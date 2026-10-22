# review

Reviewed: `2026-09-02-df12-reviewer-third-impl.md`

REVIEW GATE: run `2026-09-02-df12-reviewer-third` — job `impl-slice`, plus final integration

VERDICT: ISSUES
  PASS 1 SPEC:        ISSUES
  PASS 2 QUALITY:     n/a — spec failed first
  PASS 3 INTEGRATION: ✅ (feature AC met; build green NOT asserted — see 3.3)

---

## PASS 1 — SPEC (job `impl-slice`)

### Scope lock

Respected. `receipts/impl-slice.gate.json` `changed[]` is exactly
`docs/superpowers/dogfood/2026-09-02-df12-reviewer-third-impl.md`, `violations[]`
is empty, verdict `pass`, measured against baseline `366262f`. Git-derived by the
caller, not self-reported.

### Spec coverage

| Spec requirement (manifest.yaml:31-36) | Implemented in | Status |
|---|---|---|
| File `…-impl.md` exists | docs/superpowers/dogfood/2026-09-02-df12-reviewer-third-impl.md | ✅ |
| Containing **exactly** `# impl` | impl.md:1 — reads `# 2026-09-02 df12 reviewer-third — implementer slice` | ❌ |
| Containing **exactly** `Written for the reviewer to read.` | impl.md:3 — reads `This file is the implementer's slice for job \`impl-slice\`.` | ❌ |

### ISSUE: SPEC_GAP (PASS 1)

- `manifest.yaml:31-36` specifies the file's content with the words "containing
  exactly", then gives two lines. `docs/superpowers/dogfood/2026-09-02-df12-reviewer-third-impl.md:1-3`
  contains neither line. Both the heading and the body differ.
- The job's own `acceptance` is `["The file exists."]` (manifest.yaml:30), and that
  criterion **is** met. A file that exists with the wrong contents satisfies it. The
  narrow acceptance cannot see this class of drift, which is why the spec body has to
  be checked separately — that is what this pass is for.

### ISSUE: SPEC_NOT_PROPAGATED (PASS 1) — root cause, and the more serious finding

The implementer never received the spec. It is not the implementer's defect; the
owner is the emitter.

- `scripts/compound-v-emit-workflow.py:678` builds the prompt body from:
  `body = job.get("description") or job.get("prompt") or job.get("spec")`
- This run's manifest spells the key **`body:`** (manifest.yaml:31 for `impl-slice`,
  manifest.yaml:49 for `spec-review`). `body` matches none of the three accepted
  aliases, so the lookup yields `None` and the task text is dropped.
- The drop is **silent** — no error, no warning, and no validator elsewhere in
  `scripts/` requires any of the four spellings.
- Confirmed in the generated artefacts, not inferred: `jobs/impl-slice.prompt.md`
  (23 lines) carries title, lane, read-allowed, acceptance, and the do-not-report
  clause — and no task instructions. The inline prompt string at
  `dispatch.workflow.js:76` is likewise free of the body text. Same for
  `spec-review` (`dispatch.workflow.js:80`, `jobs/spec-review.prompt.md`).

Consequence for the pipeline: an implementer is dispatched with only a title and an
acceptance line. Where the acceptance is narrow, the job passes its gate, passes its
tests, merges, and the run reports success while the specified work was never
described to anyone. That is exactly this run's outcome.

→ Fix in the emitter: accept `body` (or reject a manifest whose job carries an
unrecognised content key, rather than silently dropping it). Do not fix by editing
this run's manifest to say `description:` — that hides a defect that will recur on
every manifest written to the documented shape.

### Over-build

Clean. The file is three lines; nothing speculative was added. The content is wrong,
not excessive.

---

## PASS 2 — QUALITY

Not run. Spec drift is resolved before quality by design — reviewing the construction
of content that has to be rewritten wastes the pass.

Two checks were cheap enough to run anyway, and both came back clean. Neither
constitutes a quality pass:

- **No fabricated metrics.** `results/impl-slice.json` carries no token, cost, or
  savings figure. `tests.selected_count: 2` and the `rc` values originate in the gate
  receipt, i.e. from execution, not from the worker's own account of itself.
- **No reward-hacking.** No test, spec, or scorer file appears in `changed[]`; the
  diff is one added documentation file. No assertion was removed, skipped, or loosened.
- The implementer correctly omitted `blocked` / `files_changed` / `violations` from
  its raw result, leaving them to the git-derived receipt.

---

## PASS 3 — INTEGRATION

### 3.1 Partition integrity — ✅

Write sets are disjoint: `impl-slice` owns `…-impl.md` (manifest.yaml:28),
`spec-review` owns `…-review.md` (manifest.yaml:46). No shared barrel, registry, or
redefined type. `lane-map.json` resolves the two trees to the two jobs with no overlap.

### 3.2 Cross-job seam — ✅

`spec-review` declares `depends_on: [impl-slice]` (manifest.yaml:45). `state.json`
records wave 1 merged and committed at `cee5911`; this job's pinned baseline is
`cee5911`. The prerequisite is genuinely present in the reviewing job's base — the
file was read from the checkout, not from a worktree. The wave barrier held.

### 3.3 Build green — NOT asserted

I could not run it. This job's shell is clamped to `register-lane` alone, so no build
or test command was available to me. I will not report green on evidence I did not
produce.

What I did observe: `receipts/impl-slice.gate.json` records both tier-1 checks at
`rc: 0`, `merge_blocked: false`. That evidence is weak on purpose — this run's
`test_contract` is `/bin/echo floor-ok`, `/bin/echo full`, `/bin/echo scoped`
(manifest.yaml:14-18). Those commands cannot fail. A green result here demonstrates
that the test plumbing selects and executes commands; it demonstrates nothing about
correctness. Not filed as BUILD_RED — the placeholders are appropriate for a harness
dogfood run — but the green must not be read as a passing suite.

### 3.4 Feature acceptance criteria

| Acceptance criterion (manifest.yaml:11-12) | Satisfied by / evidence | Status |
|---|---|---|
| The review job carries agentType `superpowers-v:spec-reviewer` | `dispatch.workflow.js:133` sets `"agent_type": "superpowers-v:spec-reviewer"`; `:364` wires it (`if (job.agent_type) opts.agentType = job.agent_type`); `impl-slice` holds `agent_type: null` (`:92`), confirming the mapping is role-selective off the manifest's `type: review`; and live — this job was spawned into the role and executed the three-pass gate rather than the generic implementer shape | ✅ |

The run's single feature AC is met, and the self-reference fix this run was built to
test (`plan.md:3`) holds.

---

## Why the verdict is still ISSUES

The feature AC passed. The run is nonetheless not DONE: PASS 1 carries two unresolved
issues, and there is no DONE with an open issue in any pass. The AC being narrow is
not a reason to wave the spec gap through — it is the same failure mode twice, since
a narrow acceptance is what let the content drift merge in the first place.

## Note on this review's own spec

`manifest.yaml:49-55` specifies this file's contents "exactly" as two lines. That body
reached me no more than `impl-slice`'s reached its implementer — the same
`compound-v-emit-workflow.py:678` defect. I received only the ACCEPTANCE ("The review
file exists and names the file it reviewed"), which this file satisfies in its first
two lines, and my dispatch prompt directs that my passes and verdict vocabulary come
from my own agent definition. Recording the divergence here rather than leaving it
silent, since it is the very defect under review.
