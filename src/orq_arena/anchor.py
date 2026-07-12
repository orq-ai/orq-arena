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
import json
import random
from dataclasses import dataclass
from pathlib import Path

from .analysis.kappa import cohen_kappa_pairs
from .data.schemas import BattleRecord
from .rejudge import outcomes_from_majorities, spearman
from .tournament.elo import bradley_terry_mle, build_wins_matrix


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
  display:flex;gap:10px;justify-content:center;padding:12px;flex-wrap:wrap}
.bar button{font:inherit;padding:8px 18px;border:1px solid var(--line);border-radius:8px;
  background:var(--paper);cursor:pointer}
.bar button:hover{border-color:var(--teal)}
.bar .key{font-family:var(--mono);font-size:11px;color:var(--muted)}
"""

_PAGE_JS = r"""
const D = JSON.parse(document.getElementById('data').textContent);
let idx = 0; const votes = {};
const cacheKey = 'orq-anchor:' + D.source + ':' + D.seed;
try { Object.assign(votes, JSON.parse(localStorage.getItem(cacheKey) || '{}')); } catch (e) {}
let downloaded = false;

function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function md(text){
  const out=[]; const lines=esc(text).split('\n'); let i=0;
  function inline(s){return s
    .replace(/`([^`]+)`/g,'<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g,'<b>$1</b>')
    .replace(/\*([^*]+)\*/g,'<i>$1</i>');}
  while(i<lines.length){
    const l=lines[i];
    if(l.startsWith('```')){const buf=[];i++;
      while(i<lines.length&&!lines[i].startsWith('```')){buf.push(lines[i]);i++;}
      i++; out.push('<pre><code>'+buf.join('\n')+'</code></pre>'); continue;}
    const h=l.match(/^(#{1,4}) (.*)/);
    if(h){const n=h[1].length+2;out.push('<h'+n+'>'+inline(h[2])+'</h'+n+'>');i++;continue;}
    if(/^[-*] /.test(l)){const buf=[];
      while(i<lines.length&&/^[-*] /.test(lines[i])){buf.push('<li>'+inline(lines[i].slice(2))+'</li>');i++;}
      out.push('<ul>'+buf.join('')+'</ul>');continue;}
    if(/^\d+\. /.test(l)){const buf=[];
      while(i<lines.length&&/^\d+\. /.test(lines[i])){buf.push('<li>'+inline(lines[i].replace(/^\d+\. /,''))+'</li>');i++;}
      out.push('<ol>'+buf.join('')+'</ol>');continue;}
    if(l.trim()===''){i++;continue;}
    const buf=[]; while(i<lines.length&&lines[i].trim()!==''){buf.push(inline(lines[i]));i++;}
    out.push('<p>'+buf.join('<br>')+'</p>');
  }
  return out.join('');
}
// left/right -> canonical A/B under this round's flip; 'tie' passes through.
function canon(side, it){
  if(side==='tie')return 'tie';
  return (side==='left')===(!it.f)?'A':'B';
}
function render(){
  const it=D.items[idx];
  const l=it.f?it.b:it.a, r=it.f?it.a:it.b;
  document.getElementById('prog').textContent=(idx+1)+' / '+D.items.length+
    '  ·  voted '+Object.keys(votes).length;
  document.getElementById('prompt').innerHTML=md(it.q);
  document.getElementById('left').innerHTML='<h3>Response 1</h3>'+md(l);
  document.getElementById('right').innerHTML='<h3>Response 2</h3>'+md(r);
  const v=votes[it.k];
  document.getElementById('lpane').classList.toggle('voted',v===canon('left',it));
  document.getElementById('rpane').classList.toggle('voted',v===canon('right',it));
}
function vote(side){const it=D.items[idx];
  if(side==='skip'){delete votes[it.k];}else{votes[it.k]=canon(side,it);}
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
    payload = payload.replace("</", "<\\/")  # keep the closing script tag inert
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


def _pair_kappa(rounds: list, a: str, b: str) -> dict:
    return next(iter(cohen_kappa_pairs(rounds, [a, b]).values()),
                {"kappa": None, "label": "n/a", "rounds": 0})


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
        # a rater literally named "panel" must not merge into the panel's votes
        label = vs.annotator if vs.annotator != _PANEL else vs.annotator + "*"
        # kappa vs panel over rounds where the panel was decisive
        rounds = [
            [{"model": _PANEL, "vote": keyed[k].majority_verdict},
             {"model": label, "vote": v}]
            for k, v in co.items() if keyed[k].majority_verdict in _DECISIVE
        ]
        pair = _pair_kappa(rounds, _PANEL, label)
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
                 {"model": vb.annotator + " (2)" if vb.annotator == va.annotator
                  else vb.annotator, "vote": vb.votes[k]}]
                for k in shared
            ]
            b_label = va.annotator + " (2)" if vb.annotator == va.annotator else vb.annotator
            pair = _pair_kappa(rounds, va.annotator, b_label)
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
