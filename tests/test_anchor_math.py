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
    res = anchor_result(
        RECORDS,
        [
            _vs("h1", {k: "A" for k in KEYS}),
            _vs("h2", {k: "A" for k in KEYS}),
        ],
    )
    assert len(res["inter_annotator"]) == 1
    assert res["inter_annotator"][0]["kappa"] == 1.0


def test_annotator_named_panel_does_not_collide():
    res = anchor_result(RECORDS, [_vs("panel", {k: "A" for k in KEYS})])
    assert res["per_annotator"][0]["kappa"] == 1.0


def test_load_votes_roundtrip(tmp_path):
    p = tmp_path / "votes.json"
    p.write_text(
        json.dumps(
            {
                "schema": 1,
                "seed": 42,
                "source": "x",
                "annotator": "h1",
                "votes": {KEYS[0]: "A", KEYS[1]: "tie"},
            }
        )
    )
    (vs,) = load_votes([p])
    assert vs.annotator == "h1" and vs.votes[KEYS[1]] == "tie"


def test_zero_covoted_rounds_yields_nan_spearman_not_alphabetical():
    res = anchor_result(RECORDS, [_vs("h1", {"deadbeefdeadbeef": "A"})])
    row = res["per_annotator"][0]
    assert row["spearman"] != row["spearman"]  # NaN


def _multi_rec(i: int, a: str, b: str, verdict: str):
    from orq_arena.data.schemas import BattleRecord

    return BattleRecord(
        prompt_hash=f"mh{i}",
        prompt_text=f"p{i}",
        model_a=a,
        model_b=b,
        response_a="ra",
        response_b="rb",
        majority_verdict=verdict,
        match_id=f"m{a}{b}",
        round_number=i,
    )


def test_rho_is_fit_on_the_covoted_rounds_with_no_filler_models():
    """The RES-1153 repro. The rater voted only a-vs-b rounds and agreed with
    the panel on every one, so their rho is 1.0 by construction. The old code
    fit the panel ranking over the whole log (where unvoted a-vs-c rounds put
    c on top) and the human ranking over all models (seating never-seen c at
    the 1000 default), and reported 0.50: an artifact of the filler, not a
    measure of the rater."""
    records = [_multi_rec(i, "a", "b", "A") for i in range(4)] + [
        _multi_rec(10 + i, "a", "c", "B") for i in range(6)
    ]
    voted = {record_key(r): "A" for r in records[:4]}
    row = anchor_result(records, [_vs("h1", voted)])["per_annotator"][0]
    assert row["n_rank_models"] == 2  # a and b; c never entered a voted round
    assert row["spearman"] == 1.0


def test_panel_side_is_fit_on_the_covoted_rounds_not_the_whole_log():
    """Same models, different populations. The panel's verdict over the whole
    log is b > a (6 of 10 rounds), but over the rounds this rater voted it is
    a > b, and the rater agreed with every one of those. Their rho is 1.0; a
    panel side fit on the whole log would report -1.0 and call this rater
    maximally wrong for agreeing with the panel."""
    voted_recs = [_multi_rec(i, "a", "b", "A") for i in range(4)]
    unvoted = [_multi_rec(10 + i, "a", "b", "B") for i in range(6)]
    voted = {record_key(r): "A" for r in voted_recs}
    row = anchor_result(voted_recs + unvoted, [_vs("h1", voted)])["per_annotator"][0]
    assert row["spearman"] == 1.0
    assert row["n_rank_models"] == 2


def test_models_below_the_comparison_floor_are_left_out():
    """Two co-voted rounds do not earn c a rank; its votes still count."""
    records = [_multi_rec(i, "a", "b", "A") for i in range(4)] + [
        _multi_rec(20 + i, "a", "c", "A") for i in range(2)
    ]
    voted = {record_key(r): "A" for r in records}
    row = anchor_result(records, [_vs("h1", voted)])["per_annotator"][0]
    assert row["n_voted"] == 6
    assert row["n_rank_models"] == 2


def test_fewer_than_two_rankable_models_is_no_ranking_claim():
    records = [_multi_rec(i, "a", "b", "A") for i in range(2)]
    voted = {record_key(r): "A" for r in records}
    row = anchor_result(records, [_vs("h1", voted)])["per_annotator"][0]
    assert row["n_rank_models"] == 0  # both sides sit below the floor
    assert row["spearman"] != row["spearman"]  # NaN, not an alphabetical tie


def test_panel_inconclusive_rounds_carry_no_ranking_claim():
    """Review-demonstrated artifact: with every co-voted round inconclusive,
    the panel-side fit had no outcomes, `_ranking` fell back to
    `sorted(models)`, and rho read +-1.0 depending on which side of the
    alphabet the rater's votes landed. Rounds the panel never decided cannot
    carry the comparison at all."""
    records = [_multi_rec(i, "a", "b", "inconclusive") for i in range(4)]
    for vote in ("A", "B"):
        voted = {record_key(r): vote for r in records}
        row = anchor_result(records, [_vs("h1", voted)])["per_annotator"][0]
        assert row["n_rank_models"] == 0
        assert row["spearman"] != row["spearman"], f"alphabetical rho for vote={vote}"


def test_rounds_against_dropped_models_do_not_clear_the_floor():
    """Review-demonstrated filler: d had 3 co-voted rounds, every one against
    below-floor e/f. Those games vanish from the Bradley-Terry fit (it only
    reads pairs of listed models), so d sat at the 1000 default with a passing
    grade. The floor now counts rounds against other rankable models only, to
    a fixed point."""
    records = [_multi_rec(i, "a", "b", "A") for i in range(4)] + [
        _multi_rec(10, "d", "e", "A"),
        _multi_rec(11, "d", "f", "A"),
        _multi_rec(12, "d", "e", "B"),
    ]
    voted = {record_key(r): "A" for r in records}
    row = anchor_result(records, [_vs("h1", voted)])["per_annotator"][0]
    assert row["n_rank_models"] == 2  # a and b; d's rounds were all vs filler
