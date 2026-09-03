# Task B2a — validate-manifest.py accepts test_contract.timeout_s

Compound V run `2026-09-03-v3.4.6-triage-test-scoping-fixes-r4`, job `validator`.

SHARED CONTRACT for the four checker-budget jobs (they run in parallel and must agree): the manifest key is `test_contract.timeout_s` — an int (never a bool) in 1..540, default 480 when absent; the per-job resolved slice (the JSON the worker gets as --test-contract-file / the Engine C gate reads) carries the same key `timeout_s`; a checker that exits 124 is recorded as tests.exit_code 124 plus a tests.failures[] entry `timeout after N s: <checker>`; the top-level failure_class is NEVER set by a test timeout. Implement the validate-manifest.py part (ONLY — the contract-test rows are a separate job that runs after the workers merge) of Task B of docs/superpowers/plans/2026-09-03-v3.4.6-triage-test-scoping-fixes.md. Read only _validate_test_contract and TEST_CONTRACT_ALLOWED_KEYS in the validator (grep for them) — do not read the 2,500-line file top to bottom. Tests first. Touch only your lane. Run python with -B; register your lane with a literal --cwd. You are unattended: decide and return; if you approach your turn budget, commit what is complete and return a summary that says what is not.

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

- validate-manifest: TEST_CONTRACT_ALLOWED_KEYS += ('timeout_s',); _validate_test_contract accepts timeout_s iff isinstance(v,int) and not isinstance(v,bool) and 1 <= v <= 540, else a violation naming the key (selftest: accept 480; refuse 0, -1, 541, true, "480"); validate-manifest --selftest green; nothing else changes.

Turn cap: 50 (default for tier standard; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
