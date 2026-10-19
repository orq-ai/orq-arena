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
from pathlib import Path

from textual.app import App

from ..candidates import CandidateSpec, HarnessCandidate
from ..config import ArenaConfig
from ..data.prompts import PromptItem
from ..events import (
    ArenaEvent,
    JudgeVerdictEvent,
    MatchResolved,
    MatchStarted,
    ResponseChunk,
    ResponseComplete,
    RoundVoided,
    SolutionReady,
    StandingsUpdated,
    ThinkingChunk,
    TournamentEnded,
    TrajectoryStep,
    TurnPrompt,
    TurnResolved,
)
from ..harness.runner import PATCH_FILE, cached_trial_dir, job_name
from ..judging import judge_labels
from ..tournament.driver import run_tournament
from .hp import VERDICT_HOLD_S, HPTracker
from .screens.fight import FightScreen
from .screens.leaderboard import LeaderboardScreen
from .screens.title import RunPlanScreen


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
        prompts: list[PromptItem],
        battle_log_path: str,
        preflight: dict | None = None,
        dataset: dict | None = None,
        prompts_path: str = "",
        plan: dict | None = None,
        auto_start: bool = False,
    ) -> None:
        super().__init__()
        self.cfg = cfg
        self._preflight = preflight
        self._dataset = dataset
        self._prompts_path = prompts_path
        self._prompts = prompts
        self._battle_log_path = battle_log_path
        self._plan = plan
        self._auto_start = auto_start
        self._events: asyncio.Queue[ArenaEvent] = asyncio.Queue()
        self._engine_task: asyncio.Task | None = None
        self._dispatcher_task: asyncio.Task | None = None
        self._by_name = {w.name: w for w in cfg.candidates}
        self._fight_screen: FightScreen | None = None
        # Full router id -> card label, once, so same-suffix judges keep two cards.
        self._judge_labels = judge_labels([*cfg.judges, *cfg.replacement_judges])
        self._judge_labels["verifier"] = "verifier"  # the hidden-tests gate, not a jury model
        # Harness mode: which candidate sits on each side, and the task on screen.
        self._side_cand: dict[str, object] = {}
        self._current_prompt = ""
        self._prompt_pos = {p.text: (i, p) for i, p in enumerate(prompts, 1)}
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
        self._fight_screen = FightScreen(
            [self._judge_labels[m] for m in self.cfg.judges],
            abstain_below=self.cfg.judge_abstain_below,
            harness=self.cfg.has_harness,
            verifier_gate=self.cfg.verifier_gate,
        )
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
                prompts_path=self._prompts_path,
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

    # ----- harness helpers -----

    def _candidate(self, name: str) -> CandidateSpec | HarnessCandidate:
        """The pool entry for a name; a model name the pool does not know still
        renders (a bare spec) instead of silently blanking the cards."""
        known = self._by_name.get(name)
        if known is not None:
            return known
        if self.cfg.has_harness:
            # Never mint a model spec for a harness name; show the bare name.
            return HarnessCandidate.model_construct(
                kind="harness", name=name, agent="?", model_id=name
            )
        return CandidateSpec(model_id=name)

    def _task_line(self, prompt: str) -> str:
        """'TASK 2/8 · fix-git · easy · 15m' from the prompt row's metadata."""
        if not self.cfg.has_harness:
            return ""
        pos = self._prompt_pos.get(prompt)
        if pos is None:
            return ""
        k, item = pos
        meta = item.metadata or {}
        parts = [f"TASK {k}/{len(self._prompts)}"]
        if meta.get("task_name"):
            parts.append(str(meta["task_name"]))
        difficulty = meta.get("difficulty") or item.category
        if difficulty and difficulty != "general":
            parts.append(str(difficulty))
        timeout = meta.get("timeout_sec")
        if isinstance(timeout, (int, float)) and timeout > 0:
            parts.append(f"{round(timeout / 60)}m")
        return " · ".join(parts)

    def _read_diff(self, side: str) -> str:
        """The finished trial's workspace diff, from the cache dir the runner wrote it to."""
        cand = self._side_cand.get(side)
        if not isinstance(cand, HarnessCandidate) or not self._current_prompt:
            return ""
        trials = Path(self.cfg.harness.trials_dir or f"{self._battle_log_path}.trials")
        try:
            trial = cached_trial_dir(trials, job_name(self._current_prompt, cand.candidate_id))
            patch = trial / PATCH_FILE if trial else None
            return patch.read_text(encoding="utf-8") if patch and patch.exists() else ""
        except OSError:
            return ""

    # ----- event handling -----

    def _handle_event(self, ev: ArenaEvent) -> None:
        fs = self._fight_screen
        if fs is None:
            return
        if isinstance(ev, StandingsUpdated):
            fs.set_standings(ev.elo, ev.matches_done, ev.matches_total)
        elif isinstance(ev, MatchStarted):
            w_a = self._candidate(ev.model_a)
            w_b = self._candidate(ev.model_b)
            self._side_cand = {"a": w_a, "b": w_b}
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
                label_a=w_a.label() if isinstance(w_a, HarnessCandidate) else "",
                label_b=w_b.label() if isinstance(w_b, HarnessCandidate) else "",
            )
        elif isinstance(ev, TurnPrompt):
            self._hp.clear_votes()  # defensive: fresh round, fresh vote buffer
            self._current_prompt = ev.prompt
            fs.set_prompt(ev.round_number, ev.prompt, task=self._task_line(ev.prompt))
        elif isinstance(ev, TrajectoryStep):
            fs.add_step(ev)
        elif isinstance(ev, SolutionReady):
            fs.solution_ready(ev, self._read_diff(ev.side))
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
                self._judge_labels.get(ev.judge_name, ev.judge_name),
                ev.verdict,
                ev.reasoning,
                probabilities=ev.probabilities,
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
