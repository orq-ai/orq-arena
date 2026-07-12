"""Damage adapter tests — evaluatorq PairwiseComparison → HP damage."""

from evaluatorq import PairwiseComparison
from evaluatorq.pairwise import PairwiseVote

from orc_arena.arena.damage import compute_damage
from orc_arena.config import MatchRules

RULES = MatchRules()  # 30 unanimous / 15 majority / 0 tie


def _vote(model: str, vote: str | None, *, flipped: bool = False) -> PairwiseVote:
    return PairwiseVote(model=model, vote=vote, flipped=flipped)


def _cmp(winner: str, votes: list[PairwiseVote]) -> PairwiseComparison:
    return PairwiseComparison(winner=winner, votes=votes)


def test_unanimous_a_deals_big_damage_to_b():
    c = _cmp("A", [_vote("j1", "A"), _vote("j2", "A"), _vote("j3", "A")])
    d = compute_damage(comparison=c, rules=RULES)
    assert (d.damage, d.loser_side, d.counts_toward_cap) == (30, "b", True)


def test_majority_b_deals_split_damage_to_a():
    c = _cmp("B", [_vote("j1", "B"), _vote("j2", "B"), _vote("j3", "A")])
    d = compute_damage(comparison=c, rules=RULES)
    assert (d.damage, d.loser_side, d.counts_toward_cap) == (15, "a", True)


def test_single_decisive_vote_is_never_unanimous():
    # Two judges abstained (flipped); one decisive A vote must not land the
    # 30-damage "unanimous" hit — the Finding 05 guard.
    c = _cmp("A", [_vote("j1", "A"), _vote("j2", None, flipped=True), _vote("j3", None)])
    d = compute_damage(comparison=c, rules=RULES)
    assert (d.damage, d.loser_side) == (15, "b")


def test_tie_with_dissent_is_majority_not_unanimous():
    c = _cmp("A", [_vote("j1", "A"), _vote("j2", "A"), _vote("j3", "tie")])
    d = compute_damage(comparison=c, rules=RULES)
    assert d.damage == 15  # a tie vote breaks unanimity


def test_tie_deals_no_damage_and_no_cap_tick():
    c = _cmp("tie", [_vote("j1", "tie"), _vote("j2", "tie"), _vote("j3", "A")])
    d = compute_damage(comparison=c, rules=RULES)
    assert (d.damage, d.loser_side, d.counts_toward_cap) == (0, "none", False)


def test_inconclusive_deals_no_damage_and_no_cap_tick():
    c = _cmp("inconclusive", [_vote("j1", None), _vote("j2", None), _vote("j3", None)])
    d = compute_damage(comparison=c, rules=RULES)
    assert (d.damage, d.loser_side, d.counts_toward_cap) == (0, "none", False)
