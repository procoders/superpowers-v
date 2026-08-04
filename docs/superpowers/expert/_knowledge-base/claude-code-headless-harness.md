# Claude Code as a Headless Harness Knowledge Base

Running `claude -p` as a scripted worker process: `--bare` semantics, auth precedence, how tools
are actually restricted (and how they are not), permission-mode behaviour under automation, model
routing slots, and redirecting the CLI at a non-Anthropic endpoint.

Maintained by Compound V Phase 1B advisor. Append at the bottom on each pass.

---

## Updated 2026-07-31 — `--bare` worker against a third-party Anthropic-compatible endpoint

All quotes verified against `https://code.claude.com/docs/en/*` on 2026-07-31.

### `--bare` — what it actually does

[CLI reference](https://code.claude.com/docs/en/cli-reference):

> *"Minimal mode: skip auto-discovery of hooks, skills, plugins, MCP servers, auto memory, and
> CLAUDE.md so scripted calls start faster. Claude has access to Bash, file read, and file edit
> tools. Sets `CLAUDE_CODE_SIMPLE`."*

[Headless doc](https://code.claude.com/docs/en/headless), "Start faster with bare mode":

> *"Bare mode is useful for CI and scripts where you need the same result on every machine. A hook
> in a teammate's `~/.claude` or an MCP server in the project's `.mcp.json` won't run, because bare
> mode never reads them. **Only flags you pass explicitly take effect.**"*
>
> *"**Bare mode skips OAuth and keychain reads.** For Anthropic authentication, set
> `ANTHROPIC_API_KEY` or configure an `apiKeyHelper` in the JSON you pass to `--settings`. Amazon
> Bedrock, Google Cloud's Agent Platform, and Microsoft Foundry use their usual provider credentials."*
>
> *"`--bare` is the recommended mode for scripted and SDK calls, and **will become the default for
> `-p` in a future release**."*

**Reusable consequences:**
- **Credential isolation is structural, not conventional.** A `--bare` worker with a scrubbed env
  cannot bill the operator's Anthropic subscription — OAuth and keychain are never read. This is
  the single strongest argument when justifying a third-party-endpoint worker.
- **`--bare` disables hooks**, so `PreToolUse` is unavailable as a permission escape hatch.
- Context must be re-supplied explicitly. Documented re-injection flags:
  `--append-system-prompt` / `--append-system-prompt-file` (system prompt), `--settings`
  (settings, incl. permission rules), `--mcp-config`, `--agents`, `--plugin-dir` / `--plugin-url`.
- **[REPORTED]** `--bare` shipped ~2026-03-22 ([gradually.ai changelog](https://www.gradually.ai/en/changelogs/claude-code/)):
  *"for scripted `-p` calls that skips hooks, LSP, plugin sync, and skill directory walks; it
  requires ANTHROPIC_API_KEY or apiKeyHelper via --settings."* It is a young flag — pin the CLI
  version any adapter was verified against.

### Restricting tools: `--allowedTools` is NOT a restriction

The most common and most consequential misreading. Three distinct mechanisms:

| Flag / mechanism | What it does |
|---|---|
| `--allowedTools` | *"Tools that execute **without prompting** for permission."* Pre-approval only. The CLI doc says outright: *"**To restrict which tools are available, use `--tools` instead.**"* |
| `--tools` | Restricts which tools exist at all. `--tools ""` strips tool access entirely. |
| deny rule, bare tool name | [permissions](https://code.claude.com/docs/en/permissions): *"A bare tool name like `Bash` **removes the tool from Claude's context entirely, so Claude never sees it.**"* A scoped rule like `Bash(rm *)` leaves the tool available and blocks matching calls. In bare mode, pass via `--settings '{"permissions":{"deny":["Bash"]}}'` since settings files are not auto-discovered. |

Rule evaluation order: **deny → ask → allow**; first match wins; specificity does not reorder.
A broad deny cannot carry allowlist exceptions.

### `dontAsk` — and the read-only Bash set that survives it

[permission-modes](https://code.claude.com/docs/en/permission-modes):

> *"If you set `dontAsk` mode, Claude Code auto-denies every tool call that would otherwise prompt
> you. Claude runs only actions matching your `permissions.allow` rules, **read-only Bash
> commands**, and calls approved by a PreToolUse hook. Use this mode for CI pipelines or restricted
> environments … the session never waits for input."*

Also denied in `dontAsk` regardless of allow rules: `AskUserQuestion`, org-`ask` connector tools,
MCP tools marked `requiresUserInteraction`. Protected-path writes are **Denied** in `dontAsk`.

[permissions](https://code.claude.com/docs/en/permissions), "Read-only commands":

> *"Claude Code recognizes a built-in set of Bash commands as read-only and runs them without a
> permission prompt **in every mode**. These include `ls`, `cat`, `echo`, `pwd`, `head`, `tail`,
> `grep`, `find`, `wc`, `which`, `diff`, `stat`, `du`, `cd`, and read-only forms of `git`. **The set
> is not configurable**; to require a prompt for one of these commands, add an `ask` or `deny`
> rule for it."*

**Reusable rule:** `--permission-mode dontAsk` + `--allowedTools "Read,Grep,Glob,Edit,Write"` does
**not** withhold Bash. It closes the arbitrary-command channel — the security conclusion usually
survives — but the worker still has a read-only shell including read-only `git`. If a doc claims
"Bash is withheld," it is wrong; either use `--tools` / a bare-name deny rule, or state accurately:
*"arbitrary commands are denied; a non-configurable read-only subset remains."*

Permission mode summary (what runs without asking):

| Mode | Without asking | Protected-path writes |
|---|---|---|
| `default` (labelled **Manual**, alias `manual` ≥ v2.1.200) | reads only | prompted |
| `acceptEdits` | reads, file edits, `mkdir touch rm rmdir mv cp sed` in-scope | prompted |
| `plan` | reads + read-only shell (+ classifier-approved with auto mode) | prompted |
| `auto` | everything, classifier-checked | routed to classifier |
| `dontAsk` | **only pre-approved** + read-only Bash + PreToolUse-approved | **denied** |
| `bypassPermissions` | everything | allowed |

Note for automation: in **auto** mode under `-p`, *"repeated blocks abort the session since there
is no user to prompt"* (3 consecutive / 20 total classifier blocks). `dontAsk` has no such fallback
— it just denies.

### Model routing slots — the one that bites when you repoint the base URL

Claude Code routes to **three** named model slots, not one:

- `ANTHROPIC_DEFAULT_OPUS_MODEL`
- `ANTHROPIC_DEFAULT_SONNET_MODEL`
- `ANTHROPIC_DEFAULT_HAIKU_MODEL` — the small/fast slot; **`ANTHROPIC_SMALL_FAST_MODEL` is
  deprecated in its favour** ([model-config](https://code.claude.com/docs/en/model-config)).

`ANTHROPIC_MODEL` alone does not cover the small/fast slot. **Reusable trap:** when repointing at a
third-party Anthropic-compatible endpoint, an unset haiku slot sends an Anthropic model id to a
provider that may not map it, producing a provider-specific unknown-model 400. Third-party vendors'
own setup docs set all three (z.ai's Claude Code page sets opus/sonnet → `glm-5.2`, haiku →
`glm-4.7`, plus `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: 1` and `API_TIMEOUT_MS: 3000000`).

**Naming note for repos with a "never Haiku" policy:** `ANTHROPIC_DEFAULT_HAIKU_MODEL` is a Claude
Code *routing-slot* env var, not a `model:` frontmatter value. Setting it to a non-Anthropic model
puts zero Haiku in the run. Frontmatter linters grep frontmatter; nothing breaks. Say so explicitly
or a reviewer will flinch at the variable name.

### `-p` headless behaviour worth knowing before wrapping it

- Output: `--output-format text | json | stream-json`. JSON payload *"includes `total_cost_usd` and
  a per-model cost breakdown"* — **computed from Anthropic's price table**, so it is meaningless
  (and actively misleading) when the request went to a third-party model. Do not carry it.
- `--json-schema` with `--output-format json` puts conforming output in `structured_output`.
- Retry telemetry: `system/api_retry` stream events carry `attempt`, `max_retries`,
  `retry_delay_ms`, `error_status`, and an `error` enum —
  `authentication_failed`, `oauth_org_not_allowed`, `billing_error`, `rate_limit`, `overloaded`,
  `invalid_request`, `model_not_found`, `server_error`, `max_output_tokens`, `unknown`. Usable as a
  provider-agnostic failure-classification fallback whenever the output is JSON.
- `system/init` reports session metadata: `model`, `tools`, `mcp_servers`, `plugins`,
  `plugin_errors`, `mcp_server_errors`, and (≥ v2.1.205) a `capabilities` array for feature
  detection instead of version-string comparison.
- SIGTERM: aborts the turn, kills the Bash process tree, runs `SessionEnd` hooks, **exits 143**.
- Background Bash tasks are killed ~5s after the final result; background subagents are waited for,
  capped at 10 min by default (`CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS`).
- Piped stdin capped at 10MB since v2.1.128.
- Session-id lookup for `--resume` is scoped to the **current project directory and its git
  worktrees** — run resume from the same directory.

### Third-party endpoints — the terms position (see also `llm-subscription-plan-compliance.md`)

- Third-party model providers are a **documented Claude Code feature** (Bedrock, Google Cloud Agent
  Platform, Microsoft Foundry; `ANTHROPIC_BASE_URL` documented across the CLI). The *mechanism* is
  sanctioned; only novel *destinations* are unaddressed.
- Anthropic's actual restriction runs the opposite way — third parties routing requests through
  **Anthropic subscription credentials** ([legal-and-compliance](https://code.claude.com/docs/en/legal-and-compliance)).
  A `--bare` worker with a scrubbed env cannot do this even by accident.
- **[NOT FOUND]** any Anthropic statement on pointing the CLI at a non-Anthropic endpoint;
  [claude-code #5577](https://github.com/anthropics/claude-code/issues/5577) asked exactly that
  (2025-08-12) and was closed with no reply.
- Prior art for the pattern: [cc-fleet](https://github.com/ethanhq/cc-fleet) (*"Every third-party
  worker is a real Claude process with its LLM backend swapped to the provider"*),
  [deep-claude](https://github.com/dennisonbertram/deep-claude). Useful when a maintainer asks
  "has anyone done this?"

### Reusable one-liners

- `--allowedTools` pre-approves; `--tools` restricts; a bare-name **deny** rule erases.
- `dontAsk` still runs the non-configurable read-only Bash set — in every mode, no exceptions.
- `--bare` skips OAuth **and** keychain: that is the credential-isolation guarantee, in Anthropic's
  own words.
- `--bare` skips hooks, so `PreToolUse` is not a fallback guard for a bare worker.
- Redirecting `ANTHROPIC_BASE_URL` without also setting the haiku/small-fast slot is the most
  likely first production 400.
- `total_cost_usd` from `--output-format json` is an Anthropic price-table computation and is
  garbage for a non-Anthropic model.

---

## Updated 2026-08-04 — cwd-rooted config discovery breaks the `env -i` isolation model

### 🔑 The taxonomy: `$HOME`-rooted vs cwd-rooted agents

The `env -i` allow-list + scratch-`HOME` pattern (established for `claude`, reused by `opencode` and
`zai`) is a **complete** isolation answer for one class of CLI and a **partial** one for another.
Classify the binary before reusing the pattern.

| Class | Where credentials/config are discovered | Is `env -i` + scratch `HOME` sufficient? |
|---|---|---|
| **`$HOME`-rooted** — e.g. `claude` (`~/.claude`, keychain, `CLAUDE_CONFIG_DIR`) | environment + `$HOME` | **Yes** — both are controlled by the launcher |
| **cwd-rooted** — every **Gemini CLI fork**: `gemini`, `qwen` (`.qwen/.env`, `.env`, `.qwen/settings.json` **in the working directory**) | environment + `$HOME` + **cwd** | **No** — cwd is the worktree, a checkout of the repo under test. No environment scrub can reach a filesystem read. |

**Why this matters for a dispatcher:** the worker's cwd is a git worktree of the repository being
worked on. For a cwd-rooted agent, that repository's contents are **part of the agent's configuration
surface**, not merely its input.

**Mitigating fact worth claiming explicitly:** `git worktree add` materialises **tracked files only**,
so the operator's own gitignored `.env` does *not* travel into the worktree. Three paths survive:
(a) a repo that *tracks* `.env` / `.qwen/`; (b) a resumed or re-dispatched job re-entering a worktree
a previous job wrote into; (c) any repo whose HEAD is not fully trusted.

### Qwen Code discovery order (verified 2026-08-04, primary docs)

[auth](https://qwenlm.github.io/qwen-code-docs/en/users/configuration/auth/) ·
[settings](https://qwenlm.github.io/qwen-code-docs/en/users/configuration/settings/)

```
credential precedence (high → low):
  CLI flags → shell env → .env files → settings.json `env`

.env search — STOPS at the first file found; files are NOT merged:
  1. .qwen/.env          ← cwd  (never subject to excludedEnvVars filtering)
  2. .env                ← cwd  (excludedEnvVars applies; default ["DEBUG","DEBUG_MODE"])
  3. ~/.qwen/.env
  4. ~/.env

settings precedence (low → high):
  defaults → system defaults → user (~/.qwen) → PROJECT (.qwen/settings.json) → system → env → CLI flags
```

**What still holds under a scrub:** *"Only variables not already present in `process.env` are
loaded."* An exported credential **cannot be overwritten** by a worktree `.env`. Half the design works.

**What does not:**
1. **Injection ≠ override.** Any variable the scrub does not set is unset, and a worktree `.env` can
   supply it. If the launcher exports `BAILIAN_CODING_PLAN_API_KEY` but not `OPENAI_API_KEY`, the
   latter is injectable and is a first-class auth path in the precedence list — a silent auth-path
   switch. Same failure family as the `opencode` worker authenticating from an ambient
   `ANTHROPIC_BASE_URL`.
2. **`.qwen/.env` is exempt from all filtering** — *"Variables from `.qwen/.env` files are never
   excluded."* Highest priority, least filtered, inside the worktree.
3. **Project `.qwen/settings.json` outranks user settings** and can set `tools.sandbox` (disabling the
   kernel sandbox), `advanced.excludedEnvVars` (emptying the filter), tool permissions, and
   **`mcpServers`** — arbitrary local commands that run outside the model's tool loop, outside a
   git-derived scope gate, and outside a sandbox the same file just turned off.

### ⚠️ Gemini CLI forks inherit an unpatched RCE class — check the fork point

[**GHSA-wpqr-6v78-jr5g**](https://github.com/advisories/GHSA-wpqr-6v78-jr5g) — *"Gemini CLI: Remote
Code Execution via workspace trust and tool allowlisting bypasses"*, **Critical, CVSS 10.0**,
published **2026-04-24**. Affects `@google/gemini-cli` < 0.39.1 (and `= 0.40.0-preview.2`); fixed in
**0.39.1 / 0.40.0-preview.3**; `google-github-actions/run-gemini-cli` < 0.1.22.

Two chained flaws, both directly relevant to any headless worker:

> "Gemini CLI running in CI environments (headless mode) automatically trusted workspace folders for
> the purpose of loading configuration and environment variables… If used with untrusted directory
> contents, this could lead to remote code execution."

> under `--yolo`, the tool allowlist "was ignored entirely" — "an allowlist intended to permit
> `run_shell_command(echo)` could effectively allow any command."

Fixed behaviour upstream: headless + untrusted folder raises `FatalUntrustedWorkspaceError` and exits.

**Reusable rule: a fork inherits the vulnerability history of everything between its fork point and
the fix.** Qwen Code forks Gemini CLI **v0.8.2** — ~31 minor versions before 0.39.1. Qwen Code ships a
[Trusted Folders](https://qwenlm.github.io/qwen-code-docs/en/users/configuration/trusted-folders/)
feature (`security.folderTrust.enabled`; untrusted ⇒ `.qwen/settings.json` not loaded, `.env` not
loaded, extensions restricted, tool auto-acceptance disabled, `~/.qwen/trustedFolders.json`) — but the
docs state it is **disabled by default** and are **silent on headless behaviour**. Backport status:
**[UNVERIFIED]** — a live-probe item, not an assumption.

**The dangerous configuration, named:** `--yolo` + headless + no mandatory sandbox + cwd = a checkout
of the repo under test + folder-trust unset. That is the advisory's exact shape. Note also that
`--yolo` **does not sandbox** in Qwen Code — sandboxing is a separate opt-in (`--sandbox`,
`QWEN_SANDBOX`, `tools.sandbox`).

### Two reusable defences for cwd-rooted workers

1. **Pre-flight worktree config check.** Before launching, refuse (or quarantine) if the worktree
   contains any agent-config path — for Qwen Code: `.qwen/.env`, `.env`, `.qwen/settings.json`,
   `.qwen/QWEN.local.md`. On a clean repo this never fires and costs nothing; it exists for the
   tracked-secret and resumed-worktree cases. **Comment the reasoning in the script** or it gets
   deleted later as dead code.
2. **Response model assertion** (generalised from `zai`'s GLM assertion). Read the model identifier
   out of the response and **fail the job** unless it matches what was requested. This is the only
   defence against a silent auth-path switch, and it converts an unnoticed charge on the wrong
   credential into a failed job. **Every** backend whose credential resolution has more state than the
   launcher models needs one. Corroborating mechanism: [qwen-code #1855](https://github.com/QwenLM/qwen-code/issues/1855)
   (2026-02-17, closed — *isolated report*), cached OAuth credentials continuing to take priority over
   a newly configured Coding Plan key, yielding persistent 401s.

### Context-file egress differs per agent — never copy another adapter's file list

Every hierarchical-context agent concatenates discovered context files and **sends them with every
prompt**. The *file names* differ, so a copied warning sends operators to check the wrong files.

| Agent | Default context files discovered |
|---|---|
| `claude` | `~/.claude/CLAUDE.md`, `./CLAUDE.md`, subdirectory `CLAUDE.md` |
| `qwen` | `QWEN.md`, `CONTEXT.md`, **`AGENTS.md`** (default since [#2006](https://github.com/QwenLM/qwen-code/issues/2006) → PR #2018, 2026-02-28; `QWEN.md`→`AGENTS.md` rename 2026-03), `.qwen/QWEN.local.md` (0.16.2, 2026-05-27), plus transitive `@path/to/file.md` imports |
| `gemini` | `GEMINI.md` (global / project-upward / subdirectory scan), `contextFileName` override |

**Consequence for repos that carry an `AGENTS.md`** (this one does): a `qwen` job ships the repo's
agent-instruction file — often its densest architecture document — to the vendor on **every job**.
`HOME` redirection isolates *user-level* config only; the repo's *project-level* context is inside the
worktree by construction.

### Other Qwen Code headless facts (docs-verified 2026-08-04)

- Headless mode is officially *"ideal for scripting, automation, CI/CD pipelines"*
  ([headless docs](https://qwenlm.github.io/qwen-code-docs/en/users/features/headless/)) — worth
  quoting when a vendor's *subscription* terms say the opposite.
- Useful flags the wrappers tend to miss: **`--max-session-turns`** (the right spend control on a
  request-billed plan) and **`--max-wall-time`** (overlaps an external timeout supervisor — pick one
  authority deliberately).
- **No `--cd`** flag. Requires the subshell-`cd` pattern, same as `claude` and `cursor`.
- **No headless effort flag.** The 5-tier ladder is the interactive `/effort` command or
  `model.reasoningEffort` in settings.json — so applying effort headlessly means writing a settings
  file, which must go in the **scratch `HOME`**, never the worktree, or the worker dirties its own
  diff and trips the scope gate.

### Reusable one-liners (additions)

- Classify the binary first: `$HOME`-rooted or **cwd-rooted**. `env -i` is a complete answer only for
  the former.
- A cwd-rooted agent makes the repo under test part of its *configuration*, not just its input.
- An environment scrub prevents **override**, never **injection** — unset names are free real estate.
- `git worktree add` checks out tracked files only: a real mitigation, worth claiming, not a guarantee.
- A fork inherits every CVE between its fork point and the fix. Check the fork point.
- `--yolo`/auto-approve is an **approval** setting, not a **sandbox** setting, in every Gemini-CLI fork.
- Security features documented as "disabled by default" must be set **explicitly** by a launcher —
  never inherited.
- Copy another adapter's egress *reasoning*, never its *file list*.
