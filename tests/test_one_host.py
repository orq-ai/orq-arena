"""Completions, catalog and pricing must resolve to one host.

The regression: at default config the client came from evaluatorq's resolver,
which honours ORQ_BASE_URL, so a run could go to staging. The catalog and price
host was derived from `cfg.gateway.base_url` instead and stayed on production,
so a staging run was priced against a different environment and the manifest
recorded a host the run never used.
"""

from __future__ import annotations

from orq_arena.config import ORQ_API_KEY_ENV, OrqAIGatewayConfig
from orq_arena.providers.models_list import catalog_host


def test_staging_traffic_is_priced_against_staging(monkeypatch):
    monkeypatch.setenv(ORQ_API_KEY_ENV, "k")
    monkeypatch.setenv("ORQ_BASE_URL", "https://staging.orq.ai")
    assert catalog_host(OrqAIGatewayConfig()) == "https://staging.orq.ai"


def test_the_default_host_is_used_when_nothing_overrides_it(monkeypatch):
    monkeypatch.setenv(ORQ_API_KEY_ENV, "k")
    monkeypatch.delenv("ORQ_BASE_URL", raising=False)
    assert catalog_host(OrqAIGatewayConfig()) == "https://api.orq.ai"


def test_an_explicit_yaml_base_url_still_wins_over_the_environment(monkeypatch):
    """Naming the endpoint in the YAML is a bring-your-own opt-out, and the
    gateway already treats it that way for completions."""
    monkeypatch.setenv(ORQ_API_KEY_ENV, "k")
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
