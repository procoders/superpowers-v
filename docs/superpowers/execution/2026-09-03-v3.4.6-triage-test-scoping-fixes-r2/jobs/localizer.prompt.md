# Task A — no content_scan_incomplete for a content-scan-excluded file (finding 99)

Compound V run `2026-09-03-v3.4.6-triage-test-scoping-fixes-r2`, job `localizer`.

Implement Task A of docs/superpowers/plans/2026-09-03-v3.4.6-triage-test-scoping-fixes.md; spec: docs/superpowers/specs/2026-09-03-v3.4.6-triage-test-scoping-fixes-design.md (Part 1). Read the pre-flight audits named in this manifest's audits block first. Tests first. Touch only scripts/compound-v-localize.py. Run python with -B; register your lane with a literal --cwd. You are unattended: decide and return. (r1's localizer did this correctly and its patch was sealed but never merged because a sibling job voided the wave — finding 107; redo it.)

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `scripts/compound-v-localize.py`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- _classify_paths calls tax.content_scan_excluded(taxonomy, path) before open(): an excluded path is neither read nor flagged (its taxonomy rows and sensitive flag still apply); the over-cap and unreadable branches stay for every other file; a NEW taxonomy fixture in the selftest covers: oversized scripts/big.py under content_scan_exclude **/*.py ⇒ exact, no content_scan_incomplete; the same file with no exclusion ⇒ the flag; oversized docs/big.md ⇒ the flag; no existing fixture rewritten (1A: _SHARED_TOKEN_TAXONOMY excludes nothing); the _is_generated content-marker tradeoff stated in a comment at the call site; localize + preeval selftests green; Python 3.9 syntax.

Turn cap: 50 (default for tier standard; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
