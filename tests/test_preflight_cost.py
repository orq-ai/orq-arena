"""Spend-ceiling math: exact counts x config caps x catalog prices."""

from orq_arena.config import ArenaConfig
from orq_arena.data.prompts import PromptItem
from orq_arena.preflight import (_JUDGE_WRAPPER_TOKENS, _PROBE_MAX_TOKENS,
                                 call_counts, cost_ceiling)

PROMPTS = [PromptItem(text="x" * 400), PromptItem(text="y" * 200)]  # max = 100 tok


def _cfg(**over) -> ArenaConfig:
    base = {
        "warriors": [
            {"model_id": "a/one"},
            {"model_id": "b/two", "max_tokens": 1000},
        ],
        "judges": ["c/judge"],
        "preflight": {"thinking_probe": False},
    }
    return ArenaConfig.model_validate({**base, **over})


def test_ceiling_is_exact_arithmetic():
    cfg = _cfg()
    counts = call_counts(cfg, PROMPTS)  # 1 match x 2 rounds
    prices = {"a/one": (1.0, 2.0), "b/two": (4.0, 8.0), "c/judge": (10.0, 20.0)}
    c = cost_ceiling(cfg, PROMPTS, counts, prices)

    cap_default = cfg.gateway.warrior_max_tokens  # 2048
    # a/one: 2 streams x (1*100 + 2*2048) / 1e6; b/two: 2 x (4*100 + 8*1000) / 1e6
    warriors = 2 * (100 + 2 * cap_default) / 1e6 + 2 * (400 + 8000) / 1e6
    judge_in = 100 + 2 * cap_default + _JUDGE_WRAPPER_TOKENS
    judges = 4 * (10 * judge_in + 20 * cfg.gateway.judge_max_tokens) / 1e6  # 1x2x1x2 calls
    assert abs(c.warriors_usd - warriors) < 1e-12
    assert abs(c.judges_usd - judges) < 1e-12
    assert c.probe_usd == 0
    assert abs(c.total_usd - (warriors + judges)) < 1e-12
    assert c.unpriced == []


def test_unpriced_models_are_excluded_and_reported():
    cfg = _cfg()
    counts = call_counts(cfg, PROMPTS)
    c = cost_ceiling(cfg, PROMPTS, counts, {"a/one": (1.0, 2.0)})
    assert c.unpriced == ["b/two", "c/judge"]
    assert c.judges_usd == 0
    assert c.warriors_usd > 0


def test_probe_priced_only_when_enabled():
    cfg = _cfg(preflight={"thinking_probe": True})
    counts = call_counts(cfg, PROMPTS)
    prices = {"a/one": (1.0, 2.0), "b/two": (4.0, 8.0), "c/judge": (10.0, 20.0)}
    c = cost_ceiling(cfg, PROMPTS, counts, prices)
    assert c.probe_usd > 0
    # dominated by the output cap: 2 warriors x cout x _PROBE_MAX_TOKENS
    assert c.probe_usd < (2 + 8) * (_PROBE_MAX_TOKENS + 100) / 1e6


def test_empty_price_map_prices_nothing():
    cfg = _cfg()
    counts = call_counts(cfg, PROMPTS)
    c = cost_ceiling(cfg, PROMPTS, counts, {})
    assert c.total_usd == 0
    assert set(c.unpriced) == {"a/one", "b/two", "c/judge"}
