"""Verdict → HP damage mapping.

A round where the panel's majority is ``DISCARD`` or ``TIE`` does not count
toward the round cap — no damage dealt, no round consumed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..config import MatchRules
from ..judges.schemas import JudgeResult

Side = Literal["a", "b", "none"]


@dataclass
class DamageResult:
    damage: int
    loser_side: Side
    counts_toward_cap: bool


def compute_damage(
    *,
    majority: Literal["A", "B", "TIE", "DISCARD"],
    verdicts: list[JudgeResult],
    rules: MatchRules,
) -> DamageResult:
    """Map (majority, verdict counts) to HP damage and loser side."""
    if majority in ("TIE", "DISCARD"):
        return DamageResult(damage=rules.damage_tie, loser_side="none", counts_toward_cap=False)

    n_total = len(verdicts) or 1
    n_agree = sum(1 for v in verdicts if v.verdict == majority)
    unanimous = n_agree == n_total

    damage = rules.damage_unanimous if unanimous else rules.damage_majority
    loser: Side = "b" if majority == "A" else "a"
    return DamageResult(damage=damage, loser_side=loser, counts_toward_cap=True)
