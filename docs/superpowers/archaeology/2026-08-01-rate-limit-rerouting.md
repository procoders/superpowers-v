# Provider cooldowns and pool rerouting — code archaeology

**Scope:** combined PR 1 + PR 2 tree at `92d6585`, before PR 3 implementation.
**Evidence:** actual classifier, policy, pool-state helper, worker boundary, result schema/collector,
dispatcher, status, and resume contracts. Baseline checks exercised 277 deterministic cases
(`55 + 37 + 60 + 94 + 31`), all passing. Those checks establish the existing behavior; they do
not cover the PR 3 state machine.

## 1. Matrix

### Existing failure-policy branches versus PR 3

| Failure | Existing classification | Existing decision | Pool behavior required by PR 3 | Existing code handles it? |
|---|---|---|---|---|
| `none` | exit 0 | `proceed` | probe success may clear eligible transient state | Partial: proceed exists; no probe ownership/state |
| `rate_limited`, first short wait | retryable | same-backend retry, cap 3 | exactly one same-assignment retry, `<=60s` inline | Partial: retry exists; provider delay bypasses 60s cap |
| `rate_limited`, second failure | same class | second same-backend retry | backend cooldown + next viable frozen slot | No |
| `overloaded`, first short wait | retryable | same-backend retry, cap 2 | one same-assignment retry | Yes for the first decision only |
| `overloaded`, second failure | same class | second same-backend retry | backend cooldown + pool advance | No |
| `usage_window_exhausted` | not in vocabulary | falls to unclassified halt if passed directly | immediate absolute-reset cooldown + pool advance | No |
| `model_unavailable` | not in vocabulary | falls to unclassified halt if passed directly | advance this job without backend-wide breaker | No |
| `network`, one provider | retryable | same-backend retry, cap 2 | preserve assignment; bounded retry | Yes, absent new state interaction |
| `network`, endpoint-specific evidence | retryable | same-backend retry only | backend network cooldown + pool advance | No |
| `network`, two providers/no success | independent retries | each provider spends budget independently | one run-level network pause | No |
| `out_of_credits` | non-retryable | permanent breaker; ring then fallback | retain PR 2 behavior | Yes; regression-sensitive |
| `auth` | non-retryable | permanent breaker + halt | retain reason-specific recovery | Yes; regression-sensitive |
| `context_length` | non-retryable | tier escalation or deep halt | unchanged | Yes; regression-sensitive |
| `timeout` / `other` | retryable | existing capped retry | unchanged | Yes; regression-sensitive |

The retry counts are authoritative in `scripts/compound-v-failure-policy.py:50-60`; every
retryable class currently takes the one generic branch at
`scripts/compound-v-failure-policy.py:309-320`. Therefore “second consecutive 429 reroutes” is a
new transition, not a configuration change to the existing cap.

### Pool member state matrix

| Frozen slot state | Existing `select` | Required ordinary dispatch | Required expired-slot dispatch |
|---|---|---|---|
| unavailable tombstone | skip, position retained | skip | skip |
| permanent breaker open | skip, position retained | skip | skip |
| no breaker/cooldown | select | select | select |
| active transient cooldown | **selects it** | skip every weighted slot for that backend | n/a |
| expired cooldown, probe idle | **selects it as healthy** | exactly one real job leases probe | one owner only |
| expired cooldown, probe leased | **selects it** | all jobs except owner skip | owner may launch |
| malformed cooldown/probe | ignored | fail closed before launch | fail closed |

The concrete proof is `scripts/compound-v-pool-state.py:195-233`: selection consults only frozen
availability and `circuit_open`. A state carrying `cooldowns.codex = 2099-01-01T00:00:00Z` still
selects the codex slot. Weighted duplicates are positional by construction
(`scripts/compound-v-pool-state.py:87-107`), so backend cooldown must skip all matching slots
without deleting them.

### Assignment and wait dimensions

| Dimension | Cells that must remain distinct |
|---|---|
| Routing source | non-pool; in-ring `assignment_source: pool`; ordinary `fallback` after ring exhaustion |
| Wait hint | absent/malformed; `1..60s`; `>60s`; absolute future reset; absolute past reset |
| Provider count | one failing/two healthy; two failing/one healthy; all unavailable/cooling/open |
| Probe result | success; same transient; permanent credits/auth; endpoint network; unrelated failure; crash/dead owner |
| Concurrency | no probe; one leased probe; several completed/in-flight results arriving after cooldown opens |
| Resume time | before expiry; after expiry; before lease expiry with live owner; expired/dead owner; malformed legacy state |

Non-pool and fallback jobs omit pool context today (`agents/parallel-dispatcher.md:215-230`). PR 3
must not accidentally apply ring selection to either cell. The sole intentional non-pool change is
the long-sleep safety rule.

## 2. Shared State

### `failure_class`, `retry_after_seconds`, and the new `retry_at`

The classifier returns a three-tuple and renders `retry_after` only
(`scripts/compound-v-classify-failure.py:255-301`). The schema requires the renamed integer
`retry_after_seconds` and has neither a minimum nor `retry_at`
(`schemas/job_result.schema.json:65-87`). Classifier-backed workers translate the field themselves;
for example codex at `scripts/compound-v-run-codex-worker.sh:503-528` and zai at
`scripts/compound-v-run-zai-worker.sh:300-308`. The collector independently reconstructs the same
pair at `scripts/compound-v-collect-results.py:321-342`, and its CLI hard-codes the old enum at
`scripts/compound-v-collect-results.py:1270-1275`.

Gap: changing only the classifier loses the new classes/time at either worker emission or collect.
Success must normalize both reset hints away; blocked results must not become policy inputs.

### `attempts` and `total_retries`

`attempts[job][class]` is per failure class, while `total_retries` is run-wide
(`skills/compound-v/state-machine.md:205-213`). The policy validates only counters supplied to it
(`scripts/compound-v-failure-policy.py:230-248`) and marks relaunches with
`consume_total_retry`; the Markdown dispatcher performs the mutation
(`agents/parallel-dispatcher.md:202-237`). There is no concrete state mutator.

Gap: “consecutive on this assignment” is not represented in the key. The dispatcher currently
resets/forks counters manually when backend/class changes. A pool reroute must reset the new
assignment's per-class count while preserving `total_retries`; resume must never infer a fresh run
budget from missing in-memory context.

### Frozen ring and current assignment

`pool_members`, `assigned_backend`, `assigned_model`, `assignment_source`, `pool_index`, and
`pool_tier` are frozen/validated by `scripts/compound-v-pool-state.py:236-379`. Resume returns only
the validated pair and reads the remaining fields from state
(`scripts/compound-v-pool-state.py:382-399`; `commands/v-resume.md:15-19`).

Gap: `select_frozen_member` owns live slot selection, while failure-policy independently scans the
same ring for out-of-credits at `scripts/compound-v-failure-policy.py:112-135`. Adding cooldown and
probe rules to both would create two viability authorities. The plan needs one shared selector or
one rigorously defined division: policy decides transition, pool-state validates/selects the exact
slot. No prose-only duplicate may silently disagree.

`model_unavailable` is slot/model-specific, unlike a backend cooldown. Existing
`_member_is_viable` excludes every slot with the exhausted backend
(`scripts/compound-v-failure-policy.py:112-118`). Reusing it would either retry a duplicate of the
same unavailable model or incorrectly suppress a different model on the same backend. Selection
must distinguish backend-wide cooldown from exact backend/model unavailability.

### `cooldowns` and probe ownership

Canonical state currently documents `cooldowns` as a bare timestamp map
(`skills/compound-v/state-machine.md:155-175`, `skills/compound-v/state-machine.md:205-215`), but
`validate_state`, `resume_assignment`, and `select_frozen_member` never read it. The only half-open
logic is prose (`commands/v-resume.md:27-32`; `skills/compound-v/failure-policy.md:123-126`). There
is no owner, lease, timestamp parser, atomic acquisition, or stale-owner reconciliation.

Gap: a successful job already in flight before `opened_at` must not clear a newer cooldown. Arrival
order is not causal order. Only a result from the leased half-open job (or an ordinary job launched
after the relevant cooldown generation) can clear it. The spec's statement that old in-flight
results “may ... clear state” needs this generation/launch-time guard in the plan.

### `network_pause` and batch evidence

Neither `state.json` shape nor any Python helper contains `network_pause`, batch identity, provider
success evidence, or an ordered observation marker. Jobs contain lifecycle/assignment fields only
(`skills/compound-v/state-machine.md:146-179`). The policy API has no job id, batch id, current time,
or evidence input (`scripts/compound-v-failure-policy.py:240-248`).

Gap: “two distinct providers in the same batch with no intervening success” cannot be validated
from the proposed evidence rows `{backend, job_id}` alone after a crash. The state transition must
be based on a dispatcher-owned batch identifier/order and persisted atomically, or explicitly be a
live-batch-only inference whose partial evidence is discarded on resume. A later success must not
clear a pause opened for an unrelated batch/generation.

### Time, lease liveness, and job timeout

Current breaker validation accepts any non-empty `opened_at` string
(`scripts/compound-v-pool-state.py:37-73`); it does not parse timezone awareness. Probe lease length
depends on the manifest job timeout, while pool-state validation already receives the manifest job
list (`scripts/compound-v-pool-state.py:337-379`). Liveness truth is separately derived from the
recorded baseline/worktree/process (`skills/compound-v/state-machine.md:232-234`).

Python 3.9 does not reliably accept a terminal `Z` through `datetime.fromisoformat`; the time
helper must normalize it to `+00:00`, reject naive/non-finite data, compare aware UTC instants, and
emit one canonical form. Probe reclamation must use both lease expiry and existing owner liveness;
expiry alone cannot steal a legitimately running timeout-bounded worker.

## 3. Sibling Code

### Existing transient retry path

Entry: every class in `RETRYABLE` reaches one generic branch
(`scripts/compound-v-failure-policy.py:309-320`). Edge handling: per-class cap, run cap, computed
jitter, and provider delay. Latent bug: `_backoff` returns any positive provider delay before the
`BACKOFF_CAP` operation (`scripts/compound-v-failure-policy.py:76-90`). A direct five-day injection
returns `backoff_seconds: 432000`, and the dispatcher then sleeps that value in foreground
(`agents/parallel-dispatcher.md:232-233`). This is the concrete hang PR 3 must close universally.

### Existing out-of-credits pool advance

Entry: pool context is all-or-nothing and current slot/backend must agree
(`scripts/compound-v-failure-policy.py:138-210`). It scans forward, skipping unavailable/open
members, consumes the run budget, clears/replaces only the current assignment, and falls through to
the concrete fallback after ring exhaustion (`scripts/compound-v-failure-policy.py:268-298`). This
is the closest sibling and must be read as a whole.

Latent coupling: policy computes `next_pool_index`, then the dispatcher calls pool-state `select`,
which scans again from that index (`agents/parallel-dispatcher.md:232-236`). Cooldown/probe state
changing between those two decisions can change the selected slot. Mutation, validation, and
launch therefore need one serialized decision boundary.

### Existing classifier priority

Specific rules run in list order. The z.ai table currently groups codes 1302, 1305, 1308, 1310,
1311, 1316, and 1317 under `rate_limited`
(`scripts/compound-v-classify-failure.py:123-154`). `_extract_retry_after` recognizes only integer
countdowns in seconds/minutes/hours/days and returns relative seconds
(`scripts/compound-v-classify-failure.py:248-264`). A documented-style message without its business
code that contains both a resettable usage-window phrase and “insufficient balance” is classified
`out_of_credits` today because that generic z.ai needle wins.

Latent bug: full rendered messages, code-absent messages, and specific-code-before-generic priority
are not represented by the present synthetic z.ai selftests
(`scripts/compound-v-classify-failure.py:304-324`). PR 3's negative control must mutate the actual
priority/needle behavior, not merely assert a new enum exists.

### Worker and collection boundary

Codex captures stderr, z.ai classifies the Claude JSON result file rather than its stderr
(`scripts/compound-v-run-codex-worker.sh:305-370`;
`scripts/compound-v-run-zai-worker.sh:274-305`). Both are process-group timeout bounded; z.ai uses
the same `claude -p` transport against `ANTHROPIC_BASE_URL`
(`scripts/compound-v-run-zai-worker.sh:212-237`). The canonical result is strict
`additionalProperties:false` (`schemas/job_result.schema.json:5-19`). Any new result field therefore
requires schema-first coordination; otherwise a correctly enriched worker result is rejected by
collect.

## 4. External APIs

Phase 1A found no provider HTTP client or SDK in this path. The code launches CLIs and reads captured
stdout/stderr: codex through `codex exec` (`scripts/compound-v-run-codex-worker.sh:315-354`) and z.ai
through an Anthropic-compatible `claude -p` process (`scripts/compound-v-run-zai-worker.sh:217-237`).
Consequently raw HTTP headers are not a shared-state source. Provider contract/version verification
belongs to the parallel Phase 1C audit; PR 3 code must consume only observed CLI error text and
normalized `job_result` fields.

## 5. Regression Surface

| Existing path | Regression if PR 3 is wrong | Required regression case |
|---|---|---|
| Success/blocked result normalization | stale reset metadata drives policy after success/scope block | success and blocked carry no failure reset/class |
| Codex/Claude short 429 | first transient reroutes too eagerly | first `<=60s` event retries same pair once |
| Non-pool short retry | pool semantics alter legacy routing/counters | same actions/caps and concrete backend |
| Non-pool long wait | process sleeps hours/days | resumable halt with absolute next retry; no long backoff |
| Pool second 429 | keeps hammering or opens permanent breaker | cooldown source, advance only current job |
| Overloaded second event | treated as permanent/down forever | transient cooldown, no `circuit_open` |
| z.ai 1113/1309/1314 | credits become retry storm | `out_of_credits`, existing breaker/fallback |
| z.ai 1302 | throttle becomes credits/window | `rate_limited` with first retry behavior |
| z.ai 1305 | overload remains generic throttle | `overloaded` |
| z.ai 1308/1310/1316-1321 | knowingly futile retry | `usage_window_exhausted`, absolute reset |
| z.ai 1311 | entire backend disabled | exact model/slot advance, no backend breaker |
| z.ai 1313/1315 | automatic retry of human-action fault | `auth`, halt/permanent breaker path |
| Code-absent z.ai rendered message | synthetic code fixtures pass while real CLI fails | full documented text selects specific class first |
| Frozen weighted ring | cooldown deletes/reweights slots | indices/models unchanged; matching slots skipped |
| Two cooling, one healthy | scan loops or picks cooled slot | deterministic third-provider selection |
| All unavailable/open/cooling | repeated wraparound spends budget | one resumable halt + earliest known retry |
| Existing out-of-credits ring advance | cooldown changes permanent fallback semantics | PR 2 cases remain byte-for-intent |
| Existing auth/context/timeout/other | new vocabulary captures unrelated errors | old class decisions unchanged |
| Run retry budget | reroute resets total | every relaunch consumes; resume preserves |
| Per-class attempt budget | old assignment's attempts poison new one | fork/reset assignment-local count only |
| Active cooldown | selector launches forbidden backend | skip all backend-weighted slots |
| Expired idle cooldown | several jobs probe at once | exactly one atomic lease owner |
| Active probe lease | resume steals live probe | owner liveness + timeout/grace honored |
| Dead/expired probe owner | backend stays locked forever | one safe lease reclamation |
| Old in-flight success | clears newer cooldown | generation/launch guard rejects stale clear |
| Probe transient/permanent result | wrong state family survives | renew cooldown or transition to existing breaker |
| Single network failure | needless provider hopping | same-assignment bounded retry |
| Endpoint-specific failure + success | global pause kills healthy work | only endpoint backend cools/reroutes |
| Two-provider correlated failure | third launch burns remaining budget | one network pause, no fan-out |
| Network recovery | three simultaneous probes | one real-job network lease |
| Crash/resume before expiry | resume ignores cooldown/pause | no forbidden launch |
| Status | old string assumption crashes/misreports | reason, absolute time, owner, pause evidence; no metrics |
| Schema/collector/workers | enriched result rejected/dropped | round-trip both new enums and optional `retry_at` |
| Python 3.9 | local 3.14 passes incompatible timestamp parsing | selftests run under 3.9 with `Z` fixtures |

The current positive denominator is real—classifier 55, policy 37, pool-state 60, collector 94,
z.ai worker stub 31, zero failures—but none of those tests detects disabled cooldown skipping,
uncapped provider waits, duplicate probe ownership, code-absent z.ai window text, or network-pause
fan-out. PR 3 acceptance must include planted in-memory negative controls for those mutations.

## 6. DRY Findings

1. **Slot viability is duplicated.** Failure-policy scans at
   `scripts/compound-v-failure-policy.py:112-135`; pool-state scans at
   `scripts/compound-v-pool-state.py:195-233`. Extend one selection authority rather than copying
   cooldown/probe tests into both independently.
2. **Circuit validation is duplicated.** `_validate_pool_context` validates the exact breaker shape
   at `scripts/compound-v-failure-policy.py:138-187`; `_circuit_open_errors` repeats it at
   `scripts/compound-v-pool-state.py:37-73`. Canonical cooldown/network validation belongs in
   pool-state; policy inputs must be validated using the same definitions or shared pure helpers.
3. **Result vocabulary is duplicated.** Classifier retryability, policy retryability/caps, schema
   enum, collector CLI choices, backend contract, adapters, and worker emitters each repeat the
   class/reset shape. All listed consumers must change together; silently adding a classifier enum
   is insufficient.
4. **Resume contracts are deliberately duplicated.** The pool assignment rule is declared
   byte-identical across `commands/v-resume.md`, `agents/parallel-dispatcher.md`, and
   `skills/compound-v/state-machine.md` (for example `commands/v-resume.md:15-19`). Cooldown/probe
   additions that affect this rule must be updated atomically and checked for drift.
5. **Timestamp semantics have no implementation.** Existing code writes/reads timestamp-shaped
   strings only in prose. Introduce one Python 3.9-safe parser/normalizer and reuse it for cooldown,
   retry-at, network pause, and leases; do not grow separate ad-hoc parsers in status/policy/pool
   code.

## 7. Design constraints for the spec

The plan must treat all **32** constraints below as hard requirements.

1. MUST cap every foreground `backoff_seconds` at 60, including provider-supplied waits.
2. MUST represent waits over 60 seconds as persisted absolute state plus reroute/resumable halt,
   never `sleep`.
3. MUST preserve legacy non-pool short-retry actions/counters.
4. MUST add `usage_window_exhausted` and `model_unavailable` to every result/policy vocabulary
   consumer in one coordinated change.
5. MUST classify z.ai specific codes/messages before generic balance/rate-limit substrings.
6. MUST test full documented z.ai renderings both with and without numeric codes.
7. MUST parse only observed strict reset formats; unknown formats fall back to bounded backoff.
8. MUST normalize terminal `Z` for Python 3.9, reject naive timestamps, and compare aware UTC.
9. MUST reject negative, boolean, non-finite, and malformed delay/time inputs fail-closed.
10. MUST preserve `total_retries` across backend changes and `/v:resume`.
11. MUST make the short throttle/overload transition assignment-local: one retry, then cooldown.
12. MUST fork/reset per-class attempts on a new concrete assignment without resetting run budget.
13. MUST keep frozen `pool_members` and weighted positions byte-for-intent unchanged.
14. MUST skip every weighted slot of a backend under an active backend-wide cooldown.
15. MUST treat `model_unavailable` as backend/model-specific, not a backend breaker/cooldown.
16. MUST halt after one bounded scan when no slot is viable and expose the earliest known retry.
17. MUST keep transient state separate from `circuit_open`; only credits/auth use the existing
    permanent breaker family.
18. MUST validate canonical cooldown objects before freeze/select/resume/launch.
19. MUST migrate legacy bare timestamp cooldowns at one explicit seam and never write them again.
20. MUST acquire an expired backend probe lease atomically under serialized state mutation.
21. MUST allow exactly one live probe owner and validate that owner against an existing job.
22. MUST derive lease duration from job timeout plus termination grace and reconcile owner
    liveness before reclamation.
23. MUST prevent a result launched before the current cooldown generation from clearing it.
24. MUST let only an eligible probe/causally newer success clear cooldown state.
25. MUST serialize policy decision, pool selection, state validation, persistence, and launch so a
    second viability scan cannot choose a different forbidden slot.
26. MUST keep one executable slot-viability authority; policy and pool-state may not drift.
27. MUST persist enough batch identity/order to prove two-provider/no-intervening-success network
    evidence, or explicitly constrain correlation to live batch state and discard incomplete
    evidence after a crash.
28. MUST not cross-provider-hop on the first generic network failure.
29. MUST open a global network pause only for two distinct concrete providers and no success in
    that batch; status must show the evidence, not certainty.
30. MUST prohibit all provider launches during an active network pause while allowing local
    collect/scope-gate work.
31. MUST serialize network recovery to one real-job probe and preserve frozen assignments.
32. MUST add negative controls proving tests fail for uncapped sleep, disabled cooldown skipping,
    double probe, code-absent z.ai misclassification, and network fan-out.

The spec is otherwise compatible with the existing architecture, but its phrase that an old
in-flight result “may ... clear state” is unsafe without constraints 23–24, and its network evidence
shape is insufficient without constraint 27. These are planning blockers, not optional review
polish.

## 8. File Touch Map (for Phase 2 partitioning)

**23 candidate files; 8 flagged SHARED RESOURCE.** This is the grep-derived regression surface,
not an instruction that every file belongs to one implementation task.

- `scripts/compound-v-classify-failure.py` — new classes, full z.ai precedence, bounded relative and
  strict absolute reset extraction; inline positive/negative tests.
- `scripts/compound-v-failure-policy.py` — universal inline-wait safety and pool-only transient,
  model-unavailable, network, retry-budget decisions; inline tests.
- `scripts/compound-v-pool-state.py` — canonical cooldown/network validation, frozen-slot selection,
  lease ownership, migration seam, resume validation; inline tests.
- `scripts/compound-v-collect-results.py` — preserve new enum/reset fields through normalization and
  conformance tests.
- `schemas/job_result.schema.json` — new enum members, optional absolute reset, numeric/timestamp
  constraints. **SHARED RESOURCE (canonical schema).**
- `examples/job_result.example.json` — keep the canonical result fixture synchronized.
  **SHARED RESOURCE (contract fixture).**
- `scripts/compound-v-run-codex-worker.sh` — carry classifier reset output into canonical result.
- `scripts/compound-v-run-zai-worker.sh` — carry absolute window reset and expanded z.ai classes;
  preserve events-log versus stderr transport.
- `scripts/compound-v-run-cursor-worker.sh` — keep classifier-backed canonical emission compatible
  with the enriched optional reset field.
- `scripts/compound-v-run-antigravity-worker.sh` — keep classifier-backed canonical emission
  compatible with the enriched optional reset field.
- `scripts/test-zai-worker-stub.sh` — worker-boundary regression for failure/reset emission.
- `skills/backend-launcher/SKILL.md` — canonical `job_spec -> job_result` vocabulary and transport.
  **SHARED RESOURCE (backend contract).**
- `skills/backend-launcher/adapter-codex.md` — Codex failure/reset transport and hidden-retry caveat.
- `skills/backend-launcher/adapter-claude.md` — Claude enum/reset transport and caller-built result.
- `skills/backend-launcher/adapter-zai.md` — z.ai message families, absolute reset, no-header boundary.
- `skills/compound-v/failure-policy.md` — authoritative classify/decide/act table and state mutation
  semantics. **SHARED RESOURCE (policy contract).**
- `skills/compound-v/state-machine.md` — canonical cooldown/network/lease state and resume rules.
  **SHARED RESOURCE (state contract).**
- `agents/parallel-dispatcher.md` — serialized apply/persist/launch path, retry/reroute/probe/network
  behavior. **SHARED RESOURCE (execution contract).**
- `commands/v-resume.md` — validate pauses/leases, reconcile owners, one-probe recovery, preserved
  budget/assignment. **SHARED RESOURCE (byte-identical resume contract).**
- `commands/v-status.md` — render canonical cooldown reason/time/owner and network evidence without
  invented health/capacity.
- `scripts/compound-v-dashboard.py` — keep the `/v:status --html/--serve` state view degrade-safe
  when cooldowns become objects and `network_pause` appears.
- `skills/compound-v/execution-manifest.md` — document runtime pool behavior without changing
  weights/config. **SHARED RESOURCE (manifest/config registry).**
- `CHANGELOG.md` — user-visible PR 3 behavior and merge dependency.
