"""The headless printer: plain lines on pipes, a progress bar on terminals."""

import asyncio
import io
import re

from rich.console import Console

from orq_arena.events import (MatchResolved, StandingsUpdated, TournamentEnded,
                              TurnResolved)
from orq_arena.headless import consume_events

ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")


def _events():
    return [
        TurnResolved(match_id="M1", round_number=1, majority="A", damage_dealt=15,
                     loser_side="b", hp_a=100, hp_b=85),
        MatchResolved(match_id="M1", winner="model-a", loser="model-b", by="round_cap",
                      final_hp_a=85, final_hp_b=40),
        StandingsUpdated(elo={"model-a": 1050.0, "model-b": 950.0},
                         matches_done=1, matches_total=1),
        TournamentEnded(champion="model-a", elo={"model-a": 1050.0, "model-b": 950.0},
                        battle_log_path="nowhere.jsonl", report={}),
    ]


async def _drive(console: Console) -> None:
    q: asyncio.Queue = asyncio.Queue()
    for ev in _events():
        q.put_nowait(ev)
    await consume_events(q, console=console, total_rounds=5)


def test_pipe_mode_prints_plain_lines():
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=100)
    asyncio.run(_drive(console))
    out = buf.getvalue()
    assert "model-a beats model-b (round_cap)" in out
    assert "match 1/1 done" in out
    assert "FINAL STANDINGS" in out
    assert "battle log" in out


def test_terminal_mode_shows_progress_and_leader():
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True, width=120)
    asyncio.run(_drive(console))
    out = ANSI.sub("", buf.getvalue())
    assert "rounds" in out and "leader model-a 1050" in out
    assert "model-a beats model-b (round_cap)" in out  # match line above the bar
    assert "FINAL STANDINGS" in out
