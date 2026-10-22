# Compound V v2.9 — Task 0: Shared foundation (serial, direct)

You are an **implementation worker, NOT the planner**. Do not change architecture. Do not write
outside WRITE_ALLOWED. If the task needs a forbidden file, STOP and report `BLOCKED` with the path.

## Repo
Work directly in the main repository at `/Users/oleg/Dev/superpowers-v` (isolation: direct, serial —
you are the only job running; every other job depends on you). Use absolute paths for everything.

## SCOPE LOCK
**WRITE-allowed (you may create/modify ONLY these):**
- `skills/compound-v/state-machine.md`
- `skills/compound-v/execution-manifest.md`
- `docs/superpowers/architecture/pre-eval-config.md`
- `scripts/compound-v-taxonomy.py`
- `scripts/compound-v-project-config.py`
- `scripts/compound-v-resolve-model.py`
- `scripts/compound-v-run-with-timeout.py`
- `schemas/pre-eval-record.schema.json`
- `schemas/fastpath-review-receipt.schema.json`

**READ-allowed (context — do not modify):** `skills/compound-v/**`,
`scripts/compound-v-validate-manifest.py`, `scripts/compound-v-scope-check.py`,
`scripts/compound-v-update-memory.py` (for `append_line` discipline reference),
`scripts/compound-v-memory.py`.

A `git diff`-derived scope gate runs after you finish and BLOCKS the job if any path outside the
WRITE-allowed set changed. Writing outside scope fails the whole run.

## REQUIRED reading before you code (absolute paths — read these fully)
- Spec: `/Users/oleg/Dev/superpowers-v/docs/superpowers/specs/2026-07-11-v2.9-pre-evaluation-design.md`
  — §0 pre-flight corrections are BINDING; §2 truth-table + missing-data table; Iron Invariants.
- Plan: `/Users/oleg/Dev/superpowers-v/docs/superpowers/plans/2026-07-11-v2.9-pre-evaluation-plan.md`
  — the **Lifecycle & commit-ordering protocol** is the single ordering authority; the **Known
  integration constraints CR5-1..10** are binding; the **Task 0** section is your exact spec.
- Audits (binding design constraints, inline below + read fully):
  `/Users/oleg/Dev/superpowers-v/docs/superpowers/archaeology/2026-07-11-v2.9-pre-evaluation.md`,
  `/Users/oleg/Dev/superpowers-v/docs/superpowers/expert/2026-07-11-v2.9-pre-evaluation.md`,
  `/Users/oleg/Dev/superpowers-v/docs/superpowers/library-audit/2026-07-11-v2.9-pre-evaluation.md`

## Your task (plan Task 0 — verbatim intent)
Create the shared contracts + shared loaders every downstream wave depends on. Deliver:

1. **`scripts/compound-v-taxonomy.py`** — the SINGLE shared loader/matcher module (no other task
   recopies it). API: `load_taxonomy`, `match_path`, `match_content`, `classify`. content_patterns
   declare explicit `pattern_type` (`literal|glob|regex`) / `case` / `scan`. **Regex is a documented
   SAFE SUBSET (no nested/overlapping quantifiers), deterministically validated, AND matched inside a
   killable subprocess via the timeout supervisor** (Python 3.9 `re` has no match timeout — CR2-7/
   AC-16). An adversarial nested-quantifier fixture MUST terminate within a fixed bound. `match_*`/
   `classify` return documented shapes. Soft-PyYAML + stdlib fallback, ONE import site — NEVER a hard
   `import yaml`.
2. **`scripts/compound-v-project-config.py`** — shared `load_project_config(repo)->dict` (fail-closed,
   reads `pre_eval.*` + `models`; malformed → raise so caller warns; CR2-11).
3. **`scripts/compound-v-resolve-model.py`** (MODIFY) — refactor `load_config_models` into a thin
   wrapper over `load_project_config`. **Behaviour-preserving**: `--selftest` must still pass and
   `--backend claude --tier deep`/`--tier standard` must still resolve to `opus` under `balanced`
   (the dispatcher calls this script between waves — do not break its CLI/JSON output).
4. **`scripts/compound-v-run-with-timeout.py`** (MODIFY) — add an enforced `--max-output-bytes`
   bounded output sink to the shared supervisor (CR5-8); preserve existing behaviour + `--selftest`.
5. **`schemas/pre-eval-record.schema.json`** and **`schemas/fastpath-review-receipt.schema.json`** —
   canonical record + receipt schemas, plus documented **digest functions (exact canonical-JSON
   encoding, excluded self-digest field)** referenced by CR5-6/CR5-7. Since downstream C1 tests
   consume these unchanged, define the canonical-JSON digest convention precisely (document it in the
   schema file or an adjacent comment/`pre-eval-config.md`).
6. **`skills/compound-v/state-machine.md`** (MODIFY) — `PRE_EVAL_DONE` = a **status field in the
   write-once pre-eval RECORD** (there is NO `state.json` at prediction time — AC-7/CR2-8);
   `FASTPATH_DISPATCHED` + `ESCALATION_REQUIRED` = real `state.json` phases; the **idempotent
   two-phase escalation protocol** (commit patch+baseline evidence → deterministic child run-id →
   create+commit child → commit parent `escalated_to`; resume reconciles partial states, discovers an
   existing child before minting — CR2-4/AC-15); accepted-fast-path linked run inits at
   `FASTPATH_DISPATCHED`, decline inits normally; **CR5-3**: fast-path resume persists each job's
   immutable pre-launch baseline SHA and reconciles against THAT, never HEAD; new `state.json` fields
   `escalated_to`, `pre_eval_id`; unbound-pre-eval discovery by `/v:status`.
7. **`skills/compound-v/execution-manifest.md`** (MODIFY) — conditional `fast_path` schema:
   `{eligible, pre_eval_id, pre_eval_ref, localization_ref, taxonomy_ref, taxonomy_digest}`; (a)
   minimal committed spec/plan stub; (b) exactly ONE implementer job, combined SPEC+QUALITY review as
   a **dispatcher PHASE outside `jobs`** (declaration `fast_path.review:{backend:claude, tier:deep}`
   OR `model:opus` — CR4-8); (c) `localization_ref` → committed artifact; (d) an **immutable taxonomy
   snapshot** under the run + `taxonomy_ref` + `taxonomy_digest`; (e) **cross-artifact binding** the
   validator enforces (AC-13): sole `write_allowed` literal == `localization.resolved_paths[0]`;
   `pre_eval_id`/decision/`taxonomy_digest`/localization-digest equal across manifest+record+artifact.
   Document the **two validation modes** (pre-dispatch vs post-review) and **path containment**
   (normalized, repo-relative, no `..`, realpath-under-root, committed regular file — not an escaping
   symlink; CR4-6).
8. **`docs/superpowers/architecture/pre-eval-config.md`** (CREATE) — the `pre_eval.*` config contract:
   keys + fail-closed defaults (`enabled` true, `fast_path` `ask`|`off`, `min_sample_count`,
   `fan_out_threshold`, `token_cap`), malformed → warn-once → default (never auto-route), `remember`
   revocable. Also document (CR5-6/CR5-7/CR5-9) the canonical receipt path bound to run_id/pre_eval_id/
   digests, and the **commit primitive** convention (path-limited/temp-index commit that commits ONLY
   the exact lifecycle path set and fails closed on overlapping user-staged changes) so downstream
   owners implement it consistently. CR5-10: a write-once **intent record** (stable request
   fingerprint → `pre_eval_id`) written BEFORE localization so a fresh-process resume can find partial
   state.

## Binding constraints (from the three audits — MUST honor)
- **Python 3.9-safe, stdlib-first.** Soft-PyYAML fallback everywhere — NEVER a hard `import yaml`.
- Reuse primitives, do not recopy: `append_line` discipline (`update-memory.py` — only appends, never
  rewrites), `_seg_is_literal`/`glob_match` (validate-manifest.py), `matches`/`is_allowed`
  (scope-check.py).
- **External CLIs** (git etc.) go through `scripts/compound-v-run-with-timeout.py` with `stdin
  </dev/null` (DEVNULL) — never a bare `subprocess.run(timeout=…)`.
- **Commit-discipline (v2.6.4):** two separate commands, no `&&`, each exit code checked — but for
  THIS task, do NOT commit; the dispatcher commits your work centrally after the scope gate. Just
  leave your edited files in the working tree.
- Phase enum is prose-only — do not hard-code the phase enum in any script.
- Never claim PRE_EVAL is enforced (it is description-driven + fail-closed only).

## Method (TDD — required)
For each script primitive: write a failing selftest (a `--selftest` mode or a `tests/`-style inline
check) FIRST, verify it fails, implement, verify it passes. Run every selftest with `python3` before
declaring done. Prove the regex-bound fixture terminates within its bound. Do a self-review pass
before reporting DONE.

## Do NOT
- Do NOT run any `git` commands (no add/commit/worktree). Only edit files + run `python3` selftests.
- Do NOT touch files outside WRITE-allowed. If you believe you need one, STOP and report `BLOCKED`.

## Report format (end your final message with exactly one)
`DONE` — all deliverables complete, all selftests pass.
`DONE_WITH_CONCERNS` — complete but list concerns.
`NEEDS_CONTEXT` — blocked on missing info; say what.
`BLOCKED` — needs a forbidden file or hit a hard stop; name it.
Include a short summary of what you built + the selftest results.
