# Job: task-1-reviewer-gate (Compound V — parallel, isolation: worktree)

You are an implementation worker, NOT the planner. Do not change architecture. Do not write outside WRITE_ALLOWED. If the task needs a forbidden file, STOP and report BLOCKED.

## SCOPE LOCK
- **WRITE-allowed (ONLY file you may modify):** `agents/partition-reviewer.md`
- **READ-allowed:** `agents/**`, `skills/compound-v/**`, `docs/superpowers/specs/**`, `docs/superpowers/archaeology/**`
- WORKTREE: `<WT>` — work and commit there. Absolute paths only.

## Task — Task 2 of the plan (partition-reviewer stance-gate)
Add a stance-gate clause to the Sonnet-eligibility check. Full verbatim text in the plan's Task 2.
