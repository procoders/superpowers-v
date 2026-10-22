---
name: plan
description: How a Compound V plan is written. The compound-v:builder follows it after its own research, and it can be invoked directly to write or revise a plan. Writes the implementation plan with an acceptance table (behaviour → check), the four checklists answered item by item, tasks with their tests, a task → model table, lanes only for parallel work, and the machine-readable compound-v-plan block. Then attaches it to the run record.
---

# Plan

A plan is the set of decisions a build cannot make on the fly: which files, which behaviours, which checks prove them. The `compound-v:builder` writes it, after its own domain research and code reading, and then builds from it. Write it for an engineer who has not seen the brainstorm. The acceptance table is the contract that both the build and the review are held to.

All `compound-v.py` calls below are `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/compound-v.py" …` with the run's `--id <id>` (the session brief prints it as `Compound V run <id>` if you lost it).

**Commands.** Run each command as one plain command line with literal values (the run id, real paths): no shell variables you set yourself, no `;` or `&&` chains, no `$?`, and no pipes or redirects (`|`, `>`, `2>&1`): the one exception is the `<<'REQUEST'` heredoc that hands `run start` its request. The sandbox's auto-allow refuses compound commands, and `sandbox.excludedCommands` only matches a bare call.

## 0. Inputs

The run is at stage `plan`. Read, in full: the spec and `checklists.md` in this directory, and have the research (builder.md §1) done: the domain requirement table, the code findings with `path:line`, the library verdicts.

## 1. Write `docs/compound-v/plans/YYYY-MM-DD-<topic>.md`

Sections, in this order:

**Header.** Goal (one sentence), spec path, stack, how the app is started.

**`## Research`.** The domain table (`DR#` requirement → source → acceptance row), the open owner facts with the default assumed, and the library verdicts with dated sources.

**`## Constraints`.** Every MUST from the research, one line each with its source (domain row `DR3`, `path:line`, a dated library source). Each open owner fact goes in with the assumption the plan makes.

**`## Acceptance`.** The table both the build and the review are held to:

| # | Behaviour (observable) | Check | Source |
|---|---|---|---|
| A1 | A visitor submits the main form and sees the confirmation with the business's contact details | live: `main-form.spec.ts › submits and confirms` | spec §Booking |
| A2 | Two submissions for the last free unit: one succeeds, the other is refused, exactly one record is stored | test: `test_last_unit_race_one_wins` | D3 |
| A3 | The app refuses to start in production with the placeholder admin password | test: `test_refuses_placeholder_secret` | S1 |

- One row per behaviour, written so that a stranger could check it. Include the **negative** rows: refusals, expiries, limits, erasure.
- Every spec requirement, every DR row, and every checklist item that applies ends up as a row.
- Each check names a test (or a live step) by the name the build will give it.
- The CLI hashes the text from `## Acceptance` to the next `## ` heading. Editing it after receipts exist makes them stale. That is intended, so finish the table here.

**`## Checklists`.** The request outranks the spec's calls: when a call narrows or reinterprets a rule the request states (a boundary read against R2, a "same rules" clause with an exception), the request's reading wins and the plan says so. A spec call never makes an applicable checklist item n.a.: when a call conflicts with an item (a seed file where D1 needs an operator edit), the item wins and the plan says so. Answer every item of `checklists.md` (R, D, V, S, U): `S5 applies → A7` or `U3 n.a. — CLI tool, no pages`. No item is skipped.

**`## Tasks`.** Size each task as the smallest unit that carries its own test cycle and that a reviewer could reject while approving its neighbour. Fold setup, configuration and docs into the task whose deliverable needs them. Each task lists:
- files to create or modify (exact paths);
- the acceptance rows it satisfies;
- its tests by name: negative paths, state transitions, persisted state checked after the action (not just the status code), missing or placeholder config;
- "done when": the command and the result that show it.

For a **web project**, one task writes the real-browser test: Playwright Test (`@playwright/test`, with `webServer` starting the app) submits each main form in a real browser and checks the resulting state (reload, admin view, stored data). Its command is `live_cmd`. curl is not enough: browser-only failures (Origin, cookies, redirects) are exactly what it catches. For a non-web project, `live_cmd` runs the binary or the API through its main flow.

Always include a short operator guide (setup, configuration, routine changes, data requests) as part of a task.

**`## Task → model`.** One row per task: `opus` by default; `sonnet` only for mechanical work with nothing to decide (renames, boilerplate config, copying text the plan already fixes). Give the reason in one line.

**`## Lanes`.** Only when parallel work is chosen, and only when tasks are large, independent and write disjoint files. At this size the default is no lanes: in our benchmark parallel waves were slower and dearer and found nothing more. When used, each task gets exclusive globs, and no glob overlaps another lane's. Shared files (lockfiles, `package.json`, route or migration registries, global styles, and any file more than one task writes) belong to one lane, or to a sequential task after the merges.

## 2. The `compound-v-plan` block

End the plan with exactly one fenced block tagged `compound-v-plan`, holding JSON:

````markdown
```compound-v-plan
{"test_cmd": "npm test",
 "live_cmd": "npx playwright test",
 "is_web": true,
 "change_set": ["src/**", "public/**", "tests/**", "e2e/**", "package.json",
                "package-lock.json", "playwright.config.*", "README.md", "OPERATOR.md"],
 "setup_cmd": "npm ci",
 "budget_usd": 7}
```
````

- Required: `test_cmd`, `live_cmd`, `is_web`, `change_set`. Optional: `setup_cmd` (run in the reviewer's checkout before review), `lanes` (`{"<task>": ["<glob>", …]}`, matching `## Lanes`), `budget_usd` (default 7), `budget_split`, `test_globs`, `timeout_s`.
- `change_set` must cover every path the build will write, including tests, lockfiles and docs. A write outside it fails the scope check. `docs/compound-v/` is exempt.
- `test_cmd` and `live_cmd` must exit non-zero on failure and run from the repo root without prompts.
- **Everything they write must be gitignored.** A tests or live step that leaves a non-ignored file behind is recorded as `error`, because it changed the tree it was checking. The first task adds `.gitignore` entries for every output: Playwright `test-results/` and `playwright-report/`, test databases (`*.sqlite`, `*.db` under a test dir), `coverage/`, caches, logs.

## 3. Self-review, then attach

Check, and fix inline:
1. **Coverage.** Every spec requirement, DR row and constraint maps to a row, and every row maps to a task and a named check.
2. **Checklists.** Every item is answered, and every "applies" points at a row.
3. **Names.** Test names, file paths and commands match across tasks, the table and the block.
4. **Proportion.** A plan longer than the code it describes has written the code. Keep signatures, test names and values, and drop bodies.

Then:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/compound-v.py" run plan --id <id> --plan docs/compound-v/plans/<file>.md
```

A `RunError` names the missing key or section. Fix the plan and run it again until the command prints the record.

## 4. Optional plan review (Codex)

For a high-stakes plan (payments, auth, personal data at scale, or depth `thorough`), when `codex` is installed, offer it once:
`compound-v.py review codex-plan --id <id> --plan <path>`. It is advisory and writes no receipt. Arbitrate each finding in a `## Plan review` section of the plan: accepted (and the change made) or rejected (and why). Then rerun `run plan`.

## 5. Hand off

Report in a few lines: the plan path, the number of acceptance rows, lanes or not, and any assumption made for an open owner fact. The approved spec was the gate; the plan goes back to the user only when it contradicts something they decided. Then:

`compound-v.py run stage --id <id> --to build`, and build (the builder continues itself; invoked directly, hand off to `compound-v:build`). Change no code before this point: the Stop hook refuses once when application code changed before the plan was attached and the run moved to build.

Task right-sizing adapted from Superpowers `writing-plans` (MIT, Jesse Vincent).
