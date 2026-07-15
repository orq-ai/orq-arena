"""The shipped demo fixture must keep parsing under the current event models.

_replay_fixture swallows parse errors silently, so a narrowed event field
would make demo rounds vanish without a trace. This guards that: every event
in the fixture parses, and the old HP/by fields it still carries are ignored,
not rejected.
"""

import json
from pathlib import Path

from orq_arena.tui.app import _event_from_dict

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "demo_tournament.json"


def test_every_demo_fixture_event_parses():
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert raw, "fixture is empty"
    for entry in raw:
        entry = dict(entry)
        entry.pop("_delay", None)
        _event_from_dict(entry)  # must not raise


def test_legacy_hp_fields_are_ignored_not_rejected():
    # A pre-eviction turn_resolved carried damage_dealt/hp_a/hp_b; parsing must
    # drop them rather than fail.
    ev = _event_from_dict({
        "type": "turn_resolved", "match_id": "M1", "round_number": 1,
        "majority": "A", "damage_dealt": 15, "loser_side": "b",
        "hp_a": 100, "hp_b": 85,
    })
    assert ev.majority == "A"
    assert not hasattr(ev, "hp_a")
