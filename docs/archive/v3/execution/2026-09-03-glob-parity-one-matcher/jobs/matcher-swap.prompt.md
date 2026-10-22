# Task A — _file_matches delegates to the scope gate's matcher; parity selftest; unavailable on loader failure

Compound V run `2026-09-03-glob-parity-one-matcher`, job `matcher-swap`.

Implement Task A of docs/superpowers/plans/2026-09-03-epic-gp-one-matcher.md exactly (the code is in the plan): remove import fnmatch, add _SCOPE_CHECK_PATH/_SCOPE_MATCH/_scope_matches(), rewrite _file_matches to delegate to the scope gate matcher with the bare-path /** fallback, add the unavailable path at the top of recall_check, append the parity rows + the bare-dir and loader-failure checks to _selftest. Only scripts/compound-v-memory.py may change. Verify with python3 scripts/compound-v-memory.py --selftest and python3 scripts/compound-v-scope-check.py --selftest (both must pass) and grep -n fnmatch scripts/compound-v-memory.py (must print nothing). Commit in your worktree.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `scripts/compound-v-memory.py`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- python3 scripts/compound-v-memory.py --selftest passes with the parity rows of the plan (Task A Step 1) all ok; grep -n fnmatch scripts/compound-v-memory.py prints nothing; recall_check returns verdict unavailable with a note starting "scope-check matcher unavailable" when the sibling cannot be loaded.

Turn cap: 50 (default for tier standard; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
