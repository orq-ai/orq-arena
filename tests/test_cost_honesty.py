"""The spend figure a user consents to must not promise more than it knows.

The regression this guards: the preflight figure was called a ceiling, and the
consent prompt read "spends up to $X", while the arithmetic behind it excluded
the one automatic candidate retry and any replacement judge, and estimated
prompt tokens from character count. A real run could cost more than the number
the user agreed to.
"""

from __future__ import annotations

import pytest

from orq_arena.config import ArenaConfig
from orq_arena.data.prompts import PromptItem
from orq_arena.preflight import call_counts, cost_projection

PRICES = {
    "prov/a": (1.0, 3.0),
    "prov/b": (1.0, 3.0),
    "prov/judge-1": (0.5, 1.5),
    "prov/stand-in": (0.5, 1.5),
}


def _cfg(**over) -> ArenaConfig:
    base = {
        "candidates": [{"model_id": "prov/a"}, {"model_id": "prov/b"}],
        "judges": ["prov/judge-1"],
        "preflight": {"thinking_probe": False},
        "match": {"max_rounds": 2},
    }
    return ArenaConfig.model_validate(base | over)


PROMPTS = [PromptItem(text="a question about something"), PromptItem(text="another one")]


def _project(cfg):
    return cost_projection(cfg, PROMPTS, call_counts(cfg, PROMPTS), PRICES)


def test_worst_case_covers_the_retry_the_projection_leaves_out():
    """Each side retries once on a stream failure, doubling that stream's spend."""
    p = _project(_cfg())
    assert p.worst_case_usd > p.projected_usd
    # Every model stream retried once is the bound; judges have no stand-in here.
    assert p.worst_case_usd == pytest.approx(p.projected_usd + p.models_usd)


def test_worst_case_covers_replacement_judges_when_configured():
    without = _project(_cfg())
    with_stand_in = _project(_cfg(replacement_judges=["prov/stand-in"]))
    # Same projected spend, because a stand-in only runs when a primary fails.
    assert with_stand_in.projected_usd == without.projected_usd
    # But the bound now has to carry a whole replacement panel.
    assert with_stand_in.worst_case_usd - with_stand_in.projected_usd > (
        without.worst_case_usd - without.projected_usd
    )


def test_no_replacement_judges_means_no_replacement_headroom():
    p = _project(_cfg())
    assert p.worst_case_usd - p.projected_usd == pytest.approx(p.models_usd)  # retry only


def test_projection_is_not_advertised_as_a_bound():
    """The type carries both numbers, so no caller has to guess which it holds."""
    p = _project(_cfg())
    assert hasattr(p, "projected_usd") and hasattr(p, "worst_case_usd")
    assert not hasattr(p, "total_usd"), "the old name asserted a bound it never was"


def test_prompt_tokens_are_estimated_and_the_type_says_so():
    """chars/4 under-counts CJK, code and dense punctuation, so neither figure
    is a hard guarantee and the docstring must not claim one."""
    assert "estimat" in (cost_projection.__doc__ or "").lower()
    from orq_arena import preflight

    assert "never over" not in (preflight.__doc__ or "")


def test_unpriced_models_still_do_not_inflate_either_figure():
    cfg = _cfg(candidates=[{"model_id": "prov/a"}, {"model_id": "prov/unpriced"}])
    p = _project(cfg)
    assert "prov/unpriced" in p.unpriced
    assert p.projected_usd > 0 and p.worst_case_usd >= p.projected_usd
