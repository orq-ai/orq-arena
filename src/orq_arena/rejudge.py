"""Re-judge a recorded run with a different panel, zero regeneration.

Reads ``battles.jsonl`` (schema v2), runs every recorded A/B pair through a
fresh evaluatorq pairwise jury, and compares the resulting Bradley-Terry
ranking against the recorded one. The whole point of keeping the responses:
swapping the jury costs judge tokens only.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from evaluatorq import PairwiseComparison, build_report, llm_jury_pairwise

from .config import ArenaConfig
from .data.schemas import BattleRecord
from .providers.orq_gateway import OrqGateway
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


def panel_excluding_contestants(
    judges: list[str], contestant_shorts: frozenset[str], short_to_full: dict[str, str]
) -> list[str]:
    """Judges that aren't a contestant, matched the way the live run matches.

    Records carry short names; the live run (battle.py) excludes a judge by
    full ``model_id``. Resolve each contestant short name to its full id and
    compare there. A contestant missing from the config can't be resolved to a
    provider, so fall back to a short-name match to keep exclusion safe.
    """
    contestants_full = {short_to_full.get(m, m) for m in contestant_shorts}
    unresolved_short = {m for m in contestant_shorts if m not in short_to_full}

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
    manifest_path = Path(log_path).with_suffix(".run.json")
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
        key = frozenset((rec.model_a, rec.model_b))  # short contestant names
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

    pairs = [(r.model_a, r.model_b) for r in records]
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


def render_result(result: dict) -> None:
    from rich.console import Console
    from rich.table import Table

    console = Console()
    report = result["report"]
    console.print(
        f"\n[bold]re-judged {result['total']} rounds[/bold], "
        f"{result['changed_verdicts']} verdicts changed"
    )
    console.print(
        f"rank correlation (Spearman) old→new: [bold]{result['spearman']:.2f}[/bold]"
        + (
            " , judge-robust ranking"
            if result["spearman"] >= 0.8
            else " , ranking is panel-sensitive; treat with care"
        )
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
    payload = {
        "total": result["total"],
        "changed_verdicts": result["changed_verdicts"],
        "spearman": result["spearman"],
        "old_ranking": result["old_ranking"],
        "new_ranking": result["new_ranking"],
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
        sp = "n/a" if r["spearman"] is None else f"{r['spearman']:.2f}"
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
