"""orc_arena.yaml loader + Pydantic config models."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator

from .orcs.roster import WarriorSpec


class MatchRules(BaseModel):
    starting_hp: int = 100
    max_rounds: int = 5
    damage_unanimous: int = 30
    damage_majority: int = 15
    damage_tie: int = 0
    # Seconds the TUI holds each verdict on screen before the next round.
    # Headless runs set this to 0.
    verdict_hold_s: float = 2.5


class GatewayConfig(BaseModel):
    base_url: str = "https://api.orq.ai/v3/router"
    api_key_env: str = "ORQ_API_KEY"
    warrior_max_tokens: int = 2048
    # A cap, not a target — free headroom for judges that think by default
    # (G1 finding: 512 starved gemini-2.5-flash's reasoning and killed every
    # one of its votes with LengthFinishReasonError).
    judge_max_tokens: int = 2048
    # Max silence between stream chunks before we declare the connection dead.
    # Generous on purpose: thinking models may pause for minutes before the
    # first token. Fires only on true silence, never on a slow-but-alive stream.
    stream_read_timeout_s: int = 1200
    judge_timeout_ms: int = 90000


class PreflightConfig(BaseModel):
    # One tiny call per warrior before the run: flags models that think
    # despite their config (vendor defaults the router can't disable).
    thinking_probe: bool = True


class ArenaConfig(BaseModel):
    """Top-level orc-arena config."""

    match: MatchRules = Field(default_factory=MatchRules)
    preflight: PreflightConfig = Field(default_factory=PreflightConfig)
    # Parallel matches for --headless runs only; the TUI is always sequential.
    headless_concurrency: int = 4
    # Pools >8 auto-switch from full round-robin to Swiss with this many rounds.
    swiss_rounds: int = 6
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    warriors: list[WarriorSpec]
    judges: list[str] = Field(description="Judge panel — router model ids")
    replacement_judges: list[str] = Field(default_factory=list)
    criteria: str = (
        "Accuracy and correctness, helpfulness and completeness, "
        "clarity, and relevance to the prompt."
    )
    # Fewer decisive reconciled votes than this -> round is 'inconclusive',
    # never a verdict. Guards against jury-of-one "unanimous" hits.
    min_successful_judges: int = 2
    # Cheap model for the post-run per-model post-mortems (leaderboard "M").
    analyzer_model: str = "openai/gpt-5.4-mini"

    @model_validator(mode="after")
    def _validate(self) -> "ArenaConfig":
        if len(self.warriors) < 2:
            raise ValueError(f"Need at least 2 warriors, got {len(self.warriors)}")
        if not self.judges:
            raise ValueError("Judge panel is empty")
        for w in self.warriors:
            budget = ((w.reasoning or {}).get("thinking") or {}).get("budget_tokens")
            cap = w.max_tokens or self.gateway.warrior_max_tokens
            if isinstance(budget, int) and budget >= cap:
                raise ValueError(
                    f"{w.orc_name}: thinking budget_tokens ({budget}) must be < "
                    f"max_tokens ({cap})"
                )
        return self


def load_config(path: str | Path) -> ArenaConfig:
    """Parse a YAML config into an ``ArenaConfig``."""
    with open(path) as fh:
        raw: dict[str, Any] = yaml.safe_load(fh)
    return ArenaConfig.model_validate(raw)
