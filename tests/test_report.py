"""The single-file HTML report renders from records + report dict alone."""

from orq_arena.config import ArenaConfig
from orq_arena.data.schemas import BattleRecord
from orq_arena.report import build_report_html, report_path_for

CFG = ArenaConfig.model_validate({
    "warriors": [{"model_id": "prov/model-a"}, {"model_id": "prov/model-b"}],
    "judges": ["prov/judge-1", "prov/judge-2"],
})


def _record(verdict: str) -> BattleRecord:
    return BattleRecord(
        prompt_hash="h", prompt_text="p?", prompt_category="general",
        model_a="model-a", model_b="model-b",
        response_a="ra", response_b="rb", majority_verdict=verdict,
        winner="model-a" if verdict == "A" else verdict,
        judge_votes=[{"model": "prov/judge-1", "vote": verdict, "flipped": False,
                      "replacement": False, "explanation": "x"}],
        tokens_a_in=10, tokens_a_out=20, tokens_b_in=10, tokens_b_out=25,
        judge_tokens_in=100, judge_tokens_out=30,
    )


REPORT = {
    "elo_ci": {"model-a": (900.0, 1300.0), "model-b": (700.0, 1100.0)},
    "elo_by_category": {}, "category_counts": {"general": 3},
    "tokens": {"warriors_in": 40, "warriors_out": 90, "judges_in": 400, "judges_out": 120},
    "jury": {"per_judge": [
        {"model": "prov/judge-1", "a_rate": 0.7, "b_rate": 0.3,
         "position_bias": 0.25, "tie_rate": 0.05},
    ]},
    "mean_agreement": 0.93,
    "fleiss": {"kappa": 0.8, "label": "substantial", "rounds_used": 3, "rounds_total": 4},
    "cohen": {}, "verbosity": {"model-a": 20.0, "model-b": 25.0},
    "reasoning_tokens": {}, "win_grid": {"model-a": {"model-b": 2.0}, "model-b": {"model-a": 1.0}},
    "thinking": {"model-a": False, "model-b": True},
    "mixed_pool": True, "error_rounds": 0, "rated_rounds": 3,
}

MANIFEST = {
    "tournament_id": "tour-1", "started_at": 1000.0, "finished_at": 1600.0,
    "seed": 42, "config_sha256": "abc", "prompts_sha256": "def", "prompt_count": 3,
    "judges": ["prov/judge-1", "prov/judge-2"], "evaluatorq_version": "1.8.0",
}


def test_report_renders_every_section():
    records = [_record("A"), _record("A"), _record("tie"), _record("inconclusive")]
    html = build_report_html(
        cfg=CFG, records=records, elo={"model-a": 1100.0, "model-b": 900.0},
        report=REPORT, manifest=MANIFEST,
    )
    assert "leads the 2-model pool" in html and "model-a" in html
    for section in ("Leaderboard", "Win grid", "The jury", "Rounds and categories", "Tokens"):
        assert section in html
    assert "10.0 min" in html
    assert "CI overlap" in html  # runner-up hi (1100) >= champion lo (900)
    assert "thinking" in html  # model-b badge
    assert "—" not in html  # house style: no em-dashes anywhere


def test_report_path_convention(tmp_path):
    assert report_path_for(tmp_path / "battles.jsonl").name == "battles.report.html"
