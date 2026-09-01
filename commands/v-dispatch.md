---
description: Execute a Compound-V-ready plan, manifest, or run-id on Engine C — the native Workflow dispatch engine. Accepts a bare plan path (auto-materializes the manifest), or a manifest|run-id (dispatches directly). Validates with --require-triage, runs partition-reviewer, emits and launches the workflow, then gates integration on compound-v-integration-gate.py before any job commit lands.
---

You are about to execute **Phase 3** of Compound V on `{{args}}` — manifest-driven dispatch on
**Engine C**, the native Workflow engine ([`workflows-accelerator.md`](../skills/compound-v/workflows-accelerator.md)).

**You run this yourself, at the top level. Do not delegate the run to the
`compound-v:parallel-dispatcher` subagent.** A subagent has no Workflow tool — probed live under
both the public name `Workflow` and the internal `RunWorkflow` — so delegating would silently
drop the run onto the residual path. It is also what kept `/v:epic` off Engine C: `/v:epic`
invokes `/v:dispatch` as a *command*, executed by the top-level agent, so once dispatch stops
delegating, the epic inherits Engine C along with everything else.

`{{args}}` is accepted in **three backward-compatible forms** — detect which:

| `{{args}}` is… | Action |
|---|---|
| a **plan path** (`docs/superpowers/plans/…md`) | **materialize the manifest first** (Phase 2 → `manifest.yaml` + `state.json` in a new run dir), then dispatch. *This is the 0.1.x contract the `plan-saved-nudge` hook and current users rely on — it still works.* |
| a **manifest path** (`…/execution/<run-id>/manifest.yaml`) | dispatch it directly (already materialized). |
| a **run-id** (a dir name under `docs/superpowers/execution/`) | resolve to that run's `manifest.yaml` and dispatch directly. |

## Steps

1. **Resolve `{{args}}`.**
   - If `{{args}}` is **empty**, list plans in `docs/superpowers/plans/` and runs in
     `docs/superpowers/execution/`, and ask which to dispatch.
   - If `{{args}}` is a **run-id** or a **manifest path**, load that run's `manifest.yaml`.
     Skip to step 3.
   - If `{{args}}` is a **plan path**, verify it exists, then **materialize** per
     [`/v:orchestrate`](v-orchestrate.md): apply
     [`routing-policy.md`](../skills/compound-v/routing-policy.md), write `manifest.yaml` +
     initial `state.json` into `docs/superpowers/execution/<run-id>/`
     (schema: [`execution-manifest.md`](../skills/compound-v/execution-manifest.md); run-dir +
     state shape: [`state-machine.md`](../skills/compound-v/state-machine.md)), then continue.

2. **Validate the manifest — always with `--require-triage`, in EVERY mode.**

   ```
   # legacy manifest (no fast_path block):
   python3 scripts/compound-v-validate-manifest.py --require-triage \
     docs/superpowers/execution/<run-id>/manifest.yaml
   # fast_path manifest (v2.9 pre-eval-backed):
   python3 scripts/compound-v-validate-manifest.py --require-triage \
     docs/superpowers/execution/<run-id>/manifest.yaml --mode pre-dispatch --repo-root <repo>
   ```

   **`--require-triage` is passed explicitly here, every time, in every mode. This is the whole
   closure.** The flag ships default-off in the validator on purpose — a mode-scoped default
   creates a circular dependency, because turning it on for `--mode pre-dispatch` reds the e2e
   suite inside the very task that adds the flag, and the task that emits the block cannot reach
   the validator to flip it later. So the closure lives at the caller: `/v:dispatch` demands a
   `triage` block, and **that is the mechanism that stops a future run repeating 3.0's own
   bootstrap exemption.** Do not drop the flag to "get a run started".

   Pick the mode by manifest kind (CR5-1): a `fast_path` block ⇒ `--mode pre-dispatch`; a legacy
   plan-based manifest carries no such block and is validated mode-lessly, as before — a mode-less
   `fast_path` manifest is fail-closed rejected. Non-zero exit ⇒ fix the manifest and re-run.

3. **Run the partition reviewer** (Iron Rule #4: no execution without a verified Partition Map):
   - Dispatch [`compound-v:partition-reviewer`](../agents/partition-reviewer.md) with the plan
     **and** the manifest (it runs `compound-v-validate-manifest.py` as its deterministic backing
     gate, then verifies disjointness + invariants).
   - `FAIL` → **STOP.** Surface the failure. Do not dispatch implementers.
   - `PASS` → continue.

4. **Select the engine by PROBE, not by version.**

   ```
   python3 scripts/compound-v-emit-workflow.py --engine-probe
   ```

   That reports the environment blockers it can decide (`CLAUDE_WORKFLOW_NAME_ONLY`,
   `CLAUDE_CODE_WORKFLOWS=false`, `CLAUDE_CODE_DISABLE_WORKFLOWS`) and prints a **clamped-spawn
   probe** to run. Run it. A clean environment is necessary and **never sufficient**:
   `disallowedTools` and `bashCommandClamp` were found in 2.1.238 while the product claims
   workflow support from 2.1.219, so a build that accepts `Workflow` and refuses the clamp would
   select Engine C and then **fail to create the Gate agent** — the clamp refuses the spawn
   outright rather than degrading.

   - Probe succeeds → **Engine C** (step 5).
   - Probe fails, or this is a subagent context → the **residual subagent path**
     ([`parallel-dispatcher.md`](../agents/parallel-dispatcher.md)), then rejoin at step 7.

   **Do not justify the fallback by claiming workflows are unavailable headless.** They are
   available in `claude -p` and in the Agent SDK; only the `ultracode` keyword is route-restricted.
   Justify it by what is actually true: a subagent has no Workflow tool, `CLAUDE_WORKFLOW_NAME_ONLY`
   refuses `scriptPath`, and the clamp may be unsupported on an older build.

5. **Emit the workflow, and commit it before it runs.**

   ```
   python3 scripts/compound-v-emit-workflow.py emit \
     docs/superpowers/execution/<run-id>/manifest.yaml \
     --out docs/superpowers/execution/<run-id>/dispatch.workflow.js
   git add docs/superpowers/execution/<run-id>/dispatch.workflow.js && git commit -m "…"
   ```

   The generator turns `depends_on` into topological waves, `max_parallel` into chunking, and
   backend/tier/effort/isolation into `agent()` options. It **refuses to emit** a script containing
   `Date.now`, `Math.random`, a bare argless clock read, or `import()` — all of which throw in that
   runtime, and none of which the runtime itself checks for on the `scriptPath` path.

6. **Launch it by `scriptPath` — this form is mandatory.**

   ```
   Workflow({ scriptPath: "docs/superpowers/execution/<run-id>/dispatch.workflow.js",
              args: { now: "<ISO-8601 stamped by you, not by the script>" } })
   ```

   The tool's own guidance is to pass the script inline; that is the opposite of committing the
   artefact, and `scriptPath` takes documented precedence. **Verify the run's reported script path
   equals the path you emitted** — otherwise the committed artefact is not what ran. Timestamps
   arrive via `args` because the runtime makes the clock globals throw.

   While it runs, the script writes what the rest of the pipeline needs:
   - `lane-map.json` — each implementer registers its real worktree as its first command, which is
     what lets [`hooks/lane-guard.sh`](../hooks/lane-guard.sh) resolve an acting job at all;
   - `receipts/<job-id>.gate.json` and `results/<job-id>.json` — one result per job, exactly one;
   - `state.json` per-job `worktree`, `baseline`, `status` and `merged`.

7. **Gate integration on the authority — BEFORE any job commit is integrated.**

   ```
   python3 scripts/compound-v-integration-gate.py \
     --run-dir docs/superpowers/execution/<run-id>/ --json
   ```

   **This call is not optional and not deferrable.** Every job must resolve to a verdict this
   script derived or verified: a missing or partial receipt is **re-derived** and that verdict
   wins; a receipt whose bindings disagree with the tree is **refused outright, never
   re-derived**; a receipt that verifies but whose conclusion disagrees with an independent
   re-derivation is refused as **contradicted**; `unverifiable` and duplicate receipts fail closed.
   Anything other than a clean report ⇒ **HALT**, do not merge, surface it.

   The workflow Gate stage is defence in depth and an early exit, never the authority — a clamp
   limits what an agent *can do*, not what it *returns*. Skipping this step would leave the
   authority as a correct script with no caller, which is the exact defect this release exists to
   fix, reproduced in its own cure.

8. **Review Gate — three passes (Opus), AC-gated.** [`spec-reviewer`](../agents/spec-reviewer.md):
   SPEC (each job's `acceptance`), QUALITY (no regressions, no fabricated metrics), INTEGRATION
   (cross-job seams, feature-level `acceptance_criteria`). DONE is gated on all three.

9. **Advance to `MERGED`, commit the run substrate, then hand off** to
   `superpowers:finishing-a-development-branch`. Write `phase: MERGED` into `state.json` **first**,
   then commit it together with `results/*.json`, `receipts/*.json`, `lane-map.json`,
   `dispatch.workflow.js` and any refreshed memory/scorecard files — in that one commit, before any
   worktree cleanup. `finishing-a-development-branch` runs `git worktree remove` on both Merge and
   Discard, which silently deletes anything uncommitted.

## Safety

- Do NOT dispatch implementers if partition-reviewer returned FAIL.
- Do NOT drop `--require-triage`, in any mode.
- Do NOT integrate a job commit without a clean `compound-v-integration-gate.py` report.
- Do NOT delegate the run to a subagent — it has no Workflow tool.
- A scope-gate **BLOCKED** halts the run; the offending worktree is left for inspection and never
  merged. Recover with [`/v:resume <run-id>`](v-resume.md).
- `backend` / `model` (e.g. `gpt-5.6-sol`) are **execution-layer data** — manifest only, never
  frontmatter. Reviewers stay `model: opus`.
- Never arm a headless Engine C launch under `bypassPermissions`: a run could start with no prompt
  and no spend cap.
- Do **not** print fabricated cost or token metrics (anti-ruflo).
