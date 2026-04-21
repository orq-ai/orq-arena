"""Damage mapping: verdict counts → HP damage + loser side."""

from __future__ import annotations

from orc_arena.arena.damage import compute_damage
from orc_arena.config import MatchRules
from orc_arena.judges.schemas import JudgeResult


def _v(judge: str, verdict: str) -> JudgeResult:
    return JudgeResult(judge_name=judge, judge_model=f"model-{judge}", verdict=verdict)  # type: ignore[arg-type]


def test_unanimous_a_deals_max_damage_to_b() -> None:
    rules = MatchRules()
    verdicts = [_v("j1", "A"), _v("j2", "A"), _v("j3", "A")]
    result = compute_damage(majority="A", verdicts=verdicts, rules=rules)
    assert result.damage == rules.damage_unanimous
    assert result.loser_side == "b"
    assert result.counts_toward_cap is True


def test_majority_b_deals_half_damage_to_a() -> None:
    rules = MatchRules()
    verdicts = [_v("j1", "B"), _v("j2", "B"), _v("j3", "A")]
    result = compute_damage(majority="B", verdicts=verdicts, rules=rules)
    assert result.damage == rules.damage_majority
    assert result.loser_side == "a"
    assert result.counts_toward_cap is True


def test_tie_does_not_count_and_no_damage() -> None:
    rules = MatchRules()
    result = compute_damage(majority="TIE", verdicts=[_v("j1", "TIE")], rules=rules)
    assert result.damage == rules.damage_tie
    assert result.loser_side == "none"
    assert result.counts_toward_cap is False


def test_discard_behaves_like_tie() -> None:
    rules = MatchRules()
    result = compute_damage(majority="DISCARD", verdicts=[], rules=rules)
    assert result.damage == 0
    assert result.loser_side == "none"
    assert result.counts_toward_cap is False
