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

4. **Render the per-job table.** One row per job from `state.json.jobs`, with `manifest.yaml` supplying the title and routing **intent** (`backend`, `tier`, optional `effort`).

   - For a non-pool job, resolve the concrete **model** with [`scripts/compound-v-resolve-model.py`](../scripts/compound-v-resolve-model.py) — `--backend <job.backend> --tier <job.tier> [--effort <job.effort>] --stance <routing_stance> [--config .claude/compound-v.json]`. Pass manifest `routing_stance` (default `balanced`) so a `cost-aware` job displays what dispatch actually used. An explicit manifest `model:` remains verbatim.
   - For a manifest `backend: pool` job, **do not invoke the resolver and do not read current pool config**. Read `assigned_backend` and `assigned_model` from `state.json jobs[<id>]`; optionally annotate `assignment_source` as `pool` or `fallback`. If either concrete field is absent/invalid, show `INVALID POOL STATE` and point to `/v:resume` rather than guessing.

   Show the concrete pair as a `Backend · Model` column so it is **always visible which model each job actually runs on**:

   | Job | Title | Backend · Model | Status | Liveness | Usage | Isolation | Worktree |
   |---|---|---|---|---|---|---|---|
   | task-0-schema | DB schema + types | claude · opus (deep/high) | done | — | — | direct | — |
   | task-1-editor-ui | Editor UI slice | codex · gpt-5.6-terra (standard/med) | running | WORKING | in=12.3k out=4.1k | worktree | $TMPDIR/… |

   Per-job `status` is one of `{pending | dispatched | running | done | blocked | failed}` (see state-machine.md). Show the `session_id` for any concrete Codex/worktree job that has one. If `state.json.attempts[<job>]` is present and non-zero, show the retry count for that job (e.g. an `Attempts` column or `· retried 2×`).

   **Liveness (hang detection).** Populate the `Liveness` column for any job whose `status` is `running` from [`scripts/compound-v-liveness.py`](../scripts/compound-v-liveness.py) `<run-dir> --json` — it classifies each running job from **git + filesystem only** (never model-self-report): `WORKING`, `LIKELY-DONE` (the worktree has a commit past its baseline — work landed, only the completion notification is stuck; hint: *`/v:resume`, or the dispatcher auto-collects it*), `STALE` (no progress past the threshold — a **suspected hang**), `DEAD` (a recorded pid died), or `UNKNOWN`. Non-running jobs show `—`. **Degrade-safe:** if the probe errors or is missing, show `—` for every row — never break the table. Surface any `STALE`/`DEAD` prominently in the summary and point the user at `/v:resume`. Never print fabricated metrics.

   **Usage (measured-only).** Populate the `Usage` column from [`scripts/compound-v-usage-aggregate.py`](../scripts/compound-v-usage-aggregate.py) `--run-dir <run-dir>` — it reads each job's OPTIONAL `usage` object out of `<run-dir>/results/*.json` (worker-sourced, git-collected) and returns a per-job list plus measured-only totals. Pool results and usage rows must be keyed by the recorded concrete `assigned_backend`, never `pool`. For a job whose `usage.measured == true`, show its real token counts (e.g. `in=12.3k out=4.1k`, and `+Nadv` when `advisor_calls > 0`). For any job that is **unmeasured** — `measured:false` (a backend with no machine-readable usage: agy/antigravity, claude Task subagent, devin), or no `usage` key at all — show `—`. **Measured only, never estimated:** never derive, guess, or back-fill a token number the backend did not report; an honest `—` beats a fabricated count (anti-ruflo). **Degrade-safe:** when `results/` is absent (a pending run) the aggregator returns empty totals with a `note` and exits 0 — show `—` for every row and never break the table (same rule as the Liveness column above). Optionally add a run-level total line to the summary (step 6) from the aggregator's `--format text` output (e.g. `measured: in=1.2M out=340k advisor_calls=3 | 4 measured, 2 unmeasured`) — it already reports the honest unmeasured count, so a partially-instrumented run is never dressed up as a complete one.

5. **Validate, then render backend health (the circuit breaker).** Before reading any provider
   failure field, run `python3 scripts/compound-v-pool-state.py validate` with
   `{"state": <state.json>, "jobs": <manifest jobs>}`. Only a `valid:true` result permits the
   health rendering below. On any validation error—including malformed cooldown/circuit/network
   evidence or duplicate probe ownership—show **`INVALID PROVIDER STATE`**, point to `/v:resume`,
   and render no partial cooldown, circuit, pause, owner, recovery, or retry-budget details. This
   fail-closed gate prevents malformed JSON state from being presented as trustworthy health.
   After validation, surface graceful-failure state so re-routes and credit-exhaustion are never
   silent (the fields are defined in [`state-machine.md`](../skills/compound-v/state-machine.md),
   the policy in [`failure-policy.md`](../skills/compound-v/failure-policy.md)):
   - **Circuit-open backends** — any canonical `circuit_open[<concrete-backend>].open == true` object (out for the run — out-of-credits or auth). A `pool` key or bare boolean is invalid state; call it out rather than interpreting it.
   - **Transient cooldowns / usage windows** — each canonical
     `cooldowns[<backend>] = {until, reason, opened_at, opened_by_attempt_id, probe}`: render the
     concrete backend, reason, absolute `until`, and leased probe owner. Expiry means probe
     eligibility, not health. For every far-future or suspicious value show the exact recovery
     command `/v:resume --clear-cooldown <backend>`; it clears only transient state through the
     validator, never a permanent circuit. Do not recommend hand-editing JSON.
   - **Correlated network pause** — render whether `network_pause` is active, its absolute retry
     time, and its sole probe owner. Explain that only two distinct same-batch `no_response`
     failures within 60 seconds and no completed provider success can open it; provider-reported
     failures such as z.ai 1234 do not. Recovery is one real-job probe, never fan-out.
   - **Run-level retries** — `total_retries` / `max_total_retries` (the anti retry-storm budget).
   - **Current pool assignments** — derive only the current integer counts from each pool job's recorded `assigned_backend`. State carries no assignment history, so do **not** claim a historical source/destination, number of advances, or number of jobs rerouted.
   - **Earliest reset** — only when both `state.earliest_reset_observed_at` and a positive `state.earliest_reset_seconds` exist, derive the absolute reset instant as `observed_at + seconds` and display that instant (plus a remaining duration only if still future). If the instant has passed, label it stale/passed and request a fresh probe; never restart the countdown from the status-read time. These paired fields clear when the associated out-of-credits condition resolves and no other such breaker remains. Never turn them into a quota percentage.

   Distinguish these labels exactly: **transient cooldown**, **resettable usage window**,
   **permanent circuit breaker**, and **correlated network pause**. If none of these fields are
   present (an older run, or no failures yet), skip this section.

6. **Summarize.** Counts by status (e.g. "3 done, 1 running, 1 pending"). Also group manifest pool jobs by their **current** recorded concrete `assigned_backend` and print integer job counts only, for example `Pool assignments: codex 3 · zai 2`; never percentages, token shares, credit shares, balance scores, savings, fallback annotations, or an inferred routing history. If `phase` is `BLOCKED` or any job is `blocked`/`failed`, or any canonical breaker object is open, point the user at `/v:resume {{args}}` to reconcile and re-dispatch the incomplete jobs (for an out-of-credits circuit-break, the user tops up credits first — see [`failure-policy.md`](../skills/compound-v/failure-policy.md)).

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

## Dashboard (v2.15) — `--html` / `--serve`

The same read-only state this command renders as text can be rendered as a **browser dashboard** via
[`scripts/compound-v-dashboard.py`](../scripts/compound-v-dashboard.py) — a **present-only** generator (no daemon,
no persistent service, no control surface; observe in the browser, act via the CLI). Both modes are read-only and
render **only** what is in the state files — measured-only usage (`—` when unmeasured), real counts (never a
fabricated `%`-progress), real timestamps only.

- **`/v:status --html [run-id]`** → `python3 scripts/compound-v-dashboard.py emit [--execution-root docs/superpowers/execution] [--out docs/superpowers/execution/dashboard.html]`. Writes a **self-contained static HTML snapshot** (data inlined, offline, theme-aware — good for sharing / audit) of every run + epic, and prints the file path to open (`file://…`). The generated `dashboard.html` is git-ignored (a build artifact).
- **`/v:status --serve [--port N]`** → `python3 scripts/compound-v-dashboard.py serve [--port 8787]`. Starts an **ephemeral, read-only, `127.0.0.1`-only** live viewer (GET/HEAD only, realpath-contained to the execution root, no directory-listing leak) that auto-refreshes as a run/epic progresses — the local, read-only equivalent of a competitor's live agent UI. It is a **foreground** process you Ctrl-C when done; it never backgrounds, never auto-launches, and writes nothing to any run dir. Control (merge/kill/retry) stays in the CLI by design.

The discoverable alias is [`/v:dashboard`](v-dashboard.md).

## Notes

- This command never mutates the run. To recover an interrupted run, use [`/v:resume`](v-resume.md).
- **Measured usage only, never estimated (anti-ruflo).** You MAY print the REAL token/advisor counts that `compound-v-usage-aggregate.py` extracts from each job's `results/*.json` `usage` object (worker-sourced, backend-measured). You may NOT print estimated, extrapolated, or invented cost/token numbers — `state.json` itself carries none, and an unmeasured job shows `—`, never a guessed figure. When in doubt, degrade to `—`.
