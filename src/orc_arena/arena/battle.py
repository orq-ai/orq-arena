"""Per-match battle engine.

One ``Battle`` owns a single fight: it drives the turn loop, tracks HP,
invokes the evaluatorq pairwise jury, and pushes typed events onto an
``asyncio.Queue`` that the TUI subscribes to.

Judging: each round's A/B pair goes through ``llm_jury_pairwise`` — every
judge sees both orderings, a judge that flips abstains (and is recorded), and
fewer than ``min_successful_judges`` decisive votes yields ``inconclusive``.
A round whose generation fails after one retry is **voided**: never judged,
never scored. A model loses on its words, never on its network.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

from evaluatorq import llm_jury_pairwise

from ..config import ArenaConfig
from ..data.prompts import PromptItem
from ..data.schemas import BattleRecord
from ..events import (
    ArenaEvent,
    JudgeVerdictEvent,
    MatchResolved,
    MatchStarted,
    ResponseChunk,
    ResponseComplete,
    RoundVoided,
    ThinkingChunk,
    TurnPrompt,
    TurnResolved,
)
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


@dataclass
class SideResult:
    text: str
    error: str | None
    usage: dict[str, Any]
    ttft_ms: int


def _prompt_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


async def _generate_side(
    *,
    gateway: OrqGateway,
    warrior: WarriorSpec,
    prompt: str,
    default_max_tokens: int,
    events: asyncio.Queue[ArenaEvent],
    match_id: str,
    side: str,  # 'a' | 'b'
) -> SideResult:
    """Stream one warrior's response; one silent-ish retry, then error out."""
    last_error = ""
    for attempt in (1, 2):
        chunks: list[str] = []
        usage: dict[str, Any] = {}
        t0 = time.monotonic()
        ttft_ms = 0
        try:
            async for kind, piece in gateway.stream_completion(
                model=warrior.model_id,
                prompt=prompt,
                max_tokens=warrior.max_tokens or default_max_tokens,
                extra_body=warrior.reasoning,
                usage_out=usage,
            ):
                if kind == "think":
                    await events.put(
                        ThinkingChunk(match_id=match_id, side=side, text=piece)  # type: ignore[arg-type]
                    )
                    continue
                if not chunks:
                    ttft_ms = int((time.monotonic() - t0) * 1000)
                chunks.append(piece)
                await events.put(
                    ResponseChunk(match_id=match_id, side=side, text=piece)  # type: ignore[arg-type]
                )
        except Exception as exc:
            last_error = str(exc)
            if attempt == 1:
                await events.put(
                    ResponseChunk(  # type: ignore[arg-type]
                        match_id=match_id, side=side, text="\n⟲ stream failed — retrying…\n"
                    )
                )
                continue
            await events.put(
                ResponseComplete(  # type: ignore[arg-type]
                    match_id=match_id, side=side, full_text="".join(chunks), error=last_error
                )
            )
            return SideResult(text="", error=last_error, usage=usage, ttft_ms=0)

        full = "".join(chunks)
        await events.put(
            ResponseComplete(  # type: ignore[arg-type]
                match_id=match_id,
                side=side,
                full_text=full,
                tokens_in=usage.get("input_tokens", 0),
                tokens_out=usage.get("output_tokens", 0),
                reasoning_tokens=usage.get("reasoning_tokens", 0),
                finish_reason=usage.get("finish_reason", ""),
                error=None,
            )
        )
        return SideResult(text=full, error=None, usage=usage, ttft_ms=ttft_ms)
    raise AssertionError("unreachable")


class Battle:
    """Drives a single match until KO or round cap."""

    def __init__(
        self,
        *,
        cfg: ArenaConfig,
        gateway: OrqGateway,
        warrior_a: WarriorSpec,
        warrior_b: WarriorSpec,
        prompts: Iterable[PromptItem],
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

        contestants = {warrior_a.model_id, warrior_b.model_id}
        panel = [m for m in cfg.judges if m not in contestants]
        if not panel:
            raise ValueError(
                f"Every judge is a contestant in {warrior_a.orc_name} vs "
                f"{warrior_b.orc_name} — add a neutral judge to the config."
            )
        replacements = [m for m in cfg.replacement_judges if m not in contestants]
        self._jury = llm_jury_pairwise(
            judges=panel,
            criteria=cfg.criteria,
            replacement_judges=replacements or None,
            min_successful_judges=cfg.min_successful_judges,
            max_tokens=cfg.gateway.judge_max_tokens,
            timeout_ms=cfg.gateway.judge_timeout_ms,
            client=gateway.client,
        )

    async def _void_round(
        self, *, round_number: int, item: PromptItem, reason: str,
        res_a: SideResult, res_b: SideResult, hp_a: int, hp_b: int,
    ) -> BattleRecord:
        await self.events.put(
            RoundVoided(match_id=self.match_id, round_number=round_number, reason=reason)
        )
        return BattleRecord(
            prompt_hash=_prompt_hash(item.text),
            prompt_text=item.text,
            prompt_category=item.category,
            model_a=self.a.short_model,
            model_b=self.b.short_model,
            response_a=res_a.text,
            response_b=res_b.text,
            majority_verdict="inconclusive",
            winner="void",
            error=reason,
            tournament_id=self.tournament_id,
            match_id=self.match_id,
            round_number=round_number,
            hp_a_before=hp_a, hp_b_before=hp_b, hp_a_after=hp_a, hp_b_after=hp_b,
        )

    async def run(self) -> MatchResult:
        rules = self.cfg.match
        hp_a = hp_b = rules.starting_hp
        battles: list[BattleRecord] = []
        rounds_counted = 0

        await self.events.put(
            MatchStarted(
                match_id=self.match_id,
                round_name=self.round_name,
                warrior_a=self.a.orc_name,
                warrior_b=self.b.orc_name,
            )
        )

        # KO is presentation, not termination: every prompt is judged so the
        # rating never depends on when the HP bar happened to empty.
        prompt_iter = iter(self.prompts)
        while rounds_counted < rules.max_rounds:
            try:
                item = next(prompt_iter)
            except StopIteration:
                break
            prompt = item.text

            round_number = rounds_counted + 1
            await self.events.put(
                TurnPrompt(match_id=self.match_id, round_number=round_number, prompt=prompt)
            )

            res_a, res_b = await asyncio.gather(
                _generate_side(
                    gateway=self.gateway, warrior=self.a, prompt=prompt,
                    default_max_tokens=self.cfg.gateway.warrior_max_tokens,
                    events=self.events, match_id=self.match_id, side="a",
                ),
                _generate_side(
                    gateway=self.gateway, warrior=self.b, prompt=prompt,
                    default_max_tokens=self.cfg.gateway.warrior_max_tokens,
                    events=self.events, match_id=self.match_id, side="b",
                ),
            )

            if res_a.error or res_b.error:
                failed = self.a.orc_name if res_a.error else self.b.orc_name
                reason = f"{failed}: stream failed after retry — {res_a.error or res_b.error}"
                battles.append(await self._void_round(
                    round_number=round_number, item=item, reason=reason,
                    res_a=res_a, res_b=res_b, hp_a=hp_a, hp_b=hp_b,
                ))
                continue

            try:
                comparison = await self._jury.compare(
                    question=prompt, response_a=res_a.text, response_b=res_b.text
                )
            except Exception as exc:
                battles.append(await self._void_round(
                    round_number=round_number, item=item,
                    reason=f"jury failed: {exc}",
                    res_a=res_a, res_b=res_b, hp_a=hp_a, hp_b=hp_b,
                ))
                continue

            for vote in comparison.votes:
                await self.events.put(
                    JudgeVerdictEvent(
                        match_id=self.match_id,
                        judge_name=vote.model.split("/")[-1],
                        verdict=vote.vote or "abstain",
                        reasoning=vote.explanation,
                        flipped=vote.flipped,
                        replacement=vote.replacement,
                    )
                )

            damage = compute_damage(comparison=comparison, rules=rules)
            hp_a_before, hp_b_before = hp_a, hp_b
            if damage.loser_side == "a":
                hp_a = max(0, hp_a - damage.damage)
            elif damage.loser_side == "b":
                hp_b = max(0, hp_b - damage.damage)

            if damage.counts_toward_cap:
                rounds_counted += 1

            judge_usage = comparison.token_usage
            battles.append(
                BattleRecord(
                    prompt_hash=_prompt_hash(prompt),
                    prompt_text=prompt,
                    prompt_category=item.category,
                    model_a=self.a.short_model,
                    model_b=self.b.short_model,
                    response_a=res_a.text,
                    response_b=res_b.text,
                    judge_votes=[v.model_dump() for v in comparison.votes],
                    majority_verdict=comparison.winner,
                    winner=(
                        self.a.short_model if comparison.winner == "A"
                        else self.b.short_model if comparison.winner == "B"
                        else comparison.winner  # 'tie' | 'inconclusive'
                    ),
                    tokens_a_in=res_a.usage.get("input_tokens", 0),
                    tokens_a_out=res_a.usage.get("output_tokens", 0),
                    tokens_a_reasoning=res_a.usage.get("reasoning_tokens", 0),
                    tokens_b_in=res_b.usage.get("input_tokens", 0),
                    tokens_b_out=res_b.usage.get("output_tokens", 0),
                    tokens_b_reasoning=res_b.usage.get("reasoning_tokens", 0),
                    finish_reason_a=res_a.usage.get("finish_reason", ""),
                    finish_reason_b=res_b.usage.get("finish_reason", ""),
                    ttft_a_ms=res_a.ttft_ms,
                    ttft_b_ms=res_b.ttft_ms,
                    judge_tokens_in=judge_usage.input_tokens if judge_usage else 0,
                    judge_tokens_out=judge_usage.output_tokens if judge_usage else 0,
                    tournament_id=self.tournament_id,
                    match_id=self.match_id,
                    round_number=round_number,
                    damage_dealt=damage.damage,
                    hp_a_before=hp_a_before,
                    hp_b_before=hp_b_before,
                    hp_a_after=hp_a,
                    hp_b_after=hp_b,
                )
            )

            await self.events.put(
                TurnResolved(
                    match_id=self.match_id,
                    round_number=round_number,
                    majority=comparison.winner,
                    damage_dealt=damage.damage,
                    loser_side=damage.loser_side,
                    hp_a=hp_a,
                    hp_b=hp_b,
                )
            )
            # Let the verdict land on screen before the next round starts.
            if rules.verdict_hold_s > 0:
                await asyncio.sleep(rules.verdict_hold_s)

        # Resolve the match for the show. The rating ignores this entirely —
        # ELO is fed per-round verdicts — so an HP tie is simply a draw.
        if hp_a == hp_b:
            winner, loser, by = self.a, self.b, "draw"
        elif hp_a > hp_b:
            winner, loser, by = self.a, self.b, "ko" if hp_b <= 0 else "round_cap"
        else:
            winner, loser, by = self.b, self.a, "ko" if hp_a <= 0 else "round_cap"

        await self.events.put(
            MatchResolved(
                match_id=self.match_id,
                winner="" if by == "draw" else winner.orc_name,
                loser="" if by == "draw" else loser.orc_name,
                by=by,
                final_hp_a=hp_a,
                final_hp_b=hp_b,
            )
        )

        return MatchResult(
            winner=winner, loser=loser, by=by,
            final_hp_a=hp_a, final_hp_b=hp_b, battles=battles,
        )
