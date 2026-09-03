---
description: Render the state of a Compound V orchestrator run — pipeline phase plus a per-job status table — by reading state.json from the run directory. Optional run-id argument; without one, list runs and pick the most recent.
---

You are about to render the **state of a Compound V orchestrator run**. This is read-only: it inspects `state.json`, it does not dispatch, collect, or merge anything.

The run-id (optional) is `{{args}}`.

## Steps

1. **Parse `{{args}}`, then locate the run.** `--live` is the only flag this command recognizes. If
   `{{args}}` is exactly `--live`, or starts with `--live` followed by whitespace, strip that leading
   token, note that the live watch (step "Live watch" below) is requested, and treat whatever remains
   (trimmed) as the run-id for the rest of this step — e.g. `--live 2026-09-01-foo` locates run
   `2026-09-01-foo` and requests the watch; a bare `--live` requests the watch with no run-id, same as
   the no-argument case below. `{{args}}` with no leading `--live` is a bare run-id (or empty), exactly
   as before, and the live watch is not requested.
   - If the (flag-stripped) `{{args}}` names a run-id, the run dir is `docs/superpowers/execution/<run-id>/`.
   - If `{{args}}` is empty, list the subdirectories of `docs/superpowers/execution/` — **except `epics/`**, which holds epic spines (`epics/<epic-id>/epic-state.json`), not runs; it is rendered by the "Epic progress" section below, never as a run row. If there is exactly one, use it. If there are several, show them (newest first by run-id date prefix) and render the most recent, noting the others.
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

   | Job | Title | Backend · Model | Status | Liveness | Usage | Isolation | Worktree |
   |---|---|---|---|---|---|---|---|
   | task-0-schema | DB schema + types | claude · opus (deep/high) | done | — | — | direct | — |
   | task-1-editor-ui | Editor UI slice | codex · gpt-5.6-terra (standard/med) | running | WORKING | in=12.3k out=4.1k | worktree | $TMPDIR/… |

   If a job carries an explicit `model:` override in the manifest, show that verbatim (resolution is skipped for it). Per-job `status` is one of `{pending | running | done | blocked | failed}` (see state-machine.md). Show the `session_id` for any Codex/worktree job that has one. If `state.json.attempts[<job>]` is present and non-zero, show the retry count for that job (e.g. an `Attempts` column or `· retried 2×`).

   **Liveness (hang detection).** Populate the `Liveness` column for any job whose `status` is `running` from [`scripts/compound-v-liveness.py`](../scripts/compound-v-liveness.py) `<run-dir> --json` — it classifies each running job from **git + filesystem only** (never model-self-report): `WORKING`, `LIKELY-DONE` (the worktree has a commit past its baseline — work landed, only the completion notification is stuck; hint: *`/v:resume`, or the dispatcher auto-collects it*), `STALE` (no progress past the threshold — a **suspected hang**), `DEAD` (a recorded pid died), or `UNKNOWN`. Non-running jobs show `—`. **Degrade-safe:** if the probe errors or is missing, show `—` for every row — never break the table. Surface any `STALE`/`DEAD` prominently in the summary and point the user at `/v:resume`. Never print fabricated metrics.

   **Usage (measured-only).** Populate the `Usage` column from [`scripts/compound-v-usage-aggregate.py`](../scripts/compound-v-usage-aggregate.py) `--run-dir <run-dir>` — it reads each job's OPTIONAL `usage` object out of `<run-dir>/results/*.json` (worker-sourced, git-collected) and returns a per-job list plus measured-only totals. For a job whose `usage.measured == true`, show its real token counts (e.g. `in=12.3k out=4.1k`, and `+Nadv` when `advisor_calls > 0`). For any job that is **unmeasured** — `measured:false` (a backend with no machine-readable usage: agy/antigravity, claude Task subagent, devin), or no `usage` key at all — show `—`. **Measured only, never estimated:** never derive, guess, or back-fill a token number the backend did not report; an honest `—` beats a fabricated count (anti-ruflo). **Degrade-safe:** when `results/` is absent (a pending run) the aggregator returns empty totals with a `note` and exits 0 — show `—` for every row and never break the table (same rule as the Liveness column above). Optionally add a run-level total line to the summary (step 6) from the aggregator's `--format text` output (e.g. `measured: in=1.2M out=340k advisor_calls=3 | 4 measured, 2 unmeasured`) — it already reports the honest unmeasured count, so a partially-instrumented run is never dressed up as a complete one.

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

## Epic progress (3.4.0)

Additive and **degrade-safe**, exactly like the two sections above: if there are no epics, or if the
probe fails, render an em-dash or skip the section — never invent an epic state.

10. **Render one progress row per epic in this project.** For each
    `docs/superpowers/execution/epics/*/epic-state.json`, ask the read-only probe:

    ```bash
    python3 scripts/compound-v-epic-state.py --stats \
      --state docs/superpowers/execution/epics/<epic-id>/epic-state.json
    # → {"epic_id":…, "status":…, "total":…, "done":…, "pending":…, "running":…,
    #    "failed":…, "blocked":…, "remaining":…}
    ```

    `--stats` is **strictly read-only** — it never mutates the state and its CLI branch never writes
    the file. Render one row per epic:

    | Epic | Status | Done / total | Remaining |
    |---|---|---|---|
    | 2026-08-02-billing | running | 3 / 7 | 4 |
    | 2026-07-19-search | blocked_needing_human | 5 / 5 | 0 |

    **A terminal epic is not a finished epic.** `blocked_needing_human` means it stopped, not that it
    completed — report the status verbatim and never soften it into "done". `/v:epic`'s own
    `--next --autonomous` reason is the authority on why it stopped; this table is counts only.

    **Degrade-safe, in every direction.** No `docs/superpowers/execution/epics/` directory → skip the
    section entirely. A probe that exits non-zero, prints nothing, or prints unparsable JSON → one row
    with `—` in every column and a plain note that the epic state could not be read; never break the
    table and never guess.

## Live watch (v3.4.2) — `--live`

**`/v:status --live [run-id]`** runs a single, read-only advisory pass over the run's live agent
transcripts — the same transcripts the harness's own `/workflows`/`/tasks` views draw from — and prints
what it finds **after** the state table above, never in place of it:

```bash
python3 scripts/compound-v-transcript-watch.py --run-dir docs/superpowers/execution/<run-id> --once
```

The script discovers the run's workflow transcript directory itself (no `--wf` needed — it scans for the
run directory's absolute path inside the agents' own `register-lane` calls, newest match wins) and emits
one line per **new** signal since its last state: `out-of-lane`, `wrong-cwd`, `error`, `stall`, `denied`.
It is advisory only — it never acts on a signal, never mutates the run, and exits 0 on every path. Print
its lines verbatim under the per-job table; a clean pass with no new signals is worth stating explicitly
("no new signals") rather than silently omitting the section.

**Degrade-safe, same rule as every other optional section in this file.** If
`scripts/compound-v-transcript-watch.py` is missing, the run's transcripts cannot be found, or the
probe errors or exits non-zero, say so in one line ("live watch unavailable: no transcripts found for
this run" or similar) and stop there — never show a traceback or raw stack output, and never break the
state table rendered above it.

## Dashboard (v2.15) — `--html`

The same read-only state this command renders as text can be rendered as a **browser dashboard** via
[`scripts/compound-v-dashboard.py`](../scripts/compound-v-dashboard.py) — a **present-only** generator (no daemon,
no persistent service, no control surface; observe in the browser, act via the CLI). It is read-only and
renders **only** what is in the state files — measured-only usage (`—` when unmeasured), real counts (never a
fabricated `%`-progress), real timestamps only.

**For a LIVE view, use the native surfaces.** The bespoke local HTTP server was removed in v3.4 (native-first):
[`/workflows`](https://code.claude.com/docs/en/workflows) shows a running dispatch's live progress, and `/tasks`
shows `state.json` / `epic-state.json` progress for runs and epics without a snapshot step. `emit` is for a
shareable, offline artifact — not for watching a dispatch in progress.

- **`/v:status --html [run-id]`** → `python3 scripts/compound-v-dashboard.py emit [--execution-root docs/superpowers/execution] [--out docs/superpowers/execution/dashboard.html]`. Writes a **self-contained static HTML snapshot** (data inlined, offline, theme-aware — good for sharing / audit) of every run + epic, and prints the file path to open (`file://…`). The generated `dashboard.html` is git-ignored (a build artifact).
- **Resume context (banner-internal, v2.19)** → `python3 scripts/compound-v-dashboard.py resume [--max-age-hours N] [--json]`. Prints ONE line naming unfinished runs/epics, or nothing at all. It exists because `SessionStart` fires on **`compact`** and the banner is otherwise stateless: a compaction destroys the agent's *position* in a pipeline, not its knowledge of the rules. Freshness comes from the **recorded** `updated_at`/`last_progress_at`, never a file mtime — git rewrites mtimes on clone and branch-switch, which would make every historical run look seconds old on a fresh checkout. A record with no recorded timestamp stays **silent** rather than being assigned a fabricated age.

The discoverable alias is [`/v:dashboard`](v-dashboard.md).

## Notes

- This command never mutates the run. To recover an interrupted run, use [`/v:resume`](v-resume.md).
- **Measured usage only, never estimated (anti-ruflo).** You MAY print the REAL token/advisor counts that `compound-v-usage-aggregate.py` extracts from each job's `results/*.json` `usage` object (worker-sourced, backend-measured). You may NOT print estimated, extrapolated, or invented cost/token numbers — `state.json` itself carries none, and an unmeasured job shows `—`, never a guessed figure. When in doubt, degrade to `—`.
