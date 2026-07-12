"""Anchor math: human votes vs panel, hand-checked."""

import json

from orq_arena.anchor import VoteSet, anchor_result, load_votes, record_key
from tests.test_anchor_items import _rec

# 4 records; panel says A on all four.
RECORDS = [_rec(i, verdict="A") for i in range(4)]
KEYS = [record_key(r) for r in RECORDS]


def _vs(name: str, votes: dict) -> VoteSet:
    return VoteSet(annotator=name, seed=42, source="test", votes=votes)


def test_perfect_agreement_needs_vote_variety_for_kappa():
    # All-A on both sides: observed agreement 1.0 but chance is also 1.0;
    # cohen_kappa_pairs defines kappa = 1.0 there.
    res = anchor_result(RECORDS, [_vs("h1", {k: "A" for k in KEYS})])
    row = res["per_annotator"][0]
    assert row["kappa"] == 1.0 and row["n_kappa"] == 4
    assert row["spearman"] == 1.0


def test_total_disagreement_gives_negative_or_zero_kappa():
    res = anchor_result(RECORDS, [_vs("h1", {k: "B" for k in KEYS})])
    row = res["per_annotator"][0]
    assert row["kappa"] is not None and row["kappa"] <= 0.0


def test_inconclusive_rounds_are_excluded_from_kappa_not_bt():
    recs = [_rec(0, "A"), _rec(1, "inconclusive")]
    keys = [record_key(r) for r in recs]
    res = anchor_result(recs, [_vs("h1", {keys[0]: "A", keys[1]: "B"})])
    row = res["per_annotator"][0]
    assert row["n_voted"] == 2 and row["n_kappa"] == 1


def test_unknown_keys_are_reported_not_crashed():
    res = anchor_result(RECORDS, [_vs("h1", {"deadbeefdeadbeef": "A"})])
    assert res["unknown_keys"] == 1


def test_two_annotators_get_inter_annotator_kappa():
    res = anchor_result(RECORDS, [
        _vs("h1", {k: "A" for k in KEYS}), _vs("h2", {k: "A" for k in KEYS}),
    ])
    assert len(res["inter_annotator"]) == 1
    assert res["inter_annotator"][0]["kappa"] == 1.0


def test_annotator_named_panel_does_not_collide():
    res = anchor_result(RECORDS, [_vs("panel", {k: "A" for k in KEYS})])
    assert res["per_annotator"][0]["kappa"] == 1.0


def test_load_votes_roundtrip(tmp_path):
    p = tmp_path / "votes.json"
    p.write_text(json.dumps({
        "schema": 1, "seed": 42, "source": "x", "annotator": "h1",
        "votes": {KEYS[0]: "A", KEYS[1]: "tie"},
    }))
    (vs,) = load_votes([p])
    assert vs.annotator == "h1" and vs.votes[KEYS[1]] == "tie"


def test_zero_covoted_rounds_yields_nan_spearman_not_alphabetical():
    res = anchor_result(RECORDS, [_vs("h1", {"deadbeefdeadbeef": "A"})])
    row = res["per_annotator"][0]
    assert row["spearman"] != row["spearman"]  # NaN
