"""Headless runner, the same tournament, no TUI, matches in parallel.

For CI/cron benchmark generation. Consumes the event queue with a Rich
printer: match results and live standings as one-liners, the full
statistical leaderboard at the end.
"""

from __future__ import annotations

import asyncio
from typing import Any

from rich.console import Console
from rich.table import Table

from .config import ArenaConfig
from .data.prompts import PromptItem
from .events import MatchResolved, RoundVoided, StandingsUpdated, TournamentEnded
from .tournament.driver import run_tournament


def _final_table(ended: TournamentEnded) -> Table:
    r: dict[str, Any] = ended.report or {}
    ci = r.get("elo_ci") or {}
    thinking = r.get("thinking") or {}
    table = Table(title="FINAL STANDINGS")
    cols = ["#", "Model", "ELO"] + (["95% CI"] if ci else [])
    for c in cols:
        table.add_column(c)
    ranked = sorted(ended.elo.items(), key=lambda kv: kv[1], reverse=True)
    for i, (name, elo) in enumerate(ranked, 1):
        badge = " 🧠" if thinking.get(name) else ""
        row = [str(i), f"{name}{badge}", f"{elo:.0f}"]
        if ci:
            lo, hi = ci.get(name, (elo, elo))
            row.append(f"{lo:.0f}–{hi:.0f}")
        table.add_row(*row)
    return table


async def run_headless(
    *,
    cfg: ArenaConfig,
    prompts: list[PromptItem],
    battle_log_path: str,
    preflight: dict | None = None,
) -> dict[str, float]:
    console = Console()
    cfg.match.verdict_hold_s = 0.0  # no screen to hold a beat for
    events: asyncio.Queue = asyncio.Queue()

    async def printer() -> None:
        while True:
            ev = await events.get()
            if isinstance(ev, MatchResolved):
                if ev.by == "draw":
                    console.print(f"[dim]{ev.match_id}[/dim] 🤝 draw")
                else:
                    console.print(f"[dim]{ev.match_id}[/dim] {ev.winner} beats {ev.loser} ({ev.by})")
            elif isinstance(ev, RoundVoided):
                console.print(f"[yellow]{ev.match_id} round void, {ev.reason}[/yellow]")
            elif isinstance(ev, StandingsUpdated):
                console.print(f"[dim]match {ev.matches_done}/{ev.matches_total} done[/dim]")
            elif isinstance(ev, TournamentEnded):
                console.print(_final_table(ev))
                r = ev.report or {}
                if r.get("mean_agreement") is not None:
                    console.print(f"mean inter-judge agreement: {r['mean_agreement']:.0%}")
                tok = r.get("tokens") or {}
                if tok:
                    console.print(
                        f"tokens, warriors {tok['warriors_in']:,} in / {tok['warriors_out']:,} out"
                        f" · jury {tok['judges_in']:,} in / {tok['judges_out']:,} out"
                    )
                console.print(f"battle log → {ev.battle_log_path}")
                return

    printer_task = asyncio.create_task(printer())
    elo = await run_tournament(
        cfg=cfg,
        prompts=prompts,
        battle_log_path=battle_log_path,
        events=events,
        concurrency=max(1, cfg.headless_concurrency),
        preflight=preflight,
    )
    await printer_task
    return elo
