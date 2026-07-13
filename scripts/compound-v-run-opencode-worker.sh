#!/usr/bin/env bash
#
# compound-v-run-opencode-worker.sh — Compound V Backend Launcher: the headless opencode
# (`opencode run`) adapter.
#
# MIRRORS compound-v-run-antigravity-worker.sh / -cursor-worker.sh (which mirror the codex
# worker). Runs ONE file-scoped job on a headless `opencode run` worker inside a dedicated
# git worktree, then emits the canonical job_result (schemas/job_result.schema.json) on
# stdout as JSON. The enforcement fields (blocked / files_changed / violations) are
# GIT-DERIVED, never self-reported by the model — produced by DELEGATING to the
# deterministic Python authority (scripts/compound-v-scope-check.py), the same gate the
# dispatcher runs after every job. The worker does NOT re-implement glob matching in bash.
#
# Contract: skills/backend-launcher/SKILL.md + skills/backend-launcher/adapter-opencode.md
#
# !!! CRITICAL SECURITY — MANDATORY provider-credential scrub (read first) !!!
# adapter-opencode.md documents a LIVE-OBSERVED finding: opencode successfully
# authenticated and completed a real request with ZERO stored credentials
# (`opencode providers list` → 0 credentials), purely by inheriting an ambient
# `ANTHROPIC_BASE_URL` from the parent shell. If this worker blindly inherited the
# DISPATCHER's own environment, a job could silently run AS the orchestrator's own
# provider credentials — an unintended privilege leak from the calling process into an
# isolated, lower-trust worker. compound-v-run-with-timeout.py has no `env=` override (it
# always inherits from whoever invokes it), so this worker wraps the ENTIRE supervisor
# invocation in `env -u NAME [-u NAME ...]` (BSD `env -u`, present on stock macOS — see
# $_SCRUB_VARS below) to strip every known provider auth/base-url var BEFORE python3 (and
# therefore opencode) ever sees the environment. This is REAL, not a comment: see the
# `run_opencode()` function. Verified live (see the accompanying scratch proof) that
# `env -u ANTHROPIC_BASE_URL -u ANTHROPIC_API_KEY ...` genuinely removes those vars from a
# child while leaving PATH and everything else intact.
#
# !!! SAFETY — LOWER-TRUST BACKEND (read before using) !!!
# opencode has NO kernel write-confinement (verified live by omission — no --sandbox /
# --read-only flag exists) and its own docs claim (DOC-CLAIMED, not independently
# live-verified against a real write attempt) it "allows all operations without explicit
# approval" by default. This worker does NOT trust that default: it writes a MANDATORY
# restrictive opencode.json (`{"permission": {"*": "ask"}}`) into the worktree before
# invoking opencode, then passes `--auto` to auto-approve exactly the non-denied subset —
# so the effective behavior matches every other lower-trust adapter (writes happen, but
# only inside a worktree the git-diff scope gate can observe), rather than trusting
# opencode's undocumented-in-practice wide-open default. The worktree + post-hoc `git
# diff` gate is still the ONLY real enforcement — same opt-in, lower-trust tier as
# Antigravity/Cursor/Devin. Prefer Codex (kernel-sandboxed) for untrusted / high-stakes work.
#
# Portability: stock-macOS bash 3.2.57 (NO associative arrays / mapfile / ${var,,})
# + jq. shellcheck-clean. Absolute paths throughout. Caller (the dispatcher) owns the
# merge-back decision; this script only OBSERVES and REPORTS — it never merges.
#
# Usage:
#   compound-v-run-opencode-worker.sh \
#     --run-id <id> --job-id <id> --repo <abs-repo-root> \
#     --prompt-file <abs-path> --model <provider/model> \
#     --write-allowed "<glob>[:<glob>...]" \
#     [--timeout-sec <n>] [--network true|false] \
#     [--read-only true|false] [--output-schema <abs-path>] [--effort <variant>]
#
# --model is REQUIRED (unlike devin/antigravity/cursor): opencode addresses models as a
# `provider/model` string with no single-vendor default to fall back on. --effort is
# OPTIONAL and maps to opencode's own `--variant` flag (provider-specific vocabulary —
# high/max/minimal — NOT Compound V's low/medium/high/xhigh; passed through best-effort,
# per adapter-opencode.md). --output-schema is ACCEPTED for CLI parity but IGNORED —
# opencode's one-shot `run` has no CLI-level output-schema flag. --network is advisory
# only (no kernel toggle exists).
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
# Bound opencode's captured JSONL stdout/stderr on disk (compound-v-run-with-timeout.py's
# own --max-output-bytes: a bounded, drain-and-discard pump so a runaway/looping worker can
# never fill the disk or block on a full pipe — see that script's docstring).
MAX_OUTPUT_BYTES=5000000

# The MANDATORY provider-credential scrub list (SAFETY, above). Every var here is a
# known provider auth token / base-url override across opencode's supported vendors
# (opencode is provider-agnostic and proxies many). Space-separated on purpose — this
# loops into repeated `env -u NAME` flags below (bash 3.2-safe: no arrays).
_SCRUB_VARS="ANTHROPIC_API_KEY ANTHROPIC_BASE_URL ANTHROPIC_AUTH_TOKEN \
OPENAI_API_KEY OPENAI_BASE_URL OPENAI_API_BASE OPENAI_ORG_ID \
GOOGLE_API_KEY GOOGLE_GENERATIVE_AI_API_KEY GEMINI_API_KEY GOOGLE_APPLICATION_CREDENTIALS \
AZURE_API_KEY AZURE_OPENAI_API_KEY AZURE_OPENAI_ENDPOINT \
AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_BEARER_TOKEN_BEDROCK \
OPENROUTER_API_KEY MISTRAL_API_KEY COHERE_API_KEY GROQ_API_KEY DEEPSEEK_API_KEY \
XAI_API_KEY TOGETHER_API_KEY PERPLEXITY_API_KEY FIREWORKS_API_KEY CEREBRAS_API_KEY \
OLLAMA_HOST"

# --- helpers -----------------------------------------------------------------

die() {
  # Environment/usage fault: no job_result could be produced.
  echo "compound-v-run-opencode-worker: $1" >&2
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

[ -n "$RUN_ID" ]      || die "--run-id is required"
[ -n "$JOB_ID" ]      || die "--job-id is required"
[ -n "$REPO" ]        || die "--repo is required"
[ -n "$PROMPT_FILE" ] || die "--prompt-file is required"
# --model is REQUIRED for opencode (unlike devin/antigravity/cursor): opencode addresses
# models as a `provider/model` string and has no single coherent "configured default"
# across its many proxied vendors the way a single-vendor CLI does.
[ -n "$MODEL" ]       || die "--model is required for opencode (must be a provider/model string, e.g. anthropic/claude-opus-4-6)"
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
# --output-schema is accepted for CLI parity with the codex worker but opencode's one-shot
# `run` has no such flag at the CLI level, so it is IGNORED. We still validate the path
# shape if one is passed, to keep the contract honest.
if [ -n "$OUTPUT_SCHEMA" ]; then
  case "$OUTPUT_SCHEMA" in /*) : ;; *) die "--output-schema must be absolute: $OUTPUT_SCHEMA" ;; esac
  [ -f "$OUTPUT_SCHEMA" ] || die "--output-schema not found: $OUTPUT_SCHEMA"
fi
# `xhigh` is codex-only; opencode's own vocabulary is high/max/minimal via --variant, never
# `xhigh`. compound-v-resolve-model.py / -validate-manifest.py already reject that pairing
# upstream of this worker — this is a defence-in-depth check, not the primary gate.
if [ "$EFFORT" = "xhigh" ]; then
  die "--effort xhigh is codex-only and is rejected for opencode: $EFFORT"
fi
# --read-only / --network are ACCEPTED for CLI parity with the codex worker but are
# ADVISORY ONLY for opencode: no kernel sandbox toggle exists. Reference them here so the
# contract is explicit and the parser-set vars are intentionally consumed.
: "advisory (opencode has no kernel sandbox): read_only=$READ_ONLY network=$NETWORK"

command -v jq       >/dev/null 2>&1 || die "jq not found on PATH"
command -v git      >/dev/null 2>&1 || die "git not found on PATH"
command -v python3  >/dev/null 2>&1 || die "python3 not found on PATH (scope gate needs it)"
command -v opencode >/dev/null 2>&1 || die "opencode not found on PATH"
# `env` is the vehicle for the MANDATORY credential scrub (SAFETY, above) — if it is
# missing we must NOT silently fall through to an unscrubbed invocation.
command -v env      >/dev/null 2>&1 || die "env not found on PATH (required for the mandatory provider-credential scrub)"

# Wall-clock cap: run opencode under the shared PROCESS-GROUP timeout supervisor
# (scripts/compound-v-run-with-timeout.py) — opencode has NO built-in --timeout flag
# (verified live absence). On expiry the supervisor killpg's the whole opencode process
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
# own git-derived enforcement WITHOUT needing any opencode-specific ignore list.
#
# NOTE on the job_result capture path: adapter-opencode.md's draft invocation informally
# says "capture to $WT/.job_result.txt", but writing it INSIDE the worktree would make it
# show up as an untracked file in the scope gate's own `git ls-files --others` scan — a
# false BLOCKED verdict on every single job. We deliberately place it in $ART (a sibling
# of $WT, never diffed) instead, exactly like the codex/antigravity/cursor workers' own
# `$ART/job_result.txt` convention.
ART="$WT.art"
mkdir -p "$ART"

# --- MANDATORY: pin a restrictive opencode.json into the worktree (SAFETY) --------------
# opencode discovers its config from the run directory (--dir "$WT"), so the restrictive
# permission file MUST physically live inside $WT for opencode to see it — there is no
# out-of-tree config-discovery path to exploit instead. To keep the worktree PRISTINE for
# the scope gate (a stray untracked/modified opencode.json would itself look like a job
# write), we: (a) back up any REPO-TRACKED opencode.json that already exists at this
# worktree's HEAD, (b) overwrite it with our pinned restrictive config for the run, then
# (c) restore the original content (or delete it, if none existed) BEFORE the scope gate
# runs — so the gate observes a worktree with ZERO trace of this scratch file.
OPENCODE_CONFIG="$WT/opencode.json"
OPENCODE_CONFIG_BACKUP="$ART/opencode.json.orig"
_opencode_config_preexisted="false"
if [ -f "$OPENCODE_CONFIG" ]; then
  _opencode_config_preexisted="true"
  cp "$OPENCODE_CONFIG" "$OPENCODE_CONFIG_BACKUP"
fi
# `permission: {"*": "ask"}` = deny-by-default; paired with `--auto` below (which
# auto-approves exactly the non-denied subset), this is the "ask, but headlessly
# auto-approved" posture documented as MANDATORY in adapter-opencode.md SAFETY — it
# never trusts opencode's own DOC-CLAIMED-but-unverified wide-open default.
cat > "$OPENCODE_CONFIG" <<'JSONEOF'
{
  "permission": {
    "*": "ask"
  }
}
JSONEOF

restore_opencode_config() {
  if [ "$_opencode_config_preexisted" = "true" ]; then
    cp "$OPENCODE_CONFIG_BACKUP" "$OPENCODE_CONFIG"
  else
    rm -f "$OPENCODE_CONFIG"
  fi
}

# --- run the headless opencode worker -----------------------------------------
# Pinned invocation (opencode-ai 1.17.18 — RE-PROBE OFTEN per adapter-opencode.md, this
# package ships new builds multiple times a day):
#   opencode run --dir "$WT" --format json --auto -m "$MODEL" [--variant "$EFFORT"] \
#     --title "compound-v-$JOB_ID" "$PROMPT" </dev/null
#
# Load-bearing facts (adapter-opencode.md):
#   * `--dir "$WT"` = opencode's real --cd-equivalent (unlike antigravity/cursor/devin).
#   * `--format json` = a JSONL event stream on stdout, one JSON object per line. Every
#     line carries `.sessionID`; `type:"text"` events carry `.part.text` — there is NO
#     `--output-last-message` equivalent, so summary/session_id are built by PARSING
#     this stream (below), not by reading a single result file opencode wrote itself.
#   * `--auto` = REQUIRED for unattended writes: "auto-approve permissions that are not
#     explicitly denied" — paired with the MANDATORY pinned opencode.json above.
#   * `-m "$MODEL"` = REQUIRED, must be a real `provider/model` string.
#   * `--variant "$EFFORT"` = OPTIONAL, only appended when --effort was given.
#   * `--title` = cosmetic correlation aid for `opencode session list`.
#   * stdin `</dev/null` — same non-negotiable rule as every other external worker.
#
# THE MANDATORY CREDENTIAL SCRUB (SAFETY, above): compound-v-run-with-timeout.py has no
# `env=` parameter — it always inherits whatever environment ITS caller (this script) had.
# So the scrub happens OUTSIDE the supervisor: `env -u NAME [-u NAME ...]` wraps the ENTIRE
# `python3 "$SUPERVISOR" ...` invocation, stripping every var in $_SCRUB_VARS before python3
# (and therefore its Popen'd opencode child, which inherits python3's ALREADY-scrubbed
# os.environ) ever sees them. This is unquoted-by-design (word-splits into repeated `-u`
# flags; every name in $_SCRUB_VARS is a bare identifier, never attacker-controlled).

EVENTS_LOG="$ART/opencode_events.jsonl"
STDERR_LOG="$ART/opencode_stderr.log"
RESULT_TXT="$ART/job_result.txt"
exit_code=0

_ENV_SCRUB_ARGS=""
for _v in $_SCRUB_VARS; do
  _ENV_SCRUB_ARGS="$_ENV_SCRUB_ARGS -u $_v"
done

# run_opencode runs the pinned `opencode run` invocation UNDER (a) the mandatory
# credential-scrub `env -u ...` wrapper and (b) the process-group timeout supervisor: on
# expiry the supervisor killpg's the whole opencode tree (not just the direct child) and
# returns 124. --stdout/--stderr are BOUNDED capture files (--max-output-bytes) so a
# runaway/looping worker can never fill the disk or block on a full pipe.
run_opencode() {
  # shellcheck disable=SC2086
  if [ -n "$EFFORT" ]; then
    env $_ENV_SCRUB_ARGS \
      python3 "$SUPERVISOR" --timeout "$TIMEOUT_SEC" --grace 3 \
        --stdout "$EVENTS_LOG" --stderr "$STDERR_LOG" --max-output-bytes "$MAX_OUTPUT_BYTES" \
        -- opencode run \
        --dir "$WT" \
        --format json \
        --auto \
        -m "$MODEL" \
        --variant "$EFFORT" \
        --title "compound-v-$JOB_ID" \
        "$(cat "$PROMPT_FILE")" </dev/null
  else
    env $_ENV_SCRUB_ARGS \
      python3 "$SUPERVISOR" --timeout "$TIMEOUT_SEC" --grace 3 \
        --stdout "$EVENTS_LOG" --stderr "$STDERR_LOG" --max-output-bytes "$MAX_OUTPUT_BYTES" \
        -- opencode run \
        --dir "$WT" \
        --format json \
        --auto \
        -m "$MODEL" \
        --title "compound-v-$JOB_ID" \
        "$(cat "$PROMPT_FILE")" </dev/null
  fi
}

# `set +e` so a non-zero exit (incl. 124 when the timeout fires) is captured rather
# than aborting the script — we must still produce a job_result either way.
set +e
run_opencode
exit_code=$?
set -e

# Restore the worktree to its pre-run state BEFORE anything below reads it — the scope
# gate must never see our own scratch opencode.json as a job-authored write.
restore_opencode_config

# --- capture session_id + summary --------------------------------------------
# Parse the JSONL event stream line-by-line (NOT `jq -s` slurp-the-whole-file): a single
# malformed/truncated line (e.g. the process was killed mid-write by the timeout
# supervisor) would make a whole-file jq parse fail and lose EVERY event, not just the
# bad one. Line-by-line degrades gracefully — each line is judged independently, and a
# bad line simply contributes nothing (never aborts the loop, per adapter-opencode.md's
# "degrade gracefully if the last event isn't the summary" requirement).
#   * session_id ← the FIRST line that carries a non-empty `.sessionID` (adapter-opencode.md).
#   * summary    ← the LAST non-empty `.part.text` from a `type:"text"` event.
session_id=""
summary=""
if [ -f "$EVENTS_LOG" ]; then
  while IFS= read -r _ev_line || [ -n "$_ev_line" ]; do
    [ -z "$_ev_line" ] && continue
    _etype=$(printf '%s' "$_ev_line" | jq -r '.type? // empty' 2>/dev/null) || _etype=""
    if [ -z "$session_id" ]; then
      _sid=$(printf '%s' "$_ev_line" | jq -r '.sessionID? // empty' 2>/dev/null) || _sid=""
      if [ -n "$_sid" ]; then session_id="$_sid"; fi
    fi
    if [ "$_etype" = "text" ]; then
      _txt=$(printf '%s' "$_ev_line" | jq -r '.part.text? // empty' 2>/dev/null) || _txt=""
      if [ -n "$_txt" ]; then summary="$_txt"; fi
    fi
  done < "$EVENTS_LOG"
fi

# session_id shape gate: opencode's own token is `ses_...`-prefixed, NOT an RFC-4122 UUID
# (adapter-opencode.md — explicitly warns the codex worker's UUID regex must NOT be
# reused verbatim here). Accept only a safe charset after the prefix; anything else ⇒
# empty ("resume fresh"), never a token that could inject into a future `-s` argv.
case "$session_id" in
  ses_*)
    case "$session_id" in
      *[!A-Za-z0-9_-]*) session_id="" ;;
    esac
    ;;
  *) session_id="" ;;
esac

[ -n "$summary" ] || summary="(no summary emitted by worker)"
printf '%s' "$summary" > "$RESULT_TXT" 2>/dev/null || true

# opencode's own JSONL failure signal (adapter-opencode.md): `{"type":"error",...}` can
# appear even on a clean-looking exit. Detected the same line-by-line way, never via a
# whole-file jq parse that a malformed line could sink entirely.
_opencode_saw_error="false"
if [ -f "$EVENTS_LOG" ]; then
  while IFS= read -r _ev_line || [ -n "$_ev_line" ]; do
    [ -z "$_ev_line" ] && continue
    _etype=$(printf '%s' "$_ev_line" | jq -r '.type? // empty' 2>/dev/null) || _etype=""
    if [ "$_etype" = "error" ]; then
      _opencode_saw_error="true"
      break
    fi
  done < "$EVENTS_LOG"
fi

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
# fault (rc 2 or unparseable) is an error; opencode timeout (124) is a timeout; any
# other non-zero opencode exit is an error; an in-band `type:"error"` event (even on
# exit 0) is an error (don't report a false success); otherwise success.

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
elif [ "$_opencode_saw_error" = "true" ]; then
  status="error"
fi

# --- classify a backend failure (fail-closed — no per-provider table yet) ---
# A non-success / non-blocked status carries a failure_class (out_of_credits /
# rate_limited / overloaded / auth / context_length / timeout / network / other) that
# drives the dispatcher's deterministic retry/reroute/halt policy. NO _OPENCODE_RULES
# table exists yet in compound-v-classify-failure.py (its --backend flag does not even
# list "opencode" — an unregistered backend is a CLI usage error, not a graceful
# fallback) because opencode proxies MANY providers whose error text differs per-vendor
# (an Anthropic 429 looks nothing like an OpenAI 429) — a genuinely harder classification
# problem than any single-vendor backend faces. We deliberately do NOT call that script
# with a fabricated backend name — fail CLOSED to "other" directly, exactly the interim
# rule adapter-opencode.md documents (the same pattern the Cursor adapter already used
# for its own "provisional" needles before real signatures existed).
# TODO: once real per-provider failure samples are available, add an _OPENCODE_RULES
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
