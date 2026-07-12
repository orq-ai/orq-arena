"""Post-demo call-to-action — the one moment a delighted viewer becomes a user."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Center, Vertical
from textual.screen import ModalScreen
from textual.widgets import Static


class CTAModalScreen(ModalScreen):
    BINDINGS = [
        ("enter,escape,space", "dismiss_modal", "Standings"),
        ("q", "quit_app", "Quit"),
    ]

    DEFAULT_CSS = """
    CTAModalScreen { align: center middle; background: $background 60%; }
    CTAModalScreen #cta-box {
        width: 64; height: auto; padding: 1 3;
        background: $panel; border: double $accent;
    }
    CTAModalScreen .cta-title { text-style: bold; color: $accent; }
    CTAModalScreen .cta-body { margin-top: 1; }
    CTAModalScreen .cta-hint { margin-top: 1; color: $text-muted; }
    """

    def compose(self) -> ComposeResult:
        with Center():
            with Vertical(id="cta-box"):
                yield Static("THAT WAS A RECORDING.", classes="cta-title")
                yield Static(
                    "Run it live with your own pool — every model on the orq.ai "
                    "router, judged by evaluatorq's pairwise jury:\n\n"
                    "  export ORQ_API_KEY=…   # get one at orq.ai\n"
                    "  uv run orq-arena run   # picker opens, choose any 2+ models",
                    classes="cta-body",
                )
                yield Static("ENTER see the standings · Q quit", classes="cta-hint")

    def action_dismiss_modal(self) -> None:
        self.app.pop_screen()

    def action_quit_app(self) -> None:
        self.app.exit()
