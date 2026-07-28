"""The worked transcripts in the docs have to come from the code, not a keyboard.

Two of them went stale silently and one was never real to begin with: a RUN PLAN
worst case of `$18.22` was hand-written as `projected + models`, forgetting the
replacement panel the example config configures, and was wrong by 3x; the
leaderboard's eight confidence intervals kept the numbers a 200-resample
bootstrap had produced after the bootstrap moved to 1000.

Both blocks are derived from the committed `examples/quickstart` run, so both are
checkable here with no network and no spend. What this pins is only the numbers a
reader would quote back: change the code and these fail, which is the point.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from orq_arena.config import load_config
from orq_arena.data.schemas import BattleRecord
from orq_arena.preflight import call_counts, cost_projection
from orq_arena.tournament.driver import config_from_manifest, read_manifest, rebuild_from_log

REPO = Path(__file__).resolve().parents[1]
QUICKSTART = REPO / "examples" / "quickstart"
LOG = QUICKSTART / "battles.jsonl"
DOCS = (REPO / "docs" / "cli.md", REPO / "docs" / "getting-started.md")


def recorded_prices() -> dict[str, tuple[float, float]]:
    """The catalog prices that run actually saw, off its own manifest.

    Not a live fetch: the point is that the documented table is reproducible
    offline and stays pinned to the run it claims to describe.
    """
    manifest = json.loads((QUICKSTART / "battles.run.json").read_text(encoding="utf-8"))
    pf = manifest["preflight"]
    cost = pf.get("cost_projection") or pf["cost_ceiling"]
    return {
        row["model_id"]: (row["price_in"], row["price_out"])
        for row in cost["rows"]
        if row["price_in"] is not None
    }


@pytest.fixture(scope="module")
def projection():
    cfg = load_config(str(QUICKSTART / "config.yaml"))
    from orq_arena.data.prompts import load_prompts

    prompts = load_prompts(str(REPO / "prompts" / "starter.jsonl"))
    return cost_projection(cfg, prompts, call_counts(cfg, prompts), recorded_prices())


@pytest.fixture(scope="module")
def rebuilt():
    records = [
        BattleRecord.model_validate_json(line)
        for line in LOG.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    manifest = read_manifest(LOG)
    cfg, _ = config_from_manifest(manifest)
    assert cfg is not None
    return rebuild_from_log(cfg, records, preflight=manifest.get("preflight"))


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_documented_spend_figures_are_the_ones_the_code_computes(doc, projection):
    """`$18.22` was arithmetic nobody ran. Both figures now have to be real."""
    text = doc.read_text(encoding="utf-8")
    projected = f"${projection.projected_usd:.2f}"
    worst = f"${projection.worst_case_usd:.2f}"
    assert projected in text, f"{doc.name} quotes no projected spend of {projected}"
    assert worst in text, f"{doc.name} quotes no worst case of {worst}"
    # The failure that shipped: worst case rendered as projected + models_usd,
    # which drops the replacement panel entirely.
    forgot_replacements = f"${projection.projected_usd + projection.models_usd:.2f}"
    assert forgot_replacements not in text, (
        f"{doc.name} still quotes {forgot_replacements}, the worst case with "
        "replacement judges left out"
    )


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_documented_leaderboard_matches_a_rebuild(doc, rebuilt):
    """Every ELO and interval in the Final Results block, against the real fit.

    The bootstrap is seeded, so a rebuild reproduces the bounds exactly; a doc
    row that disagrees is stale, not sampling noise.
    """
    elo, report = rebuilt
    text = doc.read_text(encoding="utf-8")
    ci = report["elo_ci"]
    # `│ 1 │ gemini-3.5-flash       │ 1374 │ 1184–2209 │ 86%  │`
    rows = re.findall(r"│\s*\d+\s*│\s*(\S+)\s*│\s*(-?\d+)\s*│\s*(\S+?)\s*│\s*\d+%\s*│", text)
    assert len(rows) == len(elo), (
        f"{doc.name}: expected {len(elo)} leaderboard rows, got {len(rows)}"
    )
    fmt = lambda v: "-∞" if v == float("-inf") else f"{v:.0f}"  # noqa: E731
    for name, shown_elo, shown_ci in rows:
        assert name in elo, f"{doc.name}: unknown model {name!r} in the leaderboard block"
        assert shown_elo == f"{elo[name]:.0f}", f"{doc.name}: {name} ELO is stale"
        lo, hi = ci[name]
        assert shown_ci == f"{fmt(lo)}–{fmt(hi)}", f"{doc.name}: {name} interval is stale"


def test_the_rejudge_round_count_is_the_log_s_own():
    """The block claimed 30 rounds for a log holding 140 judgeable ones."""
    from orq_arena.rejudge import load_records

    judgeable = len(load_records(str(LOG)))
    text = (REPO / "docs" / "cli.md").read_text(encoding="utf-8")
    assert f"re-judging {judgeable} rounds with panel:" in text
    assert f"re-judged {judgeable} rounds," in text
