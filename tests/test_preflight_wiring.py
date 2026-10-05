"""The preflight checks are wired into the commands, not merely implemented.

Both of these were unit-tested and neither was connected under test, so the
suite stayed green through mutations that disarmed them: inverting the
credential gate made `run` abort on a good key and proceed on a bad one, and
deleting the `config_warnings` block removed the warnings from the run plan a
user consents to before paying. A check nothing calls is not a check.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from orq_arena.cli import cli
from orq_arena.config import ORQ_API_KEY_ENV

CONFIG = """
candidates:
  - model_id: p/cand-a
  - model_id: p/cand-b
judges:
  - p/judge-1
  - p/judge-2
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "arena.yaml").write_text(CONFIG, encoding="utf-8")
    (tmp_path / "prompts.jsonl").write_text('{"text": "say hi"}\n', encoding="utf-8")
    monkeypatch.setenv(ORQ_API_KEY_ENV, "sk-orq-test")
    return tmp_path


def _no_catalog(monkeypatch):
    """No prices, no warnings: this file is about the wiring, not the content."""
    from orq_arena import cli as cli_mod

    async def _empty(_cfg, **_kw):
        return {}

    monkeypatch.setattr("orq_arena.providers.models_list.fetch_catalog", _empty)
    monkeypatch.setattr("orq_arena.providers.models_list.fetch_price_map", _empty)
    return cli_mod


def _invoke_run(monkeypatch, verdict):
    _no_catalog(monkeypatch)

    async def _verify(_gw, **_kw):
        return verdict

    monkeypatch.setattr("orq_arena.providers.credentials.verify_credential", _verify)
    return CliRunner().invoke(
        cli, ["run", "-y", "--config", "arena.yaml", "--prompts", "prompts.jsonl"]
    )


def test_a_rejected_key_stops_run_before_it_spends(project, monkeypatch):
    result = _invoke_run(monkeypatch, (False, "the router rejected ORQ_API_KEY (401)."))

    assert result.exit_code != 0
    assert "401" in result.output
    # the run never got as far as writing its log
    assert not (project / "battles.jsonl").exists()


def test_an_unreachable_router_warns_but_lets_the_run_try(project, monkeypatch):
    """Being offline is not a verdict on the key, and refusing to run on that
    basis would be wrong exactly when the user can least afford it."""
    result = _invoke_run(monkeypatch, (None, "could not reach the router"))

    assert "could not reach the router" in result.output
    # it got past the gate: whatever stops it next, it is not the credential
    assert "rejected" not in result.output


def test_the_config_warnings_reach_the_run_plan(project, monkeypatch):
    """The catalog's opinion of the config is printed before the user consents."""
    from orq_arena.providers.models_list import ModelEntry

    async def _catalog(_cfg, _model_ids):
        return {
            "p/cand-a": ModelEntry(id="p/cand-a", provider="p", endpoints=("chat", "responses")),
            "p/judge-1": ModelEntry(id="p/judge-1", provider="p", endpoints=("chat", "responses")),
            "p/judge-2": ModelEntry(id="p/judge-2", provider="p", endpoints=("chat",)),
        }

    async def _prices(_cfg, **_kw):
        return {}

    async def _verify(_gw, **_kw):
        return True, ""

    monkeypatch.setattr("orq_arena.providers.models_list.fetch_catalog_covering", _catalog)
    monkeypatch.setattr("orq_arena.providers.models_list.fetch_price_map", _prices)
    monkeypatch.setattr("orq_arena.providers.credentials.verify_credential", _verify)

    result = CliRunner().invoke(
        cli, ["run", "-y", "--config", "arena.yaml", "--prompts", "prompts.jsonl"]
    )

    # p/cand-b is absent from the catalog, p/judge-2 has no responses endpoint
    assert "p/cand-b" in result.output
    assert "p/judge-2" in result.output
    assert "responses endpoint" in result.output


def test_rejudge_checks_the_credential_before_it_spends_judge_tokens(project, monkeypatch):
    """The command the incident happened in.

    A stale key answered 401 to all 48 judge calls of a real rejudge. The
    dead-jury guard reports that afterwards; the probe stops it beforehand, and
    it only guarded `run`.
    """
    log = project / "battles.jsonl"
    log.write_text(
        '{"prompt_hash":"h","prompt_text":"p","model_a":"a","model_b":"b",'
        '"response_a":"ra","response_b":"rb","majority_verdict":"A"}\n',
        encoding="utf-8",
    )

    judged = []

    async def _verify(_gw, **_kw):
        return False, "the router rejected ORQ_API_KEY (401)."

    async def _rejudge_run(**kw):
        judged.append(kw)
        raise AssertionError("rejudge spent judge tokens on a rejected credential")

    monkeypatch.setattr("orq_arena.providers.credentials.verify_credential", _verify)
    monkeypatch.setattr("orq_arena.rejudge.rejudge_run", _rejudge_run)

    result = CliRunner().invoke(
        cli, ["rejudge", str(log), "--judge", "p/judge-1", "--config", "arena.yaml"]
    )

    assert result.exit_code != 0
    assert "401" in result.output
    assert judged == []


def _run_that_rated(project, monkeypatch, rated_rounds):
    """Drive `run` to completion with a tournament that rated this many rounds."""
    import json

    from orq_arena.tournament.driver import manifest_path_for

    _no_catalog(monkeypatch)

    async def _verify(_gw, **_kw):
        return True, ""

    async def _tournament(*, battle_log_path, **_kw):
        manifest_path_for(battle_log_path).write_text(
            json.dumps({"rated_rounds": rated_rounds}), encoding="utf-8"
        )

    monkeypatch.setattr("orq_arena.providers.credentials.verify_credential", _verify)
    monkeypatch.setattr("orq_arena.headless.run_headless", _tournament)
    monkeypatch.setattr("orq_arena.cli._open_report", lambda *a, **k: None)
    return CliRunner().invoke(
        cli, ["run", "-y", "--config", "arena.yaml", "--prompts", "prompts.jsonl"]
    )


def test_a_live_run_that_rated_nothing_does_not_exit_zero(project, monkeypatch):
    """Every judge erroring is a failed run, and CI reads the exit code.

    `rejudge` exits nonzero on a dead jury. `run` did not, so the same collapse
    on a live tournament printed "0 rated" and reported success.
    """
    result = _run_that_rated(project, monkeypatch, 0)

    assert result.exit_code != 0
    assert "no round was rated" in result.output


def test_a_live_run_that_rated_something_exits_zero(project, monkeypatch):
    result = _run_that_rated(project, monkeypatch, 12)

    assert result.exit_code == 0, result.output
