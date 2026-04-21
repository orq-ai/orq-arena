# orc-arena

An open-source retro arcade where **LLMs fight as orcs** in a single-elimination
tournament. Every warrior call and every judge call routes through the
[orq.ai router gateway](https://orq.ai) — the project is a live advertisement
for the gateway, and the battle log is drop-in compatible with the
[orq-battlebench](https://github.com/orq-ai/orq-battlebench) router-training
pipeline.

```
   ____  ____   ___      _    ____  _____ _   _    _
  / __ \|  _ \ / __|    / \  |  _ \| ____| \ | |  / \
 | |  | | |_) | |      / _ \ | |_) |  _| |  \| | / _ \
 | |__| |  _ <| |___  / ___ \|  _ <| |___| |\  |/ ___ \
  \____/|_| \_\\____|/_/   \_\_| \_\_____|_| \_/_/   \_\
         ~ 8 warriors. 7 fights. 1 champion. ~
```

## How it works

- **8 orc warriors** (LLMs) seeded into a standard single-elimination bracket.
- Each **match** is a series of prompt-turns capped at `max_rounds=5`.
- Each **turn**: both warriors respond to the same prompt; a fixed **3-judge
  panel** (Claude Haiku 4.5, Gemini 2.5 Flash, GPT-4o-mini) votes A/B/TIE
  with position-bias label swaps.
- **Majority vote** → damage: unanimous = 30 HP, 2-1 = 15 HP, tie = no damage
  and the round doesn't count toward the cap.
- Match ends by **KO** (HP ≤ 0) or **round cap** (higher HP wins).
- At the end, a **Bradley-Terry MLE** produces the final ELO leaderboard and
  a JSONL battle log you can feed straight into router training.

## Install

```bash
cd orc-arena
uv sync
export ORQ_API_KEY=...
```

## Use

```bash
# Offline demo (uses a recorded fixture, no API calls)
uv run orc-arena demo

# Live tournament — hits orq.ai
uv run orc-arena run --config orc_arena.yaml --prompts prompts/starter.jsonl --output battles.jsonl

# Print the roster
uv run orc-arena list-warriors
```

Key bindings in the TUI:

- **Enter** — advance
- **q** — quit

## Configuration

Everything is defined in `orc_arena.yaml`: the 8-warrior roster, the 3-judge
panel, gateway URL, HP rules, and the judge system prompt. Swap any model ID
for another orq.ai-routable model.

## Output

`battles.jsonl` — one line per prompt-turn. Core fields mirror
orq-battlebench's `BattleRecord` (prompt, responses, judge verdicts, majority,
winner), with orc-arena additive fields for match/HP metadata. A matrix-
factorization trainer can ingest the file as-is.

## Architecture (short version)

```
CLI → Tournament ─┐
                  ├─▶ orq.ai router gateway
Arena (battle) ───┤
                  ├─▶ events queue ──▶ Textual TUI
Judges (panel) ───┘                    (future: Unity/web renderer)
```

The engine emits typed `pydantic` events (`MatchStarted`, `ResponseChunk`,
`JudgeVerdict`, `TurnResolved`, …). The TUI is one consumer; a Unity or web
renderer is a later consumer of the same stream.

## Tests

```bash
uv run pytest
```

Covers damage mapping, Bradley-Terry ELO, bracket seeding / propagation,
majority voting with self-judge exclusion, and config loading.

## Stretch work (not in MVP)

- **Unity / web visual renderer** subscribing to the event stream.
- **Publish battle log to an orq.ai dataset** via the API (closes the
  gameplay → router-training loop).
- **ASCII-art sprite layer** with shake-on-damage animation.

## License

MIT
