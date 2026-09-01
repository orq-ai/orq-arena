"""The suite makes no real outbound HTTP call.

This became worth enforcing when the model catalog moved to a public endpoint.
Before, every catalog and price fetch was gated on ``ORQ_API_KEY``, so a test
that forgot to stub one simply got an empty result on a keyless machine. Now
those fetches need no credential, so the same omission would quietly reach
``api.orq.ai``: a green suite that depends on the network, a developer's
workspace entitlements, and someone else's rate limit.

Tests drive these paths through ``httpx.MockTransport`` (see
``test_model_catalog.py``), which never reaches the real transport, so this
fixture is invisible to them and fires only on an unstubbed call.
"""

from __future__ import annotations

import httpx
import pytest


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    """Fail loudly, and name the URL, rather than silently going online."""

    def _refuse(request: httpx.Request) -> None:
        raise AssertionError(
            f"test made a real network call: {request.method} {request.url}\n"
            "Stub it with httpx.MockTransport, or monkeypatch the fetch function."
        )

    async def _async_boom(self, request, *a, **kw):
        _refuse(request)

    def _sync_boom(self, request, *a, **kw):
        _refuse(request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _async_boom)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _sync_boom)


@pytest.fixture(autouse=True)
def no_orq_cli(monkeypatch):
    """The suite does not consult the developer's own orq login either.

    Blocking httpx was not enough. `_write_manifest` calls `active_workspace()`,
    which shells out to `orq auth whoami --json`, so on a machine with the CLI
    installed the manifest tests embedded whoever happened to be logged in and
    made a real network call through a subprocess the httpx guard cannot see. On
    CI, with no CLI, the same tests took the other branch. A test whose result
    depends on the machine's login state is not testing the code.

    The CLI is absent by default. A test that wants its advice says so, the way
    `test_credentials.py` does, and gets it because monkeypatch applies in order.
    """
    from orq_arena.providers import credentials

    monkeypatch.setattr(credentials.shutil, "which", lambda _name: None)
    # `_whoami` is process-cached, which is right for a run and wrong for a
    # suite: one test's stubbed CLI would answer for every later test.
    credentials._whoami.cache_clear()
    yield
    credentials._whoami.cache_clear()
