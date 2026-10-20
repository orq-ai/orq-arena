"""Harness mode in the TUI: trajectory panes, the verifier card, plan and results screens.

Rendered through real Textual widgets (headless Pilot), events routed through
``ArenaApp._handle_event`` exactly as the live app does, no engine and no network.
"""

from __future__ import annotations

from textual.app import App
from textual.widgets import DataTable, Static

from orq_arena.config import ArenaConfig
from orq_arena.data.prompts import PromptItem
from orq_arena.data.schemas import BattleRecord
from orq_arena.events import (
    JudgeVerdictEvent,
    MatchStarted,
    ResponseComplete,
    SolutionReady,
    TrajectoryStep,
    TurnPrompt,
)
from orq_arena.preflight import CallCounts, CostProjection, CostRow
from orq_arena.tui.app import ArenaApp
from orq_arena.tui.screens.battle_browser import BattleBrowserScreen
from orq_arena.tui.screens.fight import FightScreen
from orq_arena.tui.screens.leaderboard import LeaderboardScreen
from orq_arena.tui.screens.title import RunPlanScreen
from orq_arena.tui.widgets.response_panel import ResponsePanel
from orq_arena.tui.widgets.trajectory_panel import TrajectoryPanel

TASK = "The repo in /app has a broken history. Recover the lost commit."


class _Host(App):
    pass


def _cfg(*, harness: bool = True, gate: bool = True, judges: int = 3) -> ArenaConfig:
    if harness:
        candidates = [
            {
                "kind": "harness",
                "name": "claude-code",
                "agent": "claude-code",
                "model_id": "anthropic/opus",
            },
            {
                "kind": "harness",
                "name": "pi",
                "agent": "pi",
                "model_id": "a/opus",
                "agent_kwargs": {"thinking": "medium"},
            },
        ]
    else:
        candidates = [{"name": "Alpha", "model_id": "x/alpha"}, {"name": "Beta", "model_id": "x/b"}]
    return ArenaConfig.model_validate(
        {
            "candidates": candidates,
            "judges": [f"j/judge{i}" for i in range(judges)],
            "verifier_gate": gate,
        }
    )


def _app(cfg: ArenaConfig, prompts: list[PromptItem] | None = None) -> ArenaApp:
    return ArenaApp(cfg=cfg, prompts=prompts or [], battle_log_path="unused.jsonl")


def _screen(app: ArenaApp) -> FightScreen:
    cfg = app.cfg
    return FightScreen(
        [app._judge_labels[m] for m in cfg.judges],
        harness=cfg.has_harness,
        verifier_gate=cfg.verifier_gate,
    )


def _step(side: str, kind: str, title: str, body: str = "", *, t_ms: int = 0, replay=False):
    return TrajectoryStep(
        match_id="m", side=side, kind=kind, title=title, body=body, t_ms=t_ms, replay=replay
    )


def _solution(side: str, passed: bool | None, **kw) -> SolutionReady:
    base = {"match_id": "m", "side": side, "passed": passed, "steps": 5, "commands": 3, "edits": 1}
    return SolutionReady(**(base | kw))


async def _start(host: App, app: ArenaApp, screen: FightScreen, pilot) -> None:
    await host.push_screen(screen)
    await pilot.pause()
    app._fight_screen = screen  # route events without starting the engine
    app._handle_event(
        MatchStarted(match_id="m", round_name="r", model_a="claude-code", model_b="pi")
    )
    app._handle_event(TurnPrompt(match_id="m", round_number=1, prompt=TASK))
    await pilot.pause()


def _text(widget: Static) -> str:
    return str(widget.render())


async def test_panel_class_follows_the_candidate_kind():
    for harness, expected in ((True, TrajectoryPanel), (False, ResponsePanel)):
        app = _app(_cfg(harness=harness))
        screen = _screen(app)
        host = _Host()
        async with host.run_test(size=(140, 50)) as pilot:
            await host.push_screen(screen)
            await pilot.pause()
            assert isinstance(screen._resp_a, expected)
            assert isinstance(screen._resp_b, expected)
            assert (screen._verifier is not None) == harness


async def test_model_fight_ignores_harness_events():
    app = _app(_cfg(harness=False))
    screen = _screen(app)
    host = _Host()
    async with host.run_test(size=(140, 50)) as pilot:
        await _start(host, app, screen, pilot)
        app._handle_event(_step("a", "command", "$ ls"))
        app._handle_event(_solution("a", True))
        await pilot.pause()
        assert screen._verifier is None
        assert "verifier" not in screen._judges


async def test_steps_append_and_header_counts_update():
    app = _app(_cfg())
    screen = _screen(app)
    host = _Host()
    async with host.run_test(size=(140, 50)) as pilot:
        await _start(host, app, screen, pilot)
        panel = screen._resp_a
        assert isinstance(panel, TrajectoryPanel)
        assert "waiting" in _text(panel._header)

        app._handle_event(_step("a", "thinking", "", "need the dangling commit", t_ms=500))
        app._handle_event(_step("a", "command", "$ git reflog", t_ms=1200))
        app._handle_event(_step("a", "observation", "", "\n".join(f"l{i}" for i in range(20))))
        app._handle_event(_step("a", "edit", "src/main.py", "@@ -1 +1 @@\n-a\n+b", t_ms=61_000))
        app._handle_event(_step("a", "test", "$ python -m pytest -q", t_ms=65_000))
        await pilot.pause()

        header = _text(panel._header)
        assert "4 steps" in header  # observations are not steps
        assert "2 cmds" in header
        assert "1 edit" in header and "1 edits" not in header
        assert "1m 05s" in header
        assert "LIVE" in header and "CACHED" not in header
        assert len(panel._log.lines) > 5
        # the other pane is untouched
        assert "waiting" in _text(screen._resp_b._header)

        # an observation is cut to 6 lines plus a pointer
        obs = [r for r in panel._lines if "l0" in str(r)][0]
        assert "l5" in str(obs) and "l6" not in str(obs)
        assert "6 of 20 lines" in str(obs)

        app._handle_event(_step("a", "command", "$ git status"))
        await pilot.pause()
        assert "5 steps" in _text(panel._header)

        # a new round empties the pane
        app._handle_event(TurnPrompt(match_id="m", round_number=2, prompt="next"))
        await pilot.pause()
        assert panel._lines == [] and "waiting" in _text(panel._header)


async def test_test_marker_and_tests_edit_warning():
    app = _app(_cfg())
    screen = _screen(app)
    host = _Host()
    async with host.run_test(size=(140, 50)) as pilot:
        await _start(host, app, screen, pilot)
        app._handle_event(_step("a", "test", "$ pytest -q"))
        app._handle_event(_step("a", "edit", "tests/test_main.py", "-x\n+y"))
        app._handle_event(_step("a", "edit", "src/main.py", "-x\n+y"))
        await pilot.pause()
        lines = [str(r) for r in screen._resp_a._lines]
        assert any("◂ test" in line for line in lines)
        assert sum("⚠ tests/ edited" in line for line in lines) == 1


async def test_replay_badge_and_cost_in_header():
    app = _app(_cfg())
    screen = _screen(app)
    host = _Host()
    async with host.run_test(size=(140, 50)) as pilot:
        await _start(host, app, screen, pilot)
        app._handle_event(_step("b", "command", "$ ls", replay=True))
        app._handle_event(_solution("b", True, replay=True, cost_usd=0.18, duration_ms=245_000))
        await pilot.pause()
        header = _text(screen._resp_b._header)
        assert "⟲ CACHED" in header and "LIVE" not in header
        assert "$0.18" in header and "4m 05s" in header


async def test_diff_toggle_swaps_the_pane_and_back():
    app = _app(_cfg())
    screen = _screen(app)
    host = _Host()
    async with host.run_test(size=(140, 50)) as pilot:
        await _start(host, app, screen, pilot)
        panel = screen._resp_a
        app._handle_event(_step("a", "command", "$ ls"))
        await pilot.pause()

        # no diff text yet: say so instead of showing nothing
        panel.toggle_diff()
        await pilot.pause()
        assert "DIFF" in _text(panel._header)
        assert panel._log.lines
        panel.toggle_diff()
        await pilot.pause()
        assert "DIFF" not in _text(panel._header)
        assert panel._view == "trajectory"

        # a solution carries the stat; the diff text arrives with it
        screen.solution_ready(
            _solution("a", False, diff_stat="+2 -1 in 1 file", tests_edited=True),
            "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n",
        )
        screen.set_focus(screen._resp_b._log)  # the focused pane alone toggles
        screen.action_toggle_diff()
        await pilot.pause()
        assert panel._view == "trajectory" and screen._resp_b._view == "diff"
        screen.action_show_trajectory()
        screen.set_focus(None)  # nothing focused: both panes
        screen.action_toggle_diff()
        await pilot.pause()
        assert panel._view == "diff" and screen._resp_b._view == "diff"
        assert "+2 -1 in 1 file" in _text(panel._header)
        assert "+++ b/x" in "".join(s.text for s in panel._log.lines)

        screen.action_show_trajectory()
        await pilot.pause()
        assert panel._view == "trajectory"
        assert "5 steps" in _text(panel._header)


async def test_follow_toggle():
    app = _app(_cfg())
    screen = _screen(app)
    host = _Host()
    async with host.run_test(size=(140, 50)) as pilot:
        await _start(host, app, screen, pilot)
        panel = screen._resp_a
        assert panel._log.auto_scroll
        assert "follow ON" in _text(panel._footer)
        screen.action_toggle_follow()
        await pilot.pause()
        assert not panel._log.auto_scroll
        assert "follow OFF" in _text(panel._footer)


async def test_solution_footer_states():
    app = _app(_cfg())
    screen = _screen(app)
    host = _Host()
    async with host.run_test(size=(140, 50)) as pilot:
        await _start(host, app, screen, pilot)
        a, b = screen._resp_a, screen._resp_b
        assert "running" in _text(a._footer) or "queued" in _text(a._footer)
        app._handle_event(_step("a", "command", "$ ls"))
        await pilot.pause()
        assert "▶ running" in _text(a._footer)

        app._handle_event(
            _solution(
                "a", False, reward=0.0, cost_usd=0.42, exit_reason="finished", tests_edited=True
            )
        )
        app._handle_event(
            _solution("b", True, reward=1.0, exit_reason="max_turns", diff_stat="+2 -1 in 1 file")
        )
        await pilot.pause()
        fa, fb = _text(a._footer), _text(b._footer)
        assert "✗ hidden tests FAILED" in fa and "agent finished" in fa and "$0.42" in fa
        assert "tests/ edited" in fa
        assert "✓ hidden tests PASSED" in fb and "max_turns reached" in fb
        assert "+2 -1 in 1 file" in fb

        # timeout and not-verified and error
        app._handle_event(TurnPrompt(match_id="m", round_number=2, prompt="again"))
        app._handle_event(_solution("a", False, exit_reason="timeout"))
        app._handle_event(_solution("b", None))
        await pilot.pause()
        assert "⏱ timeout" in _text(a._footer)
        assert "did not run" in _text(b._footer)

        app._handle_event(TurnPrompt(match_id="m", round_number=3, prompt="third"))
        app._handle_event(
            ResponseComplete(match_id="m", side="a", full_text="", error="harbor died")
        )
        await pilot.pause()
        assert "trial failed: harbor died" in _text(a._footer)


async def test_verifier_card_waits_then_the_tests_decide():
    app = _app(_cfg())
    screen = _screen(app)
    host = _Host()
    async with host.run_test(size=(140, 50)) as pilot:
        await _start(host, app, screen, pilot)
        card = screen._verifier
        assert card is not None
        assert "waiting for both" in _text(card)

        app._handle_event(_solution("a", False))
        await pilot.pause()
        assert "A FAILED, waiting for the other" in _text(card)

        app._handle_event(_solution("b", True))
        await pilot.pause()
        assert "→ B" in _text(card) and "tests decide" in _text(card)
        for name in ("judge0", "judge1", "judge2"):
            assert "skipped (gate)" in _text(screen._judges[name])

        # the engine's own verdict lands on the same card
        app._handle_event(
            JudgeVerdictEvent(
                match_id="m",
                judge_name="verifier",
                verdict="B",
                reasoning="hidden tests: A failed, B passed",
            )
        )
        await pilot.pause()
        assert card.has_class("verdict-b")
        assert "hidden tests: A failed, B passed" in _text(card)

        # the next round starts clean
        app._handle_event(TurnPrompt(match_id="m", round_number=2, prompt="next"))
        await pilot.pause()
        assert "waiting for both" in _text(card)
        assert "deliberating" in _text(screen._judges["judge0"])


async def test_equal_outcomes_go_to_the_jury():
    app = _app(_cfg())
    screen = _screen(app)
    host = _Host()
    async with host.run_test(size=(140, 50)) as pilot:
        await _start(host, app, screen, pilot)
        card = screen._verifier
        assert card is not None
        app._handle_event(_solution("a", True))
        app._handle_event(_solution("b", True))
        await pilot.pause()
        assert "tie (both PASSED) → jury" in _text(card)
        assert "skipped" not in _text(screen._judges["judge0"])

        app._handle_event(
            JudgeVerdictEvent(match_id="m", judge_name="j/judge0", verdict="A", reasoning="cleaner")
        )
        await pilot.pause()
        assert screen._judges["judge0"].has_class("verdict-a")

        app._handle_event(TurnPrompt(match_id="m", round_number=2, prompt="again"))
        app._handle_event(_solution("a", False))
        app._handle_event(_solution("b", False))
        await pilot.pause()
        assert "tie (both FAILED) → jury" in _text(card)


async def test_no_verifier_card_when_the_gate_is_off():
    app = _app(_cfg(gate=False))
    screen = _screen(app)
    host = _Host()
    async with host.run_test(size=(140, 50)) as pilot:
        await _start(host, app, screen, pilot)
        assert screen._verifier is None
        app._handle_event(_solution("a", True))
        app._handle_event(_solution("b", False))
        await pilot.pause()
        assert "skipped" not in _text(screen._judges["judge0"])


async def test_judge_grid_has_a_column_per_card():
    for n_judges, gate, expected in ((2, True, 3), (4, True, 5), (4, False, 4), (3, False, 3)):
        app = _app(_cfg(judges=n_judges, gate=gate))
        screen = _screen(app)
        host = _Host()
        async with host.run_test(size=(180, 50)) as pilot:
            await host.push_screen(screen)
            await pilot.pause()
            grid = screen.query_one("#judges")
            assert grid.styles.grid_size_columns == expected
            assert len(grid.children) == expected


async def test_model_cards_show_the_harness_label_and_task_line():
    items = [
        PromptItem(
            text="first task",
            category="easy",
            metadata={"task_name": "hello-world", "difficulty": "easy", "timeout_sec": 600},
        ),
        PromptItem(
            text=TASK,
            category="medium",
            metadata={"task_name": "fix-git", "difficulty": "medium", "timeout_sec": 900},
        ),
    ]
    app = _app(_cfg(), items)
    screen = _screen(app)
    host = _Host()
    async with host.run_test(size=(140, 50)) as pilot:
        await _start(host, app, screen, pilot)
        assert "claude-code · opus · vanilla" in _text(screen._card_a._model_w)
        assert "pi · opus · " in _text(screen._card_b._model_w)
        assert "#" in _text(screen._card_b._model_w)  # setup variant
        prompt = _text(screen._prompt)
        assert "TASK 2/2 · fix-git · medium · 15m" in prompt
        assert "broken history" in prompt


async def test_diff_is_read_from_the_trial_cache(tmp_path):
    from orq_arena.harness.runner import PATCH_FILE, job_name

    cfg = _cfg()
    cfg.harness.trials_dir = str(tmp_path)
    app = _app(cfg)
    screen = _screen(app)
    host = _Host()
    async with host.run_test(size=(140, 50)) as pilot:
        await _start(host, app, screen, pilot)
        trial = tmp_path / job_name(TASK, cfg.candidates[0].candidate_id) / "trial-1"
        trial.mkdir(parents=True)
        (trial / "config.json").write_text("{}")
        (trial / "result.json").write_text(
            '{"verifier_result": {"rewards": {"reward": 1}}, "agent_result": {"n_input_tokens": 5}}'
        )
        (trial / PATCH_FILE).write_text("--- a/f\n+++ b/f\n@@ -1 +1 @@\n-1\n+2\n")
        app._handle_event(_solution("a", False))
        await pilot.pause()
        assert "+++ b/f" in screen._resp_a._diff_text
        assert screen._resp_b._diff_text == ""


def _plan(harness: dict | None = None) -> dict:
    rows = [
        CostRow("candidate", "a/opus", 8, None, None, None),
        CostRow("judge", "j/judge0", 48, 0.1, 0.4, 0.6),
    ]
    cost = CostProjection(
        projected_usd=0.6,
        worst_case_usd=0.9,
        models_usd=0.0,
        judges_usd=0.6,
        probe_usd=0.0,
        unpriced=[],
        rows=tuple(rows),
    )
    plan = {
        "counts": CallCounts(6, 8, 48, 48, 0),
        "cost": cost,
        "overlap": [],
        "probe_lines": [],
        "n_candidates": 4,
        "n_judges": 3,
        "n_prompts": 8,
        "prompts_label": "prompts/tb21.jsonl",
        "prompt_categories": {"easy": 3, "medium": 5},
        "log_path": "battles.jsonl",
    }
    if harness is not None:
        plan["harness"] = harness
    return plan


_HARNESS_PLAN = {
    "plan": {
        "trials": 32,
        "cached": 4,
        "matches": 6,
        "tasks_per_match": 8,
        "task_names": ["fix-git", "build-cython-ext"],
        "difficulty_mix": {"easy": 3, "medium": 4, "hard": 1},
        "images_missing": ["tb/fix-git:1"],
        "agent_timeouts_s": 7200,
        "wall_estimate_s": 10800,
        "cost_note": "agent spend not projected, capped via max_budget_usd",
        "harnesses": [
            {
                "name": "claude-code",
                "agent": "claude-code",
                "model": "anthropic/opus",
                "overlay": "vanilla",
            },
            {
                "name": "pi + skills",
                "agent": "pi",
                "model": "anthropic/opus",
                "overlay": "skills #a1b2",
                "api_format": "openai chat completions",
            },
        ],
    },
    "checks": ["✓ harbor 0.24.0", "⚠ images run under emulation"],
}


async def test_run_plan_renders_the_harness_block():
    host = _Host()
    async with host.run_test(size=(140, 70)) as pilot:
        await host.push_screen(RunPlanScreen(_plan(_HARNESS_PLAN)))
        await pilot.pause()
        screen = host.screen
        table = screen.query_one("#harnesses", DataTable)
        assert table.row_count == 2
        row = [str(table.get_cell_at((1, c))) for c in range(5)]
        assert row == [
            "pi + skills",
            "pi",
            "anthropic/opus",
            "skills #a1b2",
            "openai chat completions",
        ]
        text = " ".join(_text(w) for w in screen.query(Static))
        assert "8 tasks · easy 3 · medium 4 · hard 1" in text
        assert "fix-git · build-cython-ext" in text
        assert "6 matches · 8 tasks each · 32 trials (4 cached) · ≤ 48 jury calls" in text
        assert "agent timeouts total 2h00" in text and "wall estimate ≤ 3h00" in text
        assert "✓ harbor 0.24.0" in text and "1 task image(s) to pull" in text
        assert "PROMPTS" not in text


async def test_run_plan_survives_a_sparse_harness_block():
    host = _Host()
    async with host.run_test(size=(140, 70)) as pilot:
        await host.push_screen(RunPlanScreen(_plan({"plan": {}})))
        await pilot.pause()
        assert host.screen.query_one("#harnesses", DataTable).row_count == 0


async def test_run_plan_without_a_harness_block_is_unchanged():
    host = _Host()
    async with host.run_test(size=(140, 70)) as pilot:
        await host.push_screen(RunPlanScreen(_plan()))
        await pilot.pause()
        assert not host.screen.query("#harnesses")
        assert "PROMPTS" in " ".join(_text(w) for w in host.screen.query(Static))


async def test_leaderboard_adds_harness_columns_and_gate_line():
    report = {
        "harness": {
            "pi": {
                "trials": 8,
                "passed": 6,
                "verified": 8,
                "pass_rate": 0.75,
                "mean_cost_usd": 0.21,
                "mean_duration_s": 246.0,
                "tests_edited": 1,
            },
            "cc": {"trials": 8, "passed": 0, "verified": 0, "pass_rate": None},
        },
        "gate_rounds": 26,
        "rated_rounds": 48,
    }
    screen = LeaderboardScreen(
        elo={"pi": 1050.0, "cc": 950.0}, champion="pi", log_path="x", report=report
    )
    host = _Host()
    async with host.run_test(size=(140, 50)) as pilot:
        await host.push_screen(screen)
        await pilot.pause()
        table = screen.query_one("#table", DataTable)
        cols = [str(c.label) for c in table.columns.values()]
        assert cols == ["Rank", "Harness", "ELO", "pass rate", "$/task", "min/task"]
        assert [str(table.get_cell_at((0, c))) for c in range(3, 6)] == ["6/8", "0.21", "4.1"]
        assert [str(table.get_cell_at((1, c))) for c in range(3, 6)] == ["–", "–", "–"]
        gate = _text(screen.query_one("#gate-line", Static))
        assert "gate decided 26 of 48 rounds" in gate and "jury 22" in gate
        assert "tests/ edited in 1 trial" in gate


async def test_leaderboard_without_harness_has_no_gate_line():
    screen = LeaderboardScreen(
        elo={"a": 1000.0}, champion="a", log_path="x", report={"win_grid": {}}
    )
    host = _Host()
    async with host.run_test(size=(140, 50)) as pilot:
        await host.push_screen(screen)
        await pilot.pause()
        assert not screen.query("#gate-line")
        assert "pass rate" not in [
            str(c.label) for c in screen.query_one("#table", DataTable).columns.values()
        ]


async def test_battle_browser_shows_the_verifier_badge_and_dossier():
    rec = BattleRecord(
        prompt_hash="h",
        prompt_text=TASK,
        model_a="claude-code",
        model_b="pi",
        response_a="## Hidden tests: FAILED\nsome dossier A",
        response_b="## Hidden tests: PASSED\nsome dossier B",
        solution_a={
            "passed": False,
            "reward": 0.0,
            "steps": 23,
            "commands": 14,
            "edits": 6,
            "cost_usd": 0.42,
            "exit_reason": "finished",
            "tests_edited": True,
            "diff_stat": "+14 -3 in 2 files",
        },
        solution_b={"passed": True, "reward": 1.0, "steps": 12, "commands": 8, "edits": 2},
        majority_verdict="B",
        winner="pi",
        judge_votes=[
            {
                "model": "verifier",
                "vote": "B",
                "completed": True,
                "flipped": False,
                "replacement": False,
                "explanation": "hidden tests: A failed, B passed",
                "observations": [],
            }
        ],
    )
    assert rec.decided_by_gate
    screen = BattleBrowserScreen([rec])
    host = _Host()
    async with host.run_test(size=(140, 50)) as pilot:
        await host.push_screen(screen)
        await pilot.pause()
        a, b = _text(screen._resp_a), _text(screen._resp_b)
        assert "✗ hidden tests FAILED" in a and "23 steps" in a and "$0.42" in a
        assert "tests/ edited" in a and "some dossier A" in a
        assert "✓ hidden tests PASSED" in b and "some dossier B" in b
        assert "decided by the verifier gate" in _text(screen._outcome)
        assert "hidden tests: A failed, B passed" in _text(screen._judges)
