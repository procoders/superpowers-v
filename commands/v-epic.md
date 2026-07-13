---
description: Drive an EPIC — chain several features into one autonomous, resumable, dependency-ordered build on a single branch. Each feature runs through the FULL v1.0 pipeline (recon-gated spec → 3 pre-flights → writing-plans + partition → manifest → dispatch → 3-pass review) in topological order, accumulating onto the current branch. Resume-aware via epic-state.json; ends with a cross-feature integration review and finishing-a-development-branch.
---

You are running **`/v:epic`** — the **epic driver** of Compound V. A v1.0 run executes ONE plan (one feature). An **epic** chains several: an ordered set of features, each run through the full v1.0 pipeline, in dependency order, accumulating onto **one branch**. "Build a whole app." It is the same discipline one level up — resumable, topological, no daemon.

The epic spec is `{{args}}` (a path to an epic brief, or a described feature set).

The epic model, run-dir layout, the final integration review, and the honesty boundary are defined in [`skills/compound-v/epic-mode.md`](../skills/compound-v/epic-mode.md) — read it; it is the authority. The deterministic state spine is [`scripts/compound-v-epic-state.py`](../scripts/compound-v-epic-state.py) (one level up from [`state-machine.md`](../skills/compound-v/state-machine.md)). Each per-feature run is a normal v1.0 run materialized per [`execution-manifest.md`](../skills/compound-v/execution-manifest.md).

## Steps

1. **Resolve the epic spec.** From `{{args}}`: if it is a path to an epic brief, read it; if it is a described feature set, work from the description. If `{{args}}` is empty, ask the user for the epic brief (or list existing epics under `docs/superpowers/execution/epics/` to resume one). Pick an `<epic-id>` (convention: `YYYY-MM-DD-<slug>`) and an epic **title**, and capture the epic's **acceptance criteria** (used by the final integration review). Agree an **autonomy budget** with the user — `MAX_FEATURES` per `/v:epic` invocation. Seed the default from `.claude/compound-v.json` `epic.max_features` if set (written by [`/v:init`](v-init.md) Step 3c), else **1**: build one feature, then checkpoint; raise it only when the user wants more autonomy per run. An epic is *N full v1.0 runs*, so this is the **human checkpoint cadence** — a *driver policy*, not a script-enforced token meter: by default the loop builds one feature, reports `--stats`, and stops for you to review and re-run.

   **Marathon gate (opt-in, v2.10).** If `.claude/compound-v.json` `epic.autonomy.stance == "marathon"` (written by [`/v:init`](v-init.md) Step 3c) or the user explicitly asks for the autonomous/marathon loop for this invocation, this epic runs the **[Autonomous marathon loop](#autonomous-marathon-loop-opt-in-v210)** below instead of steps 4–7 — `MAX_FEATURES` does not apply there (marathon is bounded by global breaker caps, not a per-invocation feature count). Otherwise (the default, unconfigured case) continue with the checkpoint loop in steps 4–7 exactly as documented — nothing below changes for you.

2. **Decompose + spec every feature UP FRONT — the one interactive phase.** Decompose the product into independent-ish **features**, each a *vertical slice* (`auth`, `api`, `ui`), not a layer; capture cross-feature dependencies in `depends_on` (`api` depends_on `auth`). Then, for **each** feature, run `superpowers:brainstorming` to produce a real **per-feature spec file** (with feature-level Acceptance Criteria), saved to `docs/superpowers/execution/epics/<epic-id>/specs/<feature-id>.md`. **Trigger 0 applies to each of these brainstorms:** before each per-feature brainstorm, run the pre-brainstorm recon gate sequence from [`phase-0-recon.md`](../skills/compound-v/phase-0-recon.md) (plumbing-skip → KB-hit → config); later features in the same epic increasingly skip via the KB-hit gate as earlier recon/audit docs accumulate — designed behavior, not a bypass. This is the **only** human-interactive phase: every spec is written and approved *here*, before the autonomous loop — so the loop never pauses to brainstorm. That batching is what makes the epic genuinely **autonomous** *and* keeps a **real spec per feature** (the central tension, resolved). Write `features.json` = a JSON array of `{id, title, depends_on, spec_path}`, each `spec_path` pointing at its spec file.

3. **Review the decomposition, then init (specs enforced).**
   - **Gate the feature DAG before building** (one level up from partition-review): `python3 scripts/compound-v-epic-state.py --lint --features docs/superpowers/execution/epics/<epic-id>/features.json` flags structural smells (an **ISLAND** feature with no deps *and* no dependents = a likely missed dependency; an **over-coupled** feature depending on most others = a layer, not a slice) plus any hard validation error. Then **critique it yourself**: are these real vertical slices, are `depends_on` correct *and complete*? A missing edge means a feature builds before its prerequisite. Fix `features.json` until lint is clean and the split is sound — a weak decomposition is the #1 way an epic fails downstream.
   - **Resume-aware init.** The epic lives at `docs/superpowers/execution/epics/<epic-id>/epic-state.json`. **If it already exists → CONTINUE** (read it; first run `python3 scripts/compound-v-epic-state.py --check-specs --state <epic-state.json>` to confirm every non-`done` feature still has an existing, contained `spec_path` — this guards an old or hand-made state from entering the loop spec-less — then go to the loop). **Else** initialize:
     ```
     python3 scripts/compound-v-epic-state.py --init --require-specs \
       --features docs/superpowers/execution/epics/<epic-id>/features.json \
       --epic-id <epic-id> --title "<title>" \
       --out docs/superpowers/execution/epics/<epic-id>/epic-state.json
     ```
     `--require-specs` **refuses to start unless every feature has an existing `spec_path`** — the deterministic enforcement that no feature enters the autonomous loop without an approved spec. It also validates ids/refs/cycles/dups. A non-zero exit ⇒ fix and re-init; never hand-edit the state.
   - **Marathon init (only for a NEW epic, gated by step 1).** If the marathon gate applies and `epic-state.json` does not exist yet, add `--stance marathon` plus the agreed breaker caps to the `--init` command above: `--stance marathon --max-attempts-per-feature <N> --max-no-progress-cycles <N> --max-wall-clock-hours <H> --start-sha <sha>` (leave `--max-total-attempts` unset to take the script's feature-count-derived default, `max(6, 3×features)`, unless the user wants a specific number). Capture `<sha>` with `git rev-parse HEAD` **at this init moment** and pass it — it is stored as `autonomy.start_sha` and is the baseline the halt-page's accumulated-diff command (§7) and the final integration review (§8) diff against. **Marathon has no in-place upgrade.** An existing checkpoint `epic-state.json` (no `autonomy` block) cannot be flipped to marathon after the fact — `build_state`/`--init` only ever writes the marathon fields at creation time. If the epic already exists as a checkpoint state and the user now wants marathon, the options are: (a) keep finishing it in checkpoint mode (steps 4–7), or (b) start a **fresh** `--epic-id` with `--stance marathon`, reusing the same `features.json`/spec files under a new epic id. Never hand-edit an existing `epic-state.json` to inject an `autonomy` block.
   - **Commit the epic-level files right after init**: `features.json` and the freshly-created `epic-state.json` are new, uncommitted files. Two separate commands, checking each exit code — never chain with `&&`: `git add docs/superpowers/execution/epics/<epic-id>/features.json docs/superpowers/execution/epics/<epic-id>/epic-state.json`, then `git commit -m "chore(v-epic): init epic <epic-id>"`. (Per-feature spec files are committed by `superpowers:brainstorming` itself when each spec is approved, in step 2 — no separate action needed for those.)

4. **The autonomous loop (checkpoint stance — the default).** If the marathon gate (step 1) applies, **skip steps 4–7** and use the [Autonomous marathon loop](#autonomous-marathon-loop-opt-in-v210) after step 7 instead — everything below this point is the unchanged checkpoint behavior. Bounded by `MAX_FEATURES`. Repeat until no feature is runnable **or this invocation's budget is spent**:
   - **Ask for the next runnable feature:**
     ```
     python3 scripts/compound-v-epic-state.py --next \
       --state docs/superpowers/execution/epics/<epic-id>/epic-state.json
     ```
     It prints `{"feature": <feature|null>, "reason": "runnable|epic complete|epic blocked: …|epic needs reconcile: …"}`. A feature is runnable when it is `pending` and **all** its `depends_on` are `done`, returned in topological order. The loop is **fail-fast (checkpoint stance)**: any `failed` feature halts the whole epic (even independent pending features wait) until reconciled — `--next` will not route around a failure. (The marathon loop below uses a different, DAG-aware routing rule — `--next --autonomous` — that continues past an abandoned feature onto its independents; the fail-fast rule here applies only to the checkpoint `--next`.)
   - **If `feature` is non-null** (`reason == "runnable"`):
     1. **Choose the run-id, then mark it running WITH that run-id.** Pick the feature's run-id up front (convention `<epic-id>-<feature-id>`) — it names the v1.0 run dir — and record it **now**: `compound-v-epic-state.py --update --feature <id> --status running --run-id <run-id> --state <epic-state.json>`. Recording `run_id` at *running* time (not only on done/failed) is what makes a **mid-run crash recoverable** via `/v:resume <run-id>` (step 7); a `running` feature with a null `run_id` has nothing to resume.
     2. **Run that ONE feature through the v1.0 pipeline's post-spec execution tail on the current branch** — exactly as a standalone feature, reusing everything (Trigger 0 recon and brainstorming already ran up front in step 2; the loop never repeats them):
        - **Read the feature's already-approved spec** (`spec_path` from step 2). The loop does **not** brainstorm — specs were batched + approved up front, so this stage is non-interactive.
        - The **three pre-flights** in parallel (1A archaeology ∥ 1B domain ∥ 1C library) per [`SKILL.md`](../skills/compound-v/SKILL.md). A 🔴 critical finding HALTs this feature.
        - `superpowers:writing-plans` + **Phase-2 Partition Map** ([`phase-2-disjoint-partitioning.md`](../skills/compound-v/phase-2-disjoint-partitioning.md)).
        - **Materialize a manifest** ([`/v:orchestrate`](v-orchestrate.md)) into a per-feature run dir, then **dispatch** ([`/v:dispatch`](v-dispatch.md)) — partition-review → Task 0 serial → parallel batches → `git diff` scope gate → collect.
        - The **3-pass Review Gate** (spec · quality · final integration, AC-gated).
        - The scope gate, model-broker, failure-handling, and scorecards all apply **per feature**, unchanged.
     3. **On the feature's success**, mark it done with the v1.0 run-id of its run dir:
        ```
        python3 scripts/compound-v-epic-state.py --update --feature <id> --status done \
          --run-id <run-id> --state docs/superpowers/execution/epics/<epic-id>/epic-state.json
        ```
     4. **On the feature failing** (scope-gate BLOCKED, unresolvable reviewer ISSUES, a 🔴 pre-flight, or an exhausted backend) — mark it `failed`:
        ```
        python3 scripts/compound-v-epic-state.py --update --feature <id> --status failed \
          --run-id <run-id> --state docs/superpowers/execution/epics/<epic-id>/epic-state.json
        ```
        then **stop the loop** and go to step 6 (the epic is now blocked but resumable).
     5. **Checkpoint (human-in-the-loop cadence — checkpoint stance).** Count each completed feature against `MAX_FEATURES`. When this invocation's budget is spent: **first commit `epic-state.json`** — two separate commands, checking each exit code — `git add docs/superpowers/execution/epics/<epic-id>/epic-state.json`, then `git commit -m "chore(v-epic): checkpoint <epic-id> (<N> features done)"` — **then STOP and report** `python3 scripts/compound-v-epic-state.py --stats --state <epic-state.json>` (done / remaining) so the human reviews the accumulated diff and re-runs `/v:epic` to continue. **The commit is not optional**: each feature's own v1.0 run already commits *that feature's* run directory (parallel-dispatcher's Step 7), but epic-state.json itself (which `run_id`/`status` each feature is at — the epic's *only* resume mechanism) lives one level up and is never covered by that. A checkpoint is exactly the moment control returns to a human who might close the session or clean up the worktree — an uncommitted `epic-state.json` at that instant means a later `/v:epic <epic-id>` has no record of what's done, and a `finishing-a-development-branch` cleanup can erase it outright. This is a *driver-enforced cadence*, not a token ceiling; with the default `MAX_FEATURES=1` the epic checkpoints (and commits) after **every** feature.
   - **If `feature` is null**, branch on `reason` (step 5/6).

5. **Epic complete (checkpoint stance)** (`reason == "epic complete"`). All features are `done`. Run a **final cross-feature integration review**: the *whole accumulated diff* on the branch against the **epic's** acceptance criteria — not the per-feature ACs (those already passed in each feature's own review), but the cross-feature contracts: do the features compose, do shared boundaries line up, is the product coherent end-to-end. On PASS, **commit `epic-state.json` (same as the checkpoint step, if it isn't already)**, then hand to `superpowers:finishing-a-development-branch` (merge / PR / cleanup options) — never hand off with an uncommitted `epic-state.json`. On ISSUES, surface them and stay resumable.

6. **Epic blocked (checkpoint stance)** (`reason` starts with `epic blocked` — a feature `failed` or an unmet dependency). **Commit `epic-state.json` (same as the checkpoint step, if it isn't already), then stop and surface it.** Print `compound-v-epic-state.py --summary --state <epic-state.json>` so the user sees exactly which feature failed and what it blocks. The epic stays **resumable** — but only if the `failed` status actually made it into git before anyone touches the worktree. After the user fixes the failed feature (or its spec/partition), retry it (`--update --feature <id> --status pending`) and re-run `/v:epic <epic-id>` (or the same brief) — step 3 detects the existing `epic-state.json` and continues; only `pending` features run, the `done` ones are skipped.

   **Epic needs reconcile** (`reason` starts with `epic needs reconcile` — a feature is still `running`). Because epic mode is **sequential**, `--next` is only ever called between features, so a `running` feature on resume means that feature's run **crashed mid-pipeline**. Do not route around it. **Reconcile by resuming first — don't discard half-built work:** the crashed feature ran a *normal v1.0 run* with its own crash-resume, so run **[`/v:resume <run-id>`](v-resume.md)** to re-dispatch only that run's incomplete jobs; if it completes, mark the feature **`--status done`**. **If the feature's `run_id` is null** (the crash happened before the run-id was recorded — see step 4.1 — or it is an old state), there is nothing to resume → restart it with **`--status pending`**. Only if a resumed run cannot be recovered, fall back to **`--status pending`** (full restart from the spec) or **`--status failed`** (abandon and stop). Never leave a feature `running` across a resume — the epic will not advance until the stale run is reconciled. **Whichever status this settles on, commit `epic-state.json` right after** — two separate commands, checking each exit code: `git add docs/superpowers/execution/epics/<epic-id>/epic-state.json`, then `git commit -m "chore(v-epic): reconcile <feature-id> -> <status>"` — the `--status failed` ("abandon and stop") path in particular is terminal and does not otherwise pass through the checkpoint step's commit.

7. **Report (checkpoint stance).** Print the epic summary (`--summary`), the per-feature run-ids, and the next step: the integration review + `finishing-a-development-branch` on complete, or the blocking feature + the resume hint on blocked.

## Autonomous marathon loop (opt-in, v2.10)

Gated by step 1's marathon check. Everything below **replaces steps 4–7** for this invocation — the checkpoint loop above stays byte-for-byte unchanged and is never touched by any of this. Full design: [`epic-mode.md`](../skills/compound-v/epic-mode.md) "Marathon stance"; the two scripts that back every command below: [`compound-v-epic-state.py`](../scripts/compound-v-epic-state.py) (its docstring's "## CLI contract" section is authoritative) and [`compound-v-epic-arbiter.py`](../scripts/compound-v-epic-arbiter.py) (its docstring's "## CLI contract (two-phase)" section).

### 0. Stance binding — the persisted state is authoritative, not config

Config intent alone (`.claude/compound-v.json` `epic.autonomy.stance=="marathon"`, or a manual `--autonomous` ask) is **not enough** to run this loop. Before issuing any `--next --autonomous` / `--record-*` / `--breaker-check` / `--trip-breaker` command, **read `epic-state.json` directly** (it is a plain JSON file — no dedicated subcommand exists to introspect just this one field) and confirm `.autonomy.stance == "marathon"`. If that block is absent (a checkpoint state, or an old/hand-made one), **REJECT autonomous operation for this epic** — fall back to the checkpoint loop (steps 4–7), or start a fresh marathon epic per step 3's "Marathon init" bullet. Re-check this on *every* re-entry (including a resumed session), not only at first init — a config flip after a checkpoint epic already started must never silently promote it to marathon.

### 1. Per-iteration progress + breaker check (before every feature)

At the top of each loop pass, pick a **stable cycle id for this pass** (an incrementing counter held in your own scratch state, or a UUID minted once per pass and reused for every call *within* that same pass, so one pass is never double-counted):

```
python3 scripts/compound-v-epic-state.py --record-progress-cycle --cycle-id <cycle-id> \
  --state docs/superpowers/execution/epics/<epic-id>/epic-state.json
```

Idempotent by `cycle_id` (safe to replay after a crash); compares this pass's `done` count to the last recorded count and resets/increments `no_progress_cycles`. Then:

```
python3 scripts/compound-v-epic-state.py --breaker-check \
  --state docs/superpowers/execution/epics/<epic-id>/epic-state.json
```

`--breaker-check` is **read-only** → `{"tripped","which":[...],"detail":{...}}`. If `tripped`:

```
python3 scripts/compound-v-epic-state.py --trip-breaker \
  --state docs/superpowers/execution/epics/<epic-id>/epic-state.json
```

`--trip-breaker` atomically parks the epic at `blocked_needing_human` (if not already there) and records `which`/`detail`. **Commit (§9), then go straight to the halt-page runbook (§7)** — do not start another feature. Re-run `--breaker-check` again after each attempt (§4/§5) and immediately before every model call the loop makes — the arbiter (§5) and the final-review pass (§8) — not only here at the top of the pass. Ship the honest wording: **wall-clock is checked at each attempt/model-call boundary; a single in-flight pipeline phase (a pre-flight, a dispatch batch, a review pass) may overrun its check window before the next boundary catches it.** This is not a hard real-time kill — never claim one.

### 2. Ask for the next runnable feature

```
python3 scripts/compound-v-epic-state.py --next --autonomous \
  --state docs/superpowers/execution/epics/<epic-id>/epic-state.json
```

Prints `{"feature": <feature|null>, "reason": "...", "blocked_by": [ids]}`. Unlike the checkpoint `--next`, this is **DAG-aware**: an abandoned/failed/blocked feature removes only its *transitive dependents* from the runnable set — independent pending features stay runnable and are returned **before** any terminal escalation. Routing is driven entirely by **persisted state** — a `failed` feature is routed by its *stored* `disposition` (not an in-memory intent), which is what makes retries and mid-arbitration crashes recover correctly across a re-entry. `reason` embeds a literal terminal-state token as a prefix when there is nothing runnable to hand out:

- `feature` non-null (`reason` is `"runnable"` or `"running_with_failures: runnable (...)"`) → §3. **A `failed` feature carrying a `retry_fix` disposition that is still under its retry cap is handed back here as runnable** — the driver runs it exactly like any other runnable feature (§3). This is the crash-safe retry path: the retry intent lives in the persisted `disposition`, so it survives a breaker trip or a hard crash between recording the verdict and re-running.
- `"needs_arbitration: feature <id> ..."` — a `failed` feature with **no valid recorded disposition**: either the arbiter exchange never completed (a crash mid-arbitration), or a *stale* disposition was recorded against an earlier attempt (a disposition is attempt-bound — the state script only honors it when its `attempt` equals the feature's current `attempts`, so a re-run that bumped `attempts` invalidates the old verdict and this reason re-fires). **Do NOT treat this as done or abandoned** and **do NOT blindly restart from `--prepare`** — a crash can leave a challenge already `in_progress` or `consumed`, and `--prepare`/`--classify` reject a consumed/in-progress challenge, which would deadlock. Instead run the **idempotent recovery ladder first** — read the feature's current `attempts` (`--can-retry --feature <id>` → `attempts`), then:
  ```
  python3 scripts/compound-v-epic-arbiter.py --resume-challenge \
    --state docs/superpowers/execution/epics/<epic-id>/epic-state.json \
    --feature <id> --attempt <attempts>
  ```
  Prints `{"state":"absent"|"in_progress"|"consumed", "challenge_id"?, "prompt"?, "result"?}`. Branch on `state`:
  - **`"consumed"`** — the arbiter already classified before the crash (crash-after-classify-before-record). The verdict is in the returned `result` — **no re-dispatch of Claude, no re-egress**. Record it straight from `result`: `--record-disposition --feature <id> --disposition <result.disposition> --reason "<result.reason>" [--families-agreeing <result.families_agreeing csv, omitted if empty>]`, commit (§9), then act on it (§6).
  - **`"in_progress"`** — the challenge was issued (and Claude may or may not have replied) but never aggregated. Re-dispatch the fresh adversarial Claude Task on the returned `prompt`, write its ballot file, and resume at §5 **step 3** (`--classify` with the returned `challenge_id`) — the binding makes this idempotent; skip §5 steps 1–2.
  - **`"absent"`** — no challenge exists for this attempt (the crash predated `--prepare`, or a stale disposition invalidated a prior attempt's challenge that doesn't match the current one). Run the arbiter exchange (§5) from the top, the normal first-time path.
  Only after this recovery ladder resolves does the driver treat the failure as newly-arbitrated. Then act on the disposition (§6) and loop.
- `"sample_audit_due: feature(s) <ids> ..."` — one or more `done` features were sampled for a PASS-integrity audit that has not completed (see §4). **Run the outstanding sample-audit(s) now** (§4 steps 1–4) before anything else — this reason is surfaced *before* `final_review`, and `--record-final-review passed` is **rejected while any audit is due**, so you cannot skip ahead to §8. Once every due audit clears, the next `--next --autonomous` advances normally.
- `"done: ..."` — every feature is `done`, **no sample-audit is due**, **and** `final_review.status == "passed"`. → §8/terminal (success).
- `"blocked_needing_human: ..."` — a tripped breaker, a `halt_epic` disposition, or exhausted reachable work (only blocked/failed features remain). → §7 (halt-page).
- `"running_with_failures: all features done, awaiting final_review ..."` — every feature `done`, no audit due, review not yet passed. → §8.
- `"epic needs reconcile: ..."` — a feature is stuck `running` from a prior crash. Recover the crashed run itself with `/v:resume <run-id>` (or, if unrecoverable, a full restart) exactly as the checkpoint loop's step 6 — **but do NOT use the checkpoint reconcile's terminal status write, which marks a recovered run `done` directly.** In marathon that would bypass §4's PASS-integrity sampling (the recovered run might be the invocation's first success, which MUST be sample-decided and have `--mark-sample-audit-due` persisted *before* `done`). Instead, route the outcome through the marathon handlers: a **recovered success** enters **§4's success handler** (run the sample decision, mark-due-before-done, then the audit) — it does not get a bare `--update --status done`; a **recovered failure** enters **§5** (mark `failed`, then the arbiter exchange); an unrecoverable run that can't even be classified falls back to `--status pending` (full restart on the next pass). Then loop again.

### 3. Run the feature

Identical to the checkpoint loop's step 4.1–4.2 — pick the run-id, mark it running, run the full v1.0 pipeline:

```
python3 scripts/compound-v-epic-state.py --update --feature <id> --status running \
  --run-id <run-id> --state docs/superpowers/execution/epics/<epic-id>/epic-state.json
```

(Legal only from `pending`/`failed` — the marathon transition table rejects `done`/`blocked` sources; this also increments the feature's `attempts` counter, which the arbiter step below reads.) Then the same pre-flights → writing-plans + partition → manifest → dispatch → 3-pass review tail from step 4.2, unchanged.

### 4. On success — mark done (+ durable audit obligation), then sample-audit a fraction of PASSes

**PASS-integrity sample-audit (spec Component 5).** A marathon SUCCESS is not automatically trusted — a fraction of them get a fresh adversarial re-review to catch a feature whose own 3-pass gate was satisfied by a weakened test/scorer (the reward-hack `agents/spec-reviewer.md` 2.5 guards against). Deterministic policy, stated so it is auditable, not a coin flip: **hold an in-invocation counter of successful features and sample-audit every 3rd one (the 3rd, 6th, 9th … `done` this invocation); always sample-audit the FIRST success of the invocation** (so a one-feature or short epic is never audited zero times). No RNG, no fabricated rate.

**Whether or not this success is sampled, decide it FIRST — the obligation must be on disk before `done` is committed**, so a crash between "mark done" and "run the audit" can never lose the audit. The `done` mark and (for a sampled feature) the audit obligation are recorded and committed **together**, never `done` alone:

- **Sampled** — record the obligation, then (or in the same commit as) the `done` mark:
  ```
  python3 scripts/compound-v-epic-state.py --mark-sample-audit-due --feature <id> \
    --state docs/superpowers/execution/epics/<epic-id>/epic-state.json
  ```
  ```
  python3 scripts/compound-v-epic-state.py --update --feature <id> --status done \
    --run-id <run-id> --state docs/superpowers/execution/epics/<epic-id>/epic-state.json
  ```
  Commit (§9) — **both** writes in one commit, so `done` is never persisted without its pending `sample_audit_due`. While any feature has `sample_audit_due`, `--next --autonomous` reports `"sample_audit_due: ..."` (surfaced before `final_review`) and `--record-final-review passed` is **rejected** — the obligation is enforced by the state script, not by the driver remembering it.
- **Not sampled** — just the `done` mark, then commit (§9):
  ```
  python3 scripts/compound-v-epic-state.py --update --feature <id> --status done \
    --run-id <run-id> --state docs/superpowers/execution/epics/<epic-id>/epic-state.json
  ```
  Loop back to §1.

Then run the sample-audit for a sampled feature (also the entry point when `--next --autonomous` re-surfaces a `"sample_audit_due: ..."` obligation after a crash/resume — run it here, do not skip to §8):

1. **Run the breaker gate first** (§1, reusing THIS pass's cycle-id — idempotent, so it re-evaluates wall-clock without double-counting `no_progress_cycles`) before spending the audit's model call. Tripped → `--trip-breaker` → §7. (The obligation persists across the trip — it is cleared only by step 3, so the audit is still owed when the epic later resumes.)
2. **Dispatch a FRESH `compound-v:spec-reviewer` Task** (Opus, no context from the build) for **PASS 2 QUALITY + the 2.5 reward-hack check** over just that feature's diff (`git diff` for its run), against its feature-level acceptance criteria.
3. **On APPROVED** — clear the obligation, then commit (§9):
   ```
   python3 scripts/compound-v-epic-state.py --clear-sample-audit-due --feature <id> \
     --state docs/superpowers/execution/epics/<epic-id>/epic-state.json
   ```
   Loop back to §1.
4. **On ISSUES** — the success was not real. Revert it with the SINGLE atomic command (never a clear-then-revert two-step — a crash between those two writes would leave the feature `done` with its obligation already cleared, so the bad `done` sticks silently):
   ```
   python3 scripts/compound-v-epic-state.py --record-audit-failed --feature <id> \
     --last-error "sample-audit ISSUES: <summary>" \
     --state docs/superpowers/execution/epics/<epic-id>/epic-state.json
   ```
   ONE atomic write: sets status `failed` + records `last_error` + clears `sample_audit_due` + invalidates a passed `final_review` back to pending — so there is no window where the feature is `done`-without-obligation, and a later regression can't slip through on a stale review. Commit (§9), then route the feature through the **failure path (§5)** (the arbiter exchange — the feature is already `failed`, so §5 skips its own initial `--update --status failed`).

### 5. On failure — arbiter panel before any retry decision

**First**, mark the feature `failed` — before any progress/breaker/arbiter step — so a retry legally starts from `failed`, not `running` (the transition table only allows `pending`/`failed → running`):

```
python3 scripts/compound-v-epic-state.py --update --feature <id> --status failed \
  --last-error "<one-line failure summary: scope-gate BLOCKED / reviewer ISSUES / pre-flight critical / backend exhausted>" \
  --state docs/superpowers/execution/epics/<epic-id>/epic-state.json
```

**Breaker gate before EVERY model call in this section** — the spec requires re-checking "before every arbiter / sample-audit / retry / final-review model call", not once per pass. Each numbered model call below is preceded by the breaker gate (§1, reusing THIS pass's stable cycle-id — `--record-progress-cycle` is idempotent by cycle-id, so re-calling it re-evaluates wall-clock without double-incrementing `no_progress_cycles`); a tripped breaker at any of them → `--trip-breaker` → §7, abandoning the exchange.

1. **Breaker gate**, then read the feature's current attempt count (`--can-retry --feature <id>` → `{"can_retry","attempts","cap"}`; `attempts` is the number `--prepare` needs) and issue the challenge:
   ```
   python3 scripts/compound-v-epic-arbiter.py --prepare \
     --state docs/superpowers/execution/epics/<epic-id>/epic-state.json \
     --feature <id> --attempt <attempts>
   ```
   Prints `{"challenge_id","epic_id","feature","attempt","issued_at","prompt"}` and creates `docs/superpowers/execution/epics/<epic-id>/arbiter/<id>-<attempts>/` (the evidence home for this attempt) plus a challenge record. Write the failure evidence — the reviewer's ISSUES, gate verdicts, a diff summary — into a file **inside that directory**, e.g. `.../arbiter/<id>-<attempts>/evidence.json` (`--evidence-file` below is **relative** to that directory — never pass an absolute path).

2. **Breaker gate**, then **dispatch a FRESH adversarial Claude Task (Opus, no context from the failed run)** using the `prompt` field verbatim as its instructions — it must independently classify the failure and reply with a ballot JSON matching `{"epic_id","feature","attempt","challenge_id","disposition":"retry_fix|halt_feature|halt_epic|blocked_external","reason","evidence"}` (the `epic_id`/`feature`/`attempt`/`challenge_id` must echo exactly what `--prepare` printed — a mismatched or malformed ballot is dropped, never fabricated as a vote). Write that Task's reply to a file, e.g. `.../arbiter/<id>-<attempts>/claude-ballot.json`.

3. **Breaker gate**, then aggregate — Codex is polled *inside* this call, so it is itself a model-call boundary:
   ```
   python3 scripts/compound-v-epic-arbiter.py --classify \
     --state docs/superpowers/execution/epics/<epic-id>/epic-state.json \
     --feature <id> --challenge <challenge_id> \
     --evidence-file evidence.json \
     --claude-ballot docs/superpowers/execution/epics/<epic-id>/arbiter/<id>-<attempts>/claude-ballot.json
   ```
   Prints `{"disposition","confirmed":false,"reason","evidence","ballots":[...],"families_present","families_agreeing",...}` and writes the frozen audit JSON under the same `arbiter/` directory. Codex is polled automatically inside `--classify` when `~/.claude/compound-v-capabilities.json` says it's usable (Claude-only fallback otherwise — the panel is then capped to `retry_fix`/`halt_feature`, never `halt_epic`, never a confirmed blocker); a `retry_fix` verdict past this feature's `--can-retry` cap is **already masked to `halt_feature` inside `--classify`** — the driver does not need to re-check the cap itself before recording the disposition.

Record the verdict (`--confirmed` is never passed as `true` — v2.10 hard-rejects it):

```
python3 scripts/compound-v-epic-state.py --record-disposition --feature <id> \
  --disposition <disposition> --reason "<reason>" [--families-agreeing <families_agreeing csv>] \
  --state docs/superpowers/execution/epics/<epic-id>/epic-state.json
```

**`--families-agreeing` is OMITTED entirely when the arbiter returns an empty `families_agreeing`** (all ballots dropped, or a tied/conservative default) — argparse requires a value, so passing the flag with nothing after it errors; drop the flag rather than passing a bare `--families-agreeing`. (If your dispatch harness cannot conditionally drop a flag, pass a quoted empty string `--families-agreeing ""` — the CLI parses it to an empty list, same result.) **Commit (§9) NOW — epic-state.json + the `arbiter/` directory — before the §6 breaker gate.** This commit is the durable retry intent: once the disposition is on disk, a trip/crash before the retry actually re-runs cannot lose it (§6). Recording the verdict here is also what turns a `"needs_arbitration"` `--next` reason (§2 — a `failed` feature with no disposition, i.e. a crash *before* this point) back into a normally-routed feature on the next pass.

### 6. Act on the disposition

The disposition is **already persisted** by the `--record-disposition` at the end of §5 — that write is the durable record of what to do, committed *before* the pre-retry breaker gate below. So a breaker trip or a hard crash at any point in this section loses nothing: on resume, `--next --autonomous` re-routes the feature by its *stored* disposition (a `retry_fix`-under-cap feature comes back as **runnable**; a `halt_feature`/cap-exhausted one is abandoned), never by an in-memory intent the crash would have erased.

- **`retry_fix`** — the retry re-runs a whole v1.0 pipeline (a long model-spending phase). Because the disposition is persisted, the crash-safe way to re-run is to **loop back to §1**: the top-of-pass breaker gate runs, then `--next --autonomous` hands this feature back as runnable, and §3 re-runs it. If you instead re-dispatch immediately within this same live pass (an optimization, not required), **run the breaker gate (§1, this pass's cycle-id) once more BEFORE re-dispatching** — a retry must not start after a breaker has already tripped (tripped → `--trip-breaker` → §7) — then re-check `--can-retry --feature <id>` (defense-in-depth; `--classify` already capped it): if `can_retry`, `--update --status running --run-id <run-id>` (legal from `failed`) and re-run the v1.0 pipeline (§3); if not, treat it as `halt_feature` (it should already have arrived as `halt_feature` from §5). Either path is safe — the persisted disposition, not the choice of path, is what survives a crash.
- **`halt_feature`** — abandon this feature. No further status change needed — it is already `failed`, disposition recorded — `--next --autonomous` on the next pass routes around it: independents keep running, only its transitive dependents block. Continue the loop (§1).
- **`blocked_external`** — isolate it in the blocker ledger (always `confirmed:false` in v2.10 — never pass `--blocker-confirmed true`):
  ```
  python3 scripts/compound-v-epic-state.py --update --feature <id> --status blocked \
    --blocker-reason "<reason>" --families-agreeing <families_agreeing csv> \
    --evidence "<the missing external fact, if known>" \
    --state docs/superpowers/execution/epics/<epic-id>/epic-state.json
  ```
  Commit, then continue the loop (§1) — a suspected blocker isolates its dependents but never halts the whole epic by itself; the epic only resolves to `blocked_needing_human` once no other reachable work remains.
- **`halt_epic`** — already recorded (§5); no further action here. The **next** `--next --autonomous` call reports `blocked_needing_human: halt_epic disposition on ...` regardless of any other runnable work — the one disposition that intentionally halts the whole epic rather than letting the DAG route around it (a panel-level "stop everything" verdict, not a per-feature one). → §7.

### 7. Halt-page runbook (whole-epic block only)

Page **only** when the epic itself is blocked — `blocked_needing_human` (tripped breaker or `halt_epic`) or exhausted reachable work. A single `blocked`/abandoned **feature** notice does **not** page here — it batches into the end-of-run report (§8) alongside a successful `done`. Commit first (§9) — the page must describe a state that is actually on disk in git, not one still sitting uncommitted in the worktree. The runbook carries, verbatim, every field the spec requires:

- **The feature + its blocked dependents** — `--next --autonomous`'s `blocked_by` list, plus which feature(s) are `failed`/`blocked` (`--summary`).
- **Which acceptance criterion failed + the gate verdicts + a failing-diff summary** — from that feature's own 3-pass review output and its `last_error`.
- **Every panel ballot + reason + resolved family + why it aggregated** — read straight from the persisted `.../arbiter/<id>-<n>.json` audit (`ballots`, `families_present`, `families_agreeing`, the aggregation `reason`) — never re-derived or paraphrased into something the audit doesn't say.
- **Breaker state (n/cap)** — the `--breaker-check`/`--trip-breaker` `detail` object verbatim (counts + hours only — never a fabricated cost or token number).
- **Copy-paste resume commands (human-gated — this is the un-trip path, not an auto-revive).** The epic is parked at `blocked_needing_human`; a human resolves the root cause, clears the latch, and RE-RUNS `/v:epic <epic-id>` to **resume the marathon** (the loop picks up from `epic-state.json` per §0). Give the exact commands for the specific block:
  - **A tripped breaker** — `python3 scripts/compound-v-epic-state.py --clear-breaker --state <epic-state.json>` clears the `blocked_needing_human` latch and re-arms the tripped caps so the next `/v:epic` resumes the marathon. Add `--reset-wall-clock` if the wall-clock breaker tripped (re-stamps `autonomy.started_at` to now, so the hours budget starts fresh), and/or `--set-max-total-attempts <N>` if the attempt breaker tripped (raises the cap so there's headroom to continue). Without those re-arm flags the same cap trips again on the first pass.
  - **A `halt_epic` disposition** — `python3 scripts/compound-v-epic-state.py --clear-disposition --feature <id> --state <epic-state.json>` clears the sticky `halt_epic` verdict on that feature (which `--next --autonomous` treats as a whole-epic stop) so the DAG routes normally again; then `--clear-breaker` if the status latch is also set, and re-run `/v:epic <epic-id>`.
  - **A recoverable incomplete run** (a feature caught mid-pipeline) — resume THAT run in place with `/v:resume <run-id>` using the feature's **recorded `run_id`** (from `--summary`), then mark it `--status done`. This is distinct from abandoning + retrying from scratch: a fresh `--update --status pending --feature <id> --state <epic-state.json>` throws away the half-built run and restarts it from the spec — only do that when `/v:resume` can't recover it (or `run_id` is null).
  - Then **re-run `/v:epic <epic-id>`** — re-entrant, resumes the marathon from the persisted state (§0 re-confirms `stance=="marathon"`). This is **human-gated, never automatic** — nothing un-trips or re-runs on its own in v2.10.
- **Paths** — the arbiter JSON(s), the epic run dir, and `git diff <autonomy.start_sha>..HEAD` (the epic's start SHA captured at `--init`; falls back to the branch name if an older marathon state predates `start_sha`) for the accumulated diff.

Counts only, never fabricated cost/token metrics. Then stop this invocation.

### 8. Before terminal `done` — final cross-feature re-verification

When `--next --autonomous` reports `"running_with_failures: all features done, awaiting final_review ..."`: run the breaker gate (§1, this pass's cycle-id) before spending this model call — tripped → `--trip-breaker` → §7. Otherwise dispatch `compound-v:spec-reviewer` for **PASS 3 INTEGRATION only**, over the **whole accumulated diff** on the branch since the epic started — `git diff <autonomy.start_sha>..HEAD` (the SHA captured at `--init`; the branch name if an older state predates `start_sha`) — against the epic's acceptance criteria (same in spirit as the checkpoint loop's step 5 integration review). Record the verdict:

```
python3 scripts/compound-v-epic-state.py --record-final-review --status passed \
  --state docs/superpowers/execution/epics/<epic-id>/epic-state.json
```

(or `--status failed` on ISSUES — `passed` is rejected unless every feature is currently `done` **and no `sample_audit_due` obligation is outstanding**; if `--next --autonomous` is still reporting `"sample_audit_due: ..."` you must clear those audits (§4) before this call will accept `passed`). Commit (§9), then loop back to §2: a `passed` review makes the next `--next --autonomous` report `"done: ..."` — print `--summary`/`--stats`, the per-feature run-ids, and hand off to `superpowers:finishing-a-development-branch` (same as the checkpoint loop's step 5, minus the separate review step already folded in here). A `failed` review is **not** silently retried in a tight loop — surface the spec-reviewer's ISSUES immediately. Since no feature is `pending`/`running` to route work to, an unaddressed failed final review shows up at §1 as a non-advancing pass (`no_progress_cycles` increments because `done` didn't grow) — either fix the integration issue and re-run the review within this invocation, or let the no-progress breaker trip on its own boundary and hand off to §7. Never re-run the identical failing review without addressing what it found.

### 9. Commit points (two-command discipline — check each exit, never `&&`)

Commit after **every** one of these, and once more immediately before any terminal handoff (§7/§8) if anything is still pending — the v2.6.4 rule: nothing under `docs/superpowers/execution/**` may be write-without-commit, or a `finishing-a-development-branch` worktree cleanup can silently delete it.

```
git add docs/superpowers/execution/epics/<epic-id>/epic-state.json \
  docs/superpowers/execution/epics/<epic-id>/arbiter/
```
```
git commit -m "chore(v-epic): marathon <epic-id> <feature-id> -> <what happened>"
```

(Omit the `arbiter/` path when nothing was written there — e.g. a bare `done` mark.) Trigger points: a feature reaching `done` — **committed together with its `--mark-sample-audit-due` when sampled, so `done` is never on disk without the obligation** (§4); a `--clear-sample-audit-due` on a passed audit (§4); a `--record-audit-failed` reverting a failed sample-audit (§4); every `--record-disposition` + its accompanying `--update` (§5/§6 — `retry_fix`/`halt_feature`/`blocked_external`/`halt_epic`); a `--record-disposition` recovered from a `consumed` `--resume-challenge` (§2 `needs_arbitration`); every `--trip-breaker` (§1/§5/§7); every `--record-final-review` (§8); and once more, belt-and-suspenders, right before the halt-page (§7) or the terminal `done` report (§8).

### The honest v2.10 boundary

- **In-session (automatic):** the marathon loop continues past a soft per-feature error to the next runnable feature within this live `/v:epic` invocation; a crashed feature is caught by the existing `running` → reconcile path (§2) on the next pass.
- **Hard death (human, not automatic):** quota exhaustion, a closed terminal, a crashed machine — a **human re-invokes `/v:epic <epic-id>`**, which is re-entrant and resumes from `epic-state.json` (per stance-binding §0). **There is no automatic resurrection in v2.10** — no watcher revives this epic while you're away. That is v2.11 (deferred, its own spec).
- No fabricated cost/token metrics anywhere in this loop — breakers and reports bound counts and wall-clock hours only.

---

## Honesty boundary (state it to the user)

- **Epic mode is autonomous *chaining*, not "guess a product from one sentence."** Each feature still needs a **real spec** — the per-feature pre-flights and partition do the heavy lifting; the epic layer only orders and chains them.
- **Large epics run sequentially, feature-by-feature.** Parallelism is *within* a feature (the v1.0 batch dispatch); features advance one runnable-front at a time in topological order. Independent features at the same depth still run one after another, not concurrently — there is no cross-feature parallel dispatch in v1.1.
- **Quality is bounded by per-feature spec + partition quality.** A weak feature decomposition (overlapping features, missed deps) produces a weak epic. The state spine guarantees *order and resumability*, not that your decomposition was right.
- **Marathon (v2.10, opt-in) is bounded autonomy, not "survives while you sleep."** It chews the whole runnable feature DAG in one invocation and continues past a soft per-feature failure automatically — but only *within that one live invocation*. A hard death (quota, closed terminal, crashed machine) needs a **human** to re-invoke `/v:epic <epic-id>`; there is **no automatic resurrection in v2.10** (that is the deferred v2.11 auto-watcher). The default is still `checkpoint` — marathon is opt-in per epic, chosen at `--init` time, never silently promoted from an existing checkpoint epic.

## Safety

- **One branch, accumulating.** Every feature's diff lands on the current branch in dependency order; the epic does not branch per feature. Only `finishing-a-development-branch` decides the final merge/PR.
- **The epic-state is the source of truth for "where is this epic."** Mutate it only through `compound-v-epic-state.py --update` (or, in marathon, the additional `--record-*`/`--breaker-check`/`--trip-breaker` commands documented above); never hand-edit. `--next` (and `--next --autonomous`) are read-only and never an error (a `null` feature with a stop reason is information, not failure).
- **Resumable, no daemon.** There is no background process. `/v:epic` is re-entrant: re-running it continues the epic from `epic-state.json`.
- **Marathon commits after every attempt/disposition, not just at a checkpoint.** See "Autonomous marathon loop" §9 — an unattended run must never leave `docs/superpowers/execution/epics/<epic-id>/**` writes uncommitted.
- Do **not** print fabricated cost or token metrics (anti-ruflo) — marathon's breakers report counts and wall-clock hours only, in both stances.
