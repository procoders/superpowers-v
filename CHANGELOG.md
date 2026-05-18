# Changelog

All notable changes to **superpowers-v (Compound V)** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses semantic versioning.

## [Unreleased]

### Added
- `compound-v:doctor` agent + `/v:doctor` slash command — self-check that prints plugin load status, hook firing history, and triggers a no-op test dispatch to verify orchestration works end-to-end
- Hard citation-rigor rules in domain-expert agent: ≥10 distinct community posts OR 1 official source for consensus claims; isolated reports flagged as such; no fabricated URLs

### Changed
- README install steps: removed fictional `/mcp add context7` command; Context7 install correctly documented as `/plugin install context7@claude-plugins-official` or manual `~/.claude.json` MCP config. Context7 demoted from step 1 to step 3 (recommended, not required).
- Phase 3 dispatcher announce string toned down (was "going Supe"; now neutral "dispatching N implementers")

### Fixed
- CHANGELOG sync: prior `[Unreleased]` content was actually shipped in v0.1.0; consolidated.

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
