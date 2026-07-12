"""Post-mortem screen — per-model "why did I win / lose" coaching cards.

Pushed from the leaderboard via ``M``. One analyzer call per model (cheap,
configurable), cached in ``analysis.jsonl`` so revisits are free.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.markup import escape
from textual.screen import Screen
from textual.widgets import Static

from ...analysis.postmortem import (
    Postmortem,
    analyze_model,
    append_cache,
    load_records,
    read_cache,
)
from ...config import ArenaConfig


class PostmortemScreen(Screen):
    BINDINGS = [
        Binding("escape,m,q", "close", "Back"),
        ("s", "shot", "Screenshot"),
    ]

    DEFAULT_CSS = """
    PostmortemScreen { background: $surface; }
    PostmortemScreen #title {
        height: 2; padding: 0 2; background: $panel-darken-2;
        border-bottom: solid $accent; text-style: bold;
    }
    PostmortemScreen #cards { padding: 1 2; }
    PostmortemScreen .card { border: round $primary; padding: 0 1; margin-bottom: 1; height: auto; }
    PostmortemScreen #hint { height: 1; padding: 0 2; color: $text-muted; }
    """

    def __init__(self, cfg: ArenaConfig, log_path: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._cfg = cfg
        self._log_path = log_path
        self._cards: dict[str, Static] = {}

    def compose(self) -> ComposeResult:
        yield Static("THE COACH'S NOTES — per-model post-mortems", id="title")
        with VerticalScroll(id="cards"):
            for model in self._models():
                card = Static(f"[b]{escape(model)}[/b]\n[dim]analyzing…[/dim]",
                              classes="card", markup=True)
                self._cards[model] = card
                yield card
        yield Static("ESC back · s screenshot · analysis cached in analysis.jsonl", id="hint")

    def _models(self) -> list[str]:
        return sorted({m for r in load_records(self._log_path) for m in (r.model_a, r.model_b)})

    def on_mount(self) -> None:
        if not self._cards:
            self.notify("no battle log to analyze", severity="warning")
            return
        self.run_worker(self._analyze_all(), exclusive=True)

    async def _analyze_all(self) -> None:
        from ...providers.orq_gateway import OrqGateway

        records = load_records(self._log_path)
        cached = read_cache(self._log_path)
        try:
            client = OrqGateway(self._cfg.gateway).client
        except RuntimeError as exc:  # no API key (e.g. demo replay)
            for card in self._cards.values():
                card.update(f"[yellow]needs a live run — {escape(str(exc))}[/yellow]")
            return
        for model, card in self._cards.items():
            pm = cached.get(model)
            if pm is None or pm.error:
                pm = await analyze_model(
                    client=client,
                    analyzer_model=self._cfg.analyzer_model,
                    model=model,
                    records=records,
                )
                if not pm.error:
                    append_cache(self._log_path, pm)
            card.update(self._render_card(pm))

    def _render_card(self, pm: Postmortem) -> str:
        head = (
            f"[b]{escape(pm.model)}[/b]   "
            f"[dim]{pm.wins}W / {pm.losses}L / {pm.ties}T[/dim]"
        )
        if pm.error:
            return f"{head}\n[yellow]{escape(pm.error)}[/yellow]"
        lines = [head]
        if pm.one_liner:
            lines.append(f"[i]{escape(pm.one_liner)}[/i]")
        if pm.strengths:
            lines.append("[green]+ " + "\n+ ".join(escape(s) for s in pm.strengths) + "[/green]")
        if pm.weaknesses:
            lines.append("[red]− " + "\n− ".join(escape(s) for s in pm.weaknesses) + "[/red]")
        if pm.judge_patterns:
            lines.append("[dim]judges: " + " · ".join(escape(s) for s in pm.judge_patterns) + "[/dim]")
        return "\n".join(lines)

    def action_close(self) -> None:
        self.app.pop_screen()

    def action_shot(self) -> None:
        path = self.app.save_screenshot()
        self.notify(f"saved {path}")
