"""RUN PLAN screen: branding, prompts, the full cost table, one consent gate.

The TUI counterpart of the terminal preflight: everything the run will do and
the most it can spend, rendered before a single battle or judge call. ENTER is
the run's only confirmation (``-y`` skips this screen entirely).
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Center, VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Static

BANNER = r"""
 ██████╗ ██████╗  ██████╗      █████╗ ██████╗ ███████╗███╗   ██╗ █████╗
██╔═══██╗██╔══██╗██╔═══██╗    ██╔══██╗██╔══██╗██╔════╝████╗  ██║██╔══██╗
██║   ██║██████╔╝██║   ██║    ███████║██████╔╝█████╗  ██╔██╗ ██║███████║
██║   ██║██╔══██╗██║▄▄ ██║    ██╔══██║██╔══██╗██╔══╝  ██║╚██╗██║██╔══██║
╚██████╔╝██║  ██║╚██████╔╝    ██║  ██║██║  ██║███████╗██║ ╚████║██║  ██║
 ╚═════╝ ╚═╝  ╚═╝ ╚══▀▀═╝     ╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═══╝╚═╝  ╚═╝

     ~ every model fights every model. the jury sees both sides. ~
"""


def _price(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.2f}"


def _money(v: float | None) -> str:
    return "?" if v is None else f"${v:.2f}"


class RunPlanScreen(Screen):
    """Scrollable plan body; the consent bar stays pinned at the bottom."""

    BINDINGS = [
        ("enter", "fight", "Fight"),
        ("q,escape", "quit", "Quit"),
    ]

    DEFAULT_CSS = """
    RunPlanScreen { background: $surface; }
    RunPlanScreen #body { padding: 0 4; }
    RunPlanScreen #banner { color: $accent; text-style: bold; }
    RunPlanScreen .section { text-style: bold; color: $accent; margin-top: 1; }
    RunPlanScreen .line { color: $text; }
    RunPlanScreen .muted { color: $text-muted; }
    RunPlanScreen .warn { color: $warning; margin-top: 1; }
    RunPlanScreen DataTable { margin-top: 1; height: auto; }
    RunPlanScreen #consent {
        dock: bottom; height: 3; content-align: center middle;
        background: $panel; color: $accent; text-style: bold;
        border-top: solid $primary;
    }
    """

    def __init__(self, plan: dict, **kwargs) -> None:
        super().__init__(**kwargs)
        self._plan = plan

    def compose(self) -> ComposeResult:
        p = self._plan
        counts = p["counts"]
        with VerticalScroll(id="body"):
            with Center():
                yield Static(BANNER, id="banner")
            yield Static(
                f"{p['n_candidates']} candidates · full round-robin: "
                f"{counts.matches} matches × {counts.rounds_per_match} rounds · "
                f"{p['n_judges']}-judge jury · log → {p['log_path']}",
                classes="line",
            )

            yield Static("PROMPTS", classes="section")
            cats = p.get("prompt_categories") or {}
            cat_txt = (
                " (" + ", ".join(f"{c} {n}" for c, n in sorted(cats.items())) + ")"
                if len(cats) > 1
                else ""
            )
            yield Static(
                f"{p['prompts_label']} · {p['n_prompts']} prompts{cat_txt}", classes="line"
            )
            if counts.rounds_per_match < p["n_prompts"]:
                yield Static(
                    f"each match samples {counts.rounds_per_match} of {p['n_prompts']} "
                    f"(seeded slice) — pass --rounds {p['n_prompts']} for all",
                    classes="muted",
                )

            yield Static("RUN PLAN", classes="section")
            yield DataTable(id="plan", cursor_type=None, zebra_stripes=False)
            ceiling = p["ceiling"]
            if ceiling.unpriced:
                yield Static(
                    "no catalog price (self-hosted or unpriced): "
                    + ", ".join(ceiling.unpriced)
                    + "; excluded from the total",
                    classes="muted",
                )
            yield Static(
                "worst case: every response maxed out at its token cap; typical runs "
                "cost noticeably less. Exact spend is reported after the run.",
                classes="muted",
            )

            if p.get("overlap"):
                yield Static(
                    "⚖ judge/candidate family overlap: "
                    + ", ".join(p["overlap"])
                    + " — the report will carry this caveat; prefer out-of-family "
                    "judges to defend the numbers",
                    classes="warn",
                )
            for line in p.get("probe_lines") or []:
                yield Static(line, classes="warn")

            yield Static(
                "What happens next: every pair streams side by side; the jury votes "
                "in both seat orders (a flip = abstain); standings refit after every "
                "match.",
                classes="muted",
            )
        yield Static(self._consent_label(), id="consent", markup=False)

    def on_mount(self) -> None:
        ceiling = self._plan["ceiling"]
        table = self.query_one("#plan", DataTable)
        for col in ("Model", "Calls", "$/M in", "$/M out", "Ceiling"):
            table.add_column(col)
        for role, header in (
            ("candidate", "Candidates"),
            ("judge", "Judges (×2 seat orders)"),
            ("probe", None),
        ):
            rows = [r for r in ceiling.rows if r.role == role]
            if not rows:
                continue
            if header:
                table.add_row(header, "", "", "", "")
            for r in rows:
                name = "Thinking probe" if role == "probe" else f"  {r.model_id}"
                table.add_row(
                    name,
                    str(r.calls),
                    "" if role == "probe" else _price(r.price_in),
                    "" if role == "probe" else _price(r.price_out),
                    _money(r.usd),
                )
        total = (
            f"≤ ${ceiling.total_usd:.2f}" + (" + ?" if ceiling.unpriced else "")
            if ceiling.total_usd > 0
            else "spend ceiling unavailable"
        )
        table.add_row("MAXIMUM SPEND", "", "", "", total)

    def _consent_label(self) -> str:
        ceiling = self._plan["ceiling"]
        if ceiling.total_usd > 0:
            suffix = " + ?" if ceiling.unpriced else ""
            fight = f"ENTER  fight (spends up to ${ceiling.total_usd:.2f}{suffix})"
        else:
            fight = "ENTER  fight"
        return f"[ {fight} ]      [ Q  quit ]"

    def action_fight(self) -> None:
        self.app.begin()

    def action_quit(self) -> None:
        self.app.exit()
