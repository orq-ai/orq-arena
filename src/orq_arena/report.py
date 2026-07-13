"""Single-file HTML run report.

One self-contained page per run, rendered from data the run already
produced (``battles.jsonl`` records, the final report dict, the manifest).
No server, no external assets; the file works from ``file://`` and can be
attached to a PR or linked from a post. Regenerable at any time with
``orq-arena report <log>``.
"""

from __future__ import annotations

import html
import time
from pathlib import Path
from typing import Any

from .config import ArenaConfig
from .data.schemas import BattleRecord

# Official orq.ai symbol (docs.orq.ai brand asset), recolored via currentColor.
_MARK = (
    '<svg viewBox="14 3 86 94" width="22" height="22" aria-hidden="true">'
    '<g fill="currentColor">'
    '<path d="M83.5914 27.8049C83.5914 30.8783 83.5914 32.4151 82.9932 33.589C82.4671 34.6216 81.6276 35.4611 80.595 35.9872C79.4211 36.5854 77.8843 36.5854 74.8109 36.5854H72.8597C69.7862 36.5854 68.2495 36.5854 67.0756 35.9872C66.043 35.4611 65.2035 34.6216 64.6773 33.589C64.0792 32.4151 64.0792 30.8783 64.0792 27.8049V25.6098C64.0792 22.7662 64.0792 21.3444 63.565 20.2417C63.0198 19.0724 62.0799 18.1326 60.9106 17.5873C59.808 17.0732 58.3862 17.0732 55.5426 17.0732C52.699 17.0732 51.2772 17.0732 50.1746 16.559C49.0053 16.0137 48.0654 15.0739 47.5202 13.9046C47.006 12.802 47.006 11.3802 47.006 8.53659C47.006 5.69299 47.006 4.27119 47.5202 3.16856C48.0654 1.99924 49.0053 1.05943 50.1746 0.514165C51.2772 0 52.7091 0 55.573 0C58.4368 0 59.8687 0 60.9714 0.514165C62.1407 1.05943 63.0805 1.99924 63.6258 3.16856C64.1399 4.27119 64.1399 5.69299 64.1399 8.53659C64.1399 11.3802 64.1399 12.802 64.6541 13.9046C65.1994 15.0739 66.1392 16.0137 67.3085 16.559C68.4111 17.0732 69.8329 17.0732 72.6765 17.0732H74.8109C77.8843 17.0732 79.4211 17.0732 80.595 17.6713C81.6276 18.1974 82.4671 19.037 82.9932 20.0696C83.5914 21.2435 83.5914 22.7802 83.5914 25.8537V27.8049Z"/>'
    '<path d="M28.4694 17.0732C31.5429 17.0732 33.0796 17.0732 34.2535 17.6713C35.2861 18.1974 36.1256 19.037 36.6518 20.0696C37.2499 21.2435 37.2499 22.7802 37.2499 25.8537V27.8049C37.2499 30.8783 37.2499 32.4151 36.6518 33.589C36.1256 34.6216 35.2861 35.4611 34.2535 35.9872C33.0796 36.5854 31.5429 36.5854 28.4694 36.5854H26.2743C23.4307 36.5854 22.0089 36.5854 20.9063 37.0995C19.737 37.6448 18.7971 38.5846 18.2519 39.7539C17.7377 40.8566 17.7377 42.2784 17.7377 45.122C17.7377 47.9656 17.7377 49.3873 17.2236 50.49C16.6783 51.6593 15.7385 52.5991 14.5692 53.1444C13.4665 53.6585 12.0447 53.6585 9.20114 53.6585C6.35754 53.6585 4.93574 53.6585 3.83311 53.1444C2.66379 52.5991 1.72398 51.6593 1.17872 50.49C0.664551 49.3873 0.664551 47.9554 0.664551 45.0916C0.664551 42.2277 0.664551 40.7958 1.17872 39.6932C1.72398 38.5239 2.66379 37.5841 3.83311 37.0388C4.93574 36.5246 6.35754 36.5246 9.20114 36.5246C12.0447 36.5246 13.4665 36.5246 14.5692 36.0105C15.7385 35.4652 16.6783 34.5254 17.2236 33.3561C17.7377 32.2534 17.7377 30.8316 17.7377 27.988V25.8537C17.7377 22.7802 17.7377 21.2435 18.3359 20.0696C18.862 19.037 19.7015 18.1974 20.7341 17.6713C21.908 17.0732 23.4448 17.0732 26.5182 17.0732H28.4694Z"/>'
    '<path d="M37.2499 91.4634C37.2499 88.6198 37.2499 87.198 36.7357 86.0954C36.1905 84.9261 35.2507 83.9863 34.0814 83.441C32.9787 82.9268 31.5569 82.9268 28.7133 82.9268H26.5182C23.4448 82.9268 21.908 82.9268 20.7341 82.3287C19.7015 81.8026 18.862 80.963 18.3359 79.9304C17.7377 78.7565 17.7377 77.2198 17.7377 74.1463V72.1951C17.7377 69.1217 17.7377 67.5849 18.3359 66.411C18.862 65.3784 19.7015 64.5389 20.7341 64.0128C21.908 63.4146 23.4447 63.4146 26.5182 63.4146L28.4694 63.4146C31.5429 63.4146 33.0796 63.4146 34.2535 64.0128C35.2861 64.5389 36.1256 65.3784 36.6518 66.411C37.2499 67.5849 37.2499 69.1217 37.2499 72.1951V74.3295C37.2499 77.1731 37.2499 78.5949 37.7641 79.6975C38.3093 80.8669 39.2492 81.8067 40.4185 82.3519C41.5211 82.8661 42.9429 82.8661 45.7865 82.8661C48.6301 82.8661 50.0519 82.8661 51.1545 83.3803C52.3238 83.9255 53.2637 84.8653 53.8089 86.0347C54.3231 87.1373 54.3231 88.5692 54.3231 91.433C54.3231 94.2969 54.3231 95.7288 53.8089 96.8314C53.2637 98.0008 52.3238 98.9406 51.1545 99.4858C50.0519 100 48.6301 100 45.7865 100C42.9429 100 41.5211 100 40.4185 99.4858C39.2492 98.9406 38.3093 98.0008 37.7641 96.8315C37.2499 95.7288 37.2499 94.307 37.2499 91.4634Z"/>'
    '<path d="M72.8597 82.9268C69.7862 82.9268 68.2495 82.9268 67.0756 82.3287C66.043 81.8026 65.2035 80.963 64.6773 79.9304C64.0792 78.7565 64.0792 77.2198 64.0792 74.1463V72.1951C64.0792 69.1217 64.0792 67.5849 64.6773 66.411C65.2035 65.3784 66.043 64.5389 67.0756 64.0128C68.2495 63.4146 69.7862 63.4146 72.8597 63.4146H75.0548C77.8984 63.4146 79.3202 63.4146 80.4228 62.9005C81.5921 62.3552 82.532 61.4154 83.0772 60.2461C83.5914 59.1434 83.5914 57.7217 83.5914 54.8781C83.5914 52.0345 83.5914 50.6127 84.1055 49.51C84.6508 48.3407 85.5906 47.4009 86.7599 46.8556C87.8626 46.3415 89.2844 46.3415 92.128 46.3415C94.9716 46.3415 96.3934 46.3415 97.496 46.8556C98.6653 47.4009 99.6051 48.3407 100.15 49.51C100.665 50.6127 100.665 52.0446 100.665 54.9084C100.665 57.7723 100.665 59.2042 100.15 60.3068C99.6051 61.4761 98.6653 62.4159 97.496 62.9612C96.3934 63.4754 94.9716 63.4754 92.128 63.4754C89.2844 63.4754 87.8626 63.4754 86.7599 63.9895C85.5906 64.5348 84.6508 65.4746 84.1055 66.6439C83.5914 67.7466 83.5914 69.1684 83.5914 72.012V74.1463C83.5914 77.2198 83.5914 78.7565 82.9932 79.9304C82.4671 80.963 81.6276 81.8026 80.595 82.3287C79.4211 82.9268 77.8844 82.9268 74.8109 82.9268H72.8597Z"/>'
    '<path d="M50.6645 58.5366C48.1085 58.5366 46.8305 58.5366 45.8149 58.1403C44.3062 57.5516 43.1129 56.3583 42.5242 54.8496C42.1279 53.834 42.1279 52.556 42.1279 50C42.1279 47.444 42.1279 46.166 42.5242 45.1504C43.1129 43.6417 44.3062 42.4484 45.8149 41.8597C46.8305 41.4634 48.1085 41.4634 50.6645 41.4634C53.2205 41.4634 54.4985 41.4634 55.5141 41.8597C57.0228 42.4484 58.2161 43.6417 58.8048 45.1504C59.2011 46.166 59.2011 47.444 59.2011 50C59.2011 52.556 59.2011 53.834 58.8048 54.8496C58.2161 56.3583 57.0228 57.5516 55.5141 58.1403C54.4985 58.5366 53.2205 58.5366 50.6645 58.5366Z"/>'
    '</g></svg>'
)

_CSS = """
:root {
  color-scheme: light;
  /* orq.ai brand palette (Brand Guidelines v1.0), same tokens as the
     Model-Router-Auto-Evaluation dashboard: warm beige neutrals, Pulse
     Orange accent, Incognito Black ink. A/B side colors stay functional. */
  --brand: #DF5325;
  --paper: oklch(0.966 0.008 83); --card: oklch(0.992 0.005 83);
  --line: oklch(0.885 0.011 83); --ink: #141319;
  --teal: #141319; --teal-soft: oklch(0.50 0.13 158); --muted: oklch(0.535 0.013 83);
  --a: #c8189e; --b: #0092ab; --good: oklch(0.50 0.13 158); --warn: oklch(0.55 0.12 75);
  --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
  --sans: 'Inter', ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
          "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--paper); color: var(--ink); font-family: var(--sans);
       line-height: 1.55; -webkit-font-smoothing: antialiased; }
.wrap { max-width: 960px; margin: 0 auto; padding: 0 24px 72px; }
header { display: flex; align-items: center; gap: 10px; padding: 26px 0 14px;
         border-bottom: 2px solid var(--ink); color: var(--ink); }
header .brand { font-weight: 700; font-size: 17px; letter-spacing: -0.3px; }
header .kind { margin-left: auto; font-family: var(--mono); font-size: 12px; color: var(--muted); }
h1 { font-size: 30px; line-height: 1.15; margin: 26px 0 4px; letter-spacing: -0.5px; }
h2 { font-size: 17px; margin: 40px 0 10px; padding-bottom: 6px; border-bottom: 1px solid var(--line); }
.sub { color: var(--muted); font-family: var(--mono); font-size: 12.5px; }
.sub a { color: var(--brand); text-decoration: none; }
.sub a:hover { text-decoration: underline; }
.badges { display: flex; flex-wrap: wrap; gap: 8px; margin: 16px 0 4px; }
.badge { font-family: var(--mono); font-size: 12px; padding: 3px 10px; border-radius: 20px;
         border: 1px solid var(--line); background: var(--card); }
.badge b { font-weight: 600; }
.badge.good { border-color: #b5cba3; background: #eef4e6; color: var(--good); }
.badge.warn { border-color: #e0c98d; background: #f8efd9; color: var(--warn); }
.verdict { background: oklch(0.945 0.012 83); border: 1px solid var(--line);
  border-radius: 14px; padding: 26px 30px 22px; margin: 26px 0 12px;
  --state: var(--good); }
.verdict.tied { --state: var(--warn); }
.verdict .eyebrow { font-family: var(--mono); font-size: 11px; letter-spacing: .12em;
  text-transform: uppercase; color: var(--state); font-weight: 600; margin: 0 0 10px; }
.verdict h1 { margin: 0 0 10px; font-size: 27px; line-height: 1.25; letter-spacing: -0.02em; }
.verdict .expl { color: var(--muted); font-size: 13.5px; max-width: 64ch; margin: 0 0 18px; }
.verdict .kpis { display: flex; gap: 44px; border-top: 1px solid var(--line); padding-top: 16px; }
.verdict .kpi > b { display: block; font-size: 34px; font-weight: 700; letter-spacing: -0.03em;
  font-variant-numeric: tabular-nums; color: var(--ink); }
.verdict .kpi.state > b { color: var(--state); }
.verdict .kpi span { font-size: 12px; color: var(--muted); }
.verdict .kpi span.stat { display: block; margin-top: 4px; }
.verdict .kpi span b { font-size: 16px; color: var(--ink); font-variant-numeric: tabular-nums; }
.verdict .kpi span.lead b { font-size: 23px; letter-spacing: -0.02em; }
.verdict .kpi.state span.lead b { color: var(--state); }
.verdict .kpi > b.name-kpi { font-size: 26px; line-height: 1.15; padding-top: 5px; }
table { border-collapse: collapse; width: 100%; font-size: 13.5px;
        font-variant-numeric: tabular-nums; }
th { text-align: left; font-family: var(--mono); font-size: 10.5px; text-transform: uppercase;
     letter-spacing: 0.08em; color: var(--muted); padding: 6px 10px;
     border-bottom: 1.5px solid var(--line); }
td { padding: 7px 10px; border-bottom: 1px solid var(--line); vertical-align: middle; }
td.n, th.n { text-align: right; font-family: var(--mono); white-space: nowrap; }
.tablewrap { overflow-x: auto; background: var(--card); border: 1px solid var(--line);
             border-radius: 10px; padding: 4px 8px 8px; }
.ci-track { position: relative; height: 8px; background: #efece3; border-radius: 4px; min-width: 160px; }
.ci-range { position: absolute; top: 0; height: 8px; background: #cfe3da; border-radius: 4px; }
.ci-dot { position: absolute; top: -2px; width: 4px; height: 12px; border-radius: 2px; background: var(--teal-soft); }
.name { font-weight: 600; white-space: nowrap; }
.think { font-size: 11px; color: var(--muted); }
.grid td, .grid th { text-align: center; padding: 6px 6px; }
.grid td.rowname { text-align: left; font-weight: 600; white-space: nowrap; }
.foot { margin-top: 48px; padding-top: 14px; border-top: 2px solid var(--line);
        font-family: var(--mono); font-size: 11.5px; color: var(--muted); }
.foot code { background: #f0ede4; padding: 1px 5px; border-radius: 3px; }
.note { font-size: 12.5px; color: var(--muted); margin: 8px 2px; }
.sideA { color: var(--a); font-weight: 600; } .sideB { color: var(--b); font-weight: 600; }
@media (max-width: 640px) { h1 { font-size: 24px; } }
"""


def _e(s: Any) -> str:
    return html.escape(str(s))


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.0%}"


def _ci_bar(lo: float, hi: float, point: float, floor: float, span: float) -> str:
    left = (lo - floor) / span * 100
    width = max((hi - lo) / span * 100, 0.5)
    dot = (point - floor) / span * 100
    return (
        f'<div class="ci-track"><div class="ci-range" style="left:{left:.1f}%;width:{width:.1f}%">'
        f'</div><div class="ci-dot" style="left:{dot:.1f}%"></div></div>'
    )


def _cost_lines(records, manifest, prices, alias=None):
    """(warrior_usd, jury_usd_estimate, unpriced_names) or None without prices.

    Warrior spend is exact (per-record model attribution); jury spend is an
    estimate at the panel's mean catalog rate, because records store the
    panel's token total, not per-judge splits. ``alias`` maps the short model
    names stored in records to the display names the manifest is keyed by.
    """
    if not prices:
        return None
    alias = alias or {}
    id_by_name = {
        n: (w.get("model") if isinstance(w, dict) else "")
        for n, w in (manifest.get("warriors") or {}).items()
    }
    warriors_usd, unpriced = 0.0, set()
    j_in = j_out = 0
    for r in records:
        if r.error is not None:
            continue
        j_in += r.judge_tokens_in
        j_out += r.judge_tokens_out
        for name, tin, tout in (
            (r.model_a, r.tokens_a_in, r.tokens_a_out),
            (r.model_b, r.tokens_b_in, r.tokens_b_out),
        ):
            name = alias.get(name, name)
            pr = prices.get(id_by_name.get(name, ""))
            if pr is None:
                unpriced.add(name)
            else:
                warriors_usd += tin * pr[0] / 1e6 + tout * pr[1] / 1e6
    panel = [prices[j] for j in manifest.get("judges", []) if j in prices]
    unpriced.update(j for j in manifest.get("judges", []) if j not in prices)
    jury_usd = None
    if panel:
        mean_in = sum(x[0] for x in panel) / len(panel)
        mean_out = sum(x[1] for x in panel) / len(panel)
        jury_usd = j_in * mean_in / 1e6 + j_out * mean_out / 1e6
    return warriors_usd, jury_usd, sorted(unpriced)



def _win_rates(grid: dict, names: list[str]) -> dict[str, float]:
    """Rated-round win share per model from the win grid (ties are 0.5 in it)."""
    rates = {}
    for n in names:
        won = sum((grid.get(n) or {}).values())
        lost = sum((grid.get(m) or {}).get(n, 0.0) for m in names if m != n)
        rates[n] = won / (won + lost) if won + lost else 0.0
    return rates


def _per_model_cost(records, manifest, prices, alias=None) -> dict[str, float]:
    alias = alias or {}
    id_by_name = {
        n: (w.get("model") if isinstance(w, dict) else "")
        for n, w in (manifest.get("warriors") or {}).items()
    }
    out: dict[str, float] = {}
    for r in records:
        if r.error is not None:
            continue
        for name, tin, tout in (
            (r.model_a, r.tokens_a_in, r.tokens_a_out),
            (r.model_b, r.tokens_b_in, r.tokens_b_out),
        ):
            name = alias.get(name, name)
            pr = prices.get(id_by_name.get(name, ""))
            if pr is not None:
                out[name] = out.get(name, 0.0) + tin * pr[0] / 1e6 + tout * pr[1] / 1e6
    return out


def _fmt_usd(v: float) -> str:
    return f"${v:.2f}" if v >= 0.1 else f"${v:.3f}"


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
    step = next((s for s in (50, 100, 200, 500, 1000)
                 if (max(elos) - min(elos)) / s <= 6), 2000)
    e_lo = math.floor((min(elos) - step * 0.4) / step) * step
    e_hi = math.ceil((max(elos) + step * 0.4) / step) * step
    W, H, L, R, T, B = 720, 310, 70, 40, 30, 60

    def px(c):
        return L + (math.log10(max(c, 1e-4)) - x0) / span * (W - L - R)

    def py(e):
        return T + (1 - (e - e_lo) / (e_hi - e_lo)) * (H - T - B)

    frontier, best = [], float("-inf")
    for name, c, e, _r, _t in sorted(points, key=lambda p: p[1]):
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
        fill = "var(--brand)" if name == champion else ("var(--teal-soft)" if on_frontier else "#b5b1a4")
        rk = rank_of[name]
        dots.append(
            f"<circle cx='{x:.0f}' cy='{y:.0f}' r='{rad:.0f}' fill='{fill}' opacity='.88'>"
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
                f"fill='var(--muted)' text-anchor='middle' pointer-events='none'>{_e(name)}</text>"
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
                    f"stroke='var(--muted)' stroke-width='0.75' opacity='0.6'/>"
                )
            dots.append(
                leader
                + f"<text x='{lx:.0f}' y='{ly:.0f}' font-size='11' font-weight='700' "
                f"fill='var(--ink)' text-anchor='middle'>{_e(name)} "
                f"<tspan fill='var(--muted)' font-weight='400'>{_fmt_usd(c)} &middot; ELO {e:.0f}</tspan></text>"
            )
        star = " &#9733;" if on_frontier else ""
        key_rows.append(
            f"<span style='white-space:nowrap'><b>{rk}</b> {_e(name)} "
            f"<span style='color:var(--muted)'>{_fmt_usd(c)} &middot; ELO {e:.0f} &middot; {r:.0%}{star}</span></span>"
        )
    key = ("<p class='note' style='display:flex;flex-wrap:wrap;gap:4px 18px'>"
           + "".join(key_rows) + "</p>")

    # Axis ticks: y at round ELO steps with faint gridlines; x at $ decades (log scale).
    y_ticks = "".join(
        f"<line x1='{L}' y1='{py(v):.0f}' x2='{W - R}' y2='{py(v):.0f}' "
        f"stroke='var(--line)' stroke-width='{1 if v in (e_lo, e_hi) else 0.5}' "
        f"{'stroke-dasharray=2 3' if v not in (e_lo, e_hi) else ''}/>"
        f"<text x='{L - 8}' y='{py(v) + 4:.0f}' font-size='10' fill='var(--muted)' "
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
        val = 10 ** d
        x_ticks += (
            f"<line x1='{tx:.0f}' y1='{H - B}' x2='{tx:.0f}' y2='{H - B + 5}' stroke='var(--muted)'/>"
            f"<text x='{tx:.0f}' y='{H - B + 17}' font-size='10' fill='var(--muted)' "
            f"text-anchor='middle'>{_fmt_usd(val)}</text>"
        )

    return f"""
<h2>Value map</h2>
<div class="tablewrap">
<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="ELO vs cost">
<line x1="{L}" y1="{H - B}" x2="{W - R}" y2="{H - B}" stroke="var(--line)"/>
<line x1="{L}" y1="{T}" x2="{L}" y2="{H - B}" stroke="var(--line)"/>
<text x="{L - 8}" y="{T - 10}" font-size="10" fill="var(--muted)" text-anchor="end">ELO</text>
{y_ticks}
{x_ticks}
<text x="{(L + W - R) // 2}" y="{H - 14}" font-size="11" fill="var(--muted)" text-anchor="middle">cost per model over the whole run (log scale)</text>
<polyline points="{poly}" fill="none" stroke="var(--brand)" stroke-width="1.5" stroke-dasharray="5 4"/>
{"".join(dots)}
</svg></div>
{key}
<p class="note">Dashed line: the best-value frontier (&#9733; in the key; no cheaper model rates
higher). Dot size is {size_label}; the champion is magenta; hover any dot for cost, ELO,
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
        for name, tout, ttft, dur in (
            (alias.get(r.model_a, r.model_a), r.tokens_a_out, r.ttft_a_ms, r.duration_a_ms),
            (alias.get(r.model_b, r.model_b), r.tokens_b_out, r.ttft_b_ms, r.duration_b_ms),
        ):
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
        out.append((
            name,
            ts / tn if tn else 0.0,
            ft / fn if fn else 0.0,
            ot / on if on else 0.0,
            ds / tn if tn else 0.0,
        ))
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
    note = ("Average tokens per second over the run's streamed responses; "
            "time to first token annotated.")
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
            f"<text x='{L - 8}' y='{y + 12}' font-size='10.5' fill='var(--muted)' text-anchor='end'>{_e(name)}</text>"
            f"<rect x='{L}' y='{y}' width='{width:.0f}' height='14' rx='4' fill='var(--teal-soft)' opacity='{op:.2f}'/>"
            f"<text x='{L + width + 8:.0f}' y='{y + 12}' font-size='10.5' fill='var(--muted)'>{label}</text>"
        )
    return f"""
<h2>{title}</h2>
<div class="tablewrap">
<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="{title} per model">
{"".join(parts)}
</svg></div>
<p class="note">{note}</p>
"""


def build_report_html(
    *,
    cfg: ArenaConfig,
    records: list[BattleRecord],
    elo: dict[str, float],
    report: dict[str, Any],
    manifest: dict[str, Any],
    prices: dict[str, tuple[float, float]] | None = None,
) -> str:
    """Render the run report page as a self-contained HTML string."""
    judged = [r for r in records if r.error is None]
    voids = len(records) - len(judged)
    verdicts = {"A": 0, "B": 0, "tie": 0, "inconclusive": 0}
    for r in judged:
        verdicts[r.majority_verdict] = verdicts.get(r.majority_verdict, 0) + 1
    decisive = verdicts["A"] + verdicts["B"]
    rated = report.get("rated_rounds", decisive + verdicts["tie"])

    ranked = sorted(elo.items(), key=lambda kv: kv[1], reverse=True)
    champion, champ_elo = ranked[0]
    ci: dict[str, tuple[float, float]] = {
        k: tuple(v) for k, v in (report.get("elo_ci") or {}).items()
    }
    thinking = report.get("thinking") or {}
    verbosity = report.get("verbosity") or {}
    elo_sc = report.get("elo_style_controlled") or {}
    length_coef = report.get("length_coef")

    # Verdict hero: is the top spot statistically separated from the runner-up?
    overlap_caveat = ""
    if len(ranked) > 1 and ci:
        runner, _ = ranked[1]
        c_lo = ci.get(champion, (champ_elo, champ_elo))[0]
        r_hi = ci.get(runner, (0.0, 0.0))[1]
        if r_hi >= c_lo:
            overlap_caveat = (
                f'<span class="badge warn">CI overlap: {_e(runner)} is statistically '
                f"indistinguishable at this sample size</span>"
            )
        else:
            overlap_caveat = '<span class="badge good">top spot separated at 95% CI</span>'

    fleiss = report.get("fleiss") or {}
    kappa_badge = ""
    if fleiss.get("kappa") is not None:
        kappa_badge = (
            f'<span class="badge">Fleiss&#39; &kappa; <b>{fleiss["kappa"]}</b> '
            f'({_e(fleiss.get("label", ""))}) over {fleiss.get("rounds_used", "?")}/'
            f'{fleiss.get("rounds_total", "?")} full-panel rounds</span>'
        )
    agreement = report.get("mean_agreement")
    length_badge = ""
    if length_coef is not None:
        lean = "longer" if length_coef > 0 else "shorter"
        length_badge = (
            f'<span class="badge">jury length coefficient <b>{length_coef:+.2f}</b> '
            f"(leaned {lean}; len-ctrl column prices it out)</span>"
        )

    started = manifest.get("started_at")
    finished = manifest.get("finished_at") or (
        max((r.timestamp for r in records), default=None)
    )
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
    ladder_rows = []
    for i, (name, e0) in enumerate(ranked, 1):
        lo, hi = ci.get(name, (e0, e0))
        dlo, dhi = max(lo, floor), min(hi, ceil)
        think = ' <span class="think">thinking</span>' if thinking.get(name) else ""
        tok = verbosity.get(name)
        sc_cell = f"<td class='n'>{elo_sc[name]:.0f}</td>" if name in elo_sc else ""
        ladder_rows.append(
            f"<tr><td class='n'>{i}</td><td class='name'>{_e(name)}{think}</td>"
            f"<td class='n'>{e0:.0f}</td><td class='n'>{lo:.0f}&ndash;{hi:.0f}</td>"
            f"<td title='{lo:.0f} to {hi:.0f}'>{_ci_bar(dlo, dhi, e0, floor, span)}</td>"
            f"{sc_cell}"
            f"<td class='n'>{'' if tok is None else f'{tok:.0f}'}</td></tr>"
        )

    # Win grid: full names on rows, rank numbers on columns (no truncated-name collisions).
    grid = report.get("win_grid") or {}
    order = [n for n, _ in ranked]
    head = "".join(f"<th class='n'>{i}</th>" for i in range(1, len(order) + 1))
    vmax = max(
        (v for row in grid.values() for v in (row or {}).values()), default=0.0
    )
    grid_rows = []
    for i, a in enumerate(order, 1):
        cells = []
        for b in order:
            if a == b:
                cells.append("<td>&middot;</td>")
            else:
                v = (grid.get(a) or {}).get(b, 0.0)
                # Heat: single-hue intensity so the dominance triangle reads at a glance.
                alpha = 0.0 if not v or not vmax else 0.10 + 0.45 * (v / vmax)
                style = f" style='background:rgba(223,83,37,{alpha:.2f})'" if alpha else ""
                cells.append(f"<td{style}>{v:g}</td>")
        grid_rows.append(f"<tr><td class='rowname'>{i}. {_e(a)}</td>{''.join(cells)}</tr>")

    # Jury room.
    jury = report.get("jury") or {}
    jury_rows = []
    for j in jury.get("per_judge", []):
        jury_rows.append(
            f"<tr><td class='name'>{_e(str(j.get('model', '')).split('/')[-1])}</td>"
            f"<td class='n'>{_pct(j.get('a_rate'))}</td>"
            f"<td class='n'>{_pct(j.get('b_rate'))}</td>"
            f"<td class='n'>{_pct(j.get('position_bias'))}</td>"
            f"<td class='n'>{_pct(j.get('tie_rate'))}</td></tr>"
        )
    cohen = report.get("cohen") or {}
    cohen_bits = ", ".join(
        f"{_e(k)}: {v.get('kappa')}" if isinstance(v, dict) else f"{_e(k)}: {v}"
        for k, v in cohen.items()
    )

    # Rounds and category accounting.
    tok = report.get("tokens") or {}
    w_in, w_out = tok.get("warriors_in", 0), tok.get("warriors_out", 0)
    j_in, j_out = tok.get("judges_in", 0), tok.get("judges_out", 0)
    total_tok = w_in + w_out + j_in + j_out
    jury_share = f"{(j_in + j_out) / total_tok:.0%}" if total_tok else "n/a"

    panel = ", ".join(str(j).split("/")[-1] for j in manifest.get("judges", cfg.judges))

    # Records store short model names; elo/manifest/report are keyed by display
    # name (orc_name). Identical unless the roster sets custom names.
    alias = report.get("by_model_names") or {w.short_model: w.orc_name for w in cfg.warriors}
    stats_all = _speed_stats(records, alias)
    speed = _speed_svg(stats_all)
    dur_by = {n: d for n, _t, _f, _o, d in stats_all}

    value_map = ""
    if prices:
        per_cost = _per_model_cost(records, manifest, prices, alias)
        rates = _win_rates(grid, order)
        use_dur = any(dur_by.get(n, 0.0) > 0 for n in order)
        pts = [
            (n, per_cost[n], elo.get(n, 0.0), rates.get(n, 0.0),
             dur_by.get(n, 0.0) if use_dur else (verbosity.get(n) or 0.0))
            for n in order if n in per_cost and per_cost[n] > 0
        ]
        value_map = _value_map_svg(pts, champion, size_label=(
            "average time to answer" if use_dur else "average response length"))

    rates_all = _win_rates(grid, order)
    per_cost_all = _per_model_cost(records, manifest, prices, alias) if prices else {}

    cost = _cost_lines(records, manifest, prices, alias)
    w_usd_cell = j_usd_cell = t_usd_cell = ""
    cost_note = ""
    cost_head = ""
    if cost:
        w_usd, j_usd, unpriced = cost
        cost_head = "<th class='n'>est. cost</th>"
        w_usd_cell = f"<td class='n'>${w_usd:,.2f}</td>"
        j_usd_cell = f"<td class='n'>{'&asymp; $' + format(j_usd, ',.2f') if j_usd is not None else 'n/a'}</td>"
        total = w_usd + (j_usd or 0.0)
        t_usd_cell = (
            f"<tr><td class='name'>total</td><td class='n'></td><td class='n'></td>"
            f"<td class='n'><b>&asymp; ${total:,.2f}</b></td></tr>"
        )
        cost_note = (
            "<p class='note'>Model spend is exact (per-model catalog rates); jury spend is "
            "estimated at the panel's mean rate because the log stores the panel's token total, "
            "not per-judge splits." + (
                " Unpriced in the catalog and excluded: " + ", ".join(unpriced) + "." if unpriced else ""
            ) + "</p>"
        )

    # Pragmatic verdict banner (the auto-router dashboard treatment): one
    # actionable sentence, a plain-words explainer, two large KPIs.
    champ_rate = rates_all.get(champion, 0.0)
    runner_name = ranked[1][0] if len(ranked) > 1 else ""
    separated = "top spot separated" in overlap_caveat
    if separated:
        vclass, headline = "", (
            f"Adopt {_e(champion)}: wins {champ_rate:.0%} of rated rounds, "
            f"statistically ahead at 95% confidence."
        )
        expl = (
            f"{_e(champion)} beat every other model in this pool on your prompts and its lead "
            f"over {_e(runner_name)} exceeds the uncertainty of a run this size."
        )
    else:
        vclass, headline = " tied", (
            f"{_e(champion)} leads, but {_e(runner_name)} is statistically tied: "
            f"decide on cost and speed."
        )
        expl = (
            f"{_e(champion)} has the best rating, but at {len(records)} rounds the gap to "
            f"{_e(runner_name)} is inside the error bars. The value map below is the "
            f"tie-breaker; more rounds would separate them."
        )
    status = ("&#10003; TOP SPOT SEPARATED" if separated
              else "&#9888; STATISTICAL TIE AT THE TOP")
    medals = ["&#129351;", "&#129352;", "&#129353;"]
    top3 = []
    for i, (nm, e0) in enumerate(ranked[:3]):
        cls = " state" if i == 0 else ""
        stats = (
            f"<span class='stat lead'><b>{rates_all.get(nm, 0.0):.0%}</b> win rate</span>"
            f"<span class='stat'><b>{e0:.0f}</b> ELO score</span>"
        )
        if nm in per_cost_all:
            stats += f"<span class='stat'><b>{_fmt_usd(per_cost_all[nm])}</b> total cost</span>"
        top3.append(
            f"<div class='kpi{cls}'><b class='name-kpi'>{medals[i]} {_e(nm)}</b>{stats}</div>"
        )
    verdict_banner = (
        f"<div class='verdict{vclass}'><p class='eyebrow'>{status}</p>"
        f"<h1>{headline}</h1>"
        f"<p class='expl'>{expl}</p><div class='kpis'>"
        f"{''.join(top3)}</div></div>"
    )

    ds = manifest.get("dataset") or {}
    dataset_frag = ""
    if ds.get("id"):
        label = _e(ds.get("name") or ds["id"])
        dataset_frag = (
            f"dataset <a href='{_e(ds['url'])}'>{label}</a> &middot; "
            if ds.get("url") else f"dataset {label} &middot; "
        )


    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>orq-arena report &middot; {_e(manifest.get("tournament_id", ""))}</title>
<style>{_CSS}</style></head><body><div class="wrap">

<header>{_MARK}<span class="brand">orq.ai</span><span class="kind">{len(ranked)} MODELS &middot; {len(records)} ROUNDS{" &middot; " + duration.upper() if duration else ""} &middot; ORQ-ARENA RUN</span></header>

{verdict_banner}
<p class="sub">{dataset_frag}{len(ranked)} models &middot; {_e(manifest.get("tournament_id", ""))} &middot; {datestr}
{" &middot; " + duration if duration else ""} &middot; {len(records)} rounds
({rated} rated &middot; {verdicts["inconclusive"]} inconclusive &middot; {voids} voided)</p>

<div class="badges">
  {overlap_caveat}
  {kappa_badge}
  {length_badge}
  <span class="badge">decisive-vote agreement <b>{_pct(agreement)}</b></span>
  <span class="badge">jury share of tokens <b>{jury_share}</b></span>
</div>

<h2>Leaderboard</h2>
<div class="tablewrap"><table>
<thead><tr><th class="n">#</th><th>Model</th><th class="n">ELO</th><th class="n">95% CI</th>
<th>CI range (shared scale)</th>{"<th class='n'>len-ctrl</th>" if elo_sc else ""}<th class="n">avg out tok</th></tr></thead>
<tbody>{"".join(ladder_rows)}</tbody></table></div>
<p class="note">Bradley-Terry MLE over every rated round (wins and ties), anchored at a
1000-point mean; intervals are 200-iteration bootstrap percentiles. Overlapping intervals are
the honest output on a run this size.{" The len-ctrl column refits the rating with the jury&#39;s length preference priced out; a large raw-vs-len-ctrl gap means verbosity, not quality, is doing the separating." if elo_sc else ""}</p>

{value_map}
{speed}
<h2>Win grid</h2>
<div class="tablewrap"><table class="grid">
<thead><tr><th>row beats column (ties count &frac12;)</th>{head}</tr></thead>
<tbody>{"".join(grid_rows)}</tbody></table></div>

<h2>The jury</h2>
<div class="tablewrap"><table>
<thead><tr><th>Judge</th><th class="n"><span class="sideA">A</span>-lean</th>
<th class="n"><span class="sideB">B</span>-lean</th><th class="n">flip rate</th>
<th class="n">tie rate</th></tr></thead>
<tbody>{"".join(jury_rows) or "<tr><td colspan='5'>no per-judge stats recorded</td></tr>"}</tbody>
</table></div>
<p class="note">Each judge sees every pair in both seat orders; a judge that contradicts
itself abstains (the flip rate) and abstentions never become verdicts. Pairwise Cohen&#39;s
&kappa;: {cohen_bits or "n/a"}.</p>

<h2>Rounds</h2>
<div class="badges">
  <span class="badge"><span class="sideA">A</span> wins <b>{verdicts["A"]}</b></span>
  <span class="badge"><span class="sideB">B</span> wins <b>{verdicts["B"]}</b></span>
  <span class="badge">ties <b>{verdicts["tie"]}</b></span>
  <span class="badge">inconclusive <b>{verdicts["inconclusive"]}</b></span>
  <span class="badge">{"voided <b>" + str(voids) + "</b>" if voids else "voided <b>0</b>"}</span>
</div>
<p class="note">Inconclusive rounds carry no signal and are dropped from the rating, never
counted as ties. A voided round is a network failure, not a model failure; it is logged and
excluded.</p>

<h2>Tokens and cost</h2>
<div class="tablewrap"><table>
<thead><tr><th></th><th class="n">input</th><th class="n">output</th>{cost_head}</tr></thead>
<tbody>
<tr><td class="name">models</td><td class="n">{w_in:,}</td><td class="n">{w_out:,}</td>{w_usd_cell}</tr>
<tr><td class="name">jury</td><td class="n">{j_in:,}</td><td class="n">{j_out:,}</td>{j_usd_cell}</tr>
{t_usd_cell}
</tbody></table></div>
{cost_note}

<div class="foot">
config <code>{_e(manifest.get("config_sha256", "?"))}</code> &middot;
prompts <code>{_e(manifest.get("prompts_sha256", "?"))}</code> ({manifest.get("prompt_count", "?")}) &middot;
seed <code>{_e(manifest.get("seed", "?"))}</code> &middot;
panel: {_e(panel)} &middot; evaluatorq <code>{_e(manifest.get("evaluatorq_version", "?"))}</code><br>
generated by <a href="https://github.com/orq-ai/orq-arena">orq-arena</a>; regenerate any time
with <code>orq-arena report &lt;battles.jsonl&gt;</code>. Every verdict via evaluatorq&#39;s
pairwise jury; every token via the orq.ai router gateway.
</div>

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
    out.write_text(build_report_html(
        cfg=cfg, records=records, elo=elo, report=report, manifest=manifest, prices=prices,
    ), encoding="utf-8")
    return out
