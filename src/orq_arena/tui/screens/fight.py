"""Fight screen, the main attraction.

Layout:
  ┌─────────────────────────────────────────────┐
  │ Ticker strip (match progress)               │
  ├──────────────────────┬──────────────────────┤
  │ ModelCard A        │ ModelCard B        │
  ├──────────────────────┴──────────────────────┤
  │ PromptPanel                                 │
  ├──────────────────────┬──────────────────────┤
  │ ResponsePanel A      │ ResponsePanel B      │
  ├──────────────────────┴──────────────────────┤
  │ Judge cards (3 across)                      │
  └─────────────────────────────────────────────┘

Side identity: A is magenta, B is cyan (CRT theme), on the model cards,
the response panels, and the judge verdict cues.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Static

from ..widgets.judge_card import JudgeCard
from ..widgets.model_card import ModelCard
from ..widgets.prompt_panel import PromptPanel
from ..widgets.response_panel import ResponsePanel


class FightScreen(Screen):
    BINDINGS = [("q", "quit", "Quit")]

    DEFAULT_CSS = """
    FightScreen {
        background: $surface;
    }
    FightScreen #ticker-strip {
        height: 3;
        padding: 0 1;
        color: $text-muted;
        background: $panel-darken-2;
        border-bottom: solid $accent;
    }
    FightScreen #models {
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
        self._card_a = ModelCard(side="a")
        self._card_b = ModelCard(side="b")
        self._prompt = PromptPanel("[dim]waiting for next round...[/dim]")
        self._resp_a = ResponsePanel(side="a")
        self._resp_b = ResponsePanel(side="b")
        self._judges: dict[str, JudgeCard] = {name: JudgeCard(name) for name in judge_names}
        self._ticker = Static("[dim]arena loading...[/dim]", id="ticker-strip")
        self._status = Static("", id="status")
        self._orc_a = ""
        self._orc_b = ""
        self._ko_announced: set[str] = set()

    def compose(self) -> ComposeResult:
        yield self._ticker
        with Horizontal(id="models"):
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

    def set_standings(self, elo: dict[str, float], done: int, total: int) -> None:
        top = sorted(elo.items(), key=lambda kv: kv[1], reverse=True)[:5]
        strip = "   ".join(f"{i}. {n[:14]} {v:.0f}" for i, (n, v) in enumerate(top, 1))
        self._ticker.update(f"[b]MATCH {done}/{total}[/b]   {strip}")
        for card, orc in ((self._card_a, self._orc_a), (self._card_b, self._orc_b)):
            if orc in elo:
                card.set_elo(elo[orc])

    def start_match(
        self,
        orc_a: str,
        model_a: str,
        emblem_a: str,
        thinking_a: bool,
        orc_b: str,
        model_b: str,
        emblem_b: str,
        thinking_b: bool,
        starting_hp: int,
    ) -> None:
        self._orc_a, self._orc_b = orc_a, orc_b
        self._card_a.set_model(
            name=orc_a,
            model_id=model_a,
            emblem=emblem_a,
            max_hp=starting_hp,
            thinking=thinking_a,
        )
        self._card_b.set_model(
            name=orc_b,
            model_id=model_b,
            emblem=emblem_b,
            max_hp=starting_hp,
            thinking=thinking_b,
        )
        self._resp_a.reset()
        self._resp_b.reset()
        for card in self._judges.values():
            card.reset()
        self._prompt.clear_prompt()
        self._ko_announced.clear()
        self._status.update(f"[b #ff3bd4]{orc_a}[/b #ff3bd4] vs [b #00e5ff]{orc_b}[/b #00e5ff]")

    def set_prompt(self, round_number: int, text: str) -> None:
        self._prompt.set_prompt(round_number, text)
        self._resp_a.reset()
        self._resp_b.reset()
        # Previous round's verdicts stay readable (dimmed) while the next
        # responses stream; they refresh when the new votes land.
        for card in self._judges.values():
            card.mark_stale()

    def append_response(self, side: str, text: str) -> None:
        (self._resp_a if side == "a" else self._resp_b).append_chunk(text)

    def append_thinking(self, side: str, text: str) -> None:
        (self._resp_a if side == "a" else self._resp_b).append_thinking(text)

    def response_complete(
        self,
        side: str,
        *,
        tokens_out: int,
        reasoning_tokens: int,
        finish_reason: str,
        error: str | None,
    ) -> None:
        panel = self._resp_a if side == "a" else self._resp_b
        panel.complete(
            tokens_out=tokens_out,
            reasoning_tokens=reasoning_tokens,
            finish_reason=finish_reason,
            error=error,
        )

    def set_judge_verdict(
        self,
        judge_name: str,
        verdict: str,
        reasoning: str,
        *,
        flipped: bool = False,
        replacement: bool = False,
    ) -> None:
        card = self._judges.get(judge_name)
        if card is not None:
            card.set_verdict(verdict, reasoning, flipped=flipped, replacement=replacement)
            return
        # A stand-in judge has no pre-built card, surface it on the status line.
        self._status.update(f"[dim]stand-in[/dim] [b]{judge_name}[/b] votes {verdict}")

    def apply_damage(
        self, hp_a: int, hp_b: int, majority: str, damage: int, loser_side: str
    ) -> None:
        self._card_a.set_hp(hp_a)
        self._card_b.set_hp(hp_b)
        if majority in ("A", "B"):
            hit = self._orc_a if loser_side == "a" else self._orc_b
            self._status.update(
                f"verdict [b]{majority}[/b], [b red]{damage} damage[/b red] to {hit}"
            )
        else:
            self._status.update(f"verdict [b]{majority}[/b], no damage")
        # KO moment, the show ends here, the judging doesn't.
        for hp, card, orc in ((hp_a, self._card_a, self._orc_a), (hp_b, self._card_b, self._orc_b)):
            if hp == 0 and orc and orc not in self._ko_announced:
                self._ko_announced.add(orc)
                card.knock_out()
                self.app.bell()
                self._status.update(
                    f"[b red]💀 K.O.![/b red] [b]{orc}[/b] is down, remaining rounds judged for the rating"
                )

    def round_voided(self, reason: str) -> None:
        self._status.update(f"[yellow]⚠ round void, {reason}[/yellow]")

    def match_resolved(self, winner: str, *, ko: bool = False) -> None:
        if not winner:
            self._status.update(
                "[b]🤝 DRAW[/b], even on rounds; the rating heard every round anyway"
            )
        elif ko:
            self.app.bell()
            self._status.update(f"[b red]💀 K.O.![/b red]  [b]{winner}[/b] wins!")
        else:
            self._status.update(f"[b]🏁 {winner}[/b] wins on points")

    def action_quit(self) -> None:
        self.app.exit()
