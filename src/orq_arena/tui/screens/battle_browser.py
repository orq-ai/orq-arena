"""Post-run battle browser, step through every judged round.

Pushed from the leaderboard via ``B``. One round per page: prompt, both
responses, every judge's reconciled vote with flip/abstain badges and
reasoning, damage and HP deltas. The trust feature: spot-check the jury
before you believe the leaderboard.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.markup import escape
from textual.screen import Screen
from textual.widgets import Static

from ...data.schemas import BattleRecord

_VOTE_COLOR = {"A": "#ff3bd4", "B": "#00e5ff", "tie": "#ffd54d"}


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
    BattleBrowserScreen .resp { border: round $primary; padding: 0 1; height: auto; max-height: 18; }
    BattleBrowserScreen #resp-a { border: round $accent; }
    BattleBrowserScreen #resp-b { border: round $primary; }
    BattleBrowserScreen #hint { height: 1; padding: 0 2; color: $text-muted; }
    """

    def __init__(self, records: list[BattleRecord], **kwargs) -> None:
        super().__init__(**kwargs)
        self._records = records
        self._idx = 0
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
        self._resp_a.update(f"A · {r.model_a}\n\n{r.response_a[:1500]}")
        self._resp_b.update(f"B · {r.model_b}\n\n{r.response_b[:1500]}")

        lines = ["[b]THE JURY[/b]"]
        for v in r.judge_votes:
            name = str(v.get("model", "?")).split("/")[-1]
            vote = v.get("vote")
            color = _VOTE_COLOR.get(str(vote), "red")
            badge = ""
            if v.get("flipped"):
                badge = " [red]⚖ flipped, vote thrown out[/red]"
            if v.get("replacement"):
                badge += " [dim](stand-in)[/dim]"
            reason = str(v.get("explanation") or "")[:220]
            lines.append(
                f"  [b {color}]{escape(name)} → {vote or 'abstain'}[/b {color}]{badge}"
                + (f"\n    [dim]{escape(reason)}[/dim]" if reason else "")
            )
        self._judges.update("\n".join(lines))

        if r.error:
            outcome = f"[yellow]⚠ round void, {escape(r.error[:160])}[/yellow]"
        else:
            outcome = (
                f"verdict [b]{r.majority_verdict}[/b] → winner [b]{escape(r.winner)}[/b]"
                f"   [dim]tokens {r.tokens_a_out}/{r.tokens_b_out}"
                + (f" · 🧠 {r.tokens_a_reasoning}/{r.tokens_b_reasoning}"
                   if r.tokens_a_reasoning or r.tokens_b_reasoning else "")
                + "[/dim]"
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
