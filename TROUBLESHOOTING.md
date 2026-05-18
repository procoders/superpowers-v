# Troubleshooting

Common issues with Compound V and how to fix them.

## Sidekick isn't auto-firing after brainstorming

**Symptom:** You finished `superpowers:brainstorming`, the spec is saved, but Compound V didn't dispatch the pre-flights.

**Cause:** "Auto-fire" is **description-driven** — the parent Claude has to read Compound V's skill description and recognize the trigger condition. The plugin ships a `PostToolUse(Write)` hook that prints a *reminder* when a spec/plan file is saved, but the actual skill invocation still depends on the parent's recognition. Reliability is high on Opus / Sonnet 4.6+; weaker models may miss it.

**Fix:**
1. Confirm the plugin is installed: `/plugin list` should show `superpowers-v`.
2. Confirm hooks are loaded: `cat ~/.claude/settings.json` (or your project's `.claude/settings.json`) should include the plugin's hooks (Claude Code loads plugin hooks automatically on session start).
3. Confirm the SessionStart banner appeared at session start: re-start the session if not (`/session new`).
4. As a manual fallback, invoke the skill directly: `Skill compound-v`.

## Phase 1C says "Context7 unavailable"

**Symptom:** The doc-validator agent reports "DEGRADED: WebSearch-only" instead of using Context7.

**Cause:** Context7 MCP isn't installed in this Claude Code session.

**Fix:**
```
/mcp add context7
```

Or in your `.mcp.json`:
```json
{
  "mcpServers": {
    "context7": {
      "command": "npx",
      "args": ["-y", "@upstash/context7-mcp"]
    }
  }
}
```

Restart the session. Phase 1C will now use Context7 first, falling back to WebSearch only for libraries not in the index.

## Partition reviewer fails with FILE_OVERLAP

**Symptom:** `compound-v:partition-reviewer` returns `FAIL: FILE_OVERLAP` and the plan's Partition Map looks fine to you.

**Cause:** Two parallel tasks reference the same file (commonly a barrel/index file, a type declaration, a config, or a migration). Glob patterns count as expanded — `src/i18n/locales/*.json` overlaps with `src/i18n/locales/en.json`.

**Fix:** Move the shared file to **Task 0 (serial pre-phase)**, or split the original parallel task by namespace so each gets a disjoint subset. See `skills/compound-v/phase-2-disjoint-partitioning.md` § "Shared Resources → Serial Pre-Phase" and § "Default approach: split by feature slice, not by layer."

## Implementer returned BLOCKED: "need to read sibling file"

**Symptom:** During Phase 3 dispatch, one implementer reports `BLOCKED` because it needs to read a file in another parallel task's WRITE-allowed list.

**Cause:** The Partition Map missed a coupling. The two tasks aren't actually disjoint.

**Fix:**
1. Identify the shared file.
2. If it's read-only shared (e.g. a type), move it to **Task 0** so all parallel tasks get auto-propagated READ access.
3. If it's modified by both, **merge the two tasks** — they aren't actually parallelizable.
4. Re-dispatch the blocked task with the updated scope lock.

Never tell the implementer to "just peek" — that defeats the partition contract.

## Two implementers collided on a file despite the partition

**Symptom:** Phase 3 finished but `git status` shows merge conflicts or unexpected file states.

**Cause:** One implementer wrote a file outside its WRITE-allowed list. The scope lock is enforced by prompt, not by harness, so a misbehaving subagent can violate it.

**Fix:**
1. `git diff` to identify which file landed unexpectedly.
2. `git log --oneline -5` to see commit attribution.
3. Reject the violating implementer's commits; re-dispatch with a stricter scope lock and an explicit reminder: "improvising files outside the WRITE-allowed list is a scope-lock violation per Compound V Phase 3."
4. Update the Partition Map if the implementer's "improvisation" reveals a real partition gap.

## "Opus rate-limited" mid-batch

**Symptom:** Halfway through a 6-task parallel batch, some implementers fail with rate-limit errors.

**Cause:** Anthropic's API enforces per-account rate limits. 4-6 parallel Opus subagents is the practical ceiling; 10+ reliably hits the wall.

**Fix:**
1. Reduce batch size to 3-4 in the plan's Partition Map.
2. Use `run_in_background: true` on implementers — staggered start helps.
3. As a last resort: document the rate-limit fallback in the plan (`"Compound V fallback: Sonnet used for tasks X/Y because Opus rate-limited at <timestamp>"`) and re-dispatch failed tasks on Sonnet. Note this is a degradation, not the contract.

## Domain-expert audit feels generic, no community quotes

**Symptom:** Phase 1B audit returns text from official docs only — no Reddit, HN, or community sources.

**Cause:** The agent skipped Layer 2 + Layer 3 searches. Common when the dispatch prompt didn't emphasize them, or when WebSearch returned mostly official docs for the top hits.

**Fix:** Re-dispatch the domain-expert agent with an explicit instruction: "Spend at least 2 of your searches on persona/community forums where the END USER of this feature hangs out — not just the vendor docs." The agent definition has Layer 3 in its system prompt, but a busy advisor sometimes under-uses it.

## Knowledge base files are getting huge

**Symptom:** `docs/superpowers/expert/_knowledge-base/oauth.md` is 2000+ lines and hard to navigate.

**Fix:** Run a manual consolidation pass:
1. Identify entries with the same heading topic.
2. Merge them into a single canonical section, keeping the latest date stamps.
3. Move older entries to a `_history/` subdirectory if you want to preserve them for git context.

Compound V agents don't currently auto-consolidate the KB — that's a P2 enhancement.

## How do I run only Phase 1A (no domain or library audit)?

Use the slash command: `/v:archaeology <topic>`.

## How do I run only Phase 1B?

Currently: dispatch the agent manually: `Task(subagent_type: "compound-v:domain-expert", prompt: "...")`. A `/v:domain` command is P1 backlog.

## How do I run only Phase 1C?

Currently: dispatch the agent manually: `Task(subagent_type: "compound-v:doc-validator", prompt: "...")`. A `/v:libs` command is P1 backlog.

## I'm using Codex / Gemini CLI, not Claude Code

The plugin ships compatibility shims:
- **Codex**: `AGENTS.md` at the project root is auto-loaded by Codex CLI; it points at the same skills.
- **Gemini CLI**: `GEMINI.md` documents the conceptual mapping. The extension manifest schema is harness-specific — adapt to your Gemini CLI version's actual format (the shim is untested as of v0.1.1).

The skill content is harness-neutral. Tool names differ (Claude Code's `Task` ≈ Codex's `subagent`); the dispatcher logic adapts.

## Compound V says my repo is too small for it

Compound V is overkill for:
- Greenfield single-file features
- Pure refactors that touch every file (no partition possible)
- Pure plumbing (build config, lint rules)
- Solo learning sessions

Fall back to default Superpowers for those. Document the fallback at the top of the plan: `"Compound V skipped — single-file feature; using default subagent-driven-development."`
