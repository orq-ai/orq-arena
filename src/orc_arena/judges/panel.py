"""3-judge panel orchestration: label swap, majority vote, self-judge exclusion.

All judge calls go through the orq.ai gateway via ``instructor.from_openai``
so we get structured ``JudgeVerdict`` output without parsing free text.
"""

from __future__ import annotations

import asyncio
import random
from collections import Counter
from typing import Literal

import instructor

from ..providers.orq_gateway import OrqGateway
from .prompts import build_judge_prompt
from .schemas import JudgeResult, JudgeSpec, JudgeVerdict

Verdict = Literal["A", "B", "TIE", "DISCARD"]


def _flip(v: str) -> str:
    if v == "A":
        return "B"
    if v == "B":
        return "A"
    return "TIE"


async def _call_judge(
    *,
    gateway: OrqGateway,
    judge: JudgeSpec,
    user_query: str,
    response_a: str,
    response_b: str,
    system_prompt: str,
    max_tokens: int,
    rng: random.Random,
) -> JudgeResult | None:
    """Run a single judge with 50/50 label swap. Returns None on error."""
    swap = rng.random() < 0.5
    prompt = (
        build_judge_prompt(user_query, response_b, response_a)
        if swap
        else build_judge_prompt(user_query, response_a, response_b)
    )

    client = instructor.from_openai(gateway.client)
    try:
        verdict_obj = await client.chat.completions.create(
            model=judge.model_id,
            response_model=JudgeVerdict,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            max_tokens=max_tokens,
            max_retries=2,
        )
    except Exception:
        return None

    raw = verdict_obj.verdict
    final = _flip(raw) if swap else raw

    return JudgeResult(
        judge_name=judge.name,
        judge_model=judge.model_id,
        verdict=final,
        reasoning=verdict_obj.reasoning,
        label_swapped=swap,
        raw_verdict=raw,
    )


async def run_panel(
    *,
    gateway: OrqGateway,
    judges: list[JudgeSpec],
    user_query: str,
    response_a: str,
    response_b: str,
    system_prompt: str,
    max_tokens: int,
    seed: int | None = None,
) -> list[JudgeResult]:
    """Run every judge concurrently; drop failures."""
    rng = random.Random(seed)
    tasks = [
        _call_judge(
            gateway=gateway,
            judge=j,
            user_query=user_query,
            response_a=response_a,
            response_b=response_b,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            rng=rng,
        )
        for j in judges
    ]
    raw = await asyncio.gather(*tasks)
    return [r for r in raw if r is not None]


def filter_self_judges(
    verdicts: list[JudgeResult], contestant_model_ids: set[str]
) -> list[JudgeResult]:
    """Drop any verdict where the judge model matches a contestant model."""
    return [v for v in verdicts if v.judge_model not in contestant_model_ids]


def majority_vote(verdicts: list[JudgeResult]) -> Verdict:
    """2-of-3 majority. DISCARD if nothing has a plurality (e.g., all TIE is TIE)."""
    if not verdicts:
        return "DISCARD"
    counts = Counter(v.verdict for v in verdicts)
    top, top_n = counts.most_common(1)[0]
    # Require a strict plurality (count > half)
    if top_n * 2 > len(verdicts):
        return top  # type: ignore[return-value]
    # Tie between A and B with no majority → treat as TIE
    if counts.get("A", 0) == counts.get("B", 0) and top != "TIE":
        return "TIE"
    return "DISCARD"
