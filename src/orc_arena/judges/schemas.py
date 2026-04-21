"""Judge verdict schema + spec.

Lifted from orq-battlebench (schemas.py::JudgeVerdict, JudgeResult) with the
panel/majority fields tailored for orc-arena.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class JudgeSpec(BaseModel):
    """A judge model routed via orq.ai."""

    name: str
    model_id: str


class JudgeVerdict(BaseModel):
    """Structured output from a single judge call.

    ``reasoning`` comes first so the model 'thinks' before committing to a
    verdict — improves judgement quality with instructor structured output.
    """

    reasoning: str = Field(
        description=(
            "Brief explanation (2-3 sentences) of why one response is better, "
            "citing specific differences in accuracy, helpfulness, clarity, or relevance."
        )
    )
    verdict: Literal["A", "B", "TIE"] = Field(
        description="A if Response A is better, B if Response B is better, TIE if equally good."
    )


class JudgeResult(BaseModel):
    """A single judge's verdict after A/B un-swapping."""

    judge_name: str
    judge_model: str
    verdict: Literal["A", "B", "TIE"]
    reasoning: str = ""
    label_swapped: bool = False
    raw_verdict: Literal["A", "B", "TIE"] = "TIE"
