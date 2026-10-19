"""Harness candidates: config loading, identity, overlay validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orq_arena.candidates import CandidateSpec, HarnessCandidate
from orq_arena.config import ArenaConfig, known_config_keys
from orq_arena.data.schemas import BattleRecord
from orq_arena.tournament.driver import config_from_manifest, record_names


def _cfg(*candidates: dict, **extra) -> ArenaConfig:
    return ArenaConfig.model_validate({"candidates": list(candidates), "judges": ["x/j"], **extra})


def _h(**kw) -> dict:
    return {"kind": "harness", "agent": "pi", "model_id": "anthropic/m", **kw}


def test_old_yaml_without_kind_still_loads_as_a_model():
    cfg = _cfg({"model_id": "a/one"}, {"model_id": "b/two"})
    assert all(isinstance(c, CandidateSpec) for c in cfg.candidates)
    assert not cfg.has_harness
    # a model candidate dumps exactly as it did before kinds existed
    assert "kind" not in cfg.candidates[0].model_dump()


def test_harness_spec_round_trips_through_the_manifest_config():
    cfg = _cfg(
        _h(name="pi", agent_kwargs={"max_turns": 60}),
        _h(name="cc", agent="claude-code", model_id="anthropic/c"),
        {"model_id": "a/one"},
    )
    again = ArenaConfig.model_validate(cfg.model_dump(mode="json"))
    assert [c.candidate_id for c in again.candidates] == [c.candidate_id for c in cfg.candidates]
    rebuilt, source = config_from_manifest({"config": cfg.model_dump(mode="json")}, cfg)
    assert source == "manifest"
    assert rebuilt is not None and rebuilt.has_harness


def test_two_setups_of_one_agent_and_model_are_two_candidates(tmp_path):
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "SKILL.md").write_text("be careful")
    cfg = _cfg(
        _h(),
        _h(overlay={"skills": str(skills)}),
    )
    plain, with_skills = cfg.candidates
    assert plain.variant == "" and with_skills.variant
    assert plain.candidate_id == "pi:anthropic/m"
    assert with_skills.candidate_id == f"pi:anthropic/m#{with_skills.variant}"
    assert plain.name != with_skills.name


def test_editing_a_skill_file_changes_the_variant(tmp_path):
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "SKILL.md").write_text("v1")
    first = HarnessCandidate.model_validate(_h(overlay={"skills": str(skills)}))
    (skills / "SKILL.md").write_text("v2")
    second = HarnessCandidate.model_validate(_h(overlay={"skills": str(skills)}))
    assert first.variant != second.variant


def test_the_same_agent_setup_twice_is_rejected():
    with pytest.raises(ValidationError, match="listed twice"):
        _cfg(_h(name="pi"), _h(name="pi"))


def test_overlay_an_agent_cannot_honor_names_the_agent():
    with pytest.raises(ValidationError, match="pi.*memory"):
        _cfg(_h(overlay={"memory": "/tmp"}), _h(agent="codex", model_id="openai/c"))
    with pytest.raises(ValidationError, match="codex.*memory"):
        _cfg(_h(agent="codex", model_id="openai/c", overlay={"memory": "/tmp"}), _h())


def test_overlay_translates_to_harbor_arguments(tmp_path):
    c = HarnessCandidate.model_validate(
        _h(
            agent="claude-code",
            model_id="anthropic/c",
            overlay={
                "skills": str(tmp_path),
                "memory": str(tmp_path),
                "system_prompt": "be brief",
                "settings": {"a": 1},
            },
        )
    )
    args = c.overlay.to_kwargs("claude-code")
    assert args.skills == [str(tmp_path.resolve())]
    assert args.kwargs["memory_dir"] == str(tmp_path.resolve())
    assert args.kwargs["append_system_prompt"] == "be brief"
    assert args.kwargs["config"] == '{"a": 1}'
    pi = HarnessCandidate.model_validate(_h(overlay={"system_prompt": "be brief"}))
    assert pi.overlay.to_kwargs("pi").extra_instruction == "be brief"


def test_overlay_clashing_with_agent_kwargs_is_rejected(tmp_path):
    with pytest.raises(ValidationError, match="duplicate"):
        _cfg(
            _h(
                agent="claude-code",
                model_id="anthropic/c",
                agent_kwargs={"memory_dir": "x"},
                overlay={"memory": str(tmp_path)},
            ),
            _h(),
        )


def test_the_model_must_suit_the_agent():
    with pytest.raises(ValidationError, match="anthropic"):
        HarnessCandidate.model_validate(_h(agent="claude-code", model_id="openai/m"))
    with pytest.raises(ValidationError, match="openai"):
        HarnessCandidate.model_validate(_h(agent="codex", model_id="anthropic/m"))
    with pytest.raises(ValidationError, match="not supported"):
        HarnessCandidate.model_validate(_h(agent="gemini-cli"))


def test_record_names_separates_variants():
    cfg = _cfg(_h(name="pi"), _h(name="pi plus", agent_kwargs={"thinking": "high"}))
    a, b = cfg.candidates
    rec = BattleRecord(
        prompt_hash="h",
        prompt_text="t",
        model_a="pi",
        model_b="pi plus",
        model_a_id=a.candidate_id,
        model_b_id=b.candidate_id,
    )
    names = record_names([rec], cfg.candidates)
    assert names[a.candidate_id] == "pi" and names[b.candidate_id] == "pi plus"


def test_harness_config_keys_are_known_to_the_suggester():
    keys = known_config_keys()
    assert {"agent", "agent_kwargs", "harbor_bin", "verifier_gate", "overlay"} <= set(keys)


def test_decision_judges_are_refused_with_a_harness():
    with pytest.raises(ValidationError, match="decisions"):
        _cfg(_h(), _h(agent="codex", model_id="openai/c"), judge_api="decisions")


def test_a_unknown_harness_key_is_a_typo_not_a_silent_drop():
    with pytest.raises(ValidationError):
        _cfg(_h(agnet_kwargs={}), _h(agent="codex", model_id="openai/c"))
