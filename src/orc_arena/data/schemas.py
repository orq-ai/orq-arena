"""Battle record — superset of orq-battlebench BattleRecord.

Keeping the core fields byte-identical means orc-arena's battle log plugs
straight into the orq-battlebench matrix-factorization training pipeline.
Additive fields (hp_*, match_id, tournament_id, damage_dealt) are orc-arena
specific and ignored by the router trainer.
"""

from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel, Field

from ..judges.schemas import JudgeResult


class BattleRecord(BaseModel):
    """A single prompt-turn battle record (orq-battlebench compatible)."""

    # --- orq-battlebench compatible core ---
    prompt_hash: str
    prompt_text: str
    prompt_category: str = ""
    prompt_length_bucket: str = ""

    model_a: str = Field(description="Normalized name of model A (short_model).")
    model_b: str = Field(description="Normalized name of model B.")
    response_a: str = ""
    response_b: str = ""

    judge_verdicts: list[JudgeResult] = Field(default_factory=list)
    majority_verdict: Literal["A", "B", "TIE", "DISCARD"] = "DISCARD"
    winner: str = ""

    tokens_a_in: int = 0
    tokens_a_out: int = 0
    tokens_b_in: int = 0
    tokens_b_out: int = 0

    generation_type: Literal["augmentation", "new"] = "new"
    timestamp: float = Field(default_factory=time.time)

    # --- orc-arena extensions (ignored by trainer) ---
    tournament_id: str = ""
    match_id: str = ""
    round_number: int = 0
    damage_dealt: int = 0
    hp_a_before: int = 0
    hp_b_before: int = 0
    hp_a_after: int = 0
    hp_b_after: int = 0
