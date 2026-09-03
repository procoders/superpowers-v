# Review Gate — three passes; every row of the r2 review's constraint table re-checked

Compound V run `2026-09-03-glob-parity-matcher-docs-r3`, job `spec-review-1`.

Your agent definition carries the three-pass Review Gate and a Step 0 (V-memory recall). Follow it. Feature F2 matcher-docs attempt 3 of epic 2026-09-03-glob-parity: plan docs/superpowers/plans/2026-09-03-epic-gp-matcher-docs-r3.md; spec docs/superpowers/execution/epics/2026-09-03-glob-parity/specs/matcher-docs.md (read its two amendment sections). Review the merged diff of job docs-exact against 16786b7 (git diff 16786b7 -- skills/compound-v/memory.md skills/compound-v/execution-manifest.md). Re-check every row of the r2 review's section 1.3 constraint table. Write docs/superpowers/dogfood/2026-09-03-epic-gp-matcher-docs-r3-review-1.md and nothing else.

Prerequisites, already merged and COMMITTED into your base before this worktree was created: docs-exact.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-03-epic-gp-matcher-docs-r3-review-1.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- The r3 review file exists with

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
