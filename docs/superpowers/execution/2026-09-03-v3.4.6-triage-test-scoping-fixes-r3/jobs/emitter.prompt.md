# Task B2b — emit-workflow.py: slice carries timeout_s, --test-timeout-sec pass-through, receipt reads floor reasons, .run.lock retired at terminal

Compound V run `2026-09-03-v3.4.6-triage-test-scoping-fixes-r3`, job `emitter`.

SHARED CONTRACT for the four checker-budget jobs (they run in parallel and must agree): the manifest key is `test_contract.timeout_s` — an int (never a bool) in 1..540, default 480 when absent; the per-job resolved slice (the JSON the worker gets as --test-contract-file / the Engine C gate reads) carries the same key `timeout_s`; a checker that exits 124 is recorded as tests.exit_code 124 plus a tests.failures[] entry `timeout after N s: <checker>`; the top-level failure_class is NEVER set by a test timeout. Implement the emit-workflow.py part of Task B of docs/superpowers/plans/2026-09-03-v3.4.6-triage-test-scoping-fixes.md. The file is 6,000+ lines and two previous implementers ran out of turns READING it: do NOT read it top to bottom. grep for exactly these and read only them: the function that writes each job's test-contract slice (search `test_contract_file`), `_tests_block_from_floor`, `_retire_lane_map` and the finalize path that calls it, the external-launch argv builder (search `--test-timeout-sec`), and the selftest section around the existing `_retire_lane_map` / `_tests_block_from_floor` checks. Tests first. Touch only scripts/compound-v-emit-workflow.py. Run python with -B; register your lane with a literal --cwd. You are unattended: decide and return; if you approach your turn budget, commit what is complete and return a summary that says what is not.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `scripts/compound-v-emit-workflow.py`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- emit-workflow.py: the per-job resolved test-contract slice carries timeout_s when the manifest declares it; external workers are launched with --test-timeout-sec <timeout_s> (else the existing default); _tests_block_from_floor reads floor.get('reasons') so `timeout after N s: <checker>` reaches the gate receipt's tests block; the wave finalizer deletes <run>/.run.lock in the same place _retire_lane_map runs at MERGED/BLOCKED (selftest: gone after a terminal finalize, present after a non-terminal one); `--selftest` green (425+ checks today); nothing else in the file changes.

Turn cap: 50 (default for tier standard; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
