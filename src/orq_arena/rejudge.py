"""Re-judge a recorded run with a different panel, zero regeneration.

Reads ``battles.jsonl`` (schema v2), runs every recorded A/B pair through a
fresh evaluatorq pairwise jury, and compares the resulting Bradley-Terry
ranking against the recorded one. The whole point of keeping the responses:
swapping the jury costs judge tokens only.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from pathlib import Path

from evaluatorq import PairwiseComparison, build_report, llm_jury_pairwise

from .config import ArenaConfig
from .data.schemas import BattleRecord
from .providers.orq_gateway import OrqGateway
from .tournament.driver import manifest_path_for, record_names
from .tournament.elo import bradley_terry_mle, build_wins_matrix

Outcome = tuple[str, str, str]


def load_records(path: str | Path) -> list[BattleRecord]:
    records: list[BattleRecord] = []
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(BattleRecord.model_validate_json(line))
    return [r for r in records if r.error is None and r.response_a and r.response_b]


def outcomes_from_majorities(pairs: list[tuple[str, str]], majorities: list[str]) -> list[Outcome]:
    out: list[Outcome] = []
    for (model_a, model_b), majority in zip(pairs, majorities, strict=True):
        if majority == "A":
            out.append((model_a, model_b, "winner"))
        elif majority == "B":
            out.append((model_b, model_a, "winner"))
        elif majority == "tie":
            out.append((model_a, model_b, "tie"))
    return out


def spearman(rank_a: list[str], rank_b: list[str]) -> float:
    """Spearman rank correlation between two orderings of the same names."""
    n = len(rank_a)
    if n < 2 or set(rank_a) != set(rank_b):
        return float("nan")
    pos_b = {name: i for i, name in enumerate(rank_b)}
    d2 = sum((i - pos_b[name]) ** 2 for i, name in enumerate(rank_a))
    return 1 - (6 * d2) / (n * (n**2 - 1))


def contestant_key(rec: BattleRecord) -> frozenset[str]:
    """The pair a comparator is built for, one entry per contestant.

    Full ids where the record has them: a colliding short-name pair collapses
    to a one-element set, which drops a contestant from the self-judge
    exclusion and lets it judge itself.
    """
    return frozenset((rec.model_a_id or rec.model_a, rec.model_b_id or rec.model_b))


def panel_excluding_contestants(
    judges: list[str], contestants: frozenset[str], short_to_full: dict[str, str]
) -> list[str]:
    """Judges that aren't a contestant, matched the way the live run matches.

    The live run (battle.py) excludes a judge by full ``model_id``. v4 records
    carry full ids, which compare directly; v3 records carry only short names,
    which are resolved through the run's own pool. A contestant that resolves
    to neither falls back to a short-name match, so exclusion stays safe rather
    than silently letting a contestant judge itself.
    """
    contestants_full = {short_to_full.get(m, m) for m in contestants}
    unresolved_short = {m for m in contestants if m not in short_to_full}

    def is_contestant(j: str) -> bool:
        # Same short-name convention as candidates.short_model: strip the first
        # segment only, so multi-segment ids keep their tail intact.
        return j in contestants_full or j.split("/", 1)[-1] in unresolved_short

    return [j for j in judges if not is_contestant(j)]


def short_map_from_manifest(log_path: str | Path) -> dict[str, str] | None:
    """{short_model: model_id} from the run's own manifest, if it exists.

    The manifest records the exact candidate pool the run used, so self-judge
    exclusion stays correct even after the YAML candidates drift. Returns None
    when the manifest (or its candidates map) is missing or unreadable.
    """
    manifest_path = manifest_path_for(log_path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    candidates = manifest.get("candidates") or {}
    mapping = {}
    for spec in candidates.values():
        mid = (spec or {}).get("model") or ""
        if mid:
            mapping[mid.split("/", 1)[-1]] = mid
    return mapping or None


def _ranking(outcomes: list[Outcome], models: list[str]) -> list[str]:
    if not outcomes:
        return sorted(models)
    elo = bradley_terry_mle(build_wins_matrix(outcomes), models)
    return sorted(models, key=lambda m: elo[m], reverse=True)


async def rejudge_run(
    *,
    cfg: ArenaConfig,
    records: list[BattleRecord],
    judges: list[str],
    criteria: str | None = None,
    concurrency: int = 4,
    short_to_full: dict[str, str] | None = None,
) -> dict:
    """Re-score every record; return comparisons, report, and ranking delta."""
    gateway = OrqGateway(cfg.gateway)
    sem = asyncio.Semaphore(max(1, concurrency))

    # Records carry short names; resolve to full model ids so self-judge
    # exclusion matches the live run (battle.py excludes by model_id).
    # Prefer the run's own manifest pool (passed in by the CLI); the live
    # YAML is only a fallback and may have drifted since the run.
    if short_to_full is None:
        short_to_full = {c.short_model: c.model_id for c in cfg.candidates}

    # One comparator per contestant pair.
    comparators: dict[frozenset[str], object] = {}

    def comparator_for(rec: BattleRecord):
        key = contestant_key(rec)
        if key not in comparators:
            panel = panel_excluding_contestants(judges, key, short_to_full)
            if not panel:
                raise ValueError(f"every judge is a contestant in {sorted(key)}")
            comparators[key] = llm_jury_pairwise(
                judges=panel,
                criteria=criteria or cfg.criteria,
                replacement_judges=panel_excluding_contestants(
                    list(cfg.replacement_judges), key, short_to_full
                )
                or None,
                # A 1-judge rejudge panel is legitimate; don't let the run
                # config's quorum (sized for its own panel) reject it.
                min_successful_judges=min(cfg.min_successful_judges, len(panel)),
                max_tokens=cfg.gateway.judge_max_tokens,
                timeout_ms=cfg.gateway.judge_timeout_ms,
                client=gateway.client,
            )
        return comparators[key]

    async def score(rec: BattleRecord) -> PairwiseComparison:
        async with sem:
            return await comparator_for(rec).compare(  # type: ignore[attr-defined]
                question=rec.prompt_text,
                response_a=rec.response_a,
                response_b=rec.response_b,
            )

    comparisons = await asyncio.gather(*(score(r) for r in records))

    # Rank on the same key every other view uses: the full router id where the
    # record carries one, rendered as the display name the report would show.
    # Ranking on short names merged a colliding pool (one model via two
    # providers) into a single entry, and the Spearman compared rankings over a
    # field one model short: RES-1149 fixed the comparator key and missed this
    # sibling (RES-1152). Display names, not raw ids, so a non-colliding pool
    # prints exactly what it always printed; a colliding one shows full ids,
    # the same fallback the leaderboard uses.
    alias = record_names(records, cfg.candidates)
    pairs = [(alias[r.rating_key("a")], alias[r.rating_key("b")]) for r in records]
    models = sorted({m for p in pairs for m in p})
    old_outcomes = outcomes_from_majorities(pairs, [r.majority_verdict for r in records])
    new_outcomes = outcomes_from_majorities(pairs, [c.winner for c in comparisons])
    old_rank = _ranking(old_outcomes, models)
    new_rank = _ranking(new_outcomes, models)

    changed = sum(
        1 for rec, c in zip(records, comparisons, strict=True) if rec.majority_verdict != c.winner
    )
    return {
        "comparisons": comparisons,
        "report": build_report(comparisons),
        "old_ranking": old_rank,
        "new_ranking": new_rank,
        "spearman": spearman(old_rank, new_rank),
        "changed_verdicts": changed,
        "decisive": decisive_count(comparisons),
        "total": len(records),
    }


def write_rejudged(
    path: str | Path, records: list[BattleRecord], comparisons: list[PairwiseComparison]
) -> None:
    with Path(path).open("w", encoding="utf-8") as fh:
        for rec, c in zip(records, comparisons, strict=True):
            row = rec.model_copy(
                update={
                    "judge_votes": [v.model_dump() for v in c.votes],
                    "majority_verdict": c.winner,
                    "winner": (
                        rec.model_a
                        if c.winner == "A"
                        else rec.model_b
                        if c.winner == "B"
                        else c.winner
                    ),
                }
            )
            fh.write(row.model_dump_json() + "\n")


# The verdict word needs a field the statistic can express itself on. Spearman
# over n models takes finitely many values: at 4 models the only ones clearing
# 0.8 are 0.8 and 1.0 (a single adjacent swap is the whole distance between
# "judge-robust" and "panel-sensitive"), and at 3 the grade could only ever
# fire on a perfect match. Below this floor the number prints with its n and
# no verdict word attaches (RES-1153).
MIN_VERDICT_MODELS = 5


def spearman_verdict(rho: float, n_models: int) -> str:
    """The grade a rejudge Spearman has earned, or why it gets none."""
    if n_models < MIN_VERDICT_MODELS:
        return f"too few models ({n_models}) for a robustness verdict"
    if rho >= 0.8:
        return "judge-robust ranking"
    return "ranking is panel-sensitive; treat with care"


def decisive_count(comparisons: Sequence[PairwiseComparison]) -> int:
    """Comparisons that expressed a preference, ties included.

    'inconclusive' is evaluatorq's word for a panel that never reached quorum:
    the judges errored, abstained, or contradicted themselves across the seat
    orders. A tie is a decision; inconclusive is the absence of one.
    """
    return sum(1 for c in comparisons if c.winner != "inconclusive")


def render_result(result: dict) -> None:
    from rich.console import Console
    from rich.table import Table

    console = Console()
    report = result["report"]
    total = result["total"]
    # Read, not defaulted. A `.get(..., total)` here meant that dropping the key
    # upstream restored the whole bug in silence, because "missing" resolved to
    # "every round decided", which is the one answer that prints a ranking.
    decisive = result["decisive"]
    console.print(
        f"\n[bold]re-judged {total} rounds[/bold], {result['changed_verdicts']} verdicts changed"
    )

    # No decision anywhere means there is no ranking to show and nothing to
    # correlate. Printing them would dress a dead panel (bad credential, every
    # judge erroring, quorum never met) as a result.
    if not decisive:
        console.print(
            f"[bold red]the jury produced no usable verdict in any of {total} "
            "rounds[/bold red]: no ranking and no rank correlation follow from this run"
        )
        console.print("check the panel is reachable and the credential is valid, then re-run")
        return

    n_models = len(result["old_ranking"])
    # A clean run reads the way it always did (RES-1153). A partial collapse
    # says so inline, because the correlation was fit on the decided subset and
    # the reader would otherwise price it against the full round count.
    rounds = f"{total} rounds" if decisive == total else f"{decisive} of {total} rounds decided"
    console.print(
        f"rank correlation (Spearman) old→new: [bold]{result['spearman']:.2f}[/bold] "
        f"over {n_models} models, {rounds}, " + spearman_verdict(result["spearman"], n_models)
    )
    console.print(f"old ranking: {' > '.join(result['old_ranking'])}")
    console.print(f"new ranking: {' > '.join(result['new_ranking'])}")

    t = Table(title="new jury behaviour")
    for col in ("judge", "A-lean", "B-lean", "flip rate", "tie rate"):
        t.add_column(col)
    for j in report.per_judge:
        t.add_row(
            j.model.split("/")[-1],
            "–" if j.a_rate is None else f"{j.a_rate:.0%}",
            "–" if j.b_rate is None else f"{j.b_rate:.0%}",
            f"{j.position_bias:.0%}",
            f"{j.tie_rate:.0%}",
        )
    console.print(t)
    if report.mean_agreement is not None:
        console.print(f"mean inter-judge agreement: {report.mean_agreement:.0%}")


def save_report_json(path: str | Path, result: dict) -> None:
    """The saved report says the same thing the terminal said.

    `render_result` refuses to print a ranking for a jury that decided nothing,
    but the file kept both the ranking and the correlation, and `--compare` then
    tabulated that Spearman as a panel's robustness score. The ranking is an
    artifact of `_ranking` falling through to `sorted(models)` with no decisive
    outcome to fit, so it is written as null rather than as a result. `decisive`
    goes in the payload too: the collapse has to survive the round trip.
    """
    decisive = result["decisive"]
    payload = {
        "total": result["total"],
        "decisive": decisive,
        "changed_verdicts": result["changed_verdicts"],
        "spearman": result["spearman"] if decisive else None,
        "old_ranking": result["old_ranking"],
        "new_ranking": result["new_ranking"] if decisive else None,
        "jury": result["report"].model_dump(),
    }
    Path(path).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def compare_reports(paths: list[str | Path]) -> list[dict]:
    """Rows for the jury-selection table, one per saved rejudge report JSON."""
    rows: list[dict] = []
    for path in paths:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        jury = data.get("jury") or {}
        per_judge = jury.get("per_judge") or []
        panel = ", ".join(str(j.get("model", "?")).split("/")[-1] for j in per_judge)
        worst = max(per_judge, key=lambda j: j.get("position_bias") or 0.0, default=None)
        rows.append(
            {
                "file": str(path),
                "panel": panel or "?",
                "inconclusive": jury.get("inconclusive_rate"),
                "agreement": jury.get("mean_agreement"),
                "spearman": data.get("spearman"),
                # n behind the correlation; every saved report carries the
                # ranking, so old JSONs yield it too
                "models": len(data.get("old_ranking") or []) or None,
                "changed": data.get("changed_verdicts"),
                "total": data.get("total"),
                "tie_rate": jury.get("tie_rate"),
                "worst_flip": None if worst is None else worst.get("position_bias"),
                "worst_flip_judge": (
                    "" if worst is None else str(worst.get("model", "")).split("/")[-1]
                ),
            }
        )
    return rows


def render_comparison(rows: list[dict]) -> None:
    from rich.console import Console
    from rich.table import Table

    def pct(x):
        return "n/a" if x is None else f"{x:.0%}"

    t = Table(title="jury candidates over the same recorded log")
    for col in (
        "panel",
        "spearman vs run",
        "inconclusive",
        "agreement",
        "worst flip (judge)",
        "tie rate",
        "changed verdicts",
    ):
        t.add_column(col)
    for r in rows:
        # The same rule as the rejudge line itself: a correlation never
        # prints without the n it was computed over.
        if r["spearman"] is None:
            sp = "n/a"
        elif r.get("models"):
            sp = f"{r['spearman']:.2f} over {r['models']}"
        else:
            sp = f"{r['spearman']:.2f} (n unknown)"
        t.add_row(
            r["panel"],
            sp,
            pct(r["inconclusive"]),
            pct(r["agreement"]),
            f"{pct(r['worst_flip'])} ({r['worst_flip_judge']})"
            if r["worst_flip"] is not None
            else "n/a",
            pct(r["tie_rate"]),
            f"{r['changed']}/{r['total']}" if r["changed"] is not None else "n/a",
        )
    Console().print(t)
    Console().print(
        "read: high spearman = the ranking does not depend on this jury; low inconclusive = "
        "decisive; low flip = self-consistent. These measure reliability, not accuracy; "
        "accuracy needs gold pairs or a human anchor."
    )
