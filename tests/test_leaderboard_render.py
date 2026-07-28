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


async def test_style_control_line_is_descriptive_and_len_ctrl_column_is_gated():
    """Rendered through the widget, per the house rule for Textual changes.

    Identified report: the count line renders and the len-ctrl column exists.
    Unidentified report (coefficient withheld): the count still renders, the
    coefficient text and the column are absent.
    """
    from textual.widgets import Static

    base = {
        "length_pref": {"longer_wins": 52, "rounds": 60},
        "win_grid": {"a": {"b": 2.0}, "b": {"a": 1.0}},
    }
    identified = base | {
        "length_coef": 18.3,
        "elo_style_controlled": {"a": 1010.0, "b": 990.0},
    }

    for report, coef_shown in ((identified, True), (base, False)):
        screen = LeaderboardScreen(
            elo={"a": 1000.0, "b": 990.0}, champion="a", log_path="x", report=report
        )
        app = _Host()
        async with app.run_test() as pilot:
            await app.push_screen(screen)
            await pilot.pause()
            texts = [str(w.render()) for w in screen.query(Static)]
            style_lines = [t for t in texts if "longer answer won" in t]
            assert style_lines, "the descriptive count line never rendered"
            assert "87% of decisive rounds (52/60)" in style_lines[0]
            headers = [str(c.label) for c in screen.query_one("#table", DataTable).columns.values()]
            assert ("len-ctrl" in headers) is coef_shown
            assert ("prices that preference out" in style_lines[0]) is coef_shown


async def test_the_token_columns_show_real_numbers_not_zero():
    """Rendered through the widget, not read off the report dict.

    These columns went to 0 for every run when the map they were looked up
    through stopped agreeing with the metrics about its key. Only a render test
    catches that: the report payload itself was correct throughout.
    """
    cfg = load_config(EXAMPLE / "config.yaml")
    records = load_records(EXAMPLE / "battles.jsonl")
    elo, report = rebuild_from_log(cfg, records)
    assert report["verbosity"], "fixture has no token data to render"

    screen = LeaderboardScreen(
        elo=elo, champion=max(elo, key=elo.get), log_path="x.jsonl", report=report
    )
    app = _Host()
    async with app.run_test() as pilot:
        await app.push_screen(screen)
        await pilot.pause()
        table = screen.query_one("#table", DataTable)
        headers = [str(c.label) for c in table.columns.values()]
        tok_col = headers.index("avg tok")
        rendered = [str(table.get_row_at(i)[tok_col]) for i in range(table.row_count)]
    assert any(v not in ("0", "") for v in rendered), f"every avg tok cell read {rendered}"
