<p align="center">
  <img src="media/orq-arena-splash.svg" alt="orq-arena — LLM arena benchmark" width="100%">
</p>

# orq-arena

[![CI](https://github.com/orq-ai/orq-arena/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/orq-ai/orq-arena/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-%3E%3D3.10-blue.svg)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

A terminal arena where LLMs fight — and the fight is a real benchmark. It answers the question
every model pool raises: **"which of these models actually wins on *my* prompts, and can I
trust the ranking?"**

Models stream answers side by side, an LLM jury judges every round from both seat orders, HP
bars drop, and a **Bradley-Terry ELO leaderboard** comes out the other end with confidence
intervals attached. The arena is the show; the data is the point.

![Final leaderboard: ELO with bootstrap CIs, token split, per-category ratings, jury behaviour, win grid](media/leaderboard.svg)

## Why orq-arena?

Scoring one model against a rubric is a solved problem — that's
[evaluatorq](https://github.com/orq-ai/evaluatorq). What it doesn't give you is a **ranking of
a whole pool**: when five models all pass your evals, which one should be the default? Absolute
scores saturate; pairwise preference under a bias-controlled jury still separates them.

orq-arena is that missing layer. It runs a round-robin over any pool of models reachable
through the [orq.ai router gateway](https://docs.orq.ai/docs/ai-gateway) — one OpenAI-compatible
client, one API key, every provider — and hands every verdict to evaluatorq's pairwise jury:
each judge sees the pair in *both orders*; a judge that contradicts itself abstains and is
recorded as position-biased; a degraded panel yields `inconclusive` rather than a fake verdict.

**Use it when you want to:**

- Pick a default model for a product on **your own prompts**, not a public leaderboard's
- Re-rank the pool when a new model drops — one command, ~10 minutes, exact token accounting
- Generate **pairwise preference data** (`battles.jsonl`) with per-judge votes for later analysis
- Check whether "thinking" actually helps on your workload (uniform ON vs OFF pools)
- Project a genuinely fun terminal show that is quietly producing all of the above

## What you get

- **A defensible ranking, not a vibe** — pairwise judging in both seat orders, per-round
  Bradley-Terry with ties, bootstrap 95% CIs, Fleiss'/Cohen's κ, and a seeded manifest per run.
- **Zero-friction start** — `orq-arena demo` replays a recorded tournament with no API key.
- **A live show worth projecting** — CRT-neon TUI: streaming responses, judge cards that call
  out position-biased votes in public, HP drama, live standings.
- **Real benchmark data out the back** — every round lands in `battles.jsonl` (schema v2):
  both responses, reconciled per-judge votes, exact token/reasoning-token usage, TTFT.
- **Jury swaps without regeneration** — re-judge any recorded run with a different panel and
  get a rank-stability answer (Spearman).
- **Headless for CI/cron** — same benchmark, parallel matches, no TUI.

## Installation

Requires **Python >= 3.10** and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/orq-ai/orq-arena.git
cd orq-arena
uv sync
```

## Quick start

The fastest way to see everything — **no API key needed**:

```bash
uv run orq-arena demo
```

When you are ready for a live run against real models:

1. Get an API key from your [orq.ai](https://my.orq.ai) workspace and make it available:
   `cp .env.example .env`, then fill in `ORQ_API_KEY` (loaded automatically).
2. Start a tournament — a roster picker opens over your workspace-enabled model catalog;
   choose any pool ≥ 2:

   ```bash
   uv run orq-arena run
   ```

3. Before spending tokens, the preflight prints exact match/stream/judge-call counts and
   probes the pool for vendor-default thinking. Confirm, and the arena begins.

In the TUI: `s` saves an SVG screenshot, `q` quits. On the final leaderboard `B` opens the
battle browser and `M` the post-mortem coach.

## Usage

### Run a tournament

```bash
uv run orq-arena run                                   # interactive roster picker
uv run orq-arena run --config orq_arena.yaml           # YAML roster as-is (8 models, 28 matches)
uv run orq-arena run --headless --yes \
    --config orq_arena.yaml --output outputs/run.jsonl # CI/cron: no TUI, parallel matches
```

Every pair fights once (round-robin; Swiss pairing above 8 models), `max_rounds` prompts per
match. The headless runner prints one-liners per match and the full statistical leaderboard at
the end — same engine, same `battles.jsonl`.

### Browse the results

From the final leaderboard, `B` pages through every judged round — prompt, both responses, and
each judge's reconciled vote, flips included. `M` asks an analyzer model for per-model coach
notes (strengths, weaknesses, what judges rewarded), cached next to the log.

| The battle browser (`B`) | The post-mortem coach (`M`) |
|---|---|
| ![Battle browser: prompt, both responses, per-judge votes with flip badges](media/battle-browser.svg) | ![Post-mortems: per-model strengths, weaknesses, and judge patterns](media/postmortem.svg) |

### Re-judge with a different jury (no regeneration)

The responses are already in `battles.jsonl`, so swapping the jury costs judge tokens only:

```bash
uv run orq-arena rejudge battles.jsonl \
  --judge mistral/mistral-small-2603 \
  --judge anthropic/claude-haiku-4-5-20251001
```

Prints the new panel's behaviour (per-judge lean, flip rate, tie rate) and the Spearman
correlation between the recorded ranking and the re-judged one — the direct answer to
*"is this leaderboard just judge preference?"*

### Roster and model catalog

```bash
uv run orq-arena list-warriors     # print the configured pool
uv run orq-arena refresh-models    # re-fetch the workspace catalog (cached 24h)
```

## Configuration

Everything lives in `orq_arena.yaml` — no flags to remember:

```yaml
warriors:            # the pool — leaderboard names default to the model name
  - model_id: anthropic/claude-opus-4-8
  - model_id: google/gemini-3.1-pro-preview
    reasoning: { thinking: { type: disabled } }   # raw router fields, verbatim

judges:            # evaluatorq pairwise panel — plain router model ids
  - anthropic/claude-haiku-4-5-20251001
  - google/gemini-2.5-flash-lite
  - openai/gpt-5.4-nano
replacement_judges: [mistral/mistral-small-2603]
min_successful_judges: 2   # jury-of-one -> inconclusive, never a verdict
```

Reasoning recipes (forwarded untouched; the router normalizes per provider):

```yaml
# OpenAI   -> reasoning: { reasoning_effort: low|medium|high }
# Claude   -> reasoning: { thinking: { type: enabled, budget_tokens: 4096 } }
# Gemini 3 -> reasoning: { thinking: { thinking_level: low|high } }
```

The default pool is **uniform thinking-OFF** (verified per model against the live router) so
the ELO compares models, not vendor default settings. `configs/reasoning_arena.yaml` is the
uniform thinking-ON counterpart — the "does thinking help?" benchmark. Mixed pools are allowed
and get badged and footnoted on the leaderboard.

## How the number is made

- **Pairwise, same prompt, both seat orders** — the Chatbot-Arena family of methodology, with
  evaluatorq's consistency gate on top.
- **Per-round ratings.** Every judged round (win *or* tie) feeds Bradley-Terry MLE — a default
  run rates on up to 140 comparisons, not 7 knockouts. KO is presentation: the HP bar can hit
  zero, the judging finishes anyway.
- **Bootstrap 95% CIs** on the leaderboard; overlapping intervals are the honest output on
  small runs.
- **A model loses on its words, never on its network.** A stream that dies is retried once,
  then the round is *voided* — logged, shown, and excluded from the rating. Timeouts are
  read-gap only (default 20 min of silence) so slow thinkers are never penalized.
- **Self-aware jury.** Mean inter-judge agreement, Fleiss' and pairwise Cohen's κ, and
  per-judge flip rates ship with the standings; a low-agreement run headlines itself as
  low-confidence. Verbosity and reasoning-token columns keep the classic LLM-judge confounds
  visible.
- **Reproducible.** Seeded schedule and prompt slices; every run writes a `*.run.json`
  manifest (config + prompt hashes, panel, evaluatorq version, agreement stats) next to the
  `battles.jsonl` it describes.

## Outputs

| file | what |
|---|---|
| `battles.jsonl` | one row per judged round — prompts, both responses, reconciled per-judge votes (incl. flips), exact token usage incl. reasoning tokens, TTFT, finish reasons, HP bookkeeping (schema v2) |
| `battles.run.json` | run manifest: hashes, roster + reasoning settings, panel, seed, agreement, wall-clock |
| `orq-arena rejudge …` | jury-swap re-scoring + rank-stability check over any recorded log |

## Running tests

```bash
uv run pytest          # 41 tests, no network (incl. headless TUI render pilots)
```

evaluatorq is the official PyPI release (`evaluatorq>=1.8.0`) — no pin, no path override.

## Contributing

Bug reports, feature ideas, documentation fixes, and pull requests are all welcome — see
[CONTRIBUTING.md](CONTRIBUTING.md).

## Related projects

- **[evaluatorq](https://github.com/orq-ai/evaluatorq)** — the evaluation framework doing the
  judging here (pairwise juries, red teaming, agent simulation).
- **[orq-auto-router-evaluation](https://github.com/orq-ai/orq-auto-router-evaluation)** —
  benchmark the Orq Auto Router on quality, cost, and latency over your own workload.
- **[orq-python](https://github.com/orq-ai/orq-python)** — the official typed SDK for the same
  router surface, reasoning controls included.
- **[Orq.ai docs](https://docs.orq.ai)** — the router gateway, evaluators, and platform.

## License

MIT — see [LICENSE](LICENSE) for details.
