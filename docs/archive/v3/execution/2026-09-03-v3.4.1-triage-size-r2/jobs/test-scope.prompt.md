# Task C (r2) — land the tests-a-SCOPED-job-owes patch: apply r1's sealed patch, verify, fix anything red

Compound V run `2026-09-03-v3.4.1-triage-size-r2`, job `test-scope`.

Task C was implemented in run 2026-09-03-v3.4.1-triage-size (job test-scope): its scope gate passed and its own selftests were green, but a test-contract row of the orchestrator's (the path form of `python -m unittest`) blocked the record, so the wave refused it and the sealed patch was kept. Your job: apply that patch exactly — `git apply --index docs/superpowers/execution/2026-09-03-v3.4.1-triage-size/jobs/test-scope.patch` from your worktree root (baseline differs by four merged sibling jobs and two orchestrator fixes; if a hunk fails, resolve it by hand within your lane and say so) — then read plan Task C and spec §WS-C and verify every acceptance item on the applied tree: /usr/bin/python3 -B scripts/compound-v-fastpath-run.py --selftest; /usr/bin/python3 -B -m unittest discover -s tests/v2.9-e2e -p test_fastpath_and_escalation.py (24 tests expected). Fix anything red inside your lane only. Do NOT re-implement from scratch; the patch is the work. Run python with -B; register your lane with a literal --cwd.

## Write-allowed (your lane — anything else is a scope violation)

- `scripts/compound-v-fastpath-run.py`
- `tests/v2.9-e2e/test_fastpath_and_escalation.py`
- `skills/compound-v/execution-manifest.md`
- `agents/spec-reviewer.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- scripts/compound-v-fastpath-run.py carries referencing_tests(repo, changed_paths, cap=5) and resolve_test_commands(..., tier=None, referencing=None); /usr/bin/python3 -B scripts/compound-v-fastpath-run.py --selftest is green.
- /usr/bin/python3 -B -m unittest discover -s tests/v2.9-e2e -p test_fastpath_and_escalation.py passes and the file carries the five referencing cases (grep -c referencing tests/v2.9-e2e/test_fastpath_and_escalation.py >= 5).
- skills/compound-v/execution-manifest.md and agents/spec-reviewer.md §3.3 state what a SCOPED job owes (floor + impacted + ≤5 referencing, never full_command).

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
