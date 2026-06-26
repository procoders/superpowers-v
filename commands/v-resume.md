---
description: Resume an interrupted Compound V orchestrator run by run-id. Reconciles state.json against git reality (git-wins tie-break) and re-dispatches only the incomplete jobs (pending/failed/blocked) via Engine A, then continues collect → review → merge.
---

You are about to **resume** the Compound V orchestrator run `{{args}}` after an interruption or crash. Resume is **idempotent** — resuming a fully-`MERGED` run is a no-op.

Resume is **Engine-A-owned**: it does not rely on Workflows (whose resume is same-session-only and fails the crash case). The reconcile + re-dispatch logic below is the authoritative procedure defined in [`skills/compound-v/state-machine.md`](../skills/compound-v/state-machine.md).

## Steps

1. **Locate the run.** If `{{args}}` is empty, list the subdirectories of `docs/superpowers/execution/` and ask which run to resume. The run dir is `docs/superpowers/execution/<run-id>/`. If it does not exist, stop and say so.

2. **Read** `state.json` and `manifest.yaml` from the run dir. If `phase` is already `MERGED`, report nothing to do and stop.

3. **Reconcile against git reality (git-wins).** For each job, derive what actually landed using the same git signal the scope gate uses:
   - `git -C <worktree-or-repo> diff --name-only HEAD` ∪ `git -C <worktree-or-repo> ls-files --others --exclude-standard`.
   - When `state.json` and git disagree, **git wins**:
     - `done` in `state.json` but the job's `write_allowed` files are **not** in git → reclassify as not-done, re-dispatch.
     - `pending`/`running` in `state.json` but the files **are** fully present and within scope → reclassify as `done`, skip.

4. **Re-dispatch only the incomplete jobs** — those that are `pending`, `failed`, or `blocked` after step 3 — via **Engine A** (`compound-v:parallel-dispatcher` / the backend-launcher), honoring `depends_on`, `run`, and `max_parallel` exactly as the original dispatch. Each re-dispatch replays the captured prompt at `jobs/<id>.prompt.md` verbatim.
   - For a Codex worktree job with a recorded `session_id`, the codex adapter may use `codex exec resume <session_id>` instead of a cold start. Either way, the **scope gate re-runs** on return.
   - Update each job's `status` and write `state.json` after every transition.

5. **Continue the pipeline** from the reconciled phase: re-collect results, run the scope gate on every job, then the three-pass Review Gate (AC-gated), then merge worktree diffs on PASS. Already-`done` jobs are not re-run.

6. **Report.** Which jobs were skipped (already landed), which were re-dispatched, and the resulting `phase`. Point the user at [`/v:status {{args}}`](v-status.md) to inspect.

## Safety

- A `blocked` job is re-dispatched only after its prompt/partition is corrected — do not blindly re-run a job that wrote outside its scope.
- Resume never weakens enforcement: the `git diff` scope gate runs on every re-dispatched job.
- Do **not** print fabricated cost or token metrics (anti-ruflo).
