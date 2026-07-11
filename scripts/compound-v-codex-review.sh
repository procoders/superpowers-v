#!/usr/bin/env bash
#
# compound-v-codex-review.sh — Compound V cross-model plan reviewer (the second opinion).
#
# Runs an INDEPENDENT, ADVERSARIAL review of a plan/manifest on a headless, READ-ONLY
# `codex exec` worker (a different model family from the Opus planner), and emits the
# structured findings (schemas/plan-review.schema.json) on stdout as JSON.
#
# This is ADVISORY ONLY. Codex returns its opinion; the ORCHESTRATOR arbitrates — it
# must address each finding (accept → revise the plan, or reject → one-line rebuttal),
# and may escalate a contested high/critical finding to the human. Codex is never the
# authority. The value is error DECORRELATION: a different model family sees the blind
# spots the planner's own family does not see in itself.
#
# Read-only: --sandbox read-only means codex can READ the repo (to ground its objections
# against the real files) but cannot write anything. Scratch (the findings file + stderr)
# lives under $TMPDIR, outside the repo. stdin is /dev/null and codex stdout is captured —
# the same hard-won lessons as the implementation worker; this script's stdout carries
# ONLY the findings JSON.
#
# Usage:
#   compound-v-codex-review.sh \
#     --plan-file <abs> --repo <abs-repo-root> \
#     [--model <model>] [--effort low|medium|high|xhigh] \
#     [--schema <abs>] [--context-file <abs>] ... \
#     [--timeout-sec <n>]
#
# Defaults: model gpt-5.6-sol, effort xhigh (the "Codex on their max" the design calls for —
# xhigh is codex-only and live-verified on codex-cli 0.144.1;
# requires codex-cli >= 0.143.0 -- an older client fails loud with a clear "requires a newer
# version of Codex" error, not silently). `--effort xhigh` is also accepted: this script runs
# codex only, and `xhigh` is valid iff backend is codex (model_reasoning_effort=xhigh
# live-verified 2026-07-11 on codex-cli 0.144.1; every other backend rejects it).
# Schema default = <plugin>/schemas/plan-review.schema.json, resolved relative to THIS
# script — the reviewed repo has no reason to carry the plugin's schema.
#
# Exit: 0 when findings JSON was produced (even verdict=reject — that is reported IN the
# JSON). Non-zero only on a usage / environment fault.

set -euo pipefail

DEFAULT_MODEL="gpt-5.6-sol"
DEFAULT_EFFORT="xhigh"
DEFAULT_TIMEOUT_SEC=600

die() { echo "compound-v-codex-review: $1" >&2; exit 2; }

PLAN_FILE=""
REPO=""
MODEL="$DEFAULT_MODEL"
EFFORT="$DEFAULT_EFFORT"
SCHEMA=""
TIMEOUT_SEC="$DEFAULT_TIMEOUT_SEC"
CONTEXT_FILES=""   # newline-joined list of absolute paths

while [ $# -gt 0 ]; do
  case "$1" in
    --plan-file)    PLAN_FILE="$2"; shift 2 ;;
    --repo)         REPO="$2"; shift 2 ;;
    --model)        MODEL="$2"; shift 2 ;;
    --effort)       EFFORT="$2"; shift 2 ;;
    --schema)       SCHEMA="$2"; shift 2 ;;
    --context-file) CONTEXT_FILES="$CONTEXT_FILES
$2"; shift 2 ;;
    --timeout-sec)  TIMEOUT_SEC="$2"; shift 2 ;;
    *) die "unknown argument: $1" ;;
  esac
done

[ -n "$PLAN_FILE" ] || die "--plan-file is required"
[ -n "$REPO" ]      || die "--repo is required"
case "$PLAN_FILE" in /*) : ;; *) die "--plan-file must be absolute: $PLAN_FILE" ;; esac
case "$REPO" in /*) : ;; *) die "--repo must be absolute: $REPO" ;; esac
[ -f "$PLAN_FILE" ] || die "--plan-file not found: $PLAN_FILE"
[ -d "$REPO" ]      || die "--repo not a directory: $REPO"
# Default schema ships WITH the plugin (next to this script), NOT in the reviewed repo —
# defaulting to "$REPO/schemas/..." broke /v:review-plan in every project except this one.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
[ -n "$SCHEMA" ] || SCHEMA="$SCRIPT_DIR/../schemas/plan-review.schema.json"
[ -f "$SCHEMA" ] || die "schema not found: $SCHEMA"
# xhigh accepted here because this script is codex-only (xhigh is valid iff backend: codex).
case "$EFFORT" in low|medium|high|xhigh) : ;; *) die "--effort must be low|medium|high|xhigh: $EFFORT" ;; esac
# --timeout-sec is interpolated UNQUOTED into the codex argv (word-split into the
# `timeout` prefix), so a crafted value injects argv. Pin it to a positive integer.
case "$TIMEOUT_SEC" in
  ''|*[!0-9]*) die "--timeout-sec must be a positive integer: $TIMEOUT_SEC" ;;
esac
command -v codex >/dev/null 2>&1 || die "codex not found on PATH"

# Hard wall-clock cap via the shared process-group timeout supervisor — the SAME wrapper the
# codex/cursor/agy workers use, NOT an external `timeout`/`gtimeout` binary. This guarantees a
# cap even when neither binary is installed (previously: no binary ⇒ NO cap ⇒ a stalled codex
# review could hang unbounded) and kills the whole codex process GROUP on expiry (a
# `timeout`/`gtimeout` prefix signals only the direct child, leaking orphaned tool children).
SUPERVISOR="$SCRIPT_DIR/compound-v-run-with-timeout.py"
[ -f "$SUPERVISOR" ] || die "timeout supervisor not found: $SUPERVISOR"

# Scratch OUTSIDE the repo (read-only codex can still read the repo via --cd).
TMPROOT="${TMPDIR:-/tmp}"; TMPROOT="${TMPROOT%/}"
ART="$TMPROOT/compound-v-review/$$"
mkdir -p "$ART"
FINDINGS="$ART/findings.json"
STDERR_LOG="$ART/codex_stderr.log"
STDOUT_LOG="$ART/codex_stdout.log"

# Build the adversarial review prompt: instructions + the plan + any context.
PROMPT_FILE="$ART/prompt.txt"
{
  cat <<'EOF'
You are an INDEPENDENT cross-model reviewer. You belong to a DIFFERENT model family than
the planner (an Opus model) who wrote the plan below. Your one value is error
DECORRELATION: surface the blind spots the planner's own family will not see in itself.

You are ADVISORY, not the authority. You do NOT approve or block anything — the
orchestrator weighs your findings and decides. Your job is to be a rigorous, skeptical
second opinion.

ADVERSARIALLY review the plan. Actively TRY TO REFUTE it. Default to skepticism. Hunt for:
- partition: two tasks that can write the same file (expand globs); shared/contract files
  not isolated into a serial pre-phase.
- coupling: a hidden dependency the partition treats as independent.
- scope: a task whose write-scope is too wide or too narrow for its stated work.
- model-routing: a task on the wrong tier/backend (e.g. security work not on the deepest
  tier; mechanical work over-provisioned; Codex work without worktree isolation).
- acceptance: acceptance criteria that are vague or not actually testable.
- sequencing: a reader task that runs before the task that authors what it reads.
- risk: anything that could silently corrupt state, leak scope, or fail to resume.

You may READ the repository (you are sandboxed read-only) to ground each objection against
the real files — prefer concrete evidence over speculation. If you find nothing in a
category, say so; an empty findings list is honest and valuable. Be specific and
falsifiable. Return ONLY the structured findings per the provided schema.

--- PLAN UNDER REVIEW ---
EOF
  cat "$PLAN_FILE"
  printf '%s\n' "$CONTEXT_FILES" | while IFS= read -r cf; do
    [ -z "$cf" ] && continue
    [ -f "$cf" ] || continue
    printf '\n--- ADDITIONAL CONTEXT: %s ---\n' "$cf"
    cat "$cf"
  done
} > "$PROMPT_FILE"

set +e
python3 "$SUPERVISOR" --timeout "$TIMEOUT_SEC" --grace 3 -- codex exec \
  --cd "$REPO" \
  --sandbox read-only \
  --skip-git-repo-check \
  --model "$MODEL" \
  -c model_reasoning_effort="$EFFORT" \
  --output-schema "$SCHEMA" \
  --output-last-message "$FINDINGS" \
  "$(cat "$PROMPT_FILE")" </dev/null >"$STDOUT_LOG" 2>"$STDERR_LOG"
rc=$?
set -e

if [ ! -s "$FINDINGS" ]; then
  die "codex produced no findings (exit $rc). stderr: $(grep -v 'codex_hooks is deprecated' "$STDERR_LOG" 2>/dev/null | tail -3 | tr '\n' ' ')"
fi

# Emit ONLY the findings JSON on stdout.
cat "$FINDINGS"
