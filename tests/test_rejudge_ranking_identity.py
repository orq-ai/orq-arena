"""A colliding pool stays two models in the rejudge ranking.

The last known instance of the fix-one-path-miss-the-sibling pattern
(RES-1152): RES-1149 fixed rejudge's comparator key (self-judge exclusion on
the full id) and missed its ranking, which still built pairs from short
names, so `openai/gpt-oss-120b` and `groq/gpt-oss-120b` merged into one entry
and the printed Spearman compared rankings over a field one model short.

No network: the judge comparator is stubbed the way the driver tests stub
`Battle`; the ranking math under test never needed a gateway.
"""

from __future__ import annotations

import pytest

from orq_arena import rejudge as rejudge_mod
from orq_arena.config import ArenaConfig
from orq_arena.data.schemas import BattleRecord

COLLIDING_CFG = ArenaConfig.model_validate(
    {
        "candidates": [{"model_id": "openai/gpt-oss-120b"}, {"model_id": "groq/gpt-oss-120b"}],
        "judges": ["prov/j1", "prov/j2"],
    }
)


def _rec(i: int, verdict: str, a_id: str = "", b_id: str = "") -> BattleRecord:
    return BattleRecord(
        prompt_hash=f"h{i}",
        prompt_text="p",
        model_a="gpt-oss-120b" if a_id else "model-a",
        model_b="gpt-oss-120b" if b_id else "model-b",
        model_a_id=a_id,
        model_b_id=b_id,
        response_a="ra",
        response_b="rb",
        majority_verdict=verdict,
        match_id="m1",
        round_number=i,
    )


class _FixedComparator:
    """Stands in for evaluatorq's jury: every round re-judged as A wins."""

    async def compare(self, **_kw):
        from evaluatorq import PairwiseComparison

        return PairwiseComparison.model_validate({"winner": "A", "votes": []})


@pytest.fixture
def stub_jury(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(rejudge_mod, "OrqGateway", lambda cfg: SimpleNamespace(client=object()))
    monkeypatch.setattr(rejudge_mod, "llm_jury_pairwise", lambda **_kw: _FixedComparator())


async def test_a_colliding_pool_stays_two_models_in_the_ranking(stub_jury):
    records = [_rec(i, "A", a_id="openai/gpt-oss-120b", b_id="groq/gpt-oss-120b") for i in range(4)]
    result = await rejudge_mod.rejudge_run(cfg=COLLIDING_CFG, records=records, judges=["prov/j1"])
    # The old code collapsed both to the short name: a one-entry ranking.
    assert len(result["old_ranking"]) == 2
    assert set(result["old_ranking"]) == {"openai/gpt-oss-120b", "groq/gpt-oss-120b"}
    assert set(result["new_ranking"]) == {"openai/gpt-oss-120b", "groq/gpt-oss-120b"}
    # And the winner of every round ranks first in both.
    assert result["old_ranking"][0] == "openai/gpt-oss-120b"
    assert result["new_ranking"][0] == "openai/gpt-oss-120b"


async def test_a_v3_log_without_ids_still_ranks_on_short_names(stub_jury):
    cfg = ArenaConfig.model_validate(
        {
            "candidates": [{"model_id": "prov/model-a"}, {"model_id": "prov/model-b"}],
            "judges": ["prov/j1", "prov/j2"],
        }
    )
    records = [_rec(i, "A") for i in range(3)]  # no id fields, pre-v4 shape
    result = await rejudge_mod.rejudge_run(cfg=cfg, records=records, judges=["prov/j1"])
    assert result["old_ranking"] == ["model-a", "model-b"]
    assert result["spearman"] == 1.0  # every verdict re-judged identically
