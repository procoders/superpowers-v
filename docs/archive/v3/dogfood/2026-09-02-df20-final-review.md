# review

Reviewed: 2026-09-02-df20-final-impl.md

Run `2026-09-02-df20-final`, job `spec-review`, three-pass Review Gate.
Reviewer baseline: `1a71bc12f92b0deec203af32fe2ac44ff384cbca`.

## VERDICT: ISSUES

| Pass | Status |
|---|---|
| PASS 1 SPEC | ✅ (against the spec the implementer was actually given) |
| PASS 2 QUALITY | ✅ with a recorded evidence caveat |
| PASS 3 INTEGRATION | ISSUES — one defect in the dispatch layer |

The implementer is clean. The defect is in Compound V's own prompt
materialization, and it is what this dogfood run surfaced.

## PASS 1 — SPEC (impl-slice)

Operative spec = `docs/superpowers/execution/2026-09-02-df20-final/jobs/impl-slice.prompt.md`,
the file the worker was handed via `--prompt-file`.

| Requirement | Evidence | Status |
|---|---|---|
| `docs/superpowers/dogfood/2026-09-02-df20-final-impl.md` exists | file present, 3 lines | ✅ |
| Wrote only inside `write_allowed` | `receipts/impl-slice.gate.json` — `verdict: pass`, `changed` == `allowed`, `violations: []` | ✅ |
| Job acceptance "The file exists." | met | ✅ |

Scope lock: respected. Git-derived, baseline `5e226de2`, one changed path.
No `SCOPE_LOCK_VIOLATION`, no `OVER_BUILD` — one file, in lane, nothing speculative.

### Content deviation — NOT charged to the implementer

`manifest.yaml:31-36` declares for `impl-slice` a `body:` requiring the file to
contain **exactly**:

```
# impl

Written for the reviewer to read.
```

The file instead reads `# Dogfood df20 — final implementation slice` / `This file is
the implementation slice for job impl-slice in run 2026-09-02-df20-final.`

This is a deviation from the manifest, but it is **not** a `SPEC_GAP` against the
implementer: that text was never delivered to it. `impl-slice.prompt.md` contains no
instruction section at all — only write-allowed, read-allowed, a one-line acceptance,
and the do-not-report block. The implementer satisfied everything it received.
Root cause is Pass 3 below.

## PASS 2 — QUALITY

| Check | Finding |
|---|---|
| Code quality | n/a — `type: docs`, prose only, no code paths |
| Regression | none — new file, no existing caller or export touched |
| Fabricated metrics | clean — the impl file states no counts, timings, savings or percentages |
| Reward-hacking | clean — no test, spec or scorer file appears in `changed[]`; no assertion removed, no threshold loosened, no skip introduced |

**Evidence caveat on the green result.** `manifest.yaml:13-18` sets the whole test
contract to `/bin/echo`: `floor_command: /bin/echo floor-ok`, `full_command: /bin/echo
full`, impacted rule `/bin/echo scoped`. The receipt's `tests.passed: true` /
`tier_used: 1` therefore certifies only that two echo commands exited 0 — it asserts
nothing about behavior. Correct for a pipeline-exercising scaffold, and recorded here
so the green is not later read as behavioral coverage. No `TEST_GAP` is charged: the
stand-ins are what the manifest itself specifies.

## PASS 3 — INTEGRATION

### 3.1 Partition integrity — ✅

`impl-slice.write_allowed = [...-impl.md]`, `spec-review.write_allowed = [...-review.md]`.
Disjoint, no overlapping glob, no shared registry or barrel. Wave 1 merged at
`1a71bc12` (`state.json`), and this job's pinned baseline is that same commit — the
gate measures against a HEAD that did not move.

### 3.2 Cross-job seam — ✅ on the artifact, ISSUE on the mechanism

The seam itself holds: `spec-review.depends_on: [impl-slice]`, the dependency merged
and committed before this job's baseline was pinned, and the file it reads was present.

### ISSUE: INTEGRATION_MISMATCH — the manifest's `body:` is silently discarded

`scripts/compound-v-emit-workflow.py:688`, inside `render_worker_prompt`:

```python
body = job.get("description") or job.get("prompt") or job.get("spec")
```

Every job in this manifest carries its instructions under `body:`. The renderer reads
`description`, `prompt`, `spec` — never `body`. The lookup misses, the `if` at line 689
is skipped, and the task text is dropped with no error. Both jobs dispatched with
their instructions missing; `impl-slice.prompt.md` and `spec-review.prompt.md` each
jump from the run header straight to the write-allowed list.

Nothing catches it on the way through:

- `skills/compound-v/execution-manifest.md:39-55` documents no instruction-text field
  at all — neither `body` nor the three aliases the renderer actually reads. The
  required per-job list at line 135 (`id`, `title`, `type`, `backend`, `isolation`,
  `run`, `write_allowed`, `read_allowed`, `acceptance`, + `model`/`tier`) has no slot
  for the task itself.
- Job-level unknown keys are deliberately not rejected
  (`compound-v-validate-manifest.py:2104`, asserted by the test at line 4467), so
  `body:` validates clean.

Failure mode: a job can pass validation, dispatch, pass its scope gate, pass its tests
and be recorded `success` while its worker was never told what to build. The worker
gets a scope lock and a one-line acceptance, and infers the rest. Here the acceptances
were "The file exists." and "The review file exists and names the file it reviewed" —
weak enough that both jobs passed anyway, which is precisely why this stayed invisible
until a run compared the delivered prompt against the manifest.

→ Fix in the dispatch layer, not in either job: make `render_worker_prompt` read the
field the schema blesses, name that field in the per-job table and the required list,
and fail closed when a job carries no instruction text.

### 3.3 Build green — NOT ASSERTED

This reviewer's Bash is clamped to the `register-lane` form alone, so the build and
suite could not be run here. Per the evidence-before-assertion rule the composite is
**not** certified green. The only test evidence in the run is the `/bin/echo` contract
described above. Whoever closes this run must run the real suite.

### 3.4 Feature acceptance criteria

| Criterion | Evidence | Status |
|---|---|---|
| "The review job carries agentType `superpowers-v:spec-reviewer`." | `dispatch.workflow.js:133` — `"agent_type": "superpowers-v:spec-reviewer"` on job `spec-review`, applied at line 364 as `opts.agentType`; corroborated by this agent's own spawn as that role | ✅ |

The run-level AC is met. The run is **not DONE**: the `INTEGRATION_MISMATCH` above is
open, and the build is unverified.
