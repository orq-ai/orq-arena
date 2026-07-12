"""Chance-corrected agreement math."""

from orq_arena.analysis.kappa import cohen_kappa_pairs, fleiss_kappa, landis_koch


def _round(votes):  # [(judge, vote)] -> judge_votes dicts
    return [{"model": j, "vote": v, "replacement": False} for j, v in votes]


PANEL = ["j1", "j2", "j3"]


def test_perfect_agreement_is_kappa_one():
    rounds = [_round([("j1", "A"), ("j2", "A"), ("j3", "A")]),
              _round([("j1", "B"), ("j2", "B"), ("j3", "B")])]
    r = fleiss_kappa(rounds, PANEL)
    assert r["kappa"] == 1.0 and r["label"] == "almost perfect"
    assert r["rounds_used"] == 2


def test_partial_panels_are_excluded_from_fleiss():
    rounds = [
        _round([("j1", "A"), ("j2", "A"), ("j3", "A")]),
        _round([("j1", "A"), ("j2", None), ("j3", "A")]),   # abstention -> excluded
        _round([("j1", "A"), ("j2", "A"), ("j3", "A")]),
    ]
    r = fleiss_kappa(rounds, PANEL)
    assert r["rounds_used"] == 2 and r["rounds_total"] == 3


def test_cohen_pairs_cover_covoted_rounds():
    rounds = [_round([("j1", "A"), ("j2", "A"), ("j3", "B")]),
              _round([("j1", "B"), ("j2", "B"), ("j3", "B")]),
              _round([("j1", "tie"), ("j2", "tie"), ("j3", "tie")])]
    pairs = cohen_kappa_pairs(rounds, PANEL)
    assert pairs["j1 × j2"]["kappa"] == 1.0
    assert pairs["j1 × j2"]["rounds"] == 3


def test_landis_koch_labels():
    assert landis_koch(0.15) == "slight"
    assert landis_koch(0.75) == "substantial"
