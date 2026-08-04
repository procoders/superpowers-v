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
# What this test CAN prove: the pinned argv, the credential scrub, the pinned settings file
# (which is the AUTH PATH, not just a hardening knob), the sandbox refusals, and the result
# paths (success, blocked, timeout, crash, wrong model, missing init envelope, a sandbox that
# never engaged).
# What it CANNOT prove: how the real binary INTERPRETS that argv — the defect class that made
# a docs-only reading of `--sandbox` wrong in this design's first draft. That belongs to
# test-qwen-wire-smoke.sh.
#
# The stub's output shape is the one MEASURED against qwen 0.21.5 on 2026-08-04, not an
# invented one. A stub that emits a fabricated envelope makes this whole file a test of the
# fabrication — which is exactly what happened with `session_start` and the `sandbox` field.
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
  # $1 = mode (success|blocked|hang|wrongmodel|crash|noinit|fatalsandbox|invalidsandbox)
  # $2 = served model
  cat > "$STUBDIR/qwen" <<STUB
#!/usr/bin/env bash
set -eu
: > "$ARGV_OUT"
for a in "\$@"; do printf '%s\n' "\$a" >> "$ARGV_OUT"; done
env > "$ENV_OUT"
printf '%s\n' "\$PWD" > "$CWD_OUT"
case "$1" in
  hang)       sleep 30 ;;
  blocked)    printf 'stray\n' > ./NOT_ALLOWED.txt ;;
  success)    printf 'ok\n' > ./allowed.txt ;;
  wrongmodel) : ;;
  noinit)     : ;;
  crash)      printf 'boom\n' >&2; exit 3 ;;
  # There is no sandbox field to blank out. What a sandbox that cannot engage really looks
  # like is qwen's own getSandboxCommand() throwing, verbatim from the shipped source.
  fatalsandbox)
    printf 'FatalSandboxError: Missing sandbox command %sdocker%s (from QWEN_SANDBOX)\n' "'" "'" >&2
    exit 1 ;;
  # The OTHER text, MEASURED live: an unknown provider name is rejected with this instead — and
  # the real binary prints it in an unbounded loop and never exits, so the supervisor's timeout
  # is what ends that job. The stub exits so the assertion stays fast; what is under test here
  # is that the worker recognises the text, not how long the real one spins.
  invalidsandbox)
    printf 'Invalid sandbox command %sno-such%s. Must be one of docker, podman, sandbox-exec\n' "'" "'" >&2
    exit 1 ;;
esac
# The MEASURED --output-format json shape (qwen 0.21.5, live probe 2026-08-04): a top-level
# JSON ARRAY whose FIRST element is system/init — NOT session_start, which belongs to a
# different protocol this flag does not emit — with exactly these keys, and whose terminal
# result element carries usage{input_tokens,output_tokens,cache_read_input_tokens,total_tokens}
# and a stats.models map keyed BY MODEL NAME. There is no \`sandbox\` key anywhere in the
# output. The input_tokens value is deliberately five figures: a ONE-WORD prompt measured
# 17,277 input tokens, because the system preamble plus 64 tool definitions dominate it.
_INIT_FMT='{"type":"system","subtype":"init","session_id":"11111111-2222-3333-4444-555555555555","uuid":"aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee","model":"%s","cwd":"%s","permission_mode":"yolo","qwen_code_version":"0.21.5","agents":[],"mcp_servers":[],"slash_commands":[],"tools":["read_file","write_file"]}'
_RESULT_FMT='{"type":"result","subtype":"success","uuid":"ffffffff-0000-1111-2222-333333333333","session_id":"11111111-2222-3333-4444-555555555555","is_error":false,"num_turns":1,"duration_ms":1234,"duration_api_ms":1000,"permission_denials":[],"result":"done","usage":{"input_tokens":17277,"output_tokens":43,"cache_read_input_tokens":0,"total_tokens":17320},"stats":{"models":{"%s":{"api":{"totalRequests":1}}}}}'
_INIT="\$(printf "\$_INIT_FMT" "$2" "\$PWD")"
_RESULT="\$(printf "\$_RESULT_FMT" "$2")"
case "$1" in
  noinit) printf '[%s]\n' "\$_RESULT" ;;
  *)      printf '[%s,%s]\n' "\$_INIT" "\$_RESULT" ;;
esac
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
      BAILIAN_TOKEN_PLAN_API_KEY="stub-key-not-a-secret" "$@" \
    "$WORKER" \
      --run-id qwen-stub-run --job-id "job-$_mode" \
      --repo "$REPO" --prompt-file "$PROMPT" --model qwen3.8-max \
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
run_worker success "allowed.txt" 60 qwen3.8-max >/dev/null

argv_has() { grep -qxF -- "$1" "$ARGV_OUT" && echo yes || echo no; }

check "argv carries --model"                    "$(argv_has '--model')"
check "argv carries the resolved model name"    "$(argv_has 'qwen3.8-max')"
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
  BAILIAN_TOKEN_PLAN_API_KEY OPENAI_BASE_URL \
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
check "the key is forwarded as BAILIAN_TOKEN_PLAN_API_KEY" \
      "$(grep -q '^BAILIAN_TOKEN_PLAN_API_KEY=stub-key-not-a-secret$' "$ENV_OUT" && echo yes || echo no)"
TOKEN_PLAN_URL="https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"
check "the pinned default Token Plan endpoint reaches the child" \
      "$(grep -qxF "OPENAI_BASE_URL=$TOKEN_PLAN_URL" "$ENV_OUT" && echo yes || echo no)"
check "QWEN_SANDBOX reaches the child with a real provider" \
      "$(grep -qE '^QWEN_SANDBOX=(sandbox-exec|docker|podman)$' "$ENV_OUT" && echo yes || echo no)"
# CONTAINMENT, part 2 of 3. The bare boolean is the dangerous form: `QWEN_SANDBOX=true` makes
# qwen guess a provider, and when it cannot guess one it throws instead of running — but only a
# CONCRETE name makes the failure deterministic on every host. Never emit true/1/yes.
check "QWEN_SANDBOX is never the bare boolean" \
      "$(grep -qiE '^QWEN_SANDBOX=(true|1|yes|on)$' "$ENV_OUT" && echo no || echo yes)"
# CONTAINMENT, part 1 of 3. Setting SANDBOX is what DISABLES sandboxing, so the worker must
# never hand one down either.
check "SANDBOX is never handed to the child" \
      "$(grep -q '^SANDBOX=' "$ENV_OUT" && echo no || echo yes)"
# The key travels ONLY under its operator-facing name; the settings file's `envKey` is what
# tells the CLI to read that name. OPENAI_API_KEY stays unset on purpose — Qwen Code loads a
# .env variable only when it is NOT already in the environment, and the ancestor scan is what
# guards the unset name.
check "no alternate auth path: OPENAI_API_KEY is absent from the child" \
      "$(grep -q '^OPENAI_API_KEY=' "$ENV_OUT" && echo no || echo yes)"

# Ambient provider variables set by the CALLER must not survive `env -i`.
run_worker success "allowed.txt" 60 qwen3.8-max \
  OPENAI_API_KEY="leak-me-please" QWEN_SANDBOX="ambient-not-a-provider" >/dev/null
check "an ambient OPENAI_API_KEY does not reach the child" \
      "$(grep -q 'leak-me-please' "$ENV_OUT" && echo no || echo yes)"
check "an ambient QWEN_SANDBOX cannot choose the provider" \
      "$(grep -q '^QWEN_SANDBOX=ambient-not-a-provider$' "$ENV_OUT" && echo no || echo yes)"

echo "== the pinned settings file (this file IS the auth path) =="
SCRATCH_SETTINGS="$WT_ROOT/job-success.art/home/settings.json"
check "the settings file exists AT the redirected QWEN_HOME, not under a .qwen inside it" \
      "$([ -f "$SCRATCH_SETTINGS" ] && echo yes || echo no)"
# MEASURED: with QWEN_HOME set, the config dir IS QWEN_HOME. A settings.json under a `.qwen`
# subdirectory there is ignored and the CLI dies on the missing key one step later.
check "no settings.json is left at the ignored \$QWEN_HOME/.qwen path" \
      "$([ -e "$WT_ROOT/job-success.art/home/.qwen/settings.json" ] && echo no || echo yes)"
check "it sets folderTrust.enabled explicitly" \
      "$(jq -e '.security.folderTrust.enabled == true' "$SCRATCH_SETTINGS" >/dev/null 2>&1 && echo yes || echo no)"
# MEASURED: the `openai` auth path does NOT read BAILIAN_TOKEN_PLAN_API_KEY by itself — it
# dies with "Missing API key for OpenAI-compatible auth". `envKey` is the documented lever that
# points it at the operator-facing name, which is why this worker never sets OPENAI_API_KEY.
check "the provider declares envKey = BAILIAN_TOKEN_PLAN_API_KEY" \
      "$(jq -e '.modelProviders.openai.models[0].envKey == "BAILIAN_TOKEN_PLAN_API_KEY"' \
           "$SCRATCH_SETTINGS" >/dev/null 2>&1 && echo yes || echo no)"
check "the provider speaks the openai protocol and is the selected auth type" \
      "$(jq -e '.modelProviders.openai.protocol == "openai"
                and .security.auth.selectedType == "openai"' \
           "$SCRATCH_SETTINGS" >/dev/null 2>&1 && echo yes || echo no)"
check "baseUrl is the endpoint the worker resolved, not a hardcoded string in the settings" \
      "$(jq -e --arg u "$TOKEN_PLAN_URL" \
           '.modelProviders.openai.models[0].baseUrl == $u' \
           "$SCRATCH_SETTINGS" >/dev/null 2>&1 && echo yes || echo no)"
# The credential reaches the child under ONE name, and the settings file must point at that
# same name. A mismatch is the "Missing API key for OpenAI-compatible auth" failure, so pin the
# two together rather than asserting each in isolation.
check "the envKey names exactly the variable the child actually receives" \
      "$(grep -qxF "$(jq -r '.modelProviders.openai.models[0].envKey' "$SCRATCH_SETTINGS")=stub-key-not-a-secret" \
           "$ENV_OUT" && echo yes || echo no)"
check "the model id and model.name both come from --model" \
      "$(jq -e '.modelProviders.openai.models[0].id == "qwen3.8-max"
                and .model.name == "qwen3.8-max"' \
           "$SCRATCH_SETTINGS" >/dev/null 2>&1 && echo yes || echo no)"
# The settings file lands on disk in scratch. A key VALUE written there would outlive the run.
check "the key VALUE is never written into the settings file (only its variable NAME)" \
      "$(grep -q 'stub-key-not-a-secret' "$SCRATCH_SETTINGS" && echo no || echo yes)"
# A project-scoped .qwen/settings.json sits INSIDE the worktree and would dirty the worker's
# own diff, blocking a job that changed nothing on purpose.
check "no .qwen was created inside the worktree" \
      "$([ -e "$WT_ROOT/job-success/.qwen" ] && echo no || echo yes)"

echo "== result paths =="
R="$(run_worker success "allowed.txt" 60 qwen3.8-max)"
check "success status"         "$([ "$(printf '%s' "$R" | jq -r .status)" = success ] && echo yes || echo no)"
check "success is not blocked" "$([ "$(printf '%s' "$R" | jq -r .blocked)" = false ] && echo yes || echo no)"
check "files_changed is exactly the allowed file" \
      "$([ "$(printf '%s' "$R" | jq -c '.files_changed')" = '["allowed.txt"]' ] && echo yes || echo no)"
check "the session_id in the result is the one the caller assigned on the wire" \
      "$([ "$(printf '%s' "$R" | jq -r .session_id)" = "$(argv_session_id)" ] && echo yes || echo no)"
check "no cost value anywhere in the result" \
      "$(printf '%s' "$R" | tr '[:upper:]' '[:lower:]' | grep -q cost && echo no || echo yes)"

R="$(run_worker blocked "allowed.txt" 60 qwen3.8-max)"
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

R="$(run_worker hang "allowed.txt" 2 qwen3.8-max)"
check "a hung worker yields status timeout" \
      "$([ "$(printf '%s' "$R" | jq -r .status)" = timeout ] && echo yes || echo no)"
check "the supervisor's 124 is carried through as the exit code" \
      "$([ "$(printf '%s' "$R" | jq -r .exit_code)" = 124 ] && echo yes || echo no)"

R="$(run_worker crash "allowed.txt" 60 qwen3.8-max)"
check "a crashing worker yields status error" \
      "$([ "$(printf '%s' "$R" | jq -r .status)" = error ] && echo yes || echo no)"
check "a crashing worker carries the real exit code" \
      "$([ "$(printf '%s' "$R" | jq -r .exit_code)" = 3 ] && echo yes || echo no)"
check "a crashing worker gets a non-null failure_class" \
      "$(printf '%s' "$R" | jq -e '.failure_class != null' >/dev/null && echo yes || echo no)"

echo "== fail-closed assertions =="
# The served model is read from the MEASURED system/init element — never from model-authored
# output, because a model cannot authenticate its own identity. A mismatch must fail, never
# pass silently. (The `success` path above already proves the happy case: every result assertion
# in this file only runs because the init envelope matched.)
run_worker_rc wrongmodel "allowed.txt" 60 some-other-model
check "a served model that is not the requested one FAILS the job" \
      "$([ "$RC" -ne 0 ] && echo yes || echo no)"
check "the mismatch is reported, not swallowed" \
      "$(grep -q 'served model' "$TMP/worker.err" && echo yes || echo no)"
check "a mismatched run emits no success result" \
      "$(printf '%s' "$OUT" | grep -q '"status": *"success"' && echo no || echo yes)"

# Missing init element ⇒ nothing to compare against ⇒ fail closed, never "assume it matched".
run_worker_rc noinit "allowed.txt" 60 qwen3.8-max
check "a response with NO system/init element FAILS the job" \
      "$([ "$RC" -ne 0 ] && echo yes || echo no)"
check "the refusal names the missing init envelope" \
      "$(grep -q 'system/init' "$TMP/worker.err" && echo yes || echo no)"

# CONTAINMENT, part 3 of 3. There is no sandbox field in the output to read back, so engagement
# cannot be proven from the payload. What CAN be detected is qwen refusing to run without one:
# FatalSandboxError. That is a WORKER fault (the operator's machine needs fixing), not a model
# failure the dispatcher should retry or reroute.
run_worker_rc fatalsandbox "allowed.txt" 60 qwen3.8-max
check "a FatalSandboxError FAILS the job" \
      "$([ "$RC" -ne 0 ] && echo yes || echo no)"
check "the failure is reported as a sandbox problem naming QWEN_SANDBOX" \
      "$(grep -q 'QWEN_SANDBOX' "$TMP/worker.err" && echo yes || echo no)"
check "a FatalSandboxError is a worker fault, NOT a classified model failure result" \
      "$(printf '%s' "$OUT" | grep -q '"status"' && echo no || echo yes)"

# The OTHER measured text. An unknown provider name never reaches FatalSandboxError — it is
# rejected as "Invalid sandbox command … Must be one of docker, podman, sandbox-exec", which
# the real binary then repeats without ever exiting. Both texts must land in the same branch.
run_worker_rc invalidsandbox "allowed.txt" 60 qwen3.8-max
check "an 'Invalid sandbox command' rejection is ALSO a worker fault" \
      "$([ "$RC" -ne 0 ] && echo yes || echo no)"
check "it does not fall through to the failure classifier as a model error" \
      "$(printf '%s' "$OUT" | grep -q '"failure_class"' && echo no || echo yes)"

# The successful path must NOT trip that grep: a healthy sandboxed run says only
# "using macos seatbelt (profile: …)" / "hopping into sandbox (command: …)".
R="$(run_worker success "allowed.txt" 60 qwen3.8-max)"
check "a healthy run is not mistaken for a sandbox fault" \
      "$([ "$(printf '%s' "$R" | jq -r .status)" = success ] && echo yes || echo no)"

# `.env` discovery walks UPWARD from cwd, so a file one directory above the worktree is loaded
# too — and because QWEN_SANDBOX outranks the CLI flag, a planted ancestor .env could disable
# the sandbox this backend's trust tier is claimed on.
mkdir -p "$WT_ROOT"
printf 'QWEN_SANDBOX=\n' > "$WT_ROOT/.env"
run_worker_rc success "allowed.txt" 60 qwen3.8-max
check "a .env ONE DIRECTORY ABOVE the worktree makes the worker refuse to start" \
      "$([ "$RC" -ne 0 ] && echo yes || echo no)"
check "the refusal names the offending file" \
      "$(grep -q "$WT_ROOT/.env" "$TMP/worker.err" && echo yes || echo no)"
rm -f "$WT_ROOT/.env"

echo "== sandbox refusals =="
# Sandboxing is MANDATORY: with no provider the worker must refuse rather than run unconfined.
set +e
NOSANDBOX_OUT="$(make_stub success qwen3.8-max; \
  env -i PATH="$STUBDIR:$MINBIN" HOME="$HOME" TMPDIR="${TMPDIR:-/tmp}" \
      BAILIAN_TOKEN_PLAN_API_KEY="stub-key-not-a-secret" \
    "$WORKER" --run-id qwen-stub-run --job-id job-noprovider \
      --repo "$REPO" --prompt-file "$PROMPT" --model qwen3.8-max \
      --write-allowed "allowed.txt" --timeout-sec 60 2>&1)"
NOSANDBOX_RC=$?
set -e
check "with no sandbox provider on PATH the worker refuses" \
      "$([ "$NOSANDBOX_RC" -ne 0 ] && echo yes || echo no)"
check "the refusal names the missing provider requirement" \
      "$(printf '%s' "$NOSANDBOX_OUT" | grep -qi 'sandbox' && echo yes || echo no)"

# An ambient SANDBOX makes Qwen Code believe it is already contained and skip sandboxing
# silently. It cannot be defended by pre-setting it — setting it IS the disable.
run_worker_rc success "allowed.txt" 60 qwen3.8-max SANDBOX=1
check "an ambient SANDBOX makes the worker refuse" \
      "$([ "$RC" -ne 0 ] && echo yes || echo no)"
check "the refusal explains that qwen would skip sandboxing" \
      "$(grep -q 'SANDBOX is set' "$TMP/worker.err" && echo yes || echo no)"

echo "== effort policy =="
set +e
EFFORT_OUT="$(run_worker success "allowed.txt" 60 qwen3.8-max 2>&1 >/dev/null)"
set -e
: "$EFFORT_OUT"
set +e
XHIGH_OUT="$(env PATH="$STUBDIR:$SANDBOXDIR:$PATH" \
    BAILIAN_TOKEN_PLAN_API_KEY="stub-key-not-a-secret" \
  "$WORKER" --run-id qwen-stub-run --job-id job-xhigh \
    --repo "$REPO" --prompt-file "$PROMPT" --model qwen3.8-max \
    --write-allowed "allowed.txt" --timeout-sec 60 --effort xhigh 2>&1)"
XHIGH_RC=$?
set -e
check "effort xhigh is rejected (codex-only project policy, not a Qwen limitation)" \
      "$([ "$XHIGH_RC" -ne 0 ] && printf '%s' "$XHIGH_OUT" | grep -q 'codex-only' && echo yes || echo no)"

echo
echo "SELFTEST: $PASS ok, $FAILED fail"
[ "$FAILED" -eq 0 ] || exit 1
