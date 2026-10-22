# Review Gate — three passes against the spec and the feature acceptance criteria

Compound V run `2026-09-03-verification-index-readme-section-r2`, job `spec-review-2`.

Your agent definition carries the three-pass Review Gate and a Step 0 (V-memory recall). Follow it. This is the SECOND pass over F2 of epic 2026-09-03-verification-index: read review-1 (ISSUES, one item) and this run's two jobs as new code; confirm the `---` boundary is present on both sides of the section and that no other README line changed (`git diff <wave-1 commit>..HEAD -- README.md`); re-run the feature ACs as written in this manifest; compare the two numbers with the footer of docs/superpowers/dogfood/README.md in HEAD and state plainly that your own review file will not be counted until the next regeneration. Write docs/superpowers/dogfood/2026-09-03-epic-vi-readme-section-review-2.md. Run python with -B; register your lane with a literal --cwd.

Prerequisites, already merged and COMMITTED into your base before this worktree was created: readme-rule.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-03-epic-vi-readme-section-review-2.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- The review-2 file exists with ## Recall, ## SPEC, ## QUALITY, ## INTEGRATION, ## Verdict; review-1's issue 1 is shown closed with `grep -n '^---$' README.md` before/after; every feature-level acceptance criterion is re-run on the merged tree with command and output; the two numbers are compared with the footer in HEAD (the review notes its own file lands after the index); the verdict is APPROVED or ISSUES with a numbered list.

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
