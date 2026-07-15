"""HPTracker: the TUI-side damage model, derived from judged verdicts."""

from orq_arena.tui.hp import HPTracker


def _tracker() -> HPTracker:
    return HPTracker(starting_hp=100, damage_unanimous=30, damage_majority=15)


def _resolve(votes: list[str], majority: str):
    t = _tracker()
    t.start_match()
    for v in votes:
        t.note_vote(v)
    return t, t.resolve_turn(majority)


def test_unanimous_a_deals_big_damage_to_b():
    t, out = _resolve(["A", "A", "A"], "A")
    assert (out.damage, out.loser_side, out.hp_b) == (30, "b", 70)


def test_majority_b_deals_split_damage_to_a():
    t, out = _resolve(["B", "B", "A"], "B")
    assert (out.damage, out.loser_side, out.hp_a) == (15, "a", 85)


def test_single_decisive_vote_is_never_unanimous():
    # One decisive A, two abstains: must not land the 30-damage unanimous hit.
    t, out = _resolve(["A", "abstain", "abstain"], "A")
    assert (out.damage, out.loser_side) == (15, "b")


def test_tie_vote_breaks_unanimity():
    t, out = _resolve(["A", "A", "tie"], "A")
    assert out.damage == 15


def test_tie_verdict_deals_no_damage():
    t, out = _resolve(["tie", "tie", "A"], "tie")
    assert (out.damage, out.loser_side) == (0, "none")


def test_inconclusive_deals_no_damage():
    t, out = _resolve(["abstain", "abstain", "abstain"], "inconclusive")
    assert (out.damage, out.loser_side) == (0, "none")


def test_ko_side_after_health_drained():
    t = _tracker()
    t.start_match()
    for _ in range(4):  # 4 * 30 = 120 > 100 starting hp
        for v in ("A", "A"):
            t.note_vote(v)
        t.resolve_turn("A")
    assert t.ko_side == "b"


def test_start_match_resets_health_and_votes():
    t = _tracker()
    t.start_match()
    t.note_vote("A")
    t.note_vote("A")
    t.resolve_turn("A")
    t.start_match()  # fresh match
    out = t.resolve_turn("A")  # no votes buffered -> majority tier
    assert out.hp_b == 100 - 15
