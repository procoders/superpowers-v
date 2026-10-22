---
name: build
description: Use when a Compound V run has an attached plan and is at stage build. Implements the plan task by task, with tests written alongside the code (negative paths, state transitions, persisted state, missing config). One agent by default; parallel native worktree subagents only when the plan has Lanes, each one merged through the lane gate. Watches the build budget, then hands off to compound-v:verify.
---

# Build

Claude Code builds natively. This skill sets what a good build does and the few commands that keep it honest. All `compound-v.py` calls are `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/compound-v.py" …` with `--id <id>`.

**Commands.** Run each command as one plain command line with literal values (the run id, real paths): no shell variables you set yourself, no `;` or `&&` chains, no `$?`. The sandbox's auto-allow refuses compound commands.

## 0. Start

`compound-v.py run show --id <id>`. The stage must be `build` and the plan must be attached (`test_cmd`, `change_set` are set). If it is not, go back to `compound-v:plan`. Read the plan in full, including `## Constraints`, `## Acceptance` and `## Checklists`.

## 1. One agent, task by task (the default)

Work through `## Tasks` in order. For each task:

1. Write the tests named in the plan **with** the code, not after it:
   - negative paths: wrong, missing, oversized, replayed and expired input;
   - state transitions, including the forbidden ones;
   - persisted state: after an action, read back what was stored (the database, the file, the next page), not just the status code;
   - missing or placeholder config: the app refuses to start, and no default secret works.
2. Implement until the task's tests pass, then run the whole `test_cmd`.
3. Check the task's acceptance rows: each one now has a passing check under the name the plan gave it.

Tasks the `## Task → model` table marks `sonnet` may go to a `general-purpose` subagent with `model: "sonnet"`, one at a time, with the task text and its files. Review its diff before moving on.

**Stay inside `change_set`.** When you must write a path outside it, add the glob to the plan's `compound-v-plan` block, say why in the plan, and rerun `compound-v.py run plan --id <id> --plan <path>`. A write outside the set fails the scope check later.

**Do not weaken a check to pass it.** Deleting or loosening a test the plan named is recorded: the tests receipt fails with `tests removed`. When a row really cannot be met, keep it failing and say so in the hand-off.

For web projects, write the Playwright test (`live_cmd`) as its plan task says and run it here. A browser-only failure found now is cheaper than one found in review.

## 2. Parallel lanes (only when the plan has `## Lanes`)

Before the first lane:
- `.claude/settings.json` must contain `"worktree": {"baseRef": "head"}` (written by `/compound-v:init`). Without it, native worktrees branch from the default branch and miss this run's work. If it is missing, build the lanes one after another as in §1, and say so.
- Commit the main tree's current work. A lane merge is refused while the main tree has uncommitted changes outside `docs/compound-v/`.

Then dispatch one native subagent per lane task, **in one message**, each with `isolation: "worktree"` and the `model` from the plan's table. Tell each one:
- the task text, its acceptance rows and its tests;
- to write **only** inside its lane's globs, listed verbatim;
- to run `test_cmd`, commit all its work, and end its report with the output of `git rev-parse --abbrev-ref HEAD`.

Native worktrees live under `.claude/worktrees/`, which the snapshot and the scope check ignore. When a lane reports back, merge it through the gate:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/compound-v.py" lane finish --id <id> --task <task> --branch <branch from the report>
```

`merged` means the lane stayed in its globs, merged cleanly, and the tests passed on the merged tree. `refused` comes with a reason and, for out-of-lane writes, the `violations`: writes outside the lane, an interrupted worker with uncommitted changes, no commits, a merge conflict, failing tests on the merged tree, or a dirty main tree. The main tree is left untouched. Fix the cause, in the lane or in the plan, or report it to the user. Never force the merge or work around the gate.

## 3. Budget, at each task boundary

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/compound-v.py" status --id <id>
```

`status` exits 3 while the run is pending. That is normal: read the JSON rather than treating the exit code as an error. When `budget.stage_exceeded` lists `build`, stop adding scope: finish the current task and go to verification. Verification's share of the budget is reserved and must not be spent here. `spent: null` means the cost is unknown. Say so, and carry on. Cost is as of the last completed turn: the CLI writes its cost record when a turn ends, so a single-turn `claude -p` run reports it as unknown.

## 4. Hand off

When every task is done, or the budget stopped you:
- run `test_cmd` and `live_cmd`, then `git status --porcelain`. Anything new that the commands wrote (reports, test databases, coverage, caches) goes into `.gitignore` now. Otherwise the verify step records `error` for changing the tree it checks;
- make sure the operator guide exists;
- list any acceptance row that is unmet or untested, with the reason;
- `compound-v.py run stage --id <id> --to verify`, then invoke `compound-v:verify`.

Never call the work done here. Only verification can.
