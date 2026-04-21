"""Config loader: default orc_arena.yaml must parse with 8 warriors + 3 judges."""

from __future__ import annotations

from pathlib import Path

from orc_arena.config import load_config

ROOT = Path(__file__).resolve().parent.parent


def test_default_config_loads_with_full_roster() -> None:
    cfg = load_config(ROOT / "orc_arena.yaml")
    assert len(cfg.warriors) == 8
    assert len(cfg.judges) == 3
    assert cfg.match.starting_hp == 100
    assert cfg.match.max_rounds == 5
    assert cfg.gateway.base_url.startswith("https://api.orq.ai")


def test_warrior_short_model_strips_provider_prefix() -> None:
    cfg = load_config(ROOT / "orc_arena.yaml")
    assert cfg.warriors[0].short_model == "claude-opus-4-7"
    assert "/" not in cfg.warriors[0].short_model
