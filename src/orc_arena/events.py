"""Typed events emitted by the engine and consumed by the TUI + fixture replay.

All events are ``pydantic.BaseModel`` so the ``demo`` fixture can round-trip
them as JSON. The engine never calls into the TUI directly — it pushes events
into an ``asyncio.Queue``.

Verdict vocabulary follows evaluatorq's pairwise contract:
per-judge votes are ``'A' | 'B' | 'tie' | 'abstain'`` and a round's consensus
is ``'A' | 'B' | 'tie' | 'inconclusive'``.
"""

from __future__ import annotations

from typing import Any, Literal, Union

from pydantic import BaseModel


class TournamentStarted(BaseModel):
    type: Literal["tournament_started"] = "tournament_started"
    warrior_names: list[str]


class StandingsUpdated(BaseModel):
    """Live Bradley-Terry standings, recomputed after every match."""

    type: Literal["standings_updated"] = "standings_updated"
    elo: dict[str, float]
    matches_done: int
    matches_total: int


class MatchStarted(BaseModel):
    type: Literal["match_started"] = "match_started"
    match_id: str
    round_name: str
    warrior_a: str
    warrior_b: str


class TurnPrompt(BaseModel):
    type: Literal["turn_prompt"] = "turn_prompt"
    match_id: str
    round_number: int
    prompt: str


class ResponseChunk(BaseModel):
    type: Literal["response_chunk"] = "response_chunk"
    match_id: str
    side: Literal["a", "b"]
    text: str


class ThinkingChunk(BaseModel):
    """Best-effort visible reasoning delta — optional per router contract."""

    type: Literal["thinking_chunk"] = "thinking_chunk"
    match_id: str
    side: Literal["a", "b"]
    text: str


class ResponseComplete(BaseModel):
    type: Literal["response_complete"] = "response_complete"
    match_id: str
    side: Literal["a", "b"]
    full_text: str
    tokens_in: int = 0
    tokens_out: int = 0
    reasoning_tokens: int = 0
    finish_reason: str = ""
    error: str | None = None


class JudgeVerdictEvent(BaseModel):
    type: Literal["judge_verdict"] = "judge_verdict"
    match_id: str
    judge_name: str
    verdict: str  # 'A' | 'B' | 'tie' | 'abstain'
    reasoning: str
    flipped: bool = False      # judge contradicted itself across orderings
    replacement: bool = False  # stand-in for a failed judge


class RoundVoided(BaseModel):
    """A side's stream failed after retry — round never judged, never scored."""

    type: Literal["round_voided"] = "round_voided"
    match_id: str
    round_number: int
    reason: str


class TurnResolved(BaseModel):
    type: Literal["turn_resolved"] = "turn_resolved"
    match_id: str
    round_number: int
    majority: str  # 'A' | 'B' | 'tie' | 'inconclusive'
    damage_dealt: int
    loser_side: Literal["a", "b", "none"]
    hp_a: int
    hp_b: int


class MatchResolved(BaseModel):
    type: Literal["match_resolved"] = "match_resolved"
    match_id: str
    winner: str  # orc_name ('' on a draw)
    loser: str
    by: Literal["ko", "round_cap", "draw"]
    final_hp_a: int
    final_hp_b: int


class TournamentEnded(BaseModel):
    type: Literal["tournament_ended"] = "tournament_ended"
    champion: str  # orc_name (ELO leader)
    elo: dict[str, float]
    battle_log_path: str
    # Statistical rollup for the leaderboard: elo_ci, jury (PairwiseReport
    # dump), verbosity, win_grid, thinking flags, mean_agreement, error_rounds.
    report: dict[str, Any] = {}


ArenaEvent = Union[
    TournamentStarted,
    StandingsUpdated,
    MatchStarted,
    TurnPrompt,
    ResponseChunk,
    ThinkingChunk,
    ResponseComplete,
    JudgeVerdictEvent,
    RoundVoided,
    TurnResolved,
    MatchResolved,
    TournamentEnded,
]
