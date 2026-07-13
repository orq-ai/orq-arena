"""Battle record, schema v2, one JSONL row per judged (or voided) round.

v2 replaces the hand-rolled judge schema with evaluatorq's reconciled
``PairwiseVote`` dumps and drops orq-battlebench byte-compat (the token
fields it promised were never real; these are).
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field


class BattleRecord(BaseModel):
    """A single prompt-turn battle record."""

    schema_version: int = 2

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
    damage_dealt: int = 0
    hp_a_before: int = 0
    hp_b_before: int = 0
    hp_a_after: int = 0
    hp_b_after: int = 0
