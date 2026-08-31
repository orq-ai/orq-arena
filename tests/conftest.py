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
