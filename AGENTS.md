# Compound V — Codex / Universal Agent Shim (🧪 experimental, untested)

This file documents how the plugin's content *would* be consumed by tools that read `AGENTS.md` from a project root (Codex CLI and similar). **It has not been tested on a real Codex install** — tool-name mappings and dispatch syntax are based on documentation and may need adaptation per your harness version.

## What this plugin does

Compound V is a **sidekick to Superpowers**. It intercepts the three Superpowers phase transitions (brainstorming → writing-plans → execution) and adds:

1. **Three parallel pre-flights** after brainstorming:
   - Code archaeology (existing-code reality)
   - Domain-expert advisor with three-layer audience search (product/regulatory reality)
   - Library/doc validator via Context7 MCP (dependency currency)
2. **Disjoint File Partition Map enforcement** inside writing-plans
3. **Batched parallel dispatch** (4-6 concurrent) on Opus by default, Sonnet only for strict junior-level mechanical tasks

## How Codex / non-Claude-Code harnesses use it

The skill content lives at `skills/compound-v/SKILL.md` and its phase reference files. Read those directly — they're harness-neutral prose. The dispatch templates assume Claude Code's `Task` tool; in Codex, substitute your harness's subagent-spawning mechanism (e.g. `subagent` in Codex CLI).

## Tool name mapping (Claude Code → Codex)

| Claude Code | Codex / generic |
|---|---|
| `Task(subagent_type, prompt, model, maxTurns, run_in_background)` | `subagent <name> --model opus --max-turns 15 --background` |
| `Skill <name>` | Read the skill file directly and apply |
| `mcp__plugin_context7_context7__*` | Whatever the local Context7 MCP installation exposes |

## First-class agents (under `agents/`)

These work in any harness that reads `agents/*.md` frontmatter. Codex CLI loads them as `subagent_type` candidates automatically:

- `compound-v:code-archaeologist` — Phase 1A
- `compound-v:domain-expert` — Phase 1B (with multi-layer WebSearch incl. persona forums)
- `compound-v:doc-validator` — Phase 1C
- `compound-v:partition-reviewer` — pre-execution gate
- `compound-v:parallel-dispatcher` — execution orchestrator
- `compound-v:spec-reviewer` — post-implementer spec compliance

## Model policy (universal)

- **Opus by default** — every implementer, reviewer, advisor
- **Sonnet** — narrow exception per the 8-box junior-task taxonomy in `skills/compound-v/phase-3-parallel-opus-dispatch.md`
- **Never Haiku** — not permitted in this project

## Key entry points

- For setup: `README.md`
- For the full skill flow: `skills/compound-v/SKILL.md`
- For "what's in this plugin": `CHANGELOG.md`
- For "it broke": `TROUBLESHOOTING.md`
- For the comic / why it exists: `assets/skyscraper-metaphor.md`

## Disclaimer

This plugin was built and tested primarily on Claude Code. Codex / Gemini compatibility is best-effort via shims. If you find harness-specific gotchas, please file an issue.
