"""Bradley-Terry MLE ELO, adapted from orq-battlebench/ranking.py.

Pure Python, no numpy/scipy. Ties split 0.5 / 0.5 (standard Bradley-Terry
treatment); percentile bootstrap CIs; optional length-controlled fit.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass


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
        else:  # 'winner', a beat b
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


def style_controlled_elo(
    rows: list[tuple[str, str, float, int, int]],
    models: list[str],
    iterations: int = 2000,
    lr: float = 0.05,
    tol: float = 1e-7,
) -> tuple[dict[str, float], float]:
    """Bradley-Terry as logistic regression with a length-difference covariate.

    The LMArena style-control / length-controlled AlpacaEval approach:
    P(A wins) = sigmoid(theta_a - theta_b + gamma * d) with
    d = (len_a - len_b) / (len_a + len_b), fit jointly, then the reported
    rating zeroes the length term. gamma > 0 means the jury favored longer
    answers; the style-controlled ELO is what remains once that preference
    is priced out.

    ``rows``: (model_a, model_b, y, len_a, len_b) with y = 1.0 A wins,
    0.0 B wins, 0.5 tie. Returns ({model: elo}, gamma), anchored like
    ``bradley_terry_mle`` (geometric mean at 1000).
    """
    if not rows or not models:
        return ({m: 1000.0 for m in models}, 0.0)
    theta = {m: 0.0 for m in models}
    gamma = 0.0
    n = len(rows)
    feats = [(a, b, y, (la - lb) / (la + lb) if (la + lb) > 0 else 0.0) for a, b, y, la, lb in rows]
    for _ in range(iterations):
        g_theta = {m: 0.0 for m in models}
        g_gamma = 0.0
        for a, b, y, d in feats:
            z = theta[a] - theta[b] + gamma * d
            p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
            err = y - p
            g_theta[a] += err
            g_theta[b] -= err
            g_gamma += err * d
        step = 0.0
        for m in models:
            delta = lr * g_theta[m] / n
            theta[m] += delta
            step = max(step, abs(delta))
        gd = lr * g_gamma / n
        gamma += gd
        step = max(step, abs(gd))
        mean = sum(theta.values()) / len(theta)
        for m in theta:
            theta[m] -= mean
        if step < tol:
            break
    ln10 = math.log(10)
    return ({m: 400 * t / ln10 + 1000 for m, t in theta.items()}, gamma)


# Resamples per bootstrap. 1000 costs milliseconds on a pool this size and
# steadies the tails; 200 left the 2.5th percentile jumping between runs.
BOOTSTRAP_ITERATIONS = 1000


def bootstrap_draws(
    matches: list[tuple[str, str, str]],
    models: list[str],
    iterations: int = BOOTSTRAP_ITERATIONS,
    seed: int = 42,
) -> list[dict[str, float]]:
    """One refitted rating vector per resample, kept whole.

    Callers summarize these same draws rather than resampling per question, so
    an interval and a difference computed for one report always describe the
    same bootstrap. Resampling twice would agree only for as long as both call
    sites happened to pass the same seed.
    """
    import random

    rng = random.Random(seed)
    out: list[dict[str, float]] = []
    for _ in range(iterations):
        resampled = [matches[rng.randrange(len(matches))] for _ in matches]
        ratings = bradley_terry_mle(build_wins_matrix(resampled), models, iterations=50)
        out.append({m: ratings.get(m, 1000.0) for m in models})
    return out


def _percentiles(vals: list[float]) -> tuple[float, float]:
    """Nearest-rank 2.5/97.5 percentiles on (n-1), symmetric at both tails."""
    vals = sorted(vals)
    n = len(vals)
    return vals[int(0.025 * (n - 1))], vals[int(0.975 * (n - 1))]


def bootstrap_ci(
    matches: list[tuple[str, str, str]],
    models: list[str],
    iterations: int = BOOTSTRAP_ITERATIONS,
    seed: int = 42,
) -> dict[str, tuple[float, float]]:
    """Percentile bootstrap 95% CI on the BT-MLE ratings.

    Resamples the outcome list with replacement ``iterations`` times and
    refits. Small pools + few comparisons => wide intervals, which is the
    honest output.

    These are *marginal* intervals: read one at a time. Two of them overlapping
    says nothing about whether those two models differ, because they are drawn
    from the same resamples and share the anchoring. For that question use
    ``paired_difference``.
    """
    if not matches:
        return {m: (1000.0, 1000.0) for m in models}
    return ci_from_draws(bootstrap_draws(matches, models, iterations, seed), models)


def ci_from_draws(
    draws: list[dict[str, float]], models: list[str]
) -> dict[str, tuple[float, float]]:
    """Marginal 95% intervals from pre-computed draws."""
    if not draws:
        return {m: (1000.0, 1000.0) for m in models}
    return {m: _percentiles([d[m] for d in draws]) for m in models}


@dataclass(frozen=True)
class Difference:
    """The bootstrap distribution of one model's rating minus another's.

    ``lo``/``hi`` are the 95% interval on that difference; it excluding 0 is
    what "separated" means. ``win_rate`` is the share of resamples where the
    first model came out ahead, which stays readable when the interval doesn't
    exclude 0: "ahead in 71% of resamples" is a measurement, where "tied" would
    be a claim the data cannot support.
    """

    lo: float
    hi: float
    win_rate: float

    @property
    def separated(self) -> bool:
        """True when the interval excludes 0, in either direction."""
        return self.lo > 0.0 or self.hi < 0.0


def paired_difference(
    matches: list[tuple[str, str, str]],
    models: list[str],
    a: str,
    b: str,
    iterations: int = BOOTSTRAP_ITERATIONS,
    seed: int = 42,
) -> Difference:
    """Bootstrap ``rating[a] - rating[b]``, differenced within each resample.

    Subtracting two marginal intervals instead would ignore that the two
    ratings move together across resamples, and give an interval far too wide
    to ever separate anything.
    """
    if not matches:
        return Difference(lo=0.0, hi=0.0, win_rate=0.5)
    return difference_from_draws(bootstrap_draws(matches, models, iterations, seed), a, b)


def difference_from_draws(draws: list[dict[str, float]], a: str, b: str) -> Difference:
    """``rating[a] - rating[b]`` from pre-computed draws, differenced per draw."""
    if not draws:
        return Difference(lo=0.0, hi=0.0, win_rate=0.5)
    diffs = [d[a] - d[b] for d in draws]
    lo, hi = _percentiles(diffs)
    return Difference(lo=lo, hi=hi, win_rate=sum(d > 0 for d in diffs) / len(diffs))
