# Review Gate — three passes against the spec and the feature acceptance criteria

Compound V run `2026-09-03-glob-parity-matcher-docs-r2`, job `spec-review-1`.

Your agent definition carries the three-pass Review Gate and a Step 0 (V-memory recall). Follow it. Feature F2 matcher-docs of epic 2026-09-03-glob-parity: spec docs/superpowers/execution/epics/2026-09-03-glob-parity/specs/matcher-docs.md (read its Amendment section), plan docs/superpowers/plans/2026-09-03-epic-gp-matcher-docs.md. Review the merged diff of job docs-contract (attempt 2; the attempt-1 review is docs/superpowers/dogfood/2026-09-03-epic-gp-matcher-docs-review-1.md — state whether each of its 2 SPEC_GAP and 3 CONSTRAINT_VIOLATION items is closed). Run /usr/bin/python3 scripts/lint-frontmatter.py yourself and check every relative link in the two files resolves. Write docs/superpowers/dogfood/2026-09-03-epic-gp-matcher-docs-r2-review-1.md and nothing else.

Prerequisites, already merged and COMMITTED into your base before this worktree was created: docs-contract.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-03-epic-gp-matcher-docs-r2-review-1.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- The r2-review-1 file exists with

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
