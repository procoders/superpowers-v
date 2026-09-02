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
# Only a POSITIVELY IDENTIFIED, fully resolved, out-of-lane path denies.
#
# COST
# ----
# PreToolUse hooks share a tight time budget, so every path here is bounded: at
# most 8 run directories are inspected, resolution stops at the first match, and
# the manifest is only parsed AFTER a job has been resolved.
#
# RE-MEASURED 2026-09-02 (sixth review pass) on macOS 26.5.2 / arm64 with
# /usr/bin/python3 3.9.6, 50 invocations per cell, old hook and new interleaved
# in one round so a shared machine loads both arms equally, against a project
# carrying copies of this repository's 47 run directories:
#
#   bare interpreter start (`-c pass`)      30 ms   the floor, taken in the
#                                                   SAME round as the rows below
#   unresolved job (human session)         120 ms -> 167 ms
#   resolved, write in lane                202 ms -> 245 ms
#   resolved, write out of lane            201 ms -> 298 ms*
#
# The arrow is this pass's viability ladder: +47 ms on the unresolved path,
# +43 ms on the resolved allow, which is one `import yaml` probe and matches the
# ~44 ms that probe costs measured on its own. (*The deny cell was the last one
# taken and the round's closing floor had drifted up; the earlier baseline had
# in-lane 208.5 ms and deny 209.5 ms, so read the deny as EQUAL to the allow --
# the verdict has never been the expensive part, resolution and the manifest
# parse are.)
#
# HOW MANY ROUNDS THAT IS, HONESTLY: ONE. The rows above are the single round
# taken while this machine was quiet (opening floor 30.0 ms). Every later
# attempt was DISCARDED by the rule two paragraphs down -- a parallel dogfood
# run held the cores and the floor sat at 45-390 ms, where the same cells read
# 250-680 ms. Two independent things corroborate the delta rather than the
# absolutes: the probe measured on its own costs ~44 ms (`import yaml`, cache
# prefix stripped), which is the +47/+43 seen here; and the OLD hook measured
# 127 ms unresolved / 208 ms in lane / 209 ms deny in a separate quiet round,
# which is the "before" column again. The sixth review pass, measuring
# independently on this box, also could not reproduce 47 ms for any variant and
# reported 115-175 ms per invocation.
#
# THE 47-81 ms THIS HEADER PUBLISHED IS WITHDRAWN, AND SO IS THE REASON IT WAS
# NEVER RE-TAKEN. Those figures were measured 2026-09-01. On 2026-09-02 the
# fourth review pass added the PYTHONPYCACHEPREFIX redirection below, and nobody
# re-measured: the UNCHANGED hook now costs 120 ms on the path that published
# 47 ms. The redirection is why, and the mechanism is worth knowing before
# anyone "optimises" it away: PYTHONPYCACHEPREFIX moves the bytecode-cache
# LOOKUP into a private per-invocation directory while PYTHONDONTWRITEBYTECODE
# forbids populating it, so EVERY stdlib module is recompiled from source on
# every single invocation. Measured directly, `-c 'import json,os,re,shlex,sys,
# time'`: 31 ms plain, 32 ms with PYTHONDONTWRITEBYTECODE alone, 35 ms with the
# prefix alone (it populates once and reuses), 90 ms with both. That ~59 ms is
# the price of refusing to execute a planted .pyc, and it is worth paying --
# but it should be paid knowingly, and it is not what the README said it was.
#
# So the ambient figure is a RANGE, 167-245 ms, on this machine, in this state.
# Roughly: ~30 ms interpreter floor + ~59 ms cache-miss tax + ~45 ms viability
# probe + ~33 ms bash, payload compile and resolution; a resolved call adds the
# manifest parse and the matcher import on top.
#
# To reproduce: drive this hook with the synthetic PreToolUse payloads that
# tests/test-lane-guard.sh builds (its sandbox is the shape the resolved rows
# above were measured against) and time the loop. Take the bare-interpreter
# floor in the same round and DISCARD any round whose floor is above ~31 ms --
# a machine running a parallel dogfood run doubles every number here, which is
# how a "measured" figure ends up being about the load. Set CV_LANE_GUARD_LOG
# and read it back to confirm which path you hit -- an in-lane allow logs
# NOTHING and an unresolved allow logs "ALLOW (job unresolved)", and the two are
# otherwise indistinguishable from stdout, which is empty for both.
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
#   CV_LANE_GUARD_LOG  log file (default $TMPDIR/compound-v-lane-guard.log).
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
export PYTHONDONTWRITEBYTECODE=1
CV_PYCACHE_DIR="${TMPDIR:-/tmp}/cv-lane-guard-pycache.$$.${RANDOM:-0}"
if mkdir -p "$CV_PYCACHE_DIR" 2>/dev/null; then
  export PYTHONPYCACHEPREFIX="$CV_PYCACHE_DIR"
  # Single-quoted on purpose: the variable is never reassigned, so expanding it
  # at trap time is correct AND cannot be broken by a quote inside $TMPDIR.
  trap 'rm -rf -- "$CV_PYCACHE_DIR"' EXIT
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
# WHAT THE LADDER COSTS, MEASURED (2026-09-02, macOS 26.5.2 / arm64,
# /usr/bin/python3 3.9.6, 50 invocations per path). One probe, ~44 ms, on every
# Write/Edit/Bash call in every session: 127 ms unresolved before, 171 ms after.
# The fifth pass refused to pay it and said so in this header. That reasoning is
# withdrawn: it was weighing the probe against a 47 ms ambient cost that no
# longer exists (the real figure is measured in COST above), and it was buying
# speed with the one property this hook exists to have. A guard that picks an
# interpreter which cannot run is not a cheap guard, it is not a guard.
#
# Two things keep the bill to one probe on an ordinary machine:
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
_cv_log() {
  # The payload's log file, resolved the same way it resolves it. Best effort:
  # a logging failure must never influence a decision.
  printf '%s\n' "$1" \
    >>"${CV_LANE_GUARD_LOG:-${TMPDIR:-/tmp}/compound-v-lane-guard.log}" \
    2>/dev/null || true
}

# Kept as one-line functions on purpose: tests/test-lane-guard.sh plants a
# violation by rewriting these two lines, and a mutation that cannot be applied
# proves nothing.
_cv_can_yaml() { env -u PYTHONPYCACHEPREFIX "$1" -B -c 'import yaml' >/dev/null 2>&1; }
_cv_can_run() { env -u PYTHONPYCACHEPREFIX "$1" -B -c pass >/dev/null 2>&1; }

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

PY=""
_cv_runnable=""
_cv_passed_over=""
for _cv_cand in ${_cv_cands+"${_cv_cands[@]}"}; do
  if _cv_can_yaml "$_cv_cand"; then PY="$_cv_cand"; break; fi
  if [ -z "$_cv_runnable" ] && _cv_can_run "$_cv_cand"; then
    _cv_runnable="$_cv_cand"
  fi
  _cv_passed_over="${_cv_passed_over:+$_cv_passed_over, }$_cv_cand"
done

if [ -n "$PY" ]; then
  # An ordinary machine takes rung 1 on the first candidate and logs NOTHING: a
  # line on every tool call would bury the DENYs this log exists for. A pick
  # that had to pass over a candidate is not ordinary, and is named.
  [ -z "$_cv_passed_over" ] \
    || _cv_log "lane-guard: interpreter $PY (imports yaml); passed over: $_cv_passed_over"
elif [ -n "$_cv_runnable" ]; then
  PY="$_cv_runnable"
  _cv_log "lane-guard: interpreter $PY CANNOT import PyYAML and no candidate on \
this list could (tried: $CV_PY_CANDIDATES); the manifest read falls back to a \
yaml-capable candidate if the payload finds one, else to the embedded parser, \
which reads a SUBSET of YAML"
else
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


def _yaml_via(interpreter, manifest_path):
    """Parse with another interpreter's PyYAML, or None if that cannot be done."""
    import subprocess
    proc = None
    try:
        proc = subprocess.Popen(
            [interpreter, "-B", "-c", _YAML_TO_JSON, manifest_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, _err = proc.communicate(timeout=5)
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
out="$("$PY" -c "$LANE_GUARD_PY" 2>/dev/null)" || out=""
case "$out" in
  '{'*) printf '%s\n' "$out" ;;
  *) : ;;
esac
exit 0
