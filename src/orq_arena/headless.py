"""Headless runner, the same tournament, no TUI, matches in parallel.

For CI/cron benchmark generation. Consumes the event queue two ways,
picked by where stdout goes (the sibling repos' treatment):

* a terminal: a pinned Rich progress bar over rounds (spinner, M-of-N,
  elapsed, current leader) with completed-match one-liners above it;
* a pipe or CI log: plain line-per-match output, no ANSI redraw noise.

Both end with the full statistical leaderboard and the report-page path.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from rich.console import Console
from rich.progress import (BarColumn, MofNCompleteColumn, Progress,
                           SpinnerColumn, TextColumn, TimeElapsedColumn)
from rich.table import Table

from .config import ArenaConfig
from .data.prompts import PromptItem
from .events import (MatchResolved, RoundVoided, StandingsUpdated,
                     TournamentEnded, TurnResolved)
from .tournament.driver import run_tournament


def _final_table(ended: TournamentEnded) -> Table:
    r: dict[str, Any] = ended.report or {}
    ci = r.get("elo_ci") or {}
    sc = r.get("elo_style_controlled") or {}
    thinking = r.get("thinking") or {}
    table = Table(title="FINAL STANDINGS")
    cols = (["#", "Model", "ELO"] + (["95% CI"] if ci else [])
            + (["len-ctrl"] if sc else []))
    for c in cols:
        table.add_column(c)
    ranked = sorted(ended.elo.items(), key=lambda kv: kv[1], reverse=True)
    for i, (name, elo) in enumerate(ranked, 1):
        badge = " 🧠" if thinking.get(name) else ""
        row = [str(i), f"{name}{badge}", f"{elo:.0f}"]
        if ci:
            lo, hi = ci.get(name, (elo, elo))
            row.append(f"{lo:.0f}–{hi:.0f}")
        if sc:
            row.append(f"{sc.get(name, elo):.0f}")
        table.add_row(*row)
    return table


def _print_summary(console: Console, ev: TournamentEnded) -> None:
    console.print(_final_table(ev))
    r = ev.report or {}
    if r.get("mean_agreement") is not None:
        console.print(f"mean inter-judge agreement: {r['mean_agreement']:.0%}")
    if r.get("length_coef") is not None:
        lean = "longer" if r["length_coef"] > 0 else "shorter"
        console.print(
            f"style control: jury length coefficient {r['length_coef']:+.2f} "
            f"(leaned {lean}); len-ctrl column prices it out"
        )
    tok = r.get("tokens") or {}
    if tok:
        console.print(
            f"tokens, models {tok.get('models_in', tok.get('warriors_in', 0)):,} in "
            f"/ {tok.get('models_out', tok.get('warriors_out', 0)):,} out"
            f" · jury {tok['judges_in']:,} in / {tok['judges_out']:,} out"
        )
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
    events: asyncio.Queue, *, console: Console, total_rounds: int
) -> None:
    """Drain the event queue until TournamentEnded.

    On a terminal, a pinned progress bar counts rounds while match results
    print above it; on a pipe, the plain line-per-match output survives
    grep and CI logs.
    """
    if not console.is_terminal:
        while True:
            ev = await events.get()
            if isinstance(ev, MatchResolved):
                console.print(_match_line(ev))
            elif isinstance(ev, RoundVoided):
                console.print(f"[yellow]{ev.match_id} round void, {ev.reason}[/yellow]")
            elif isinstance(ev, StandingsUpdated):
                console.print(f"[dim]match {ev.matches_done}/{ev.matches_total} done[/dim]")
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
            console=console,
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
                    progress.update(task, description=(
                        f"rounds · {ev.matches_done}/{ev.matches_total} matches"
                        + (f" · leader {leader} {ev.elo[leader]:.0f}" if leader else "")
                    ))
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
) -> dict[str, float]:
    console = Console(file=sys.stdout)
    events: asyncio.Queue = asyncio.Queue()

    from .preflight import call_counts

    counts = call_counts(cfg, prompts)
    total_rounds = counts.matches * counts.rounds_per_match

    printer_task = asyncio.create_task(
        consume_events(events, console=console, total_rounds=total_rounds)
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
