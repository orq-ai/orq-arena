<!-- generated-by: gsd-doc-writer -->
# Testing

Test suite reference for orq-arena — how to run it, what each of the 11 test files covers, the
headless Textual rendering pattern used for TUI screens, and how to add a new test.

> **Audience:** contributors extending or reviewing the codebase. For environment setup before
> you get here, see [CONTRIBUTING.md](../CONTRIBUTING.md); for the pipeline the tests exercise,
> see [docs/architecture.md](architecture.md).

## Framework and Setup

Tests are written with [pytest](https://docs.pytest.org/) and [`pytest-asyncio`](https://pytest-asyncio.readthedocs.io/)
for async support. Both are pinned in the `dev` dependency group in `pyproject.toml`
(`pytest>=8`, `pytest-asyncio>=0.23`), installed automatically by `uv sync`. The same group also
carries `textual-dev>=1.6`, which is unrelated to running the suite — it's the interactive
TUI debugging tool (`textual console`, live CSS reload), not a test dependency.

The pytest configuration lives in `pyproject.toml` under `[tool.pytest.ini_options]`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
pythonpath = ["src"]
```

Key settings:

- **`testpaths = ["tests"]`** — a bare `pytest` (or `uv run pytest`) invocation collects only from
  the `tests/` directory.
- **`asyncio_mode = "auto"`** — any `async def test_...` runs without a `@pytest.mark.asyncio`
  decorator; pytest-asyncio picks it up automatically.
- **`pythonpath = ["src"]`** — `src/` is put on `sys.path` for the test session, so tests import
  the package directly at its real name — `from orq_arena.arena.damage import compute_damage`,
  `from orq_arena.tournament.elo import bradley_terry_mle`, etc. — not `from src.orq_arena...`.
  This works straight out of a fresh `uv sync`, with no separate editable-install step required
  for collection to succeed.

Two things this suite deliberately does **not** have, worth knowing up front so you don't go
looking for them:

- **No `conftest.py`.** There is no shared fixtures file anywhere in the repo. Each test file
  builds its own small private helpers instead (functions prefixed `_`, e.g. `_cfg()`, `_vote()`,
  `_w()`, `_rec()`, `_records()` — see the [Test Map](#test-map) below).
- **No registered markers.** `pyproject.toml` defines no `markers` list, and no test in the suite
  carries a `@pytest.mark.*` decorator. Every test in the repository runs against fakes or pure
  functions — there is no `integration`/`live`/`slow` split to opt in or out of.

## Running Tests

### Full suite

```bash
uv run pytest
```

Collects from `tests/` and runs all **41 tests across 11 files**. None of them touch the network
or need an API key, and the whole run finishes in well under a second (0.86s measured locally;
`uv run pytest --collect-only -q` alone takes about half that).

### Verbose output

```bash
uv run pytest -v
```

### Run a single file

```bash
uv run pytest tests/test_damage.py
```

### Run a single test

```bash
uv run pytest tests/test_damage.py::test_tie_deals_no_damage_and_no_cap_tick
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

This is the exact command CI runs — see [CI Integration](#ci-integration).

## Test Map

| File | Tests | What it covers |
|---|---|---|
| `tests/test_damage.py` | 6 | The damage adapter (`arena/damage.py::compute_damage`) — evaluatorq's `PairwiseComparison` → HP damage. Unanimous vs. majority damage tiers, the guard that a single surviving decisive vote (after two abstentions) can never trigger the "unanimous" tier, a tie vote breaking unanimity, and zero damage / no round-cap tick on `tie` or `inconclusive`. |
| `tests/test_battle_rounds.py` | 5 | `arena/battle.py::Battle.run()` round semantics, driven by an in-file `FakeGateway` (streams canned text, or raises for models in a `failing` set) and `FakeJury` (returns a canned `PairwiseComparison`, or asserts it's never called). Covers: a stream failure voiding the round without ever invoking the jury, the happy path (judged, damage applied, events emitted), `Battle.__init__` raising when every judge is also a contestant, KO not stopping the judging loop (all drawn prompts are still judged even after HP hits 0), and equal final HP resolving as a draw. |
| `tests/test_elo.py` | 5 | Bradley-Terry MLE (`tournament/elo.py`) — a clean sweep ranks the winner highest, identical win/loss records yield equal ratings, a tie splits rating movement evenly, ties shift ratings symmetrically relative to a shared opponent, and the bootstrap confidence interval brackets the point estimate with a real (non-zero-width) range. |
| `tests/test_scheduler.py` | 4 | The round-robin scheduler and per-round outcome feed (`tournament/driver.py`) — every pair meets exactly once for 8 warriors (`C(8,2) = 28` matches, no self-pairs), the schedule is stable for a fixed seed, `outcomes_from_records` keeps wins/ties and skips `inconclusive`/voided rounds, and `elo_by_category` only emits a category once it has reached the 20-comparison floor. |
| `tests/test_swiss.py` | 4 | `tournament/swiss.py::SwissScheduler` — the first round pairs everyone, round 2 avoids rematches and pairs round-1 winners against each other, an odd-sized pool floats exactly one competitor, and a recorded tie splits score credit 0.5/0.5. |
| `tests/test_kappa.py` | 4 | Chance-corrected inter-judge agreement (`analysis/kappa.py`) — perfect agreement yields `kappa == 1.0` with the `"almost perfect"` label, rounds with an abstaining judge are excluded from the Fleiss' calculation (`rounds_used` < `rounds_total`), pairwise Cohen's kappa is computed over co-voted rounds only, and `landis_koch()`'s label boundaries (e.g. `0.15` → `"slight"`, `0.75` → `"substantial"`). |
| `tests/test_config.py` | 5 | The YAML config loader (`config.py::load_config`) — the shipped `orq_arena.yaml` parses to 8 warriors and 3 judges with the documented defaults (`starting_hp=100`, `max_rounds=5`, gateway base URL), `short_model` strips the provider prefix (`"anthropic/claude-opus-4-8"` → `"claude-opus-4-8"`), `configs/reasoning_arena.yaml` loads with a uniform thinking-ON pool, the default `orq_arena.yaml` pool is uniform thinking-OFF, and a `reasoning.thinking.budget_tokens` that doesn't fit under `max_tokens` fails validation. |
| `tests/test_roster_picker.py` | 4 | Model-catalog picker plumbing — `providers/models_list.py::_parse_payload` strips non-chat models and de-duplicates by id, `_filter_by_type` keeps chat models plus anything of unknown type, `orcs/roster.py::assign_warriors` preserves already-configured `WarriorSpec`s (including their `reasoning` block) and names newly picked models after their bare model id. The fourth test is a Textual pilot (see below) that mounts `tui/screens/roster_select.py::RosterSelectScreen` and checks the live selection-count line. |
| `tests/test_fight_render.py` | 1 | Headless render pilot for `tui/screens/fight.py::FightScreen` — see [Headless Textual Render Tests](#headless-textual-render-tests). |
| `tests/test_leaderboard_render.py` | 2 | Headless render pilots for `tui/screens/leaderboard.py::LeaderboardScreen`, with and without a report payload. |
| `tests/test_browser_render.py` | 1 | Headless render pilot for `tui/screens/battle_browser.py::BattleBrowserScreen`. |

There is no shared `conftest.py` row because none exists — see [Framework and Setup](#framework-and-setup).

## Headless Textual Render Tests

Four of the eleven files mount a real Textual screen inside a headless terminal and drive it
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
> render time — which no logic test could catch.

In plain terms: a widget in `src/orq_arena/tui/widgets/judge_card.py` once defined something that
collided with Textual's own internal `Widget._render`. Nothing about that collision was visible
to a test that only called the widget's business-logic methods directly — the class still
behaved correctly in isolation. It only surfaced once Textual actually tried to render the
mounted widget tree, which is exactly what `app.run_test()` forces to happen and a plain
function-level unit test never does. That's the standing justification for keeping a real render
pilot per screen rather than trusting logic-level tests alone.

The three files dedicated entirely to this pattern:

- **`tests/test_fight_render.py`** — drives `FightScreen` through a full match lifecycle in one
  test: starting a match, live standings, streaming thinking/response text, per-side completion
  with token/finish-reason metadata, four judge verdicts (`A`, `abstain`+flipped, `tie`, and an
  unrecognized judge id falling back to a status line), applying damage, then a KO, a voided
  round, and a draw resolution banner — finishing by confirming that stale verdicts from the
  previous round stay visible but dimmed (`has_class("stale")`) until a new verdict for that
  judge arrives.
- **`tests/test_leaderboard_render.py`** — mounts `LeaderboardScreen` twice: once with a full
  report payload loaded from `fixtures/demo_tournament.json` (asserting the main standings table,
  the jury table, and the win-grid table all mount with the right row counts), and once with only
  bare `elo`/`champion`/`log_path` data (asserting the jury table is absent entirely rather than
  empty).
- **`tests/test_browser_render.py`** — mounts `BattleBrowserScreen` and pages through it with
  `screen.action_next()`. Its record source is worth describing precisely: the module-level
  `_records()` helper checks whether `outputs/smoke/pr5.jsonl` exists (relative to the repo
  root) and, if so, parses every non-blank line into a real `BattleRecord` via
  `BattleRecord.model_validate_json`. `outputs/smoke/` is git-ignored (see `.gitignore`), so that
  file is a locally regenerated smoke-test artifact — present if you've run a smoke test on your
  machine, absent on a fresh clone or in CI. When it's absent, `_records()` falls back to a single
  hand-built synthetic `BattleRecord` (schema v2, one judge vote) so the test still has something
  shaped correctly to page through. Either way the test only asserts on paging behavior
  (`screen._idx` advancing modulo the record count), so it passes identically down both paths.

`tests/test_roster_picker.py` also contains one test using this same `_Host` + `run_test()` pilot
pattern (`test_picker_mounts_and_counts_update`, mounting `RosterSelectScreen`) alongside its
three plain logic-level tests — it isn't counted among the "three render pilots" above because
rendering is incidental to that file's main purpose (catalog parsing and warrior assignment), not
its reason for existing.

## Coverage

No coverage tooling is installed — `pytest-cov` is not in the `dev` dependency group — and CI
enforces no coverage threshold. The only gate, locally and in CI, is that all 41 tests pass.

## CI Integration

Tests run on GitHub Actions via [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)
(workflow name `CI`, job name `Unit tests`). It triggers on push to `master`, `feat/**`, or
`fix/**` branches, and on every pull request.

| Step | Runs |
|---|---|
| Checkout | `actions/checkout@v4` |
| Install uv | `astral-sh/setup-uv@v4` (`version: latest`) |
| Install Python | `uv python install 3.12` |
| Install dependencies | `uv sync --frozen` — installs the exact versions pinned in `uv.lock`, including the `dev` group (`pytest`, `pytest-asyncio`, `textual-dev`) |
| Run tests | `uv run pytest -q` |

It's a single job on `ubuntu-latest` with a single Python version — no OS/version matrix, no
separate lint step, and no coverage gate. `uv run pytest -q` locally reproduces the CI check
exactly.

## Adding a New Test

1. **File and naming.** Create or extend `tests/test_<topic>.py`. Test functions are plain
   `def test_...():` (or `async def test_...():`) at module scope — the suite does not use
   `unittest.TestCase` or a `class Test<Topic>:` grouping convention. The only classes that do
   appear in test files are tiny non-test helpers, like the `class _Host(App): pass` used by the
   render pilots.
2. **No shared fixtures file.** There is no `conftest.py` to import from. Build small private
   helpers local to your file instead, prefixed with `_` — mirror `_cfg()` in
   `tests/test_battle_rounds.py` or `_vote()`/`_cmp()` in `tests/test_damage.py`.
3. **Async tests need no decorator.** `asyncio_mode = "auto"` means `async def test_...():` is
   picked up automatically — do not add `@pytest.mark.asyncio`.
4. **Never touch the network.** Nothing in this suite constructs a real `OrqGateway` or calls
   `evaluatorq.llm_jury_pairwise` for real. When the code under test would call out, substitute a
   small `Fake*` class and inject it with `monkeypatch.setattr(...)`, following
   `tests/test_battle_rounds.py`'s `FakeGateway`/`FakeJury` (and its
   `monkeypatch.setattr(battle_mod, "llm_jury_pairwise", lambda **kw: jury)`).
5. **New TUI widget or screen?** Add a render pilot using the recipe from
   [Headless Textual Render Tests](#headless-textual-render-tests) — a bare `_Host(App)`,
   `async with app.run_test(...) as pilot:`, `await app.push_screen(screen)`,
   `await pilot.pause()`, then assert on real mounted widget state (`has_class(...)`,
   `query_one(...)`, `.row_count`). Logic-only tests cannot catch a rendering-time failure — that
   is the entire reason this pattern exists (see above).
6. **Verify before pushing.** `uv run pytest -q` should pass with no network access; use
   `uv run pytest --collect-only -q` first if you just want to confirm a new test is discovered.

A minimal example combining a plain logic test and the render-pilot recipe:

```python
from textual.app import App

from orq_arena.arena.damage import compute_damage
from orq_arena.config import MatchRules
from orq_arena.tui.screens.fight import FightScreen


def _rules() -> MatchRules:
    return MatchRules()


def test_something_about_damage():
    rules = _rules()
    # ...build a PairwiseComparison, call compute_damage(comparison=..., rules=rules)...


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
