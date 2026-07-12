"""evaluatorq pairwise verdict → HP damage mapping.

A round whose consensus is ``tie`` or ``inconclusive`` deals no damage and
does not count toward the round cap.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from evaluatorq import PairwiseComparison

from ..config import MatchRules

Side = Literal["a", "b", "none"]


@dataclass
class DamageResult:
    damage: int
    loser_side: Side
    counts_toward_cap: bool


def compute_damage(*, comparison: PairwiseComparison, rules: MatchRules) -> DamageResult:
    """Map a panel's reconciled comparison to HP damage and loser side."""
    winner = comparison.winner  # 'A' | 'B' | 'tie' | 'inconclusive'
    if winner not in ("A", "B"):
        return DamageResult(damage=rules.damage_tie, loser_side="none", counts_toward_cap=False)

    decisive = [v for v in comparison.votes if v.vote in ("A", "B", "tie")]
    # "Unanimous" needs at least two decisive votes agreeing on the winner,
    # a degraded panel can never land the big hit on its own say-so.
    unanimous = len(decisive) >= 2 and all(v.vote == winner for v in decisive)
    damage = rules.damage_unanimous if unanimous else rules.damage_majority
    return DamageResult(
        damage=damage,
        loser_side="b" if winner == "A" else "a",
        counts_toward_cap=True,
    )
