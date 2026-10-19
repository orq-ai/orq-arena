"""Post-run battle browser, step through every judged round.

Pushed from the leaderboard via ``B``. One round per page: prompt, both
responses, every judge's reconciled vote with flip/abstain badges and
reasoning, damage and HP deltas. The trust feature: spot-check the jury
before you believe the leaderboard.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.markup import escape
from textual.screen import Screen
from textual.widgets import Static

from ...data.schemas import BattleRecord
from ...judging import judge_labels, vote_probabilities

_VOTE_COLOR = {"A": "$accent", "B": "$primary", "tie": "#ffd54d"}
_DOSSIER_CHARS = 3000


def _solution_badge(sol: dict) -> Text:
    """'✓ hidden tests PASSED' plus the trial's counts, colour-coded."""
    passed = sol.get("passed")
    if passed is True:
        head = Text("✓ hidden tests PASSED", style="bold green")
    elif passed is False:
        head = Text("✗ hidden tests FAILED", style="bold red")
    else:
        head = Text("hidden tests did not run", style="bold yellow")
    if sol.get("reward") is not None:
        head.append(f"  (reward {sol['reward']:g})")
    facts = [
        f"{sol.get('steps', 0)} steps",
        f"{sol.get('commands', 0)} cmds",
        f"{sol.get('edits', 0)} edits",
    ]
    if sol.get("cost_usd") is not None:
        facts.append(f"${sol['cost_usd']:.2f}")
    if sol.get("exit_reason"):
        facts.append(f"exit: {sol['exit_reason']}")
    head.append("\n" + " · ".join(facts), style="dim")
    if sol.get("diff_stat"):
        head.append(f"\n{sol['diff_stat']}", style="dim")
    if sol.get("tests_edited"):
        head.append("\n⚠ tests/ edited", style="bold red")
    return head


def _response_view(label: str, text: str, sol: dict | None) -> Text | str:
    """A model round shows the answer; a harness round the badge and the judges' dossier."""
    if not sol:
        return f"{label}\n\n{text[:1500]}"
    view = Text(f"{label}\n")
    view.append_text(_solution_badge(sol))
    view.append(f"\n\n{text[:_DOSSIER_CHARS]}")
    return view


class BattleBrowserScreen(Screen):
    """Arrow-key pager over ``battles.jsonl`` records."""

    BINDINGS = [
        Binding("left,k", "prev", "Prev"),
        Binding("right,j,space", "next", "Next"),
        Binding("escape,b,q", "close", "Back"),
        ("s", "shot", "Screenshot"),
    ]

    DEFAULT_CSS = """
    BattleBrowserScreen { background: $surface; }
    BattleBrowserScreen #header {
        height: 2; padding: 0 2; background: $panel-darken-2;
        border-bottom: solid $accent;
    }
    BattleBrowserScreen #body { padding: 0 2; height: 1fr; }
    BattleBrowserScreen .block { margin-top: 1; }
    BattleBrowserScreen #responses { layout: grid; grid-size: 2; grid-gutter: 1; height: auto; }
    BattleBrowserScreen .resp { border: round $primary; padding: 0 1; height: auto; max-height: 30; }
    BattleBrowserScreen #resp-a { border: round $accent; }
    BattleBrowserScreen #resp-b { border: round $primary; }
    BattleBrowserScreen #hint { height: 1; padding: 0 2; color: $text-muted; }
    """

    def __init__(self, records: list[BattleRecord], **kwargs) -> None:
        super().__init__(**kwargs)
        self._records = records
        self._idx = 0
        self._labels = judge_labels(
            [str(v.get("model", "?")) for r in records for v in r.judge_votes]
        )
        self._header = Static("", markup=True)
        self._prompt = Static("", classes="block", markup=True)
        self._resp_a = Static("", id="resp-a", classes="resp", markup=False)
        self._resp_b = Static("", id="resp-b", classes="resp", markup=False)
        self._judges = Static("", classes="block", markup=True)
        self._outcome = Static("", classes="block", markup=True)

    def compose(self) -> ComposeResult:
        yield self._header
        with VerticalScroll(id="body"):
            yield self._prompt
            with Horizontal(id="responses"):
                yield self._resp_a
                yield self._resp_b
            yield self._judges
            yield self._outcome
        yield Static("←/→ page · ESC back · s screenshot", id="hint")

    def on_mount(self) -> None:
        self._show()

    def _show(self) -> None:
        if not self._records:
            self._header.update("[dim]no judged rounds in the log[/dim]")
            return
        r = self._records[self._idx]
        self._header.update(
            f"[b]ROUND {self._idx + 1}/{len(self._records)}[/b]   "
            f"[dim]{r.match_id} · round {r.round_number} · category {r.prompt_category or '-'}[/dim]"
        )
        self._prompt.update(f"[b]PROMPT[/b]\n{escape(r.prompt_text[:600])}")
        self._resp_a.update(_response_view(f"A · {r.model_a}", r.response_a, r.solution_a))
        self._resp_b.update(_response_view(f"B · {r.model_b}", r.response_b, r.solution_b))

        lines = ["[b]THE JURY[/b]"]
        for v in r.judge_votes:
            name = self._labels[str(v.get("model", "?"))]
            vote = v.get("vote")
            color = _VOTE_COLOR.get(str(vote), "red")
            badge = ""
            if v.get("flipped"):
                badge = " [red]⚖ flipped, vote thrown out[/red]"
            if v.get("replacement"):
                badge += " [dim](stand-in)[/dim]"
            probs = vote_probabilities(v)
            if probs is not None:
                detail = f"   A {probs['A']:.0%} · B {probs['B']:.0%} · tie {probs['tie']:.0%}"
                reason = ""
            else:
                detail = ""
                reason = str(v.get("explanation") or "")[:220]
            lines.append(
                f"  [b {color}]{escape(name)} → {vote or 'abstain'}[/]{detail}{badge}"
                + (f"\n    [dim]{escape(reason)}[/dim]" if reason else "")
            )
        self._judges.update("\n".join(lines))

        if r.error:
            outcome = f"[yellow]⚠ round void, {escape(r.error[:160])}[/yellow]"
        else:
            outcome = (
                f"verdict [b]{r.majority_verdict}[/b] → winner [b]{escape(r.winner)}[/b]"
                f"   [dim]tokens {r.tokens_a_out}/{r.tokens_b_out}"
                + (
                    f" · 🧠 {r.tokens_a_reasoning}/{r.tokens_b_reasoning}"
                    if r.tokens_a_reasoning or r.tokens_b_reasoning
                    else ""
                )
                + "[/dim]"
                + (
                    "   [dim]decided by the verifier gate, no jury call[/dim]"
                    if r.decided_by_gate
                    else ""
                )
            )
        self._outcome.update(outcome)
        self.query_one("#body", VerticalScroll).scroll_home(animate=False)

    def action_prev(self) -> None:
        if self._records:
            self._idx = (self._idx - 1) % len(self._records)
            self._show()

    def action_next(self) -> None:
        if self._records:
            self._idx = (self._idx + 1) % len(self._records)
            self._show()

    def action_close(self) -> None:
        self.app.pop_screen()

    def action_shot(self) -> None:
        path = self.app.save_screenshot()
        self.notify(f"saved {path}")
