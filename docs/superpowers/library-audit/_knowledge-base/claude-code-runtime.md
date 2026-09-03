# Claude Code Runtime Library Knowledge Base

Maintained by Compound V Phase 1C validator. Append at the bottom.

Scope: Claude Code's own runtime contracts that Compound V builds on — the native `Workflow`
(`RunWorkflow`) runtime and the hooks contract. These are *not* third-party libraries and are not in
Context7; the authoritative source is the installed binary plus `code.claude.com/docs`.

---

## Updated 2026-09-01 — Compound V 3.0 (triage / scoped tests / native-Workflow orchestration)

Validated for [`docs/superpowers/preflight/2026-09-01-v3.0-1c-docs.md`](../../preflight/2026-09-01-v3.0-1c-docs.md).
Local Claude Code at time of audit: **`2.1.238`**.

**Sources.** `https://code.claude.com/docs/en/workflows.md` (fetched 2026-09-01) · verbatim string
extraction from `/Users/oleg/.local/share/claude/versions/2.1.238` · live `ToolSearch` probe from inside a
subagent.

**Reproduce the binary evidence:**

```bash
strings -a "$(readlink -f "$(which claude)")" > /tmp/cc-strings.txt
python3 -c "d=open('/tmp/cc-strings.txt',errors='replace').read(); \
  i=d.find('Every script must begin with'); print(d[i-6000:i+9500])"
```

### Native Workflow runtime

Internal tool name **`RunWorkflow`**; permission-rule name **`Workflow`**. Tool inputs:
`script` · `name` · `scriptPath` · `args` · `resumeFromRunId` (`^wf_[a-z0-9-]{6,}$`) · `remote`.
`scriptPath` takes precedence over `script` and `name`. Every invocation persists its script under the
session directory and returns the path.

Script body API (verbatim, 2026-09-01, v2.1.238):

```
agent(prompt, opts?: {label?, phase?, schema?, model?, effort?, isolation?: 'worktree', agentType?}): Promise<any>
pipeline(items, stage1, stage2, ...): Promise<any[]>
parallel(thunks: Array<() => Promise<any>>): Promise<any[]>
log(message): void ; phase(title): void
args: any
budget: {total: number|null, spent(): number, remaining(): number}
workflow(nameOrRef: string | {scriptPath}, args?): Promise<any>   // one level of nesting only
```

- **`pipeline` stage callbacks receive `(prevResult, originalItem, index)`.** No barrier between stages.
  **A stage that throws drops that item to `null` and skips its remaining stages** — so a throwing stage
  destroys every downstream record for that item.
- `parallel` is a barrier; a throwing thunk resolves to `null`, the call never rejects.
- `agent()` with `schema` forces a StructuredOutput tool call and returns the validated object. Returns
  `null` when skipped or terminally errored.
- `opts.effort`: `'low' | 'medium' | 'high' | 'xhigh' | 'max'`.
- `opts.isolation`: only `'worktree'` in this build; `'remote'` errors "not available in this build".
- **`opts.agentType` resolves from the same registry as the Agent tool** and composes with `schema`.
- `opts.phase` must be set per-agent inside pipeline/parallel stages — the global `phase()` races.
- **`budget.total` is a HARD ceiling when set** (from a user `+500k`-style directive); exceeding it makes
  `agent()` **throw**. `null` when unset — i.e. no default token cap.
- **Determinism ban:** `Date.now()`, `Math.random()`, and argless `new Date()` **throw** inside a script
  (they would break resume). Plain JavaScript only — no TypeScript syntax, no `import()`,
  **no filesystem or Node.js API access**.
- Agents spawned by the script **do** have full tools including Bash and session MCP tools (via ToolSearch).
  The sandbox applies to the *script*, not to its agents.
- Caps: concurrency `min(16, availableCPUs - 2)` per workflow; **1000** agents total per run; **4096** items
  per single `parallel()`/`pipeline()` call (explicit error, not silent truncation).
- Resume: `resumeFromRunId`, **same-session only**. Completed agents with unchanged `(prompt, opts)` return
  cached results; a failed agent and **every agent that started after it** re-run, including completed ones.
  Stop the prior run before resuming.
- Save locations for *named* workflows: `.claude/workflows/` (project, nearest-wins between cwd and repo
  root) and `~/.claude/workflows/` (personal). Plugins ship them under `workflows/`, namespaced
  `/<plugin>:<name>`.
- Disable / restrict: `disableWorkflows` (managed settings), `CLAUDE_CODE_DISABLE_WORKFLOWS=1`, and
  **`CLAUDE_CODE_WORKFLOWS`** which restricts a session to **named workflows only** — refusing `script`,
  `scriptPath`, `resumeFromRunId`, and `remote`.
- Other env: `CLAUDE_CODE_WORKFLOW_PREFIX_STAGGER_MS` (default `5000`),
  `CLAUDE_CODE_WORKFLOW_SIZE_WARNING_AGENTS` (default 25), `CLAUDE_CODE_WORKFLOW_SIZE_WARNING_TOKENS`
  (default 1.5M). The "Large workflow" warning is advisory and suppressed under ultracode.

**Correction to a widely-repeated belief (including our own 2026-09-01 recon):** workflows **can** be
launched under `claude -p` and the Agent SDK. What is not honored from `-p` / SDK / scheduled / webhook is
the **`ultracode` keyword opt-in**. Launch there succeeds via an allow rule `Workflow` / `Workflow(<name>)`,
auto permission mode, bypass mode, a `PreToolUse` hook returning `allow`, or `--permission-prompt-tool`.

**Observed but undocumented (2026-09-01):** a subagent has no Workflow tool. `ToolSearch
"select:Workflow,RunWorkflow"` from inside a subagent returns no match. No gating predicate or doc statement
was found; the only diagnostic is the generic *"org policy, launch gate, or the 'Dynamic workflows' setting
in /config"*. Treat as observed behaviour, not a contract.

### Stop hook contract

Stdin (zod schema recovered from the binary): `session_id`, `transcript_path`, `cwd`, `permission_mode`,
`effort.level`, `hook_event_name: "Stop"`, `stop_hook_active: boolean`, `last_assistant_message?: string`.
**`session_id` is present** — it is the correct key for "did this session already do X".

Output: `decision: "block"` (**not** `"continue"`/`"stop"` — see the confabulation note below) with `reason`
("Feedback for the model; the conversation continues so the model can act on it"), plus `systemMessage`,
`continue`, `stopReason`, `suppressOutput`, and `hookSpecificOutput.additionalContext`. Exit 2 blocks; the
blocking message is the JSON `reason` when present, stderr otherwise.

- **`CLAUDE_CODE_STOP_HOOK_BLOCK_CAP`, default `8`** — undocumented on the public hooks page. On the 9th
  **consecutive** block Claude Code overrides the hook and ends the turn with a warning. The counter is
  per-consecutive-run and resets when a Stop pass produces no blocking errors; `stop_hook_active` is
  therefore *not* a permanent per-session flag.
- Product guidance embedded in that warning: *"For Stop/SubagentStop hooks, check `stop_hook_active` in the
  input and return success while it's true."*
- **Multiple Stop hooks compose: all matching hooks run, and any one blocking wins** over any number exiting
  0. A separate `continue: false` path force-*ends* the turn (`reason: "stop_hook_prevented"`).

**Methodology note — WebFetch confabulated this contract.** A second `WebFetch` of the hooks page returned a
confident table claiming Stop's `decision` is `"continue" | "stop"`, after a first fetch of the same URL had
correctly reported the section truncated. The binary disproves it. **For Claude Code's own runtime, extract
from the installed binary; treat fetched summaries of truncated pages as unreliable.**

### Version floors (as of 2026-09-01)

| Capability | Floor |
|---|---|
| `/workflow-authoring` bundled skill | **v2.1.248** |
| `workflowSizeGuideline` setting | v2.1.219 |
| Symlink refusal on workflow save | v2.1.216 |
| `ultracode` keyword not honored from `-p`/SDK/scheduled/webhook | v2.1.210 |
| `claude --effort ultracode` | v2.1.203 |
| Save to nearest `.claude/workflows/` in a monorepo | v2.1.178 |

Recommended floor for anything built on the Workflow runtime: **`>= 2.1.219`**.

---

## Updated 2026-09-02 — preflight-workflow-probe

External runtime dependencies of this repo's bash+Python surface. No dependency manifest of any kind
exists in the tree (`PROBE` 2026-09-02: no `package.json`, `requirements.txt`, `pyproject.toml`,
`go.mod`, `Cargo.toml`, `Gemfile`, `composer.json`), so these are undeclared by construction.

### CPython

- **3.9 is EOL as of 2025-10-31**; **3.9.25** was the final security release. CVEs after that date
  have no upstream patch (RHEL 9 backports are the only distro safety net; macOS is not one).
  Sources: python.org release page for 3.9.25; Red Hat Developer, 2025-12-04.
- This repo's floor is **3.9** on purpose — stock-macOS `/usr/bin/python3` is **3.9.6**
  (`PROBE`), and `scripts/compound-v-scope-check.py:98` states the target. `CONVENTIONS.md`:
  stdlib only, no third-party runtime deps.
- **CI tests 3.9 and 3.12 only** (`.github/workflows/validate.yml:112,276,345`). **3.13 and 3.14 are
  untested**, yet `hooks/session-banner.sh:42` invokes bare `python3`, which on this machine is
  **3.14.7**. `hooks/postcompact-resume.sh:120-133` has a `_python` resolver; the banner does not —
  so one session can run the same script under two interpreters.
- `PROBE`: `compound-v-dashboard.py --selftest` **passes on both 3.9.6 and 3.14.7**.
- **Deprecated-and-scheduled-for-removal APIs still in use** (5 occurrences across `scripts/*.py`):
  `datetime.utcnow()` and `datetime.utcfromtimestamp()`, deprecated since **3.12**. In the dashboard:
  `:262` (`_iso()`, which produces the `display_ts` field exported by `resume --json`) and `:1180`.
  **No removal version has been announced upstream** — do not claim one. 3.9-safe replacement is
  `datetime.timezone.utc`; `datetime.UTC` is 3.11+ and would break the floor. Warnings are currently
  invisible because callers redirect `2>/dev/null`, so CI will not surface them either.

### jq

- **Current: 1.8.2, released 2026-06-20.** This machine: **1.7.1** at `/opt/homebrew/bin/jq`, plus a
  separate `/usr/bin/jq`. No minimum version is declared anywhere in the repo.
- Fixed since 1.7.1: **1.8.0** — CVE-2024-23337 (signed integer overflow in `jvp_array_write` /
  `jvp_object_rehash`; array/object size now capped at 2^29) and CVE-2024-53427 (NaN-with-payload
  accepted when parsing JSON). **1.8.1** — CVE-2025-49014 (heap use-after-free in `f_strftime` /
  `f_strflocaltime`; also reverted 1.8.0's `reduce`/`foreach` state change over a perf regression).
  The two parser fixes are the relevant ones: `hooks/postcompact-resume.sh:231` pipes the
  model-generated `compact_summary` through jq. No hook calls `strftime`.
- **Breaking change in 1.8.0:** binding syntax — `[-1 as $x | 1,$x]` now yields `[1,-1]` (was
  `[-1,-1]`). This repo's filters use `--arg` and simple field access; none are affected.
- **`jq` guard audit** (`PROBE` 2026-09-02, stub `jq` exiting 127 placed first on `PATH`):

  | Hook | `command -v jq` guards | jq uses | stdout on jq failure | exit |
  |---|---|---|---|---|
  | `hooks/session-banner.sh` | **0** | 3 | *(empty)* | **127** |
  | `hooks/plan-saved-nudge.sh` | **0** | 4 | — | — |
  | `hooks/postcompact-resume.sh` | 1 (`:145`) | 6 | *(empty)* | **0** |
  | `hooks/precompact-snapshot.sh` | 1 (`:128`) | 3 | — | — |
  | `hooks/triage-prompt-nudge.sh` | 1 (`:233`) | 7 | — | — |

  `session-banner.sh` runs `set -euo pipefail` (`:13`) with unguarded `jq -n` at `:50,52,55`, so a jq
  failure loses the **entire** banner, not just the JSON envelope. Since `SessionStart` accepts
  plain-text stdout as context (see `claude-code-hooks.md`), a jq-free fallback is available there.

---

## Updated 2026-09-02 — v3.4-native-first (epic resurrection tools)

Validated for [`docs/superpowers/library-audit/2026-09-02-v3-4-native-first.md`](../2026-09-02-v3-4-native-first.md).
Source: **live tool schemas fetched via `ToolSearch` from inside a Phase-1C subagent**, same session,
same machine as the 2026-09-02 CPython/jq entry above. Local Claude Code: `2.1.238`.

### `CronCreate` / `CronList` / `CronDelete` (live schema, verbatim)

```
CronCreate: {cron: string (5-field, local time), prompt: string,
             recurring?: boolean (default true), durable?: boolean (no effect — see below)}
CronList:   {}  — lists this session's jobs
CronDelete: {id: string} — cancels one of this session's jobs
```

- **Session-only, in-memory, no disk persistence.** *"Jobs live only in this Claude session — nothing
  is written to disk, and the job is gone when Claude exits."* `durable: true` has **no effect** — the
  tool description says so explicitly, in case a caller assumes the parameter does something.
- **Recurring jobs auto-expire after 7 days: "they fire one final time, then are deleted."** The tool's
  own guidance: *"Tell the user about the 7-day limit when scheduling recurring jobs."* This applies to
  any `/loop <interval> <cmd>` invocation whose interval mode is backed by `CronCreate` — confirmed by
  this audit to be a real, currently-live constraint, not a documentation artifact of an older build.
- **Jitter, not a fixed offset.** *"The scheduler adds a small deterministic jitter... recurring tasks
  fire up to 10% of their period late (max 15 min); one-shot tasks landing on :00/:30 fire up to 90s
  early."* Jobs additionally only fire while the REPL is idle (not mid-query).
- One-shot (`recurring: false`) jobs fire once at the next cron match, then auto-delete — the "remind
  me at X" shape, not the "keep resurrecting a marathon" shape.

### Subagent tool-surface visibility — a now three-times-reproduced pattern

| Tool | Visible via `ToolSearch` from inside a subagent? | First observed |
|---|---|---|
| `Workflow` / `RunWorkflow` | ❌ no match | 2026-09-01 1C audit, 🟠-4 |
| `CronCreate` / `CronList` / `CronDelete` | ✅ full schema returned | 2026-09-02, this entry |
| `ProposeGoal` | ❌ no match | 2026-09-02, this entry |
| `ScheduleWakeup` | ❌ no match | 2026-09-02, this entry |

Pattern: session-scoped interactive tools (dynamic workflow launch, goal-setting, dynamic self-pacing)
are not exposed to a spawned subagent; stateless session-store tools (the Cron trio) are. Treat any
future spec claim about `ProposeGoal` or `ScheduleWakeup`'s exact shape as requiring a **main-session**
live probe — a Phase 1C (or any other) subagent cannot independently confirm it, only cite prior
same-day evidence gathered elsewhere.

### `/loop` and `/schedule` skill descriptions (live, this session's own skill listing)

`/loop`: *"Run a prompt or slash command on a recurring interval (e.g. `/loop 5m /foo`). Omit the
interval to let the model self-pace."* — confirms the interval-mode/dynamic-mode split the spec assumes.

`/schedule`: *"Create, update, list, or run scheduled cloud agents (routines) that execute on a cron
schedule... Also use when the user wants a one-time scheduled run."* — confirms both the recurring-cloud
case and the one-time case; no session-lifetime coupling documented (unlike `/loop`/`CronCreate`).

---

## Updated 2026-09-03 — v3.4.1 triage-size (the `--tools` flag)

Validated for [`docs/superpowers/library-audit/2026-09-03-v3-4-1-triage-size.md`](../2026-09-03-v3-4-1-triage-size.md).
No Context7 attached to this subagent; no local Bash access to invoke `claude` directly either
(`bashCommandClamp` on this spawn allowed only the V-memory search script) — every claim below is
WebSearch/WebFetch-sourced and explicitly triangulated across independent origins because this KB
already has one recorded WebFetch-confabulation incident (the Stop-hook `decision` enum, above).

### `claude -p --tools ""` — a real, distinct flag from `--allowedTools`/`--disallowedTools`

Four independent sources, fetched/searched this session, converge:

1. `code.claude.com/docs/en/cli-reference.md` (raw .md, fetched twice with different prompts): both
   fetches independently reproduce the identical cross-reference sentence inside the `--allowedTools`
   entry — *"To restrict which tools are available, use `--tools` instead."* An identical specific
   sentence recurring across separately-prompted fetches of the same URL is the pattern this file's own
   Stop-hook incident treats as evidence a page really contains the text (that incident was a
   **second fetch contradicting the first**, not two fetches agreeing).
2. `backgroundclaude.com/cli-reference` (independent third-party origin, different rendering pipeline):
   full, un-hedged entry — **"`--tools` — Restrict which built-in tools Claude can use. Pass `""` to
   disable all, `"default"` for all, or a comma list."** Example: `claude --tools "Bash,Edit,Read"`.
3. `WebSearch` aggregate (separate retrieval path again): *"`--tools` is the flag you need [to actually
   restrict access] ... differs from `--allowedTools`, which only skips the confirmation prompt but does
   not limit what Claude can reach."*
4. The rendered (non-raw) `cli-reference` page independently, in a still-truncated excerpt, names the
   same flag under "Tool Configuration Flags" without giving its full body — consistent with, not
   contradicting, the other three.

**Verdict: real flag, `--tools ""` is the documented "disable every tool" value.** `--output-format text`
is separately confirmed as the plain documented default (`headless` page, fetched in full this session).

**Residual gap, recorded rather than hidden:** no session in this audit chain has independently *run*
`claude -p --tools "" ...` and observed the exit code / stdout / tool-use-attempt-count — the evidence
above is converged documentation, not a live invocation. Before a design leans on `--tools ""` as a
safety property (e.g. "the classify prompt has zero tool access, so it cannot do anything but answer"),
run the one real invocation first. See the source audit's §6/§7 for the specific constraint this produced.

---

## Updated 2026-09-03 — `worktree.baseRef` is a live, project-scoped native setting (v3.4.7 readme-clarity)

Validated for
[`docs/superpowers/library-audit/2026-09-03-v3-4-7-readme-clarity.md`](../2026-09-03-v3-4-7-readme-clarity.md).
No Context7 attached to this subagent (`bashCommandClamp` again allowed only the V-memory
script — same constraint as the 2026-09-03 triage-size entry above); sources are the live
`EnterWorktree` tool schema (first-party, this session) plus two `WebFetch`es of
`code.claude.com/docs/en/worktrees.md` and `.../settings.md`.

**This repo's own `.claude/settings.json` already sets `{"worktree":{"baseRef":"head"}}`.**
`scripts/compound-v-emit-workflow.py`'s `_worktree_base_is_head()` reads that exact key
from that exact file — **not** a coincidental name reuse. `worktree.baseRef` is a real,
currently-documented Claude Code project setting, confirmed two independent ways:

1. **`EnterWorktree`'s own live tool description**, verbatim: *"the base ref is governed
   by the `worktree.baseRef` setting: `fresh` (default) branches from
   `origin/<default-branch>`; `head` branches from your current local HEAD."*
2. **`code.claude.com/docs/en/worktrees.md`** §"Choose the base branch": same two values,
   plus the exact JSON example `{"worktree":{"baseRef":"head"}}` — byte-identical to what
   this repo's `.claude/settings.json` already contains and to what `commands/v-init.md`
   (per the v3.4.7 spec) will offer to write.

**Only two legal values — `"fresh"` and `"head"`.** No branch-name form; *"You can't set
`worktree.baseRef` to a branch name."*

**Scope is project-wide, not caller-scoped — the load-bearing nuance.** `.claude/settings.json`
is the **"Shared project"** tier (*"Everyone in the project"*, per the settings-precedence
table on `settings.md`). Setting `baseRef: head` therefore governs:

- Every interactive `claude --worktree <name>` session anyone runs in this repo.
- Every `isolation: worktree` custom subagent — confirmed verbatim: *"Subagent worktrees
  use the same base branch as `--worktree`, so they branch from your repository's default
  branch unless `worktree.baseRef` is set to `"head"`."* This is very likely the actual
  mechanism Compound V's own job dispatch rides on (`agent(... opts.isolation: 'worktree')`
  per this file's 2026-09-01 entry above) — the same setting key governs both the native
  tool's own worktrees and Compound V's job worktrees, deliberately or not.
- The `"fresh"` default's own auto-refresh safety property is what a `"head"` project
  gives up: *"For a 'fresh' base, Claude Code keeps `origin/HEAD` current: when the
  repository hasn't been fetched in the last 24 hours, it fetches the default branch,
  capped at five seconds... Before v2.1.208, a fresh worktree used whatever `origin/HEAD`
  was already cached locally."* A `"head"` worktree never does this — it always branches
  from the *local* checkout's current `HEAD`, unpushed commits and all.

**No explicit "introduced in vX.Y.Z" line found for the setting itself** on either fetched
page — several nearby "Before v2.1.2xx" notes (worktree-reuse behavior, `origin/HEAD`
caching, both citing 2.1.208) imply `worktree.baseRef` predates that range, which comfortably
supports this repo's `Claude Code ≥ 2.1.219` floor, but this is an inference from adjacent
version notes, not a directly-quoted floor for the key. Flag rather than assert if a future
spec needs an exact introduction version.

Sources: live `EnterWorktree` tool description (this session) ·
[`code.claude.com/docs/en/worktrees.md`](https://code.claude.com/docs/en/worktrees.md)
§"Choose the base branch", §"Isolate subagents with worktrees" ·
[`code.claude.com/docs/en/settings.md`](https://code.claude.com/docs/en/settings.md)
settings-precedence table · `scripts/compound-v-emit-workflow.py:1379-1398`
(`_worktree_base_is_head`) · `.claude/settings.json` (this repo, current contents).

---

## Updated 2026-09-03 — v3.4.8 workflow retry (`agent()` null-vs-throw contract)

Validated for
[`docs/superpowers/library-audit/2026-09-03-v3-4-8-workflow-retry.md`](../2026-09-03-v3-4-8-workflow-retry.md).
No Context7 attached to this subagent (`ToolSearch` → no match); no local Bash access beyond the V-memory
script (`bashCommandClamp`) — same constraint pattern as the two 2026-09-03 entries above. Primary source is
a **full** live `WebFetch` of `code.claude.com/docs/en/workflows.md`, cross-checked against this KB's own
2026-09-01 `BINARY` entry and against this repo's currently-shipped `scripts/compound-v-emit-workflow.py`.

**`agent()`'s error-resolution contract, now three-way corroborated.** Live doc, verbatim, 2026-09-03:

> "An `agent()` call **resolves to `null`** if you stop it mid-run or **it hits an unrecoverable API
> error**. `pipeline()` keeps that `null` in the results array…"

This is the complete general statement on the current page — there is no documented "throws on a transient
API error" path. It matches, word-for-word in substance, the 2026-09-01 `BINARY` entry above (*"Returns
`null` if skipped or terminally errored"*), extracted from the installed executable two days earlier and one
engine build apart. **Third independent confirmation:** this repo's own shipped, dogfooded JS template
(`compound-v-emit-workflow.py`, `recordStage`/`gateStage`/`finalizeWave`) already handles `agent()` with
*both* a `try/catch` (for the throw path — budget exceeded, unknown `agentType`, malformed options) *and* an
explicit `=== null`/`=== undefined` check (for the unrecoverable-API-error path) at every call site — and the
`null` branch's recorded "reason" is always a **static literal**, never `String(err)`, because no error
object exists on that path. Treat "`agent()` throws on a transient API failure" as **false** for any future
spec — the correct mental model is: throws on setup/programmer errors, resolves to `null` (with zero
diagnostic detail) on an unrecoverable API-level error, including exactly the 529/rate-limit/network classes
a retry design is likely to target.

**Sandbox-wording drift, unresolved, flag rather than assert.** The 2026-09-01 `BINARY` extraction states a
single combined clause: *"No filesystem or Node.js API access."* The 2026-09-03 live-fetched page instead
gives two narrower, separate bullets: *"No direct filesystem or shell access from the workflow itself"* and
*"No module loading: a script that contains `import()` fails before the run starts."* Neither the 2026-09-01
nor the 2026-09-03 source explicitly confirms or denies whether JS runtime globals such as `setTimeout` are
available inside the script. `Grep` over this repo's entire shipped JS template (2026-09-03) found **zero**
uses of `setTimeout`/`await new Promise(...)`-style delays — no prior Compound V workflow script has ever
exercised this. **`UNVERIFIED` — a live throwaway-script probe from a main session (not a subagent — the
Workflow tool is not visible to a subagent per the 2026-09-02 entry above) is needed before any design
depends on an in-script timed wait.**

**`bashCommandClamp` / `disallowedTools` reconfirmed still-undocumented, 2026-09-03.** The full live fetch of
`workflows.md` today contains neither string, anywhere — reconfirming the 2026-09-01 entry's 🟡-5 finding
two days later on a fresh full-page fetch, not just carried forward.

Sources: [`code.claude.com/docs/en/workflows.md`](https://code.claude.com/docs/en/workflows.md) (fetched in
full, 2026-09-03) · this file's own 2026-09-01 entry (`BINARY`, installed Claude Code `2.1.238`) ·
`scripts/compound-v-emit-workflow.py:2171-2179,2201-2249,2267-2311` (`Grep`+`Read`, this session, current
HEAD).

---

## Updated 2026-09-03 — `agent()` schema property-addition semantics (v3.4.9 kb_files/retries)

Validated for
[`docs/superpowers/library-audit/2026-09-03-v3-4-9-preflight-kb-paths-and-retries-schema.md`](../2026-09-03-v3-4-9-preflight-kb-paths-and-retries-schema.md).
No Context7 attached to this subagent (fourth same-week 1C run recording this). Sources: a live `WebFetch` of
`code.claude.com/docs/en/workflows.md`, prompted specifically for the `schema` option's property-addition
semantics (narrower than the same-day v3.4.8 fetch above, which focused on error/retry behavior) · direct
read of `scripts/compound-v-emit-preflight.py`'s already-shipping `RESULT_SCHEMA` and wrapper-prompt JS
template · `schemas/job_result.schema.json`'s existing (v3.4.8) `retries.items` sub-schema.

**The array-of-strings schema shape is documented AND already running in this repo.** The live doc's own
worked example uses exactly `{type: 'array', items: {type: 'string'}}` for a schema property. This repo's
`RESULT_SCHEMA["properties"]["blocking"]` (`compound-v-emit-preflight.py:102`) is byte-identical to that
shape and has been shipping in production since the pre-flight emitter existed — stronger evidence than any
doc statement, because it is observed running code. Adding a second array-of-strings property (`kb_files`)
to the same schema carries zero shape-currency risk.

**Gap in the live doc: it describes schema *shape*, never schema *evolution*.** No mention anywhere on the
fetched page of a property-count limit, nesting-depth limit, or guidance on adding a new property to an
already-working schema. Nothing found either way — treat as unaddressed by the doc, not as "confirmed safe
by the doc" (the confirmation instead comes from the running-code precedent above).

**Required-vs-optional JSON Schema semantics apply to `agent()`'s `schema` option, and this repo's own code
already demonstrates it.** A property listed in `properties` but absent from `required` may legitimately be
omitted from a schema-compliant `agent()` response — standard JSON Schema behavior, not Claude-Code-specific
and not subject to library drift. `RESULT_SCHEMA`'s existing `notes` property (`properties`-only, never
`required`, never explicitly asked for by name in the wrapper prompt) is direct, already-running evidence
of this: nothing forces an agent to fill it, and nothing in this repo currently does. **Any future field
added to this schema that the orchestrator actually depends on being present must either go in `required`,
or be explicitly asked for by name in the wrapper prompt text — schema membership alone is not enough.**

**`RESULT_SCHEMA` and the wrapper prompt are ONE shared object/string across all three parallel pre-flight
phases.** `compound-v-emit-preflight.py:236-267`: the `parallel()` fan-out for 1A (code-archaeologist), 1B
(domain-expert), and 1C (doc-validator) all receive the identical `CFG.schema` and near-identical `prompt`
template, differing only in interpolated `purpose`/`out` strings. A schema field addition is global across
all three phases by construction — not opt-in per phase — even when only some phases' own agent
instructions describe using it.

**Three result-construction sites in the JS template bypass `agent()`/`schema` entirely and get no schema
enforcement or defaulting.** The `e.skipped` branch (`:240`), the `r === null`/`undefined` branch
(`:287-288`), and the `catch` branch (`:296-297`) are hand-written object literals returned directly from
the `parallel()` callback, never passed through structured-output validation. Each already lists
`blocking: []` explicitly — the established precedent that any field the post-processing step reads
unconditionally must be defensively present (or coalesced with `|| []`) at all three sites, not only
wherever the schema is defined.

Sources: [`code.claude.com/docs/en/workflows.md`](https://code.claude.com/docs/en/workflows.md) (fetched
2026-09-03, this session) · `scripts/compound-v-emit-preflight.py:91-105,209-267,302-324` (`Read`, this
session, current HEAD) · `schemas/job_result.schema.json:219-257` (`Read`, this session).
