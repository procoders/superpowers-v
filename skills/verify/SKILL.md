---
name: verify
description: Compound V verification (not the native /verify). Use when a Compound V build is finished, and after any small change (typo, copy, config) in a project set up for Compound V. Runs the project's tests, the real-browser or main-flow check, the scope check and, for full runs, an executable review in an isolated checkout, with at most one fix round. Each step writes a tree-bound receipt. Reports verified, incomplete or failed, and says done only when verified.
---

# Verify

The CLI is the authority here, not you. Each step runs a real command and writes a signed receipt bound to the exact working tree. An edit after a receipt makes it stale. You run the steps, fix what fails, and report what the CLI says. All calls are `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/compound-v.py" … --id <id>`.

**Commands.** Run each command as one plain command line with literal values (the run id, real paths): no shell variables you set yourself, no `;` or `&&` chains, no `$?`, and no pipes or redirects (`|`, `>`, `2>&1`): the one exception is the `<<'REQUEST'` heredoc that hands `run start` its request. The sandbox's auto-allow refuses compound commands, and `sandbox.excludedCommands` only matches a bare call.

## 0. Find or start the run

The session brief (at session start and on your prompts: `Compound V run <id>: stage …`) names this session's run. Use that id: `run show --id <id>`. Without `--id` the CLI answers only when exactly one run is open in the repo, because it cannot tell which session a run belongs to.

**No run, after a small change** (typo, copy, config): start a light run whose `--change-set` globs cover exactly the files you meant to change (`git status --short` shows them). Pass the user's request on stdin:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/compound-v.py" run start --tier light \
  --change-set 'README.md' --request-file - <<'REQUEST'
<the user's request, verbatim>
REQUEST
```

A light run needs `tests` and `scope`, plus `live` when the diff touches UI. It takes `test_cmd`, `live_cmd` and `is_web` from `.claude/compound-v.json`. When your diff touches UI (HTML, CSS, templates, components, `public/`) and the config has no `live_cmd`, ask the user one question before starting the run: the command that checks the page in a real browser, or a waiver of that check. Pass a command with `--live-cmd '<command>'`; record a waiver with `waive live` once the run exists. If the stage is `build`, run `run stage --id <id> --to verify` first.

**Escalation.** The CLI reclassifies the diff by its content (auth, sessions, payments, personal data, new endpoints or forms, a big or binary diff). A light run can become full, and its receipts are then cleared. Tell the user why, in one line with the CLI's reasons, and do the full steps. Without a plan, the review judges against the request alone.

## 1. The steps, in this order

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/compound-v.py" receipt tests --id <id>
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/compound-v.py" receipt live  --id <id>   # when required
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/compound-v.py" receipt scope --id <id>
```

Each one prints one line (`step: result (exit, duration)`), plus the reason and the last 5 output lines on a fail or error; `--json` gives the full receipt. Run each receipt command bare: a pipe or redirect keeps the call inside the sandbox, where a browser cannot start, and the CLI then records `error` ("could not start inside the sandbox"), never a pass.
- **fail**: fix the cause (§3), then run all the steps again. A fix changes the tree, so the earlier receipts are stale.
- **scope fail**: a file outside `change_set` (or outside its lane) changed. Revert it, or, when it belongs to the work, add its glob in the plan block and rerun `run plan`. Never hide a write.
- **error, "gitignore what it writes"**: the command left a non-ignored file behind (a report, a test database, coverage). Add it to `.gitignore`, delete the stray output, and rerun the steps.
- **tests fail with `tests removed`**: a test that existed when the plan was attached is gone. Restore it.
- **error, "could not start inside the sandbox"**: rerun that receipt command exactly as shown above, alone. It is not a product failure.
- **live error, browser cannot run** (no browser binary, no display, sandbox): ask the user once whether to waive the browser check, saying what will not have been checked. Only on their yes: `compound-v.py waive live --id <id> --reason "<their words>"`. A failing browser test is a failure, never a reason to waive.

## 2. Executable review (full runs)

Required for full runs, at most two rounds. Read `reviewer` from `run show --id <id>` (`codex` or `claude`; empty means `claude`).

**Codex:** `compound-v.py review codex --id <id>`. The CLI materializes the tree, runs Codex there, and records the result.

**Claude** (the default):

Run `mktemp -d` on its own and use the directory it prints, literally, as `<dir>` below:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/compound-v.py" checkout --id <id> --dest <dir>/tree   # prints {"tree": ..., "dest": ...}
```

Fill `${CLAUDE_PLUGIN_ROOT}/skills/verify/review-prompt.md`:
- `{request}`: the run record's `request` (the user's original words);
- `{acceptance}`: the plan's `## Acceptance` table (`none: light run` without a plan);
- `{checklists}`: `${CLAUDE_PLUGIN_ROOT}/skills/plan/checklists.md` together with the plan's `## Checklists` answers;
- `{snapshot}`: the `tree` that `checkout` printed;
- `{setup_cmd}`: the plan's `setup_cmd`, or `none`;
- `{previous}`: for round 2, the round-1 findings from `docs/compound-v/runs/<id>-review-1.json`; for round 1, `none`.

Dispatch the `compound-v:reviewer` agent with the filled prompt, `CHECKOUT=<dir>/tree`, `FINDINGS=<dir>/findings.json`, and the round. The findings file must stay outside the repo: inside it, the file would change the tree and stale the review. `review record` copies it into `docs/compound-v/runs/` itself. Then:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/compound-v.py" review record --id <id> --findings <dir>/findings.json --reviewer claude
```

The CLI checks that the findings belong to the current tree, stores them under `docs/compound-v/runs/`, and passes the review only when there are no blocker or high findings.

## 3. The fix round: exactly one

When review 1 has blocker or high findings:
1. `run stage --id <id> --to build`. Fix every blocker and high finding, and the cheap mediums. Each fix comes with a test that would have caught it.
2. `run stage --id <id> --to verify`. Run all of §1 again, then review round 2 (§2).
3. When round 2 still has blocker or high findings, the run ends **incomplete**, with those findings recorded. There is no third review, and nothing is called fixed without a review.

After the last review, edit nothing. An edit stales every receipt, and no review round is left to renew them.

## 4. Status and the report

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/compound-v.py" status --id <id>
```

The exit code is the outcome: 0 verified, 3 pending, 4 incomplete, 5 failed. Each one is a normal answer, so read the JSON (`missing`, `stale`, `failed`, `waived`, `budget`). Pending means a step is still missing or stale: go back to §1.

Report to the user:
- the **outcome** in the first line, then each step's state;
- review findings still open, and acceptance rows unmet or untested;
- waivers, quoted, marked "waived by you in chat, not machine-checked";
- cost: `budget.spent` in USD, labelled "the CLI's estimate", against `budget.limit`, or "unknown" when it is null. Codex time is recorded separately and is not in that figure. Cost is as of the last completed turn: the CLI writes its cost record when a turn ends, so a single-turn `claude -p` run reports it as unknown.

Say **done** only when the outcome is `verified`. For incomplete or failed, name the step and the reason. When the run's escalation reasons include `auth` or `payments`, or the depth was `thorough`, suggest the native `/security-review` as an optional extra, not a receipt.

The Stop hook refuses the first stop of an unverified run, once, with the reason. Continue with this skill. If you are waiting on the user or a step cannot run, say so and stop again. The run is then recorded incomplete. An incomplete run reopens when you write a receipt (or a review, a waiver, a stage move), so carry on once the user answers; a verified run stays closed.

## Common failures

| Claim | What it needs |
|---|---|
| "Tests pass" | A current `tests` receipt with result `pass`, not a run you remember |
| "Works in the browser" | A current `live` receipt, or the user's quoted waiver |
| "Review fixed" | Round 2 recorded with no blocker or high findings |
| "Done" | `status` exits 0 |
| "Just one more tweak after review" | It stales every receipt, and no round is left |
