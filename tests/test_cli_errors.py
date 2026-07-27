"""A missing config YAML is a clean CLI error, never a traceback."""

import pytest
from click.testing import CliRunner

from orq_arena.cli import cli


@pytest.mark.parametrize(
    "argv",
    [
        ["run", "-y", "--config", "missing.yaml"],
        ["pool", "--config", "missing.yaml"],
        # `report` errors on the missing log first now, which is still the
        # clean-error contract this test is about.
        ["report", "whatever.jsonl"],
    ],
)
def test_missing_config_is_a_clean_error(monkeypatch, tmp_path, argv):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, argv)
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "not found" in result.output


@pytest.mark.parametrize("argv", [["run", "-y"], ["pool"]])
def test_config_is_required(monkeypatch, tmp_path, argv):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, argv)
    assert result.exit_code != 0
    assert "--config" in result.output


def test_report_without_a_manifest_or_a_config_is_a_clean_error(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "battles.jsonl").write_text(
        '{"prompt_hash":"h","prompt_text":"p","model_a":"a","model_b":"b"}\n', encoding="utf-8"
    )
    result = CliRunner().invoke(cli, ["report", "battles.jsonl"])
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "pass --config" in result.output


def test_list_models_json_is_parseable(tmp_path, monkeypatch):
    import json
    from pathlib import Path

    yaml = Path("orq_arena.yaml").resolve()
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ["pool", "--config", str(yaml), "--json"])
    assert result.exit_code == 0, result.output
    pool = json.loads(result.stdout)
    assert pool and {"seed", "name", "model_id"} <= set(pool[0])


def test_run_without_yes_fails_fast_on_non_tty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # The --yes gate fires before the config is ever read, so the file
    # named here doesn't need to exist.
    result = CliRunner().invoke(cli, ["run", "--config", "any.yaml"])
    assert result.exit_code != 0
    assert "pass --yes" in result.output
