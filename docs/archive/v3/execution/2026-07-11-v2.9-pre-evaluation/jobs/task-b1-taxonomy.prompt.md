You are an **implementation worker, NOT the planner**. Do not change architecture. Do not write
outside WRITE_ALLOWED. If the task needs a forbidden file, STOP and report `BLOCKED` with the path.

## Where you work (ISOLATION: git worktree)
Work **exclusively inside this git worktree** (a full checkout of the repo at the post-Task-0 commit):
  /Users/oleg/Dev/superpowers-v/.v29-worktrees/task-b1-taxonomy
ALL file edits go under that absolute path (e.g. `/Users/oleg/Dev/superpowers-v/.v29-worktrees/task-b1-taxonomy/scripts/...`). Read reference docs either from
the worktree or the main repo — both have the committed Task 0 outputs, plan, spec, and audits.
**Do NOT run any git commands** (no add/commit/worktree). Just edit files + run `python3`. The
dispatcher runs a git-derived scope gate on your worktree and merges your work back centrally.

## SCOPE LOCK
**WRITE-allowed (create/modify ONLY these, under $WT):**
- `scripts/compound-v-validate-taxonomy.py` (CREATE)
- `.claude/compound-v-impact-taxonomy.example.yaml` (CREATE)
**READ-allowed (context — do not modify):**
- `scripts/compound-v-taxonomy.py`, `scripts/compound-v-validate-manifest.py`
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
**Task B1 — Impact-taxonomy schema + example + validator.**

Create `scripts/compound-v-validate-taxonomy.py` and `.claude/compound-v-impact-taxonomy.example.yaml`.
Taxonomy shape:
- `version`
- `path_patterns: [{glob, difficulty_band, impact_band}]`
- `content_patterns: [{match, pattern_type, case, scan, kind, impact_band}]` where
  `kind ∈ {legal_copy, i18n_placeholder, feature_flag, config_literal, shared_token, a11y}`
  (**SIX** content kinds — shared_token & a11y are first-class taxonomy kinds because F2's post-diff
  re-check needs them; CR4-4).
- `sensitive_path_list: [glob]`
- a `churn: {exclude_paths: [glob], format_commit_patterns: [regex]}` block (single-sourced so D1
  reuses it, never invents its own excludes; CR4-10).

Validator requirements (delegate MATCHING semantics to the shared loader `compound-v-taxonomy.py` — do
not reimplement matching): soft-PyYAML + stdlib fallback (NEVER hard `import yaml`); bands must be
`low|medium|high`; an **unbounded regex is rejected** (reuse the loader's safe-subset validator);
missing `sensitive_path_list` fails; the `churn` block validates (globs + bounded regexes).

**Step-1 failing selftest:** missing `sensitive_path_list` fails; all six content kinds (incl.
shared_token/a11y) with explicit `pattern_type`/`case`/`scan` pass; bad band rejected; unbounded regex
rejected; churn block validates. Then write the example taxonomy with the four content surfaces
(cited 1B incidents: legal/compliance copy, i18n placeholders, feature-flag flips, config/constant
literals) + shared_token/a11y + a starter sensitive-path-list. Do NOT run git.
