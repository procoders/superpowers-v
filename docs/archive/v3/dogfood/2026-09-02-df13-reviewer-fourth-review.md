# review

Reviewed: `2026-09-02-df13-reviewer-fourth-impl.md`
(full path: `docs/superpowers/dogfood/2026-09-02-df13-reviewer-fourth-impl.md`)

REVIEW GATE: run `2026-09-02-df13-reviewer-fourth` — job `spec-review`

VERDICT: ISSUES
  PASS 1 SPEC:        ISSUES
  PASS 2 QUALITY:     ISSUES
  PASS 3 INTEGRATION: ISSUES

Ordering note: the SPEC gap below is root-caused to the dispatch pipeline, not to
the implementer's judgment, and the artifact under review is three lines. Stopping
at Pass 1 would have hidden the Pass 2 finding that explains why the gap survived
every gate, so all three passes were run.

---

## PASS 1 — SPEC

### 1.1 Scope lock

`impl-slice` wrote exactly one path, and it is the one path its lane allowed.
Gate receipt `receipts/impl-slice.gate.json` — `verdict: pass`, `violations: []`,
baseline `366262f0`, realised `366262f0`. No scope-lock violation.

### 1.2 Spec coverage

| Manifest requirement (`manifest.yaml:31-36`, job `impl-slice`) | Implemented in | Status |
|---|---|---|
| File `docs/superpowers/dogfood/…-impl.md` exists | the file, 3 lines | ✅ |
| It contains **exactly** `# impl` / blank / `Written for the reviewer to read.` | file contains `# 2026-09-02 df13 reviewer-fourth — impl slice` / blank / `Placeholder implementation artifact for the reviewer to review.` | ❌ |

ISSUE: SPEC_GAP  (PASS 1)
  - `manifest.yaml:31` declares the job's task under the key `body:`. The prompt
    renderer at `scripts/compound-v-emit-workflow.py:678` reads
    `job.get("description") or job.get("prompt") or job.get("spec")` — it never
    reads `body`. The key is silently dropped.
  - Observable consequence: `jobs/impl-slice.prompt.md` carries title,
    write-allowed, read-allowed, acceptance and the do-not-report block, and **no
    task text at all**. The same hole appears in the spawned prompt embedded at
    `dispatch.workflow.js:76`. Neither worker was ever told what to write.
  - The same loss hit this review job: `jobs/spec-review.prompt.md` and
    `dispatch.workflow.js:80` likewise carry no `body`. The required review-file
    content was recovered only by reading `manifest.yaml` directly.
  - Nothing rejects the unknown key. `scripts/compound-v-validate-manifest.py`
    enforces unknown-key rejection for `advisor` (:745), `triage` (:1758) and
    `test_contract` (:1822/:1858) — there is no equivalent check on job keys, so
    `body:` validates clean and vanishes.
  → Not an implementer fault. Fix the renderer and/or reject unknown job keys in
    the validator; a manifest key that carries the whole task must not be able to
    disappear silently.

### 1.3 Audit constraints

The manifest points all three audit slots (`manifest.yaml:8-10`) at `spec.md`,
which is a three-line stub carrying no Design Constraints section. No MUST /
MUST NOT items exist to check. Vacuous, not violated.

### 1.4 Job acceptance

| Job | Narrow acceptance | Status |
|---|---|---|
| impl-slice | "The file exists." | ✅ — and this is the whole problem: the acceptance was satisfiable without the content requirement the `body` carried |
| spec-review | "The review file exists and names the file it reviewed." | ✅ — this file, named above |

### 1.5 Over-build

None. Three lines, no extra files, no speculative helpers.

---

## PASS 2 — QUALITY

### 2.1 Code quality
Not applicable — the artifact is prose, no logic.

### 2.2 Regression
None available to break. One new file, no callers, no changed signatures.

### 2.3 Test alignment

ISSUE: TEST_GAP  (PASS 2)
  - `manifest.yaml:14-18` defines the entire test contract as `/bin/echo floor-ok`,
    `/bin/echo full` and `/bin/echo scoped`. `receipts/impl-slice.gate.json` records
    `tests.passed: true`, `tier_used: 1`, two checks at `rc: 0`.
  - Those commands exit 0 for any file content whatsoever, including an empty file.
    The manifest's only substantive requirement — the exact content in `body` — has
    no guard that could fail.
  - This is why the Pass 1 defect reached a green gate: the scope gate proved the
    right *path* was written and the test contract proved nothing about *what*.
  → A run whose acceptance is content needs one check that reads the content.

### 2.4 Fabricated metrics
None. No token counts, no savings claims, no hardcoded baselines in the diff.
The gate receipt's numbers (`selected_count: 2`, `rc: 0`) are machine-derived.

### 2.5 Reward-hacking
None. `impl-slice` touched no test, spec, scorer or threshold — its diff is a
single added doc file. The `/bin/echo` stubs came from the manifest as authored
(a dogfood harness), not from a worker weakening a check to get green. Weak
evidence, honestly obtained; not a reward hack.

---

## PASS 3 — INTEGRATION

### 3.1 Partition integrity
Clean. The two jobs' `write_allowed` sets are disjoint single files
(`…-impl.md`, `…-review.md`); no shared barrel, registry or type.

### 3.2 Cross-job seam
Holds. Wave 1 integrated at commit `eb9b9815` (`state.json:31`), and that commit
is this job's pinned baseline (`state.json:19`) — so the prerequisite was merged
**and committed** before this wave's agent ran, and the file under review was
readable in the checkout. The wave barrier did what it claims.

### 3.3 Build

ISSUE: BUILD_UNVERIFIED  (PASS 3)
  - This job's shell is clamped to `register-lane` alone
    (`dispatch.workflow.js:142`), so no build or suite could be run from here.
  - The only recorded evidence is the two `/bin/echo` invocations above, which do
    not exercise the repository.
  → Recorded green, but the green asserts nothing. Not claiming a green build.

### 3.4 Feature acceptance criteria

| Acceptance criterion (`manifest.yaml:12`) | Satisfied by / evidence | Status |
|---|---|---|
| "The review job carries agentType `superpowers-v:spec-reviewer`." | `dispatch.workflow.js:133` sets `agent_type: "superpowers-v:spec-reviewer"` on the `spec-review` job; `:364` applies it as `opts.agentType`; the dispatched prompt (`:80`) opens with "You are spawned as `superpowers-v:spec-reviewer`", and this review was produced under that role's three-pass protocol. | ✅ |

The run's one feature-level criterion is met. The run is **not DONE**: the
SPEC_GAP and TEST_GAP above are open, and the build is unverified.

---

## Summary of open issues

1. `SPEC_GAP` — manifest `body:` is silently dropped by
   `scripts/compound-v-emit-workflow.py:678`; both workers ran with no task text.
2. `TEST_GAP` — the `/bin/echo` test contract cannot fail on wrong content, which
   is what let (1) reach a green gate.
3. `BUILD_UNVERIFIED` — no runnable build evidence from this lane.

Scope lock: respected. `impl-slice` gate PASS, confirmed at the seam; this job
wrote only `docs/superpowers/dogfood/2026-09-02-df13-reviewer-fourth-review.md`.
