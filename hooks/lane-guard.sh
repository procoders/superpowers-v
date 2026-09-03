#!/usr/bin/env bash
# Compound V — PreToolUse lane guard (Feature E, v3.0)
#
# WHAT THIS IS
# ------------
# A native `PreToolUse` DENY that refuses a write outside the acting job's
# `write_allowed` lane BEFORE the bytes land, instead of noticing afterwards.
#
# WHAT THIS IS NOT
# ----------------
# It is NOT a replacement for `scripts/compound-v-scope-check.py`. That script
# is git-derived, sees every path a job actually touched no matter how it was
# touched, and REMAINS THE AUTHORITY: a job whose git verdict is BLOCKED is
# still BLOCKED, and the D1 integration postcondition still decides what enters
# the tree. This hook is DEFENCE IN DEPTH — a floor under that verdict.
#
# The honest reason for the caveat is in `bash_targets()` below: for the `Bash`
# matcher this hook has to INSPECT A SHELL COMMAND STRING, and shell command
# inspection is a parsing problem with unbounded evasions (`eval`, an
# interpreter one-liner, a variable holding the path, a build step, a script
# that writes on the guard's behalf). Every one of those walks straight past
# this hook and straight into the git gate. A deny that can be walked around is
# a supplement, never a replacement — see the spec's Feature E / E2.
#
# WHY IT MATCHES `Bash` AT ALL
# ----------------------------
# The 1D live probe (commit 0982ce0) established that a `Write|Edit`-only
# matcher is decorative: this environment actively nudges agents toward `cat`,
# `sed` and heredocs over the Write tool, and none of those reach a Write|Edit
# matcher. So `Bash` is matched too, on the understanding above.
#
# FAIL-OPEN CONTRACT
# ------------------
# A false deny inside a long autonomous run is far more expensive than a missed
# write the git gate catches anyway. Therefore: ANY uncertainty allows.
#   * unparseable stdin                 -> allow, log
#   * a Bash command whose quoting the
#     tokenizer cannot parse            -> allow, log
#   * no lane map / job unresolvable    -> allow, log   (the normal case for an
#                                         ordinary human session)
#   * an ISOLATED AGENT unresolved
#     against a LIVE lane map           -> allow, log, record one deduplicated
#                                         line in the run dir, AND say so once
#                                         in additionalContext -- see UNRESOLVED
#                                         IDENTITY below
#   * manifest missing or malformed     -> allow, log, AND say so in
#                                         additionalContext (the guard was
#                                         supposed to be active and could not be)
#   * a path this hook cannot resolve   -> allow, log
#   * the interpreter itself crashing   -> allow (the wrapper below discards any
#                                         non-JSON output and exits 0)
#   * an interpreter PROBE that runs
#     out of its budget                 -> allow, log, say so once, and STOP
#                                         probing (eighth pass, H3)
#   * the private bytecode-cache dir
#     cannot be created                 -> allow, log, say so, and load NOTHING
#                                         (eighth pass, H2)
# Only a POSITIVELY IDENTIFIED, fully resolved, out-of-lane path denies.
#
# COST
# ----
# PreToolUse hooks share a tight time budget, so every path here is bounded: at
# most 8 run directories are inspected, resolution stops at the first match, and
# the manifest is only parsed AFTER a job has been resolved.
#
# EVERY EXTERNAL PROCESS IS BOUNDED TOO, as of the eighth pass (H3): an
# interpreter probe gets CV_PROBE_TIMEOUT (0.9 s, sub-second on purpose against a
# ~25 ms ordinary probe), a delegated manifest parse gets _PARSE_BUDGET_S (5 s),
# and the registration in hooks/hooks.json carries `timeout: 10` so the harness
# has a bound of its own even if this file grows a path that forgets one. A probe
# that runs out of budget stops the ladder, says so once, and allows.
#
# THE LOG IS BOUNDED IN THE OTHER SENSE TOO (eighth pass, item 6). The
# interpreter line names the chosen interpreter on every path, which is the only
# way the viability ladder is observable — but it is written ONCE PER SESSION,
# not once per call, keyed by a marker beside the log. MEASURED, 50 invocations
# in one session on this machine (2026-09-03):
#   unresolved path (an ordinary session)   100 lines before -> 51 after
#                                           (50 interpreter lines -> 1; the 50
#                                           `ALLOW (job unresolved)` lines stay)
#   resolved, in-lane allow                  50 lines before ->  1 after
# The transition is still logged: a different interpreter, or a candidate newly
# passed over, is a different message and reappears.
#
# RE-MEASURED 2026-09-03 (seventh review pass) on macOS 26.5.2 / arm64 with
# /usr/bin/python3 3.9.6, 50 invocations per cell, TWO qualifying rounds, against
# a sandbox project carrying copies of this repository's 48 run directories:
#
#   bare interpreter start (`-c pass`)             25.6 / 25.9 ms   the floor
#   one viability probe (`import yaml`, alone)     38.3 / 38.5 ms
#   A  unresolved, 1st candidate has PyYAML       148.9 / 150.4 ms  ONE probe
#   C  unresolved, NO candidate has PyYAML        199.1 / 204.0 ms  THREE probes
#   R  resolved, write in lane (live lane map)    244.1 / 235.0 ms  ONE probe
#
# THE POPULATIONS, NAMED, because the ambient cost is not one number:
#   * ~149 ms -- the machine whose FIRST candidate imports yaml. This is the
#     ordinary macOS box (/usr/bin/python3 ships PyYAML) and it pays exactly ONE
#     probe. It is also the only path a session that never dispatches will take.
#   * ~200 ms -- the machine where NO candidate imports yaml: two `import yaml`
#     probes plus one `-c pass` probe, three in all.
#   * ~175 ms -- the machine whose SECOND candidate imports yaml: two probes.
#     DERIVED, not measured end to end (A plus one in-loop probe, whose marginal
#     cost here is ~25 ms -- the 38 ms row above includes an `env` exec that the
#     in-loop probe does not pay). Said plainly rather than published as if it
#     had been timed.
#
# WHAT THE SEVENTH PASS ACTUALLY CHANGED, AND WHAT IT DID NOT. Splitting the
# `-c pass` probe out of the `import yaml` loop below removes ONE probe from the
# second-candidate population (3 -> 2) and changes NOTHING for the other two: a
# healthy machine already broke out of the loop on its first candidate, and a
# machine with no PyYAML anywhere still pays three. The honest claim is "one
# probe on the healthy path", not "one probe saved on the healthy path".
#
# ON THE 167/245 ms THIS HEADER PUBLISHED ON 2026-09-02: not withdrawn as wrong,
# superseded as noisy. Today's rounds put the same cells at ~149 and ~240 by the
# same protocol, and no code between them touches either path. That gap is
# round-to-round variation on a shared machine, which is the standing reason this
# file publishes a method and a floor rather than a single number. Two things did
# get fixed in the measuring, and both inflate a figure silently:
#   * MEASURE THE UNRESOLVED PATH SOMEWHERE UNRESOLVED. Driving the loop from a
#     checkout that a LIVE run's lane map claims measures the RESOLVED path and
#     calls it unresolved -- 247 ms in the first attempt at this round, which is
#     cell R, not cell A. Set CV_LANE_GUARD_LOG and read back which path you hit.
#   * TAKE THE FLOOR IN THE SAME ROUND AND DISCARD ABOVE ~31 ms. A machine
#     sharing its cores with a parallel dogfood run doubles every number here.
#     Both rounds above opened at 25.6/25.9 ms and closed at 26.2/26.3 ms.
#
# WHERE THE ~149 ms GOES, roughly: ~26 ms interpreter floor + ~59 ms bytecode
# cache-miss tax + ~25 ms viability probe + the rest in bash, payload compile and
# run-directory resolution. A resolved call adds the manifest parse and the
# matcher import on top, which is the whole of the A -> R gap; the DENY costs the
# same as the resolved allow, because the verdict has never been the expensive
# part.
#
# THE CACHE-MISS TAX IS OURS AND IT IS DELIBERATE, and it is worth knowing before
# anyone "optimises" it away: PYTHONPYCACHEPREFIX moves the bytecode-cache LOOKUP
# into a private per-invocation directory while PYTHONDONTWRITEBYTECODE forbids
# populating it, so EVERY stdlib module is recompiled from source on every single
# invocation. Measured directly, `-c 'import json,os,re,shlex,sys,time'`: 31 ms
# plain, 32 ms with PYTHONDONTWRITEBYTECODE alone, 35 ms with the prefix alone,
# 90 ms with both. That ~59 ms is the price of refusing to execute a planted
# .pyc. The 47-81 ms this file published on 2026-09-01 predates it and stays
# withdrawn.
#
# To reproduce: build a sandbox project (copy `docs/superpowers/execution/` into
# a temp dir), drive the hook with a synthetic PreToolUse payload whose `cwd` is
# that sandbox, and time 50 invocations. Take the bare-interpreter floor in the
# same round. `tests/test-lane-guard.sh` builds the shape the resolved cell needs.
#
# A result cache was considered and rejected: it would save the resolution and
# parse and buy a cache-invalidation bug in the one component whose failure mode
# is a false deny.
#
# The quote-aware tokenizer and the unresolved-identity record made this source
# ~250 lines longer, and the source is COMPILED ON EVERY INVOCATION (it is
# passed to `python3 -c`, and PYTHONDONTWRITEBYTECODE deliberately forbids the
# .pyc cache that would amortise it). Measured on a DIFFERENT machine from the
# figures above, so read the delta and not the absolutes -- same harness, 10
# runs, three repeats, on the unresolved path every ordinary tool call takes:
#   before  41.5 / 43.6 / 43.9 ms      after  48.6 / 49.3 / 51.4 ms
# i.e. roughly +6 ms ambient. That is the price of the fix, stated rather than
# hidden: the shipped segmentation allowed `sed -i 's/a/b/; s/c/d/' FILE`
# outright, and no amount of speed makes a guard that misses worth keeping.
#
# CARVE-OUT: EXTERNAL WORKERS
# ---------------------------
# A command invoking `scripts/compound-v-run-*-worker.sh` is NEVER denied
# (spec D5.2). What that OS process writes happens in its own worktree, in a
# separate process, outside any hook this session controls; it is covered by the
# worker script's own scope-gate call plus the D1 integration postcondition.
# Denying it here would only break the second family, never police it.
#
# REGISTRATION
# ------------
# This job does NOT register the hook — `hooks/hooks.json` belongs to task-16.
# The intended registration is a `PreToolUse` entry with matcher
# `Write|Edit|MultiEdit|NotebookEdit|Bash`.
#
# LANE REGISTRATION IS NOT ENFORCED, AND THIS HOOK CANNOT ENFORCE IT
# ------------------------------------------------------------------
# A job binds itself to its worktree by running `register-lane`, which the
# implementer's prompt calls its "FIRST COMMAND, BEFORE ANY OTHER TOOL CALL".
# That is prose. Nothing makes it happen, and a worker that writes first is
# allowed because no map entry exists yet. This hook cannot close that from its
# side — it sees whatever is on disk when PreToolUse fires, and denying until a
# map appears would deny the registration command itself. What it does instead
# is refuse to let the failure be invisible: see UNRESOLVED IDENTITY below.
#
# LANE MAP CONTRACT (how a tool call becomes a job id)
# ----------------------------------------------------
# Resolution order, first hit wins:
#   1. $CV_LANE_MAP           — explicit path to a lane-map JSON (tests, and any
#                               dispatcher that wants to be explicit)
#   2. <project>/docs/superpowers/execution/<run-id>/lane-map.json
#   3. <project>/docs/superpowers/execution/<run-id>/state.json, whose
#      jobs.<id> may carry "agent_id" (or "agent_ids": [...]) and "worktree"
# Lane-map shape:
#   {"run_id": "...", "manifest": "<path, default <rundir>/manifest.yaml>",
#    "agents":    {"<agent_id>": "<job-id>"},
#    "worktrees": {"<abs worktree path>": "<job-id>"}}
# Within a run dir, `agent_id` is tried first (the probe proved the payload
# carries it); the `cwd`->worktree map is the fallback, because the probe also
# showed `cwd` IS the agent's worktree (`.claude/worktrees/<runId>-<n>`).
#
# The glob matcher is IMPORTED from scripts/compound-v-scope-check.py, never
# reimplemented: two glob engines that disagree is a bug factory, and that one
# has reproduced-exploit selftests behind it. The YAML loader is imported from
# scripts/compound-v-validate-manifest.py for the same reason.
#
# READING THAT MANIFEST NEEDS PyYAML, AND THIS HOOK NOW ASKS FOR IT
# ----------------------------------------------------------------
# Without PyYAML the loader falls back to an embedded SUBSET parser, and until
# the fifth review pass (2026-09-02) that parser could not read the shape
# `yaml.safe_dump` writes -- a folded scalar, or a block sequence at its parent
# key's own indent. The parse stopped at the first one and every later key,
# `jobs:` included, was dropped. Pointed at a real run's manifest by a
# `command -v python3` that happened to be a Homebrew build with no PyYAML, this
# guard therefore read a manifest with NO JOBS, resolved no lane, and failed
# open on every out-of-lane write. Both halves are fixed: the subset parser
# reads safe_dump's output and raises instead of truncating, and the interpreter
# this hook runs under is CHOSEN BY ASKING (`<py> -c 'import yaml'`) rather than
# by ordering guesses -- see the viability ladder below, which also says what
# that costs. `load_manifest_data` keeps its own delegation as a second line:
# the ladder settles which interpreter runs, the payload can still hand a
# manifest to a yaml-capable candidate, and it says by path when it does.
#
# Measured over all 47 manifests under docs/superpowers/execution/ (2026-09-02):
# both parsers read every one, and the ONLY field they disagree on anywhere is
# `jobs[].body`, the block scalars the subset parser flattens. With `body` set
# aside the jobs lists are identical 47/47, `write_allowed` included -- which is
# why the fallback is survivable, and not why it is acceptable as a default.
#
# ENV
#   CV_LANE_MAP        explicit lane-map JSON (overrides discovery)
#   CV_PROJECT_DIR     project root override (else CLAUDE_PROJECT_DIR, else
#                      derived from the payload cwd)
#   CV_SCOPE_CHECK     path to compound-v-scope-check.py
#   CV_PROBE_TIMEOUT   seconds one interpreter probe may take (default 0.9).
#                      Sub-second by design: an ordinary probe answers in ~25 ms,
#                      and this bound exists for the interpreter that HANGS.
#   CV_LANE_GUARD_LOG  log file (default $TMPDIR/compound-v-lane-guard.log). Its
#                      DIRECTORY is also the hook's store: the once-per-session
#                      interpreter marker is written beside it.
#                      Defaults OUTSIDE the repo on purpose: a guard that logs
#                      into the worktree would create the very untracked file
#                      the scope gate then blocks the job for.
#   CV_VALIDATE_MANIFEST  path to compound-v-validate-manifest.py (the YAML
#                      loader)
#   CV_PYTHON          interpreter override. Honoured VERBATIM: when it is set
#                      it is the only candidate, and no PyYAML preference
#                      overrides it.
#   CV_PY_CANDIDATES   the interpreter paths, in probe order. Computed here and
#                      exported for the payload, which may hand the manifest
#                      read to one of them. It is ALSO honoured on input: when
#                      it is set, it IS the ordered candidate list (each entry
#                      still put through the viability ladder below) -- that is
#                      the seam the tests use to put a broken interpreter first.
#                      CV_PYTHON still wins over it.

# No `set -e`: this hook must never fail closed.
set -uo pipefail

HOOK_DIR="$(cd "$(dirname "$0")" && pwd -P 2>/dev/null || echo .)"
: "${CV_SCOPE_CHECK:=${CLAUDE_PLUGIN_ROOT:-$HOOK_DIR/..}/scripts/compound-v-scope-check.py}"
: "${CV_VALIDATE_MANIFEST:=${CLAUDE_PLUGIN_ROOT:-$HOOK_DIR/..}/scripts/compound-v-validate-manifest.py}"
export CV_SCOPE_CHECK CV_VALIDATE_MANIFEST

# --------------------------------------------------------------------------- #
# Logging, the fail-open notice, and the session marker store — all defined
# BEFORE the first thing that can fail, because every failure below has to be
# able to say so.
# --------------------------------------------------------------------------- #
_CV_LOG_FILE="${CV_LANE_GUARD_LOG:-${TMPDIR:-/tmp}/compound-v-lane-guard.log}"
# The hook's store: the directory the log lives in. In a session that is where
# TMPDIR points; a test that redirects the log gets the markers redirected with
# it, so a suite cleans up after itself instead of littering TMPDIR.
_CV_LOG_DIR="${_CV_LOG_FILE%/*}"
[ "$_CV_LOG_DIR" = "$_CV_LOG_FILE" ] && _CV_LOG_DIR="."

_cv_log() {
  # The payload's log file, resolved the same way it resolves it. Best effort:
  # a logging failure must never influence a decision.
  printf '%s\n' "$1" >>"$_CV_LOG_FILE" 2>/dev/null || true
}

# The fail-open notice, emitted from BASH, for the failures that happen before
# any interpreter runs. Same wording as the payload's `open_notice`, and it must
# stay JSON-safe: every caller below passes a literal message with no quote, no
# backslash and no newline in it, because nothing here escapes one.
_cv_notice() {
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"Compound V lane-guard FAILED OPEN: %s This write was NOT checked against the lane. The git-derived scope gate (scripts/compound-v-scope-check.py) is unaffected and remains the authority."}}\n' "$1"
}

# THE PAYLOAD IS READ HERE, not by the python payload, and the reason is the
# session id: the interpreter line below is logged ONCE PER SESSION rather than
# once per tool call, and only stdin carries the session. The bytes are handed
# to the payload verbatim on its own stdin further down.
CV_STDIN="$(cat 2>/dev/null)"

# Pure parameter expansion, no forks: this runs on every Write/Edit/Bash call and
# a `sed` here would cost more than the line it dedupes saves. It takes the FIRST
# "session_id" in the payload, which is the harness's own field; a tool argument
# that happens to contain that text would only key the marker differently, which
# costs one extra logged line and nothing else.
_cv_sid=""
case "$CV_STDIN" in
  *'"session_id"'*)
    _cv_sid="${CV_STDIN#*\"session_id\"}"
    _cv_sid="${_cv_sid#*:}"
    _cv_sid="${_cv_sid#*\"}"
    _cv_sid="${_cv_sid%%\"*}"
    ;;
esac
_cv_sid="${_cv_sid//[!A-Za-z0-9_.-]/_}"
[ -n "$_cv_sid" ] || _cv_sid="nosession"
[ "${#_cv_sid}" -le 128 ] || _cv_sid="${_cv_sid:0:128}"

# ONE INTERPRETER LINE PER SESSION, NOT PER TOOL CALL (eighth review pass,
# 2026-09-03). Naming the chosen interpreter on every path is what makes the
# ladder observable — see the log line below — but "every path" was implemented
# as "every call", and a busy session writes that identical line thousands of
# times, which buries the lines that mean something (a DENY, an unresolved
# identity) in it. The marker holds the last message logged for this session, so
# a repeat is skipped and a CHANGE (a different interpreter, a candidate newly
# passed over) is logged again — the transition is the part worth seeing.
_cv_log_once() {
  local _mk _prev
  _mk="$_CV_LOG_DIR/cv-lane-guard-interp.$_cv_sid"
  _prev=""
  if [ -f "$_mk" ]; then read -r _prev <"$_mk" 2>/dev/null || _prev=""; fi
  [ "$_prev" = "$1" ] && return 0
  _cv_log "$1"
  printf '%s\n' "$1" >"$_mk" 2>/dev/null || true
  return 0
}

# BOUNDED CAPTURE (eighth review pass, item H3, 2026-09-03). Every probe below
# runs a foreign executable — a wrapper script, a shim, a virtualenv launcher —
# and an executable that HANGS is not a hypothetical: a login-shell wrapper
# waiting on a lock, an interpreter on a stalled network mount. Unbounded, the
# probe holds a PreToolUse hook open for as long as it likes and the session
# stalls on a component whose entire contract is to never be the reason anything
# stalls.
#
# `timeout(1)` is NOT used: it is coreutils, absent from a stock macOS, and the
# fallback would have to be this anyway. A watchdog subshell costs one fork and,
# unlike a poll loop, adds NO latency to the ordinary probe that answers in
# ~25 ms — there is nothing to poll, `wait` returns the moment the probe exits.
# Both jobs are fully redirected: a background process still holding the hook's
# stdout would keep the harness waiting for EOF long after this script exited.
: "${CV_PROBE_TIMEOUT:=0.9}"
_cv_bounded() {
  # 0 = the command succeeded, 1..127 = it failed, 124 = it ran out of budget.
  "$@" >/dev/null 2>&1 </dev/null &
  local _pid=$!
  ( sleep "$CV_PROBE_TIMEOUT"; kill -9 "$_pid" ) >/dev/null 2>&1 </dev/null &
  local _wd=$!
  wait "$_pid" 2>/dev/null
  local _rc=$?
  kill "$_wd" >/dev/null 2>&1
  wait "$_wd" 2>/dev/null
  # A killed child reports 128+SIGNAL. Nothing here exits by signal for any
  # other reason, so that is the timeout.
  [ "$_rc" -ge 128 ] && return 124
  return "$_rc"
}

# WHY BOTH, and the second one is the load-bearing half (fourth review pass,
# item 3, 2026-09-02).
#
# WRITING: this hook runs on every Write/Edit/Bash call, and importing the
# matcher must not leave __pycache__/*.pyc next to the scripts. The scope gate
# forgives no path by extension, so a cache entry the guard itself dropped
# outside a job's lane would BLOCK the job it is guarding.
#
# READING: `PYTHONDONTWRITEBYTECODE=1` stops Python WRITING a cache; it does not
# stop it READING one. A forged unchecked hash-based `.pyc` planted at
# scripts/__pycache__/compound-v-scope-check.<tag>.pyc is never validated against
# its source, and `load_matcher` below would execute it — in this process, on
# every tool call — handing back an `is_allowed` that approves every out-of-lane
# write. `PYTHONPYCACHEPREFIX` moves both the lookup and the write to a private
# directory outside the tree, so the in-tree entry is never consulted. If that
# directory cannot be created we fall through WITHOUT it: this guard fails open
# by contract and must never refuse a session because a temp dir was missing.
#
# The directory is per-invocation and removed on exit; a fixed, predictable name
# would merely move the plantable location out of the repo, where the scope gate
# cannot see it at all. Nothing is ever written into it either — the export above
# is still in force — so even a hijacked directory only turns a cache lookup into
# a miss, and a miss loads the source, which is the outcome we want.
#
# IT IS ALSO, MEASURED, THE MOST EXPENSIVE LINE IN THIS FILE: a redirected
# lookup that is never populated recompiles every stdlib module from source on
# every invocation — 31 ms plain, 90 ms with both variables set. That is ~59 ms
# of the hook's ambient cost, and it is why the 47 ms this file used to publish
# stopped being true the day this landed. Worth paying; see COST above before
# changing it, and re-measure if you do.
#
# AND IF THE PREFIX CANNOT BE SET, NOTHING RUNS (eighth review pass, item H2,
# 2026-09-03). This used to fall through WITHOUT the redirection and carry on,
# which inverted the defence exactly when it was needed: the one machine where
# the private directory cannot be created is the one whose temp dir is full,
# unwritable or hostile, and the loaders below then execute whatever `.pyc` sits
# beside the matcher — in this process, on every tool call. Fail-open is still
# the contract, so this ALLOWS; it just refuses to allow while running the
# loader. The notice says which happened.
export PYTHONDONTWRITEBYTECODE=1
CV_PYCACHE_DIR="${TMPDIR:-/tmp}/cv-lane-guard-pycache.$$.${RANDOM:-0}"
if mkdir -p "$CV_PYCACHE_DIR" 2>/dev/null; then
  export PYTHONPYCACHEPREFIX="$CV_PYCACHE_DIR"
  # Single-quoted on purpose: the variable is never reassigned, so expanding it
  # at trap time is correct AND cannot be broken by a quote inside $TMPDIR.
  trap 'rm -rf -- "$CV_PYCACHE_DIR"' EXIT
else
  _cv_log "lane-guard: the private bytecode-cache directory $CV_PYCACHE_DIR \
could not be created, so an in-tree .pyc could be executed by the loaders this \
hook uses. NOTHING was loaded and this write was NOT checked against any lane. \
The git-derived scope gate (scripts/compound-v-scope-check.py) is unaffected \
and remains the authority."
  _cv_notice "its private bytecode-cache directory could not be created, so the \
matcher and the YAML loader were NOT imported (an in-tree .pyc beside either \
one would have been executed in this process)."
  exit 0
fi

# WHICH PYTHON IS A CORRECTNESS QUESTION, NOT A TASTE ONE (fifth review pass,
# 2026-09-02; the pick is VIABILITY-CHECKED as of the sixth, same day).
#
# This hook reads the acting job's lane out of a YAML manifest. With PyYAML the
# read is exact; without it the repo's embedded SUBSET parser runs, and a subset
# parser is defined by what it cannot read. On the machine this was found on,
# `command -v python3` resolved to a Homebrew 3.14 with NO PyYAML while
# /usr/bin/python3 (which ships it on macOS) sat right beside it — so the guard
# picked the one interpreter that could not read the manifest it was pointed at,
# parsed no jobs, and FAILED OPEN on every out-of-lane write of a real run.
#
# The fifth pass answered that by ORDERING the candidates: take the first path
# that is executable, and leave `import yaml` to be discovered later, inside the
# payload. Two things an ordering cannot decide:
#   * `-x` IS NOT "CAN RUN". A wrapper script, a stale shim, a virtualenv
#     interpreter whose framework was upgraded out from under it — all
#     executable, all exit non-zero on anything. Picked as THE interpreter, the
#     payload never runs, the wrapper below discards the empty output, and the
#     hook produces NO DECISION AT ALL: a silent no-op indistinguishable from an
#     allow, in the component whose entire job is to not be silent.
#   * an ordering is a GUESS about which path has PyYAML. The property is cheap
#     to ask for, and asking is not a guess.
#
# So the pick is a VIABILITY LADDER, resolved here, before anything else runs:
#   1. the first candidate for which `<py> -c 'import yaml'` exits 0;
#   2. failing that, the first for which `<py> -c pass` exits 0 — logged BY
#      PATH with its missing PyYAML named, because the manifest read is then a
#      delegated candidate's or the subset parser's problem;
#   3. failing that, nothing here can run: log that the guard is INERT for this
#      call and exit. Fail-open stays the contract; silence does not.
#
# WHAT THE LADDER COSTS, MEASURED (re-taken 2026-09-03, seventh pass; macOS
# 26.5.2 / arm64, /usr/bin/python3 3.9.6, 50 invocations per cell, two qualifying
# rounds). ONE probe on the ordinary machine -- ~25 ms marginal, ~38 ms measured
# standalone -- on every Write/Edit/Bash call in every session. The full cell
# table and the other two populations are in COST above. The fifth pass refused
# to pay this and said so in this header. That reasoning is withdrawn: it was
# weighing the probe against a 47 ms ambient cost that no longer exists, and it
# was buying speed with the one property this hook exists to have. A guard that
# picks an interpreter which cannot run is not a cheap guard, it is not a guard.
#
# Three things keep the bill to one probe on an ordinary machine:
#   * RUNG 2 IS NOT COMPUTED ON THE WAY TO RUNG 1. The `-c pass` probe lives in
#     its own loop, entered only when nothing on the list imports yaml (seventh
#     pass). It never made the healthy machine pay -- that one breaks out on its
#     first candidate either way -- but it did cost the machine whose SECOND
#     candidate has PyYAML a third probe it had no use for.
#   * ORDER. /usr/bin/python3 is tried before the one on PATH because on macOS
#     it is the one that ships PyYAML — now purely a COST heuristic (which
#     candidate is likeliest to answer first), never a correctness claim: the
#     probe decides, and on a machine where PATH's python3 has PyYAML and
#     /usr/bin/python3 does not, PATH's is what gets picked.
#   * NO PYCACHE PREFIX ON THE PROBE. The probes strip PYTHONPYCACHEPREFIX
#     (leaving PYTHONDONTWRITEBYTECODE in force, so they still write nothing).
#     The prefix exists to stop a planted in-tree `.pyc` being executed when
#     this hook imports a REPO module; a probe imports `yaml` and nothing else,
#     so the redirection protects nothing there — and costs 60 ms, because a
#     redirected lookup that may not be populated recompiles every stdlib module
#     from source on every call. Measured: 31 ms plain, 90 ms with both.
#
# `CV_PYTHON`, when set, is the ONLY candidate — an explicit override exists to
# be obeyed, and a hook that silently substituted another interpreter could not
# be pointed at a chosen one by a test. It is still put through the same ladder:
# obeying an override is not the same as pretending a dead interpreter works.
# Kept as one-line functions on purpose: tests/test-lane-guard.sh plants a
# violation by rewriting these two lines, and a mutation that cannot be applied
# proves nothing. Both go through `_cv_bounded`, so a candidate that hangs costs
# CV_PROBE_TIMEOUT and not the session; both return 124 when that happens.
_cv_can_yaml() { _cv_bounded env -u PYTHONPYCACHEPREFIX "$1" -B -c 'import yaml'; }
_cv_can_run() { _cv_bounded env -u PYTHONPYCACHEPREFIX "$1" -B -c pass; }

_cv_cands=()
if [ -n "${CV_PYTHON:-}" ]; then
  _cv_cands=("$CV_PYTHON")
elif [ -n "${CV_PY_CANDIDATES:-}" ]; then
  # An explicit ordered list. Honoured as given, and every entry still probed.
  IFS=':' read -r -a _cv_cands <<<"$CV_PY_CANDIDATES"
else
  _cv_path_py="$(command -v python3 2>/dev/null || true)"
  for _cv_cand in /usr/bin/python3 "$_cv_path_py"; do
    [ -n "$_cv_cand" ] || continue
    _cv_dupe=""
    for _cv_seen in ${_cv_cands+"${_cv_cands[@]}"}; do
      [ "$_cv_seen" = "$_cv_cand" ] && _cv_dupe=1
    done
    [ -n "$_cv_dupe" ] && continue
    _cv_cands+=("$_cv_cand")
  done
fi

CV_PY_CANDIDATES=""
for _cv_cand in ${_cv_cands+"${_cv_cands[@]}"}; do
  CV_PY_CANDIDATES="${CV_PY_CANDIDATES:+$CV_PY_CANDIDATES:}$_cv_cand"
done
export CV_PY_CANDIDATES

# RUNG 1 ONLY, first. The `-c pass` probe used to run INSIDE this loop, on every
# candidate that failed `import yaml` — so a machine whose FIRST candidate has
# PyYAML paid one probe (it breaks immediately), but a machine whose second one
# has it paid three, and a machine with none paid two plus the loop. Rung 2 is the
# unhealthy path by construction; it does not need to be computed on the way to
# rung 1. Split, the healthy machine pays exactly one probe and the unhealthy one
# pays at most one per candidate per rung.
PY=""
_cv_runnable=""
_cv_passed_over=""
_cv_timedout=""
for _cv_cand in ${_cv_cands+"${_cv_cands[@]}"}; do
  _cv_can_yaml "$_cv_cand"
  _cv_rc=$?
  if [ "$_cv_rc" = "0" ]; then PY="$_cv_cand"; break; fi
  # A candidate that ran out of budget STOPS THE LADDER. Stepping over it would
  # mean paying the same budget again for every remaining candidate, and the
  # thing that just happened — an interpreter on this machine hangs — is not a
  # property of that one path that the next one is likely to fix.
  if [ "$_cv_rc" = "124" ]; then _cv_timedout="$_cv_cand"; break; fi
  _cv_passed_over="${_cv_passed_over:+$_cv_passed_over, }$_cv_cand"
done

# RUNG 2, reached only when nothing on the list can import yaml.
if [ -z "$PY" ] && [ -z "$_cv_timedout" ]; then
  for _cv_cand in ${_cv_cands+"${_cv_cands[@]}"}; do
    _cv_can_run "$_cv_cand"
    _cv_rc=$?
    if [ "$_cv_rc" = "0" ]; then _cv_runnable="$_cv_cand"; break; fi
    if [ "$_cv_rc" = "124" ]; then _cv_timedout="$_cv_cand"; break; fi
  done
fi

# A TIMED-OUT PROBE IS ANNOUNCED, ONCE, AND THE HOOK STOPS. Fail open — the
# contract does not bend for a slow machine — but never silently: the guard was
# supposed to be active on this call and was not.
if [ -n "$_cv_timedout" ]; then
  _cv_log "lane-guard: interpreter probe of $_cv_timedout exceeded its \
${CV_PROBE_TIMEOUT}s budget; the ladder STOPPED there and the guard is INERT \
for this tool call. This write was NOT checked against any lane. The \
git-derived scope gate (scripts/compound-v-scope-check.py) is unaffected and \
remains the authority."
  _cv_notice "an interpreter probe exceeded its ${CV_PROBE_TIMEOUT}s budget and \
the ladder stopped rather than hold this tool call open; no interpreter was \
chosen."
  exit 0
fi

if [ -n "$PY" ]; then
  # THE INTERPRETER IS NAMED ON EVERY PATH, not only on the fallback ones. It used
  # to be logged only when a candidate had been passed over, and the consequence
  # was that the ORDER could not be observed: on a machine where PATH's python3
  # has PyYAML and /usr/bin/python3 does not, the pick is the whole difference
  # between the ladder and the ordering it replaced, and nothing said which one
  # ran. One line per call is the price of that being checkable — the same log
  # already carries a line on the unresolved path, which is the common one.
  # ONCE PER SESSION as of the eighth pass: see `_cv_log_once`.
  _cv_log_once "lane-guard: interpreter $PY (imports yaml)${_cv_passed_over:+; passed over: $_cv_passed_over}"
elif [ -n "$_cv_runnable" ]; then
  PY="$_cv_runnable"
  _cv_log_once "lane-guard: interpreter $PY CANNOT import PyYAML and no candidate on \
this list could (tried: $CV_PY_CANDIDATES); the manifest read falls back to a \
yaml-capable candidate if the payload finds one, else to the embedded parser, \
which reads a SUBSET of YAML"
else
  # NOT deduplicated per session, unlike the two rungs above: this one is not a
  # standing fact about the machine but a call on which the guard reached no
  # decision at all, and every one of those is its own incident.
  _cv_log "lane-guard: NO candidate interpreter could be run (tried: \
${CV_PY_CANDIDATES:-<none>}); the guard is INERT for this tool call and this \
write was NOT checked against any lane. The git-derived scope gate \
(scripts/compound-v-scope-check.py) is unaffected and remains the authority."
  exit 0
fi

# Read the Python source into a variable WITHOUT a $(...) command substitution:
# bash parses the inside of $( ) even around a quoted heredoc, and a bare
# backtick in the Python source is then a syntax error in this file.
# `read -d ''` returns non-zero at EOF by design; the variable is still set.
IFS= read -r -d '' LANE_GUARD_PY <<'PYEOF' || true
import json
import os
import re
import shlex
import sys
import time

LOG = (os.environ.get("CV_LANE_GUARD_LOG")
       or os.path.join(os.environ.get("TMPDIR", "/tmp"),
                       "compound-v-lane-guard.log"))


def log(msg):
    """Best effort. A logging failure must never influence the decision."""
    try:
        with open(LOG, "a") as fh:
            fh.write(str(msg).replace("\n", " ")[:2000] + "\n")
    except Exception:
        pass


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}))


def open_notice(reason):
    """Fail open, and SAY SO. Used only once a job was resolved and the guard
    was therefore supposed to be active -- an unresolved agent is the ordinary
    case (a human session) and stays silent."""
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "additionalContext": (
            "Compound V lane-guard FAILED OPEN: " + reason
            + " This write was NOT checked against the job's write_allowed. "
              "The git-derived scope gate (scripts/compound-v-scope-check.py) "
              "is unaffected and remains the authority."),
    }}))


# --------------------------------------------------------------------------- #
# path helpers
# --------------------------------------------------------------------------- #
def _rel_under(path, root):
    """Repo-relative path if `path` is inside `root`, else None.

    Compared both lexically and through realpath, because on macOS a worktree
    handed to us as /tmp/... is really /private/tmp/... and a lexical-only
    comparison would silently place every target OUTSIDE the root (= allow
    everything)."""
    if not root:
        return None
    pairs = [(os.path.normpath(path), os.path.normpath(root))]
    try:
        pairs.append((os.path.realpath(path), os.path.realpath(root)))
    except Exception:
        pass
    for p, r in pairs:
        r = r.rstrip(os.sep)
        if p == r:
            return "."
        if p.startswith(r + os.sep):
            return p[len(r) + 1:]
    return None


UNRESOLVABLE = ("$", "`", "\n")


def _resolvable(token):
    return token and not any(ch in token for ch in UNRESOLVABLE)


# --------------------------------------------------------------------------- #
# lane resolution
# --------------------------------------------------------------------------- #
def project_roots(cwd):
    out = []

    def add(p):
        if p:
            p = os.path.normpath(p)
            if p not in out:
                out.append(p)

    add(os.environ.get("CV_PROJECT_DIR"))
    add(os.environ.get("CLAUDE_PROJECT_DIR"))
    cur = os.path.normpath(cwd or ".")
    # The probe showed workflow worktrees live at <project>/.claude/worktrees/<id>,
    # so the MAIN checkout (which holds the live state.json) is derivable.
    m = re.match(r"^(.*)/\.claude/worktrees/[^/]+", cur)
    if m:
        add(m.group(1))
    for _ in range(12):  # bounded walk
        if os.path.isdir(os.path.join(cur, "docs", "superpowers", "execution")):
            add(cur)
            break
        nxt = os.path.dirname(cur)
        if nxt == cur:
            break
        cur = nxt
    return out


def _mtime(p):
    try:
        return os.path.getmtime(p)
    except OSError:
        return 0.0


def map_files(cwd, limit=8):
    """Lane-map candidates, newest run first. Bounded: PreToolUse hooks share a
    tight time budget, so this never walks more than `limit` run dirs."""
    explicit = os.environ.get("CV_LANE_MAP")
    if explicit:
        return [explicit]
    found = []
    for root in project_roots(cwd):
        base = os.path.join(root, "docs", "superpowers", "execution")
        try:
            names = os.listdir(base)
        except OSError:
            continue
        dirs = [os.path.join(base, n) for n in names]
        dirs = [d for d in dirs if os.path.isdir(d)]
        dirs.sort(key=_mtime, reverse=True)
        for d in dirs[:limit]:
            for cand in ("lane-map.json", "state.json"):
                p = os.path.join(d, cand)
                if os.path.isfile(p):
                    found.append(p)
                    break
        if found:
            break
    return found[:limit]


def read_map(path):
    """-> (agents{aid: job}, worktrees{path: job}, manifest_path) or None."""
    try:
        with open(path, "r") as fh:
            data = json.load(fh)
    except Exception as exc:
        log("lane-map unreadable %s: %s" % (path, exc))
        return None
    if not isinstance(data, dict):
        return None
    rundir = os.path.dirname(path)
    manifest = data.get("manifest") or os.path.join(rundir, "manifest.yaml")
    if not os.path.isabs(manifest):
        manifest = os.path.join(rundir, manifest)
    agents, worktrees = {}, {}
    for aid, job in (data.get("agents") or {}).items():
        if isinstance(job, str):
            agents[aid] = job
    for wt, job in (data.get("worktrees") or {}).items():
        if isinstance(job, str):
            worktrees[wt] = job
    # state.json fallback shape: jobs.<id>.{agent_id|agent_ids, worktree}
    jobs = data.get("jobs")
    if isinstance(jobs, dict):
        for job_id, rec in jobs.items():
            if not isinstance(rec, dict):
                continue
            aid = rec.get("agent_id")
            if isinstance(aid, str) and aid:
                agents.setdefault(aid, job_id)
            for aid in (rec.get("agent_ids") or []):
                if isinstance(aid, str) and aid:
                    agents.setdefault(aid, job_id)
            wt = rec.get("worktree")
            if isinstance(wt, str) and wt:
                worktrees.setdefault(wt, job_id)
    return agents, worktrees, manifest


def resolve_job(agent_id, cwd, maps=None):
    """-> (job_id, manifest_path, root, project_root, how) or None."""
    for path in (map_files(cwd) if maps is None else maps):
        parsed = read_map(path)
        if not parsed:
            continue
        agents, worktrees, manifest = parsed
        # <project>/docs/superpowers/execution/<run>/<file>
        proj = os.path.normpath(os.path.join(os.path.dirname(path),
                                             "..", "..", "..", ".."))
        if agent_id and agent_id in agents:
            job = agents[agent_id]
            root = None
            for wt, j in worktrees.items():
                if j == job:
                    root = wt
                    break
            return job, manifest, root or cwd, proj, "agent_id"
        for wt, job in worktrees.items():
            if cwd and _rel_under(cwd, wt) is not None:
                return job, manifest, wt, proj, "cwd->worktree"
    return None


# --------------------------------------------------------------------------- #
# UNRESOLVED IDENTITY -- recorded, not silently permissive
#
# `register-lane` is the implementer's "FIRST COMMAND, BEFORE ANY OTHER TOOL
# CALL" and NOTHING ENFORCES IT. It is prompt prose. A worker that writes before
# it registers is allowed, because at that moment no map entry exists for it --
# and this hook cannot fix that ORDERING from its side: PreToolUse fires with
# whatever map is on disk, it has no way to make a registration that has not
# happened yet exist, and refusing to act until one does would mean denying the
# `register-lane` command itself. (It also cannot lock the registration write:
# that read-modify-write is `register_lane()` in
# scripts/compound-v-emit-workflow.py -- another job's lane -- and this hook
# never writes the lane map at all. See the report for the exact defect.)
#
# What the guard CAN do is stop the failure from being invisible. When an
# ISOLATED AGENT (cwd inside `.claude/worktrees/<id>`) fails to resolve against a
# LIVE lane map, that is not the ordinary human session -- it is a worker that
# wrote before registering, or a registration a concurrent sibling's
# read-modify-write lost. One deduplicated line goes into the run directory so
# afterwards the run says so, instead of reading as a clean run.
#
# THE THREE GATES ON RECORDING, and why each is there:
#   1. a lane map was found            -- otherwise Compound V is not involved
#   2. at least one worktree it names still EXISTS on disk -- a finished run's
#      worktrees are removed (`git worktree remove` runs on Merge AND Discard),
#      so a repo full of historical run dirs does not make every call an incident
#   3. cwd is inside `.claude/worktrees/<id>` -- a plain human session in the
#      main checkout stays exactly as silent as it is today
# Residual false positive, stated rather than hidden: a NON-Compound-V agent
# worktree running while a Compound V run is genuinely live. Cost of that: one
# recorded line and one notice. There is no signal that separates the two --
# Engine C hands its workers no environment marker.
# --------------------------------------------------------------------------- #
UNRESOLVED_RECORD = "lane-guard-unresolved.jsonl"
UNRESOLVED_RECORD_MAX = 262144   # bounded: this runs on every tool call
WORKTREE_RE = re.compile(r"^(?P<root>.*/\.claude/worktrees/[^/]+)(?:/|$)")


def agent_worktree_root(cwd):
    """The `<...>/.claude/worktrees/<id>` prefix of cwd, or None."""
    m = WORKTREE_RE.match(os.path.normpath(cwd or ""))
    return m.group("root") if m else None


def live_lane_map(path):
    """True when this run's lane map still names a worktree that exists."""
    parsed = read_map(path)
    if not parsed:
        return False
    _agents, worktrees, _manifest = parsed
    for wt in worktrees:
        try:
            if os.path.isdir(wt):
                return True
        except Exception:
            pass
    return False


def record_unresolved(map_path, agent_id, cwd, tool):
    """Append one DEDUPLICATED line to <run-dir>/lane-guard-unresolved.jsonl.

    -> True when a new line was written (the caller announces it once; every
    later call for the same identity stays quiet).

    LOCKING. The dedupe is a read-then-append, so it takes an exclusive
    `fcntl.flock` on the record file across both halves -- two workers hitting
    this in the same instant cannot read each other's pre-write state and both
    conclude they are first. The lock is NON-BLOCKING with two short retries: a
    PreToolUse hook that waits on a lock is a hook that stalls the session, and
    this record is worth far less than the run. If the lock cannot be had the
    line is appended anyway -- the file is opened O_APPEND, so a short write
    cannot be lost or interleaved, and the worst outcome is a duplicate line,
    never a missing one.

    Never raises: a failure to record must not influence the decision."""
    try:
        import fcntl
        rundir = os.path.dirname(map_path)
        wt_root = agent_worktree_root(cwd)
        # NEVER write inside the tree the acting agent is being gated on: an
        # untracked file there is one the git scope gate would then union into
        # that job's changed set and BLOCK it for. The run dir normally lives in
        # the main checkout, but a linked worktree carries the same paths.
        if wt_root and _rel_under(rundir, wt_root) is not None:
            log("SKIP-RECORD (run dir is inside the gated worktree) %s" % rundir)
            return False
        path = os.path.join(rundir, UNRESOLVED_RECORD)
        key = (agent_id or "", os.path.normpath(cwd or ""))
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "tool": tool,
            "agent_id": key[0],
            "cwd": key[1],
            "why": ("lane guard could not resolve this caller to a job; the "
                    "write was NOT lane-checked (register-lane missing, ran "
                    "late, or its entry was lost)"),
        }
    except Exception as exc:
        log("RECORD FAILED (setup): %r" % (exc,))
        return False

    fh = None
    locked = False
    try:
        fh = open(path, "a+")
        for _ in range(6):   # <= 30 ms worst case, on a path that is already rare
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except (IOError, OSError):
                time.sleep(0.005)
        try:
            fh.seek(0, os.SEEK_END)
            if fh.tell() > UNRESOLVED_RECORD_MAX:
                return False
            fh.seek(0)
            body = fh.read(UNRESOLVED_RECORD_MAX)
        except Exception:
            body = ""
        for line in body.splitlines():
            try:
                prev = json.loads(line)
            except Exception:
                continue
            if (prev.get("agent_id") or "", prev.get("cwd") or "") == key:
                return False
        fh.write(json.dumps(entry, sort_keys=True) + "\n")
        fh.flush()
        return True
    except Exception as exc:
        log("RECORD FAILED (write): %r" % (exc,))
        return False
    finally:
        if fh is not None:
            try:
                if locked:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                fh.close()
            except Exception:
                pass


def repo_loader():
    """The repo's own YAML loader (scripts/compound-v-validate-manifest.py).

    Never a third parser: two YAML parsers that disagree about what a lane is
    would be a bug factory, and that module's `load_yaml` already prefers PyYAML
    and carries the subset parser's selftests.
    """
    import importlib.util
    src = os.environ.get("CV_VALIDATE_MANIFEST")
    if not src or not os.path.isfile(src):
        raise RuntimeError("validate-manifest loader not found")
    spec = importlib.util.spec_from_file_location("_cv_vm", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Handed to a yaml-capable candidate interpreter: YAML in, JSON out. `default`
# keeps a date or a similar non-JSON scalar from turning a readable manifest
# into an unreadable one -- a lane is a list of strings either way.
_YAML_TO_JSON = (
    "import json,sys,yaml\n"
    "sys.stdout.write(json.dumps(yaml.safe_load(open(sys.argv[1]).read()),"
    " default=str))\n"
)


# The delegated parse's hard budget, in seconds. Larger than a probe's (0.9 s):
# this one is READING A FILE and only ever runs after a job has resolved, so it
# is off the ordinary session's path entirely — but it is still bounded, and the
# bound plus one probe budget has to stay inside the `timeout` that
# hooks/hooks.json puts on this hook's registration.
_PARSE_BUDGET_S = 5


def _yaml_via(interpreter, manifest_path):
    """Parse with another interpreter's PyYAML, or None if that cannot be done."""
    import subprocess
    proc = None
    try:
        proc = subprocess.Popen(
            [interpreter, "-B", "-c", _YAML_TO_JSON, manifest_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, _err = proc.communicate(timeout=_PARSE_BUDGET_S)
    except Exception as exc:  # noqa: BLE001 - a guard path never raises
        # Including a timeout: PreToolUse has a budget, and a candidate that
        # hangs must not take the session with it.
        if proc is not None:
            try:
                proc.kill()
                proc.communicate(timeout=1)
            except Exception:
                pass
        log("candidate %s could not parse the manifest: %r" % (interpreter, exc))
        return None
    if proc.returncode != 0:
        return None
    try:
        return json.loads(out.decode("utf-8", "replace"))
    except Exception:
        return None


def load_manifest_data(manifest_path):
    """The manifest as a mapping, PREFERRING AN INTERPRETER THAT HAS PyYAML.

    The embedded subset parser is a subset by definition, so it is the last
    resort and never the silent default. Order:

      1. PyYAML in THIS process -- the ordinary case, and free;
      2. failing that, the first CV_PY_CANDIDATES entry whose PyYAML can read
         the file (announced BY PATH in the log, because the interpreter this
         hook was started under being yaml-less is the fact worth knowing);
      3. failing that, the repo's subset parser, which raises rather than hand
         back a truncated document.

    Step 2 costs one subprocess and is reached only after a job has resolved --
    the unresolved path every human session takes never gets here at all.
    """
    with open(manifest_path, "r") as fh:
        text = fh.read()
    try:
        import yaml  # noqa: F401 - presence is the whole question
    except ImportError:
        pass
    else:
        return repo_loader().load_yaml(text)

    log("PyYAML unavailable in %s; the embedded parser reads a SUBSET of YAML, "
        "so a yaml-capable interpreter is preferred" % sys.executable)
    mine = os.path.realpath(sys.executable or "")
    for cand in (os.environ.get("CV_PY_CANDIDATES") or "").split(os.pathsep):
        if not cand or os.path.realpath(cand) == mine:
            continue
        data = _yaml_via(cand, manifest_path)
        if data is not None:
            log("manifest parsed by %s (PyYAML)" % cand)
            return data
    log("no candidate interpreter has PyYAML; falling back to the embedded "
        "subset parser for %s" % manifest_path)
    return repo_loader().load_yaml(text)


def write_allowed_for(manifest_path, job_id):
    """Read the job's lane out of the manifest."""
    data = load_manifest_data(manifest_path)
    jobs = (data or {}).get("jobs") or []
    if isinstance(jobs, dict):
        jobs = [dict(v, id=k) for k, v in jobs.items() if isinstance(v, dict)]
    for job in jobs:
        if isinstance(job, dict) and job.get("id") == job_id:
            allowed = job.get("write_allowed") or []
            return [g for g in allowed if isinstance(g, str)]
    raise RuntimeError("job %r not in %s" % (job_id, manifest_path))


def load_matcher():
    import importlib.util
    src = os.environ.get("CV_SCOPE_CHECK")
    if not src or not os.path.isfile(src):
        raise RuntimeError("scope-check matcher not found")
    spec = importlib.util.spec_from_file_location("_cv_scope", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.is_allowed


# --------------------------------------------------------------------------- #
# Bash command inspection
#
# READ THIS BEFORE TRUSTING IT. This is a heuristic extractor of paths a command
# would WRITE. It is deliberately conservative in BOTH directions:
#   * it skips anything it cannot resolve (a `$var`, a command substitution, a
#     relative path after a `cd`) rather than guessing -- guessing produces
#     false denies, and a false deny stalls an autonomous run;
#   * everything it does not model at all is simply invisible to it.
#
# What it CANNOT see (non-exhaustive, and that is the point):
#   * interpreters: python3 -c / node -e / perl -e / awk / ruby writing a file
#   * eval, base64 | sh, a script invoked by path that writes on its own
#   * a path held in a variable, or produced by command substitution
#   * the contents of `$( )` and backticks -- the tokenizer does not model them,
#     so a separator inside one still splits the command (no worse than before,
#     and every token it produces carries `$`/`` ` `` and is therefore skipped
#     as unresolvable)
#   * the command a `find -exec ... \;` runs (`find` itself is not modelled)
#   * build/format tooling: make, npm run build, prettier --write, go generate
#   * git subcommands that rewrite the tree without naming paths
#     (checkout <branch>, restore, apply, clean, stash, reset --hard)
#   * relative paths in a segment that follows a `cd` (skipped on purpose)
#   * an in-lane path that is a symlink pointing out of lane
#   * anything a background/long-running process writes after the call returns
#   * a command whose QUOTING it cannot parse at all -- an unterminated quote, a
#     heredoc whose terminator never arrives, a `$(( a << b ))` that looks like a
#     heredoc. Those raise `_UnparseableCommand` and ALLOW, by contract: on
#     uncertainty this hook never denies.
# All of the above are seen by the git-derived gate afterwards. That is exactly
# why the git gate keeps the authority.
# --------------------------------------------------------------------------- #
WORKER_RE = re.compile(r"compound-v-run-[A-Za-z0-9_.-]+-worker\.sh")
REDIR_WORDS = (">", ">>", ">|", "&>", "&>>", "1>", "1>>", "2>", "2>>")
REDIR_ATTACHED = re.compile(r"^(?:[0-9]*|&)>>?\|?(?P<t>.+)$")
CD_LIKE = ("cd", "pushd", "popd", "chdir")
WRAPPERS = ("env", "sudo", "command", "nohup", "time", "exec", "builtin")
# all non-flag args are write targets
ALL_ARGS = ("rm", "rmdir", "unlink", "shred", "touch", "tee", "mv", "truncate",
            "patch")
# only the LAST non-flag arg is the destination
DEST_LAST = ("cp", "install", "rsync", "ln")
# In-place editors REQUIRE the file to already exist -- if it does not, no write
# happens and allowing is correct. That fact resolves the otherwise unparseable
# "is this token the script, the -i suffix, or the file?" ambiguity: keep only
# the non-flag args that name something on disk.
EXISTING_ONLY = ("sed", "perl", "ruby", "patch")
# flags that consume the following token (kept small on purpose: a value
# mistaken for a path is a false deny)
VALUE_FLAGS = {
    "truncate": ("-s", "--size", "-r", "--reference"),
    "install": ("-m", "--mode", "-o", "--owner", "-g", "--group", "-t",
                "--target-directory"),
    "cp": ("-t", "--target-directory", "-S", "--suffix"),
    "mv": ("-t", "--target-directory", "-S", "--suffix"),
    "rsync": ("-e", "--rsh", "--exclude", "--include", "--files-from"),
    "tee": ("-p",),
    # NOTE: -i / --in-place is deliberately ABSENT. BSD sed spells it
    # `-i '' <script> <file>` and GNU sed `-i <script> <file>`; treating -i as
    # value-taking makes the GNU form swallow the script and lose the file, a
    # false ALLOW on exactly the case AC-20 names. Both forms are disambiguated
    # by the existence filter instead (see EXISTING_ONLY).
    "sed": ("-e", "--expression", "-f", "--file", "-l", "--line-length"),
    "patch": ("-p", "--strip", "-d", "--directory", "-D", "-F", "-r", "-z"),
}


class _UnparseableCommand(Exception):
    """The tokenizer met shell it does not model.

    ALWAYS resolves to ALLOW at the call site. This exception exists so that
    "I could not parse this" is a distinct, loggable outcome instead of being
    silently degraded into a wrong answer -- which is what the previous
    regex-split did in both directions, and why it shipped a false ALLOW."""


# Separators, but only when they are OUTSIDE quotes and not escaped.
_UNQUOTED_BREAK = ";&|\n"
# A heredoc delimiter word ends at any of these.
_HEREDOC_END = " \t\n;&|<>()"


def _read_heredoc(s, i):
    """Consume `<<` / `<<-` plus its delimiter word starting at s[i].

    -> (raw text consumed, (delimiter, allow_leading_tabs), next index)

    Raises when the delimiter is not a plain literal (`<<$VAR`, `<<`cmd``):
    without knowing the delimiter there is no way to know where the BODY ends,
    and every byte after it is then unclassifiable. Guessing there is exactly
    how a heredoc body gets read as a command."""
    n = len(s)
    j = i + 2
    strip_tabs = False
    if j < n and s[j] == "-":
        strip_tabs = True
        j += 1
    while j < n and s[j] in " \t":
        j += 1
    parts = []
    while j < n and s[j] not in _HEREDOC_END:
        ch = s[j]
        if ch == "'":
            k = s.find("'", j + 1)
            if k < 0:
                raise _UnparseableCommand("unterminated quote in heredoc delimiter")
            parts.append(s[j + 1:k])
            j = k + 1
            continue
        if ch == '"':
            k = j + 1
            while k < n and s[k] != '"':
                k += 2 if s[k] == "\\" else 1
            if k >= n:
                raise _UnparseableCommand("unterminated quote in heredoc delimiter")
            parts.append(s[j + 1:k])
            j = k + 1
            continue
        if ch == "\\":
            if j + 1 >= n:
                raise _UnparseableCommand("trailing backslash in heredoc delimiter")
            parts.append(s[j + 1])
            j += 2
            continue
        if ch in ("$", "`"):
            raise _UnparseableCommand("heredoc delimiter is not a literal")
        parts.append(ch)
        j += 1
    word = "".join(parts)
    if not word:
        raise _UnparseableCommand("heredoc with no delimiter")
    return s[i:j], (word, strip_tabs), j


def _skip_heredoc_bodies(s, i, heredocs):
    """Skip the body of each pending heredoc. A heredoc body is DATA, never a
    command: the old regex split read `rm README.md` inside one as a command and
    would have DENIED on it."""
    for delim, strip_tabs in heredocs:
        while True:
            nl = s.find("\n", i)
            line = s[i:] if nl < 0 else s[i:nl]
            candidate = line.lstrip("\t") if strip_tabs else line
            i = len(s) if nl < 0 else nl + 1
            if candidate == delim:
                break
            if nl < 0:
                raise _UnparseableCommand("heredoc %r never terminated" % delim)
    return i


def _split_segments(cmd_string):
    """Split a shell command into command segments, QUOTE-AWARE.

    Splits on `;`, `&`, `&&`, `|`, `||` and newlines only where they are outside
    single quotes, double quotes and backslash escapes, and skips heredoc bodies
    whole.

    This replaced a raw `re.split(r"\\|\\||&&|;|\\||\\n|&")`, which split on the
    BYTES before any quote was parsed. That regex was wrong in both directions
    and both were observed by executing it:
      * false ALLOW -- `sed -i 's/a/b/; s/c/d/' README.md` and
        `sed -E -i 's/a|b/c/' README.md` produced NO target at all, so the
        out-of-lane write sailed through, while the single-expression spelling
        was correctly denied. The hook's own documentation listed all three as
        caught.
      * false DENY -- a `;` in a heredoc body or in a `git commit -m "..."`
        message opened a segment whose first word was whatever followed it, so
        `git commit -m "fix; rm README.md"` was read as an `rm` of README.md.
        A false deny stalls an autonomous run, which is the more expensive half.

    Raises `_UnparseableCommand` on anything it cannot model. The caller ALLOWS
    on that -- never deny on uncertainty."""
    segments = []
    buf = []
    heredocs = []
    i, n = 0, len(cmd_string)

    def flush():
        seg = "".join(buf).strip()
        if seg:
            segments.append(seg)
        del buf[:]

    while i < n:
        ch = cmd_string[i]

        if ch == "\\":
            if i + 1 >= n:
                raise _UnparseableCommand("trailing backslash")
            if cmd_string[i + 1] == "\n":   # line continuation
                i += 2
                continue
            buf.append(cmd_string[i:i + 2])
            i += 2
            continue

        if ch == "'":
            j = cmd_string.find("'", i + 1)
            if j < 0:
                raise _UnparseableCommand("unterminated single quote")
            buf.append(cmd_string[i:j + 1])
            i = j + 1
            continue

        if ch == '"':
            j = i + 1
            while j < n and cmd_string[j] != '"':
                j += 2 if cmd_string[j] == "\\" else 1
            if j >= n:
                raise _UnparseableCommand("unterminated double quote")
            buf.append(cmd_string[i:j + 1])
            i = j + 1
            continue

        if (ch == "<" and cmd_string.startswith("<<", i)
                and not cmd_string.startswith("<<<", i)):
            text, delim, i = _read_heredoc(cmd_string, i)
            buf.append(text)
            heredocs.append(delim)
            continue

        if ch == "\n" and heredocs:
            flush()
            i = _skip_heredoc_bodies(cmd_string, i + 1, heredocs)
            heredocs = []
            continue

        if ch in _UNQUOTED_BREAK:
            flush()
            i += 1
            continue

        buf.append(ch)
        i += 1

    if heredocs:
        raise _UnparseableCommand("heredoc body never started")
    flush()
    return segments


def _tokens(segment):
    try:
        lx = shlex.shlex(segment, posix=True)
        lx.whitespace_split = True
        return list(lx)
    except ValueError as exc:
        # NOT a whitespace-split fallback any more. Splitting a segment shlex
        # rejected produces tokens like `'s/a/b/` and `README.md"` -- garbage
        # that was then matched against the lane and DENIED on. Unparseable
        # means unparseable: allow, and say which command it was.
        raise _UnparseableCommand("shlex: %s" % exc)


def _nonflag(args, cmd):
    """Non-flag arguments, honouring `--` and a small value-flag table."""
    out = []
    value_flags = VALUE_FLAGS.get(cmd, ())
    skip_next = False
    end_of_flags = False
    for tok in args:
        if skip_next:
            skip_next = False
            continue
        if not end_of_flags:
            if tok == "--":
                end_of_flags = True
                continue
            if tok.startswith("-") and len(tok) > 1:
                if tok in value_flags:
                    skip_next = True
                continue
        out.append(tok)
    return out


def bash_targets(cmd_string, cwd):
    """-> (targets, saw_cd). `saw_cd` means relative paths from that point on
    are unresolvable, so the caller must only evaluate absolute ones.

    Raises `_UnparseableCommand`; the caller ALLOWS on it."""

    def existing(tokens):
        keep = []
        for t in tokens:
            if not _resolvable(t):
                continue
            p = t if os.path.isabs(t) else os.path.join(cwd or ".", t)
            try:
                if os.path.exists(p):
                    keep.append(t)
            except Exception:
                pass
        return keep

    targets = []
    saw_cd = False
    for segment in _split_segments(cmd_string):
        segment = segment.strip()
        if not segment:
            continue
        toks = _tokens(segment)
        words = []
        i = 0
        while i < len(toks):
            tok = toks[i]
            if tok in REDIR_WORDS:
                if i + 1 < len(toks) and not toks[i + 1].startswith("&"):
                    targets.append((toks[i + 1], saw_cd))
                i += 2
                continue
            if tok.startswith("<"):
                # `< file`, `<<EOF`, `<<<word` -- reads, and the heredoc
                # delimiter must not be mistaken for a path.
                i += 2 if tok in ("<", "<<", "<<-", "<<<") else 1
                continue
            m = REDIR_ATTACHED.match(tok)
            if m:
                t = m.group("t")
                if not t.startswith("&"):
                    targets.append((t, saw_cd))
                i += 1
                continue
            words.append(tok)
            i += 1
        # command word: skip VAR=val assignments and thin wrappers
        idx = 0
        while idx < len(words) and (
                re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[idx])
                or os.path.basename(words[idx]) in WRAPPERS):
            idx += 1
        if idx >= len(words):
            continue
        cmd = os.path.basename(words[idx])
        args = words[idx + 1:]
        if cmd in CD_LIKE:
            saw_cd = True
            continue
        if cmd == "dd":
            for a in args:
                if a.startswith("of="):
                    targets.append((a[3:], saw_cd))
            continue
        if cmd in ("sed", "perl", "ruby"):
            # Only the in-place forms write. Without -i these are filters and
            # any write is a redirection, which the redirection scan above
            # already caught.
            if not any(a == "-i" or a.startswith("-i") or a == "--in-place"
                       or a.startswith("--in-place") for a in args):
                continue
            targets.extend((f, saw_cd)
                           for f in existing(_nonflag(args, cmd)))
            continue
        if cmd == "git":
            sub = args[0] if args else ""
            rest = args[1:]
            if sub in ("mv", "rm"):
                targets.extend((f, saw_cd) for f in _nonflag(rest, "git"))
            elif "--" in rest:
                # `git checkout -- <paths>` / `git restore -- <paths>`: only
                # after `--` is a token unambiguously a path. A bare
                # `git checkout <branch>` is NOT treated as a path (that would
                # deny every branch switch).
                after = rest[rest.index("--") + 1:]
                targets.extend((f, saw_cd) for f in after)
            continue
        if cmd in ALL_ARGS:
            files = _nonflag(args, cmd)
            if cmd in EXISTING_ONLY:
                files = existing(files)
            targets.extend((f, saw_cd) for f in files)
            continue
        if cmd in DEST_LAST:
            files = _nonflag(args, cmd)
            if files:
                targets.append((files[-1], saw_cd))
            continue
    return targets, saw_cd


# --------------------------------------------------------------------------- #
def main():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("payload is not an object")
    except Exception as exc:
        log("ALLOW (malformed input): %s" % exc)
        return 0

    tool = payload.get("tool_name") or ""
    if tool not in ("Write", "Edit", "MultiEdit", "NotebookEdit", "Bash"):
        return 0

    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        log("ALLOW (no tool_input) tool=%s" % tool)
        return 0

    command = tool_input.get("command") or ""
    if tool == "Bash" and WORKER_RE.search(command):
        # D5.2 -- never deny the external family's launcher.
        log("ALLOW (external worker invocation, D5.2): %s" % command[:200])
        return 0

    cwd = payload.get("cwd") or os.getcwd()
    agent_id = payload.get("agent_id") or ""

    maps = map_files(cwd)
    resolved = resolve_job(agent_id, cwd, maps)
    if not resolved:
        # An ISOLATED AGENT that matches nothing in a LIVE lane map is the
        # dangerous case, not the ordinary one: it wrote before `register-lane`,
        # or its registration was lost. Record it so the run cannot afterwards
        # read as clean. See the block above for the three gates and the
        # residual false positive.
        if agent_worktree_root(cwd):
            for path in maps:
                if not live_lane_map(path):
                    continue
                first = record_unresolved(path, agent_id, cwd, tool)
                log("ALLOW (UNRESOLVED IDENTITY under a live lane map %s) "
                    "tool=%s agent_id=%r cwd=%s first=%s"
                    % (path, tool, agent_id, cwd, first))
                if first:
                    open_notice(
                        "an isolated agent (cwd %s) resolved to NO job in the "
                        "live lane map %s. Most likely it wrote before running "
                        "`register-lane`, or a concurrent registration lost its "
                        "entry. Recorded in %s so this run does not read as a "
                        "clean one." % (cwd, path, UNRESOLVED_RECORD))
                return 0
        # The ordinary case for a plain human session. Silent by design: an
        # additionalContext line on every tool call would be pure noise.
        log("ALLOW (job unresolved) tool=%s agent_id=%r cwd=%s"
            % (tool, agent_id, cwd))
        return 0
    job_id, manifest, root, project_root, how = resolved

    try:
        allowed = write_allowed_for(manifest, job_id)
        is_allowed = load_matcher()
    except Exception as exc:
        log("ALLOW (guard degraded) job=%s: %s" % (job_id, exc))
        open_notice("job %s resolved, but its lane could not be read (%s)."
                    % (job_id, exc))
        return 0
    if not allowed:
        log("ALLOW (empty write_allowed) job=%s" % job_id)
        open_notice("job %s has no write_allowed globs to enforce." % job_id)
        return 0

    if tool == "Bash":
        try:
            raw_targets, _ = bash_targets(command, cwd)
        except _UnparseableCommand as exc:
            # By contract: uncertainty allows. Logged, not announced -- a command
            # the tokenizer rejects is overwhelmingly a command the shell would
            # reject too, and a per-call notice on it would be noise.
            log("ALLOW (command not parseable: %s) job=%s cmd=%s"
                % (exc, job_id, command[:200]))
            return 0
    else:
        p = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        raw_targets = [(p, False)] if p else []

    if not raw_targets:
        log("ALLOW (no write target identified) job=%s tool=%s" % (job_id, tool))
        return 0

    for target, after_cd in raw_targets:
        if not _resolvable(target):
            log("ALLOW-SKIP (unresolvable token) job=%s target=%r"
                % (job_id, target))
            continue
        if not os.path.isabs(target):
            if after_cd:
                # A `cd` earlier in the command means this hook no longer knows
                # what this relative path resolves to. Guessing here is how a
                # false deny happens, so it skips.
                log("ALLOW-SKIP (relative path after cd) job=%s target=%r"
                    % (job_id, target))
                continue
            target = os.path.join(cwd, target)
        rel = _rel_under(target, root)
        if rel is None:
            other = _rel_under(target, project_root)
            if other is not None and _rel_under(project_root, root) is None:
                deny("Compound V lane guard: job '%s' (%s) tried to write "
                     "'%s', which is in the main checkout but OUTSIDE its own "
                     "worktree %s. A job writes only inside its own tree. "
                     "(Defence in depth; the git-derived scope gate remains "
                     "the authority.)" % (job_id, tool, other, root))
                log("DENY (cross-tree) job=%s target=%s" % (job_id, target))
                return 0
            log("ALLOW-SKIP (outside the gated tree) job=%s target=%s"
                % (job_id, target))
            continue
        if is_allowed(rel, allowed):
            continue
        deny("Compound V lane guard: job '%s' is not allowed to write '%s'. "
             "Its write_allowed lane is: %s. Resolved via %s. Write only "
             "inside the lane; if the change genuinely belongs elsewhere, stop "
             "and report it rather than widening the lane yourself. (This deny "
             "is defence in depth -- the git-derived scope gate "
             "scripts/compound-v-scope-check.py still runs afterwards and "
             "remains the authority.)"
             % (job_id, rel, ", ".join(allowed), how))
        log("DENY job=%s tool=%s target=%s lane=%s"
            % (job_id, tool, rel, allowed))
        return 0

    return 0


try:
    sys.exit(main())
except SystemExit:
    raise
except Exception as _exc:  # absolute last resort: never fail closed
    log("ALLOW (internal error): %r" % (_exc,))
    sys.exit(0)
PYEOF

# The wrapper is the second half of the fail-open contract: if the interpreter
# is missing, crashes, or emits anything that is not a JSON object, the hook
# produces NO decision and exits 0. Only well-formed JSON is ever passed on.
# stdin was consumed above (the session id keys the once-per-session marker), so
# the payload is handed the same bytes on its own stdin.
out="$(printf '%s' "$CV_STDIN" | "$PY" -c "$LANE_GUARD_PY" 2>/dev/null)" || out=""
case "$out" in
  '{'*) printf '%s\n' "$out" ;;
  *) : ;;
esac
exit 0
