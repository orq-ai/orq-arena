"""orq_arena.yaml loader + Pydantic config models."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator

from .candidates import CandidateSpec


class MatchRules(BaseModel):
    max_rounds: int = 5
    # HP + damage tiers are TUI presentation only (the live show's health bars);
    # the rating never sees them, it's fed per-round verdicts. The TUI derives
    # damage from the judged verdicts using these knobs.
    starting_hp: int = 100
    damage_unanimous: int = 30
    damage_majority: int = 15


# The one secret orq-arena reads; every gateway/catalog/dataset call uses it.
ORQ_API_KEY_ENV = "ORQ_API_KEY"
# The user-facing router host. Completions resolve through evaluatorq, which
# honours ORQ_BASE_URL; the catalog resolves the same way so one run never
# straddles two environments (see providers/models_list.catalog_host).
DEFAULT_ORQ_HOST = "https://api.orq.ai"


class OrqAIGatewayConfig(BaseModel):
    base_url: str = "https://api.orq.ai/v3/router"
    candidate_max_tokens: int = 2048
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
    gateway: OrqAIGatewayConfig = Field(default_factory=OrqAIGatewayConfig)
    candidates: list[CandidateSpec]
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
    def _unique_candidate_names(self) -> ArenaConfig:
        """No two candidates may answer to the same name.

        Display names default to the model id minus its provider prefix, so a
        pool holding the same model from two providers (openai/gpt-oss-120b and
        groq/gpt-oss-120b) would otherwise collapse into one rating with nothing
        printed to say so. Generated names fall back to the full id, which is
        unique by construction; a duplicate the user wrote themselves raises,
        because guessing which one they meant is worse than asking.
        """
        custom = {c.name for c in self.candidates if c.name_is_custom}
        by_short: dict[str, list[CandidateSpec]] = {}
        for c in self.candidates:
            if not c.name_is_custom:
                by_short.setdefault(c.short_model, []).append(c)
        for short, group in by_short.items():
            if len(group) > 1 or short in custom:
                for c in group:
                    c.name = c.model_id

        seen: dict[str, str] = {}
        for c in self.candidates:
            if c.name in seen:
                raise ValueError(
                    f"Duplicate candidate name {c.name!r} "
                    f"({seen[c.name]} and {c.model_id}); names must be unique"
                )
            seen[c.name] = c.model_id
        return self

    @model_validator(mode="after")
    def _validate(self) -> ArenaConfig:
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
