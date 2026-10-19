"""Task scanning, stratified sampling and the prompt file."""

from __future__ import annotations

import json

from click.testing import CliRunner

from orq_arena.cli import cli
from orq_arena.data.tasks import sample_tasks, scan_tasks, write_prompts


def _task(root, name, difficulty="easy", timeout=900, gpus=0, image="img/x:1"):
    d = root / name / "abc123"
    d.mkdir(parents=True)
    (d / "instruction.md").write_text(f"Do {name}.\n")
    env = f'docker_image = "{image}"\n' if image else ""
    (d / "task.toml").write_text(
        f'[task]\nname = "terminal-bench/{name}"\n[metadata]\ndifficulty = "{difficulty}"\n'
        f'category = "software-engineering"\ntags = ["a"]\n[agent]\ntimeout_sec = {timeout}\n'
        f"[environment]\n{env}gpus = {gpus}\n"
    )


def _tree(tmp_path):
    for i in range(6):
        _task(tmp_path, f"easy{i}", "easy")
    for i in range(6):
        _task(tmp_path, f"med{i}", "medium")
    for i in range(3):
        _task(tmp_path, f"hard{i}", "hard")
    _task(tmp_path, "gpu1", "easy", gpus=1)
    _task(tmp_path, "slow1", "easy", timeout=3600)
    _task(tmp_path, "build1", "easy", image="")
    return tmp_path


def test_scan_reads_metadata_and_handles_the_cache_layout(tmp_path):
    tasks = scan_tasks(_tree(tmp_path))
    by = {t.name: t for t in tasks}
    assert len(tasks) == 18
    t = by["easy0"]
    assert (t.difficulty, t.timeout_sec, t.image, t.instruction) == (
        "easy",
        900,
        "img/x:1",
        "Do easy0.",
    )
    assert by["build1"].image == "" and by["gpu1"].gpus == 1


def test_sample_is_stratified_filtered_and_seed_stable(tmp_path):
    tasks = scan_tasks(_tree(tmp_path))
    a = sample_tasks(tasks, n=5, seed=1)
    assert a == sample_tasks(tasks, n=5, seed=1)
    assert a != sample_tasks(tasks, n=5, seed=2)
    assert not {t.name for t in a} & {"gpu1", "slow1"}
    mix = {d: sum(1 for t in a if t.difficulty == d) for d in ("easy", "medium", "hard")}
    assert sum(mix.values()) == 5 and all(v >= 1 for v in mix.values())
    assert any(t.name == "slow1" for t in sample_tasks(tasks, n=18, seed=1, max_timeout_s=None))
    assert len(sample_tasks(tasks, n=99, seed=1)) == 16  # capped at what survives the filters


def test_prompt_rows_carry_what_the_runner_needs(tmp_path):
    tasks = sample_tasks(scan_tasks(_tree(tmp_path)), n=3, seed=1)
    out = tmp_path / "p.jsonl"
    write_prompts(tasks, out)
    rows = [json.loads(ln) for ln in out.read_text().splitlines()]
    assert len(rows) == 3
    r = rows[0]
    assert r["prompt"].startswith("Do ") and r["category"] == r["difficulty"]
    assert r["harbor_task_path"].endswith("/abc123") and r["image"] == "img/x:1"
    assert r["timeout_sec"] == 900 and r["task_name"]


def test_cli_samples_and_reports(tmp_path):
    _tree(tmp_path / "tb")
    out = tmp_path / "sub" / "s.jsonl"
    res = CliRunner().invoke(
        cli, ["tasks", "sample", "--dataset", str(tmp_path / "tb"), "--n", "4", "-o", str(out)]
    )
    assert res.exit_code == 0, res.output
    assert len(out.read_text().splitlines()) == 4
    bad = CliRunner().invoke(cli, ["tasks", "sample", "--dataset", str(tmp_path / "nope")])
    assert bad.exit_code != 0


def test_replicates_repeat_each_task_and_replicate_zero_matches_an_unreplicated_file(tmp_path):
    from orq_arena.data.prompts import item_key, load_prompts

    picked = sample_tasks(scan_tasks(_tree(tmp_path / "tb")), n=3, seed=1)
    plain, rep = tmp_path / "plain.jsonl", tmp_path / "rep.jsonl"
    write_prompts(picked, plain)
    write_prompts(picked, rep, replicates=3)
    assert "replicate" not in json.loads(plain.read_text().splitlines()[0])
    rows = [json.loads(line) for line in rep.read_text().splitlines()]
    assert len(rows) == 9
    assert sorted({r["replicate"] for r in rows}) == [0, 1, 2]
    assert [r["task_name"] for r in rows[:3]] == [r["task_name"] for r in rows[3:6]]
    base = load_prompts(plain)
    keys = [item_key(i) for i in load_prompts(rep)]
    assert keys[:3] == [item_key(i) for i in base]  # old cached trials stay valid
    assert len(set(keys)) == 9  # every replicate is its own trial


def test_the_cli_takes_replicates(tmp_path):
    out = tmp_path / "s.jsonl"
    res = CliRunner().invoke(
        cli,
        ["tasks", "sample", "--dataset", str(_tree(tmp_path / "tb")), "--n", "2",
         "--replicates", "3", "-o", str(out)],
    )  # fmt: skip
    assert res.exit_code == 0 and "3 replicates each" in res.output
    assert len(out.read_text().splitlines()) == 6
