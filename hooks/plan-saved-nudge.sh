#!/usr/bin/env bash
# Compound V — PostToolUse(Write) hook
# Fires after any Write tool call. Reads the hook event JSON from stdin,
# checks if the written file is a Compound-V-relevant artifact (plan, spec, or
# recon doc), and if so, emits a context-injection nudge with the next step.
# Note: the recon arm fires AFTER a recon doc is written — it reinforces the
# recon→brainstorm handoff but does NOT backstop Trigger 0's pre-fire gap
# (nothing is written before a brainstorm begins).
#
# Hook input format (Claude Code spec): JSON on stdin with tool_input.file_path
# (per https://docs.claude.com/en/docs/claude-code/hooks). Patterns use a
# leading `*` (not `*/`) so RELATIVE paths like docs/superpowers/plans/x.md
# match too — Write tool_input.file_path is not guaranteed absolute (A20).
# Output format: JSON on stdout with hookSpecificOutput.additionalContext.

set -euo pipefail

# Read full hook event from stdin
input="$(cat)"

# Extract the written file's path. Falls back to empty if missing.
file_path=$(echo "$input" | jq -r '.tool_input.file_path // empty' 2>/dev/null || echo "")

# No path → not a write we care about
[ -z "$file_path" ] && exit 0

# Match Compound-V-relevant artifacts
nudge=""
case "$file_path" in
  *docs/superpowers/plans/*.md)
    nudge="💉 Compound V — plan saved at $file_path. To execute: invoke compound-v:partition-reviewer first (verify Partition Map is disjoint), then compound-v:parallel-dispatcher. Shortcuts: /v:orchestrate $file_path materializes a manifest from the plan, or /v:dispatch $file_path runs the pipeline directly (it still accepts a bare plan path)."
    ;;
  *docs/superpowers/specs/*.md)
    nudge="💉 Compound V — spec saved at $file_path. If this came from brainstorming, dispatch the three pre-flights IN ONE MESSAGE WITH THREE PARALLEL TASK CALLS: compound-v:code-archaeologist, compound-v:domain-expert, compound-v:doc-validator. Then writing-plans with the three audits as design-constraint sources."
    ;;
  *docs/superpowers/recon/*.md)
    nudge="💉 Compound V — recon saved at $file_path. Start the brainstorm with it: read it before the first question; treat DIRECTIONS as non-exhaustive."
    ;;
  *)
    # Not relevant — exit silently
    exit 0
    ;;
esac

# Emit context-injection JSON per platform
if [ -n "${CURSOR_PLUGIN_ROOT:-}" ]; then
  jq -n --arg ctx "$nudge" '{additional_context: $ctx}'
elif [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -z "${COPILOT_CLI:-}" ]; then
  jq -n --arg ctx "$nudge" \
    '{hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: $ctx}}'
else
  jq -n --arg ctx "$nudge" '{additionalContext: $ctx}'
fi
