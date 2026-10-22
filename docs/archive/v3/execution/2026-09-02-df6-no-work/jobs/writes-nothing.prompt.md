# Declares a lane, deliberately writes nothing

Compound V run `2026-09-02-df6-no-work`, job `writes-nothing`.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-02-df6-never-written.md`

## Read-allowed (advisory — git cannot enforce reads)

- `docs/superpowers/execution/2026-09-02-df6-no-work/spec.md`

## Acceptance (your definition of done)

- Nothing is written. This is a deliberate test of the no-work check.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
