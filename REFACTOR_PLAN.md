# orc-arena → evaluatorq refactor plan

> **Status (2026-07-12): EXECUTED through PR 8** — harvest PRs on `feat/chennai-harvest`:
> `09b7d47` (PR 5 ergonomics), `b29afd8` (PR 6 roster picker), `c234e5f` (PR 7 browser+κ+
> post-mortems), `f4eaa25` (PR 8 theme+CTA+Swiss). 41 tests. **evaluatorq now the official
> PyPI release (>=1.8.0)** — the git-SHA pin + path override are gone; the '1.3.0 unreleased'
> premise came from a stale CHANGELOG header in the sibling checkout. Prior status:
> **(2026-07-11): EXECUTED through PR 4** — commits `62ffbaa` (PR 1), `61f40a5` (PR 2),
> `775f46b` (PR 3), `9e96390`+`fd8288b` (PR 4). PR 5 (per-category ELO, cost preflight, panel
> presets, `--headless`) remains open. Execution report:
> `outputs/html/orc-arena-refactor-report.html`
> (https://claude.ai/code/artifact/f02388ad-5f11-4f0a-b152-0dd414f18996). Notable deviations from
> plan, discovered live: roster re-audited against the router (gemini-3-pro-preview broken
> upstream; kimi-k2.6 / deepseek-v4-pro / qwen3.5-flash cannot disable thinking → excluded from
> the uniform-OFF pool); streamed CoT arrives as `delta.reasoning`; Anthropic path reports
> `reasoning_tokens=0` (filed to docs team); final src LOC is 2,426, not ~1,600 — all planned
> deletions landed, and ~870 lines of owner-approved new capability (rejudge, CIs+manifest,
> reasoning support, TUI upgrades) were added on top.

**Goal.** Refocus this repo on the arena only: a benchmark that produces a Bradley-Terry ELO
ranking over a configurable pool of models, rendered by the existing Textual TUI. All judging
moves to `evaluatorq` (pairwise jury), all model traffic stays on the orq.ai router gateway.
Tournament modes (single-elimination bracket) are removed. End state: ~1,600 src LOC where every
line renders the show, routes the tokens, or demonstrates the eval.

**Companion analysis:** `outputs/html/orc-arena-architecture-report.html` (Findings 01–05, target
architecture §09, artifact: https://claude.ai/code/artifact/cb006f76-6fec-4586-a550-a18bfc91617a).

**Non-goals.** No Unity/web renderer seams, no parallel-match execution (the TUI shows one fight
at a time), no generic n-format tournament engine, no byte-compat with orq-battlebench records
(schema v2 below supersedes it).

---

## Vocabulary decision (applies to every PR)

Adopt evaluatorq's verdict vocabulary end-to-end and delete the arena's two hand-spelled Literals
(report Finding 04):

| concept | today | after |
|---|---|---|
| per-judge vote | `"A" \| "B" \| "TIE"` (`JudgeVerdict`) | `PairwiseVote.vote`: `'A' \| 'B' \| 'tie' \| None` (None = abstained/flipped) |
| panel outcome | `"A" \| "B" \| "TIE" \| "DISCARD"` (`majority_vote`) | `PairwiseComparison.winner`: `'A' \| 'B' \| 'tie' \| 'inconclusive'` |
| record winner | short model / `"tie"` / `"discard"` | short model / `"tie"` / `"inconclusive"` |

`damage.py`, `events.py`, `data/schemas.py`, and the TUI widgets all switch to the new strings.
The `demo` fixture is regenerated in PR 3 (it embeds the old vocabulary).

---

## PR 1 — Swap the bench: `judges/` → `llm_jury_pairwise` (~−180 LOC)

### 1.1 Dependencies (`pyproject.toml`)

- Remove `instructor>=1.7` (evaluatorq does its own structured output).
- Add `evaluatorq` pinned to a main SHA — RES-760 (pairwise) is **already merged to
  evaluatorq main** (verified 2026-07-11, `pairwise.py` present on `origin/main` @ `8e56a56`);
  1.3.0 is still unreleased on PyPI:

```toml
[project]
dependencies = [
  # ...
  "evaluatorq @ git+https://github.com/orq-ai/evaluatorq.git@<main-sha>",
]

# local development against the sibling checkout:
[tool.uv.sources]
evaluatorq = { path = "../evaluatorq", editable = true }
```

Switch the local `../evaluatorq` checkout from the stale feature branch to `main` first. Re-pin
to the PyPI release when 1.3.0 ships. Note 1.3.0 makes `openai` and `loguru` core deps of
evaluatorq; `openai` is already here, `loguru` is new transitive baggage we accept.

### 1.2 Config (`config.py`, `orc_arena.yaml`)

`JudgeSpec` and `judge_system_prompt` die. New shape:

```yaml
judges:
  - anthropic/claude-haiku-4-5
  - google/gemini-2.5-flash
  - openai/gpt-4o-mini
replacement_judges:
  - mistral/mistral-small        # neutral stand-in; cures judge-erosion (Finding 05)
criteria: >-
  Accuracy and correctness, helpfulness and completeness, clarity, and
  relevance to the prompt.
```

```python
class ArenaConfig(BaseModel):
    match: MatchRules = Field(default_factory=MatchRules)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    warriors: list[WarriorSpec]
    judges: list[str]
    replacement_judges: list[str] = []
    criteria: str = "Accuracy, helpfulness, clarity, relevance to the prompt."
    min_successful_judges: int = 2   # jury-of-one -> 'inconclusive', never a verdict
```

Judge display names: derive from the model id tail (`model_id.split("/")[-1]`) at the event/TUI
boundary. No name map unless someone asks for one.

`GatewayConfig.judge_max_tokens` survives and feeds `llm_jury_pairwise(max_tokens=...)`.

### 1.3 Battle wiring (`arena/battle.py`)

Replace the `run_panel` / `filter_self_judges` / `majority_vote` block (battle.py:163–188) with a
comparator built once per match and called once per round:

```python
from evaluatorq import llm_jury_pairwise

# in Battle.__init__ (panel is fixed for the whole match):
panel = [m for m in cfg.judges if m not in {warrior_a.model_id, warrior_b.model_id}]
self.jury = llm_jury_pairwise(
    judges=panel,
    criteria=cfg.criteria,
    replacement_judges=cfg.replacement_judges,
    min_successful_judges=cfg.min_successful_judges,
    max_tokens=cfg.gateway.judge_max_tokens,
    client=gateway.client,          # judges ride the same orq router client
)

# per round:
comparison = await self.jury.compare(
    question=prompt, response_a=resp_a, response_b=resp_b
)
```

The one-line panel filter *is* the self-judge exclusion. With 3 judges and at most 2 contestants
excluded, the primary panel can drop to 1; the configured replacement judge plus
`min_successful_judges=2` keeps a real fight from ever being decided by a jury of one
(closes Finding 05). Keep `replacement_judges` non-empty in the default config — it also keeps
`PairwiseComparator` off its single-judge `propagate_errors` path.

### 1.4 Verdict → damage adapter (`arena/damage.py`, rewritten in place, ~40 LOC)

```python
Side = Literal["a", "b", "none"]

def compute_damage(comparison: PairwiseComparison, rules: MatchRules) -> DamageResult:
    winner = comparison.winner                     # 'A' | 'B' | 'tie' | 'inconclusive'
    if winner in ("tie", "inconclusive"):
        return DamageResult(damage=rules.damage_tie, loser_side="none", counts_toward_cap=False)
    decisive = [v for v in comparison.votes if v.vote in ("A", "B", "tie")]
    unanimous = len(decisive) >= 2 and all(v.vote == winner for v in decisive)
    damage = rules.damage_unanimous if unanimous else rules.damage_majority
    return DamageResult(damage=damage, loser_side="b" if winner == "A" else "a",
                        counts_toward_cap=True)
```

Semantics preserved: tie/inconclusive deal no damage and don't consume a round (today's
TIE/DISCARD behavior). Semantics fixed: "unanimous" now requires at least two decisive votes —
a degraded panel can no longer land the 30-damage hit (Finding 05). Update the YAML comment
(`# 3-0 verdict` → `# all decisive votes agree, minimum 2`).

### 1.5 Events (`events.py`) and TUI

`JudgeVerdictEvent` gains the drama fields, keeps its name:

```python
class JudgeVerdictEvent(BaseModel):
    kind: Literal["judge_verdict"] = "judge_verdict"
    match_id: str
    judge_name: str                  # model id tail
    verdict: str                     # 'A' | 'B' | 'tie' | 'abstain'
    reasoning: str                   # PairwiseVote.explanation
    flipped: bool = False            # judge contradicted itself across orderings
    replacement: bool = False        # stand-in for a failed judge
```

Emit one per `comparison.votes` entry (vote `None` → `"abstain"`). `tui/widgets/judge_card.py`
renders a flip badge when `flipped` (copy suggestion: "flipped under cross-examination — vote
thrown out"). `TurnResolved.majority` becomes `str` with the new vocabulary.

### 1.6 Records (`data/schemas.py`) — schema v2

`judge_verdicts: list[JudgeResult]` → `judge_votes: list[dict]` holding
`PairwiseVote.model_dump()` (model, vote, flipped, completed, replacement, explanation). Add
`schema_version: int = 2`. `majority_verdict` stores `comparison.winner`; `winner` maps
`inconclusive` per the vocabulary table. Judge token usage from `comparison.token_usage` lands in
new `judge_tokens_in` / `judge_tokens_out` fields (warrior token fields are fixed in PR 3).

### 1.7 Deletions and tests

- Delete `src/orc_arena/judges/` entirely (panel.py, schemas.py, prompts.py — 196 LOC).
- Delete `tests/test_panel_tally.py`.
- Add `tests/test_damage_adapter.py`: winner mapping ×4, unanimity requires ≥2 decisive votes,
  jury-of-one → inconclusive → no damage, tie doesn't tick the round cap, panel filter excludes
  both contestants.

### Acceptance

- `uv run pytest` green; `uv pip list | grep instructor` empty.
- Live smoke: 2-warrior mini config (add `fixtures/smoke.yaml`), `ORQ_API_KEY` set,
  `orc-arena run --config fixtures/smoke.yaml` completes a match with visible per-judge verdicts
  and at least one flip/abstain rendering correctly.

---

## PR 2 — Bracket out, round-robin in (~−90 LOC)

### 2.1 Deletions

- `tournament/bracket.py` (95), `tui/screens/bracket.py` (5, dead stub), `tests/test_bracket.py`.
- `BracketUpdated` event and its TUI handler.
- The `len(cfg.warriors) != 8` gate in `driver.py`; new validation: `len(warriors) >= 2`.
- The seed-advantage HP tiebreak in `battle.py` (lines ~250–251): an HP tie at the round cap is
  now a drawn match. `MatchResult.by` gains `"draw"` (winner/loser fields become the two
  participants in config order; the TUI banner shows "DRAW" instead of a champion).
- **KO no longer truncates sampling.** The turn loop runs all `max_rounds` prompts regardless of
  HP; reaching 0 HP is a rendering event (the KO banner fires, remaining rounds still get judged
  and logged). Rationale: with KO-as-termination, rounds-per-pair is outcome-dependent — lopsided
  pairs contribute fewer comparisons and the game mechanics contaminate the sampling design. HP
  keeps clamping at 0 for display; `MatchResult.by` = `"ko"` whenever HP hit 0 at any point.

### 2.2 Scheduler (`tournament/driver.py`, rewritten, ~70 LOC)

```python
schedule = list(itertools.combinations(cfg.warriors, 2))   # C(n,2); 28 at n=8
rng.shuffle(schedule)                                       # match order variety, seeded
```

Per match, unchanged: shuffled prompt slice of `max_rounds`, one `Battle`, append records to the
JSONL log.

### 2.3 ELO feed — per round, not per match

After each match, extend outcomes from its `BattleRecord`s:

```python
for rec in result.battles:
    if rec.majority_verdict == "A":
        outcomes.append((name_a, name_b, "winner"))
    elif rec.majority_verdict == "B":
        outcomes.append((name_b, name_a, "winner"))
    elif rec.majority_verdict == "tie":
        outcomes.append((name_a, name_b, "tie"))     # 0.5/0.5 — finally exercises elo.py's tie path
    # 'inconclusive' rounds carry no rating information; skip
```

`elo.py` is untouched. Up to `C(n,2) × max_rounds` comparisons (~140 at the default 8×5) replace
today's 7 match outcomes — this is what makes BT-MLE defensible (resolves report Finding 02).

Recompute ELO after every match (pure Python, 8 models, effectively free) and emit a new
`StandingsUpdated(elo: dict[str, float], matches_done: int, matches_total: int)` event; the
leaderboard screen updates live instead of only at `TournamentEnded`. `TournamentEnded.champion`
= ELO leader.

### 2.4 Jury stats on the leaderboard

Accumulate every `PairwiseComparison` across the run; at the end call
`evaluatorq.build_report(comparisons)` and render a jury table on the leaderboard screen:
per-judge A/B lean, flip rate (position bias), tie rate, plus mean inter-judge agreement.
~30 LOC of widget, all data free from evaluatorq.

### 2.5 Statistical honesty on the leaderboard (~60 LOC)

- **Bootstrap CIs.** Port the bootstrap confidence intervals `elo.py`'s header says it dropped
  from orq-battlebench's `ranking.py` (resample outcomes with replacement, ~200 iterations,
  report the 2.5/97.5 percentiles). Leaderboard renders `1234 ±45`; models whose CIs overlap the
  next rank render as a shared rank band, not a fake strict order.
- **Verbosity column.** Mean output tokens per model beside its ELO — makes the best-documented
  LLM-judge confound (verbosity bias) visible instead of hidden.
- **Confidence banner.** If `build_report().mean_agreement` falls below a threshold (default
  0.6, config knob), the leaderboard headlines "low-confidence ranking — judges disagree" and the
  run manifest records it. The instrument says so when its own reading is noise.

### 2.6 Run manifest (`run.json`)

Written next to `battles.jsonl` at start, finalized at end: config hash, prompt-set path + hash,
judge panel + replacements, warrior/judge max-tokens and temperatures, evaluatorq version/SHA,
seed, match count, mean agreement, inconclusive rate. Without this, two runs aren't comparable
and "benchmark data" is a marketing claim. ~20 LOC.

### 2.5 Tests

- `tests/test_scheduler.py`: C(n,2) count, no self-pairs, seeded order stable.
- Extend `tests/test_elo.py`: tie outcomes shift ratings symmetrically.

### Acceptance

- `orc-arena run` on the smoke config (2 warriors → 1 match) and on a 4-warrior config
  (6 matches) completes; leaderboard shows live standings and the jury table.
- Cost sanity check on 8×5 default before merging: ~28 matches × ≤5 rounds × 3 judges × 2
  orderings ≈ 840 judge calls (~8× today) — confirm acceptable or trim default `max_rounds`.

---

## PR 3 — Part-1 hygiene (~−55 LOC)

Everything here is from the report's §04/§03 audit, minus items already deleted with their module.

1. **Real token usage.** `OrqGateway.stream_completion` passes
   `stream_options={"include_usage": True}` and fills a caller-supplied `usage_out: dict` from the
   terminal chunk (per-call dict — safe under concurrent A/B streams). `_generate_side` writes
   `tokens_in`/`tokens_out` into `BattleRecord`; delete the `max(1, len(full) // 4)` estimator
   (Finding 03).
2. **Dead code:** `OrqGateway.generate()` + `GenerationResult` (~35 LOC — judges no longer need a
   non-streaming path at all), `TournamentState` (if not already gone in PR 2's driver rewrite),
   `WarriorCard.set_elo()`, `ResponsePanel.set_text()`, `WarriorSpec.starting_elo`,
   `GatewayConfig.concurrency` (knob wired to nothing; parallel matches are a non-goal).
3. **Zero-consumer events:** delete `TournamentStarted` and `ResponseComplete` (emitters and
   classes) or wire them; the report's call is delete.
4. **Replay codec + fixture:** update `tui/app.py`'s decode mapping for the new/changed events,
   then regenerate `fixtures/demo_tournament.json` from one real smoke run (the old fixture
   embeds the retired vocabulary and bracket events). `orc-arena demo` must work offline again.
5. `orcs/roster.py` line-1 docstring ("default roster" that doesn't exist).

### Acceptance

- `orc-arena demo` replays the new fixture with judge flip badges visible, no API key needed.
- `grep -rn "len(full) // 4\|generate(\|TournamentStarted\|ResponseComplete" src/` returns nothing.

---

## PR 4 — `orc-arena rejudge`: the evaluatorq demo inside the demo (~+60 LOC, optional but it's the point)

New CLI command that re-scores a recorded run with a different panel, zero regeneration:

```
orc-arena rejudge battles.jsonl \
  --judge anthropic/claude-haiku-4-5 --judge openai/gpt-4o-mini \
  [--criteria "..."] [--output rejudged.jsonl]
```

Implementation (verified API surface): read the JSONL; for each record build one
`PairwiseComparator` (panel minus that record's two contestants) and
`await jury.compare(question=rec.prompt_text, response_a=rec.response_a,
response_b=rec.response_b)`; collect comparisons; print `build_report()` as a Rich table
(win rates, agreement, per-judge flip/lean) plus the re-fed BT-ELO delta vs the recorded run.

Stretch (verify at impl time, not promised): push results to the Orq platform via
`evaluatorq(inference=False, data=..., evaluators=[llm_jury(...)])` — requires shaping rows as
`DataPoint(inputs={"messages": ...})`; the pairwise two-response shape may not fit the
single-response replay column. If it doesn't fit cleanly, ship the local rejudge only.

Plus: README rewrite around the two-product story (gateway routes every token, evaluatorq issues
every verdict, `battles.jsonl` + ELO are the reusable benchmark output).

**Rank-stability check (~15 LOC on top):** after a rejudge, print the Spearman rank correlation
between the recorded run's ELO order and the re-judged order. High correlation = the ranking is
judge-robust; low = it's panel preference. This is the strongest available answer to "your
leaderboard is just what three cheap models like."

---

> **Harvest addendum (2026-07-12):** a comparative review of the chennai brainstorm fork
> (`~/conductor/workspaces/orc-arena-v1/chennai`) identified 10 features worth taking — roster
> picker over the workspace-enabled catalog, cost engine + prices.yaml, fixture recorder with real
> pacing, battle browser, Fleiss/Cohen κ, per-model post-mortems, CRT-neon theme, Swiss auto-switch
> for >8 pools, headless match concurrency, post-demo CTA — sequenced as PRs 5–8. Methodology never
> flows in (chennai's rating core is match-level, tie-less, CI-less). Full report:
> `outputs/html/orc-arena-vs-chennai-report.html`
> (https://claude.ai/code/artifact/c66af501-60ae-430c-a32e-8ec5093dd451).

## PR 5 — Benchmark ergonomics (merged: original PR 5 + Harvest 09) · ~+160 LOC

On branch `feat/chennai-harvest`. Nothing here adds a subsystem — knobs and slices.

> **Deferred (owner, 2026-07-12): dollar-cost estimation** (Harvest 02 — `prices.yaml`,
> `estimate_tournament_cost`, USD panels). Too loose for now: the price table is a hand-maintained
> guess that goes stale monthly. What we *record* is exact — token counts per side, per judge,
> per round — and that's what ships, shaped so a future `prices.yaml` multiply-through lands as
> one small isolated PR.
>
> **Dropped (owner, 2026-07-12): fixture recording as product surface** (Harvest 03 —
> recorder port, `--record` flags, `demo --refresh`, pacing keys). The `demo` command itself
> stays exactly as shipped (~30 lines + one committed fixture — the only zero-key path, and the
> CTA's trigger). Recording has one real consumer: regenerating the fixture when the schema
> changes. That's a dev task → `scripts/record_fixture.py` (the PR-2 smoke script, formalized;
> not CLI surface, needs a key, run rarely).

1. **`scripts/record_fixture.py`** (~50, dev-only): tiny real run → event capture with curated
   delays → writes `fixtures/demo_tournament.json`. Documented in the script header, not README.
2. **Preflight** (before the first API call): exact call counts — matches × rounds × warrior
   streams and judge calls (panel × 2 orderings) — plus a **thinking probe**: one tiny call per
   warrior, flag any model whose `reasoning_tokens > 0` despite the uniform-OFF pool (automates
   the kimi audit). Result goes to `run.json` and the mixed-pool badge.
   `preflight: {thinking_probe: true}` config; `--yes` skips the pause. No dollar figures.
3. **Token accounting rollup**: leaderboard panel splitting **judge tokens vs warrior tokens**
   (exact, no price table); totals in `run.json`.
4. **Per-category ELO.** Prompt rows already carry `category`; `BattleRecord` gets the field;
   BT runs overall + per category with a ≥20-comparison floor; leaderboard category picker;
   per-slice counts in `run.json`. Ship 2–3 curated prompt sets.
5. **`--headless`** + **match concurrency** (Harvest 09, ~60): null renderer drains the queue,
   Rich-prints match results + final table; matches run under an `asyncio.Semaphore`
   (`headless_concurrency: 4` default — verify router rate limits at impl time). TUI runs stay
   strictly sequential.
6. **Panel presets** as config comments (demo trio vs frontier judges). No code.

Acceptance: preflight prints call counts + thinking audit; 4-model `--headless` run completes
concurrently with correct ELO; category table renders; leaderboard shows the judge-vs-warrior
token split; `demo` still replays the committed fixture untouched.

## PR 6 — Roster picker over the workspace catalog (Harvest 01) · ~+700 LOC

1. **`providers/models_list.py`** (port): `GET /v2/router/models` (workspace-enabled subset) ∩
   `GET /v2/models` (`type == "chat"`), on `api.orq.ai`; 24h cache at
   `~/.cache/orq-arena/models.json`; `refresh-models` CLI command (`--show` groups by provider).
2. **`roster_select.py`** (port, adapted): live-search input, provider chips, seed-order roster
   panel, live **call-count estimate** as you pick (matches × rounds × judge calls — exact, no
   dollar figures). Drop the `{2,4,8,16,32}` size gate — any ≥2.
   `orc-arena run` with no `--config` opens the picker; `--config` skips it. Picked warriors get
   orc names auto-assigned from a name pool; reasoning defaults to none (provider default) with
   the preflight probe as the safety net.
3. Ships default-styled; restyled by PR 8's theme.

Acceptance: pick 3 models including one think-by-default → probe flags it → manifest records it.

## PR 7 — Trust & insight (Harvest 04/06/07) · ~+560 LOC

1. **Battle browser** (port ~350, adapted to schema v2): leaderboard key `B`; one judged round
   per page — prompt, both responses, per-judge votes **with flip/abstain badges and reasoning**,
   damage/HP deltas, reasoning-token counts. Arrow-key navigation.
2. **κ statistics** (~80 from `judge_stats.py`): Fleiss' κ (+ Landis-Koch label) and pairwise
   Cohen's κ over `judge_votes`; rendered in the jury panel and written to `run.json`. Their
   position-bias section is *not* taken (superseded by evaluatorq's both-orders flips).
3. **Per-model post-mortems** (rebuild ~150, not a port — chennai's uses `instructor`):
   one analyzer call per warrior over its battles + `PairwiseVote.explanation` texts, structured
   output via the existing router client; cached in `analysis.jsonl`; leaderboard key `M`.
   `analyzer_model: openai/gpt-5.4-mini` config default.

Acceptance: `B` pages through a real log; κ shows with its label; `M` renders a post-mortem.

## PR 8 — Show polish (Harvest 05/08/10) · ~+250 LOC

1. **CRT-neon theme** (port `theme.py` + widget restyle). Side identity: **A = magenta,
   B = cyan** (owner decision 2026-07-12) — green/orange are reserved for HP states and
   win/loss semantics. Never pure #000/#fff.
2. **Post-demo CTA modal**: play-live / quit keys, `export ORQ_API_KEY` + orq.ai pointer.
3. **Swiss auto-switch** for pools >8 (`SwissScheduler` port ~70): score-group pairing with
   rematch avoidance; pairs by **match winner** (the HP show) while the rating stays per-round —
   pairing quality affects efficiency only, never validity. ≤8 pools keep full round-robin.

Acceptance: demo ends in the CTA; 10-model headless Swiss run produces per-round-fed ELO; fight
screen screenshots read arcade.

## Reasoning-model support (folded across PRs 1–3)

Today the arena sends no reasoning controls, reads only `delta.content`, and counts tokens by
`len(text)//4` — while the shipped roster already mixes thinking and non-thinking defaults
(`gemini-2.5-pro` is thinking-*enforced* on the router, `gemini-2.5-flash` thinks by default,
the other six don't). The ranking silently conflates model quality with vendor default settings.
Router facts (docs.orq.ai, AI Gateway → Reasoning models): `reasoning_effort`
(`none…xhigh`, OpenAI) and `thinking: {type: enabled|disabled, budget_tokens}` (Claude/Gemini)
are accepted on `/chat/completions` and normalized per model; disabling on thinking-enforced
models is coerced to a minimum budget of 128; setting `reasoning_effort` auto-drops
`temperature`/`top_p`; reasoning usage returns under
`usage.completion_tokens_details.reasoning_tokens`. Visible chain-of-thought in responses is
explicitly **not** part of the router's stable contract — optional provider fields only.

**Interface ruling (owner, 2026-07-11): config file only.** No CLI flags for thinking or effort
— one interface, not two. `WarriorSpec.reasoning: dict | None = None` is the whole mechanism:
raw router fields passed verbatim as `extra_body` on the warrior's `create()` call. No shorthand
syntax (`reasoning: off` sugar would need per-provider expansion tables). Any custom or future
router control passes through with zero arena code. YAML comments carry the three provider
recipes:

```yaml
warriors:
  - orc_name: Azog Deepmind
    model_id: google/gemini-2.5-pro
    # think-by-default model: explicitly disabled for the uniform-OFF default pool
    # (router coerces disable to its minimum budget of 128 on thinking-enforced models)
    reasoning: { thinking: { type: disabled } }
  - orc_name: Grak the Thoughtful
    model_id: anthropic/claude-opus-4-7   # no reasoning block = provider default (off)
# recipes: OpenAI  -> reasoning: { reasoning_effort: low|medium|high }
#          Claude  -> reasoning: { thinking: { type: enabled, budget_tokens: 4096 } }
#          Gemini3 -> reasoning: { thinking: { thinking_level: low|high } }
```

- **Default policy: uniform OFF.** The default config carries explicit
  `thinking: {type: disabled}` blocks on think-by-default warriors (today: the two gemini-2.5
  entries) and nothing on the rest — explicit beats a blanket-send, and the dumb-pipe rule holds
  (no per-provider logic in arena code, just per-warrior config lines).
- Config validation: `thinking.budget_tokens < max_tokens` (per-warrior `max_tokens` override
  added, defaulting to `gateway.warrior_max_tokens`).
- **Roster refresh (both configs).** The current 8-warrior list was hand-picked at repo creation
  and is stale (gpt-4o, deepseek-v3, mistral-large). At PR 1, refresh against the router's live
  registry (verify `GET {base_url}/models` at impl time) with current-gen picks documented on the
  router: gpt-5.x family, claude-sonnet-4-6 / opus-4-x, gemini-3-preview family, plus whatever
  current deepseek/mistral the registry lists. Roster selection stays manual curation in YAML —
  no discovery mechanism in code.
- **Second config: `configs/reasoning_arena.yaml`** — the "does thinking help" benchmark.
  Modern reasoning models only (no o-series — dated): gpt-5.x with `reasoning_effort`,
  claude-4.x with thinking budgets (budget 4096 / max_tokens 16000 per docs pairing),
  gemini-3-preview with `thinking_level`. Same prompts, thinking ON uniformly.
- Router base URL: `https://api.orq.ai/v3/router` (PR 1). `api.orq.ai` is the public-facing
  host and the one this repo always shows; `my.orq.ai` is an alias to the same server and fine
  where the orq-ai-sdk uses it internally. `/v3` is the docs-canonical path for raw OpenAI
  clients.
- Judges stay non-reasoning by default; if ever wanted, `llm_jury_pairwise(extra_kwargs=...)`
  carries `reasoning_effort` panel-wide — note in config comments, don't build anything.

**orq-ai-sdk check (4.11.7, /Users/arian/…/orq-python).** The official SDK's
`router.chat.completions.create()` exposes everything above *typed*: `reasoning_effort`
(`none…xhigh`), `thinking` (enabled / disabled / adaptive schemas), `max_completion_tokens`,
`stream` + `stream_options`, and `usage.completion_tokens_details.reasoning_tokens` — our
`extra_body` pass-through serializes to exactly the fields the typed SDK sends, so the two paths
are wire-identical. Warriors stay on `AsyncOpenAI` anyway, for three reasons: evaluatorq's
judge client is `AsyncOpenAI` (shared `client=`, one HTTP stack), the openai SDK's async
streaming iterator is the cleaner fit for the TUI loop, and the router docs' own examples use it.
orq-ai-sdk enters where it belongs: PR 4's platform upload already pulls it via
`evaluatorq[orq]`, and the README can show the typed-SDK variant of a warrior call as the
"official SDK" example. If we later want typed reasoning controls in arena code, swapping the
warrior call to orq-ai-sdk is a contained change to `providers/orq_gateway.py` only.

**Into PR 1 (TUI):** response panel gets an animated "thinking…" timer between `TurnPrompt` and
its first `ResponseChunk` (widget-local, no new events). Best-effort CoT: if a streamed delta
carries an optional reasoning field (`getattr(delta, "reasoning_content", None)` /
`model_extra`), render it dimmed as a rolling last-~3-lines window — never depend on it (router
contract above); the timer is the guaranteed path.

**Into PR 3 (usage):** the `usage_out` capture also reads
`completion_tokens_details.reasoning_tokens`; `BattleRecord` gains `tokens_a_reasoning` /
`tokens_b_reasoning` and per-side time-to-first-token. `run.json` records each warrior's
effective reasoning setting (explicit config or `"vendor-default"`).

**Into PR 2 (leaderboard, extends §2.5):** mean reasoning tokens rendered beside the verbosity
column; thinking-enabled warriors get a 🧠 badge; mixed pools are **allowed** (deliberately —
"is +40 ELO worth 6× the tokens and 10× the latency?" is a legitimate benchmark and precisely
the router's pitch) with a footnote naming the mix. No hard error, no confirmation prompt.

**Timeouts & incomplete responses (into PR 1).** State today: the router imposes no timeout
unless `timeout.call_timeout` is sent (we never send it); the openai SDK's *default*
`httpx.Timeout(600, connect=5)` is the only cutoff — an inherited, unconfigured 10-minute
read-gap guard. The real defect is failure handling: `_generate_side` swallows any stream
exception and the round is judged on the partial/empty text, so a timeout or disconnect becomes
a forfeit scored as merit. Policy:

- **Wait for the model, always.** `AsyncOpenAI(timeout=httpx.Timeout(connect=10, read=cfg.gateway.stream_read_timeout_s, write=60, pool=60))`
  with `stream_read_timeout_s: 1200` default (20 min of inter-chunk silence tolerated — covers
  thinking; fires only on true silence, never on a slow-but-alive stream). No total cap; never
  send router `call_timeout`. Not infinite: a dead connection must eventually fail or one network
  blip hangs the tournament.
- **Never judge an incomplete response.** On stream error: retry that side once (same prompt);
  still failing → the round is **voided** — no judging, no damage, no round-cap tick, no ELO
  datapoint. Logged in the JSONL as an `error` round with the exception, surfaced in the TUI
  ("connection died — round void") and counted in `run.json` (`error_rounds`). A model must lose
  on its words, never on its network.
- **Truncation is visible, not voided.** Record `finish_reason` per side in `BattleRecord`;
  `length` means the model spent its budget — judged as-is, but auditable. (Thinking budgets
  can't eat the answer: `budget_tokens < max_tokens` validation above.)
- Judge calls keep evaluatorq's `timeout_ms` (default 90s) — non-thinking judges; exposed as
  `judge_timeout_ms` in config for anyone running a thinking panel.

**Acceptance (PR 1 smoke config):** include one thinking-enabled warrior
(`anthropic/claude-*, budget 2048, max_tokens 4096`); verify the thinking indicator renders, the
match completes, and reasoning tokens land in the record. Timeout path: unit-test the
void-round flow (fake stream raising mid-iteration → retry → void, zero damage, zero ELO rows).

## TUI upgrades (the show is the product — ~200 LOC across PRs 1/2/5)

Grounded in a read of `tui/`: the event wiring is clean, but the drama is flat — the KO climax
is one dim status line, `WarriorCard` renders a hardcoded `ELO 1000` forever (dead `set_elo`),
verdict "A" is never visually tied to the left card, and the leaderboard is a bare table.

**PR 1 (with the judge/thinking work):**
- **Side identity colors** — side A green / side B orange on warrior-card borders, response-panel
  borders, and judge verdict cues. One CSS class per side; ends the mental "which one is A" hop.
- **Damage that lands** — floating `−30!` on the hit card, HP bar color states
  (green → yellow → red), KO as a centered banner + `App.bell()` instead of a status-line note.
- **Tokens/sec ticker** in each response panel footer (live chars/4 estimate; stamped with real
  usage on `ResponseComplete`… of its PR-3 successor). Model speed differences are gateway drama.
- Already specified elsewhere: thinking timer, dimmed CoT window, flip/abstain judge badges,
  void-round banner, truncation marker.

**PR 2 (with the round-robin work):**
- Bracket strip's replacement: **match ticker + live top-5 ELO strip**
  (`MATCH 12/28 · Grak vs Snot`), reshuffling on each `StandingsUpdated`.
- **Wire warrior-card ELO live** — `set_elo` resurrects with real data: `ELO 1187 ▲+23`
  between matches. The number the repo exists to compute finally appears during the show.
- Leaderboard: ±CI column, 🧠 badges, mean-tokens column, jury table, low-confidence banner
  (§2.5) **plus an N×N win-grid heatmap** (colored `DataTable` cells — non-transitivity visible
  at a glance).
- **`s` binding → `App.save_screenshot()`** (Textual-native SVG export), bound on all screens.
  README/Show-HN screenshots generate themselves.

**PR 5 (ergonomics):**
- Replay controls in demo mode: `space` pause, `+`/`-` speed multiplier (fixture currently plays
  at a hardcoded 0.02s/event — judge reasoning is unreadable).
- Round intro shows the prompt's `category` tag once per-category ELO exists.

**Rejected for the TUI:** markdown rendering of streams (heavy mid-stream), chart libraries,
mouse navigation, theming. Plain streaming text reads fine.

## Explicitly rejected (the cut list stays cut)

Swiss or bracket modes, human-vote web UI, a database, multi-run aggregation services, custom
judge-prompt DSLs, parallel match execution. Any of these returns only with a ticket and an owner.

---

## Sequencing, risk, rollback

- **Order:** PR 1 → PR 2 → PR 3 → PR 4. PR 2 depends on PR 1's vocabulary; PR 3's fixture
  regeneration depends on PR 2's events; PR 4 reads PR 1's schema v2.
- **Each PR:** tests green + smoke run (live for PR 1/2, offline demo for PR 3). PRs revert
  independently.
- **Pinned-branch risk:** RES-760 is unmerged in evaluatorq; pin an exact SHA and re-pin on
  release of 1.3.0. If the branch is force-rebased, the `[tool.uv.sources]` path dep keeps local
  dev working.
- **Latency:** both-orderings judging doubles judge calls but runs them concurrently — wall-clock
  per round ≈ one judge call, unchanged. Volume knobs if cost bites: `swap=False` (halves),
  smaller `max_rounds`, smaller pool.
- **LOC ledger:** −196 (judges/) −100 (bracket + stub) −65 (dead, ~10 overlap) +~40 (adapter,
  scheduler, jury widget) ⇒ ~1,600 src LOC.

## Decisions taken (flag if you disagree)

1. evaluatorq vocabulary end-to-end; record schema v2; battlebench byte-compat dropped.
2. Judge display names derived from model id tail; no name map.
3. HP tie at round cap = draw (seed advantage deleted with the seeds).
4. `min_successful_judges=2` + one neutral replacement judge as shipped defaults.
5. Sequential matches only; `concurrency` knob deleted rather than implemented.
6. Fixture regenerated (not migrated) in PR 3.
7. KO is presentation, not termination — every match judges all `max_rounds` prompts (§2.1).
8. Leaderboard always shows CIs and mean output tokens; low judge agreement is announced, not
   buried (§2.5). A benchmark that can't say "insufficient data" is a toy.
9. Reasoning controls are raw router fields passed through verbatim (`WarriorSpec.reasoning` →
   `extra_body`), never modeled per-provider in arena code; the router normalizes. Config file
   is the only interface — no CLI flags for thinking/effort, no shorthand syntax.
9a. Default pool is uniform thinking-OFF (explicit disable blocks on think-by-default warriors);
    `configs/reasoning_arena.yaml` is the uniform thinking-ON counterpart with modern reasoning
    models (no o-series). Mixed pools allowed, badged 🧠, footnoted — never refused.
9b. Rosters are refreshed to current-gen models at PR 1, verified against the router registry;
    selection stays manual YAML curation, no discovery code.
12. Streams are waited out, not raced: 1200s read-gap guard (config), no total cap, no router
    `call_timeout`. A round with an incomplete response is retried once, then voided — partial
    output is never judged, so slow thinking is never penalized.
13. Side identity colors are A = magenta / B = cyan once the CRT theme lands (owner,
    2026-07-12); green/orange are HP-state and win/loss colors only.
14. Preflight runs a per-warrior thinking probe by default (config-off) — vendor-default
    thinking is detected before it contaminates a run, not after.
15. Swiss pairing consumes match winners (the show); the rating never stops being per-round.
16. Post-mortem analyzer defaults to a cheap model (`openai/gpt-5.4-mini`), one call per warrior
    per run, cached in `analysis.jsonl`.
17. Harvest rule: features flow in from chennai, methodology never does.
18. Dollar-cost estimation deferred (owner, 2026-07-12): stale-prone price tables are guesses;
    exact token counts ship instead, shaped so pricing can bolt on later as an isolated PR.
19. Demo stays as shipped (zero-key funnel, ~30 lines + fixture); fixture *recording* is a dev
    script, never product surface (owner, 2026-07-12). No --record flags, no demo --refresh,
    no pacing keys.
10. Visible chain-of-thought is rendered best-effort only ("thinking…" indicator is the
    guaranteed path) — the router's stable contract excludes CoT text.
11. Warrior + judge traffic stays on `AsyncOpenAI`; orq-ai-sdk (typed reasoning controls,
    platform APIs) enters via PR 4 / README examples. All user-facing URLs in this repo use
    `api.orq.ai` (`my.orq.ai` is the same server, SDK-internal use is fine); base URL becomes
    `https://api.orq.ai/v3/router` in PR 1.
