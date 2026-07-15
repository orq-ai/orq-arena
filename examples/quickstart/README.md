# Quickstart example run

A real, committed orq-arena run so you can inspect the output before spending a
cent of your own. Small on purpose: 4 models, thinking-OFF, the 30-prompt
starter bank, the cheap default judge trio.

Open **[`battles.report.html`](battles.report.html)** in a browser for the full
page. Regenerate it from the recorded log at any time (no model calls):

```bash
uv run orq-arena report examples/quickstart/battles.jsonl
```

Reproduce the whole run (needs `ORQ_API_KEY`, ~$2 ceiling, a couple of minutes):

```bash
uv run orq-arena run --config examples/quickstart/config.yaml \
  --prompts prompts/starter.jsonl -y --no-open \
  --output examples/quickstart/battles.jsonl
```

## What this run shows

- **A real ranking with overlapping CIs.** `gemini-3.5-flash` and
  `claude-sonnet-4-6` finished tied at the top; `gpt-5.4-mini` and
  `mistral-medium-2604` trailed. On 6 matches the 95% confidence intervals are
  wide and overlap, which is the honest output at this sample size, not a bug.
  Treat the shipped 30-prompt bank as a smoke test; use your own prompts and
  more rounds for a ranking you intend to defend.
- **Draws are real.** Match M1 ended a draw (equal judged round wins), which is
  how the engine resolves a match now: the winner is whoever won more judged
  rounds, HP is a TUI-only show.
- **The family-overlap caveat, on the record.** The cheap default judges share
  provider families with the candidates (anthropic/google/openai on both
  sides), so the report carries a `judge/contestant family overlap` badge and
  the manifest records it under `preflight.family_overlaps`. For numbers you
  intend to defend, judge with families outside your pool.
- **Length control.** The jury leaned longer (length coefficient reported in the
  report); the len-ctrl column prices that preference out.

## Files

| File | What it is |
|------|-----------|
| `config.yaml` | The 4-model roster + judge panel this run used |
| `battles.jsonl` | One JSONL row per judged round (schema v3): both responses, per-judge votes, token usage, timing |
| `battles.run.json` | Seeded manifest: config/prompt hashes, panel, evaluatorq version, preflight (incl. `family_overlaps`) |
| `battles.report.html` | The self-contained HTML report |
