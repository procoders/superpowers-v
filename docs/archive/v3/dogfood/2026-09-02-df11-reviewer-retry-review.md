# review

Reviewed: 2026-09-02-df11-reviewer-retry-impl.md

Run `2026-09-02-df11-reviewer-retry`, job `spec-review`, isolation `direct`,
baseline pinned at `b221488c5120d24e9e10857be97b3b6d6526d028`.

## VERDICT: ISSUES

| Pass | Result |
|---|---|
| PASS 1 SPEC | ISSUES — 1 finding (systemic root cause) |
| PASS 2 QUALITY | clean for what was produced |
| PASS 3 INTEGRATION | feature AC met; build-green NOT verifiable from this lane |

---

## PASS 1 — SPEC

### Coverage

| Spec requirement (manifest `jobs[impl-slice].body`) | Implemented in | Status |
|---|---|---|
| File `docs/superpowers/dogfood/2026-09-02-df11-reviewer-retry-impl.md` exists | the file, created | ✅ |
| Containing exactly `# impl` / `Written for the reviewer to read.` | file contains `# df11 reviewer-retry implementation slice` / `Placeholder artifact for the impl-slice job in run 2026-09-02-df11-reviewer-retry.` | ❌ |

Narrow job `acceptance` ("The file exists.") — ✅ met.

### ISSUE: SPEC_GAP — the job body never reached the worker

- `docs/superpowers/dogfood/2026-09-02-df11-reviewer-retry-impl.md:1-3` does not match the
  content `manifest.yaml:31-36` specifies with "containing exactly".
- Root cause is **not** the implementer. `scripts/compound-v-emit-workflow.py:678`:

  ```python
  body = job.get("description") or job.get("prompt") or job.get("spec")
  ```

  `render_worker_prompt` is the sole prompt renderer (its output is handed to the worker via
  `--prompt-file`, `scripts/compound-v-emit-workflow.py:721`). It reads `description` /
  `prompt` / `spec` and **never `body`** — the key every manifest in this repo actually uses.
- Confirmed in the rendered artifact: `jobs/impl-slice.prompt.md` carries title, lane,
  read-allowed, acceptance and the do-not-report clause, and **no task instruction at all**.
  `jobs/spec-review.prompt.md` is missing its body the same way.
- Not local to df11. `^\s*(body|description):` over `docs/superpowers/execution/**/manifest.yaml`
  returns **20 hits, all `body:`, zero `description:`**, across 12 run directories. Every
  dispatched worker in this repo has been handed a prompt that states its lane and its
  acceptance but never its task.
- No guard catches it: the job schema in `skills/compound-v/execution-manifest.md:41-55` (and
  the required-field rule at :135) documents **no instruction field at all** — neither `body`
  nor `description` — and `scripts/compound-v-validate-manifest.py` validates neither.

→ Fix the key mismatch (accept `body` in the renderer, or rename across manifests), **and**
declare the field in the manifest schema so the validator can fail closed on a job whose
instructions would render empty. The silent-drop is the defect; the content divergence is only
its first visible symptom.

### Why the run went green anyway

`acceptance: ["The file exists."]` is satisfiable without ever seeing the instruction. The
weak acceptance is what let an instruction-free dispatch report `success`. Worth tightening in
the harness fixtures — an acceptance that a body-less prompt can satisfy cannot detect this bug.

### Over-build

Clean. `impl-slice` wrote one file, inside its lane, and added nothing speculative.

---

## PASS 2 — QUALITY

- **Scope lock:** respected. `receipts/impl-slice.gate.json` — verdict `pass`, `changed` ==
  `allowed` == the single declared path, `violations: []`, git-derived against baseline
  `366262f001b765e6309c6323fe17237ec3ac9488` with `diff_digest`
  `sha256:11167306a15da5bb25e749cd0799892b7d8306fcd1bfb96252e1354e7a77f7b3`.
- **Regression:** none possible — docs-only, no code, no signatures, no callers.
- **Fabricated metrics:** none. The impl file states no numbers.
- **Reward-hacking:** none. No test, spec, scorer or threshold was touched, weakened, skipped
  or deleted in this diff.
- **TEST_GAP (noted, not charged to the implementer):** the run's `test_contract` is
  `/bin/echo floor-ok` / `/bin/echo full` / `/bin/echo scoped` (`manifest.yaml:13-18`). Those
  are harness stubs. `results/impl-slice.json` records `selected_count: 2, exit_code: 0` — a
  green that carries **no evidence about the repository**. Correct for a dogfood fixture;
  recorded here so nobody reads it as a passing suite.

---

## PASS 3 — INTEGRATION

| Feature acceptance criterion | Evidence | Status |
|---|---|---|
| The review job carries agentType `superpowers-v:spec-reviewer` | `dispatch.workflow.js:133` sets `"agent_type": "superpowers-v:spec-reviewer"` on the `spec-review` job; `:364` assigns `opts.agentType = job.agent_type`. Committed-artifact evidence, independent of self-report. This session is in fact governed by the three-pass Review Gate definition. | ✅ |

- **Partition integrity:** holds. Two jobs, disjoint single-file lanes, no shared file, no
  registry or barrel touched.
- **Seams:** `impl-slice` merged at `b221488c5120d24e9e10857be97b3b6d6526d028`
  (`state.json`, wave 1 `integrated: true`), which is this job's pinned baseline. The
  dependency ordering did what it claims.
- **BUILD GREEN — NOT ASSERTED.** This lane's Bash is clamped to the single `register-lane`
  form, so I could not run the build or the suite, and the run's only test evidence is the
  `/bin/echo` stubs above. Per the evidence-before-assertion rule I am reporting the build as
  **unverified**, not green. The merge-blocking CI run remains the authority.

---

## Disclosure

`manifest.yaml` is outside this job's advisory `read_allowed`
(`2026-09-02-df11-reviewer-retry-impl.md` only). I read it because the delivered prompt
contained no spec to review against — which is itself the PASS 1 finding. Reading the manifest
is standard for a spec gate; noting it so the deviation is on the record rather than implied.

This file exceeds the two lines `manifest.yaml:49-55` specifies, for the same reason: that
instruction never reached this worker either, and the acceptance actually delivered to this
lane was "the review file exists and names the file it reviewed" — met above. Suppressing a
systemic finding to hit a literal line count would be the wrong trade.
