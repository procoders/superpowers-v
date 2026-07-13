#!/usr/bin/env bash
#
# test-advisor-worker-stub.sh — stub-first proof for the READ-ONLY advisor consult
# (scripts/compound-v-advisor-consult.sh), with NO real backend ever invoked.
#
# A live nested bypass agent DELETED this repo on 2026-07-13. The advisor is therefore READ-ONLY,
# and this test proves that safety property structurally: it installs a FAKE backend via
# $COMPOUND_V_ADVISOR_STUB (a canned-advice echoer) and asserts that:
#
#   (a) the cross-brand selector picks the RIGHT advisor — codex when codex is available,
#       opus fallback (claude) when only claude is available;
#   (b) the argv the consult passes to the backend carries the READ-ONLY / PLAN safety flags and
#       NEVER contains --dangerously-skip-permissions (nor --yolo / a bypass permission-mode);
#   (c) the parsed advice + advisor_calls:1 come back in the consult's JSON.
#
# Exit 0 on pass; non-zero + diagnostics on fail. No codex / claude binary is ever run.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONSULT="$SCRIPT_DIR/compound-v-advisor-consult.sh"

command -v jq      >/dev/null 2>&1 || { echo "FAIL: jq not found on PATH"; exit 2; }
command -v python3 >/dev/null 2>&1 || { echo "FAIL: python3 not found on PATH"; exit 2; }
[ -f "$CONSULT" ] || { echo "FAIL: consult script not found: $CONSULT"; exit 2; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

CANNED="STUB_ADVICE: prefer approach B (canned from the fake backend)"

# --- the FAKE backend --------------------------------------------------------
# Impersonates whichever real binary the consult would have launched, using the IDENTICAL argv.
# It (1) dumps its argv, one element per line, to $COMPOUND_V_ADVISOR_STUB_ARGV_OUT so the test
# can assert the safety flags, and (2) emits canned advice in the SHAPE the consult parses:
#   codex  -> writes CANNED to the --output-last-message file; a thread.started JSONL to stdout
#   claude -> a stream-json `result` event carrying CANNED on stdout
# It NEVER writes any repo file and takes no action — it is a pure echoer.
STUB="$TMP/fake-backend.sh"
cat > "$STUB" <<STUB_EOF
#!/usr/bin/env bash
set -eu
CANNED="$CANNED"
# Dump argv one-per-line for the test's flag assertions.
if [ -n "\${COMPOUND_V_ADVISOR_STUB_ARGV_OUT:-}" ]; then
  : > "\$COMPOUND_V_ADVISOR_STUB_ARGV_OUT"
  for _a in "\$@"; do printf '%s\n' "\$_a" >> "\$COMPOUND_V_ADVISOR_STUB_ARGV_OUT"; done
fi
# Detect which backend we are impersonating from our own argv.
_is_codex=0; _is_claude=0
for _a in "\$@"; do
  [ "\$_a" = "exec" ] && _is_codex=1
  [ "\$_a" = "-p" ] && _is_claude=1
done
if [ "\$_is_codex" = "1" ]; then
  # Find the --output-last-message file and write the canned advice there.
  _prev=""; _out=""
  for _a in "\$@"; do
    [ "\$_prev" = "--output-last-message" ] && _out="\$_a"
    _prev="\$_a"
  done
  [ -n "\$_out" ] && printf '%s' "\$CANNED" > "\$_out"
  printf '%s\n' '{"type":"thread.started","thread_id":"00000000-0000-0000-0000-000000000000"}'
  exit 0
fi
if [ "\$_is_claude" = "1" ]; then
  # Emit a stream-json result event; the consult parses .result from it.
  jq -cn --arg r "\$CANNED" '{type:"result", subtype:"success", result:\$r}'
  exit 0
fi
echo "fake-backend: could not tell which backend to impersonate" >&2
exit 3
STUB_EOF
chmod +x "$STUB"

fail=0

# assert_line <file> <exact-line>  — the exact line is present
assert_line() {
  if grep -Fxq -- "$2" "$1"; then return 0; fi
  echo "  FAIL: expected argv element '$2' not found in $1"; fail=1
}
# assert_no_line <file> <exact-line> — the exact line is ABSENT
assert_no_line() {
  if grep -Fxq -- "$2" "$1"; then
    echo "  FAIL: forbidden argv element '$2' WAS present in $1"; fail=1
  fi
}
# assert_adjacent <file> <a> <b> — line <a> is immediately followed by line <b>
assert_adjacent() {
  if awk -v a="$2" -v b="$3" 'prev==a && $0==b{found=1} {prev=$0} END{exit found?0:1}' "$1"; then
    return 0
  fi
  echo "  FAIL: expected argv '$2' immediately followed by '$3' in $1"; fail=1
}

# --- case 1: codex available -> cross-brand codex advisor, read-only sandbox ----
ARGV1="$TMP/argv.codex"
OUT1="$(COMPOUND_V_ADVISOR_STUB="$STUB" COMPOUND_V_ADVISOR_STUB_ARGV_OUT="$ARGV1" \
  bash "$CONSULT" \
    --question "Should I use a queue or a mutex here?" \
    --executor claude --available "codex,claude")"

b1="$(printf '%s' "$OUT1" | jq -r '.advisor_backend')"
m1="$(printf '%s' "$OUT1" | jq -r '.advisor_model')"
a1="$(printf '%s' "$OUT1" | jq -r '.advice')"
c1="$(printf '%s' "$OUT1" | jq -r '.advisor_calls')"

[ "$b1" = "codex" ] || { echo "  FAIL: expected advisor_backend=codex, got '$b1'"; fail=1; }
[ -n "$m1" ] && [ "$m1" != "null" ] || { echo "  FAIL: expected a concrete advisor_model, got '$m1'"; fail=1; }
[ "$a1" = "$CANNED" ] || { echo "  FAIL: advice mismatch (codex): got '$a1'"; fail=1; }
[ "$c1" = "1" ] || { echo "  FAIL: expected advisor_calls=1 (codex), got '$c1'"; fail=1; }
# Safety flags on the codex argv.
assert_line "$ARGV1" "--sandbox"
assert_adjacent "$ARGV1" "--sandbox" "read-only"
assert_line "$ARGV1" "--json"
assert_no_line "$ARGV1" "--dangerously-skip-permissions"
assert_no_line "$ARGV1" "--allow-dangerously-skip-permissions"
assert_no_line "$ARGV1" "--yolo"
[ "$fail" = "0" ] && echo "  case1 (codex cross-brand, read-only): PASS"

# --- case 2: only claude available -> opus fallback, plan mode -----------------
ARGV2="$TMP/argv.claude"
OUT2="$(COMPOUND_V_ADVISOR_STUB="$STUB" COMPOUND_V_ADVISOR_STUB_ARGV_OUT="$ARGV2" \
  bash "$CONSULT" \
    --question "Should I use a queue or a mutex here?" \
    --executor codex --available "claude")"

b2="$(printf '%s' "$OUT2" | jq -r '.advisor_backend')"
m2="$(printf '%s' "$OUT2" | jq -r '.advisor_model')"
a2="$(printf '%s' "$OUT2" | jq -r '.advice')"
c2="$(printf '%s' "$OUT2" | jq -r '.advisor_calls')"

[ "$b2" = "claude" ] || { echo "  FAIL: expected advisor_backend=claude, got '$b2'"; fail=1; }
[ "$m2" = "opus" ]   || { echo "  FAIL: expected advisor_model=opus (never haiku), got '$m2'"; fail=1; }
[ "$a2" = "$CANNED" ] || { echo "  FAIL: advice mismatch (claude): got '$a2'"; fail=1; }
[ "$c2" = "1" ] || { echo "  FAIL: expected advisor_calls=1 (claude), got '$c2'"; fail=1; }
# Safety flags on the claude argv.
assert_line "$ARGV2" "--permission-mode"
assert_adjacent "$ARGV2" "--permission-mode" "plan"
assert_line "$ARGV2" "--model"
assert_no_line "$ARGV2" "--dangerously-skip-permissions"
assert_no_line "$ARGV2" "--allow-dangerously-skip-permissions"
assert_no_line "$ARGV2" "--yolo"
# The opus fallback must never be run in a bypass permission-mode.
assert_no_line "$ARGV2" "bypassPermissions"
[ "$fail" = "0" ] && echo "  case2 (opus fallback, plan mode): PASS"

# --- case 3: context path is embedded read-only (no write anywhere) -----------
CTX="$TMP/ctx.md"
printf 'CONTEXT-MARKER-42\n' > "$CTX"
ARGV3="$TMP/argv.ctx"
OUT3="$(COMPOUND_V_ADVISOR_STUB="$STUB" COMPOUND_V_ADVISOR_STUB_ARGV_OUT="$ARGV3" \
  bash "$CONSULT" \
    --question "Given the context, queue or mutex?" \
    --context-path "$CTX" \
    --executor claude --available "codex,claude")"
c3adv="$(printf '%s' "$OUT3" | jq -r '.advisor_calls')"
[ "$c3adv" = "1" ] || { echo "  FAIL: expected advisor_calls=1 (ctx), got '$c3adv'"; fail=1; }
# The prompt (last argv element) must carry the read-only context marker.
if grep -Fq 'CONTEXT-MARKER-42' "$ARGV3"; then :; else
  echo "  FAIL: context file contents were not embedded in the advisor prompt"; fail=1
fi
[ "$fail" = "0" ] && echo "  case3 (read-only context embedded): PASS"

echo "---"
if [ "$fail" = "0" ]; then
  echo "SELFTEST PASSED (no real backend was invoked)"
  exit 0
fi
echo "SELFTEST FAILED"
exit 1
