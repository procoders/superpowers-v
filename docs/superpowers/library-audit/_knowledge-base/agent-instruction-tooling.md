# Agent-Instruction & Onboarding Tooling Knowledge Base

Maintained by Compound V Phase 1C validator. Append at the bottom. Date-stamp every claim. Cite sources. Never delete prior entries — strike through with `~~old~~` and add `→ updated YYYY-MM-DD: <new>`.

---

## Updated 2026-06-30 — `/v:onboard` dependency sweep

Audit: `docs/superpowers/library-audit/2026-06-30-v-onboard-dependencies.md`.

### `@google/design.md` (DESIGN.md linter)
- **2026-06-30:** Current **v0.3.0** (released 2026-06-15). Repo `google-labs-code/design.md`, Apache-2.0, 23.6k★, not archived, 51 open issues, last commit 2026-06-15. Active.
- npm package `@google/design.md`; CLI bin `design.md` (Windows alias `designmd`). Invoke: `npx @google/design.md lint DESIGN.md`.
- Subcommands: **`lint`** (exit 1 on errors, 0 otherwise; `--format json` default; stdin via `lint -`), **`diff <a> <b>`** (exit 1 on regression), **`export`** (formats: json-tailwind, css-tailwind, dtcg), **`spec`** (prints format spec + rules).
- JSON findings schema: `{ findings: [{ severity, path, message }], summary: { errors, warnings, info } }`. `severity` ∈ `error|warning|info`.
- WCAG: `contrast-ratio` rule computes backgroundColor/textColor pairs vs WCAG AA 4.5:1; reports at warning severity. v0.2.0 (2026-05) added CSS Color Module color-format support.
- Source: Context7 `/google-labs-code/design.md` (README, 294 snippets); `gh api repos/google-labs-code/design.md`.

### `repomix` (deterministic repo pack)
- **2026-06-30:** Current **v1.16.0** (published 2026-06-29 — one day old). Repo `yamadashy/repomix`, MIT, 26.7k★, not archived/deprecated, pushed 2026-06-30. Very active.
- Secret scan: built-in via **Secretlint**, controlled by `security.enableSecurityCheck`, **ON by default**. Disable with `--no-security-check`. It is NOT opt-in — do not design a pack step that "enables" it; it already runs.
- Token counts: per-file + total + per-format. `.gitignore`-aware. Emits file tree. `--remove-comments` / `--compress` / `--remove-empty-lines` for token reduction.
- `gitingest` is a viable alternative but repomix is the chosen dependency for `/v:onboard` PACK.
- Source: npm `registry.npmjs.org/repomix`; repomix.com/guide/configuration; `gh api repos/yamadashy/repomix`.

### AGENTS.md / Linux Foundation AAIF
- **2026-06-30:** AGENTS.md is an AAIF (Agentic AI Foundation, Linux Foundation) project — AAIF formed 2025-12-09 anchored by MCP, goose, and AGENTS.md (OpenAI contribution). 60k+ projects adopted. Living standard.
- **Claude Code reads `CLAUDE.md`, NOT `AGENTS.md`.** Canonical bridge: a thin `CLAUDE.md` whose first line is `@AGENTS.md`, optionally followed by a `## Claude Code` section. Official docs give this exact example. A symlink (`ln -s AGENTS.md CLAUDE.md`) also works when no Claude-specific content is needed; on Windows use the `@AGENTS.md` import (symlinks need admin/Dev Mode).
- `@path` import syntax: relative or absolute paths, recursive imports up to **4 hops**, import parsing skips code spans/fences. **Imported files load in FULL at launch** — `@import` is NOT a token optimization. Only path-scoped `.claude/rules/*.md` (YAML `paths:` frontmatter) and skills defer-load.
- CLAUDE.md size: docs say **"target under 200 lines"** — a recommendation for adherence, NOT a hard ceiling. CLAUDE.md loads in full regardless of length. (Auto-memory `MEMORY.md` has a real 200-line/25KB load cap; CLAUDE.md does not.)
- `/init` in a repo with existing `AGENTS.md`/`.cursorrules`/`.windsurfrules`/`.devin/rules/` reads and incorporates them.
- Source: https://code.claude.com/docs/en/memory; https://www.linuxfoundation.org/press/...aaif...; https://agents.md.

### MCP servers (the §10 recommender set)
Resolve to the **maintained vendor/community server**, never the deprecated per-integration entries in `modelcontextprotocol/servers` (the reference repo itself is live, but its database/integration reference servers are the deprecated ones to avoid).

- **GitHub MCP** — `github/github-mcp-server`, not archived, 31k★, pushed 2026-06-30. Remote (recommended): `https://api.githubcopilot.com/mcp/` (needs host OAuth/GitHub App; strongest in VS Code). Local: Docker or binary (stdio). Remote has extra tools (e.g. `create_pull_request_with_copilot`).
- **Postgres MCP** — `crystaldba/postgres-mcp` ("Postgres MCP Pro"), **v0.3.0** (2026-05-16), 3.0k★, not archived. Last *commit* 2026-01-22 (slowest of the set; re-check if it crosses 12 months). **Read-only flag is `--access-mode=restricted`** (read-only txns + exec-time limit + pglast rejects COMMIT/ROLLBACK), NOT `--read-only`. `--read-only` belongs to the DEPRECATED `modelcontextprotocol/servers` Postgres reference.
- **Supabase MCP** — `@supabase/mcp-server-supabase`, **v0.8.2** (2026-06-08). Flags `--read-only` and `--project-ref=<ref>` both real + recommended. Caveat: `--project-ref` scopes only DB tools (`execute_sql`, `apply_migration`); `create_project`/`create_branch` ignore it — lethal-trifecta warning still applies.
- **Playwright MCP** — `@playwright/mcp` (microsoft/playwright-mcp), **v0.0.77** (2026-06-29). **CVE-2025-9611**: DNS-rebinding via missing Origin/Host validation in versions **< 0.0.40** → a malicious web page could drive the local MCP and reach all tools. **Pin ≥ 0.0.40.** Current latest is well past the fix.
- **Context7 MCP** — `@upstash/context7-mcp`, official Upstash, MIT, active. Install: `npx -y @upstash/context7-mcp@latest` (Claude Code: `claude mcp add --scope user context7 -- npx -y @upstash/context7-mcp --api-key …`). Two tools: `resolve-library-id`, `query-docs`.
- **Sentry MCP** — `getsentry/sentry-mcp`, vendor-operated, pushed 2026-06-29. Remote (preferred): `https://mcp.sentry.dev/mcp`. Local stdio for self-hosted Sentry (WIP). Claude Code plugin: `claude plugin marketplace add getsentry/sentry-mcp`.
- Source: `gh api` repo health for each; vendor docs (supabase.com/docs/guides/ai-tools/mcp, github/github-mcp-server docs, docs.sentry.io/product/sentry-mcp); CVE-2025-9611 (SentinelOne / VulnCheck / GHSA-8rgw-6xp9-2fg3).

### V-memory embedding lane (consumed by `/v:onboard`, not extended)
- **2026-06-30:** V-memory DENSE lane uses **direct onnxruntime**, NOT the `fastembed` library. Bootstrap installs `onnxruntime, tokenizers, huggingface_hub, numpy` (unpinned) into an isolated out-of-repo venv; runs the Xenova ONNX export of multilingual-e5-small (384-dim, 512-token window). `fastembed` is never imported — references to "fastembed/onnxruntime" are a mislabel.
- `/v:onboard` adds **zero** new embedding/Python deps. Its only V-memory interaction is auto-running the existing `/v:memory-refresh` (INDEX step) and extending which git-tracked files are indexed (root `CONVENTIONS.md`/`DESIGN.md`/`AGENTS.md`). No conflict.
- Source: `scripts/compound-v-memory.py:343-364, 850-889`.

---

## Updated 2026-07-10 — Claude Code bundled deep-research, Visual Companion contract, AskUserQuestion caps

Audit: `docs/superpowers/library-audit/2026-07-10-research-grounded-brainstorm.md` (Research-Grounded Brainstorm v2.7.0).

### Installed stack (this machine, 2026-07-10)
- Claude Code **v2.1.197** (Mach-O arm64; BUILD_TIME 2026-06-29T19:08:42Z; GIT_SHA c8fd8048), at `~/.local/share/claude/versions/2.1.197`. Facts below are string-extracted from that binary unless noted.
- Superpowers plugin cache holds **5.1.0, 6.0.3, 6.1.0, 6.1.1**; newest upstream = **6.1.1** (obra/superpowers, released 2026-07-02).

### `deep-research` — bundled Claude Code Workflow (NOT a SKILL.md file)
- **2026-07-10:** Present on v2.1.197; appears **unprefixed** in the available-skills listing (`deep-research`), the same bucket as builtin `/verify`, `/code-review`, `/run`. It is a **dynamic Workflow**, not a classic skill file.
- **Invocation:** user-facing `/deep-research <question>`; programmatic `Workflow({name: 'deep-research', args: '<question>'})` (verified — the no-arg error prints exactly this). Argument = **one research-question string**.
- **Pipeline:** scope agent *"Decompose this research question into complementary search angles"* → fan-out search agents → extract **2–5 FALSIFIABLE claims** → **N-vote adversarial verification** (`VOTES_PER_CLAIM`; verdict phase uses `VERDICT_SCHEMA`) → `{label:"synthesize", schema: REPORT_SCHEMA}` → report + 3–5 sentence executive summary.
- **Output mode:** **returns the report as a message; does NOT write a file** (binary workflow-agent rule: *"Communicate your final report directly as a regular message — do NOT attempt to create files."*). Any caller that needs a persisted doc must write it itself.
- **Provenance:** the dynamic-**Workflow** platform was introduced **v2.1.154 (2026-05-28)** (*"Introducing dynamic workflows … orchestrates … tens to hundreds of agents … Run /workflows"*; trigger keyword renamed `workflow`→`ultracode`). The changelog references `/deep-research` only via **bugfixes** (e.g. verifier misreporting "all claims refuted" as `unverified`, ~v2.1.196–198), never a clean "Added" line. **`skills.md`'s bundled-skills list omits deep-research** and is explicitly non-exhaustive ("including `/doctor`, `/code-review`, `/batch`, `/debug`, `/loop`, `/claude-api`" + `/run`, `/verify`, `/run-skill-generator`).
- **Consequence for callers:** presence is **not** version-inferable and the skill is gate-able (`disableBundledSkills` / `CLAUDE_CODE_DISABLE_BUNDLED_SKILLS`, ultracode toggle). Correct presence-check = **is `deep-research` in the live available-skills listing**; invoke via the skill/slash interface (a plain subagent may lack the `Workflow` tool). Absent ⇒ WebSearch fallback.
- Source: binary strings in `versions/2.1.197`; `code.claude.com/docs/en/changelog`; `code.claude.com/docs/en/skills.md`.

### Superpowers Visual Companion — contract is stable 6.0.3 → 6.1.1
- **2026-07-10:** `skills/brainstorming/SKILL.md` and `scripts/start-server.sh` are **byte-identical** across 6.0.3 and 6.1.1; `visual-companion.md` differs only by **removing the Gemini-CLI launch note** in 6.1.1. → Reference the companion by its **contract**, never a version pin.
- `start-server.sh` flags: `--project-dir <path>`, `--host`, `--url-host`, `--idle-timeout-minutes <n>`, `--open`, `--foreground` (=`--no-daemon`), `--background` (=`--daemon`). Returns startup JSON `{"type":"server-started","port":N,"url":"http://<host>:N/?key=…","screen_dir":"…/content","state_dir":"…/state"}`, also written to `$STATE_DIR/server-info`. The `?key=…` is mandatory.
- Events: **`$STATE_DIR/events`**, JSONL, one obj/line `{"type":"click","choice":"a","text":"…","timestamp":…}`, **cleared on each new screen push**, **absent ⇒ no browser interaction**.
- `data-multiselect`: supported — `helper.js`: `container.dataset.multiselect !== undefined` inside `toggleSelect`; put the bare attribute on a `.options` container.
- Frame CSS classes (frame-template.html, 6.0.3 == 6.1.1): `.options .option .letter .content · .cards .card .card-image .card-body · .mockup .mockup-header .mockup-body · .split · .pros-cons .pros .cons · .mock-nav .mock-sidebar .mock-content .mock-button .mock-input .placeholder · .subtitle .section .label · .selected`. Selection wiring `data-choice onclick="toggleSelect(this)"`.
- **Upstream rule that companion-batching guidance overrides** (quote): SKILL.md *"Use the terminal for content that is text — requirements questions, conceptual choices, tradeoff lists, A/B/C/D text options, scope decisions"*; visual-companion.md *"Use the terminal when the content is text or tabular … anything where the answer is words, not a visual preference."* Batching independent text questions into one form supersedes this — say so, and never force-open the browser (upstream: *"Offer … just-in-time — NOT upfront … This offer MUST be its own message … If no visual question ever arises, never offer it."*).
- Source: installed 6.0.3/6.1.0/6.1.1 caches; `github.com/obra/superpowers/releases` (v6.1.1).

### AskUserQuestion caps (native tool)
- **2026-07-10:** **1–4 questions per call**, **2–4 options per question**, **header ≤12 chars**, automatic **"Other" free-text** option, **`multiSelect: true`** supported (multiSelect verified directly from the binary: *"Use multiSelect: true to allow multiple answers to be selected for a question"*; numeric caps are ajv-compiled — confirmed via `code.claude.com/docs/en/agent-sdk/user-input`). v2.1.200 (2026-07-03): dialogs **no longer auto-continue by default** (opt into idle timeout via `/config`) — the old "60s auto-timeout" is off by default now.
- Source: binary strings; `code.claude.com/docs/en/agent-sdk/user-input`; changelog 2.1.181 / 2.1.200.

### V-memory recall CLI (local)
- **2026-07-10:** `python3 scripts/compound-v-memory.py search "<query>" [--repo REPO] [--top N] [--intent planning|review] [--json] [--no-embed]`. `/v:remember` uses `search "{{args}}" --top 8`. A separate `recall-check` subcommand (recurring-failure verdict) is for review gates — **not** brainstorm gate 2; gate 2 uses `search`. Agent bash cwd resets between calls → use an absolute script path or explicit `cd`.
- Source: `scripts/compound-v-memory.py search --help`; `commands/v-remember.md:10`.
