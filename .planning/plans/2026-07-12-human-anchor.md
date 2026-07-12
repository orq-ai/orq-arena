# G5: Human-Anchor Annotation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Blind human annotation of recorded rounds via a static HTML page, merged back into a human-vs-panel Cohen's κ and Bradley-Terry rank correlation, converting the jury from "self-consistent" to "human-anchored".

**Architecture:** Two new CLI commands on one new module. `orq-arena annotate battles.jsonl` renders a self-contained blinded annotation page (same static-file mold as `report.py`: no server, works from `file://`, no external assets); the rater votes with keyboard, exports `votes.json`. `orq-arena anchor battles.jsonl votes.json [...]` merges vote files against the log and prints κ + Spearman using the existing `analysis/kappa.py` and `rejudge.py`/`tournament/elo.py` machinery. No TUI screen (decision 28); no new dependencies.

**Tech Stack:** Python (stdlib + existing deps only: pydantic, click, rich), vanilla inline JS/CSS in the generated page.

## Global Constraints

- Blinding contract (decision 29): the generated page must contain **no model names, no jury votes, no majority verdicts, no winner strings**. Round keys are one-way hashes. Side order is flipped per round by seeded RNG.
- Self-contained page: no CDN, no fetch, no external assets; must work from `file://`. Votes leave via a download button, never a network call.
- Pure stdlib for all math; no numpy (house rule, see `elo.py`).
- No em-dashes in any prose (docs, page copy, docstrings).
- Existing code reused, not duplicated: `load_records`, `outcomes_from_majorities`, `spearman` from `src/orq_arena/rejudge.py`; `bradley_terry_mle`, `build_wins_matrix` from `src/orq_arena/tournament/elo.py`; `cohen_kappa_pairs`, `landis_koch` from `src/orq_arena/analysis/kappa.py` (returns `{pair_label: {"kappa": float|None, "label": str, "rounds": int}}`).
- `BattleRecord` fields used: `prompt_hash`, `prompt_text`, `model_a`, `model_b`, `response_a`, `response_b`, `majority_verdict` (`'A'|'B'|'tie'|'inconclusive'`), `match_id`, `round_number`, `error`.
- Tests follow house style: plain pytest functions, no fixtures/classes, hand-computed expected values (see `tests/test_damage.py`, `tests/test_preflight_cost.py`).

---

### Task 1: Round keys and blinded annotation items

**Files:**
- Create: `src/orq_arena/anchor.py`
- Test: `tests/test_anchor_items.py`

**Interfaces:**
- Consumes: `BattleRecord` (`src/orq_arena/data/schemas.py`).
- Produces: `record_key(rec: BattleRecord) -> str` (16-hex one-way key, stable across runs); `annotation_items(records: list[BattleRecord], *, seed: int = 42, sample: int | None = None) -> list[dict]` where each dict is `{"k": str, "q": str, "a": str, "b": str, "f": bool}` (`a`/`b` are canonical responses, `f` = display-flipped), shuffled deterministically by `seed`.

- [ ] **Step 1: Write the failing test**

```python
"""Round keys and blinded item extraction."""

from orq_arena.anchor import annotation_items, record_key
from orq_arena.data.schemas import BattleRecord


def _rec(i: int, verdict: str = "A") -> BattleRecord:
    return BattleRecord(
        prompt_hash=f"hash{i}", prompt_text=f"prompt {i}",
        model_a="model-one", model_b="model-two",
        response_a=f"answer a {i}", response_b=f"answer b {i}",
        majority_verdict=verdict, match_id="m1", round_number=i,
    )


RECORDS = [_rec(i) for i in range(6)]


def test_record_key_is_stable_and_opaque():
    k1, k2 = record_key(RECORDS[0]), record_key(RECORDS[0])
    assert k1 == k2 and len(k1) == 16
    assert "model-one" not in k1 and k1 != record_key(RECORDS[1])


def test_items_are_seeded_shuffled_and_blind():
    items = annotation_items(RECORDS, seed=7)
    assert items == annotation_items(RECORDS, seed=7)          # deterministic
    assert [i["k"] for i in items] != [record_key(r) for r in RECORDS]  # shuffled
    keys = {i["k"] for i in items}
    assert keys == {record_key(r) for r in RECORDS}
    for it in items:
        assert set(it) == {"k", "q", "a", "b", "f"}            # nothing extra leaks


def test_flip_is_seeded_per_key_and_mixed():
    items = annotation_items(RECORDS, seed=7)
    again = {i["k"]: i["f"] for i in annotation_items(RECORDS, seed=7)}
    assert all(again[i["k"]] == i["f"] for i in items)
    assert annotation_items(RECORDS, seed=8) != items          # seed changes order/flips


def test_sample_truncates_after_shuffle():
    assert len(annotation_items(RECORDS, seed=7, sample=3)) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_anchor_items.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'orq_arena.anchor'`

- [ ] **Step 3: Write minimal implementation**

Create `src/orq_arena/anchor.py`:

```python
"""Human-anchor annotation: blinded static page + vote merge.

``annotate`` renders battles.jsonl into one self-contained HTML page a
rater opens from file://, reads both responses blind (no model names, no
jury votes, seeded side order, decision 29), and votes with a/b/t/space;
votes export as votes.json. ``anchor`` merges vote files back against the
log and reports human-vs-panel Cohen's kappa and Bradley-Terry rank
correlation (decision 28, pulled forward from PR 11.4).
"""

from __future__ import annotations

import hashlib
import random

from .data.schemas import BattleRecord


def record_key(rec: BattleRecord) -> str:
    """One-way 16-hex key; recomputable from the log, opaque in the page."""
    raw = f"{rec.prompt_hash}:{rec.model_a}:{rec.model_b}:{rec.match_id}:{rec.round_number}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def annotation_items(
    records: list[BattleRecord], *, seed: int = 42, sample: int | None = None
) -> list[dict]:
    """Blinded page payload: canonical responses + per-round display flip."""
    items = []
    for rec in records:
        key = record_key(rec)
        items.append({
            "k": key,
            "q": rec.prompt_text,
            "a": rec.response_a,
            "b": rec.response_b,
            "f": random.Random(f"{seed}:{key}").random() < 0.5,
        })
    random.Random(seed).shuffle(items)
    return items[:sample] if sample else items
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_anchor_items.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/orq_arena/anchor.py tests/test_anchor_items.py
git commit -m "feat: blinded annotation items with one-way round keys"
```

### Task 2: Blinded annotation page renderer

**Files:**
- Modify: `src/orq_arena/anchor.py` (append)
- Test: `tests/test_anchor_page.py`

**Interfaces:**
- Consumes: `annotation_items` output (Task 1).
- Produces: `render_annotate_page(items: list[dict], *, seed: int, source: str) -> str` returning a complete HTML document. Exported vote file shape (consumed by Task 3): `{"schema": 1, "seed": int, "source": str, "annotator": str, "votes": {key: "A"|"B"|"tie"}}` in the **canonical** frame (the page un-flips before export).

**Page spec:**
- Palette and fonts follow `report.py` (`--paper #faf8f3`, `--ink #141319`, `--teal #00342d`, side accents `--a #c8189e` / `--b #0092ab` used only as neutral left/right markers, never labeled with model names).
- Layout: header (progress `n / total`, source name, annotator name input), prompt card, two response panels side by side (stack under 900px), footer with key legend.
- Keys: `a` vote left, `b` vote right, `t` tie, `space` skip, `ArrowLeft`/`ArrowRight` navigate. Buttons mirror every key.
- Votes are stored canonical: left maps to `f ? "B" : "A"`, right to `f ? "A" : "B"`.
- Export: "download votes.json" button always visible; auto-triggers when the last round is voted. `beforeunload` warns when votes exist and were not downloaded. localStorage is used as a best-effort crash cache only (file:// origins are flaky), keyed by `source + seed`.
- Markdown: escape HTML first, then render fenced code blocks, inline code, `#`-headers, bold, italics, unordered/ordered lists, paragraphs. Nothing else. (~60 lines of JS, included below.)

- [ ] **Step 1: Write the failing test**

```python
"""The annotation page must be blind and self-contained."""

from orq_arena.anchor import annotation_items, render_annotate_page
from tests.test_anchor_items import RECORDS  # same synthetic records


def _page() -> str:
    items = annotation_items(RECORDS, seed=7)
    return render_annotate_page(items, seed=7, source="battles.jsonl")


def test_page_is_blind():
    page = _page()
    assert "model-one" not in page and "model-two" not in page
    assert "majority_verdict" not in page and "judge" not in page.lower()


def test_page_is_self_contained_and_complete():
    page = _page()
    assert page.startswith("<!doctype html>")
    for token in ("http://", "https://", "src=", "@import"):
        assert token not in page  # no external assets, no CDN
    assert "answer a 0" in page and "votes.json" in page
    assert '"seed": 7' in page or '"seed":7' in page


def test_page_embeds_all_items_once():
    page = _page()
    for rec_text in (f"prompt {i}" for i in range(6)):
        assert page.count(rec_text) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_anchor_page.py -q`
Expected: FAIL with `ImportError: cannot import name 'render_annotate_page'`

- [ ] **Step 3: Write the implementation**

Append to `src/orq_arena/anchor.py` (imports: add `import json`):

```python
_PAGE_CSS = """
:root { --ink:#141319; --paper:#faf8f3; --card:#fff; --line:#e6e1d6;
  --teal:#00342d; --muted:#7a766c; --a:#c8189e; --b:#0092ab;
  --mono:"SF Mono","JetBrains Mono",ui-monospace,Menlo,monospace;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif; }
*{box-sizing:border-box} body{margin:0;background:var(--paper);color:var(--ink);
  font-family:var(--sans);line-height:1.55}
.wrap{max-width:1200px;margin:0 auto;padding:0 24px 90px}
header{display:flex;gap:14px;align-items:center;padding:18px 0;border-bottom:2px solid var(--teal)}
header .prog{font-family:var(--mono);font-size:13px;color:var(--muted);margin-left:auto}
header input{font:inherit;padding:4px 8px;border:1px solid var(--line);border-radius:6px}
.prompt{background:var(--card);border:1px solid var(--line);border-radius:10px;
  padding:14px 18px;margin:18px 0;font-size:15px}
.duel{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:900px){.duel{grid-template-columns:1fr}}
.resp{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:4px 18px 14px;
  overflow-wrap:break-word}
.resp h3{font-family:var(--mono);font-size:12px;text-transform:uppercase;letter-spacing:.08em}
.resp.left h3{color:var(--a)} .resp.right h3{color:var(--b)}
.resp.voted{outline:3px solid var(--teal)}
.resp pre{background:#f0ede4;padding:10px;border-radius:6px;overflow-x:auto}
.resp code{font-family:var(--mono);font-size:12.5px;background:#f0ede4;padding:1px 4px;border-radius:3px}
.bar{position:fixed;bottom:0;left:0;right:0;background:var(--card);border-top:1px solid var(--line);
  display:flex;gap:10px;justify-content:center;padding:12px}
.bar button{font:inherit;padding:8px 18px;border:1px solid var(--line);border-radius:8px;
  background:var(--paper);cursor:pointer}
.bar button:hover{border-color:var(--teal)}
.bar .key{font-family:var(--mono);font-size:11px;color:var(--muted)}
"""

_PAGE_JS = """
const D = JSON.parse(document.getElementById('data').textContent);
let idx = 0; const votes = {};
const cacheKey = 'orq-anchor:' + D.source + ':' + D.seed;
try { Object.assign(votes, JSON.parse(localStorage.getItem(cacheKey) || '{}')); } catch (e) {}
let downloaded = false;

function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function md(src){
  const out=[]; const lines=esc(src).split('\\n'); let i=0;
  function inline(s){return s
    .replace(/`([^`]+)`/g,'<code>$1</code>')
    .replace(/\\*\\*([^*]+)\\*\\*/g,'<b>$1</b>')
    .replace(/\\*([^*]+)\\*/g,'<i>$1</i>');}
  while(i<lines.length){
    const l=lines[i];
    if(l.startsWith('```')){const buf=[];i++;
      while(i<lines.length&&!lines[i].startsWith('```')){buf.push(lines[i]);i++;}
      i++; out.push('<pre><code>'+buf.join('\\n')+'</code></pre>'); continue;}
    const h=l.match(/^(#{1,4}) (.*)/);
    if(h){out.push('<h'+(h[1].length+2)+'>'+inline(h[2])+'</h'+(h[1].length+2)+'>');i++;continue;}
    if(/^[-*] /.test(l)){const buf=[];
      while(i<lines.length&&/^[-*] /.test(lines[i])){buf.push('<li>'+inline(lines[i].slice(2))+'</li>');i++;}
      out.push('<ul>'+buf.join('')+'</ul>');continue;}
    if(/^\\d+\\. /.test(l)){const buf=[];
      while(i<lines.length&&/^\\d+\\. /.test(lines[i])){buf.push('<li>'+inline(lines[i].replace(/^\\d+\\. /,''))+'</li>');i++;}
      out.push('<ol>'+buf.join('')+'</ol>');continue;}
    if(l.trim()===''){i++;continue;}
    const buf=[]; while(i<lines.length&&lines[i].trim()!==''){buf.push(inline(lines[i]));i++;}
    out.push('<p>'+buf.join('<br>')+'</p>');
  }
  return out.join('');
}
function canon(side){const it=D.items[idx]; if(side==='tie')return 'tie';
  return (side==='left')===(!it.f)?'A':'B';}
function shown(it){return it.f?[it.b,it.a]:[it.a,it.b];}
function render(){
  const it=D.items[idx]; const [l,r]=shown(it);
  document.getElementById('prog').textContent=(idx+1)+' / '+D.items.length+
    '  ·  voted '+Object.keys(votes).length;
  document.getElementById('prompt').innerHTML=md(it.q);
  document.getElementById('left').innerHTML='<h3>Response 1</h3>'+md(l);
  document.getElementById('right').innerHTML='<h3>Response 2</h3>'+md(r);
  const v=votes[it.k];
  document.getElementById('lpane').classList.toggle('voted',v===canonSideOf('left'));
  document.getElementById('rpane').classList.toggle('voted',v===canonSideOf('right'));
  function canonSideOf(side){const t=idx;return (side==='left')===(!it.f)?'A':'B';}
}
function vote(side){const it=D.items[idx];
  if(side==='skip'){delete votes[it.k];}else{votes[it.k]=canon(side);}
  try{localStorage.setItem(cacheKey,JSON.stringify(votes));}catch(e){}
  if(idx<D.items.length-1){idx++;render();}
  else{render(); if(Object.keys(votes).length===D.items.length) download();}
}
function download(){
  const name=document.getElementById('annotator').value||'anonymous';
  const payload={schema:1,seed:D.seed,source:D.source,annotator:name,votes:votes};
  const a=document.createElement('a');
  a.href=URL.createObjectURL(new Blob([JSON.stringify(payload,null,1)],{type:'application/json'}));
  a.download='votes.json'; a.click(); downloaded=true;
}
document.addEventListener('keydown',e=>{
  if(e.target.tagName==='INPUT')return;
  if(e.key==='a')vote('left'); else if(e.key==='b')vote('right');
  else if(e.key==='t')vote('tie'); else if(e.key===' '){e.preventDefault();vote('skip');}
  else if(e.key==='ArrowRight'&&idx<D.items.length-1){idx++;render();}
  else if(e.key==='ArrowLeft'&&idx>0){idx--;render();}
});
window.addEventListener('beforeunload',e=>{
  if(Object.keys(votes).length&&!downloaded)e.preventDefault();});
render();
"""


def render_annotate_page(items: list[dict], *, seed: int, source: str) -> str:
    """One self-contained blinded page; votes leave only via download."""
    payload = json.dumps({"seed": seed, "source": source, "items": items})
    payload = payload.replace("</", "<\\/")  # keep </script> inert inside the data block
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>orq-arena blind annotation</title>
<style>{_PAGE_CSS}</style></head><body>
<div class="wrap">
<header><b>blind annotation</b>
<input id="annotator" placeholder="your name">
<span class="prog" id="prog"></span></header>
<div class="prompt" id="prompt"></div>
<div class="duel">
<div class="resp left" id="lpane"><div id="left"></div></div>
<div class="resp right" id="rpane"><div id="right"></div></div>
</div>
<div class="bar">
<button onclick="vote('left')">1 better <span class="key">a</span></button>
<button onclick="vote('tie')">tie <span class="key">t</span></button>
<button onclick="vote('right')">2 better <span class="key">b</span></button>
<button onclick="vote('skip')">skip <span class="key">space</span></button>
<button onclick="download()">download votes.json</button>
</div>
</div>
<script id="data" type="application/json">{payload}</script>
<script>{_PAGE_JS}</script>
</body></html>"""
```

Note for the implementer: the `render()` function above contains a redundant inner `canonSideOf`; simplify while keeping behavior (highlight the voted pane in canonical terms). Behavior, not the sketch, is the contract; the tests define it.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_anchor_page.py -q`
Expected: 3 passed

- [ ] **Step 5: Manual smoke check (required, browser)**

Generate a page from a real log and open it:

```bash
uv run python -c "
from orq_arena.rejudge import load_records
from orq_arena.anchor import annotation_items, render_annotate_page
recs = load_records('outputs/g1/battles.jsonl')
items = annotation_items(recs, seed=42, sample=10)
open('/tmp/annotate-smoke.html','w').write(render_annotate_page(items, seed=42, source='g1'))
"
open /tmp/annotate-smoke.html
```

Verify: keys a/b/t/space vote and advance, arrows navigate, markdown and code fences render, votes.json downloads with canonical A/B/tie values, no model name visible anywhere including view-source.

- [ ] **Step 6: Commit**

```bash
git add src/orq_arena/anchor.py tests/test_anchor_page.py
git commit -m "feat: blinded static annotation page with canonical vote export"
```

### Task 3: Vote loading and anchor math

**Files:**
- Modify: `src/orq_arena/anchor.py` (append)
- Test: `tests/test_anchor_math.py`

**Interfaces:**
- Consumes: `record_key` (Task 1); votes.json shape (Task 2); `outcomes_from_majorities`, `spearman` from `rejudge.py`; `bradley_terry_mle`, `build_wins_matrix` from `tournament/elo.py`; `cohen_kappa_pairs` from `analysis/kappa.py`.
- Produces: `load_votes(paths: list[str | Path]) -> list[VoteSet]` with `VoteSet(annotator: str, seed: int, source: str, votes: dict[str, str])`; `anchor_result(records: list[BattleRecord], votesets: list[VoteSet]) -> dict` with keys `per_annotator` (list of dicts: `annotator`, `n_voted`, `n_kappa` co-decisive rounds, `kappa`, `kappa_label`, `spearman`), `inter_annotator` (list of dicts: `pair`, `kappa`, `kappa_label`, `rounds`), `panel_ranking`, `unknown_keys` (votes not matching any record).

- [ ] **Step 1: Write the failing test**

```python
"""Anchor math: human votes vs panel, hand-checked."""

import json

from orq_arena.anchor import VoteSet, anchor_result, load_votes, record_key
from tests.test_anchor_items import _rec

# 4 records; panel says A on all four.
RECORDS = [_rec(i, verdict="A") for i in range(4)]
KEYS = [record_key(r) for r in RECORDS]


def _vs(name: str, votes: dict) -> VoteSet:
    return VoteSet(annotator=name, seed=42, source="test", votes=votes)


def test_perfect_agreement_needs_vote_variety_for_kappa():
    # All-A on both sides: observed agreement 1.0 but chance is also 1.0;
    # cohen_kappa_pairs defines kappa = 1.0 there.
    res = anchor_result(RECORDS, [_vs("h1", {k: "A" for k in KEYS})])
    row = res["per_annotator"][0]
    assert row["kappa"] == 1.0 and row["n_kappa"] == 4
    assert row["spearman"] == 1.0


def test_total_disagreement_gives_negative_or_zero_kappa():
    res = anchor_result(RECORDS, [_vs("h1", {k: "B" for k in KEYS})])
    row = res["per_annotator"][0]
    assert row["kappa"] is not None and row["kappa"] <= 0.0


def test_inconclusive_rounds_are_excluded_from_kappa_not_bt():
    recs = [_rec(0, "A"), _rec(1, "inconclusive")]
    keys = [record_key(r) for r in recs]
    res = anchor_result(recs, [_vs("h1", {keys[0]: "A", keys[1]: "B"})])
    row = res["per_annotator"][0]
    assert row["n_voted"] == 2 and row["n_kappa"] == 1


def test_unknown_keys_are_reported_not_crashed():
    res = anchor_result(RECORDS, [_vs("h1", {"deadbeefdeadbeef": "A"})])
    assert res["unknown_keys"] == 1


def test_two_annotators_get_inter_annotator_kappa():
    res = anchor_result(RECORDS, [
        _vs("h1", {k: "A" for k in KEYS}), _vs("h2", {k: "A" for k in KEYS}),
    ])
    assert len(res["inter_annotator"]) == 1
    assert res["inter_annotator"][0]["kappa"] == 1.0


def test_load_votes_roundtrip(tmp_path):
    p = tmp_path / "votes.json"
    p.write_text(json.dumps({
        "schema": 1, "seed": 42, "source": "x", "annotator": "h1",
        "votes": {KEYS[0]: "A", KEYS[1]: "tie"},
    }))
    (vs,) = load_votes([p])
    assert vs.annotator == "h1" and vs.votes[KEYS[1]] == "tie"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_anchor_math.py -q`
Expected: FAIL with `ImportError: cannot import name 'VoteSet'`

- [ ] **Step 3: Write the implementation**

Append to `src/orq_arena/anchor.py` (imports: add `from dataclasses import dataclass`, `from pathlib import Path`, `from .analysis.kappa import cohen_kappa_pairs`, `from .rejudge import outcomes_from_majorities, spearman`, `from .tournament.elo import bradley_terry_mle, build_wins_matrix`):

```python
_DECISIVE = ("A", "B", "tie")
_PANEL = "panel"


@dataclass(frozen=True)
class VoteSet:
    annotator: str
    seed: int
    source: str
    votes: dict[str, str]  # record_key -> 'A' | 'B' | 'tie'


def load_votes(paths: list[str | Path]) -> list[VoteSet]:
    sets: list[VoteSet] = []
    for p in paths:
        data = json.loads(Path(p).read_text())
        votes = {
            k: v for k, v in (data.get("votes") or {}).items() if v in _DECISIVE
        }
        sets.append(VoteSet(
            annotator=str(data.get("annotator") or Path(p).stem),
            seed=int(data.get("seed") or 0),
            source=str(data.get("source") or ""),
            votes=votes,
        ))
    return sets


def _ranking(records, majorities, models) -> list[str]:
    pairs = [(r.model_a, r.model_b) for r in records]
    outcomes = outcomes_from_majorities(pairs, majorities)
    if not outcomes:
        return sorted(models)
    elo = bradley_terry_mle(build_wins_matrix(outcomes), models)
    return sorted(models, key=lambda m: elo[m], reverse=True)


def anchor_result(records, votesets: list[VoteSet]) -> dict:
    """Human-vs-panel kappa + rank correlation; humans are just more judges."""
    keyed = {record_key(r): r for r in records}
    models = sorted({m for r in records for m in (r.model_a, r.model_b)})
    panel_rank = _ranking(records, [r.majority_verdict for r in records], models)

    unknown = 0
    per_annotator = []
    for vs in votesets:
        co = {k: v for k, v in vs.votes.items() if k in keyed}
        unknown += len(vs.votes) - len(co)
        # kappa vs panel over rounds where the panel was decisive
        rounds = [
            [{"model": _PANEL, "vote": keyed[k].majority_verdict},
             {"model": vs.annotator, "vote": v}]
            for k, v in co.items() if keyed[k].majority_verdict in _DECISIVE
        ]
        pair = next(iter(cohen_kappa_pairs(rounds, [_PANEL, vs.annotator]).values()),
                    {"kappa": None, "label": "n/a", "rounds": 0})
        recs = [keyed[k] for k in co]
        human_rank = _ranking(recs, list(co.values()), models)
        per_annotator.append({
            "annotator": vs.annotator,
            "n_voted": len(co),
            "n_kappa": pair["rounds"],
            "kappa": pair["kappa"],
            "kappa_label": pair["label"],
            "spearman": spearman(panel_rank, human_rank),
        })

    inter = []
    for i, va in enumerate(votesets):
        for vb in votesets[i + 1:]:
            shared = [k for k in va.votes if k in vb.votes and k in keyed]
            rounds = [
                [{"model": va.annotator, "vote": va.votes[k]},
                 {"model": vb.annotator, "vote": vb.votes[k]}]
                for k in shared
            ]
            pair = next(iter(
                cohen_kappa_pairs(rounds, [va.annotator, vb.annotator]).values()
            ), {"kappa": None, "label": "n/a", "rounds": 0})
            inter.append({
                "pair": f"{va.annotator} × {vb.annotator}",
                "kappa": pair["kappa"], "kappa_label": pair["label"],
                "rounds": pair["rounds"],
            })

    return {
        "per_annotator": per_annotator,
        "inter_annotator": inter,
        "panel_ranking": panel_rank,
        "unknown_keys": unknown,
    }
```

Edge case locked by test: annotator name must never equal `"panel"`; guard in `load_votes` by suffixing (`f"{name}*"`) if it does. Add that guard and this test:

```python
def test_annotator_named_panel_does_not_collide():
    res = anchor_result(RECORDS, [_vs("panel", {k: "A" for k in KEYS})])
    assert res["per_annotator"][0]["kappa"] == 1.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_anchor_math.py -q`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/orq_arena/anchor.py tests/test_anchor_math.py
git commit -m "feat: anchor math, human-vs-panel kappa and rank correlation"
```

### Task 4: CLI commands `annotate` and `anchor`

**Files:**
- Modify: `src/orq_arena/cli.py` (append two commands after `rejudge`)
- Test: `tests/test_anchor_cli.py`

**Interfaces:**
- Consumes: everything from Tasks 1-3, `load_records` from `rejudge.py`.
- Produces: `orq-arena annotate <battles.jsonl> [--out annotate.html] [--sample N] [--seed 42]`; `orq-arena anchor <battles.jsonl> <votes.json ...>`.

- [ ] **Step 1: Write the failing test**

```python
"""CLI wiring for annotate + anchor."""

import json

from click.testing import CliRunner

from orq_arena.anchor import record_key
from orq_arena.cli import cli
from tests.test_anchor_items import RECORDS


def _log(tmp_path):
    p = tmp_path / "battles.jsonl"
    p.write_text("\n".join(r.model_dump_json() for r in RECORDS) + "\n")
    return p


def test_annotate_writes_blind_page(tmp_path):
    log = _log(tmp_path)
    out = tmp_path / "annotate.html"
    r = CliRunner().invoke(cli, ["annotate", str(log), "--out", str(out), "--sample", "3"])
    assert r.exit_code == 0, r.output
    page = out.read_text()
    assert "model-one" not in page and page.count("class=\"resp") == 2
    assert "3 rounds" in r.output


def test_anchor_prints_kappa_table(tmp_path):
    log = _log(tmp_path)
    votes = tmp_path / "votes.json"
    votes.write_text(json.dumps({
        "schema": 1, "seed": 42, "source": "battles.jsonl", "annotator": "h1",
        "votes": {record_key(r): "A" for r in RECORDS},
    }))
    r = CliRunner().invoke(cli, ["anchor", str(log), str(votes)])
    assert r.exit_code == 0, r.output
    assert "h1" in r.output and "κ" in r.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_anchor_cli.py -q`
Expected: FAIL, `Error: No such command 'annotate'` (exit code 2 assertion failure)

- [ ] **Step 3: Write the implementation**

Append to `src/orq_arena/cli.py`, matching the existing command style (lazy imports inside the function, `click.echo` output; see `rejudge` at `src/orq_arena/cli.py:170` for the pattern):

```python
@cli.command()
@click.argument("battle_log", type=click.Path(exists=True))
@click.option("--out", "out_path", default="annotate.html", show_default=True)
@click.option("--sample", type=int, default=None,
              help="Annotate a seeded random subset instead of every round.")
@click.option("--seed", type=int, default=42, show_default=True)
def annotate(battle_log: str, out_path: str, sample: int | None, seed: int) -> None:
    """Render a blinded human-annotation page from a recorded run.

    The page is one self-contained HTML file: open it locally or send it
    to a rater; no model names, no jury votes, seeded side order. Votes
    come back as votes.json for `orq-arena anchor`.
    """
    from .anchor import annotation_items, render_annotate_page
    from .rejudge import load_records

    records = load_records(battle_log)
    if not records:
        raise click.ClickException(f"no judgeable rounds in {battle_log}")
    items = annotation_items(records, seed=seed, sample=sample)
    Path(out_path).write_text(
        render_annotate_page(items, seed=seed, source=Path(battle_log).name)
    )
    click.echo(f"{len(items)} rounds → {out_path} (blind; votes export as votes.json)")


@cli.command()
@click.argument("battle_log", type=click.Path(exists=True))
@click.argument("vote_files", nargs=-1, required=True, type=click.Path(exists=True))
def anchor(battle_log: str, vote_files: tuple[str, ...]) -> None:
    """Merge human vote files against a recorded run: κ + rank correlation.

    Prints per-annotator Cohen's κ vs the panel majority, Spearman rank
    correlation between the human and panel Bradley-Terry rankings, and
    inter-annotator κ when more than one vote file is given.
    """
    from rich.console import Console
    from rich.table import Table

    from .anchor import anchor_result, load_votes
    from .rejudge import load_records

    result = anchor_result(load_records(battle_log), load_votes(list(vote_files)))
    t = Table(title="human anchor vs panel")
    for col in ("annotator", "voted", "κ rounds", "κ vs panel", "label", "rank ρ"):
        t.add_column(col)
    for row in result["per_annotator"]:
        t.add_row(
            row["annotator"], str(row["n_voted"]), str(row["n_kappa"]),
            "n/a" if row["kappa"] is None else f"{row['kappa']:.2f}",
            row["kappa_label"],
            "n/a" if row["spearman"] != row["spearman"] else f"{row['spearman']:.2f}",
        )
    Console().print(t)
    for pair in result["inter_annotator"]:
        click.echo(
            f"inter-annotator {pair['pair']}: "
            + ("κ=n/a" if pair["kappa"] is None else f"κ={pair['kappa']:.2f}")
            + f" ({pair['kappa_label']}, {pair['rounds']} rounds)"
        )
    if result["unknown_keys"]:
        click.echo(f"⚠ {result['unknown_keys']} votes matched no round in this log")
```

`Path` is already imported at module top of `cli.py`; verify, otherwise import locally.

- [ ] **Step 4: Run tests, full suite**

Run: `uv run pytest -q`
Expected: all pass (existing 57 + new)

- [ ] **Step 5: Commit**

```bash
git add src/orq_arena/cli.py tests/test_anchor_cli.py
git commit -m "feat: annotate + anchor CLI, blinded page in and kappa out"
```

### Task 5: Docs and plan bookkeeping

**Files:**
- Modify: `docs/cli.md` (new sections for `annotate` and `anchor`, same structure as the `rejudge` section: synopsis, flags table, output format, examples)
- Modify: `docs/methodology.md` ("Current limitations": rewrite the "No human-anchor study yet" bullet to point at the annotate/anchor workflow; add a short "Human anchor" subsection after "Jury swapping" describing the blinding contract and what κ/ρ mean)
- Modify: `README.md` ("What you get" list: one bullet, e.g. "A human-anchor check: blind-annotate any recorded run in a browser, get panel-vs-human κ and rank correlation with one command")
- Modify: `REFACTOR_PLAN.md` (mark G5 progress; PR 11.4 references G5 instead of restating)

- [ ] **Step 1: Write the docs** (content per file as listed above; follow each file's existing voice; no em-dashes)
- [ ] **Step 2: Run the docs check that exists in CI** (`uv run pytest -q` covers doc-adjacent tests; also grep docs for banned em-dash: `grep -n "—" docs/cli.md docs/methodology.md README.md` must return nothing new)
- [ ] **Step 3: Commit**

```bash
git add docs/cli.md docs/methodology.md README.md REFACTOR_PLAN.md
git commit -m "docs: human-anchor annotate/anchor workflow"
```

---

## Self-review notes

- Spec coverage: blinding (Tasks 1-2 + tests), static no-server page (Task 2), canonical vote export (Task 2), κ vs panel + Spearman + multi-annotator (Task 3), CLI (Task 4), docs + limitation rewrite (Task 5). Gap accepted on purpose: no per-category anchor slices (category display is under separate discussion), no localStorage-restore test (best-effort cache only, manual smoke covers it).
- Types consistent: `record_key` 16-hex str used in page payload (`k`), votes.json keys, and `anchor_result` lookups; `VoteSet.votes: dict[str, str]` everywhere; `cohen_kappa_pairs` field names (`kappa`, `label`, `rounds`) match `analysis/kappa.py:96-104`.
- Sample-size guidance for the real study lives in methodology docs (50-100 rounds, 2-3 raters), matching PR 11.4.
