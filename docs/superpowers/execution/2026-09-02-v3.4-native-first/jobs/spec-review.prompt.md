# Review Gate — three passes against the spec and the feature-level acceptance criteria

Compound V run `2026-09-02-v3.4-native-first`, job `spec-review`.

Your agent definition carries the three-pass Review Gate and a Step 0 (V-memory recall).
Follow it. Review the merged result of run 2026-09-02-v3.4-native-first against
docs/superpowers/specs/2026-09-02-v3.4-native-first-design.md and the manifest's
acceptance_criteria. Run the commands the criteria name (tests, greps, selftests with
/usr/bin/python3) rather than trusting summaries. Write
docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review.md with sections
## Recall, ## SPEC, ## QUALITY, ## INTEGRATION, ## Verdict (APPROVED or ISSUES with a
numbered list). Report what you found, not what would be reassuring.

Prerequisites, already merged and COMMITTED into your base before this worktree was created: docs-release.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- The review file exists with SPEC, QUALITY and INTEGRATION sections, each naming the evidence it checked and a verdict APPROVED or ISSUES.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
