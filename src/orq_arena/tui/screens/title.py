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


def _span(seconds: int | float) -> str:
    """7200 -> '2h00', 540 -> '9m'."""
    minutes = round(seconds / 60)
    hours, mins = divmod(minutes, 60)
    return f"{hours}h{mins:02d}" if hours else f"{mins}m"


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

            harness = p.get("harness") or {}
            if harness:
                yield from self._harness_block(harness)
            else:
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
                        f"(seeded slice); pass --rounds {p['n_prompts']} for all",
                        classes="muted",
                    )

            yield Static("RUN PLAN", classes="section")
            yield DataTable(id="plan", cursor_type="none", zebra_stripes=False)
            cost = p["cost"]
            if cost.unpriced:
                yield Static(
                    "no catalog price (self-hosted or unpriced): "
                    + ", ".join(cost.unpriced)
                    + "; excluded from both figures",
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
                    + ". The report will carry this caveat; prefer out-of-family "
                    "judges to defend the numbers",
                    classes="warn",
                )
            for line in p.get("probe_lines") or []:
                yield Static(line, classes="warn")

            cfg = getattr(self.app, "cfg", None)
            seats = (
                "in one seat order"
                if cfg is not None and not cfg.judge_swap
                else "in both seat orders (a flip = abstain)"
            )
            yield Static(
                f"What happens next: every pair streams side by side; the jury votes "
                f"{seats}; standings refit after every match.",
                classes="muted",
            )
        yield Static(self._consent_label(), id="consent", markup=False)

    def _harness_block(self, harness: dict) -> ComposeResult:
        """HARNESSES table plus the TASKS / SCHEDULE / BUDGET / CHECKS lines.

        Every key is optional: the block renders whatever preflight managed to compute.
        """
        plan = harness.get("plan") or {}
        yield Static("HARNESSES", classes="section")
        yield DataTable(id="harnesses", cursor_type="none", zebra_stripes=False)
        yield Static("all agents route through the orq router", classes="muted")

        n_tasks = plan.get("tasks_per_match")
        mix = plan.get("difficulty_mix") or {}
        tasks = [f"{n_tasks if n_tasks is not None else self._plan.get('n_prompts', '?')} tasks"]
        tasks += [f"{k} {v}" for k, v in mix.items()]
        yield Static("TASKS", classes="section")
        yield Static(" · ".join(tasks), classes="line")
        names = plan.get("task_names") or []
        if names:
            more = f" · +{len(names) - 8} more" if len(names) > 8 else ""
            yield Static(" · ".join(names[:8]) + more, classes="muted")

        sched = []
        if plan.get("matches") is not None:
            sched.append(f"{plan['matches']} matches")
        if n_tasks is not None:
            sched.append(f"{n_tasks} tasks each")
        if plan.get("trials") is not None:
            sched.append(f"{plan['trials']} trials ({plan.get('cached', 0)} cached)")
        jury = sum(r.calls for r in self._plan["cost"].rows if r.role == "judge")
        if jury:
            sched.append(f"≤ {jury} jury calls")
        if sched:
            yield Static("SCHEDULE", classes="section")
            yield Static(" · ".join(sched), classes="line")

        budget = []
        if plan.get("cost_note"):
            budget.append(str(plan["cost_note"]))
        if self._plan["cost"].judges_usd:
            budget.append(f"jury ≈ ${self._plan['cost'].judges_usd:.2f}")
        if plan.get("agent_timeouts_s"):
            budget.append(f"agent timeouts total {_span(plan['agent_timeouts_s'])}")
        if plan.get("wall_estimate_s"):
            budget.append(f"wall estimate ≤ {_span(plan['wall_estimate_s'])}")
        if budget:
            yield Static("BUDGET", classes="section")
            yield Static(" · ".join(budget), classes="line")

        checks = list(harness.get("checks") or [])
        missing = plan.get("images_missing") or []
        if missing:
            checks.append(
                f"⚠ {len(missing)} task image(s) to pull on first use: " + ", ".join(missing[:4])
            )
        if checks:
            yield Static("CHECKS", classes="section")
            for line in checks:
                bad = line.lstrip().startswith(("⚠", "✗"))
                yield Static(line, classes="warn" if bad else "line", markup=False)

        cfg = getattr(self.app, "cfg", None)
        if cfg is not None:
            gate = "ON" if getattr(cfg, "verifier_gate", False) else "OFF"
            yield Static("JUDGES", classes="section")
            yield Static(
                " · ".join(j.split("/", 1)[-1] for j in cfg.judges) + f" · verifier gate {gate}",
                classes="line",
            )

    def _fill_harness_table(self, harness: dict) -> None:
        table = self.query_one("#harnesses", DataTable)
        for col in ("name", "agent", "model", "overlay", "api"):
            table.add_column(col)
        for h in (harness.get("plan") or {}).get("harnesses") or []:
            table.add_row(
                str(h.get("name", "")),
                str(h.get("agent", "")),
                str(h.get("model", "")),
                str(h.get("overlay") or "vanilla"),
                str(h.get("api_format") or ""),
            )

    def on_mount(self) -> None:
        from ...cli import judges_header  # lazy: cli imports the TUI lazily too

        if self._plan.get("harness"):
            self._fill_harness_table(self._plan["harness"])
        cost = self._plan["cost"]
        # The app's config names the judge mode and seat orders; a bare host has none.
        cfg = getattr(self.app, "cfg", None)
        table = self.query_one("#plan", DataTable)
        for col in ("Model", "Calls", "$/M in", "$/M out", "Cost"):
            table.add_column(col)
        for role, header in (
            ("candidate", "Candidates"),
            ("judge", judges_header(cfg) if cfg is not None else "Judges (×2 seat orders)"),
            ("probe", None),
        ):
            rows = [r for r in cost.rows if r.role == role]
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
            f"≈ ${cost.projected_usd:.2f}" + (" + ?" if cost.unpriced else "")
            if cost.projected_usd > 0
            else "spend projection unavailable"
        )
        table.add_row("PROJECTED SPEND", "", "", "", total)
        if cost.projected_usd > 0:
            table.add_row(
                "worst case, retries + stand-ins",
                "",
                "",
                "",
                f"≈ ${cost.worst_case_usd:.2f}",
            )

    def _consent_label(self) -> str:
        cost = self._plan["cost"]
        if cost.projected_usd > 0:
            suffix = " + ?" if cost.unpriced else ""
            fight = (
                f"ENTER  fight (≈ ${cost.projected_usd:.2f}{suffix}, "
                f"up to ${cost.worst_case_usd:.2f} with retries)"
            )
        else:
            fight = "ENTER  fight"
        return f"[ {fight} ]      [ Q  quit ]"

    def action_fight(self) -> None:
        self.app.begin()  # type: ignore[attr-defined]

    def action_quit(self) -> None:
        self.app.exit()
