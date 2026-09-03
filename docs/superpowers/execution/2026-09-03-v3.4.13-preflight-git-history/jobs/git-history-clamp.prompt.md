# Task A — three read-only git forms in the pre-flight clamp; two checks narrowed, two added

Compound V run `2026-09-03-v3.4.13-preflight-git-history`, job `git-history-clamp`.

Implement Task A of docs/superpowers/plans/2026-09-03-v3.4.13-preflight-git-history.md exactly — the code blocks are in the plan (Step 1 replaces the clamp expression near line 212; Step 1b rewrites the docstring phrase and the clamp comment; Step 2 replaces the two named checks near line 500 and adds two). Run the plan's Step 3 commands and quote their output in your summary. Only scripts/compound-v-emit-preflight.py may change. Commit in your worktree.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `scripts/compound-v-emit-preflight.py`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- python3 scripts/compound-v-emit-preflight.py --selftest prints no FAIL line; an emitted script lists exactly Bash(git blame:*), Bash(git log:*), Bash(git show:*) as its git forms; only scripts/compound-v-emit-preflight.py changed.

Turn cap: 50 (default for tier standard; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
