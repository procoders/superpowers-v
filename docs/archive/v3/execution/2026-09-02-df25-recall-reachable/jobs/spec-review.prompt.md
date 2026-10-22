# Review job — spawned by role, must consult V-memory first

Compound V run `2026-09-02-df25-recall-reachable`, job `spec-review`.

Prerequisites, already merged and COMMITTED into your base before this worktree was created: impl-slice.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-02-df25-recall-reachable-review.md`

## Read-allowed (advisory — git cannot enforce reads)

- `docs/superpowers/dogfood/2026-09-02-df25-recall-reachable-impl.md`

## Acceptance (your definition of done)

- The review names the recall command it ran and what came back.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
