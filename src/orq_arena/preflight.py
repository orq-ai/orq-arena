"""Pre-run checks: exact call counts, a spend projection, a thinking probe.

Counts are exact. The dollar figures are not a guarantee, and the code no
longer pretends otherwise: prices come from the router's own catalog and every
output cap is assumed fully hit, but prompt tokens are estimated from character
count, which under-counts CJK, code and dense punctuation. Two figures come
out, because one number cannot honestly answer both questions a user has:
``projected_usd`` is what a clean run costs, and ``worst_case_usd`` adds the
retry every stream may take and the replacement panel every judge may need.
The probe automates the audit that caught kimi-k2.6 burning its whole token
budget on vendor-default thinking: one tiny call per candidate, flag anything
that produces reasoning despite its config.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from itertools import combinations
from typing import Any

from .candidates import CandidateSpec
from .config import ArenaConfig
from .data.prompts import PromptItem
from .providers.models_list import ModelEntry
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
class CostRow:
    """One line of the run-plan cost table; usd=None means unpriced, not $0."""

    role: str  # "candidate" | "judge" | "replacement" | "probe"
    model_id: str
    calls: int  # streams for candidates, judge calls for judges, probes for probe
    price_in: float | None  # $/M input tokens; None when absent from the catalog
    price_out: float | None
    usd: float | None


@dataclass(frozen=True)
class CostProjection:
    """What a run costs, with every output cap assumed fully hit.

    Two figures, because a single one would have to lie about something.
    ``projected_usd`` prices the calls a clean run makes. ``worst_case_usd``
    adds the failure paths that spend real money without appearing in any call
    count: the one retry each stream takes, and a replacement panel for every
    judge call, when replacements are configured. Neither is a hard bound,
    since prompt tokens are estimated from characters; see the module docstring.
    """

    projected_usd: float
    worst_case_usd: float
    models_usd: float
    judges_usd: float
    probe_usd: float
    unpriced: list[str]  # router ids absent from the catalog, excluded
    rows: tuple[CostRow, ...] = ()


def cost_projection(
    cfg: ArenaConfig,
    prompts: list[PromptItem],
    counts: CallCounts,
    prices: dict[str, tuple[float, float]],
) -> CostProjection:
    """Price the run from exact call counts, config caps and catalog prices.

    Estimated inputs: prompt tokens (chars/4, taken at the longest prompt) and
    the judge-input term, which assumes both responses hit the model output
    cap. Retries and replacement judges never appear in a call count, so they
    are priced into ``worst_case_usd`` rather than left for the user to discover
    on the invoice.
    """
    prompt_tok = max((_est_tokens(p.text) for p in prompts), default=1)
    rounds = counts.rounds_per_match
    n = len(cfg.candidates)
    unpriced: list[str] = []
    rows: list[CostRow] = []

    models_usd = 0.0
    max_cap = 0
    for w in cfg.candidates:
        cap = w.max_tokens or cfg.gateway.candidate_max_tokens
        max_cap = max(max_cap, cap)
        streams = (n - 1) * rounds  # each candidate meets every other once
        if w.model_id not in prices:
            unpriced.append(w.model_id)
            rows.append(CostRow("candidate", w.model_id, streams, None, None, None))
            continue
        cin, cout = prices[w.model_id]
        usd = streams * (cin * prompt_tok + cout * cap) / 1e6
        models_usd += usd
        rows.append(CostRow("candidate", w.model_id, streams, cin, cout, usd))

    judge_in_tok = prompt_tok + 2 * max_cap + _JUDGE_WRAPPER_TOKENS
    judges_usd = 0.0
    calls_per_judge = counts.matches * rounds * 2  # both seat orders
    for j in cfg.judges:
        if j not in prices:
            unpriced.append(j)
            rows.append(CostRow("judge", j, calls_per_judge, None, None, None))
            continue
        cin, cout = prices[j]
        usd = calls_per_judge * (cin * judge_in_tok + cout * cfg.gateway.judge_max_tokens) / 1e6
        judges_usd += usd
        rows.append(CostRow("judge", j, calls_per_judge, cin, cout, usd))

    probe_usd = 0.0
    if counts.probe_calls:
        probe_prompt_tok = _est_tokens(_PROBE_PROMPT)
        for w in cfg.candidates:
            if w.model_id not in prices:
                continue  # already recorded above
            cin, cout = prices[w.model_id]
            probe_usd += (cin * probe_prompt_tok + cout * _PROBE_MAX_TOKENS) / 1e6
        rows.append(CostRow("probe", "thinking probe", counts.probe_calls, None, None, probe_usd))

    # Stand-ins are priced at their own worst rate, not the primary panel's: a
    # cheap panel backed by an expensive replacement would otherwise slip past
    # the figure entirely.
    replacement_usd = 0.0
    if cfg.replacement_judges:
        per_call = [
            (prices[j][0] * judge_in_tok + prices[j][1] * cfg.gateway.judge_max_tokens) / 1e6
            for j in cfg.replacement_judges
            if j in prices
        ]
        unpriced.extend(j for j in cfg.replacement_judges if j not in prices)
        # Every primary call failing and being stood in for is the bound.
        replacement_usd = max(per_call, default=0.0) * calls_per_judge * len(cfg.judges)
        rows.append(
            CostRow(
                "replacement",
                ", ".join(cfg.replacement_judges),
                0,  # only on failure; no call is scheduled up front
                None,
                None,
                replacement_usd or None,
            )
        )

    projected = models_usd + judges_usd + probe_usd
    # Failure paths that spend money without adding a call to any count:
    # `_generate_side` retries a dead stream once, and evaluatorq promotes a
    # stand-in for a judge call that errors outright.
    worst_case = projected + models_usd + replacement_usd
    return CostProjection(
        projected_usd=projected,
        worst_case_usd=worst_case,
        models_usd=models_usd,
        judges_usd=judges_usd,
        probe_usd=probe_usd,
        unpriced=sorted(set(unpriced)),
        rows=tuple(rows),
    )


def config_warnings(cfg: ArenaConfig, catalog: dict[str, ModelEntry]) -> list[str]:
    """What the catalog knows that the config should hear about, or ``[]``.

    Advisory only. Every one of these describes a run that still works, so none
    of them blocks, and the shipped configs already name models the catalog does
    not list.

    "Absent" and "deprecated" are separate branches because they are separate
    facts. `fetch_catalog` carries deprecated entries with the flag set, so a
    model that is missing entirely is one the catalog says nothing about, which
    is a statement about the catalog rather than a claim about the model. It is
    the picker in `fetch_chat_models` that omits deprecated models, not this
    dict.

    An empty catalog means it could not be reached, not that every model is
    unknown, so it produces no warnings at all. Warning on a network blip would
    teach the reader to skip the section that matters.
    """
    if not catalog:
        return []

    judges = list(cfg.judges) + list(cfg.replacement_judges)
    referenced = [w.model_id for w in cfg.candidates] + judges

    unknown: list[str] = []
    deprecated: list[str] = []
    seen: set[str] = set()
    for model_id in referenced:
        if model_id in seen:
            continue
        seen.add(model_id)
        entry = catalog.get(model_id)
        if entry is None:
            unknown.append(model_id)
        elif entry.deprecated:
            deprecated.append(model_id)

    # Only judges take evaluatorq's Responses path; a candidate is streamed over
    # chat completions regardless of what else it supports.
    no_responses = sorted(
        {j for j in judges if (e := catalog.get(j)) is not None and not e.has_responses}
    )

    warnings: list[str] = []
    if unknown:
        warnings.append(
            f"not listed in the model catalog: {', '.join(sorted(unknown))}. "
            "The catalog says nothing about them, which can mean a model that aged out "
            "of it. The run still calls them; the cost projection cannot price them."
        )
    if deprecated:
        warnings.append(
            f"the catalog lists these as deprecated: {', '.join(sorted(deprecated))}. "
            "They still route today, but pick a successor before they stop."
        )
    if no_responses:
        warnings.append(
            f"judges without a responses endpoint: {', '.join(no_responses)}. "
            "evaluatorq judges over the router's Responses endpoint because that is the "
            "one the router prices; these fall back to chat completions and their judge "
            "cost goes unattributed."
        )
    return warnings


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
        name
        for name, r in probe.items()
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
