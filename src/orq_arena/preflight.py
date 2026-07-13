"""Pre-run checks: exact call counts, a spend ceiling, a thinking probe.

Counts are exact. The dollar line is a *ceiling*, every output cap fully
hit, priced from the router's own catalog, so it supersedes plan decision
18 ("prices are guesses"): prices are real, only token volumes are bounded
rather than predicted. Live runs land under, never over.
The probe automates the audit that caught kimi-k2.6 burning its whole token
budget on vendor-default thinking: one tiny call per candidate, flag anything
that produces reasoning despite its config.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from itertools import combinations
from typing import Any

from .config import ArenaConfig
from .data.prompts import PromptItem
from .roster import CandidateSpec
from .providers.orq_gateway import OrqGateway

_PROBE_PROMPT = "Reply with the single word: ok"


@dataclass(frozen=True)
class CallCounts:
    matches: int
    rounds_per_match: int
    model_streams: int
    judge_calls: int  # panel × both orderings; replacements add more on failure
    probe_calls: int


def call_counts(cfg: ArenaConfig, prompts: list[PromptItem]) -> CallCounts:
    matches = len(list(combinations(cfg.candidates, 2)))
    rounds = min(cfg.match.max_rounds, len(prompts))
    return CallCounts(
        matches=matches,
        rounds_per_match=rounds,
        model_streams=matches * rounds * 2,
        judge_calls=matches * rounds * len(cfg.judges) * 2,
        probe_calls=len(cfg.candidates) if cfg.preflight.thinking_probe else 0,
    )


_PROBE_MAX_TOKENS = 1000  # headroom for coerced minimum thinking budgets
# Judge input = prompt + both responses + instruction/criteria wrapper.
_JUDGE_WRAPPER_TOKENS = 300


def _est_tokens(text: str) -> int:
    return max(1, len(text) // 4)


@dataclass(frozen=True)
class CostCeiling:
    """Spend bound with every output cap fully hit; math, not prediction."""

    total_usd: float
    models_usd: float
    judges_usd: float
    probe_usd: float
    unpriced: list[str]  # router ids absent from the catalog, excluded


def cost_ceiling(
    cfg: ArenaConfig,
    prompts: list[PromptItem],
    counts: CallCounts,
    prices: dict[str, tuple[float, float]],
) -> CostCeiling:
    """Upper-bound the run's spend from exact counts, config caps, catalog prices.

    The only estimated inputs are prompt tokens (chars/4, taken at the
    longest prompt) and the judge-input term, which assumes both responses
    hit the model output cap. Replacement judges swap in only for a failed
    primary call and price similarly; not modeled.
    """
    prompt_tok = max((_est_tokens(p.text) for p in prompts), default=1)
    rounds = counts.rounds_per_match
    n = len(cfg.candidates)
    unpriced: list[str] = []

    models_usd = 0.0
    max_cap = 0
    for w in cfg.candidates:
        cap = w.max_tokens or cfg.gateway.candidate_max_tokens
        max_cap = max(max_cap, cap)
        if w.model_id not in prices:
            unpriced.append(w.model_id)
            continue
        cin, cout = prices[w.model_id]
        streams = (n - 1) * rounds  # each candidate meets every other once
        models_usd += streams * (cin * prompt_tok + cout * cap) / 1e6

    judge_in_tok = prompt_tok + 2 * max_cap + _JUDGE_WRAPPER_TOKENS
    judges_usd = 0.0
    calls_per_judge = counts.matches * rounds * 2  # both seat orders
    for j in cfg.judges:
        if j not in prices:
            unpriced.append(j)
            continue
        cin, cout = prices[j]
        judges_usd += calls_per_judge * (
            cin * judge_in_tok + cout * cfg.gateway.judge_max_tokens
        ) / 1e6

    probe_usd = 0.0
    if counts.probe_calls:
        probe_prompt_tok = _est_tokens(_PROBE_PROMPT)
        for w in cfg.candidates:
            if w.model_id not in prices:
                continue  # already recorded above
            cin, cout = prices[w.model_id]
            probe_usd += (cin * probe_prompt_tok + cout * _PROBE_MAX_TOKENS) / 1e6

    return CostCeiling(
        total_usd=models_usd + judges_usd + probe_usd,
        models_usd=models_usd,
        judges_usd=judges_usd,
        probe_usd=probe_usd,
        unpriced=sorted(set(unpriced)),
    )


async def _probe_one(gateway: OrqGateway, w: CandidateSpec) -> tuple[str, dict[str, Any]]:
    usage: dict[str, Any] = {}
    think_chunks = 0
    try:
        async for kind, _piece in gateway.stream_completion(
            model=w.model_id,
            prompt=_PROBE_PROMPT,
            max_tokens=_PROBE_MAX_TOKENS,
            extra_body=w.reasoning,
            usage_out=usage,
        ):
            if kind == "think":
                think_chunks += 1
        reasoning_tokens = usage.get("reasoning_tokens", 0)
        # The router under-reports reasoning_tokens on some providers
        # (Anthropic returns 0 while thinking), visible CoT chunks count too.
        thinks = reasoning_tokens > 0 or think_chunks > 0
        return w.name, {
            "model": w.model_id,
            "reasoning_tokens": reasoning_tokens,
            "cot_chunks": think_chunks,
            "thinks": thinks,
            "configured": w.thinking_enabled,
            "error": None,
        }
    except Exception as exc:
        return w.name, {
            "model": w.model_id,
            "reasoning_tokens": 0,
            "cot_chunks": 0,
            "thinks": False,
            "configured": w.thinking_enabled,
            "error": str(exc)[:200],
        }


async def thinking_probe(cfg: ArenaConfig) -> dict[str, dict[str, Any]]:
    """One tiny call per candidate; returns {name: probe result}."""
    gateway = OrqGateway(cfg.gateway)
    results = await asyncio.gather(*(_probe_one(gateway, w) for w in cfg.candidates))
    return dict(results)


def surprises(probe: dict[str, dict[str, Any]]) -> list[str]:
    """Candidates whose observed thinking contradicts their config."""
    return [
        name for name, r in probe.items()
        if r["error"] is None and r["thinks"] and not r["configured"]
    ]


def judge_family_overlaps(judges: list[str], candidates: list[CandidateSpec]) -> list[str]:
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

    candidate_fams = {fam(c.model_id) for c in candidates}
    return [j for j in judges if fam(j) in candidate_fams]
