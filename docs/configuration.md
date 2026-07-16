# Configuration Reference

Complete reference for every configuration surface in orq-arena: the one environment variable
it reads, the YAML roster/rules files under the project root and `configs/`, and the prompts
file format. The tool is configured by two layers:

1. A `.env` file holding the single secret orq-arena needs (`ORQ_API_KEY`), loaded at CLI
   startup.
2. A YAML file (`orq_arena.yaml` by default) describing match rules, the gateway client, the
   candidate roster, and the judge panel, parsed and validated into an `ArenaConfig` Pydantic
   model.

The source of truth for every key below is `src/orq_arena/config.py` (models `MatchRules`,
`GatewayConfig`, `PreflightConfig`, `ArenaConfig`) and `src/orq_arena/roster.py`
(`CandidateSpec`). All file paths in this document are relative to the project root.

---

## Environment Variables

Copy the template and fill it in before running anything that calls a real model:

```bash
cp .env.example .env
```

| Variable | Required | Default | Description |
|---|---|---|---|
| `ORQ_API_KEY` | Required for live runs |, | The only secret orq-arena needs. Every candidate, judge, analyzer, and preflight-probe call goes through the orq.ai router gateway with this one key. Read via `os.environ.get(cfg.api_key_env, "")` in `OrqGateway.__init__` (`src/orq_arena/providers/orq_gateway.py`); the gateway raises `RuntimeError("ORQ_API_KEY is not set. Export it before running orq-arena.")` at construction time if it is empty. Get one at [my.orq.ai](https://my.orq.ai) > workspace settings > API keys (per `.env.example`). |

Notes:

- The variable **name** itself is configurable, not hardcoded, it comes from the YAML key
  `gateway.api_key_env` (default `"ORQ_API_KEY"`, see the [`gateway` table](#gateway-gatewayconfig)
  below). Changing `api_key_env` changes which environment variable orq-arena reads; it does not
  set a key.
- `ORQ_API_KEY` is **not** required for `orq-arena demo` (replays a recorded fixture, no API
  calls) or `orq-arena list-models` (prints the roster, never constructs a gateway).

### `.env` loading

Every CLI invocation reads `./.env` once before any subcommand runs. It parses `KEY=VALUE`
lines (skipping blanks and `#` comments, stripping surrounding quotes) and loads them with
`os.environ.setdefault`, so **the real shell environment always wins**; `.env` only fills in
what the shell hasn't set. A missing `.env` is silently fine.

`.env` is git-ignored; `.env.example` is the committed template with `ORQ_API_KEY=` blank.

---

## Config Files

| File | Purpose |
|---|---|
| `orq_arena.yaml` | The default roster + rules, shipped at the project root. Loaded whenever `--config` is omitted or points here, `DEFAULT_CONFIG = "orq_arena.yaml"` in `src/orq_arena/cli.py`. Ships 8 candidates, uniform thinking-**OFF**, so the ELO compares models rather than vendor default reasoning settings. |
| `configs/reasoning_arena.yaml` | Uniform thinking-**ON** counterpart of the default file, the "does thinking help?" benchmark. Not loaded automatically; run it explicitly with `--config configs/reasoning_arena.yaml`. |
| `configs/frontier_8.yaml`, `configs/budget_8.yaml`, `configs/frontier_16.yaml` | Ready-made pools tiered by the Artificial Analysis intelligence index (frontier ~40-56, budget ~12-25, 16-model stress test). See [`configs/README.md`](https://github.com/orq-ai/orq-arena/blob/master/configs/README.md). |

Any YAML path can be passed to `--config`; `load_config()` (`src/orq_arena/config.py`) reads it
with `yaml.safe_load` and validates it into an `ArenaConfig` via
`ArenaConfig.model_validate(raw)`. There is no `${VAR}` environment-variable substitution inside
the YAML, every value is literal.

### Which commands take `--config`

| Command | `--config` behavior |
|---|---|
| `orq-arena run` | Optional. If omitted, `orq_arena.yaml` is still loaded (for `judges`, `match`, `gateway`, etc.) but the interactive roster picker replaces `candidates` at runtime, see the [`candidates`](#candidates-the-roster) section. If given, the YAML roster is used as-is, the picker is skipped, and the run is headless by default (`--tui` opts into the live show). |
| `orq-arena demo` | Defaults to `orq_arena.yaml`. Only used for its rules/roster labels, the fixture replay makes no API calls. |
| `orq-arena list-models` | Defaults to `orq_arena.yaml`. Prints the configured roster. |
| `orq-arena rejudge` | Defaults to `orq_arena.yaml`. Supplies `gateway` and (unless `--criteria` overrides it) `criteria`. |
| `orq-arena refresh-models` | Defaults to `orq_arena.yaml`. Only `gateway` is used, to re-fetch the workspace model catalog. |

---

## `orq_arena.yaml` field reference

A minimal example, drawn from the real shipped file (some `candidates` entries and all-default
sections omitted for brevity, the code default is noted inline where a key isn't set in the
shipped file):

```yaml
match:
  max_rounds: 5
  # starting_hp / damage_unanimous / damage_majority are TUI-presentation-only
  # knobs (the rating never sees them); they take code defaults if omitted.
  starting_hp: 100
  damage_unanimous: 30
  damage_majority: 15

gateway:
  base_url: https://api.orq.ai/v3/router
  api_key_env: ORQ_API_KEY
  candidate_max_tokens: 2048
  judge_max_tokens: 2048
  stream_read_timeout_s: 1200
  judge_timeout_ms: 90000

# preflight and headless_concurrency not set in the shipped
# file - both take their code defaults (see tables below).

candidates:
  - model_id: anthropic/claude-opus-4-8
  - model_id: openai/gpt-5.4
  - model_id: google/gemini-3.1-pro-preview
    reasoning: { thinking: { type: disabled } }
  # ...5 more candidates in the shipped orq_arena.yaml

judges:
  - anthropic/claude-haiku-4-5-20251001
  - google/gemini-2.5-flash-lite
  - openai/gpt-5.4-nano

replacement_judges:
  - mistral/mistral-medium-2604

criteria: >-
  Accuracy and correctness, helpfulness and completeness, clarity, and
  relevance to the prompt.

min_successful_judges: 2
```

### `match` (`MatchRules`)

Only `max_rounds` affects what gets rated. `starting_hp`, `damage_unanimous`, and
`damage_majority` are **TUI-presentation-only** knobs: the engine no longer tracks HP, so they
feed nothing but the live show's health bars. The TUI recomputes HP, damage tiers, and KO
client-side from the judged verdicts (`src/orq_arena/tui/hp.py::HPTracker`); the rating never
sees any of them.

| Key | Type | Default | Effect |
|---|---|---|---|
| `max_rounds` | `int` | `5` | Prompt cap per match. The actual number of rounds run is `min(max_rounds, len(prompts))` (`preflight.call_counts`), a smaller prompts file also shortens matches. **The only match key that affects the rating.** |
| `starting_hp` | `int` | `100` | **TUI-only.** HP each candidate's health bar starts a match with, in the live show (`HPTracker`). Never read by the rating. |
| `damage_unanimous` | `int` | `30` | **TUI-only.** HP the show's bar subtracts when a round's decisive votes agree unanimously. Presentation drama only; the rating is decided by judged round wins, not HP. |
| `damage_majority` | `int` | `15` | **TUI-only.** HP the show's bar subtracts on a decisive but non-unanimous (split) verdict. Presentation drama only. |

Verdict pacing is no longer a config key: the seconds the TUI holds on each verdict before the
next round is a code constant, `VERDICT_HOLD_S` in `src/orq_arena/tui/hp.py` (headless runs never
pause). The match winner is the side with more judged round wins (equal round wins is a draw, an
empty winner), and every prompt in the drawn slice is always judged regardless of where the
on-screen HP bar happens to sit.

### `gateway` (`GatewayConfig`)

| Key | Type | Default | Effect |
|---|---|---|---|
| `base_url` | `str` | `"https://api.orq.ai/v3/router"` | Base URL for the `AsyncOpenAI` client (`OrqGateway.__init__`, `src/orq_arena/providers/orq_gateway.py`). One OpenAI-compatible endpoint fronts every provider, models, judges, the analyzer, and the preflight probe all share it. |
| `api_key_env` | `str` | `"ORQ_API_KEY"` | Name of the environment variable read for the API key. Changing this changes which env var orq-arena looks for; see [Environment Variables](#environment-variables) above. |
| `candidate_max_tokens` | `int` | `2048` | Default per-response output cap for candidate completions (`stream_completion`'s `max_tokens=max_tokens or self._cfg.candidate_max_tokens`). Too low truncates long or creative answers, a cut response is flagged `✂ truncated` in the TUI response panel (`src/orq_arena/tui/widgets/response_panel.py`) and judges tend to penalize it. Overridden per-candidate by `candidates[].max_tokens`. |
| `judge_max_tokens` | `int` | `2048` | Output cap for judge calls, passed to evaluatorq's `llm_jury_pairwise(max_tokens=...)`. A **cap, not a target**: it costs nothing extra on frugal judges. Thinking-by-default judges (e.g. `gemini-2.5-flash`) burn reasoning tokens before writing a verdict; a low cap starves the verdict entirely and fails the vote (the codebase's own regression case: `512` produced a `LengthFinishReasonError` on every one of that judge's votes). `2048` leaves headroom without materially raising cost on the cheap default panel. |
| `stream_read_timeout_s` | `int` | `1200` | Max **silence** between stream chunks, in seconds, before the client treats the connection as dead (`httpx.Timeout(read=float(stream_read_timeout_s), ...)` in `OrqGateway.__init__`). This is a read-gap timeout, not a total-duration cap, a thinking model that pauses for minutes before its first token is fine as long as chunks keep arriving within this gap. A stream that goes silent longer than this is retried once, then the round is voided (logged, shown, excluded from scoring). `1200s` = 20 minutes, deliberately generous. |
| `judge_timeout_ms` | `int` | `90000` | Per-judge-call timeout in milliseconds, passed to evaluatorq's `llm_jury_pairwise(timeout_ms=...)` (`Battle.__init__`, `src/orq_arena/arena/battle.py`). `90000` (90s) is also evaluatorq's own library default for this parameter. |

Not configurable via YAML: `connect=10.0`, `write=60.0`, and `pool=60.0` second timeouts are
hardcoded in `OrqGateway.__init__` alongside `stream_read_timeout_s`, only the read-gap timeout
is exposed as a config key. The preflight probe call (see below) also uses a hardcoded
`max_tokens=1000`, independent of `candidate_max_tokens`/`judge_max_tokens`.

!!! info "Credential/host resolution at defaults"

    When `base_url` and `api_key_env` are left at their defaults, `OrqGateway` delegates
    credential and host resolution to evaluatorq's `resolve_llm_client` (the company-wide
    single source of truth). That path **honors the `ORQ_BASE_URL` environment variable**
    (host plus `/v3/router`, the way to point at a staging host) and **requires an ORQ
    key**, it will not silently fall back to `OPENAI_API_KEY`. Setting either `base_url` or
    `api_key_env` in the YAML is a **bring-your-own-endpoint opt-out**: the run then uses
    the config verbatim with no environment-variable precedence, so `ORQ_BASE_URL` is
    ignored and only the named `api_key_env` variable is read.

#### Bring your own endpoint

The gateway client is a plain `AsyncOpenAI` client: nothing in the tournament engine is
orq.ai-specific. Point `base_url` at any OpenAI-compatible chat endpoint and set `api_key_env`
to whatever variable holds that endpoint's key.
Two features do depend on the orq.ai router and degrade cleanly without it:

- **The roster picker and `refresh-models`** read the workspace model catalog from the router.
  On another endpoint, declare `candidates` in the YAML and run with `--config` so the picker is
  skipped.
- **Reasoning controls** (`candidates[].reasoning`) are forwarded verbatim as `extra_body`; the
  router normalizes them per provider. Other endpoints receive them as-is and may ignore or
  reject unknown fields, so on a non-router endpoint only include fields your server accepts.

The default stays on the router because one key covering every provider is what makes a mixed
pool a one-command run. It is the recommended path, not the only one.

### `preflight` (`PreflightConfig`)

| Key | Type | Default | Effect |
|---|---|---|---|
| `thinking_probe` | `bool` | `True` | Before a live, non-picker run (`orq-arena run --config ...`), sends one tiny probe call (`"Reply with the single word: ok"`) per candidate to detect vendor-default thinking that contradicts its `reasoning` config (`thinking_probe`, `src/orq_arena/preflight.py`). Surfaces as `🧠 … thinks despite config` in the CLI preflight output and footnotes the leaderboard for that candidate. Adds one extra call per candidate (`probe_calls` in `preflight.CallCounts`). Set `false` to skip those extra calls. |

### Top-level run settings (`ArenaConfig`)

| Key | Type | Default | Effect |
|---|---|---|---|
| `headless_concurrency` | `int` | `4` | Matches run in parallel under an `asyncio.Semaphore(max(1, headless_concurrency))`, for `orq-arena run --headless` only (`run_headless` → `run_tournament(concurrency=...)`, `src/orq_arena/headless.py`). The TUI always passes `concurrency=1` internally so the live show stays one fight at a time, this key has no effect on non-headless runs. |

### `candidates` (the roster)

`candidates: list[CandidateSpec]`: required at the top level, and the parsed list must contain at
least 2 entries (`ArenaConfig._validate`: `"Need at least 2 candidates, got {n}"`). Configs from
before the rename keep working: `warriors:` is accepted as a deprecated alias for `candidates:`,
`warrior_max_tokens` for `gateway.candidate_max_tokens`, and `orc_name` for a candidate's `name`. This holds
true even for `orq-arena run` with **no** `--config`: `orq_arena.yaml` is still loaded first (for
`judges`, `match`, `gateway`, etc.) before the interactive picker overwrites `cfg.candidates` at
runtime via `assign_candidates` (`src/orq_arena/tui/app.py`), so the shipped file's `candidates` list must always
validate on its own.

| Key | Type | Default | Effect |
|---|---|---|---|
| `model_id` | `str` |, (required) | orq.ai router gateway model slug, e.g. `anthropic/claude-opus-4-8`. The only required field per candidate entry. |
| `name` | `str` | `""` → falls back to `short_model` | Display name used on the leaderboard, TUI cards, and arena events (`MatchStarted`/`MatchResolved`). Defaults to `model_id` with the provider prefix stripped (`"anthropic/claude-opus-4-8"` → `"claude-opus-4-8"`) and is **never auto-generated beyond that**: a custom name is allowed but not invented (`src/orq_arena/roster.py` docstring: "Display name defaults to the model's short name... A custom `name` is still allowed but never generated."). Note: `battles.jsonl` records (`BattleRecord.model_a`/`model_b`) always store `short_model`, not `name`; `name` is presentation-only. |
| `emblem` | `str` | `""` | Optional glyph/emoji shown before the orc name on the TUI candidate card (`src/orq_arena/tui/widgets/model_card.py`). Purely cosmetic. |
| `reasoning` | `dict \| null` | `None` | Raw router reasoning-control object, forwarded verbatim as `extra_body` on the completion request (`stream_completion`, `src/orq_arena/providers/orq_gateway.py`). Not interpreted beyond the `budget_tokens` cross-check below, the router normalizes it per provider. |
| `max_tokens` | `int \| null` | `None` → falls back to `gateway.candidate_max_tokens` | Per-candidate override of the response output cap. |

**Reasoning passthrough recipes** (forwarded untouched; the router normalizes per provider,
comment block in `orq_arena.yaml`):

```yaml
# OpenAI   -> reasoning: { reasoning_effort: low|medium|high }
# Claude   -> reasoning: { thinking: { type: enabled, budget_tokens: 4096 } }
# Gemini 3 -> reasoning: { thinking: { thinking_level: low|high } }
```

To explicitly disable a think-by-default model (e.g. some Gemini models) for a uniform
thinking-OFF pool:

```yaml
reasoning: { thinking: { type: disabled } }
```

Cross-field validation: if `reasoning.thinking.budget_tokens` is set, it must be strictly less
than the candidate's effective cap (`max_tokens` if set, else `gateway.candidate_max_tokens`), a
config where the thinking budget meets or exceeds the output cap fails to load with
`ValueError: {name}: thinking budget_tokens ({budget}) must be < max_tokens ({cap})`
(`ArenaConfig._validate`, `src/orq_arena/config.py`).

The shipped `orq_arena.yaml` also documents which models it deliberately excludes from the
default pool because the router can't disable their thinking (see the comment below the `candidates` list
in that file), those belong in `configs/reasoning_arena.yaml` instead.

### `judges`, `replacement_judges`, `criteria`, `min_successful_judges`

| Key | Type | Default | Effect |
|---|---|---|---|
| `judges` | `list[str]` |, (required, non-empty) | Router model ids forming the base judge panel handed to evaluatorq's `llm_jury_pairwise(judges=...)`. Must be non-empty, `ArenaConfig._validate` raises `ValueError("Judge panel is empty")` otherwise. Each judge votes on both seat orderings of every round. |
| `replacement_judges` | `list[str]` | `[]` | Neutral stand-ins promoted when a primary judge errors mid-run (`llm_jury_pairwise(replacement_judges=...)`). |
| `criteria` | `str` | `"Accuracy and correctness, helpfulness and completeness, clarity, and relevance to the prompt."` | Free-text criteria string every judge is given, what the jury is asked to judge on. Can be overridden for a single re-judge without editing the YAML via `orq-arena rejudge ... --criteria "..."`. |
| `min_successful_judges` | `int` | `2` | Minimum number of decisive reconciled votes required for a round to produce a real verdict. Fewer than this, and the round is `inconclusive` (dropped from the rating, doesn't count toward `max_rounds`), a guard against a "jury of one" deciding a round. |

**Self-judge exclusion:** per match, any judge whose `model_id` matches either contestant's
`model_id` is filtered out of that match's panel (`panel = [m for m in cfg.judges if m not in
contestants]`, `Battle.__init__`). If that empties the panel entirely, `Battle.__init__` raises
`ValueError("Every judge is a contestant in ..., add a neutral judge to the config.")`: a
small `judges` list can strand a specific pairing if both models in that match are also
configured as judges elsewhere in the roster.

---

## Prompts file format

Prompts are not part of `ArenaConfig`, the file is a separate `--prompts` CLI flag on
`orq-arena run` (default `prompts/starter.jsonl`, `DEFAULT_PROMPTS` in `src/orq_arena/cli.py`). Format: one
JSON object per line (JSONL), parsed by `load_prompts()` into a list of `PromptItem`
(`src/orq_arena/data/prompts.py`).

Instead of a file path, `--prompts orq:<dataset_id>` pulls the datapoints of an
[orq.ai Dataset](https://docs.orq.ai/docs/ai-studio/optimize/datasets) through the orq-python
SDK, authenticated with the same environment variable as the gateway (`gateway.api_key_env`).
Mapping per datapoint: the last `user` message becomes the prompt text, `{{var}}` placeholders
are filled from the datapoint's `inputs`, multi-part content is joined, and datapoints without
a user message are skipped (the count is reported if the dataset yields nothing usable).
Dataset prompts all land in the `general` category; `expected_output` is not read today.

When `--prompts orq:<dataset_id>` is used, the run also captures the dataset's identity:
`orq_dataset_meta()` (`src/orq_arena/data/prompts.py`) returns `{id, name, url}`, an orq.ai
studio link plus a display name fetched via the SDK's `datasets.retrieve` on a best-effort
basis (any failure, offline included, leaves the id standing in as the name, so a run is
never blocked on this call). This lands under a `dataset` key in `battles.run.json`, present
only for dataset-sourced runs, and `battles.report.html` links the dataset by that name.

| Field | Type | Required | Effect |
|---|---|---|---|
| `prompt` | `str` | Required (or `text`, see below) | The prompt text, becomes `PromptItem.text`. |
| `text` | `str` | Fallback for `prompt` | Read only if `prompt` is absent (`row.get("prompt") or row.get("text")`). A row with neither key is silently skipped. |
| `category` | `str` | Optional, default `"general"` | Feeds the per-category ELO slices on the leaderboard. Untagged rows land in `"general"`. |

`PromptItem` itself (`src/orq_arena/data/prompts.py`) is a frozen dataclass with exactly two
fields: `text: str` and `category: str = "general"`.

The shipped `prompts/starter.jsonl` has 30 prompts across four categories: `code` (8), `general`
(11), `math` (6), and `creative` (5). Example row:

```json
{"prompt": "Write a Python function that finds the longest palindromic substring in a given string. Explain your approach.", "category": "code", "length_bucket": "medium"}
```

Note: every row in the shipped file carries a `length_bucket` key (`short`/`medium`), it
is not read by `load_prompts()` today and has no effect on the run.

---

## Required vs Optional Settings

Settings that cause a hard failure (config load or first live call) if absent or invalid:

- `candidates`: required top-level key, must parse to at least 2 `CandidateSpec` entries, and each
  entry requires `model_id`. Missing/short lists fail `ArenaConfig` validation immediately,
  independent of whether the interactive picker will replace the roster afterward.
- `judges`: required top-level key, must be a non-empty list.
- Any `candidates[].reasoning.thinking.budget_tokens` must be strictly less than that candidate's
  effective `max_tokens` (own override or `gateway.candidate_max_tokens`), or config loading fails.
- `ORQ_API_KEY` (or whatever `gateway.api_key_env` names) must be set in the real environment,
  not required to *load* the YAML, but the gateway raises `RuntimeError` the moment any live
  call is attempted (`orq-arena run`, `rejudge`, `refresh-models`). Not needed for `orq-arena
  demo` or `list-models`.
- At least one configured judge must not be a contestant in a given match, or that match raises
  `ValueError` at battle start.

Everything else is a Pydantic default and safe to omit from the YAML entirely:

| Key | Default |
|---|---|
| `match.max_rounds` | `5` |
| `match.starting_hp` (TUI-only) | `100` |
| `match.damage_unanimous` (TUI-only) | `30` |
| `match.damage_majority` (TUI-only) | `15` |
| `gateway.base_url` | `https://api.orq.ai/v3/router` |
| `gateway.api_key_env` | `ORQ_API_KEY` |
| `gateway.candidate_max_tokens` | `2048` |
| `gateway.judge_max_tokens` | `2048` |
| `gateway.stream_read_timeout_s` | `1200` |
| `gateway.judge_timeout_ms` | `90000` |
| `preflight.thinking_probe` | `true` |
| `headless_concurrency` | `4` |
| `replacement_judges` | `[]` |
| `criteria` | `"Accuracy and correctness, helpfulness and completeness, clarity, and relevance to the prompt."` |
| `min_successful_judges` | `2` |
| `candidates[].name` | short model id |
| `candidates[].emblem` | `""` |
| `candidates[].reasoning` | `null` |
| `candidates[].max_tokens` | `null` (→ `gateway.candidate_max_tokens`) |

---

## Alternate configs and overrides

orq-arena is a CLI tool with a single baked-in inference gateway host
(`gateway.base_url`), not a deployed service, there is no dev/staging/production split to
document. The equivalent axes for changing behavior between runs are:

- **Different model pool / benchmark question:** pass a different YAML to `--config`. The two
  shipped presets are `orq_arena.yaml` (uniform thinking-OFF, the default) and
  `configs/reasoning_arena.yaml` (uniform thinking-ON), run the latter with
  `orq-arena run --config configs/reasoning_arena.yaml`. `load_config()` accepts any path.
- **Ad hoc pool without editing YAML:** run `orq-arena run` with no `--config` at all, the
  interactive roster picker opens over your workspace-enabled model catalog and replaces
  `candidates` at runtime; `judges`, `match`, and `gateway` still come from `orq_arena.yaml`.
- **Different jury on an already-recorded run, no regeneration:** `orq-arena rejudge
  <log_path> --judge <id> [--judge <id> ...] [--criteria "..."]` re-scores the responses
  already in `battles.jsonl` with a new panel and/or criteria, without touching the YAML file.
- **Different gateway host:** edit `gateway.base_url` in the YAML, it is a plain string field
  with no environment-variable indirection. No alternate/staging orq.ai host is referenced
  anywhere in this repository; the shipped value is the only one in use.

### Regenerated / git-ignored files

These are run outputs, not configuration, do not hand-edit them as config, and note they are
git-ignored (`.gitignore`):

| File | Written by |
|---|---|
| `.env` | Hand-authored from `.env.example`; never committed. |
| `battles.jsonl` | `orq-arena run`, one row per judged round (`BattleRecord`, schema v3; includes per-model `ttft_a_ms`/`ttft_b_ms` and `duration_a_ms`/`duration_b_ms` timing fields). |
| `battles.run.json` | `orq-arena run`, the run manifest (config + prompt hashes, panel, seed, agreement stats; also a `dataset` key with id, name, and studio URL for dataset-sourced runs). |
