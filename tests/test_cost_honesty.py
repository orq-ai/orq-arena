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
    "prov/stand-in": (5.0, 15.0),  # 10x the primary panel, on purpose
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


def test_stand_ins_are_priced_at_their_own_rate_not_the_panel_s():
    """A cheap panel backed by an expensive stand-in must not slip past the
    figure: `prov/stand-in` costs 10x `prov/judge-1` in PRICES."""
    p = _project(_cfg(replacement_judges=["prov/stand-in"]))
    replacement_headroom = p.worst_case_usd - p.projected_usd - p.models_usd
    assert replacement_headroom > p.judges_usd * 5, (
        "the stand-in was priced at the primary panel's rate"
    )


def test_an_unpriced_stand_in_is_reported_not_silently_free():
    p = _project(_cfg(replacement_judges=["prov/no-price"]))
    assert "prov/no-price" in p.unpriced


def test_no_replacement_judges_means_no_replacement_headroom():
    p = _project(_cfg())
    assert p.worst_case_usd - p.projected_usd == pytest.approx(p.models_usd)  # retry only


def test_the_projection_is_the_number_a_clean_run_spends():
    """Both figures exist and differ, so no caller has to guess which it holds."""
    p = _project(_cfg())
    assert 0 < p.projected_usd < p.worst_case_usd


def test_prompt_tokens_are_estimated_so_neither_figure_is_a_hard_cap():
    """chars/4 under-counts dense scripts, so the same prompt length in CJK
    prices identically to ASCII while really costing more. Demonstrates why
    neither figure may be presented as a guaranteed cap."""
    ascii_prompts = [PromptItem(text="a" * 400)]
    cjk_prompts = [PromptItem(text="\u6f22" * 400)]
    cfg = _cfg()
    a = cost_projection(cfg, ascii_prompts, call_counts(cfg, ascii_prompts), PRICES)
    c = cost_projection(cfg, cjk_prompts, call_counts(cfg, cjk_prompts), PRICES)
    assert a.projected_usd == c.projected_usd


def test_unpriced_models_still_do_not_inflate_either_figure():
    cfg = _cfg(candidates=[{"model_id": "prov/a"}, {"model_id": "prov/unpriced"}])
    p = _project(cfg)
    assert "prov/unpriced" in p.unpriced
    assert p.projected_usd > 0 and p.worst_case_usd >= p.projected_usd
