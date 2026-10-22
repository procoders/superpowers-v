# Review Gate — three passes against the spec and the feature acceptance criteria

Compound V run `2026-09-03-v3.4.6-triage-test-scoping-fixes-r7`, job `spec-review`.

Your agent definition carries the three-pass Review Gate and a Step 0 (V-memory recall). Follow it — within a HARD BUDGET of 50 tool calls: r6's reviewer spent 80 reading and wrote nothing. FIRST action after Step 0: create docs/superpowers/dogfood/2026-09-03-v3.4.6-triage-test-scoping-fixes-review.md with the section skeleton (## Recall, ## SPEC, ## QUALITY, ## INTEGRATION, ## Verdict) and fill each section as you verify, so a cap leaves a partial verdict rather than nothing. Scope: ONE diff range, `git diff eb581ce..HEAD -- scripts/ tests/ skills/compound-v/execution-manifest.md agents/parallel-dispatcher.md CHANGELOG.md` (skip docs/superpowers/execution/**). Verify the manifest's five acceptance_criteria with commands (AC 1 in a sandbox checkout via scripts/compound-v-sandbox-checkout.sh <dest> --empty-pre-eval; AC 2's timeout case with a sleeping checker under timeout_s 1; AC 5's bookkeeping-path rule with three .run.lock paths). Spot-check, do not re-derive: the two hand commits 24dc534 and ebbbaf7 (findings 110/113) — read only _lane_map_worktree_for and the JS gate branch; the emitter patch (7481d78) — read only its four hunks. State which parts the pipeline merged (r3 35e8ed0; r5 f36c1b2, 207ebe2; r6 6335253) and which the orchestrator applied by hand (7481d78, 24dc534, ebbbaf7). Verdict APPROVED or ISSUES with a numbered list. Run python with -B; register your lane with a literal --cwd.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-03-v3.4.6-triage-test-scoping-fixes-review.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- The review file exists with the five sections; every acceptance criterion is run on the merged tree with the command and output (AC 1 in a sandbox before/after, AC 2's timeout case, AC 5's bookkeeping rule); the hand-applied commits are named as such; the verdict is APPROVED or ISSUES with a numbered list.

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
