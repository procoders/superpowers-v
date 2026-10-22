---
name: build
user-invocable: false
description: Use when a Compound V spec is approved and its run is at stage plan. Dispatches one fresh compound-v:builder that does the domain research, the code reading and the library check, writes and attaches the plan, and builds it with tests including the real-browser test. Every later fix goes back to that same builder. Watches the build budget, then hands off to compound-v:verify.
---

# Build

Claude Code builds natively; this skill decides who builds and keeps the main conversation small. One fresh `compound-v:builder` does research, plan and code in its own context. In our benchmark that one-agent scheme matched the best light-flow build, while separate pre-flight agents, a plan written in the main conversation and a separate builder cost more and did not beat it (see V4-RESULTS in the benchmark kit; spec §4.2–4.4). All `compound-v.py` calls are `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/compound-v.py" …` with `--id <id>`.

**Commands.** Run each command as one plain command line with literal values (the run id, real paths): no shell variables you set yourself, no `;` or `&&` chains, no `$?`, and no pipes or redirects (`|`, `>`, `2>&1`): the one exception is the `<<'REQUEST'` heredoc that hands `run start` its request. The sandbox's auto-allow refuses compound commands, and `sandbox.excludedCommands` only matches a bare call.

## 0. Start

`compound-v.py run show --id <id> --brief`. The stage is `plan` after the brainstorm (or `build` when you come back for a fix). The spec path is in the run record.

## 1. One builder

Dispatch **one** `compound-v:builder` subagent, in the foreground. Give it the run id, the spec path and the user's original request (the record's `request`), nothing else: it reads the spec and the code itself. It researches the domain (at most 4 searches), reads the code it will touch, checks any library it adds, writes the plan following `compound-v:plan` and its checklists, runs `run plan` and `run stage --to build` itself, then builds every task with its tests, including the Playwright test for web projects.

**Keep its agent id.** Every later fix (a gap in its report, a failing receipt, review findings) goes to this same builder with `SendMessage`, so it works from the context it already has. Never start a second builder for a fix, and do not fix code yourself. Only if the builder cannot be reached any more, dispatch a new one with the plan path and say why.

When it reports:
1. `run show --id <id> --brief`: the stage must be `build` and the plan attached. If not, send the builder back to finish that step.
2. Read its list of unmet rows, open owner facts and out-of-set paths. An open owner fact that changes what gets built goes to the user now, in one message. Do not re-read the diff or rerun its tests here: verification runs them as receipts.

## 2. Large work

The builder decides whether to split independent parts across native subagents (Opus for judgment, Sonnet for mechanical work). The Workflow tool runs several agents at once and needs the user's explicit opt-in, so the builder uses it only when the spec says `Parallel: yes (owner)`. When more than one agent writes, it uses exclusive lanes, native worktrees and `lane finish`. Lanes need `"worktree": {"baseRef": "head"}` in `.claude/settings.json` (written by `/compound-v:init`). A `refused` lane merge is fixed in the lane, never forced.

## 3. Budget

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/compound-v.py" status --id <id>
```

`status` exits 3 while the run is pending; read the JSON rather than treating the exit code as an error. When `budget.stage_exceeded` lists `build`, tell the builder to finish the current task and stop adding scope. Verification's share is reserved. `spent: null` means the cost is unknown: say so, and carry on. Cost is as of the last completed turn: the CLI writes its cost record when a turn ends, so a single-turn `claude -p` run reports it as unknown.

## 4. Hand off

`compound-v.py run stage --id <id> --to verify`, then invoke `compound-v:verify`. Never call the work done here. Only verification can.
