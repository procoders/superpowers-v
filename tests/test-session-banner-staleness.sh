#!/usr/bin/env bash
# The banner MUST still emit valid JSON even if the staleness probe fails.
set -uo pipefail
cd "$(mktemp -d)"
PATH_NO_PY="/usr/bin:/bin"   # simulate python3 absent
out=$(PATH="$PATH_NO_PY" bash "$OLDPWD/hooks/session-banner.sh" 2>/dev/null || true)
echo "$out" | jq -e '.additionalContext // .additional_context // .hookSpecificOutput' >/dev/null \
  && echo "PASS banner emits under probe failure" || { echo "FAIL"; exit 1; }

# --- Version floor probe: the banner warns below 2.1.219 and stays silent above it. ---
REPO="$OLDPWD"
fake="$(mktemp -d)"
_fake_claude() { printf '#!/bin/sh\necho "%s"\n' "$1" > "$fake/claude"; chmod +x "$fake/claude"; }
_banner() { PATH="$fake:$PATH" bash "$REPO/hooks/session-banner.sh" 2>/dev/null || true; }

_fake_claude "2.1.100 (Claude Code)"
warn="$(_banner)"
# The em dash is \u2014-escaped by the JSON writer, so assert on the ASCII halves.
case "$warn" in
  *"Claude Code 2.1.100 < 2.1.219"*) : ;;
  *) echo "FAIL old version did not warn"; exit 1 ;;
esac
case "$warn" in
  *"Compound V 3.x needs native Workflows/hooks; update."*)
    echo "PASS old version warns (numeric compare: 100 < 219)" ;;
  *) echo "FAIL warning text truncated"; exit 1 ;;
esac

_fake_claude "2.2.0 (Claude Code)"
case "$(_banner)" in
  *"needs native Workflows/hooks"*) echo "FAIL new version warned"; exit 1 ;;
  *) echo "PASS new version silent" ;;
esac

_fake_claude "2.1.219 (Claude Code)"
case "$(_banner)" in
  *"needs native Workflows/hooks"*) echo "FAIL floor itself warned"; exit 1 ;;
  *) echo "PASS floor itself silent" ;;
esac

_fake_claude "no version here"
case "$(_banner)" in
  *"needs native Workflows/hooks"*) echo "FAIL unparseable output warned"; exit 1 ;;
  *) echo "PASS unparseable output silent" ;;
esac

out=$(PATH="/usr/bin:/bin" bash "$REPO/hooks/session-banner.sh" 2>/dev/null || true)
case "$out" in
  *"needs native Workflows/hooks"*) echo "FAIL missing claude binary warned"; exit 1 ;;
  *) echo "PASS missing claude binary silent" ;;
esac
rm -rf "$fake"

# --- issue #21: an empty onboard manifest is reported, never silently "0 stale". ---
emp="$(mktemp -d)"; mkdir -p "$emp/docs/superpowers/architecture"
printf '{"generated":"2026-07-16","docs":{}}' > "$emp/docs/superpowers/architecture/.onboard-manifest.json"
out="$(cd "$emp" && CLAUDE_PLUGIN_ROOT="$REPO" bash "$REPO/hooks/session-banner.sh" 2>/dev/null || true)"
case "$out" in
  *"registers no cited files"*) echo "PASS empty manifest is reported as unregistered" ;;
  *) echo "FAIL empty manifest was silent"; exit 1 ;;
esac
echo "$out" | jq -e '.hookSpecificOutput.additionalContext' >/dev/null || { echo "FAIL banner JSON invalid"; exit 1; }
echo "PASS banner staleness suite"
