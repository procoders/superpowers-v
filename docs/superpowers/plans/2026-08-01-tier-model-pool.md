# Tier Model Pools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic weighted per-tier backend pools whose manifest-order assignments are frozen in run state and preserved across resume and quota reroutes.

**Architecture:** `compound-v-project-config.py` owns fail-closed pool normalization; `compound-v-resolve-model.py` remains pure and resolves one indexed pool member through the existing model resolver. A new `compound-v-pool-state.py` owns the narrow state/assignment contract, while the manifest validator and failure policy enforce the safety boundaries before any adapter sees a concrete job.

**Tech Stack:** Python 3.9-safe standard library, YAML manifests consumed through the existing validator, Markdown executable runbooks. No new dependency, wire format, adapter, or provider call.

## Global Constraints

- PR 1 (`feat/zai-backend`, GitHub PR #5) is a merge prerequisite; do not merge this branch first.
- Pools rotate job counts by manifest ordinal; never claim equal tokens, credits, messages, wall-clock, savings, or balance scores.
- `claude` is excluded from shipped pools by default; membership remains explicit opt-in.
- Pool members are per-stance and per-tier; `model` is optional, `weight` is an integer from 1 through 100 with default 1, and an expanded tier ring is capped at 256 slots.
- Pool jobs require `worktree`, may not be reviewers or sensitive deep-only jobs, and may not use `effort: xhigh` because a pool can select a non-Codex backend.
- A member is resolved through the existing `resolve()` entry point so stance rules, optional model precedence, Opencode shape checks, and never-Haiku enforcement remain active.
- Eligible expanded members and concrete assignments are frozen in `state.json`; config edits and dispatch timing cannot change them.
- `rate_limited` retries the recorded backend. Only `out_of_credits` advances to the next viable pool member, consumes the run-level retry budget, and eventually falls through to the existing fallback chain.
- No adapter, worker, classifier, scorecard, usage extractor, or `job_result` may receive the routing token `pool`; they receive `assigned_backend` and `assigned_model`.
- Python 3.9 compatibility is mandatory: no `match`, `X | Y`, `zip(strict=)`, `itertools.batched`, or `StrEnum`.
- TDD is mandatory: each production behavior must first be demonstrated by a failing selftest, then implemented minimally and rerun green.

## Partition Map

**Parallel tasks (run concurrently):**

| Task | Files (exclusive ownership) |
|---|---|
| 1: Config, pure resolution, frozen assignment | `scripts/compound-v-project-config.py`, `scripts/compound-v-resolve-model.py`, `scripts/compound-v-pool-state.py` |
| 2: Manifest safety gate | `scripts/compound-v-validate-manifest.py` |
| 3: Quota failure semantics | `scripts/compound-v-failure-policy.py`, `scripts/compound-v-classify-failure.py` |
| 4: Dispatcher and resume contract | `agents/parallel-dispatcher.md`, `commands/v-resume.md`, `commands/v-status.md`, `skills/compound-v/state-machine.md`, `skills/compound-v/failure-policy.md` |
| 5: Public schema, routing and config docs | `skills/compound-v/execution-manifest.md`, `skills/compound-v/routing-policy.md`, `commands/v-init.md`, `commands/v-models.md`, `examples/manifest.example.yaml` |

**Serial integration phase (Task 6, after Tasks 1–5):**

- `CHANGELOG.md` — honest feature/release note after integrated behavior exists.
- `.claude-plugin/plugin.json` — post-PR1 version/description lockstep if the branch base contains PR 1.
- `.claude-plugin/marketplace.json` — same lockstep decision as plugin manifest.

**Verification:** No file appears in two rows. ✅

---

### Task 1: Config, Pure Resolution, and Frozen Assignment

**Files:**
- Modify: `scripts/compound-v-project-config.py`
- Modify: `scripts/compound-v-resolve-model.py`
- Create: `scripts/compound-v-pool-state.py`

**Interfaces:**
- Produces: `resolve_pools(cfg) -> (normalized, warnings)`, `resolve_backend_max_parallel(cfg) -> (normalized, warnings)`, and `resolve_pool(tier, index, stance, pools, config_models, effort=None, job_type=None) -> dict`.
- Produces: pool-state CLI/functions that expand weights, freeze available members once, assign by manifest ordinal, preserve the counter when members are skipped, and validate load-bearing state fields.
- Consumes: existing `resolve()` and existing config-loader conventions.

- [ ] **Step 1: Add failing config selftests**

  Extend `_selftest()` to prove structural non-object `pools`/`backend_max_parallel` raise; malformed entries warn and drop; absent keys normalize to `{}`; `model` is optional; duplicate backends, non-positive/bool/greater-than-100 weights, and members that would push an expanded tier ring past 256 slots warn and drop; `backend_max_parallel` accepts only positive non-bool integers.

- [ ] **Step 2: Run the config selftest and verify RED**

  Run: `LANG=C python3 scripts/compound-v-project-config.py --selftest`

  Expected: FAIL because the pool readers and structural checks do not exist.

- [ ] **Step 3: Implement minimal fail-closed normalization**

  Add top-level structural checks plus normalized readers. Keep the normalized shape `{stance: {tier: [{backend, optional model, weight}]}}`; never auto-detect a legacy flat pool shape.

- [ ] **Step 4: Add failing resolver selftests**

  Cover weights `2:1` yielding `A,A,B,A,A,B`; optional model resolution through `resolve()`; malformed Opencode override rejection; unknown stance/tier; unavailable member skip without shrinking positional ordinals; `xhigh` rejection for pools; and resolved Haiku surfaced to the caller.

- [ ] **Step 5: Run resolver selftest and verify RED**

  Run: `LANG=C python3 scripts/compound-v-resolve-model.py --selftest`

  Expected: FAIL because `resolve_pool()` does not exist.

- [ ] **Step 6: Implement pure indexed pool resolution**

  Expand each normalized member into consecutive weighted slots, choose from `index % len(expanded)`, and call `resolve(member.backend, tier, explicit_model=member.get("model"), ...)`. Do not store mutable iterator/counter state in this module.

- [ ] **Step 7: Create pool-state selftests before implementation**

  The new script's `--selftest` must prove: manifest-order ordinals per tier; `codex` PATH and `zai` env availability are evaluated only at freeze; an unavailable/open-circuit slot advances rather than resizing the ring; assignments persist concrete backend/model; state validation rejects a dispatched pool job missing either field; config edits after freeze do not alter assignments; resume returns recorded assignments.

- [ ] **Step 8: Run the new selftest and verify RED, then implement GREEN**

  Run before implementation: `LANG=C python3 scripts/compound-v-pool-state.py --selftest`

  Expected RED: missing functions/assertions fail. Implement only the pure JSON/state helpers and CLI needed by the executable dispatcher prose, then rerun until `SELFTEST: N ok, 0 fail` with a non-zero `N` printed.

- [ ] **Step 9: Commit Task 1**

  ```bash
  git add scripts/compound-v-project-config.py scripts/compound-v-resolve-model.py scripts/compound-v-pool-state.py
  git commit -m "feat(pool): resolve and freeze weighted tier assignments"
  ```

### Task 2: Manifest Safety Gate

**Files:**
- Modify: `scripts/compound-v-validate-manifest.py`

**Interfaces:**
- Consumes: Task 1 pool readers/resolver by the existing sibling-module seam.
- Produces: manifest acceptance for `job.backend: pool` only, plus pool-specific safety errors.

- [ ] **Step 1: Add failing validator fixtures**

  Extend the embedded selftest with fixtures for: valid worktree light/standard pool job; direct isolation rejection; reviewer rejection; `advisor_backend: pool` rejection; sensitive `security|auth|payment|pii|a11y` type rejection; deep-tier rejection; xhigh rejection; explicit manifest model rejection on pool jobs; missing/empty configured pool rejection; resolved Haiku rejection; and a legacy non-pool manifest that stays valid.

- [ ] **Step 2: Run validator selftest and verify RED**

  Run: `LANG=C python3 scripts/compound-v-validate-manifest.py --selftest`

  Expected: new valid fixture fails on unknown backend and negative fixtures lack their pool-specific messages.

- [ ] **Step 3: Implement the scoped routing token**

  Keep `VALID_BACKENDS` concrete. Add a separate `POOL_BACKEND = "pool"` used only for `job.backend`; validate pool config and resolved models through Task 1; never make pool legal for advisor configuration. Enforce pool⇒worktree, non-reviewer, standard/light only, non-sensitive, no explicit manifest model, no xhigh, and resolved never-Haiku.

- [ ] **Step 4: Prove existing validation is unchanged**

  Run:
  ```bash
  LANG=C python3 scripts/compound-v-validate-manifest.py --selftest
  for f in examples/*.yaml docs/superpowers/execution/*/manifest.yaml; do
    python3 scripts/compound-v-validate-manifest.py "$f"
  done
  ```

  Expected: selftest reports checked count with 0 failures; every pre-existing manifest exits 0.

- [ ] **Step 5: Commit Task 2**

  ```bash
  git add scripts/compound-v-validate-manifest.py
  git commit -m "feat(pool): enforce pooled manifest safety invariants"
  ```

### Task 3: Quota Failure Semantics

**Files:**
- Modify: `scripts/compound-v-failure-policy.py`
- Modify: `scripts/compound-v-classify-failure.py`

**Interfaces:**
- Consumes: concrete assigned backend only; optional ordered `pool_members` and current member index for `out_of_credits`.
- Produces: a reroute decision to the next viable member, or existing fallback/halt, with run-level budget and reset-time data preserved.

- [ ] **Step 1: Add failing failure-policy selftests**

  Prove `rate_limited` retries the same assignment and does not clear it; `out_of_credits` selects the next viable pool member and circuit-breaks only the exhausted concrete backend; pool reroute increments/consumes total retries across member changes; pool exhaustion uses the ordinary concrete-backend fallback; unavailable/open members are skipped; terminal halt carries the earliest known reset time.

- [ ] **Step 2: Run policy selftest and verify RED**

  Run: `LANG=C python3 scripts/compound-v-failure-policy.py --selftest`

  Expected: FAIL because the pool-aware arguments/results are absent.

- [ ] **Step 3: Implement the minimal additive decision API**

  Preserve all existing `decide()` callers and result keys. Add optional pool context and fields such as `next_pool_index`, `consume_total_retry`, and `earliest_reset_seconds`; never add `pool` to `FALLBACK`.

- [ ] **Step 4: Add classifier regression cases first**

  Extend concrete backend CLI choices to every worker backend shipped after PR 1, while proving `pool` remains rejected. Classification may reuse generic needles; it must never be invoked with the routing token.

- [ ] **Step 5: Run both selftests GREEN**

  Run:
  ```bash
  LANG=C python3 scripts/compound-v-failure-policy.py --selftest
  LANG=C python3 scripts/compound-v-classify-failure.py --selftest
  ```

  Expected: both report a positive checked count and 0 failures.

- [ ] **Step 6: Commit Task 3**

  ```bash
  git add scripts/compound-v-failure-policy.py scripts/compound-v-classify-failure.py
  git commit -m "feat(pool): reroute exhausted assignments within their pool"
  ```

### Task 4: Dispatcher and Resume Contract

**Files:**
- Modify: `agents/parallel-dispatcher.md`
- Modify: `commands/v-resume.md`
- Modify: `commands/v-status.md`
- Modify: `skills/compound-v/state-machine.md`
- Modify: `skills/compound-v/failure-policy.md`

**Interfaces:**
- Consumes: Task 1 pool-state CLI and Task 3 policy output.
- Produces: one byte-consistent execution rule: resolve/freeze before launch; use assigned concrete backend everywhere; resume from state; report integer assignment counts.

- [ ] **Step 1: Add the assignment lifecycle to the dispatcher**

  Before launch, freeze pool members once, compute ordinal from manifest order among pool jobs of the same tier, write `assigned_backend`/`assigned_model`, and pass only those concrete fields to resolver/advisor/classifier/worker/scope-gate/usage/memory. Respect `backend_max_parallel` as a documented batch ceiling, without claiming a new deterministic enforcement gate.

- [ ] **Step 2: Define retry and resume without re-derivation**

  Preserve assignment for transient retries; on `out_of_credits`, record the circuit and next assignment before relaunch; on resume, require and validate recorded assignment and reuse its worktree. Copy the authoritative resume wording byte-for-byte into all three documented locations.

- [ ] **Step 3: Make status output honest**

  Render counts like `codex 3 · zai 2`, not percentages; use concrete assignments for resolution/usage rows; display the earliest reset time when the pool is exhausted.

- [ ] **Step 4: Run lockstep/document checks**

  Run `LANG=C python3 scripts/compound-v-lint-frontmatter.py` and the repository dead-link check from `.github/workflows/validate.yml`.

- [ ] **Step 5: Commit Task 4**

  ```bash
  git add agents/parallel-dispatcher.md commands/v-resume.md commands/v-status.md skills/compound-v/state-machine.md skills/compound-v/failure-policy.md
  git commit -m "docs(pool): freeze dispatch assignments across resume"
  ```

### Task 5: Public Schema, Routing, and Config Docs

**Files:**
- Modify: `skills/compound-v/execution-manifest.md`
- Modify: `skills/compound-v/routing-policy.md`
- Modify: `commands/v-init.md`
- Modify: `commands/v-models.md`
- Modify: `examples/manifest.example.yaml`

**Interfaces:**
- Consumes: Tasks 1–4 exact field names and invariants.
- Produces: user-facing config/manifest contract and a validator-backed example.

- [ ] **Step 1: Document exact config and manifest shapes**

  Add per-stance `pools.<stance>.<tier>[]`, optional member `model`, bounded `weight` (1–100; expanded tier ring ≤256 slots), top-level `backend_max_parallel`, `backend: pool` restrictions, concrete state fields, and merge dependency on PR 1. State that `/v:models` refreshes `models` and preserves pool overrides rather than rewriting them.

- [ ] **Step 2: Document routing/trust policy**

  Pool is explicit operator configuration, never an automatic downgrade; only standard/light non-sensitive implementers qualify. Shipped defaults/example use Codex + zai and omit Claude. Explain job-count rotation and its non-metrics, including z.ai's time-of-day multiplier caveat.

- [ ] **Step 3: Add a validating example**

  Extend `examples/manifest.example.yaml` with a pool-routed non-reviewer job only if the repository validator can resolve its pool config without making every checkout depend on local secrets. Otherwise provide the pool example in prose and keep the CI manifest concrete; do not create a fixture that is environment-dependent.

- [ ] **Step 4: Verify docs and manifests**

  Run the manifest sweep and dead-link guard. Expected: every tracked manifest checked, 0 errors; a deliberately injected invalid pool fixture is found by the validator selftest.

- [ ] **Step 5: Commit Task 5**

  ```bash
  git add skills/compound-v/execution-manifest.md skills/compound-v/routing-policy.md commands/v-init.md commands/v-models.md examples/manifest.example.yaml
  git commit -m "docs(pool): publish tier pool configuration and routing contract"
  ```

### Task 6: Serial Integration, Release Note, and Full Verification

**Files:**
- Modify: `CHANGELOG.md`
- Modify only after PR 1 is present in the branch base: `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`

**Interfaces:**
- Consumes: all prior task behavior and PR 1's released zai backend metadata.
- Produces: honest public release description and a branch ready for review/PR.

- [ ] **Step 1: Integrate and run targeted acceptance tests**

  Run every changed script's `--selftest`, then exercise a six-job `2:1` fixture, unavailable-member fixture, state freeze/edit/resume fixture, invalid direct/reviewer/advisor/Haiku manifests, and pool `out_of_credits` reroute fixture. Each harness must print a non-zero checked count and 0 failures; temporarily inject one invalid field and confirm the gate reports it before restoring the fixture.

- [ ] **Step 2: Write the changelog from measured behavior**

  Describe deterministic weighted job-count rotation, frozen assignments, resume and quota fallback. Include a “What this does not show” paragraph naming tokens, credits, messages, wall-clock, savings and balanced quota as unmeasured.

- [ ] **Step 3: Resolve release lockstep after rebasing/merging PR 1**

  If PR 1 is now in the base, set the next version in both plugin manifests and CHANGELOG together. If it is not, leave the current version files untouched and make the PR explicitly dependent; do not manufacture a release order that contradicts Git history.

- [ ] **Step 4: Run full repository verification**

  Reproduce `.github/workflows/validate.yml` locally where available: all Python `--selftest` scripts under `LANG=C`, manifest sweep with a checked count, frontmatter lint, dead-link scan, JSON/schema checks, and `git diff --check`. Record exact counts and exit codes.

- [ ] **Step 5: Run independent spec and quality reviews**

  Review the complete diff against all 12 acceptance criteria and the three audit constraint sections. Fix Critical/Important findings, rerun the affected tests, then run one final whole-branch review.

- [ ] **Step 6: Commit integration**

  ```bash
  git add CHANGELOG.md .claude-plugin/plugin.json .claude-plugin/marketplace.json
  git commit -m "docs(pool): release deterministic tier model pools"
  ```

- [ ] **Step 7: Push and open PR 2**

  Push `feat/tier-model-pool`, open a PR against `main`, mark PR #5 as a merge prerequisite in the body, paste exact verification counts, and avoid claiming PR 1 is merged until GitHub reports it merged.
