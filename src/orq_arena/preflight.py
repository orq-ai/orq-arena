"""Pre-run checks: exact call counts and a per-warrior thinking probe.

No dollar figures, counts are exact, prices are guesses (plan decision 18).
The probe automates the audit that caught kimi-k2.6 burning its whole token
budget on vendor-default thinking: one tiny call per warrior, flag anything
that produces reasoning despite its config.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from itertools import combinations
from typing import Any

from .config import ArenaConfig
from .data.prompts import PromptItem
from .orcs.roster import WarriorSpec
from .providers.orq_gateway import OrqGateway

_PROBE_PROMPT = "Reply with the single word: ok"


@dataclass(frozen=True)
class CallCounts:
    matches: int
    rounds_per_match: int
    warrior_streams: int
    judge_calls: int  # panel × both orderings; replacements add more on failure
    probe_calls: int


def call_counts(cfg: ArenaConfig, prompts: list[PromptItem]) -> CallCounts:
    matches = len(list(combinations(cfg.warriors, 2)))
    rounds = min(cfg.match.max_rounds, len(prompts))
    return CallCounts(
        matches=matches,
        rounds_per_match=rounds,
        warrior_streams=matches * rounds * 2,
        judge_calls=matches * rounds * len(cfg.judges) * 2,
        probe_calls=len(cfg.warriors) if cfg.preflight.thinking_probe else 0,
    )


async def _probe_one(gateway: OrqGateway, w: WarriorSpec) -> tuple[str, dict[str, Any]]:
    usage: dict[str, Any] = {}
    think_chunks = 0
    try:
        async for kind, _piece in gateway.stream_completion(
            model=w.model_id,
            prompt=_PROBE_PROMPT,
            max_tokens=1000,  # headroom for coerced minimum thinking budgets
            extra_body=w.reasoning,
            usage_out=usage,
        ):
            if kind == "think":
                think_chunks += 1
        reasoning_tokens = usage.get("reasoning_tokens", 0)
        # The router under-reports reasoning_tokens on some providers
        # (Anthropic returns 0 while thinking), visible CoT chunks count too.
        thinks = reasoning_tokens > 0 or think_chunks > 0
        return w.orc_name, {
            "model": w.model_id,
            "reasoning_tokens": reasoning_tokens,
            "cot_chunks": think_chunks,
            "thinks": thinks,
            "configured": w.thinking_enabled,
            "error": None,
        }
    except Exception as exc:
        return w.orc_name, {
            "model": w.model_id,
            "reasoning_tokens": 0,
            "cot_chunks": 0,
            "thinks": False,
            "configured": w.thinking_enabled,
            "error": str(exc)[:200],
        }


async def thinking_probe(cfg: ArenaConfig) -> dict[str, dict[str, Any]]:
    """One tiny call per warrior; returns {orc_name: probe result}."""
    gateway = OrqGateway(cfg.gateway)
    results = await asyncio.gather(*(_probe_one(gateway, w) for w in cfg.warriors))
    return dict(results)


def surprises(probe: dict[str, dict[str, Any]]) -> list[str]:
    """Warriors whose observed thinking contradicts their config."""
    return [
        name for name, r in probe.items()
        if r["error"] is None and r["thinks"] and not r["configured"]
    ]


def judge_family_overlaps(judges: list[str], warriors: list[WarriorSpec]) -> list[str]:
    """Judges sharing a provider family with a contestant.

    Self-preference bias rides on stylistic self-recognition (Panickssery et
    al., NeurIPS 2024): a judge favors its own family's prose, and neither
    blinding nor seat-swapping corrects it. Exact self-judging is already
    excluded per match; this flags the family-level residue so the ranking
    ships with a warning instead of a hidden thumb on the scale.
    """
    # ponytail: provider prefix as family proxy; per-provider lineage tables
    # if one provider ever hosts unrelated model families
    def fam(model_id: str) -> str:
        return model_id.split("/", 1)[0].lower()

    warrior_fams = {fam(w.model_id) for w in warriors}
    return [j for j in judges if fam(j) in warrior_fams]
