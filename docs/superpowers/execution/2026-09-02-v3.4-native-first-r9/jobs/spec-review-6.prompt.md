# Review Gate — three passes against the spec and the feature-level acceptance criteria

Compound V run `2026-09-02-v3.4-native-first-r9`, job `spec-review-6`.

Your agent definition carries the three-pass Review Gate and a Step 0 (V-memory recall).
Follow it. This is the SIXTH pass. Read the five earlier passes under docs/superpowers/dogfood/.
The fifth pass raised three items (the lane guard failing open on folded-scalar manifests under a
PyYAML-less interpreter; the r8 clamp denial misdiagnosed as a continuation when it was "$PWD"
substitution; acceptance greps answered by splitting the literal). This run's job guard-honest
closed them. Review its merge as new code: drive hooks/lane-guard.sh yourself with the r5
manifest and an out-of-lane write under the default PATH — it must DENY; confirm the fallback
parser refuses a zero-job parse loudly; confirm the emitted register-lane carries no "$PWD" and the
prompt names substitution; confirm the definition-scoped grep. Then run the acceptance commands on
the whole merged tree with /usr/bin/python3 -B. Write
docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review-6.md with ## Recall, ## SPEC,
## QUALITY, ## INTEGRATION, ## Verdict (APPROVED or ISSUES with a numbered list). Report what you
found, not what would be reassuring.

Prerequisites, already merged and COMMITTED into your base before this worktree was created: guard-honest.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review-6.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- The review-6 file exists with the five sections; it states, for each of the fifth pass's three items, closed or open with evidence; the verdict is APPROVED or ISSUES with a numbered list.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
