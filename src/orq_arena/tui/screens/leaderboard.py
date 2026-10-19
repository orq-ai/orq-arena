"""Leaderboard screen, final ELO rankings with the statistics that make
them defensible: bootstrap CIs, per-judge jury behaviour, verbosity, and a
win grid. Renders plain (rank/ELO only) when no report is supplied."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Static

from ...judging import judge_labels


def _harness_cells(h: dict[str, Any] | None) -> list[str]:
    """pass rate, $/task, min/task for one harness; dashes when it has no trials."""
    if not h:
        return ["–", "–", "–"]
    if h.get("verified"):
        passed = f"{h.get('passed', 0)}/{h['verified']}"
    elif h.get("pass_rate") is not None:
        passed = f"{h['pass_rate']:.0%}"
    else:
        passed = "–"
    cost = h.get("mean_cost_usd")
    secs = h.get("mean_duration_s")
    return [
        passed,
        "–" if cost is None else f"{cost:.2f}",
        "–" if secs is None else f"{secs / 60:.1f}",
    ]


class LeaderboardScreen(Screen):
    BINDINGS = [
        ("enter,space,q", "quit", "Quit"),
        ("s", "shot", "Screenshot"),
        ("b", "browse", "Battle browser"),
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
        cfg: Any | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._elo = elo
        self._champion = champion
        self._log_path = log_path
        self._report = report or {}
        self._cfg = cfg

    def compose(self) -> ComposeResult:
        r = self._report
        with VerticalScroll():
            yield Static("Final Results", id="title")
            yield Static(f"🏆 Leaderboard king: {self._champion}", id="champion")

            agreement = r.get("mean_agreement")
            if agreement is not None and agreement < 0.6:
                yield Static(
                    f"⚠ low-confidence ranking, judges agreed only {agreement:.0%} "
                    "of the time; treat adjacent ranks as unordered",
                    classes="warn",
                )
            if r.get("mixed_pool"):
                yield Static(
                    "⚠ mixed pool: thinking-enabled (🧠) and disabled models share "
                    "this ranking, cost/latency differ by design",
                    classes="warn",
                )
            if r.get("error_rounds"):
                yield Static(
                    f"{r['error_rounds']} round(s) voided on stream failure, "
                    "never judged, never rated",
                    classes="warn",
                )

            yield DataTable(id="table")

            harness = r.get("harness") or {}
            if harness:
                total = r.get("rated_rounds") or 0
                gate = r.get("gate_rounds") or 0
                line = f"gate decided {gate} of {total} rounds"
                if total > gate:
                    line += f" · jury {total - gate}"
                edited = sum(h.get("tests_edited", 0) for h in harness.values())
                if edited:
                    line += f" · tests/ edited in {edited} trial(s)"
                yield Static(line, id="gate-line", classes="section")

            # Descriptive first (a count, nothing to converge); the modelled
            # coefficient only exists when identified, which is also when the
            # len-ctrl column it explains is present (RES-1150).
            lp = r.get("length_pref")
            if lp and lp["rounds"]:
                share = lp["longer_wins"] / lp["rounds"]
                lc = r.get("length_coef")
                coef_bit = (
                    f"; len-ctrl ELO prices that preference out (coef {lc:+.1f})"
                    if lc is not None
                    else ""
                )
                yield Static(
                    f"style control: longer answer won {share:.0%} of decisive "
                    f"rounds ({lp['longer_wins']}/{lp['rounds']}){coef_bit}",
                    classes="section",
                )

            tok = r.get("tokens") or {}
            if tok:
                wi = tok.get("models_in", 0)
                wo = tok.get("models_out", 0)
                ji, jo = tok.get("judges_in", 0), tok.get("judges_out", 0)
                jury_share = (ji + jo) / max(1, wi + wo + ji + jo)
                yield Static(
                    f"tokens, models {wi:,} in / {wo:,} out"
                    f"   ·   jury {ji:,} in / {jo:,} out"
                    f"   ({jury_share:.0%} of all tokens went to judging)",
                    classes="section",
                )

            if r.get("elo_by_category"):
                yield Static("BY CATEGORY, Bradley-Terry per prompt slice", classes="section")
                yield DataTable(id="cats")

            if r.get("jury"):
                yield Static("THE JURY ROOM, per-judge behaviour", classes="section")
                yield DataTable(id="jury")
                fleiss = r.get("fleiss") or {}
                if fleiss.get("kappa") is not None:
                    cohen = r.get("cohen") or {}
                    pair_txt = "   ".join(
                        f"{k}: {v['kappa']}" for k, v in cohen.items() if v.get("kappa") is not None
                    )
                    yield Static(
                        f"Fleiss' κ [b]{fleiss['kappa']}[/b] ({fleiss['label']}) over "
                        f"{fleiss['rounds_used']}/{fleiss['rounds_total']} full-panel rounds"
                        + (f"   ·   pairwise: {pair_txt}" if pair_txt else ""),
                        classes="section",
                    )
            if r.get("win_grid"):
                yield Static("WIN GRID, row beats column (ties = ½)", classes="section")
                yield DataTable(id="grid")

            yield Static(
                f"battle log → {self._log_path}   ·   manifest → *.run.json", id="log-path"
            )
            yield Static("ENTER exit · B battle browser · s screenshot", id="hint")

    def on_mount(self) -> None:
        r = self._report
        ci = r.get("elo_ci") or {}
        thinking = r.get("thinking") or {}
        verbosity = r.get("verbosity") or {}
        reasoning = r.get("reasoning_tokens") or {}

        table = self.query_one("#table", DataTable)
        sc = r.get("elo_style_controlled") or {}
        harness = r.get("harness") or {}
        cols = ["Rank", "Harness" if harness else "Model", "ELO"]
        if ci:
            cols.append("95% CI")
        if sc:
            cols.append("len-ctrl")
        if harness:
            cols += ["pass rate", "$/task", "min/task"]
        if verbosity:
            cols += ["avg tok", "🧠 tok"]
        table.add_columns(*cols)

        # verbosity and reasoning are keyed by display name, the same key the
        # rows are built from, so no indirection is needed. Going through a
        # reversed name map is what made these columns read 0 whenever the map
        # and the metrics disagreed about their key.
        ranked = sorted(self._elo.items(), key=lambda kv: kv[1], reverse=True)
        for i, (name, elo) in enumerate(ranked, 1):
            badge = " 🧠" if thinking.get(name) else ""
            row = [str(i), f"{name}{badge}", f"{elo:.0f}"]
            if ci:
                lo, hi = ci.get(name, (elo, elo))
                row.append(f"{lo:.0f}–{hi:.0f}")
            if sc:
                row.append(f"{sc.get(name, elo):.0f}")
            if harness:
                row += _harness_cells(harness.get(name))
            if verbosity:
                row.append(f"{verbosity.get(name, 0):.0f}")
                row.append(f"{reasoning.get(name, 0):.0f}")
            table.add_row(*row)

        by_cat = r.get("elo_by_category") or {}
        if by_cat:
            counts = r.get("category_counts") or {}
            ct = self.query_one("#cats", DataTable)
            cats = list(by_cat.keys())
            ct.add_columns("Model", "overall", *(f"{c} (n={counts.get(c, '?')})" for c in cats))
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
            per_judge = jury.get("per_judge", [])
            labels = judge_labels([j["model"] for j in per_judge])
            for j in per_judge:
                jt.add_row(
                    labels[j["model"]],
                    "–" if j.get("a_rate") is None else f"{j['a_rate']:.0%}",
                    "–" if j.get("b_rate") is None else f"{j['b_rate']:.0%}",
                    # One seat order means no flip could be seen, not that none happened.
                    f"{j.get('position_bias', 0):.0%}"
                    if getattr(self._cfg, "judge_swap", True)
                    else "n/a (swap off)",
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
                    *("·" if n == m else f"{grid.get(n, {}).get(m, 0):g}" for m in names),
                )

    def action_browse(self) -> None:
        from ...data.schemas import load_records
        from .battle_browser import BattleBrowserScreen

        records = load_records(self._log_path)
        if not records:
            self.notify("no battle log to browse", severity="warning")
            return
        self.app.push_screen(BattleBrowserScreen(records))

    def action_shot(self) -> None:
        path = self.app.save_screenshot()
        self.notify(f"saved {path}")

    def action_quit(self) -> None:
        self.app.exit()
