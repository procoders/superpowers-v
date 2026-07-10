You are job **task-3-skill-wiring** of Compound V run `2026-07-10-research-grounded-brainstorm`. You work in an ISOLATED GIT WORKTREE at `/private/tmp/compound-v/2026-07-10-research-grounded-brainstorm/task-3-skill-wiring` — do ALL file operations under that absolute path. Do NOT touch the main tree at `/Users/oleg/Dev/superpowers-v`. Do NOT run `git commit` or `git push` — leave every change uncommitted in the worktree; the orchestrator runs the scope gate, merges, and commits.

READ FIRST (inside the worktree):
1. `docs/superpowers/plans/2026-07-10-research-grounded-brainstorm.md` → **"### Task 3"** — execute exactly (description rewrite suggestion included there; you may improve the wording but the ≤500-char total is a hard CI gate).
2. Archaeology audit §3a (exact SKILL.md slots: description L3, When-Fires L59-83, overrides table L88-97, dir tree L179-203, integration row L234, caveat L46) and §3d (hook files + the zero-hook-backstop reality your caveat wording must state honestly).

SCOPE LOCK — write_allowed (any other write = BLOCKED):
- `skills/compound-v/SKILL.md`
- `hooks/session-banner.sh`
- `hooks/plan-saved-nudge.sh`

Notes: link the two new docs as `[phase-0-recon.md](phase-0-recon.md)` and `[brainstorm-elicitation.md](brainstorm-elicitation.md)` — sibling jobs create them; the links resolve at merge (do NOT create those files yourself; they are outside your scope). Add the Phase 0 announcement line beside the existing three.

VERIFY inside the worktree: `python3 scripts/lint-frontmatter.py` passes (it enforces the 500-char cap); `bash -n hooks/session-banner.sh hooks/plan-saved-nudge.sh` clean; report the exact final character count of the description.

Return: summary + verification output incl. the char count. No fabricated metrics; report honestly.
