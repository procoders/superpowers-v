# LLM Provider Load-Balancing Knowledge Base

Maintained by Compound V Phase 1B advisor. Append at the bottom on each pass.

Scope: routing work across multiple LLM providers or accounts — strategies, fairness under
heterogeneous meters, quota introspection surfaces, and failure interaction. Adjacent domain
`metered-llm-subscriptions` (the meters themselves) is folded in here rather than split, because
the two are only useful together.

---

## Updated 2026-08-01 — tier model pools (round-robin across three metered subscriptions)

Source audit: [`../2026-08-01-tier-model-pool.md`](../2026-08-01-tier-model-pool.md)

### Matrix A — what production multi-provider routers actually ship

| System | Default strategy | Alternatives | Unweighted round-robin as primary? |
|---|---|---|---|
| [LiteLLM Router](https://docs.litellm.ai/docs/routing) | `simple-shuffle` — weighted by rpm/tpm, random when neither is set | `least-busy`, `usage-based-routing-v2` (lowest TPM), `latency-based-routing`, `cost-based-routing` | No |
| [OpenRouter](https://openrouter.ai/docs/guides/routing/provider-selection) | weighted by **inverse square of price**, excluding providers with outages in last 30s | `sort: price` / `sort: latency` — either **disables** load balancing | No |
| [Portkey](https://portkey.ai/docs/product/ai-gateway/load-balancing) | `loadbalance` with explicit weights normalized to 1; `weight: 0` drains a target | `fallback`, `conditional`; all three compose | No |
| AWS ALB (general LB principle) | round robin is offered — and the documented reason to leave it is unequal request cost | `least_outstanding_requests` | Yes, and it's the one you migrate off |

**Generalized rule.** Every production LLM router expresses capacity as a **weight** or reads a
**live signal**. None uses a bare rotation. The one widely-shared tool that *calls itself*
round-robin — [CC-Router](https://github.com/VictorMinemu/CC-Router), "Round-robin proxy for
multiple Claude Max subscriptions" — actually does *"detects 429/529 responses and coolsdown
accounts; picks the least-loaded one."*

**Design corollary.** If a rotation must ship for scope reasons, ship it with an optional integer
`weight` (default 1) from day one. Deterministic integer weighted round-robin (expand the member
list by weight, then modulo) reproduces a plain rotation exactly at all-weights-1, adds no
randomness, and avoids a schema-breaking follow-up.

### Matrix B — the three coding-subscription meters (as of 2026-08)

| Provider | Meter unit | Windows | Remaining-quota readable at runtime? | Per-job tokens readable? |
|---|---|---|---|---|
| **Anthropic Max** (Claude Code) | messages / compute-hours, **shared across Claude.ai + Claude Code** ([support](https://support.claude.com/en/articles/11145838)) | 5h rolling + weekly | **No.** No endpoint/header for subscription remaining. Admin [Rate Limits API](https://platform.claude.com/docs/en/manage-claude/rate-limits-api) returns *configured* limits for **API orgs only** (`"The Admin API is unavailable for individual accounts"`). OTel `claude_code.token.usage`/`cost.usage` = consumption, not remaining | **No** for a `Task` subagent |
| **OpenAI Codex** (ChatGPT plan) | message quota, `primary` + `secondary` | 5h rolling + plan-dependent secondary | **Probably** — `token_count` events carry `rate_limits.{primary,secondary}.{used_percent,window_minutes,resets_in_seconds}`. Readable from `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` ([codex-ratelimit](https://github.com/xiangz19/codex-ratelimit)). **Caveat:** [openai/codex#14728](https://github.com/openai/codex/issues/14728) documents `rate_limits: null` specifically in **exec mode**; fix version unconfirmed | Yes |
| **z.ai GLM Coding Plan** | **credits**, a published function of tokens | 5h credits reset 5h after consumption; weekly credits reset every 7 days ([docs](https://docs.z.ai/devpack/overview)) | **Probably** — unofficial `/api/monitor/usage/quota/limit` (+ `model-usage`, `tool-usage`) on `https://api.z.ai` (or `open.bigmodel.cn`), `Authorization: {token}` **without** `Bearer` ([opencode-glm-quota](https://github.com/guyinwonder168/opencode-glm-quota)). ISOLATED — one source, absent from official docs | Yes (and credits are computable from them) |

**z.ai credit formula (published, official):**
`credits = (in × Min + cachedIn × Mc + out × Mout) / 10000`
Multipliers — GLM-5.2 `6.9/1.7/24`, GLM-5-Turbo `5.7/1.5/21`, GLM-4.7 `4.6/1.2/16`,
GLM-4.6V `1.2/0.3/2.7`; MCP tools output-multiplier `1.2`.
**Peak** Mon–Fri 14:00–18:00 UTC+8; off-peak charged at **50%** of standard.

**Counter-intuitive takeaway worth remembering.** The provider most people assume is opaque
(z.ai) is the **most** introspectable of the three — its cost function is published outright.
The one that looks safest because it's first-party (Anthropic Max) is the **only** genuinely dark
meter, and in Compound V it is already recorded as such:
`scripts/compound-v-usage-extract.py` → `UNMEASURED_BACKENDS = frozenset(("agy","antigravity","claude","devin"))`.

### Rule — round-robin equalizes numerators across unrelated denominators

Textbook complaint: "even traffic ≠ even load" (unequal request cost). With metered *subscriptions*
there are two further layers:

1. **Unit mismatch.** One job = `1/N` of a message budget, `1/M` of a different message budget,
   and `k` credits. Equalizing the top number of three different fractions is not balance.
2. **Clock dependence.** z.ai's 2x peak multiplier means the *same* manifest with the *same*
   counter burns twice the credits depending on the hour the run starts. Any "even burn" claim is
   false for half the working week unless time-of-day is modelled.

So: a rotation is a legitimate v1 *primitive*, but it must be **named** rotation and its claim
scoped to **job counts**, never quotas/tokens/credits/wall-clock.

### Rule — a shared-meter member is not an equal pool member

If one pool member draws from the same subscription as the orchestrator/interactive session
(Anthropic Max: *"usage limits that are shared across Claude and Claude Code"*), spreading work
onto it evenly means the operator's own next turn is the first thing throttled. Two of the three
meters are pure worker capacity; the third is the seat you're sitting in. Precedent that this is
not theoretical: Anthropic reset all Pro/Max 5h+weekly limits after fixing a bug where Claude Code
*"spawn[ed] excessive parallel subagents, burning through usage faster than expected"*
([ClaudeDevs post](https://x.com/ClaudeDevs/status/2061501787769893055) — REPORTED, snippet-sourced).

Default position: **exclude the shared-meter member from a default pool, or down-weight it.**
Opt-in, never opt-out.

Community signal on Max opacity (≥8 distinct threads on the vendor's own tracker, 2026):
[#52135](https://github.com/anthropics/claude-code/issues/52135) (opened 2026-04-22, closed as not
planned) plus its cross-references #50742, #47587, #51715, #51219, #41174, and separately #52921,
#9424. Establishes *"Max accounting is opaque and depletes faster than users model"* — **not** any
specific mechanism.

### Matrix C — failure interaction (rotation + reroute)

| Pathology | Shape | Mitigation used in real systems |
|---|---|---|
| Retry storm / thundering herd | everything retries the moment the window clears | exponential backoff + **full jitter**, capped; a run-level retry budget |
| Cascading exhaustion | last healthy member absorbs the remainder and dies too | circuit-break per backend for the run; surface a **retry-after** so the caller knows *when*, not just *that* — [LiteLLM #27823](https://github.com/BerriAI/litellm/issues/27823) (2026-05-13, fixed by PR #30098) is the canonical write-up of getting this wrong |
| Pool resize mid-run | a cooled-down member is removed, `len(pool)` changes, every subsequent modulo assignment shifts | **deprioritize, don't remove** (LiteLLM `cooldown_time`/`allowed_fails`; OpenRouter keeps outage-flagged providers as fallbacks). Freeze the member list at run start; handle unavailability by **skipping**, never resizing |
| Ping-pong between members | job bounces A→B→A, each hop resetting its per-class retry counter | bind the breaker to the **backend**, not the job; make it structurally impossible for the selector to pick an open breaker |

**Determinism rule for any counter-based assignment.** A counter defined over *observed dispatch
order* is not reproducible: batches complete out of order, per-backend concurrency caps change
slot-filling, and failures relocate jobs. Define it over a **plan-time, git-tracked order** (the
manifest's declared job order) and persist both the frozen member list and each assignment.

### Anti-patterns catalogue (do NOT)

- Do NOT claim "balances quotas" for anything that counts jobs.
- Do NOT let a rotation move work **down** a trust ordering — a counter is not a justification.
  (Compound V's own rule: adaptive signals *"only ever escalate UP … never auto-select a
  lower-trust backend."*)
- Do NOT clear a recorded assignment on a failure class whose policy retries the **same** backend
  — the assignment is exactly what makes the resume reproducible.
- Do NOT classify quota failures by HTTP status: OpenAI `insufficient_quota` and a throttle are
  both 429; the Anthropic credit error is a 400/402.
- Do NOT publish a percentage or "balance score". Counts only.

### Open lead to verify on the next pass

- Does `codex exec` on the currently pinned codex-cli emit a populated `rate_limits` block, or
  still `null`? ([#14728](https://github.com/openai/codex/issues/14728) reads closed but carries no
  fix version.) One live probe settles it.
- Does `GET https://api.z.ai/api/monitor/usage/quota/limit` respond as documented by the
  third-party plugin? ISOLATED single source; needs one live call.

---

## Updated 2026-08-01 — cooldown causality and correlated-network evidence

Source audit: [`../2026-08-01-rate-limit-rerouting.md`](../2026-08-01-rate-limit-rerouting.md)

### Rule — cooldown recovery is causal, not collection-ordered

Concurrent workers finish out of order. A success from a request launched before a newer failure
opened a cooldown must not clear that cooldown merely because its result was collected later.
Only the leased half-open probe, or a successful attempt whose recorded generation/start is newer
than the cooldown generation, may clear it. Pre-cooldown successes remain valid job results but
are not recovery evidence.

This is the same invariant as "exactly one half-open probe": permitting an older ordinary worker
to clear state would create an unleased second probe through result reordering.

### Rule — provider-reported `network` is not common-path outage evidence

z.ai code `1234` is a business error returned with HTTP 500, so receiving it proves the provider
sent a response. It can describe a provider-side transport/process problem, but cannot prove the
caller's DNS, VPN, proxy, or internet path is down. Source:
<https://docs.z.ai/api-reference/api-code>.

Keep two machine-readable scopes even if the UI groups both as network failures:

- `no_response`: locally observed DNS/TLS/connect/reset/timeout before a valid provider response;
- `provider_reported`: provider error envelope or completed stream reports an internal network
  failure.

Only independent `no_response` observations can contribute to a correlated global network pause.
Evidence must be deduplicated by backend + attempt, carry batch id + observed UTC time, and fall
inside a bounded correlation window. "Same batch" without a time bound is not correlation.

Anthropic notes that SSE errors can occur after HTTP 200; z.ai notes that streaming failures may
appear in `finish_reason` rather than the normal error envelope. A provider success therefore means
a completed successful worker, not connection establishment or first token. Sources:
<https://platform.claude.com/docs/en/api/errors>,
<https://docs.z.ai/api-reference/api-code>.

### Rule — a retry hint is a minimum, never a delay to truncate

Anthropic says retrying earlier than `retry-after` will fail. OpenAI defines `Retry-After` as a
minimum and recommends added jitter. If `provider minimum + jitter` exceeds an inline-wait cap,
park/reroute the work; do not retry at the cap. Missing/invalid hints use bounded non-zero
exponential backoff with jitter. Sources:
<https://platform.claude.com/docs/en/api/rate-limits>,
<https://developers.openai.com/api/docs/guides/rate-limits>.

Official Anthropic SDKs retry eligible transient errors twice by default, and OpenAI SDKs also
retry eligible rate limits. An orchestrator-level attempt counter is therefore a worker-launch
budget, not a physical provider-request counter. Keep that distinction visible.

### Rule — backend-wide cooldown is conservative, not provider truth

Anthropic API limits apply by model class; OpenAI limits vary by model and some model families
share a limiter. If a CLI does not expose limiter identity, a backend-wide cooldown is a
defensible fail-closed anti-storm choice, but it may suppress unrelated healthy models. Document
that availability trade-off and keep known assignment-specific failures such as model access out
of the backend-wide breaker. Sources:
<https://platform.claude.com/docs/en/api/rate-limits>,
<https://developers.openai.com/api/docs/guides/rate-limits>.

### Update — z.ai quota query now has an official Personal-plan surface

The previous open lead that z.ai usage introspection was only a reverse-engineered endpoint is no
longer the whole picture. z.ai now documents an official `glm-plan-usage` Claude Code plugin that
queries current Personal-plan quota and usage:
<https://docs.z.ai/devpack/extension/usage-query-plugin>.

This does not make percentage-driven cross-provider routing sound: the other providers' coding
subscription meters remain heterogeneous, and PR3's CLI-process contract need not install or poll
the plugin. Treat it as an observability option, not a routing signal.
