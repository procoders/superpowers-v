# Review Gate — three passes against the spec and the feature acceptance criteria

Compound V run `2026-09-03-v3.4.8-workflow-retry-r2`, job `spec-review-2`.

Your agent definition carries the three-pass Review Gate and a Step 0 (V-memory recall). Follow it within a HARD BUDGET of 40 tool calls; FIRST action after Step 0: create docs/superpowers/dogfood/2026-09-03-v3.4.8-workflow-retry-review-2.md with the section skeleton and fill it as you verify. SECOND pass: read review-1 (docs/superpowers/dogfood/2026-09-03-v3.4.8-workflow-retry-review.md, ISSUES 1–5 + one low) and the closure commit (`git log -1 --format=%H --grep='v3.4.8 review-1 closure'`, `git show <sha>`); confirm each of items 1–5 closed or open with one command each: (1) execution-manifest.md/failure-policy.md/CHANGELOG say unclassified retry, signature withRetry(stage, jobId, fn); (2) schemas/job_result.schema.json has retries + escalated_from, Record writes them on the result (run `/usr/bin/python3 -B scripts/compound-v-emit-workflow.py --selftest` and `bash tests/test-engine-c-contract.sh`); (3) parallel-dispatcher.md says escalated_from: opus; (4) invariant 4 says deep|frontier / opus|fable; (5) 'requested', not 'measured'. Verdict APPROVED or ISSUES with a numbered list. Run python with -B; register your lane with a literal --cwd.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-03-v3.4.8-workflow-retry-review-2.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- The review-2 file exists with the five sections; each of review-1's items 1–5 is shown closed or open with its command and output; the two suites re-run; the verdict is APPROVED or ISSUES with a numbered list.

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
