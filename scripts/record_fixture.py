"""Dev script: regenerate fixtures/demo_tournament.json from a tiny real run.

Not product surface — run this when the event schema or vocabulary changes
(roughly once a quarter). Needs ORQ_API_KEY. Costs a few cents.

    uv run python scripts/record_fixture.py
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from orc_arena.config import ArenaConfig
from orc_arena.data.prompts import PromptItem
from orc_arena.tournament.driver import run_tournament

CFG = ArenaConfig.model_validate(
    {
        "match": {"starting_hp": 100, "max_rounds": 2},
        "gateway": {"warrior_max_tokens": 400},
        "warriors": [
            {"model_id": "openai/gpt-5.4-mini"},
            {"model_id": "google/gemini-2.5-flash",
             "reasoning": {"thinking": {"type": "disabled"}}},
            {"model_id": "mistral/mistral-medium-2604"},
        ],
        "judges": [
            "anthropic/claude-haiku-4-5-20251001",
            "google/gemini-2.5-flash-lite",
            "openai/gpt-5.4-nano",
        ],
        "replacement_judges": ["mistral/mistral-small-2603"],
        "min_successful_judges": 2,
    }
)

PROMPTS = [
    PromptItem("In two sentences, explain a hash map to a new programmer.", "general"),
    PromptItem("Give one strong argument for and one against microservices, two sentences each.", "general"),
    PromptItem("Write a haiku about a slow database query.", "creative"),
]

OUT = Path("fixtures/demo_tournament.json")


async def main() -> None:
    events: asyncio.Queue = asyncio.Queue()
    recorded: list[dict] = []

    async def drain() -> None:
        while True:
            ev = await events.get()
            d = ev.model_dump()
            # Curated pacing: fast text stream, readable beats between the rest.
            d["_delay"] = 0.01 if d["type"] in ("response_chunk", "thinking_chunk") else 0.35
            if d["type"] == "tournament_ended":
                d["battle_log_path"] = ""
                recorded.append(d)
                return
            recorded.append(d)

    drain_task = asyncio.create_task(drain())
    await run_tournament(
        cfg=CFG, prompts=PROMPTS,
        battle_log_path="outputs/smoke/fixture_battles.jsonl", events=events,
    )
    await drain_task

    OUT.write_text(json.dumps(recorded, indent=1, default=str))
    kinds: dict[str, int] = {}
    for d in recorded:
        kinds[d["type"]] = kinds.get(d["type"], 0) + 1
    print(f"wrote {OUT} ({len(recorded)} events): {kinds}")


if __name__ == "__main__":
    asyncio.run(main())
