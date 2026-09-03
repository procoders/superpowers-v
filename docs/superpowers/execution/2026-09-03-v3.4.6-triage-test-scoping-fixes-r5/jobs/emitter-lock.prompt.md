# Task B2b-ii — emit-workflow.py: the finalizer deletes .run.lock at a terminal phase

Compound V run `2026-09-03-v3.4.6-triage-test-scoping-fixes-r5`, job `emitter-lock`.

SHARED CONTRACT for the four checker-budget jobs (they run in parallel and must agree): the manifest key is `test_contract.timeout_s` — an int (never a bool) in 1..540, default 480 when absent; the per-job resolved slice (the JSON the worker gets as --test-contract-file / the Engine C gate reads) carries the same key `timeout_s`; a checker that exits 124 is recorded as tests.exit_code 124 plus a tests.failures[] entry `timeout after N s: <checker>`; the top-level failure_class is NEVER set by a test timeout. Implement ONLY the .run.lock retirement in scripts/compound-v-emit-workflow.py (Task B, finding 105): grep `_retire_lane_map` and read only that function and its call sites in the finalize path; delete <run>/.run.lock there at MERGED/BLOCKED; add the selftest next to the existing _retire_lane_map checks. Budget: at most 12 tool calls of reading. Touch only scripts/compound-v-emit-workflow.py. Run python with -B; register your lane with a literal --cwd. You are unattended: decide and return.

Prerequisites, already merged and COMMITTED into your base before this worktree was created: emitter-slice.

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

- emit-workflow.py: the wave finalizer deletes <run>/.run.lock in the same place _retire_lane_map runs at MERGED/BLOCKED; selftest asserts the lock is gone after a terminal finalize and present after a non-terminal one; `--selftest` green; nothing else changes.

Turn cap: 50 (default for tier standard; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
