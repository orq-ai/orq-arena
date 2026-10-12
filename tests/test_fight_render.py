"""Headless render test: the fight screen survives a full match lifecycle.

Exists because JudgeCard once shadowed Textual's internal Widget._render and
only exploded at render time, which no logic test could catch.
"""

from __future__ import annotations

from textual.app import App

from orq_arena.tui.screens.fight import FightScreen


class _Host(App):
    pass


async def test_fight_screen_full_match_lifecycle():
    screen = FightScreen(["haiku", "flash-lite", "nano"])
    app = _Host()
    async with app.run_test(size=(120, 40)) as pilot:
        await app.push_screen(screen)
        await pilot.pause()

        screen.start_match(
            "Grak",
            "anthropic/claude-opus-4-8",
            "⚔",
            False,
            "Snot",
            "openai/gpt-5.4-mini",
            "🏹",
            True,
            100,
        )
        screen.set_standings({"Grak": 1010.0, "Snot": 990.0}, 1, 28)
        screen.set_prompt(1, "Why is the sky blue?")
        screen.append_thinking("b", "hmm, Rayleigh scattering...")
        screen.append_response("a", "Because of Rayleigh scattering.")
        screen.append_response("b", "Short answer: physics.")
        screen.response_complete(
            "a", tokens_out=120, reasoning_tokens=0, finish_reason="stop", error=None
        )
        screen.response_complete(
            "b", tokens_out=90, reasoning_tokens=64, finish_reason="length", error=None
        )
        screen.set_judge_verdict("haiku", "A", "clearer and complete")
        screen.set_judge_verdict("flash-lite", "abstain", "", flipped=True)
        screen.set_judge_verdict("nano", "tie", "both fine")
        screen.set_judge_verdict("stand-in-judge", "B", "unknown card -> status line")
        screen.apply_damage(100, 85, "A", 15, "b")
        await pilot.pause()

        # KO path + void + draw banner
        screen.apply_damage(100, 0, "A", 30, "b")
        screen.round_voided("Snot: stream failed after retry, boom")
        screen.match_resolved("Grak", ko=True)
        screen.match_resolved("")
        await pilot.pause()

        assert screen._card_b.has_class("ko")
        assert screen._judges["flash-lite"].has_class("verdict-abstain")
        assert screen._judges["haiku"].has_class("verdict-a")

        # next round keeps previous verdicts visible, dimmed
        screen.set_prompt(2, "Second question?")
        await pilot.pause()
        assert screen._judges["haiku"].has_class("stale")
        assert screen._judges["haiku"].has_class("verdict-a")  # still shows the vote
        screen.set_judge_verdict("haiku", "B", "changed my mind")
        assert not screen._judges["haiku"].has_class("stale")
        assert screen._judges["haiku"].has_class("verdict-b")


def _card_text(screen, name: str) -> str:
    return str(screen._judges[name].render())


async def test_fight_screen_decision_votes_show_probability_bars():
    screen = FightScreen(["jev-latest", "decider-4b", "gpt-6-luna"], abstain_below=0.5)
    app = _Host()
    async with app.run_test(size=(140, 40)) as pilot:
        await app.push_screen(screen)
        await pilot.pause()
        screen.set_judge_verdict(
            "jev-latest", "A", "", probabilities={"A": 0.71, "B": 0.18, "tie": 0.11}
        )
        screen.set_judge_verdict(
            "decider-4b", "abstain", "", probabilities={"A": 0.46, "B": 0.41, "tie": 0.13}
        )
        screen.set_judge_verdict(
            "gpt-6-luna",
            "abstain",
            "",
            probabilities={"A": 0.45, "B": 0.47, "tie": 0.08},
            flipped=True,
        )
        screen.set_judge_verdict(
            "typesafe/jev-mini", "B", "", probabilities={"A": 0.3, "B": 0.6, "tie": 0.1}
        )
        await pilot.pause()

        decided = _card_text(screen, "jev-latest")
        assert "→ A  0.71" in decided
        assert "A ████████████████░░░░░░ 71%" in decided
        assert "= ██░░░░░░░░░░░░░░░░░░░░ 11%" in decided
        assert screen._judges["jev-latest"].has_class("verdict-a")

        floored = _card_text(screen, "decider-4b")
        assert "✕ abstain" in floored
        assert "top 0.46 under the 0.50 floor" in floored
        assert screen._judges["decider-4b"].has_class("verdict-abstain")

        flipped = _card_text(screen, "gpt-6-luna")
        assert "flipped when sides swapped" in flipped
        assert "47%" in flipped
        assert "floor" not in flipped  # a flip is not a floor abstention

        assert "votes B (0.60)" in str(screen._status.render())


async def test_same_suffix_judges_get_their_own_cards():
    from orq_arena.config import ArenaConfig
    from orq_arena.events import JudgeVerdictEvent
    from orq_arena.tui.app import ArenaApp

    cfg = ArenaConfig.model_validate(
        {
            "candidates": [
                {"name": "Alpha", "model_id": "x/alpha"},
                {"name": "Beta", "model_id": "x/beta"},
            ],
            "judges": ["openai/gpt-oss-120b", "groq/gpt-oss-120b", "x/nano"],
        }
    )
    app = ArenaApp(cfg=cfg, prompts=[], battle_log_path="unused.jsonl")
    labels = [app._judge_labels[m] for m in cfg.judges]
    assert labels == ["openai/gpt-oss-120b", "groq/gpt-oss-120b", "nano"]

    screen = FightScreen(labels)
    host = _Host()
    async with host.run_test(size=(140, 40)) as pilot:
        await host.push_screen(screen)
        await pilot.pause()
        app._fight_screen = screen  # route events without starting the engine
        for judge, verdict in (("openai/gpt-oss-120b", "A"), ("groq/gpt-oss-120b", "B")):
            app._handle_event(
                JudgeVerdictEvent(match_id="m", judge_name=judge, verdict=verdict, reasoning="r")
            )
        await pilot.pause()
        assert screen._judges["openai/gpt-oss-120b"].has_class("verdict-a")
        assert screen._judges["groq/gpt-oss-120b"].has_class("verdict-b")
