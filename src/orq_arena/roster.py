"""Candidate specification: one model under evaluation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


class CandidateSpec(BaseModel):
    """A single candidate, a model routed via the orq.ai gateway.

    Display name defaults to the model's short name (owner decision 22:
    model names only on the leaderboard). A custom ``name`` is still
    allowed but never generated.
    """

    model_id: str = Field(description="orq.ai gateway model slug, e.g. 'anthropic/claude-opus-4-8'")
    name: str = ""
    emblem: str = Field(default="", description="Optional glyph shown before the name")
    # Raw router reasoning controls, forwarded verbatim as extra_body.
    reasoning: dict[str, Any] | None = None
    # Per-candidate output cap; None = gateway.candidate_max_tokens.
    max_tokens: int | None = None

    @model_validator(mode="after")
    def _default_name(self) -> "CandidateSpec":
        if not self.name:
            self.name = self.short_model
        return self

    @property
    def short_model(self) -> str:
        """'anthropic/claude-opus-4-8' → 'claude-opus-4-8'."""
        return self.model_id.split("/", 1)[-1]

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
