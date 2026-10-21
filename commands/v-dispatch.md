---
description: Execute a Compound-V-ready plan, manifest, or run-id on Engine C — the native Workflow dispatch engine. Accepts a bare plan path (auto-materializes the manifest), or a manifest|run-id (dispatches directly). Validates with --require-triage, runs partition-reviewer, emits and launches the workflow, then gates integration on compound-v-integration-gate.py before any job commit lands.
---

You are about to execute **Phase 3** of Compound V on `{{args}}` — manifest-driven dispatch on
**Engine C**, the native Workflow engine (`scripts/compound-v-emit-workflow.py`).

**You run this yourself, at the top level. Do not delegate the run to the
`superpowers-v:parallel-dispatcher` subagent.** A subagent has no Workflow tool — probed live under
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

**Re-dispatching a run that already ran (3.9.0).** Running `/v:dispatch` again on a run-id or
manifest path whose run directory already holds an attempt — any of `jobs/*.baseline`,
`receipts/*.gate.json` or `results/*.json` — first runs `resume-prepare` (step 5), exactly as
[`/v:resume`](v-resume.md) does. Without it a `direct` job keeps the first attempt's pin, and
every commit made since — the run's own bookkeeping, a taxonomy you added, anything — is charged
to the job as a violation. Before 3.9.0 `register-lane` only *warned* about that pin, and the
warning reached the Workflow agent, not you, so the halt read as an unexplained baseline
violation. Now both doors refuse with exit 2 and name `/v:resume`: `emit` refuses a run directory
whose concluded attempt still holds a pin other than `HEAD`, and `register-lane` refuses a `direct`
job whose pin is not `HEAD`. A `worktree` job re-pins itself on a concluded attempt at
`register-lane` (v3.6.3, see [`state-machine.md`](../skills/compound-v/state-machine.md) §
`baseline` re-pins on a re-attempt), but `emit`'s refusal covers it too; `resume-prepare` covers
both kinds.

## Resolving the plugin root

The `scripts/` and `schemas/` this command calls ship with the plugin — they are not files in
your own repository. Resolve the plugin root once per session before calling any of them:

```bash
CV="${CLAUDE_PLUGIN_ROOT:-$(ls -d "$HOME"/.claude/plugins/cache/*/superpowers-v/*/ 2>/dev/null | sort -V | tail -1)}"
CV="${CV%/}"
[ -f "$CV/scripts/compound-v-emit-workflow.py" ] || CV="$PWD"
[ -f "$CV/scripts/compound-v-emit-workflow.py" ] || { echo "superpowers-v plugin root not found: reinstall the plugin" >&2; CV=""; }
```

`CLAUDE_PLUGIN_ROOT` is set for hooks but is not set in this Bash environment, so treat it as a
hint, never the whole answer. The cache line covers an installed plugin; `$PWD` is used only when
the current directory is a checkout of this plugin. Anywhere else an unresolved root is reported
instead of pointing `$CV` at a `scripts/` directory your repository does not have — the old
fallback did exactly that in every user repository. An empty `$CV` is a stop: do not run the
steps below with it. Paths under `docs/superpowers/` stay relative; only the plugin's own
`scripts/` and `schemas/` get `$CV`.

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
   python3 "$CV/scripts/compound-v-validate-manifest.py" --require-triage \
     docs/superpowers/execution/<run-id>/manifest.yaml
   # fast_path manifest (v2.9 pre-eval-backed):
   python3 "$CV/scripts/compound-v-validate-manifest.py" --require-triage \
     docs/superpowers/execution/<run-id>/manifest.yaml --mode pre-dispatch --repo-root <repo>
   ```

   **`--require-triage` is passed explicitly here, every time, in every mode. This is the whole
   closure.** The flag ships default-off in the validator on purpose — a mode-scoped default
   creates a circular dependency, because turning it on for `--mode pre-dispatch` reds the e2e
   suite inside the very task that adds the flag, and the task that emits the block cannot reach
   the validator to flip it later. So the closure lives at the caller: `/v:dispatch` demands a
   `triage` block, and **that is the mechanism that stops a future run repeating 3.0's own
   bootstrap exemption.** Do not drop the flag to "get a run started".

   The flag also carries the SCOPED+ rule: a manifest with `triage.flavor: scoped_plus` is
   rejected unless it declares a `type: review` job with `tier: deep` and `backend: claude`. That
   half is checkable here because the reviewer is *declared*; the cross-model half is evidence
   that does not exist yet, and step 9 checks it after the fact.

   Pick the mode by manifest kind (CR5-1): a `fast_path` block ⇒ `--mode pre-dispatch`; a legacy
   plan-based manifest carries no such block and is validated mode-lessly, as before — a mode-less
   `fast_path` manifest is fail-closed rejected. Non-zero exit ⇒ fix the manifest and re-run.

   A refusal that names `.claude/compound-v-impact-taxonomy.yaml` ("does not exist", or a
   `taxonomy_digest` that "does not match") is not a manifest defect: the repository has no
   committed taxonomy, or the triage record predates it. Run [`/v:init`](v-init.md) Step 4g to
   draft and commit one, re-run [`/v:triage`](v-triage.md) for the request, and re-materialize the
   manifest ([`/v:orchestrate`](v-orchestrate.md)) so its `triage` block binds the new record.

   **One null-digest shape is accepted.** A `triage` block with `disabled_by_config: true` passes
   with `taxonomy_digest: null` — and only then: its `tier` must be `FULL`, `pre_eval.enabled`
   must still be `false` in `.claude/compound-v.json`, and `pre_eval_id` must name the committed
   record [`/v:triage`](v-triage.md) writes with `--record-disabled` (decision `FULL_PIPELINE`,
   null `taxonomy_digest`, localization flag `pre_eval_disabled`, its own digest intact). Turn the
   stage back on and the same block is refused; re-triage and bind the scored record.

   **Check a refused record before re-triaging blind:**

   ```
   python3 "$CV/scripts/compound-v-preeval.py" record-status --pre-eval-id <id> --repo . --json
   ```

   It is read-only and mirrors these triage checks: exit 0 means `--require-triage` would accept
   the record, exit 1 means it would not, and `reason` says what to run — a superseded record
   names its successor (`superseded_by`), a stale or missing taxonomy says to re-run `/v:triage`.
   `--request-env VAR` resolves the newest record for the request text in `$VAR` instead of an id.

3. **Run the partition reviewer** (Iron Rule #4: no execution without a verified Partition Map):
   - Dispatch [`superpowers-v:partition-reviewer`](../agents/partition-reviewer.md) with the plan
     **and** the manifest (it runs `compound-v-validate-manifest.py` as its deterministic backing
     gate, then verifies disjointness + invariants).
   - `FAIL` → **STOP.** Surface the failure. Do not dispatch implementers.
   - `PASS` → continue.

4. **Select the engine by PROBE, not by version.**

   > ### Engine C is enabled again as of 3.0.2 — what was wrong, and what closed it
   >
   > 3.0.1 disabled it. A cross-model review had found three CRITICAL defects, every one firing on
   > first real use, in a path 3.0 had made the default **without ever executing it end to end**.
   > All three are fixed and each is now pinned by a test that was **observed red** against 3.0.1:
   >
   > 1. **A `direct` job's patch landed in the wrong repository.** `record` branched on whether the
   >    agent-reported worktree was empty, and a compliant direct agent always reported its cwd — so
   >    it always entered `merge_back` — while the emitted command carried no `--repo-root` and fell
   >    back to the repo containing the installed script. The reproduction observed `M README.md`
   >    **in the plugin repository**. Now: the branch is the manifest's `isolation`, `--repo-root` is
   >    required by every subcommand, and the default destination is deleted outright.
   > 2. **A job could land with the authority never having run.** `record` staged into the checkout
   >    before the gate and never committed, so any later plain `git commit` swept it in. Now `record`
   >    is **evidence only**, and a serialized `finalize-wave` runs the integration gate → merges only
   >    what it permitted → commits, pathspec-restricted so it cannot sweep unrelated staged work.
   >    The wave loop stops scheduling after any non-success result.
   > 3. **The external worker lost its invocation and its worktree.** Now `emit` materializes
   >    `jobs/<id>.prompt.md` and `jobs/<id>.launch.argv.json`, the Gate carries its observed worktree
   >    into Record explicitly, and `register-lane` pins the baseline **before** the worker launches.
   >    An unpinned baseline is a gate error, not a fallback to a HEAD the worker can move.
   >
   > Also closed: the lane-map read-modify-write raced (a 12-writer subprocess test now pins it; a
   > mutant that reverts only the lock loses 1–3 of 12 lanes), `GATE_SCHEMA` rejected the `tests`
   > object the Gate emits on every passing verdict, and a throw in Implement dropped the item past
   > both Gate and Record — the v2.6.4 audit-trail loss, reproduced structurally.
   >
   > **Two authority passes, deliberately.** `finalize-wave` gates each wave before committing it;
   > step 8 re-runs the gate run-wide afterwards. The first is what makes a dependent's worktree see
   > its prerequisite; the second is the run-level authority and is cheap. Neither replaces the other.
   >
   > **The reason 3.0.1 existed, kept as history:** Engine C shipped as the default before it had
   > run end to end. Since 3.0.3 it has run every dogfood build of this repo — more than eighty
   > recorded runs under `docs/superpowers/execution/`, multi-wave with `depends_on`, a Codex job on
   > Engine C (3.4.3), a downstream seven-job feature (issue #19). What was still outstanding on
   > 2026-09-11 was a *wide* run: the widest recorded held five jobs. The 3.6.0 entry in the
   > CHANGELOG records the first wide one.



   ```
   python3 "$CV/scripts/compound-v-emit-workflow.py" --engine-probe
   ```

   That reports the environment blockers it can decide (`CLAUDE_WORKFLOW_NAME_ONLY`,
   `CLAUDE_CODE_WORKFLOWS=false`, `CLAUDE_CODE_DISABLE_WORKFLOWS`) and prints a **clamped-spawn
   probe** to run. Run it. A clean environment is necessary and **never sufficient**:
   `disallowedTools` and `bashCommandClamp` were found in 2.1.238 while the product claims
   workflow support from 2.1.219, so a build that accepts `Workflow` and refuses the clamp would
   select Engine C and then **fail to create the Gate agent** — the clamp refuses the spawn
   outright rather than degrading.

   - Probe succeeds → **Engine C** (step 5). `engine_c: false` in `.claude/compound-v.json` still
     forces the residual path for anyone who wants it.
   - Probe fails, or this is a subagent context → the **residual subagent path**
     ([`parallel-dispatcher.md`](../agents/parallel-dispatcher.md)), then rejoin at step 8.

   **Do not justify the fallback by claiming workflows are unavailable headless.** They are
   available in `claude -p` and in the Agent SDK; only the `ultracode` keyword is route-restricted.
   Justify it by what is actually true: a subagent has no Workflow tool, `CLAUDE_WORKFLOW_NAME_ONLY`
   refuses `scriptPath`, and the clamp may be unsupported on an older build.

5. **Emit the workflow, and commit it before it runs.**

   **A run that already ran is prepared first.** If the run directory holds any of
   `jobs/*.baseline`, `receipts/*.gate.json` or `results/*.json`, run this before `emit`:

   ```
   python3 "$CV/scripts/compound-v-emit-workflow.py" resume-prepare \
     --run-dir docs/superpowers/execution/<run-id>
   ```

   It is the same call [`/v:resume`](v-resume.md) step 5 makes: for every job not yet integrated
   (and not a codex job left for resume-in-place) it deletes the stale pin, resets the job to
   `pending`, drops its lane-map entries, archives its gate receipt as
   `receipts/<id>.gate.superseded-*.json` and retires its before-image — a `worktree` job's
   `preexisting/<id>.txt` is deleted, a `direct` job's is kept minus the lines for the files
   registration rewrites. Integrated jobs are left alone, and the phase returns to
   `PARTITION_VERIFIED`.

   `emit` (without `--print`) exits 2 with `REFUSING TO EMIT: run directory … still holds a
   previous attempt for <job ids> (pinned baseline …)` when any manifest job has a receipt
   (`receipts/<id>.gate.json`) or result (`results/<id>.json`) on disk, is not
   `merged.integrated`, is not a codex job left for resume-in-place, and still holds a pin that is
   not the current `HEAD`. The message names `/v:resume <run-id>` and the `resume-prepare` call
   above. A pin with no receipt or result yet (an attempt that died before Gate) passes `emit`; a
   `direct` job carrying one is then refused at `register-lane`, exit 2, `REFUSING TO REGISTER
   direct job <id>`. Answer either refusal with `resume-prepare`, never by deleting files by hand.

   ```bash
   EMIT_JSON="$(python3 "$CV/scripts/compound-v-emit-workflow.py" emit \
     docs/superpowers/execution/<run-id>/manifest.yaml \
     --out docs/superpowers/execution/<run-id>/dispatch.workflow.js)" &&
   printf '%s' "$EMIT_JSON" \
     | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.stdout.write("".join(p+"\0" for p in [d["script"]]+d["job_artefacts"]))' \
     | xargs -0 git add -- &&
   git commit -m "…"
   ```

   **Commit every path in `job_artefacts`, not only the script.** `emit` prints one JSON report;
   `script` is the workflow file and `job_artefacts` lists what it wrote beside it for each job:
   `jobs/<id>.prompt.md`, `jobs/<id>.launch.argv.json` for an external backend, and
   `jobs/<id>.recall-check.json` when recall tightened the job. None of them is exempt from the scope
   gate by name. On a re-dispatch this matters: `resume-prepare` keeps a `direct` job's snapshot,
   which binds the first attempt's prompt to its old digest, so a re-emitted prompt whose bytes
   changed and was left uncommitted is charged to that job as an out-of-lane write. Committed, it
   is part of the new pin and nothing is charged. On a first dispatch the commit costs nothing and
   keeps the handoff files durable.

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

   **Wave width vs. the runtime's concurrency cap.** The native Workflow runtime runs "up to 16
   concurrent agents by default, fewer when Claude Code has fewer CPUs available, including inside
   a CPU-limited container" (docs: code.claude.com/docs/en/workflows, "Behavior and limits",
   fetched 2026-09-21). Engine C's `pipeline(wave, implementStage, gateStage, recordStage)` chains
   Implement → Gate → Record **per job**, so a job holds exactly one agent slot at a time — a wave
   of W jobs competes for W of those 16 slots, with no per-job multiplier
   (`compound-v-validate-manifest.py`'s `WAVE_EXCEEDS_RUNTIME_CONCURRENCY` advisory, surfaced by
   step 3's partition-reviewer, already did this arithmetic against this manifest). A wave over the
   cap does **not** fail — the extra jobs queue for a slot as earlier ones finish — but before
   launching a manifest with any wave wider than 16, decide whether you want it to run at full
   width:
   ```bash
   export CLAUDE_CODE_WORKFLOW_MAX_CONCURRENT_AGENTS=<n>   # 1-256, Claude Code >= 2.1.269;
                                                            # <n> >= the widest wave's job count
   ```
   Pro plans default the size guideline to `small` (fewer than 5 agents) — that guideline is
   **advice Claude takes when writing a NEW workflow script, never a cap on a manifest-driven
   Engine C run you already emitted**; it does not shrink or reject this wave.

   **The usage-limit pause (>= 2.1.271) — three lines.** A run pauses (agents wait, no new ones
   start) only when **all** of: it is an interactive session signed in with a claude.ai
   subscription; `autoContinueAtUsageLimit` is on; and the reset is within 24h with the run not
   already having waited twice. **In `claude -p`/headless, a background session, Remote Control, or
   an agent-team teammate session the run never pauses at all — the affected agent just fails**,
   and it is the emitted script's own retry/escalation ladder
   (`RETRY_MAX_ATTEMPTS_DEFAULT`, the one-shot `CLAUDE_ESCALATION` reviewer lift — see
   [`failure-policy.md`](../skills/compound-v/failure-policy.md)'s `timeout` class) that catches
   it, not a pause. This dispatch runs at the top level per the header above, so check which of the
   two you actually are before reading a `STALE` job's `PAUSED?` hint (step 7's transcript watch,
   or the liveness sweep on the residual path) as "go check `/workflows`" versus "this already
   failed and the ladder already handled it."

   While it runs, the script writes what the rest of the pipeline needs:
   - `lane-map.json` — each implementer registers its real worktree as its first command, which is
     what lets [`hooks/lane-guard.sh`](../hooks/lane-guard.sh) resolve an acting job at all;
   - `jobs/<job-id>.test-contract.json` — written by that same first command, **before** an
     external worker launches, because that is the only moment early enough for the worker to be
     handed `--test-contract-file`. A contract resolved after the implementer has run reaches
     nobody;
   - `receipts/<job-id>.gate.json` and `results/<job-id>.json` — one result per job, exactly one;
   - `state.json` per-job `worktree`, `baseline`, `status` and `merged`;
   - `docs/superpowers/memory/triage-outcomes.jsonl` — the precision-IGNORED `merge_pending`
     `actual`, appended once every job is terminal. Step 10 writes the terminal one.

7. **Watch the live transcripts in the background (v3.4.2).** While the workflow launched in step 6
   runs, use the Monitor tool to run the read-only transcript watch every two minutes rather than
   waiting for the gate to catch a problem after the fact:

   ```bash
   python3 "$CV/scripts/compound-v-transcript-watch.py" --run-dir docs/superpowers/execution/<run-id> --every 120
   ```

   It is advisory only — it never writes into the run directory or acts on a signal — but two of its
   signals are worth acting on immediately rather than waiting for the run to finish: **`out-of-lane`**
   (a write outside the job's `write_allowed`) and **`wrong-cwd`** (a `register-lane` whose isolation or
   cwd disagrees with the manifest). Either one, seen live, is reason enough to `TaskStop` the workflow
   and re-orchestrate early — the same move that would have caught 3.4.0's r1 defect and 3.4.1's r2
   defect early, before the gate, instead of only after it.

8. **Gate integration on the authority — BEFORE any job commit is integrated.**

   ```
   python3 "$CV/scripts/compound-v-integration-gate.py" \
     --run-dir docs/superpowers/execution/<run-id>/ --json
   ```

   **This call is not optional and not deferrable.** Every job must resolve to a verdict this
   script derived or verified: a missing or partial receipt is **re-derived** and that verdict
   wins; a receipt whose bindings disagree with the tree is **refused outright, never
   re-derived**; a receipt that verifies but whose conclusion disagrees with an independent
   re-derivation is refused as **contradicted**; `unverifiable` and duplicate receipts fail closed.
   Anything other than a clean report ⇒ **HALT**, do not merge, surface it. **On Engine C this call
   already ran inside every `finalize-wave`** — its verdicts are what merged each wave — so a run-wide
   re-run after the last wave is a confirmation, and it reports an already-merged `direct` job as
   `stale` once the bookkeeping commit moved HEAD (finding 149): read `tally` and `merged.integrated`
   in `state.json` before treating that as a halt.

   The workflow Gate stage is defence in depth and an early exit, never the authority — a clamp
   limits what an agent *can do*, not what it *returns*. Skipping this step would leave the
   authority as a correct script with no caller, which is the exact defect this release exists to
   fix, reproduced in its own cure.

9. **Review Gate — three passes (Opus), AC-gated.** [`spec-reviewer`](../agents/spec-reviewer.md):
   SPEC (each job's `acceptance`), QUALITY (no regressions, no fabricated metrics), INTEGRATION
   (cross-job seams, feature-level `acceptance_criteria`). DONE is gated on all three.

   **If — and only if — the manifest says `triage.flavor: scoped_plus`, a second opinion
   runs first, and it is mandatory.** SCOPED+ means *a small edit on a sensitive path*: the
   change is one file and twenty lines, so the SCOPED band is the honest size, but the path
   is one where being wrong is expensive. Such a run buys back both reviews the plain SCOPED
   band skips — the deep in-harness reviewer (declared in the manifest, and step 2's
   `--require-triage` already refused to dispatch without it) and one look from outside
   Claude's own family, via **the ladder** ([cross-model-review.md § The ladder](../skills/compound-v/cross-model-review.md#the-ladder)):
   Codex when it is installed, else an advisor-assisted Opus subagent, else refuse — a SCOPED+
   run never silently passes with no second opinion at all.

   Seal the reviewed bytes, then run rung 1 or rung 2 of the ladder:

   ```
   RUN=docs/superpowers/execution/<run-id>
   git diff --no-color <baseline from state.json> > $RUN/receipts/cross-model.patch
   # Rung 1 — Codex present:
   "$CV/scripts/compound-v-codex-review.sh" --repo "$PWD" \
     --plan-file "$PWD/$RUN/receipts/cross-model.patch" \
     --context-file "$PWD/<manifest spec_path>" > $RUN/receipts/.review.json
   # Rung 2 — no Codex, an advisor is configured: dispatch one read-only Opus subagent via
   # the Agent tool with the same adversarial prompt (told to consult the advisor before its
   # verdict) instead of the command above; write its plan-review.schema.json output to the
   # same $RUN/receipts/.review.json path.
   # wrap: the reviewer's output is plan-review findings and nothing else — the binding fields
   # are added here, and the receipt is sealed with the SHARED digest primitive.
   python3 -B - <<'EOF'   # writes $RUN/receipts/cross-model.json
   ... {run_id, pre_eval_id, diff_digest,
        reviewer_backend: "codex" | "claude-advisor",  # "claude-advisor" only on rung 2
        cross_model: <false iff reviewer_backend == "claude-advisor", else true>,
        reviewer_model, produced_at, review: <the reviewer's JSON>}
   ... then digest=record_digest(obj, "digest")
   EOF
   python3 "$CV/scripts/compound-v-validate-manifest.py" $RUN/manifest.yaml --require-triage \
     --require-cross-model-receipt $RUN/receipts/cross-model.json \
     --expected-diff-digest "$(python3 "$CV/scripts/compound-v-taxonomy.py" --digest $RUN/receipts/cross-model.patch)"
   ```

   A `reviewer_backend: "claude-advisor"` receipt is **accepted with a `SECOND_OPINION_SAME_FAMILY`
   WARN**, not refused — rung 2 satisfies the SCOPED+ mandate, honestly. State the disclosure
   line verbatim wherever this run's result is reported: *"Second look by the same model family
   (Claude + advisor) — no decorrelation; not a cross-model review."* Only rung 3 (neither Codex
   nor an advisor configured) is refused for a SCOPED+ run.

   The receipt's shape is [`schemas/cross-model-receipt.schema.json`](../schemas/cross-model-receipt.schema.json)
   — a flat envelope around the driver's `plan-review` output, because that schema is
   `additionalProperties: false` and cannot carry a run id. **The findings stay advisory: you
   arbitrate, exactly as for [`/v:review-plan`](v-review-plan.md), and a `concerns` verdict is
   not a merge blocker.** What is *not* advisory is that the review ran, on this run, over these
   bytes — which is why the validator refuses a receipt whose ids do not bind, whose
   `diff_digest` is not the patch you sealed, or whose self-digest does not re-derive. A run whose
   receipt does not verify does not proceed to the merge; fix it or re-run the review. Commit the
   receipt and the patch with the rest of the run substrate in step 10.

   **When `spec-reviewer` returns ISSUES, apply `superpowers:receiving-code-review` before minting
   a single fix job:** check each finding against the code as it actually is, and push back with the technical
   reason when a finding is wrong for this codebase instead of dispatching a fix for it. Findings
   are input to your judgment, not orders — and a finding you cannot verify is not thereby
   dismissed: say what you could not check and why.

10. **Append the terminal `actual`, commit the run substrate, then hand off**
   to `superpowers:finishing-a-development-branch`. **Do not write `phase: MERGED` into
   `state.json` by hand** — the workflow finalizer has advanced the phase itself since stage 1
   (`fix(finalize)`, commit f0dfc30), so a hand-written phase here is at best a duplicate and at
   worst a regression of what the finalizer recorded. Read the phase back if you want to confirm
   it; do not author it. Once the merge/commit boundary has actually succeeded, append the run's
   terminal triage outcome:

   ```
   python3 "$CV/scripts/compound-v-triage-outcomes.py" actual \
     --pre-eval-id <manifest triage.pre_eval_id> --run-id <run-id> \
     --review-result approved            # the step-8 verdict, verbatim; never assumed
     [--demoted] [--ci-failed] [--reverted] [--escalated]   # negative outcomes, when they happened
   ```

   **This append is on the same footing as the `state.json` commit, not an optional extra.**
   `predicted` → `bind` → `actual` is a three-event join, and until this release the `actual`
   half had **no reachable producer on this path at all**: the only live callers were the
   residual `parallel-dispatcher` (which step 4 tells you not to use) and `/v:collect`'s v2.9
   fast-path tail. So the join never closed, `/v:status` precision read `insufficient`
   permanently, and the miscalibration circuit breaker could only ever see demotions — the exact
   blind spot negative outcomes exist to remove. Report the outcome that happened; a run whose
   review did **not** pass gets that recorded, not an `approved` written to tidy the log.

   Engine C's Record stage already appended a precision-**IGNORED** `merge_pending` intermediate
   when its last job went terminal. That one is deliberately not terminal (CR5-4): this append
   replaces it, last-writer-wins, and only a terminal `actual` whose committed git blob backs it
   is ever counted. **A manifest with no `triage` block has no `pre_eval_id`** (3.0's own
   bootstrap manifest is one): say so and skip the append — never mint an id to make the join
   close.

   **Per-ticket usage — extract it before the run-substrate commit below.** On Engine C the implementers are Workflow
   agents, so their token counts are in no worker-written `job_result`; they live in the Workflow's
   own transcripts. Sum them into the run's results:

   ```
   /usr/bin/python3 "$CV/scripts/compound-v-usage-extract.py" --backend claude \
     --workflow-transcript "$HOME/.claude/projects/<cwd-slug>/" \
     --run-dir docs/superpowers/execution/<run-id> --write
   ```

   `<cwd-slug>` is the absolute working directory with every `/` replaced by `-` — for this repo,
   `-Users-oleg-Dev-superpowers-v`. Engine C's agent transcripts sit under
   `<slug>/<session-uuid>/subagents/workflows/<wf-id>/agent-*.jsonl`; the scan is recursive, so the
   project directory is the right thing to point at. A transcript is tied to a job by the `--run-dir`
   **and** `--job-id` that every stage prompt embeds — the run dir is what keeps a repeated job id like
   `spec-review-1` from crediting another run's tokens to this one — and a job's implement, gate and
   record stages are summed together, deduplicated by message id (one message spans several transcript
   lines and each repeats the same cumulative usage; summing per line inflates the cache figures by
   roughly half). The written `usage` carries input, output, cache-read and cache-creation tokens with
   `source: workflow-transcript`, and the commit below then carries it.

   The dry run (no `--write`) prints one line per job, then `unmeasured:`, then `unmatched:`. A large
   `unmatched:` count is normal — it is every transcript in the project that belongs to some other run.
   A `run_level:` line reports the wave-level `finalize-wave` stages: real spend on this run that belongs
   to no single job, reported rather than divided among them.

   **A job with no transcript stays unmeasured** — `--write` leaves its result file untouched, no `usage`
   key, and `/v:status` renders `—` for it. Never estimate, extrapolate or back-fill a token count to
   fill that gap (anti-ruflo). `--write` is idempotent: the totals are recomputed from the transcripts
   and replace the previous object, so re-running it cannot double-count. Exit 2 means the transcript
   directory or the run directory does not exist.

   **Before anything here reads as "the run is done", run `superpowers:verification-before-completion`.**
   Its rule is evidence before claims: name the command that proves the claim, run it fresh, read
   its full output and exit code, and only then state the claim — no completion claim without fresh
   verification evidence. Every verdict this step reports (review passed, integration gate clean,
   tests green) must come from output in hand now, not from a step you remember succeeding.

   Then commit `state.json` together with `results/*.json`, `receipts/*.json` (including a
   SCOPED+ run's `receipts/cross-model.json` and the `cross-model.patch` its digest binds to),
   `lane-map.json`,
   `jobs/*.test-contract.json`, `dispatch.workflow.js`,
   `docs/superpowers/memory/triage-outcomes.jsonl` and any refreshed memory/scorecard files — in
   that one commit, before any worktree cleanup — because an uncommitted run directory is not in
   the repository at all: `git clean -fdx` wipes it, a fresh clone never had it, and removing the
   worktree it was written in takes it along. The committed record is the only durable audit trail.
   (Not because the hand-off skill discards it: Superpowers 6.2.0's `finishing-a-development-branch`
   menu is merge locally / push a PR / keep the branch as-is, with no Discard option
   (`finishing-a-development-branch/SKILL.md:55-65`) — a discard needs the human to ask for one in
   so many words — and its cleanup removes a worktree only when
   the path sits under `.worktrees/` or `worktrees/` (`SKILL.md:169-178`).)

   In the final report, after a run with any BLOCKED or failed job, suggest
   [`/v:lessons`](v-lessons.md) — it drafts a routing lesson when the same failure has recurred
   across independent runs, and writes nothing until the human accepts it.

## Safety

- Do NOT dispatch implementers if partition-reviewer returned FAIL.
- Do NOT drop `--require-triage`, in any mode.
- Do NOT integrate a job commit without a clean `compound-v-integration-gate.py` report.
- Do NOT delegate the run to a subagent — it has no Workflow tool.
- A scope-gate **BLOCKED** halts the run; the offending worktree is left for inspection and never
  merged. Recover with [`/v:resume <run-id>`](v-resume.md).
- `backend` / `model` (e.g. `gpt-6.1-sol`) are **execution-layer data** — manifest only, never
  frontmatter. Reviewers stay `model: opus`.
- Never arm a headless Engine C launch under `bypassPermissions`: a run could start with no prompt
  and no spend cap.
- Do NOT finish a run without the step-9 `actual` append: an unclosed `predicted`↔`actual` join
  is what keeps precision at `insufficient` and the circuit breaker blind to every negative
  outcome that is not a demotion.
- Do **not** print fabricated cost or token metrics (anti-ruflo).
