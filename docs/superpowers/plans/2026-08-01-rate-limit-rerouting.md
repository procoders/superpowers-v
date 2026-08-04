# Provider Cooldown and Failure Rerouting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make three-provider pool dispatch survive rate limits, reset windows, overload, model exclusions, and temporary internet loss without long foreground sleeps, retry storms, stale recovery, or pool reordering.

**Architecture:** `compound-v-failure-policy.py` remains the sole policy decision engine and emits transition intent without scanning the pool. `compound-v-pool-state.py` is the sole executable authority for cooldown/network validation, frozen-ring viability, attempt identities, half-open leases, and exact next assignment. The dispatcher performs policy → state transition → validation → atomic persistence → launch; workers and the collector only transport normalized evidence.

**Tech Stack:** Python 3.9-safe standard library, Bash 3.2 worker wrappers, JSON state/schema, Markdown runbooks. No provider HTTP client, quota polling, new dependency, or fabricated health/capacity metric.

**Spec:** [`docs/superpowers/specs/2026-08-01-rate-limit-rerouting-design.md`](../specs/2026-08-01-rate-limit-rerouting-design.md)

**Audits:** [`archaeology`](../archaeology/2026-08-01-rate-limit-rerouting.md), [`domain`](../expert/2026-08-01-rate-limit-rerouting.md), [`library`](../library-audit/2026-08-01-rate-limit-rerouting.md)

## Global Constraints

- Merge order is PR 1 (`feat/zai-backend`) → PR 2 (`feat/tier-model-pool`) → this PR; do not hide or automatically merge the stacked prerequisites.
- `MAX_INLINE_WAIT_SECONDS = 60`; no process may foreground-sleep longer, including non-pool callers.
- The frozen weighted ring is never resized, reordered, or reweighted because of health, quota, latency, or inferred capacity.
- `out_of_credits` and `auth` keep the permanent breaker behavior; transient cooldown, resettable usage window, exact model exclusion, and global network pause are distinct state.
- Only an exact leased half-open attempt can clear its cooldown. A pre-cooldown in-flight success cannot.
- Only `network_scope: no_response` evidence can contribute to global internet correlation. A valid provider response, including z.ai 1234, is `provider_reported`.
- Cross-provider relaunches monotonically increment run `total_retries`; resume never resets it.
- All timestamps are strict aware UTC. Normalize a terminal `Z` to `+00:00` before Python 3.9 `datetime.fromisoformat`; reject naive timestamps, booleans, NaN, Infinity, and negative delays.
- Bash stays 3.2-compatible. Python stays 3.9-compatible. No `match`, `X | Y`, `zip(strict=)`, arrays, or `${var,,}`.
- Tests must report a positive checked count and zero failures, and negative controls must demonstrate that injected defects are detected.
- TDD is mandatory: add the failing assertion/fixture first, record RED, implement the smallest behavior, then record GREEN.

## Partition Map

**Serial shared foundation:**

| Task | Files (exclusive ownership) |
|---|---|
| 0: Time and result wire contract | `scripts/compound-v-provider-time.py`, `schemas/job_result.schema.json`, `examples/job_result.example.json`, `skills/backend-launcher/SKILL.md` |

**Parallel batch after Task 0:**

| Task | Files (exclusive ownership) |
|---|---|
| 1: Provider classification and result transport | `scripts/compound-v-classify-failure.py`, `scripts/compound-v-collect-results.py`, `scripts/compound-v-run-codex-worker.sh`, `scripts/compound-v-run-zai-worker.sh`, `scripts/compound-v-run-cursor-worker.sh`, `scripts/compound-v-run-antigravity-worker.sh`, `scripts/test-zai-worker-stub.sh` |
| 2: Pure failure-policy intent | `scripts/compound-v-failure-policy.py` |
| 3: Cooldown, probe, network, and assignment state | `scripts/compound-v-pool-state.py` |
| 4: Dispatcher, resume, and status integration | `agents/parallel-dispatcher.md`, `commands/v-resume.md`, `commands/v-status.md`, `scripts/compound-v-dashboard.py` |

**Serial integration after Tasks 1–4:**

| Task | Files (exclusive ownership) |
|---|---|
| 5: Authoritative runbooks and release note | `skills/compound-v/failure-policy.md`, `skills/compound-v/state-machine.md`, `skills/compound-v/execution-manifest.md`, `skills/backend-launcher/adapter-codex.md`, `skills/backend-launcher/adapter-claude.md`, `skills/backend-launcher/adapter-zai.md`, `CHANGELOG.md` |

**Verification:** No file appears in two rows. ✅

---

### Task 0: Strict Time and Result Wire Contract

**Interfaces:** Produces `parse_utc_timestamp(value, field)`, `format_utc_timestamp(value)`, `parse_delay(value, field)`, and optional `job_result.retry_at` / `job_result.network_scope`. All later tasks consume these exact names.

- [ ] Add `compound-v-provider-time.py --selftest` cases first for `Z`, offsets normalized to `Z`, naive/malformed timestamps, bool/negative/non-finite delays, and JSON `NaN`/`Infinity`. Running the absent script is the initial RED.
- [ ] Implement strict Python 3.9 helpers. The parsing core is:

  ```python
  normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
  parsed = datetime.datetime.fromisoformat(normalized)
  if parsed.tzinfo is None or parsed.utcoffset() is None:
      raise ValueError("%s must be timezone-aware" % field)
  return parsed.astimezone(datetime.timezone.utc)
  ```

- [ ] Extend the schema enum with `usage_window_exhausted` and `model_unavailable`; add nullable RFC3339 `retry_at` and nullable enum `network_scope: no_response|provider_reported`; reject negative delay. Update the example success result with neither optional failure field.
- [ ] Document the additive wire fields and success/blocked omission rule in the launcher contract.
- [ ] Run `LANG=C python3 scripts/compound-v-provider-time.py --selftest` and schema/collector selftests; expect positive counts and zero failures.
- [ ] Commit: `git commit -m "feat(routing): define strict provider failure timing contract"`.

### Task 1: Provider Classification and Result Transport

**Interfaces:** Classifier continues returning `failure_class`, `retryable`, `matched`, `retry_after`, plus `retry_at` and `network_scope`. Collector and four worker emitters preserve those optional fields without inventing them.

- [ ] Add failing classifier cases for full z.ai messages both with and without numeric codes: 1302 throttle, 1305 overload, 1308/1310/1316–1321 resettable window, 1311 model unavailable, 1113 credits, 1309/1314 expiry, 1313 policy action, 1315 auth/product mismatch, and 1234 provider-reported network error. Add OpenAI/Anthropic-style Retry-After/reset strings and true DNS/TLS/connect/reset no-response cases.
- [ ] Assert full-message matching, not code-only matching. In particular:

  ```python
  expect("zai 1234 is not global-offline evidence",
         classify("zai", "[1234] Network error")["network_scope"]
         == "provider_reported")
  ```

- [ ] Run classifier selftest and verify the new cases RED, then minimally add ordered provider-specific needles/parsers so permanent and reset-window classes win over generic `network`/`other`.
- [ ] Add collector RED cases proving strict validation, omission on success/blocked, and exact passthrough on errors. Implement optional arguments/serialization through the shared time helper.
- [ ] Update each external worker emitter without changing enforcement fields or success semantics. Extend the z.ai stub to inspect an emitted reset-window and 1234 result.
- [ ] Run classifier, collector, worker syntax checks, and `scripts/test-zai-worker-stub.sh`; expect positive counts and zero failures.
- [ ] Commit: `git commit -m "feat(routing): normalize provider cooldown and network evidence"`.

### Task 2: Pure Failure-Policy Intent

**Interfaces:** Extend `decide()` additively with pool-routing, assignment, attempt, retry/reset, and summarized network inputs. It must not accept or scan `pool_members`. Output retains legacy keys and adds `cooldown_backend`, `cooldown_reason`, `cooldown_until`, `advance_pool`, `exclude_backend`, `exclude_model`, `network_pause`, and `next_retry_at` intent fields.

- [ ] Add RED tests for first short retry, second pooled cooldown+advance, immediate usage-window advance, exact model exclusion, >60-second pooled reroute, >60-second non-pool resumable halt, permanent breaker preservation, single-network bounded retry, correlated-network pause, and monotonic budget exhaustion.
- [ ] Assert the boundary explicitly:

  ```python
  d = decide("rate_limited", "zai", 0, 0, 12,
             retry_after=61, pool_routed=False, jitter=False)
  check("never sleep 61s", d["action"], "halt",
        d["backoff_seconds"] == 0 and bool(d["next_retry_at"]))
  ```

- [ ] Replace policy-side ring scanning with intent. First short transient returns `retry`; the second or a reset-window returns cooldown+`advance_pool`; `model_unavailable` returns exact backend/model exclusion; permanent failures retain reason-specific circuit intent.
- [ ] Preserve existing non-pool decisions byte-for-byte where delay ≤60. Cap any emitted `backoff_seconds` at 60; carry a precise absolute `next_retry_at` when known.
- [ ] Run the full policy selftest and a negative control that temporarily raises the inline cap; it must be detected.
- [ ] Commit: `git commit -m "feat(routing): decide bounded retry and cooldown transitions"`.

### Task 3: Canonical Cooldown, Probe, Network, and Assignment State

**Interfaces:** Extend the JSON CLI with `transition` and `clear-cooldown` while retaining `freeze|validate|resume|select`. `transition` consumes `{state,jobs,job_id,intent,now,batch_id,job_timeout_seconds,grace_seconds}` and returns `{state,action,assignment,next_retry_at}`. This module alone scans frozen slots and owns atomic-state validity.

- [ ] Add RED state tests for the canonical object fields `until`, `reason`, `opened_at`, `opened_by_attempt_id`, and `probe.{status,owner_job_id,owner_attempt_id,lease_until}`; legacy bare timestamp only at an explicit migration helper; unknown/new bare strings fail closed.
- [ ] Add RED selection tests proving active cooldown/open circuit/exact model exclusion skip without ring mutation, two cooling + one healthy selects deterministically, and all unavailable returns the earliest absolute retry without looping.
- [ ] Add RED concurrency tests proving unique persisted launch `attempt_id`, one half-open lease, exact leased success clears, stale success does not, transient probe failure renews, permanent probe failure opens the existing circuit, and liveness reconciliation precedes lease reclaim.
- [ ] Add RED network tests for evidence `{backend,job_id,attempt_id,batch_id,observed_at}`, backend+attempt dedupe, same-batch/two-provider/60-second correlation, completed-success veto, z.ai 1234 exclusion, stale evidence rejection, and exactly one real-job network probe.
- [ ] Implement validation and transitions with bounded scans (`<= len(frozen_members)`) and no sleeps. Generate attempt IDs before launch and persist transition output atomically at the caller seam.
- [ ] Implement `clear-cooldown` to validate a known backend, remove transient cooldown only, never alter `circuit_open`, validate the result, and return the replacement state.
- [ ] Run `compound-v-pool-state.py --selftest`; then run seven mutation/negative controls for disabled skipping, long sleep, stale clear, double probe, z.ai no-code classification fixture, z.ai 1234 offline evidence, and network probe fan-out. Each must be caught.
- [ ] Commit: `git commit -m "feat(routing): persist cooldown probes and network pause state"`.

### Task 4: Dispatcher, Resume, and Status Integration

**Interfaces:** Dispatcher consumes Task 2 intent and Task 3 transition output in the only allowed sequence: classify → decide → transition → validate → atomic `state.json.tmp` replacement → launch. Dashboard/status only read validated state.

- [ ] Add dashboard RED fixtures for transient cooldown, usage-window reset, permanent circuit, network pause, probe owner, and exact `/v:resume --clear-cooldown <backend>` recovery command; assert no percentage, score, quota, or savings claim.
- [ ] Rewrite dispatcher prose with exact attempt/batch identity lifecycle, completed-success definition, bounded inline retry, one transition authority, atomic persistence, and launch prohibition after failed validation.
- [ ] Specify resume: validate first; reconcile git-wins/liveness; never launch through active cooldown/pause; expiry grants one serialized probe; preserve `total_retries`; support `--clear-cooldown <backend>` only through the helper.
- [ ] Implement dashboard rendering from canonical fields and keep old state rendering compatible.
- [ ] Run dashboard selftest, frontmatter lint, and targeted `rg` consistency checks across the three integration docs. Inject a far-future cooldown and prove the exact recovery command appears.
- [ ] Commit: `git commit -m "feat(routing): integrate resumable cooldown dispatch"`.

### Task 5: Authoritative Runbooks and Release Note

**Interfaces:** Copy the implemented names and state shapes from Tasks 0–4; do not introduce a second algorithm in prose.

- [ ] Update failure-policy and state-machine runbooks with the scenario matrix: first/second failure, long reset, overload, exact model exclusion, permanent failure, stale success, single-provider network fault, correlated offline pause, recovery probe, all-three unavailable.
- [ ] Update execution and backend adapter contracts with optional result fields, provider-reported versus no-response distinction, the 60-second ceiling, completed-success meaning, and non-pool compatibility.
- [ ] Add a CHANGELOG entry stating the conservative trade-off: backend-wide transient cooldown can temporarily sideline healthy credentials/models, but prevents herd retries; no quota-aware balancing or dynamic weights are claimed.
- [ ] Run dead-link validation with a deliberately injected missing target, then the full manifest/selftest sweep. Expected: injected target detected; tracked docs report zero dead links; all tests positive-count/zero-fail.
- [ ] Commit: `git commit -m "docs(routing): explain three-provider cooldown recovery"`.

### Task 6: Final Integration and PR Gate

- [ ] Run every Python `--selftest` discovered from `.github/workflows/validate.yml`, all Bash suites, manifest validation, `git diff --check`, frontmatter lint, dead-link check, and schema validation. Record checked counts, not merely exit zero.
- [ ] Run injected-error controls independently and prove each harness catches the defect.
- [ ] Review all changes against the 20 spec acceptance criteria and the three audits; scan for `TODO|TBD|placeholder`, duplicate policy algorithms, long `sleep`, and provider-health percentage claims.
- [ ] Request code review, address findings using `superpowers:receiving-code-review`, rerun the full gate, then use `superpowers:finishing-a-development-branch` to push and open the stacked PR.
- [ ] PR description must explicitly explain: the three-provider failure matrix; first retry/second reroute; cooldown and one half-open probe; run-level budget; permanent breaker distinction; >60-second no-hang behavior; temporary internet/global pause; `provider_reported` versus `no_response`; conservative backend-wide trade-off; no quota-aware balancing; non-pool compatibility; and PR 1 → PR 2 → PR 3 merge order.

## Acceptance-Criteria Traceability

Tasks 1–4 implement and test spec AC 1–20. Task 3 owns AC 6–17 state/concurrency invariants; Task 2 owns AC 1–5, 9, 12, and 18 policy boundaries; Task 1 owns AC 4, 14, and 17 input normalization; Task 4 owns AC 15–19 dispatch/status behavior. Tasks 5–6 independently verify documentation and all seven negative-control families required by AC 20.
