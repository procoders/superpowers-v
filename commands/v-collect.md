---
description: Re-run the collect + scope-gate + review tail of a Compound V run by run-id. Normalizes each job's output into results/<id>.json, re-runs the git-derived scope gate on every job, then the three-pass Review Gate (AC-gated). Use to re-check a dispatched run without re-dispatching workers.
---

You are running **`/v:collect`** — the **collect → scope-gate → review** tail of the Compound V pipeline, on an already-dispatched run. It does **not** re-dispatch workers (use [`/v:resume`](v-resume.md) for that). It re-normalizes results, re-runs the file-scope gate, and re-runs the Review Gate — the deterministic, idempotent back half of a run.

The run-id is `{{args}}`.

The run-dir layout and per-job `status` semantics are in [`skills/compound-v/state-machine.md`](../skills/compound-v/state-machine.md); the manifest each job is checked against is [`execution-manifest.md`](../skills/compound-v/execution-manifest.md); the canonical `job_result` shape is [`schemas/job_result.schema.json`](../schemas/job_result.schema.json).

## Steps

1. **Locate the run.** If `{{args}}` is empty, list the subdirectories of `docs/superpowers/execution/` and ask which run to collect. The run dir is `docs/superpowers/execution/<run-id>/`. If it does not exist, stop and say so. If no jobs have been dispatched yet (`phase` earlier than `DISPATCHED`), tell the user there is nothing to collect and stop.

   **Branch on the manifest kind.** If `manifest.yaml` carries a `fast_path` block (a v2.9 pre-eval-backed fast-path run — its `phase` is `FASTPATH_DISPATCHED`), do **not** run the ordinary three-pass review tail (steps 3–4). Run the **fast-path authoritative sequence** below instead (CR5-2). Step 2 (collect/normalize) still applies to the single implementer job. A legacy (non-`fast_path`) manifest uses steps 2–5 unchanged.

2. **Collect — normalize each job's output.** The collector is **per-job** (required `--job-id` + `--run-dir`; no positional run-dir). Loop over every dispatched `<job-id>`, normalizing its heterogeneous worker output into a canonical `results/<id>.json`:
   ```
   # for each dispatched <job-id>:
   python3 scripts/compound-v-collect-results.py \
     --job-id <job-id> \
     --run-dir docs/superpowers/execution/<run-id>/ \
     --scope <scope-verdict.json> \
     --worker-output <last-message> \
     --schema schemas/job_result.schema.json
   ```
   Output lands in `<run-dir>/results/<job-id>.json`. The collector validates each result against [`schemas/job_result.schema.json`](../schemas/job_result.schema.json). Its `files_changed` / `violations` / `blocked` fields are **git-derived** (folded in from `--scope`), never model-self-reported; `--worker-output` feeds only the human `summary`. It prints **no fabricated cost metrics**.

3. **Scope gate — git-diff authority, every job.** Re-run the scope gate on each job against its `write_allowed` from the manifest. The script takes a mutually-exclusive **mode flag** (`--worktree` OR `--repo`) plus the allowed globs (`--allow-file`) — no positional path. Use the mode matching how the job was dispatched (mirrors [`phase-3-parallel-opus-dispatch.md`](../skills/compound-v/phase-3-parallel-opus-dispatch.md)):
   ```
   # worktree jobs:
   python3 scripts/compound-v-scope-check.py --worktree <wt-dir> --allow-file <allow-globs-file>
   # direct (in-repo) jobs:
   python3 scripts/compound-v-scope-check.py --repo <repo-dir> --baseline <pre-dispatch-commit> --allow-file <allow-globs-file>
   ```
   Exit codes: `0` = pass, `1` = blocked (violations present), `2` = usage/git error. It derives changed files with `git -C <worktree-or-repo> diff --name-only HEAD` ∪ `git ... ls-files --others --exclude-standard`. Any path outside `write_allowed` ⇒ the job is **BLOCKED**: mark it `blocked` in `state.json`, retain its worktree, **do not merge it**, and **HALT the run** — surface the offending paths to the user. A BLOCKED job is corrected and re-dispatched via `/v:resume`, not silently merged.

4. **Review Gate — three passes (Opus), AC-gated.** If every job passes the scope gate, run [`spec-reviewer`](../agents/spec-reviewer.md)'s three passes:
   - **SPEC** — each job satisfies its own `acceptance` in the manifest.
   - **QUALITY** — code quality, no regressions, **no fabricated metrics**.
   - **INTEGRATION** — cross-job seams build, and the composite change satisfies the feature-level `acceptance_criteria`.
   DONE is gated on all three. Unresolvable reviewer ISSUES ⇒ HALT (do not merge).

5. **Update state + report.** Write `state.json` after each transition (`COLLECTED` → `REVIEWED`). **Commit what this command rewrote** — `state.json` and the refreshed `results/*.json` — the same commit discipline as [`parallel-dispatcher`](../agents/parallel-dispatcher.md)'s Step 7: uncommitted files in a worktree are silently deleted by `finishing-a-development-branch`'s cleanup step, and `/v:collect` is explicitly usable **standalone** (re-checking an already-dispatched run), so don't assume a later step will commit on your behalf. Report: per-job scope verdict, the three review-pass outcomes, and whether the run is clear to merge. If clear, point at the merge step (worktree diffs apply into the main tree, then `superpowers:finishing-a-development-branch`). If BLOCKED, point at [`/v:resume {{args}}`](v-resume.md).

## Fast-path collect — the authoritative sequence (v2.9, CR5-2)

For a `fast_path` manifest, `/v:collect` runs the **ONE authoritative order** the Lifecycle & commit-ordering protocol defines (single authority; the dispatcher's [Step 2e](../agents/parallel-dispatcher.md) and `/v:resume` match it byte-for-intent). This replaces steps 3–4. The single implementer job has already been normalized (step 2). Reconcile git **against the job's immutable pre-launch baseline SHA** (`state.json jobs[<id>].baseline`), never a live `HEAD` — a fast-path worker may commit and move `HEAD` (CR5-3). The order is fixed — **tests (floor) → scope gate → F2 → review → post-review receipt validation → final scope recheck → merge → terminal `actual`** — and is driven by [`scripts/compound-v-fastpath-run.py`](../scripts/compound-v-fastpath-run.py):

1. **Test floor — run it FIRST, persist the result, HALT on failure (non-skippable).** Ahead of the scope gate, run the proportionate floor ladder (configured tests → guarded parse-check → cheap diff-read) and write its **fresh** result into the run dir — step 4's `review-spec` fails closed unless this floor-result file exists and PASSED, and `/v:collect` is usable standalone, so this command must produce it (never assume the dispatcher left one behind):
   ```
   python3 scripts/compound-v-fastpath-run.py test-floor \
     --worktree <wt-dir> [--baseline <pinned-baseline-sha>] [--test-cmd <configured-tests>] \
     > docs/superpowers/execution/<run-id>/review/floor-result.json
   ```
   A floor **FAILURE** blocks the merge: surface it and **HALT** — do not scope-gate, review, or merge.
2. **Scope gate** — run [`scripts/compound-v-scope-check.py`](../scripts/compound-v-scope-check.py) on the implementer job against its sole `write_allowed` literal, as in step 3. Any out-of-scope path ⇒ **BLOCKED**, HALT, do not merge.
3. **F2 — post-hoc reclassify, pre-merge, against the pinned baseline.** BEFORE any merge/commit/worktree-removal, run the sibling reclassifier over the **same pinned baseline + the authoritative changed-path set the scope gate used**:
   ```
   python3 scripts/compound-v-postdiff-reclassify.py \
     --worktree <wt-dir> --baseline <pinned-baseline-sha> \
     --taxonomy <manifest fast_path.taxonomy_ref, repo-relative> [--changed-file <scope-changed-paths>]
   # → {"escalate": bool, "reasons": [...]}   (exit 1 iff escalate)
   ```
   If `escalate` is true, the fast-path prediction was wrong: **do not merge**. Hand off to the dispatcher's two-phase escalation ([`parallel-dispatcher.md`](../agents/parallel-dispatcher.md)) — advance `phase` to `ESCALATION_REQUIRED`, preserve the patch + baseline as evidence, and the pipeline rejoins the full path via a **new** run. Escalation appends the terminal `actual` with `escalated:true` on **this** (parent) run.
4. **Combined `needs_review` review — one deep/opus Task (write the receipt).** On a clean F2, build the review request with [`scripts/compound-v-fastpath-run.py`](../scripts/compound-v-fastpath-run.py) `review-spec` — it fails closed unless the **floor PASSED** (step 1's `floor-result.json`), scope was CLEAN, and F2 did NOT escalate, so it consumes the persisted floor result:
   ```
   python3 scripts/compound-v-fastpath-run.py review-spec \
     --worktree <wt-dir> --baseline <pinned-baseline-sha> \
     --manifest <run-dir>/manifest.yaml --run-id <run-id> --pre-eval-id <pre_eval_id> \
     --floor-result <run-dir>/review/floor-result.json --scope-clean --f2-result <f2-result.json> \
     --out <run-dir>/review/spec.json
   ```
   Run the in-harness combined **SPEC+QUALITY** review as a `deep`/opus Task on the emitted `needs_review` prompt. Then let **`accept-review` seal the receipt after acceptance** (do NOT hand-write it, HIGH-3): `python3 scripts/compound-v-fastpath-run.py accept-review --spec <spec-json> --result <result-json> --run-dir docs/superpowers/execution/<run-id>`. It first invalidates any stale receipt (HIGH-4), then on a clean bound `approved` result atomically writes the fully-sealed `review/receipt.json` (ts + `worktree` + `attempt_id` + bindings + `record_digest` self-seal; `backend:claude`, model == Claude Opus). A rejected/timed-out result leaves no valid receipt. One combined pass with a recorded vacuous INTEGRATION rationale — **not** the three separate passes.
5. **Post-review receipt validation — C1 `--mode post-review`.** Before merge, verify the receipt with the validator:
   ```
   python3 scripts/compound-v-validate-manifest.py --mode post-review \
     [--repo-root <repo>] --worktree <wt-dir> [--receipt <run-dir>/review/receipt.json] <run-dir>/manifest.yaml
   ```
   `--worktree <wt-dir>` is **mandatory** (MED-7): the validator recomputes `final_diff_digest` in the worker's linked worktree — the checkout the receipt hashed. Omitting it recomputes against the clean main checkout and fails closed. `--mode post-review` REQUIRES + verifies the receipt (`run_id`/`pre_eval_id` bindings, `reviewer_backend:claude`, reviewer model == Claude Opus, `worktree` == diff-root, self-digest). A missing or mismatched receipt fails closed — no merge.
6. **Final scope recheck → merge** — re-run the scope gate once more (step 2) to catch anything the review round touched; then **merge** the worktree diff back into the main tree.
7. **Append + commit the terminal `actual` — ONLY AFTER the merge boundary succeeds (CR5-4).** Only once the merge/commit lands, append the terminal triage event:
   ```
   python3 scripts/compound-v-triage-outcomes.py actual \
     --pre-eval-id <pre_eval_id> --run-id <run-id> --review-result approved
   ```
   A precision-**ignored** intermediate (`--merge-pending`) event MAY be recorded earlier, but a `review_passed` `actual` that never merged must **never** reach Tier 2 — the terminal `actual` is emitted strictly after the merge boundary. Commit `state.json` (phase `MERGED`) together with the run substrate before any worktree cleanup, exactly as the dispatcher's commit discipline requires.

## Safety

- The scope gate is the **authority**, not the worker's self-report — a job that wrote outside `write_allowed` is BLOCKED and never merges.
- This command is **idempotent**: re-collecting a clean run re-derives the same verdicts and does not re-dispatch.
- Do **not** override the Opus requirement on the reviewers, and do **not** skip the final integration pass.
- Do **not** print fabricated cost or token metrics (anti-ruflo).
