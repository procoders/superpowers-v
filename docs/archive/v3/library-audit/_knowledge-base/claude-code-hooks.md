# Claude Code Hooks Knowledge Base

Maintained by Compound V Phase 1C validator. Append at the bottom.

---

## Updated 2026-07-26 — v2.18 "Arm the autonomy" (`Stop` / `SubagentStop` contract)

Sources: live docs `https://code.claude.com/docs/en/hooks` (fetched 2026-07-26; the old
`https://docs.claude.com/en/docs/claude-code/hooks` now 301s here); byte-scan of the
installed runtime `/Users/oleg/.local/share/claude/versions/2.1.216`; working example
`~/.claude/plugins/cache/claude-plugins-official/ralph-loop/1.0.0/`.

### Events (2026-07-26, runtime 2.1.216)

Shipped event enum (binary @238483006) — 30 events. Relevant: `Stop`, **`StopFailure`**,
`SubagentStart`, `SubagentStop`. Both `Stop` and `SubagentStop` are documented and
supported. The premise in Compound V's `hooks/hooks.json` `$comment` that `SubagentStop`
is "not documented" was already known-wrong; re-confirmed here against the shipped enum.

### `Stop` stdin payload (zod, binary @238483006 / @238488973)

Base (`LA`), all events: `session_id` **required**, `transcript_path` **required**,
`cwd` **required**, `prompt_id?`, `permission_mode?`, `agent_id?`, `agent_type?`.

`Stop` adds: `hook_event_name:"Stop"`, `stop_hook_active` **required boolean**,
`last_assistant_message?` (needs ≥ 2.1.197), `background_tasks?`, `session_crons?`.

`SubagentStop` adds: `stop_hook_active`, `agent_id`, `agent_transcript_path`,
`agent_type`, `last_assistant_message?`, `background_tasks?`, `session_crons?`.

`session_id` is therefore safe to rely on for session isolation on `Stop`.

### Blocking

- `{"decision":"block","reason":"..."}` on stdout, exit 0 — prevents the turn ending and
  feeds `reason` back as a message.
- exit 2 also blocks; stderr becomes
  `Stop hook blocking error from command "<name>": <stderr>` (@230340978).
- `hookSpecificOutput.additionalContext` on `Stop`/`SubagentStop` is **non-blocking**
  (@228265067 — additionalContexts never enter `blockingErrors`).
- `permissionDecision` / `permissionDecisionReason` are **PreToolUse-only**, invalid on `Stop`.
- Universal: `continue`, `stopReason`, `suppressOutput`, `systemMessage`, `terminalSequence`.
  `continue:false` → `preventContinuation` → `{reason:"stop_hook_prevented"}`.

### Consecutive-block cap — **undocumented publicly, real in the binary** (@228318760)

```js
let Us = ble(process.env.CLAUDE_CODE_STOP_HOOK_BLOCK_CAP, 8);
if (Us > 0 && Wi > Us) return ..., yield Rl(
  `A hook blocked the turn from ending ${Wi} consecutive times — overriding and ending turn. `
  + "For Stop/SubagentStop hooks, check stop_hook_active in the input and return success while it's true. "
  + "Set CLAUDE_CODE_STOP_HOOK_BLOCK_CAP to raise this limit.", "warning"),
  {reason:"completed"};
```

- Default **8**. `stopHookBlockingCount` starts at 0, guard is `count+1 > cap`, so
  **8 blocks honored, 9th overridden**; turn ends normally with a `warning`.
- `Us > 0` guard: **`CLAUDE_CODE_STOP_HOOK_BLOCK_CAP=0` disables the cap entirely.**
  Not an invariant — an overridable default.
- `maxTurns` is checked *before* the cap. Under `claude -p --max-turns N`, ceiling is
  `min(N, cap)`.
- The public docs page contains no cap and no env var. Local runtime is authoritative.

### `stop_hook_active` propagation — **the trap** (@230333922, @228278819, @228318760)

The producer passes the query-loop's `stopHookActive` straight through:
`{... hook_event_name:"Stop", stop_hook_active: n, ...}`.

Initialized once per query entry (`stopHookActive: e.stopHookActive ?? !1`). The block
branch sets `stopHookActive: !0`. **Every other continue-branch propagates it unchanged**
(compact retry, malformed-tool-use retry, thinking-only retry, next_turn). It is never
cleared within a turn.

⇒ **After the first block, `stop_hook_active` is `true` for the rest of that user turn.**
A hook that returns success unconditionally when it is true can block **exactly once per
turn**, and the cap of 8 becomes unreachable.

The runtime's "check `stop_hook_active` and return success while it's true" text is
printed **only in the cap-exceeded warning** — advice for hooks with no bound of their
own, not a contract requirement.

**`ralph-loop` 1.0.0 does NOT read `stop_hook_active` at all.** It reads only
`session_id` (line 32) and `transcript_path` (line 68), and bounds itself with its own
`max_iterations` frontmatter counter (line 61). That is why it can loop. Do not cite it
as precedent for honoring `stop_hook_active`.

### Blocks are DISCARDED on some end-turn paths — undocumented (@228258074, fn `CRs`)

```js
if (y.blockingError || y.preventContinuation)
  C(`[end-turn] Stop hook block discarded (turn ended by ${
      d==="tool" ? "tool result" : d==="mcp_meta" ? "MCP end-turn" : "loop tick"
    }, no model re-invoke): ...`)
```

Turn ended by tool result / MCP end-turn / loop tick ⇒ the hook fires, the block is
dropped, no model re-invoke. Same for `PostToolBatch` (@104857344). **A `Stop` hook is
not a hard gate on every turn-ending path.**

### Registration

No `matcher` for `Stop`. Docs: *"…don't support matchers and always fire on every
occurrence. If you add a `matcher` field to these events, it is silently ignored."*
Working shape (`ralph-loop/hooks/hooks.json`):

```json
{ "hooks": { "Stop": [ { "hooks": [
  { "type": "command", "command": "bash \"${CLAUDE_PLUGIN_ROOT}/hooks/stop-hook.sh\"" }
] } ] } }
```

---

## Updated 2026-07-26 — adjacent runtime facts (same audit)

**Usage-limit reset signals.**
- Claude 2.1.216 exposes them three ways: headers
  `anthropic-ratelimit-unified-{status,reset,overage-reset,<claim>-utilization}`
  (@86452586, @224095850); `GET /api/oauth/usage` → `{percent, utilization, resets_at}`
  (@224086525); and a stream-json message
  `{"type":"rate_limit_event","rate_limit_info":{status,resetsAt,rateLimitType,utilization,
  overageStatus,overageResetsAt},...}` (@238755226). `resetsAt` is unix epoch seconds.
  Code-verified, **not** observed on a live 429.
- **codex-cli 0.144.1 `exec --json` does not expose any reset time.** Live probe
  (`codex exec --sandbox read-only --json --ephemeral "Reply with exactly: OK"`) emitted
  `thread.started`, `turn.started`, `item.completed`×3, `turn.completed`; `turn.completed`
  carries `usage{input_tokens,cached_input_tokens,output_tokens,reasoning_output_tokens}`
  only. `RateLimitWindow{used_percent,window_minutes,resets_at}`,
  `RateLimitWindowSnapshot{limit_window_seconds,reset_after_seconds,remaining}` and
  `UsageErrorBody{plan_type,resets_at}` exist in the binary but belong to the **app-server**
  protocol (`app-server/src/request_processors/account_processor/rate_limit_resets.rs`),
  not `exec`. Exec's limit text is prose: `"You've hit your usage limit for {}. …"`.

**macOS tool availability (this machine, darwin 25.5.0).**
`setsid` **NOT FOUND**. `timeout` **NOT FOUND**. `gtimeout` **NOT FOUND**.
`nohup` = `/usr/bin/nohup`. `jq` 1.7.1, `python3` 3.9.6, `codex-cli` 0.144.1,
`claude` 2.1.216. Any detach/timeout mechanism must be Python-side
(`os.setsid()`, `killpg`) or `nohup`, never the `setsid(1)` / GNU `timeout` binaries.
`scripts/compound-v-run-with-timeout.py` already sets this precedent for timeouts.

**`codex exec` flags verified live on 0.144.1** (`codex exec --help`):
`-c/--config`, `--enable/--disable`, `--strict-config`, `-i/--image`, `-m/--model`,
`--oss`, `--local-provider`, `-p/--profile`, `-s/--sandbox {read-only,workspace-write,
danger-full-access}`, `--dangerously-bypass-approvals-and-sandbox`,
`--dangerously-bypass-hook-trust`, `-C/--cd`, `--add-dir`, `--skip-git-repo-check`,
`--ephemeral`, `--ignore-user-config`, `--ignore-rules`, `--output-schema`, `--color`,
`--json`, `-o/--output-last-message`. Subcommands: `resume`, `review`, `help`.
No `--timeout`, no `--detach`. `--ask-for-approval` remains absent from `exec` (top-level
only) — the existing pin is still correct. With stdin attached, `codex exec` prints
`Reading additional input from stdin...` to stderr; keep `</dev/null`.

---

## Updated 2026-09-02 — preflight-workflow-probe

Local Claude Code **2.1.238**. Sources: `BINARY` = verbatim strings from
`/Users/oleg/.local/share/claude/versions/2.1.238`; `FETCHED` = `https://code.claude.com/docs/en/hooks`
(note: `https://docs.claude.com/en/docs/claude-code/hooks` now **301**s there).

### The full event list (FETCHED 2026-09-02) — 33 events

`SessionStart` · `Setup` · `UserPromptSubmit` · `UserPromptExpansion` · `PreToolUse` ·
`PermissionRequest` · `PermissionDenied` · `PostToolUse` · `PostToolUseFailure` · `PostToolBatch` ·
`Notification` · `MessageDisplay` · `SubagentStart` · `SubagentStop` · `TaskCreated` ·
`TaskCompleted` · `Stop` · `StopFailure` · `TeammateIdle` · `InstructionsLoaded` · `ConfigChange` ·
`CwdChanged` · `DirectoryAdded` · `FileChanged` · `WorktreeCreate` · `WorktreeRemove` · `PreCompact` ·
`PostCompact` · `PreModelSwitch` · `PostModelSwitch` · `Elicitation` · `ElicitationResult` ·
`SessionEnd`

Corroborated by `BINARY` quoted-string counts in 2.1.238: `PreToolUse` 37, `Stop` 54,
`UserPromptSubmit` 26, `SessionStart` 27, `PostToolUseFailure` 19, `SessionEnd` 9, `Notification` 9,
`PreCompact` 7, `PostCompact` 6. Every event this plugin registers in `hooks/hooks.json` is real.

### Which events promote plain stdout to model context (2026-09-02)

**Only four:** `UserPromptSubmit`, `UserPromptExpansion`, `SessionStart`, `PostModelSwitch`.
`FETCHED`: "For most events, Claude Code writes stdout to the debug log and doesn't show it in the
transcript. The exceptions are `UserPromptSubmit`, `UserPromptExpansion`, `SessionStart`, and
`PostModelSwitch`, where Claude Code adds plain-text stdout as context that Claude can see and act on."

**`PostCompact` is NOT one of them** — its stdout is the compaction's display text. This independently
confirms the claim already recorded in `hooks/hooks.json:5` for 2.1.238. Consequence: a PostCompact
hook cannot inject model context via stdout, so "structured vs rendered" output there is
presentational only.

### PostCompact row (BINARY, embedded hooks reference, 2026-09-02)

```
| PreCompact  | "manual"/"auto" | Before compaction |
| PostCompact | "manual"/"auto" | After compaction (receives summary) |
```

PostCompact receives the compaction summary; `SessionStart` does not.

### Context-injection shape (BINARY, 2026-09-02)

```json
{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "..."}}
```

`hookSpecificOutput` "must include `hookEventName`"; `additionalContext` is "Text injected into model
context". Top-level `additionalContext` without the wrapper is **not** supported — the binary carries
the error string `Did you mean hookSpecificOutput.additionalContext (with a hookEventName)?`.
`hooks/session-banner.sh:57-58` emits the correct shape.

Also `BINARY`, worth pinning against future confabulation:
`decision` — `"block"` for PostToolUse/Stop/UserPromptSubmit, **deprecated for PreToolUse** (use
`hookSpecificOutput.permissionDecision`: `"allow" | "deny" | "ask"`). This matches the 2026-09-01 1C
audit's finding and again contradicts the `"continue" | "stop"` values a WebFetch summary invented
that day. **Grade hook-contract claims `BINARY`, not `FETCHED`.**

### Hook types (BINARY, 2026-09-02)

`command` · `prompt` (LLM condition) · `agent` (runs an agent with tools). The latter two are
**only available for tool events**: `PreToolUse`, `PostToolUse`, `PermissionRequest`.
