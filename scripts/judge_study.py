"""Compare jury panels judged over the same recorded rounds, as markdown tables.

Feeds docs/research/llm-judges-vs-decision-models.md: every number in that page
comes out of this script, run over the logs `orq-arena rejudge --output` wrote.
No API calls.

    uv run python scripts/judge_study.py --ref REF.jsonl NAME=LOG.jsonl [NAME=LOG.jsonl ...]

``--ref`` is the panel the others are measured against (the recorded LLM jury).
"""

from __future__ import annotations

import argparse
import statistics
from collections import Counter

from evaluatorq import PairwiseComparison, build_report

from orq_arena.analysis.kappa import fleiss_kappa
from orq_arena.data.schemas import BattleRecord, load_records
from orq_arena.judging import apply_abstain_floor, judge_labels, top_probability
from orq_arena.rejudge import _ranking, outcomes_from_majorities, spearman

FLOORS = (0.5, 0.6, 0.7, 0.8, 0.9)
CONFIDENCE_BINS = ((0.0, 0.6), (0.6, 0.8), (0.8, 0.95), (0.95, 1.01))


def judged(path: str) -> list[BattleRecord]:
    return [r for r in load_records(path) if r.error is None and r.response_a and r.response_b]


def key(r: BattleRecord) -> tuple:
    return (r.match_id, r.round_number, r.prompt_hash)


def comparisons(records: list[BattleRecord]) -> list[PairwiseComparison]:
    return [
        PairwiseComparison.model_validate({"winner": r.majority_verdict, "votes": r.judge_votes})
        for r in records
    ]


def cohen(a: list[str], b: list[str]) -> float | None:
    """Cohen's kappa between two raters over the same items."""
    n = len(a)
    if not n:
        return None
    po = sum(x == y for x, y in zip(a, b, strict=True)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / n**2
    return None if pe == 1 else (po - pe) / (1 - pe)


def agreement(winners: list[str], ref: list[str]) -> tuple[int, float | None, float | None]:
    """Rounds both decided, raw agreement, and Cohen's kappa over them."""
    both = [(w, r) for w, r in zip(winners, ref, strict=True) if "inconclusive" not in (w, r)]
    if not both:
        return 0, None, None
    a, b = [w for w, _ in both], [r for _, r in both]
    return len(both), sum(x == y for x, y in both) / len(both), cohen(a, b)


def ranking(records: list[BattleRecord], winners: list[str]) -> list[str]:
    pairs = [(r.rating_key("a"), r.rating_key("b")) for r in records]
    models = sorted({m for p in pairs for m in p})
    return _ranking(outcomes_from_majorities(pairs, winners), models)


def longer_wins(records: list[BattleRecord], winners: list[str]) -> float | None:
    rows = [
        (len(r.response_a) > len(r.response_b)) == (w == "A")
        for r, w in zip(records, winners, strict=True)
        if w in ("A", "B") and len(r.response_a) != len(r.response_b)
    ]
    return sum(rows) / len(rows) if rows else None


def first_seat_rate(records: list[BattleRecord], model: str) -> float | None:
    """How often the judge picked whichever response sat first, over decisive A/B passes.

    0.5 is no seat preference. Read off the per-ordering observations, which logs
    judged before evaluatorq recorded them do not have.
    """
    picks = []
    for r in records:
        for v in r.judge_votes:
            if v.get("model") != model:
                continue
            for o in v.get("observations") or []:
                if o.get("verdict") in ("A", "B"):
                    first = "A" if o.get("ordering") == "ab" else "B"
                    picks.append(o["verdict"] == first)
    return sum(picks) / len(picks) if picks else None


def pct(x: float | None, places: int = 0) -> str:
    return "n/a" if x is None else f"{x:.{places}%}"


def num(x: float | None, places: int = 2) -> str:
    return "n/a" if x is None else f"{x:.{places}f}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ref", required=True)
    ap.add_argument("logs", nargs="+", metavar="NAME=LOG")
    ap.add_argument(
        "--sweep",
        metavar="NAME",
        help="Also score every 1-, 3-, 5- and 7-judge sub-panel of this panel's judges.",
    )
    args = ap.parse_args()

    ref = {key(r): r for r in judged(args.ref)}
    panels: list[tuple[str, list[BattleRecord]]] = []
    for item in args.logs:
        name, _, path = item.partition("=")
        recs = [r for r in judged(path) if key(r) in ref]
        panels.append((name, recs))

    print(f"Reference: `{args.ref}`, {len(ref)} judged rounds.\n")
    print(
        "| Panel | Rounds | Decided | Ties | Spearman vs ref | Agreement vs ref "
        "| Cohen's κ vs ref | Fleiss κ | Longer answer won | Jury $ | $ per 1k rounds "
        "| p50 / p95 s per round |"
    )
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for name, recs in panels:
        winners = [r.majority_verdict for r in recs]
        ref_w = [ref[key(r)].majority_verdict for r in recs]
        decided = [w for w in winners if w != "inconclusive"]
        both, agree, kappa = agreement(winners, ref_w)
        rho = spearman(ranking(recs, ref_w), ranking(recs, winners))
        panel = list(dict.fromkeys(v["model"] for r in recs for v in r.judge_votes))
        fleiss = fleiss_kappa([r.judge_votes for r in recs], panel).get("kappa")
        costs = [r.judge_cost_usd for r in recs]
        cost = sum(costs) if costs and all(c is not None for c in costs) else None
        ms = sorted(r.judge_ms for r in recs if r.judge_ms)
        lat = (
            f"{statistics.median(ms) / 1000:.1f} / {ms[int(0.95 * (len(ms) - 1))] / 1000:.1f}"
            if ms
            else "n/a"
        )
        print(
            f"| {name} | {len(recs)} | {pct(len(decided) / len(recs))} "
            f"| {pct(decided.count('tie') / len(decided) if decided else None)} | {num(rho)} "
            f"| {pct(agree)} ({both}) | {num(kappa)} | {num(fleiss)} "
            f"| {pct(longer_wins(recs, winners))} "
            f"| {'n/a' if cost is None else f'${cost:.3f}'} "
            f"| {'n/a' if cost is None else f'${cost * 1000 / len(recs):.2f}'} | {lat} |"
        )

    print("\nPer judge:\n")
    print(
        "| Panel | Judge | Flip rate | First-seat picks | Tie rate | Mean confidence "
        "| Failed or no answer |"
    )
    print("|---|---|---|---|---|---|---|")
    for name, recs in panels:
        report = build_report(comparisons(recs))
        labels = judge_labels([j.model for j in report.per_judge])
        for j in report.per_judge:
            votes = [v for r in recs for v in r.judge_votes if v["model"] == j.model]
            conf = [p for v in votes if (p := top_probability(v)) is not None]
            failed = sum(
                1
                for v in votes
                if v.get("vote") is None
                and not v.get("flipped")
                and not any(o.get("verdict") for o in v.get("observations") or [])
            )
            print(
                f"| {name} | {labels[j.model]} | {pct(j.position_bias)} "
                f"| {pct(first_seat_rate(recs, j.model))} | {pct(j.tie_rate)} "
                f"| {num(statistics.mean(conf)) if conf else 'n/a'} "
                f"| {pct(failed / len(votes) if votes else None)} |"
            )

    print("\nAbstain floor, decision panels (`judge_abstain_below`), recomputed offline:\n")
    print("| Panel | Floor | Decided | Agreement vs ref | Cohen's κ vs ref |")
    print("|---|---|---|---|---|")
    for name, recs in panels:
        comps = comparisons(recs)
        if not any(top_probability(v) is not None for c in comps for v in c.votes):
            continue
        quorum = min(2, len(comps[0].votes)) if comps else 2
        ref_w = [ref[key(r)].majority_verdict for r in recs]
        for floor in (None, *FLOORS):
            winners = [apply_abstain_floor(c, floor, quorum).winner for c in comps]
            both, agree, kappa = agreement(winners, ref_w)
            decided = sum(w != "inconclusive" for w in winners) / len(winners)
            print(
                f"| {name} | {floor or 'off'} | {pct(decided)} | {pct(agree)} ({both}) | {num(kappa)} |"
            )

    print("\nConfidence against the reference verdict (decision judges, decided votes):\n")
    print(
        "| Panel | Judge | "
        + " | ".join(f"{lo:.2f}–{min(hi, 1):.2f}" for lo, hi in CONFIDENCE_BINS)
        + " |"
    )
    print("|---|---|" + "---|" * len(CONFIDENCE_BINS))
    for name, recs in panels:
        models = list(dict.fromkeys(v["model"] for r in recs for v in r.judge_votes))
        labels = judge_labels(models)
        for model in models:
            bins: list[list[bool]] = [[] for _ in CONFIDENCE_BINS]
            for r in recs:
                ref_v = ref[key(r)].majority_verdict
                if ref_v == "inconclusive":
                    continue
                for v in r.judge_votes:
                    p = top_probability(v) if v["model"] == model else None
                    if p is None:
                        continue
                    i = next(i for i, (lo, hi) in enumerate(CONFIDENCE_BINS) if lo <= p < hi)
                    bins[i].append(v["vote"] == ref_v)
            if not any(bins):
                continue
            cells = [f"{pct(sum(b) / len(b))} of {len(b)}" if b else "n/a" for b in bins]
            print(f"| {name} | {labels[model]} | " + " | ".join(cells) + " |")

    if args.sweep:
        sweep(dict(panels)[args.sweep], ref)


def sweep(recs: list[BattleRecord], ref: dict) -> None:
    """Every sub-panel of a big panel, rebuilt offline from the per-judge votes.

    A judge's reconciled vote does not depend on who else sits on the panel, so
    a sub-panel's verdict is the plurality of its members' votes under the same
    quorum rule the run uses (two decisive votes, or one for a lone judge).
    """
    from itertools import combinations

    from evaluatorq.pairwise import pairwise_consensus

    models = list(dict.fromkeys(v["model"] for r in recs for v in r.judge_votes))
    labels = judge_labels(models)
    ref_w = [ref[key(r)].majority_verdict for r in recs]
    print(f"\nPanel size, every sub-panel of {len(models)} decision judges:\n")
    print(
        "| Size | Panels | Decided (median) | κ vs ref: worst / median / best "
        "| Best panel deciding at least 60% (κ, decided) |"
    )
    print("|---|---|---|---|---|")
    singles = []
    top3: list[tuple] = []
    for k in (1, 3, 5, 7):
        if k > len(models):
            continue
        scored = []
        for panel in combinations(models, k):
            winners = []
            for r in recs:
                votes = [v.get("vote") for v in r.judge_votes if v["model"] in panel]
                decisive = [v for v in votes if v is not None]
                winners.append(
                    "inconclusive" if len(decisive) < min(2, k) else pairwise_consensus(decisive)
                )
            _, agree, kappa = agreement(winners, ref_w)
            decided = sum(w != "inconclusive" for w in winners) / len(winners)
            scored.append((kappa if kappa is not None else -1.0, decided, agree, panel))
            if k == 1:
                singles.append((panel[0], decided, agree, kappa))
        scored.sort()
        busy = [s for s in scored if s[1] >= 0.6]
        best = busy[-1] if busy else None
        if k == 3:
            top3 = busy[-5:][::-1]
        print(
            f"| {k} | {len(scored)} | {pct(statistics.median(d for _, d, _, _ in scored))} "
            f"| {num(scored[0][0])} / {num(scored[len(scored) // 2][0])} / {num(scored[-1][0])} "
            + (
                f"| {', '.join(labels[m] for m in best[3])} ({num(best[0])}, {pct(best[1])}) |"
                if best
                else "| none |"
            )
        )
    print("\nBest three-judge panels deciding at least 60% of rounds:\n")
    print("| Panel | κ vs ref | Agreement | Decided |")
    print("|---|---|---|---|")
    for kappa, decided, agree, panel in top3:
        print(
            f"| {', '.join(labels[m] for m in panel)} | {num(kappa)} | {pct(agree)} | {pct(decided)} |"
        )
    print("\nEach decision judge alone:\n")
    print("| Judge | Decided | Agreement vs ref | Cohen's κ vs ref |")
    print("|---|---|---|---|")
    for model, decided, agree, kappa in sorted(singles, key=lambda t: -(t[3] or -1)):
        print(f"| {labels[model]} | {pct(decided)} | {pct(agree)} | {num(kappa)} |")


if __name__ == "__main__":
    main()
