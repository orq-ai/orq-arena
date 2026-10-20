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


# --- the terminal verdict, held to the report page's bar ------------------


def _verdict(top_difference, elo=None):
    from orq_arena.headless import _verdict_line

    report = {"elo_ci": {"a": (900.0, 1300.0), "b": (700.0, 1100.0)}, "rated_rounds": 40}
    if top_difference is not None:
        report["top_difference"] = top_difference
    return _verdict_line(
        TournamentEnded(
            champion="a",
            elo=elo or {"a": 1100.0, "b": 900.0},
            battle_log_path="x.jsonl",
            report=report,
        )
    )


def test_headless_verdict_separates_on_the_difference_not_on_overlap():
    """Headless is the default run mode, so this line is what most users see.
    The marginal intervals here overlap; the measured difference does not."""
    line = _verdict(
        {
            "champion": "a",
            "runner_up": "b",
            "lo": 25.0,
            "hi": 284.0,
            "win_rate": 0.99,
            "separated": True,
        }
    )
    assert line == "🏆 a wins"


def test_headless_verdict_never_calls_an_unresolved_gap_a_tie():
    line = _verdict(
        {
            "champion": "a",
            "runner_up": "b",
            "lo": -120.0,
            "hi": 284.0,
            "win_rate": 0.71,
            "separated": False,
        }
    )
    assert "cannot separate" in line and "71%" in line
    assert "statistically tied" not in line


def test_headless_verdict_claims_nothing_when_nothing_was_measured():
    assert _verdict(None) == "🏆 a has the best rating"


def test_a_finished_trial_prints_one_line_and_the_table_gains_harness_columns():
    from orq_arena.events import SolutionReady
    from orq_arena.headless import _final_table

    q: asyncio.Queue = asyncio.Queue()
    q.put_nowait(
        SolutionReady(
            match_id="M1",
            side="a",
            passed=True,
            cost_usd=0.42,
            duration_ms=120000,
            steps=14,
            exit_reason="finished",
        )  # fmt: skip
    )
    q.put_nowait(
        TournamentEnded(
            champion="pi",
            elo={"pi": 1010.0, "cc": 990.0},
            battle_log_path="x.jsonl",
            report={
                "harness": {
                    "pi": {
                        "passed": 6,
                        "verified": 8,
                        "mean_cost_usd": 0.21,
                        "mean_duration_s": 246.0,
                    }
                }
            },
        )  # fmt: skip
    )
    out, err = io.StringIO(), io.StringIO()
    asyncio.run(
        consume_events(
            q,
            console=Console(file=out, width=120),
            err_console=Console(file=err, width=120),
            total_rounds=1,
        )  # fmt: skip
    )
    assert "hidden tests PASSED" in err.getvalue() and "$0.42" in err.getvalue()
    assert "6/8" in out.getvalue() and "0.21" in out.getvalue() and "4.1" in out.getvalue()
    table = _final_table(
        TournamentEnded(champion="pi", elo={"pi": 1.0}, battle_log_path="", report={})
    )
    assert [c.header for c in table.columns] == ["#", "Model", "ELO"]


def test_the_table_shows_voids_and_estimated_costs_not_a_bare_rate():
    from orq_arena.headless import _harness_cells

    # 10 trials, 8 voided: the rate must not read 2/2
    assert _harness_cells(
        {"passed": 2, "verified": 2, "unverified": 8, "mean_cost_usd": 0.5, "mean_duration_s": 60.0}
    )[0] == "2/2 (8 void)"  # fmt: skip
    # a pi cost is tokens at the catalog rate: marked, not passed off as measured
    estimated = _harness_cells({"passed": 1, "verified": 1, "mean_cost_usd": 0.21, "estimated": 3})
    reported = _harness_cells({"passed": 1, "verified": 1, "mean_cost_usd": 0.21, "estimated": 0})
    assert estimated[1] == "~0.21" and reported[1] == "0.21"


def test_a_finished_trial_line_marks_an_estimated_cost():
    from orq_arena.events import SolutionReady
    from orq_arena.headless import _solution_line

    base = dict(
        match_id="M1", side="a", passed=True, cost_usd=0.42, steps=3, exit_reason="finished"
    )
    assert "· $0.42" in _solution_line(SolutionReady(**base))
    assert "· ~$0.42" in _solution_line(SolutionReady(**base, cost_estimated=True))
