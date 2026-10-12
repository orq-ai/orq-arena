"""The single-file HTML report renders from records + report dict alone."""

from orq_arena.config import ArenaConfig
from orq_arena.data.schemas import BattleRecord
from orq_arena.report import _ROUNDS_CAP, build_report_html, report_path_for

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
    assert "model-a" in html  # verdict banner headline
    # Overlapping intervals never license a tie claim, so the page must not make
    # one (this run records no separation measurement at all).
    assert "statistically tied" not in html
    assert "STATISTICAL TIE" not in html
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
    # No separation measurement recorded, so the page makes no claim either way
    # (it used to infer "indistinguishable" from the marginal intervals here).
    assert "Top-spot separation" not in html
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


def test_length_row_descriptive_first_and_coefficient_gated():
    """The page's length claim follows the producer's identification gate.

    Identified: the count, the coefficient with its interval (unbounded side
    named, separated resamples disclosed), and the length-adj. column.
    Not identified: the count still renders, with an explicit withholding
    line, and no column.
    """
    records = [_record("A"), _record("B")]
    identified = REPORT | {
        "length_pref": {"longer_wins": 59, "rounds": 74},
        "length_coef": 18.27,
        "length_coef_ci": {"lo": 13.2, "hi": None, "separated": 61, "draws": 400},
        "elo_style_controlled": {"model-a": 1010.0, "model-b": 990.0},
    }
    html = build_report_html(
        cfg=CFG,
        records=records,
        elo={"model-a": 1050.0, "model-b": 950.0},
        report=identified,
        manifest=MANIFEST,
    )
    assert "<b>longer</b> answer (in characters) won <b>80%</b> of decisive rounds (59/74)" in html
    assert "+18.3" in html and "13.2 to unbounded" in html
    assert "61/400 resamples separated" in html
    assert "length-adj." in html

    withheld = REPORT | {"length_pref": {"longer_wins": 40, "rounds": 74}}
    html = build_report_html(
        cfg=CFG,
        records=records,
        elo={"model-a": 1050.0, "model-b": 950.0},
        report=withheld,
        manifest=MANIFEST,
    )
    assert "won <b>54%</b> of decisive rounds (40/74)" in html
    assert "not statistically identified on this run" in html
    assert "length-adj." not in html


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
    assert "Estimated total" in html and "kpi-card" in html
    # An old log carries no judge cost, so the jury is estimated at the panel
    # mean rate and marked approximate, whatever the mode.
    assert "&asymp;" in html and "&middot; estimated" in html and "&middot; measured" not in html
    assert "Mean confidence" not in html  # prompted judges carry no probabilities
    assert "Every verdict via evaluatorq&#39;s pairwise jury" in html


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
    assert "win share &middot; $" in html  # per-model cost rendered via the alias


PRICES = {
    "prov/model-a": (1.0, 2.0),
    "prov/model-b": (1.0, 2.0),
}


def _decision_vote(model: str, ab: dict, ba: dict, vote: str | None) -> dict:
    """A stored decision vote: each seat order's raw probabilities, as evaluatorq keeps them."""
    return {
        "model": model,
        "vote": vote,
        "flipped": False,
        "completed": True,
        "replacement": False,
        "explanation": f"choice={vote!r}",
        "observations": [
            {"ordering": "ab", "raw_output": {"probabilities": ab}},
            {"ordering": "ba", "raw_output": {"probabilities": ba}},
        ],
    }


def test_decisions_report_measures_jury_cost_and_shows_confidence():
    cfg = ArenaConfig.model_validate(
        {
            "candidates": [{"model_id": "prov/model-a"}, {"model_id": "prov/model-b"}],
            "judges": ["openai/judge-x", "groq/judge-x"],
            "judge_api": "decisions",
            "judge_abstain_below": 0.5,
        }
    )
    records = []
    for _ in range(2):
        rec = _record("A")
        rec.judge_votes = [
            # The "ba" ordering saw the sides swapped; un-swapped it reads A 0.70.
            _decision_vote(
                "openai/judge-x",
                {"A": 0.72, "B": 0.18, "tie": 0.10},
                {"A": 0.18, "B": 0.70, "tie": 0.12},
                "A",
            ),
            # Top option 0.45 under the 0.50 floor: an abstention, not a flip.
            _decision_vote(
                "groq/judge-x",
                {"A": 0.45, "B": 0.40, "tie": 0.15},
                {"A": 0.40, "B": 0.45, "tie": 0.15},
                None,
            ),
        ]
        rec.judge_cost_usd = 0.02
        records.append(rec)
    report = REPORT | {
        "judge_cost_usd": 0.04,
        "jury": {
            "per_judge": [
                {"model": m, "a_rate": 1.0, "b_rate": 0.0, "position_bias": 0.0, "tie_rate": 0.0}
                for m in ("openai/judge-x", "groq/judge-x")
            ]
        },
    }
    html = build_report_html(
        cfg=cfg,
        records=records,
        elo={"model-a": 1050.0, "model-b": 950.0},
        report=report,
        manifest=MANIFEST | {"judges": cfg.judges, "judge_api": "decisions"},
        prices=PRICES,
    )
    # Measured jury cost: exact figure, a plain Total card, no approximation.
    assert "$0.040" in html and "&middot; measured" in html and "Total" in html
    assert "&asymp;" not in html and "Estimated total" not in html
    assert "jury cost is what each judge call was priced at" in html
    # Confidence column, mean of the winning option over decided votes.
    assert "Mean confidence" in html and "0.71" in html
    assert "2 votes (50%) abstained because the top option fell under the 0.50 floor." in html
    # Same short name on two providers: both judges keep their own label.
    assert "openai/judge-x" in html and "groq/judge-x" in html
    assert "panel: openai/judge-x, groq/judge-x (decision models)" in html
    assert "Every verdict via the orq.ai Decisions API" in html
    # Rounds show probabilities, not the synthesized explanation.
    assert "A 71% &middot; B 18% &middot; tie 11%" in html
    assert "choice=" not in html
    assert not any(d in html for d in ("\u2014", "&mdash;", "&#8212;", "&#x2014;"))


def test_swap_off_says_position_bias_was_not_measured():
    cfg = CFG.model_copy(update={"judge_swap": False})
    html = build_report_html(
        cfg=cfg,
        records=[_record("A")],
        elo={"model-a": 1050.0, "model-b": 950.0},
        report=REPORT,
        manifest=MANIFEST,
    )
    assert "n/a (swap off)" in html
    assert "single seat order, so position bias (the flip rate) was not measured" in html


def test_rounds_section_renders_chips_and_caps():
    records = [_record("A") for _ in range(_ROUNDS_CAP + 5)]
    html = build_report_html(
        cfg=CFG,
        records=records,
        elo={"model-a": 1050.0, "model-b": 950.0},
        report=REPORT,
        manifest=MANIFEST,
    )
    assert "<h2>Rounds</h2>" in html
    assert html.count("<details class='pw-cmp'>") == _ROUNDS_CAP
    assert "pw-chip pw-chip--a" in html
    assert f"Showing the first {_ROUNDS_CAP} of {_ROUNDS_CAP + 5} judged rounds" in html
    assert "battle browser" in html


def test_report_is_built_on_the_evaluatorq_skin():
    from evaluatorq.common.reports import load_css

    html = build_report_html(
        cfg=CFG,
        records=[_record("A")],
        elo={"model-a": 1050.0, "model-b": 950.0},
        report=REPORT,
        manifest=MANIFEST,
    )
    assert load_css().split(".kpi-band", 1)[1][:200] in html  # the shared rules ship verbatim
    assert "ES Klarheit Kurrent" in html and 'class="hero"' in html
    for token in ("@import", "http://"):
        assert token not in html  # self-contained: no font fetch, no namespaced logo


def test_orq_dataset_meta_offline_fallback(monkeypatch):
    import orq_ai_sdk

    from orq_arena.data.prompts import orq_dataset_meta

    def _boom(*a, **k):
        raise RuntimeError("no network in tests")

    monkeypatch.setattr(orq_ai_sdk, "Orq", _boom)
    meta = orq_dataset_meta("ds_42")
    assert meta == {"id": "ds_42", "name": "ds_42", "url": "https://my.orq.ai/datasets/ds_42"}
