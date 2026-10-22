# Task A — replace the attempt-2 row with a load-bearing one (spy on spec_from_file_location)

Compound V run `2026-09-03-glob-parity-one-matcher-r3`, job `load-bearing-row`.

Implement Task A of docs/superpowers/plans/2026-09-03-epic-gp-one-matcher-r3.md exactly: REPLACE the existing fail-closed block (from its leading comment through its check(...) call) with the plan's Step 1 block — do not add a second row. Run the plan's Step 2 proof (copy BOTH scripts/compound-v-memory.py and scripts/compound-v-scope-check.py into one scratch directory; the guardless copy must print FAIL for the row, the real copy ok) and Step 3 selftests. Only scripts/compound-v-memory.py may change, and only inside _selftest. Quote the REAL and GUARDLESS lines verbatim in your summary. Commit in your worktree.

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

- The plan's Step 2 proof reproduced with both files side by side, REAL ok / GUARDLESS FAIL lines quoted verbatim in your summary; both selftests pass; grep -c 'no private bytecode cache' scripts/compound-v-memory.py prints 1; the diff touches only _selftest.

Turn cap: 50 (default for tier standard; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
