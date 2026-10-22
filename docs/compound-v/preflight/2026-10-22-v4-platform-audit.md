# v4 platform and library audit (pre-flight 1C)

Checked 2026-10-22. Local CLI: Claude Code 2.1.306, codex-cli 0.162.1. Sources: official docs under
https://code.claude.com/docs/en/ (fetched today; page text is the evidence) and local command output.
Tools: Context7 present but not used (platform docs are not library docs); WebFetch used. Recall block absent from the prompt;
V-memory not queried (platform facts only). No DEGRADED path other than that.

## 1. plugin.json and namespacing
- Only `name` is required; the manifest itself is optional (/docs/en/plugins-reference "Manifest file", "Fields"). Optional: `version` (setting it
  pins users until changed), `description`, `author`, `license`, `homepage`, `skills`, `commands`, `agents`, `hooks`, `mcpServers`, `settings`,
  `userConfig`, `dependencies`, `types` (mod declarations), `workflows`, `experimental.evals`, and more. Unknown top-level keys are stripped, warning in `validate`.
- `name` is the namespace prefix: `compound-v` yields `/compound-v:<skill>`. Not reserved: only names starting `claude-`, `anthropic-`, `cc-plugin-` or equal to `claude`, `claude-code` etc. are errors.
- Commands are merged into skills; docs recommend `skills/<name>/SKILL.md` for new work (/docs/en/skills "Skills vs. commands"; plugin-reference layout table: "Prefer `skills/` for new plugins"). `skills/init/SKILL.md` gives `/compound-v:init`; frontmatter `name` sets the last segment. A `commands/*.md` file also works, same frontmatter minus `name`/`paths`. **Use skills.**
- Setting `commands`/`agents` in the manifest replaces the default dir scan; `skills` adds to it. A `CLAUDE.md` at plugin root is not loaded (validate warns today on this repo).

## 2. Marketplace: two entries, one pinned to a v3 ref  (VERIFIED in docs, not installed live)
`marketplace.json` requires `name`, `owner`, `plugins[]`; each entry requires `name` and `source` (/docs/en/plugins/marketplace-reference).
`github`, `url`, `git-subdir` sources take `ref` (branch or tag) and `sha` (40-char). Duplicate entry names are an error; two entries with different names may point at the same repo. Suggested shape (keep marketplace name `procoders`, file stays on `main`):
```json
{"name":"procoders","owner":{"name":"Oleg"},"plugins":[
 {"name":"compound-v","source":"./"},
 {"name":"superpowers-v","source":{"source":"github","repo":"procoders/superpowers-v","ref":"v3"}}]}
```
Rules to respect: entry `name` must equal the `name` in that ref's `plugin.json` (`superpowers-v` on the v3 branch; yes today). Existing users' `superpowers-v@procoders` keys keep resolving to v3. Add `sha` to freeze the last 3.9.x commit. `claude plugin marketplace add` accepts `owner/repo@ref` / `#ref`, so a separate v3 marketplace file is not needed. A marketplace is read from the default branch's `.claude-plugin/marketplace.json`, so main must carry both entries. UNVERIFIED: a live install of the `ref` entry (run `claude plugin marketplace add ./<tmp>` + `install superpowers-v@procoders` once before release).

## 3. Hooks
- Events (33 listed, same page /docs/en/hooks): SessionStart, UserPromptSubmit, PreToolUse, Stop, SubagentStop, PreCompact, PostCompact, SessionEnd, etc.
- **Stop** stdin: `session_id, transcript_path, cwd, permission_mode, hook_event_name, stop_hook_active, last_assistant_message, background_tasks, session_crons`. `stop_hook_active` is true when Claude is already continuing because of a stop hook; "check this value ... to avoid blocking on a condition that will never resolve". Block: stdout `{"decision":"block","reason":"..."}` (reason required) or exit 2 with stderr as reason. Softer: `hookSpecificOutput.additionalContext` (hookEventName "Stop"). **Refuse once** = block only when `stop_hook_active` is false (or when a once-marker in the run record is unset), exit 0 otherwise. Backstop: after 8 consecutive stop-hook continuations the harness overrides the block and ends the turn; `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP` raises it. `continue:false`+`stopReason` is not documented under Stop itself (UNVERIFIED for Stop).
- **UserPromptSubmit**: stdin has `prompt`; stdout JSON `hookSpecificOutput:{hookEventName:"UserPromptSubmit",additionalContext:"..."}` or plain stdout (exit 0) both become context; `decision:"block"` rejects the prompt; exit 2 rejects it and shows stderr. Timeout default is 30 s here (not 600).
- **SessionStart**: `additionalContext`, `sessionTitle`, `initialUserMessage`, `watchPaths`; input `source` = startup|resume|clear|compact|fork; command and mcp_tool hooks only.
- **PreCompact** (`trigger`, `custom_instructions`; exit 2 blocks) / **PostCompact** (`trigger`, `compact_summary`; no decision control). **SubagentStop**: adds `agent_id, agent_type, agent_transcript_path, last_assistant_message`; block keeps the subagent running.
- `timeout` is in **seconds**; defaults 600 command/http, 30 prompt, 60 agent, 30 for command hooks on UserPromptSubmit. Exit codes other than 0/2 are a non-blocking error in the docs I read (PreModelSwitch section links "other-exit-codes"). **Conflict:** this repo's `hooks/hooks.json` comment asserts "a non-zero exit from a Stop hook IS a block". I did not find that in the fetched text; UNVERIFIED either way, keep `|| true` and the fail-open design, and test with a real broken script on 2.1.306.
- `${CLAUDE_PLUGIN_ROOT}` resolves in hook `command`/`args`, MCP/LSP/monitor commands and **skill, command and agent Markdown bodies** (inline substitution). It is exported as env to hook processes only, and is **not** in the env of Bash commands Claude runs. Also `${CLAUDE_PLUGIN_DATA}` (persists across updates; use for state, never write under ROOT) and `${CLAUDE_PROJECT_DIR}`. Exec form (`args`) is preferred over quoting.

## 4. Skills and agents frontmatter
- Skills: `name`, `description`, `when_to_use`, `argument-hint`, `arguments`, `disable-model-invocation`, `user-invocable`, `allowed-tools` (pre-approves for the turn, does not restrict), `disallowed-tools`, `model` (override for the turn; with `context: fork` sets the subagent model), `effort`, `context: fork`, `agent`, `background`, `hooks`, `paths`, `shell`, `metadata`. `model` does exist.
- Agents: required `name`, `description`; `tools`, `disallowedTools`, `model` (sonnet|opus|haiku|fable|full id|inherit), `maxTurns`, `memory` (user|project|local), `omitClaudeMd` (>= 2.1.271), `effort`, `isolation`, `skills`, `background`, `color`, `autoCompactWindow` (>= 2.1.296). **Plugin agents ignore `hooks`, `mcpServers`, `permissionMode`, `initialPrompt`.**
- **`isolation: worktree` exists** (only value): temp git worktree, auto-removed when the subagent changes nothing. Caveat from the docs: it branches from the **default branch, not the parent's HEAD**, which matters for the spec's "own worktree per parallel writer" (uncommitted or branch-local work is not seen). This repo's settings already use `worktree.baseRef: "head"` (UNVERIFIED whether that setting also governs subagent worktrees).
- Agent memory dir: `.claude/agent-memory/<agent-name>/` (plugin prefix handling is as recorded in AGENTS.md; not re-tested).

## 5. Mods and usage
- A mod = plugin with `hooks/hooks.json` `"modules": ["./file.tsx"]` (one path) and a `register(on, options)` export; `.tsx` allowed; optional `types` in the manifest (/docs/en/plugins/mods/reference). Mods ignored on older CLIs (this repo's floor 2.1.287 stays).
- `$.session.usage()` returns `{ startedAt, context:{tokens,window,percent}, rateLimits:[{kind,percentUsed,resetsAt}], cost }`. A `cost` field exists but its type/scope (parent only? subagents? USD?) is UNVERIFIED; read `types/claude-code.d.ts` for the build before relying on it. `session.measure` fires after each turn. The spec's plan (measure from transcripts incl. subagents, `session-usage.py`) is the safer authority. Limits: hook 10 s, `$.process.run` 30 s default/10 min max, `claude plugin test` 5 s per test.

## 6. enabledPlugins
Key format `plugin-name@marketplace-name`, boolean (local example: `"superpowers@claude-plugins-official": true`, `"context7@claude-plugins-official": false`). Precedence: managed > CLI > project-local > shared project > user; same key from the higher level wins (docs, Settings precedence). So `{"enabledPlugins":{"superpowers@claude-plugins-official":false}}` in `.claude/settings.json` disables it for that project (inferred from the precedence rule; not live-tested). `extraKnownMarketplaces` and `permissions.allow` in a committed file wait for folder trust.

## 7. Browser verification
- **Claude in Chrome** (`claude --chrome`, `/chrome`): extension >= 1.0.36, visible Chrome window, needs `/login` on a direct Anthropic plan; API key or `setup-token` auth keeps it off; a project's `CLAUDE_CODE_ENABLE_CFC` is ignored. Not headless, so not suitable for `claude -p` gates.
- **Built-in browser pane** (`mcp__Claude_Browser__*`): desktop-app feature available in this session; no evidence it exists in headless `claude -p` (UNVERIFIED).
- **Playwright MCP**: `@playwright/mcp` 0.0.83 (npm, modified 2026-09-28; Node >= 18). Install: `claude mcp add playwright npx @playwright/mcp@latest`; `--headless` (headed by default), `--browser chrome|firefox|webkit|msedge`, `--isolated`, `--caps vision,pdf,devtools`, `--output-dir`. Runs headless, so usable in `claude -p`. Pin the version rather than `@latest` for receipts.
- **Chrome DevTools MCP**: `chrome-devtools-mcp` 1.11.0 (npm, 2026-10-15; Node ^20.19 || ^22.12 || >=23). Headless flag not checked here: UNVERIFIED.
- Recommendation for the spec: default to Playwright MCP headless (only one verified headless, version-pinnable, no login dependency); Chrome/DevTools as detected alternatives.

## 8. validate / test / eval (local `--help`, 2.1.306)
- `claude plugin validate <path> [--json] [--strict] [--profile directory]`: manifest, marketplace.json, skills/agents/commands frontmatter, hooks files, mod calls; today it passes with 1 warning (root CLAUDE.md). `--strict` fails on warnings.
- `claude plugin test [dir]`: runs only `*.test.ts(x)` mod tests (kit `claude-code/testing`), 5 s each. Not a general test runner.
- `claude plugin eval [target]`: runs `evals/**/case.yaml` through real `claude` children, with-vs-without-plugin arms; `--runs`, `--threshold`, `--max-cost-usd`, `--allow-tools`, `--scaffold`, `--judge-model` (default haiku: conflicts with the never-Haiku policy, pass `--judge-model sonnet`), `--json`, exit 1 below threshold, exit 2 on cost ceiling. Spends tokens; release gate, not CI.

## 9. codex exec (0.162.1, `--help`)
Read-only review: `codex exec -s read-only -C "$CHECKOUT" --skip-git-repo-check --ephemeral --output-schema schema.json -o last.txt [--json] -m "$model" -` (prompt on stdin). Confirmed flags: `-s/--sandbox read-only|workspace-write|danger-full-access`, `--output-schema <FILE>`, `-o/--output-last-message <FILE>`, `--json`, `--ephemeral`, `-C/--cd`, `--ignore-user-config`, `--ignore-rules`, `--strict-config`. Also a new `codex exec review` subcommand and `--worktree`. Not run live; `--output-schema` enforcement of shape on the final message is UNVERIFIED (validate the JSON in `verify` anyway).

## Design constraints for the plan
MUST use `skills/` not `commands/`; MUST keep marketplace entry `name` equal to each ref's plugin.json `name`; MUST gate Stop on `stop_hook_active`/once-marker and still fail open; MUST write mutable state to the project `docs/compound-v/` or `${CLAUDE_PLUGIN_DATA}`, never under `${CLAUDE_PLUGIN_ROOT}`; MUST NOT put `hooks`/`permissionMode` in plugin agent frontmatter; MUST NOT assume `isolation: worktree` starts from the current HEAD; MUST NOT rely on Chrome integration in `claude -p`; MUST pass `--judge-model` non-Haiku to evals; MUST NOT use `$.session.usage().cost` as run cost until its shape is verified. Version floor candidates: 2.1.271 (omitClaudeMd), 2.1.287 (mods).

## Open questions
1. Live-test the `ref`-pinned marketplace entry and the project-level `enabledPlugins:false` override before 4.0.
2. Does `worktree.baseRef: "head"` apply to `isolation: worktree` subagents?

## Verified in Task 13 (live probes, 2026-10-22, Claude Code 2.1.306)
- **enabledPlugins:** a project `.claude/settings.json` with `{"enabledPlugins": {"superpowers@claude-plugins-official": false}}` shows every Superpowers install as `✘ disabled` in `claude plugin list` inside that project, and `✔ enabled` outside it. VERIFIED.
- **Built-in browser pane is not available to `claude -p`** (native-overlap probe 1). VERIFIED.
- **Chromium inside the Claude Code sandbox on macOS fails:** `bootstrap_check_in … Permission denied (1100)` (Mach port registration), with or without `allowLocalBinding` / `allowMachLookup: ["*"]`. Running `npx playwright test` as a `sandbox.excludedCommands` entry (plus a matching `Bash(...)` allow rule) passes. VERIFIED. A call with a pipe appended stays sandboxed, as the docs say.
- **An `Edit(/docs/compound-v/runs/**)` permission deny is also enforced as a sandbox write deny:** a sandboxed `python3` write there fails with `PermissionError: Operation not permitted`. So v4 writes no such rule. VERIFIED.
- **The sandbox cannot write `~/.claude/compound-v/`:** the receipt key moved to `<git common dir>/compound-v/receipt.key`. VERIFIED by the light smoke.
- **`cost-state` in `-p`:** a one-turn run's transcript holds one `cost-state` line, written after the Stop hook ran, so a single-turn run's own cost is unknown to the hooks; multi-turn runs see the previous turns'. VERIFIED (light smoke).
- **Sandbox auto-allow refused two compound commands** with shell variables / `$?`; the skills now say to run each CLI call as one plain line. VERIFIED (light smoke).
- Still UNVERIFIED: a live install of the `ref: "v3"` marketplace entry (needs the `v3` branch pushed; installing would also change the user's plugin config), and whether a Stop hook exiting 1 blocks (our hooks are registered `|| true` and exit 0 by trap, so it cannot arise).
