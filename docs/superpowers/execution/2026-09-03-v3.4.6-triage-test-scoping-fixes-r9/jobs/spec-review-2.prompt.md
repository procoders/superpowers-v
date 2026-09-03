# Review Gate — three passes against the spec and the feature acceptance criteria

Compound V run `2026-09-03-v3.4.6-triage-test-scoping-fixes-r9`, job `spec-review-2`.

Your agent definition carries the three-pass Review Gate and a Step 0 (V-memory recall). Follow it within a HARD BUDGET of 40 tool calls. FIRST action after Step 0: create docs/superpowers/dogfood/2026-09-03-v3.4.6-triage-test-scoping-fixes-review-2.md with the section skeleton and fill it as you verify. This is the SECOND pass: read review-1 (docs/superpowers/dogfood/2026-09-03-v3.4.6-triage-test-scoping-fixes-review.md, ISSUES 7) and the closure commit 20866b2 (`git show 20866b2`), then confirm each of the seven items closed or open with one command each: (1) `grep -n 'test-timeout-sec' scripts/compound-v-emit-workflow.py` shows the flag is always passed with 480 when the manifest is silent; (2–4) the CHANGELOG paragraphs no longer claim the probe, the 900, or 66,677 B; (5) the finding-105 entry exists; (6) `_retire_run_lock` reads the phase itself and all three call sites are unconditional; (7) `resolve_test_commands` refuses a float and 541. Re-run the manifest's AC 2 timeout case and AC 5 bookkeeping case once each. Verdict APPROVED or ISSUES with a numbered list. Run python with -B; register your lane with a literal --cwd.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-03-v3.4.6-triage-test-scoping-fixes-review-2.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- The review-2 file exists with the five sections; each of review-1's seven items is shown closed or open with its command and output; AC 2 and AC 5 re-run; the verdict is APPROVED or ISSUES with a numbered list.

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
