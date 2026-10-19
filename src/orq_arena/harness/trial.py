"""One finished Harbor trial, read back from its directory.

Harbor writes ``result.json`` (verifier reward, cost, timings, exception),
``agent/<agent>.txt`` (the agent's native structured log), ``verifier/`` and,
with ``--artifact /app``, ``artifacts/app``. This module turns that into a
``Trial``: what the judges and the report need, and nothing Harbor-specific.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .parsers import Step, parse_line

STEPS_FILE = "steps.json"
_TEST_TAIL_LINES = 40


@dataclass
class Trial:
    agent: str
    dir: Path | None = None
    passed: bool | None = None  # None: the verifier did not run
    reward: float | None = None
    test_tail: str = ""
    steps: list[Step] = field(default_factory=list)
    cost_usd: float | None = None
    # True when the agent reported no cost and it was priced from tokens (pi).
    cost_estimated: bool = False
    tokens_in: int = 0
    tokens_out: int = 0
    duration_ms: int = 0
    exit_reason: str = "finished"  # finished | max_turns | timeout | error
    # Set when the trial never produced a judgeable result (Harbor failed, the
    # agent could not start, the router refused it). The round is voided.
    error: str | None = None
    diff: str = ""
    diff_stat: str = ""
    diff_note: str = ""  # why there is no diff ("diff unavailable: ...")
    tests_edited: bool = False

    @property
    def commands(self) -> int:
        return sum(1 for s in self.steps if s.kind in ("command", "test"))

    @property
    def edits(self) -> int:
        return sum(1 for s in self.steps if s.kind == "edit")

    @property
    def n_steps(self) -> int:
        return sum(1 for s in self.steps if s.kind not in ("observation", "log", "done"))

    def solution_dict(self) -> dict[str, Any]:
        """The compact form stored on the battle record."""
        return {
            "passed": self.passed,
            "reward": self.reward,
            "cost_usd": self.cost_usd,
            "cost_estimated": self.cost_estimated,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "duration_ms": self.duration_ms,
            "steps": self.n_steps,
            "commands": self.commands,
            "edits": self.edits,
            "diff_stat": self.diff_stat,
            "diff_note": self.diff_note,
            "tests_edited": self.tests_edited,
            "exit_reason": self.exit_reason,
            "trial_dir": str(self.dir) if self.dir else "",
        }


def find_trial_dir(job_dir: Path) -> Path | None:
    """The trial directory inside a Harbor job directory (we run one trial per job)."""
    if not job_dir.is_dir():
        return None
    subs = [p for p in job_dir.iterdir() if p.is_dir() and (p / "config.json").exists()]
    if not subs:
        subs = [p for p in job_dir.iterdir() if p.is_dir() and (p / "agent").is_dir()]
    return max(subs, key=lambda p: p.stat().st_mtime) if subs else None


def native_log(trial_dir: Path, agent: str) -> Path | None:
    """The agent's native log: ``agent/<agent>.txt``, else the newest ``agent/*.txt``."""
    agent_dir = trial_dir / "agent"
    named = agent_dir / f"{agent}.txt"
    if named.exists():
        return named
    candidates = sorted(agent_dir.glob("*.txt"), key=lambda p: p.stat().st_mtime)
    return candidates[-1] if candidates else None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _iso_ms(start: Any, end: Any) -> int:
    try:
        a = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
    except ValueError:
        return 0
    return max(0, int((b - a).total_seconds() * 1000))


def _duration_ms(result: dict[str, Any]) -> int:
    """Agent wall time: its own phase when Harbor records one, else the whole trial."""
    for key in ("agent_execution", "agent"):
        phase = result.get(key)
        if isinstance(phase, dict) and phase.get("started_at") and phase.get("finished_at"):
            return _iso_ms(phase["started_at"], phase["finished_at"])
    return _iso_ms(result.get("started_at"), result.get("finished_at"))


def _reward(result: dict[str, Any], trial_dir: Path) -> float | None:
    rewards = (result.get("verifier_result") or {}).get("rewards")
    if isinstance(rewards, dict) and rewards:
        value = rewards.get("reward", next(iter(rewards.values())))
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    txt = trial_dir / "verifier" / "reward.txt"
    if txt.exists():
        try:
            return float(txt.read_text(encoding="utf-8").strip())
        except ValueError:
            return None
    js = _read_json(trial_dir / "verifier" / "reward.json")
    if js:
        try:
            return float(js.get("reward", next(iter(js.values()))))
        except (TypeError, ValueError, StopIteration):
            return None
    return None


def _steps_from_log(path: Path | None, agent: str) -> list[Step]:
    if path is None:
        return []
    steps: list[Step] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        steps.extend(parse_line(agent, line))
    return steps


def load_steps(trial_dir: Path, agent: str) -> list[Step]:
    """The trial's steps: the stored ``steps.json``, else parsed from the native log."""
    stored = trial_dir / STEPS_FILE
    if stored.exists():
        try:
            rows = json.loads(stored.read_text(encoding="utf-8"))
            return [
                Step(r["kind"], r["title"], r.get("body", ""), r.get("meta") or {}) for r in rows
            ]
        except (OSError, ValueError, KeyError):
            pass
    return _steps_from_log(native_log(trial_dir, agent), agent)


def load_trial(trial_dir: Path, agent: str) -> Trial:
    """Read a finished trial. A trial with no ``result.json`` carries an error."""
    result = _read_json(trial_dir / "result.json")
    if not result:
        return Trial(agent=agent, dir=trial_dir, error="no result.json in the trial directory")

    steps = load_steps(trial_dir, agent)
    stored = trial_dir / STEPS_FILE
    if not stored.exists():
        stored.write_text(json.dumps([s.as_dict() for s in steps]), encoding="utf-8")

    agent_result = result.get("agent_result") or {}
    exception = result.get("exception_info")
    reward = _reward(result, trial_dir)
    done = next((s for s in reversed(steps) if s.kind == "done"), None)

    cost = agent_result.get("cost_usd")
    if cost is None and done is not None:
        cost = done.meta.get("cost_usd")

    exit_reason = str(done.meta.get("exit", "finished")) if done else "finished"
    error = None
    if exception:
        text = json.dumps(exception, default=str) if not isinstance(exception, str) else exception
        if "timeout" in text.lower():
            exit_reason = "timeout"
        else:
            exit_reason = "error"
            if reward is None:
                error = f"trial failed before the verifier ran: {text[:300]}"

    if exit_reason == "timeout" and reward is None:
        reward = 0.0  # out of time before the tests could pass is a fail, not "not run"

    tests = trial_dir / "verifier" / "test-stdout.txt"
    tail = ""
    if tests.exists():
        tail = "\n".join(
            tests.read_text(encoding="utf-8", errors="replace")
            .rstrip()
            .splitlines()[-_TEST_TAIL_LINES:]
        )

    return Trial(
        agent=agent,
        dir=trial_dir,
        passed=None if reward is None else reward >= 1.0,
        reward=reward,
        test_tail=tail,
        steps=steps,
        cost_usd=float(cost) if isinstance(cost, (int, float)) else None,
        tokens_in=int(agent_result.get("n_input_tokens") or 0),
        tokens_out=int(agent_result.get("n_output_tokens") or 0),
        duration_ms=_duration_ms(result),
        exit_reason=exit_reason,
        error=error,
    )
