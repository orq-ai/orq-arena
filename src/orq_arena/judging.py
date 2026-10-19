"""How the judge panel is seated, and what a decision judge's vote carries.

evaluatorq's pairwise jury already speaks both endpoints: a chat model is
prompted for a JSON verdict, and a model the catalog marks as decision-capable
is asked one A/B/tie ``choice`` question through the router's Decisions API
(``/classify``). It picks the endpoint per model from the catalog. That is the
wrong authority for a benchmark: the catalog marks chat models such as
claude-haiku-4-5 as decision-capable too, so an "LLM panel" quietly became a
mixed one when evaluatorq learned to route them. ``judge_api`` in the config
decides instead, and `pin_judge_endpoints` makes evaluatorq follow it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from evaluatorq import PairwiseComparison, llm_jury_pairwise
from evaluatorq.common.model_catalogue import ModelInfo, get_model_info, register_model
from evaluatorq.pairwise import pairwise_consensus

from .config import ArenaConfig

_SWAP = {"A": "B", "B": "A", "tie": "tie"}


async def pin_judge_endpoints(cfg: ArenaConfig, client: Any) -> None:
    """Seat every judge on the endpoint ``cfg.judge_api`` names, whatever the catalog says.

    Overrides evaluatorq's catalogue entry for each judge so its runtime routing
    agrees with the config. A judge the catalogue does not know is still pinned
    in decisions mode, so a catalogue outage cannot demote it to a chat call.
    Whether a model can serve the pinned endpoint at all is the preflight's
    question (`preflight.judge_api_errors`), asked before any spend.
    """
    decisions = cfg.judge_api == "decisions"
    for model in dict.fromkeys([*cfg.judges, *cfg.replacement_judges]):
        info = await get_model_info(model, client)
        if info is None:
            if not decisions:
                continue  # unknown to the catalogue means chat already
            info = ModelInfo(
                input_cost_per_1k=None,
                output_cost_per_1k=None,
                provider=model.split("/", 1)[0],
                supports_responses=False,
            )
        if info.supports_classify != decisions:
            register_model(model, info._replace(supports_classify=decisions))


def make_jury(
    cfg: ArenaConfig,
    *,
    panel: list[str],
    replacements: list[str],
    client: Any,
    criteria: str | None = None,
    min_successful_judges: int | None = None,
) -> Jury:
    """The pairwise jury both `run` and `rejudge` judge with, built one way."""
    quorum = cfg.min_successful_judges if min_successful_judges is None else min_successful_judges
    comparator = llm_jury_pairwise(
        judges=panel,
        criteria=criteria or cfg.criteria,
        swap=cfg.judge_swap,
        replacement_judges=replacements or None,
        min_successful_judges=quorum,
        max_tokens=cfg.gateway.judge_max_tokens,
        timeout_ms=cfg.gateway.judge_timeout_ms,
        client=client,
    )
    return Jury(comparator, floor=cfg.judge_abstain_below, quorum=quorum)


class Jury:
    """evaluatorq's comparator plus the abstain floor, which evaluatorq does not have."""

    def __init__(self, comparator: Any, *, floor: float | None, quorum: int) -> None:
        self._comparator = comparator
        self._floor = floor
        self._quorum = quorum

    async def compare(
        self, *, question: str, response_a: str, response_b: str
    ) -> PairwiseComparison:
        comparison = await self._comparator.compare(
            question=question, response_a=response_a, response_b=response_b
        )
        return apply_abstain_floor(comparison, self._floor, self._quorum)


def vote_probabilities(vote: Any) -> dict[str, float] | None:
    """P(A), P(B), P(tie) for one reconciled vote, or None for a prompted judge.

    Read off the vote's observations, where evaluatorq keeps each ordering's raw
    decision answer. The swapped ordering is turned back to the original seats
    (its "A" was response B) and the orderings are averaged. Takes a
    `PairwiseVote` or its stored dict, so a saved run reads the same as a live one.
    """
    observations = (
        vote.get("observations") if isinstance(vote, dict) else getattr(vote, "observations", None)
    ) or []
    seen: list[dict[str, float]] = []
    for obs in observations:
        ordering = obs.get("ordering") if isinstance(obs, dict) else obs.ordering
        raw = obs.get("raw_output") if isinstance(obs, dict) else obs.raw_output
        probs = (raw or {}).get("probabilities")
        if not isinstance(probs, dict):
            continue
        if ordering == "ba":
            probs = {_SWAP.get(k, k): v for k, v in probs.items()}
        seen.append({k: float(probs.get(k, 0.0)) for k in ("A", "B", "tie")})
    if not seen:
        return None
    return {k: sum(p[k] for p in seen) / len(seen) for k in ("A", "B", "tie")}


def top_probability(vote: Any) -> float | None:
    """The probability of the option the vote went to; None for a prompted or abstained vote."""
    choice = vote.get("vote") if isinstance(vote, dict) else vote.vote
    probs = vote_probabilities(vote)
    if probs is None or choice is None:
        return None
    return probs[choice]


def apply_abstain_floor(
    comparison: PairwiseComparison, floor: float | None, quorum: int
) -> PairwiseComparison:
    """Turn votes whose winning option fell under ``floor`` into abstentions.

    Same path as a flipped vote: the judge stays on the record with its
    probabilities, casts nothing, and the panel winner is recomputed with
    evaluatorq's own rule (plurality, inconclusive under quorum).
    """
    if floor is None:
        return comparison
    votes = []
    for v in comparison.votes:
        p = top_probability(v)
        # A verdict with no readable probabilities cannot show it cleared the floor.
        unsure = v.vote is not None and (p is None or p < floor)
        votes.append(v.model_copy(update={"vote": None}) if unsure else v)
    decisive = [v.vote for v in votes if v.vote is not None]
    winner = "inconclusive" if len(decisive) < max(1, quorum) else pairwise_consensus(decisive)
    return comparison.model_copy(update={"votes": votes, "winner": winner})


def floor_abstained(vote: dict, floor: float | None) -> bool:
    """True when this stored vote is an abstention the floor made, not a flip or a failure."""
    if floor is None or vote.get("vote") is not None or vote.get("flipped"):
        return False
    probs = vote_probabilities(vote)
    if probs is None:
        # Answered but unreadable: the floor abstains it. No observations means a failed call.
        return bool(vote.get("observations"))
    return max(probs.values()) < floor


def judge_labels(model_ids: Sequence[str]) -> dict[str, str]:
    """A display label per judge id that no other judge on the panel shares.

    The short name (``gpt-oss-120b``), or ``provider/short`` only for ids whose
    short name repeats, so ``openai/gpt-oss-120b`` and ``groq/gpt-oss-120b`` on
    one panel get two cards instead of one.
    """
    ids = list(dict.fromkeys(model_ids))
    shorts = [m.split("/")[-1] for m in ids]
    labels = {}
    for model, short in zip(ids, shorts, strict=True):
        if shorts.count(short) > 1:
            short = f"{model.split('/', 1)[0]}/{short}" if "/" in model else model
        labels[model] = short
    return labels


def judged_cost_usd(comparison: PairwiseComparison) -> float | None:
    """What the panel cost for this round, when every judge call was priced.

    Decision calls carry the cost the router reported; prompted calls are priced
    by evaluatorq from the catalog. A round with any unpriced call returns None,
    so a partial figure never reads as the whole.
    """
    usage = comparison.token_usage
    if usage is None or usage.total_cost is None or usage.priced_calls < usage.calls:
        return None
    return usage.total_cost
