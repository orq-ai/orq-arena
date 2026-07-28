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


@dataclass(frozen=True)
class StyleFit:
    """A length-controlled fit that either converged or says so.

    The previous version returned wherever 2000 fixed gradient steps stopped.
    On the committed example run that was gamma=3.44 against a true MLE of
    18.3, and the column fit at the wrong gamma reordered the leaderboard
    (RES-1150). A fit that cannot certify convergence reports it, and the
    caller publishes no coefficient rather than a number that measures the
    iteration budget.

    ``converged`` is the whole-fit verdict (every played rating and gamma at
    an interior optimum), the bar for publishing the length-adjusted column.
    ``gamma_converged`` judges the length coefficient alone: a bootstrap
    resample can crater one model's rating (all its rounds redrawn as losses)
    while gamma sits at a perfectly good maximum, and calling that draw
    "gamma separated" would misstate which parameter failed.
    """

    elo: dict[str, float]
    gamma: float
    converged: bool
    gamma_converged: bool


def _style_loglik(
    theta: list[float], gamma: float, feats: list[tuple[int, int, float, float]]
) -> float:
    s = 0.0
    for a, b, y, d in feats:
        z = max(-30.0, min(30.0, theta[a] - theta[b] + gamma * d))
        p = 1.0 / (1.0 + math.exp(-z))
        s += y * math.log(max(p, 1e-12)) + (1.0 - y) * math.log(max(1.0 - p, 1e-12))
    return s


def style_controlled_elo(
    rows: list[tuple[str, str, float, int, int]],
    models: list[str],
    max_iter: int = 500,
    gtol: float = 1e-6,
    warm: StyleFit | None = None,
) -> StyleFit:
    """Bradley-Terry as logistic regression with a length-difference covariate.

    The LMArena style-control / length-controlled AlpacaEval approach:
    P(A wins) = sigmoid(theta_a - theta_b + gamma * d) with
    d = (len_a - len_b) / (len_a + len_b) in characters, fit jointly, then the
    reported rating zeroes the length term. gamma > 0 means the jury favored
    longer answers.

    Diagonal-Newton with a backtracking line search on the log-likelihood,
    stopping on the **gradient norm**. Each piece is load-bearing: plain
    gradient descent needed ~500k iterations to reach this MLE (the shipped
    2000 got a fifth of the way and shipped that), an undamped Newton step
    diverges outright on this likelihood, and a step-size stopping test never
    fires on a slow crawl. On separable data (the longer answer always wins)
    no finite maximum exists; the loop runs out and returns converged=False.

    ``rows``: (model_a, model_b, y, len_a, len_b) with y = 1.0 A wins,
    0.0 B wins, 0.5 tie. ``elo`` is anchored like ``bradley_terry_mle``
    (geometric mean at 1000).
    """
    if not rows or not models:
        return StyleFit({m: 1000.0 for m in models}, 0.0, converged=True, gamma_converged=True)
    idx = {m: i for i, m in enumerate(models)}
    feats = [
        (idx[a], idx[b], y, (la - lb) / (la + lb) if (la + lb) > 0 else 0.0)
        for a, b, y, la, lb in rows
    ]
    ln10 = math.log(10)
    if warm is None:
        theta = [0.0] * len(models)
        gamma = 0.0
    else:
        # Bootstrap draws start at the full-data optimum: a resample's maximum
        # sits nearby, so a converged draw takes a handful of steps instead of
        # hundreds, and a separated one runs off immediately instead of
        # spending its whole budget mid-climb and being miscounted.
        theta = [(warm.elo.get(m, 1000.0) - 1000.0) * ln10 / 400.0 for m in models]
        gamma = warm.gamma
    ll = _style_loglik(theta, gamma, feats)
    played = {a for a, _b, _y, _d in feats} | {b for _a, b, _y, _d in feats}
    has_length_signal = any(f[3] != 0.0 for f in feats)
    converged = False
    gamma_converged = False
    for _ in range(max_iter):
        g_theta = [0.0] * len(models)
        g_gamma = 0.0
        h_theta = [1e-9] * len(models)  # Hessian-diagonal floor: unplayed models
        h_gamma = 1e-9
        for a, b, y, d in feats:
            z = max(-30.0, min(30.0, theta[a] - theta[b] + gamma * d))
            p = 1.0 / (1.0 + math.exp(-z))
            w = max(p * (1.0 - p), 1e-9)
            err = y - p
            g_theta[a] += err
            g_theta[b] -= err
            g_gamma += err * d
            h_theta[a] += w
            h_theta[b] += w
            h_gamma += w * d * d
        # A vanishing gradient is necessary, not sufficient: separable data
        # drives every p toward 1, so errors AND curvature both collapse
        # toward gtol, and "the optimum" is wherever saturation stalled, with
        # theta and gamma split arbitrarily. An interior maximum keeps
        # per-parameter curvature orders of magnitude above that (every
        # unsaturated row contributes p(1-p) ~ 0.1). Parameters with no data
        # are exempt: an unplayed model stays anchored at 0, and all-equal
        # lengths legitimately pin gamma there too.
        gamma_converged = abs(g_gamma) < gtol and (not has_length_signal or h_gamma > 100 * gtol)
        if max(max(abs(g) for g in g_theta), abs(g_gamma)) < gtol:
            converged = gamma_converged and all(h_theta[i] > 100 * gtol for i in played)
            break
        step = 1.0
        while step > 1e-8:
            cand_theta = [t + step * g_theta[i] / h_theta[i] for i, t in enumerate(theta)]
            cand_gamma = gamma + step * g_gamma / h_gamma
            mean = sum(cand_theta) / len(cand_theta)
            cand_theta = [t - mean for t in cand_theta]  # loglik-invariant anchor
            cand_ll = _style_loglik(cand_theta, cand_gamma, feats)
            if cand_ll > ll:
                break
            step /= 2
        else:
            # No ascent step exists at float precision. For gamma this is a
            # verdict, not a failure: the flag above says whether it settled
            # (a draw that craters one model stalls here with gamma at a
            # perfectly good maximum). The whole fit stays unconverged.
            break
        theta, gamma, ll = cand_theta, cand_gamma, cand_ll
    elo = {m: 400 * theta[i] / ln10 + 1000 for m, i in idx.items()}
    return StyleFit(elo, gamma, converged, gamma_converged)


@dataclass(frozen=True)
class GammaInterval:
    """Percentile interval for the length coefficient, honest about infinity.

    A resample where the longer answer always wins has no finite MLE; its fit
    never converges. Such draws are placed at signed infinity rather than
    dropped, so they widen the interval instead of silently tightening it. A
    bound that lands on infinity reports as None (unbounded on that side).
    """

    lo: float | None
    hi: float | None
    separated: int  # draws whose fit ran off without a finite maximum
    draws: int

    @property
    def excludes_zero(self) -> bool:
        """[lo, +inf) excludes 0 iff lo > 0; (-inf, hi] iff hi < 0."""
        if self.lo is not None and self.lo > 0.0:
            return True
        return self.hi is not None and self.hi < 0.0


def bootstrap_gamma(
    rows: list[tuple[str, str, float, int, int]],
    models: list[str],
    draws: int = 400,
    seed: int = 42,
    max_iter: int = 1000,
    warm: StyleFit | None = None,
) -> GammaInterval:
    """Bootstrap the length coefficient over the style rows.

    Its own resample: the rating bootstrap's draws carry (a, b, verdict)
    triples with no lengths, so gamma cannot be read off them. Pass the
    full-data fit as ``warm`` so each draw starts at that optimum.

    # ponytail: a draw that hasn't converged by max_iter counts as separated,
    # which can only widen the interval; raise max_iter if that margin matters
    """
    import random

    rng = random.Random(seed)
    vals: list[float] = []
    separated = 0
    for _ in range(draws):
        resampled = [rows[rng.randrange(len(rows))] for _ in rows]
        fit = style_controlled_elo(resampled, models, max_iter=max_iter, warm=warm)
        # gamma_converged, not converged: a draw may crater one model's rating
        # (that parameter separates) while gamma sits at a clean maximum, and
        # this interval is about gamma alone.
        if fit.gamma_converged:
            vals.append(fit.gamma)
        else:
            separated += 1
            vals.append(math.copysign(math.inf, fit.gamma))
    lo, hi = _percentiles(vals)
    return GammaInterval(
        lo=None if math.isinf(lo) else lo,
        hi=None if math.isinf(hi) else hi,
        separated=separated,
        draws=draws,
    )


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
