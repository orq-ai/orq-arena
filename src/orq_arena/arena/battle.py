"""Per-match battle engine.

One ``Battle`` owns a single fight: it drives the turn loop, invokes the
evaluatorq pairwise jury, and pushes typed events onto an ``asyncio.Queue``
that the TUI subscribes to. The match winner is whoever won more judged
rounds; HP/damage is a TUI-only show derived from those same verdicts.

Judging: each round's A/B pair goes through ``llm_jury_pairwise``, every
judge sees both orderings, a judge that flips abstains (and is recorded), and
fewer than ``min_successful_judges`` decisive votes yields ``inconclusive``.
A round whose generation fails after one retry is **voided**: never judged,
never scored. A model loses on its words, never on its network.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Literal

from ..candidates import AnyCandidate, CandidateSpec, HarnessCandidate
from ..config import ArenaConfig
from ..data.prompts import PromptItem, item_key, prompt_hash
from ..data.schemas import GATE_JUDGE, BattleRecord
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
from ..harness.dossier import render as render_dossier
from ..harness.runner import HarborRunner
from ..judging import judged_cost_usd, make_jury, vote_probabilities
from ..providers.orq_gateway import OrqGateway


@dataclass
class MatchResult:
    winner: AnyCandidate
    loser: AnyCandidate
    draw: bool
    battles: list[BattleRecord] = field(default_factory=list)


@dataclass
class SideResult:
    text: str
    error: str | None
    usage: dict[str, Any]
    ttft_ms: int
    duration_ms: int = 0
    # Harness sides only: the trial's verdict, diff and counts (Trial.solution_dict).
    solution: dict[str, Any] | None = None


def _label(candidate: AnyCandidate) -> str:
    """The name a record stores in ``model_*`` and ``winner``.

    A model's short name, as ever. A harness has no unique short name (two pi
    setups on one model share it), so its display name stands in.
    """
    return candidate.name if isinstance(candidate, HarnessCandidate) else candidate.short_model


_prompt_hash = prompt_hash


async def _generate_side(
    *,
    gateway: OrqGateway,
    candidate: CandidateSpec,
    prompt: str,
    default_max_tokens: int,
    events: asyncio.Queue[ArenaEvent],
    match_id: str,
    side: Literal["a", "b"],
) -> SideResult:
    """Stream one model's response; one silent-ish retry, then error out."""
    last_error = ""
    for attempt in (1, 2):
        chunks: list[str] = []
        usage: dict[str, Any] = {}
        t0 = time.monotonic()
        ttft_ms = 0
        try:
            async for kind, piece in gateway.stream_completion(
                model=candidate.model_id,
                prompt=prompt,
                max_tokens=candidate.max_tokens or default_max_tokens,
                extra_body=candidate.reasoning,
                usage_out=usage,
            ):
                if kind == "think":
                    await events.put(ThinkingChunk(match_id=match_id, side=side, text=piece))
                    continue
                if not chunks:
                    ttft_ms = int((time.monotonic() - t0) * 1000)
                chunks.append(piece)
                await events.put(ResponseChunk(match_id=match_id, side=side, text=piece))
        except Exception as exc:
            last_error = str(exc)
            if attempt == 1:
                await events.put(
                    ResponseChunk(
                        match_id=match_id, side=side, text="\n⟲ stream failed, retrying…\n"
                    )
                )
                continue
            await events.put(
                ResponseComplete(
                    match_id=match_id, side=side, full_text="".join(chunks), error=last_error
                )
            )
            # Keep what arrived. The round is voided either way, but a
            # half-written answer is the evidence for why it died.
            return SideResult(
                text="".join(chunks), error=last_error, usage=usage, ttft_ms=0, duration_ms=0
            )

        full = "".join(chunks)
        await events.put(
            ResponseComplete(
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
        return SideResult(
            text=full,
            error=None,
            usage=usage,
            ttft_ms=ttft_ms,
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
    raise AssertionError("unreachable")


async def _generate_harness_side(
    *,
    runner: HarborRunner,
    candidate: HarnessCandidate,
    item: PromptItem,
    events: asyncio.Queue[ArenaEvent],
    match_id: str,
    side: Literal["a", "b"],
) -> SideResult:
    """Run (or replay) one harness trial; the dossier is what the judges read.

    No retry loop: a retry is another trial, minutes and dollars, and a harness
    that failed to produce a result voids the round like a dead stream does.
    """
    trial = await runner.run_side(
        item=item, candidate=candidate, events=events, match_id=match_id, side=side
    )
    if trial.error:
        await events.put(
            ResponseComplete(match_id=match_id, side=side, full_text="", error=trial.error)
        )
        return SideResult(text="", error=trial.error, usage={}, ttft_ms=0)
    dossier = render_dossier(trial)
    await events.put(
        ResponseComplete(
            match_id=match_id,
            side=side,
            full_text=dossier,
            tokens_in=trial.tokens_in,
            tokens_out=trial.tokens_out,
            finish_reason=trial.exit_reason,
        )
    )
    return SideResult(
        text=dossier,
        error=None,
        usage={
            "input_tokens": trial.tokens_in,
            "output_tokens": trial.tokens_out,
            "finish_reason": trial.exit_reason,
        },
        ttft_ms=0,
        duration_ms=trial.duration_ms,
        solution=trial.solution_dict(),
    )


class Battle:
    """Drives a single match until KO or round cap."""

    def __init__(
        self,
        *,
        cfg: ArenaConfig,
        gateway: OrqGateway,
        candidate_a: AnyCandidate,
        candidate_b: AnyCandidate,
        prompts: Iterable[PromptItem],
        match_id: str,
        round_name: str,
        tournament_id: str,
        events: asyncio.Queue[ArenaEvent],
        on_record: Callable[[BattleRecord], None] | None = None,
        runner: HarborRunner | None = None,
    ) -> None:
        self.cfg = cfg
        self.gateway = gateway
        self.a = candidate_a
        self.b = candidate_b
        self.prompts = list(prompts)
        self.match_id = match_id
        self.round_name = round_name
        self.tournament_id = tournament_id
        self.events = events
        # Called the moment a round resolves, so a run killed mid-match keeps
        # every round it already paid for. Batching to the end of the match
        # lost up to `headless_concurrency` matches of work on a Ctrl-C.
        self._on_record = on_record
        self.runner = runner
        if runner is None and any(
            isinstance(c, HarnessCandidate) for c in (candidate_a, candidate_b)
        ):
            raise ValueError("a harness candidate needs a HarborRunner")

        contestants = {candidate_a.model_id, candidate_b.model_id}
        panel = [m for m in cfg.judges if m not in contestants]
        if not panel:
            raise ValueError(
                f"Every judge is a contestant in {candidate_a.name} vs "
                f"{candidate_b.name}, add a neutral judge to the config."
            )
        replacements = [m for m in cfg.replacement_judges if m not in contestants]
        self._jury = make_jury(cfg, panel=panel, replacements=replacements, client=gateway.client)

    async def _void_round(
        self,
        *,
        round_number: int,
        item: PromptItem,
        reason: str,
        res_a: SideResult,
        res_b: SideResult,
    ) -> BattleRecord:
        await self.events.put(
            RoundVoided(match_id=self.match_id, round_number=round_number, reason=reason)
        )
        return BattleRecord(
            prompt_hash=_prompt_hash(item_key(item)),
            prompt_text=item.text,
            prompt_category=item.category,
            prompt_metadata=item.metadata,
            model_a=_label(self.a),
            model_b=_label(self.b),
            model_a_id=self.a.candidate_id,
            model_b_id=self.b.candidate_id,
            response_a=res_a.text,
            response_b=res_b.text,
            solution_a=res_a.solution,
            solution_b=res_b.solution,
            majority_verdict="inconclusive",
            winner="void",
            error=reason,
            tournament_id=self.tournament_id,
            match_id=self.match_id,
            round_number=round_number,
        )

    async def _generate(
        self, candidate: AnyCandidate, item: PromptItem, side: Literal["a", "b"]
    ) -> SideResult:
        if isinstance(candidate, HarnessCandidate):
            assert self.runner is not None  # checked in __init__
            return await _generate_harness_side(
                runner=self.runner,
                candidate=candidate,
                item=item,
                events=self.events,
                match_id=self.match_id,
                side=side,
            )
        return await _generate_side(
            gateway=self.gateway,
            candidate=candidate,
            prompt=item.text,
            default_max_tokens=self.cfg.gateway.candidate_max_tokens,
            events=self.events,
            match_id=self.match_id,
            side=side,
        )

    def _gate(self, res_a: SideResult, res_b: SideResult) -> Literal["A", "B"] | None:
        """The verifier's verdict when exactly one side passed the hidden tests."""
        if not self.cfg.verifier_gate or res_a.solution is None or res_b.solution is None:
            return None
        pa, pb = res_a.solution.get("passed"), res_b.solution.get("passed")
        if pa is None or pb is None or pa == pb:
            return None
        return "A" if pa else "B"

    def _record(self, battles: list[BattleRecord], rec: BattleRecord) -> None:
        """Keep the in-memory list and the on-disk log in step, per round."""
        battles.append(rec)
        if self._on_record is not None:
            self._on_record(rec)

    async def run(self) -> MatchResult:
        rules = self.cfg.match
        battles: list[BattleRecord] = []
        rounds_counted = 0
        wins_a = wins_b = 0

        await self.events.put(
            MatchStarted(
                match_id=self.match_id,
                round_name=self.round_name,
                model_a=self.a.name,
                model_b=self.b.name,
            )
        )

        # The round cap counts decisive rounds; ties/inconclusive keep drawing
        # more prompts so the rating gets ``max_rounds`` real comparisons.
        prompt_iter = iter(self.prompts)
        while rounds_counted < rules.max_rounds:
            try:
                item = next(prompt_iter)
            except StopIteration:
                break
            prompt = item.text

            round_number = rounds_counted + 1
            await self.events.put(
                TurnPrompt(
                    match_id=self.match_id,
                    round_number=round_number,
                    prompt=prompt,
                    replicate=int(item.metadata.get("replicate") or 0),
                )
            )

            res_a, res_b = await asyncio.gather(
                self._generate(self.a, item, "a"), self._generate(self.b, item, "b")
            )

            if res_a.error or res_b.error:
                failed_cand = self.a if res_a.error else self.b
                what = "trial" if isinstance(failed_cand, HarnessCandidate) else "stream"
                reason = f"{failed_cand.name}: {what} failed, {res_a.error or res_b.error}"
                if what == "stream":
                    reason = reason.replace("failed,", "failed after retry,", 1)
                self._record(
                    battles,
                    await self._void_round(
                        round_number=round_number,
                        item=item,
                        reason=reason,
                        res_a=res_a,
                        res_b=res_b,
                    ),
                )
                continue

            verdict: Literal["A", "B"] | None = self._gate(res_a, res_b)
            judge_usage = None
            judge_cost: float | None = None
            judge_ms = 0
            if verdict is not None:
                # The hidden tests decided: no jury call, a synthetic vote keeps the
                # record shaped like every other round.
                passed_a = (res_a.solution or {}).get("passed")
                why = f"hidden tests: A {'passed' if passed_a else 'failed'}, B {'failed' if passed_a else 'passed'}"
                votes: list[dict[str, Any]] = [
                    {
                        "model": GATE_JUDGE,
                        "vote": verdict,
                        "completed": True,
                        "flipped": False,
                        "replacement": False,
                        "explanation": why,
                        "observations": [],
                    }
                ]
                winner_code: str = verdict
                await self.events.put(
                    JudgeVerdictEvent(
                        match_id=self.match_id,
                        judge_name=GATE_JUDGE,
                        verdict=verdict,
                        reasoning=why,
                    )
                )
            else:
                t0 = time.monotonic()
                try:
                    comparison = await self._jury.compare(
                        question=prompt, response_a=res_a.text, response_b=res_b.text
                    )
                except Exception as exc:
                    self._record(
                        battles,
                        await self._void_round(
                            round_number=round_number,
                            item=item,
                            reason=f"jury failed: {exc}",
                            res_a=res_a,
                            res_b=res_b,
                        ),
                    )
                    continue
                judge_ms = int((time.monotonic() - t0) * 1000)

                for vote in comparison.votes:
                    probabilities = vote_probabilities(vote)
                    await self.events.put(
                        JudgeVerdictEvent(
                            match_id=self.match_id,
                            judge_name=vote.model,
                            verdict=vote.vote or "abstain",
                            # A decision judge's explanation only restates its numbers.
                            reasoning="" if probabilities else vote.explanation,
                            probabilities=probabilities,
                            flipped=vote.flipped,
                            replacement=vote.replacement,
                        )
                    )
                votes = [v.model_dump() for v in comparison.votes]
                winner_code = comparison.winner
                judge_usage = comparison.token_usage
                judge_cost = judged_cost_usd(comparison)

            if winner_code == "A":
                wins_a += 1
                rounds_counted += 1
            elif winner_code == "B":
                wins_b += 1
                rounds_counted += 1
            # tie/inconclusive: judged and recorded, but no round-cap credit.

            self._record(
                battles,
                BattleRecord(
                    prompt_hash=_prompt_hash(prompt),
                    prompt_text=prompt,
                    prompt_category=item.category,
                    prompt_metadata=item.metadata,
                    model_a=_label(self.a),
                    model_b=_label(self.b),
                    model_a_id=self.a.candidate_id,
                    model_b_id=self.b.candidate_id,
                    response_a=res_a.text,
                    response_b=res_b.text,
                    solution_a=res_a.solution,
                    solution_b=res_b.solution,
                    judge_votes=votes,
                    majority_verdict=winner_code,
                    winner=(
                        _label(self.a)
                        if winner_code == "A"
                        else _label(self.b)
                        if winner_code == "B"
                        else winner_code  # 'tie' | 'inconclusive'
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
                    duration_a_ms=res_a.duration_ms,
                    duration_b_ms=res_b.duration_ms,
                    judge_tokens_in=judge_usage.input_tokens if judge_usage else 0,
                    judge_tokens_out=judge_usage.output_tokens if judge_usage else 0,
                    judge_cost_usd=judge_cost if verdict is None else 0.0,
                    judge_ms=judge_ms,
                    tournament_id=self.tournament_id,
                    match_id=self.match_id,
                    round_number=round_number,
                ),
            )

            await self.events.put(
                TurnResolved(
                    match_id=self.match_id,
                    round_number=round_number,
                    majority=winner_code,
                )
            )

        # Match winner = more judged round wins; equal is a draw. The rating
        # ignores this entirely (it's fed per-round verdicts).
        draw = wins_a == wins_b
        if wins_a >= wins_b:
            winner, loser = self.a, self.b
        else:
            winner, loser = self.b, self.a

        await self.events.put(
            MatchResolved(
                match_id=self.match_id,
                winner="" if draw else winner.name,
                loser="" if draw else loser.name,
            )
        )

        return MatchResult(winner=winner, loser=loser, draw=draw, battles=battles)
