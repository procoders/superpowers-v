# dependent — must see wave 1's commit

Compound V run `2026-09-02-df2-frontier`, job `tier-summary`.

Prerequisites, already merged and COMMITTED into your base before this worktree was created: tier-frontier, tier-deep, tier-standard.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-02-df2-summary.md`

## Read-allowed (advisory — git cannot enforce reads)

- `docs/superpowers/dogfood/2026-09-02-df2-frontier.md`
- `docs/superpowers/dogfood/2026-09-02-df2-deep.md`
- `docs/superpowers/dogfood/2026-09-02-df2-standard.md`

## Acceptance (your definition of done)

- The file lists all three wave-1 files.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
