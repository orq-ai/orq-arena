"""Textual App, wires the tournament engine to the TUI.

Flow:
  RUN PLAN screen (the one consent gate; skipped by -y)
    ↓ (ENTER)
  Fight screen + background tournament task
    ↓ TournamentEnded
  Leaderboard screen.
"""

from __future__ import annotations

import asyncio

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
from ..candidates import CandidateSpec
from ..tournament.driver import run_tournament
from .hp import VERDICT_HOLD_S, HPTracker
from .screens.fight import FightScreen
from .screens.leaderboard import LeaderboardScreen
from .screens.title import RunPlanScreen


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
        preflight: dict | None = None,
        dataset: dict | None = None,
        plan: dict | None = None,
        auto_start: bool = False,
    ) -> None:
        super().__init__()
        self.cfg = cfg
        self._preflight = preflight
        self._dataset = dataset
        self._prompts = prompts
        self._battle_log_path = battle_log_path
        self._plan = plan
        self._auto_start = auto_start
        self._events: asyncio.Queue[ArenaEvent] = asyncio.Queue()
        self._engine_task: asyncio.Task | None = None
        self._dispatcher_task: asyncio.Task | None = None
        self._by_name = {w.name: w for w in cfg.candidates}
        self._fight_screen: FightScreen | None = None
        # HP is a TUI-side show, derived from the judged verdicts.
        self._hp = HPTracker(
            starting_hp=cfg.match.starting_hp,
            damage_unanimous=cfg.match.damage_unanimous,
            damage_majority=cfg.match.damage_majority,
        )

    # ----- lifecycle -----

    def on_mount(self) -> None:
        from .theme import THEMES

        for theme in THEMES.values():
            self.register_theme(theme)
        # crt-neon stays registered (command palette / ORQ_ARENA_THEME) but
        # the brand look is the default.
        import os

        self.theme = os.environ.get("ORQ_ARENA_THEME") or "orq-arena"
        if self._auto_start:
            self.begin()  # -y: consent already given, straight to the fight
        elif self._plan is not None:
            self.push_screen(RunPlanScreen(self._plan))
        # else: bare app; a caller (tests, capture script) pushes its own screens

    def begin(self) -> None:
        """Called from RunPlanScreen when the user presses ENTER."""
        if self._engine_task is not None:
            return  # already running
        self._fight_screen = FightScreen([_judge_display(m) for m in self.cfg.judges])
        self.push_screen(self._fight_screen)
        self._dispatcher_task = asyncio.create_task(self._dispatch_events())
        self._engine_task = asyncio.create_task(self._run_live())

    async def _run_live(self) -> None:
        try:
            await run_tournament(
                cfg=self.cfg,
                prompts=self._prompts,
                battle_log_path=self._battle_log_path,
                events=self._events,
                preflight=self._preflight,
                dataset=self._dataset,
            )
        except Exception as exc:
            await self._events.put(
                TournamentEnded(champion="<error>", elo={}, battle_log_path=str(exc))
            )

    async def _dispatch_events(self) -> None:
        while True:
            ev = await self._events.get()
            self._handle_event(ev)
            # The engine never sleeps; verdict pacing lives here in the show.
            if isinstance(ev, TurnResolved):
                await asyncio.sleep(VERDICT_HOLD_S)
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
                return

    # ----- event handling -----

    def _handle_event(self, ev: ArenaEvent) -> None:
        fs = self._fight_screen
        if fs is None:
            return
        if isinstance(ev, StandingsUpdated):
            fs.set_standings(ev.elo, ev.matches_done, ev.matches_total)
        elif isinstance(ev, MatchStarted):
            # Fall back to a bare spec so a name the pool does not know
            # still renders instead of silently blanking the cards.
            w_a = self._by_name.get(ev.model_a) or CandidateSpec(model_id=ev.model_a)
            w_b = self._by_name.get(ev.model_b) or CandidateSpec(model_id=ev.model_b)
            self._hp.start_match()
            fs.start_match(
                w_a.name,
                w_a.model_id,
                w_a.emblem,
                w_a.thinking_enabled,
                w_b.name,
                w_b.model_id,
                w_b.emblem,
                w_b.thinking_enabled,
                self.cfg.match.starting_hp,
            )
        elif isinstance(ev, TurnPrompt):
            self._hp.clear_votes()  # defensive: fresh round, fresh vote buffer
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
            self._hp.note_vote(ev.verdict)
            fs.set_judge_verdict(
                ev.judge_name,
                ev.verdict,
                ev.reasoning,
                flipped=ev.flipped,
                replacement=ev.replacement,
            )
        elif isinstance(ev, RoundVoided):
            self._hp.clear_votes()
            fs.round_voided(ev.reason)
        elif isinstance(ev, TurnResolved):
            out = self._hp.resolve_turn(ev.majority)
            fs.apply_damage(out.hp_a, out.hp_b, ev.majority, out.damage, out.loser_side)
        elif isinstance(ev, MatchResolved):
            fs.match_resolved(ev.winner, ko=self._hp.ko_side != "none")
