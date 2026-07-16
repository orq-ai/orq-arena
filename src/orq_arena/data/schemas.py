"""Battle record, schema v3, one JSONL row per judged (or voided) round.

v2 replaced the hand-rolled judge schema with evaluatorq's reconciled
``PairwiseVote`` dumps. v3 drops the arena HP bookkeeping (damage/hp fields):
HP was never scored, it's a TUI-only presentation the show now derives from
the judged verdicts. Old v2 logs still load (the dropped fields are ignored).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class BattleRecord(BaseModel):
    """A single prompt-turn battle record."""

    schema_version: int = 3

    prompt_hash: str
    prompt_text: str
    prompt_category: str = ""

    model_a: str = Field(description="Normalized name of model A (short_model).")
    model_b: str = Field(description="Normalized name of model B.")
    response_a: str = ""
    response_b: str = ""

    # evaluatorq PairwiseVote dumps: model, vote, flipped, completed,
    # replacement, explanation.
    judge_votes: list[dict[str, Any]] = Field(default_factory=list)
    majority_verdict: str = "inconclusive"  # 'A' | 'B' | 'tie' | 'inconclusive'
    winner: str = ""  # short_model | 'tie' | 'inconclusive' | 'void'

    tokens_a_in: int = 0
    tokens_a_out: int = 0
    tokens_a_reasoning: int = 0
    tokens_b_in: int = 0
    tokens_b_out: int = 0
    tokens_b_reasoning: int = 0
    finish_reason_a: str = ""
    finish_reason_b: str = ""
    ttft_a_ms: int = 0
    duration_a_ms: int = 0
    ttft_b_ms: int = 0
    duration_b_ms: int = 0
    judge_tokens_in: int = 0
    judge_tokens_out: int = 0

    # Set when the round was voided (stream failure after retry), such a
    # round is never judged and never scored.
    error: str | None = None

    timestamp: float = Field(default_factory=time.time)

    # --- arena bookkeeping ---
    tournament_id: str = ""
    match_id: str = ""
    round_number: int = 0


def load_records(log_path: str | Path) -> list[BattleRecord]:
    """Every record in a battle log, voided rounds included (unlike
    rejudge's judgeable-only loader). Missing file -> empty list."""
    records: list[BattleRecord] = []
    p = Path(log_path)
    if not p.exists():
        return records
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(BattleRecord.model_validate_json(line))
    return records
