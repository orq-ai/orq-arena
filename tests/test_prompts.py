"""Prompt loaders: JSONL parsing and orq.ai datapoint mapping."""

from __future__ import annotations

import pytest

from orq_arena.data.prompts import datapoint_to_prompt, load_prompts


def test_jsonl_loader_reads_prompt_and_category(tmp_path) -> None:
    f = tmp_path / "p.jsonl"
    f.write_text('{"prompt": "hi", "category": "code"}\n\n{"text": "yo"}\n')
    items = load_prompts(f)
    assert [(i.text, i.category) for i in items] == [("hi", "code"), ("yo", "general")]


def test_datapoint_maps_last_user_message_with_inputs() -> None:
    item = datapoint_to_prompt(
        inputs={"country": "France"},
        messages=[
            {"role": "system", "content": "be brief"},
            {"role": "user", "content": "Capital of {{ country }}?"},
            {"role": "assistant", "content": "Paris"},
        ],
    )
    assert item is not None
    assert item.text == "Capital of France?"
    assert item.category == "general"


def test_datapoint_without_user_message_is_skipped() -> None:
    assert datapoint_to_prompt(None, [{"role": "assistant", "content": "x"}]) is None
    assert datapoint_to_prompt(None, None) is None


def test_datapoint_content_parts_are_joined() -> None:
    item = datapoint_to_prompt(
        inputs=None,
        messages=[{"role": "user", "content": [{"type": "text", "text": "part one"},
                                               {"type": "text", "text": "part two"}]}],
    )
    assert item is not None and item.text == "part one\npart two"


def test_orq_scheme_requires_api_key(monkeypatch) -> None:
    monkeypatch.delenv("ORQ_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ORQ_API_KEY"):
        load_prompts("orq:some_dataset_id")
