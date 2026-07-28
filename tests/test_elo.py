"""Bradley-Terry ELO: higher win rate → higher rating; equal record → equal rating."""

from __future__ import annotations

from orq_arena.tournament.elo import bradley_terry_mle, build_wins_matrix


def test_clean_sweep_ranks_winner_highest() -> None:
    matches = [
        ("A", "B", "winner"),
        ("A", "C", "winner"),
        ("B", "C", "winner"),
    ]
    wins = build_wins_matrix(matches)
    elo = bradley_terry_mle(wins, ["A", "B", "C"])
    assert elo["A"] > elo["B"] > elo["C"]


def test_identical_records_yield_equal_elo() -> None:
    matches = [
        ("A", "B", "winner"),
        ("B", "A", "winner"),
    ]
    wins = build_wins_matrix(matches)
    elo = bradley_terry_mle(wins, ["A", "B"])
    assert abs(elo["A"] - elo["B"]) < 1e-6


def test_tie_splits_evenly() -> None:
    matches = [("A", "B", "tie")]
    wins = build_wins_matrix(matches)
    elo = bradley_terry_mle(wins, ["A", "B"])
    assert abs(elo["A"] - elo["B"]) < 1e-6


def test_ties_shift_ratings_symmetrically():
    # a beats c, b beats c, a ties b -> a and b should be equal, both above c
    matches = [("a", "c", "winner"), ("b", "c", "winner"), ("a", "b", "tie")]
    ratings = bradley_terry_mle(build_wins_matrix(matches), ["a", "b", "c"])
    assert abs(ratings["a"] - ratings["b"]) < 1.0
    assert ratings["a"] > ratings["c"]


# The longer answer usually wins, at TWO distinct length ratios, with wins
# nearly balanced between the models. All three properties are load-bearing:
# counterexamples keep the MLE finite (a clean sweep is separable), the second
# ratio keeps gamma identified (a single ratio makes d collinear with the pair
# indicator, a flat ridge on which any gamma fits equally well and the answer
# is path-dependent), and balance keeps the model term from soaking up the
# likelihood before the length term is measured.
STYLE_ROWS = (
    [("a", "b", 1.0, 400, 100)] * 18
    + [("a", "b", 0.0, 100, 400)] * 14
    + [("a", "b", 0.0, 400, 100)] * 4
    + [("a", "b", 1.0, 100, 400)] * 4
    + [("a", "b", 1.0, 300, 200)] * 10
    + [("a", "b", 0.0, 200, 300)] * 10
)


def test_style_control_absorbs_length_wins():
    from orq_arena.tournament.elo import style_controlled_elo

    fit = style_controlled_elo(STYLE_ROWS, ["a", "b"])
    assert fit.converged
    assert fit.gamma > 0  # the jury's length preference is exposed
    raw = bradley_terry_mle(
        build_wins_matrix([("a", "b", "winner")] * 32 + [("b", "a", "winner")] * 28), ["a", "b"]
    )
    # pricing length out shrinks the gap vs the raw fit
    assert abs(fit.elo["a"] - fit.elo["b"]) < abs(raw["a"] - raw["b"])


def test_style_control_refuses_separated_data():
    from orq_arena.tournament.elo import style_controlled_elo

    # The longer answer always wins: gamma has no finite maximum, and the old
    # code silently returned wherever its iteration budget ran out.
    rows = [("a", "b", 1.0, 400, 100)] * 10 + [("b", "a", 0.0, 100, 400)] * 10
    fit = style_controlled_elo(rows, ["a", "b"])
    assert not fit.converged


def test_style_control_neutral_without_length_signal():
    from orq_arena.tournament.elo import style_controlled_elo

    # Same lengths both sides: gamma has nothing to fit, ranking matches raw BT.
    rows = [("a", "b", 1.0, 200, 200)] * 6 + [("a", "b", 0.0, 200, 200)] * 2
    fit = style_controlled_elo(rows, ["a", "b"])
    assert fit.converged
    assert abs(fit.gamma) < 1e-3
    assert fit.elo["a"] > fit.elo["b"]


def test_style_control_empty_rows_is_flat():
    from orq_arena.tournament.elo import style_controlled_elo

    fit = style_controlled_elo([], ["a", "b"])
    assert fit.elo == {"a": 1000.0, "b": 1000.0}
    assert fit.gamma == 0.0
    assert fit.converged


def test_style_control_gamma_is_stable_under_a_bigger_budget():
    """The regression that shipped: gamma tracked the iteration count.

    2000 fixed gradient steps reported 3.44 on the example run while the MLE
    was 18.3; raising the budget moved the answer. A converged fit must give
    the same gamma no matter how much extra budget it is offered. The fixture
    has to carry two length ratios: on single-ratio (ridge) data the old
    estimator was *also* budget-stable, parked at an arbitrary point, and this
    test would discriminate nothing.
    """
    from orq_arena.tournament.elo import style_controlled_elo

    small = style_controlled_elo(STYLE_ROWS, ["a", "b"], max_iter=500)
    big = style_controlled_elo(STYLE_ROWS, ["a", "b"], max_iter=15000)
    assert small.converged and big.converged
    assert abs(small.gamma - big.gamma) < 1e-4


def test_judge_family_overlap_flags_shared_provider():
    from orq_arena.candidates import CandidateSpec
    from orq_arena.preflight import judge_family_overlaps

    candidates = [
        CandidateSpec(model_id="anthropic/claude-opus-4-8"),
        CandidateSpec(model_id="google/gemini-3.1-pro-preview"),
    ]
    judges = ["anthropic/claude-haiku-4-5-20251001", "mistral/mistral-small-2603"]
    assert judge_family_overlaps(judges, candidates) == ["anthropic/claude-haiku-4-5-20251001"]
    assert judge_family_overlaps(["mistral/mistral-small-2603"], candidates) == []


def test_bootstrap_ci_brackets_the_point_estimate():
    from orq_arena.tournament.elo import bootstrap_ci

    matches = [("a", "b", "winner")] * 6 + [("b", "a", "winner")] * 2
    ci = bootstrap_ci(matches, ["a", "b"], iterations=50)
    ratings = bradley_terry_mle(build_wins_matrix(matches), ["a", "b"])
    lo, hi = ci["a"]
    assert lo <= ratings["a"] <= hi
    assert lo < hi  # a real interval, not a point


def test_bootstrap_ci_percentile_indices_are_symmetric():
    # The percentile picks the nearest-rank index on (n-1) at both tails,
    # not -1 on the low side only. For n=50: floor(0.025*49)=1, floor(0.975*49)=47.
    from orq_arena.tournament import elo as elo_mod

    class _Fixed:
        def __init__(self, vals):
            self._vals = vals

        def randrange(self, _n):  # unused; monkeypatched refit ignores resample
            return 0

    fixed = [float(i) for i in range(50)]  # 0..49, already sorted
    orig_mle = elo_mod.bradley_terry_mle
    # Force each bootstrap iteration to yield a distinct known rating for 'a'.
    seq = iter(fixed)

    def fake_mle(_wins, models, iterations=100):
        return {m: (next(seq) if m == "a" else 1000.0) for m in models}

    elo_mod.bradley_terry_mle = fake_mle
    try:
        ci = elo_mod.bootstrap_ci([("a", "b", "winner")], ["a", "b"], iterations=50)
    finally:
        elo_mod.bradley_terry_mle = orig_mle
    # sorted vals = 0..49 -> lo index 1 (=1.0), hi index 47 (=47.0)
    assert ci["a"] == (1.0, 47.0)


def test_elo_is_anchored_at_1000_mean():
    from orq_arena.tournament.elo import style_controlled_elo

    # A balanced cycle (a>b>c>a) keeps every rating finite so the anchoring
    # convention is what's tested, not the log-strength clamp on a sweep.
    matches = [("a", "b", "winner"), ("b", "c", "winner"), ("c", "a", "winner")]
    bt = bradley_terry_mle(build_wins_matrix(matches), ["a", "b", "c"])
    # Both fits anchor mean log-strength to 0, i.e. mean ELO == 1000.
    assert abs(sum(bt.values()) / len(bt) - 1000.0) < 1e-6
    rows = [("a", "b", 1.0, 100, 100), ("b", "c", 1.0, 100, 100), ("c", "a", 1.0, 100, 100)]
    fit = style_controlled_elo(rows, ["a", "b", "c"])
    assert abs(sum(fit.elo.values()) / len(fit.elo) - 1000.0) < 1e-6
