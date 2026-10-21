"""What the agent changed: the final workspace against the pristine task image.

Harbor keeps no snapshot of the starting state, only the final ``/app`` when run
with ``--artifact /app``. The pristine side is the task's own Docker image, which
Harbor has already pulled, so one throwaway ``diff`` inside it compares the two.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

DIFF_TIMEOUT_S = 60
_HEADER = re.compile(r"^\+\+\+ (\S+)")

# argv, timeout seconds -> (exit code, stdout). Injected so tests need no docker.
RunCmd = Callable[[list[str], float], Awaitable[tuple[int, bytes]]]


@dataclass
class DiffResult:
    text: str = ""
    stat: str = ""
    note: str = ""  # "diff unavailable: <why>" when there is no text
    tests_edited: bool = False


async def run_cmd(argv: list[str], timeout: float) -> tuple[int, bytes]:
    proc = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    return proc.returncode or 0, out


def summarize(diff: str) -> tuple[str, bool]:
    """('+14 -3 in 2 files', tests_edited) for a unified diff."""
    plus = minus = 0
    files: list[str] = []
    for line in diff.splitlines():
        m = _HEADER.match(line)
        if m:
            files.append(m.group(1))
        elif line.startswith("+") and not line.startswith("+++"):
            plus += 1
        elif line.startswith("-") and not line.startswith("---"):
            minus += 1
    tests = any(re.search(r"(^|/)tests?/", f) for f in files)
    n = len(files)
    return f"+{plus} -{minus} in {n} file{'' if n == 1 else 's'}", tests


async def workspace_diff(
    trial_dir: Path,
    image: str | None,
    *,
    enabled: bool = True,
    max_bytes: int = 200_000,
    run: RunCmd = run_cmd,
) -> DiffResult:
    def unavailable(why: str) -> DiffResult:
        return DiffResult(note=f"diff unavailable: {why}")

    if not enabled:
        return unavailable("disabled in config")
    if not image:
        return unavailable("task builds from a Dockerfile, no pristine image to compare")
    after = trial_dir / "artifacts" / "app"
    if not after.is_dir():
        return unavailable("no artifacts/app in the trial")
    argv = [
        "docker", "run", "--rm", "--entrypoint", "diff",
        "-v", f"{after.resolve()}:/after:ro",
        image, "-ruN", "--exclude=.git", "/app", "/after",
    ]  # fmt: skip
    try:
        code, out = await run(argv, DIFF_TIMEOUT_S)
    except asyncio.TimeoutError:
        return unavailable(f"timed out after {DIFF_TIMEOUT_S}s")
    except OSError as exc:
        return unavailable(str(exc))
    if code not in (0, 1):  # diff exits 1 when the trees differ
        return unavailable(f"docker diff exited {code}")
    text = out.decode("utf-8", errors="replace")
    if not text.strip():
        return DiffResult(stat="no changes")
    stat, tests = summarize(text)
    if len(text.encode("utf-8")) > max_bytes:
        text = text.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")
        text += "\n[diff truncated]\n"
    return DiffResult(text=text, stat=stat, tests_edited=tests)
