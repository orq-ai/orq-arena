"""jury-compare reads saved rejudge reports and tabulates the candidates."""
import json

from orq_arena.rejudge import compare_reports


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
