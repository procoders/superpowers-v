# Review Gate — three passes against the spec and the feature acceptance criteria

Compound V run `2026-09-03-v3.4.6-triage-test-scoping-fixes-r4`, job `spec-review`.

Your agent definition carries the three-pass Review Gate and a Step 0 (V-memory recall). Follow it. Review these six jobs plus r3's merged localizer and fastpath (35e8ed0) as new code, PLUS the orchestrator's own hand-made engine fix in HEAD (commit 'engine-c: an implementer that returns nothing no longer voids its wave', findings 107–110: --impl-no-result, _lane_map_worktree_for, impl_no_result receipt tag, error status) — review it with the same three passes (r1's checker-budget was split into fastpath / validator-emitter / workers / contract-docs after its implementer hit the 80-turn cap, finding 108) against the spec and this manifest's acceptance criteria; reproduce AC 1 in a sandbox checkout before/after; reproduce the timeout classification with a sleeping checker under timeout_s 1; confirm the five workers refuse timeout_s 0. Write docs/superpowers/dogfood/2026-09-03-v3.4.6-triage-test-scoping-fixes-review.md. Run python with -B; register your lane with a literal --cwd.

Prerequisites, already merged and COMMITTED into your base before this worktree was created: validator, emitter, workers, contract-docs, changelog, contract-rows.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/superpowers/dogfood/2026-09-03-v3.4.6-triage-test-scoping-fixes-review.md`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- The review file exists with ## Recall, ## SPEC, ## QUALITY, ## INTEGRATION, ## Verdict; every acceptance criterion is run on the merged tree with the command and output — AC 1 in a sandbox checkout (scripts/compound-v-sandbox-checkout.sh <dest> --empty-pre-eval) against the merged tree AND against `git archive` of the pre-run commit; AC 2's timeout case reproduced with a sleeping checker; the verdict is APPROVED or ISSUES with a numbered list.

Turn cap: 80 (default for tier deep; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.
