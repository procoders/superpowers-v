# Provider cooldowns and pool rerouting (PR 3 of 3)

**Goal:** keep a tier-model-pool run productive when one of three independent model providers is
temporarily throttled, overloaded, window-exhausted, or unreachable, without turning a transient
failure into a retry storm, silently changing the frozen weighted ring, or sleeping the
orchestrator for hours or days.

**Merge prerequisites:** PR 1 supplies the concrete `zai` backend; PR 2 supplies deterministic
weighted pools and frozen concrete assignments. This PR is intentionally stacked on both and must
merge after them. The implementation branch may carry their commits while they are open; that is
not a claim that either prerequisite has merged.

**Architecture:** the deterministic failure-policy script remains the sole **policy** decision
engine: given one normalized failure and retry budgets, it decides retry, advance-pool, permanent
fallback, or halt and emits a transition intent. `compound-v-pool-state.py` is the sole executable
authority for frozen-slot viability, cooldown/network validation, half-open lease acquisition, and
the exact next assignment. The dispatcher serializes intent application → pool-state transition →
validation → atomic state persistence → launch. Neither policy nor Markdown performs a second ring
scan. Workers continue to classify captured CLI output; no component calls a provider quota
endpoint or sees provider HTTP headers directly.

**Tech stack:** Python 3.9-safe stdlib, JSON state, existing shell workers. No daemon, scheduler,
HTTP client, dependency, dynamic weight adjustment, health score, or fabricated capacity metric.

## What this claims

This feature makes **bounded, deterministic failover decisions from observed worker failures**.
It does not claim to know provider balance, remaining tokens, message allowance, reset percentage,
or future capacity. Compound V launches CLI processes; a CLI or its SDK may already have retried
internally before the orchestrator receives a final result. The run-level budget counts observed
worker launches, not hidden SDK attempts.

Official provider behavior confirms why status alone is insufficient:

- Anthropic distinguishes `429 rate_limit_error` from `529 overloaded_error`; its official SDKs
  retry connection errors, rate limits, and 5xx failures twice by default and honour
  `retry-after` when present: <https://docs.anthropic.com/en/api/errors>.
- OpenAI documents `Retry-After` only for a temporary 429, warns that quota/billing errors require
  action, and states that unsuccessful retries themselves consume per-minute capacity:
  <https://platform.openai.com/docs/guides/rate-limits>.
- z.ai publishes several semantically different business errors under HTTP 429: balance failure
  (`1113`), request throttling (`1302`), overload (`1305`), resettable usage windows
  (`1308`, `1310`, `1316`–`1321`), unavailable subscription/model combinations, and policy/account
  restrictions: <https://docs.z.ai/api-reference/api-code>.

The classifier therefore branches on a normalized reason and the rendered message, never the
HTTP status by itself. Tests use both full provider envelopes and the actual `claude -p`-style
rendering where the numeric z.ai business code may be absent.

## Existing defects this PR closes

1. `compound-v-failure-policy.py::_backoff` returns any positive provider delay before applying
   `BACKOFF_CAP`. A rendered "try again in 5 days" therefore requests a five-day foreground sleep.
2. The z.ai classifier currently treats `1305`, `1308`, `1310`, `1311`, `1316`, and `1317` as one
   `rate_limited` family. In real CLI output the numeric code may disappear, so invented short test
   messages can pass while documented messages fall into `other` or collide with the generic
   `insufficient balance` needle.
3. Pool selection skips unavailable and circuit-open members, but does not yet skip active
   transient cooldowns or serialize half-open probes.
4. A local DNS/TLS/internet outage currently looks like several independent provider failures.
   Naive cross-provider rerouting would multiply doomed calls and consume the run retry budget.

## Failure vocabulary and decisions

The normalized result vocabulary gains `usage_window_exhausted` and `model_unavailable` while
retaining the existing classes. A worker may additionally surface an optional absolute `retry_at`
beside `retry_after_seconds`.

| Failure signal | Meaning | Pool action | Breaker/cooldown |
|---|---|---|---|
| `rate_limited` | Short request/token/concurrency throttle | One same-assignment retry, then reroute current job | Transient backend cooldown |
| `overloaded` | Provider service capacity failure | One same-assignment retry, then reroute current job | Transient backend cooldown |
| `usage_window_exhausted` | Explicit resettable window lasting minutes, hours, days, or a month | No knowingly futile same-backend retry; reroute immediately | Cooldown until explicit reset |
| `model_unavailable` | This backend/account cannot serve the assigned model | Advance this pool job; do not disable unrelated models on the backend | No backend-wide breaker |
| `network` | Transport/network failure, further qualified by `network_scope` | Retry same assignment within its existing cap; reroute only with evidence the failure is endpoint-specific | Endpoint cooldown or correlated run pause |
| `out_of_credits` | Balance/package/billing exhausted | Existing pool advance, then concrete fallback | Existing permanent run breaker |
| `auth` | Invalid/expired credential or account policy restriction | Halt until corrected | Existing permanent run breaker |
| `context_length`, `timeout`, `other` | Existing meanings | Existing behavior | No new breaker behavior |

### z.ai message mapping

The mapping is based on the published message semantics and must work without a visible code:

- `1113` and balance/package exhaustion → `out_of_credits`.
- `1302` request-rate limit → `rate_limited`.
- `1305` temporarily overloaded → `overloaded`.
- `1308`, `1310`, `1316`–`1321` with a future reset → `usage_window_exhausted`.
- `1309` expired Coding Plan and `1314` expired enterprise package → `out_of_credits`.
- `1311` plan lacks the selected model → `model_unavailable`.
- `1313` Fair Use restriction requiring a restoration request and `1315` wrong key product type
  → `auth` (human action, never automatic retry).
- `1234` provider-reported network error → `network` with
  `network_scope: provider_reported`; generic 5xx processing failures → `overloaded` or `other`
  according to the existing narrow rules. Only DNS/TLS/connect/reset failures where no valid
  provider response arrived use `network_scope: no_response`.

Specific code/message rules run before generic substrings. A phrase such as "usage limit reached
for the past 5 hours; insufficient balance for extra usage" is a resettable window, not a
permanent balance breaker. Full documented messages are the positive fixtures; synthetic messages
alone are not acceptable evidence.

## Time handling: no long foreground sleep

`MAX_INLINE_WAIT_SECONDS` is 60, matching the existing backoff cap.

- A valid provider minimum plus jitter, or a computed backoff with jitter, from 1 through 60
  seconds may be returned as `backoff_seconds` for one inline retry. The 60-second eligibility
  decision is made after jitter; a provider minimum is never truncated to fit the cap.
- A valid wait greater than 60 seconds is **never** returned as `backoff_seconds`. The policy
  returns a cooldown mutation plus reroute, or a resumable halt when no member is viable.
- An absolute provider reset such as z.ai `next_flush_time` is normalized to `retry_at` in UTC.
  It remains absolute in state; it is not repeatedly converted from "N seconds from now".
- A missing or unparseable reset falls back to bounded exponential backoff with jitter. It never
  becomes zero-delay spinning.
- A syntactically valid far-future reset is not silently clamped or ignored: it remains visible
  in status, the backend remains bypassed, and no process sleeps for it. `/v:status` prints the
  exact validated recovery command `/v:resume --clear-cooldown <backend>`; that command accepts
  only a known concrete backend, clears only transient cooldown state (never a permanent circuit),
  validates the complete resulting state, persists it atomically, and then resumes. Operators are
  never instructed to hand-edit `state.json`.
- A reset in the past is treated as immediately probe-eligible, never as a negative delay.

For a non-pool job, retry counts and backend routing remain unchanged. The one deliberate safety
change is universal: a delay over 60 seconds becomes a resumable halt with `next_retry_at`, not a
long-running `sleep`.

## Canonical cooldown state

The old bare timestamp map becomes a validated object map keyed only by concrete backend:

```json
{
  "cooldowns": {
    "zai": {
      "until": "2026-08-05T00:00:00Z",
      "reason": "usage_window_exhausted",
      "opened_at": "2026-08-01T07:20:00Z",
      "opened_by_attempt_id": "task-a:2",
      "probe": {
        "status": "idle",
        "owner_job_id": null,
        "owner_attempt_id": null,
        "lease_until": null
      }
    }
  }
}
```

Required invariants:

- `pool` is never a key; the key is the concrete provider backend.
- Entries contain exactly `until`, `reason`, `opened_at`, `opened_by_attempt_id`, and `probe`.
- Timestamps are non-empty, timezone-aware ISO-8601 instants; `until >= opened_at` unless the
  parsed provider reset was already past at observation time, in which case `until == opened_at`.
- `reason` is one of `rate_limited`, `overloaded`, `usage_window_exhausted`, or `network`.
- Every worker launch receives a unique persisted `attempt_id`; the opening failure's id is
  recorded as `opened_by_attempt_id`.
- `probe` contains exactly `status`, `owner_job_id`, `owner_attempt_id`, and `lease_until`.
- `idle` requires null owner/attempt/lease. `leased` requires an existing job id, its current
  unique attempt id, and a future lease.
- A backend cannot have more than one probe owner. State writes are serialized by the dispatcher.
- Probe lease duration is derived from the launched job's timeout plus termination grace, so a
  legitimately running probe is not stolen. Resume first reconciles git/process liveness; only an
  absent/dead owner or an expired lease can return the probe to idle.
- Only a successful result whose `attempt_id` equals the current leased
  `probe.owner_attempt_id` may clear the cooldown. Success from any pre-cooldown or ordinary
  in-flight attempt remains a valid job result but cannot mutate newer health state. A repeated
  matching transient failure replaces `until`, returns the probe to idle, and leaves the frozen
  ring unchanged.

Legacy string cooldowns are accepted only at a migration seam that converts them once to the new
shape with a documented conservative reason. Newly written state always uses the object form;
malformed mixed state fails closed.

## Pool routing state machine

The frozen weighted ring remains the positional authority.

```text
assigned slot
    |
    +-- success --------------------------> finish; clear only if this is leased probe
    |
    +-- first short rate-limit/overload --> same backend/model retry, consume run budget
    |                                         |
    |                                         +-- success --> clear, finish
    |                                         +-- failure --> cooldown source
    |
    +-- explicit usage window ------------> cooldown source immediately
                                              |
                                              v
                               scan next frozen slot by index
                               skip unavailable/open/cooling slots
                                              |
                             +----------------+----------------+
                             |                                 |
                         viable slot                    no viable slot
                             |                                 |
                    record new concrete                 resumable halt;
                    assignment + index                  earliest next_retry_at
```

The policy emits `advance_pool` plus its exclusion/cooldown intent; it does not compute
`next_pool_index`. The pool-state transition performs one bounded scan and returns the exact
assignment together with validated replacement state. The reroute changes only the current job. A
transient cooldown deprioritizes the backend for new
pool dispatches; it does not resize the ring, rewrite weights, reassign already successful work,
or open the permanent `circuit_open` breaker.

`model_unavailable` supplies an exact backend/model exclusion for this job's bounded scan. It does
not create a backend-wide cooldown, so another model on the same provider remains eligible. A
backend-wide cooldown intentionally skips every weighted slot for that backend; this conservative
scope is an availability trade-off forced by CLI output that lacks stable limiter identity, not a
claim that every provider model shares one limiter.

Every cross-provider relaunch consumes `total_retries`. Per-class attempt counts may start at zero
for the new concrete assignment, but `total_retries` never resets across assignment changes or
`/v:resume`. If the run-level budget is exhausted, the policy halts before selecting another slot.

When every frozen slot is unavailable, circuit-open, or cooling, the job becomes `failed` and
resumable. The reason lists the distinct unavailable categories and the earliest known cooldown
expiry. Independent siblings continue; there is no daemon and no sleeping process waiting for the
timestamp.

## Half-open recovery and concurrency

An expired cooldown is probe-eligible, not automatically healthy. The next eligible real job may
atomically lease it as the single half-open probe. Compound V does not spend a separate synthetic
"reply ok" request merely to test capacity.

While the probe lease is active, other jobs skip that backend. Success from that exact leased
attempt clears the cooldown before normal dispatch resumes. A matching transient failure renews
the cooldown. A permanent
`out_of_credits` or `auth` result removes the cooldown and enters the existing reason-specific
circuit-breaker path.

Results from workers that were already in flight when a cooldown opened are still collected and
scope-gated. They may reinforce a failure, but their success cannot clear newer health state; only
the currently leased probe attempt can do that. The dispatcher launches no new ordinary work on
that backend until the one-probe rule permits it. This bounds a thundering herd without pretending
already-running external processes can be recalled safely.

## Temporary internet loss and correlated network failures

Cross-provider hopping is unsafe when the common network path is down. PR3 therefore adds a
validated optional run-level `network_pause` object with the same idle/leased probe discipline:

```json
{
  "network_pause": {
    "opened_at": "2026-08-01T07:20:00Z",
    "until": "2026-08-01T07:21:00Z",
    "evidence": [
      {"backend": "codex", "job_id": "task-a", "attempt_id": "task-a:2", "batch_id": "batch-4", "observed_at": "2026-08-01T07:20:00Z"},
      {"backend": "zai", "job_id": "task-b", "attempt_id": "task-b:1", "batch_id": "batch-4", "observed_at": "2026-08-01T07:20:12Z"}
    ],
    "probe": {"status": "idle", "owner_job_id": null, "owner_attempt_id": null, "lease_until": null}
  }
}
```

Deterministic evidence rules:

`NETWORK_CORRELATION_SECONDS` is 60. It is an orchestrator safety bound, not a claim about normal
network outage duration. Each evidence row contains exactly `backend`, `job_id`, `attempt_id`,
`batch_id`, and `observed_at`; rows are deduplicated by concrete backend plus attempt id and expired
outside the correlation window.

1. One backend's `network` failure is not enough to infer global internet loss. Apply the existing
   same-assignment bounded network retry; do not immediately provider-hop.
2. A completed successful provider call in the same batch and correlation window proves that a
   common total outage is absent. A repeatedly failing endpoint may then receive a backend
   `network` cooldown, and a pool job may reroute to the provider that demonstrated connectivity.
3. `network_scope: provider_reported` (including z.ai 1234 returned inside HTTP 500) proves a
   provider response existed. It may cool that endpoint/service but never contributes evidence to
   common-path internet loss.
4. `network_scope: no_response` failures from at least two distinct concrete providers, carrying
   the same batch id, observed within 60 seconds, and with no completed provider success in that
   window, open `network_pause`. This is explicitly an inference, not certainty, and status shows
   the evidence rows.
5. A provider success means a worker's final normalized successful completion. A TCP connection,
   HTTP 200, opened SSE stream, or first token is not success; final SSE/`finish_reason` errors
   remain failures.
6. While paused, no new provider worker launches. Local collect/scope-gate work continues.
7. At expiry or `/v:resume`, exactly one waiting real job leases the network probe. Success clears
   the pause; another network failure renews it. The orchestrator never fans out three simultaneous
   probes after connectivity returns.
8. The pause uses a bounded 60-second default when no provider time exists. It never opens a
   permanent backend circuit and never erases frozen assignments.

This deliberately prefers a short resumable interruption over spending all provider and run
budgets during a laptop Wi-Fi, DNS, VPN, proxy, TLS, or upstream connectivity outage.

## Three-provider scenario matrix

Likelihood labels are qualitative design priorities, not measured production frequencies.

| Scenario | Relative likelihood | Required outcome |
|---|---|---|
| One provider briefly throttles; two are healthy | High under parallel load | One local retry, source cooldown, current job advances |
| z.ai window closes for hours/days | Medium/high for Coding Plan usage | Immediate reset cooldown; no 2/4/8-second hammering |
| One provider overloads | Medium | Bounded retry, then temporary failover; no permanent breaker |
| Two providers throttle together | Medium in bursty batches | Skip both cooldowns, use third, preserve ring positions |
| All three throttle | Low but credible | Stop rotation, expose earliest reset, resumable halt |
| One provider endpoint/DNS path fails | Medium/low | Other-provider success proves endpoint-specific failure; cooldown only that backend |
| Internet/VPN/proxy disappears | Medium operational risk | Correlated pause; no three-provider retry storm |
| Huge or malformed cooldown | Credible integration fault | Never long-sleep; persist/display valid future time or bounded fallback |
| Concurrent jobs reach half-open backend | Medium | Exactly one lease owner; all others skip |
| Crash during cooldown/probe | Normal crash-recovery case | Validate state, reconcile owner, preserve total budget and assignment |

## Interfaces

### Classifier output / `job_result`

`compound-v-classify-failure.py` continues to return `failure_class`, `retryable`, `matched`, and
`retry_after`. It additionally returns `retry_at` (`null` when absent) and `network_scope`
(`no_response`, `provider_reported`, or `null`). Worker results surface both optional fields;
success/blocked results carry neither failure timing/scope nor a failure class.

The schema rejects negative/non-finite delays and malformed timestamps. Provider strings are
treated as untrusted input; parsing never executes or interpolates them.

### Failure-policy inputs and outputs

New inputs include whether the job is pool-routed, current concrete assignment, current failure
attempt id, reset hints, retry counters, and the summarized batch-network facts needed for policy.
The policy does not accept or scan `pool_members`. Existing callers that omit all pool/network
inputs retain legacy routing decisions except for the universal 60-second sleep safety rule.

Decisions may return:

- `cooldown_backend`, reason, and minimum-until intent (the state helper constructs the canonical
  object with attempt/probe metadata);
- `advance_pool`, an exact backend/model exclusion when applicable, `reroute_to`, and
  `consume_total_retry`;
- `network_pause` mutation;
- `next_retry_at` on resumable halt;
- `probe_backend` / `probe_owner_job_id` / `probe_owner_attempt_id` when a half-open lease is
  acquired.

The policy returns intent data only. The dispatcher passes current state + job + intent + injected
UTC time/batch context to one pool-state transition. That helper validates current state, applies
the cooldown/network mutation, performs at most one bounded viability scan/lease acquisition, and
returns replacement state plus the concrete launch assignment. The dispatcher validates again,
persists by atomic replacement, then launches. A failed validation launches nothing. The existing
out-of-credits pool advance is refactored through this same authority so PR2 and PR3 cannot drift.

### Status and resume

`/v:status` renders concrete backend, reason, absolute retry time, probe owner, and whether the
run is provider-cooling or network-paused. It reports no percentage, health score, estimated
quota, or invented savings.

`/v:resume` validates cooldown/network state before considering failed jobs, reconciles probe
owners through the existing git-wins/liveness rules, and never dispatches to an active cooldown,
open circuit, or active network pause. Expiry grants probe eligibility, not automatic health.

## Acceptance criteria

1. A temporary OpenAI/Anthropic-style rate limit with a wait at or below 60 seconds retries the
   same concrete assignment once and consumes the run retry budget.
2. A second consecutive short rate limit on a pooled assignment records a canonical backend
   cooldown and advances only that job to the next viable frozen slot.
3. A wait over 60 seconds is never emitted as foreground `backoff_seconds`; pool jobs reroute and
   non-pool/no-viable jobs halt resumably with `next_retry_at`.
4. z.ai documented full messages classify correctly with and without numeric business codes:
   throttle, overload, resettable window, model unavailable, credits, and auth/policy action.
5. An explicit future usage-window reset causes immediate cooldown/reroute without a knowingly
   futile same-backend retry.
6. Pool selection skips active cooldown slots without deleting or reordering frozen members.
7. Two cooling providers and one healthy provider select the healthy provider deterministically.
8. Three unavailable/open/cooling providers halt without looping and report the earliest known
   absolute retry time.
9. Every cross-provider relaunch increments `total_retries`; `/v:resume` never resets it.
10. Exactly one attempt may own an expired backend's half-open probe lease. Only success from that
    exact leased `attempt_id` clears the cooldown; pre-cooldown in-flight success cannot clear it;
    repeated transient failure renews it.
11. A permanent failure returned by a probe transitions through the existing reason-specific
    circuit breaker, not another transient cooldown.
12. A single network failure preserves the assignment and uses the existing bounded retry.
13. A completed success by another provider in the correlation window permits endpoint-specific
    network cooldown and rerouting of the failing provider's pool job; merely opening a stream
    does not.
14. Deduplicated `no_response` failures from two distinct providers in one batch within 60 seconds
    and with no completed provider success open a global network pause. Provider-reported z.ai
    1234 and stale/duplicate evidence cannot open it.
15. Network recovery uses exactly one real-job probe; it does not fan out across the pool.
16. Resume during an active cooldown or network pause performs no forbidden launch; resume after
    expiry grants only a serialized probe.
17. Unknown backend/reason/scope, bare-string new cooldown, malformed/naive timestamp, invalid
    attempt/probe owner/lease, duplicate probe ownership/evidence, negative or non-finite delay,
    and malformed/stale network evidence all fail closed.
18. Legacy non-pool short-retry decisions remain unchanged. The only intentional non-pool change
    is that a delay over 60 seconds cannot block the process.
19. Status and documentation distinguish transient cooldown, resettable usage window, permanent
    circuit breaker, and correlated network pause without capacity percentages or health claims.
20. Negative controls prove the tests detect at least: disabled cooldown skipping, uncapped
    multi-day sleep, stale in-flight success clearing a newer cooldown, double half-open probe,
    z.ai message-without-code misclassification, z.ai 1234 counted as offline evidence, and
    network-pause fan-out.

## Non-goals

- Polling z.ai's undocumented quota endpoint or adding direct provider HTTP clients.
- Reading HTTP headers that the CLI transport does not expose.
- Dynamically changing pool weights from failures, latency, price, or inferred capacity.
- Predicting quota consumption, monetary savings, or a provider health percentage.
- Cancelling workers already in flight solely because another job opened a cooldown.
- Automatically merging prerequisite PRs or hiding the stacked merge order.
