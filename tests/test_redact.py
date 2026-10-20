"""A credential an agent prints must never reach a step, the log, the dossier or a report."""

from __future__ import annotations

import io
import json

import pytest

from orq_arena import redact
from orq_arena.data.log import BattleLog
from orq_arena.data.schemas import BattleRecord
from orq_arena.harness.dossier import render
from orq_arena.harness.parsers import Step
from orq_arena.harness.trial import Trial, load_trial

KEY = "sk-orq-0123456789abcdefghijklmnopqrstuvwxyz"


@pytest.fixture(autouse=True)
def _key():
    redact.clear()
    redact.register(KEY)
    yield
    redact.clear()


def test_the_value_and_its_url_encoded_form_are_masked_and_short_values_are_left():
    redact.register("a b/c+d=eeeeeeeeee", "short")
    out = redact.redact(f"k={KEY} q=a%20b%2Fc%2Bd%3Deeeeeeeeee s=short")
    assert KEY not in out and "a%20b" not in out
    assert out.count(redact.MASK) == 2 and "s=short" in out


def test_a_step_masks_its_title_body_and_meta():
    s = Step("observation", f"export KEY={KEY}", f"line {KEY}", {"note": KEY, "n": 3})
    assert KEY not in json.dumps(s.as_dict())
    assert s.meta["n"] == 3


def test_the_battle_log_never_writes_the_key(tmp_path):
    log = BattleLog(tmp_path / "b.jsonl")
    log.append(
        BattleRecord(
            prompt_hash="h", prompt_text="t", model_a="a", model_b="b",
            response_a=f"## Trajectory\n- [command] env | grep {KEY}", error=f"harbor: {KEY}",
        )
    )  # fmt: skip
    text = (tmp_path / "b.jsonl").read_text()
    assert KEY not in text and redact.MASK in text


def test_the_dossier_the_jury_reads_is_masked():
    t = Trial(agent="pi", passed=True, reward=1.0, test_tail=f"FAILED: token {KEY}")
    t.steps = [Step("command", "ls")]
    assert KEY not in render(t)


def test_a_trial_dir_is_scrubbed_in_place_including_nested_logs(tmp_path):
    d = tmp_path / "t__abc"
    (d / "agent" / "sessions").mkdir(parents=True)
    (d / "agent" / "pi.txt").write_text(f'{{"stdout": "OPENAI_API_KEY={KEY}"}}\n')
    (d / "agent" / "sessions" / "s.jsonl").write_text(f"x {KEY} y")
    (d / "agent" / "blob.bin").write_bytes(b"\x00\x01" + KEY.encode())
    (d / "result.json").write_text("{}")
    assert redact.scrub_tree(d) == 2
    assert KEY not in (d / "agent" / "pi.txt").read_text()
    assert KEY not in (d / "agent" / "sessions" / "s.jsonl").read_text()
    assert (d / "agent" / "blob.bin").read_bytes().endswith(KEY.encode())  # binary left alone
    assert redact.scrub_tree(d) == 0  # idempotent


def test_steps_loaded_from_a_native_log_are_masked_in_steps_json(tmp_path):
    d = tmp_path / "t__abc"
    (d / "agent").mkdir(parents=True)
    (d / "agent" / "claude-code.txt").write_text(
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": f"echo {KEY}"}}]}}) + "\n"
    )  # fmt: skip
    (d / "result.json").write_text(json.dumps({"verifier_result": {"rewards": {"reward": 1.0}}}))
    load_trial(d, "claude-code")
    assert KEY not in (d / "steps.json").read_text()


def test_the_streams_the_process_prints_to_are_masked():
    inner = io.StringIO()
    stream = redact._RedactingStream(inner)
    stream.write(f"auth {KEY}\n")
    assert KEY not in inner.getvalue() and redact.MASK in inner.getvalue()
    assert stream.getvalue() == inner.getvalue()  # everything else is the wrapped stream


def test_the_report_and_the_rounds_page_are_masked(tmp_path, monkeypatch):
    from orq_arena import report
    from orq_arena.config import ArenaConfig

    cfg = ArenaConfig.model_validate(
        {"candidates": [{"model_id": "p/a"}, {"model_id": "p/b"}], "judges": ["p/j"]}
    )
    monkeypatch.setattr(report, "build_report_html", lambda **_: f"<pre>{KEY}</pre>")
    rec = BattleRecord(
        prompt_hash="h", prompt_text=f"q {KEY}", model_a="a", model_b="b",
        response_a=f"leak {KEY}", response_b="ok", error=f"harbor: {KEY}",
    )  # fmt: skip
    out = report.write_report(
        cfg=cfg, records=[rec], elo={}, report={}, manifest={}, log_path=tmp_path / "b.jsonl"
    )  # fmt: skip
    assert KEY not in out.read_text()
    rounds = (tmp_path / "b.rounds.html").read_text()
    assert KEY not in rounds and redact.MASK in rounds


def test_the_runner_masks_a_failure_tail_and_registers_the_key_it_hands_agents(
    tmp_path, monkeypatch
):
    from orq_arena.harness.runner import _log_tail

    log = tmp_path / "x.harbor.log"
    log.write_text(f"Traceback ... env: ORQ_API_KEY={KEY}")
    assert KEY not in _log_tail(log)
