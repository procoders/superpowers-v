# Review Gate — three passes against the spec and the feature acceptance criteria

Compound V run `2026-09-03-verification-index-readme-section`, job `spec-review`.

Your agent definition carries the three-pass Review Gate and a Step 0 (V-memory recall). Follow it. This is F2 of epic 2026-09-03-verification-index (depends on F1 review-index, already merged): review the two jobs of this run as new code against the spec and this manifest's acceptance criteria; verify the numbers by reading both files; run `bash scripts/compound-v-dogfood-index.sh` and confirm `git diff --exit-code docs/superpowers/dogfood/README.md` (your worktree is a fresh checkout — say if the footer changed and whether the README numbers still match). Write docs/superpowers/dogfood/2026-09-03-epic-vi-readme-section-review.md. Run python with -B; register your lane with a literal --cwd.

Prerequisites, already merged and COMMITTED into your base before this worktree was created: readme-section.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-03-epic-vi-readme-section-review.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- The review file exists with ## Recall, ## SPEC, ## QUALITY, ## INTEGRATION, ## Verdict; each feature-level acceptance criterion is run on the merged tree with the command and output; the two numbers in README.md are compared against the footer of docs/superpowers/dogfood/README.md in HEAD (the review notes that its own file lands after the index and is not counted); the verdict is APPROVED or ISSUES with a numbered list.

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
