# Task B' (claude) — the CHANGELOG's multi-model claim says what this run proves (review-1 issue 2)

Compound V run `2026-09-03-v3.4.3-codex-sandbox-checkout-r5`, job `docs-fix`.

Your r4 twin did this work and passed its gate, but the wave was refused for a sibling's sake; its sealed patch is committed at docs/superpowers/execution/2026-09-03-v3.4.3-codex-sandbox-checkout-r5/jobs/docs-fix.r4.patch (repo-relative). In your worktree: `git apply --index docs/superpowers/execution/2026-09-03-v3.4.3-codex-sandbox-checkout-r5/jobs/docs-fix.r4.patch`, then verify the CHANGELOG sentence against the acceptance (it must claim exactly what r3 proved and say the session id is proven in THIS run, r5, by the events-log read). Fix wording by hand if the patch does not apply cleanly. Touch only CHANGELOG.md. Run python with -B; register your lane with a literal --cwd.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `CHANGELOG.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- CHANGELOG.md's 3.4.3 section states the multi-model contract as PROVEN BY RUN r3 (worktree outside the repository; the scope gate measuring the worker's tree; exactly the lane merged) and names the session id as proven in r5 by the events-log read (finding 81) — no claim beyond what a run directory shows; /usr/bin/python3 -B scripts/lint-frontmatter.py . is green.

Turn cap: 50 (default for tier standard; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
