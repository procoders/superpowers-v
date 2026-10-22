# Task B3 — the five run-*-worker.sh: tc_validate accepts timeout_s, tc_run honours it

Compound V run `2026-09-03-v3.4.6-triage-test-scoping-fixes-r3`, job `workers`.

SHARED CONTRACT for the four checker-budget jobs (they run in parallel and must agree): the manifest key is `test_contract.timeout_s` — an int (never a bool) in 1..540, default 480 when absent; the per-job resolved slice (the JSON the worker gets as --test-contract-file / the Engine C gate reads) carries the same key `timeout_s`; a checker that exits 124 is recorded as tests.exit_code 124 plus a tests.failures[] entry `timeout after N s: <checker>`; the top-level failure_class is NEVER set by a test timeout. Implement the five-worker part of Task B of docs/superpowers/plans/2026-09-03-v3.4.6-triage-test-scoping-fixes.md ('fix them in all five, or in none'). Read docs/superpowers/archaeology/2026-09-03-v3-4-6-triage-test-scoping-fixes.md §7 first. Tests first. Touch only your lane. Python 3.9 syntax. Run python with -B; register your lane with a literal --cwd. You are unattended: decide and return; if you approach your turn budget, commit what is complete and return a summary that says what is not.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `scripts/compound-v-run-codex-worker.sh`
- `scripts/compound-v-run-antigravity-worker.sh`
- `scripts/compound-v-run-cursor-worker.sh`
- `scripts/compound-v-run-opencode-worker.sh`
- `scripts/compound-v-run-devin-worker.sh`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- In all five workers, byte-identically: tc_validate's jq predicate allows an optional `timeout_s` key that is a number >= 1 (existing has()/type== idiom, no `as $x |` binding) and refuses 0 or a non-number; tc_run reads .timeout_s from the contract file when present and uses it as the supervisor timeout instead of TEST_TIMEOUT_SEC (which stays the --test-timeout-sec fallback); bash 3.2 syntax; shellcheck clean on all five; a quick self-check in your summary: a contract file with timeout_s 480 passes tc_validate, with timeout_s 0 it dies.

Turn cap: 50 (default for tier standard; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
