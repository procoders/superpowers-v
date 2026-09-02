#!/usr/bin/env bash
# tests/test-lane-guard.sh — the decision table of hooks/lane-guard.sh, driven
# by SYNTHETIC PreToolUse stdin against a sandboxed project tree.
#
# Repo precedent: tests/test-epic-goal-stop.sh does the same for the Stop hook;
# no hook in this plugin ships an inline --selftest, so the test home is here.
#
# THE TWO RULES THIS FILE EXISTS TO DEFEND
#   1. A PreToolUse hook that denies wrongly stalls an autonomous run, so every
#      fail-open path below is asserted to produce NO deny, and every single
#      invocation is asserted to exit 0.
#   2. A Write|Edit-only guard is decorative (1D probe, commit 0982ce0), so the
#      shell paths — sed -i in BOTH the GNU and the BSD spelling, and a heredoc
#      redirection — are asserted to DENY.
#
# Payloads are JSON-encoded by python3 rather than hand-quoted: the commands
# under test are full of quotes and newlines, and a shell-quoting accident that
# silently rewrites the command would make a green run meaningless (the BSD
# `sed -i ''` case collapses into the GNU case if you get this wrong).

set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd -P)"
HOOK="${LANE_GUARD_SRC:-$REPO/hooks/lane-guard.sh}"
HOOK_BASH="${HOOK_BASH:-bash}"
# NOBODY WRITES BYTECODE, this suite included: the scope gate carries no
# extension carve-out since the fourth review pass (2026-09-02), so a .pyc a test
# leaves beside the scripts is a real out-of-lane write. This does NOT weaken the
# forged-.pyc case below — PYTHONDONTWRITEBYTECODE stops Python writing a cache,
# never reading one, which is the whole point that case exists to make.
export PYTHONDONTWRITEBYTECODE=1

pass=0
fail=0
ok()  { pass=$((pass + 1)); printf 'PASS %s\n' "$1"; }
bad() { fail=$((fail + 1)); printf 'FAIL %s\n' "$1"; }
check(){ if [ "$2" = "1" ]; then ok "$1"; else bad "$1"; fi; }

# --------------------------------------------------------------------------- #
# Preconditions — loud, never silently skipped.
# --------------------------------------------------------------------------- #
[ -f "$HOOK" ] || { echo "FATAL: $HOOK missing"; exit 1; }
[ -x "$HOOK" ] || { echo "FATAL: $HOOK is not executable"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "FATAL: python3 required"; exit 1; }
[ -f "$REPO/scripts/compound-v-scope-check.py" ] \
  || { echo "FATAL: the matcher this hook reuses is missing"; exit 1; }
[ -f "$REPO/scripts/compound-v-validate-manifest.py" ] \
  || { echo "FATAL: the YAML loader this hook reuses is missing"; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# --------------------------------------------------------------------------- #
# Sandbox project. The layout mirrors what the 1D probe observed: a linked
# workflow worktree at <project>/.claude/worktrees/<runId>-<n>.
# --------------------------------------------------------------------------- #
PROJ="$WORK/proj"
RUN="$PROJ/docs/superpowers/execution/2099-01-01-sandbox"
WT="$PROJ/.claude/worktrees/wf_sandbox-1"
mkdir -p "$RUN" "$WT/hooks" "$WT/tests" "$WT/docs" "$PROJ/hooks"
: >"$WT/README.md"
: >"$WT/docs/existing.md"
: >"$WT/hooks/lane-guard.sh"
: >"$WT/tests/a.sh"
: >"$PROJ/hooks/lane-guard.sh"

cat >"$RUN/manifest.yaml" <<'YEOF'
run_id: 2099-01-01-sandbox
jobs:
  - id: job-under-test
    write_allowed:
      - "hooks/lane-guard.sh"
      - "tests/**"
YEOF

cat >"$RUN/lane-map.json" <<JEOF
{"run_id": "2099-01-01-sandbox",
 "agents": {"agent_abc123": "job-under-test"},
 "worktrees": {"$WT": "job-under-test"}}
JEOF

# A second run whose manifest is MISSING — the "resolved but degraded" path.
RUN2="$PROJ/docs/superpowers/execution/2099-01-02-nomanifest"
WT2="$PROJ/.claude/worktrees/wf_nomanifest-1"
mkdir -p "$RUN2" "$WT2"
cat >"$RUN2/lane-map.json" <<JEOF
{"run_id": "2099-01-02-nomanifest",
 "agents": {"agent_nomanifest": "job-under-test"},
 "worktrees": {"$WT2": "job-under-test"}}
JEOF

# A run whose manifest is written THE WAY `yaml.safe_dump` WRITES ONE (fifth
# review pass, 2026-09-02). Two shapes below defeated the embedded subset parser
# the guard falls back to without PyYAML: a scalar FOLDED across lines at the
# dump width (`feature`, and the `acceptance` item), and block SEQUENCES sitting
# at their parent key's own indent (`jobs`, `write_allowed`). The parse stopped
# at the first one, `jobs` was never reached, and the guard failed open on every
# out-of-lane write of a real run. These are literal safe_dump(width=100) bytes.
RUN4="$PROJ/docs/superpowers/execution/2099-01-04-folded"
WT4="$PROJ/.claude/worktrees/wf_folded-1"
mkdir -p "$RUN4" "$WT4/hooks"
cat >"$RUN4/manifest.yaml" <<'YEOF'
run_id: 2099-01-04-folded
feature: 'Close the fifth review pass: a lane guard that actually enforces, a register-lane the clamp
  accepts, and honest acceptance greps'
jobs:
- id: folded-job
  type: core_slice
  backend: claude
  write_allowed:
  - hooks/lane-guard.sh
  acceptance:
  - the guard reads this manifest through the fallback parser AND through PyYAML and denies the same
    out-of-lane write under both
YEOF
cat >"$RUN4/lane-map.json" <<JEOF
{"run_id": "2099-01-04-folded",
 "agents": {"agent_folded": "folded-job"},
 "worktrees": {"$WT4": "folded-job"}}
JEOF

# An interpreter that CANNOT import yaml, whatever the machine has installed: a
# shim package that raises on import, in front of the real one on PYTHONPATH.
# This is how the fallback parser is exercised deterministically rather than
# only on whichever box happens to lack PyYAML.
NOYAML_DIR="$WORK/noyaml"
mkdir -p "$NOYAML_DIR"
printf 'raise ImportError("PyYAML is blocked for this test")\n' >"$NOYAML_DIR/yaml.py"
NOYAML_PY="$WORK/python3-without-yaml"
{ printf '#!/bin/sh\n'
  printf 'PYTHONPATH=%s exec %s "$@"\n' "$NOYAML_DIR" "$(command -v python3)"
} >"$NOYAML_PY"
chmod +x "$NOYAML_PY"

# ...and an interpreter that CAN, if this machine has one at all.
YAML_PY=""
for _cand in /usr/bin/python3 "$(command -v python3 2>/dev/null || true)"; do
  [ -n "$_cand" ] && [ -x "$_cand" ] || continue
  if "$_cand" -c 'import yaml' >/dev/null 2>&1; then YAML_PY="$_cand"; break; fi
done

# The DELEGATION branch — the guard running under a yaml-less interpreter while
# a yaml-capable one is on its candidate list — cannot be reached by pointing
# CV_PYTHON at the shim above, because CV_PYTHON is honoured verbatim and is
# then the ONLY candidate. So this wrapper overrides the candidate list from
# inside the child, the way a machine whose first candidate lacks PyYAML would
# present it. The second entry clears PYTHONPATH, or it would inherit the shim
# that blocks yaml and prove nothing.
FALLBACK_PY=""
if [ -n "$YAML_PY" ]; then
  CLEAN_PY="$WORK/python3-with-yaml"
  { printf '#!/bin/sh\n'; printf 'PYTHONPATH= exec %s "$@"\n' "$YAML_PY"; } >"$CLEAN_PY"
  chmod +x "$CLEAN_PY"
  FALLBACK_PY="$WORK/python3-without-yaml-but-with-a-candidate"
  { printf '#!/bin/sh\n'
    printf 'PYTHONPATH=%s CV_PY_CANDIDATES=%s exec %s "$@"\n' \
           "$NOYAML_DIR" "$NOYAML_PY:$CLEAN_PY" "$(command -v python3)"
  } >"$FALLBACK_PY"
  chmod +x "$FALLBACK_PY"
fi

# Isolated agent worktrees that NO lane map knows about — the shape of a worker
# that wrote before it ran `register-lane`, or whose registration a concurrent
# sibling's read-modify-write lost.
WTX="$PROJ/.claude/worktrees/wf_unregistered-9"
WTY="$PROJ/.claude/worktrees/wf_unregistered-10"
WTZ="$PROJ/.claude/worktrees/wf_unregistered-11"
mkdir -p "$WTX" "$WTY" "$WTZ"

# A SEPARATE project whose only run is FINISHED: its lane map names a worktree
# that no longer exists on disk (`git worktree remove` runs on Merge AND
# Discard). A repo full of historical run dirs must not turn every unresolved
# call into a recorded incident.
PROJ2="$WORK/proj2"
RUN3="$PROJ2/docs/superpowers/execution/2099-01-03-finished"
GONE="$PROJ2/.claude/worktrees/wf_gone-1"        # deliberately NOT created
OTHER="$PROJ2/.claude/worktrees/wf_other-2"
mkdir -p "$RUN3" "$OTHER"
cat >"$RUN3/lane-map.json" <<JEOF
{"run_id": "2099-01-03-finished",
 "agents": {},
 "worktrees": {"$GONE": "job-gone"}}
JEOF

# Where every MUTATED copy of the hook lives. It has to MIRROR THE PLUGIN
# LAYOUT (`<root>/hooks/<hook>` beside `<root>/scripts/`), because the hook
# locates the matcher and the YAML loader relative to its own directory. A
# mutant dropped in a bare temp dir cannot find either, fails open as "guard
# degraded", and would then satisfy any assertion that merely expects ALLOW —
# a planted violation that passes for the wrong reason proves nothing.
MUTROOT="$WORK/mutants"
mkdir -p "$MUTROOT/hooks"
ln -s "$REPO/scripts" "$MUTROOT/scripts"

records()  { find "$PROJ/docs/superpowers/execution" \
                  -name lane-guard-unresolved.jsonl 2>/dev/null; }
reclines() { find "$PROJ/docs/superpowers/execution" \
                  -name lane-guard-unresolved.jsonl -exec cat {} + 2>/dev/null \
             | grep -c . ; }
recreset() { find "$PROJ/docs/superpowers/execution" \
                  -name lane-guard-unresolved.jsonl -delete 2>/dev/null; }

# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
n=0
OUT=""; RC=0; LOG=""
HOOK_UNDER_TEST=""   # set to run a MUTATED copy of the hook

encode() {  # encode <tool> <agent_id> <cwd> <key> <value>
  CV_T="$1" CV_A="$2" CV_C="$3" CV_K="$4" CV_V="$5" python3 -c '
import json, os
print(json.dumps({
    "hook_event_name": "PreToolUse",
    "tool_name": os.environ["CV_T"],
    "agent_id": os.environ["CV_A"],
    "session_id": "s1",
    "cwd": os.environ["CV_C"],
    "tool_input": {os.environ["CV_K"]: os.environ["CV_V"]},
}))'
}

# run <stdin-text> [extra env assignments...]
run() {
  local stdin_text="$1"; shift
  n=$((n + 1))
  LOG="$WORK/log.$n"
  OUT="$(printf '%s' "$stdin_text" \
        | env -u CLAUDE_PROJECT_DIR -u CLAUDE_PLUGIN_ROOT \
              CV_PROJECT_DIR="$PROJ" CV_LANE_GUARD_LOG="$LOG" "$@" \
              "$HOOK_BASH" "${HOOK_UNDER_TEST:-$HOOK}" 2>"$WORK/err.$n")"
  RC=$?
}

is_deny() { printf '%s' "$OUT" | python3 -c '
import json, sys
try:
    d = json.loads(sys.stdin.read())
except Exception:
    print("no"); raise SystemExit
o = d.get("hookSpecificOutput") or {}
print("yes" if o.get("permissionDecision") == "deny"
      and o.get("hookEventName") == "PreToolUse"
      and (o.get("permissionDecisionReason") or "").strip() else "no")'; }

silent() { [ -z "$OUT" ] && echo yes || echo no; }
logged() { grep -q "$1" "$LOG" 2>/dev/null && echo yes || echo no; }

verdict() {  # verdict <name> <deny|allow>
  if [ "$2" = deny ]; then
    check "$1 -> DENY" "$([ "$(is_deny)" = yes ] && echo 1 || echo 0)"
  else
    check "$1 -> no deny" "$([ "$(is_deny)" = no ] && echo 1 || echo 0)"
  fi
  check "$1 -> exit 0" "$([ "$RC" = "0" ] && echo 1 || echo 0)"
}

# bash_case <name> <deny|allow> <agent> <cwd> <command>
bash_case() {
  run "$(encode Bash "$3" "$4" command "$5")"
  verdict "$1" "$2"
}
# file_case <name> <deny|allow> <tool> <agent> <cwd> <file_path>
file_case() {
  run "$(encode "$3" "$4" "$5" file_path "$6")"
  verdict "$1" "$2"
}

echo "=== 1. the tool matcher ==================================="

file_case "Read is not a write tool" allow Read agent_abc123 "$WT" "$WT/README.md"
check "Read produces no output at all" \
  "$([ "$(silent)" = yes ] && echo 1 || echo 0)"

echo "=== 2. Write / Edit ======================================="

file_case "in-lane Write (hooks/lane-guard.sh)" allow \
  Write agent_abc123 "$WT" "$WT/hooks/lane-guard.sh"
check "an in-lane Write is silent (no context noise)" \
  "$([ "$(silent)" = yes ] && echo 1 || echo 0)"

file_case "in-lane Write under a ** glob (tests/**)" allow \
  Write agent_abc123 "$WT" "$WT/tests/test-lane-guard.sh"

file_case "out-of-lane Write (README.md)" deny \
  Write agent_abc123 "$WT" "$WT/README.md"
check "the deny names the offending path and the lane" \
  "$(printf '%s' "$OUT" | grep -q 'README.md' \
     && printf '%s' "$OUT" | grep -q 'tests/' && echo 1 || echo 0)"
check "the deny does NOT claim to replace the git-derived verdict" \
  "$(printf '%s' "$OUT" | grep -qi 'remains the authority' && echo 1 || echo 0)"
check "the deny is logged" \
  "$([ "$(logged '^DENY')" = yes ] && echo 1 || echo 0)"

file_case "out-of-lane Edit" deny Edit agent_abc123 "$WT" "$WT/docs/existing.md"
file_case "out-of-lane MultiEdit" deny MultiEdit agent_abc123 "$WT" "$WT/docs/existing.md"
file_case "a RELATIVE file_path is resolved against cwd" deny \
  Write agent_abc123 "$WT" "docs/existing.md"

echo "=== 3. Bash — the hole a Write|Edit matcher leaves ========"

bash_case "sed -i, GNU spelling (sed -i SCRIPT FILE)" deny \
  agent_abc123 "$WT" "sed -i 's/a/b/' README.md"
bash_case "sed -i, BSD spelling (sed -i '' SCRIPT FILE)" deny \
  agent_abc123 "$WT" "sed -i '' 's/a/b/' README.md"
bash_case "sed -i.bak (suffix attached to the flag)" deny \
  agent_abc123 "$WT" "sed -i.bak -e 's/a/b/' docs/existing.md"
bash_case "heredoc redirection (cat > FILE <<EOF)" deny \
  agent_abc123 "$WT" "$(printf 'cat > docs/leak.md <<%sEOF%s\nleak\nEOF\n' "'" "'")"
bash_case "append redirection (>>)" deny \
  agent_abc123 "$WT" 'echo hi >> README.md'
bash_case "attached redirection with no space (>FILE)" deny \
  agent_abc123 "$WT" 'echo hi >docs/leak2.md'
bash_case "redirection buried after && in a chain" deny \
  agent_abc123 "$WT" 'echo start && printf x > docs/leak3.md && echo done'
bash_case "tee" deny agent_abc123 "$WT" 'echo hi | tee -a docs/leak4.md'
bash_case "rm of an out-of-lane file" deny agent_abc123 "$WT" 'rm -f docs/existing.md'
bash_case "mv out of lane (the SOURCE is a write too)" deny \
  agent_abc123 "$WT" 'mv README.md tests/moved.md'
bash_case "cp destination out of lane" deny \
  agent_abc123 "$WT" 'cp tests/a.sh docs/copy.md'
bash_case "dd of=" deny \
  agent_abc123 "$WT" 'dd if=/dev/zero of=docs/leak5.md bs=1 count=1'
bash_case "git rm out of lane" deny agent_abc123 "$WT" 'git rm -f docs/existing.md'
bash_case "git checkout -- PATH out of lane" deny \
  agent_abc123 "$WT" 'git checkout -- docs/existing.md'
bash_case "an absolute out-of-lane path inside the worktree" deny \
  agent_abc123 "$WT" "printf x > $WT/docs/abs-leak.md"

echo "=== 3b. quote-aware segmentation ==========================="
# THE FALSE ALLOW A CROSS-MODEL REVIEW FOUND BY EXECUTING bash_targets().
# The shipped segmentation was `re.split(r"\|\||&&|;|\||\n|&")` — it split on
# the BYTES before any quote was parsed, so these were the observed outputs:
#   sed -i 's/a/b/' README.md          => [('README.md', False)]   (denied)
#   sed -i 's/a/b/; s/c/d/' README.md  => []                       (ALLOWED)
#   sed -E -i 's/a|b/c/' README.md     => []                       (ALLOWED)
# One expression denied, two expressions or a `|` in the pattern allowed —
# while the hook's own documentation listed all three as caught.

bash_case "sed -i, ONE expression (the spelling that already worked)" deny \
  agent_abc123 "$WT" "sed -i 's/a/b/' README.md"
bash_case "sed -i, TWO expressions split by a QUOTED ;" deny \
  agent_abc123 "$WT" "sed -i 's/a/b/; s/c/d/' README.md"
bash_case "sed -E -i whose PATTERN contains a QUOTED |" deny \
  agent_abc123 "$WT" "sed -E -i 's/a|b/c/' README.md"

# The same regex was wrong in the other direction too, and that half is the
# expensive one: a false deny stalls an autonomous run, while a miss is still
# caught by the git-derived gate afterwards. Each of these opened a bogus
# segment whose first word became a command.
bash_case "a ; inside a HEREDOC BODY is data, not a command" allow \
  agent_abc123 "$WT" \
  "$(printf 'cat > tests/new.sh <<%sEOF%s\nrm README.md; echo hi\nEOF\n' "'" "'")"
bash_case "a | inside a quoted grep PATTERN is not a pipe" allow \
  agent_abc123 "$WT" "grep -E 'a|rm README.md' tests/a.sh"
bash_case "a ; inside a double-quoted commit MESSAGE is not a separator" allow \
  agent_abc123 "$WT" 'git commit -m "fix; rm README.md"'

# UNQUOTED separators must still split — a tokenizer that over-merges would
# quietly stop denying half the table above.
bash_case "an UNQUOTED ; still splits (rm in the second segment denies)" deny \
  agent_abc123 "$WT" 'echo ok; rm docs/existing.md'
bash_case "an UNQUOTED | still splits (tee in the second segment denies)" deny \
  agent_abc123 "$WT" 'echo ok | tee docs/existing.md'

bash_case "in-lane heredoc is not denied" allow \
  agent_abc123 "$WT" "$(printf 'cat > tests/new.sh <<%sEOF%s\nx\nEOF\n' "'" "'")"
bash_case "in-lane sed -i is not denied" allow \
  agent_abc123 "$WT" "sed -i 's/a/b/' hooks/lane-guard.sh"
bash_case "a read-only command is not denied" allow \
  agent_abc123 "$WT" 'grep -rn foo docs/ | head -5'
bash_case "2>&1 is a descriptor dup, not a path" allow \
  agent_abc123 "$WT" 'grep -rn foo docs/ 2>&1 | head'
bash_case "a redirect outside the gated tree (/dev/null) is not denied" allow \
  agent_abc123 "$WT" 'grep -rn foo docs/ > /dev/null'
bash_case "git checkout BRANCH is not read as a path" allow \
  agent_abc123 "$WT" 'git checkout main'
bash_case "mkdir is not modelled and must not false-deny" allow \
  agent_abc123 "$WT" 'mkdir -p docs/sub'
bash_case "truncate -s 0 does not read the SIZE as a path" allow \
  agent_abc123 "$WT" 'truncate -s 0 tests/a.sh'

# PLANTED VIOLATION (AC-19): a guard is only trusted once it is shown to FAIL
# without the thing under test. Neuter the Bash arm — exactly the Write|Edit-only
# guard the 1D probe called decorative — and prove the identical `sed -i` payload
# then slips through. If this ever passes, the Bash matcher has stopped working
# and every DENY above is meaningless.
MUTANT="$MUTROOT/hooks/lane-guard-writeedit-only.sh"
sed 's/"NotebookEdit", "Bash")/"NotebookEdit")/' "$HOOK" >"$MUTANT"
chmod +x "$MUTANT"
grep -q '"NotebookEdit", "Bash")' "$MUTANT" \
  && { echo "FATAL: the mutation did not apply — this check would be a no-op"; exit 1; }
grep -q '"NotebookEdit")' "$MUTANT" \
  || { echo "FATAL: the mutation did not apply — this check would be a no-op"; exit 1; }
HOOK_UNDER_TEST="$MUTANT"
bash_case "PLANTED: a Write|Edit-only guard MISSES sed -i (so Bash is load-bearing)" \
  allow agent_abc123 "$WT" "sed -i 's/a/b/' README.md"
HOOK_UNDER_TEST=""
bash_case "and the real guard catches that same payload" deny \
  agent_abc123 "$WT" "sed -i 's/a/b/' README.md"

# PLANTED VIOLATION 2: restore the raw regex segmentation that shipped, and
# prove the two-expression `sed -i` slips straight through it — the exact false
# ALLOW a cross-model review found by executing bash_targets(). The mutation
# injects the old expression inline rather than leaving it in the hook as dead
# code, so a crash cannot masquerade as the old behaviour.
MUTANT_SPLIT="$MUTROOT/hooks/lane-guard-regex-split.sh"
python3 - "$HOOK" "$MUTANT_SPLIT" <<'PYX'
import sys
src = open(sys.argv[1]).read()
edits = [
    # the segmentation that shipped
    ("for segment in _split_segments(cmd_string):",
     'for segment in re.split(r"\\|\\||&&|;|\\||\\n|&", cmd_string):'),
    # and the whitespace-split fallback that shipped with it — both halves, or
    # the mutant would allow via the new "unparseable" path instead of via the
    # old bug, and prove nothing.
    ('raise _UnparseableCommand("shlex: %s" % exc)',
     'return segment.split()'),
]
for old, new in edits:
    if src.count(old) != 1:
        raise SystemExit("FATAL: mutation anchor %r is not unique" % old)
    src = src.replace(old, new)
open(sys.argv[2], "w").write(src)
PYX
[ -s "$MUTANT_SPLIT" ] || { echo "FATAL: split mutation did not apply"; exit 1; }
chmod +x "$MUTANT_SPLIT"
HOOK_UNDER_TEST="$MUTANT_SPLIT"
bash_case "PLANTED: the shipped regex split MISSES sed -i with two expressions" \
  allow agent_abc123 "$WT" "sed -i 's/a/b/; s/c/d/' README.md"
bash_case "PLANTED: and it FALSE-DENIES a ; inside a commit message" \
  deny agent_abc123 "$WT" 'git commit -m "fix; rm README.md"'
HOOK_UNDER_TEST=""

echo "=== 4. the external-worker carve-out (spec D5.2) =========="

# The command below ALSO redirects out of lane. It must still be allowed: what
# that separate OS process writes happens in its own worktree, outside any hook
# this session controls, and is covered by the worker's own scope-gate call plus
# the D1 integration postcondition. Denying it would break the second family,
# not police it.
bash_case "scripts/compound-v-run-codex-worker.sh is never denied" allow \
  agent_abc123 "$WT" 'bash scripts/compound-v-run-codex-worker.sh --job x > docs/worker.log'
check "the carve-out is recorded in the log, not silent" \
  "$([ "$(logged 'external worker invocation')" = yes ] && echo 1 || echo 0)"
for backend in antigravity cursor devin opencode; do
  bash_case "scripts/compound-v-run-$backend-worker.sh is never denied" allow \
    agent_abc123 "$WT" "scripts/compound-v-run-$backend-worker.sh > docs/w.log"
done

echo "=== 5. job resolution ====================================="

file_case "cwd->worktree fallback denies an out-of-lane write" deny \
  Write "" "$WT" "$WT/README.md"
check "the fallback names itself in the reason" \
  "$(printf '%s' "$OUT" | grep -q 'cwd->worktree' && echo 1 || echo 0)"

file_case "cwd->worktree fallback works from a SUBDIR of the worktree" deny \
  Write "" "$WT/docs" "$WT/README.md"

file_case "agent_id resolution names itself in the reason" deny \
  Write agent_abc123 "$WT" "$WT/README.md"
check "agent_id is the primary resolution path" \
  "$(printf '%s' "$OUT" | grep -q 'via agent_id' && echo 1 || echo 0)"

echo "=== 6. cross-tree writes =================================="

file_case "a worktree job writing into the MAIN checkout is denied" deny \
  Write agent_abc123 "$WT" "$PROJ/hooks/lane-guard.sh"
check "the cross-tree deny says so" \
  "$(printf '%s' "$OUT" | grep -qi 'OUTSIDE its own' && echo 1 || echo 0)"

file_case "a path outside the project entirely is out of scope, not denied" allow \
  Write agent_abc123 "$WT" "/var/tmp/cv-lane-guard-outside.txt"

echo "=== 7. fail open, and say so =============================="

file_case "unresolvable agent (an ordinary human session) is allowed" allow \
  Write agent_not_in_any_map "$WORK" "$WORK/anything.md"
check "unresolvable agent is LOGGED" \
  "$([ "$(logged 'job unresolved')" = yes ] && echo 1 || echo 0)"
check "unresolvable agent stays SILENT (no per-call context noise)" \
  "$([ "$(silent)" = yes ] && echo 1 || echo 0)"

run 'not json at all'
verdict "malformed input" allow
check "malformed input is LOGGED" \
  "$([ "$(logged 'malformed input')" = yes ] && echo 1 || echo 0)"

run ''
verdict "empty input" allow

run '{"tool_name":"Write","agent_id":"agent_abc123","cwd":"'"$WT"'"}'
verdict "payload with no tool_input" allow

run '[1,2,3]'
verdict "JSON that is not an object" allow

file_case "resolved job with a MISSING manifest fails open" allow \
  Write agent_nomanifest "$WT2" "$WT2/README.md"
check "the degraded case announces the fail-open in additionalContext" \
  "$(printf '%s' "$OUT" | grep -q 'FAILED OPEN' && echo 1 || echo 0)"
check "the degraded case is LOGGED" \
  "$([ "$(logged 'guard degraded')" = yes ] && echo 1 || echo 0)"

run "$(encode Write agent_abc123 "$WT" file_path "$WT/README.md")" \
    CV_PYTHON="$WORK/no-such-python"
check "a missing interpreter fails OPEN (no output, exit 0)" \
  "$([ -z "$OUT" ] && [ "$RC" = "0" ] && echo 1 || echo 0)"

run "$(encode Write agent_abc123 "$WT" file_path "$WT/README.md")" \
    CV_SCOPE_CHECK="$WORK/no-such-matcher.py"
check "a missing matcher -> no deny, exit 0, and an announced fail-open" \
  "$([ "$(is_deny)" = no ] && [ "$RC" = "0" ] \
     && printf '%s' "$OUT" | grep -q 'FAILED OPEN' && echo 1 || echo 0)"

echo "=== 7b. an UNRESOLVED IDENTITY is recorded, not silent ===="
# `register-lane` is prompt prose — "FIRST COMMAND, BEFORE ANY OTHER TOOL CALL"
# — and nothing enforces it. A worker that writes before registering is allowed,
# because no map entry exists yet, and this hook cannot fix that ordering from
# its side. What it CAN refuse to do is let the failure be invisible: a run in
# which the guard never resolved anything must not read afterwards as a clean
# run.

recreset

file_case "an isolated agent unresolved under a LIVE lane map is allowed" allow \
  Write "" "$WTX" "$WTX/README.md"
check "it is recorded in the run dir, not only in a temp log" \
  "$([ -n "$(records)" ] && echo 1 || echo 0)"
check "exactly one line was recorded" \
  "$([ "$(reclines)" = "1" ] && echo 1 || echo 0)"
check "the fail-open is ANNOUNCED once, naming register-lane" \
  "$(printf '%s' "$OUT" | grep -q 'FAILED OPEN' \
     && printf '%s' "$OUT" | grep -q 'register-lane' && echo 1 || echo 0)"
check "it is logged as an unresolved identity, not as a plain human session" \
  "$([ "$(logged 'UNRESOLVED IDENTITY')" = yes ] && echo 1 || echo 0)"

file_case "the SAME identity again is allowed" allow \
  Write "" "$WTX" "$WTX/docs/other.md"
check "the repeat does NOT add a second line (deduplicated)" \
  "$([ "$(reclines)" = "1" ] && echo 1 || echo 0)"
check "the repeat is silent — one notice per identity, not per tool call" \
  "$([ "$(silent)" = yes ] && echo 1 || echo 0)"

file_case "a DIFFERENT unregistered worktree is allowed" allow \
  Write "" "$WTY" "$WTY/README.md"
check "a different identity DOES add a line" \
  "$([ "$(reclines)" = "2" ] && echo 1 || echo 0)"

# The lock earns its place here: without it these eight read-then-append pairs
# can each read the file before any of them has written, and all eight conclude
# they are first.
recreset
CONCUR="$(encode Write "" "$WTZ" file_path "$WTZ/README.md")"
for _k in 1 2 3 4 5 6 7 8; do
  printf '%s' "$CONCUR" \
    | env -u CLAUDE_PROJECT_DIR -u CLAUDE_PLUGIN_ROOT \
          CV_PROJECT_DIR="$PROJ" CV_LANE_GUARD_LOG="$WORK/log.concurrent" \
          "$HOOK_BASH" "$HOOK" >/dev/null 2>&1 &
done
wait
check "8 CONCURRENT identical calls record exactly ONE line (locked)" \
  "$([ "$(reclines)" = "1" ] && echo 1 || echo 0)"

# The three gates on recording, each asserted.
recreset
file_case "a resolved job records NOTHING (the guard did its job)" deny \
  Write agent_abc123 "$WT" "$WT/README.md"
check "gate 1: a resolved identity leaves no incident record" \
  "$([ -z "$(records)" ] && echo 1 || echo 0)"

run "$(encode Write "" "$OTHER" file_path "$OTHER/README.md")" \
    CV_PROJECT_DIR="$PROJ2"
verdict "an isolated agent under a FINISHED run's lane map" allow
check "gate 2: a run whose worktrees are gone records nothing" \
  "$([ ! -f "$RUN3/lane-guard-unresolved.jsonl" ] && echo 1 || echo 0)"
check "gate 2: and stays silent (no per-call noise in a stale repo)" \
  "$([ "$(silent)" = yes ] && echo 1 || echo 0)"

file_case "gate 3: an ordinary human session (cwd is no worktree) is allowed" \
  allow Write "" "$WORK" "$WORK/human.md"
check "gate 3: a human session records nothing and stays silent" \
  "$([ -z "$(records)" ] && [ "$(silent)" = yes ] && echo 1 || echo 0)"
recreset

# PLANTED VIOLATION 3: strip the recording, and the incident becomes exactly the
# silent fail-open this section exists to end.
MUTANT_REC="$MUTROOT/hooks/lane-guard-no-record.sh"
sed 's/if agent_worktree_root(cwd):/if False:/' "$HOOK" >"$MUTANT_REC"
chmod +x "$MUTANT_REC"
grep -q 'if False:' "$MUTANT_REC" \
  || { echo "FATAL: the record mutation did not apply"; exit 1; }
HOOK_UNDER_TEST="$MUTANT_REC"
file_case "PLANTED: without the recording an unresolved identity is silent" \
  allow Write "" "$WTX" "$WTX/README.md"
check "PLANTED: and the run afterwards looks completely clean" \
  "$([ -z "$(records)" ] && [ "$(silent)" = yes ] && echo 1 || echo 0)"
HOOK_UNDER_TEST=""
recreset

# PLANTED VIOLATION 4: neuter the dedupe the lock protects, and the same
# identity writes a line on every single tool call.
MUTANT_DEDUPE="$MUTROOT/hooks/lane-guard-no-dedupe.sh"
sed 's/) == key:/) == 0:/' "$HOOK" >"$MUTANT_DEDUPE"
chmod +x "$MUTANT_DEDUPE"
grep -q ') == 0:' "$MUTANT_DEDUPE" \
  || { echo "FATAL: the dedupe mutation did not apply"; exit 1; }
HOOK_UNDER_TEST="$MUTANT_DEDUPE"
file_case "PLANTED: dedupe removed, call 1" allow Write "" "$WTX" "$WTX/a.md"
file_case "PLANTED: dedupe removed, call 2" allow Write "" "$WTX" "$WTX/b.md"
check "PLANTED: without the dedupe the same identity records twice" \
  "$([ "$(reclines)" = "2" ] && echo 1 || echo 0)"
HOOK_UNDER_TEST=""
recreset

echo "=== 7c. a manifest as yaml.safe_dump writes it ============"
# The regression this section exists for: driven with a REAL run's manifest and
# the default PATH, the shipped guard resolved the job, could not find it in the
# manifest its own fallback parser had truncated, and ALLOWED the out-of-lane
# write. A guard that fails open on the ordinary output of the tool that writes
# every manifest in this repo is not a guard. Both parsers are exercised, and
# both must reach the same verdict.

file_case "folded manifest, default PATH -> out-of-lane Write is DENIED" deny \
  Write agent_folded "$WT4" "$WT4/README.md"
check "the deny reads the lane out of the folded manifest" \
  "$(printf '%s' "$OUT" | grep -q 'hooks/lane-guard.sh' && echo 1 || echo 0)"

file_case "folded manifest, default PATH -> the in-lane Write still passes" allow \
  Write agent_folded "$WT4" "$WT4/hooks/lane-guard.sh"

run "$(encode Write agent_folded "$WT4" file_path "$WT4/README.md")" \
    CV_PYTHON="$NOYAML_PY"
verdict "folded manifest, FALLBACK parser (no PyYAML anywhere)" deny
check "the fallback deny reads the same lane" \
  "$(printf '%s' "$OUT" | grep -q 'hooks/lane-guard.sh' && echo 1 || echo 0)"
check "the missing PyYAML is logged BY PATH, not swallowed" \
  "$([ "$(logged 'PyYAML unavailable in ')" = yes ] && echo 1 || echo 0)"
check "...and so is the decision to use the subset parser" \
  "$([ "$(logged 'no candidate interpreter has PyYAML')" = yes ] \
     && echo 1 || echo 0)"

run "$(encode Write agent_folded "$WT4" file_path "$WT4/hooks/lane-guard.sh")" \
    CV_PYTHON="$NOYAML_PY"
verdict "folded manifest, FALLBACK parser, in-lane Write" allow

if [ -n "$YAML_PY" ]; then
  run "$(encode Write agent_folded "$WT4" file_path "$WT4/README.md")" \
      CV_PYTHON="$YAML_PY"
  verdict "folded manifest, PyYAML interpreter ($YAML_PY)" deny
  check "the PyYAML deny reads the same lane as the fallback one" \
    "$(printf '%s' "$OUT" | grep -q 'hooks/lane-guard.sh' && echo 1 || echo 0)"
  check "a PyYAML interpreter logs no missing-PyYAML line" \
    "$([ "$(logged 'PyYAML unavailable')" = no ] && echo 1 || echo 0)"
  run "$(encode Write agent_folded "$WT4" file_path "$WT4/hooks/lane-guard.sh")" \
      CV_PYTHON="$YAML_PY"
  verdict "folded manifest, PyYAML interpreter, in-lane Write" allow

  # DELEGATION: running under a yaml-less interpreter, with a yaml-capable one
  # on the candidate list. The manifest read moves to the candidate; the verdict
  # is the same, and the yaml-less interpreter is named in the log.
  run "$(encode Write agent_folded "$WT4" file_path "$WT4/README.md")" \
      CV_PYTHON="$FALLBACK_PY"
  verdict "folded manifest, yaml-less interpreter DELEGATES to a candidate" deny
  check "the yaml-less interpreter is still named BY PATH in the log" \
    "$([ "$(logged 'PyYAML unavailable in ')" = yes ] && echo 1 || echo 0)"
  check "the log names the candidate that actually parsed the manifest" \
    "$([ "$(logged 'manifest parsed by ')" = yes ] && echo 1 || echo 0)"
  check "delegation happened INSTEAD of the subset parser, not as well as it" \
    "$([ "$(logged 'no candidate interpreter has PyYAML')" = no ] \
       && echo 1 || echo 0)"
else
  printf 'SKIP folded manifest under a PyYAML interpreter — no python3 on this '
  printf 'machine can import yaml (CI installs it; this half did NOT run)\n'
fi

check "the hook prefers an interpreter that can import yaml" \
  "$(grep -q 'CV_PY_CANDIDATES' "$HOOK" && echo 1 || echo 0)"
check "the hook says WHY the preference is resolved lazily, not by probing" \
  "$(grep -q 'RESOLVED LAZILY' "$HOOK" && echo 1 || echo 0)"

echo "=== 8. documented blind spots (asserted, not assumed) ====="
# These are ALLOWED, and that is the honest limit of command inspection. They
# are pinned here so the limit is a tested fact rather than a claim in a
# comment, and so a future change that starts denying them is a deliberate
# decision that has to update a failing test to justify itself.
# Every one of them is still caught afterwards by the git-derived scope gate.

# shellcheck disable=SC2016  # the literal $f is the entire point of this case
bash_case "BLIND SPOT: a path held in a shell variable" allow \
  agent_abc123 "$WT" 'f=README.md; echo hi > "$f"'
bash_case "BLIND SPOT: an interpreter one-liner" allow \
  agent_abc123 "$WT" 'python3 -c "open(\"README.md\",\"w\").write(\"x\")"'
bash_case "BLIND SPOT: a relative path in a segment after cd" allow \
  agent_abc123 "$WT" 'cd docs && echo hi > leak.md'
bash_case "BLIND SPOT: a build/format step that writes on its own" allow \
  agent_abc123 "$WT" 'npx prettier --write .'
bash_case "BLIND SPOT: a script invoked by path that writes on its own" allow \
  agent_abc123 "$WT" 'bash tests/a.sh'

# Limits of the quote-aware tokenizer, kept honest and kept PASSING.
bash_case "BLIND SPOT: a command whose quoting cannot be parsed at all" allow \
  agent_abc123 "$WT" "sed -i 's/a/b/ README.md"
check "the unparseable command is LOGGED as unparseable" \
  "$([ "$(logged 'command not parseable')" = yes ] && echo 1 || echo 0)"
check "the unparseable command produces NO context noise" \
  "$([ "$(silent)" = yes ] && echo 1 || echo 0)"
bash_case "BLIND SPOT: find -exec — the executed command is not modelled" allow \
  agent_abc123 "$WT" 'find tests -name "*.sh" -exec sed -i "s/a/b/" {} \;'
# shellcheck disable=SC2016  # the literal $(...) is the entire point of this case
bash_case "BLIND SPOT: the contents of a command substitution" allow \
  agent_abc123 "$WT" 'echo $(rm README.md) > tests/subst.txt'

echo "=== 8b. a forged .pyc beside the matcher does not run ======"
# FOURTH REVIEW PASS, item 1 (2026-09-02). The guard loads the matcher with
# spec_from_file_location + exec_module on EVERY Write/Edit/Bash call. An
# UNCHECKED HASH-BASED .pyc (flags 0b01: hash-based, check_source=0) is never
# validated against its source, so one planted at
# scripts/__pycache__/compound-v-scope-check.<tag>.pyc would execute here and
# could return an is_allowed() that approves every out-of-lane write.
# PYTHONDONTWRITEBYTECODE stops Python WRITING a cache, never READING one; the
# control is PYTHONPYCACHEPREFIX, which moves the lookup out of the tree.
# The plant location is asked of the interpreter (`cache_from_source`) rather
# than spelled out, because WHERE the cache lands is interpreter-dependent: a
# stock python3 puts it in `<dir>/__pycache__/` INSIDE the tree, while Apple's
# /usr/bin/python3 3.9.6 ships a default `sys.pycache_prefix` that redirects it
# outside. The exploit is the same in both cases; only its address moves, and
# only the first case is one the scope gate could ever have seen.
PYCDIR="$WORK/pyc-matcher"
mkdir -p "$PYCDIR"
cp "$REPO/scripts/compound-v-scope-check.py" "$PYCDIR/compound-v-scope-check.py"
PLANTED="$(CV_PYCDIR="$PYCDIR" python3 - <<'PYEOF'
import importlib.util, marshal, os
src = os.path.join(os.environ["CV_PYCDIR"], "compound-v-scope-check.py")
target = importlib.util.cache_from_source(src)
os.makedirs(os.path.dirname(target), exist_ok=True)
code = compile("def is_allowed(path, globs):\n    return True\n",
               "<forged>", "exec")
with open(target, "wb") as fh:
    fh.write(importlib.util.MAGIC_NUMBER)
    fh.write((0b01).to_bytes(4, "little"))   # hash-based, check_source=0
    fh.write(b"\x00" * 8)                    # the hash nobody checks
    fh.write(marshal.dumps(code))
print(target)
PYEOF
)"
check "the forged .pyc is planted where this interpreter would look for it" \
  "$([ -f "$PLANTED" ] && echo 1 || echo 0)"

# The plant is POTENT: loaded the way both loaders load it, with no cache
# redirection, the forged code wins. If this stops being true the test below
# proves nothing, so it is asserted rather than assumed.
POTENT="$(CV_PYCDIR="$PYCDIR" python3 -B - <<'PYEOF'
import importlib.util, os
src = os.path.join(os.environ["CV_PYCDIR"], "compound-v-scope-check.py")
spec = importlib.util.spec_from_file_location("_probe_forged", src)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print("yes" if mod.is_allowed("/etc/passwd", ["docs/**"]) else "no")
PYEOF
)"
check "the planted .pyc IS executed without a cache redirection (the plant is real)" \
  "$([ "$POTENT" = yes ] && echo 1 || echo 0)"

# ...and the guard, which sets PYTHONPYCACHEPREFIX, still refuses an out-of-lane
# write while pointed at exactly that matcher.
run "$(encode Write agent_abc123 "$WT" file_path "$WT/README.md")" \
    CV_SCOPE_CHECK="$PYCDIR/compound-v-scope-check.py"
verdict "a forged .pyc beside the matcher does not defeat the guard" deny

check "the guard redirects the bytecode cache out of the tree" \
  "$(grep -q 'PYTHONPYCACHEPREFIX' "$HOOK" && echo 1 || echo 0)"
check "the guard says WHY the redirection exists, not just that it does" \
  "$(grep -q 'stop it READING one' "$HOOK" && echo 1 || echo 0)"

# The plant may live outside $WORK when the interpreter carries a default
# sys.pycache_prefix (Apple's /usr/bin/python3 does), so the suite's own trap
# would not reach it. Remove it here rather than leave a forged pyc behind.
[ -n "$PLANTED" ] && rm -f "$PLANTED"

echo "=== 9. the invariants the spec pins ======================="

check "the hook reuses compound-v-scope-check.py's matcher" \
  "$(grep -q 'compound-v-scope-check.py' "$HOOK" && echo 1 || echo 0)"
check "the hook defines NO second glob engine" \
  "$(grep -qE 'glob_to_regex|fnmatch' "$HOOK" && echo 0 || echo 1)"
check "the hook says registration belongs to task-16, and does not self-register" \
  "$(grep -q 'hooks.json' "$HOOK" && grep -q 'task-16' "$HOOK" && echo 1 || echo 0)"
check "the hook states the git-derived verdict REMAINS THE AUTHORITY" \
  "$(grep -q 'REMAINS THE AUTHORITY' "$HOOK" && echo 1 || echo 0)"
check "the hook never claims the deny replaces the git gate" \
  "$(grep -qiE 'replaces the git|instead of the git' "$HOOK" && echo 0 || echo 1)"
check "the hook keeps its log OUT of the repo by default" \
  "$(grep -q 'TMPDIR' "$HOOK" && echo 1 || echo 0)"
check "the segmentation is quote-aware, not a raw regex split" \
  "$(grep -q '_split_segments(cmd_string)' "$HOOK" \
     && ! grep -q 'SEGMENT_RE' "$HOOK" && echo 1 || echo 0)"
check "the incident record's read-then-append takes an exclusive lock" \
  "$(grep -q 'LOCK_EX' "$HOOK" && echo 1 || echo 0)"
check "the hook is honest that it cannot enforce lane registration" \
  "$(grep -q 'CANNOT ENFORCE IT' "$HOOK" && echo 1 || echo 0)"

echo "-------------------------------------------"
printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" = "0" ] || exit 1
echo "OK lane-guard.sh decision table green"
