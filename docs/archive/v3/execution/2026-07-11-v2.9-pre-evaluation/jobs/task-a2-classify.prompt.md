You are an **implementation worker, NOT the planner**. Do not change architecture. Do not write
outside WRITE_ALLOWED. If the task needs a forbidden file, STOP and report `BLOCKED` with the path.

## Where you work (ISOLATION: git worktree)
Work **exclusively inside this git worktree** (a full checkout of the repo at the post-Task-0 commit):
  /Users/oleg/Dev/superpowers-v/.v29-worktrees/task-a2-classify
ALL file edits go under that absolute path (e.g. `/Users/oleg/Dev/superpowers-v/.v29-worktrees/task-a2-classify/scripts/...`). Read reference docs either from
the worktree or the main repo — both have the committed Task 0 outputs, plan, spec, and audits.
**Do NOT run any git commands** (no add/commit/worktree). Just edit files + run `python3`. The
dispatcher runs a git-derived scope gate on your worktree and merges your work back centrally.

## SCOPE LOCK
**WRITE-allowed (create/modify ONLY these, under $WT):**
- `scripts/compound-v-classify-request.py` (CREATE)
**READ-allowed (context — do not modify):**
- `scripts/compound-v-resolve-model.py`, `scripts/compound-v-run-with-timeout.py`
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
**Task A2 — T3 classify as a PARENT-invoked Task contract (NOT Python→Claude).**

Create `scripts/compound-v-classify-request.py`. The pre-eval engine (A3, a later task) is
**T3-agnostic**: it accepts `--t3-category` and, if unset when T3 is needed, returns `needs_t3` with a
ready prompt; the **parent harness** runs ONE `light`-tier Task with that prompt, parses the enum, and
re-invokes the engine. This script provides:
(a) the **prompt builder** (bounded, tiny input: request text + resolved paths + taxonomy categories)
    + a **strict enum parser** used by the parent, and
(b) an **optional headless-codex route** for non-Claude harnesses (read-only sandbox, through the
    timeout supervisor, `stdin </dev/null`, bounded output).
`category ∈ {plumbing, user-facing-minor, user-facing-major, unknown}`. Any error/timeout/unparse/
non-enum reply → `unknown` → fail-closed FULL_PIPELINE.

CRITICAL (N1): this is **net-new** — `resolve-model.py` only RESOLVES a model name, it NEVER calls a
model. Do not call any model from Python on the Claude path; only the optional codex route spawns an
external CLI (through the timeout wrapper, closed stdin).

**Step-1 failing selftest:** the parser rejects a non-enum reply → `unknown`; the prompt builder emits
a bounded prompt; the codex route is invoked through the timeout wrapper with closed stdin — a fake-CLI
fixture proving backend selection, timeout, closed stdin, output bound, and unknown-on-error. Do NOT
run git.
