# Direct-mode writer — the shape that was blocked by our own files

Compound V run `2026-09-02-df2c-direct-retry`, job `direct-writer`.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-02-df2c-direct-retry.md`

## Read-allowed (advisory — git cannot enforce reads)

- `docs/superpowers/execution/2026-09-02-df2c-direct-retry/spec.md`

## Acceptance (your definition of done)

- The file exists and the gate passed.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
