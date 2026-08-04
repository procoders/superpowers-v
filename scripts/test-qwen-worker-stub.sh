#!/usr/bin/env bash
#
# test-qwen-worker-stub.sh — stub-first proof for scripts/compound-v-run-qwen-worker.sh.
# A FAKE `qwen` is placed first on PATH; the real binary is NEVER run, no network, no key.
#
# THIS TEST ALWAYS RUNS. It deliberately carries NO `command -v qwen` skip guard — the whole
# point of a stub test is that it proves the WORKER using a fake binary, so it must be live
# exactly where the real CLI is absent (CI). A skip guard here would silently disable the
# coverage of credential scrubbing, argv, the timeout path, the scope gate, the model-identity
# assertion and the sandbox refusals while still reporting green.
# Only scripts/test-qwen-wire-smoke.sh skips, because only IT needs the real binary.
#
# What this test CAN prove: the pinned argv, the credential scrub, the sandbox refusals, and
# the result paths (success, blocked, timeout, crash, wrong model, unproven containment).
# What it CANNOT prove: how the real binary INTERPRETS that argv — the defect class that made
# a docs-only reading of `--sandbox` wrong in this design's first draft. That belongs to
# test-qwen-wire-smoke.sh.
#
# Exit 0 on pass; non-zero with diagnostics on fail.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKER="$SCRIPT_DIR/compound-v-run-qwen-worker.sh"

command -v jq      >/dev/null 2>&1 || { echo "FAIL: jq not found on PATH"; exit 2; }
command -v python3 >/dev/null 2>&1 || { echo "FAIL: python3 not found on PATH"; exit 2; }
command -v git     >/dev/null 2>&1 || { echo "FAIL: git not found on PATH"; exit 2; }
[ -f "$WORKER" ] || { echo "FAIL: worker not found: $WORKER"; exit 2; }

# Hermetic launcher environment. Every one of these is read by the worker, and an ambient
# value would change the verdict of a test that is supposed to be about the worker.
unset SANDBOX QWEN_SANDBOX SEATBELT_PROFILE SANDBOX_FLAGS QWEN_SANDBOX_IMAGE QWEN_HOME || true
unset OPENAI_BASE_URL OPENAI_API_KEY || true

TMP="$(mktemp -d)"
WT_ROOT="${TMPDIR:-/tmp}/compound-v/qwen-stub-run"
cleanup() {
  rm -rf "$TMP"
  # The worktrees this run created, and the .env the ancestor case planted above them. The
  # run-id is qwen-specific so this never touches another worker's scratch — and leaving the
  # planted .env behind would make the NEXT run refuse every case.
  rm -rf "$WT_ROOT"
}
trap cleanup EXIT

# A stale plant from an interrupted previous run would refuse every case below.
rm -f "$WT_ROOT/.env"

PASS=0
FAILED=0
ok()   { PASS=$((PASS + 1)); echo "  ok   - $1"; }
bad()  { FAILED=$((FAILED + 1)); echo "  FAIL - $1"; }
check() { if [ "$2" = "yes" ]; then ok "$1"; else bad "$1"; fi; }

# --- the fake qwen -----------------------------------------------------------
# The stub's output paths and behaviour are BAKED IN at generation time, not passed through
# the environment: the worker launches it under `env -i`, so a control variable set by this
# test would be scrubbed before the stub ever saw it. (That the scrub does this is itself one
# of the properties under test.)
STUBDIR="$TMP/bin"
SANDBOXDIR="$TMP/sandboxbin"
MINBIN="$TMP/minbin"
mkdir -p "$STUBDIR" "$SANDBOXDIR" "$MINBIN"
ARGV_OUT="$TMP/argv.txt"
ENV_OUT="$TMP/env.txt"
CWD_OUT="$TMP/cwd.txt"

# Fake sandbox providers, so the test is hermetic on a host that has none. The worker only
# ever does `command -v` on these — it never executes them (engaging the sandbox is qwen's
# own job) — so a non-functional stub is exactly the right fidelity here.
for _p in sandbox-exec docker podman; do
  printf '#!/bin/sh\nexit 0\n' > "$SANDBOXDIR/$_p"
  chmod +x "$SANDBOXDIR/$_p"
done

# A minimal bin dir for the "no sandbox provider" case: real tools, but NOT sandbox-exec,
# docker or podman. Replacing PATH wholesale is the only way to hide a provider from
# `command -v`, which searches all of PATH.
for _b in bash sh env python3 git jq uname dirname mkdir rm cat head tr sed grep sleep chmod cut uuidgen; do
  _bp="$(command -v "$_b" 2>/dev/null || true)"
  if [ -n "$_bp" ]; then ln -sf "$_bp" "$MINBIN/$_b"; fi
done

make_stub() {
  # $1 = mode (success|blocked|hang|wrongmodel|crash|nosandbox), $2 = served model name
  cat > "$STUBDIR/qwen" <<STUB
#!/usr/bin/env bash
set -eu
: > "$ARGV_OUT"
for a in "\$@"; do printf '%s\n' "\$a" >> "$ARGV_OUT"; done
env > "$ENV_OUT"
printf '%s\n' "\$PWD" > "$CWD_OUT"
# The sandbox transport sets SANDBOX on itself once it has engaged; the stub reports the
# provider it was handed, which is what the worker's containment proof reads back.
_sandbox="\${QWEN_SANDBOX:-}"
case "$1" in
  hang)       sleep 30 ;;
  blocked)    printf 'stray\n' > ./NOT_ALLOWED.txt ;;
  success)    printf 'ok\n' > ./allowed.txt ;;
  wrongmodel) : ;;
  nosandbox)  _sandbox="" ;;
  crash)      echo 'boom' >&2; exit 3 ;;
esac
printf '[{"type":"system","subtype":"session_start","session_id":"11111111-2222-3333-4444-555555555555","model":"$2","sandbox":"%s"},{"type":"result","subtype":"success","is_error":false,"result":"done","usage":{"input_tokens":11,"output_tokens":7}}]\n' "\$_sandbox"
STUB
  chmod +x "$STUBDIR/qwen"
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
  # $1 = mode, $2 = write-allowed globs, $3 = timeout, $4 = served model,
  # rest = extra env assignments for the CALLER (which the scrub must drop)
  _mode="$1"; _allow="$2"; _timeout="$3"; _served="$4"; shift 4
  make_stub "$_mode" "$_served"
  env PATH="$STUBDIR:$SANDBOXDIR:$PATH" \
      BAILIAN_CODING_PLAN_API_KEY="stub-key-not-a-secret" "$@" \
    "$WORKER" \
      --run-id qwen-stub-run --job-id "job-$_mode" \
      --repo "$REPO" --prompt-file "$PROMPT" --model qwen3-coder-plus \
      --write-allowed "$_allow" --timeout-sec "$_timeout" 2>"$TMP/worker.err"
}

RC=0
OUT=""
run_worker_rc() {
  # Same as run_worker, but tolerates a non-zero exit: refusal paths are under test.
  set +e
  OUT="$(run_worker "$@")"
  RC=$?
  set -e
}

echo "== argv =="
run_worker success "allowed.txt" 60 qwen3-coder-plus >/dev/null

argv_has() { grep -qxF -- "$1" "$ARGV_OUT" && echo yes || echo no; }

check "argv carries --model"                    "$(argv_has '--model')"
check "argv carries the resolved model name"    "$(argv_has 'qwen3-coder-plus')"
check "argv carries --approval-mode=yolo as ONE token" "$(argv_has '--approval-mode=yolo')"
check "argv carries --auth-type"                "$(argv_has '--auth-type')"
check "argv carries openai as the auth type"    "$(argv_has 'openai')"
check "argv carries --output-format"            "$(argv_has '--output-format')"
check "argv carries json"                       "$(argv_has 'json')"
check "argv carries --session-id"               "$(argv_has '--session-id')"
check "argv carries --safe-mode"                "$(argv_has '--safe-mode')"
check "argv carries --max-subagent-depth"       "$(argv_has '--max-subagent-depth')"
check "argv carries --max-session-turns"        "$(argv_has '--max-session-turns')"

# The caller ASSIGNS the session id rather than scraping it back out of the response. Each run
# mints a fresh one, so it is always read from the argv of the run under assertion.
argv_session_id() { grep -A1 -xF -- '--session-id' "$ARGV_OUT" | tail -1; }
SID="$(argv_session_id)"
case "$SID" in
  [0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]-[0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]-[0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]-[0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]-[0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]) SID_OK=yes ;;
  *) SID_OK=no ;;
esac
check "the session id the caller assigned is a UUID (got: $SID)" "$SID_OK"

# The prompt is POSITIONAL. `-p`/`--prompt` is deprecated and combining the two is a parse error.
check "the prompt reaches the binary positionally" \
      "$(grep -q 'implementation worker' "$ARGV_OUT" && echo yes || echo no)"

# Every one of these means something other than what its name suggests, or hangs headless,
# or leaks the key into a world-readable argv. See adapter-qwen.md's "never emit" table.
for flag in -p --prompt --yolo --allowed-tools --worktree --sandbox -s \
            --openai-api-key --insecure --resume --dangerously-skip-permissions \
            --max-wall-time --cd; do
  check "argv NEVER carries $flag" "$([ "$(argv_has "$flag")" = no ] && echo yes || echo no)"
done

echo "== cwd =="
# Qwen Code has NO --cd/--dir flag, so the worktree is entered with a subshell cd. Without it
# the worker edits the LAUNCHER's cwd and the gate diffs an untouched worktree — an empty diff
# waving through a job that changed everything.
check "qwen ran inside the worktree" \
      "$(grep -q 'compound-v/qwen-stub-run/job-success' "$CWD_OUT" && echo yes || echo no)"

echo "== the credential scrub =="
env_names() { cut -d= -f1 "$ENV_OUT" | sort -u; }
EXPECTED_ENV="$(printf '%s\n' PATH TMPDIR LANG HOME QWEN_HOME \
  BAILIAN_CODING_PLAN_API_KEY OPENAI_BASE_URL \
  QWEN_SANDBOX SEATBELT_PROFILE SANDBOX_FLAGS QWEN_SANDBOX_IMAGE \
  PWD SHLVL _ | sort -u)"
UNEXPECTED="$(comm -23 <(env_names) <(printf '%s\n' "$EXPECTED_ENV") | tr '\n' ' ')"
check "no variable beyond the allow-list reached the child (got: ${UNEXPECTED:-none})" \
      "$([ -z "$UNEXPECTED" ] && echo yes || echo no)"
check "HOME is NOT the operator's" \
      "$(grep -q "^HOME=$HOME$" "$ENV_OUT" && echo no || echo yes)"
check "HOME points inside the scratch dir, not the repo or the worktree" \
      "$(grep -q "^HOME=.*job-success\.art/home$" "$ENV_OUT" && echo yes || echo no)"
check "QWEN_HOME points at the same scratch dir (it also drops ~/.env from discovery)" \
      "$(grep -q "^QWEN_HOME=.*job-success\.art/home$" "$ENV_OUT" && echo yes || echo no)"
check "the key is forwarded as BAILIAN_CODING_PLAN_API_KEY" \
      "$(grep -q '^BAILIAN_CODING_PLAN_API_KEY=stub-key-not-a-secret$' "$ENV_OUT" && echo yes || echo no)"
check "the pinned default endpoint reaches the child" \
      "$(grep -q '^OPENAI_BASE_URL=https://coding-intl.dashscope.aliyuncs.com/v1$' "$ENV_OUT" && echo yes || echo no)"
check "QWEN_SANDBOX reaches the child with a real provider" \
      "$(grep -qE '^QWEN_SANDBOX=(sandbox-exec|docker|podman)$' "$ENV_OUT" && echo yes || echo no)"
# Setting SANDBOX is what DISABLES sandboxing, so the worker must never hand one down either.
check "SANDBOX is never handed to the child" \
      "$(grep -q '^SANDBOX=' "$ENV_OUT" && echo no || echo yes)"
check "no alternate auth path: OPENAI_API_KEY is absent from the child" \
      "$(grep -q '^OPENAI_API_KEY=' "$ENV_OUT" && echo no || echo yes)"

# Ambient provider variables set by the CALLER must not survive `env -i`.
run_worker success "allowed.txt" 60 qwen3-coder-plus \
  OPENAI_API_KEY="leak-me-please" QWEN_SANDBOX="ambient-not-a-provider" >/dev/null
check "an ambient OPENAI_API_KEY does not reach the child" \
      "$(grep -q 'leak-me-please' "$ENV_OUT" && echo no || echo yes)"
check "an ambient QWEN_SANDBOX cannot choose the provider" \
      "$(grep -q '^QWEN_SANDBOX=ambient-not-a-provider$' "$ENV_OUT" && echo no || echo yes)"

echo "== the pinned settings file =="
SCRATCH_SETTINGS="$WT_ROOT/job-success.art/home/.qwen/settings.json"
check "the settings file exists in the redirected QWEN_HOME" \
      "$([ -f "$SCRATCH_SETTINGS" ] && echo yes || echo no)"
check "it sets folderTrust.enabled explicitly" \
      "$(jq -e '.security.folderTrust.enabled == true' "$SCRATCH_SETTINGS" >/dev/null 2>&1 && echo yes || echo no)"
# A project-scoped .qwen/settings.json sits INSIDE the worktree and would dirty the worker's
# own diff, blocking a job that changed nothing on purpose.
check "no .qwen was created inside the worktree" \
      "$([ -e "$WT_ROOT/job-success/.qwen" ] && echo no || echo yes)"

echo "== result paths =="
R="$(run_worker success "allowed.txt" 60 qwen3-coder-plus)"
check "success status"         "$([ "$(printf '%s' "$R" | jq -r .status)" = success ] && echo yes || echo no)"
check "success is not blocked" "$([ "$(printf '%s' "$R" | jq -r .blocked)" = false ] && echo yes || echo no)"
check "files_changed is exactly the allowed file" \
      "$([ "$(printf '%s' "$R" | jq -c '.files_changed')" = '["allowed.txt"]' ] && echo yes || echo no)"
check "the session_id in the result is the one the caller assigned on the wire" \
      "$([ "$(printf '%s' "$R" | jq -r .session_id)" = "$(argv_session_id)" ] && echo yes || echo no)"
check "no cost value anywhere in the result" \
      "$(printf '%s' "$R" | tr '[:upper:]' '[:lower:]' | grep -q cost && echo no || echo yes)"

R="$(run_worker blocked "allowed.txt" 60 qwen3-coder-plus)"
check "an out-of-scope write is BLOCKED" \
      "$([ "$(printf '%s' "$R" | jq -r .status)" = blocked ] && echo yes || echo no)"
check "blocked sets blocked: true" \
      "$([ "$(printf '%s' "$R" | jq -r .blocked)" = true ] && echo yes || echo no)"
check "the offending path is listed in violations" \
      "$(printf '%s' "$R" | jq -e '.violations | index("NOT_ALLOWED.txt")' >/dev/null && echo yes || echo no)"
check "a blocked job is NOT merged back into the repo" \
      "$([ -e "$REPO/NOT_ALLOWED.txt" ] && echo no || echo yes)"
check "blocked clears failure_class" \
      "$(printf '%s' "$R" | jq -e '.failure_class == null' >/dev/null && echo yes || echo no)"

R="$(run_worker hang "allowed.txt" 2 qwen3-coder-plus)"
check "a hung worker yields status timeout" \
      "$([ "$(printf '%s' "$R" | jq -r .status)" = timeout ] && echo yes || echo no)"
check "the supervisor's 124 is carried through as the exit code" \
      "$([ "$(printf '%s' "$R" | jq -r .exit_code)" = 124 ] && echo yes || echo no)"

R="$(run_worker crash "allowed.txt" 60 qwen3-coder-plus)"
check "a crashing worker yields status error" \
      "$([ "$(printf '%s' "$R" | jq -r .status)" = error ] && echo yes || echo no)"
check "a crashing worker carries the real exit code" \
      "$([ "$(printf '%s' "$R" | jq -r .exit_code)" = 3 ] && echo yes || echo no)"
check "a crashing worker gets a non-null failure_class" \
      "$(printf '%s' "$R" | jq -e '.failure_class != null' >/dev/null && echo yes || echo no)"

echo "== fail-closed assertions =="
# The served model comes from the transport's own envelope, never from model-authored output:
# a model cannot authenticate its own identity. A mismatch must fail, never pass silently.
run_worker_rc wrongmodel "allowed.txt" 60 some-other-model
check "a served model that is not the requested one FAILS the job" \
      "$([ "$RC" -ne 0 ] && echo yes || echo no)"
check "the mismatch is reported, not swallowed" \
      "$(grep -q 'served model' "$TMP/worker.err" && echo yes || echo no)"
check "a mismatched run emits no success result" \
      "$(printf '%s' "$OUT" | grep -q '"status": *"success"' && echo no || echo yes)"

# A mandatory sandbox that silently no-ops is worse than an honest optional one, because the
# trust tier is claimed on it.
run_worker_rc nosandbox "allowed.txt" 60 qwen3-coder-plus
check "a run that cannot prove containment FAILS the job" \
      "$([ "$RC" -ne 0 ] && echo yes || echo no)"
check "the containment failure says the sandbox could not be proven" \
      "$(grep -qi 'sandbox' "$TMP/worker.err" && echo yes || echo no)"

# `.env` discovery walks UPWARD from cwd, so a file one directory above the worktree is loaded
# too — and because QWEN_SANDBOX outranks the CLI flag, a planted ancestor .env could disable
# the sandbox this backend's trust tier is claimed on.
mkdir -p "$WT_ROOT"
printf 'QWEN_SANDBOX=\n' > "$WT_ROOT/.env"
run_worker_rc success "allowed.txt" 60 qwen3-coder-plus
check "a .env ONE DIRECTORY ABOVE the worktree makes the worker refuse to start" \
      "$([ "$RC" -ne 0 ] && echo yes || echo no)"
check "the refusal names the offending file" \
      "$(grep -q "$WT_ROOT/.env" "$TMP/worker.err" && echo yes || echo no)"
rm -f "$WT_ROOT/.env"

echo "== sandbox refusals =="
# Sandboxing is MANDATORY: with no provider the worker must refuse rather than run unconfined.
set +e
NOSANDBOX_OUT="$(make_stub success qwen3-coder-plus; \
  env -i PATH="$STUBDIR:$MINBIN" HOME="$HOME" TMPDIR="${TMPDIR:-/tmp}" \
      BAILIAN_CODING_PLAN_API_KEY="stub-key-not-a-secret" \
    "$WORKER" --run-id qwen-stub-run --job-id job-noprovider \
      --repo "$REPO" --prompt-file "$PROMPT" --model qwen3-coder-plus \
      --write-allowed "allowed.txt" --timeout-sec 60 2>&1)"
NOSANDBOX_RC=$?
set -e
check "with no sandbox provider on PATH the worker refuses" \
      "$([ "$NOSANDBOX_RC" -ne 0 ] && echo yes || echo no)"
check "the refusal names the missing provider requirement" \
      "$(printf '%s' "$NOSANDBOX_OUT" | grep -qi 'sandbox' && echo yes || echo no)"

# An ambient SANDBOX makes Qwen Code believe it is already contained and skip sandboxing
# silently. It cannot be defended by pre-setting it — setting it IS the disable.
run_worker_rc success "allowed.txt" 60 qwen3-coder-plus SANDBOX=1
check "an ambient SANDBOX makes the worker refuse" \
      "$([ "$RC" -ne 0 ] && echo yes || echo no)"
check "the refusal explains that qwen would skip sandboxing" \
      "$(grep -q 'SANDBOX is set' "$TMP/worker.err" && echo yes || echo no)"

echo "== effort policy =="
set +e
EFFORT_OUT="$(run_worker success "allowed.txt" 60 qwen3-coder-plus 2>&1 >/dev/null)"
set -e
: "$EFFORT_OUT"
set +e
XHIGH_OUT="$(env PATH="$STUBDIR:$SANDBOXDIR:$PATH" \
    BAILIAN_CODING_PLAN_API_KEY="stub-key-not-a-secret" \
  "$WORKER" --run-id qwen-stub-run --job-id job-xhigh \
    --repo "$REPO" --prompt-file "$PROMPT" --model qwen3-coder-plus \
    --write-allowed "allowed.txt" --timeout-sec 60 --effort xhigh 2>&1)"
XHIGH_RC=$?
set -e
check "effort xhigh is rejected (codex-only project policy, not a Qwen limitation)" \
      "$([ "$XHIGH_RC" -ne 0 ] && printf '%s' "$XHIGH_OUT" | grep -q 'codex-only' && echo yes || echo no)"

echo
echo "SELFTEST: $PASS ok, $FAILED fail"
[ "$FAILED" -eq 0 ] || exit 1
