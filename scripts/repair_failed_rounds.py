"""Split a rejudged log into the rounds where some judge call failed, and splice repairs back.

A judge call that fails for an infrastructure reason (a 429 burst, a timeout)
leaves a vote with no verdict in either seat order. Those rounds say nothing
about the judge, so the study re-judges just them with the same panel and
splices the result back, keyed on (match_id, round_number, prompt_hash).

    uv run python scripts/repair_failed_rounds.py split LOG.jsonl FAILED.jsonl
    uv run python scripts/repair_failed_rounds.py splice LOG.jsonl REPAIRED.jsonl OUT.jsonl
"""

from __future__ import annotations

import sys

from orq_arena.data.schemas import load_records


def failed(vote: dict) -> bool:
    return (
        vote.get("vote") is None
        and not vote.get("flipped")
        and not any(o.get("verdict") for o in vote.get("observations") or [])
    )


def key(r) -> tuple:
    return (r.match_id, r.round_number, r.prompt_hash)


if __name__ == "__main__":
    cmd, *paths = sys.argv[1:]
    if cmd == "split":
        src, dst = paths
        bad = [r for r in load_records(src) if any(failed(v) for v in r.judge_votes)]
        with open(dst, "w", encoding="utf-8") as fh:
            fh.writelines(r.model_dump_json() + "\n" for r in bad)
        print(f"{len(bad)} rounds with a failed judge call -> {dst}")
    else:
        src, fix, dst = paths
        fixed = {key(r): r for r in load_records(fix)}
        rows = [fixed.get(key(r), r) for r in load_records(src)]
        with open(dst, "w", encoding="utf-8") as fh:
            fh.writelines(r.model_dump_json() + "\n" for r in rows)
        print(f"spliced {len(fixed)} repaired rounds into {len(rows)} -> {dst}")
