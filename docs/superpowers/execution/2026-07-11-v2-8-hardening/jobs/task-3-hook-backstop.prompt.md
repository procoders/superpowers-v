You are job **task-3-hook-backstop** of Compound V run `2026-07-11-v2-8-hardening` (repo `/Users/oleg/Dev/superpowers-v`, branch `v2.8-hardening`).

READ FIRST: `docs/superpowers/plans/2026-07-11-v2-8-hardening.md` — your task is **"### Task 3"**; the **Global Constraints**, **Shared Interface Contract**, and **Routing table** sections bind you. Constraint sources are the three audit docs in the plan header (cited as A#/E# in your task).

SCOPE LOCK: your write_allowed is EXACTLY the "Task 3" row of the plan's Partition Map. Any other write = BLOCKED; the run halts.

MODE: ISOLATED GIT WORKTREE at `/private/tmp/compound-v/2026-07-11-v2-8-hardening/task-3-hook-backstop` — ALL file operations under that absolute path; never touch the main tree; do NOT git commit/push (the orchestrator gates, merges, commits).

Do NOT push. No fabricated metrics. Run every verification step your task lists and report outputs verbatim; report failures honestly.
