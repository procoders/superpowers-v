# Phase 1B — Domain Expert Audit: `zai` backend (headless `claude -p --bare` against z.ai GLM Coding Plan)

**Date:** 2026-07-31
**Spec audited:** `docs/superpowers/specs/2026-07-31-zai-backend-design.md`
**Branch:** `feat/zai-backend`
**Scope:** domain/regulatory reality only. Existing-code reality is Phase 1A; library/API currency is Phase 1C.

> **Reading key.** Every claim below is tagged.
> **[VERIFIED]** = read on a primary source (vendor doc, official CLI doc, legal text) that I fetched, quoted below.
> **[REPORTED]** = a real, dated, linked third-party source, but not primary or not corroborated to the community-signal threshold (≥10 distinct posts, or ≥1 official advisory).
> **[ISOLATED REPORT]** = one source only. Treat as a lead, not a constraint.
> **[NOT FOUND]** = I searched and found nothing. Stated so the plan does not mistake silence for confirmation.

---

## 1. Domain(s) Identified

1. **`llm-subscription-plan-compliance`** — a vendor coding-subscription (z.ai GLM Coding Plan) with a tool allow-list, personal-use licensing, a credit/quota engine, and an automated risk-control system with a three-strike ban.
2. **`claude-code-headless-harness`** — Claude Code as a scripted, non-interactive worker process: `--bare` semantics, permission modes, tool restriction, auth precedence, and third-party-endpoint redirection.
3. **`oss-plugin-maintainer-acceptance`** — what a maintainer of a publicly distributed Claude Code plugin will and will not merge when the change puts *end users'* third-party accounts at risk.

---

## 2. Sources Consulted

**Knowledge base:** `docs/superpowers/expert/_knowledge-base/` — 7 files present, all read for relevance.
`autonomous-agent-orchestration.md` (updated 2026-07-12) is the only adjacent one; it covers runaway-loop and circuit-breaker theory and is reused in §4 (retry-storm risk). No KB file existed for either z.ai or Claude-Code-as-harness. **Both created (see §9).**

**Trigger 0 recon:** `docs/superpowers/recon/` contains exactly one doc, `2026-07-11-fts5-cyrillic-tokenizer.md` — unrelated. No recon doc for this topic; no path was handed by the caller. Full search budget spent here.

**Primary sources fetched (quoted in-line below):**

| Source | URL |
|---|---|
| z.ai Coding Plan — Usage Policy | https://docs.z.ai/devpack/usage-policy |
| z.ai Coding Plan — Overview / Usage Instruction (credits, multipliers, caps) | https://docs.z.ai/devpack/overview |
| z.ai Coding Plan — FAQ | https://docs.z.ai/devpack/faq |
| z.ai Coding Plan — Claude Code setup | https://docs.z.ai/devpack/tool/claude |
| z.ai Coding Plan — Tool Integration (supported-tool list) | https://docs.z.ai/devpack/tool/others |
| z.ai — Subscription Terms (legal) | https://docs.z.ai/legal-agreement/subscription-terms |
| z.ai — API error codes | https://docs.z.ai/api-reference/api-code |
| z.ai — GLM-5.2 model card | https://docs.z.ai/guides/llm/glm-5.2 |
| z.ai — GLM-5-Turbo model card | https://docs.z.ai/guides/llm/glm-5-turbo |
| z.ai — GLM-4.7 model card | https://docs.z.ai/guides/llm/glm-4.7 |
| Claude Code — Legal and compliance | https://code.claude.com/docs/en/legal-and-compliance |
| Claude Code — CLI reference (`--bare`, `--tools`, `--allowedTools`) | https://code.claude.com/docs/en/cli-reference |
| Claude Code — Run programmatically / headless (bare mode) | https://code.claude.com/docs/en/headless |
| Claude Code — Permission modes (`dontAsk`) | https://code.claude.com/docs/en/permission-modes |
| Claude Code — Permissions (read-only Bash set, deny rules) | https://code.claude.com/docs/en/permissions |
| Anthropic — Usage Policy (AUP), eff. 2025-09-15 | https://www.anthropic.com/legal/aup |
| Anthropic — Commercial Terms, eff. 2025-06-17 | https://www.anthropic.com/legal/commercial-terms |

**Community / practitioner sources fetched:**
`pi` issue #4187 ([earendil-works/pi](https://github.com/earendil-works/pi/issues/4187), mirrored at [badlogic/pi-mono](https://github.com/badlogic/pi-mono/issues/4187)) ·
opencode issue #8618 ([concurrency](https://github.com/anomalyco/opencode/issues/8618), 2026-01-15) ·
opencode issue #15350 ([ECONNRESET](https://github.com/anomalyco/opencode/issues/15350)) ·
LiteLLM issue #32218 ([`glm-5.2[1m]` unknown model](https://github.com/BerriAI/litellm/issues/32218)) ·
openclaw issue #31234 ([blanket usage errors](https://github.com/openclaw/openclaw/issues/31234)) ·
[OpenClaw z.ai provider docs](https://docs.openclaw.ai/providers/zai) ·
[Awesome Agents, 2026-04-20](https://awesomeagents.ai/news/zai-coding-plan-bans-non-coding-use/) ·
[OfficeChai, 2026-04-20](https://officechai.com/ai/after-claude-google-z-ai-restricts-openclaw-like-non-coding-usage-on-its-coding-plans-openclaw-creator-responds/) ·
[HN 46549823](https://news.ycombinator.com/item?id=46549823) ·
[anthropics/claude-code #5577](https://github.com/anthropics/claude-code/issues/5577) ·
claude-code issues [#53922](https://github.com/anthropics/claude-code/issues/53922), [#62426](https://github.com/anthropics/claude-code/issues/62426).

**Searches that returned nothing usable — stated so the plan does not read silence as clearance:**
- Practitioner comparison of **GLM-5.2 vs GLM-5-Turbo on scope discipline / obeying a file allow-list** in agentic code editing → **[NOT FOUND]**. Every hit was a vendor page or an SEO review that benchmarks chat/coding quality, not scope obedience.
- Real captured **z.ai 429 response bodies as seen through `api.z.ai/api/anthropic`** → **[NOT FOUND]**. All samples I could find are from the OpenAI-compat layer (`/api/coding/paas/v4`) or from wrapper libraries.
- Any Anthropic statement, official or in-issue, on **pointing Claude Code at a non-Anthropic model endpoint** → **[NOT FOUND]**. Issue #5577 asked exactly this on 2025-08-12 and was closed **with no Anthropic reply**.
- Any confirmed, individually documented **z.ai account ban** → **[NOT FOUND]**. Only policy text and throttling-wave reports (§5).

---

## 3. Domain Constraints the Brainstorm Probably Missed

### A. z.ai terms — what the Coding Plan actually forbids

**A1. [VERIFIED] Claude Code is on the officially supported list. The premise holds.**
`https://docs.z.ai/devpack/tool/others` lists the coding-agent tools as: *"Claude Code, Claude for IDE, ZCode, OpenCode, Pi, Cursor, Cline, TRAE, Qoder, Droid, Kilo Code, Roo Code, Crush, Goose, Eigent"*, plus a best-effort tier: *"OpenClaw, Hermes Agent, SillyTavern are also supported and will continue to be served on a best-effort basis."* The gating sentence is: *"The GLM Coding Plan is limited to use within the following officially supported tools and product environments; users may not use their subscription benefits for tools or scenarios outside of this scope."*
`https://docs.z.ai/devpack/tool/claude` documents the exact Claude Code setup the spec uses, with `ANTHROPIC_BASE_URL = "https://api.z.ai/api/anthropic"`.
**Note for the plan:** `Pi` is now *on* the Tier-1 list, which retroactively resolves issue #4187 — cite the live list, not the issue.

**A2. [VERIFIED] The prohibition is aimed at *bypassing* a supported tool, not at scripting one.**
Subscription Terms §4 (`https://docs.z.ai/legal-agreement/subscription-terms`): *"You shall not use the GLM Coding Plan quota for general-purpose API access or any scenarios outside such tools, including but not limited to directly invoking model APIs"*, and usage through *"SDK-based access or other third-party integrations"* may have benefits restricted.
The `zai` worker spawns **the real, unmodified `claude` binary**, which makes its own HTTP calls. It is not an SDK client, not a re-implementation, not a proxy. **On the plain text of the rule, `claude -p --bare` is inside Claude Code.** This is the strongest single fact in the audit and the plan should state it exactly this way.

**A3. [VERIFIED] But three *other* clauses in the same section are the real exposure, and the spec addresses none of them.**
From §4 of the Subscription Terms:
- *"The GLM Coding Plan subscription is tied to a single account and is licensed only to the individual natural person associated with such account."*
- *"You shall not share your account or subscription, or allow any other person… to use your GLM Coding Plan quota"* — and from the Usage Policy: *"Account sharing or multi-user access is prohibited."*
- *"you may not resell, sub-resell, repackage, aggregate, proxy or otherwise provide the GLM Coding Plan to any third party"*

A single developer running their own key across 4–6 of their own workers is one natural person and is fine. **A CI runner, a team-shared key, or a hosted deployment of this plugin is not**, and this plugin ships publicly to users who will do all three. The word **`aggregate`** is the one to worry about: a dispatcher that pools one key across many concurrent workers is *arguably* aggregation. I do not think that reading survives contact with intent — the clause is about reselling — but a maintainer will ask, and the plan needs an answer in writing.

**A4. [VERIFIED] Enforcement is automated, graduated, and terminal at three strikes.**
Usage Policy: *"Violations of the Usage Rules may trigger risk control measures, including rate limiting, account freezing, or other restrictions. Accounts with more than three violations may be banned."*
There is **no documented appeal SLA**; the console shows a risk notice on the Plan Overview page and you file an appeal. The asymmetry matters: the cost of a false positive is the user's whole subscription, and the plugin's author is not the one who pays it.

**A5. [VERIFIED] The plan must be used for coding.**
*"The GLM Coding Plan is designed specifically for Coding Scenarios. If the system detects that the subscription is being used for requests clearly unrelated to coding scenarios, certain subscription benefits may be restricted."* (quoted at [Awesome Agents, 2026-04-20](https://awesomeagents.ai/news/zai-coding-plan-bans-non-coding-use/)).
`zai` is scoped to **implementation worker only, never reviewer, never arbiter** — which is squarely a coding scenario. **Keep it that way.** The moment a follow-on PR gives `zai` a reviewer or arbiter seat, or uses it to summarize a spec, it drifts toward the prohibited zone. The spec already excludes those as non-goals; the plan should record *why* that exclusion is now load-bearing rather than merely tidy.

**A6. [VERIFIED — this is the one that breaks the design premise] Concurrency is undocumented, dynamic, and tier-linked — and there is no published number.**
Usage Policy states only a relative ordering — `Max > Pro > Lite` — with per-tier *project* guidance (Lite: single project; Pro: 1–2 projects; Max: 2+ projects). [OpenClaw's provider doc](https://docs.openclaw.ai/providers/zai) is blunter: *"Coding Plan rate and concurrency limits are tied to the plan tier and can be adjusted dynamically based on resource availability."*
**[REPORTED]** opencode issue [#8618](https://github.com/anomalyco/opencode/issues/8618) (2026-01-15), titled *"GLM Coding Plan Pro ($15/mo) unusable due to undocumented concurrent request limit of 1"*: the reporter hit `AI_RetryError: Failed after 4 attempts. Last error: Too Many Requests` and could reach *"barely… 4% of my 5 hour limit"*; a commenter adds *"I see 4.7 is limited to 1, wasn't it 3 recently?"* — i.e. the cap moved **down**. That is a single issue thread, so it is **not** a proven current cap. But it is exactly the failure mode this design produces, and it is the strongest counter-evidence to the spec's core sentence *"three providers' quotas are consumed in parallel."*
**The plan cannot assume z.ai parallelizes.** Pro-tier guidance of "1–2 projects" is not a promise of 4–6 concurrent in-flight requests.

### B. Anthropic's side — can an upstream maintainer accept this?

**B1. [VERIFIED] Nothing in Anthropic's terms forbids pointing Claude Code at a third-party endpoint.**
- [Claude Code legal-and-compliance](https://code.claude.com/docs/en/legal-and-compliance) names the restriction precisely, and it runs the *other* direction: *"OAuth authentication is intended exclusively for purchasers of Claude Free, Pro, Max, Team, and Enterprise subscription plans… Anthropic does not permit third-party developers to offer Claude.ai login or to route requests through Free, Pro, or Max plan credentials on behalf of their users."* That is about **third-party tools consuming Anthropic subscription credentials**. The `zai` backend does the mirror image — Anthropic's own tool consuming a third party's credentials — and is not addressed.
- [Anthropic Usage Policy](https://www.anthropic.com/legal/aup) (eff. 2025-09-15): **[VERIFIED]** contains **no** clause restricting use alongside competing models, no automation/volume clause, no reverse-engineering clause. The nearest neighbours are "don't bypass guardrails" and "don't train on inputs/outputs without authorization" — neither applies.
- [Commercial Terms](https://www.anthropic.com/legal/commercial-terms) (eff. 2025-06-17) §D.4: *"Customer may not and must not attempt to (a) access the Services to build a competing product or service, including to train competing AI models or resell the Services except as expressly approved by Anthropic; (b) reverse engineer or duplicate the Services…"* — every verb is scoped to **accessing the Services**. A `zai` job never touches Anthropic's Services: the spec's `env -i` scrub plus `--bare`'s documented refusal to read OAuth/keychain (see B3) means zero Anthropic API calls occur.

**B2. [VERIFIED] Third-party endpoints are a first-class, documented Claude Code feature.**
Bedrock, Google Cloud's Agent Platform and Microsoft Foundry are all documented providers, and the [headless doc](https://code.claude.com/docs/en/headless) says of bare mode: *"Amazon Bedrock, Google Cloud's Agent Platform, and Microsoft Foundry use their usual provider credentials."* `ANTHROPIC_BASE_URL` is documented across the CLI. The mechanism is sanctioned; only the *destination* is novel.

**B3. [VERIFIED] `--bare`'s auth behaviour is exactly what the spec claims — and it is Anthropic's own documented recommendation.**
[headless doc](https://code.claude.com/docs/en/headless), verbatim: *"Bare mode skips OAuth and keychain reads. For Anthropic authentication, set `ANTHROPIC_API_KEY` or configure an `apiKeyHelper` in the JSON you pass to `--settings`."* And: *"`--bare` is the recommended mode for scripted and SDK calls, and will become the default for `-p` in a future release."*
This independently confirms the spec's central safety claim — a `zai` job is **structurally incapable of billing the operator's Anthropic subscription**. Cite this sentence in the PR; it is the single best defusing evidence available.

**B4. [NOT FOUND / open] Anthropic has never answered the question directly.** [Issue #5577](https://github.com/anthropics/claude-code/issues/5577) (2025-08-12) asked verbatim whether it is permissible to use `ANTHROPIC_BASE_URL` for non-Anthropic models and to publish adapters enabling it. It was **closed with no Anthropic response**. Silence is not permission, but combined with B1–B3 the risk is *reputational, not contractual*. Say that plainly rather than claiming clearance.

**B5. [REPORTED] Anthropic *has* enforced, but only against the mirror-image pattern.** Early 2026 ([HN 46549823](https://news.ycombinator.com/item?id=46549823); [VentureBeat](https://venturebeat.com/technology/anthropic-cracks-down-on-unauthorized-claude-usage-by-third-party-harnesses), 403 to my fetch — cited from search summary only, so treat as **[REPORTED]**): Anthropic blocked consumer OAuth tokens extracted from Claude Code subscriptions and used inside OpenClaw / OpenCode / Roo Code / Goose. The distinction drawn in that coverage — *calling the real CLI is allowed; extracting OAuth tokens into a third-party client is banned* — is precisely the line `zai` stays on the safe side of.

### C. Quota mechanics — verified line by line against the spec

**Every number in the spec's §"Model resolution" checks out.** [VERIFIED] at `https://docs.z.ai/devpack/overview`:

> *"Model credit usage = (Input tokens × Input multiplier + Cached Input tokens × Cached Input multiplier + Output tokens × Output multiplier) / 10,000"*

| Model | Input | Cached | Output | Spec says | Verdict |
|---|---|---|---|---|---|
| GLM-5.2 | 6.9 | 1.7 | 24 | 6.9 / 1.7 / 24 | ✅ |
| GLM-5-Turbo | 5.7 | 1.5 | 21 | 5.7 / 1.5 / 21 | ✅ |
| GLM-4.7 | 4.6 | 1.2 | 16 | 4.6 / 1.2 / 16 | ✅ |
| GLM-4.6V | 1.2 | 0.3 | 2.7 | *"z.ai publishes no multiplier"* | ❌ **correction** |

| Cap | Lite | Pro | Max | Spec says | Verdict |
|---|---|---|---|---|---|
| per 5-hour window | 2 000 | 12 000 | 28 000 | 2 000 / 12 000 / 28 000 | ✅ |
| weekly | 10 000 | 60 000 | 140 000 | 10 000 / 60 000 / 140 000 | ✅ |

Peak window: *"Monday–Friday, 14:00–18:00 Singapore Standard Time"*; off-peak *"charges at 50% of standard rates"*. ✅ matches the spec.

**C1. [VERIFIED — correction] `glm-4.6v` DOES have a published multiplier (1.2 / 0.3 / 2.7).** The spec's sentence *"`glm-5.1`, `glm-5`, `glm-4.6`, `glm-4.5-air` and `glm-4.6v` are accepted by the endpoint but z.ai publishes no multiplier for them"* is **wrong for `glm-4.6v`**. Drop it from that list. (It is a vision model and has no business in a code-worker tier map — but the *stated reason* must be "it's not a coding model", not "unpublished burn rate".)

**C2. [REPORTED — the half-rate is promotional and time-boxed] The 50%-off-peak figure is not a stable property.** Multiple secondary sources describe the current state as a **promo**: off-peak eased from 2× to 1× *"through the end of September 2026"*, reverting to *"2x off-peak and 3x peak"* afterwards ([digitalapplied](https://www.digitalapplied.com/blog/glm-coding-plan-worth-it-2026-value-analysis), [techsy](https://techsy.io/en/blog/glm-5-2-coding-plan)); a separate ZCode-only promo cut peak from 3× to 2× *"through July 31, 2026"* — i.e. **today**. These are aggregator claims, not vendor text, and the 2×/3× framing does not reconcile cleanly with the docs' "50% off-peak" framing. **Do not build any arithmetic on the off-peak rate.** The spec is already correct to defer time-of-day routing to PR 2; the plan should additionally date-stamp the credit arithmetic in the adapter doc so a future reader knows it was true on 2026-07-31 and nothing more.

**C3. [VERIFIED] Exhaustion is a hard stop with no overage.** FAQ: *"Once the quota is used up, you'll need to wait until the next 5-hour cycle for it to refresh. The system will not deduct from your account balance."* Weekly quota *"starts counting from the time you place your order, and the quota is refreshed and reset on a 7-day cycle"* — i.e. **the weekly boundary is per-account, keyed to purchase date, not a calendar week**. Any operator-facing message that says "resets Monday" would be wrong.

### D. Model reality

**D1. [VERIFIED] The spec's context/output claim is wrong for two of the three models.** Per the model cards:

| Model | Context | Max output | Tuned for |
|---|---|---|---|
| `glm-5.2` | *"truly usable 1M-token context"* | *"128K"* | *"long-horizon tasks"*, *"stable long-task execution"*, *"reliable adherence to engineering standards"* |
| `glm-5-turbo` | **"200K"** | *"128K"* | *"deeply optimized for the OpenClaw scenario"* |
| `glm-4.7` | **"200K"** | *"128K"* | *"enhanced programming capabilities and more stable multi-step reasoning/execution"*; *"think before acting"* inside *"Claude Code, Kilo Code, TRAE, Cline, and Roo Code"* |

The spec asserts *"the CLI's `contextWindow` (200 000) and `maxOutputTokens` (32 000) are the alias's Anthropic defaults, not GLM's real limits (1M / 131 072)."* **131 072 = 128K is right for all three. But 1M is a `glm-5.2`-only property, and the `light` tier (`glm-5-turbo`) really is 200K.** A worker on `light` with a large repo context will hit a real 200K wall, not a cosmetic CLI default. Fix the sentence or the plan inherits a false ceiling.

**D2. [VERIFIED + REPORTED] Bare `glm-5.2` is probably **not** the 1M variant.** z.ai's own docs and every setup guide say the 1M window inside Claude Code is selected by the model id **`glm-5.2[1m]`**, not `glm-5.2` ([apidog](https://apidog.com/blog/glm-5-2-claude-code-cline-cursor/), [digitalapplied](https://www.digitalapplied.com/blog/run-glm-5-2-inside-claude-code-setup-guide) — *"The model ID is `glm-5.2` everywhere except inside Claude Code, where you use the 1M-context variant `glm-5.2[1m]`"*). And **[REPORTED]** LiteLLM issue [#32218](https://github.com/BerriAI/litellm/issues/32218) shows `glm-5.2[1m]` rejected with *"ZaiException - Unknown Model, please check the model code."* while plain `glm-5.2` works — the same `1211` the spec's probe hit. So the bracket suffix is documented, is the only documented route to 1M, and is at least sometimes rejected. The plan should either (a) probe `glm-5.2[1m]` once and record the result, or (b) state explicitly that `zai` runs the default window and makes no 1M claim. **Do not silently imply 1M.**

**D3. [NOT FOUND — say so out loud] There is no practitioner evidence either way on GLM scope discipline.**
I searched Reddit, HN, dev.to/Medium and GitHub for reports that any GLM model touches files it was told not to, or breaks a strict scope lock, in Claude Code. **Nothing.** Every comparison found is a vendor page or an SEO listicle grading chat/coding quality.
What *is* on record cuts in an awkward direction for the spec's tier map:
- **[VERIFIED]** `glm-5-turbo` is *"deeply optimized for the **OpenClaw** scenario"* — a general-purpose personal-assistant harness which sits on z.ai's **best-effort** tier, not the coding tier. Its documented strengths (*"Enhanced Decomposition of Complex Instructions"*, *"Precise Invocation, No Failures"*, *"long-chain execution"*) are agent-loop virtues, not file-scope virtues.
- **[VERIFIED]** `glm-4.7` is the one whose card names Claude Code by name and claims a *"think before acting"* mechanism inside it.
- **[ISOLATED REPORT]** [MindStudio, 2026](https://www.mindstudio.ai/blog/glm-5-2-vs-gpt-5-5-vs-claude-opus-agentic-workflows) claims *GLM 5.2 "can execute well-defined sub-tasks but struggles with the self-correcting behavior… If early code has a bug, GLM 5.2 is more likely to continue building on the broken foundation rather than backtracking."* One vendor-adjacent blog, no methodology. **Do not treat as a design input** — but it is a hypothesis worth the acceptance command catching.

**Consequence for the plan:** the `light → glm-5-turbo` choice is defended in the spec on **latency**, which is a fine reason and needs no benchmark. But the spec's implicit claim that any of these three is safe under a strict scope lock is **unevidenced in both directions**. The honest position — and the one that matches this repo's style — is: *"no public evidence exists on GLM scope discipline in a file-allow-list harness; the git-derived scope gate is the only thing standing between a stray edit and a merge, and the first N runs are the evidence."* Consider making `glm-4.7` the `light` default instead, on the strength of its Claude-Code-specific card and its 32% cheaper burn, and demoting `glm-5-turbo` to the documented override. That is a design suggestion, not a constraint.

### E. Claude Code harness semantics the spec gets partly wrong

**E1. [VERIFIED — security claim needs fixing] `--allowedTools` does not withhold Bash. Read-only Bash runs in `dontAsk` regardless.**
The spec says: *"`Bash` is deliberately withheld… Under `dontAsk` an off-list tool is refused rather than prompted."* Half right.
- [CLI reference](https://code.claude.com/docs/en/cli-reference): `--allowedTools` = *"Tools that execute without prompting for permission… **To restrict which tools are available, use `--tools` instead**."*
- [headless doc](https://code.claude.com/docs/en/headless): *"In bare mode Claude has access to the **Bash**, file read, and file edit tools."*
- [permission-modes](https://code.claude.com/docs/en/permission-modes): *"If you set `dontAsk` mode, Claude Code auto-denies every tool call that would otherwise prompt you. Claude runs only actions matching your `permissions.allow` rules, **read-only Bash commands**, and calls approved by a PreToolUse hook."*
- [permissions](https://code.claude.com/docs/en/permissions): *"Claude Code recognizes a built-in set of Bash commands as read-only and runs them without a permission prompt **in every mode**. These include `ls`, `cat`, `echo`, `pwd`, `head`, `tail`, `grep`, `find`, `wc`, `which`, `diff`, `stat`, `du`, `cd`, and read-only forms of `git`. **The set is not configurable**."*

So a `zai` worker under the spec's exact flags **does get a read-only shell**, including read-only `git`. The arbitrary-command channel really is closed — the spec's *security* conclusion survives — but its *mechanism* description is wrong and a reviewer will catch it.
Two documented ways to actually remove the tool: `--tools` (restricts availability), or a **bare-name deny rule** — *"A bare tool name like `Bash` removes the tool from Claude's context entirely, so Claude never sees it."* In bare mode, settings auto-discovery is skipped, so a deny rule must be passed via `--settings '{"permissions":{"deny":["Bash"]}}'`.
Also note: **`--bare` skips hooks**, so the `PreToolUse` escape hatch named in the `dontAsk` docs is unavailable to this worker. Nothing else to fall back on.

**E2. [VERIFIED] The env allow-list is missing two variables z.ai's own setup sets.**
`https://docs.z.ai/devpack/tool/claude` configures, beyond base URL and key:
- `"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": 1` — suppresses non-essential calls. Under `env -i` with only `PATH HOME TMPDIR LANG` + three `ANTHROPIC_*`, this is **not forwarded**, so whatever non-essential traffic Claude Code emits goes to **z.ai** and burns Coding Plan credits on requests the operator never asked for.
- `"API_TIMEOUT_MS": "3000000"` (50 minutes) — z.ai considers a very long client timeout necessary. Not forwarded either, so Claude Code's default applies. See E4.

**E3. [VERIFIED — likely a real bug] The haiku/small-fast model slot is unset, and it is exactly the shape that produces `1211`.**
z.ai's Claude Code doc sets **three** model variables:
```
ANTHROPIC_DEFAULT_OPUS_MODEL   = glm-5.2
ANTHROPIC_DEFAULT_SONNET_MODEL = glm-5.2
ANTHROPIC_DEFAULT_HAIKU_MODEL  = glm-4.7
```
The spec injects only `ANTHROPIC_MODEL`. Claude Code routes some traffic to the small/fast ("haiku") slot independently of `ANTHROPIC_MODEL`. With the slot unset against a z.ai base URL, that request carries an Anthropic haiku model id. The spec's own probe established that z.ai maps *some* Anthropic aliases (`claude-opus-4-8` accepted) and rejects unknown ids with **`400 [1211][Unknown Model…]`** — so this is either silently fine or the single most likely first production failure, and **the spec has not tested it**.
This collides head-on with this repo's **never-Haiku** rule (`CONVENTIONS.md`, `scripts/lint-frontmatter.py:124-126`). The resolution is clean once stated: `ANTHROPIC_DEFAULT_HAIKU_MODEL` is an **env var naming a Claude Code routing slot**, not a `model:` frontmatter value, and setting it to `glm-4.7` puts *zero* Haiku in the run. The linter greps frontmatter, so nothing breaks — but a reviewer will flinch at the variable name and the plan should pre-empt that in one sentence.

**E4. [REPORTED, layer-scoped] z.ai closes idle connections mid-stream.**
opencode issue [#15350](https://github.com/anomalyco/opencode/issues/15350): `error={"error":{"code":"ECONNRESET","path":"https://api.z.ai/api/coding/paas/v4/chat/completions","errno":0}}`, *101 consecutive ECONNRESET failures in a single session*, resets landing *"after approximately 40-100 seconds of streaming"*; the reporter attributes it to z.ai terminating idle keep-alive connections after 30–60s while the client reuses them. Closed **"not planned"**, no z.ai response.
**Scope honestly:** that is the **OpenAI-compat** layer, not `/api/anthropic`, and the client was Bun. It is not proof the Anthropic layer behaves the same way. But it is a plausible shared-infrastructure behaviour, it explains why z.ai's own docs recommend a 50-minute `API_TIMEOUT_MS`, and a 900-second `timeout_sec` job that dies at t=60s with a transport error is indistinguishable from a hang unless `failure_class` can say `network`.

### F. Operational failure modes — the error surface the spec says it has not seen

**F1. [VERIFIED] z.ai publishes the entire quota/rate-limit error surface. The spec's "have not been observed and must not be invented" is honest about *its probes* but wrong about *the documentation*.** From `https://docs.z.ai/api-reference/api-code`:

| Code | HTTP | Message (verbatim) | Maps to |
|---|---|---|---|
| `1113` | **429** | `Insufficient balance or no resource package. Please recharge.` | `out_of_credits` |
| `1210` | 400 | `Invalid API parameter, please check the documentation.` | `other` |
| `1211` | 400 | `Unknown Model, please check the model code.` | `other` ✅ (the one the spec saw) |
| `1301` | 400 | `System detected potentially unsafe or sensitive content in input or generation…` | `other` |
| `1302` | **429** | `Rate limit reached for requests` | `rate_limited` |
| `1305` | **429** | `The service may be temporarily overloaded, please try again later` | `overloaded` |
| `1308` | **429** | `Usage limit reached for {number} {unit}. Your limit will reset at {next_flush_time}` | `rate_limited` |
| `1310` | **429** | `Weekly/Monthly Limit Exhausted. Your limit will reset at {next_flush_time}` | `out_of_credits` |
| `1311` | **429** | `Your current subscription plan does not yet include access to ${model_name}` | `auth` / `other` |
| `1316` | **429** | `Usage limit reached for the past 5 hours. Insufficient balance for extra usage…` | `rate_limited` |
| `1317` | **429** | `Usage limit reached for the past 7 days. Insufficient balance for extra usage…` | `out_of_credits` |

Documented error envelope: `{"error":{"code":"XXXX","message":"…"}}`.
**[VERIFIED] No `Retry-After` header is documented anywhere in z.ai's API reference.** `1308`/`1310`/`1316`/`1317` instead put a `{next_flush_time}` **inside the message string**. So a client cannot do standards-based backoff; it must parse prose or use a fixed schedule.
**[NOT FOUND]** — how these render *through* `api.z.ai/api/anthropic` into Claude Code's `API Error: …` line. The spec's one observed sample (`API Error: 400 [1211][…][<trace-id>]`) shows the shape is `[code][message][trace-id]`, which strongly suggests `[1316]`, `[1302]` etc. will render the same way. **Suggestive, not verified** — the plan should say the needle set is derived from documented codes and confirmed for `1211` only.

**F2. [REPORTED] There was a real enforcement wave in April 2026 and it surfaced as `1302`/`1303`.**
[Awesome Agents, 2026-04-20](https://awesomeagents.ai/news/zai-coding-plan-bans-non-coding-use/) and [OfficeChai, 2026-04-20](https://officechai.com/ai/after-claude-google-z-ai-restricts-openclaw-like-non-coding-usage-on-its-coding-plans-openclaw-creator-responds/) both report codes `1302`/`1303` appearing across SillyTavern, opencode and Letta-code communities in the week of 2026-04-14, attributed to z.ai's non-coding-use crackdown. Two independent outlets, same week, same codes — enough to call a **pattern**, not enough to call a mechanism. Note `1303` is **not** in the published error table; treat it as **[REPORTED]** only.
**The operationally important part:** enforcement throttling is *indistinguishable at the wire from ordinary rate limiting*. A dispatcher that reacts to `429` by retrying harder is, from z.ai's risk-control perspective, doing the thing that got people throttled.

**F3. [REPORTED] Blanket failure is a known z.ai mode.** openclaw issue [#31234](https://github.com/openclaw/openclaw/issues/31234): *"Every request fails with an API limit/usage error"*, *"100% of the time across sessions"*, open with no root cause. No error bodies were captured in the thread. A `zai` backend must be able to circuit-break on *sustained* provider failure, not just retry per-job.

**F4. [REPORTED — Anthropic-side, but the same shape] Bursty parallel launches trip server-side limiters even at top tier.** claude-code issue [#53922](https://github.com/anthropics/claude-code/issues/53922): bulk-spawning ~10 sessions, *"the first 3-4 work, the rest fail with 'Server is temporarily limiting requests (not your usage limit) · Rate limited'"*; issue [#62426](https://github.com/anthropics/claude-code/issues/62426): *"Rate limits blocking multi-agent Claude Code workflows even at highest paid tier"*. Different vendor, but it is the identical anti-pattern: **simultaneous cold-start of N workers looks like an attack**. Stagger.

---

## 4. Common Traps in This Domain

1. **Reading a tool allow-list as an endorsement of every invocation mode.** "Claude Code is supported" answers *which binary*. It does not answer *how many at once*, *from what process*, or *whose key*. Those live in three different clauses, and A6 is the one with no published number.
2. **Treating an undocumented limit as absent.** z.ai's concurrency cap is explicitly *"adjusted dynamically based on resource availability"*. A design validated at 3 concurrent on a Tuesday afternoon can fail at 3 concurrent on a Thursday.
3. **Retry-storming a provider that bans on three strikes.** This repo's own KB (`autonomous-agent-orchestration.md`, 2026-07-12) already establishes that *"the circuit breaker pattern must be at the infrastructure level, not just in agent code, because if the agent is looping, it can't be trusted to stop itself."* Here the runaway cost is not dollars — it is the user's account.
4. **`--allowedTools` ≠ tool restriction.** A very common misreading; Anthropic's own CLI doc has to say *"use `--tools` instead"* out loud. See E1.
5. **Forgetting the small/fast model slot when redirecting the base URL.** The main model is the obvious one to set and the least likely to be the thing that 400s. See E3.
6. **Building arithmetic on a promotional rate.** Off-peak pricing has changed at least twice in 2026 and at least one promo expires **today**. See C2.
7. **Assuming an Anthropic-compatible endpoint is Anthropic-equivalent.** Same wire format, different: model ids, error envelope, cache semantics, keep-alive behaviour, `Retry-After` (absent), context ceilings, and — critically — different *terms*.
8. **Publishing a plugin whose failure mode lands on the user's account, not the author's.** The whole risk in this feature is externalized to whoever installs it.

---

## 5. Regulatory / Compliance Notes

Not a regulated domain — no GDPR/HIPAA/PCI surface. The compliance surface is **contractual**, and it is two-sided:

| | z.ai | Anthropic |
|---|---|---|
| Is the invocation permitted? | **Yes** — Claude Code is Tier-1 supported and this is the real binary (A1, A2) | **Yes** — no clause prohibits it; third-party endpoints are a documented feature (B1, B2) |
| What could go wrong | automated risk control: throttle → freeze → ban at 3 violations (A4) | reputational only; no contractual hook found (B4) |
| Who pays | **the end user** — their subscription | nobody |
| Written escape hatch | appeal via console Plan Overview; **no published SLA** | n/a |
| Live prohibitions this design must not cross | account sharing / multi-user (A3); resell / repackage / **aggregate** / proxy (A3); non-coding scenarios (A5); general-purpose API access (A2) | routing requests through Anthropic **subscription credentials** on a user's behalf (B1) — not applicable here, and `--bare` makes it impossible (B3) |

**No jurisdictional filing, licence, or disclosure obligation applies.** The one genuinely regulatory-flavoured item is that z.ai's terms license the plan *"only to the individual natural person associated with such account"* — which makes **CI use, team-shared keys, and hosted deployments** out of bounds regardless of how the plugin behaves. That belongs in user-facing documentation, not just in a design doc.

---

## 6. Recent Breaking Changes (last 12 months)

| When | What | Impact on this design |
|---|---|---|
| **2026-03-22** [REPORTED] | `--bare` added to Claude Code *"for scripted `-p` calls that skips hooks, LSP, plugin sync, and skill directory walks; it requires `ANTHROPIC_API_KEY` or `apiKeyHelper` via `--settings`"* ([gradually.ai changelog](https://www.gradually.ai/en/changelogs/claude-code/)) | The flag the whole design rests on is **~4 months old**. Corroborated by the live docs (B3). |
| ongoing [VERIFIED] | *"`--bare` … will become the default for `-p` in a future release"* ([headless doc](https://code.claude.com/docs/en/headless)) | Argues **for** the design: the plugin is adopting the future default early. Also means the `claude` backend's non-bare behaviour may shift under it later. |
| **~2026-01** [REPORTED] | Anthropic blocked third-party harnesses using extracted Claude Code OAuth tokens (OpenClaw/OpenCode/Roo Code/Goose) ([HN 46549823](https://news.ycombinator.com/item?id=46549823)) | Establishes the enforcement line — and that `zai` is on the safe side of it (B5). |
| **2026-01-15** [ISOLATED REPORT] | z.ai Coding Plan concurrency reported at **1** for GLM-4.7 on Pro, apparently reduced from 3 ([opencode #8618](https://github.com/anomalyco/opencode/issues/8618)) | Directly threatens the "consume three providers' quotas in parallel" premise (A6). |
| **~2026-04-14** [REPORTED] | z.ai non-coding-use enforcement wave; `1302`/`1303` throttling across multiple client communities (two outlets, 2026-04-20) | Enforcement is live, automated, and wire-indistinguishable from rate limiting (F2). |
| **2026-06-14** [REPORTED] | GLM-5.2 launched with 1M context and **no benchmarks at launch** ([MarkTechPost, 2026-06-14](https://www.marktechpost.com/2026/06/14/z-ai-launches-glm-5-2-with-a-usable-1m-token-context-two-thinking-effort-levels-and-no-benchmarks-at-launch/)) | Explains D3: there is no vendor benchmark to appeal to, and the community hasn't produced a scope-discipline one either. |
| **through 2026-09-30** [REPORTED] | Off-peak quota multiplier promo (2× → 1×); a separate ZCode peak promo (3× → 2×) **expires 2026-07-31** | Any credit arithmetic in the adapter doc is a dated snapshot (C2). |
| **deprecated** [VERIFIED via docs] | `ANTHROPIC_SMALL_FAST_MODEL` → replaced by `ANTHROPIC_DEFAULT_HAIKU_MODEL` | If E3 is fixed, use the current name. |

---

## 7. Design Constraints for the Plan (non-negotiable)

Ranked. **M1–M4 are blocking-adjacent: the plan is not safe to dispatch without them.**

### MUST

- **M1. Cap and stagger `zai` concurrency; do not assume it parallelizes.** z.ai publishes **no** concurrency number, states it is *"adjusted dynamically"*, and the only field report puts it at **1** on Pro (A6, F4). The plan MUST (a) default `zai` to a **conservative per-batch cap** (1–2 concurrent, config-overridable), (b) **stagger worker starts**, and (c) state in the PR that the "three providers in parallel" claim is **unproven for z.ai** and awaits measurement. Shipping 4–6 concurrent `zai` workers on an unmeasured cap is the single highest-risk decision in this spec.
- **M2. Ship the documented 429 needle set now; do not "fail closed to `other`" on quota walls.** All of `1113 · 1302 · 1305 · 1308 · 1310 · 1311 · 1316 · 1317` are published with HTTP 429 and exact messages (F1). `scripts/compound-v-classify-failure.py --backend zai` MUST map them to `rate_limited` / `out_of_credits` / `overloaded` / `auth`. The spec's *"must not be invented"* discipline is right and MUST be preserved by **citing docs.z.ai as the source and marking every needle except `1211` as documentation-derived, not observation-derived.**
- **M3. Bound retries, and add a per-backend circuit breaker.** No `Retry-After` exists (F1); `next_flush_time` is embedded in prose. Combined with a **three-violation ban** (A4) and enforcement that looks exactly like rate limiting (F2), an unbounded retry loop can cost a user their subscription. MUST: fixed low retry ceiling on any `zai` 429, exponential backoff, and a circuit breaker that stops dispatching to `zai` for the rest of the run after N consecutive quota/rate failures (cf. this repo's KB: enforcement outside the agent's own loop).
- **M4. Set `ANTHROPIC_DEFAULT_HAIKU_MODEL` (and the Opus/Sonnet slots) in the injected env, or prove they are unused.** (E3) MUST either forward all three model-slot variables per z.ai's own Claude Code doc, or add a probe to the acceptance evidence showing a `--bare` run makes **zero** small-fast-model requests. Add one sentence to the PR pre-empting the never-Haiku reflex: this is a Claude Code routing-slot env var, not a `model:` frontmatter value, and it puts no Haiku anywhere.
- **M5. Correct the Bash claim, and withhold Bash by a mechanism that actually withholds it.** (E1) `--allowedTools` only pre-approves; `dontAsk` still runs the **non-configurable read-only Bash set** (`ls cat grep find diff stat du cd`, read-only `git`); `--bare` disables the `PreToolUse` fallback. MUST either use `--tools` / `--settings '{"permissions":{"deny":["Bash"]}}'`, or rewrite the spec's sentence to say accurately: *"arbitrary commands are denied; a non-configurable read-only shell subset remains."*
- **M6. Fix the context/output claim per model.** (D1) `glm-5-turbo` and `glm-4.7` are **200K**, not 1M. Only `glm-5.2` is 1M — and **[REPORTED]** only via the `glm-5.2[1m]` id, which is itself sometimes rejected (D2). The plan MUST either probe `glm-5.2[1m]` and record the result, or state that `zai` runs the default window and makes no 1M claim.
- **M7. Drop `glm-4.6v` from the "no published multiplier" list.** (C1) It publishes 1.2 / 0.3 / 2.7. Exclude it because it is a vision model, not because its burn is unknown.
- **M8. Forward `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`, and set an explicit API timeout.** (E2) z.ai's own setup sets both. Under `env -i` neither reaches the worker, so non-essential traffic bills the user's Coding Plan and the client timeout is Claude Code's default against a provider documented to want 50 minutes. Adding these to the injected set changes AC #7 — the allow-list assertion must be updated in lockstep, not silently.
- **M9. Document the personal-use boundary in user-facing docs, not only the design doc.** (A3) z.ai licenses the plan *"only to the individual natural person associated with such account"* and forbids sharing, resale, repackaging, **aggregation** and proxying. The README "Good to know" section MUST say: `zai` is for **your own key on your own machine**; **not** for CI, not for a shared team key, not for a hosted deployment.
- **M10. Keep `zai` opt-in and off by default, and gate it behind an explicit acknowledgement in `/v:init`.** The failure mode lands on the **user's** z.ai account, not the author's (§4.8). This is the same reasoning already applied to antigravity and cursor as "lower-trust, opt-in" — extend it, and make the acknowledgement about *account risk*, not just sandbox trust.
- **M11. Date-stamp every credit/quota number in the adapter doc.** (C2) The off-peak rate is promotional and at least one promo expires today. Write "verified against docs.z.ai on 2026-07-31" beside the multiplier table.

### MUST NOT

- **N1. MUST NOT give `zai` a reviewer, arbiter, advisor, or summarizer seat.** Already a non-goal; it is now **load-bearing**, because z.ai restricts benefits for *"requests clearly unrelated to coding scenarios"* (A5). Record the compliance reason alongside the existing arbiter-substring reason.
- **N2. MUST NOT claim "three providers' quotas consumed in parallel" as a measured property.** Unproven for z.ai (M1) and it is exactly the shape of claim `CONVENTIONS.md`'s anti-ruflo CI gate exists to catch. Say "designed to draw on a third quota" until measured.
- **N3. MUST NOT retry indefinitely, reroute *into* `zai* on another backend's rate-limit, or auto-escalate concurrency on 429.** Rerouting is PR 3 by design; N3 makes explicit that the v1 default must be **conservative**, not merely deferred.
- **N4. MUST NOT carry `total_cost_usd`.** Already correct in the spec, and now independently confirmed: the headless doc states `--output-format json` *"includes `total_cost_usd` and a per-model cost breakdown"* — computed from Anthropic's price table for a model that never ran. Keep it out.

### SHOULD

- **S1. SHOULD consider `glm-4.7` for `light` instead of `glm-5-turbo`.** (D3) `glm-4.7`'s card names Claude Code explicitly and claims a *"think before acting"* mechanism inside it; `glm-5-turbo` is tuned for **OpenClaw**, a best-effort-tier general-purpose harness. `glm-4.7` also burns 32% less. If latency is genuinely the deciding factor, say so and keep `glm-5-turbo` — but the current rationale does not engage with the tuning-target mismatch.
- **S2. SHOULD add `network` to the `failure_class` needles for `zai`.** (E4) ECONNRESET mid-stream is a documented z.ai behaviour on the sibling layer, and a 60-second transport death currently reads as an opaque error.
- **S3. SHOULD state the evidence gap on scope discipline in the adapter doc.** (D3) There is **no** public evidence in either direction. The honest sentence — "the git-derived scope gate is the only guarantee; the first runs are the evidence" — matches this repo's voice and pre-empts the reviewer question.
- **S4. SHOULD capture and commit the first real 429 body seen in production.** F1's needle set is documentation-derived; the spec's own discipline says observation beats documentation. Make capturing one an explicit follow-up, since PR 3's rerouting depends on it.

---

## 8. Open Questions for the Human (product/business, not technical)

1. **How much of the user's account are we willing to risk on their behalf?** Everything downstream is a rounding error next to this. z.ai bans at three violations, with an automated risk-control system, no published appeal SLA, and enforcement that looks identical to rate limiting on the wire. Options: ship opt-in with a loud acknowledgement (M10); ship with a hard concurrency cap of 1; or do not ship publicly and keep `zai` as a local config. **Only you can price this.**
2. **What concurrency does *your* plan tier actually sustain?** Nobody can answer this from documentation — z.ai publishes no number and adjusts it dynamically. It needs one empirical run at 2, 4 and 6 concurrent on the real key, on a weekday and a weekend, recording every non-200. That measurement is the difference between M1 being a permanent cap and a temporary one.
3. **Is `zai` positioned as a capacity multiplier or a cost saver?** These pull opposite ways. Capacity → high concurrency → account risk. Cost → serial, off-peak, `glm-4.7` → very low risk, modest benefit. The spec currently reads as capacity but justifies its model map on capability. Pick one and let it drive M1 and S1.
4. **Do you want `zai` in `/v:epic` marathon mode at all?** Marathon runs unattended for hours with auto-resurrection. An unattended loop retrying against a three-strike provider is the highest-consequence combination in this codebase. A simple answer — "`zai` is excluded from marathon/auto-resurrection in v1" — removes an entire risk class for one line of config.
5. **Whose key, and is a `ZAI_API_KEY` in an operator's environment ever going to be a shared team key?** M9 says the docs must forbid it. Enforcement is a different question, and the honest answer may be "we can't, we only warn."
6. **`glm-5.2[1m]` — probe it now or defer?** (D2) Deciding this decides whether the plugin can honestly claim a large context window for `zai`. It is one probe against a live key.

---

## 9. Knowledge Base Updates

Two new KB files created (no prior file covered either domain):

- **`docs/superpowers/expert/_knowledge-base/llm-subscription-plan-compliance.md`** — generalized, reusable matrix for *any* vendor coding-subscription used as an automation backend: the four clause families to check (tool allow-list · personal-use/aggregation · scenario restriction · enforcement ladder), the concurrency-is-undocumented pattern, the "enforcement is wire-indistinguishable from rate limiting" trap, and the full z.ai error/credit tables as a worked example.
- **`docs/superpowers/expert/_knowledge-base/claude-code-headless-harness.md`** — Claude Code as a scripted worker: `--bare` semantics and auth precedence, the `--allowedTools` vs `--tools` vs deny-rule distinction, the non-configurable read-only Bash set under `dontAsk`, the model-slot env vars, and the third-party-endpoint terms position.

No existing KB entries were struck through — none covered this ground.

---

## BLOCKING FINDINGS

Two. Neither kills the feature; both invalidate a claim the plan would otherwise build on.

> ### 🔴 BLOCKING-1 — The parallelism premise is unverified, and the one field report contradicts it.
> The spec's opening sentence is *"three providers' quotas are consumed in parallel"* at *"4-6 concurrent workers."* z.ai publishes **no** concurrency limit, states it is *"adjusted dynamically based on resource availability"*, and the only concrete report ([opencode #8618](https://github.com/anomalyco/opencode/issues/8618), 2026-01-15) puts it at **1 concurrent request on the Pro tier**, apparently reduced from 3, with the reporter reaching *"barely… 4% of my 5 hour limit."* A design that opens 4–6 simultaneous cold-start streams against that cap does not get parallelism — it gets a 429 storm, from a provider whose risk-control bans at three violations and whose enforcement throttling is wire-indistinguishable from ordinary rate limiting.
> **To clear:** either (a) measure real sustained concurrency on the target plan tier and record it as acceptance evidence, or (b) ship with a default cap of 1–2 concurrent `zai` jobs plus staggered starts, and restate the premise as an intention rather than a measured property. **Do not merge with an uncapped `zai` fan-out.**

> ### 🟠 BLOCKING-2 — "Quota-exhaustion shapes have not been observed and must not be invented" is true of the probes and false of the documentation.
> z.ai publishes the complete surface at `https://docs.z.ai/api-reference/api-code`: `1113`, `1302`, `1305`, `1308`, `1310`, `1311`, `1316`, `1317` — all HTTP **429**, all with exact message templates, envelope `{"error":{"code":"XXXX","message":"…"}}`, and **no `Retry-After`** (the reset time is embedded in the message prose). Shipping a `zai` classifier that fails closed to `other` means every quota wall becomes a retry — against a three-strike provider — when the correct classification was available in the vendor's own reference the whole time.
> **To clear:** implement the needle set above, mark it **documentation-derived** (only `1211` is observation-derived), and pair it with M3's retry ceiling and circuit breaker. The spec's no-invention discipline is preserved by *citing the source*, not by omitting the codes.

---

*Written by the Compound V Phase 1B domain-expert advisor, 2026-07-31. Read-only pass: no code, spec, or configuration was modified.*
