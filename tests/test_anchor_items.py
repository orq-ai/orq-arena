"""Round keys and blinded item extraction."""

from orq_arena.anchor import annotation_items, record_key
from orq_arena.data.schemas import BattleRecord


def _rec(i: int, verdict: str = "A") -> BattleRecord:
    return BattleRecord(
        prompt_hash=f"hash{i}", prompt_text=f"prompt {i}",
        model_a="model-one", model_b="model-two",
        response_a=f"answer a {i}", response_b=f"answer b {i}",
        majority_verdict=verdict, match_id="m1", round_number=i,
    )


RECORDS = [_rec(i) for i in range(6)]


def test_record_key_is_stable_and_opaque():
    k1, k2 = record_key(RECORDS[0]), record_key(RECORDS[0])
    assert k1 == k2 and len(k1) == 16
    assert "model-one" not in k1 and k1 != record_key(RECORDS[1])


def test_items_are_seeded_shuffled_and_blind():
    items = annotation_items(RECORDS, seed=7)
    assert items == annotation_items(RECORDS, seed=7)          # deterministic
    assert [i["k"] for i in items] != [record_key(r) for r in RECORDS]  # shuffled
    keys = {i["k"] for i in items}
    assert keys == {record_key(r) for r in RECORDS}
    for it in items:
        assert set(it) == {"k", "q", "a", "b", "f"}            # nothing extra leaks


def test_flip_is_seeded_per_key_and_mixed():
    items = annotation_items(RECORDS, seed=7)
    again = {i["k"]: i["f"] for i in annotation_items(RECORDS, seed=7)}
    assert all(again[i["k"]] == i["f"] for i in items)
    assert annotation_items(RECORDS, seed=8) != items          # seed changes order/flips


def test_sample_truncates_after_shuffle():
    assert len(annotation_items(RECORDS, seed=7, sample=3)) == 3


def test_exclude_drops_already_voted_keys():
    keys = {record_key(r) for r in RECORDS[:2]}
    items = annotation_items(RECORDS, seed=7, exclude=keys)
    assert {i["k"] for i in items} == {record_key(r) for r in RECORDS[2:]}
    # exclusion composes with sample (filter first, then truncate)
    assert len(annotation_items(RECORDS, seed=7, exclude=keys, sample=2)) == 2
