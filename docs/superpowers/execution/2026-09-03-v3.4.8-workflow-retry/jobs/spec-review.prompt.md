# Review Gate — three passes against the spec and the feature acceptance criteria

Compound V run `2026-09-03-v3.4.8-workflow-retry`, job `spec-review`.

Your agent definition carries the three-pass Review Gate and a Step 0 (V-memory recall). Follow it within a HARD BUDGET of 50 tool calls; FIRST action after Step 0: create docs/superpowers/dogfood/2026-09-03-v3.4.8-workflow-retry-review.md with the section skeleton and fill it as you verify. Review the three jobs against docs/superpowers/specs/2026-09-03-v3.4.8-workflow-retry-design.md and this manifest's five acceptance criteria; confirm no timing claim is published; confirm implementers are never escalated. Run python with -B; register your lane with a literal --cwd. Verify explicitly: the emitted script has no Date.now/Math.random/new Date; withRetry handles a null resolution (not only a throw); the exhaustion reason text; the escalation uses the ladder map, never a literal 'fable'; implementers never escalated.

Prerequisites, already merged and COMMITTED into your base before this worktree was created: emitter-retry, validator-retry, docs.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-03-v3.4.8-workflow-retry-review.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- The review file exists with ## Recall, ## SPEC, ## QUALITY, ## INTEGRATION, ## Verdict; each acceptance criterion is run on the merged tree with the command and output (the stub-agent simulation via the emitter selftest; the validator cases); the verdict is APPROVED or ISSUES with a numbered list.

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
