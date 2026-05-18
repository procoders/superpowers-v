# Changelog

All notable changes to **superpowers-v (Compound V)** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses semantic versioning.

## [Unreleased]

### Added
- **6 first-class agents** in `agents/` (invokable as `subagent_type: "compound-v:<name>"`):
  - `code-archaeologist` — Phase 1A; five-phase audit of existing code reality
  - `domain-expert` — Phase 1B; product/domain audit with three-layer parallel WebSearch (official sources, practitioner channels, audience/persona forums)
  - `doc-validator` — Phase 1C; library currency check via Context7 MCP
  - `partition-reviewer` — verifies a plan's Partition Map is genuinely disjoint
  - `parallel-dispatcher` — orchestrates batched parallel Opus dispatch
  - `spec-reviewer` — checks implementer diffs against spec + audit constraints
- **2 slash commands** in `commands/`:
  - `/v:archaeology <topic>` — run Phase 1A alone
  - `/v:dispatch <plan-path>` — run partition-review + parallel-dispatch on a plan
- **Hooks** in `hooks/` for hard sidekick auto-fire:
  - `SessionStart` banner reminding the parent Claude that Compound V is loaded
  - `SubagentStop matcher=brainstorming|writing-plans` nudges with the next-step dispatch
  - `PostToolUse matcher=Write` nudges when a plan or spec is saved
- **Phase 1C** — library/doc validator with Context7 MCP integration; `_knowledge-base/` persistence per library/ecosystem topic
- **Sonnet exception (strict 8-box junior-task taxonomy)** for implementers — Opus by default, Sonnet only when every box ticks
- **Multi-harness compatibility**: `AGENTS.md` (Codex), `GEMINI.md` (Gemini CLI), `gemini-extension.json`
- **Multi-layer audience search** in domain-expert: official docs + practitioner channels (Reddit, HN, SO) + persona forums (where the END USER hangs out)
- **CI**: `.github/workflows/validate.yml` validates plugin.json schema, agent frontmatter, dead cross-refs, mermaid syntax
- **TROUBLESHOOTING.md** for common Compound V issues

### Changed
- Renamed `velocity-mode` → `compound-v` skill (named after the Compound V from *The Boys* / *Gen V* — the supe-making chemical)
- Three pre-flights now run in parallel (was two): adds Phase 1C library validator
- Realistic concurrency: 4-6 parallel Task calls per message (was "unlimited"); batched dispatch documented
- `maxTurns: 15` cap on every dispatched subagent
- `run_in_background: true` recommended for implementer batch

## [0.1.0] — 2026-05-18

### Added
- Initial release. Compound V skill with two parallel pre-flights (archaeology + domain-expert), Disjoint Partition Map, parallel Opus dispatch.
