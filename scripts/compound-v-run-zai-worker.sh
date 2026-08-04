#!/usr/bin/env bash
#
# compound-v-run-zai-worker.sh — headless z.ai (GLM) worker for Compound V.
#
# Runs ONE file-scoped job as a Bash-spawned `claude -p` process pointed at z.ai's
# Anthropic-compatible endpoint, inside its own git worktree, and emits the canonical
# job_result on stdout. Implements skills/backend-launcher/adapter-zai.md.
#
# z.ai ships no headless CLI of its own; Claude Code is a tier-1 officially supported tool
# for the GLM Coding Plan, so driving the genuine binary is the compliant path.
#
# !!! SAFETY — lower-trust, opt-in, WORKER-ONLY !!!
# There is NO kernel write-confinement here (contrast codex's --sandbox workspace-write).
# The worktree plus the git-derived scope gate DETECTS an in-worktree scope leak but cannot
# PREVENT an out-of-worktree side effect. Prefer codex for untrusted / high-stakes work.
#
# Enforcement (blocked/files_changed/violations) is git-derived by
# scripts/compound-v-scope-check.py — never self-reported by the model.
#
# bash 3.2 safe: no arrays, no ${var,,}, no readarray.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SUPERVISOR="$SCRIPT_DIR/compound-v-run-with-timeout.py"
SCOPE_CHECK="$SCRIPT_DIR/compound-v-scope-check.py"
USAGE_EXTRACT="$SCRIPT_DIR/compound-v-usage-extract.py"

# Pinned, not caller-overridable: an ambient ZAI_BASE_URL in the dispatcher's own
# environment must not be able to redirect this worker to an unpinned endpoint
# before the credential scrub even runs.
ZAI_BASE_URL="https://api.z.ai/api/anthropic"

# The MANDATORY provider-credential scrub, as an ALLOWLIST rather than a denylist. `env -i`
# clears EVERY inherited variable and only these names are injected back with their parent
# values; a credential can reach the child ONLY if it is named here, never by omission from a
# denylist. Note HOME is absent on purpose — it is replaced with a scratch dir below.
_SAFE_ENV_VARS="PATH TMPDIR LANG"

# --- helpers -----------------------------------------------------------------

die() {
  # Environment/usage fault: no job_result could be produced.
  echo "compound-v-run-zai-worker: $1" >&2
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
  jq -n --arg b zai \
    '{input_tokens: null, output_tokens: null, advisor_calls: null, backend: $b, measured: false}'
}

# --- arguments ---------------------------------------------------------------

RUN_ID=""""; JOB_ID=""; REPO=""; PROMPT_FILE=""; MODEL=""
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

# NETWORK is accepted for CLI parity with the codex worker and then deliberately DISCARDED:
# this backend has no kernel sandbox, so there is no network toggle to map it onto. Referenced
# here so the discard is explicit rather than an oversight — never claim enforcement that does
# not exist.
: "$NETWORK"

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

# `xhigh` is codex-only. Every other backend rejects it with a message naming the rule.
case "$EFFORT" in
  ""|low|medium|high) : ;;
  xhigh) die "effort 'xhigh' is codex-only; use 'high' for backend zai" ;;
  *) die "unknown --effort '$EFFORT' (expected low|medium|high)" ;;
esac

# --- preflight ---------------------------------------------------------------

command -v jq      >/dev/null 2>&1 || die "jq not found on PATH"
command -v git     >/dev/null 2>&1 || die "git not found on PATH"
command -v python3 >/dev/null 2>&1 || die "python3 not found on PATH"
command -v claude  >/dev/null 2>&1 || die "claude not found on PATH"
# `env` is the vehicle for the MANDATORY credential scrub — without it we must NOT silently
# fall through to an unscrubbed invocation.
command -v env     >/dev/null 2>&1 || die "env not found on PATH (required for the credential scrub)"
[ -f "$SUPERVISOR" ]     || die "supervisor not found: $SUPERVISOR"
[ -f "$SCOPE_CHECK" ]    || die "scope gate not found: $SCOPE_CHECK"
[ -f "$USAGE_EXTRACT" ]  || die "usage extractor not found: $USAGE_EXTRACT"

ZAI_KEY="${ZAI_API_KEY:-}"
[ -n "$ZAI_KEY" ] || die "ZAI_API_KEY is not set (the GLM Coding Plan key; see commands/v-init.md)"

# --- worktree + scratch ------------------------------------------------------

WT_PARENT="${TMPDIR:-/tmp}/compound-v"
WT="$WT_PARENT/$RUN_ID/$JOB_ID"
ART="$WT.art"          # scratch OUTSIDE the worktree so the diff stays pristine
SCRATCH="$ART/home"    # the worker's HOME — see the credential note below

# Baseline captured BEFORE `worktree add`, so the gate diffs against the commit the worktree
# was actually created from.
BASELINE_SHA="$(git -C "$REPO" rev-parse HEAD 2>/dev/null)" || die "cannot resolve HEAD in $REPO"

mkdir -p "$WT_PARENT/$RUN_ID" "$ART" "$SCRATCH/.claude"

# Idempotent on resume: drop any stale worktree at this path, then recreate at current HEAD.
if [ -e "$WT" ]; then
  git -C "$REPO" worktree remove -f "$WT" >/dev/null 2>&1 || rm -rf "$WT"
fi
git -C "$REPO" worktree add "$WT" HEAD >/dev/null 2>&1 || die "cannot create worktree at $WT"

EVENTS_LOG="${EVENTS_LOG_OVERRIDE:-$ART/zai_result.json}"
STDERR_LOG="$ART/zai_stderr.log"
mkdir -p "$(dirname "$EVENTS_LOG")"

# --read-only is enforced POST-HOC, exactly as the contract says: an EMPTY allow-list makes the
# gate treat EVERY changed path as a violation, so a read-only job that writes anything is
# correctly BLOCKED. No kernel flag is involved and none is claimed.
if [ "$READ_ONLY" = "true" ]; then
  WRITE_ALLOWED=""
fi
# NOTE: unlike the other five workers, the allow-list is NOT written to a file here. See the
# scope-gate invocation below for why — it is built as --allow arguments instead.

# --- run ---------------------------------------------------------------------

# Build the `env -i` allow-list as POSITIONAL PARAMETERS, not a concatenated string: bash 3.2
# has no arrays, but `set --` keeps each entry as ONE argument even when a value contains
# spaces (a PATH segment like "/Applications/Some App.app/..." is a real-world case a naive
# string splice would corrupt).
set --
for _v in $_SAFE_ENV_VARS; do
  eval "_safe_val=\"\${$_v-}\""
  if [ -n "$_safe_val" ]; then
    set -- "$@" "$_v=$_safe_val"
  fi
done

PROMPT_TEXT="$(cat "$PROMPT_FILE")"

# The names `claude` is allowed to receive, comma-joined for --env-only below. Static list,
# not conditioned on which are actually set — an absent name is silently skipped downstream
# (compound-v-run-with-timeout.py's --env-only reads from ITS OWN environment; nothing here
# ever forwards a value that was never in $_SAFE_ENV_VARS to begin with).
ENV_ONLY_NAMES="$(printf '%s' "$_SAFE_ENV_VARS" | tr ' ' ',')"
ENV_ONLY_NAMES="$ENV_ONLY_NAMES,HOME,CLAUDE_CONFIG_DIR,ANTHROPIC_BASE_URL,ANTHROPIC_AUTH_TOKEN"
ENV_ONLY_NAMES="$ENV_ONLY_NAMES,ANTHROPIC_MODEL,ANTHROPIC_DEFAULT_OPUS_MODEL"
ENV_ONLY_NAMES="$ENV_ONLY_NAMES,ANTHROPIC_DEFAULT_SONNET_MODEL,ANTHROPIC_DEFAULT_HAIKU_MODEL"
ENV_ONLY_NAMES="$ENV_ONLY_NAMES,API_TIMEOUT_MS,CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"

exit_code=0
# `claude` has no --cd/--workdir equivalent (contrast `codex exec --cd`), so the worktree is
# entered with a SUBSHELL cd. Without it the worker would edit files in the LAUNCHER's cwd —
# the repo root — and the scope gate, which diffs the worktree, would see an empty diff and
# wave through a job that changed nothing where it was supposed to.
#
# `env -i` wraps the SUPERVISOR here, not `claude` directly — load-bearing for the credential.
# `env` builds the child's environment from its operands and then EXECS into it, replacing its
# own process image; whatever briefly held the token in argv stops existing within a fork/exec
# instant. The python3 supervisor is the opposite: it stays running for the WHOLE job to
# enforce the wall-clock timeout, so a value passed as one of ITS OWN arguments sits in that
# long-lived process's argv — world-readable via `ps`/`/proc/<pid>/cmdline` — for the entire
# job. Measured: with the token nested inside the supervisor's own `--` command argument (the
# previous shape), `ps -eo command` on a live worker showed `ANTHROPIC_AUTH_TOKEN=<key>`,
# readable by sibling workers of OTHER backends in the same run even though the credential
# scrub deliberately never gave it to them. Wrapping the supervisor instead keeps every var off
# any long-lived process's command line.
#
# `--env-only "$ENV_ONLY_NAMES"` is load-bearing too, and not redundant with the outer `env -i`:
# measured, this machine's python3 (a macOS Python.framework build) adds SDKROOT / CPATH /
# LIBRARY_PATH / MANPATH / __CF_USER_TEXT_ENCODING and more to ITS OWN process on startup,
# regardless of how it was launched — Popen's default (inherit-everything) behaviour would
# hand all of that to `claude` too. `--env-only` builds `claude`'s environment from scratch out
# of exactly the named list, discarding anything the supervisor's own runtime added.
( cd "$WT" && \
env -i "$@" \
    HOME="$SCRATCH" \
    CLAUDE_CONFIG_DIR="$SCRATCH/.claude" \
    ANTHROPIC_BASE_URL="$ZAI_BASE_URL" \
    ANTHROPIC_AUTH_TOKEN="$ZAI_KEY" \
    ANTHROPIC_MODEL="$MODEL" \
    ANTHROPIC_DEFAULT_OPUS_MODEL="$MODEL" \
    ANTHROPIC_DEFAULT_SONNET_MODEL="$MODEL" \
    ANTHROPIC_DEFAULT_HAIKU_MODEL="$MODEL" \
    API_TIMEOUT_MS="$((TIMEOUT_SEC * 1000))" \
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
  python3 "$SUPERVISOR" --timeout "$TIMEOUT_SEC" --grace 3 --env-only "$ENV_ONLY_NAMES" -- \
    claude -p \
      --permission-mode dontAsk \
      --tools "Read,Edit,Write,Bash" \
      --allowedTools "Read,Edit,Write,Bash" \
      --exclude-dynamic-system-prompt-sections \
      --output-format json \
      -- "$PROMPT_TEXT" \
  </dev/null >"$EVENTS_LOG" 2>"$STDERR_LOG" ) || exit_code=$?

# Four facts the invocation above encodes. Each was MEASURED on 2026-08-01 against
# claude 2.1.207; a future editor who "simplifies" any of them will break the worker
# silently, so they are written down rather than left to be re-derived:
#
#  1. ANTHROPIC_DEFAULT_HAIKU_MODEL is a Claude Code SLOT NAME, not a model choice. It is
#     filled with the resolved GLM model exactly like the other two slots, so the plugin's
#     never-Haiku policy is untouched. z.ai's own integration guide sets all three; an unset
#     small/fast slot sends an Anthropic identifier and earns `400 [1211][Unknown Model]`.
#
#  2. `--tools` and `--allowedTools` are DIFFERENT THINGS and BOTH are required. `--tools`
#     decides which built-in tools EXIST; `--allowedTools` decides which run without asking.
#     With only --allowedTools the worker had Bash but NO Write; with only --tools, dontAsk
#     refused the write. `Grep`/`Glob` do not exist as tools in this CLI version at all —
#     searching goes through Bash.
#
#  3. `--` before the prompt is not decoration: --tools and --allowedTools are VARIADIC and
#     swallow the positional prompt without it.
#
#  4. `--bare` is deliberately NOT used. In bare mode the built-in set is exactly
#     Bash,Edit,Read — `Write` does not exist and cannot be restored by --tools — so a bare
#     worker cannot create a new file. HOME/CLAUDE_CONFIG_DIR redirection buys ONLY the
#     USER-LEVEL half of bare's isolation (no operator hooks, plugins, skills catalogue,
#     ~/.claude/.credentials.json out of reach) while keeping Write. It does NOT exclude
#     CLAUDE.md: $WT is a checkout of this repo, so the PROJECT-level CLAUDE.md and
#     .claude/settings.json are still live and reach z.ai on every job — measured with a
#     marker file, see adapter-zai.md's Compliance section for the disclosure.

USAGE_JSON="$(python3 "$USAGE_EXTRACT" --backend zai --events-log "$EVENTS_LOG" 2>/dev/null)" \
  || USAGE_JSON="$(unmeasured_usage)"
[ -n "$USAGE_JSON" ] || USAGE_JSON="$(unmeasured_usage)"

# Supervisor timeout: killpg'd the whole process tree, exit 124.
if [ "$exit_code" = "124" ]; then
  emit_job_result "timeout" false '[]' '[]' \
    "worker exceeded ${TIMEOUT_SEC}s and was terminated" "" "$WT" 124 "timeout" 0 "$USAGE_JSON"
  exit 0
fi

SUMMARY="$(jq -r '.result // ""' "$EVENTS_LOG" 2>/dev/null || echo "")"
SESSION_ID="$(jq -r '.session_id // ""' "$EVENTS_LOG" 2>/dev/null || echo "")"
# Same UUID anchor the codex worker uses — `claude -p` emits a real RFC-4122 UUID.
case "$SESSION_ID" in
  [0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]-[0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]-[0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]-[0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]-[0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]) : ;;
  *) SESSION_ID="" ;;
esac

# THE GLM ASSERTION — the deterministic compensating control for the one guarantee this
# invocation cannot make structurally. `--bare` would have guaranteed OAuth and keychain are
# never read; we are not using it (see note 4 above), so instead we CHECK where the response
# actually came from. A non-GLM model means the request did not reach z.ai, and the job fails
# rather than letting an unnoticed charge land on some other credential.
# Check EVERY modelUsage key, not just the first: a response that mixes a glm-*
# key with a later-sorting non-GLM key (e.g. a haiku-slot fallback) must still
# fail, not pass on the strength of whichever key sorts first.
NON_GLM_MODEL="$(jq -r '(.modelUsage // {}) | keys | map(select(startswith("glm-") | not)) | .[0] // ""' "$EVENTS_LOG" 2>/dev/null || echo "")"
MODEL_COUNT="$(jq -r '(.modelUsage // {}) | keys | length' "$EVENTS_LOG" 2>/dev/null || echo 0)"
if [ "$exit_code" = "0" ]; then
  if [ "$MODEL_COUNT" = "0" ] || [ -n "$NON_GLM_MODEL" ]; then
    SERVED_MODEL="${NON_GLM_MODEL:-"(none)"}"
    emit_job_result "error" false '[]' '[]' \
      "response came from model '$SERVED_MODEL', not a GLM — the request did not reach z.ai" \
      "$SESSION_ID" "$WT" 1 "other" 0 "$USAGE_JSON"
    exit 0
  fi
fi

if [ "$exit_code" != "0" ]; then
  FAIL_JSON="$(python3 "$SCRIPT_DIR/compound-v-classify-failure.py" \
    --backend zai --exit-code "$exit_code" --stderr-file "$STDERR_LOG" 2>/dev/null || echo '{}')"
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

# --- the git-derived scope gate ----------------------------------------------
# Deterministic authority. Never re-implement glob matching in bash, and never read what the
# model said it changed.
#
# The allow-list is passed as REPEATED --allow ARGUMENTS, built HERE in the parent shell,
# rather than through a file on disk. The other five workers write the list to
# "$ART/write_allowed.globs" before the child starts and read it back after the child exits —
# but that path is predictable, and the child has Bash + Write with no kernel confinement, so a
# job can overwrite its own allow-list before the gate ever reads it (reproduced: a child that
# writes an out-of-scope file and then appends `**` to that file gets back a clean PASS).
# Positional parameters live in THIS process only; the child has no handle on them and no way to
# reach them. `--allow-file` stays supported by the gate itself for other callers — only this
# worker's transport changes. `set -f` (noglob) stays mandatory around the unquoted split:
# entries are literal globs, not paths to expand against the launcher's cwd.
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
  emit_job_result "blocked" true "$FILES_JSON" "$VIOL_JSON" \
    "$SUMMARY" "$SESSION_ID" "$WT" 0 "" 0 "$USAGE_JSON"
  exit 0
fi

emit_job_result "success" false "$FILES_JSON" "$VIOL_JSON" \
  "$SUMMARY" "$SESSION_ID" "$WT" 0 "" 0 "$USAGE_JSON"
exit 0
