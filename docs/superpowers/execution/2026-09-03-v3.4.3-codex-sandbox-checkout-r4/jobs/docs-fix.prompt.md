# Task B' (claude) — the CHANGELOG's multi-model claim says what this run proves (review-1 issue 2)

Compound V run `2026-09-03-v3.4.3-codex-sandbox-checkout-r4`, job `docs-fix`.

Review pass 1 issue 2: CHANGELOG.md:11 claims 'UUID session id … end to end' which run r3 did not demonstrate (session_id was empty; finding 81 fixed it in Record afterwards). Rewrite that sentence so it claims exactly what r3 proved and says the session id is proven by r4 (this run). Touch only CHANGELOG.md. Run python with -B; register your lane with a literal --cwd.

## Write-allowed (your lane — anything else is a scope violation)

- `CHANGELOG.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- CHANGELOG.md's 3.4.3 section states the multi-model contract as PROVEN BY RUN r3 (worktree outside the repository; the scope gate measuring the worker's tree; exactly the lane merged) and names the session id as proven in r4 by the events-log read (finding 81) — no claim beyond what a run directory shows; /usr/bin/python3 -B scripts/lint-frontmatter.py . is green.

Turn cap: 50 (default for tier standard; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
