"""Completions, catalog and pricing must resolve to one host.

The regression: at default config the client came from evaluatorq's resolver,
which honours ORQ_BASE_URL, so a run could go to staging. The catalog and price
host was derived from `cfg.gateway.base_url` instead and stayed on production,
so a staging run was priced against a different environment and the manifest
recorded a host the run never used.
"""

from __future__ import annotations

from orq_arena.config import OrqAIGatewayConfig
from orq_arena.providers.models_list import catalog_host


def test_staging_traffic_is_priced_against_staging(monkeypatch):
    monkeypatch.setenv("ORQ_BASE_URL", "https://staging.orq.ai")
    assert catalog_host(OrqAIGatewayConfig()) == "https://staging.orq.ai"


def test_the_default_host_is_used_when_nothing_overrides_it(monkeypatch):
    monkeypatch.delenv("ORQ_BASE_URL", raising=False)
    assert catalog_host(OrqAIGatewayConfig()) == "https://my.orq.ai"


def test_the_old_router_spelling_resolves_like_the_default(monkeypatch):
    """One host for the whole run, whichever name the config uses for the router.

    The catalog, the credential probe and the completions each ask "is this the
    orq router?" separately. If they disagreed about `api.orq.ai`, a config
    written before the default changed would send completions to one place and
    price or probe against another.
    """
    from orq_arena.providers.models_list import router_base_url

    old = OrqAIGatewayConfig(base_url="https://api.orq.ai/v3/router")
    monkeypatch.delenv("ORQ_BASE_URL", raising=False)
    assert catalog_host(old) == "https://my.orq.ai"
    assert router_base_url(old) == "https://my.orq.ai/v3/router"
    monkeypatch.setenv("ORQ_BASE_URL", "https://staging.orq.ai")
    assert catalog_host(old) == "https://staging.orq.ai"
    assert router_base_url(old) == "https://staging.orq.ai/v3/router"


def test_the_committed_quickstart_config_is_still_the_orq_router():
    """That recording keeps the config it ran with, old spelling included."""
    from pathlib import Path

    from orq_arena.config import is_orq_router, load_config

    repo = Path(__file__).resolve().parents[1]
    cfg = load_config(str(repo / "examples" / "quickstart" / "config.yaml"))
    assert cfg.gateway.base_url == "https://api.orq.ai/v3/router"
    assert is_orq_router(cfg.gateway.base_url)


def test_an_explicit_yaml_base_url_still_wins_over_the_environment(monkeypatch):
    """Naming the endpoint in the YAML is a bring-your-own opt-out, and the
    gateway already treats it that way for completions."""
    monkeypatch.setenv("ORQ_BASE_URL", "https://staging.orq.ai")
    byo = OrqAIGatewayConfig(base_url="https://vllm.internal/v1")
    assert catalog_host(byo) == "https://vllm.internal"


def test_the_manifest_records_the_host_the_run_actually_used(monkeypatch, tmp_path):
    from orq_arena.config import ArenaConfig
    from orq_arena.data.prompts import PromptItem
    from orq_arena.tournament.driver import _write_manifest, manifest_path_for, read_manifest

    monkeypatch.setenv("ORQ_BASE_URL", "https://staging.orq.ai")
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
    manifest = read_manifest(log)
    assert manifest["effective_host"] == "https://staging.orq.ai"
    assert manifest["prompts_path"] == "prompts/starter.jsonl"
