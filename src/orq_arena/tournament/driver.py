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
from typing import Literal

from evaluatorq import PairwiseComparison, build_report
from pydantic import ValidationError

from ..arena.battle import Battle
from ..candidates import CandidateSpec
from ..config import ArenaConfig
from ..data.log import BattleLog
from ..data.prompts import PromptItem
from ..data.schemas import BattleRecord
from ..events import ArenaEvent, StandingsUpdated, TournamentEnded
from ..providers.models_list import catalog_host
from ..providers.orq_gateway import OrqGateway
from .elo import (
    bootstrap_ci,
    bootstrap_draws,
    bradley_terry_mle,
    build_wins_matrix,
    ci_from_draws,
    difference_from_draws,
    style_controlled_elo,
)

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


def elo_by_category(outcomes: list[Outcome]) -> dict[str, dict[str, float]]:
    """Bradley-Terry per prompt category, skipping under-sampled slices.

    Each slice rates only the models that actually appear in it; a model
    absent from a category is left out, not seeded at 1000.
    """
    by_cat: dict[str, list[Outcome]] = {}
    for o in outcomes:
        by_cat.setdefault(o[3], []).append(o)
    out: dict[str, dict[str, float]] = {}
    for cat, rows in sorted(by_cat.items()):
        if len(rows) < MIN_CATEGORY_COMPARISONS:
            continue
        cat_names = sorted({x for a, b, _kind, _cat in rows for x in (a, b)})
        out[cat] = bradley_terry_mle(build_wins_matrix(_triples(rows)), cat_names)
    return out


def _rebuild_comparisons(records: list[BattleRecord]) -> list[PairwiseComparison]:
    comps: list[PairwiseComparison] = []
    for rec in records:
        if rec.error is not None:
            continue
        comps.append(
            PairwiseComparison.model_validate(
                {"winner": rec.majority_verdict, "votes": rec.judge_votes}
            )
        )
    return comps


def record_names(records: list[BattleRecord], candidates: list[CandidateSpec]) -> dict[str, str]:
    """Map each record's stored model key to its display name.

    Keyed on the full router id where the record carries one, because short
    names collide across providers (openai/gpt-oss-120b vs groq/gpt-oss-120b)
    and a short-name map would rate two different models as one. v3 logs have
    no ids, so those fall back to the short name they do have.
    """
    by_id = {c.model_id: c.name for c in candidates}
    # Short names are only usable when they identify one candidate. A collision
    # resolves to nothing rather than to whichever candidate happened to be last.
    short_counts: dict[str, int] = {}
    for c in candidates:
        short_counts[c.short_model] = short_counts.get(c.short_model, 0) + 1
    by_short = {c.short_model: c.name for c in candidates if short_counts[c.short_model] == 1}

    alias: dict[str, str] = {}
    for rec in records:
        for short, full in ((rec.model_a, rec.model_a_id), (rec.model_b, rec.model_b_id)):
            key = full or short
            alias[key] = (by_id.get(full, "") if full else by_short.get(short, "")) or short
    return alias


def rating_key(rec: BattleRecord, side: Literal["a", "b"]) -> str:
    """The key a record is rated under: its full id when it has one.

    Everything downstream of the rating (verbosity, style rows, cost, speed)
    keys on this too, so a colliding short name cannot merge two models in one
    view while the leaderboard shows them apart.
    """
    return (rec.model_a_id or rec.model_a) if side == "a" else (rec.model_b_id or rec.model_b)


def _top_difference(draws: list[dict[str, float]], ranked: list[tuple[str, float]]) -> dict | None:
    """Bootstrap of (champion - runner-up), from the report's own draws.

    Carries the two names it was computed from, so a reader can never pair
    these numbers with a different runner-up than the one measured.
    """
    if len(ranked) < 2 or not draws:
        return None
    champion, runner = ranked[0][0], ranked[1][0]
    diff = difference_from_draws(draws, champion, runner)
    return {
        "champion": champion,
        "runner_up": runner,
        "lo": diff.lo,
        "hi": diff.hi,
        "win_rate": diff.win_rate,
        "separated": diff.separated,
    }


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
        tokens.setdefault(rating_key(rec, "a"), []).append(rec.tokens_a_out)
        tokens.setdefault(rating_key(rec, "b"), []).append(rec.tokens_b_out)
        reasoning.setdefault(rating_key(rec, "a"), []).append(rec.tokens_a_reasoning)
        reasoning.setdefault(rating_key(rec, "b"), []).append(rec.tokens_b_reasoning)

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

    # Same key the rating uses. Building these from short_model merged two
    # providers of one model in every view except the leaderboard: one
    # verbosity figure averaging both, and style rows that were self-matches.
    alias = record_names(records, cfg.candidates)
    y_by_verdict = {"A": 1.0, "B": 0.0, "tie": 0.5}
    style_rows = [
        (
            alias[rating_key(rec, "a")],
            alias[rating_key(rec, "b")],
            y_by_verdict[rec.majority_verdict],
            len(rec.response_a or ""),
            len(rec.response_b or ""),
        )
        for rec in records
        if rec.error is None
        and rec.majority_verdict in y_by_verdict
        and rating_key(rec, "a") in alias
        and rating_key(rec, "b") in alias
    ]
    elo_sc, length_coef = style_controlled_elo(style_rows, names)
    # One bootstrap, summarized two ways: the marginal intervals below and the
    # top-two difference. Resampling separately per question would leave them
    # agreeing only for as long as both call sites passed the same seed.
    triples = _triples(outcomes)
    draws = bootstrap_draws(triples, names) if triples else []
    ranked_now = sorted(
        bradley_terry_mle(build_wins_matrix(triples), names).items(),
        key=lambda kv: kv[1],
        reverse=True,
    )
    return {
        "elo_ci": ci_from_draws(draws, names) if draws else bootstrap_ci(triples, names),
        # Whether the top two actually differ is a question about their
        # difference, not about whether two marginal intervals happen to touch.
        "top_difference": _top_difference(draws, ranked_now),
        "elo_style_controlled": elo_sc if style_rows else None,
        "length_coef": length_coef if style_rows else None,
        "elo_by_category": elo_by_category(outcomes),
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
        "verbosity": {alias.get(m, m): sum(v) / len(v) for m, v in tokens.items() if v},
        "reasoning_tokens": {alias.get(m, m): sum(v) / len(v) for m, v in reasoning.items() if v},
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
        "by_model_names": dict(alias),
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
    alias = record_names(records, cfg.candidates)
    outcomes: list[Outcome] = []
    for rec in records:
        if rec.error is not None:
            continue
        outcomes.extend(
            outcomes_from_records(
                [rec],
                alias[rating_key(rec, "a")],
                alias[rating_key(rec, "b")],
            )
        )
    names = sorted({alias[rating_key(r, s)] for r in records for s in ("a", "b")})
    elo = bradley_terry_mle(build_wins_matrix(_triples(outcomes)), names)
    report = _final_report(cfg, records, outcomes, names, preflight=preflight)
    return elo, report


MANIFEST_SUFFIX = ".run.json"


def manifest_path_for(log_path: str | Path) -> Path:
    return Path(log_path).with_suffix(MANIFEST_SUFFIX)


def config_sha256(cfg: ArenaConfig) -> str:
    return hashlib.sha256(cfg.model_dump_json().encode("utf-8")).hexdigest()[:16]


def read_manifest(log_path: str | Path) -> dict:
    """The run's manifest, or ``{}`` when it's missing or unreadable."""
    try:
        data = json.loads(manifest_path_for(log_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


# Exactly the fields a rebuild reads. Everything else in a manifest's recorded
# config stays local, so a forwarded manifest can describe a run without also
# steering where this machine sends its API key (see config_from_manifest).
IDENTITY_FIELDS = ("candidates", "judges", "replacement_judges", "min_successful_judges")

IdentitySource = Literal["manifest", "manifest-partial", "config"]


def _identity_from_recorded_config(recorded: dict) -> dict | None:
    """Identity fields out of a manifest's full recorded config."""
    if not isinstance(recorded.get("candidates"), list) or not recorded.get("judges"):
        return None
    return {k: recorded[k] for k in IDENTITY_FIELDS if k in recorded}


def _identity_from_candidate_map(manifest: dict) -> dict | None:
    """Identity fields out of a pre-config-blob manifest's own bookkeeping.

    Those manifests recorded the pool as ``{display name: {model, reasoning}}``
    with reasoning collapsed to the string ``"vendor-default"`` when unset, which
    still pins every field a rebuild reads.
    """
    candidates = manifest.get("candidates") or {}
    if not candidates or not manifest.get("judges"):
        return None
    identity = {
        "candidates": [
            {
                "model_id": spec["model"],
                "name": name,
                "reasoning": None
                if spec.get("reasoning") == "vendor-default"
                else spec.get("reasoning"),
            }
            for name, spec in candidates.items()
            if isinstance(spec, dict) and spec.get("model")
        ],
        "judges": list(manifest["judges"]),
        "replacement_judges": list(manifest.get("replacement_judges") or []),
    }
    if manifest.get("min_successful_judges") is not None:
        identity["min_successful_judges"] = manifest["min_successful_judges"]
    return identity


def config_from_manifest(
    manifest: dict, fallback: ArenaConfig | None = None
) -> tuple[ArenaConfig | None, IdentitySource]:
    """The config the run actually used, so a rebuilt report describes that run.

    Rebuilds read model names, the judge panel and the thinking flags from the
    manifest the run wrote, never from a YAML that may have moved on since.

    Only ``IDENTITY_FIELDS`` are taken from the manifest. The gateway in
    particular is never adopted: a manifest is meant to be forwarded (bug
    reports ask for one), and rebuilding through its ``base_url`` would let a
    file someone else wrote choose the host this machine sends ``ORQ_API_KEY``
    to on the report's catalog read.

    Returns ``(cfg, source)``: ``manifest`` (identity from the recorded
    config), ``manifest-partial`` (identity reconstructed from a pre-config-blob
    manifest's candidate/judge entries), or ``config`` (nothing usable on disk,
    the caller should say so out loud). ``cfg`` is None only when the manifest
    is unusable and no fallback config was supplied.
    """
    recorded = manifest.get("config")
    sources: list[tuple[dict | None, IdentitySource]] = [
        (
            _identity_from_recorded_config(recorded) if isinstance(recorded, dict) else None,
            "manifest",
        ),
        (_identity_from_candidate_map(manifest), "manifest-partial"),
    ]
    for identity, source in sources:
        if identity is None:
            continue
        # ponytail: everything outside IDENTITY_FIELDS (gateway, criteria, match
        # rules) comes from the local config. None of it reaches the rating, so
        # the rebuild is exact; widen this only for a field a report actually reads.
        merged = fallback.model_dump() if fallback is not None else {}
        merged.update(identity)
        try:
            return ArenaConfig.model_validate(merged), source
        except ValidationError:
            continue  # a hand-edited manifest is not worth dying over

    return fallback, "config"


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
    prompts_path: str = "",
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
        "config_sha256": config_sha256(cfg),
        # The whole config, so a report rebuilt months later describes this run
        # rather than whatever the YAML says by then.
        "config": cfg.model_dump(mode="json"),
        # Category rides in the hash: two banks with identical prompts but
        # different category labels are different prompt sets, and rate
        # differently per category.
        "prompts_sha256": hashlib.sha256(
            "\n".join(f"{p.category}\t{p.text}" for p in prompts).encode("utf-8")
        ).hexdigest()[:16],
        "prompt_count": len(prompts),
        "prompts_path": prompts_path,
        # Where this run's traffic actually went, which ORQ_BASE_URL can move.
        # Provenance only: a rebuild never adopts a manifest's host (RES-1147).
        "effective_host": catalog_host(cfg.gateway),
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
    prompts_path: str = "",
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
    manifest_path = manifest_path_for(battle_log_path)

    names = [w.name for w in cfg.candidates]
    schedule = round_robin_schedule(cfg.candidates, seed)
    matches_total = len(schedule)
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
        prompts_path=prompts_path,
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
                # Per round, not per match: a killed run keeps what it paid for.
                on_record=log.append,
            )
            result = await battle.run()
            async with state_lock:
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

    # Slices pre-drawn so the schedule is seed-stable regardless of
    # completion order under concurrency.
    slices = [_draw_slice() for _ in schedule]
    if concurrency <= 1:
        for i, (w_a, w_b) in enumerate(schedule, 1):
            await _run_match(i, w_a, w_b, slices[i - 1])
    else:
        await asyncio.gather(
            *(_run_match(i, w_a, w_b, slices[i - 1]) for i, (w_a, w_b) in enumerate(schedule, 1))
        )

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
        prompts_path=prompts_path,
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
