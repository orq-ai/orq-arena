<!-- generated-by: gsd-doc-writer -->
# Development

Contributor reference for orq-arena: local setup, what `uv sync` actually installs, the module
layout (core benchmark vs. the Textual show), the dev-only commands and scripts, Textual-specific
testing and debugging notes, and the conventions this repo enforces for real.

---

## Local setup

### Prerequisites

- **Python `>=3.10`**: `requires-python` in [`pyproject.toml`](../pyproject.toml). CI installs
  and tests against Python 3.12 on Ubuntu (`uv python install 3.12`,
  [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)).
- **[uv](https://docs.astral.sh/uv/)**: this project's only dependency/environment manager.
  There is no pip/venv/poetry workflow documented or supported here.

Install `uv` if you don't already have it:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Clone and install

```bash
git clone https://github.com/orq-ai/orq-arena.git
cd orq-arena
uv sync
```

`uv sync` installs the runtime dependencies (`textual`, `click`, `pydantic`, `pyyaml`, `openai`,
`httpx`, `evaluatorq`, `[project.dependencies]` in `pyproject.toml`) plus everything in the
**`dev` dependency group** (`[dependency-groups]`, PEP 735 groups, not a `[project.optional-dependencies]`
extra): `pytest>=8`, `pytest-asyncio>=0.23`, `textual-dev>=1.6`. uv includes the `dev` group by
default, so there's no separate `--extra`/`--group` flag to remember for local setup. Installing
also registers the **`orq-arena`** console script (`[project.scripts]` → `orq_arena.cli:cli`),
which is the entry point used throughout this guide.

CI installs the same way with `uv sync --frozen`, which fails instead of silently updating
`uv.lock` if it's out of date.

For the fork/clone/verify walkthrough (including the zero-cost sanity checks), see
["Development setup" in CONTRIBUTING.md](../CONTRIBUTING.md#development-setup), the notes above
just expand on what `uv sync` pulls in.

### Configure credentials

Only needed for commands that call the real orq.ai gateway (`run`, `rejudge`,
`refresh-models`: not `demo` or `list-warriors`):

```bash
cp .env.example .env
# then fill in ORQ_API_KEY
```

See [docs/configuration.md](configuration.md) for exactly how `.env` is loaded (a small
stdlib-only parser in `cli.py`, never overrides an already-set shell variable) and the full
variable reference.

---

## Module layout

`src/orq_arena/` splits into a benchmark **core** and one **presentation layer**, connected by a
single one-way event queue. Core packages import zero `textual` today:

| Layer | Packages | Role |
|---|---|---|
| Core | `cli.py`, `config.py`, `events.py`, `preflight.py`, `rejudge.py`, `headless.py`, `orcs/`, `providers/`, `tournament/`, `arena/`, `data/`, `analysis/` | Schedules matches, streams both sides, invokes the evaluatorq jury, scores damage, computes ELO/CIs/κ, the benchmark itself. |
| Presentation | `tui/` (`app.py`, `screens/`, `widgets/`) | The only package that imports `textual`. Renders the CRT-neon show; a pure consumer. |

The seam between them is [`events.py`](../src/orq_arena/events.py)`::ArenaEvent`, a pydantic
`Union` pushed onto an `asyncio.Queue[ArenaEvent]`. The tournament engine
(`tournament/driver.py`, `arena/battle.py`) is the **sole producer**;
[`tui/app.py`](../src/orq_arena/tui/app.py)`::ArenaApp` and
[`headless.py`](../src/orq_arena/headless.py)`::run_headless` are two interchangeable
**consumers** draining that same queue. Both only render, **neither can push anything back into
the engine or influence a verdict**. Keep that direction intact when touching either side: a
screen or widget should never reach into `tournament/`, `arena/`, or a judge call directly.

This map is intentionally short. For the full directory tree with rationale, the component
diagram, and the data-flow walkthrough, see [docs/architecture.md](architecture.md); for the
equally short authoritative version contributors are expected to internalize, see
["Project shape" in CONTRIBUTING.md](../CONTRIBUTING.md#project-shape), this section expands on
both rather than replacing either.

---

## Running the app from source

There is no build step, `uv run` executes straight from `src/` via the `orq-arena` console
script `uv sync` registers. The table below is the day-to-day dev loop; the full flag reference
for every command lives in [docs/cli.md](cli.md).

| Command | What it does | Hits orq.ai? |
|---|---|---|
| `uv run orq-arena demo` | Replays `fixtures/demo_tournament.json` through the TUI | No, no network, no key |
| `uv run orq-arena list-warriors` | Prints the roster from `orq_arena.yaml` (or `--config`) | No |
| `uv run orq-arena run` | Opens the roster picker over your live model catalog, then runs live in the TUI | Yes |
| `uv run orq-arena run --config orq_arena.yaml` | Runs that YAML's roster as-is, TUI, no picker | Yes |
| `uv run orq-arena run --config orq_arena.yaml --headless --yes` | Same live run, no TUI, matches run in parallel, no confirmation pause, the closest thing to a CI smoke run | Yes |
| `uv run orq-arena rejudge battles.jsonl --judge mistral/mistral-small-2603` | Re-scores an existing log with a new panel; prints the Spearman rank-stability | Yes, judge calls only |
| `uv run orq-arena refresh-models` | Bypasses the 24h model-catalog cache and re-fetches it | Yes |

Note that `run` still shows the preflight confirmation prompt even with `--headless` unless you
also pass `--yes`, pair both flags for a non-interactive invocation. For local iteration with no
API key and no cost, `demo` and `list-warriors` are the two commands safe to run repeatedly;
everything else needs `ORQ_API_KEY` in `.env` and spends real tokens.

---

## The dev-only fixture recorder (`scripts/record_fixture.py`)

`fixtures/demo_tournament.json`: the file `orq-arena demo` replays, isn't hand-written; it's a
real recorded event stream from a tiny live tournament.
[`scripts/record_fixture.py`](../scripts/record_fixture.py) regenerates it:

```bash
uv run python scripts/record_fixture.py
```

Per its own header, this is dev-only, not product surface: run it when the `ArenaEvent` schema or
vocabulary changes, "roughly once a quarter." It needs `ORQ_API_KEY` and costs a few cents: it
runs a real 3-warrior / 3-judge / 2-round tournament (`openai/gpt-5.4-mini`,
`google/gemini-2.5-flash` with thinking disabled, and `mistral/mistral-medium-2604`, judged by the
same panel `orq_arena.yaml` ships) through the real `run_tournament` engine, drains every event,
tags each with a `_delay` for replay pacing (fast for text/thinking chunks, a readable 0.35s pause
for everything else), and writes the result to `fixtures/demo_tournament.json`. It also leaves a
small real battle log at `outputs/smoke/fixture_battles.jsonl` as a side effect.

---

## Textual devtools (`textual-dev`)

The `dev` dependency group installs [`textual-dev`](https://github.com/Textualize/textual-dev),
which provides the `textual` CLI. The TUI takes over the whole terminal while it runs, so ordinary
`print()`/logging output is invisible, `textual console` opens a second terminal that receives it
instead:

```bash
# terminal 1 - the devtools console
uv run textual console

# terminal 2 - run the app in dev mode (connects to the console above)
uv run textual run --dev "orq-arena demo"
```

`ArenaApp` ([`src/orq_arena/tui/app.py`](../src/orq_arena/tui/app.py)) takes required constructor
arguments (`cfg`, `prompts`, `battle_log_path`) that only `cli.py` assembles, so point
`textual run --dev` at the `orq-arena` command itself, as above, rather than trying to import
`ArenaApp` directly.

---

## Testing during development

A short summary for iterating locally; the full reference lives in [docs/testing.md](testing.md).

- **Framework:** `pytest` with `pytest-asyncio` in `asyncio_mode = "auto"` (`pyproject.toml`
  `[tool.pytest.ini_options]`), so `async def test_*` functions run with no decorator needed.
  `testpaths = ["tests"]`, `pythonpath = ["src"]`.
- **No markers, no network:** this repo has no `integration`/`unit` marker split, the whole
  suite runs offline, no API key required.
- **Run everything:** `uv run pytest` (or `uv run pytest -q`, the exact invocation
  [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs).
- **Run one file:** `uv run pytest tests/test_battle_rounds.py -v`.
- **No coverage gate:** `pytest-cov` isn't a dependency and CI passes no coverage flags, there's
  no threshold to hit.

### Headless TUI tests (`app.run_test()`)

Textual screens are tested without a real terminal, using Textual's own pilot: instantiate a bare
`App` host, push the screen under test, drive it through
`async with app.run_test(size=(...)) as pilot:`, then assert on screen state.
[`tests/test_browser_render.py`](../tests/test_browser_render.py) is the clearest example, it
builds a `BattleBrowserScreen` from real (or synthetic, if no fixture log is on disk)
`BattleRecord`s, pushes it onto a throwaway `App`, and asserts `screen._idx` advances on
`action_next()`. The same pattern covers the fight and leaderboard screens
([`tests/test_fight_render.py`](../tests/test_fight_render.py),
[`tests/test_leaderboard_render.py`](../tests/test_leaderboard_render.py)) and the roster picker
([`tests/test_roster_picker.py`](../tests/test_roster_picker.py)).

> **Textual pitfall, never name a widget method `_render`.** Textual's own `Widget`/`Static`
> machinery uses that name internally; shadowing it with a method of your own has crashed this app
> twice (`REFACTOR_PLAN.md`'s fix log: "Textual 8.x `_render` shadowing (×2, second caught by the
> render test)"). `tests/test_browser_render.py` exists specifically to catch this class of
> regression, when you add a widget with custom render logic, give it a headless `run_test()`
> pilot test rather than trusting it visually.

---

## Conventions

- **Code style:** there is no linter or formatter configured in this repo, no ruff, no
  pre-commit, no Makefile. The only automated gate is the test suite
  (`uv run pytest -q` in CI). Match what's already there: `from __future__ import annotations` at
  the top of most modules, `@dataclass` for lightweight internal data (`preflight.py`,
  `arena/battle.py`, `arena/damage.py`, `tournament/swiss.py`, `providers/models_list.py`,
  `data/prompts.py`), pydantic `BaseModel` for anything validated at a boundary, config, events,
  schemas, roster (`config.py`, `events.py`, `data/schemas.py`, `orcs/roster.py`,
  `analysis/postmortem.py`), and `async`/`await` through the tournament/battle/gateway path.
- **Signed commits are required** by the repo's branch ruleset. See
  ["Making changes" in CONTRIBUTING.md](../CONTRIBUTING.md#making-changes) for the signing setup
  link.
- **Methodology invariants need a plan-level discussion first.** Judging, rating, or void-policy
  changes touch the numbers the README calls defensible. See
  ["Design invariants worth knowing" in docs/architecture.md](architecture.md#design-invariants-worth-knowing)
  for what's currently load-bearing (round-robin/Swiss sizing, the jury quorum, unanimous-vs-majority
  damage, the read-gap-only timeout, the one-way event queue) before changing any of it,
  ["Making changes" in CONTRIBUTING.md](../CONTRIBUTING.md#making-changes) is the process pointer.
- **No secrets in the repo.** `.env` is gitignored; `.env.example` is the committed template. See
  ["Never commit secrets" in CONTRIBUTING.md](../CONTRIBUTING.md#never-commit-secrets).

---

## Branching & pull requests

- The default branch is **`master`**. CI
  ([`.github/workflows/ci.yml`](../.github/workflows/ci.yml)) runs on pushes to `master`,
  `feat/**`, `fix/**`, and on every pull request.
- Branch off `master`; the `feat/...` / `fix/...` naming used in history is the recommended (not
  enforced) convention.
- Before opening a PR, run the same check CI runs:

  ```bash
  uv run pytest -q
  ```

- Open the PR with [the template](../.github/PULL_REQUEST_TEMPLATE.md), its checklist covers
  tests passing, doc updates for user-facing changes, and no committed secrets.
- Commits must be signed (see Conventions above).

The full contributor process, code of conduct, project shape, how to report a bug, lives in
[CONTRIBUTING.md](../CONTRIBUTING.md).

---

## Cross-references

- [docs/architecture.md](architecture.md), component diagram, data flow, key abstractions, design invariants
- [docs/configuration.md](configuration.md), environment variables, `orq_arena.yaml` field reference
- [docs/testing.md](testing.md), full testing reference
- [docs/getting-started.md](getting-started.md), prerequisites and first run
- [docs/cli.md](cli.md), every command and flag
- [CONTRIBUTING.md](../CONTRIBUTING.md), code of conduct, project shape, PR checklist, issue reporting
