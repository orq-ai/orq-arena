"""Headless render test: the fight screen survives a full match lifecycle.

Exists because JudgeCard once shadowed Textual's internal Widget._render and
only exploded at render time — which no logic test could catch.
"""

from __future__ import annotations

from textual.app import App

from orc_arena.tui.screens.fight import FightScreen


class _Host(App):
    pass


async def test_fight_screen_full_match_lifecycle():
    screen = FightScreen(["haiku", "flash-lite", "nano"])
    app = _Host()
    async with app.run_test(size=(120, 40)) as pilot:
        await app.push_screen(screen)
        await pilot.pause()

        screen.start_match(
            "Grak", "anthropic/claude-opus-4-8", "⚔", False,
            "Snot", "openai/gpt-5.4-mini", "🏹", True,
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
        screen.round_voided("Snot: stream failed after retry — boom")
        screen.match_resolved("Grak", "ko")
        screen.match_resolved("", "draw")
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
