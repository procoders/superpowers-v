# standard tier — execution

Compound V run `2026-09-02-df2-frontier`, job `tier-standard`.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-02-df2-standard.md`

## Read-allowed (advisory — git cannot enforce reads)

- `docs/superpowers/execution/2026-09-02-df2-frontier/spec.md`

## Acceptance (your definition of done)

- The file exists.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
