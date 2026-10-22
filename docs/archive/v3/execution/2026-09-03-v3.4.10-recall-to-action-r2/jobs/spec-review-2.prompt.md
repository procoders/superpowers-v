# Review Gate — three passes against the spec and the feature acceptance criteria

Compound V run `2026-09-03-v3.4.10-recall-to-action-r2`, job `spec-review-2`.

Your agent definition carries the three-pass Review Gate and a Step 0 (V-memory recall). Follow it within a HARD BUDGET of 40 tool calls; FIRST action after Step 0: create docs/superpowers/dogfood/2026-09-03-v3.4.10-recall-to-action-review-2.md with the section skeleton and fill it as you verify. SECOND pass (SCOPED+ run: you are the mandatory deep review; the Codex receipt follows at dispatch step 8 — say so): read review-1 (docs/superpowers/dogfood/2026-09-03-v3.4.10-recall-to-action-review.md, ISSUES 3+2) and the closure commit (`git log -1 --format=%H --grep='v3.4.10 review-1 closure'`, `git show <sha>`); confirm each item closed or open with one command: (1) the emitted prompt section carries the four reading-budget clauses (run `--selftest` and grep the emitter for 'at most 20 reading calls'); (2) auto_tighten is read from .claude/compound-v.json with the manifest key as override (grep `_cfg_doc`); (3) memory.md's gate sentence names --no-recall; (4) the spec no longer claims the receipt carries recall_check; (5) review jobs are skipped in the recall loop. Re-run the emitter selftest and tests/test-engine-c-contract.sh. Verdict APPROVED or ISSUES with a numbered list. Run python with -B; register your lane with a literal --cwd.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-03-v3.4.10-recall-to-action-review-2.md`

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
