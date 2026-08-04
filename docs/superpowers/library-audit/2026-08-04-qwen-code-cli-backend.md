# Library Audit — Qwen Code CLI backend (Phase 1C)

**Date:** 2026-08-04
**Spec:** `docs/superpowers/specs/2026-08-04-qwen-code-cli-backend-design.md`
**Recon:** `docs/superpowers/recon/2026-08-04-qwen-code-cli-backend-adapter.md`
**Scope:** library currency + API/flag signatures only. Code reality = Phase 1A; domain/ToS = Phase 1B.

> **Verification basis.** The spec was written from prose docs. This audit adds a third source the
> spec did not use: **the actual `yargs` option table in the released source at tag `v0.21.5`**
> (`packages/cli/src/config/config.ts`, `config/sandboxConfig.ts`, `config/environment.ts`,
> `utils/sandbox.ts`, `utils/headlessSafetyWarnings.ts`). Where the published docs and the source
> disagree, **the source is treated as authoritative and the disagreement is itself reported as a
> finding.** This is not a live-binary probe — the spec's requirement for one still stands.

---

## 1. Tools Available

| Tool | Status | Notes |
|---|---|---|
| Context7 MCP | ✅ | Two indexed libraries: `/qwenlm/qwen-code` (10,959 snippets, High reputation) and `/websites/qwenlm_github_io_qwen-code-docs_en` (5,720 snippets). Used for sandbox + auth lookups. |
| WebFetch (primary docs) | ✅ | `qwenlm.github.io/qwen-code-docs` reachable. `github.com/…/blob/…` returns 403/404 — use `raw.githubusercontent.com` or `gh api` instead. |
| GitHub API (`gh`) | ✅ | Repo metadata, releases, commits, code search, git trees. |
| npm registry | ✅ | `registry.npmjs.org` direct (npmjs.com HTML is 403 to WebFetch). |
| Released source at `v0.21.5` | ✅ | Ground truth for every flag claim below. |

**Repo dependency manifests: none.** No `package.json`, `pyproject.toml`, `go.mod`, or lockfile exists
in this repository — Compound V is a Claude Code plugin (`.claude-plugin/plugin.json`, v2.18.0) that
shells out to external CLIs. **Qwen Code is therefore an unpinned runtime dependency**, exactly like
`codex`, `cursor-agent`, and `agy`. There is no lockfile that can pin it. See CONSTRAINT-8.

No existing `qwen` reference anywhere in the repo outside `docs/superpowers/` — this is genuinely new
surface.

---

## 2. Libraries Mentioned

| Name | Spec context | Current stable | Repo pinned | Last release | Maintenance | Status |
|---|---|---|---|---|---|---|
| `@qwen-code/qwen-code` (`qwen`) | The entire backend | **0.21.5** | none (external CLI, no manifest) | **2026-08-04** (today, ~6h before this audit) | 26,646★, Apache-2.0, not archived, `pushed_at` 2026-08-04T08:57Z, 567 published versions, nightly channel daily | 🟢 **OK** — but see 🟠 H-5 on velocity |
| `@qwen-code/qwen-code-core` | transitive | tracks CLI | n/a | 2026-08-04 | same repo | 🟢 OK |
| Node.js runtime | unmentioned by spec | `engines: {node: ">=22.0.0"}` | not asserted anywhere | — | — | 🟡 M-5 |
| Alibaba Bailian / DashScope Coding Plan API | auth target | OpenAI-compatible `/v1` | n/a | — | first-party docs current | 🟢 OK |

**Release cadence, measured:** stable `v0.21.1` (2026-07-28) → `v0.21.2` (07-31) → `v0.21.3` (08-01) →
`v0.21.4` (08-03) → `v0.21.5` (08-04). Five stable releases in seven days, plus a nightly every day and
a weekly `preview` tag. Recent commits touch CLI, core, web-shell, and desktop.

**Verdict on the recon's abandonment question: emphatically NOT abandoned.** The project is one of the
most actively developed CLIs in this repo's backend roster. The currency risk here is the *opposite* of
staleness — it is **churn**.

---

## 3. API Signatures Verified

Every row checked against the `yargs` option table at tag `v0.21.5`.

### 3.1 Spec claims that hold ✅

| Spec claim | Verdict | Evidence |
|---|---|---|
| `qwen -p "<prompt>"` runs headless | ✅ works | `.option('prompt', {alias: 'p', type: 'string'})` — **but deprecated, see C-4** |
| `-o text` / `--output-format text\|json\|stream-json` | ✅ exact | `.option('output-format', {alias: 'o', choices: ['text','json','stream-json']})` |
| `--continue` resumes latest project session | ✅ exact | `.option('continue', {alias: 'c', type: 'boolean'})` — "Resume the most recent session for the current project." |
| `--resume <session-id>` resumes a specific session | ✅ exact | `.option('resume', {alias: 'r', type: 'string'})` — but see M-4 |
| `--yolo` / `--approval-mode=yolo` auto-approve | ✅ both exist | `.option('yolo', {alias:'y', type:'boolean'})`; `approval-mode` `choices: ['plan','default','auto-edit','auto','yolo']` — **but mutually exclusive, see C-3** |
| `--yolo` does **not** imply a sandbox | ✅ confirmed | `getHeadlessYoloSafetyWarning()` exists precisely because they are independent |
| `QWEN_CODE_SUPPRESS_YOLO_WARNING=1` silences the warning | ✅ exact | `utils/headlessSafetyWarnings.ts:44` — `isTruthyEnv(env['QWEN_CODE_SUPPRESS_YOLO_WARNING'])` |
| `SANDBOX_FLAGS` injects container flags | ✅ exact | `utils/sandbox.ts:445` |
| `BAILIAN_CODING_PLAN_API_KEY` is the Coding Plan key var | ✅ exact | Qwen auth docs + Alibaba Model Studio help page, both first-party |
| `OPENAI_BASE_URL` intl = `https://coding-intl.dashscope.aliyuncs.com/v1` | ✅ exact | first-party auth doc |
| `OPENAI_BASE_URL` China = `https://coding.dashscope.aliyuncs.com/v1` | ✅ exact | first-party auth doc + `help.aliyun.com` |
| OAuth cannot work headless; Coding Plan / API key can | ✅ confirmed | first-party auth doc |
| **No `--effort`/`--reasoning` CLI flag for headless mode** | ✅ **CONFIRMED** | Exhaustive enumeration of every `.option(` call in `config.ts` at v0.21.5: zero `effort`, `reasoning`, or `thinking` options. **The spec's claim #5 is correct.** Settings-file path `model.reasoningEffort` + interactive `/effort` are the only surfaces. |
| Coding Plan is a multi-vendor catalog behind one key | ✅ confirmed, and larger than stated | see M-6 |
| Apache-2.0, fork of Gemini CLI | ✅ | `license.spdx_id = Apache-2.0` on the repo |

### 3.2 Spec claims that are WRONG ❌

| Spec claim | Reality at v0.21.5 | Finding |
|---|---|---|
| `--sandbox <profile>` takes a Seatbelt profile name | `.option('sandbox', {alias:'s', type:` **`'boolean'`** `})`. Profiles come from `SEATBELT_PROFILE`; providers from `QWEN_SANDBOX`. | 🔴 C-1 |
| CLI `--sandbox` outranks the env var | Source comment: *"note environment variable takes precedence over argument (from command line or settings)"* — **`QWEN_SANDBOX` beats `--sandbox`.** The published doc claims the reverse. | 🔴 C-1 |
| 5 Seatbelt profiles | **6** — `restrictive-proxied` is missing from the spec | 🟡 M-1 |
| `effort` accepts `low\|medium\|high` | Qwen's ladder is **`low\|medium\|high\|xhigh\|max`** — it *does* support `xhigh` natively | 🟡 M-2 |
| `.env` order `.qwen/.env → .env → ~/.qwen/.env → ~/.env` | Correct **per directory**, but omits the **upward parent-directory walk** from cwd to `$HOME` | 🟠 H-3 |
| `HOME=<scratch>` is the config-isolation lever | `QWEN_HOME` is the purpose-built one, and it additionally suppresses `~/.env` | 🟠 H-2 |

### 3.3 Flags the spec never knew existed (all verified at v0.21.5)

| Flag | Signature | Why it matters here |
|---|---|---|
| `--core-tools <list>` | `array`, comma-or-repeat | **Actual** tool allowlist |
| `--exclude-tools <list>` | `array`, comma-or-repeat | **Actual** tool denylist — the read-only enforcement lever |
| `--allowed-tools <list>` | `array` — *"Tools that are allowed to run without confirmation"* | ⚠️ **confirmation bypass, NOT restriction** |
| `--session-id <id>` | `string` — "Specify a session ID for this run" | **Caller can assign the id instead of parsing it out** |
| `--fork-session` | `boolean`, requires `--resume`/`--continue` | branch a session |
| `--max-wall-time <dur>` | `90`/`30s`/`5m`/`1h`/`1.5h`; **aborts with exit code 55** | native wall-clock budget |
| `--max-tool-calls <n>` | `0` = no tool calls at all; **exit code 55** | `0` is a hard read-only-ish lever |
| `--max-session-turns <n>` | integer cap | runaway guard |
| `--max-subagent-depth <n>` | `1` disables nesting; default 5 | answers recon F11 |
| `--safe-mode` | disables *"context files, hooks, extensions, skills, MCP servers"* | answers recon F11 |
| `--bare` | *"skip implicit startup auto-discovery; only honor explicitly provided CLI inputs"* | hermetic worker mode — **different meaning from Claude Code's `--bare`** |
| `--fallback-model <m,…>` | up to 3, for **429/503/529** | names the exact capacity codes |
| `--json-schema <json\|@file>` | headless-only; registers a synthetic `structured_output` tool; session ends on first valid call | pin `job_result` at the source |
| `--worktree <slug>` | starts session in `<repoRoot>/.qwen/worktrees/<slug>/`; **"On exit, the WorktreeExitDialog prompts to keep or remove"** | ⚠️ collides with Compound V's own worktree |
| `--auth-type <t>` | `openai\|qwen-oauth\|gemini\|vertex-ai\|anthropic` | pin auth deterministically |
| `--openai-api-key`, `--openai-base-url` | `string` | ⚠️ key in argv — visible to `ps` |
| `--insecure` | sets `QWEN_TLS_INSECURE=1` | must never be emitted |
| `--include-directories` / `--add-dir` | `array` — *additional* workspace dirs | **not** a cwd setter |
| `--chat-recording` | if false, `--continue`/`--resume` stop working | resume precondition |

### 3.4 Parser-level mutual exclusions (each is `exit 1` + help dump)

Verified in the `.check()` block, `config.ts:982-1027`:

- `--prompt` + positional query → *"Cannot use both a positional prompt and the --prompt (-p) flag together"*
- `--prompt` + `--prompt-interactive`
- **`--yolo` + `--approval-mode`** → *"Cannot use both --yolo (-y) and --approval-mode together. Use --approval-mode=yolo instead."*
- `--continue` + `--resume`
- `--session-id` + (`--continue` | `--resume`)
- `--fork-session` without `--resume`/`--continue`
- `--include-partial-messages` without `--output-format stream-json`
- `--input-format stream-json` without `--output-format stream-json`

### 3.5 Deprecations already live at v0.21.5

| Deprecated | Replacement (verbatim) |
|---|---|
| `--prompt` / `-p` | *"Use the positional prompt instead. This flag will be removed in a future version."* |
| `--sandbox-image` | *"Use the `tools.sandboxImage` setting in settings.json instead."* |
| `--proxy` | *"Use the `proxy` setting in settings.json instead."* |
| `--experimental-acp` | use `--acp` |
| `--experimental-skills` | *"Skills are now enabled by default. This flag is ignored."* |

### 3.6 Exit codes and JSON shape

`--output-format json` emits **an array of message objects**, buffered until the session ends:
`type: "system"` (`subtype: "session_start"`, carries `session_id`) · `type: "assistant"`
(`message.content[]` of `{type:"text", text:…}`, plus `usage`) · `type: "result"`
(`subtype: "success"`, `usage`, `.stats.models`, `.stats.tools.totalCalls`).

Exit codes: **0** success · **53** session-turn cap overrun · **55** budget exceeded (wall-time /
tool-calls) · **130** SIGINT.

`SANDBOX` env var is set *by the sandbox transport itself* — `sandbox-exec` on macOS Seatbelt, the
container name (e.g. `qwen-code-sandbox`) under Docker/Podman. Any non-empty value means "inside a
sandbox". It is a **verifiable post-hoc assertion that sandboxing actually engaged.**

---

## 4. Critical Findings 🔴

### C-1 — `--sandbox` is a boolean, and `QWEN_SANDBOX` **overrides** it

The spec's pinned invocation contains `[--sandbox <profile> --sandbox-image <image-if-linux>]`. Three
separate errors:

1. **`--sandbox` takes no profile.** `.option('sandbox', {alias: 's', type: 'boolean', description: 'Run in sandbox?'})`.
2. **Profiles are not selected by any flag.** `SEATBELT_PROFILE` env var only, defaulting to
   `permissive-open` (`utils/sandbox.ts:225` — `process.env['SEATBELT_PROFILE'] ??= 'permissive-open'`).
   The six valid names are in `BUILTIN_SEATBELT_PROFILES` (`utils/sandbox.ts:60-67`).
3. **The env var wins over the flag.** From `config/sandboxConfig.ts`:

   ```ts
   // note environment variable takes precedence over argument (from command line or settings)
   const environmentConfiguredSandbox = process.env['QWEN_SANDBOX']?.toLowerCase().trim() ?? '';
   sandbox = environmentConfiguredSandbox?.length > 0 ? environmentConfiguredSandbox : sandbox;
   ```

**The published documentation states the opposite** — the sandbox docs page asserts
`qwen --sandbox=docker|podman|sandbox-exec` and a precedence of *"CLI flag > environment variable >
settings.json"*. Both claims are contradicted by the source at the same tag. **A doc-only verification
pass on this tool produces a wrong sandbox configuration.** This is the same class of defect that broke
`zai`'s first draft, and it landed in exactly the security-relevant flag.

Two further behaviours from `getSandboxCommand()`:

- If `process.env['SANDBOX']` is already set, sandboxing is **silently skipped** (`return ''`) — the
  process believes it is already contained. An `env -i` allow-list that leaks `SANDBOX` disables the
  sandbox with no error.
- On macOS the provider resolution is `if (os.platform() === 'darwin' && commandExists.sync('sandbox-exec')) return 'sandbox-exec';`
  — this fires **before** the docker/podman branches, so on a Mac an enabled sandbox is always Seatbelt
  unless `QWEN_SANDBOX=docker` is set explicitly.

**Fix:** drive sandboxing entirely through the environment —
`QWEN_SANDBOX=sandbox-exec` (macOS) or `docker`/`podman` (Linux), plus an explicit
`SEATBELT_PROFILE=<one of the six>`, plus `QWEN_SANDBOX_IMAGE` instead of the deprecated
`--sandbox-image`. Assert `SANDBOX` is non-empty inside the run to prove it engaged.

Sources: <https://github.com/QwenLM/qwen-code/blob/v0.21.5/packages/cli/src/config/sandboxConfig.ts>,
<https://github.com/QwenLM/qwen-code/blob/v0.21.5/packages/cli/src/utils/sandbox.ts>,
<https://qwenlm.github.io/qwen-code-docs/en/users/features/sandbox/>

---

### C-2 — `--allowed-tools` bypasses confirmation; it does **not** restrict tools

```ts
.option('allowed-tools', { type: 'array', string: true,
  description: 'Tools to allow, will bypass confirmation' })
```

This is the **identical trap** already recorded in this knowledge base for Claude Code's
`--allowedTools` (see `_knowledge-base/claude-code-cli-flags.md`, 2026-07-31) — the flag whose
misreading shipped in `zai`'s first draft. Qwen Code inherits it from the Gemini CLI lineage, and it is
registered **twice** in the same command (`config.ts:769` and `config.ts:950`), with slightly different
help text, which makes a docs-only reading even more likely to land on the wrong one.

The genuine restriction levers are `--core-tools <list>` (allowlist) and `--exclude-tools <list>`
(denylist). Additionally `--max-tool-calls 0` aborts the run on the first tool call of any kind.

**Impact on the spec:** §"New this PR" promises a *"read-only `qwen` consult … no write tools
regardless"* for advisor mode, and the job contract says `read_only` is *"enforced post-hoc the same way
as every other adapter."* Post-hoc git enforcement is fine as a backstop, but the spec never names a
pre-hoc mechanism — and the flag whose name most invites selection is the wrong one. Advisor consults
must use `--exclude-tools` (or `--core-tools`), never `--allowed-tools`.

Source: <https://github.com/QwenLM/qwen-code/blob/v0.21.5/packages/cli/src/config/config.ts>

---

### C-3 — `--yolo` and `--approval-mode` together are a hard parse error

```ts
if (argv['yolo'] && argv['approvalMode']) {
  return 'Cannot use both --yolo (-y) and --approval-mode together. Use --approval-mode=yolo instead.';
}
```

`.fail()` writes to stderr, dumps help, and `process.exit(1)`.

The spec writes *"`--yolo` (or `--approval-mode=yolo`)"* — correct as a description of alternatives, but
the pinned invocation hardcodes `--yolo` while the design elsewhere contemplates approval-mode
overrides. Any code path that composes both (e.g. a `plan`-mode advisor consult layered on the standard
worker argv) fails before the model is ever contacted, and the failure looks like a CLI-not-found error
rather than an argv bug.

**Fix:** pick one. `--approval-mode` is strictly more expressive (`plan` mode is directly useful for a
read-only advisor consult); emit `--approval-mode=yolo` for workers and `--approval-mode=plan` for
advisors, and never emit `--yolo`.

---

### C-4 — `-p` / `--prompt` is deprecated

```ts
.deprecateOption('prompt', 'Use the positional prompt instead. This flag will be removed in a future version.')
```

The positional form is `qwen "<prompt>"` — `.positional('query', { description: 'Positional prompt.
Defaults to one-shot; use -i/--prompt-interactive for interactive.' })`. Note that the positional
**already defaults to one-shot**, so `-p` buys nothing.

`-p` still functions at v0.21.5 and emits a deprecation notice. But the spec pins `qwen -p` as the
adapter's identity — *"a Bash-spawned `qwen -p` process — Qwen Code's own native headless mode"* — and
given this project's release cadence (§2), "a future version" is plausibly weeks away. A deprecation
notice on stderr also pollutes output that `compound-v-classify-failure.py` will be parsing.

**Fix:** use the positional prompt. Retain `-p` only if a live probe shows the positional form behaves
differently under `--output-format json`. Note `--prompt` + positional together is also a parse error
(§3.4), so this is a swap, not an addition.

---

## 5. High-Priority Findings 🟠

### H-1 — There is no `--cd`/`--dir` flag. Resolved. And `--worktree` is a trap.

The spec's open question *"Whether `qwen` has a `--cd`/`--dir`-equivalent flag or needs a subshell `cd`
like cursor/zai"* — **answered: no such flag exists.** Exhaustive enumeration of the `yargs` option
table at v0.21.5 shows no `cd`, `dir`, `workspace`, `project`, or `-C` option. `--include-directories`
(alias `--add-dir`) adds *additional* directories to the workspace; it does not change cwd.

**The worker must `cd` into the worktree in a subshell, exactly like `cursor` and `zai`.**

More important: **`--worktree` exists and must never be used.**

```
'Start the session inside a git worktree at <repoRoot>/.qwen/worktrees/<slug>/. …
 On exit, the WorktreeExitDialog prompts to keep or remove the worktree.'
```

Qwen Code ships its own git-worktree manager that creates worktrees at a path Compound V does not
control, and **prompts interactively on exit** — a guaranteed hang or spurious failure in a headless
worker, and a second worktree layered under the orchestrator's own. The name is close enough to this
adapter's `isolation: worktree` invariant that an implementer could plausibly reach for it.

---

### H-2 — `QWEN_HOME` is the correct isolation lever, not `HOME=<scratch>`

The spec proposes `env -i … HOME=<scratch>`, reasoning by analogy from `zai`'s `CLAUDE_CONFIG_DIR`
redirect. Qwen Code has a **direct** analogue: `QWEN_HOME`, plus `QWEN_RUNTIME_DIR`. From
`config/environment.ts`, `QWEN_HOME` relocates *"settings.json, OAuth tokens, installation_id"* and is
pre-resolved in a bootstrap pass before the regular `.env` load.

It also carries a second, load-bearing behaviour the `HOME` trick does not:

```
// When QWEN_HOME is set, skip ~/.env to avoid surprise cross-contamination
// from a shared home .env
if (!process.env['QWEN_HOME']) { candidates.push(path.join(path.dirname(globalQwenDir), '.env')); }
```

Setting `QWEN_HOME` **removes `~/.env` from the discovery set entirely.** `HOME=<scratch>` merely points
the same lookups at an empty directory — equivalent only as long as nothing else in the process
resolves the real home. Use `QWEN_HOME=<scratch>` **and** `HOME=<scratch>`, not `HOME` alone.

---

### H-3 — `.env` discovery walks **up** the directory tree

The spec's order `.qwen/.env → .env → ~/.qwen/.env → ~/.env` is right for one directory level and wrong
about the search. `findEnvFiles()` walks from cwd toward `$HOME`, and **at each directory** tries
`<dir>/.qwen/.env` then `<dir>/.env`, before falling back to the home candidates.

For a worker whose cwd is a git worktree **inside the repo**, this means a `.env` at the repo root — or
at any ancestor directory — is discovered and loaded into the worker's environment. That is a
configuration- and credential-injection surface the spec does not account for, and it is reachable by
any job that can write a file one level up (which the scope gate detects only *after* the run).

Two mitigations exist in-tree and should be used deliberately rather than relied on by accident:

- **Workspace trust.** *"When workspace is untrusted, only allow user-level `.env` files."* Depends on
  the trust configuration resolving as expected under `env -i` — needs live confirmation.
- **First-wins.** Values already present in `process.env` are never overwritten
  (`!Object.hasOwn(process.env, key)`). So an explicitly-passed `BAILIAN_CODING_PLAN_API_KEY` **cannot**
  be hijacked by a planted `.env`. Good — but a planted `.env` can still introduce variables the
  orchestrator did not pass at all (`QWEN_SANDBOX=false`, `OPENAI_BASE_URL`, `QWEN_TLS_INSECURE`).

Combined with C-1's finding that `QWEN_SANDBOX` outranks `--sandbox`, **a planted `.env` in an ancestor
directory can silently disable the sandbox.** Treat `--safe-mode` / `--bare` and an explicit
`advanced.excludedEnvVars` as candidate mitigations, and pin them during live verification.

---

### H-4 — The default Seatbelt profile is the weakest one, and it is network-open

`process.env['SEATBELT_PROFILE'] ??= 'permissive-open'`. If the adapter enables sandboxing without
naming a profile, it gets **permissive** (writes broadly allowed) and **open** (network unrestricted).

The spec's job contract says `network` *"maps to whether the container/Seatbelt profile permits network
access when `--sandbox` is engaged."* That mapping has to be built explicitly: `network: false` must
resolve to a `*-closed` (or `*-proxied`) profile. Nothing about enabling the sandbox restricts network
by default. Compare `codex`, where the adapter passes
`-c sandbox_workspace_write.network_access=false` explicitly.

---

### H-5 — Release velocity, not staleness, is the currency risk

Five stable releases in seven days; a nightly every day; `v0.21.5` shipped ~6 hours before this audit.
The v0.21.5 notes say "No known breaking changes," but the same release stream has already produced
five active deprecations (§3.5), one of which (`--prompt`) is the spec's central flag.

An adapter that hardcodes an argv against "current docs" will drift within weeks. Every other backend in
this repo has the same exposure, but none of them moves this fast.

**Required:** pin and record the verified version (`qwen --version`) in `adapter-qwen.md` the way
`codex-cli 0.144.1` is recorded, and treat a version bump as a trigger to re-run the flag verification —
not as a routine upgrade.

---

### H-6 — `--auth-type anthropic` exists, weakening one CR5-5 argument

`AuthType` at v0.21.5 is `openai | qwen-oauth | gemini | vertex-ai | anthropic`
(`packages/core/src/core/contentGenerator.ts:56-62`).

The spec argues: *"`zai`/`opencode`/`devin` additionally get an explicit backend-name block because
their own model resolution can produce an 'opus'-substring string … `qwen`'s model names never do, so it
rides the universal CR5-5 check alone."*

The premise holds **only** under the spec's own Non-goal ("No OpenRouter/BYOK/custom-provider auth paths
… scoped strictly to the Alibaba Coding Plan"). The binary itself accepts `--auth-type anthropic`, and
`OPENAI_BASE_URL`/`--openai-base-url` are freely settable. The safety of the CR5-5 gate for `qwen` rests
on a **scope decision**, not on a property of the tool. If the scope ever widens, `qwen` needs the same
explicit backend-name block `zai` and `opencode` already have.

Cheap hardening available now: pin `--auth-type openai` in the worker argv, so the auth path is
asserted rather than inherited from config discovery.

---

## 6. Medium Findings 🟡

**M-1 — Six Seatbelt profiles, not five.** `BUILTIN_SEATBELT_PROFILES` = `permissive-open`,
`permissive-closed`, `permissive-proxied`, `restrictive-open`, `restrictive-closed`,
**`restrictive-proxied`**. The spec omits `restrictive-proxied` — plausibly the most useful one for a
network-controlled worker.

**M-2 — The effort ladder is five tiers and includes `xhigh`.** `model.reasoningEffort` accepts
`low | medium | high | xhigh | max`. The spec says *"`effort` accepts `low|medium|high`, never `xhigh`
(project-wide: `xhigh` is codex-only)"*. The restriction is sound as **project policy**, but the spec
phrases it as though it describes Qwen — it does not. Qwen supports `xhigh` natively, and `max` is not
mentioned at all. Document it as a policy clamp so a future reader does not "fix" a non-bug. Note also
that Qwen applies its own *"per-provider translation and clamp layer"* — an effort value can be silently
downgraded per model, so `effort` is advisory on this backend.

**M-3 — `--sandbox-image` is deprecated** → `tools.sandboxImage` in settings.json (or
`QWEN_SANDBOX_IMAGE`). The spec's invocation uses the deprecated flag.

**M-4 — `--resume` with no id opens an interactive session picker.** *"Use without an ID to show session
picker."* Since `--resume` is `type: 'string'`, a shell-expansion accident that drops the id yields a
hang, not an error. The worker must never emit a bare `--resume`. **Better: `--session-id <id>` lets the
caller *assign* the id** — which makes the spec's unverified-`--resume`-id-shape question (recon F10)
moot for new sessions. Also note `--chat-recording false` disables resume entirely.

**M-5 — Node `>=22.0.0` is required** and asserted nowhere in the spec, `/v:init`, or the acceptance
criteria. `codex`/`cursor-agent` ship as binaries; `qwen` is an npm package with a hard engine floor. A
machine on Node 20 gets an install-time or runtime failure that will not classify as a quota error.

**M-6 — Model catalog is wider than the spec lists, and already drifting.** Alibaba's own Model Studio
page (2026-08-04) lists: `qwen3.7-plus`, `qwen3.6-plus`, `qwen3.5-plus`, `qwen3-max-2026-01-23`,
`qwen3-coder-next`, `qwen3-coder-plus`, `MiniMax-M2.5`, `glm-5`, `glm-4.7`, `kimi-k2.5`. The spec omits
`glm-4.7`, `qwen3-coder-next`, and `qwen3-max-2026-01-23`. **Qwen3.8-Max (launched 2026-08-03) is not
yet in the Coding Plan catalog** — which vindicates the spec's explicit decision not to hardcode a
default tier map. Keep that decision; resolve via `/v:models` against a live key.

**M-7 — The npm package publishes no `license` field.** The repo is Apache-2.0 (`license.spdx_id`), but
`registry.npmjs.org/@qwen-code/qwen-code/0.21.5` has no `license` key, so automated license scanners
will report "unknown". Cosmetic, but worth knowing before it surfaces in a compliance check.

---

## 7. Design Constraints for the Plan

Non-negotiable, each traceable to a source citation above.

**MUST**

1. Drive sandboxing through **`QWEN_SANDBOX`** (`sandbox-exec` | `docker` | `podman`), not `--sandbox`.
   The env var wins regardless. (C-1)
2. Set **`SEATBELT_PROFILE`** explicitly whenever the sandbox is engaged on macOS. The default is
   `permissive-open`. (C-1, H-4)
3. Map `network: false` to a `*-closed` or `*-proxied` profile explicitly. Sandbox ≠ network
   restriction. (H-4)
4. Use **`--exclude-tools`** (or `--core-tools`) for read-only/advisor enforcement. Optionally
   `--max-tool-calls 0`. (C-2)
5. Emit **`--approval-mode=<mode>`** and never `--yolo` — they are mutually exclusive at parse time. (C-3)
6. Use the **positional prompt** (`qwen "<prompt>"`), not `-p`. (C-4)
7. **`cd` into the worktree in a subshell.** No cwd flag exists. (H-1)
8. Set **`QWEN_HOME=<scratch>`** in addition to `HOME=<scratch>`. (H-2)
9. Add **`SANDBOX`** to the `env -i` **deny** reasoning explicitly — a leaked `SANDBOX` silently disables
   sandboxing. After the run, assert `SANDBOX` was non-empty *inside* the process to prove containment.
   (C-1)
10. Pin **`--auth-type openai`** in the worker argv. (H-6)
11. Record the **exact verified version** (`qwen --version`) in `adapter-qwen.md`, as `codex-cli 0.144.1`
    is recorded, and re-verify flags on every version bump. (H-5)
12. Assert **Node >= 22.0.0** in `/v:init` capability detection. (M-5)
13. Use **`--session-id <id>`** to assign session ids on new sessions rather than parsing them back out.
    (M-4)
14. Wire exit codes **0 / 53 / 55 / 130** into `compound-v-classify-failure.py` — these are documented and
    deterministic, so the backend does **not** have to fail closed to `other` for the budget/interrupt
    classes. (§3.6)

**MUST NOT**

15. **Never pass `--worktree`.** It creates a second worktree at a path Compound V does not control and
    prompts interactively on exit. (H-1)
16. **Never pass `--allowed-tools`** believing it restricts tools. It only bypasses confirmation. (C-2)
17. **Never pass `--sandbox <profile>`** — it is a boolean. (C-1)
18. **Never pass `--openai-api-key` on the command line** — argv is world-readable via `ps`. Use the
    `BAILIAN_CODING_PLAN_API_KEY` env var. (§3.3)
19. **Never pass `--insecure`.** (§3.3)
20. **Never emit a bare `--resume`** with no id — it opens an interactive picker and hangs. (M-4)
21. **Never combine** `--prompt` with a positional, `--continue` with `--resume`, or `--session-id` with
    either — each is a parse-time `exit 1`. (§3.4)
22. **Do not describe the `xhigh` ban as a Qwen limitation.** It is Compound V policy; Qwen supports
    `xhigh` and `max`. (M-2)

**SHOULD (opportunities the spec missed — each removes work it planned to do)**

23. `--max-wall-time` / `--max-tool-calls` / `--max-session-turns` give **native** budget enforcement with
    a deterministic exit code 55, complementing `compound-v-run-with-timeout.py`.
24. `--fallback-model` documents the capacity codes **429/503/529** — real needles for
    `compound-v-classify-failure.py`, which the spec assumed had none. The "fail closed to `other`" gap is
    narrower than the spec claims.
25. `--json-schema` can pin the model's final output to a schema in headless mode — a first-party route to
    a well-formed `job_result` payload.
26. `--safe-mode` (disables skills, hooks, extensions, MCP servers) and `--max-subagent-depth 1` are
    concrete answers to recon **F11** ("Skills and SubAgents vs the planner/executor prompt lock") — the
    spec listed it as unresolved. Skills are **on by default** at v0.21.5 (`--experimental-skills` is
    deprecated as redundant), so this is a live concern, not hypothetical.
27. `--bare` ("skip implicit startup auto-discovery; only honor explicitly provided CLI inputs") is a
    hermeticity lever. **Its meaning differs from Claude Code's `--bare`**, which caps the tool set at
    `Bash, Edit, Read` — do not carry that assumption across.

---

## 8. Open Questions for the Human

These are scoping decisions this audit cannot make.

1. **Does `--sandbox` remain optional in v1 given C-1?** The spec made "no mandatory `--sandbox`" an
   explicit user decision. That decision was taken believing `--sandbox <profile>` worked as written. The
   real configuration is env-var-driven and its default profile is `permissive-open`. Re-confirm with the
   corrected facts — the choice may stand, but it should be re-taken knowingly.
2. **Does a planted ancestor `.env` count as an accepted risk?** (H-3) It can inject `QWEN_SANDBOX=false`
   and silently disable containment on a backend that is already lower-trust. Options: rely on workspace
   trust, add `--safe-mode`/`--bare`, or scrub ancestor `.env` files before dispatch. Materially affects
   the trust-tier claim.
3. **Advisor mode: `--approval-mode=plan` instead of yolo + post-hoc git check?** `plan` mode is
   first-party and produces no writes at all. Stronger than a scope gate that only detects afterward — but
   it changes what an advisor consult can observe (it cannot run tools to inspect the tree).
4. **International or China endpoint?** Both are documented and confirmed. Alibaba's own help page shows
   only `coding.dashscope.aliyuncs.com/v1` (Beijing). Region mismatch produces a 401 that does not
   identify itself as a region error — a failure mode worth an explicit config field rather than a default.
5. **Does the `qwen` advisor priority slot survive C-1?** The spec ranks `codex > qwen > (no-OS-guarantee
   tier)` on *"verified isolation strength"*, crediting qwen's *"optional kernel sandbox."* If v1 ships
   with the sandbox off (Q1), the ranking rests on a capability the adapter does not exercise. Either
   require the sandbox for the advisor path specifically, or move `qwen` down to the no-guarantee tier.
6. **Version pin policy for a CLI shipping ~daily?** (H-5) Pin an exact version and re-verify on bump, or
   track `latest` and accept drift? Everything in §7 is verified against **v0.21.5** and nothing else.

---

## 9. Knowledge Base Updates

- **Created** `docs/superpowers/library-audit/_knowledge-base/qwen-code-cli.md` — full verified flag
  table at v0.21.5, sandbox/env precedence, `.env` discovery, mutual exclusions, deprecations, exit codes,
  Coding Plan auth.
- **Appended** to `docs/superpowers/library-audit/_knowledge-base/claude-code-cli-flags.md` — a
  cross-tool section recording that the `allowedTools`-means-bypass-not-restrict trap is a **Gemini-CLI-lineage
  family trait**, now confirmed in a second tool, plus the `--bare` name collision.
- **Appended** to `docs/superpowers/library-audit/_knowledge-base/agent-instruction-tooling.md` — a
  reusable method note: for fast-moving CLIs, verify flags against the released **source** `yargs` table,
  not the docs site; this audit found the docs contradicting the source at the same tag on a
  security-relevant flag.

---

## Sources

- <https://github.com/QwenLM/qwen-code> — repo metadata via `gh api`, 2026-08-04: not archived, Apache-2.0, 26,646★, `pushed_at` 2026-08-04T08:57:57Z
- <https://github.com/QwenLM/qwen-code/releases/tag/v0.21.5> — published 2026-08-04T02:17:38Z
- <https://github.com/QwenLM/qwen-code/blob/v0.21.5/packages/cli/src/config/config.ts> — yargs option table, `.check()` exclusions, deprecations
- <https://github.com/QwenLM/qwen-code/blob/v0.21.5/packages/cli/src/config/sandboxConfig.ts> — `QWEN_SANDBOX` precedence over CLI flag
- <https://github.com/QwenLM/qwen-code/blob/v0.21.5/packages/cli/src/utils/sandbox.ts> — 6 Seatbelt profiles, `SEATBELT_PROFILE` default
- <https://github.com/QwenLM/qwen-code/blob/v0.21.5/packages/cli/src/config/environment.ts> — `.env` upward walk, `QWEN_HOME`, workspace trust
- <https://github.com/QwenLM/qwen-code/blob/v0.21.5/packages/cli/src/utils/headlessSafetyWarnings.ts> — `QWEN_CODE_SUPPRESS_YOLO_WARNING`
- <https://github.com/QwenLM/qwen-code/blob/v0.21.5/packages/core/src/core/contentGenerator.ts> — `AuthType` enum
- <https://registry.npmjs.org/@qwen-code/qwen-code> — 0.21.5, 567 versions, `engines.node >=22.0.0`, `bin.qwen`
- <https://qwenlm.github.io/qwen-code-docs/en/users/features/headless/> — headless flags, JSON shape, exit codes
- <https://qwenlm.github.io/qwen-code-docs/en/users/features/sandbox/> — sandbox docs (**contradicts source on `--sandbox` arity and precedence**)
- <https://qwenlm.github.io/qwen-code-docs/en/users/configuration/auth/> — Coding Plan headless setup, both endpoints
- <https://qwenlm.github.io/qwen-code-docs/en/users/configuration/settings/> — `.env` precedence, `model.reasoningEffort` values, `advanced.excludedEnvVars`
- <https://help.aliyun.com/en/model-studio/qwen-code> — Alibaba first-party Coding Plan model catalog
- <https://qwenlm.github.io/qwen-code-docs/en/design/2026-06-30-unified-reasoning-effort-cli/> — 5-tier effort ladder, `/effort` command
- Context7: `/qwenlm/qwen-code`, `/websites/qwenlm_github_io_qwen-code-docs_en`
