"""The length claim is published only as strongly as the data supports it.

The regression this guards (RES-1150): the length coefficient was whatever
2000 fixed gradient steps reached (3.44 on the committed run, against a true
MLE of 18.3), the length-adjusted column was fit at that wrong gamma, and
correcting it reordered the leaderboard. The rules now: the headline is a
plain count; the modelled coefficient and its column appear only when the fit
converges and a bootstrap interval excludes 0; resamples with no finite
maximum are disclosed, not dropped.
"""

from __future__ import annotations

from orq_arena.config import ArenaConfig
from orq_arena.data.schemas import BattleRecord
from orq_arena.tournament.driver import rebuild_from_log
from orq_arena.tournament.elo import GammaInterval, bootstrap_gamma, style_controlled_elo

CFG = ArenaConfig.model_validate(
    {
        "candidates": [{"model_id": "prov/a"}, {"model_id": "prov/b"}],
        "judges": ["prov/j1", "prov/j2"],
    }
)


def _record(n: int, verdict: str, len_a: int, len_b: int) -> BattleRecord:
    return BattleRecord(
        prompt_hash=f"h{n}",
        prompt_text="p",
        model_a="a",
        model_b="b",
        model_a_id="prov/a",
        model_b_id="prov/b",
        response_a="x" * len_a,
        response_b="y" * len_b,
        majority_verdict=verdict,
        winner={"A": "a", "B": "b"}.get(verdict, verdict),
        judge_votes=[{"model": "prov/j1", "vote": verdict}],
    )


# Strong length signal without separation: the longer side usually wins, in
# both seat arrangements and at two distinct length ratios, with enough
# counterexamples to keep the maximum finite.
IDENTIFIED = (
    [_record(i, "A", 400, 100) for i in range(16)]
    + [_record(16 + i, "B", 100, 400) for i in range(16)]
    + [_record(32 + i, "B", 400, 100) for i in range(4)]
    + [_record(36 + i, "A", 100, 400) for i in range(4)]
    + [_record(40 + i, "A", 300, 200) for i in range(10)]
    + [_record(50 + i, "B", 200, 300) for i in range(10)]
)

# No length signal at all: every response the same length, winners split.
NO_SIGNAL = [_record(i, "A" if i % 3 else "B", 200, 200) for i in range(24)]


def test_identified_run_publishes_count_coefficient_and_column():
    _, report = rebuild_from_log(CFG, IDENTIFIED)
    pref = report["length_pref"]
    # 16+16 rounds the longer side won, +4+4 it lost, +10+10 it won again.
    assert pref == {"longer_wins": 52, "rounds": 60}
    assert report["length_coef"] is not None and report["length_coef"] > 0
    ci = report["length_coef_ci"]
    assert ci["lo"] is not None and ci["lo"] > 0
    assert ci["draws"] > 0
    assert set(report["elo_style_controlled"]) == {"a", "b"}


def test_no_signal_run_keeps_the_count_but_withholds_the_model():
    """Equal lengths pin gamma at 0; an interval through 0 publishes nothing."""
    _, report = rebuild_from_log(CFG, NO_SIGNAL)
    assert report["length_pref"] is None  # no round had a longer answer
    assert report["length_coef"] is None
    assert report["length_coef_ci"] is None
    assert report["elo_style_controlled"] is None


def test_separated_run_withholds_the_model():
    """The longer answer always wins: no finite MLE exists, so no number."""
    records = [_record(i, "A", 400, 100) for i in range(10)] + [
        _record(10 + i, "B", 100, 400) for i in range(10)
    ]
    _, report = rebuild_from_log(CFG, records)
    assert report["length_pref"] == {"longer_wins": 20, "rounds": 20}
    assert report["length_coef"] is None
    assert report["elo_style_controlled"] is None


def test_equal_length_rounds_never_enter_the_count():
    """A round with no longer answer can neither win nor lose the headline."""
    records = IDENTIFIED[:10] + [_record(100 + i, "A", 250, 250) for i in range(5)]
    _, report = rebuild_from_log(CFG, records)
    assert report["length_pref"]["rounds"] == 10


def test_bootstrap_places_separated_draws_at_signed_infinity():
    """Resamples of separable data go to the tail they ran toward; a bound
    that lands there reports as unbounded instead of pretending a number."""
    rows = [("a", "b", 1.0, 400, 100)] * 10 + [("b", "a", 0.0, 100, 400)] * 10
    ci = bootstrap_gamma(rows, ["a", "b"], draws=20, max_iter=60)
    assert ci.separated == 20
    assert ci.lo is None and ci.hi is None
    assert not ci.excludes_zero


def test_gamma_interval_excludes_zero_semantics():
    assert GammaInterval(lo=2.0, hi=None, separated=5, draws=100).excludes_zero
    assert GammaInterval(lo=None, hi=-1.0, separated=5, draws=100).excludes_zero
    assert not GammaInterval(lo=-1.0, hi=3.0, separated=0, draws=100).excludes_zero
    assert not GammaInterval(lo=None, hi=None, separated=100, draws=100).excludes_zero


def test_a_cratered_model_does_not_masquerade_as_gamma_separation():
    """One model losing every round separates *its rating*, not gamma. The
    whole fit rightly refuses, but the gamma-specific verdict stands, so a
    bootstrap draw like this lands in the interval instead of at infinity."""
    rows = (
        # c loses everything, at mixed lengths, so theta_c has no floor...
        [("a", "c", 1.0, 300, 200)] * 6
        + [("c", "b", 0.0, 200, 300)] * 6
        # ...while a-vs-b rounds carry a finite, unremarkable length signal.
        + [("a", "b", 1.0, 400, 100)] * 4
        + [("b", "a", 0.0, 100, 400)] * 4
        + [("a", "b", 0.0, 400, 100)] * 2
        + [("b", "a", 1.0, 100, 400)] * 2
    )
    fit = style_controlled_elo(rows, ["a", "b", "c"])
    assert not fit.converged
    assert fit.gamma_converged
    # The bootstrap must make the same distinction: draws that crater c keep
    # contributing their finite gamma. Classifying on the whole-fit verdict
    # would call most of these draws "separated" and blow the count up.
    ci = bootstrap_gamma(rows, ["a", "b", "c"], draws=60)
    assert ci.separated < 10, f"{ci.separated}/60 draws misfiled as gamma separation"
