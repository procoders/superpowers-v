#!/usr/bin/env bash
# Compound V — SubagentStop nudge
# Fires when a Superpowers subagent (brainstorming or writing-plans) finishes.
# Prints a reminder so the parent Claude invokes Compound V at the right transition.
#
# Reads the matcher name from the CLAUDE_HOOK_MATCHER env var (set by the harness).

matcher="${CLAUDE_HOOK_MATCHER:-unknown}"

case "$matcher" in
  brainstorming)
    cat <<'EOF'
💉 Compound V nudge — brainstorming complete.
   Trigger 1: dispatch the three pre-flights in parallel BEFORE writing-plans:
     1. Task: compound-v:code-archaeologist  (Phase 1A — existing code reality)
     2. Task: compound-v:domain-expert       (Phase 1B — product/domain reality + audience search)
     3. Task: compound-v:doc-validator       (Phase 1C — library currency via Context7)
   All three in ONE message with three concurrent Task calls. Then invoke writing-plans
   with the three audits attached as design-constraint sources.
EOF
    ;;
  writing-plans)
    cat <<'EOF'
💉 Compound V nudge — writing-plans complete.
   Trigger 2 + 3: before dispatching implementers, run:
     1. Task: compound-v:partition-reviewer  (verifies the plan's Partition Map is disjoint)
     2. If PASS → Task: compound-v:parallel-dispatcher  (batched parallel Opus dispatch)
   Or use the /v:dispatch <plan-path> command to do both in one shot.
EOF
    ;;
  *)
    # Unknown matcher — do nothing
    ;;
esac
