# Review Gate — three passes against the retry plan and the sample-audit finding

Compound V run `2026-09-03-glob-parity-one-matcher-r2`, job `spec-review-1`.

Your agent definition carries the three-pass Review Gate and a Step 0 (V-memory recall). Follow it. Feature F1 one-matcher attempt 2 of epic 2026-09-03-glob-parity: plan docs/superpowers/plans/2026-09-03-epic-gp-one-matcher-r2.md, the finding under review docs/superpowers/execution/epics/2026-09-03-glob-parity/arbiter/one-matcher-1-sample-audit.md item 1. Review the merged diff of job selftest-row; reproduce the plan's Step 2 proof yourself. Write docs/superpowers/dogfood/2026-09-03-epic-gp-one-matcher-r2-review-1.md and nothing else.

Prerequisites, already merged and COMMITTED into your base before this worktree was created: selftest-row.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-03-epic-gp-one-matcher-r2-review-1.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- The review file exists with

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
