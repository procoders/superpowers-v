#!/usr/bin/env bash
# Compound V — SessionStart hook
# Emits a context-injection JSON output that prints a one-line "loaded" banner
# to the session, reminding the parent Claude that Compound V is available.
# When no project config (.claude/compound-v.json) is present, appends a single
# '/v:init' setup hint so first-time users know how to configure routing.
#
# Hook output format (Claude Code spec): JSON to stdout with hookSpecificOutput.
# Cursor: JSON with additional_context (snake_case).
# Generic SDK: JSON with additionalContext.
# Pattern adapted from obra/superpowers v5.1.0 hooks/session-start.

set -euo pipefail

banner="Compound V loaded — sidekick to Superpowers. Auto-fires after brainstorming (description-based discovery). Phases: code-archaeologist + domain-expert + doc-validator (parallel) → partition-reviewer → parallel-dispatcher. You do not need to invoke it manually."

# First-run setup hint: the project stance config is .claude/compound-v.json
# (project-level, committed). SessionStart runs from the project root, so the
# relative path resolves against the current working directory. When it is
# absent, append a one-line /v:init nudge. No new env vars are introduced.
if [ ! -e ".claude/compound-v.json" ]; then
  banner="$banner Tip: run /v:init to detect backends (Codex, Context7) and pick a routing stance — saved to .claude/compound-v.json."
fi

# Detect platform and emit appropriate JSON shape
if [ -n "${CURSOR_PLUGIN_ROOT:-}" ]; then
  jq -n --arg ctx "$banner" '{additional_context: $ctx}'
elif [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -z "${COPILOT_CLI:-}" ]; then
  jq -n --arg ctx "$banner" \
    '{hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: $ctx}}'
else
  jq -n --arg ctx "$banner" '{additionalContext: $ctx}'
fi
