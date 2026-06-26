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
  "jobs": {
    "task-0-schema":   { "status": "done",    "isolation": "direct",   "worktree": null,                          "session_id": null },
    "task-1-editor-ui":{ "status": "running", "isolation": "worktree", "worktree": "$TMPDIR/compound-v/<run>/task-1-editor-ui", "session_id": "uuid" },
    "task-2-api":      { "status": "pending", "isolation": "direct",   "worktree": null,                          "session_id": null }
  }
}
```

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
4. **Re-dispatch only `pending` / `failed` / `blocked`** jobs (after step 3 reclassification), honoring `depends_on` and `max_parallel` exactly as the initial dispatch did. Each re-dispatch replays `jobs/<id>.prompt.md` verbatim.
   - For a Codex worktree job whose `session_id` is recorded, the codex adapter MAY resume the existing session (`codex exec resume <session_id>`) rather than start cold; either way the **scope gate re-runs** on return.
5. **Continue the pipeline** from the reconciled phase: re-collect, re-run the scope gate on every job, then the Review Gate, then merge. Already-`done` jobs are not re-run.

**Why git-wins, restated:** `state.json` is a convenience cache; the filesystem under git is the ground truth. A resume that trusted a stale `done` could skip work that was never actually committed. By re-deriving from git on every resume, the run stays correct even across a hard crash mid-write.

---

## Cross-references

- Manifest schema + invariants: [`execution-manifest.md`](execution-manifest.md)
- The job_result contract every `results/<id>.json` conforms to: [`schemas/job_result.schema.json`](../../schemas/job_result.schema.json)
- Backend dispatch contract: [`backend-launcher/SKILL.md`](../backend-launcher/SKILL.md)
- Status rendering: [`commands/v-status.md`](../../commands/v-status.md) · Resume: [`commands/v-resume.md`](../../commands/v-resume.md)
