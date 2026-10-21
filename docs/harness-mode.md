# Harness mode

Rate coding agents, not just models. In harness mode a candidate is a **coding agent** (Claude
Code, pi, codex, ...) with a model behind it and an optional setup around it: skills, MCP
servers, memory, a system prompt. Each agent works on real tasks from
terminal-bench 2.1 (an open set of terminal tasks, each with hidden tests) inside a container, and the
arena rates them head to head exactly like models: round-robin matches, a jury, Bradley-Terry
ELO with confidence intervals.

The question it answers is the one model arenas cannot: **same model, different harness. Does the
rating move?** Put "pi" and "pi with skills" in the same pool and the gap between them is what the
skills are worth on your tasks.

## How a round works

1. The arena picks a task and hands it to both agents. Each runs in its own fresh container,
   driven by [Harbor](https://github.com/harbor-framework/harbor), which owns the container and
   the agent.
2. When an agent stops, the task's hidden tests run against what it left behind.
3. If exactly one agent passes, the tests decide the round. No jury call. This is the
   [verifier gate](#the-verifier-gate).
4. If both pass or both fail, a jury reads a short write-up of each solution (test result, the
   diff the agent made, a summary of its steps) and picks the better one.
5. The verdict feeds the ELO, as in any other run.

Headless runs print one line per finished trial. The TUI (`--tui`) streams each agent's steps
live next to each other instead of a model's thinking and answer. The rounds page
(`battles.rounds.html`, linked from the report) shows each side's verdict, diff and trajectory,
with filters to find a round: by agent, task, winner, result, whether the tests or the jury decided
it, and whether both sides passed.

## What you need

- **Docker**, running. Every trial is a container.
- **Harbor**, installed once. It needs Python 3.12 or newer, which is why it is a separate tool and
  not a dependency of orq-arena:

  ```bash
  uv tool install --python 3.13 harbor
  harbor --version
  ```

  The docs were written against Harbor 0.24; the run manifest records the version that ran.
- **`ORQ_API_KEY`** in the environment, as for any run. It reaches every agent as the router key
  through the Harbor process's environment (never a command-line argument or a file), so one key
  covers the agents and the judges. A Claude or Codex subscription login in your shell
  (`CLAUDE_CODE_OAUTH_TOKEN`, `CLAUDE_FORCE_OAUTH`, `CODEX_FORCE_AUTH_JSON` and the like) is
  dropped before Harbor starts, so a run never bills your subscription.

`orq-arena run` checks all of this before it spends anything and stops with a list of what is
missing (see [Preflight](#preflight-and-the-run-plan)).

## Pick the tasks

A prompts file for harness mode has one row per task, with the task folder in its metadata.
`orq-arena tasks sample` builds it from a local copy of the terminal-bench 2.1 dataset
(`harbor-framework/terminal-bench-2-1` on GitHub, cloned to a folder, then pass its `tasks/` folder;
Harbor's own task cache also works):

```bash
orq-arena tasks sample --dataset <path to the dataset> --n 8 --seed 7 -o prompts/tb21-sample.jsonl
```

It draws a stratified sample by difficulty, skips tasks that need a GPU or whose agent time limit
is longer than 15 minutes (by default), and is repeatable for a given `--seed`. Each row looks like an
ordinary prompt (the task instructions as `prompt`, the difficulty as `category`) plus metadata:
`harbor_task_path`, `task_name`, `difficulty`, `timeout_sec` and `image`. Because the difficulty is
the category, the usual per-category ELO slices come out per difficulty for free.

To rebuild a published sample exactly, name its tasks instead of sampling: the 16 tasks of the
reference runs are in `configs/tb21-sample16.txt` (its first 8 are the 8-task reference sample).

```bash
orq-arena tasks sample --dataset <path to the dataset> --names-file configs/tb21-sample16.txt -o tasks.jsonl
```

The rows it writes are identical to the ones the reference runs used, so every trial cached for
them still matches.

Eight tasks is a reference-run size, not a defensible benchmark. See [Costs](#costs).

**Several trials per task.** Agents are not deterministic, so one trial is one draw. Pass
`--replicates 3` and every task appears three times in the file, tagged `replicate` 0, 1, 2. Each
replicate is its own trial per agent, cached and replayed like any other, and a round plays one
replicate against another agent's same replicate. Replicate 0 is keyed exactly like a file written
without `--replicates`, so trials you already have are reused as the first draw. Cost and wall time
scale with the replicate count.

## Configure the pool

The shipped [`configs/harness-tb21.yaml`](https://github.com/orq-ai/orq-arena/blob/master/configs/harness-tb21.yaml)
is a four-agent pool. Trimmed:

```yaml
harness:
  max_parallel_trials: 2
  timeout_multiplier: 1.5       # amd64 images on a Mac run under emulation

verifier_gate: true
judge_api: llm                  # a dossier is too long for decision models

candidates:
  - kind: harness
    name: claude-code
    agent: claude-code
    model_id: anthropic/claude-opus-5-5
    agent_kwargs: { max_turns: 60, max_budget_usd: 2.0 }

  - kind: harness
    name: pi
    agent: pi
    model_id: anthropic/claude-opus-5-5
    agent_kwargs: { max_turns: 60 }

  - kind: harness
    name: pi + skills
    agent: pi
    model_id: anthropic/claude-opus-5-5
    agent_kwargs: { max_turns: 60, thinking: medium }
    overlay:
      skills: harness/skills
      system_prompt: "Prefer small diffs; run the tests before you stop."

judges: [google/gemini-3.1-pro-preview, xai/grok-4.5, mistral/mistral-medium-2604]
```

Run it:

```bash
orq-arena run --config configs/harness-tb21.yaml --prompts prompts/tb21-sample.jsonl
```

Unless you pass `--rounds`, every match draws the whole task set. A trial costs minutes and
dollars, and drawing the same tasks in every match means each trial is run once and replayed in
the other matches (see [Cache and replay](#cache-and-replay)).

Every key is in the [configuration reference](configuration.md#harness-candidates-kind-harness).

### Models and the router

Harbor has no endpoint flag, so each agent is pointed at the orq router through the environment of
the Harbor process, the way Harbor itself reads provider settings. What each agent speaks was
measured against the router:

| Agent | Model | Wire format | Router path |
|---|---|---|---|
| `claude-code` | must be `anthropic/...` | Anthropic messages | `/v3/anthropic` |
| `pi` | any `provider/model` | OpenAI chat completions | `/v3/router` |
| `codex` | must be `openai/...` | OpenAI responses | `/v3/router` |

Stock Harbor cannot run codex against the router: it strips the provider from the model name and
the router's responses endpoint then rejects the request, so codex retries silently forever. The
arena ships a ten-line Harbor agent, `OrqCodex` (in `src/orq_arena/harness/harbor_agents/`), that
puts the prefix back, and puts that folder on the Harbor process's `PYTHONPATH`. Nothing for you to
install.

Other agents are not supported yet: each needs its own routing and parser. An `agent_env` map on a
candidate adds extra environment for the Harbor process (a proxy, say), and its *names* count
toward the candidate's identity. The judges always go through the router.

## Overlay: what each agent honors

The `overlay` block is the setup around the agent. It is how you test "skills on versus off" or
"memory seeded versus empty" for one agent and model. Not every agent can take every key, and one
that cannot **fails config loading with its name in the message**, so a run never silently tests
nothing.

| Overlay key | `claude-code` | `pi` | `codex` | Other agents |
|---|---|---|---|---|
| `skills` (folder, `--skill`) | yes | yes | yes | no |
| `mcp_servers` (`--mcp-config`) | yes | yes | yes | no |
| `memory` (seeded folder) | yes | no | no | no |
| `system_prompt` | yes, appended to the system prompt | yes, as an instruction added to the task (weaker) | yes, as an instruction added to the task | yes, same |
| `settings` (native agent config) | yes | yes | yes | no |

A `skills` folder is either one skill (a folder holding `SKILL.md`) or a folder whose children are
skills. `mcp_servers` takes the usual `{name: {command, args}}` or `{name: {url}}` map. Skills and
MCP are Harbor features, so how well an agent uses them is up to the agent.

Skills and memory paths are resolved on your machine, and preflight stops the run if one
does not exist.

## Identity and variants

Two candidates with the same agent and model but different setups are different contestants. Each
gets a **variant**: the first six characters of a hash of its `agent_kwargs`, the *names* of its
`agent_env` keys (never the values, so a secret cannot leak into a log), its instructions, and the
**contents** of its skills and memory folders. A vanilla agent with nothing set has an empty variant.

The candidate's identity is `agent:model_id#variant`, for example
`pi:anthropic/claude-opus-5-5#e95601`. The default display name is
`agent/short_model-variant`. Because the hash covers file contents, editing a skill file makes a
new contestant with its own rating and its own trials, instead of quietly reusing the old
version's results.

## Cache and replay

A trial is expensive, so each one is run once. Trials are stored under `harness.trials_dir`
(default: the battle log's path plus `.trials`), keyed by the task and the candidate's identity.

- **Same run, later match.** The agent that already ran a task is not run again. Its stored steps
  and result are replayed into the match instantly while the jury still judges live. The pass
  rate, cost and time in the report count each trial once.
- **Re-run after a crash or a judge change.** Point at the same `trials_dir` and finished trials
  are reused. A partial trial from a killed run is deleted and run again.
- **Demo trick.** Run headless once to fill the cache, then run with `--tui` against the same
  `trials_dir`: every trajectory replays instantly and the jury still works live.
- **To re-run one trial**, delete its folder under `trials_dir`.

Re-judging a finished log with `orq-arena rejudge` reads the stored write-ups, so it costs judge
tokens only and never re-runs an agent. Rounds the tests already decided are not re-judged.

## The verifier gate

When exactly one agent passes the hidden tests, the round goes to it without a jury call
(`verifier_gate: true`, the default). This is both cheaper and more reliable: a failing test is
better evidence than a model's reading of a diff. The round is recorded with one vote from a
synthetic judge named `verifier`, and the report and TUI label it "decided by verifier gate".

Pairs that both pass or both fail go to the jury, which reads each side's write-up and weighs
correctness of the diff, minimal and clean changes, efficiency, and reward hacking (editing or
skipping tests, hard-coding the expected output). An agent that edits files under `tests/` is
flagged with a "tests/ edited" warning in the report, because that can turn a failing task into a
passing one without solving it.

Set `verifier_gate: false` to send every pair to the jury. The method is described in
[Methodology](methodology.md#harness-runs-the-verifier-gate-and-the-dossier).

## Preflight and the run plan

Before any spend, `orq-arena run` checks that:

- `harbor` is on the `PATH` and answers `--version`, and Docker is running;
- the router key (`harness.api_key_name`) is set;
- every overlay path exists and every `agent_env` value resolves (`${VAR}` set);
- every prompt row has a `harbor_task_path` that exists on disk.

Any of those failing stops the run with the list. It also runs `harbor run --dry-run` once per
distinct agent as a sanity check; that one only warns, since it depends on the Harbor version.

The run plan then shows the harnesses, the tasks (count, difficulty mix, names), the schedule
(matches, tasks per match, trials and how many are already cached), the task images missing
locally, and the worst-case wall time. The trial count is an upper bound: a tied round does not
count toward a match's round cap, so a small `--rounds` can draw an extra task.

## Costs

Agent spend is **not projected**. The preflight says so, and the caps per trial are whatever you
set in `agent_kwargs`: `max_turns` (claude-code and pi) and `max_budget_usd` (claude-code only).
codex has neither, so a codex trial is bounded by the task's time limit alone.

Those caps are not equal across agents, so they are not a fair limit. codex accepts no turn cap,
and a "turn" means different things per agent: pi on deepseek-v4-pro logged 119 steps under
`max_turns: 60`. The one limit Harbor applies to every agent alike is the task's own time limit
(times `timeout_multiplier`), and that is the rule: **the task time limit is the only per-trial
cap, and spend is capped at the orq gateway** (a [Budget](https://docs.orq.ai/ai-gateway/budgets)
scoped to the run's API key), as a ceiling for the whole run. In the measured runs the dollar cap
never bound (the most a claude-code trial cost was $0.63 against its $2.00 cap with Opus, and
$0.37 against $1.00 in the budget and mid-price pools), while the time limit stopped 18 trials in
the mid-price pool. The shipped configs still carry the old caps; they go when the trials are
next re-run, because changing a contestant's config starts its cache over.

What a run cost is
reported afterwards, as each trial measured it and tagged `observed`. pi reports no cost of its
own, so its cost is its token counts priced at the catalog rate and tagged `estimated`; the
report, the headless table and the TUI mark it with a `~`.

Measured, on an Apple-silicon Mac:

| Run | Trials | Wall time | Agent spend | Per trial | Jury |
|---|---|---|---|---|---|
| Opus 5.5 behind three agents plus codex, 8 tasks | 32 | not recorded | not summed | $0.00 to $0.63, 0.2 to 4.6 min | $2.57 (final run) |
| Budget pool (Haiku 5.5 and cheaper), 16 tasks, 3 in parallel | 96 | 3.2 hours | $7.60 | $0.01 mean, but $0.40 for deepseek-v4-pro | $1.13 |

Budget a few dollars for the jury and a re-judge with a new panel costs only that. Wall time is
dominated by pulling task images on the first run and installing the agent in each fresh
container; a replay from the trial cache costs only the jury calls.

## Caveats

- **Emulation on a Mac.** The task images are linux/amd64. Apple-silicon Macs run them under
  emulation: slower, and a few tasks are flaky. That is why `timeout_multiplier` defaults to 1.5.
  The first run also pulls every task image, 10 to 20 minutes for eight tasks.
- **A fresh container for every trial.** Nothing carries over between tasks. The agent is also
  installed fresh each time, which takes one to four minutes and dominates the wall time of easy
  tasks.
- **pi's live pane lags.** Harbor buffers pi's log in 4 KB blocks, so a pi pane updates in bursts
  and its last steps appear when the trial ends. The result is unaffected.
- **Keep the Mac awake.** On macOS the arena wraps Harbor in `caffeinate -i`. If the machine
  sleeps anyway, the trial clock and its timeout stop mid-run and the timings are wrong.
- **A trial that could not run is voided, never lost.** If Harbor fails before the tests run
  (the container did not start, the agent could not be installed, the router refused every model
  call, a hard time limit), the round is voided and nothing is cached, so the next run tries
  again. An agent that ran out of its own time, whose model refused the task, or whose tests ran
  and failed loses the round.
  Some task images cannot host some agents (a stale package index, for example); the voided
  round names the reason.
- **Disk.** Docker needs room for every task image (hundreds of MB each, a few GB for some) and
  Harbor copies each finished workspace out of the container. The arena keeps only the diff and
  deletes that copy. If the disk fills, Docker Desktop turns read-only and every later trial voids
  with a `docker compose` error: free space, restart Docker Desktop and run again, finished trials
  are reused.
- **Interrupted trials.** Harbor leaves the container of a killed trial behind; the arena removes
  it on a clean cancel, but check `docker ps -a` after a hard kill.
- **Memory is seeded, not accumulating.** `overlay.memory` gives the agent the same starting
  files for each task. Memory that grows across tasks would make task order matter and break the
  cache, so it is out of scope for now.
- **One trial per task and agent, unless you ask for more.** Agents are not deterministic and a
  trial is a single draw, so a small task set gives wide intervals. A pass rate over eight tasks
  moves by 12.5 points per task. `--replicates` repeats each task, at proportional cost.
- **Dockerfile tasks have no pristine workspace.** For a task built from a Dockerfile rather than
  a prebuilt image, the diff is reported as unavailable; the jury still gets the test result and
  the trajectory.
- **Harbor changes often.** A new release comes every few weeks. The version used is recorded in
  the run manifest and shown in the report footer.
- **Self-preference is approximate.** A judge is excluded from a match when its model id equals a
  contestant's, which only roughly applies to agents, and a judge can also favour a model of its
  own maker. The preflight warns when a judge shares a provider with a contestant, and the shipped
  harness configs use panels with no contestant's model family on them.

## Reference run results

The shipped `configs/harness-tb21.yaml` on eight terminal-bench 2.1 tasks, measured on
2026-10-19. claude-code, pi and pi + skills all run `anthropic/claude-opus-5-5`; codex runs
`openai/gpt-6-luna`.

How to read the tables in this section:

- **Pass rate** is passed trials out of verified trials, one trial per task and agent. A trial
  that could not run is voided and run again, so every agent below ends with one verified trial
  per task; the voided attempts are named under each table.
- **`~`** marks a cost that is tokens priced at the catalog rate (pi reports no cost of its own),
  not a billed figure.
- **ELO** comes from the jury and the tests together. All the runs below were re-judged on
  2026-10-21 by panels with no contestant's model family on them (see each config), from the
  stored write-ups, without running an agent again.
- **The caps are not equal.** claude-code stops at its `max_budget_usd`, pi at `max_turns` (turns, not steps), and
  codex only at the task's time limit (see [Costs](#costs)). In these runs the dollar cap never
  bound, but the pass rates compare agents under different limits.
- **The samples are small.** One trial per task over 8 or 16 tasks, and the ELO intervals are
  drawn over rounds, not tasks, so they understate how much a different task draw would move
  things. Agents whose intervals overlap are not separated; read their order as a lead, not a
  ranking. `--replicates` is the way to tighten this, at proportional cost.

| Harness | Pass rate | ELO (95% CI) | $/task | min/task |
|---|---|---|---|---|
| claude-code | 8/8 | 1166 (1020 to 1594) | 0.27 | 1.2 |
| pi + skills | 8/8 | 1053 (920 to 1290) | ~0.21 | 1.4 |
| pi | 7/8 | 978 (810 to 1183) | ~0.21 | 1.3 |
| codex | 5/8 | 804 (519 to 928) | 0.01 | 2.1 |

How to read it:

- **The top two are not separated.** claude-code is ahead of pi + skills in 86% of resamples,
  and its interval overlaps pi + skills and pi. The order of these two has moved before: the
  live run's panel (gpt-6-luna, gemini-3.1-pro-preview and claude-sonnet-5-5, two of them from
  a contestant's family) put pi + skills first, and an earlier run with a different round draw
  put claude-code first. Re-judging with that old panel three more times never switched a winner,
  so the draw and the panel move the order, not the noise of one panel. With 36 rated rounds,
  the order of two agents that pass the same tests is not settled.
- **The tests separate little at the top.** Five of the eight tasks are passed by every agent.
  The one task that separates pi from pi + skills is `headless-terminal`, a single trial each.
  `pi + skills` differs from `pi` in three ways (the skills folder, one line of system prompt and
  `thinking: medium`), so that gap is not attributable to skills alone; the budget config adds a
  control, `pi + thinking`, that changes only the thinking level.
- **codex is clearly behind** on these tasks, failing three of them, and also by far the
  cheapest.

Run conditions: Harbor 0.24.0; the first 8 tasks of `configs/tb21-sample16.txt` (1 easy, 5 medium,
2 hard: `tasks sample --n 8 --seed 7` with `password-recovery` replaced by `cancel-async-tasks`,
because Opus 5.5 refuses it whatever the harness, which tells nothing about the harness); an Apple-silicon Mac with
`max_parallel_trials: 2`; 32 trials, each run once and cached across runs; 48 rounds, of which
the verifier gate decided 10 and the jury 38 (14 of those a tie or no result); jury agreement
90%. The live run's jury cost $2.57 and the re-judge $2.50; 3 of the re-judge's 114 judge votes
were lost to grok-4.5 timeouts. A refusal counts as a loss, like any other failed task.

### Budget pool: cheap models behind the agents

`configs/harness-tb21-budget.yaml` runs six agents on 16 tasks (the 8 above plus 8 more: `fix-git`,
`cobol-modernization`, `pypi-server`, `chess-best-move`, `count-dataset-tokens`, `raman-fitting`,
`configure-git-webserver`, `polyglot-rust-c`), with models that cost about $0.1 to $0.4 per million
input tokens, 10 to 40 times less than Opus. Measured on 2026-10-19 with an Apple-silicon Mac and
`max_parallel_trials: 3`: 96 trials, 3.2 hours, $7.60 of agent spend (pi's cost is estimated from
tokens) and $1.13 of jury; the re-judge with the new panel cost $3.36.

| Harness | Pass rate | ELO (95% CI) | $/task | min/task |
|---|---|---|---|---|
| claude-code (haiku-5-5) | 14/16 | 1238 (1142 to 1362) | 0.03 | 2.0 |
| pi + skills (haiku-5-5) | 12/16 | 1117 (1038 to 1206) | ~0.01 | 1.6 |
| pi (haiku-5-5) | 13/16 | 1069 (990 to 1154) | ~0.01 | 1.6 |
| codex (gpt-6-luna) | 11/16 | 1045 (959 to 1131) | 0.01 | 1.9 |
| pi (deepseek-v4-pro) | 12/16 | 776 (674 to 857) | ~0.40 | 5.6 |
| pi (glm-5.3-flash) | 8/16 | 754 (633 to 841) | ~0.01 | 6.3 |

One codex attempt voided: on `headless-terminal` the verifier timed out after 22 minutes
(`VerifierTimeoutError`). Nothing was cached, so the trial ran again in the same run: codex made
17 attempts and has 16 verified trials, and 11/16 is out of those 16. Every other agent made 16
attempts, all verified.

How to read it:

- **The tests separate more here than with Opus.** Of the 16 tasks, 5 are passed by every agent and
  `raman-fitting` is passed by none, so 10 carry signal, against 3 of 8 in the Opus run.
- **ELO is not pass rate.** pi with deepseek-v4-pro passes 12 of 16, as many as pi + skills, yet rates
  below every Haiku agent and codex. The criteria ask the jury to weigh efficiency, and on trials
  that passed, its median is 37 steps, 3.1 minutes and $0.13, against 10 to 13 steps, under a
  minute and under a cent for the Haiku agents. It lost 52 of its 64 jury rounds. It also accounts for $6.44 of the $7.60 agent
  spend. If you want correctness alone, rank by pass rate.
- **Same model, different harness again.** claude-code leads the three Haiku agents on both pass
  rate (14 of 16 against 12 and 13) and ELO (1238 against 1069 and 1117), but its interval still
  overlaps the two pi entries, so it is a lead, not a separation. The two pi agents overlap fully.
- **The intervals are tighter than the Opus run**: 165 to 220 points wide for the top four, against
  370 to 570 there, because this run drew 240 rounds, 59 of them decided by the tests.
- **Jury:** 92% mean agreement, and 36 rounds ended in a tie or no result.

One trial per task and agent, as above: a pass rate over 16 tasks moves 6 points per task.

#### Skills control: thinking helped, the skills overlay did not

`pi + skills` differs from `pi` in three ways (the skills folder, a system prompt line and
`thinking: medium`), so the budget config adds `pi + thinking (haiku)`: thinking medium and
nothing else. Measured on 2026-10-20, 16 tasks, 7 agents, 16 new trials (the rest replayed from
cache), 278 rated rounds, 0 voided, re-judged by the same panel as the table above:

| Harness | Pass rate | ELO (95% CI) | $/task | min/task |
|---|---|---|---|---|
| claude-code (haiku-5-5) | 14/16 | 1220 (1134 to 1331) | 0.03 | 2.0 |
| pi + thinking (haiku-5-5) | 13/16 | 1208 (1133 to 1307) | ~0.01 | 1.4 |
| pi + skills (haiku-5-5) | 12/16 | 1077 (1008 to 1153) | ~0.01 | 1.6 |
| pi (haiku-5-5) | 13/16 | 1042 (963 to 1118) | ~0.01 | 1.6 |
| codex (gpt-6-luna) | 11/16 | 1021 (938 to 1102) | 0.01 | 1.9 |
| pi (deepseek-v4-pro) | 12/16 | 738 (630 to 819) | ~0.40 | 5.6 |
| pi (glm-5.3-flash) | 8/16 | 695 (561 to 784) | ~0.01 | 6.3 |

- **On correctness the three pi setups are one tier.** They pass 13, 12 and 13 of 16, and the only
  task that separates them is `headless-terminal`, which `pi + skills` fails. One task is too
  close to call.
- **On quality they separate, in two steps.** Thinking medium alone adds 166 points over `pi`
  (1208 against 1042). Adding the skills folder and the prompt line on top of it removes 131 of
  them (`pi + skills`, 1077). On jury rounds `pi + thinking` beat `pi + skills` 7 times to 2 and
  `pi` 8 times to 1 (the rest ties or no result). It takes fewer steps (median 10, against 13
  and 11) and less time (1.4 minutes, against 1.6 and 1.6).
- **So the overlay looks harmful here, not inert.** `pi + skills` still rates 35 points above
  `pi`, but that is thinking's gain minus the overlay's cost.
- **The sample is small.** 16 tasks, one trial each, and the top intervals overlap (claude-code
  and `pi + thinking`; the live run's panel had them the other way round). The example skill in `harness/skills` is two lines, so this says nothing about
  skills that carry real task knowledge.
- ELO is only comparable inside one pool: adding the control moved every rating.

### Mid-price pool: stronger, still cheap models behind pi

`configs/harness-tb21-mid.yaml` puts five more models behind pi on the same 16 tasks, with the two
Haiku 5.5 agents of the budget pool as a bridge. All five were smoke-tested through pi and the
router on one easy task first. Measured on 2026-10-20: 7 agents, 336 rounds, 80 new trials
(the Haiku ones replayed from the budget run's cache), 5.3 hours, and $1.53 of jury ($4.51 for the
re-judge with the new panel). The agent
spend of the five new models was $27.26, and all of it is **estimated** (pi reports no cost, so
it is tokens priced at the catalog rate), not a billed figure.

| Harness | Pass rate | ELO (95% CI) | $/task | min/task | Agent timeouts |
|---|---|---|---|---|---|
| claude-code (haiku-5-5) | 14/16 | 1366 (1263 to 1530) | 0.03 | 2.0 | 0 |
| pi (haiku-5-5) | 13/16 | 1193 (1120 to 1290) | ~0.01 | 1.6 | 0 |
| pi (deepseek-v4.1-flash) | 9/16 | 975 (894 to 1062) | ~0.21 | 10.0 | 4 |
| pi (grok-4.3) | 6/16 | 936 (843 to 1024) | ~0.12 | 4.0 | 2 |
| pi (muse-spark-1.3) | 8/16 | 883 (796 to 951) | ~0.57 | 7.5 | 1 |
| pi (qwen3.8-max) | 9/16 | 835 (746 to 911) | ~0.54 | 15.1 | 8 |
| pi (glm-5.3) | 7/16 | 811 (713 to 879) | ~0.26 | 7.9 | 3 |

One pi (muse-spark-1.3) attempt voided: the trial made no model call ("the router may have
refused it"). It ran again in the same run, so muse-spark-1.3 made 17 attempts and has 16
verified trials. Every other agent made 16 attempts, all verified.

ELO is only comparable inside one pool: the two Haiku agents rate higher here than in the budget
pool because they face weaker opponents.

How to read it:

- **The more expensive models did worse, not better.** None of the five passes more than 9 of 16
  tasks, against 13 for pi on Haiku, and each costs 12 to 57 times more per task for the pi agent
  (about $0.12 to $0.57 against about $0.01) and takes 2.5 to 9 times as long. Together they used
  $27.26 of the run's $27.97 agent spend.
- **Timeouts explain part of it.** 18 of the 112 trials hit the agent time limit, 8 of them
  qwen3.8-max (the task limit is 15 minutes, times the 1.5 multiplier). The Haiku agents had none.
  A timeout is a loss, like any failed task.
- **This measures the models behind pi, as pi drives them, one trial each.** pi was not tuned
  per model, a different harness might suit these models better, and a task passed or failed by
  one trial moves a pass rate 6 points. Treat it as "these five, under pi, on these tasks", not
  as a ranking of the models.
- **The tests still separate**: `fix-git` and `merge-diff-arc-agi-task` are passed by all seven,
  `raman-fitting` by none (as in the budget run), and 125 of the 336 rounds were decided by the
  tests alone.
- **Jury:** 91% mean agreement. The live run's panel had `alibaba/qwen3.7-plus` on it, from the
  same family as qwen3.8-max; without it qwen3.8-max rates 27 points higher, so that judge did
  not favour its family here.

## What comes next

The harness headline is moving to correctness first. With hidden tests, the answer is the pass
rate; the jury's ELO becomes a quality view inside it. Planned, in order:

- **Correctness tier, then one criterion.** The report names the agents the leader cannot be
  told apart from on the tests (paired on the same tasks), then picks the best of them by cost,
  latency, turns or quality. Runs without a jury become possible, the cap rule above is applied,
  and the trials are re-run with replicates.
- **A jury only where it changes the answer:** rounds both agents passed, among the top tier and
  between a baseline and a variant, judged for quality by a panel with no contestant's model on it.
- **A/B through evaluatorq.** A baseline against a variant exports as an evaluatorq pairwise run,
  so the verdict and its interval match the rest of the orq tools.
- **Your own tasks.** Tasks without hidden tests go to the jury instead of being voided, and a guide
  shows how to package your repo's past changes as Harbor tasks.
