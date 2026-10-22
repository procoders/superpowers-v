# Review Gate — three passes against the spec and the feature acceptance criteria

Compound V run `2026-09-03-verification-index-review-index-r3`, job `spec-review-2`.

Your agent definition carries the three-pass Review Gate and a Step 0 (V-memory recall). Follow it. This is the SECOND pass over F1 of epic 2026-09-03-verification-index: read review-1 (ISSUES) and this run's two jobs as new code; reproduce issue 1 against the merged script with a crafted line; run the r1 acceptance criteria as corrected here. Your own review files land in docs/superpowers/dogfood/ after the index was generated — say so; F2's run regenerates the index. Write docs/superpowers/dogfood/2026-09-03-epic-vi-review-index-review-2.md. Run python with -B; register your lane with a literal --cwd.

Prerequisites, already merged and COMMITTED into your base before this worktree was created: index-output.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-03-epic-vi-review-index-review-2.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- The review-2 file exists with ## Recall, ## SPEC, ## QUALITY, ## INTEGRATION, ## Verdict; for each of review-1's seven items it states closed or open with the command and output that proves it (item 2 is closed by this manifest's corrected acceptance_criteria[1]; item 6 is a recorded follow-up; item 7 is advisory); every feature-level acceptance criterion is re-run on the merged tree; the verdict is APPROVED or ISSUES with a numbered list.

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
