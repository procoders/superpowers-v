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

---

## Updated 2026-08-04 — Alibaba Bailian / Model Studio Coding Plan as a headless dispatch backend

### 🔑 The generalisation: clause family 3 has TWO axes, and only one of them is curable by "spawn the real binary"

The 2026-07-31 entry established that *spawning the vendor-approved binary ≠ SDK access*, so a
dispatcher shelling out to a real CLI stays inside z.ai's allow-list. **That reasoning is not
portable.** It cures a clause that restricts the **client**; it does nothing for a clause that
restricts the **mode of use**.

| Axis | Clause restricts… | Example wording | Cured by spawning the approved binary? |
|---|---|---|---|
| **Client axis** | *which* software may call the endpoint | *"directly invoking model APIs"*, *"SDK-based access"* (z.ai) | **Yes** — the binary makes its own HTTP calls |
| **Mode axis** | *how* the endpoint may be driven | *"automated scripts… non-interactive batch calling scenarios"* (Alibaba) | **No** — a script driving an approved binary is still an automated script |

**Check both axes on every new plan.** A plan can be permissive on the client axis (long allow-list,
your tool is on it) and restrictive on the mode axis at the same time — which reads as "we're fine"
to anyone who only checks the tool list. This is the sharper form of the existing one-liner
*"'Supported tool' answers which binary, not how many at once, from what process, or whose key."*

### Alibaba Bailian Coding Plan — worked example (verified 2026-08-04, EN + ZH primary)

**Mode restriction** ([EN](https://www.alibabacloud.com/help/en/model-studio/coding-plan),
[ZH](https://help.aliyun.com/zh/model-studio/coding-plan), heading *"Prohibition of API calls"*):

> "This plan is for interactive use in programming tools such as Claude Code and OpenClaw. Do not use
> the plan's API key for automated scripts, application backends, or other non-interactive scenarios."
>
> 「仅限在编程工具（如 Claude Code、OpenClaw 等）中使用，禁止**以 API 调用的形式**用于自动化脚本、自定义应用程序后端或任何非交互式批量调用场景。」

**Read the Chinese, not only the English.** The qualifier 「以 API 调用的形式」 (*"in the form of API
calls"*) is absent from the English rendering and materially narrows the clause — it plausibly scopes
the ban to calling the endpoint **directly**, bypassing an approved tool. The FAQ's own examples of
prohibited use are **curl, Postman, Dify** — all bypass patterns. **Reusable rule: when a Chinese
vendor's EN and ZH terms differ in scope, the ZH text is the operative one and usually the more
precise; fetch both.**

**The unresolved contradiction (state it, don't resolve it).** Alibaba lists **Qwen Code** as a
supported tool, and Qwen Code's own docs market headless mode as *"ideal for scripting, automation,
CI/CD pipelines."* So the vendor ships a first-party tool designed for automation and a plan whose
terms prohibit automation. **[NOT FOUND]** any community report of the clause being enforced, in
either direction — searches across Reddit returned nothing relevant. Enforcement here is **unmeasured**,
unlike z.ai's (two press reports, reproducible error codes). Surface it as a human decision.

**Enforcement ladder:** 「将套餐 API Key 用于允许范围之外的调用将被视为违规或滥用，可能会导致订阅被暂停或 API Key 被封禁。」
— *"may result in subscription suspension or API Key ban."* No strike count published (contrast z.ai's
explicit three), no appeal path published, no SLA.

**Personal-use:** 「套餐为订阅人专享使用，禁止共享。」 — subscriber-only, sharing prohibited. Plus the
[Intl Product ToS v3.8.0](https://www.alibabacloud.com/help/en/legal/latest/alibaba-cloud-international-website-product-terms-of-service-v-3-8-0)
(no resale/sublicense; no account transfer without written consent) and the
[API Terms of Use](https://www.alibabacloud.com/help/en/legal/latest/api-term-of-use)
(*"non-transferable, non-sublicensable, non-exclusive"*).

**Auto-disable on exposure:** 「若系统检测到您的 API Key 存在公开泄露的情况，可能会自动将其禁用」 — a key
detected as publicly leaked is disabled automatically. Raises the stakes on argv exposure (`ps` /
`/proc/<pid>/cmdline`) and on any config file that could reach a commit.

### ⚠️ Quota can be counted in REQUESTS, not tokens — check the unit before porting quota math

z.ai bills a token-weighted credit; **Alibaba bills model calls.**

> "The Coding Plan's quota consumption is based on the number of model calls, not on token consumption."
> — [Coding Plan FAQ](https://www.alibabacloud.com/help/en/model-studio/coding-plan-faq)

| Bailian Coding Plan (Pro) | Value |
|---|---|
| price | $50/mo (intl) · ¥200/mo (CN) |
| per 5 hours | 6 000 requests |
| per week | 45 000 requests |
| per month | 90 000 requests |

**This inverts the optimisation.** Token-billed ⇒ long outputs are expensive. Request-billed ⇒ **turn
count** is expensive and output length is free. For an agentic worker the right control is a
max-turns cap, not a max-tokens cap. Any adapter that carries a token-cost mental model onto a
request-billed plan will optimise the wrong knob.

Other structural facts:
- **Concurrency limit exists, magnitude undocumented, adjusts dynamically** — *"the platform
  dynamically adjusts this limit based on the overall resource load"*; exceeded ⇒
  `concurrency allocated quota exceeded`. Same anti-pattern as z.ai: published token quota, hidden
  concurrency.
- **No pay-as-you-go fallback:** 「额度消耗完毕后，继续调用会失败报错，并且不会自动转为按量付费模式计费」 —
  exhaustion is a hard wall, not an overage charge. Cost-safe; makes a dispatcher `FALLBACK` entry
  load-bearing rather than nice-to-have.
- **Coding Plan credentials are a separate namespace:** key `sk-sp-…`, dedicated base URL, **not**
  interchangeable with ordinary Model Studio pay-as-you-go keys.
- **Lite discontinued** — no new purchases 2026-03-20, no renewal/upgrade 2026-04-13. Pro is
  effectively the only tier.

**Endpoints:**

| | China | International |
|---|---|---|
| OpenAI-compatible | `https://coding.dashscope.aliyuncs.com/v1` | `https://coding-intl.dashscope.aliyuncs.com/v1` |
| Anthropic-compatible | `https://coding.dashscope.aliyuncs.com/apps/anthropic` | *(intl equivalent — unverified)* |

### DashScope error surface — key on `errorType`, NOT on message text

**The trap:** z.ai's classifier keys on documented *message text*. DashScope returns **`message: null`**
on at least its throttling path, so a message-text classifier matches nothing and fails to `other`.

Observed shape ([qwen-code #2191](https://github.com/QwenLM/qwen-code/issues/2191), 2026):

```json
{"errorType":"THROTTLING.userQPSLimit","rid":"<uuid>","message":null,"status":429}
```

| Needle | Source | Sensible class |
|---|---|---|
| `THROTTLING.userQPSLimit` | [#2191](https://github.com/QwenLM/qwen-code/issues/2191) | rate_limited |
| `concurrency allocated quota exceeded` | Coding Plan FAQ | rate_limited |
| `hour allocated quota exceeded` | Coding Plan FAQ | rate_limited |
| `week` / `month allocated quota exceeded` | Coding Plan FAQ | out_of_credits |
| 401 `invalid access token or token expired` | [#1855](https://github.com/QwenLM/qwen-code/issues/1855) | auth |

429s on DashScope are a **live, recurring** surface, not an edge case — **6 threads**:
[#2217](https://github.com/QwenLM/qwen-code/issues/2217),
[#2191](https://github.com/QwenLM/qwen-code/issues/2191),
[#2146](https://github.com/QwenLM/qwen-code/issues/2146),
[#1742](https://github.com/QwenLM/qwen-code/issues/1742),
[#882](https://github.com/QwenLM/qwen-code/issues/882),
[#1983](https://github.com/QwenLM/qwen-code/issues/1983).

### Vendor comparison — the four clause families, three vendors (2026-08-04)

| | z.ai GLM Coding Plan | Alibaba Bailian Coding Plan | Anthropic Pro/Max |
|---|---|---|---|
| **1. Tool allow-list** | published, ~15 tools, tiered | published, ~14 tools incl. Qwen Code | n/a (own tool) |
| **2. Personal use / aggregation** | one natural person; no share; no resell/**aggregate**/proxy | subscriber-only; no share; no resell/sublicense/transfer | no third-party routing of Pro/Max credentials |
| **3. Scenario / mode** | **client axis** — no direct API / SDK access; coding scenarios only | **MODE axis** — no automated scripts, no non-interactive batch | AUP silent on automation |
| **4. Enforcement** | rate-limit → freeze → ban at **>3 violations**; console appeal | suspension or key ban; **no strike count, no appeal published**; auto-disable on leaked key | enforced ~Jan 2026 vs extracted OAuth tokens |
| **Quota unit** | token-weighted credits | **model calls** | rolling windows |
| **Enforcement measured?** | yes (press + error codes) | **no — zero reports found** | yes (HN coverage) |

### Reusable one-liners (additions)

- Check **both** axes of the scenario clause: *which client* and *how driven*. Only the first is
  cured by spawning the approved binary.
- Fetch the vendor's **Chinese** terms too — the EN rendering dropped a scope-narrowing qualifier here.
- Check the **quota unit** before porting quota math: token-billed and request-billed plans reward
  opposite behaviours.
- A vendor listing your tool while banning your usage mode is a contradiction you cannot resolve —
  escalate it to the human, don't adjudicate it in an adapter doc.
- "No published strike count" is worse than "three strikes," not better — it means the first
  violation may be the last.
