"""Reading a real Harbor trial directory back."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from orq_arena.harness.trial import load_trial

FIXTURES = Path(__file__).parent / "fixtures" / "harbor"


def _trial(tmp_path: Path, result: str, log: str, agent: str) -> Path:
    d = tmp_path / "fix-git__abc1234"
    (d / "agent").mkdir(parents=True)
    (d / "verifier").mkdir()
    shutil.copy(FIXTURES / result, d / "result.json")
    shutil.copy(FIXTURES / log, d / "agent" / f"{agent}.txt")
    shutil.copy(FIXTURES / "test-stdout.txt", d / "verifier" / "test-stdout.txt")
    return d


def test_a_passing_claude_trial(tmp_path):
    t = load_trial(_trial(tmp_path, "result.json", "claude-code.txt", "claude-code"), "claude-code")
    assert t.passed is True and t.reward == 1.0 and t.error is None
    assert t.cost_usd is not None and t.tokens_in > 0 and t.duration_ms > 0
    assert t.exit_reason == "finished" and t.edits >= 1 and t.test_tail
    assert (tmp_path / "fix-git__abc1234" / "steps.json").exists()


def test_a_pi_trial_reports_no_cost(tmp_path):
    t = load_trial(_trial(tmp_path, "result-pi.json", "pi.txt", "pi"), "pi")
    assert t.passed is True and t.cost_usd is None


def test_a_cancelled_trial_is_an_error_not_a_loss(tmp_path):
    t = load_trial(_trial(tmp_path, "result-cancelled.json", "codex.txt", "codex"), "codex")
    assert t.passed is None and t.error and "before the verifier" in t.error


def test_an_agent_timeout_without_a_verdict_counts_as_a_fail(tmp_path):
    d = _trial(tmp_path, "result.json", "claude-code.txt", "claude-code")
    res = json.loads((d / "result.json").read_text())
    res["verifier_result"] = None
    res["exception_info"] = {"exception_type": "AgentTimeoutError", "exception_message": "timeout"}
    (d / "result.json").write_text(json.dumps(res))
    t = load_trial(d, "claude-code")
    assert t.exit_reason == "timeout" and t.passed is False and t.error is None


def test_a_missing_result_is_an_error(tmp_path):
    (tmp_path / "t").mkdir()
    assert load_trial(tmp_path / "t", "pi").error
