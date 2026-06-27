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

4. **Reconcile the circuit breaker (neither a silent retry nor a permanent lockout).** `circuit_open` is an **object per backend** — `{ "<backend>": { "open": bool, "reason": "out_of_credits|auth", "opened_at": "<iso-ts>", "cleared_by": null } }` (see [`state-machine.md`](../skills/compound-v/state-machine.md)). For each entry, decide whether to keep it open or clear it **before** any re-dispatch:
   - **`reason == "out_of_credits"`** → keep the breaker **OPEN** unless the user confirms a credit top-up, **or** a cheap liveness probe — a tiny "reply ok" call to that backend — returns success. Only then set `cleared_by` (`"top_up"` or `"probe"`) and re-dispatch that backend's `failed` jobs. The run-level `total_retries` budget persists across the resume.
   - **`reason == "auth"`** → keep the breaker **OPEN** until the user re-authenticates (point them at [`/v:init`](v-init.md)). Only after re-auth set `cleared_by: "reauth"` and re-dispatch its `failed` jobs.
   - **Cooldown-only (no open breaker)** → a backend whose `cooldowns[backend]` timestamp has merely **expired** is **half-opened**: probe it **once** before full re-dispatch. A clean probe clears the cooldown; a repeat failure re-cools it via the policy.
   - **Never silently re-dispatch to a still-open breaker.** If neither the top-up/probe (credits) nor the re-auth (auth) has happened, leave the breaker open, leave its jobs `failed`, and report exactly what the user must do to unblock — do not retry behind their back.
   - Update `circuit_open[backend].cleared_by` and write `state.json` for every breaker transition.

5. **Re-dispatch only the incomplete jobs** — those that are `pending`, `failed`, or `blocked` after steps 3–4 (and **not** behind a still-open breaker) — via **Engine A** (`compound-v:parallel-dispatcher` / the backend-launcher), honoring `depends_on`, `run`, and `max_parallel` exactly as the original dispatch. Each re-dispatch replays the captured prompt at `jobs/<id>.prompt.md` verbatim.
   - For a Codex worktree job with a recorded `session_id`, the codex adapter may use `codex exec resume <session_id>` instead of a cold start. Either way, the **scope gate re-runs** on return.
   - Update each job's `status` and write `state.json` after every transition.

6. **Continue the pipeline** from the reconciled phase: re-collect results, run the scope gate on every job, then the three-pass Review Gate (AC-gated), then merge worktree diffs on PASS. Already-`done` jobs are not re-run.

7. **Report.** Which jobs were skipped (already landed), which were re-dispatched, which stayed **blocked behind an open breaker** (and the exact unblock action — top up credits or re-auth via `/v:init`), and the resulting `phase`. Point the user at [`/v:status {{args}}`](v-status.md) to inspect.

## Safety

- A `blocked` job is re-dispatched only after its prompt/partition is corrected — do not blindly re-run a job that wrote outside its scope.
- A backend with an **open `circuit_open` breaker** is never silently retried: `out_of_credits` needs a confirmed top-up (or a passing liveness probe), `auth` needs a re-auth (`/v:init`). Without that, its jobs stay `failed` and surfaced.
- Resume never weakens enforcement: the `git diff` scope gate runs on every re-dispatched job.
- Do **not** print fabricated cost or token metrics (anti-ruflo).
