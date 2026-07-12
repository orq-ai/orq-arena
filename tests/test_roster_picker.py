"""Picker plumbing: catalog parsing, warrior assignment, screen render."""

from __future__ import annotations

from textual.app import App
from textual.widgets import SelectionList

from orc_arena.config import ArenaConfig
from orc_arena.orcs.roster import ORC_NAME_POOL, WarriorSpec, assign_warriors
from orc_arena.providers.models_list import ModelEntry, _parse_payload, _filter_by_type
from orc_arena.tui.screens.roster_select import RosterSelectScreen


def test_parse_payload_strips_non_chat_and_dupes():
    data = {"data": [
        {"id": "openai/gpt-5.4", "owned_by": "openai", "created": 1},
        {"id": "openai/gpt-5.4", "owned_by": "openai", "created": 1},
        {"id": "openai/text-embedding-3-large", "owned_by": "openai"},
        {"id": "elevenlabs/some-tts-model", "owned_by": "elevenlabs"},
        {"id": "anthropic/claude-opus-4-8", "owned_by": "anthropic"},
    ]}
    models = _parse_payload(data)
    assert [m.id for m in models] == ["openai/gpt-5.4", "anthropic/claude-opus-4-8"]


def test_type_map_filter_keeps_chat_and_unknown():
    entries = [ModelEntry("a/chatty", "a"), ModelEntry("a/imagey", "a"), ModelEntry("a/alias", "a")]
    kept = _filter_by_type(entries, {"a/chatty": "chat", "a/imagey": "image"})
    assert [m.id for m in kept] == ["a/chatty", "a/alias"]


def test_assign_warriors_keeps_configured_specs_and_names_new_ones():
    existing = [WarriorSpec(
        orc_name="Azog Deepmind", model_id="google/gemini-3.1-pro-preview",
        reasoning={"thinking": {"type": "disabled"}},
    )]
    out = assign_warriors(
        ["google/gemini-3.1-pro-preview", "moonshotai/kimi-k2.6"], existing
    )
    assert out[0] is existing[0]                      # spec (incl. reasoning) preserved
    assert out[1].model_id == "moonshotai/kimi-k2.6"
    assert (out[1].orc_name, out[1].emblem) in ORC_NAME_POOL
    assert out[1].orc_name != "Azog Deepmind"
    assert out[1].reasoning is None                   # probe is the safety net


class _Host(App):
    pass


async def test_picker_mounts_and_counts_update():
    cfg = ArenaConfig.model_validate({
        "warriors": [
            {"orc_name": "A", "model_id": "x/a"},
            {"orc_name": "B", "model_id": "x/b"},
        ],
        "judges": ["x/j1", "x/j2", "x/j3"],
    })
    screen = RosterSelectScreen(cfg, prompt_count=10)
    app = _Host()
    async with app.run_test(size=(120, 40)) as pilot:
        await app.push_screen(screen)
        await pilot.pause()
        assert isinstance(screen.query_one(SelectionList), SelectionList)
        # preselected roster from cfg -> 2 chosen -> counts line present
        assert "1 matches" in screen._counts_line() or "matches" in screen._counts_line()
        screen._chosen = ["x/a", "x/b", "x/c"]
        assert "3 matches" in screen._counts_line()
