# Agent Hook Context-Injection Knowledge Base

Maintained by Compound V Phase 1B advisor. Append at the bottom on each pass.

**Scope note.** This file covers the *design* rules for producing output an agent harness will
accept and inject. The event-by-event API surface (stdin schemas, event enum, exit-code matrix)
belongs to Phase 1C's `docs/superpowers/library-audit/_knowledge-base/claude-code-hooks.md` —
read that first for the contract, this for how to write a producer against it.

---

## Updated 2026-09-02 — SessionStart vs PostCompact output contracts

All runtime claims recovered by byte-offset extraction from the installed Claude Code
**2.1.238** binary (`~/.local/share/claude/versions/2.1.238`), cross-checked against
[the hooks reference](https://code.claude.com/docs/en/hooks) fetched 2026-09-02.

### Which events actually reach the model

Only **four** of ~30 events inject plain-text stdout into the model's context. Docs, verbatim:

> The exceptions are `UserPromptSubmit`, `UserPromptExpansion`, `SessionStart`, and
> `PostModelSwitch`, where Claude Code adds plain-text stdout as context that Claude can see
> and act on.

Everything else writes stdout to the debug log only. **`PostCompact` is not in the list** —
its output is user-facing display text (below). Never describe a non-listed event's hook as
"re-injecting context".

### The `hookSpecificOutput` wrapper is mandatory, and its absence fails SILENTLY

Runtime 2.1.238 dispatches per event (offset 296941375):

```js
case"SessionStart":
  u.additionalContext=e.hookSpecificOutput.additionalContext,
  u.initialUserMessage=e.hookSpecificOutput.initialUserMessage,
  u.sessionTitle=e.hookSpecificOutput.sessionTitle,
```

A **bare top-level** `{"additionalContext": "…"}` is not read. It lands in the unrecognized-key
path (offset 296470892):

```js
let s=r.includes("additionalContext")?" Did you mean hookSpecificOutput.additionalContext (with a hookEventName)?":"";
T(`Hook JSON output had unrecognized keys (ignored): ${r.join(", ")}.${s}`)
```

Ignored, diagnostic to debug log only, exit 0. **There is no error surface** — the symptom is
"the banner stopped appearing", which no test suite notices by default.

`hookSpecificOutput` variants confirmed present in 2.1.238: `PreToolUse`, `UserPromptSubmit`,
`UserPromptExpansion`, `SessionStart`, `PostToolUse`, `PostToolBatch`, `Stop`/`SubagentStop`.
**No `PostCompact` variant exists.**

### JSON is detected by the leading brace, not by content type

```js
let t=e.trim();
if(!t.startsWith("{"))return T("Hook output does not start with {, treating as plain text"),{plainText:e};
```

One stray stdout line ahead of the payload silently reclassifies structured output as prose.
On the four injecting events this degrades gracefully (the prose still reaches the model); on
every other event it disappears. Corroborated in the wild by the debug log in
[anthropics/claude-code#12671](https://github.com/anthropics/claude-code/issues/12671)
(2025-11-29, CLOSED) — *isolated report*, cited for its debug evidence, not as consensus.

### The 10,000-char figure is a persist-to-disk threshold, NOT a cap

Widely repeated secondary sources call it a "10,000-character cap". The runtime is more
forgiving:

```js
async function gTt(e,t,r,n=uFp){
  if(e.length<=n)return e;
  let o=await Net(e,`hook-${t}-${r}`,tY());
  if(Fet(o))return …,`${e.slice(0,n)}\n\n[Hook ${r} truncated at ${n} chars — persist-to-disk failed: ${o.error}]`;
  …}
```

`uFp=1e4` (offset 287057089). Over the threshold the content is **persisted to disk and
replaced by a reference**; hard truncation happens only if that write fails, and is marked
explicitly. Telemetry event: `tengu_hook_output_persisted`.

Also: `additionalContext` is **not** passed through the capping function that
`classifierContext` is. The runtime's own log strings distinguish them —
`") provided classifierContext ("` + `" chars after cap)"` versus
`") provided additionalContext ("` + `" chars)"`.

**Design consequence:** over-long context is not blocked, it is quietly *paid for* in context
budget. Bound your output yourself; the runtime will not do it for you.

### PostCompact: stdout becomes `userDisplayMessage`, and the runtime wraps it

Producer and consumer, verbatim (offset ~697620):

```js
let i={...c_(e,er()),hook_event_name:"PostCompact",trigger:t.trigger,compact_summary:t.compactSummary},…
a.push(`PostCompact [${l.command}] completed successfully: ${l.output.trim()}`)
…
return{userDisplayMessage:a.length>0?a.join(…
```

- `compact_summary` and `trigger` are **real in the binary and absent from the public docs**
  (checked 2026-09-02) — version-coupled, so consumers must fail silent when missing.
- Output is shown at the compaction boundary to the **user**, not injected into the model.
- The hook does not control its own prefix; the runtime prepends
  `PostCompact [<command>] completed successfully: `.
- Therefore a PostCompact hook must emit **plain text**. A JSON object renders to the user as
  raw JSON.

### Reusable matrix

| Event | stdout → model? | `hookSpecificOutput` variant? | Emit |
|---|---|---|---|
| `SessionStart` | yes | yes (`additionalContext`, `initialUserMessage`, `sessionTitle`) | JSON wrapper |
| `UserPromptSubmit` | yes | yes (`additionalContext` required) | JSON wrapper |
| `UserPromptExpansion` | yes | yes | JSON wrapper |
| `PostModelSwitch` | yes | not enumerated in 2.1.238 error text | plain text |
| `PostCompact` | **no** — `userDisplayMessage` | **no** | **plain text** |
| `Stop` / `SubagentStop` | via `additionalContext` (non-blocking) | yes | JSON wrapper |

### Timeouts (docs, fetched 2026-09-02)

Defaults: `command`/`http`/`mcp_tool` **600 s**, `prompt` **30 s**, `agent` **60 s**.
Lowered per event: `UserPromptSubmit`, `PreModelSwitch`, `PostModelSwitch` **30 s**;
`MessageDisplay` **10 s**. `SessionEnd` hooks share a **1.5 s** budget, raised to match an
explicit `timeout` up to 60 s.

**Rule:** a hook on a per-turn or per-compaction event should set an explicit short `timeout`
regardless of the generous default — it must never be why a turn stalls.
