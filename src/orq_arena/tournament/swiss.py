"""Swiss/Monrad pairing for large pools — same benchmark, scaled.

Ported from the chennai fork. Bradley-Terry estimates converge faster when
strong models play strong models; random pairing needs roughly 3× the matches
for equivalent ranking confidence. Swiss approximates a near-optimal
active-learning schedule cheaply.

Pairing consumes **match winners** (the HP show, decision 15); the rating
itself never stops being per-round. Auto-switched by the driver for pools
larger than 8 — never a user-facing mode.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class _SwissState:
    scores: dict[str, float] = field(default_factory=dict)
    played: set[frozenset] = field(default_factory=set)


class SwissScheduler:
    """Pair by score group, avoid rematches; float one model on odd rounds."""

    def __init__(self, names: list[str]) -> None:
        self._state = _SwissState(scores={n: 0.0 for n in names})

    def record_outcome(self, winner: str, loser: str, *, tie: bool = False) -> None:
        if tie:
            self._state.scores[winner] += 0.5
            self._state.scores[loser] += 0.5
        else:
            self._state.scores[winner] += 1.0
        self._state.played.add(frozenset({winner, loser}))

    def next_round_pairs(self) -> list[tuple[str, str]]:
        """Sort by descending score (name-stable), pair nearest rematch-free."""
        ordered = sorted(
            self._state.scores.keys(),
            key=lambda n: (-self._state.scores[n], n),
        )
        unpicked = list(ordered)
        pairs: list[tuple[str, str]] = []
        while len(unpicked) >= 2:
            head = unpicked.pop(0)
            partner = self._pick_partner(head, unpicked)
            if partner is None:
                continue  # odd float — head sits this round out
            unpicked.remove(partner)
            pairs.append((head, partner))
        return pairs

    def _pick_partner(self, head: str, candidates: list[str]) -> str | None:
        for cand in candidates:
            if frozenset({head, cand}) not in self._state.played:
                return cand
        # Everyone remaining already played head — repeat beats skipping.
        return candidates[0] if candidates else None
