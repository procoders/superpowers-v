---
description: Drive an EPIC — chain several features into one autonomous, resumable, dependency-ordered build on a single branch. Each feature runs through the FULL v1.0 pipeline (spec → 3 pre-flights → writing-plans + partition → manifest → dispatch → 3-pass review) in topological order, accumulating onto the current branch. Resume-aware via epic-state.json; ends with a cross-feature integration review and finishing-a-development-branch.
---

You are running **`/v:epic`** — the **epic driver** of Compound V. A v1.0 run executes ONE plan (one feature). An **epic** chains several: an ordered set of features, each run through the full v1.0 pipeline, in dependency order, accumulating onto **one branch**. "Build a whole app." It is the same discipline one level up — resumable, topological, no daemon.

The epic spec is `{{args}}` (a path to an epic brief, or a described feature set).

The epic model, run-dir layout, the final integration review, and the honesty boundary are defined in [`skills/compound-v/epic-mode.md`](../skills/compound-v/epic-mode.md) — read it; it is the authority. The deterministic state spine is [`scripts/compound-v-epic-state.py`](../scripts/compound-v-epic-state.py) (one level up from [`state-machine.md`](../skills/compound-v/state-machine.md)). Each per-feature run is a normal v1.0 run materialized per [`execution-manifest.md`](../skills/compound-v/execution-manifest.md).

## Steps

1. **Resolve the epic spec.** From `{{args}}`: if it is a path to an epic brief, read it; if it is a described feature set, work from the description. If `{{args}}` is empty, ask the user for the epic brief (or list existing epics under `docs/superpowers/execution/epics/` to resume one). Pick an `<epic-id>` (convention: `YYYY-MM-DD-<slug>`) and an epic **title**, and capture the epic's **acceptance criteria** (used by the final integration review).

2. **Derive the feature list.** Decompose the product into independent-ish **features** — each `{id, title, depends_on}`. Split by feature slice (a vertical capability), not by layer; capture cross-feature dependencies in `depends_on` (e.g. `api` depends_on `auth`). Aim for features that are each a *real* v1.0 unit of work — a spec the pre-flights and partition can chew on. This decomposition quality bounds the whole epic (see the honesty boundary).

3. **Resume-aware init.** The epic lives at `docs/superpowers/execution/epics/<epic-id>/epic-state.json`.
   - **If it already exists → CONTINUE from it.** Do not re-init; read it and go to the loop. (Re-running `/v:epic` after a fix is the resume path.)
   - **Else** write the feature list to `docs/superpowers/execution/epics/<epic-id>/features.json` (a JSON array of `{id, title, depends_on}`) and initialize:
     ```
     python3 scripts/compound-v-epic-state.py --init \
       --features docs/superpowers/execution/epics/<epic-id>/features.json \
       --epic-id <epic-id> --title "<title>" \
       --out docs/superpowers/execution/epics/<epic-id>/epic-state.json
     ```
     It validates ids/refs/cycles and writes `epic-state.json` with every feature `pending`. A non-zero exit (bad id, dangling ref, cycle, duplicate) ⇒ fix the feature list and re-init — do not hand-edit the state.

4. **The loop.** Repeat until no feature is runnable:
   - **Ask for the next runnable feature:**
     ```
     python3 scripts/compound-v-epic-state.py --next \
       --state docs/superpowers/execution/epics/<epic-id>/epic-state.json
     ```
     It prints `{"feature": <feature|null>, "reason": "runnable|epic complete|epic blocked: …|epic needs reconcile: …"}`. A feature is runnable when it is `pending` and **all** its `depends_on` are `done`, returned in topological order. The loop is **fail-fast**: any `failed` feature halts the whole epic (even independent pending features wait) until reconciled — `--next` will not route around a failure.
   - **If `feature` is non-null** (`reason == "runnable"`):
     1. **Mark it running:** `compound-v-epic-state.py --update --feature <id> --status running --state <epic-state.json>`.
     2. **Run that ONE feature through the full v1.0 pipeline on the current branch** — exactly as a standalone feature, reusing everything:
        - `superpowers:brainstorming` → a real per-feature **spec** (with feature-level Acceptance Criteria). Epic mode does not skip the spec — see the honesty boundary.
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
   - **If `feature` is null**, branch on `reason` (step 5/6).

5. **Epic complete** (`reason == "epic complete"`). All features are `done`. Run a **final cross-feature integration review**: the *whole accumulated diff* on the branch against the **epic's** acceptance criteria — not the per-feature ACs (those already passed in each feature's own review), but the cross-feature contracts: do the features compose, do shared boundaries line up, is the product coherent end-to-end. On PASS, hand to `superpowers:finishing-a-development-branch` (merge / PR / cleanup options). On ISSUES, surface them and stay resumable.

6. **Epic blocked** (`reason` starts with `epic blocked` — a feature `failed` or an unmet dependency). **Stop and surface it.** Print `compound-v-epic-state.py --summary --state <epic-state.json>` so the user sees exactly which feature failed and what it blocks. The epic stays **resumable**: after the user fixes the failed feature (or its spec/partition), retry it (`--update --feature <id> --status pending`) and re-run `/v:epic <epic-id>` (or the same brief) — step 3 detects the existing `epic-state.json` and continues; only `pending` features run, the `done` ones are skipped.

   **Epic needs reconcile** (`reason` starts with `epic needs reconcile` — a feature is still `running`). Because epic mode is **sequential**, `--next` is only ever called between features, so a `running` feature on resume means that feature's run **crashed mid-pipeline**. Do not route around it. **Reconcile before continuing:** inspect that feature's run dir / `state.json` (via its `run_id`); if the work is incomplete or unverified, mark it **`--status pending`** to retry from scratch, or **`--status failed`** to abandon and stop. Never leave a feature `running` across a resume — the epic will not advance until the stale run is reconciled.

7. **Report.** Print the epic summary (`--summary`), the per-feature run-ids, and the next step: the integration review + `finishing-a-development-branch` on complete, or the blocking feature + the resume hint on blocked.

## Honesty boundary (state it to the user)

- **Epic mode is autonomous *chaining*, not "guess a product from one sentence."** Each feature still needs a **real spec** — the per-feature pre-flights and partition do the heavy lifting; the epic layer only orders and chains them.
- **Large epics run sequentially, feature-by-feature.** Parallelism is *within* a feature (the v1.0 batch dispatch); features advance one runnable-front at a time in topological order. Independent features at the same depth still run one after another, not concurrently — there is no cross-feature parallel dispatch in v1.1.
- **Quality is bounded by per-feature spec + partition quality.** A weak feature decomposition (overlapping features, missed deps) produces a weak epic. The state spine guarantees *order and resumability*, not that your decomposition was right.

## Safety

- **One branch, accumulating.** Every feature's diff lands on the current branch in dependency order; the epic does not branch per feature. Only `finishing-a-development-branch` decides the final merge/PR.
- **The epic-state is the source of truth for "where is this epic."** Mutate it only through `compound-v-epic-state.py --update`; never hand-edit. `--next` is read-only and never an error (a `null` feature with a stop reason is information, not failure).
- **Resumable, no daemon.** There is no background process. `/v:epic` is re-entrant: re-running it continues the epic from `epic-state.json`.
- Do **not** print fabricated cost or token metrics (anti-ruflo).
