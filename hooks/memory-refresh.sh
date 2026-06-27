#!/usr/bin/env bash
# Compound V — V-memory refresh hook (SessionStart + PostToolUse:Write).
#
# Non-blocking + SILENT: self-backgrounds a `refresh --quick` and returns in ~ms, so it
# never stalls SessionStart or a Write. It emits NO context output, so it composes cleanly
# with session-banner.sh / plan-saved-nudge.sh (those still fire and inject their context).
#
# It NEVER installs or downloads: `refresh` without --with-embeddings is FTS5-only and
# offline. Embeddings are bootstrapped only by the explicit `/v:memory-refresh
# --with-embeddings` / `bootstrap` path, never from a hook.
#
# The index cache lives OUTSIDE the repo (~/.cache/compound-v/memory/<repo-id>/), so a
# refresh can never write into the working tree and therefore can never dirty a dispatch
# worker's git scope gate. Concurrent fires (a Write storm during dispatch, or SessionStart
# racing a Write) are safe: the engine's flock makes every loser an instant no-op.

set -euo pipefail

input="$(cat 2>/dev/null || true)"
file_path=$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty' 2>/dev/null || echo "")

# PostToolUse:Write carries a file_path — only react to writes under docs/superpowers.
# SessionStart carries no file_path — always do a quick refresh.
if [ -n "$file_path" ]; then
  case "$file_path" in
    */docs/superpowers/*) : ;;
    *) exit 0 ;;
  esac
fi

script="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}/scripts/compound-v-memory.py"
command -v python3 >/dev/null 2>&1 || exit 0
[ -f "$script" ] || exit 0

# Detach: nohup + background + redirected fds so the session returns immediately.
nohup python3 "$script" refresh --quick </dev/null >/dev/null 2>&1 &
exit 0
