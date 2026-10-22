---
name: init
description: Set up Compound V in this project. Probes git, Python, Codex, a browser runner and Superpowers; picks the reviewer and test command; writes .claude/compound-v.json and the two native project settings Compound V relies on (worktree base and run-record protection). Every write is shown as a diff and applied only on the user's yes. Run once per project, and again after installing Codex or Playwright.
argument-hint: "[--check]"
---

# Init

Set up this project for the Compound V cycle (brainstorm → pre-flights → plan → build → verify). Probe everything first, then show the user **one** message with the findings and every proposed change, numbered, and apply only what they approve. With `--check`, probe and report, and write nothing.

## 1. Probes (write nothing)

Run these and keep the results:

```bash
git rev-parse --show-toplevel && git rev-parse --verify -q HEAD   # a repo with a first commit
python3 -c 'import sys; print(sys.version_info >= (3, 9))'      # True
codex --version                                                   # reviewer candidate
npx --no-install playwright --version                             # Playwright Test in this project
claude mcp list                                                   # a playwright or chrome-devtools MCP?
claude plugin list --json                                         # is superpowers@claude-plugins-official enabled?
```

- **No first commit, or not a git repo**: stop and say so. The run record pins a base commit, so Compound V cannot run without one.
- **Python below 3.9**: stop, and name the interpreter found.
- **Test command**: detect one from `package.json` (`scripts.test` → `npm test`), `pyproject.toml` / `pytest.ini` (`python3 -m pytest`), a `Makefile` `test:` target (`make test`), `go.mod` (`go test ./...`) or `Cargo.toml` (`cargo test`). With none, propose none, and the plan will set one per run.
- **Browser runner**: Playwright Test in the project, or a Playwright / Chrome DevTools MCP in `claude mcp list`. With none, the offer is `claude mcp add playwright -- npx @playwright/mcp@0.0.83 --headless`, plus a note that each web plan adds Playwright Test (`@playwright/test`) as a dev dependency for its `live_cmd`. Without a browser, a web run ends incomplete unless the user waives the check.
- **Codex stop-review gate**: the codex plugin keeps a per-project `stopReviewGate` flag in its state file. Check it with
  `grep -ls '"stopReviewGate": *true' ~/.claude/plugins/data/codex-*/state/"$(basename "$PWD")"-*/state.json "${TMPDIR:-/tmp}"/codex-companion/"$(basename "$PWD")"-*/state.json 2>/dev/null`.
  A hit means two Stop-time reviewers would both fire (Codex's gate and Compound V's refuse-once Stop hook). Warn, and suggest `/codex:setup --disable-review-gate` for this project.
- **Existing files**: read `.claude/compound-v.json` and `.claude/settings.json` if they exist. Every write below is a merge into them. Never truncate either file.

## 2. One message: findings and proposed changes

Report the probes in a few lines, then list each proposed change with its diff, numbered:

**① `.claude/compound-v.json`** (Compound V's own config):

```json
{"version": 4,
 "stance": "standard",
 "default_tier": "full",
 "reviewer": "claude",
 "test_cmd": "npm test",
 "budget_usd": 7,
 "models": {"build": "opus", "mechanical": "sonnet", "review": "opus"}}
```

- `reviewer`: `codex` when `codex --version` works and the user wants it, otherwise `claude`. The Claude reviewer is an Opus subagent, and its cost counts in the run's Claude budget. Codex runs outside it and is timed separately.
- `stance`: `standard`, or `cost-aware` (brainstorm depth defaults to quick, and the advisor is off or Opus, never Fable).
- `test_cmd`: the detected command, which the user confirms or corrects.
- `models`: the map the plan's task → model table draws from. This replaces v3's `/v:models`. Opus judges and builds, Sonnet takes mechanical work only.

**② `.claude/settings.json`** (the project's native settings, merged key by key):

```json
{"worktree": {"baseRef": "head"},
 "permissions": {"deny": ["Edit(/docs/compound-v/runs/**)"]}}
```

- `worktree.baseRef: "head"` makes native `isolation: "worktree"` subagents branch from the current HEAD instead of the default branch, so parallel lanes see this run's work. It applies project-wide, to interactive `--worktree` sessions too. A plugin cannot ship this setting, which is why init writes it.
- The deny rule protects run records natively. `Edit(...)` rules cover every built-in file-editing tool (Write included) and Bash redirections and `sed`/`tee` targets. The leading `/` anchors the path at the project root. A `Write(...)` path rule would never be consulted, so it is not written. Receipts stay signed either way, and the plugin's guard hook covers projects that have not run init.
- Append to an existing `permissions.deny` list; never replace it.

**③ Superpowers** (only when it is enabled): both brainstorm skills would fire on the same request. Offer to disable it for this project only, in `.claude/settings.json`:
`{"enabledPlugins": {"superpowers@claude-plugins-official": false}}`. Compound V neither calls Superpowers nor defers to it.

**④ Playwright MCP** (only when no browser runner was found): the `claude mcp add` command above.

**⑤ Warnings** with no write: the Codex stop-review gate, a missing test command, no browser.

End the message with one question: "Apply ①–④? Say which to skip or change." Then apply exactly what was approved, and nothing else.

## 3. Apply

- Write the JSON by reading the existing file, merging, and writing it back pretty-printed. Show the final diff afterwards (`git diff -- .claude/`).
- `.claude/` may be write-protected by the sandbox. The user's approval of the edit prompt is what lets the write through. Never route around it.
- Run nothing else. Installing Codex, Playwright browsers or project dependencies is the user's call: give the command and let them run it.

## 4. Report

In at most 8 lines: what was written, the reviewer, the test command, the browser state (Playwright Test / MCP / none, and what that means for web runs), any warning, and the next step: "Describe what you want built; Compound V starts with `compound-v:brainstorm`. Small changes go straight to `compound-v:verify`."
