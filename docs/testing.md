# Testing

Test suite reference for orq-arena, how to run it, what each of the 24 test files covers, the
headless Textual rendering pattern used for TUI screens, and how to add a new test.

## Framework and Setup

Tests are written with [pytest](https://docs.pytest.org/) and [`pytest-asyncio`](https://pytest-asyncio.readthedocs.io/)
for async support. Both are pinned in the `dev` dependency group in `pyproject.toml`
(`pytest>=8`, `pytest-asyncio>=0.23`), installed automatically by `uv sync`. The same group also
carries `textual-dev>=1.6`, which is unrelated to running the suite, it's the interactive
TUI debugging tool (`textual console`, live CSS reload), not a test dependency.

The pytest configuration lives in `pyproject.toml` under `[tool.pytest.ini_options]`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
pythonpath = ["src"]
```

Key settings:

- **`testpaths = ["tests"]`**: a bare `pytest` (or `uv run pytest`) invocation collects only from
  the `tests/` directory.
- **`asyncio_mode = "auto"`**: any `async def test_...` runs without a `@pytest.mark.asyncio`
  decorator; pytest-asyncio picks it up automatically.
- **`pythonpath = ["src"]`**: `src/` is put on `sys.path` for the test session, so tests import
  the package directly at its real name, `from orq_arena.tui.hp import HPTracker`,
  `from orq_arena.tournament.elo import bradley_terry_mle`, etc., not `from src.orq_arena...`.
  This works straight out of a fresh `uv sync`, with no separate editable-install step required
  for collection to succeed.

Two things this suite deliberately does **not** have, worth knowing up front so you don't go
looking for them:

- **No `conftest.py`.** There is no shared fixtures file anywhere in the repo. Each test file
  builds its own small private helpers instead (functions prefixed `_`, e.g. `_cfg()`, `_vote()`,
  `_w()`, `_rec()`, `_records()`, see the [Test Map](#test-map) below).
- **No registered markers.** `pyproject.toml` defines no `markers` list, and no test in the suite
  carries a `@pytest.mark.*` decorator. Every test in the repository runs against fakes or pure
  functions, there is no `integration`/`live`/`slow` split to opt in or out of.

## Running Tests

### Full suite

```bash
uv run pytest
```

Collects from `tests/` and runs all **111 tests across 24 files**. None of them touch the network
or need an API key, and the whole run finishes in a few seconds (about 2.6s measured locally;
`uv run pytest --collect-only -q` alone takes about 0.4s).

### Verbose output

```bash
uv run pytest -v
```

### Run a single file

```bash
uv run pytest tests/test_hp_tracker.py
```

### Run a single test

```bash
uv run pytest tests/test_elo.py::test_clean_sweep_ranks_winner_highest
```

### Filter by name substring

```bash
uv run pytest -k kappa
```

Matches on module, class, and function name, so `-k kappa` selects all 4 tests in
`tests/test_kappa.py` without needing the full path.

### Collect without running

```bash
uv run pytest --collect-only -q
```

Useful as a quick sanity check that a newly added test file is actually being discovered.

### CI-equivalent quiet run

```bash
uv run pytest -q
```

This is the exact command CI runs, see [CI Integration](#ci-integration).

## Test Map

| File | Tests | What it covers |
|---|---|---|
| `tests/test_hp_tracker.py` | 8 | The TUI-side HP model (`tui/hp.py::HPTracker`), derived purely from judged verdicts for the live show (the rating never sees it). Unanimous vs. majority damage tiers, the guard that a single surviving decisive vote (after two abstentions) can never trigger the "unanimous" tier, a tie vote breaking unanimity, and zero damage / no round-cap tick on `tie` or `inconclusive`. |
| `tests/test_battle_rounds.py` | 5 | `arena/battle.py::Battle.run()` round semantics, driven by an in-file `FakeGateway` (streams canned text, or raises for models in a `failing` set) and `FakeJury` (returns a canned `PairwiseComparison`, or asserts it's never called). Covers: a stream failure voiding the round without ever invoking the jury, the happy path (judged, recorded, events emitted), `Battle.__init__` raising when every judge is also a contestant, the judging loop drawing every capped prompt, and the match winner being decided by more judged round wins (equal round wins resolves as a draw). |
| `tests/test_driver.py` | 4 | `tournament/driver.py::run_tournament` orchestration with a faked `Battle`/gateway (no network): the round-robin schedule, per-match ELO recompute, standings/end events, the `<output>.run.json` manifest round-trip, and seed-stable determinism under concurrency. |
| `tests/test_elo.py` | 9 | Bradley-Terry MLE (`tournament/elo.py`), a clean sweep ranks the winner highest, identical win/loss records yield equal ratings, a tie splits rating movement evenly, ties shift ratings symmetrically relative to a shared opponent, and the bootstrap confidence interval brackets the point estimate with a real (non-zero-width) range. Style control (`style_controlled_elo`): pure-length wins shrink the rating gap and expose a positive length coefficient, equal-length rows leave gamma at zero with the raw ranking intact, empty input yields a flat 1000 field. Plus `preflight.py::judge_family_overlaps` flagging a judge that shares a provider family with a candidate. |
| `tests/test_scheduler.py` | 5 | The round-robin scheduler and per-round outcome feed (`tournament/driver.py`), every pair meets exactly once for 8 candidates (`C(8,2) = 28` matches, no self-pairs), the schedule is stable for a fixed seed, `outcomes_from_records` keeps wins/ties and skips `inconclusive`/voided rounds, and `elo_by_category` only emits a category once it has reached the 20-comparison floor. |
| `tests/test_gateway_resolution.py` | 5 | Gateway credential/host resolution (`providers/orq_gateway.py`): at default config, delegation to evaluatorq's `resolve_llm_client` (honoring `ORQ_BASE_URL`, requiring an ORQ key, no silent `OPENAI_API_KEY` fallback); and the bring-your-own-endpoint opt-out when `base_url`/`api_key_env` are set, which uses the config verbatim with no env precedence. |
| `tests/test_cli_tui_optional.py` | 3 | The core CLI runs without the `[tui]` extra: with `textual` made unimportable, `demo`, the roster picker (no-`--config` `run`), and `--tui` print a friendly install hint instead of a traceback, while the headless/report/rejudge paths still work. |
| `tests/test_fixture_replay.py` | 2 | The shipped `fixtures/demo_tournament.json` still parses under the current event models (`_replay_fixture` swallows parse errors, so a narrowed field would make demo rounds vanish silently): every event parses, and the old HP/`by` fields it still carries are ignored, not rejected. |
| `tests/test_kappa.py` | 4 | Chance-corrected inter-judge agreement (`analysis/kappa.py`), perfect agreement yields `kappa == 1.0` with the `"almost perfect"` label, rounds with an abstaining judge are excluded from the Fleiss' calculation (`rounds_used` < `rounds_total`), pairwise Cohen's kappa is computed over co-voted rounds only, and `landis_koch()`'s label boundaries (e.g. `0.15` → `"slight"`, `0.75` → `"substantial"`). |
| `tests/test_config.py` | 5 | The YAML config loader (`config.py::load_config`), the shipped `orq_arena.yaml` parses to 8 candidates and 3 judges with the documented defaults (`starting_hp=100`, `max_rounds=5`, gateway base URL), `short_model` strips the provider prefix (`"anthropic/claude-opus-4-8"` → `"claude-opus-4-8"`), `configs/reasoning_arena.yaml` loads with a uniform thinking-ON pool, the default `orq_arena.yaml` pool is uniform thinking-OFF, and a `reasoning.thinking.budget_tokens` that doesn't fit under `max_tokens` fails validation. |
| `tests/test_roster_picker.py` | 4 | Model-catalog picker plumbing, `providers/models_list.py::_parse_payload` strips non-chat models and de-duplicates by id, `_filter_by_type` keeps chat models plus anything of unknown type, `roster.py::assign_candidates` preserves already-configured `CandidateSpec`s (including their `reasoning` block) and names newly picked models after their bare model id. The fourth test is a Textual pilot (see below) that mounts `tui/screens/roster_select.py::RosterSelectScreen` and checks the live selection-count line. |
| `tests/test_fight_render.py` | 1 | Headless render pilot for `tui/screens/fight.py::FightScreen`, see [Headless Textual Render Tests](#headless-textual-render-tests). |
| `tests/test_leaderboard_render.py` | 2 | Headless render pilots for `tui/screens/leaderboard.py::LeaderboardScreen`, with and without a report payload. |
| `tests/test_browser_render.py` | 1 | Headless render pilot for `tui/screens/battle_browser.py::BattleBrowserScreen`. |
| `tests/test_prompts.py` | 5 | Prompt loaders (`data/prompts.py`), JSONL rows parse with `prompt`/`text` fallback and category default, an orq.ai datapoint maps its last user message with `{{var}}` substitution from `inputs`, datapoints without a user turn are skipped, multi-part content joins its text parts, and the `orq:` scheme fails fast when the API key env var is missing. |
| `tests/test_report.py` | 7 | The HTML report page (`report.py`), every section renders from a recorded run, `report_path_for` follows the `<log>.report.html` convention, an est. cost column appears only when a price map is supplied and a dataset line appears only when the manifest carries orq.ai dataset metadata (with a real link to it), a speed section renders tok/s and TTFT from per-round durations and is skipped entirely on legacy logs that predate duration capture, and `data/prompts.py::orq_dataset_meta` falls back to a synthesized id-as-name entry when the orq.ai SDK call fails offline. |
| `tests/test_rejudge_compare.py` | 1 | `rejudge.py` comparison table rows from a recorded run. |
| `tests/test_anchor_items.py` | 5 | Blinded annotation items (`anchor.py`), one-way round keys, seeded shuffle, no model names leak. |
| `tests/test_anchor_page.py` | 5 | The blinded annotation page renders self-contained with no verdict/name strings. |
| `tests/test_anchor_math.py` | 8 | Human-vs-panel Cohen's κ and BT rank correlation from merged vote files. |
| `tests/test_anchor_cli.py` | 3 | `annotate`/`anchor` command wiring and guards. |
| `tests/test_anchor_serve.py` | 4 | `annotate --serve` localhost mode, votes POST to /save. |
| `tests/test_headless_display.py` | 2 | The headless printer, plain lines on pipes and the progress bar on terminals. |
| `tests/test_preflight_cost.py` | 4 | Preflight spend-ceiling estimate. |

There is no shared `conftest.py` row because none exists, see [Framework and Setup](#framework-and-setup).

## Headless Textual Render Tests

Four of the 24 files mount a real Textual screen inside a headless terminal and drive it
with Textual's own test harness, rather than only calling into the screen's methods and checking
returned Python values. The pattern is the same in each:

```python
from textual.app import App
from orq_arena.tui.screens.fight import FightScreen  # or leaderboard / battle_browser / roster_select

class _Host(App):
    pass

async def test_my_screen():
    screen = FightScreen(...)
    app = _Host()
    async with app.run_test(size=(120, 40)) as pilot:
        await app.push_screen(screen)
        await pilot.pause()
        # ...drive the screen through method calls that mimic real events...
        await pilot.pause()
        assert screen._card_b.has_class("ko")   # assert on real mounted widget state
```

`_Host(App)` is a bare Textual `App` subclass that exists only to give the screen somewhere to
mount. `app.run_test(size=(w, h))` boots that app in a headless, size-controlled terminal and
hands back a `pilot` you can drive; `await pilot.pause()` lets pending messages and layout settle
before the next assertion. `size=` is only needed for the wider screens (fight/browser use
`(120, 40)` or `(130, 44)`); the leaderboard tests omit it and take Textual's default.

**Why this pattern exists.** The module docstring in `tests/test_fight_render.py` states the
reason directly:

> Exists because JudgeCard once shadowed Textual's internal Widget._render and only exploded at
> render time, which no logic test could catch.

In plain terms: a widget in `src/orq_arena/tui/widgets/judge_card.py` once defined something that
collided with Textual's own internal `Widget._render`. Nothing about that collision was visible
to a test that only called the widget's business-logic methods directly, the class still
behaved correctly in isolation. It only surfaced once Textual actually tried to render the
mounted widget tree, which is exactly what `app.run_test()` forces to happen and a plain
function-level unit test never does. That's the standing justification for keeping a real render
pilot per screen rather than trusting logic-level tests alone.

The three files dedicated entirely to this pattern:

- **`tests/test_fight_render.py`**: drives `FightScreen` through a full match lifecycle in one
  test: starting a match, live standings, streaming thinking/response text, per-side completion
  with token/finish-reason metadata, four judge verdicts (`A`, `abstain`+flipped, `tie`, and an
  unrecognized judge id falling back to a status line), applying damage, then a KO, a voided
  round, and a draw resolution banner, finishing by confirming that stale verdicts from the
  previous round stay visible but dimmed (`has_class("stale")`) until a new verdict for that
  judge arrives.
- **`tests/test_leaderboard_render.py`**: mounts `LeaderboardScreen` twice: once with a full
  report payload loaded from `fixtures/demo_tournament.json` (asserting the main standings table,
  the jury table, and the win-grid table all mount with the right row counts), and once with only
  bare `elo`/`champion`/`log_path` data (asserting the jury table is absent entirely rather than
  empty).
- **`tests/test_browser_render.py`**: mounts `BattleBrowserScreen` and pages through it with
  `screen.action_next()`. Its record source is worth describing precisely: the module-level
  `_records()` helper checks whether `outputs/smoke/pr5.jsonl` exists (relative to the repo
  root) and, if so, parses every non-blank line into a real `BattleRecord` via
  `BattleRecord.model_validate_json`. `outputs/smoke/` is git-ignored (see `.gitignore`), so that
  file is a locally regenerated smoke-test artifact, present if you've run a smoke test on your
  machine, absent on a fresh clone or in CI. When it's absent, `_records()` falls back to a single
  hand-built synthetic `BattleRecord` (schema v3, one judge vote) so the test still has something
  shaped correctly to page through. Either way the test only asserts on paging behavior
  (`screen._idx` advancing modulo the record count), so it passes identically down both paths.

`tests/test_roster_picker.py` also contains one test using this same `_Host` + `run_test()` pilot
pattern (`test_picker_mounts_and_counts_update`, mounting `RosterSelectScreen`) alongside its
three plain logic-level tests, it isn't counted among the "three render pilots" above because
rendering is incidental to that file's main purpose (catalog parsing and candidate assignment), not
its reason for existing.

## Coverage

No coverage tooling is installed, `pytest-cov` is not in the `dev` dependency group, and CI
enforces no coverage threshold. The only gate, locally and in CI, is that all 111 tests pass.

## CI Integration

Tests run on GitHub Actions via [`.github/workflows/ci.yml`](https://github.com/orq-ai/orq-arena/blob/master/.github/workflows/ci.yml)
(workflow name `CI`, job name `Unit tests`). It triggers on push to `master`, `feat/**`, or
`fix/**` branches, and on every pull request.

| Step | Runs |
|---|---|
| Checkout | `actions/checkout@v4` |
| Install uv | `astral-sh/setup-uv@v4` (`version: latest`) |
| Install Python | `uv python install 3.12` |
| Install dependencies | `uv sync --frozen`, installs the exact versions pinned in `uv.lock`, including the `dev` group (`pytest`, `pytest-asyncio`, `textual-dev`) |
| Run tests | `uv run pytest -q` |

It's a single job on `ubuntu-latest` with a single Python version, no OS/version matrix, no
separate lint step, and no coverage gate. `uv run pytest -q` locally reproduces the CI check
exactly.

## Adding a New Test

1. **File and naming.** Create or extend `tests/test_<topic>.py`. Test functions are plain
   `def test_...():` (or `async def test_...():`) at module scope, the suite does not use
   `unittest.TestCase` or a `class Test<Topic>:` grouping convention. The only classes that do
   appear in test files are tiny non-test helpers, like the `class _Host(App): pass` used by the
   render pilots.
2. **No shared fixtures file.** There is no `conftest.py` to import from. Build small private
   helpers local to your file instead, prefixed with `_`, mirror `_cfg()` in
   `tests/test_battle_rounds.py` or `_tracker()`/`_resolve()` in `tests/test_hp_tracker.py`.
3. **Async tests need no decorator.** `asyncio_mode = "auto"` means `async def test_...():` is
   picked up automatically, do not add `@pytest.mark.asyncio`.
4. **Never touch the network.** Nothing in this suite constructs a real `OrqGateway` or calls
   `evaluatorq.llm_jury_pairwise` for real. When the code under test would call out, substitute a
   small `Fake*` class and inject it with `monkeypatch.setattr(...)`, following
   `tests/test_battle_rounds.py`'s `FakeGateway`/`FakeJury` (and its
   `monkeypatch.setattr(battle_mod, "llm_jury_pairwise", lambda **kw: jury)`).
5. **New TUI widget or screen?** Add a render pilot using the recipe from
   [Headless Textual Render Tests](#headless-textual-render-tests), a bare `_Host(App)`,
   `async with app.run_test(...) as pilot:`, `await app.push_screen(screen)`,
   `await pilot.pause()`, then assert on real mounted widget state (`has_class(...)`,
   `query_one(...)`, `.row_count`). Logic-only tests cannot catch a rendering-time failure, that
   is the entire reason this pattern exists (see above).
6. **Verify before pushing.** `uv run pytest -q` should pass with no network access; use
   `uv run pytest --collect-only -q` first if you just want to confirm a new test is discovered.

A minimal example combining a plain logic test and the render-pilot recipe:

```python
from textual.app import App

from orq_arena.tui.hp import HPTracker
from orq_arena.tui.screens.fight import FightScreen

def _tracker() -> HPTracker:
    return HPTracker(starting_hp=100, damage_unanimous=30, damage_majority=15)

def test_something_about_hp():
    tracker = _tracker()
    tracker.start_match()
    # ...feed judged verdicts, assert on the resulting HP bars / KO...

class _Host(App):
    pass

async def test_my_new_screen_mounts():
    screen = FightScreen(["haiku", "flash-lite"])
    app = _Host()
    async with app.run_test(size=(120, 40)) as pilot:
        await app.push_screen(screen)
        await pilot.pause()
        assert screen.is_mounted
```
