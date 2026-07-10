---
description: Re-run the collect + scope-gate + review tail of a Compound V run by run-id. Normalizes each job's output into results/<id>.json, re-runs the git-derived scope gate on every job, then the three-pass Review Gate (AC-gated). Use to re-check a dispatched run without re-dispatching workers.
---

You are running **`/v:collect`** — the **collect → scope-gate → review** tail of the Compound V pipeline, on an already-dispatched run. It does **not** re-dispatch workers (use [`/v:resume`](v-resume.md) for that). It re-normalizes results, re-runs the file-scope gate, and re-runs the Review Gate — the deterministic, idempotent back half of a run.

The run-id is `{{args}}`.

The run-dir layout and per-job `status` semantics are in [`skills/compound-v/state-machine.md`](../skills/compound-v/state-machine.md); the manifest each job is checked against is [`execution-manifest.md`](../skills/compound-v/execution-manifest.md); the canonical `job_result` shape is [`schemas/job_result.schema.json`](../schemas/job_result.schema.json).

## Steps

1. **Locate the run.** If `{{args}}` is empty, list the subdirectories of `docs/superpowers/execution/` and ask which run to collect. The run dir is `docs/superpowers/execution/<run-id>/`. If it does not exist, stop and say so. If no jobs have been dispatched yet (`phase` earlier than `DISPATCHED`), tell the user there is nothing to collect and stop.

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

## Safety

- The scope gate is the **authority**, not the worker's self-report — a job that wrote outside `write_allowed` is BLOCKED and never merges.
- This command is **idempotent**: re-collecting a clean run re-derives the same verdicts and does not re-dispatch.
- Do **not** override the Opus requirement on the reviewers, and do **not** skip the final integration pass.
- Do **not** print fabricated cost or token metrics (anti-ruflo).
