# 0004. The native Workflow runtime becomes the dispatch engine, and the scope gate moves into the run

- **Status:** Accepted
- **Date:** 2026-09-01
- **Reverses:** the "What STAYS in Engine A — even when C runs" guarantee, which commit `c27d33e`
  deleted from [`skills/compound-v/workflows-accelerator.md`](../../../skills/compound-v/workflows-accelerator.md);
  it survives only in git — `git show c27d33e^:skills/compound-v/workflows-accelerator.md`
- **Deciders:** Compound V v3.0 design, Feature D
  ([spec § "Feature D — Dispatch on the native Workflow runtime"](../specs/2026-09-01-v3.0-triage-tests-orchestration-design.md))

## Context

In 1.0 this project decided where the native Workflow runtime — Engine C — was allowed to touch the
system, and called that boundary load-bearing. Verbatim, from the § "What STAYS in Engine A — even
when C runs" section that commit `c27d33e` deleted from
[`workflows-accelerator.md`](../../../skills/compound-v/workflows-accelerator.md) — the quoted lines
are `:60-71` of the pre-deletion blob, `git show c27d33e^:skills/compound-v/workflows-accelerator.md`:

> This is the load-bearing guarantee. Engine C only changes **how jobs fan out**, never
> the enforcement or recovery layer:
>
> - **The scope gate stays in Engine A.** Every job's `files_changed` is checked against
>   `write_allowed` by `compound-v-scope-check.py`
>   in A's layer, regardless of which engine dispatched the job. File-scope enforcement
>   never regresses to C's weaker guarantees.
> - **`state.json` resume stays in Engine A.** Workflows' resume is *same-session-only*
>   and "starts fresh" after a Claude Code exit — it fails the crash case by design
>   (PRD §3.1). So crash-resume lives entirely in A's
>   `state-machine.md` layer. Even when C ran the dispatch, the run
>   is resumable because A owns the state.

(Two inline link targets in the source are rendered above as plain filenames; the words are unchanged,
and the source's own relative paths would not resolve from this directory.)

The reasoning was sound and the conclusion was wrong, because of what "Engine A's layer" actually is.

**Engine A is prose.** On the `claude` backend there is no program that runs the scope gate. There is a
document telling a dispatcher model to run it, and the document is candid about its own status —
[`agents/parallel-dispatcher.md` § "Step 2b — Scope gate + state.json"](../../../agents/parallel-dispatcher.md) heads the step
"(wiring, not prose)" and then supplies a shell command a model must remember to type. The external
backends are different: the codex, cursor and antigravity worker scripts invoke
[`compound-v-scope-check.py`](../../../scripts/compound-v-scope-check.py) themselves, in bash, as
[`compound-v-run-codex-worker.sh`](../../../scripts/compound-v-run-codex-worker.sh) records in its
"git-derived enforcement" comment block —
"the SAME deterministic gate the dispatcher runs after every job... Single source of truth."

**And the external backends were never used.** Every job declared in every committed manifest under
`docs/superpowers/execution/` names `backend: claude` — **73 of 73** across the runs that were
dispatched
([recon `:44`](../recon/2026-09-01-v3.0-triage-tests-orchestration.md)). So the flagship guarantee of
this project, the thing that distinguishes it from a fan-out script, was mechanically enforced on
exactly zero of the jobs anyone ran.

That is what the 1.0 decision protected. It kept the gate out of Engine C to stop it "regressing to C's
weaker guarantees", while the layer it was kept in had no enforcement to regress from. Protecting a
prose gate by keeping it in prose is not protection; it is a naming convention.

The native runtime changed what is available. A live probe
([1D](../preflight/2026-09-01-v3.0-1d-native-enforcement-probe.md)) established that a workflow can
spawn an agent narrowed at spawn to nothing but the scope-check invocation, and that `PreToolUse` fires
for workflow-spawned agents carrying `agent_id` — a prevention point, not only a detection point.

## Decision

**Engine C is the primary and default way jobs execute in 3.0, and the scope gate and the state write
move into the run. The batching, ordering, worktree-lifecycle and concurrency prose in
`agents/parallel-dispatcher.md` is deleted, not left beside it.**

Concretely, the run becomes a three-stage pipeline — Implement, Gate, Record — and the Gate agent is
narrowed at spawn: `disallowedTools` strips its tool pool to Bash plus structured output, and
`bashCommandClamp` confines its shell to the scope-check invocation alone. The clamp is fail-closed: it
denies when the permission check crashes, denies commands whose structure it cannot verify, and refuses
to spawn the agent at all if it can bind nothing. A clamped Gate agent cannot do anything except run the
check.

### What is explicitly NOT moved, and why

This is the half that keeps the reversal honest.

**The workflow Gate is not the authority.** A Gate stage is an `agent()` call. The script itself has no
filesystem and no shell — it cannot run the gate; it can only ask an agent to. And the clamp bounds what
that agent *can do*, never what it *returns*: a structured-output schema proves the shape of the JSON
that came back, not that the check ran to produce it. An earlier draft of this spec claimed the
in-workflow gate was authoritative. That claim is withdrawn and named here so it is not made again.

**So the git-derived integration postcondition stays outside the run, and it holds the authority.** Every
original job must have exactly one gate receipt bound to its baseline commit, its realised commit and a
diff digest. Where a receipt is missing, `null`, or its digests disagree with the tree, the verification
layer runs [`compound-v-scope-check.py`](../../../scripts/compound-v-scope-check.py) itself and **that
verdict wins**. Integration is refused until every job has a valid receipt. The workflow gate is defense
in depth and an early exit, nothing more.

Also staying outside the run:

- **Cross-session resume.** The 1.0 guarantee said "`state.json` resume stays in Engine A". Half of that
  is reversed and half is not, and the distinction matters: the state **write** moves into the run as
  the Record stage; the **resume authority** does not. The native runtime's resume is same-session-only
  and re-runs completed agents past a failure point, so `state.json` and `/v:resume` remain the
  crash-recovery mechanism exactly as [`state-machine.md`](../../../skills/compound-v/state-machine.md)
  describes.
- **Retry, integration, review and per-failure-class policy**, which the workflow runtime has no notion
  of.

Three properties are mandatory because the runtime's failure semantics are sharp:

- **The Gate stage must be total.** A stage that throws drops its item to `null` and skips every
  remaining stage — no `state.json` written, no record committed, the job silently `null`, precisely on
  the jobs that went wrong. That is the v2.6.4 audit-trail loss reappearing structurally. The Gate
  catches everything and returns a verdict; it never throws. An Implement-stage throw is covered the
  same way: the postcondition treats a missing receipt exactly like a failed one.
- **`null` is FAIL, never pass.** `agent()` returns `null` when it is skipped or dies on a terminal API
  error. A gate reading `null` as "no violations" is unreachable exactly when the worker died.
- **Every side effect is idempotent.** On relaunch, agents that started after a failed one re-run,
  completed ones included. Every attempt and receipt is keyed to an immutable commit hash, each hash is
  merged at most once, and reconciliation skips terminal jobs. Idempotence on Record alone would still
  leave double commits and double worktree integration.

### Alternatives declined

- **Keep Engine C opt-in, as 1.0 decided.** Declined: that design was decided in 1.0 and never built, and
  five years of it would not have changed the number above. It leaves the gate as prose on the only path
  anyone uses.
- **Fix the prose instead — make the dispatcher's scope-gate step louder.** Declined: louder prose is
  the mechanism that produced 73 jobs with no mechanical gate. The step is already marked "wiring, not
  prose" and already carries the exact command; there is no remaining volume to add.
- **Make the in-workflow Gate authoritative and drop the outside postcondition.** Declined, and named
  above as the specific error to avoid: schema proves shape, not execution.
- **Ship Engine C alongside the old loop as a third orchestrator.** Declined. Compound V ships no
  competing orchestrators. Two things survive and neither is an engine: the **verification layer** (the
  postcondition, `state.json`, `/v:resume`), which is the product; and the **residual subagent path**, a
  reduced form of the old loop retained only for contexts that physically cannot launch a workflow — on
  current evidence, subagent contexts alone.

## Consequences

- **The `/v:epic` blocker dissolves as a side effect.** A subagent has no Workflow tool. Today
  `/v:dispatch` delegates the run to the `compound-v:parallel-dispatcher` subagent, which is why an epic
  would otherwise be stuck on the old path. Once dispatch stops delegating to a subagent, the epic
  inherits Engine C along with everything else.
- **The scope gate stops being something a model can forget.** Its worst case moves from "the dispatcher
  did not type it" to "the receipt is missing, so the verification layer runs the check itself".
- **A committed workflow artifact must be the artifact that ran.** The tool's own guidance is to pass the
  script inline; `scriptPath` takes documented precedence, and the dispatch prose forces that form.
  Inline would mean the committed script is not what executed — an audit-trail lie of the kind this
  project exists to prevent.
- **We now depend on a runtime we do not control**, at a floor of Claude Code ≥ 2.1.219, including two
  options (`disallowedTools`, `bashCommandClamp`) found by reading the installed binary rather than in
  the public tool description. Undocumented options can change without notice. The mitigation is the
  postcondition: if the clamp weakens or the Gate stage stops behaving, the outside check still runs and
  still decides.
- **The cross-vendor path needed explicit design, not an assurance.** A clamp that omits
  `scripts/compound-v-run-<backend>-worker.sh` cannot launch the external family at all, and non-`claude`
  jobs run their workflow agent at `isolation: 'direct'` so the worker owns its own worktree — this
  repository already carries a downstream incident from getting nested worktrees wrong.

### Falsification condition

This decision is wrong, and the dispatch path should return to the verification layer's own loop, if any
of the following is observed:

1. **The integration postcondition passes a job whose tree disagrees with its receipt.** The
   authority-of-last-resort is the whole basis for allowing the gate to move; if it can be satisfied by
   a receipt it did not verify, nothing was gained and a layer of misplaced confidence was added.
2. **A run integrates with a job that produced no receipt at all.** The postcondition refusing to run is
   worse than the old prose gate, because the old gate at least had a human-legible step someone could
   notice was skipped.
3. **The residual subagent path is needed for materially more than subagent contexts** — a version floor
   problem, a `CLAUDE_CODE_WORKFLOWS` restriction, or headless launch failing in practice. If most runs
   fall back, Engine C is not the engine and this ADR describes a system that does not exist. Countable:
   record which path each run took.
4. **Moving the gate into the run reduces enforcement coverage below the pre-3.0 baseline.** The baseline
   is stated plainly so this is testable rather than rhetorical: on the `claude` path, mechanical
   coverage before 3.0 was zero.

### What this does not show

**What the 73 actually counts.** It counts jobs *as declared in committed manifests*, not jobs observed
to have completed. Every `backend:` line in every manifest under `docs/superpowers/execution/` reads
`claude`: 73 across the eleven runs that were dispatched, 79 if the six-job `2026-07-26-v2.18-autonomy`
manifest is included, whose run was never executed. Only 6 of those 11 run directories carry a
`state.json`, and no `state.json` in this repository records a `backend` field at all. So the figure
establishes that **no non-`claude` backend was ever scheduled** — which is the claim this ADR rests on —
and does not establish that 73 jobs each ran to completion, nor that 73 jobs each escaped the gate. Some
of them were surely gated by a dispatcher that did type the command; there is no record either way, which
is itself the point.

The figure is also this repository only, and this repository is the plugin's own author. It says nothing
about how downstream users of Compound V distribute jobs across backends.

Nothing here is a throughput or latency claim. No comparison between Engine C and the previous loop has
been measured, and per [ADR 0002](0002-limits-ship-with-the-claim.md) none may be published until it is.
The runtime capabilities this decision depends on were established by a live probe on one machine at
Claude Code 2.1.238; the probe shows the capability exists there, not that it is stable across versions.
