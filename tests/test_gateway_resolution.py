"""Gateway credential/host resolution: delegate at defaults, explicit for BYO."""

import pytest

from orq_arena.config import GatewayConfig
from orq_arena.providers.orq_gateway import OrqGateway


def _clear(monkeypatch):
    for k in ("ORQ_API_KEY", "ORQ_BASE_URL", "OPENAI_API_KEY", "OPENAI_BASE_URL"):
        monkeypatch.delenv(k, raising=False)


def test_defaults_resolve_to_api_orq_host(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("ORQ_API_KEY", "sk-test")
    gw = OrqGateway(GatewayConfig())
    assert str(gw.client.base_url).rstrip("/") == "https://api.orq.ai/v3/router"
    # custom stream timeout survives the resolver-built client
    assert gw.client.timeout.read == 1200.0


def test_defaults_honor_orq_base_url(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("ORQ_API_KEY", "sk-test")
    monkeypatch.setenv("ORQ_BASE_URL", "https://staging.orq.ai")
    gw = OrqGateway(GatewayConfig())
    assert str(gw.client.base_url).rstrip("/") == "https://staging.orq.ai/v3/router"


def test_defaults_reject_openai_key_only(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")  # must not capture the run
    with pytest.raises(RuntimeError, match="ORQ_API_KEY"):
        OrqGateway(GatewayConfig())


def test_byo_endpoint_uses_config_verbatim(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("VLLM_KEY", "sk-local")
    monkeypatch.setenv("ORQ_BASE_URL", "https://staging.orq.ai")  # must be ignored
    cfg = GatewayConfig(base_url="http://localhost:8000/v1", api_key_env="VLLM_KEY")
    gw = OrqGateway(cfg)
    assert str(gw.client.base_url).rstrip("/") == "http://localhost:8000/v1"


def test_byo_endpoint_missing_key_names_the_var(monkeypatch):
    _clear(monkeypatch)
    cfg = GatewayConfig(base_url="http://localhost:8000/v1", api_key_env="VLLM_KEY")
    with pytest.raises(RuntimeError, match="VLLM_KEY"):
        OrqGateway(cfg)
