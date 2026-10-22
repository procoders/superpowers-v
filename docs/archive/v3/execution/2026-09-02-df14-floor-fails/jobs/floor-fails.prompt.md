# Writes correctly; the floor fails underneath it

Compound V run `2026-09-02-df14-floor-fails`, job `floor-fails`.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-02-df14-floor.md`

## Read-allowed (advisory — git cannot enforce reads)

- `docs/superpowers/execution/2026-09-02-df14-floor-fails/spec.md`

## Acceptance (your definition of done)

- The file exists; the floor is expected to fail.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
