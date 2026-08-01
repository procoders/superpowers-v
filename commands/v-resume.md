---
description: Resume an interrupted Compound V orchestrator run by run-id. Reconciles state.json against git reality (git-wins tie-break) and re-dispatches only the incomplete jobs (pending/failed/blocked) via Engine A, then continues collect → review → merge.
---

You are about to **resume** the Compound V orchestrator run `{{args}}` after an interruption or crash. Resume is **idempotent** — resuming a fully-`MERGED` run is a no-op.

Resume is **Engine-A-owned**: it does not rely on Workflows (whose resume is same-session-only and fails the crash case). The reconcile + re-dispatch logic below is the authoritative procedure defined in [`skills/compound-v/state-machine.md`](../skills/compound-v/state-machine.md).

## Steps

1. **Locate the run.** If `{{args}}` is empty, list the subdirectories of `docs/superpowers/execution/` and ask which run to resume. The run dir is `docs/superpowers/execution/<run-id>/`. If it does not exist, stop and say so.

2. **Read** `state.json` and `manifest.yaml` from the run dir. If `phase` is already `MERGED`, report nothing to do and stop.

> **Pool-assignment resume rule (Shared Interface Contract — byte-identical in `commands/v-resume.md`, `agents/parallel-dispatcher.md`, and `skills/compound-v/state-machine.md`).**
> Before any git or breaker reconciliation, if the manifest contains a job whose routing token is `backend: pool`, validate the complete recorded state with `python3 scripts/compound-v-pool-state.py validate` using `{"state": <state.json>, "jobs": <manifest jobs>}`; any error HALTS resume.
> Then obtain only that job's concrete pair with `python3 scripts/compound-v-pool-state.py resume` using `{"state": <state.json>, "job_id": "<id>"}`; the helper returns only `assigned_backend` and `assigned_model`.
> Read `assignment_source`, `pool_index`, `pool_tier`, and `worktree` directly from the already-validated `state.json jobs[<id>]` record and reuse all six recorded values for reconciliation.
> Never reload current pool config, recompute a manifest ordinal, rerun freeze, or call the model resolver for that recorded assignment. A same-assignment retry preserves it byte-for-byte; any replacement authorized by policy intent is selected only by `transition` and MUST be written and validated before relaunch.

> **Pool-assignment replacement rule (Shared Interface Contract — copy byte-identically into dispatcher and resume runbooks).**
> Assignment replacement is transition-owned. `out_of_credits` first opens the canonical permanent circuit and performs one bounded frozen-ring scan; only after ring exhaustion may it use an explicitly supplied exact `fallback_assignment` whose backend matches policy `reroute_to`. A missing, malformed, or mismatched fallback HALTS without guessing. `auth` persists its canonical permanent circuit and HALTS. A second short transient or a transient with a known wait over 60 seconds opens a cooldown and advances; `usage_window_exhausted` opens its cooldown and advances immediately; and `model_unavailable` excludes only the exact `exclude_assignment: {backend, model}` pair before selection. The dispatcher adds the persisted current `attempt_id`; when `consume_total_retry: true`, transition atomically charges `total_retries` once for that failed attempt only if it returns a concrete launch assignment, while a no-viable-member halt persists health without a charge. Replay cannot charge twice, and exhaustion HALTS before assignment. Persist and validate every resulting assignment and health-state mutation before relaunch.

**Cooldown/network gate before git reconciliation.** Validate the complete state with
`compound-v-pool-state.py validate`. Reconcile any recorded probe owner against process liveness
and git-wins before reclaiming an expired lease. An unexpired cooldown or active network pause
forbids launch; expiry grants eligibility for one serialized real-job probe, never automatic
health or fan-out. Preserve run `total_retries` exactly.

`/v:resume --clear-cooldown <backend>` is the only manual recovery for a wrongly far-future
transient cooldown. Pass the existing state and backend to `compound-v-pool-state.py
clear-cooldown`; the helper validates a known concrete backend, clears transient cooldown only,
never clears `circuit_open`, validates the replacement, and the caller atomically persists it.
Hand-editing `state.json` is forbidden.

3. **Reconcile against git reality (git-wins).** For each job, derive what actually landed using the same git signal the scope gate uses:
   - `git -C <worktree-or-repo> diff --name-only HEAD` ∪ `git -C <worktree-or-repo> ls-files --others --exclude-standard`.
   - When `state.json` and git disagree, **git wins**:
     - `done` in `state.json` but the job's `write_allowed` files are **not** in git → reclassify as not-done, re-dispatch.
     - `pending`/`dispatched`/`running` in `state.json` but the files **are** fully present and within scope → reclassify as `done`, skip.

4. **Reconcile the circuit breaker (neither a silent retry nor a permanent lockout).** The already-run pool-state validation has checked the one canonical map keyed by **concrete backend** — `{ "<backend>": { "open": bool, "reason": "out_of_credits|auth", "opened_at": "<iso-ts>", "cleared_by": null } }` (see [`state-machine.md`](../skills/compound-v/state-machine.md)). It rejects `circuit_open.pool`, bare booleans, incomplete/extra fields, and invalid open/reason/cleared-by combinations; a pool job consults its recorded `assigned_backend`. For each valid entry, decide whether to keep it open or clear it **before** any re-dispatch:
   - **`reason == "out_of_credits"`** → keep the breaker **OPEN** unless the user confirms a credit top-up, **or** a cheap liveness probe — a tiny "reply ok" call to that backend — returns success. Only then set `cleared_by` (`"top_up"` or `"probe"`) and re-dispatch that backend's `failed` jobs. Clear `earliest_reset_observed_at` + `earliest_reset_seconds` when that exhausted condition is resolved and no other out-of-credits breaker remains; otherwise retain/recompute the pair only from a fresh observation. The run-level `total_retries` budget persists across the resume.
   - **`reason == "auth"`** → keep the breaker **OPEN** until the user re-authenticates (point them at [`/v:init`](v-init.md)). Only after re-auth set `cleared_by: "reauth"` and re-dispatch its `failed` jobs.
   - **Cooldown-only (no open breaker)** → `cooldowns[backend]` is the canonical object
     `{until, reason, opened_at, opened_by_attempt_id, probe}`. Expiry may lease one real pending
     job as the half-open probe. Only final success from that exact leased `attempt_id` clears it;
     stale pre-cooldown success cannot, transient failure renews it, and permanent failure opens
     its reason-specific breaker.
   - **Correlated network pause** → only deduplicated `no_response` evidence from two distinct
     providers in the same batch within 60 seconds, with no completed provider success, can open
     it. z.ai 1234 is provider-reported and never counts. Recovery leases one real job; all other
     launches remain paused until that probe completes.
   - **Never silently re-dispatch to a still-open breaker.** If neither the top-up/probe (credits) nor the re-auth (auth) has happened, leave the breaker open, leave its jobs `failed`, and report exactly what the user must do to unblock — do not retry behind their back.
   - Update `circuit_open[backend].cleared_by` and write `state.json` for every breaker transition.

5. **Re-dispatch only the incomplete jobs** — `pending`, `failed`, or `blocked`, plus `dispatched` / `running` jobs that git-wins found **not landed** after steps 3–4 (and **not** behind a still-open breaker) — via **Engine A** (`compound-v:parallel-dispatcher` / the backend-launcher), honoring `depends_on`, `run`, manifest `max_parallel`, and the run-start `backend_max_parallel` ceilings against each recorded concrete backend exactly as the original dispatch. Each re-dispatch replays the captured prompt at `jobs/<id>.prompt.md` verbatim. A recorded `assignment_source: "fallback"` is a valid concrete fallback assignment after pool exhaustion; validate and reuse it exactly like an in-ring `assignment_source: "pool"` assignment.
   - A Codex worktree job's resume-vs-recreate decision is governed by the **resume-eligibility rule below** — reproduced verbatim so it agrees word-for-word with [`parallel-dispatcher.md`](../agents/parallel-dispatcher.md) and kills the old contradiction (this step once said "may use `codex exec resume`" unconditionally, while the dispatcher's invariant recreates the worktree fresh at HEAD). Either way — resumed session or fresh recreate — the **scope gate re-runs** on return.
   - Update each job's `status` and write `state.json` after every transition.

Both inputs the rule needs live in **`state.json jobs[<id>]`** — `session_id` (the captured UUID) and `failure_class` — written there by the dispatcher on the job's return (Step 2 already reads `state.json`; you do **not** need to open `results/<id>.json` for this). A job with an empty `session_id` has no session to resume ⇒ recreate fresh regardless.

> **Resume-eligibility rule (Shared Interface Contract — byte-identical in `commands/v-resume.md` and `agents/parallel-dispatcher.md`).**
> A codex worktree job may be resumed via `codex exec resume <captured-uuid>` **IFF** its `failure_class` is
> environmental (`timeout` | `network`) **AND** its worktree still exists at the recorded path.
> Every other case recreates the worktree **fresh at HEAD** — the parallel-dispatcher worktree-recreate invariant.
> Never resume by cwd filtering; pass the captured UUID explicitly.

6. **Continue the pipeline** from the reconciled phase: re-collect results, run the scope gate on every job, then the three-pass Review Gate (AC-gated), then merge worktree diffs on PASS. Already-`done` jobs are not re-run. **On reaching `MERGED`, commit the run substrate exactly as [`parallel-dispatcher`](../agents/parallel-dispatcher.md)'s Step 7 does** — `state.json` (phase written as `MERGED` first, then committed together with the rest), `results/*.json`, and the memory/scorecard files if this resume refreshed them — **before** handing off to `superpowers:finishing-a-development-branch`. This matters *especially* on the resume path: the whole point of resuming is recovering from a crash or interruption, so leaving the just-recovered state uncommitted means a subsequent worktree cleanup can silently erase the very state resume just fixed.

7. **Report.** Which jobs were skipped (already landed), which were re-dispatched, which stayed **blocked behind an open breaker** (and the exact unblock action — top up credits or re-auth via `/v:init`), and the resulting `phase`. Point the user at [`/v:status {{args}}`](v-status.md) to inspect.

## Fast-path & escalation resume (v2.9)

A pre-eval-backed fast-path run reconciles by the same git-wins logic, with two deviations the state machine makes authoritative ([`state-machine.md`](../skills/compound-v/state-machine.md) §Fast-path resume, §Idempotent two-phase escalation). Detect the run kind from `state.json.phase` (and `manifest.yaml`'s `fast_path` block).

**`FASTPATH_DISPATCHED` — reconcile like `DISPATCHED`, but baseline-relative, NOT HEAD-relative (CR5-3).** A fast-path job persists its **immutable pre-launch baseline SHA** in `state.json jobs[<id>].baseline` (recorded at dispatch, the same SHA the scope gate and F2 attribute against). Reconcile step 3's git observation against **THAT baseline**, never a live `HEAD`:
- `git -C <worktree> diff --name-only <baseline>` ∪ `git -C <worktree> ls-files --others --exclude-standard`.
- A HEAD-relative diff would go **blind** — a fast-path worker may commit and move `HEAD`, so a change attributed against `HEAD` would show nothing landed. Baseline-relative is the only correct signal (the identical reason the scope gate baselines against the recorded pre-`worktree add` SHA).
- **Completion is a three-way agreement**, not a single flag: a fast-path job is `done` only when the normalized `results/<id>.json` **and** the git-derived scope verdict **and** the baseline-relative patch digest all agree the work landed and is in-scope. If any of the three disagrees, git wins — treat it as not-done and re-dispatch (replaying `jobs/<id>.prompt.md` verbatim).
- After reconciling the single implementer job, continue the fast-path tail via the authoritative sequence, not the ordinary three-pass tail — see [`/v:collect`](v-collect.md). The non-skippable **test floor runs FIRST** on resume too (re-run + persist `compound-v-fastpath-run.py test-floor`, HALT on failure), then: **test floor → scope gate → F2 (pre-merge) → combined `needs_review` deep/opus Task → post-review receipt validation → final scope recheck → merge → terminal `actual`** — byte-for-intent identical to `/v:collect` and `parallel-dispatcher.md` Step 2e (MED-7: a resumed fast-path must not skip the floor).

**`ESCALATION_REQUIRED` — follow `escalated_to`, reconcile the two-phase escalation (AC-15/CR4-3).** The pre-merge F2 escalated: the frozen fast-path `manifest.yaml` is **never** replayed against a full pipeline. Instead follow the idempotent two-phase escalation protocol, discovering partial state and **never minting a duplicate child**:
- If `state.json.escalated_to` is set, that child run-id already exists and is durable (the parent's `escalated_to` is committed **LAST**, so a committed link ⇒ the child is complete). Resume the child by that run-id (recurse into this same algorithm for it — it is a normal full-pipeline run starting from the clean baseline).
- If `escalated_to` is **null** but the parent already committed the escalation's patch + baseline evidence, the escalation crashed mid-protocol. **Derive the deterministic child run-id from the parent** and check whether that run dir already exists: if it does, **adopt it** (do not create a second) and, if the parent's `escalated_to` is still unwritten, complete the protocol by committing the link last; if it does not, create + commit the child from the **clean baseline** (the preserved patch is evidence only, never applied), then commit the parent's `escalated_to`.
- **Never replay the fast-path job set against a full manifest.** The escalated pipeline is a fresh full-pipeline run on its own run-id; the original fast-path run stays terminal at `ESCALATION_REQUIRED` with its patch preserved as evidence.

## Safety

- A `blocked` job is re-dispatched only after its prompt/partition is corrected — do not blindly re-run a job that wrote outside its scope.
- A backend with an **open `circuit_open` breaker** is never silently retried: `out_of_credits` needs a confirmed top-up (or a passing liveness probe), `auth` needs a re-auth (`/v:init`). Without that, its jobs stay `failed` and surfaced.
- Resume never weakens enforcement: the `git diff` scope gate runs on every re-dispatched job.
- Do **not** print fabricated cost or token metrics (anti-ruflo).
