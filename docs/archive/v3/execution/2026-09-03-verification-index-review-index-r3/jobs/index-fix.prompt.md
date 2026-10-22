# Task A' — verdict from the matched token, and three fixture gaps (review-1 issues 1, 3, 4, 5)

Compound V run `2026-09-03-verification-index-review-index-r3`, job `index-fix`.

Review pass 1 (docs/superpowers/dogfood/2026-09-03-epic-vi-review-index-review-1.md) found ISSUES: (1) the verdict value is taken by a bare substring scan of the whole line, APPROVED first — derive it from the token the anchored pattern matched; (3) no fixture for `## VERDICT: **ISSUES** (4)`; (4) the `^` anchor is unguarded — add a mid-sentence-only fixture expecting `unknown`; (5) case-insensitivity unguarded — add `verdict: approved`. Tests first, then the code. Touch only the script and its test. You are unattended: decide and return. Run python with -B; register your lane with a literal --cwd.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `scripts/compound-v-dogfood-index.sh`
- `tests/test-dogfood-index.sh`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- scripts/compound-v-dogfood-index.sh derives `verdict` from the token the ANCHORED alternation matched (a line `VERDICT: ISSUES — the earlier pass was approved` yields ISSUES), and tests/test-dogfood-index.sh asserts it; the fixture also carries `## VERDICT: **ISSUES** (4)` (row ISSUES), a file whose only verdict-shaped text is mid-sentence (row unknown), and a lowercase `verdict: approved` (row APPROVED); bash tests/test-dogfood-index.sh green under /bin/bash; shellcheck clean; bash 3.2 idioms only.

Turn cap: 50 (default for tier standard; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
