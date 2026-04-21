"""Leaderboard screen — final ELO rankings."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Static


class LeaderboardScreen(Screen):
    BINDINGS = [("enter,space,q", "quit", "Quit")]

    DEFAULT_CSS = """
    LeaderboardScreen {
        background: $surface;
        padding: 2 4;
    }
    LeaderboardScreen #title {
        text-style: bold;
        color: $accent;
    }
    LeaderboardScreen #champion {
        color: $success;
        text-style: bold;
        margin-top: 1;
    }
    LeaderboardScreen DataTable {
        margin-top: 1;
    }
    LeaderboardScreen #hint {
        margin-top: 2;
        color: $text-muted;
    }
    """

    def __init__(self, elo: dict[str, float], champion: str, log_path: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._elo = elo
        self._champion = champion
        self._log_path = log_path

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("FINAL STANDINGS", id="title")
            yield Static(f"🏆 Champion: {self._champion}", id="champion")
            yield DataTable(id="table")
            yield Static(f"battle log → {self._log_path}", id="log-path")
            yield Static("press ENTER to exit", id="hint")

    def on_mount(self) -> None:
        table = self.query_one("#table", DataTable)
        table.add_columns("Rank", "Orc", "ELO")
        ranked = sorted(self._elo.items(), key=lambda kv: kv[1], reverse=True)
        for i, (name, elo) in enumerate(ranked, 1):
            table.add_row(str(i), name, f"{elo:.0f}")

    def action_quit(self) -> None:
        self.app.exit()
