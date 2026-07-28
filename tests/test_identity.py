"""Two models must never quietly become one.

The regression: display names default to the model id with its provider prefix
stripped, so `openai/gpt-oss-120b` and `groq/gpt-oss-120b` both became
`gpt-oss-120b`. The alias map collapsed to a single key and the two models were
rated as one, with nothing printed to say so.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orq_arena.config import ORQ_API_KEY_ENV, ArenaConfig


def _cfg(candidates: list[dict]) -> ArenaConfig:
    return ArenaConfig.model_validate({"candidates": candidates, "judges": ["prov/j1", "prov/j2"]})


def test_the_same_model_from_two_providers_keeps_two_identities():
    cfg = _cfg([{"model_id": "openai/gpt-oss-120b"}, {"model_id": "groq/gpt-oss-120b"}])
    names = [c.name for c in cfg.candidates]
    assert len(set(names)) == 2, f"both models answer to {names[0]!r}"


def test_a_collision_falls_back_to_the_full_model_id():
    """The full id is the one name that is unique by construction."""
    cfg = _cfg([{"model_id": "openai/gpt-oss-120b"}, {"model_id": "groq/gpt-oss-120b"}])
    assert {c.name for c in cfg.candidates} == {"openai/gpt-oss-120b", "groq/gpt-oss-120b"}


def test_uncontested_short_names_stay_short():
    """The fallback only fires on a real collision; ordinary pools read the same."""
    cfg = _cfg([{"model_id": "openai/gpt-5.4"}, {"model_id": "anthropic/claude-opus-4-8"}])
    assert [c.name for c in cfg.candidates] == ["gpt-5.4", "claude-opus-4-8"]


def test_two_models_sharing_a_written_name_are_pulled_apart_and_reported():
    """A name cannot be honoured for two different models. The full id is the
    one name that distinguishes them, and the swap is reported so nobody has to
    notice a model answering to something they did not write."""
    cfg = _cfg(
        [
            {"model_id": "openai/gpt-5.4", "name": "champ"},
            {"model_id": "anthropic/claude-opus-4-8", "name": "champ"},
        ]
    )
    assert [c.name for c in cfg.candidates] == ["openai/gpt-5.4", "anthropic/claude-opus-4-8"]
    assert cfg.renamed == [("champ", "openai/gpt-5.4"), ("champ", "anthropic/claude-opus-4-8")]


def test_the_same_model_listed_twice_is_an_error_no_rename_can_fix():
    with pytest.raises(ValidationError, match="[Dd]uplicate"):
        _cfg([{"model_id": "openai/gpt-5.4"}, {"model_id": "openai/gpt-5.4"}])


def test_a_clean_pool_reports_no_renames():
    cfg = _cfg([{"model_id": "openai/gpt-5.4"}, {"model_id": "anthropic/claude-opus-4-8"}])
    assert cfg.renamed == []


def test_a_written_name_colliding_with_a_generated_one_pulls_both_apart():
    cfg = _cfg(
        [
            {"model_id": "openai/gpt-5.4"},
            {"model_id": "anthropic/claude-opus-4-8", "name": "gpt-5.4"},
        ]
    )
    assert [c.name for c in cfg.candidates] == ["openai/gpt-5.4", "anthropic/claude-opus-4-8"]


def test_an_old_manifest_of_a_colliding_pool_still_rebuilds():
    """RES-1147 records display names in the manifest, and a pre-collision-fix
    manifest recorded the colliding short name twice. Reading that back must
    resolve, not raise: a rebuild silently falling back to the live YAML is the
    exact failure RES-1147 exists to prevent."""
    from orq_arena.tournament.driver import config_from_manifest

    recorded = {
        "candidates": [
            {"model_id": "openai/gpt-oss-120b", "name": "gpt-oss-120b"},
            {"model_id": "groq/gpt-oss-120b", "name": "gpt-oss-120b"},
        ],
        "judges": ["prov/j1", "prov/j2"],
    }
    cfg, source = config_from_manifest({"config": recorded}, None)
    assert source == "manifest", "an old manifest fell back to the live config"
    assert {c.name for c in cfg.candidates} == {"openai/gpt-oss-120b", "groq/gpt-oss-120b"}


def test_records_carry_the_full_model_id_so_a_log_is_unambiguous():
    from orq_arena.data.schemas import BattleRecord

    rec = BattleRecord(
        prompt_hash="h",
        prompt_text="p",
        model_a="gpt-oss-120b",
        model_b="gpt-oss-120b",
        model_a_id="openai/gpt-oss-120b",
        model_b_id="groq/gpt-oss-120b",
    )
    assert rec.model_a_id != rec.model_b_id


def test_v3_logs_without_model_ids_still_load():
    """Old logs predate the field; they must not fail to parse."""
    from orq_arena.data.schemas import BattleRecord

    rec = BattleRecord.model_validate_json(
        '{"prompt_hash":"h","prompt_text":"p","model_a":"a","model_b":"b"}'
    )
    assert rec.model_a_id == "" and rec.model_b_id == ""


def test_two_providers_of_one_model_are_rated_separately():
    """The end of the chain: distinct names are useless if the rebuild still
    keys on the colliding short name."""
    from orq_arena.data.schemas import BattleRecord
    from orq_arena.tournament.driver import rebuild_from_log

    cfg = _cfg([{"model_id": "openai/gpt-oss-120b"}, {"model_id": "groq/gpt-oss-120b"}])
    records = [
        BattleRecord(
            prompt_hash=f"h{i}",
            prompt_text="p",
            model_a="gpt-oss-120b",
            model_b="gpt-oss-120b",
            model_a_id="openai/gpt-oss-120b",
            model_b_id="groq/gpt-oss-120b",
            response_a="x",
            response_b="y",
            majority_verdict="A",
            winner="gpt-oss-120b",
            judge_votes=[{"model": "prov/j1", "vote": "A"}],
        )
        for i in range(6)
    ]
    elo, _ = rebuild_from_log(cfg, records)
    assert set(elo) == {"openai/gpt-oss-120b", "groq/gpt-oss-120b"}
    assert elo["openai/gpt-oss-120b"] > elo["groq/gpt-oss-120b"]


def test_a_v3_log_without_ids_still_rebuilds_on_short_names():
    from orq_arena.data.schemas import BattleRecord
    from orq_arena.tournament.driver import rebuild_from_log

    cfg = _cfg([{"model_id": "openai/gpt-5.4"}, {"model_id": "anthropic/claude-opus-4-8"}])
    records = [
        BattleRecord(
            prompt_hash="h",
            prompt_text="p",
            model_a="gpt-5.4",
            model_b="claude-opus-4-8",
            response_a="x",
            response_b="y",
            majority_verdict="A",
            winner="gpt-5.4",
            judge_votes=[{"model": "prov/j1", "vote": "A"}],
        )
    ]
    elo, _ = rebuild_from_log(cfg, records)
    assert set(elo) == {"gpt-5.4", "claude-opus-4-8"}


def test_prompt_provenance_distinguishes_two_banks_that_differ_only_by_category(tmp_path):
    """The manifest hash used to cover prompt texts only, so re-labelling every
    prompt's category produced an identical hash and looked like the same bank."""

    from orq_arena.data.prompts import PromptItem
    from orq_arena.tournament.driver import _write_manifest, manifest_path_for, read_manifest

    cfg = _cfg([{"model_id": "p/a"}, {"model_id": "p/b"}])

    def _hash(prompts, name):
        d = tmp_path / name
        d.mkdir()
        _write_manifest(
            manifest_path_for(d / "battles.jsonl"),
            cfg=cfg,
            prompts=prompts,
            seed=42,
            tournament_id="t",
            started_at=0.0,
        )
        return read_manifest(d / "battles.jsonl")["prompts_sha256"]

    same_text_code = [PromptItem(text="write a parser", category="code")]
    same_text_general = [PromptItem(text="write a parser", category="general")]
    assert _hash(same_text_code, "code") != _hash(same_text_general, "general")


def test_dataset_prompts_carry_their_category():
    """Without this every dataset-sourced prompt landed in "general" and
    per-category ELO was dead for dataset runs."""
    from orq_arena.data.prompts import datapoint_to_prompt

    item = datapoint_to_prompt({"category": "math"}, [{"role": "user", "content": "what is 2+2?"}])
    assert item is not None and item.category == "math"

    untagged = datapoint_to_prompt({}, [{"role": "user", "content": "hi"}])
    assert untagged is not None and untagged.category == "general"


def test_a_colliding_pool_does_not_drop_a_contestant_from_self_judge_exclusion():
    """`rejudge` keyed its comparators on the short-name pair, so a colliding
    pool collapsed to a one-element set and one side stopped being recognised
    as a contestant, letting it judge itself."""
    from orq_arena.data.schemas import BattleRecord
    from orq_arena.rejudge import contestant_key, panel_excluding_contestants

    rec = BattleRecord(
        prompt_hash="h",
        prompt_text="p",
        model_a="gpt-oss-120b",
        model_b="gpt-oss-120b",
        model_a_id="openai/gpt-oss-120b",
        model_b_id="groq/gpt-oss-120b",
    )
    key = contestant_key(rec)
    assert len(key) == 2, "both contestants must survive the key"
    panel = panel_excluding_contestants(
        ["openai/gpt-oss-120b", "groq/gpt-oss-120b", "anthropic/claude-haiku-4-5-20251001"],
        key,
        {},
    )
    assert panel == ["anthropic/claude-haiku-4-5-20251001"]


def test_two_rounds_of_a_colliding_pool_get_distinct_annotation_keys():
    """The annotation key hashed short names, so a colliding pool produced one
    key for two different match-ups and human votes crossed between them."""
    from orq_arena.anchor import record_key
    from orq_arena.data.schemas import BattleRecord

    def _rec(a_id: str, b_id: str) -> BattleRecord:
        return BattleRecord(
            prompt_hash="h",
            prompt_text="p",
            model_a="gpt-oss-120b",
            model_b="gpt-oss-120b",
            model_a_id=a_id,
            model_b_id=b_id,
            match_id="M1",
            round_number=1,
        )

    assert record_key(_rec("openai/gpt-oss-120b", "groq/gpt-oss-120b")) != record_key(
        _rec("groq/gpt-oss-120b", "openai/gpt-oss-120b")
    )


def test_v3_annotation_keys_are_unchanged_so_existing_votes_still_match():
    from orq_arena.anchor import record_key
    from orq_arena.data.schemas import BattleRecord

    v3 = BattleRecord(
        prompt_hash="h", prompt_text="p", model_a="a", model_b="b", match_id="M1", round_number=1
    )
    import hashlib

    # The guarantee: with no id fields the key is the pre-v4 input string.
    expected = hashlib.sha256(b"h:a:b:M1:1").hexdigest()[:16]
    assert record_key(v3) == expected


def test_every_per_model_view_separates_a_colliding_pool_not_just_the_ladder(monkeypatch):
    """The leaderboard separated them while verbosity, the length-controlled
    rating and the name map still merged both models into one entry."""
    from orq_arena.data.schemas import BattleRecord
    from orq_arena.tournament import driver as driver_mod
    from orq_arena.tournament.driver import rebuild_from_log
    from orq_arena.tournament.elo import style_controlled_elo

    cfg = _cfg([{"model_id": "openai/gpt-oss-120b"}, {"model_id": "groq/gpt-oss-120b"}])
    records = [
        BattleRecord(
            prompt_hash=f"h{i}",
            prompt_text="p",
            model_a="gpt-oss-120b",
            model_b="gpt-oss-120b",
            model_a_id="openai/gpt-oss-120b",
            model_b_id="groq/gpt-oss-120b",
            response_a="x" * 50,
            response_b="y" * 200,
            majority_verdict="A",
            winner="gpt-oss-120b",
            tokens_a_out=50,
            tokens_b_out=200,
            judge_votes=[{"model": "prov/j1", "vote": "A"}],
        )
        for i in range(6)
    ]

    # The style fit's *published* output is now gated on statistical
    # identification, which a 6-round fixture can never clear, so the identity
    # regression (style rows built from short names became self-matches and
    # the fit learned nothing) is asserted on the rows the fit receives.
    seen_rows: list = []
    real_fit = style_controlled_elo

    def spy(rows, models, **kw):
        seen_rows.append(rows)
        return real_fit(rows, models, **kw)

    monkeypatch.setattr(driver_mod, "style_controlled_elo", spy)
    _, report = rebuild_from_log(cfg, records)
    both = {"openai/gpt-oss-120b", "groq/gpt-oss-120b"}

    assert set(report["verbosity"]) == both
    assert report["verbosity"]["openai/gpt-oss-120b"] == 50.0
    assert report["verbosity"]["groq/gpt-oss-120b"] == 200.0
    assert set(report["reasoning_tokens"]) == both
    assert set(report["by_model_names"].values()) == both
    style_rows = seen_rows[0]
    assert {r[0] for r in style_rows} | {r[1] for r in style_rows} == both
    assert all(r[0] != r[1] for r in style_rows), "style rows are self-matches again"


# --- every panel, not just the ladder -------------------------------------

PANEL_PRICES = {
    "openai/gpt-5.4": (1.0, 2.0),
    "anthropic/claude-opus-4-8": (1.0, 2.0),
    "openai/gpt-oss-120b": (1.0, 2.0),
    "groq/gpt-oss-120b": (1.0, 2.0),
}


def _panel_records(a_id, b_id, a_short, b_short):
    from orq_arena.data.schemas import BattleRecord

    return [
        BattleRecord(
            prompt_hash=f"h{i}",
            prompt_text="p",
            model_a=a_short,
            model_b=b_short,
            model_a_id=a_id,
            model_b_id=b_id,
            response_a="x",
            response_b="y",
            majority_verdict="A",
            winner=a_short,
            tokens_a_in=10,
            tokens_a_out=50,
            tokens_b_in=10,
            tokens_b_out=90,
            duration_a_ms=1000,
            duration_b_ms=2000,
            judge_votes=[{"model": "prov/j1", "vote": "A"}],
        )
        for i in range(4)
    ]


def _panels(cands, a_id, b_id, a_short, b_short):
    """(tui tokens, speed row names, per-model cost) as a reader would see them."""
    from orq_arena.report import _per_model_cost, _speed_stats
    from orq_arena.tournament.driver import rebuild_from_log

    cfg = _cfg(cands)
    recs = _panel_records(a_id, b_id, a_short, b_short)
    _, report = rebuild_from_log(cfg, recs)
    alias = report["by_model_names"]
    manifest = {"candidates": {c.name: {"model": c.model_id} for c in cfg.candidates}}
    names = [c.name for c in cfg.candidates]
    return (
        {n: report["verbosity"].get(n, 0) for n in names},  # leaderboard.py's lookup
        [row[0] for row in _speed_stats(recs, alias)],
        _per_model_cost(recs, manifest, PANEL_PRICES, alias),
    )


@pytest.mark.parametrize(
    "label,cands,a_id,b_id,a_short,b_short",
    [
        (
            "ordinary",
            [{"model_id": "openai/gpt-5.4"}, {"model_id": "anthropic/claude-opus-4-8"}],
            "openai/gpt-5.4",
            "anthropic/claude-opus-4-8",
            "gpt-5.4",
            "claude-opus-4-8",
        ),
        (
            "custom names",
            [
                {"model_id": "openai/gpt-5.4", "name": "Red"},
                {"model_id": "anthropic/claude-opus-4-8", "name": "Blue"},
            ],
            "openai/gpt-5.4",
            "anthropic/claude-opus-4-8",
            "gpt-5.4",
            "claude-opus-4-8",
        ),
        (
            "colliding",
            [{"model_id": "openai/gpt-oss-120b"}, {"model_id": "groq/gpt-oss-120b"}],
            "openai/gpt-oss-120b",
            "groq/gpt-oss-120b",
            "gpt-oss-120b",
            "gpt-oss-120b",
        ),
        (
            "v3 log, no ids",
            [{"model_id": "openai/gpt-5.4"}, {"model_id": "anthropic/claude-opus-4-8"}],
            "",
            "",
            "gpt-5.4",
            "claude-opus-4-8",
        ),
    ],
)
def test_no_panel_merges_or_blanks_a_model(label, cands, a_id, b_id, a_short, b_short):
    """Tokens, speed and cost all key on the record's own key. Keying any one of
    them differently showed two models apart on the ladder and merged, blank or
    missing in another panel, which is worse than either alone."""
    tokens, speed_rows, cost = _panels(cands, a_id, b_id, a_short, b_short)
    assert len(speed_rows) == 2, f"{label}: speed merged into {speed_rows}"
    assert len(cost) == 2, f"{label}: cost lost a model ({cost})"
    assert sorted(tokens.values()) == [50.0, 90.0], f"{label}: tokens read {tokens}"
    assert set(tokens) == set(speed_rows) == set(cost), f"{label}: panels disagree on names"


def test_the_preflight_says_which_models_it_renamed(tmp_path, monkeypatch):
    """methodology.md promises "the preflight says so". A silent merge becoming
    a silent rename would be no better."""
    import json

    from click.testing import CliRunner

    from orq_arena.cli import cli

    cfg = {
        "candidates": [{"model_id": "openai/gpt-oss-120b"}, {"model_id": "groq/gpt-oss-120b"}],
        "judges": ["anthropic/claude-haiku-4-5-20251001"],
        "preflight": {"thinking_probe": False},
    }
    (tmp_path / "c.yaml").write_text(json.dumps(cfg), encoding="utf-8")
    (tmp_path / "p.jsonl").write_text('{"prompt": "hi"}\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(ORQ_API_KEY_ENV, raising=False)  # keeps the catalog read offline

    async def _no_tournament(**_kw):
        return {}

    monkeypatch.setattr("orq_arena.headless.run_headless", _no_tournament)
    monkeypatch.setattr("orq_arena.cli._open_report", lambda *a, **k: None)

    res = CliRunner().invoke(
        cli,
        ["run", "-y", "--config", "c.yaml", "--prompts", "p.jsonl", "--output", "out.jsonl"],
    )
    assert res.exit_code == 0, res.output
    assert "renamed to keep two models apart" in res.output
    assert "openai/gpt-oss-120b" in res.output


def test_listing_one_model_twice_is_an_error_no_rename_can_resolve():
    """Distinct models get pulled apart by falling back to their ids. The same
    id twice has no second identity to fall back to, so it has to raise."""
    with pytest.raises(ValidationError, match="listed twice"):
        _cfg([{"model_id": "openai/gpt-5.4"}, {"model_id": "openai/gpt-5.4"}])
