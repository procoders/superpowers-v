# Failure policy — three-provider cooldown recovery

Compound V handles backend failure as a deterministic, persisted pipeline. The scripts are the authority for thresholds and mutations; this runbook documents their interfaces and operator-visible behavior without duplicating their algorithms.

- [`compound-v-classify-failure.py`](../../scripts/compound-v-classify-failure.py) normalizes provider evidence.
- [`compound-v-failure-policy.py`](../../scripts/compound-v-failure-policy.py) returns an intent; it never scans or mutates a pool ring.
- [`compound-v-pool-state.py`](../../scripts/compound-v-pool-state.py) is the only authority that scans the frozen ring, leases probes, and mutates routing state.
- `compound-v-pool-state.py validate` validates the proposed state before it is atomically persisted.

The dispatcher order is fixed: **classify → decide → transition → validate → atomic persist → launch**. A launch is never allowed to race ahead of its persisted attempt, probe lease, assignment, or launch binding.

## Normalized evidence and results

The classifier returns `failure_class`, `retryable`, `matched`, `retry_after`, `retry_at`, and `network_scope`. The canonical `job_result` always carries `failure_class` and integer `retry_after_seconds`; failures may additionally carry `retry_at` and `network_scope`.

`network_scope` has two deliberately different meanings:

- `provider_reported`: the provider returned structured evidence, including z.ai code `1234`. It is backend evidence and may cool that backend.
- `no_response`: DNS, TLS, connection, or reset failure before a provider response. One observation is only a single-provider fault; correlated observations from distinct backends in the same batch may open the global network pause.

`status: success` means a final normalized worker result completed successfully. An HTTP connection, SSE connection, first token, or intermediate event is not success. Success and `blocked` results omit `retry_at` and `network_scope` and carry cleared failure/timing values. A scope-gate `blocked` result never enters backend recovery.

## Policy intent

The policy consumes a concrete backend, normalized failure evidence, retry counters/budgets, and known provider timing. It returns intent fields including `cooldown_backend`, `cooldown_reason`, `cooldown_until`, `advance_pool`, `exclude_backend`, `exclude_model`, `network_pause`, and `next_retry_at`, together with the legacy action fields. It does not accept responsibility for choosing a ring member.

Exact model exclusion is narrower than backend exclusion: `model_unavailable` excludes only the failed concrete backend/model pair, allowing another model on that backend. Auth or permanent quota exhaustion opens the existing permanent backend circuit. Transient throttling, overload, and provider-reported transport evidence create a backend-wide cooldown.

That backend-wide cooldown is intentionally conservative. CLI-process output does not identify the credential, organization, or limiter bucket, so a cooldown can temporarily sideline a healthy model or credential on the same backend. This prevents retry herds; it is **not** quota balancing. Compound V does not poll balances, estimate remaining percentages, dynamically change weights, or optimize credits.

## The 60-second ceiling

Only a known provider minimum plus deterministic jitter that is **at most 60 seconds** may be waited inline. A known `retry_at` or retry-after longer than 60 seconds is never slept inside dispatch: the pool transitions to another viable member and records the cooldown, or a non-pool/no-viable route halts resumably with the precise `next_retry_at`.

Known provider timing survives per-class or total retry-budget exhaustion. An explicit usage-window observation at the total budget ceiling persists its cooldown intent and reset time without consuming another retry or advancing the ring.

## Scenario matrix

| Observation | Persisted transition | Next behavior |
|---|---|---|
| First short `rate_limited`/`overloaded` failure (wait ≤60s) | No cooldown or ring advance | Retry the same concrete assignment exactly once after the bounded wait |
| Second short `rate_limited`/`overloaded` failure | Open backend cooldown with the current attempt id and advance intent | Transition selects another viable member; preserve known reset time |
| Explicit usage-window exhaustion | Open cooldown immediately, even on the first observation | Advance without an inline retry; at an exhausted total budget persist timing without consuming/advancing |
| Provider reset over 60s | Persist cooldown through the absolute reset | Do not sleep; reroute, or halt with `next_retry_at` |
| Provider overload | Backend-wide transient cooldown | Continue on another viable member; later recovery uses one probe |
| Exact model unavailable | Exclude the backend/model pair | Other models on that backend remain eligible |
| Confirmed auth/permanent credits failure | Open canonical permanent circuit | Exclude backend until explicit recovery; never transient-probe it |
| Stale success from an older attempt | Retain as stale evidence | It cannot clear a cooldown, network pause, or publish the current result |
| One `no_response` network fault | Record the observation without cooldown/advance | Perform the bounded same-assignment retry; do not pause the whole run |
| Correlated `no_response` faults | Open global network pause with distinct-backend/batch evidence | Stop ordinary launches until its leaseable recovery probe is due |
| Expired cooldown | Lease exactly one backend probe to one job/attempt | Other jobs keep that backend idle until probe completion/lease expiry |
| Completed leased probe success | Clear only the cooldown/pause owned by that exact attempt | Backend/network returns to normal eligibility |
| All three providers unavailable | Preserve reasons and earliest precise retry | Halt resumably; do not spin or silently select an open route |

When an expired global network pause and backend cooldowns coexist, transition leases the single global network probe first; backend probes remain idle. One attempt may not own both probe types. A lease is represented in state, not inferred from a running process.

## Attempts, results, and crash recovery

Every launch uses monotonically increasing `attempt_counter` and `attempt_id: "<job-id>:<counter>"`, plus the job's `batch_id`. Before launch the dispatcher atomically persists `jobs[id].launch_binding` with `job_id`, `attempt_id`, `batch_id`, concrete `backend`, and the attempt-specific result path.

Collection compares the result with that binding before transition or publication. The accepted attempt may publish to `results/<job-id>.json`; a mismatched older result is retained under `stale-results/<job-id>/<attempt-id>.json`. This is why stale success cannot close health state.

## Non-pool compatibility

Ordinary concrete-backend manifests still use the same classifier and policy. They omit pool context, never invoke ring selection, and keep their existing fallback behavior. They still receive the 60-second ceiling, precise resumable retry timing, completed-success rule, cooldown/circuit validation, and launch-binding protection.

Independent jobs continue when a sibling is cooled or failed. The run pauses only when global network evidence requires it or no viable backend remains. `/v:resume` revalidates persisted state and re-dispatches only incomplete work.

## Cross-references

- State and probe shapes: [`state-machine.md`](state-machine.md)
- Manifest routing contract: [`execution-manifest.md`](execution-manifest.md)
- Canonical result schema: [`job_result.schema.json`](../../schemas/job_result.schema.json)
- Dispatcher runbook: [`parallel-dispatcher.md`](../../agents/parallel-dispatcher.md)
