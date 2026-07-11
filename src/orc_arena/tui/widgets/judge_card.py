"""Judge card — compact verdict display with flip/abstain/stand-in badges."""

from __future__ import annotations

from textual.widgets import Static

_CUES = {"a": "→ A", "b": "→ B", "tie": "→ TIE", "abstain": "✕ abstain"}
_VERDICT_CLASSES = ("verdict-a", "verdict-b", "verdict-tie", "verdict-abstain")


class JudgeCard(Static):
    """One judge's reconciled vote + reasoning snippet."""

    DEFAULT_CSS = """
    JudgeCard {
        width: 1fr;
        height: 7;
        padding: 0 1;
        border: round $secondary;
        background: $panel-darken-1;
    }
    JudgeCard.waiting { opacity: 0.4; }
    JudgeCard.verdict-a { border: round $success; }
    JudgeCard.verdict-b { border: round $warning; }
    JudgeCard.verdict-tie { border: round $accent; }
    JudgeCard.verdict-abstain { border: round $error; }
    """

    def __init__(self, judge_name: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.judge_name = judge_name
        self._verdict = ""
        self._reasoning = ""
        self._flipped = False
        self._replacement = False
        self.add_class("waiting")
        self.update(self._render())

    def _render(self) -> str:
        name = self.judge_name + (" [dim](stand-in)[/dim]" if self._replacement else "")
        if not self._verdict:
            return f"[b]{name}[/b]\n[dim]deliberating…[/dim]"
        cue = _CUES.get(self._verdict.lower(), self._verdict)
        lines = [f"[b]{name}[/b]  {cue}"]
        if self._flipped:
            lines.append("[red]⚖ flipped when sides swapped — vote thrown out[/red]")
        reason = self._reasoning[:110] + ("…" if len(self._reasoning) > 110 else "")
        lines.append(f"[dim]{reason}[/dim]")
        return "\n".join(lines)

    def set_verdict(
        self, verdict: str, reasoning: str, *, flipped: bool = False, replacement: bool = False
    ) -> None:
        self._verdict = verdict
        self._reasoning = reasoning
        self._flipped = flipped
        self._replacement = replacement
        self.remove_class("waiting")
        for c in _VERDICT_CLASSES:
            self.remove_class(c)
        cls = f"verdict-{verdict.lower()}"
        if cls in _VERDICT_CLASSES:
            self.add_class(cls)
        self.update(self._render())

    def reset(self) -> None:
        self._verdict = ""
        self._reasoning = ""
        self._flipped = False
        self._replacement = False
        self.add_class("waiting")
        for c in _VERDICT_CLASSES:
            self.remove_class(c)
        self.update(self._render())
