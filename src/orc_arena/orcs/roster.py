"""Warrior specification + default roster."""

from __future__ import annotations

from pydantic import BaseModel, Field


class WarriorSpec(BaseModel):
    """A single orc warrior — a model routed via the orq.ai gateway."""

    orc_name: str = Field(description="Flavor display name, e.g. 'Grak the Thoughtful'")
    model_id: str = Field(description="orq.ai gateway model slug, e.g. 'anthropic/claude-opus-4-7'")
    emblem: str = Field(default="⚔", description="Single-glyph emblem rendered on the warrior card")
    starting_elo: float = Field(default=1000.0)

    @property
    def short_model(self) -> str:
        """'anthropic/claude-opus-4-7' → 'claude-opus-4-7'."""
        return self.model_id.split("/", 1)[-1]
