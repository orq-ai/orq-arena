"""Human-anchor annotation: blinded static page + vote merge.

``annotate`` renders battles.jsonl into one self-contained HTML page a
rater opens from file://, reads both responses blind (no model names, no
jury votes, seeded side order, decision 29), and votes with a/b/t/space;
votes export as votes.json. ``anchor`` merges vote files back against the
log and reports human-vs-panel Cohen's kappa and Bradley-Terry rank
correlation (decision 28, pulled forward from PR 11.4).
"""

from __future__ import annotations

import hashlib
import random

from .data.schemas import BattleRecord


def record_key(rec: BattleRecord) -> str:
    """One-way 16-hex key; recomputable from the log, opaque in the page."""
    raw = f"{rec.prompt_hash}:{rec.model_a}:{rec.model_b}:{rec.match_id}:{rec.round_number}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def annotation_items(
    records: list[BattleRecord], *, seed: int = 42, sample: int | None = None
) -> list[dict]:
    """Blinded page payload: canonical responses + per-round display flip."""
    items = []
    for rec in records:
        key = record_key(rec)
        items.append({
            "k": key,
            "q": rec.prompt_text,
            "a": rec.response_a,
            "b": rec.response_b,
            "f": random.Random(f"{seed}:{key}").random() < 0.5,
        })
    random.Random(seed).shuffle(items)
    return items[:sample] if sample else items
