# Job task-0-engine — Extend the V-memory engine to index root onboarding files

You are an **implementation worker, NOT the planner.** Do not change architecture. Do not write outside WRITE_ALLOWED. If the task needs a file outside scope, STOP and report BLOCKED — do not improvise.

## SCOPE LOCK
- **WRITE-allowed (the ONLY files you may modify):**
  - `scripts/compound-v-memory.py`
- **READ-allowed (context):** `scripts/**`, `docs/superpowers/specs/**`, `docs/superpowers/plans/**`, `docs/superpowers/archaeology/**`
- You are running **directly on the `v-onboard` branch** (isolation: direct). Make ONLY the engine edit. Do NOT touch any other file. Do NOT commit (the dispatcher handles git after the scope gate) — actually, you SHOULD `git add scripts/compound-v-memory.py && git commit` per plan Task 0 Step 7, because this is a direct/serial job and the scope gate diffs against the recorded baseline `d543f76` (an in-tree commit is still diffed correctly). Commit only `scripts/compound-v-memory.py`.

## Task (plan Task 0 — implement EXACTLY via its TDD steps)
Extend the existing V-memory engine so the four root onboarding files become recallable, WITHOUT widening the docs glob and WITHOUT breaking the existing selftest.

This is the **shared foundation** every dependent job (toolkit, prose, wiring) consumes — correctness here is load-bearing.

### Design constraints (NON-NEGOTIABLE — from the archaeology audit)
1. **`tracked_files()` (`scripts/compound-v-memory.py:238`) must be EXTENDED, not replaced.** Add a scoped second `git ls-files -z -- AGENTS.md CLAUDE.md CONVENTIONS.md DESIGN.md` union alongside the existing `DOCS_REL` listing, inside the `_in_git_worktree` branch. Do **NOT** widen `DOCS_REL` (that would index the whole repo — catastrophic FTS bloat, risk R6). Preserve the fail-closed `return []` on git error (`:258`) and the worktree-only-trust-git rule. Keep the `.md`/`.jsonl` filter so the `.json` manifest stays out of the index.
2. **`doc_type_for()` (`:133`) must gain explicit cases for the four root files.** Today any non-`docs/superpowers/` single-segment path returns `parts[0]` (the filename itself: `AGENTS.md` → `"AGENTS.md"`). Map the four to clean labels: `agents`/`claude`/`conventions`/`design`. A non-onboarding root path (e.g. `README.md`) MUST still fall back to `parts[0]`.
3. Existing selftest assertions (around `:964-966`) MUST still pass. Add the NEW assertions in the SAME `_selftest()`.

### TDD steps (follow superpowers:test-driven-development — write the failing test FIRST)
Implement plan Task 0 Steps 1→6 exactly as written in `docs/superpowers/plans/2026-06-30-v-onboard.md`:
- **Step 1:** append the `doc_type_for` clean-label assertions (agents/claude/conventions/design) + the unchanged `README.md → "README.md"` assertion inside `_selftest()` before the final return.
- **Step 2:** run `python3 scripts/compound-v-memory.py --selftest` → confirm it FAILS on `doc_type root agents`.
- **Step 3:** implement the `ONBOARD_ROOT_DOC_TYPES` map + the `doc_type_for` body exactly as the plan specifies.
- **Step 4:** extend `tracked_files` with the scoped root-file `ls-files` union (the exact snippet in the plan), unioned into `rels` before the `.md`/`.jsonl` filter+sort.
- **Step 5:** append the `tracked_files unions roots` selftest (temp git repo helper from the plan).
- **Step 6:** run `python3 scripts/compound-v-memory.py --selftest` → confirm PASS, 0 failed, including ALL pre-existing assertions.
- **Step 7:** `git add scripts/compound-v-memory.py && git commit -m "feat(onboard): index root AGENTS/CLAUDE/CONVENTIONS/DESIGN in V-memory (Task 0)"`. Commit ONLY that one file.

## Acceptance (you must satisfy ALL)
- `tracked_files` unions root AGENTS/CLAUDE/CONVENTIONS/DESIGN via a SCOPED second `ls-files` (not a DOCS_REL widen).
- `doc_type_for` returns clean labels (agents/claude/conventions/design); existing selftest asserts still pass.
- `python3 scripts/compound-v-memory.py --selftest` is GREEN (0 failed).

## Self-review before DONE
- Confirm `DOCS_REL` was NOT widened. Confirm fail-closed `[]` path intact. Confirm `.json` still excluded by the filter. Confirm no file other than `scripts/compound-v-memory.py` changed (`git status --porcelain`).

## Status report (end your final message with EXACTLY one)
`DONE` / `DONE_WITH_CONCERNS` / `NEEDS_CONTEXT` / `BLOCKED` — followed by a 2-4 line summary: what you changed, the selftest result (paste the final `0 failed` line), and the commit SHA.
