"""The rounds browser: every round of a run on a page of its own, with filters.

The run report stays a summary and only links here. A run is hundreds of rounds and a
harness round carries two diffs and two trajectories, so the page ships each trial once
as JSON and builds a round's body only when it is opened. Everything a model or agent
wrote is put on the page with ``textContent``, never as markup.

Self-contained: one file, no network. ``orq-arena report <log>`` regenerates it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evaluatorq.common.reports import esc as _e

from .data.schemas import BattleRecord
from .judging import floor_abstained, vote_probabilities
from .redact import redact

# Caps for what is embedded per trial. The same cached trial appears in every match that drew
# it, so it is stored once and referenced; the full files stay in the trial directory.
DIFF_CAP = 16_000
STEPS_CAP = 16_000
TESTS_CAP = 4_000
STEP_BODY_CAP = 400
PROMPT_CAP = 20_000
RESPONSE_CAP = 20_000
WHY_CAP = 600
ROUNDS_CAP = 5_000
_TRUNC = "\n[truncated, the full file is in the trial directory]"


def rounds_path_for(report_path: str | Path) -> Path:
    """The rounds page that sits next to a report page (``x.report.html`` to ``x.rounds.html``)."""
    p = Path(report_path)
    name = p.name
    stem = name[: -len(".report.html")] if name.endswith(".report.html") else p.stem
    return p.with_name(stem + ".rounds.html")


def _cap(text: str, n: int, *, tail: bool = False) -> str:
    if len(text) <= n:
        return text
    return ("[truncated]\n" + text[-n:]) if tail else (text[:n] + _TRUNC)


def _read(sol: dict[str, Any], *parts: str, cap: int, tail: bool = False) -> str:
    trial_dir = sol.get("trial_dir") or ""
    if not trial_dir:
        return ""
    path = Path(trial_dir).joinpath(*parts)
    try:
        return _cap(path.read_text(encoding="utf-8", errors="replace"), cap, tail=tail)
    except OSError:
        return ""


def _trajectory(sol: dict[str, Any]) -> tuple[str, int]:
    """The trial's steps as plain text, and how many steps there are."""
    raw = _read(sol, "steps.json", cap=10**9)
    try:
        rows = json.loads(raw) if raw else []
    except ValueError:
        return "", 0
    if not isinstance(rows, list):
        return "", 0
    lines: list[str] = []
    n = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        n += 1
        lines.append(f"[{row.get('kind', '')}] {row.get('title', '')}")
        body = str(row.get("body") or "").strip()
        if body:
            clipped = body if len(body) <= STEP_BODY_CAP else body[:STEP_BODY_CAP].rstrip() + "…"
            lines.extend("    " + ln for ln in clipped.splitlines()[:12])
    return _cap("\n".join(lines), STEPS_CAP), n


def _trial(sol: dict[str, Any], dossier: str) -> dict[str, Any]:
    traj, n_steps = _trajectory(sol)
    cost = sol.get("cost_usd")
    return {
        "passed": sol.get("passed"),
        "reward": sol.get("reward"),
        "cost": cost if isinstance(cost, (int, float)) else None,
        "est": bool(sol.get("cost_estimated")),
        "steps": int(sol.get("steps") or 0),
        "cmds": int(sol.get("commands") or 0),
        "edits": int(sol.get("edits") or 0),
        "ms": int(sol.get("duration_ms") or 0),
        "exit": sol.get("exit_reason") or "unknown",
        "stat": sol.get("diff_stat") or "",
        "note": sol.get("diff_note") or "",
        "tests_edited": bool(sol.get("tests_edited")),
        "diff": _read(sol, "diff.patch", cap=DIFF_CAP),
        "traj": traj,
        "n_traj": n_steps,
        "tests": _read(sol, "verifier", "test-stdout.txt", cap=TESTS_CAP, tail=True),
        "dossier": dossier,
    }


def rounds_data(
    records: list[BattleRecord],
    alias: dict[str, str],
    labels: dict[str, str],
    floor: float | None,
) -> dict[str, Any]:
    """Everything the page needs: rounds in log order and each distinct trial once."""
    trials: dict[str, dict[str, Any]] = {}
    rounds: list[dict[str, Any]] = []
    for i, r in enumerate(records[:ROUNDS_CAP], 1):
        name_a = alias.get(r.rating_key("a"), r.model_a)
        name_b = alias.get(r.rating_key("b"), r.model_b)
        meta = r.prompt_metadata or {}
        harness = r.solution_a is not None or r.solution_b is not None
        keys: list[str | None] = []
        for side, sol, text in (
            ("a", r.solution_a, r.response_a),
            ("b", r.solution_b, r.response_b),
        ):
            if not harness:
                keys.append(None)
                continue
            sol = sol or {}
            key = sol.get("trial_dir") or f"round{i}{side}"
            if key not in trials:
                trials[key] = _trial(sol, _cap(text, RESPONSE_CAP))
            keys.append(key)
        votes = []
        for v in r.judge_votes:
            probs = vote_probabilities(v)
            votes.append(
                {
                    "judge": labels.get(str(v.get("model")), str(v.get("model", ""))),
                    "vote": v.get("vote"),
                    "flipped": bool(v.get("flipped")),
                    "floor": bool(floor_abstained(v, floor)),
                    "stand_in": bool(v.get("replacement")),
                    "why": (
                        " · ".join(f"{k} {probs[k]:.0%}" for k in ("A", "B", "tie"))
                        if probs
                        else (v.get("explanation") or "")[:WHY_CAP]
                    ),
                }
            )
        picks = {v["vote"] for v in votes if v["vote"]}
        rounds.append(
            {
                "i": i,
                "match": r.match_id,
                "n": r.round_number,
                "q": _cap(r.prompt_text, PROMPT_CAP),
                "cat": r.prompt_category or "",
                "task": meta.get("task_name") or "",
                "level": meta.get("difficulty") or "",
                "a": name_a,
                "b": name_b,
                "v": "void" if r.error else r.majority_verdict,
                "err": r.error or "",
                "gate": bool(r.decided_by_gate),
                "split": bool(
                    len(picks) > 1 or (not r.error and r.majority_verdict == "inconclusive")
                ),
                "votes": votes,
                "ta": keys[0],
                "tb": keys[1],
                "ra": "" if harness else _cap(r.response_a, RESPONSE_CAP),
                "rb": "" if harness else _cap(r.response_b, RESPONSE_CAP),
            }
        )
    return {
        "rounds": rounds,
        "trials": trials,
        "total": len(records),
        "capped": len(records) > ROUNDS_CAP,
    }


def _json_for_script(data: dict[str, Any]) -> str:
    """JSON safe inside a <script> block: nothing in it can close the tag or open a comment."""
    return (
        json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace(" ", "\\u2028")
        .replace(" ", "\\u2029")
    )


def build_rounds_html(
    *,
    records: list[BattleRecord],
    alias: dict[str, str],
    labels: dict[str, str],
    floor: float | None,
    title: str,
    report_href: str,
) -> str:
    """The standalone rounds page for one run."""
    from .report import _CSS  # imported late: report imports this module's path helper only

    data = rounds_data(records, alias, labels, floor)
    page = _TEMPLATE
    for key, value in (
        ("@@CSS@@", _CSS + _EXTRA_CSS),
        ("@@TITLE@@", _e(title)),
        ("@@REPORT@@", _e(report_href)),
        ("@@DATA@@", _json_for_script(data)),
    ):
        page = page.replace(key, value)
    return redact(page)


def write_rounds(path: Path, **kwargs: Any) -> Path:
    path.write_text(build_rounds_html(**kwargs), encoding="utf-8")
    return path


_EXTRA_CSS = """
.rf { border: 1px solid rgba(127,127,127,.3); border-radius: 8px; padding: 12px 14px; margin: 8px 0 14px; background: var(--surface, #fff); }
.rf-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 10px; }
.rf-row + .rf-row { margin-top: 10px; }
.rf input[type=search], .rf select { font: inherit; font-size: 13.5px; padding: 6px 8px; min-width: 0;
  border: 1px solid rgba(127,127,127,.4); border-radius: 6px; background: var(--surface, #fff); color: inherit; }
.rf input[type=search] { flex: 1 1 260px; }
.rf select { flex: 0 1 200px; }
.rf [hidden] { display: none; }
.rf-vs { color: var(--gray-500); font-size: 13px; }
.rf-pills { display: flex; flex-wrap: wrap; gap: 6px; }
.rf-pill { font: inherit; font-size: 13px; padding: 4px 12px; border-radius: 999px; cursor: pointer;
  border: 1px solid rgba(127,127,127,.4); background: transparent; color: inherit; }
.rf-pill[aria-pressed=true] { background: var(--slate, #1d2129); border-color: var(--slate, #1d2129); color: #fff; }
.rf-more { font-size: 13px; }
.rf-more > summary { cursor: pointer; color: var(--gray-500); list-style: none; }
.rf-more > summary::before { content: "+ "; } .rf-more[open] > summary::before { content: "- "; }
.rf-more-grid { display: flex; flex-wrap: wrap; gap: 8px 14px; margin-top: 8px; }
.rf-more-grid label { display: flex; flex-direction: column; gap: 2px; font-size: 11px; text-transform: uppercase;
  letter-spacing: .04em; color: var(--gray-500); }
.rf-more-grid select { text-transform: none; letter-spacing: 0; }
.rf-status { display: flex; align-items: center; gap: 12px; font-size: 13px; color: var(--gray-500); }
.rf-count { font-weight: 600; color: inherit; font-variant-numeric: tabular-nums; }
.rf-clear { font: inherit; font-size: 12.5px; background: none; border: 0; cursor: pointer; color: var(--link, #3b6fd4); padding: 0; }
.rd[hidden] { display: none; }
.rd-empty { padding: 28px 0; color: var(--gray-500); }
.rd-prompt { white-space: pre-wrap; word-break: break-word; }
.rd-note { font-size: 13px; color: var(--gray-700); margin: 6px 0; }
.pw-cmp.rd { padding: 0; }
.pw-cmp.rd > summary { display: grid; grid-template-columns: 38px 1fr auto; align-items: center; gap: 4px 12px; padding: 10px 14px; }
.pw-cmp.rd[open] > summary { border-bottom: 1px solid rgba(127,127,127,.2); }
.pw-cmp.rd > *:not(summary) { margin-left: 14px; margin-right: 14px; }
.pw-cmp.rd > :last-child { margin-bottom: 12px; }
.rd-title { font-weight: 600; overflow-wrap: anywhere; }
.rd-pair { font-size: 13px; color: var(--gray-500); }
.rd-meta { font-size: 12px; color: var(--gray-500); }
.rd-end { display: flex; align-items: center; gap: 8px; justify-content: flex-end; text-align: right; }
.rd-warn { color: #d9534f; font-size: 13px; }
"""

# The page. Placeholders are replaced, never formatted, because the script is full of braces.
_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Rounds · @@TITLE@@</title>
<style>@@CSS@@</style></head>
<body><div class="container">
<header class="hero"><p class="meta">@@TITLE@@ &middot; ROUNDS</p>
<h1>Rounds</h1>
<p class="lede"><a href="@@REPORT@@">&larr; back to the run report</a></p></header>
<div class="rf" id="rf">
 <div class="rf-row">
  <input type="search" id="f-q" placeholder="Search a task, prompt or agent" aria-label="search">
  <select id="f-who" aria-label="agent"></select>
  <span class="rf-vs" id="vs-wrap" hidden>vs <select id="f-vs" aria-label="versus"></select></span>
  <select id="f-task" aria-label="task"></select>
 </div>
 <div class="rf-row">
  <div class="rf-pills" id="pills" role="group" aria-label="outcome"></div>
 </div>
 <div class="rf-row">
  <details class="rf-more" id="more"><summary>More filters</summary>
   <div class="rf-more-grid">
    <label>winner<select id="f-win"></select></label>
    <label id="l-tests">hidden tests<select id="f-tests"><option value="">any</option>
     <option value="both-pass">both passed</option><option value="both-fail">both failed</option>
     <option value="one">exactly one passed</option><option value="edited">edited tests/</option></select></label>
    <label>match<select id="f-match"></select></label>
    <label id="l-cat">category<select id="f-cat"></select></label>
    <label>judges<select id="f-panel"><option value="">any</option><option value="flipped">a vote flipped</option>
     <option value="abstained">a judge abstained</option><option value="standin">a stand-in voted</option></select></label>
    <label>order<select id="f-sort"><option value="">log order</option><option value="split">panel splits first</option>
     <option value="task">by task</option></select></label>
   </div>
  </details>
  <span class="rf-status"><span class="rf-count" id="count"></span><button class="rf-clear" id="reset" type="button">clear filters</button>
   <span id="capnote"></span></span>
 </div>
</div>
<div id="list"></div>
<p class="rd-empty" id="empty" hidden>No round matches these filters.</p>
</div>
<script id="data" type="application/json">@@DATA@@</script>
<script>
(function () {
const D = JSON.parse(document.getElementById('data').textContent);
const R = D.rounds, T = D.trials;
const $ = id => document.getElementById(id);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const uniq = xs => [...new Set(xs.filter(x => x !== '' && x != null))];
const fmtDur = ms => { const s = Math.floor(ms / 1000); return s >= 60 ? Math.floor(s / 60) + 'm ' + String(s % 60).padStart(2, '0') + 's' : s + 's'; };
const fmtUsd = v => v == null ? 'cost unknown' : '$' + (v < 0.1 ? v.toFixed(3) : v.toFixed(2));
const winnerOf = r => r.v === 'A' ? r.a : r.v === 'B' ? r.b : '';
const harness = R.some(r => r.ta || r.tb);

const FIELDS = ['q', 'who', 'vs', 'task', 'show', 'win', 'tests', 'match', 'cat', 'panel', 'sort'];
const PILLS = [['', 'All'], ['tests', 'Decided by tests'], ['jury', 'Decided by jury'], ['tie', 'Tie or no result'], ['split', 'Panel split'], ['void', 'Voided']];
const names = uniq(R.flatMap(r => [r.a, r.b])).sort();
function fill(id, first, values) {
  const s = $(id); s.textContent = '';
  for (const [v, t] of [['', first], ...values.map(x => [x, x])]) { const o = el('option', null, t); o.value = v; s.appendChild(o); }
}
fill('f-who', 'Any agent', names); fill('f-vs', 'any opponent', names);
fill('f-win', 'any', [...names, '(tie)']);
fill('f-task', harness ? 'Any task' : 'Any prompt category', harness ? uniq(R.map(r => r.task)).sort() : uniq(R.map(r => r.cat)).sort());
fill('f-cat', 'any', uniq(R.map(r => r.cat)).sort());
fill('f-match', 'any', uniq(R.map(r => r.match)));
$('l-tests').hidden = !harness;
$('l-cat').hidden = !harness || uniq(R.map(r => r.cat)).length < 2;
if (D.capped) $('capnote').textContent = 'Showing the first ' + R.length + ' of ' + D.total + ' rounds.';
let show = '';
const pills = $('pills');
for (const [v, t] of PILLS) {
  const b = el('button', 'rf-pill', t); b.type = 'button'; b.dataset.v = v; b.setAttribute('aria-pressed', v === '' ? 'true' : 'false');
  b.addEventListener('click', () => { show = v; apply(); }); pills.appendChild(b);
}

const field = f => f === 'show' ? { get value() { return show; }, set value(v) { show = v; } } : $('f-' + f);
function state() { const s = {}; for (const f of FIELDS) { const v = field(f).value; if (v) s[f] = v; } return s; }
function writeHash() { const p = new URLSearchParams(state()).toString(); history.replaceState(null, '', p ? '#' + p : location.pathname + location.search); }
function readHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  for (const f of FIELDS) { const f_ = field(f); const v = p.get(f) || ''; f_.value = v; if (f !== 'show' && f_.value !== v) f_.value = ''; }
}

function matches(r, s) {
  if (s.q) { const hay = (r.q + ' ' + r.task + ' ' + r.a + ' ' + r.b).toLowerCase(); if (!hay.includes(s.q.toLowerCase())) return false; }
  if (s.who && r.a !== s.who && r.b !== s.who) return false;
  if (s.vs) { if (s.who ? !((r.a === s.who && r.b === s.vs) || (r.b === s.who && r.a === s.vs)) : (r.a !== s.vs && r.b !== s.vs)) return false; }
  if (s.task && (harness ? r.task : r.cat) !== s.task) return false;
  if (s.cat && r.cat !== s.cat) return false;
  if (s.match && r.match !== s.match) return false;
  if (s.win) { if (s.win === '(tie)' ? r.v !== 'tie' : winnerOf(r) !== s.win) return false; }
  if (s.show === 'tests' && !r.gate) return false;
  if (s.show === 'jury' && (r.gate || !(r.v === 'A' || r.v === 'B'))) return false;
  if (s.show === 'tie' && !(r.v === 'tie' || r.v === 'inconclusive')) return false;
  if (s.show === 'split' && !r.split) return false;
  if (s.show === 'void' && r.v !== 'void') return false;
  if (s.tests) {
    if (!r.ta || !r.tb) return false;
    const pa = T[r.ta].passed, pb = T[r.tb].passed;
    if (s.tests === 'both-pass' && !(pa === true && pb === true)) return false;
    if (s.tests === 'both-fail' && !(pa === false && pb === false)) return false;
    if (s.tests === 'one' && !((pa === true) !== (pb === true))) return false;
    if (s.tests === 'edited' && !(T[r.ta].tests_edited || T[r.tb].tests_edited)) return false;
  }
  if (s.panel === 'flipped' && !r.votes.some(v => v.flipped)) return false;
  if (s.panel === 'abstained' && !r.votes.some(v => v.vote == null)) return false;
  if (s.panel === 'standin' && !r.votes.some(v => v.stand_in)) return false;
  return true;
}

function badge(text, tone) { return el('span', 'status-badge status-badge--' + tone, text); }
function verdictBadge(r) {
  if (r.v === 'A') return badge(r.a + ' wins', 'pass');
  if (r.v === 'B') return badge(r.b + ' wins', 'pass');
  if (r.v === 'tie') return badge('tie', 'neutral');
  if (r.v === 'void') return badge('voided', 'fail');
  return badge('no result', 'warn');
}
function chip(v) {
  const tone = v.vote === 'A' ? 'a' : v.vote === 'B' ? 'b' : 'tie';
  const c = el('span', v.vote == null ? 'pw-chip pw-chip--abstain' : 'pw-chip pw-chip--' + tone, v.vote == null ? '·' : v.vote);
  if (v.flipped) c.classList.add('pw-chip--flip');
  c.title = v.judge + (v.vote == null ? ' abstained' : '');
  return c;
}
function pre(text) { const p = el('pre'); p.textContent = text; return p; }
function details(summary, text) { const d = el('details'); d.append(el('summary', null, summary), pre(text)); return d; }

function trialPane(letter, name, key, gated) {
  const t = T[key], box = el('div', 'pw-response hx');
  const h = el('h4'); h.append(el('span', 'side' + letter, letter), ' ' + name); box.appendChild(h);
  const p = el('p');
  const word = t.passed === true ? '✓ hidden tests PASSED' : t.passed === false ? '✗ hidden tests FAILED' : 'hidden tests not run';
  p.appendChild(badge(word + (typeof t.reward === 'number' ? ' (reward ' + t.reward + ')' : ''), t.passed === true ? 'pass' : t.passed === false ? 'fail' : 'neutral'));
  box.appendChild(p);
  box.appendChild(el('p', 'hx-counts', t.steps + ' steps · ' + t.cmds + ' cmds · ' + t.edits + ' edits · ' + fmtDur(t.ms) + ' · ' +
    fmtUsd(t.cost) + (t.cost == null ? '' : t.est ? ' (estimated)' : ' (observed)')));
  box.appendChild(el('p', 'hx-exit', 'exit: ' + t.exit));
  const stat = t.stat + (t.tests_edited ? '  ⚠ tests/ edited' : '');
  if (t.diff.trim()) box.appendChild(details('diff ' + stat, t.diff));
  else if (stat.trim()) box.appendChild(el('p', 'hx-exit', 'diff ' + stat));
  else if (t.note) box.appendChild(el('p', 'hx-exit', t.note));
  if (t.traj) box.appendChild(details('trajectory, ' + t.n_traj + ' steps', t.traj));
  if (t.tests.trim()) box.appendChild(details('test output', t.tests));
  if (!gated && t.dossier) box.appendChild(details('dossier the jury read', t.dossier));
  return box;
}

function build(r, body) {
  if (r.err) body.appendChild(el('p', 'rd-note', 'voided: ' + r.err));
  if (r.task) { const d = details('Task instructions', r.q); body.appendChild(d); }
  else if (r.q.length > 140) { body.appendChild(el('h4', null, 'Prompt')); const p = el('div', 'rd-prompt'); p.textContent = r.q; body.appendChild(p); }
  const panes = el('div', 'pw-responses');
  if (r.ta || r.tb) {
    if (r.ta) panes.appendChild(trialPane('A', r.a, r.ta, r.gate));
    if (r.tb) panes.appendChild(trialPane('B', r.b, r.tb, r.gate));
  } else {
    for (const [letter, name, text] of [['A', r.a, r.ra], ['B', r.b, r.rb]]) {
      const box = el('div', 'pw-response'); const h = el('h4'); h.append(el('span', 'side' + letter, letter), ' ' + name);
      box.append(h, pre(text)); panes.appendChild(box);
    }
  }
  body.appendChild(panes);
  if (r.gate) body.appendChild(el('p', 'rd-note', 'The jury was skipped: exactly one side passed the hidden tests, so the tests decided this round.'));
  if (r.votes.length) body.appendChild(el('h4', null, 'Judges'));
  const ul = el('ul', 'pw-votes');
  for (const v of r.votes) {
    const li = el('li', 'pw-vote');
    li.append(el('span', 'pw-vote__model', v.judge), chip(v));
    if (v.flipped) li.appendChild(el('span', 'pw-tag pw-tag--flip', 'flipped'));
    if (v.floor) li.appendChild(el('span', 'pw-tag', 'under floor'));
    if (v.stand_in) li.appendChild(el('span', 'pw-tag', 'stand-in'));
    li.appendChild(el('span', 'pw-vote__why', v.why));
    ul.appendChild(li);
  }
  body.appendChild(ul);
}

const rows = R.map(r => {
  const d = el('details', 'pw-cmp rd'), sum = el('summary');
  const main = el('div');
  const title = r.task ? r.task + (r.level ? ' · ' + r.level : '') : (r.q.length > 140 ? r.q.slice(0, 140) + '…' : r.q);
  const pair = el('div', 'rd-pair');
  pair.append(el('span', 'sideA', 'A'), ' ' + r.a + '  vs  ', el('span', 'sideB', 'B'), ' ' + r.b);
  const how = r.v === 'void' ? 'voided' : r.gate ? 'decided by tests' : 'decided by jury';
  main.append(el('div', 'rd-title', title), pair, el('div', 'rd-meta', [r.match ? r.match + ' · round ' + r.n : '', how].filter(Boolean).join(' · ')));
  const end = el('div', 'rd-end');
  if (r.split) { const w = el('span', 'rd-warn', '⚠ split'); w.title = 'the panel split or could not decide'; end.appendChild(w); }
  end.appendChild(verdictBadge(r));
  sum.append(el('span', 'pw-cmp__idx', String(r.i)), main, end);
  d.appendChild(sum);
  let built = false;
  d.addEventListener('toggle', () => { if (d.open && !built) { built = true; build(r, d); } });
  return d;
});
const list = $('list'); rows.forEach(d => list.appendChild(d));

function apply() {
  const s = state();
  let order = R.map((r, k) => k);
  if (s.sort === 'split') order.sort((x, y) => (R[y].split - R[x].split) || (x - y));
  if (s.sort === 'task') order.sort((x, y) => R[x].task.localeCompare(R[y].task) || (x - y));
  let shown = 0;
  for (const k of order) { const ok = matches(R[k], s); rows[k].hidden = !ok; if (ok) shown++; list.appendChild(rows[k]); }
  $('count').textContent = shown + ' of ' + R.length + ' rounds';
  $('empty').hidden = shown > 0;
  $('vs-wrap').hidden = !s.who;
  if (!s.who && $('f-vs').value) { $('f-vs').value = ''; }
  pills.querySelectorAll('.rf-pill').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.v === show)));
  $('reset').hidden = Object.keys(s).length === 0;
  if (s.win || s.tests || s.match || s.cat || s.panel || s.sort) $('more').open = true;
  writeHash();
}
for (const f of FIELDS) if (f !== 'show') $('f-' + f).addEventListener(f === 'q' ? 'input' : 'change', apply);
$('reset').addEventListener('click', () => { for (const f of FIELDS) field(f).value = ''; apply(); });
window.addEventListener('hashchange', () => { readHash(); apply(); });
readHash(); apply();
})();
</script></body></html>
"""
