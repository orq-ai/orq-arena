"""Terminal-bench style tasks: find them on disk, sample a stratified set, write prompts.

A task is a directory holding ``task.toml`` and ``instruction.md``; the format is
Harbor's, so the same code reads a clone of ``terminal-bench-2-1`` and Harbor's
own download cache (``~/.cache/harbor/tasks/packages/terminal-bench/<name>/<hash>/``).
"""

from __future__ import annotations

import json
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised on 3.10 only
    import tomli as tomllib

DEFAULT_DATASET = "~/.cache/harbor/tasks/packages/terminal-bench"


@dataclass(frozen=True)
class TaskInfo:
    name: str
    path: Path
    instruction: str
    difficulty: str = "unknown"
    category: str = ""
    tags: tuple[str, ...] = ()
    timeout_sec: float = 900.0
    image: str = ""  # empty: the task builds from a Dockerfile
    gpus: int = 0
    extra: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)


def scan_tasks(root: str | Path) -> list[TaskInfo]:
    """Every task under ``root``, sorted by name; unreadable tasks are skipped."""
    root = Path(root).expanduser()
    found: dict[str, TaskInfo] = {}
    for toml_path in sorted(root.rglob("task.toml")):
        task_dir = toml_path.parent
        instruction = task_dir / "instruction.md"
        if not instruction.is_file():
            continue
        try:
            data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        meta, env = data.get("metadata") or {}, data.get("environment") or {}
        name = str((data.get("task") or {}).get("name") or task_dir.name).split("/")[-1]
        found[name] = TaskInfo(
            name=name,
            path=task_dir.resolve(),
            instruction=instruction.read_text(encoding="utf-8").strip(),
            difficulty=str(meta.get("difficulty") or "unknown"),
            category=str(meta.get("category") or ""),
            tags=tuple(meta.get("tags") or ()),
            timeout_sec=float((data.get("agent") or {}).get("timeout_sec") or 900),
            image=str(env.get("docker_image") or ""),
            gpus=int(env.get("gpus") or 0),
        )
    return [found[k] for k in sorted(found)]


def read_names(path: str | Path) -> list[str]:
    """Task names from a text file, one per line; blank lines and ``#`` comments are skipped."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]


def select_named(tasks: list[TaskInfo], names: list[str]) -> list[TaskInfo]:
    """The named tasks, in the order the names are given. A name with no task is an error."""
    by_name = {t.name: t for t in tasks}
    missing = [n for n in names if n not in by_name]
    if missing:
        raise ValueError(f"no such task in the dataset: {', '.join(missing)}")
    return [by_name[n] for n in names]


def sample_tasks(
    tasks: list[TaskInfo],
    *,
    n: int,
    seed: int = 7,
    max_timeout_s: float | None = 900,
    exclude_gpu: bool = True,
    stratify: str = "difficulty",
) -> list[TaskInfo]:
    """``n`` tasks, spread across ``stratify`` groups in proportion to their size.

    Seed-stable: the same tree and seed give the same sample, so two people
    comparing harnesses on "the seed 7 set" mean the same tasks.
    """
    pool = [
        t
        for t in tasks
        if (not exclude_gpu or t.gpus == 0)
        and (max_timeout_s is None or t.timeout_sec <= max_timeout_s)
    ]
    n = min(n, len(pool))
    if n <= 0:
        return []
    rng = random.Random(seed)
    groups: dict[str, list[TaskInfo]] = {}
    for t in sorted(pool, key=lambda t: t.name):
        groups.setdefault(getattr(t, stratify, "") or "unknown", []).append(t)
    for key in sorted(groups):
        rng.shuffle(groups[key])
    # Largest-remainder allocation: each group's share of n, rounded down, then the
    # leftover seats go to the groups with the biggest fractional parts.
    total = len(pool)
    quota = {k: n * len(g) / total for k, g in groups.items()}
    seats = {k: int(q) for k, q in quota.items()}
    spare = n - sum(seats.values())
    for k in sorted(quota, key=lambda k: (quota[k] - seats[k], k), reverse=True)[:spare]:
        seats[k] += 1
    picked = [t for k in sorted(groups) for t in groups[k][: seats[k]]]
    return sorted(picked, key=lambda t: t.name)


def write_prompts(tasks: list[TaskInfo], out: str | Path, replicates: int = 1) -> None:
    """One JSONL row per task and replicate: the instruction plus what the runner needs.

    With ``replicates`` above 1 every task appears that many times, tagged ``replicate``
    0 to n-1; each is a separate trial per agent. Replicate 0 matches a file written
    without replicates, so trials cached before still count.
    """
    with Path(out).open("w", encoding="utf-8") as fh:
        for t, rep in ((t, r) for r in range(max(1, replicates)) for t in tasks):
            row = {
                "prompt": t.instruction,
                "category": t.difficulty,
                "task_name": t.name,
                "harbor_task_path": str(t.path),
                "tb_category": t.category,
                "difficulty": t.difficulty,
                "timeout_sec": t.timeout_sec,
                "image": t.image,
                "tags": list(t.tags),
            }
            if replicates > 1:
                row["replicate"] = rep
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
