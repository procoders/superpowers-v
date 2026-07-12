---
description: Render the state of a Compound V orchestrator run — pipeline phase plus a per-job status table — by reading state.json from the run directory. Optional run-id argument; without one, list runs and pick the most recent.
---

You are about to render the **state of a Compound V orchestrator run**. This is read-only: it inspects `state.json`, it does not dispatch, collect, or merge anything.

The run-id (optional) is `{{args}}`.

## Steps

1. **Locate the run.**
   - If `{{args}}` names a run-id, the run dir is `docs/superpowers/execution/{{args}}/`.
   - If `{{args}}` is empty, list the subdirectories of `docs/superpowers/execution/`. If there is exactly one, use it. If there are several, show them (newest first by run-id date prefix) and render the most recent, noting the others.
   - If `docs/superpowers/execution/` is absent or empty, tell the user there are no **Compound V**
     orchestrator runs yet. Before stopping, do one cheap check: does `.superpowers/sdd/` exist in
     this repo (plain Superpowers' `subagent-driven-development` task-tracking directory —
     `task-N-brief.md` / `task-N-report.md` / `progress.md` / `review-<sha>..<sha>.diff`)? If so,
     say so explicitly: work clearly happened here, just not through Compound V's manifest-driven
     dispatch (auto-interception didn't trigger, or the plan predates it) — **do not** parse or
     summarize its contents (that directory's format belongs to the base Superpowers plugin, not
     Compound V; a presence check is all that's warranted). Otherwise stop as before — genuinely
     no orchestrator runs of either kind.

2. **Read `state.json`** from the run dir (and `manifest.yaml` for job titles). If `state.json` is missing or unreadable, report that the run dir exists but has no state yet, and stop.

3. **Render the run-level phase.** Show the `phase` (one of `SPEC_READY → PREFLIGHT_DONE → PARTITION_VERIFIED → DISPATCHED → COLLECTED → REVIEWED → MERGED`, or terminal `BLOCKED`) and `updated_at`. The phase meanings are defined in [`skills/compound-v/state-machine.md`](../skills/compound-v/state-machine.md).

   **v2.9 fast-path phases.** A pre-eval-backed fast-path run uses two extra `state.json` phases (same authority doc): `FASTPATH_DISPATCHED` (the single-job fast-path manifest was materialized + dispatched) and terminal-branch `ESCALATION_REQUIRED` (the pre-merge post-hoc reclassifier escalated; the pipeline rejoined the full path via a **new** run). Render them exactly like any other phase. `PRE_EVAL_DONE` is **not** a phase — it is a `status` field inside a write-once pre-eval **record** (there is no `state.json` at prediction time); never expect it in `state.json.phase`. When `phase == ESCALATION_REQUIRED`, read `state.json.escalated_to` and show the child run-id the fast-path escalated into (`escalated → <child-run-id>`); the fast-path patch stays under this run as evidence, the child starts from the clean baseline.

4. **Render the per-job table.** One row per job from `state.json.jobs`, with `manifest.yaml` supplying the title, the `backend`, and the routing **intent** (`tier`, optional `effort`). For each job, resolve the concrete **model** it runs on with [`scripts/compound-v-resolve-model.py`](../scripts/compound-v-resolve-model.py) — `--backend <job.backend> --tier <job.tier> [--effort <job.effort>] --stance <routing_stance> [--config .claude/compound-v.json]` (the manifest carries intent, not a hardcoded model, so the plugin survives model churn). Pass `--stance` from the manifest's `routing_stance` (default `balanced`) so the displayed `Backend · Model` matches what actually dispatches — without it a `cost-aware` `standard`-tier Claude job would display `opus` but dispatch `sonnet`. Show it as a `Backend · Model` column so it is **always visible which model each job runs on**:

   | Job | Title | Backend · Model | Status | Liveness | Isolation | Worktree |
   |---|---|---|---|---|---|---|
   | task-0-schema | DB schema + types | claude · opus (deep/high) | done | — | direct | — |
   | task-1-editor-ui | Editor UI slice | codex · gpt-5.6-terra (standard/med) | running | WORKING | worktree | $TMPDIR/… |

   If a job carries an explicit `model:` override in the manifest, show that verbatim (resolution is skipped for it). Per-job `status` is one of `{pending | running | done | blocked | failed}` (see state-machine.md). Show the `session_id` for any Codex/worktree job that has one. If `state.json.attempts[<job>]` is present and non-zero, show the retry count for that job (e.g. an `Attempts` column or `· retried 2×`).

   **Liveness (hang detection).** Populate the `Liveness` column for any job whose `status` is `running` from [`scripts/compound-v-liveness.py`](../scripts/compound-v-liveness.py) `<run-dir> --json` — it classifies each running job from **git + filesystem only** (never model-self-report): `WORKING`, `LIKELY-DONE` (the worktree has a commit past its baseline — work landed, only the completion notification is stuck; hint: *`/v:resume`, or the dispatcher auto-collects it*), `STALE` (no progress past the threshold — a **suspected hang**), `DEAD` (a recorded pid died), or `UNKNOWN`. Non-running jobs show `—`. **Degrade-safe:** if the probe errors or is missing, show `—` for every row — never break the table. Surface any `STALE`/`DEAD` prominently in the summary and point the user at `/v:resume`. Never print fabricated metrics.

5. **Render backend health (the circuit breaker).** From `state.json`, surface graceful-failure state so re-routes and credit-exhaustion are never silent (the fields are defined in [`state-machine.md`](../skills/compound-v/state-machine.md), the policy in [`failure-policy.md`](../skills/compound-v/failure-policy.md)):
   - **Circuit-open backends** — any `circuit_open[<backend>] == true` (out for the run — out-of-credits or auth). Call it out prominently.
   - **Cooldowns** — any `cooldowns[<backend>]` timestamp still in the future (a transiently-failed backend deprioritized until then; probed half-open next batch).
   - **Run-level retries** — `total_retries` / `max_total_retries` (the anti retry-storm budget).
   - **Active re-routes** — if a backend is circuit-open and jobs were re-routed (e.g. codex→claude/opus), state it with the job count and the cost direction (*"codex out of credits → 3 jobs re-routed to claude/opus, est. cost ↑"*). Never present a cheap→expensive swap silently.

   If none of these fields are present (an older run, or no failures yet), skip this section.

6. **Summarize.** Counts by status (e.g. "3 done, 1 running, 1 pending"). If `phase` is `BLOCKED` or any job is `blocked`/`failed`, or any backend is `circuit_open`, point the user at `/v:resume {{args}}` to reconcile and re-dispatch the incomplete jobs (for an out-of-credits circuit-break, the user tops up credits first — see [`failure-policy.md`](../skills/compound-v/failure-policy.md)).

## Pre-Evaluation & fast-path (v2.9)

These renderings are additive and **degrade-safe**: if `docs/superpowers/pre-eval/` is absent, the triage stream is missing, or a script errors, skip the section silently — never break the run table, never fabricate a number.

7. **Render the pre-eval decision + derived 1-10 for a pre-eval-backed run.** If `state.json.pre_eval_id` is set (present on any fast-path OR declined-then-normal run — the bind holds for both), read the write-once record `docs/superpowers/pre-eval/<pre_eval_id>.json` and show its `decision` (`FASTPATH_ELIGIBLE` | `FULL_PIPELINE`), `override_fired`, and the **derived 1-10** per axis — `difficulty.display` and `impact.display`. That 1-10 is a post-decision **band-midpoint DISPLAY label** (`low→2, medium→5, high→8`; `unknown`/absent → `—`), never the gate and never a computed magnitude — render it verbatim from the record, label it as a display band, and do not derive your own.

8. **Unbound-pre-eval discovery.** A pre-eval record can exist with **no run** — the user declined the fast-path offer, or a crash hit before materialization. These are invisible to the run-directory scan, so surface them explicitly: list the records under `docs/superpowers/pre-eval/*.json` whose `pre_eval_id` has a `predicted` event but **no** `bind` event in `docs/superpowers/memory/triage-outcomes.jsonl` (an unbound prediction). For each, show its `decision` + the derived 1-10 (as in step 7) under an **"unbound pre-evals"** heading, so a pre-eval'd request is never silently lost. Do not invent a phase for them — they have no `state.json`.

9. **Fast-path precision + escalation-rate (AC-12) — git-derived actuals only.** Report how well the fast-path is calibrated from the `predicted`↔`actual` join, never a self-reported number:

   ```bash
   # Pass --repo so the effective pre_eval.min_sample_count floor is resolved from
   # .claude/compound-v.json, and --min-sample so the floor is actually APPLIED
   # (the `precision` subcommand does NOT auto-read the config floor — pass it, or
   # a single sample would masquerade as a calibrated rate). Resolve the floor from
   # pre_eval.min_sample_count (its declared default when the config is absent/malformed).
   python3 scripts/compound-v-triage-outcomes.py precision --repo . --min-sample "$FLOOR"
   # → {"precision": …, "escalation_rate": …, "n": N, "excluded_no_terminal_actual": E}
   #   OR {"status": "insufficient", "n": N, "excluded_no_terminal_actual": E, "min_sample_count": floor}
   ```

   - `precision` is computed from the fast-path **PARENT** outcome only (`review_passed ∧ not escalated`), `escalation_rate` from `escalated / n`, where `n` = fast-path parents **with a terminal `actual`** (a pre-merge `merge_pending`/absent actual is excluded and reported in `excluded_no_terminal_actual`, never counted).
   - When the script returns `{"status": "insufficient", …}` (n = 0, or n below the `min_sample_count` floor), print **"insufficient samples (n=N, need ≥floor)"** — do **not** print a precision percentage. This floor exists precisely so a two-run history never masquerades as a calibrated rate. Show the sample size `n` alongside any figure you do print.

## Notes

- This command never mutates the run. To recover an interrupted run, use [`/v:resume`](v-resume.md).
- Do **not** print fabricated cost or token metrics — `state.json` carries none and neither should this output (anti-ruflo).
