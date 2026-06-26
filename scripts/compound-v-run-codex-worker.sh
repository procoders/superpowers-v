#!/usr/bin/env bash
#
# compound-v-run-codex-worker.sh — Compound V Backend Launcher: the headless Codex adapter.
#
# Runs ONE file-scoped job on a headless `codex exec` worker inside a dedicated git
# worktree, then emits the canonical job_result (schemas/job_result.schema.json) on
# stdout as JSON. The enforcement fields (blocked / files_changed / violations) are
# GIT-DERIVED here, never self-reported by the model: we diff the worktree and union
# in untracked files, then test every changed path against write_allowed. The model's
# --output-last-message text feeds only the human `summary`.
#
# Contract: skills/backend-launcher/SKILL.md + skills/backend-launcher/adapter-codex.md
#
# Portability: stock-macOS bash 3.2.57 (NO associative arrays / mapfile / ${var,,})
# + jq. shellcheck-clean. Absolute paths throughout. Caller (the dispatcher) owns the
# merge-back decision; this script only OBSERVES and REPORTS — it never merges.
#
# Usage:
#   compound-v-run-codex-worker.sh \
#     --run-id <id> --job-id <id> --repo <abs-repo-root> \
#     --prompt-file <abs-path> --model <model> \
#     --write-allowed "<glob>[:<glob>...]" \
#     [--timeout-sec <n>] [--network true|false] \
#     [--read-only true|false] [--output-schema <abs-path>] \
#     [--effort low|medium|high]
#
# All file paths MUST be absolute. write_allowed is a colon-separated glob list,
# each glob matched repo-relative against the changed paths.
#
# Exit code: 0 when the job_result was produced (even for a BLOCKED/timeout/error
# job — those are reported IN the job_result.status). Non-zero only on a usage /
# environment fault that prevented producing a result at all.

set -euo pipefail

# --- constants ---------------------------------------------------------------
TIMEOUT_EXIT_CODE=124          # GNU/BSD `timeout` convention when the limit fires
DEFAULT_TIMEOUT_SEC=900
DEFAULT_NETWORK=false
DEFAULT_READ_ONLY=false

# --- helpers -----------------------------------------------------------------

die() {
  # Environment/usage fault: no job_result could be produced.
  echo "compound-v-run-codex-worker: $1" >&2
  exit 2
}

# Emit the canonical job_result JSON on stdout, built entirely with jq so every
# field is correctly typed and escaped. Arrays arrive as newline-joined strings
# and are split with jq's split/select to drop the trailing empty element.
emit_job_result() {
  # $1 status  $2 blocked(true|false)  $3 files_nl  $4 violations_nl
  # $5 summary  $6 session_id  $7 worktree  $8 exit_code(int)
  jq -n \
    --arg status "$1" \
    --argjson blocked "$2" \
    --arg files "$3" \
    --arg violations "$4" \
    --arg summary "$5" \
    --arg session_id "$6" \
    --arg worktree "$7" \
    --argjson exit_code "$8" \
    '{
       status: $status,
       blocked: $blocked,
       files_changed: ($files     | split("\n") | map(select(length > 0))),
       violations:    ($violations | split("\n") | map(select(length > 0))),
       summary: $summary,
       session_id: $session_id,
       worktree: $worktree,
       exit_code: $exit_code
     }'
}

# Test one repo-relative path against the colon-separated write_allowed glob list.
# Returns 0 (allowed) if any glob matches, 1 (not allowed) otherwise. Uses bash
# `case` glob matching, which honours ** loosely via * — adequate because the
# authoritative gate is scripts/compound-v-scope-check.py; this is the adapter's
# fast first-pass so it can self-report a clean job_result.
path_is_allowed() {
  _candidate="$1"
  _globs="$2"
  _OLDIFS="$IFS"
  IFS=":"
  for _glob in $_globs; do
    IFS="$_OLDIFS"
    [ -z "$_glob" ] && continue
    # Normalise a trailing "/**" to "/*" so bash case-globbing matches nested paths.
    _g="$_glob"
    case "$_g" in
      */\*\*) _g="${_g%/\*\*}/*" ;;
    esac
    # shellcheck disable=SC2254  # intentional glob match against the pattern var
    case "$_candidate" in
      $_g) return 0 ;;
    esac
    # Also accept the directory-prefix form: "a/b/**" should match "a/b/c/d".
    case "$_glob" in
      */\*\*)
        _prefix="${_glob%/\*\*}/"
        case "$_candidate" in
          "$_prefix"*) return 0 ;;
        esac
        ;;
    esac
  done
  IFS="$_OLDIFS"
  return 1
}

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
EFFORT=""

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
    --effort)        EFFORT="$2"; shift 2 ;;
    *) die "unknown argument: $1" ;;
  esac
done

# --- validation --------------------------------------------------------------

[ -n "$RUN_ID" ]        || die "--run-id is required"
[ -n "$JOB_ID" ]        || die "--job-id is required"
[ -n "$REPO" ]          || die "--repo is required"
[ -n "$PROMPT_FILE" ]   || die "--prompt-file is required"
[ -n "$MODEL" ]         || die "--model is required"
[ -n "$WRITE_ALLOWED" ] || die "--write-allowed is required"

case "$REPO" in /*) : ;; *) die "--repo must be an absolute path: $REPO" ;; esac
case "$PROMPT_FILE" in /*) : ;; *) die "--prompt-file must be an absolute path: $PROMPT_FILE" ;; esac
[ -d "$REPO" ]        || die "--repo is not a directory: $REPO"
[ -f "$PROMPT_FILE" ] || die "--prompt-file not found: $PROMPT_FILE"
if [ -n "$OUTPUT_SCHEMA" ]; then
  case "$OUTPUT_SCHEMA" in /*) : ;; *) die "--output-schema must be absolute: $OUTPUT_SCHEMA" ;; esac
  [ -f "$OUTPUT_SCHEMA" ] || die "--output-schema not found: $OUTPUT_SCHEMA"
fi
if [ -n "$EFFORT" ]; then
  case "$EFFORT" in
    low|medium|high) : ;;
    *) die "--effort must be one of low|medium|high: $EFFORT" ;;
  esac
fi
command -v jq  >/dev/null 2>&1 || die "jq not found on PATH"
command -v git >/dev/null 2>&1 || die "git not found on PATH"

# Resolve which timeout binary is present (GNU `timeout` or coreutils `gtimeout`).
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
WT="$TMPROOT/compound-v/$RUN_ID/$JOB_ID"

# Clean any stale worktree at this path (idempotent re-dispatch on resume).
if [ -e "$WT" ]; then
  git -C "$REPO" worktree remove -f "$WT" >/dev/null 2>&1 || rm -rf "$WT"
fi
mkdir -p "$(dirname "$WT")"

# `git worktree add <path> HEAD` — fresh checkout at HEAD = clean diff baseline.
git -C "$REPO" worktree add "$WT" HEAD >/dev/null 2>&1 \
  || die "git worktree add failed for $WT"

# Adapter scratch lives OUTSIDE the worktree, in a sibling dir under $TMPDIR (which is
# one of codex's workspace-write sandbox roots, so --output-last-message can be written
# there). This keeps the worktree PRISTINE: only the job's real output shows up in
# `git diff`, so the generic scope-gate (scripts/compound-v-scope-check.py) agrees with
# this worker's own git-derived enforcement WITHOUT needing any codex-specific ignore list.
ART="$WT.art"
mkdir -p "$ART"
RESULT_TXT="$ART/job_result.txt"

# --- run the headless Codex worker -------------------------------------------
# Pinned flag set, verified live against codex-cli 0.130. NOTE: `--ask-for-approval
# never` is INVALID for `codex exec` (top-level/interactive flag only) and is
# deliberately OMITTED — `codex exec` already defaults to approval: never.
#
# codex emits a cosmetic `[features].codex_hooks is deprecated` warning on stderr;
# we filter exactly that line out of the captured stderr so it does not pollute the
# banner we scan for the session UUID. Everything else on stderr is preserved.

SANDBOX="workspace-write"
if [ "$READ_ONLY" = "true" ]; then
  SANDBOX="read-only"
fi

STDERR_LOG="$ART/codex_stderr.log"
# codex prints its FINAL agent message to stdout; we must NOT let it reach our stdout,
# which is reserved for the canonical job_result JSON alone. Capture + discard it (the
# human summary comes from --output-last-message, the session id from stderr).
STDOUT_LOG="$ART/codex_stdout.log"
exit_code=0

# run_codex runs the pinned `codex exec` invocation. $TIMEOUT_PREFIX is an optional
# leading prefix ("timeout <sec>"): when no timeout binary is available it is empty
# and codex runs directly. It is intentionally left UNQUOTED so it word-splits into
# the `timeout` argv (or vanishes when empty) — hence the SC2086 disables. The
# optional --output-schema flag is injected only when set (bash 3.2-safe — no arrays).
# $EFFORT_FLAG is an analogous optional middle chunk ("-c model_reasoning_effort=<e>"):
# unquoted so it word-splits into the codex argv when set, or vanishes when empty.
#
# stdin is redirected from /dev/null. The prompt is passed POSITIONALLY, but `codex
# exec` also reads stdin when it is not a TTY and will BLOCK ("Reading additional
# input from stdin...") in a non-interactive / background context. </dev/null makes
# stdin an immediate EOF so codex uses only the positional prompt and never hangs.
# (Verified live against codex-cli 0.130 — without it the worker hangs indefinitely.)
run_codex() {
  if [ -n "$OUTPUT_SCHEMA" ]; then
    # shellcheck disable=SC2086
    $TIMEOUT_PREFIX codex exec \
      --cd "$WT" \
      --sandbox "$SANDBOX" \
      --skip-git-repo-check \
      --model "$MODEL" \
      $EFFORT_FLAG \
      --output-schema "$OUTPUT_SCHEMA" \
      --output-last-message "$RESULT_TXT" \
      -c "sandbox_workspace_write.network_access=$NETWORK" \
      "$(cat "$PROMPT_FILE")" </dev/null
  else
    # shellcheck disable=SC2086
    $TIMEOUT_PREFIX codex exec \
      --cd "$WT" \
      --sandbox "$SANDBOX" \
      --skip-git-repo-check \
      --model "$MODEL" \
      $EFFORT_FLAG \
      --output-last-message "$RESULT_TXT" \
      -c "sandbox_workspace_write.network_access=$NETWORK" \
      "$(cat "$PROMPT_FILE")" </dev/null
  fi
}

# Build the timeout prefix (word-split intentionally inside run_codex). Empty when
# no timeout binary is present, in which case codex runs without a wall-clock cap.
TIMEOUT_PREFIX=""
if [ -n "$TIMEOUT_BIN" ]; then
  TIMEOUT_PREFIX="$TIMEOUT_BIN $TIMEOUT_SEC"
fi

# Build the codex reasoning-effort flag (word-split intentionally inside run_codex).
# Empty when --effort was not given, in which case codex uses the model's default
# reasoning effort. The value carries no spaces, so it splits into exactly the two
# argv tokens `-c` and `model_reasoning_effort=<effort>`.
EFFORT_FLAG=""
if [ -n "$EFFORT" ]; then
  EFFORT_FLAG="-c model_reasoning_effort=$EFFORT"
fi

# `set +e` so a non-zero exit (incl. 124 when the timeout fires) is captured rather
# than aborting the script — we must still produce a job_result either way.
set +e
run_codex >"$STDOUT_LOG" 2>"$STDERR_LOG"
exit_code=$?
set -e

# Strip ONLY the cosmetic codex_hooks deprecation line from the captured stderr.
if [ -f "$STDERR_LOG" ]; then
  grep -v 'codex_hooks is deprecated' "$STDERR_LOG" > "$STDERR_LOG.clean" 2>/dev/null || true
  mv -f "$STDERR_LOG.clean" "$STDERR_LOG" 2>/dev/null || true
fi

# --- capture session_id + summary --------------------------------------------
# The session UUID is printed in the run banner. Scan the cleaned stderr (and the
# result text as a fallback) for the first UUID-shaped token. No flag exists to
# request it directly; resume is `codex exec resume <uuid>`.

# ERE (grep -oE) quantifier syntax: bare {n}, not BRE \{n\}.
UUID_RE='[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
session_id=""
if [ -f "$STDERR_LOG" ]; then
  session_id=$(grep -oE "$UUID_RE" "$STDERR_LOG" 2>/dev/null | head -n1 || true)
fi
if [ -z "$session_id" ] && [ -f "$RESULT_TXT" ]; then
  session_id=$(grep -oE "$UUID_RE" "$RESULT_TXT" 2>/dev/null | head -n1 || true)
fi

summary=""
if [ -f "$RESULT_TXT" ]; then
  summary=$(cat "$RESULT_TXT")
fi
[ -n "$summary" ] || summary="(no summary emitted by worker)"

# --- git-derived enforcement -------------------------------------------------
# files_changed = `git diff --name-only` UNION `git ls-files --others --exclude-standard`,
# both inside the worktree. This is the authority for what the job touched — never the
# model's self-report. Exclude the adapter's own scratch files (.job_result.txt etc.).

raw_changed=$(
  { git -C "$WT" diff --name-only 2>/dev/null
    git -C "$WT" ls-files --others --exclude-standard 2>/dev/null
  } | LC_ALL=C sort -u
)

files_changed=""
violations=""
while IFS= read -r path; do
  [ -z "$path" ] && continue
  # Drop the adapter's transient artifacts written into the worktree root.
  case "$path" in
    .job_result.txt|.codex_stderr.log|.codex_stderr.log.clean|.codex_stdout.log) continue ;;
  esac
  if [ -z "$files_changed" ]; then
    files_changed="$path"
  else
    files_changed="$files_changed
$path"
  fi
  if ! path_is_allowed "$path" "$WRITE_ALLOWED"; then
    if [ -z "$violations" ]; then
      violations="$path"
    else
      violations="$violations
$path"
    fi
  fi
done <<EOF
$raw_changed
EOF

# --- derive status -----------------------------------------------------------

blocked="false"
status="success"

if [ -n "$violations" ]; then
  blocked="true"
  status="blocked"
elif [ "$exit_code" = "$TIMEOUT_EXIT_CODE" ]; then
  status="timeout"
elif [ "$exit_code" != "0" ]; then
  status="error"
fi

# --- emit --------------------------------------------------------------------
# stdout = the canonical job_result JSON, and ONLY that. The caller (dispatcher)
# parses this and decides whether to merge (`git -C "$WT" diff HEAD | git apply`)
# or to leave the worktree for inspection on BLOCKED. We do NOT merge here.

emit_job_result \
  "$status" \
  "$blocked" \
  "$files_changed" \
  "$violations" \
  "$summary" \
  "$session_id" \
  "$WT" \
  "$exit_code"

exit 0
