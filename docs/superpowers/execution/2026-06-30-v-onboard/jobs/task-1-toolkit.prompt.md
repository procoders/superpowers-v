# Job task-1-toolkit — compound-v-onboard.py (pack, Tier-1/2 gates, staleness, design-lint)

You are an **implementation worker, NOT the planner.** Do not change architecture. Do not write outside WRITE_ALLOWED. If the task needs a forbidden file, STOP and report BLOCKED.

## SCOPE LOCK
- **WRITE-allowed (the ONLY file you may modify/create):** `scripts/compound-v-onboard.py`
- **READ-allowed:** `scripts/**`, `docs/superpowers/specs/**`, `docs/superpowers/plans/**`, `docs/superpowers/library-audit/**`
- Worktree: you work in an ISOLATED git worktree. Stay inside it. Use ABSOLUTE paths.

## Task — implement plan Tasks 1→5 SERIALLY in the ONE file
`scripts/compound-v-onboard.py` is a single-owner serial file. Implement plan Tasks 1, 2, 3, 4, 5 IN ORDER (each adds a subcommand/function), following each task's TDD steps. Authority for exact code = `docs/superpowers/plans/2026-06-30-v-onboard.md` (Tasks 1–5).
