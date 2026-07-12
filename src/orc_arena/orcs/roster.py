"""Warrior specification."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class WarriorSpec(BaseModel):
    """A single orc warrior — a model routed via the orq.ai gateway."""

    orc_name: str = Field(description="Flavor display name, e.g. 'Grak the Thoughtful'")
    model_id: str = Field(description="orq.ai gateway model slug, e.g. 'anthropic/claude-opus-4-8'")
    emblem: str = Field(default="⚔", description="Single-glyph emblem rendered on the warrior card")
    # Raw router reasoning controls, forwarded verbatim as extra_body — e.g.
    # {"thinking": {"type": "enabled", "budget_tokens": 4096}} or
    # {"reasoning_effort": "medium"}. None = provider default.
    reasoning: dict[str, Any] | None = None
    # Per-warrior output cap; None = gateway.warrior_max_tokens.
    max_tokens: int | None = None

    @property
    def short_model(self) -> str:
        """'anthropic/claude-opus-4-8' → 'claude-opus-4-8'."""
        return self.model_id.split("/", 1)[-1]

    @property
    def thinking_enabled(self) -> bool:
        """True if this warrior has any reasoning control switched on."""
        r = self.reasoning or {}
        thinking = r.get("thinking") or {}
        if thinking.get("type") == "enabled" or thinking.get("thinking_level"):
            return True
        effort = r.get("reasoning_effort")
        return bool(effort and effort != "none")
