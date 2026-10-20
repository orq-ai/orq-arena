"""The single-file HTML report renders from records + report dict alone."""

from orq_arena.config import ArenaConfig
from orq_arena.data.schemas import BattleRecord
from orq_arena.report import build_report_html, report_path_for, write_report
from orq_arena.rounds_page import build_rounds_html, rounds_data, rounds_path_for

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
    # Confidence column: mean of the leading option over every vote, abstained ones too.
    assert "Mean confidence" in html and "0.71" in html and "0.45" in html
    assert "2 votes (50%) abstained because the top option fell under the 0.50 floor." in html
    # Same short name on two providers: both judges keep their own label.
    assert "openai/judge-x" in html and "groq/judge-x" in html
    assert "panel: openai/judge-x, groq/judge-x (decision models)" in html
    assert "Every verdict via the orq.ai Decisions API" in html
    # Rounds (on their own page) show probabilities, not the synthesized explanation.
    data = rounds_data(records, {}, {"openai/judge-x": "openai/judge-x"}, 0.5)
    assert data["rounds"][0]["votes"][0]["why"] == "A 71% · B 18% · tie 11%"
    assert data["rounds"][0]["votes"][1]["floor"] is True
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


def test_the_report_links_to_the_rounds_page_and_never_embeds_a_round():
    records = [_record("A") for _ in range(5)]
    kw = dict(cfg=CFG, records=records, elo={"model-a": 1050.0, "model-b": 950.0}, report=REPORT, manifest=MANIFEST)  # fmt: skip
    html = build_report_html(**kw, rounds_href="battles.rounds.html")
    assert "<h2>Rounds</h2>" in html and "href='battles.rounds.html'" in html
    assert "pw-cmp" not in html.replace(".pw-cmp", "")  # no round markup, only the stylesheet
    assert "<details class='pw-cmp'" not in html and "pw-vote__why'>" not in html
    assert "<h2>Rounds</h2>" not in build_report_html(**kw)  # no page to link to, no section


def test_the_rounds_page_path_sits_next_to_the_report():
    assert rounds_path_for("x/battles.report.html").name == "battles.rounds.html"
    assert rounds_path_for("x/custom.html").name == "custom.rounds.html"


def test_write_report_writes_both_pages_and_the_report_only_links(tmp_path):
    records = [_record("A") for _ in range(3)]
    out = write_report(
        cfg=CFG, records=records, elo={"model-a": 1050.0, "model-b": 950.0}, report=REPORT,
        manifest=MANIFEST, log_path=tmp_path / "battles.jsonl",
    )  # fmt: skip
    page = tmp_path / "battles.rounds.html"
    assert out.name == "battles.report.html" and page.exists()
    assert "battles.rounds.html" in out.read_text()
    html = page.read_text()
    for needle in (
        "f-q",
        "f-who",
        "f-vs",
        "f-task",
        "f-win",
        "f-tests",
        "f-match",
        "f-panel",
        "f-sort",
    ):
        assert f'id="{needle}"' in html  # the filters
    assert "battles.report.html" in html  # the way back
    assert '<option value="">log order</option>' in html  # the default order is selectable
    assert html.count("<select") <= 9 and 'id="pills"' in html  # a few controls, outcome as pills


def test_the_rounds_page_holds_every_round_with_no_cap_at_200():
    records = [_record("A") for _ in range(250)]
    data = rounds_data(records, {}, {"prov/judge-1": "judge-1"}, None)
    assert len(data["rounds"]) == 250 and data["capped"] is False
    r = data["rounds"][0]
    assert (r["a"], r["b"], r["v"], r["votes"][0]["judge"]) == (
        "model-a",
        "model-b",
        "A",
        "judge-1",
    )
    assert r["ra"] == "ra" and r["rb"] == "rb" and r["ta"] is None


def test_the_rounds_page_cannot_be_broken_out_of_by_a_model_answer():
    rec = _record("A")
    rec.response_a = "</script><script>alert(1)</script> <!-- & \u2028"
    html = build_rounds_html(
        records=[rec], alias={}, labels={}, floor=None, title="t", report_href="r.html"
    )
    assert (
        "</script><script>alert(1)" not in html
        and "<!--" not in html.split('id="data"')[1].split("</script>")[0]
    )
    assert "\\u003c/script\\u003e" in html or "\u003c/script\u003e" in html


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


# ---------------------------------------------------------------- harness mode


def _trial_dir(root, name, *, patch="", steps=None, tests=""):
    d = root / name
    (d / "verifier").mkdir(parents=True)
    if patch:
        (d / "diff.patch").write_text(patch, encoding="utf-8")
    if steps is not None:
        import json

        (d / "steps.json").write_text(json.dumps(steps), encoding="utf-8")
    if tests:
        (d / "verifier" / "test-stdout.txt").write_text(tests, encoding="utf-8")
    return str(d)


def _solution(passed, trial_dir, **over):
    return {
        "passed": passed,
        "reward": 1.0 if passed else 0.0,
        "cost_usd": 0.42,
        "tokens_in": 100,
        "tokens_out": 50,
        "duration_ms": 680_000,
        "steps": 23,
        "commands": 14,
        "edits": 6,
        "diff_stat": "+14 -3, 2 files",
        "diff_note": "",
        "tests_edited": False,
        "exit_reason": "finished",
        "trial_dir": trial_dir,
    } | over


def _harness_setup(tmp_path):
    cfg = ArenaConfig.model_validate(
        {
            "candidates": [
                {"kind": "harness", "agent": "pi", "model_id": "p/m", "name": "pi"},
                {"kind": "harness", "agent": "codex", "model_id": "openai/m", "name": "codex"},
            ],
            "judges": ["prov/judge-1"],
        }
    )
    a_dir = _trial_dir(
        tmp_path,
        "a",
        patch="--- a/tests/t.py\n+++ b/tests/t.py\n@@\n-<script>alert(1)</script>\n+ok\n",
        steps=[{"kind": "command", "title": "$ pytest <b>", "body": "3 passed", "meta": {}}],
        tests="FAILED test_history_intact",
    )
    b_dir = _trial_dir(tmp_path, "b", patch="--- a/x\n+++ b/x\n@@\n-1\n+2\n")
    rec = BattleRecord(
        prompt_hash="h1",
        prompt_text="fix the repo",
        prompt_category="easy",
        model_a="pi",
        model_b="codex",
        model_a_id="pi:p/m",
        model_b_id="codex:p/m",
        response_a="## Hidden tests: FAILED",
        response_b="## Hidden tests: PASSED",
        majority_verdict="B",
        winner="codex",
        judge_votes=[
            {
                "model": "verifier",
                "vote": "B",
                "completed": True,
                "flipped": False,
                "replacement": False,
                "explanation": "hidden tests: A failed, B passed",
                "observations": [],
            }
        ],
        solution_a=_solution(False, a_dir, tests_edited=True),
        solution_b=_solution(True, b_dir, exit_reason="max_turns", cost_usd=0.18),
        judge_cost_usd=0.0,
    )
    report = REPORT | {
        "by_model_names": {"pi:p/m": "pi", "codex:p/m": "codex"},
        "elo_ci": {"pi": (900.0, 1100.0), "codex": (950.0, 1150.0)},
        "win_grid": {"pi": {"codex": 0.0}, "codex": {"pi": 1.0}},
        "harness": {
            "pi": {
                "trials": 1,
                "passed": 0,
                "verified": 1,
                "pass_rate": 0.0,
                "mean_cost_usd": 0.42,
                "mean_duration_s": 680.0,
                "tests_edited": 1,
            },
            "codex": {
                "trials": 1,
                "passed": 1,
                "verified": 1,
                "pass_rate": 1.0,
                "mean_cost_usd": 0.18,
                "mean_duration_s": 240.0,
                "tests_edited": 0,
            },
        },
        "gate_rounds": 1,
    }
    manifest = MANIFEST | {"harness": {"harbor_version": "0.24.0", "tasks": ["/t/fix-git"]}}
    return cfg, [rec], report, manifest


def test_harness_report_renders_the_ladder_and_leaves_the_rounds_to_their_page(tmp_path):
    cfg, records, report, manifest = _harness_setup(tmp_path)
    html = build_report_html(
        cfg=cfg,
        records=records,
        elo={"pi": 950.0, "codex": 1050.0},
        report=report,
        manifest=manifest,
        rounds_href="battles.rounds.html",
    )
    # the ladder swaps the length column for the three harness columns
    assert "pass rate" in html and "$/task" in html and "min/task" in html
    assert "avg length" not in html and "length-adj." not in html
    assert "0/1" in html and "1/1" in html
    assert "Agent trials" in html and "observed" in html
    assert "harbor <code>0.24.0</code> &middot; 1 tasks" in html
    assert "Harness</th>" in html
    # no round, diff or trajectory is embedded: the rounds live on their page
    assert "alert(1)" not in html and "$ pytest" not in html and "hidden tests PASSED" not in html
    assert not any(d in html for d in ("\u2014", "&mdash;", "&#8212;", "&#x2014;"))


def test_harness_rounds_page_carries_badges_diff_trajectory_and_gate(tmp_path):
    cfg, records, report, manifest = _harness_setup(tmp_path)
    data = rounds_data(records, {"pi:p/m": "pi", "codex:p/m": "codex"}, {}, None)
    (r,) = data["rounds"]
    assert r["gate"] is True and r["v"] == "B" and (r["a"], r["b"]) == ("pi", "codex")
    ta, tb = data["trials"][r["ta"]], data["trials"][r["tb"]]
    assert (ta["passed"], tb["passed"]) == (False, True)
    assert (ta["steps"], ta["cmds"], ta["edits"], ta["ms"]) == (23, 14, 6, 680_000)
    assert ta["tests_edited"] is True and tb["exit"] == "max_turns" and tb["cost"] == 0.18
    assert "<script>alert(1)</script>" in ta["diff"] and "$ pytest <b>" in ta["traj"]
    assert ta["n_traj"] == 1 and "FAILED test_history_intact" in ta["tests"]
    html = build_rounds_html(
        records=records, alias={"pi:p/m": "pi", "codex:p/m": "codex"}, labels={}, floor=None,
        title="t", report_href="r.html",
    )  # fmt: skip
    # untrusted diff and trajectory text is data, never markup
    assert "<script>alert(1)</script>" not in html
    assert not any(d in html for d in ("&mdash;", "&#8212;", "&#x2014;"))


def test_harness_rounds_survive_missing_trial_files(tmp_path):
    cfg, records, report, manifest = _harness_setup(tmp_path)
    for rec in records:
        rec.solution_a["trial_dir"] = str(tmp_path / "gone")
        rec.solution_b["trial_dir"] = ""
    data = rounds_data(records, {}, {}, None)
    (r,) = data["rounds"]
    ta, tb = data["trials"][r["ta"]], data["trials"][r["tb"]]
    assert ta["passed"] is False and ta["diff"] == "" and ta["traj"] == "" and tb["tests"] == ""


def test_harness_cost_counts_a_replayed_trial_once(tmp_path):
    from orq_arena.report import _harness_costs

    cfg, records, _report, _manifest = _harness_setup(tmp_path)
    again = records[0].model_copy(deep=True)  # same task, same two harnesses: a replay
    usd, trials, unknown = _harness_costs([*records, again], {"pi:p/m": "pi", "codex:p/m": "codex"})
    assert (trials, unknown) == (2, 0)
    assert usd == {"pi": 0.42, "codex": 0.18}


def test_the_ladder_and_the_spend_card_say_when_a_cost_is_estimated(tmp_path):
    from orq_arena.report import _cost_provenance

    cfg, records, report, manifest = _harness_setup(tmp_path)
    for rec in records:
        rec.solution_a["cost_estimated"] = True  # pi: tokens priced at the catalog rate
    report["harness"]["pi"] |= {"estimated": 1, "unverified": 0}
    report["harness"]["codex"] |= {"estimated": 0, "unverified": 3}
    html = build_report_html(
        cfg=cfg, records=records, elo={"pi": 950.0, "codex": 1050.0}, report=report, manifest=manifest
    )  # fmt: skip
    assert "~$0.42" in html and "1 of 1 trials priced from tokens" in html
    assert "(3 void)" in html  # a void is shown beside the pass rate
    assert (
        "1 observed, 1 estimated from tokens" in html and "2 trials &middot; observed" not in html
    )
    assert _cost_provenance(4, 0) == "observed"
    assert _cost_provenance(4, 4) == "estimated from tokens"
