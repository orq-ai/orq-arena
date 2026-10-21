"""Judge card, compact verdict display with flip/abstain/stand-in badges."""

from __future__ import annotations

from textual.widgets import Static

_CUES = {"a": "→ A", "b": "→ B", "tie": "→ TIE", "abstain": "✕ abstain"}
_VERDICT_CLASSES = ("verdict-a", "verdict-b", "verdict-tie", "verdict-abstain")
# (probability key, row label, fill colour): sides keep their theme colours.
_BAR_ROWS = (("A", "A", "$accent"), ("B", "B", "$primary"), ("tie", "=", "#ffd54d"))


def _bar(p: float, width: int = 22) -> str:
    filled = round(max(0.0, min(1.0, p)) * width)
    return "█" * filled + "░" * (width - filled)


class JudgeCard(Static):
    """One judge's reconciled vote + reasoning snippet, or P(A)/P(B)/P(tie) bars
    for a decision judge, which returns probabilities and no prose."""

    DEFAULT_CSS = """
    JudgeCard {
        width: 1fr;
        height: 7;
        padding: 0 1;
        border: round $secondary;
        background: $panel-darken-1;
    }
    JudgeCard.waiting { opacity: 0.4; }
    JudgeCard.stale { opacity: 0.55; }
    JudgeCard.verdict-a { border: round $accent; }
    JudgeCard.verdict-b { border: round $primary; }
    JudgeCard.verdict-tie { border: round #ffd54d; }
    JudgeCard.verdict-abstain { border: round $error; }
    """

    def __init__(self, judge_name: str, *, abstain_below: float | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.judge_name = judge_name
        self._abstain_below = abstain_below
        self._verdict = ""
        self._reasoning = ""
        self._probabilities: dict[str, float] | None = None
        self._flipped = False
        self._replacement = False
        self._skipped = False
        self.add_class("waiting")
        self.update(self._markup())

    def _markup(self) -> str:
        name = self.judge_name + (" [dim](stand-in)[/dim]" if self._replacement else "")
        if self._skipped:
            return f"[b]{name}[/b]\n[dim]skipped (gate)[/dim]"
        if not self._verdict:
            return f"[b]{name}[/b]\n[dim]deliberating…[/dim]"
        cue = _CUES.get(self._verdict.lower(), self._verdict)
        probs = self._probabilities
        if probs is not None and self._verdict in probs:
            cue += f"  {probs[self._verdict]:.2f}"
        lines = [f"[b]{name}[/b]  {cue}"]
        if probs is None:
            if self._flipped:
                lines.append("[red]⚖ flipped when sides swapped, vote thrown out[/red]")
            reason = self._reasoning[:110] + ("…" if len(self._reasoning) > 110 else "")
            lines.append(f"[dim]{reason}[/dim]")
            return "\n".join(lines)
        # Short flip line: the title already says abstain, and the bars need the rows.
        if self._flipped:
            lines.append("[red]⚖ flipped when sides swapped[/red]")
        for key, label, color in _BAR_ROWS:
            p = probs.get(key, 0.0)
            bar = _bar(p)
            filled = bar.count("█")
            lines.append(f"{label} [{color}]{bar[:filled]}[/][dim]{bar[filled:]}[/dim] {p:.0%}")
        top = max(probs.values())
        floor = self._abstain_below
        if self._verdict == "abstain" and not self._flipped and floor and top < floor:
            lines.append(f"[dim]top {top:.2f} under the {floor:.2f} floor[/dim]")
        return "\n".join(lines)

    def set_verdict(
        self,
        verdict: str,
        reasoning: str,
        *,
        probabilities: dict[str, float] | None = None,
        flipped: bool = False,
        replacement: bool = False,
    ) -> None:
        self._verdict = verdict
        self._reasoning = reasoning
        self._probabilities = probabilities
        self._flipped = flipped
        self._replacement = replacement
        self._skipped = False
        self.remove_class("waiting")
        self.remove_class("stale")
        for c in _VERDICT_CLASSES:
            self.remove_class(c)
        cls = f"verdict-{verdict.lower()}"
        if cls in _VERDICT_CLASSES:
            self.add_class(cls)
        self.update(self._markup())

    def skip(self) -> None:
        """The verifier gate decided this round, so no jury vote is coming."""
        self.reset()
        self._skipped = True
        self.update(self._markup())

    def mark_stale(self) -> None:
        """Keep last round's verdict visible but dimmed while the next streams."""
        if self._verdict:
            self.add_class("stale")
        else:
            self.reset()

    def reset(self) -> None:
        self.remove_class("stale")
        self._verdict = ""
        self._reasoning = ""
        self._probabilities = None
        self._flipped = False
        self._replacement = False
        self._skipped = False
        self.add_class("waiting")
        for c in _VERDICT_CLASSES:
            self.remove_class(c)
        self.update(self._markup())


class VerifierCard(JudgeCard):
    """The hidden-tests gate, shown next to the jury in harness mode.

    Reads ``waiting for both`` until both trials report, then either the side the
    tests picked or why the jury has to decide.
    """

    _note = "waiting for both"

    def __init__(self, **kwargs) -> None:
        super().__init__("verifier", **kwargs)

    def _markup(self) -> str:
        if self._verdict in ("A", "B"):
            cue = _CUES[self._verdict.lower()]
            return f"[b]verifier[/b]  {cue}  tests decide\n[dim]{self._reasoning[:110]}[/dim]"
        return f"[b]verifier[/b]\n[dim]{self._note}[/dim]"

    def note(self, text: str) -> None:
        """A non-verdict state: partial results, or a tie that goes to the jury."""
        self.reset()
        self._note = text
        self.update(self._markup())
        if text.startswith("waiting"):
            self.add_class("waiting")
        else:
            self.remove_class("waiting")

    def mark_stale(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._note = "waiting for both"
        super().reset()
