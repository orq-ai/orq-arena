# Harness mode

Rate coding agents, not just models. In harness mode a candidate is a **coding agent** (Claude
Code, pi, codex, ...) with a model behind it and an optional setup around it: skills, MCP
servers, memory, a system prompt. Each agent works on real tasks from
terminal-bench 2.1 (an open set of 89 terminal tasks, each with hidden tests) inside a container, and the
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
live next to each other instead of a model's thinking and answer. The HTML report shows each
side's verdict, diff and trajectory.

## What you need

- **Docker**, running. Every trial is a container.
- **Harbor**, installed once. It needs Python 3.12 or newer, which is why it is a separate tool and
  not a dependency of orq-arena:

  ```bash
  uv tool install --python 3.13 harbor
  harbor --version
  ```

  The docs were written against Harbor 0.24; the run manifest records the version that ran.
- **`ORQ_API_KEY`** in the environment, as for any run. Harbor passes it to every agent as the
  router key, so one key covers the agents and the judges.

`orq-arena run` checks all of this before it spends anything and stops with a list of what is
missing (see [Preflight](#preflight-and-the-run-plan)).

## Pick the tasks

A prompts file for harness mode has one row per task, with the task folder in its metadata.
`orq-arena tasks sample` builds it from a local copy of the terminal-bench 2.1 dataset
(`terminal-bench/terminal-bench-2-1`, cloned or downloaded to a folder; Harbor's own task cache
also works):

```bash
orq-arena tasks sample --dataset <path to the dataset> --n 8 --seed 7 -o prompts/tb21-sample.jsonl
```

It draws a stratified sample by difficulty, skips tasks that need a GPU or whose agent time limit
is longer than 15 minutes (by default), and is repeatable for a given `--seed`. Each row looks like an
ordinary prompt (the task instructions as `prompt`, the difficulty as `category`) plus metadata:
`harbor_task_path`, `task_name`, `difficulty`, `timeout_sec` and `image`. Because the difficulty is
the category, the usual per-category ELO slices come out per difficulty for free.

Eight tasks is a reference-run size, not a defensible benchmark. See [Costs](#costs).

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
    api_format: anthropic_messages
    agent_kwargs: { max_turns: 60, max_budget_usd: 2.0 }

  - kind: harness
    name: pi
    agent: pi
    model_id: anthropic/claude-opus-5-5
    api_format: openai_chat_completions
    agent_kwargs: { max_turns: 60 }

  - kind: harness
    name: pi + skills
    agent: pi
    model_id: anthropic/claude-opus-5-5
    api_format: openai_chat_completions
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

All agents are pointed at the orq router through Harbor's own flags (`--base-url`,
`--api-key-name`, `--api-format`), with no custom code:

| Agent | `api_format` | Router path |
|---|---|---|
| `claude-code` | `anthropic_messages` | `/v3/anthropic` |
| `pi` | `openai_chat_completions` | `/v3/router` |
| `codex` | `openai_responses` | `/v3/router` |

Whether the router can serve a given agent depends on that agent. If one cannot be served, give it
a native provider key for that candidate only:

```yaml
agent_env: { OPENAI_API_KEY: "${OPENAI_API_KEY}" }
```

The run then no longer routes that agent through orq, and you should say so when you publish the
results. The judges always go through the router.

## Overlay: what each agent honors

The `overlay` block is the setup around the agent. It is how you test "skills on versus off" or
"memory seeded versus empty" for one agent and model. Not every agent can take every key, and one
that cannot **fails config loading with its name in the message**, so a run never silently tests
nothing.

| Overlay key | `claude-code` | `pi` | `codex` | Other agents |
|---|---|---|---|---|
| `skills` (folder copied in) | yes | yes | no | no |
| `mcp_servers` | yes | yes | no | no |
| `memory` (seeded folder) | yes | no, use `files` | no | no |
| `system_prompt` | yes, appended to the system prompt | yes, but as extra instructions (weaker) | yes, as extra instructions | yes, as extra instructions |
| `settings` | yes | no, use `files` | yes | no |
| `files` (`{container path: local path}`) | no | yes, needs the helper below | no | no |

`files` is the escape hatch for anything an agent reads from disk, for example a pi extension. It
runs pi through a small helper agent (`orq_arena_harbor.pi_files:PiWithFiles`, in `harbor_agents/`)
that uploads the files first. The helper has to be installed into Harbor's own environment:

```bash
uv tool install --python 3.13 harbor --with-editable ./harbor_agents
```

Skills, memory and `files` paths are resolved on your machine, and preflight stops the run if one
does not exist.

## Identity and variants

Two candidates with the same agent and model but different setups are different contestants. Each
gets a **variant**: the first six characters of a hash of its `agent_kwargs`, the *names* of its
`agent_env` keys (never the values, so a secret cannot leak into a log), its instructions, and the
**contents** of its overlay files. A vanilla agent with nothing set has an empty variant.

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
measured by each trial and tagged `observed` in the report.

Rough planning numbers, computed from public terminal-bench figures and not measured on this
tool: about six minutes and between $0.5 and $1 per trial for a frontier model. The reference
pool of four agents on eight tasks is 32 trials, so budget in the tens of dollars and a few hours
of wall time at two parallel trials. The jury adds a few dollars; a re-judge with a new panel
costs only that.

## Caveats

- **Emulation on a Mac.** The task images are linux/amd64. Apple-silicon Macs run them under
  emulation: slower, and a few tasks are flaky. That is why `timeout_multiplier` defaults to 1.5.
  The first run also pulls every task image, 10 to 20 minutes for eight tasks.
- **A fresh container for every trial.** Nothing carries over between tasks.
- **Memory is seeded, not accumulating.** `overlay.memory` gives the agent the same starting
  files for each task. Memory that grows across tasks would make task order matter and break the
  cache, so it is out of scope for now.
- **One trial per task and agent.** Agents are not deterministic and a trial is a single draw, so
  a small task set gives wide intervals. A pass rate over eight tasks moves by 12.5 points per task.
- **Dockerfile tasks have no pristine workspace.** For a task built from a Dockerfile rather than
  a prebuilt image, the diff is reported as unavailable; the jury still gets the test result and
  the trajectory.
- **Harbor changes often.** A new release comes every few weeks. The version used is recorded in
  the run manifest and shown in the report footer.
- **Self-preference is approximate.** A judge is excluded from a match when its model id equals a
  contestant's, which only roughly applies to agents. The preflight still warns when a judge
  shares a provider with a contestant.

## Reference run results

To be filled after the reference run. Nothing below is measured yet.

| Harness | Pass rate | ELO (95% CI) | $/task (observed) | min/task |
|---|---|---|---|---|
| claude-code | to be filled after the reference run | | | |
| pi | to be filled after the reference run | | | |
| pi + skills | to be filled after the reference run | | | |
| codex | to be filled after the reference run | | | |

Run conditions to record with the numbers: Harbor version, task sample (`--n`, `--seed`), machine
and `max_parallel_trials`, wall time, and the share of rounds the verifier gate decided.
