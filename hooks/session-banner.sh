#!/usr/bin/env bash
# Compound V — SessionStart hook
# Emits a context-injection JSON output that prints a one-line "loaded" banner
# to the session, reminding the parent Claude that Compound V is available.
#
# Hook output format (Claude Code spec): JSON to stdout with hookSpecificOutput.
# Cursor: JSON with additional_context (snake_case).
# Generic SDK: JSON with additionalContext.
# Pattern adapted from obra/superpowers v5.1.0 hooks/session-start.

set -euo pipefail

banner="Compound V loaded — sidekick to Superpowers. Auto-fires after brainstorming (description-based discovery). Phases: code-archaeologist + domain-expert + doc-validator (parallel) → partition-reviewer → parallel-dispatcher. You do not need to invoke it manually."

# Detect platform and emit appropriate JSON shape
if [ -n "${CURSOR_PLUGIN_ROOT:-}" ]; then
  jq -n --arg ctx "$banner" '{additional_context: $ctx}'
elif [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -z "${COPILOT_CLI:-}" ]; then
  jq -n --arg ctx "$banner" \
    '{hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: $ctx}}'
else
  jq -n --arg ctx "$banner" '{additionalContext: $ctx}'
fi
