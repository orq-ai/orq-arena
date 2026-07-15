"""Tournament driver, full round-robin, per-round Bradley-Terry ELO.

Every pair fights once; every judged round (win or tie) feeds the rating.
The HP show is presentation, the leaderboard comes from ~C(n,2)·max_rounds
reconciled panel verdicts, not from 7 knockout outcomes.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import time
from itertools import combinations
from pathlib import Path

from evaluatorq import PairwiseComparison, build_report

from ..arena.battle import Battle
from ..config import ArenaConfig
from ..data.log import BattleLog
from ..data.prompts import PromptItem
from ..data.schemas import BattleRecord
from ..events import ArenaEvent, StandingsUpdated, TournamentEnded
from ..roster import CandidateSpec
from ..providers.orq_gateway import OrqGateway
from .elo import bootstrap_ci, bradley_terry_mle, build_wins_matrix, style_controlled_elo

Outcome = tuple[str, str, str, str]  # (name, name, 'winner' | 'tie', category)


def round_robin_schedule(
    candidates: list[CandidateSpec], seed: int = 42
) -> list[tuple[CandidateSpec, CandidateSpec]]:
    """Every pair once, in a seeded shuffled order."""
    schedule = list(combinations(candidates, 2))
    random.Random(seed).shuffle(schedule)
    return schedule


def outcomes_from_records(records: list[BattleRecord], name_a: str, name_b: str) -> list[Outcome]:
    """Per-round rating feed: wins and ties count, inconclusive/void don't."""
    out: list[Outcome] = []
    for rec in records:
        cat = rec.prompt_category or "general"
        if rec.majority_verdict == "A":
            out.append((name_a, name_b, "winner", cat))
        elif rec.majority_verdict == "B":
            out.append((name_b, name_a, "winner", cat))
        elif rec.majority_verdict == "tie":
            out.append((name_a, name_b, "tie", cat))
    return out


def _triples(outcomes: list[Outcome]) -> list[tuple[str, str, str]]:
    return [(a, b, kind) for a, b, kind, _ in outcomes]


# Slices thinner than this print noise, not signal.
MIN_CATEGORY_COMPARISONS = 20


def elo_by_category(outcomes: list[Outcome], names: list[str]) -> dict[str, dict[str, float]]:
    """Bradley-Terry per prompt category, skipping under-sampled slices."""
    by_cat: dict[str, list[Outcome]] = {}
    for o in outcomes:
        by_cat.setdefault(o[3], []).append(o)
    return {
        cat: bradley_terry_mle(build_wins_matrix(_triples(rows)), names)
        for cat, rows in sorted(by_cat.items())
        if len(rows) >= MIN_CATEGORY_COMPARISONS
    }


def _rebuild_comparisons(records: list[BattleRecord]) -> list[PairwiseComparison]:
    comps: list[PairwiseComparison] = []
    for rec in records:
        if rec.error is not None:
            continue
        comps.append(PairwiseComparison(winner=rec.majority_verdict, votes=rec.judge_votes))
    return comps


def _final_report(
    cfg: ArenaConfig,
    records: list[BattleRecord],
    outcomes: list[Outcome],
    names: list[str],
    preflight: dict | None = None,
) -> dict:
    # A candidate "thinks" if its config says so OR the preflight probe saw it
    # thinking anyway (vendor defaults the router can't disable).
    probed = {
        name: bool(r.get("thinks"))
        for name, r in ((preflight or {}).get("thinking_probe") or {}).items()
    }
    comparisons = _rebuild_comparisons(records)
    jury = build_report(comparisons) if comparisons else None

    from ..analysis.kappa import cohen_kappa_pairs, fleiss_kappa

    vote_rounds = [r.judge_votes for r in records if r.error is None]
    fleiss = fleiss_kappa(vote_rounds, list(cfg.judges))
    cohen = cohen_kappa_pairs(vote_rounds, list(cfg.judges))

    tokens: dict[str, list[int]] = {}
    reasoning: dict[str, list[int]] = {}
    for rec in records:
        if rec.error is not None:
            continue
        tokens.setdefault(rec.model_a, []).append(rec.tokens_a_out)
        tokens.setdefault(rec.model_b, []).append(rec.tokens_b_out)
        reasoning.setdefault(rec.model_a, []).append(rec.tokens_a_reasoning)
        reasoning.setdefault(rec.model_b, []).append(rec.tokens_b_reasoning)

    grid: dict[str, dict[str, float]] = {n: {m: 0.0 for m in names} for n in names}
    for a, b, kind, _cat in outcomes:
        if kind == "winner":
            grid[a][b] += 1.0
        else:
            grid[a][b] += 0.5
            grid[b][a] += 0.5

    model_in = sum(r.tokens_a_in + r.tokens_b_in for r in records)
    model_out = sum(r.tokens_a_out + r.tokens_b_out for r in records)
    judge_in = sum(r.judge_tokens_in for r in records)
    judge_out = sum(r.judge_tokens_out for r in records)

    cat_counts: dict[str, int] = {}
    for o in outcomes:
        cat_counts[o[3]] = cat_counts.get(o[3], 0) + 1

    by_model = {w.short_model: w for w in cfg.candidates}
    orc_by_model = {w.short_model: w.name for w in cfg.candidates}
    y_by_verdict = {"A": 1.0, "B": 0.0, "tie": 0.5}
    style_rows = [
        (
            orc_by_model[rec.model_a],
            orc_by_model[rec.model_b],
            y_by_verdict[rec.majority_verdict],
            len(rec.response_a or ""),
            len(rec.response_b or ""),
        )
        for rec in records
        if rec.error is None
        and rec.majority_verdict in y_by_verdict
        and rec.model_a in orc_by_model
        and rec.model_b in orc_by_model
    ]
    elo_sc, length_coef = style_controlled_elo(style_rows, names)
    return {
        "elo_ci": bootstrap_ci(_triples(outcomes), names),
        "elo_style_controlled": elo_sc if style_rows else None,
        "length_coef": length_coef if style_rows else None,
        "elo_by_category": elo_by_category(outcomes, names),
        "category_counts": cat_counts,
        "tokens": {
            "models_in": model_in,
            "models_out": model_out,
            "judges_in": judge_in,
            "judges_out": judge_out,
        },
        "jury": jury.model_dump() if jury else None,
        "mean_agreement": jury.mean_agreement if jury else None,
        "fleiss": fleiss,
        "cohen": cohen,
        "verbosity": {orc_by_model.get(m, m): sum(v) / len(v) for m, v in tokens.items() if v},
        "reasoning_tokens": {
            orc_by_model.get(m, m): sum(v) / len(v) for m, v in reasoning.items() if v
        },
        "win_grid": grid,
        "thinking": {
            w.name: (w.thinking_enabled or probed.get(w.name, False)) for w in cfg.candidates
        },
        # Explicitly reasoning-off models (unless the probe caught them thinking
        # anyway): the report flags these so a forced-off model isn't read as a
        # weak one that ran on equal footing.
        "thinking_off": {
            w.name: True
            for w in cfg.candidates
            if w.thinking_disabled and not probed.get(w.name, False)
        },
        "mixed_pool": len({w.thinking_enabled or probed.get(w.name, False) for w in cfg.candidates})
        > 1,
        "error_rounds": sum(1 for r in records if r.error is not None),
        "rated_rounds": len(outcomes),
        "by_model_names": {w.short_model: w.name for w in by_model.values()},
    }


def rebuild_from_log(
    cfg: ArenaConfig,
    records: list[BattleRecord],
    preflight: dict | None = None,
) -> tuple[dict[str, float], dict]:
    """Recompute (elo, report) from a recorded log, keyed exactly like the
    live run (display names), so a regenerated report page matches the one
    the run wrote. The single rebuild path for ``orq-arena report``.
    """
    alias = {w.short_model: w.name for w in cfg.candidates}
    outcomes: list[Outcome] = []
    for rec in records:
        if rec.error is not None:
            continue
        outcomes.extend(
            outcomes_from_records(
                [rec], alias.get(rec.model_a, rec.model_a), alias.get(rec.model_b, rec.model_b)
            )
        )
    names = sorted({alias.get(m, m) for r in records for m in (r.model_a, r.model_b)})
    elo = bradley_terry_mle(build_wins_matrix(_triples(outcomes)), names)
    report = _final_report(cfg, records, outcomes, names, preflight=preflight)
    return elo, report


def _write_manifest(
    path: Path,
    *,
    cfg: ArenaConfig,
    prompts: list[PromptItem],
    seed: int,
    tournament_id: str,
    started_at: float,
    finished_at: float | None = None,
    report: dict | None = None,
    preflight: dict | None = None,
    dataset: dict | None = None,
) -> None:
    try:
        from importlib.metadata import version

        evq_version = version("evaluatorq")
    except Exception:
        evq_version = "unknown"
    manifest = {
        "tournament_id": tournament_id,
        "started_at": started_at,
        "seed": seed,
        "config_sha256": hashlib.sha256(cfg.model_dump_json().encode("utf-8")).hexdigest()[:16],
        "prompts_sha256": hashlib.sha256(
            "\n".join(p.text for p in prompts).encode("utf-8")
        ).hexdigest()[:16],
        "prompt_count": len(prompts),
        "candidates": {
            c.name: {"model": c.model_id, "reasoning": c.reasoning or "vendor-default"}
            for c in cfg.candidates
        },
        "judges": list(cfg.judges),
        "replacement_judges": list(cfg.replacement_judges),
        "min_successful_judges": cfg.min_successful_judges,
        "evaluatorq_version": evq_version,
    }
    if finished_at is not None:
        manifest["finished_at"] = finished_at
    if dataset is not None:
        manifest["dataset"] = dataset
    if preflight is not None:
        manifest["preflight"] = preflight
    if report is not None:
        manifest["mean_agreement"] = report.get("mean_agreement")
        manifest["error_rounds"] = report.get("error_rounds")
        manifest["rated_rounds"] = report.get("rated_rounds")
        manifest["category_counts"] = report.get("category_counts")
        manifest["fleiss"] = report.get("fleiss")
        manifest["tokens"] = report.get("tokens")
        manifest["length_coef"] = report.get("length_coef")
    path.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")


async def run_tournament(
    *,
    cfg: ArenaConfig,
    prompts: list[PromptItem],
    battle_log_path: str,
    events: asyncio.Queue[ArenaEvent],
    seed: int = 42,
    concurrency: int = 1,
    preflight: dict | None = None,
    dataset: dict | None = None,
) -> dict[str, float]:
    """Run the full round-robin; return final ELO ratings by orc name.

    ``concurrency`` > 1 runs matches in parallel under a semaphore, headless
    runs only; the TUI passes 1 so the show stays one fight at a time.
    """
    if len(cfg.candidates) < 2:
        raise ValueError(f"Need at least 2 candidates, got {len(cfg.candidates)}")
    if not prompts:
        raise ValueError("Prompt set is empty")

    gateway = OrqGateway(cfg.gateway)
    log = BattleLog(battle_log_path)
    manifest_path = Path(battle_log_path).with_suffix(".run.json")

    names = [w.name for w in cfg.candidates]
    candidate_by_name = {w.name: w for w in cfg.candidates}
    use_swiss = len(cfg.candidates) > 8
    schedule = [] if use_swiss else round_robin_schedule(cfg.candidates, seed)
    matches_total = cfg.swiss_rounds * (len(names) // 2) if use_swiss else len(schedule)
    started_at = time.time()
    tournament_id = f"bench-{int(started_at)}"
    _write_manifest(
        manifest_path,
        cfg=cfg,
        prompts=prompts,
        seed=seed,
        tournament_id=tournament_id,
        started_at=started_at,
        preflight=preflight,
        dataset=dataset,
    )

    rng = random.Random(seed)
    outcomes: list[Outcome] = []
    all_records: list[BattleRecord] = []
    elo: dict[str, float] = {n: 1000.0 for n in names}

    def _draw_slice() -> list[PromptItem]:
        shuffled = list(prompts)
        rng.shuffle(shuffled)
        return shuffled[: cfg.match.max_rounds]

    sem = asyncio.Semaphore(max(1, concurrency))
    state_lock = asyncio.Lock()
    matches_done = 0

    async def _run_match(i: int, w_a, w_b, fight_prompts: list[PromptItem]):
        nonlocal elo, matches_done
        async with sem:
            battle = Battle(
                cfg=cfg,
                gateway=gateway,
                candidate_a=w_a,
                candidate_b=w_b,
                prompts=fight_prompts,
                match_id=f"M{i}",
                round_name=f"match {i}/{matches_total}",
                tournament_id=tournament_id,
                events=events,
            )
            result = await battle.run()
            async with state_lock:
                log.append_many(result.battles)
                all_records.extend(result.battles)
                outcomes.extend(outcomes_from_records(result.battles, w_a.name, w_b.name))
                if outcomes:
                    elo = bradley_terry_mle(build_wins_matrix(_triples(outcomes)), names)
                matches_done += 1
                await events.put(
                    StandingsUpdated(
                        elo=elo, matches_done=matches_done, matches_total=matches_total
                    )
                )
            return result

    if not use_swiss:
        # Slices pre-drawn so the schedule is seed-stable regardless of
        # completion order under concurrency.
        slices = [_draw_slice() for _ in schedule]
        if concurrency <= 1:
            for i, (w_a, w_b) in enumerate(schedule, 1):
                await _run_match(i, w_a, w_b, slices[i - 1])
        else:
            await asyncio.gather(
                *(
                    _run_match(i, w_a, w_b, slices[i - 1])
                    for i, (w_a, w_b) in enumerate(schedule, 1)
                )
            )
    else:
        # Pools >8: Swiss, pair by score group between rounds (decision 15:
        # pairing consumes match winners; the rating stays per-round).
        from .swiss import SwissScheduler

        scheduler = SwissScheduler(names)
        match_no = 0
        for _swiss_round in range(1, cfg.swiss_rounds + 1):
            pairs = scheduler.next_round_pairs()
            if not pairs:
                break
            tasks = []
            for a, b in pairs:
                match_no += 1
                tasks.append(
                    _run_match(match_no, candidate_by_name[a], candidate_by_name[b], _draw_slice())
                )
            results = await asyncio.gather(*tasks)
            for res in results:
                if res.by == "draw":
                    scheduler.record_outcome(res.winner.name, res.loser.name, tie=True)
                else:
                    scheduler.record_outcome(res.winner.name, res.loser.name)

    report = _final_report(cfg, all_records, outcomes, names, preflight=preflight)
    _write_manifest(
        manifest_path,
        cfg=cfg,
        prompts=prompts,
        seed=seed,
        tournament_id=tournament_id,
        started_at=started_at,
        finished_at=time.time(),
        report=report,
        preflight=preflight,
        dataset=dataset,
    )

    try:
        from ..providers.models_list import fetch_price_map
        from ..report import write_report

        try:
            prices = await fetch_price_map(cfg.gateway)
        except Exception:
            prices = {}
        write_report(
            prices=prices or None,
            cfg=cfg,
            records=all_records,
            elo=elo,
            report=report,
            manifest=json.loads(manifest_path.read_text(encoding="utf-8")),
            log_path=battle_log_path,
        )
    except Exception as exc:  # a finished run must never die on its report page
        from loguru import logger

        logger.warning(f"report page not written: {exc}")

    champion = max(elo, key=lambda n: elo[n]) if elo else ""
    await events.put(
        TournamentEnded(
            champion=champion,
            elo=elo,
            battle_log_path=str(battle_log_path),
            report=report,
        )
    )
    return elo
