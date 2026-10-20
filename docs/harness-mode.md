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

judges: [openai/gpt-6-luna, google/gemini-3.1-pro-preview, anthropic/claude-sonnet-5-5]
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

Agent spend is **not projected**. The preflight says so and the cap per trial is whatever you set
in `agent_kwargs` (`max_budget_usd`, `max_turns`). What it does cost is reported afterwards, as
measured by each trial and tagged `observed` in the report. pi reports no cost of its own, so
its cost is its token counts priced at the catalog rate and tagged `estimated`.

Rough planning numbers, computed from public terminal-bench figures and not measured on this
tool: about six minutes and between $0.5 and $1 per trial for a frontier model. The reference
pool of four agents on eight tasks is 32 trials, so budget in the tens of dollars and a few hours
of wall time at two parallel trials. The jury adds a few dollars; a re-judge with a new panel
costs only that.

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
  contestant's, which only roughly applies to agents. The preflight still warns when a judge
  shares a provider with a contestant.

## Reference run results

The shipped `configs/harness-tb21.yaml` on eight terminal-bench 2.1 tasks, measured on
2026-10-19. claude-code, pi and pi + skills all run `anthropic/claude-opus-5-5`; codex runs
`openai/gpt-6-luna`.

| Harness | Pass rate | ELO (95% CI) | $/task | min/task |
|---|---|---|---|---|
| pi + skills | 8/8 | 1121 (999 to 1334) | 0.21 (estimated) | 1.4 |
| claude-code | 8/8 | 1060 (914 to 1253) | 0.27 | 1.2 |
| pi | 7/8 | 982 (851 to 1140) | 0.21 (estimated) | 1.3 |
| codex | 5/8 | 837 (561 to 968) | 0.01 | 2.1 |

How to read it:

- **The top two are not separated.** pi + skills is ahead of claude-code in 69% of resamples.
  The jury is not what makes the order wobble: re-judging the same 48 rounds three more times
  with the same panel changed the verdict on 16 of the 38 jury-judged rounds at least once, but
  never switched a winner (the changes are between a pick, a tie and no result), and the ranking
  came out identical every time. What moves the order is which rounds are drawn: the first run,
  with a different draw and `password-recovery` in the sample, put claude-code first. With 32
  rated rounds, the order of two agents that pass the same tests follows the draw.
- **The tests separate little at the top.** Five of the eight tasks are passed by every agent.
  The one task that separates pi from pi + skills is `headless-terminal`, a single trial each:
  suggestive for the skill, not a measurement.
- **codex is clearly behind** on these tasks, failing three of them, and also by far the
  cheapest.

Run conditions: Harbor 0.24.0; `orq-arena tasks sample --n 8 --seed 7` (1 easy, 5 medium,
2 hard), with `password-recovery` swapped for `cancel-async-tasks` because Opus 5.5 refuses it
whatever the harness, which tells nothing about the harness; an Apple-silicon Mac with
`max_parallel_trials: 2`; 32 trials, each run once and cached across runs; 48 rounds, of which
the verifier gate decided 10 and the jury 38 (16 of those inconclusive); jury agreement 80%,
jury cost $2.57 for the final run. A refusal counts as a loss, like any other failed task.

### Budget pool: cheap models behind the agents

`configs/harness-tb21-budget.yaml` runs six agents on 16 tasks (the 8 above plus 8 more: `fix-git`,
`cobol-modernization`, `pypi-server`, `chess-best-move`, `count-dataset-tokens`, `raman-fitting`,
`configure-git-webserver`, `polyglot-rust-c`), with models that cost about $0.1 to $0.4 per million
input tokens, 10 to 40 times less than Opus. Measured on 2026-10-19 with an Apple-silicon Mac and
`max_parallel_trials: 3`: 96 trials, 3.2 hours, $7.60 of agent spend (pi's cost is estimated from
tokens) and $1.13 of jury.

| Harness | Pass rate | ELO (95% CI) | $/task | min/task |
|---|---|---|---|---|
| claude-code (haiku-5-5) | 14/16 | 1204 (1121 to 1318) | 0.03 | 2.0 |
| pi + skills (haiku-5-5) | 12/16 | 1112 (1042 to 1191) | 0.01 | 1.6 |
| pi (haiku-5-5) | 13/16 | 1083 (1012 to 1165) | 0.01 | 1.6 |
| codex (gpt-6-luna) | 11/16 | 1046 (959 to 1136) | 0.01 | 1.9 |
| pi (glm-5.3-flash) | 8/16 | 780 (668 to 864) | 0.01 | 6.3 |
| pi (deepseek-v4-pro) | 12/16 | 775 (665 to 853) | 0.40 | 5.6 |

How to read it:

- **The tests separate more here than with Opus.** Of the 16 tasks, 5 are passed by every agent and
  `raman-fitting` is passed by none, so 10 carry signal, against 3 of 8 in the Opus run.
- **ELO is not pass rate.** pi with deepseek-v4-pro passes 12 of 16, as many as pi + skills, yet rates
  last. The criteria ask the jury to weigh efficiency, and on trials that passed, its median is 37
  steps, 3.1 minutes and $0.13, against 10 to 13 steps, under a minute and under a cent for the
  Haiku agents. It lost 50 of its 64 jury rounds. It also accounts for $6.44 of the $7.60 agent
  spend. If you want correctness alone, rank by pass rate.
- **Same model, different harness again.** claude-code leads the three Haiku agents on both pass
  rate (14 of 16 against 12 and 13) and ELO (1204 against 1083 and 1112), but its interval still
  overlaps the two pi entries, so it is a lead, not a separation. The two pi agents overlap fully.
- **The intervals are tighter than the Opus run**: 150 to 200 points wide for the top four, against
  290 to 410 there, because this run drew 240 rounds, 59 of them decided by the tests.
- **Jury:** 94% mean agreement, and 38 rounds ended in a tie or no result. One round voided: a
  codex trial hit `VerifierTimeoutError` after 22 minutes and is retried on the next run.

One trial per task and agent, as above: a pass rate over 16 tasks moves 6 points per task.

