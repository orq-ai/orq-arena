"""Pilot: decision models as filters for generated benchmark prompts, against a cheap LLM.

Generates candidate prompts per starter category with planted flaws (off category,
unanswerable, near duplicate of a starter prompt), then asks each labeller one
yes/no question: is this a usable benchmark prompt for its category? Prints
precision and recall at catching the planted flaws, spend and latency, as
markdown. Feeds the data-generation section of
docs/research/llm-judges-vs-decision-models.md.

    uv run python scripts/data_filter_pilot.py --out .context/pilot
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import time
from pathlib import Path

from evaluatorq.common.judge import ClassifyQuestion
from evaluatorq.common.llm_call import execute_classify

from orq_arena.config import OrqAIGatewayConfig
from orq_arena.providers.models_list import fetch_price_map
from orq_arena.providers.orq_gateway import OrqGateway

GENERATOR = "openai/gpt-5.4-mini"
DECIDERS = ["typesafe/jev-latest", "orq/decider-4b", "openai/gpt-6-luna"]
LLM_LABELLERS = ["openai/gpt-5.4-nano", "google/gemini-3.5-flash-lite"]
PER_KIND = {"none": 30, "off_category": 6, "unanswerable": 6, "near_duplicate": 6}
QUESTION = (
    "Is `candidate` a usable benchmark prompt for the category `category`? Usable means: "
    "it belongs to that category, it can be answered well from general knowledge in one "
    "reply (no missing context, no private data, no future events), and it is not a "
    "near-duplicate rewording of any prompt in `existing`."
)
FLAWS = {
    "none": "a fresh, well-posed prompt that belongs in the category",
    "off_category": "a well-posed prompt that clearly belongs to a different category",
    "unanswerable": "a prompt that cannot be answered: it relies on a missing attachment, "
    "private data, or an unknowable future fact",
    "near_duplicate": "a light rewording of one of the existing prompts",
}


async def _generate(gateway: OrqGateway, category: str, existing: list[str]) -> list[dict]:
    out: list[dict] = []
    for kind, n in PER_KIND.items():
        resp = await gateway.client.chat.completions.create(
            model=GENERATOR,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Category: {category}\nExisting prompts:\n"
                        + "\n".join(f"- {p}" for p in existing)
                        + f"\n\nWrite {n} new prompts, each {FLAWS[kind]}. Return JSON "
                        '{"prompts": ["...", ...]} and nothing else.'
                    ),
                }
            ],
            response_format={"type": "json_object"},
        )
        prompts = json.loads(resp.choices[0].message.content or "{}").get("prompts") or []
        out += [{"category": category, "flaw": kind, "text": p} for p in prompts[:n]]
    return out


def _state(item: dict, existing: list[str]) -> dict:
    return {"category": item["category"], "existing": existing, "candidate": item["text"]}


async def _decide(gateway: OrqGateway, model: str, item: dict, existing: list[str]) -> dict:
    q = ClassifyQuestion(kind="noul", instructions=QUESTION, state=_state(item, existing))
    t0 = time.monotonic()
    payload, usage = await execute_classify(
        client=gateway.client, model=model, question=q, span=None, timeout_s=60
    )
    p = (payload.get("answers") or {}).get("verdict", {}).get("noul")
    if p is None:  # single-question form keys the answer by the question name
        p = next(iter((payload.get("answers") or {}).values()), {}).get("noul")
    return {
        "usable": None if p is None else p >= 0.5,
        "p": p,
        "ms": int((time.monotonic() - t0) * 1000),
        "usd": getattr(usage, "total_cost", None),
    }


async def _ask_llm(gateway: OrqGateway, model: str, item: dict, existing: list[str]) -> dict:
    t0 = time.monotonic()
    resp = await gateway.client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": QUESTION
                + "\n\n"
                + json.dumps(_state(item, existing))
                + '\n\nAnswer with JSON {"usable": true|false} and nothing else.',
            }
        ],
        response_format={"type": "json_object"},
    )
    try:
        usable = json.loads(resp.choices[0].message.content or "{}").get("usable")
    except ValueError:
        usable = None
    u = resp.usage
    return {
        "usable": usable if isinstance(usable, bool) else None,
        "ms": int((time.monotonic() - t0) * 1000),
        "tokens": (u.prompt_tokens, u.completion_tokens) if u else (0, 0),
    }


async def main(out: Path, seed: int) -> None:
    out.mkdir(parents=True, exist_ok=True)
    gateway = OrqGateway(OrqAIGatewayConfig())
    starter = [json.loads(line) for line in Path("prompts/starter.jsonl").open()]
    existing: dict[str, list[str]] = {}
    for row in starter:
        existing.setdefault(row["category"], []).append(row["prompt"])

    items_path = out / "items.jsonl"
    if items_path.exists():
        items = [json.loads(line) for line in items_path.open()]
    else:
        items = [
            i for c in existing for i in await _generate(gateway, c, existing[c])
        ]  # sequential: four categories, no need to fan out
        random.Random(seed).shuffle(items)
        items_path.write_text("".join(json.dumps(i) + "\n" for i in items))

    sem = asyncio.Semaphore(8)

    async def label(model: str, item: dict) -> dict:
        async with sem:
            fn = _decide if model in DECIDERS else _ask_llm
            try:
                return await fn(gateway, model, item, existing[item["category"]])
            except Exception as exc:
                return {"usable": None, "error": str(exc)[:200], "ms": 0}

    labels = {}
    for model in DECIDERS + LLM_LABELLERS:
        labels[model] = await asyncio.gather(*(label(model, i) for i in items))
    (out / "labels.json").write_text(json.dumps(labels, indent=1))

    prices = await fetch_price_map(OrqAIGatewayConfig())
    for model in LLM_LABELLERS:  # chat replies carry tokens, not a cost: price them here
        cin, cout = prices.get(model, (None, None))
        for r in labels[model]:
            tin, tout = r.get("tokens", (0, 0))
            r["usd"] = None if cin is None else (cin * tin + cout * tout) / 1e6

    flawed = [i["flaw"] != "none" for i in items]
    print(f"{len(items)} generated prompts, {sum(flawed)} with a planted flaw.\n")
    print(
        "| Labeller | Kind | Flaws caught (recall) | Flags that were flaws (precision) "
        "| Good prompts kept | No answer | p50 latency | $ per 1k labels |"
    )
    print("|---|---|---|---|---|---|---|---|")
    for model, rows in labels.items():
        flagged = [r.get("usable") is False for r in rows]
        tp = sum(f and g for f, g in zip(flagged, flawed, strict=True))
        kept_good = sum((not f) and (not g) for f, g in zip(flagged, flawed, strict=True))
        none = sum(r.get("usable") is None for r in rows)
        ms = [r["ms"] for r in rows if r.get("ms")]
        usd = [r.get("usd") for r in rows]
        cost = f"${sum(usd) * 1000 / len(rows):.3f}" if all(u is not None for u in usd) else "n/a"
        print(
            f"| {model} | {'decision' if model in DECIDERS else 'llm'} "
            f"| {tp / max(1, sum(flawed)):.0%} | {tp / max(1, sum(flagged)):.0%} "
            f"| {kept_good / max(1, len(flawed) - sum(flawed)):.0%} | {none} "
            f"| {statistics.median(ms) / 1000:.2f}s | {cost} |"
        )
    print("\nRecall per planted flaw:\n")
    kinds = [k for k in PER_KIND if k != "none"]
    print("| Labeller | " + " | ".join(kinds) + " |")
    print("|---|" + "---|" * len(kinds))
    for model, rows in labels.items():
        cells = []
        for k in kinds:
            idx = [n for n, i in enumerate(items) if i["flaw"] == k]
            cells.append(
                f"{sum(rows[n].get('usable') is False for n in idx) / max(1, len(idx)):.0%}"
            )
        print(f"| {model} | " + " | ".join(cells) + " |")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=".context/pilot")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    asyncio.run(main(Path(args.out), args.seed))
