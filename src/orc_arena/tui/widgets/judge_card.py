"""Judge card — compact verdict display that flips in as a judge returns."""

from __future__ import annotations

from textual.reactive import reactive
from textual.widgets import Static


class JudgeCard(Static):
    """One judge's verdict + reasoning snippet."""

    DEFAULT_CSS = """
    JudgeCard {
        width: 1fr;
        height: 7;
        padding: 0 1;
        border: round $secondary;
        background: $panel-darken-1;
    }
    JudgeCard.waiting {
        opacity: 0.4;
    }
    JudgeCard.verdict-a {
        border: round $success;
    }
    JudgeCard.verdict-b {
        border: round $warning;
    }
    JudgeCard.verdict-tie {
        border: round $accent;
    }
    """

    judge_name: reactive[str] = reactive("")
    verdict: reactive[str] = reactive("")
    reasoning: reactive[str] = reactive("")

    def __init__(self, judge_name: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.judge_name = judge_name
        self.add_class("waiting")
        self.update(self._render())

    def _render(self) -> str:
        if not self.verdict:
            return f"[b]{self.judge_name}[/b]\n[dim]waiting...[/dim]"
        cue = {"A": "→ A", "B": "→ B", "TIE": "→ TIE"}.get(self.verdict, self.verdict)
        reason = self.reasoning[:120] + ("..." if len(self.reasoning) > 120 else "")
        return f"[b]{self.judge_name}[/b]  {cue}\n[dim]{reason}[/dim]"

    def set_verdict(self, verdict: str, reasoning: str) -> None:
        self.verdict = verdict
        self.reasoning = reasoning
        self.remove_class("waiting")
        for c in ("verdict-a", "verdict-b", "verdict-tie"):
            self.remove_class(c)
        self.add_class(f"verdict-{verdict.lower()}")
        self.update(self._render())

    def reset(self) -> None:
        self.verdict = ""
        self.reasoning = ""
        self.add_class("waiting")
        for c in ("verdict-a", "verdict-b", "verdict-tie"):
            self.remove_class(c)
        self.update(self._render())
