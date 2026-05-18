---
description: Run Compound V Phase 1A — code archaeology — on a topic without running the other pre-flights. Useful when you want the technical audit but already have domain + library context.
---

You are about to run **Phase 1A only** of Compound V: a code-archaeology audit on `{{args}}`.

This skips Phase 1B (domain-expert) and Phase 1C (library-validator). Use the full Compound V flow (just stop using a slash command — the skill auto-fires after brainstorming) if you want all three.

## Steps

1. Read the brainstorming spec (or use the topic argument as the spec context).
2. Dispatch the `compound-v:code-archaeologist` agent with:
   - **Topic / spec** from `{{args}}` or the most recent brainstorming output
   - **Repo root** = current working directory
   - **Knowledge base path** = `docs/superpowers/archaeology/_knowledge-base/`
   - **Model**: opus (set by the agent definition)
   - **maxTurns**: 15
3. When the agent returns, the audit is saved to `docs/superpowers/archaeology/YYYY-MM-DD-<topic-slug>.md`.
4. Surface the "Design constraints for the spec" section and the "File Touch Map" to the user — these are what the next phase (writing-plans) consumes.

If `{{args}}` is empty, ask: "What feature or topic should I run archaeology on?" then proceed.
