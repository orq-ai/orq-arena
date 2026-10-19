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
| `fallback/` | a rehearsal run: `battles.jsonl`, its report, and the TUI recording |
| `qr.svg`, `qr-repo.svg` | form QR (placeholder) and repo QR |

## Still to fill in

- **Form URL.** `qr.svg` is a placeholder. Once the form exists:
  `uvx segno --scale 10 --border 2 --dark "#f2ecff" --light "#060310" --output=talks/2026-meetup/qr.svg "<form url>"`.
  The form asks for one field whose name contains "prompt"; nothing else is needed.
- **LMArena raise.** The hook slide carries `<!-- VERIFY raise figure before talk -->`.
- **Rehearsal and fallback.** Not run yet (it spends money). Record wall time, rated rounds
  and cost here, and the pool if it had to be trimmed to finish in 15 minutes.

## Runbook

### The day before

1. Key: `export ORQ_API_KEY=$(sed 's/^ORQ_API_KEY=//' ~/.orq/api-key)`, then
   `orq-arena pool --config talks/2026-meetup/demo.yaml`.
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
  --output /tmp/meetup/battles.jsonl --tui
```

No CSV yet? Leave the CSV out and the run goes on the seed alone. Leave the TUI running in
its own window and go back to the deck.

### Chapter 8: read the result

The leaderboard shows an `audience` category slice only once there are 20 decided rounds on
audience prompts (`MIN_CATEGORY_COMPARISONS` in `src/orq_arena/tournament/driver.py`). Under
20, say the overall ladder is on seed plus audience and move on.

Bonus, if time allows: did the jury matter?

```bash
orq-arena rejudge /tmp/meetup/battles.jsonl --config orq_arena.yaml --judge-api llm \
  --judge anthropic/claude-haiku-4-5-20251001 \
  --judge google/gemini-3.5-flash-lite --judge openai/gpt-5.4-nano
```

### Fallback

Wifi down or 429s piling up: switch to the recording and the saved report, one command each.

```bash
asciinema play talks/2026-meetup/fallback/demo.cast
open talks/2026-meetup/fallback/battles.report.html
```

### Short slot

Cut in this order: chapter 9 (agents), the chapter 8 rejudge, chapter 3 (BYOK, say it in one
sentence on the build slide).
