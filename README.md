<p align="center">
  <img src="media/orq-arena-splash.svg" alt="orq-arena — LLM arena benchmark" width="100%">
</p>

# orq-arena

[![CI](https://github.com/orq-ai/orq-arena/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/orq-ai/orq-arena/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-%3E%3D3.10-blue.svg)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

A terminal arena where LLMs fight — and the fight is a real benchmark. It answers the question
every model pool raises: **"which of these models actually wins on *my* prompts, and can I trust
the ranking?"**

Models stream answers side by side, an LLM jury judges every round from both seat orders, HP
bars drop, and a **Bradley-Terry ELO leaderboard** comes out the other end with confidence
intervals attached. The arena is the show; the data is the point.

![Final leaderboard: ELO with bootstrap CIs, token split, per-category ratings, jury behaviour, win grid](media/leaderboard.svg)

Under the hood it is a deliberately thin demo of two things:

- **[orq.ai router gateway](https://docs.orq.ai/docs/ai-gateway)** — every token in the arena
  flows through one OpenAI-compatible client and one API key (`api.orq.ai/v3/router`), across
  Anthropic, OpenAI, Google, DeepSeek, Mistral and friends. Per-model reasoning controls
  (`thinking`, `reasoning_effort`) are raw router fields, forwarded verbatim.
- **[evaluatorq](https://github.com/orq-ai/evaluatorq)** — every verdict on screen is an
  `llm_jury_pairwise` decision: each judge sees the pair in *both orders*; a judge that
  contradicts itself abstains and is recorded as position-biased; a degraded panel yields
  `inconclusive` rather than a fake verdict.

## What you get

- **A defensible ranking, not a vibe** — pairwise judging in both seat orders, per-round
  Bradley-Terry with ties, bootstrap 95% CIs, Fleiss'/Cohen's κ, and a seeded manifest per run.
- **Zero-friction start** — `orq-arena demo` replays a recorded tournament with no API key.
- **A live show worth projecting** — CRT-neon TUI: streaming responses, judge cards that call
  out position-biased votes in public, HP drama, live standings.
- **Real benchmark data out the back** — every round lands in `battles.jsonl` (schema v2):
  both responses, reconciled per-judge votes, exact token/reasoning-token usage, TTFT.
- **Jury swaps without regeneration** — `orq-arena rejudge` re-scores any recorded run with a
  different panel and reports rank stability (Spearman).
- **Headless for CI/cron** — same benchmark, parallel matches, no TUI.

## Installation

Requires **Python >= 3.10** and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/orq-ai/orq-arena.git
cd orq-arena
uv sync
cp .env.example .env   # then add your ORQ_API_KEY (skip for the demo)
```

## Quick start

The fastest way to see everything — **no API key needed**:

```bash
uv run orq-arena demo
```

When you are ready for a live run against real models:

```bash
# a roster picker opens over your workspace-enabled model catalog —
# choose any pool >= 2 (round-robin; Swiss above 8):
uv run orq-arena run

# or skip the picker and use the YAML roster as-is (default: 8 models, 28 matches):
uv run orq-arena run --config orq_arena.yaml

# CI / cron: no TUI, matches in parallel, same battles.jsonl out the end:
uv run orq-arena run --headless --yes --config orq_arena.yaml --output outputs/run.jsonl
```

Before spending tokens, `run` prints a preflight (exact match/stream/judge-call counts) and
probes the pool for vendor-default thinking. In the TUI: `s` saves an SVG screenshot, `q`
quits. On the final leaderboard `B` opens the battle browser and `M` the post-mortem coach.

| The battle browser (`B`) | The post-mortem coach (`M`) |
|---|---|
| ![Battle browser: prompt, both responses, per-judge votes with flip badges](media/battle-browser.svg) | ![Post-mortems: per-model strengths, weaknesses, and judge patterns](media/postmortem.svg) |

## Re-judge yesterday's tournament (no regeneration)

The responses are already in `battles.jsonl`, so swapping the jury costs judge tokens only:

```bash
uv run orq-arena rejudge battles.jsonl \
  --judge mistral/mistral-small-2603 \
  --judge anthropic/claude-haiku-4-5-20251001
```

Prints the new panel's behaviour (per-judge lean, flip rate, tie rate) and the Spearman
correlation between the recorded ranking and the re-judged one — the direct answer to
*"is this leaderboard just judge preference?"*

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

## What makes the number defensible

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

## Development

```bash
uv sync
uv run pytest          # 41 tests, no network (incl. headless TUI render pilots)
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the workflow. evaluatorq is the official PyPI
release (`evaluatorq>=1.8.0`) — no pin, no path override.

Prefer the typed client? The [official SDK](https://github.com/orq-ai/orq-python) exposes the
same router surface, reasoning controls included:

```python
from orq_ai_sdk import Orq

client = Orq(api_key=os.environ["ORQ_API_KEY"])
resp = client.router.chat.completions.create(
    model="anthropic/claude-opus-4-8",
    messages=[{"role": "user", "content": "..."}],
    thinking={"type": "enabled", "budget_tokens": 4096},
)
```

## Related projects

- **[evaluatorq](https://github.com/orq-ai/evaluatorq)** — the evaluation framework doing the
  judging here (pairwise juries, red teaming, agent simulation).
- **[orq-auto-router-evaluation](https://github.com/orq-ai/orq-auto-router-evaluation)** —
  benchmark the Orq Auto Router on quality, cost, and latency over your own workload.
- **[Orq.ai docs](https://docs.orq.ai)** — the router gateway, evaluators, and platform.

## License

[MIT](LICENSE) © Orq.ai
