# 0003. Test scope follows the diff, on a three-set floor that CI still backstops

- **Status:** Accepted
- **Date:** 2026-09-01
- **Supersedes:** the `impacted-tests` rejection in
  [`2026-07-25-v2.17-cochange-and-evidence-packing-design.md:308-310`](../specs/2026-07-25-v2.17-cochange-and-evidence-packing-design.md)
- **Deciders:** Compound V v3.0 design, Feature B
  ([spec § "Feature B — Scoped tests, bought with a floor and an evaluation"](../specs/2026-09-01-v3.0-triage-tests-orchestration-design.md))

## Context

Nine weeks ago this project considered this exact feature and killed it, in a list headed "killed on
our own data — do not re-litigate". The rejection, verbatim:

> - **`impacted-tests` (run only the tests a diff exercises).** REJECTED: directly contradicts the
>   v2.14.1 lesson — we found 25 of 29 selftests silently never running in CI. Running *fewer* tests is
>   the bug we just fixed.

That rejection was right about its evidence and wrong about its inference.

**Right about the evidence.** v2.14.1 found a real, severe defect: a green CI that was not running most
of the suite. The fix outlived the release — CI now fails when its discovery glob matches nothing, and
says why in the failure text: "no test files discovered under `tests/` — the discovery glob is dead,
which is exactly how 25 of 29 selftests silently stopped running in v2.14"
([`validate.yml:362-364`](../../../.github/workflows/validate.yml)).

**Wrong about the inference.** "Running fewer tests" was treated as one thing. It is two, and they have
opposite risk profiles:

1. **Tests that run nowhere.** v2.14.1's defect. A coverage hole with no backstop, invisible, and
   discovered by accident. This is a bug.
2. **Tests that do not run in the pre-merge inner loop but do run in the merge-blocking suite.** A
   schedule, with a backstop, whose worst case is a late signal rather than an absent one.

The v2.17 rejection reasoned about (2) using the harm of (1). Different failure, different mitigation.

Two further facts changed the ground under the rejection, and both are properties of this repository as
it stands today rather than arguments:

- **There is no "run everything" to preserve.** `run_test_floor`
  ([`compound-v-fastpath-run.py`](../../../scripts/compound-v-fastpath-run.py), `def run_test_floor`) is already
  merge-blocking and already fail-closed on an empty command, and it has never had a producer for
  `--test-cmd`. The manifest has no test field at all. So the status quo the rejection was defending is
  not "the full suite runs"; it is "nothing runs mechanically, and
  [`agents/spec-reviewer.md`](../../../agents/spec-reviewer.md), as it read before Feature B's own
  task changed it — § 3.3 "Build is green": *"The composite must build/compile and the test suite must
  pass"* (`git show 8d08b70^:agents/spec-reviewer.md`, replaced by `8d08b70`) — asks a model to confirm
  a suite it was never told how to invoke."
- **Nothing under `tests/` was swept by CI on this branch until Feature B's own task-0 landed the
  sweep** — the v2.14.1 false-green shape recurring, in the very repository that named it.

## Decision

**A job declares `test_scope` (`full` | `impacted` | `floor_only`), resolved through a declarative
`impacted_map` in the manifest's `test_contract`. Scoping buys early feedback only. The merge-blocking
CI run is what preserves the guarantee, and it always runs.**

The mechanism, in the parts that carry the safety:

- **The floor is three sets, not one:** impacted ∪ **previously failing** ∪ **newly added**. Impacted
  alone was the first draft and is not what regression-test-selection practice does. Previously-failing
  comes from the last recorded run's `tests.failures[]`
  ([`job_result.schema.json`](../../../schemas/job_result.schema.json)); newly-added from
  `git diff --name-only --diff-filter=A`.
- **An unmapped path resolves to `full_command`.** A changed file matching no `when` glob is unknown
  blast radius, never "nothing to run".
- **Overlapping globs union.** Every matching `run` is selected. First-match-wins would silently drop
  coverage the map explicitly declares.
- **`floor_only` means *only the floor*, never nothing.**
- **When failure identifiers are unavailable, the next run's floor falls back to `full_command`** rather
  than silently dropping the previously-failing set. An aggregate exit code cannot say *which* test
  failed, and a set that cannot be computed is not a set that can be assumed empty.
- **The CI backstop is a job that always runs and is required, dispatching internally.** "The full suite
  still runs in CI" is false as usually implemented: GitHub reports a conditionally-skipped job as
  `Success`, so a path filter can turn a required check green without running it. A backstop that a
  path filter can skip is the v2.14.1 defect wearing a different hat.

### The honest limit

**The floor is early feedback. It does not restore what the full suite guaranteed. CI does.**

The union of impacted, previously-failing and newly-added structurally omits every existing,
previously-passing test the declared map fails to select. Change `src/parser.py`, break
`tests/test_cli_integration.py` through an indirect import, and no set selects it: the floor passes, and
only the merge-blocking CI run catches it. Any wording that implies the floor preserves pre-merge safety
is wrong and must not ship — in a spec, a status line, an agent's report, or a release note.

**The known miss rate, stated with the claim.** Call-graph-derived test selection is measured at **0.2%
(class-level) to 10.6% (method-level) unsafe per revision**, from reflection and library exclusion. A
hand-written glob map carries strictly less information than a call graph — it encodes the relationships
its author remembered, where a call graph encodes the ones the code actually has. So **0.2% is an
optimistic floor, not an expectation.**

### Alternatives declined

- **Leave the v2.17 rejection standing.** Declined because the status quo it protects does not exist.
  Preserving "run everything" would be a defensible trade; preserving "run nothing, and ask a reviewer
  to say it ran" is not.
- **Build real selection — dynamic coverage or a call graph.** Declined on the line this project already
  drew in the same rejected-candidates list that killed `impacted-tests`: Compound V orchestrates and
  verifies builds, it does not index codebases. It would also buy at most the 0.2% end of the range for
  a large permanent maintenance surface, and it does not remove the need for the CI backstop.
- **Scope tests and drop the always-run CI job, on the grounds that the floor is good enough.** Declined
  — this is precisely the decision v2.17 rejected, and it stays rejected. The backstop is the entire
  reason this ADR is allowed to supersede that one.
- **Infer the impacted set from the diff automatically, with no declared map.** Declined: an inferred
  set has no author to be wrong, and therefore no author to correct it. A declared map is auditable and
  reviewable; its misses are somebody's misses.

## Consequences

- **The v2.17 rejected-candidates list now has one entry that was re-litigated.** That list says "do not
  re-litigate", and this ADR does exactly that. The precedent is narrow on purpose: a rejection is
  reopenable when the evidence it rested on has been shown to be about a different failure, and the
  reopening is recorded rather than performed quietly in a spec.
- **Every job result now carries what was actually run.** `tests: {command, exit_code, scope,
  selected_count, duration_ms, failures[]}` is added to the job-result contract, and `duration_ms` and
  `failures[]` are **measured-only** — absent rather than estimated when the runner does not report
  them. A reviewer reading "tests passed" can now see which tests.
- **A job reporting no test command at all is a FAIL, not a pass.** The reviewer becomes tier-aware, and
  the unattended auto-route class additionally requires `full_command`, because the floor alone does not
  carry the guarantee that class is trading on.
- **The map will be wrong sometimes, and the misses will be silent by construction.** A glob map rots as
  the code moves. Nothing in this decision detects a rotted map; only the CI backstop catches its
  consequences, and only at merge time. This is the accepted cost, not an oversight.
- **A slower merge signal is now normal.** Some failures that used to surface in the inner loop will
  surface in CI instead. That is the trade, stated forward.

### Falsification condition

This decision is wrong, and should be reverted to "always run everything", if any of the following is
observed:

1. **A defect reaches `main` that the full suite would have caught pre-merge and neither the scoped floor
   nor the CI backstop caught.** That is a backstop failure, which means the trade had no floor at all
   and the v2.17 rejection was right on its original terms.
2. **The map's measured miss rate on this repository exceeds 10.6%** — worse than method-level
   call-graph selection, the pessimistic end of the published range. Measurable directly: run
   `full_command` alongside the scoped set on a sample of jobs and count the failures the scoped set did
   not select. `tests.failures[]` is what makes that count possible.
3. **Scoping saves no meaningful time.** If recorded `duration_ms` shows the full suite is fast enough
   that the scoped set buys nothing, the decision has cost (a map to maintain, a miss rate to accept)
   and no benefit. Revert.
4. **The always-run CI job is ever observed reporting green without executing** — the v2.14.1 shape
   again. That falsifies the backstop, and the backstop is the load-bearing half of this ADR.

### What this does not show

The 0.2%–10.6% range is from published regression-test-selection research on **call-graph-derived**
selection, recorded in the v3.0 spec at
[§ B2, "Known miss rate, stated with the claim"](../specs/2026-09-01-v3.0-triage-tests-orchestration-design.md).
It was **not measured on this repository**, not measured on a glob map, and not measured on Compound V
at all. No measurement of this
project's own miss rate exists and none has been taken; falsifier 2 above describes how one would be. The
claim that a glob map carries strictly less information than a call graph is an argument about what the
two structures contain, not an experiment.

Nothing here establishes a time saving. No baseline duration for this repository's full suite has been
recorded — `duration_ms` is added by this release precisely so that a future claim can be made from data
instead of from expectation, and until that data exists no speed claim about scoped tests may be
published (per [ADR 0002](0002-limits-ship-with-the-claim.md)).

The always-run CI backstop is a property of the workflow configuration as written, not an observed
outcome across releases. It has not yet survived a release cycle, and a guard nobody has watched fail is
a guard nobody has confirmed works.
