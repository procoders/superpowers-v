# v2.8.1 — Session-Aware Workers — Design

**Status:** approved in conversation 2026-07-11 (Oleg): "готовим … 2.8.1 куда включим «session-aware
workers», три маленьких изменения с чёткими границами … Плюс один probe на thread-naming."
**Pre-flights:** library-audit (all codex capabilities LIVE-PROBED 0.144.1) + archaeology (exact
line-level reality) done at `docs/superpowers/{library-audit,archaeology}/2026-07-11-session-aware-workers.md`.
Domain-expert pre-flight SKIPPED per the skip rule — pure internal plumbing, no user-facing/domain surface.

## Goal

Make Compound V's codex integration session-aware, via three small bounded changes plus the
resolved thread-naming probe:

1. **Capture the real session id.** The codex worker runs with `--json`, parses the
   `thread.started` event's `thread_id` (a UUID, the first JSONL line — probed), and surfaces
   it so the caller writes `job_result.session_id`. This replaces today's fragile stderr
   UUID-scrape heuristic with the structured id — and adopts the idiom the cursor worker
   already uses (DRY).
2. **`--ephemeral` for discovery review.** The codex review script runs `--ephemeral` (no
   session persisted) — correct for stateless, anchoring-averse discovery rounds.
3. **Liveness reads the JSONL stream as an ADDITIONAL signal**, layered degrade-safe on the
   existing git+FS+pid classifier.
4. **Resume is tightened AND its doc contradiction reconciled.** `/v:resume` may `codex exec
   resume <session_id>` ONLY for an **environmental failure with an intact worktree**; every
   other case recreates the worktree fresh (the `parallel-dispatcher.md` invariant). The two
   docs currently contradict — this makes them agree.

**Probe result (thread-naming, the user's explicit ask):** `codex exec` exposes NO launch-time
`--name`/`--thread` flag; `resume` accepts a UUID *or* a thread name, but names can't be set in
`exec`. **Conclusion: capture the auto-generated `thread_id` UUID; do not attempt to name
sessions.** No feature built on naming.

## Non-goals

- No new commands, agents, servers; no upstream edits; no fabricated metrics.
- No resume for discovery/review rounds (anchoring); resume is crash-recovery only.
- No change to the result-extraction path — `--output-last-message` still yields the canonical
  last message (verified to coexist with `--json`).
- `--ephemeral` ONLY in the review script, never the implementer worker (implementers are what
  we resume).

## Shared Interface Contract (cross-task, nailed up front)

- **Session id source:** the FIRST `--json` line is `{"type":"thread.started","thread_id":"<uuid>"}`.
  The worker parses `thread_id` from it and prints it on a dedicated, greppable stdout line
  `COMPOUND_V_SESSION_ID=<uuid>` (the caller reads that), replacing the stderr-scrape. If the
  event is absent (older CLI / failure), emit `COMPOUND_V_SESSION_ID=` (empty) — degrade-safe,
  never crash.
- **JSONL events log path (new `logs/` convention):** the dispatcher hands the worker an
  explicit path `docs/superpowers/execution/<run-id>/logs/<job-id>.jsonl`; the worker writes
  the `--json` stream there (in addition to whatever it needs internally). The dispatcher then
  records that exact path in `state.json` `jobs[<id>].log`. Absent for non-codex jobs.
- **`job["log"]` is the bridge:** liveness reads `state.json` `jobs[<id>].log`; it was already
  read by the classifier but never populated — this feature populates it for codex jobs.
- **Resume eligibility:** resume is permitted iff the recorded `failure_class` is environmental
  (timeout / network / killed — NOT scope-block, NOT model-error) AND the worktree still exists
  at its recorded path. Otherwise recreate fresh. `resume` uses the captured UUID (authoritative);
  never rely on cwd filtering (our worktree paths are ephemeral — pass the UUID explicitly).

## Changes

### C1 — codex worker `--json` + structured session id
`scripts/compound-v-run-codex-worker.sh`: add `--json` to BOTH `codex exec` invocations (schema
path + plain path — the mirror hazard: change both identically); direct the JSONL stream to the
dispatcher-provided `--events-log <path>` (new arg) AND keep `--output-last-message` for the
result; parse the first `thread.started.thread_id` and emit `COMPOUND_V_SESSION_ID=<uuid>`;
delete the stderr UUID-scrape. Degrade-safe when the event is missing.
`skills/backend-launcher/adapter-codex.md`: pinned block + flag table gain `--json` and the
`--events-log` + `thread_id` capture note; the stale "session-id from the stderr banner / stdout
discarded" story (lines ~22, ~63, Resume §136–145) is replaced.

### C2 — codex review `--ephemeral`
`scripts/compound-v-codex-review.sh`: add `--ephemeral` to the single `codex exec` invocation
(discovery rounds must not persist/resume). One-line change + a comment stating why.

### C3 — liveness JSONL signal
`scripts/compound-v-liveness.py`: when `job["log"]` exists and is a readable JSONL file, use its
newest event's timestamp / event type as an ADDITIONAL progress signal (a recent
`item.completed`/`turn.completed` = WORKING; a stream that stopped past the threshold reinforces
STALE). Guarded by the existing `if log and os.path.isfile(log)` pattern → **degrade-safe**: no
log ⇒ the current git+FS+pid logic is unchanged. Extend `--selftest` with a JSONL-signal case.

### C4 — resume tightening + doc reconciliation
`commands/v-resume.md` Step 5: resume-by-session_id is gated to environmental-failure +
intact-worktree; all else recreates fresh — cite the `parallel-dispatcher.md` invariant so the
two agree. `agents/parallel-dispatcher.md`: record the `--events-log` path into
`state.json jobs[<id>].log` at dispatch, and state the resume-eligibility rule identically.
`skills/compound-v/state-machine.md`: document the `log` field in the `state.json` job shape
(and the new `logs/` run-dir subdir).

### C0 — release
Version 2.8.1 lockstep ×3 + CHANGELOG entry.

## Acceptance Criteria

1. Codex worker adds `--json` to BOTH invocations, parses `thread.started.thread_id`, emits
   `COMPOUND_V_SESSION_ID=<uuid>` (empty when absent), writes the JSONL stream to the
   dispatcher-provided events-log path, and the stderr UUID-scrape is gone. `--output-last-message`
   still yields the result. `bash -n` clean; worker path-transport test (if present) still passes.
2. `--ephemeral` present on the review script's `codex exec`; `bash -n` clean.
3. Liveness uses the JSONL log as an additional signal, fully degrade-safe (no log ⇒ identical
   prior behavior); `--selftest` green incl. a new JSONL case.
4. `/v:resume` and `parallel-dispatcher.md` AGREE: resume only for environmental-failure +
   intact worktree, by captured UUID; the prior contradiction is gone. `state-machine.md`
   documents `jobs[].log` + `logs/`.
5. `adapter-codex.md` reflects `--json`/`--events-log`/`thread_id`; no stale stderr-scrape story.
6. Version 2.8.1 lockstep ×3 + CHANGELOG (crediting the live probes + the thread-naming
   resolution). CI green (incl. the CHANGELOG guard).
7. Invariants: no new commands/agents/servers, no upstream edits, no fabricated metrics; probe
   conclusions honest (thread-naming unsupported, stated).
8. Cross-model Codex review (targeted, xhigh) run post-build to a clean verdict; adjacent-bug
   hunt included.
