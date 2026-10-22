# Review Gate — three passes against the spec and the feature-level acceptance criteria

Compound V run `2026-09-02-v3.4-native-first-r6`, job `spec-review-3`.

Your agent definition carries the three-pass Review Gate and a Step 0 (V-memory recall).
Follow it. This is the THIRD pass. Read the two earlier passes,
docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review.md and
docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review-2.md. The second pass closed the
first's eight items and raised three record defects (stale architecture KB citations to deleted
scripts; two comments dating a fix to "3.4.1"; SKILL.md:39's "append task-outcomes.jsonl"). The
orchestrator closed those three directly (commit "fix(record): ...") and, separately, the scope gate
gained a bytecode carve-out (scripts/compound-v-scope-check.py is_bytecode_noise) after the second
pass's own file was refused for a scripts/__pycache__/*.pyc. Verify each of the three closures and
the carve-out's selftest, then run the acceptance commands on the whole merged tree
(runs r2, r4, r5 and the orchestrator's fixes): every tests/*.sh, every script --selftest with
/usr/bin/python3, the lint. Write docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review-3.md
with ## Recall, ## SPEC, ## QUALITY, ## INTEGRATION, ## Verdict (APPROVED or ISSUES with a numbered
list). Run python with `-B` so you write no bytecode. Report what you found, not what would be
reassuring.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review-3.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- The review-3 file exists with the five sections; it states, for each of the second pass's three items and the bytecode carve-out, closed or open with evidence; the verdict is APPROVED or ISSUES with a numbered list.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
