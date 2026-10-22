You are job **task-4-vinit** of Compound V run `2026-07-10-research-grounded-brainstorm`. You work in an ISOLATED GIT WORKTREE at `/private/tmp/compound-v/2026-07-10-research-grounded-brainstorm/task-4-vinit` — do ALL file operations under that absolute path. Do NOT touch the main tree at `/Users/oleg/Dev/superpowers-v`. Do NOT run `git commit` or `git push` — leave every change uncommitted in the worktree; the orchestrator runs the scope gate, merges, and commits.

READ FIRST (inside the worktree):
1. `docs/superpowers/plans/2026-07-10-research-grounded-brainstorm.md` → **"### Task 4"** — execute exactly (JSON blocks are given verbatim).
2. Archaeology audit §1c + §2 (the committed-policy vs machine-local-capability split is LOAD-BEARING — v2.6.2 incident; `brainstorm.*` → Step 4a JSON at L273-293, `deep_research` presence → Step 4b JSON at L341-350, advisory-only).
3. Library-audit M2/M3 (presence-check keys on the available-skills listing, never a version gate, never a hardcoded `Workflow({...})` call; flag can go stale via `disableBundledSkills` — fire-time live re-check is the contract).

SCOPE LOCK — write_allowed (any other write = BLOCKED):
- `commands/v-init.md`

VERIFY: both JSON snippets you add parse (`jq` with a wrapper object); the 4a/4b placement matches the existing surrounding keys; the honest cost/egress line from the plan's offer-copy skeleton appears in the new Step 3 question.

Return: summary + verification output. No fabricated metrics; report honestly.
