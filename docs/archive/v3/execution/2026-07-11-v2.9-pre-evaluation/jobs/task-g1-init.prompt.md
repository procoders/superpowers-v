You are an **implementation worker, NOT the planner**. Do not change architecture. Do not write
outside WRITE_ALLOWED. If the task needs a forbidden file, STOP and report `BLOCKED` with the path.

## Where you work (ISOLATION: git worktree)
Work **exclusively inside this git worktree** (a full checkout of the repo at the post-Task-0 commit):
  /Users/oleg/Dev/superpowers-v/.v29-worktrees/task-g1-init
ALL file edits go under that absolute path (e.g. `/Users/oleg/Dev/superpowers-v/.v29-worktrees/task-g1-init/scripts/...`). Read reference docs either from
the worktree or the main repo — both have the committed Task 0 outputs, plan, spec, and audits.
**Do NOT run any git commands** (no add/commit/worktree). Just edit files + run `python3`. The
dispatcher runs a git-derived scope gate on your worktree and merges your work back centrally.

## SCOPE LOCK
**WRITE-allowed (create/modify ONLY these, under $WT):**
- `commands/v-init.md` (MODIFY — the ONLY file; /v:init writes .claude/compound-v.json inline in its own doc, there is NO separate init script)
**READ-allowed (context — do not modify):**
- `docs/superpowers/architecture/pre-eval-config.md`, `scripts/compound-v-project-config.py`
A `git diff`-derived scope gate BLOCKS this job if any path outside WRITE-allowed changed.

## REQUIRED reading (absolute paths; read the relevant parts fully)
- Plan (your task section + the **Lifecycle & commit-ordering protocol** + **Known integration
  constraints CR5-1..10**): /Users/oleg/Dev/superpowers-v/docs/superpowers/plans/2026-07-11-v2.9-pre-evaluation-plan.md
- Spec (§0 BINDING corrections; §2 truth-table + missing-data; Iron Invariants; the AC list):
  /Users/oleg/Dev/superpowers-v/docs/superpowers/specs/2026-07-11-v2.9-pre-evaluation-design.md
- Audits (binding design constraints):
  /Users/oleg/Dev/superpowers-v/docs/superpowers/archaeology/2026-07-11-v2.9-pre-evaluation.md
  /Users/oleg/Dev/superpowers-v/docs/superpowers/expert/2026-07-11-v2.9-pre-evaluation.md
  /Users/oleg/Dev/superpowers-v/docs/superpowers/library-audit/2026-07-11-v2.9-pre-evaluation.md
- Task 0 shared contracts you build on (already committed in your worktree): the shared taxonomy
  loader `scripts/compound-v-taxonomy.py` (load_taxonomy/match_path/match_content/classify), the
  timeout supervisor `scripts/compound-v-run-with-timeout.py` (now with `--max-output-bytes`),
  `scripts/compound-v-project-config.py`, the canonical schemas under `schemas/`, and the updated
  `skills/compound-v/state-machine.md` + `execution-manifest.md`.

## Binding constraints (MUST honor — from the three audits + Global Constraints)
- **Python 3.9-safe, stdlib-first.** Soft-PyYAML fallback — NEVER a hard `import yaml`.
- **Reuse the named Task 0 / existing primitives — do NOT recopy them.** Import/delegate to the
  shared loader, the timeout supervisor, `append_line` (update-memory.py), etc.
- **Every external CLI** (rg, git grep, grep, codex, git) MUST go through
  `scripts/compound-v-run-with-timeout.py` with `stdin` closed (DEVNULL) and bounded output — NEVER
  a bare `subprocess.run(timeout=...)` on an external CLI.
- **Fail-closed everywhere:** ambiguity / missing data / tier disagreement / unknown / parse failure
  → FULL_PIPELINE (or escalate). Never fail open.
- No fabricated cost/token metrics anywhere.

## Method — TDD (required)
Write the failing selftest FIRST (a `--selftest` mode is the repo convention), verify it fails,
implement, verify it passes. Run every selftest with `python3` before declaring done. Self-review.

## Report format (end your final message with exactly ONE token)
`DONE` / `DONE_WITH_CONCERNS` (list them) / `NEEDS_CONTEXT` (say what) / `BLOCKED` (name the file).
Include a short summary of what you built + selftest results.

---
## YOUR TASK
**Task G1 — /v:init owns the pre_eval.* config + remember-my-choice + revocation + off.**

Modify `commands/v-init.md` ONLY. `/v:init` seeds `.claude/compound-v.json` inline in its own doc
(Step 4a); there is no separate init script. Add the `pre_eval.*` config surface per
`docs/superpowers/architecture/pre-eval-config.md` (the Task 0 contract):
- Seeds `pre_eval.*` defaults (enabled true, fast_path `ask`|`off`, min_sample_count,
  fan_out_threshold, token_cap).
- A malformed value → **warn once → use default → NEVER auto-route** (invalid is never treated as an
  auto-route).
- `pre_eval.remember: {css-only: "fastpath", …}` per-category opt-in is **displayable and revocable**
  (revoke via /v:init or by editing config). AC-11: an explicit one-time per-category human opt-in,
  NOT a silent auto-route — every fail-closed override (sensitive path, shared_token, a11y, churn-hot,
  tier-disagreement, post-hoc diff escalation) STILL fires on a remembered category.
- `off` is a **hard kill-switch** (no offer, no fast-path, ever).
Default: not remembered (ask).

Since this is a command doc (`.md`, no runnable code), your "selftest" is a **verification fixture**:
document (and, where a snippet is inline, show) that (a) defaults are seeded, (b) a malformed value
warns→defaults→never auto-routes, (c) a remembered category is displayable+revocable, (d) `off` is a
hard kill-switch. Ensure frontmatter stays model-policy-clean (Opus/Sonnet only, never Haiku). Do NOT
run git.
