"""orq_arena.yaml loader + Pydantic config models."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import AliasChoices, BaseModel, Field, model_validator

from .roster import CandidateSpec


class MatchRules(BaseModel):
    max_rounds: int = 5
    # HP + damage tiers are TUI presentation only (the live show's health bars);
    # the rating never sees them, it's fed per-round verdicts. The TUI derives
    # damage from the judged verdicts using these knobs.
    starting_hp: int = 100
    damage_unanimous: int = 30
    damage_majority: int = 15


class GatewayConfig(BaseModel):
    base_url: str = "https://api.orq.ai/v3/router"
    api_key_env: str = "ORQ_API_KEY"
    # ``warrior_max_tokens`` accepted as a deprecated YAML alias.
    candidate_max_tokens: int = Field(
        default=2048,
        validation_alias=AliasChoices("candidate_max_tokens", "warrior_max_tokens"),
    )
    # A cap, not a target, free headroom for judges that think by default
    # (G1 finding: 512 starved gemini-2.5-flash's reasoning and killed every
    # one of its votes with LengthFinishReasonError).
    judge_max_tokens: int = 2048
    # Max silence between stream chunks before we declare the connection dead.
    # Generous on purpose: thinking models may pause for minutes before the
    # first token. Fires only on true silence, never on a slow-but-alive stream.
    stream_read_timeout_s: int = 1200
    judge_timeout_ms: int = 90000


class PreflightConfig(BaseModel):
    # One tiny call per candidate before the run: flags models that think
    # despite their config (vendor defaults the router can't disable).
    thinking_probe: bool = True


class ArenaConfig(BaseModel):
    """Top-level orq-arena config."""

    match: MatchRules = Field(default_factory=MatchRules)
    preflight: PreflightConfig = Field(default_factory=PreflightConfig)
    # Parallel matches for headless runs only; the TUI is always sequential.
    headless_concurrency: int = 4
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    # ``warriors`` accepted as a deprecated YAML alias.
    candidates: list[CandidateSpec] = Field(
        validation_alias=AliasChoices("candidates", "warriors"),
    )
    judges: list[str] = Field(description="Judge panel, router model ids")
    replacement_judges: list[str] = Field(default_factory=list)
    criteria: str = (
        "Accuracy and correctness, helpfulness and completeness, "
        "clarity, and relevance to the prompt."
    )
    # Fewer decisive reconciled votes than this -> round is \'inconclusive\',
    # never a verdict. Guards against jury-of-one "unanimous" hits.
    min_successful_judges: int = 2

    @model_validator(mode="after")
    def _validate(self) -> "ArenaConfig":
        if len(self.candidates) < 2:
            raise ValueError(f"Need at least 2 candidates, got {len(self.candidates)}")
        if not self.judges:
            raise ValueError("Judge panel is empty")
        for c in self.candidates:
            budget = ((c.reasoning or {}).get("thinking") or {}).get("budget_tokens")
            cap = c.max_tokens or self.gateway.candidate_max_tokens
            if isinstance(budget, int) and budget >= cap:
                raise ValueError(
                    f"{c.name}: thinking budget_tokens ({budget}) must be < max_tokens ({cap})"
                )
        return self


def load_config(path: str | Path) -> ArenaConfig:
    """Parse a YAML config into an ``ArenaConfig``."""
    with open(path, encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml.safe_load(fh)
    return ArenaConfig.model_validate(raw)
