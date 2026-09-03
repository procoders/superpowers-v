# Task C — execution-manifest.md, failure-policy.md, CHANGELOG

Compound V run `2026-09-03-v3.4.8-workflow-retry`, job `docs`.

Implement Task C of docs/superpowers/plans/2026-09-03-v3.4.8-workflow-retry.md; describe the behaviour as the spec defines it (Tasks A and B run in parallel). Touch only your four files (agents/parallel-dispatcher.md added). Read the pre-flight audits named in this manifest's audits block first (their §7 MUSTs bind). Tests first. Python 3.9 syntax. Run python with -B; register your lane with a literal --cwd. You are unattended: decide and return; if you approach your turn budget, commit what is complete and return a summary that says what is not.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `skills/compound-v/execution-manifest.md`
- `skills/compound-v/failure-policy.md`
- `CHANGELOG.md`
- `agents/parallel-dispatcher.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- execution-manifest.md documents `retry` per the spec's Decisions (null trigger, deterministic table, retries[] in the result, requested escalation, fast-path out of scope, resume note) and corrects its reviewer-invariant paragraph (~lines 78-80) to deep-or-stronger (frontier/fable, 3.4.6); failure-policy.md says the policy applies inside Engine C (same table, no jitter, class unknown on the null path); parallel-dispatcher.md Step 2c gains the transient-exhaustion ⇒ reviewer-lift decision; CHANGELOG [Unreleased] has the entry (findings 118, 119) with no timing claim; lint green.

Turn cap: 30 (default for tier light; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
