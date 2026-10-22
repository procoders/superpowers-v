# Claude Code Advisor Tool — Knowledge Base

Maintained by Compound V Phase 1C validator. Append at the bottom.

---

## Updated 2026-09-11 — advisor tool: settings, CLI flag, pairing rules, billing, disable paths, API block names

Validated for [`docs/superpowers/library-audit/2026-09-11-v3-6-wide-dispatch.md`](../2026-09-11-v3-6-wide-dispatch.md). Sources: `code.claude.com/docs/en/advisor`, `code.claude.com/docs/en/settings-reference`, `code.claude.com/docs/en/cli-reference`, `platform.claude.com/docs/en/agents-and-tools/tool-use/advisor-tool`. All fetched live 2026-09-11 against Claude Code 2.1.263 (docs current through changelog entries up to 2.1.268, i.e. ahead of installed).

**Enable paths (three):** `/advisor <model>` command (interactive picker or direct arg, saves to user settings); `advisorModel` setting in any settings file (Scope: "Any file" per the settings-reference table); `--advisor <model>` CLI flag (single-session, takes precedence over the setting, not listed in `claude --help`).

**Legal values:** `fable`, `opus`, `sonnet` (aliases resolving to Claude Code's built-in default version per family) or a full model ID such as `claude-opus-5`.

**Pairing table (verbatim from `advisor.md` §"Choose an advisor model"):**

| Main model | Accepted advisors | Notes |
|---|---|---|
| Haiku 4.5 | Fable, Opus, Sonnet | Haiku can call the advisor but cannot act as one |
| Sonnet 4.6 | Fable, Opus, Sonnet | |
| Sonnet 5 | Fable, Opus, Sonnet 5 | A Sonnet 4.6 advisor is rejected |
| Opus 4.6 | Fable, Opus, Sonnet 5 | Sonnet 5 and Opus 4.6 ranked equally capable |
| Opus 4.7+ | Fable, Opus 4.7+ | Any Opus 4.7+ accepts another as advisor; Opus 4.6/Sonnet 5 advisor rejected |
| Fable 5.1 or Fable 5 | Fable 5.1, or the same Fable version | An Opus or Sonnet advisor is rejected, and so is a Fable 5 advisor for a Fable 5.1 main |

**→ v3.6-wide-dispatch spec's claim "Fable 5.1 main accepts only Fable 5.1" CONFIRMED** — for a Fable-5.1 main, "same Fable version" resolves to Fable 5.1 only.

**Subagents inherit the configured advisor** and apply the same pairing check against their own model (verbatim: *"Subagents inherit the configured advisor and apply the same pairing check against their own model."*).

**Version floors:**
- Fable 5.1 as advisor requires Claude Code **v2.1.257+**.
- Non-interactive `/advisor` (headless `-p`, Agent SDK, desktop app, Remote Control) requires **v2.1.260+**.

**Disable paths (two):**
1. Feature-flag fetching off (e.g. `DISABLE_TELEMETRY`) — the advisor is gated behind a fetched feature flag, so a session that skips flag fetching never turns it on.
2. `CLAUDE_CODE_DISABLE_ADVISOR_TOOL=1` — disables entirely; `/advisor` becomes unavailable, `advisorModel` is ignored, `--advisor` is accepted but has no effect.

**Billing:** API billing pays the advisor model's own input/output rates. Subscription plans: advisor usage counts toward plan limits, except Fable-as-advisor bills to usage credits on plans where Fable usage does. Consent flow: run `/model fable` and accept to continue on Fable, which both saves Fable as the selected model and unlocks it as an advisor selection. Before consent, `/advisor fable`, the `/advisor` picker, and `--advisor fable` all decline to apply Fable and point at `/model fable` instead (interactive: notification; `--advisor fable` at launch: exits with a message, except in a background session which starts without the advisor).

**Caching:** enabling/disabling the advisor mid-session does not invalidate the main model's prompt cache. The advisor's own read of the transcript is **never cached** — each call reprocesses the full transcript fresh.

**Messages API content blocks (verbatim from the API doc's JSON examples and tables):**
- `server_tool_use` block, `name: "advisor"`, always-empty `input`.
- `advisor_tool_result` block, `tool_use_id` pointing at the `server_tool_use` id, `content` a discriminated union:
  - `advisor_result` — `{text, stop_reason}` — plaintext advisor models (e.g. `claude-opus-4-8`).
  - `advisor_redacted_result` — `{encrypted_content, stop_reason}` — encrypted output; returned by Fable 5.1, Mythos 5.1, Opus 5, Fable 5, Mythos 5 advisors.
  - `advisor_tool_result_error` — `{error_code}` — e.g. `"overloaded"`, `"max_uses_exceeded"` (per-request cap via the tool definition's `max_uses`).
- Tool `type` for the advisor tool definition itself: `"advisor_20260301"`.

**Not verifiable from any doc page:** whether Claude Code's own on-disk session transcripts (`~/.claude/projects/**.jsonl`) carry these exact block names verbatim. The Claude Code doc pages describe the *product feature* (the `/advisor` command, the setting, the flag); the block-name schema lives only in the Messages-API doc, which documents the wire format, not Claude Code's transcript-persistence format. Any claim that the two match is empirical (a live probe on a specific machine/version), not doc-confirmed — treat it as such in any spec that relies on it.

**Never Haiku violation risk:** none — Haiku can only *call* the advisor, never *act as* one, so nothing in this feature routes work onto Haiku.
