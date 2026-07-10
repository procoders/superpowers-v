---
description: Materialize a Compound V execution manifest from a plan. Reads a Compound-V-ready plan path, applies the routing policy, and writes manifest.yaml plus an initial state.json into docs/superpowers/execution/<run-id>/ — without dispatching. Use this to inspect or edit the manifest before /v:dispatch.
---

You are running **`/v:orchestrate`** — the **materialize** step of Compound V. You turn a verified plan into the machine-readable contract the dispatcher runs: a `manifest.yaml` plus an initial `state.json` in a fresh run directory. This command **does not dispatch** — it produces the manifest and stops, so the user (or `/v:dispatch`) can inspect or edit it first.

The plan path is `{{args}}`.

The manifest schema and rules are defined in [`skills/compound-v/execution-manifest.md`](../skills/compound-v/execution-manifest.md); the routing decisions come from [`skills/compound-v/routing-policy.md`](../skills/compound-v/routing-policy.md); the run-dir layout and `state.json` shape come from [`skills/compound-v/state-machine.md`](../skills/compound-v/state-machine.md). Read those — they are the authority; this command is the procedure.

## Steps

1. **Resolve the plan.** If `{{args}}` is empty, list the plans in `docs/superpowers/plans/` and ask the user which to materialize. If the named plan path does not exist, stop and say so.

2. **Read the plan and its pre-flight audits.** Extract:
   - the feature title and **feature-level Acceptance Criteria** (from the spec the plan targets),
   - the verified **Partition Map** (the disjoint write-paths per task),
   - the three audit paths (`docs/superpowers/{archaeology,expert,library-audit}/<topic>.md`).
   If the plan has no Partition Map, stop — this plan is not Compound-V-ready; route it through Phase 2 (`skills/compound-v/phase-2-disjoint-partitioning.md`) first.

3. **Choose the run-id.** Convention: `YYYY-MM-DD-<slug>` (the slug from the plan/feature). The run dir is `docs/superpowers/execution/<run-id>/`. Create it (and `jobs/` + `results/` subdirs).

4. **Apply the routing policy** ([`routing-policy.md`](../skills/compound-v/routing-policy.md)) to each partition entry. For every job set `backend · model · isolation · run` from its `type`, honoring the active stance in `.claude/compound-v.json` (Balanced default; **Claude-only** when Codex is absent). Consult `docs/superpowers/memory/routing-lessons.md` — a recorded lesson overrides the table default for that pattern.

5. **Materialize `manifest.yaml`** in the run dir per the schema in [`execution-manifest.md`](../skills/compound-v/execution-manifest.md): top-level `run_id`, `feature`, `spec_path`, `plan_path`, `audits`, `acceptance_criteria`, `routing_stance`, `max_parallel`, and `jobs[]` with `id · title · type · backend · model · isolation · run · depends_on · write_allowed · read_allowed · acceptance`. Shared/contract/schema/version files go in a single serial `type: shared_foundation` Task 0; every other job `depends_on` it. `read_allowed` need not re-list Task 0 outputs or the audits (auto-included). The worked shape is [`examples/manifest.example.yaml`](../examples/manifest.example.yaml).

6. **Write the initial `state.json`** per the shape in [`state-machine.md`](../skills/compound-v/state-machine.md): `phase: PARTITION_VERIFIED` (the manifest exists and the partition is the verified one from the plan), `updated_at`, and a `jobs` map with every job `status: pending`, its `isolation`, `worktree: null`, `session_id: null`.

7. **Validate before declaring done.** Run the deterministic manifest validator:
   ```
   python3 scripts/compound-v-validate-manifest.py docs/superpowers/execution/<run-id>/manifest.yaml
   ```
   It enforces the invariants (disjoint `write_allowed`, `codex ⇒ worktree`, `reviewers ⇒ opus`, shared-in-Task-0). If it exits non-zero, **fix the manifest** and re-run — do not hand a manifest the validator rejects to dispatch.

8. **Commit the run directory.** `docs/superpowers/execution/<run-id>/{manifest.yaml,state.json}` are new files on disk, not yet in git — a plain **write** is not durable. Stage and commit them now:
   ```bash
   git add docs/superpowers/execution/<run-id>/manifest.yaml docs/superpowers/execution/<run-id>/state.json
   git commit -m "chore(v-orchestrate): materialize run <run-id>"
   ```
   This is not optional. If this run is happening inside a git worktree, an *uncommitted* run directory is silently deleted by `git worktree remove` — the cleanup step in `superpowers:finishing-a-development-branch` — the very moment the branch is merged or discarded, taking Compound V's own audit trail with it. See [`state-machine.md`](../skills/compound-v/state-machine.md)'s note on this.

9. **Report.** Print the run-id, the run-dir path, the job count by backend/model, and the next step: `/v:dispatch <run-id>` to execute, or edit `manifest.yaml` first. Point the user at [`/v:status {{args}}`](v-status.md) to inspect.

## Safety

- This command **materializes only** — it never dispatches, never writes outside the run dir, never merges.
- `backend` and `model` are **execution-layer data** — they live in the manifest, never in any frontmatter.
- Do **not** invent a partition: if the plan lacks a verified Partition Map, return it to planning rather than guessing.
- Do **not** print fabricated cost or token metrics (anti-ruflo).
