"""Chance-corrected jury agreement, Fleiss' κ and pairwise Cohen's κ.

Pure Python, textbook math (adapted from the chennai fork's judge_stats):

* Fleiss (1971) κ for n raters × k categories, computed over rounds where the
  **full primary panel voted decisively** (Fleiss assumes a fixed rater count;
  abstentions and replacements make partial rounds incomparable, so they're
  excluded and the coverage is reported alongside).
* Cohen (1960) pairwise κ over each judge pair's co-voted rounds.
* Landis & Koch (1977) thresholds label the result.

Categories are the decisive votes: A / B / tie. Abstentions are evaluatorq's
consistency gate doing its job, they are not ratings and don't enter κ.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

_CATEGORIES = ("A", "B", "tie")


def landis_koch(kappa: float) -> str:
    if kappa < 0:
        return "poor"
    if kappa <= 0.20:
        return "slight"
    if kappa <= 0.40:
        return "fair"
    if kappa <= 0.60:
        return "moderate"
    if kappa <= 0.80:
        return "substantial"
    return "almost perfect"


def _decisive_votes(round_votes: list[dict[str, Any]]) -> dict[str, str]:
    """{judge_model: vote} for decisive, non-replacement votes in one round."""
    return {
        v["model"]: v["vote"]
        for v in round_votes
        if v.get("vote") in _CATEGORIES and not v.get("replacement")
    }


def fleiss_kappa(rounds: list[list[dict[str, Any]]], panel: list[str]) -> dict[str, Any]:
    """Fleiss' κ over rounds where every primary panelist voted decisively.

    ``rounds`` is a list of ``judge_votes`` lists (PairwiseVote dumps).
    Returns kappa, its Landis-Koch label, and coverage (used/total rounds).
    """
    n = len(panel)
    usable: list[Counter] = []
    for votes in rounds:
        decisive = _decisive_votes(votes)
        if all(j in decisive for j in panel):
            usable.append(Counter(decisive[j] for j in panel))

    total = len(rounds)
    if n < 2 or len(usable) < 2:
        return {"kappa": None, "label": "n/a", "rounds_used": len(usable), "rounds_total": total}

    N = len(usable)
    # P_i: agreement within each round; p_j: category prevalence.
    p_i_sum = 0.0
    cat_totals: Counter = Counter()
    for counts in usable:
        cat_totals.update(counts)
        p_i_sum += (sum(c * c for c in counts.values()) - n) / (n * (n - 1))
    p_bar = p_i_sum / N
    p_e = sum((cat_totals[c] / (N * n)) ** 2 for c in _CATEGORIES)
    kappa = 1.0 if p_e == 1.0 else (p_bar - p_e) / (1.0 - p_e)
    return {
        "kappa": round(kappa, 3),
        "label": landis_koch(kappa),
        "rounds_used": N,
        "rounds_total": total,
    }


def cohen_kappa_pairs(
    rounds: list[list[dict[str, Any]]], panel: list[str]
) -> dict[str, dict[str, Any]]:
    """Pairwise Cohen's κ over each judge pair's co-decisive rounds."""
    out: dict[str, dict[str, Any]] = {}
    for i, a in enumerate(panel):
        for b in panel[i + 1 :]:
            pairs: list[tuple[str, str]] = []
            for votes in rounds:
                decisive = _decisive_votes(votes)
                if a in decisive and b in decisive:
                    pairs.append((decisive[a], decisive[b]))
            key = f"{a.split('/')[-1]} × {b.split('/')[-1]}"
            if len(pairs) < 2:
                out[key] = {"kappa": None, "label": "n/a", "rounds": len(pairs)}
                continue
            n = len(pairs)
            p_o = sum(x == y for x, y in pairs) / n
            pa: Counter = Counter(x for x, _ in pairs)
            pb: Counter = Counter(y for _, y in pairs)
            p_e = sum((pa[c] / n) * (pb[c] / n) for c in _CATEGORIES)
            kappa = 1.0 if p_e == 1.0 else (p_o - p_e) / (1.0 - p_e)
            out[key] = {"kappa": round(kappa, 3), "label": landis_koch(kappa), "rounds": n}
    return out
