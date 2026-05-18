---
description: Execute a Compound-V-ready plan via batched parallel Opus dispatch. Takes a plan path; runs partition-reviewer first, then if PASS dispatches Task 0 sequentially and the parallel batches concurrently.
---

You are about to execute **Phase 3** of Compound V — batched parallel dispatch — on the plan at `{{args}}`.

This replaces the default Superpowers `subagent-driven-development` sequential-implementer pattern with parallel batches (4-6 implementers per message) on Opus by default, Sonnet only where the Partition Map's justification holds.

## Steps

1. **Verify the plan exists** at the path in `{{args}}`. If `{{args}}` is empty, list plans in `docs/superpowers/plans/` and ask the user which to dispatch.

2. **Run the partition reviewer first** (Iron Rule #4: no execution without a verified Partition Map):
   - Dispatch `compound-v:partition-reviewer` with the plan path
   - If verdict is `FAIL` → STOP. Surface the failure to the user. Do not dispatch implementers.
   - If verdict is `PASS` → continue

3. **Dispatch the parallel dispatcher**:
   - Dispatch `compound-v:parallel-dispatcher` with:
     - Plan path
     - Partition-review verdict (PASS)
     - Audit paths: `docs/superpowers/{archaeology,expert,library-audit}/<topic>.md`
   - The dispatcher handles Task 0 sequentially, then the parallel batches, then reviewers, then final integration.

4. When the dispatcher returns its summary, hand off to `superpowers:finishing-a-development-branch`.

## Safety

- Do NOT dispatch implementers if partition-reviewer returned FAIL.
- Do NOT override the Sonnet eligibility from the Partition Map.
- Do NOT silently skip the final integration review.
