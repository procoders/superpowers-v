# 2026-09-02 df27 full-pass — Review Gate

REVIEW GATE: run `2026-09-02-df27-full-pass` — job `impl-slice` + final integration

VERDICT: **ISSUES**
  PASS 1 SPEC:        ISSUES (3)
  PASS 2 QUALITY:     ISSUES (1 — TEST_GAP)
  PASS 3 INTEGRATION: ISSUES (1 — minor seam) · feature AC 1/1 met

Reviewer role: `superpowers-v:spec-reviewer`, spawned by role at `direct` isolation.
Baseline pinned for this job: `0291e53bad0d7d555e21ee5cdb6b5ac1950d8615`.

---

## Recall

Five commands ran, in this order. All five succeeded; the script was neither missing
nor erroring. Every one of them printed the banner
`V-memory: index is 11 new / 0 removed docs behind the repo — run /v:memory-refresh`,
so **the corpus below is stale by 11 documents** and this review's recall evidence is
qualified accordingly.

**1. The conservative bridge, over the diff under review**

```
/usr/bin/python3 /Users/oleg/Dev/superpowers-v/scripts/compound-v-memory.py recall-check \
  --repo /Users/oleg/Dev/superpowers-v \
  --files docs/superpowers/dogfood/2026-09-02-df27-full-pass-impl.md \
          docs/superpowers/dogfood/2026-09-02-df27-full-pass-review.md \
  --k 5
```

Returned, verbatim:

```
recall-check: none (0/5 match on docs/superpowers/dogfood/2026-09-02-df27-full-pass-impl.md, docs/superpowers/dogfood/2026-09-02-df27-full-pass-review.md)
```

Verdict `none`, not `tighten`. No prior `blocked` / `error` / `timeout` or
scope-violation record attaches to these paths, so the escalation bridge stays shut.

**2. `search "reviewer spawned by role direct isolation recall clamp" --intent review --top 5`**

1. `dogfood/2026-09-02-df10-review.md` — PASS 3 — INTEGRATION
2. `dogfood/2026-09-02-df10-review.md` — Verdict
3. `dogfood/2026-09-02-df12-reviewer-third-review.md` — 3.4 Feature acceptance criteria
4. `specs/2026-09-01-v3.0-triage-tests-orchestration-design.md` — D5. The cross-vendor path, which is not automatically unaffected
5. `dogfood/2026-09-02-df13-reviewer-fourth-review.md` — 3.4 Feature acceptance criteria

**3. `search "impl slice wrote job title instead of specified body content spec gap dogfood" --intent review --top 5`**

1. `dogfood/2026-09-02-df21-postgate-review.md` — Spec coverage
2. `dogfood/2026-09-02-df13-reviewer-fourth-review.md` — Summary of open issues
3. `dogfood/2026-09-02-df10-review.md` — ISSUE: SPEC_GAP (PASS 1)
4. `dogfood/2026-09-02-df12-reviewer-third-review.md` — ISSUE: SPEC_NOT_PROPAGATED (PASS 1)
5. `dogfood/2026-09-02-df13-reviewer-fourth-review.md` — 1.2 Spec coverage

**4. `search "placeholder deliverable written by the workflow instead of a spawned agent" --intent review --top 5`**

1. `dogfood/2026-09-02-df21-postgate-review.md` — Spec coverage
2. `dogfood/2026-09-02-df18-direct-digest-impl.md` — df18-direct-digest — impl-slice
3. `specs/2026-09-01-v3.0-triage-tests-orchestration-design.md` — Feature E — Lane enforcement as a native deny, not a post-hoc verdict
4. `dogfood/2026-09-02-df19-clean-impl.md` — 2026-09-02-df19-clean — implementation slice
5. `dogfood/2026-09-02-df21-postgate-impl.md` — 2026-09-02-df21-postgate — impl-slice

**5. `search "review job spawn prompt omits manifest body direct isolation worktree boilerplate" --intent review --top 6`**

1. `dogfood/2026-09-02-df21-postgate-review.md` — Spec coverage
2. `dogfood/2026-09-02-df20-final-review.md` — **ISSUE: INTEGRATION_MISMATCH — the manifest's `body:` is silently discarded**
3. `dogfood/2026-09-02-df18-direct-digest-review.md` — ISSUE: SPEC_GAP (PASS 1)
4. `specs/2026-06-26-compound-v-orchestrator-prd.md` — 5.4 Isolation model (per-job, planner-decided)
5. `dogfood/2026-09-02-df12-reviewer-third-review.md` — ISSUE: SPEC_NOT_PROPAGATED (PASS 1)
6. `plans/2026-06-26-compound-v-orchestrator-v1-plan.md` — Batch B2

**What recall was worth here.** It named the exact prior finding this run reproduces
— df10, df12, df13, df18, df20 and df21 all recorded that the manifest's `body:`
never reaches the worker — which is what sent me to compare the rendered
`.prompt.md` against the string the workflow actually spawns with, instead of
charging the divergence to the implementer. Recall is evidence with a citation, not
authority: every claim below is re-verified against the code, and where the recalled
prose and the code disagreed (the recalled root cause was
`compound-v-emit-workflow.py:678/688`; the live one is
`dispatch.workflow.js:76,80`) **the code wins, and the disagreement is itself the
finding** — the fix moved the defect rather than closing it.

Two recall calls also returned zero worker prompts and zero run-directory stubs,
which is the observable half of the 3.3.2 corpus claim checked in Pass 1.

---

## Review

`docs/superpowers/dogfood/2026-09-02-df27-full-pass-impl.md` is **not accurate against
its own specification**: `manifest.yaml:32-36` says the file must contain *exactly*
`# impl` / `A red test floor once merged because nothing read the tests block.`, and
the delivered two lines are `# 2026-09-02 df27 full-pass — impl slice` /
`Writes the file the reviewer reviews.` — the job's *title*, not its *body*. The
divergence is not implementer drift and must not be charged to the implementer: the
body reaches the rendered `jobs/impl-slice.prompt.md:5-9` but is absent from
`dispatch.workflow.js:76`, which is the string actually handed to `agent()` at
`dispatch.workflow.js:369`, so the worker's entire instruction set was "the file
exists" — and it complied.

### PASS 1 — SPEC

**Scope lock.** Git-derived, from the caller's own receipt
(`receipts/impl-slice.gate.json:6`), not self-reported: verdict `pass`, mode
`worktree`, baseline `5f32ae7`, `changed` = exactly
`docs/superpowers/dogfood/2026-09-02-df27-full-pass-impl.md`, `violations: []`. That
path is the whole of impl-slice's `write_allowed` (`manifest.yaml:28`). No leak.

**Spec coverage.** This run's `spec.md` makes five checkable claims — one per fix of
the night. Checked against the code, not against the claim:

| `spec.md` claim | Verified in | Status |
|---|---|---|
| 3.3.4 — wave 1 writes *with a task body* | `jobs/impl-slice.prompt.md:5-9` carries it; `dispatch.workflow.js:76` (the spawn string, used at `:369`) does not | ❌ PARTIAL |
| 3.0.5 — a `standard` tier that resolves to Sonnet | `manifest.yaml:24` declares `tier: light`, never `standard` | ❌ NOT EXERCISED |
| 3.0.6 — a `direct`-mode reviewer spawned by role | `dispatch.workflow.js:135` `agent_type`, `:148` `isolation: direct`, `:368` `opts.agentType`; and this review is in fact executing the three-pass Gate | ✅ |
| 3.3.5 — whose clamp now admits recall | `dispatch.workflow.js:143-146` lists `search` and `recall-check`; both ran, five times, without a denial | ✅ |
| 3.3.2 — reading a corpus with the machine output removed | `compound-v-memory.py:272-287` `is_generated_run_artifact`; observed: 0 worker prompts and 0 run stubs across five recall calls | ✅ (stale index) |
| 3.3.3 — under an agent definition that tells it to | `agents/spec-reviewer.md:20-50` carries Step 0 on disk; the definition **this job was spawned with does not** | ❌ |

**ISSUE: SPEC_NOT_PROPAGATED (PASS 1)** — the headline, and the run's reason to exist.

The manifest's per-job `body` is absent from the prompt the workflow actually spawns
with, for **both** jobs:

- `dispatch.workflow.js:76` — `prompts["impl-slice"].implement` runs
  TITLE → register-lane → worktree note → WRITE-ALLOWED → ACCEPTANCE → RETURN. The
  body text (`containing exactly`, `A red test floor once merged…`) does not appear.
- `dispatch.workflow.js:80` — `prompts["spec-review"].implement`, identically, omits
  the three-section output contract at `manifest.yaml:55-68`. This reviewer never
  received it and reconstructed it by reading the manifest directly.
- `dispatch.workflow.js:369` spawns from exactly that string. `prompt_file` appears
  only as inert metadata (`:114`, `:156`); nothing in the dispatch path reads it.

The 3.3.4 fix landed in `render_worker_prompt`'s **output file** and not in the
workflow's **spawn prompt**. Recall (df12, df13, df18, df20, df21) shows this is the
sixth consecutive run to merge with the same defect, under a different line number
each time. → Fix in the workflow materializer: carry `jobs[].body` into
`CFG.prompts[<id>].implement`, or make `implementStage` read `prompt_file`.

**ISSUE: SPEC_GAP (PASS 1)**

- `docs/superpowers/dogfood/2026-09-02-df27-full-pass-impl.md:1,3` does not carry the
  content `manifest.yaml:32-36` demands.
- Owner is the emitter, per the issue above — not the implementer. Re-running
  impl-slice against the current workflow would reproduce it exactly.

**ISSUE: ACCEPTANCE_GAP (PASS 1) — the 3.0.5 claim is untestable as configured**

- `spec.md:3-4` states wave 1 runs "on a `standard` tier that resolves to Sonnet
  (3.0.5)". `manifest.yaml:24` declares `tier: light`.
- `compound-v-resolve-model.py:80` maps balanced-stance claude as
  `{"standard": "sonnet", "light": "sonnet"}`. `light → sonnet` held **before and
  after** 3.0.5; the row 3.0.5 changed is `standard`. `dispatch.workflow.js:111,113,120`
  confirms what actually resolved: `model: sonnet`, `model_source: tier`, `tier: light`.
- A green run therefore says nothing about 3.0.5. → Declare `tier: standard` on wave 1
  and re-dispatch, or drop the claim from `spec.md`.

**ISSUE: CONSTRAINT_VIOLATION (PASS 1) — the reviewer's Step 0 did not arrive**

- `agents/spec-reviewer.md:20-50` carries "## Step 0 — ask what this project already
  knows (V-memory)", including the two commands and the "never a routing input" rule.
- The definition **this job was spawned with** goes from `:18` ("Per-task you
  typically run as the SPEC pass…") straight to `:52` ("## Required inputs"). Lines
  20-51 are absent.
- I ran recall because the job's `acceptance` and the Bash clamp pointed at it, not
  because my definition instructed me to — so `spec.md:6`'s "under an agent definition
  that tells it to" is **not demonstrated by this run**. Two candidate causes, both
  worth checking before re-claiming 3.3.3: a stale installed-plugin copy of
  `agents/spec-reviewer.md` shadowing the repo copy, or the section being dropped at
  definition load. → Verify which, then re-dispatch.

**Audit constraints.** `manifest.yaml:7-10` points all three audit slots at `spec.md`,
a 10-line dogfood stub with no "Design Constraints" section. No MUST/MUST NOT items
exist. Vacuously satisfied — recorded, not credited.

**Job acceptance.** `jobs[impl-slice].acceptance` = "The file exists." ✅. Worth
stating plainly: an acceptance this loose is structurally incapable of detecting the
SPEC_NOT_PROPAGATED defect above, which is half of why it has survived six runs.

**Over-build.** None. One file, two lines, no extra flags, helpers, or files.

### PASS 2 — QUALITY

- **Code quality** — no code changed. A two-line markdown file; naming matches the
  run id. Clean.
- **No regression** — additive, docs-only. No exports, callers, or signatures.
- **Test alignment** — **ISSUE: TEST_GAP (PASS 2)**. `manifest.yaml:14-18` declares
  `/bin/echo floor-ok`, `/bin/echo full`, `/bin/echo scoped`. An `echo` cannot fail on
  wrong file content, so the contract guards *nothing* and returns rc 0 regardless of
  what the worker wrote. This is the mechanism by which SPEC_NOT_PROPAGATED reaches a
  green gate run after run. The irony is exact and self-documenting: the body that
  never arrived says *"A red test floor once merged because nothing read the tests
  block."* → A dogfood run whose point is content fidelity needs a contract that
  greps the delivered file.
- **No fabricated metrics** — the deliverable prints, logs and documents no numbers.
  Clean. This review asserts no timing or cost figure. (The measured figures at
  `compound-v-memory.py:255-259` — 71 prompts, 44 stubs, 267 files, 43% — carry a date
  and a repository and are measured values, not cost theater.)
- **No reward-hacking** — the gate receipt's `changed` list is one markdown file. No
  test, spec, scorer, threshold or timeout file was touched; nothing skipped,
  loosened, deleted or swallowed.

### PASS 3 — INTEGRATION

**Partition integrity.** Two jobs, two disjoint single-file lanes
(`manifest.yaml:28,46`). No shared barrel, registry or type. The gate receipt confirms
impl-slice touched only its own path. `preexisting/spec-review.txt:1-19` captures the
run's own bookkeeping — both `.prompt.md`, both `.baseline`, `lane-map.json`,
`state.json`, `dispatch.workflow.js`, the receipt and result files — as pre-existing at
this job's registration, so the pipeline's audit trail is excluded from my diff rather
than counted against my lane. That is the df21 behavior, and it is present.

**Cross-job seams.** `depends_on: [impl-slice]` (`manifest.yaml:45`) is honored in
fact, not merely declared: `state.json:28-32` records wave 1 `integrated: true` at
commit `0291e53`, and this job's pinned baseline is that same `0291e53`. The file under
review was committed into my base before I began. No drift, nothing consumed that was
not produced.

**ISSUE: INTEGRATION_MISMATCH (PASS 3) — worktree boilerplate on a direct job**

- `jobs/spec-review.prompt.md:24` reads "already merged and COMMITTED into your base
  **before this worktree was created**". This job is `isolation: direct`
  (`manifest.yaml:43`) and has no worktree — the spawn prompt itself says so, and warns
  that conflating the two is what made 3.0.1 apply a direct job's patch into a
  different repository.
- Cosmetic in effect here (the rendered file is not what spawns the agent, per PASS 1),
  but it is the same direct-vs-worktree confusion the run is meant to have closed.
  → Render the prerequisite line per isolation mode.

**Build.** Docs-only; nothing compiles. Stated precisely: this is an **observed
recorded result from a placeholder echo contract**, not an independently re-run suite.
`receipts/impl-slice.gate.json:13-25` records both checks at rc 0, tier 1,
`merge_blocked: false`, `failures: []`; `results/impl-slice.json:20-26` agrees. This
reviewer's shell is clamped to three commands (register-lane, `search`, `recall-check`)
and **could not re-execute the contract**. Green is not claimed beyond that evidence —
and per the TEST_GAP above, that evidence is worth very little.

**Feature acceptance criteria.**

| Criterion (`manifest.yaml:11-12`) | Satisfied by / evidence | Status |
|---|---|---|
| "The reviewer reports what V-memory returned, or that it returned nothing." | The Recall section above: five named commands, the verbatim `recall-check: none` verdict, 21 returned section titles, and the stale-index caveat. Nothing invented. | ✅ |

Feature AC: 1/1.

### Summary of open issues

1. `SPEC_NOT_PROPAGATED` (PASS 1) — `dispatch.workflow.js:76,80` omit the manifest
   `body`; `:369` spawns from those strings. Sixth run with this defect.
2. `SPEC_GAP` (PASS 1) — impl deliverable content ≠ `manifest.yaml:32-36`. Consequence
   of (1); not the implementer's.
3. `ACCEPTANCE_GAP` (PASS 1) — `spec.md:3-4` claims a `standard` tier; `manifest.yaml:24`
   declares `light`. 3.0.5 is unexercised.
4. `CONSTRAINT_VIOLATION` (PASS 1) — `agents/spec-reviewer.md:20-50` Step 0 is absent
   from the spawned definition. 3.3.3 undemonstrated.
5. `TEST_GAP` (PASS 2) — an `/bin/echo` contract cannot fail on wrong content, which is
   what lets (1) merge green.
6. `INTEGRATION_MISMATCH` (PASS 3) — worktree-phrased prerequisite line on a `direct` job.

Of the night's six fixes, **three landed and are demonstrated** (3.0.6 spawn-by-role,
3.3.5 recall clamp, 3.3.2 corpus exclusion), **one landed in the wrong renderer**
(3.3.4), **one is undemonstrated** (3.3.3), and **one was never configured into the run**
(3.0.5). The run is **not DONE**.

---

## Routing

Nothing recalled changed any routing decision: the six prior dogfood records surfaced
above were used only as evidence to re-verify against the code — every finding here is
cited to a file:line, backend/tier/model stayed exactly as
`manifest.yaml:22-27,39-44` declared them, `recall-check` returned `none` rather than
the escalation-only `tighten`, and recall is never a routing input, because that order
is deterministic and lives in `routing-policy.md`.
