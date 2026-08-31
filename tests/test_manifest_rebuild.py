"""A rebuilt report must describe the run that happened, not today's YAML.

The regression: `orq-arena report <old log>` re-derived model names, the judge
panel and the thinking flags from whatever `orq_arena.yaml` says now, so a
report regenerated after the YAML moved on relabelled models and printed
judge-agreement stats for a panel that never judged that run.
"""

from __future__ import annotations

import json
import pathlib

import pytest
from click.testing import Result

from orq_arena.config import ORQ_API_KEY_ENV, ArenaConfig
from orq_arena.data.schemas import BattleRecord
from orq_arena.tournament.driver import (
    IDENTITY_FIELDS,
    config_from_manifest,
    config_sha256,
    read_manifest,
    rebuild_from_log,
)


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    """No network. `report` prices its cost section from the live catalog, which
    is public now, so dropping the key no longer makes that a no-op: the stub
    below is what keeps it offline. The key still goes, because the
    workspace-enabled narrowing does read it."""
    monkeypatch.delenv(ORQ_API_KEY_ENV, raising=False)

    async def _no_prices(_gw):
        return {}

    monkeypatch.setattr("orq_arena.providers.models_list.fetch_price_map", _no_prices)


RAN_WITH = ArenaConfig.model_validate(
    {
        "candidates": [
            {"model_id": "prov/model-a"},
            {"model_id": "prov/model-b", "reasoning": {"thinking": {"type": "disabled"}}},
        ],
        "judges": ["prov/judge-1", "prov/judge-2"],
        "min_successful_judges": 2,
    }
)

# The same file after a user edits it between runs: a display name added, the
# reasoning-off flag dropped, the panel swapped wholesale.
DRIFTED = ArenaConfig.model_validate(
    {
        "candidates": [
            {"model_id": "prov/model-a", "name": "our-default"},
            {"model_id": "prov/model-b"},
        ],
        "judges": ["other/judge-9"],
    }
)


def _records() -> list[BattleRecord]:
    out = []
    for i, verdict in enumerate(("A", "B", "A", "tie")):
        out.append(
            BattleRecord(
                prompt_hash=f"h{i}",
                prompt_text="p?",
                model_a="model-a",
                model_b="model-b",
                response_a="ra",
                response_b="rb",
                majority_verdict=verdict,
                winner="model-a" if verdict == "A" else "model-b" if verdict == "B" else verdict,
                judge_votes=[
                    {"model": j, "vote": verdict, "flipped": False, "replacement": False}
                    for j in ("prov/judge-1", "prov/judge-2")
                ],
            )
        )
    return out


def _manifest(cfg: ArenaConfig, *, with_config: bool) -> dict:
    manifest = {
        "tournament_id": "bench-1",
        "config_sha256": config_sha256(cfg),
        "candidates": {
            c.name: {"model": c.model_id, "reasoning": c.reasoning or "vendor-default"}
            for c in cfg.candidates
        },
        "judges": list(cfg.judges),
        "replacement_judges": list(cfg.replacement_judges),
        "min_successful_judges": cfg.min_successful_judges,
    }
    if with_config:
        manifest["config"] = cfg.model_dump(mode="json")
    return manifest


def test_full_config_blob_wins_over_the_live_yaml():
    cfg, source = config_from_manifest(_manifest(RAN_WITH, with_config=True), DRIFTED)
    assert source == "manifest"
    assert [c.name for c in cfg.candidates] == ["model-a", "model-b"]
    assert list(cfg.judges) == ["prov/judge-1", "prov/judge-2"]
    assert cfg.candidates[1].thinking_disabled is True


def test_pre_config_manifests_still_rebuild_their_own_identity():
    """Manifests written before the config blob existed carry enough on their own."""
    cfg, source = config_from_manifest(_manifest(RAN_WITH, with_config=False), DRIFTED)
    assert source == "manifest-partial"
    assert [c.name for c in cfg.candidates] == ["model-a", "model-b"]
    assert list(cfg.judges) == ["prov/judge-1", "prov/judge-2"]
    assert cfg.candidates[1].thinking_disabled is True
    # Everything the manifest never recorded still comes from the live config.
    assert cfg.gateway.base_url == DRIFTED.gateway.base_url


def test_missing_or_unusable_manifest_falls_back_and_says_so():
    assert config_from_manifest({}, DRIFTED) == (DRIFTED, "config")
    assert config_from_manifest({"config": {"nonsense": True}}, DRIFTED)[1] == "config"


def test_drifted_yaml_no_longer_relabels_models_or_voids_the_kappa():
    """The end-to-end regression, both halves of it."""
    records = _records()
    manifest = _manifest(RAN_WITH, with_config=True)

    _, truth = rebuild_from_log(RAN_WITH, records)
    drifted_elo, drifted_report = rebuild_from_log(DRIFTED, records)
    # Guard: the drift really does damage when the manifest is ignored.
    assert "our-default" in drifted_elo  # a model relabelled after the fact
    assert drifted_report["fleiss"]["kappa"] is None  # kappa for a panel that never judged
    assert truth["thinking_off"] == {"model-b": True}
    assert drifted_report["thinking_off"] == {}  # the reasoning-off disclosure, dropped

    rebuilt_cfg, source = config_from_manifest(manifest, DRIFTED)
    elo, report = rebuild_from_log(rebuilt_cfg, records)
    assert source == "manifest"
    assert "our-default" not in elo
    assert report["fleiss"]["kappa"] == truth["fleiss"]["kappa"]
    assert report["thinking_off"] == truth["thinking_off"]


def test_read_manifest_is_quiet_about_a_missing_or_broken_file(tmp_path):
    log = tmp_path / "battles.jsonl"
    log.write_text("", encoding="utf-8")
    assert read_manifest(log) == {}
    log.with_suffix(".run.json").write_text("{not json", encoding="utf-8")
    assert read_manifest(log) == {}
    log.with_suffix(".run.json").write_text(json.dumps({"seed": 42}), encoding="utf-8")
    assert read_manifest(log) == {"seed": 42}


def _write_run(tmp_path, *, with_manifest: bool = True, with_yaml: bool = True):
    """A recorded run on disk, plus the drifted YAML sitting next to it."""
    log = tmp_path / "battles.jsonl"
    log.write_text("\n".join(r.model_dump_json() for r in _records()) + "\n", encoding="utf-8")
    if with_manifest:
        log.with_suffix(".run.json").write_text(
            json.dumps(_manifest(RAN_WITH, with_config=True)), encoding="utf-8"
        )
    drifted = tmp_path / "orq_arena.yaml"
    if with_yaml:  # YAML is a JSON superset, so this is a valid config file
        drifted.write_text(json.dumps(DRIFTED.model_dump(mode="json")), encoding="utf-8")
    return log, drifted


def _report(args: list[str], cwd, monkeypatch) -> tuple[Result, str]:
    """Run `orq-arena report` from `cwd` and return (result, rendered page)."""
    from click.testing import CliRunner

    from orq_arena.cli import cli

    monkeypatch.chdir(cwd)
    res = CliRunner().invoke(cli, ["report", *args])
    page = (cwd / "battles.report.html").read_text(encoding="utf-8") if res.exit_code == 0 else ""
    return res, page


def test_report_defaults_to_the_manifest_even_with_a_drifted_yaml_present(tmp_path, monkeypatch):
    log, _ = _write_run(tmp_path)
    res, page = _report([str(log)], tmp_path, monkeypatch)
    assert res.exit_code == 0, res.output
    assert "our-default" not in page  # the run's own names survive the edit
    assert "may have drifted" not in page  # nothing to disclose, identity is the run's


def test_report_needs_no_config_file_at_all_when_the_log_is_manifested(tmp_path, monkeypatch):
    log, _ = _write_run(tmp_path, with_yaml=False)
    res, page = _report([str(log)], tmp_path, monkeypatch)
    assert res.exit_code == 0, res.output
    assert "model-a" in page


def test_explicit_config_wins_and_the_page_says_it_did(tmp_path, monkeypatch):
    log, drifted = _write_run(tmp_path)
    res, page = _report([str(log), "--config", str(drifted)], tmp_path, monkeypatch)
    assert res.exit_code == 0, res.output
    assert "our-default" in page  # the operator asked for their file
    assert "may have drifted since the run" in page
    assert "not the config this run used" in res.output


def test_a_log_without_a_manifest_discloses_the_fallback(tmp_path, monkeypatch):
    log, _ = _write_run(tmp_path, with_manifest=False)
    res, page = _report([str(log)], tmp_path, monkeypatch)
    assert res.exit_code == 0, res.output
    assert "our-default" in page  # nothing on disk to correct it
    assert "may have drifted since the run" in page
    # The no-manifest-and-no-config error lives in tests/test_cli_errors.py.


def test_the_writer_records_what_the_reader_needs(tmp_path):
    """The write side, which nothing else covers: delete the recorded config
    from `_write_manifest` and every other test here still passes, because they
    all hand-build their manifests."""
    from orq_arena.data.prompts import PromptItem
    from orq_arena.tournament.driver import _write_manifest, manifest_path_for

    log = tmp_path / "battles.jsonl"
    _write_manifest(
        manifest_path_for(log),
        cfg=RAN_WITH,
        prompts=[PromptItem(text="p?")],
        seed=42,
        tournament_id="bench-1",
        started_at=0.0,
    )
    manifest = read_manifest(log)
    assert manifest["config_sha256"] == config_sha256(RAN_WITH)

    cfg, source = config_from_manifest(manifest, DRIFTED)
    assert source == "manifest"
    assert cfg.model_dump(include=set(IDENTITY_FIELDS)) == RAN_WITH.model_dump(
        include=set(IDENTITY_FIELDS)
    )


def test_the_committed_example_run_rebuilds_from_its_own_manifest():
    """A real pre-change manifest, not a synthetic one: the partial path has to
    survive the shape actually on disk, which a mirror of the writer can't prove."""
    log = pathlib.Path("examples/quickstart/battles.jsonl")
    manifest = read_manifest(log)
    assert "config" not in manifest, "committed example is no longer a pre-change manifest"

    cfg, source = config_from_manifest(manifest, DRIFTED)
    assert source == "manifest-partial"
    assert {c.name for c in cfg.candidates} == set(manifest["candidates"])
    assert list(cfg.judges) == manifest["judges"]

    records = [
        BattleRecord.model_validate_json(line)
        for line in log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    _, report = rebuild_from_log(cfg, records, preflight=manifest.get("preflight"))
    assert report["fleiss"]["kappa"] == manifest["fleiss"]["kappa"]
    assert report["mean_agreement"] == manifest["mean_agreement"]


def test_a_manifest_never_steers_where_this_machine_sends_its_key():
    """Manifests get forwarded (bug reports ask for one). Rebuilding through a
    recorded `base_url` would let a file someone else wrote choose the host the
    report's authenticated catalog read goes to."""
    hostile = ArenaConfig.model_validate(
        {
            **RAN_WITH.model_dump(),
            "gateway": {"base_url": "https://attacker.example/v3/router"},
        }
    )
    local = DRIFTED.gateway.base_url

    from_blob, _ = config_from_manifest({"config": hostile.model_dump(mode="json")}, DRIFTED)
    from_map, _ = config_from_manifest(_manifest(hostile, with_config=False), DRIFTED)
    assert from_blob.gateway.base_url == local
    assert from_map.gateway.base_url == local
    # ...while still taking the identity it is there to carry.
    assert [c.name for c in from_blob.candidates] == [c.name for c in RAN_WITH.candidates]


def test_a_manifested_log_survives_an_unreadable_config_file(tmp_path, monkeypatch):
    log, drifted = _write_run(tmp_path)
    drifted.write_text("candidates: [oops\n  broken: yaml", encoding="utf-8")
    res, page = _report([str(log)], tmp_path, monkeypatch)
    assert res.exit_code == 0, res.output
    assert "our-default" not in page
