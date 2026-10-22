# review

Reviewed: `docs/superpowers/dogfood/2026-09-02-df18-direct-digest-impl.md`
(the deliverable of job `impl-slice`, run `2026-09-02-df18-direct-digest`).

REVIEW GATE: run 2026-09-02-df18-direct-digest — df18 direct digest

VERDICT: ISSUES
  PASS 1 SPEC:        ISSUES (1 — SPEC_GAP, root cause in the harness, not the implementer)
  PASS 2 QUALITY:     ✅
  PASS 3 INTEGRATION: ✅ (feature acceptance criterion met, with evidence)

## PASS 1 — SPEC

Scope lock: respected. The gate receipt
(`docs/superpowers/execution/2026-09-02-df18-direct-digest/receipts/impl-slice.gate.json:6`)
is git-derived and reports `verdict: pass`, `changed` == `allowed` ==
`["docs/superpowers/dogfood/2026-09-02-df18-direct-digest-impl.md"]`, `violations: []`,
against baseline `5e226de`. No path outside the lane.

| Spec requirement (manifest.yaml:31-36, job `impl-slice` `body`) | Implemented in | Status |
|---|---|---|
| File `docs/superpowers/dogfood/…-impl.md` exists | the file, 3 lines | ✅ |
| Containing exactly `# impl` / `Written for the reviewer to read.` | file line 1 reads `# df18-direct-digest — impl-slice`; line 3 reads `Placeholder deliverable for job …` | ❌ |

Audit constraints: the manifest points `archaeology`, `domain` and `library` all at
`spec.md` (manifest.yaml:8-10), which is a 3-line run description carrying no
"Design Constraints" section. There are no MUST/MUST NOT items to check. Nothing
unsatisfied, and nothing was audited — recorded so the clean line is not read as
three passing audits.

Job acceptance (`impl-slice`): "The file exists." — met.

Over-build: none. Three lines, no extra files, no speculative helpers.

### ISSUE: SPEC_GAP (PASS 1)

- `docs/superpowers/dogfood/2026-09-02-df18-direct-digest-impl.md:1,3` — content does not
  match the exact text the manifest's `body` demanded (manifest.yaml:32-36).
- Root cause, and why this is not the implementer's fault: the instruction never
  reached the worker. `scripts/compound-v-emit-workflow.py:688` renders the task body
  from `job.get("description") or job.get("prompt") or job.get("spec")` — it never reads
  `body`. This manifest uses `body:` for both jobs, so both prompts were emitted without
  their task text. `docs/superpowers/execution/2026-09-02-df18-direct-digest/jobs/impl-slice.prompt.md`
  confirms it: title, lane, acceptance, the no-fabrication clause — and no task.
- The key is not caught either. `body` is not a documented job field in
  `skills/compound-v/execution-manifest.md`, and the validator deliberately rejects no
  unknown job keys (`scripts/compound-v-validate-manifest.py:2104-2107`, "NO unknown-key
  rejection is introduced anywhere in this validator"). A misspelled or undocumented
  instruction key therefore vanishes silently, and every downstream signal stays green:
  the worker writes something plausible, the narrow acceptance ("the file exists") passes,
  the scope gate passes, the tests pass. This run is the demonstration.
- → Fix in the manifest or the emitter, not in the deliverable: rename `body:` to
  `description:` in this manifest, and either teach `render_worker_prompt` to accept
  `body` as a fourth alias or have the validator warn when a job carries an
  instruction-shaped key the emitter will not read. Do not "fix" this by relaxing the
  impl job's acceptance to match what was written.

## PASS 2 — QUALITY

- Code quality: n/a in substance — the deliverable is a 3-line Markdown placeholder.
  It is well-formed, names its job and run, and claims nothing it does not deliver.
- Regression: none possible. The file is new (git-derived `changed` list, one added path).
- Test alignment: the run's `test_contract` is `/bin/echo` placeholders (manifest.yaml:14-18).
  No requirement here has a guard test, and none could — there is no behavior to guard.
  Flagged as a fact about this dogfood run, not charged as a TEST_GAP against the job.
- Fabricated metrics: none. No token counts, no savings figures, no invented percentages
  anywhere in the deliverable or the run's own bookkeeping.
- Reward-hacking: none. No test, spec, scorer or threshold was touched by the diff; the
  only changed path is the new deliverable itself.

## PASS 3 — INTEGRATION

- Partition integrity: no leak. Two jobs, disjoint `write_allowed` lists (manifest.yaml:28,46);
  `lane-map.json` resolves the checkout root to `spec-review` and `wf_c37ab0b0-dc5-1` to
  `impl-slice`. Nothing is written by both.
- Cross-job seam: `spec-review`'s `read_allowed` names exactly the file `impl-slice` produced,
  and `depends_on: [impl-slice]` ordered them. The dependency was honoured — `state.json`
  shows `impl-slice` merged and committed as `b16f557` before this job's baseline was pinned
  at that same commit, so the reviewer read a committed tree, not a worktree in flight.
- Build: the receipt records both checkers at `rc: 0`, `merge_blocked: false`. Stated
  plainly: those checkers are `/bin/echo floor-ok` and `/bin/echo scoped`. This proves the
  test-selection plumbing ran and reported honestly; it is not evidence that the repository
  builds, and must not be read as such.

| Feature acceptance criterion (manifest.yaml:12) | Satisfied by / evidence | Status |
|---|---|---|
| The review job carries agentType `superpowers-v:spec-reviewer` | `dispatch.workflow.js:133` sets `agent_type` on the `spec-review` item; `:364` passes it as `opts.agentType`. Independent confirmation that these spawn options were live for *this* agent: the run's `implement_clamp` (`dispatch.workflow.js:141-143`) allows only the `register-lane` Bash form, and this agent's first non-conforming Bash call was refused by the harness naming `bashCommandClamp` — the sibling option from the same `opts`. | ✅ |

The feature-level criterion is met. DONE is nonetheless withheld: the PASS 1 SPEC_GAP is
open, and there is no DONE with an open issue in any pass.
