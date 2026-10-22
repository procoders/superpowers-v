# v2.8.1 Session-Aware Workers — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or executing-plans. Under Compound V this plan dispatches via the execution manifest.

**Spec:** `docs/superpowers/specs/2026-07-11-session-aware-workers-design.md` (ACs 1–8).
**Audits:** `docs/superpowers/{library-audit,archaeology}/2026-07-11-session-aware-workers.md`.

## Global Constraints

- Version lockstep 2.8.1 ×3 (plugin.json, marketplace.json, CHANGELOG top) — CI enforces the third.
- No new commands/agents/servers; no upstream edits; no fabricated metrics.
- Every touched script keeps/extends `--selftest`; `bash -n` clean on shells; `lint-frontmatter.py` green on the final tree.
- Workers in worktrees leave changes uncommitted; the serial foundation task commits.
- All codex capability facts are LIVE-PROBED (library audit) — do not re-invent; cite them.

## Shared Interface Contract (verbatim, all tasks bind to it)

- **Session-id line:** the codex worker parses the FIRST `--json` event
  `{"type":"thread.started","thread_id":"<uuid>"}` and prints exactly `COMPOUND_V_SESSION_ID=<uuid>`
  on its own stdout line; `COMPOUND_V_SESSION_ID=` (empty) when the event is absent. The caller
  (dispatcher) reads that line into `job_result.session_id`. The stderr UUID-scrape is deleted.
- **Events-log path:** new worker arg `--events-log <path>`; the dispatcher passes
  `docs/superpowers/execution/<run-id>/logs/<job-id>.jsonl`; the worker writes the `--json`
  stream there. The dispatcher records that same path in `state.json jobs[<id>].log`.
- **`job["log"]`** in `state.json` = the events-log path for codex jobs; absent otherwise.
  Liveness reads it; it is degrade-safe (absent ⇒ prior git+FS+pid behavior unchanged).
- **Resume eligibility (identical wording in v-resume.md AND parallel-dispatcher.md):** a codex
  job may be resumed via `codex exec resume <captured-uuid>` IFF its `failure_class` is
  environmental (timeout | network | killed) AND its worktree still exists at the recorded path;
  every other case recreates the worktree fresh at HEAD (the parallel-dispatcher invariant).
  Never resume by cwd filtering — pass the captured UUID explicitly.
- `--ephemeral` is added ONLY to `compound-v-codex-review.sh`, never the worker.

## Partition Map (disjoint write sets)

| Task | Files |
|---|---|
| 0 (serial) | `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `CHANGELOG.md` |
| 1 | `scripts/compound-v-run-codex-worker.sh`, `skills/backend-launcher/adapter-codex.md` |
| 2 | `scripts/compound-v-codex-review.sh` |
| 3 | `scripts/compound-v-liveness.py` |
| 4 | `commands/v-resume.md`, `agents/parallel-dispatcher.md`, `skills/compound-v/state-machine.md` |
| 5 (serial review) | — |

No file appears twice. Tasks 1–4 parallel after Task 0. Routing: all `claude · deep · worktree` (Task 0/5 direct); effort high (C1/C4 are contract-bearing), medium acceptable for C2.

---

### Task 0 — version lockstep 2.8.1 (serial foundation)
- [ ] Bump plugin.json + marketplace.json to `2.8.1`.
- [ ] CHANGELOG `## [2.8.1] — 2026-07-11` on top (em-dash): Added — session-aware codex workers (`--json` thread_id capture, structured `COMPOUND_V_SESSION_ID`), `logs/<job>.jsonl` run-dir convention, liveness JSONL signal, `--ephemeral` discovery review; Fixed — resume/parallel-dispatcher contradiction reconciled, dead `job["log"]` now populated, stderr UUID-scrape replaced; Probed — thread-naming unsupported in `codex exec` (capture the auto UUID). Credit the live probes.
- [ ] Verify 3 version probes = 2.8.1; simulate the CHANGELOG CI guard; COMMIT (worktrees build on this HEAD).

### Task 1 — codex worker `--json` + structured session id
**Files:** `scripts/compound-v-run-codex-worker.sh`, `skills/backend-launcher/adapter-codex.md`
- [ ] Add a `--events-log <path>` arg to the worker (optional; when absent, keep a `$ART` default so standalone use still works).
- [ ] Add `--json` to BOTH `codex exec` invocations (schema path ~302–311 AND plain path ~314–322 — change identically; the mirror hazard). Keep `--output-last-message` (verified to coexist — result path unchanged).
- [ ] Write the `--json` stream to the events-log path (tee/redirect); parse the first `thread.started` line for `thread_id`; emit `COMPOUND_V_SESSION_ID=<uuid>` on stdout (empty when absent). DELETE the stderr UUID-scrape (~354–361).
- [ ] `adapter-codex.md`: pinned block (48–59) + flag table (66–76) gain `--json` + `--events-log` + the thread_id-capture note; replace the stale "session-id from stderr banner / stdout discarded" story (lines ~22, ~63, Resume §136–145) with the structured-capture reality; keep the invocation otherwise pinned.
- [ ] Verify: `bash -n`; if `scripts/test-worker-path-transport.sh` exists, run it (must pass); a dry parse test — feed a captured 2-line JSONL fixture (`thread.started` + an item) to the parse logic and confirm it extracts the uuid and emits the line; empty/missing event ⇒ empty emit, no crash.

### Task 2 — codex review `--ephemeral`
**Files:** `scripts/compound-v-codex-review.sh`
- [ ] Add `--ephemeral` to the single `codex exec` invocation (146–154), between `--sandbox read-only` and the flag block, with a one-line comment: discovery rounds must not persist/resume (statelessness is the point — anchoring-averse).
- [ ] Verify `bash -n`; the script still emits findings JSON on stdout (no behavior change beyond non-persistence).

### Task 3 — liveness JSONL signal
**Files:** `scripts/compound-v-liveness.py`
- [ ] In `classify_job()` (116–164), guarded by the existing `if log and os.path.isfile(log)` pattern (143–148): parse the JSONL log's newest line; a recent `item.completed`/`turn.completed`/any event newer than the staleness threshold is a WORKING signal; a log whose newest event is older than the threshold reinforces STALE. NEVER let a malformed/partial JSONL line raise — wrap in try/except, treat unparseable as "no signal" and fall through to git+FS+pid. Degrade-safe: no `log` ⇒ identical prior behavior.
- [ ] Extend `--selftest` (202–328): a job with a fresh JSONL log ⇒ WORKING; a job with a stale JSONL log + no other progress ⇒ STALE; a malformed JSONL log ⇒ no crash, falls back. 
- [ ] Verify `python3 scripts/compound-v-liveness.py --selftest` green; run it against the real v2.8.1 run-dir once (informational).

### Task 4 — resume tightening + doc reconciliation
**Files:** `commands/v-resume.md`, `agents/parallel-dispatcher.md`, `skills/compound-v/state-machine.md`
- [ ] `v-resume.md` Step 5: replace the loose "may use codex exec resume <session_id>" with the Shared-Contract resume-eligibility rule (environmental-failure + intact worktree, by captured UUID, else recreate fresh); cite `parallel-dispatcher.md`'s worktree-recreate invariant so they agree (kills the archaeology-flagged contradiction at v-resume.md:29 vs parallel-dispatcher.md:183).
- [ ] `parallel-dispatcher.md`: at dispatch, record the `--events-log` path into `state.json jobs[<id>].log`; state the SAME resume-eligibility rule verbatim; keep the worktree-recreate invariant intact (do not weaken it).
- [ ] `state-machine.md`: document the `log` field in the `state.json` job shape (80–82 area) and the new `logs/` run-dir subdir in the layout.
- [ ] Verify: `grep -n "resume" commands/v-resume.md agents/parallel-dispatcher.md` shows the identical rule; `lint-frontmatter.py` green; no contradiction remains (the two files' resume rules match word-for-word on eligibility).

### Task 5 — three-pass Review Gate (serial)
Spec ACs 1–8; run all selftests + lint on the merged tree; confirm the resume rule is byte-identical across the two docs; confirm the events-log/`job["log"]`/liveness contract is coherent end to end; no writes outside the union.

## Execution Handoff
Task 0 serial (commits) → Tasks 1–4 parallel `claude · worktree` scope-gated by the (now hardened) gate → Task 5 review → memory → MERGED (Step 7) → post-build Codex rounds (xhigh, targeted: verify + adjacent-bug hunt) to a clean verdict → report + push authorization.
