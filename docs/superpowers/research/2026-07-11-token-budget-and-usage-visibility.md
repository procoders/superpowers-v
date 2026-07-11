# Compound V — Real Token/Usage Data Research Report

**Date:** 2026-07-11 (research conducted July 2026). Deep-dive research agent (general-purpose,
WebSearch-driven), requested after the user identified this as a real recurring want: most
users are on flat Max/Pro subscriptions (not pay-per-token), but still want to know how many
tokens a task actually consumed, and want help budgeting within Claude's rolling rate-limit
window. Part of the
[2026 orchestrator landscape synthesis](2026-07-11-2026-orchestrator-landscape-synthesis.md).

---

## 1. How the Claude subscription rate-limit window actually works in 2026

**Confirmed from official Anthropic sources:**

- Claude Code enforces **two overlapping windows**: a **5-hour rolling window** and a **7-day (weekly) rolling window**. This is confirmed structurally by the official `statusLine` JSON schema, which exposes both as `rate_limits.five_hour` and `rate_limits.seven_day` — [Customize your status line](https://code.claude.com/docs/en/statusline).
- **May 6, 2026**: Anthropic's own announcement confirms Anthropic "doubl[ed] Claude Code's five-hour rate limits" for Pro, Max, Team, and Enterprise plans, and removed peak-hour limit reductions for Pro/Max — [Higher usage limits for Claude and a compute deal with SpaceX](https://www.anthropic.com/news/higher-limits-spacex) (official Anthropic news post).
- Usage limits are **shared across Claude Code, claude.ai, and other Claude surfaces** on the same subscription — [Use Claude Code with your Pro or Max plan](https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-or-max-plan) (official Anthropic support article).
- The general "how limits work" support article describes usage as a **"conversation budget"** shaped by conversation length/complexity, features used, model, and effort level, but does **not** publish exact prompt-per-window numbers — [How do usage and length limits work?](https://support.claude.com/en/articles/11647753-how-do-usage-and-length-limits-work) (official). Several third-party trackers (not independently verified against a primary Anthropic page) report Anthropic stopped publishing fixed prompts-per-window figures in 2026, and that Max plans track two separate weekly caps (all-models vs. Sonnet-only) — treat these specifics as lower-confidence, aggregator-sourced.
- Pricing tiers (well-established, multiple sources): Pro $20/mo, Max 5x $100/mo, Max 20x $200/mo.
- **Important distinction**: the per-minute, token-bucket API rate limits documented at [platform.claude.com/docs/en/api/rate-limits](https://platform.claude.com/docs/en/api/rate-limits) (with `anthropic-ratelimit-*` response headers and `retry-after`) govern **organization/API-key billing** (RPM/ITPM/OTPM per model, per usage tier). This is a **separate system** from the Pro/Max subscription's 5-hour/7-day window. Claude Code running under a user's own subscription does not go through that API-key rate-limit machinery in the same way, so those headers are **not** the right signal for subscription-tier budgeting (see §4c).
- A **real, structured, local signal for the 5-hour/7-day window already exists and is officially documented**: the `statusLine` hook JSON's `rate_limits.five_hour.{used_percentage, resets_at}` and `rate_limits.seven_day.{used_percentage, resets_at}` (`resets_at` is Unix epoch seconds). This field is populated "only for Claude.ai subscribers (Pro/Max) after the first API response in the session." **This is the single most useful fact from this whole research pass** — see §4c.

## 2. Does Claude Code expose real token-usage data anywhere a plugin/hook could read it?

**(a) JSONL transcripts (`~/.claude/projects/<encoded-path>/<session-id>.jsonl`)**

Confirmed real fields: each assistant message carries `message.usage` with `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens` — these are genuine logged API-response usage fields, not a client-side tokenizer estimate.

**Critical caveat, confirmed and important**: [GitHub issue anthropics/claude-code#27361](https://github.com/anthropics/claude-code/issues/27361), **closed "not planned"** — the final streaming `message_stop` event is never written to the JSONL, so `stop_reason` is always `null` and, per the reporter's 128-call sample, **`output_tokens` is undercounted by roughly 2x** (23,725 logged vs. 45,050 measured by re-tokenizing the actual content). Anthropic has declined to fix this. This means: **JSONL-derived output-token counts are known-inaccurate**, not just "unverified" — using them as a real number would print a wrong number with false confidence, which is arguably worse than an honest N/A.

**(b) ccusage and similar community tools**

- **ccusage** ([ccusage.com](https://ccusage.com/), [github.com/ryoppippi/ccusage](https://github.com/ryoppippi/ccusage)) and forks/derivatives (`claude-code-usage-analyzer`, `ccusage0`, `phuryn/claude-usage`, `tokenking`) all read the **local JSONL logs directly** and extract the logged `message.usage.*` fields — they do **not** run their own tokenizer as the primary method. This means they inherit the #27361 output-token undercount unless they've separately adopted the tiktoken-recount workaround the issue thread suggests (could not confirm any of these tools have done so).
- `phuryn/claude-usage`'s README explicitly states: *"Claude Code writes detailed usage logs locally... regardless of your plan,"* and separately: *"If you use Claude Code via a Max or Pro subscription, your actual cost structure is different (subscription-based, not per-token)"* — i.e., the tool's own dollar figures are explicitly framed as list-price-equivalent estimates, not real spend, for subscription users. It restricts cost calculation to models whose name matches a known family (`fable`/`mythos`/`opus`/`sonnet`/`haiku`), excluding unrecognized models rather than guessing at pricing.
- **Claude-Code-Usage-Monitor** ([Maciek-roboblog](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor)) explicitly does **"predictions and warnings"** — i.e., it extrapolates/forecasts future usage from a burn rate. That is exactly the class of number Compound V's anti-fabrication charter should refuse to originate.

**(c) Task tool / hook surfacing**

- The **common hook input fields** (all events) are `session_id`, `prompt_id`, `transcript_path`, `cwd`, `permission_mode`, `effort`, `hook_event_name`, plus `agent_id`/`agent_type` inside a subagent — confirmed via [code.claude.com/docs/en/hooks](https://code.claude.com/docs/en/hooks). **No token or cost field is in the common schema**, and PostToolUse/SubagentStop were not confirmed to carry usage numbers either — a plain hook alone does not hand you a subagent's token count.
- **The actual answer, and the strongest finding of this research**: a distinct, newer, officially-documented feature called **`subagentStatusLine`** (requires Claude Code ≥ v2.1.205) *does* expose real live per-subagent data. Per [the statusline doc](https://code.claude.com/docs/en/statusline#subagent-status-lines), the script receives a `tasks` array where each task carries `id`, `name`, `type`, `status`, `description`, `label`, `startTime`, `model`, `contextWindowSize`, `tokenCount`, `tokenSamples`, `cwd` — a **real, live token count per running/finished subagent, keyed by task id**. This is a rendering hook (it drives the agent panel UI), but nothing stops a script assigned to it from also persisting what it receives.
- **OpenTelemetry** (opt-in, `CLAUDE_CODE_ENABLE_TELEMETRY=1`): the `claude_code.token.usage` and `claude_code.cost.usage` metrics carry `query_source` (`main`/`subagent`/`auxiliary`) and `agent.name` (subagent type, verbatim for built-in/plugin agents) — real, per-request, ground-truth data. For **per-instance** attribution (distinguishing two concurrently-running subagents of the same type, which is exactly Compound V's parallel-dispatch pattern), a beta flag `CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1` + `OTEL_TRACES_EXPORTER=otlp` emits `claude_code.llm_request` spans carrying `input_tokens`/`output_tokens`/`cache_read_tokens`/`cache_creation_tokens` **and** `agent_id`/`parent_agent_id` — genuinely real, per-subagent-instance token data — [Observability with OpenTelemetry](https://code.claude.com/docs/en/agent-sdk/observability), [monitoring-usage](https://code.claude.com/docs/en/monitoring-usage). This requires standing up an OTLP collector — real infrastructure, not zero-config.

**(d) Official usage CLI/API for subscription billing**

- Inside Claude Code, `/usage` (per a truncated but real doc snippet: *"/usage breakdown shows what's driving your li[mit]"* — [Slash commands](https://code.claude.com/docs/en/slash-commands)) shows current-period usage; some older material calls this `/status`, and `/cost` is reported by third parties to now alias `/usage`. The exact current command name/output shape was not fully pinned from primary docs in this pass — treat as needing a quick live check before building against it.
- **No public Admin API or historical-usage-export endpoint for Pro/Max subscription billing** was found. The Claude Console's Usage/Cost pages and Rate Limits API (`platform.claude.com/docs/en/manage-claude/rate-limits-api`) are for **API-key/organization billing**, a different product surface. For a subscription user, the **only** machine-readable usage sources are: local JSONL logs (with the known bug above), the live `statusLine`/`subagentStatusLine` snapshots, and opt-in OTel.

## 3. What people are actually asking for (2026)

- The existence of a whole ecosystem of local usage tools (ccusage, claude-usage, claude-code-usage-analyzer, ccusage0, tokenking, Claude-Code-Usage-Monitor, claude_telemetry) confirms real demand for token-usage visibility **even under flat subscription billing** — corroborating the premise directly.
- Community guidance converges on: parallel/background subagent sessions consume the same 5-hour quota as interactive ones, **roughly linearly with concurrency** — "running ten agents in parallel uses quota roughly ten times as fast as running one," and advice to "budget by dispatch count, not by clock time" on Max plans (2026 aggregator guidance — not primary Anthropic sources, treat as directional).
- A concrete real GitHub feature ask exists for controlling fan-out: [anthropics/claude-code#15487](https://github.com/anthropics/claude-code/issues/15487) "Add `maxParallelAgents` Configuration Setting."
- Notably, per a 2026 Claude Code changelog claim (via [gradually.ai's changelog tracker](https://www.gradually.ai/en/changelogs/claude-code/), not Anthropic's own changelog directly — lower confidence), Anthropic itself shipped a July 2026 fix for **"rate-limit telemetry being over-counted when multiple parallel requests were in flight at the moment a usage limit was hit."** This is a signal that Anthropic is aware concurrent/parallel dispatch (Compound V's exact pattern) stresses rate-limit accounting.
- Verbatim primary Reddit/HN threads could not be pulled in this pass (search results kept resolving to blog/aggregator pages rather than actual forum posts) — the demand signal here rests on the tool ecosystem and GitHub issues above, not on quoted community complaints. Flagging this gap honestly rather than fabricating quotes.

## 4. Recommended design for Compound V

**Grounding in the current codebase** (`schemas/job_result.schema.json`, `examples/job_result.example.json`, `skills/backend-launcher/adapter-cursor.md`, `scripts/compound-v-run-codex-worker.sh`): job_result currently carries **zero** token/cost fields for *any* backend. Notably, `adapter-cursor.md` already documents a precedent: *"The `.usage` token counts are deliberately IGNORED — anti-ruflo: the worker never emits token/cost metrics"* — even though cursor-agent self-reports a `.usage` field, Compound V chose not to surface it because its provenance/accuracy wasn't verified as ground truth. The design below extends that same discipline: **surface a number only when its source is structurally real and its accuracy is documented; otherwise print an explicit, labeled N/A.**

**(a) Real per-job token counts for Claude subagent jobs**

- **Tier 1 (recommended default, zero extra infra)**: ship an optional `subagentStatusLine` script that, on each invocation, appends the raw `tasks[].{id, tokenCount, contextWindowSize, model, status}` it receives to a per-run file (e.g. `docs/superpowers/execution/<run-id>/.subagent-usage.jsonl`). After a job's `SubagentStop`, the dispatcher reads the last known `tokenCount` for that task id and writes it into `job_result` as `token_usage: {total_tokens: N, source: "claude_code_subagentStatusLine", as_of: "<ts>"}`. This is a **real** number, sourced and labeled — but note it's a combined context-window figure, not an input/output split, and requires Claude Code ≥ v2.1.205 plus the statusLine hook actually firing (verify this works headlessly / under `Task`-only dispatch before relying on it, since `subagentStatusLine` is documented as an interactive-UI feature).
- **Tier 2 (opt-in, advanced, more precise)**: document `CLAUDE_CODE_ENABLE_TELEMETRY=1` + `CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1` + `OTEL_TRACES_EXPORTER=otlp` against a small local OTLP collector, giving real per-`agent_id` input/output/cache token breakdown via `claude_code.llm_request` spans. This mirrors V-memory's existing pattern (default lane simple/local, DENSE lane opt-in with real infra) — do **not** make it the default, since it requires standing up a collector, which cuts against the "no daemon" posture, but it's legitimate as a documented advanced mode.
- **Do not** parse JSONL `output_tokens` as ground truth given the confirmed, Anthropic-acknowledged (issue closed not-planned) ~2x undercount bug. If ever surfaced, it must carry an explicit "approximate, known undercount, see anthropics/claude-code#27361" label — never presented as exact.
- **Do not** build a "predicted tokens per task" extrapolation the way some community monitors do — that is fabrication under the charter, full stop.

**(b) Where real numbers are not accessible — say so explicitly**

For Claude subagent jobs where neither Tier 1 nor Tier 2 capture is active, `job_result` should carry an explicit, honest marker — e.g. `"token_usage": null` with `"token_usage_note": "not captured — subscription billing has no historical usage API; enable subagentStatusLine capture or OTel enhanced telemetry for real per-job counts"` — rather than silently omitting the field or guessing. This is consistent with the project's existing anti-ruflo discipline.

For **Codex jobs**, real capture is straightforward and should be added: `codex exec --json`'s `turn.completed` event carries a genuine, server-computed `usage` object — `{input_tokens, cached_input_tokens, output_tokens, reasoning_output_tokens}` (OpenAI API-billed, ground truth). This can be parsed the exact same safe, structural way `thread_id` is already parsed today (`jq 'select(.type=="turn.completed")'`, never regex/substring matching), summed across turns, and written into `job_result` as a genuinely real, sourced number. This is the one place in this research where "yes, capture it, it's real" is an unambiguous answer.

For **Cursor**, the existing "ignored" stance may be overcautious if `.usage` is genuinely server-reported by cursor-agent from real API responses — but this provenance was not verified in this pass, so no change is recommended now, only flagged as worth a future, narrowly-scoped investigation. For **Antigravity**, no usage-reporting surface was found; leave as N/A, consistent with its already-lower-trust status.

**(c) 5-hour window budgeting — a real signal already exists; use it instead of estimating**

This is the cleanest win in the whole report. `statusLine`'s `rate_limits.five_hour.{used_percentage, resets_at}` and `rate_limits.seven_day.{...}` are **real, Anthropic-computed, officially documented, already-shipped** numbers — no estimation needed. Concrete design: have the orchestrating Compound V session (which *is* a Claude Code session) write this block to a small state file each time its statusLine refreshes (e.g. `~/.claude/compound-v-ratelimits.json`), and have `/v:dispatch`/the parallel-dispatcher read the most recent snapshot **before** launching a batch, surfacing it plainly: *"You're at 63% of your 5-hour window, resets at 14:20. N jobs queued."* This is a real fact, not a projection. Do **not** attempt to forward-project "how many more tasks fit" from a per-task token estimate — that crosses into fabrication. The one honest forward-looking statement available is a **real observed delta** between two real snapshots ("this run's first 4 jobs moved the window from 12% to 41%"), which is measured fact, not prediction, and is safe to print.

Finally, the API's `anthropic-ratelimit-*` 429 headers are the wrong mechanism for this use case — they govern a different (API-key/org, per-minute token-bucket) system, not the Pro/Max subscription window that Compound V's Claude Task-tool jobs actually run under.

---

### Key sources
- [Higher usage limits for Claude and a compute deal with SpaceX](https://www.anthropic.com/news/higher-limits-spacex) (official Anthropic)
- [Use Claude Code with your Pro or Max plan](https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-or-max-plan) (official)
- [How do usage and length limits work?](https://support.claude.com/en/articles/11647753-how-do-usage-and-length-limits-work) (official)
- [Rate limits — Claude Platform Docs](https://platform.claude.com/docs/en/api/rate-limits) (official, API-key billing)
- [Customize your status line](https://code.claude.com/docs/en/statusline) (official — source of `rate_limits.*` and `subagentStatusLine.tasks[].tokenCount`)
- [Monitoring — Claude Code Docs](https://code.claude.com/docs/en/monitoring-usage) (official OTel metrics/events)
- [Observability with OpenTelemetry — Agent SDK](https://code.claude.com/docs/en/agent-sdk/observability) (official, `claude_code.llm_request` span)
- [Hooks — Claude Code Docs](https://code.claude.com/docs/en/hooks) (official)
- [anthropics/claude-code#27361](https://github.com/anthropics/claude-code/issues/27361) — JSONL output-token undercount, closed not-planned
- [ccusage.com](https://ccusage.com/) / [github.com/ryoppippi/ccusage](https://github.com/ryoppippi/ccusage)
- [github.com/phuryn/claude-usage](https://github.com/phuryn/claude-usage)
- [github.com/Maciek-roboblog/Claude-Code-Usage-Monitor](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor)
- [anthropics/claude-code#15487](https://github.com/anthropics/claude-code/issues/15487)
- Codex `turn.completed.usage` structure: cross-referenced via community docs (simplified.guide, docs.onlinetool.cc/codex/docs/exec.html) — **verify directly against the locally-installed `codex-cli` version's own `--json` output before wiring**, per this project's own docs-before-code rule.

### Local files this recommendation is grounded in
- `schemas/job_result.schema.json` — current schema, no token/cost fields
- `examples/job_result.example.json`
- `skills/backend-launcher/adapter-cursor.md:68` — existing "ignore self-reported `.usage`" precedent
- `skills/backend-launcher/adapter-codex.md:151` — existing safe structural-parse pattern for `thread.started` (model for how to add `turn.completed.usage`)
- `scripts/compound-v-run-codex-worker.sh` — where a `turn.completed` usage-sum would be added
