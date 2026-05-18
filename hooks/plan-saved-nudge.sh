#!/usr/bin/env bash
# Compound V — PostToolUse(Write) nudge
# Fires after any Write tool call. Checks if the written file is a Compound-V-relevant
# artifact (a plan, a spec, an audit) and nudges the parent Claude with the next step.
#
# Reads the written file path from CLAUDE_TOOL_INPUT_FILE_PATH (set by the harness).

path="${CLAUDE_TOOL_INPUT_FILE_PATH:-}"

# Bail if we don't have a path or it's not a Compound-V-relevant file
[ -z "$path" ] && exit 0

case "$path" in
  *docs/superpowers/plans/*.md)
    cat <<EOF
💉 Compound V nudge — plan saved at $path
   Before dispatching: run /v:dispatch $path
   (Runs compound-v:partition-reviewer first, then compound-v:parallel-dispatcher if PASS.)
EOF
    ;;
  *docs/superpowers/specs/*.md)
    cat <<EOF
💉 Compound V nudge — spec saved at $path
   If this came from brainstorming, dispatch the three pre-flights in parallel before writing-plans:
   compound-v:code-archaeologist  ∥  compound-v:domain-expert  ∥  compound-v:doc-validator
EOF
    ;;
  *)
    # Not a Compound-V-relevant artifact
    exit 0
    ;;
esac
