"""Per-model post-mortems — "why did I win, why did I lose?".

One analyzer call per warrior: its battles, its own responses (trimmed), and
the judges' reconciled explanations go to a cheap analyzer model that returns
a structured summary. Cached in ``analysis.jsonl`` next to the battle log —
re-running the leaderboard doesn't re-spend tokens.

Rebuilt from the chennai concept on the existing router client (no
instructor): JSON-mode + pydantic validation, one retry.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from ..data.schemas import BattleRecord

_MAX_RESPONSE_CHARS = 700
_MAX_BATTLES = 24


class Postmortem(BaseModel):
    model: str = ""
    strengths: list[str] = Field(default_factory=list, description="2-4 recurring strengths")
    weaknesses: list[str] = Field(default_factory=list, description="2-4 recurring weaknesses")
    judge_patterns: list[str] = Field(
        default_factory=list, description="Recurring judge critiques, quoted or paraphrased"
    )
    one_liner: str = Field(default="", description="One coaching sentence for this model")
    # runtime fields
    wins: int = 0
    losses: int = 0
    ties: int = 0
    error: str | None = None
    created_at: float = Field(default_factory=time.time)


def _battles_for(model: str, records: list[BattleRecord]) -> list[dict]:
    """Flatten this model's rounds to its own POV, judge reasoning included."""
    out: list[dict] = []
    for r in records:
        if r.error is not None:
            continue
        if r.model_a == model:
            side, mine, opponent = "A", r.response_a, r.model_b
        elif r.model_b == model:
            side, mine, opponent = "B", r.response_b, r.model_a
        else:
            continue
        if r.majority_verdict in ("A", "B"):
            outcome = "WIN" if r.majority_verdict == side else "LOSS"
        else:
            outcome = r.majority_verdict.upper()
        out.append({
            "prompt": r.prompt_text[:300],
            "category": r.prompt_category,
            "my_response": mine[:_MAX_RESPONSE_CHARS],
            "opponent": opponent,
            "outcome": outcome,
            "judge_notes": [
                f"{v.get('model', '?').split('/')[-1]} voted {v.get('vote') or 'abstain'}"
                + (f": {v['explanation'][:200]}" if v.get("explanation") else "")
                for v in r.judge_votes
            ],
        })
    return out[:_MAX_BATTLES]


_SYSTEM = (
    "You are a blunt performance coach for LLMs in a pairwise arena. Given one "
    "model's rounds — prompts, its responses, outcomes, and the judges' notes — "
    "identify recurring strengths, recurring weaknesses, and patterns in what "
    "judges praised or punished. Be specific and evidence-based; no flattery. "
    "Respond ONLY with JSON: {\"strengths\": [..], \"weaknesses\": [..], "
    "\"judge_patterns\": [..], \"one_liner\": \"..\"}."
)


async def analyze_model(
    *, client: AsyncOpenAI, analyzer_model: str, model: str, records: list[BattleRecord]
) -> Postmortem:
    battles = _battles_for(model, records)
    wins = sum(b["outcome"] == "WIN" for b in battles)
    losses = sum(b["outcome"] == "LOSS" for b in battles)
    ties = sum(b["outcome"] == "TIE" for b in battles)
    if not battles:
        return Postmortem(model=model, error="no judged rounds", wins=0, losses=0, ties=0)

    payload = json.dumps(battles, ensure_ascii=False)
    last_err = ""
    for _ in range(2):
        try:
            resp = await client.chat.completions.create(
                model=analyzer_model,
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": f"Model under review: {model}\n\nRounds:\n{payload}"},
                ],
                max_tokens=800,
                response_format={"type": "json_object"},
            )
            raw = resp.choices[0].message.content or "{}"
            data = json.loads(raw)
            return Postmortem(
                model=model, wins=wins, losses=losses, ties=ties,
                strengths=[str(s) for s in data.get("strengths", [])][:4],
                weaknesses=[str(s) for s in data.get("weaknesses", [])][:4],
                judge_patterns=[str(s) for s in data.get("judge_patterns", [])][:4],
                one_liner=str(data.get("one_liner", "")),
            )
        except Exception as exc:
            last_err = str(exc)
    return Postmortem(model=model, wins=wins, losses=losses, ties=ties, error=last_err[:200])


def load_records(log_path: str | Path) -> list[BattleRecord]:
    records: list[BattleRecord] = []
    p = Path(log_path)
    if not p.exists():
        return records
    with p.open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(BattleRecord.model_validate_json(line))
    return records


def cache_path(log_path: str | Path) -> Path:
    return Path(log_path).with_name("analysis.jsonl")


def read_cache(log_path: str | Path) -> dict[str, Postmortem]:
    out: dict[str, Postmortem] = {}
    p = cache_path(log_path)
    if not p.exists():
        return out
    for line in p.read_text().splitlines():
        if line.strip():
            pm = Postmortem.model_validate_json(line)
            out[pm.model] = pm
    return out


def append_cache(log_path: str | Path, pm: Postmortem) -> None:
    with cache_path(log_path).open("a") as fh:
        fh.write(pm.model_dump_json() + "\n")
