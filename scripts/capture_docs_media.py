"""Regenerate the committed TUI screenshots in docs/assets/ and media/.

Drives the real TUI headlessly (Textual Pilot) over the committed example run
(examples/quickstart), so the images always match the code and real data:

    uv run python scripts/capture_docs_media.py

Writes leaderboard.svg and battle-browser.svg. The report PNG is captured
separately with headless Chrome from examples/quickstart/battles.report.html.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from orq_arena.config import load_config
from orq_arena.data.schemas import load_records
from orq_arena.tournament.driver import rebuild_from_log
from orq_arena.tui.app import ArenaApp
from orq_arena.tui.screens.battle_browser import BattleBrowserScreen
from orq_arena.tui.screens.leaderboard import LeaderboardScreen

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "quickstart"
# A decisive round with a flip badge, the two things the browser exists to show.
BROWSER_ROUND = 2


async def capture() -> dict[str, str]:
    cfg = load_config(str(EXAMPLE / "config.yaml"))
    records = load_records(EXAMPLE / "battles.jsonl")
    manifest = json.loads((EXAMPLE / "battles.run.json").read_text())
    elo, report = rebuild_from_log(cfg, records, preflight=manifest.get("preflight"))
    champion = max(elo, key=elo.get) if elo else ""

    shots: dict[str, str] = {}

    app = ArenaApp(cfg=cfg, prompts=[], battle_log_path="", live=False)
    async with app.run_test(size=(140, 38)) as pilot:
        app.push_screen(
            LeaderboardScreen(
                elo=elo,
                champion=champion,
                log_path="examples/quickstart/battles.jsonl",
                report=report,
                cfg=cfg,
            )
        )
        await pilot.pause()
        shots["leaderboard.svg"] = app.export_screenshot()

    app = ArenaApp(cfg=cfg, prompts=[], battle_log_path="", live=False)
    async with app.run_test(size=(140, 36)) as pilot:
        app.push_screen(BattleBrowserScreen(records))
        for _ in range(BROWSER_ROUND):
            await pilot.press("right")
        await pilot.pause()
        shots["battle-browser.svg"] = app.export_screenshot()
    return shots


def main() -> None:
    shots = asyncio.run(capture())
    for name, svg in shots.items():
        for dest in (ROOT / "docs" / "assets" / name, ROOT / "media" / name):
            dest.write_text(svg, encoding="utf-8")
            print(f"wrote {dest.relative_to(ROOT)} ({len(svg)} bytes)")


if __name__ == "__main__":
    main()
