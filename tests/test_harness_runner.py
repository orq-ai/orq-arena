"""HarborRunner with a fake `harbor` process: streaming, replay, sharing, failure."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from orq_arena.candidates import HarnessCandidate
from orq_arena.config import HarnessConfig
from orq_arena.data.prompts import PromptItem
from orq_arena.events import SolutionReady, TrajectoryStep
from orq_arena.harness.diff import DiffResult
from orq_arena.harness.runner import HarborRunner, job_name

LINES = [
    {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": "python -m pytest -q"}}]}},
    {"type": "user", "message": {"content": [{"type": "tool_result", "content": "3 passed"}]}},
    {"type": "result", "subtype": "success", "total_cost_usd": 0.5, "num_turns": 2},
]  # fmt: skip


class FakeProc:
    def __init__(self, argv, *, reward=1.0, returncode=0, write=True):
        self.argv, self.returncode, self._reward, self._write = argv, None, reward, write
        self._final = returncode

    def _arg(self, flag):
        return self.argv[self.argv.index(flag) + 1]

    async def wait(self):
        if self._write:
            trial = Path(self._arg("-o")) / self._arg("--job-name") / "task__abc"
            (trial / "agent").mkdir(parents=True)
            (trial / "verifier").mkdir()
            (trial / "config.json").write_text("{}")
            with (trial / "agent" / "claude-code.txt").open("w") as fh:
                for obj in LINES:
                    fh.write(json.dumps(obj) + "\n")
                    fh.flush()
                    await asyncio.sleep(0)
            (trial / "verifier" / "test-stdout.txt").write_text("3 passed")
            (trial / "result.json").write_text(json.dumps({
                "agent_result": {"cost_usd": 0.5, "n_input_tokens": 10, "n_output_tokens": 5},
                "verifier_result": {"rewards": {"reward": self._reward}},
            }))  # fmt: skip
        self.returncode = self._final
        return self.returncode

    def send_signal(self, _sig):
        self.returncode = -2

    def kill(self):
        self.returncode = -9


class Spawner:
    def __init__(self, **kw):
        self.calls: list[list[str]] = []
        self.kw = kw

    async def __call__(self, *argv, **_):
        self.calls.append(list(argv))
        return FakeProc(list(argv), **self.kw)


async def _nodiff(*_a, **_k):
    return 0, b""


def _runner(tmp_path, spawn):
    return HarborRunner(
        HarnessConfig(), tmp_path / "trials", router_host="https://my.orq.ai", spawn=spawn,
        diff_run=_nodiff, poll_s=0.01,
    )  # fmt: skip


def _cand(**kw):
    return HarnessCandidate.model_validate(
        {"kind": "harness", "agent": "claude-code", "model_id": "anthropic/m",
         "api_format": "anthropic_messages", **kw}
    )  # fmt: skip


ITEM = PromptItem("fix it", metadata={"harbor_task_path": "/tasks/fix-git", "timeout_sec": 10})


def _drain(q):
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


async def test_live_run_streams_steps_then_solution_and_builds_argv(tmp_path):
    spawn = Spawner()
    runner, q = _runner(tmp_path, spawn), asyncio.Queue()
    c = _cand(agent_kwargs={"max_turns": 5})
    trial = await runner.run_side(item=ITEM, candidate=c, events=q, match_id="M1", side="a")
    events = _drain(q)
    steps = [e for e in events if isinstance(e, TrajectoryStep)]
    assert [s.kind for s in steps][:2] == ["test", "observation"]
    assert not any(s.replay for s in steps)
    (ready,) = [e for e in events if isinstance(e, SolutionReady)]
    assert ready.passed is True and ready.cost_usd == 0.5 and not ready.replay
    assert trial.passed and trial.test_tail == "3 passed"

    argv = spawn.calls[0]
    assert argv[:2] == ["harbor", "run"]
    assert argv[argv.index("--base-url") + 1] == "https://my.orq.ai/v3/anthropic"
    assert argv[argv.index("--api-format") + 1] == "anthropic_messages"
    assert "max_turns=5" in argv and argv[argv.index("-m") + 1] == "anthropic/m"
    assert argv[argv.index("--job-name") + 1] == job_name("fix it", c.candidate_id)


async def test_second_call_replays_with_no_spawn(tmp_path):
    spawn = Spawner()
    runner, c = _runner(tmp_path, spawn), _cand()
    await runner.run_side(item=ITEM, candidate=c, events=asyncio.Queue(), match_id="M1", side="a")
    q = asyncio.Queue()
    await runner.run_side(item=ITEM, candidate=c, events=q, match_id="M2", side="b")
    assert len(spawn.calls) == 1
    events = _drain(q)
    assert events and all(e.replay for e in events if isinstance(e, TrajectoryStep | SolutionReady))
    assert isinstance(events[-1], SolutionReady) and events[-1].replay


async def test_a_fresh_runner_replays_from_disk(tmp_path):
    c = _cand()
    await _runner(tmp_path, Spawner()).run_side(
        item=ITEM, candidate=c, events=asyncio.Queue(), match_id="M1", side="a"
    )
    spawn = Spawner()
    q = asyncio.Queue()
    await _runner(tmp_path, spawn).run_side(
        item=ITEM, candidate=c, events=q, match_id="M1", side="a"
    )
    assert spawn.calls == [] and _drain(q)[-1].replay


async def test_two_concurrent_callers_share_one_spawn(tmp_path):
    spawn = Spawner()
    runner, c = _runner(tmp_path, spawn), _cand()
    qa, qb = asyncio.Queue(), asyncio.Queue()
    await asyncio.gather(
        runner.run_side(item=ITEM, candidate=c, events=qa, match_id="M1", side="a"),
        runner.run_side(item=ITEM, candidate=c, events=qb, match_id="M2", side="b"),
    )
    assert len(spawn.calls) == 1
    assert any(isinstance(e, SolutionReady) for e in _drain(qa))
    assert any(isinstance(e, SolutionReady) and e.replay for e in _drain(qb))


async def test_nonzero_exit_without_result_is_an_error_trial(tmp_path):
    runner = _runner(tmp_path, Spawner(returncode=2, write=False))
    q = asyncio.Queue()
    trial = await runner.run_side(item=ITEM, candidate=_cand(), events=q, match_id="M", side="a")
    assert trial.error and "exited 2" in trial.error
    (ready,) = [e for e in _drain(q) if isinstance(e, SolutionReady)]
    assert ready.error


async def test_missing_task_path_is_an_error_not_a_crash(tmp_path):
    runner = _runner(tmp_path, Spawner())
    trial = await runner.run_side(
        item=PromptItem("no task"),
        candidate=_cand(),
        events=asyncio.Queue(),
        match_id="M",
        side="a",
    )
    assert trial.error and "harbor_task_path" in trial.error


async def test_failed_verifier_reward_is_a_fail_not_an_error(tmp_path):
    runner = _runner(tmp_path, Spawner(reward=0.0))
    trial = await runner.run_side(
        item=ITEM, candidate=_cand(), events=asyncio.Queue(), match_id="M", side="a"
    )
    assert trial.passed is False and trial.error is None


def test_diffresult_default_is_empty():
    assert DiffResult().text == ""
