# Task B — the manifest `retry` block

Compound V run `2026-09-03-v3.4.8-workflow-retry`, job `validator-retry`.

Implement Task B of docs/superpowers/plans/2026-09-03-v3.4.8-workflow-retry.md. Mirror the existing `test_contract` block validation (grep `TEST_CONTRACT_ALLOWED_KEYS` and `_validate_test_contract`); read only those ranges. Touch only scripts/compound-v-validate-manifest.py. Read the pre-flight audits named in this manifest's audits block first (their §7 MUSTs bind). Tests first. Python 3.9 syntax. Run python with -B; register your lane with a literal --cwd. You are unattended: decide and return; if you approach your turn budget, commit what is complete and return a summary that says what is not.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `scripts/compound-v-validate-manifest.py`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- Optional top-level `retry: {max_attempts: int 1..3 (isinstance int, not bool), escalate_reviewer: bool}`; 0, 4, "3", a bool for the int, a non-bool for the flag and unknown keys refused with a violation naming the key; selftest cases; `--selftest` green; Python 3.9.

Turn cap: 50 (default for tier standard; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
