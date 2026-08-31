"""Model metadata comes from the public catalog, and needs no credential.

The catalog (`GET {host}/v2/model-catalog`) is public and rate-limited, and it
answers three questions the repo used to guess at:

* which models are chat-capable, previously a 20-pattern substring regex over
  ids ("whisper", "dall-e", ...) plus an authenticated `type` lookup;
* what they cost, previously reconciled by hand from two different Model Garden
  cost representations;
* whether they are deprecated, which nothing could ask before.

Because it needs no key, the model picker and the cost projection now work
before the user has a credential at all, where they used to return an empty
list and a blank price.

The workspace-enabled question is separate and still needs a key: the catalog
lists what orq offers, not what this workspace turned on.
"""

from __future__ import annotations

import json

import httpx
import pytest

from orq_arena.config import OrqAIGatewayConfig
from orq_arena.providers import models_list as ml


def _entry(model_id: str, **over) -> dict:
    row = {
        "id": model_id,
        "name": model_id.split("/")[-1],
        "provider": {"id": model_id.split("/")[0]},
        "created": "1777852800",
        "endpoints": ["chat", "responses"],
        "deprecated": False,
        "context_window": "200000",
        "features": ["streaming", "tool_calling"],
        "pricing": {
            "input": {"cost": 1.0, "currency": "USD", "per": 1000000, "unit": "tokens"},
            "output": {"cost": 5.0, "currency": "USD", "per": 1000000, "unit": "tokens"},
        },
    }
    row.update(over)
    return row


CATALOG = {
    "object": "list",
    "data": [
        _entry("anthropic/claude-haiku-4-5"),
        _entry(
            "openai/gpt-5.4-nano",
            pricing={
                "input": {"cost": 0.2, "per": 1000000, "unit": "tokens"},
                "output": {"cost": 1.25, "per": 1000000, "unit": "tokens"},
            },
        ),
        _entry("openai/text-embedding-3-small", endpoints=["embeddings"]),
        _entry("openai/whisper-1", endpoints=["transcriptions"]),
        _entry("legacy/retired-model", deprecated=True),
        _entry("chatonly/no-responses", endpoints=["chat"]),
    ],
}


@pytest.fixture(autouse=True)
def _no_cache(tmp_path, monkeypatch):
    """Each test starts with a cold cache in its own directory."""
    monkeypatch.setattr(ml, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(ml, "CACHE_FILE", tmp_path / "cache" / "models.json")


def _transport(*, expect_no_auth: bool = True, calls: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append((str(request.url), request.headers.get("authorization")))
        if request.url.path == "/v2/model-catalog":
            if expect_no_auth:
                assert "authorization" not in request.headers, (
                    "the catalog is public; sending a key makes it fail closed for "
                    "users who have none"
                )
            return httpx.Response(200, json=CATALOG)
        return httpx.Response(404, json={"error": "unexpected path"})

    return httpx.MockTransport(handler)


@pytest.fixture
def patched_client(monkeypatch):
    """Route every httpx.AsyncClient in models_list through the mock."""

    def install(transport):
        real = httpx.AsyncClient

        def factory(*a, **kw):
            kw["transport"] = transport
            return real(*a, **kw)

        monkeypatch.setattr(ml.httpx, "AsyncClient", factory)

    return install


async def test_the_catalog_is_fetched_without_a_credential(patched_client, monkeypatch):
    monkeypatch.delenv("ORQ_API_KEY", raising=False)
    calls: list = []
    patched_client(_transport(calls=calls))

    catalog = await ml.fetch_catalog(OrqAIGatewayConfig())

    assert "anthropic/claude-haiku-4-5" in catalog
    assert calls and all(auth is None for _url, auth in calls)


async def test_prices_come_straight_from_the_catalog(patched_client, monkeypatch):
    monkeypatch.delenv("ORQ_API_KEY", raising=False)
    patched_client(_transport())

    prices = await ml.fetch_price_map(OrqAIGatewayConfig())

    # per-1M dollars, exactly as the catalog states them, with no key present
    assert prices["openai/gpt-5.4-nano"] == (0.2, 1.25)
    assert prices["anthropic/claude-haiku-4-5"] == (1.0, 5.0)


async def test_chat_capability_is_read_not_guessed(patched_client, monkeypatch):
    """The old regex banned any id containing 'whisper', 'image-', 'tts' and so
    on, which is a substring guess about a capability the catalog states."""
    monkeypatch.delenv("ORQ_API_KEY", raising=False)
    patched_client(_transport())

    listed = await ml.fetch_chat_models(OrqAIGatewayConfig())
    ids = {m.id for m in listed.models}

    assert "anthropic/claude-haiku-4-5" in ids
    assert "openai/text-embedding-3-small" not in ids  # endpoints say embeddings
    assert "openai/whisper-1" not in ids


async def test_deprecated_models_are_carried_not_hidden(patched_client, monkeypatch):
    """Absence and deprecation are different facts, and preflight needs both."""
    monkeypatch.delenv("ORQ_API_KEY", raising=False)
    patched_client(_transport())

    catalog = await ml.fetch_catalog(OrqAIGatewayConfig())

    assert catalog["legacy/retired-model"].deprecated is True
    assert catalog["anthropic/claude-haiku-4-5"].deprecated is False


async def test_the_responses_endpoint_is_visible_per_model(patched_client, monkeypatch):
    """evaluatorq 1.32.4 prefers the router's Responses endpoint for judges,
    because that is the endpoint the router prices."""
    monkeypatch.delenv("ORQ_API_KEY", raising=False)
    patched_client(_transport())

    catalog = await ml.fetch_catalog(OrqAIGatewayConfig())

    assert "responses" in catalog["anthropic/claude-haiku-4-5"].endpoints
    assert "responses" not in catalog["chatonly/no-responses"].endpoints


async def test_a_catalog_failure_leaves_pricing_advisory(patched_client, monkeypatch):
    """Pricing never blocks a run; a dead catalog yields no prices, not a crash
    and not a zero."""
    monkeypatch.delenv("ORQ_API_KEY", raising=False)
    patched_client(httpx.MockTransport(lambda r: httpx.Response(503, json={})))

    assert await ml.fetch_price_map(OrqAIGatewayConfig()) == {}


async def test_the_catalog_is_read_from_the_run_host(patched_client, monkeypatch):
    """One-host discipline: a staging run must not be priced against production
    (tests/test_one_host.py)."""
    monkeypatch.delenv("ORQ_API_KEY", raising=False)
    monkeypatch.setenv("ORQ_BASE_URL", "https://staging.orq.ai")
    calls: list = []
    patched_client(_transport(calls=calls))

    await ml.fetch_catalog(OrqAIGatewayConfig())

    assert any(url.startswith("https://staging.orq.ai/v2/model-catalog") for url, _ in calls)


async def test_a_cached_catalog_is_reused_without_a_second_fetch(patched_client, monkeypatch):
    monkeypatch.delenv("ORQ_API_KEY", raising=False)
    calls: list = []
    patched_client(_transport(calls=calls))

    first = await ml.fetch_catalog(OrqAIGatewayConfig())
    n_after_first = len(calls)
    second = await ml.fetch_catalog(OrqAIGatewayConfig())

    assert len(calls) == n_after_first, "second call should have been served from cache"
    assert set(first) == set(second)


async def test_a_cache_written_by_an_older_version_is_ignored(patched_client, monkeypatch):
    """The cached rows gained fields. A v1 file lacks `endpoints`, and reading
    it as if it had them would silently drop every model from the picker."""
    monkeypatch.delenv("ORQ_API_KEY", raising=False)
    ml.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ml.CACHE_FILE.write_text(
        json.dumps({"fetched_at": 9e9, "data": [{"id": "old/model", "owned_by": "old"}]}),
        encoding="utf-8",
    )
    patched_client(_transport())

    catalog = await ml.fetch_catalog(OrqAIGatewayConfig())

    assert "old/model" not in catalog
    assert "anthropic/claude-haiku-4-5" in catalog
