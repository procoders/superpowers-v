---
description: Render the state of a Compound V orchestrator run — pipeline phase plus a per-job status table — by reading state.json from the run directory. Optional run-id argument; without one, list runs and pick the most recent.
---

You are about to render the **state of a Compound V orchestrator run**. This is read-only: it inspects `state.json`, it does not dispatch, collect, or merge anything.

The run-id (optional) is `{{args}}`.

## Steps

1. **Locate the run.**
   - If `{{args}}` names a run-id, the run dir is `docs/superpowers/execution/{{args}}/`.
   - If `{{args}}` is empty, list the subdirectories of `docs/superpowers/execution/`. If there is exactly one, use it. If there are several, show them (newest first by run-id date prefix) and render the most recent, noting the others.
   - If `docs/superpowers/execution/` is absent or empty, tell the user there are no orchestrator runs yet and stop.

2. **Read `state.json`** from the run dir (and `manifest.yaml` for job titles). If `state.json` is missing or unreadable, report that the run dir exists but has no state yet, and stop.

3. **Render the run-level phase.** Show the `phase` (one of `SPEC_READY → PREFLIGHT_DONE → PARTITION_VERIFIED → DISPATCHED → COLLECTED → REVIEWED → MERGED`, or terminal `BLOCKED`) and `updated_at`. The phase meanings are defined in [`skills/compound-v/state-machine.md`](../skills/compound-v/state-machine.md).

4. **Render the per-job table.** One row per job from `state.json.jobs`, with `manifest.yaml` supplying the title, the `backend`, and the routing **intent** (`tier`, optional `effort`). For each job, resolve the concrete **model** it runs on with [`scripts/compound-v-resolve-model.py`](../scripts/compound-v-resolve-model.py) — `--backend <job.backend> --tier <job.tier> [--effort <job.effort>] --stance <routing_stance> [--config .claude/compound-v.json]` (the manifest carries intent, not a hardcoded model, so the plugin survives model churn). Pass `--stance` from the manifest's `routing_stance` (default `balanced`) so the displayed `Backend · Model` matches what actually dispatches — without it a `cost-aware` `standard`-tier Claude job would display `opus` but dispatch `sonnet`. Show it as a `Backend · Model` column so it is **always visible which model each job runs on**:

   | Job | Title | Backend · Model | Status | Liveness | Isolation | Worktree |
   |---|---|---|---|---|---|---|
   | task-0-schema | DB schema + types | claude · opus (deep/high) | done | — | direct | — |
   | task-1-editor-ui | Editor UI slice | codex · gpt-5.5 (standard/med) | running | WORKING | worktree | $TMPDIR/… |

   If a job carries an explicit `model:` override in the manifest, show that verbatim (resolution is skipped for it). Per-job `status` is one of `{pending | running | done | blocked | failed}` (see state-machine.md). Show the `session_id` for any Codex/worktree job that has one. If `state.json.attempts[<job>]` is present and non-zero, show the retry count for that job (e.g. an `Attempts` column or `· retried 2×`).

   **Liveness (hang detection).** Populate the `Liveness` column for any job whose `status` is `running` from [`scripts/compound-v-liveness.py`](../scripts/compound-v-liveness.py) `<run-dir> --json` — it classifies each running job from **git + filesystem only** (never model-self-report): `WORKING`, `LIKELY-DONE` (the worktree has a commit past its baseline — work landed, only the completion notification is stuck; hint: *`/v:resume`, or the dispatcher auto-collects it*), `STALE` (no progress past the threshold — a **suspected hang**), `DEAD` (a recorded pid died), or `UNKNOWN`. Non-running jobs show `—`. **Degrade-safe:** if the probe errors or is missing, show `—` for every row — never break the table. Surface any `STALE`/`DEAD` prominently in the summary and point the user at `/v:resume`. Never print fabricated metrics.

5. **Render backend health (the circuit breaker).** From `state.json`, surface graceful-failure state so re-routes and credit-exhaustion are never silent (the fields are defined in [`state-machine.md`](../skills/compound-v/state-machine.md), the policy in [`failure-policy.md`](../skills/compound-v/failure-policy.md)):
   - **Circuit-open backends** — any `circuit_open[<backend>] == true` (out for the run — out-of-credits or auth). Call it out prominently.
   - **Cooldowns** — any `cooldowns[<backend>]` timestamp still in the future (a transiently-failed backend deprioritized until then; probed half-open next batch).
   - **Run-level retries** — `total_retries` / `max_total_retries` (the anti retry-storm budget).
   - **Active re-routes** — if a backend is circuit-open and jobs were re-routed (e.g. codex→claude/opus), state it with the job count and the cost direction (*"codex out of credits → 3 jobs re-routed to claude/opus, est. cost ↑"*). Never present a cheap→expensive swap silently.

   If none of these fields are present (an older run, or no failures yet), skip this section.

6. **Summarize.** Counts by status (e.g. "3 done, 1 running, 1 pending"). If `phase` is `BLOCKED` or any job is `blocked`/`failed`, or any backend is `circuit_open`, point the user at `/v:resume {{args}}` to reconcile and re-dispatch the incomplete jobs (for an out-of-credits circuit-break, the user tops up credits first — see [`failure-policy.md`](../skills/compound-v/failure-policy.md)).

## Notes

- This command never mutates the run. To recover an interrupted run, use [`/v:resume`](v-resume.md).
- Do **not** print fabricated cost or token metrics — `state.json` carries none and neither should this output (anti-ruflo).
