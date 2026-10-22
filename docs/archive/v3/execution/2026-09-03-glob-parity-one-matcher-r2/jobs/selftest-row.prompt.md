# Task A — the fail-closed selftest row (no private bytecode cache ⇒ unavailable, nothing loaded)

Compound V run `2026-09-03-glob-parity-one-matcher-r2`, job `selftest-row`.

Implement Task A of docs/superpowers/plans/2026-09-03-epic-gp-one-matcher-r2.md exactly (the row is in the plan, Step 1) and run its Step 2 proof and Step 3 selftests. Only scripts/compound-v-memory.py may change, and only inside _selftest. Report in your summary the exact output line of the guardless-copy run. Commit in your worktree.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `scripts/compound-v-memory.py`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- The new row passes on the real file and FAILS on the guardless copy (plan Step 2, reproduced and reported in your summary); both selftests pass; the diff touches only _selftest.

Turn cap: 50 (default for tier standard; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
