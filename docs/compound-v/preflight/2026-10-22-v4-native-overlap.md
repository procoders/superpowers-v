# v4 native-overlap audit

Checked 2026-10-22 against Claude Code 2.1.306. Sources: the official docs at `code.claude.com/docs/en/*.md` (fetched today),
strings from the installed binary (`~/.local/share/claude/versions/2.1.306`), and four headless probes run in `/tmp/cvprobe`
(`claude -p --model claude-sonnet-5-5 --output-format json`, no bypass flag, total spend about $1). Question per component: does
Claude Code already do this, does it work in `claude -p`, and is its evidence machine-checkable?

| # | Component (plan) | Native feature | Headless `-p`? | Machine evidence? | Verdict |
|---|---|---|---|---|---|
| 1 | Browser check (Task 9 `live_cmd`, Task 10 init probe) | Desktop Browser pane `mcp__Claude_Browser__*` (desktop.md "Preview your app"); Claude in Chrome `--chrome` (chrome.md); bundled `/run` skill (drives web apps with `chromium-cli`); bundled `/verify` | Pane: **no** (probe 1 shows no browser tools). Chrome: the tools are **listed** under `-p --chrome` (probe 2), but the extension needs a visible Chrome window and `/login`, so a working headless run is UNVERIFIED. `/run`: yes, but `chromium-cli` is not installed here. `/verify`: model can't invoke it (`disable-model-invocation`) | No. `/run` "defines no output files and no structured result" (probe 3); the pane and Chrome only give screenshots and model narration | **KEEP OURS** (Playwright Test exit code). Use `/run-skill-generator` recipes as a launch hint only |
| 2 | Usage and cost (Task 5 `usage.py`, `prices.json`, `transcripts_for`) | `-p` result `total_cost_usd` + `modelUsage[*].costUSD`; transcript entry `type:"cost-state"` (`totalCostUSD`, per-model `costUSD`, `hasUnknownModelCost`); statusline `cost.total_cost_usd`; mod `$.session.usage().cost.usd`; `--max-budget-usd`; OTel `claude_code.cost.usage` | Yes. Probe 4 (one Explore subagent): `result.usage` output 329 + subagent transcript 349 = `modelUsage` 678. So `total_cost_usd` and `cost-state` (both $0.3175) **include subagents**, VERIFIED | Yes: numbers written by the CLI from its own bundled price table | **USE NATIVE**. Drop `prices.json` and the token×price math; keep a small reader |
| 3 | Completion gate (Task 7 `stop_hook`, refuse-once) | Stop hooks `type:"prompt"` / `type:"agent"` (hooks.md "Prompt-based hooks"); `/goal` (goal.md) | Yes (`claude -p "/goal …"` is documented) | No. `/goal` "doesn't run commands or read files"; the verdict comes from the "small fast model", which is Haiku by default and our policy forbids Haiku. Agent hooks are experimental (60 s timeout, 50 turns) and leave no receipt | **KEEP OURS** (command Stop hook reading `verify`) |
| 4 | Lane worktrees (Task 6 `lane start/finish`) | `isolation: worktree`, `worktree.baseRef:"head"`, EnterWorktree/ExitWorktree, isolation enforcement, `WorktreeCreate/Remove` hooks (worktrees.md) | Yes. EnterWorktree/ExitWorktree are present under `-p` (probe 1). `-p` runs never clean up their worktrees | Partial. Native refuses Edit/Write into the main checkout and git redirects. It does not check per-lane globs, merge, or run tests | **WRAP NATIVE**. Drop `lane start`; keep `lane finish` |
| 5 | Run-record protection (Task 7 `guard_hook`) | Permission deny `Edit(docs/compound-v/runs/**)` (permissions.md) | Yes (settings rules) | Yes (deterministic refusal) | **USE NATIVE**, written by init; the hook stays only as a fallback before init |
| 6 | Session continuity (Task 7 `session.sh`) | Compaction summary, `--resume/--continue`, `/goal` restored on resume, SessionStart `source=compact\|resume` + `additionalContext` | Yes | Not applicable (context only) | **KEEP OURS**. It is already a thin native SessionStart hook; native has no idea of run stage |
| 7a | Plan skill | Plan mode (EnterPlanMode/ExitPlanMode, permission-modes.md) | Approval UX is interactive; UNVERIFIED in `-p` | No acceptance table, no `compound-v-plan` block | **KEEP OURS** |
| 7b | Reviewer agent | `/code-review` (code-review-local.md), `/security-review`, `/simplify`, `ReportFindings` tool | `/code-review`: yes, but findings come back as **text** in `-p`. `/security-review` needs an `origin` remote | No schema, reviews the diff rather than the request + acceptance table, no isolated checkout | **KEEP OURS**; `/code-review` is at most an optional extra |
| 7c | `v-memory` docs lookup agent | Built-in `Explore` | Yes | No (lookup) | **KEEP OURS**. Explore runs on the **main model** (Opus), per sub-agents.md; a per-call `model:"sonnet"` override exists, but a 25-turn Sonnet agent file is cheaper and pinned |
| 7d | Domain pre-flight | `/deep-research` bundled workflow (workflows.md), `anthropic-skills:deep-research` | Listed under `-p` (probe 2); needs workflow approval; availability under `--setting-sources project,local` is UNVERIFIED | Cited report, not checks | **KEEP OURS** (≤4 searches; deep-research is heavier than the cost budget allows) |
| 8a | Prompt triage (Task 7 `prompt_hook`) | UserPromptSubmit `type:"prompt"` hook | Yes | No: a paid model call on the background (Haiku) model | **KEEP OURS** (deterministic, as spec §5 requires) |
| 8b | Budget cap | `--max-budget-usd` (print mode, subagents count; spend "can pass the cap") | Yes | Yes (`error_max_budget_usd` result) | **USE NATIVE** in the benchmark and `-p`; keep the run-record budget for interactive use |
| 8c | Pre-commit verify | Project skill named `verify` gets a "run it before each commit" instruction (skills.md, ≥2.1.286); plugin skills **don't count** | Yes | Depends on what the skill runs | **WRAP NATIVE** (optional): init writes a one-line project skill that calls `compound-v.py verify` |
| 8d | Release evals (Task 11 deletes `evals/`) | `claude plugin eval` (`--judge-model`, `--max-cost-usd`, with/without plugin arms) | Yes | Yes (JSON, exit codes) | **USE NATIVE** for trigger tests (engagement, triage); the salon benchmark stays an external kit |

## Notes

**1. Browser.** No Claude-provided browser is usable in a sandboxed `claude -p` benchmark. The pane is desktop-only. Chrome
drives the user's real logged-in profile and requires `/login`. `/run` expects `chromium-cli` (binary strings: "a headless-Chromium
REPL … Screenshots land in `chromium_cli/sessions/…`"), which is not on this machine and gives screenshots, not pass/fail.
`/verify` is user-invoked only. The plan's Playwright Test choice stands. Also: native `/verify` and our `compound-v:verify` will
both be in the user's skill list, so the skill description must make clear which one is which.

**2. Cost — the clearest reinvention.** The CLI already prices every model, subagents included, and writes the result into the
transcript as `cost-state` lines. A per-model `hasUnknownModelCost` flag replaces our "price missing ⇒ null" logic. The
`modelPricing` managed setting re-prices everything for contract rates. Replace `transcripts_for` + token summing + `prices.json`
with: in `-p`, read `total_cost_usd`/`modelUsage` from the result; in interactive sessions, read the last `cost-state` line from
the Stop hook's `transcript_path`, or have the band mod pass `usage().cost.usd` (the binary shows it is the same `bh()`
accumulator as the statusline's `total_cost_usd`). Per-stage cost = delta at each stage transition. **UNVERIFIED:** how often
`cost-state` is written in a live session. This session's transcript has 12 such lines over about 58k lines, so the last one can
lag. The format is not in the docs, so read it fail-open. All of these figures are client-side estimates, not billing
(agent-sdk/cost-tracking.md). Codex is still timed by us.

**3. Gate.** The native gates all ask a model to judge the transcript. Spec §3 requires script-written fields, so `/goal` and
prompt/agent hooks are out. Our hook should still respect the native backstop: after 8 consecutive blocks the harness overrides,
which matches our refuse-once design.

**4. Worktrees.** This answers the platform audit's open question 2: "Subagent worktrees use the same base branch as `--worktree`,
so they branch from your repository's default branch unless `worktree.baseRef` is set to `"head"`". The plan's reason for its own
`git worktree add … HEAD` disappears once init sets that. Native isolation also gives a pre-write main-checkout guard, which the
spec had given up. It does not catch `cp` or `>` writes into the main tree. A plugin **cannot** ship `worktree.baseRef`: plugin
`settings.json` honours only `agent` and `subagentStatusLine` (plugins/manifest-reference.md). So `/compound-v:init` must write it
to project settings with consent. **UNVERIFIED:** how `lane finish` learns a subagent's worktree path. Use a `WorktreeCreate` hook
or the PostToolUse `tool_response`. The docs list no worktree option for Workflow-tool agents (UNVERIFIED).

**5. Protection.** Edit deny rules cover every built-in edit tool, recognised Bash file commands (`sed`, `tee`) and `>`
redirections. They do not cover arbitrary subprocesses, so `compound-v.py` can still write the record. That is stronger than the
plan's guard, which matches only Write/Edit/MultiEdit/NotebookEdit. A plugin cannot ship permissions, for the same reason as in
note 4, so init writes the rule. Receipts stay HMAC-signed either way.

**6–7.** Keep our own: Explore costs Opus, `/code-review` has no schema in `-p`, plan mode is interactive approval, deep-research
is too heavy for the budget.

Probes: probe 1 = plain `-p` tool list; probe 2 = `-p --chrome` tools, skills and agents; probe 3 = loading the `/run` and
`/verify` skill text; probe 4 = one Explore subagent, cost reconciliation.
