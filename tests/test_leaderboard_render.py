"""Headless render test: the leaderboard mounts with a real report payload."""

from __future__ import annotations

import json
from pathlib import Path

from textual.app import App
from textual.widgets import DataTable

from orq_arena.config import load_config
from orq_arena.data.schemas import load_records
from orq_arena.tournament.driver import rebuild_from_log
from orq_arena.tui.screens.leaderboard import LeaderboardScreen

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "quickstart"


class _Host(App):
    pass


async def test_leaderboard_mounts_with_quickstart_report():
    cfg = load_config(EXAMPLE / "config.yaml")
    records = load_records(EXAMPLE / "battles.jsonl")
    manifest = json.loads((EXAMPLE / "battles.run.json").read_text())
    elo, report = rebuild_from_log(cfg, records, preflight=manifest.get("preflight"))
    screen = LeaderboardScreen(
        elo=elo,
        champion=max(elo, key=elo.get),
        log_path="examples/quickstart/battles.jsonl",
        report=report,
    )
    app = _Host()
    async with app.run_test() as pilot:
        await app.push_screen(screen)
        await pilot.pause()
        main = screen.query_one("#table", DataTable)
        assert main.row_count == len(elo)
        # report payload present -> jury + win grid tables mount too
        assert screen.query_one("#jury", DataTable).row_count >= 1
        assert screen.query_one("#grid", DataTable).row_count == len(elo)


async def test_leaderboard_mounts_plain_without_report():
    screen = LeaderboardScreen(elo={"a": 1000.0, "b": 990.0}, champion="a", log_path="x")
    app = _Host()
    async with app.run_test() as pilot:
        await app.push_screen(screen)
        await pilot.pause()
        assert screen.query_one("#table", DataTable).row_count == 2
        assert not screen.query("#jury")
