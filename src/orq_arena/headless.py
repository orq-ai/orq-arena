"""Headless runner, the same tournament, no TUI, matches in parallel.

For CI/cron benchmark generation. Progress and match chatter go to
stderr so stdout stays pipeable; the queue is consumed two ways, picked
by where stderr goes (the sibling repos' treatment):

* a terminal: a pinned Rich progress bar over rounds (spinner, M-of-N,
  elapsed, current leader) with completed-match one-liners above it;
* a pipe or CI log: plain line-per-match output, no ANSI redraw noise.

Both end with the full statistical leaderboard and the report-page path
on stdout.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from .config import ArenaConfig
from .data.prompts import PromptItem
from .events import MatchResolved, RoundVoided, StandingsUpdated, TournamentEnded, TurnResolved
from .tournament.driver import run_tournament


def _ranked(ended: TournamentEnded) -> list[tuple[str, float]]:
    return sorted(ended.elo.items(), key=lambda kv: kv[1], reverse=True)


def _win_pct(grid: dict[str, dict[str, float]], name: str) -> str:
    """Points scored / rated rounds played; ties count ½ (win share)."""
    points = sum((grid.get(name) or {}).values())
    played = points + sum((grid.get(o) or {}).get(name, 0.0) for o in grid)
    return f"{points / played:.0%}" if played else ""


def _verdict_line(ended: TournamentEnded) -> str | None:
    """The report banner's headline call: a winner, or an honest tie."""
    r: dict[str, Any] = ended.report or {}
    ranked = _ranked(ended)
    if not ranked:
        return None
    if len(ranked) == 1:
        return f"🏆 {ranked[0][0]} wins"
    ci = r.get("elo_ci") or {}
    (n1, e1), (n2, e2) = ranked[0], ranked[1]
    lo1, hi1 = ci.get(n1, (e1, e1))
    lo2, hi2 = ci.get(n2, (e2, e2))
    if ci and lo1 <= hi2 and lo2 <= hi1:
        return (
            f"🏆 {n1} leads, but {n2} is statistically tied "
            f"(CIs overlap at {r.get('rated_rounds', 0)} rated rounds; "
            "the report page has the tie-breakers)"
        )
    return f"🏆 {n1} wins"


def _final_table(ended: TournamentEnded) -> Table:
    r: dict[str, Any] = ended.report or {}
    ci = r.get("elo_ci") or {}
    grid = r.get("win_grid") or {}
    thinking = r.get("thinking") or {}
    table = Table(title="FINAL STANDINGS")
    cols = ["#", "Model", "ELO"] + (["95% CI"] if ci else []) + (["win%"] if grid else [])
    for c in cols:
        table.add_column(c)
    for i, (name, elo) in enumerate(_ranked(ended), 1):
        badge = " 🧠" if thinking.get(name) else ""
        row = [str(i), f"{name}{badge}", f"{elo:.0f}"]
        if ci:
            lo, hi = ci.get(name, (elo, elo))
            # -inf lower bound: the model won too few rounds to identify a floor
            fmt = lambda v: "-∞" if v == float("-inf") else f"{v:.0f}"  # noqa: E731
            row.append(f"{fmt(lo)}–{fmt(hi)}")
        if grid:
            row.append(_win_pct(grid, name))
        table.add_row(*row)
    return table


def _print_summary(console: Console, ev: TournamentEnded) -> None:
    console.print()
    verdict = _verdict_line(ev)
    if verdict:
        console.print(verdict)
        console.print()
    console.print(_final_table(ev))
    console.print()
    r = ev.report or {}
    jury_bits = []
    if r.get("mean_agreement") is not None:
        jury_bits.append(f"{r['mean_agreement']:.0%} mean agreement")
    if r.get("length_coef") is not None:
        lean = "longer" if r["length_coef"] > 0 else "shorter"
        jury_bits.append(f"leaned {lean} ({r['length_coef']:+.2f}); the report prices it out")
    if jury_bits:
        console.print("jury: " + " · ".join(jury_bits))
    rated = r.get("rated_rounds")
    if rated is not None:
        console.print(f"rounds: {rated} rated · {r.get('error_rounds', 0)} voided")
    tok = r.get("tokens") or {}
    if tok:
        console.print(
            f"tokens, models {tok.get('models_in', 0):,} in "
            f"/ {tok.get('models_out', 0):,} out"
            f" · jury {tok['judges_in']:,} in / {tok['judges_out']:,} out"
        )
    console.print()
    console.print(f"battle log → {ev.battle_log_path}")
    from .report import report_path_for

    rp = report_path_for(ev.battle_log_path)
    if rp.exists():
        console.print(f"report page → {rp}")


def _match_line(ev: MatchResolved) -> str:
    if not ev.winner:
        return f"[dim]{ev.match_id}[/dim] 🤝 draw"
    return f"[dim]{ev.match_id}[/dim] {ev.winner} beats {ev.loser}"


async def consume_events(
    events: asyncio.Queue,
    *,
    console: Console,
    err_console: Console,
    total_rounds: int,
    quiet: bool = False,
) -> None:
    """Drain the event queue until TournamentEnded.

    Progress and match chatter go to err_console (stderr) so stdout stays
    pipeable; the final summary goes to console (stdout). On a terminal,
    a pinned progress bar counts rounds while match results print above
    it; on a pipe, the plain line-per-match output survives grep and CI
    logs. quiet drops everything but the summary.
    """
    if quiet:
        while True:
            ev = await events.get()
            if isinstance(ev, TournamentEnded):
                _print_summary(console, ev)
                return

    if not err_console.is_terminal:
        while True:
            ev = await events.get()
            if isinstance(ev, TurnResolved):
                # Round heartbeat: a match can run minutes; CI logs shouldn't go dark.
                err_console.print(
                    f"[dim]{ev.match_id} round {ev.round_number}: {ev.majority}[/dim]"
                )
            elif isinstance(ev, MatchResolved):
                err_console.print(_match_line(ev))
            elif isinstance(ev, RoundVoided):
                err_console.print(f"[yellow]{ev.match_id} round void, {ev.reason}[/yellow]")
            elif isinstance(ev, StandingsUpdated):
                err_console.print(f"[dim]match {ev.matches_done}/{ev.matches_total} done[/dim]")
            elif isinstance(ev, TournamentEnded):
                _print_summary(console, ev)
                return

    else:
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=err_console,
        )
        with progress:
            task = progress.add_task("rounds", total=total_rounds)
            while True:
                ev = await events.get()
                if isinstance(ev, TurnResolved):
                    progress.advance(task, 1)
                elif isinstance(ev, RoundVoided):
                    progress.advance(task, 1)
                    progress.console.print(
                        f"[yellow]{ev.match_id} round void, {ev.reason}[/yellow]"
                    )
                elif isinstance(ev, MatchResolved):
                    progress.console.print(_match_line(ev))
                elif isinstance(ev, StandingsUpdated):
                    leader = max(ev.elo, key=ev.elo.get) if ev.elo else ""
                    progress.update(
                        task,
                        description=(
                            f"rounds · {ev.matches_done}/{ev.matches_total} matches"
                            + (f" · leader {leader} {ev.elo[leader]:.0f}" if leader else "")
                        ),
                    )
                elif isinstance(ev, TournamentEnded):
                    progress.update(task, completed=total_rounds)
                    break
        _print_summary(console, ev)


async def run_headless(
    *,
    cfg: ArenaConfig,
    prompts: list[PromptItem],
    battle_log_path: str,
    preflight: dict | None = None,
    dataset: dict | None = None,
    quiet: bool = False,
) -> dict[str, float]:
    console = Console(file=sys.stdout)
    err_console = Console(file=sys.stderr)
    events: asyncio.Queue = asyncio.Queue()

    from .preflight import call_counts

    counts = call_counts(cfg, prompts)
    total_rounds = counts.matches * counts.rounds_per_match

    printer_task = asyncio.create_task(
        consume_events(
            events,
            console=console,
            err_console=err_console,
            total_rounds=total_rounds,
            quiet=quiet,
        )
    )
    elo = await run_tournament(
        cfg=cfg,
        prompts=prompts,
        battle_log_path=battle_log_path,
        events=events,
        concurrency=max(1, cfg.headless_concurrency),
        preflight=preflight,
        dataset=dataset,
    )
    await printer_task
    return elo
