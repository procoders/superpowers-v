# Review Gate — three passes against the spec and the feature-level acceptance criteria

Compound V run `2026-09-02-v3.4-native-first-r10`, job `spec-review-7`.

Your agent definition carries the three-pass Review Gate and a Step 0 (V-memory recall).
Follow it. This is the SEVENTH pass. Read the six earlier passes under docs/superpowers/dogfood/.
The sixth pass raised four items (interpreter picked by [ -x ] not viability; a manifest count of
35 vs 46; the 47 ms hook cost carried forward across an interpreter change; two source-grepping
assertions). This run's job guard-viable closed them. Review its merge as new code: drive
hooks/lane-guard.sh with a broken python3 first on PATH and an out-of-lane write (must DENY and
log the interpreter); check the measured numbers in README/AGENTS/CHANGELOG against a measurement
of your own with the README recipe; check the test assertions assert behaviour. Then run the
acceptance commands on the whole merged tree with /usr/bin/python3 -B. Write
docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review-7.md with ## Recall, ## SPEC,
## QUALITY, ## INTEGRATION, ## Verdict (APPROVED or ISSUES with a numbered list). Report what you
found, not what would be reassuring. Run python with -B; register your lane with a literal --cwd.

Prerequisites, already merged and COMMITTED into your base before this worktree was created: guard-viable.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review-7.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- The review-7 file exists with the five sections; it states, for each of the sixth pass's four items, closed or open with evidence; the verdict is APPROVED or ISSUES with a numbered list.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
