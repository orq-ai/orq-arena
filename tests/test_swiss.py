"""Swiss pairing: score groups, rematch avoidance, odd float."""

from orq_arena.tournament.swiss import SwissScheduler


def test_first_round_pairs_everyone():
    s = SwissScheduler([f"m{i}" for i in range(10)])
    pairs = s.next_round_pairs()
    assert len(pairs) == 5
    flat = [n for p in pairs for n in p]
    assert len(set(flat)) == 10


def test_winners_meet_winners_and_no_rematch():
    names = ["a", "b", "c", "d"]
    s = SwissScheduler(names)
    r1 = s.next_round_pairs()
    for w, l in r1:
        s.record_outcome(w, l)  # first name wins
    winners = {w for w, _ in r1}
    r2 = s.next_round_pairs()
    assert all(frozenset(p) not in {frozenset(q) for q in r1} for p in r2)
    # the two round-1 winners are paired together
    assert any(set(p) == winners for p in r2)


def test_odd_pool_floats_one():
    s = SwissScheduler(["a", "b", "c"])
    pairs = s.next_round_pairs()
    assert len(pairs) == 1


def test_tie_scores_half_each():
    s = SwissScheduler(["a", "b"])
    s.record_outcome("a", "b", tie=True)
    assert s._state.scores["a"] == s._state.scores["b"] == 0.5
