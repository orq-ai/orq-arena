# orq-arena plan

> **Status (2026-07-12):** PRs 1–8 executed and live-verified; dependency is the official
> `evaluatorq>=1.8.0` from PyPI; leaderboard shows model names only. Working branch: `master`
> (post-merge); `gnhf/…` and `feat/chennai-harvest` kept as the granular history.
> **G1 ran 2026-07-12** (28 matches / 140 rounds / 10.7 min, `outputs/g1/`): pipeline clean,
> renders clean, three real bugs caught and fixed; the <25% inconclusive gate number itself
> proved miscalibrated, see G1 for the measured story and the proposed replacement gate.
> **G2 merged the same day**: master now carries the refactor
> ([#1](https://github.com/orq-ai/orq-arena/pull/1), [#2](https://github.com/orq-ai/orq-arena/pull/2)).
> **G2.5 shipped 2026-07-12** (report page + length-controlled ELO + BYOK + demo GIF).
> **Next up: G3 remainder (HN post draft), G4, then PR 9.**
> Full historical specs for PRs 1–8 live in git history (`git log --follow REFACTOR_PLAN.md`)
> and in the reports below, this document keeps only what's ahead, the executed summary, and
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

### G1, Dress rehearsal *(the A− → A gate)*, **RAN 2026-07-12, artifacts in `outputs/g1/`**
One full default run: 8 warriors, 28 matches, headless start to finish, then the leaderboard
surfaces at real volume (TUI screens piloted over the real log; SVGs exported headlessly).

**Pass checklist (measured):**
- [x] Run completed unattended in **10.7 min** (concurrency 4): 140/140 rounds, 280 warrior
      streams, 840 judge calls; warriors 8.3k in / 219k out, jury 1.47M in / 109k out.
- [x] **Zero voided rounds**; token accounting complete on all 140.
- [ ] Inconclusive share **48.6%, gate FAILED as written, number needs recalibration** (below).
- [x] Leaderboard renders sanely at 8 rows: CIs, token split, categories, jury+κ, win grid
      (`outputs/g1/leaderboard.svg`).
- [x] `B` browser paged over the 140 real rounds; `M` post-mortems analyzed all 8 models live
      (cached in `outputs/g1/analysis.jsonl`; the coach caught truncation losses again).
- [x] `rejudge` ran over the log, twice (gpt-5.1 solo; haiku+gpt-5.1+gemini-2.5-flash panel).
- [x] README-grade SVGs exported headlessly (leaderboard / browser / postmortem). Fight-screen
      shot still wants a live/themed-fixture run (fold into G2 fixture regen).

**The inconclusive finding (the reason this gate exists).** 68/140 rounds inconclusive, but
**59 of 68 are flip-abstentions, only 6 are true judge splits**: per-judge flip rates haiku 30%,
flash-lite 45%, nano 45%, so ≥2 of 3 votes die and the min-2 quorum (rightly) refuses a verdict.
Meanwhile decisive votes agree at 93% and Fleiss' κ = 0.815, the panel isn't noisy, it's
conservative on close frontier pairs. Rejudge evidence: gpt-5.1 solo still flips 25% on the same
rounds (solo ranking Spearman vs run: 0.50, solo judges are NOT a fix); the 3-judge candidate
panel landed at 52.9% inconclusive yet ranking Spearman 0.83. Verdict: **the <~25% number was a
pre-measurement guess; the honest gate is ranking signal, not abstention rate**, proposed
replacement: rated rounds ≥ 50% of judged, κ ≥ 0.6, decisive-agreement ≥ 85% (this run: 51%
rated, κ 0.815, 93%). More/costlier judges don't buy decisiveness here; they buy the G4 story.

**G1 catches fixed:** `rejudge` crashed on panels smaller than the run's `min_successful_judges`
(now clamped); manifest end-rewrite clobbered `started_at` (now preserved, + `finished_at`);
`judge_max_tokens` 512 starved thinking-by-default judges, gemini-2.5-flash lost **every** vote
to `LengthFinishReasonError` mid-rejudge, silently covered by a 74%-flip replacement → default
raised to 2048 (a cap, costs nothing on frugal judges).
**Paper-cuts filed:** win-grid 9-char names collide (two `gemini-3` columns); ELO CI renders the
raw −3000 BT clamp for a cratered model; replacement-judge quality is invisible in the TUI (the
74%-flip stand-in surfaced only in rejudge stats).

### G2, Merge train, **DONE 2026-07-12**
[#1](https://github.com/orq-ai/orq-arena/pull/1) (refactor, PRs 1–4) and
[#2](https://github.com/orq-ai/orq-arena/pull/2) (harvest + G1, PRs 5–8) squash-merged to
master; suite green on the result. Squash because the repo ruleset requires signed commits and
six early commits weren't, the granular history lives on the kept branches. Fixture regen
also done (`demo` blanked names off the stale pre-rename fixture; regenerated, plus unknown
names now render instead of silently skipping `MatchStarted`).

### G2.5, Run report page, **DONE 2026-07-12** *(pulled from PR 12, decision 23)*
Shipped: `src/orq_arena/report.py` renders a self-contained page (verdict hero with CI-overlap
caveat and κ badge, ELO ladder with CI bars and the len-ctrl column, win grid with full-name
rows, jury room, category/token accounting, manifest hashes); written automatically after every
run and regenerable with `orq-arena report <log>` (no API calls). Same day, a parallel session
landed the two launch-research blockers: **length-controlled ELO** (`style_controlled_elo`,
jury length coefficient printed with the standings; on the G1 log the jury leaned longer at
+3.90 and gemini-3.5-flash drops 1128 to 1034 priced-out), **judge/warrior family-overlap
preflight warning** (self-preference caveat), **BYOK docs** (any OpenAI-compatible endpoint),
and the **demo GIF** (G3 item).

### G3, Show-HN kit, **README/OSS half done 2026-07-12**
Done (`8fcc993`, `e2cebe6`): project renamed **orq-arena** (decision 25); README rebuilt on the
house pattern (splash, badges, G1 screenshots, zero-key demo first); LICENSE, CONTRIBUTING,
PR template, `.env.example` (+ stdlib loader), CI workflow, `media/`, pyproject metadata.
Remaining: demo GIF; post draft led by the flip-badge story ("individual judges are
position-biased; the gated panel is judge-robust, the tool proves it about itself") and
linking a real G2.5 report page.

### G4, Judge-quality experiment
`rejudge` one real log with a strong panel (opus / gpt-5.4 / gemini-pro); publish κ + Spearman
vs the cheap trio. One command; pre-empts the strongest objection.

---

## PR 9, Library-first inversion (the future `evaluatorq.arena` module)

The benchmark is an evaluatorq-tied framework; the TUI is a bonus (decision 21). evaluatorq has
the exact module precedent (`redteam`, `simulation`: own extra, own CLI mount, own run store)
and **no macro pool-ranking layer**: this is that layer.

1. **Package split.** Core (`config`, `preflight`, `arena/`, `tournament/`, `analysis/`,
   `providers/`, `data/`, `headless`) imports zero Textual. `textual` → 
   `[project.optional-dependencies] tui`; `orq_arena.tui` imports lazily with a friendly
   "pip install orq-arena[tui]" error. Same commit: core vocabulary goes model-neutral
   (`warriors:` → `models:`, `WarriorSpec` → `ModelSpec`, `orc_name` → `name`, `orcs/roster.py`
   → `roster.py`), an `evaluatorq.arena` candidate can't ship fantasy nouns; the TUI keeps the
   warrior/HP/damage theatre as pure presentation (decision 24).
2. **CLI inversion.** `orq-arena bench` = primary, headless by default: writes `battles.jsonl`
   + `run.json` + machine-readable `report.json` (ELO, CIs, κ, categories, tokens); exit-code
   asserts (`--assert-agreement 0.5`, `--assert-min-rated N`) so CI can fail a run.
   `orq-arena run` (TUI) requires the extra. `demo`/`rejudge` unchanged.
3. **Programmatic API.** `from orq_arena import run_benchmark` returning a typed result.
   GitHub Action recipe: nightly "did the router's new model reshuffle our pool?".
4. **Event stream stays the seam**: core emits, any renderer consumes.

**Merge-to-evaluatorq criteria (not before):** human-anchor validation done (PR 11), API stable
across real uses, evaluatorq team wants the surface. On merge: core → `src/evaluatorq/arena/`,
extra `evaluatorq[arena]`, CLI `evaluatorq arena bench`; the themed TUI rides along
(`redteam/ui` precedent) or stays here as the skin.

## PR 10, Ops hardening + statistics

1. **`--resume`** from a partial `battles.jsonl` (seeded schedule + manifest identify remaining
   matches). Reference: Model-Router-Auto-Evaluation's checkpoint/resume.
2. **429 backoff-with-jitter** inside the stream retry, *before* the void policy, a rate-limit
   storm must not void rounds. Per decision 20: backoff + resume only, no budget guard.
3. **`--dry-run`**: validate config + prompts, print call counts, **zero API calls** (thinking
   probe explicitly skipped).
4. **Regularized BT** (small ridge prior): kills ±3000 small-n explosions; CIs stay.
5. **`orq-arena merge a.jsonl b.jsonl …`**: pooled rating, chained manifests; refuse on
   config-hash mismatch unless `--force`.
6. Preflight prints an expected-CI-width hint for the chosen n.

## PR 11, Validation & data quality *(the citability gate)*

1. **Prompt bank**: 30 → 150–300, category-balanced; pilot-run discrimination pass drops
   prompts where every pair ties; private-set option (publish hashes, not text).
2. **Judge sanity suite** (CI, no humans): inject degraded responses (truncated / wrong /
   off-topic); the panel must catch ≥ threshold.
3. **Length-controlled scoring toggle**: correct the verbosity confound; show both numbers.
4. **Human anchor study**: ~50–100 rounds, 2–3 blind raters; publish panel↔human κ + rank
   correlation in `METHODS.md`. **This converts "self-consistent" into "validated".**

## PR 12, Launch polish (report renderer moved to G2.5)

1. ~~One-file HTML report per run~~ → **G2.5** (decision 23). PR 9's `bench` wires it in as the
   default post-run output; the zero-key demo path also ends in this report.
2. **`METHODS.md`**: how the number is made (pairwise both-orders, gating, BT, CIs, κ, void
   policy, thinking policy) + the PR 11 human-anchor results.
3. ~~OSS packaging kit~~ → shipped with G3's README pass (`e2cebe6`): `.env.example`,
   CONTRIBUTING, PR template, badges, CI workflow, media/. Left here: QUICKSTART.md if the
   README's quick-start outgrows itself, and `--help` text polish alongside PR 9's CLI
   inversion.

**Sequencing:** G1–G2 → **G2.5** → G3–G4 → PR 9 → 10 → 11 → 12. Engineering lives in 9–10; the
A+ lives in 11–12.

---

## Prior art to reference

**Model-Router-Auto-Evaluation** (`~/Developer/workspace/opensource/Model-Router-Auto-Evaluation`)
already proved in-house: one-file HTML dashboard per run, zero-key demo ending in the full
report, `--dry-run`, checkpoint/resume, `.env.example` onboarding, OSS packaging kit, verdict
banner. Platform tier to consider later: provisioned versioned judges (`provision-judge`) and
cloud sync with Studio deep links.

**chennai worktree** (`~/conductor/workspaces/orq-arena-v1/chennai`): harvested (8 features in);
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
| fixes | `cb01205` `f84da47` `4b74de4` `e5cdd93` `7217a69` `cdf42af` | Textual 8.x `_render` shadowing (×2, second caught by the render test); response-panel wrapping; verdict visibility (stale cards + 2.5s hold); `warrior_max_tokens` 1024→2048; **official evaluatorq ≥1.8.0** (git pin + path override removed); **model names only**. |

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
7. KO is presentation, not termination, every match judges all `max_rounds` prompts.
8. Leaderboard always shows CIs and token columns; low judge agreement is announced, not buried.
9. Reasoning controls are raw router fields passed verbatim (`WarriorSpec.reasoning` →
   `extra_body`); config file is the only interface, no CLI flags, no shorthand.
   9a. Default pool uniform thinking-OFF (explicit disable blocks); `configs/reasoning_arena.yaml`
   is the uniform-ON counterpart; mixed pools allowed, badged, footnoted, never refused.
   9b. Rosters refreshed against the live registry; selection stays manual YAML curation.
10. Visible chain-of-thought is best-effort ("thinking…" timer is the guaranteed path), the
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
    surface, no `--record`, no `demo --refresh`, no pacing keys.
20. No client-side token-budget/spend guard: budgets are the router/gateway's job (workspace
    controls). Arena records exact usage; the platform enforces policy.
21. Library-first: the core is an evaluatorq-tied framework and a candidate `evaluatorq.arena`
    module; TUI is the `orq-arena[tui]` extra. Separate repo until human-anchor validation +
    API stability earn the merge.
22. Model names only on the leaderboard: `orc_name` defaults to the model short name; flavor
    pool deleted; custom names possible, never generated.
23. Per-run HTML report pulled forward to G2.5 (before the HN post): static single file in the
    Model-Router-Auto-Evaluation dashboard mold, rendered from the log + manifest alone.
    Explicitly not a live dashboard, no server, no state.
24. Two-layer vocabulary: the core/library and config speak models (`models:`, `ModelSpec`,
    `name`); only the TUI speaks arena (warriors, HP, damage). Rename rides PR 9's package
    split, every import is already moving; no standalone rename churn.
25. Project renamed **orq-arena** (was orc-arena): "orc" was playful but muddied the goal of
    promoting orq.ai, and the GitHub repo was already `orq-ai/orq-arena`. Package
    `orq_arena`, CLI `orq-arena`, config `orq_arena.yaml`. Internal fantasy identifiers still
    exit at PR 9 (decision 24).
