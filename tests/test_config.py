"""Config loader: default orq_arena.yaml must parse with 8 candidates + 3 judges."""

from __future__ import annotations

from pathlib import Path

from orq_arena.config import load_config

ROOT = Path(__file__).resolve().parent.parent


def test_default_config_loads_with_full_roster() -> None:
    cfg = load_config(ROOT / "orq_arena.yaml")
    assert len(cfg.candidates) == 8
    assert len(cfg.judges) == 3
    assert cfg.match.starting_hp == 100
    assert cfg.match.max_rounds == 5
    assert cfg.gateway.base_url.startswith("https://api.orq.ai")


def test_warrior_short_model_strips_provider_prefix() -> None:
    cfg = load_config(ROOT / "orq_arena.yaml")
    assert cfg.candidates[0].short_model == "claude-opus-4-8"
    assert "/" not in cfg.candidates[0].short_model


def test_reasoning_config_loads_uniform_on() -> None:
    cfg = load_config(ROOT / "configs" / "reasoning_arena.yaml")
    assert len(cfg.candidates) == 8
    # always-thinking models (deepseek-reasoner, kimi-k2*) carry no config
    # block, so the flag undercounts them by design.
    assert sum(w.thinking_enabled for w in cfg.candidates) >= 5


def test_default_pool_is_uniform_thinking_off() -> None:
    cfg = load_config(ROOT / "orq_arena.yaml")
    assert not any(w.thinking_enabled for w in cfg.candidates)


def test_thinking_budget_must_fit_max_tokens() -> None:
    import pytest
    from orq_arena.config import ArenaConfig

    bad = {
        "warriors": [
            {"name": "A", "model_id": "x/a"},
            {
                "name": "B",
                "model_id": "x/b",
                "reasoning": {"thinking": {"type": "enabled", "budget_tokens": 2048}},
                "max_tokens": 1024,
            },
        ],
        "judges": ["x/j"],
    }
    with pytest.raises(ValueError, match="budget_tokens"):
        ArenaConfig.model_validate(bad)


def test_deprecated_warriors_yaml_alias_still_loads(tmp_path) -> None:
    """Pre-rename configs keep working: warriors/warrior_max_tokens/orc_name."""
    legacy = tmp_path / "legacy.yaml"
    legacy.write_text(
        """
gateway:
  warrior_max_tokens: 1024
warriors:
  - model_id: prov/model-a
    orc_name: Alpha
  - model_id: prov/model-b
judges: [prov/judge-1]
""",
        encoding="utf-8",
    )
    cfg = load_config(legacy)
    assert [c.name for c in cfg.candidates] == ["Alpha", "model-b"]
    assert cfg.gateway.candidate_max_tokens == 1024
