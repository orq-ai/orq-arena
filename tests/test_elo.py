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
