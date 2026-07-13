# Getting Started

This guide takes you from a fresh clone to a live tournament, a round-robin of LLMs
streaming answers side by side, judged in both seat orders by an evaluatorq pairwise jury,
ranked by Bradley-Terry ELO with confidence intervals attached.

The end-to-end path is:

1. Install the toolkit (`uv sync`).
2. Try the zero-key demo, see the whole show with no credentials.
3. Add your orq.ai API key (`.env`).
4. Run a live tournament, pick a roster, clear the preflight, watch the fight, read the leaderboard.
5. Know where your results land, and what to do if something goes wrong.

Every command below runs through the **`orq-arena`** CLI (installed by the steps in
[1. Install](#1-install)). Run `uv run orq-arena --help` to list every subcommand. The full
subcommand and flag reference is in **[cli.md](cli.md)**.

> **No API key yet?** Skip straight to [2. Try it now](#2-try-it-now--no-api-key-needed),
> `orq-arena demo` replays a full recorded tournament with no network calls. Come back to
> step 3 when you're ready to point at real models.

---

## Prerequisites

| Requirement | Minimum | How to check |
|---|---|---|
| Python | `>= 3.10` | `python3 --version` |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | any recent | `uv --version` |
| Git | any | `git --version` |
| orq.ai workspace | active, with at least one chat model enabled | [my.orq.ai](https://my.orq.ai) |

You only need the workspace for **live** runs, the demo needs none of it. When you do go
live, you need:

- A workspace **API key** (`ORQ_API_KEY`) from [my.orq.ai](https://my.orq.ai) > workspace
  settings > API keys (per `.env.example`). It's the only secret orq-arena needs, every
  candidate, judge, analyzer, and preflight-probe call goes through the orq.ai router gateway
  with this one key.

---

## 1. Install

```bash
git clone https://github.com/orq-ai/orq-arena.git
cd orq-arena
uv sync
```

`uv sync` creates a `.venv` and installs orq-arena plus its dependencies (`textual`, `click`,
`pydantic`, `pyyaml`, `openai`, `httpx`, `evaluatorq`) resolved against `uv.lock`. This
registers the **`orq-arena`** console script (entry point `orq_arena.cli:cli` in
`pyproject.toml`'s `[project.scripts]`), every command below is run through `uv run` so this
is the only setup step.

---

## 2. Try it now, no API key needed

```bash
uv run orq-arena demo
```

This replays a fully recorded tournament, 3 matches, 6 judged rounds, all 3 default judges
voting, from `fixtures/demo_tournament.json` through the exact same TUI screens a live run
uses: streaming responses, judge verdicts, HP drama, and the final leaderboard. No network
calls, no API key. Press `q` to quit, `s` to save a screenshot.

`demo` still loads `orq_arena.yaml` (only for cosmetic labels like the judge names in the
fight-screen header), it ships in the repo, so this works immediately after `uv sync` with no
edits needed. `demo` also takes `--fixture` and `--config` if you want to point it elsewhere;
see [cli.md](cli.md).

---

## 3. Add your orq.ai credentials

```bash
cp .env.example .env
```

Then fill in the one variable it asks for:

```bash
ORQ_API_KEY=your-orq-api-key
```

`.env` is read by a small stdlib-only loader in `src/orq_arena/cli.py` (`_load_dotenv`),
called once at the top of every CLI invocation. It uses `os.environ.setdefault`, so **a
variable already set in your shell always wins**, `.env` only fills in what the shell hasn't
already set. `.env` is git-ignored; only `.env.example` is committed.

`ORQ_API_KEY` is **not** required for `orq-arena demo` or `orq-arena list-models`, only for
`run` and `rejudge`, which construct a gateway client. `refresh-models` wants it too, but
degrades instead of failing: without a key the catalog fetch quietly falls back to any
existing cache, else an empty list (the YAML-roster fallback belongs to `run`'s picker only). Full variable reference:
[configuration.md](configuration.md#environment-variables).

---

## 4. Run your first live tournament

```bash
uv run orq-arena run
```

Without `--config`, this opens the roster picker over your workspace-enabled model catalog:

1. **Pick your pool.** The picker fetches your workspace's chat-capable models (cached 24h at
   `~/.cache/orq-arena/models.json`) into a searchable, provider-filterable list. Toggle
   models with `SPACE`, a live HUD line shows the exact call counts as you pick
   (`N matches × R rounds → X streams + Y judge calls`, never a dollar estimate). Pick any pool
   of 2 or more, then press `S` to lock it in (`F` fills to 8 at random, `X` clears, `/`
   searches, `Q` quits).
2. **Preflight probe.** orq-arena automatically sends one tiny call per candidate ("Reply with
   the single word: ok") to catch vendor-default thinking that contradicts your config. If a
   model reasons despite being configured off, you'll see a toast:
   `🧠 thinks despite config: ..., ranking will be footnoted`.
3. **The fight.** Every pair of candidates meets once (round-robin up to 8 candidates; Swiss
   pairing engages automatically above that, never a flag you set). For each prompt, both
   candidates stream side by side, the jury votes in both seat orders, HP drops, and the round
   is logged.
4. **The leaderboard.** Once every match finishes, the final Bradley-Terry ELO leaderboard
   opens with bootstrap 95% CIs. Press `B` to browse every judged round (prompt, both
   responses, per-judge votes with flip badges), `M` to generate per-model coach notes, `S` to
   save a screenshot, `ENTER`/`SPACE`/`Q` to exit.

If your workspace catalog can't be reached, orq-arena degrades in two stages: a plain network
hiccup keeps the picker open but limits it to the models already in your YAML roster (a red
`FALLBACK` badge marks this); an outright failure to fetch anything drops you back to the
title screen with a `catalog load failed: ...` toast, press `ENTER` there to run the YAML
roster directly, picker skipped for that run. See [Troubleshooting](#troubleshooting) below.

---

## 5. Pin a roster, or skip the TUI entirely

Pass `--config` to use a YAML roster as-is and skip the interactive picker, this is also how
you point at the alternate `configs/reasoning_arena.yaml` preset (the uniform thinking-**ON**
counterpart of the default thinking-**OFF** pool), or your own file:

```bash
uv run orq-arena run --config orq_arena.yaml
```

With `--config`, the CLI prints the same call counts up front, runs the same thinking probe,
then asks `Proceed?` before spending anything (`click.confirm(..., abort=True)`), pass
`--yes`/`-y` to skip the prompt for CI or scripts. For the shipped `orq_arena.yaml` (8
candidates) against the default `prompts/starter.jsonl` (30 prompts, capped at `match.max_rounds`
= 5 per match), that preflight line reads exactly:

```
preflight: 28 matches × 5 rounds → 280 model streams + 840 judge calls + 8 probe calls
```

The prompt set is swappable: `--prompts your_prompts.jsonl` for a local file (format:
[Configuration](configuration.md#prompts-file-format)), or `--prompts orq:<dataset_id>` to
fight over an [orq.ai Dataset](https://docs.orq.ai/docs/ai-studio/optimize/datasets) straight
from your workspace, same API key.

With `--config` the run is headless by default: matches run in parallel under
`headless_concurrency` (default 4) through a Rich one-liner printer, and the HTML report
opens in your browser when the run ends (`--no-open` to skip; it never opens in CI). Pass
`--tui` to watch the live Textual show instead. Without `--config` the roster picker opens,
which needs the TUI. Full flag reference for `run` and every other subcommand (`demo`, `rejudge`, `jury-compare`, `report`, `annotate`, `anchor`, `list-models`,
`refresh-models`): **[cli.md](cli.md)**.

---

## Where results land

Every live run, TUI or headless, writes to the same three files, all in the current working
directory by default:

| File | Contents |
|---|---|
| `battles.jsonl` | One JSON line per judged (or voided) round, `BattleRecord`, schema v2: both responses, reconciled per-judge votes, token/TTFT accounting, HP before/after. |
| `battles.run.json` | The run manifest, written next to the log, config/prompt hashes, roster, judge panel, seed, and (once finished) agreement stats. |
| `battles.report.html` | A single-file HTML report, no server, no external assets. The verdict banner leads with the top 3 models (win rate, ELO score, total cost); a value map plots ELO against cost per model on a log scale; a Speed section (tokens per second, time to first token) appears whenever the log carries per-side durations. Runs sourced from an orq.ai Dataset (`--prompts orq:<dataset_id>`) link the dataset by name in the report. |

Pass `--output path/to/file.jsonl` to move all three, the manifest and report page always sit
next to whatever `--output` you choose (`Path(battle_log_path).with_suffix(".run.json")` and
`.with_suffix(".report.html")`). All three files are git-ignored; `orq-arena rejudge` (see
[cli.md](cli.md)) reads `battles.jsonl` straight back off disk to re-score a run with a
different jury, at no regeneration cost, and `orq-arena report <log>` regenerates the report
page on demand.

---

## Troubleshooting

**`RuntimeError: ORQ_API_KEY is not set. Export it before running orq-arena.`**
`.env` is missing, empty, or still the blank template. Run `cp .env.example .env`, fill in a
real key from [my.orq.ai](https://my.orq.ai) > workspace settings > API keys, and re-run. This
only fires on `run` or `rejudge`, `demo`, `list-models`, and `refresh-models` never
construct a gateway client, so they run with no key at all (`refresh-models` just falls back
to cached results, or an empty list).

**`Error: --tui and --headless contradict each other`**
Both flags were passed to `orq-arena run`; drop one. `--headless` is a deprecated no-op
(headless is already the default with `--config`); `--tui` opts into the live show.

**`catalog load failed: ...` toast, then dropped back to the title screen**
The picker's catalog load raised an unexpected error. Note this is rare by design: HTTP
failures, a bad `ORQ_API_KEY`, an unreachable gateway, a flaky network, are swallowed
inside the fetch and degrade to a cached or YAML-only roster, shown as a `FALLBACK` badge in
the picker instead of this toast. Pressing `ENTER` on the title screen still runs the roster
already in `orq_arena.yaml`. `orq-arena refresh-models` reports which source the catalog came
from (live, cache, or fallback, it does not print the underlying HTTP error), and `--config`
skips the picker altogether.

**A response panel shows `✂ truncated`**
The candidate hit its output cap (`gateway.candidate_max_tokens`, default `2048`) before
finishing, judges tend to penalize a cut-off answer. Raise `gateway.candidate_max_tokens` in
your YAML, or set a higher per-candidate `max_tokens` on that one entry. See
[configuration.md](configuration.md#gateway-gatewayconfig).

**A model you expected in the default pool isn't there**
`orq_arena.yaml` deliberately excludes models the router can't disable thinking for, the
shipped file's own comment names `moonshotai/kimi-k2.6`, `deepseek/deepseek-v4-pro`, and
`alibaba/qwen3.5-flash` as excluded for this reason. Mixing an always-thinking model into the
uniform thinking-**OFF** pool would compare reasoning tokens no config could turn off. Add
them to `configs/reasoning_arena.yaml` (the thinking-**ON** preset) instead, or pick them
explicitly in the roster picker if a mixed pool is what you want.

---

## Next steps

| Goal | Where to go |
|---|---|
| See every subcommand and flag | [cli.md](cli.md) |
| Understand every `orq_arena.yaml` key | [configuration.md](configuration.md) |
| See how the toolkit is structured | [architecture.md](architecture.md) |
| Understand the scoring methodology | [methodology.md](methodology.md) |
| Run and write tests | [testing.md](testing.md) |
| Set up a local development environment | [development.md](development.md) |
| Back to the project overview | [README.md](../README.md) |
