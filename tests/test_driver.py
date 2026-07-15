"""run_tournament orchestration: scheduling, ELO recompute, events, manifest.

Battle and the gateway are faked so nothing hits the network; the driver's own
logic (round-robin schedule, per-match ELO, standings/end events, manifest
round-trip, seed-stable determinism under concurrency) is what's exercised.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import orq_arena.tournament.driver as driver_mod
from orq_arena.config import ArenaConfig
from orq_arena.data.prompts import PromptItem
from orq_arena.data.schemas import BattleRecord
from orq_arena.events import StandingsUpdated, TournamentEnded


def _cfg(n: int = 3) -> ArenaConfig:
    return ArenaConfig.model_validate({
        "warriors": [{"name": f"C{i}", "model_id": f"x/m{i}"} for i in range(n)],
        "judges": ["x/j1", "x/j2"],
        "preflight": {"thinking_probe": False},
    })


class FakeBattle:
    """candidate_a always wins its match; deterministic given the schedule."""

    def __init__(self, *, cfg, gateway, candidate_a, candidate_b, prompts,
                 match_id, round_name, tournament_id, events):
        self.a, self.b = candidate_a, candidate_b

    async def run(self):
        rec = BattleRecord(
            prompt_hash="h", prompt_text="p",
            model_a=self.a.short_model, model_b=self.b.short_model,
            majority_verdict="A", winner=self.a.short_model,
        )
        return SimpleNamespace(battles=[rec], winner=self.a, loser=self.b, draw=False)


def _patch(monkeypatch):
    monkeypatch.setattr(driver_mod, "Battle", FakeBattle)
    monkeypatch.setattr(driver_mod, "OrqGateway", lambda cfg: object())

    async def _no_prices(_gw):
        return {}

    monkeypatch.setattr("orq_arena.providers.models_list.fetch_price_map", _no_prices)
    monkeypatch.setattr("orq_arena.report.write_report", lambda **kw: None)


async def _run(cfg, tmp_path, *, concurrency=1, preflight=None):
    events: asyncio.Queue = asyncio.Queue()
    log = tmp_path / "battles.jsonl"
    elo = await driver_mod.run_tournament(
        cfg=cfg, prompts=[PromptItem("p1"), PromptItem("p2")],
        battle_log_path=str(log), events=events, seed=7,
        concurrency=concurrency, preflight=preflight,
    )
    drained = []
    while not events.empty():
        drained.append(events.get_nowait())
    return elo, drained, log


async def test_round_robin_runs_every_pair_and_ends(monkeypatch, tmp_path):
    _patch(monkeypatch)
    elo, events, log = await _run(_cfg(3), tmp_path)
    # C(3,2) = 3 matches -> 3 standings updates + 1 end
    standings = [e for e in events if isinstance(e, StandingsUpdated)]
    ended = [e for e in events if isinstance(e, TournamentEnded)]
    assert len(standings) == 3
    assert standings[-1].matches_done == 3 and standings[-1].matches_total == 3
    assert len(ended) == 1
    assert ended[0].champion == max(elo, key=elo.get)
    # 3 matches * 1 record each
    lines = [ln for ln in log.read_text().splitlines() if ln.strip()]
    assert len(lines) == 3


async def test_manifest_round_trips_preflight(monkeypatch, tmp_path):
    _patch(monkeypatch)
    preflight = {"counts": {}, "family_overlaps": ["x/j1"]}
    _elo, _events, log = await _run(_cfg(3), tmp_path, preflight=preflight)
    manifest = json.loads(log.with_suffix(".run.json").read_text())
    assert manifest["seed"] == 7
    assert manifest["preflight"]["family_overlaps"] == ["x/j1"]
    assert "config_sha256" in manifest and "finished_at" in manifest
    assert set(manifest["candidates"]) == {"C0", "C1", "C2"}


async def test_concurrency_is_seed_stable(monkeypatch, tmp_path):
    _patch(monkeypatch)
    elo1, _e1, _l1 = await _run(_cfg(4), tmp_path / "seq", concurrency=1)
    elo3, _e3, _l3 = await _run(_cfg(4), tmp_path / "par", concurrency=3)
    # Pre-drawn slices make the final rating identical regardless of order.
    assert elo1 == elo3


async def test_rebuild_from_log_matches_live_elo(monkeypatch, tmp_path):
    _patch(monkeypatch)
    cfg = _cfg(3)
    elo, _events, log = await _run(cfg, tmp_path)
    records = [
        BattleRecord.model_validate_json(ln)
        for ln in log.read_text().splitlines() if ln.strip()
    ]
    rebuilt_elo, report = driver_mod.rebuild_from_log(cfg, records)
    assert rebuilt_elo == elo
    assert report["rated_rounds"] == 3
