"""Title screen — ASCII banner. ENTER triggers the tournament."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Center, Middle
from textual.screen import Screen
from textual.widgets import Static

BANNER = r"""
   ____  ____   ___      _    ____  _____ _   _    _
  / __ \|  _ \ / __|    / \  |  _ \| ____| \ | |  / \
 | |  | | |_) | |      / _ \ | |_) |  _| |  \| | / _ \
 | |__| |  _ <| |___  / ___ \|  _ <| |___| |\  |/ ___ \
  \____/|_| \_\\\____|/_/   \_\_| \_\_____|_| \_/_/   \_\

         ~ every model fights every model. the jury sees both sides. ~
"""


class TitleScreen(Screen):
    BINDINGS = [("enter", "start", "Start"), ("space", "start", "Start"), ("q", "quit", "Quit")]

    DEFAULT_CSS = """
    TitleScreen {
        background: $surface;
        align: center middle;
    }
    TitleScreen #banner {
        color: $accent;
        text-style: bold;
    }
    TitleScreen #hint {
        color: $text-muted;
        margin-top: 2;
    }
    """

    def compose(self) -> ComposeResult:
        with Middle():
            with Center():
                yield Static(BANNER, id="banner")
            with Center():
                yield Static("press ENTER to begin — q to quit", id="hint")

    def action_start(self) -> None:
        self.app.begin()

    def action_quit(self) -> None:
        self.app.exit()
