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

banner="Compound V loaded — sidekick to Superpowers. Auto-fires before brainstorming (gated recon) and after it (pre-flights) — description-based discovery. Phases: recon → code-archaeologist + domain-expert + doc-validator (parallel) → partition-reviewer → parallel-dispatcher. You do not need to invoke it manually."

# First-run setup hint: the project stance config is .claude/compound-v.json
# (project-level, committed). SessionStart runs from the project root, so the
# relative path resolves against the current working directory. When it is
# absent, append a one-line /v:init nudge. No new env vars are introduced.
if [ ! -e ".claude/compound-v.json" ]; then
  banner="$banner Tip: run /v:init to detect backends (Codex, Context7) and pick a routing stance — saved to .claude/compound-v.json."
fi

# Read-only onboarding staleness nudge. MUST fail silent: set -euo pipefail would
# abort the whole banner on any non-zero exit, so guard python and swallow errors.
if command -v python3 >/dev/null 2>&1 && [ -e "docs/superpowers/architecture/.onboard-manifest.json" ]; then
  stale=$(python3 "${CLAUDE_PLUGIN_ROOT:-.}/scripts/compound-v-onboard.py" staleness --quiet 2>/dev/null || echo 0)
  if [ "${stale:-0}" -gt 0 ] 2>/dev/null; then
    banner="$banner ⚠ $stale architecture doc(s) stale vs HEAD — run /v:onboard --refresh."
  fi
fi

# Anti-amnesia resume context (v2.19). SessionStart fires on `compact` as well as
# `startup`, but the banner above is STATELESS -- it says the same thing to a fresh
# session and to one that was six hours into a 16-job dispatch. That gap is the
# reported "Claude forgets" failure: what a compaction destroys is not the rules
# (they come back with the skill) but the agent's POSITION in the pipeline. This
# reads it back off disk. Read-only, and MUST fail silent for the same reason as
# the staleness probe above: set -euo pipefail would abort the whole banner.
if command -v python3 >/dev/null 2>&1 && [ -d "docs/superpowers/execution" ]; then
  resume=$(python3 "${CLAUDE_PLUGIN_ROOT:-.}/scripts/compound-v-dashboard.py" resume 2>/dev/null || echo "")
  if [ -n "${resume:-}" ]; then
    banner="$banner $resume"
  fi
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
