You are job **task-3-liveness-jsonl** of Compound V run `2026-07-11-session-aware-workers` (repo `/Users/oleg/Dev/superpowers-v`, branch `v2.8.1-session-aware`).

READ FIRST: `docs/superpowers/plans/2026-07-11-session-aware-workers.md` — your task is **"### Task 3"**. The **Global Constraints** and **Shared Interface Contract** sections BIND you (session-id line, events-log path, job.log bridge, resume-eligibility rule). Audits: docs/superpowers/{library-audit,archaeology}/2026-07-11-session-aware-workers.md — all codex facts are LIVE-PROBED, cite don't reinvent.

SCOPE LOCK: write_allowed = exactly the "Task 3" row of the Partition Map. Any other write = BLOCKED, run halts.

MODE: ISOLATED WORKTREE at `/private/tmp/compound-v/2026-07-11-session-aware-workers/task-3-liveness-jsonl` — ALL ops under that absolute path; never touch the main tree; do NOT git commit/push (orchestrator gates+merges+commits).

Do NOT push. No fabricated metrics. Run EVERY verification step your task lists; report outputs verbatim; report failures honestly.
