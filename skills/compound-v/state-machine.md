# State Machine & Resume — run dir + crash recovery

This is the **lightweight execution substrate** for an orchestrator run: a run directory plus a `state.json`. It is **not** an FSM engine — there is no daemon, no event loop, no background process. The run directory *is* the record (it doubles as the audit trail; see PRD §5.12), and `state.json` is the single source of truth for "where is this run."

Resume is **owned by the verification layer** (`state.json` + the helper scripts), not by any engine. It is deliberately **not** the native runtime's resume: that is same-session-only, starts fresh after a Claude Code exit — which fails the crash case by design — and, past a failure point, **re-runs completed agents**, so a 16-job run whose job 3 failed would re-run jobs 4–16 that already succeeded.

**Since 3.0 the scope gate and the state write happen INSIDE the run, on Engine C.** That reverses what this file said in 1.0, and the reversal is deliberate: keeping them "outside" kept them in prose, and on the `claude` backend — 73 of 73 recorded jobs — no program ran the gate at all. See [`workflows-accelerator.md`](workflows-accelerator.md) and [`ADR 0004`](../../docs/superpowers/adr/0004-workflow-as-the-dispatch-engine.md). What did **not** move is this document: cross-session recovery, and the git-derived integration postcondition that decides what enters the tree, remain here.

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
the initial `state.json` right after materializing them, and the dispatch engine commits the full
run directory (final `state.json`, `results/*.json`) before handing off to
`superpowers:finishing-a-development-branch` — Engine C
([`scripts/compound-v-emit-workflow.py`](../../scripts/compound-v-emit-workflow.py)) by default since
3.0, and the residual [`parallel-dispatcher`](../../agents/parallel-dispatcher.md) subagent as the
fallback where no Workflow tool exists. This matters because that skill's cleanup step runs
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
Engine C and the residual `parallel-dispatcher` fallback) implement against.

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
├── manifest.yaml            # the contract (see execution-manifest.md)
├── state.json               # phase + per-job status (this doc)
├── dispatch.workflow.js     # Engine C: the EXACT orchestration that ran (committed)
├── lane-map.json            # agent/worktree -> job id, read by hooks/lane-guard.sh
├── jobs/
│   ├── <id>.prompt.md            # the exact dispatched prompt — replayed verbatim on resume
│   └── <id>.test-contract.json   # the RESOLVED test slice handed to the worker as an argument
├── logs/
│   └── <id>.jsonl           # codex worker's --json event stream (session-aware workers)
├── receipts/
│   └── <id>.gate.json       # the Gate stage's raw six-field receipt, as produced
└── results/
    ├── <id>.json            # normalized job_result (schemas/job_result.schema.json) — EXACTLY ONE
    └── attempts/
        └── <id>.<n>.json    # superseded attempts, archived out of the gate's line of sight
```

- `manifest.yaml` — schema and rules live in [`execution-manifest.md`](execution-manifest.md). Read-only after materialization.
- `jobs/<id>.prompt.md` — captured at dispatch time. Resume re-dispatches **this exact prompt**, so a re-run is deterministic rather than re-derived.
- `logs/<id>.jsonl` — the codex worker's `--json` event stream, one file per codex job (the dispatcher passes `--events-log docs/superpowers/execution/<run-id>/logs/<id>.jsonl` and records that path into `state.json jobs[<id>].log`). Present only for codex jobs; the liveness sweep reads the newest event as a progress signal. Degrade-safe: absent ⇒ prior git+FS+pid behavior unchanged.
- `results/<id>.json` — one normalized [`job_result`](../../schemas/job_result.schema.json) per finished job. Its `files_changed` / `violations` / `blocked` fields are **git-derived**, never model-self-reported.

  **Exactly one per job, and the naming is enforced.** [`compound-v-integration-gate.py`](../../scripts/compound-v-integration-gate.py) treats any sibling `results/<id>.<anything>.json` as a **duplicate receipt** and returns `forged` for that job — D1 requires exactly one receipt per job, and job ids never contain a dot, so the split is unambiguous. Superseded attempts therefore live in `results/attempts/<id>.<n>.json`, which the gate's listing (direct `*.json` children of `results/` only) does not scan: history is preserved without minting a rival receipt.
- `dispatch.workflow.js` — Engine C's generated script, **committed before it is launched** and launched by `scriptPath`. This is what makes "the exact orchestration that ran is in the run directory" true rather than aspirational.
- `lane-map.json` — `{"run_id", "manifest", "agents": {"<agent_id>": "<job-id>"}, "worktrees": {"<abs path>": "<job-id>"}}`. Read by [`hooks/lane-guard.sh`](../../hooks/lane-guard.sh) to resolve which job a tool call belongs to. **Without it the guard resolves no job, fails open, and silently allows every write.** Each implementer registers its own worktree as its first command. On Claude Code 2.1.238 a spawned agent is not told its own `agent_id`, so `agents` is normally empty and the `worktrees` map — the guard's documented `cwd` fallback, and the one the 1D probe proved works — carries the resolution. A run dir without this file is not an error; it is a run the guard cannot attribute.
- `receipts/<id>.gate.json` — the Gate stage's receipt exactly as produced, kept beside the normalized result so a reviewer can compare the raw artefact against the folded one.

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
  "cooldowns": { "codex": "2026-06-26T14:33:10Z" },
  "circuit_open": {
    "codex": { "open": true, "reason": "out_of_credits", "opened_at": "2026-06-26T14:32:55Z", "cleared_by": null }
  },
  "attempts": { "task-2-api": { "rate_limited": 2, "network": 1 } },
  "jobs": {
    "task-0-schema":   { "status": "done",    "isolation": "direct",   "worktree": null,                          "session_id": null,   "log": null },
    "task-1-editor-ui":{ "status": "running", "isolation": "worktree", "worktree": "$TMPDIR/compound-v/<run>/task-1-editor-ui", "session_id": "uuid", "log": "docs/superpowers/execution/<run>/logs/task-1-editor-ui.jsonl" },
    "task-2-api":      { "status": "pending", "isolation": "direct",   "worktree": null,                          "session_id": null,   "log": null }
  }
}
```

> **`worktree` and `baseline` are what the integration authority needs, and until 3.0 nothing wrote them.** A smoke run of [`compound-v-integration-gate.py`](../../scripts/compound-v-integration-gate.py) against this release's own run dir returned **`unverifiable` for every job**: no `results/` directory, `worktree: null`, no `baseline`. The gate fails closed correctly, so the whole verification layer was inert. Record both, per job, at dispatch — `worktree` decides *where* the gate runs, `baseline` decides *what it measures against*.
>
> **They stay OPTIONAL on read.** A run dispatched before the cutover carries neither, and [`/v:resume`](../../commands/v-resume.md) must still accept it: a job with no `baseline` reconciles as it always did, and a job with no receipt is re-derived rather than failed. Never refuse to resume a run because it predates a field.

Per-job fields: `status` (lifecycle, below), `isolation` (`direct` | `worktree`), `worktree` (absolute path or `null`), `session_id` (the codex `thread_id` UUID read from the worker's `job_result.session_id`, UUID-validated — the resume UUID; `null` otherwise), `failure_class` (the returned `job_result.failure_class`, e.g. `timeout`/`network`; consulted by the resume-eligibility rule; `null` otherwise), `baseline` (the **immutable pre-launch baseline SHA** the scope gate — and, on a fast-path job, the post-hoc reclassifier — attribute against; recorded at dispatch, reconciled against on resume, **never** re-derived from a moved `HEAD`; CR5-3), and **`log`** (the codex worker's events-log path — `docs/superpowers/execution/<run-id>/logs/<id>.jsonl` — recorded by the dispatcher at dispatch; `null`/absent for non-codex jobs). `log` is read by the liveness sweep as a progress signal and is **degrade-safe**: absent ⇒ prior git+FS+pid behavior unchanged.

**`merged` — a CACHE of the merge, never the proof of one (3.0; 3.4.0 demoted it).** `{ "realised_commit": "<40-hex>", "mode": "worktree" | "direct", "integrated": true, "commit": "<sha>", "proof": "head-matches-artifact" }`, written when a job's work is merged and committed. **Idempotence on the record step alone is not enough**, and this field is why: the native runtime's resume re-runs every agent that started after a failed one, *completed ones included*, so a finished job can implement, gate and record a second time.

But this file is exempt by name from the scope gate and writable by a direct worker, so `integrated: true` is a **claim**. Until 3.4.0 the wave finalizer read it as an answer and skipped that job's merge outright — a forged entry meant the work never landed while the run reported it merged. The finalizer now asks git instead: it applies the job's sealed `jobs/<id>.patch` to a throwaway index seeded from the pinned baseline, reads the blob ids that produces, and skips the merge **only** when `HEAD:<path>` already equals every one of them. The same proof is required after the commit, before any worktree is pruned. Absent ⇒ never merged, which is exactly the state a pre-cutover run is in, so it merges once and normally.

**`jobs/<id>.patch` — the sealed artifact.** Not a state field, but the thing that makes the field above safe to keep as a cache. `gate-receipt` writes the binary diff of the paths it approved against the pinned baseline and records its sha256 in `receipts/<id>.gate.json`; the integration authority refuses a receipt whose artifact is missing or no longer hashes to that value; the finalizer applies exactly that file. Nothing that happened to the worktree after the gate — a revert, a post-gate edit, a test byproduct — can change what merges.

**The manifest is digest-bound.** `emit` hashes `manifest.yaml` and bakes the digest into the workflow script; `gate-receipt`, `record`, `finalize-wave` and the integration authority each verify the file on disk against it and refuse a mismatch. The manifest declares every job's `write_allowed` and lives in this same by-name-exempt run directory, so without the digest a job could widen its own lane map and every later check would agree with the widened list.

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
   - For a Codex worktree job, the codex adapter MAY resume the existing session (`codex exec resume <session_id>`) rather than start cold **only under the resume-eligibility rule** — its recorded `failure_class` is environmental (`timeout` | `network`) **AND** its worktree still exists at the recorded path (the authoritative rule + rationale live in [`v-resume.md`](../../commands/v-resume.md) and [`parallel-dispatcher.md`](../../agents/parallel-dispatcher.md)); every other case recreates the worktree fresh at HEAD. Either way the **scope gate re-runs** on return.
6. **Continue the pipeline** from the reconciled phase: re-collect, re-run the scope gate on every job, then the Review Gate, then merge. Already-`done` jobs are not re-run.

**Why git-wins, restated:** `state.json` is a convenience cache; the filesystem under git is the ground truth. A resume that trusted a stale `done` could skip work that was never actually committed. By re-deriving from git on every resume, the run stays correct even across a hard crash mid-write.

---

## Cross-references

- Graceful backend-failure policy (classify → retry/reroute/halt; the circuit-breaker fields above): [`failure-policy.md`](failure-policy.md)
- Manifest schema + invariants: [`execution-manifest.md`](execution-manifest.md)
- The job_result contract every `results/<id>.json` conforms to: [`schemas/job_result.schema.json`](../../schemas/job_result.schema.json)
- Backend dispatch contract: [`backend-launcher/SKILL.md`](../backend-launcher/SKILL.md)
- Status rendering: [`commands/v-status.md`](../../commands/v-status.md) · Resume: [`commands/v-resume.md`](../../commands/v-resume.md)
