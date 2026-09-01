#!/usr/bin/env bash
# Compound V — Stop hook: the armed epic goal condition (Feature A) and the
# off-by-default pipeline-bypass correction (Feature B).  v2.18.
#
# ┌──────────────────────────────────────────────────────────────────────────┐
# │ HIGHEST BLAST RADIUS IN THIS PLUGIN.  This file runs at the end of EVERY  │
# │ turn of EVERY Claude Code session of every user who installs Compound V.  │
# │ A bug here does not fail a build — it wedges a stranger's session so they │
# │ cannot end their turn.  Read the two invariants below before editing.     │
# └──────────────────────────────────────────────────────────────────────────┘
#
# INVARIANT 1 — A BLOCK IS ONLY EVER VALID JSON, NEVER AN EXIT CODE.
#   A non-zero exit from a `Stop` hook *is itself a block*.  So any ordinary
#   bash failure — a bad assignment, a missing `jq`, an unbound variable, a
#   syntax error — would hold the user's turn open forever.  Fail-open is
#   therefore MECHANICAL, via two independent mechanisms, BOTH required:
#     (a) hooks.json registers this script as `"<script>" || true`;
#     (b) this script is an unconditional-`exit 0` wrapper: an EXIT trap that
#         forces status 0 on every path, plus all fallible logic confined to
#         `hook_main`, run inside a command substitution whose output is
#         DISCARDED unless it returned 0.  A half-finished run emits nothing.
#   Deliberately NO `set -e` and NO `set -u`.  `set -u` in particular exits the
#   whole shell on an unbound variable — `|| true` around a function call does
#   not save you from it.  Every expansion below is explicitly defaulted
#   instead, and every pipeline is guarded (under `set -e` a no-match `grep`
#   aborts the script, and an aborted Stop hook exits non-zero = a block).
#
# INVARIANT 2 — THIS HOOK NEVER WRITES epic-state.json.
#   That file has ~35 `_atomic_write_json` call sites documented as "not
#   flock-guarded — only the single live driver calls this", and a lock inside
#   `_atomic_write_json` would self-deadlock `claim_resume`, which already
#   calls it while holding the lock.  The hook READS it, exclusively through
#   `scripts/compound-v-epic-state.py --goal-status` (strictly read-only).
#   `continue_count` and the enforcement once-marker live in this hook's own
#   store under the OS temp dir.  tests/test-epic-goal-stop.sh asserts zero
#   writes (content digest + mtime unchanged across a blocking event).
#
# DECISION TABLE (evaluated top to bottom; exactly ONE state update and exactly
# ONE JSON response per event):
#
#   1. jq / stdin unusable ......................... exit 0, silent
#   2. hook_event_name != "Stop" ................... exit 0, silent   [GATE FIRST]
#        SubagentStop / StopFailure / unknown / missing all land here.
#   3. session_id empty ............................ exit 0 (cannot isolate)
#   4. GOAL RULE — armed && session matches && !met && !terminal
#        && continue_count < max_continues ......... increment, PERSIST, BLOCK, done
#      any of: not armed / session mismatch / goal met / epic terminal /
#      counter exhausted / state unreadable / store lost / persist failed
#                                                    ... fall through, open
#   5. ENFORCEMENT — only if the goal rule did not block, and only when
#      `.enforcement.pipeline_bypass == true` in .claude/compound-v.json:
#      source changed && no run record && marker unset ... set marker, BLOCK
#   6. otherwise ................................... exit 0, silent
#
# STORE LOSS, AND THE ONE CONSERVATIVE EDGE IT COSTS.  A temp sweep or a reboot
# can remove the store mid-arm.  Recreating the counter at zero would silently
# grant another full tranche of continuations beyond `max_continues`, so a
# missing store during an ACTIVE arm fails OPEN and says so on stderr.  "Active"
# is decided by two independent signals: the arm's slot DIRECTORY (present but
# counter-less = partial loss) and `stop_hook_active` (true = a Stop block
# already happened this turn, so a vanished slot is loss, not novelty).  The
# cost, stated: a disarm/re-arm INSIDE a turn that already blocked is
# indistinguishable from a sweep and therefore fails open — the epic simply is
# not held that turn.  Autonomy stopping is an acceptable failure; an unbounded
# loop is not.  Covered by tests/test-epic-goal-stop.sh.
#
# `stop_hook_active` is READ and LOGGED but never returned on.  The flag is set
# on the first block and never cleared for the rest of the turn, so returning on
# it would cap this feature at exactly one block — while a synthetic-stdin
# selftest still passed.  (Anthropic's own `ralph-loop`, the one shipped Stop
# hook that actually loops, never reads the flag at all.)  It IS used as
# corroborating evidence in one place: see "store loss" below.
#
# BOUNDS, HONESTLY RANKED.  Our own `continue_count` is THE bound.  The harness
# cap (CLAUDE_CODE_STOP_HOOK_BLOCK_CAP, default 8) is a backstop we do not rely
# on — it is gated `if (n > 0 && …)`, so 0 disables blocking limits entirely.
# The epic circuit breakers remain unchanged and authoritative above both.
#
# ENFORCEMENT IS BEST-EFFORT AND NOTHING HERE CLAIMS OTHERWISE.  The runtime
# silently discards a `Stop` block when a turn ends via a tool result, an MCP
# end-turn, or a loop tick.  The guarantee is "at most once WHILE THE MARKER
# SURVIVES" — a temp sweep can happen mid-session and would permit one more
# correction.  That failure direction is benign (an extra correction, never a
# missed one), and the weaker true promise beats the stronger false one.

# Mechanism (b), first half: force status 0 on EVERY exit path, including a
# mid-script abort or a signal.  `hook_main` clears this trap for itself so its
# own non-zero return still reaches the caller as a real failure signal.
trap 'exit 0' EXIT

set -o pipefail

_HOOK_TAG="compound-v/epic-goal-stop"

_log() { printf '%s: %s\n' "$_HOOK_TAG" "$*" >&2; }

# --- store ------------------------------------------------------------------
# Everything this hook writes lives here, and NOWHERE else.
_store_dir() {
  local t="${TMPDIR:-/tmp}"
  while [ "${t}" != "/" ] && [ "${t%/}" != "${t}" ]; do t="${t%/}"; done
  [ -n "$t" ] || t="/tmp"
  printf '%s/compound-v-stop-hook' "$t"
}

# sha256 of "$1".  No digest tool ⇒ we cannot key the store ⇒ fail open.
_digest() {
  if command -v shasum >/dev/null 2>&1; then
    printf '%s' "$1" | shasum -a 256 2>/dev/null | cut -d' ' -f1
  elif command -v sha256sum >/dev/null 2>&1; then
    printf '%s' "$1" | sha256sum 2>/dev/null | cut -d' ' -f1
  elif command -v openssl >/dev/null 2>&1; then
    printf '%s' "$1" | openssl dgst -sha256 2>/dev/null | awk '{print $NF}'
  else
    return 1
  fi
}

# --- discovery --------------------------------------------------------------
# Fixed, ordered, deterministic — never a guess.  From the hook's canonicalized
# `cwd`, walk UP to the nearest ancestor holding a `.git` (the canonical project
# root); fall back to the cwd itself.  Bounded to 40 levels.
_project_root() {
  local d="$1" i=0
  while [ "$i" -lt 40 ]; do
    [ -e "$d/.git" ] && { printf '%s' "$d"; return 0; }
    [ "$d" = "/" ] && break
    d="$(dirname "$d")" || break
    [ -n "$d" ] || break
    i=$((i + 1))
  done
  printf '%s' "$1"
}

# At most ONE armed epic per project.  Zero or multiple matches FAIL OPEN rather
# than guessing which epic to hold the session open for.
_discover_state() {
  local base="$1/docs/superpowers/execution/epics"
  [ -d "$base" ] || return 1
  local n=0 found="" d f
  for d in "$base"/*/; do
    f="${d}epic-state.json"
    [ -f "$f" ] || continue
    n=$((n + 1))
    found="$f"
  done
  if [ "$n" -gt 1 ]; then
    _log "discovery found $n epic-state.json files under $base — FAILING OPEN (at most one armed epic per project)"
    return 1
  fi
  [ "$n" -eq 1 ] || return 1
  printf '%s' "$found"
}

# The read-only CLI that owns the completion vocabulary.  Plugin root first
# (how the hook actually runs), then a repo-relative sibling (how the tests and
# a source checkout run).
_locate_cli() {
  local c
  if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ]; then
    c="${CLAUDE_PLUGIN_ROOT}/scripts/compound-v-epic-state.py"
    [ -f "$c" ] && { printf '%s' "$c"; return 0; }
  fi
  c="$(dirname "$0")/../scripts/compound-v-epic-state.py"
  [ -f "$c" ] && { printf '%s' "$c"; return 0; }
  return 1
}

_is_uint() { case "${1:-}" in '' | *[!0-9]*) return 1 ;; *) return 0 ;; esac; }

# --- rule 1: the armed goal condition ---------------------------------------
# Returns 0 ONLY when it printed a block on stdout (which also means it made the
# single permitted state update).  Any other outcome returns non-zero and the
# caller falls through to the enforcement rule.
_goal_rule() {
  local proj="$1" sid="$2" sha="$3"

  local state cli
  state="$(_discover_state "$proj")" || return 1

  # Cheap NEGATIVE fast-path, and nothing more.  This hook runs at the end of
  # every turn of every session, so it must not pay a Python interpreter start
  # for an epic that carries no armed record at all.  `goal_arm` is lazily
  # created by --arm-goal and POPPED by --disarm-goal, so its presence is an
  # exact, non-semantic test.  Only a DEFINITIVE "absent" skips; any jq failure
  # falls through to the canonical helper, which stays the sole authority on
  # met / terminal / should_continue.
  local has_arm
  has_arm="$(jq -r 'if has("goal_arm") then "y" else "n" end' "$state" 2>/dev/null)" || has_arm=""
  [ "$has_arm" = "n" ] && return 1

  cli="$(_locate_cli)" || { _log "epic-state CLI not found — goal rule inert"; return 1; }
  command -v python3 >/dev/null 2>&1 || { _log "python3 absent — goal rule inert"; return 1; }

  # STRICTLY read-only (`--goal-status` never writes, and its CLI branch never
  # calls _atomic_write_json).  Any non-zero — corrupt JSON, a failed marathon
  # validation, a vanished file — FAILS OPEN.
  local gs rc
  gs="$(python3 "$cli" --goal-status --state "$state" 2>/dev/null)"
  rc=$?
  if [ "$rc" -ne 0 ] || [ -z "$gs" ]; then
    _log "--goal-status failed (rc=$rc) on $state — FAILING OPEN"
    return 1
  fi

  local armed
  armed="$(printf '%s' "$gs" | jq -r '.armed // false' 2>/dev/null)" || armed="false"
  [ "$armed" = "true" ] || return 1

  # Session isolation.  An EMPTY stored id is refused here as well as at arm
  # time: an empty id matches nothing meaningfully, and a fall-through would
  # hold EVERY session in the project open, not just the one that armed it.
  local ssid
  ssid="$(printf '%s' "$gs" | jq -r '.session_id // empty' 2>/dev/null)" || ssid=""
  [ -n "$ssid" ] || { _log "armed record carries an empty session_id — FAILING OPEN"; return 1; }
  [ "$ssid" = "$sid" ] || return 1

  local arm_id maxc cond should
  arm_id="$(printf '%s' "$gs" | jq -r '.arm_id // empty' 2>/dev/null)" || arm_id=""
  maxc="$(printf '%s' "$gs" | jq -r '.max_continues // empty' 2>/dev/null)" || maxc=""
  cond="$(printf '%s' "$gs" | jq -r '.condition // empty' 2>/dev/null)" || cond=""
  should="$(printf '%s' "$gs" | jq -r '.should_continue // false' 2>/dev/null)" || should="false"

  [ -n "$arm_id" ] || { _log "armed record carries an empty arm_id — FAILING OPEN"; return 1; }
  # `0` is INVALID, not "unlimited".  There is no unlimited setting.
  _is_uint "$maxc" && [ "$maxc" -gt 0 ] || {
    _log "max_continues is not a positive integer (${maxc:-<empty>}) — FAILING OPEN"
    return 1
  }

  # `should_continue` is `armed AND NOT met AND NOT terminal`.  A terminal-but-
  # unmet epic (tripped breaker, halt_epic, exhausted work, unsatisfiable DAG)
  # yields false: it STOPPED, it did not finish — continuing would burn the
  # counter against a dead epic, and calling it "met" would be a fabricated
  # completion claim.
  [ "$should" = "true" ] || return 1

  # --- the counter, in this hook's own store --------------------------------
  # Keyed on all THREE of root + session + arm_id.  Root, because keying on the
  # session alone lets project A suppress project B in the same session.
  # arm_id, because a disarm/rearm inside one live session would otherwise reuse
  # the slot and a SEQUENTIAL second epic would inherit the first epic's count.
  local store key dir cnt_file cnt
  store="$(_store_dir)"
  key="$(_digest "${proj}|${sid}|${arm_id}")" || {
    _log "no sha256 tool available — cannot key the store, FAILING OPEN"
    return 1
  }
  [ -n "$key" ] || return 1
  dir="${store}/goal-${key}"
  cnt_file="${dir}/count"

  if [ -d "$dir" ]; then
    # The DIRECTORY is the arm's existence marker; the file is the counter.
    # Directory present but counter gone = the store was lost mid-arm.
    # Recreating it at zero would silently grant another full tranche of
    # continuations beyond max_continues, so: FAIL OPEN.  Autonomy stopping is
    # an acceptable failure; an unbounded loop is not.
    if [ ! -f "$cnt_file" ]; then
      _log "counter file missing under an existing arm slot ($dir) — the store was swept mid-arm. FAILING OPEN; NOT recreating the counter at zero. Re-arm with /v:epic to resume goal-held continuation."
      return 1
    fi
    cnt="$(cat "$cnt_file" 2>/dev/null)" || cnt=""
    cnt="$(printf '%s' "$cnt" | tr -d '[:space:]')" || cnt=""
    _is_uint "$cnt" || {
      _log "counter file is corrupt (${cnt:-<empty>}) — FAILING OPEN"
      return 1
    }
  else
    # No slot at all.  Either a genuinely new arm (count starts at 0), or the
    # WHOLE store was swept.  `stop_hook_active` disambiguates the dangerous
    # half: it is true only when a Stop hook already blocked this turn, which
    # means a slot must have existed — so its absence is loss, not novelty.
    if [ "$sha" = "true" ]; then
      _log "arm slot absent although a Stop block already occurred this turn — the store was swept. FAILING OPEN; NOT restarting the counter at zero."
      return 1
    fi
    mkdir -p "$dir" 2>/dev/null || {
      _log "cannot create the hook store at $dir — FAILING OPEN"
      return 1
    }
    cnt=0
  fi

  if [ "$cnt" -ge "$maxc" ]; then
    _log "continue budget exhausted for arm ${arm_id} (${cnt}/${maxc}) — releasing the turn."
    return 1
  fi

  local next tmp
  next=$((cnt + 1))
  # PERSIST BEFORE THE BLOCK IS EMITTED.  A failed persist OPENS the hook — a
  # block we could not count is a block we could not bound.
  tmp="${cnt_file}.tmp.$$"
  if ! printf '%s\n' "$next" >"$tmp" 2>/dev/null; then
    rm -f "$tmp" 2>/dev/null
    _log "could not write the continue counter — FAILING OPEN (a block we cannot count is a block we cannot bound)"
    return 1
  fi
  if ! mv -f "$tmp" "$cnt_file" 2>/dev/null; then
    rm -f "$tmp" 2>/dev/null
    _log "could not commit the continue counter — FAILING OPEN"
    return 1
  fi

  _log "goal armed (condition=${cond}) and unmet — continuation ${next}/${maxc} for arm ${arm_id}"

  local reason
  reason="Compound V — an epic goal is armed for this session and is NOT yet met.

  goal condition : ${cond}
  epic state     : ${state}
  continuation   : ${next} of ${maxc}

Do not end the turn. Resume the epic loop in commands/v-epic.md: read the epic
state, take the next runnable feature, and drive it through the pipeline. The
goal is evaluated DETERMINISTICALLY from that file — you cannot satisfy it by
declaring it satisfied, only by the work landing on disk. When the condition is
genuinely met (or the epic goes terminal), this hook stops holding the turn open
by itself; to stop sooner, disarm with:
  python3 scripts/compound-v-epic-state.py --disarm-goal --state ${state}"

  jq -n --arg reason "$reason" \
    --arg msg "Compound V: epic goal unmet — continuation ${next}/${maxc}" \
    '{decision: "block", reason: $reason, systemMessage: $msg}' 2>/dev/null || return 1
  return 0
}

# --- rule 2: pipeline-bypass enforcement (OFF by default) -------------------
# Runs ONLY when the goal rule did not block.  Returns 0 having printed a block,
# or non-zero having printed nothing.
_enforcement_rule() {
  local proj="$1" sid="$2"

  local cfg="${proj}/.claude/compound-v.json"
  [ -f "$cfg" ] || return 1
  local on
  on="$(jq -r '.enforcement.pipeline_bypass // false' "$cfg" 2>/dev/null)" || on="false"
  [ "$on" = "true" ] || return 1

  command -v git >/dev/null 2>&1 || return 1

  local store key marker
  store="$(_store_dir)"
  key="$(_digest "${proj}|${sid}")" || return 1
  [ -n "$key" ] || return 1
  marker="${store}/enforce-${key}"
  # "At most once WHILE THE MARKER SURVIVES" — not "once per session".
  [ -e "$marker" ] && return 1

  local changed
  changed="$( { git -C "$proj" diff --name-only HEAD 2>/dev/null || true
                git -C "$proj" ls-files --others --exclude-standard 2>/dev/null || true
              } | sed '/^$/d' | sort -u )" || changed=""
  [ -n "$changed" ] || return 1

  # A run record among the changes means the pipeline WAS used for this work.
  local records
  records="$(printf '%s\n' "$changed" \
    | grep -E '^docs/superpowers/(execution/[^/]+/state\.json|pre-eval/.+)$' 2>/dev/null || true)"
  [ -z "$records" ] || return 1

  # Source = everything except the pipeline's own paper trail and this hook's
  # own store (normally in $TMPDIR and therefore outside the repo entirely —
  # excluded explicitly for the case where TMPDIR is set INSIDE the worktree,
  # where arming a goal would otherwise count as "source changed").
  local store_rel="" src
  case "$store" in
    "$proj"/*) store_rel="${store#"$proj"/}" ;;
  esac
  src="$(printf '%s\n' "$changed" | grep -v '^docs/superpowers/' 2>/dev/null || true)"
  if [ -n "$store_rel" ]; then
    src="$(printf '%s\n' "$src" | grep -v "^${store_rel}/" 2>/dev/null || true)"
  fi
  src="$(printf '%s\n' "$src" | sed '/^$/d')" || src=""
  [ -n "$src" ] || return 1

  # Set the marker BEFORE emitting.  A marker we could not write is a
  # correction we could not bound, so that case stays silent.
  mkdir -p "$store" 2>/dev/null || return 1
  : >"$marker" 2>/dev/null || return 1

  local n
  n="$(printf '%s\n' "$src" | wc -l | tr -d ' ')" || n="?"

  local reason
  reason="Compound V — tracked source changed in this session, but no run record exists.

  changed source files : ${n}
  run record looked for : docs/superpowers/execution/<run-id>/state.json
                          docs/superpowers/pre-eval/<id>.json (accepted fast-path)

Implementing straight from an approved design is literally compliant with the
letter of the upstream brainstorming gate — and it is exactly the bypass this
check exists to name. The Compound V pipeline begins where that gate releases.

Before finishing: either route this through the pipeline (/v:orchestrate then
/v:dispatch, or /v:epic for a multi-feature build), or — if the change is
provably trivial and low-impact — take the SANCTIONED SHORTCUT: the Stage -1
Pre-Evaluation fast-path in skills/compound-v/phase-preeval.md, which collapses
the pipeline into one scope-gated implementer plus one combined SPEC+QUALITY
review and leaves a real pre-eval record behind.

This correction fires at most once while its marker survives, and is advisory:
say so and continue if the pipeline genuinely does not apply here."

  jq -n --arg reason "$reason" \
    --arg msg "Compound V: source changed with no run record — pipeline-bypass check" \
    '{decision: "block", reason: $reason, systemMessage: $msg}' 2>/dev/null || return 1
  return 0
}

# --- main -------------------------------------------------------------------
# All fallible logic lives here.  Its stdout is captured by the caller and
# DISCARDED unless it returned 0, so a half-finished run can never emit a
# partial or malformed block.
hook_main() {
  # Mechanism (b), second half: shed the caller's EXIT trap so this function's
  # own failure status is real and the caller can suppress its output.
  trap - EXIT

  # No jq → we can neither parse the event nor emit a well-formed decision.
  command -v jq >/dev/null 2>&1 || return 1

  local input
  input="$(cat)" || return 1
  [ -n "$input" ] || return 1

  # ---- EVENT GATE, FIRST, BEFORE ANY STATE READ OR WRITE -------------------
  # The harness converts a `Stop` registration to `SubagentStop` for subagents,
  # and Compound V dispatches subagents constantly.  Without this gate a
  # subagent shares the session id, passes session isolation, is continued
  # repeatedly, and burns the main session's counter.
  local ev
  ev="$(printf '%s' "$input" | jq -r '.hook_event_name // empty' 2>/dev/null)" || ev=""
  [ "$ev" = "Stop" ] || return 1

  local sid
  sid="$(printf '%s' "$input" | jq -r '.session_id // empty' 2>/dev/null)" || sid=""
  # No session id ⇒ no isolation ⇒ we would risk holding a session we do not own.
  [ -n "$sid" ] || return 1

  # Read it, log it, do NOT return on it.  See the header.
  local sha
  sha="$(printf '%s' "$input" | jq -r 'if .stop_hook_active == true then "true" else "false" end' 2>/dev/null)" || sha="false"
  _log "event=Stop session=${sid} stop_hook_active=${sha}"

  local cwdv root proj
  cwdv="$(printf '%s' "$input" | jq -r '.cwd // empty' 2>/dev/null)" || cwdv=""
  [ -n "$cwdv" ] || cwdv="$PWD"
  root="$(cd "$cwdv" 2>/dev/null && pwd -P)" || return 1
  [ -n "$root" ] || return 1
  proj="$(_project_root "$root")"
  [ -n "$proj" ] || return 1

  # ---- PRECEDENCE ----------------------------------------------------------
  # The goal rule first.  If it blocked, it already made the one permitted state
  # update and printed the one permitted response — the enforcement rule does
  # NOT run.  A goal-driven continuation is the system working as intended; a
  # pipeline correction on the same turn would be noise, and two blocks on one
  # event is undefined behaviour.
  if _goal_rule "$proj" "$sid" "$sha"; then
    return 0
  fi

  if _enforcement_rule "$proj" "$sid"; then
    return 0
  fi

  return 1
}

out="$(hook_main)"
rc=$?
if [ "$rc" -eq 0 ] && [ -n "${out:-}" ]; then
  printf '%s\n' "$out"
fi
exit 0
