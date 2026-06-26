---
description: Render the state of a Compound V orchestrator run — pipeline phase plus a per-job status table — by reading state.json from the run directory. Optional run-id argument; without one, list runs and pick the most recent.
---

You are about to render the **state of a Compound V orchestrator run**. This is read-only: it inspects `state.json`, it does not dispatch, collect, or merge anything.

The run-id (optional) is `{{args}}`.

## Steps

1. **Locate the run.**
   - If `{{args}}` names a run-id, the run dir is `docs/superpowers/execution/{{args}}/`.
   - If `{{args}}` is empty, list the subdirectories of `docs/superpowers/execution/`. If there is exactly one, use it. If there are several, show them (newest first by run-id date prefix) and render the most recent, noting the others.
   - If `docs/superpowers/execution/` is absent or empty, tell the user there are no orchestrator runs yet and stop.

2. **Read `state.json`** from the run dir (and `manifest.yaml` for job titles). If `state.json` is missing or unreadable, report that the run dir exists but has no state yet, and stop.

3. **Render the run-level phase.** Show the `phase` (one of `SPEC_READY → PREFLIGHT_DONE → PARTITION_VERIFIED → DISPATCHED → COLLECTED → REVIEWED → MERGED`, or terminal `BLOCKED`) and `updated_at`. The phase meanings are defined in [`skills/compound-v/state-machine.md`](../skills/compound-v/state-machine.md).

4. **Render the per-job table.** One row per job from `state.json.jobs`, with `manifest.yaml` supplying the title:

   | Job | Title | Status | Isolation | Worktree |
   |---|---|---|---|---|
   | task-0-schema | DB schema + types | done | direct | — |
   | task-1-editor-ui | Editor UI slice | running | worktree | $TMPDIR/… |

   Per-job `status` is one of `{pending | running | done | blocked | failed}` (see state-machine.md). Show the `session_id` for any Codex/worktree job that has one.

5. **Summarize.** Counts by status (e.g. "3 done, 1 running, 1 pending"). If `phase` is `BLOCKED` or any job is `blocked`/`failed`, point the user at `/v:resume {{args}}` to reconcile and re-dispatch the incomplete jobs.

## Notes

- This command never mutates the run. To recover an interrupted run, use [`/v:resume`](v-resume.md).
- Do **not** print fabricated cost or token metrics — `state.json` carries none and neither should this output (anti-ruflo).
