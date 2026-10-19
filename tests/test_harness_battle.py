"""Harness rounds in Battle: the verifier gate, the jury on ties, voided trials."""

from __future__ import annotations

import asyncio

import pytest
from evaluatorq import PairwiseComparison
from evaluatorq.pairwise import PairwiseVote

import orq_arena.judging as judging_mod
from orq_arena.arena.battle import Battle
from orq_arena.config import ArenaConfig
from orq_arena.data.prompts import PromptItem
from orq_arena.events import JudgeVerdictEvent, SolutionReady
from orq_arena.harness.parsers import Step
from orq_arena.harness.trial import Trial


def _cfg(**extra) -> ArenaConfig:
    h = {"kind": "harness", "model_id": "x/m"}
    return ArenaConfig.model_validate(
        {
            "candidates": [
                {**h, "agent": "pi", "name": "pi"},
                {**h, "agent": "codex", "name": "codex", "model_id": "openai/m"},
            ],
            "judges": ["x/j1", "x/j2"],
            **extra,
        }
    )


class FakeJury:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    async def compare(self, *, question, response_a, response_b):
        self.calls.append((response_a, response_b))
        return PairwiseComparison(
            winner="B",
            votes=[PairwiseVote(model="x/j1", vote="B"), PairwiseVote(model="x/j2", vote="B")],
        )


class FakeRunner:
    def __init__(self, trials: dict[str, Trial]):
        self.trials = trials

    async def run_side(self, *, item, candidate, events, match_id, side):
        trial = self.trials[candidate.name]
        await events.put(
            SolutionReady(match_id=match_id, side=side, passed=trial.passed, error=trial.error)
        )
        return trial


def _trial(passed, **kw) -> Trial:
    return Trial(
        agent="pi", passed=passed, reward=None if passed is None else float(passed),
        steps=[Step("command", "$ ls")], duration_ms=1000, cost_usd=0.1, **kw,
    )  # fmt: skip


async def _run(monkeypatch, trials, **cfg_extra):
    jury = FakeJury()
    monkeypatch.setattr(judging_mod, "llm_jury_pairwise", lambda **kw: jury)
    cfg = _cfg(**cfg_extra)
    events: asyncio.Queue = asyncio.Queue()
    b = Battle(
        cfg=cfg, gateway=type("G", (), {"client": object()})(),
        candidate_a=cfg.candidates[0], candidate_b=cfg.candidates[1],
        prompts=[PromptItem("fix it", metadata={"harbor_task_path": "/t"})],
        match_id="M1", round_name="r", tournament_id="t", events=events,
        runner=FakeRunner(trials),
    )  # fmt: skip
    result = await b.run()
    out = []
    while not events.empty():
        out.append(events.get_nowait())
    return result, jury, out


async def test_one_side_passing_decides_without_a_jury_call(monkeypatch):
    result, jury, events = await _run(monkeypatch, {"pi": _trial(False), "codex": _trial(True)})
    rec = result.battles[0]
    assert jury.calls == []
    assert rec.majority_verdict == "B" and rec.winner == "codex"
    assert rec.decided_by_gate and rec.judge_votes[0]["model"] == "verifier"
    assert rec.solution_a["passed"] is False and rec.solution_b["passed"] is True
    assert rec.model_a_id == "pi:x/m"
    verdicts = [e for e in events if isinstance(e, JudgeVerdictEvent)]
    assert [v.judge_name for v in verdicts] == ["verifier"]


@pytest.mark.parametrize("passed", [True, False])
async def test_equal_verdicts_go_to_the_jury_with_dossiers(monkeypatch, passed):
    result, jury, _ = await _run(monkeypatch, {"pi": _trial(passed), "codex": _trial(passed)})
    assert len(jury.calls) == 1
    assert "## Hidden tests:" in jury.calls[0][0]
    assert not result.battles[0].decided_by_gate


async def test_gate_off_always_calls_the_jury(monkeypatch):
    _, jury, _ = await _run(
        monkeypatch, {"pi": _trial(False), "codex": _trial(True)}, verifier_gate=False
    )
    assert len(jury.calls) == 1


async def test_unrun_verifier_falls_through_to_the_jury(monkeypatch):
    _, jury, _ = await _run(monkeypatch, {"pi": _trial(None), "codex": _trial(True)})
    assert len(jury.calls) == 1


async def test_errored_trial_voids_the_round(monkeypatch):
    bad = Trial(agent="pi", error="router refused it")
    result, jury, _ = await _run(monkeypatch, {"pi": bad, "codex": _trial(True)})
    rec = result.battles[0]
    assert jury.calls == [] and rec.winner == "void" and "trial failed" in (rec.error or "")
