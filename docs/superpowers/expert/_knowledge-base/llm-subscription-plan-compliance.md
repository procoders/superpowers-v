# LLM Coding-Subscription Compliance Knowledge Base

Vendor coding subscriptions (z.ai GLM Coding Plan, Anthropic Pro/Max, OpenAI/Codex plans,
Cursor, …) used as an **automation backend**: what their terms actually restrict, how quota
and concurrency really work, how enforcement presents at the wire, and which clause families
to check before wiring one into a dispatcher.

Maintained by Compound V Phase 1B advisor. Append at the bottom on each pass.

---

## Updated 2026-07-31 — z.ai GLM Coding Plan as a headless dispatch backend

### The four clause families to check on ANY coding subscription

Checking "is my tool on the supported list?" answers one of four questions. The other three are
where the risk lives. Reusable checklist:

1. **Tool allow-list** — *which binary may call this endpoint.* Usually published and usually
   generous. Says nothing about how the binary is driven.
2. **Personal-use / aggregation** — *whose key, how many humans, may it be pooled.* This is the
   clause that rules out CI, shared team keys, and hosted deployments, and it is almost never
   what people check.
3. **Scenario restriction** — *what the plan may be used FOR.* Coding plans increasingly restrict
   to coding scenarios and actively detect otherwise.
4. **Enforcement ladder** — *what happens on violation, how many strikes, is there an appeal.*
   Determines whether an aggressive retry policy is merely wasteful or account-fatal.

**Rule of thumb:** if the plugin/tool is distributed publicly, the cost of a false positive lands
on the **end user's** subscription, never the author's. Price the feature accordingly: opt-in,
off by default, with an acknowledgement about *account risk* — not only about sandbox trust.

### z.ai GLM Coding Plan — worked example (verified 2026-07-31)

**Tool allow-list** ([docs.z.ai/devpack/tool/others](https://docs.z.ai/devpack/tool/others)):
Tier-1 coding-agent tools — *"Claude Code, Claude for IDE, ZCode, OpenCode, Pi, Cursor, Cline,
TRAE, Qoder, Droid, Kilo Code, Roo Code, Crush, Goose, Eigent"*. Best-effort tier —
*"OpenClaw, Hermes Agent, SillyTavern"*, which *"will continue to be served on a best-effort
basis. Under high inference load, some requests may face temporary rate limits."*
Gate: *"users may not use their subscription benefits for tools or scenarios outside of this scope."*

**Personal-use / aggregation** ([Subscription Terms §4](https://docs.z.ai/legal-agreement/subscription-terms)):
*"tied to a single account and is licensed only to the individual natural person associated with
such account"*; *"You shall not share your account or subscription"*; *"you may not resell,
sub-resell, repackage, **aggregate**, proxy or otherwise provide the GLM Coding Plan to any third
party"*. Also: *"You shall not use the GLM Coding Plan quota for general-purpose API access …
including but not limited to directly invoking model APIs"*, and usage via *"SDK-based access or
other third-party integrations"* may have benefits restricted.
**Reusable reading:** *spawning the vendor-approved binary* ≠ *SDK access*. A dispatcher that
shells out to the real CLI is inside the allow-list; one that re-implements the HTTP client is not.

**Scenario restriction** ([quoted 2026-04-20](https://awesomeagents.ai/news/zai-coding-plan-bans-non-coding-use/)):
*"designed specifically for Coding Scenarios. If the system detects that the subscription is being
used for requests clearly unrelated to coding scenarios, certain subscription benefits may be
restricted."* Practical consequence: an orchestrator may use such a plan for **implementation**,
but giving it a reviewer / summarizer / arbiter / chat seat drifts toward the prohibited zone.

**Enforcement ladder** ([Usage Policy](https://docs.z.ai/devpack/usage-policy)):
*"Violations of the Usage Rules may trigger risk control measures, including rate limiting,
account freezing, or other restrictions. Accounts with more than three violations may be banned."*
Automated risk control; appeal via the console Plan Overview page; **no published SLA**.

### Concurrency is the undocumented limit — assume nothing

**Pattern, not z.ai-specific:** coding subscriptions publish *token/credit* quotas and hide
*concurrency*. z.ai states only a relative ordering (`Max > Pro > Lite`) with per-tier *project*
guidance (Lite: 1 project, Pro: 1–2, Max: 2+); [OpenClaw's provider doc](https://docs.openclaw.ai/providers/zai)
adds *"rate and concurrency limits are tied to the plan tier and can be adjusted dynamically based
on resource availability."*

- **[ISOLATED REPORT]** [opencode #8618](https://github.com/anomalyco/opencode/issues/8618)
  (2026-01-15): GLM-4.7 on Coding Plan Pro limited to **1 concurrent request**, apparently reduced
  from 3; *"AI_RetryError: Failed after 4 attempts. Last error: Too Many Requests"*; reporter could
  use *"barely… 4% of my 5 hour limit."* One thread — a lead, not a proven current cap.
- **Same anti-pattern, other vendor [REPORTED]:** [claude-code #53922](https://github.com/anthropics/claude-code/issues/53922)
  — bulk-spawning ~10 sessions, *"the first 3-4 work, the rest fail with 'Server is temporarily
  limiting requests (not your usage limit) · Rate limited'"*; [#62426](https://github.com/anthropics/claude-code/issues/62426)
  — rate limits blocking multi-agent workflows *"even at highest paid tier"*.

**Reusable rules:** (a) simultaneous cold-start of N workers looks like an attack to every
provider — **stagger**; (b) a limit validated once is not a limit, because it is adjusted
dynamically; (c) never ship a fan-out number as a *measured* property without an actual
concurrency measurement at 2 / 4 / 6, weekday and weekend.

### Enforcement throttling is wire-indistinguishable from ordinary rate limiting

**[REPORTED]** — two outlets, same week ([Awesome Agents](https://awesomeagents.ai/news/zai-coding-plan-bans-non-coding-use/),
[OfficeChai](https://officechai.com/ai/after-claude-google-z-ai-restricts-openclaw-like-non-coding-usage-on-its-coding-plans-openclaw-creator-responds/),
both 2026-04-20): z.ai's April-2026 non-coding-use crackdown surfaced across SillyTavern, opencode
and Letta-code as error codes **1302 / 1303**. Note `1303` is not in the published error table.

**The reusable consequence, and it is the important one:** a client cannot tell "you're going too
fast" from "you're being penalized." So **reacting to 429 by retrying harder is, from the
provider's risk-control perspective, doing the thing that got people penalized.** Any dispatcher
against a strike-based provider needs a bounded retry ceiling *and* a per-backend circuit breaker
that stops dispatching for the rest of the run — enforcement outside the agent's own loop
(see `autonomous-agent-orchestration.md`).

Blanket-failure mode also exists: [openclaw #31234](https://github.com/openclaw/openclaw/issues/31234)
— *"Every request fails with an API limit/usage error … 100% of the time across sessions"*, open,
no root cause, no error bodies captured.

### z.ai credit engine — verified numbers (docs.z.ai/devpack/overview, 2026-07-31)

> *"Model credit usage = (Input tokens × Input multiplier + Cached Input tokens × Cached Input
> multiplier + Output tokens × Output multiplier) / 10,000"*

| Model | Input | Cached input | Output |
|---|---|---|---|
| GLM-5.2 | 6.9 | 1.7 | 24 |
| GLM-5-Turbo | 5.7 | 1.5 | 21 |
| GLM-4.7 | 4.6 | 1.2 | 16 |
| GLM-4.6V | 1.2 | 0.3 | 2.7 |

| Cap | Lite | Pro | Max |
|---|---|---|---|
| per rolling 5-hour window | 2 000 | 12 000 | 28 000 |
| weekly | 10 000 | 60 000 | 140 000 |

Peak = *"Monday–Friday, 14:00–18:00 Singapore Standard Time"*; off-peak billed at *"50% of standard
rates"*. **Weekly window is keyed to purchase date, not the calendar:** *"starts counting from the
time you place your order, and the quota is refreshed and reset on a 7-day cycle"*
([FAQ](https://docs.z.ai/devpack/faq)). No overage: *"Once the quota is used up, you'll need to
wait until the next 5-hour cycle … The system will not deduct from your account balance."*

**⚠️ Peak/off-peak rates are promotional and move.** **[REPORTED]** an off-peak promo (2× → 1×)
runs *"through the end of September 2026"*, reverting to 2× off-peak / 3× peak; a ZCode-only peak
promo (3× → 2×) expired 2026-07-31. The 2×/3× framing does not reconcile cleanly with the docs'
"50% off-peak" framing. **Reusable rule: never build arithmetic on a promotional rate; date-stamp
any quota math you write down.**

### z.ai error surface — full published table ([docs.z.ai/api-reference/api-code](https://docs.z.ai/api-reference/api-code))

Envelope: `{"error":{"code":"XXXX","message":"…"}}`. **No `Retry-After` header is documented
anywhere** — reset times are embedded in the message prose as `{next_flush_time}`.

| Code | HTTP | Message | Sensible failure class |
|---|---|---|---|
| 1113 | 429 | `Insufficient balance or no resource package. Please recharge.` | out_of_credits |
| 1210 | 400 | `Invalid API parameter, please check the documentation.` | other |
| 1211 | 400 | `Unknown Model, please check the model code.` | other |
| 1301 | 400 | `System detected potentially unsafe or sensitive content…` | other |
| 1302 | 429 | `Rate limit reached for requests` | rate_limited |
| 1305 | 429 | `The service may be temporarily overloaded, please try again later` | overloaded |
| 1308 | 429 | `Usage limit reached for {number} {unit}. Your limit will reset at {next_flush_time}` | rate_limited |
| 1310 | 429 | `Weekly/Monthly Limit Exhausted. Your limit will reset at {next_flush_time}` | out_of_credits |
| 1311 | 429 | `Your current subscription plan does not yet include access to ${model_name}` | auth |
| 1316 | 429 | `Usage limit reached for the past 5 hours. Insufficient balance for extra usage…` | rate_limited |
| 1317 | 429 | `Usage limit reached for the past 7 days. Insufficient balance for extra usage…` | out_of_credits |

Observed rendering through Claude Code against `api.z.ai/api/anthropic` (one sample only,
Compound V live probe 2026-07-31): `API Error: 400 [1211][Unknown Model, please check the model
code.][<trace-id>]` — shape is `[code][message][trace-id]`, which suggests but does not prove the
429s render identically.

**Transport [REPORTED, OpenAI-compat layer only]:** [opencode #15350](https://github.com/anomalyco/opencode/issues/15350)
— `{"error":{"code":"ECONNRESET","path":"https://api.z.ai/api/coding/paas/v4/chat/completions"}}`,
101 consecutive failures in one session, resets *"after approximately 40-100 seconds of streaming"*,
attributed to z.ai closing idle keep-alive connections after 30–60s. Closed "not planned." Consistent
with z.ai's own Claude Code setup recommending `API_TIMEOUT_MS: 3000000`.

### z.ai endpoint layers — easy to get wrong

| Layer | Subscription (Coding Plan) | Pay-as-you-go |
|---|---|---|
| Anthropic-compatible | `https://api.z.ai/api/anthropic` | same URL, only if no Coding Plan was ever purchased |
| OpenAI-compatible (Chat Completions) | `https://api.z.ai/api/coding/paas/v4` | `https://api.z.ai/api/paas/v4` |

z.ai exposes **no Responses API** — which is why OpenAI Codex CLI (≥ some 2026 build, which refuses
`wire_api = "chat"`) cannot reach z.ai at all.

### Anthropic's side — where the line actually is (verified 2026-07-31)

Relevant when repointing Anthropic's own tooling at a competitor:
- [AUP](https://www.anthropic.com/legal/aup) (eff. 2025-09-15): **no** clause on competing models,
  automation, volume, or reverse engineering.
- [Commercial Terms](https://www.anthropic.com/legal/commercial-terms) (eff. 2025-06-17) §D.4:
  *"Customer may not … (a) access the Services to build a competing product or service, including
  to train competing AI models or resell the Services … (b) reverse engineer or duplicate the
  Services"* — every verb scoped to **accessing the Services**.
- [Claude Code legal](https://code.claude.com/docs/en/legal-and-compliance): the actual restriction
  runs the **other** direction — *"Anthropic does not permit third-party developers to offer
  Claude.ai login or to route requests through Free, Pro, or Max plan credentials on behalf of
  their users."*
- **[REPORTED]** Anthropic enforced this in ~Jan 2026 against harnesses using *extracted OAuth
  tokens* ([HN 46549823](https://news.ycombinator.com/item?id=46549823)) — OpenClaw, OpenCode, Roo
  Code, Goose. The line drawn in coverage: **calling the real CLI is fine; extracting OAuth tokens
  into a third-party client is not.**
- **[NOT FOUND]** Any Anthropic statement on pointing Claude Code at a non-Anthropic endpoint.
  [claude-code #5577](https://github.com/anthropics/claude-code/issues/5577) asked exactly that on
  2025-08-12 and was **closed with no reply**. Silence ≠ permission; risk here is reputational,
  not contractual.

### Reusable one-liners

- "Supported tool" answers *which binary*, not *how many at once*, *from what process*, or *whose key*.
- The clause that rules out CI is the personal-use clause, and nobody reads it.
- Undocumented ≠ absent. "Adjusted dynamically" means yesterday's successful fan-out proves nothing.
- On a strike-based provider, retry policy is a **compliance** decision, not a reliability one.
- If the plugin ships publicly, the ban lands on the installer. Opt-in, off by default, loud notice.
