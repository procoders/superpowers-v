#!/usr/bin/env bash
# Compound V — Stop hook: the triage gate and the off-by-default pipeline-bypass
# correction.  v3.4.
#
# The armed-epic-goal rule that used to run first in this file was REMOVED in
# 3.4.0, because Claude Code's own `/goal` covers it: the harness holds the
# session open against a user-approved condition and evaluates it itself, so a
# second, home-grown continuation engine in the highest-blast-radius file of
# this plugin bought nothing.  `commands/v-epic.md` §0d now offers that native
# goal instead of arming one here.
#
# ┌──────────────────────────────────────────────────────────────────────────┐
# │ HIGHEST BLAST RADIUS IN THIS PLUGIN.  This file runs at the end of EVERY  │
# │ turn of EVERY Claude Code session of every user who installs Compound V.  │
# │ A bug here does not fail a build — it wedges a stranger's session so they │
# │ cannot end their turn.  Read the invariant below before editing.          │
# └──────────────────────────────────────────────────────────────────────────┘
#
# THE INVARIANT — A BLOCK IS ONLY EVER VALID JSON, NEVER AN EXIT CODE.
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
# THIS HOOK WRITES NOTHING OUTSIDE ITS OWN STORE.  The once-per-session markers
# and the incomplete-check ledger live under the OS temp dir; no file in the
# repository is created, edited or committed by this script on any path.
#
# DECISION TABLE (evaluated top to bottom; exactly ONE state update and exactly
# ONE JSON response per event):
#
#   1. jq / stdin unusable ......................... exit 0, silent
#   2. hook_event_name != "Stop" ................... exit 0, silent   [GATE FIRST]
#        SubagentStop / StopFailure / unknown / missing all land here.
#   3. session_id empty ............................ exit 0 (cannot isolate)
#   4. THE TRIAGE GATE — only when `.enforcement.triage_gate` in
#      .claude/compound-v.json — ON when absent as of 3.2.0; set it to `false`
#      to opt out:
#      non-exempt files changed && NO pre-eval record COVERS that diff
#        && this session's own marker unset ........ set marker, BLOCK
#      a bounded check that could not finish ....... RECORD it, then open
#   5. THE BYPASS RULE — only if the triage gate did not block, and only when
#      `.enforcement.pipeline_bypass == true` in .claude/compound-v.json:
#      source changed && no run record && marker unset ... set marker, BLOCK
#   6. otherwise ................................... exit 0, silent
#
# WHY THE TRIAGE GATE SITS ABOVE THE BYPASS RULE.  Both are "you changed code
# without X". The triage gate is ON by default as of 3.2.0 (an explicit
# `enforcement.triage_gate: false` opts out); the bypass rule is still off. Only
# one response per event is
# permitted.  The triage gate is the more specific diagnosis, and its correction
# — `/v:triage` — is the first step of the correction the bypass rule asks for.
# Firing the general one first would send the reader to a pipeline that now
# refuses to run without the very record the triage gate is asking them to make.
# The bypass rule keeps its own relative position, so its behaviour is unchanged
# from the release that introduced it.
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
if [ "${CV_HEADLESS_CLASSIFY:-}" = "1" ]; then exit 0; fi  # finding 131: never fire inside the headless classifier

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

_is_uint() { case "${1:-}" in '' | *[!0-9]*) return 1 ;; *) return 0 ;; esac; }

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

# --- rule 1: the triage gate (ON by default as of 3.2.0) ---------------------
# Fires when the turn is ending, non-exempt files have changed, and NO pre-eval
# record covers that diff.  It is the first rule evaluated.  Returns 0 having
# printed a block, or non-zero having printed nothing.

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
  # ON BY DEFAULT as of 3.2.0. It shipped off, on a blast-radius claim this
  # project made about itself and never checked — "it would block turn-end in
  # every session of every install, including sessions that never touched
  # Compound V". A live probe on 2026-09-02 says otherwise, and the four cases
  # are pinned in tests/test-epic-goal-stop.sh:
  #
  #   * no `.claude/compound-v.json`            -> silent. A project that never
  #     ran /v:init is untouched, full stop. That is most installs.
  #   * config present, no uncovered change     -> silent.
  #   * `docs/superpowers/**` and this hook's own store are exempt.
  #   * it fires AT MOST ONCE per session, on its own marker, and the marker is
  #     written BEFORE the block is emitted, so it cannot loop.
  #   * the whole rule is bounded (default 800 ms) and FAILS OPEN on every
  #     timeout, unreadable record, or git error.
  #
  # So the real population is: a repository that deliberately initialised
  # Compound V, once per session, when the tree carries code changes no triage
  # record covers. That is exactly the failure this plugin exists to catch — the
  # user complaint that started the 3.0 line was an agent skipping the pipeline
  # — and leaving the one mechanism that catches it switched off was not caution,
  # it was the mechanism-with-no-caller defect wearing a config key.
  #
  # OPT OUT with `"enforcement": {"triage_gate": false}` in
  # .claude/compound-v.json. Absent means ON.
  #
  # NOT `// true`. jq's `//` is the ALTERNATIVE operator: it yields the right
  # side when the left is `null` OR `false`, so `.enforcement.triage_gate // true`
  # turns an explicit `"triage_gate": false` back into `true` and the opt-out this
  # very block message documents would not work. Caught by its own test on the
  # first run of the flip. Only a literal `false` (boolean or the string) opts out.
  on="$(jq -r 'if (.enforcement.triage_gate == false or .enforcement.triage_gate == "false")
               then "false" else "true" end' "$cfg" 2>/dev/null)" || on="true"
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

# --- rule 2: the bypass rule — pipeline-bypass enforcement (OFF by default) --
# Runs ONLY when the triage gate did not block.  Returns 0 having printed a
# block, or non-zero having printed nothing.
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
  # where this hook's own markers would otherwise count as "source changed").
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
  # subagent shares the main session's id, so it would consume that session's
  # once-per-session marker and correct the wrong party.
  local ev
  ev="$(printf '%s' "$input" | jq -r '.hook_event_name // empty' 2>/dev/null)" || ev=""
  [ "$ev" = "Stop" ] || return 1

  local sid
  sid="$(printf '%s' "$input" | jq -r '.session_id // empty' 2>/dev/null)" || sid=""
  # No session id ⇒ no isolation ⇒ we would risk holding a session we do not own.
  [ -n "$sid" ] || return 1

  # Read and logged for diagnostics, never returned on.  The flag is set on the
  # first block of a turn and never cleared, so returning on it would cap every
  # rule below at exactly one block per session while a synthetic-stdin selftest
  # still passed.  Each rule bounds itself with its own marker instead.
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
  # The triage gate, then the older bypass rule.  Both are "you changed code
  # without X". The triage gate is ON by default as of 3.2.0; the bypass rule is
  # still off. Only ONE response per event is permitted — so the more specific
  # diagnosis goes first: `/v:triage` is the first step of the correction the
  # bypass rule asks for, and the pipeline it points at now refuses to run
  # without that record.  If the gate blocked, it already made the one permitted
  # state update and printed the one permitted response, and the bypass rule
  # does not run.
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
