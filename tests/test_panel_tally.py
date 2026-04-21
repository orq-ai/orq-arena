"""Judge panel: majority vote + self-judge exclusion."""

from __future__ import annotations

from orc_arena.judges.panel import filter_self_judges, majority_vote
from orc_arena.judges.schemas import JudgeResult


def _v(judge: str, model: str, verdict: str) -> JudgeResult:
    return JudgeResult(judge_name=judge, judge_model=model, verdict=verdict)  # type: ignore[arg-type]


def test_two_of_three_majority_wins() -> None:
    verdicts = [
        _v("j1", "m1", "A"),
        _v("j2", "m2", "A"),
        _v("j3", "m3", "B"),
    ]
    assert majority_vote(verdicts) == "A"


def test_all_tie_returns_tie() -> None:
    verdicts = [
        _v("j1", "m1", "TIE"),
        _v("j2", "m2", "TIE"),
        _v("j3", "m3", "TIE"),
    ]
    assert majority_vote(verdicts) == "TIE"


def test_split_a_b_tie_gets_tie_not_discard() -> None:
    verdicts = [
        _v("j1", "m1", "A"),
        _v("j2", "m2", "B"),
    ]
    assert majority_vote(verdicts) == "TIE"


def test_empty_is_discard() -> None:
    assert majority_vote([]) == "DISCARD"


def test_self_judge_excluded() -> None:
    verdicts = [
        _v("j1", "model-a", "A"),  # j1 is contestant A
        _v("j2", "m2", "A"),
        _v("j3", "m3", "B"),
    ]
    filtered = filter_self_judges(verdicts, {"model-a"})
    assert len(filtered) == 2
    assert all(v.judge_model != "model-a" for v in filtered)


def test_self_judge_exclusion_preserves_others() -> None:
    verdicts = [_v("j1", "m1", "A"), _v("j2", "m2", "B")]
    filtered = filter_self_judges(verdicts, {"unused-model"})
    assert filtered == verdicts
