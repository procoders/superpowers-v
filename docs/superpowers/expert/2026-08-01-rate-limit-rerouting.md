# Provider cooldowns and pool rerouting — Domain Audit

## 1. Domain(s) Identified

- Primary: multi-provider LLM failure routing and circuit-breaker semantics.
- Secondary: retry/cooldown operational safety for unattended coding-agent runs.
- Secondary: correlated-network-outage inference across Anthropic, OpenAI, and z.ai transports.

The committed PR3 spec was read in full. Trigger 0 supplied no recon document: the recorded
outcome was a fresh strong KB hit in
`docs/superpowers/library-audit/_knowledge-base/model-routing-and-provider-quotas.md`. That KB,
`_knowledge-base/llm-provider-load-balancing.md`,
`_knowledge-base/autonomous-agent-orchestration.md`, and
`_knowledge-base/llm-subscription-plan-compliance.md` were reused and then checked against current
official sources.

## 2. Sources Consulted

- Prior KB: `library-audit/_knowledge-base/model-routing-and-provider-quotas.md` — REUSED, but its
  statement that z.ai quota querying is wholly undocumented is now stale; z.ai publishes an
  official Claude Code usage-query plugin.
- Prior KB: `_knowledge-base/llm-provider-load-balancing.md` — REUSED for frozen-ring, retry-storm,
  backend-breaker, and heterogeneous-meter constraints.
- Prior KB: `_knowledge-base/autonomous-agent-orchestration.md` — REUSED for lease ownership,
  global retry budgets, and actionable resumable halts.
- Prior KB: `_knowledge-base/llm-subscription-plan-compliance.md` — REUSED for z.ai risk-control
  consequences and Coding Plan windows.
- Anthropic official API errors: 429 is `rate_limit_error`, 529 is `overloaded_error`; official
  SDKs retry connection errors, 429s, and 5xx twice by default, honouring `retry-after` when present:
  <https://platform.claude.com/docs/en/api/errors>.
- Anthropic official rate limits: limits are per model class and use RPM, ITPM, and OTPM;
  `retry-after` is the number of seconds before an earlier retry would fail, and sharp traffic
  acceleration can itself produce 429s:
  <https://platform.claude.com/docs/en/api/rate-limits>.
- OpenAI official rate limits: limits vary by model, some model families share a limiter,
  `Retry-After` is a minimum for temporary 429s, SDKs already retry eligible errors, application
  retries must account for those hidden attempts, and failed retries consume per-minute capacity:
  <https://developers.openai.com/api/docs/guides/rate-limits>.
- z.ai official error table: business codes must be read separately from HTTP status; codes
  1308/1310 and 1316–1321 carry reset instants, while 1234 is an HTTP 500 response saying
  "Network error": <https://docs.z.ai/api-reference/api-code>.
- z.ai official Coding Plan policy: concurrency is dynamic by plan/resource availability, and
  risk-control violations may cause throttling, freezing, or a ban after repeated violations:
  <https://docs.z.ai/devpack/usage-policy>.
- z.ai official Coding Plan overview: the plan has independent rolling five-hour and seven-day
  credit windows: <https://docs.z.ai/devpack/overview>.
- z.ai official Usage Query Plugin: current quota can now be queried interactively from Claude
  Code on a Personal plan: <https://docs.z.ai/devpack/extension/usage-query-plugin>.

Community/persona/forum searches were intentionally not used. The active technical-source policy
requires primary or official sources only; the audit therefore does not use anecdotes to assign
failure probabilities or infer undocumented CLI rendering.

## 3. Domain Constraints the Brainstorm Probably Missed

### 🔴 MUST distinguish "no provider response" from a provider-reported network failure

The spec maps z.ai code `1234` to `network`, while the correlated-outage rule treats `network` as
DNS/TLS/connect/reset "with no provider response." Those facts cannot both be used as the same
evidence. z.ai documents `1234` as a business error carried by an HTTP 500 response, so receipt of
it proves that a provider response was reached; it does **not** prove the caller's common internet
path is unavailable: <https://docs.z.ai/api-reference/api-code>.

The classifier may retain a broad `network` presentation class, but the policy needs a separate
machine-readable evidence kind, for example `network_scope: no_response | provider_reported`, or
an equivalent narrow boolean. Only independently observed no-response transport failures may
contribute to `network_pause`. Provider-reported `1234` should receive an endpoint/service
cooldown or existing bounded 5xx handling and must not count toward the two-provider global-pause
threshold.

### 🔴 MUST prevent stale in-flight success from clearing a newer cooldown

The spec says already-running workers may clear cooldown state. A worker that started before
`opened_at` can finish after another worker opens the cooldown; collection order is not causal
order. Clearing on that late result can re-enable a provider immediately after the newest
confirmed throttle.

Only the leased half-open probe, or a completed success whose recorded launch/attempt generation
is newer than the cooldown generation, may clear it. A plain success from a pre-cooldown worker
may be collected and scope-gated but must leave the cooldown unchanged. This follows from the
spec's own single-probe invariant; otherwise an ordinary old request silently acts as a second
probe.

### MUST bound the correlation window, not merely say "same batch"

Two failures in one batch can be separated by a long worker runtime and need not describe one
network incident. Persist evidence with a batch identifier and observed UTC instant, and accept it
for the global-pause inference only inside an explicit bounded correlation window. The window is
an orchestrator safety parameter, not a measured network property. z.ai explicitly describes
concurrency limits as dynamic, so coincident failures can also be independent throttling/service
events and should not be relabelled as connectivity without no-response evidence:
<https://docs.z.ai/devpack/usage-policy>.

### MUST treat provider retry delays as minimums and CLI reset data as optional

Anthropic says an earlier retry than `retry-after` will fail. OpenAI says `Retry-After` is a
minimum and recommends a small random delay; it may be missing or invalid. The CLI-process
architecture does not expose response headers by contract, so these official API guarantees do
not guarantee that Compound V will see them:
<https://platform.claude.com/docs/en/api/rate-limits>,
<https://developers.openai.com/api/docs/guides/rate-limits>.

Consequently:

- parser absence must use bounded non-zero fallback, never imply immediate retry;
- the inline eligibility check applies to `minimum + jitter`, not the minimum alone;
- if that combined wait exceeds 60 seconds, park/reroute rather than truncate the provider's
  minimum;
- deterministic tests need an injected clock and jitter source (or stable per-attempt jitter),
  not wall-clock/random assertions.

### MUST make cooldown scope conservative and explicit

Anthropic API limits are measured per model class. OpenAI says limits vary by model and that only
some model families share limits. A cooldown keyed solely by backend can therefore temporarily
disable unrelated models on that provider:
<https://platform.claude.com/docs/en/api/rate-limits>,
<https://developers.openai.com/api/docs/guides/rate-limits>.

Because CLI-rendered failures may omit limiter identity, backend-wide cooldown is a defensible
fail-closed choice for PR3, especially for the stated three-provider/one-member-each scenario.
The plan and PR description must call it a conservative availability trade-off, not provider
truth. `model_unavailable` correctly remains assignment/model-specific and must not create that
backend-wide cooldown.

### MUST count a complete call, not an opened stream, as network success

Anthropic documents that SSE errors can occur after an HTTP 200 response, and z.ai documents that
streaming failures may surface in `finish_reason` rather than the normal error envelope:
<https://platform.claude.com/docs/en/api/errors>,
<https://docs.z.ai/api-reference/api-code>.

Therefore "provider success in the current batch" means a worker's final successful result, not
TCP connection, headers received, stream opened, or first output token. A mid-stream failure must
remain eligible transport/service evidence according to its final normalized result.

### MUST expose an actual recovery operation for far-future cooldowns

The spec correctly refuses to long-sleep or silently clamp a syntactically valid future reset,
but "the operator may clear bad provider data" is not yet an interface. Status must provide an
exact safe recovery action (a validated command or documented state transition) and must not ask
operators to hand-edit arbitrary JSON. This is required to ensure a corrupt year-long reset causes
visible reduced capacity, not an operationally permanent backend disappearance.

### SHOULD preserve hidden-retry honesty in status and tests

Anthropic SDKs retry eligible transient errors twice by default; OpenAI SDKs also retry eligible
rate limits and explicitly warns application layers to account for hidden SDK attempts:
<https://platform.claude.com/docs/en/api/errors>,
<https://developers.openai.com/api/docs/guides/rate-limits>.

The approved single orchestrator retry is still bounded, but may be the fourth physical provider
request. Status and PR prose must continue saying `total_retries` counts worker relaunches, not API
attempts. Do not infer provider reliability from that count.

## 4. Common Traps in This Domain

- **429 is not a semantic class.** z.ai uses HTTP 429 for depleted balance, short throttling,
  resettable windows, missing model access, expired plans, and Fair Use restrictions; the spec's
  ordered code/message matching is mandatory: <https://docs.z.ai/api-reference/api-code>.
- **Retry-after cap inversion.** A safety cap cannot turn a provider's 300-second minimum into a
  60-second retry; it must turn the operation into parked state.
- **Completion-order health.** Concurrent results arrive out of order. State generation, not
  collector arrival order, decides whether a success may clear a cooldown.
- **Weighted duplicate slots.** Skipping a cooling backend must skip all of its frozen weighted
  slots without deleting them; otherwise the ring changes and resume is not reproducible.
- **False global outage.** Two provider business errors, two timeouts from already-overloaded
  workers, or one no-response failure duplicated by a wrapper are not two independent network
  observations.
- **Probe resurrection.** An expired lease is not proof the old external process stopped. The
  existing liveness reconciliation must precede lease theft, as the spec requires.
- **Retry amplification.** OpenAI states failed retries consume rate capacity; SDK and CLI layers
  can already retry before Compound V relaunches a worker:
  <https://developers.openai.com/api/docs/guides/rate-limits>.
- **Provider-wide collateral damage.** Backend-scoped cooldown is safer against storms but can
  suppress a healthy model whose limiter is independent; report the scope honestly.

## 5. Regulatory / Compliance Notes

There is no material privacy or regulated-data change in PR3; persisted evidence already uses
backend and job identifiers rather than prompts or provider response bodies.

There is, however, a subscription-enforcement constraint for z.ai. Its Coding Plan dynamically
adjusts concurrency, limits subscription use to the subscriber and supported tools, and may apply
high-intensity throttling, account freezing, or bans after repeated risk-control violations:
<https://docs.z.ai/devpack/usage-policy>. This makes bounded retries and a non-permanent treatment
of ordinary throttles necessary, but code `1313` must remain a human-action halt rather than an
automatic cooldown loop.

The audit does not assert that any particular ordinary 429 is an enforcement strike; the public
error surface does not support that inference.

## 6. Recent Breaking Changes (last 12 months)

- z.ai's current official error table now includes resettable Coding Plan codes through `1321`,
  and it distinguishes overload (`1305`) from short request rate limiting (`1302`) and resettable
  windows (`1308`, `1310`, `1316`–`1321`):
  <https://docs.z.ai/api-reference/api-code>. The spec covers these current rows.
- z.ai now officially publishes a `glm-plan-usage` Claude Code plugin for Personal-plan quota and
  usage queries: <https://docs.z.ai/devpack/extension/usage-query-plugin>. This invalidates the old
  blanket KB statement that quota querying is wholly undocumented. It does **not** require PR3 to
  poll quotas; failure-observed routing remains the narrower and more portable design.
- Current z.ai Coding Plan documentation describes five-hour credits as dynamically refreshed and
  weekly credits as resetting every seven days:
  <https://docs.z.ai/devpack/overview>. Absolute provider reset messages must therefore remain
  visible rather than being reduced to a generic permanent credit breaker.
- Current OpenAI guidance states official SDKs automatically retry eligible rate limits and
  honour `Retry-After`; layering a worker retry must account for this behavior:
  <https://developers.openai.com/api/docs/guides/rate-limits>.

## 7. Design Constraints for the Plan

- MUST split no-response transport evidence from provider-reported network errors; z.ai `1234`
  MUST NOT contribute to global internet-loss inference.
- MUST attach attempt/generation identity to cooldown mutation and success; only the leased probe
  or a causally newer success may clear a cooldown.
- MUST store `batch_id` and `observed_at` with network evidence and enforce a bounded correlation
  window before opening `network_pause`.
- MUST deduplicate network evidence by concrete backend and worker attempt so one wrapped error
  cannot count twice.
- MUST define provider success as a completed successful worker result, not stream establishment.
- MUST treat a provider retry delay as a minimum; add jitter before testing 60-second inline
  eligibility and park rather than truncate when the combined wait exceeds the cap.
- MUST inject clock/jitter inputs for deterministic boundary tests at 59/60/61 seconds and for
  past/future absolute reset handling.
- MUST preserve backend-wide cooldown as an explicitly conservative scope when limiter identity is
  unavailable; MUST keep `model_unavailable` assignment-specific.
- MUST provide a validated, actionable way to clear/correct a bad far-future cooldown and surface
  it in `/v:status`.
- MUST keep `total_retries` as the monotonic worker-launch budget across reroute and resume and
  describe it as distinct from hidden CLI/SDK attempts.
- MUST test SSE/mid-stream final errors as failures even if a connection/HTTP 200 occurred.
- MUST keep `1313` and other human-action policy/auth failures out of automatic cooldown probing.
- MUST NOT use the new z.ai usage-query plugin or any quota percentage as a routing input in PR3;
  its existence is an observability fact, not deterministic cross-provider capacity.

## 8. Open Questions for the Human

None are genuinely blocking. The spec's backend-wide cooldown is a conservative but coherent PR3
scope once its reduced-availability trade-off is documented. A future PR may introduce
model/limiter-scoped cooldown keys if the CLI transport begins exposing stable limiter identity.

## 9. Knowledge Base Updates

Appended `Updated 2026-08-01 — cooldown causality and correlated-network evidence` to
`_knowledge-base/llm-provider-load-balancing.md` with:

- causal/generation-safe cooldown clearing;
- separation of provider-reported network errors from no-response transport evidence;
- bounded, timestamped, deduplicated outage correlation;
- minimum-delay semantics and no cap truncation;
- conservative backend-scope implications;
- the now-official z.ai Personal-plan usage-query surface.
