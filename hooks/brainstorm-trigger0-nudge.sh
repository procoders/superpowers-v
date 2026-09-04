#!/usr/bin/env bash
# Compound V — PreToolUse(Skill) hook: Trigger-0 AND Trigger-1 backstop
# Fires on two Superpowers skill invocations and injects a one-line idempotent
# reminder for the Compound V trigger that belongs at that transition:
#   * superpowers:brainstorming  -> Trigger 0 (run the gates in phase-0-recon.md)
#   * superpowers:writing-plans  -> Trigger 1 (run the three pre-flights FIRST)
# Trigger 1 is nudged HERE, not when the spec file is written, because
# brainstorming puts a user-review gate between the two: its state machine goes
# "User reviews spec?" -> "Invoke writing-plans skill" [approved]
# (superpowers/6.2.0/skills/brainstorming/SKILL.md:55-57), the User Review Gate
# says "Wait for the user's response ... Only proceed once the user approves"
# (:122-127), and "The ONLY skill you invoke after brainstorming is
# writing-plans" (:61). So the invocation of writing-plans — not the Write that
# saves the spec — is the moment the spec is approved, and the pre-flights must
# run on an APPROVED spec.
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
if [ "${CV_HEADLESS_CLASSIFY:-}" = "1" ]; then exit 0; fi  # finding 131: never fire inside the headless classifier

# No jq → we cannot parse or emit safely; stay silent rather than ever block.
command -v jq >/dev/null 2>&1 || exit 0

# Read full hook event from stdin
input="$(cat)"

# Extract tool name and skill name defensively. Falls back to empty if missing
# or if stdin is not valid JSON.
tool_name=$(echo "$input" | jq -r '.tool_name // empty' 2>/dev/null || echo "")
skill_name=$(echo "$input" | jq -r '.tool_input.skill // empty' 2>/dev/null || echo "")

# Fire only for the Skill tool
[ "$tool_name" = "Skill" ] || exit 0

case "$skill_name" in
  superpowers:brainstorming)
    nudge="💉 Compound V — Trigger 0 backstop: run the Trigger 0 gates from phase-0-recon.md if not already done for this brainstorm (reminder only — the gates in that doc decide whether recon actually runs)."
    ;;
  superpowers:writing-plans)
    nudge="💉 Compound V — Trigger 1: the spec has passed brainstorming's user-review gate — writing-plans is invoked only after the user approved the spec, so the approved spec is what the audits must read. BEFORE writing the plan, run the three pre-flights (code-archaeologist ∥ domain-expert ∥ doc-validator) on that approved spec as ONE native Workflow on Engine C: python3 scripts/compound-v-emit-preflight.py --spec <spec> --out … then Workflow({ scriptPath }) — see skills/compound-v/SKILL.md \"Trigger 1\". Then write the plan with the three audits as design-constraint sources. ALL THREE: doc-validator is skipped only when the spec has ZERO technical dependencies — \"no NEW dependency\" is not the rule, because dependencies you already use go stale and acquire CVEs. If this spec RESCOPES work whose earlier features already went through the pipeline, that earlier compliance does not carry: the rescope re-enters at the top."
    ;;
  *)
    exit 0
    ;;
esac

# Emit context-injection JSON per platform
if [ -n "${CURSOR_PLUGIN_ROOT:-}" ]; then
  jq -n --arg ctx "$nudge" '{additional_context: $ctx}'
elif [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -z "${COPILOT_CLI:-}" ]; then
  jq -n --arg ctx "$nudge" \
    '{hookSpecificOutput: {hookEventName: "PreToolUse", additionalContext: $ctx}}'
else
  jq -n --arg ctx "$nudge" '{additionalContext: $ctx}'
fi
