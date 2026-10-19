# Meetup talk: orq-arena for AI builders

A 25 minute talk with a live demo. `talk.html` is the whole deck: open it from disk in a
browser, no network needed. Arrow keys or space move between slides, `0` to `9` jump to a
chapter, `s` shows the say lines, `?` lists the keys. `python3 check.py` checks the deck
offline before the talk.

| File | What it is |
|---|---|
| `talk.html` | the deck, with four toys: round robin, Bradley-Terry, the judge panel, decision judges |
| `check.py` | offline check: no em-dash, no network reference, slide order, toy math under node |
| `audience_prompts.py` | form export (CSV) plus `seed.jsonl` to one prompts JSONL |
| `seed.jsonl` | 10 rows from `prompts/starter.jsonl`, so the run starts with or without submissions |
| `demo.yaml` | the live run's config: `configs/budget_8.yaml` with its decision-model panel |
| `fallback/` | the rehearsal run: `battles.jsonl`, `battles.run.json`, `battles.report.html`; the TUI recording still to add |
| `qr.svg`, `qr-repo.svg` | form QR (placeholder) and repo QR |

## Still to fill in

- **Form URL.** `qr.svg` is a placeholder. Once the form exists:
  `uvx segno --scale 10 --border 2 --dark "#f2ecff" --light "#060310" --output=talks/2026-meetup/qr.svg "<form url>"`.
  The form asks for one field whose name contains "prompt"; nothing else is needed.
- **LMArena raise.** The hook slide carries `<!-- VERIFY raise figure before talk -->`.
- **evaluatorq 1.74.** The agents slide says evaluatorq 1.74 renders tool calls for the judge
  (verified on 1.74.0, `common/messages.py`). Master pins `>=1.55.1`; check the bump has merged.
- **TUI recording.** `fallback/demo.cast` is not recorded yet; see "Record the fallback" below.

## Rehearsal, 2026-10-19

Headless, `demo.yaml` as shipped (all 8 models), `seed.jsonl` (10 prompts):

| Wall time | Rounds rated | Cost |
|---|---|---|
| 12 min 0 s | 117 of 140 (0 voided) | about $0.97: models $0.86, jury $0.08, thinking probe $0.03 |

Under the 15 minute budget, so the pool stays at 8. The preflight projects $2.99 (worst case
$5.60) because it assumes every answer hits its token cap; the real run cost a third of that.
Each match samples 5 prompts (`max_rounds`), so the run is 28 pairs x 5 = 140 rounds however
many prompts the audience adds; the live run should take about as long.

## Record the fallback

One more paid run (about $1), in a real terminal, so the cast and the saved report match:

```bash
export ORQ_API_KEY=$(sed 's/^ORQ_API_KEY=//' ~/.orq/api-key)
uv tool install asciinema   # once
asciinema rec talks/2026-meetup/fallback/demo.cast -c ".venv/bin/orq-arena run \
  --config talks/2026-meetup/demo.yaml --prompts talks/2026-meetup/seed.jsonl \
  --output talks/2026-meetup/fallback/battles.jsonl --overwrite --tui --yes"
```

The run rewrites `battles.jsonl`, `battles.run.json` and `battles.report.html` next to the
cast. Commit the cast only if it is under 2 MB; otherwise keep it local and say where here.
If you re-record, swap the `#ring` slide's record for one from the new `battles.jsonl`.

## Runbook

### The day before

1. Key: `export ORQ_API_KEY=$(sed 's/^ORQ_API_KEY=//' ~/.orq/api-key)`, then
   `orq-arena run --config talks/2026-meetup/demo.yaml --prompts talks/2026-meetup/seed.jsonl --output /tmp/keycheck/battles.jsonl`
   and answer no at the confirmation pause. The credential check runs before the pause (a
   stale key fails there); the thinking probe before it costs cents. `orq-arena pool` reads
   only the YAML and proves nothing about the key.
2. `python3 talks/2026-meetup/check.py` prints `ok`.
3. Wifi off: `asciinema play talks/2026-meetup/fallback/demo.cast` plays and
   `open talks/2026-meetup/fallback/battles.report.html` opens from disk.
4. Open `talk.html` on the projector resolution once, walk every toy.

### At the door

Form open, the title slide up with its QR. Export the responses as CSV just before chapter 2.

### Chapter 2: start the run

```bash
python3 talks/2026-meetup/audience_prompts.py ~/Downloads/form.csv -o /tmp/meetup.jsonl
orq-arena run --config talks/2026-meetup/demo.yaml --prompts /tmp/meetup.jsonl \
  --output /tmp/meetup/battles.jsonl --overwrite --tui
```

`--overwrite` because a practice run may have left a log there. No CSV yet? Leave the CSV
out and the run goes on the seed alone. Leave the TUI running in
its own window and go back to the deck.

### Chapter 8: read the result

The leaderboard shows an `audience` category slice only once there are 20 decided rounds on
audience prompts (`MIN_CATEGORY_COMPARISONS` in `src/orq_arena/tournament/driver.py`). Under
20, say the overall ladder is on seed plus audience and move on. Rough guide: about 140 rounds
at 77% decided means three or more submissions usually get there.

Bonus, if time allows: did the jury matter?

```bash
orq-arena rejudge /tmp/meetup/battles.jsonl --config orq_arena.yaml --judge-api llm \
  --judge anthropic/claude-haiku-4-5-20251001 \
  --judge google/gemini-3.5-flash-lite --judge openai/gpt-5.4-nano
```

### Fallback

Wifi down or 429s piling up: switch to the recording and the saved report, one command each.
Not recorded yet: until the rehearsal runs, there is no fallback.

```bash
asciinema play talks/2026-meetup/fallback/demo.cast
open talks/2026-meetup/fallback/battles.report.html
```

### Short slot

Cut in this order: chapter 9 (agents), the chapter 8 rejudge, chapter 3 (BYOK, say it in one
sentence on the build slide).
