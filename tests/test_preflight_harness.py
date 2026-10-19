"""Harness preflight: blocking checks, the run-plan dict, and model-only filters.

No test here reaches Harbor, Docker or the network: `_run_cmd` and
`preflight.shutil.which` are replaced (conftest's `no_orq_cli` only patches
`credentials.shutil.which`).
"""

from __future__ import annotations

import pytest

from orq_arena import preflight
from orq_arena.config import ArenaConfig
from orq_arena.data.prompts import PromptItem
from orq_arena.harness.runner import job_name
from orq_arena.preflight import (
    call_counts,
    config_warnings,
    cost_projection,
    harness_checks,
    harness_plan,
    judge_context_warnings,
    judge_family_overlaps,
    referenced_models,
    thinking_probe,
)
from orq_arena.providers.models_list import ModelEntry


class Cmds:
    """A scripted `_run_cmd`: records argv, answers by prefix."""

    def __init__(self, *, docker_up=True, images=(), dry_run=(0, "ok"), version="harbor 0.24.0"):
        self.calls: list[list[str]] = []
        self.docker_up = docker_up
        self.images = set(images)
        self.dry_run = dry_run
        self.version = version

    def __call__(self, argv, timeout=30.0):
        self.calls.append(list(argv))
        if argv[:2] == ["docker", "info"]:
            return (0, "") if self.docker_up else (1, "Cannot connect to the Docker daemon")
        if argv[:3] == ["docker", "image", "inspect"]:
            return (0, "") if argv[3] in self.images else (1, "No such image")
        if "--dry-run" in argv:
            return self.dry_run
        if argv[-1] == "--version":
            return 0, self.version + "\n"
        raise AssertionError(f"unexpected command {argv}")

    @property
    def dry_runs(self):
        return [c for c in self.calls if "--dry-run" in c]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ORQ_API_KEY", "sk-test")
    monkeypatch.setattr(preflight.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(preflight.platform, "machine", lambda: "x86_64")
    cmds = Cmds()
    monkeypatch.setattr(preflight, "_run_cmd", cmds)
    return cmds


def _tasks(tmp_path, n=2):
    items = []
    for i in range(n):
        d = tmp_path / f"task-{i}"
        d.mkdir()
        items.append(
            PromptItem(
                text=f"do thing {i}",
                category="easy" if i % 2 == 0 else "hard",
                metadata={
                    "harbor_task_path": str(d),
                    "task_name": f"task-{i}",
                    "difficulty": "easy" if i % 2 == 0 else "hard",
                    "timeout_sec": 900,
                    "image": f"img/task-{i}:1",
                },
            )
        )
    return items


def _cfg(*extra, **over) -> ArenaConfig:
    h = {"kind": "harness", "model_id": "anthropic/m"}
    return ArenaConfig.model_validate(
        {
            "candidates": [
                {**h, "agent": "claude-code", "name": "cc"},
                {**h, "agent": "pi", "name": "pi"},
                *extra,
            ],
            "judges": ["openai/j1"],
            "preflight": {"thinking_probe": False},
            **over,
        }
    )


# ---------------------------------------------------------------- blocking checks


def test_a_healthy_setup_has_no_problems_and_one_dry_run_per_agent(tmp_path, env):
    extra = {
        "kind": "harness",
        "agent": "pi",
        "model_id": "anthropic/m",
        "name": "pi 2",
        "agent_kwargs": {"max_turns": 5},
    }
    cfg, prompts = _cfg(extra), _tasks(tmp_path)
    assert harness_checks(cfg, prompts) == []
    assert len(env.dry_runs) == 2  # claude-code and pi, though pi has two variants
    argv = env.dry_runs[0]
    assert argv[:2] == ["/usr/bin/harbor", "run"] and "--dry-run" in argv
    assert "-o" in argv and str(tmp_path / "task-0") in argv


@pytest.mark.parametrize(
    ("break_it", "needle"),
    [
        (lambda m, e: m.setattr(preflight.shutil, "which", lambda _n: None), "not on PATH"),
        (lambda m, e: setattr(e, "docker_up", False), "Docker daemon"),
        (lambda m, e: m.delenv("ORQ_API_KEY"), "ORQ_API_KEY is not set"),
        (lambda m, e: setattr(e, "version", ""), None),
    ],
)
def test_blocking_problems(tmp_path, env, monkeypatch, break_it, needle):
    break_it(monkeypatch, env)
    problems = harness_checks(_cfg(), _tasks(tmp_path))
    if needle is None:
        assert problems == []  # an empty version string is not a failure by itself
    else:
        assert any(needle in p for p in problems)


def test_a_failing_version_command_blocks(tmp_path, env, monkeypatch):
    monkeypatch.setattr(
        preflight,
        "_run_cmd",
        lambda argv, timeout=30.0: (2, "boom") if argv[-1] == "--version" else (0, ""),
    )
    assert any("--version` failed" in p for p in harness_checks(_cfg(), _tasks(tmp_path)))


def test_missing_overlay_path_names_the_candidate(tmp_path, env):
    cand = {
        "kind": "harness",
        "agent": "claude-code",
        "model_id": "anthropic/m",
        "name": "with skills",
        "overlay": {"skills": str(tmp_path / "no-such-skills")},
    }
    problems = harness_checks(_cfg(cand), _tasks(tmp_path))
    assert any("with skills" in p and "no-such-skills" in p for p in problems)


def test_unresolved_agent_env_blocks_resolved_does_not(tmp_path, env, monkeypatch):
    monkeypatch.delenv("NATIVE_KEY_XYZ", raising=False)
    cand = {
        "kind": "harness",
        "agent": "codex",
        "model_id": "openai/m",
        "name": "codex",
        "agent_env": {"OPENAI_API_KEY": "${NATIVE_KEY_XYZ}"},
    }
    prompts = _tasks(tmp_path)
    assert any("OPENAI_API_KEY" in p for p in harness_checks(_cfg(cand), prompts))
    monkeypatch.setenv("NATIVE_KEY_XYZ", "k")
    assert harness_checks(_cfg(cand), prompts) == []


def test_prompt_rows_need_an_existing_task_directory(tmp_path, env):
    prompts = _tasks(tmp_path)
    prompts.append(PromptItem(text="no meta"))
    prompts.append(PromptItem(text="gone", metadata={"harbor_task_path": str(tmp_path / "gone")}))
    problems = harness_checks(_cfg(), prompts)
    assert any("1 of 4 prompt rows have no harbor_task_path" in p for p in problems)
    assert any("task directories not found" in p and "gone" in p for p in problems)


def test_dry_run_trouble_warns_but_never_blocks(tmp_path, env):
    env.dry_run = (2, "Error: No such option: --dry-run")
    cfg, prompts = _cfg(), _tasks(tmp_path)
    assert harness_checks(cfg, prompts) == []
    lines = harness_plan(cfg, prompts)["checks"]
    assert any(
        ln.startswith("⚠ harbor dry run for claude-code") and "no --dry-run" in ln for ln in lines
    )

    env.dry_run = (1, "flaky thing")
    assert harness_checks(cfg, prompts) == []


# ---------------------------------------------------------------- the plan


PLAN_KEYS = {
    "trials",
    "cached",
    "matches",
    "tasks_per_match",
    "task_names",
    "difficulty_mix",
    "images_missing",
    "agent_timeouts_s",
    "wall_estimate_s",
    "cost_note",
    "harnesses",
}


def test_plan_shape_and_numbers(tmp_path, env):
    cfg, prompts = _cfg(), _tasks(tmp_path, 3)
    env.images = {"img/task-0:1"}
    out = harness_plan(cfg, prompts, trials_dir=tmp_path / "trials")
    plan = out["plan"]
    assert set(out) == {"plan", "checks"} and set(plan) == PLAN_KEYS
    assert plan["trials"] == 6 and plan["cached"] == 0 and plan["matches"] == 1
    assert plan["tasks_per_match"] == 3
    assert plan["task_names"] == ["task-0", "task-1", "task-2"]
    assert plan["difficulty_mix"] == {"easy": 2, "hard": 1}
    assert plan["images_missing"] == ["img/task-1:1", "img/task-2:1"]
    assert plan["agent_timeouts_s"] == 3 * 900 * 2
    # 6 uncached trials x 900 s x 1.5 multiplier, on 2 lanes
    assert plan["wall_estimate_s"] == int(6 * 900 * 1.5 / 2)
    assert "not projected" in plan["cost_note"] and "max_budget_usd" in plan["cost_note"]
    assert plan["harnesses"][0] == {
        "name": "cc",
        "agent": "claude-code",
        "model": "anthropic/m",
        "overlay": "vanilla",
        "api_format": "anthropic messages",
    }
    assert any(ln.startswith("✓ harbor 0.24.0") for ln in out["checks"])
    assert "✓ docker" in out["checks"] and "✓ ORQ_API_KEY" in out["checks"]
    assert any("1/3 images" in ln for ln in out["checks"])


def test_cached_trials_are_counted_and_skip_the_wall_estimate(tmp_path, env):
    cfg, prompts = _cfg(), _tasks(tmp_path, 2)
    trials = tmp_path / "trials"
    done = trials / job_name(prompts[0].text, cfg.candidates[0].candidate_id) / "t__abc"
    done.mkdir(parents=True)
    (done / "config.json").write_text("{}")
    (done / "result.json").write_text(
        '{"verifier_result": {"rewards": {"reward": 1}}, "agent_result": {"n_input_tokens": 5}}'
    )
    # a partial run: config but no result.json, so it is not a hit
    part = trials / job_name(prompts[1].text, cfg.candidates[0].candidate_id) / "t__def"
    part.mkdir(parents=True)
    (part / "config.json").write_text("{}")

    plan = harness_plan(cfg, prompts, trials_dir=str(trials))["plan"]
    assert plan["cached"] == 1 and plan["trials"] == 4
    assert plan["wall_estimate_s"] == int(3 * 900 * 1.5 / 2)


def test_without_docker_no_image_is_reported_missing(tmp_path, env):
    env.docker_up = False
    out = harness_plan(_cfg(), _tasks(tmp_path))
    assert out["plan"]["images_missing"] == []
    assert not any("images" in ln for ln in out["checks"])


def test_emulation_warning_only_on_arm(tmp_path, env, monkeypatch):
    cfg, prompts = _cfg(), _tasks(tmp_path)
    assert not any("emulation" in ln for ln in harness_plan(cfg, prompts)["checks"])
    monkeypatch.setattr(preflight.platform, "machine", lambda: "arm64")
    assert (
        "⚠ images are linux/amd64, running under emulation" in harness_plan(cfg, prompts)["checks"]
    )


def test_plan_reuses_the_checks_dry_runs(tmp_path, env):
    cfg, prompts = _cfg(), _tasks(tmp_path)
    harness_checks(cfg, prompts)
    n = len(env.dry_runs)
    harness_plan(cfg, prompts)
    assert len(env.dry_runs) == n


# ---------------------------------------------------------------- model-only filters


def test_harness_ids_never_reach_the_catalog_check():
    cfg = _cfg()
    assert referenced_models(cfg) == ["openai/j1"]
    catalog = {
        "openai/j1": ModelEntry(id="openai/j1", provider="openai", endpoints=("chat", "responses"))
    }
    assert config_warnings(cfg, catalog) == []


def test_counts_cost_and_context_ignore_harness_sides():
    model = {"model_id": "p/plain"}
    cfg = _cfg(model, preflight={"thinking_probe": True})
    prompts = [PromptItem(text="x" * 400)]
    counts = call_counts(cfg, prompts)
    # 3 candidates, 3 matches; only the two matches against p/plain stream a model
    assert counts.matches == 3 and counts.model_streams == 2
    assert counts.probe_calls == 1
    cost = cost_projection(cfg, prompts, counts, {"p/plain": (1.0, 2.0), "openai/j1": (1.0, 2.0)})
    assert cost.unpriced == [] and cost.models_usd > 0
    assert [r.model_id for r in cost.rows if r.role == "candidate"] == ["p/plain"]
    assert judge_context_warnings(cfg, prompts, {}) == []


def test_probe_spends_no_call_on_a_harness(monkeypatch):
    seen: list[str] = []

    class FakeGateway:
        def __init__(self, _cfg):
            pass

        async def stream_completion(self, *, model, **_kw):
            seen.append(model)
            yield "text", "ok"

    monkeypatch.setattr(preflight, "OrqGateway", FakeGateway)
    import asyncio

    cfg = _cfg({"model_id": "p/plain"}, preflight={"thinking_probe": True})
    probe = asyncio.run(thinking_probe(cfg))
    assert seen == ["p/plain"] and list(probe) == ["plain"]


def test_family_overlap_reads_harness_model_ids():
    cfg = _cfg()
    assert judge_family_overlaps(["anthropic/judge", "openai/j1"], cfg.candidates) == [
        "anthropic/judge"
    ]
