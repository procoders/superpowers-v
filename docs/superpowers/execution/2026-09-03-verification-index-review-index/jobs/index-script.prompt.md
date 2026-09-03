# Task A — scripts/compound-v-dogfood-index.sh and tests/test-dogfood-index.sh

Compound V run `2026-09-03-verification-index-review-index`, job `index-script`.

Implement plan Task A (docs/superpowers/plans/2026-09-03-epic-vi-review-index.md) against the spec (docs/superpowers/execution/epics/2026-09-03-verification-index/specs/review-index.md). Test first — and read the spec's §Pre-flight amendments 1–5 before the regex: the corpus has `## VERDICT: …` headings, `VERDICT: **ISSUES**`, two-digit passes, and `-reviewer-…-impl.md` files that must not be rows; bash 3.2 idioms only, POSIX classes, `|| true` on every grep that may not match, `LC_ALL=C` on sorts, no `sed -i`. Do not write docs/superpowers/dogfood/README.md (Task B owns it). You are unattended: decide and return. Run python with -B; register your lane with a literal --cwd.

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

- bash tests/test-dogfood-index.sh is green and asserts every case of plan Task A Step 1 (three rows in date/pass order with ISSUES/APPROVED/unknown, the footer counts, byte-identical second run, non-zero exit with a message on a missing dir); shellcheck scripts/compound-v-dogfood-index.sh is clean; bash 3.2, set -eu, no python. The fixture includes a `## VERDICT: APPROVED` file, a `VERDICT: **ISSUES**` file, a two-digit pass (`-review-10.md`), a `-reviewer-x-impl.md` decoy that yields no row, and a file with no verdict line; the test runs the script with `/bin/bash` explicitly.

Turn cap: 50 (default for tier standard; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
