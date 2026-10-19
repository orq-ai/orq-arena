"""The text a judge reads for one side of a harness round.

A harness round has no single answer, so the jury reads a dossier: the hidden
tests' verdict, the workspace diff, a trajectory summary with its key steps, and
the tail of the test output. The string is stored as the record's ``response_a``
or ``response_b``, which is why rejudge, anchor and the battle browser work on a
harness log unchanged.
"""

from __future__ import annotations

from .trial import Trial

DIFF_CAP = 8 * 1024
STEPS_CAP = 6 * 1024


def _clip(text: str, cap: int) -> str:
    return text if len(text) <= cap else text[:cap] + "\n[truncated]"


def _fmt_duration(ms: int) -> str:
    s = ms // 1000
    return f"{s // 60}m {s % 60:02d}s" if s >= 60 else f"{s}s"


def verdict_line(passed: bool | None, reward: float | None) -> str:
    word = {True: "PASSED", False: "FAILED", None: "not run"}[passed]
    return f"{word} (reward {reward:g})" if reward is not None else word


def key_steps(trial: Trial) -> list[str]:
    """First 3, last 5 and every test command, in order, as one line each."""
    shown = [s for s in trial.steps if s.kind in ("command", "test", "edit", "message")]
    keep: dict[int, None] = {}
    for i in [*range(min(3, len(shown))), *range(max(0, len(shown) - 5), len(shown))]:
        keep[i] = None
    for i, s in enumerate(shown):
        if s.kind == "test":
            keep[i] = None
    lines: list[str] = []
    prev = -1
    for i in sorted(keep):
        if prev >= 0 and i != prev + 1:
            lines.append("...")
        s = shown[i]
        lines.append(f"- [{s.kind}] {s.title}")
        prev = i
    return lines


def render(trial: Trial) -> str:
    cost = f"${trial.cost_usd:.2f}" if trial.cost_usd is not None else "cost unknown"
    parts = [f"## Hidden tests: {verdict_line(trial.passed, trial.reward)}"]

    head = "## Workspace diff"
    if trial.diff_stat:
        head += f" ({trial.diff_stat}{', tests/ edited' if trial.tests_edited else ''})"
    parts.append(head)
    parts.append(_clip(trial.diff, DIFF_CAP) if trial.diff else (trial.diff_note or "no changes"))

    parts.append(
        f"## Trajectory: {trial.n_steps} steps, {trial.commands} commands, {trial.edits} edits, "
        f"{_fmt_duration(trial.duration_ms)}, {cost}, exit: {trial.exit_reason}"
    )
    steps = "\n".join(key_steps(trial))
    if steps:
        parts.append("## Key steps\n" + _clip(steps, STEPS_CAP))
    if trial.test_tail:
        parts.append("## Test output (tail)\n" + trial.test_tail)
    return "\n\n".join(parts)
