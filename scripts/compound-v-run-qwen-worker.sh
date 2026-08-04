#!/usr/bin/env bash
#
# compound-v-run-qwen-worker.sh — headless Qwen Code worker for Compound V.
#
# Runs ONE file-scoped job as a Bash-spawned `qwen` process against Alibaba's Bailian
# **Token Plan** endpoint, inside its own git worktree, and emits the canonical job_result on
# stdout. Implements skills/backend-launcher/adapter-qwen.md.
#
# NOT the Coding Plan. Measured 2026-08-04 on the operator's key: every Coding Plan combination
# (both regions x three models x Bearer/x-api-key) returned 401, and the one 200 seen there —
# GET /models — is UNAUTHENTICATED, so it proves nothing (a bogus key gets the same catalog).
# The same key authenticates and generates on the Token Plan, where a bogus key does get a 401.
#
# !!! SAFETY — lower-trust in ROLE, sandbox-mandatory in MECHANISM, WORKER-ONLY !!!
# Unlike zai/cursor/antigravity/opencode, this backend DOES get kernel confinement — and it is
# REQUIRED, not optional. A machine with no sandbox provider (sandbox-exec on macOS, docker or
# podman on Linux) makes this worker REFUSE to start rather than run unconfined.
#
# Engagement is NOT observable in the result payload. The 2026-08-04 live probe against
# qwen 0.21.5 found NO `sandbox` key anywhere in `--output-format json`, so the earlier
# "read it back out of the envelope" proof could never have passed. What IS enforceable, and
# what this worker now relies on, is three things:
#   1. refuse when an ambient SANDBOX is set (setting it IS the disable, see below);
#   2. always hand qwen a CONCRETE provider name in QWEN_SANDBOX (sandbox-exec|docker|podman),
#      never the bare boolean — an unresolvable provider then makes qwen itself raise
#      FatalSandboxError instead of silently running unconfined;
#   3. treat that FatalSandboxError as a WORKER fault, not a model failure.
# The guarantee is qwen's own fatal error, not an observed field. Do not upgrade that claim.
#
# The backend is still never a reviewer: the manifest validator rejects it by name.
#
# Status. The INVOCATION SHAPE is verified live 2026-08-04 against qwen 0.21.5 on Token Plan
# Pro: exit 0, a real generation, an init envelope reporting the requested model. What is still
# stub-only, and must not be described as verified: the scope gate, the merge-back, and the
# blocked path have never run against a real model's edits.
#
# Enforcement (blocked/files_changed/violations) is git-derived by
# scripts/compound-v-scope-check.py — never self-reported by the model.
#
# bash 3.2 safe: no arrays, no ${var,,}, no process substitution, no readarray.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SUPERVISOR="$SCRIPT_DIR/compound-v-run-with-timeout.py"
SCOPE_CHECK="$SCRIPT_DIR/compound-v-scope-check.py"
USAGE_EXTRACT="$SCRIPT_DIR/compound-v-usage-extract.py"

# The Token Plan endpoint, MEASURED working end-to-end on 2026-08-04. Note the shape: a
# regional host and a `/compatible-mode/v1` path, NOT the Coding Plan's coding-intl.dashscope
# host. Unlike zai's hard-pinned base URL this one stays caller-selectable — other regions are
# a legitimate operator choice and a region mismatch returns a 401 that never says "wrong
# region". The scheme is still pinned: an ambient value cannot downgrade it to plaintext.
QWEN_DEFAULT_BASE_URL="https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"

# Token Plan quota is counted in CREDITS off token usage, not in requests, so the turn count is
# no longer the only thing that costs — but it is still the runaway guard. 15 is the same
# ceiling adapter-claude.md pins for a scoped implementation slice — enough turns to write and
# self-check a partitioned file set, small enough that a runaway job ends rather than churns.
#
# MEASURED and load-bearing on a per-token plan: a ONE-WORD prompt consumed 17,277 INPUT
# tokens. That is the system preamble plus 64 tool definitions, not the user's prompt, and
# --safe-mode was already on. `--core-tools` is the lever that could cut it. NOT applied yet:
# trimming the tool set must be measured before it is claimed, not guessed at.
MAX_TURNS=15

# The MANDATORY provider-credential scrub, as an ALLOWLIST rather than a denylist. `env -i`
# clears EVERY inherited variable and only these names are injected back with their parent
# values; a credential can reach the child ONLY if it is named here, never by omission from a
# denylist. HOME is absent on purpose — it is replaced with a scratch dir below.
_SAFE_ENV_VARS="PATH TMPDIR LANG"

# --- helpers -----------------------------------------------------------------

die() {
  # Environment/usage fault: no job_result could be produced.
  echo "compound-v-run-qwen-worker: $1" >&2
  exit 2
}

# Allow only [A-Za-z0-9._-]; reject `.`, `..`, empty, and any separator. A `../x` id is a
# path-traversal vector into the worktree parent. bash 3.2-safe: case glob, no regex.
id_is_safe() {
  _id="${1:-}"
  [ -n "$_id" ] || return 1
  [ "$_id" = "." ] && return 1
  [ "$_id" = ".." ] && return 1
  case "$_id" in
    *[!A-Za-z0-9._-]*) return 1 ;;
  esac
  return 0
}

emit_job_result() {
  # $1 status  $2 blocked(true|false)  $3 files_json (JSON array)  $4 violations_json (JSON array)
  # $5 summary  $6 session_id  $7 worktree  $8 exit_code(int)  $9 failure_class ("" => null)
  # ${10} retry_after_seconds  ${11} usage_json  ${12} retry_at  ${13} network_scope
  jq -n \
    --arg status "$1" \
    --argjson blocked "$2" \
    --argjson files "$3" \
    --argjson violations "$4" \
    --arg summary "$5" \
    --arg session_id "$6" \
    --arg worktree "$7" \
    --argjson exit_code "$8" \
    --arg failure_class "$9" \
    --argjson retry_after_seconds "${10}" \
    --argjson usage "${11}" \
    --arg retry_at "${12:-}" \
    --arg network_scope "${13:-}" \
    '({
       status: $status,
       blocked: $blocked,
       files_changed: $files,
       violations: $violations,
       summary: $summary,
       failure_class: (if ($status == "success" or $status == "blocked" or $failure_class == "")
                       then null else $failure_class end),
       session_id: $session_id,
       worktree: $worktree,
       exit_code: $exit_code,
       retry_after_seconds: (if ($status == "success" or $status == "blocked")
                             then 0 else $retry_after_seconds end),
       usage: $usage
     } + (if ($status != "success" and $status != "blocked" and $retry_at != "")
          then {retry_at: $retry_at} else {} end)
       + (if ($status != "success" and $status != "blocked" and $network_scope != "")
          then {network_scope: $network_scope} else {} end))'
}

unmeasured_usage() {
  jq -n --arg b qwen \
    '{input_tokens: null, output_tokens: null, advisor_calls: null, backend: $b, measured: false}'
}

# --- arguments ---------------------------------------------------------------

RUN_ID=""; JOB_ID=""; REPO=""; PROMPT_FILE=""; MODEL=""
WRITE_ALLOWED=""; TIMEOUT_SEC=""; EFFORT=""; READ_ONLY="false"; NETWORK="false"
EVENTS_LOG_OVERRIDE=""

while [ $# -gt 0 ]; do
  case "$1" in
    --run-id)        RUN_ID="$2"; shift 2 ;;
    --job-id)        JOB_ID="$2"; shift 2 ;;
    --repo)          REPO="$2"; shift 2 ;;
    --prompt-file)   PROMPT_FILE="$2"; shift 2 ;;
    --model)         MODEL="$2"; shift 2 ;;
    --write-allowed) WRITE_ALLOWED="$2"; shift 2 ;;
    --timeout-sec)   TIMEOUT_SEC="$2"; shift 2 ;;
    --effort)        EFFORT="$2"; shift 2 ;;
    --read-only)     READ_ONLY="$2"; shift 2 ;;
    --network)       NETWORK="$2"; shift 2 ;;
    --events-log)    EVENTS_LOG_OVERRIDE="$2"; shift 2 ;;
    --output-schema) shift 2 ;;   # accepted and ignored, for CLI parity
    *) die "unknown argument: $1" ;;
  esac
done

[ -n "$RUN_ID" ]      || die "--run-id is required"
[ -n "$JOB_ID" ]      || die "--job-id is required"
[ -n "$REPO" ]        || die "--repo is required"
[ -n "$PROMPT_FILE" ] || die "--prompt-file is required"
[ -n "$MODEL" ]       || die "--model is required"
[ -n "$TIMEOUT_SEC" ] || die "--timeout-sec is required"

id_is_safe "$RUN_ID" || die "unsafe --run-id '$RUN_ID' (allowed: A-Za-z0-9._-, not . or ..)"
id_is_safe "$JOB_ID" || die "unsafe --job-id '$JOB_ID' (allowed: A-Za-z0-9._-, not . or ..)"

case "$REPO" in        /*) : ;; *) die "--repo must be absolute: $REPO" ;; esac
case "$PROMPT_FILE" in /*) : ;; *) die "--prompt-file must be absolute: $PROMPT_FILE" ;; esac
[ -d "$REPO/.git" ] || [ -f "$REPO/.git" ] || die "--repo is not a git repository: $REPO"
[ -f "$PROMPT_FILE" ] || die "--prompt-file not found: $PROMPT_FILE"
case "$TIMEOUT_SEC" in ''|*[!0-9]*) die "--timeout-sec must be a positive integer" ;; esac
[ "$TIMEOUT_SEC" -gt 0 ] || die "--timeout-sec must be a positive integer"

# NETWORK is NOT decorative here — it selects the Seatbelt profile on macOS and the container
# network flag on Linux — so a typo must be a refusal, not a silently different sandbox.
case "$NETWORK" in
  true|false) : ;;
  *) die "--network must be true or false (got '$NETWORK')" ;;
esac
case "$READ_ONLY" in
  true|false) : ;;
  *) die "--read-only must be true or false (got '$READ_ONLY')" ;;
esac

# `xhigh` is codex-only. Every other backend rejects it with a message naming the rule.
case "$EFFORT" in
  ""|low|medium|high) : ;;
  xhigh) die "effort 'xhigh' is codex-only; use 'high' for backend qwen" ;;
  *) die "unknown --effort '$EFFORT' (expected low|medium|high)" ;;
esac
# DELIBERATE DISCARD, not an oversight. Qwen Code has NO headless effort flag at all: the only
# surface is `model.reasoningEffort` in settings.json, and Qwen applies its own per-provider
# clamp on top, so a requested value is advisory twice over. The `xhigh` rejection above is
# COMPOUND V POLICY (xhigh is reserved for codex's kernel model_reasoning_effort), NOT a Qwen
# limitation — Qwen's own ladder runs low|medium|high|xhigh|max and supports both of the top
# two natively. Documented so a future reader does not "fix" a non-bug.
: "$EFFORT"

# --- preflight ---------------------------------------------------------------

command -v jq      >/dev/null 2>&1 || die "jq not found on PATH"
command -v git     >/dev/null 2>&1 || die "git not found on PATH"
command -v python3 >/dev/null 2>&1 || die "python3 not found on PATH"
command -v qwen    >/dev/null 2>&1 || die "qwen not found on PATH (npm @qwen-code/qwen-code, Node >= 22)"
# `env` is the vehicle for the MANDATORY credential scrub — without it we must NOT silently
# fall through to an unscrubbed invocation.
command -v env     >/dev/null 2>&1 || die "env not found on PATH (required for the credential scrub)"
[ -f "$SUPERVISOR" ]    || die "supervisor not found: $SUPERVISOR"
[ -f "$SCOPE_CHECK" ]   || die "scope gate not found: $SCOPE_CHECK"
[ -f "$USAGE_EXTRACT" ] || die "usage extractor not found: $USAGE_EXTRACT"

QWEN_KEY="${BAILIAN_TOKEN_PLAN_API_KEY:-}"
[ -n "$QWEN_KEY" ] || \
  die "BAILIAN_TOKEN_PLAN_API_KEY is not set — the qwen worker never reads a key from a file inside the repo"

OPENAI_BASE_URL="${OPENAI_BASE_URL:-$QWEN_DEFAULT_BASE_URL}"
case "$OPENAI_BASE_URL" in
  https://*) : ;;
  *) die "OPENAI_BASE_URL must be an https endpoint (got '$OPENAI_BASE_URL')" ;;
esac

# --- the mandatory kernel sandbox --------------------------------------------
# Qwen Code's own source says "environment variable takes precedence over argument" —
# QWEN_SANDBOX BEATS the -s flag, the OPPOSITE of what the published docs page claims. And
# `-s`/`--sandbox` is a BOOLEAN, not a profile selector. So sandboxing is configured entirely
# through the environment and this worker never passes a sandbox flag at all.
QWEN_SANDBOX=""
SEATBELT_PROFILE=""
SANDBOX_FLAGS=""
if [ "$(uname -s)" = "Darwin" ]; then
  command -v sandbox-exec >/dev/null 2>&1 || die "qwen requires a sandbox: sandbox-exec not found"
  QWEN_SANDBOX="sandbox-exec"
  # The DEFAULT profile is permissive-open (writes broad, network open). Never inherit it.
  if [ "$NETWORK" = "true" ]; then SEATBELT_PROFILE="restrictive-open"
  else SEATBELT_PROFILE="restrictive-closed"; fi
elif command -v docker >/dev/null 2>&1; then
  QWEN_SANDBOX="docker"
  # SEATBELT_PROFILE has NO effect on the container path. Network denial is a container flag.
  [ "$NETWORK" = "true" ] || SANDBOX_FLAGS="--network=none"
elif command -v podman >/dev/null 2>&1; then
  QWEN_SANDBOX="podman"
  [ "$NETWORK" = "true" ] || SANDBOX_FLAGS="--network=none"
else
  die "qwen requires a sandbox provider: none of sandbox-exec, docker, podman found"
fi

# THE WHITELIST GATE ON THE EXPORTED VALUE. Every branch above assigns a literal, so this
# cannot fire today — it exists because of what qwen does when the value is NOT one of these
# three, MEASURED 2026-08-04: it prints "Invalid sandbox command '…'. Must be one of docker,
# podman, sandbox-exec" IN AN UNBOUNDED LOOP and never exits. Only the supervisor's wall-clock
# timeout ends that job, so it burns the whole budget and reports `timeout` instead of a
# configuration fault. Refusing here makes that loop UNREACHABLE rather than merely survivable.
# Keep this immediately before the export path: any future edit that makes the provider
# caller-influenced (a flag, a config field, an env override) is exactly the change that would
# otherwise reopen the hang, and it will hit this line first.
case "$QWEN_SANDBOX" in
  sandbox-exec|docker|podman) : ;;
  *) die "refusing to export QWEN_SANDBOX='$QWEN_SANDBOX': must be one of sandbox-exec, docker, podman (an unrecognised value makes qwen loop forever instead of failing)" ;;
esac

# A pre-existing SANDBOX value makes Qwen Code believe it is ALREADY contained and skip
# sandboxing silently. It cannot be defended by pre-setting it — setting it IS the disable —
# so it is excluded from the allow-list above and asserted absent here.
[ -z "${SANDBOX:-}" ] || die "SANDBOX is set in the environment; qwen would skip sandboxing"

# --- worktree + scratch ------------------------------------------------------

WT_PARENT="${TMPDIR:-/tmp}/compound-v"
WT="$WT_PARENT/$RUN_ID/$JOB_ID"
ART="$WT.art"          # scratch OUTSIDE the worktree so the diff stays pristine
SCRATCH="$ART/home"    # the worker's HOME *and* QWEN_HOME — see the settings note below

# Baseline captured BEFORE `worktree add`, so the gate diffs against the commit the worktree
# was actually created from.
BASELINE_SHA="$(git -C "$REPO" rev-parse HEAD 2>/dev/null)" || die "cannot resolve HEAD in $REPO"

# $SCRATCH/.qwen is deliberately NOT created. With QWEN_HOME set, the config dir IS $QWEN_HOME
# itself — `.qwen` underneath it is the HOME-relative legacy path, which qwen only mentions to
# warn that it will not migrate it ("QWEN_HOME points to … but no settings.json was found
# there. Existing config remains at …/.qwen"). Measured 2026-08-04.
mkdir -p "$WT_PARENT/$RUN_ID" "$ART" "$SCRATCH"

# Idempotent on resume: drop any stale worktree at this path, then recreate at current HEAD.
if [ -e "$WT" ]; then
  git -C "$REPO" worktree remove -f "$WT" >/dev/null 2>&1 || rm -rf "$WT"
fi
git -C "$REPO" worktree add "$WT" HEAD >/dev/null 2>&1 || die "cannot create worktree at $WT"

# --- ancestor-config preflight -----------------------------------------------
# Qwen Code's `.env` discovery walks UPWARD from cwd (and `.qwen/.env` is exempt from every
# exclusion filter at every level), so checking only inside the worktree is insufficient: a
# file at $TMPDIR/compound-v/<run-id>/, at $TMPDIR/, or at any ancestor is loaded too. Because
# QWEN_SANDBOX outranks the CLI flag, a planted ancestor .env could silently disable the one
# control this backend's trust tier is claimed on.
#
# Cheap (a handful of `test -e`), and it never fires on a clean run: `git worktree add`
# materialises TRACKED files only. It exists for the tracked-secret case and for a resumed
# worktree a previous job wrote into. DO NOT "optimise" this away as dead code.
_scan="$WT"
while [ -n "$_scan" ] && [ "$_scan" != "/" ]; do
  for _f in "$_scan/.env" "$_scan/.qwen/.env" "$_scan/.qwen/settings.json" "$_scan/.qwen/QWEN.local.md"; do
    if [ -e "$_f" ]; then
      die "qwen config file present in the search path: $_f"
    fi
  done
  _scan="$(dirname "$_scan")"
done

# --- the pinned settings file, in scratch and NEVER in the worktree ----------
# THIS FILE IS THE AUTH PATH, not just a hardening knob. Measured 2026-08-04 against qwen
# 0.21.5: the `openai` auth path does NOT read a BAILIAN_*_API_KEY variable on its own — with
# only that variable set the CLI dies with "Missing API key for OpenAI-compatible auth. Set
# settings.security.auth.apiKey, or set the 'OPENAI_API_KEY' environment variable."
#
# `modelProviders[].envKey` is the vendor-documented lever that closes that gap (their own
# auth.md publishes this exact block): it names WHICH environment variable holds the key, so
# the operator-facing name — the one Alibaba documents and the one /v:init records — is also
# the name the CLI reads. Measured result of the run that added this block: exit 0, no "Missing
# API key", init envelope reporting the requested model, and a real generation.
#
# Deliberate consequence: OPENAI_API_KEY is NEVER set, never allow-listed, and never handed to
# the child. Qwen Code loads a `.env` variable only when it is NOT already in the environment,
# so leaving the name unset would let a planted .env supply it — hence the ancestor scan above.
#
# security.folderTrust.enabled is set EXPLICITLY rather than inheriting the documented-off
# default (Qwen Code forked Gemini CLI at v0.8.2, ~31 minors before GHSA-wpqr-6v78-jr5g's fix;
# whether the untrusted-folder behaviour was backported is UNVERIFIED).
#
# PATH, MEASURED, and it is NOT the obvious one: the file goes at "$SCRATCH/settings.json",
# i.e. directly at $QWEN_HOME — NOT at "$SCRATCH/.qwen/settings.json". With QWEN_HOME set, the
# config dir IS $QWEN_HOME; a file under `.qwen` there is ignored and the CLI prints "QWEN_HOME
# points to … but no settings.json was found there", then dies on the missing key. That exact
# mistake was live in this worker until the 2026-08-04 probe caught it.
#
# It MUST live under $SCRATCH and never inside $WT: a project-scoped .qwen/settings.json sits
# in the worktree and would dirty the worker's own diff, tripping the scope gate on a job that
# changed nothing on purpose. Redirecting QWEN_HOME removes that whole hazard class; do not
# replicate the opencode worker's in-worktree config pin and its symlink guards.
#
# Built with jq, not a heredoc: $MODEL and $OPENAI_BASE_URL are caller-supplied, and a
# hand-quoted JSON template would be one odd catalog name away from an unparseable settings
# file that fails as "no auth type is selected" three steps later.
jq -n --arg model "$MODEL" --arg base "$OPENAI_BASE_URL" \
  '{
     modelProviders: {
       openai: {
         protocol: "openai",
         models: [ { id: $model,
                     name: ($model + " (Token Plan)"),
                     baseUrl: $base,
                     envKey: "BAILIAN_TOKEN_PLAN_API_KEY" } ]
       }
     },
     security: { auth: { selectedType: "openai" }, folderTrust: { enabled: true } },
     model: { name: $model }
   }' > "$SCRATCH/settings.json" || die "cannot write the pinned settings file"

EVENTS_LOG="${EVENTS_LOG_OVERRIDE:-$ART/qwen_result.json}"
STDERR_LOG="$ART/qwen_stderr.log"
mkdir -p "$(dirname "$EVENTS_LOG")"

# --read-only is enforced POST-HOC, exactly as the contract says: an EMPTY allow-list makes the
# gate treat EVERY changed path as a violation, so a read-only job that writes anything is
# correctly BLOCKED. No kernel flag is involved and none is claimed.
if [ "$READ_ONLY" = "true" ]; then
  WRITE_ALLOWED=""
fi
# NOTE: unlike the other workers, the allow-list is NOT written to a file here. See the
# scope-gate invocation below for why — it is built as --allow arguments instead.

# The caller ASSIGNS the session id; Qwen Code accepts one, which is strictly better than
# scraping it back out of the response and regex-validating it.
if command -v uuidgen >/dev/null 2>&1; then
  SESSION_ID="$(uuidgen | tr '[:upper:]' '[:lower:]')"
else
  SESSION_ID="$(python3 -c 'import uuid; print(uuid.uuid4())')"
fi

# --- run ---------------------------------------------------------------------

# Build the `env -i` allow-list as POSITIONAL PARAMETERS, not a concatenated string: bash 3.2
# has no arrays, but `set --` keeps each entry as ONE argument even when a value contains
# spaces (a PATH segment like "/Applications/Some App.app/..." is a real-world case a naive
# string splice would corrupt). The two conditional sandbox variables go in the same way,
# which is the adapter's `${VAR:+VAR="$VAR"}` line without an unquoted expansion.
set --
for _v in $_SAFE_ENV_VARS; do
  eval "_safe_val=\"\${$_v-}\""
  if [ -n "$_safe_val" ]; then
    set -- "$@" "$_v=$_safe_val"
  fi
done
if [ -n "$SEATBELT_PROFILE" ]; then set -- "$@" "SEATBELT_PROFILE=$SEATBELT_PROFILE"; fi
if [ -n "$SANDBOX_FLAGS" ];    then set -- "$@" "SANDBOX_FLAGS=$SANDBOX_FLAGS"; fi

PROMPT_TEXT="$(cat "$PROMPT_FILE")"

# The names `qwen` is allowed to receive, comma-joined for --env-only below. Static list, not
# conditioned on which are actually set — an absent name is silently skipped downstream
# (compound-v-run-with-timeout.py's --env-only reads from ITS OWN environment, which `env -i`
# has already reduced to exactly this set).
#
# SANDBOX is deliberately NOT here: setting it is what turns sandboxing OFF.
# QWEN_SANDBOX_IMAGE is listed for the container path even though this worker does not set
# one — an unset name costs nothing and its absence from the list would be a silent trap.
ENV_ONLY_NAMES="$(printf '%s' "$_SAFE_ENV_VARS" | tr ' ' ',')"
ENV_ONLY_NAMES="$ENV_ONLY_NAMES,HOME,QWEN_HOME,BAILIAN_TOKEN_PLAN_API_KEY,OPENAI_BASE_URL"
ENV_ONLY_NAMES="$ENV_ONLY_NAMES,QWEN_SANDBOX,SEATBELT_PROFILE,QWEN_SANDBOX_IMAGE,SANDBOX_FLAGS"

exit_code=0
# `qwen` has NO --cd/--dir flag anywhere in its option table (--include-directories adds READ
# scope, it does not change cwd), so the worktree is entered with a SUBSHELL cd. Without it the
# worker would edit files in the LAUNCHER's cwd and the scope gate, which diffs the worktree,
# would see an empty diff and wave through a job that changed everything.
#
# `env -i` wraps the SUPERVISOR here, not `qwen` directly — load-bearing for the credential.
# `env` builds the child's environment from its operands and then EXECS into it, replacing its
# own process image; whatever briefly held the key in argv stops existing within a fork/exec
# instant. The python3 supervisor is the opposite: it stays running for the WHOLE job to
# enforce the wall-clock timeout, so a value passed as one of ITS OWN arguments sits in that
# long-lived process's argv — world-readable via `ps`/`/proc/<pid>/cmdline` — for the entire
# job. Measured on the zai worker: a token nested inside the supervisor's own `--` command
# argument was readable by sibling workers of OTHER backends in the same run. Aggravated here,
# because Alibaba auto-disables keys it detects as publicly exposed.
#
# `--env-only "$ENV_ONLY_NAMES"` is load-bearing too, and not redundant with the outer `env -i`:
# a macOS Python.framework build adds SDKROOT / CPATH / LIBRARY_PATH / MANPATH and more to ITS
# OWN process on startup regardless of how it was launched, and Popen's default
# (inherit-everything) would hand all of that to `qwen`.
#
# The supervisor is the ONE timeout authority. Qwen's native --max-wall-time overlaps it and is
# deliberately not set: two racing timeouts produce an ambiguous failure class.
( cd "$WT" && \
env -i "$@" \
    HOME="$SCRATCH" \
    QWEN_HOME="$SCRATCH" \
    BAILIAN_TOKEN_PLAN_API_KEY="$QWEN_KEY" \
    OPENAI_BASE_URL="$OPENAI_BASE_URL" \
    QWEN_SANDBOX="$QWEN_SANDBOX" \
  python3 "$SUPERVISOR" --timeout "$TIMEOUT_SEC" --grace 3 --env-only "$ENV_ONLY_NAMES" -- \
    qwen --model "$MODEL" \
      --approval-mode=yolo \
      --auth-type openai \
      --output-format json \
      --session-id "$SESSION_ID" \
      --safe-mode \
      --max-subagent-depth 1 \
      --max-session-turns "$MAX_TURNS" \
      "$PROMPT_TEXT" \
  </dev/null >"$EVENTS_LOG" 2>"$STDERR_LOG" ) || exit_code=$?

# Flag facts this invocation encodes, written down rather than left to be re-derived — every
# one of them contradicts a plausible reading of the docs, and the sources are the released
# v0.21.5 CLI source, not the docs site:
#
#  1. `--approval-mode=yolo`, NEVER bare `--yolo`. Passing both is a hard parse error
#     ("Cannot use both --yolo (-y) and --approval-mode together"), exit 1 plus a help dump.
#  2. `--allowed-tools` is NEVER emitted: it bypasses confirmation, it does NOT restrict which
#     tools exist. The real restriction levers are --core-tools / --exclude-tools, and neither
#     is claimed here.
#  3. The prompt is POSITIONAL. `-p`/`--prompt` is deprecated at v0.21.5 and combining it with
#     a positional is a parse error.
#  4. `--safe-mode` is required, not optional: it disables context files (AGENTS.md — this
#     repo's own architecture document — QWEN.md, CONTEXT.md, .qwen/QWEN.local.md and their
#     transitive @-imports), hooks, extensions, skills AND MCP servers. Dropping it silently
#     re-opens that egress to Alibaba on every call.
#  5. `--worktree` is NEVER emitted: it starts the session in Qwen Code's OWN worktree under
#     .qwen/worktrees/ and prompts interactively on exit — headless that is a hang, and the
#     model would then edit files the scope gate never diffs.
#  6. `--auth-type openai` is MEASURED-redundant with security.auth.selectedType in the pinned
#     settings file, and kept anyway: it puts the auth path in the process line where an
#     operator reading `ps` can see it. Dropping BOTH fails with "No auth type is selected."
#     The choice list is exactly openai|anthropic|qwen-oauth|gemini|vertex-ai — there is NO
#     bailian/dashscope auth type, and every Anthropic-shaped path on the Bailian endpoint
#     measured 404, so `openai` is the only protocol this endpoint speaks.
#  7. `--session-id` IS honored, verified: the id handed in came back verbatim as `session_id`
#     on every element. It is also VALIDATED — a non-UUID value is a parse-time refusal
#     ("Invalid --session-id … Must be a valid UUID") plus a help dump, which is why the id is
#     minted by uuidgen/uuid4 and never hand-shaped.

# `usage` on the terminal `result` element measured as {input_tokens, output_tokens,
# cache_read_input_tokens} and, on the Token Plan, also total_tokens. compound-v-usage-extract.py
# reads input_tokens/output_tokens and ignores every other key, so an added field is inert; an
# empty-but-well-formed usage object still yields measured:false with null counts, never a
# fabricated 0. No cost figure is recorded, estimated, or carried anywhere.
USAGE_JSON="$(python3 "$USAGE_EXTRACT" --backend qwen --events-log "$EVENTS_LOG" 2>/dev/null)" \
  || USAGE_JSON="$(unmeasured_usage)"
[ -n "$USAGE_JSON" ] || USAGE_JSON="$(unmeasured_usage)"

# --- containment, part 3: a sandbox that never engaged is a WORKER fault ------
# There is no `sandbox` field in the output to read back (measured: no such key anywhere), so
# engagement cannot be observed. What CAN be observed is qwen complaining that it could not
# engage one. Two different texts, and the difference was measured, not read off the source:
#   * getSandboxCommand() throws FatalSandboxError when a KNOWN provider's command is missing —
#     "Missing sandbox command '…' (from QWEN_SANDBOX)" / "QWEN_SANDBOX is true but failed to
#     determine command for sandbox; install docker or podman or specify command in
#     QWEN_SANDBOX";
#   * an UNKNOWN provider name instead prints "Invalid sandbox command '…'. Must be one of
#     docker, podman, sandbox-exec" — and, measured, prints it in an UNBOUNDED LOOP without
#     ever exiting. So "qwen fails loudly" is only half true: on that path it hangs, and the
#     supervisor's timeout is what actually ends the job. Both texts are matched here anyway,
#     because a hang that the timeout catches still must not be filed as a model failure.
# This worker only ever emits a `command -v`-verified concrete name, so the unknown-name path
# should be unreachable; it is matched because "should be unreachable" is not a guarantee.
#
# NEVER the bare boolean, and the reason is measured too: with QWEN_SANDBOX=true and no
# SEATBELT_PROFILE, macOS silently selects the PERMISSIVE-OPEN profile (writes broad, network
# open) and reports "using macos seatbelt (profile: permissive-open)". That is a sandbox in
# name only. A concrete provider plus an explicit profile is what makes the confinement real.
#
# Checked BEFORE the timeout and exit-code branches on purpose. Classifying it as a model
# failure would file a job that never ran contained as `other`/`rate_limited` and let the
# dispatcher retry or reroute it; the operator's machine is what needs fixing, not the prompt.
# Verified not to false-positive on a healthy sandboxed run, whose stderr says only
# "using macos seatbelt (profile: …)" / "hopping into sandbox (command: …)".
if grep -qE 'FatalSandboxError|from QWEN_SANDBOX|failed to determine command for sandbox|Invalid sandbox command' \
     "$STDERR_LOG" 2>/dev/null; then
  die "qwen could not engage the mandatory sandbox (QWEN_SANDBOX=$QWEN_SANDBOX): $(head -c 300 "$STDERR_LOG")"
fi

# Supervisor timeout: killpg'd the whole process tree, exit 124.
if [ "$exit_code" = "124" ]; then
  emit_job_result "timeout" false '[]' '[]' \
    "worker exceeded ${TIMEOUT_SEC}s and was terminated" "$SESSION_ID" "$WT" 124 "timeout" 0 \
    "$USAGE_JSON"
  exit 0
fi

if [ "$exit_code" != "0" ]; then
  FAIL_JSON="$(python3 "$SCRIPT_DIR/compound-v-classify-failure.py" \
    --backend qwen --exit-code "$exit_code" --stderr-file "$STDERR_LOG" 2>/dev/null || echo '{}')"
  FAILURE_CLASS="$(printf '%s' "$FAIL_JSON" | jq -r '.failure_class // "other"' 2>/dev/null || echo other)"
  RETRY_AFTER="$(printf '%s' "$FAIL_JSON" | jq -r '.retry_after // 0' 2>/dev/null || echo 0)"
  RETRY_AT="$(printf '%s' "$FAIL_JSON" | jq -r '.retry_at // ""' 2>/dev/null || echo '')"
  NETWORK_SCOPE="$(printf '%s' "$FAIL_JSON" | jq -r '.network_scope // ""' 2>/dev/null || echo '')"
  ERR_TEXT="$(head -c 500 "$STDERR_LOG" 2>/dev/null || echo "")"
  emit_job_result "error" false '[]' '[]' \
    "worker exited $exit_code: $ERR_TEXT" "$SESSION_ID" "$WT" "$exit_code" \
    "$FAILURE_CLASS" "$RETRY_AFTER" "$USAGE_JSON" "$RETRY_AT" "$NETWORK_SCOPE"
  exit 0
fi

# --- the fail-closed model-identity assertion on a clean exit -----------------
# It reads the TRANSPORT's own envelope, and it runs only after the failure branches above, so
# a crashed or timed-out job still gets a classified job_result instead of a worker fault.
#
# MEASURED 2026-08-04 against qwen 0.21.5: the FIRST output element is
# {"type":"system","subtype":"init", …}. There is NO `session_start` element — that name does
# exist in the source but belongs to a different "dual output" protocol that
# `--output-format json` does not emit, and an earlier draft of this worker read it and would
# therefore have failed every real run closed. The init element's measured key set is exactly
# agents, cwd, mcp_servers, model, permission_mode, qwen_code_version, session_id,
# slash_commands, subtype, tools, type, uuid — `model` is present (measured "qwen3.8-max").
#
# NEVER read the served model from --json-schema/structured_output: that content is authored by
# the model, and a model cannot authenticate its own identity — a substituted model would
# simply assert the expected name. The plan's multi-vendor catalog (glm-*, deepseek-*) is what
# makes "did we get the model we asked for" a real question, and an
# ancestor-planted OPENAI_API_KEY — a name this design deliberately leaves unset, so it is free
# real estate — is a first-class alternate auth path this is the concrete defense against.
#
# Exactly one such element is required: missing, duplicated, or mismatched all fail closed.
SERVED_MODEL="$(jq -r '[.[] | select(.type=="system" and .subtype=="init") | .model] | if length==1 then .[0] else empty end' "$EVENTS_LOG" 2>/dev/null || true)"
[ -n "$SERVED_MODEL" ] || die "no unique system/init element carrying .model in the response — failing closed"
[ "$SERVED_MODEL" = "$MODEL" ] || die "served model '$SERVED_MODEL' != requested '$MODEL'"

# NO CONTAINMENT PROOF IS READ FROM THE PAYLOAD, because none exists: there is no `sandbox` key
# anywhere in the measured output. The deleted assertion could never have passed. Containment
# rests on the three enforceable steps documented in the header — refuse an ambient SANDBOX,
# hand qwen a concrete provider, treat FatalSandboxError as a worker fault — and the adapter
# doc says so plainly. Do not re-add a payload-derived proof without a field to read.

SUMMARY="$(jq -r '[.[] | select(.type=="result") | (.result // "")] | last // ""' "$EVENTS_LOG" 2>/dev/null || echo "")"

# --- THE SILENT-NO-OP GUARD: an API failure that reports itself as success ----
# MEASURED 2026-08-04, and it is the worst failure shape an orchestrator can get. A run whose
# EVERY API call failed still came back:
#
#     {"type":"result","subtype":"success","is_error":false, …,
#      "result":"[API Error: Connection error. (cause: connect ECONNREFUSED …)]"}
#
# exit 0. So `subtype` says success, `is_error` says false, the process says 0 — and the model
# never ran. The scope gate then correctly finds nothing changed, and without this guard the
# job is reported `status: success` having built nothing.
#
# Why that cannot be left as a documented quirk: this plan bills from CREDIT WINDOWS (12,000 /
# 5h). Window exhaustion is not an edge case, it is the normal end state of a busy run. Every
# job after that point would report success, the dispatcher would mark them done, and the run
# would "complete" with no work performed and nothing for the failure policy to reroute.
#
# TWO detectors, because `is_error` was MEASURED TO LIE and must not be trusted alone:
#   (a) is_error == true                      — believed when set, never relied on when false;
#   (b) the result string contains "[API Error:" — the shape actually observed.
# Substring, not an anchor: the measured strings began with it, but a partial run can emit
# assistant text first. Over-triggering turns a real success into a retryable error, which is
# the safe direction; under-triggering silently loses the whole run.
API_ERROR="$(jq -r '
  [.[] | select(.type=="result")] | last
  | if . == null then empty
    elif (.is_error == true)
      then (((.error // .result // "") | tostring)
            | if . == "" then "is_error:true with no error text" else . end)
    elif (((.result // "") | tostring) | contains("[API Error:"))
      then (.result | tostring)
    else empty end' "$EVENTS_LOG" 2>/dev/null || true)"

# --- the git-derived scope gate ----------------------------------------------
# Deterministic authority. Never re-implement glob matching in bash, and never read what the
# model said it changed.
#
# The allow-list is passed as REPEATED --allow ARGUMENTS, built HERE in the parent shell,
# rather than through a file on disk. The other workers write the list to
# "$ART/write_allowed.globs" before the child starts and read it back after the child exits —
# but that path is predictable and the child can write, so a job can overwrite its own
# allow-list before the gate ever reads it (reproduced on zai: a child that writes an
# out-of-scope file and then appends `**` to that file gets back a clean PASS). Positional
# parameters live in THIS process only; the child has no handle on them. `--allow-file` stays
# supported by the gate for other callers — only this worker's transport changes. `set -f`
# (noglob) stays mandatory around the unquoted split: entries are literal globs, not paths to
# expand against the launcher's cwd.
set --
_old_ifs="$IFS"
set -f
IFS=":"
for _glob in $WRITE_ALLOWED; do
  [ -n "$_glob" ] || continue
  set -- "$@" --allow "$_glob"
done
IFS="$_old_ifs"
set +f

# The gate signals its VERDICT through the exit code: 0 = clean, 1 = BLOCKED, 2 = a usage or
# git fault in the gate itself. Only 2 (or unparseable output) is fatal — treating 1 as a
# crash would turn every blocked job into a dead worker instead of a `blocked` job_result.
SCOPE_JSON=""
gate_rc=0
set +e
SCOPE_JSON="$(python3 "$SCOPE_CHECK" --worktree "$WT" --baseline "$BASELINE_SHA" \
  "$@" 2>"$ART/scope_check.err")"
gate_rc=$?
set -e
if [ "$gate_rc" -gt 1 ] || [ -z "$SCOPE_JSON" ] \
   || ! printf '%s' "$SCOPE_JSON" | jq -e . >/dev/null 2>&1; then
  die "scope gate failed (rc=$gate_rc): $(head -c 300 "$ART/scope_check.err")"
fi

FILES_JSON="$(printf '%s' "$SCOPE_JSON" | jq -c '.files_changed // .changed // []')"
VIOL_JSON="$(printf '%s' "$SCOPE_JSON" | jq -c '.violations // []')"
BLOCKED="$(printf '%s' "$SCOPE_JSON" | jq -r 'if ((.violations // []) | length) > 0 then "true" else "false" end')"

if [ "$BLOCKED" = "true" ]; then
  # Leave the worktree for inspection; the caller must NOT merge.
  #
  # BLOCKED wins over the API-error branch below, deliberately. A scope violation is the louder
  # signal — the worker wrote where it was not allowed to — and it must never be masked by a
  # later API failure. Both verdicts refuse the merge, so nothing is lost by ordering it first.
  emit_job_result "blocked" true "$FILES_JSON" "$VIOL_JSON" \
    "$SUMMARY" "$SESSION_ID" "$WT" 0 "" 0 "$USAGE_JSON"
  exit 0
fi

# The silent-no-op guard fires HERE, after the gate, so the emitted job_result carries the REAL
# files_changed rather than an assumed empty list. A run that changed nothing AND carries an
# API-error result can no longer come out as `success`.
if [ -n "$API_ERROR" ]; then
  # An emitted job_result, NOT a bare `die`. `die` exits 2 with no JSON, which the dispatcher
  # reads as a dead worker — unclassifiable, and the failure policy cannot reroute it. A
  # `status: error` with a real failure_class is what lets a 401 become `auth` and a spent
  # window become `usage_window_exhausted` and get handled instead of halting the run.
  printf '%s\n' "$API_ERROR" > "$ART/api_error.txt"
  # --exit-code 1, not 0, and this is load-bearing: classify() short-circuits `exit_code == 0`
  # to "none" before it ever looks at the text. The PROCESS did exit 0 — that stays truthful in
  # the emitted exit_code field below — but the JOB failed, so the classifier is handed a
  # non-zero code to unlock the needle matching it would otherwise skip.
  FAIL_JSON="$(python3 "$SCRIPT_DIR/compound-v-classify-failure.py" \
    --backend qwen --exit-code 1 --stderr-file "$ART/api_error.txt" 2>/dev/null || echo '{}')"
  FAILURE_CLASS="$(printf '%s' "$FAIL_JSON" | jq -r '.failure_class // "other"' 2>/dev/null || echo other)"
  RETRY_AFTER="$(printf '%s' "$FAIL_JSON" | jq -r '.retry_after // 0' 2>/dev/null || echo 0)"
  RETRY_AT="$(printf '%s' "$FAIL_JSON" | jq -r '.retry_at // ""' 2>/dev/null || echo '')"
  NETWORK_SCOPE="$(printf '%s' "$FAIL_JSON" | jq -r '.network_scope // ""' 2>/dev/null || echo '')"
  # exit_code stays 0: that is what the process really returned. The lie was never the exit
  # code, it was `subtype: success` — and the status field is where this run gets corrected.
  emit_job_result "error" false "$FILES_JSON" '[]' \
    "the transport reported success but the run carried an API error: $(printf '%s' "$API_ERROR" | head -c 400)" \
    "$SESSION_ID" "$WT" 0 "$FAILURE_CLASS" "$RETRY_AFTER" "$USAGE_JSON" "$RETRY_AT" "$NETWORK_SCOPE"
  exit 0
fi

emit_job_result "success" false "$FILES_JSON" "$VIOL_JSON" \
  "$SUMMARY" "$SESSION_ID" "$WT" 0 "" 0 "$USAGE_JSON"
exit 0
