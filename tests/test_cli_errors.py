"""A missing config YAML is a clean CLI error, never a traceback."""

import pytest
from click.testing import CliRunner

from orq_arena.cli import cli


@pytest.mark.parametrize(
    "argv",
    [
        ["run", "-y"],
        ["list-models"],
        ["report", "whatever.jsonl"],
    ],
)
def test_missing_config_is_a_clean_error(monkeypatch, tmp_path, argv):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, argv)
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "orq_arena.yaml not found" in result.output
