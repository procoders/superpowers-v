The evidence supports making the light flow the default. It does **not** support deleting the parallel-execution safety contract. Ranked findings:

1. **Manifest validator, integration gate, lane guard — CHANGE/EXTRACT, not DELETE.** A final scope check is not equivalent to the current protections. The lane guard can refuse writes into another checkout before they happen ([implementation]); the integration gate independently checks results and rejects changes to the approved lane definition ([implementation]). “Lanes from the plan” needs a deterministic parser, pinned baseline, immutable approved lanes, per-worker attribution, and verification before integration. Removing these while retaining optional parallelism contradicts В8.

2. **`codex-review.sh` — CHANGE, not CARRY OVER.** It prompts an advisory **plan** review and launches Codex in a read-only sandbox ([prompt and invocation]). It provides neither the proposed acceptance-test execution environment nor a blocking product-review verdict. Add an isolated, provisioned checkout, executable checks, structured findings, and re-verification after fixes. Its current exit zero can include a rejection.

3. **`postdiff-reclassify.py` — RETAIN its responsibility until replaced.** Calling this “statistics” is incorrect. It checks whether the materialized diff invalidates initial triage, including sensitive paths, semantic content and Python control-flow changes ([checks]). A “small copy change” that becomes authentication logic still needs escalation. Deleting the paid classifier is defensible only with an explicit conservative fallback for unclassified requests; one successful FULL classification does not establish deterministic coverage.

4. **Engine C, resume and epics — DEPRECATE/OPTIONAL before DELETE.** The experiments justify bypassing orchestration for these workloads. They did not test interruption recovery, multi-feature dependencies, conflicting workers or partial integration. “Duplicates `/goal` and `/loop`” lacks a capability-parity demonstration. Existing unfinished runs need a supported completion path.

5. **Engine-test deletion bucket — WRONG.** It includes `sandbox-checkout`, although the helper is retained. Its tests protect tracked-only copying, exclusion of ignored artifacts, and refusal to overwrite nonempty destinations ([tests]). Split mixed suites: retain worker transport, timeout, scope and hook-failure assertions wherever the corresponding capability survives.

6. **Dense memory — DELETE is a maintenance choice, not a demonstrated “useless” verdict.** The recorded benchmark improves hit@4 from 12/23 to 13/23; cross-language/paraphrase subsets contain only four/three questions ([results]). That supports disabling this embedding implementation by default. It does not establish that dense retrieval has no value.

**Missing from the table:**

- **Actual browser verification.** “Browser / curl” permits precisely the inadequate substitute the experiment exposed. Require a browser-driven form submission and resulting persistent state; specify unavailable-browser behavior and applicability for non-web projects.
- **A mechanical completion contract.** A Stop question is insufficient. Review, browser and scope receipts must identify the checked tree and acceptance-table revision; subsequent edits invalidate them. Missing evidence, reviewer timeout and unresolved findings need explicit outcomes.
- **A routing executor and worker-result consumer.** Preserve model overrides, effort validation and backend availability checks. Retained workers return zero even for blocked/error results; somebody must interpret their structured status ([contract]).
- **Unlisted dependencies:** `emit-preflight.py`, `project-config.py`, remaining receipt schemas, agent definitions and plugin/marketplace metadata. Onboarding’s parsing cross-check currently imports the supposedly deleted manifest loader ([dependency]).
- **Archive and upgrade behavior.** `docs/archive/` is outside default memory indexing ([corpus selection]). Renaming the plugin also needs migration of command references, settings and namespaced agent memory.

**Migration sequence, highest risk first:** First extract the surviving safety contracts and port their negative tests. Then implement the light path alongside v3, with executable-review, browser, routing and stale-receipt tests. Next test upgrading a configured project and completing an interrupted v3 run. Only then switch defaults and remove engine-specific callers, code and tests together. Preserve downstream full-suite requirements: a green plugin CI does not prove the generated application passes its suite. The recursive CI sweep remains green after deleting tests, so test-count reduction alone cannot demonstrate preserved coverage ([runner]).

**Additional evidence required:** Rejudging the same builds measures judge variation, not implementation repeatability. Brownfield’s 6–9-point advantage lies within the reported noise, and its losses include specification decisions rather than isolated engine effects ([report]).

Demand three cheap checks before deletion:

- One paired holdout feature in a different existing application, with identical approved requirements, checklists and review budget.
- A synthetic parallel run: forbidden write, forged/stale receipt, worker timeout and interruption/resume. This tests safety without another product build.
- A seeded browser-form failure, skipped review, and post-review edit; completion must refuse all three.

Unused adapters and outcome-only dashboards can be removed as explicit support reductions without claiming experimental proof. Safety mechanisms need replacement tests.

Read-only inspection only; no tests were run.