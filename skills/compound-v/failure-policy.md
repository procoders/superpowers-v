# Failure Policy — classify → decide → act (graceful backend failures)

> *"A supe goes down mid-fight, you don't keep punching the corpse. You read what killed them, and you send the right replacement."*

When a dispatched job comes back non-success, the dispatcher does **not** guess and does **not** blindly retry. It runs a two-stage deterministic pipeline — **classify** the failure, then look up the **action** in a static decision table — and acts on the result. There is **no daemon, no event loop**: the "circuit breaker" is just a handful of `state.json` fields the dispatcher reads at batch boundaries.

The two scripts below **are** the tables. This doc explains how the dispatcher wires them together; it does not re-encode the numbers (when they disagree, the scripts win).

- **Classifier** — [`scripts/compound-v-classify-failure.py`](../../scripts/compound-v-classify-failure.py)
- **Decision table** — [`scripts/compound-v-failure-policy.py`](../../scripts/compound-v-failure-policy.py)

The re-route is the **same** env-aware codex→claude rewrite as [`routing-policy.md`](routing-policy.md) — invoked here at **runtime** on an out-of-credits event, not only at `/v:init`.

---

## The loop (what the dispatcher runs on a non-success `job_result`)

```
job_result.status != success
        │
        ▼
1. classify  ── compound-v-classify-failure.py --backend <B> --exit-code <N> [--stderr-file P]
        │            → {failure_class, retryable, matched}
        │            (job_result.failure_class already carries this for codex; recompute for claude
        │             from the stream-json api_retry.error enum — see adapter-claude.md)
        ▼
2. decide    ── compound-v-failure-policy.py --failure-class <C> --backend <B>
        │            --attempts <state.attempts[job]> --total-retries <state.total_retries>
        │            --max-total-retries <state.max_total_retries> [--retry-after S]
        │            → {action, reason, backoff_seconds, reroute_to, escalate_tier, circuit_break}
        ▼
3. act on `action` ∈ {proceed, retry, reroute, halt}   (table below; loud reporting always)
```

`failure_class` rides on the `job_result` ([`schemas/job_result.schema.json`](../../schemas/job_result.schema.json)) — the Codex worker emits it; it is `null` on success/blocked. A `blocked` result is a **scope-gate** halt, not a backend failure, and never enters this loop.

---

## 1. Classification taxonomy (class → signature → retryable)

Classify by the error **TYPE**, never the HTTP status — the status is ambiguous (OpenAI `insufficient_quota` and a throttle are **both** 429; an Anthropic credit error is a **400/402, not a 429**). The classifier branches on the captured stderr (codex) or the stream-json `api_retry.error` enum (claude), in priority order (most specific first), with `out_of_credits` checked **before** `rate_limited`.

| `failure_class` | Signature (where it comes from) | Retryable |
|---|---|---|
| `none` | exit 0 — success, no failure | — |
| `out_of_credits` | quota/billing exhausted. codex: `insufficient_quota`, `hit your usage limit`, `billing_hard_limit`. claude enum: `billing_error` (a 400/402, **not** 429) | **No** |
| `rate_limited` | throttled. codex: `rate limit`, `429`, `too many requests`. claude enum: `rate_limit` | Yes |
| `overloaded` | 5xx / server overloaded. codex: `overloaded`, `503`, `502`. claude enum: `overloaded_error`, `529` | Yes |
| `auth` | bad/expired key or login. codex: `invalid_api_key`, `401`, `not logged in`. claude enum: `authentication_failed`, `oauth_org_not_allowed` | **No** |
| `context_length` | prompt too large. codex: `context_length_exceeded`, `maximum context length`. claude enum: `prompt is too long`, `max_output_tokens` | **No** (reroute) |
| `timeout` | our wall-clock wrapper fired — **exit 124** | Yes |
| `network` | transport/DNS, no HTTP status: `ECONNRESET`, `connection refused`, `getaddrinfo` | Yes |
| `other` | unclassified non-zero | Yes (once) |

The retryable set is exactly `{rate_limited, overloaded, timeout, network, other}`. `out_of_credits` / `auth` / `context_length` are deliberately **not** retryable — retrying a quota or auth failure only burns wall-clock and rate-limits you harder.

---

## 2. Per-class action table (matches the policy script exactly)

`compound-v-failure-policy.py` returns one `action`. This is the table it encodes — read the script for the authoritative numbers:

| `failure_class` | `action` | Effect | Caps |
|---|---|---|---|
| `none` | `proceed` | nothing to do | — |
| `out_of_credits` (fallback exists) | `reroute` | `circuit_break` the backend for the run + `reroute_to` the fallback (codex→claude) | never retried |
| `out_of_credits` (no fallback, e.g. claude) | `halt` | `circuit_break`; run stays resumable — top up, then `/v:resume` | never retried |
| `auth` | `halt` | `circuit_break`; human re-auths via `/v:init`, then `/v:resume` | never retried |
| `context_length` | `reroute` | `escalate_tier` (bigger tier); if already deepest, split the job → back to planning | never retried |
| `rate_limited` | `retry` → `halt` | retry SAME backend, exp backoff + jitter, honor `retry-after` | per-class **3**, then run-level `max_total_retries` |
| `overloaded` | `retry` → `halt` | same | per-class **2**, then run-level |
| `network` | `retry` → `halt` | same | per-class **2**, then run-level |
| `timeout` | `retry` → `halt` | retry once, longer | per-class **1**, then run-level |
| `other` | `retry` → `halt` | retry once, then stop | per-class **1**, then run-level |

**Backoff:** exponential (`base 2 · 2^attempts`, jittered to de-sync siblings, capped at **60s**); a provider `retry-after` **overrides** the computed value. Retries are capped **twice** — per-class (above) **and** by the run-level `max_total_retries` (default 12), the anti retry-storm guard. Whichever ceiling hits first → `halt`.

### Acting on each `action`

- **`proceed`** — success; merge/collect as normal (this branch is only reached if something upstream mislabeled a success).
- **`retry`** — re-dispatch the **same** backend after `backoff_seconds`; bump `attempts[job]` and `total_retries` in `state.json` first. Same prompt (`jobs/<id>.prompt.md`), same scope gate on return.
- **`reroute`**:
  - `circuit_break: true` (out_of_credits) → set `circuit_open[backend]=true`, and re-route **this job and every remaining same-backend job** in the run through the env-aware **codex→claude** rewrite ([`routing-policy.md`](routing-policy.md) §Env-aware Claude-only fallback). Announce it loudly (below).
  - `escalate_tier: true` (context_length) → re-resolve the job at a **bigger tier** via [`compound-v-resolve-model.py`](../../scripts/compound-v-resolve-model.py) and re-dispatch. If already at the deepest tier, the job is too big for one shot — **split it** (back to planning/partition), don't loop.
- **`halt`** — mark the job `failed` in `state.json`, keep the run **`/v:resume`-able**, and (ralph-tui-style) **continue other independent jobs** — a sibling's 429 must not kill jobs that have nothing to do with it. The run only stops dead when the **last viable backend** is exhausted.

---

## 3. The circuit breaker — `state.json` fields, checked at batch boundaries

Borrowed from LiteLLM / OpenRouter, realized as **static state**, not a process. The dispatcher reads these at the start/edges of each batch — there is nothing running between batches.

| Field | Shape | Meaning |
|---|---|---|
| `attempts` | `{ "<job-id>": n }` | how many times this job has been retried (the policy's `--attempts`) |
| `cooldowns` | `{ "<backend>": "<iso-ts>" }` | a transient-failed backend is **deprioritized** until this timestamp (retryable next batch) |
| `circuit_open` | `{ "<backend>": bool }` | `true` = backend is out for the run (credit-exhausted or auth) |
| `total_retries` | `int` | run-wide retry counter (the policy's `--total-retries`) |
| `max_total_retries` | `int` (default 12) | run-level retry budget — the anti retry-storm cap |

**Breaker states** (no daemon — just how the fields are read):
- **open** — `circuit_open[backend]==true`. Skip the backend entirely this run. Only `out_of_credits` (confirmed) and `auth` open it.
- **half-open** — a backend whose `cooldowns[backend]` timestamp has **expired**: probe it **once** at the next batch start before full re-dispatch.
- **closed** — normal. A success clears any `cooldowns[backend]` entry.

See [`state-machine.md`](state-machine.md) for the resume behavior built on these fields.

---

## Borrowed patterns (LiteLLM / OpenRouter / ralph-tui)

- **Deprioritize, don't remove.** A transient-failed backend gets a short **cooldown timestamp** (eligible again next batch), not an open breaker. Only a confirmed `out_of_credits` (or `auth`) opens the breaker for the whole run. A 429 is a "come back in a minute," not a "you're done."
- **ralph-tui safe default for disjoint partitions.** A job that exhausts its retry budget is marked `failed` and the **batch CONTINUES** — independent jobs don't die because a sibling got throttled. The run halts only when the **last viable backend** is exhausted (→ `/v:resume`).
- **Two-layer fallback (OpenRouter).** Layer 1 is per-class retry on the same backend (transient); layer 2 is the cross-backend re-route (out_of_credits). The re-route reuses the existing env-aware rewrite — it is not a second code path.
- **Loud reporting (never silent).** A re-route or circuit-break is **always** surfaced — in [`/v:status`](../../commands/v-status.md) (circuit-open backends, per-job attempts, active re-routes) and in the run summary: *"codex out of credits → N jobs re-routed to claude/opus, est. cost ↑."* **Never quietly swap a cheap backend for an expensive one** — the user must see the cost change.

---

## Anti-patterns (do NOT)

- ❌ **Retry `out_of_credits` or `auth`.** They never self-heal by retrying; you only burn time and rate-limit harder. Circuit-break (+ re-route for credits) or halt.
- ❌ **Cap retries by count alone.** Cap by **count AND wall-clock** — per-class ceiling *and* the run-level `max_total_retries`. One job spinning on 429s must not exhaust the whole run.
- ❌ **Hammer a quota-exhausted backend.** Once the breaker is open, stop dispatching to it for the run.
- ❌ **Classify by HTTP status.** Classify by error **TYPE**: OpenAI `insufficient_quota` and a throttle are both 429; the Anthropic credit error is a **400/402, not a 429**. The status alone will mis-route you.
- ❌ **Silently swap backends.** Every re-route/circuit-break is announced (status + summary), with the cost direction called out.

---

## Cross-references

- Classifier: [`scripts/compound-v-classify-failure.py`](../../scripts/compound-v-classify-failure.py) · Decision table: [`scripts/compound-v-failure-policy.py`](../../scripts/compound-v-failure-policy.py)
- The re-route mechanism (env-aware codex→claude): [`routing-policy.md`](routing-policy.md)
- Circuit-breaker fields + resume: [`state-machine.md`](state-machine.md)
- Dispatcher wiring (the executable): [`agents/parallel-dispatcher.md`](../../agents/parallel-dispatcher.md)
- The job_result contract carrying `failure_class`: [`backend-launcher/SKILL.md`](../backend-launcher/SKILL.md) · [`schemas/job_result.schema.json`](../../schemas/job_result.schema.json)
- Phase-3 dispatch step: [`phase-3-parallel-opus-dispatch.md`](phase-3-parallel-opus-dispatch.md)
