"""Run: .venv/bin/python -m pytest talks/2026-meetup -q"""

import json
from pathlib import Path

from audience_prompts import build

SEED = Path(__file__).with_name("seed.jsonl")


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def write_csv(tmp_path, text):
    path = tmp_path / "form.csv"
    path.write_text(text, encoding="utf-8")
    return path


def test_seed_only_when_no_csv(tmp_path):
    out = tmp_path / "prompts.jsonl"
    assert build(SEED, None, out) == 10
    assert len(rows(out)) == 10


def test_prompt_column_found_by_substring(tmp_path):
    csv_path = write_csv(
        tmp_path,
        "Timestamp,Your prompt,Email\n2026-10-19,Name three uses of a decision model,me@x.io\n",
    )
    out = tmp_path / "prompts.jsonl"
    assert build(SEED, csv_path, out) == 11
    assert rows(out)[-1] == {
        "prompt": "Name three uses of a decision model",
        "category": "audience",
    }
    assert "me@x.io" not in out.read_text()
    assert "2026-10-19" not in out.read_text()


def test_long_and_blank_rows_dropped(tmp_path):
    csv_path = write_csv(
        tmp_path,
        'Prompt\n"' + "x" * 601 + '"\n""\n"line one\nline two\tend"\n"line one line two end"\n',
    )
    out = tmp_path / "prompts.jsonl"
    assert build(SEED, csv_path, out) == 11
    assert rows(out)[-1]["prompt"] == "line one line two end"


def test_header_only_csv_yields_seed(tmp_path):
    out = tmp_path / "prompts.jsonl"
    assert build(SEED, write_csv(tmp_path, "Timestamp,prompt\n"), out) == 10


def test_every_output_line_is_json_with_category(tmp_path):
    csv_path = write_csv(tmp_path, 'PROMPT\n"say ""hi"", then {}"\nsecond one\n')
    out = tmp_path / "prompts.jsonl"
    build(SEED, csv_path, out)
    parsed = rows(out)
    assert len(parsed) == 12
    assert all(r["prompt"] and r["category"] for r in parsed)
    assert [r["category"] for r in parsed[10:]] == ["audience", "audience"]
    assert parsed[10]["prompt"] == 'say "hi", then {}'
