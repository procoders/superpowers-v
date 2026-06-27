#!/usr/bin/env bash
#
# compound-v-run-cursor-worker.sh — Compound V Backend Launcher: the headless Cursor (cursor-agent) adapter.
#
# MIRRORS compound-v-run-antigravity-worker.sh (which mirrors the codex worker). Runs ONE
# file-scoped job on a headless `cursor-agent -p` worker inside a dedicated git worktree,
# then emits the canonical job_result (schemas/job_result.schema.json) on stdout as JSON.
# The enforcement fields (blocked / files_changed / violations) are GIT-DERIVED, never
# self-reported by the model — produced by DELEGATING to the deterministic Python authority
# (scripts/compound-v-scope-check.py), the same gate the dispatcher runs after every job.
# The worker does NOT re-implement glob matching in bash. The model's `--output-format json`
# `.result` text feeds only `summary`.
#
# Contract: skills/backend-launcher/SKILL.md + skills/backend-launcher/adapter-cursor.md
#
# !!! SAFETY — LOWER-TRUST BACKEND (read before using) !!!
# Unlike codex (`--sandbox workspace-write` = a kernel-level write-confinement root),
# cursor-agent has NO kernel write-confinement. `-p --force` (a.k.a. --yolo, REQUIRED for
# headless writes) lets the agent run arbitrary shell and write OUTSIDE the worktree. The
# worktree + post-hoc `git diff` gate enforces file-scope IN the worktree but CANNOT PREVENT
# an out-of-worktree write or shell side-effect. Cursor is therefore an OPT-IN, LOWER-TRUST
# backend (same tier as Antigravity) — prefer Codex (kernel-sandboxed) for untrusted /
# high-stakes work.
#
# TRUST/FORCE (VERIFIED live, cursor-agent 2025.09.12): in a fresh/untrusted directory a
# headless `-p` run REFUSES to proceed ("Pass --trust, --yolo, or -f if you trust this
# directory") and exits non-zero — even for a no-write task. So `-f` is REQUIRED for ALL
# headless runs; it both trusts the worktree AND auto-applies writes (verified: it created
# the file). A read-only / review job therefore still runs WITH `-f` and is enforced POST-HOC
# by the git-diff gate (empty write_allowed => any write is a violation => BLOCKED), exactly
# like the antigravity adapter. (`--trust` alone may give a propose-only mode, but that is not
# yet verified, so the worker does not rely on it.)
#
# Portability: stock-macOS bash 3.2.57 (NO associative arrays / mapfile / ${var,,})
# + jq. shellcheck-clean. Absolute paths throughout. Caller (the dispatcher) owns the
# merge-back decision; this script only OBSERVES and REPORTS — it never merges.
#
# Usage:
#   compound-v-run-cursor-worker.sh \
#     --run-id <id> --job-id <id> --repo <abs-repo-root> \
#     --prompt-file <abs-path> [--model <model>] \
#     --write-allowed "<glob>[:<glob>...]" \
#     [--timeout-sec <n>] [--network true|false] \
#     [--read-only true|false] [--output-schema <abs-path>]
#
# --model is OPTIONAL: when empty, `--model` is omitted and cursor-agent uses its configured
# default. --output-schema is ACCEPTED for CLI parity with the codex worker but IGNORED —
# cursor-agent has no output-schema flag. --network is advisory only (no kernel toggle).
# --read-only true OMITS --force (proposals only → no writes); default false passes --force.
#
# All file paths MUST be absolute. write_allowed is a colon-separated glob list, each glob
# matched repo-relative against the changed paths. An EMPTY --write-allowed (read-only /
# review job) means no writes are permitted, so ANY changed path is a violation → BLOCKED.
#
# Exit code: 0 when the job_result was produced (even for a BLOCKED/timeout/error job — those
# are reported IN job_result.status). Non-zero only on a usage / environment fault.

set -euo pipefail

# --- constants ---------------------------------------------------------------
TIMEOUT_EXIT_CODE=124          # GNU/BSD `timeout` convention when the limit fires
DEFAULT_TIMEOUT_SEC=900
DEFAULT_NETWORK=false
DEFAULT_READ_ONLY=false

# --- helpers -----------------------------------------------------------------

die() {
  echo "compound-v-run-cursor-worker: $1" >&2
  exit 2
}

# Emit the canonical job_result JSON on stdout, built entirely with jq so every field is
# correctly typed and escaped. files_changed / violations arrive as JSON ARRAYS (straight
# from the gate's NUL-correct output) and pass through untouched — no newline round-trip.
emit_job_result() {
  # $1 status  $2 blocked(true|false)  $3 files_json  $4 violations_json  $5 summary
  # $6 session_id  $7 worktree  $8 exit_code(int)  $9 failure_class ("" => null)
  # ${10} retry_after_seconds(int, 0 when unknown)
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
    '{
       status: $status,
       blocked: $blocked,
       files_changed: $files,
       violations:    $violations,
       summary: $summary,
       session_id: $session_id,
       worktree: $worktree,
       exit_code: $exit_code,
       failure_class: (if $failure_class == "" then null else $failure_class end),
       retry_after_seconds: $retry_after_seconds
     }'
}

# Validate an id against a strict safe-character allow-list (these ids become PATH SEGMENTS
# under $TMPROOT/compound-v/, and cleanup does `rm -rf`). Allow only [A-Za-z0-9._-]; reject
# `.`/`..`/empty. bash 3.2-safe.
id_is_safe() {
  _id="$1"
  [ -n "$_id" ] || return 1
  case "$_id" in
    .|..) return 1 ;;
    *[!A-Za-z0-9._-]*) return 1 ;;
  esac
  return 0
}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# --- argument parsing --------------------------------------------------------

RUN_ID=""
JOB_ID=""
REPO=""
PROMPT_FILE=""
MODEL=""
WRITE_ALLOWED=""
TIMEOUT_SEC="$DEFAULT_TIMEOUT_SEC"
NETWORK="$DEFAULT_NETWORK"
READ_ONLY="$DEFAULT_READ_ONLY"
OUTPUT_SCHEMA=""

while [ $# -gt 0 ]; do
  case "$1" in
    --run-id)        RUN_ID="$2"; shift 2 ;;
    --job-id)        JOB_ID="$2"; shift 2 ;;
    --repo)          REPO="$2"; shift 2 ;;
    --prompt-file)   PROMPT_FILE="$2"; shift 2 ;;
    --model)         MODEL="$2"; shift 2 ;;
    --write-allowed) WRITE_ALLOWED="$2"; shift 2 ;;
    --timeout-sec)   TIMEOUT_SEC="$2"; shift 2 ;;
    --network)       NETWORK="$2"; shift 2 ;;
    --read-only)     READ_ONLY="$2"; shift 2 ;;
    --output-schema) OUTPUT_SCHEMA="$2"; shift 2 ;;
    *) die "unknown argument: $1" ;;
  esac
done

# --- validation --------------------------------------------------------------

[ -n "$RUN_ID" ]      || die "--run-id is required"
[ -n "$JOB_ID" ]      || die "--job-id is required"
[ -n "$REPO" ]        || die "--repo is required"
[ -n "$PROMPT_FILE" ] || die "--prompt-file is required"
# --model is OPTIONAL (empty => cursor-agent's configured default).
# --write-allowed may be EMPTY for a read-only / review job (every changed path is a violation).

# --timeout-sec is interpolated UNQUOTED into the argv (word-split into the `timeout` prefix),
# so a crafted value could inject argv. Pin it to a positive integer BEFORE use.
case "$TIMEOUT_SEC" in
  ''|*[!0-9]*) die "--timeout-sec must be a positive integer: $TIMEOUT_SEC" ;;
esac

id_is_safe "$RUN_ID" || die "--run-id has invalid characters (allowed: A-Za-z0-9._-, not . or ..): $RUN_ID"
id_is_safe "$JOB_ID" || die "--job-id has invalid characters (allowed: A-Za-z0-9._-, not . or ..): $JOB_ID"

case "$REPO" in /*) : ;; *) die "--repo must be an absolute path: $REPO" ;; esac
case "$PROMPT_FILE" in /*) : ;; *) die "--prompt-file must be an absolute path: $PROMPT_FILE" ;; esac
[ -d "$REPO" ]        || die "--repo is not a directory: $REPO"
[ -f "$PROMPT_FILE" ] || die "--prompt-file not found: $PROMPT_FILE"
if [ -n "$OUTPUT_SCHEMA" ]; then
  case "$OUTPUT_SCHEMA" in /*) : ;; *) die "--output-schema must be absolute: $OUTPUT_SCHEMA" ;; esac
  [ -f "$OUTPUT_SCHEMA" ] || die "--output-schema not found: $OUTPUT_SCHEMA"
fi
# --read-only and --network are ADVISORY for cursor: `-f` is REQUIRED for any headless run
# (an untrusted dir is refused without it — verified), so it is ALWAYS passed; read-only is
# enforced POST-HOC by the git-diff gate (empty write_allowed blocks every write). Reference
# the parsed vars so they are intentionally consumed and the contract is explicit.
: "cursor: read_only=$READ_ONLY network=$NETWORK (both advisory; -f always passed, gate enforces scope)"

command -v jq           >/dev/null 2>&1 || die "jq not found on PATH"
command -v git          >/dev/null 2>&1 || die "git not found on PATH"
command -v python3      >/dev/null 2>&1 || die "python3 not found on PATH (scope gate + failure classifier need it)"
command -v cursor-agent >/dev/null 2>&1 || die "cursor-agent not found on PATH"

# Resolve which timeout binary is present (GNU `timeout` or coreutils `gtimeout`). cursor-agent
# has NO built-in --print-timeout, so without one of these there is NO wall-clock cap — the
# adapter doc notes this; install coreutils (`gtimeout`) for a hard cap on macOS.
TIMEOUT_BIN=""
if command -v timeout >/dev/null 2>&1; then
  TIMEOUT_BIN="timeout"
elif command -v gtimeout >/dev/null 2>&1; then
  TIMEOUT_BIN="gtimeout"
fi

# --- worktree lifecycle ------------------------------------------------------
# Worktrees live OUTSIDE the repo, under $TMPDIR, so no .gitignore change is needed.

TMPROOT="${TMPDIR:-/tmp}"
TMPROOT="${TMPROOT%/}"
case "$TMPROOT" in
  /*) : ;;
  *) die "TMPDIR must be an absolute path (got: $TMPROOT)" ;;
esac
TMPROOT_REAL="$(cd "$TMPROOT" 2>/dev/null && pwd -P)" || die "TMPDIR does not exist: $TMPROOT"
WT_PARENT="$TMPROOT_REAL/compound-v"
[ -L "$WT_PARENT" ] && die "refusing: worktree parent is a symlink: $WT_PARENT"
WT="$WT_PARENT/$RUN_ID/$JOB_ID"

mkdir -p "$(dirname "$WT")"
WT_PARENT_REAL="$(cd "$WT_PARENT" && pwd -P)"
WT_DIR_REAL="$(cd "$(dirname "$WT")" && pwd -P)"
case "$WT_DIR_REAL/" in
  "$WT_PARENT_REAL"/*/) : ;;
  *) die "refusing to operate on worktree path outside $WT_PARENT_REAL: $WT" ;;
esac
REPO_REAL="$(cd "$REPO" && pwd -P)"
case "$WT_DIR_REAL/" in
  "$REPO_REAL"/*) die "refusing: worktree path is inside the repo: $WT" ;;
esac

if [ -e "$WT" ]; then
  git -C "$REPO" worktree remove -f "$WT" >/dev/null 2>&1 || rm -rf "$WT"
fi

# Capture the BASELINE commit BEFORE `git worktree add` — a commit-to-hide-changes attempt is
# still detected because we diff against this pinned SHA, not the literal HEAD.
BASELINE_SHA="$(git -C "$REPO" rev-parse HEAD 2>/dev/null)" \
  || die "could not resolve baseline HEAD in $REPO"
[ -n "$BASELINE_SHA" ] || die "empty baseline HEAD in $REPO"

git -C "$REPO" worktree add "$WT" HEAD >/dev/null 2>&1 \
  || die "git worktree add failed for $WT"

ART="$WT.art"
mkdir -p "$ART"

# --- run the headless Cursor worker ------------------------------------------
# cursor-agent headless (verified flag surface, cursor-agent 2025.09.12 + docs/cli/headless):
#   cd "$WT" && cursor-agent -p [--force] --output-format json [--model "$M"] "$PROMPT" </dev/null
# prints a single JSON object whose `.result` is the agent's final message.
#
# Load-bearing facts:
#   * `-p/--print` = non-interactive; `--output-format json` = ONE JSON object on stdout (verified).
#   * `-f` (force/trust) is REQUIRED for ANY headless run: an untrusted worktree is refused
#     without it (verified live), and it is what lets writes land. Always passed; read-only is
#     enforced post-hoc by the git-diff gate. See SAFETY banner.
#   * cursor-agent runs against the CURRENT directory — we `cd "$WT"` (no --add-dir flag).
#   * stdin redirected </dev/null (the same hard-won lesson as codex/agy).
#   * No built-in timeout flag — the optional `timeout`/`gtimeout` prefix is the only cap.
#   * VERIFIED output shape: `{"type":"result","result": <final message>, "session_id": <uuid>, …}`.
#     `.result` → summary; `.session_id` → session_id for `cursor-agent --resume <id>`. (`.usage`
#     token counts are deliberately IGNORED — anti-ruflo: we never emit token/cost metrics.)

STDERR_LOG="$ART/cursor_stderr.log"
STDOUT_LOG="$ART/cursor_stdout.log"
exit_code=0

# run_cursor runs the pinned, VERIFIED invocation. `-f` (force/trust) is ALWAYS passed: a
# headless run in an untrusted worktree is refused without it (verified live), and it is what
# lets writes land. $TIMEOUT_PREFIX and the optional --model word-split into the argv (or
# vanish when empty) — hence the SC2086 disables. The prompt value is the LAST positional
# argument; stdin is </dev/null.
run_cursor() {
  cd "$WT" || return 2
  if [ -n "$MODEL" ]; then
    # shellcheck disable=SC2086
    $TIMEOUT_PREFIX cursor-agent -p -f --output-format json \
      --model "$MODEL" "$(cat "$PROMPT_FILE")" </dev/null
  else
    # shellcheck disable=SC2086
    $TIMEOUT_PREFIX cursor-agent -p -f --output-format json \
      "$(cat "$PROMPT_FILE")" </dev/null
  fi
}

TIMEOUT_PREFIX=""
if [ -n "$TIMEOUT_BIN" ]; then
  TIMEOUT_PREFIX="$TIMEOUT_BIN $TIMEOUT_SEC"
fi

set +e
run_cursor >"$STDOUT_LOG" 2>"$STDERR_LOG"
exit_code=$?
set -e

# --- capture session_id + summary --------------------------------------------
# stdout is a single JSON object (--output-format json). `.result` is the final message →
# summary. A chat/session id (field name varies by version — try the common ones) → session_id
# for resume; "" if absent or the output was not parseable JSON (fall back to raw stdout).
session_id=""
summary=""
if [ -s "$STDOUT_LOG" ] && jq -e . "$STDOUT_LOG" >/dev/null 2>&1; then
  summary=$(jq -r '.result // .text // .response // ""' "$STDOUT_LOG" 2>/dev/null || true)
  session_id=$(jq -r '.chatId // .chat_id // .session_id // .sessionId // .id // ""' "$STDOUT_LOG" 2>/dev/null || true)
fi
if [ -z "$summary" ] && [ -f "$STDOUT_LOG" ]; then
  summary=$(cat "$STDOUT_LOG")
fi
[ -n "$summary" ] || summary="(no summary emitted by worker)"
case "$session_id" in null) session_id="" ;; esac

# --- git-derived enforcement (delegated to the Python scope gate) ------------
# Authoritative enforcement comes from scripts/compound-v-scope-check.py — the SAME
# deterministic gate the dispatcher runs after every job. write_allowed (colon-separated
# globs) is expanded one-per-line into an allow-file under $ART (outside the worktree). An
# EMPTY allow-list makes EVERY changed path a violation (read-only job that writes => BLOCKED).
# Baseline = the pinned SHA captured before `worktree add` (in-worktree commits still diffed).

ALLOW_FILE="$ART/write_allowed.globs"
: > "$ALLOW_FILE"
_OLDIFS="$IFS"
IFS=":"
for _glob in $WRITE_ALLOWED; do
  IFS="$_OLDIFS"
  [ -z "$_glob" ] && continue
  printf '%s\n' "$_glob" >> "$ALLOW_FILE"
done
IFS="$_OLDIFS"

GATE_JSON=""
gate_rc=0
set +e
GATE_JSON=$(python3 "$SCRIPT_DIR/compound-v-scope-check.py" \
  --worktree "$WT" --baseline "$BASELINE_SHA" --allow-file "$ALLOW_FILE" 2>"$ART/scope_check.err")
gate_rc=$?
set -e

files_json="[]"
violations_json="[]"
viol_count=0
gate_verdict=""
if [ -n "$GATE_JSON" ] && printf '%s' "$GATE_JSON" | jq -e . >/dev/null 2>&1; then
  gate_verdict=$(printf '%s' "$GATE_JSON" | jq -r '.verdict // ""')
  files_json=$(printf '%s' "$GATE_JSON" | jq -c '.changed // []')
  violations_json=$(printf '%s' "$GATE_JSON" | jq -c '.violations // []')
  viol_count=$(printf '%s' "$GATE_JSON" | jq '(.violations // []) | length')
fi

# --- derive status -----------------------------------------------------------
blocked="false"
status="success"

if [ "$gate_verdict" = "blocked" ] || [ "$viol_count" -gt 0 ]; then
  blocked="true"
  status="blocked"
elif [ "$gate_rc" != "0" ] && [ "$gate_rc" != "1" ]; then
  status="error"
elif [ "$exit_code" = "$TIMEOUT_EXIT_CODE" ]; then
  status="timeout"
elif [ "$exit_code" != "0" ]; then
  status="error"
fi

# --- classify a backend failure ----------------------------------------------
# A non-success / non-blocked status carries a failure_class driving the dispatcher's
# retry/reroute/halt policy. The classifier reads cursor-agent's captured stderr.
failure_class=""
retry_after="0"
if [ "$status" = "error" ] || [ "$status" = "timeout" ] || [ "$exit_code" != "0" ]; then
  if [ "$gate_rc" != "0" ] && [ "$gate_rc" != "1" ]; then
    failure_class="other"
  else
    _cls_json=$(python3 "$SCRIPT_DIR/compound-v-classify-failure.py" \
      --backend cursor --exit-code "$exit_code" --stderr-file "$STDERR_LOG" 2>/dev/null || true)
    failure_class=$(printf '%s' "$_cls_json" | jq -r '.failure_class' 2>/dev/null || true)
    retry_after=$(printf '%s' "$_cls_json" | jq -r '.retry_after // 0' 2>/dev/null || echo 0)
  fi
  case "$failure_class" in
    ""|null|none) failure_class="other" ;;
  esac
  case "$retry_after" in
    ''|*[!0-9]*) retry_after="0" ;;
  esac
fi

# --- emit --------------------------------------------------------------------
emit_job_result \
  "$status" \
  "$blocked" \
  "$files_json" \
  "$violations_json" \
  "$summary" \
  "$session_id" \
  "$WT" \
  "$exit_code" \
  "$failure_class" \
  "$retry_after"

exit 0
