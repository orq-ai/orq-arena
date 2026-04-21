"""Per-match battle engine.

One ``Battle`` owns a single fight: it drives the turn loop, tracks HP,
invokes the judge panel, and pushes typed events onto an ``asyncio.Queue``
that the TUI (or any future renderer) subscribes to.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from typing import Iterable

from ..config import ArenaConfig
from ..data.schemas import BattleRecord
from ..events import (
    ArenaEvent,
    JudgeVerdictEvent,
    MatchResolved,
    MatchStarted,
    ResponseChunk,
    ResponseComplete,
    TurnPrompt,
    TurnResolved,
)
from ..judges.panel import filter_self_judges, majority_vote, run_panel
from ..orcs.roster import WarriorSpec
from ..providers.orq_gateway import OrqGateway
from .damage import compute_damage


@dataclass
class MatchResult:
    winner: WarriorSpec
    loser: WarriorSpec
    by: str  # 'ko' | 'round_cap'
    final_hp_a: int
    final_hp_b: int
    battles: list[BattleRecord] = field(default_factory=list)


def _prompt_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


async def _generate_side(
    *,
    gateway: OrqGateway,
    warrior: WarriorSpec,
    prompt: str,
    max_tokens: int,
    events: asyncio.Queue[ArenaEvent],
    match_id: str,
    side: str,  # 'a' | 'b'
) -> tuple[str, int, str | None]:
    """Stream one warrior's response; return (full_text, tokens_out, error)."""
    chunks: list[str] = []
    error: str | None = None
    try:
        async for piece in gateway.stream_completion(
            model=warrior.model_id,
            prompt=prompt,
            max_tokens=max_tokens,
        ):
            chunks.append(piece)
            await events.put(
                ResponseChunk(match_id=match_id, side=side, text=piece)  # type: ignore[arg-type]
            )
    except Exception as exc:
        error = str(exc)

    full = "".join(chunks)
    # We don't have usage tokens from streaming; approximate by char/4.
    tokens_out = max(1, len(full) // 4) if full else 0
    await events.put(
        ResponseComplete(
            match_id=match_id,
            side=side,  # type: ignore[arg-type]
            full_text=full,
            tokens_out=tokens_out,
            error=error,
        )
    )
    return full, tokens_out, error


class Battle:
    """Drives a single match until KO or round cap."""

    def __init__(
        self,
        *,
        cfg: ArenaConfig,
        gateway: OrqGateway,
        warrior_a: WarriorSpec,
        warrior_b: WarriorSpec,
        prompts: Iterable[str],
        match_id: str,
        round_name: str,
        tournament_id: str,
        events: asyncio.Queue[ArenaEvent],
    ) -> None:
        self.cfg = cfg
        self.gateway = gateway
        self.a = warrior_a
        self.b = warrior_b
        self.prompts = list(prompts)
        self.match_id = match_id
        self.round_name = round_name
        self.tournament_id = tournament_id
        self.events = events

    async def run(self) -> MatchResult:
        rules = self.cfg.match
        hp_a = hp_b = rules.starting_hp
        battles: list[BattleRecord] = []
        rounds_counted = 0

        await self.events.put(
            MatchStarted(
                match_id=self.match_id,
                round_name=self.round_name,  # type: ignore[arg-type]
                warrior_a=self.a.orc_name,
                warrior_b=self.b.orc_name,
            )
        )

        prompt_iter = iter(self.prompts)
        while hp_a > 0 and hp_b > 0 and rounds_counted < rules.max_rounds:
            try:
                prompt = next(prompt_iter)
            except StopIteration:
                break

            round_number = rounds_counted + 1
            await self.events.put(
                TurnPrompt(match_id=self.match_id, round_number=round_number, prompt=prompt)
            )

            # Generate both sides concurrently
            (resp_a, tok_a, err_a), (resp_b, tok_b, err_b) = await asyncio.gather(
                _generate_side(
                    gateway=self.gateway,
                    warrior=self.a,
                    prompt=prompt,
                    max_tokens=self.cfg.gateway.warrior_max_tokens,
                    events=self.events,
                    match_id=self.match_id,
                    side="a",
                ),
                _generate_side(
                    gateway=self.gateway,
                    warrior=self.b,
                    prompt=prompt,
                    max_tokens=self.cfg.gateway.warrior_max_tokens,
                    events=self.events,
                    match_id=self.match_id,
                    side="b",
                ),
            )

            # Judge panel
            verdicts = await run_panel(
                gateway=self.gateway,
                judges=self.cfg.judges,
                user_query=prompt,
                response_a=resp_a,
                response_b=resp_b,
                system_prompt=self.cfg.judge_system_prompt,
                max_tokens=self.cfg.gateway.judge_max_tokens,
            )

            # Emit each verdict for the TUI
            for v in verdicts:
                await self.events.put(
                    JudgeVerdictEvent(
                        match_id=self.match_id,
                        judge_name=v.judge_name,
                        verdict=v.verdict,
                        reasoning=v.reasoning,
                    )
                )

            # Self-judge exclusion (judge model == contestant model)
            contestants = {self.a.model_id, self.b.model_id}
            verdicts = filter_self_judges(verdicts, contestants)
            majority = majority_vote(verdicts)

            damage = compute_damage(majority=majority, verdicts=verdicts, rules=rules)
            hp_a_before, hp_b_before = hp_a, hp_b
            if damage.loser_side == "a":
                hp_a = max(0, hp_a - damage.damage)
            elif damage.loser_side == "b":
                hp_b = max(0, hp_b - damage.damage)

            if damage.counts_toward_cap:
                rounds_counted += 1

            battle = BattleRecord(
                prompt_hash=_prompt_hash(prompt),
                prompt_text=prompt,
                model_a=self.a.short_model,
                model_b=self.b.short_model,
                response_a=resp_a,
                response_b=resp_b,
                judge_verdicts=verdicts,
                majority_verdict=majority,
                winner=(
                    self.a.short_model if majority == "A"
                    else self.b.short_model if majority == "B"
                    else "tie" if majority == "TIE"
                    else "discard"
                ),
                tokens_a_out=tok_a,
                tokens_b_out=tok_b,
                tournament_id=self.tournament_id,
                match_id=self.match_id,
                round_number=round_number,
                damage_dealt=damage.damage,
                hp_a_before=hp_a_before,
                hp_b_before=hp_b_before,
                hp_a_after=hp_a,
                hp_b_after=hp_b,
            )
            battles.append(battle)

            await self.events.put(
                TurnResolved(
                    match_id=self.match_id,
                    round_number=round_number,
                    majority=majority,
                    verdicts=verdicts,
                    damage_dealt=damage.damage,
                    loser_side=damage.loser_side,  # type: ignore[arg-type]
                    hp_a=hp_a,
                    hp_b=hp_b,
                )
            )

        # Resolve winner
        if hp_a <= 0 and hp_b <= 0:
            # Edge case: both KO'd in the same round — higher pre-damage HP wins.
            # We don't track that precisely; fall back to B wins (arbitrary).
            winner, loser, by = self.b, self.a, "ko"
        elif hp_a <= 0:
            winner, loser, by = self.b, self.a, "ko"
        elif hp_b <= 0:
            winner, loser, by = self.a, self.b, "ko"
        elif hp_a == hp_b:
            winner, loser, by = self.a, self.b, "round_cap"  # seed advantage
        elif hp_a > hp_b:
            winner, loser, by = self.a, self.b, "round_cap"
        else:
            winner, loser, by = self.b, self.a, "round_cap"

        await self.events.put(
            MatchResolved(
                match_id=self.match_id,
                winner=winner.orc_name,
                loser=loser.orc_name,
                by=by,  # type: ignore[arg-type]
                final_hp_a=hp_a,
                final_hp_b=hp_b,
            )
        )

        return MatchResult(
            winner=winner,
            loser=loser,
            by=by,
            final_hp_a=hp_a,
            final_hp_b=hp_b,
            battles=battles,
        )
