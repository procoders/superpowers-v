# Troubleshooting

All CLI calls below are `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/compound-v.py" … --id <id>`; from a
checkout of this repo, `python3 scripts/compound-v.py`.

## The hooks say nothing

Compound V's hooks only act in a project that is set up and has a first commit.

- **Not set up.** Without `.claude/compound-v.json` the prompt hook prints one line per session,
  "Compound V is installed but not set up here — run /compound-v:init", and does nothing else. Run
  `/compound-v:init` and approve its changes.
- **Not a git repo, or no first commit.** Every hook exits silently. Commit something first.
- **No `python3` on `PATH`.** The hooks exit silently. Install Python 3.9 or newer.
- **Questions, slash commands, greetings and "read/explain" requests** are not change requests, so
  the prompt hook stays quiet on purpose. After three nudges in one session it stops nudging.

## A run is stuck, or ended incomplete

`status` prints the outcome and exits with it: `0` verified, `3` pending, `4` incomplete, `5` failed.

| Outcome | Means | What to do |
|---|---|---|
| pending | A required receipt is missing or stale (the tree changed after it) | Run the steps again in `/compound-v:verify` |
| verified | Every required receipt is current and passing | Done |
| incomplete | A step could not run (no `test_cmd`/`live_cmd`, timeout, command not found, the step changed the tree, no reviewer run recorded), review rounds ran out with blocker/high findings open, or the budget was hit | Fix the named reason, then restart (below) |
| failed | A step ran and failed, and no review round is left | Fix it, then restart (below) |

The Stop hook refuses the first stop of an unverified run once, with the reason. The second stop
goes through and records the run `incomplete` or `failed`. An incomplete or failed run reopens by itself
when new evidence is written (a receipt, a review, a waiver or a stage move); a verified run stays closed.

**Restart** (optional) to finish the same work under a fresh run instead. Pass the closed run's `base_commit` so the
diff still covers the work, then re-attach the plan:

```bash
CV="python3 ${CLAUDE_PLUGIN_ROOT}/scripts/compound-v.py"
$CV run show --id <old-id>                       # note base_commit, spec and plan
$CV run start --tier full --base <base_commit> --spec <spec> --request-file - <<'REQUEST'
<the original request, verbatim>
REQUEST
$CV run plan  --id <new-id> --plan <plan>
$CV run stage --id <new-id> --to verify
```

Then run `/compound-v:verify`.

## A step errors with "gitignore what it writes"

The tests or live command left a file behind that git does not ignore (a report, a test database,
`coverage/`, Playwright's `test-results/` or `playwright-report/`). That changed the tree the receipt
was checking, so the CLI records `error`. Add the output to `.gitignore`, delete the stray files, and
run the steps again.

## The review is recorded as "no reviewer run recorded" or "stale review"

- **No reviewer run recorded.** With the Claude reviewer, the review only counts when it was done by
  the `compound-v:reviewer` subagent after `checkout`: the `SubagentStop` hook is what records that
  it ran. Run `checkout --dest <tmp>/tree`, dispatch `compound-v:reviewer` on that checkout, then
  `review record`. A review written in the main session, or by another agent type, does not count.
- **Stale review.** The tree changed between `checkout` and `review record`. Keep the findings file
  outside the repo (`review record` copies it in), and edit nothing while the review runs.

## The browser check cannot start: Playwright browsers are missing

`receipt live` fails with Playwright's "Executable doesn't exist" message when the browser binaries
are not installed. Install them yourself, outside any sandbox that blocks the download:

```bash
npx playwright install chromium
```

If a browser cannot run at all on this machine, verify asks you once whether to waive the check and
records your words with `waive live`. A browser test that runs and fails is a failure, never a
reason to waive.

## Two brainstorms start on the same request

Superpowers and Compound V both have a brainstorm skill, and both fire. Compound V does not call or
defer to Superpowers. Disable Superpowers for this project only, in `.claude/settings.json`:

```json
{"enabledPlugins": {"superpowers@claude-plugins-official": false}}
```

`/compound-v:init` offers exactly this change when it finds Superpowers enabled. Check the result with
`claude plugin list` inside the project.

## Two reviewers fire at stop

The Codex plugin's stop-review gate and Compound V's Stop hook both act at stop. `/compound-v:init`
warns when it finds the gate on; turn it off for the project with `/codex:setup --disable-review-gate`.
