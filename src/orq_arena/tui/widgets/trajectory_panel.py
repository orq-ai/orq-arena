"""Trajectory panel: a coding agent's steps streaming live, one pane per side.

The harness-mode counterpart of ``ResponsePanel``. Append-only (a RichLog never
re-renders what it already wrote), so a 100-step trajectory costs the same per
step as the first one. ``d`` swaps the log for the workspace diff, ``t`` swaps
it back, ``f`` pins the view to the newest step.
"""

from __future__ import annotations

import re

from rich.console import RenderableType
from rich.syntax import Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.markup import escape
from textual.widgets import RichLog, Static

from ...events import SolutionReady, TrajectoryStep

OBSERVATION_LINES = 6
MAX_LINES = 2000
_TESTS_PATH = re.compile(r"(^|/)tests?/")


def _fmt_duration(ms: int) -> str:
    secs = max(0, ms) // 1000
    mins, s = divmod(secs, 60)
    return f"{mins}m{s:02d}s" if mins else f"{s}s"


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else many or one + 's'}"


def _diff(body: str) -> Syntax:
    # Transparent background so the panel colour shows through.
    return Syntax(body, "diff", theme="ansi_dark", background_color="default", word_wrap=True)


class TrajectoryPanel(Vertical):
    """Header counts, an append-only step log, and a verdict footer."""

    DEFAULT_CSS = """
    TrajectoryPanel {
        height: 1fr;
        border: round $primary;
        background: $panel-darken-2;
    }
    TrajectoryPanel.side-a { border: round $accent; }
    TrajectoryPanel.side-b { border: round $primary; }
    TrajectoryPanel #traj-header {
        height: 1;
        padding: 0 1;
        color: $text-muted;
        background: $panel-darken-3;
    }
    TrajectoryPanel #traj-log { height: 1fr; padding: 0 1; background: transparent; }
    TrajectoryPanel #traj-footer {
        height: auto;
        max-height: 5;
        padding: 0 1;
        color: $text-muted;
        background: $panel-darken-3;
    }
    """

    def __init__(self, side: str = "a", **kwargs) -> None:
        super().__init__(**kwargs)
        self.add_class(f"side-{side}")
        self.side = side
        self._header = Static("", id="traj-header")
        self._log = RichLog(
            id="traj-log", wrap=True, markup=False, highlight=False, max_lines=MAX_LINES
        )
        self._footer = Static("", id="traj-footer")
        self._follow = True
        self._view = "trajectory"  # or "diff"
        self._lines: list[RenderableType] = []
        self._diff_text = ""
        self._solution: SolutionReady | None = None
        self._error = ""
        self._reset_counts()

    def _reset_counts(self) -> None:
        self._steps = 0
        self._cmds = 0
        self._edits = 0
        self._t_ms = 0
        self._replay = False
        self._started = False

    def compose(self) -> ComposeResult:
        yield self._header
        yield self._log
        yield self._footer

    def on_mount(self) -> None:
        self._log.auto_scroll = self._follow
        self._render_header()
        self._render_footer()

    # --- state transitions -------------------------------------------------

    def reset(self) -> None:
        """New round: empty log, zero counts, back to the trajectory view."""
        self._reset_counts()
        self._lines = []
        self._diff_text = ""
        self._solution = None
        self._error = ""
        self._view = "trajectory"
        self._log.clear()
        self._render_header()
        self._render_footer()

    def add_step(self, ev: TrajectoryStep) -> None:
        self._started = True
        self._t_ms = max(self._t_ms, ev.t_ms)
        self._replay = self._replay or ev.replay
        if ev.kind in ("command", "test"):
            self._cmds += 1
        elif ev.kind == "edit":
            self._edits += 1
        if ev.kind not in ("observation", "log", "done"):
            self._steps += 1
        for renderable in self._render_step(ev):
            self._append(renderable)
        self._render_header()
        self._render_footer()

    def solution(self, ev: SolutionReady) -> None:
        """The trial finished: final counts, cost, and the hidden-tests verdict."""
        self._solution = ev
        self._started = True
        self._replay = self._replay or ev.replay
        self._steps, self._cmds, self._edits = ev.steps, ev.commands, ev.edits
        self._t_ms = max(self._t_ms, ev.duration_ms)
        self._render_header()
        self._render_footer()
        if self._view == "diff":
            self._show_diff()

    def fail(self, error: str) -> None:
        """The trial produced no result (the round is void)."""
        self._error = error
        self._render_footer()

    def set_diff(self, text: str) -> None:
        self._diff_text = text
        if self._view == "diff":
            self._show_diff()

    def toggle_diff(self) -> None:
        if self._view == "diff":
            self.show_trajectory()
            return
        self._view = "diff"
        self._show_diff()
        self._render_header()
        self._render_footer()

    def show_trajectory(self) -> None:
        if self._view == "trajectory":
            return
        self._view = "trajectory"
        self._log.clear()
        for renderable in self._lines:
            self._log.write(renderable)
        self._render_header()
        self._render_footer()

    def toggle_follow(self) -> None:
        self._follow = not self._follow
        self._log.auto_scroll = self._follow
        if self._follow:
            self._log.scroll_end(animate=False)
        self._render_footer()

    # --- rendering ---------------------------------------------------------

    def _append(self, renderable: RenderableType) -> None:
        self._lines.append(renderable)
        if len(self._lines) > MAX_LINES:
            del self._lines[: len(self._lines) - MAX_LINES]
        if self._view == "trajectory":
            self._log.write(renderable)

    def _render_step(self, ev: TrajectoryStep) -> list[RenderableType]:
        kind = ev.kind
        if kind in ("command", "test"):
            title = ev.title if ev.title.startswith("$") else f"$ {ev.title}"
            text = Text(title, style="bold")
            if kind == "test":
                text.append("   ◂ test", style="bold yellow")
            return [text]
        if kind == "edit":
            head = Text(f"✎ edit {ev.title}", style="bold")
            if _TESTS_PATH.search(ev.title):
                head.append("   ⚠ tests/ edited", style="bold red")
            return [head, _diff(ev.body)] if ev.body.strip() else [head]
        if kind == "read":
            return [Text(f"▸ {ev.title}", style="dim")]
        if kind == "thinking":
            return [Text(f"💭 {(ev.body or ev.title).strip()}", style="dim italic")]
        if kind == "observation":
            lines = (ev.body or ev.title).splitlines() or [""]
            shown = [f"  {line}" for line in lines[:OBSERVATION_LINES]]
            if len(lines) > OBSERVATION_LINES:
                shown.append(f"  ... ({OBSERVATION_LINES} of {len(lines)} lines)")
            return [Text("\n".join(shown), style="dim")]
        if kind == "done":
            return [Text(f"◼ {ev.title or ev.body}", style="bold")]
        if kind == "log":
            return [Text(f"· {(ev.title or ev.body)[:200]}", style="dim")]
        # message
        body = f"\n{ev.body}" if ev.body and ev.body != ev.title else ""
        return [Text(f"{ev.title}{body}")]

    def _show_diff(self) -> None:
        self._log.clear()
        sol = self._solution
        if self._diff_text.strip():
            self._log.write(_diff(self._diff_text))
        else:
            note = "no diff text available for this trial"
            if sol is None:
                note = "the diff is collected when the trial finishes"
            self._log.write(Text(note, style="dim"))
            if sol and sol.diff_stat:
                self._log.write(Text(sol.diff_stat, style="dim"))
            if sol and sol.tests_edited:
                self._log.write(Text("⚠ tests/ edited", style="bold red"))

    def _render_header(self) -> None:
        sol = self._solution
        if self._view == "diff":
            stat = sol.diff_stat if sol and sol.diff_stat else "no stat yet"
            self._header.update(f"DIFF · {stat}")
            return
        if not self._started:
            self._header.update("waiting for the agent…")
            return
        parts = [
            _plural(self._steps, "step"),
            _plural(self._cmds, "cmd"),
            _plural(self._edits, "edit"),
            _fmt_duration(self._t_ms),
        ]
        if sol is not None and sol.cost_usd is not None:
            parts.append(f"${sol.cost_usd:.2f}")
        if self._replay:
            parts.append("⟲ CACHED")
        elif sol is None:
            parts.append("LIVE")
        self._header.update(" · ".join(parts))

    def _render_footer(self) -> None:
        follow = f"follow {'ON' if self._follow else 'OFF'}"
        if self._view == "diff":
            self._footer.update(f"t trajectory · {follow}")
            return
        sol = self._solution
        if sol is None and self._error:
            self._footer.update(f"[red]✕ trial failed: {escape(self._error[:120])}[/red]")
            return
        if sol is None:
            state = "▶ running" if self._started else "… queued"
            self._footer.update(f"{state}  ·  {follow}")
            return
        self._footer.update("\n".join(self._solution_lines(sol)))

    def _solution_lines(self, sol: SolutionReady) -> list[str]:
        if sol.error:
            return [f"[red]✕ trial failed: {escape(sol.error[:120])}[/red]"]
        exit_text = {
            "finished": "agent finished",
            "max_turns": "max_turns reached",
            "timeout": "agent timeout",
            "error": "agent error",
        }.get(sol.exit_reason, sol.exit_reason or "agent stopped")
        done = f"◼ done: {exit_text}"
        if sol.cost_usd is not None:
            done += f" · ${sol.cost_usd:.2f}"
        lines = [done]
        reward = f"  (reward {sol.reward:g})" if sol.reward is not None else ""
        if sol.passed is True:
            lines.append(f"[b green]✓ hidden tests PASSED[/b green]{reward}")
        elif sol.passed is False:
            if sol.exit_reason == "timeout":
                lines.append(f"[b red]⏱ timeout, hidden tests FAILED[/b red]{reward}")
            else:
                lines.append(f"[b red]✗ hidden tests FAILED[/b red]{reward}")
        else:
            lines.append("[yellow]hidden tests did not run[/yellow]")
        extra = escape(sol.diff_stat)
        if sol.tests_edited:
            extra = f"{extra}  [b red]⚠ tests/ edited[/b red]".strip()
        if extra:
            lines.append(extra)
        return lines
