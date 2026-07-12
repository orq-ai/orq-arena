<!-- generated-by: gsd-doc-writer -->
# CLI Reference

`orq-arena` is the single console-script entry point for this project, a `click.group()`
defined in [`src/orq_arena/cli.py`](../src/orq_arena/cli.py) and registered as
`orq-arena = "orq_arena.cli:cli"` under `[project.scripts]` in
[`pyproject.toml`](../pyproject.toml). `cli.py` is the sole source of truth for this page;
every flag, default, and behavior documented below is read directly from it (plus
[`rejudge.py`](../src/orq_arena/rejudge.py) and
[`providers/models_list.py`](../src/orq_arena/providers/models_list.py) for the two commands
that delegate to them).

It exposes five subcommands: [`run`](#run), [`demo`](#demo), [`list-warriors`](#list-warriors),
[`rejudge`](#rejudge), and [`refresh-models`](#refresh-models). The `cli` group itself defines
no flags beyond Click's built-in `--help`; there is no `--version` option. Every flag below
lives on a specific subcommand.

```bash
uv run orq-arena --help              # list every subcommand
uv run orq-arena <command> --help    # per-command flag help
```

For installation and your first run, see [getting-started.md](getting-started.md). For the
full `orq_arena.yaml` key reference, see [configuration.md](configuration.md).

## At a glance

| Command | Purpose |
|---|---|
| [`run`](#run) | Live round-robin (or Swiss, >8 warriors) tournament against real models via the orq.ai router. |
| [`demo`](#demo) | Replay a recorded tournament fixture, zero API calls, zero key. |
| [`list-warriors`](#list-warriors) | Print the configured roster (seed, orc name, model id). |
| [`rejudge`](#rejudge) | Re-score a recorded `battles.jsonl` with a different judge panel, zero regeneration. |
| [`report`](#report) | Render the single-file HTML report page from a recorded run; no API calls. |
| [`jury-compare`](#jury-compare) | Tabulate candidate juries from saved rejudge reports, side by side; no API calls. |
| [`refresh-models`](#refresh-models) | Force re-fetch of the 24h workspace model-catalog cache. |

---

## Shared behaviors

A few things apply across every subcommand and are only documented once, here:

- **`.env` loading**: every invocation reads `./.env` once, at the top of the `cli` group
  (`_load_dotenv`, called before any subcommand body runs), via a small stdlib-only `KEY=VALUE`
  parser that uses `os.environ.setdefault`, **a variable already set in your shell always wins
  over `.env`.** `ORQ_API_KEY` is the only variable read anywhere in the codebase. Full loader
  behavior (quoting, comments, missing-file handling): [configuration.md](configuration.md#environment-variables).
- **Config validation is all-or-nothing**: `load_config()` parses `--config` (or the default
  `orq_arena.yaml`) and validates the *entire* file into an `ArenaConfig` (≥2 `warriors`,
  non-empty `judges`, thinking-budget cross-checks, etc.) regardless of which fields a given
  subcommand actually uses. An invalid config file fails the same way for `list-warriors` or
  `refresh-models` as it does for `run`, see
  [Required vs Optional Settings](configuration.md#required-vs-optional-settings).
- **Default paths**: four constants in `cli.py` supply every default in the tables below:

  | Constant | Value | Used by |
  |---|---|---|
  | `DEFAULT_CONFIG` | `orq_arena.yaml` | `--config` on every subcommand |
  | `DEFAULT_PROMPTS` | `prompts/starter.jsonl` | `run --prompts` |
  | `DEFAULT_OUTPUT` | `battles.jsonl` | `run --output`, and `rejudge`'s `log_path` positional |
  | `DEFAULT_FIXTURE` | `fixtures/demo_tournament.json` | `demo --fixture` |

  All are relative to the current working directory, not the package install location.
- **Log quieting**: `run`, `demo`, and `rejudge` redirect evaluatorq's `loguru` output to
  stderr at `ERROR` level only (`_quiet_logs()`), so library logging never corrupts the TUI or
  interleaves with `rejudge`'s Rich tables. `list-warriors` and `refresh-models` don't touch
  logging config.
- **Which commands need `ORQ_API_KEY`:**

  | Command | Needs a live API key? |
  |---|---|
  | `run` | Yes, warrior streams, judge calls, and (if enabled) the thinking probe all call the gateway. |
  | `demo` | No, replays a JSON fixture, zero network calls. |
  | `list-warriors` | No, prints the parsed config only. |
  | `rejudge` | Yes, re-scores recorded responses with a live judge panel. |
  | `refresh-models` | Effectively yes, without it, falls back to any existing cache, then an empty result. See [`refresh-models`](#refresh-models). |

---

## `run`

Run the full round-robin (or Swiss, above 8 warriors) arena live, hits orq.ai.

```text
orq-arena run [--config PATH] [--prompts PATH] [--output PATH] [--headless] [--yes|-y]
```

| Flag | Default | Effect |
|---|---|---|
| `--config PATH` | none, triggers the roster picker (see Behavior below) | Use this YAML roster as-is and skip the interactive picker. |
| `--prompts PATH` | `prompts/starter.jsonl` | JSONL prompt file, see [Prompts file format](configuration.md#prompts-file-format), or `orq:<dataset_id>` to pull an [orq.ai Dataset](https://docs.orq.ai/docs/ai-studio/optimize/datasets): each datapoint's last user message becomes a prompt, `{{var}}` placeholders filled from its `inputs`; datapoints without a user message are skipped. Uses the same API key as the gateway. Always honored, whether or not `--config` is given. |
| `--output PATH` | `battles.jsonl` | Where the battle log (schema v2) is written as rounds complete. |
| `--headless` | off | No TUI; matches run in parallel under `headless_concurrency` (default `4`, see [configuration.md](configuration.md)). **Requires `--config`**: there is no picker without a TUI to render it in. |
| `--yes`, `-y` | off | Skip the preflight confirmation pause. |

**Behavior notes:**

- **Picker vs. config-supplied roster.** Without `--config`, `orq_arena.yaml` (or whatever
  `DEFAULT_CONFIG` resolves to) is still loaded first, for `judges`, `match`, and `gateway`,
  but the interactive TUI roster picker opens before anything runs, letting you choose any pool
  of ≥2 models from your workspace-enabled catalog (the same fetch `refresh-models` uses). In
  this path, the preflight (call counts + optional thinking probe) runs **in-app**, after the
  picker closes, right before the fight starts. With `--config`, the YAML's `warriors` list is
  used exactly as written and the picker is skipped entirely; preflight and the confirmation
  prompt happen up front in the terminal, before the TUI (or headless run) even starts.
- **The `--headless` guard.** `--headless` without `--config` raises immediately:
  `--headless needs --config (no picker without a TUI)` (a clean `click.ClickException`, exit
  code 1, not a traceback).
- **Preflight output** (config-supplied path only, the picker path renders the same
  information in-app instead of via these `click.echo` lines). First, exact call counts:

  ```text
  preflight: {matches} matches × {rounds_per_match} rounds → {warrior_streams} warrior streams + {judge_calls} judge calls[ + {probe_calls} probe calls]
  ```

  computed by `preflight.call_counts`: `matches = C(len(warriors), 2)`,
  `rounds_per_match = min(match.max_rounds, len(prompts))`, `warrior_streams = matches ×
  rounds × 2`, `judge_calls = matches × rounds × len(judges) × 2`. If `preflight.thinking_probe`
  is enabled (default `true`), a `thinking probe…` line follows, then one line per warrior that
  either failed the probe (`⚠ {orc_name} ({model}): probe failed, {error}`) or thinks despite
  being configured off (`🧠 {orc_name} ({model}): thinks despite config ({reasoning_tokens}
  reasoning tok), ranking will be footnoted`). If no warrior thinks despite being configured
  off, a `pool is thinking-clean ✓` line prints (probe-failure warnings, if any, still appear
  above it).
- **Confirmation.** Unless `--yes`/`-y` is given, the CLI prompts `Proceed?`
  (`click.confirm(..., abort=True)`); declining aborts the run with no calls made.
- **Output.** Every judged round is appended to `--output` (`battles.jsonl`, schema v2) as the
  run proceeds, live-run or headless alike.

**Examples:**

```bash
# Interactive roster picker over your workspace catalog; judges/rules/gateway from orq_arena.yaml
uv run orq-arena run

# Use the shipped roster as-is, skip the confirmation prompt
uv run orq-arena run --config orq_arena.yaml --yes

# Headless for CI/cron -- no TUI, matches run in parallel (headless_concurrency)
uv run orq-arena run --headless --config orq_arena.yaml --yes

# Custom prompt set and output path, with an alternate roster
uv run orq-arena run --config configs/reasoning_arena.yaml --prompts prompts/starter.jsonl --output reasoning_battles.jsonl
```

See [Match rules, gateway, warriors, and judges](configuration.md) for every YAML key this
command reads, and [architecture.md](architecture.md#data-flow) for how the tournament engine
schedules and scores matches.

---

## `demo`

Replay a recorded tournament from a fixture file, no API calls, no key required.

```text
orq-arena demo [--fixture PATH] [--config PATH]
```

| Flag | Default | Effect |
|---|---|---|
| `--fixture PATH` | `fixtures/demo_tournament.json` | Recorded arena events to replay. |
| `--config PATH` | `orq_arena.yaml` | Used only for its rules/roster labels in the replay, no live calls are made, so `ORQ_API_KEY` is not required. |

**Behavior notes:**

- **Zero-key replay.** Loads a JSON fixture of previously recorded arena events and re-emits
  them through the same TUI (`ArenaApp(..., live=False, fixture=fixture_path)`), so the show
  renders identically to a live run with no network calls and no `ORQ_API_KEY` needed.
- There is no `--prompts` flag on this command, `demo` runs with `prompts=[]`; every prompt
  shown comes from the fixture's recorded events, not from a prompts file.

**Examples:**

```bash
uv run orq-arena demo
uv run orq-arena demo --fixture fixtures/demo_tournament.json --config orq_arena.yaml
```

---

## `list-warriors`

Print the configured roster, no API calls, no key required.

```text
orq-arena list-warriors [--config PATH]
```

| Flag | Default | Effect |
|---|---|---|
| `--config PATH` | `orq_arena.yaml` | YAML roster to print. |

**Behavior notes:**

- Prints a fixed-width table, seed number, `orc_name` (falls back to the model's short name,
  see [configuration.md](configuration.md#warriors-the-roster)), and the full `model_id`, in
  roster order, 1-indexed. Format string: `f"{'Seed':<5} {'Orc name':<26} Model ID"` for the
  header, `f"{i:<5} {w.orc_name:<26} {w.model_id}"` per row.

**Example**, against the shipped `orq_arena.yaml` (8 warriors, none with a custom `orc_name`):

```bash
uv run orq-arena list-warriors
```

```text
Seed  Orc name                   Model ID
----------------------------------------------------------------------
1     claude-opus-4-8             anthropic/claude-opus-4-8
2     claude-sonnet-4-6           anthropic/claude-sonnet-4-6
3     gpt-5.4                     openai/gpt-5.4
4     gpt-5.4-mini                openai/gpt-5.4-mini
5     gemini-3.1-pro-preview      google/gemini-3.1-pro-preview
6     gemini-3.5-flash            google/gemini-3.5-flash
7     deepseek-chat               deepseek/deepseek-chat
8     mistral-medium-2604         mistral/mistral-medium-2604
```

```bash
uv run orq-arena list-warriors --config configs/reasoning_arena.yaml
```

---

## `rejudge`

Re-judge a recorded run with a different panel, zero regeneration. The responses in the
battle log are already on disk, so swapping the jury costs judge tokens only.

```text
orq-arena rejudge [LOG_PATH] --judge MODEL_ID [--judge MODEL_ID ...] [--criteria TEXT]
                  [--config PATH] [--output PATH] [--report-json PATH] [--concurrency N]
```

| Argument / Flag | Default | Effect |
|---|---|---|
| `log_path` (positional) | `battles.jsonl` | Recorded battle log to re-judge (schema v2 JSONL). Optional, omit it to re-judge the default log in the current directory. |
| `--judge MODEL_ID` | none, **required, repeatable** | Router model id for the new panel; pass `--judge` multiple times for a multi-judge panel. Click raises a missing-option error if omitted entirely. |
| `--criteria TEXT` | `cfg.criteria` from `--config` | Override the judging criteria for this rejudge only, doesn't touch the YAML file. |
| `--config PATH` | `orq_arena.yaml` | Supplies `gateway`, and (unless overridden) `criteria`, `replacement_judges`, and `min_successful_judges`. |
| `--output PATH` | none, result only printed | Write the re-judged rounds to this JSONL path. |
| `--report-json PATH` | none, result only printed | Write the run summary as JSON. |
| `--concurrency N` | `4` | Max concurrent judge calls, via `asyncio.Semaphore(concurrency)`. |

**Behavior notes:**

- **Loading.** `load_records(log_path)` parses every line as a `BattleRecord` and keeps only
  rows with no `error` and both `response_a`/`response_b` present, voided or errored rounds
  are silently skipped. If nothing qualifies, the command aborts cleanly with
  `no judgeable rounds in {log_path}` (`click.ClickException`, exit code 1).
- **Self-judge exclusion by short name.** For each contestant pair, any `--judge` whose short
  name (the segment after the last `/`, matching how `model_a`/`model_b` are stored) equals
  either contestant is dropped from that pair's panel, the same rule live matches apply,
  re-evaluated per pair since one rejudge panel is fixed but contestants vary round to round.
  If this empties the panel for a pair, `rejudge_run` raises a plain `ValueError`:
  `every judge is a contestant in {sorted(pair)}`: this is **not** a `ClickException`, so it
  surfaces as a full Python traceback (unlike the clean `Error: ...` message for the
  empty-log case above). Add a neutral model to `--judge` to fix it. `replacement_judges` from
  the config are filtered the same way (dropped to `None` if that empties the list too).
- **Quorum clamp to panel size.** Each pair's jury is built with
  `min_successful_judges=min(cfg.min_successful_judges, len(panel))`: the YAML's quorum
  (sized for the original run's, typically larger, panel) is clamped down per pair so a
  legitimate 1- or 2-judge rejudge panel is never rejected by a quorum meant for a bigger jury.
- One `llm_jury_pairwise` comparator is built and cached per unique contestant pair
  (`frozenset`), not per round, repeated pairs reuse the same comparator instance.
- **Report contents**, printed by `render_result`:
  - `re-judged {N} rounds, {M} verdicts changed` (vs. the recorded `majority_verdict`)
  - Spearman rank correlation between the old and new Bradley-Terry rankings, labeled
    `judge-robust ranking` at `>= 0.8`, otherwise `ranking is panel-sensitive; treat with care`
  - `old ranking: A > B > C ...` and `new ranking: ...` strings
  - a **"new jury behaviour"** table, one row per judge: `A-lean`, `B-lean`, `flip rate`
    (position bias, how often a judge's verdict flips depending on seat order), `tie rate`
  - `mean inter-judge agreement`, if the underlying evaluatorq report provides it
- **`--output`** writes one JSONL row per input record with `judge_votes`, `majority_verdict`,
  and `winner` replaced by the new panel's verdict, every other field (prompt, both
  responses, tokens, timings) is copied through unchanged via `model_copy`.
- **`--report-json`** writes:

  ```json
  {
    "total": 0,
    "changed_verdicts": 0,
    "spearman": 0.0,
    "old_ranking": ["..."],
    "new_ranking": ["..."],
    "jury": { "...": "full evaluatorq report, including per_judge stats" }
  }
  ```

**Examples:**

```bash
# Single-judge rejudge of the default log against the default config
uv run orq-arena rejudge battles.jsonl --judge mistral/mistral-small-2603

# Multi-judge panel
uv run orq-arena rejudge battles.jsonl --judge mistral/mistral-small-2603 --judge anthropic/claude-haiku-4-5-20251001

# Override criteria, write both the rejudged log and a JSON summary
uv run orq-arena rejudge battles.jsonl \
  --judge mistral/mistral-small-2603 \
  --criteria "Correctness only; ignore style." \
  --output battles.rejudged.jsonl \
  --report-json rejudge_report.json

# Higher concurrency against a non-default log
uv run orq-arena rejudge my_battles.jsonl --judge openai/gpt-5.4-nano --concurrency 8
```

---

## `jury-compare`

Compare candidate juries over the same recorded log. The selection loop: run once, then for
each candidate panel `rejudge <log> --judge ... --report-json candidate.json` (judge tokens
only), then compare the saved reports. Makes no API calls.

```text
orq-arena jury-compare REPORT_JSON [REPORT_JSON ...]
```

Columns per candidate: Spearman vs the recorded ranking (does the ranking depend on this
jury?), inconclusive rate (decisiveness), mean agreement, worst per-judge flip rate
(self-consistency), tie rate, changed verdicts. These measure reliability, not accuracy;
which jury is *right* needs gold pairs or a human anchor (planned).

```bash
uv run orq-arena rejudge battles.jsonl --judge openai/gpt-5.1 --report-json solo.json
uv run orq-arena rejudge battles.jsonl --judge anthropic/claude-haiku-4-5-20251001 \
  --judge openai/gpt-5.1 --report-json panel.json
uv run orq-arena jury-compare solo.json panel.json
```

## `report`

Render the single-file HTML report page from a recorded run. Reads `battles.jsonl` and its
`*.run.json` manifest; makes no API calls. The same page is written automatically at the end
of every run (`<log>.report.html` next to the log).

```text
orq-arena report [LOG_PATH] [--config PATH] [--output PATH]
```

| Flag / arg | Default | Effect |
|---|---|---|
| `LOG_PATH` (positional) | `battles.jsonl` | The recorded run to render. |
| `--config PATH` | `orq_arena.yaml` | Supplies judges and rules for the report's statistics rebuild. |
| `--output PATH` | `<log>.report.html` | Destination HTML file. |

The page is self-contained (inline CSS, no external assets, works from `file://`): verdict
headline with a CI-overlap caveat, the ELO ladder with confidence-interval bars and the
len-ctrl column, the win grid, per-judge behaviour, category and token accounting, and the
manifest hashes for reproducibility.

```bash
uv run orq-arena report outputs/g1/battles.jsonl
uv run orq-arena report battles.jsonl --output /tmp/run.html
```

## `refresh-models`

Re-fetch the workspace-enabled chat model list from orq.ai, bypassing the cache.

```text
orq-arena refresh-models [--config PATH] [--show/--no-show]
```

| Flag | Default | Effect |
|---|---|---|
| `--config PATH` | `orq_arena.yaml` | Only `gateway` is used (base URL, API key env var name). |
| `--show` / `--no-show` | `--no-show` (off) | Print every fetched model id, grouped by provider. |

**Behavior notes:**

- Calls `fetch_chat_models(cfg.gateway, force_refresh=True)`, bypassing the 24h TTL cache at
  `~/.cache/orq-arena/models.json` and re-fetching the workspace-enabled, chat-capable catalog
  live (`providers/models_list.py`). This is the same fetch path `run`'s roster picker uses,
  running `refresh-models` first warms the cache the next picker session reads.
- **Endpoint strategy**, in order: `GET {host}/v2/router/models` (the workspace-enabled
  subset, primary source), falling back to `GET {host}/v3/router/models`, then the configured
  `gateway.base_url` + `/models`. Results are narrowed to `type == "chat"` via `GET
  {host}/v2/models` when that endpoint is reachable; non-chat ids (embeddings, TTS/STT, image,
  rerank, moderation, etc.) are always stripped by a regex safety net regardless of whether
  that type lookup succeeds.
- **Without `ORQ_API_KEY`:** the command doesn't error, it skips the live fetch and falls
  back to any existing cache; with no cache either, it prints `0 models (source=fallback, ...)`
  (this command passes no fallback ids of its own).
- Only a **successful** live fetch overwrites the cache file, without a key, or if every
  candidate URL fails, the existing cache (if any) is left untouched and simply re-reported.
- Always prints one summary line:
  `{count} models (source={live|cache|fallback}, age={seconds}s, cache={path})`.
- `--show` additionally prints every model id grouped by provider (providers and ids both
  sorted):

  ```text
  anthropic  (6)
    anthropic/claude-haiku-4-5-20251001
    anthropic/claude-opus-4-8
    ...

  openai  (9)
    openai/gpt-5.4
    openai/gpt-5.4-mini
    ...
  ```

**Examples:**

```bash
uv run orq-arena refresh-models
uv run orq-arena refresh-models --show
uv run orq-arena refresh-models --config configs/reasoning_arena.yaml --show
```

---

## Common workflows

### See it work with zero setup

```bash
uv run orq-arena demo
```

No `ORQ_API_KEY`, no network calls, replays `fixtures/demo_tournament.json` through the real
TUI.

### First live run

```bash
cp .env.example .env   # fill in ORQ_API_KEY
uv run orq-arena run
```

Opens the roster picker over your workspace-enabled catalog; `judges`, `match`, and `gateway`
still come from `orq_arena.yaml`. Confirm the preflight to spend tokens.

### Headless run for CI/cron

```bash
uv run orq-arena run --headless --config orq_arena.yaml --yes
```

No TUI; `--config` is required; `--yes` skips the confirmation prompt, safe for a
non-interactive shell.

### Compare two juries on the same recorded run

```bash
uv run orq-arena rejudge battles.jsonl --judge mistral/mistral-small-2603 --judge anthropic/claude-haiku-4-5-20251001
```

Costs judge tokens only, the responses already in `battles.jsonl` are reused as-is. Prints
the changed-verdict count and the Spearman rank correlation against the original ranking.

### Warm the model-catalog cache before a run

```bash
uv run orq-arena refresh-models --show
```

Forces a live re-fetch (bypassing the 24h cache) so the next `orq-arena run` picker session
opens with fresh data.

---

## See also

| Doc | What it covers |
|---|---|
| [Getting Started](getting-started.md) | Prerequisites, install, first live run, common setup issues |
| [Configuration Reference](configuration.md) | Every `orq_arena.yaml` key, `.env` loading, reasoning recipes, defaults |
| [Architecture](architecture.md) | Component diagram, data flow, key abstractions |
| [Methodology](methodology.md) | Bradley-Terry scoring, bias controls, confidence intervals, reproducibility |
| [README](../README.md) | Project overview, installation, quick start |
