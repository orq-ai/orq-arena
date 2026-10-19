"""orq_arena.yaml loader + Pydantic config models."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .candidates import AnyCandidate, CandidateSpec, HarnessCandidate


class MatchRules(BaseModel):
    # extra="forbid" on every config-surface model (RES-1156): pydantic's
    # default silently drops unknown keys, so a typo like replacment_judges:
    # configured nothing while the preflight consent read as if it had.
    model_config = ConfigDict(extra="forbid")

    max_rounds: int = 5
    # HP + damage tiers are TUI presentation only (the live show's health bars);
    # the rating never sees them, it's fed per-round verdicts. The TUI derives
    # damage from the judged verdicts using these knobs.
    starting_hp: int = 100
    damage_unanimous: int = 30
    damage_majority: int = 15


# The one secret orq-arena reads; every gateway/catalog/dataset call uses it.
ORQ_API_KEY_ENV = "ORQ_API_KEY"
# The orq.ai host a run talks to unless told otherwise. It is the host
# evaluatorq and the orq CLI default to, so the arena, the judge library under
# it and the CLI that mints its key all name the same place. Completions resolve
# through evaluatorq, which honours ORQ_BASE_URL; the catalog resolves the same
# way so one run never straddles two environments (see
# providers/models_list.catalog_host).
DEFAULT_ORQ_HOST = "https://my.orq.ai"

# `api.orq.ai` is the same service under another name, and it was this repo's
# default before `my.orq.ai`. Every config written then spells the router out as
# `https://api.orq.ai/v3/router`. Those must keep meaning "the orq router", not
# "a bring-your-own endpoint": the difference decides whether ORQ_BASE_URL is
# honoured, and losing that silently is how a staging run ends up priced and
# probed against production.
_ORQ_ROUTER_URLS = frozenset({f"{DEFAULT_ORQ_HOST}/v3/router", "https://api.orq.ai/v3/router"})


def is_orq_router(base_url: str) -> bool:
    """True when ``base_url`` is the orq.ai router, under either of its names."""
    return base_url.rstrip("/") in _ORQ_ROUTER_URLS


class OrqAIGatewayConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str = f"{DEFAULT_ORQ_HOST}/v3/router"
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
    model_config = ConfigDict(extra="forbid")

    # One tiny call per candidate before the run: flags models that think
    # despite their config (vendor defaults the router can't disable).
    thinking_probe: bool = True


class HarnessConfig(BaseModel):
    """How harness candidates run: the Harbor CLI, its router endpoint, the cache."""

    model_config = ConfigDict(extra="forbid")

    harbor_bin: str = "harbor"
    # Trial cache and artifacts, keyed (prompt_hash, candidate_id). None means
    # "<battle log>.trials" next to the run's log.
    trials_dir: str | None = None
    # Global cap on concurrent Harbor trials across all matches (headless).
    max_parallel_trials: int = 2
    # Agents reach the orq router at <router_host>/v3/anthropic (anthropic_messages)
    # or <router_host>/v3/router (openai_*). None follows the arena's gateway host.
    router_host: str | None = None
    api_key_name: str = ORQ_API_KEY_ENV
    # The TB-2.1 images are linux/amd64; on a Mac they run under emulation.
    timeout_multiplier: float = Field(default=1.5, gt=0)
    artifacts: list[str] = Field(default_factory=lambda: ["/app"])
    # Diff the final workspace against the pristine image for the judges.
    diff: bool = True
    diff_max_bytes: int = 200_000


class ArenaConfig(BaseModel):
    """Top-level orq-arena config."""

    model_config = ConfigDict(extra="forbid")

    match: MatchRules = Field(default_factory=MatchRules)
    preflight: PreflightConfig = Field(default_factory=PreflightConfig)
    # Parallel matches for headless runs only; the TUI is always sequential.
    headless_concurrency: int = 4
    gateway: OrqAIGatewayConfig = Field(default_factory=OrqAIGatewayConfig)
    candidates: list[AnyCandidate]
    # Only read when a candidate has kind: harness.
    harness: HarnessConfig = Field(default_factory=HarnessConfig)
    # A hidden-test pass beats a fail without a jury call; the jury only sees
    # pass/pass and fail/fail pairs. Harness runs only.
    verifier_gate: bool = True
    # Optional evaluatorq pairwise prompt template, shared by the run and rejudge.
    judge_prompt: str | None = None
    # (was, model_id) for every candidate the validator had to rename off a
    # collision. Output, never input: excluded so it cannot ride into the
    # manifest's recorded config, and rebuilt from scratch on every validation
    # so a copy cannot inherit or share another config's list.
    renamed: list[tuple[str, str]] = Field(default_factory=list, exclude=True, init=False)
    judges: list[str] = Field(description="Judge panel, router model ids")
    replacement_judges: list[str] = Field(default_factory=list)
    criteria: str = (
        "Accuracy and correctness, helpfulness and completeness, "
        "clarity, and relevance to the prompt."
    )
    # Fewer decisive reconciled votes than this -> round is \'inconclusive\',
    # never a verdict. Guards against jury-of-one "unanimous" hits.
    min_successful_judges: int = 2
    # Which router endpoint seats the judges. "llm" prompts chat models for a JSON
    # verdict; "decisions" asks decision models one A/B/tie choice question through
    # the Decisions API and gets a probability per option back. One mode per panel:
    # the catalog marks some chat models as decision-capable too, so the mode, not
    # the model id, has to say which endpoint a judge answers on.
    judge_api: Literal["llm", "decisions"] = "llm"
    # Show each judge both seat orders (A/B, then B/A) and throw out a vote that
    # flips. Off halves judge calls, and position bias then goes unmeasured.
    judge_swap: bool = True
    # Decisions mode only: a vote whose winning option has a lower probability than
    # this counts as an abstention. None keeps every vote.
    judge_abstain_below: float | None = Field(default=None, gt=0.0, lt=1.0)

    @property
    def has_harness(self) -> bool:
        return any(isinstance(c, HarnessCandidate) for c in self.candidates)

    @model_validator(mode="after")
    def _unique_candidate_names(self) -> ArenaConfig:
        """No two candidates may answer to the same name.

        Display names default to the model id minus its provider prefix, so a
        pool holding the same model from two providers (openai/gpt-oss-120b and
        groq/gpt-oss-120b) would otherwise collapse into one rating with nothing
        printed to say so. A duplicated name falls back to the full model id,
        which is unique by construction, and the swap is recorded in
        ``renamed`` so the CLI can say it out loud rather than quietly
        answering to something the user did not write.

        Two candidates with the same model id *and* the same name are the same
        model listed twice, which no rename can disambiguate, so that raises.
        """
        self.renamed = []  # this validation's findings, not a previous one's
        by_name: dict[str, list[AnyCandidate]] = {}
        for c in self.candidates:
            by_name.setdefault(c.name, []).append(c)
        for name, group in by_name.items():
            if len(group) == 1:
                continue
            if len({c.candidate_id for c in group}) < len(group):
                raise ValueError(
                    f"Duplicate candidate {name!r}: the same model_id (or agent setup) "
                    "is listed twice"
                )
            for c in group:
                self.renamed.append((name, c.candidate_id))
                c.name = c.candidate_id

        seen: dict[str, str] = {}
        for c in self.candidates:
            if c.name in seen:
                raise ValueError(
                    f"Duplicate candidate name {c.name!r} "
                    f"({seen[c.name]} and {c.candidate_id}); names must be unique"
                )
            seen[c.name] = c.candidate_id
        return self

    @model_validator(mode="after")
    def _validate(self) -> ArenaConfig:
        if len(self.candidates) < 2:
            raise ValueError(f"Need at least 2 candidates, got {len(self.candidates)}")
        if not self.judges:
            raise ValueError("Judge panel is empty")
        if self.judge_abstain_below is not None and self.judge_api != "decisions":
            raise ValueError(
                "judge_abstain_below reads the probabilities a decision model returns; "
                "set judge_api: decisions or drop it"
            )
        if self.has_harness and self.judge_api == "decisions":
            raise ValueError(
                "judge_api: decisions cannot read a harness run: decision models "
                "take 32k to 64k of context and a trajectory dossier does not fit. "
                "Use judge_api: llm."
            )
        for c in self.candidates:
            if not isinstance(c, CandidateSpec):
                continue
            budget = ((c.reasoning or {}).get("thinking") or {}).get("budget_tokens")
            cap = c.max_tokens or self.gateway.candidate_max_tokens
            if isinstance(budget, int) and budget >= cap:
                raise ValueError(
                    f"{c.name}: thinking budget_tokens ({budget}) must be < max_tokens ({cap})"
                )
        return self


def known_config_keys() -> list[str]:
    """Every settable key across the config surface, for did-you-mean hints.

    Lives beside the models so a new sub-model added here cannot silently
    drop out of the CLI's suggestion pool.
    """
    models = (
        ArenaConfig,
        MatchRules,
        OrqAIGatewayConfig,
        PreflightConfig,
        HarnessConfig,
        CandidateSpec,
        HarnessCandidate,
    )
    return sorted(
        {
            name
            for model in models
            for name, field in model.model_fields.items()
            if field.init is not False  # 'renamed' is output-only, never a valid key
        }
    )


def load_config(path: str | Path) -> ArenaConfig:
    """Parse a YAML config into an ``ArenaConfig``."""
    with open(path, encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml.safe_load(fh)
    return ArenaConfig.model_validate(raw)
