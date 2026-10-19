"""Native agent log lines to trajectory steps."""

from __future__ import annotations

import json

from orq_arena.harness.parsers import parse_line


def _line(obj) -> str:
    return json.dumps(obj)


def test_claude_bash_tool_use_is_a_command_and_pytest_is_a_test():
    run = {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": "git log --oneline\nls"}},
    ]}}  # fmt: skip
    (step,) = parse_line("claude-code", _line(run))
    assert step.kind == "command" and step.title == "$ git log --oneline"
    test = {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": "python -m pytest -q"}},
    ]}}  # fmt: skip
    (step,) = parse_line("claude-code", _line(test))
    assert step.kind == "test"


def test_claude_edit_read_text_thinking_and_result():
    edit = {"type": "assistant", "message": {"content": [
        {"type": "text", "text": "Fixing it"},
        {"type": "thinking", "thinking": "hmm"},
        {"type": "tool_use", "name": "Edit", "input": {"file_path": "/app/a.py", "old_string": "x", "new_string": "y"}},
        {"type": "tool_use", "name": "Read", "input": {"file_path": "/app/b.py"}},
    ]}}  # fmt: skip
    steps = parse_line("claude-code", _line(edit))
    assert [s.kind for s in steps] == ["message", "thinking", "edit", "read"]
    assert steps[2].title == "/app/a.py" and steps[2].body == "-x\n+y"
    res = {"type": "result", "subtype": "error_max_turns", "total_cost_usd": 0.42, "num_turns": 60}
    (done,) = parse_line("claude-code", _line(res))
    assert (
        done.kind == "done" and done.meta["exit"] == "max_turns" and done.meta["cost_usd"] == 0.42
    )


def test_claude_observation_keeps_the_tail_only():
    out = "\n".join(f"line {i}" for i in range(100))
    ev = {"type": "user", "message": {"content": [
        {"type": "tool_result", "content": [{"type": "text", "text": out}]},
    ]}}  # fmt: skip
    (step,) = parse_line("claude-code", _line(ev))
    assert step.kind == "observation"
    assert step.body.splitlines()[-1] == "line 99" and len(step.body.splitlines()) <= 20


def test_pi_tool_execution_events():
    start = {"type": "tool_execution_start", "toolName": "bash", "args": {"command": "npm test"}}
    (step,) = parse_line("pi", _line(start))
    assert step.kind == "test"
    end = {"type": "tool_execution_end", "toolName": "bash", "isError": True,
           "result": {"content": [{"type": "text", "text": "boom"}]}}  # fmt: skip
    (obs,) = parse_line("pi", _line(end))
    assert obs.kind == "observation" and obs.title.startswith("✗")
    assert parse_line("pi", _line({"type": "message_update"})) == []


def test_codex_items():
    started = {"type": "item.started", "item": {"type": "command_execution", "command": "ls -la"}}
    (cmd,) = parse_line("codex", _line(started))
    assert cmd.kind == "command"
    done = {"type": "item.completed", "item": {"type": "command_execution",
            "command": "ls", "aggregated_output": "a\nb", "exit_code": 2}}  # fmt: skip
    (obs,) = parse_line("codex", _line(done))
    assert obs.kind == "observation" and "exit 2" in obs.title


def test_unknown_and_non_json_lines_become_log_steps_not_nothing():
    (a,) = parse_line("pi", _line({"type": "something_new", "x": 1}))
    assert a.kind == "log" and "something_new" in a.title
    (b,) = parse_line("claude-code", "not json at all")
    assert b.kind == "log"
    (c,) = parse_line("gemini-cli", _line({"hello": 1}))
    assert c.kind == "log"
    assert parse_line("pi", "   ") == []
