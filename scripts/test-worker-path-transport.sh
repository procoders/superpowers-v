#!/usr/bin/env bash
# Regression self-test for the worker gate->emit path transport (both
# compound-v-run-codex-worker.sh and compound-v-run-antigravity-worker.sh).
#
# Both workers read the scope gate's `.changed` / `.violations` JSON arrays and pass them
# THROUGH as JSON (jq --argjson) into job_result — no newline round-trip. This test mirrors
# that exact transport and proves a filename containing a LITERAL NEWLINE survives as ONE
# array element (the bug was: a newline-joined round-trip split it into two phantom paths).
# The scope gate itself is NUL-correct (compound-v-scope-check.py), so the BLOCK decision was
# always right; this guards the REPORTED arrays.
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

REPO="$TMP/repo"
mkdir -p "$REPO"
git -C "$REPO" init -q
git -C "$REPO" config user.email t@t.co
git -C "$REPO" config user.name t
echo seed > "$REPO/seed.txt"
git -C "$REPO" add -A
git -C "$REPO" commit -qm seed >/dev/null
BASE="$(git -C "$REPO" rev-parse HEAD)"

WT="$TMP/wt"
git -C "$REPO" worktree add -q "$WT" HEAD

# A filename containing a literal newline + an ordinary file.
NL="$(printf 'foo\nbar.txt')"
printf 'x' > "$WT/$NL"
printf 'y' > "$WT/normal.txt"

fail=0

run_gate() {  # $1 = allow-glob file -> echoes GATE_JSON
  python3 "$SCRIPT_DIR/compound-v-scope-check.py" \
    --worktree "$WT" --baseline "$BASE" --allow-file "$1" 2>/dev/null || true
}

# The exact worker transport: capture the gate arrays as JSON, then re-emit via --argjson.
transport() {  # $1 = GATE_JSON ; echoes the emitted files_changed+violations object
  local gj="$1" files_json violations_json
  files_json="$(printf '%s' "$gj" | jq -c '.changed // []')"
  violations_json="$(printf '%s' "$gj" | jq -c '.violations // []')"
  jq -n --argjson files "$files_json" --argjson violations "$violations_json" \
    '{files_changed: $files, violations: $violations}'
}

# --- case 1: everything allowed -> the newline name is ONE element of files_changed ------
printf '**\n' > "$TMP/allow_all"
OUT1="$(transport "$(run_gate "$TMP/allow_all")")"
n_changed="$(printf '%s' "$OUT1" | jq '.files_changed | length')"
has_nl="$(printf '%s' "$OUT1" | jq --arg p "$NL" '(.files_changed | index($p)) != null')"
if [ "$n_changed" = "2" ] && [ "$has_nl" = "true" ]; then
  echo "  case1 changed: newline filename is ONE element (2 files total) ✅"
else
  echo "  case1 FAIL: n_changed=$n_changed has_nl=$has_nl :: $OUT1"
  fail=1
fi

# --- case 2: only normal.txt allowed -> the newline name is ONE violation ----------------
printf 'normal.txt\n' > "$TMP/allow_one"
OUT2="$(transport "$(run_gate "$TMP/allow_one")")"
n_viol="$(printf '%s' "$OUT2" | jq '.violations | length')"
viol_is_nl="$(printf '%s' "$OUT2" | jq --arg p "$NL" '(.violations | index($p)) != null')"
if [ "$n_viol" = "1" ] && [ "$viol_is_nl" = "true" ]; then
  echo "  case2 violations: newline filename is ONE violation ✅"
else
  echo "  case2 FAIL: n_viol=$n_viol viol_is_nl=$viol_is_nl :: $OUT2"
  fail=1
fi

git -C "$REPO" worktree remove -f "$WT" >/dev/null 2>&1 || true

if [ "$fail" = "0" ]; then
  echo "SELFTEST PASSED"
  exit 0
fi
echo "SELFTEST FAILED"
exit 1
