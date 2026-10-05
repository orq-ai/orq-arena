"""A missing or rejected credential fails before the run spends anything.

Two failures motivated this. A rejudge ran with a stale `ORQ_API_KEY`, every
one of its 48 judge calls returned 401, and the only signal was a leaderboard
that looked fine. And `orq doctor` reported healthy throughout, because it
checks auth and endpoint reachability but never exercises router inference,
which is the one thing the arena does.

Two pieces, deliberately kept apart:

* `credential_hint()` builds the message shown when no key is present. It uses
  the orq CLI only as a source of advice, never as a source of tokens: the CLI
  documents that its login session expires after about an hour, and a
  tournament routinely runs longer, so borrowing that token would swap a loud
  failure for a mid-run one.
* `verify_credential()` makes one cheap call and reports whether the key the
  run will actually use is accepted.

Precedence matches what `orq launch` documents, so the arena does not silently
disagree with the rest of the user's orq tooling: an exported key wins over the
login session.
"""

from __future__ import annotations

import httpx
import pytest

from orq_arena.config import ORQ_API_KEY_ENV, OrqAIGatewayConfig
from orq_arena.providers import credentials as cred


@pytest.fixture(autouse=True)
def _no_key(monkeypatch):
    monkeypatch.delenv(ORQ_API_KEY_ENV, raising=False)


def _cli(monkeypatch, *, present=True, whoami=None, returncode=0):
    """Stand in for the `orq` binary."""
    monkeypatch.setattr(cred.shutil, "which", lambda _n: "/usr/local/bin/orq" if present else None)

    def fake_run(*_a, **_kw):
        class R:
            pass

        r = R()
        r.returncode = returncode
        r.stdout = whoami or ""
        r.stderr = ""
        return r

    monkeypatch.setattr(cred.subprocess, "run", fake_run)


WHOAMI = '{"authenticated": true, "active_workspace_key": "orq-research"}'


def test_the_hint_names_both_commands_when_the_cli_is_absent(monkeypatch):
    _cli(monkeypatch, present=False)
    hint = cred.credential_hint()
    assert ORQ_API_KEY_ENV in hint
    assert "orq auth login" in hint
    assert "orq api-keys create" in hint


def test_a_logged_in_cli_is_told_to_mint_a_key_not_to_lend_its_session(monkeypatch):
    """The session token expires in about an hour; a tournament does not."""
    _cli(monkeypatch, whoami=WHOAMI)
    hint = cred.credential_hint()
    assert "orq-research" in hint  # it knows which workspace you are in
    assert "orq api-keys create" in hint
    assert "expire" in hint


def test_a_cli_that_is_installed_but_logged_out_still_says_log_in(monkeypatch):
    _cli(monkeypatch, whoami="", returncode=1)
    hint = cred.credential_hint()
    assert "orq auth login" in hint


def test_the_active_workspace_is_readable_for_the_manifest(monkeypatch):
    _cli(monkeypatch, whoami=WHOAMI)
    assert cred.active_workspace() == "orq-research"


def _cli_that_accepts(monkeypatch, accepted: list[str]):
    """An `orq` binary that knows one spelling of the JSON flag and no other."""
    monkeypatch.setattr(cred.shutil, "which", lambda _n: "/usr/local/bin/orq")
    seen: list[list[str]] = []

    def fake_run(argv, **_kw):
        seen.append(argv)

        class R:
            pass

        r = R()
        ok = argv[3:] == accepted
        r.returncode = 0 if ok else 1
        r.stdout = WHOAMI if ok else ""
        r.stderr = "" if ok else "Error: unknown flag"
        return r

    monkeypatch.setattr(cred.subprocess, "run", fake_run)
    return seen


def test_the_workspace_is_read_from_a_current_cli(monkeypatch):
    """orq CLI 8.x asks for JSON with `-o json` and rejects `--json`.

    The call used `--json` only, so on every current install the CLI answered
    "unknown flag", `_whoami` took that as "no advice", and the workspace hint
    and the manifest field went quiet without any error.
    """
    seen = _cli_that_accepts(monkeypatch, ["-o", "json"])
    assert cred.active_workspace() == "orq-research"
    assert seen == [["orq", "auth", "whoami", "-o", "json"]]


def test_the_workspace_is_still_read_from_an_older_cli(monkeypatch):
    _cli_that_accepts(monkeypatch, ["--json"])
    assert cred.active_workspace() == "orq-research"


def test_a_flag_that_exits_zero_without_json_still_tries_the_other_spelling(monkeypatch):
    """A parse failure is the same "wrong spelling" case as a nonzero exit.

    A CLI that accepts `-o json` but prints something else exits 0. That used
    to end the search, while a nonzero exit moved on to `--json`.
    """
    monkeypatch.setattr(cred.shutil, "which", lambda _n: "/usr/local/bin/orq")

    def fake_run(argv, **_kw):
        class R:
            pass

        r = R()
        r.returncode = 0
        r.stdout = WHOAMI if argv[3:] == ["--json"] else "active_workspace_key: orq-research"
        r.stderr = ""
        return r

    monkeypatch.setattr(cred.subprocess, "run", fake_run)
    assert cred.active_workspace() == "orq-research"


def test_no_cli_means_no_workspace_claim(monkeypatch):
    """Absent provenance is recorded as absent, never guessed."""
    _cli(monkeypatch, present=False)
    assert cred.active_workspace() is None


def test_unparseable_cli_output_is_not_a_crash(monkeypatch):
    _cli(monkeypatch, whoami="not json at all")
    assert cred.active_workspace() is None
    assert "orq auth login" in cred.credential_hint()


def _transport(handler) -> httpx.MockTransport:
    """A transport, not a client: the probe must resolve its own host.

    Injecting a ready-made client hid which router was asked. The handler now
    sees the URL `verify_credential` actually built.
    """
    return httpx.MockTransport(handler)


@pytest.fixture
def with_key(monkeypatch):
    """A key is present, so the probe gets as far as asking the router."""
    monkeypatch.setenv(ORQ_API_KEY_ENV, "sk-orq-test")


async def test_a_run_with_no_key_at_all_never_reaches_the_router():
    """The probe answers from the environment before it opens a connection."""
    calls: list[str] = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={})

    ok, detail = await cred.verify_credential(OrqAIGatewayConfig(), transport=_transport(handler))

    assert ok is False
    assert calls == []
    assert "orq auth login" in detail or "orq api-keys create" in detail


async def test_a_rejected_key_is_reported_before_the_run(with_key):
    calls: list[str] = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(
            401, json={"error": {"message": "API key is not valid for this workspace."}}
        )

    ok, detail = await cred.verify_credential(OrqAIGatewayConfig(), transport=_transport(handler))

    assert ok is False
    assert "401" in detail
    assert len(calls) == 1, "the probe is one call, not one per model"


async def test_an_accepted_key_passes_quietly(with_key):
    def handler(request):
        return httpx.Response(200, json={"data": [{"id": "openai/gpt-5.4-nano"}]})

    ok, detail = await cred.verify_credential(OrqAIGatewayConfig(), transport=_transport(handler))

    assert ok is True
    assert detail == ""


async def test_a_network_failure_is_not_a_credential_verdict(with_key):
    """Being offline does not mean the key is bad, and refusing to run would be
    the wrong call. Unknown is reported as unknown."""

    def handler(request):
        raise httpx.ConnectError("no route to host")

    ok, detail = await cred.verify_credential(OrqAIGatewayConfig(), transport=_transport(handler))

    assert ok is None
    assert "could not" in detail.lower()


async def test_a_server_error_is_not_a_credential_verdict(with_key):
    def handler(request):
        return httpx.Response(503, json={})

    ok, _detail = await cred.verify_credential(OrqAIGatewayConfig(), transport=_transport(handler))

    assert ok is None, "a 503 says the router is unwell, not that the key is wrong"


async def test_the_probe_asks_the_router_the_run_will_actually_call(with_key, monkeypatch):
    """The probe follows ORQ_BASE_URL, like completions and the catalog do.

    It used to build its client from the static `gateway.base_url` default, so a
    staging run checked its key against production: a staging-only key was
    rejected and the run aborted, and a production key passed the probe and then
    401'd on every judge call. That is the failure this module exists to catch,
    committed by the check itself.
    """
    monkeypatch.setenv("ORQ_BASE_URL", "https://staging.orq.ai")
    asked: list[str] = []

    def handler(request):
        asked.append(str(request.url))
        return httpx.Response(200, json={"data": []})

    ok, _detail = await cred.verify_credential(OrqAIGatewayConfig(), transport=_transport(handler))

    assert ok is True
    assert asked == ["https://staging.orq.ai/v3/router/models"]


async def test_a_byo_endpoint_is_probed_as_written(with_key, monkeypatch):
    """A YAML `base_url` is the opt-out, and it wins here as it does elsewhere."""
    monkeypatch.setenv("ORQ_BASE_URL", "https://staging.orq.ai")
    asked: list[str] = []

    def handler(request):
        asked.append(str(request.url))
        return httpx.Response(200, json={"data": []})

    cfg = OrqAIGatewayConfig(base_url="https://proxy.internal/llm")
    ok, _detail = await cred.verify_credential(cfg, transport=_transport(handler))

    assert ok is True
    assert asked == ["https://proxy.internal/llm/models"]


async def test_an_unexpected_status_is_not_a_pass(with_key):
    """404, 429, anything unexpected: the question was not answered.

    These used to fall through to "the router accepts the key", which is the
    same healthy-but-untested verdict `orq doctor` gave while every judge call
    401'd. A bring-your-own endpoint with no listing route answers 404, and a
    rate-limited workspace answers 429.
    """
    for status in (400, 404, 429):

        def handler(_request, _status=status):
            return httpx.Response(_status, json={})

        ok, detail = await cred.verify_credential(
            OrqAIGatewayConfig(), transport=_transport(handler)
        )

        assert ok is None, f"{status} is not a verdict on the credential"
        assert str(status) in detail


def _manifest(tmp_path):
    from orq_arena.config import ArenaConfig
    from orq_arena.data.prompts import PromptItem
    from orq_arena.tournament.driver import _write_manifest, manifest_path_for, read_manifest

    cfg = ArenaConfig.model_validate(
        {"candidates": [{"model_id": "p/a"}, {"model_id": "p/b"}], "judges": ["p/j1", "p/j2"]}
    )
    log = tmp_path / "battles.jsonl"
    _write_manifest(
        manifest_path_for(log),
        cfg=cfg,
        prompts=[PromptItem(text="p")],
        seed=42,
        tournament_id="bench-1",
        started_at=0.0,
        prompts_path="prompts/starter.jsonl",
    )
    return read_manifest(log)


def test_the_manifest_records_the_workspace_when_the_cli_can_say(tmp_path, monkeypatch):
    """A leaderboard is a claim about models as one workspace can reach them."""
    _cli(monkeypatch, whoami=WHOAMI)
    assert _manifest(tmp_path)["orq_cli_workspace"] == "orq-research"


def test_the_manifest_records_an_unknown_workspace_as_unknown(tmp_path, monkeypatch):
    """Absent provenance is recorded as absent, never guessed, and never
    inherited from whichever machine happened to write the run."""
    _cli(monkeypatch, present=False)
    assert _manifest(tmp_path)["orq_cli_workspace"] is None
