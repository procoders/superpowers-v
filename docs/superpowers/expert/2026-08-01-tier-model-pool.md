# Domain audit — tier model pools (round-robin across metered LLM subscriptions)

**Phase:** Compound V 1B (domain-expert)
**Date:** 2026-08-01
**Spec under audit:** [`docs/superpowers/specs/2026-08-01-tier-model-pool-design.md`](../specs/2026-08-01-tier-model-pool-design.md)
**Operator's stated goal (verbatim):** *"ровнее жечь квоты в трёх провайдерах"* — burn three providers' quotas more evenly.

**Reading key.** Every claim below is tagged:

- **[VERIFIED]** — I fetched the cited page in this session and the quote/field comes from that fetch, or I read the file in this repo.
- **[REPORTED]** — the claim comes from a search-result snippet or a secondary source I did not fetch directly. Treat as a lead, not a fact.
- **[ISOLATED]** — a single source, below the community-signal bar. Needs verification before it drives a design decision.

---

## 1. Domain(s) identified

1. **`llm-provider-load-balancing`** — routing work across multiple LLM providers/accounts; strategies, fairness, failure interaction.
2. **`metered-llm-subscriptions`** — the meters themselves: Anthropic Max, OpenAI/ChatGPT-plan Codex, z.ai GLM Coding Plan. Units, windows, introspection surfaces.

A third domain the spec touches but I leave to Phase 1A/1C: the repo's own dispatcher/state-machine internals.

---

## 2. Sources consulted

**Knowledge base.** `docs/superpowers/expert/_knowledge-base/` contains seven files; none covers provider load-balancing or subscription metering. `autonomous-agent-orchestration.md` is adjacent but is about agent orchestration patterns, not quota routing. **No KB reuse was possible; a new KB file is created (§9).**

**Recon.** `docs/superpowers/recon/` holds exactly one doc (`2026-07-11-fts5-cyrillic-tokenizer.md`) — unrelated. No Trigger-0 recon exists for this topic and none was handed to me.

**In-repo files read.** `skills/compound-v/routing-policy.md`, `skills/compound-v/failure-policy.md`, `schemas/job_result.schema.json`, `scripts/compound-v-usage-extract.py`, `README.md`, `CHANGELOG.md` (head), `AGENTS.md`, the spec itself.

**Pages fetched directly [VERIFIED source of the quotes attributed to them]:**

- [LiteLLM — Router / Load Balancing](https://docs.litellm.ai/docs/routing)
- [LiteLLM issue #27823 — no Retry-After when all deployments in cooldown](https://github.com/BerriAI/litellm/issues/27823)
- [Anthropic — Rate Limits API](https://platform.claude.com/docs/en/manage-claude/rate-limits-api)
- [Anthropic support — Claude Code usage limits](https://support.claude.com/en/articles/11145838)
- [anthropics/claude-code issue #52135](https://github.com/anthropics/claude-code/issues/52135)
- [z.ai devpack — Overview](https://docs.z.ai/devpack/overview)
- [z.ai devpack — FAQ](https://docs.z.ai/devpack/faq)
- [guyinwonder168/opencode-glm-quota](https://github.com/guyinwonder168/opencode-glm-quota) + [raw README](https://raw.githubusercontent.com/guyinwonder168/opencode-glm-quota/main/README.md)
- [openai/codex issue #14728](https://github.com/openai/codex/issues/14728)
- [xiangz19/codex-ratelimit](https://github.com/xiangz19/codex-ratelimit)
- [VictorMinemu/CC-Router](https://github.com/VictorMinemu/CC-Router)
- [ccusage — Codex guide](https://ccusage.com/guide/codex/)
- [Codex CLI rate-limit reset banking (danielvaughan)](https://codex.danielvaughan.com/2026/06/12/codex-cli-rate-limit-reset-banking-usage-optimisation-cost-control-profiles-token-budgets/)

**Search-only sources [REPORTED]:** [Anthropic rate-limit headers](https://docs.anthropic.com/en/api/rate-limits), [OpenRouter provider selection](https://openrouter.ai/docs/guides/routing/provider-selection), [Portkey load balancing](https://portkey.ai/docs/product/ai-gateway/load-balancing), [AWS ALB least-outstanding-requests](https://tech.spscommerce.com/2020/07/24/aws-alb-routing.html), [ClaudeDevs limit-reset post](https://x.com/ClaudeDevs/status/2061501787769893055), [Claude Code OTel metrics](https://signoz.io/docs/claude-code-monitoring/), [Claude Code headless output formats](https://code.claude.com/docs/en/headless).

**Queries run (12, in 3 parallel batches):** LiteLLM routing strategies · Anthropic rate-limit headers · Claude Code Max 5h window · z.ai quota API · OpenRouter provider routing · Codex CLI rate-limit headers · round-robin with heterogeneous backends · retry storm / thundering herd / circuit breaker · codex exec rate_limits JSONL · Claude Code OTel · ccusage blocks · claude-code-router round-robin projects · r/ClaudeAI+r/ChatGPTCoding multi-subscription juggling · Claude Code weekly-limit complaints · GLM credit multipliers · least-outstanding-requests vs round robin · Portkey weighted config · deterministic round-robin under parallel batches.

**Searches that returned nothing usable — stated so the absence is not read as a clean bill of health:** the two Layer-3 persona searches aimed at Reddit (`site:reddit.com` rotation across Claude/Codex/GLM, and `r/ClaudeAI OR r/ChatGPTCoding` multi-subscription burn) returned **no Reddit results at all** — the engine substituted blog and GitHub results. **I therefore have no Reddit/HN community evidence on the specific practice of rotating three coding subscriptions.** The community signal I do have comes from the `anthropics/claude-code` issue tracker (§4) and from the existence of purpose-built rotation tools (§3), which is a weaker but real proxy.

---

## 3. Q1 — Is round-robin the right primitive?

### 3.1 What comparable orchestrators actually do

| System | Default strategy | Other strategies offered | Unweighted round-robin available? |
|---|---|---|---|
| **LiteLLM Router** [VERIFIED] | `simple-shuffle` — "Picks deployments based on Requests per minute (rpm) or Tokens per minute (tpm)" with optional weights; "When rpm/tpm aren't provided, it randomly picks a deployment" | `least-busy` ("least number of ongoing calls"), `usage-based-routing-v2` ("lowest TPM usage"), `latency-based-routing`, `cost-based-routing` | **No.** The default is *weighted/random shuffle*, not a rotation. |
| **OpenRouter** [REPORTED] | Weighted by **inverse square of price**, after excluding providers with outages in the last 30s | `sort: price`, `sort: latency` — and setting either **disables load balancing entirely** | **No** |
| **Portkey Gateway** [REPORTED] | `loadbalance` with explicit per-target **weights**, normalized to sum 1; `weight: 0` drains a target without removing it | `fallback`, `conditional` routing; all three compose | **No** |
| **AWS ALB** (general LB, for the principle) [REPORTED] | round robin *is* an option — and the documented reason to leave it is exactly ours: it "splits requests among targets equally, regardless of the state of the target… may result in overloading of requests to one of the targets" when requests are unequal | `least_outstanding_requests` | Yes, and it is the one you're told to move off |

**Finding: no production multi-provider LLM router ships unweighted round-robin as its primary strategy.** All four express capacity as a *weight* or read a *live signal*. The nearest thing in the wild — [CC-Router](https://github.com/VictorMinemu/CC-Router), whose tagline is literally "Round-robin proxy for multiple Claude Max subscriptions" — describes its actual selection as [VERIFIED, README quote]: *"Rate limit awareness — detects 429/529 responses and coolsdown accounts; picks the least-loaded one."* Even the tool that calls itself round-robin is least-loaded-with-cooldown underneath.

### 3.2 Why the heterogeneity here is worse than the textbook case

The textbook complaint is "even traffic ≠ even load" — job costs vary, so equal counts ≠ equal work. That applies here (a docs edit and a multi-file refactor both count as 1). But this spec has a **second, sharper** problem: **the three meters are denominated in three different units, and one of them is a function of wall-clock time.**

| Provider | Meter unit | Windows | Cost of one "job" |
|---|---|---|---|
| Anthropic Max | messages / compute-hours, shared across Claude.ai + Claude Code [VERIFIED] | 5-hour rolling + weekly [REPORTED] | opaque; not exposed per-job |
| OpenAI Codex (ChatGPT plan) | message quota, `primary` + `secondary` windows [VERIFIED shape] | 5-hour rolling primary + a plan-dependent secondary [REPORTED] | opaque; percentages only |
| z.ai GLM Coding Plan | **credits**, computed from tokens [VERIFIED] | 5-hour credits ("resets 5 hours after consumption") + weekly ("resets every 7 days") [VERIFIED] | **exactly computable** — see formula below |

z.ai publishes the cost function outright [VERIFIED, docs.z.ai/devpack/overview]:

> "Model credit usage = (Input tokens × Input multiplier + Cached Input tokens × Cached Input multiplier + Output tokens × Output multiplier) / 10,000"

with multipliers GLM-5.2 `6.9 / 1.7 / 24`, GLM-5-Turbo `5.7 / 1.5 / 21`, GLM-4.7 `4.6 / 1.2 / 16`, GLM-4.6V `1.2 / 0.3 / 2.7`; MCP tools at output-multiplier 1.2. And a **time-of-day multiplier**: *"Peak hours: Monday to Friday, 14:00–18:00 Singapore Standard Time (UTC+8)"*, with off-peak charged at *"50% of the standard credit rate."*

So a single pool-routed job burns:

- `1/N` of an Anthropic message budget whose size you cannot read,
- `1/M` of a Codex message budget whose size you cannot read,
- and a z.ai credit amount that varies with output length **and doubles depending on what time the run starts**.

Round-robin equalizes the numerator across three unrelated denominators. That is not balance — it is three independent fractions that happen to have the same top number. **The spec's own Risks section already concedes the token half of this. It does not concede the units half or the clock half.**

The clock half matters concretely: the spec's non-goal *"No time-of-day routing to exploit z.ai's promotional off-peak window"* is a fine scope decision, but combined with a 2x peak multiplier it means **the same manifest, same pool, same counter, run at 15:00 UTC+8 vs 20:00 UTC+8, burns twice the z.ai credits for identical work.** A doc that says "burns three providers' quotas evenly" while that is true is making a claim it cannot support.

### 3.3 Verdict

Round-robin is a **defensible v1 primitive** — it is deterministic, needs no network call, and is a strict improvement over "all eight jobs to whichever backend the planner wrote down." But it is not balancing, and the field does not treat it as such.

**Recommendation that costs almost nothing and prevents a schema-breaking v2:** make the pool member accept an optional `weight` (integer, default 1) *now*, and implement **deterministic integer weighted round-robin** (expand the member list by weight, then modulo). With every weight at 1 this reproduces the spec's AC#4 sequence `0,1,2,0,1,2` exactly, with no randomness. It gives the operator the single knob the whole rest of the field uses (Portkey's normalized weights, LiteLLM's rpm-weighted shuffle, OpenRouter's inverse-square price weighting) and it is the only mechanism that lets the operator down-weight the `claude` member (§5) without editing code.

---

## 4. Q2 — What is actually measurable at runtime?

### 4.1 Anthropic

**API-key path [REPORTED — quotes from search snippet of docs.anthropic.com/en/api/rate-limits]:** response headers `anthropic-ratelimit-requests-limit`, `-requests-remaining`, `-requests-reset` (RFC 3339), `anthropic-ratelimit-tokens-*`; `retry-after` on a 429 `rate_limit_error`.

**Admin API [VERIFIED]:** `GET https://api.anthropic.com/v1/organizations/rate_limits` with an **Admin API key** returns *configured* limits (`requests_per_minute`, `input_tokens_per_minute`, …). The docs are explicit about what this is for: *"Read your current limits at startup and on a schedule instead of hardcoding values."* It returns **limits, not remaining** — and it is org/workspace scoped: *"The Admin API is unavailable for individual accounts."*

**Max subscription path — the one this project actually uses: NO runtime remaining-quota surface.**

- The `claude` backend here is a Claude Code `Task` subagent, in-process. There is no endpoint, no header, no CLI flag that returns remaining Max quota. The only first-party surface is Settings → Usage / `/usage` in the app.
- Third-party reconstruction exists but is unreliable: `ccusage` rebuilds 5-hour "blocks" from local JSONL; its own tracker carries [issue #483 "Live Blocks not accurate, Limit reached earlier"](https://github.com/ryoppippi/ccusage/issues/483) [REPORTED], and `blocks --live` was **removed in v18.0.0** [REPORTED].
- Claude Code OpenTelemetry emits `claude_code.token.usage` and `claude_code.cost.usage`, opt-in via `CLAUDE_CODE_ENABLE_TELEMETRY=1` [REPORTED]. Those are **consumption**, not **remaining**.

**And this repo already knows it** [VERIFIED — `scripts/compound-v-usage-extract.py:56-58`]:

```python
UNMEASURED_BACKENDS = frozenset(
    ("agy", "antigravity", "claude", "devin")
)
```

with the schema's own words [VERIFIED — `schemas/job_result.schema.json`]: *"When a backend emits no machine-readable usage (agy/antigravity, claude Task subagent, devin) … `measured` is false and the token counts are null (anti-ruflo: a null is honest, a made-up number is not)."*

### 4.2 OpenAI / Codex

**API-key path [REPORTED]:** `x-ratelimit-remaining-requests`, `x-ratelimit-remaining-tokens`.

**ChatGPT-plan Codex CLI path [VERIFIED shape, via issue #14728 and codex-ratelimit]:** rate-limit state rides on `token_count` events carrying a `rate_limits` payload with `primary.used_percent`, `secondary.used_percent`, `window_minutes`, `resets_in_seconds` (plus `plan_type`, `resets_at`).

**The catch, and it lands exactly on this project's invocation mode.** [openai/codex#14728](https://github.com/openai/codex/issues/14728) is titled *"feat(exec): emit rate_limits in exec mode JSONL output"* and documents that **`codex exec` produced `"rate_limits": null`** while VS Code mode returned real values. The issue's stated candidate root causes: *"(A) The API server does not send `x-codex-*` response headers for exec-mode sessions (different from vscode/app-server mode)"* and *"(B) The npm-published binary predates the RateLimitsUpdated handler code."* The issue reads as closed, but **the page I fetched contains no maintainer reply and no fix version** — I could not confirm which release fixed it.

Working alternative that sidesteps the question [VERIFIED]: [`codex-ratelimit`](https://github.com/xiangz19/codex-ratelimit) does not call `/status` at all — it walks `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` backwards for the most recent `token_count` event and reads `used_percent` / `window_minutes` / `resets_in_seconds` from it. `ccusage` reads the same tree (`CODEX_HOME`, default `~/.codex`, `sessions/` + `archived_sessions/`) [VERIFIED] — though ccusage reports tokens and cost, **not** window percentages.

**Net: Codex remaining-quota is readable from local session files today. Whether `codex exec` on codex-cli 0.130 (this repo's pinned invocation) populates `rate_limits` is UNVERIFIED and needs a live probe.**

### 4.3 z.ai — the spec's factual claim is wrong

The spec says the non-goal exists because quota-aware balancing *"would need per-backend quota introspection that z.ai, for one, does not expose."* Both halves fail.

**(a) An undocumented but in-production monitor API exists** [VERIFIED — quotes from the opencode-glm-quota README]:

| Endpoint | Purpose | Params |
|---|---|---|
| `/api/monitor/usage/quota/limit` | current quota percentages | none |
| `/api/monitor/usage/model-usage` | model usage | `startTime`, `endTime` |
| `/api/monitor/usage/tool-usage` | MCP tool usage | `startTime`, `endTime` |

Base URL `https://api.z.ai` (global) or `https://open.bigmodel.cn` (CN). Auth is unusual and worth quoting exactly: *"The plugin does NOT use 'Bearer' prefix in the Authorization header. The token is passed directly: `Authorization: {token}`"*.

**Status: UNOFFICIAL.** These paths appear in neither `docs.z.ai/devpack/overview` nor `/faq`, both of which I fetched. The FAQ points users at the dashboard instead — *"you can view the progress of your quota consumption"* in the subscription portal — and the overview at the [Charge Type billing page](https://z.ai/manage-apikey/billing). **[ISOLATED]** — one implementation, no second corroborating source found. Verify with a live call before any design depends on it.

**(b) Even without any endpoint, z.ai burn is computable from data this project already collects.** The credit formula and multipliers are published (§3.2), and `job_result.usage` already carries `input_tokens` / `output_tokens` with `measured: true` for the measurable backends. A z.ai worker in the codex/opencode/cursor mould would be measurable; credits = a pure function of tokens, model, and clock.

### 4.4 The consequence — the asymmetry runs the other way

| Backend | Remaining quota readable? | Per-job token usage readable in this repo today? |
|---|---|---|
| `zai` | **probably** (unofficial endpoint) + credits computable from tokens | expected yes (new adapter, codex-shaped) |
| `codex` | **probably** (local session JSONL; exec-mode gap unconfirmed) | **yes** — `_extract_codex`, `measured: true` |
| `claude` | **no** | **no** — in `UNMEASURED_BACKENDS` |

**The member the spec assumes is unmeasurable (z.ai) is the most measurable of the three. The member it treats as the safe default (claude) is the only one that is genuinely dark — and it is also the one that competes with the operator's own session (§5).**

**Framing consequence:** round-robin is a **stepping stone with a known, asymmetric ceiling**, not the endpoint. A quota-aware v2 is buildable for `codex` and `zai` and structurally not buildable for `claude` without a new Anthropic surface. The plan should say that, and the Risks paragraph's stated reason must be corrected — otherwise the plan inherits a false premise and the eventual v2 will be scoped against the wrong constraint.

---

## 5. Q3 — The heterogeneity trap: does spreading onto `claude` compete with the operator's own session?

**Yes. Plainly and by design.**

The chain, each link sourced:

1. **The Max limit is shared across surfaces.** [VERIFIED, verbatim from support.claude.com/en/articles/11145838]: *"Both Pro and Max plans offer usage limits that are shared across Claude and Claude Code, meaning all activity in both tools counts against the same usage limits."*
2. **Claude Code subagents run inside that same subscription.** The `Task` path is in-process, on the same authenticated session as the orchestrator conversation. There is no separate meter for a subagent.
3. **Vendor-confirmed that parallel subagents can blow the window.** [REPORTED — search snippet of the ClaudeDevs post, X/@ClaudeDevs, not fetched directly]: *"We've reset 5-hour and weekly rate limits for all users on Pro and Max plans. We fixed an issue that caused some Claude Code sessions to spawn excessive parallel subagents, burning through usage faster than expected."* This is a **vendor advisory**, which clears the evidence bar on its own — but I could not fetch X, so the quote is snippet-sourced and should be re-verified before being quoted in the plan.
4. **Users consistently report Max burn outrunning their mental model.** [VERIFIED for #52135, REPORTED for the rest] — [anthropics/claude-code#52135](https://github.com/anthropics/claude-code/issues/52135), *"[BUG] Max (20x) weekly limit depletes disproportionately — 51% mid-week, ~17% within minutes of session reset"*, opened **2026-04-22**, **closed as not planned**, no visible maintainer reply. It cross-references five sibling issues on the same tracker: #50742, #47587, #51715, #51219, #41174; search also surfaced #52921 (weekly counter resetting on ~24h) and #9424. That is **≥8 distinct threads on the vendor's own tracker** — a genuine community signal that *Max accounting is opaque and depletes faster than users model*. It is **not** evidence of any specific mechanism, and #52135 being closed as not-planned means Anthropic did not accept it as a bug.
5. **The other two meters are disjoint from the operator.** `codex exec` and a headless `zai` worker are separate processes on separate subscriptions. Nothing they burn touches the conversation the operator is sitting in.

### The asymmetry, stated plainly

The three pool members are not three interchangeable buckets of capacity. Two are pure worker capacity. The third is **shared with the operator's ability to keep working**. Spreading jobs "evenly" onto `claude` means the thing that gets rate-limited is the operator's next interactive turn — in the middle of the very run that caused it.

And that inverts the actual goal. "Ровнее жечь квоты" is not really a request for equal thirds; it is a request to **stop running out of the one you're sitting in**. A design that treats `claude` as an equal third makes the operator's own seat the first casualty of a big run.

### Second-order: pooling makes `claude` jobs strictly more expensive than before

Spec §4 forces `isolation: worktree` on **every** pool-routed job. That is the right call for enforcement uniformity — but the routing-policy tables today put `bounded_crud`, `mechanical_refactor` and `docs` on `claude` with `isolation: direct`. Pooling those job types converts them to worktree: extra setup, a fresh tree the worker must re-read, more context tokens. So a `claude` job routed *through a pool* costs more Max quota than the same job routed the old way. The spec names the worktree cost but frames it as a cost of enforcement uniformity; it does not notice it is also a **quota regression on the exact member that is already the scarcest**.

### Recommendation

**The `claude` member should be excluded from the default pool, or — if the `weight` field of §3.3 is adopted — shipped at a documented sub-unity weight.** Concretely:

- Ship the documented example pool as `codex` + `zai` only, with a one-line note: *"`claude` is the seat you are sitting in — its quota is shared with this conversation. Add it to a pool deliberately, not by default."*
- If `claude` is in a pool, its presence must be **opt-in**, not opt-out.
- Whatever is chosen, the doc must state the shared-limit fact and cite it. An operator who does not know Max is shared across Claude.ai and Claude Code cannot make this call.

---

## 6. Q4 — Failure interaction: oscillation and stampede

### 6.1 The spec's AC#9 does not match this repo's failure policy

Spec §3 and AC#9: a job that failed with `rate_limited` or `out_of_credits` has its recorded assignment cleared on resume, *"and the existing failure policy picks the next backend."*

`skills/compound-v/failure-policy.md` [VERIFIED, read in repo] says otherwise on both classes:

| Class | What the policy actually does | What AC#9 assumes |
|---|---|---|
| `rate_limited` | **`retry` on the SAME backend**, exponential backoff + jitter, per-class cap 3, then `halt`. It does **not** reroute. | "picks the next backend" |
| `out_of_credits` | `reroute` — but through *"the env-aware **codex→claude** rewrite"*, which opens `circuit_open[backend]` for the whole run and moves **this job and every remaining same-backend job** to **`claude`, `isolation: worktree`, `tier: deep`**. | "picks the next backend" (implying the next *pool member*) |

Two concrete defects follow.

**Defect A — clearing on `rate_limited` destroys the reproducibility §3 exists to protect.** If the assignment is cleared but the policy retries the same backend, the resumed job has no recorded assignment to honour and falls back to re-deriving from a counter whose state was lost. That is precisely the "same job to a different backend with a different worktree" outcome §3 forbids. **`rate_limited` must not clear the assignment** — or the failure policy has to be extended to reroute on it, which is a materially larger change than "no change to any adapter."

**Defect B — the stampede is already built in.** The first `out_of_credits` on `codex` circuit-breaks codex for the run and dumps **every remaining codex-bound job onto `claude`** — the member that shares the operator's session. With a pool in place, this converts "one provider exhausted" into "the operator's own subscription absorbs the entire remainder of the run." This is the classic cascading-exhaustion failure, and here it lands on the worst possible target.

### 6.2 Named pathologies and the mitigations real systems use

| Pathology | What it looks like here | Mitigation in the field | Status in this repo |
|---|---|---|---|
| **Retry storm / thundering herd** | every throttled job retries the instant the window clears | exponential backoff with **full jitter**, capped; a run-level retry budget | **Already defused** — `base 2·2^attempts`, jittered, cap 60s, `max_total_retries` 12, provider `retry-after` overrides [VERIFIED, failure-policy.md] |
| **Cascading exhaustion** ("all deployments in cooldown") | last healthy member absorbs everything and dies too | LiteLLM raises `RouterRateLimitError`; [issue #27823](https://github.com/BerriAI/litellm/issues/27823) (2026-05-13, closed via PR #30098) shows the *practical* failure is that clients *"cannot programmatically determine when to retry"* [VERIFIED] | **Not handled for pools.** See constraint M6 |
| **Deprioritize-don't-remove** | a cooled-down member disappears from the pool, changing `len(pool)` and therefore every subsequent assignment | LiteLLM `cooldown_time`/`allowed_fails`; OpenRouter skips providers with outages in the last 30s but **keeps them as fallbacks** [REPORTED] | Repo has the right split already (`cooldowns` = deprioritize, `circuit_open` = remove for the run). **The pool must reuse it, not invent a second filter.** |
| **Ping-pong between members** | job bounces A→B→A, each hop resetting its per-class counter | bind the breaker to the **backend**, not the job; never re-dispatch to an open breaker | Repo does this for `circuit_open`, but failure-policy explicitly says counters *"reset/fork on backend re-route"* — so with a pool a job can spend fresh retry budget per hop, with only `max_total_retries=12` as backstop |

### 6.3 The determinism bug hiding in §"Risks"

Spec §Risks: *"Unavailable members are filtered out of the pool **before** the counter is applied."*

That is safe only if availability is fixed for the whole run. It isn't — `cooldowns` and `circuit_open` change *during* a run, at batch boundaries. If a member becomes unavailable at batch 2, `len(pool)` changes, the modulo changes meaning, and **AC#4's "asserted deterministically, with no randomness anywhere" holds only for runs in which nothing fails.**

The fix is standard and cheap: **compute the eligible member list once, at run start, persist it in `state.json`, and handle mid-run unavailability by *skipping* (advance the counter past the member) rather than resizing the pool.** Skipping preserves the index sequence; resizing destroys it.

A related second-order coupling the spec does not mention: `backend_max_parallel` (§5) changes **which job fills which slot**, which changes dispatch order, which — because the counter is defined over *dispatch* order — changes the assignments. Two runs of the same manifest with different `backend_max_parallel` produce different assignments. If the counter is instead defined over the **manifest's declared job order** (a plan-time, git-tracked property), this coupling vanishes and the sequence becomes reproducible from the manifest alone.

---

## 7. Q5 — Predicted maintainer objections

The project's values, read off its own docs [VERIFIED]: determinism; git-derived enforcement, never model-self-reported; anti-ruflo (*"never a fabricated cost or token number"*); **advisory ≠ gate**; adaptation is **escalation-only, never down the trust ordering**; *"could not tell" is a distinct answer from "nothing found"*; never a silent cheap→expensive swap; and ADR 0002 — *any published number ships with its limits in the same document*.

### Objection 1 (strongest) — "A pool is a routing input that isn't in the deterministic routing order, and it can move work *down* the trust ordering."

`routing-policy.md` pins the order — lessons → stance table → scorecard → env-fallback → invariants → resolve — and is emphatic that recall *"is evidence for planning + review, never a routing input."* A pool inserts a **new decision point** that appears nowhere in that list, and whose output depends on **dispatch order**, a runtime property.

Worse, the same doc forbids exactly what a pool can silently do: *"They only ever escalate UP a fixed trust/capability ordering, never down. The ordering is `claude` … ≥ `codex` … ≥ `antigravity` … An `unhealthy` cell pushes work to a stronger or higher-trust seat; it can never … auto-select a lower-trust backend."* A pool containing `claude`, `codex` and `zai` moves a job from `claude` to `zai` on a counter — no measurement, no justification, no log line. **The spec does not mention trust ordering at all.**

**Evidence that defuses it:** state the pool's exact position in the routing order (after the stance table, before model resolution); make it a **pure function of `(tier, frozen eligible member list, index)`** with the index persisted; and add a written, validator-enforced invariant that a pool may only contain members the stance table would already permit for that job type, and that reviewer/sensitive-surface jobs can never be pooled (the spec already forbids reviewers — extend the same rule to security/auth/payments/PII/a11y, which routing-policy pins to `deep` *"in every stance"*).

### Objection 2 — "'Burn quotas evenly' is a fabricated claim; this ships a number it cannot measure."

The PR's stated goal is even quota burn. It measures neither quotas nor evenness — by its own admission it balances job counts. The CHANGELOG standard for exactly this situation is severe: *"every warning carries support, rate, Wilson lower bound, narrow support and the sample window verbatim — no risk score, no confidence %, no 'likely'. Inventing a summary metric on top of the counts is precisely the fabricated-evidence failure this project exists to prevent."*

**Evidence that defuses it:** rename the feature to what it does — **rotation**, not balancing — and ship an ADR-0002-style *"What this does not show"* block beside the claim: it equalizes **job counts per tier**, not tokens, credits, messages, or wall-clock; a 3x-cost job counts the same as a docs edit; z.ai credits additionally vary **2x by time of day** (peak Mon–Fri 14:00–18:00 UTC+8, off-peak 50%); and `claude` burn is **unmeasurable in this repo by construction** (`UNMEASURED_BACKENDS`). Report only counts in `/v:status` (`3 → claude, 3 → codex, 2 → zai`), never a "% balanced".

### Objection 3 — "AC#4's determinism is conditional and the spec doesn't say on what."

*"member 0, 1, 2, 0, 1, 2 — asserted deterministically, with no randomness anywhere"* is true only when dispatch order is fixed, the eligible list is fixed, and nothing fails. Batches complete out of order; §Risks lets the member list shrink mid-run; the failure policy relocates jobs; `backend_max_parallel` reshuffles slot-filling.

**Evidence that defuses it:** define the counter over the **manifest's declared job order**, not observed dispatch order; freeze the eligible list at run start into `state.json`; skip-don't-resize on mid-run unavailability; and add acceptance criteria that assert the sequence is **unchanged** (a) when jobs complete out of order, (b) when `backend_max_parallel` is set, and (c) when a member circuit-breaks mid-run.

---

## 8. Recent breaking changes (last 12 months)

| Date | Change | Impact on this design | Confidence |
|---|---|---|---|
| 2026-05-06 | Claude Code 5-hour limits **doubled** for Pro/Max/Team/seat-based Enterprise; peak-hours reduction removed for Pro/Max | Any hard-coded assumption about Max headroom is stale | [REPORTED] — multiple secondary blogs, no primary Anthropic URL fetched |
| ~2026-06 | Anthropic reset 5h+weekly limits for all Pro/Max after fixing *"excessive parallel subagents"* burn | Direct precedent for §5 | [REPORTED] — ClaudeDevs X post, snippet only |
| 2026-03→? | `codex exec` emitted `rate_limits: null` in JSONL ([#14728](https://github.com/openai/codex/issues/14728)); also [#14489](https://github.com/openai/codex/issues/14489) re-emits `last_token_usage` on rate-limit-only updates | A codex quota probe may silently return nothing on this repo's exec-mode invocation | [VERIFIED issue exists; fix version UNVERIFIED] |
| ccusage v18.0.0 | `blocks --live` **removed** | Rules out the most obvious third-party live-quota reader for Claude | [REPORTED] |
| through Sept 2026 | z.ai off-peak promotional rate (1x rather than 2x/0.5x baseline) | A time-of-day non-goal taken now expires with the promo | [REPORTED] — secondary blogs only; the fetched z.ai docs state peak/off-peak at 50%, no promo mentioned |
| 2026-05-13 | LiteLLM [#27823](https://github.com/BerriAI/litellm/issues/27823) closed via PR #30098 — `Retry-After` now surfaced when all deployments are cooling down | The pattern to copy for M6 | [VERIFIED] |

---

## 9. Design constraints for the plan — ranked, non-negotiable

**BLOCKING (must be resolved before the plan is written).**

- **B1 — Correct the false premise.** The Risks sentence *"it would need per-backend quota introspection that z.ai, for one, does not expose"* is wrong. z.ai publishes an exact credit formula with per-model multipliers and peak/off-peak windows, and an in-production (unofficial) `/api/monitor/usage/quota/limit` endpoint exists. The backend that is genuinely unmeasurable is **`claude`**, per this repo's own `UNMEASURED_BACKENDS`. Rewrite the rationale, or the plan scopes v2 against the wrong constraint.
- **B2 — AC#9 contradicts `failure-policy.md`.** `rate_limited` does not reroute today (it retries the same backend, cap 3); `out_of_credits` reroutes via the env-aware rewrite **to `claude` specifically**, not to the next pool member. Either the AC changes or the failure policy does — and the second is a much bigger PR than this one claims to be.
- **B3 — Trust ordering is unaddressed.** `routing-policy.md` forbids auto-routing *down* the trust ordering. A pool spanning `claude`/`codex`/`zai` does exactly that on a counter. The plan must add an explicit invariant and a validator check, or it contradicts a written project rule.
- **B4 — `claude` in the default pool competes with the operator's live session.** Shared Max limit is vendor-documented; the parallel-subagent burn incident is vendor-confirmed. Default the shipped example pool to `codex` + `zai`; make `claude` membership opt-in and documented.

**MUST.**

- **M1** — MUST NOT describe the feature as balancing quotas, burn, tokens, or credits. It rotates **job counts per tier**. Name it rotation; ship an ADR-0002 *"What this does not show"* block naming all four things it does not equalize (tokens, credits, messages, wall-clock) plus the z.ai 2x time-of-day factor plus the unmeasurability of `claude`.
- **M2** — MUST freeze the eligible member list **once at run start** and persist it in `state.json`. Mid-run unavailability MUST be handled by **skipping** the member (counter advances past it), never by resizing the pool. AC#5's "filtered before the counter" is only correct for the run-start filter.
- **M3** — The counter MUST be defined over the **manifest's declared job order**, not observed dispatch order, so the assignment sequence is reproducible from the manifest alone and is not perturbed by `backend_max_parallel` or out-of-order batch completion.
- **M4** — MUST NOT clear the recorded assignment on `rate_limited`. Only a confirmed `out_of_credits` (the class that opens `circuit_open`) may clear it. Otherwise a retry-on-same-backend job loses the assignment that reproducibility depends on.
- **M5** — The resolver MUST consult `circuit_open[backend]` **before** the modulo, and it MUST be structurally impossible for the counter to select a backend whose breaker is open.
- **M6** — When the last viable pool member is exhausted, the run MUST `halt` carrying the **earliest known reset time** across members (`retry_after_seconds`, or codex `resets_in_seconds`, or z.ai's 5h-from-consumption rule) rather than a bare failure — the lesson of LiteLLM #27823. A human resuming must be told *when*, not just *that*.
- **M7** — Pool membership MUST be forbidden for reviewer jobs (spec already has this) **and** for security / auth / payments / PII / a11y jobs, which `routing-policy.md` pins to `deep` in every stance.
- **M8** — Every pool assignment MUST be reported as a **count**, never a percentage or a "balance score" (anti-ruflo). `/v:status` shows `claude 3 · codex 3 · zai 2`, full stop.
- **M9** — The re-route triggered by a pool member's `out_of_credits` MUST be announced with its cost direction, per the existing "never silently swap a cheap backend for an expensive one" rule — which becomes more important, not less, when the fallback target is the operator's own subscription.

**SHOULD.**

- **S1** — SHOULD add an optional integer `weight` (default 1) to the pool-member object now. Deterministic integer weighted round-robin reproduces AC#4 exactly at all-weights-1, costs ~10 lines, and is the mechanism every comparable system uses (Portkey normalized weights, LiteLLM rpm-weighted shuffle, OpenRouter inverse-square price). Without it, down-weighting `claude` requires a schema change later.
- **S2** — SHOULD document the z.ai peak window (Mon–Fri 14:00–18:00 UTC+8, off-peak 50%) beside the time-of-day non-goal, so the operator can make the scheduling call manually even though the tool won't.
- **S3** — SHOULD note that pooling converts previously-`direct` `claude` jobs to `worktree`, which raises their cost on the scarcest meter.
- **S4** — SHOULD record `assigned_backend`/`assigned_model` alongside the existing `usage` object so a future quota-aware version has per-(backend, job) token history to calibrate weights from — the data is already collected for `codex`/`opencode`/`cursor`.

**MUST NOT.**

- MUST NOT introduce a runtime network call for quota introspection in this PR (it is a non-goal, and both available surfaces are unofficial or unconfirmed).
- MUST NOT claim any measured evenness, saving, or improvement. No such measurement exists.

---

## 10. Open questions for the human

1. **Is the goal "equal thirds" or "never stall"?** They produce different designs. Equal thirds → weighted rotation with `claude` at parity. Never stall → `claude` excluded or heavily down-weighted, and rotation only across the two disjoint worker meters. Only the operator can say which failure hurts more: an idle codex quota, or losing their own interactive session mid-run.
2. **Should `claude` be in the default pool at all**, given its quota is shared with the conversation doing the dispatching?
3. **Is a mid-run quota probe ever acceptable?** If "no new runtime dependency, no network call from the dispatcher" is a hard project rule, then quota-aware v2 is off the table permanently and round-robin *is* the endpoint — which changes how §"Non-goals" should be worded.
4. **`backend_max_parallel` for `zai` defaults to 4 "per its adapter"** — but no `zai` adapter and no `2026-07-31-zai-backend-design.md` exist in this repo (`skills/backend-launcher/` has advisor, antigravity, claude, codex, cursor, devin, opencode; `grep -rl zai` finds nothing). Is the zai PR expected to land first, or is the pool spec citing a document that does not yet exist?
5. **Whose clock?** The z.ai peak window is UTC+8. Does the operator want the eventual scheduling advice expressed in their local time, and is running z.ai-heavy work outside 14:00–18:00 UTC+8 something they'd accept as a later feature?

---

## 11. Knowledge base updates

Created: [`_knowledge-base/llm-provider-load-balancing.md`](_knowledge-base/llm-provider-load-balancing.md) — new file. Contains the four-system strategy matrix, the three-provider meter/introspection matrix, the failure-interaction patterns, and the "round-robin equalizes numerators across unrelated denominators" framing, all with the citations above. No existing KB file covered this domain, so nothing was superseded or struck through.
