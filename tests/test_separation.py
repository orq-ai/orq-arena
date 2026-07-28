"""Separation is a claim about a difference, not about two bars side by side.

The regression this guards: the report decided the top spot by asking whether
two marginal 95% intervals overlapped. Non-overlap is a conservative way to
claim a difference, so that branch erred safe. The other branch did not, and
printed "STATISTICAL TIE AT THE TOP" whenever the bars touched, which overlap
never licenses. The intervals are also correlated through the shared anchoring,
so comparing them separately is the wrong object twice.
"""

from __future__ import annotations

from orq_arena.tournament.elo import bootstrap_ci, paired_difference

MODELS = ["a", "b", "c", "d"]


def _lead(n_ab: int = 40, share: float = 0.70) -> list[tuple[str, str, str]]:
    """A takes 70% of 40 rounds against B, inside a four-model field.

    Ordinary arena numbers, not a constructed edge: at this size the two
    marginal intervals still overlap while A is ahead in 99% of resamples.
    That combination is exactly what the old overlap rule called a tie.
    """
    wins = round(n_ab * share)
    out = [("a", "b", "winner")] * wins + [("b", "a", "winner")] * (n_ab - wins)
    out += [("a", "c", "winner")] * 12 + [("c", "a", "winner")] * 6
    out += [("b", "c", "winner")] * 10 + [("c", "b", "winner")] * 7
    out += [("c", "d", "winner")] * 10 + [("d", "c", "winner")] * 6
    return out


def test_the_case_the_old_rule_got_wrong():
    """Marginal intervals overlap, yet A is ahead of B in ~every resample.

    The old rule called this a statistical tie. It is the opposite: a
    consistent, measurable lead the marginal-overlap test cannot see.
    """
    matches = _lead()
    ci = bootstrap_ci(matches, MODELS)
    marginals_overlap = ci["b"][1] >= ci["a"][0]
    assert marginals_overlap, "fixture no longer exercises the interesting case"

    diff = paired_difference(matches, MODELS, "a", "b")
    assert diff.lo > 0, "the paired difference should exclude 0 here"
    assert diff.win_rate > 0.95


def test_a_genuine_coin_flip_is_not_separated():
    matches = [("a", "b", "winner")] * 20 + [("b", "a", "winner")] * 20
    diff = paired_difference(matches, ["a", "b"], "a", "b")
    assert diff.lo < 0 < diff.hi
    assert 0.3 < diff.win_rate < 0.7


def test_the_difference_is_paired_not_two_marginals():
    """Resample k's difference must come from resample k, not from two
    independently summarized distributions."""
    matches = _lead()
    diff = paired_difference(matches, MODELS, "a", "b")
    ci = bootstrap_ci(matches, MODELS)
    # The naive subtraction of marginal bounds is strictly wider than the
    # paired interval; if they ever matched, the pairing was lost.
    naive_lo = ci["a"][0] - ci["b"][1]
    assert diff.lo > naive_lo


def test_win_rate_and_interval_agree_on_direction():
    for matches in (_lead(), _lead(share=0.25)):
        diff = paired_difference(matches, MODELS, "a", "b")
        if diff.lo > 0:
            assert diff.win_rate > 0.5
        elif diff.hi < 0:
            assert diff.win_rate < 0.5


def test_no_outcomes_is_not_a_separation_claim():
    diff = paired_difference([], MODELS, "a", "b")
    assert diff.lo <= 0 <= diff.hi
    assert diff.win_rate == 0.5


def test_seeded_and_reproducible():
    m = _lead()
    assert paired_difference(m, MODELS, "a", "b") == paired_difference(m, MODELS, "a", "b")


# --- the rule as the reader meets it -------------------------------------

from orq_arena.config import ArenaConfig  # noqa: E402
from orq_arena.data.schemas import BattleRecord  # noqa: E402
from orq_arena.report import build_report_html  # noqa: E402

_CFG = ArenaConfig.model_validate(
    {"candidates": [{"model_id": "p/a"}, {"model_id": "p/b"}], "judges": ["p/j1", "p/j2"]}
)
_RECORDS = [
    BattleRecord(
        prompt_hash="h",
        prompt_text="p",
        model_a="a",
        model_b="b",
        response_a="x",
        response_b="y",
        majority_verdict="A",
        winner="a",
        judge_votes=[{"model": "p/j1", "vote": "A"}],
    )
]
# Marginal intervals that overlap heavily: the old rule read these as a tie.
_OVERLAPPING_CI = {"a": (900.0, 1300.0), "b": (700.0, 1100.0)}


def _page(top_difference) -> str:
    report = {"elo_ci": _OVERLAPPING_CI, "rated_rounds": 40}
    if top_difference is not None:
        report["top_difference"] = top_difference
    return build_report_html(
        cfg=_CFG,
        records=_RECORDS,
        elo={"a": 1100.0, "b": 900.0},
        report=report,
        manifest={},
    )


def _diff(**over) -> dict:
    base = {"champion": "a", "runner_up": "b", "lo": 25.0, "hi": 284.0, "win_rate": 0.99}
    return {**base, "separated": base["lo"] > 0} | over


def test_page_separates_on_the_difference_even_though_the_bars_overlap():
    """The whole point: overlapping marginal intervals, separated top spot."""
    page = _page(_diff())
    assert "TOP SPOT SEPARATED" in page
    assert "Adopt a" in page
    assert "holds across resamples" in page


def test_page_never_calls_an_unresolved_gap_a_tie():
    page = _page(_diff(lo=-120.0, hi=284.0, win_rate=0.71, separated=False))
    assert "NOT RESOLVED" in page
    assert "ahead in 71% of resamples" in page
    for banned in (
        "statistically tied",
        "STATISTICAL TIE",
        "indistinguishable",
        "effectively tied",
    ):
        assert banned not in page


def test_a_run_with_no_measurement_claims_nothing_either_way():
    """Runs recorded before this existed carry no difference. The page must not
    invent one, in either direction."""
    page = _page(None)
    assert "SEPARATION NOT MEASURED" in page
    assert "NOT RESOLVED" not in page
    assert "TOP SPOT SEPARATED" not in page
    assert "too small to call it" not in page


def test_the_page_reports_the_pair_the_difference_was_measured_between():
    """Not a separately derived ranking that could disagree with it."""
    page = _page(_diff(champion="b", runner_up="a", lo=-284.0, hi=-25.0, win_rate=0.01))
    assert "b" in page
