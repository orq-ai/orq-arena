"""Follow an agent's native log while Harbor is still running the trial."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from .trial import find_trial_dir, native_log


async def follow(
    job_dir: Path,
    agent: str,
    on_line: Callable[[str], None],
    finished: asyncio.Event,
    *,
    poll_s: float = 0.5,
) -> None:
    """Call ``on_line`` for every complete line appended to the agent's log.

    The file may not exist yet (Harbor builds the image first) and is found by
    glob once it does. Polls rather than watching: the log lives on a bind
    mount where inotify is unreliable. Returns after ``finished`` is set and the
    log has been drained once more.
    """
    path: Path | None = None
    offset = 0
    partial = ""

    def drain() -> None:
        nonlocal path, offset, partial
        if path is None:
            trial = find_trial_dir(job_dir)
            path = native_log(trial, agent) if trial else None
            if path is None:
                return
        try:
            with path.open("rb") as fh:
                fh.seek(offset)
                chunk = fh.read()
        except OSError:
            return
        if not chunk:
            return
        offset += len(chunk)
        text = partial + chunk.decode("utf-8", errors="replace")
        *lines, partial = text.split("\n")
        for line in lines:
            if line.strip():
                on_line(line)

    while not finished.is_set():
        drain()
        try:
            await asyncio.wait_for(finished.wait(), timeout=poll_s)
        except asyncio.TimeoutError:
            pass
    drain()
    if partial.strip():
        on_line(partial)
