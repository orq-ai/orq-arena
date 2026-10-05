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
        _entry("chatonly/no-responses", endpoints=["chat"]),
    ],
}


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


def _by_id_transport(entries: dict[str, dict], calls: list[str] | None = None):
    """The catalog list, plus the by-id route that answers for unlisted models."""
    prefix = "/v2/model-catalog/"

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if calls is not None:
            calls.append(path)
        if path == "/v2/model-catalog":
            return httpx.Response(200, json=CATALOG)
        if path.startswith(prefix):
            row = entries.get(path[len(prefix) :])
            if row is None:
                return httpx.Response(404, json={"code": 5, "message": "entry not found"})
            return httpx.Response(200, json={"model": row})
        return httpx.Response(404, json={"error": "unexpected path"})

    return httpx.MockTransport(handler)


RETIRED = _entry("legacy/retired-model", deprecated=True, deprecation="1792454400")


async def test_a_deprecated_model_is_found_by_asking_for_it_by_id(patched_client, monkeypatch):
    """The list never includes a deprecated model, so absence cannot mean it.

    This used to assert that the list carried a row with `deprecated: true`. The
    real endpoint never sends one: every row it lists is live. A deprecated model
    and a misspelt id are both just missing, and the deprecated warning could
    not fire against the real API at all. Asking by id is what tells them apart.
    """
    monkeypatch.delenv("ORQ_API_KEY", raising=False)
    patched_client(_by_id_transport({"legacy/retired-model": RETIRED}))

    catalog, unchecked = await ml.fetch_catalog_covering(
        OrqAIGatewayConfig(), ["anthropic/claude-haiku-4-5", "legacy/retired-model", "p/typo"]
    )

    assert catalog["legacy/retired-model"].deprecated is True
    assert catalog["legacy/retired-model"].deprecation == 1792454400
    assert catalog["anthropic/claude-haiku-4-5"].deprecated is False
    assert "p/typo" not in catalog  # 404: the catalog has no such entry
    # a 404 is an answer, so nothing is left unchecked
    assert unchecked == frozenset()


async def test_a_config_the_list_fully_covers_costs_no_extra_request(patched_client, monkeypatch):
    monkeypatch.delenv("ORQ_API_KEY", raising=False)
    calls: list[str] = []
    patched_client(_by_id_transport({}, calls))

    await ml.fetch_catalog_covering(
        OrqAIGatewayConfig(), ["anthropic/claude-haiku-4-5", "openai/gpt-5.4-nano"]
    )

    assert calls == ["/v2/model-catalog"]


@pytest.mark.parametrize("failure", [503, 429, "timeout", "not-json"])
async def test_a_lookup_that_gets_no_answer_is_unchecked_not_missing(
    patched_client, monkeypatch, failure
):
    """A 503 is not a 404.

    Every failure of the by-id route used to come back as "no entry", and the
    warning then told the user to check the id of a model that was spelt
    correctly, and filed a deprecated model under unknown. The catalog returned
    503 three times on the day this was written. No answer is its own outcome.
    """
    monkeypatch.delenv("ORQ_API_KEY", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/model-catalog":
            return httpx.Response(200, json=CATALOG)
        if failure == "timeout":
            raise httpx.ReadTimeout("too slow")
        if failure == "not-json":
            return httpx.Response(200, text="<html>gateway</html>")
        return httpx.Response(failure, json={})

    patched_client(httpx.MockTransport(handler))

    catalog, unchecked = await ml.fetch_catalog_covering(
        OrqAIGatewayConfig(), ["legacy/retired-model", "anthropic/claude-haiku-4-5"]
    )

    assert "legacy/retired-model" not in catalog
    assert unchecked == {"legacy/retired-model"}
    # advisory all the way down: the list itself still stands
    assert "anthropic/claude-haiku-4-5" in catalog


async def test_an_unreadable_catalog_is_not_patched_up_one_model_at_a_time(
    patched_client, monkeypatch
):
    """No list means no check, and that is reported as one fact. Filling an empty
    catalog from by-id lookups would hide the outage behind a partial answer."""
    monkeypatch.delenv("ORQ_API_KEY", raising=False)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(503, json={})

    patched_client(httpx.MockTransport(handler))

    assert await ml.fetch_catalog_covering(OrqAIGatewayConfig(), ["p/any"]) == ({}, frozenset())
    assert calls == ["/v2/model-catalog"]


async def test_the_responses_endpoint_is_visible_per_model(patched_client, monkeypatch):
    """evaluatorq prefers the router's Responses endpoint for judges,
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


def _failing_transport():
    def handler(_request):
        raise httpx.ConnectError("no route to host")

    return httpx.MockTransport(handler)


def _prime_cache(monkeypatch, *, age_s: float) -> None:
    """A well-formed cache of the given age, written the way the code writes it."""
    monkeypatch.setattr(ml.time, "time", lambda: 1_000_000.0)
    entry = ml.ModelEntry(
        id="cached/model", provider="cached", endpoints=("chat",), price_in=1.0, price_out=2.0
    )
    ml._write_cache({"cached/model": entry})
    raw = json.loads(ml.CACHE_FILE.read_text(encoding="utf-8"))
    raw["fetched_at"] = 1_000_000.0 - age_s
    ml.CACHE_FILE.write_text(json.dumps(raw), encoding="utf-8")


async def test_a_fresh_cache_is_reported_as_cache_with_its_real_age(patched_client, monkeypatch):
    """`age=` is the age of the rows, not the age of the call.

    `fetched_at` used to be stamped `now` on every path, so a 20-hour-old cache
    printed `age=0s` and the summary line could not answer the one question it
    exists for.
    """
    monkeypatch.delenv("ORQ_API_KEY", raising=False)
    _prime_cache(monkeypatch, age_s=3600)
    patched_client(_transport())

    ml_result = await ml.fetch_chat_models(OrqAIGatewayConfig())

    assert ml_result.source == "cache"
    assert 1_000_000.0 - ml_result.fetched_at == 3600


async def test_a_failed_refresh_is_reported_as_stale_not_as_live(patched_client, monkeypatch):
    """The regression: `refresh-catalog` offline printed `source=live, age=0s`.

    The command exists to answer "is my catalog current?", and it answered by
    labelling a weeks-old cache a fresh live fetch.
    """
    monkeypatch.delenv("ORQ_API_KEY", raising=False)
    _prime_cache(monkeypatch, age_s=21 * 24 * 3600)
    patched_client(_failing_transport())

    ml_result = await ml.fetch_chat_models(OrqAIGatewayConfig(), force_refresh=True)

    assert ml_result.source == "stale"
    assert ml_result.fetched_at == 1_000_000.0 - 21 * 24 * 3600
    # the rows still come through: a stale catalog beats no catalog
    assert [m.id for m in ml_result.models] == ["cached/model"]


async def test_an_expired_cache_is_refetched(patched_client, monkeypatch):
    """The 24h TTL. Without this, deleting the expiry check kept the suite green
    while prices, `deprecated` and `endpoints` froze at the first fetch forever.
    """
    monkeypatch.delenv("ORQ_API_KEY", raising=False)
    _prime_cache(monkeypatch, age_s=25 * 3600)
    patched_client(_transport())

    catalog, source, _fetched_at = await ml._fetch_catalog(OrqAIGatewayConfig())

    assert source == "live"
    assert "cached/model" not in catalog
    assert "anthropic/claude-haiku-4-5" in catalog


async def test_a_fetch_failure_with_no_cache_reports_fallback(patched_client, monkeypatch):
    monkeypatch.delenv("ORQ_API_KEY", raising=False)
    patched_client(_failing_transport())

    ml_result = await ml.fetch_chat_models(OrqAIGatewayConfig(), force_refresh=True)

    assert ml_result.source == "fallback"
    assert ml_result.models == []


async def test_a_live_fetch_is_reported_as_live(patched_client, monkeypatch):
    monkeypatch.delenv("ORQ_API_KEY", raising=False)
    patched_client(_transport())

    ml_result = await ml.fetch_chat_models(OrqAIGatewayConfig())

    assert ml_result.source == "live"


def test_the_price_unit_is_normalised_from_what_the_row_states():
    """The live catalog states `per` as 1000000, 1000 and 1 across families.

    Reading a per-1k or per-token cost as though it were per-1M understates it
    by 1000x or 1e6x, and the run plan prints the result as a measured figure.
    """
    assert ml._price({"input": {"cost": 0.14, "per": 1_000_000}}, "input") == 0.14
    assert ml._price({"input": {"cost": 0.006, "per": 1000}}, "input") == 6.0
    assert ml._price({"input": {"cost": 0.00002, "per": 1}}, "input") == 20.0


def test_a_row_with_no_usable_unit_is_unpriced_rather_than_assumed():
    assert ml._price({"input": {"cost": 0.5}}, "input") is None
    assert ml._price({"input": {"cost": 0.5, "per": 0}}, "input") is None
    assert ml._price({"input": {"cost": 0.5, "per": "1000000"}}, "input") is None


def test_a_price_in_another_currency_is_unpriced_not_read_as_dollars():
    """The cost path is dollars end to end, and the catalog prices in EUR too.

    37 chat-capable models are priced in EUR today. Summing those into
    `projected_usd` at 1:1 reports a spend figure nobody measured, so they are
    named as unpriced instead. A missing `currency` is read as USD, which is
    what every row that carries one states.
    """
    usd = {"cost": 1.0, "currency": "USD", "per": 1_000_000}
    eur = {"cost": 1.0, "currency": "EUR", "per": 1_000_000}
    assert ml._price({"input": usd}, "input") == 1.0
    assert ml._price({"input": eur}, "input") is None
    assert ml._price({"input": {"cost": 1.0, "per": 1_000_000}}, "input") == 1.0


async def test_a_euro_priced_model_never_reaches_the_dollar_price_map(patched_client, monkeypatch):
    """End to end: the projection can only see models it can price in dollars."""
    monkeypatch.delenv("ORQ_API_KEY", raising=False)
    euro_catalog = {
        "object": "list",
        "data": [
            _entry("anthropic/claude-haiku-4-5"),
            _entry(
                "greenpt/glm-5.2",
                pricing={
                    "input": {"cost": 0.05, "currency": "EUR", "per": 1_000_000},
                    "output": {"cost": 0.25, "currency": "EUR", "per": 1_000_000},
                },
            ),
        ],
    }

    def handler(request):
        assert request.url.path == "/v2/model-catalog"
        return httpx.Response(200, json=euro_catalog)

    patched_client(httpx.MockTransport(handler))

    prices = await ml.fetch_price_map(OrqAIGatewayConfig())

    assert "anthropic/claude-haiku-4-5" in prices
    assert "greenpt/glm-5.2" not in prices


def _narrowing_transport(*, router_status: int = 200, enabled: list[str] | None = None):
    """Serves the public catalog, and the workspace's enabled ids separately."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/model-catalog":
            return httpx.Response(200, json=CATALOG)
        if request.url.path == "/v2/router/models":
            if router_status != 200:
                return httpx.Response(router_status, json={"error": "nope"})
            return httpx.Response(200, json={"data": [{"id": i} for i in enabled or []]})
        return httpx.Response(404, json={"error": "unexpected path"})

    return httpx.MockTransport(handler)


async def test_a_key_narrows_the_picker_to_the_workspaces_own_models(patched_client, monkeypatch):
    monkeypatch.setenv("ORQ_API_KEY", "sk-orq-test")
    patched_client(_narrowing_transport(enabled=["anthropic/claude-haiku-4-5"]))

    result = await ml.fetch_chat_models(OrqAIGatewayConfig())

    assert [m.id for m in result.models] == ["anthropic/claude-haiku-4-5"]


async def test_an_unreachable_narrowing_call_keeps_the_full_catalog(patched_client, monkeypatch):
    """ "Could not narrow" is not "nothing is enabled".

    Without this the picker empties whenever /v2/router/models has a bad day,
    and the user is told their workspace has no models at all.
    """
    monkeypatch.setenv("ORQ_API_KEY", "sk-orq-test")
    patched_client(_narrowing_transport(router_status=503))

    result = await ml.fetch_chat_models(OrqAIGatewayConfig())

    assert "anthropic/claude-haiku-4-5" in [m.id for m in result.models]
    assert "openai/gpt-5.4-nano" in [m.id for m in result.models]


async def test_a_disjoint_id_space_keeps_the_full_catalog(patched_client, monkeypatch):
    """An empty intersection is likelier to mean the two id spaces disagree than
    that the workspace enabled nothing, and emptying the picker on that guess
    leaves the user with no way forward."""
    monkeypatch.setenv("ORQ_API_KEY", "sk-orq-test")
    patched_client(_narrowing_transport(enabled=["some-other-namespace/model"]))

    result = await ml.fetch_chat_models(OrqAIGatewayConfig())

    assert "anthropic/claude-haiku-4-5" in [m.id for m in result.models]


async def test_a_success_code_over_an_unusable_body_is_still_a_failed_fetch(
    patched_client, monkeypatch
):
    """A schema change or a 200-wrapped error would empty everything at once.

    `raise_for_status` passes, `data` is missing, and the parsed catalog is
    empty: prices blank, the picker empties, and `config_warnings` returns []
    because an empty catalog means "unreachable, say nothing". A cache on disk
    was ignored, because the fallback only covered transport errors.
    """
    monkeypatch.delenv("ORQ_API_KEY", raising=False)
    _prime_cache(monkeypatch, age_s=3600)

    def handler(_request):
        return httpx.Response(200, json={"error": {"message": "upstream is unwell"}})

    patched_client(httpx.MockTransport(handler))

    catalog, source, _at = await ml._fetch_catalog(OrqAIGatewayConfig(), force_refresh=True)

    assert source == "stale"
    assert "cached/model" in catalog


async def test_an_unusable_body_with_no_cache_reports_fallback(patched_client, monkeypatch):
    monkeypatch.delenv("ORQ_API_KEY", raising=False)

    def handler(_request):
        return httpx.Response(200, json={"unexpected": "shape"})

    patched_client(httpx.MockTransport(handler))

    catalog, source, _at = await ml._fetch_catalog(OrqAIGatewayConfig())

    assert (catalog, source) == ({}, "fallback")
