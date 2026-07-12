"""CLI wiring for annotate + anchor."""

import json

from click.testing import CliRunner

from orq_arena.anchor import record_key
from orq_arena.cli import cli
from tests.test_anchor_items import RECORDS


def _log(tmp_path):
    p = tmp_path / "battles.jsonl"
    p.write_text("\n".join(r.model_dump_json() for r in RECORDS) + "\n")
    return p


def test_annotate_writes_blind_page(tmp_path):
    log = _log(tmp_path)
    out = tmp_path / "annotate.html"
    r = CliRunner().invoke(cli, ["annotate", str(log), "--out", str(out), "--sample", "3"])
    assert r.exit_code == 0, r.output
    page = out.read_text()
    assert "model-one" not in page and page.count('class="resp') == 2
    assert "3 rounds" in r.output


def test_anchor_prints_kappa_table(tmp_path):
    log = _log(tmp_path)
    votes = tmp_path / "votes.json"
    votes.write_text(json.dumps({
        "schema": 1, "seed": 42, "source": "battles.jsonl", "annotator": "h1",
        "votes": {record_key(r): "A" for r in RECORDS},
    }))
    r = CliRunner().invoke(cli, ["anchor", str(log), str(votes)])
    assert r.exit_code == 0, r.output
    assert "h1" in r.output and "κ" in r.output


def test_annotate_exclude_builds_resume_page(tmp_path):
    log = _log(tmp_path)
    votes = tmp_path / "votes.json"
    votes.write_text(json.dumps({
        "schema": 1, "seed": 42, "source": "battles.jsonl", "annotator": "h1",
        "votes": {record_key(r): "A" for r in RECORDS[:4]},
    }))
    out = tmp_path / "resume.html"
    r = CliRunner().invoke(
        cli, ["annotate", str(log), "--out", str(out), "--exclude", str(votes)])
    assert r.exit_code == 0, r.output
    assert "2 rounds" in r.output and "4 already-voted excluded" in r.output
    for rec in RECORDS[:4]:
        assert rec.prompt_text not in out.read_text()
