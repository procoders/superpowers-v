# Provider cooldowns and pool rerouting (PR 3 of 3)

**Goal:** keep a tier-model-pool run productive when one of three independent model providers is
temporarily throttled, overloaded, window-exhausted, or unreachable, without turning a transient
failure into a retry storm, silently changing the frozen weighted ring, or sleeping the
orchestrator for hours or days.

**Merge prerequisites:** PR 1 supplies the concrete `zai` backend; PR 2 supplies deterministic
weighted pools and frozen concrete assignments. This PR is intentionally stacked on both and must
merge after them. The implementation branch may carry their commits while they are open; that is
not a claim that either prerequisite has merged.

**Architecture:** the deterministic failure-policy script remains the sole decision engine. It
gains pool-aware cooldown/reroute inputs and emits explicit state mutations. The pool-state helper
owns validation and selection against frozen state. Workers continue to classify their captured
CLI output into normalized failure signals; no component calls a provider quota endpoint or sees
provider HTTP headers directly.

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
| `network` | DNS/TLS/connect/reset with no provider response | Retry same assignment within its existing cap; reroute only with evidence the failure is endpoint-specific | Endpoint cooldown or correlated run pause |
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
- `1234` network error → `network`; generic 5xx processing failures → `overloaded` or `other`
  according to the existing narrow rules.

Specific code/message rules run before generic substrings. A phrase such as "usage limit reached
for the past 5 hours; insufficient balance for extra usage" is a resettable window, not a
permanent balance breaker. Full documented messages are the positive fixtures; synthetic messages
alone are not acceptable evidence.

## Time handling: no long foreground sleep

`MAX_INLINE_WAIT_SECONDS` is 60, matching the existing backoff cap.

- A valid `Retry-After` or computed backoff from 1 through 60 seconds may be returned as
  `backoff_seconds` for one inline retry.
- A valid wait greater than 60 seconds is **never** returned as `backoff_seconds`. The policy
  returns a cooldown mutation plus reroute, or a resumable halt when no member is viable.
- An absolute provider reset such as z.ai `next_flush_time` is normalized to `retry_at` in UTC.
  It remains absolute in state; it is not repeatedly converted from "N seconds from now".
- A missing or unparseable reset falls back to bounded exponential backoff with jitter. It never
  becomes zero-delay spinning.
- A syntactically valid far-future reset is not silently clamped or ignored: it remains visible
  in status, the backend remains bypassed, and no process sleeps for it. The operator may correct
  or clear bad provider data explicitly.
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
      "probe": {
        "status": "idle",
        "owner_job_id": null,
        "lease_until": null
      }
    }
  }
}
```

Required invariants:

- `pool` is never a key; the key is the concrete provider backend.
- Entries contain exactly `until`, `reason`, `opened_at`, and `probe`.
- Timestamps are non-empty, timezone-aware ISO-8601 instants; `until >= opened_at` unless the
  parsed provider reset was already past at observation time, in which case `until == opened_at`.
- `reason` is one of `rate_limited`, `overloaded`, `usage_window_exhausted`, or `network`.
- `probe` contains exactly `status`, `owner_job_id`, and `lease_until`.
- `idle` requires null owner/lease. `leased` requires an existing job id and a future lease.
- A backend cannot have more than one probe owner. State writes are serialized by the dispatcher.
- Probe lease duration is derived from the launched job's timeout plus termination grace, so a
  legitimately running probe is not stolen. Resume first reconciles git/process liveness; only an
  absent/dead owner or an expired lease can return the probe to idle.
- Success by the probe clears the cooldown. A repeated matching transient failure replaces
  `until`, returns the probe to idle, and leaves the frozen ring unchanged.

Legacy string cooldowns are accepted only at a migration seam that converts them once to the new
shape with a documented conservative reason. Newly written state always uses the object form;
malformed mixed state fails closed.

## Pool routing state machine

The frozen weighted ring remains the positional authority.

```text
assigned slot
    |
    +-- success --------------------------> clear its cooldown, finish
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

The reroute changes only the current job. A transient cooldown deprioritizes the backend for new
pool dispatches; it does not resize the ring, rewrite weights, reassign already successful work,
or open the permanent `circuit_open` breaker.

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

While the probe lease is active, other jobs skip that backend. Success clears the cooldown before
normal dispatch resumes. A matching transient failure renews the cooldown. A permanent
`out_of_credits` or `auth` result removes the cooldown and enters the existing reason-specific
circuit-breaker path.

Results from workers that were already in flight when a cooldown opened are still collected and
scope-gated. They may reinforce or clear state, but the dispatcher launches no new ordinary work
on that backend until the one-probe rule permits it. This bounds a thundering herd without
pretending already-running external processes can be recalled safely.

## Temporary internet loss and correlated network failures

Cross-provider hopping is unsafe when the common network path is down. PR3 therefore adds a
validated optional run-level `network_pause` object with the same idle/leased probe discipline:

```json
{
  "network_pause": {
    "opened_at": "2026-08-01T07:20:00Z",
    "until": "2026-08-01T07:21:00Z",
    "evidence": [
      {"backend": "codex", "job_id": "task-a"},
      {"backend": "zai", "job_id": "task-b"}
    ],
    "probe": {"status": "idle", "owner_job_id": null, "lease_until": null}
  }
}
```

Deterministic evidence rules:

1. One backend's `network` failure is not enough to infer global internet loss. Apply the existing
   same-assignment bounded network retry; do not immediately provider-hop.
2. A successful provider call in the current batch proves that a common total outage is absent.
   A repeatedly failing endpoint may then receive a backend `network` cooldown, and a pool job may
   reroute to the provider that demonstrated connectivity.
3. Network failures from at least two distinct concrete providers in the same dispatch batch,
   with no intervening provider success in that batch, open `network_pause`. This is explicitly an
   inference, not certainty, and the status output shows its evidence rows.
4. While paused, no new provider worker launches. Local collect/scope-gate work continues.
5. At expiry or `/v:resume`, exactly one waiting real job leases the network probe. Success clears
   the pause; another network failure renews it. The orchestrator never fans out three simultaneous
   probes after connectivity returns.
6. The pause uses a bounded 60-second default when no provider time exists. It never opens a
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
`retry_after`. It additionally returns `retry_at` (`null` when absent). Worker results surface it
as optional `retry_at`; success/blocked results carry neither a failure reset nor a failure class.

The schema rejects negative/non-finite delays and malformed timestamps. Provider strings are
treated as untrusted input; parsing never executes or interpolates them.

### Failure-policy inputs and outputs

New inputs include frozen pool context, current `pool_index`, canonical cooldown state, current
UTC time, batch network evidence, and whether the job is pool-routed. Existing callers that omit
all pool/network inputs retain legacy routing decisions except for the universal 60-second sleep
safety rule.

Decisions may return:

- `cooldown_backend` and a complete canonical `cooldown` object;
- `next_pool_index`, `reroute_to`, and `consume_total_retry`;
- `network_pause` mutation;
- `next_retry_at` on resumable halt;
- `probe_backend` / `probe_owner_job_id` when a half-open lease is acquired.

The policy returns data only. The dispatcher applies mutations atomically, validates the resulting
state, persists it, then launches. A failed validation launches nothing.

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
10. Exactly one job may own an expired backend's half-open probe lease. Success clears the
    cooldown; repeated transient failure renews it.
11. A permanent failure returned by a probe transitions through the existing reason-specific
    circuit breaker, not another transient cooldown.
12. A single network failure preserves the assignment and uses the existing bounded retry.
13. Success by another provider in the same batch permits endpoint-specific network cooldown and
    rerouting of the failing provider's pool job.
14. Network failures from two distinct providers in one batch with no provider success open a
    global network pause and prevent additional provider launches.
15. Network recovery uses exactly one real-job probe; it does not fan out across the pool.
16. Resume during an active cooldown or network pause performs no forbidden launch; resume after
    expiry grants only a serialized probe.
17. Unknown backend/reason, bare-string new cooldown, malformed/naive timestamp, invalid probe
    owner/lease, duplicate probe ownership, negative delay, and malformed network evidence all
    fail closed.
18. Legacy non-pool short-retry decisions remain unchanged. The only intentional non-pool change
    is that a delay over 60 seconds cannot block the process.
19. Status and documentation distinguish transient cooldown, resettable usage window, permanent
    circuit breaker, and correlated network pause without capacity percentages or health claims.
20. Negative controls prove the tests detect at least: disabled cooldown skipping, uncapped
    multi-day sleep, double half-open probe, z.ai message-without-code misclassification, and
    network-pause fan-out.

## Non-goals

- Polling z.ai's undocumented quota endpoint or adding direct provider HTTP clients.
- Reading HTTP headers that the CLI transport does not expose.
- Dynamically changing pool weights from failures, latency, price, or inferred capacity.
- Predicting quota consumption, monetary savings, or a provider health percentage.
- Cancelling workers already in flight solely because another job opened a cooldown.
- Automatically merging prerequisite PRs or hiding the stacked merge order.

