# Getting Started

This guide takes you from a fresh clone to your first benchmark: a round-robin tournament
over your model pool, judged in both seat orders by an evaluatorq pairwise jury, ranked by
Bradley-Terry ELO with confidence intervals attached.

The path is five steps:

1. [Install](#1-install) the CLI (`uv sync`).
2. [Add your orq.ai API key](#2-add-your-orqai-credentials) (`.env`).
3. [Run the benchmark](#3-run-the-benchmark) and read the standings.
4. [Bring your own prompts](#4-bring-your-own-prompts): a local JSONL file or an
   orq.ai Dataset.
5. [Know where the results land](#5-where-results-land): the battle log, the manifest, and
   the HTML report.

Every command below runs through the **`orq-arena`** CLI. Run `uv run orq-arena --help` to
list every subcommand; the full flag reference is in **[cli.md](cli.md)**.

---

## Prerequisites

| Requirement | Minimum | How to check |
|---|---|---|
| Python | `>= 3.10` | `python3 --version` |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | any recent | `uv --version` |
| Git | any | `git --version` |
| orq.ai workspace | active, with at least one chat model enabled | [my.orq.ai](https://my.orq.ai) |

The one secret you need is a workspace **API key** (`ORQ_API_KEY`), created per the
[API keys guide](https://docs.orq.ai/docs/ai-studio/organization/api-keys). Every candidate, judge, and
preflight-probe call goes through the orq.ai router gateway with this one key, so one key
covers every provider in the pool.

---

## 1. Install

```bash
git clone https://github.com/orq-ai/orq-arena.git
cd orq-arena
uv sync
```

`uv sync` creates a `.venv` and installs orq-arena plus its core dependencies resolved
against `uv.lock`, registering the **`orq-arena`** console script. That's the only setup
step: the benchmark, the HTML report, and `rejudge` all run on the core install.

Check it worked:

```text
$ uv run orq-arena --help
Usage: orq-arena [OPTIONS] COMMAND [ARGS]...

  orq-arena, LLM arena benchmark: orq.ai router + evaluatorq jury.
...
```

---

## 2. Add your orq.ai credentials

```bash
cp .env.example .env
```

Then fill in the one variable it asks for:

```bash
ORQ_API_KEY=your-orq-api-key
```

`.env` is loaded automatically at the top of every CLI invocation; a variable already set in
your shell always wins over `.env`. `.env` is git-ignored; only `.env.example` is committed.
Full variable reference: [configuration.md](configuration.md#environment-variables).

---

## 3. Run the benchmark

```bash
uv run orq-arena run
```

The model pool comes straight from the `candidates` list in `orq_arena.yaml` (the shipped
file has an 8-model pool; edit it or pass `--config your.yaml`). The essentials of that
file:

```yaml
# orq_arena.yaml (trimmed to the essentials)
candidates:                # the model pool: router model ids, any size >= 2
  - model_id: anthropic/claude-sonnet-4-6
  - model_id: openai/gpt-5.4
  - model_id: deepseek/deepseek-chat
  - model_id: google/gemini-3.5-flash
    reasoning: { thinking: { type: disabled } }   # per-model overrides inline

judges:                    # the jury; every pair judged in both seat orders
  - anthropic/claude-haiku-4-5-20251001
  - google/gemini-2.5-flash-lite
  - openai/gpt-5.4-nano

match:
  max_rounds: 5            # prompts judged per match
```

Every key, default, and per-model override is documented in
[configuration.md](configuration.md). The run walks through three stages:

1. **Preflight.** The exact call counts print up front, then a **RUN PLAN table**: one row
   per candidate and judge with its call count, catalog price, and worst-case cost, closing
   with the maximum the run can spend. A tiny thinking probe runs per candidate, then the
   run pauses at `Proceed (spends up to $X)? [y/N]` before any battle or judge call. Pass
   `--yes`/`-y` to skip the pause in CI or scripts.
2. **The matches.** Every pair of candidates meets once (a full round-robin), matches in
   parallel. For each prompt, both candidates stream through the router, the jury votes in
   both seat orders, and the round is logged.
3. **The standings.** Bradley-Terry ELO with bootstrap 95% CIs, printed in the terminal, and
   the HTML report is written next to the battle log (`--open` to view it in your browser).

**Expected output** (reconstructed from the committed
[`examples/quickstart`](https://github.com/orq-ai/orq-arena/tree/master/examples/quickstart)
run, a 4-model pool against the default judge trio):

```text
$ uv run orq-arena run --config examples/quickstart/config.yaml \
    --output examples/quickstart/battles.jsonl
preflight: 6 matches × 5 rounds → 60 model streams + 180 judge calls + 4 probe calls
                                   RUN PLAN
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━┓
┃ Model                                 ┃ Calls ┃ $/M in ┃ $/M out ┃ Ceiling ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━┩
│ Candidates                            │       │        │         │         │
│   openai/gpt-5.4-mini                 │    15 │   0.75 │    4.50 │   $0.14 │
│   anthropic/claude-sonnet-4-6         │    15 │   3.00 │   15.00 │   $0.46 │
│   google/gemini-3.5-flash             │    15 │   1.50 │    9.00 │   $0.28 │
│   mistral/mistral-medium-2604         │    15 │   1.50 │    7.50 │   $0.23 │
│ Judges (×2 seat orders)               │       │        │         │         │
│   anthropic/claude-haiku-4-5-20251001 │    60 │   1.00 │    5.00 │   $0.88 │
│   google/gemini-2.5-flash-lite        │    60 │   0.10 │    0.40 │   $0.08 │
│   openai/gpt-5.4-nano                 │    60 │   0.20 │    1.25 │   $0.21 │
│ Thinking probe                        │     4 │        │         │   $0.04 │
├───────────────────────────────────────┼───────┼────────┼─────────┼─────────┤
│ MAXIMUM SPEND                         │       │        │         │ ≤ $2.31 │
└───────────────────────────────────────┴───────┴────────┴─────────┴─────────┘
     worst case: every response maxed out at its token cap; typical runs
         cost noticeably less. Exact spend is reported after the run.
thinking probe…
  pool is thinking-clean ✓
Proceed (spends up to $2.31)? [y/N]:
```

**This pause is the cost gate.** Everything above was (almost) free: only the tiny probe
calls have been made, no battle has run. The RUN PLAN table shows the worst case per model,
and the `Proceed` question repeats the maximum the run can spend. Answer `n` and nothing
happens; answer `y` and the matches start:

```text
Proceed (spends up to $2.31)? [y/N]: y
M1 🤝 draw
match 1/6 done
M2 gemini-3.5-flash beats gpt-5.4-mini
match 2/6 done
M4 claude-sonnet-4-6 beats mistral-medium-2604
match 3/6 done
M3 gpt-5.4-mini beats mistral-medium-2604
match 4/6 done
M5 claude-sonnet-4-6 beats gpt-5.4-mini
match 5/6 done
M6 gemini-3.5-flash beats mistral-medium-2604
match 6/6 done

🏆 gemini-3.5-flash leads, but claude-sonnet-4-6 is statistically tied (CIs
overlap at 30 rated rounds; the report page has the tie-breakers)

                   FINAL STANDINGS
┏━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━┳━━━━━━━━━━━━┳━━━━━━┓
┃ # ┃ Model               ┃ ELO  ┃ 95% CI     ┃ win% ┃
┡━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━╇━━━━━━━━━━━━╇━━━━━━┩
│ 1 │ gemini-3.5-flash    │ 1572 │ 1259–5000  │ 70%  │
│ 2 │ claude-sonnet-4-6   │ 1572 │ 1238–4803  │ 70%  │
│ 3 │ gpt-5.4-mini        │ 489  │ -3000–1810 │ 33%  │
│ 4 │ mistral-medium-2604 │ 367  │ -3000–1686 │ 27%  │
└───┴─────────────────────┴──────┴────────────┴──────┘

jury: 95% mean agreement · leaned longer (+2.33); the report prices it out
rounds: 30 rated · 0 voided
tokens, models 1,728 in / 51,324 out · jury 349,228 in / 23,643 out

battle log → examples/quickstart/battles.jsonl
report page → examples/quickstart/battles.report.html
```

!!! tip "No API key yet?"

    A real recorded run is committed at
    [`examples/quickstart/`](https://github.com/orq-ai/orq-arena/tree/master/examples/quickstart).
    Regenerate its report with no key and no network:
    `uv run orq-arena report examples/quickstart/battles.jsonl`.

---

## 4. Bring your own prompts

The whole point of orq-arena is ranking models on **your** prompts. The default
`prompts/starter.jsonl` is just a demo set; swap it with `--prompts`, from a local file or
straight from your orq.ai workspace.

**A local JSONL file** — one JSON object per line, `prompt` is the only required field.
`category` is optional (feeds per-category ratings); any other keys ride along into
`battles.jsonl` so you can join results back to your source data:

```json
{"prompt": "Write a Python function that finds the longest palindromic substring.", "category": "code"}
{"prompt": "Summarize the key trade-offs between SQL and NoSQL for a startup.", "category": "reasoning"}
```

```bash
uv run orq-arena run --prompts your_prompts.jsonl
```

Full field reference: [Prompts file format](configuration.md#prompts-file-format).

**An orq.ai Dataset** — pass `orq:<dataset_id>` to fight over an
[orq.ai Dataset](https://docs.orq.ai/docs/ai-studio/optimize/datasets) from your workspace,
same API key, nothing to export:

```bash
uv run orq-arena run --prompts orq:my_dataset_id
```

Each datapoint's last `user` message becomes a prompt (`{{var}}` placeholders filled from
its `inputs`). The run manifest records the dataset's identity, and the HTML report links
it by name.

!!! tip "Which model ids can fight?"

    `uv run orq-arena refresh-catalog --show` lists your workspace-enabled catalog, grouped
    by provider, ready to paste into the YAML's `candidates` list.

---

## 5. Where results land

Every run writes three files, all in the current working directory by default. Everything
downstream (re-judging, reporting, human annotation) works from the battle log alone, with no
further model calls:

| File | Contents |
|---|---|
| `battles.jsonl` | One JSON line per judged round: both responses, reconciled per-judge votes, token/TTFT accounting. |
| `battles.run.json` | The run manifest: config/prompt hashes, candidate pool, judge panel, seed, and (once finished) agreement stats. |
| `battles.report.html` | A single-file HTML report, no server, no external assets. Verdict banner with the top 3 models up top, then the ELO ladder with error bars, a quality-vs-cost value map, speed, and the exact dollar spend. Forward it to anyone. |

![HTML report page: verdict banner with the top three models, badges, ELO leaderboard with CI bars, and the ELO-vs-cost value map](assets/report-page.png)

Pass `--output path/to/file.jsonl` to move all three; the manifest and report page always sit
next to the log. `orq-arena report <log>` regenerates the report page on demand, and
`orq-arena rejudge` re-scores a recorded run with a different jury at judge-token cost only
(see [cli.md](cli.md)).

---

## Troubleshooting

??? failure "`RuntimeError: ORQ_API_KEY is not set. Export it before running orq-arena.`"

    `.env` is missing, empty, or still the blank template. Run `cp .env.example .env`, fill in a
    real key (created per the [API keys guide](https://docs.orq.ai/docs/ai-studio/organization/api-keys)), and re-run. This
    only fires on `run` or `rejudge`; `report`, `annotate`, and `anchor` work from the recorded
    log with no key at all.

??? warning "A response shows `✂ truncated` in the report"

    The candidate hit its output cap (`gateway.candidate_max_tokens`, default `2048`) before
    finishing, and judges tend to penalize a cut-off answer. Raise `gateway.candidate_max_tokens`
    in your YAML, or set a higher per-candidate `max_tokens` on that one entry. See
    [configuration.md](configuration.md#gateway-gatewayconfig).

??? question "A model you expected in the default pool isn't there"

    `orq_arena.yaml` deliberately excludes models the router can't disable thinking for.
    Mixing an always-thinking model into the uniform thinking-**OFF** pool would compare
    reasoning tokens no config could turn off. Add them to `configs/reasoning_arena.yaml`
    (the thinking-**ON** preset) instead, or add them to your own YAML explicitly if a mixed
    pool is what you want.

---

## Next steps

| Goal | Where to go |
|---|---|
| See every subcommand and flag | [cli.md](cli.md) |
| Understand every `orq_arena.yaml` key | [configuration.md](configuration.md) |
| Understand the scoring methodology | [methodology.md](methodology.md) |
| Contribute to the project | [CONTRIBUTING.md](https://github.com/orq-ai/orq-arena/blob/master/CONTRIBUTING.md) |
