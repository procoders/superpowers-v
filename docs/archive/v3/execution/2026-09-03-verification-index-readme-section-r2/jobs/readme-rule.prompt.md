# Task A' — the section's lower `blank / --- / blank` boundary (review-1 issue 1) and the numbers re-read from the refreshed footer

Compound V run `2026-09-03-verification-index-readme-section-r2`, job `readme-rule`.

Review pass 1 (docs/superpowers/dogfood/2026-09-03-epic-vi-readme-section-review.md) found ONE issue: the new `## Verification program` section was spliced in after the file's existing `---` and left `## Under the hood (for the curious)` with no horizontal rule above it (seven of eight `##` headings carry a `blank / --- / blank` boundary; archaeology §7.6). Fix: insert a blank line, `---`, and a blank line between the section's paragraph and `## Under the hood`. Do NOT remove the rule above the section. Then re-read the footer of docs/superpowers/dogfood/README.md (index-refresh ran first, so it now counts review-1) and update the sentence's two numbers to that footer verbatim (`N review files, A APPROVED`) — quote the footer line in your summary. Nothing else changes. Run python with -B; register your lane with a literal --cwd. You are unattended: decide and return.

Prerequisites, already merged and COMMITTED into your base before this worktree was created: index-refresh.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `README.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- README.md: a `blank / --- / blank` separator sits between the `## Verification program` paragraph and `## Under the hood (for the curious)`; the pre-existing `---` above the section stays; `grep -c '^---$' README.md` grows by exactly one; the section's two numbers equal the footer of docs/superpowers/dogfood/README.md as it is in HEAD after index-refresh (`Reviews: N · APPROVED: A`); no other README change; `/usr/bin/python3 -B scripts/lint-frontmatter.py .` green.

Turn cap: 30 (default for tier light; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
