"""Prompt panel — shows the current turn's prompt."""

from __future__ import annotations

from textual.widgets import Static


class PromptPanel(Static):
    DEFAULT_CSS = """
    PromptPanel {
        height: 4;
        padding: 0 1;
        border: round $accent;
        background: $panel;
        color: $text;
    }
    """

    def set_prompt(self, round_number: int, text: str) -> None:
        snippet = text if len(text) <= 300 else text[:300] + "..."
        self.update(f"[b]Round {round_number}[/b]  [dim]prompt[/dim]\n{snippet}")

    def clear_prompt(self) -> None:
        self.update("[dim]waiting for next round...[/dim]")
