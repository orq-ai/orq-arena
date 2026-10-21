# LLM judges vs decision models

The arena can judge each round two ways. An **LLM panel** prompts cheap chat models for a
verdict and a written reason. A **decision panel** asks decision models one question through the
orq.ai [Decisions API](https://docs.orq.ai/ai-gateway/features/decisions): is response A better,
response B, or neither? Each answers with a probability per option and no prose.

This page compares the two on real arena rounds and says where each one belongs. Every number
here comes from a run made for this page, and the commands that produced it are listed at the
end so it can be regenerated. Dated 2026-10-13, evaluatorq 1.55.1.

**Short version.** On two pools of eight models, the shipped decision panel (jev-latest,
pplx-decider-v1-27b, gpt-6-luna) agreed with a strong reference jury better than the LLM trio
did on both, decided about a third more rounds, leaned toward longer answers no more than the
reference does, and cost about an eleventh as much per round. It loses the written reasons on
judge cards. The panel was picked using these same two pools, so the margin is an upper
estimate; the second-best panel tried still beat the LLM trio on one pool and tied or trailed it
on the other (section 2.2).

## 1. How the two work

| | LLM panel (`judge_api: llm`) | Decision panel (`judge_api: decisions`) |
|---|---|---|
| What the judge is asked | A prompt with both answers and the criteria; it writes JSON `{explanation, value}` | One `choice` question with options A, B, tie; the criteria are the question, both answers are the material |
| What comes back | A verdict and a paragraph of reasoning | A probability for A, B and tie; the vote is the most likely option |
| Calibration | None: a verdict, no strength | Probabilities; native decision models are trained to make them meaningful (section 2.4) |
| Price | Input and output tokens at chat rates; output is the reasoning | Input tokens only, at about $0.035 to $0.10 per million |
| Seat order | Both orders, a flip abstains | The same; the flip rule is unchanged |
| Context | The judge model's window | Model specific and smaller: decider-4b takes 32k, jev-latest 32k of state plus question |
| Failure modes | Off-contract JSON, refusals, a reasoning model running out of tokens | Refusal (counts as abstain), 4xx/5xx; no parse failures, the answer is typed |
| What the reader sees | The judge's reason on every card | Three probability bars per card, no reason |

Both run through evaluatorq's pairwise jury, so stand-in judges, the quorum and the plurality
rule are the same in both modes. Self-judge exclusion is the arena's own step, taken before the
jury is built, so it too is the same in both. The arena pins every judge to the
endpoint `judge_api` names, because the catalog marks some chat models as decision-capable too
(section 3.1).

## 2. Measured on the arena

### Setup

- **Pool 1, quickstart:** the committed `examples/quickstart/battles.jsonl`, eight frontier and
  mid-tier models, 140 rounds, recorded in July with the then-default LLM panel
  (claude-haiku-4-5, gemini-2.5-flash-lite, gpt-5.4-nano).
- **Pool 2, budget:** two fresh runs of the `configs/budget_8.yaml` pool on
  `prompts/starter.jsonl` (eight small models, 140 rounds each), one judged live by the LLM panel
  that file shipped with then (claude-haiku-4-5, gemini-3.5-flash-lite, gpt-5.4-nano) and one live
  by a decision panel. Each was then re-judged by the other kind of panel. Both configs are kept
  in `docs/research/configs/`, since `configs/budget_8.yaml` now ships the decision panel.
- **Reference jury:** there is no human ground truth for these rounds, so each pool was also
  re-judged by three strong chat models (grok-4.6, kimi-k3, glm-5.3, both seat orders, about
  $10 per pool). "Agreement" below means agreement with this jury on the rounds both decided.
  It is a better yardstick than the cheap LLM panel, not a truth. It is independent of pool 1
  but not of pool 2: `budget_8` seats `xai/grok-4-1-fast`, so grok-4.6 judges its own family
  there, and the pool 2 figures (κ 0.92, Spearman 0.93) may be flattered by it. Re-running
  pool 2 with kimi-k3 and glm-5.3 alone would settle it.
- **Decision models tried:** typesafe/jev-latest, orq/decider-4b, openai/gpt-6-luna,
  perplexity/pplx-decider-v1-27b, alibaba/decision-model-preview, berget/Cloudflare/clef-flash,
  berget/convaiinnovations/laya, berget/Qwen/Qwen3.5-2B: every native decision model the catalog
  lists (chat models that also have a Decisions endpoint are not included, see section 8).

### 2.1 Pool 1: quickstart, against the reference jury

| Panel | Decided | Ties | Agreement | Cohen's κ | Spearman | Longer answer won | Jury $ per 1k rounds | Seconds per round (p50) |
|---|---|---|---|---|---|---|---|---|
| LLM trio, as recorded | 54% | 3% | 91% | 0.83 | 0.79 | 80% | n/a | n/a |
| LLM trio, same three re-run | 59% | 0% | 90% | 0.79 | 0.81 | 83% | $7.09 | 8.5 |
| **Decisions: jev-latest, pplx-decider, gpt-6-luna (shipped)** | **78%** | 8% | 93% | **0.87** | **0.95** | **67%** | **$0.65** | **0.5** |
| Decisions: jev-latest, pplx-decider, decider-4b | 80% | 14% | 94% | 0.90 | 0.83 | 72% | $0.41 | 1.1 |
| Decisions: jev-latest, decider-4b, gpt-6-luna (the plan's panel) | 73% | 17% | 94% | 0.89 | 0.95 | 69% | $0.63 | 1.2 |
| *Reference jury itself* | *79%* | *10%* | | | | *68%* | *$74.17* | *94.5* |

*Decided* is the share of rounds that produced a verdict; the rest were inconclusive and never
reach the rating. *Agreement* and *κ* are measured on the rounds both the panel and the
reference decided. *Spearman* compares the eight-model ranking with the reference jury's
ranking; with eight models one swapped pair moves it by about 0.05, so read differences under
0.1 as noise.

What it says:

- **The LLM trio decides barely half the rounds.** Its judges flip between seat orders 30% to
  50% of the time (gpt-5.4-nano half the time), and a flip throws the vote out. jev-latest and
  pplx-decider flip 10% to 17% across the two pools; gpt-6-luna about a third of the time.
- **On the rounds both decide, every decision panel agrees with the reference at least as well**
  (κ 0.87 to 0.90 against 0.79 to 0.83), while deciding a third more of them.
- **The LLM trio favours the longer answer more than the reference does.** The longer answer won
  80% to 83% of its decided rounds; the reference jury's figure is 68%, the shipped decision
  panel's 67%. The arena prices length out of the rating separately either way.
- **The shipped panel costs about an eleventh as much and answers in half a second.**

### 2.2 Pool 2: budget, two live runs

Two fresh runs of `configs/budget_8.yaml` (gpt-5.4-mini, gemini-3.7-flash, deepseek-flash,
mistral-small, grok-4-1-fast, command-a, qwen3.5-flash, claude-haiku-4-5), 140 rounds each.

**Live, as a user would see them.** One run judged live by the LLM trio, the other live by the
plan's decision panel (jev-latest, decider-4b, gpt-6-luna, pplx-decider as stand-in). The
responses differ between the two runs, so this compares whole runs, not verdicts:

| Live run | Rated rounds | Jury $ | Jury seconds per round (p50) | Run wall time | Interval width, top model |
|---|---|---|---|---|---|
| LLM trio | 78 | $0.88 | 3.4 | 14 min 19 s | 1525 to 2164 |
| Decision panel | 106 | $0.08 | 0.34 | 11 min 55 s | 1157 to 1602 |

**Against the reference, on the LLM-judged run's responses:**

| Panel | Decided | Ties | Agreement | Cohen's κ | Spearman | Longer answer won | Jury $ per 1k rounds | Seconds per round (p50) |
|---|---|---|---|---|---|---|---|---|
| LLM trio, live | 55% | 3% | 94% | 0.89 | 0.69 | 79% | $6.32 | 3.4 |
| **Decisions: jev-latest, pplx-decider, gpt-6-luna (shipped)** | **77%** | 7% | **96%** | **0.92** | **0.93** | **69%** | **$0.59** | **0.6** |
| Decisions: jev-latest, pplx-decider, decider-4b | 70% | 16% | 88% | 0.79 | 0.76 | 83% | $0.37 | 1.4 |
| *Reference jury itself* | *76%* | *8%* | | | | *64%* | *$69.33* | *68.5* |

The second pool is where the choice of the third judge shows: with decider-4b in the third seat
the panel trails the LLM trio on agreement (κ 0.79 against 0.89) and leans to the longer answer
as much as it does; with gpt-6-luna it leads on every column. decider-4b alone agrees with the
reference at κ 0.56 on this pool against 0.71 on the first. Seat-swapped re-judges ran the
other way too (the LLM trio over the decision-judged run): the two kinds of panel ranked that
run's models with Spearman 0.90 between them.

### 2.3 Each decision model alone, and panel size

Every decision model judged all rounds of both pools once, so any sub-panel can be rebuilt
offline from their votes: a judge's vote does not depend on who else sits on the panel.

| Judge | κ alone, pool 1 / pool 2 | Decided, pool 1 / 2 | Flip rate | Picks the first seat | Seconds per round, uncontended |
|---|---|---|---|---|---|
| jev-latest | 0.85 / 0.84 | 84% / 83% | 16% / 17% | 55% / 57% | 0.29 |
| pplx-decider-v1-27b | 0.76 / 0.76 | 86% / 90% | 13% / 10% | 49% / 51% | 0.38 |
| gpt-6-luna | 0.67 / 0.73 | 66% / 64% | 33% / 36% | 65% / 67% | 0.15 |
| clef-flash | 0.71 / 0.67 | 68% / 78% | 32% / 22% | 44% / 45% | 1.6 |
| decider-4b | 0.71 / 0.56 | 70% / 70% | 29% / 30% | 43% / 49% | 0.22 |
| decision-model-preview | 0.45 / 0.57 | 34% / 49% | 65% / 51% | 28% / 33% | n/a |
| laya | 0.11 / 0.01 | 26% / 25% | 73% / 75% | 36% / 29% | n/a |
| Qwen3.5-2B | n/a | 0% / 0% | 100% | 100% | n/a |

Qwen3.5-2B picks whichever answer is shown first, every time, so the flip rule discards all of
its votes. laya and decision-model-preview are close to noise on this task. jev-latest and
pplx-decider are the two best on both pools and the most self-consistent. gpt-6-luna is weaker
alone and leans to the first seat, but its errors fall on different rounds from the other two,
which is what a third judge is for.

Panel size, over every sub-panel of the eight (pool 1 / pool 2):

| Judges | Sub-panels | Decided (median) | κ, median |
|---|---|---|---|
| 1 | 8 | 67% / 67% | 0.71 / 0.67 |
| 3 | 56 | 49% / 52% | 0.87 / 0.82 |
| 5 | 56 | 78% / 79% | 0.84 / 0.82 |
| 7 | 8 | 90% / 88% | 0.84 / 0.82 |

Three judges decide fewer rounds than one (the panel needs a plurality, and a flip or a split
costs the round), but agree better with the reference (κ 0.87 / 0.82 against 0.71 / 0.67).
Five and seven judges decide more rounds again with κ flat around 0.82 to 0.84, so a bigger
panel buys coverage, not agreement. The median three-judge decision panel does not beat the
LLM trio on pool 2 (κ 0.82 against 0.89); the shipped one does because it was picked for it. Among three-judge panels that decide at
least 60% of rounds on both pools and seat no degenerate judge, jev-latest, pplx-decider and
gpt-6-luna has the best combined agreement (κ 0.87 and 0.92) and the highest decided share. It
ships, with decider-4b as the stand-in (fast, run by orq, only called when a primary fails).
gpt-6-luna is an OpenAI model, so the preflight flags the family overlap on pools with OpenAI
candidates; the LLM trio overlapped on all three seats.

### 2.4 Do the probabilities mean anything?

Agreement with the reference jury, by how sure the judge said it was (shipped panel, pool 1 then
pool 2):

| Judge | under 0.60 | 0.60 to 0.80 | 0.80 to 0.95 | 0.95 and over |
|---|---|---|---|---|
| jev-latest | 72% / 50% | 93% / 92% | 96% / 96% | 95% / 100% |
| pplx-decider-v1-27b | 72% / 69% | 100% / 96% | 100% / 100% | (2 votes) |
| gpt-6-luna | (4 votes) | 62% / 80% | 79% / 67% | 93% / 97% |

For jev-latest and pplx-decider the confidence means something: a vote under 0.60 agrees with
the reference half to three quarters of the time, one over 0.60 more than nine times in ten. gpt-6-luna
says 0.80 or more on most votes and is right less often than that in the middle band.

That makes `judge_abstain_below` a real dial (shipped panel, pool 1 / pool 2):

| Floor | Decided | Agreement | κ |
|---|---|---|---|
| off | 78% / 77% | 93% / 96% | 0.87 / 0.92 |
| 0.5 | 69% / 68% | 96% / 95% | 0.92 / 0.91 |
| 0.6 | 48% / 58% | 100% / 99% | 1.00 / 0.97 |
| 0.7 | 40% / 44% | 100% / 98% | 1.00 / 0.97 |

A floor of 0.6 buys near-perfect agreement at the price of a third of the rounds, which widens
every confidence interval. The default stays off; raise it when a decided round must be right
more than the ranking must be tight.

### 2.5 Seat swap

The plan was to turn seat swapping off for decision panels if their judges flipped under 2% of
the time, halving judge calls. They flip 10% to 36%. Swap stays on.

## 3. What it buys and what it costs the arena

**Buys.** An eleventh of the jury spend. Rounds judged in about half a second instead of three to
eight. A third more decided rounds from the same responses, so tighter intervals for the same model
spend. A length lean no stronger than the reference jury's. A measured jury cost: decision calls report their own price, so
the report's jury card is exact rather than an estimate (prompted judges are now priced per call
too). A confidence per vote that can be thresholded.

**Costs.** The judge cards lose their written reasons; a reader auditing a surprising verdict
sees "A 71%, B 18%, tie 11%" instead of why. Criteria nuance is compressed into one question.
The Decisions API is in beta and carries no evaluators or guardrails yet.

### 3.1 Found along the way

- **The shipped LLM panel had quietly become a mixed one.** evaluatorq 1.55.1 sends a judge to
  the Decisions API whenever the authenticated catalog marks it decision-capable, and the catalog
  marks claude-haiku-4-5 (and gpt-oss, gemini-3.8-flash, glm-5.3-flash and others) that way. From
  the evaluatorq 1.55.1 bump until this change, the default panel's haiku seat answered with
  probabilities, not a prompted verdict. `judge_api` now decides the endpoint and the arena pins
  every judge to it.
- **Decision judges can hit the workspace rate limit.** A re-judge at concurrency 8 with three
  decision judges and both seat orders wants 48 requests in flight, and a provider behind the
  router can answer 429. evaluatorq does not retry a 429: the vote is lost. Since evaluatorq 1.74
  it also caps in-flight judge requests at 10 per process. We measured that cap on 2026-10-21
  (evaluatorq 1.74.0, arena `3f5a894`): the 140-round quickstart log re-judged by this panel
  (jev-latest, pplx-decider-v1-27b, gpt-6-luna) at `--concurrency 8`, twice at the default cap
  and twice with it raised to 48 through `scripts/rejudge_cap.py`. Wall time was the same within
  noise (35 and 48 s at 10, 41 and 44 s at 48). Lost votes were not: at 10, pplx-decider lost 6
  and 4 of its 140 votes to 429s; at 48 it lost 57 and 62, and the panel decided 93 and 95
  rounds instead of 109 and 113. So the cap costs no time and protects the votes; we keep it.
  The commands and raw numbers are in [`rejudge-cap-timing.json`](rejudge-cap-timing.json).
  Live runs stay under the cap (generation is the bottleneck), and a re-judge that loses votes
  can be repeated at a lower `--concurrency`.
- **jev-latest's catalog window (64k) is not its limit:** state plus question must fit 32k.
  Prompt plus two capped responses stays well under that on every shipped config.

## 4. LLM-as-jury in general

A decision model is a drop-in judge when the verdict is a choice from a short fixed list (A or B
or tie, pass or fail, a label), a yes/no with a probability, or a bounded score, and the material
fits its context. Pairwise preference, guardrail checks and rubric levels all fit.

It is not a drop-in when the output has to be a reason (an audit trail, feedback to a writer), when
the rubric has many clauses that interact (it gets one question, not a checklist to reason
through), when the material is long (multi-turn transcripts or agent traces past 32k to 64k),
when judging means computing or quoting (checking arithmetic, citing the faulty line), or when
the verdict depends on tool calls and their results that would have to be serialized into the
state.

## 5. Applications: evaluation

- **Pairwise preference** at arena scale, as measured above.
- **Pass/fail guardrails and CI gates**: a `noul` question per rule, a threshold on the
  probability, and the threshold means something because the probability is calibrated.
- **Rubric scores**: a `score` question over ordered levels returns a probability-weighted level.
- **Online sampling**: at input-token prices, judging every production call instead of a 1%
  sample becomes a budget line rather than a project.
- **Evaluator alignment**: where an LLM judge needs prompt surgery to move its pass rate, a
  calibrated judge has a threshold to move, and the confidence says which items a human should
  look at.

## 6. Applications: data generation

Decision models do not generate; they filter and label. A pilot: 192 benchmark prompts generated
by gpt-5.4-mini for the four starter categories, 72 of them with a planted flaw (off category,
unanswerable, or a near-duplicate of a starter prompt), each labelled usable or not.

| Labeller | Flaws caught | Flags that were flaws | Good prompts kept | Seconds per label | $ per 1k labels |
|---|---|---|---|---|---|
| jev-latest (decision) | 89% | 97% | 98% | 0.26 | $0.025 |
| gpt-6-luna (decision) | 71% | 100% | 100% | 0.14 | $0.044 |
| decider-4b (decision) | 65% | 57% | 71% | 0.11 | $0.013 |
| gemini-3.5-flash-lite (LLM) | 88% | 94% | 97% | 0.56 | $0.105 |
| gpt-5.4-nano (LLM) | 85% | 79% | 87% | 0.58 | $0.075 |

jev-latest matched the better LLM filter at a quarter of the price and twice the speed. Every
labeller caught every unanswerable prompt; off-category prompts were the hard case for all of
them, and decider-4b missed nearly every near-duplicate. Labels here are the planted intent, not
a human check.

Where this goes: rejection sampling of synthetic data, dedup and on-topic gates, preference-pair
labelling for DPO (an arena round is exactly a labelled pair, with a confidence), and routing the
low-confidence items to people.

## 7. When to use which

| Situation | Use | Why |
|---|---|---|
| Ranking models on your prompts, arena style | Decision panel | Cheaper, faster, more decided rounds, better agreement; which three judges sit on it matters (section 2.2) |
| You must read why a judge decided | LLM panel | Decision models return no reasons |
| Judging long transcripts or agent traces | LLM panel | Decision context is 32k to 64k |
| Rubric with many interacting clauses | LLM panel, or one decision question per clause | One question compresses the rubric |
| Guardrail or CI gate on a clear rule | Decision model | Calibrated probability, typed answer, input-only price |
| Judging all production traffic | Decision model | Price makes 100% sampling affordable |
| Filtering synthetic data | Decision model (jev-latest) | Matched the better LLM filter at a quarter of the cost |
| A judge must not change identity mid-run | Either; the arena pins endpoints | |

## 8. Open questions and follow-ups

- **Human anchors.** The reference here is a strong LLM jury. Fifty human-annotated rounds per
  pool (`orq-arena annotate`, then `orq-arena anchor`) would say how both panels track people.
- **Soft Bradley-Terry.** Every vote now stores its probabilities, so a rating fit on them rather
  than on hard votes can be tried offline on saved runs.
- **evaluatorq:** retry 429s with the router's wait hint; expose per-vote usage, so the report can
  show each judge's cost; let a caller pass the Decisions API `cache` option, so a repeated
  re-judge costs nothing.
- **Emulated decision models.** The catalog's chat models with a Decisions endpoint (haiku,
  gemini flash, gpt-oss) report probabilities they were not trained to calibrate; they were not
  measured here.
- **Calibration plot** in the report, from the data already in `judge_votes`.

## Reproduce

All re-judges read recorded responses, so they cost judge tokens only. Tables come from
`scripts/judge_study.py`; the pilot from `scripts/data_filter_pilot.py`.

```bash
# Pool 1: reference jury, then each panel (repeat --judge per model)
orq-arena rejudge examples/quickstart/battles.jsonl \
  --config docs/research/configs/quickstart_reference_jury.yaml --judge-api llm \
  --judge xai/grok-4.6 --judge moonshotai/kimi-k3 --judge zai/glm-5.3 \
  --output qs.reference.jsonl
orq-arena rejudge examples/quickstart/battles.jsonl \
  --config docs/research/configs/quickstart_decisions.yaml --judge-api decisions \
  --judge typesafe/jev-latest --judge perplexity/pplx-decider-v1-27b --judge openai/gpt-6-luna \
  --concurrency 3 --output qs.decisions.jsonl  # the study ran at 3; see 3.1 on concurrency
uv run python scripts/judge_study.py --ref qs.reference.jsonl \
  "recorded LLM panel=examples/quickstart/battles.jsonl" "decisions=qs.decisions.jsonl"

# Pool 2: two live runs, then the same re-judges over b8_llm.jsonl
orq-arena run --config docs/research/configs/budget_8_live_llm.yaml \
  --prompts prompts/starter.jsonl -y --output b8_llm.jsonl
orq-arena run --config docs/research/configs/budget_8_live_decisions.yaml \
  --prompts prompts/starter.jsonl -y --output b8_dec.jsonl

# Panel sweep: all eight decision models in one panel, then every sub-panel offline
orq-arena rejudge examples/quickstart/battles.jsonl \
  --config docs/research/configs/quickstart_decisions.yaml --judge-api decisions \
  --judge typesafe/jev-latest --judge orq/decider-4b --judge openai/gpt-6-luna \
  --judge perplexity/pplx-decider-v1-27b --judge alibaba/decision-model-preview \
  --judge berget/Cloudflare/clef-flash --judge berget/convaiinnovations/laya \
  --judge berget/Qwen/Qwen3.5-2B --output qs.all8.jsonl
uv run python scripts/judge_study.py --ref qs.reference.jsonl "all 8=qs.all8.jsonl" --sweep "all 8"

# Data filtering pilot
uv run python scripts/data_filter_pilot.py --out pilot/
```

A round where a judge call failed for an infrastructure reason (a 429 burst) was re-judged with
the same panel and spliced back (`scripts/repair_failed_rounds.py`); 1 to 16 rounds per log were
affected.
