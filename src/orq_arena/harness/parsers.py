"""Native agent log lines to trajectory steps.

Harbor tees each agent's own structured log into ``agent/<agent>.txt`` while the
trial runs: claude-code writes stream-json, pi writes ``--mode json``, codex
writes its ``exec --json`` events. One line can carry several steps. A line this
module does not recognise becomes a ``log`` step rather than vanishing, so a pane
never goes blank on a format the agent changed.
"""

from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass, field
from typing import Any

from ..events import StepKind

TEST_COMMAND = re.compile(
    r"\b(pytest|py\.test|npm (run )?test|yarn test|go test|cargo test|make (test|check)|"
    r"unittest|ctest|bats|jest|vitest|rspec|tox)\b"
)

_OBS_LINES = 20
_OBS_BYTES = 2048


@dataclass
class Step:
    kind: StepKind
    title: str
    body: str = ""
    # Machine-readable extras: {"exit": "max_turns"}, {"cost_usd": 0.4, "turns": 9}.
    meta: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "title": self.title, "body": self.body, "meta": self.meta}


def _first_line(text: str, limit: int = 160) -> str:
    line = next((ln for ln in text.splitlines() if ln.strip()), "")
    return line if len(line) <= limit else line[: limit - 1] + "…"


def tail_text(text: str, lines: int = _OBS_LINES, limit: int = _OBS_BYTES) -> str:
    """The last ``lines`` lines of ``text``, capped at ``limit`` characters."""
    out = "\n".join(text.rstrip().splitlines()[-lines:])
    return out if len(out) <= limit else "…" + out[-limit:]


def _unwrap_shell(command: str) -> str:
    """codex runs everything as ``/bin/bash -lc '<cmd>'``; show the command itself."""
    try:
        parts = shlex.split(command)
    except ValueError:
        return command
    if len(parts) == 3 and parts[0] in ("/bin/bash", "/bin/sh") and parts[1] == "-lc":
        return parts[2]
    return command


def _command_step(command: str) -> Step:
    command = _unwrap_shell(command)
    kind: StepKind = "test" if TEST_COMMAND.search(command) else "command"
    return Step(kind, "$ " + _first_line(command), command if "\n" in command.strip() else "")


def _text_of(content: Any) -> str:
    """Tool-result content is a string, or a list of {type: text, text}."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            _text_of(c.get("text") if isinstance(c, dict) else c) for c in content if c
        )
    if isinstance(content, dict):
        return _text_of(content.get("text") or content.get("content") or "")
    return "" if content is None else str(content)


def _log(obj: Any) -> Step:
    return Step("log", json.dumps(obj, default=str)[:200])


# claude-code ---------------------------------------------------------------

_CLAUDE_EDIT = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
_CLAUDE_READ = {"Read", "Grep", "Glob", "LS"}


def _claude_tool_use(block: dict[str, Any]) -> Step:
    name = block.get("name", "")
    inp = block.get("input") or {}
    if name == "Bash":
        return _command_step(str(inp.get("command", "")))
    if name in _CLAUDE_EDIT:
        old, new = inp.get("old_string"), inp.get("new_string")
        if old is not None or new is not None:
            body = "\n".join(
                [f"-{ln}" for ln in str(old or "").splitlines()]
                + [f"+{ln}" for ln in str(new or "").splitlines()]
            )
        else:
            body = str(inp.get("content", ""))
        return Step("edit", str(inp.get("file_path") or inp.get("notebook_path") or name), body)
    if name in _CLAUDE_READ:
        target = inp.get("file_path") or inp.get("pattern") or inp.get("path") or ""
        return Step("read", f"{name.lower()} {target}".strip())
    return Step("command", f"{name} {_first_line(json.dumps(inp, default=str), 100)}".strip())


def _parse_claude(obj: dict[str, Any]) -> list[Step]:
    kind = obj.get("type")
    if kind == "system":
        if obj.get("subtype") == "init":
            return [Step("log", f"session started · model {obj.get('model', '?')}")]
        return []  # thinking_tokens, vcs_state_changed and friends are bookkeeping
    if kind in ("assistant", "user"):
        content = (obj.get("message") or {}).get("content")
        if isinstance(content, str):
            return [Step("message", _first_line(content), content)] if kind == "assistant" else []
        steps: list[Step] = []
        for block in content or []:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if kind == "assistant" and btype == "text" and block.get("text", "").strip():
                steps.append(Step("message", _first_line(block["text"]), block["text"]))
            elif kind == "assistant" and btype == "thinking":
                # claude-code ships the signature and an empty text; nothing to show then.
                if block.get("thinking", "").strip():
                    steps.append(
                        Step("thinking", _first_line(block["thinking"]), block["thinking"])
                    )
            elif kind == "assistant" and btype == "tool_use":
                steps.append(_claude_tool_use(block))
            elif kind == "user" and btype == "tool_result":
                text = _text_of(block.get("content"))
                steps.append(Step("observation", _first_line(text, 80), tail_text(text)))
        return steps
    if kind == "result":
        subtype = str(obj.get("subtype", ""))
        exit_reason = (
            "max_turns"
            if "max_turns" in subtype
            else "error"
            if obj.get("is_error") or subtype.startswith("error")
            else "finished"
        )
        cost = obj.get("total_cost_usd")
        return [
            Step(
                "done",
                f"done: {exit_reason}",
                _text_of(obj.get("result"))[:500],
                {"exit": exit_reason, "cost_usd": cost, "turns": obj.get("num_turns")},
            )
        ]
    return [_log(obj)]


# pi (--mode json) ----------------------------------------------------------


def _pi_tool(name: str, args: dict[str, Any]) -> Step:
    low = name.lower()
    if low == "bash":
        return _command_step(str(args.get("command", "")))
    path = str(args.get("path") or args.get("file_path") or "")
    if low in ("edit", "write"):
        pairs = args.get("edits") or [
            {"oldText": args.get("oldText"), "newText": args.get("newText")}
        ]
        body_lines: list[str] = []
        for e in pairs:
            if e.get("oldText") is None and e.get("newText") is None:
                continue
            body_lines += [f"-{ln}" for ln in str(e.get("oldText") or "").splitlines()]
            body_lines += [f"+{ln}" for ln in str(e.get("newText") or "").splitlines()]
        body = "\n".join(body_lines) if body_lines else str(args.get("content", ""))
        return Step("edit", path or name, body)
    if low in ("read", "grep", "find", "ls"):
        return Step("read", f"{low} {path or args.get('pattern', '')}".strip())
    return Step("command", f"{name} {_first_line(json.dumps(args, default=str), 100)}".strip())


def _parse_pi(obj: dict[str, Any]) -> list[Step]:
    kind = obj.get("type")
    if kind == "tool_execution_start":
        return [_pi_tool(str(obj.get("toolName", "")), obj.get("args") or {})]
    if kind == "tool_execution_end":
        text = _text_of((obj.get("result") or {}).get("content", obj.get("result")))
        title = _first_line(text, 80) or "(no output)"
        return [Step("observation", ("✗ " if obj.get("isError") else "") + title, tail_text(text))]
    if kind == "message_end":
        msg = obj.get("message") or {}
        if msg.get("role") != "assistant":
            return []
        steps = []
        if msg.get("stopReason") == "error":
            steps.append(Step("log", "⚠ model call failed: " + str(msg.get("errorMessage", "?"))))
        for block in msg.get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and block.get("text", "").strip():
                steps.append(Step("message", _first_line(block["text"]), block["text"]))
            elif block.get("type") == "thinking" and block.get("thinking", "").strip():
                steps.append(Step("thinking", _first_line(block["thinking"]), block["thinking"]))
        return steps
    if kind == "agent_end":
        return [Step("done", "done: finished", "", {"exit": "finished"})]
    if kind == "auto_retry_start":
        return [Step("log", f"retrying after: {obj.get('errorMessage', '?')}")]
    if kind in (
        "session",
        "agent_start",
        "agent_settled",
        "auto_retry_end",
        "entry_appended",
        "turn_start",
        "turn_end",
        "message_start",
        "message_update",
        "tool_execution_update",
    ):
        return []  # streaming bookkeeping; the matching *_end carries the content
    return [_log(obj)]


# codex (exec --json) -------------------------------------------------------


def _parse_codex(obj: dict[str, Any]) -> list[Step]:
    kind = str(obj.get("type", ""))
    item = obj.get("item") or {}
    itype = item.get("type") or item.get("item_type")
    if kind == "item.started" and itype == "command_execution":
        return [_command_step(str(item.get("command", "")))]
    if kind == "item.completed":
        if itype == "command_execution":
            out = str(item.get("aggregated_output", ""))
            code = item.get("exit_code")
            mark = "" if code in (0, None) else f"✗ exit {code} "
            return [
                Step("observation", mark + (_first_line(out, 80) or "(no output)"), tail_text(out))
            ]
        if itype == "agent_message":
            text = str(item.get("text", ""))
            return [Step("message", _first_line(text), text)]
        if itype == "reasoning":
            text = str(item.get("text", ""))
            return [Step("thinking", _first_line(text), text)]
        if itype == "file_change":
            return [
                Step("edit", str(c.get("path", "?")), str(c.get("kind", "")))
                for c in item.get("changes") or []
            ] or [Step("edit", "file change")]
        return [_log(obj)]
    if kind == "item.started":
        return []
    if kind in ("thread.started", "turn.started"):
        return []
    if kind == "turn.completed":
        return [Step("done", "done: finished", "", {"exit": "finished", "usage": obj.get("usage")})]
    if kind == "error":
        return [Step("log", "⚠ " + str(obj.get("message", "error")))]  # often a retry notice
    if kind == "turn.failed":
        return [
            Step(
                "done",
                "done: error",
                str(obj.get("message") or obj.get("error", "")),
                {"exit": "error"},
            )
        ]
    return [_log(obj)]


_PARSERS = {"claude-code": _parse_claude, "pi": _parse_pi, "codex": _parse_codex}


def parse_line(agent: str, line: str) -> list[Step]:
    """Steps carried by one native log line ([] for pure bookkeeping)."""
    line = line.strip()
    if not line:
        return []
    try:
        obj = json.loads(line)
    except ValueError:
        return [Step("log", line[:200])]
    if not isinstance(obj, dict):
        return [Step("log", line[:200])]
    parser = _PARSERS.get(agent)
    if parser is None:
        return [_log(obj)]
    try:
        return parser(obj)
    except Exception:  # a shape we did not expect is a log line, never a crashed tournament
        return [_log(obj)]
