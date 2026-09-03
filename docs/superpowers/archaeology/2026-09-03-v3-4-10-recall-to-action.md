# v3.4.10 recall→action — Code Archaeology

**Spec audited:** `docs/superpowers/specs/2026-09-03-v3.4.10-recall-to-action-design.md`
**Plan already on disk (read for context, not rubber-stamped):** `docs/superpowers/plans/2026-09-03-v3.4.10-recall-to-action.md`
**Repo:** `/Users/oleg/Dev/superpowers-v` @ `main`

**Note on sequencing.** Per this agent's charter, this audit is built from the CODE, not the
plan — the plan is one more claim to verify. Several of its Task A bullets do not survive
contact with the code (§2, §3, §5, §6); most seriously, its central write target
(`state["jobs"][id]["recall_check"]`) is described as if `build_plan`/`cmd_emit` already had a
state.json write path. It does not.

## Step 0 — V-memory recall

Ran `compound-v-memory.py search` four times (planning intent): `"recall to action decision
memory challenge"`, `"emit workflow recall-check auto_tighten emitter"`,
`"compound-v-emit-workflow.py implementer prompt tier escalation state.json"`, `"cmd_emit never
touches state.json register-lane"`. No prior archaeology exists for this exact subsystem
(recall→action at emit time). Load-bearing adjacent hits, cited inline below where they bind:
`docs/superpowers/archaeology/2026-09-03-v3-4-8-workflow-retry.md` (the retry/reviewer-escalation
machinery this feature sits directly beside — same file, same wave loop, same escalation-ladder
vocabulary), `docs/superpowers/archaeology/2026-09-03-v3-4-9-preflight-kb-paths-and-retries-schema.md`
(this project's own prior finding that `_load_state`/`_save_state`/register-lane is the correct
place to look for "who writes into `state["jobs"][id]`" questions), and
`docs/superpowers/archaeology/2026-09-03-v3-4-2-transcript-watch.md` §2 (independently documents
`register-lane` as the writer of `state.json.jobs.<id>.isolation` — corroborates §2/§3 below).
`skills/compound-v/memory.md` and `commands/v-init.md` were read directly (not just recalled) —
both currently state the three phantom actions (`force_worktree`, `extra_review_pass`,
`fold_into_task0`) verbatim, confirming the spec's own description of what needs replacing.

## 1. Matrix

Dimensions: **job kind** (implement vs. reviewer, via `_is_reviewer_job`) × **recall verdict**
(`tighten` / `none` / `unavailable`) × **`memory.auto_tighten`** (true/false) × **`prior_attempt_failed`**
(this job already failed once in this run — the existing, unrelated escalation trigger).

| Job kind | Verdict | `auto_tighten` | `prior_attempt_failed` | What the spec wants | Existing mechanism it must compose with |
|---|---|---|---|---|---|
| implement | `tighten` | false | false | prompt section only | none — new code |
| implement | `tighten` | true | false | tier +1 rung, review acceptance gains re-check clause | **no tier ladder exists** (§3) |
| implement | `tighten` | true | true | tier +1 rung (recall) **and** model +1 rung (existing re-attempt escalation), same job | **untested interaction, two different axes** (§2) |
| implement | `none` / `unavailable` | any | any | nothing | — |
| reviewer | (recall-check never run on reviewers per spec text) | — | — | acceptance gains re-check clause **only if some implement job in the manifest tightened** | **no code today maps "this reviewer" → "the implement jobs it reviews"** (§2) |
| implement | `tighten` | true | — | explicit `model:` pin must stay untouched | Trivially true **only if** the new tier value is fed into `resolve_job_model`, which checks `job.get("model")` first (`:1295-1297`) and never inspects tier when a pin is present — a real, already-existing safety property, not something Task A has to build (§3) |

**Not handled by the plan as written:** the reviewer-selection cell above. Every manifest this
repo has actually run (156 occurrences of `type: review` across 151 `manifest.yaml`/`dispatch.workflow.js`
files, one review job per manifest depending on every implement job — confirmed pattern, not
schema-enforced) has exactly one review job, so "the review job" is unambiguous in practice. But
the code enforces no such cardinality, and no existing function maps an implement job to "the
review job(s) that will read its diff." The plan's Task A bullet ("append to the review job's
acceptance") presumes this resolves itself; it does not name how.

## 2. Shared State

### `state["jobs"][job_id]["recall_check"]` (does not exist; the plan's own write target)

- **`build_plan()`/`cmd_emit` (`scripts/compound-v-emit-workflow.py:1553-1798`, `:5311-5414`) never
  call `_load_state` or `_save_state`.** Exhaustively grepped every call site of both functions in
  this 7,200+-line file: they appear in `cmd_gate_receipt` (:3223), `cmd_record` (:4352),
  `cmd_register_lane` (:5084), `cmd_resume`-adjacent reconciliation code (:4590-4667), and roughly
  twenty selftest fixtures — never once inside `build_plan`, `job_entry`, or `cmd_emit`. The
  Python process that runs at `emit` time has, today, zero read or write path to `state.json`.
- **`state.json` DOES already exist on disk when `emit` runs** — `commands/v-orchestrate.md:5`
  ("a manifest.yaml plus an initial state.json") and `commands/v-dispatch.md:19,33` both confirm
  `/v:orchestrate` (or `/v:dispatch`'s own materialize step) writes the initial file *before*
  `emit` is invoked (`commands/v-dispatch.md:136`). So the plan's target is reachable, but only by
  adding a genuinely new state.json read-modify-write to `cmd_emit` — using the file's own
  `_load_state`/`_save_state` helpers (not a bespoke JSON read) — which is a different, larger
  change than "in build_plan ... record recall_check on the job's state entry" reads as.
- **A second, arguably more correct mechanism already exists and does exactly this shape of write:**
  `cmd_register_lane` (`:4989-5100+`) is documented as *"the Implement stage's FIRST tool call"*
  (comment at :5059) and already does `state = _load_state(run_dir); entry =
  state["jobs"].setdefault(args.job_id, {}); entry.setdefault("baseline", ...)` under
  `_run_dir_lock` (:5083-5086) — i.e. it is the one place in the whole lifecycle proven to run
  *before* a job's real work starts and to write into that job's state entry. Its argv is built by
  the *emitted JS*, not by `build_plan` directly (`compound-v-emit-workflow.py:1943`,
  `'%s -B %s register-lane --run-dir %s --job-id %s ...'`). Threading `recall_check` through here
  means baking the verdict into `CFG.jobs[id]` at emit time (which `build_plan` already can do)
  and adding a new `--recall-check-json` flag to `cmd_register_lane`'s argv — a *different* patch
  surface than the one the plan names (`cmd_gate_receipt`'s argv, per its bullet 2).
- **Gap the plan must resolve explicitly, not by implication:** pick ONE of (a) teach `cmd_emit`
  to read/merge/write `state.json` directly at emit time (new capability for a function that has
  never touched this file), or (b) thread the verdict through `CFG` and land it via
  `register-lane`'s existing runtime write path (new CLI flag, JS argv change, but reuses a
  mechanism proven to run at the right moment). The plan's bullet 2 proposes a *third* location
  (`gate-receipt`'s argv) for a *different* purpose (copying into the *receipt*) — see next
  finding — and never mentions that the state.json write itself has no home yet.

### `cmd_gate_receipt` — already reads `state_job` (`:3223-3224`), which changes the plan's own bullet 2

- `cmd_gate_receipt` does `state = _load_state(run_dir); state_job = state["jobs"].get(job_id) or {}`
  at :3223-3224, purely to read the pinned `baseline` (:3225). **If `recall_check` lands in
  `state["jobs"][job_id]` by either mechanism above, `cmd_gate_receipt` can read
  `state_job.get("recall_check")` directly and copy it onto the receipt with zero new CLI
  surface** — no `--recall-check-json` flag needed. The plan's own bullet 2 ("add
  `--recall-check-json` or reuse the existing job-spec pass-through — pick the smaller change")
  frames this as an open choice between two NEW mechanisms; the actually-smaller change is a third
  option neither bullet names: read what's already loaded. `--escalated-from`
  (`cmd_gate_receipt:3134-3138`) is the one true precedent for "a new gate-receipt flag," but it
  exists because the escalated model is a **retry-time** decision the JS computes and gate-receipt
  has no other way to learn — `recall_check` is known at **emit time**, before the JS runs at all,
  and state.json is already the channel gate-receipt reads from for exactly this reason.

### `job` (the raw manifest dict) vs. `entry` (the built dict) — an established mutation discipline the plan's tier-raise must respect

- Every derived/resolved value in `job_entry()` (model, model_source, model_note, tier-cap source,
  agent_isolation, …) is written onto **`entry`**, never back onto `job` — confirmed at
  `:1701-1725` for the model-escalation case: `entry["model"] = stepped`, `entry["model_note"] =
  "re-attempt after a recorded non-success: %s → %s"`, and `job` itself is left untouched.
- `resolve_job_model(job, ...)` (`:1279-1323`) reads `job.get("tier")` (:1298), i.e. it takes the
  **raw manifest job dict**, not `entry`. For an `auto_tighten` tier raise to actually change which
  model resolves, the call at `:1699` (`resolve_job_model(job, python_bin, stance=stance,
  config_path=config_path)`) must receive an ALREADY-RAISED tier — meaning the recall-check
  subprocess call and the tier decision have to run **before** line 1699, inside `job_entry()`,
  not "after each implement job's entry is built" as the plan's Task A bullet 3 literally says
  (entry is fully built, model already resolved, by the time `job_entry()` returns). The correct
  pattern, matching the file's own convention, is a **local variable** (e.g. an effective tier) fed
  into `resolve_job_model` via a shallow-copied job dict — never a mutation of the shared `job`
  object, which several later reads in the same function (`entry["tier"] = job.get("tier")` at
  :1640, evaluated earlier in source order but same object) depend on holding the manifest's
  *declared* value for audit purposes.

### `recall_check()`'s own `actions` field (`scripts/compound-v-memory.py:1084-1091`) — untouched by the plan, and now permanently stale

- `recall_check()` hardcodes `actions = ["force_worktree", "extra_review_pass", "fold_into_task0"]`
  whenever verdict is `tighten` — the exact three phantom actions the spec says don't map to
  Engine C. **`scripts/compound-v-memory.py` is not in the plan's Partition Map** (only
  `compound-v-emit-workflow.py`, `memory.md`, `v-init.md`, `CHANGELOG.md`). So after this ships,
  `recall-check`'s own JSON output (and anything that echoes it verbatim — e.g. the "emit JSON
  summary lists recall_check per job" bullet, if implemented as a passthrough of the whole verdict
  dict) will keep emitting `force_worktree`/`extra_review_pass`/`fold_into_task0` in the `actions`
  key, right next to a prompt section and a tier-raise that do neither of the three literal things
  named. Either the emitter must explicitly drop/ignore `verdict["actions"]` when relaying the
  verdict (never surface it verbatim), or `recall_check()`'s `actions` field itself needs updating
  — the plan is silent on which, and the field is a stale artifact of exactly the "three phantom
  actions" this feature exists to close.

### `.claude/compound-v.json` reads — an established helper exists, "do NOT import it" is correct but under-specifies which existing tool to reuse

- `config_wants_embeddings(root)` (`scripts/compound-v-memory.py:111-122`) is the one-purpose
  reader the plan's Task A cites as "the reader shape" to copy (`try: json.load(fh); return
  bool(cfg.get("memory", {}).get(...))`, catches `(OSError, ValueError, AttributeError,
  TypeError)`).
- `scripts/compound-v-emit-workflow.py` already has its own generic reader, `_read_json(path,
  default=None)` (`:357-362`), used throughout the file for exactly this class of "read a JSON
  file, degrade to a default on any error" need. The plan should use **this** file's own
  `_read_json` helper for `.claude/compound-v.json`'s `memory.auto_tighten`, not hand-roll a third
  copy of the same three-line pattern — `config_wants_embeddings`'s shape is a good model for the
  *exception tuple*, but `_read_json` is the actually-DRY tool already living in the file being
  edited.

## 3. Sibling Code

### `escalate_claude_model` / `CLAUDE_ESCALATION` (`:1072`, `:1263-1276`) — the MODEL ladder, not a tier ladder

Read in full. `CLAUDE_ESCALATION = ("sonnet", "opus", "fable")`; `escalate_claude_model(model)`
steps one rung by **string value**, refusing (returning unchanged, with a reason) for any value
not on the ladder — the exact "don't touch a pin we don't own" property the spec wants for the
tier raise too. **This is the wrong axis to reuse for `auto_tighten`'s tier raise**: it escalates a
resolved *model name*, not a manifest *tier*. `resolve_job_model` never sees a "tier ladder" — it
calls out to `compound-v-resolve-model.py` with whatever `tier` string the job declares.

### `TIERS` (`scripts/compound-v-resolve-model.py:163`) — a landmine for anyone grepping for a tier ladder

`TIERS = ("frontier", "deep", "standard", "light")` — **ordered high-to-low**, the reverse of an
ascending escalation ladder. An implementer searching this codebase for "the tier ladder" to reuse
will find `CLAUDE_ESCALATION` (wrong axis, model not tier — see above) and `TIERS` (right axis,
wrong direction — `TIERS.index("light")` is `3`; stepping "+1" walks *toward* `light`, not away
from it). **No ascending `light→standard→deep` mapping exists anywhere in this repo today.** Task
A must define one from scratch (e.g. a two-entry dict `{"light": "standard", "standard": "deep"}`,
mirroring `escalation_map()`'s shape at `:1114-1123` but for tiers, not models) and must not reuse
`TIERS` as-is.

### `_is_reviewer_job` / `prior_attempt_failed` gate (`:1232-1261`, used at `:1708`)

Read in full. `if not _is_reviewer_job(job) and prior_attempt_failed(abs_run_dir, job_id):` is the
existing guard that exempts reviewers from the (unrelated) cross-run model-escalation-on-retry
mechanism, with the stated rationale that a sealed review receipt must carry literal Opus. The
spec's `recall-check` is scoped to "every implement job" already (spec text, "Decision" §1), so
this exact collision doesn't recur for recall-check's own subprocess call — but the **tier raise**
Task A builds is a new code path inside the same `if backend == "claude":` block (:1693), and
whoever writes it needs to positively confirm it is gated the same way (never run for a job where
`_is_reviewer_job(job)` is true), rather than assuming "implement job" scoping happens elsewhere
by construction.

### `cmd_register_lane` (`:4989-5100+`) — read in full; the closest sibling for "write into state.json before a job starts"

Already covered in §2 for its write-target relevance. Notably: it takes `--repo-root` (required,
never defaulted — the same paranoia `cmd_emit` and `cmd_gate_receipt` show about repo identity),
locks the run dir (`_run_dir_lock`) around every `state.json` mutation, and uses `setdefault`
(never overwrite) when merging into a job's entry — the exact discipline any new `recall_check`
write into the same dict needs to match, wherever it ends up living.

### `_run(cmd, cwd=None, env=None, text=True)` (`:242-260`) — no timeout parameter, anywhere, ever

Read in full, then grepped every one of its ~40 call sites in this file. **Not one passes a
timeout; the function's signature has none.** It wraps `subprocess.Popen(...).communicate()` with
no `timeout=` argument — a hung child process blocks the caller forever. This has apparently never
mattered because every existing caller shells out to fast, local, non-network commands (`git`,
the model resolver, scope-check, the model wrapper CLI). The plan's Task A bullet 1 specifies "a
30 s timeout" for the recall-check subprocess call as if this were an existing capability to pass
in — it is not. Building it requires either (a) a new optional `timeout=` kwarg on `_run()`
itself (touches the shared helper every other call site in this SHARED-RESOURCE file also uses,
though an optional kwarg with a `None`/no-timeout default is additive and safe), or (b) a bespoke
`subprocess.run(cmd, timeout=30)` call for this one site that duplicates `_run`'s
`PYTHONDONTWRITEBYTECODE` env setup and never-raise contract. Neither is named in the plan.

## 4. External APIs

None. This feature touches zero third-party libraries or hosted APIs, and — unlike the sibling
v3.4.8 retry feature — it never runs inside the emitted JS/Workflow sandbox at all: the recall
lookup happens entirely in the Python `emit` step, before any `agent()` call exists. So the JS
runtime's `Math.random()`/`Date.now()`/`setTimeout` bans and its
resolve-vs-throw ambiguity on `agent()` (both hard blockers for v3.4.8, per
`docs/superpowers/archaeology/2026-09-03-v3-4-8-workflow-retry.md` §4) simply do not apply here —
worth stating explicitly since this is exactly the kind of runtime-capability gap Phase 1A exists
to catch, and for this feature it is a **non-issue by construction**, not an oversight.
`compound-v-memory.py` itself is confirmed pure-stdlib (`skills/compound-v/memory.md:15`, "pure
stdlib core, offline") — the subprocess call adds no new dependency.

## 5. Regression Surface

1. **`scan_failures()` (`compound-v-memory.py:1031-1058`) is an unbounded, uncached `os.walk` over
   the ENTIRE `docs/superpowers/execution/` tree, re-run from scratch on every `recall-check`
   invocation.** This repo currently has 150+ run directories under `docs/superpowers/execution/`
   (confirmed by direct enumeration while auditing §1's manifest count). Task A's design calls
   `recall-check` **once per implement job**, as a **new subprocess**, on **every `emit`**. An
   8-job manifest now pays 8 full history walks (each parsing every `results/*.json` under every
   run directory) on every single `emit` call — and `emit` is not called once per run: `/v:resume`
   re-emits, and a manifest can be re-emitted manually while iterating. This is a real, currently
   invisible latency regression on `emit` that grows monotonically with the project's own run
   history — the exact kind of "small change, unbounded cost" this project's own AGENTS.md
   philosophy (see the lane-guard timing methodology) says should be measured, not assumed cheap.
2. **No timeout on `_run()` (§3) turns "recall-check hangs" into "emit hangs forever," which is
   *worse* than the failure mode the spec explicitly designs around.** The spec's own text says
   "a missing or erroring `compound-v-memory.py` is noted and stepped past, never a reason to
   refuse to emit" — but that fallback only fires on a **completed** subprocess with a bad exit
   code or bad JSON. A **hung** subprocess (e.g. a corrupted/huge results tree, a filesystem stall)
   never reaches that fallback at all; it blocks `cmd_emit` indefinitely, turning a fully automatic
   `/v:dispatch` into a silent hang with no error, no timeout, no diagnostic — regressing every
   existing `emit` call, not just the ones that would have hit `tighten`.
3. **`state["jobs"][job_id]` is written by at least three existing paths today** (`register-lane`
   at job start, `gate-receipt`'s read at gate time, `cmd_record`'s
   `state["jobs"].setdefault(job_id, {}).update(state_job)` at :4353 after the job finishes). If
   Task A adds a **fourth** writer (`cmd_emit`, pre-dispatch) that does not use the same
   `_load_state`/`_save_state` + `setdefault`/merge discipline every existing writer uses, it risks
   clobbering fields a later writer expects to already be there, or being silently clobbered itself
   by `cmd_record`'s own `.update(state_job)` if `state_job` (built fresh inside `cmd_record`,
   `:4107` `dict(_load_state(run_dir)["jobs"].get(job_id) or {})`) does not explicitly preserve an
   `recall_check` key it never touches — `dict(...)` copies existing keys first, so `.update()`
   downstream should be additive and safe **only if** `cmd_record` is never made to construct
   `state_job` from scratch instead of copying the existing entry. Confirm this remains true after
   the edit; it is fragile-by-convention, not fragile-by-schema.
4. **Every implement job's prompt file changes shape** (`render_worker_prompt`,
   `:1364-1450+`, called once per job inside `job_entry()` and written to disk immediately by
   `cmd_emit`, :5386) whenever a `tighten` verdict fires. This is a **pure addition** with low
   regression risk to the render function's existing behavior (its own hard-refusal path for a
   missing `body`, :1422-1432, is untouched by anything upstream of the new section) — noted here
   only because `render_worker_prompt`'s docstring is explicit that the template deliberately adds
   nothing beyond lanes/acceptance/cap; the new section is a first, deliberate exception to that
   stated design principle and should be justified as such in the eventual plan, not just added.

## 6. DRY Findings

- **`_read_json` (`compound-v-emit-workflow.py:357-362`) already exists in the file being edited**
  and is the right tool for reading `.claude/compound-v.json`'s `memory.auto_tighten` — reuse it
  rather than hand-rolling a third `try: json.load / except: default` block (§2).
- **`register-lane` already writes into `state["jobs"][id]` at the right moment in the job
  lifecycle** (§2, §3) — before deciding to teach `cmd_emit` a brand-new state.json write
  capability it has never had, confirm whether threading the verdict through `CFG` and into
  `register-lane`'s existing write isn't the smaller, more consistent change.
- **`cmd_gate_receipt` already loads `state_job` from `state.json`** (§2) — if `recall_check` lands
  in state.json by either mechanism, no new `--recall-check-json` CLI flag is needed on
  `gate-receipt` at all; the plan's bullet 2 proposes solving a problem that (once the state.json
  write exists) is already solved.
- **No tier-escalation ladder exists anywhere in this repo** (§3) — `CLAUDE_ESCALATION` is models,
  `TIERS` is descending and for a different purpose. This is new code, not a reuse opportunity, and
  should be named as new rather than assumed to already exist "like `escalate_claude_model` does."
- **`recall_check()`'s `actions` field is a live duplicate of exactly the three phantom actions
  this feature exists to retire** (§2), and it is outside the plan's Partition Map. Decide
  explicitly whether to strip it at the point of consumption or fix it at the source
  (`compound-v-memory.py`, which would then need to join the Partition Map).

## 7. Design constraints for the spec (non-negotiable)

1. **`build_plan`/`cmd_emit` has no existing read or write path to `state.json`.** The plan must
   explicitly choose one of: (a) add a new, lock-free (emit runs single-process, pre-dispatch, so
   no concurrent writer exists yet) `_load_state`/merge/`_save_state` step inside `cmd_emit`, or
   (b) bake `recall_check` into `CFG.jobs[id]` and add a new flag to `cmd_register_lane`'s argv so
   the verdict lands in state.json via the existing runtime write path that already proves it runs
   before a job's work starts. Silence on this, as in the plan's current Task A bullet 2, is not an
   implementation detail — it is the load-bearing decision the rest of the feature depends on.
   (§2, §3)
2. **The tier raise must be computed and applied *inside* `job_entry()`, before the
   `resolve_job_model(job, ...)` call at `compound-v-emit-workflow.py:1699`**, not "after the
   entry is built" as currently worded — by the time `job_entry()` returns, model resolution has
   already happened against the manifest's original tier. Use a local/copied value, never a
   mutation of the shared `job` dict, matching this function's existing convention of writing every
   derived fact onto `entry`. (§2)
3. **No ascending tier ladder (`light→standard→deep`) exists in this codebase.** It must be
   authored as new code, explicitly distinct from `CLAUDE_ESCALATION` (models, `:1072`) and `TIERS`
   (`compound-v-resolve-model.py:163`, descending, wrong direction if indexed naively). (§3)
4. **`_run()` has no timeout parameter, on any of its ~40 call sites in this file.** "A 30 s
   timeout" is new capability, not a flag to pass to an existing helper — decide whether to extend
   `_run()` itself (additive, optional kwarg, touches a SHARED RESOURCE) or write a dedicated
   bounded subprocess call for this one site, and treat a **hang** (not just a bad exit code) as a
   case the "never a reason to refuse to emit" fallback must actually cover. (§3, §5-2)
5. **`recall-check` is called once per implement job, as a fresh subprocess, on every `emit` — and
   `scan_failures()` re-walks the entire (currently 150+ run directory) execution tree every single
   call, with no caching across jobs or across repeated emits of the same manifest.** State this
   cost explicitly and decide whether it is acceptable as-is, whether the N-job case should share
   one scan, or whether this is deferred with a stated reason. (§5-1)
6. **Explicitly decide what happens to `verdict["actions"]`** (`compound-v-memory.py:1084-1091`,
   still literally `force_worktree`/`extra_review_pass`/`fold_into_task0` after this ships, since
   `compound-v-memory.py` is outside the Partition Map). If the emitted `state.json`/gate
   receipt/emit-summary echoes the raw verdict dict anywhere, this stale field surfaces right next
   to the two real actions the doc rewrite (Task B) is about to describe — either strip it at the
   point of consumption or bring `compound-v-memory.py` into scope to fix it at the source. (§2, §6)
7. **State explicitly how "the review job" is identified**, given no code today maps an implement
   job to the review job(s) that depend on it, and the manifest schema does not enforce
   exactly-one-reviewer-per-manifest (every manifest observed in this repo happens to follow that
   pattern, but it is a convention, not a constraint the emitter checks). (§1)
8. **Confirm the tier raise is gated by `_is_reviewer_job(job)` the same way the existing
   model-escalation-on-retry branch is** (`:1708`), even though `recall-check` itself is already
   scoped to implement jobs by the spec's own text — the tier-raise code path is new and must
   positively re-state the same exclusion, not inherit it by assumption. (§3)
9. **If `cmd_emit` gains a new `state.json` writer, it must use `_load_state`/`_save_state` and a
   `setdefault`/merge pattern**, matching `cmd_register_lane`'s and `cmd_record`'s existing
   discipline — a raw overwrite risks clobbering fields those two writers already depend on being
   present later in the same run. (§2, §5-3)
10. **Reuse `_read_json` (`compound-v-emit-workflow.py:357-362`) for the `.claude/compound-v.json`
    read**, not a bespoke third copy of the try/except JSON-load pattern. (§2, §6)

## 8. File Touch Map (for Phase 2 partitioning)

| File | Role | SHARED RESOURCE? |
|---|---|---|
| `scripts/compound-v-emit-workflow.py` | 7,200+ lines. Owns `build_plan`/`job_entry` (where the recall-check call and tier-raise must be sequenced correctly relative to `resolve_job_model`), `render_worker_prompt` (prompt section), `cmd_emit` (emit JSON summary; currently zero state.json touch), `_load_state`/`_save_state`/`_run_dir_lock` (the mechanism any state.json write must reuse), `cmd_register_lane` (the alternate, arguably-correct write hook), `cmd_gate_receipt` (already reads `state_job` — may need zero new argv), `_run()` (no timeout, ~40 call sites), `_read_json` (the reuse target for config reads), `CLAUDE_ESCALATION`/`escalate_claude_model` (the sibling ladder pattern to mirror, not reuse directly), `selftest()` (~2,100 lines of its own). | **SHARED RESOURCE** — single largest file in the repo; every recent feature (v3.4.8, v3.4.9) has landed here too. |
| `scripts/compound-v-memory.py` | Owns `recall_check()`/`cmd_recall_check` (the subprocess target), and the stale `actions` field (§2, §7-6) — **not in the plan's Partition Map**, flagged because the plan's own consumption of the verdict may need it to be, or must explicitly filter around it. | Read-only dependency for this feature as scoped; **contested** whether it should be in-scope (§7-6). |
| `scripts/compound-v-resolve-model.py` | Not touched by the plan. Owns `TIERS` (descending, wrong direction for a ladder — §3) and the per-stance tier→model tables that make "deep resolves to opus" true. Relevant as read-only context for why the tier raise's downstream model choice is safe, not as an edit target. | No — read-only reference. |
| `skills/compound-v/memory.md` | Task B — replace the three phantom actions (already confirmed present verbatim at lines 88-89) with the two real ones. | No — prose doc, but widely cross-referenced (`SKILL.md`, `routing-policy.md`, `v-remember.md` all link here). |
| `commands/v-init.md` | Task B — Step 3b (lines ~346-349, confirmed present verbatim: "force worktree / +review pass / fold into Task 0") needs the same replacement, independently, since it's a separate prose copy of the same three actions. | No. |
| `CHANGELOG.md` | Task B — `[Unreleased]` entry. | **SHARED RESOURCE** — every plan in this repo appends here; low collision risk if appended, not inserted mid-file (per the v3.4.9 audit's identical note on this same file). |
| `skills/compound-v/execution-manifest.md` | **Not in the plan's Partition Map.** Documents the manifest's `retry`/tier vocabulary; if a new ascending tier-escalation concept is introduced (§3, §7-3), this is the natural place a schema-literate reader would look for it next to the existing retry-lift language the v3.4.8 feature already added there. Flagging as a decision, not a silent omission. | Not touched by this plan as scoped. |
| `docs/superpowers/execution/**/results/*.json` | **Read, not written**, by every `recall-check` invocation this feature adds (§5-1). Not a file to edit, but the growth of this directory (150+ run dirs today) is the direct driver of the performance regression finding — worth the plan author's awareness when deciding whether to cache or bound the scan. | Not a touch target; flagged for its role as the ambient cost driver. |
