"""A rejudge leaves verifier-decided rounds alone and judges the rest from the dossiers."""

from __future__ import annotations

from types import SimpleNamespace

import orq_arena.judging as judging_mod
import orq_arena.rejudge as rejudge_mod
from orq_arena.config import ArenaConfig
from orq_arena.data.schemas import BattleRecord

CFG = ArenaConfig.model_validate(
    {
        "candidates": [
            {"kind": "harness", "agent": "pi", "model_id": "x/m", "name": "pi"},
            {"kind": "harness", "agent": "codex", "model_id": "openai/m", "name": "codex"},
        ],
        "judges": ["prov/j1"],
    }
)
GATE_VOTE = {"model": "verifier", "vote": "B", "completed": True, "explanation": "hidden tests"}


def _rec(i: int, gate: bool) -> BattleRecord:
    return BattleRecord(
        prompt_hash=f"h{i}",
        prompt_text="fix it",
        model_a="pi",
        model_b="codex",
        model_a_id="pi:x/m",
        model_b_id="codex:x/m",
        response_a="## Hidden tests: FAILED",
        response_b="## Hidden tests: PASSED",
        judge_votes=[GATE_VOTE] if gate else [],
        majority_verdict="B" if gate else "tie",
    )


class _AlwaysA:
    calls = 0

    async def compare(self, **_kw):
        from evaluatorq import PairwiseComparison

        type(self).calls += 1
        return PairwiseComparison.model_validate({"winner": "A", "votes": []})


async def test_gate_rounds_are_not_rejudged(monkeypatch):
    monkeypatch.setattr(rejudge_mod, "OrqGateway", lambda cfg: SimpleNamespace(client=object()))
    monkeypatch.setattr(judging_mod, "llm_jury_pairwise", lambda **_kw: _AlwaysA())
    result = await rejudge_mod.rejudge_run(
        cfg=CFG, records=[_rec(0, gate=True), _rec(1, gate=False)], judges=["prov/j1"]
    )
    winners = [c.winner for c in result["comparisons"]]
    assert winners == ["B", "A"]  # the gate keeps B; the jury round moved to A
    assert _AlwaysA.calls == 1
    assert result["changed_verdicts"] == 1
