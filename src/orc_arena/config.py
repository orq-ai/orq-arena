"""orc_arena.yaml loader + Pydantic config models."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from .judges.schemas import JudgeSpec
from .orcs.roster import WarriorSpec


class MatchRules(BaseModel):
    starting_hp: int = 100
    max_rounds: int = 5
    damage_unanimous: int = 30
    damage_majority: int = 15
    damage_tie: int = 0


class GatewayConfig(BaseModel):
    base_url: str = "https://api.orq.ai/v2/router"
    api_key_env: str = "ORQ_API_KEY"
    concurrency: int = 4
    warrior_max_tokens: int = 1024
    judge_max_tokens: int = 512


class ArenaConfig(BaseModel):
    """Top-level orc-arena config."""

    match: MatchRules = Field(default_factory=MatchRules)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    warriors: list[WarriorSpec]
    judges: list[JudgeSpec]
    judge_system_prompt: str = (
        "You are an expert judge evaluating AI assistant responses. "
        "Be impartial and focus on accuracy, helpfulness, clarity, and relevance."
    )


def load_config(path: str | Path) -> ArenaConfig:
    """Parse a YAML config into an ``ArenaConfig``."""
    with open(path) as fh:
        raw: dict[str, Any] = yaml.safe_load(fh)
    return ArenaConfig.model_validate(raw)
