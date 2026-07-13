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
import re
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Collection

from .analysis.kappa import cohen_kappa_pairs
from .data.schemas import BattleRecord
from .rejudge import outcomes_from_majorities, spearman
from .tournament.elo import bradley_terry_mle, build_wins_matrix


def record_key(rec: BattleRecord) -> str:
    """One-way 16-hex key; recomputable from the log, opaque in the page."""
    raw = f"{rec.prompt_hash}:{rec.model_a}:{rec.model_b}:{rec.match_id}:{rec.round_number}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def annotation_items(
    records: list[BattleRecord], *, seed: int = 42, sample: int | None = None,
    exclude: Collection[str] = (),
) -> list[dict]:
    """Blinded page payload: canonical responses + per-round display flip.

    ``exclude`` drops rounds by record key (Prodigy's --exclude move): pass
    a rater's existing votes.json keys to build a resume page with only
    their unvoted rounds.
    """
    items = []
    excluded = set(exclude)
    for rec in records:
        key = record_key(rec)
        if key in excluded:
            continue
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
.gate{max-width:640px;margin:48px auto;background:var(--card);border:1px solid var(--line);
  border-radius:12px;padding:28px 34px}
.gate h2{margin-top:0;color:var(--teal)}
.gate ul{padding-left:20px} .gate li{margin-bottom:6px}
.gate .stats{font-family:var(--mono);font-size:13px;color:var(--muted);margin:14px 0}
.gate input{font:inherit;padding:8px 10px;border:1px solid var(--line);border-radius:8px;
  width:100%;margin:6px 0 16px}
.gate button{font:inherit;padding:10px 22px;border:none;border-radius:8px;
  background:var(--teal);color:#fff;cursor:pointer}
.gate button:disabled{opacity:.4;cursor:default}
.gate .big{font-size:17px}
.hidden{display:none}
.nav{display:flex;flex-wrap:wrap;gap:4px;padding:10px 0 2px}
.dot{width:13px;height:13px;border-radius:4px;cursor:pointer;
  background:#e6e1d6;border:1px solid #d5cfc0}
.dot.seen{background:#b3ac9c;border-color:#b3ac9c}
.dot.voted{background:var(--teal);border-color:var(--teal)}
.dot.tie{background:#c99a2e;border-color:#c99a2e}
.dot.cur{outline:2px solid var(--a);outline-offset:1px}
.legend{font-family:var(--mono);font-size:10.5px;color:var(--muted);padding-bottom:6px}
"""

_PAGE_JS = r"""
const D = JSON.parse(document.getElementById('data').textContent);
let idx = 0; const votes = {}; const seen = new Set();
const cacheKey = 'orq-anchor:' + D.source + ':' + D.seed;
try {
  const c = JSON.parse(localStorage.getItem(cacheKey) || '{}');
  Object.assign(votes, c.v || {});
  for (const k of c.s || []) seen.add(k);
} catch (e) {}
let downloaded = false;
// Served over http (orq-arena annotate --serve): votes also POST to /save
// after every decision, so closing the tab loses nothing.
const SERVED = location.protocol.indexOf('http') === 0;
let savedToServer = false;
function cache(){
  try{localStorage.setItem(cacheKey,JSON.stringify({v:votes,s:[...seen]}));}catch(e){}
}
function persist(){
  if(!SERVED)return;
  const name=document.getElementById('annotator').value||'anonymous';
  fetch('/save',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({schema:1,seed:D.seed,source:D.source,annotator:name,votes:votes})})
    .then(r=>{savedToServer=r.ok;}).catch(()=>{savedToServer=false;});
}

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
let view='intro';
function show(name){
  view=name;
  for(const v of ['intro','annotate','done'])
    document.getElementById('view-'+v).classList.toggle('hidden',v!==name);
  document.getElementById('bar').classList.toggle('hidden',name!=='annotate');
  document.getElementById('nav').classList.toggle('hidden',name==='intro');
  document.getElementById('legend').classList.toggle('hidden',name==='intro');
  if(name==='annotate')render();
  if(name==='done')renderDone();
}
function counts(){
  const voted=Object.keys(votes).length;
  const skipped=[...seen].filter(k=>!(k in votes)).length;
  return {voted, skipped, left:D.items.length-voted-skipped};
}
function progText(prefix){
  const c=counts();
  return prefix+'  ·  voted '+c.voted+' · skipped '+c.skipped+' · left '+c.left;
}
function buildNav(){
  const nav=document.getElementById('nav');
  D.items.forEach((it,i)=>{
    const d=document.createElement('span');
    d.className='dot'; d.title='round '+(i+1);
    d.onclick=()=>{idx=i;show('annotate');};
    nav.appendChild(d);
  });
}
function updateNav(){
  const dots=document.getElementById('nav').children;
  D.items.forEach((it,i)=>{
    const v=votes[it.k];
    dots[i].className='dot'
      +(v==='tie'?' tie':v?' voted':seen.has(it.k)?' seen':'')
      +(view==='annotate'&&i===idx?' cur':'');
  });
}
function render(){
  const it=D.items[idx];
  seen.add(it.k); cache();
  const l=it.f?it.b:it.a, r=it.f?it.a:it.b;
  document.getElementById('prog').textContent=progText((idx+1)+' / '+D.items.length);
  document.getElementById('prompt').innerHTML=md(it.q);
  document.getElementById('left').innerHTML='<h3>Response 1</h3>'+md(l);
  document.getElementById('right').innerHTML='<h3>Response 2</h3>'+md(r);
  const v=votes[it.k];
  document.getElementById('lpane').classList.toggle('voted',v===canon('left',it));
  document.getElementById('rpane').classList.toggle('voted',v===canon('right',it));
  updateNav();
}
function renderDone(){
  const c=counts(), total=D.items.length;
  document.getElementById('prog').textContent=progText('done');
  document.getElementById('done-stats').textContent=
    c.voted+' of '+total+' rounds voted'+(c.voted<total?' ('+(total-c.voted)+' skipped or unseen; click any dot above to finish them)':'');
  document.getElementById('done-hint').textContent=SERVED
    ? (savedToServer||Object.keys(votes).length===0
       ? 'Votes are saved on this machine automatically; you can close this tab.'
       : 'Saving to the local server failed; use the download button instead.')
    : downloaded
    ? 'votes.json downloaded. Send it back to whoever sent you this file.'
    : 'One step left: download your votes and send the file back.';
  updateNav();
}
function nextUnvoted(){
  const total=D.items.length;
  for(let s=1;s<=total;s++){
    const i=(idx+s)%total;
    if(!(D.items[i].k in votes)){idx=i;show('annotate');return;}
  }
  show('done');
}
function start(){
  const name=document.getElementById('annotator-in').value.trim();
  document.getElementById('annotator').value=name;
  show('annotate');
}
function vote(side){const it=D.items[idx];
  if(side==='skip'){delete votes[it.k];}else{votes[it.k]=canon(side,it);}
  cache(); persist();
  if(idx<D.items.length-1){idx++;render();}
  else{show('done');}
}
function download(){
  const name=document.getElementById('annotator').value||'anonymous';
  const payload={schema:1,seed:D.seed,source:D.source,annotator:name,votes:votes};
  const a=document.createElement('a');
  a.href=URL.createObjectURL(new Blob([JSON.stringify(payload,null,1)],{type:'application/json'}));
  a.download='votes.json'; a.click(); downloaded=true;
  if(view==='done')renderDone();
}
document.addEventListener('keydown',e=>{
  if(e.target.tagName==='INPUT'){
    if(e.key==='Enter'&&view==='intro')start();
    return;
  }
  if(view==='intro'){ if(e.key==='Enter')start(); return; }
  if(view==='done'){
    if(e.key==='ArrowLeft'){idx=D.items.length-1;show('annotate');}
    else if(e.key==='n')nextUnvoted();
    return;
  }
  if(e.key==='a')vote('left'); else if(e.key==='b')vote('right');
  else if(e.key==='t')vote('tie'); else if(e.key===' '){e.preventDefault();vote('skip');}
  else if(e.key==='n')nextUnvoted();
  else if(e.key==='ArrowRight'){ if(idx<D.items.length-1){idx++;render();} else show('done'); }
  else if(e.key==='ArrowLeft'&&idx>0){idx--;render();}
});
window.addEventListener('beforeunload',e=>{
  if(Object.keys(votes).length&&!downloaded&&!(SERVED&&savedToServer))e.preventDefault();});
document.getElementById('n-items').textContent=D.items.length;
document.getElementById('n-mins').textContent=Math.max(1,Math.round(D.items.length*45/60));
document.getElementById('criteria').textContent=D.criteria;
buildNav();
show('intro');
"""


DEFAULT_CRITERIA = (
    "Accuracy and correctness, helpfulness and completeness, "
    "clarity, and relevance to the prompt."
)


def render_annotate_page(
    items: list[dict], *, seed: int, source: str, criteria: str = DEFAULT_CRITERIA
) -> str:
    """One self-contained blinded page; votes leave only via download.

    Three views: intro (what this is, round count, expected time, guidelines,
    rater name), the annotation duel, and a done screen with an explicit
    download step; no surprise auto-download.
    """
    payload = json.dumps(
        {"seed": seed, "source": source, "criteria": criteria, "items": items}
    )
    payload = payload.replace("</", "<\\/")  # keep the closing script tag inert
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>orq-arena blind annotation</title>
<style>{_PAGE_CSS}</style></head><body>
<div class="wrap">
<header><b>blind annotation</b>
<input id="annotator" type="hidden">
<span class="prog" id="prog"></span></header>
<div class="nav hidden" id="nav"></div>
<div class="legend hidden" id="legend">■ voted · <span style="color:#c99a2e">■</span> tie ·
<span style="color:#b3ac9c">■</span> skipped · □ unseen · click any dot to jump ·
<b>n</b> = next unvoted</div>

<div id="view-intro" class="gate">
<h2>Compare two AI answers, pick the better one</h2>
<p>You will see one prompt and two anonymous responses at a time. You don't know which
model wrote which, and the sides are shuffled every round on purpose.</p>
<p class="stats"><span id="n-items"></span> rounds · roughly <span id="n-mins"></span> min ·
keys: <b>a</b> left better, <b>b</b> right better, <b>t</b> tie, <b>space</b> skip,
<b>n</b> next unvoted, arrows to move around</p>
<p>A dot strip above the rounds shows where you are and what each round's state is
(voted, tie, skipped, unseen); click any dot to jump to that round.</p>
<h3>Guidelines</h3>
<ul>
<li>Read both responses fully before voting; don't reward the first or the longer one.</li>
<li>Weigh: <span id="criteria"></span></li>
<li>Prefer <b>tie</b> when both are genuinely comparable; prefer <b>skip</b> when the
topic is out of your depth. Neither hurts the study; forced guesses do.</li>
<li>When you finish, a final screen lets you download <code>votes.json</code>;
send that file back to whoever sent you this page.</li>
</ul>
<label>Your name (attached to your votes)</label>
<input id="annotator-in" placeholder="e.g. dana">
<button class="big" onclick="start()">Start annotating ⏎</button>
</div>

<div id="view-annotate" class="hidden">
<div class="prompt" id="prompt"></div>
<div class="duel">
<div class="resp left" id="lpane"><div id="left"></div></div>
<div class="resp right" id="rpane"><div id="right"></div></div>
</div>
</div>

<div id="view-done" class="gate hidden">
<h2>All rounds seen ✓</h2>
<p class="stats" id="done-stats"></p>
<p id="done-hint"></p>
<button class="big" onclick="download()">Download votes.json</button>
<p class="stats">Missed something? Left arrow goes back to the rounds; skipped rounds
can still be voted.</p>
</div>

<div class="bar hidden" id="bar">
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
        data = json.loads(Path(p).read_text(encoding="utf-8"))
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
            # no co-voted rounds -> no ranking claim, not an alphabetical one
            "spearman": spearman(panel_rank, human_rank) if co else float("nan"),
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


_VOTE_KEYS = ("schema", "seed", "source", "annotator", "votes")


def make_annotation_server(
    page: str, votes_dir: Path, *, host: str = "127.0.0.1", port: int = 8765
) -> ThreadingHTTPServer:
    """Localhost-only serve mode (decision 30): the same blinded page, but
    every vote POSTs to /save and lands as votes-<annotator>.json next to
    the log. No auth surface: binds 127.0.0.1, two fixed routes, capped
    body, sanitized filename, whitelisted payload keys.
    """
    written: set[Path] = set()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args) -> None:
            pass  # keep the terminal quiet; votes are the signal

        def do_GET(self) -> None:
            if self.path in ("", "/"):
                body = page.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_error(404)

        def do_POST(self) -> None:
            if self.path != "/save":
                self.send_error(404)
                return
            size = int(self.headers.get("Content-Length") or 0)
            if not 0 < size <= 5_000_000:
                self.send_error(413)
                return
            try:
                data = json.loads(self.rfile.read(size))
                votes = {
                    str(k): v for k, v in (data.get("votes") or {}).items()
                    if v in _DECISIVE
                }
                slug = re.sub(
                    r"[^a-z0-9-]+", "-", str(data.get("annotator") or "").lower()
                ).strip("-") or "anonymous"
            except (ValueError, AttributeError):
                self.send_error(400)
                return
            payload = {k: data.get(k) for k in _VOTE_KEYS}
            payload["votes"] = votes
            path = votes_dir / f"votes-{slug}.json"
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
            tmp.replace(path)
            written.add(path)
            self.send_response(204)
            self.end_headers()

    server = ThreadingHTTPServer((host, port), Handler)
    server.votes_written = written  # type: ignore[attr-defined]
    return server


def render_anchor_result(result: dict) -> None:
    """Rich table for `anchor` and for --serve's exit summary."""
    from rich.console import Console
    from rich.table import Table

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
    console = Console()
    console.print(t)
    for pair in result["inter_annotator"]:
        console.print(
            f"inter-annotator {pair['pair']}: "
            + ("κ=n/a" if pair["kappa"] is None else f"κ={pair['kappa']:.2f}")
            + f" ({pair['kappa_label']}, {pair['rounds']} rounds)"
        )
    if result["unknown_keys"]:
        console.print(f"⚠ {result['unknown_keys']} votes matched no round in this log")
