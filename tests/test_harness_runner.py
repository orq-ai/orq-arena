"""HarborRunner with a fake `harbor` process: streaming, replay, sharing, failure."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

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
        self.envs: list[dict[str, str]] = []
        self.kw = kw

    async def __call__(self, *argv, env=None, **_):
        self.calls.append(list(argv))
        self.envs.append(env or {})
        return FakeProc(list(argv), **self.kw)


async def _nodiff(*_a, **_k):
    return 0, b""


def _runner(tmp_path, spawn, prices=None):
    return HarborRunner(
        HarnessConfig(), tmp_path / "trials", router_host="https://my.orq.ai", spawn=spawn,
        diff_run=_nodiff, poll_s=0.01, keep_awake=False, prices=prices,
    )  # fmt: skip


def _cand(**kw):
    return HarnessCandidate.model_validate(
        {"kind": "harness", "agent": "claude-code", "model_id": "anthropic/m",
         **kw}
    )  # fmt: skip


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("ORQ_API_KEY", "sk-test-key")


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
    assert argv[argv.index("-a") + 1] == "claude-code"
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


async def test_the_key_and_the_endpoint_travel_in_the_environment_not_argv(tmp_path):
    spawn = Spawner()
    await _runner(tmp_path, spawn).run_side(
        item=ITEM, candidate=_cand(), events=asyncio.Queue(), match_id="M", side="a"
    )
    assert not any("sk-test-key" in a for a in spawn.calls[0])
    env = spawn.envs[0]
    assert env["ANTHROPIC_API_KEY"] == "sk-test-key"
    assert env["ANTHROPIC_BASE_URL"] == "https://my.orq.ai/v3/anthropic"


async def test_a_subscription_login_in_the_shell_never_reaches_harbor(tmp_path, monkeypatch):
    # With these set, Harbor bills the user's Claude or Codex subscription, not the router.
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oauth-token")
    monkeypatch.setenv("CLAUDE_FORCE_OAUTH", "1")
    monkeypatch.setenv("CODEX_FORCE_AUTH_JSON", "1")
    spawn = Spawner()
    await _runner(tmp_path, spawn).run_side(
        item=ITEM, candidate=_cand(), events=asyncio.Queue(), match_id="M", side="a"
    )
    env = spawn.envs[0]
    assert not {"CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_FORCE_OAUTH", "CODEX_FORCE_AUTH_JSON"} & set(env)
    assert env["ANTHROPIC_API_KEY"] == "sk-test-key"


async def test_each_replicate_of_a_task_is_its_own_trial(tmp_path):
    spawn = Spawner()
    runner = _runner(tmp_path, spawn)
    rep1 = PromptItem(ITEM.text, metadata={**ITEM.metadata, "replicate": 1})
    for item in (ITEM, rep1, rep1):  # the second rep1 replays the first
        await runner.run_side(
            item=item, candidate=_cand(), events=asyncio.Queue(), match_id="M", side="a"
        )
    names = [c[c.index("--job-name") + 1] for c in spawn.calls]
    assert len(names) == 2 and names[0] != names[1]
    assert names[0] == job_name(ITEM.text, _cand().candidate_id)  # replicate 0 keeps the old name


async def test_a_key_an_agent_prints_is_scrubbed_from_every_file_and_event(tmp_path):
    from orq_arena import redact

    redact.clear()
    key = "sk-test-key-0123456789abcdef"
    spawn = Spawner(reward=1.0)
    runner = _runner(tmp_path, spawn)
    runner._api_key = lambda: key  # type: ignore[method-assign]
    orig = FakeProc.wait

    async def leaky_wait(self):
        await orig(self)
        trial = Path(self._arg("-o")) / self._arg("--job-name") / "task__abc"
        (trial / "agent" / "claude-code.txt").write_text(
            json.dumps({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Bash", "input": {"command": f"env | grep {key}"}}]}}) + "\n"
        )  # fmt: skip
        (trial / "agent" / "raw.log").write_text(f"OPENAI_API_KEY={key}")
        return self.returncode

    FakeProc.wait = leaky_wait  # type: ignore[method-assign]
    try:
        q: asyncio.Queue = asyncio.Queue()
        await runner.run_side(item=ITEM, candidate=_cand(), events=q, match_id="M", side="a")
    finally:
        FakeProc.wait = orig  # type: ignore[method-assign]
        redact.clear()
    leaked = [
        p
        for p in (tmp_path / "trials").rglob("*")
        if p.is_file() and key in p.read_text(errors="ignore")
    ]
    assert not leaked, leaked
    assert not any(key in json.dumps(e.model_dump()) for e in _drain(q))


async def test_pi_and_codex_routes(tmp_path):
    spawn = Spawner()
    runner = _runner(tmp_path, spawn)
    pi = _cand(agent="pi", model_id="anthropic/m")
    codex = _cand(agent="codex", model_id="openai/m")
    for c in (pi, codex):
        await runner.run_side(
            item=ITEM, candidate=c, events=asyncio.Queue(), match_id="M", side="a"
        )
    pi_argv, codex_argv = spawn.calls
    assert pi_argv[pi_argv.index("-m") + 1] == "openai/anthropic/m"
    assert "model_api=openai-completions" in pi_argv
    assert spawn.envs[0]["OPENAI_BASE_URL"] == "https://my.orq.ai/v3/router"
    assert codex_argv[codex_argv.index("-a") + 1] == "orq_codex:OrqCodex"
    assert "orq_codex" in "".join(p.name for p in Path(spawn.envs[1]["PYTHONPATH"]).iterdir())


async def test_overlay_becomes_harbor_flags(tmp_path):
    skills = tmp_path / "skills"
    (skills / "s1").mkdir(parents=True)
    (skills / "s1" / "SKILL.md").write_text("x")
    spawn = Spawner()
    c = _cand(
        overlay={
            "skills": str(skills),
            "mcp_servers": {"git": {"command": "mcp-git"}},
            "system_prompt": "be brief",
        },
        extra_instructions="also this",
    )
    await _runner(tmp_path, spawn).run_side(
        item=ITEM, candidate=c, events=asyncio.Queue(), match_id="M", side="a"
    )
    argv = spawn.calls[0]
    assert argv[argv.index("--skill") + 1] == str(skills.resolve())
    assert "append_system_prompt=be brief" in argv  # claude-code has a native system prompt
    assert argv[argv.index("--extra-instruction") + 1] == "also this"
    mcp = json.loads(Path(argv[argv.index("--mcp-config") + 1]).read_text())
    assert mcp == {"mcpServers": {"git": {"command": "mcp-git"}}}


async def test_a_missing_key_is_an_error_trial(tmp_path, monkeypatch):
    monkeypatch.delenv("ORQ_API_KEY")
    trial = await _runner(tmp_path, Spawner()).run_side(
        item=ITEM, candidate=_cand(), events=asyncio.Queue(), match_id="M", side="a"
    )
    assert trial.error and "ORQ_API_KEY" in trial.error


async def test_a_cancelled_trials_result_is_not_a_cache_hit(tmp_path):
    from orq_arena.harness.runner import cached_trial_dir

    trial = tmp_path / "t" / "job" / "task__abc"
    trial.mkdir(parents=True)
    (trial / "config.json").write_text("{}")
    (trial / "result.json").write_text(
        json.dumps(
            {"exception_info": {"exception_type": "CancelledError"}, "verifier_result": None}
        )
    )
    assert cached_trial_dir(tmp_path / "t", "job") is None


async def test_pi_cost_is_estimated_from_tokens_and_tagged(tmp_path):
    runner = _runner(tmp_path, Spawner(), prices={"anthropic/m": (1.0, 2.0)})
    c = _cand(agent="pi", model_id="anthropic/m")
    # the fake result reports cost 0.5, so wipe it to look like pi
    orig = FakeProc.wait

    async def wait(self):
        rc = await orig(self)
        trial = next((Path(self._arg("-o")) / self._arg("--job-name")).iterdir())
        res = json.loads((trial / "result.json").read_text())
        res["agent_result"]["cost_usd"] = None
        (trial / "result.json").write_text(json.dumps(res))
        return rc

    FakeProc.wait = wait  # type: ignore[method-assign]
    try:
        trial = await runner.run_side(
            item=ITEM, candidate=c, events=asyncio.Queue(), match_id="M", side="a"
        )
    finally:
        FakeProc.wait = orig  # type: ignore[method-assign]
    assert trial.cost_estimated and trial.cost_usd == pytest.approx((10 * 1.0 + 5 * 2.0) / 1e6)


async def test_a_hard_limit_outranks_the_result_harbor_wrote_on_cancel(tmp_path, monkeypatch):
    runner = _runner(tmp_path, Spawner())
    monkeypatch.setattr(runner, "_hard_timeout_s", lambda *_: 0.0)

    class Slow(FakeProc):
        async def wait(self):
            if self.returncode is None and not getattr(self, "_cancelled", False):
                await asyncio.sleep(10)
            return self.returncode

        def send_signal(self, sig):
            # Harbor writes a cancelled result with a verifier-less exception
            trial = Path(self._arg("-o")) / self._arg("--job-name") / "task__x"
            trial.mkdir(parents=True)
            (trial / "config.json").write_text("{}")
            (trial / "result.json").write_text(json.dumps({
                "exception_info": {"exception_type": "CancelledError"},
                "verifier_result": None, "agent_result": None,
            }))  # fmt: skip
            self._cancelled = True
            self.returncode = -2

    async def spawn(*argv, **_):
        return Slow(list(argv))

    runner._spawn = spawn
    trial = await runner.run_side(
        item=ITEM, candidate=_cand(), events=asyncio.Queue(), match_id="M", side="a"
    )
    assert trial.error and trial.passed is None


async def test_an_unexpected_exception_voids_one_round_instead_of_raising(tmp_path, monkeypatch):
    runner = _runner(tmp_path, Spawner())

    async def boom(*_a, **_k):
        raise RuntimeError("bug")

    monkeypatch.setattr(runner, "_run_live", boom)
    trial = await runner.run_side(
        item=ITEM, candidate=_cand(), events=asyncio.Queue(), match_id="M", side="a"
    )
    assert trial.error and "bug" in trial.error
    # and the key was forgotten, so a later match may try again
    assert not runner._trials
