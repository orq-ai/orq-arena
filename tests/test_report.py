"""The single-file HTML report renders from records + report dict alone."""

from orq_arena.config import ArenaConfig
from orq_arena.data.schemas import BattleRecord
from orq_arena.report import build_report_html, report_path_for

CFG = ArenaConfig.model_validate(
    {
        "candidates": [{"model_id": "prov/model-a"}, {"model_id": "prov/model-b"}],
        "judges": ["prov/judge-1", "prov/judge-2"],
    }
)


def _record(verdict: str) -> BattleRecord:
    return BattleRecord(
        prompt_hash="h",
        prompt_text="p?",
        prompt_category="general",
        model_a="model-a",
        model_b="model-b",
        response_a="ra",
        response_b="rb",
        majority_verdict=verdict,
        winner="model-a" if verdict == "A" else verdict,
        judge_votes=[
            {
                "model": "prov/judge-1",
                "vote": verdict,
                "flipped": False,
                "replacement": False,
                "explanation": "x",
            }
        ],
        tokens_a_in=10,
        tokens_a_out=20,
        tokens_b_in=10,
        tokens_b_out=25,
        judge_tokens_in=100,
        judge_tokens_out=30,
    )


REPORT = {
    "elo_ci": {"model-a": (900.0, 1300.0), "model-b": (700.0, 1100.0)},
    "elo_by_category": {},
    "category_counts": {"general": 3},
    "tokens": {"models_in": 40, "models_out": 90, "judges_in": 400, "judges_out": 120},
    "jury": {
        "per_judge": [
            {
                "model": "prov/judge-1",
                "a_rate": 0.7,
                "b_rate": 0.3,
                "position_bias": 0.25,
                "tie_rate": 0.05,
            },
        ]
    },
    "mean_agreement": 0.93,
    "fleiss": {"kappa": 0.8, "label": "substantial", "rounds_used": 3, "rounds_total": 4},
    "cohen": {},
    "verbosity": {"model-a": 20.0, "model-b": 25.0},
    "reasoning_tokens": {},
    "win_grid": {"model-a": {"model-b": 2.0}, "model-b": {"model-a": 1.0}},
    "thinking": {"model-a": False, "model-b": True},
    "mixed_pool": True,
    "error_rounds": 0,
    "rated_rounds": 3,
}

MANIFEST = {
    "tournament_id": "bench-1",
    "started_at": 1000.0,
    "finished_at": 1600.0,
    "seed": 42,
    "config_sha256": "abc",
    "prompts_sha256": "def",
    "prompt_count": 3,
    "judges": ["prov/judge-1", "prov/judge-2"],
    "evaluatorq_version": "1.8.0",
}


def test_report_renders_every_section():
    records = [_record("A"), _record("A"), _record("tie"), _record("inconclusive")]
    html = build_report_html(
        cfg=CFG,
        records=records,
        elo={"model-a": 1100.0, "model-b": 900.0},
        report=REPORT,
        manifest=MANIFEST,
    )
    assert "model-a" in html and ("statistically" in html)  # verdict banner headline
    for section in (
        "Leaderboard",
        "Win grid",
        "The jury",
        "Panel verdicts",
        "Tokens and cost",
        "Confidence stats",
        "Methodology in detail",
    ):
        assert section in html
    assert "Category" not in html  # category table removed: not universal across datasets
    assert "10.0 MIN" in html  # duration rides in the header metadata strip (uppercased)
    # runner-up hi (1100) >= champion lo (900): top spot not separated
    assert "indistinguishable at this sample size" in html
    assert "thinking" in html  # model-b badge
    # house style: no em-dashes anywhere, literal or HTML-entity
    assert not any(d in html for d in ("—", "&mdash;", "&#8212;", "&#x2014;"))


def test_report_family_overlap_badge_from_manifest():
    records = [_record("A"), _record("A")]
    manifest = MANIFEST | {"preflight": {"family_overlaps": ["prov/judge-1"]}}
    html = build_report_html(
        cfg=CFG,
        records=records,
        elo={"model-a": 1100.0, "model-b": 900.0},
        report=REPORT,
        manifest=manifest,
    )
    # Rendered as a Confidence-stats caveat row (favoring master's drawer design).
    assert "family overlap" in html.lower()
    assert "provider family" in html
    assert "prov/judge-1" in html
    # empty list renders no caveat
    clean = build_report_html(
        cfg=CFG,
        records=records,
        elo={"model-a": 1100.0, "model-b": 900.0},
        report=REPORT,
        manifest=MANIFEST | {"preflight": {"family_overlaps": []}},
    )
    assert "provider family" not in clean


def test_report_path_convention(tmp_path):
    assert report_path_for(tmp_path / "battles.jsonl").name == "battles.report.html"


def test_report_cost_column_with_prices():
    records = [_record("A"), _record("B")]
    prices = {
        "prov/model-a": (1.0, 2.0),
        "prov/model-b": (1.0, 2.0),
        "prov/judge-1": (0.5, 1.0),
        "prov/judge-2": (0.5, 1.0),
    }
    html = build_report_html(
        cfg=CFG,
        records=records,
        elo={"model-a": 1050.0, "model-b": 950.0},
        report=REPORT,
        manifest=MANIFEST,
        prices=prices,
    )
    # warriors: in 2*(10+10)=40 @ $1/M + out 2*(20+25)=90 @ $2/M
    assert "Estimated total" in html and "costcard" in html
    # jury estimated at panel mean rate, marked approximate
    assert "&asymp;" in html


def test_report_no_cost_without_prices():
    html = build_report_html(
        cfg=CFG,
        records=[_record("A")],
        elo={"model-a": 1050.0, "model-b": 950.0},
        report=REPORT,
        manifest=MANIFEST,
    )
    assert "est. cost" not in html
    assert "dataset" not in html  # no dataset in manifest, no dataset line


def test_report_speed_section_from_durations():
    fast, slow = _record("A"), _record("A")
    fast.ttft_a_ms, fast.duration_a_ms = 400, 2000  # 20 out tok / 2s = 10 tok/s
    fast.ttft_b_ms, fast.duration_b_ms = 900, 5000
    slow.ttft_a_ms, slow.duration_a_ms = 400, 2500
    slow.ttft_b_ms, slow.duration_b_ms = 800, 6000
    html = build_report_html(
        cfg=CFG,
        records=[fast, slow],
        elo={"model-a": 1050.0, "model-b": 950.0},
        report=REPORT,
        manifest=MANIFEST,
    )
    assert "Speed" in html and "tok/s" in html and "ttft 0.4s" in html
    # logs that predate duration capture skip the section entirely
    html_old = build_report_html(
        cfg=CFG,
        records=[_record("A"), _record("A")],
        elo={"model-a": 1050.0, "model-b": 950.0},
        report=REPORT,
        manifest=MANIFEST,
    )
    assert "tok/s" not in html_old


def test_report_links_orq_dataset():
    manifest = MANIFEST | {
        "dataset": {
            "id": "ds_01",
            "name": "Support prompts",
            "url": "https://my.orq.ai/datasets/ds_01",
        }
    }
    html = build_report_html(
        cfg=CFG,
        records=[_record("A")],
        elo={"model-a": 1050.0, "model-b": 950.0},
        report=REPORT,
        manifest=manifest,
    )
    assert "dataset <a href='https://my.orq.ai/datasets/ds_01'>Support prompts</a>" in html


def test_report_with_custom_display_names():
    """Records store short model names; a pool with custom display names must
    still price, rank, and render (regression: KeyError / blank cost column)."""
    from orq_arena.tournament.driver import rebuild_from_log

    cfg = ArenaConfig.model_validate(
        {
            "candidates": [
                {"model_id": "prov/model-a", "name": "Alpha"},
                {"model_id": "prov/model-b", "name": "Beta"},
            ],
            "judges": ["prov/judge-1", "prov/judge-2"],
        }
    )
    records = [_record("A"), _record("B"), _record("A")]
    elo, rep = rebuild_from_log(cfg, records)
    assert set(elo) == {"Alpha", "Beta"}
    assert set(rep["verbosity"]) == {"Alpha", "Beta"}
    manifest = MANIFEST | {
        "candidates": {"Alpha": {"model": "prov/model-a"}, "Beta": {"model": "prov/model-b"}}
    }
    prices = {
        "prov/model-a": (1.0, 2.0),
        "prov/model-b": (1.0, 2.0),
        "prov/judge-1": (0.5, 1.0),
        "prov/judge-2": (0.5, 1.0),
    }
    html = build_report_html(
        cfg=cfg,
        records=records,
        elo=elo,
        report=rep,
        manifest=manifest,
        prices=prices,
    )
    assert "Alpha" in html and "Estimated total" in html
    assert ">cost</span>" in html  # per-model cost metric rendered via the alias


def test_orq_dataset_meta_offline_fallback(monkeypatch):
    import orq_ai_sdk

    from orq_arena.data.prompts import orq_dataset_meta

    def _boom(*a, **k):
        raise RuntimeError("no network in tests")

    monkeypatch.setattr(orq_ai_sdk, "Orq", _boom)
    meta = orq_dataset_meta("ds_42", api_key_env="ORQ_API_KEY")
    assert meta == {"id": "ds_42", "name": "ds_42", "url": "https://my.orq.ai/datasets/ds_42"}
