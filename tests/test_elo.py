"""Bradley-Terry ELO: higher win rate → higher rating; equal record → equal rating."""

from __future__ import annotations

from orc_arena.tournament.elo import bradley_terry_mle, build_wins_matrix


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


def test_bootstrap_ci_brackets_the_point_estimate():
    from orc_arena.tournament.elo import bootstrap_ci

    matches = [("a", "b", "winner")] * 6 + [("b", "a", "winner")] * 2
    ci = bootstrap_ci(matches, ["a", "b"], iterations=50)
    ratings = bradley_terry_mle(build_wins_matrix(matches), ["a", "b"])
    lo, hi = ci["a"]
    assert lo <= ratings["a"] <= hi
    assert lo < hi  # a real interval, not a point
