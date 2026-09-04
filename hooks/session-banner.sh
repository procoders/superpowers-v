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
if [ "${CV_HEADLESS_CLASSIFY:-}" = "1" ]; then exit 0; fi  # finding 131: never fire inside the headless classifier

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

# Version floor probe. Compound V 3.x hands execution to the native Workflow runtime
# and to native hook events that landed in Claude Code 2.1.219; below that floor the
# pipeline simply does not run, and README claimed the floor for months with nothing
# anywhere that checked it. SessionStart is the one place a user reliably reads a
# warning. One extra process, read-only, and it MUST fail silent: a missing binary, a
# refused exec, or output this does not recognise says NOTHING rather than guessing a
# version. No `timeout` wrapper — it is absent from a default macOS, and the hook is
# already bounded by `timeout: 10` on its registration in hooks/hooks.json.
CV_VERSION_FLOOR="${CV_VERSION_FLOOR:-2.1.219}"

# Strictly-lower comparison over major.minor.patch, numeric PER COMPONENT: 2.1.9 is
# lower than 2.1.219, which a lexical compare gets backwards. No `sort -V` — BSD sort
# on macOS did not always carry it, and a fallback ladder is more code than this.
_semver_lt() {
  local l="$1" r="$2" lp rp i
  for _ in 1 2 3; do
    lp="${l%%.*}"; rp="${r%%.*}"
    case "$lp" in ''|*[!0-9]*) return 1 ;; esac
    case "$rp" in ''|*[!0-9]*) return 1 ;; esac
    if [ "$lp" -lt "$rp" ]; then return 0; fi
    if [ "$lp" -gt "$rp" ]; then return 1; fi
    l="${l#*.}"; r="${r#*.}"
  done
  return 1
}

if command -v claude >/dev/null 2>&1; then
  _cv_ver_raw="$(claude --version 2>/dev/null || true)"
  _cv_ver_re='([0-9]+\.[0-9]+\.[0-9]+)'
  if [[ "$_cv_ver_raw" =~ $_cv_ver_re ]]; then
    _cv_ver="${BASH_REMATCH[1]}"
    if _semver_lt "$_cv_ver" "$CV_VERSION_FLOOR"; then
      banner="$banner ⚠ Claude Code $_cv_ver < $CV_VERSION_FLOOR — Compound V 3.x needs native Workflows/hooks; update."
    fi
  fi
fi

# JSON, WITHOUT REQUIRING jq, AND IN THE SHAPE THE RUNTIME ACTUALLY READS.
#
# Two defects a Phase-1B audit found here, both live:
#
#   1. The generic branch emitted a bare top-level `{"additionalContext": ...}`.
#      That key is only recognised INSIDE `hookSpecificOutput` alongside a
#      `hookEventName` — the binary's own hook-output table lists exactly that
#      shape — so a bare one is an unrecognised key and is DISCARDED. The branch
#      was reached whenever `CLAUDE_PLUGIN_ROOT` was unset, which happens, and the
#      banner then silently did nothing at all.
#   2. `jq` is not installed by default on macOS or on most Linux images, and this
#      script runs under `set -euo pipefail`. A missing `jq` did not degrade the
#      banner — it killed it, on every session start, with no diagnostic.
#
# So: Claude's shape is the DEFAULT rather than a branch conditional on an
# environment variable, and the JSON is written by hand when jq is absent. Only
# two characters need escaping for a JSON string built from our own banner text —
# backslash and double quote — plus the control characters a banner never carries
# but a pasted run-id could.
# NEWLINE AND CARRIAGE RETURN ARE THE TWO THAT MATTER, and the first version of
# this function deleted every control byte EXCEPT those two — so a banner carrying
# a newline emitted a literal LF inside a JSON string, which is invalid JSON. A
# cross-model review probed it byte-for-byte; the comment claiming control
# characters were handled was false.
#
# python3 is already a hard dependency of this hook's own resume query, so the
# escaping is done by the one thing on this machine that is definitionally correct
# about JSON. The sed path remains only for a machine with no python3 at all, and
# it now escapes LF and CR rather than passing them through.
_json_escape() {
  if command -v python3 >/dev/null 2>&1; then
    printf '%s' "$1" | python3 -c 'import json,sys; s=json.dumps(sys.stdin.read()); sys.stdout.write(s[1:-1])'
    return
  fi
  printf '%s' "$1" | LC_ALL=C sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' \
    -e 's/\t/\\t/g' -e 's/\r/\\r/g' \
    | LC_ALL=C awk 'NR>1{printf "\\n"} {printf "%s", $0}' \
    | LC_ALL=C tr -d '\000-\010\013\014\016-\037'
}

_emit_json() {
  # $1 = the full JSON body, already escaped
  printf '%s\n' "$1"
}

_ctx="$(_json_escape "$banner")"
if [ -n "${CURSOR_PLUGIN_ROOT:-}" ]; then
  _emit_json "{\"additional_context\": \"${_ctx}\"}"
elif [ -n "${COPILOT_CLI:-}" ]; then
  _emit_json "{\"additionalContext\": \"${_ctx}\"}"
else
  # Claude Code and anything that speaks its hook contract — the default, because
  # a missing CLAUDE_PLUGIN_ROOT is not evidence of a different harness.
  _emit_json "{\"hookSpecificOutput\": {\"hookEventName\": \"SessionStart\", \"additionalContext\": \"${_ctx}\"}}"
fi
