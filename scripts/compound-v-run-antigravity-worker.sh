#!/usr/bin/env bash
#
# compound-v-run-antigravity-worker.sh — Compound V Backend Launcher: the headless Antigravity (agy) adapter.
#
# MIRRORS compound-v-run-codex-worker.sh. Runs ONE file-scoped job on a headless
# `agy --print` worker inside a dedicated git worktree, then emits the canonical
# job_result (schemas/job_result.schema.json) on stdout as JSON. The enforcement
# fields (blocked / files_changed / violations) are GIT-DERIVED, never self-reported
# by the model — produced by DELEGATING to the deterministic Python authority
# (scripts/compound-v-scope-check.py), the same gate the dispatcher runs after every
# job. The worker does NOT re-implement glob matching in bash. The model's printed
# stdout response text feeds only `summary`.
#
# Contract: skills/backend-launcher/SKILL.md + skills/backend-launcher/adapter-antigravity.md
#
# !!! SAFETY — LOWER-TRUST BACKEND (read before using) !!!
# Unlike codex (`--sandbox workspace-write` = a kernel-level write-confinement root),
# agy has NO kernel write-confinement. `--dangerously-skip-permissions` (REQUIRED for
# headless writes) lets the agent run arbitrary shell and write OUTSIDE the worktree.
# The worktree + post-hoc `git diff` gate enforces file-scope IN the worktree but
# CANNOT PREVENT an out-of-worktree write or shell side-effect. Antigravity is therefore
# an OPT-IN, LOWER-TRUST backend — prefer Codex (kernel-sandboxed) for untrusted /
# high-stakes work.
#
# Portability: stock-macOS bash 3.2.57 (NO associative arrays / mapfile / ${var,,})
# + jq. shellcheck-clean. Absolute paths throughout. Caller (the dispatcher) owns the
# merge-back decision; this script only OBSERVES and REPORTS — it never merges.
#
# Usage:
#   compound-v-run-antigravity-worker.sh \
#     --run-id <id> --job-id <id> --repo <abs-repo-root> \
#     --prompt-file <abs-path> [--model <model>] \
#     --write-allowed "<glob>[:<glob>...]" \
#     [--timeout-sec <n>] [--network true|false] \
#     [--read-only true|false] [--output-schema <abs-path>]
#
# --model is OPTIONAL: when empty, `--model` is omitted from the agy invocation and
# agy uses its configured default. --output-schema is ACCEPTED for CLI parity with
# the codex worker but IGNORED — agy has no output-schema flag.
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
  echo "compound-v-run-antigravity-worker: $1" >&2
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

[ -n "$RUN_ID" ]        || die "--run-id is required"
[ -n "$JOB_ID" ]        || die "--job-id is required"
[ -n "$REPO" ]          || die "--repo is required"
[ -n "$PROMPT_FILE" ]   || die "--prompt-file is required"
# NOTE: --model is OPTIONAL for antigravity. When empty, --model is omitted from the
# agy invocation and agy uses its configured default model.
# NOTE: --write-allowed may legitimately be EMPTY for a read-only / review job.
# An empty allow-list means NO writes are permitted, so ANY changed path is a
# violation (the scope gate, run with zero allowed globs, blocks everything).

# --timeout-sec is interpolated UNQUOTED into the agy argv (word-split into the
# `timeout` prefix and into agy's --print-timeout), so a crafted value like
# '5; touch /tmp/PWNED' would inject argv. Pin it to a positive integer BEFORE
# it is ever used.
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
# --output-schema is accepted for CLI parity with the codex worker but agy has no
# such flag, so it is IGNORED. We still validate the path shape if one is passed,
# to keep the contract honest (a caller passing a bogus path learns about it).
if [ -n "$OUTPUT_SCHEMA" ]; then
  case "$OUTPUT_SCHEMA" in /*) : ;; *) die "--output-schema must be absolute: $OUTPUT_SCHEMA" ;; esac
  [ -f "$OUTPUT_SCHEMA" ] || die "--output-schema not found: $OUTPUT_SCHEMA"
fi
# --read-only / --network are ACCEPTED for CLI parity with the codex worker but are
# ADVISORY ONLY for antigravity: agy exposes no kernel sandbox toggle for either, so
# they do not change the invocation. (read-only is still enforced post-hoc — the
# git-diff gate BLOCKS any write on an empty-write_allowed review job.) Reference them
# here so the contract is explicit and the parser-set vars are intentionally consumed.
: "advisory (no kernel sandbox in agy): read_only=$READ_ONLY network=$NETWORK"

command -v jq      >/dev/null 2>&1 || die "jq not found on PATH"
command -v git     >/dev/null 2>&1 || die "git not found on PATH"
command -v python3 >/dev/null 2>&1 || die "python3 not found on PATH (scope gate + failure classifier need it)"
command -v agy     >/dev/null 2>&1 || die "agy not found on PATH"

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

# Adapter scratch lives OUTSIDE the worktree, in a sibling dir under $TMPDIR. This
# keeps the worktree PRISTINE: only the job's real output shows up in `git diff`, so
# the generic scope-gate (scripts/compound-v-scope-check.py) agrees with this worker's
# own git-derived enforcement WITHOUT needing any agy-specific ignore list.
ART="$WT.art"
mkdir -p "$ART"

# --- run the headless Antigravity worker -------------------------------------
# VERIFIED live against agy 1.0.13 on stock macOS:
#   cd "$WT" && agy --dangerously-skip-permissions --add-dir "$WT" \
#     --print-timeout "${SEC}s" [--model "$M"] --print "$PROMPT"
# writes files into the worktree, PRINTS the agent's response to STDOUT, exit 0.
#
# Load-bearing facts (do NOT re-derive per run):
#   * FLAG ORDER: `--print` MUST be LAST; its value is the prompt. A flag placed
#     right after `--print` gets eaten as the prompt.
#   * `--dangerously-skip-permissions` is REQUIRED for headless file writes (else
#     agy prompts/auto-denies and writes nothing). See SAFETY banner at the top.
#   * agy has NO `--cd`: we `cd "$WT"` and pass `--add-dir "$WT"`.
#   * Response text → captured STDOUT → job_result.summary.
#   * No resumable session UUID is exposed → session_id is "".
#   * `agy models </dev/null` works headless; the map is resolved upstream (a fallback
#     map, refreshable from the live catalog via /v:models discovery).
#   * READ-ONLY / NETWORK: agy exposes no kernel sandbox toggle for these here, so
#     --read-only and --network are advisory only and do not change the invocation
#     (the post-hoc git-diff gate still BLOCKS any write on a read-only job).

STDERR_LOG="$ART/agy_stderr.log"
STDOUT_LOG="$ART/agy_stdout.log"
exit_code=0

# run_agy runs the pinned `agy` invocation. $TIMEOUT_PREFIX is an optional leading
# prefix ("timeout <sec>"): when no timeout binary is available it is empty and agy
# runs directly. It is intentionally left UNQUOTED so it word-splits into the
# `timeout` argv (or vanishes when empty) — hence the SC2086 disables. The optional
# --model flag is injected only when set (bash 3.2-safe — no arrays). `--print` is
# ALWAYS LAST, immediately followed by the prompt value.
run_agy() {
  cd "$WT" || return 2
  if [ -n "$MODEL" ]; then
    # shellcheck disable=SC2086
    $TIMEOUT_PREFIX agy \
      --dangerously-skip-permissions \
      --add-dir "$WT" \
      --print-timeout "${TIMEOUT_SEC}s" \
      --model "$MODEL" \
      --print "$(cat "$PROMPT_FILE")" </dev/null
  else
    # shellcheck disable=SC2086
    $TIMEOUT_PREFIX agy \
      --dangerously-skip-permissions \
      --add-dir "$WT" \
      --print-timeout "${TIMEOUT_SEC}s" \
      --print "$(cat "$PROMPT_FILE")" </dev/null
  fi
}

# Build the timeout prefix (word-split intentionally inside run_agy). Empty when no
# timeout binary is present, in which case agy relies on its own --print-timeout
# (which we always pass) for the wall-clock cap.
TIMEOUT_PREFIX=""
if [ -n "$TIMEOUT_BIN" ]; then
  TIMEOUT_PREFIX="$TIMEOUT_BIN $TIMEOUT_SEC"
fi

# `set +e` so a non-zero exit (incl. 124 when the timeout fires) is captured rather
# than aborting the script — we must still produce a job_result either way.
set +e
run_agy >"$STDOUT_LOG" 2>"$STDERR_LOG"
exit_code=$?
set -e

# --- capture session_id + summary --------------------------------------------
# agy exposes no resumable session UUID → session_id is always "". The agent's
# printed response is on stdout (captured to $STDOUT_LOG) → feeds the human summary.
session_id=""

summary=""
if [ -f "$STDOUT_LOG" ]; then
  summary=$(cat "$STDOUT_LOG")
fi
[ -n "$summary" ] || summary="(no summary emitted by worker)"

# --- git-derived enforcement (delegated to the Python scope gate) ------------
# The authoritative enforcement (files_changed / violations / blocked) comes from
# scripts/compound-v-scope-check.py — the SAME deterministic gate the dispatcher
# runs after every job. The worker does NOT re-implement glob matching in bash.
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
# fault (rc 2 or unparseable) is an error; agy timeout (124) is a timeout; any
# other non-zero agy exit is an error; otherwise success.

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
# the captured agy stderr — see compound-v-classify-failure.py + -failure-policy.py.
# "" => null in the emitted JSON.
failure_class=""
retry_after="0"
# Classify on ANY non-zero agy exit — including a job that is also scope-BLOCKED — so an
# out_of_credits/auth failure still records a class the dispatcher can use to open a circuit
# (a blocked job whose agy exited 0 stays failure_class:null, correctly).
if [ "$status" = "error" ] || [ "$status" = "timeout" ] || [ "$exit_code" != "0" ]; then
  # A GATE/enforcement fault (gate_rc neither 0 nor 1) is an ENVIRONMENT fault, not a
  # backend failure — classify it generically, NEVER via the agy exit code (which may
  # be 0 on a clean agy run whose scope GATE then faulted).
  if [ "$gate_rc" != "0" ] && [ "$gate_rc" != "1" ]; then
    failure_class="other"
  else
    _cls_json=$(python3 "$SCRIPT_DIR/compound-v-classify-failure.py" \
      --backend antigravity --exit-code "$exit_code" --stderr-file "$STDERR_LOG" 2>/dev/null || true)
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
# parses this and decides whether to merge (index-based patch including new files)
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
