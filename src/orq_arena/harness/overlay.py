"""Harness overlay: the setup around an agent that the arena can vary.

A candidate is "agent + model + overlay". The overlay carries skills, MCP
servers, memory, a system prompt and agent settings, so one run can rate "skills
on vs off" or "memory seeded vs empty" for the same agent and model.

Harbor owns the container, so an overlay is translated into Harbor flags:
``--skill``, ``--mcp-config``, ``--extra-instruction`` and typed agent kwargs
(``--ak``). Not every agent can honor every key; one that cannot fails config
validation with the agent name in the message, so a run never silently tests
nothing.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# overlay key -> the Harbor surface it rides on, per agent. A key missing from an
# agent's set is one that agent cannot honor.
_SUPPORT: dict[str, frozenset[str]] = {
    "claude-code": frozenset({"skills", "mcp_servers", "memory", "system_prompt", "settings"}),
    "pi": frozenset({"skills", "mcp_servers", "system_prompt", "settings"}),
    "codex": frozenset({"skills", "mcp_servers", "system_prompt", "settings"}),
}
# Only claude-code has a typed system-prompt kwarg; the others get the text
# appended to the task instruction, which is a weaker lever (the model sees it as
# part of the user's message, not as its system prompt).
_NATIVE_SYSTEM_PROMPT = frozenset({"claude-code"})


class OverlayError(ValueError):
    """The overlay asks an agent for something it cannot do."""


@dataclass
class OverlayArgs:
    kwargs: dict[str, Any] = field(default_factory=dict)  # --ak key=value
    skills: list[str] = field(default_factory=list)  # --skill <dir>
    mcp_servers: dict[str, Any] = field(default_factory=dict)  # --mcp-config <file>
    extra_instruction: str = ""  # --extra-instruction <text>


def _hash_path(h: Any, root: Path) -> None:
    """Fold a file, or every file under a directory, into ``h`` (path + bytes)."""
    if root.is_dir():
        for p in sorted(q for q in root.rglob("*") if q.is_file()):
            h.update(str(p.relative_to(root)).encode())
            h.update(b"\0")
            h.update(p.read_bytes())
    elif root.is_file():
        h.update(root.read_bytes())
    else:
        h.update(b"<missing>")
    h.update(b"\1")


class Overlay(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skills: str | None = Field(
        default=None,
        description="Directory of one skill (holds SKILL.md) or of several skill directories",
    )
    mcp_servers: dict[str, Any] = Field(
        default_factory=dict, description="Claude-style {name: {command, args} | {url}} map"
    )
    memory: str | None = Field(default=None, description="Directory of seeded memory files")
    system_prompt: str = ""
    settings: dict[str, Any] = Field(default_factory=dict, description="Native agent config")

    def is_empty(self) -> bool:
        return not (
            self.skills or self.mcp_servers or self.memory or self.system_prompt or self.settings
        )

    def paths(self) -> list[str]:
        """Every local path the overlay reads, for the preflight existence check."""
        return [p for p in (self.skills, self.memory) if p]

    def fingerprint(self) -> str:
        """Stable digest of the overlay's content, '' when empty.

        Hashes file contents, not paths, so editing a skill changes the identity
        of the candidate that carries it.
        """
        if self.is_empty():
            return ""
        h = hashlib.sha256()
        h.update(
            json.dumps(
                {
                    "mcp": self.mcp_servers,
                    "prompt": self.system_prompt,
                    "settings": self.settings,
                    "has": [bool(self.skills), bool(self.memory)],
                },
                sort_keys=True,
                default=str,
            ).encode()
        )
        for p in (self.skills, self.memory):
            if p:
                _hash_path(h, Path(p).expanduser())
        return h.hexdigest()

    def to_kwargs(self, agent: str) -> OverlayArgs:
        """Translate into Harbor arguments, or raise naming ``agent``."""
        support = _SUPPORT.get(agent, frozenset({"system_prompt"}))
        for key in ("skills", "mcp_servers", "memory", "system_prompt", "settings"):
            if getattr(self, key) and key not in support:
                raise OverlayError(f"agent {agent!r} cannot honor overlay.{key}")
        out = OverlayArgs()
        if self.skills:
            out.skills.append(str(Path(self.skills).expanduser().resolve()))
        out.mcp_servers = dict(self.mcp_servers)
        if self.memory:
            out.kwargs["memory_dir"] = str(Path(self.memory).expanduser().resolve())
        if self.settings:
            out.kwargs["config"] = json.dumps(self.settings)
        if self.system_prompt:
            if agent in _NATIVE_SYSTEM_PROMPT:
                out.kwargs["append_system_prompt"] = self.system_prompt
            else:
                out.extra_instruction = self.system_prompt
        return out
