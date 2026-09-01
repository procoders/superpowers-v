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
#   WHY (a) IS NOT REDUNDANT, stated precisely because the imprecise version is
#   easy to write.  A bash PARSE ERROR exits 2 — which is exactly the blocking
#   code — and bash parses a script INCREMENTALLY, so a malformed command only
#   bites when execution reaches it.  Probed on bash 3.2: a parse error BELOW the
#   `trap` line is caught by mechanism (b), because the trap is already
#   installed; a parse error ABOVE it, or anything that stops this file being
#   executed at all, exits 2 with no trap registered, and ONLY the `|| true`
#   registration stands between that and a wedged session.  Everything above the
#   trap is therefore comments on purpose.  Both directions are asserted in
#   tests/test-epic-goal-stop.sh, so the day someone moves that trap down the
#   file, the suite says so.
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
#   5. TRIAGE GATE — only if the goal rule did not block, and only when
#      `.enforcement.triage_gate == true` in .claude/compound-v.json:
#      non-exempt files changed && NO pre-eval record COVERS that diff
#        && this session's own marker unset ........ set marker, BLOCK
#      a bounded check that could not finish ....... RECORD it, then open
#   6. ENFORCEMENT — only if neither rule above blocked, and only when
#      `.enforcement.pipeline_bypass == true` in .claude/compound-v.json:
#      source changed && no run record && marker unset ... set marker, BLOCK
#   7. otherwise ................................... exit 0, silent
#
# WHY THE TRIAGE GATE SITS ABOVE THE BYPASS RULE.  Both are "you changed code
# without X", both are off by default, and only one response per event is
# permitted.  The triage gate is the more specific diagnosis, and its correction
# — `/v:triage` — is the first step of the correction the bypass rule asks for.
# Firing the general one first would send the reader to a pipeline that now
# refuses to run without the very record the triage gate is asking them to make.
# The bypass rule keeps its own relative position, so absorbing v2.18 changes
# nothing about how that rule already behaved.
#
# COVERAGE, NOT MERE EXISTENCE.  `/v:triage` COMMITS its record, so the record is
# never in the dirty changed-set — its presence has to be read off disk, and a
# matching `session_id` alone is not enough.  A record exempts a path only when
# it is the SAME SESSION and that path lies inside the record's own
# `declared_paths`.  Otherwise one triage of "change the README" would exempt a
# later, unrelated edit to this very file in the same session.  A record that is
# not DIRECT additionally has to be BOUND to a run: `run_id` set, and
# docs/superpowers/execution/<run_id>/state.json present.  SCOPED and FULL are
# promises to route through the pipeline; the run directory is the evidence that
# the promise was kept, and without it the record is an intention, not a cover.
#
# THE 1.5 SECOND BUDGET IS SHARED BY EVERY `Stop` HOOK, AND A TIMED-OUT `git` IS
# A SILENT NO-OP — the dead-guard shape this project has already shipped once
# (v2.14.1: a link guard that could not fail, 25 of 29 selftests never running).
# So each of this rule's two external calls runs under `_bounded_capture`, and a
# call that does not finish is RECORDED — `$TMPDIR/compound-v-stop-hook/
# triage-incomplete-<key>` plus a stderr line — before the rule fails open.  The
# gate still cannot block on evidence it does not have; what it must not do is
# look identical to a clean pass.  Budget: COMPOUND_V_TRIAGE_GATE_BUDGET_MS,
# default 800, split evenly between the two calls.
#
# WHAT THE TRIAGE GATE DOES NOT SEE, SAID PLAINLY.  It reads the WORKING TREE
# against HEAD.  Work already committed in this session is invisible to it, as it
# is to the bypass rule beside it.  This is a nudge at the end of a turn, not a
# proof that every change in a session was triaged; the mechanical authority is
# the validator's `--require-triage` on the dispatch path.
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

# --- bounded execution -------------------------------------------------------
# Every `Stop` hook on the machine shares ONE 1.5 second budget, and an external
# command that runs past it is cut off with no trace — a guard that cannot finish
# looks exactly like a guard that passed.  So the triage gate never calls an
# external command directly; it calls it through here.
#
# This is a poll rather than a wrapper around `timeout(1)`, because there is no
# `timeout` on a stock macOS box — probed on the maintainer's machine: neither
# `timeout` nor `gtimeout` is on PATH.  The child writes its exit status to a
# sentinel file as its LAST act and the parent polls for that file, never for the
# pid: a finished-but-unreaped child still answers `kill -0` and would read as
# "still running".
#
# Killing the poll's child does NOT reliably kill the command inside it — the
# subshell dies, the `git` under it can outlive us — so every call gets its OWN
# output file and unlinks it on the way out.  A survivor keeps writing into an
# unlinked inode that nothing will ever read; sharing one filename would instead
# let a timed-out call from a previous turn scribble into the next turn's answer.
#
# _bounded_capture <budget_ms> <path_prefix> <cmd...>
#   returns 0  → the command completed; its own exit status is in $_BC_RC and its
#                stdout is at $_BC_OUT, which the CALLER unlinks after reading
#   returns 1  → the budget expired; the child was killed; nothing survives
#   returns 2  → could not run bounded at all (no `sleep`); nothing survives
_BC_RC=""
_BC_OUT=""
_BC_N=0
_bounded_capture() {
  local ms="$1" pfx="$2"
  shift 2
  _BC_RC=""
  _BC_OUT=""
  command -v sleep >/dev/null 2>&1 || return 2

  _BC_N=$((_BC_N + 1))
  local out="${pfx}.$$.${_BC_N}" rcf waited=0 step=25 pid rc
  rcf="${out}.rc"
  rm -f "$out" "$rcf" 2>/dev/null
  : >"$out" 2>/dev/null || return 2

  # Job control stays OFF (no `set -m`), so bash prints no "Terminated" notice
  # for the child killed below — a timeout says exactly one thing on stderr, and
  # it is the line _record_triage_incomplete writes.
  { "$@" >"$out" 2>/dev/null; printf '%s' "$?" >"$rcf" 2>/dev/null; } &
  pid=$!

  while [ "$waited" -lt "$ms" ]; do
    # `-s`, not `-e`: the redirection creates the file before printf fills it.
    if [ -s "$rcf" ]; then
      rc="$(cat "$rcf" 2>/dev/null)"
      _is_uint "$rc" || rc=1
      rm -f "$rcf" 2>/dev/null
      _BC_RC="$rc"
      _BC_OUT="$out"
      return 0
    fi
    if ! sleep 0.025 2>/dev/null; then
      kill -TERM "$pid" 2>/dev/null
      wait "$pid" 2>/dev/null
      rm -f "$out" "$rcf" 2>/dev/null
      return 2
    fi
    waited=$((waited + step))
  done

  kill -TERM "$pid" 2>/dev/null
  wait "$pid" 2>/dev/null
  rm -f "$out" "$rcf" 2>/dev/null
  return 1
}

# --- rule 2: the triage gate (OFF by default) --------------------------------
# Fires when the turn is ending, non-exempt files have changed, and NO pre-eval
# record covers that diff.  Runs ONLY when the goal rule did not block.  Returns
# 0 having printed a block, or non-zero having printed nothing.

# One jq pass over every candidate record, emitting `tier<US>run_id<US>path` for
# each declared path of each record belonging to THIS session.  The separator is
# U+001F, not a tab: a tab is an IFS-WHITESPACE character, so bash `read` folds a
# run of them into ONE delimiter and an empty `run_id` would silently shift the
# path into the run_id slot -- every record would then cover nothing.
#
# `tier` is read from `.tier` when a producer supplies it, and otherwise mapped
# from `.decision`, which is the field the record schema actually carries today
# (FASTPATH_ELIGIBLE / SCOPED_PIPELINE / FULL_PIPELINE == DIRECT / SCOPED / FULL,
# spec §A1).  Anything unrecognised maps to "" and is therefore treated as
# non-DIRECT — the direction that demands MORE evidence, not less.
#
# A declared path containing the separator or a line break is DROPPED rather than
# escaped: this output is read back line by line, and a re-escaped path no longer
# equals the path git reports.  Dropping narrows the declared set; keeping it
# would widen it, and only one of those two mistakes is safe.
# shellcheck disable=SC2016  # $tier/$rid are jq variables, not shell ones.
_TRIAGE_JQ='
[ .[]
  | select(type == "object")
  | select(((.session_id // "") | tostring) == $sid)
  | (if ((.tier // "") | tostring | length) > 0
     then ((.tier | tostring) | ascii_upcase)
     else ((.decision // "") | tostring
           | if   . == "FASTPATH_ELIGIBLE" then "DIRECT"
             elif . == "SCOPED_PIPELINE"   then "SCOPED"
             elif . == "FULL_PIPELINE"     then "FULL"
             else "" end)
     end) as $tier
  | (((.run_id // "") | tostring)) as $rid
  | (.declared_paths // [])
  | select(type == "array")
  | .[]
  | select(type == "string")
  | select(length > 0)
  | select((test("[\u001f\n\r]")) | not)
  | ([$tier, $rid, .] | join("\u001f"))
] | .[]
'

# Set by _triage_rule for the two helpers below, so neither has to be handed a
# multi-kilobyte string on every call.
_TR_PROJ=""
_TR_RECS=""

# A bounded check that quietly does nothing is the exact failure this rule was
# written around, so incompletion is WRITTEN DOWN: appended to a store file and
# said once on stderr.  It is deliberately NOT the once-per-session marker — no
# block happened, so the next turn gets to try again.
_record_triage_incomplete() {
  local f="$1" why="$2" ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null)" || ts=""
  [ -n "$ts" ] || ts="unknown-time"
  printf '%s\ttriage-gate-incomplete\t%s\n' "$ts" "$why" >>"$f" 2>/dev/null
  _log "triage gate INCOMPLETE — ${why}. Failing open and recording it in ${f}; a bounded check that could not run is not a pass."
}

# _path_covered <changed_path> <declared_entry>
# Exact match, a directory prefix (the declared entry ends in `/`), or a glob
# (the declared entry contains `*`).  A bare `hooks` does NOT cover `hooks/x.sh`
# — the record has to say `hooks/` or `hooks/**`.  Widening a declared set by
# accident is the one direction this must not fail in.
_path_covered() {
  local p="$1" d="$2"
  [ -n "$d" ] || return 1
  [ "$p" = "$d" ] && return 0
  case "$d" in
    */) case "$p" in "$d"*) return 0 ;; esac ;;
  esac
  # shellcheck disable=SC2254  # $d is unquoted ON PURPOSE: this is the one place
  # a declared entry is a pattern rather than a literal.
  case "$d" in
    *\**) case "$p" in $d) return 0 ;; esac ;;
  esac
  return 1
}

# _covered_by_records <changed_path> — 0 when some record in $_TR_RECS covers it.
_covered_by_records() {
  local p="$1" t rid d oldifs="$IFS" found=1
  while IFS=$'\037' read -r t rid d; do
    [ -n "$d" ] || continue
    if [ "$t" != "DIRECT" ]; then
      # SCOPED / FULL / unrecognised: an intention, not a cover, until the run
      # directory it promised actually exists.  `run_id` is joined into a path,
      # so it is constrained to one harmless segment first.
      case "$rid" in '' | */* | *..*) continue ;; esac
      [ -f "${_TR_PROJ}/docs/superpowers/execution/${rid}/state.json" ] || continue
    fi
    if _path_covered "$p" "$d"; then found=0; break; fi
  done <<EOF
${_TR_RECS}
EOF
  IFS="$oldifs"
  return "$found"
}

_triage_rule() {
  local proj="$1" sid="$2"
  _TR_PROJ="$proj"
  _TR_RECS=""

  local cfg="${proj}/.claude/compound-v.json"
  [ -f "$cfg" ] || return 1
  local on
  on="$(jq -r '.enforcement.triage_gate // false' "$cfg" 2>/dev/null)" || on="false"
  # OFF BY DEFAULT, and the default is the safe one: a false positive here does
  # not fail a build, it holds a stranger's turn open.
  [ "$on" = "true" ] || return 1

  command -v git >/dev/null 2>&1 || return 1

  local store key marker inc
  store="$(_store_dir)"
  key="$(_digest "${proj}|${sid}")" || return 1
  [ -n "$key" ] || return 1
  marker="${store}/triage-${key}"
  inc="${store}/triage-incomplete-${key}"
  # At most once per session, on THIS rule's own marker.  Never on
  # `stop_hook_active`: that is a consecutive-block counter, not a session flag,
  # and CLAUDE_CODE_STOP_HOOK_BLOCK_CAP (default 8) lets the harness override the
  # hook outright — neither is a bound we get to own.
  [ -e "$marker" ] && return 1

  mkdir -p "$store" 2>/dev/null || return 1

  local budget half
  budget="${COMPOUND_V_TRIAGE_GATE_BUDGET_MS:-800}"
  _is_uint "$budget" && [ "$budget" -ge 100 ] && [ "$budget" -le 5000 ] || budget=800
  half=$((budget / 2))

  # A PREFIX, not a filename: _bounded_capture appends a per-call suffix and
  # unlinks the file itself on every path, so nothing accumulates in the store
  # and no two calls can ever read each other's output.
  local tmpo="${store}/triage-${key}.work"

  # ---- the changed set, bounded --------------------------------------------
  # Tracked modifications UNIONED with untracked-but-not-ignored files, in ONE
  # git process rather than two, because the budget is shared.  A brand new
  # source file is the commonest shape of untriaged work, and git has already
  # dropped everything .gitignore covers, so this is "in the repo and not
  # deliberately ignored" rather than "already in the index".
  local rc chg=""
  _bounded_capture "$half" "$tmpo" \
    git -C "$proj" -c core.quotePath=false \
      status --porcelain --untracked-files=all --no-renames
  rc=$?
  if [ "$rc" -eq 1 ]; then
    _record_triage_incomplete "$inc" "git status did not finish within ${half}ms"
    return 1
  fi
  if [ "$rc" -ne 0 ] || [ "${_BC_RC:-1}" != "0" ]; then
    _record_triage_incomplete "$inc" "git status could not run (bounded rc=${rc}, git rc=${_BC_RC:-?})"
    return 1
  fi
  # porcelain v1: two status columns, a space, then the path.  `--no-renames`
  # keeps a rename from arriving as `old -> new` in one field, and
  # `core.quotePath=false` stops a non-ASCII path arriving octal-escaped — an
  # escaped path would match no declared entry and read as uncovered.
  chg="$(sed -e 's/^...//' -e 's/^"\(.*\)"$/\1/' "$_BC_OUT" 2>/dev/null | sed '/^$/d' | sort -u)" || chg=""
  rm -f "$_BC_OUT" 2>/dev/null

  # ---- the exempt set ------------------------------------------------------
  # The pipeline's own paper trail — which is where the triage record itself
  # lands — and this hook's store when TMPDIR happens to point inside the repo.
  local store_rel="" changed
  case "$store" in
    "$proj"/*) store_rel="${store#"$proj"/}" ;;
  esac
  changed="$(printf '%s\n' "$chg" | grep -v '^docs/superpowers/' 2>/dev/null || true)"
  if [ -n "$store_rel" ]; then
    changed="$(printf '%s\n' "$changed" | grep -v "^${store_rel}/" 2>/dev/null || true)"
  fi
  changed="$(printf '%s\n' "$changed" | sed '/^$/d')" || changed=""
  [ -n "$changed" ] || return 1

  # ---- the records, bounded ------------------------------------------------
  local pdir="${proj}/docs/superpowers/pre-eval"
  if [ -d "$pdir" ]; then
    local files n oldifs
    # `find`, not a glob: an unmatched glob would reach jq as a literal filename.
    files="$(find "$pdir" -maxdepth 1 -type f -name '*.json' 2>/dev/null | sort)" || files=""
    files="$(printf '%s\n' "$files" | sed '/^$/d')" || files=""
    if [ -n "$files" ]; then
      n="$(printf '%s\n' "$files" | wc -l | tr -d ' ')" || n=0
      if [ "${n:-0}" -gt 500 ]; then
        _record_triage_incomplete "$inc" "${n} pre-eval records is more than can be scanned within ${half}ms"
        return 1
      fi
      oldifs="$IFS"
      IFS=$'\n'
      # shellcheck disable=SC2086
      set -- $files
      IFS="$oldifs"
      _bounded_capture "$half" "$tmpo" jq -r -s --arg sid "$sid" "$_TRIAGE_JQ" "$@"
      rc=$?
      if [ "$rc" -eq 1 ]; then
        _record_triage_incomplete "$inc" "the pre-eval record scan did not finish within ${half}ms"
        return 1
      fi
      if [ "$rc" -ne 0 ] || [ "${_BC_RC:-1}" != "0" ]; then
        _record_triage_incomplete "$inc" "the pre-eval record scan failed (bounded rc=${rc}, jq rc=${_BC_RC:-?}) — a record we could not read is not an exemption"
        return 1
      fi
      _TR_RECS="$(cat "$_BC_OUT" 2>/dev/null)" || _TR_RECS=""
      rm -f "$_BC_OUT" 2>/dev/null
    fi
  fi

  # ---- coverage ------------------------------------------------------------
  local p uncovered="" nunc=0
  while IFS= read -r p; do
    [ -n "$p" ] || continue
    if ! _covered_by_records "$p"; then
      nunc=$((nunc + 1))
      if [ "$nunc" -le 8 ]; then uncovered="${uncovered}
  ${p}"; fi
    fi
  done <<EOF
${changed}
EOF
  [ "$nunc" -gt 0 ] || return 1
  if [ "$nunc" -gt 8 ]; then uncovered="${uncovered}
  … and $((nunc - 8)) more"; fi

  # Marker BEFORE the block is emitted: a correction we could not bound is a
  # correction we do not make.
  : >"$marker" 2>/dev/null || return 1

  _log "triage gate: ${nunc} changed path(s) not covered by any pre-eval record for session ${sid}"

  local reason
  reason="Compound V — this turn changed files that no triage record covers.

  uncovered changed paths (${nunc}):${uncovered}

A pre-eval record covers a path only when it was written for THIS session and
that path lies inside its own declared_paths — and, for a SCOPED or FULL record,
only when the run directory it promised actually exists. Existence is not
coverage: a triage of one file must not license an edit to another.

Before finishing, run:
  /v:triage <what this change is>

It classifies the change, writes and commits the record, and prints the tier
that decided it. DIRECT means implement in place and run the floor; SCOPED and
FULL route through /v:orchestrate and /v:dispatch.

This gate reads the working tree against HEAD, so it cannot see work already
committed this turn. It fires at most once per session and is advisory: say so
and continue if triage genuinely does not apply here. Turn it off by setting
enforcement.triage_gate to false in .claude/compound-v.json."

  jq -n --arg reason "$reason" \
    --arg msg "Compound V: ${nunc} changed path(s) with no triage record covering them" \
    '{decision: "block", reason: $reason, systemMessage: $msg}' 2>/dev/null || return 1
  return 0
}

# --- rule 3: pipeline-bypass enforcement (OFF by default) -------------------
# Runs ONLY when neither rule above blocked.  Returns 0 having printed a block,
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
  # update and printed the one permitted response — NEITHER correction rule
  # runs.  A goal-driven continuation is the system working as intended; a
  # pipeline correction on the same turn would be noise, and two blocks on one
  # event is undefined behaviour.
  if _goal_rule "$proj" "$sid" "$sha"; then
    return 0
  fi

  # Then the triage gate, then the older bypass rule.  Both are "you changed
  # code without X", both are off by default, and only ONE response per event is
  # permitted — so the more specific diagnosis goes first: `/v:triage` is the
  # first step of the correction the bypass rule asks for, and the pipeline it
  # points at now refuses to run without that record.
  if _triage_rule "$proj" "$sid"; then
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
