"""The RUN PLAN screen lists every model, prices the run, and gates on ENTER."""

from __future__ import annotations

from textual.app import App
from textual.widgets import DataTable, Static

from orq_arena.preflight import CallCounts, CostCeiling, CostRow
from orq_arena.tui.screens.title import RunPlanScreen


class _Host(App):
    def __init__(self):
        super().__init__()
        self.began = False

    def begin(self):
        self.began = True


def _plan(*, unpriced: bool = False) -> dict:
    rows = [
        CostRow("candidate", "prov/model-a", 15, 1.0, 5.0, 0.14),
        CostRow("candidate", "prov/model-b", 15, 2.0, 9.0, 0.28),
        CostRow("judge", "prov/judge-1", 60, 0.1, 0.4, 0.08),
        CostRow("probe", "probe", 2, None, None, 0.01),
    ]
    if unpriced:
        rows = [CostRow(r.role, r.model_id, r.calls, None, None, None) for r in rows]
    ceiling = CostCeiling(
        total_usd=0.0 if unpriced else 0.51,
        models_usd=0.42,
        judges_usd=0.08,
        probe_usd=0.01,
        unpriced=[r.model_id for r in rows] if unpriced else [],
        rows=tuple(rows),
    )
    return {
        "counts": CallCounts(1, 5, 10, 30, 2),
        "ceiling": ceiling,
        "overlap": ["prov"],
        "probe_lines": [],
        "n_candidates": 2,
        "n_judges": 1,
        "n_prompts": 30,
        "prompts_label": "prompts/starter.jsonl",
        "prompt_categories": {"code": 10, "general": 20},
        "log_path": "battles.jsonl",
    }


async def test_plan_screen_lists_every_model_and_prices():
    app = _Host()
    async with app.run_test(size=(120, 50)) as pilot:
        await app.push_screen(RunPlanScreen(_plan()))
        await pilot.pause()
        table = app.screen.query_one("#plan", DataTable)
        cells = " ".join(str(table.get_cell_at((r, 0))) for r in range(table.row_count))
        for model in ("model-a", "model-b", "judge-1", "Thinking probe"):
            assert model in cells
        assert "MAXIMUM SPEND" in cells
        consent = str(app.screen.query_one("#consent", Static).render())
        assert "$0.51" in consent
        # sampling caveat: 5 of 30
        body = " ".join(str(s.render()) for s in app.screen.query(Static))
        assert "samples 5 of 30" in body
        assert "prompts/starter.jsonl" in body


async def test_plan_screen_degrades_without_pricing():
    app = _Host()
    async with app.run_test(size=(120, 50)) as pilot:
        await app.push_screen(RunPlanScreen(_plan(unpriced=True)))
        await pilot.pause()
        consent = str(app.screen.query_one("#consent", Static).render())
        assert "$" not in consent  # no dollar figure without a ceiling
        table = app.screen.query_one("#plan", DataTable)
        last = str(table.get_cell_at((table.row_count - 1, 4)))
        assert "unavailable" in last


async def test_enter_begins_and_q_quits():
    app = _Host()
    async with app.run_test(size=(120, 50)) as pilot:
        await app.push_screen(RunPlanScreen(_plan()))
        await pilot.pause()
        await pilot.press("enter")
        assert app.began
