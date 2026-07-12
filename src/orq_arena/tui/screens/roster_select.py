"""Roster picker — choose the pool from your orq.ai workspace catalog.

Opens first on ``orq-arena run`` (unless ``--config`` pins the YAML roster).
Fetches the workspace-enabled chat catalog once (24h cache), filters locally:
live-search input, provider chips, and a seed-order roster panel. Any pool
size ≥ 2 — the arena is a round-robin, not a bracket.

Shows exact call counts as you pick (matches × rounds × judge calls), never
dollar estimates (plan decision 18).
"""

from __future__ import annotations

from itertools import combinations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.markup import escape
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Input, SelectionList, Static
from textual.widgets.selection_list import Selection

from ...config import ArenaConfig
from ...providers.models_list import ModelEntry, fetch_chat_models

MIN_POOL = 2


class _ProviderChip(Static):
    """A provider-filter pill; clicking filters the list."""

    class Clicked(Message):
        def __init__(self, provider: str | None) -> None:
            super().__init__()
            self.provider = provider

    DEFAULT_CSS = """
    _ProviderChip { width: auto; padding: 0 1; margin: 0 1 0 0; color: $text-muted; }
    _ProviderChip.active { color: $text; background: $accent; text-style: bold; }
    _ProviderChip:hover { color: $text; text-style: bold; }
    """

    def __init__(self, provider: str | None, label: str, **kwargs) -> None:
        super().__init__(label, markup=False, **kwargs)
        self.provider_key = provider

    def on_click(self) -> None:
        self.post_message(self.Clicked(self.provider_key))


class RosterSelectScreen(Screen):
    """Pick your pool; START posts RosterSelected."""

    BINDINGS = [
        ("s", "start", "Start"),
        ("f", "random_fill", "Fill to 8"),
        ("x", "clear", "Clear"),
        ("slash", "focus_search", "Search"),
        Binding("escape", "leave_search", "Leave search", priority=True),
        Binding("q", "quit", "Quit", priority=True),
    ]

    DEFAULT_CSS = """
    RosterSelectScreen { background: $surface; }
    RosterSelectScreen #hud {
        height: 2; padding: 0 2; background: $panel-darken-2;
        border-bottom: solid $accent;
    }
    RosterSelectScreen #search-row { height: 3; padding: 0 2; }
    RosterSelectScreen #search-row Input { width: 1fr; }
    RosterSelectScreen #providers-row { height: 1; padding: 0 2; }
    RosterSelectScreen #picker {
        height: 1fr; padding: 0 2;
        layout: grid; grid-size: 2; grid-columns: 2fr 1fr; grid-gutter: 1;
    }
    RosterSelectScreen SelectionList { height: 1fr; border: round $primary; }
    RosterSelectScreen #roster-box {
        height: 1fr; border: round $warning; padding: 0 1; overflow-x: hidden;
    }
    RosterSelectScreen #roster-list { width: 1fr; height: auto; }
    RosterSelectScreen #status {
        height: 3; padding: 0 2; background: $panel-darken-2; border-top: solid $accent;
    }
    RosterSelectScreen .hud-line { height: 1; }
    """

    class RosterSelected(Message):
        """Posted when the user confirms >= MIN_POOL model ids."""

        def __init__(self, model_ids: list[str]) -> None:
            super().__init__()
            self.model_ids = list(model_ids)

    class LoadFailed(Message):
        def __init__(self, reason: str) -> None:
            super().__init__()
            self.reason = reason

    def __init__(self, cfg: ArenaConfig, *, prompt_count: int, **kwargs) -> None:
        super().__init__(**kwargs)
        self._cfg = cfg
        self._prompt_count = prompt_count
        self._chosen: list[str] = [w.model_id for w in cfg.warriors]
        self._all_models: list[ModelEntry] = []
        self._source = "loading"
        self._active_provider: str | None = None
        self._search_query = ""
        self._silence = False
        self._chips: list[_ProviderChip] = []

        self._hud = Static("", classes="hud-line", markup=True)
        self._search = Input(placeholder="search models — / to focus, esc to leave")
        self._providers_row = Horizontal(id="providers-row")
        self._picker: SelectionList[str] = SelectionList()
        self._roster_header = Static("", markup=True)
        self._roster_list = Static("", id="roster-list", markup=True)
        self._status_line = Static("", classes="hud-line", markup=True)
        self._hint_line = Static(
            "[b]S[/b] start · [b]F[/b] fill · [b]X[/b] clear · [b]/[/b] search · "
            "[b]SPACE[/b] toggle · [b]Q[/b] quit",
            classes="hud-line", markup=True,
        )

    def compose(self) -> ComposeResult:
        with Vertical(id="hud"):
            yield self._hud
        with Horizontal(id="search-row"):
            yield self._search
        yield self._providers_row
        with Horizontal(id="picker"):
            yield self._picker
            with Vertical(id="roster-box"):
                yield self._roster_header
                with VerticalScroll():
                    yield self._roster_list
        with Vertical(id="status"):
            yield self._status_line
            yield self._hint_line

    def on_mount(self) -> None:
        self._render_all()
        self._picker.focus()
        self.run_worker(self._load_models(), exclusive=True)

    async def _load_models(self) -> None:
        fallback = [w.model_id for w in self._cfg.warriors]
        try:
            ml = await fetch_chat_models(self._cfg.gateway, fallback_ids=fallback)
        except Exception as exc:
            self.post_message(self.LoadFailed(str(exc)))
            return
        self._all_models = sorted(ml.models, key=lambda m: m.sort_key)
        self._source = ml.source
        self._rebuild_chips()
        self._populate_list()
        self._render_all()

    # ---------- rendering ----------

    def _counts_line(self) -> str:
        n = len(self._chosen)
        if n < MIN_POOL:
            return f"[dim]pick at least {MIN_POOL} models[/dim]"
        matches = len(list(combinations(range(n), 2)))
        rounds = min(self._cfg.match.max_rounds, self._prompt_count)
        judge_calls = matches * rounds * len(self._cfg.judges) * 2
        return (
            f"{matches} matches × {rounds} rounds → "
            f"{matches * rounds * 2} streams + {judge_calls} judge calls"
        )

    def _render_all(self) -> None:
        n = len(self._chosen)
        ready = n >= MIN_POOL
        color = "green" if ready else "yellow"
        self._hud.update(
            f"[b]ORQ-ARENA[/b] · pick your pool   [{color}]{n} selected[/{color}]"
            f"   [dim]·[/dim]   {self._counts_line()}"
        )
        src = {
            "loading": "[dim]contacting gateway…[/dim]",
            "live": "[green]LIVE[/green] [dim]workspace-enabled catalog[/dim]",
            "cache": "[yellow]CACHE[/yellow] [dim]~/.cache/orq-arena/models.json — refresh-models to update[/dim]",
            "fallback": "[red]FALLBACK[/red] [dim]gateway unreachable — YAML roster only[/dim]",
        }.get(self._source, "")
        self._status_line.update(
            f"{src}   [dim]·   {len(self._visible())}/{len(self._all_models)} models shown[/dim]"
        )
        self._roster_header.update(f"[b]YOUR POOL[/b] [dim]({n}, seed order)[/dim]")
        if not self._chosen:
            self._roster_list.update("[dim]empty — SPACE to add models[/dim]")
        else:
            lines = []
            for i, mid in enumerate(self._chosen, 1):
                provider, _, short = mid.partition("/")
                lines.append(f"[dim]#{i:>2}[/dim] [b]{escape(short or mid)}[/b] [dim]{escape(provider)}[/dim]")
            self._roster_list.update("\n".join(lines))

    # ---------- provider chips ----------

    def _rebuild_chips(self) -> None:
        self._providers_row.remove_children()
        chips = [_ProviderChip(None, "ALL")]
        chips += [_ProviderChip(p, p) for p in sorted({m.provider for m in self._all_models})]
        for ch in chips:
            if ch.provider_key == self._active_provider:
                ch.add_class("active")
            self._providers_row.mount(ch)
        self._chips = chips

    def on__provider_chip_clicked(self, event: _ProviderChip.Clicked) -> None:
        self._active_provider = event.provider
        for ch in self._chips:
            ch.set_class(ch.provider_key == event.provider, "active")
        self._populate_list()
        self._render_all()

    # ---------- list ----------

    def _visible(self) -> list[ModelEntry]:
        q = self._search_query.strip().lower()
        items = self._all_models
        if self._active_provider is not None:
            items = [m for m in items if m.provider == self._active_provider]
        if q:
            items = [m for m in items if q in m.id.lower() or q in m.provider.lower()]
        return items

    def _populate_list(self) -> None:
        self._silence = True
        try:
            self._picker.clear_options()
            options = [
                Selection(
                    f"{escape(m.provider):<14}  {escape(m.id)}",
                    value=m.id,
                    initial_state=m.id in self._chosen,
                )
                for m in self._visible()
            ]
            if options:
                self._picker.add_options(options)
        finally:
            self.set_timer(0.01, self._clear_silence)

    def _clear_silence(self) -> None:
        self._silence = False

    def on_selection_list_selected_changed(
        self, event: SelectionList.SelectedChanged
    ) -> None:
        if self._silence:
            return
        selected = set(event.selection_list.selected)
        # Keep pick order stable: drop deselected, append newly selected.
        self._chosen = [m for m in self._chosen if m in selected]
        for mid in event.selection_list.selected:
            if mid not in self._chosen:
                self._chosen.append(mid)
        self._render_all()

    # ---------- input ----------

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input is self._search:
            self._search_query = event.value
            self._populate_list()
            self._render_all()

    def action_focus_search(self) -> None:
        self._search.focus()

    def action_leave_search(self) -> None:
        self._picker.focus()

    def action_random_fill(self) -> None:
        import random

        want = max(0, 8 - len(self._chosen))
        candidates = [m.id for m in self._all_models if m.id not in self._chosen]
        random.shuffle(candidates)
        self._chosen.extend(candidates[:want])
        self._populate_list()
        self._render_all()

    def action_clear(self) -> None:
        self._chosen = []
        self._populate_list()
        self._render_all()

    def action_start(self) -> None:
        if len(self._chosen) < MIN_POOL:
            self.app.bell()
            self.notify(f"pick at least {MIN_POOL} models", severity="warning")
            return
        self.post_message(self.RosterSelected(self._chosen))

    def action_quit(self) -> None:
        self.app.exit()
