"""Headless render test: the leaderboard mounts with a real report payload."""

from __future__ import annotations

import json
from pathlib import Path

from textual.app import App
from textual.widgets import DataTable

from orq_arena.tui.screens.leaderboard import LeaderboardScreen

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "demo_tournament.json"


class _Host(App):
    pass


async def test_leaderboard_mounts_with_fixture_report():
    ended = json.loads(FIXTURE.read_text())[-1]
    assert ended["type"] == "tournament_ended"
    screen = LeaderboardScreen(
        elo=ended["elo"],
        champion=ended["champion"],
        log_path=ended["battle_log_path"],
        report=ended["report"],
    )
    app = _Host()
    async with app.run_test() as pilot:
        await app.push_screen(screen)
        await pilot.pause()
        main = screen.query_one("#table", DataTable)
        assert main.row_count == len(ended["elo"])
        # report payload present -> jury + win grid tables mount too
        assert screen.query_one("#jury", DataTable).row_count >= 1
        assert screen.query_one("#grid", DataTable).row_count == len(ended["elo"])


async def test_leaderboard_mounts_plain_without_report():
    screen = LeaderboardScreen(elo={"a": 1000.0, "b": 990.0}, champion="a", log_path="x")
    app = _Host()
    async with app.run_test() as pilot:
        await app.push_screen(screen)
        await pilot.pause()
        assert screen.query_one("#table", DataTable).row_count == 2
        assert not screen.query("#jury")
