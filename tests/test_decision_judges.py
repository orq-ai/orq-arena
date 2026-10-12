"""Decision-model judges: seating, probabilities, the abstain floor, labels, preflight."""

from __future__ import annotations

import asyncio

import pytest
from evaluatorq import PairwiseComparison, PairwiseVote
from evaluatorq.common import model_catalogue
from evaluatorq.common.model_catalogue import ModelInfo
from pydantic import ValidationError

from orq_arena import judging
from orq_arena.config import ArenaConfig
from orq_arena.data.prompts import PromptItem
from orq_arena.judging import (
    apply_abstain_floor,
    floor_abstained,
    judge_labels,
    pin_judge_endpoints,
    vote_probabilities,
)
from orq_arena.preflight import (
    _JUDGE_WRAPPER_TOKENS,
    call_counts,
    cost_projection,
    judge_api_errors,
)
from orq_arena.providers.models_list import ModelEntry


def _cfg(**over) -> ArenaConfig:
    base = {
        "candidates": [{"model_id": "a/one"}, {"model_id": "b/two"}],
        "judges": ["typesafe/jev-latest"],
        "preflight": {"thinking_probe": False},
    }
    return ArenaConfig.model_validate({**base, **over})


def _obs(ordering: str, probs: dict[str, float]) -> dict:
    return {"ordering": ordering, "repetition": 0, "raw_output": {"probabilities": probs}}


def _vote(model: str, vote: str | None, ab: dict, ba: dict) -> PairwiseVote:
    return PairwiseVote(model=model, vote=vote, observations=[_obs("ab", ab), _obs("ba", ba)])


def test_the_swapped_seat_order_is_read_back_in_the_original_seats():
    # In the swapped order response B sat in seat A, so its "A" is the original B.
    v = _vote("j", "A", {"A": 0.8, "B": 0.1, "tie": 0.1}, {"A": 0.2, "B": 0.6, "tie": 0.2})
    p = vote_probabilities(v)
    assert p == pytest.approx({"A": 0.7, "B": 0.15, "tie": 0.15})
    # A stored dict reads the same as the live vote.
    assert vote_probabilities(v.model_dump()) == pytest.approx(p)


def test_a_prompted_judge_has_no_probabilities():
    assert vote_probabilities({"model": "j", "vote": "A", "observations": []}) is None
    assert vote_probabilities({"model": "j", "vote": "A"}) is None


def test_the_floor_turns_an_unsure_vote_into_an_abstention_and_recounts():
    sure = _vote("j1", "A", {"A": 0.9, "B": 0.05, "tie": 0.05}, {"A": 0.05, "B": 0.9, "tie": 0.05})
    unsure = _vote(
        "j2", "B", {"A": 0.4, "B": 0.45, "tie": 0.15}, {"A": 0.45, "B": 0.4, "tie": 0.15}
    )
    other = _vote("j3", "B", {"A": 0.1, "B": 0.8, "tie": 0.1}, {"A": 0.8, "B": 0.1, "tie": 0.1})
    c = PairwiseComparison(winner="B", votes=[sure, unsure, other])

    floored = apply_abstain_floor(c, 0.5, quorum=2)
    assert [v.vote for v in floored.votes] == ["A", None, "B"]
    assert floored.winner == "inconclusive"  # A vs B split, no plurality
    assert floor_abstained(floored.votes[1].model_dump(), 0.5)
    assert not floor_abstained(floored.votes[0].model_dump(), 0.5)

    assert apply_abstain_floor(c, None, quorum=2) is c
    # Under quorum after the floor: inconclusive, never a verdict from one judge.
    assert apply_abstain_floor(c, 0.85, quorum=2).winner == "inconclusive"


def test_a_flip_is_not_counted_as_a_floor_abstention():
    flipped = {"model": "j", "vote": None, "flipped": True, "observations": [
        _obs("ab", {"A": 0.4, "B": 0.3, "tie": 0.3}),
        _obs("ba", {"A": 0.4, "B": 0.3, "tie": 0.3}),
    ]}  # fmt: skip
    assert not floor_abstained(flipped, 0.5)


def test_judge_labels_only_qualify_names_that_collide():
    labels = judge_labels(["openai/gpt-oss-120b", "groq/openai/gpt-oss-120b", "orq/decider-4b"])
    assert labels == {
        "openai/gpt-oss-120b": "openai/gpt-oss-120b",
        "groq/openai/gpt-oss-120b": "groq/gpt-oss-120b",
        "orq/decider-4b": "decider-4b",
    }


def test_the_config_mode_decides_the_endpoint_not_the_catalogue(monkeypatch):
    # The catalogue marks a chat model decision-capable; an llm panel keeps it on chat.
    haiku = ModelInfo(0.001, 0.005, "anthropic", True, supports_classify=True)
    jev = ModelInfo(0.00004, 0.0, "typesafe", False, supports_classify=True)
    known = {"anthropic/claude-haiku-4-5": haiku, "typesafe/jev-latest": jev}

    async def _info(model, _client=None):
        return known.get(model)

    monkeypatch.setattr(judging, "get_model_info", _info)

    llm = _cfg(judge_api="llm", judges=["anthropic/claude-haiku-4-5"])
    asyncio.run(pin_judge_endpoints(llm, None))
    assert model_catalogue.is_known_classify_model("anthropic/claude-haiku-4-5") is False

    unknown = _cfg(judge_api="decisions", judges=["typesafe/jev-latest", "acme/new-decider"])
    asyncio.run(pin_judge_endpoints(unknown, None))
    assert model_catalogue.is_known_classify_model("acme/new-decider") is True


def test_the_floor_needs_the_decisions_api():
    with pytest.raises(ValidationError, match="judge_api: decisions"):
        _cfg(judge_api="llm", judges=["a/judge"], judge_abstain_below=0.5)
    assert _cfg(judge_api="decisions", judge_abstain_below=0.5).judge_abstain_below == 0.5


def test_preflight_blocks_judges_that_cannot_answer_on_the_chosen_endpoint():
    catalog = {
        "typesafe/jev-latest": ModelEntry(
            "typesafe/jev-latest", "typesafe", endpoints=("classify",)
        ),
        "openai/gpt-6-luna": ModelEntry(
            "openai/gpt-6-luna", "openai", endpoints=("chat", "classify")
        ),
        "x/chat-only": ModelEntry("x/chat-only", "x", endpoints=("chat", "responses")),
    }
    assert (
        judge_api_errors(_cfg(judge_api="decisions", judges=["openai/gpt-6-luna"]), catalog) == []
    )
    assert (
        "x/chat-only"
        in judge_api_errors(_cfg(judge_api="decisions", judges=["x/chat-only"]), catalog)[0]
    )
    assert "typesafe/jev-latest" in judge_api_errors(_cfg(judge_api="llm"), catalog)[0]
    # A model that serves both answers on either.
    assert judge_api_errors(_cfg(judge_api="llm", judges=["openai/gpt-6-luna"]), catalog) == []
    # Unknown to the catalog: not blocked here, config_warnings reports it.
    assert judge_api_errors(_cfg(judge_api="decisions", judges=["acme/x"]), catalog) == []


def test_decision_judges_are_priced_on_input_and_swap_off_halves_the_calls():
    prompts = [PromptItem(text="x" * 400)]  # 100 tokens
    prices = {"typesafe/jev-latest": (0.042, 9.0)}  # an output rate the API never bills
    for swap, orders in ((True, 2), (False, 1)):
        cfg = _cfg(judge_api="decisions", judge_swap=swap)
        counts = call_counts(cfg, prompts)
        assert counts.judge_calls == orders  # 1 match x 1 round x 1 judge
        c = cost_projection(cfg, prompts, counts, prices)
        judge_in = 100 + 2 * cfg.gateway.candidate_max_tokens + _JUDGE_WRAPPER_TOKENS
        assert c.judges_usd == pytest.approx(orders * 0.042 * judge_in / 1e6)


def test_a_manifest_from_before_judge_api_rebuilds_as_an_llm_run():
    from orq_arena.tournament.driver import config_from_manifest

    local = _cfg(judge_api="decisions", judge_swap=False, judge_abstain_below=0.6)
    old = {
        "candidates": {"one": {"model": "a/one"}, "two": {"model": "b/two"}},
        "judges": ["c/judge"],
    }
    cfg, _ = config_from_manifest(old, local)
    assert (cfg.judge_api, cfg.judge_swap, cfg.judge_abstain_below) == ("llm", True, None)

    new = {**old, "judges": ["typesafe/jev-latest"], "judge_api": "decisions", "judge_swap": False}
    cfg, _ = config_from_manifest(new, _cfg())
    assert (cfg.judge_api, cfg.judge_swap) == ("decisions", False)


def test_new_judge_keys_leave_an_old_runs_config_hash_alone():
    """The quickstart manifest predates judge_api; its YAML must still hash to what it recorded."""
    import json
    from pathlib import Path

    from orq_arena.config import load_config
    from orq_arena.tournament.driver import config_sha256

    root = Path(__file__).resolve().parent.parent / "examples" / "quickstart"
    cfg = load_config(root / "config.yaml")
    recorded = json.loads((root / "battles.run.json").read_text())["config_sha256"]
    assert config_sha256(cfg) == recorded
    assert config_sha256(cfg.model_copy(update={"judge_swap": False})) != recorded
