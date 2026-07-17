"""Replay the committed example run through the real TUI, for the demo GIF.

Opens on the Run Plan screen (rebuilt from the committed manifest's preflight,
so no API key and no spend), then feeds ArenaApp events reconstructed from
examples/quickstart/battles.jsonl so the live show renders real matches.
Recorded by vhs (scripts/demo.tape) into media/demo.gif:

    vhs scripts/demo.tape
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from orq_arena.config import load_config
from orq_arena.data.schemas import load_records
from orq_arena.events import (
    JudgeVerdictEvent,
    MatchResolved,
    MatchStarted,
    ResponseChunk,
    ResponseComplete,
    StandingsUpdated,
    TournamentEnded,
    TurnPrompt,
    TurnResolved,
)
from orq_arena.preflight import CallCounts, CostCeiling, CostRow
from orq_arena.tournament.driver import rebuild_from_log
from orq_arena.tui.app import ArenaApp, _judge_display

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "quickstart"
REPLAY_MATCHES = ["M1"]  # short on purpose; the GIF should loop, not lecture
CHUNK_CHARS = 90
CHUNK_DELAY_S = 0.006
JUDGE_DELAY_S = 0.8
PLAN_HOLD_S = 5.0  # long enough to read the cost table, short enough to loop
# Outlives the tape's Sleep on purpose: vhs stops recording while the final
# leaderboard is still on screen, so the gif never ends on a shell prompt.
LEADERBOARD_HOLD_S = 30.0


def plan_from_manifest(cfg, manifest: dict) -> dict:
    """The Run Plan dict the CLI would build, rebuilt from the recorded preflight."""
    pf = manifest["preflight"]
    ceiling_d = pf["cost_ceiling"]
    return {
        "counts": CallCounts(**pf["counts"]),
        "ceiling": CostCeiling(
            total_usd=ceiling_d["total_usd"],
            models_usd=ceiling_d["models_usd"],
            judges_usd=ceiling_d["judges_usd"],
            probe_usd=ceiling_d["probe_usd"],
            unpriced=ceiling_d["unpriced"],
            rows=tuple(CostRow(**r) for r in ceiling_d["rows"]),
        ),
        "overlap": pf.get("family_overlaps") or [],
        "probe_lines": [],
        "n_candidates": len(cfg.candidates),
        "n_judges": len(cfg.judges),
        "n_prompts": manifest["prompt_count"],
        "prompts_label": "prompts/starter.jsonl",
        "prompt_categories": manifest.get("category_counts") or {},
        "log_path": "battles.jsonl",
    }


class ReplayApp(ArenaApp):
    """The real ArenaApp with the engine swapped for a recorded-run replay."""

    def __init__(self, *, records, final_elo, final_report, **kwargs) -> None:
        super().__init__(**kwargs)
        self._records = records
        self._final_elo = final_elo
        self._final_report = final_report

    def on_mount(self) -> None:
        super().on_mount()  # pushes RunPlanScreen (plan mode, no auto_start)
        self.set_timer(PLAN_HOLD_S, self.begin)  # the "press ENTER" beat

    async def _run_live(self) -> None:  # overrides the network engine
        put = self._events.put
        by_match: dict[str, list] = {}
        for r in self._records:
            by_match.setdefault(r.match_id, []).append(r)

        for done, mid in enumerate(REPLAY_MATCHES, 1):
            recs = by_match[mid]
            first = recs[0]
            await put(
                MatchStarted(
                    match_id=mid,
                    round_name=f"match {done}/{len(REPLAY_MATCHES)}",
                    model_a=first.model_a,
                    model_b=first.model_b,
                )
            )
            await asyncio.sleep(1.2)
            wins = {"A": 0, "B": 0}
            for rec in recs:
                await put(
                    TurnPrompt(
                        match_id=mid,
                        round_number=rec.round_number,
                        prompt=rec.prompt_text,
                    )
                )
                await asyncio.sleep(0.6)
                a, b = rec.response_a or "", rec.response_b or ""
                for i in range(0, max(len(a), len(b)), CHUNK_CHARS):
                    for side, text in (("a", a), ("b", b)):
                        piece = text[i : i + CHUNK_CHARS]
                        if piece:
                            await put(ResponseChunk(match_id=mid, side=side, text=piece))
                    await asyncio.sleep(CHUNK_DELAY_S)
                for side, text, tok in (
                    ("a", a, rec.tokens_a_out),
                    ("b", b, rec.tokens_b_out),
                ):
                    await put(
                        ResponseComplete(match_id=mid, side=side, full_text=text, tokens_out=tok)
                    )
                await asyncio.sleep(0.5)
                for v in rec.judge_votes:
                    await put(
                        JudgeVerdictEvent(
                            match_id=mid,
                            judge_name=_judge_display(v["model"]),
                            verdict=v.get("vote") or "abstain",
                            reasoning=v.get("explanation") or "",
                            flipped=bool(v.get("flipped")),
                            replacement=bool(v.get("replacement")),
                        )
                    )
                    await asyncio.sleep(JUDGE_DELAY_S)
                if rec.majority_verdict in wins:
                    wins[rec.majority_verdict] += 1
                await put(
                    TurnResolved(
                        match_id=mid,
                        round_number=rec.round_number,
                        majority=rec.majority_verdict,
                    )
                )
                # the dispatcher holds VERDICT_HOLD_S after this on its own
            winner, loser = first.model_a, first.model_b
            if wins["B"] > wins["A"]:
                winner, loser = loser, winner
            elif wins["A"] == wins["B"]:
                winner = loser = ""
            await put(MatchResolved(match_id=mid, winner=winner, loser=loser))
            await put(
                StandingsUpdated(
                    elo=self._final_elo,
                    matches_done=done,
                    matches_total=len(REPLAY_MATCHES),
                )
            )
            await asyncio.sleep(2.0)

        await put(
            TournamentEnded(
                champion=max(self._final_elo, key=self._final_elo.get),
                elo=self._final_elo,
                battle_log_path="examples/quickstart/battles.jsonl",
                report=self._final_report,
            )
        )
        await asyncio.sleep(LEADERBOARD_HOLD_S)
        self.exit()


def main() -> None:
    cfg = load_config(str(EXAMPLE / "config.yaml"))
    records = load_records(EXAMPLE / "battles.jsonl")
    manifest = json.loads((EXAMPLE / "battles.run.json").read_text())
    elo, report = rebuild_from_log(cfg, records)
    replay = [r for r in records if r.match_id in REPLAY_MATCHES and not r.error]
    app = ReplayApp(
        records=replay,
        final_elo=elo,
        final_report=report,
        cfg=cfg,
        prompts=[],
        battle_log_path="examples/quickstart/battles.jsonl",
        plan=plan_from_manifest(cfg, manifest),
    )
    app.run()


if __name__ == "__main__":
    main()
