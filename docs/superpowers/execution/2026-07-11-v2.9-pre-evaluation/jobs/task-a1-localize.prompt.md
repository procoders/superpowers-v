You are an **implementation worker, NOT the planner**. Do not change architecture. Do not write
outside WRITE_ALLOWED. If the task needs a forbidden file, STOP and report `BLOCKED` with the path.

## Where you work (ISOLATION: git worktree)
Work **exclusively inside this git worktree** (a full checkout of the repo at the post-Task-0 commit):
  /Users/oleg/Dev/superpowers-v/.v29-worktrees/task-a1-localize
ALL file edits go under that absolute path (e.g. `/Users/oleg/Dev/superpowers-v/.v29-worktrees/task-a1-localize/scripts/...`). Read reference docs either from
the worktree or the main repo — both have the committed Task 0 outputs, plan, spec, and audits.
**Do NOT run any git commands** (no add/commit/worktree). Just edit files + run `python3`. The
dispatcher runs a git-derived scope gate on your worktree and merges your work back centrally.

## SCOPE LOCK
**WRITE-allowed (create/modify ONLY these, under $WT):**
- `scripts/compound-v-localize.py` (CREATE)
**READ-allowed (context — do not modify):**
- `scripts/compound-v-taxonomy.py`, `scripts/compound-v-run-with-timeout.py`
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
**Task A1 — Bounded read-only localization + committed localization artifact.**

Create `scripts/compound-v-localize.py`. Interface: `localize(request, repo, taxonomy) ->
{resolved_paths[], fan_out, flags[], confidence}` with `confidence ∈ {exact, ambiguous, failed}`.
It ALSO writes a committed **localization artifact** at
`docs/superpowers/pre-eval/<pre_eval_id>.localization.json` referenced by `fast_path.localization_ref`
(write-once — reject overwrite).

Requirements:
- Bounded resolution: resolve the symbol/selector/token via `rg → git grep → grep` **degrade order**
  (never hard-require ripgrep; C3). Hard cap on files inspected + a timeout. Cannot resolve within the
  cap → `ambiguous` (→ pre-eval override #1 → full pipeline). It is **bounded**, not mini-archaeology.
- Classify resolved paths via the **shared Taxonomy loader** (`compound-v-taxonomy.py` — do not
  reimplement matching): set `flags` such as `shared_token`, `is_generated`, `is_a11y_state`.
- **CR3-8 fake-CLI test (critical):** selftests MUST prove every fallback (`rg`/`git grep`/`grep`)
  routes through `compound-v-run-with-timeout.py` with `stdin=DEVNULL`, process-group termination,
  and **bounded output** (`--max-output-bytes`). An ordinary `subprocess.run(timeout=…)` MUST fail the
  test. Use fake-CLI fixtures on PATH to prove backend selection + closed stdin + output bound.
- **Step-1 failing selftest:** a shared-token CSS request (e.g. "make button X red" where the color is
  a global design token) → `confidence=exact`, `fan_out>1`, `flags` includes `shared_token`; the
  artifact file is written write-once.
Follow the Lifecycle protocol Phase-P step 1 (localization artifact is write-once, committed by the
dispatcher). Do NOT run git.
