"""Single-file HTML run report.

One self-contained page per run, rendered from data the run already
produced (``battles.jsonl`` records, the final report dict, the manifest).
No server, no external assets; the file works from ``file://`` and can be
attached to a PR or linked from a post. Regenerable at any time with
``orq-arena report <log>``.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from evaluatorq.common.reports import esc as _e
from evaluatorq.common.reports import html_table, load_css, load_logo_svg, status_badge
from evaluatorq.common.reports import pct as _pct
from evaluatorq.pairwise_reports.sections import POSITION_BIAS_WARN

from .config import ArenaConfig
from .data.schemas import BattleRecord
from .judging import floor_abstained, judge_labels, vote_probabilities

if TYPE_CHECKING:  # driver imports this module at render time; keep it type-only
    from .tournament.driver import IdentitySource

# The evaluatorq report skin (report.css, embedded fonts and texture), so an
# arena report and an evaluatorq export read as one family and restyle together
# on upgrade. Two edits keep the page self-contained and in house style: the
# Google Fonts @import goes (Kurrent is embedded, Inter is only a fallback) and
# so do the comments. Every self-contained page here (report, annotate) uses it.
_BASE_CSS = (
    re.sub(r"@import url\([^)]*\);|/\*.*?\*/", "", load_css(), flags=re.S)
    # A/B side colours follow the evaluatorq pairwise vote chips.
    + ":root { --a: #3b6fd4; --b: #8257c5; --warn-ink: #8a6a00; --heat: 245 139 78; }"
)
# Inline SVG needs no namespace; dropping it keeps the pages free of URLs.
_LOGO = load_logo_svg().replace(' xmlns="http://www.w3.org/2000/svg"', "")

# Arena-only rules, in evaluatorq tokens. The pw-* rules (vote chips, round
# rows, position-bias bar) are copied from evaluatorq's pairwise export
# (pairwise_reports/export_html.py, _PAIRWISE_CSS), which keeps them private.
_ARENA_CSS = """
.hero .status-badge { margin: 4px 0 10px; }
.hero h1 { font-size: 28px; line-height: 1.25; margin: 0 0 10px; }
.lede { color: var(--gray-700); max-width: 66ch; margin: 0 0 6px; }
.note, .vnote { font-size: 13px; color: var(--gray-500); margin: 8px 2px 14px; }
.kpi-value .medal { font-size: .6em; vertical-align: middle; margin-left: 6px; }
.kpi-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tablewrap { overflow-x: auto; }
.tablewrap table { margin: 12px 0 8px; }
.tablewrap th, .tablewrap td { padding: 8px 10px; }
td.n, th.n { text-align: right; font-family: var(--mono); white-space: nowrap; }
.card svg { display: block; }
.ci-track { position: relative; height: 8px; border-radius: 4px; min-width: 110px; background: var(--gray-100); }
.ci-range { position: absolute; top: 0; height: 8px; border-radius: 4px; background: rgb(var(--heat) / .45); }
.ci-dot { position: absolute; top: -2px; width: 4px; height: 12px; border-radius: 2px; background: var(--slate); }
.name { font-weight: 600; white-space: nowrap; }
.think { font-size: 11px; color: var(--gray-500); }
.think.off { color: var(--warn-ink); border: 1px solid rgba(242, 182, 0, .45); border-radius: 5px; padding: 0 5px; }
.grid td, .grid th { text-align: center; padding: 7px 6px; }
.grid td.rowname { text-align: left; font-weight: 600; white-space: nowrap; }
.sideA { color: var(--a); font-weight: 600; } .sideB { color: var(--b); font-weight: 600; }
.sig.warn { color: var(--warn-ink); } .sig.good { color: var(--c-pass); }
.subhead { font-family: var(--mono); font-size: 12px; color: var(--gray-500); margin: 22px 2px 8px; }
.tally { display: flex; flex-wrap: wrap; gap: 8px 20px; margin: 4px 2px 10px; font-size: 14px; }
details.method { margin: 48px 0 0; }
details.method > summary { font-size: 22px; font-weight: 600; color: var(--slate); list-style: none;
  padding-bottom: 6px; border-bottom: 1px solid var(--gray-300); }
details.method > summary::-webkit-details-marker { display: none; }
details.method > summary::after { content: " ▸"; color: var(--gray-500); }
details.method[open] > summary::after { content: " ▾"; }
details.method h3 { margin: 22px 0 4px; }
details.method p { font-size: 14px; color: var(--gray-700); max-width: 74ch; }
.footer code { font-size: 11px; }
.pw-caption { opacity: .7; font-size: .9em; margin: 4px 0 12px; }
.pw-muted { opacity: .6; }
.pw-bias { display: inline-flex; align-items: center; gap: 8px; font-variant-numeric: tabular-nums; }
.pw-bias__track { width: 60px; height: 8px; background: rgba(127,127,127,.15); border-radius: 4px; overflow: hidden; }
.pw-bias__fill { display: block; height: 100%; background: #7f8c9a; }
.pw-bias__fill--warn { background: #d9534f; }
.pw-tag { font-size: .75em; padding: 1px 6px; border-radius: 10px; background: rgba(127,127,127,.18); margin-left: 6px; }
.pw-tag--flip { background: rgba(217,83,79,.18); }
.pw-chip { display: inline-block; min-width: 34px; text-align: center; padding: 1px 8px; margin-right: 4px;
  border-radius: 10px; font-size: .8em; background: rgba(127,127,127,.15); }
.pw-chip--a { background: rgba(59,111,212,.22); }
.pw-chip--b { background: rgba(130,87,197,.22); }
.pw-chip--tie { background: rgba(127,127,127,.2); }
.pw-chip--abstain { opacity: .5; }
.pw-chip--flip { outline: 1px dashed rgba(217,83,79,.6); }
.pw-split { margin-left: 8px; color: #d9534f; }
.pw-cmp { border: 1px solid rgba(127,127,127,.25); border-radius: 6px; margin: 6px 0; padding: 6px 10px; background: var(--surface); }
.pw-cmp summary { display: flex; align-items: flex-start; gap: 10px; cursor: pointer; font-weight: 400; color: var(--slate); }
.pw-cmp__idx { opacity: .6; width: 28px; font-variant-numeric: tabular-nums; }
.pw-cmp__q { flex: 1; min-width: 0; overflow-wrap: anywhere; }
.pw-cmp__pair { display: block; font-size: 12px; color: var(--gray-500); }
.pw-cmp__chips { white-space: nowrap; }
.pw-responses { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 12px 0; }
.pw-response h4 { margin: 0; }
.pw-response pre { white-space: pre-wrap; word-break: break-word; background: rgba(127,127,127,.08);
  padding: 8px; border-radius: 4px; margin: 4px 0 0; font-size: 12.5px; max-height: 28rem; overflow-y: auto; }
.pw-votes { list-style: none; padding: 0; margin: 8px 0 4px; }
.pw-vote { display: flex; flex-wrap: wrap; align-items: baseline; gap: 10px; padding: 6px 0; border-top: 1px solid rgba(127,127,127,.15); }
.pw-vote__model { width: 170px; font-weight: 600; flex: none; }
.pw-vote__why { flex: 1; opacity: .85; font-size: 13.5px; }
@media (max-width: 720px) { .pw-responses { grid-template-columns: 1fr; } .kpi-band { flex-wrap: wrap; } }
"""

_CSS = _BASE_CSS + _ARENA_CSS


def _ci_bar(lo: float, hi: float, point: float, floor: float, span: float) -> str:
    left = (lo - floor) / span * 100
    width = max((hi - lo) / span * 100, 0.5)
    dot = (point - floor) / span * 100
    return (
        f'<div class="ci-track"><div class="ci-range" style="left:{left:.1f}%;width:{width:.1f}%">'
        f'</div><div class="ci-dot" style="left:{dot:.1f}%"></div></div>'
    )


def _cost_lines(records, manifest, prices, alias=None, jury_measured=None):
    """(models_usd, jury_usd, unpriced_names) or None without prices.

    Model spend is exact (per-record attribution). Jury spend is
    ``jury_measured`` when the log priced every judge call, else an estimate
    at the panel's mean catalog rate from the panel's token total. ``alias``
    maps the short model names stored in records to the display names the
    manifest is keyed by.
    """
    if not prices:
        return None
    alias = alias or {}
    id_by_name = _ids_by_name(manifest)
    models_usd, unpriced = 0.0, set()
    j_in = j_out = 0
    for r in records:
        if r.error is not None:
            continue
        j_in += r.judge_tokens_in
        j_out += r.judge_tokens_out
        for side, tin, tout in (
            ("a", r.tokens_a_in, r.tokens_a_out),
            ("b", r.tokens_b_in, r.tokens_b_out),
        ):
            name, pr = _priced_side(r, side, alias, prices, id_by_name)
            if pr is None:
                unpriced.add(name)
            else:
                models_usd += tin * pr[0] / 1e6 + tout * pr[1] / 1e6
    if jury_measured is not None:
        return models_usd, jury_measured, sorted(unpriced)
    panel = [prices[j] for j in manifest.get("judges", []) if j in prices]
    unpriced.update(j for j in manifest.get("judges", []) if j not in prices)
    jury_usd = None
    if panel:
        mean_in = sum(x[0] for x in panel) / len(panel)
        mean_out = sum(x[1] for x in panel) / len(panel)
        jury_usd = j_in * mean_in / 1e6 + j_out * mean_out / 1e6
    return models_usd, jury_usd, sorted(unpriced)


def _win_rates(grid: dict, names: list[str]) -> dict[str, float]:
    """Rated-round win share per model from the win grid (ties are 0.5 in it)."""
    rates = {}
    for n in names:
        won = sum((grid.get(n) or {}).values())
        lost = sum((grid.get(m) or {}).get(n, 0.0) for m in names if m != n)
        rates[n] = won / (won + lost) if won + lost else 0.0
    return rates


def _ids_by_name(manifest) -> dict[str, str]:
    return {
        n: str(w.get("model") or "") if isinstance(w, dict) else ""
        for n, w in (manifest.get("candidates") or {}).items()
    }


def _priced_side(r, side, alias, prices, id_by_name):
    """``(display name, price pair or None)`` for one side of one record.

    v4 records carry the router id, which is what the catalog prices by; v3
    records only have a short name, so those route through the manifest's pool.
    """
    key = r.rating_key(side)
    name = alias.get(key, key)
    return name, prices.get(key if key in prices else id_by_name.get(name, ""))


def _per_model_cost(records, manifest, prices, alias=None) -> dict[str, float]:
    alias = alias or {}
    id_by_name = _ids_by_name(manifest)
    out: dict[str, float] = {}
    for r in records:
        if r.error is not None:
            continue
        for side, tin, tout in (
            ("a", r.tokens_a_in, r.tokens_a_out),
            ("b", r.tokens_b_in, r.tokens_b_out),
        ):
            name, pr = _priced_side(r, side, alias, prices, id_by_name)
            if pr is not None:
                out[name] = out.get(name, 0.0) + tin * pr[0] / 1e6 + tout * pr[1] / 1e6
    return out


def _fmt_usd(v: float) -> str:
    return f"${v:.2f}" if v >= 0.1 else f"${v:.3f}"


def _kpi(label: str, value: str, subtitle: str, status: str = "") -> str:
    """One evaluatorq KPI card; no status means a plain grey edge.

    evaluatorq's ``kpi_cards`` has no subtitle slot and escapes its value, so
    the markup is written out here with the same classes.
    """
    edge = f" kpi-card--{status}" if status else ""
    return (
        f"<div class='kpi-card{edge}'><div class='kpi-value'>{value}</div>"
        f"<div class='kpi-label'>{label}</div><div class='kpi-subtitle'>{subtitle}</div></div>"
    )


def _value_map_svg(points, champion: str, size_label: str = "average response length") -> str:
    """ELO vs cost (log x), dashed best-value frontier, size = avg out tokens.

    ELO on y (not win rate) so dot height agrees with the leaderboard rank in
    the dot: raw win rate ignores opponent strength and inverts rank order.
    points: (name, cost_usd, elo, win_rate, size) in leaderboard order.
    """
    import math

    if len(points) < 2:
        return ""
    xs = [math.log10(max(c, 1e-4)) for _, c, *_ in points]
    x0, x1 = min(xs), max(xs)
    span = (x1 - x0) or 1.0
    tmax = max(t for *_, t in points) or 1.0
    elos = [e for _, _, e, _, _ in points]
    # Pad the ELO range, then snap the axis to tick multiples.
    step = next((s for s in (50, 100, 200, 500, 1000) if (max(elos) - min(elos)) / s <= 6), 2000)
    e_lo = math.floor((min(elos) - step * 0.4) / step) * step
    e_hi = math.ceil((max(elos) + step * 0.4) / step) * step
    W, H, L, R, T, B = 720, 310, 70, 40, 30, 60

    def px(c):
        return L + (math.log10(max(c, 1e-4)) - x0) / span * (W - L - R)

    def py(e):
        return T + (1 - (e - e_lo) / (e_hi - e_lo)) * (H - T - B)

    frontier, best = [], float("-inf")
    for _name, c, e, _r, _t in sorted(points, key=lambda p: p[1]):
        if e > best:
            frontier.append((px(c), py(e)))
            best = e
    poly = " ".join(f"{x:.0f},{y:.0f}" for x, y in frontier)
    fx = {round(x) for x, _ in frontier}

    # Rank-in-dot labeling: numbers match the leaderboard, full detail on hover
    # and in the key below. Inline text labels collide at any interesting density.
    rank_of = {pt[0]: i for i, pt in enumerate(points, 1)}
    dots, key_rows = [], []
    for name, c, e, r, t in points:
        x, y = px(c), py(e)
        rad = max(9.0, 5 + 9 * (t / tmax))
        on_frontier = round(x) in fx
        fill = (
            "var(--clay)"
            if name == champion
            else ("var(--olive)" if on_frontier else "var(--gray-500)")
        )
        rk = rank_of[name]
        # Surface ring separates overlapping dots; dot fills are dark enough for
        # plain white digits (no outline) in both light and dark.
        dots.append(
            f"<circle cx='{x:.0f}' cy='{y:.0f}' r='{rad:.0f}' fill='{fill}' opacity='.9' "
            f"stroke='var(--surface)' stroke-width='1.5'>"
            f"<title>{_e(name)}: {_fmt_usd(c)}, ELO {e:.0f}, {r:.0%} win rate</title></circle>"
            f"<text x='{x:.0f}' y='{y + 3.5:.0f}' font-size='10' font-weight='700' fill='#fff' "
            f"text-anchor='middle' pointer-events='none'>{rk}</text>"
        )
        if rk > 3:
            # Non-podium dots: name only, tucked under the dot (cost/ELO live
            # in the key and the hover title). Clamped inside the frame.
            # ponytail: no collision avoidance; stagger if crowded pools overlap.
            nx = min(max(x, L + 60), W - R - 60)
            dots.append(
                f"<text x='{nx:.0f}' y='{y + rad + 12:.0f}' font-size='10' "
                f"fill='var(--gray-500)' text-anchor='middle' pointer-events='none'>{_e(name)}</text>"
            )
        else:
            # Podium labels: centered over their own dot, staggered upward by
            # rank, clamped inside the frame, with a leader line back to the
            # dot whenever the label had to move. No ambiguity about ownership.
            lx = min(max(x, L + 115), W - 120)
            ly = y - rad - 10 - (rk - 1) * 15
            leader = ""
            if abs(lx - x) > 4 or (y - rad - ly) > 20:
                leader = (
                    f"<line x1='{lx:.0f}' y1='{ly + 3:.0f}' x2='{x:.0f}' y2='{y - rad - 1:.0f}' "
                    f"stroke='var(--gray-500)' stroke-width='0.75' opacity='0.6'/>"
                )
            dots.append(
                leader + f"<text x='{lx:.0f}' y='{ly:.0f}' font-size='11' font-weight='700' "
                f"fill='var(--slate)' text-anchor='middle'>{_e(name)} "
                f"<tspan fill='var(--gray-500)' font-weight='400'>{_fmt_usd(c)} &middot; ELO {e:.0f}</tspan></text>"
            )
        star = " &#9733;" if on_frontier else ""
        key_rows.append(
            f"<span style='white-space:nowrap'><b>{rk}</b> {_e(name)} "
            f"<span style='color:var(--gray-500)'>{_fmt_usd(c)} &middot; ELO {e:.0f} &middot; {r:.0%}{star}</span></span>"
        )
    key = (
        "<p class='note' style='display:flex;flex-wrap:wrap;gap:4px 18px'>"
        + "".join(key_rows)
        + "</p>"
    )

    # Axis ticks: y at round ELO steps with faint gridlines; x at $ decades (log scale).
    y_ticks = "".join(
        f"<line x1='{L}' y1='{py(v):.0f}' x2='{W - R}' y2='{py(v):.0f}' "
        f"stroke='var(--gray-300)' stroke-width='{1 if v in (e_lo, e_hi) else 0.5}' "
        f"{'stroke-dasharray=2 3' if v not in (e_lo, e_hi) else ''}/>"
        f"<text x='{L - 8}' y='{py(v) + 4:.0f}' font-size='10' fill='var(--gray-500)' "
        f"text-anchor='end'>{v:.0f}</text>"
        for v in range(e_lo, e_hi + 1, step)
    )
    lo_dec = math.floor(x0)
    hi_dec = math.ceil(x1)
    x_ticks = ""
    for d in range(lo_dec, hi_dec + 1):
        if d < x0 - 0.05 or d > x1 + 0.05:
            continue
        tx = L + (d - x0) / span * (W - L - R)
        val = 10**d
        x_ticks += (
            f"<line x1='{tx:.0f}' y1='{H - B}' x2='{tx:.0f}' y2='{H - B + 5}' stroke='var(--gray-500)'/>"
            f"<text x='{tx:.0f}' y='{H - B + 17}' font-size='10' fill='var(--gray-500)' "
            f"text-anchor='middle'>{_fmt_usd(val)}</text>"
        )
    # Label the far-right extreme (the priciest model) so the right end of the
    # axis carries a number, mirroring the top ELO tick. Decade ticks stop at
    # the last whole $ power, which is usually left of the real max. Skip when a
    # decade already lands on the edge.
    if abs(x1 - round(x1)) > 0.03:
        x_ticks += (
            f"<line x1='{W - R}' y1='{H - B}' x2='{W - R}' y2='{H - B + 5}' stroke='var(--gray-500)'/>"
            f"<text x='{W - R}' y='{H - B + 17}' font-size='10' fill='var(--gray-500)' "
            f"text-anchor='end'>{_fmt_usd(10**x1)}</text>"
        )

    return f"""
<h2>Value map</h2>
<div class="card">
<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="ELO vs cost">
<line x1="{L}" y1="{H - B}" x2="{W - R}" y2="{H - B}" stroke="var(--gray-300)"/>
<line x1="{L}" y1="{T}" x2="{L}" y2="{H - B}" stroke="var(--gray-300)"/>
<text x="{L - 8}" y="{T - 10}" font-size="10" fill="var(--gray-500)" text-anchor="end">ELO</text>
{y_ticks}
{x_ticks}
<text x="{(L + W - R) // 2}" y="{H - 14}" font-size="11" fill="var(--gray-500)" text-anchor="middle">cost per model over the whole run (log scale)</text>
<polyline points="{poly}" fill="none" stroke="var(--clay)" stroke-width="1.5" stroke-dasharray="5 4"/>
{"".join(dots)}
</svg></div>
{key}
<p class="note">Dashed line: the best-value frontier (&#9733; in the key; no cheaper model rates
higher). Dot size is {size_label}; the champion is orange; hover any dot for cost, ELO,
and win rate. Win rate counts rated rounds only.</p>
"""


def _speed_stats(records, alias=None) -> list[tuple[str, float, float, float, float]]:
    """Per model: (avg tok/s, avg ttft s, avg out tokens, avg duration s).

    tok/s and duration are 0.0 on logs that predate duration capture.
    """
    alias = alias or {}
    agg: dict[str, list] = {}
    for r in records:
        if r.error is not None:
            continue
        for side, tout, ttft, dur in (
            ("a", r.tokens_a_out, r.ttft_a_ms, r.duration_a_ms),
            ("b", r.tokens_b_out, r.ttft_b_ms, r.duration_b_ms),
        ):
            key = r.rating_key(side)  # type: ignore[arg-type]
            name = alias.get(key, key)
            a = agg.setdefault(name, [0.0, 0, 0.0, 0, 0.0, 0, 0.0])
            if dur > 0 and tout:
                a[0] += tout / (dur / 1000)
                a[1] += 1
                a[6] += dur / 1000
            if ttft > 0:
                a[2] += ttft / 1000
                a[3] += 1
            a[4] += tout
            a[5] += 1
    out = []
    for name, (ts, tn, ft, fn, ot, on, ds) in agg.items():
        out.append(
            (
                name,
                ts / tn if tn else 0.0,
                ft / fn if fn else 0.0,
                ot / on if on else 0.0,
                ds / tn if tn else 0.0,
            )
        )
    return out


def _speed_svg(stats) -> str:
    """Horizontal bars: tok/s when the log has durations, else time to first token."""
    rows = [x for x in stats if x[1] > 0 or x[2] > 0]
    if len(rows) < 2:
        return ""
    # Only rendered when the log carries durations (owner call: a TTFT-only
    # fallback chart earned its deletion). Older logs simply skip the section.
    if not any(x[1] > 0 for x in rows):
        return ""
    rows.sort(key=lambda x: -x[1])
    vmax = max(x[1] for x in rows) or 1.0
    title = "Speed"
    note = (
        "Average tokens per second over the run's streamed responses; "
        "time to first token annotated."
    )
    W, L, RH = 720, 170, 26
    H = 24 + RH * len(rows) + 8
    parts = []
    for i, (name, tps, ttft, _ot, _dur) in enumerate(rows):
        y = 18 + i * RH
        val = tps
        width = max((val / vmax) * (W - L - 190), 3)
        label = f"{tps:.0f} tok/s &middot; ttft {ttft:.1f}s"
        op = 0.85 - 0.5 * (i / max(len(rows) - 1, 1))
        parts.append(
            f"<text x='{L - 8}' y='{y + 12}' font-size='10.5' fill='var(--gray-500)' text-anchor='end'>{_e(name)}</text>"
            f"<rect x='{L}' y='{y}' width='{width:.0f}' height='14' rx='4' fill='var(--olive)' opacity='{op:.2f}'/>"
            f"<text x='{L + width + 8:.0f}' y='{y + 12}' font-size='10.5' fill='var(--gray-500)'>{label}</text>"
        )
    return f"""
<h2>{title}</h2>
<div class="card">
<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="{title} per model">
{"".join(parts)}
</svg></div>
<p class="note">{note}</p>
"""


_ROUNDS_CAP = 200  # a 16-model run would otherwise be tens of MB


def _clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n].rstrip() + "…"


def _vote_chip(v: dict, label: str) -> str:
    """The judge's pick as an evaluatorq vote chip; a dot when it abstained."""
    flip = " pw-chip--flip" if v.get("flipped") else ""
    choice = v.get("vote")
    if choice is None:
        return f"<span class='pw-chip pw-chip--abstain{flip}' title='{_e(label)} abstained'>&middot;</span>"
    tone = {"A": "a", "B": "b"}.get(choice, "tie")
    return f"<span class='pw-chip pw-chip--{tone}{flip}' title='{_e(label)}'>{_e(choice)}</span>"


def _rounds_html(judged, alias, labels, floor) -> str:
    """One expandable row per judged round: the panel's chips, then both answers and every vote."""
    if not judged:
        return ""
    rows = []
    for i, r in enumerate(judged[:_ROUNDS_CAP], 1):
        name_a = alias.get(r.rating_key("a"), r.model_a)
        name_b = alias.get(r.rating_key("b"), r.model_b)
        verdict = r.majority_verdict
        badge = {
            "A": (f"{name_a} wins", "pass"),
            "B": (f"{name_b} wins", "pass"),
            "tie": ("tie", "neutral"),
        }.get(verdict, ("inconclusive", "warn"))
        picks = {v.get("vote") for v in r.judge_votes if v.get("vote")}
        split = (
            "<span class='pw-split' title='the panel split or could not decide'>⚠</span>"
            if len(picks) > 1 or verdict == "inconclusive"
            else ""
        )
        chips = "".join(
            _vote_chip(v, labels.get(v.get("model"), v.get("model", ""))) for v in r.judge_votes
        )
        question = _clip(r.prompt_text, 300)
        full_prompt = f"<pre>{_e(r.prompt_text)}</pre>" if question != r.prompt_text else ""
        votes = []
        for v in r.judge_votes:
            label = labels.get(v.get("model"), v.get("model", ""))
            tags = "<span class='pw-tag pw-tag--flip'>flipped</span>" if v.get("flipped") else ""
            tags += "<span class='pw-tag'>under floor</span>" if floor_abstained(v, floor) else ""
            tags += "<span class='pw-tag'>stand-in</span>" if v.get("replacement") else ""
            probs = vote_probabilities(v)
            why = (
                " &middot; ".join(f"{k} {probs[k]:.0%}" for k in ("A", "B", "tie"))
                if probs
                else _e(_clip(v.get("explanation") or "", 400))
            )
            votes.append(
                f"<li class='pw-vote'><span class='pw-vote__model'>{_e(label)}</span>"
                f"{_vote_chip(v, label)}{tags}<span class='pw-vote__why'>{why}</span></li>"
            )
        rows.append(
            f"<details class='pw-cmp'><summary><span class='pw-cmp__idx'>{i}</span>"
            f"<span class='pw-cmp__q'>{_e(question)}<span class='pw-cmp__pair'>"
            f"<span class='sideA'>A</span> {_e(name_a)} vs <span class='sideB'>B</span> "
            f"{_e(name_b)}</span></span>{status_badge(*badge)}"
            f"<span class='pw-cmp__chips'>{chips}</span>{split}</summary>{full_prompt}"
            f"<div class='pw-responses'><div class='pw-response'><h4><span class='sideA'>A</span> "
            f"{_e(name_a)}</h4><pre>{_e(r.response_a)}</pre></div><div class='pw-response'><h4>"
            f"<span class='sideB'>B</span> {_e(name_b)}</h4><pre>{_e(r.response_b)}</pre></div></div>"
            f"<ul class='pw-votes'>{''.join(votes)}</ul></details>"
        )
    cap = (
        f"<p class='note'>Showing the first {_ROUNDS_CAP} of {len(judged)} judged rounds. To page "
        f"through all of them, run with <code>orq-arena run --tui</code> and press <b>B</b> on the "
        f"final leaderboard to open the battle browser.</p>"
        if len(judged) > _ROUNDS_CAP
        else ""
    )
    return (
        "<h2>Rounds</h2><p class='note'>Every judged round with each judge&#39;s pick: A, B or tie; "
        "a dot means the judge abstained, a dashed outline that it flipped when the sides were "
        "swapped, and &#9888; that the panel split. Open a round to read both answers and every "
        "vote.</p>" + "".join(rows) + cap
    )


def _empty_report_html(manifest: dict[str, Any], n_records: int) -> str:
    """Minimal valid page when no models were rated (empty pool / all voided)."""
    bench_id = _e(manifest.get("tournament_id", ""))
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>orq-arena report &middot; {bench_id}</title>
<style>{_CSS}</style></head><body><div class="container">
<header class="hero"><div class="report-brand-logo">{_LOGO}</div>
<p class="meta">{bench_id} &middot; ORQ-ARENA RUN</p>
{status_badge("⚠ NO RATED MODELS", "warn")}
<h1>Nothing to rank.</h1>
<p class="lede">This run produced no rated models: all {n_records} rounds errored, or no
candidates were configured. Check the candidates in the YAML and the run log, then re-run.</p></header>
</div></body></html>
"""


def build_report_html(
    *,
    cfg: ArenaConfig,
    records: list[BattleRecord],
    elo: dict[str, float],
    report: dict[str, Any],
    manifest: dict[str, Any],
    prices: dict[str, tuple[float, float]] | None = None,
    identity_source: IdentitySource = "manifest",
) -> str:
    """Render the run report page as a self-contained HTML string.

    ``identity_source`` says where the model names, judge panel and reasoning
    flags came from: the run's manifest, or a YAML that may have drifted since
    (``"config"``), which the page then discloses rather than the console only.
    """
    judged = [r for r in records if r.error is None]
    voids = len(records) - len(judged)
    verdicts = {"A": 0, "B": 0, "tie": 0, "inconclusive": 0}
    for r in judged:
        verdicts[r.majority_verdict] = verdicts.get(r.majority_verdict, 0) + 1
    decisive = verdicts["A"] + verdicts["B"]
    rated = report.get("rated_rounds", decisive + verdicts["tie"])

    ranked = sorted(elo.items(), key=lambda kv: kv[1], reverse=True)
    if not ranked:
        return _empty_report_html(manifest, len(records))
    champion, champ_elo = ranked[0]
    ci: dict[str, tuple[float, float]] = {
        k: tuple(v) for k, v in (report.get("elo_ci") or {}).items()
    }
    thinking = report.get("thinking") or {}
    thinking_off = report.get("thinking_off") or {}
    verbosity = report.get("verbosity") or {}
    elo_sc = report.get("elo_style_controlled") or {}
    length_coef = report.get("length_coef")

    # Verdict hero: does the top spot actually beat the runner-up? That is a
    # question about their difference, bootstrapped per resample. Two marginal
    # intervals overlapping would say nothing: they share the anchoring and move
    # together, so overlap is routine even for a lead that never reverses.
    # None when there's no runner-up, or a run recorded before this was measured.
    # Three states, not two. A run recorded before this was measured must not
    # be described as unresolved: nothing was measured, so nothing is claimed.
    top_diff = report.get("top_difference") or None
    top_separated: bool | None = top_diff["separated"] if top_diff else None

    fleiss = report.get("fleiss") or {}
    agreement = report.get("mean_agreement")

    # Judge/contestant family overlap: a self-preference caveat the run recorded
    # at preflight. Surfaced as a Confidence-stats row so the forwarded report
    # carries it too (see signal_rows below).
    family_overlaps = (manifest.get("preflight") or {}).get("family_overlaps") or []

    started = manifest.get("started_at")
    finished = manifest.get("finished_at") or (max((r.timestamp for r in records), default=None))
    duration = ""
    if started and finished and finished > started + 1:
        duration = f"{(finished - started) / 60:.1f} min"
    datestr = time.strftime("%Y-%m-%d %H:%M", time.localtime(started)) if started else ""

    # ELO ladder with CI bars on a shared scale.
    # Drawing scale only: clip runaway bootstrap tails (the BT clamp can put a
    # cratered model's lower bound at -3000, which would squeeze every other
    # bar into a corner). Exact bounds stay in the text column and tooltip.
    points = [e0 for _, e0 in ranked]
    all_lo = [max(ci.get(n, (e0, e0))[0], min(points) - 350) for n, e0 in ranked]
    all_hi = [min(ci.get(n, (e0, e0))[1], max(points) + 350) for n, e0 in ranked]
    floor, ceil = min(all_lo), max(all_hi)
    span = max(ceil - floor, 1.0)
    medals = ("&#129351;", "&#129352;", "&#129353;")  # gold/silver/bronze, reused by the hero
    ladder_rows = []
    for i, (name, e0) in enumerate(ranked, 1):
        lo, hi = ci.get(name, (e0, e0))
        dlo, dhi = max(lo, floor), min(hi, ceil)
        if thinking.get(name):
            think = ' <span class="think">thinking</span>'
        elif thinking_off.get(name):
            think = ' <span class="think off">thinking off</span>'
        else:
            think = ""
        tok = verbosity.get(name)
        sc_cell = f"<td class='n'>{elo_sc[name]:.0f}</td>" if name in elo_sc else ""
        rank = medals[i - 1] if i <= 3 else str(i)
        # BT strength -> 0 floors the rating at 400*log10(1e-10)+1000 = -3000; that
        # bound is really -inf (model won ~nothing), so show it as such, not the artifact.
        lo_txt = "&minus;&infin;" if lo <= -2900 else f"{lo:.0f}"
        ladder_rows.append(
            f"<tr><td class='n'>{rank}</td><td class='name'>{_e(name)}{think}</td>"
            f"<td class='n'>{e0:.0f}</td><td class='n'>{lo_txt}&ndash;{hi:.0f}</td>"
            f"<td title='{lo:.0f} to {hi:.0f}'>{_ci_bar(dlo, dhi, e0, floor, span)}</td>"
            f"{sc_cell}"
            f"<td class='n'>{'' if tok is None else f'{tok:.0f}'}</td></tr>"
        )

    # Win grid: full names on rows, rank numbers on columns (no truncated-name collisions).
    grid = report.get("win_grid") or {}
    order = [n for n, _ in ranked]
    head = "".join(f"<th class='n'>{i}</th>" for i in range(1, len(order) + 1))
    vmax = max((v for row in grid.values() for v in (row or {}).values()), default=0.0)
    grid_rows = []
    for i, a in enumerate(order, 1):
        cells = []
        for b in order:
            if a == b:
                cells.append("<td>&middot;</td>")
            else:
                v = (grid.get(a) or {}).get(b, 0.0)
                # Heat: single-hue intensity so the dominance triangle reads at a glance.
                # Token-driven rgb so the heat re-tunes on the dark surface.
                alpha = 0.0 if not v or not vmax else 0.10 + 0.45 * (v / vmax)
                style = f" style='background:rgb(var(--heat) / {alpha:.2f})'" if alpha else ""
                cells.append(f"<td{style} title='{_e(a)} beat {_e(b)} {v:g}&times;'>{v:g}</td>")
        grid_rows.append(f"<tr><td class='rowname'>{i}. {_e(a)}</td>{''.join(cells)}</tr>")

    # Jury room, in the columns of evaluatorq's pairwise export. Labels come
    # from the whole panel, so two judges sharing a short name never share a row.
    decisions = cfg.judge_api == "decisions"
    jury = report.get("jury") or {}
    per_judge = jury.get("per_judge", [])
    panel_ids = list(manifest.get("judges", cfg.judges))
    labels = judge_labels([*panel_ids, *(str(j.get("model", "")) for j in per_judge)])
    all_votes = [v for r in judged for v in r.judge_votes]
    stand_ins = {v.get("model") for v in all_votes if v.get("replacement")}
    # A flip rate means something only for a judge that saw both seat orders.
    swapped = {v.get("model") for v in all_votes if v.get("completed")}
    # Mean confidence: how sure a decision judge was of its leading option.
    # Prompted judges carry no probabilities, so LLM runs never grow the column.
    conf: dict[str, list[float]] = {}
    # Over every vote that carries probabilities, abstained and flipped ones too,
    # so a judge that contradicts itself does not read as confident.
    for v in all_votes:
        probs = vote_probabilities(v)
        if probs is not None:
            conf.setdefault(str(v.get("model", "")), []).append(max(probs.values()))
    jury_head = ["Judge", "A rate", "B rate", "Tie rate", "Flip rate"]
    jury_head += ["Mean confidence"] if conf else []
    jury_rows = []
    for j in per_judge:
        model = str(j.get("model", ""))
        bias = j.get("position_bias")
        if not cfg.judge_swap:
            flip = "n/a (swap off)"
        elif model not in swapped or bias is None:
            flip = "<span class='pw-muted' title='never saw both seat orders of a pair'>n/a</span>"
        else:
            warn = " pw-bias__fill--warn" if bias >= POSITION_BIAS_WARN else ""
            flip = (
                f"<span class='pw-bias'><span class='pw-bias__track'><span class='pw-bias__fill"
                f"{warn}' style='width:{min(bias, 1.0) * 100:.0f}%'></span></span>"
                f"{_pct(bias)}</span>"
            )
        tag = " <span class='pw-tag'>stand-in</span>" if model in stand_ins else ""
        row = [
            f"<span class='name'>{_e(labels.get(model, model))}</span>{tag}",
            _pct(j.get("a_rate")),
            _pct(j.get("b_rate")),
            _pct(j.get("tie_rate")),
            flip,
        ]
        if conf:
            ps = conf.get(model)
            row.append(f"{sum(ps) / len(ps):.2f}" if ps else "n/a")
        jury_rows.append(row)
    if not cfg.judge_swap:
        seat_note = (
            "This run used a single seat order, so position bias (the flip rate) was not measured."
        )
    elif per_judge and not swapped:
        seat_note = (
            "No pair completed both seat orders, so position bias (the flip rate) could not be "
            "measured for this run despite swapping being enabled."
        )
    else:
        seat_note = (
            "Each judge sees every pair in both seat orders; a judge that contradicts itself "
            "abstains (the flip rate) and abstentions never become verdicts; a high flip rate "
            "flags a judge to distrust."
        )
    if conf:
        seat_note += (
            " Mean confidence is how sure a judge was of its leading option, averaged over "
            "all its votes, including abstained ones (1.00 = certain)."
        )
    abstain_floor = cfg.judge_abstain_below
    if abstain_floor is not None and all_votes:
        n_floor = sum(floor_abstained(v, abstain_floor) for v in all_votes)
        seat_note += (
            f" {n_floor} vote{'' if n_floor == 1 else 's'} ({n_floor / len(all_votes):.0%}) "
            f"abstained because the top option fell under the {abstain_floor:.2f} floor."
        )
    cohen = report.get("cohen") or {}
    _raw_ks = [v.get("kappa") if isinstance(v, dict) else v for v in cohen.values()]
    _ks = [k for k in _raw_ks if isinstance(k, (int, float))]
    cohen_range = (
        f"{min(_ks):.2f} to {max(_ks):.2f}" if len(_ks) > 1 else (f"{_ks[0]:.2f}" if _ks else "")
    )

    # Rounds and category accounting.
    tok = report.get("tokens") or {}
    w_in = tok.get("models_in", 0)
    w_out = tok.get("models_out", 0)
    j_in, j_out = tok.get("judges_in", 0), tok.get("judges_out", 0)
    total_tok = w_in + w_out + j_in + j_out
    jury_share = f"{(j_in + j_out) / total_tok:.0%}" if total_tok else "n/a"

    # Flag a high inconclusive share: those rounds carried no signal, so a run
    # that's mostly inconclusive is weak evidence and shouldn't read as neutral.
    inc = verdicts["inconclusive"]
    inc_cls = " warn" if len(records) and inc / len(records) > 0.30 else ""

    # Confidence & methodology: one aligned row per run-confidence signal
    # (reads far better than ragged pills). (label, reading html, td class).
    signal_rows: list[tuple[str, str, str]] = []
    # This page gets forwarded, so a caveat folded into a closed drawer is a
    # caveat nobody reads: an unverified identity opens the drawer it sits in.
    conf_open = ""
    if identity_source == "config":
        conf_open = " open"
        signal_rows.append(
            (
                "Run identity",
                "model names, judge panel and reasoning flags were rebuilt from a config file, "
                "not from the run's own manifest, so they may have drifted since the run",
                " warn",
            )
        )
    if family_overlaps:
        signal_rows.append(
            (
                "Judge/contestant family overlap",
                f"<b>{_e(', '.join(family_overlaps))}</b> share a provider family with "
                "the pool; self-preference bias is not corrected by seat swapping",
                " warn",
            )
        )
    if top_diff:
        # The names the difference was measured between, never a separately
        # derived ranking that could disagree with it.
        champ_name, runner_name = top_diff["champion"], top_diff["runner_up"]
        rate = f"{top_diff['win_rate']:.0%}"
        if top_separated:
            signal_rows.append(
                (
                    "Top-spot separation",
                    f"the lead over {_e(runner_name)} is <b>{top_diff['lo']:.0f} to "
                    f"{top_diff['hi']:.0f}</b> rating points (95% of resamples), and holds in "
                    f"{rate} of them",
                    " good",
                )
            )
        else:
            # Not "tied": a run this size simply cannot resolve the gap either
            # way, and the resample share says which way it leans meanwhile.
            signal_rows.append(
                (
                    "Top-spot separation",
                    f"not resolved at this sample size: the gap to {_e(runner_name)} spans "
                    f"<b>{top_diff['lo']:.0f} to {top_diff['hi']:.0f}</b> rating points, with "
                    f"{_e(champ_name)} ahead in {rate} of resamples",
                    " warn",
                )
            )
    if fleiss.get("kappa") is not None:
        signal_rows.append(
            (
                "How much the jury agreed",
                f"<b>{fleiss['kappa']} of 1</b> ({_e(fleiss.get('label', ''))}, 1 = every judge "
                f"agreed), across {fleiss.get('rounds_used', '?')}/"
                f"{fleiss.get('rounds_total', '?')} full-panel rounds",
                "",
            )
        )
    # Descriptive claim first: a count, immune to how any estimator behaves.
    # The modelled coefficient joins it only when identified (fit converged,
    # bootstrap interval excluding 0), which is also when the length-adj.
    # column exists. Length means characters throughout.
    length_pref = report.get("length_pref")
    if length_pref and length_pref["rounds"]:
        rounds_n = length_pref["rounds"]
        longer = length_pref["longer_wins"]
        lean_word, lean_wins = (
            ("longer", longer) if longer * 2 >= rounds_n else ("shorter", rounds_n - longer)
        )
        detail = (
            f"the <b>{lean_word}</b> answer (in characters) won "
            f"<b>{lean_wins / rounds_n:.0%}</b> of decisive rounds "
            f"({lean_wins}/{rounds_n})"
        )
        if length_coef is not None:
            ci_d = report.get("length_coef_ci") or {}
            lo_t = "unbounded" if ci_d.get("lo") is None else f"{ci_d['lo']:+.1f}"
            hi_t = "unbounded" if ci_d.get("hi") is None else f"{ci_d['hi']:+.1f}"
            sep = ci_d.get("separated", 0)
            sep_note = f"; {sep}/{ci_d.get('draws', '?')} resamples separated" if sep else ""
            detail += (
                f"; modelled length coefficient <b>{length_coef:+.1f}</b> "
                f"(95% CI {lo_t} to {hi_t}{sep_note}), priced out in the "
                f"length-adj. column"
            )
        else:
            detail += (
                "; the modelled length coefficient is not statistically "
                "identified on this run (its interval reaches 0, or the fit "
                "has no finite estimate), so no length-adjusted column is shown"
            )
        signal_rows.append(("Did length sway the jury", detail, ""))
    signal_rows.append(("Judges agreeing on decisive rounds", f"<b>{_pct(agreement)}</b>", ""))
    signal_rows.append(("Jury share of tokens used", f"<b>{jury_share}</b>", ""))
    signals_table = html_table(
        ["Signal", "Reading"],
        [
            [f"<span class='name'>{lbl}</span>", f"<span class='sig{c}'>{txt}</span>"]
            for lbl, txt, c in signal_rows
        ],
    )

    panel = ", ".join(labels[j] for j in panel_ids) + (" (decision models)" if decisions else "")

    # Records store short model names; elo/manifest/report are keyed by display
    # name (name). Identical unless the config sets custom names.
    alias = report.get("by_model_names") or {w.short_model: w.name for w in cfg.candidates}
    stats_all = _speed_stats(records, alias)
    speed = _speed_svg(stats_all)
    dur_by = {n: d for n, _t, _f, _o, d in stats_all}

    # Fairness disclosure: name any model that ran with reasoning explicitly
    # switched off, so its rating isn't read as a like-for-like result.
    off_names = [n for n in order if thinking_off.get(n)]
    off_note = (
        f' <span class="sig warn">Not a like-for-like field:</span> '
        f"{', '.join(_e(n) for n in off_names)} ran with vendor reasoning explicitly "
        f'disabled (tagged <span class="think off">thinking off</span> above); their '
        f"scores sit below what the same model would earn reasoning freely."
        if off_names
        else ""
    )

    value_map = ""
    if prices:
        per_cost = _per_model_cost(records, manifest, prices, alias)
        rates = _win_rates(grid, order)
        use_dur = any(dur_by.get(n, 0.0) > 0 for n in order)
        pts = [
            (
                n,
                per_cost[n],
                elo.get(n, 0.0),
                rates.get(n, 0.0),
                dur_by.get(n, 0.0) if use_dur else (verbosity.get(n) or 0.0),
            )
            for n in order
            if n in per_cost and per_cost[n] > 0
        ]
        value_map = _value_map_svg(
            pts,
            champion,
            size_label=("average time to answer" if use_dur else "average response length"),
        )

    rates_all = _win_rates(grid, order)
    per_cost_all = _per_model_cost(records, manifest, prices, alias) if prices else {}

    # Tokens & cost as three cards: models spend, jury spend, aggregated total.
    # Without catalog prices there's no cost story, so cards fall back to tokens.
    # Jury spend is exact when the log priced every judge call (v5 logs, either
    # judge_api), else estimated; the cards branch on that, not on the mode.
    jury_measured = report.get("judge_cost_usd")
    rounds_judged = [r for r in judged if r.judge_votes]
    if jury_measured is None and rounds_judged:
        if all(r.judge_cost_usd is not None for r in rounds_judged):
            jury_measured = sum(r.judge_cost_usd or 0.0 for r in rounds_judged)
    cost = _cost_lines(records, manifest, prices, alias, jury_measured)
    cost_note = ""
    if cost:
        w_usd, j_usd, unpriced = cost
        total = w_usd + (j_usd or 0.0)
        if jury_measured is not None:
            j_card = _kpi(
                "Jury", _fmt_usd(j_usd), f"{j_in:,} in &middot; {j_out:,} out &middot; measured"
            )
            t_card = _kpi("Total", f"${total:,.2f}", f"jury {jury_share} of tokens", "neutral")
            spend = (
                "Model and jury spend are exact: jury cost is what each judge call was priced at."
            )
        else:
            j_big = f"&asymp; ${j_usd:,.2f}" if j_usd is not None else "n/a"
            j_card = _kpi("Jury", j_big, f"{j_in:,} in &middot; {j_out:,} out &middot; estimated")
            t_card = _kpi(
                "Estimated total",
                f"&asymp; ${total:,.2f}",
                f"jury {jury_share} of tokens",
                "neutral",
            )
            spend = (
                "Model spend is exact (per-model catalog rates); jury spend is estimated at the "
                "panel's mean rate because the log stores the panel's token total, not per-judge splits."
            )
        models_card = _kpi(
            "Models", f"${w_usd:,.2f}", f"{w_in:,} in &middot; {w_out:,} out &middot; exact"
        )
        cost_cards = f"<div class='kpi-band'>{models_card}{j_card}{t_card}</div>"
        excluded = (
            " Unpriced in the catalog and excluded: " + ", ".join(unpriced) + "."
            if unpriced
            else ""
        )
        cost_note = f"<p class='note'>{spend}{excluded}</p>"
    else:
        cost_cards = (
            "<div class='kpi-band'>"
            + _kpi(
                "Models", f"{w_in + w_out:,}", f"{w_in:,} in &middot; {w_out:,} out &middot; tokens"
            )
            + _kpi(
                "Jury", f"{j_in + j_out:,}", f"{j_in:,} in &middot; {j_out:,} out &middot; tokens"
            )
            + "</div>"
        )

    # Pragmatic verdict banner (the auto-router dashboard treatment): one
    # actionable sentence, a plain-words explainer, two large KPIs.
    champ_rate = rates_all.get(champion, 0.0)
    runner_name = ranked[1][0] if len(ranked) > 1 else ""
    separated = top_separated is True
    if len(ranked) == 1:
        headline = f"{_e(champion)} ran unopposed: nothing to rank."
        expl = (
            "A benchmark needs at least two candidates to produce a ranking. Add "
            "competitors to get a verdict."
        )
    elif rated == 0:
        headline = "No decisive rounds: nothing to rank yet."
        expl = (
            f"All {len(records)} rounds were inconclusive or errored, so no model earned a "
            f"rated win. Re-run with more prompts or a decisive jury to separate the field."
        )
    elif separated:
        headline = (
            f"Adopt {_e(champion)}: wins {champ_rate:.0%} of rated rounds, "
            f"and the lead over {_e(runner_name)} holds across resamples."
        )
        expl = (
            f"{_e(champion)} beat every other model in this pool on your prompts and its lead "
            f"over {_e(runner_name)} exceeds the uncertainty of a run this size."
        )
    elif top_diff:
        # Unresolved is not tied. The models may well differ; this run is too
        # small to say. Report which way it leans and how often, and let the
        # reader decide whether to spend more rounds or pick on cost.
        lean = f"{top_diff['win_rate']:.0%}"
        headline = (
            f"{_e(champion)} leads {_e(runner_name)}, but this run is too small to "
            f"call it: decide on cost and speed, or run more rounds."
        )
        expl = (
            f"{_e(champion)} has the best rating and stays ahead of {_e(runner_name)} in "
            f"{lean} of resamples, but at {len(records)} rounds the gap could still be either "
            f"way. That is not evidence they are equal, only that this run cannot separate "
            f"them. The value map below breaks the deadlock on cost; more rounds would settle "
            f"it on quality."
        )
    else:
        # Nothing was measured (a run recorded before separation was computed),
        # so the page claims nothing either way rather than inventing a verdict.
        headline = f"{_e(champion)} has the best rating in this pool."
        expl = (
            f"This run predates the separation check, so whether the gap to {_e(runner_name)} "
            f"is real was never measured. Regenerate the report from the battle log to find "
            f"out: <code>orq-arena report &lt;log&gt;</code>."
        )
    if separated:
        status = status_badge("✓ TOP SPOT SEPARATED", "pass")
    elif top_diff:
        status = status_badge("⚠ TOP SPOT NOT RESOLVED AT THIS SIZE", "warn")
    else:
        status = status_badge("SEPARATION NOT MEASURED", "neutral")
    top3 = []
    for i, (nm, e0) in enumerate(ranked[:3]):
        # ELO is the value (the ranking axis); win share and spend ride below.
        sub = f"ELO &middot; {rates_all.get(nm, 0.0):.0%} win share"
        if nm in per_cost_all:
            sub += f" &middot; {_fmt_usd(per_cost_all[nm])}"
        edge = ("pass" if separated else "warn") if i == 0 else ""
        top3.append(_kpi(_e(nm), f"{e0:.0f}<span class='medal'>{medals[i]}</span>", sub, edge))
    # Reconcile the common confusion when a lower-ranked card shows a higher
    # win share than the model above it (win share ignores opponent strength;
    # ELO doesn't). Only shown when that inversion is actually on the card.
    shown = ranked[:3]
    inversion = any(
        rates_all.get(shown[j][0], 0.0) > rates_all.get(shown[i][0], 0.0)
        for i in range(len(shown))
        for j in range(i + 1, len(shown))
    )
    winshare_note = (
        "<p class='vnote'>Win share counts every rated round equally; ELO weights "
        "opponent strength and head-to-head results, so a model can post a "
        "higher win share yet rank lower.</p>"
        if inversion
        else ""
    )

    bench_id = _e(manifest.get("tournament_id", ""))

    ds = manifest.get("dataset") or {}
    dataset_frag = ""
    if ds.get("id"):
        label = _e(ds.get("name") or ds["id"])
        dataset_frag = (
            f"dataset <a href='{_e(ds['url'])}'>{label}</a> &middot; "
            if ds.get("url")
            else f"dataset {label} &middot; "
        )

    judges_meta = f"{len(panel_ids)} JUDGES{' (DECISION MODELS)' if decisions else ''}"
    swap_meta = "SEAT SWAP ON" if cfg.judge_swap else "SEAT SWAP OFF"
    seat_meth = (
        "Every judge scores each pair in both seat orders; a judge that contradicts itself between "
        "orders abstains (the flip rate), and abstentions never become verdicts."
        if cfg.judge_swap
        else "Every judge scores each pair in one seat order, so self-contradiction (the flip rate) "
        "is not measured."
    )
    decision_meth = (
        " Each judge answers one choice question (A, B or tie) through the orq Decisions API and "
        "returns a probability per option; the vote is the most probable option. Native decision "
        "models report calibrated probabilities; emulated chat models report their own estimate."
        if decisions
        else ""
    )
    cost_meth = (
        "Model and jury spend are exact: jury cost is what each judge call was priced at."
        if jury_measured is not None
        else "Model spend is exact (per-model catalog rates). Jury spend is estimated (&asymp;) at "
        "the panel&#39;s mean rate, because the log stores the panel&#39;s token total, not "
        "per-judge splits. Models unpriced in the catalog are excluded from the estimate."
    )
    via = (
        "Every verdict via the orq.ai Decisions API"
        if decisions
        else "Every verdict via evaluatorq&#39;s pairwise jury"
    )
    rounds = _rounds_html(judged, alias, labels, abstain_floor)

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>orq-arena report &middot; {bench_id}</title>
<style>{_CSS}</style></head><body><div class="container">

<header class="hero">
<div class="report-brand-logo">{_LOGO}</div>
<p class="meta">{dataset_frag}{bench_id} &middot; {datestr} &middot; {len(ranked)} MODELS &middot; {len(records)} ROUNDS{" &middot; " + duration.upper() if duration else ""} &middot; {judges_meta} &middot; {swap_meta} &middot; ORQ-ARENA RUN</p>
{status}
<h1>{headline}</h1>
<p class="lede">{expl}</p>
<div class="kpi-band">{"".join(top3)}</div>{winshare_note}
<p class="pw-caption"><strong>Criteria:</strong> {_e(cfg.criteria)}</p>
</header>

<h2>Leaderboard</h2>
<div class="tablewrap"><table>
<thead><tr><th class="n">#</th><th>Model</th><th class="n">ELO</th><th class="n">95% CI</th>
<th>CI range (shared scale)</th>{"<th class='n'>length-adj.</th>" if elo_sc else ""}<th class="n">avg length</th></tr></thead>
<tbody>{"".join(ladder_rows)}</tbody></table></div>
<p class="note">ELO is a skill rating anchored at 1000: a model climbs by winning rounds, and more
for beating a strong opponent, so a higher score means better on your prompts. The 95% CI is the
range its true rating most likely sits in; the bar plots each on one shared scale, so models
whose bars overlap are not thereby tied: read each bar on its own, and see Confidence stats for whether the top two actually separate.{" The length-adj. column refits the rating with the jury&#39;s length preference (measured in characters) priced out; a large gap between a model&#39;s ELO and its length-adjusted score means verbosity, not quality, was separating them. It appears only when that preference is identified: the joint fit converged and its bootstrap interval excludes 0." if elo_sc else ""} Full method (Bradley-Terry, bootstrap intervals, the &minus;&infin; bound) is in Methodology in detail below.{off_note}</p>

{value_map}
{speed}
<h2>Win grid</h2>
<div class="tablewrap"><table class="grid">
<thead><tr><th style="text-transform:none">row beats column (ties count &frac12;)</th>{head}</tr></thead>
<tbody>{"".join(grid_rows)}</tbody></table></div>

<h2>Tokens and cost</h2>
{cost_cards}
{cost_note}

<details class="method"><summary>The jury</summary>
<div class="tablewrap">{html_table(jury_head, jury_rows) if jury_rows else "<p class='note'>No per-judge stats recorded.</p>"}</div>
<p class="note">{seat_note} Judges also agree with one another (0 = chance, 1 = perfect): {cohen_range or "n/a"}.</p>

<p class="subhead">Panel verdicts across all {len(records)} rounds</p>
<div class="tally">
  <span><span class="sideA">A</span> wins <b>{verdicts["A"]}</b></span>
  <span><span class="sideB">B</span> wins <b>{verdicts["B"]}</b></span>
  <span>ties <b>{verdicts["tie"]}</b></span>
  <span class="sig{inc_cls}">inconclusive <b>{verdicts["inconclusive"]}</b></span>
  {f'<span class="sig warn">errored <b>{voids}</b></span>' if voids else ""}
</div>
<p class="note">The A-vs-B split is panel seat lean; a large skew would flag position bias in the
setup. Inconclusive rounds carry no signal and are dropped from the rating, never counted as ties.{" An errored round is a network or infrastructure failure, not a model failure; it is logged and excluded." if voids else ""}</p>
</details>

<details class="method"{conf_open}><summary>Confidence stats</summary>
<div class="tablewrap">{signals_table}</div>
<p class="note">These are run-confidence signals, not model scores: whether the top spot
clears the noise floor, how tightly the jury agreed, and whether length rather than quality
did the separating.</p>
</details>

<details class="method"><summary>Methodology in detail</summary>
<h3>Ratings</h3>
<p>Bradley-Terry MLE over every rated round (wins and ties), anchored at a 1000-point mean.
95% intervals are 1000-iteration bootstrap percentiles; small pools give wide, overlapping
intervals, which is the honest output at this size. Those intervals are marginal, so read one at a
time: two of them overlapping does not mean the two models are tied, because both are drawn from the
same resamples and share the anchoring. Whether the top two separate is decided on the bootstrap of
their difference, taken within each resample, and reported in Confidence stats. A &minus;&infin; lower bound means a model
won so few rounds its rating is unidentifiable below. The length claim leads with a plain
count (how often the longer answer, in characters, won a decisive round). The modelled
coefficient behind the length-adjusted column is a joint logistic fit (Newton with a line
search, stopped on the gradient norm) bootstrapped over the same rows; the column and the
coefficient are shown only when that fit converges and the interval excludes 0. Resamples
where one side always wins have no finite coefficient; they are counted as separated and
widen the interval rather than being dropped.</p>
<h3>The jury</h3>
<p>{seat_meth}{decision_meth} Fleiss&#39; &kappa;
measures panel agreement across full-panel rounds; pairwise Cohen&#39;s &kappa; measures
judge-vs-judge agreement. Decisive-vote agreement is the share of decisive rounds the panel
agreed on. The A-vs-B split is panel-level seat lean.</p>
<h3>Rounds</h3>
<p>A- and B-wins plus ties are decisive and feed the rating (rated = decisive + ties).
Inconclusive rounds carry no signal and are dropped, never counted as ties. An errored round is
a network or infrastructure failure, not a model failure; it is logged and excluded.</p>
<h3>Cost</h3>
<p>{cost_meth}</p>
</details>

{rounds}

<footer class="footer"><span class="footer-logo">{_LOGO}</span>
config <code>{_e(manifest.get("config_sha256", "?"))}</code> &middot;
prompts <code>{_e(manifest.get("prompts_sha256", "?"))}</code> ({manifest.get("prompt_count", "?")}) &middot;
seed <code>{_e(manifest.get("seed", "?"))}</code> &middot;
panel: {_e(panel)} &middot; evaluatorq <code>{_e(manifest.get("evaluatorq_version", "?"))}</code><br>
generated by <a href="https://github.com/orq-ai/orq-arena">orq-arena</a>; regenerate any time
with <code>orq-arena report &lt;battles.jsonl&gt;</code>. {via}; every token via the orq.ai
router gateway.
</footer>

</div></body></html>
"""


def report_path_for(log_path: str | Path) -> Path:
    return Path(log_path).with_suffix(".report.html")


def write_report(
    *,
    cfg: ArenaConfig,
    records: list[BattleRecord],
    elo: dict[str, float],
    report: dict[str, Any],
    manifest: dict[str, Any],
    log_path: str | Path,
    prices: dict[str, tuple[float, float]] | None = None,
) -> Path:
    out = report_path_for(log_path)
    out.write_text(
        build_report_html(
            cfg=cfg,
            records=records,
            elo=elo,
            report=report,
            manifest=manifest,
            prices=prices,
        ),
        encoding="utf-8",
    )
    return out
