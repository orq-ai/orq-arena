# Harbor fixtures (phase 0 spike, 2026-10-19)

Captured from real `harbor run` trials (harbor 0.24.0, task `fix-git` and `regex-log` from
`harbor-framework/terminal-bench-2-1`, model claude-haiku-5-5 or openai/gpt-6-luna through the
orq router). Paths were rewritten (`/repo`, `/home/user`), thinking signatures replaced by
`<sig>`; no key or token appears in any file (grepped). Full command lines and event shapes are
in `.context/plans/harness-spike.md`.

Native agent logs (what the live tail reads, `<trial>/agent/<agent>.txt`):

| file | produced by | notes |
|---|---|---|
| `claude-code.txt` | `-a claude-code`, task regex-log, extra instruction forcing the Write tool | stream-json, 28 lines, whole file. Has `Write`, `Bash`, thinking blocks, final `result` line. |
| `pi.txt` | `-a pi --skill <dir>`, task fix-git | `--mode json`, 93 lines, whole file. First `message_start` (role system) carries `sections.skills` with the skill. Contains an `error` assistant message plus `auto_retry_start/end` (router "Connection error." once). `message_update` lines are already filtered out by harbor. |
| `pi-edit.txt` | `-a pi`, task regex-log, extra instruction forcing the write tool | 46 lines, shows `write` tool (`args.path`, `args.content`). |
| `codex.txt` | `-a orq_codex:OrqCodex` (see notes), task regex-log, extra instruction forcing apply_patch | 11 lines. Shows `file_change` items and `turn.completed` usage. First two lines are NOT JSON (a warning and "Reading additional input from stdin..."). |
| `codex-bash.txt` | same agent, task fix-git | 29 lines, 10 `command_execution` items. |
| `codex-failure-bare-model.txt` | stock `-a codex -m openai/gpt-6-luna` | FAILURE fixture: only `thread.started` and `turn.started`, then silence for 9+ minutes (the router rejects the bare model name `gpt-6-luna` with HTTP 400 and codex retries silently). The trial was killed by SIGINT; see `result-cancelled.json`. |

Harbor-written files:

| file | produced by |
|---|---|
| `trajectory.json` | `<trial>/agent/trajectory.json`, claude-code on fix-git (ATIF-v1.7). Per-agent variants: `trajectory-pi.json` (pi + skill), `trajectory-codex.json` (codex, tool name is always `exec`, the command is JavaScript in `arguments.input`). |
| `result.json` | `<trial>/result.json`, claude-code on fix-git, reward 1.0. `result-pi.json`, `result-codex.json` for the others. |
| `result-cancelled.json` | `<trial>/result.json` of the killed stock-codex trial: `exception_info` is set, `verifier_result` and `agent_result` are null. A `result.json` existing does NOT mean the trial succeeded. |
| `job-result.json` | `<jobs_dir>/<job_name>/result.json` (job level aggregate). |
| `trial-config.json` | `<trial>/config.json`. |
| `test-stdout.txt`, `reward.txt`, `ctrf.json` | `<trial>/verifier/` of the claude-code fix-git trial. |
| `workspace-fix-git.diff` | `docker run --rm --platform linux/amd64 -v <trial>/artifacts/app:/after:ro alexgshaw/fix-git:20260403 diff -ruN --exclude=.git /app /after` (exit code 1 means "differences found", not an error). |
