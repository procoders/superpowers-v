# Task C — CHANGELOG [Unreleased] entries for findings 99 and 102

Compound V run `2026-09-03-v3.4.6-triage-test-scoping-fixes-r2`, job `changelog`.

Implement Task C of docs/superpowers/plans/2026-09-03-v3.4.6-triage-test-scoping-fixes.md. Describe the behaviour as the spec defines it (Tasks A and B implement it in parallel — do not wait for them). Touch only CHANGELOG.md. Run python with -B; register your lane with a literal --cwd. You are unattended: decide and return. (r1's changelog job was sealed but never merged — finding 107; redo it.)

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

- CHANGELOG [Unreleased] has two ### Fixed entries (findings 99, 102) with the measured numbers (66,677 vs 65,536 B; four-request sandbox probe; 340 s vs 300 s), what changes and what does not (non-excluded big files keep the flag; sensitive paths untouched; default budget 600 s); lint-frontmatter green.

Turn cap: 30 (default for tier light; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
