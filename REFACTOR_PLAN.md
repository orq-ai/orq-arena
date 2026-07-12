# orc-arena plan

> **Status (2026-07-12):** PRs 1–8 executed and live-verified; dependency is the official
> `evaluatorq>=1.8.0` from PyPI; leaderboard shows model names only. Working branch
> `feat/chennai-harvest` (stacked on `gnhf/…`); master is still pre-refactor.
> **Next up: gates G1–G4, then PR 9.**
> Full historical specs for PRs 1–8 live in git history (`git log --follow REFACTOR_PLAN.md`)
> and in the reports below — this document keeps only what's ahead, the executed summary, and
> the decision log.

**Goal.** An arena benchmark producing a Bradley-Terry ELO ranking over a configurable pool of
models: every verdict from evaluatorq's pairwise jury, every token through the orq.ai router
gateway (`api.orq.ai/v3/router`). One mode. The benchmark core is a library/framework (future
`evaluatorq.arena` module); the Textual TUI is the optional show on top.

**Reports:**
[analysis](https://claude.ai/code/artifact/cb006f76-6fec-4586-a550-a18bfc91617a) ·
[refactor executed](https://claude.ai/code/artifact/f02388ad-5f11-4f0a-b152-0dd414f18996) ·
[chennai harvest](https://claude.ai/code/artifact/c66af501-60ae-430c-a32e-8ec5093dd451) ·
[final grade](https://claude.ai/code/artifact/969f030d-db1c-4b70-b550-6a98b337ab98)

---

## Launch gates (do these before any A+ work)

### G1 — Dress rehearsal *(the A− → A gate)*
One full default run: 8 warriors, 28 matches, live TUI start to finish, then the leaderboard
surfaces at real volume. Nothing beyond 3 models has ever run end to end; both eyeball-found UX
bugs (unwrapped text, vanishing verdicts) were this class of finding. ~1h + a few $.

**Pass checklist:**
- [ ] Run completes without manual intervention; wall-clock and judge-call totals recorded.
- [ ] Zero voided rounds absent a genuine upstream failure; inconclusive share < ~25%.
- [ ] Every leaderboard section renders sanely at 8 rows (CIs, tokens, categories, jury+κ, grid).
- [ ] `B` browser and `M` post-mortems work over ~140 real rounds.
- [ ] `rejudge` runs over the produced log.
- [ ] SVG screenshots captured (`s`) for the README; UX paper-cuts filed or fixed.

### G2 — Merge train
PR `gnhf/…` → master, then `feat/chennai-harvest` → master. Regenerate the demo fixture from a
themed run (`scripts/record_fixture.py`) — it still carries old orc names and pre-theme events.

### G3 — Show-HN kit
README SVGs + demo GIF; post draft led by the flip-badge story ("individual judges are
position-biased; the gated panel is judge-robust — the tool proves it about itself").

### G4 — Judge-quality experiment
`rejudge` one real log with a strong panel (opus / gpt-5.4 / gemini-pro); publish κ + Spearman
vs the cheap trio. One command; pre-empts the strongest objection.

---

## PR 9 — Library-first inversion (the future `evaluatorq.arena` module)

The benchmark is an evaluatorq-tied framework; the TUI is a bonus (decision 21). evaluatorq has
the exact module precedent (`redteam`, `simulation`: own extra, own CLI mount, own run store)
and **no macro pool-ranking layer** — this is that layer.

1. **Package split.** Core (`config`, `preflight`, `arena/`, `tournament/`, `analysis/`,
   `providers/`, `data/`, `headless`) imports zero Textual. `textual` → 
   `[project.optional-dependencies] tui`; `orc_arena.tui` imports lazily with a friendly
   "pip install orc-arena[tui]" error.
2. **CLI inversion.** `orc-arena bench` = primary, headless by default: writes `battles.jsonl`
   + `run.json` + machine-readable `report.json` (ELO, CIs, κ, categories, tokens); exit-code
   asserts (`--assert-agreement 0.5`, `--assert-min-rated N`) so CI can fail a run.
   `orc-arena run` (TUI) requires the extra. `demo`/`rejudge` unchanged.
3. **Programmatic API.** `from orc_arena import run_benchmark` returning a typed result.
   GitHub Action recipe: nightly "did the router's new model reshuffle our pool?".
4. **Event stream stays the seam** — core emits, any renderer consumes.

**Merge-to-evaluatorq criteria (not before):** human-anchor validation done (PR 11), API stable
across real uses, evaluatorq team wants the surface. On merge: core → `src/evaluatorq/arena/`,
extra `evaluatorq[arena]`, CLI `evaluatorq arena bench`; the themed TUI rides along
(`redteam/ui` precedent) or stays here as the skin.

## PR 10 — Ops hardening + statistics

1. **`--resume`** from a partial `battles.jsonl` (seeded schedule + manifest identify remaining
   matches). Reference: Model-Router-Auto-Evaluation's checkpoint/resume.
2. **429 backoff-with-jitter** inside the stream retry, *before* the void policy — a rate-limit
   storm must not void rounds. Per decision 20: backoff + resume only, no budget guard.
3. **`--dry-run`**: validate config + prompts, print call counts, **zero API calls** (thinking
   probe explicitly skipped).
4. **Regularized BT** (small ridge prior): kills ±3000 small-n explosions; CIs stay.
5. **`orc-arena merge a.jsonl b.jsonl …`**: pooled rating, chained manifests; refuse on
   config-hash mismatch unless `--force`.
6. Preflight prints an expected-CI-width hint for the chosen n.

## PR 11 — Validation & data quality *(the citability gate)*

1. **Prompt bank**: 30 → 150–300, category-balanced; pilot-run discrimination pass drops
   prompts where every pair ties; private-set option (publish hashes, not text).
2. **Judge sanity suite** (CI, no humans): inject degraded responses (truncated / wrong /
   off-topic); the panel must catch ≥ threshold.
3. **Length-controlled scoring toggle**: correct the verbosity confound; show both numbers.
4. **Human anchor study**: ~50–100 rounds, 2–3 blind raters; publish panel↔human κ + rank
   correlation in `METHODS.md`. **This converts "self-consistent" into "validated".**

## PR 12 — Report renderer + launch polish

1. **One-file self-contained HTML report per run** (leaderboard, CIs, κ, win grid, jury room,
   verdict banner — house style), written by `bench` automatically; the zero-key demo path also
   ends in this report.
2. **Verdict banner**: one headline conclusion per run.
3. **`METHODS.md`**: how the number is made (pairwise both-orders, gating, BT, CIs, κ, void
   policy, thinking policy) + the PR 11 human-anchor results.
4. **OSS packaging kit**: `.env.example`, QUICKSTART, CONTRIBUTING, badges, CI workflow,
   media/ screenshots, real `--help` text.

**Sequencing:** G1–G4 → PR 9 → 10 → 11 → 12. Engineering lives in 9–10; the A+ lives in 11–12.

---

## Prior art to reference

**Model-Router-Auto-Evaluation** (`~/Developer/workspace/opensource/Model-Router-Auto-Evaluation`)
already proved in-house: one-file HTML dashboard per run, zero-key demo ending in the full
report, `--dry-run`, checkpoint/resume, `.env.example` onboarding, OSS packaging kit, verdict
banner. Platform tier to consider later: provisioned versioned judges (`provision-judge`) and
cloud sync with Studio deep links.

**chennai worktree** (`~/conductor/workspaces/orc-arena-v1/chennai`): harvested (8 features in);
its modes/audio/pickers-for-modes stay dead. Features flow in, methodology never (decision 17).

## Explicitly rejected

Tournament modes (single/double elim, debate), mode pickers, audio, client-side price tables or
budget guards, `--record` product surface, generic n-format tournament engines, Unity/web
renderer seams. Any return needs a ticket and an owner.

---

## Executed record (PRs 1–8 + fixes)

| PR | Commits | Summary |
|---|---|---|
| 1 | `62ffbaa` | `judges/` deleted → `llm_jury_pairwise` (both orders, flip ⇒ recorded abstention, replacements, min-2 floor). Damage adapter (unanimity ≥2 decisive). Records schema v2 (exact tokens incl. reasoning, TTFT, finish reasons). Reasoning controls verbatim per warrior; verified uniform-OFF default pool + `configs/reasoning_arena.yaml`. 1200s read-gap timeout; stream failure → retry → **round voided**. Roster refreshed vs live registry. TUI: side colors, damage drama, thinking timer + live CoT, flip badges. `instructor` out. |
| 2 | `61f40a5` | Bracket deleted → round-robin, any pool ≥2. **Per-round BT with ties**; bootstrap CIs; live standings + card ELO; KO = pure rendering (all rounds judged); draws. Leaderboard: CIs, 🧠 badges, verbosity/reasoning columns, jury table, win grid, agreement banner. Run manifest. Screenshot key. |
| 3 | `775f46b` | Last zero-consumer event deleted; every event has a consumer. |
| 4 | `9e96390` `fd8288b` | `rejudge` (jury swap + Spearman rank-stability; live: 2/6 verdicts changed, ranking held at 1.00). README rewritten. |
| 5 | `09b7d47` | Preflight (exact call counts + **thinking probe**), per-category ELO (20-comparison floor), `--headless` + parallel matches, judges-vs-warriors **token split** (live: jury = 8× warrior tokens), dev-only fixture script, panel-preset docs. |
| 6 | `b29afd8` | Roster picker over the **workspace-enabled catalog** (`/v2/router/models` ∩ `/v2/models` chat, 24h cache, `refresh-models`; live: 137 models). In-app probe post-selection feeds the mixed-pool footnote. |
| 7 | `c234e5f` | Battle browser (`B`), **Fleiss/Cohen κ** (+ coverage, Landis-Koch), per-model **post-mortems** (`M`, JSON-mode on the router client, cached; live test diagnosed truncation losses correctly). |
| 8 | `f4eaa25` | CRT-neon as a native Textual theme (A = magenta / B = cyan), post-demo CTA, **Swiss auto-switch** for pools >8 (pairs by match winner; rating stays per-round). |
| fixes | `cb01205` `f84da47` `4b74de4` `e5cdd93` `7217a69` `cdf42af` | Textual 8.x `_render` shadowing (×2 — second caught by the render test); response-panel wrapping; verdict visibility (stale cards + 2.5s hold); `warrior_max_tokens` 1024→2048; **official evaluatorq ≥1.8.0** (git pin + path override removed); **model names only**. |

Key measured facts: default run = 28 matches / ≤140 judged rounds / ~840 judge calls; jury
tokens ≈ 8× warrior tokens under both-orders judging; cheap judges flip 67–83% on easy pairs
(the gate converts this to abstentions); 41 tests.

---

## Decision log (numbers stable; newest last)

1. evaluatorq verdict vocabulary end-to-end; records schema v2; battlebench byte-compat dropped.
2. Judge display names derive from the model id tail; no name map.
3. HP tie at round cap = draw (seed advantage deleted).
4. `min_successful_judges=2` + one neutral replacement judge as shipped defaults.
5. Sequential matches in the TUI; (superseded in part by PR 5: headless runs parallelize).
6. Demo fixture regenerated, not migrated, when schemas change.
7. KO is presentation, not termination — every match judges all `max_rounds` prompts.
8. Leaderboard always shows CIs and token columns; low judge agreement is announced, not buried.
9. Reasoning controls are raw router fields passed verbatim (`WarriorSpec.reasoning` →
   `extra_body`); config file is the only interface — no CLI flags, no shorthand.
   9a. Default pool uniform thinking-OFF (explicit disable blocks); `configs/reasoning_arena.yaml`
   is the uniform-ON counterpart; mixed pools allowed, badged, footnoted — never refused.
   9b. Rosters refreshed against the live registry; selection stays manual YAML curation.
10. Visible chain-of-thought is best-effort ("thinking…" timer is the guaranteed path) — the
    router's stable contract excludes CoT text.
11. Traffic stays on `AsyncOpenAI`; user-facing URLs use `api.orq.ai` (`my.orq.ai` = same
    server, SDK-internal ok); base URL `https://api.orq.ai/v3/router`. orq-ai-sdk enters via
    platform features/README examples.
12. Streams are waited out, not raced: 1200s read-gap guard, no total cap, no router
    `call_timeout`. Incomplete response → one retry → round voided. A model loses on its
    words, never on its network.
13. Side identity: A = magenta, B = cyan (CRT theme); green/orange/red stay semantic.
14. Preflight thinking probe on by default (config-off).
15. Swiss pairing consumes match winners (the show); the rating never stops being per-round.
16. Post-mortem analyzer defaults to a cheap model (`analyzer_model: openai/gpt-5.4-mini`).
17. Harvest rule: features flow in from chennai, methodology never does.
18. Dollar-cost estimation deferred: price tables are stale-prone guesses; exact token counts
    ship instead, shaped so pricing can bolt on later.
19. Demo stays as shipped (zero-key funnel); fixture recording is a dev script, never product
    surface — no `--record`, no `demo --refresh`, no pacing keys.
20. No client-side token-budget/spend guard: budgets are the router/gateway's job (workspace
    controls). Arena records exact usage; the platform enforces policy.
21. Library-first: the core is an evaluatorq-tied framework and a candidate `evaluatorq.arena`
    module; TUI is the `orc-arena[tui]` extra. Separate repo until human-anchor validation +
    API stability earn the merge.
22. Model names only on the leaderboard: `orc_name` defaults to the model short name; flavor
    pool deleted; custom names possible, never generated.
