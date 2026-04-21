"""Textual App — wires the tournament engine to the TUI.

Flow:
  Title screen
    ↓ (ENTER)
  Fight screen + background tournament task
    (bracket strip + warrior cards re-render for each match)
    ↓ TournamentEnded
  Leaderboard screen.

Two modes:
  live   = cfg+prompts, runs ``run_tournament``
  replay = loads a JSON fixture and re-emits recorded events (``orc-arena demo``).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from textual.app import App

from ..config import ArenaConfig
from ..events import (
    ArenaEvent,
    BracketUpdated,
    JudgeVerdictEvent,
    MatchResolved,
    MatchStarted,
    ResponseChunk,
    TournamentEnded,
    TurnPrompt,
    TurnResolved,
)
from ..tournament.driver import run_tournament
from .screens.fight import FightScreen
from .screens.leaderboard import LeaderboardScreen
from .screens.title import TitleScreen


class ArenaApp(App):
    """Main Textual app."""

    TITLE = "orc-arena"
    BINDINGS = [("q", "quit", "Quit")]

    def __init__(
        self,
        *,
        cfg: ArenaConfig,
        prompts: list[str],
        battle_log_path: str,
        live: bool = True,
        fixture: str | None = None,
    ) -> None:
        super().__init__()
        self.cfg = cfg
        self._prompts = prompts
        self._battle_log_path = battle_log_path
        self._live = live
        self._fixture = fixture
        self._events: asyncio.Queue[ArenaEvent] = asyncio.Queue()
        self._engine_task: asyncio.Task | None = None
        self._dispatcher_task: asyncio.Task | None = None
        self._by_name = {w.orc_name: w for w in cfg.warriors}
        self._fight_screen: FightScreen | None = None

    # ----- lifecycle -----

    def on_mount(self) -> None:
        self.push_screen(TitleScreen())

    def begin(self) -> None:
        """Called from TitleScreen when the user presses ENTER.

        Pushes the Fight screen and kicks off tournament + event dispatcher.
        """
        if self._engine_task is not None:
            return  # already running
        self._fight_screen = FightScreen([j.name for j in self.cfg.judges])
        self.push_screen(self._fight_screen)
        self._dispatcher_task = asyncio.create_task(self._dispatch_events())
        if self._live:
            self._engine_task = asyncio.create_task(self._run_live())
        else:
            self._engine_task = asyncio.create_task(self._replay_fixture())

    async def _run_live(self) -> None:
        try:
            await run_tournament(
                cfg=self.cfg,
                prompts=self._prompts,
                battle_log_path=self._battle_log_path,
                events=self._events,
            )
        except Exception as exc:
            await self._events.put(
                TournamentEnded(champion="<error>", elo={}, battle_log_path=str(exc))
            )

    async def _replay_fixture(self) -> None:
        assert self._fixture is not None
        events = json.loads(Path(self._fixture).read_text())
        for raw in events:
            delay = raw.pop("_delay", 0.02)
            await asyncio.sleep(delay)
            try:
                ev = _event_from_dict(raw)
            except Exception:
                continue
            await self._events.put(ev)

    async def _dispatch_events(self) -> None:
        while True:
            ev = await self._events.get()
            self._handle_event(ev)
            if isinstance(ev, TournamentEnded):
                self.push_screen(
                    LeaderboardScreen(
                        elo=ev.elo,
                        champion=ev.champion,
                        log_path=ev.battle_log_path,
                    )
                )
                return

    # ----- event handling -----

    def _handle_event(self, ev: ArenaEvent) -> None:
        fs = self._fight_screen
        if fs is None:
            return
        if isinstance(ev, BracketUpdated):
            fs.set_bracket_strip(_compact_bracket(ev.rounds))
        elif isinstance(ev, MatchStarted):
            w_a = self._by_name.get(ev.warrior_a)
            w_b = self._by_name.get(ev.warrior_b)
            if w_a and w_b:
                fs.start_match(
                    w_a.orc_name, w_a.model_id, w_a.emblem,
                    w_b.orc_name, w_b.model_id, w_b.emblem,
                    self.cfg.match.starting_hp,
                )
        elif isinstance(ev, TurnPrompt):
            fs.set_prompt(ev.round_number, ev.prompt)
        elif isinstance(ev, ResponseChunk):
            fs.append_response(ev.side, ev.text)
        elif isinstance(ev, JudgeVerdictEvent):
            fs.set_judge_verdict(ev.judge_name, ev.verdict, ev.reasoning)
        elif isinstance(ev, TurnResolved):
            fs.apply_damage(ev.hp_a, ev.hp_b, ev.majority, ev.damage_dealt)
        elif isinstance(ev, MatchResolved):
            fs.match_resolved(ev.winner, ev.by)


def _compact_bracket(rounds: list[list[list[str | None]]]) -> str:
    if not rounds:
        return "[dim]bracket[/dim]"
    headers = ["QF", "SF", "F"]
    parts: list[str] = []
    for idx, rnd in enumerate(rounds):
        names = []
        for pair in rnd:
            a = (pair[0] if len(pair) > 0 else None) or "?"
            b = (pair[1] if len(pair) > 1 else None) or "?"
            names.append(f"{a[:10]} vs {b[:10]}")
        hdr = headers[idx] if idx < len(headers) else f"R{idx+1}"
        parts.append(f"[b]{hdr}[/b] " + "  ".join(names))
    return "   ".join(parts)


def _event_from_dict(raw: dict[str, Any]) -> ArenaEvent:
    kind = raw["type"]
    mapping = {
        "bracket_updated": BracketUpdated,
        "match_started": MatchStarted,
        "turn_prompt": TurnPrompt,
        "response_chunk": ResponseChunk,
        "judge_verdict": JudgeVerdictEvent,
        "turn_resolved": TurnResolved,
        "match_resolved": MatchResolved,
        "tournament_ended": TournamentEnded,
    }
    cls = mapping.get(kind)
    if cls is None:
        raise ValueError(f"Unknown event kind: {kind}")
    return cls.model_validate(raw)
