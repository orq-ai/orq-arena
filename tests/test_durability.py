"""A round you paid for should survive the run being killed.

The regression: the driver wrote the battle log once per match, after the whole
match returned. Ctrl-C three rounds into a five-round match discarded three
rounds that had already been generated, judged and recorded. At the default
`headless_concurrency: 4` that was up to four matches of paid work at once,
while `docs/cli.md` already promised the log is written "as rounds complete".
"""

from __future__ import annotations

import asyncio

import pytest

from orq_arena.config import ArenaConfig
from orq_arena.data.log import BattleLog
from orq_arena.data.schemas import BattleRecord, load_records

CFG = ArenaConfig.model_validate(
    {
        "candidates": [{"model_id": "prov/a"}, {"model_id": "prov/b"}],
        "judges": ["prov/j1", "prov/j2"],
        "match": {"max_rounds": 5},
    }
)


def _record(n: int) -> BattleRecord:
    return BattleRecord(
        prompt_hash=f"h{n}",
        prompt_text=f"p{n}",
        model_a="a",
        model_b="b",
        response_a="x",
        response_b="y",
        majority_verdict="A",
        winner="a",
        round_number=n,
    )


def test_each_record_lands_on_disk_as_it_resolves(tmp_path):
    log = BattleLog(tmp_path / "battles.jsonl")
    for n in (1, 2, 3):
        log.append(_record(n))
        # Readable immediately, not buffered until some later flush.
        assert len(load_records(log.path)) == n


def test_a_match_abandoned_midway_keeps_the_rounds_it_finished(tmp_path):
    """The exact scenario: killed after round 2 of 5."""
    log = BattleLog(tmp_path / "battles.jsonl")

    async def _match() -> None:
        for n in (1, 2, 3, 4, 5):
            if n == 3:
                raise asyncio.CancelledError  # Ctrl-C lands here
            log.append(_record(n))

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_match())

    kept = load_records(log.path)
    assert [r.round_number for r in kept] == [1, 2]


async def test_the_driver_writes_rounds_not_matches(tmp_path, monkeypatch):
    """End to end through `run_tournament`: the log has to grow while a match
    is still running, which writing once per match never had."""
    from orq_arena.arena.battle import MatchResult
    from orq_arena.tournament import driver as driver_mod

    log_path = tmp_path / "battles.jsonl"
    seen_midmatch: list[int] = []

    class FakeBattle:
        def __init__(self, **kw):
            self._on_record = kw["on_record"]

        async def run(self):
            for n in (1, 2, 3):
                self._on_record(_record(n))
                # What an observer (or a Ctrl-C) would find on disk right now.
                seen_midmatch.append(len(load_records(log_path)))
            return MatchResult(
                winner=CFG.candidates[0],
                loser=CFG.candidates[1],
                draw=False,
                battles=[_record(1), _record(2), _record(3)],
            )

    monkeypatch.setattr(driver_mod, "Battle", FakeBattle)
    monkeypatch.setattr(driver_mod, "OrqGateway", lambda cfg: object())
    monkeypatch.setattr("orq_arena.report.write_report", lambda **kw: None)

    async def _no_prices(_gw):
        return {}

    monkeypatch.setattr("orq_arena.providers.models_list.fetch_price_map", _no_prices)

    from orq_arena.data.prompts import PromptItem

    await driver_mod.run_tournament(
        cfg=CFG,
        prompts=[PromptItem(text="p")],
        battle_log_path=str(log_path),
        events=asyncio.Queue(),
    )
    assert seen_midmatch == [1, 2, 3], "the log only grew once the match ended"


async def test_a_voided_round_keeps_whatever_text_arrived(monkeypatch):
    """A round that dies mid-stream is voided either way, but the half-written
    answer is the evidence for why. It used to be discarded."""
    from orq_arena.arena.battle import _generate_side

    class DyingGateway:
        async def stream_completion(self, **kw):
            yield ("text", "the first half")
            raise RuntimeError("connection reset")

    res = await _generate_side(
        gateway=DyingGateway(),
        candidate=CFG.candidates[0],
        prompt="p",
        default_max_tokens=64,
        events=asyncio.Queue(),
        match_id="M1",
        side="a",
    )
    assert res.error is not None
    assert res.text == "the first half"
