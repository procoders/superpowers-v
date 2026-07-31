# Z.AI / GLM API — Library Knowledge Base

Maintained by Compound V Phase 1C validator. Append at the bottom.

---

## Updated 2026-07-31 — zai backend (PR 1 of 3)

All claims verified against first-party docs on 2026-07-31. Primary machine-readable sources:
<https://docs.z.ai/llms.txt> (91-entry doc index) and <https://docs.z.ai/openapi.json> (14 paths).
Chinese sibling platform `docs.bigmodel.cn` used as corroboration where z.ai has no equivalent page.

> Probing note: unauthenticated live probes of `api.z.ai` are **useless for route discovery** — the auth
> gate fires before routing, so `/api/paas/v4/<anything>` returns the same `401 {"code":"1001"}`.
> A 401 is not evidence that a route exists.

### Endpoints (2026-07-31)

| Layer | GLM Coding Plan (subscription) | Pay-as-you-go |
|---|---|---|
| Anthropic Messages | `https://api.z.ai/api/anthropic` | not documented by z.ai |
| OpenAI Chat Completions | `https://api.z.ai/api/coding/paas/v4` | `https://api.z.ai/api/paas/v4` |

The `coding/` infix is the entire difference on the OpenAI layer.
> "Incorrect endpoint configuration will result in inability to use GLM Coding Plan subscription quota."
> — <https://docs.z.ai/devpack/tool/others>

⚠️ **z.ai publishes no Anthropic-compatibility page outside the Coding Plan section.** `openapi.json`
contains "anthropic" zero times; `guides/develop/claude/introduction` 404s. The claim that the Anthropic
URL is the *same* for subscription and pay-as-you-go is **UNVERIFIABLE on z.ai** — it is only supported by
the parallel structure on `open.bigmodel.cn`, where both use `https://open.bigmodel.cn/api/anthropic`.

### Auth: `ANTHROPIC_AUTH_TOKEN`, not `ANTHROPIC_API_KEY` (2026-07-31)

z.ai documents **only** the Bearer path for Claude Code (<https://docs.z.ai/devpack/tool/claude>):

```json
"env": {
    "ANTHROPIC_AUTH_TOKEN": "your_zai_api_key",
    "ANTHROPIC_BASE_URL": "https://api.z.ai/api/anthropic",
    "API_TIMEOUT_MS": "3000000"
}
```

`x-api-key` is **never mentioned**. Since `ANTHROPIC_API_KEY` sends `x-api-key` and *no* `Authorization`
header, configuring z.ai via `ANTHROPIC_API_KEY` is off the documented path. See
`claude-code-cli-flags.md` for the measured header mapping.

Model config on the Anthropic layer is documented via the tier trio, not `ANTHROPIC_MODEL`:
`ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU}_MODEL`. (`ANTHROPIC_MODEL` was measured to work — it lands as
`"model"` in the request body — but z.ai doesn't document it.)

### Officially supported tools (2026-07-31) — ToS-relevant

> "The GLM Coding Plan is limited to use within the following officially supported tools and product
> environments; users may not use their subscription benefits for tools or scenarios outside of this scope."
> — <https://docs.z.ai/devpack/tool/others> (authoritative list; other pages are stale subsets)

**Coding agents (15):** Claude Code, Claude for IDE, ZCode, OpenCode, Pi, Cursor, Cline, TRAE, Qoder,
Droid, Kilo Code, Roo Code, Crush, Goose, Eigent.
**General-purpose (3, best-effort, may be rate-limited):** OpenClaw, Hermes Agent, SillyTavern.

Driving Claude Code against z.ai is therefore a **compliant** path.

### The Coding Plan is THREE models (2026-07-31)

> "Only the following three models can be called: **GLM-5.2, GLM-5-Turbo and GLM-4.7**."
> — <https://docs.z.ai/devpack/faq>

This is the key trap: the pricing catalogue lists ~20 models, but that is the **pay-as-you-go** surface.
`glm-5.1`, `glm-5`, `glm-4.6`, `glm-4.6v`, `glm-4.5-air` are current, non-deprecated **pay-as-you-go**
models — they are *not* Coding Plan models. That is also why no credit multiplier is published for them:
they bill in dollars, not credits. Using them on a plan key is undocumented territory.

⚠️ z.ai contradicts itself: <https://docs.z.ai/devpack/latest-model> (a Coding Plan page) recommends
`"ANTHROPIC_DEFAULT_HAIKU_MODEL": "glm-4.5-air"`, which the FAQ says cannot be called. Do not build on it.

### Credits (2026-07-31) — all figures exact, source <https://docs.z.ai/devpack/overview>

> "Model credit usage = (Input tokens × Input multiplier + Cached Input tokens × Cached Input multiplier
> + Output tokens × Output multiplier) / 10,000"

Second formula usually omitted: **MCP tool credit usage = calls × output multiplier**.

| Model | Input | Cached input | Output |
|---|---|---|---|
| GLM-5.2 | 6.9 | 1.7 | 24 |
| GLM-5-Turbo | 5.7 | 1.5 | 21 |
| GLM-4.7 | 4.6 | 1.2 | 16 |
| GLM-4.6V (Vision MCP) | 1.2 | 0.3 | 2.7 |

Published multipliers exist for those 4 models plus 3 MCP servers (Web Search, Web Reader, Zread — output
multiplier 1.2 each). Nothing else.

| Plan | 5-hour credits | Weekly credits |
|---|---|---|
| Lite | 2,000 | 10,000 |
| Pro | 12,000 | 60,000 |
| Max | 28,000 | 140,000 |

> "During off-peak hours, model usage is charged at 50% of the standard credit rate."
> "Peak hours: Monday to Friday, 14:00–18:00 Singapore Standard Time (UTC+8)."

Plus, from the revision notice: **"usage on weekends will be deducted at off-peak rates all day."**

⚠️ **Plan revision 2026-07-30** (<https://docs.z.ai/devpack/notice/usage-revision>):
> "The new credits-based plan is now available. Previous plans are no longer sold to new users."
> "Users on plans discontinued on July 30 can still renew or upgrade them."

The table above may describe the legacy plan. Re-check before quoting quotas to a new subscriber.

### Prompt caching is IMPLICIT — no `cache_control` (2026-07-31)

<https://docs.z.ai/guides/capabilities/cache>:
> "**Automatic Cache Recognition**: Implicit caching that intelligently identifies repeated context content
> without manual configuration"
> "Caching is automatically triggered based on content similarity, no manual configuration required"
> "Detailed display of cached token counts in response field `usage.prompt_tokens_details.cached_tokens`"

- `cache_control` appears **zero times** in z.ai docs and in `openapi.json`. No `ephemeral`, no breakpoints.
- **No numeric TTL** — only "Cache has reasonable time limits, will recalculate after expiration".
- Reported field is **OpenAI-shaped** (`prompt_tokens_details.cached_tokens`). The Anthropic-shaped
  `cache_read_input_tokens` / `cache_creation_input_tokens` appear nowhere in the docs.
- ⚠️ **Every caching example is on the OpenAI endpoint.** Behaviour on the *Anthropic-compatible* endpoint
  is undocumented in either direction — though Anthropic-shaped cache fields have been *observed* non-zero
  there, so some translation exists. Observed, not contracted.

Practical rule: against z.ai you **cannot place cache breakpoints**. Prompt *stability* is the only lever.

### No Responses API (2026-07-31) — confirmed from five independent angles

1. `openapi.json` — complete path list, no `/responses`:
   `/paas/v4/chat/completions`, `/paas/v4/async-result/{id}`, `/paas/v4/async/images/generations`,
   `/paas/v4/audio/transcriptions`, `/paas/v4/files`, `/paas/v4/images/generations`,
   `/paas/v4/layout_parsing`, `/paas/v4/reader`, `/paas/v4/tokenizer`, `/paas/v4/videos/generations`,
   `/paas/v4/web_search`, `/v1/agents`, `/v1/agents/async-result`, `/v1/agents/conversation`.
2. `llms.txt` (91 entries) — only "Chat Completion" as an LLM endpoint.
3. `docs.bigmodel.cn/llms.txt` (202 entries) — no `/responses` either.
4. Release notes back to 2025-07 — no Responses API launch.
5. <https://github.com/zai-org/GLM-5/issues/39> (opened 2026-03-30) — an **open** request asking z.ai to
   *add* an OpenAI-compatible `/responses` endpoint for Codex compatibility. Assigned, no commitment.

**Consequence:** `codex-cli` ≥ 0.144.4 speaks only Responses (`wire_api = "chat"` removed — see
`codex-cli` notes below) and therefore **cannot** reach z.ai directly. Published integrations all route
through a LiteLLM-style Responses↔Chat-Completions proxy.

### Context and output limits (2026-07-31)

| Model | Context | Max output |
|---|---|---|
| GLM-5.2 | **1M** (opt-in) | 128K (=131072) |
| GLM-5-Turbo | 200K | 128K |
| GLM-4.7 | 200K | 128K |

⚠️ 1M is **not** the default — it requires a model-name suffix
(<https://docs.z.ai/devpack/latest-model>):
> "To enable GLM 1M context, add the `[1m]` suffix to the model name (e.g., `glm-5.2[1m]`) and configure
> the compression window size parameter `"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "1000000"`."

Do not generalise "1M / 131072" across a tier map — it holds for `glm-5.2` only, and only with the suffix.

### Model deprecations (2026-07-31): NONE

Exhaustive negative. Grepped every z.ai page and the bigmodel index for
deprecat / retire / EOL / sunset / discontinu / "no longer available" / "will be removed" / 下线 / 弃用 /
停止 / 退役 — **zero hits against any model**. Release notes are additions-only back to 2025-07. The only
"discontinued" hits concern **subscription plans** (2026-07-30), not models.

### Anthropic model aliases are NOT documented (2026-07-31)

No z.ai or bigmodel page contains any `claude-<version>` model identifier. The documented pattern is the
inverse — you override Claude Code's tier env vars with **GLM** codes:
> "调用时使用智谱模型编码即可" ("when calling, just use the Zhipu model code")
> — <https://docs.bigmodel.cn/cn/guide/develop/claude/introduction>

An alias like `claude-opus-4-8` being accepted is **observed-only, undocumented, and may change without
notice**. Resolve bare GLM names.

### Related: codex-cli removed Chat Completions (2026-07-31)

Verified live against the installed `codex-cli 0.144.4`. Config load fails **before any network call**:

```
Error loading config.toml: `wire_api = "chat"` is no longer supported.
How to fix: set `wire_api = "responses"` in your provider config.
More info: https://github.com/openai/codex/discussions/7782
```

Remaining `wire_api` variants in the binary: `responses`, `responses_websocket`. Deprecated Dec 2025,
removed via PR #10157, early Feb 2026. Stated rationale: Chat Completions "originated in the GPT-3.5 era
and was not designed for today's agentic coding and reasoning use cases".
