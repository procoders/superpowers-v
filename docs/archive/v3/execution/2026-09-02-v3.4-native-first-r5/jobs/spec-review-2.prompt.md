# Review Gate — three passes against the spec and the feature-level acceptance criteria

Compound V run `2026-09-02-v3.4-native-first-r5`, job `spec-review-2`.

Your agent definition carries the three-pass Review Gate and a Step 0 (V-memory recall).
Follow it. This is the SECOND pass. Read docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review.md (the first pass, ISSUES 1-8) and verify each was closed by run r5's review-fixes job (ISSUE 4 was resolved by a spec amendment: the marker stays). Then review the merged result of runs r2, r4 and r5 against
docs/superpowers/specs/2026-09-02-v3.4-native-first-design.md and the manifest's
acceptance_criteria. Run the commands the criteria name (tests, greps, selftests with
/usr/bin/python3) rather than trusting summaries. Write
docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review-2.md with sections
## Recall, ## SPEC, ## QUALITY, ## INTEGRATION, ## Verdict (APPROVED or ISSUES with a
numbered list). Report what you found, not what would be reassuring.

Prerequisites, already merged and COMMITTED into your base before this worktree was created: review-fixes.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review-2.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- The review-2 file exists with SPEC, QUALITY, INTEGRATION and Verdict sections; it states, per ISSUE 1-8 of the first pass, closed or still open with evidence.
- The verdict is APPROVED or ISSUES with a numbered list.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
