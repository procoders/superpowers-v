# Task B2c — tests/test-engine-c-contract.sh rows for timeout_s (after workers merged)

Compound V run `2026-09-03-v3.4.6-triage-test-scoping-fixes-r6`, job `contract-rows`.

SHARED CONTRACT for the four checker-budget jobs (they run in parallel and must agree): the manifest key is `test_contract.timeout_s` — an int (never a bool) in 1..540, default 480 when absent; the per-job resolved slice (the JSON the worker gets as --test-contract-file / the Engine C gate reads) carries the same key `timeout_s`; a checker that exits 124 is recorded as tests.exit_code 124 plus a tests.failures[] entry `timeout after N s: <checker>`; the top-level failure_class is NEVER set by a test timeout. Add the timeout_s rows to tests/test-engine-c-contract.sh (Task B of docs/superpowers/plans/2026-09-03-v3.4.6-triage-test-scoping-fixes.md). The workers and validator jobs are in HEAD (merged in r5), so the rows must pass now; if one fails, the workers' validator is wrong — report exactly which worker and what it printed rather than weakening the row. Touch only the test file. Run python with -B; register your lane with a literal --cwd. You are unattended: decide and return.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `tests/test-engine-c-contract.sh`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- tests/test-engine-c-contract.sh gains rows that feed each of the five workers' tc_validate a resolved slice with timeout_s 480 (must be accepted) and timeout_s 0 (must be refused), in the file's existing per-worker extraction style; bash tests/test-engine-c-contract.sh green on the merged tree (workers and validator are in HEAD by the time you run).

Turn cap: 30 (default for tier light; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
