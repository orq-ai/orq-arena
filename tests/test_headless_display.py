"""The headless printer: chatter on stderr, summary on stdout;
plain lines on pipes, a progress bar on terminals."""

import asyncio
import io
import re

from rich.console import Console

from orq_arena.events import MatchResolved, StandingsUpdated, TournamentEnded, TurnResolved
from orq_arena.headless import consume_events

ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")


def _events():
    return [
        TurnResolved(match_id="M1", round_number=1, majority="A"),
        MatchResolved(match_id="M1", winner="model-a", loser="model-b"),
        StandingsUpdated(
            elo={"model-a": 1050.0, "model-b": 950.0}, matches_done=1, matches_total=1
        ),
        TournamentEnded(
            champion="model-a",
            elo={"model-a": 1050.0, "model-b": 950.0},
            battle_log_path="nowhere.jsonl",
            report={},
        ),
    ]


async def _drive(console: Console, err_console: Console, quiet: bool = False) -> None:
    q: asyncio.Queue = asyncio.Queue()
    for ev in _events():
        q.put_nowait(ev)
    await consume_events(q, console=console, err_console=err_console, total_rounds=5, quiet=quiet)


def test_pipe_mode_prints_plain_lines():
    out_buf, err_buf = io.StringIO(), io.StringIO()
    console = Console(file=out_buf, force_terminal=False, width=100)
    err_console = Console(file=err_buf, force_terminal=False, width=100)
    asyncio.run(_drive(console, err_console))
    err = err_buf.getvalue()
    out = out_buf.getvalue()
    assert "model-a beats model-b" in err
    assert "match 1/1 done" in err
    assert "Final Results" in out
    assert "battle log" in out


def test_terminal_mode_shows_progress_and_leader():
    out_buf, err_buf = io.StringIO(), io.StringIO()
    console = Console(file=out_buf, force_terminal=True, width=120)
    err_console = Console(file=err_buf, force_terminal=True, width=120)
    asyncio.run(_drive(console, err_console))
    err = ANSI.sub("", err_buf.getvalue())
    out = ANSI.sub("", out_buf.getvalue())
    assert "rounds" in err and "leader model-a 1050" in err
    assert "model-a beats model-b" in err  # match line above the bar
    assert "Final Results" in out


def test_quiet_mode_only_prints_summary():
    out_buf, err_buf = io.StringIO(), io.StringIO()
    console = Console(file=out_buf, force_terminal=False, width=100)
    err_console = Console(file=err_buf, force_terminal=False, width=100)
    asyncio.run(_drive(console, err_console, quiet=True))
    assert err_buf.getvalue() == ""
    assert "Final Results" in out_buf.getvalue()


def test_draw_prints_a_draw_line():
    out_buf, err_buf = io.StringIO(), io.StringIO()
    console = Console(file=out_buf, force_terminal=False, width=100)
    err_console = Console(file=err_buf, force_terminal=False, width=100)

    async def _drive_draw() -> None:
        q: asyncio.Queue = asyncio.Queue()
        q.put_nowait(MatchResolved(match_id="M1", winner="", loser=""))
        q.put_nowait(TournamentEnded(champion="", elo={}, battle_log_path="x.jsonl"))
        await consume_events(q, console=console, err_console=err_console, total_rounds=1)

    asyncio.run(_drive_draw())
    assert "draw" in err_buf.getvalue()
