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


# Flavor pool for picker-assigned warriors: name, emblem. Models already in
# the YAML keep their configured spec (including reasoning blocks).
ORC_NAME_POOL: tuple[tuple[str, str], ...] = (
    ("Grak the Thoughtful", "⚔"), ("Thrall Swiftclaw", "🗡"),
    ("Morgoth Quadskull", "⚒"), ("Snot the Quick", "🏹"),
    ("Azog Deepmind", "🛡"), ("Gruk Flashfist", "🔥"),
    ("Bolg the Seeker", "🪓"), ("Ugluk Stormcaller", "⚡"),
    ("Mog the Patient", "🐗"), ("Zug Ironjaw", "⛰"),
    ("Krul Sparkfang", "✨"), ("Durz the Wide", "🌊"),
    ("Yagg Doomwhisper", "🌑"), ("Rukh Emberclad", "🕯"),
    ("Skarn Halftusk", "🦴"), ("Vrog the Unmoved", "🗿"),
    ("Nazgrel Quickwit", "💨"), ("Ghor the Verbose", "📜"),
    ("Brakka Threehands", "🪝"), ("Olm Stonebrow", "🪨"),
    ("Zib the Terse", "🎯"), ("Hurg Wallbreaker", "🔨"),
    ("Fenn Shadowstep", "🌫"), ("Torg the Deliberate", "⏳"),
    ("Mawg Brightfang", "🌟"), ("Krix Looplord", "🔁"),
    ("Dregg the Certain", "📌"), ("Shaz Veilpiercer", "🔍"),
    ("Grubb Longwind", "🌪"), ("Okk the Balanced", "⚖"),
    ("Rasz Firsttoken", "🥇"), ("Ulg the Redundant", "📎"),
)


def assign_warriors(model_ids: list[str], existing: list[WarriorSpec]) -> list[WarriorSpec]:
    """Build WarriorSpecs for picked models.

    Models already configured keep their spec (name, emblem, reasoning);
    new models draw names from ORC_NAME_POOL in pick order, provider default
    reasoning (the preflight probe is the safety net).
    """
    by_model = {w.model_id: w for w in existing}
    used_names = {w.orc_name for w in existing}
    pool = iter(n for n in ORC_NAME_POOL if n[0] not in used_names)
    out: list[WarriorSpec] = []
    for mid in model_ids:
        if mid in by_model:
            out.append(by_model[mid])
            continue
        try:
            name, emblem = next(pool)
        except StopIteration:
            name, emblem = mid.rsplit("/", 1)[-1], "⚔"
        out.append(WarriorSpec(orc_name=name, model_id=mid, emblem=emblem))
    return out
