# Review Gate — three passes against the spec and the feature acceptance criteria

Compound V run `2026-09-03-v3.4.10-recall-to-action`, job `spec-review`.

Your agent definition carries the three-pass Review Gate and a Step 0 (V-memory recall). Follow it within a HARD BUDGET of 40 tool calls; FIRST action after Step 0: create docs/superpowers/dogfood/2026-09-03-v3.4.10-recall-to-action-review.md with the section skeleton and fill it as you verify. This run is SCOPED+ (flavor scoped_plus): you are the mandatory deep review; a Codex cross-model receipt follows at dispatch step 8 — say so. Review both jobs against the spec and the four acceptance criteria; confirm the bridge never loosens (no lower tier, no other backend, no test-slice change) and that an explicit model: pin is never touched. Run python with -B; register your lane with a literal --cwd. Verify the pre-flight MUSTs: the raise happens before resolve_job_model; TIER_RAISE is a new dict (no TIERS indexing); the subprocess has timeout=30; register-lane carries --recall-check-json; no match/case anywhere in the diff; quote the measured recall_check_ms from this run's own emit summary against the emit total.

Prerequisites, already merged and COMMITTED into your base before this worktree was created: emitter-recall, docs.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-03-v3.4.10-recall-to-action-review.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- The review file exists with the five sections; each acceptance criterion is run on the merged tree with the command and output (the emitter selftest's fixtures for AC 1–3); this is a SCOPED+ run: the review is the mandatory deep review and it states that a cross-model (Codex) receipt is still owed at dispatch step 8; the verdict is APPROVED or ISSUES with a numbered list.

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
