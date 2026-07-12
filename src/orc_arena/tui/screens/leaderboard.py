"""Leaderboard screen — final ELO rankings with the statistics that make
them defensible: bootstrap CIs, per-judge jury behaviour, verbosity, and a
win grid. Renders plain (rank/ELO only) when no report is available, e.g.
replaying an old fixture."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Static


class LeaderboardScreen(Screen):
    BINDINGS = [
        ("enter,space,q", "quit", "Quit"),
        ("s", "shot", "Screenshot"),
    ]

    DEFAULT_CSS = """
    LeaderboardScreen {
        background: $surface;
    }
    LeaderboardScreen VerticalScroll { padding: 1 4; }
    LeaderboardScreen #title { text-style: bold; color: $accent; }
    LeaderboardScreen #champion { color: $success; text-style: bold; margin-top: 1; }
    LeaderboardScreen .warn { color: $warning; margin-top: 1; }
    LeaderboardScreen .section { text-style: bold; color: $accent; margin-top: 1; }
    LeaderboardScreen DataTable { margin-top: 1; height: auto; max-height: 14; }
    LeaderboardScreen #hint { margin-top: 1; color: $text-muted; }
    """

    def __init__(
        self,
        elo: dict[str, float],
        champion: str,
        log_path: str,
        report: dict[str, Any] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._elo = elo
        self._champion = champion
        self._log_path = log_path
        self._report = report or {}

    def compose(self) -> ComposeResult:
        r = self._report
        with VerticalScroll():
            yield Static("FINAL STANDINGS", id="title")
            yield Static(f"🏆 Leaderboard king: {self._champion}", id="champion")

            agreement = r.get("mean_agreement")
            if agreement is not None and agreement < 0.6:
                yield Static(
                    f"⚠ low-confidence ranking — judges agreed only {agreement:.0%} "
                    "of the time; treat adjacent ranks as unordered",
                    classes="warn",
                )
            if r.get("mixed_pool"):
                yield Static(
                    "⚠ mixed pool: thinking-enabled (🧠) and disabled warriors share "
                    "this ranking — cost/latency differ by design",
                    classes="warn",
                )
            if r.get("error_rounds"):
                yield Static(
                    f"{r['error_rounds']} round(s) voided on stream failure — "
                    "never judged, never rated",
                    classes="warn",
                )

            yield DataTable(id="table")

            tok = r.get("tokens") or {}
            if tok:
                total_in = tok["warriors_in"] + tok["judges_in"]
                total_out = tok["warriors_out"] + tok["judges_out"]
                jury_share = (
                    (tok["judges_in"] + tok["judges_out"]) / max(1, total_in + total_out)
                )
                yield Static(
                    f"tokens — warriors {tok['warriors_in']:,} in / {tok['warriors_out']:,} out"
                    f"   ·   jury {tok['judges_in']:,} in / {tok['judges_out']:,} out"
                    f"   ({jury_share:.0%} of all tokens went to judging)",
                    classes="section",
                )

            if r.get("elo_by_category"):
                yield Static("BY CATEGORY — Bradley-Terry per prompt slice", classes="section")
                yield DataTable(id="cats")

            if r.get("jury"):
                yield Static("THE JURY ROOM — per-judge behaviour", classes="section")
                yield DataTable(id="jury")
            if r.get("win_grid"):
                yield Static("WIN GRID — row beats column (ties = ½)", classes="section")
                yield DataTable(id="grid")

            yield Static(f"battle log → {self._log_path}   ·   manifest → *.run.json", id="log-path")
            yield Static("ENTER exit · s screenshot", id="hint")

    def on_mount(self) -> None:
        r = self._report
        ci = r.get("elo_ci") or {}
        thinking = r.get("thinking") or {}
        verbosity = r.get("verbosity") or {}
        reasoning = r.get("reasoning_tokens") or {}
        names_by_model = r.get("by_model_names") or {}

        table = self.query_one("#table", DataTable)
        cols = ["Rank", "Orc", "ELO"]
        if ci:
            cols.append("95% CI")
        if verbosity:
            cols += ["avg tok", "🧠 tok"]
        table.add_columns(*cols)

        # verbosity is keyed by short_model; map orc name -> short_model
        model_by_name = {orc: model for model, orc in names_by_model.items()}
        ranked = sorted(self._elo.items(), key=lambda kv: kv[1], reverse=True)
        for i, (name, elo) in enumerate(ranked, 1):
            badge = " 🧠" if thinking.get(name) else ""
            row = [str(i), f"{name}{badge}", f"{elo:.0f}"]
            if ci:
                lo, hi = ci.get(name, (elo, elo))
                row.append(f"{lo:.0f}–{hi:.0f}")
            if verbosity:
                m = model_by_name.get(name, "")
                row.append(f"{verbosity.get(m, 0):.0f}")
                row.append(f"{reasoning.get(m, 0):.0f}")
            table.add_row(*row)

        by_cat = r.get("elo_by_category") or {}
        if by_cat:
            counts = r.get("category_counts") or {}
            ct = self.query_one("#cats", DataTable)
            cats = list(by_cat.keys())
            ct.add_columns("Orc", "overall", *(f"{c} (n={counts.get(c, '?')})" for c in cats))
            for name, elo in ranked:
                ct.add_row(
                    name,
                    f"{elo:.0f}",
                    *(f"{by_cat[c].get(name, 0):.0f}" for c in cats),
                )

        jury = r.get("jury")
        if jury:
            jt = self.query_one("#jury", DataTable)
            jt.add_columns("Judge", "A-lean", "B-lean", "flip rate", "tie rate")
            for j in jury.get("per_judge", []):
                jt.add_row(
                    j["model"].split("/")[-1],
                    "–" if j.get("a_rate") is None else f"{j['a_rate']:.0%}",
                    "–" if j.get("b_rate") is None else f"{j['b_rate']:.0%}",
                    f"{j.get('position_bias', 0):.0%}",
                    f"{j.get('tie_rate', 0):.0%}",
                )

        grid = r.get("win_grid")
        if grid:
            gt = self.query_one("#grid", DataTable)
            names = [n for n, _ in ranked]
            gt.add_columns("", *(n[:8] for n in names))
            for n in names:
                gt.add_row(
                    n[:8],
                    *(
                        "·" if n == m else f"{grid.get(n, {}).get(m, 0):g}"
                        for m in names
                    ),
                )

    def action_shot(self) -> None:
        path = self.app.save_screenshot()
        self.notify(f"saved {path}")

    def action_quit(self) -> None:
        self.app.exit()
