"""Tournament driver — walks the bracket, runs each match, updates ELO."""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field

from ..arena.battle import Battle
from ..config import ArenaConfig
from ..data.log import BattleLog
from ..data.schemas import BattleRecord
from ..events import ArenaEvent, BracketUpdated, TournamentEnded, TournamentStarted
from ..providers.orq_gateway import OrqGateway
from .bracket import Bracket
from .elo import bradley_terry_mle, build_wins_matrix


@dataclass
class TournamentState:
    tournament_id: str
    bracket: Bracket
    matches_run: int = 0
    match_outcomes: list[tuple[str, str, str]] = field(default_factory=list)
    all_battles: list[BattleRecord] = field(default_factory=list)


async def run_tournament(
    *,
    cfg: ArenaConfig,
    prompts: list[str],
    battle_log_path: str,
    events: asyncio.Queue[ArenaEvent],
    seed: int = 42,
) -> dict[str, float]:
    """Drive the full 8-warrior bracket; return final ELO ratings by orc name."""
    if len(cfg.warriors) != 8:
        raise ValueError(f"Need 8 warriors, got {len(cfg.warriors)}")
    if not prompts:
        raise ValueError("Prompt set is empty")

    gateway = OrqGateway(cfg.gateway)
    log = BattleLog(battle_log_path)

    warrior_by_name = {w.orc_name: w for w in cfg.warriors}
    names = [w.orc_name for w in cfg.warriors]
    bracket = Bracket.seed_eight(names)

    await events.put(TournamentStarted(warrior_names=names))
    await events.put(BracketUpdated(rounds=bracket.as_display()))

    rng = random.Random(seed)
    tournament_id = f"tour-{int(time.time())}"
    outcomes: list[tuple[str, str, str]] = []

    while True:
        matchup = bracket.next_open_match()
        if matchup is None:
            break
        w_a = warrior_by_name[bracket.name_for_seed(matchup.seed_a)]
        w_b = warrior_by_name[bracket.name_for_seed(matchup.seed_b)]

        # Shuffle a fresh prompt slice for this match so fights feel distinct.
        shuffled = list(prompts)
        rng.shuffle(shuffled)
        fight_prompts = shuffled[: cfg.match.max_rounds]

        battle = Battle(
            cfg=cfg,
            gateway=gateway,
            warrior_a=w_a,
            warrior_b=w_b,
            prompts=fight_prompts,
            match_id=matchup.match_id,
            round_name=matchup.round_name,
            tournament_id=tournament_id,
            events=events,
        )
        result = await battle.run()
        log.append_many(result.battles)

        winner_seed = matchup.seed_a if result.winner.orc_name == w_a.orc_name else matchup.seed_b
        bracket.record_winner(matchup.match_id, winner_seed)
        outcomes.append((result.winner.orc_name, result.loser.orc_name, "winner"))

        await events.put(BracketUpdated(rounds=bracket.as_display()))

    # ELO over all match outcomes
    wins = build_wins_matrix(outcomes)
    elo = bradley_terry_mle(wins, names)

    await events.put(
        TournamentEnded(
            champion=bracket.champion() or "",
            elo=elo,
            battle_log_path=str(battle_log_path),
        )
    )
    return elo
