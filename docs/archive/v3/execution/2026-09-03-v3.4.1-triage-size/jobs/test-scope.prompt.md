# Task C — the tests a SCOPED job owes: referencing tests, capped, never the whole suite at SCOPED/DIRECT

Compound V run `2026-09-03-v3.4.1-triage-size`, job `test-scope`.

Implement plan Task C against spec §WS-C. Tests first. FULL keeps today's rule (unmapped ⇒ full_command). For SCOPED and DIRECT an unmapped path resolves to the referencing tests (cap 5 beyond impacted) else the floor only — never to full_command and never to nothing. `resolve_from_manifest` passes the manifest's triage.tier and computes `referencing` from the worktree; the worker-side contract validator must accept the new label and `selected_count`. Run python with -B; register your lane with a literal --cwd.

## Write-allowed (your lane — anything else is a scope violation)

- `scripts/compound-v-fastpath-run.py`
- `tests/v2.9-e2e/test_fastpath_and_escalation.py`
- `skills/compound-v/execution-manifest.md`
- `agents/spec-reviewer.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- /usr/bin/python3 -B scripts/compound-v-fastpath-run.py --selftest and /usr/bin/python3 -B -m unittest tests/v2.9-e2e/test_fastpath_and_escalation.py are green and the unittest file carries the five cases of plan Task C Step 1 (grep for "referencing").
- referencing_tests(repo, changed_paths, cap=5) exists, is language-agnostic, bounded, sorted and capped; resolve_test_commands accepts tier= and referencing=; slice carries selected_count and the label impacted+referencing when the heuristic contributed.
- execution-manifest.md and agents/spec-reviewer.md §3.3 state what a SCOPED job owes (floor + impacted + ≤5 referencing, never full_command).

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
