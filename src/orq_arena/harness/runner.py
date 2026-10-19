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
import sys
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
from .routing import route
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


def _ak_value(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value)


def finished_trial_dir(trials_dir: Path, name: str) -> Path | None:
    """The trial directory once Harbor wrote its ``result.json`` (success or not)."""
    trial = find_trial_dir(trials_dir / name)
    return trial if trial is not None and (trial / "result.json").exists() else None


def cached_trial_dir(trials_dir: Path, name: str) -> Path | None:
    """A trial worth replaying: finished, with the verifier's verdict.

    A cancelled or crashed trial also writes ``result.json`` (with an
    ``exception_info`` and no verifier result), so the file's presence alone says
    nothing about whether the agent got a fair run.
    """
    trial = finished_trial_dir(trials_dir, name)
    if trial is None:
        return None
    try:
        result = json.loads((trial / "result.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return trial if isinstance(result, dict) and result.get("verifier_result") else None


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
        prices: dict[str, tuple[float, float]] | None = None,
        keep_awake: bool | None = None,
    ) -> None:
        self.cfg = cfg
        self.trials_dir = Path(trials_dir)
        self.router_host = router_host
        self._spawn = spawn
        self._diff_run = diff_run
        self._poll_s = poll_s
        self._prices = prices or {}
        # A sleeping Mac freezes the trial and its timeout clock mid-run.
        self._caffeinate = (
            shutil.which("caffeinate")
            if (sys.platform == "darwin" if keep_awake is None else keep_awake)
            else None
        )
        self._sem = asyncio.Semaphore(max(1, cfg.max_parallel_trials))
        self._trials: dict[tuple[str, str], asyncio.Future[Trial]] = {}

    # ----- command line -------------------------------------------------

    def _api_key(self) -> str:
        key = os.environ.get(self.cfg.api_key_name, "")
        if not key:
            raise HarnessError(
                f"{self.cfg.api_key_name} is not set; agents reach the router with it"
            )
        return key

    def _plan(
        self, item: PromptItem, c: HarnessCandidate, name: str
    ) -> tuple[list[str], dict[str, str]]:
        """The Harbor command line and the process environment for one trial."""
        task = item.metadata.get("harbor_task_path")
        if not task:
            raise HarnessError(
                "this prompt row has no harbor_task_path; build the prompt file with "
                "`orq-arena tasks sample`"
            )
        r = route(c.agent, c.model_id, self.router_host, self._api_key())
        overlay = c.overlay.to_kwargs(c.agent) if c.overlay else None
        kwargs: dict[str, Any] = {
            **c.agent_kwargs,
            **r.kwargs,
            **(overlay.kwargs if overlay else {}),
        }
        argv = [
            self.cfg.harbor_bin, "run", "-y",
            "-p", str(task),
            "-a", r.harbor_agent,
            "-m", r.model,
            "-n", "1",
            "-o", str(self.trials_dir),
            "--job-name", name,
            "--timeout-multiplier", str(c.timeout_multiplier or self.cfg.timeout_multiplier),
        ]  # fmt: skip
        for art in self.cfg.artifacts:
            argv += ["--artifact", art]
        for key, value in kwargs.items():
            argv += ["--ak", f"{key}={_ak_value(value)}"]
        if overlay:
            for skill in overlay.skills:
                argv += ["--skill", skill]
            if overlay.mcp_servers:
                mcp = self.trials_dir / f"{name}.mcp.json"
                mcp.parent.mkdir(parents=True, exist_ok=True)
                mcp.write_text(json.dumps({"mcpServers": overlay.mcp_servers}), encoding="utf-8")
                argv += ["--mcp-config", str(mcp)]
        instructions = "\n\n".join(
            p for p in (c.extra_instructions, overlay.extra_instruction if overlay else "") if p
        )
        if instructions:
            argv += ["--extra-instruction", instructions]
        env = {**os.environ, **r.env, **self._agent_env(c)}
        if r.pythonpath:
            env["PYTHONPATH"] = os.pathsep.join(
                p for p in (r.pythonpath, env.get("PYTHONPATH")) if p
            )
        if self._caffeinate:
            argv = [self._caffeinate, "-i", *argv]
        return argv, env

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
        trial = self._priced(load_trial(trial_dir, c.agent), c)
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

    def _priced(self, trial: Trial, c: HarnessCandidate) -> Trial:
        """pi reports no cost; price its tokens at the catalog rate and say so."""
        price = self._prices.get(c.model_id)
        if trial.cost_usd is None and price and (trial.tokens_in or trial.tokens_out):
            trial.cost_usd = (price[0] * trial.tokens_in + price[1] * trial.tokens_out) / 1e6
            trial.cost_estimated = True
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
        job_dir = self.trials_dir / name
        shutil.rmtree(job_dir, ignore_errors=True)  # a partial run from a killed attempt
        self.trials_dir.mkdir(parents=True, exist_ok=True)
        try:
            argv, env = self._plan(item, c, name)
        except HarnessError as exc:
            return await self._fail(str(exc), c, events, match_id, side)
        log_path = self.trials_dir / f"{name}.harbor.log"
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
                    await _remove_containers(find_trial_dir(job_dir))
                finished.set()
                await follower

        trial_dir = finished_trial_dir(self.trials_dir, name)
        if trial_dir is None:
            tail_log = _log_tail(log_path)
            return await self._fail(
                (error or "harbor produced no result.json") + (f": {tail_log}" if tail_log else ""),
                c,
                events,
                match_id,
                side,
            )
        trial = self._priced(load_trial(trial_dir, c.agent), c)
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


async def _remove_containers(trial_dir: Path | None) -> None:
    """Harbor leaves the container behind when interrupted; the trial name is its handle."""
    if trial_dir is None:
        return
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "ps", "-aq", "--filter", f"name={trial_dir.name.lower()}",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )  # fmt: skip
        out, _ = await asyncio.wait_for(proc.communicate(), 20)
        ids = out.decode().split()
        if ids:
            rm = await asyncio.create_subprocess_exec(
                "docker", "rm", "-f", *ids,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )  # fmt: skip
            await asyncio.wait_for(rm.wait(), 30)
    except (OSError, asyncio.TimeoutError):
        pass  # best effort: the user can `docker rm` it
