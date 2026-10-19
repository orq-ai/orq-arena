"""Workspace diff against the pristine task image, with a fake docker."""

from __future__ import annotations

import asyncio

from orq_arena.harness.diff import summarize, workspace_diff

PATCH = """--- /app/src/main.py
+++ /after/src/main.py
@@ -1 +1,2 @@
-a
+b
+c
--- /app/tests/test_x.py
+++ /after/tests/test_x.py
@@ -1 +1 @@
-x
+y
"""


def test_summarize_counts_and_flags_tests():
    stat, tests = summarize(PATCH)
    assert stat == "+3 -2 in 2 files" and tests is True
    assert summarize(PATCH.split("--- /app/tests")[0])[1] is False


async def test_diff_runs_docker_and_caps_output(tmp_path):
    (tmp_path / "artifacts" / "app").mkdir(parents=True)
    seen = {}

    async def run(argv, timeout):
        seen["argv"] = argv
        return 1, PATCH.encode()

    d = await workspace_diff(tmp_path, "img:1", run=run, max_bytes=50)
    assert seen["argv"][:2] == ["docker", "run"] and "img:1" in seen["argv"]
    assert d.stat == "+3 -2 in 2 files" and d.tests_edited and d.text.endswith("[diff truncated]\n")


async def test_diff_fallbacks_say_why(tmp_path):
    async def run(argv, timeout):
        raise AssertionError("docker must not run")

    assert "Dockerfile" in (await workspace_diff(tmp_path, None, run=run)).note
    assert "artifacts/app" in (await workspace_diff(tmp_path, "i", run=run)).note
    assert "disabled" in (await workspace_diff(tmp_path, "i", enabled=False, run=run)).note

    (tmp_path / "artifacts" / "app").mkdir(parents=True)

    async def slow(argv, timeout):
        raise asyncio.TimeoutError

    assert "timed out" in (await workspace_diff(tmp_path, "i", run=slow)).note

    async def bad(argv, timeout):
        return 125, b""

    assert "exited 125" in (await workspace_diff(tmp_path, "i", run=bad)).note
