# Example configs

Ready-to-run model pools. Point `--config` at any of them; bring your own prompts
with `--prompts`. Tiers are drawn from the Artificial Analysis intelligence
index (via orquesta-web `autorouter-intelligence`) so each pool is internally
coherent, no makeweights padding a "frontier" field, no giants lurking in a
"budget" one.

| Config | Models | Providers | AA band | For |
|--------|--------|-----------|---------|-----|
| [`../orq_arena.yaml`](../orq_arena.yaml) | 8 | 5 | mixed, uniform thinking-OFF | The default: a fair apples-to-apples ELO |
| [`reasoning_arena.yaml`](reasoning_arena.yaml) | 8 | 5 | mixed, uniform thinking-ON | Does thinking help on your prompts? |
| [`frontier_8.yaml`](frontier_8.yaml) | 8 | 5 | ~40-56 | The strongest models, each at its best |
| [`budget_8.yaml`](budget_8.yaml) | 8 | 8 | ~12-25 | Which cheap/fast model wins on your prompts |
| [`frontier_16.yaml`](frontier_16.yaml) | 16 | 8 | ~29-56 | Big-field stress test + preference-data generation |
| [`byok_openrouter.yaml`](byok_openrouter.yaml) | 4 | 4 | example | The engine on a non-orq endpoint (bring your own key) |

Pool size drives cost: an N-model pool runs C(N,2) matches (28 for 8, 120 for
16), each `match.max_rounds` rounds. Every run prints an exact spend ceiling and
asks once before spending anything.

Notes:
- **Thinking on/off.** The default and `reasoning_arena` pin a uniform reasoning
  effort for a fair comparison. `frontier_*` let reasoning-native models run at
  their default (best) effort, so they compare at full strength, not under a
  cap. `budget_8` pins only gemini thinking-OFF and lets the preflight probe
  report the rest.
- **Judge/candidate family overlap.** In wide pools the cheap judge trio shares
  provider families with several candidates. That's expected; the report flags
  it. Swap in out-of-family judges when you intend to defend the numbers.
