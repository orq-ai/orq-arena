"""Gateway credential/host resolution: delegate at defaults, explicit for BYO."""

import pytest

from orq_arena.config import OrqAIGatewayConfig
from orq_arena.providers.orq_gateway import OrqGateway


def _clear(monkeypatch):
    for k in ("ORQ_API_KEY", "ORQ_BASE_URL", "OPENAI_API_KEY", "OPENAI_BASE_URL"):
        monkeypatch.delenv(k, raising=False)


def test_defaults_resolve_to_the_my_orq_host(monkeypatch):
    """The host evaluatorq and the orq CLI default to, so all three agree."""
    _clear(monkeypatch)
    monkeypatch.setenv("ORQ_API_KEY", "sk-test")
    gw = OrqGateway(OrqAIGatewayConfig())
    assert str(gw.client.base_url).rstrip("/") == "https://my.orq.ai/v3/router"
    # custom stream timeout survives the resolver-built client
    assert gw.client.timeout.read == 1200.0


def test_defaults_honor_orq_base_url(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("ORQ_API_KEY", "sk-test")
    monkeypatch.setenv("ORQ_BASE_URL", "https://staging.orq.ai")
    gw = OrqGateway(OrqAIGatewayConfig())
    assert str(gw.client.base_url).rstrip("/") == "https://staging.orq.ai/v3/router"


def test_defaults_reject_openai_key_only(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")  # must not capture the run
    with pytest.raises(RuntimeError, match="ORQ_API_KEY"):
        OrqGateway(OrqAIGatewayConfig())


def test_byo_endpoint_uses_config_verbatim(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("ORQ_API_KEY", "sk-local")
    monkeypatch.setenv("ORQ_BASE_URL", "https://staging.orq.ai")  # must be ignored
    cfg = OrqAIGatewayConfig(base_url="http://localhost:8000/v1")
    gw = OrqGateway(cfg)
    assert str(gw.client.base_url).rstrip("/") == "http://localhost:8000/v1"


def test_byo_endpoint_missing_key_names_the_var(monkeypatch):
    _clear(monkeypatch)
    cfg = OrqAIGatewayConfig(base_url="http://localhost:8000/v1")
    with pytest.raises(RuntimeError, match="ORQ_API_KEY"):
        OrqGateway(cfg)


OLD_SPELLING = "https://api.orq.ai/v3/router"


def test_a_config_that_spells_the_router_the_old_way_is_not_a_byo_endpoint(monkeypatch):
    """`api.orq.ai` was the default, so every config written then names it.

    When the default moved to `my.orq.ai`, a plain equality check against the new
    default would have reclassified all of those as bring-your-own endpoints.
    They would still have run, against the same service, but ORQ_BASE_URL would
    have stopped applying to them without a word. Both names are the orq router.
    """
    _clear(monkeypatch)
    monkeypatch.setenv("ORQ_API_KEY", "sk-test")
    monkeypatch.setenv("ORQ_BASE_URL", "https://staging.orq.ai")
    gw = OrqGateway(OrqAIGatewayConfig(base_url=OLD_SPELLING))
    assert str(gw.client.base_url).rstrip("/") == "https://staging.orq.ai/v3/router"


def test_the_old_spelling_still_rejects_an_openai_key_only(monkeypatch):
    """Being the orq router keeps the guard that comes with it."""
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    with pytest.raises(RuntimeError, match="ORQ_API_KEY"):
        OrqGateway(OrqAIGatewayConfig(base_url=OLD_SPELLING))
