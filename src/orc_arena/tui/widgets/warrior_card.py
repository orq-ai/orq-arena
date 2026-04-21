"""Warrior card — name, model, HP bar, ELO.

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
    WarriorCard .name {
        text-style: bold;
        color: $accent;
    }
    WarriorCard .model {
        color: $text-muted;
    }
    WarriorCard .elo {
        color: $text-muted;
    }
    WarriorCard.hit {
        background: $error-darken-1;
    }
    """

    def __init__(
        self,
        orc_name: str = "",
        model_id: str = "",
        emblem: str = "⚔",
        max_hp: int = 100,
        elo: float = 1000.0,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._orc_name = orc_name
        self._model_id = model_id
        self._emblem = emblem
        self._max_hp = max_hp
        self._hp = max_hp
        self._elo = elo
        self._name_w: Static | None = None
        self._model_w: Static | None = None
        self._hp_w: ProgressBar | None = None
        self._elo_w: Static | None = None

    def compose(self) -> ComposeResult:
        self._name_w = Static(f"{self._emblem}  {self._orc_name}", classes="name")
        self._model_w = Static(self._model_id, classes="model")
        self._hp_w = ProgressBar(total=self._max_hp, show_eta=False)
        self._elo_w = Static(f"ELO {self._elo:.0f}", classes="elo")
        with Vertical():
            yield self._name_w
            yield self._model_w
            yield self._hp_w
            yield self._elo_w

    def on_mount(self) -> None:
        if self._hp_w is not None:
            self._hp_w.update(progress=self._hp)

    def set_warrior(
        self,
        *,
        orc_name: str,
        model_id: str,
        emblem: str,
        max_hp: int,
    ) -> None:
        self._orc_name = orc_name
        self._model_id = model_id
        self._emblem = emblem
        self._max_hp = max_hp
        self._hp = max_hp
        if self._name_w:
            self._name_w.update(f"{emblem}  {orc_name}")
        if self._model_w:
            self._model_w.update(model_id)
        if self._hp_w:
            self._hp_w.update(total=max_hp, progress=max_hp)

    def set_hp(self, new_hp: int) -> None:
        old = self._hp
        self._hp = max(0, new_hp)
        if self._hp_w:
            self._hp_w.update(progress=self._hp)
        if self._hp < old:
            self.add_class("hit")
            self.set_timer(0.3, lambda: self.remove_class("hit"))

    def set_elo(self, elo: float) -> None:
        self._elo = elo
        if self._elo_w:
            self._elo_w.update(f"ELO {elo:.0f}")
