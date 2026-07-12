"""Warrior card — name, model, HP bar with damage flashes, ELO.

Child widget references are stored directly on the card instance so we never
query by ID — two WarriorCards can be mounted on the same screen without
colliding on shared IDs.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import ProgressBar, Static


class WarriorCard(Static):
    """A single warrior's status card."""

    DEFAULT_CSS = """
    WarriorCard {
        height: 9;
        padding: 1 2;
        border: round $accent;
        background: $panel;
    }
    WarriorCard.side-a { border: round $accent; }
    WarriorCard.side-b { border: round $primary; }
    WarriorCard .name { text-style: bold; }
    WarriorCard.side-a .name { color: $accent; }
    WarriorCard.side-b .name { color: $primary; }
    WarriorCard .model { color: $text-muted; }
    WarriorCard .hp-line { color: $text; }
    WarriorCard .elo { color: $text-muted; }
    WarriorCard.hit { background: $error-darken-1; }
    WarriorCard.ko { opacity: 0.5; border: round $error; }
    """

    def __init__(self, side: str = "a", **kwargs) -> None:
        super().__init__(**kwargs)
        self.add_class(f"side-{side}")
        self._orc_name = ""
        self._model_id = ""
        self._emblem = ""
        self._thinking = False
        self._max_hp = 100
        self._hp = 100
        self._elo = 1000.0
        self._name_w: Static | None = None
        self._model_w: Static | None = None
        self._hp_bar: ProgressBar | None = None
        self._hp_line: Static | None = None
        self._elo_w: Static | None = None

    def compose(self) -> ComposeResult:
        self._name_w = Static("", classes="name")
        self._model_w = Static("", classes="model")
        self._hp_bar = ProgressBar(total=self._max_hp, show_eta=False)
        self._hp_line = Static("", classes="hp-line")
        self._elo_w = Static(f"ELO {self._elo:.0f}", classes="elo")
        with Vertical():
            yield self._name_w
            yield self._model_w
            yield self._hp_bar
            yield self._hp_line
            yield self._elo_w

    def on_mount(self) -> None:
        self._refresh_all()

    def _refresh_all(self) -> None:
        if self._name_w:
            badge = "  🧠" if self._thinking else ""
            prefix = f"{self._emblem}  " if self._emblem else ""
            self._name_w.update(f"{prefix}{self._orc_name}{badge}")
        if self._model_w:
            self._model_w.update(self._model_id)
        if self._hp_bar:
            self._hp_bar.update(total=self._max_hp, progress=self._hp)
        self._update_hp_line()

    def _update_hp_line(self, flash: str = "") -> None:
        if self._hp_line is None:
            return
        share = self._hp / self._max_hp if self._max_hp else 0
        color = "green" if share > 0.5 else "yellow" if share > 0.25 else "red"
        self._hp_line.update(f"[{color}]HP {self._hp}/{self._max_hp}[/{color}]{flash}")

    def set_warrior(
        self,
        *,
        orc_name: str,
        model_id: str,
        emblem: str,
        max_hp: int,
        thinking: bool = False,
    ) -> None:
        self._orc_name = orc_name
        self._model_id = model_id
        self._emblem = emblem
        self._thinking = thinking
        self._max_hp = max_hp
        self._hp = max_hp
        self.remove_class("ko")
        self._refresh_all()

    def set_hp(self, new_hp: int) -> None:
        old = self._hp
        self._hp = max(0, new_hp)
        if self._hp_bar:
            self._hp_bar.update(progress=self._hp)
        if self._hp < old:
            self._update_hp_line(f"  [b red]−{old - self._hp}![/b red]")
            self.add_class("hit")
            self.set_timer(0.3, lambda: self.remove_class("hit"))
            self.set_timer(1.2, self._update_hp_line)
        else:
            self._update_hp_line()

    def knock_out(self) -> None:
        self.add_class("ko")

    def set_elo(self, elo: float) -> None:
        self._elo = elo
        if self._elo_w:
            self._elo_w.update(f"ELO {elo:.0f}")
