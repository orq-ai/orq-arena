"""Bracket seeding + winner propagation."""

from __future__ import annotations

import pytest

from orc_arena.tournament.bracket import Bracket

NAMES = [f"Orc{i}" for i in range(1, 9)]  # Orc1..Orc8


def test_seed_eight_produces_standard_pairings() -> None:
    bracket = Bracket.seed_eight(NAMES)
    qf = bracket.rounds[0]
    pairs = [(m.seed_a, m.seed_b) for m in qf]
    assert pairs == [(1, 8), (4, 5), (3, 6), (2, 7)]


def test_requires_eight_warriors() -> None:
    with pytest.raises(ValueError):
        Bracket.seed_eight(["only", "three", "names"])


def test_winner_propagates_to_semifinal() -> None:
    bracket = Bracket.seed_eight(NAMES)
    bracket.record_winner("QF1", 1)
    bracket.record_winner("QF2", 4)
    assert bracket.rounds[1][0].seed_a == 1
    assert bracket.rounds[1][0].seed_b == 4


def test_full_bracket_has_champion() -> None:
    bracket = Bracket.seed_eight(NAMES)
    # Top-seeds advance through every round.
    bracket.record_winner("QF1", 1)
    bracket.record_winner("QF2", 4)
    bracket.record_winner("QF3", 3)
    bracket.record_winner("QF4", 2)
    bracket.record_winner("SF1", 1)
    bracket.record_winner("SF2", 2)
    bracket.record_winner("F1", 1)
    assert bracket.champion() == "Orc1"


def test_next_open_match_returns_first_unresolved() -> None:
    bracket = Bracket.seed_eight(NAMES)
    assert bracket.next_open_match().match_id == "QF1"
    bracket.record_winner("QF1", 1)
    assert bracket.next_open_match().match_id == "QF2"
