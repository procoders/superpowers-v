# Compound V — Gemini CLI Shim (🧪 experimental, untested)

This file documents how the plugin's content *would* be used in Gemini CLI. **The shim has not been tested on a real Gemini CLI install** — the manifest format for Gemini CLI extensions is version-specific and the maintainer has not verified compatibility. Treat this as a starting point, not a working integration.

## What this plugin does

Compound V is a **sidekick to Superpowers**. It intercepts the three Superpowers phase transitions (brainstorming → writing-plans → execution) and adds:

1. **Three parallel pre-flights** after brainstorming:
   - Code archaeology (existing-code reality)
   - Domain-expert advisor with three-layer audience search (product/regulatory reality)
   - Library/doc validator via Context7 MCP (dependency currency)
2. **Disjoint File Partition Map enforcement** inside writing-plans
3. **Batched parallel dispatch** on the most capable model available (Gemini 2.5 Pro or equivalent)

## How Gemini uses it

The skill content lives at `skills/compound-v/SKILL.md` and its phase reference files. Read those directly — they're harness-neutral.

Gemini's `activate_skill` tool can load the SKILL.md content on demand. Trigger: when the conversation mentions brainstorming completion, planning, or implementation orchestration.

## Tool name mapping (Claude Code → Gemini CLI)

| Claude Code | Gemini CLI |
|---|---|
| `Task(subagent_type, prompt, model)` | Gemini's `run_subagent` or `agent_dispatch` (varies by version) |
| `Skill <name>` | `activate_skill <name>` |
| `mcp__plugin_context7_context7__*` | MCP tools loaded via Gemini's MCP integration |

## Model policy mapping

This plugin was authored for the Anthropic Claude family. On Gemini:

- "Opus default" → **Gemini 2.5 Pro** (or whatever is currently the most capable model)
- "Sonnet exception" → **Gemini 2.5 Flash** for the same narrow junior-task taxonomy
- "Never Haiku" → Never use Gemini Flash-Lite or smaller; the project's reasoning bar is high

See `skills/compound-v/phase-3-parallel-opus-dispatch.md` § "Model Selection Taxonomy" for the strict 8-box criteria that gate the cheaper-model carve-out.

## Key entry points

- For setup: `README.md`
- For the full skill flow: `skills/compound-v/SKILL.md`
- For "what's in this plugin": `CHANGELOG.md`
- For "it broke": `TROUBLESHOOTING.md`

## Disclaimer

This plugin was built and tested primarily on Claude Code. Gemini compatibility is best-effort. If you find Gemini-specific gotchas, please file an issue.
