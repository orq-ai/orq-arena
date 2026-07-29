"""Unknown YAML keys are rejected, not silently dropped (RES-1156).

A typo like ``replacment_judges:`` used to configure nothing while the run
went ahead as if it had; every config-surface model now forbids extras and
the CLI turns the rejection into a did-you-mean.
"""

from __future__ import annotations

import json
from pathlib import Path

import click
import pytest
import yaml
from pydantic import ValidationError

from orq_arena.cli import _load_config
from orq_arena.config import load_config
from orq_arena.tournament.driver import config_from_manifest

ROOT = Path(__file__).resolve().parent.parent

BASE = {
    "candidates": [{"model_id": "x/a"}, {"model_id": "x/b"}],
    "judges": ["x/j"],
}


def _write(tmp_path: Path, cfg: dict) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return p


def test_unknown_top_level_key_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="replacment_judges"):
        load_config(_write(tmp_path, {**BASE, "replacment_judges": ["x/r"]}))


def test_unknown_gateway_key_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="base_uri"):
        load_config(_write(tmp_path, {**BASE, "gateway": {"base_uri": "https://x"}}))


def test_unknown_match_key_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="max_round"):
        load_config(_write(tmp_path, {**BASE, "match": {"max_round": 3}}))


def test_unknown_preflight_key_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="thinking_prob"):
        load_config(_write(tmp_path, {**BASE, "preflight": {"thinking_prob": False}}))


def test_unknown_candidate_key_rejected(tmp_path: Path) -> None:
    cfg = {**BASE, "candidates": [{"model_id": "x/a", "reasonning": {}}, {"model_id": "x/b"}]}
    with pytest.raises(ValidationError, match="reasonning"):
        load_config(_write(tmp_path, cfg))


def test_cli_suggests_the_intended_key(tmp_path: Path) -> None:
    p = _write(tmp_path, {**BASE, "replacment_judges": ["x/r"]})
    with pytest.raises(click.ClickException) as excinfo:
        _load_config(str(p))
    msg = excinfo.value.message
    assert str(p) in msg
    assert "unknown setting 'replacment_judges'" in msg
    assert "did you mean 'replacement_judges'?" in msg


def test_cli_names_nested_location(tmp_path: Path) -> None:
    p = _write(tmp_path, {**BASE, "gateway": {"base_urll": "https://x"}})
    with pytest.raises(click.ClickException) as excinfo:
        _load_config(str(p))
    assert "unknown setting 'gateway.base_urll'" in excinfo.value.message
    assert "did you mean 'base_url'?" in excinfo.value.message


def test_cli_still_renders_non_extra_errors(tmp_path: Path) -> None:
    p = _write(tmp_path, {**BASE, "candidates": [{"model_id": "x/a"}]})
    with pytest.raises(click.ClickException) as excinfo:
        _load_config(str(p))
    assert "at least 2 candidates" in excinfo.value.message


@pytest.mark.parametrize(
    "path",
    [
        ROOT / "orq_arena.yaml",
        ROOT / "examples" / "quickstart" / "config.yaml",
        *sorted((ROOT / "configs").glob("*.yaml")),
    ],
    ids=lambda p: p.name,
)
def test_every_shipped_yaml_still_loads(path: Path) -> None:
    assert load_config(path).candidates


def test_suggestion_pool_omits_output_only_fields() -> None:
    from orq_arena.config import known_config_keys

    keys = known_config_keys()
    assert "replacement_judges" in keys
    # 'renamed' is computed by validation, never a key a user may write.
    assert "renamed" not in keys


def test_quickstart_manifest_rebuild_survives_strictness() -> None:
    manifest_path = ROOT / "examples" / "quickstart" / "battles.run.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    fallback = load_config(ROOT / "examples" / "quickstart" / "config.yaml")
    cfg, source = config_from_manifest(manifest, fallback)
    assert cfg is not None
    # pre-config-blob manifest, so identity is rebuilt from its candidate map;
    # the assertion is that strictness did not knock it down to "config".
    assert source == "manifest-partial"
