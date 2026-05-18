#!/usr/bin/env bash
# Compound V — SessionStart banner
# Prints a one-line reminder that Compound V is loaded and what it does.
# Output goes to Claude's session context as a system message.

cat <<'EOF'
💉 Compound V loaded — sidekick to Superpowers.
   Auto-fires after brainstorming (3 parallel pre-flights: archaeology + domain-expert + library-validator).
   Enforces Disjoint Partition Map. Dispatches implementers in parallel on Opus (Sonnet only for narrow junior carve-out).
   You do not need to invoke it — just use Superpowers normally.
EOF
