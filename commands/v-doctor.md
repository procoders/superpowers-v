---
description: Run Compound V self-check. Verifies the plugin is loaded, all agents/commands/hooks are wired, Context7 MCP is available, and optionally runs a no-op smoke test to confirm end-to-end orchestration works.
---

You are about to run the **Compound V doctor** — a self-check that diagnoses install/wiring issues without touching the user's project files.

## Steps

1. Dispatch the `compound-v:doctor` agent with:
   - **Empty prompt** (the agent does its own probing)
   - **maxTurns**: 10
   - **Model**: opus (set by agent definition)
2. The doctor will:
   - Locate the plugin install
   - Verify manifest, 6 agents, hooks, commands
   - Probe Context7 MCP availability
   - Ask the user about user-visible state (`/plugin list`, `/agents` output, SessionStart banner)
3. If `{{args}}` contains `smoke` (e.g. user typed `/v:doctor smoke`), tell the doctor to ALSO run the end-to-end orchestration smoke test (~one Opus dispatch).
4. Return the structured health report to the user.

If the report says ❌ on any check, surface the fix command verbatim — these are usually one-liner install/re-install fixes.
