"""A rejudge Spearman prints its n and earns its verdict word, or neither.

The regression (RES-1153): one Spearman value was printed bare and graded
"judge-robust ranking" at >= 0.8. Over a small pool the statistic is too
coarse for the grade: at 4 models the only reachable values clearing 0.8 are
0.8 and 1.0, so a single adjacent swap was the entire distance between the
two verdicts, and no n was shown to warn the reader.
"""

from __future__ import annotations

from types import SimpleNamespace

from orq_arena.rejudge import MIN_VERDICT_MODELS, render_result, spearman_verdict


def test_verdict_word_needs_a_field_wide_enough_to_earn_it():
    assert spearman_verdict(0.85, 8) == "judge-robust ranking"
    assert spearman_verdict(0.5, 8) == "ranking is panel-sensitive; treat with care"
    # 4 models: perfect correlation still gets no verdict word, only the why
    assert spearman_verdict(1.0, 4) == "too few models (4) for a robustness verdict"
    assert spearman_verdict(1.0, MIN_VERDICT_MODELS) == "judge-robust ranking"


def _result(n_models: int, rho: float) -> dict:
    ranking = [f"m{i}" for i in range(n_models)]
    return {
        "total": 30,
        "changed_verdicts": 3,
        "spearman": rho,
        "old_ranking": ranking,
        "new_ranking": list(reversed(ranking)),
        "report": SimpleNamespace(per_judge=[], mean_agreement=None),
    }


def _rendered(capsys, result: dict) -> str:
    render_result(result)
    # rich wraps to terminal width; join lines so substrings survive the wrap
    return " ".join(capsys.readouterr().out.split())


def test_rendered_line_carries_model_and_round_counts(capsys):
    out = _rendered(capsys, _result(8, 1.0))
    assert "over 8 models, 30 rounds" in out
    assert "judge-robust ranking" in out


def test_rendered_line_withholds_the_verdict_below_the_floor(capsys):
    out = _rendered(capsys, _result(4, 1.0))
    assert "over 4 models, 30 rounds" in out
    assert "too few models (4) for a robustness verdict" in out
    assert "judge-robust" not in out
