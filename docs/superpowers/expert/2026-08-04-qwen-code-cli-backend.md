# Phase 1B — Domain Audit: `qwen` (Qwen Code CLI) as a Compound V dispatch backend

**Date:** 2026-08-04
**Spec audited:** `docs/superpowers/specs/2026-08-04-qwen-code-cli-backend-design.md`
**Recon deepened:** `docs/superpowers/recon/2026-08-04-qwen-code-cli-backend-adapter.md`
**Advisor:** Compound V Phase 1B (domain / regulatory reality)

> **Headline.** Two findings are severe enough to change the shape of the feature, not just annotate it.
> **(1)** Alibaba's Coding Plan documentation — in English *and* Chinese, on Alibaba's own help pages —
> explicitly prohibits using the plan's API key for *"automated scripts, custom application backends, or any
> non-interactive batch calling scenarios,"* on pain of *"subscription suspension or API Key ban."* Compound V's
> dispatcher is, by construction, an automated script making non-interactive batched calls. This is **not** the
> same clause `zai` cleared, and the spec's reasoning-by-analogy to `zai` does not transfer.
> **(2)** The `env -i` + scratch-`HOME` isolation the spec asserts by analogy to `zai` **does not cover Qwen
> Code's threat surface**, because Qwen Code reads credentials and settings from files inside its *cwd* — the
> worktree — which no environment scrub can reach. Upstream Gemini CLI shipped a **CVSS 10.0** advisory for
> exactly this configuration (headless + `--yolo` + workspace trust) on 2026-04-24; Qwen Code forked upstream
> **~31 minor versions before the fix**, and its own folder-trust mitigation is **documented as off by default**.

---

## 1. Domain(s) Identified

| Domain | KB file | Why |
|---|---|---|
| `llm-subscription-plan-compliance` | **existed** — reused, updated | Coding subscription driven as an automation backend; ToS/quota/enforcement reality |
| `claude-code-headless-harness` | **existed** — reviewed, updated | Headless coding-CLI-as-worker: credential scrub, config discovery, sandbox claims |
| `ai-tooling-jurisdictional-risk` | **created** | Routing proprietary source code through a foreign-jurisdiction cloud provider |

---

## 2. Sources Consulted

### Knowledge base reused (no re-derivation)

- `docs/superpowers/expert/_knowledge-base/llm-subscription-plan-compliance.md` — last updated **2026-07-31**
  (4 days old, primary-sourced ⇒ authoritative, no re-verification needed). Its **four-clause-family checklist**
  is the instrument that found finding (1); its reusable one-liner *"'Supported tool' answers which binary, not
  how many at once, from what process, or whose key"* is precisely the trap this spec fell into.
- `docs/superpowers/expert/_knowledge-base/claude-code-headless-harness.md` — last updated 2026-08-01.
- In-repo precedent read directly: `skills/backend-launcher/adapter-zai.md` (Compliance + Safety sections, the
  stated bar), `scripts/compound-v-run-zai-worker.sh` (the `_SAFE_ENV_VARS` allow-list shape).

### Primary sources (fetched 2026-08-04)

| Source | What it settled |
|---|---|
| [Alibaba Cloud — Coding Plan (EN)](https://www.alibabacloud.com/help/en/model-studio/coding-plan) | Prohibition on non-interactive use; sharing ban; quotas; violation consequences |
| [阿里云 — Coding Plan (ZH, original)](https://help.aliyun.com/zh/model-studio/coding-plan) | The authoritative Chinese wording, incl. the load-bearing qualifier 「以 API 调用的形式」 |
| [Alibaba Cloud — Coding Plan FAQ (EN)](https://www.alibabacloud.com/help/en/model-studio/coding-plan-faq) | Quota unit = model calls; dynamic concurrency limit; no PAYG fallback; Lite discontinued |
| [阿里云 — Coding Plan FAQ (ZH)](https://help.aliyun.com/zh/model-studio/coding-plan-faq) | Auto-disable on detected key exposure; interactive-use definition by contrast |
| [Model Studio — privacy notice](https://www.alibabacloud.com/help/en/model-studio/privacy-notice) | "never use your data for model training"; AES-256; SOC 2 |
| [Alibaba Cloud Intl — Product Terms of Service v3.8.0](https://www.alibabacloud.com/help/en/legal/latest/alibaba-cloud-international-website-product-terms-of-service-v-3-8-0) | Resale/sublicense prohibition; account transfer prohibition |
| [Qwen Code — Authentication](https://qwenlm.github.io/qwen-code-docs/en/users/configuration/auth/) | Credential precedence; `.env` search order; **stops at first file**; env not overwritten |
| [Qwen Code — Settings](https://qwenlm.github.io/qwen-code-docs/en/users/configuration/settings/) | Settings precedence incl. project `.qwen/settings.json`; `advanced.excludedEnvVars` |
| [Qwen Code — Headless](https://qwenlm.github.io/qwen-code-docs/en/users/features/headless/) | *"ideal for scripting, automation, CI/CD pipelines"*; `--max-session-turns`, `--max-wall-time`; **no `--cd`** |
| [Qwen Code — Trusted Folders](https://qwenlm.github.io/qwen-code-docs/en/users/configuration/trusted-folders/) | `security.folderTrust.enabled`, **disabled by default**; what untrusted blocks |
| [GHSA-wpqr-6v78-jr5g](https://github.com/advisories/GHSA-wpqr-6v78-jr5g) | **CVSS 10.0** Gemini CLI RCE via workspace trust + `--yolo` allowlist bypass, 2026-04-24 |

### Community / practitioner (Layer 2–3)

| Source | Date | Weight |
|---|---|---|
| [qwen-code #1855](https://github.com/QwenLM/qwen-code/issues/1855) — OAuth session persists over new Coding Plan key ⇒ 401 | 2026-02-17, closed | Single issue — **isolated report**, but mechanism-corroborating |
| [qwen-code #2217](https://github.com/QwenLM/qwen-code/issues/2217), [#2191](https://github.com/QwenLM/qwen-code/issues/2191), [#2146](https://github.com/QwenLM/qwen-code/issues/2146), [#1742](https://github.com/QwenLM/qwen-code/issues/1742), [#882](https://github.com/QwenLM/qwen-code/issues/882), [#1983](https://github.com/QwenLM/qwen-code/issues/1983) | 2026 | **6 threads** — DashScope 429 / `THROTTLING.userQPSLimit` is a live, recurring surface |
| [qwen-code #2006](https://github.com/QwenLM/qwen-code/issues/2006) (closed via PR #2018), [#504](https://github.com/QwenLM/qwen-code/issues/504) | 2026-02-28 | AGENTS.md adopted as a default context file |
| [HN 48772443](https://news.ycombinator.com/item?id=48772443) — Reuters: Alibaba bans Claude Code internally over backdoor risk | 2026-07-03, 336 pts / 281 comments | Above threshold — vendor-policy signal |
| [HN 47789014](https://news.ycombinator.com/item?id=47789014) — Qwen free tier discontinued | 2026 | Confirms OAuth-tier EOL |
| [Penligent — Gemini CLI RCE / CI-CD agent attack surface](https://www.penligent.ai/hackinglabs/gemini-cli-rce-workspace-trust-and-the-ci-cd-agent-attack-surface/) | 2026-04-28 | Independent technical write-up of the advisory chain |
| [NatLawReview — Choosing Between U.S. and Chinese AI Models: Export Control Risks on Both Sides](https://natlawreview.com/article/choosing-between-us-and-chinese-ai-models-export-control-risks-both-sides) | 2026 | Legal-press framing of the jurisdictional class |
| [CSA — Sovereign AI Risk: When Your AI Vendor Gets Export-Controlled](https://labs.cloudsecurityalliance.org/research/csa-whitepaper-sovereign-ai-risk-export-controls-enterprise/) | 2026 | Industry-body framing |

### Searches that returned nothing usable — stated, not padded

- **`site:reddit.com` Qwen Coding Plan ban/rate-limit experience** — **NO RELEVANT HITS.** The engine returned
  Wikipedia and crypto-news noise. I therefore have **zero** community evidence about how Alibaba enforces the
  non-interactive clause in practice. That absence is itself a finding: the enforcement ladder for this plan is
  **unmeasured**, unlike z.ai's (which had two press reports and reproducible error codes).
- **Alibaba Model Studio data-retention period / retention opt-out** — **NOT FOUND** on any Alibaba-owned page.
  The privacy notice states data is stored "in compliance with relevant laws and regulations" and gives **no
  retention period, no region, and no deletion mechanism**.
- **`coding-intl.dashscope.aliyuncs.com` residency statement** — **NOT FOUND** as a first-party commitment. The
  `ap-southeast-1`/Singapore association is inferred from Alibaba's general DashScope-International endpoint
  documentation, **not** from a Coding-Plan-specific residency guarantee.

---

## 3. Domain Constraints the Brainstorm Probably Missed

### 3.1 🔴 The Coding Plan prohibits exactly what Compound V does (MUST resolve before shipping)

The spec's Compliance posture is **silent** — it has no Compliance section at all, while `adapter-zai.md` has a
dedicated one. That silence is a real gap, and worse than a gap: the spec inherits `zai`'s *conclusion*
("spawning the vendor-approved binary is the compliant path") without re-checking whether `zai`'s *reasoning*
survives the change of vendor. It does not.

**Verbatim, Alibaba's own Chinese page** ([help.aliyun.com/zh/model-studio/coding-plan](https://help.aliyun.com/zh/model-studio/coding-plan), fetched 2026-08-04):

> 「仅限在编程工具（如 Claude Code、OpenClaw 等）中使用，禁止以 API 调用的形式用于自动化脚本、自定义应用程序后端或任何非交互式批量调用场景。」
>
> 「将套餐 API Key 用于允许范围之外的调用将被视为违规或滥用，可能会导致订阅被暂停或 API Key 被封禁。」

**Verbatim, Alibaba's English page** ([alibabacloud.com/help/en/model-studio/coding-plan](https://www.alibabacloud.com/help/en/model-studio/coding-plan), under the heading *"Prohibition of API calls"*):

> "This plan is for interactive use in programming tools such as Claude Code and OpenClaw. Do not use the plan's
> API key for automated scripts, application backends, or other non-interactive scenarios."
>
> "Using the API key outside the permitted scope is a violation that may result in subscription suspension or
> API Key revocation."

**Why `zai`'s reasoning does not transfer — this is the crux.** The two clauses restrict *different axes*:

| | z.ai GLM Coding Plan | Alibaba Bailian Coding Plan |
|---|---|---|
| Restricted axis | **Which client** — bans *"directly invoking model APIs"*, *"SDK-based access"* | **Mode of use** — bans *"automated scripts"*, *"non-interactive batch calling scenarios"* |
| Does spawning the approved binary cure it? | **Yes** — the binary makes its own HTTP calls, so it is not SDK access | **Not necessarily** — a script driving an approved binary is still an automated script running non-interactively |
| Compound V's status | Inside the line (adapter-zai.md's stated reasoning holds) | **Genuinely ambiguous** |

**The countervailing reading, stated fairly.** Two facts cut the other way and must not be suppressed:

1. The Chinese original qualifies the prohibition with **「以 API 调用的形式」** — *"in the form of API calls."*
   That qualifier plausibly scopes the ban to calling the endpoint **directly**, bypassing an approved tool.
2. The FAQ's own examples of prohibited use are **curl, Postman, and Dify** — all direct-API/bypass patterns,
   not "an approved tool driven by a script." And **Qwen Code is itself on the supported-tools list**, while
   Qwen Code's own documentation markets headless mode as *"ideal for scripting, automation, CI/CD pipelines"*
   ([headless docs](https://qwenlm.github.io/qwen-code-docs/en/users/features/headless/)).

So Alibaba ships a first-party tool whose headless mode is designed for automation, and a subscription whose
terms prohibit automation. **That contradiction is Alibaba's, not ours — but the account risk lands on the
operator.** I cannot resolve it from public documentation, and I found **no** community report of anyone testing
it. The honest verdict: **materially riskier than `zai`, unresolvable without Alibaba, and a decision the human
must make with the clause in front of them** — not a footnote the plan can quietly inherit.

**Aggravating detail specific to this spec:** the **advisor-mode** role is the weakest position of all. An
advisor consult is a review/second-opinion call, not an interactive programming session in a programming tool.
It is the least defensible use under both readings, and the spec proposes it as a *new* capability.

**Reusable rule (added to KB):** *tool allow-list membership answers "which binary," never "driven by what."
When a plan restricts the* **mode** *of use rather than the* **client**, *spawning the approved binary does not
cure the violation.*

### 3.2 🔴 `env -i` + scratch-`HOME` does NOT isolate Qwen Code the way it isolates Claude Code

The spec (lines 74–89) asserts its isolation "mirrors `zai`'s `env -i` allow-list + scratch-`HOME` shape,
adapted to Qwen Code's own config path." **The adaptation is incomplete, and the gap is the one the dispatcher
prompt asked about — it is real.**

Claude Code's credential/config surface is essentially `$HOME`-rooted, so redirecting `HOME` +
`CLAUDE_CONFIG_DIR` covers it. **Qwen Code's surface is `cwd`-rooted as well as `$HOME`-rooted**, and `cwd` is
the worktree — a checkout of the repository under test.

Verified discovery order ([auth docs](https://qwenlm.github.io/qwen-code-docs/en/users/configuration/auth/),
[settings docs](https://qwenlm.github.io/qwen-code-docs/en/users/configuration/settings/)):

```
.env search (STOPS at first file found; files are NOT merged):
  1. .qwen/.env      ← INSIDE THE WORKTREE   ← env -i cannot reach this
  2. .env            ← INSIDE THE WORKTREE   ← env -i cannot reach this
  3. ~/.qwen/.env    ← scratch HOME (covered)
  4. ~/.env          ← scratch HOME (covered)

settings precedence (low → high):
  defaults → system defaults → user (~/.qwen) → PROJECT (.qwen/settings.json) → system → env vars → CLI flags
                                                 ↑ INSIDE THE WORKTREE
```

**What the environment scrub still protects:** *"Only variables not already present in `process.env` are
loaded."* Because the invocation exports `BAILIAN_CODING_PLAN_API_KEY` and `OPENAI_BASE_URL`, a worktree `.env`
**cannot overwrite them**. The Coding Plan key cannot be hijacked by simple override. Credit where due — that
half of the design holds.

**What it does not protect — four concrete paths:**

1. **Variable injection, not override.** Any name the scrub does *not* set is free real estate. `OPENAI_API_KEY`
   is unset by the spec's invocation and is a *first-class auth path* in Qwen Code's precedence list — a
   worktree `.env` can supply it and silently change which credential and which endpoint the job authenticates
   against. This is the identical failure mode that forced the `opencode` worker's scrub into existence
   (opencode was observed authenticating from an inherited ambient `ANTHROPIC_BASE_URL`) and that `zai`'s
   **GLM assertion** was invented to catch. **`qwen` has no equivalent assertion in this spec.**
2. **`.qwen/.env` is exempt from all filtering.** The docs state exclusions apply to project `.env` but
   *"Variables from `.qwen/.env` files are never excluded."* The highest-priority `.env` is also the least
   filtered, and it lives in the worktree.
3. **Project `.qwen/settings.json` outranks user settings.** A worktree settings file can set `tools.sandbox`
   (i.e. **turn off** the optional kernel sandbox the spec offers as the mitigating control),
   `advanced.excludedEnvVars` (empty the exclusion list), tool permissions, and — per the upstream advisory's
   attack chain — **`mcpServers`**, which are arbitrary local commands. An MCP server writes wherever it likes:
   **outside the model's tool loop, outside the git scope gate, and outside any `--sandbox` the settings file
   just disabled.**
4. **`git worktree add` narrows but does not close this.** A worktree materializes **tracked files only**, so
   the operator's own gitignored `.env` does **not** travel into the worktree — a genuine and worth-stating
   mitigation the spec should claim explicitly. Three live paths remain: a repo that *tracks* `.env`/`.qwen/`;
   a resumed or re-dispatched job re-entering a worktree a previous job wrote into; and any repo whose HEAD is
   not fully trusted.

**The upstream precedent is not hypothetical.** [GHSA-wpqr-6v78-jr5g](https://github.com/advisories/GHSA-wpqr-6v78-jr5g)
(published 2026-04-24, **Critical, CVSS 10.0**, `@google/gemini-cli` < 0.39.1) describes this exact chain:

> "Gemini CLI running in CI environments (headless mode) automatically trusted workspace folders for the purpose
> of loading configuration and environment variables. This is potentially risky in situations where Gemini CLI
> runs on untrusted folders in headless mode… If used with untrusted directory contents, this could lead to
> remote code execution."

and, separately:

> under `--yolo` mode, the tool allowlist "was ignored entirely" — "an allowlist intended to permit
> `run_shell_command(echo)` could effectively allow any command."

**Qwen Code is a fork of Gemini CLI v0.8.2** (recon [F6]). The fix landed in **0.39.1** — roughly **31 minor
versions** after the fork point. Qwen Code *does* ship a
[Trusted Folders](https://qwenlm.github.io/qwen-code-docs/en/users/configuration/trusted-folders/) feature that
blocks exactly the right things when a folder is untrusted (`.qwen/settings.json` not loaded, `.env` not loaded,
extensions restricted, tool auto-acceptance disabled) — but the same page documents it as **disabled by
default**, and does **not** state what headless mode does with an untrusted folder (upstream's fixed behaviour
is `FatalUntrustedWorkspaceError`; whether Qwen Code backported that is **unverified**).

**Net:** the spec's proposed invocation is `--yolo`, headless, no mandatory sandbox, cwd = a repo checkout, with
folder-trust unset — **the precise configuration the upstream advisory is about.** This is not a reason to
abandon the backend; it is a reason the plan must add pre-flight controls the spec does not currently contain.

### 3.3 🟡 Data egress is real — but the spec must not copy `zai`'s file list, which is wrong here

The dispatcher's question 2 is well-founded: yes, the same concern applies. But the *mechanism differs*, and an
adapter that copy-pastes `zai`'s "CLAUDE.md and `.claude/settings.json`" sentence would be **factually wrong**
and would leave operators checking the wrong files.

Qwen Code inherits Gemini CLI's hierarchical context system: context files are discovered across scopes,
**concatenated, and sent to the model with every prompt**. Qwen Code's defaults are `QWEN.md` / `CONTEXT.md`,
and **`AGENTS.md` was added as a default** ([#2006](https://github.com/QwenLM/qwen-code/issues/2006), closed via
PR #2018, 2026-02-28; `QWEN.md` was renamed toward `AGENTS.md` for community consistency in March 2026).
Context files also support `@path/to/file.md` **imports**, which pull in further files transitively.

**Concretely, for this repository:** `compaund-v` has **`AGENTS.md` at its root** — a full description of the
plugin's architecture, dispatch model, adapter roster, and scripts — and `CLAUDE.md` whose first line is
`@AGENTS.md`. A `qwen` job dispatched against this repo therefore ships **Compound V's own design document to
Alibaba on every single job**, plus any `.qwen/settings.json` and `QWEN.local.md` present. That is the project's
most IP-dense artifact, and nothing in the spec says so.

Note this is a *different* file set from `zai`'s, so the two adapters need **different** egress warnings.

### 3.4 🟡 Quota is counted in **requests**, not tokens — the spec's mental model is inherited from `zai` and is wrong

`adapter-zai.md` reasons in credits-from-a-multiplier-table. Alibaba does not work that way:

> "The Coding Plan's quota consumption is based on the number of model calls, not on token consumption."
> — [Coding Plan FAQ](https://www.alibabacloud.com/help/en/model-studio/coding-plan-faq)

Pro: **6,000 requests / 5 h · 45,000 / week · 90,000 / month** ($50/mo intl, ¥200/mo CN). This inverts the
optimisation: under z.ai, long outputs are expensive; under Bailian, **turn count** is expensive and token
length is free. An agentic worker doing a 60-turn tool loop burns 60 units. The relevant control is therefore
`--max-session-turns`, which Qwen Code **has** and the spec **does not mention**.

Other quota facts the spec omits:
- **A concurrency limit exists, is undocumented in magnitude, and moves**: *"the platform dynamically adjusts
  this limit based on the overall resource load"*; exceeding it yields `concurrency allocated quota exceeded`.
  This is the KB's known anti-pattern — never ship a `max_parallel` as measured.
- **No pay-as-you-go fallback:** 「额度消耗完毕后，继续调用会失败报错，并且不会自动转为按量付费模式计费」 — quota exhaustion is a hard
  wall, not an overage charge. Good for cost safety; makes the `FALLBACK` policy entry load-bearing.
- **Lite is discontinued** (no new purchases 2026-03-20; no renewal/upgrade after 2026-04-13) — Pro is
  effectively the only tier, so tier-conditional guidance is unnecessary.
- **Auto-disable on detected key exposure:** 「若系统检测到您的 API Key 存在公开泄露的情况，可能会自动将其禁用」 — a key that
  leaks into a log or a committed file is revoked automatically. Raises the stakes on §3.2's leak paths and on
  the argv-exposure lesson `zai` already learned the hard way.

### 3.5 🟡 Error surface: DashScope's shape is already visible — the spec need not fail fully closed

The spec says classification is "Not yet built… fails closed to `other` for every payload." Defensible, but
**more is knowable today than the spec assumes**, from six community threads (above threshold for a real signal):

- `{"errorType":"THROTTLING.userQPSLimit","rid":"<uuid>","message":null,"status":429}` —
  [#2191](https://github.com/QwenLM/qwen-code/issues/2191); note **`message` is null**, so any classifier
  keying on message text (as `zai`'s does) matches nothing. Key on `errorType`.
- `concurrency allocated quota exceeded` / `hour allocated quota exceeded` / `week allocated quota exceeded` /
  `month allocated quota exceeded` — Coding Plan FAQ. These map cleanly to `rate_limited` vs `out_of_credits`.
- 429 + free-quota-exhausted, and 401 `invalid access token or token expired` —
  [#1742](https://github.com/QwenLM/qwen-code/issues/1742), [#1855](https://github.com/QwenLM/qwen-code/issues/1855).

**The `zai` precedent makes this urgent, not optional:** `compound-v-classify-failure.py`'s final `else` is
`_CODEX_RULES`, so a `qwen` job without its own branch is classified with **OpenAI's** needles — the exact bug
that told an operator to run `codex login` after a GLM error.

### 3.6 🟢 Smaller items a domain reader would flag

- **Auth-path confusion is a *reported* failure mode, not theoretical.** [#1855](https://github.com/QwenLM/qwen-code/issues/1855)
  (2026-02-17, closed — **isolated report**, one thread): cached OAuth credentials continued to take priority
  over a newly configured Coding Plan key, yielding persistent 401s. Mechanism-corroborates §3.2's core claim
  that Qwen Code's credential resolution has more state than the spec models. Scratch `HOME` should neutralise
  it — **which is a prediction to test in the live probe, not a fact to assume.**
- **`--max-wall-time` exists** and duplicates part of `compound-v-run-with-timeout.py`'s job. Not a conflict, but
  the plan should choose one authority deliberately rather than have two timeouts race.
- **No `--cd` flag** is documented — confirms recon [F10]'s open question in the *pessimistic* direction. The
  subshell-`cd` pattern (cursor/zai) is required. `--include-directories` exists but adds scope rather than
  changing cwd.
- **The `xhigh` house rule is safe here.** No headless effort flag exists at all, so effort must be written into
  a pinned settings.json — meaning it lands in the *project* `.qwen/settings.json` slot, i.e. **inside the
  worktree**, i.e. inside the scope gate's diff. Writing effort config into the worktree would make the worker
  dirty its own diff. The plan must place it in the scratch `HOME` (`$HOME/.qwen/settings.json`) instead — a
  non-obvious interaction between two of the spec's own decisions that neither section notices.
- **SOC 2 + AES-256 + "never use your data for model training"** is a genuinely reassuring first-party statement
  ([privacy notice](https://www.alibabacloud.com/help/en/model-studio/privacy-notice)) and should be cited
  *alongside* the egress warning — the audit's job is calibration, not alarm. What is **absent** from that page:
  any retention period, any storage region, any deletion mechanism.

---

## 4. Common Traps in This Domain

1. **Cloning the previous adapter's compliance conclusion instead of its compliance *method*.** `zai`'s clause
   restricts the client; Alibaba's restricts the mode. The four-clause checklist in the KB exists precisely so
   the *method* is what gets reused. This spec reused the conclusion.
2. **Assuming `env -i` is the whole isolation story.** It is a complete answer for a `$HOME`-rooted tool and a
   partial one for a `cwd`-rooted tool. Every Gemini-CLI-derived agent is cwd-rooted.
3. **Treating a fork's upstream CVEs as someone else's problem.** A fork at v0.8.2 inherits the vulnerability
   history of everything between v0.8.2 and the fix.
4. **Reading "supported tools includes X" as "my usage of X is permitted."**
5. **Carrying a token-based quota model onto a request-based plan** — inverts which knob controls spend.
6. **Message-text error classifiers against an API that returns `message: null`.**
7. **Trusting a benchmark table to pick an advisor** when the stated purpose is *error decorrelation*. The spec
   gets this right and says so explicitly — noted as a strength, not a trap it fell into.

---

## 5. Regulatory / Compliance Notes

**Contractual (Alibaba).** Beyond §3.1: the
[International Product Terms of Service v3.8.0](https://www.alibabacloud.com/help/en/legal/latest/alibaba-cloud-international-website-product-terms-of-service-v-3-8-0)
prohibits reselling/sublicensing the Services and prohibits selling, transferring or sublicensing the account
without prior written consent; the [API Terms of Use](https://www.alibabacloud.com/help/en/legal/latest/api-term-of-use)
grant a *"non-transferable, non-sublicensable, non-exclusive"* licence. Same shape as z.ai's
resell/aggregate/proxy clause. A **single operator dispatching their own jobs with their own key** is inside
these lines; a shared team key, a CI secret, or a hosted deployment is not.

**Data protection.** First-party: no training on customer data, AES-256, SOC 2 (Security/Availability/
Confidentiality). Not stated anywhere I could find: retention period, storage region, deletion path. For an EU
or UK operator, sending source code to a Chinese-headquartered provider is a **third-country transfer** under
GDPR Ch. V whenever the payload contains personal data — and source code, commit metadata, and issue text
routinely do. The international endpoint's Singapore association is *inferred from* general DashScope
documentation, **not** a Coding-Plan-specific residency commitment — treat residency as **unconfirmed**.

**Jurisdiction / IP / export control** (dispatcher question 4 — yes, this is a recognised class):
- Chinese-model adoption in US enterprises became structural during 2026, and the policy response is live: a
  redesigned US framework aimed at **models and access** is expected as an interim final rule around **fall
  2026** ([CSA](https://labs.cloudsecurityalliance.org/research/csa-whitepaper-sovereign-ai-risk-export-controls-enterprise/),
  [NatLawReview](https://natlawreview.com/article/choosing-between-us-and-chinese-ai-models-export-control-risks-both-sides)).
  The concrete risk to a *plugin* is **continuity**, not sanction: a backend that becomes unreachable or
  unlawful for some installers on a policy change.
- China is separately building **outbound** controls on advanced-model distribution — the same risk from the
  other side.
- **The most persuasive signal is Alibaba's own behaviour.** Reuters, 2026-07-03: Alibaba **banned Claude Code
  on internal machines** over alleged backdoor risk, directing staff to its own Qoder
  ([HN 48772443](https://news.ycombinator.com/item?id=48772443), 336 points / 281 comments). A vendor that will
  not route its own proprietary code through a foreign coding agent is making an argument the operator is
  entitled to apply symmetrically. **This belongs in the adapter doc as a neutral fact**, because it frames the
  decision better than any amount of advocacy.

**What this does *not* mean.** None of the above prohibits a private individual from using a paid Alibaba
subscription on their own repositories. The audit's job is to ensure the operator chooses knowingly and that
the **default is off**. Consistent with the KB's standing rule: *if the plugin ships publicly, the ban lands on
the installer.*

---

## 6. Recent Breaking Changes (last 12 months)

| Date | Change | Impact on this spec |
|---|---|---|
| **2026-04-24** | [GHSA-wpqr-6v78-jr5g](https://github.com/advisories/GHSA-wpqr-6v78-jr5g) — Gemini CLI workspace-trust + `--yolo` allowlist-bypass RCE, **CVSS 10.0**, fixed 0.39.1 / 0.40.0-preview.3 | **Highest-impact item in this audit.** Qwen Code forks v0.8.2; backport status unverified |
| **2026-04-15** | Qwen OAuth free tier discontinued ([HN 47789014](https://news.ycombinator.com/item?id=47789014)) | Confirms spec's "no OAuth path" Non-goal — correct |
| **2026-04-13** | Coding Plan **Lite** stops renewals/upgrades (no new purchases from 2026-03-20) | Pro is effectively the only tier |
| **2026-03** | `QWEN.md` → `AGENTS.md` as default context file ([#2006](https://github.com/QwenLM/qwen-code/issues/2006) → PR #2018) | Changes the **egress file list**; this repo has `AGENTS.md` at root |
| **2026-05-27** | qwen-code 0.16.2 — `.qwen/QWEN.local.md` loaded as project-local context | Another worktree-rooted file read on every job |
| **2026-08-03** | Qwen3.8-Max shipped (one day before the spec) | Validates the spec's refusal to hardcode a default model map — **a correct call** |
| **2026-07-03** | Alibaba bans Claude Code internally (Reuters) | Jurisdictional framing for the adapter doc |

---

## 7. Design Constraints for the Plan (non-negotiable)

### Compliance

1. **MUST** add a **Compliance** section to `skills/backend-launcher/adapter-qwen.md` at the same standard as
   `adapter-zai.md`, quoting Alibaba's prohibition **verbatim in both English and Chinese**, with both the
   strict and the 「以 API 调用的形式」 readings stated, and an explicit statement that Compound V **cannot resolve
   the ambiguity** and the operator accepts the account risk.
2. **MUST NOT** reuse `adapter-zai.md`'s "spawning the vendor-approved binary is the compliant path" sentence
   for `qwen`. It is a conclusion about a differently-shaped clause. Reproducing it would be a false assurance.
3. **MUST** state the three operator-side clauses in the adapter doc: subscriber-only, **no account/key
   sharing**, no resale/sublicense/account transfer. **MUST NOT** ship any configuration that puts the key in
   CI, a shared secret store, or a team-wide config.
4. **MUST** mark `qwen` **opt-in and off by default**, with the acknowledgement covering **account-suspension
   risk**, not only sandbox trust — the KB's standing rule for publicly-distributed plugins.
5. **SHOULD** ship the advisor-mode `qwen` path **behind a separate opt-in from the worker path**, or defer it.
   It is the least defensible use under both readings of the clause and is the spec's *newest* capability.
   ⚠️ This is a scope recommendation the plan author may reasonably reject — but it must be a **decision**, not
   an oversight.

### Isolation / security

6. **MUST NOT** describe `env -i` + scratch-`HOME` as equivalent isolation to `zai`'s. It is **strictly weaker**
   because Qwen Code reads `.qwen/.env`, `.env`, and `.qwen/settings.json` from **cwd**.
7. **MUST** pre-flight-refuse (or quarantine) the job when the worktree contains any of `.qwen/.env`, `.env`,
   `.qwen/settings.json`, or `.qwen/QWEN.local.md`. `git worktree add` materialises tracked files only, so on a
   clean repo this check costs nothing and never fires — it exists for the tracked-secret and
   resumed-worktree cases. State that reasoning in the script comment so it is not "optimised away" later.
8. **MUST** set `security.folderTrust.enabled` explicitly (in the **scratch** `~/.qwen/settings.json`) rather
   than relying on the default, which the docs say is **off**.
9. **MUST** add a **model assertion** equivalent to `zai`'s GLM assertion: read the response's model
   identifier and **fail the job** unless it matches the requested model. This is the only defence against a
   silent auth-path switch, and §3.2 path 1 plus [#1855](https://github.com/QwenLM/qwen-code/issues/1855) show
   the switch is reachable. The spec currently has no equivalent.
10. **MUST** verify, during the live probe, whether Qwen Code backported the upstream headless-untrusted-folder
    fix (upstream ≥ 0.39.1 raises `FatalUntrustedWorkspaceError`). Record the observed behaviour and the
    `qwen --version` in the adapter doc. **MUST NOT** ship "verified" while this is unknown.
11. **MUST** keep the credential out of any long-lived process's argv — `env -i` wraps the **supervisor**, per
    the measured `zai` lesson. Aggravated here: Alibaba **auto-disables keys it detects as exposed**.
12. **SHOULD** make `--sandbox` the **default-on** for `qwen` with an opt-out, rather than the spec's
    default-off with an opt-in. `qwen` is the *only* non-Codex backend with a real kernel sandbox available;
    defaulting it off discards the one advantage that justifies its priority-list position above
    zai/opencode/cursor/antigravity in §"advisor-mode." ⚠️ The spec records default-off as an **explicit user
    decision** — flagging the inconsistency for reconsideration, not overriding it.

### Data egress

13. **MUST** document egress with Qwen Code's **actual** file set — `AGENTS.md`, `QWEN.md`, `CONTEXT.md`,
    `.qwen/QWEN.local.md`, transitive `@`-imports, and any worktree `.qwen/settings.json` — **not** `zai`'s
    `CLAUDE.md` list.
14. **MUST** state plainly that dispatching `qwen` **against this repository** sends `AGENTS.md` — Compound V's
    own architecture document — to Alibaba on every job.
15. **SHOULD** cite the first-party mitigations (no training on customer data, AES-256, SOC 2) next to the
    warning, and state that retention period, storage region, and deletion path are **not published**.

### Correctness / operations

16. **MUST** write any pinned `effort` settings.json into the **scratch `HOME`**, never into the worktree —
    a worktree settings file dirties the worker's own diff and trips the scope gate.
17. **MUST** model quota as **requests, not tokens** (Pro: 6,000 / 5 h, 45,000 / week, 90,000 / month) and
    **SHOULD** set a default `--max-session-turns` for exactly that reason.
18. **MUST** set `max_parallel` conservatively (**≤ 2** suggested) and label it **unmeasured**. The concurrency
    limit is real, undocumented in magnitude, and *"dynamically adjust[ed]."* **MUST NOT** ship a fan-out number
    as measured without a real 2/4/6 concurrency run.
19. **MUST** bound retries and open a per-backend circuit breaker early. On a plan whose stated penalty is
    suspension, retry policy is a **compliance** decision, not a reliability one — and enforcement throttling is
    wire-indistinguishable from ordinary rate limiting.
20. **MUST** add the `qwen` branch to `compound-v-classify-failure.py` **in this PR**, not a follow-on —
    the function's final `else` is `_CODEX_RULES`, so its absence is not a neutral gap, it is a **wrong**
    answer. Seed it with the known needles (`THROTTLING.userQPSLimit`, `concurrency allocated quota exceeded`,
    `{hour,week,month} allocated quota exceeded`, 401 `invalid access token`) and key on **`errorType`, not
    `message`** — DashScope returns `message: null`.
21. **MUST** keep the `FALLBACK` entry (spec already has this — correct, and load-bearing given there is no
    pay-as-you-go fallback on quota exhaustion).
22. **MUST** keep the `worktree`-mandatory invariant and the CR5-5 worker-only gate (spec already correct).

---

## 8. Open Questions for the Human

1. **The decision this audit exists to surface.** Alibaba's own docs prohibit using the Coding Plan key for
   *"automated scripts… or any non-interactive batch calling scenarios,"* penalty *"subscription suspension or
   API Key ban."* Compound V is an automated script making non-interactive calls, through an approved tool.
   I cannot resolve the ambiguity, and I found **zero** reports of anyone testing it. **Do you accept the
   account risk on a subscription you are about to buy?** Options: (a) ship as designed with a loud
   acknowledgement; (b) ship worker-only, drop advisor-mode; (c) ask Alibaba support in writing first and quote
   the reply in the adapter doc; (d) drop the backend.
2. **Does anything change if you are not the only user?** Every mitigation above assumes one operator, one key,
   one machine. If this key would ever sit in CI or be shared, the answer to (1) is settled — don't.
3. **Is Compound V's `AGENTS.md` acceptable to send to Alibaba on every job?** It is the plugin's design
   document and it ships on every `qwen` job against this repo. Fine, or should the worker strip context files?
4. **`--sandbox` default-on or default-off?** The spec chose off. Constraint 12 argues for on. Your call, but it
   determines whether `qwen` genuinely deserves its position above zai/opencode/cursor/antigravity.
5. **Jurisdiction:** does any repo you would dispatch `qwen` against carry client code under an NDA or a
   contract with a data-residency or third-country-transfer clause? If yes, this backend needs a per-repo
   allow-list, not a global toggle.
6. **Do you want `glm-5` reachable through two backends at all?** Same model family via `zai` and via `qwen`
   doubles the surface. If z.ai is being dropped, consider dropping `zai` in the same PR rather than leaving a
   second live path to the same weights.

---

## 9. Knowledge Base Updates

| File | Action | Content appended |
|---|---|---|
| `_knowledge-base/llm-subscription-plan-compliance.md` | **updated** | New section *"Updated 2026-08-04 — Alibaba Bailian Coding Plan"*: the **client-axis vs mode-axis** distinction (the generalised form of finding §3.1), verbatim EN+ZH clauses, request-based (not token-based) quota model, dynamic concurrency, no-PAYG-fallback, auto-disable-on-exposure, DashScope error needles, and a **vendor comparison matrix** for the four clause families across z.ai / Alibaba / Anthropic |
| `_knowledge-base/claude-code-headless-harness.md` | **updated** | New section *"Updated 2026-08-04 — cwd-rooted config discovery breaks the `env -i` isolation model"*: the `$HOME`-rooted vs cwd-rooted taxonomy, the Gemini-CLI-fork family and its inherited CVE exposure, GHSA-wpqr-6v78-jr5g, the settings/`.env` precedence tables, and the reusable **pre-flight worktree config-file check** + **response model assertion** patterns |
| `_knowledge-base/ai-tooling-jurisdictional-risk.md` | **created** | New domain file: third-country transfer under GDPR Ch. V for coding agents, US/China bidirectional export-control trajectory (interim final rule expected ~fall 2026), the continuity-not-sanction risk framing for plugins, context-file egress as the concrete leak surface, and the Alibaba-bans-Claude-Code symmetry argument |

---

### Confidence and limits of this audit

- §3.1 (ToS) is **primary-sourced and cross-checked in two languages on two Alibaba domains** — high confidence
  in the *text*, and deliberately **low** confidence in the *enforcement*, which is unmeasured and for which I
  found no community evidence at all.
- §3.2 (isolation) mixes **verified documentation** (discovery orders, precedence, folder-trust default, the
  upstream advisory) with **reasoned attack paths** (variable injection, workspace `mcpServers`) that are
  **not measured**. They are flagged as live-probe items, not exploits I demonstrated.
- Everything in §3.3–3.5 is documentation-verified.
- The audit did **not** review this repo's existing code — that is Phase 1A's job — nor library API signatures,
  which is Phase 1C's.
