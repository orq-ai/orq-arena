"""Fight screen — the main attraction.

Layout:
  ┌─────────────────────────────────────────────┐
  │ Bracket strip (compact)                     │
  ├──────────────────────┬──────────────────────┤
  │ WarriorCard A        │ WarriorCard B        │
  ├──────────────────────┴──────────────────────┤
  │ PromptPanel                                 │
  ├──────────────────────┬──────────────────────┤
  │ ResponsePanel A      │ ResponsePanel B      │
  ├──────────────────────┴──────────────────────┤
  │ Judge cards (3 across)                      │
  └─────────────────────────────────────────────┘
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Static

from ..widgets.judge_card import JudgeCard
from ..widgets.prompt_panel import PromptPanel
from ..widgets.response_panel import ResponsePanel
from ..widgets.warrior_card import WarriorCard


class FightScreen(Screen):
    BINDINGS = [("q", "quit", "Quit")]

    DEFAULT_CSS = """
    FightScreen {
        background: $surface;
    }
    FightScreen #bracket-strip {
        height: 3;
        padding: 0 1;
        color: $text-muted;
        background: $panel-darken-2;
        border-bottom: solid $accent;
    }
    FightScreen #warriors {
        height: 11;
        layout: grid;
        grid-size: 2 1;
        grid-gutter: 1;
        padding: 0 1;
    }
    FightScreen #prompt-area {
        height: 5;
        padding: 0 1;
    }
    FightScreen #responses {
        layout: grid;
        grid-size: 2 1;
        grid-gutter: 1;
        padding: 0 1;
        height: 1fr;
    }
    FightScreen #judges {
        height: 9;
        layout: grid;
        grid-size: 3 1;
        grid-gutter: 1;
        padding: 0 1;
        border-top: solid $accent;
    }
    FightScreen #status {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    """

    def __init__(self, judge_names: list[str], **kwargs) -> None:
        super().__init__(**kwargs)
        self._judge_names = judge_names
        self._card_a = WarriorCard()
        self._card_b = WarriorCard()
        self._prompt = PromptPanel("[dim]waiting for next round...[/dim]")
        self._resp_a = ResponsePanel()
        self._resp_b = ResponsePanel()
        self._judges: dict[str, JudgeCard] = {
            name: JudgeCard(name) for name in judge_names
        }
        self._bracket_strip = Static("[dim]bracket loading...[/dim]", id="bracket-strip")
        self._status = Static("", id="status")

    def compose(self) -> ComposeResult:
        yield self._bracket_strip
        with Horizontal(id="warriors"):
            yield self._card_a
            yield self._card_b
        with Vertical(id="prompt-area"):
            yield self._prompt
        with Horizontal(id="responses"):
            yield self._resp_a
            yield self._resp_b
        with Horizontal(id="judges"):
            for name in self._judge_names:
                yield self._judges[name]
        yield self._status

    # --- called by the App from the event loop ---

    def set_bracket_strip(self, text: str) -> None:
        self._bracket_strip.update(text)

    def start_match(self,
                    orc_a: str, model_a: str, emblem_a: str,
                    orc_b: str, model_b: str, emblem_b: str,
                    starting_hp: int) -> None:
        self._card_a.set_warrior(orc_name=orc_a, model_id=model_a, emblem=emblem_a, max_hp=starting_hp)
        self._card_b.set_warrior(orc_name=orc_b, model_id=model_b, emblem=emblem_b, max_hp=starting_hp)
        self._resp_a.reset()
        self._resp_b.reset()
        for card in self._judges.values():
            card.reset()
        self._prompt.clear_prompt()
        self._status.update(f"[b]{orc_a}[/b] vs [b]{orc_b}[/b]")

    def set_prompt(self, round_number: int, text: str) -> None:
        self._prompt.set_prompt(round_number, text)
        self._resp_a.reset()
        self._resp_b.reset()
        for card in self._judges.values():
            card.reset()

    def append_response(self, side: str, text: str) -> None:
        (self._resp_a if side == "a" else self._resp_b).append_chunk(text)

    def set_judge_verdict(self, judge_name: str, verdict: str, reasoning: str) -> None:
        card = self._judges.get(judge_name)
        if card is not None:
            card.set_verdict(verdict, reasoning)

    def apply_damage(self, hp_a: int, hp_b: int, majority: str, damage: int) -> None:
        self._card_a.set_hp(hp_a)
        self._card_b.set_hp(hp_b)
        if majority in ("A", "B"):
            self._status.update(f"verdict {majority} — {damage} damage")
        else:
            self._status.update(f"verdict {majority} — no damage")

    def match_resolved(self, winner: str, by: str) -> None:
        self._status.update(f"[b]{winner}[/b] wins by [b]{by}[/b]")

    def action_quit(self) -> None:
        self.app.exit()
