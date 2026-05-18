# Changelog

All notable changes to **superpowers-v (Compound V)** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses semantic versioning.

## [0.1.1] — 2026-05-18

Honesty pass after an independent verification audit caught several fabricated CLI/env-var references that I had baked into hooks and docs without verifying against the official Claude Code documentation.

### Fixed (critical — load-bearing)
- **Hook scripts no longer read fabricated environment variables.** Rewrote `session-banner.sh` and `plan-saved-nudge.sh` to follow the documented Claude Code hook interface: input read from JSON on stdin (via `jq`), output emitted as JSON for `additionalContext` context injection. Pattern adapted from upstream `obra/superpowers v5.1.0` reference hooks. Previous scripts read `$CLAUDE_HOOK_MATCHER` and `$CLAUDE_TOOL_INPUT_FILE_PATH`, neither of which exists in the official hook spec — the hooks were technically running but always silently no-op'd.
- **SessionStart matcher corrected** from `*` to the documented pattern `startup|clear|compact` (matches upstream superpowers).

### Removed
- `compound-v:doctor` agent + `/v:doctor` slash command — clutter for typical sessions; manual debug instructions in TROUBLESHOOTING.md cover the same ground.
- `SubagentStop` hook configuration + `sidekick-nudge.sh` script — the `SubagentStop` event is not in the official Claude Code hooks reference and the reference plugin `obra/superpowers` does not use it. Replaced with description-based auto-fire (which was always the primary mechanism) plus the `PostToolUse(Write)` plan-saved nudge.
- `gemini-extension.json` — manifest schema was not verifiable against official Gemini CLI docs; removed rather than ship a fabricated config.

### Changed
- **Multi-harness shims (AGENTS.md, GEMINI.md) marked 🧪 experimental / untested.** Previous wording implied verified support; honest reality is the shims are based on documentation patterns but were not exercised on a real Codex or Gemini install. The README compatibility table now reflects this.
- README install steps: removed fictional `/mcp add context7` command; correct install path is `/plugin install context7@claude-plugins-official` or manual `~/.claude.json` MCP config. Context7 demoted from step 1 to step 3 (recommended, not required).
- Phase 3 dispatcher announce string toned down (was "going Supe"; now neutral "dispatching N implementers").
- SKILL.md auto-fire caveat rewritten honestly: skill invocation is description-driven; hooks provide reminders but do NOT enforce the trigger.
- `.github/workflows/validate.yml` no longer validates `gemini-extension.json` (file removed).

### Added
- Hard citation-rigor rules in `agents/domain-expert.md`: ≥10 distinct community posts OR 1 official source for consensus claims; isolated reports flagged explicitly; no fabricated URLs; verbatim quotes only; empty section > padded section.

### Notes on the honesty audit
The verifier could not find official documentation for several Task tool parameters used throughout the plugin (`subagent_type: "<plugin>:<agent>"` plugin-namespaced syntax, `maxTurns`, `run_in_background: true`). These remain in the plugin's prompts and docs because they are observably functional in Claude Code as of v0.1.1, but should be revisited if they break in a future CC version. Tracked for future verification.

## [0.1.0] — 2026-05-18

Initial public release.

### Added

**Core skill (`skills/compound-v/`):**
- Three-trigger interceptor for Superpowers transitions (after brainstorming, inside writing-plans, before execution)
- Phase 1A: code-archaeology pre-flight (five-phase audit of existing-code reality)
- Phase 1B: domain-expert advisor with three-layer parallel WebSearch (official docs, practitioner channels, audience/persona forums)
- Phase 1C: library/doc validator via Context7 MCP (catches stale deps, abandoned libraries, outdated API signatures)
- Phase 2: Disjoint File Partition Map enforcement inside writing-plans
- Phase 3: batched parallel Opus dispatch with strict scope locks; `model: opus` by default, `model: sonnet` only when a task ticks every box of the strict 8-box junior-task taxonomy

**6 first-class agents (`agents/`)** — invokable as `subagent_type: "compound-v:<name>"`:
- `code-archaeologist`, `domain-expert`, `doc-validator`, `partition-reviewer`, `parallel-dispatcher`, `spec-reviewer`

**2 slash commands (`commands/`):**
- `/v:archaeology <topic>`, `/v:dispatch <plan-path>`

**Hooks (`hooks/`)** — sidekick auto-fire (text-printer only, no side effects):
- `SessionStart` banner reminding parent Claude that Compound V is loaded
- `PostToolUse matcher=Write` nudges when a plan or spec is saved

**Operational:**
- `.github/workflows/validate.yml` — JSON schema, agent frontmatter (with no-Haiku project policy), dead-link scan, shellcheck on hooks
- `scripts/lint-frontmatter.py` — Python frontmatter linter for local pre-commit
- `evals/evals.json` — 8 trigger eval test cases (3 positive, 2 negative, 3 edge) for the compound-v skill
- `.cclintrc.json` — config for [`@felixgeelhaar/cclint`](https://github.com/felixgeelhaar/cclint)
- `TROUBLESHOOTING.md` — common issues
- All code blocks tagged with explicit language

**Realistic concurrency limits documented:** 4-6 foreground / 5-10 background Task calls per message; batched dispatch for larger plans; `maxTurns: 15` cap; `run_in_background: true` recommended for implementer batch.

**Output convention:** `docs/superpowers/{archaeology,expert,library-audit}/` with `_knowledge-base/` subdirectories for cross-feature knowledge persistence.

## [0.1.0] — 2026-05-18

Initial public release.

### Added

**Core skill (`skills/compound-v/`):**
- Three-trigger interceptor for Superpowers transitions (after brainstorming, inside writing-plans, before execution)
- Phase 1A: code-archaeology pre-flight (five-phase audit of existing-code reality)
- Phase 1B: domain-expert advisor with three-layer parallel WebSearch (official docs, practitioner channels, audience/persona forums)
- Phase 1C: library/doc validator via Context7 MCP (catches stale deps, abandoned libraries, outdated API signatures)
- Phase 2: Disjoint File Partition Map enforcement inside writing-plans
- Phase 3: batched parallel Opus dispatch with strict scope locks; `model: opus` by default, `model: sonnet` only when a task ticks every box of the strict 8-box junior-task taxonomy

**6 first-class agents (`agents/`)** — invokable as `subagent_type: "compound-v:<name>"`:
- `code-archaeologist`, `domain-expert`, `doc-validator`, `partition-reviewer`, `parallel-dispatcher`, `spec-reviewer`

**2 slash commands (`commands/`):**
- `/v:archaeology <topic>`, `/v:dispatch <plan-path>`

**Hooks (`hooks/`)** — sidekick auto-fire (text-printer only, no side effects):
- `SessionStart` banner reminding parent Claude that Compound V is loaded
- `SubagentStop matcher=brainstorming|writing-plans` nudges with next-step dispatch
- `PostToolUse matcher=Write` nudges when a plan or spec is saved

**Multi-harness compatibility shims (experimental):**
- `AGENTS.md` (Codex CLI)
- `GEMINI.md` + `gemini-extension.json` (Gemini CLI)

**Operational:**
- `.github/workflows/validate.yml` — JSON schema, agent frontmatter (with no-Haiku project policy), dead-link scan, shellcheck on hooks
- `scripts/lint-frontmatter.py` — Python frontmatter linter for local pre-commit
- `evals/evals.json` — 8 trigger eval test cases (3 positive, 2 negative, 3 edge) for the compound-v skill
- `.cclintrc.json` — config for [`@felixgeelhaar/cclint`](https://github.com/felixgeelhaar/cclint) (silences CLAUDE.md-specific false-positives)
- `TROUBLESHOOTING.md` — 11 documented common issues
- All code blocks tagged with explicit language (`plaintext`, `markdown`, etc.)

**Realistic concurrency limits documented:** 4-6 foreground / 5-10 background Task calls per message; batched dispatch for larger plans; `maxTurns: 15` cap; `run_in_background: true` recommended for implementer batch.

**Output convention:** `docs/superpowers/{archaeology,expert,library-audit}/` with `_knowledge-base/` subdirectories for cross-feature knowledge persistence.
