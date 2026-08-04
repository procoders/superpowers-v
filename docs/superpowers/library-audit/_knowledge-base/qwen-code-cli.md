# Qwen Code CLI — Library Knowledge Base

Maintained by Compound V Phase 1C validator. Append at the bottom.

---

## Updated 2026-08-04 — qwen backend adapter (Phase 1C)

Verified against the **released source at tag `v0.21.5`** (published 2026-08-04T02:17:38Z), not the
docs site. Where the docs site and the source disagree, the source is recorded and the disagreement
noted. **Not a live-binary probe** — no Coding Plan key existed at audit time.

Primary files read:
`packages/cli/src/config/config.ts` (yargs option table) ·
`packages/cli/src/config/sandboxConfig.ts` · `packages/cli/src/utils/sandbox.ts` ·
`packages/cli/src/config/environment.ts` · `packages/cli/src/utils/headlessSafetyWarnings.ts` ·
`packages/core/src/core/contentGenerator.ts`.

### Project currency (2026-08-04)

| | |
|---|---|
| npm package | `@qwen-code/qwen-code`, bin `qwen` |
| latest stable | **0.21.5**, published 2026-08-04 |
| versions published | 567 (first 2025-07-22) |
| channels | `latest` · `preview` (weekly, Tue 23:59 UTC) · `nightly` (daily, midnight UTC) |
| engines | **`node >=22.0.0`** |
| npm `license` field | **absent** — repo is Apache-2.0, but scanners report "unknown" |
| repo | not archived, not disabled, Apache-2.0, 26,646★, `pushed_at` 2026-08-04 |
| lineage | fork of Google Gemini CLI (v0.8.2 base) |

Stable cadence in the audit week: `0.21.1` (07-28) → `0.21.2` (07-31) → `0.21.3` (08-01) →
`0.21.4` (08-03) → `0.21.5` (08-04). **Five stable releases in seven days.** The currency risk for this
tool is churn, not abandonment. Pin a verified version; treat a bump as a re-verification trigger.

### ⚠️ `--sandbox` is a BOOLEAN, and `QWEN_SANDBOX` OVERRIDES it (2026-08-04)

The single most dangerous doc/source divergence found.

```ts
// packages/cli/src/config/config.ts
.option('sandbox', { alias: 's', type: 'boolean', description: 'Run in sandbox?' })
```

```ts
// packages/cli/src/config/sandboxConfig.ts
// note environment variable takes precedence over argument (from command line or settings)
const environmentConfiguredSandbox = process.env['QWEN_SANDBOX']?.toLowerCase().trim() ?? '';
sandbox = environmentConfiguredSandbox?.length > 0 ? environmentConfiguredSandbox : sandbox;
```

**The published docs assert the opposite on both points** — the sandbox page shows
`qwen --sandbox=docker|podman|sandbox-exec` and a precedence of *"CLI flag > environment variable >
settings.json"*. Neither survives contact with the source at the same tag.

Correct configuration surface:

| Concern | Lever | Values |
|---|---|---|
| enable + provider | `QWEN_SANDBOX` | `true` · `false` · `docker` · `podman` · `sandbox-exec` |
| macOS profile | `SEATBELT_PROFILE` | see below; **defaults to `permissive-open`** |
| container image | `QWEN_SANDBOX_IMAGE` / `tools.sandboxImage` | `--sandbox-image` is **deprecated** |
| extra container flags | `SANDBOX_FLAGS` | e.g. `"--security-opt label=disable"` |
| Linux uid/gid mapping | `SANDBOX_SET_UID_GID` | `1`/`true`/`0`/`false` |
| proxied profiles | `QWEN_SANDBOX_PROXY_COMMAND` | implies `HTTPS_PROXY` |

Two behaviours that bite headless callers:

- **`SANDBOX` set ⇒ sandboxing silently skipped.** `getSandboxCommand()` opens with
  `if (process.env['SANDBOX']) return '';` — the process assumes it is already contained. A leaked
  `SANDBOX` in an `env -i` allow-list disables containment with **no error**.
- **macOS always resolves to Seatbelt.** `if (os.platform() === 'darwin' && commandExists.sync('sandbox-exec')) return 'sandbox-exec';`
  fires *before* the docker/podman branches. Docker on macOS requires `QWEN_SANDBOX=docker` explicitly.

`SANDBOX` is also the **verification signal**: the transport sets it — `sandbox-exec` under Seatbelt, the
container name (e.g. `qwen-code-sandbox`) under Docker/Podman. Non-empty ⇒ genuinely sandboxed. Assert it
inside the run to prove containment engaged.

**Six built-in Seatbelt profiles** (`utils/sandbox.ts:60-67`) — commonly miscounted as five:

```
permissive-open (default)  permissive-closed   permissive-proxied
restrictive-open           restrictive-closed  restrictive-proxied
```

Custom profiles: drop a `.sb` file in the project's `.qwen/` and point `SEATBELT_PROFILE` at it.

**Sandbox ≠ network restriction.** The default profile is `-open`. Network control requires explicitly
choosing a `*-closed` or `*-proxied` profile.

### ⚠️ `--allowed-tools` bypasses confirmation — it does NOT restrict (2026-08-04)

```ts
.option('allowed-tools', { type: 'array', string: true,
  description: 'Tools to allow, will bypass confirmation' })
```

**Same trap as Claude Code's `--allowedTools`** (see `claude-code-cli-flags.md`, 2026-07-31). Both tools
descend from the Gemini CLI lineage. Registered **twice** in the same yargs command
(`config.ts:769` and `config.ts:950`) with slightly different help text, which makes a docs-only read
even likelier to land wrong.

Actual restriction levers:

| Flag | Meaning |
|---|---|
| `--core-tools <list>` | core tool paths — allowlist |
| `--exclude-tools <list>` | tools to exclude — denylist |
| `--max-tool-calls 0` | aborts on the first tool call of any kind (exit 55) |
| `--approval-mode=plan` | plan only, no execution |
| `--safe-mode` | disables context files, hooks, extensions, skills, MCP servers |

All list-valued flags accept comma-separated **or** repeated form.

### Headless invocation — verified flag table (v0.21.5)

| Flag | Type | Notes |
|---|---|---|
| *(positional)* `query` | string | **preferred prompt form**; defaults to one-shot |
| `--prompt` / `-p` | string | ⚠️ **DEPRECATED** — *"Use the positional prompt instead."* |
| `--prompt-interactive` / `-i` | string | run prompt, then stay interactive |
| `--output-format` / `-o` | `text\|json\|stream-json` | |
| `--input-format` | `text\|stream-json` | requires `-o stream-json` |
| `--include-partial-messages` | boolean | requires `-o stream-json` |
| `--json-schema <json\|@file>` | string | **headless only**; registers a synthetic `structured_output` tool; session ends on first valid call |
| `--json-fd <n>` / `--json-file <path>` | dual output | TUI on stdout, JSON events elsewhere |
| `--continue` / `-c` | boolean | most recent session for this project |
| `--resume [id]` / `-r` | string | ⚠️ **bare form opens an interactive picker** |
| `--session-id <id>` | string | **caller assigns the id** — avoids parsing it back out |
| `--fork-session` | boolean | requires `--resume`/`--continue` |
| `--chat-recording` | boolean | if false, `--continue`/`--resume` stop working |
| `--yolo` / `-y` | boolean | ⚠️ mutually exclusive with `--approval-mode` |
| `--approval-mode` | `plan\|default\|auto-edit\|auto\|yolo` | preferred over `--yolo` |
| `--sandbox` / `-s` | **boolean** | see the section above |
| `--sandbox-image` | string | ⚠️ deprecated → `tools.sandboxImage` |
| `--model` / `-m` | string | bare model name |
| `--fallback-model <m,…>` | array, max 3 | for capacity errors — **429 / 503 / 529** |
| `--auth-type` | `openai\|qwen-oauth\|gemini\|vertex-ai\|anthropic` | pin it explicitly |
| `--openai-api-key` / `--openai-base-url` | string | ⚠️ key in argv is visible to `ps` — prefer env |
| `--max-wall-time <dur>` | `90`, `30s`, `5m`, `1h`, `1.5h`; min 1s | **exit 55** on overrun |
| `--max-tool-calls <n>` | `0` = none; `-1`/unset = unlimited | **exit 55** on overrun |
| `--max-session-turns <n>` | integer | |
| `--max-subagent-depth <n>` | `1` disables nesting; default 5 | |
| `--core-tools` / `--exclude-tools` / `--allowed-tools` | array | see above |
| `--include-directories` / `--add-dir` | array | **additional** workspace dirs — NOT a cwd setter |
| `--system-prompt` / `--append-system-prompt` | string | combinable with each other |
| `--safe-mode` | boolean | disables all customizations |
| `--bare` | boolean | *"skip implicit startup auto-discovery; only honor explicitly provided CLI inputs"* |
| `--worktree [slug]` | string | ⚠️ see below |
| `--insecure` | boolean | sets `QWEN_TLS_INSECURE=1` — never use |
| `--disabled-slash-commands` | array | merges with `QWEN_DISABLED_SLASH_COMMANDS` |
| `--mcp-config` / `--allowed-mcp-server-names` | | |
| `--channel` | `VSCode\|ACP\|SDK\|CI\|desktop` | |
| `--acp` | boolean | ACP mode (`--experimental-acp` deprecated) |
| `--proxy` | string | ⚠️ deprecated → `proxy` setting |

### There is NO `--cd`/`--dir`/`--workspace` flag (2026-08-04)

Exhaustive enumeration of every `.option(` call at v0.21.5: **no cwd flag exists.** Callers must `cd` in
a subshell. `--include-directories` adds *extra* workspace dirs; it does not change cwd.

### ⚠️ `--worktree` is Qwen's OWN worktree manager — not a cwd flag

```
'Start the session inside a git worktree at <repoRoot>/.qwen/worktrees/<slug>/.
 Pass a slug (--worktree my-feature), a PR reference (--worktree=#123 or a full GitHub
 pull-request URL), or use bare --worktree to auto-generate a slug.
 On exit, the WorktreeExitDialog prompts to keep or remove the worktree.'
```

It creates a worktree at a path the caller does not choose and **prompts interactively on exit** —
a hang in any headless run. Never pass it from an orchestrator that manages its own worktrees.

### There is NO `--effort`/`--reasoning` CLI flag (2026-08-04)

Confirmed by exhaustive enumeration at v0.21.5 — zero `effort`, `reasoning`, or `thinking` options.

The reasoning-effort surface is:
- interactive slash command `/effort <tier>` (bare `/effort` opens a picker)
- settings.json `model.reasoningEffort`

**Ladder is five tiers: `low | medium | high | xhigh | max`.** One global setting applies to all models
and persists across sessions. A **per-provider translation and clamp layer** downgrades unsupported tiers
to the nearest supported one with a one-time warning — so effort is *advisory*, not guaranteed, per model.

Headless application requires writing `model.reasoningEffort` into a settings.json the run will read
(opencode's pattern), not a CLI argument.

### Parser-level mutual exclusions — each is `exit 1` + help dump

From the `.check()` block, `config.ts:982-1027`:

- `--prompt` + positional query
- `--prompt` + `--prompt-interactive`
- **`--yolo` + `--approval-mode`** → *"Use --approval-mode=yolo instead."*
- `--continue` + `--resume`
- `--session-id` + (`--continue` | `--resume`)
- `--fork-session` without `--resume`/`--continue`
- `--include-partial-messages` without `-o stream-json`
- `--input-format stream-json` without `-o stream-json`

`.fail()` writes the message to stderr, dumps help, and `process.exit(1)`.

### Active deprecations at v0.21.5

| Deprecated | Replacement (verbatim) |
|---|---|
| `--prompt` / `-p` | *"Use the positional prompt instead. This flag will be removed in a future version."* |
| `--sandbox-image` | *"Use the `tools.sandboxImage` setting in settings.json instead."* |
| `--proxy` | *"Use the `proxy` setting in settings.json instead."* |
| `--telemetry*` (several) | corresponding `telemetry.*` settings |
| `--experimental-acp` | `--acp` |
| `--experimental-skills` | *"Skills are now enabled by default. This flag is ignored."* |

**Skills are ON by default.** `--safe-mode` is the lever that disables them (along with hooks,
extensions, MCP servers, context files); `--max-subagent-depth 1` disables sub-agent nesting.

### `--output-format json` shape and exit codes

Array of message objects, buffered until the session completes:

- `{ type: "system", subtype: "session_start", session_id: … }`
- `{ type: "assistant", message: { content: [ { type: "text", text: … } ] }, usage: {…} }`
- `{ type: "result", subtype: "success", usage: {…} }` — with `.stats.models`, `.stats.tools.totalCalls`

Exit codes: **0** success · **53** session-turn cap overrun · **55** budget exceeded (wall-time or
tool-calls) · **130** SIGINT.

`--fallback-model` names the capacity-error codes explicitly: **429 / 503 / 529**.

### `.env` discovery walks UP the directory tree (2026-08-04)

`findEnvFiles()` in `config/environment.ts` walks from cwd toward `$HOME`. **At each directory** it tries
`<dir>/.qwen/.env` first, then `<dir>/.env`. On reaching `$HOME` it pushes the home candidates:
`<QWEN_HOME|~/.qwen>/.env` → legacy `~/.qwen/.env` (only when `QWEN_HOME` redirects) → `~/.env`.

A commonly-repeated summary — `.qwen/.env → .env → ~/.qwen/.env → ~/.env` — is right **per directory**
and wrong about the search: it omits the parent walk. For a worker whose cwd is a git worktree inside a
repo, a `.env` at the repo root or any ancestor **is loaded**.

Two guards:

- **Workspace trust.** *"When workspace is untrusted, only allow user-level `.env` files"* —
  `~/.qwen/.env`, `~/.env`, `<QWEN_HOME>/.env`.
- **First-wins.** `!Object.hasOwn(process.env, key)` — an explicitly-exported variable is **never**
  overwritten by a `.env`. A planted file cannot hijack a passed key, but it *can* introduce variables
  the caller never passed (`QWEN_SANDBOX=false`, `OPENAI_BASE_URL`, `QWEN_TLS_INSECURE`).

Combined with the `QWEN_SANDBOX`-beats-`--sandbox` precedence above: **a planted ancestor `.env` can
silently disable the sandbox.**

Also: `DEBUG` / `DEBUG_MODE` are auto-excluded from *project* `.env` files (configurable via
`advanced.excludedEnvVars`); variables from `.qwen/.env` are **never** excluded even if listed.

### `QWEN_HOME` is the config-isolation lever (2026-08-04)

`QWEN_HOME` (with `QWEN_RUNTIME_DIR`) relocates *"settings.json, OAuth tokens, installation_id"* and is
pre-resolved in a bootstrap pass before the regular `.env` load. It is the direct analogue of
`CLAUDE_CONFIG_DIR`.

It carries a second behaviour a bare `HOME` redirect does not:

```ts
// When QWEN_HOME is set, skip ~/.env to avoid surprise cross-contamination
// from a shared home .env
if (!process.env['QWEN_HOME']) { candidates.push(path.join(path.dirname(globalQwenDir), '.env')); }
```

Setting `QWEN_HOME` **removes `~/.env` from the discovery set entirely**. `HOME=<scratch>` only points
the same lookups at an empty directory. Set both.

### YOLO safety warning (2026-08-04)

`utils/headlessSafetyWarnings.ts`:

```
'Warning: running headless with --yolo / approval-mode=yolo and no sandbox. …
 Enable a sandbox via --sandbox / QWEN_SANDBOX, or set
 QWEN_CODE_SUPPRESS_YOLO_WARNING=1 to silence this notice.'
```

Fires only when approval mode is `yolo` **and** `SANDBOX` is empty **and** the run is non-interactive.
Suppress with `QWEN_CODE_SUPPRESS_YOLO_WARNING=1`.

### Alibaba Bailian "Coding Plan" auth (2026-08-04)

Headless/scripted setup, first-party:

```bash
export BAILIAN_CODING_PLAN_API_KEY="sk-sp-xxxxxxxxx"
export OPENAI_BASE_URL="https://coding-intl.dashscope.aliyuncs.com/v1"   # international
# export OPENAI_BASE_URL="https://coding.dashscope.aliyuncs.com/v1"      # China (Beijing)
export OPENAI_MODEL="qwen3-coder-plus"
```

- The dedicated `coding[-intl].dashscope.aliyuncs.com` host is **required** — the standard DashScope
  endpoint does not serve Coding Plan quota.
- **Region mismatch yields a 401 that does not identify itself as a region error.**
- settings.json equivalent: `modelProviders.openai[].{protocol,id,baseUrl,envKey}` +
  `security.auth.selectedType: "openai"` + `model.name`. Manual model entries **disable auto-updates**
  of the model list.
- OAuth is browser-bound and cannot complete headless. Qwen OAuth was discontinued 2026-04-15.
- `AuthType` enum (`packages/core/src/core/contentGenerator.ts`):
  `openai` · `qwen-oauth` · `gemini` · `vertex-ai` · `anthropic`. **`anthropic` is a real auth path** —
  relevant to any reviewer-gate reasoning that assumes a backend can never resolve an Anthropic model.

**Coding Plan catalog per Alibaba's own Model Studio page (2026-08-04):**
`qwen3.7-plus`, `qwen3.6-plus`, `qwen3.5-plus`, `qwen3-max-2026-01-23`, `qwen3-coder-next`,
`qwen3-coder-plus`, `MiniMax-M2.5`, `glm-5`, `glm-4.7`, `kimi-k2.5`.
Thinking-capable: `qwen3.7-plus`, `qwen3.6-plus`, `qwen3.5-plus`, `glm-5`, `kimi-k2.5`.

**Qwen3.8-Max (announced 2026-08-03) is NOT yet in the Coding Plan catalog** — a concrete reason not to
hardcode a default tier map for this backend.

### Sources

- <https://github.com/QwenLM/qwen-code> (tag `v0.21.5`) — all source citations above
- <https://registry.npmjs.org/@qwen-code/qwen-code> — version/engine/bin metadata
- <https://qwenlm.github.io/qwen-code-docs/en/users/features/headless/>
- <https://qwenlm.github.io/qwen-code-docs/en/users/features/sandbox/> — ⚠️ contradicts source on `--sandbox`
- <https://qwenlm.github.io/qwen-code-docs/en/users/configuration/auth/>
- <https://qwenlm.github.io/qwen-code-docs/en/users/configuration/settings/>
- <https://qwenlm.github.io/qwen-code-docs/en/design/2026-06-30-unified-reasoning-effort-cli/>
- <https://help.aliyun.com/en/model-studio/qwen-code>
- Full audit: `docs/superpowers/library-audit/2026-08-04-qwen-code-cli-backend.md`
