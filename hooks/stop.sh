#!/usr/bin/env bash
trap 'exit 0' EXIT
root="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
py="$(command -v python3)" || exit 0
out="$("$py" -I -B "$root/scripts/compound-v.py" hook stop 2>/dev/null)" || exit 0
[ -n "$out" ] && printf '%s\n' "$out"
exit 0
