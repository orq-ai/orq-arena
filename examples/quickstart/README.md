# Quickstart example run

A real, committed orq-arena run so you can inspect the output before spending a
cent of your own: 8 models across six providers, the 30-prompt starter bank,
the cheap default judge trio.

Open **[`battles.report.html`](battles.report.html)** in a browser for the full
page. Regenerate it from the recorded log at any time (no model calls):

```bash
uv run orq-arena report examples/quickstart/battles.jsonl
```

Reproduce the whole run (needs `ORQ_API_KEY`, ~$12 ceiling, several minutes):

```bash
uv run orq-arena run --config examples/quickstart/config.yaml \
  --prompts prompts/starter.jsonl -y --no-open \
  --output examples/quickstart/battles.jsonl
```

## What this run shows

- **A real ranking with overlapping CIs.** `gemini-3.5-flash` leads at 1374,
  but `claude-sonnet-4-6` (1196) and `gpt-5.4` (1174) overlap it; at the
  bottom, `gemini-3.1-pro-preview`'s lower bound is unidentifiable (-3000) on
  so few wins. Wide, overlapping intervals are the honest output at 76 rated
  rounds, not a bug. Treat the shipped 30-prompt bank as a smoke test; use
  your own prompts and more rounds for a ranking you intend to defend.
- **Draws are real.** 7 of the 28 matches ended a draw (equal judged round
  wins), which is how the engine resolves a match now: the winner is whoever
  won more judged rounds, HP is a TUI-only show.
- **The consistency gate at work.** 64 of the 140 rounds came back
  inconclusive: a cheap panel abstains on close pairs, and the quorum refuses
  to force a verdict out of a jury that can't agree with itself. The rating is
  built on the 76 rounds that survived.
- **The family-overlap caveat, on the record.** The cheap default judges share
  provider families with the candidates (anthropic/google/openai on both
  sides), so the report carries a `judge/contestant family overlap` badge and
  the manifest records it under `preflight.family_overlaps`. For numbers you
  intend to defend, judge with families outside your pool.
- **Length control.** The jury leaned longer (length coefficient +3.44); the
  len-ctrl column prices that preference out.

## Files

| File | What it is |
|------|-----------|
| `config.yaml` | The 8-model pool + judge panel this run used |
| `battles.jsonl` | One JSONL row per judged round (schema v3): both responses, per-judge votes, token usage, timing |
| `battles.run.json` | Seeded manifest: config/prompt hashes, panel, evaluatorq version, preflight (incl. `family_overlaps`) |
| `battles.report.html` | The self-contained HTML report |
