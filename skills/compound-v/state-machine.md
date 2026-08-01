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

**Written to disk is not the same as durable — the run directory must be explicitly committed.**
"The run directory *is* the record" (above) is a promise that only holds if it's actually in git.
Two mandatory commit points close the gap (a real incident — noticed by Oscar Salcedo — is what
surfaced this): [`/v:orchestrate`](../../commands/v-orchestrate.md) commits `manifest.yaml` +
the initial `state.json` right after materializing them, and
[`parallel-dispatcher`](../../agents/parallel-dispatcher.md) commits the full run directory
(final `state.json`, `results/*.json`) before handing off to
`superpowers:finishing-a-development-branch`. This matters because that skill's cleanup step runs
`git worktree remove` on Merge/Discard — a normal git operation that **silently deletes any
uncommitted files** in the worktree, no warning, no confirmation. Skip either commit point and a
crash, an early "discard," or just reaching the worktree-cleanup step can erase the run's own
audit trail — `/v:status` will then honestly (and confusingly) report no runs ever happened.

---

## v2.9 — Pre-Eval, fast-path & escalation states

v2.9 adds a pre-brainstorm **Pre-Evaluation** stage and a proportionate **fast-path**. It introduces
three new lifecycle tokens. Read them with one distinction firmly in mind (AC-7/CR2-8):

| Token | Kind | Lives in | Reached when |
|---|---|---|---|
| `PRE_EVAL_DONE` | **record status field**, NOT a `state.json` phase | the write-once pre-eval **record** `docs/superpowers/pre-eval/<pre_eval_id>.json` (`status` field) | Score computed + record written **and committed**. **There is no `state.json` / run dir at prediction time** — the run dir is created post-plan (`v-orchestrate` Step 3), so `PRE_EVAL_DONE` cannot be a run phase. |
| `FASTPATH_DISPATCHED` | real `state.json` **phase** | `state.json.phase` (a run exists by now) | Fast-path was eligible, the user accepted, and the single-job fast-path manifest was materialized + dispatched. |
| `ESCALATION_REQUIRED` | real `state.json` **phase** | `state.json.phase` | The post-hoc diff re-classification failed; the patch is preserved as evidence and the pipeline rejoins the full path via a **new** run. |

**No script hard-codes any phase enum** (phases are prose-only; `compound-v-liveness.py` keys on
per-job `status`, not run `phase`). This section is the authority readers (`/v:status`, `/v:resume`,
`parallel-dispatcher`) implement against.

### Transitions

```
PRE_EVAL_DONE ─(eligible ∧ accept)─► FASTPATH_DISPATCHED ─► [scope-gate + test floor + F2]
    ├─(F2 clean)──────► REVIEWED (1 combined SPEC+QUALITY pass) ─► MERGED
    └─(F2 escalates)─► ESCALATION_REQUIRED ─► PREFLIGHT_DONE ─► PARTITION_VERIFIED ─► … (normal)
PRE_EVAL_DONE ─(not eligible ∨ decline ∨ fast_path:off)─► SPEC_READY ─► … (normal)
```

- **Accepted fast-path:** the linked run **initializes at `FASTPATH_DISPATCHED`**.
- **Decline / not-eligible / `off`:** the run **initializes normally** (`SPEC_READY`), exactly as
  pre-v2.9. Pre-eval is fail-closed — a missed or disabled pre-eval simply degrades to the normal
  pipeline (AC-6; PRE_EVAL is description-driven and unenforceable — never claim it is enforced).

### New `state.json` fields (v2.9)

| Field | Shape | Meaning |
|---|---|---|
| `pre_eval_id` | string \| null | The write-once id (`YYYY-MM-DDThhmmssZ-<slug>-<nonce>`) of the pre-eval record this run was materialized from. Present on any pre-eval-backed run (fast-path OR a declined pre-eval that later became a normal run — bound for both, CR3-2). `null` for runs created without a pre-eval. |
| `escalated_to` | string \| null | On `ESCALATION_REQUIRED`, the **new** run-id of the full-pipeline child the fast-path escalated into. `null` otherwise. The fast-path patch stays under the ORIGINAL run as evidence; the child starts from the clean baseline. |

The frozen `manifest.yaml` is **never mutated in place** on escalation (AC-4/H1) — `/v:resume`
replays a fixed job set, so escalation mints a new run and links it via `escalated_to`.

### Idempotent two-phase escalation protocol (AC-15/CR2-4)

Escalation is **crash-consistent**. Every boundary below is a two-command commit (no `&&`, each exit
code checked) and a resume checkpoint:

1. **Commit patch + baseline evidence** under the original run (the fast-path diff + its immutable
   pre-launch baseline SHA) — real evidence overriding the wrong prediction.
2. **Derive a deterministic child run-id** from the parent (same parent ⇒ same child id) so a
   re-run never mints a second child.
3. **Create + commit the child** full-pipeline run (its own run dir + initial `state.json`), starting
   from the **clean baseline** (the preserved patch is evidence only, not applied).
4. **Commit the parent's `escalated_to`** link **LAST** — so a committed `escalated_to` ⇒ the child
   is already durable.

`/v:resume` **reconciles every partial state** and **discovers an existing child before minting
another**: if step 2's deterministic child id already has a run dir, resume adopts it rather than
creating a duplicate.

### Fast-path resume reconciles against the pinned baseline, never HEAD (CR5-3)

A fast-path run persists **each job's immutable pre-launch baseline SHA** in `state.json` and
reconciles against **THAT**, never `HEAD` — a worker may commit and move `HEAD`, so a HEAD-relative
diff would go blind (the same reason the scope gate baselines against the recorded pre-`worktree add`
SHA). Completion of a fast-path job requires the normalized result **and** the git-derived scope
verdict **and** the baseline-relative patch digest to agree. `FASTPATH_DISPATCHED` reconciles like
`DISPATCHED`; `ESCALATION_REQUIRED` follows `escalated_to` and never replays the fast-path job set
against a full manifest.

### Unbound pre-eval discovery (`/v:status`)

A pre-eval record can exist with **no run** (declined, or crashed before materialization). `/v:status`
discovers these **unbound** records under `docs/superpowers/pre-eval/` (a `predicted` triage event
with no `bind`) and renders their decision + derived 1-10 alongside real runs, so a pre-eval'd
request is never invisible. Fast-path **precision + escalation-rate** are computed from the
`triage-outcomes.jsonl` `predicted`↔`actual` join (git-derived actuals only), shown with their sample
size and "insufficient samples" below the floor — never a fabricated number (AC-12).

---

## Run directory layout

```
docs/superpowers/execution/<run-id>/
├── manifest.yaml          # the contract (see execution-manifest.md)
├── state.json             # phase + per-job status (this doc)
├── jobs/
│   └── <id>.prompt.md     # the exact dispatched prompt — replayed verbatim on resume
├── logs/
│   └── <id>.jsonl         # codex worker's --json event stream (session-aware workers)
└── results/
    └── <id>.json          # normalized job_result (schemas/job_result.schema.json)
```

- `manifest.yaml` — schema and rules live in [`execution-manifest.md`](execution-manifest.md). Read-only after materialization.
- `jobs/<id>.prompt.md` — captured at dispatch time. Resume re-dispatches **this exact prompt**, so a re-run is deterministic rather than re-derived.
- `logs/<id>.jsonl` — the codex worker's `--json` event stream, one file per codex job (the dispatcher passes `--events-log docs/superpowers/execution/<run-id>/logs/<id>.jsonl` and records that path into `state.json jobs[<id>].log`). Present only for codex jobs; the liveness sweep reads the newest event as a progress signal. Degrade-safe: absent ⇒ prior git+FS+pid behavior unchanged.
- `results/<id>.json` — one normalized [`job_result`](../../schemas/job_result.schema.json) per finished job, written by the collector. Its `files_changed` / `violations` / `blocked` fields are **git-derived**, never model-self-reported.

---

## `state.json` shape

```json
{
  "run_id": "2026-06-26-linkedin-sequence-editor",
  "phase": "DISPATCHED",
  "updated_at": "2026-06-26T14:31:00Z",
  "pre_eval_id": null,
  "escalated_to": null,
  "total_retries": 2,
  "max_total_retries": 12,
  "earliest_reset_observed_at": "2026-06-26T14:32:55Z",
  "earliest_reset_seconds": 120,
  "backend_max_parallel": { "zai": 4 },
  "cooldowns": { "codex": "2026-06-26T14:33:10Z" },
  "circuit_open": {
    "codex": { "open": true, "reason": "out_of_credits", "opened_at": "2026-06-26T14:32:55Z", "cleared_by": null }
  },
  "pool_members": {
    "standard": [
      { "backend": "codex", "model": "gpt-5.6-terra", "available": true },
      { "backend": "zai", "model": "glm-5.2", "available": true }
    ]
  },
  "attempts": { "task-2-api": { "rate_limited": 2, "network": 1 } },
  "jobs": {
    "task-0-schema":   { "status": "done",    "isolation": "direct",   "worktree": null,                          "session_id": null,   "log": null },
    "task-1-editor-ui":{ "status": "running", "isolation": "worktree", "worktree": "$TMPDIR/compound-v/<run>/task-1-editor-ui", "session_id": "uuid", "log": "docs/superpowers/execution/<run>/logs/task-1-editor-ui.jsonl" },
    "task-2-api":      { "status": "pending", "isolation": "worktree", "worktree": "$TMPDIR/compound-v/<run>/task-2-api", "session_id": null, "log": null, "assigned_backend": "zai", "assigned_model": "glm-5.2", "assignment_source": "pool", "pool_index": 1, "pool_tier": "standard" }
  }
}
```

Per-job fields: `status` (lifecycle, below), `isolation` (`direct` | `worktree`), `worktree` (absolute path or `null`), `session_id` (the codex `thread_id` UUID read from the worker's `job_result.session_id`, UUID-validated — the resume UUID; `null` otherwise), `failure_class` (the returned `job_result.failure_class`, e.g. `timeout`/`network`; consulted by the resume-eligibility rule; `null` otherwise), `baseline` (the **immutable pre-launch baseline SHA** the scope gate — and, on a fast-path job, the post-hoc reclassifier — attribute against; recorded at dispatch, reconciled against on resume, **never** re-derived from a moved `HEAD`; CR5-3), and **`log`** (the codex worker's events-log path — `docs/superpowers/execution/<run-id>/logs/<id>.jsonl` — recorded by the dispatcher at dispatch; `null`/absent for non-codex jobs). A pool-routed job additionally carries the load-bearing assignment fields below. `log` is read by the liveness sweep as a progress signal and is **degrade-safe**: absent ⇒ prior git+FS+pid behavior unchanged.

### Frozen pool assignment fields

At run start, before any job launches, the dispatcher runs `compound-v-project-config.py` once and sends the normalized `pools`, `models`, manifest `jobs` in original order, stance, and current state to `compound-v-pool-state.py freeze`. The successful output atomically replaces `state.json`; then `compound-v-pool-state.py validate` must exit 0. This is the only assignment freeze. Re-running the helper against a state that already has `pool_members` may validate/preserve it, but current config must never replace it.

| Field | Shape | Meaning |
|---|---|---|
| `pool_members` | `{ "<tier>": [{ "backend": str, "model"?: str, "available": bool }, ...] }` | Expanded weighted slots frozen once. Unavailable slots remain positional tombstones; the ring is never resized. |
| `jobs[id].assigned_backend` | concrete backend string | Backend supplied to every backend-keyed consumer. Never `pool`. |
| `jobs[id].assigned_model` | non-empty string | Concrete model supplied to the worker and status/memory rows. |
| `jobs[id].assignment_source` | `"pool"` or `"fallback"` | `pool` means the pair matches the frozen slot. `fallback` is the recorded ordinary concrete fallback after ring exhaustion; it may differ from the originating slot. Missing on legacy state is treated as `pool`. |
| `jobs[id].pool_index` | non-negative integer | Current/originating index in the exact expanded frozen tier ring. It is the manifest-order ordinal modulo the ring, advanced across unavailable/open slots without shrinking. A fallback retains the originating index. |
| `jobs[id].pool_tier` | `standard` or `light` — never `deep` | Frozen tier lookup key; must match the manifest tier. Pooling `deep` is a stated Non-goal; `compound-v-validate-manifest.py` rejects any `backend: pool` job at `tier: deep` before it can reach `state.json`, matching [`routing-policy.md`](routing-policy.md) and [`execution-manifest.md`](execution-manifest.md). |
| `backend_max_parallel` | `{ "<concrete-backend>": positive-int }` | Normalized run-start batching ceilings copied from config so resume does not change them after a config edit. Prose-enforced batching contract, not a semaphore claim. |

`assignment_source: "pool"` requires the recorded backend/model to match the exact available frozen slot at `pool_members[pool_tier][pool_index]`. `assignment_source: "fallback"` permits a different known-concrete backend/model while still requiring a valid originating tier/index. Unknown source/backend, a missing model, or malformed ring context fails closed. `compound-v-pool-state.py resume` validates and returns the recorded concrete pair; it never derives from config or a counter.

The same helper validates the canonical circuit map before freeze/select/state-validation/resume: `state.circuit_open` must be an object keyed only by known concrete backends; each value has exactly `open`, `reason`, `opened_at`, and `cleared_by`, never a bare boolean. `opened_at` is always a non-empty string. Open entries require `reason: out_of_credits|auth` and `cleared_by: null`. A closed entry preserves its reason and records the matching recovery: `auth` requires `cleared_by: reauth`; `out_of_credits` requires `cleared_by: top_up|probe`. Null or cross-reason clearance pairs are rejected fail-closed.

The ordinal is counted independently per tier from manifest order among `backend: pool` jobs. Dispatch timing, `depends_on`, batching, retries, and config edits never affect it. A transient `rate_limited`/overloaded/network/timeout retry preserves the complete assignment. Only an `out_of_credits` policy decision can replace it: record either the selected `next_pool_index` pair (`assignment_source: "pool"`) or the resolved ordinary fallback pair (`assignment_source: "fallback"`), increment the run budget when `consume_total_retry` is true, validate, then relaunch.

### Backend-failure fields (the circuit breaker — no daemon)

These run-level fields are how graceful backend-failure handling persists across batch boundaries. The dispatcher reads them at the start/edges of each batch; nothing runs between batches. The full classify→decide→act policy is [`failure-policy.md`](failure-policy.md).

| Field | Shape | Meaning |
|---|---|---|
| `attempts` | `{ "<job-id>": { "<failure-class>": n } }` | retries this job has had **per failure-class**, so a budget burned by one class doesn't starve another. The dispatcher feeds `attempts[job][class]` as `--attempts` (per-class cap). Absent class ⇒ 0; reset/fork the counter when the job is re-routed to a different backend or the class changes. |
| `cooldowns` | `{ "<backend>": "<iso-ts>" }` | a transient-failed backend is **deprioritized** until this timestamp (eligible again next batch). |
| `circuit_open` | `{ "<concrete-backend>": { "open": bool, "reason": "out_of_credits\|auth", "opened_at": "<iso-ts>", "cleared_by": null } }` | the one canonical per-concrete-backend breaker map. Values are objects, never bare booleans; `pool` is never a key. `open: true` ⇒ the backend is **out for the run**; only a confirmed `out_of_credits` or `auth` opens it. `reason` distinguishes the two so `/v:resume` can reconcile correctly (top-up vs re-auth); `cleared_by` records what closed it (`"top_up"` / `"reauth"` / `"probe"`), `null` while still open. |
| `total_retries` | `int` | run-wide retry counter — the policy's `--total-retries`. |
| `max_total_retries` | `int` (default 12) | run-level retry budget — the anti retry-storm cap (`--max-total-retries`). |
| `earliest_reset_observed_at` | ISO timestamp or `null` | Observation time paired with `earliest_reset_seconds`; the seconds value is relative to this instant, not to the next read. |
| `earliest_reset_seconds` | positive number or `null` | Provider-relative reset delay observed at `earliest_reset_observed_at`. Compare/reset using the derived absolute instant; clear both fields when the associated exhaustion is resolved. `/v:status` never renders it as a percentage. |

"Deprioritize, don't remove": a 429/5xx/timeout gets a short **cooldown** (open next batch), only a confirmed `out_of_credits`/`auth` opens the breaker object for the whole run.

### Per-job `status`

| Status | Meaning | Resume action |
|---|---|---|
| `pending` | Not yet dispatched (or queued behind `depends_on`). | **re-dispatch** |
| `dispatched` | Concrete assignment written and launch initiated, before the running transition is persisted. | reconcile, then **re-dispatch if not landed** |
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

> **Pool-assignment resume rule (Shared Interface Contract — byte-identical in `commands/v-resume.md`, `agents/parallel-dispatcher.md`, and `skills/compound-v/state-machine.md`).**
> Before any git or breaker reconciliation, if the manifest contains a job whose routing token is `backend: pool`, validate the complete recorded state with `python3 scripts/compound-v-pool-state.py validate` using `{"state": <state.json>, "jobs": <manifest jobs>}`; any error HALTS resume.
> Then obtain only that job's concrete pair with `python3 scripts/compound-v-pool-state.py resume` using `{"state": <state.json>, "job_id": "<id>"}`; the helper returns only `assigned_backend` and `assigned_model`.
> Read `assignment_source`, `pool_index`, `pool_tier`, and `worktree` directly from the already-validated `state.json jobs[<id>]` record and reuse all six recorded values for reconciliation.
> Never reload current pool config, recompute a manifest ordinal, rerun freeze, or call the model resolver for that recorded assignment. A transient retry preserves it byte-for-byte; only an `out_of_credits` policy decision may replace it, and the replacement MUST be written and validated before relaunch.

2. **Reconcile against git reality.** For each job, observe what actually landed using the same git-derived signal the scope gate uses:
   `git -C <worktree-or-repo> diff --name-only HEAD` ∪ `git -C <worktree-or-repo> ls-files --others --exclude-standard`.
   This is "what the disk says," independent of what `state.json` claims.
3. **Apply the GIT-WINS tie-break.** When `state.json` and git disagree, **git wins**:
   - `state.json` says `done` but the job's `write_allowed` files are **not** present in git → treat as **not done**, re-dispatch.
   - `state.json` says `running`/`dispatched`/`pending` but the files **are** fully present and inside scope → treat as `done`, skip.
   - This keeps resume safe under a crash that landed files but never got to write `state.json` — and under a stale `done` whose work was reverted.
4. **Reconcile the breaker — neither a silent retry nor a permanent lockout.** Before re-dispatching, reconcile the canonical `circuit_open` object map by concrete backend (`assigned_backend` for a pool job; never a `pool` key). The full per-backend procedure (probe semantics, `cleared_by`) lives in [`commands/v-resume.md`](../../commands/v-resume.md); in brief:
   - **Cooldown expired (transient):** a backend whose `cooldowns[backend]` timestamp has **expired** — and which has **no** open `circuit_open` entry — goes **half-open**: probe it **once** at the start of the next batch before full re-dispatch. A clean probe clears the `cooldowns` entry; a repeat failure re-cools it via the policy.
   - **`circuit_open[backend].open==true` with `reason=="out_of_credits"`:** stays **open** — `/v:resume` does **not** reopen it automatically. Clear it (set `cleared_by`) only when the user confirms a top-up **or** a cheap liveness probe (a tiny "reply ok" call) succeeds; then re-dispatch that backend's failed jobs. Clear the paired earliest-reset observation when no other out-of-credits breaker remains; otherwise retain/recompute only from fresh evidence. The run-level `total_retries` budget persists across resume.
   - **`circuit_open[backend].open==true` with `reason=="auth"`:** stays **open** until the user re-auths (via `/v:init`); only then clear it (`cleared_by`) and re-dispatch its failed jobs.
   - **Never silently re-dispatch to a still-open breaker.** An open `out_of_credits`/`auth` breaker that the user hasn't resolved keeps its jobs `failed` and surfaced, not re-tried.
5. **Re-dispatch `pending` / `failed` / `blocked` jobs, plus `dispatched` / `running` jobs that git-wins found not landed** (after step 3 reclassification and step 4 breaker reconciliation), honoring `depends_on`, manifest `max_parallel`, and frozen run-start `backend_max_parallel` ceilings against each concrete assignment exactly as the initial dispatch did. Each re-dispatch replays `jobs/<id>.prompt.md` verbatim.

Both Codex resume inputs live in `state.json jobs[<id>]`. A job with an empty `session_id` has no session to resume ⇒ recreate fresh regardless.

> **Resume-eligibility rule (Shared Interface Contract — byte-identical in `commands/v-resume.md`, `agents/parallel-dispatcher.md`, and `skills/compound-v/state-machine.md`).**
> A codex worktree job may be resumed via `codex exec resume <captured-uuid>` **IFF** its `failure_class` is
> environmental (`timeout` | `network`) **AND** its worktree still exists at the recorded path.
> Every other case recreates the worktree **fresh at HEAD** — the parallel-dispatcher worktree-recreate invariant.
> Never resume by cwd filtering; pass the captured UUID explicitly.

Either way the **scope gate re-runs** on return.
6. **Continue the pipeline** from the reconciled phase: re-collect, re-run the scope gate on every job, then the Review Gate, then merge. Already-`done` jobs are not re-run.

**Why git-wins, restated:** `state.json` is a convenience cache; the filesystem under git is the ground truth. A resume that trusted a stale `done` could skip work that was never actually committed. By re-deriving from git on every resume, the run stays correct even across a hard crash mid-write.

---

## Cross-references

- Graceful backend-failure policy (classify → retry/reroute/halt; the circuit-breaker fields above): [`failure-policy.md`](failure-policy.md)
- Manifest schema + invariants: [`execution-manifest.md`](execution-manifest.md)
- The job_result contract every `results/<id>.json` conforms to: [`schemas/job_result.schema.json`](../../schemas/job_result.schema.json)
- Backend dispatch contract: [`backend-launcher/SKILL.md`](../backend-launcher/SKILL.md)
- Status rendering: [`commands/v-status.md`](../../commands/v-status.md) · Resume: [`commands/v-resume.md`](../../commands/v-resume.md)
