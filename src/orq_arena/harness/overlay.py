"""Harness overlay: the setup around an agent that the arena can vary.

A candidate is "agent + model + overlay". The overlay carries skills, MCP
servers, memory, a system prompt, agent settings and raw files, so one run can
rate "skills on vs off" or "memory seeded vs empty" for the same agent and model.

Harbor owns the container, so an overlay is translated into Harbor agent kwargs
(``--ak key=value``). Not every agent can honor every key; one that cannot fails
config validation with the agent name in the message, so a run never silently
tests nothing.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# Custom Harbor agent that uploads ``overlay.files`` before delegating to pi.
# Lives in harbor_agents/ and is installed into Harbor's own venv.
PI_FILES_AGENT = "orq_arena_harbor.pi_files:PiWithFiles"

# overlay key -> Harbor agent kwarg, per agent. ``None`` means the text rides in
# ``extra_instructions``, which every Harbor agent accepts. A key missing from an
# agent's row is one that agent cannot honor.
_SUPPORT: dict[str, dict[str, str | None]] = {
    "claude-code": {
        "skills": "skills_dir",
        "mcp_servers": "mcp_servers",
        "memory": "memory_dir",
        "system_prompt": "append_system_prompt",
        "settings": "config",
    },
    "pi": {"skills": "skills", "mcp_servers": "mcp_servers", "system_prompt": None},
    "codex": {"system_prompt": None, "settings": "config"},
}
_FALLBACK_SUPPORT: dict[str, str | None] = {"system_prompt": None}

_HINTS = {"memory": "use `files`", "settings": "use `files`"}


class OverlayError(ValueError):
    """The overlay asks an agent for something it cannot do."""


@dataclass
class OverlayArgs:
    kwargs: dict[str, Any] = field(default_factory=dict)
    extra_instructions: str = ""
    # ``module:Class`` Harbor loads instead of the built-in agent, or None.
    custom_agent: str | None = None


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

    skills: str | None = Field(default=None, description="Directory of skills copied in")
    mcp_servers: dict[str, Any] = Field(default_factory=dict)
    memory: str | None = Field(default=None, description="Directory of seeded memory files")
    system_prompt: str = ""
    settings: dict[str, Any] = Field(default_factory=dict)
    # {container path: local path}; pi only, through the PiWithFiles subclass.
    files: dict[str, str] = Field(default_factory=dict)

    def is_empty(self) -> bool:
        return not (
            self.skills
            or self.mcp_servers
            or self.memory
            or self.system_prompt
            or self.settings
            or self.files
        )

    def paths(self) -> list[str]:
        """Every local path the overlay reads, for the preflight existence check."""
        return [p for p in (self.skills, self.memory, *self.files.values()) if p]

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
                    "files": sorted(self.files),
                    "has": [bool(self.skills), bool(self.memory)],
                },
                sort_keys=True,
                default=str,
            ).encode()
        )
        for p in (self.skills, self.memory, *(self.files[k] for k in sorted(self.files))):
            if p:
                _hash_path(h, Path(p).expanduser())
        return h.hexdigest()

    def to_kwargs(self, agent: str) -> OverlayArgs:
        """Translate into Harbor agent kwargs, or raise naming ``agent``."""
        support = _SUPPORT.get(agent, _FALLBACK_SUPPORT)
        out = OverlayArgs()
        prompt_parts = [self.system_prompt] if self.system_prompt else []

        def put(key: str, value: Any) -> None:
            kwarg = support[key]
            if kwarg is None:
                return
            out.kwargs[kwarg] = value

        for key, value in (
            ("skills", self.skills),
            ("mcp_servers", self.mcp_servers),
            ("memory", self.memory),
            ("settings", self.settings),
        ):
            if not value:
                continue
            if key not in support:
                hint = _HINTS.get(key)
                raise OverlayError(
                    f"agent {agent!r} cannot honor overlay.{key}"
                    + (f" ({hint})" if hint and agent == "pi" else "")
                )
            put(key, str(Path(value).expanduser().resolve()) if isinstance(value, str) else value)

        if self.system_prompt:
            if support["system_prompt"] is None:
                out.extra_instructions = "\n\n".join(prompt_parts)
            else:
                put("system_prompt", self.system_prompt)

        if self.files:
            if agent != "pi":
                raise OverlayError(f"agent {agent!r} cannot honor overlay.files (pi only)")
            out.custom_agent = PI_FILES_AGENT
            out.kwargs["files"] = {
                dest: str(Path(src).expanduser().resolve()) for dest, src in self.files.items()
            }
        return out
