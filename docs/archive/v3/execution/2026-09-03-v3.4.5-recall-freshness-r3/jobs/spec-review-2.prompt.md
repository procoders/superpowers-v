# Review Gate — three passes against the spec and the feature acceptance criteria

Compound V run `2026-09-03-v3.4.5-recall-freshness-r3`, job `spec-review-2`.

Your agent definition carries the three-pass Review Gate and a Step 0 (V-memory recall). Follow it and quote Step 0's stderr (the refresh line, or its absence — nothing should be stale after this run's own bookkeeping commit... unless it is: say which). This is the SECOND pass over v3.4.5: read review-1 (ISSUES 2 + 3 recorded items) and engine-2 (merged in r2 as 233e6f7) and this run's docs-3 as new code; confirm items 1–5 closed with evidence (`grep` for the retired warning string across skills/ commands/ agents/; the finally; the single hash pass — count calls to file_sha per search with a quick instrumented run; the lock-held selftest present and green); re-run the four ACs as corrected in this manifest. Write docs/superpowers/dogfood/2026-09-03-v3.4.5-recall-freshness-review-2.md. Run python with -B; register your lane with a literal --cwd. Also record, from docs/superpowers/execution/2026-09-03-v3.4.5-recall-freshness-r2/receipts/docs-2.gate.json, that docs-2's refusal was a full_command rc 124 (checker cap TEST_TIMEOUT_S=300 in compound-v-fastpath-run.py) and not a diff problem — finding 102, fixed in the next cycle, not this run.

Prerequisites, already merged and COMMITTED into your base before this worktree was created: docs-3.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-03-v3.4.5-recall-freshness-review-2.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- The review-2 file exists with ## Recall, ## SPEC, ## QUALITY, ## INTEGRATION, ## Verdict; Step 0's own search stderr is quoted; review-1's items 1–5 are each shown closed (or open) with the command and output; every acceptance criterion of this manifest is re-run on the merged tree; the verdict is APPROVED or ISSUES with a numbered list.

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
