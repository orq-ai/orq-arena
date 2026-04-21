"""Typed events emitted by the engine and consumed by the TUI / future renderers.

All events are ``pydantic.BaseModel`` so a future Unity/web renderer can consume
the same stream via JSON. The engine never calls into the TUI directly — it
pushes events into an ``asyncio.Queue``.
"""

from __future__ import annotations

from typing import Literal, Union

from pydantic import BaseModel, Field

from .judges.schemas import JudgeResult


class TournamentStarted(BaseModel):
    type: Literal["tournament_started"] = "tournament_started"
    warrior_names: list[str]


class BracketUpdated(BaseModel):
    type: Literal["bracket_updated"] = "bracket_updated"
    # round → list of [a, b] matchups; 'a'/'b' may be None for TBD.
    # List (not tuple) so JSON round-trip works cleanly for the fixture replay.
    rounds: list[list[list[str | None]]]


class MatchStarted(BaseModel):
    type: Literal["match_started"] = "match_started"
    match_id: str
    round_name: str  # 'quarterfinal', 'semifinal', 'final'
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


class ResponseComplete(BaseModel):
    type: Literal["response_complete"] = "response_complete"
    match_id: str
    side: Literal["a", "b"]
    full_text: str
    tokens_out: int = 0
    error: str | None = None


class JudgeVerdictEvent(BaseModel):
    type: Literal["judge_verdict"] = "judge_verdict"
    match_id: str
    judge_name: str
    verdict: Literal["A", "B", "TIE"]
    reasoning: str


class TurnResolved(BaseModel):
    type: Literal["turn_resolved"] = "turn_resolved"
    match_id: str
    round_number: int
    majority: Literal["A", "B", "TIE", "DISCARD"]
    verdicts: list[JudgeResult]
    damage_dealt: int
    loser_side: Literal["a", "b", "none"]
    hp_a: int
    hp_b: int


class MatchResolved(BaseModel):
    type: Literal["match_resolved"] = "match_resolved"
    match_id: str
    winner: str  # orc_name
    loser: str
    by: Literal["ko", "round_cap"]
    final_hp_a: int
    final_hp_b: int


class TournamentEnded(BaseModel):
    type: Literal["tournament_ended"] = "tournament_ended"
    champion: str  # orc_name
    elo: dict[str, float]
    battle_log_path: str


ArenaEvent = Union[
    TournamentStarted,
    BracketUpdated,
    MatchStarted,
    TurnPrompt,
    ResponseChunk,
    ResponseComplete,
    JudgeVerdictEvent,
    TurnResolved,
    MatchResolved,
    TournamentEnded,
]
