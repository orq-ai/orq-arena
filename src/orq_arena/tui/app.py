"""Textual App, wires the tournament engine to the TUI.

Flow:
  Title screen
    ↓ (ENTER)
  Fight screen + background tournament task
    ↓ TournamentEnded
  Leaderboard screen.

Two modes:
  live   = cfg+prompts, runs ``run_tournament``
  replay = loads a JSON fixture and re-emits recorded events (``orq-arena demo``).
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
    JudgeVerdictEvent,
    MatchResolved,
    MatchStarted,
    ResponseChunk,
    ResponseComplete,
    RoundVoided,
    StandingsUpdated,
    ThinkingChunk,
    TournamentEnded,
    TurnPrompt,
    TurnResolved,
)
from ..orcs.roster import WarriorSpec, assign_warriors
from ..tournament.driver import run_tournament
from .screens.cta_modal import CTAModalScreen
from .screens.fight import FightScreen
from .screens.leaderboard import LeaderboardScreen
from .screens.roster_select import RosterSelectScreen
from .screens.title import TitleScreen


def _judge_display(model_id: str) -> str:
    return model_id.split("/")[-1]


class ArenaApp(App):
    """Main Textual app."""

    TITLE = "orq-arena"
    BINDINGS = [("q", "quit", "Quit"), ("s", "shot", "Screenshot")]

    def action_shot(self) -> None:
        path = self.save_screenshot()
        self.notify(f"saved {path}")

    def __init__(
        self,
        *,
        cfg: ArenaConfig,
        prompts: list[str],
        battle_log_path: str,
        live: bool = True,
        fixture: str | None = None,
        preflight: dict | None = None,
        pick_roster: bool = False,
    ) -> None:
        super().__init__()
        self.cfg = cfg
        self._preflight = preflight
        self._pick_roster = pick_roster
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
        from .theme import CRT_THEME

        self.register_theme(CRT_THEME)
        self.theme = "crt-neon"
        if self._pick_roster:
            self.push_screen(RosterSelectScreen(self.cfg, prompt_count=len(self._prompts)))
        else:
            self.push_screen(TitleScreen())

    def on_roster_select_screen_roster_selected(
        self, message: RosterSelectScreen.RosterSelected
    ) -> None:
        self.cfg.warriors = assign_warriors(message.model_ids, self.cfg.warriors)
        self._by_name = {w.orc_name: w for w in self.cfg.warriors}
        self.pop_screen()
        self.run_worker(self._probe_then_begin(), exclusive=True)

    def on_roster_select_screen_load_failed(
        self, message: RosterSelectScreen.LoadFailed
    ) -> None:
        self.notify(f"catalog load failed: {message.reason}", severity="warning")
        self.pop_screen()
        self.push_screen(TitleScreen())

    async def _probe_then_begin(self) -> None:
        """Picker path: the CLI preflight didn't run, so probe here."""
        from ..preflight import judge_family_overlaps

        overlap = judge_family_overlaps(list(self.cfg.judges), self.cfg.warriors)
        if overlap:
            self.notify(
                f"⚖ judge/contestant family overlap: {', '.join(overlap)}. "
                "Self-preference bias survives seat swapping; prefer judges "
                "from families outside the pool.",
                severity="warning", timeout=10,
            )
        if self.cfg.preflight.thinking_probe:
            from ..preflight import surprises, thinking_probe

            self.notify("probing pool for vendor-default thinking…", timeout=4)
            try:
                probe = await thinking_probe(self.cfg)
                self._preflight = {**(self._preflight or {}), "thinking_probe": probe}
                odd = surprises(probe)
                if odd:
                    self.notify(
                        f"🧠 thinks despite config: {', '.join(odd)}, ranking will be footnoted",
                        severity="warning", timeout=8,
                    )
            except Exception as exc:
                self.notify(f"thinking probe failed: {exc}", severity="warning")
        self.begin()

    def begin(self) -> None:
        """Called from TitleScreen when the user presses ENTER."""
        if self._engine_task is not None:
            return  # already running
        self._fight_screen = FightScreen([_judge_display(m) for m in self.cfg.judges])
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
                preflight=self._preflight,
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
                        report=ev.report,
                        cfg=self.cfg,
                    )
                )
                if not self._live:
                    self.push_screen(CTAModalScreen())
                return

    # ----- event handling -----

    def _handle_event(self, ev: ArenaEvent) -> None:
        fs = self._fight_screen
        if fs is None:
            return
        if isinstance(ev, StandingsUpdated):
            fs.set_standings(ev.elo, ev.matches_done, ev.matches_total)
        elif isinstance(ev, MatchStarted):
            # Fall back to a bare spec so a name the roster doesn't know
            # (e.g. a fixture recorded with another pool) still renders
            # instead of silently blanking the cards.
            w_a = self._by_name.get(ev.warrior_a) or WarriorSpec(model_id=ev.warrior_a)
            w_b = self._by_name.get(ev.warrior_b) or WarriorSpec(model_id=ev.warrior_b)
            fs.start_match(
                w_a.orc_name, w_a.model_id, w_a.emblem, w_a.thinking_enabled,
                w_b.orc_name, w_b.model_id, w_b.emblem, w_b.thinking_enabled,
                self.cfg.match.starting_hp,
            )
        elif isinstance(ev, TurnPrompt):
            fs.set_prompt(ev.round_number, ev.prompt)
        elif isinstance(ev, ResponseChunk):
            fs.append_response(ev.side, ev.text)
        elif isinstance(ev, ThinkingChunk):
            fs.append_thinking(ev.side, ev.text)
        elif isinstance(ev, ResponseComplete):
            fs.response_complete(
                ev.side,
                tokens_out=ev.tokens_out,
                reasoning_tokens=ev.reasoning_tokens,
                finish_reason=ev.finish_reason,
                error=ev.error,
            )
        elif isinstance(ev, JudgeVerdictEvent):
            fs.set_judge_verdict(
                ev.judge_name, ev.verdict, ev.reasoning,
                flipped=ev.flipped, replacement=ev.replacement,
            )
        elif isinstance(ev, RoundVoided):
            fs.round_voided(ev.reason)
        elif isinstance(ev, TurnResolved):
            fs.apply_damage(ev.hp_a, ev.hp_b, ev.majority, ev.damage_dealt, ev.loser_side)
        elif isinstance(ev, MatchResolved):
            fs.match_resolved(ev.winner, ev.by)


def _event_from_dict(raw: dict[str, Any]) -> ArenaEvent:
    kind = raw["type"]
    mapping = {
        "standings_updated": StandingsUpdated,
        "match_started": MatchStarted,
        "turn_prompt": TurnPrompt,
        "response_chunk": ResponseChunk,
        "thinking_chunk": ThinkingChunk,
        "response_complete": ResponseComplete,
        "judge_verdict": JudgeVerdictEvent,
        "round_voided": RoundVoided,
        "turn_resolved": TurnResolved,
        "match_resolved": MatchResolved,
        "tournament_ended": TournamentEnded,
    }
    cls = mapping.get(kind)
    if cls is None:
        raise ValueError(f"Unknown event kind: {kind}")
    return cls.model_validate(raw)
