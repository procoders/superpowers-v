# Task B4 — execution-manifest.md + parallel-dispatcher.md

Compound V run `2026-09-03-v3.4.6-triage-test-scoping-fixes-r4`, job `contract-docs`.

SHARED CONTRACT for the four checker-budget jobs (they run in parallel and must agree): the manifest key is `test_contract.timeout_s` — an int (never a bool) in 1..540, default 480 when absent; the per-job resolved slice (the JSON the worker gets as --test-contract-file / the Engine C gate reads) carries the same key `timeout_s`; a checker that exits 124 is recorded as tests.exit_code 124 plus a tests.failures[] entry `timeout after N s: <checker>`; the top-level failure_class is NEVER set by a test timeout. Implement the two-doc part of Task B of docs/superpowers/plans/2026-09-03-v3.4.6-triage-test-scoping-fixes.md. Read docs/superpowers/archaeology/2026-09-03-v3-4-6-triage-test-scoping-fixes.md §7 first. Tests first. Touch only your lane. Python 3.9 syntax. Run python with -B; register your lane with a literal --cwd. You are unattended: decide and return; if you approach your turn budget, commit what is complete and return a summary that says what is not.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `skills/compound-v/execution-manifest.md`
- `agents/parallel-dispatcher.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- execution-manifest.md documents test_contract.timeout_s (default 480 s, cap 540 s under the harness's 600 s foreground ceiling for one Bash call, per checker command, full_command/impacted/floor alike; a 124 is tests.exit_code + a `timeout after N s` failures entry, never failure_class), the FULL-tier note (an unmapped lane path runs full_command — map every lane path or budget the suite) and that run-dir bookkeeping / gitignored paths never promote the slice; agents/parallel-dispatcher.md's invocation template says `--test-timeout-sec <test_contract.timeout_s, default 480>` instead of the hardcoded 900; lint-frontmatter green.

Turn cap: 30 (default for tier light; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
