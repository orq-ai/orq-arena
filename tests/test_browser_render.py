"""Battle browser renders real schema-v2 records headlessly."""

from pathlib import Path

from textual.app import App

from orq_arena.data.schemas import BattleRecord
from orq_arena.tui.screens.battle_browser import BattleBrowserScreen

LOG = Path(__file__).resolve().parent.parent / "outputs" / "smoke" / "pr5.jsonl"


def _records():
    if LOG.exists():
        return [
            BattleRecord.model_validate_json(ln)
            for ln in LOG.read_text().splitlines()
            if ln.strip()
        ]
    return [
        BattleRecord(
            prompt_hash="h",
            prompt_text="p?",
            model_a="ma",
            model_b="mb",
            response_a="ra",
            response_b="rb",
            majority_verdict="A",
            winner="ma",
            judge_votes=[
                {
                    "model": "x/j",
                    "vote": "A",
                    "flipped": False,
                    "replacement": False,
                    "explanation": "clear",
                }
            ],
        )
    ]


class _Host(App):
    pass


async def test_browser_pages_through_records():
    records = _records()
    screen = BattleBrowserScreen(records)
    app = _Host()
    async with app.run_test(size=(130, 44)) as pilot:
        await app.push_screen(screen)
        await pilot.pause()
        assert screen._idx == 0
        screen.action_next()
        await pilot.pause()
        assert screen._idx == (1 % len(records))


async def test_browser_shows_decision_probabilities_inline():
    def obs(ordering, probs):
        return {"ordering": ordering, "raw_output": {"probabilities": probs}}

    record = BattleRecord(
        prompt_hash="h",
        prompt_text="p?",
        model_a="ma",
        model_b="mb",
        response_a="ra",
        response_b="rb",
        majority_verdict="A",
        winner="ma",
        judge_votes=[
            {
                "model": "typesafe/jev-latest",
                "vote": "A",
                "flipped": False,
                "replacement": False,
                "explanation": "P(A)=.71 P(B)=.18 tie=.11",
                # second seat order is swapped: its "B" was response A
                "observations": [
                    obs("ab", {"A": 0.70, "B": 0.19, "tie": 0.11}),
                    obs("ba", {"A": 0.17, "B": 0.72, "tie": 0.11}),
                ],
            },
            {
                "model": "x/llm-judge",
                "vote": "B",
                "flipped": False,
                "replacement": False,
                "explanation": "second answer is tighter",
            },
        ],
    )
    screen = BattleBrowserScreen([record])
    app = _Host()
    async with app.run_test(size=(130, 44)) as pilot:
        await app.push_screen(screen)
        await pilot.pause()
        jury = str(screen._judges.render())
        assert "jev-latest → A   A 71% · B 18% · tie 11%" in jury
        assert "P(A)=" not in jury  # the numbers replace the restated explanation
        assert "llm-judge → B" in jury
        assert "second answer is tighter" in jury
