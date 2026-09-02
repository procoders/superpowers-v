# Review job — must spawn by role

Compound V run `2026-09-02-df12-reviewer-third`, job `spec-review`.

Prerequisites, already merged and COMMITTED into your base before this worktree was created: impl-slice.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-02-df12-reviewer-third-review.md`

## Read-allowed (advisory — git cannot enforce reads)

- `docs/superpowers/dogfood/2026-09-02-df12-reviewer-third-impl.md`

## Acceptance (your definition of done)

- The review file exists and names the file it reviewed.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
