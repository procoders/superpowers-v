#!/usr/bin/env bash
trap 'exit 0' EXIT
root="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
py="$(command -v python3)" || exit 0
"$py" -I -B "$root/scripts/compound-v.py" hook subagent >/dev/null 2>&1
exit 0
