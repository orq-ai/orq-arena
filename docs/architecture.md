# Architecture

Technical design, component diagram, data flow, and key abstractions for orq-arena, a
terminal LLM arena that turns a round-robin tournament into a Bradley-Terry ELO leaderboard.

## System overview

orq-arena is a Python CLI benchmark tool, installed as the `orq-arena` console script
(entry point `orq_arena.cli:cli` in [`pyproject.toml`](../pyproject.toml), a `click` group in
[`src/orq_arena/cli.py`](../src/orq_arena/cli.py)), that runs a round-robin (or Swiss, above
8 candidates) tournament over a pool of LLMs reachable through the orq.ai router gateway, judges
every round with evaluatorq's bias-controlled pairwise jury, and produces a Bradley-Terry ELO
leaderboard with bootstrap confidence intervals. The architectural style is a **typed
event-queue spine**: the tournament engine
([`tournament/driver.py`](../src/orq_arena/tournament/driver.py),
[`arena/battle.py`](../src/orq_arena/arena/battle.py)) is the sole producer onto an
`asyncio.Queue[ArenaEvent]` ([`events.py`](../src/orq_arena/events.py), every event a pydantic
`BaseModel`), and two interchangeable consumers drain it, a Textual TUI
([`tui/app.py`](../src/orq_arena/tui/app.py)) for the live show, and a Rich-based headless
printer ([`headless.py`](../src/orq_arena/headless.py)) for CI/cron. Both consumers only
render; neither can push anything back into the engine or influence a verdict. A `demo` mode
replays a recorded fixture ([`fixtures/demo_tournament.json`](../fixtures/demo_tournament.json))
through the same event vocabulary with no network calls, so the TUI renders identically
whether the run is live or replayed.

## CLI commands

| Command | Handler | Purpose |
|---|---|---|
| `run` | `cli.py` → `tournament/driver.py::run_tournament`, or `tui/app.py` | Live tournament. Without `--config`, opens the roster picker over the workspace model catalog first (the YAML still supplies judges, rules, and gateway settings). `--headless` runs the same engine through `headless.py`'s Rich printer instead of the TUI, and requires `--config`. |
| `demo` | `cli.py` → `tui/app.py::_replay_fixture` | Replays `fixtures/demo_tournament.json` through the TUI, no API key, no network. |
| `list-models` | `cli.py` | Prints the configured roster (seed, orc name, model id) from the loaded YAML. |
| `rejudge` | `cli.py` → [`rejudge.py`](../src/orq_arena/rejudge.py)`::rejudge_run` | Re-scores a recorded `battles.jsonl` with a new judge panel and reports rank-stability (Spearman) against the original ranking, zero regeneration. |
| `report` | `cli.py` → [`report.py`](../src/orq_arena/report.py)`::build_report_html` | Renders the single-file HTML report page from a recorded `battles.jsonl` + its `*.run.json` manifest, no API calls. The same page is written automatically at the end of every live run. |
| `jury-compare` | `cli.py` → [`rejudge.py`](../src/orq_arena/rejudge.py)`::compare_reports` | Tabulates candidate juries from saved rejudge report JSONs; no API calls. |
| `annotate` | `cli.py` → [`anchor.py`](../src/orq_arena/anchor.py) | Renders the blinded human-annotation page from a recorded log (static or `--serve` localhost). |
| `anchor` | `cli.py` → [`anchor.py`](../src/orq_arena/anchor.py) | Merges vote files into human-vs-panel κ and rank correlation. |
| `refresh-models` | `cli.py` → [`providers/models_list.py`](../src/orq_arena/providers/models_list.py)`::fetch_chat_models` | Bypasses the 24h cache and re-fetches the workspace-enabled chat model catalog. |

## Component diagram

```text
                       ┌───────────────────────────────────┐
                       │  cli.py  (click group)             │
                       │  run · demo · rejudge ·            │
                       │  list-models · refresh-models    │
                       └───────────────┬─────────────────────┘
                                       │ loads
                     ┌─────────────────┼──────────────────────┐
                     ▼                                        ▼
         config.py :: ArenaConfig               data/prompts.py :: PromptItem[]
       (orq_arena.yaml, validated)                    (JSONL, per-category)
                     │                                        │
                     └─────────────────┬──────────────────────┘
                                       ▼
             tournament/driver.py :: run_tournament()
     round_robin_schedule (≤8 candidates)  |  tournament/swiss.py (>8, auto)
                                       │  one Battle per match
                                       ▼
              arena/battle.py :: Battle.run()
      ┌─────────────────────────────┼──────────────────────────────┐
      ▼                             ▼                               ▼
providers/orq_gateway.py     evaluatorq.llm_jury_pairwise    arena/damage.py
  stream_completion()             .compare()                 compute_damage()
      │                             │                               │
      └──────────► api.orq.ai/v3/router ◄──────────┘                │
             (model streams + judge calls, one AsyncOpenAI client) │
                                       │                              │
                                       ▼                              ▼
                          events.py :: ArenaEvent      data/schemas.py :: BattleRecord
                       (asyncio.Queue - typed, pydantic)              │
                     ┌─────────────────┴────────────────┐            ▼
                     ▼                                  ▼    data/log.py :: BattleLog
            tui/app.py (Textual)              headless.py (Rich)     │
           ArenaApp - CRT-neon show          run_headless - CI/cron  ▼
          (display only, never judges)     (parallel matches)  battles.jsonl
                                                                battles.run.json
```

Two side-channels sit outside this main loop and are worth knowing about separately:

- **Re-judge** ([`rejudge.py`](../src/orq_arena/rejudge.py)) skips the engine entirely, it
  reads a finished `battles.jsonl` straight off disk and drives a fresh
  `llm_jury_pairwise` panel directly, so the event queue and the TUI/headless consumers are
  never involved.
- **Post-mortem** ([`analysis/postmortem.py`](../src/orq_arena/analysis/postmortem.py)) is
  triggered on demand from the leaderboard screen (key `m`), not by the tournament loop; it
  makes one analyzer call per candidate against the finished `battles.jsonl` and caches results
  next to it.
- **Model catalog** ([`providers/models_list.py`](../src/orq_arena/providers/models_list.py))
  feeds the roster picker and `refresh-models`; it is a read path against orq.ai's model
  listing endpoints, independent of the gateway calls the battle loop makes.

## Data flow

A full tournament, triggered by `orq-arena run` (`cli.py` → `run_tournament` in
[`tournament/driver.py`](../src/orq_arena/tournament/driver.py)):

1. **Load & pick**: `cli.py` loads `.env` (`_load_dotenv`, `os.environ.setdefault`, never
   overrides an already-set variable), parses `orq_arena.yaml` into an `ArenaConfig`
   (`config.py::load_config`), and loads the prompt set (`data/prompts.py::load_prompts`,
   default `prompts/starter.jsonl`; `--prompts orq:<dataset_id>` pulls an orq.ai Dataset via
   the orq-python SDK instead, and `orq_dataset_meta` resolves its id, display name, and
   studio URL, best-effort, for the run manifest and report). Without `--config`, the TUI's
   roster picker opens first (backed by `providers/models_list.py::fetch_chat_models`);
   picked model ids become `CandidateSpec`s via `roster.py::assign_candidates`.
2. **Preflight**: `preflight.py::call_counts` prints exact match/stream/judge-call totals
   before anything is spent; if `preflight.thinking_probe` is on, `thinking_probe` sends one
   tiny call per candidate and `surprises` flags any model that reasons despite being configured
   off. This runs from the CLI before the confirmation prompt, or in-app
   (`ArenaApp._probe_then_begin`) when the roster came from the picker.
3. **Schedule**: `round_robin_schedule` (every pair once, seeded shuffle) pairs ≤8 candidates;
   `tournament/swiss.py::SwissScheduler` (score-group pairing, `swiss_rounds` rounds, default
   6) takes over above that, selected automatically by candidate count, never a user-facing
   flag. A run manifest is written immediately (`_write_manifest`, `<output>.run.json`) with
   config/prompt hashes, the roster, and (when prompts came from an orq.ai
   Dataset) its id/name/url.
4. **Per match**: each pairing becomes one `arena/battle.py::Battle`. For every prompt (up to
   `match.max_rounds`), `Battle.run` streams both models concurrently (`asyncio.gather`)
   through `providers/orq_gateway.py::OrqGateway.stream_completion`, one `AsyncOpenAI` client
   pointed at `api.orq.ai/v3/router`, pushing `ResponseChunk`/`ThinkingChunk`/
   `ResponseComplete` events as text and reasoning deltas arrive. A stream that raises gets one
   retry (`_generate_side`); a second failure voids the round (`RoundVoided`,
   `BattleRecord.error` set), never judged, never scored.
5. **Judge**: both full responses go to `evaluatorq.llm_jury_pairwise` (a `PairwiseComparator`
   built once per match from `cfg.judges`, minus any candidate that is also configured as a
   judge, self-judge exclusion; raises if that empties the panel). `.compare(...)` runs the
   panel in both seat orders and reconciles to a `PairwiseComparison{winner, votes}`; fewer
   than `min_successful_judges` decisive votes yields `'inconclusive'`. Every vote is re-emitted
   as a `JudgeVerdictEvent`.
6. **Damage & record**: `arena/damage.py::compute_damage` turns the comparison into HP damage
   (`damage_unanimous` only when every decisive vote agrees with the winner, else
   `damage_majority`; `0` damage and no round-cap tick on tie/inconclusive) and a
   `BattleRecord` (schema v2, [`data/schemas.py`](../src/orq_arena/data/schemas.py)) is appended
   to the run's `data/log.py::BattleLog` (`battles.jsonl`).
7. **Live standings**: after each match, `outcomes_from_records` folds its judged rounds into
   the running outcome list and `tournament/elo.py::bradley_terry_mle` recomputes ELO for every
   candidate; a `StandingsUpdated` event carries the live board to whichever consumer is running.
8. **Report & close**: once every match (or Swiss round) completes, `_final_report` bundles
   the final ratings, a bootstrap 95% CI per candidate (`bootstrap_ci`), the length-controlled
   rating and length coefficient (`style_controlled_elo`), per-category ELO slices
   (categories with ≥20 comparisons only), Fleiss'/pairwise Cohen's κ
   ([`analysis/kappa.py`](../src/orq_arena/analysis/kappa.py)), token/verbosity/reasoning-token
   rollups, and the win grid into a `TournamentEnded` event; the manifest is rewritten with the
   finished report and the HTML report page is written next to the log
   ([`report.py`](../src/orq_arena/report.py)).
9. **Consume**: `tui/app.py::ArenaApp` or `headless.py::run_headless` drains the same queue
   end to end and renders it (CRT-neon fight screen → leaderboard, or one-liners → a Rich
   standings table).

### One judged round, in detail

```text
Battle.run() - one round, per prompt in the match's slice
───────────────────────────────────────────────────────────

prompt
  │
  ├─ stream ─▶ candidate A ─┐        OrqGateway.stream_completion()
  │                       ├─ asyncio.gather ─▶  api.orq.ai/v3/router
  ├─ stream ─▶ candidate B ─┘        (ResponseChunk / ThinkingChunk events)
  │
  │  either side raises? ── retry once (_generate_side) ── raises again?
  │                                                             │
  │                                                             ▼
  │                                                   RoundVoided
  │                                                   (BattleRecord.error set -
  │                                                    never judged, never scored)
  ▼  both sides streamed OK
evaluatorq.llm_jury_pairwise(...).compare(question, response_a, response_b)
  panel sees BOTH seat orders · fewer than min_successful_judges
  decisive votes ⇒ consensus is 'inconclusive'
  │
  ▼
PairwiseComparison{ winner: A|B|tie|inconclusive, votes: [PairwiseVote, ...] }
  │
  ▼
arena/damage.py :: compute_damage()
  tie / inconclusive ─▶ 0 damage, doesn't count toward the round cap
  A / B              ─▶ damage_unanimous (all decisive votes agree with
                         the winner) or damage_majority otherwise
  │
  ▼
BattleRecord (schema v2) ──▶ BattleLog.append ──▶ battles.jsonl
  │
  ▼
TurnResolved / JudgeVerdictEvent ──▶ asyncio.Queue[ArenaEvent] ──▶ TUI or
                                                    headless printer (display only)
```

## Key abstractions

| Abstraction | Kind | Location | Purpose |
|---|---|---|---|
| `ArenaEvent` | pydantic `Union` (11 event types) | [`events.py`](../src/orq_arena/events.py) | The typed vocabulary pushed onto the `asyncio.Queue` that decouples the engine from any consumer; every event is a `BaseModel` so the `demo` fixture can round-trip them as JSON. |
| `run_tournament` / `_final_report` | async function | [`tournament/driver.py`](../src/orq_arena/tournament/driver.py) | The orchestrator, builds the schedule, runs matches (optionally concurrent under headless), maintains live Bradley-Terry ELO, writes the run manifest, and bundles CIs/κ/token rollups into the closing report. |
| `Battle` / `Battle.run` | class | [`arena/battle.py`](../src/orq_arena/arena/battle.py) | Drives one match: turn loop over prompts, streams both sides concurrently, invokes the jury, applies damage, appends `BattleRecord`s. |
| `OrqGateway` | class | [`providers/orq_gateway.py`](../src/orq_arena/providers/orq_gateway.py) | Single `AsyncOpenAI` client pointed at `api.orq.ai/v3/router`; every candidate stream and every judge call (via evaluatorq's shared `.client`) rides this one instance. |
| `compute_damage` / `DamageResult` | function + dataclass | [`arena/damage.py`](../src/orq_arena/arena/damage.py) | Maps a `PairwiseComparison`'s consensus to HP damage and loser side; tie/inconclusive rounds deal 0 damage and don't count toward the round cap. |
| `BattleRecord` | pydantic model, schema v2 | [`data/schemas.py`](../src/orq_arena/data/schemas.py) | One judged-or-voided round: prompt, both responses, reconciled per-judge votes, token/TTFT/duration/finish-reason accounting, HP before/after. |
| `BattleLog` | class | [`data/log.py`](../src/orq_arena/data/log.py) | Append-only JSONL sink for `BattleRecord`; truncates on open (one tournament per output file). |
| `bradley_terry_mle` / `bootstrap_ci` / `style_controlled_elo` | functions | [`tournament/elo.py`](../src/orq_arena/tournament/elo.py) | Iterative MLE Bradley-Terry ratings (pure Python, no numpy) anchored to a 1000 mean, a percentile bootstrap for 95% CIs, and a logistic BT refit with a length-difference covariate that yields the len-ctrl rating plus the jury's length coefficient. Ties split 0.5/0.5. |
| `SwissScheduler` | class | [`tournament/swiss.py`](../src/orq_arena/tournament/swiss.py) | Score-group pairing that avoids rematches; auto-engaged by the driver for pools >8 candidates, never a user-facing mode switch. |
| `fleiss_kappa` / `cohen_kappa_pairs` / `landis_koch` | functions | [`analysis/kappa.py`](../src/orq_arena/analysis/kappa.py) | Chance-corrected inter-judge agreement, Fleiss' over the full panel, pairwise Cohen's between judge pairs, computed only over rounds where every counted panelist voted decisively. |
| `rejudge_run` / `spearman` | async function + function | [`rejudge.py`](../src/orq_arena/rejudge.py) | Re-scores every recorded round in a `battles.jsonl` with a new panel, zero regeneration, and reports the Spearman correlation between the old and new Bradley-Terry rankings. |
| `call_counts` / `thinking_probe` / `judge_family_overlaps` | functions | [`preflight.py`](../src/orq_arena/preflight.py) | Exact pre-run call accounting, a one-call-per-candidate probe that flags vendor-default thinking the config didn't ask for, and a self-preference check that warns when a judge shares a provider family with a contestant. |
| `build_report_html` / `write_report` | functions | [`report.py`](../src/orq_arena/report.py) | Self-contained HTML report page (verdict banner with top-3 win rate/ELO/cost, ELO ladder with CI bars, len-ctrl column, value map, Speed section when duration data is present, win grid, jury behaviour) written next to the log at run end and on `orq-arena report`. |
| `fetch_chat_models` | async function | [`providers/models_list.py`](../src/orq_arena/providers/models_list.py) | Workspace-enabled chat model catalog, cached 24h at `~/.cache/orq-arena/models.json`, feeding the roster picker and `refresh-models`. |
| `analyze_model` / `Postmortem` | function + pydantic model | [`analysis/postmortem.py`](../src/orq_arena/analysis/postmortem.py) | Per-model coach notes (strengths/weaknesses/judge patterns) from a cheap analyzer model (`cfg.analyzer_model`), cached in `analysis.jsonl` next to the log. |
| `ArenaConfig` / `CandidateSpec` | pydantic models | [`config.py`](../src/orq_arena/config.py), [`roster.py`](../src/orq_arena/roster.py) | Validated `orq_arena.yaml`, match rules, gateway settings, candidate roster (raw reasoning controls forwarded verbatim), judge panel, quorum. Validates ≥2 candidates, a non-empty judge panel, and that each candidate's thinking `budget_tokens` stays under its token cap. |
| `ArenaApp` | Textual `App` | [`tui/app.py`](../src/orq_arena/tui/app.py) | Wires the event queue to the CRT-neon TUI (title → roster picker → fight → leaderboard → battle browser / post-mortem); live or fixture-replay mode; a pure consumer. |
| `run_headless` | async function | [`headless.py`](../src/orq_arena/headless.py) | Same `run_tournament` core, a Rich one-liner printer instead of a TUI, parallel matches under `headless_concurrency`. |

## Design invariants worth knowing

- **Round-robin vs. Swiss is sizing, not a mode.** `tournament/swiss.py`'s scheduler engages
  only when the roster exceeds 8 candidates (`len(cfg.candidates) > 8` in `driver.py`); below that,
  every pair meets once via `round_robin_schedule`. There is no config flag for this, one
  code path, sized automatically to the roster (the scheduler's own docstring: "never a
  user-facing mode").
- **KO is presentation; every judged round rates.** The HP bar can hit zero mid-match, but the
  turn loop keeps drawing prompts until `match.max_rounds` rounds are judged, the rating
  ignores HP entirely and is fed per-round verdicts, so a match resolving by `"ko"` vs
  `"round_cap"` only changes the on-screen story, never the ELO input.
- **The jury quorum guards the big hit.** `min_successful_judges` (default 2) is the floor for
  a decisive round; below it, the consensus is `'inconclusive'`. Even at quorum,
  `compute_damage`'s "unanimous" branch requires *every* decisive vote (still ≥2) to agree
  with the winner before the higher `damage_unanimous` lands, a degraded panel can never land
  the big hit on its own say-so.
- **A model loses on its words, never on its network.** `_generate_side` retries a failed
  stream exactly once per side; a second failure voids the round, never judged, never scored,
  but logged (`RoundVoided`) and shown. The gateway's timeout is read-gap only
  (`stream_read_timeout_s`, default 1200s / 20 minutes of silence between chunks) with no
  total-duration cap, so a model that thinks for minutes before its first token is never
  penalized, only a genuinely dead connection times out.
- **The event queue is one-way.** `ArenaEvent` is the only channel out of the engine;
  `tui/app.py` and `headless.py` both just drain the same `asyncio.Queue` and render, neither
  calls back into the driver, the battle loop, or the ELO feed.
- **Reproducible by construction.** Every run seeds `round_robin_schedule` and each match's
  prompt slice (`random.Random(seed)`), and writes a `<output>.run.json` manifest, config
  hash, prompt hash, roster, judge panel, evaluatorq version, dataset id/name/url
  when prompts came from an orq.ai Dataset, and (once finished) agreement stats,
  next to the JSONL it describes.

## Directory structure rationale

```
orq-arena/
├── src/orq_arena/            # the package - installed as the `orq-arena` console script
│   ├── cli.py                 #   click group: run · demo · rejudge · report · list-models · refresh-models
│   ├── config.py               #   orq_arena.yaml -> ArenaConfig (pydantic, validated)
│   ├── events.py                #   ArenaEvent union - the typed queue spine
│   ├── preflight.py              #   exact call counts + per-candidate thinking probe
│   ├── rejudge.py                 #   jury-swap re-scoring over a recorded battles.jsonl
│   ├── report.py                  #   single-file HTML report page from a recorded run
│   ├── headless.py                 #   CI/cron runner - same engine, Rich printer, no TUI
│   ├── orcs/                        #   CandidateSpec + roster assignment
│   ├── providers/                    #   orq_gateway.py (router client) + models_list.py (catalog, 24h cache)
│   ├── tournament/                    #   driver.py (schedule + orchestration), elo.py (Bradley-Terry + CIs), swiss.py
│   ├── arena/                          #   battle.py (one match), damage.py (verdict -> HP)
│   ├── data/                            #   schemas.py (BattleRecord v2), log.py (JSONL sink), prompts.py (JSONL + orq.ai Dataset loader)
│   ├── analysis/                         #   kappa.py (Fleiss'/Cohen's κ), postmortem.py (cached coach notes)
│   └── tui/                               #   Textual app - title, roster picker, fight, leaderboard, battle browser, post-mortem
├── configs/                  # YAML presets - reasoning_arena.yaml (uniform thinking-ON pool)
├── prompts/                  # evaluation prompt sets (JSONL) - starter.jsonl is the CLI default
├── fixtures/                 # demo_tournament.json - recorded events replayed by `orq-arena demo`
├── outputs/                  # conventional destination for --output in headless/CI runs
├── tests/                    # pytest suite - no network, incl. Textual render pilots
├── media/                    # README/doc SVG assets
├── orq_arena.yaml            # default roster + judge panel (the config `run` loads by default)
└── docs/                     # this documentation set
```

- **`src/orq_arena/`** mirrors the pipeline itself: `tournament/` schedules, `arena/` fights one
  match, `providers/` is the only thing that talks to orq.ai, `data/` is the schema and the
  sink, and `analysis/` computes cross-cutting statistics after the fact. `tui/` and
  `headless.py` are the two presentation layers and hold no benchmark logic of their own.
  `cli.py`, `config.py`, `events.py`, `preflight.py`, and `rejudge.py` sit at the package root
  because each is a cross-cutting entry point rather than belonging to one pipeline stage.
- **`configs/`** holds alternate rosters as plain YAML, version-controlled the same way as the
  default `orq_arena.yaml` at the repo root, `reasoning_arena.yaml` is the uniform
  thinking-ON counterpart to the default uniform thinking-OFF pool.
- **`prompts/`** and **`fixtures/`** are input data: `prompts/starter.jsonl` is what a live run
  judges by default, `fixtures/demo_tournament.json` is a fully recorded event stream so `demo`
  needs no API key.
- **`outputs/`** is not a hardcoded default, the CLI writes `battles.jsonl` to the working
  directory unless `--output` overrides it, but it is the conventional place to point
  `--output` (e.g. `--output outputs/run.jsonl`, as in [cli.md](cli.md)), keeping generated
  run artifacts out of the repo root.
- **`tests/`** runs fully offline (84 tests across 21 files),
  including Textual "render pilot" tests for the fight, leaderboard, and battle-browser
  screens.
