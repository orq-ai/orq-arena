<p align="center">
  <img src="media/orq-arena-splash.svg" alt="orq-arena, LLM arena benchmark" width="100%">
</p>

# orq-arena

[![CI](https://github.com/orq-ai/orq-arena/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/orq-ai/orq-arena/actions/workflows/ci.yml) [![Python](https://img.shields.io/badge/python-%3E%3D3.10-blue.svg)](pyproject.toml) [![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

An arena benchmark for LLMs on **your own data**.

A new model ships every few weeks, and each one tops a leaderboard somewhere. Whether it wins on your workload is a different question: public leaderboards rank models on someone else's data.

So run your own leaderboard. orq-arena ranks your model pool head-to-head on your own prompts and answers the question directly: **"which of these models actually wins on my data, and can I trust the ranking?"**

One command runs a round-robin tournament over your models. A panel of LLM judges compares every pair of answers blind, in both orders so no judge can favor "whichever answer came first". Out the other end: a chess-style **ELO leaderboard** with confidence intervals.

Every run opens on the **Run Plan**: the full pool, every judge, and the estimated cost to run the benchmark:

![RUN PLAN screen: the pool, the jury, and the worst-case cost per model, before anything is spent](docs/assets/run-plan.svg)

And ends on the **Final Results**: ELO with 95% CIs and the length-controlled rating, per-judge behaviour, and the win grid:

![Final Results: ELO ladder with CIs and len-ctrl, per-judge behaviour, win grid](docs/assets/leaderboard.svg)

## Why orq-arena?

Eval suites score models one at a time and stop discriminating once several models pass: everything reads 9/10 and the ranking goes flat. Head-to-head comparison keeps discriminating: show a judge two answers to the same prompt and ask which is better, the same technique the big human-preference leaderboards use, with an LLM jury instead of a crowd. The verdicts are guarded: every pair is judged twice with the answers swapped, a judge that changes its vote when only the order changed is discarded for that round, and if too few trustworthy votes remain the round counts as `inconclusive` rather than a coin flip.

Models are called through the [orq.ai router gateway](https://docs.orq.ai/docs/ai-gateway), so one API key covers every provider; judging is [evaluatorq](https://github.com/orq-ai/evaluatorq), our library for exactly this kind of jury.

**Use it when you want to:**

- Pick a default model for a product on **your own prompts**, not a public leaderboard's
- Re-rank the pool when a new model drops: one command, exact token accounting
- Generate **pairwise preference data** (`battles.jsonl`) with per-judge votes for later analysis
- Check whether "thinking" actually helps on your workload (uniform ON vs OFF pools)
- Pick the strong/economical pair for your [Orq.ai Auto Router](https://docs.orq.ai/docs/ai-gateway/auto-router): the leaderboard shows which cheaper models are statistically tied with your strongest

## What you get

- **A ranking you can defend.** The rating is [Bradley-Terry](https://en.wikipedia.org/wiki/Bradley%E2%80%93Terry_model), the statistical model behind chess-style ratings, fit over every judged round with bootstrapped 95% confidence intervals. When two models are statistically tied, the report says so instead of hiding it. Judge-agreement stats ship with the standings.
- **A report you can share.** One HTML per run. Verdict first, then the ELO ladder with error bars, a quality-vs-cost chart, latency, and the exact dollar spend.
- **Raw data out the back.** Every judged round lands in `battles.jsonl`: both responses, each judge's vote, exact token counts, per-response timing. Real pairwise preference data for whatever you want to do next.
- **Jury swaps.** The responses are already recorded, so re-judging with a different panel costs judge tokens only, and tells you how much the ranking depends on who judged it.
- **Human spot-checks.** `annotate` renders a run into a blind page (no model names, no jury votes) you can send to human raters; `anchor` compares their votes with the panel's.
- **Watch live.** `--tui` (optional extra) opens on a Run Plan consent screen (the full per-model cost table), then streams the run as a live arena with health bars and judge cards.

The report is the artifact you can share, one self-contained HTML file:

![HTML report page: verdict banner with the top three models, badges, ELO leaderboard with CI bars, and the ELO-vs-cost value map](docs/assets/report-page.png)

## Installation

Requires **Python >= 3.10** and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/orq-ai/orq-arena.git
cd orq-arena
uv tool install .
```

`uv tool install .` puts the **`orq-arena`** command on your PATH in its own isolated
environment: the benchmark, the HTML report, and `rejudge` all run on it. The live `--tui`
show needs the optional extra (`uv tool install '.[tui]'`); without it, `--tui` prints a
friendly install hint. Hacking on the code instead? `uv sync` and prefix commands with
`uv run`.

## Quick start

1. Get an API key from your orq.ai workspace ([API keys guide](https://docs.orq.ai/docs/ai-studio/organization/api-keys)): `cp .env.example .env`, then fill in `ORQ_API_KEY` (loaded automatically).
2. Point the `candidates` list at your model pool (or keep the shipped 8-model `orq_arena.yaml`) and run:

```bash
orq-arena run --config orq_arena.yaml --prompts your_prompts.jsonl
```

Before spending anything, the preflight prints the exact number of API calls and a worst-case dollar ceiling, then asks once. Matches run in parallel with plain log lines. When the last round lands, the **HTML report is written next to the battle log** (`--open` to view it in your browser).

```bash
# CI/cron-ready: -y skips the confirmation (required in a non-interactive
# shell, where the prompt would abort)
orq-arena run --config orq_arena.yaml --prompts your_prompts.jsonl -y
```

Bring your prompts either way:

```bash
# a local JSONL, one prompt per line ("category" is optional)
orq-arena run --config orq_arena.yaml --prompts your_prompts.jsonl

# or an orq.ai Dataset, straight from your workspace
orq-arena run --config orq_arena.yaml --prompts orq:<dataset_id>
```

```jsonl
{"prompt": "Summarize this incident report for a customer email.", "category": "support"}
{"prompt": "Draft the SQL for monthly active users by plan.", "category": "analytics"}
```

Dataset-backed runs record the [Dataset](https://docs.orq.ai/docs/ai-studio/optimize/datasets)'s id, name, and studio URL in the manifest, and the report links it by name. If each match should see every prompt, pass `--rounds <n>`; the preflight warns when it samples a subset.

Set expectations for the out-of-the-box run: the shipped 30-prompt bank and cheap default judge trio are a **smoke test** that exercises every mechanism, not a benchmark. Expect wide, overlapping error bars and a judge/candidate family-overlap caveat on the report; both are the honest output at that scale. A ranking you intend to defend takes your own prompt set (hundreds of rounds) and judges from families outside the pool ([Methodology](docs/methodology.md#current-limitations)).

No key yet? Open the committed example run's report at [`examples/quickstart/`](examples/quickstart/), or regenerate it keyless: `orq-arena report examples/quickstart/battles.jsonl`. Keys: [API keys guide](https://docs.orq.ai/docs/ai-studio/organization/api-keys).

## Usage

**Run the benchmark**: `orq-arena run --config orq_arena.yaml` (headless, parallel, report at the end; the config is explicit, point it at the shipped `orq_arena.yaml` or your own, and edit its `candidates` list to change the pool). Pass `--tui` to watch the fight live. Full flag reference: **[docs/cli.md](docs/cli.md)**.

**Share the result**: the report (`<log>.report.html`) is one self-contained file. It opens with a verdict banner naming the top three models (win rate, ELO, total cost), then the full ladder with error bars, a quality-vs-cost chart, speed, the win grid, and how the jury behaved. Regenerate it any time with `orq-arena report battles.jsonl`, no model calls needed.

**Re-judge with a different jury**: the responses are already in `battles.jsonl`, so swapping the panel costs judge tokens only: `orq-arena rejudge battles.jsonl --judge mistral/mistral-small-2603`. It reports how the new jury behaved and how much the ranking moved. Multi-judge example: **[docs/cli.md](docs/cli.md)**.

## The live show (bonus)

The same run, projected: `orq-arena run --config orq_arena.yaml --tui` opens on the Run Plan consent screen (every model priced, one ENTER to fight), then streams both models side by side with judge cards that call out position-biased votes in public. `s` saves an SVG screenshot, `q` quits.

![The live --tui show: a match streaming side by side, judge cards calling out flipped votes, and the final leaderboard](media/demo.gif)

From the final leaderboard, `B` pages through every judged round (prompt, both responses, per-judge votes with flip badges). Screenshots and keys: [docs/cli.md](docs/cli.md).

## Configuration

Everything lives in `orq_arena.yaml`, no flags to remember. The default pool runs every model with extended reasoning ("thinking") turned **off**, and verifies that against the live router, so the ELO compares models on equal footing rather than whatever each vendor enables by default. `configs/reasoning_arena.yaml` is the thinking-ON counterpart, and [`configs/`](configs/) has ready-made frontier, budget, and 16-model pools. Per-provider reasoning settings, replacement judges, and every other key: **[docs/configuration.md](docs/configuration.md)**.

```yaml
candidates:
  - model_id: anthropic/claude-opus-4-8
  - model_id: google/gemini-3.1-pro-preview
    reasoning: { thinking: { type: disabled } }   # raw router fields, verbatim

judges:
  - anthropic/claude-haiku-4-5-20251001
  - google/gemini-2.5-flash-lite
min_successful_judges: 2   # jury-of-one -> inconclusive, never a verdict
```

## How the number is made

- **Same prompt, both orders.** Every pair of answers is judged twice with positions swapped, the standard defense the big human-preference leaderboards use. A judge that picks A in one order and B in the other was voting on position, not content; its vote is thrown out for that round and the flip is counted against it.
- **Ratings from every round, not from knockouts.** The ELO is a Bradley-Terry fit over all judged rounds (a default 8-model run rates on up to 140 comparisons, not 7 match wins), with bootstrapped 95% confidence intervals. On small runs the intervals overlap; the report says so rather than pretending precision.
- **Length preference is priced out, in public.** LLM judges tend to favor longer answers. The rating is also refit with that preference removed, and both numbers are shown side by side. A model can still win by being longer; it can't do it invisibly.
- **A model loses on its words, never on its network.** A dead stream retries once, then the round is voided, never judged, never scored. Timeouts fire on silence between tokens, not total duration, so slow-thinking models aren't penalized for being slow.
- **Self-aware and reproducible.** Judge-agreement statistics and per-judge flip rates ship with the standings. Every run writes a manifest with the random seed, config and prompt hashes, and the exact panel, enough to rerun or audit it. Full details: **[docs/methodology.md](docs/methodology.md)**.

## Documentation

Full guides live at **[orq-ai.github.io/orq-arena](https://orq-ai.github.io/orq-arena/)** (source in [`docs/`](docs/)); start with the [docs index](docs/index.md) for a reading order tailored to your goal.

| Guide | Description |
|-------|-------------|
| [Getting Started](docs/getting-started.md) | Prerequisites, install, first live run, common setup issues |
| [CLI Reference](docs/cli.md) | Every command and flag: `run`, `pool`, `report`, and the rest |
| [Configuration](docs/configuration.md) | Every `orq_arena.yaml` key, reasoning recipes, defaults |
| [Methodology](docs/methodology.md) | How the ranking is made, bias controls, confidence intervals, reproducibility |

## Contributing

Bug reports, feature ideas, documentation fixes, and pull requests are all welcome; see [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, project shape, and conventions. Run the test suite with `uv run pytest`.

## Related projects

- **[evaluatorq](https://github.com/orq-ai/evaluatorq)**: the evaluation framework doing the judging here (pairwise juries, red teaming, agent simulation).
- **[orq-auto-router-evaluation](https://github.com/orq-ai/orq-auto-router-evaluation)**: benchmark the Orq.ai Auto Router on quality, cost, and latency over your own workload.
- **[orq-python](https://github.com/orq-ai/orq-python)**: the official typed SDK for the same router surface, reasoning controls included.
- **[Orq.ai docs](https://docs.orq.ai)**: the router gateway, evaluators, and platform.

## License

MIT, see [LICENSE](LICENSE) for details.
