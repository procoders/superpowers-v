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
MUTANT="$WORK/lane-guard-writeedit-only.sh"
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

echo "-------------------------------------------"
printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" = "0" ] || exit 1
echo "OK lane-guard.sh decision table green"
