"""Single-elimination bracket for 8 warriors.

Seeding follows the standard sports bracket: (1 vs 8), (4 vs 5), (3 vs 6), (2 vs 7).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

RoundName = Literal["quarterfinal", "semifinal", "final"]


@dataclass
class Matchup:
    match_id: str
    round_name: RoundName
    seed_a: int  # 1-indexed seed
    seed_b: int
    winner_seed: int | None = None


@dataclass
class Bracket:
    """8-warrior single-elim bracket; 3 rounds, 7 fights."""

    seeds: list[str] = field(default_factory=list)  # seeds[0] is seed 1
    rounds: list[list[Matchup]] = field(default_factory=list)

    @classmethod
    def seed_eight(cls, warrior_names: list[str]) -> "Bracket":
        if len(warrior_names) != 8:
            raise ValueError(f"Expected 8 warriors, got {len(warrior_names)}")
        # Standard bracket pairings (indices into seeds are 0-based but we
        # track 1-based seed numbers).
        pairings = [(1, 8), (4, 5), (3, 6), (2, 7)]
        quarter = [
            Matchup(match_id=f"QF{i+1}", round_name="quarterfinal", seed_a=a, seed_b=b)
            for i, (a, b) in enumerate(pairings)
        ]
        semi = [
            Matchup(match_id="SF1", round_name="semifinal", seed_a=0, seed_b=0),
            Matchup(match_id="SF2", round_name="semifinal", seed_a=0, seed_b=0),
        ]
        final = [Matchup(match_id="F1", round_name="final", seed_a=0, seed_b=0)]
        return cls(seeds=list(warrior_names), rounds=[quarter, semi, final])

    def name_for_seed(self, seed: int) -> str:
        return self.seeds[seed - 1]

    def next_open_match(self) -> Matchup | None:
        """Return the first unresolved matchup with both slots filled."""
        for rnd in self.rounds:
            for m in rnd:
                if m.winner_seed is None and m.seed_a and m.seed_b:
                    return m
        return None

    def record_winner(self, match_id: str, winner_seed: int) -> None:
        """Record a winner and propagate to the next round."""
        for r_idx, rnd in enumerate(self.rounds):
            for m_idx, m in enumerate(rnd):
                if m.match_id != match_id:
                    continue
                if winner_seed not in (m.seed_a, m.seed_b):
                    raise ValueError(
                        f"Winner seed {winner_seed} not in match {match_id}"
                    )
                m.winner_seed = winner_seed
                # Propagate
                if r_idx + 1 < len(self.rounds):
                    target_idx = m_idx // 2
                    slot = "seed_a" if m_idx % 2 == 0 else "seed_b"
                    target = self.rounds[r_idx + 1][target_idx]
                    setattr(target, slot, winner_seed)
                return
        raise KeyError(f"No match with id {match_id}")

    def champion(self) -> str | None:
        final = self.rounds[-1][0]
        if final.winner_seed is None:
            return None
        return self.name_for_seed(final.winner_seed)

    def as_display(self) -> list[list[list[str | None]]]:
        """Snapshot for TUI rendering (JSON-friendly lists, not tuples)."""
        out: list[list[list[str | None]]] = []
        for rnd in self.rounds:
            row: list[list[str | None]] = []
            for m in rnd:
                a = self.name_for_seed(m.seed_a) if m.seed_a else None
                b = self.name_for_seed(m.seed_b) if m.seed_b else None
                row.append([a, b])
            out.append(row)
        return out
