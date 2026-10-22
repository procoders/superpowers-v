# Review Gate — three passes against the spec and the feature-level acceptance criteria

Compound V run `2026-09-02-v3.4-native-first-r12`, job `spec-review-9`.

Your agent definition carries the three-pass Review Gate and a Step 0 (V-memory recall).
Follow it. This is the NINTH and final pass of this cycle. Read the eight earlier passes under
docs/superpowers/dogfood/, and docs/superpowers/reviews/2026-09-03-codex-round-4-gate-changes.json (a
cross-model adversarial review with nine findings). This run's three jobs claim to close all nine
Codex findings and all six eighth-pass items. Review the merged tree as new code: reproduce Codex C1
(widen the manifest after emit → the gate refuses), C2 (a planted scripts/yaml.py does not widen the
parse), C3 (a worktree reverted after the gate is refused and not pruned), H1 (test byproducts after
the gate do not contradict the receipt), H3 (a sleeping python3 first on PATH → the hook returns
within its budget with a notice); check the eighth pass's six items with evidence. Report everything
in one pass, ranked. Then run the acceptance commands on the whole merged tree with
/usr/bin/python3 -B. Write docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review-9.md with
## Recall, ## SPEC, ## QUALITY, ## INTEGRATION, ## Verdict (APPROVED or ISSUES with a numbered list).
Run python with -B; register your lane with a literal --cwd.

Prerequisites, already merged and COMMITTED into your base before this worktree was created: patch-artifact, guard-hardening, records.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review-9.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- The review-9 file exists with the five sections; it states, for each of the nine Codex findings and the six eighth-pass items, closed or open with evidence; the verdict is APPROVED or ISSUES with a numbered list.

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
