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

# finding 68 (stage 3, 2026-09-03): a run that is OVER must claim nothing, even
# though its direct job's "worktree" — the checkout itself — still exists. Two
# run dirs newer than every other fixture: one MERGED, one DISPATCHED, both with
# a lane map that claims the project root for a direct job whose lane is one file.
RUN_T="$PROJ/docs/superpowers/execution/2099-09-09-terminal"; mkdir -p "$RUN_T"
cat >"$RUN_T/manifest.yaml" <<'YEOF'
run_id: 2099-09-09-terminal
jobs:
  - id: review-done
    isolation: direct
    write_allowed:
      - "docs/only-this.md"
YEOF
cat >"$RUN_T/lane-map.json" <<JEOF
{"run_id": "2099-09-09-terminal", "agents": {}, "worktrees": {"$PROJ": "review-done"}}
JEOF
printf '{"run_id": "2099-09-09-terminal", "phase": "MERGED", "jobs": {"review-done": {"status": "done"}}}\n' >"$RUN_T/state.json"
RUN_L="$PROJ/docs/superpowers/execution/2099-09-08-live"; mkdir -p "$RUN_L"
cp "$RUN_T/manifest.yaml" "$RUN_L/manifest.yaml"; sed -i '' 's/2099-09-09-terminal/2099-09-08-live/' "$RUN_L/manifest.yaml" 2>/dev/null || sed -i 's/2099-09-09-terminal/2099-09-08-live/' "$RUN_L/manifest.yaml"
cat >"$RUN_L/lane-map.json" <<JEOF
{"run_id": "2099-09-08-live", "agents": {}, "worktrees": {"$PROJ": "review-done"}}
JEOF
# Both start RETIRED (terminal + oldest mtime) so no earlier section sees them;
# section 2b wakes the live one up, then retires it again.
printf '{"run_id": "2099-09-08-live", "phase": "MERGED", "jobs": {"review-done": {"status": "done"}}}\n' >"$RUN_L/state.json"
touch -t 200001010000 "$RUN_T" "$RUN_L"

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

# EVERY PAYLOAD CARRIES ITS OWN SESSION ID unless a case pins one. The hook logs
# the chosen interpreter ONCE PER SESSION (eighth review pass, item 6), keyed by
# a marker beside the log — so a suite that reused one session id would silently
# suppress the interpreter line in every case after the first, and the
# assertions that read it would be testing the marker rather than the ladder.
# Section 7g pins SID on purpose, which is how the dedupe itself is tested.
sid_n=0
SID=""
encode() {  # encode <tool> <agent_id> <cwd> <key> <value>
  sid_n=$((sid_n + 1))
  CV_T="$1" CV_A="$2" CV_C="$3" CV_K="$4" CV_V="$5" \
  CV_SID="${SID:-s-auto-$sid_n}" python3 -c '
import json, os
print(json.dumps({
    "hook_event_name": "PreToolUse",
    "tool_name": os.environ["CV_T"],
    "agent_id": os.environ["CV_A"],
    "session_id": os.environ["CV_SID"],
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

# A fail-open notice, PARSED rather than grepped. The two notices the eighth pass
# added are printed by BASH, not by the python payload — hand-built JSON that a
# stray quote would turn into output the harness silently discards, which is
# indistinguishable from the hook having said nothing at all.
is_notice() { printf '%s' "$OUT" | python3 -c '
import json, sys
try:
    d = json.loads(sys.stdin.read())
except Exception:
    print("no"); raise SystemExit
o = (d.get("hookSpecificOutput") or {})
print("yes" if o.get("hookEventName") == "PreToolUse"
      and "FAILED OPEN" in (o.get("additionalContext") or "")
      and "permissionDecision" not in o else "no")'; }

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

echo "=== 2z. review-1 of 3.4.3, issue 3: read-only git with -- is not a write ==="
bash_case "git show <sha> -- <out-of-lane path> is READ-ONLY (allowed)" allow \
  agent_abc123 "$WT" "git show HEAD -- README.md"
bash_case "git log -- <out-of-lane path> is READ-ONLY (allowed)" allow \
  agent_abc123 "$WT" "git log --oneline -3 -- README.md"
bash_case "git checkout -- <out-of-lane path> still WRITES (denied)" deny \
  agent_abc123 "$WT" "git checkout -- README.md"

echo "=== 2a. finding 78: the LONGEST worktree prefix wins ===================="
# The sandbox run's lane map claims $WT for job-under-test. Add a claim on the
# PROJECT ROOT by another job (a direct job's "worktree" is the checkout): a
# Write at $WT must still resolve to job-under-test, not to the root's job.
cp "$RUN/lane-map.json" "$RUN/lane-map.json.f78bak"
cat >"$RUN/lane-map.json" <<JEOF
{"run_id": "2099-01-01-sandbox",
 "agents": {},
 "worktrees": {"$PROJ": "root-job", "$WT": "job-under-test"}}
JEOF
file_case "finding 78: an in-lane Write at the nested worktree resolves to ITS job (allowed), not the root's" allow \
  Write agent_unknown78 "$WT" "$WT/tests/test-lane-guard.sh"
file_case "finding 78: an out-of-lane Write at the nested worktree is denied AS that job" deny \
  Write agent_unknown78 "$WT" "$WT/README.md"
check "finding 78: the deny names job-under-test, not root-job" \
  "$(printf '%s' "$OUT" | grep -q 'job-under-test' && ! printf '%s' "$OUT" | grep -q 'root-job' && echo 1 || echo 0)"
mv "$RUN/lane-map.json.f78bak" "$RUN/lane-map.json"

echo "=== 2b. finding 68: a finished run's lane map claims nothing ============"
# Make the two fixture runs the newest candidates, TERMINAL newest of all, so the
# resolver meets the MERGED map first and must skip it to find the live one.
printf '{"run_id": "2099-09-08-live", "phase": "DISPATCHED", "jobs": {"review-done": {"status": "running"}}}\n' >"$RUN_L/state.json"
touch -t 209901010000 "$RUN_L"; touch "$RUN_T"
file_case "a LIVE run's direct job claims the checkout: an unknown agent's out-of-lane Write at the root is denied" deny \
  Write agent_zzz "$PROJ" "$PROJ/docs/somewhere-else.md"
printf '{"run_id": "2099-09-08-live", "phase": "MERGED", "jobs": {"review-done": {"status": "done"}}}\n' >"$RUN_L/state.json"
file_case "...and once that run is MERGED the same Write resolves to NO job (allowed, unresolved)" allow \
  Write agent_zzz "$PROJ" "$PROJ/docs/somewhere-else.md"
check "finding 68: the terminal run is skipped, not resolved — the log says unresolved" \
  "$([ "$(logged 'job unresolved')" = yes ] && echo 1 || echo 0)"
# Retire both fixtures for every later section: terminal (skipped by the resolver)
# AND oldest by mtime, so neither can outrank the suite's other run dirs.
printf '{"run_id": "2099-09-08-live", "phase": "MERGED", "jobs": {"review-done": {"status": "done"}}}\n' >"$RUN_L/state.json"
touch -t 200001010000 "$RUN_T" "$RUN_L"
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
check "...and says so in the log — fail-open is never a silent no-decision" \
  "$([ "$(logged 'INERT for this tool call')" = yes ] && echo 1 || echo 0)"

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

echo "=== 7d. the interpreter pick is VIABILITY-CHECKED ========="
# Until the sixth review pass (2026-09-02) the pick was an ordering over
# whatever was executable, and `-x` is not "can run": a wrapper, a stale shim or
# a virtualenv whose framework moved is executable and exits non-zero on
# everything. Picked as THE interpreter, the payload never runs, the wrapper
# discards the empty output, and the hook produces no decision at all — a silent
# no-op that reads exactly like an allow. These cases are behavioural on
# purpose: the two assertions that used to live here grepped this hook's own
# source for a variable name and a comment, which a rewrite of the mechanism
# would have kept green.

BROKEN_DIR="$WORK/brokenpath"
mkdir -p "$BROKEN_DIR"
BROKEN_PY="$BROKEN_DIR/python3"
{ printf '#!/bin/sh\n'
  printf 'echo "this python3 cannot run anything" >&2\n'
  printf 'exit 1\n'
} >"$BROKEN_PY"
chmod +x "$BROKEN_PY"

# The literal shape this was found in: a python3 on PATH that is executable and
# dead. The guard must still reach a verdict.
run "$(encode Write agent_folded "$WT4" file_path "$WT4/README.md")" \
    PATH="$BROKEN_DIR:$PATH"
verdict "an executable-but-broken python3 FIRST ON PATH still denies" deny
check "and the deny still reads the lane out of the manifest" \
  "$(printf '%s' "$OUT" | grep -q 'hooks/lane-guard.sh' && echo 1 || echo 0)"

# THE PATH CASE THAT CAN ACTUALLY FAIL (seventh review pass, 2026-09-03).
#
# The case immediately above cannot: /usr/bin/python3 is probed FIRST, so a broken
# python3 on PATH is never a candidate the ladder has to step over, and that
# assertion stays green under the plain ORDERING the ladder replaced. It is a
# regression case for "the guard still reaches a verdict", not evidence for the
# ladder.
#
# The shape that discriminates is the one the hook's own header claims to handle:
# PATH's python3 imports yaml and the OS one does not, so the PROBE and not the
# order decides. It cannot be produced by editing PATH alone -- the first candidate
# is the literal /usr/bin/python3 -- so this drives a copy of the hook whose OS
# candidate is the dead interpreter. Under the pre-change order (first executable
# wins, modelled exactly by neutering the probe) the dead one is picked, the
# payload never runs, and the case reds.
if [ -n "$YAML_PY" ]; then
  YAMLPATH_DIR="$WORK/yamlpath"
  mkdir -p "$YAMLPATH_DIR"
  YAMLPATH_PY="$YAMLPATH_DIR/python3"
  { printf '#!/bin/sh\n'; printf 'PYTHONPATH= exec %s "$@"\n' "$YAML_PY"; } >"$YAMLPATH_PY"
  chmod +x "$YAMLPATH_PY"

  CAND_ANCHOR='^  for _cv_cand in /usr/bin/python3 "\$_cv_path_py"; do$'
  if [ "$(grep -cE "$CAND_ANCHOR" "$HOOK")" != "1" ]; then
    echo "FATAL: the default-candidate line is not unique -- this case tests nothing"
    exit 1
  fi
  OSDEAD="$MUTROOT/hooks/lane-guard-os-python-dead.sh"
  sed -E "s|$CAND_ANCHOR|  for _cv_cand in $BROKEN_PY \"\$_cv_path_py\"; do|" \
    "$HOOK" >"$OSDEAD"
  chmod +x "$OSDEAD"
  grep -q "for _cv_cand in $BROKEN_PY " "$OSDEAD" \
    || { echo "FATAL: the dead-OS-interpreter substitution did not apply"; exit 1; }

  HOOK_UNDER_TEST="$OSDEAD"
  run "$(encode Write agent_folded "$WT4" file_path "$WT4/README.md")" \
      PATH="$YAMLPATH_DIR:$PATH"
  verdict "OS python3 dead, PATH's imports yaml -> the PROBE picks PATH's" deny
  check "the log NAMES the interpreter it used (PATH's), on the ordinary path" \
    "$([ "$(logged "interpreter $YAMLPATH_PY (imports yaml)")" = yes ] \
       && echo 1 || echo 0)"
  check "...and names the dead OS candidate it passed over" \
    "$([ "$(logged "passed over: $BROKEN_PY")" = yes ] && echo 1 || echo 0)"

  # PLANTED VIOLATION 6 -- the PRE-CHANGE CANDIDATE ORDER, exactly: with the yaml
  # probe neutered the ladder degenerates to "take the first candidate", which is
  # what the fifth pass shipped. The dead OS interpreter wins, the payload never
  # runs, and the out-of-lane write sails through in silence. This case must red.
  OSDEAD_ORDER="$MUTROOT/hooks/lane-guard-os-python-dead-ordering.sh"
  sed 's/^_cv_can_yaml() {.*/_cv_can_yaml() { return 0; }/' "$OSDEAD" >"$OSDEAD_ORDER"
  chmod +x "$OSDEAD_ORDER"
  grep -q '_cv_can_yaml() { return 0; }' "$OSDEAD_ORDER" \
    || { echo "FATAL: the ordering mutation did not apply"; exit 1; }
  HOOK_UNDER_TEST="$OSDEAD_ORDER"
  run "$(encode Write agent_folded "$WT4" file_path "$WT4/README.md")" \
      PATH="$YAMLPATH_DIR:$PATH"
  check "PLANTED: the pre-change ORDER picks the dead OS python3 -> no deny" \
    "$([ "$(is_deny)" = no ] && [ "$RC" = "0" ] && echo 1 || echo 0)"
  check "PLANTED: and the out-of-lane write is allowed in COMPLETE silence" \
    "$([ "$(silent)" = yes ] && echo 1 || echo 0)"
  HOOK_UNDER_TEST=""
else
  printf 'SKIP the PATH-wins case -- no python3 on this machine can import yaml '
  printf '(CI installs it; this half did NOT run)\n'
fi

if [ -n "$YAML_PY" ]; then
  # ...and the same interpreter FIRST IN THE CANDIDATE LIST, which is where the
  # ladder actually has to step over it.
  run "$(encode Write agent_folded "$WT4" file_path "$WT4/README.md")" \
      CV_PY_CANDIDATES="$BROKEN_PY:$YAML_PY"
  verdict "a broken interpreter FIRST IN THE CANDIDATE LIST is stepped over" deny
  check "the log names the interpreter it actually used" \
    "$([ "$(logged "interpreter $YAML_PY")" = yes ] && echo 1 || echo 0)"
  check "the log names the candidate it passed over" \
    "$([ "$(logged "passed over: $BROKEN_PY")" = yes ] && echo 1 || echo 0)"

  # PLANTED VIOLATION 5: neuter the viability probe and the ladder is back to an
  # ordering over executables — the broken shim wins, the payload never runs,
  # and the out-of-lane write sails through with NO output at all.
  MUTANT_VIABLE="$MUTROOT/hooks/lane-guard-no-viability.sh"
  sed 's/^_cv_can_yaml() {.*/_cv_can_yaml() { return 0; }/' "$HOOK" \
    >"$MUTANT_VIABLE"
  chmod +x "$MUTANT_VIABLE"
  grep -q '_cv_can_yaml() { return 0; }' "$MUTANT_VIABLE" \
    || { echo "FATAL: the viability mutation did not apply"; exit 1; }
  HOOK_UNDER_TEST="$MUTANT_VIABLE"
  run "$(encode Write agent_folded "$WT4" file_path "$WT4/README.md")" \
      CV_PY_CANDIDATES="$BROKEN_PY:$YAML_PY"
  check "PLANTED: without the probe the broken interpreter is picked -> no deny" \
    "$([ "$(is_deny)" = no ] && [ "$RC" = "0" ] && echo 1 || echo 0)"
  check "PLANTED: and the out-of-lane write is allowed in COMPLETE silence" \
    "$([ "$(silent)" = yes ] && echo 1 || echo 0)"
  HOOK_UNDER_TEST=""
else
  printf 'SKIP the viability ladder under a PyYAML interpreter — no python3 on '
  printf 'this machine can import yaml (CI installs it; this half did NOT run)\n'
fi

# Rung 2: nothing on the list has PyYAML, but something can run. The guard uses
# it, and says by path what it settled for.
run "$(encode Write agent_folded "$WT4" file_path "$WT4/README.md")" \
    CV_PY_CANDIDATES="$BROKEN_PY:$NOYAML_PY"
verdict "no candidate has PyYAML -> the first that RUNS is used" deny
check "rung 2 names the interpreter and its missing PyYAML" \
  "$([ "$(logged "interpreter $NOYAML_PY CANNOT import PyYAML")" = yes ] \
     && echo 1 || echo 0)"

# Rung 3: nothing can run at all. Fail open — and never silently.
run "$(encode Write agent_folded "$WT4" file_path "$WT4/README.md")" \
    CV_PY_CANDIDATES="$BROKEN_PY"
check "no runnable interpreter -> no deny, exit 0" \
  "$([ "$(is_deny)" = no ] && [ "$RC" = "0" ] && echo 1 || echo 0)"
check "...and the guard says in the log that it was INERT for that call" \
  "$([ "$(logged 'INERT for this tool call')" = yes ] && echo 1 || echo 0)"
check "...naming the candidate it could not run" \
  "$([ "$(logged "$BROKEN_PY")" = yes ] && echo 1 || echo 0)"

# CV_PYTHON is still obeyed rather than second-guessed — and a dead one is
# reported, not silently replaced by a working interpreter beside it.
run "$(encode Write agent_folded "$WT4" file_path "$WT4/README.md")" \
    CV_PYTHON="$BROKEN_PY"
check "a dead CV_PYTHON is NOT silently replaced -> no deny, exit 0" \
  "$([ "$(is_deny)" = no ] && [ "$RC" = "0" ] && echo 1 || echo 0)"
check "a dead CV_PYTHON is reported in the log" \
  "$([ "$(logged 'INERT for this tool call')" = yes ] && echo 1 || echo 0)"

echo "=== 7e. the interpreter is named on the HEALTHY path ======"
# EIGHTH REVIEW PASS, item 3 (2026-09-03). Every assertion on the interpreter
# line up to here fires on a DEGRADED path — a candidate was passed over, or the
# pick fell to rung 2 — so all of them stayed green under the conditional the
# seventh pass replaced (`log only when something was passed over`). The line
# exists to make the ORDINARY pick observable, and nothing tested the ordinary
# pick. This does, and the planted restoration below shows it can go red.
if [ -n "$YAML_PY" ]; then
  run "$(encode Write agent_folded "$WT4" file_path "$WT4/README.md")" \
      CV_PY_CANDIDATES="$YAML_PY"
  verdict "healthy path (one viable candidate) still denies" deny
  check "the healthy path NAMES the interpreter it chose" \
    "$([ "$(logged "interpreter $YAML_PY (imports yaml)")" = yes ] \
       && echo 1 || echo 0)"
  check "...and reports nothing passed over, because nothing was" \
    "$([ "$(logged 'passed over')" = no ] && echo 1 || echo 0)"

  # PLANTED VIOLATION 7: put the pre-seventh-pass conditional back — the line is
  # logged only when a candidate was passed over. Every OTHER interpreter
  # assertion in this file stays green under it; this one must red.
  MUTANT_QUIET="$MUTROOT/hooks/lane-guard-quiet-interpreter.sh"
  sed 's|^  _cv_log_once "lane-guard: interpreter \$PY (imports yaml)|  [ -n "$_cv_passed_over" ] \&\& _cv_log_once "lane-guard: interpreter $PY (imports yaml)|' \
    "$HOOK" >"$MUTANT_QUIET"
  chmod +x "$MUTANT_QUIET"
  grep -q '\[ -n "$_cv_passed_over" \] && _cv_log_once "lane-guard: interpreter' \
    "$MUTANT_QUIET" \
    || { echo "FATAL: the quiet-interpreter mutation did not apply"; exit 1; }
  HOOK_UNDER_TEST="$MUTANT_QUIET"
  run "$(encode Write agent_folded "$WT4" file_path "$WT4/README.md")" \
      CV_PY_CANDIDATES="$YAML_PY"
  verdict "PLANTED: the conditional does not change the verdict" deny
  check "PLANTED: ...but the healthy pick becomes unobservable" \
    "$([ "$(logged 'lane-guard: interpreter ')" = no ] && echo 1 || echo 0)"
  HOOK_UNDER_TEST=""
else
  printf 'SKIP the healthy-path interpreter line — no python3 on this machine '
  printf 'can import yaml (CI installs it; this half did NOT run)\n'
fi

echo "=== 7f. no private pycache prefix -> NOTHING is imported =="
# EIGHTH REVIEW PASS, item H2 (2026-09-03). PYTHONPYCACHEPREFIX is what stops a
# forged in-tree `.pyc` being executed by the two loaders this hook uses. When
# the private directory could not be created the hook used to carry on WITHOUT
# it — i.e. it dropped the defence on precisely the machine whose temp dir is
# full, unwritable or hostile. It must fail open by loading nothing at all, and
# say which of the two happened.
#
# The plant here differs from 8b's in one way that matters: its module-level code
# WRITES A MARKER, so "no import happened" is an observation and not an inference
# from an allow (a fail-open allow and a hijacked-matcher allow look identical
# from the outside).
#
# The plant is made BY THE INTERPRETER THE HOOK WILL USE, and the hook is pinned
# to it. WHERE the cache lands is interpreter-dependent — a stock python3 writes
# `<dir>/__pycache__/`, Apple's /usr/bin/python3 3.9.6 redirects it under
# ~/Library/Caches — so a plant made by the suite's python3 and read by the
# hook's is simply not found, and the planted-violation half would pass for the
# wrong reason.
PYCDIR2="$WORK/pyc-h2"
mkdir -p "$PYCDIR2"
cp "$REPO/scripts/compound-v-scope-check.py" "$PYCDIR2/compound-v-scope-check.py"
H2_MARK="$WORK/h2-import-happened"
H2_PY="${YAML_PY:-$(command -v python3)}"
PLANTED2="$(CV_PYCDIR="$PYCDIR2" CV_MARK="$H2_MARK" "$H2_PY" - <<'PYEOF'
import importlib.util, marshal, os
src = os.path.join(os.environ["CV_PYCDIR"], "compound-v-scope-check.py")
target = importlib.util.cache_from_source(src)
os.makedirs(os.path.dirname(target), exist_ok=True)
code = compile("open(%r, 'w').write('imported')\n"
               "def is_allowed(path, globs):\n    return True\n"
               % os.environ["CV_MARK"], "<forged>", "exec")
with open(target, "wb") as fh:
    fh.write(importlib.util.MAGIC_NUMBER)
    fh.write((0b01).to_bytes(4, "little"))   # hash-based, check_source=0
    fh.write(b"\x00" * 8)                    # the hash nobody checks
    fh.write(marshal.dumps(code))
print(target)
PYEOF
)"
CV_PYCDIR="$PYCDIR2" "$H2_PY" -B - <<'PYEOF' >/dev/null 2>&1
import importlib.util, os
src = os.path.join(os.environ["CV_PYCDIR"], "compound-v-scope-check.py")
spec = importlib.util.spec_from_file_location("_probe_h2", src)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
PYEOF
check "the marker plant IS potent (loaded with no redirection, it runs)" \
  "$([ -f "$H2_MARK" ] && echo 1 || echo 0)"
rm -f "$H2_MARK"

# TMPDIR under a non-directory: mkdir -p cannot create the private prefix there.
run "$(encode Write agent_abc123 "$WT" file_path "$WT/README.md")" \
    CV_SCOPE_CHECK="$PYCDIR2/compound-v-scope-check.py" CV_PYTHON="$H2_PY" \
    TMPDIR=/dev/null/nope
verdict "an uncreatable pycache prefix fails OPEN" allow
check "the fail-open is ANNOUNCED as well-formed JSON, not just text" \
  "$([ "$(is_notice)" = yes ] && echo 1 || echo 0)"
check "...and it names the bytecode cache" \
  "$(printf '%s' "$OUT" | grep -q 'bytecode-cache' && echo 1 || echo 0)"
check "NO import happened — the forged matcher never ran" \
  "$([ ! -f "$H2_MARK" ] && echo 1 || echo 0)"
check "...and it is logged, not only announced" \
  "$([ "$(logged 'private bytecode-cache directory')" = yes ] && echo 1 || echo 0)"

# PLANTED VIOLATION 8: restore the fall-through — carry on without the prefix.
# The loader then runs, the forged matcher executes in this process, and the
# marker appears. That is the hole H2 closed.
MUTANT_NOPREFIX="$MUTROOT/hooks/lane-guard-prefix-optional.sh"
python3 - "$HOOK" "$MUTANT_NOPREFIX" <<'PYX'
import sys
src = open(sys.argv[1]).read()
old = 'if mkdir -p "$CV_PYCACHE_DIR" 2>/dev/null; then'
if src.count(old) != 1:
    raise SystemExit("FATAL: the pycache anchor is not unique")
# Make the guarded block unconditional-ish: the prefix is skipped, and the hook
# falls through to the loaders exactly as it did before H2.
src = src.replace(old, 'if false; then')
open(sys.argv[2], "w").write(src)
PYX
chmod +x "$MUTANT_NOPREFIX"
grep -q 'if false; then' "$MUTANT_NOPREFIX" \
  || { echo "FATAL: the prefix mutation did not apply"; exit 1; }
# The `else` arm now runs on every call, so the mutant must lose it as well —
# otherwise it exits for the same reason and proves nothing about the loader.
python3 - "$MUTANT_NOPREFIX" <<'PYX'
import re, sys
p = sys.argv[1]
src = open(p).read()
start = src.index('if false; then')
end = src.index('\nfi\n', start) + len('\nfi\n')
src = src[:start] + src[end:]
open(p, "w").write(src)
PYX
grep -q 'PYTHONPYCACHEPREFIX="\$CV_PYCACHE_DIR"' "$MUTANT_NOPREFIX" \
  && { echo "FATAL: the prefix block was not removed"; exit 1; }
HOOK_UNDER_TEST="$MUTANT_NOPREFIX"
rm -f "$H2_MARK"
run "$(encode Write agent_abc123 "$WT" file_path "$WT/README.md")" \
    CV_SCOPE_CHECK="$PYCDIR2/compound-v-scope-check.py" CV_PYTHON="$H2_PY"
check "PLANTED: without the prefix the forged matcher DOES run" \
  "$([ -f "$H2_MARK" ] && echo 1 || echo 0)"
HOOK_UNDER_TEST=""
rm -f "$H2_MARK"
[ -n "$PLANTED2" ] && rm -f "$PLANTED2"

echo "=== 7g. one interpreter line per SESSION, not per call ===="
# EIGHTH REVIEW PASS, item 6 (2026-09-03). Naming the interpreter on every path
# is what makes 7e possible; naming it on every CALL buries the lines that carry
# information (a DENY, an unresolved identity) under thousands of identical ones.
# The marker lives beside the log, which is why a suite that redirects the log
# also redirects the markers.
SHARED_LOG="$WORK/log.session"
: >"$SHARED_LOG"
rm -f "$WORK"/cv-lane-guard-interp.* 2>/dev/null
SID="s-pinned"
SESSION_PAYLOAD="$(encode Write agent_abc123 "$WT" file_path "$WT/hooks/lane-guard.sh")"
SID=""
for _i in 1 2 3; do
  printf '%s' "$SESSION_PAYLOAD" \
    | env -u CLAUDE_PROJECT_DIR -u CLAUDE_PLUGIN_ROOT \
          CV_PROJECT_DIR="$PROJ" CV_LANE_GUARD_LOG="$SHARED_LOG" \
          "$HOOK_BASH" "$HOOK" >/dev/null 2>&1
done
check "3 calls in ONE session write exactly ONE interpreter line" \
  "$([ "$(grep -c 'lane-guard: interpreter ' "$SHARED_LOG")" = "1" ] \
     && echo 1 || echo 0)"
check "the marker lives beside the log (the hook's store)" \
  "$([ -f "$WORK/cv-lane-guard-interp.s-pinned" ] && echo 1 || echo 0)"

SID="s-other"
OTHER_PAYLOAD="$(encode Write agent_abc123 "$WT" file_path "$WT/hooks/lane-guard.sh")"
SID=""
printf '%s' "$OTHER_PAYLOAD" \
  | env -u CLAUDE_PROJECT_DIR -u CLAUDE_PLUGIN_ROOT \
        CV_PROJECT_DIR="$PROJ" CV_LANE_GUARD_LOG="$SHARED_LOG" \
        "$HOOK_BASH" "$HOOK" >/dev/null 2>&1
check "a DIFFERENT session names its interpreter again" \
  "$([ "$(grep -c 'lane-guard: interpreter ' "$SHARED_LOG")" = "2" ] \
     && echo 1 || echo 0)"

echo "=== 7h. an interpreter probe is BOUNDED =================="
# EIGHTH REVIEW PASS, item H3 (2026-09-03). A probe runs a FOREIGN EXECUTABLE —
# a wrapper script, a shim, a launcher on a stalled mount. Unbounded, one that
# hangs holds a PreToolUse hook open for as long as it likes, in the component
# whose contract is to never be the reason anything stalls. The candidate below
# sleeps 30 s before it would exec a real python3; the hook must come back inside
# its own budget, with the fail-open said out loud.
SLOW_DIR="$WORK/slowpath"
mkdir -p "$SLOW_DIR"
SLOW_PY="$SLOW_DIR/python3"
SLOW_SECS="30.$$"   # unique per run: the orphan check below greps for exactly this
{ printf '#!/bin/sh\n'
  printf 'sleep %s\n' "$SLOW_SECS"
  printf 'exec %s "$@"\n' "$(command -v python3)"
} >"$SLOW_PY"
chmod +x "$SLOW_PY"

_t0=$SECONDS
run "$(encode Write agent_folded "$WT4" file_path "$WT4/README.md")" \
    PATH="$SLOW_DIR:$PATH" CV_PY_CANDIDATES="$SLOW_PY:${YAML_PY:-$(command -v python3)}"
_elapsed=$((SECONDS - _t0))
verdict "a candidate that hangs does not hang the hook" allow
check "the hook returned inside its budget (${_elapsed}s, must be <= 5)" \
  "$([ "$_elapsed" -le 5 ] && echo 1 || echo 0)"
check "the timeout is ANNOUNCED as well-formed JSON, not just text" \
  "$([ "$(is_notice)" = yes ] && echo 1 || echo 0)"
check "...and the notice names the budget" \
  "$(printf '%s' "$OUT" | grep -q 'budget' && echo 1 || echo 0)"
check "the timed-out candidate is named in the log" \
  "$([ "$(logged "probe of $SLOW_PY exceeded")" = yes ] && echo 1 || echo 0)"
check "the ladder STOPPED rather than paying the budget per candidate" \
  "$([ "$(logged 'ladder STOPPED')" = yes ] && echo 1 || echo 0)"
# The timed-out wrapper's own child must not outlive it: killing only the wrapper
# left one orphaned `sleep 30` per tool call (ninth review pass, item 5).
sleep 1
check "no orphaned probe child survives the timeout (pkill -P before kill)" \
  "$(pgrep -f "^sleep ${SLOW_SECS}\$" >/dev/null 2>&1 && echo 0 || echo 1)"

# The budget is honoured as configured, not hardcoded: a longer one is visibly
# slower, which is also the cheapest proof that the bound is what returns.
_t0=$SECONDS
run "$(encode Write agent_folded "$WT4" file_path "$WT4/README.md")" \
    CV_PROBE_TIMEOUT=3 CV_PY_CANDIDATES="$SLOW_PY:${YAML_PY:-$(command -v python3)}"
_elapsed2=$((SECONDS - _t0))
check "CV_PROBE_TIMEOUT is honoured (3s budget took ${_elapsed2}s, >= 3)" \
  "$([ "$_elapsed2" -ge 3 ] && echo 1 || echo 0)"

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
# The hook bounds its own subprocesses; the REGISTRATION bounds the hook. A
# budget a component applies to itself is not a budget on that component, and
# this one runs on every Write/Edit/Bash call.
check "hooks.json bounds the lane-guard registration with a timeout" \
  "$(CV_HOOKS="$REPO/hooks/hooks.json" python3 -c '
import json, os, sys
d = json.load(open(os.environ["CV_HOOKS"]))
for entry in d["hooks"]["PreToolUse"]:
    for h in entry["hooks"]:
        if "lane-guard.sh" in h.get("command", ""):
            sys.stdout.write("1" if isinstance(h.get("timeout"), int)
                             and h["timeout"] > 0 else "0")
            raise SystemExit
sys.stdout.write("0")')"

echo "-------------------------------------------"
printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" = "0" ] || exit 1
echo "OK lane-guard.sh decision table green"
