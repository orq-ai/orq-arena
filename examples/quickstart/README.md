# Quickstart example run

A real, committed orq-arena run so you can inspect the output before spending a
cent of your own: 8 models across five providers, the 30-prompt starter bank,
the cheap default judge trio.

Open **[`battles.report.html`](battles.report.html)** in a browser for the full
page. Regenerate it from the recorded log at any time (no model calls), writing
outside the repository so the committed artifact stays untouched:

```bash
orq-arena report examples/quickstart/battles.jsonl \
  --output /tmp/orq-arena-quickstart.report.html
```

Reproduce the whole run (needs `ORQ_API_KEY`, several minutes). The preflight projects
≈ $11.87 and puts the worst case at ≈ $36.70, the gap being a stand-in judge covering every
judge call, which this config's `replacement_judges` allows:

```bash
orq-arena run --config examples/quickstart/config.yaml \
  --prompts prompts/starter.jsonl -y \
  --output examples/quickstart/battles.jsonl --overwrite
```

`--overwrite` is required here: `battles.jsonl` is committed and non-empty, so without it the
run refuses rather than erase a recorded run. Drop the flag and write somewhere else if you
would rather keep the committed log untouched.

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
- **Length control, and it changes the answer.** The longer answer won 59 of
  74 decisive rounds (80%, length in characters). The modelled length
  coefficient is +18.3 (95% lower bound 13.2), and the report's `length-adj.`
  column refits the rating with that preference priced out, where the raw
  champion drops to 6th: its lead is substantially a length effect. The
  manifest records `length_coef: 3.437`, the value this run computed at the
  time with an estimator that stopped long before converging; manifests are
  historical records, so it stays, and the report page recomputes correctly
  from the log.

## Files

| File | What it is |
|------|-----------|
| `config.yaml` | The 8-model pool + judge panel this run used |
| `battles.jsonl` | One JSONL row per judged round (schema v3; runs recorded now are v4 and also carry each model's full router id): both responses, per-judge votes, token usage, timing |
| `battles.run.json` | Seeded manifest: config/prompt hashes, panel, evaluatorq version, preflight (incl. `family_overlaps`) |
| `battles.report.html` | The self-contained HTML report |
