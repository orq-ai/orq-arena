# orq-arena documentation

An arena benchmark for LLMs on **your own prompts**. It answers the question every model pool
raises: **"which of these models actually wins on *my* prompts, and can I trust the ranking?"**

One command runs a round-robin tournament over your models. A panel of LLM judges compares every
pair of answers blind, in both orders so no judge can favor "whichever answer came first". Out the
other end: a chess-style **ELO leaderboard** with confidence intervals, and a self-contained
**HTML report** you can send to anyone. A live terminal show ships too, as the bonus.

Every run opens on the **RUN PLAN**: the full pool, every judge, and the worst-case cost per
model, priced before a single token is spent, with one consent gate:

![RUN PLAN screen: the pool, the jury, and the worst-case cost per model, before anything is spent](assets/run-plan.svg)

And ends on the **FINAL STANDINGS**: ELO with 95% CIs and the length-controlled rating,
per-judge behaviour, and the win grid:

![Final standings: ELO ladder with CIs and len-ctrl, per-judge behaviour, win grid](assets/leaderboard.svg)

## Why orq-arena?

Public leaderboards rank models on someone else's prompts. Your eval suite scores models one at a
time, and once several models all pass, the scores stop telling them apart: everything gets a
9/10.

Comparison still works where scores saturate. Show a judge two answers to the same prompt and ask
which is better; that's how [LMArena](https://lmarena.ai) ranks models with human voters.
orq-arena runs the same protocol on **your prompts** with an LLM jury instead of a crowd, and
guards the verdicts: every pair is judged twice with the answers swapped, a judge that changes its
vote when only the order changed is discarded for that round, and if too few trustworthy votes
remain the round counts as `inconclusive` rather than a coin flip.

Models are called through the [orq.ai router gateway](https://docs.orq.ai/docs/ai-gateway), so one
API key covers every provider; judging is [evaluatorq](https://github.com/orq-ai/evaluatorq), our
library for exactly this kind of jury.

**Use it when you want to:**

- Pick a default model for a product on **your own prompts**, not a public leaderboard's
- Re-rank the pool when a new model drops: one command, ~10 minutes, exact token accounting
- Generate **pairwise preference data** (`battles.jsonl`) with per-judge votes for later analysis
- Check whether "thinking" actually helps on your workload (uniform ON vs OFF pools)

## What you get

- **A ranking you can defend.** The rating is
  [Bradley-Terry](https://en.wikipedia.org/wiki/Bradley%E2%80%93Terry_model), the statistical
  model behind chess-style ratings, fit over every judged round with bootstrapped 95% confidence
  intervals. When two models are statistically tied, the report says so instead of hiding it.
  Judge-agreement stats ship with the standings.
- **A report you can forward.** One self-contained HTML file per run. Plain-words verdict up top,
  then the ELO ladder with error bars, a quality-vs-cost chart, latency, and the exact dollar
  spend.
- **Raw data out the back.** Every judged round lands in `battles.jsonl`: both responses, each
  judge's vote, exact token counts, per-response timing. Real pairwise preference data for
  whatever you want to do next.
- **Headless by default.** Plain log lines on pipes, a progress bar on terminals, matches in
  parallel. Drop it in CI or cron with `-y`.
- **Cheap jury swaps.** The responses are already recorded, so re-judging with a different panel
  costs judge tokens only, and tells you how much the ranking depends on who judged it.
- **Human spot-checks.** `annotate` renders a run into a blind page (no model names, no jury
  votes) you can send to human raters; `anchor` compares their votes with the panel's. (The
  mechanism ships; no published study against it yet, see
  [Methodology](methodology.md#current-limitations).)
- **A live show when you want one.** `--tui` (optional extra) opens on a RUN PLAN consent
  screen (full per-model cost table), then streams the run as a live arena with health
  bars and judge cards.

The report is the artifact you forward, one self-contained HTML file:

![HTML report page: verdict banner with the top three models, badges, ELO leaderboard with CI bars, and the ELO-vs-cost value map](assets/report-page.png)

Don't take the bullets' word for it: a real recorded run is committed at
[`examples/quickstart/`](https://github.com/orq-ai/orq-arena/tree/master/examples/quickstart) (an
8-model pool). Inspect the raw `battles.jsonl` and its manifest, or regenerate the report
yourself: `orq-arena report examples/quickstart/battles.jsonl`.

<div class="grid cards" markdown>

-   :material-rocket-launch:{ .lg .middle } **Getting Started**

    ---

    Install, add your key, and get your first benchmark running.

    [:octicons-arrow-right-24: Getting Started](getting-started.md)

-   :material-console:{ .lg .middle } **CLI Reference**

    ---

    Every command and flag with its expected output: `run`, `rejudge`
    (with `--compare`), `report`, `annotate`, `anchor`, `pool`,
    `refresh-catalog`.

    [:octicons-arrow-right-24: CLI Reference](cli.md)

-   :material-tune:{ .lg .middle } **Configuration**

    ---

    Every `orq_arena.yaml` key, its type, default, and effect, plus the
    prompts file format and `.env` loading.

    [:octicons-arrow-right-24: Configuration](configuration.md)

-   :material-scale-balance:{ .lg .middle } **Methodology**

    ---

    How the ranking is made, the bias controls, confidence intervals, and
    when to trust the number.

    [:octicons-arrow-right-24: Methodology](methodology.md)

</div>

## Suggested reading order

- **Running benchmarks?** [Getting Started](getting-started.md) → [Configuration](configuration.md) → [CLI Reference](cli.md)
- **Contributing code?** [CONTRIBUTING.md](https://github.com/orq-ai/orq-arena/blob/master/CONTRIBUTING.md) has the dev setup, project shape, and PR conventions
- **New to Orq.ai?** [orq.ai](https://orq.ai) is the platform behind the router and the jury; [docs.orq.ai](https://docs.orq.ai) covers the gateway, datasets, and API keys
