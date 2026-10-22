# Review Gate — three passes against the spec and the feature-level acceptance criteria

Compound V run `2026-09-02-v3.4-native-first-r7`, job `spec-review-4`.

Your agent definition carries the three-pass Review Gate and a Step 0 (V-memory recall).
Follow it. This is the FOURTH pass. Read the three earlier passes under docs/superpowers/dogfood/
(…-review.md, …-review-2.md, …-review-3.md). The third pass raised three items, all in the scope
gate's bytecode carve-out: (1) the predicate dropped anything under __pycache__/; (2) three records
contradicted the code; (3) no CHANGELOG entry. The orchestrator closed them in commit
"fix(scope-gate): bytecode by extension only; the pipeline's own outcome streams leave the changed
set; records and CHANGELOG say so" — which ALSO added a second carve-out: the pipeline's own outcome
streams (docs/superpowers/memory/triage-outcomes.jsonl, worker-performance.jsonl) leave the changed
set, because the third pass's own file was refused as `contradicted` when Record's merge_pending
append landed between its gate and the authority. Review that commit as new code: reproduce the
third pass's payload.py/id_rsa probe against scripts/compound-v-scope-check.py and require BLOCK;
check the bookkeeping carve-out cannot be abused to land anything (merge-back applies only approved
paths); check .gitignore, the module docstring and CHANGELOG describe the code. Then run the
acceptance commands on the whole merged tree: every tests/*.sh, every script --selftest with
/usr/bin/python3 -B, the lint. Write docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review-4.md
with ## Recall, ## SPEC, ## QUALITY, ## INTEGRATION, ## Verdict (APPROVED or ISSUES with a numbered
list). Run python with -B. Report what you found, not what would be reassuring.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-02-v3.4-native-first-review-4.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- The review-4 file exists with the five sections; it states, for each of the third pass's three items and the two carve-outs, closed or open with evidence; the verdict is APPROVED or ISSUES with a numbered list.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
