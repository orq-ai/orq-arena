"""Presentational HP model for the live show.

The engine stopped tracking HP: it was never scored, only shown. The TUI
recomputes the health bars locally from the same judged verdicts the rating
uses, so the drama is a pure function of the votes with nothing leaking into
the record. Damage tiers mirror the old ``compute_damage``: a unanimous
decisive panel hits harder than a split one; ties and inconclusive rounds
deal nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Seconds the fight screen holds each verdict on screen before the next round
# (was ``MatchRules.verdict_hold_s``; now a TUI concern).
VERDICT_HOLD_S = 2.5


@dataclass
class TurnOutcome:
    damage: int
    loser_side: Literal["a", "b", "none"]
    hp_a: int
    hp_b: int


class HPTracker:
    """One per match; fed the round's judge votes then its majority verdict."""

    def __init__(self, *, starting_hp: int, damage_unanimous: int, damage_majority: int) -> None:
        self._start = starting_hp
        self._unanimous = damage_unanimous
        self._majority = damage_majority
        self._hp_a = starting_hp
        self._hp_b = starting_hp
        self._votes: list[str] = []

    def start_match(self) -> None:
        self._hp_a = self._start
        self._hp_b = self._start
        self._votes = []

    def note_vote(self, verdict: str) -> None:
        """Buffer one judge's vote for the current round ('A'|'B'|'tie'|'abstain')."""
        self._votes.append(verdict)

    def clear_votes(self) -> None:
        self._votes = []

    def resolve_turn(self, majority: str) -> TurnOutcome:
        """Apply the round's damage and return the resulting bars.

        Mirrors the retired ``compute_damage``: decisive = votes in A/B/tie;
        unanimous (>=2 decisive, all agreeing with the winner) hits harder.
        """
        decisive = [v for v in self._votes if v in ("A", "B", "tie")]
        self.clear_votes()
        if majority not in ("A", "B"):
            return TurnOutcome(damage=0, loser_side="none", hp_a=self._hp_a, hp_b=self._hp_b)
        unanimous = len(decisive) >= 2 and all(v == majority for v in decisive)
        damage = self._unanimous if unanimous else self._majority
        loser_side: Literal["a", "b"] = "b" if majority == "A" else "a"
        if loser_side == "a":
            self._hp_a = max(0, self._hp_a - damage)
        else:
            self._hp_b = max(0, self._hp_b - damage)
        return TurnOutcome(damage=damage, loser_side=loser_side, hp_a=self._hp_a, hp_b=self._hp_b)

    @property
    def ko_side(self) -> Literal["a", "b", "none"]:
        if self._hp_a <= 0 and self._hp_b > 0:
            return "a"
        if self._hp_b <= 0 and self._hp_a > 0:
            return "b"
        return "none"
