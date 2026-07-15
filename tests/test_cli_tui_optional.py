"""The core CLI runs without the [tui] extra; TUI paths give a friendly hint."""

import builtins

from click.testing import CliRunner

from orq_arena.cli import cli


def _hide_textual(monkeypatch):
    """Make any `import textual...` raise ModuleNotFoundError, as if uninstalled."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "textual" or name.startswith("textual."):
            raise ModuleNotFoundError(f"No module named '{name}'", name="textual")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    # tui.app may already be cached from another test; force the lazy re-import.
    import sys

    for mod in list(sys.modules):
        if mod == "orq_arena.tui" or mod.startswith("orq_arena.tui."):
            monkeypatch.delitem(sys.modules, mod, raising=False)


def test_roster_picker_without_textual_gives_hint(monkeypatch, tmp_path):
    _hide_textual(monkeypatch)
    monkeypatch.chdir(tmp_path)
    # no --config -> picker path (TUI); should fail with the install hint
    result = CliRunner().invoke(cli, ["run"])
    assert result.exit_code != 0
    assert "orq-arena[tui]" in result.output
    assert "--config" in result.output


def test_demo_without_textual_gives_hint(monkeypatch):
    _hide_textual(monkeypatch)
    result = CliRunner().invoke(cli, ["demo"])
    assert result.exit_code != 0
    assert "orq-arena[tui]" in result.output


def test_help_works_without_textual(monkeypatch):
    _hide_textual(monkeypatch)
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "rejudge" in result.output
