"""The worked transcripts in the docs have to come from the code, not a keyboard.

Two of them went stale silently and one was never real to begin with: a RUN PLAN
worst case of `$18.22` was hand-written as `projected + models`, forgetting the
replacement panel the example config configures, and was wrong by 3x; the
leaderboard's eight confidence intervals kept the numbers a 200-resample
bootstrap had produced after the bootstrap moved to 1000.

Everything checked here derives from the committed `examples/quickstart` run, so
it needs no network and spends nothing. What is pinned is every number a reader
would quote back, in *every* file that quotes it: the same figure living in three
docs is how the last drift survived a fix.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from orq_arena.config import load_config
from orq_arena.data.prompts import load_prompts
from orq_arena.data.schemas import load_records
from orq_arena.preflight import call_counts, cost_projection
from orq_arena.tournament.driver import config_from_manifest, read_manifest, rebuild_from_log

REPO = Path(__file__).resolve().parents[1]
QUICKSTART = REPO / "examples" / "quickstart"
LOG = QUICKSTART / "battles.jsonl"

# Every doc that quotes a spend figure. `examples/quickstart/README.md` was the
# one this test originally forgot, which is the whole failure mode.
SPEND_DOCS = (
    REPO / "docs" / "cli.md",
    REPO / "docs" / "getting-started.md",
    QUICKSTART / "README.md",
)
# The subset that reproduces the full Final Results table.
LADDER_DOCS = SPEND_DOCS[:2]


def recorded_prices() -> dict[str, tuple[float, float]]:
    """The catalog prices that run actually saw, off its own manifest.

    Not a live fetch: the documented table has to stay pinned to the run it
    claims to describe, and has to be checkable with no key present.
    """
    manifest = json.loads((QUICKSTART / "battles.run.json").read_text(encoding="utf-8"))
    pf = manifest["preflight"]
    # This run predates RES-1148, which renamed the manifest key along with the
    # concept: a ceiling that was never a ceiling became an honest projection.
    cost = pf.get("cost_projection") or pf["cost_ceiling"]
    return {
        row["model_id"]: (row["price_in"], row["price_out"])
        for row in cost["rows"]
        if row["price_in"] is not None
    }


@pytest.fixture(scope="module")
def projection():
    cfg = load_config(str(QUICKSTART / "config.yaml"))
    prompts = load_prompts(str(REPO / "prompts" / "starter.jsonl"))
    return cost_projection(cfg, prompts, call_counts(cfg, prompts), recorded_prices())


@pytest.fixture(scope="module")
def rebuilt():
    records = load_records(LOG)
    manifest = read_manifest(LOG)
    cfg, _ = config_from_manifest(manifest)
    assert cfg is not None
    elo, report = rebuild_from_log(cfg, records, preflight=manifest.get("preflight"))
    assert elo, "the committed log rebuilt to an empty field"
    return elo, report


@pytest.mark.parametrize("doc", SPEND_DOCS, ids=lambda p: p.name)
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


@pytest.mark.parametrize("doc", LADDER_DOCS, ids=lambda p: p.name)
def test_documented_run_plan_prices_every_row(doc, projection):
    """The per-model Cost column, not just the total underneath it.

    A row can go stale on its own: the header itself read `Ceiling` for a
    release after the code started rendering `Cost`.
    """
    text = doc.read_text(encoding="utf-8")
    for row in projection.rows:
        if row.usd is None or row.role == "replacement":
            continue  # `_print_run_plan` renders no replacement row (cli.py)
        assert f"${row.usd:.2f}" in text, f"{doc.name}: no Cost cell for {row.model_id}"


@pytest.mark.parametrize("doc", LADDER_DOCS, ids=lambda p: p.name)
def test_documented_leaderboard_matches_a_rebuild(doc, rebuilt):
    """Every ELO and interval in the Final Results block, against the real fit.

    The bootstrap is seeded, so a rebuild reproduces the bounds exactly; a doc
    row that disagrees is stale, not sampling noise.
    """
    elo, report = rebuilt
    text = doc.read_text(encoding="utf-8")
    ci = report["elo_ci"]
    # `│ 1 │ gemini-3.5-flash       │ 1374 │ 1184–2209 │ 86%  │`
    rows = re.findall(r"│\s*\d+\s*│\s*(\S+)\s*│\s*(-?\d+)\s*│\s*(\S+?)\s*│\s*(\d+)%\s*│", text)
    assert rows, f"{doc.name}: no Final Results block found at all"
    assert len(rows) == len(elo), (
        f"{doc.name}: expected {len(elo)} leaderboard rows, got {len(rows)}"
    )
    for name, shown_elo, shown_ci, _win in rows:
        assert name in elo, f"{doc.name}: unknown model {name!r} in the leaderboard block"
        assert shown_elo == f"{elo[name]:.0f}", f"{doc.name}: {name} ELO is stale"
        lo, hi = ci[name]
        assert shown_ci == f"{lo:.0f}–{hi:.0f}", f"{doc.name}: {name} interval is stale"


@pytest.mark.parametrize("doc", LADDER_DOCS, ids=lambda p: p.name)
def test_documented_jury_stats_match_the_rebuild(doc, rebuilt):
    """The one-line jury summary under the table drifts just as quietly."""
    _elo, report = rebuilt
    text = doc.read_text(encoding="utf-8")
    assert f"{report['mean_agreement']:.0%} mean agreement" in text
    pref = report["length_pref"]
    share = pref["longer_wins"] / pref["rounds"]
    assert (
        f"longer answer won {share:.0%} of decisive rounds "
        f"({pref['longer_wins']}/{pref['rounds']})" in text
    )
    # The pricing-out claim is licensed by the coefficient being identified;
    # if the gate ever closes on this run, the transcript must drop the claim.
    assert ("the report prices that preference out" in text) == (report["length_coef"] is not None)
    assert f"rounds: {report['rated_rounds']} rated" in text


def test_the_quickstart_readme_prose_quotes_the_real_run(rebuilt):
    """Prose, not a table, so the leaderboard regex above never sees it.

    Whitespace-insensitive: these sentences get rewrapped, and a rewrap is not
    a drift.
    """
    elo, report = rebuilt
    champion, rating = max(elo.items(), key=lambda kv: kv[1])
    words = " ".join((QUICKSTART / "README.md").read_text(encoding="utf-8").split())
    pref = report["length_pref"]
    sc = report["elo_style_controlled"]
    ci = report["length_coef_ci"]
    assert sc and ci, "the committed run stopped being length-identified; rewrite the README"
    sc_rank = sorted(sc, key=lambda k: -sc[k]).index(champion) + 1
    ordinal = {1: "1st", 2: "2nd", 3: "3rd"}.get(sc_rank, f"{sc_rank}th")
    for claim in (
        f"`{champion}` leads at {rating:.0f}",
        f"{report['rated_rounds']} rated rounds",
        f"{len(load_records(LOG))} rounds came back inconclusive",
        f"longer answer won {pref['longer_wins']} of {pref['rounds']} decisive rounds",
        f"coefficient is {report['length_coef']:+.1f}",
        f"lower bound {ci['lo']:.1f}",
        # The finding, not just the number: where the raw champion lands once
        # length is priced out.
        f"champion drops to {ordinal}",
    ):
        assert claim in words, f"quickstart README no longer says {claim!r}"


def test_the_rejudge_round_count_is_the_log_s_own():
    """The block claimed 30 rounds for a log holding 140 judgeable ones."""
    from orq_arena.rejudge import load_records as judgeable_records

    judgeable = len(judgeable_records(str(LOG)))
    text = (REPO / "docs" / "cli.md").read_text(encoding="utf-8")
    assert f"re-judging {judgeable} rounds with panel:" in text
    assert f"re-judged {judgeable} rounds," in text
