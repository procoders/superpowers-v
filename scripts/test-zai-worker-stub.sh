#!/usr/bin/env bash
#
# test-zai-worker-stub.sh — stub-first proof for scripts/compound-v-run-zai-worker.sh.
# A FAKE `claude` is placed first on PATH; the real binary is NEVER run, no network, no key.
#
# What this test CAN prove: the pinned argv, the credential scrub, and the five result paths
# (success, blocked, timeout, non-GLM, crash).
# What it CANNOT prove: how the real binary INTERPRETS that argv. The defect that broke the
# first draft of this backend — `--allowedTools` not defining the tool set — passed every
# conceivable argv assertion. That class is covered by test-zai-wire-smoke.sh instead.
#
# Exit 0 on pass; non-zero with diagnostics on fail.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKER="$SCRIPT_DIR/compound-v-run-zai-worker.sh"

command -v jq      >/dev/null 2>&1 || { echo "FAIL: jq not found on PATH"; exit 2; }
command -v python3 >/dev/null 2>&1 || { echo "FAIL: python3 not found on PATH"; exit 2; }
command -v git     >/dev/null 2>&1 || { echo "FAIL: git not found on PATH"; exit 2; }
[ -f "$WORKER" ] || { echo "FAIL: worker not found: $WORKER"; exit 2; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PASS=0
FAILED=0
ok()   { PASS=$((PASS + 1)); echo "  ok   - $1"; }
bad()  { FAILED=$((FAILED + 1)); echo "  FAIL - $1"; }
check() { if [ "$2" = "yes" ]; then ok "$1"; else bad "$1"; fi; }

# --- the fake claude ---------------------------------------------------------
# The stub's output paths and behaviour are BAKED IN at generation time, not passed through
# the environment: the worker launches it under `env -i`, so a control variable set by this
# test would be scrubbed before the stub ever saw it. (That the scrub does this is itself one
# of the properties under test.)
STUBDIR="$TMP/bin"
mkdir -p "$STUBDIR"
ARGV_OUT="$TMP/argv.txt"
ENV_OUT="$TMP/env.txt"
CWD_OUT="$TMP/cwd.txt"

make_stub() {
  # $1 = mode (success|blocked|hang|nonglm|crash), $2 = modelUsage key
  cat > "$STUBDIR/claude" <<STUB
#!/usr/bin/env bash
set -eu
: > "$ARGV_OUT"
for a in "\$@"; do printf '%s\n' "\$a" >> "$ARGV_OUT"; done
env > "$ENV_OUT"
printf '%s\n' "\$PWD" > "$CWD_OUT"
case "$1" in
  hang)     sleep 30 ;;
  blocked)  printf 'stray\n' > ./NOT_ALLOWED.txt ;;
  success)  printf 'ok\n' > ./allowed.txt ;;
  nonglm)   : ;;
  crash)    echo "boom" >&2; exit 1 ;;
esac
cat <<'JSON'
{"type":"result","subtype":"success","is_error":false,"result":"stub did the thing",
 "session_id":"ce0ba7c7-bb9a-421f-b926-9973806d506f",
 "total_cost_usd":0.42,
 "usage":{"input_tokens":123,"output_tokens":45},
 "modelUsage":{"$2":{"inputTokens":123,"outputTokens":45,"costUSD":0.42}}}
JSON
STUB
  chmod +x "$STUBDIR/claude"
}

# --- a throwaway git repo ----------------------------------------------------
REPO="$TMP/repo"
mkdir -p "$REPO"
git -C "$REPO" init -q .
git -C "$REPO" config user.email t@t
git -C "$REPO" config user.name t
printf 'x\n' > "$REPO/seed.txt"
git -C "$REPO" add -A
git -C "$REPO" commit -qm base

PROMPT="$TMP/prompt.md"
printf 'You are an implementation worker, NOT the planner.\n' > "$PROMPT"

run_worker() {
  # $1 = mode, $2 = write-allowed globs, $3 = timeout, $4 = modelUsage key,
  # rest = extra env assignments for the CALLER (which the scrub must drop)
  _mode="$1"; _allow="$2"; _timeout="$3"; _mkey="$4"; shift 4
  make_stub "$_mode" "$_mkey"
  env PATH="$STUBDIR:$PATH" ZAI_API_KEY="stub-key-not-a-secret" "$@" \
    "$WORKER" \
      --run-id stub-run --job-id "job-$_mode" \
      --repo "$REPO" --prompt-file "$PROMPT" --model glm-5.2 \
      --write-allowed "$_allow" --timeout-sec "$_timeout" 2>"$TMP/worker.err"
}

echo "== argv, environment and cwd =="
run_worker success "allowed.txt" 60 glm-5.2 >/dev/null

argv_has() { grep -qxF -- "$1" "$ARGV_OUT" && echo yes || echo no; }

check "argv carries --permission-mode"                 "$(argv_has '--permission-mode')"
check "argv carries dontAsk"                           "$(argv_has 'dontAsk')"
check "argv carries --tools"                           "$(argv_has '--tools')"
check "argv carries --allowedTools"                    "$(argv_has '--allowedTools')"
check "argv carries the exact tool list"               "$(argv_has 'Read,Edit,Write,Bash')"
check "argv carries --exclude-dynamic-system-prompt-sections" \
      "$(argv_has '--exclude-dynamic-system-prompt-sections')"
check "argv carries --output-format json"              "$(argv_has 'json')"

# The prompt MUST be preceded by `--`: --tools/--allowedTools are variadic and would
# otherwise swallow it.
TERM_LINE="$(grep -nxF -- '--' "$ARGV_OUT" | head -1 | cut -d: -f1 || echo 0)"
PROMPT_LINE="$(grep -n 'implementation worker' "$ARGV_OUT" | head -1 | cut -d: -f1 || echo 0)"
check "the prompt is guarded by a -- terminator" \
      "$([ "$TERM_LINE" -gt 0 ] && [ "$PROMPT_LINE" -gt "$TERM_LINE" ] && echo yes || echo no)"

for flag in --dangerously-skip-permissions --yolo --bare; do
  check "argv NEVER carries $flag" "$([ "$(argv_has "$flag")" = no ] && echo yes || echo no)"
done

# The worker must run INSIDE the worktree, not the launcher's cwd.
check "claude ran inside the worktree" \
      "$(grep -q 'compound-v/stub-run/job-success' "$CWD_OUT" && echo yes || echo no)"

echo "== the credential scrub =="
env_names() { cut -d= -f1 "$ENV_OUT" | sort -u; }
EXPECTED_ENV="$(printf '%s\n' PATH TMPDIR LANG LC_ALL TERM HOME CLAUDE_CONFIG_DIR \
  ANTHROPIC_BASE_URL ANTHROPIC_AUTH_TOKEN ANTHROPIC_MODEL \
  ANTHROPIC_DEFAULT_OPUS_MODEL ANTHROPIC_DEFAULT_SONNET_MODEL ANTHROPIC_DEFAULT_HAIKU_MODEL \
  API_TIMEOUT_MS CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC PWD SHLVL _ | sort -u)"
UNEXPECTED="$(comm -23 <(env_names) <(printf '%s\n' "$EXPECTED_ENV") | tr '\n' ' ')"
check "no variable beyond the allow-list reached the child (got: ${UNEXPECTED:-none})" \
      "$([ -z "$UNEXPECTED" ] && echo yes || echo no)"
check "HOME is NOT the operator's" \
      "$(grep -q "^HOME=$HOME$" "$ENV_OUT" && echo no || echo yes)"
check "ZAI_API_KEY itself is not forwarded" \
      "$(grep -q '^ZAI_API_KEY=' "$ENV_OUT" && echo no || echo yes)"
check "the key is forwarded as ANTHROPIC_AUTH_TOKEN" \
      "$(grep -q '^ANTHROPIC_AUTH_TOKEN=stub-key-not-a-secret$' "$ENV_OUT" && echo yes || echo no)"
check "no x-api-key path: ANTHROPIC_API_KEY is absent" \
      "$(grep -q '^ANTHROPIC_API_KEY=' "$ENV_OUT" && echo no || echo yes)"
check "the haiku SLOT is filled with a GLM model, not a Haiku" \
      "$(grep -q '^ANTHROPIC_DEFAULT_HAIKU_MODEL=glm-5.2$' "$ENV_OUT" && echo yes || echo no)"

# An ambient provider variable set by the CALLER must not survive `env -i`.
run_worker success "allowed.txt" 60 glm-5.2 \
  ANTHROPIC_API_KEY="leak-me-please" ANTHROPIC_BASE_URL="https://evil.example" >/dev/null
check "an ambient ANTHROPIC_API_KEY does not reach the child" \
      "$(grep -q 'leak-me-please' "$ENV_OUT" && echo no || echo yes)"
check "an ambient ANTHROPIC_BASE_URL does not override the z.ai endpoint" \
      "$(grep -q '^ANTHROPIC_BASE_URL=https://api.z.ai/api/anthropic$' "$ENV_OUT" && echo yes || echo no)"

echo "== result paths =="
R="$(run_worker success "allowed.txt" 60 glm-5.2)"
check "success status"        "$([ "$(printf '%s' "$R" | jq -r .status)" = success ] && echo yes || echo no)"
check "success is not blocked" "$([ "$(printf '%s' "$R" | jq -r .blocked)" = false ] && echo yes || echo no)"
check "session_id is the UUID" \
      "$([ "$(printf '%s' "$R" | jq -r .session_id)" = ce0ba7c7-bb9a-421f-b926-9973806d506f ] && echo yes || echo no)"
check "usage is measured with real counts" \
      "$([ "$(printf '%s' "$R" | jq -r '.usage.input_tokens')" = 123 ] && \
         [ "$(printf '%s' "$R" | jq -r '.usage.measured')" = true ] && echo yes || echo no)"
check "no cost value anywhere in the result" \
      "$(printf '%s' "$R" | tr '[:upper:]' '[:lower:]' | grep -q cost && echo no || echo yes)"

R="$(run_worker blocked "allowed.txt" 60 glm-5.2)"
check "out-of-scope write is BLOCKED" \
      "$([ "$(printf '%s' "$R" | jq -r .status)" = blocked ] && echo yes || echo no)"
check "the offending path is listed in violations" \
      "$(printf '%s' "$R" | jq -e '.violations | index("NOT_ALLOWED.txt")' >/dev/null && echo yes || echo no)"

R="$(run_worker hang "allowed.txt" 2 glm-5.2)"
check "a hung worker yields status timeout" \
      "$([ "$(printf '%s' "$R" | jq -r .status)" = timeout ] && echo yes || echo no)"
check "timeout carries failure_class timeout" \
      "$([ "$(printf '%s' "$R" | jq -r .failure_class)" = timeout ] && echo yes || echo no)"

R="$(run_worker nonglm "allowed.txt" 60 claude-opus-4-8)"
check "a non-GLM response fails the job" \
      "$([ "$(printf '%s' "$R" | jq -r .status)" = error ] && echo yes || echo no)"
check "the non-GLM failure says why" \
      "$(printf '%s' "$R" | jq -r .summary | grep -q 'did not reach z.ai' && echo yes || echo no)"

# The `crash` mode was declared in make_stub() but never invoked by any run_worker call, so
# the worker's entire exit_code != 0 branch (the classifier call, failure_class,
# retry_after_seconds, ERR_TEXT) had ZERO test coverage. Wire it up.
R="$(run_worker crash "allowed.txt" 60 glm-5.2)"
check "a crashing worker yields status error" \
      "$([ "$(printf '%s' "$R" | jq -r .status)" = error ] && echo yes || echo no)"
check "a crashing worker is not blocked" \
      "$([ "$(printf '%s' "$R" | jq -r .blocked)" = false ] && echo yes || echo no)"
check "a crashing worker carries the real exit code" \
      "$([ "$(printf '%s' "$R" | jq -r .exit_code)" = 1 ] && echo yes || echo no)"
check "a crashing worker gets a classified failure_class (not null)" \
      "$([ "$(printf '%s' "$R" | jq -r .failure_class)" = other ] && echo yes || echo no)"

echo
echo "SELFTEST: $PASS ok, $FAILED fail"
[ "$FAILED" -eq 0 ] || exit 1
