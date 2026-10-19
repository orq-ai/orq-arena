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
  │ Judge cards (one per judge)                 │
  └─────────────────────────────────────────────┘

Harness mode swaps the response panels for TrajectoryPanels (a coding agent's
steps, then the hidden-test verdict) and adds a verifier card to the judge row.

Side identity: A is $accent, B is $primary (blue and purple in the orq
theme, magenta and cyan in crt-neon), on the model cards, the response
panels, and the judge verdict cues.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Static

from ...events import SolutionReady, TrajectoryStep
from ..widgets.judge_card import JudgeCard, VerifierCard
from ..widgets.model_card import ModelCard
from ..widgets.prompt_panel import PromptPanel
from ..widgets.response_panel import ResponsePanel
from ..widgets.trajectory_panel import TrajectoryPanel

VERIFIER = "verifier"
_HARNESS_ACTIONS = {"toggle_diff", "show_trajectory", "toggle_follow"}


class FightScreen(Screen):
    BINDINGS = [
        ("q", "quit", "Quit"),
        Binding("d", "toggle_diff", "Diff"),
        Binding("t", "show_trajectory", "Trajectory"),
        Binding("f", "toggle_follow", "Follow"),
    ]

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
    FightScreen.harness #prompt-area { height: 6; }
    FightScreen.harness PromptPanel { height: 5; }
    FightScreen #status {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    """

    def __init__(
        self,
        judge_names: list[str],
        *,
        abstain_below: float | None = None,
        harness: bool = False,
        verifier_gate: bool = True,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._judge_names = judge_names
        self._harness = harness
        self._card_a = ModelCard(side="a")
        self._card_b = ModelCard(side="b")
        self._prompt = PromptPanel("[dim]waiting for next round...[/dim]")
        self._resp_a: ResponsePanel | TrajectoryPanel
        self._resp_b: ResponsePanel | TrajectoryPanel
        if harness:
            self.add_class("harness")
            self._resp_a = TrajectoryPanel(side="a")
            self._resp_b = TrajectoryPanel(side="b")
        else:
            self._resp_a = ResponsePanel(side="a")
            self._resp_b = ResponsePanel(side="b")
        self._judges: dict[str, JudgeCard] = {
            name: JudgeCard(name, abstain_below=abstain_below) for name in judge_names
        }
        self._verifier: VerifierCard | None = None
        if harness and verifier_gate:
            self._verifier = VerifierCard()
            self._judges[VERIFIER] = self._verifier
        # side -> passed (None: verifier did not run), until both trials report
        self._passed: dict[str, bool | None] = {}
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
            if self._verifier is not None:
                yield self._verifier
        yield self._status

    def on_mount(self) -> None:
        # One column per card: the grid was hard-wired to 3 judges.
        self.query_one("#judges").styles.grid_size_columns = max(1, len(self._judges))

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in _HARNESS_ACTIONS and not self._harness:
            return False
        return True

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
        label_a: str = "",
        label_b: str = "",
    ) -> None:
        self._orc_a, self._orc_b = orc_a, orc_b
        self._card_a.set_model(
            name=orc_a,
            model_id=model_a,
            emblem=emblem_a,
            max_hp=starting_hp,
            thinking=thinking_a,
            label=label_a,
        )
        self._card_b.set_model(
            name=orc_b,
            model_id=model_b,
            emblem=emblem_b,
            max_hp=starting_hp,
            thinking=thinking_b,
            label=label_b,
        )
        self._resp_a.reset()
        self._resp_b.reset()
        self._passed.clear()
        for card in self._judges.values():
            card.reset()
        self._prompt.clear_prompt()
        self._ko_announced.clear()
        self._status.update(f"[b $accent]{orc_a}[/] vs [b $primary]{orc_b}[/]")

    def set_prompt(self, round_number: int, text: str, *, task: str = "") -> None:
        self._prompt.set_prompt(round_number, text, task=task)
        self._resp_a.reset()
        self._resp_b.reset()
        self._passed.clear()
        # Previous round's verdicts stay readable (dimmed) while the next
        # responses stream; they refresh when the new votes land.
        for card in self._judges.values():
            card.mark_stale()

    def append_response(self, side: str, text: str) -> None:
        panel = self._resp_a if side == "a" else self._resp_b
        if isinstance(panel, ResponsePanel):
            panel.append_chunk(text)

    def append_thinking(self, side: str, text: str) -> None:
        panel = self._resp_a if side == "a" else self._resp_b
        if isinstance(panel, ResponsePanel):
            panel.append_thinking(text)

    def _trajectory(self, side: str) -> TrajectoryPanel | None:
        panel = self._resp_a if side == "a" else self._resp_b
        return panel if isinstance(panel, TrajectoryPanel) else None

    def add_step(self, ev: TrajectoryStep) -> None:
        if panel := self._trajectory(ev.side):
            panel.add_step(ev)

    def solution_ready(self, ev: SolutionReady, diff_text: str = "") -> None:
        """One trial finished; once both have, the verifier card says who decides."""
        if panel := self._trajectory(ev.side):
            if diff_text:
                panel.set_diff(diff_text)
            panel.solution(ev)
        self._passed[ev.side] = None if ev.error else ev.passed
        verifier = self._verifier
        if verifier is None:
            return
        if len(self._passed) < 2:
            only = next(iter(self._passed.items()))
            verifier.note(f"{only[0].upper()} {_outcome(only[1])}, waiting for the other")
            return
        pa, pb = self._passed["a"], self._passed["b"]
        if pa is None or pb is None:
            verifier.note("tests did not run on both → jury")
        elif pa != pb:
            # The battle confirms with a "verifier" verdict; show it as soon as it is known.
            self.set_judge_verdict(VERIFIER, "A" if pa else "B", "hidden tests decide")
        else:
            verifier.note(f"tie (both {_outcome(pa)}) → jury")

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
        if isinstance(panel, TrajectoryPanel):
            # The dossier text is for the judges; the pane already shows the trial.
            if error:
                panel.fail(error)
            return
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
        probabilities: dict[str, float] | None = None,
        flipped: bool = False,
        replacement: bool = False,
    ) -> None:
        if judge_name == VERIFIER and self._verifier is not None:
            for name in self._judge_names:
                self._judges[name].skip()
        card = self._judges.get(judge_name)
        if card is not None:
            card.set_verdict(
                verdict,
                reasoning,
                probabilities=probabilities,
                flipped=flipped,
                replacement=replacement,
            )
            return
        # A stand-in judge has no pre-built card, surface it on the status line.
        top = (
            f" ({probabilities[verdict]:.2f})" if probabilities and verdict in probabilities else ""
        )
        self._status.update(f"[dim]stand-in[/dim] [b]{judge_name}[/b] votes {verdict}{top}")

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

    def _focused_panels(self) -> list[TrajectoryPanel]:
        """The pane under focus, else both."""
        node = self.focused
        while node is not None:
            if isinstance(node, TrajectoryPanel):
                return [node]
            node = node.parent  # type: ignore[assignment]
        return [p for p in (self._trajectory("a"), self._trajectory("b")) if p is not None]

    def action_toggle_diff(self) -> None:
        for panel in self._focused_panels():
            panel.toggle_diff()

    def action_show_trajectory(self) -> None:
        for panel in self._focused_panels():
            panel.show_trajectory()

    def action_toggle_follow(self) -> None:
        for panel in self._focused_panels():
            panel.toggle_follow()

    def action_quit(self) -> None:
        self.app.exit()


def _outcome(passed: bool | None) -> str:
    return "PASSED" if passed else "FAILED" if passed is False else "not verified"
