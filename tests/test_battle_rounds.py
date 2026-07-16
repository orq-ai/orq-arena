"""Battle round semantics: void-on-failure and happy-path judging via fakes."""

from __future__ import annotations

import asyncio

import pytest
from evaluatorq import PairwiseComparison
from evaluatorq.pairwise import PairwiseVote

import orq_arena.arena.battle as battle_mod
from orq_arena.arena.battle import Battle
from orq_arena.config import ArenaConfig
from orq_arena.data.prompts import PromptItem
from orq_arena.events import JudgeVerdictEvent, RoundVoided, TurnResolved


def _cfg() -> ArenaConfig:
    return ArenaConfig.model_validate(
        {
            "candidates": [
                {"name": "Alpha", "model_id": "x/alpha"},
                {"name": "Beta", "model_id": "x/beta"},
            ],
            "judges": ["x/j1", "x/j2", "x/j3"],
        }
    )


class FakeGateway:
    """Streams canned text; models listed in `failing` raise every attempt."""

    def __init__(self, failing: set[str] | None = None) -> None:
        self.failing = failing or set()
        self.client = object()

    async def stream_completion(
        self, *, model, prompt, max_tokens=None, extra_body=None, usage_out=None
    ):
        if model in self.failing:
            raise RuntimeError("boom: connection died")
        if usage_out is not None:
            usage_out.update(
                {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "reasoning_tokens": 0,
                    "finish_reason": "stop",
                }
            )
        yield ("text", f"{model} says hi")


class FakeJury:
    def __init__(self, comparison: PairwiseComparison | None = None) -> None:
        self.comparison = comparison
        self.calls = 0

    async def compare(self, *, question, response_a, response_b):
        self.calls += 1
        if self.comparison is None:
            raise AssertionError("jury must not be called for a voided round")
        return self.comparison


def _build_battle(monkeypatch, gateway, jury) -> tuple[Battle, asyncio.Queue]:
    monkeypatch.setattr(battle_mod, "llm_jury_pairwise", lambda **kw: jury)
    cfg = _cfg()
    events: asyncio.Queue = asyncio.Queue()
    b = Battle(
        cfg=cfg,
        gateway=gateway,
        candidate_a=cfg.candidates[0],
        candidate_b=cfg.candidates[1],
        prompts=[PromptItem("What is 2+2?")],
        match_id="M1",
        round_name="round",
        tournament_id="t",
        events=events,
    )
    return b, events


def _drain(events: asyncio.Queue) -> list:
    out = []
    while not events.empty():
        out.append(events.get_nowait())
    return out


async def test_stream_failure_voids_round_without_judging(monkeypatch):
    jury = FakeJury(comparison=None)  # raises if called
    b, events = _build_battle(monkeypatch, FakeGateway(failing={"x/alpha"}), jury)
    result = await b.run()

    assert jury.calls == 0
    rec = result.battles[0]
    assert rec.winner == "void"
    assert rec.error and "stream failed after retry" in rec.error

    evs = _drain(events)
    assert any(isinstance(e, RoundVoided) for e in evs)
    assert not any(isinstance(e, JudgeVerdictEvent) for e in evs)
    assert not any(isinstance(e, TurnResolved) for e in evs)


async def test_happy_path_judges_and_records_winner(monkeypatch):
    comparison = PairwiseComparison(
        winner="A",
        votes=[
            PairwiseVote(model="x/j1", vote="A"),
            PairwiseVote(model="x/j2", vote="A", flipped=False),
            PairwiseVote(model="x/j3", vote=None, flipped=True),
        ],
    )
    jury = FakeJury(comparison)
    b, events = _build_battle(monkeypatch, FakeGateway(), jury)
    result = await b.run()

    rec = result.battles[0]
    assert rec.majority_verdict == "A"
    assert rec.winner == "alpha"
    assert result.winner is b.a and result.draw is False
    assert len(rec.judge_votes) == 3
    assert rec.tokens_a_out == 5 and rec.finish_reason_a == "stop"

    evs = _drain(events)
    verdicts = [e for e in evs if isinstance(e, JudgeVerdictEvent)]
    assert len(verdicts) == 3
    assert any(e.verdict == "abstain" and e.flipped for e in verdicts)


async def test_all_judges_contestants_raises(monkeypatch):
    cfg = ArenaConfig.model_validate(
        {
            "candidates": [
                {"name": "Alpha", "model_id": "x/j1"},
                {"name": "Beta", "model_id": "x/j2"},
            ],
            "judges": ["x/j1", "x/j2"],
        }
    )
    with pytest.raises(ValueError, match="neutral judge"):
        Battle(
            cfg=cfg,
            gateway=FakeGateway(),
            candidate_a=cfg.candidates[0],
            candidate_b=cfg.candidates[1],
            prompts=[PromptItem("p")],
            match_id="M1",
            round_name="round",
            tournament_id="t",
            events=asyncio.Queue(),
        )


async def test_every_prompt_is_judged(monkeypatch):
    # All three prompts are judged; the winner is whoever won more rounds.
    comparison = PairwiseComparison(
        winner="A",
        votes=[PairwiseVote(model="x/j1", vote="A"), PairwiseVote(model="x/j2", vote="A")],
    )
    jury = FakeJury(comparison)
    monkeypatch.setattr(battle_mod, "llm_jury_pairwise", lambda **kw: jury)
    cfg = _cfg()
    cfg.match.max_rounds = 3
    events: asyncio.Queue = asyncio.Queue()
    b = Battle(
        cfg=cfg,
        gateway=FakeGateway(),
        candidate_a=cfg.candidates[0],
        candidate_b=cfg.candidates[1],
        prompts=[PromptItem("p1"), PromptItem("p2"), PromptItem("p3")],
        match_id="M1",
        round_name="round",
        tournament_id="t",
        events=events,
    )
    result = await b.run()
    assert len(result.battles) == 3  # all prompts judged
    assert result.winner is b.a and result.draw is False
    assert jury.calls == 3


async def test_no_round_wins_is_a_draw(monkeypatch):
    comparison = PairwiseComparison(
        winner="tie",
        votes=[PairwiseVote(model="x/j1", vote="tie"), PairwiseVote(model="x/j2", vote="tie")],
    )
    jury = FakeJury(comparison)
    b, events = _build_battle(monkeypatch, FakeGateway(), jury)
    result = await b.run()
    assert result.draw is True
    evs = _drain(events)
    from orq_arena.events import MatchResolved

    resolved = [e for e in evs if isinstance(e, MatchResolved)]
    assert resolved and resolved[0].winner == ""
