"""A jury that decided nothing reports failure, it does not report a ranking.

The regression: every judge call in a rejudge returned 401, every panel
collapsed 0/3, and `render_result` still printed a full "new ranking" line and
a Spearman number. The ranking was an artifact of `outcomes_from_majorities`
seeing no decisive outcome for any pair, so Bradley-Terry ranked a field of
models that had never actually been compared. A credential typo was
indistinguishable from a real result.

The rule: a comparison whose winner is "inconclusive" carries no preference.
When none of them do, there is nothing to rank and nothing to correlate, and
saying so is the only honest output.
"""

from __future__ import annotations

from types import SimpleNamespace

from orq_arena.rejudge import decisive_count, render_result


class _Comparison:
    def __init__(self, winner: str) -> None:
        self.winner = winner


def test_inconclusive_comparisons_do_not_count_as_decisions():
    assert decisive_count([_Comparison("A"), _Comparison("B"), _Comparison("tie")]) == 3
    assert decisive_count([_Comparison("inconclusive")] * 5) == 0
    assert decisive_count([_Comparison("A"), _Comparison("inconclusive")]) == 1
    assert decisive_count([]) == 0


def _result(*, decisive: int, total: int = 30) -> dict:
    ranking = [f"m{i}" for i in range(8)]
    return {
        "total": total,
        "decisive": decisive,
        "changed_verdicts": 0,
        "spearman": 1.0,
        "old_ranking": ranking,
        "new_ranking": list(reversed(ranking)),
        "report": SimpleNamespace(
            per_judge=[],
            mean_agreement=None,
            model_dump=lambda: {"per_judge": [], "inconclusive_rate": 1.0},
        ),
    }


def _rendered(capsys, result: dict) -> str:
    render_result(result)
    return " ".join(capsys.readouterr().out.split())


def test_a_fully_collapsed_jury_prints_no_ranking_and_no_correlation(capsys):
    out = _rendered(capsys, _result(decisive=0))
    assert "no usable verdict" in out
    # the three things that made the failure look like a result
    assert "new ranking" not in out
    assert "old ranking" not in out
    assert "Spearman" not in out


def test_a_fully_collapsed_jury_says_how_many_rounds_it_lost(capsys):
    """The count printed is the count that failed.

    The line used to interpolate `decisive`, which is 0 on this branch, so it
    read "no usable verdict in 0 of 48 rounds": literally, that zero rounds
    went wrong.
    """
    out = _rendered(capsys, _result(decisive=0, total=48))
    assert "in any of 48 rounds" in out
    assert "0 of 48" not in out


def test_a_working_jury_still_renders_the_ranking(capsys):
    out = _rendered(capsys, _result(decisive=30))
    assert "new ranking" in out
    assert "Spearman" in out


def test_a_partly_collapsed_jury_still_ranks_but_shows_the_shortfall(capsys):
    """Some verdicts is not no verdicts. The ranking stands on what was decided,
    and the count that produced it is printed rather than implied."""
    out = _rendered(capsys, _result(decisive=7, total=30))
    assert "new ranking" in out
    assert "7 of 30" in out


def test_a_mostly_collapsed_jury_gets_a_number_but_no_verdict_word(capsys):
    """One decided round of 48 printed "judge-robust ranking".

    The guard only fired at exactly zero. The correlation is fit on the decided
    rounds, so a single round can produce rho 1.00, and the grade then vouched
    for a ranking the panel had almost entirely failed to judge. The number and
    its count still print; the verdict word does not.
    """
    out = _rendered(capsys, _result(decisive=1, total=48))
    assert "1 of 48 rounds decided" in out
    assert "too few rounds decided for a robustness verdict" in out
    assert "judge-robust" not in out
    assert "panel-sensitive" not in out


def test_the_verdict_floor_is_half_the_rounds(capsys):
    assert "judge-robust ranking" in _rendered(capsys, _result(decisive=24, total=48))
    assert "judge-robust" not in _rendered(capsys, _result(decisive=23, total=48))


def test_a_clean_run_keeps_the_round_phrasing_it_had(capsys):
    """RES-1153 shaped this line; a run that decided everything reads as before,
    so the shortfall wording only appears when there is a shortfall."""
    out = _rendered(capsys, _result(decisive=30, total=30))
    assert "over 8 models, 30 rounds," in out
    assert "of 30 rounds decided" not in out


def test_a_live_run_that_decides_nothing_rates_nobody():
    """The tournament path, as opposed to rejudge.

    `outcomes_from_records` already drops inconclusive rounds from the rating
    feed, so an all-collapsed run reaches the report with nothing to rate. That
    is the correct behaviour and the reason the live path never showed this bug;
    this pins it, because the failure mode is silent if it ever regresses.
    """
    from orq_arena.config import ArenaConfig
    from orq_arena.data.schemas import BattleRecord
    from orq_arena.tournament.driver import _final_report, outcomes_from_records

    cfg = ArenaConfig.model_validate(
        {
            "candidates": [{"model_id": "p/a"}, {"model_id": "p/b"}, {"model_id": "p/c"}],
            "judges": ["p/j1", "p/j2"],
        }
    )
    records = [
        BattleRecord(
            prompt_hash=f"h{i}",
            prompt_text="q",
            model_a="a",
            model_b="b",
            majority_verdict="inconclusive",
        )
        for i in range(12)
    ]
    outcomes = [o for r in records for o in outcomes_from_records([r], r.model_a, r.model_b)]
    assert outcomes == []

    report = _final_report(cfg, records, outcomes, ["a", "b", "c"])
    assert report["rated_rounds"] == 0
    # no rating, and therefore no champion for the standings to crown
    assert report.get("elo") is None
    assert report.get("top_difference") is None


class _AllInconclusive:
    """Stands in for evaluatorq's jury when every panel collapses."""

    async def compare(self, **_kw):
        from evaluatorq import PairwiseComparison

        return PairwiseComparison.model_validate({"winner": "inconclusive", "votes": []})


async def test_rejudge_run_reports_a_collapsed_panel_as_zero_decisive(monkeypatch):
    """The count comes from the real run, not from a hand-built dict.

    Every other test here builds `result` itself, so dropping the `decisive`
    key from `rejudge_run` left the suite green while `render_result` fell back
    to "everything decided" and printed a ranking again. This is the test that
    fails when the key goes.
    """
    from types import SimpleNamespace

    from orq_arena import rejudge as rejudge_mod
    from orq_arena.config import ArenaConfig
    from orq_arena.data.schemas import BattleRecord

    monkeypatch.setattr(rejudge_mod, "OrqGateway", lambda cfg: SimpleNamespace(client=object()))
    monkeypatch.setattr(rejudge_mod, "llm_jury_pairwise", lambda **_kw: _AllInconclusive())

    cfg = ArenaConfig.model_validate(
        {"candidates": [{"model_id": "p/a"}, {"model_id": "p/b"}], "judges": ["p/j1", "p/j2"]}
    )
    records = [
        BattleRecord(
            prompt_hash=f"h{i}",
            prompt_text="q",
            model_a="a",
            model_b="b",
            model_a_id="p/a",
            model_b_id="p/b",
            response_a="ra",
            response_b="rb",
            majority_verdict="A",
            match_id="m1",
            round_number=i,
        )
        for i in range(6)
    ]

    result = await rejudge_mod.rejudge_run(cfg=cfg, records=records, judges=["p/j1"])

    assert result["decisive"] == 0
    assert result["total"] == 6


def test_the_saved_report_does_not_carry_a_ranking_the_terminal_refused(tmp_path):
    """`--report-json` is the artifact a reader reuses, and it kept the number.

    The terminal said "no usable verdict" while the file next to it carried a
    full ranking and a Spearman, and `--compare` printed that Spearman as a
    panel's robustness score.
    """
    import json

    from orq_arena.rejudge import compare_reports, save_report_json

    path = tmp_path / "panel.json"
    save_report_json(path, _result(decisive=0, total=48))
    saved = json.loads(path.read_text(encoding="utf-8"))

    assert saved["decisive"] == 0
    assert saved["spearman"] is None
    assert saved["new_ranking"] is None
    # and the jury-selection table cannot resurrect it
    (row,) = compare_reports([path])
    assert row["spearman"] is None


def test_a_decided_report_is_saved_exactly_as_before(tmp_path):
    import json

    from orq_arena.rejudge import save_report_json

    path = tmp_path / "panel.json"
    save_report_json(path, _result(decisive=30, total=30))
    saved = json.loads(path.read_text(encoding="utf-8"))

    assert saved["decisive"] == 30
    assert saved["spearman"] == 1.0
    assert saved["new_ranking"] == list(reversed([f"m{i}" for i in range(8)]))
