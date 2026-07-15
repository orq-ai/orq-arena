"""jury-compare reads saved rejudge reports and tabulates the candidates."""
import json

from orq_arena.rejudge import compare_reports, panel_excluding_contestants


def test_panel_excludes_contestants_by_full_id_like_live():
    # Contestant "command-r" resolves to cohere/command-r; a judge with the
    # same short name from a different provider must NOT be excluded (matches
    # the live run, which compares full model ids).
    short_to_full = {"command-r": "cohere/command-r", "gpt-x": "openai/gpt-x"}
    judges = ["openai/command-r", "mistral/small"]
    panel = panel_excluding_contestants(
        judges, frozenset({"command-r", "gpt-x"}), short_to_full
    )
    assert panel == ["openai/command-r", "mistral/small"]


def test_panel_excludes_matching_full_id():
    short_to_full = {"command-r": "cohere/command-r"}
    panel = panel_excluding_contestants(
        ["cohere/command-r", "mistral/small"], frozenset({"command-r", "x"}), short_to_full
    )
    assert panel == ["mistral/small"]


def test_panel_unresolved_contestant_falls_back_to_short_name():
    # Contestant not in the config: can't know its provider, so exclude on
    # short name to stay safe.
    panel = panel_excluding_contestants(
        ["openai/command-r", "mistral/small"], frozenset({"command-r"}), {}
    )
    assert panel == ["mistral/small"]


def _write(tmp_path, name, spearman, flip):
    p = tmp_path / name
    p.write_text(json.dumps({
        "total": 140, "changed_verdicts": 36, "spearman": spearman,
        "old_ranking": ["a", "b"], "new_ranking": ["b", "a"],
        "jury": {
            "comparisons": 140, "a_win_rate": 0.7, "b_win_rate": 0.3,
            "tie_rate": 0.01, "inconclusive_rate": 0.5, "mean_agreement": 0.92,
            "per_judge": [
                {"model": "prov/j1", "a_rate": 0.7, "b_rate": 0.3,
                 "position_bias": flip, "tie_rate": 0.01},
            ],
        },
    }))
    return p


def test_compare_reports_rows(tmp_path):
    a = _write(tmp_path, "a.json", 0.83, 0.34)
    b = _write(tmp_path, "b.json", 0.50, 0.25)
    rows = compare_reports([a, b])
    assert [r["spearman"] for r in rows] == [0.83, 0.50]
    assert rows[0]["worst_flip_judge"] == "j1"
    assert rows[0]["inconclusive"] == 0.5
    assert rows[1]["panel"] == "j1"
