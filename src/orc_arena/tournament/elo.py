"""Bradley-Terry MLE ELO — adapted from orq-battlebench/ranking.py.

Pure Python, no numpy/scipy. Simplified for orc-arena: no bootstrap CIs.
Ties split 0.5 / 0.5 (standard Bradley-Terry treatment).
"""

from __future__ import annotations

import math
from collections import defaultdict


def build_wins_matrix(
    matches: list[tuple[str, str, str]],
) -> dict[str, dict[str, float]]:
    """Given (winner, loser, outcome) triples, build wins[i][j] = matches i beat j.

    ``outcome`` is 'winner' (winner beat loser) or 'tie'. For ties the inputs are
    the two participants and each gets 0.5.
    """
    wins: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for a, b, outcome in matches:
        if outcome == "tie":
            wins[a][b] += 0.5
            wins[b][a] += 0.5
        else:  # 'winner' — a beat b
            wins[a][b] += 1.0
    return wins


def bradley_terry_mle(
    wins: dict[str, dict[str, float]],
    models: list[str],
    iterations: int = 100,
    tol: float = 1e-6,
) -> dict[str, float]:
    """Iterative MLE. Returns {model: elo} anchored so geometric mean = 1000."""
    if not models:
        return {}
    ratings: dict[str, float] = {m: 1.0 for m in models}

    n_matrix: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for i in models:
        for j in models:
            if i == j:
                continue
            n_matrix[i][j] = wins.get(i, {}).get(j, 0) + wins.get(j, {}).get(i, 0)

    for _ in range(iterations):
        old = dict(ratings)
        for i in models:
            numerator = sum(wins.get(i, {}).get(j, 0) for j in models if j != i)
            denominator = 0.0
            for j in models:
                if j == i:
                    continue
                if n_matrix[i][j] > 0:
                    denominator += n_matrix[i][j] / (ratings[i] + ratings[j])
            ratings[i] = numerator / denominator if denominator > 0 else 1.0

        log_mean = sum(math.log(max(r, 1e-10)) for r in ratings.values()) / len(ratings)
        factor = math.exp(-log_mean)
        for m in ratings:
            ratings[m] *= factor

        if all(abs(ratings[m] - old[m]) < tol for m in models):
            break

    return {m: 400 * math.log10(max(r, 1e-10)) + 1000 for m, r in ratings.items()}
