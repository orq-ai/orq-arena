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

# orq.ai pinwheel mark (same geometry as the README splash).
_MARK = (
    '<svg viewBox="-30 -30 68 68" width="22" height="22" aria-hidden="true">'
    '<g fill="currentColor">'
    '<g><rect x="3" y="-26" width="19" height="19" rx="6.2"/>'
    '<rect x="26" y="-10" width="11.5" height="11.5" rx="3.8"/></g>'
    '<g transform="rotate(90)"><rect x="3" y="-26" width="19" height="19" rx="6.2"/>'
    '<rect x="26" y="-10" width="11.5" height="11.5" rx="3.8"/></g>'
    '<g transform="rotate(180)"><rect x="3" y="-26" width="19" height="19" rx="6.2"/>'
    '<rect x="26" y="-10" width="11.5" height="11.5" rx="3.8"/></g>'
    '<g transform="rotate(270)"><rect x="3" y="-26" width="19" height="19" rx="6.2"/>'
    '<rect x="26" y="-10" width="11.5" height="11.5" rx="3.8"/></g>'
    "</g></svg>"
)

_CSS = """
:root {
  --ink: #141319; --paper: #faf8f3; --card: #ffffff; --line: #e6e1d6;
  --teal: #00342d; --teal-soft: #0a7b63; --muted: #7a766c;
  --a: #c8189e; --b: #0092ab; --good: #3f6b2f; --warn: #8a6510;
  --mono: "SF Mono", "JetBrains Mono", ui-monospace, Menlo, monospace;
  --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--paper); color: var(--ink); font-family: var(--sans);
       line-height: 1.55; -webkit-font-smoothing: antialiased; }
.wrap { max-width: 960px; margin: 0 auto; padding: 0 24px 72px; }
header { display: flex; align-items: center; gap: 10px; padding: 26px 0 14px;
         border-bottom: 2px solid var(--teal); color: var(--teal); }
header .brand { font-weight: 700; font-size: 17px; letter-spacing: -0.3px; }
header .kind { margin-left: auto; font-family: var(--mono); font-size: 12px; color: var(--muted); }
h1 { font-size: 30px; line-height: 1.15; margin: 26px 0 4px; letter-spacing: -0.5px; }
h2 { font-size: 17px; margin: 40px 0 10px; padding-bottom: 6px; border-bottom: 1px solid var(--line); }
.sub { color: var(--muted); font-family: var(--mono); font-size: 12.5px; }
.badges { display: flex; flex-wrap: wrap; gap: 8px; margin: 16px 0 4px; }
.badge { font-family: var(--mono); font-size: 12px; padding: 3px 10px; border-radius: 20px;
         border: 1px solid var(--line); background: var(--card); }
.badge b { font-weight: 600; }
.badge.good { border-color: #b5cba3; background: #eef4e6; color: var(--good); }
.badge.warn { border-color: #e0c98d; background: #f8efd9; color: var(--warn); }
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


def build_report_html(
    *,
    cfg: ArenaConfig,
    records: list[BattleRecord],
    elo: dict[str, float],
    report: dict[str, Any],
    manifest: dict[str, Any],
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
                style = f" style='background:rgba(10,123,99,{alpha:.2f})'" if alpha else ""
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
    cat_counts = report.get("category_counts") or {}
    cat_elo = report.get("elo_by_category") or {}
    cat_rows = []
    for cat in sorted(cat_counts):
        by_cat = cat_elo.get(cat)
        leader = (
            _e(max(by_cat, key=by_cat.get)) if by_cat
            else "<span class='note'>below the 20-comparison floor</span>"
        )
        cat_rows.append(
            f"<tr><td>{_e(cat)}</td><td class='n'>{cat_counts[cat]}</td><td>{leader}</td></tr>"
        )

    tok = report.get("tokens") or {}
    w_in, w_out = tok.get("warriors_in", 0), tok.get("warriors_out", 0)
    j_in, j_out = tok.get("judges_in", 0), tok.get("judges_out", 0)
    total_tok = w_in + w_out + j_in + j_out
    jury_share = f"{(j_in + j_out) / total_tok:.0%}" if total_tok else "n/a"

    panel = ", ".join(str(j).split("/")[-1] for j in manifest.get("judges", cfg.judges))

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>orq-arena report &middot; {_e(manifest.get("tournament_id", ""))}</title>
<style>{_CSS}</style></head><body><div class="wrap">

<header>{_MARK}<span class="brand">orq.ai</span><span class="kind">orq-arena run report</span></header>

<h1>{_e(champion)} leads the {len(ranked)}-model pool at ELO {champ_elo:.0f}</h1>
<p class="sub">{_e(manifest.get("tournament_id", ""))} &middot; {datestr}
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

<h2>Rounds and categories</h2>
<div class="badges">
  <span class="badge"><span class="sideA">A</span> wins <b>{verdicts["A"]}</b></span>
  <span class="badge"><span class="sideB">B</span> wins <b>{verdicts["B"]}</b></span>
  <span class="badge">ties <b>{verdicts["tie"]}</b></span>
  <span class="badge">inconclusive <b>{verdicts["inconclusive"]}</b></span>
  <span class="badge">{"voided <b>" + str(voids) + "</b>" if voids else "voided <b>0</b>"}</span>
</div>
<div class="tablewrap"><table>
<thead><tr><th>Category</th><th class="n">rated rounds</th><th>leader (where rated &ge; 20)</th></tr></thead>
<tbody>{"".join(cat_rows) or "<tr><td colspan='3'>no category data</td></tr>"}</tbody></table></div>
<p class="note">Inconclusive rounds carry no signal and are dropped from the rating, never
counted as ties. A voided round is a network failure, not a model failure; it is logged and
excluded.</p>

<h2>Tokens</h2>
<div class="tablewrap"><table>
<thead><tr><th></th><th class="n">input</th><th class="n">output</th></tr></thead>
<tbody>
<tr><td class="name">warriors</td><td class="n">{w_in:,}</td><td class="n">{w_out:,}</td></tr>
<tr><td class="name">jury</td><td class="n">{j_in:,}</td><td class="n">{j_out:,}</td></tr>
</tbody></table></div>

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
) -> Path:
    out = report_path_for(log_path)
    out.write_text(
        build_report_html(cfg=cfg, records=records, elo=elo, report=report, manifest=manifest)
    )
    return out
