"""Candidate specification: one contestant in the arena.

A contestant is either a model routed via the orq.ai gateway (``CandidateSpec``,
the original and default kind) or a coding-agent harness run through Harbor
(``HarnessCandidate``). Both expose ``name`` and ``candidate_id``; everything that
keys identity (the rating, record names, report views) keys on ``candidate_id``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Discriminator, Field, PrivateAttr, Tag, model_validator

from .harness.overlay import Overlay, OverlayError


class CandidateSpec(BaseModel):
    """A single candidate, a model routed via the orq.ai gateway.

    Display name defaults to the model's short name (owner decision 22:
    model names only on the leaderboard). A custom ``name`` is honoured as
    written. The one case where a name is generated is a collision: two
    providers of the same model share a short name, so ``ArenaConfig`` falls
    both back to their full ids rather than rate them as one model.
    """

    model_config = ConfigDict(extra="forbid")

    # Never dumped: a model candidate's recorded config stays byte-identical to
    # what it was before harness candidates existed, so old manifest hashes hold.
    kind: Literal["model"] = Field(default="model", exclude=True)
    model_id: str = Field(description="orq.ai gateway model slug, e.g. 'anthropic/claude-opus-4-8'")
    name: str = ""
    emblem: str = Field(default="", description="Optional glyph shown before the name")
    # Raw router reasoning controls, forwarded verbatim as extra_body.
    reasoning: dict[str, Any] | None = None
    # Per-candidate output cap; None = gateway.candidate_max_tokens.
    max_tokens: int | None = None

    @model_validator(mode="after")
    def _default_name(self) -> CandidateSpec:
        if not self.name:
            self.name = self.short_model
        return self

    @property
    def short_model(self) -> str:
        """'anthropic/claude-opus-4-8' → 'claude-opus-4-8'."""
        return self.model_id.split("/", 1)[-1]

    @property
    def candidate_id(self) -> str:
        """The identity every per-candidate view keys on (a model: its router id)."""
        return self.model_id

    @property
    def thinking_enabled(self) -> bool:
        """True if this candidate has any reasoning control switched on."""
        r = self.reasoning or {}
        thinking = r.get("thinking") or {}
        if thinking.get("type") == "enabled" or thinking.get("thinking_level"):
            return True
        effort = r.get("reasoning_effort")
        return bool(effort and effort != "none")

    @property
    def thinking_disabled(self) -> bool:
        """True if reasoning is *explicitly* switched off, so the report can tell
        a forced-off model apart from a vendor default that simply doesn't reason."""
        r = self.reasoning or {}
        if (r.get("thinking") or {}).get("type") == "disabled":
            return True
        return r.get("reasoning_effort") == "none"


class HarnessCandidate(BaseModel):
    """A coding-agent harness run through Harbor: agent + model + overlay.

    Same model with a different harness setup (skills, MCP, memory, system
    prompt) is a different contestant, told apart by ``variant``.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["harness"]
    agent: str = Field(description="Harbor agent name, e.g. 'claude-code', 'pi', 'codex'")
    model_id: str = Field(description="Model the agent drives, 'provider/model'")
    name: str = ""
    emblem: str = ""
    # Harbor --api-format; None lets Harbor pick the agent's native wire format.
    api_format: str | None = None
    agent_kwargs: dict[str, Any] = Field(default_factory=dict)
    # Env passed to the Harbor process, e.g. a native key when the router cannot
    # serve this agent. Values may use ${VAR}; only the keys enter the identity.
    agent_env: dict[str, str] = Field(default_factory=dict)
    overlay: Overlay | None = None
    extra_instructions: str = ""
    timeout_multiplier: float | None = None

    _variant: str = PrivateAttr(default="")

    @model_validator(mode="after")
    def _finish(self) -> HarnessCandidate:
        try:
            args = self.overlay.to_kwargs(self.agent) if self.overlay else None
        except OverlayError as exc:
            raise ValueError(f"{self.name or self.agent}: {exc}") from exc
        if args:
            clash = sorted(set(args.kwargs) & set(self.agent_kwargs))
            if clash:
                raise ValueError(
                    f"{self.name or self.agent}: agent_kwargs {clash} duplicate the overlay"
                )
        self._variant = self._compute_variant()
        if not self.name:
            self.name = f"{self.agent}/{self.short_model}" + (
                f"-{self._variant}" if self._variant else ""
            )
        return self

    def _compute_variant(self) -> str:
        overlay_fp = self.overlay.fingerprint() if self.overlay else ""
        if not (self.agent_kwargs or self.agent_env or self.extra_instructions or overlay_fp):
            return ""
        blob = json.dumps(
            {
                "kwargs": self.agent_kwargs,
                "env": sorted(self.agent_env),
                "instructions": self.extra_instructions,
                "overlay": overlay_fp,
            },
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:6]

    @property
    def variant(self) -> str:
        return self._variant

    @property
    def short_model(self) -> str:
        return self.model_id.split("/", 1)[-1]

    @property
    def candidate_id(self) -> str:
        return f"{self.agent}:{self.model_id}" + (f"#{self._variant}" if self._variant else "")

    @property
    def thinking_enabled(self) -> bool:
        k = self.agent_kwargs
        effort = k.get("thinking") or k.get("reasoning_effort")
        return bool(effort and effort not in ("none", "off"))

    # Duck-compat with CandidateSpec for the report and the TUI.
    @property
    def thinking_disabled(self) -> bool:
        return False

    @property
    def reasoning(self) -> None:
        return None

    @property
    def max_tokens(self) -> None:
        return None

    def overlay_summary(self) -> str:
        """'skills, system_prompt' or 'vanilla'."""
        if not self.overlay or self.overlay.is_empty():
            return "agent settings" if self._variant else "vanilla"
        return ", ".join(k for k, v in self.overlay.model_dump().items() if v)

    def label(self) -> str:
        """'claude-code · opus-5-5 · skills #a1b2' for the fight cards."""
        parts = [self.agent, self.short_model, self.overlay_summary()]
        if self._variant:
            parts.append(f"#{self._variant}")
        return " · ".join(parts)


def _kind(value: Any) -> str:
    """Old YAML has no ``kind`` key; absent means a model candidate."""
    if isinstance(value, dict):
        return str(value.get("kind", "model"))
    return str(getattr(value, "kind", "model"))


AnyCandidate = Annotated[
    Union[  # noqa: UP007 (Annotated members cannot use | on 3.10)
        Annotated[CandidateSpec, Tag("model")],
        Annotated[HarnessCandidate, Tag("harness")],
    ],
    Discriminator(_kind),
]
