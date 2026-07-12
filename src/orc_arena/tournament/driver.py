"""Tournament driver — full round-robin, per-round Bradley-Terry ELO.

Every pair fights once; every judged round (win or tie) feeds the rating.
The HP show is presentation — the leaderboard comes from ~C(n,2)·max_rounds
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
from ..data.schemas import BattleRecord
from ..events import ArenaEvent, StandingsUpdated, TournamentEnded
from ..orcs.roster import WarriorSpec
from ..providers.orq_gateway import OrqGateway
from .elo import bootstrap_ci, bradley_terry_mle, build_wins_matrix

Outcome = tuple[str, str, str]  # (name, name, 'winner' | 'tie')


def round_robin_schedule(
    warriors: list[WarriorSpec], seed: int = 42
) -> list[tuple[WarriorSpec, WarriorSpec]]:
    """Every pair once, in a seeded shuffled order."""
    schedule = list(combinations(warriors, 2))
    random.Random(seed).shuffle(schedule)
    return schedule


def outcomes_from_records(
    records: list[BattleRecord], name_a: str, name_b: str
) -> list[Outcome]:
    """Per-round rating feed: wins and ties count, inconclusive/void don't."""
    out: list[Outcome] = []
    for rec in records:
        if rec.majority_verdict == "A":
            out.append((name_a, name_b, "winner"))
        elif rec.majority_verdict == "B":
            out.append((name_b, name_a, "winner"))
        elif rec.majority_verdict == "tie":
            out.append((name_a, name_b, "tie"))
    return out


def _rebuild_comparisons(records: list[BattleRecord]) -> list[PairwiseComparison]:
    comps: list[PairwiseComparison] = []
    for rec in records:
        if rec.error is not None:
            continue
        comps.append(
            PairwiseComparison(winner=rec.majority_verdict, votes=rec.judge_votes)
        )
    return comps


def _final_report(
    cfg: ArenaConfig, records: list[BattleRecord], outcomes: list[Outcome], names: list[str]
) -> dict:
    comparisons = _rebuild_comparisons(records)
    jury = build_report(comparisons) if comparisons else None

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
    for a, b, kind in outcomes:
        if kind == "winner":
            grid[a][b] += 1.0
        else:
            grid[a][b] += 0.5
            grid[b][a] += 0.5

    by_model = {w.short_model: w for w in cfg.warriors}
    return {
        "elo_ci": bootstrap_ci(outcomes, names),
        "jury": jury.model_dump() if jury else None,
        "mean_agreement": jury.mean_agreement if jury else None,
        "verbosity": {m: sum(v) / len(v) for m, v in tokens.items() if v},
        "reasoning_tokens": {m: sum(v) / len(v) for m, v in reasoning.items() if v},
        "win_grid": grid,
        "thinking": {w.orc_name: w.thinking_enabled for w in cfg.warriors},
        "mixed_pool": len({w.thinking_enabled for w in cfg.warriors}) > 1,
        "error_rounds": sum(1 for r in records if r.error is not None),
        "rated_rounds": len(outcomes),
        "by_model_names": {w.short_model: w.orc_name for w in by_model.values()},
    }


def _write_manifest(
    path: Path, *, cfg: ArenaConfig, prompts: list[str], seed: int,
    tournament_id: str, report: dict | None = None,
) -> None:
    try:
        from importlib.metadata import version

        evq_version = version("evaluatorq")
    except Exception:
        evq_version = "unknown"
    manifest = {
        "tournament_id": tournament_id,
        "started_at": time.time(),
        "seed": seed,
        "config_sha256": hashlib.sha256(
            cfg.model_dump_json().encode("utf-8")
        ).hexdigest()[:16],
        "prompts_sha256": hashlib.sha256(
            "\n".join(prompts).encode("utf-8")
        ).hexdigest()[:16],
        "prompt_count": len(prompts),
        "warriors": {w.orc_name: {"model": w.model_id, "reasoning": w.reasoning or "vendor-default"} for w in cfg.warriors},
        "judges": list(cfg.judges),
        "replacement_judges": list(cfg.replacement_judges),
        "min_successful_judges": cfg.min_successful_judges,
        "evaluatorq_version": evq_version,
    }
    if report is not None:
        manifest["mean_agreement"] = report.get("mean_agreement")
        manifest["error_rounds"] = report.get("error_rounds")
        manifest["rated_rounds"] = report.get("rated_rounds")
    path.write_text(json.dumps(manifest, indent=2, default=str))


async def run_tournament(
    *,
    cfg: ArenaConfig,
    prompts: list[str],
    battle_log_path: str,
    events: asyncio.Queue[ArenaEvent],
    seed: int = 42,
) -> dict[str, float]:
    """Run the full round-robin; return final ELO ratings by orc name."""
    if len(cfg.warriors) < 2:
        raise ValueError(f"Need at least 2 warriors, got {len(cfg.warriors)}")
    if not prompts:
        raise ValueError("Prompt set is empty")

    gateway = OrqGateway(cfg.gateway)
    log = BattleLog(battle_log_path)
    manifest_path = Path(battle_log_path).with_suffix(".run.json")

    names = [w.orc_name for w in cfg.warriors]
    schedule = round_robin_schedule(cfg.warriors, seed)
    tournament_id = f"tour-{int(time.time())}"
    _write_manifest(
        manifest_path, cfg=cfg, prompts=prompts, seed=seed, tournament_id=tournament_id
    )

    rng = random.Random(seed)
    outcomes: list[Outcome] = []
    all_records: list[BattleRecord] = []
    elo: dict[str, float] = {n: 1000.0 for n in names}

    for i, (w_a, w_b) in enumerate(schedule, 1):
        shuffled = list(prompts)
        rng.shuffle(shuffled)
        fight_prompts = shuffled[: cfg.match.max_rounds]

        battle = Battle(
            cfg=cfg,
            gateway=gateway,
            warrior_a=w_a,
            warrior_b=w_b,
            prompts=fight_prompts,
            match_id=f"M{i}",
            round_name=f"match {i}/{len(schedule)}",
            tournament_id=tournament_id,
            events=events,
        )
        result = await battle.run()
        log.append_many(result.battles)
        all_records.extend(result.battles)

        outcomes.extend(outcomes_from_records(result.battles, w_a.orc_name, w_b.orc_name))
        if outcomes:
            elo = bradley_terry_mle(build_wins_matrix(outcomes), names)
        await events.put(
            StandingsUpdated(elo=elo, matches_done=i, matches_total=len(schedule))
        )

    report = _final_report(cfg, all_records, outcomes, names)
    _write_manifest(
        manifest_path, cfg=cfg, prompts=prompts, seed=seed,
        tournament_id=tournament_id, report=report,
    )

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
