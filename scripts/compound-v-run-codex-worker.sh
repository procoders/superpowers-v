#!/usr/bin/env bash
#
# compound-v-run-codex-worker.sh — Compound V Backend Launcher: the headless Codex adapter.
#
# Runs ONE file-scoped job on a headless `codex exec` worker inside a dedicated git
# worktree, then emits the canonical job_result (schemas/job_result.schema.json) on
# stdout as JSON. The enforcement fields (blocked / files_changed / violations) are
# GIT-DERIVED, never self-reported by the model — and they are produced by DELEGATING
# to the deterministic Python authority (scripts/compound-v-scope-check.py), the same
# gate the dispatcher runs after every job. The worker does NOT re-implement glob
# matching in bash (a weaker case-glob matcher would diverge from the Python gate and
# miss gitignored writes). The model's --output-last-message text feeds only `summary`.
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
# each glob matched repo-relative against the changed paths. An EMPTY
# --write-allowed is valid (read-only / review job): no writes are permitted, so
# ANY changed path is a violation and the job is BLOCKED.
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
# field is correctly typed and escaped. files_changed / violations arrive as JSON
# ARRAYS (straight from the gate's NUL-correct output) and pass through untouched —
# no newline round-trip, so a path containing a newline stays ONE element.
emit_job_result() {
  # $1 status  $2 blocked(true|false)  $3 files_json (JSON array)  $4 violations_json (JSON array)
  # $5 summary  $6 session_id  $7 worktree  $8 exit_code(int)  $9 failure_class ("" => null)
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

# Validate an id (run_id / job_id) against a strict safe-character allow-list.
# These ids become PATH SEGMENTS under $TMPROOT/compound-v/, so a `../` or any
# separator could escape the tree and let the cleanup `rm -rf` delete arbitrary
# dirs. Allow only [A-Za-z0-9._-]; reject `.` and `..`; reject empty. Returns 0
# when safe, 1 otherwise. bash 3.2-safe (case glob, no regex/associative arrays).
id_is_safe() {
  _id="$1"
  [ -n "$_id" ] || return 1
  case "$_id" in
    .|..) return 1 ;;
    *[!A-Za-z0-9._-]*) return 1 ;;
  esac
  return 0
}

# Directory of THIS script (resolves the sibling Python scope gate authority).
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
# NOTE: --write-allowed may legitimately be EMPTY for a read-only / review job.
# An empty allow-list means NO writes are permitted, so ANY changed path is a
# violation (the scope gate, run with zero allowed globs, blocks everything).

# --timeout-sec is interpolated UNQUOTED into the codex argv (word-split into the
# `timeout` prefix), so a crafted value like '5; touch /tmp/PWNED' would inject
# argv. Pin it to a positive integer BEFORE it is ever used.
case "$TIMEOUT_SEC" in
  ''|*[!0-9]*) die "--timeout-sec must be a positive integer: $TIMEOUT_SEC" ;;
esac

# Path-traversal guard: run_id / job_id become path segments under $TMPROOT, and
# the stale-worktree cleanup does `rm -rf` on that path. A `../` (or any path
# separator) in an id would escape the tree and delete arbitrary dirs. Validate
# BEFORE building any path or touching the filesystem.
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
if [ -n "$EFFORT" ]; then
  case "$EFFORT" in
    low|medium|high) : ;;
    *) die "--effort must be one of low|medium|high: $EFFORT" ;;
  esac
fi
command -v jq      >/dev/null 2>&1 || die "jq not found on PATH"
command -v git     >/dev/null 2>&1 || die "git not found on PATH"
command -v python3 >/dev/null 2>&1 || die "python3 not found on PATH (scope gate + failure classifier need it)"
command -v codex   >/dev/null 2>&1 || die "codex not found on PATH"

# Wall-clock cap: run codex under the shared PROCESS-GROUP timeout supervisor
# (scripts/compound-v-run-with-timeout.py) — on expiry it killpg's the whole codex process tree
# (not just the direct child) and returns 124. No external `timeout`/`gtimeout` binary needed.
SUPERVISOR="$SCRIPT_DIR/compound-v-run-with-timeout.py"
[ -f "$SUPERVISOR" ] || die "timeout supervisor not found: $SUPERVISOR"

# --- worktree lifecycle ------------------------------------------------------
# Worktrees live OUTSIDE the repo, under $TMPDIR, so no .gitignore change is needed.

TMPROOT="${TMPDIR:-/tmp}"
TMPROOT="${TMPROOT%/}"
# Require an ABSOLUTE tmp root: a relative $TMPDIR would resolve the worktree against the
# caller's cwd (possibly INSIDE the repo), defeating isolation and the scope diff.
case "$TMPROOT" in
  /*) : ;;
  *) die "TMPDIR must be an absolute path (got: $TMPROOT)" ;;
esac
# Canonicalize the tmp root up front (resolve the /var → /private/var class of symlink) and
# build the parent from the REAL path, so no symlinked component can redirect the worktree.
TMPROOT_REAL="$(cd "$TMPROOT" 2>/dev/null && pwd -P)" || die "TMPDIR does not exist: $TMPROOT"
WT_PARENT="$TMPROOT_REAL/compound-v"
# Reject a pre-planted symlink at the parent (it could redirect writes/cleanup out of tmp).
# We keep the DETERMINISTIC $RUN_ID/$JOB_ID path (not a random `mktemp -d`) on purpose:
# idempotent re-dispatch + cleanup on resume locate the worktree by exactly that path.
[ -L "$WT_PARENT" ] && die "refusing: worktree parent is a symlink: $WT_PARENT"
WT="$WT_PARENT/$RUN_ID/$JOB_ID"

# Defence-in-depth: even with the id-character guard above, ASSERT WT sits
# strictly under $TMPROOT/compound-v/ before any remove/rm. The destructive
# `rm -rf` fallback only runs after this assertion holds — so a path that
# somehow escaped can never be deleted.
#
# CANONICALIZE BOTH SIDES identically before comparing: on macOS $TMPDIR is
# `/var/folders/...` while `pwd -P` resolves it to `/private/var/folders/...`
# (the /var → /private/var symlink). Comparing a canonical parent against a raw
# $WT prefix would FALSELY reject every valid run. So we canonicalize the parent
# of $WT and compare it against the canonical $WT_PARENT. The real defense is the
# id-character regex above (no `/`, no `..` ⇒ no traversal); this is belt-and-braces.
mkdir -p "$(dirname "$WT")"
WT_PARENT_REAL="$(cd "$WT_PARENT" && pwd -P)"
WT_DIR_REAL="$(cd "$(dirname "$WT")" && pwd -P)"
case "$WT_DIR_REAL/" in
  "$WT_PARENT_REAL"/*/) : ;;
  *) die "refusing to operate on worktree path outside $WT_PARENT_REAL: $WT" ;;
esac
# ...and assert the worktree is NOT inside the repo — a worktree under the repo would make
# the `git diff` scope enforcement meaningless.
REPO_REAL="$(cd "$REPO" && pwd -P)"
case "$WT_DIR_REAL/" in
  "$REPO_REAL"/*) die "refusing: worktree path is inside the repo: $WT" ;;
esac

# Clean any stale worktree at this path (idempotent re-dispatch on resume). Safe
# now that WT is proven to live under $WT_PARENT_REAL.
if [ -e "$WT" ]; then
  git -C "$REPO" worktree remove -f "$WT" >/dev/null 2>&1 || rm -rf "$WT"
fi

# Capture the BASELINE commit BEFORE `git worktree add` — the worktree is created
# from HEAD, so this SHA is exactly the worktree's diff baseline. We pass this
# pinned SHA (not the literal "HEAD") to the scope gate: if the executor COMMITS
# inside its worktree, the working tree looks clean and a `git diff HEAD` would
# see nothing — but `git diff <baseline-sha>` still includes the committed change,
# so a commit-to-hide-changes attempt is still detected and BLOCKED.
BASELINE_SHA="$(git -C "$REPO" rev-parse HEAD 2>/dev/null)" \
  || die "could not resolve baseline HEAD in $REPO"
[ -n "$BASELINE_SHA" ] || die "empty baseline HEAD in $REPO"

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

# run_codex runs the pinned `codex exec` invocation UNDER the process-group timeout supervisor
# (`python3 "$SUPERVISOR" --timeout <sec> -- codex exec …`): on expiry it killpg's the whole
# codex tree (not just the direct child) and returns 124. The supervisor path is QUOTED (no
# word-split, so a spaced repo path is safe). The optional --output-schema branch is chosen when
# set (bash 3.2-safe — no arrays).
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
    python3 "$SUPERVISOR" --timeout "$TIMEOUT_SEC" --grace 3 -- codex exec \
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
    python3 "$SUPERVISOR" --timeout "$TIMEOUT_SEC" --grace 3 -- codex exec \
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

# --- git-derived enforcement (delegated to the Python scope gate) ------------
# The authoritative enforcement (files_changed / violations / blocked) comes from
# scripts/compound-v-scope-check.py — the SAME deterministic gate the dispatcher
# runs after every job. The worker no longer re-implements glob matching in bash
# (a weaker `case`-glob matcher would DIVERGE from the Python authority, e.g. bash
# `*` matches `/`, and it could not see gitignored writes). Single source of truth.
#
# write_allowed is a colon-separated glob list; the gate wants one glob per line,
# so we expand it into an allow-file under $ART (outside the worktree → never seen
# in the diff). An EMPTY --write-allowed (read-only / review job) yields an EMPTY
# allow-file, which makes the gate treat EVERY changed path as a violation — a
# review job that writes anything is correctly BLOCKED. Baseline = the pinned SHA
# captured before `worktree add` (so an in-worktree commit is still diffed).

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

# Run the gate. It prints a JSON verdict on stdout; exit 0 = pass, 1 = blocked,
# 2 = usage/git error. Capture both so a gate fault becomes status: error rather
# than a silently-clean result.
GATE_JSON=""
gate_rc=0
set +e
GATE_JSON=$(python3 "$SCRIPT_DIR/compound-v-scope-check.py" \
  --worktree "$WT" --baseline "$BASELINE_SHA" --allow-file "$ALLOW_FILE" 2>"$ART/scope_check.err")
gate_rc=$?
set -e

# Parse the gate verdict with jq (the gate's `changed`/`violations` arrays are the
# authority). On a gate error (rc 2 / unparseable) treat enforcement as empty and
# let the status logic below mark it an error.
files_json="[]"
violations_json="[]"
viol_count=0
gate_verdict=""
if [ -n "$GATE_JSON" ] && printf '%s' "$GATE_JSON" | jq -e . >/dev/null 2>&1; then
  gate_verdict=$(printf '%s' "$GATE_JSON" | jq -r '.verdict // ""')
  # Pass the gate's arrays through as JSON (the gate is NUL-correct) — no newline
  # round-trip, so a filename containing a newline survives as a single element.
  files_json=$(printf '%s' "$GATE_JSON" | jq -c '.changed // []')
  violations_json=$(printf '%s' "$GATE_JSON" | jq -c '.violations // []')
  viol_count=$(printf '%s' "$GATE_JSON" | jq '(.violations // []) | length')
fi

# --- derive status -----------------------------------------------------------
# The gate's verdict decides blocked; the worker's exit code layers timeout/error
# on top. A blocked verdict ALWAYS wins (a scope leak is terminal). Then: a gate
# fault (rc 2 or unparseable) is an error; codex timeout (124) is a timeout; any
# other non-zero codex exit is an error; otherwise success.

blocked="false"
status="success"

if [ "$gate_verdict" = "blocked" ] || [ "$viol_count" -gt 0 ]; then
  blocked="true"
  status="blocked"
elif [ "$gate_rc" != "0" ] && [ "$gate_rc" != "1" ]; then
  # Gate could not produce a verdict (usage/git error) — fail closed as error.
  status="error"
elif [ "$exit_code" = "$TIMEOUT_EXIT_CODE" ]; then
  status="timeout"
elif [ "$exit_code" != "0" ]; then
  status="error"
fi

# --- classify a backend failure ----------------------------------------------
# A non-success / non-blocked status carries a failure_class (out_of_credits /
# rate_limited / overloaded / auth / context_length / timeout / network / other) that
# drives the dispatcher's deterministic retry/reroute/halt policy. The classifier reads
# the captured codex stderr — see compound-v-classify-failure.py + -failure-policy.py.
# "" => null in the emitted JSON.
failure_class=""
retry_after="0"
# Classify on ANY non-zero codex exit — including a job that is also scope-BLOCKED — so an
# out_of_credits/auth failure still records a class the dispatcher can use to open a circuit
# (a blocked job whose codex exited 0 stays failure_class:null, correctly).
if [ "$status" = "error" ] || [ "$status" = "timeout" ] || [ "$exit_code" != "0" ]; then
  # A GATE/enforcement fault (gate_rc neither 0 nor 1) is an ENVIRONMENT fault, not a
  # backend failure — classify it generically, NEVER via the codex exit code (which may
  # be 0 on a clean codex run whose scope GATE then faulted).
  if [ "$gate_rc" != "0" ] && [ "$gate_rc" != "1" ]; then
    failure_class="other"
  else
    _cls_json=$(python3 "$SCRIPT_DIR/compound-v-classify-failure.py" \
      --backend codex --exit-code "$exit_code" --stderr-file "$STDERR_LOG" 2>/dev/null || true)
    failure_class=$(printf '%s' "$_cls_json" | jq -r '.failure_class' 2>/dev/null || true)
    retry_after=$(printf '%s' "$_cls_json" | jq -r '.retry_after // 0' 2>/dev/null || echo 0)
  fi
  # FAIL CLOSED: an error/timeout status must NEVER carry failure_class none/empty — the
  # policy maps `none` to `proceed`, which would let an enforcement failure continue as if
  # it had succeeded. Force any none/empty/null to a real (retry-once-then-halt) class.
  case "$failure_class" in
    ""|null|none) failure_class="other" ;;
  esac
  case "$retry_after" in
    ''|*[!0-9]*) retry_after="0" ;;
  esac
fi

# --- emit --------------------------------------------------------------------
# stdout = the canonical job_result JSON, and ONLY that. The caller (dispatcher)
# parses this and decides whether to merge (index-based patch including new files:
# `git -C "$WT" add -A && git -C "$WT" diff --cached --binary HEAD | git apply --index`)
# or to leave the worktree for inspection on BLOCKED. We do NOT merge here.

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
