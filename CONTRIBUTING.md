# Contributing

Thanks for helping improve orq-arena. Bug reports, feature ideas, documentation fixes, and
pull requests are all welcome.

## Code of conduct

Be respectful and constructive. This should be a welcoming project for contributors of every
background. Harassment, demeaning comments, and personal attacks are not tolerated.

## Development setup

The project uses [uv](https://docs.astral.sh/uv/) for environment and dependency management:

```bash
# 1. Fork the repo on GitHub, then clone your fork
git clone https://github.com/<your-username>/orq-arena.git
cd orq-arena

# 2. Install (runtime + dev dependencies; the TUI extra is needed for the render tests)
uv sync --extra tui

# 3. Verify
uv run pytest            # full suite, no network
uv run orq-arena demo    # replay a recorded tournament, no API key
```

Live runs need an orq.ai API key: `cp .env.example .env` and fill in `ORQ_API_KEY`
(`.env` is gitignored and loaded automatically).

### Never commit secrets

API keys live in `.env`, which is gitignored. Use [`.env.example`](.env.example) as the
template. If you add a new credential, wire it through an environment variable and extend
`.env.example`: never hardcode it.

## Project shape

- `src/orq_arena/`: the benchmark core. `tournament/` (scheduling, Bradley-Terry + CIs),
  `arena/` (one battle: stream → judge → record), `providers/` (orq router client,
  model catalog), `analysis/` (κ, post-mortems), `data/` (schema-v3 records), `rejudge.py`,
  `anchor.py` (human annotation), `report.py` (the HTML report).
- `src/orq_arena/tui/`: the Textual show, behind the optional `[tui]` extra. Strictly a
  consumer of the event stream; nothing in here may affect a verdict (HP/damage is computed
  here, from the judged verdicts, for display only).
- `tests/`: plain pytest, async via `pytest-asyncio`, no network. TUI screens are tested
  headlessly with Textual's `run_test()` pilot.

## Making changes

1. Create a topic branch off `master` (`feat/...` or `fix/...`, CI runs on both).
2. Keep the diff small and the vocabulary local: match the surrounding code's style; the
   methodology invariants in the README ("How the number is made") are load-bearing;
   changes to judging, rating, or void policy need a plan-level discussion first.
3. Add or update a test when behaviour changes. Textual widgets get a headless render test
   (that pattern has caught real bugs twice).
4. Run `uv run pytest` before pushing.
5. Open a PR using the template. Note: the repo requires **signed commits**
   ([GitHub docs](https://docs.github.com/en/authentication/managing-commit-signature-verification/signing-commits)).

## Reporting bugs

Open a GitHub issue with: what you ran, what you expected, what happened, and, if a live run
is involved, the `*.run.json` manifest of the run (it contains no secrets: hashes, model ids,
panel, and agreement stats).
