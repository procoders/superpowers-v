# Task B — test_contract.timeout_s; rc 124 ⇒ failure_class timeout (finding 102)

Compound V run `2026-09-03-v3.4.6-triage-test-scoping-fixes`, job `checker-budget`.

Implement Task B of docs/superpowers/plans/2026-09-03-v3.4.6-triage-test-scoping-fixes.md as amended (spec Parts 2 and 3 plus the 'Decisions forced by pre-flight 1A/1C' section). Read docs/superpowers/archaeology/2026-09-03-v3-4-6-triage-test-scoping-fixes.md §7 first: it names every hop (resolve_test_commands → _cmd_test_floor → run_test_floor; tc_run in the five workers; _tests_block_from_floor; parallel-dispatcher.md) and why a test timeout must never set the top-level failure_class. Tests first. Touch only your lane. Run python with -B; register your lane with a literal --cwd. You are unattended: decide and return.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `scripts/compound-v-fastpath-run.py`
- `scripts/compound-v-validate-manifest.py`
- `scripts/compound-v-emit-workflow.py`
- `scripts/compound-v-run-codex-worker.sh`
- `scripts/compound-v-run-antigravity-worker.sh`
- `scripts/compound-v-run-cursor-worker.sh`
- `scripts/compound-v-run-opencode-worker.sh`
- `scripts/compound-v-run-devin-worker.sh`
- `skills/compound-v/execution-manifest.md`
- `tests/test-engine-c-contract.sh`
- `agents/parallel-dispatcher.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- Per the plan's Task B as amended by pre-flight 1A/1C: validate-manifest accepts timeout_s as int-not-bool in 1..540 (selftest accept 480; refuse 0/-1/541/true/"480"); fastpath-run: TEST_TIMEOUT_S=480, resolve_test_commands copies timeout_s into the slice, _cmd_test_floor passes it to run_test_floor, a 124 records tests.exit_code 124 + failures entry `timeout after N s: <checker>` (selftest with sleep 2 under timeout_s 1), NO failure_class change; finding 105: unmapped⇒full promotion skips docs/superpowers/execution/** and gitignored paths with a contract note (selftest: 1 mapped + 3 .run.lock paths ⇒ impacted); emit-workflow: _tests_block_from_floor reads floor['reasons'], the finalizer deletes .run.lock with the lane map at MERGED/BLOCKED (selftest), the slice carries timeout_s and external workers get --test-timeout-sec from it; all five workers' tc_validate accept timeout_s (number ≥ 1, existing jq idiom) and tc_run read it, byte-identical, bash 3.2, shellcheck clean; agents/parallel-dispatcher.md's template follows the contract; tests/test-engine-c-contract.sh gains accept+refuse rows; execution-manifest.md documents the key, the 540 cap under the 600 s harness ceiling, and the bookkeeping-path rule; named selftests green; Python 3.9 syntax.

Turn cap: 50 (default for tier standard; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
