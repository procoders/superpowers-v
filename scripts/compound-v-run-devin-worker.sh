#!/usr/bin/env bash
#
# compound-v-run-devin-worker.sh — Compound V Backend Launcher: the headless Devin (`devin -p`) adapter.
#
# MIRRORS compound-v-run-antigravity-worker.sh (which mirrors the codex worker). Runs ONE
# file-scoped job on a headless `devin -p` worker inside a dedicated git worktree, then emits
# the canonical job_result (schemas/job_result.schema.json) on stdout as JSON. The enforcement
# fields (blocked / files_changed / violations) are GIT-DERIVED, never self-reported by the
# model — produced by DELEGATING to the deterministic Python authority
# (scripts/compound-v-scope-check.py), the same gate the dispatcher runs after every job. The
# worker does NOT re-implement glob matching in bash. Devin's printed stdout response feeds
# only `summary` (Devin has no `--output-last-message`/`--json` structured envelope).
#
# Contract: skills/backend-launcher/SKILL.md + skills/backend-launcher/adapter-devin.md
#
# !!! AUTH-PENDING — READ BEFORE TRUSTING THIS SCRIPT'S OUTPUT SEMANTICS !!!
# This script was built and syntax/logic-verified WITHOUT an authenticated Cognition account
# (no `devin auth login` / `COGNITION_API_KEY` available on the build host). Two things are
# explicitly DOC-CLAIMED / UNVERIFIED, not proven by a live run, and are marked TODO below:
#   1. session_id — Devin exposes real resume (`-r/--resume <SESSION_ID>`), and the best
#      VERIFIED-live candidate to capture an id is `devin list --format json` run in the
#      worktree after the job, but the exact field name/timing is UNVERIFIED without a real
#      account. This worker does NOT attempt that parse — session_id is always emitted "".
#   2. failure classification — no real Devin failure text (expired key, rate limit, ACU
#      exhaustion) exists to build a `_DEVIN_RULES` table in compound-v-classify-failure.py
#      (whose --backend flag does not even list "devin" yet). This worker does a BEST-EFFORT
#      exit-code + empty-stdout heuristic only, and fails closed to failure_class: "other" on
#      any non-zero-exit / empty-output outcome — exactly the interim rule adapter-devin.md
#      documents. Re-verify both against a real account before promoting either to pinned.
#
# !!! SAFETY — LOWER-TRUST BACKEND (read before using) !!!
# Devin HAS a real kernel-sandbox flag (`--sandbox`, Research Preview) but its coverage of
# Devin's own (non-shell) file-edit tool calls, and its network-filtering, are both
# UNVERIFIED/self-described-unstable by Cognition — see adapter-devin.md SAFETY. This worker
# does NOT pass `--sandbox`; `--permission-mode dangerous` (REQUIRED for unattended writes)
# removes Devin's own approval rail entirely. The worktree + post-hoc `git diff` gate is
# therefore the ONLY enforcement this adapter relies on — same opt-in, lower-trust tier as
# Antigravity/Cursor. Prefer Codex (kernel-sandboxed) for untrusted / high-stakes work.
#
# Portability: stock-macOS bash 3.2.57 (NO associative arrays / mapfile / ${var,,})
# + jq. shellcheck-clean. Absolute paths throughout. Caller (the dispatcher) owns the
# merge-back decision; this script only OBSERVES and REPORTS — it never merges.
#
# Usage:
#   compound-v-run-devin-worker.sh \
#     --run-id <id> --job-id <id> --repo <abs-repo-root> \
#     --prompt-file <abs-path> [--model <model>] \
#     --write-allowed "<glob>[:<glob>...]" \
#     [--timeout-sec <n>] [--network true|false] \
#     [--read-only true|false] [--output-schema <abs-path>]
#
# --model is OPTIONAL: when empty, `--model` is omitted from the devin invocation and devin
# uses its configured default. --output-schema is ACCEPTED for CLI parity with the codex
# worker but IGNORED — devin has no output-schema flag. --network is advisory only (Devin's
# sandbox network-filtering is explicitly "currently unstable" per Cognition's own docs).
# --read-only is ADVISORY: enforced POST-HOC by the gate (empty --write-allowed => any write
# BLOCKS), same as every lower-trust adapter — devin has no propose-only headless mode.
#
# All file paths MUST be absolute. write_allowed is a colon-separated glob list, each glob
# matched repo-relative against the changed paths. An EMPTY --write-allowed (read-only /
# review job) means no writes are permitted, so ANY changed path is a violation => BLOCKED.
#
# Exit code: 0 when the job_result was produced (even for a BLOCKED/timeout/error job — those
# are reported IN job_result.status). Non-zero only on a usage / environment fault.

set -euo pipefail

# --- constants ---------------------------------------------------------------
TIMEOUT_EXIT_CODE=124          # GNU/BSD `timeout` convention when the limit fires
DEFAULT_TIMEOUT_SEC=900
DEFAULT_NETWORK=false
DEFAULT_READ_ONLY=false
# Bound Devin's captured stdout/stderr on disk (compound-v-run-with-timeout.py's own
# --max-output-bytes: a bounded, drain-and-discard pump so a runaway/looping worker can
# never fill the disk or block on a full pipe — see that script's docstring).
MAX_OUTPUT_BYTES=5000000

# --- helpers -----------------------------------------------------------------

die() {
  # Environment/usage fault: no job_result could be produced.
  echo "compound-v-run-devin-worker: $1" >&2
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

[ -n "$RUN_ID" ]      || die "--run-id is required"
[ -n "$JOB_ID" ]      || die "--job-id is required"
[ -n "$REPO" ]        || die "--repo is required"
[ -n "$PROMPT_FILE" ] || die "--prompt-file is required"
# NOTE: --model is OPTIONAL for devin. When empty, --model is omitted from the devin
# invocation and devin uses its configured default.
# NOTE: --write-allowed may legitimately be EMPTY for a read-only / review job.
# An empty allow-list means NO writes are permitted, so ANY changed path is a
# violation (the scope gate, run with zero allowed globs, blocks everything).

# --timeout-sec is interpolated into the supervisor invocation; pin it to a positive
# integer BEFORE it is ever used (defence against argv/arithmetic injection).
case "$TIMEOUT_SEC" in
  ''|*[!0-9]*) die "--timeout-sec must be a positive integer: $TIMEOUT_SEC" ;;
esac
[ "$TIMEOUT_SEC" -gt 0 ] || die "--timeout-sec must be > 0 (got $TIMEOUT_SEC): a 0 cap would kill the job instantly"

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
# --output-schema is accepted for CLI parity with the codex worker but devin has no
# such flag, so it is IGNORED. We still validate the path shape if one is passed,
# to keep the contract honest (a caller passing a bogus path learns about it).
if [ -n "$OUTPUT_SCHEMA" ]; then
  case "$OUTPUT_SCHEMA" in /*) : ;; *) die "--output-schema must be absolute: $OUTPUT_SCHEMA" ;; esac
  [ -f "$OUTPUT_SCHEMA" ] || die "--output-schema not found: $OUTPUT_SCHEMA"
fi
# --read-only / --network are ACCEPTED for CLI parity with the codex worker but are
# ADVISORY ONLY for devin: --sandbox (Research Preview) is not relied on for enforcement
# here (see SAFETY), so neither flag changes the invocation. Reference them here so the
# contract is explicit and the parser-set vars are intentionally consumed.
: "advisory (devin --sandbox not relied on for enforcement): read_only=$READ_ONLY network=$NETWORK"

command -v jq      >/dev/null 2>&1 || die "jq not found on PATH"
command -v git     >/dev/null 2>&1 || die "git not found on PATH"
command -v python3 >/dev/null 2>&1 || die "python3 not found on PATH (scope gate needs it)"
command -v devin   >/dev/null 2>&1 || die "devin not found on PATH"

# Wall-clock cap: run devin under the shared PROCESS-GROUP timeout supervisor
# (scripts/compound-v-run-with-timeout.py) — devin has NO built-in --timeout flag
# (verified live absence). On expiry the supervisor killpg's the whole devin process
# tree (not just the direct child) and returns 124. No external timeout/gtimeout needed.
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

# Adapter scratch lives OUTSIDE the worktree, in a sibling dir under $TMPDIR. This
# keeps the worktree PRISTINE: only the job's real output shows up in `git diff`, so
# the generic scope-gate (scripts/compound-v-scope-check.py) agrees with this worker's
# own git-derived enforcement WITHOUT needing any devin-specific ignore list.
#
# NOTE on the job_result capture path: adapter-devin.md's draft invocation informally
# says "capture to $WT/.job_result.txt", but writing it INSIDE the worktree would make
# it show up as an untracked file in the scope gate's own `git ls-files --others` scan
# — a false BLOCKED verdict on every single job. We deliberately place it in $ART
# (a sibling of $WT, never diffed) instead, exactly like the codex/antigravity/cursor
# workers' own `$ART/job_result.txt` convention.
ART="$WT.art"
mkdir -p "$ART"

# --- run the headless Devin worker --------------------------------------------
# Pinned invocation (devin-cli 3000.1.27 — auth-free flags VERIFIED live, task-execution
# behavior DOC-CLAIMED per adapter-devin.md):
#   cd "$WT" && devin -p "$PROMPT" --permission-mode dangerous [--model "$MODEL"] </dev/null
#
# Load-bearing facts (adapter-devin.md):
#   * `-p, --print` = non-interactive; runs, prints the final response to stdout, exits.
#   * `--permission-mode dangerous` is REQUIRED for unattended writes (default `auto` only
#     auto-approves READ-only tools and would stall forever waiting for approval).
#   * `</dev/null` is REQUIRED — an unauthenticated run attempted an interactive login
#     prompt and only failed cleanly because stdin was closed (verified live).
#   * No `--cd`/`--cwd` flag exists — the supervisor's own `--cwd "$WT"` takes its place.
#   * No `--json`/`--output-format json` — stdout IS the final response text; captured
#     via the supervisor's `--stdout` straight into $ART/job_result.txt (bounded by
#     --max-output-bytes so a runaway worker can't fill the disk).
#   * `--model` is OPTIONAL — omitted when empty, letting devin use its configured default.
#   * `--export` is DELIBERATELY NOT PASSED: it writes an ATIF conversation trace with
#     no size cap of its own, outside `--max-output-bytes` (which only bounds the
#     supervisor's own --stdout/--stderr captures) — an unbounded write a lower-trust
#     worker fully controls the size of. This worker does not parse `--export`'s output
#     either (session-id shape is auth-pending; see header), so there is no current
#     consumer to justify the unbounded write. TODO(follow-on): reintroduce `--export`
#     once (a) its output is actually parsed for session_id and (b) it is routed
#     through a bounded capture (or devin ships its own size cap).

RESULT_TXT="$ART/job_result.txt"
STDERR_LOG="$ART/devin_stderr.log"
exit_code=0

# run_devin runs the pinned `devin -p` invocation UNDER the process-group timeout
# supervisor: on expiry it killpg's the whole devin tree (not just the direct child) and
# returns 124. --stdout/--stderr are BOUNDED capture files (--max-output-bytes) so a
# runaway/looping worker can never fill the disk or block on a full pipe. `--cwd "$WT"`
# stands in for devin's missing `--cd` flag. The trailing `</dev/null` closes the
# supervisor's OWN stdin (belt-and-braces; the supervisor already launches devin with
# stdin=DEVNULL internally) — same hard-won-lesson discipline as every other worker.
run_devin() {
  if [ -n "$MODEL" ]; then
    python3 "$SUPERVISOR" --timeout "$TIMEOUT_SEC" --grace 3 --cwd "$WT" \
      --stdout "$RESULT_TXT" --stderr "$STDERR_LOG" --max-output-bytes "$MAX_OUTPUT_BYTES" \
      -- devin -p "$(cat "$PROMPT_FILE")" \
      --permission-mode dangerous \
      --model "$MODEL" </dev/null
  else
    python3 "$SUPERVISOR" --timeout "$TIMEOUT_SEC" --grace 3 --cwd "$WT" \
      --stdout "$RESULT_TXT" --stderr "$STDERR_LOG" --max-output-bytes "$MAX_OUTPUT_BYTES" \
      -- devin -p "$(cat "$PROMPT_FILE")" \
      --permission-mode dangerous </dev/null
  fi
}

# `set +e` so a non-zero exit (incl. 124 when the timeout fires) is captured rather
# than aborting the script — we must still produce a job_result either way.
set +e
run_devin
exit_code=$?
set -e

# --- capture session_id + summary --------------------------------------------
# session_id: AUTH-PENDING — see header comment. No authenticated account was available to
# verify `devin list --format json`'s field shape or timing, so this worker does NOT
# attempt that parse (a wrong/guessed field name would be worse than an honest "unknown").
# Always emitted "" — meaning "resume fresh" to the dispatcher, exactly like every other
# backend's degrade-safe empty-session-id case.
session_id=""

summary=""
if [ -f "$RESULT_TXT" ]; then
  summary=$(cat "$RESULT_TXT")
fi
# Best-effort AUTH-PENDING failure signal (task requirement, no real classifier exists
# yet — see header): a clean exit (0) with COMPLETELY EMPTY stdout is treated as a
# probable silent failure (e.g. an unauthenticated run failing before producing output)
# rather than reported as a false "success". Computed BEFORE the human-readable
# "(no summary...)" placeholder is substituted in, so it reflects what devin ACTUALLY
# emitted, not the placeholder text.
_summary_is_empty="false"
if [ -z "$(printf '%s' "$summary" | tr -d '[:space:]')" ]; then
  _summary_is_empty="true"
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
# `set -f` (noglob) around the unquoted split below: WRITE_ALLOWED entries are LITERAL
# glob patterns destined for the scope gate's own matcher, not shell globs to be
# expanded HERE. With globbing left on, a glob-char-bearing entry could expand against
# files in the launcher's cwd and silently corrupt the allow-list before the gate ever
# sees it — `set -f` makes the unquoted `for _glob in $WRITE_ALLOWED` split on IFS=":"
# only, never pathname-expand the results.
set -f
for _glob in $WRITE_ALLOWED; do
  IFS="$_OLDIFS"
  [ -z "$_glob" ] && continue
  printf '%s\n' "$_glob" >> "$ALLOW_FILE"
done
set +f
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
# fault (rc 2 or unparseable) is an error; devin timeout (124) is a timeout; any
# other non-zero devin exit is an error; a clean-exit-but-empty-stdout is a
# best-effort AUTH-PENDING error signal (see above); otherwise success.

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
elif [ "$_summary_is_empty" = "true" ]; then
  status="error"
fi

# --- classify a backend failure (AUTH-PENDING best-effort — see header) -----
# A non-success / non-blocked status carries a failure_class (out_of_credits /
# rate_limited / overloaded / auth / context_length / timeout / network / other) that
# drives the dispatcher's deterministic retry/reroute/halt policy. NO _DEVIN_RULES
# table exists yet in compound-v-classify-failure.py (its --backend flag does not even
# list "devin" — an unregistered backend is a CLI usage error, not a graceful fallback),
# because no authenticated failure sample was available to build real substring
# signatures. We deliberately do NOT call that script with a fabricated backend name —
# fail CLOSED to "other" directly, exactly the interim rule adapter-devin.md documents.
# TODO: once a live Cognition account can capture real failure text, add a _DEVIN_RULES
# table to compound-v-classify-failure.py and route through it like every other backend.
failure_class=""
retry_after="0"
if [ "$status" = "error" ] || [ "$status" = "timeout" ] || [ "$exit_code" != "0" ]; then
  failure_class="other"
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
