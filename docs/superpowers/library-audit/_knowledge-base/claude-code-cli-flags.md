# Claude Code CLI Flags — Library Knowledge Base

Maintained by Compound V Phase 1C validator. Append at the bottom.

---

## Updated 2026-07-31 — zai backend (PR 1 of 3)

Verified against **`claude 2.1.207` installed on this machine**, by (a) reading the option-registration
table inside the binary, and (b) capturing the real wire request with a **localhost HTTP stub** standing in
for the Anthropic endpoint. No network egress, no API key, no quota spend.

Doc host note: `docs.anthropic.com` and `docs.claude.com` now redirect. Canonical:
`code.claude.com/docs/en/*` (Claude Code), `platform.claude.com/docs/en/*` (API).

### `--allowedTools` does NOT control which tools exist (2026-07-31)

The single most misleading flag in the CLI. It governs **prompting only**.

> "`--allowedTools`, `--allowed-tools` | Tools that execute without prompting for permission. …
> **To restrict which tools are available, use `--tools` instead**"
> — <https://code.claude.com/docs/en/cli-reference>

Measured matrix — "tools sent" = the `tools` array in the actual API request body:

| Invocation | Tools sent on the wire |
|---|---|
| `--bare --permission-mode dontAsk --allowedTools Read,Grep,Glob,Edit,Write` | `Bash, Edit, Read` |
| `--bare` (no tool flags at all) | `Bash, Edit, Read` — **identical** |
| `--bare --tools default` | `Bash, Edit, Read` — cannot be widened |
| `--bare --tools Edit,Read` | `Edit, Read` |
| `--bare --disallowedTools Bash` | `Edit, Read` |
| non-bare `--allowedTools Read,Grep,Glob,Edit,Write` | 29 tools incl. `Write`, `WebFetch`, `Agent`, `Cron*` |

Levers that actually remove a tool:
- `--tools <list>` — "Restrict which built-in tools Claude can use." Does not affect MCP tools.
- `--disallowedTools <BareName>` — "A bare tool name removes the matching tools from Claude's context
  entirely, so Claude never sees it." Scoped rules like `Bash(rm *)` leave the tool and deny matching calls.

**Delimiter:** both comma and space are accepted by `--allowedTools`/`--tools`/`--disallowedTools`.

### `--bare` tool set is capped at `Bash, Edit, Read` (2026-07-31)

> "In bare mode Claude has access to the Bash, file read, and file edit tools."
> — <https://code.claude.com/docs/en/headless>

Measured tool descriptions in bare mode:

```
Bash :: execute shell commands
Edit :: modify file contents in place
Read :: read files, images, PDFs, notebooks
```

Consequences for headless workers:
- **No `Write`.** `Edit` modifies *in place*, so a bare worker **cannot create a new file** with a tool.
  The only creation path left is `Bash`.
- **No `Grep`/`Glob`.** Search must go through `Bash`.
- The set **cannot be widened** — `--tools default` still yields the same three.

### `--bare` auth: `ANTHROPIC_AUTH_TOKEN` works, despite `--help` (2026-07-31)

Local `claude --help` claims bare-mode auth is "strictly ANTHROPIC_API_KEY or apiKeyHelper via --settings".
**That is incomplete.** Measured under `--bare`:

| Env var | Header actually sent |
|---|---|
| `ANTHROPIC_API_KEY` | `x-api-key: …` (no `Authorization` header) |
| `ANTHROPIC_AUTH_TOKEN` | `Authorization: Bearer …` — **honoured under `--bare`** |

Matches the documented header mapping:
> "`ANTHROPIC_AUTH_TOKEN` in `Authorization: Bearer`, `ANTHROPIC_API_KEY` in `x-api-key`, and
> `apiKeyHelper` in both." — <https://code.claude.com/docs/en/llm-gateway-connect>

Picking the wrong one against a third-party Anthropic-compatible endpoint is an **auth failure**, not a
style choice. When the gateway's header type is unknown, Anthropic's documented default is
`ANTHROPIC_AUTH_TOKEN`.

The **OAuth/keychain** half of the guarantee is publicly documented:
> "Bare mode skips OAuth and keychain reads." — <https://code.claude.com/docs/en/headless>

⚠️ Not independently reproduced here: the OAuth token on the test machine was expired, so bare and
non-bare both returned "Not logged in". The differentiator was never exercised. Treat as vendor-stated.

### `dontAsk` permits read-only Bash in EVERY mode (2026-07-31)

> "`dontAsk` denies anything not in your `permissions.allow` rules **or the read-only command set**"
> — <https://code.claude.com/docs/en/headless>

> "Claude Code recognizes a built-in set of Bash commands as read-only and runs them **without a permission
> prompt in every mode**. These include `ls`, `cat`, `echo`, `pwd`, `head`, `tail`, `grep`, `find`, `wc`,
> `which`, `diff`, `stat`, `du`, `cd`, and read-only forms of `git`. **The set is not configurable**"
> — <https://code.claude.com/docs/en/permissions#read-only-commands>

Security consequence for sandboxed workers: if `Bash` is in the tool set and `HOME` is forwarded,
`cat ~/.claude/.credentials.json` is reachable under `dontAsk`. The `Read` **tool** is confined to the
working directory; `Bash`/`cat` is **not** path-scoped. Remove the tool (`--disallowedTools Bash`) or
scrub `HOME` — a permission mode alone does not close this.

`dontAsk` also never waits for input (safe headless), and never appears in the Shift+Tab cycle.

### System-prompt flags (2026-07-31)

All four are publicly documented, but `--system-prompt-file` and `--append-system-prompt-file` are
registered with `.hideHelp()` and so are **absent from local `claude --help`** — do not conclude they
don't exist from `--help` alone.

- `--append-system-prompt-file <file>` composes with `--bare` (measured: injected marker present in request).
- Mutually exclusive with `--append-system-prompt`: *"Error: Cannot use both … Please use only one."*

### `--exclude-dynamic-system-prompt-sections` — the prompt-cache lever (2026-07-31)

> "Move per-machine sections from the system prompt (working directory, environment info, memory paths,
> git-repo flag) into the first user message. Improves prompt-cache reuse across different users and
> machines running the same task. Only applies with the default system prompt; ignored when
> `--system-prompt` or `--system-prompt-file` is set." — <https://code.claude.com/docs/en/cli-reference>

Why it matters — **measured** system blocks under `--bare`:

```
SYS[1] cache_control={'type':'ephemeral'}  "You are a Claude agent, built on Anthropic's Claude Agent SDK."
SYS[2] cache_control={'type':'ephemeral'}  "CWD: …\nDate: 2026-08-01\n\ngitStatus: …"
```

The volatile per-machine text sits **inside** the cached prefix, so it breaks cross-worker cache reuse by
construction. Open question: the flag is documented as moving the "git-repo flag", which may be narrower
than the full `gitStatus` block observed. Measure before relying on it.

### `--effort` EXISTS and accepts `xhigh` (2026-07-31)

> `--effort <level>  Effort level for the current session (low, medium, high, xhigh, max)`
> — `claude 2.1.207 --help`

Measured: `--bare --effort xhigh` is accepted (no parse error). `anthropic-beta: effort-2025-11-24` rides
on every request. Any adapter doc claiming "Claude Code has no reasoning-effort flag" or "`xhigh` is
codex-only" is **stale**.

### `--output-format json` result shape (2026-07-31)

Measured result object (error path):

```json
{"type":"result","subtype":"success","is_error":true,"api_error_status":400,
 "result":"API Error: 400 …","session_id":"8bb63881-b989-46d3-987b-1a04abb53dd8",
 "total_cost_usd":0,
 "usage":{"input_tokens":0,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,
          "output_tokens":0,"service_tier":"standard", …},
 "modelUsage":{}, "permission_denials":[], "uuid":"…"}
```

- `.result`, `.session_id`, `.usage.input_tokens`, `.usage.output_tokens`, `.modelUsage`, `.is_error` — all present.
- `.session_id` is a real **RFC-4122 UUID**.
- ⚠️ **`subtype` reported `"success"` on a hard 400.** Never key success off `subtype`; use `is_error`.
  (The TypeScript SDK types `subtype` as `"end" | "interrupted"`, which also doesn't match the observed value.)
- ⚠️ `modelUsage` is `{}` on the error path — gate any `measured: true` flag on non-empty usage so a failed
  job never records zeros as real measurements.

### Flag stability (2026-07-31, bounded)

Zero changelog entries for `--bare`, `dontAsk`, `--permission-mode`, `--allowedTools`, `--output-format`,
`--system-prompt-file`, `--append-system-prompt-file`, or `--exclude-dynamic-system-prompt-sections`
across **v2.1.179–2.1.220**. Bounded negative — could not page further back.

Direction of travel: *"`--bare` is the recommended mode for scripted and SDK calls, and **will become the
default for `-p` in a future release**."* Anything relying on non-bare `-p` defaults should expect churn.

### Zero-cost wire-inspection recipe (2026-07-31)

To see exactly what `claude -p` sends without spending a token: run a localhost HTTP server that logs
headers + body and returns HTTP 400, then point the CLI at it.

```bash
env -i PATH=/usr/bin:/bin HOME=$HOME TMPDIR=/tmp LANG=en_US.UTF-8 \
  ANTHROPIC_BASE_URL=http://127.0.0.1:8791 \
  ANTHROPIC_API_KEY=sk-test-AAAA ANTHROPIC_MODEL=<model> \
  claude -p "hi" --output-format json --bare </dev/null
```

Reveals: auth header, `POST {base}/v1/messages?beta=true`, `anthropic-version: 2023-06-01`, the
`anthropic-beta` list, the resolved `model`, every system block with its `cache_control`, and the full
tool array. This is the only reliable way to check tool-set and auth claims — a fake `claude` on `PATH`
validates argv but **cannot** reveal that the real binary interprets a flag differently.

---

## Updated 2026-08-04 — qwen backend (cross-tool: the `allowedTools` trap is a family trait)

Cross-reference added while auditing Qwen Code CLI v0.21.5. Full detail lives in
`qwen-code-cli.md`; recorded here because it changes how the Claude Code entry above should be read.

### The "allowed tools ≠ available tools" inversion is inherited, not a Claude Code quirk

The 2026-07-31 entry above documents `--allowedTools` as *"the single most misleading flag in the CLI"*
— it governs prompting only, and `--tools` / `--disallowedTools` are the real levers.

**Qwen Code has the identical flag with the identical semantics**, verified in its released source:

```ts
// QwenLM/qwen-code @ v0.21.5 — packages/cli/src/config/config.ts
.option('allowed-tools', { type: 'array', string: true,
  description: 'Tools to allow, will bypass confirmation' })
```

Qwen Code is a fork of Google's Gemini CLI (v0.8.2 base), so this is a **lineage trait shared by every
Gemini-CLI-derived agent**, not a Claude Code idiosyncrasy. Treat "a flag named `--allowed*tools`" as a
confirmation-bypass control by default in any such tool, and go find the separate restriction flag.

Restriction-lever mapping across the two tools:

| Concern | Claude Code | Qwen Code v0.21.5 |
|---|---|---|
| bypass confirmation (**not** restriction) | `--allowedTools` / `--allowed-tools` | `--allowed-tools` |
| restrict which tools exist | `--tools <list>` | `--core-tools <list>` |
| remove specific tools | `--disallowedTools <BareName>` | `--exclude-tools <list>` |
| hard stop on any tool use | — | `--max-tool-calls 0` (exit 55) |
| no-execution mode | `--permission-mode plan` | `--approval-mode=plan` |

Aggravating factor in Qwen Code: `allowed-tools` is registered **twice** in the same yargs command
(`config.ts:769` and `config.ts:950`) with slightly different help text — a docs-only reader is even more
likely to land on the wrong one.

### `--bare` means different things in the two CLIs — do not carry the assumption across

| | meaning |
|---|---|
| Claude Code | caps the tool set at `Bash, Edit, Read`; **cannot be widened** (measured, 2026-07-31 above) |
| Qwen Code v0.21.5 | *"Minimal mode: skip implicit startup auto-discovery and only honor explicitly provided CLI inputs."* — a **hermeticity** lever, says nothing about the tool set |

Qwen Code's nearest equivalent to Claude Code's `--bare` tool-capping is `--core-tools <list>`; its
nearest equivalent for suppressing ambient configuration is `--safe-mode` (disables context files, hooks,
extensions, skills, MCP servers).

### Method note reinforced

The 2026-07-31 entry's closing point — *"a fake `claude` on `PATH` validates argv but cannot reveal that
the real binary interprets a flag differently"* — held again. For Qwen Code the cheap substitute for a
live probe was **reading the released source's `yargs` table at the exact tag**, which surfaced four
doc-contradicting facts a docs-only pass had accepted. See `qwen-code-cli.md`.

Sources: <https://github.com/QwenLM/qwen-code/blob/v0.21.5/packages/cli/src/config/config.ts>;
audit `docs/superpowers/library-audit/2026-08-04-qwen-code-cli-backend.md`.
