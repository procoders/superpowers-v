#!/usr/bin/env bash
# tests/test-skill-nudges.sh — the two reminder hooks that carry Trigger 0 and Trigger 1.
#
# 3.4.17 moved Trigger 1 (the three pre-flights) from the spec arm of plan-saved-nudge.sh
# to the writing-plans branch of brainstorm-trigger0-nudge.sh. The reason is a gate, not a
# preference: brainstorming WRITES the spec, then asks the user to review it
# (superpowers/6.2.0/skills/brainstorming/SKILL.md:122-127), and only an approved spec
# reaches writing-plans (:55-57 and :61 — "The ONLY skill you invoke after brainstorming
# is writing-plans"). Auditing at spec-write time audits an unapproved spec.
#
# These assertions are the mechanism, not the prose: a hook that stops branching, or a
# spec arm that grows a dispatch instruction back, fails here.
# bash 3.2 compatible (macOS stock). Run: bash tests/test-skill-nudges.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
T0_HOOK="$REPO/hooks/brainstorm-trigger0-nudge.sh"
PS_HOOK="$REPO/hooks/plan-saved-nudge.sh"

pass=0
fail=0
ok()  { pass=$((pass + 1)); printf 'PASS %s\n' "$1"; }
bad() { fail=$((fail + 1)); printf 'FAIL %s\n' "$1"; }

if ! command -v jq >/dev/null 2>&1; then
  printf 'FAIL tests/test-skill-nudges.sh: jq is required (both hooks refuse to parse without it)\n'
  exit 1
fi

# Run a hook with a payload; echoes stdout, sets RC. Never aborts the suite under set -e.
RC=0
run_hook() {
  # $1 = hook path, $2 = stdin payload, rest = extra env assignments
  local hook="$1" payload="$2"
  shift 2
  set +e
  OUT=$(printf '%s' "$payload" | env CLAUDE_PLUGIN_ROOT="$REPO" "$@" bash "$hook" 2>/dev/null)
  RC=$?
  set -e
}

contains() { case "$1" in *"$2"*) return 0 ;; *) return 1 ;; esac; }

# --- brainstorm-trigger0-nudge.sh -------------------------------------------------

run_hook "$T0_HOOK" '{"tool_name":"Skill","tool_input":{"skill":"superpowers:brainstorming"}}'
ctx=$(printf '%s' "$OUT" | jq -r '.hookSpecificOutput.additionalContext // empty' 2>/dev/null || echo "")
if [ "$RC" = "0" ] && contains "$ctx" "Trigger 0"; then
  ok "brainstorming -> additionalContext names Trigger 0"
else
  bad "brainstorming: rc=$RC ctx=${ctx:0:80}"
fi

run_hook "$T0_HOOK" '{"tool_name":"Skill","tool_input":{"skill":"superpowers:writing-plans"}}'
ctx=$(printf '%s' "$OUT" | jq -r '.hookSpecificOutput.additionalContext // empty' 2>/dev/null || echo "")
if [ "$RC" = "0" ] && contains "$ctx" "Trigger 1"; then
  ok "writing-plans -> additionalContext names Trigger 1"
else
  bad "writing-plans: no Trigger 1 (rc=$RC) ctx=${ctx:0:80}"
fi
if contains "$ctx" "pre-flights"; then
  ok "writing-plans -> nudge tells the agent to run the pre-flights"
else
  bad "writing-plans: nudge does not mention pre-flights"
fi
# The Trigger-1 nudge must not be the Trigger-0 text: same hook, different branch.
if contains "$ctx" "Trigger 0 backstop"; then
  bad "writing-plans: emitted the Trigger 0 backstop text instead of the Trigger 1 nudge"
else
  ok "writing-plans -> does NOT emit the Trigger 0 backstop text"
fi

run_hook "$T0_HOOK" '{"tool_name":"Skill","tool_input":{"skill":"superpowers:test-driven-development"}}'
if [ "$RC" = "0" ] && [ -z "$OUT" ]; then
  ok "an unrelated skill -> silent, rc 0"
else
  bad "unrelated skill: rc=$RC out=${OUT:0:80}"
fi

run_hook "$T0_HOOK" '{"tool_name":"Write","tool_input":{"file_path":"README.md"}}'
if [ "$RC" = "0" ] && [ -z "$OUT" ]; then
  ok "a non-Skill tool -> silent, rc 0"
else
  bad "non-Skill tool: rc=$RC out=${OUT:0:80}"
fi

run_hook "$T0_HOOK" '{"tool_name":"Skill","tool_input":{'
if [ "$RC" = "0" ] && [ -z "$OUT" ]; then
  ok "malformed JSON -> silent, rc 0 (a hook must never block on garbage in)"
else
  bad "malformed JSON: rc=$RC out=${OUT:0:80}"
fi

# Cursor speaks a different output shape; the branch has to survive the rename.
run_hook "$T0_HOOK" '{"tool_name":"Skill","tool_input":{"skill":"superpowers:writing-plans"}}' \
  CURSOR_PLUGIN_ROOT="$REPO"
ctx=$(printf '%s' "$OUT" | jq -r '.additional_context // empty' 2>/dev/null || echo "")
if [ "$RC" = "0" ] && contains "$ctx" "Trigger 1"; then
  ok "CURSOR_PLUGIN_ROOT -> emits additional_context carrying the Trigger 1 nudge"
else
  bad "cursor variant: rc=$RC ctx=${ctx:0:80}"
fi

# --- plan-saved-nudge.sh ----------------------------------------------------------

run_hook "$PS_HOOK" '{"tool_name":"Write","tool_input":{"file_path":"docs/superpowers/specs/2026-09-04-x-design.md"}}'
ctx=$(printf '%s' "$OUT" | jq -r '.hookSpecificOutput.additionalContext // empty' 2>/dev/null || echo "")
if [ "$RC" = "0" ] && [ -n "$ctx" ]; then
  ok "spec write -> still emits a nudge"
else
  bad "spec write: rc=$RC ctx=${ctx:0:80}"
fi
if contains "$ctx" "THREE PARALLEL"; then
  bad "spec write: still orders THREE PARALLEL task calls at spec-write time"
else
  ok "spec write -> no longer orders THREE PARALLEL task calls"
fi
if contains "$ctx" "dispatch the three pre-flights"; then
  bad "spec write: still dispatches the three pre-flights before the user-review gate"
else
  ok "spec write -> no longer dispatches the pre-flights before the user-review gate"
fi
if contains "$ctx" "writing-plans"; then
  ok "spec write -> points at writing-plans as the moment Trigger 1 fires"
else
  bad "spec write: nudge never mentions writing-plans"
fi

run_hook "$PS_HOOK" '{"tool_name":"Write","tool_input":{"file_path":"docs/superpowers/plans/2026-09-04-x-plan.md"}}'
ctx=$(printf '%s' "$OUT" | jq -r '.hookSpecificOutput.additionalContext // empty' 2>/dev/null || echo "")
if [ "$RC" = "0" ] && contains "$ctx" "/v:dispatch"; then
  ok "plan write -> unchanged, still points at /v:dispatch"
else
  bad "plan write: rc=$RC ctx=${ctx:0:80}"
fi

printf 'tests/test-skill-nudges.sh: %d passed, %d failed\n' "$pass" "$fail"
[ "$fail" = "0" ] || exit 1
