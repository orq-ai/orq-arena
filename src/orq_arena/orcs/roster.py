"""Warrior specification."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


class WarriorSpec(BaseModel):
    """A single warrior, a model routed via the orq.ai gateway.

    Display name defaults to the model's short name (owner decision 22:
    model names only on the leaderboard). A custom ``orc_name`` is still
    allowed but never generated.
    """

    model_id: str = Field(description="orq.ai gateway model slug, e.g. 'anthropic/claude-opus-4-8'")
    orc_name: str = ""
    emblem: str = Field(default="", description="Optional glyph shown before the name")
    # Raw router reasoning controls, forwarded verbatim as extra_body.
    reasoning: dict[str, Any] | None = None
    # Per-warrior output cap; None = gateway.warrior_max_tokens.
    max_tokens: int | None = None

    @model_validator(mode="after")
    def _default_name(self) -> "WarriorSpec":
        if not self.orc_name:
            self.orc_name = self.short_model
        return self

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


def assign_warriors(model_ids: list[str], existing: list[WarriorSpec]) -> list[WarriorSpec]:
    """Build WarriorSpecs for picked models.

    Models already configured keep their spec (incl. reasoning blocks);
    new models display as their model name (decision 22).
    """
    by_model = {w.model_id: w for w in existing}
    return [by_model.get(mid) or WarriorSpec(model_id=mid) for mid in model_ids]
