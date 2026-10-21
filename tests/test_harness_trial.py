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


def _write(d: Path, **over) -> Path:
    base = {
        "agent_result": {"n_input_tokens": 10, "n_output_tokens": 5, "cost_usd": 0.1},
        "verifier_result": {"rewards": {"reward": 0.0}},
        "exception_info": None,
    }
    d.mkdir(parents=True, exist_ok=True)
    (d / "result.json").write_text(json.dumps({**base, **over}))
    return d


def test_a_timeout_word_in_a_traceback_is_not_an_agent_timeout(tmp_path):
    # Every asyncio cancellation traceback mentions a timeout frame.
    exc = {
        "exception_type": "CancelledError",
        "exception_message": "",
        "exception_traceback": "File selectors.py, in select(timeout)\n    timeout_sec=timeout_sec",
    }
    d = _write(tmp_path / "t", exception_info=exc, verifier_result=None, agent_result=None)
    t = load_trial(d, "pi")
    assert t.error and t.passed is None and t.exit_reason == "error"


def test_setup_and_verifier_timeouts_void_the_round_but_an_agent_timeout_is_a_fail(tmp_path):
    for kind in ("EnvironmentStartTimeoutError", "AgentSetupTimeoutError", "VerifierTimeoutError"):
        exc = {"exception_type": kind, "exception_message": "timed out"}
        d = _write(tmp_path / kind, exception_info=exc, verifier_result=None)
        assert load_trial(d, "pi").error, kind
    exc = {"exception_type": "AgentTimeoutError", "exception_message": "timed out"}
    d = _write(tmp_path / "agent", exception_info=exc, verifier_result=None)
    t = load_trial(d, "pi")
    assert t.error is None and t.passed is False and t.exit_reason == "timeout"


def test_an_agent_that_never_got_a_model_answer_is_not_a_loss(tmp_path):
    d = _write(tmp_path / "t", agent_result={"n_input_tokens": 0, "n_output_tokens": 0})
    t = load_trial(d, "codex")
    assert t.error and "no model call" in t.error


def test_a_model_refusal_is_a_loss_not_a_void(tmp_path):
    # claude-code reports a refusal with zero tokens, which must not read as a router failure.
    exc = {"exception_type": "AgentSafetyRefusalError", "exception_message": "refused"}
    for name, verifier in (("ran", {"rewards": {"reward": 0.0}}), ("skipped", None)):
        d = _write(
            tmp_path / name,
            exception_info=exc,
            verifier_result=verifier,
            agent_result={"n_input_tokens": 0, "n_output_tokens": 0, "cost_usd": 0.06},
        )
        t = load_trial(d, "claude-code")
        assert t.error is None and t.passed is False and t.exit_reason == "refused", name


def test_such_a_trial_is_not_cached_on_disk(tmp_path):
    from orq_arena.harness.runner import cached_trial_dir

    good = tmp_path / "job-good" / "t__a"
    _write(good, verifier_result={"rewards": {"reward": 1.0}})
    (good / "config.json").write_text("{}")
    bad = tmp_path / "job-bad" / "t__a"
    _write(bad, agent_result={"n_input_tokens": 0}, verifier_result={"rewards": {"reward": 0.0}})
    (bad / "config.json").write_text("{}")
    assert cached_trial_dir(tmp_path, "job-good") is not None
    assert cached_trial_dir(tmp_path, "job-bad") is None
