# Task B1 — fastpath-run.py: budget from the slice, 124 ⇒ failures entry, bookkeeping paths never promote (findings 102 + 105)

Compound V run `2026-09-03-v3.4.6-triage-test-scoping-fixes-r3`, job `fastpath`.

SHARED CONTRACT for the four checker-budget jobs (they run in parallel and must agree): the manifest key is `test_contract.timeout_s` — an int (never a bool) in 1..540, default 480 when absent; the per-job resolved slice (the JSON the worker gets as --test-contract-file / the Engine C gate reads) carries the same key `timeout_s`; a checker that exits 124 is recorded as tests.exit_code 124 plus a tests.failures[] entry `timeout after N s: <checker>`; the top-level failure_class is NEVER set by a test timeout. Implement the fastpath-run.py part of Task B of docs/superpowers/plans/2026-09-03-v3.4.6-triage-test-scoping-fixes.md (spec Parts 2 and 3 + Decisions). Read docs/superpowers/archaeology/2026-09-03-v3-4-6-triage-test-scoping-fixes.md §7 first. Tests first. Touch only your lane. Python 3.9 syntax. Run python with -B; register your lane with a literal --cwd. You are unattended: decide and return; if you approach your turn budget, commit what is complete and return a summary that says what is not.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `scripts/compound-v-fastpath-run.py`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- TEST_TIMEOUT_S = 480; resolve_test_commands copies contract['timeout_s'] into the slice when present and, for the unmapped⇒full_command promotion only, ignores changed paths under docs/superpowers/execution/** and gitignored paths (one `git check-ignore --stdin` call) with a contract note `ignored N bookkeeping path(s) for the unmapped rule`; _cmd_test_floor passes test_timeout_s=slice_.get('timeout_s', TEST_TIMEOUT_S) into run_test_floor; a checker exiting 124 yields tests.exit_code 124 + a failures[] entry `timeout after N s: <checker>` and NO failure_class change; selftests: sleep-2 checker under timeout_s 1 ⇒ 124 + entry; slice without timeout_s ⇒ default; 1 mapped + 3 docs/superpowers/execution/x/.run.lock paths ⇒ impacted, not full; `--selftest` green.

Turn cap: 50 (default for tier standard; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
