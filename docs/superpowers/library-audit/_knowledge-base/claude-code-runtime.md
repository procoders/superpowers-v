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
