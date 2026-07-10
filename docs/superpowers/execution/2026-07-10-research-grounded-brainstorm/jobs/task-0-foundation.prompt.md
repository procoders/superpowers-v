You are job **task-0-foundation** of Compound V run `2026-07-10-research-grounded-brainstorm` (repo `/Users/oleg/Dev/superpowers-v`, branch `v2.7-brainstorm-recon`). You work DIRECTLY in the main working tree — this is the serial foundation job; nothing races you.

READ FIRST: `docs/superpowers/plans/2026-07-10-research-grounded-brainstorm.md` — your task is **"### Task 0"**. Execute its steps exactly, including the verbatim CHANGELOG entry (heading separator is an em-dash `—`, match the existing headings) and the CI-guard YAML snippet (indent to match the sibling steps in `.github/workflows/validate.yml`).

SCOPE LOCK — write_allowed (writing ANY other file = BLOCKED, the run halts):
- `.claude-plugin/plugin.json`
- `.claude-plugin/marketplace.json`
- `CHANGELOG.md`
- `.github/workflows/validate.yml`
- `.gitignore`

VERIFY per plan Step 5 (all three version probes must print `2.7.0`), plus simulate the new guard locally (run its shell body — it must pass).

THEN COMMIT exactly per plan Step 6 — **your commit is mandatory**: the parallel batch's worktrees are created at your committed HEAD. Do NOT push. No token/cost numbers anywhere.

Return: files changed, verification output, commit sha. Report failures honestly — never claim a check passed that didn't run.
