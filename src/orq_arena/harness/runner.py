"""Run harness candidates through the ``harbor`` CLI, stream their trajectories.

Harbor is an external tool, not a Python dependency: it needs Python 3.12 and
this package supports 3.10. A trial is one ``harbor run`` subprocess. Trials are
cached on disk by ``(prompt_hash, candidate_id)``: the same agent on the same task
is run once per tournament, and every later match that draws it replays the
stored trajectory instantly while the jury still judges live.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import signal
import subprocess
import time
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from ..candidates import HarnessCandidate
from ..config import HarnessConfig
from ..data.prompts import PromptItem, prompt_hash
from ..events import ArenaEvent, SolutionReady, TrajectoryStep
from . import tail
from .diff import RunCmd, run_cmd, workspace_diff
from .parsers import parse_line
from .trial import Trial, find_trial_dir, load_trial

EXTRAS_FILE = "orq_arena.json"  # diff stat and notes, next to Harbor's own files
PATCH_FILE = "diff.patch"
_SIGINT_GRACE_S = 30

Spawn = Callable[..., Any]


class HarnessError(RuntimeError):
    """The harness could not be run at all (as opposed to an agent that lost)."""


@lru_cache(maxsize=4)
def harbor_version(harbor_bin: str) -> str:
    exe = shutil.which(harbor_bin)
    if exe is None:
        return "unknown"
    try:
        out = subprocess.run(
            [exe, "--version"], capture_output=True, text=True, timeout=15, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    return (
        (out.stdout or out.stderr).strip().splitlines()[-1]
        if (out.stdout or out.stderr)
        else "unknown"
    )


def job_name(prompt_text: str, candidate_id: str) -> str:
    """Directory-safe cache key for one (task, candidate) trial."""
    return f"{prompt_hash(prompt_text)}-{hashlib.sha256(candidate_id.encode()).hexdigest()[:10]}"


def api_endpoint(router_host: str, api_format: str | None) -> str:
    """Anthropic-native agents use /v3/anthropic, everything else /v3/router."""
    path = "/v3/anthropic" if api_format == "anthropic_messages" else "/v3/router"
    return router_host.rstrip("/") + path


def _ak_value(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value)


def cached_trial_dir(trials_dir: Path, name: str) -> Path | None:
    """The finished trial for ``name``, or None (absent, or a run that never finished)."""
    trial = find_trial_dir(trials_dir / name)
    return trial if trial is not None and (trial / "result.json").exists() else None


class HarborRunner:
    def __init__(
        self,
        cfg: HarnessConfig,
        trials_dir: Path,
        *,
        router_host: str,
        spawn: Spawn = asyncio.create_subprocess_exec,
        diff_run: RunCmd = run_cmd,
        poll_s: float = 0.5,
    ) -> None:
        self.cfg = cfg
        self.trials_dir = Path(trials_dir)
        self.router_host = router_host
        self._spawn = spawn
        self._diff_run = diff_run
        self._poll_s = poll_s
        self._sem = asyncio.Semaphore(max(1, cfg.max_parallel_trials))
        self._trials: dict[tuple[str, str], asyncio.Future[Trial]] = {}

    # ----- command line -------------------------------------------------

    def _argv(self, item: PromptItem, c: HarnessCandidate, name: str) -> list[str]:
        task = item.metadata.get("harbor_task_path")
        if not task:
            raise HarnessError(
                "this prompt row has no harbor_task_path; build the prompt file with "
                "`orq-arena tasks sample`"
            )
        overlay = c.overlay.to_kwargs(c.agent) if c.overlay else None
        kwargs = {**c.agent_kwargs, **(overlay.kwargs if overlay else {})}
        instructions = "\n\n".join(
            p for p in (c.extra_instructions, overlay.extra_instructions if overlay else "") if p
        )
        if instructions:
            kwargs["extra_instructions"] = instructions
        argv = [
            self.cfg.harbor_bin, "run",
            "-p", str(task),
            "-a", (overlay.custom_agent if overlay and overlay.custom_agent else c.agent),
            "-m", c.model_id,
            "-n", "1",
            "-o", str(self.trials_dir),
            "--job-name", name,
            "--timeout-multiplier", str(c.timeout_multiplier or self.cfg.timeout_multiplier),
            "--base-url", api_endpoint(self.router_host, c.api_format),
            "--api-key-name", self.cfg.api_key_name,
        ]  # fmt: skip
        if c.api_format:
            argv += ["--api-format", c.api_format]
        for art in self.cfg.artifacts:
            argv += ["--artifact", art]
        for key, value in kwargs.items():
            argv += ["--ak", f"{key}={_ak_value(value)}"]
        for key, value in self._agent_env(c).items():
            argv += ["--ae", f"{key}={value}"]
        return argv

    @staticmethod
    def _agent_env(c: HarnessCandidate) -> dict[str, str]:
        return {k: os.path.expandvars(v) for k, v in c.agent_env.items()}

    def _hard_timeout_s(self, item: PromptItem, c: HarnessCandidate) -> float:
        agent_s = float(item.metadata.get("timeout_sec") or 900)
        mult = c.timeout_multiplier or self.cfg.timeout_multiplier
        # image build/pull, install, verifier: margin on top of twice the agent budget
        return agent_s * mult * 2 + 1800

    # ----- public -------------------------------------------------------

    async def run_side(
        self,
        *,
        item: PromptItem,
        candidate: HarnessCandidate,
        events: asyncio.Queue[ArenaEvent],
        match_id: str,
        side: Literal["a", "b"],
    ) -> Trial:
        """Run (or replay) one side. Always returns a Trial; ``trial.error`` voids the round."""
        key = (prompt_hash(item.text), candidate.candidate_id)
        existing = self._trials.get(key)
        if existing is not None:
            trial = await existing
            await self._replay(trial, events, match_id, side)
            return trial

        fut: asyncio.Future[Trial] = asyncio.get_running_loop().create_future()
        self._trials[key] = fut
        try:
            name = job_name(item.text, candidate.candidate_id)
            done = cached_trial_dir(self.trials_dir, name)
            if done is not None:
                trial = await self._load(done, item, candidate)
                await self._replay(trial, events, match_id, side)
            else:
                trial = await self._run_live(item, candidate, name, events, match_id, side)
        except BaseException as exc:
            # Nothing finished: forget the key so a later match may try again.
            self._trials.pop(key, None)
            if isinstance(exc, Exception):
                fut.set_exception(exc)
                fut.exception()  # mark retrieved when nobody else is waiting
            else:
                fut.cancel()
            raise
        fut.set_result(trial)
        return trial

    def is_cached(self, item: PromptItem, candidate: HarnessCandidate) -> bool:
        name = job_name(item.text, candidate.candidate_id)
        return cached_trial_dir(self.trials_dir, name) is not None

    # ----- internals ----------------------------------------------------

    async def _load(self, trial_dir: Path, item: PromptItem, c: HarnessCandidate) -> Trial:
        trial = load_trial(trial_dir, c.agent)
        extras_path = trial_dir / EXTRAS_FILE
        if extras_path.exists():
            extras = json.loads(extras_path.read_text(encoding="utf-8"))
            patch = trial_dir / PATCH_FILE
            trial.diff = patch.read_text(encoding="utf-8") if patch.exists() else ""
            trial.diff_stat = extras.get("diff_stat", "")
            trial.diff_note = extras.get("diff_note", "")
            trial.tests_edited = bool(extras.get("tests_edited"))
        elif trial.error is None:
            await self._attach_diff(trial, trial_dir, item)
        return trial

    async def _attach_diff(self, trial: Trial, trial_dir: Path, item: PromptItem) -> None:
        d = await workspace_diff(
            trial_dir,
            item.metadata.get("image"),
            enabled=self.cfg.diff,
            max_bytes=self.cfg.diff_max_bytes,
            run=self._diff_run,
        )
        trial.diff, trial.diff_stat = d.text, d.stat
        trial.diff_note, trial.tests_edited = d.note, d.tests_edited
        (trial_dir / PATCH_FILE).write_text(d.text, encoding="utf-8")
        (trial_dir / EXTRAS_FILE).write_text(
            json.dumps({"diff_stat": d.stat, "diff_note": d.note, "tests_edited": d.tests_edited}),
            encoding="utf-8",
        )

    @staticmethod
    def _ready(trial: Trial, match_id: str, side: Literal["a", "b"], replay: bool) -> SolutionReady:
        return SolutionReady(
            match_id=match_id,
            side=side,
            passed=trial.passed,
            reward=trial.reward,
            cost_usd=trial.cost_usd,
            duration_ms=trial.duration_ms,
            steps=trial.n_steps,
            commands=trial.commands,
            edits=trial.edits,
            diff_stat=trial.diff_stat,
            tests_edited=trial.tests_edited,
            exit_reason=trial.exit_reason,
            replay=replay,
            error=trial.error,
        )

    async def _replay(
        self,
        trial: Trial,
        events: asyncio.Queue[ArenaEvent],
        match_id: str,
        side: Literal["a", "b"],
    ) -> None:
        """Emit a stored trial's steps at once: the live side runs concurrently, so pacing buys nothing."""
        for step in trial.steps:
            await events.put(
                TrajectoryStep(
                    match_id=match_id,
                    side=side,
                    kind=step.kind,
                    title=step.title,
                    body=step.body,
                    replay=True,
                )
            )
        await events.put(self._ready(trial, match_id, side, replay=True))

    async def _run_live(
        self,
        item: PromptItem,
        c: HarnessCandidate,
        name: str,
        events: asyncio.Queue[ArenaEvent],
        match_id: str,
        side: Literal["a", "b"],
    ) -> Trial:
        try:
            argv = self._argv(item, c, name)
        except HarnessError as exc:
            return await self._fail(str(exc), c, events, match_id, side)

        job_dir = self.trials_dir / name
        shutil.rmtree(job_dir, ignore_errors=True)  # a partial run from a killed attempt
        self.trials_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.trials_dir / f"{name}.harbor.log"
        env = {**os.environ, **self._agent_env(c)}
        t0 = time.monotonic()

        def on_line(line: str) -> None:
            for step in parse_line(c.agent, line):
                try:
                    events.put_nowait(
                        TrajectoryStep(
                            match_id=match_id,
                            side=side,
                            kind=step.kind,
                            title=step.title,
                            body=step.body,
                            t_ms=int((time.monotonic() - t0) * 1000),
                        )
                    )
                except asyncio.QueueFull:  # a stalled consumer must not stall the trial
                    pass

        async with self._sem:
            t0 = time.monotonic()
            finished = asyncio.Event()
            follower = asyncio.create_task(
                tail.follow(job_dir, c.agent, on_line, finished, poll_s=self._poll_s)
            )
            proc: Any = None
            error = ""
            try:
                with log_path.open("wb") as logfh:
                    proc = await self._spawn(
                        *argv, env=env, stdout=logfh, stderr=asyncio.subprocess.STDOUT
                    )
                    try:
                        await asyncio.wait_for(proc.wait(), self._hard_timeout_s(item, c))
                    except asyncio.TimeoutError:
                        error = "harbor run exceeded its hard time limit"
                if not error and proc.returncode:
                    error = f"harbor run exited {proc.returncode}"
            except OSError as exc:
                error = f"could not start harbor: {exc}"
            finally:
                if proc is not None and proc.returncode is None:
                    await _stop(proc)
                finished.set()
                await follower

        trial_dir = cached_trial_dir(self.trials_dir, name)
        if trial_dir is None:
            tail_log = _log_tail(log_path)
            return await self._fail(
                (error or "harbor produced no result.json") + (f": {tail_log}" if tail_log else ""),
                c,
                events,
                match_id,
                side,
            )
        trial = load_trial(trial_dir, c.agent)
        if trial.error is None:
            await self._attach_diff(trial, trial_dir, item)
        await events.put(self._ready(trial, match_id, side, replay=False))
        return trial

    async def _fail(
        self,
        error: str,
        c: HarnessCandidate,
        events: asyncio.Queue[ArenaEvent],
        match_id: str,
        side: Literal["a", "b"],
    ) -> Trial:
        trial = Trial(agent=c.agent, error=error, exit_reason="error")
        await events.put(self._ready(trial, match_id, side, replay=False))
        return trial


def _log_tail(path: Path, chars: int = 300) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()[-chars:]
    except OSError:
        return ""


async def _stop(proc: Any) -> None:
    """Interrupt Harbor so it tears its container down, then insist."""
    try:
        proc.send_signal(signal.SIGINT)
        await asyncio.wait_for(proc.wait(), _SIGINT_GRACE_S)
    except (asyncio.TimeoutError, ProcessLookupError):
        proc.kill()
        await proc.wait()
