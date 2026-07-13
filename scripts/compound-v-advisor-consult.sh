#!/usr/bin/env bash
#
# compound-v-advisor-consult.sh — Compound V Backend Launcher: the READ-ONLY advisor consult.
#
# Runs ONE cross-brand advisory turn for a cheap executor that hit a hard sub-decision, and
# prints, on stdout, a small JSON object:
#
#   {"advisor_backend": "<b>", "advisor_model": "<m>", "advice": "<text>", "advisor_calls": 1}
#
# The advisor is READ-ONLY by hard contract — it ADVISES, it NEVER writes files or runs
# destructive bash. This is the structural mitigation for the 2026-07-13 repo-deletion incident
# (a live nested bypass agent deleted this repo): a no-write advisor CANNOT cause that class of
# damage regardless of what it is asked to do. The two backend paths are therefore pinned to
# read-only / plan-mode invocations, and NEITHER path ever passes --dangerously-skip-permissions.
#
#   * cross-brand (preferred): codex exec --sandbox read-only --json   (kernel read-only sandbox)
#   * opus fallback:           claude -p --model opus --permission-mode plan --output-format
#                              stream-json --verbose   (plan mode is structurally incapable of
#                              editing; NEVER --dangerously-skip-permissions / --yolo)
#
# The advisor backend is chosen by the deterministic B1 selector
# (compound-v-resolve-model.py --select-advisor), which prefers a DIFFERENT brand than the
# executor (codex > other non-claude > opus fallback). `advisor_calls` is WORKER-COUNTED — this
# one consult == 1 — never read from any CLI usage.iterations[] (that is turn count, not advisor
# count; see docs/superpowers/library-audit/2026-07-13-usage-and-advisor.md).
#
# Contract: skills/backend-launcher/SKILL.md + skills/backend-launcher/adapter-advisor.md
#
# Portability: stock-macOS bash 3.2.57 (indexed arrays OK; NO associative arrays / mapfile /
# ${var,,}) + jq + python3. Absolute paths where they matter. The script writes ONLY ephemeral
# scratch under $TMPDIR to capture the backend's own output — it NEVER writes a repo/deliverable
# file, and stdout carries EXACTLY one JSON object.
#
# Testing: honor $COMPOUND_V_ADVISOR_STUB (a path to a fake backend) so the whole path can be
# proven WITHOUT a live backend run — when set, the stub is invoked in place of the real
# codex/claude binary with the IDENTICAL argv. See scripts/test-advisor-worker-stub.sh.
#
# Usage:
#   compound-v-advisor-consult.sh \
#     --question "<text>" | --question-file <abs-path> \
#     [--context-path <glob>]... \
#     [--executor <backend>] [--available <csv>] [--advisor-backend <b>] \
#     [--cd <dir>] [--timeout-sec <n>] [--calls-log <path>]
#
# --calls-log <path> (optional): on each SUCCESSFUL consult, append exactly ONE compact JSON line
#   (the consult result object) to <path>, creating its parent dir if needed (append, never
#   truncate). This is the per-job advisor log — the dispatcher passes
#   `<run-dir>/logs/<job-id>.advisor.jsonl`, and collect-results COUNTS the lines in that file to
#   DERIVE usage.advisor_calls (honest, git/FS-derived, never model-self-reported). Omitting
#   --calls-log preserves the prior behavior exactly (no logging). See adapter-advisor.md.
#
# Exit: 0 when advice was produced; non-zero (with a diagnostic on stderr) on a usage/environment
# fault or an unsupported advisor backend.

set -euo pipefail

# --- constants ---------------------------------------------------------------
DEFAULT_TIMEOUT_SEC=300
DEFAULT_EXECUTOR="claude"
MAX_OUTPUT_BYTES=4000000

die() {
  echo "compound-v-advisor-consult: $1" >&2
  exit 2
}

# Directory of THIS script (resolves the sibling resolver + timeout supervisor).
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RESOLVE="$SCRIPT_DIR/compound-v-resolve-model.py"
SUPERVISOR="$SCRIPT_DIR/compound-v-run-with-timeout.py"

# --- argument parsing --------------------------------------------------------

QUESTION=""
QUESTION_FILE=""
EXECUTOR="$DEFAULT_EXECUTOR"
AVAILABLE=""
ADVISOR_OVERRIDE=""
CD_DIR="$PWD"
TIMEOUT_SEC="$DEFAULT_TIMEOUT_SEC"
CALLS_LOG=""
# Indexed array of context globs (bash 3.2-safe).
CONTEXT_PATHS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --question)         QUESTION="$2"; shift 2 ;;
    --question-file)    QUESTION_FILE="$2"; shift 2 ;;
    --context-path)     CONTEXT_PATHS+=("$2"); shift 2 ;;
    --executor)         EXECUTOR="$2"; shift 2 ;;
    --available)        AVAILABLE="$2"; shift 2 ;;
    --advisor-backend)  ADVISOR_OVERRIDE="$2"; shift 2 ;;
    --cd)               CD_DIR="$2"; shift 2 ;;
    --timeout-sec)      TIMEOUT_SEC="$2"; shift 2 ;;
    --calls-log)        CALLS_LOG="$2"; shift 2 ;;
    *) die "unknown argument: $1" ;;
  esac
done

# --- validation --------------------------------------------------------------

command -v jq      >/dev/null 2>&1 || die "jq not found on PATH"
command -v python3 >/dev/null 2>&1 || die "python3 not found on PATH"
[ -f "$RESOLVE" ]    || die "resolver not found: $RESOLVE"
[ -f "$SUPERVISOR" ] || die "timeout supervisor not found: $SUPERVISOR"

# Exactly one of --question / --question-file.
if [ -n "$QUESTION" ] && [ -n "$QUESTION_FILE" ]; then
  die "pass only ONE of --question / --question-file"
fi
if [ -n "$QUESTION_FILE" ]; then
  [ -f "$QUESTION_FILE" ] || die "--question-file not found: $QUESTION_FILE"
  QUESTION="$(cat "$QUESTION_FILE")"
fi
[ -n "$QUESTION" ] || die "a question is required (--question or --question-file)"

# --timeout-sec is interpolated into the supervisor argv — pin it to a positive integer.
case "$TIMEOUT_SEC" in
  ''|*[!0-9]*) die "--timeout-sec must be a positive integer: $TIMEOUT_SEC" ;;
esac

[ -d "$CD_DIR" ] || die "--cd is not a directory: $CD_DIR"

# --- pick the advisor backend (B1 selector, or an explicit override) ---------
# The selector prefers a DIFFERENT brand than the executor: codex > other non-claude > opus.
# An explicit --advisor-backend skips the selector but still resolves its concrete deep model.

if [ -n "$ADVISOR_OVERRIDE" ]; then
  ADVISOR_BACKEND="$ADVISOR_OVERRIDE"
  SEL_JSON="$(python3 "$RESOLVE" --backend "$ADVISOR_BACKEND" --tier deep 2>/dev/null)" \
    || die "could not resolve a deep model for advisor backend '$ADVISOR_BACKEND'"
  ADVISOR_MODEL="$(printf '%s' "$SEL_JSON" | jq -r '.model // empty')"
else
  [ -n "$AVAILABLE" ] || die "--available <csv> is required (unless --advisor-backend is given)"
  SEL_JSON="$(python3 "$RESOLVE" --select-advisor --executor "$EXECUTOR" --available "$AVAILABLE" 2>/dev/null)" \
    || die "advisor selector failed (executor='$EXECUTOR' available='$AVAILABLE')"
  ADVISOR_BACKEND="$(printf '%s' "$SEL_JSON" | jq -r '.advisor_backend // empty')"
  ADVISOR_MODEL="$(printf '%s' "$SEL_JSON" | jq -r '.model // empty')"
fi

[ -n "$ADVISOR_BACKEND" ] || die "selector returned no advisor_backend"
[ -n "$ADVISOR_MODEL" ]   || die "selector returned no advisor_model"

# --- build the read-only advisor prompt --------------------------------------
# Question + read-only context (file contents embedded so the advice is grounded WITHOUT relying
# on the backend's own file-access, which stays sandboxed/read-only regardless).

WORK="$(mktemp -d "${TMPDIR:-/tmp}/compound-v-advisor.XXXXXX")" || die "cannot create scratch dir"
trap 'rm -rf "$WORK"' EXIT

PROMPT_FILE="$WORK/prompt.txt"
{
  printf '%s\n' "You are a READ-ONLY ADVISOR consulted on ONE hard sub-decision."
  printf '%s\n' "You ADVISE ONLY: return your recommendation as plain text. You do NOT write files,"
  printf '%s\n\n' "you do NOT run destructive commands, you do NOT take any action."
  printf '%s\n%s\n\n' "QUESTION:" "$QUESTION"
  if [ "${#CONTEXT_PATHS[@]}" -gt 0 ]; then
    printf '%s\n' "READ-ONLY CONTEXT:"
    for _pattern in "${CONTEXT_PATHS[@]}"; do
      # Unquoted glob expansion; a non-matching pattern stays literal and is skipped by -f.
      for _f in $_pattern; do
        [ -f "$_f" ] || continue
        printf -- '--- %s ---\n' "$_f"
        cat "$_f"
        printf '\n'
      done
    done
  fi
} > "$PROMPT_FILE"

PROMPT="$(cat "$PROMPT_FILE")"

# --- run ONE advisory turn, READ-ONLY, under the process-group timeout supervisor -----
# $COMPOUND_V_ADVISOR_STUB (a fake backend path) replaces the real binary with the IDENTICAL
# argv, so the safety flags and the parse path are proven without a live backend run.

RAW_STDOUT="$WORK/stdout.log"
RAW_STDERR="$WORK/stderr.log"
ADVICE_FILE="$WORK/advice.txt"
: > "$ADVICE_FILE"

STUB="${COMPOUND_V_ADVISOR_STUB:-}"

run_supervised() {  # $@ = the full backend command (binary first)
  # </dev/null: belt-and-braces EOF on stdin (the supervisor also sets stdin=DEVNULL), so a
  # backend that reads stdin when it is not a TTY never blocks in this non-interactive context.
  python3 "$SUPERVISOR" \
    --timeout "$TIMEOUT_SEC" --grace 3 \
    --stdout "$RAW_STDOUT" --stderr "$RAW_STDERR" \
    --max-output-bytes "$MAX_OUTPUT_BYTES" \
    -- "$@" </dev/null
}

ADVICE=""
sup_rc=0

case "$ADVISOR_BACKEND" in
  codex)
    # Cross-brand, kernel READ-ONLY sandbox. --json forces a JSONL event stream to stdout, so the
    # advice text is taken from --output-last-message (the same proven pattern the codex worker
    # uses for its summary), NOT from stdout. --skip-git-repo-check: the --cd dir may not be a
    # git root. NO write flags, NO --dangerously-* of any kind.
    if [ -n "$STUB" ]; then BIN="$STUB"; else BIN="codex"; command -v codex >/dev/null 2>&1 || die "codex not found on PATH"; fi
    CMD=( "$BIN" exec
      --sandbox read-only
      --skip-git-repo-check
      --json
      --model "$ADVISOR_MODEL"
      --cd "$CD_DIR"
      --output-last-message "$ADVICE_FILE"
      "$PROMPT" )
    set +e
    run_supervised "${CMD[@]}"
    sup_rc=$?
    set -e
    [ "$sup_rc" = "0" ] || die "advisor backend 'codex' exited non-zero ($sup_rc)"
    ADVICE="$(cat "$ADVICE_FILE" 2>/dev/null || true)"
    ;;

  claude)
    # Opus fallback. --permission-mode plan is the structural no-write guarantee: plan mode CANNOT
    # edit files. --disallowedTools is belt-and-braces defense-in-depth. --output-format
    # stream-json REQUIRES --verbose (library-audit) and yields the advice in the final `result`
    # event's `.result`. NEVER --dangerously-skip-permissions / --yolo / a bypass permission-mode.
    if [ -n "$STUB" ]; then BIN="$STUB"; else BIN="claude"; command -v claude >/dev/null 2>&1 || die "claude not found on PATH"; fi
    CMD=( "$BIN"
      -p
      --model "$ADVISOR_MODEL"
      --permission-mode plan
      --disallowedTools "Write" "Edit" "MultiEdit" "NotebookEdit"
      --output-format stream-json
      --verbose
      "$PROMPT" )
    set +e
    run_supervised "${CMD[@]}"
    sup_rc=$?
    set -e
    [ "$sup_rc" = "0" ] || die "advisor backend 'claude' exited non-zero ($sup_rc)"
    # Parse the LAST stream-json `result` event's `.result` (JSONL; one object per line).
    ADVICE="$(jq -rs 'map(select(type=="object" and .type=="result")) | (last // {}) | .result // empty' "$RAW_STDOUT" 2>/dev/null || true)"
    ;;

  *)
    # B2 supports exactly the two pinned READ-ONLY paths (cross-brand codex + opus fallback). Any
    # other selected backend is refused rather than driven with an unproven/unsafe invocation.
    die "advisor backend '$ADVISOR_BACKEND' is not supported by the consult (B2 supports: codex, claude)"
    ;;
esac

[ -n "$ADVICE" ] || die "advisor backend '$ADVISOR_BACKEND' returned no advice text"

# --- record one line into the per-job advisor log (DERIVED count source) ------
# On a SUCCESSFUL consult, append EXACTLY ONE compact JSON line to --calls-log (when given). The
# dispatcher passes `<run-dir>/logs/<job-id>.advisor.jsonl`; collect-results COUNTS the lines to
# DERIVE usage.advisor_calls — the honest, git/FS-derived count (never model-self-reported). We
# reach here only after ADVICE was produced (a failed consult die()s earlier and never logs).
# Append, never truncate; create the parent dir if needed. Omitting --calls-log => no logging
# (backward compatible). This does NOT alter stdout — stdout stays exactly one JSON object.
if [ -n "$CALLS_LOG" ]; then
  _log_dir="$(dirname "$CALLS_LOG")"
  [ -d "$_log_dir" ] || mkdir -p "$_log_dir" || die "cannot create --calls-log dir: $_log_dir"
  jq -nc \
    --arg advisor_backend "$ADVISOR_BACKEND" \
    --arg advisor_model "$ADVISOR_MODEL" \
    --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --argjson advisor_calls 1 \
    '{advisor_backend: $advisor_backend, advisor_model: $advisor_model, advisor_calls: $advisor_calls, ts: $ts}' \
    >> "$CALLS_LOG" || die "cannot append to --calls-log: $CALLS_LOG"
fi

# --- emit --------------------------------------------------------------------
# advisor_calls on the stdout object is this-consult == 1. The RUN-LEVEL usage.advisor_calls is
# DERIVED by collect-results counting the --calls-log lines, NOT summed from this field.
jq -n \
  --arg advisor_backend "$ADVISOR_BACKEND" \
  --arg advisor_model "$ADVISOR_MODEL" \
  --arg advice "$ADVICE" \
  --argjson advisor_calls 1 \
  '{advisor_backend: $advisor_backend, advisor_model: $advisor_model, advice: $advice, advisor_calls: $advisor_calls}'

exit 0
