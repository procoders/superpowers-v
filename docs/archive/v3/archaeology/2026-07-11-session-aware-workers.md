# v2.8.1 Session-Aware Workers — Code Archaeology (Phase 1A)

Reality-only survey of the exact surfaces the feature touches. Every claim cites a file:line
in the repo at branch `v2.8.1-session-aware`. No implementation proposed. Library facts are
NOT re-derived here — they live in `docs/superpowers/library-audit/2026-07-11-session-aware-workers.md`.

Feature (per dispatch brief) = three small changes riding an already-probed codex capability:
(A) worker captures the real `thread_id` via `--json`; (B) review script goes `--ephemeral`;
(C) liveness gains an optional JSONL-events signal; plus tightening resume to
environmental-failure-with-intact-worktree only.

---

## Surface 1 — `scripts/compound-v-run-codex-worker.sh` (the implementer worker)

**The two `codex exec` invocations** live in `run_codex()`, `scripts/compound-v-run-codex-worker.sh:299–324`:
- `--output-schema` path: lines **302–311** (`codex exec … --output-schema "$OUTPUT_SCHEMA" --output-last-message "$RESULT_TXT" …`).
- plain path: lines **314–322** (identical minus `--output-schema`).
- Both run under the supervisor `python3 "$SUPERVISOR" --timeout … -- codex exec …`, both end `"$(cat "$PROMPT_FILE")" </dev/null`, both take the optional word-split `$EFFORT_FLAG`.
- Neither carries `--json` today. This is where `--json` must be added to **both** branches (mirror-edit hazard: two invocations must stay in sync — same class as the `$EFFORT_FLAG` double-append).

**Where stdout currently goes:** captured to a scratch log and effectively **discarded**. `STDOUT_LOG="$ART/codex_stdout.log"` (line **283**); the run is redirected `run_codex >"$STDOUT_LOG" 2>"$STDERR_LOG"` (line **338**). The header comment (lines **280–283**) states the intent explicitly: "codex prints its FINAL agent message to stdout; we must NOT let it reach our stdout … Capture + discard it." `$STDOUT_LOG` is written but **never read again** anywhere in the script — confirmed: the only reads are `$STDERR_LOG` and `$RESULT_TXT`. So today stdout is captured-then-ignored; adding `--json` turns this file into JSONL and it becomes the natural place to parse `thread.started`.

**How the result / last message is captured:** `RESULT_TXT="$ART/job_result.txt"` (line **263**), passed as `--output-last-message "$RESULT_TXT"` in both invocations, read into `summary` at lines **363–367** (`summary=$(cat "$RESULT_TXT")`, fallback `"(no summary emitted by worker)"`). Per library audit fact #2, `--json` and `--output-last-message` **coexist**, so this canonical result path is unaffected.

**How the caller receives a session_id TODAY (the load-bearing gap):** the script does NOT read structured stdout. It **scrapes the first UUID-shaped token out of stderr** (and falls back to `$RESULT_TXT`):
- `UUID_RE='[0-9a-fA-F]{8}-…-…{12}'` (line **354**).
- `session_id=$(grep -oE "$UUID_RE" "$STDERR_LOG" … | head -n1)` (line **357**); fallback grep over `$RESULT_TXT` (lines **359–361**).
- emitted into `job_result.session_id` via `emit_job_result … "$session_id" …` (line **488**), typed by jq at lines **68/79**.

This is a **heuristic, not a contract**: "first UUID anywhere in stderr" can capture a *different* UUID (a request id, a trace id, a UUID inside the model's own reasoning text if it lands in the result-txt fallback). The feature replaces this with the authoritative `thread.started.thread_id` from `--json` stdout (library audit fact #1: it is the FIRST JSONL event and IS the resume id). **Design constraint:** the new parse must not regress the empty-string contract — when no `thread_id` line is present (older client, `--json` absent), `session_id` must stay `""` (schema permits it; adapter-codex.md:145 documents the fresh-re-dispatch fallback).

**Note — the cosmetic-stderr filter (lines 342–346)** strips `codex_hooks is deprecated` from stderr only. Library audit fact #1 warns an early `item.completed` may carry that same benign notice on the JSONL stream — a JSONL parser keys on `type=="thread.started"`, so it is unaffected, but any code that greps the raw JSONL for text should be aware.

---

## Surface 2 — `scripts/compound-v-codex-review.sh` (the cross-model reviewer)

**The single `codex exec` invocation:** lines **146–154**:
```
python3 "$SUPERVISOR" --timeout "$TIMEOUT_SEC" --grace 3 -- codex exec \
  --cd "$REPO" --sandbox read-only --skip-git-repo-check --model "$MODEL" \
  -c model_reasoning_effort="$EFFORT" --output-schema "$SCHEMA" \
  --output-last-message "$FINDINGS" "$(cat "$PROMPT_FILE")" </dev/null …
```
One invocation only (no schema/plain fork here — schema is always set, defaulted at line 79).

**Does it default to a persisted session today?** YES — implicitly. There is **no `--ephemeral`** flag anywhere in this script; a normal `codex exec` run persists session files to disk. This is exactly where `--ephemeral` slots (single edit, one invocation) per library audit fact #3 and design-constraint "`--ephemeral` belongs ONLY in the review/discovery script, never the implementer worker."

**Any resume logic?** NONE. The script has no `resume`, no `session_id` capture, no `--last`. It is fire-and-forget: run → read `$FINDINGS` (line 158) → `cat "$FINDINGS"` to stdout (line 163). It never surfaces a session id, so making it `--ephemeral` costs nothing downstream (nothing consumes a review session id today).

**Slot for `--ephemeral`:** between `--sandbox read-only` and the rest of the flag block at lines 148–153. Read-only + ephemeral is coherent: a discovery review that can neither write the repo nor leave a resumable session behind.

---

## Surface 3 — `scripts/compound-v-liveness.py` (hang detector)

**Classify function:** `classify_job(job, now, stale_sec)` at lines **116–164**; run-level driver `probe()` at **167–183**. Classes `WORKING / LIKELY-DONE / STALE / DEAD / UNKNOWN` (line 47).

**Exact signals used today** (all optional, degrade-safe — line 120 comment: "worktree, baseline, pid, log"):
1. **git ancestry (LIKELY-DONE), checked FIRST** — lines **132–139**: `_git(["rev-parse","HEAD"], wt)` past `baseline` AND `_git_ok(["merge-base","--is-ancestor", baseline, "HEAD"], wt)`.
2. **FS mtime (WORKING/STALE)** — `_newest_mtime(wt)` (lines **79–98**, walks worktree, excludes `.git`, `lstat` not `stat`) OR-ed with an **optional `log` mtime** at lines **143–148** (`if log and os.path.isfile(log): lm = os.stat(log).st_mtime`). Age vs `stale_sec` at lines **150–156**.
3. **pid liveness (DEAD/UNKNOWN)** — `_pid_alive(pid)` (lines **101–113**, EPERM = alive) used at 154 and the no-FS-signal fallback 159–162.

**Where a JSONL-events signal layers in without breaking the git+FS fallback:** the probe **already reads an optional `log` file's mtime** (lines 143–148) — so an *mtime-only* progress signal from a JSONL log needs **zero probe change**, only that the dispatcher populate `job["log"]`. But the feature wants a **JSONL-EVENTS signal** (parse events, e.g. detect the last event type / a terminal `thread` event), which is richer than mtime. That new logic layers cleanly as a step **between current step 1 (LIKELY-DONE, line 132) and step 2 (mtime, line 150)**, or folded into step 2, guarded by `if log and os.path.isfile(log)` exactly like the existing mtime read — so **no JSONL file ⇒ the guard is false ⇒ current mtime/commit path runs unchanged** (this is the degrade-safe invariant the library audit design-constraint demands, and it matches the existing `log`-optional pattern). The `job` dict is the extension point: `classify_job` reads only `job.get(...)` keys (lines 121–124), all optional.

**Does it know a worktree path / run-dir layout?** It reads `job["worktree"]` (line 121) and `job["log"]` (line 124) straight from `state.json`; it does NOT itself compute or know the `$TMPDIR/compound-v/<run>/<job>` convention — the dispatcher supplies those paths. `probe()` reads `<run-dir>/state.json` (line 170). So a JSONL log path must be **written into `state.json` job entries by the dispatcher/worker** for the probe to find it (see Surface 7 — no `log` key is populated today).

**`--selftest`:** YES — `_selftest()` at lines **202–328**, wired via `--selftest` (line 337) → `main` line 340. It covers LIKELY-DONE, WORKING, STALE, DEAD, UNKNOWN, EPERM, symlink-lstat, probe filtering, exit codes. A new JSONL-events branch MUST add a self-test case here (existing convention: every signal has a `check(...)`).

---

## Surface 4 — `schemas/job_result.schema.json` + collector

**`session_id` field:** EXISTS. `schemas/job_result.schema.json:44–47` — `"type": "string"`, and it is in the top-level `required` array (line **16**). So it is **required, non-nullable string, empty-string-allowed** (description line 46–47: "the UUID from the run banner, resumed via `codex exec resume <uuid>`. May be empty string when the backend has no resumable session"). No schema change needed to carry a real `thread_id`; the description text ("from the run banner") is now stale-in-spirit (it will come from the `--json` stream) — a doc-accuracy edit, not a structural one.

**No `failure_class` distinction between environmental vs scope-block vs error at the granularity resume needs:** the schema's `failure_class` enum (lines **56–59**) = `[null, none, out_of_credits, rate_limited, overloaded, auth, context_length, timeout, network, other]`. This classifies **backend** failures (credits/auth/rate/network/timeout), NOT "environmental failure with intact worktree" vs "scope block" vs "logic error." `status` (lines 21–24) = `success|blocked|timeout|error`. So the resume-tightening guard ("resume only on environmental failure + intact worktree") has **no single existing field** that encodes it — it must be composed from existing signals (`status==timeout|error` AND `failure_class ∈ {timeout,network,overloaded,...}` AND worktree still on disk), NOT invented as a new enum unless the plan chooses to add one. **This is a finding, not a TODO:** today there is no `failure_class` value meaning "environmental / safe-to-resume"; the distinction must be derived.

**Where `session_id` is populated in the collector:** `scripts/compound-v-collect-results.py:253–258`. Precedence: `scope.get("session_id")` → else worker JSON `wjson["session_id"]` (line 254–255) → `--session-id` CLI override (line 256–257, arg defined line 385) → coerced to `""` if None (line 258). Emitted at line **289**. The codex worker's `job_result` JSON already carries `session_id`, so it flows worker → `scope`/`wjson` → collector unchanged. **No collector change is required to propagate a real `thread_id`** — the worker just needs to put the right value in `session_id`; the collector is transport-agnostic.

---

## Surface 5 — `commands/v-resume.md` (resume guard)

**Step 5 exact current wording** (`commands/v-resume.md:28–30`):
> 5. Re-dispatch only the incomplete jobs — those that are `pending`, `failed`, or `blocked` … via Engine A …
>    - "For a Codex worktree job with a recorded `session_id`, **the codex adapter may use `codex exec resume <session_id>` instead of a cold start.** Either way, the scope gate re-runs on return."

**Is there a guard on WHEN resume is appropriate?** Only partial, and it CONFLICTS with the feature's intent:
- Line 38 (Safety): "A `blocked` job is re-dispatched only after its prompt/partition is corrected — do not blindly re-run a job that wrote outside its scope." (scope-block guard, but says re-dispatch, not resume.)
- **Critical conflict:** `agents/parallel-dispatcher.md:183` (the retry path) mandates the OPPOSITE of session resume — on `retry` it re-dispatches "through the full worker-script lifecycle … the worktree is removed and recreated fresh at current HEAD before the retry runs … **never resume by poking the CLI at the job's old worktree directly.**" And adapter-codex.md:110/112 reinforces: the worktree-recreate is "the ONLY correct way to fix a wrong worktree base."
- So there are **two contradictory statements in the repo today**: v-resume.md:29 says "adapter MAY `codex exec resume`," while parallel-dispatcher.md:183 says "never resume, always recreate the worktree." The feature's tightening (resume ONLY for environmental-failure + intact worktree) is precisely the reconciliation point — **the guard belongs in v-resume.md Step 5 and must be squared with dispatcher Step 7/retry (line 183).**

**Is there a `failure_class` distinguishing environmental vs scope-block vs error, in scripts?** The worker classifies failures via `compound-v-classify-failure.py` (worker lines 460–463) into the schema enum. There is **no** "environmental" class; "intact worktree" is a filesystem check (`os.path.isdir(worktree)`), not a recorded field. The resume guard must therefore combine: `status ∈ {error,timeout}` (NOT `blocked` — a scope block must never auto-resume, it needs partition correction per line 38) + worktree still present + a recorded `session_id`. **Where the guard belongs:** Step 5 bullet at v-resume.md:29, tightened; and it must not contradict dispatcher:183 (which owns the *retry* path — arguably resume-by-session is a v-resume-only affordance for a crash-interrupted job, distinct from an in-run policy retry).

---

## Surface 6 — `skills/backend-launcher/adapter-codex.md` (pinned runbook)

**The pinned invocation block:** lines **48–59** (fenced `codex exec` with `--cd/--sandbox/--skip-git-repo-check/--model/${effort}/${output_schema}/--output-last-message/-c network/prompt </dev/null`). This is documentation mirroring the script's `run_codex()`; it does NOT yet mention `--json`. **Must gain `--json` + a `thread_id`-capture note** to stay in sync with the script (the file's own header, line 7, pins it to codex-cli 0.144.1 and says "do not re-derive per run").

**Existing session_id/resume mentions to update:**
- Step 5 NORMALIZE, line **22**: "session_id ← run banner UUID" — this is the OLD stderr-scrape story; must change to "thread_id from the first `--json` `thread.started` event."
- Line **63** (stream handling): "the session-id from the stderr banner — so codex's stdout is safely discarded." This is now **false** under the feature — stdout is exactly what carries the id. This sentence must be rewritten (stdout becomes JSONL, no longer discarded).
- The flag table (lines 66–76) has no `--json` row — add one.
- The **Resume** section, lines **136–145**: documents `codex exec resume <SESSION_ID>` and the stderr-scrape+result-fallback capture (line 145). Must be updated to the `thread_id` capture and, if the plan tightens resume, note the environmental-only guard.

---

## Surface 7 — Where a per-job JSONL events log naturally lives

**Run-dir layout (verified on a real run, `docs/superpowers/execution/2026-07-11-v2-8-hardening/`):**
```
<run-id>/
  manifest.yaml
  state.json
  jobs/<id>.prompt.md       ← per-job INPUT (prompt), captured at dispatch (parallel-dispatcher.md:110)
  results/<id>.json         ← per-job OUTPUT (normalized job_result, collector-written)
  validation/               ← ad-hoc (this run only)
```
Canonical layout is pinned in `agents/parallel-dispatcher.md:21` and `skills/compound-v/state-machine.md:60–61`: `manifest.yaml`, `state.json`, `jobs/<id>.prompt.md`, `results/<id>.json`.

**Is there a `logs/` convention?** NO. There is a `jobs/` (inputs) and a `results/` (outputs) convention, but **no per-job log/stream directory** in the run-dir. The worker's live streams go to **`$ART` under `$TMPDIR`, OUTSIDE the run-dir and outside the repo**: `ART="$WT.art"` (worker line 261), holding `codex_stdout.log` (283), `codex_stderr.log` (279), `job_result.txt` (263), `write_allowed.globs` (383), `scope_check.err`. `$ART` is deliberately outside the worktree so it never appears in `git diff` (worker lines 256–260; adapter-codex.md:64). These are **ephemeral** — the run-dir is git-committed (dispatcher Step 7), but `$ART` is not.

**Consequence for the liveness JSONL signal:** the `--json` stream currently would land in `$ART/codex_stdout.log` under `$TMPDIR` (transient, per-`$WT`). For the liveness probe to read it, `state.json`'s job entry must record a `log` path (the probe reads `job["log"]`, liveness.py:124) — and **`state.json` job entries do NOT populate `log`, `baseline`, or `pid` today**: the shape at state-machine.md:80–82 records only `status/isolation/worktree/session_id`. So `job["log"]`, `job["baseline"]`, `job["pid"]` are read by the probe but **never written by the dispatcher** at present (the probe treats them as absent → degrades to worktree-only). **Finding:** a JSONL-events liveness signal requires the dispatcher to (a) point the worker's `--json` stream at a stable path and (b) record that path in `state.json` `job["log"]`. The path can live either under `$ART` (transient, but liveness runs mid-flight so transient is acceptable) or under a new `<run-dir>/logs/<id>.jsonl` (persistent, git-committable). Which one is a plan decision; the archaeology fact is: **no `logs/` convention exists yet, and `job["log"]` is currently a dead (unpopulated) input.**

---

## Regression Surface (each: "if the new code breaks, what breaks")

1. **Worker `--json` on BOTH invocations (worker.sh:302–311, 314–322).** If `--json` is added to only one branch, schema-jobs vs plain-jobs diverge (same mirror-hazard as `$EFFORT_FLAG`). If `--json` changes stdout format and any downstream still greps stdout as prose → garbage summary. (Mitigant already true: stdout is discarded today, summary comes from `$RESULT_TXT`.)
2. **stdout→job_result contract (worker.sh:476–494, adapter-codex.md:171).** The worker's OWN stdout must remain "canonical job_result JSON and nothing else." If `--json` output ever leaks to the worker's stdout (vs the captured `$STDOUT_LOG`), the collector/scope-check parse breaks for EVERY codex job. The redirect at line 338 must keep `$STDOUT_LOG` capturing the JSONL.
3. **`session_id` semantics (worker.sh:354–361 → schema:44).** If the new `thread_id` parse fails to find the line and doesn't fall back to `""`, a required-field violation breaks the job_result schema for every codex job. Empty-string fallback is the invariant.
4. **Liveness degrade-safety (liveness.py:132–164).** If the JSONL-events branch throws on a malformed/partial JSONL line (a stream mid-write), it must not crash `classify_job` — the whole probe's contract (docstring line 20: "Never crashes") and the git+FS fallback would regress for ALL jobs, not just codex.
5. **`--ephemeral` on review (codex-review.sh:146–154).** Low risk (nothing consumes a review session id), BUT if `--ephemeral` is unsupported on an older pinned client it fails loud → every `/v:review-plan` and cross-model dispatch review breaks. Library audit fact #3 confirms the flag exists on 0.144.1; a client-floor note (cf. adapter-codex.md:84's `xhigh`/sol floor pattern) is the precedent.
6. **Resume tightening (v-resume.md:29 vs parallel-dispatcher.md:183).** If the guard lets a `blocked` job resume-by-session, it re-runs a scope-violating job without partition correction (violates v-resume.md:38 safety). If it forbids resume too broadly, it silently falls back to fresh re-dispatch (current behavior) — safe but wastes the feature. The two docs currently contradict; a fix touching one without the other leaves the repo self-inconsistent.

---

## DRY Findings

- **session_id capture is duplicated across FOUR worker scripts** (`grep -rn session_id scripts/`): codex (worker.sh:354–361, stderr UUID-scrape), cursor (`compound-v-run-cursor-worker.sh:289`, structured `jq .session_id // .chatId …` from its OWN `--output-format json`), antigravity (`compound-v-run-antigravity-worker.sh:334`, always `""`). **Cursor already parses a structured JSON stream for its session id** (worker line 253: `{"type":"result", …, "session_id": <uuid>}`). The codex `--json` change makes codex converge on cursor's pattern (parse the structured stream, not scrape a banner). **Decision for the plan:** extend the codex worker to match cursor's structured-parse approach; do NOT invent a third capture idiom. The collector (collect-results.py:253–258) is already the single normalization point — no duplication there.
- **No duplicate JSONL/liveness logic** — `compound-v-liveness.py` is the sole classifier; extend it, don't fork.
- **`$ART` scratch pattern is shared** by codex/cursor/antigravity workers (each writes `codex_stdout.log`/equivalent under `$TMPDIR`). If the plan routes the JSONL log through `$ART`, it reuses an established pattern; if it introduces `<run-dir>/logs/`, that is a NEW convention only codex uses — justify or generalize.

---

## Design constraints for the spec (non-negotiable)

1. **Add `--json` to BOTH `codex exec` invocations in `run_codex()`** (worker.sh:302–311 AND 314–322). Missing one is a latent divergence bug.
2. **Parse `thread_id` from the FIRST `thread.started` JSONL line of the captured stdout** (`$STDOUT_LOG`, worker.sh:283), NOT from the stderr UUID-scrape. Keep the stderr/result-txt scrape ONLY as a degrade fallback, or remove it — but the empty-string contract (schema:44, required) MUST hold when no id is found.
3. **Do NOT change the result-extraction path.** `--output-last-message "$RESULT_TXT"` (worker.sh:309/320) stays canonical for `summary`; `--json` coexists (library fact #2). The worker's own stdout must remain ONLY the job_result JSON — the JSONL goes to `$STDOUT_LOG`, never the worker's stdout (regression #2).
4. **`--ephemeral` goes ONLY in `compound-v-codex-review.sh`** (lines 146–154), between `--sandbox read-only` and the flag block. NEVER in the implementer worker (implementers are the resumable ones). Pin/note the client floor (0.144.1 verified).
5. **Liveness JSONL-events signal MUST be guarded by `if log and os.path.isfile(log)`** exactly like the existing optional-log mtime read (liveness.py:143), so no-JSONL ⇒ current git+FS path runs UNCHANGED (docstring "Never crashes" invariant). Add a `check(...)` self-test case in `_selftest()` (liveness.py:202–328) — the file's convention is one self-test per signal.
6. **For the probe to SEE the JSONL, `state.json` job entries must record a `log` path** — `job["log"]` is read (liveness.py:124) but NEVER written today (state-machine.md:80–82 records only status/isolation/worktree/session_id). The dispatcher must populate it AND point the worker's `--json` stream at that stable path. Decide: transient `$ART` path vs new persistent `<run-dir>/logs/<id>.jsonl` (no `logs/` convention exists today — Surface 7).
7. **Resume tightening lives in `v-resume.md` Step 5 (line 29)** and MUST be reconciled with `parallel-dispatcher.md:183` (which currently mandates worktree-recreate, "never resume by poking the old worktree"). Guard = resume-by-`session_id` only when `status ∈ {error,timeout}` (NOT `blocked` — v-resume.md:38) AND the worktree still exists on disk AND a non-empty `session_id` was captured. There is NO existing `failure_class` meaning "environmental/safe-to-resume"; it must be DERIVED from `status` + `failure_class ∈ {timeout,network,overloaded}` + worktree-present, not assumed.
8. **Update `adapter-codex.md` in lockstep with the script:** add `--json` to the pinned block (lines 48–59) and flag table (66–76); fix line 22 ("session_id ← run banner UUID"), line 63 ("session-id from the stderr banner … stdout safely discarded" — now false), and the Resume section (136–145). A pinned runbook that lies about the flags is worse than none.
9. **Extend the codex worker's id-capture to match cursor's structured-stream parse idiom** (cursor-worker.sh:289) — do not create a third session-id capture pattern (DRY).

---

## File Touch Map (for Phase 2 partitioning)

| File | Change | Shared? |
|---|---|---|
| `scripts/compound-v-run-codex-worker.sh` | add `--json` to both `run_codex()` invocations; parse `thread_id` from `$STDOUT_LOG` into `session_id`; keep empty-string fallback | worker script (codex-only) |
| `scripts/compound-v-codex-review.sh` | add `--ephemeral` to the single `codex exec` invocation | review script (codex-only) |
| `scripts/compound-v-liveness.py` | add optional JSONL-events signal (guarded by `job["log"]`), + `_selftest()` case | **SHARED RESOURCE** — read/used by dispatcher (parallel-dispatcher.md) and `/v:status`; degrade-safe contract must hold |
| `agents/parallel-dispatcher.md` | populate `state.json` `job["log"]` with the JSONL path; reconcile the resume-vs-recreate statement (line 183) | **SHARED RESOURCE** — canonical run-dir + state.json contract; state-machine.md and v-resume.md both read it |
| `skills/compound-v/state-machine.md` | document the new `job["log"]` field in the state.json shape (lines 80–82) | **SHARED RESOURCE** — authoritative state.json schema doc; multiple commands cite it |
| `commands/v-resume.md` | tighten Step 5 (line 29) resume guard to environmental-failure + intact-worktree only | command doc (reads state-machine.md + dispatcher) |
| `skills/backend-launcher/adapter-codex.md` | add `--json`/`thread_id` to pinned block + flag table; fix lines 22, 63, 136–145 | **SHARED RESOURCE** — pinned runbook mirroring worker.sh; must stay in sync with the script |
| `schemas/job_result.schema.json` | (optional) refresh `session_id` description text only, no structural change | **SHARED RESOURCE** — used as codex `--output-schema` target AND by collector conformance check; do NOT alter structure/required |
| `scripts/compound-v-collect-results.py` | NO CHANGE expected — already transport-agnostic (lines 253–258); listed only to assert it is intentionally untouched | collector (normalization single-point) |
| `docs/superpowers/execution/<run-id>/logs/` (IF the plan chooses persistent logs) | NEW directory convention | **SHARED RESOURCE** — new run-dir layout element; dispatcher + liveness + status must agree |
