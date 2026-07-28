"""Two models must never quietly become one.

The regression: display names default to the model id with its provider prefix
stripped, so `openai/gpt-oss-120b` and `groq/gpt-oss-120b` both became
`gpt-oss-120b`. The alias map collapsed to a single key and the two models were
rated as one, with nothing printed to say so.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orq_arena.config import ArenaConfig


def _cfg(candidates: list[dict]) -> ArenaConfig:
    return ArenaConfig.model_validate({"candidates": candidates, "judges": ["prov/j1", "prov/j2"]})


def test_the_same_model_from_two_providers_keeps_two_identities():
    cfg = _cfg([{"model_id": "openai/gpt-oss-120b"}, {"model_id": "groq/gpt-oss-120b"}])
    names = [c.name for c in cfg.candidates]
    assert len(set(names)) == 2, f"both models answer to {names[0]!r}"


def test_a_collision_falls_back_to_the_full_model_id():
    """The full id is the one name that is unique by construction."""
    cfg = _cfg([{"model_id": "openai/gpt-oss-120b"}, {"model_id": "groq/gpt-oss-120b"}])
    assert {c.name for c in cfg.candidates} == {"openai/gpt-oss-120b", "groq/gpt-oss-120b"}


def test_uncontested_short_names_stay_short():
    """The fallback only fires on a real collision; ordinary pools read the same."""
    cfg = _cfg([{"model_id": "openai/gpt-5.4"}, {"model_id": "anthropic/claude-opus-4-8"}])
    assert [c.name for c in cfg.candidates] == ["gpt-5.4", "claude-opus-4-8"]


def test_an_explicit_duplicate_name_is_rejected_not_silently_merged():
    """A custom name is the user's own doing, so say so instead of guessing."""
    with pytest.raises(ValidationError, match="[Dd]uplicate"):
        _cfg(
            [
                {"model_id": "openai/gpt-5.4", "name": "champ"},
                {"model_id": "anthropic/claude-opus-4-8", "name": "champ"},
            ]
        )


def test_a_users_name_wins_and_the_generated_one_moves_aside():
    """Only a duplicate the user wrote themselves is an error; a generated name
    is ours to change, so it yields to the explicit one."""
    cfg = _cfg(
        [
            {"model_id": "openai/gpt-5.4"},
            {"model_id": "anthropic/claude-opus-4-8", "name": "gpt-5.4"},
        ]
    )
    assert [c.name for c in cfg.candidates] == ["openai/gpt-5.4", "gpt-5.4"]


def test_records_carry_the_full_model_id_so_a_log_is_unambiguous():
    from orq_arena.data.schemas import BattleRecord

    rec = BattleRecord(
        prompt_hash="h",
        prompt_text="p",
        model_a="gpt-oss-120b",
        model_b="gpt-oss-120b",
        model_a_id="openai/gpt-oss-120b",
        model_b_id="groq/gpt-oss-120b",
    )
    assert rec.model_a_id != rec.model_b_id


def test_v3_logs_without_model_ids_still_load():
    """Old logs predate the field; they must not fail to parse."""
    from orq_arena.data.schemas import BattleRecord

    rec = BattleRecord.model_validate_json(
        '{"prompt_hash":"h","prompt_text":"p","model_a":"a","model_b":"b"}'
    )
    assert rec.model_a_id == "" and rec.model_b_id == ""


def test_two_providers_of_one_model_are_rated_separately(tmp_path):
    """The end of the chain: distinct names are useless if the rebuild still
    keys on the colliding short name."""
    from orq_arena.data.schemas import BattleRecord
    from orq_arena.tournament.driver import rebuild_from_log

    cfg = _cfg([{"model_id": "openai/gpt-oss-120b"}, {"model_id": "groq/gpt-oss-120b"}])
    records = [
        BattleRecord(
            prompt_hash=f"h{i}",
            prompt_text="p",
            model_a="gpt-oss-120b",
            model_b="gpt-oss-120b",
            model_a_id="openai/gpt-oss-120b",
            model_b_id="groq/gpt-oss-120b",
            response_a="x",
            response_b="y",
            majority_verdict="A",
            winner="gpt-oss-120b",
            judge_votes=[{"model": "prov/j1", "vote": "A"}],
        )
        for i in range(6)
    ]
    elo, _ = rebuild_from_log(cfg, records)
    assert set(elo) == {"openai/gpt-oss-120b", "groq/gpt-oss-120b"}
    assert elo["openai/gpt-oss-120b"] > elo["groq/gpt-oss-120b"]


def test_a_v3_log_without_ids_still_rebuilds_on_short_names():
    from orq_arena.data.schemas import BattleRecord
    from orq_arena.tournament.driver import rebuild_from_log

    cfg = _cfg([{"model_id": "openai/gpt-5.4"}, {"model_id": "anthropic/claude-opus-4-8"}])
    records = [
        BattleRecord(
            prompt_hash="h",
            prompt_text="p",
            model_a="gpt-5.4",
            model_b="claude-opus-4-8",
            response_a="x",
            response_b="y",
            majority_verdict="A",
            winner="gpt-5.4",
            judge_votes=[{"model": "prov/j1", "vote": "A"}],
        )
    ]
    elo, _ = rebuild_from_log(cfg, records)
    assert set(elo) == {"gpt-5.4", "claude-opus-4-8"}


def test_prompt_provenance_distinguishes_two_banks_that_differ_only_by_category():
    """The manifest hash used to cover prompt texts only, so re-labelling every
    prompt's category produced an identical hash and looked like the same bank."""
    import tempfile
    from pathlib import Path

    from orq_arena.data.prompts import PromptItem
    from orq_arena.tournament.driver import _write_manifest, manifest_path_for, read_manifest

    cfg = _cfg([{"model_id": "p/a"}, {"model_id": "p/b"}])

    def _hash(prompts):
        d = Path(tempfile.mkdtemp())
        _write_manifest(
            manifest_path_for(d / "battles.jsonl"),
            cfg=cfg,
            prompts=prompts,
            seed=42,
            tournament_id="t",
            started_at=0.0,
        )
        return read_manifest(d / "battles.jsonl")["prompts_sha256"]

    same_text_code = [PromptItem(text="write a parser", category="code")]
    same_text_general = [PromptItem(text="write a parser", category="general")]
    assert _hash(same_text_code) != _hash(same_text_general)


def test_dataset_prompts_carry_their_category():
    """Without this every dataset-sourced prompt landed in "general" and
    per-category ELO was dead for dataset runs."""
    from orq_arena.data.prompts import datapoint_to_prompt

    item = datapoint_to_prompt({"category": "math"}, [{"role": "user", "content": "what is 2+2?"}])
    assert item is not None and item.category == "math"

    untagged = datapoint_to_prompt({}, [{"role": "user", "content": "hi"}])
    assert untagged is not None and untagged.category == "general"
