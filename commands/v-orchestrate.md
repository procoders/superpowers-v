---
description: Materialize a Compound V execution manifest from a plan (or an accepted fast-path pre-eval). Applies the routing policy and writes manifest.yaml plus an initial state.json into docs/superpowers/execution/<run-id>/ — without dispatching. Binds every pre-eval-backed run. Use this to inspect or edit the manifest before /v:dispatch.
---

You are running **`/v:orchestrate`** — the **materialize** step of Compound V. You turn a verified plan into the machine-readable contract the dispatcher runs: a `manifest.yaml` plus an initial `state.json` in a fresh run directory. This command **does not dispatch** — it produces the manifest and stops, so the user (or `/v:dispatch`) can inspect or edit it first.

The argument is `{{args}}`. It is normally a **plan path**. It may instead be an **accepted fast-path pre-eval** — a `pre_eval_id` (`YYYY-MM-DDThhmmssZ-<slug>-<nonce>`) or a path to `docs/superpowers/pre-eval/<pre_eval_id>.json` whose `decision` is `FASTPATH_ELIGIBLE` — in which case take **Step 0** and stop.

The manifest schema and rules are defined in [`skills/compound-v/execution-manifest.md`](../skills/compound-v/execution-manifest.md); the routing decisions come from [`skills/compound-v/routing-policy.md`](../skills/compound-v/routing-policy.md); the run-dir layout and `state.json` shape come from [`skills/compound-v/state-machine.md`](../skills/compound-v/state-machine.md). Read those — they are the authority; this command is the procedure.

## Steps

0a. **Obtain a triage record if there is none (spec §A3).** Every run this command materializes must
   trace to a committed pre-eval record — `compound-v-validate-manifest.py` requires a well-formed
   `triage` block, and [`/v:dispatch`](v-dispatch.md) passes `--require-triage` in every mode, so a
   run without one cannot be dispatched. **Before anything else**, look for a record covering this
   work:

   ```bash
   ls docs/superpowers/pre-eval/*.json 2>/dev/null | tail -20
   ```

   A record covers this work when its `localization.resolved_paths` (or `declared_paths`) are the
   files this plan touches. If `{{args}}` already *is* a `pre_eval_id` or a record path, that is the
   record — skip to Step 0.

   One may already exist without anyone having asked for it: since v3.4 the `UserPromptSubmit`
   hook (`hooks/triage-prompt-nudge.sh`) runs the same scorer `/v:triage` step T2 runs, once per
   session, so the record for this work may be sitting there **uncommitted**. If so, commit it
   (`/v:triage` step T3) and use it rather than minting a second.

   **If none exists, run [`/v:triage <the request>`](v-triage.md) now** and use the record it writes
   and commits. Do not hand-write a record, do not invent a `pre_eval_id`, and do not proceed
   without one: those two producers are the only ones, and a reconstructed audit trail is the
   fabricated-evidence pattern rather than a repair. Carry the resulting `pre_eval_id` into Step 6's
   `state.json`, Step 8b's `bind`, and the manifest's `triage` block.

   **Copy the record's `flavor` into the manifest's `triage` block verbatim when it has one.** The
   only value is `scoped_plus` — a SCOPED-sized change on a sensitive path — and it is a routing
   *consequence*, not a routing input: it tells this command to give the run a `type: review` job
   with `tier: deep` and `backend: claude` (`/v:dispatch` step 2 refuses the manifest without one)
   and it tells step 8 to run the mandatory cross-model second opinion. A record with no `flavor`
   gets no `flavor` key; never add one to buy a deeper review the scorer did not ask for, and
   never drop one to skip a review it did.

   Triage may come back **DIRECT**. A DIRECT change has no manifest, no run directory and no
   worktree, so **this command is not its next step**. Implement it in place, run the test floor,
   and commit it as an ordinary commit together with its record. Only a record that was SCOPED or
   FULL to begin with arrives here.

0. **Fast-path branch (accepted pre-eval → committed single-job run).** If `{{args}}` resolves to an accepted `FASTPATH_ELIGIBLE` pre-eval record (a `pre_eval_id`, or a `docs/superpowers/pre-eval/<pre_eval_id>.json` path with `decision: FASTPATH_ELIGIBLE`), do **not** run the plan-based flow below — the fast path has no full plan and no three audits. Instead delegate to the deterministic materializer, which runs the authoritative **Phase-M** lifecycle (mint a deterministic run-id from `pre_eval_id` → copy the pinned taxonomy snapshot into the run → write spec/plan **stubs**, block-YAML audit **skip-records**, the single-job `fast_path` manifest with the review **declaration** only, and the captured implementer prompt → **commit all artifacts except `state.json`** → **append + commit the `bind` event** → **commit `state.json` at `FASTPATH_DISPATCHED` LAST**). It also runs the validator in `--mode pre-dispatch` as an in-code gate before binding, so a manifest the validator would reject never reaches dispatch.
   ```bash
   python3 scripts/compound-v-fastpath-materialize.py materialize \
     --repo . --pre-eval-id <pre_eval_id> [--prompt-file <captured-implementer-prompt>]
   ```
   The materializer is **idempotent + crash-consistent**: a committed `state.json` at `FASTPATH_DISPATCHED` ⇒ the `bind` is already durable ⇒ the run is complete (re-running is a no-op); a run interrupted before `state.json` is rebuilt deterministically (same `pre_eval_id` → same run-id; an existing child is discovered before another is minted). It **fails closed** — a tampered record (its `localization.resolved_paths[0]` disagreeing with the committed localization artifact, a non-`FASTPATH_ELIGIBLE` decision, or a taxonomy snapshot whose bytes don't content-address to the record's `taxonomy_digest`) is **rejected before any write or commit**. Report the run-id and the next step (`/v:dispatch <run-id>`), then **stop** — Steps 1-9 below do not apply.

1. **Resolve the plan.** If `{{args}}` is empty, list the plans in `docs/superpowers/plans/` and ask the user which to materialize. If the named plan path does not exist, stop and say so.

2. **Read the plan and its pre-flight audits.** Extract:
   - the feature title and **feature-level Acceptance Criteria** (from the spec the plan targets),
   - the verified **Partition Map** (the disjoint write-paths per task),
   - the three audit paths (`docs/superpowers/{archaeology,expert,library-audit}/<topic>.md`).
   If the plan has no Partition Map, stop — this plan is not Compound-V-ready; route it through Phase 2 (`skills/compound-v/phase-2-disjoint-partitioning.md`) first.

3. **Choose the run-id.** Convention: `YYYY-MM-DD-<slug>` (the slug from the plan/feature). The run dir is `docs/superpowers/execution/<run-id>/`. Create it (and `jobs/` + `results/` subdirs).

4. **Apply the routing policy** ([`routing-policy.md`](../skills/compound-v/routing-policy.md)) to each partition entry. For every job set `backend · model · isolation · run` from its `type`, honoring the active stance in `.claude/compound-v.json` (Balanced default; **Claude-only** when Codex is absent). Consult `docs/superpowers/memory/routing-lessons.md` — a recorded lesson overrides the table default for that pattern.

   **Effort follows the job's kind, not its tier alone** ([`routing-policy.md`](../skills/compound-v/routing-policy.md) § Effort by job kind). New code and design decisions get `deep` · `high`. **A fix job minted from a review finding carries `effort: medium`** — the finding already names the file, the defect and the bar, so the thinking is done and written down; high effort there re-derives a conclusion the job was handed. A reviewer job is `high` on its first pass over a diff and `medium` on a re-pass over the same one.

5. **Materialize `manifest.yaml`** in the run dir per the schema in [`execution-manifest.md`](../skills/compound-v/execution-manifest.md): top-level `run_id`, `feature`, `spec_path`, `plan_path`, `audits`, `acceptance_criteria`, `routing_stance`, `max_parallel`, and `jobs[]` with `id · title · type · backend · model · isolation · run · depends_on · write_allowed · read_allowed · acceptance`. Shared/contract/schema/version files go in a single serial `type: shared_foundation` Task 0; every other job `depends_on` it. `read_allowed` need not re-list Task 0 outputs or the audits (auto-included). The worked shape is [`examples/manifest.example.yaml`](../examples/manifest.example.yaml).

6. **Write the initial `state.json`** per the shape in [`state-machine.md`](../skills/compound-v/state-machine.md): `phase: PARTITION_VERIFIED` (the manifest exists and the partition is the verified one from the plan), `updated_at`, and a `jobs` map with every job `status: pending`, its `isolation`, `worktree: null`, `session_id: null`. **If this run is pre-eval-backed** — the invocation carried a `--pre-eval-id`, or the plan traces to a pre-eval whose offer was declined and is now becoming a normal run — set `pre_eval_id: <the id>` (else `null`). This is what lets a declined pre-eval later be re-joined to its triage record (CR3-2).

7. **Validate before declaring done.** Run the deterministic manifest validator:
   ```
   python3 scripts/compound-v-validate-manifest.py docs/superpowers/execution/<run-id>/manifest.yaml
   ```
   It enforces the invariants (disjoint `write_allowed`, `codex ⇒ worktree`, `reviewers ⇒ opus`, shared-in-Task-0). If it exits non-zero, **fix the manifest** and re-run — do not hand a manifest the validator rejects to dispatch. A plan-based manifest carries **no** `fast_path` block, so it is validated mode-lessly (legacy). The **only** `fast_path` manifest this command produces comes from the Step 0 materializer, which validates it with `--mode pre-dispatch` itself — never hand-materialize a `fast_path` manifest here without that mode (a mode-less `fast_path` manifest is fail-closed rejected; CR5-1).

8. **Commit the run directory.** `docs/superpowers/execution/<run-id>/{manifest.yaml,state.json}` are new files on disk, not yet in git — a plain **write** is not durable. Stage and commit them now, along with what the pre-flight audits appended:
   ```bash
   git add docs/superpowers/execution/<run-id>/manifest.yaml docs/superpowers/execution/<run-id>/state.json
   git add docs/superpowers/archaeology/_knowledge-base docs/superpowers/expert/_knowledge-base docs/superpowers/library-audit/_knowledge-base
   git add <each path in the pre-flight result's kb_files, if any>
   git commit -m "chore(v-orchestrate): materialize run <run-id>"
   ```
   This is not optional. If this run is happening inside a git worktree, an *uncommitted* run directory is silently deleted by `git worktree remove` — the cleanup step in `superpowers:finishing-a-development-branch` — the very moment the branch is merged or discarded, taking Compound V's own audit trail with it. See [`state-machine.md`](../skills/compound-v/state-machine.md)'s note on this.

   **Stage the three knowledge-base directories too, and name the exact files from `kb_files`.** 1C appends to `docs/superpowers/library-audit/_knowledge-base/<topic>.md` (its Step 7); 1A may do the same under `docs/superpowers/archaeology/_knowledge-base/<topic>.md`, and 1B under `docs/superpowers/expert/_knowledge-base/<topic>.md`. Those are already-tracked files after their first run, so the scope gate's untracked-file protection does not cover a later modification — it gets charged to whatever direct-mode job runs next (finding 100: it had to be stashed mid-run on 2026-09-03). Read the pre-flight result's `kb_files` (Step 2's audits came from that same pre-flight run) and `git add` each path it names, in addition to the three directory globs above — the globs catch a KB write this run-id has not seen before; `kb_files` catches the modification to one it has.

8b. **Bind every pre-eval-backed run (CR3-2).** If Step 6 set a `pre_eval_id`, append **and commit** the `bind` triage event **now** (after the run dir is committed, so the run it points at is durable), via the two-command discipline (no `&&`, each exit code checked):
   ```bash
   python3 scripts/compound-v-triage-outcomes.py bind --pre-eval-id <pre_eval_id> --run-id <run-id>
   git add docs/superpowers/memory/triage-outcomes.jsonl
   git commit -m "chore(v-orchestrate): bind run <run-id> to <pre_eval_id>"
   ```
   This binds **every** pre-eval-backed run — fast-path (handled inside the Step 0 materializer) **or** full-pipeline (here) — so a declined pre-eval that later became a normal run is still joined to its `predicted` triage record. The `bind` is idempotent: skip the append if a `bind` for this `(pre_eval_id, run-id)` already exists. Runs with `pre_eval_id: null` skip this step.

9. **Report.** Print the run-id, the run-dir path, the job count by backend/model, and the next step: `/v:dispatch <run-id>` to execute, or edit `manifest.yaml` first. Point the user at [`/v:status {{args}}`](v-status.md) to inspect.

## Safety

- This command **materializes only** — it never dispatches, never writes outside the run dir, never merges.
- `backend` and `model` are **execution-layer data** — they live in the manifest, never in any frontmatter.
- Do **not** invent a partition: if the plan lacks a verified Partition Map, return it to planning rather than guessing.
- Do **not** print fabricated cost or token metrics (anti-ruflo).
