#!/usr/bin/env bash
# The banner MUST still emit valid JSON even if the staleness probe fails.
set -uo pipefail
cd "$(mktemp -d)"
PATH_NO_PY="/usr/bin:/bin"   # simulate python3 absent
out=$(PATH="$PATH_NO_PY" bash "$OLDPWD/hooks/session-banner.sh" 2>/dev/null || true)
echo "$out" | jq -e '.additionalContext // .additional_context // .hookSpecificOutput' >/dev/null \
  && echo "PASS banner emits under probe failure" || { echo "FAIL"; exit 1; }
