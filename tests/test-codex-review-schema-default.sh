#!/usr/bin/env bash
# The codex-review default schema MUST resolve relative to the PLUGIN (this repo),
# not the reviewed target repo — a target repo without schemas/ must get past the
# schema check (and then fail on a LATER validation we provoke deliberately).
set -uo pipefail
SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/scripts/compound-v-codex-review.sh"
T="$(mktemp -d)"
echo plan > "$T/plan.md"
mkdir "$T/repo"   # deliberately NO schemas/ dir here
err=$(bash "$SCRIPT" --plan-file "$T/plan.md" --repo "$T/repo" --effort bogus 2>&1 || true)
case "$err" in
  *"schema not found"*) echo "FAIL schema default still resolves against --repo: $err"; exit 1 ;;
  *"--effort must be"*) echo "PASS schema default resolves from the plugin dir" ;;
  *) echo "FAIL unexpected error: $err"; exit 1 ;;
esac
