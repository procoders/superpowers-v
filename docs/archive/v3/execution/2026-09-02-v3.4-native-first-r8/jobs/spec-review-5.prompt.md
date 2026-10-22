# Review Gate — three passes against the spec and the feature-level acceptance criteria

Compound V run `2026-09-02-v3.4-native-first-r8`, job `spec-review-5`.

Your agent definition carries the three-pass Review Gate and a Step 0 (V-memory recall).
Follow it. This is the FIFTH pass. Read the four earlier passes under docs/superpowers/dogfood/
(…-review.md … -review-4.md). The fourth pass raised four items on the scope gate's carve-outs;
this run's job gate-strict withdrew both carve-outs and moved the bookkeeping append after the
authority. Review gate-strict's merge as new code: re-run the fourth pass's forged-.pyc probe
against the merged tree (the guard must deny; the gate must BLOCK); check that no pipeline write
now lands between a direct-mode job's gate and its re-derivation; check the -B invariant in the
emitted commands, rules and prompts; check every record named. Then run the acceptance commands on
the whole merged tree with /usr/bin/python3 -B. Write
docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review-5.md with ## Recall, ## SPEC,
## QUALITY, ## INTEGRATION, ## Verdict (APPROVED or ISSUES with a numbered list). Report what you
found, not what would be reassuring.

Prerequisites, already merged and COMMITTED into your base before this worktree was created: gate-strict.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review-5.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- The review-5 file exists with the five sections; it states, for each of the fourth pass's four items, closed or open with evidence; the verdict is APPROVED or ISSUES with a numbered list.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
