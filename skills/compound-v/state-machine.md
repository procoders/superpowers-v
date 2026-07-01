# State Machine & Resume — run dir + crash recovery

This is the **lightweight execution substrate** for an orchestrator run: a run directory plus a `state.json`. It is **not** an FSM engine — there is no daemon, no event loop, no background process. The run directory *is* the record (it doubles as the audit trail; see PRD §5.12), and `state.json` is the single source of truth for "where is this run."

Resume is **owned by Engine A** (agent + helper scripts). It is deliberately **not** a Workflows (Engine C) capability — Workflows resume is same-session-only and starts fresh after a Claude Code exit, which fails the crash case by design. So even when the opt-in Workflows accelerator runs the dispatch batch, the scope gate and the state machine below stay in Engine A's layer.

---

## States (run-level `phase`)

A run advances through seven states, plus one terminal failure state:

```
SPEC_READY ─► PREFLIGHT_DONE ─► PARTITION_VERIFIED ─► DISPATCHED ─► COLLECTED ─► REVIEWED ─► MERGED
                                                          │
                                                          └────────────► BLOCKED  (terminal)
```

| Phase | Reached when |
|---|---|
| `SPEC_READY` | A spec with feature-level Acceptance Criteria exists; the run dir is initialized. |
| `PREFLIGHT_DONE` | The three pre-flights (1A archaeology ∥ 1B domain ∥ 1C library) have produced their audits. (🔴 critical finding → HALT before this advances.) |
| `PARTITION_VERIFIED` | `partition-reviewer` returned PASS and `manifest.yaml` is materialized. (Partition FAIL → HALT.) |
| `DISPATCHED` | Jobs have been launched via [`backend-launcher`](../backend-launcher/SKILL.md); per-job status is being tracked. |
| `COLLECTED` | All jobs are terminal and `results/<id>.json` exist; the scope gate has run on every job. |
| `REVIEWED` | The three-pass Review Gate (spec / quality / final integration, AC-gated) has passed. |
| `MERGED` | Worktree diffs applied into the main tree, `finishing-a-development-branch` handed off. |
| `BLOCKED` | **Terminal.** A hard halt event fired (scope-gate BLOCKED, partition FAIL, unresolvable reviewer ISSUES, or a 🔴 pre-flight finding). The run does not merge; the offending worktree(s) are left for inspection. |

`state.json` is written **after every phase transition** so a crash never loses more than the in-flight phase.

---

## Run directory layout

```
docs/superpowers/execution/<run-id>/
├── manifest.yaml          # the contract (see execution-manifest.md)
├── state.json             # phase + per-job status (this doc)
├── jobs/
│   └── <id>.prompt.md     # the exact dispatched prompt — replayed verbatim on resume
└── results/
    └── <id>.json          # normalized job_result (schemas/job_result.schema.json)
```

- `manifest.yaml` — schema and rules live in [`execution-manifest.md`](execution-manifest.md). Read-only after materialization.
- `jobs/<id>.prompt.md` — captured at dispatch time. Resume re-dispatches **this exact prompt**, so a re-run is deterministic rather than re-derived.
- `results/<id>.json` — one normalized [`job_result`](../../schemas/job_result.schema.json) per finished job, written by the collector. Its `files_changed` / `violations` / `blocked` fields are **git-derived**, never model-self-reported.

---

## `state.json` shape

```json
{
  "run_id": "2026-06-26-linkedin-sequence-editor",
  "phase": "DISPATCHED",
  "updated_at": "2026-06-26T14:31:00Z",
  "total_retries": 2,
  "max_total_retries": 12,
  "cooldowns": { "codex": "2026-06-26T14:33:10Z" },
  "circuit_open": {
    "codex": { "open": true, "reason": "out_of_credits", "opened_at": "2026-06-26T14:32:55Z", "cleared_by": null }
  },
  "attempts": { "task-2-api": { "rate_limited": 2, "network": 1 } },
  "jobs": {
    "task-0-schema":   { "status": "done",    "isolation": "direct",   "worktree": null,                          "session_id": null },
    "task-1-editor-ui":{ "status": "running", "isolation": "worktree", "worktree": "$TMPDIR/compound-v/<run>/task-1-editor-ui", "session_id": "uuid" },
    "task-2-api":      { "status": "pending", "isolation": "direct",   "worktree": null,                          "session_id": null }
  }
}
```

### Backend-failure fields (the circuit breaker — no daemon)

These run-level fields are how graceful backend-failure handling persists across batch boundaries. The dispatcher reads them at the start/edges of each batch; nothing runs between batches. The full classify→decide→act policy is [`failure-policy.md`](failure-policy.md).

| Field | Shape | Meaning |
|---|---|---|
| `attempts` | `{ "<job-id>": { "<failure-class>": n } }` | retries this job has had **per failure-class**, so a budget burned by one class doesn't starve another. The dispatcher feeds `attempts[job][class]` as `--attempts` (per-class cap). Absent class ⇒ 0; reset/fork the counter when the job is re-routed to a different backend or the class changes. |
| `cooldowns` | `{ "<backend>": "<iso-ts>" }` | a transient-failed backend is **deprioritized** until this timestamp (eligible again next batch). |
| `circuit_open` | `{ "<backend>": { "open": bool, "reason": "out_of_credits\|auth", "opened_at": "<iso-ts>", "cleared_by": null } }` | a per-backend breaker **object** (not a bare bool). `open: true` ⇒ the backend is **out for the run**; only a confirmed `out_of_credits` or `auth` opens it. `reason` distinguishes the two so `/v:resume` can reconcile correctly (top-up vs re-auth); `cleared_by` records what closed it (`"top_up"` / `"reauth"` / `"probe"`), `null` while still open. |
| `total_retries` | `int` | run-wide retry counter — the policy's `--total-retries`. |
| `max_total_retries` | `int` (default 12) | run-level retry budget — the anti retry-storm cap (`--max-total-retries`). |

"Deprioritize, don't remove": a 429/5xx/timeout gets a short **cooldown** (open next batch), only a confirmed `out_of_credits`/`auth` opens the breaker object for the whole run.

### Per-job `status`

| Status | Meaning | Resume action |
|---|---|---|
| `pending` | Not yet dispatched (or queued behind `depends_on`). | **re-dispatch** |
| `running` | Dispatched, no terminal result captured. After a crash this is ambiguous — reconcile against git. | reconcile, then **re-dispatch if not landed** |
| `done` | Job finished, scope gate PASSED, result normalized. | skip (unless git disagrees — see git-wins) |
| `blocked` | Scope gate caught a write outside `write_allowed`. Worktree retained. | **re-dispatch** (after the partition/prompt is corrected) |
| `failed` | Worker errored, timed out, or returned non-zero. | **re-dispatch** |

The run-level `phase` and the per-job `status` map are distinct: `phase` is the pipeline stage; `status` is each job's lifecycle within `DISPATCHED`/`COLLECTED`.

---

## Liveness sweep — reconcile in-flight, not only on resume

`/v:resume` reconciles against git **after** an interruption. The dispatcher also reconciles **during** a run: between batches (and while awaiting a background job) it runs the read-only liveness probe ([`scripts/compound-v-liveness.py`](../../scripts/compound-v-liveness.py)) over `state.json` and applies the same **git-wins** rule live — a `running` job whose worktree already holds a commit past its `baseline` is `LIKELY-DONE` and is collected immediately (scope-gate + merge + `done`), rather than waiting on a completion notification that may never arrive (the "parked subagent" case). A job with no filesystem progress past the threshold is `STALE` (a suspected hang), surfaced and folded into the `timeout` failure class ([`failure-policy.md`](failure-policy.md)). No new phase, no daemon — just the git-derived probe read at batch boundaries. See [`agents/parallel-dispatcher.md`](../../agents/parallel-dispatcher.md) Step 2d.

## Resume — reconcile, then re-dispatch the incomplete

`/v:resume <run-id>` (see [`commands/v-resume.md`](../../commands/v-resume.md)) recovers a crashed or interrupted run. It is **idempotent**: resuming a fully-`MERGED` run is a no-op.

**Algorithm:**

1. **Read** `state.json` and `manifest.yaml` from the run dir.
2. **Reconcile against git reality.** For each job, observe what actually landed using the same git-derived signal the scope gate uses:
   `git -C <worktree-or-repo> diff --name-only HEAD` ∪ `git -C <worktree-or-repo> ls-files --others --exclude-standard`.
   This is "what the disk says," independent of what `state.json` claims.
3. **Apply the GIT-WINS tie-break.** When `state.json` and git disagree, **git wins**:
   - `state.json` says `done` but the job's `write_allowed` files are **not** present in git → treat as **not done**, re-dispatch.
   - `state.json` says `running`/`pending` but the files **are** fully present and inside scope → treat as `done`, skip.
   - This keeps resume safe under a crash that landed files but never got to write `state.json` — and under a stale `done` whose work was reverted.
4. **Reconcile the breaker — neither a silent retry nor a permanent lockout.** Before re-dispatching, reconcile the circuit-breaker fields. The full per-backend procedure (probe semantics, `cleared_by`) lives in [`commands/v-resume.md`](../../commands/v-resume.md); in brief:
   - **Cooldown expired (transient):** a backend whose `cooldowns[backend]` timestamp has **expired** — and which has **no** open `circuit_open` entry — goes **half-open**: probe it **once** at the start of the next batch before full re-dispatch. A clean probe clears the `cooldowns` entry; a repeat failure re-cools it via the policy.
   - **`circuit_open[backend].open==true` with `reason=="out_of_credits"`:** stays **open** — `/v:resume` does **not** reopen it automatically. Clear it (set `cleared_by`) only when the user confirms a top-up **or** a cheap liveness probe (a tiny "reply ok" call) succeeds; then re-dispatch that backend's failed jobs (the run-level `total_retries` budget persists across the resume).
   - **`circuit_open[backend].open==true` with `reason=="auth"`:** stays **open** until the user re-auths (via `/v:init`); only then clear it (`cleared_by`) and re-dispatch its failed jobs.
   - **Never silently re-dispatch to a still-open breaker.** An open `out_of_credits`/`auth` breaker that the user hasn't resolved keeps its jobs `failed` and surfaced, not re-tried.
5. **Re-dispatch only `pending` / `failed` / `blocked`** jobs (after step 3 reclassification and step 4 breaker reconciliation), honoring `depends_on` and `max_parallel` exactly as the initial dispatch did. Each re-dispatch replays `jobs/<id>.prompt.md` verbatim.
   - For a Codex worktree job whose `session_id` is recorded, the codex adapter MAY resume the existing session (`codex exec resume <session_id>`) rather than start cold; either way the **scope gate re-runs** on return.
6. **Continue the pipeline** from the reconciled phase: re-collect, re-run the scope gate on every job, then the Review Gate, then merge. Already-`done` jobs are not re-run.

**Why git-wins, restated:** `state.json` is a convenience cache; the filesystem under git is the ground truth. A resume that trusted a stale `done` could skip work that was never actually committed. By re-deriving from git on every resume, the run stays correct even across a hard crash mid-write.

---

## Cross-references

- Graceful backend-failure policy (classify → retry/reroute/halt; the circuit-breaker fields above): [`failure-policy.md`](failure-policy.md)
- Manifest schema + invariants: [`execution-manifest.md`](execution-manifest.md)
- The job_result contract every `results/<id>.json` conforms to: [`schemas/job_result.schema.json`](../../schemas/job_result.schema.json)
- Backend dispatch contract: [`backend-launcher/SKILL.md`](../backend-launcher/SKILL.md)
- Status rendering: [`commands/v-status.md`](../../commands/v-status.md) · Resume: [`commands/v-resume.md`](../../commands/v-resume.md)
