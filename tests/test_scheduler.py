"""Round-robin scheduler + per-round outcome feed."""

from orq_arena.data.schemas import BattleRecord
from orq_arena.candidates import CandidateSpec
from orq_arena.tournament.driver import outcomes_from_records, round_robin_schedule


def _w(i: int) -> CandidateSpec:
    return CandidateSpec(name=f"orc{i}", model_id=f"x/m{i}")


def test_every_pair_exactly_once():
    candidates = [_w(i) for i in range(8)]
    schedule = round_robin_schedule(candidates)
    assert len(schedule) == 28  # C(8,2)
    pairs = {frozenset((a.name, b.name)) for a, b in schedule}
    assert len(pairs) == 28
    assert all(len(p) == 2 for p in pairs)  # no self-pairs


def test_schedule_is_seed_stable():
    candidates = [_w(i) for i in range(6)]
    s1 = round_robin_schedule(candidates, seed=7)
    s2 = round_robin_schedule(candidates, seed=7)
    assert [(a.name, b.name) for a, b in s1] == [(a.name, b.name) for a, b in s2]


def _rec(majority: str, error: str | None = None, category: str = "code") -> BattleRecord:
    return BattleRecord(
        prompt_hash="h",
        prompt_text="p",
        model_a="ma",
        model_b="mb",
        majority_verdict=majority,
        error=error,
        prompt_category=category,
    )


def test_outcomes_include_wins_and_ties_skip_rest():
    records = [
        _rec("A"),
        _rec("B"),
        _rec("tie"),
        _rec("inconclusive"),
        _rec("inconclusive", error="void"),
    ]
    out = outcomes_from_records(records, "Alpha", "Beta")
    assert out == [
        ("Alpha", "Beta", "winner", "code"),
        ("Beta", "Alpha", "winner", "code"),
        ("Alpha", "Beta", "tie", "code"),
    ]


def test_elo_by_category_respects_floor():
    from orq_arena.tournament.driver import elo_by_category

    # 25 code outcomes (passes the 20 floor), 3 math (skipped)
    outcomes = [("a", "b", "winner", "code")] * 25 + [("b", "a", "winner", "math")] * 3
    sliced = elo_by_category(outcomes)
    assert "code" in sliced and "math" not in sliced
    assert sliced["code"]["a"] > sliced["code"]["b"]


def test_elo_by_category_excludes_absent_models():
    from orq_arena.tournament.driver import elo_by_category

    # 'c' never plays in code; it must not appear seeded at 1000.
    outcomes = [("a", "b", "winner", "code")] * 20 + [("c", "a", "winner", "math")] * 20
    sliced = elo_by_category(outcomes)
    assert set(sliced["code"]) == {"a", "b"}
    assert "c" not in sliced["code"]
