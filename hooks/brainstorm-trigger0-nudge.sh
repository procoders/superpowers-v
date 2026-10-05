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
#
# RECALL (v3.7.2). The reminder used to end at "search V-memory first" — prose an
# agent may skip, and an audit of 369 real searches found about 1% of results
# visibly used. So when the Skill call carries a topic (tool_input.args), this hook
# RUNS the V-memory search itself and appends up to 3 hits to the reminder, in the
# same framed block the pre-flight and review prompts carry (rendered by
# scripts/compound-v-emit-preflight.py --recall-query, the one renderer). No args
# -> no search, today's reminder only. The budget: the engine call is capped at
# 3 s inside the helper (FTS5 lane only, --no-refresh, so a cold embedder or a
# refresh holding the lock cannot eat it) and the helper itself at 4 s here; the
# registration carries no `timeout`, so these are the bounds. Any failure — no
# python3, no engine, no index, a timeout, garbage — drops the block and keeps
# the reminder. Never blocks, never prints outside the JSON, always exits 0.
# CV_MEMORY_ENGINE overrides the engine path (tests point it at a fake).

set -euo pipefail
if [ "${CV_HEADLESS_CLASSIFY:-}" = "1" ]; then exit 0; fi  # finding 131: never fire inside the headless classifier
# CV_DISABLED_HOOKS: comma-separated hook basenames (no .sh) to turn off. lane-guard is
# excluded on purpose — see hooks/lane-guard.sh's own header comment.
_cv_off=",$(printf '%s' "${CV_DISABLED_HOOKS:-}" | tr -d ' \t'),"
case "$_cv_off" in *",brainstorm-trigger0-nudge,"*) exit 0 ;; esac

# No jq → we cannot parse or emit safely; stay silent rather than ever block.
command -v jq >/dev/null 2>&1 || exit 0

# Read full hook event from stdin
input="$(cat)"

# Extract tool name and skill name defensively. Falls back to empty if missing
# or if stdin is not valid JSON.
tool_name=$(echo "$input" | jq -r '.tool_name // empty' 2>/dev/null || echo "")
skill_name=$(echo "$input" | jq -r '.tool_input.skill // empty' 2>/dev/null || echo "")
# The topic the skill was invoked with — a string only; anything else is no topic.
topic=$(echo "$input" | jq -r 'if (.tool_input.args|type) == "string" then .tool_input.args else empty end' 2>/dev/null || echo "")
hook_cwd=$(echo "$input" | jq -r '.cwd // empty' 2>/dev/null || echo "")

# Fire only for the Skill tool
[ "$tool_name" = "Skill" ] || exit 0

case "$skill_name" in
  superpowers:brainstorming)
    nudge="Compound V — Trigger 0 backstop: run the Trigger 0 gates from phase-0-recon.md if not already done for this brainstorm (reminder only — the gates in that doc decide whether recon actually runs)."
    ;;
  superpowers:writing-plans)
    nudge="Compound V — Trigger 1: the spec has passed brainstorming's user-review gate — writing-plans is invoked only after the user approved the spec, so the approved spec is what the audits must read. BEFORE writing the plan, run the three pre-flights (code-archaeologist ∥ domain-expert ∥ doc-validator) on that approved spec as ONE native Workflow on Engine C: python3 scripts/compound-v-emit-preflight.py --spec <spec> --out … then Workflow({ scriptPath }) — see skills/compound-v/SKILL.md \"Trigger 1\". Then write the plan with the three audits as design-constraint sources. ALL THREE: doc-validator is skipped only when the spec has ZERO technical dependencies — \"no NEW dependency\" is not the rule, because dependencies you already use go stale and acquire CVEs. If this spec RESCOPES work whose earlier features already went through the pipeline, that earlier compliance does not carry: the rescope re-enters at the top."
    ;;
  *)
    exit 0
    ;;
esac

# Run a command with a wall-clock bound, portably (macOS has no timeout(1)): a
# background child plus a polling waiter, TERM then KILL. Same shape as
# precompact-snapshot.sh's _bounded. Prints the child's stdout only on rc 0.
_bounded() {
  local limit_tenths="$1"; shift
  local out rc waited pid grace
  out="$(mktemp "${TMPDIR:-/tmp}/cv-t0-recall.XXXXXX" 2>/dev/null)" || return 1
  ( "$@" >"$out" 2>/dev/null ) &
  pid=$!
  waited=0
  while [ "$waited" -lt "$limit_tenths" ]; do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.1
    waited=$((waited + 1))
  done
  if kill -0 "$pid" 2>/dev/null; then
    kill -TERM "$pid" 2>/dev/null
    grace=0
    while [ "$grace" -lt 5 ]; do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.1
      grace=$((grace + 1))
    done
    kill -0 "$pid" 2>/dev/null && kill -KILL "$pid" 2>/dev/null
    wait "$pid" 2>/dev/null || true
    rm -f "$out" 2>/dev/null
    return 1
  fi
  rc=0
  wait "$pid" 2>/dev/null || rc=$?
  if [ "$rc" -ne 0 ]; then rm -f "$out" 2>/dev/null; return 1; fi
  cat "$out" 2>/dev/null
  rm -f "$out" 2>/dev/null
  return 0
}

recall_block=""
if [ -n "$topic" ] && command -v python3 >/dev/null 2>&1; then
  plugin_root="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." 2>/dev/null && pwd)}"
  helper="$plugin_root/scripts/compound-v-emit-preflight.py"
  engine="${CV_MEMORY_ENGINE:-$plugin_root/scripts/compound-v-memory.py}"
  if [ -f "$helper" ]; then
    set -- python3 -B "$helper" "--recall-query=$topic" --recall-engine "$engine" \
      --recall-top 3 --recall-timeout 3 --no-embed
    if [ -n "$hook_cwd" ] && [ -d "$hook_cwd" ]; then set -- "$@" --repo "$hook_cwd"; fi
    recall_block=$(PYTHONDONTWRITEBYTECODE=1 _bounded 40 "$@" || true)
  fi
fi
if [ -n "$recall_block" ]; then
  nudge="$nudge

$recall_block"
fi

# Emit context-injection JSON per platform
if [ -n "${CURSOR_PLUGIN_ROOT:-}" ]; then
  jq -n --arg ctx "$nudge" '{additional_context: $ctx}'
elif [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -z "${COPILOT_CLI:-}" ]; then
  jq -n --arg ctx "$nudge" \
    '{hookSpecificOutput: {hookEventName: "PreToolUse", additionalContext: $ctx}}'
else
  jq -n --arg ctx "$nudge" '{additionalContext: $ctx}'
fi
