#!/usr/bin/env bash
# Compound V — PreToolUse(Skill) hook: Trigger-0 backstop
# Fires when the Skill tool invokes superpowers:brainstorming and injects a
# one-line idempotent reminder to run the Trigger 0 gates from phase-0-recon.md.
# Reminder only, never enforcement: it emits additionalContext exclusively —
# no permissionDecision, no blocking exit code — and is silent (exit 0) for
# every other tool, skill, or malformed input.
#
# PROBE VERDICT (2026-07-11, installed Claude Code 2.1.197): PreToolUse — PROVEN.
# Evidence, strongest first:
#   1. LIVE PROBE: nested `claude -p --settings` session with a PreToolUse(Bash)
#      hook emitting {"hookSpecificOutput":{"hookEventName":"PreToolUse",
#      "additionalContext":"PROBE_TOKEN_XYZ123 ..."}} — the model received the
#      injected context (as a PreToolUse-hook system-reminder next to the tool
#      result) and repeated PROBE_TOKEN_XYZ123 verbatim. Exit 0, empty stderr.
#   2. Installed-binary strings (~/.local/share/claude/versions/2.1.197): the
#      hook-output handler's `case "PreToolUse"` branch assigns
#      `u.additionalContext = e.hookSpecificOutput.additionalContext`.
#      (The binary's schema HELP text omits additionalContext for PreToolUse —
#      help-string staleness; the runtime handler and the live probe win.)
#   3. Official docs (code.claude.com/docs/en/hooks, fetched 2026-07-11):
#      PreToolUse listed among events supporting hookSpecificOutput.
#      additionalContext ("next to the tool result").
#
# Hook input format (Claude Code spec): JSON on stdin with tool_name and
# tool_input; the Skill tool's input carries the skill name in tool_input.skill.
# Output format: JSON on stdout with hookSpecificOutput.additionalContext.

set -euo pipefail

# No jq → we cannot parse or emit safely; stay silent rather than ever block.
command -v jq >/dev/null 2>&1 || exit 0

# Read full hook event from stdin
input="$(cat)"

# Extract tool name and skill name defensively. Falls back to empty if missing
# or if stdin is not valid JSON.
tool_name=$(echo "$input" | jq -r '.tool_name // empty' 2>/dev/null || echo "")
skill_name=$(echo "$input" | jq -r '.tool_input.skill // empty' 2>/dev/null || echo "")

# Fire only for the Skill tool invoking superpowers:brainstorming
[ "$tool_name" = "Skill" ] || exit 0
[ "$skill_name" = "superpowers:brainstorming" ] || exit 0

nudge="💉 Compound V — Trigger 0 backstop: run the Trigger 0 gates from phase-0-recon.md if not already done for this brainstorm (reminder only — the gates in that doc decide whether recon actually runs)."

# Emit context-injection JSON per platform
if [ -n "${CURSOR_PLUGIN_ROOT:-}" ]; then
  jq -n --arg ctx "$nudge" '{additional_context: $ctx}'
elif [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -z "${COPILOT_CLI:-}" ]; then
  jq -n --arg ctx "$nudge" \
    '{hookSpecificOutput: {hookEventName: "PreToolUse", additionalContext: $ctx}}'
else
  jq -n --arg ctx "$nudge" '{additionalContext: $ctx}'
fi
