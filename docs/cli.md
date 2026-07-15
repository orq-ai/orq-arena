# CLI Reference

`orq-arena` is the single console-script entry point for this project, a `click.group()`
defined in [`src/orq_arena/cli.py`](https://github.com/orq-ai/orq-arena/blob/master/src/orq_arena/cli.py) and registered as
`orq-arena = "orq_arena.cli:cli"` under `[project.scripts]` in
[`pyproject.toml`](https://github.com/orq-ai/orq-arena/blob/master/pyproject.toml). `cli.py` is the sole source of truth for this page;
every flag, default, and behavior documented below is read directly from it (plus
[`rejudge.py`](https://github.com/orq-ai/orq-arena/blob/master/src/orq_arena/rejudge.py) and
[`providers/models_list.py`](https://github.com/orq-ai/orq-arena/blob/master/src/orq_arena/providers/models_list.py) for the two commands
that delegate to them).

It exposes eight subcommands: [`run`](#run), [`demo`](#demo), [`list-models`](#list-models),
[`rejudge`](#rejudge) (including its [`--compare`](#rejudge-compare) mode), [`report`](#report),
[`annotate`](#annotate), [`anchor`](#anchor), and [`refresh-models`](#refresh-models). The `cli` group itself defines
no flags beyond Click's built-in `--help`; there is no `--version` option. Every flag below
lives on a specific subcommand.

```bash
uv run orq-arena --help              # list every subcommand
uv run orq-arena <command> --help    # per-command flag help
```

```text
Usage: orq-arena [OPTIONS] COMMAND [ARGS]...

  orq-arena, LLM arena benchmark: orq.ai router + evaluatorq jury.

Options:
  --help  Show this message and exit.

Commands:
  anchor          Merge human vote files against a recorded run: κ + rank...
  annotate        Render a blinded human-annotation page from a recorded...
  demo            Replay a recorded tournament from a fixture file (no...
  list-models     Print the configured candidate roster.
  refresh-models  Re-fetch the workspace-enabled chat model list from...
  rejudge         Re-judge a recorded run with a different panel, zero...
  report          Render the single-file HTML report page from a recorded...
  run             Run the arena benchmark (hits orq.ai): headless logs by...
```

!!! info "About the output blocks on this page"

    The *Expected output* blocks below are captured from real invocations
    against the committed example run at
    [`examples/quickstart/`](https://github.com/orq-ai/orq-arena/tree/master/examples/quickstart),
    keyless wherever the command makes no API calls. The two blocks that need
    live judge calls (`run`, `rejudge --judge`) are reconstructed from that
    same run's recorded numbers and marked as such. Your model names and
    numbers will differ; the shape won't.

For installation and your first run, see [getting-started.md](getting-started.md). For the
full `orq_arena.yaml` key reference, see [configuration.md](configuration.md).

## At a glance

| Command | Purpose |
|---|---|
| [`run`](#run) | Round-robin benchmark via the orq.ai router: headless by default, HTML report opens at the end, `--tui` for the live show. |
| [`demo`](#demo) | Replay a recorded tournament fixture, zero API calls, zero key. |
| [`list-models`](#list-models) | Print the configured roster (seed, name, model id). |
| [`rejudge`](#rejudge) | Re-score a recorded `battles.jsonl` with a different judge panel, zero regeneration; or, with [`--compare`](#rejudge-compare), tabulate saved rejudge reports side by side. |
| [`report`](#report) | Render the single-file HTML report page from a recorded run; no model calls, one optional catalog read for prices. |
| [`annotate`](#annotate) | Render a blinded human-annotation page from a recorded run; no API calls. |
| [`anchor`](#anchor) | Merge human vote files back against a run: panel↔human κ + rank correlation; no API calls. |
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
  `orq_arena.yaml`) and validates the *entire* file into an `ArenaConfig` (≥2 `candidates`,
  non-empty `judges`, thinking-budget cross-checks, etc.) regardless of which fields a given
  subcommand actually uses. An invalid config file fails the same way for `list-models` or
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
  interleaves with `rejudge`'s Rich tables. `list-models` and `refresh-models` don't touch
  logging config.
- **Which commands need `ORQ_API_KEY`:**

  | Command | Needs a live API key? |
  |---|---|
  | `run` | Yes, model streams, judge calls, and (if enabled) the thinking probe all call the gateway. |
  | `demo` | No, replays a JSON fixture, zero network calls. |
  | `list-models` | No, prints the parsed config only. |
  | `rejudge` | Yes, re-scores recorded responses with a live judge panel. |
  | `refresh-models` | Effectively yes, without it, falls back to any existing cache, then an empty result. See [`refresh-models`](#refresh-models). |

---

## `run`

Run the benchmark (a full round-robin over the pool), hits orq.ai. With
`--config` the run is headless: matches in parallel, plain log lines on pipes, a
progress bar on terminals, and the HTML report opens in your browser at the end.
`--tui` runs the same tournament as the live show instead. Without `--config`
the interactive roster picker opens first, which needs (and implies) the TUI.
Both `--tui` and the picker require the optional `[tui]` extra (`uv sync --extra tui`);
without it they print a friendly install hint. The headless run needs no extra.

```text
orq-arena run [--config PATH] [--prompts PATH] [--output PATH] [--rounds N]
              [--overwrite] [--tui] [--no-open] [--yes|-y]
```

| Flag | Default | Effect |
|---|---|---|
| `--config PATH` | none, triggers the roster picker (see Behavior below) | Use this YAML roster as-is and skip the interactive picker. |
| `--prompts PATH` | `prompts/starter.jsonl` | JSONL prompt file, see [Prompts file format](configuration.md#prompts-file-format), or `orq:<dataset_id>` to pull an [orq.ai Dataset](https://docs.orq.ai/docs/ai-studio/optimize/datasets): each datapoint's last user message becomes a prompt, `{{var}}` placeholders filled from its `inputs`; datapoints without a user message are skipped. Uses the same API key as the gateway. Always honored, whether or not `--config` is given. When the prompts come from a Dataset, the run manifest records its id, display name, and studio URL, and the HTML report links the dataset by name. |
| `--output PATH` | `battles.jsonl` | Where the battle log (schema v3) is written as rounds complete. |
| `--rounds N` | `match.max_rounds` from the YAML | Rounds per match. The preflight warns when this samples a subset of your prompts. |
| `--overwrite` | off | Allow replacing an existing non-empty battle log at `--output`; without it the run refuses rather than erase a recorded run. |
| `--tui` | off | Watch the live TUI show instead of headless logs. Headless runs use `headless_concurrency` (default `4`, see [configuration.md](configuration.md)) to parallelize matches. |
| `--no-open` | off | Do not open the HTML report in a browser when the run ends (it never opens on non-TTY stdout or when `CI` is set). |
| `--headless` | off | Deprecated no-op: headless is already the default with `--config`. |
| `--yes`, `-y` | off | Skip the preflight confirmation pause. |

**Behavior notes:**

- **Picker vs. config-supplied roster.** Without `--config`, `orq_arena.yaml` (or whatever
  `DEFAULT_CONFIG` resolves to) is still loaded first, for `judges`, `match`, and `gateway`,
  but the interactive TUI roster picker opens before anything runs, letting you choose any pool
  of ≥2 models from your workspace-enabled catalog (the same fetch `refresh-models` uses). In
  this path, the preflight (call counts + optional thinking probe) runs **in-app**, after the
  picker closes, right before the fight starts. With `--config`, the YAML's `candidates` list is
  used exactly as written and the picker is skipped entirely; preflight and the confirmation
  prompt happen up front in the terminal, before the TUI (or headless run) even starts.
- **Flag conflicts.** `--tui --headless` raises immediately (a clean `click.ClickException`,
  exit code 1, not a traceback). Without `--config` the picker path always runs the TUI.
- **Preflight output** (config-supplied path only, the picker path renders the same
  information in-app instead of via these `click.echo` lines). First, exact call counts:

  ```text
  preflight: {matches} matches × {rounds_per_match} rounds → {model_streams} model streams + {judge_calls} judge calls[ + {probe_calls} probe calls]
  ```

  computed by `preflight.call_counts`: `matches = C(len(candidates), 2)`,
  `rounds_per_match = min(match.max_rounds, len(prompts))`, `model_streams = matches ×
  rounds × 2`, `judge_calls = matches × rounds × len(judges) × 2`. Next, a spend ceiling:

  ```text
  spend ceiling ≈ ${total} (candidates ${w} + judges ${j}[ + probe ${p}]; every output cap fully hit, live runs land under)
  ```

  computed by `preflight.cost_ceiling` from those exact counts, the config's output caps
  (`candidate_max_tokens` / per-candidate `max_tokens`, `judge_max_tokens`), and per-model prices
  fetched live from the router's Model Garden catalog (`providers.models_list.fetch_price_map`).
  It is an upper bound, the number the run cannot exceed, not a prediction; the judge-input
  term assumes both responses hit the model output cap. Models missing from the catalog are
  excluded and listed on a `⚠ no catalog price for: …` line; if pricing is entirely
  unreachable that warning lists the whole roster and the spend-ceiling line is the one
  skipped (pricing never blocks the run). The ceiling is also recorded in the run
  manifest under `preflight.cost_ceiling`. If `preflight.thinking_probe`
  is enabled (default `true`), a `thinking probe…` line follows, then one line per candidate that
  either failed the probe (`⚠ {name} ({model}): probe failed, {error}`) or thinks despite
  being configured off (`🧠 {name} ({model}): thinks despite config ({reasoning_tokens}
  reasoning tok), ranking will be footnoted`). If no candidate thinks despite being configured
  off, a `pool is thinking-clean ✓` line prints (probe-failure warnings, if any, still appear
  above it).
- **Confirmation.** Unless `--yes`/`-y` is given, the CLI prompts `Proceed?`
  (`click.confirm(..., abort=True)`); declining aborts before any battle or judge calls
  (the thinking probe, when enabled, has already made its one probe stream per model).
- **Output.** Every judged round is appended to `--output` (`battles.jsonl`, schema v3) as the
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

**Expected output** (headless, piped; reconstructed from the committed
[`examples/quickstart`](https://github.com/orq-ai/orq-arena/tree/master/examples/quickstart) run's
recorded manifest and log, its 4-model pool against the default judge trio):

```text
$ uv run orq-arena run --config examples/quickstart/config.yaml -y --no-open \
    --output examples/quickstart/battles.jsonl
preflight: 6 matches × 5 rounds → 60 model streams + 180 judge calls + 4 probe calls
  ⚖ judge/contestant family overlap: anthropic/claude-haiku-4-5-20251001, google/gemini-2.5-flash-lite, openai/gpt-5.4-nano. Self-preference bias is not corrected by seat swapping; prefer judges from families outside the pool.
  spend ceiling ≈ $2.31 (models $1.11 + judges $1.16 + probe $0.04; every output cap fully hit, live runs land under)
thinking probe…
  pool is thinking-clean ✓
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
      FINAL STANDINGS
┏━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━┓
┃ # ┃ Model               ┃ ELO  ┃ 95% CI    ┃ len-ctrl ┃
┡━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━┩
│ 1 │ gemini-3.5-flash    │ 1572 │ 1259–5000 │ 1301     │
│ 2 │ claude-sonnet-4-6   │ 1572 │ 1238–4803 │ 1371     │
│ 3 │ gpt-5.4-mini        │ 489  │ -3000–1810│ 717      │
│ 4 │ mistral-medium-2604 │ 367  │ -3000–1686│ 611      │
└───┴─────────────────────┴──────┴───────────┴──────────┘
mean inter-judge agreement: 95%
style control: jury length coefficient +2.33 (leaned longer); len-ctrl column prices it out
tokens, models 1,728 in / 51,324 out · jury 349,228 in / 23,643 out
battle log → examples/quickstart/battles.jsonl
report page → examples/quickstart/battles.report.html
```

On a terminal (not piped) the per-match lines print above a pinned progress bar
(spinner, rounds M-of-N, elapsed, current leader), and without `-y` the run pauses
at `Proceed? [y/N]` after the preflight, before any battle or judge call.

See [Match rules, gateway, candidates, and judges](configuration.md) for every YAML key this
command reads, and [methodology.md](methodology.md) for how matches are scheduled and scored.

---

## `demo`

Replay a recorded tournament from a fixture file, no API calls, no key required. `demo`
renders through the Textual TUI, so it needs the optional `[tui]` extra (`uv sync --extra tui`);
without it the command prints a friendly install hint instead of a traceback.

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

**From the final leaderboard** (live TUI runs and `demo` alike): `B` opens the battle browser,
paging through every judged round with the prompt, both responses, and per-judge votes with
flip badges; `M` generates per-model coach notes from the analyzer model (cached in
`analysis.jsonl`); `s` saves an SVG screenshot; `q` quits.

![Battle browser: prompt, both responses, per-judge votes with flip badges](assets/battle-browser.svg)

![Post-mortems: per-model strengths, weaknesses, and judge patterns](assets/postmortem.svg)

---

## `list-models`

Print the configured roster, no API calls, no key required.

```text
orq-arena list-models [--config PATH]
```

| Flag | Default | Effect |
|---|---|---|
| `--config PATH` | `orq_arena.yaml` | YAML roster to print. |

**Behavior notes:**

- Prints a fixed-width table, seed number, `name` (falls back to the model's short name,
  see [configuration.md](configuration.md#candidates-the-roster)), and the full `model_id`, in
  roster order, 1-indexed. Format string: `f"{'Seed':<5} {'Name':<26} Model ID"` for the
  header, `f"{i:<5} {w.name:<26} {w.model_id}"` per row.

**Expected output**, against the shipped `orq_arena.yaml` (8 candidates, none with a custom `name`):

```bash
uv run orq-arena list-models
```

```text
Seed  Name                       Model ID
----------------------------------------------------------------------
1     claude-opus-4-8            anthropic/claude-opus-4-8
2     claude-sonnet-4-6          anthropic/claude-sonnet-4-6
3     gpt-5.4                    openai/gpt-5.4
4     gpt-5.4-mini               openai/gpt-5.4-mini
5     gemini-3.1-pro-preview     google/gemini-3.1-pro-preview
6     gemini-3.5-flash           google/gemini-3.5-flash
7     deepseek-chat              deepseek/deepseek-chat
8     mistral-medium-2604        mistral/mistral-medium-2604
```

```bash
uv run orq-arena list-models --config configs/reasoning_arena.yaml
```

---

## `rejudge`

Re-judge a recorded run with a different panel, zero regeneration. The responses in the
battle log are already on disk, so swapping the jury costs judge tokens only. `rejudge` has two
mutually exclusive modes: the default `--judge` mode re-scores a log with a new panel, and
[`--compare`](#rejudge-compare) tabulates saved rejudge reports side by side (no API calls).

```text
orq-arena rejudge [LOG_PATH] --judge MODEL_ID [--judge MODEL_ID ...] [--criteria TEXT]
                  [--config PATH] [--output PATH] [--report-json PATH] [--concurrency N]
orq-arena rejudge --compare REPORT_JSON [--compare REPORT_JSON ...]
```

| Argument / Flag | Default | Effect |
|---|---|---|
| `log_path` (positional) | `battles.jsonl` | Recorded battle log to re-judge (schema v3 JSONL). Optional, omit it to re-judge the default log in the current directory. Ignored in `--compare` mode. |
| `--judge MODEL_ID` | none, **required unless `--compare`, repeatable** | Router model id for the new panel; pass `--judge` multiple times for a multi-judge panel. Mutually exclusive with `--compare`. |
| `--compare REPORT_JSON` | none, **repeatable** | Switches to compare mode: tabulate the given saved rejudge report JSONs side by side (see [`rejudge --compare`](#rejudge-compare)). Mutually exclusive with `--judge`; makes no API calls. |
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

**Expected output** (illustrative; the table shape and labels are exact, the numbers are
from a single-judge rejudge of the committed example run):

```text
$ uv run orq-arena rejudge examples/quickstart/battles.jsonl --judge openai/gpt-5.1

re-judged 30 rounds, 6 verdicts changed
rank correlation (Spearman) old→new: 0.80 , judge-robust ranking
old ranking: gemini-3.5-flash > claude-sonnet-4-6 > gpt-5.4-mini > mistral-medium-2604
new ranking: claude-sonnet-4-6 > gemini-3.5-flash > gpt-5.4-mini > mistral-medium-2604
       new jury behaviour
┏━━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━┓
┃ judge   ┃ A-lean ┃ B-lean ┃ flip rate ┃ tie rate ┃
┡━━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━┩
│ gpt-5.1 │ 48%    │ 52%    │ 10%       │ 13%      │
└─────────┴────────┴────────┴───────────┴──────────┘
```

Below a Spearman of 0.8 the second line reads
`, ranking is panel-sensitive; treat with care` instead, and a
`mean inter-judge agreement: NN%` line follows the table whenever the panel
has more than one judge.

---

## `rejudge --compare`

Compare candidate juries over the same recorded log, a mode of [`rejudge`](#rejudge) selected by
passing `--compare` instead of `--judge`. The selection loop: run once, then for each candidate
panel `rejudge <log> --judge ... --report-json candidate.json` (judge tokens only), then compare
the saved reports with `rejudge --compare`. Makes no API calls.

```text
orq-arena rejudge --compare REPORT_JSON [--compare REPORT_JSON ...]
```

!!! warning "`--compare` is a repeated flag, not a list"

    Pass `--compare` once **per report**: `--compare solo.json --compare panel.json`.
    A bare second path (`--compare solo.json panel.json`) silently binds to the
    `LOG_PATH` positional instead, and the table tabulates only the first report.

Columns per candidate: Spearman vs the recorded ranking (does the ranking depend on this
jury?), inconclusive rate (decisiveness), mean agreement, worst per-judge flip rate
(self-consistency), tie rate, changed verdicts. These measure reliability, not accuracy;
which jury is *right* needs gold pairs or a human anchor (see [`annotate`](#annotate) and [`anchor`](#anchor)).

```bash
uv run orq-arena rejudge battles.jsonl --judge openai/gpt-5.1 --report-json solo.json
uv run orq-arena rejudge battles.jsonl --judge anthropic/claude-haiku-4-5-20251001 \
  --judge openai/gpt-5.1 --report-json panel.json
uv run orq-arena rejudge --compare solo.json --compare panel.json
```

**Expected output** (the report JSONs carry the numbers; the compare step itself makes no API calls):

```text
                                  jury candidates over the same recorded log
┏━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━┓
┃ panel           ┃ spearman vs run ┃ inconclusive ┃ agreement ┃ worst flip      ┃ tie rate ┃ changed        ┃
┃                 ┃                 ┃              ┃           ┃ (judge)         ┃          ┃ verdicts       ┃
┡━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━┩
│ gpt-5.1         │ 0.80            │ 10%          │ n/a       │ 10% (gpt-5.1)   │ 13%      │ 6/30           │
│ claude-haiku-4… │ 1.00            │ 17%          │ 86%       │ 13% (gpt-5.1)   │ 7%       │ 3/30           │
│ gpt-5.1         │                 │              │           │                 │          │                │
└─────────────────┴─────────────────┴──────────────┴───────────┴─────────────────┴──────────┴────────────────┘
read: high spearman = the ranking does not depend on this jury; low inconclusive = decisive; low flip =
self-consistent. These measure reliability, not accuracy; accuracy needs gold pairs or a human anchor.
```

## `report`

Render the single-file HTML report page from a recorded run. Reads `battles.jsonl` and its
`*.run.json` manifest; makes no model calls (one catalog read prices the cost section when a
key is present). The same page is written automatically at the end
of every run (`<log>.report.html` next to the log).

![HTML report page: verdict banner with the top three models, badges, ELO leaderboard with CI bars, and the ELO-vs-cost value map](assets/report-page.png)

```text
orq-arena report [LOG_PATH] [--config PATH] [--output PATH]
```

| Flag / arg | Default | Effect |
|---|---|---|
| `LOG_PATH` (positional) | `battles.jsonl` | The recorded run to render. |
| `--config PATH` | `orq_arena.yaml` | Supplies the judge panel and the model-name mapping for the report's statistics rebuild; match rules are not consulted. |
| `--output PATH` | `<log>.report.html` | Destination HTML file. |

The page is self-contained (inline CSS, no external assets, works from `file://`): verdict
headline with a CI-overlap caveat, the ELO ladder with confidence-interval bars and the
len-ctrl column, the win grid, per-judge behaviour, token and cost accounting (catalog
rates when a key is present: candidate spend exact, jury spend estimated at the panel mean;
one catalog read, never completion spend), and the
manifest hashes for reproducibility.

```bash
uv run orq-arena report outputs/g1/battles.jsonl
uv run orq-arena report battles.jsonl --output /tmp/run.html
```

**Expected output** (one line; without a key the page's cost section is simply omitted,
nothing warns or fails):

```text
$ uv run orq-arena report examples/quickstart/battles.jsonl
report page -> examples/quickstart/battles.report.html
```

## `annotate`

Render a blinded human-annotation page from a recorded run. Reads `battles.jsonl`; makes no
API calls. This is the front half of the human-anchor workflow (the back half is
[`anchor`](#anchor)): the accuracy check that converts "the panel agrees with itself" into
"the panel agrees with people" (see
[Methodology → Human anchor](methodology.md#human-anchor-does-the-panel-agree-with-people)).

```text
orq-arena annotate BATTLE_LOG [--out PATH] [--sample N] [--seed N] [--criteria TEXT]
```

| Flag / arg | Default | Effect |
|---|---|---|
| `BATTLE_LOG` (positional) | required | The recorded run to annotate. |
| `--out PATH` | `annotate.html` | Destination HTML file. |
| `--sample N` | all rounds | Annotate a seeded random subset instead of every round. |
| `--criteria TEXT` | the jury's default rubric | Judging guidelines shown to the rater. |
| `--seed N` | `42` | Drives round order and per-round side flips; keep it if you want two raters on identical pages. |
| `--exclude PATH` | none | votes.json file(s), repeatable: rounds already voted there are dropped, producing a resume page with only the remaining rounds (or a top-up page when growing a study). |
| `--serve` | off | Prodigy-style local mode: serve the page at `http://127.0.0.1:<port>` instead of writing a file. Every vote saves automatically as `votes-<annotator>.json` next to the log (no download step); Ctrl-C stops the server and prints the anchor table for whatever was voted. Localhost-only by construction; for remote raters use the default file mode. |
| `--port N` | `8765` | Port for `--serve`; `0` picks a free one. |

The page is one self-contained HTML file (inline CSS/JS, no external assets, works from
`file://`), so "deployment" is sending someone the file. It is **blind by construction**:
model names, jury votes, and verdicts never enter the payload; rounds are shuffled and the
two responses swap sides per round under the seed; round keys are one-way hashes.

The rater's flow has three views. An **intro** states what the task is, the round count, a
rough time estimate, the criteria to weigh (`--criteria`, defaulting to the jury's default
rubric), the key legend, and asks for their name. The **annotation view** shows one prompt
and two anonymous responses; votes go by `a` (left better), `b` (right better), `t` (tie),
`space` (skip), arrows to navigate; markdown and code fences render properly. After the last
round a **done screen** shows how many rounds were voted vs skipped and holds the explicit
"Download votes.json" button (plus a leave-warning while votes are undownloaded; left arrow
goes back to revisit skips). A persistent header count (voted / skipped / left) and a
clickable per-round dot navigator (voted, tie, skipped, unseen, current) keep position
visible at all times; `n` jumps to the next unvoted round. Exported votes are already
un-flipped to the canonical A/B frame, so the vote file is independent of presentation
order.

```bash
uv run orq-arena annotate outputs/g1/battles.jsonl --sample 60
uv run orq-arena annotate battles.jsonl --out rater2.html --seed 42
# resume: only the rounds dana hasn't voted yet
uv run orq-arena annotate battles.jsonl --exclude votes-dana.json --out dana-round2.html
# annotate your own run locally, votes save as you click, Ctrl-C prints the numbers
uv run orq-arena annotate outputs/g1/battles.jsonl --serve --sample 60
```

**Expected output** (file mode; `--serve` prints the local URL instead and holds until Ctrl-C):

```text
$ uv run orq-arena annotate examples/quickstart/battles.jsonl --out annotate.html --sample 10
10 rounds -> annotate.html (blind; votes export as votes.json)
```

## `anchor`

Merge one or more human vote files back against the recorded run and print the human-anchor
numbers; no API calls.

```text
orq-arena anchor BATTLE_LOG VOTES_JSON [VOTES_JSON ...]
```

| Flag / arg | Default | Effect |
|---|---|---|
| `BATTLE_LOG` (positional) | required | The same log the annotation page was generated from. |
| `VOTES_JSON` (positional, repeatable) | required | Vote files exported by the annotation page, one per rater. |

Output, per annotator: rounds voted, rounds usable for κ (the panel must have been decisive;
inconclusive rounds are excluded from κ but still feed the human Bradley-Terry fit), Cohen's
κ vs the panel majority with its Landis-Koch label, and the Spearman correlation between the
human-vote Bradley-Terry ranking and the panel's. With two or more vote files it also prints
each rater pair's inter-annotator κ over their shared rounds. Votes whose key matches no
round in the log are counted and warned, never crash.

```bash
uv run orq-arena anchor outputs/g1/battles.jsonl votes-h1.json votes-h2.json
```

**Expected output** (two raters over the committed example run):

```text
                         human anchor vs panel
┏━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━━┓
┃ annotator ┃ voted ┃ κ rounds ┃ κ vs panel ┃ label          ┃ rank ρ ┃
┡━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━━┩
│ h1        │ 29    │ 19       │ 0.90       │ almost perfect │ 0.80   │
│ h2        │ 27    │ 19       │ 0.80       │ substantial    │ 0.80   │
└───────────┴───────┴──────────┴────────────┴────────────────┴────────┘
inter-annotator h1 × h2: κ=0.44 (moderate, 26 rounds)
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

**Expected output** (here keyless, so the live fetch is skipped and the cache re-reported;
with a key, `source=live` and `age=0s`):

```text
$ uv run orq-arena refresh-models
137 models (source=cache, age=4528s, cache=/Users/you/.cache/orq-arena/models.json)
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
| [Methodology](methodology.md) | How the ranking is made, bias controls, confidence intervals, reproducibility |
| [README](https://github.com/orq-ai/orq-arena/blob/master/README.md) | Project overview, installation, quick start |
