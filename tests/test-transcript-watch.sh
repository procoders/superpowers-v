#!/usr/bin/env bash
# tests/test-transcript-watch.sh — the transcript play-ahead watcher, driven END
# TO END through its CLI against a SYNTHETIC but shape-faithful session tree.
#
# WHY THIS FILE EXISTS SEPARATELY FROM --selftest
#   The script's own --selftest exercises its parsers. This file exercises what a
#   caller gets: discovery with no --wf, the exact signal SET, the dedup across
#   two --once runs with one --state, the --json shape, the exit code, and — the
#   claim the whole feature rests on — that a read-only watcher writes NOTHING
#   into the run directory or the repository.
#
# THE FIXTURE IS BUILT FROM THE REAL ON-DISK SHAPE, verified live in the Phase 1A
# archaeology (docs/superpowers/archaeology/2026-09-03-v3-4-2-transcript-watch.md):
#   <session>/subagents/workflows/<wf_id>/agent-<id>.jsonl + agent-<id>.meta.json
#   + journal.jsonl, one JSON object per line, `message.content` being EITHER a
#   bare string (the first line) or an array of tool_use / tool_result / text /
#   thinking items, plus `type:"attachment"` lines that carry no `message` at all.
#   A parser written against prose alone does not anticipate those three shapes,
#   so all three are planted here.
#
# TWO TRAPS FROM THE ARCHAEOLOGY ARE PLANTED DELIBERATELY:
#   * agent-3's FIRST register-lane is denied by the harness's bashCommandClamp
#     (a routine, real event) and its SECOND succeeds — the watcher must read the
#     job/cwd/isolation off the call that SUCCEEDED, never the denied attempt.
#   * agent-2 carries both the lane guard's real denial text and its
#     FAILED-OPEN notice. The first is a denial; the second is an
#     allow-with-notice and must NOT be reported as `denied`.

set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd -P)"
WATCH="${TRANSCRIPT_WATCH_SRC:-$REPO/scripts/compound-v-transcript-watch.py}"
PY="${PY:-/usr/bin/python3}"
# NOBODY WRITES BYTECODE, this suite included: the watcher imports two sibling
# scripts BY PATH, and a bytecode-writing interpreter would leave a real
# scripts/__pycache__/*.pyc in the checkout — which the scope gate, carrying no
# extension carve-out, correctly reports as an out-of-lane write.
export PYTHONDONTWRITEBYTECODE=1

pass=0
fail=0
ok()  { pass=$((pass + 1)); printf 'PASS %s\n' "$1"; }
bad() { fail=$((fail + 1)); printf 'FAIL %s\n' "$1"; }
check(){ if [ "$2" = "1" ]; then ok "$1"; else bad "$1"; fi; }

# --------------------------------------------------------------------------- #
# Preconditions — loud, never silently skipped. A test that quietly no-ops is
# how 25 of 29 selftests stopped running in v2.14.
# --------------------------------------------------------------------------- #
[ -f "$WATCH" ] || { echo "FATAL: $WATCH missing"; exit 1; }
command -v "$PY" >/dev/null 2>&1 || { echo "FATAL: $PY required"; exit 1; }
command -v git   >/dev/null 2>&1 || { echo "FATAL: git required"; exit 1; }
[ -f "$REPO/scripts/compound-v-scope-check.py" ] || {
  echo "FATAL: scope-check missing — the watcher IMPORTS its matcher"; exit 1; }
[ -f "$REPO/scripts/compound-v-validate-manifest.py" ] || {
  echo "FATAL: validate-manifest missing — the watcher IMPORTS its load_yaml"; exit 1; }

T="$(mktemp -d)"
cleanup() { rm -rf "$T"; }
trap cleanup EXIT

# --------------------------------------------------------------------------- #
# The sandbox: a git repo, a run directory inside it, one worktree-isolated job
# and one direct job, and a session tree with two workflow directories.
# --------------------------------------------------------------------------- #
SANDBOX="$T/repo"
RUN="$SANDBOX/docs/superpowers/execution/run1"
WTA="$T/wt-a"
SESSION="$T/session"
WF1="$SESSION/subagents/workflows/wf_test-1"
WF2="$SESSION/subagents/workflows/wf_other"

mkdir -p "$RUN" "$WTA/src" "$WF1" "$WF2"
git -C "$SANDBOX" init -q 2>/dev/null
git -C "$SANDBOX" config user.email t@t.t
git -C "$SANDBOX" config user.name t

cat >"$RUN/manifest.yaml" <<YAML
run_id: run1
jobs:
  - id: a
    isolation: worktree
    write_allowed:
      - "src/**"
  - id: b
    isolation: direct
    write_allowed:
      - "docs/**"
YAML

cat >"$RUN/lane-map.json" <<JSON
{
  "agents": {},
  "manifest": "$RUN/manifest.yaml",
  "run_id": "run1",
  "worktrees": {
    "$WTA": "a",
    "$SANDBOX": "b"
  }
}
JSON

cat >"$RUN/state.json" <<JSON
{
  "run_id": "run1",
  "phase": "DISPATCHING",
  "jobs": {
    "a": {"status": "running", "isolation": "worktree"},
    "b": {"status": "running", "isolation": "direct"}
  }
}
JSON

git -C "$SANDBOX" add -A >/dev/null 2>&1
git -C "$SANDBOX" commit -qm fixture >/dev/null 2>&1

NOW="$("$PY" -c 'import datetime;print(datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"))')"
OLD="$("$PY" -c 'import datetime;print((datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S.000Z"))')"
EMIT="$SANDBOX/scripts/compound-v-emit-workflow.py"

A1=a111111111111111
A2=a222222222222222
A3=a333333333333333
A4=a444444444444444
A5=a555555555555555

# --- agent-1: job `a` in its worktree. One in-lane write (no signal), one
# out-of-lane Write, one out-of-lane Bash redirect, one Traceback result. -----
cat >"$WF1/agent-$A1.jsonl" <<JSONL
{"type":"user","agentId":"$A1","timestamp":"$NOW","message":{"role":"user","content":"You are the implementer for Compound V job \`a\`. Register your lane against $RUN before anything else."}}
{"type":"attachment","agentId":"$A1","timestamp":"$NOW","attachment":{"type":"skill_listing","content":"- ads: ..."}}
{"type":"assistant","agentId":"$A1","timestamp":"$NOW","message":{"role":"assistant","content":[{"type":"thinking","thinking":"","signature":"x"}]}}
{"type":"assistant","agentId":"$A1","timestamp":"$NOW","message":{"role":"assistant","content":[{"type":"tool_use","id":"t1","name":"Bash","input":{"command":"$PY -B $EMIT register-lane --run-dir $RUN --job-id a --cwd $WTA --repo-root $SANDBOX --isolation worktree"}}]}}
{"type":"user","agentId":"$A1","timestamp":"$NOW","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"t1","is_error":false,"content":"{\"registered\": \"a\"}"}]}}
{"type":"assistant","agentId":"$A1","timestamp":"$NOW","message":{"role":"assistant","content":[{"type":"tool_use","id":"t2","name":"Write","input":{"file_path":"$WTA/src/ok.py","content":"print(1)"}}]}}
{"type":"user","agentId":"$A1","timestamp":"$NOW","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"t2","content":"File created successfully at: $WTA/src/ok.py"}]}}
{"type":"assistant","agentId":"$A1","timestamp":"$NOW","message":{"role":"assistant","content":[{"type":"tool_use","id":"t3","name":"Write","input":{"file_path":"$WTA/README.md","content":"nope"}}]}}
{"type":"user","agentId":"$A1","timestamp":"$NOW","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"t3","content":"File created successfully at: $WTA/README.md"}]}}
{"type":"assistant","agentId":"$A1","timestamp":"$NOW","message":{"role":"assistant","content":[{"type":"tool_use","id":"t4","name":"Bash","input":{"command":"echo x > $SANDBOX/notes.txt"}}]}}
{"type":"user","agentId":"$A1","timestamp":"$NOW","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"t4","content":""}]}}
{"type":"assistant","agentId":"$A1","timestamp":"$NOW","message":{"role":"assistant","content":[{"type":"tool_use","id":"t5","name":"Bash","input":{"command":"$PY -B $SANDBOX/x.py"}}]}}
{"type":"user","agentId":"$A1","timestamp":"$NOW","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"t5","is_error":true,"content":"Traceback (most recent call last):\n  File \"x.py\", line 1, in <module>\nValueError: boom"}]}}
JSONL

cat >"$WF1/agent-$A1.meta.json" <<JSON
{"agentType":"workflow-subagent","worktreePath":"$WTA","spawnedWithWorktree":true,"spawnDepth":1,"model":"opus"}
JSON

# --- agent-2: job `b`, direct, correctly registered. One REAL lane-guard denial
# and one FAILED-OPEN notice that must not be mistaken for one. ---------------
cat >"$WF1/agent-$A2.jsonl" <<JSONL
{"type":"user","agentId":"$A2","timestamp":"$NOW","message":{"role":"user","content":"You are the implementer for Compound V job \`b\` of $RUN."}}
{"type":"assistant","agentId":"$A2","timestamp":"$NOW","message":{"role":"assistant","content":[{"type":"tool_use","id":"u1","name":"Bash","input":{"command":"$PY -B $EMIT register-lane --run-dir $RUN --job-id b --cwd $SANDBOX --repo-root $SANDBOX --isolation direct"}}]}}
{"type":"user","agentId":"$A2","timestamp":"$NOW","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"u1","is_error":false,"content":"{\"registered\": \"b\"}"}]}}
{"type":"assistant","agentId":"$A2","timestamp":"$NOW","message":{"role":"assistant","content":[{"type":"tool_use","id":"u2","name":"Write","input":{"file_path":"$SANDBOX/docs/note.md","content":"in lane"}}]}}
{"type":"user","agentId":"$A2","timestamp":"$NOW","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"u2","is_error":true,"content":"Compound V lane guard: job 'b' is not allowed to write 'scripts/y.py'. Its lane is: docs/**"}]}}
{"type":"assistant","agentId":"$A2","timestamp":"$NOW","message":{"role":"assistant","content":[{"type":"tool_use","id":"u3","name":"Bash","input":{"command":"true"}}]}}
{"type":"user","agentId":"$A2","timestamp":"$NOW","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"u3","content":"Compound V lane-guard FAILED OPEN: no manifest could be read; allowing"}]}}
JSONL

cat >"$WF1/agent-$A2.meta.json" <<JSON
{"agentType":"workflow-subagent","spawnDepth":1,"model":"opus"}
JSON

# --- agent-3: job `a` again, but registered with --isolation direct and --cwd
# at the repository root while the manifest says worktree (finding 60's shape).
# Its FIRST attempt is denied by the bashCommandClamp for using "\$PWD". -------
cat >"$WF1/agent-$A3.jsonl" <<JSONL
{"type":"user","agentId":"$A3","timestamp":"$NOW","message":{"role":"user","content":"Second worker for job \`a\` of $RUN."}}
{"type":"assistant","agentId":"$A3","timestamp":"$NOW","message":{"role":"assistant","content":[{"type":"tool_use","id":"v1","name":"Bash","input":{"command":"$PY -B $EMIT register-lane --run-dir $RUN --job-id zzz-never-read --cwd \"\$PWD\" --isolation worktree"}}]}}
{"type":"user","agentId":"$A3","timestamp":"$NOW","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"v1","is_error":true,"content":"Permission to use Bash with command ... has been denied: this agent's Bash use is clamped to a fixed set of command forms (per-spawn bashCommandClamp)."}]}}
{"type":"assistant","agentId":"$A3","timestamp":"$NOW","message":{"role":"assistant","content":[{"type":"tool_use","id":"v2","name":"Bash","input":{"command":"$PY -B $EMIT register-lane --run-dir $RUN --job-id a --cwd $SANDBOX --repo-root $SANDBOX --isolation direct"}}]}}
{"type":"user","agentId":"$A3","timestamp":"$NOW","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"v2","is_error":false,"content":"{\"registered\": \"a\"}"}]}}
JSONL

cat >"$WF1/agent-$A3.meta.json" <<JSON
{"agentType":"workflow-subagent","spawnDepth":1}
JSON

# --- agent-4: never registered a lane, one read two hours ago, no journal
# result. `meta.json` deliberately carries NO `model` key (amendment 5). -------
cat >"$WF1/agent-$A4.jsonl" <<JSONL
{"type":"user","agentId":"$A4","timestamp":"$OLD","message":{"role":"user","content":"A worker with no lane."}}
{"type":"assistant","agentId":"$A4","timestamp":"$OLD","message":{"role":"assistant","content":[{"type":"tool_use","id":"w1","name":"Read","input":{"file_path":"$SANDBOX/README.md"}}]}}
{"type":"user","agentId":"$A4","timestamp":"$OLD","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"w1","content":"1\thello"}]}}
JSONL

cat >"$WF1/agent-$A4.meta.json" <<JSON
{"agentType":"workflow-subagent","description":"no model key here","spawnDepth":1}
JSON

cat >"$WF1/journal.jsonl" <<JSONL
{"type":"started","key":"k1","agentId":"$A1"}
{"type":"started","key":"k2","agentId":"$A2"}
{"type":"started","key":"k3","agentId":"$A3"}
{"type":"started","key":"k4","agentId":"$A4"}
{"type":"result","key":"k1","agentId":"$A1"}
{"type":"result","key":"k2","agentId":"$A2"}
{"type":"result","key":"k3","agentId":"$A3"}
JSONL

# --- wf_other: a DIFFERENT workflow in the same session that never mentions the
# run directory. Discovery must not pick it; addressed directly it shows the
# `(unregistered)` write policy. ----------------------------------------------
cat >"$WF2/agent-$A5.jsonl" <<JSONL
{"type":"user","agentId":"$A5","timestamp":"$NOW","message":{"role":"user","content":"An unrelated worker."}}
{"type":"assistant","agentId":"$A5","timestamp":"$NOW","message":{"role":"assistant","content":[{"type":"tool_use","id":"z1","name":"Write","input":{"file_path":"$SANDBOX/zzz.md","content":"x"}}]}}
{"type":"user","agentId":"$A5","timestamp":"$NOW","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"z1","content":"File created successfully"}]}}
JSONL
cat >"$WF2/journal.jsonl" <<JSONL
{"type":"started","key":"k9","agentId":"$A5"}
{"type":"result","key":"k9","agentId":"$A5"}
JSONL

# --------------------------------------------------------------------------- #
# 1. Discovery with NO --wf, and the exact signal set.
# --------------------------------------------------------------------------- #
ST="$T/state1.json"
OUT="$T/out1.txt"
"$PY" -B "$WATCH" --run-dir "$RUN" --transcripts "$SESSION" --once --state "$ST" >"$OUT" 2>"$T/err1.txt"
RC=$?

check "exit 0 on the advisory path" "$([ "$RC" = 0 ] && echo 1 || echo 0)"
check "discovery with no --wf found wf_test-1 by the run directory's path" \
      "$(grep -q 'wf_test-1' "$OUT" && echo 1 || echo 0)"
check "the out-of-lane Write is reported against job a (README.md)" \
      "$(grep -E '\ba\b.*out-of-lane.*README\.md' "$OUT" >/dev/null && echo 1 || echo 0)"
check "the out-of-lane Bash redirect is reported against job a (notes.txt)" \
      "$(grep -E '\ba\b.*out-of-lane.*notes\.txt' "$OUT" >/dev/null && echo 1 || echo 0)"
check "the IN-LANE write (src/ok.py) produces NO signal" \
      "$(grep -q 'src/ok.py' "$OUT" && echo 0 || echo 1)"
check "the Traceback result is reported as error" \
      "$(grep -E '\ba\b.*\berror\b.*Traceback' "$OUT" >/dev/null && echo 1 || echo 0)"
check "the lane guard's real denial is reported as denied against job b" \
      "$(grep -E '\bb\b.*\bdenied\b' "$OUT" >/dev/null && echo 1 || echo 0)"
check "...and the FAILED-OPEN notice is NOT a second denial" \
      "$([ "$(grep -c 'denied' "$OUT")" = 1 ] && echo 1 || echo 0)"
check "the mis-registered isolation is reported as wrong-cwd" \
      "$(grep -q 'wrong-cwd' "$OUT" && echo 1 || echo 0)"
check "...attributed to job a, read off the register-lane call that SUCCEEDED" \
      "$(grep -E 'wrong-cwd' "$OUT" | grep -qE '\ba\b' && echo 1 || echo 0)"
check "...never off the clamp-denied attempt (zzz-never-read is invisible)" \
      "$(grep -q 'zzz-never-read' "$OUT" && echo 0 || echo 1)"
check "the two-hour-old agent that never returned is reported as stall" \
      "$(grep -q 'stall' "$OUT" && echo 1 || echo 0)"
check "an agent with no register-lane call is named (unregistered)" \
      "$(grep -q '(unregistered)' "$OUT" && echo 1 || echo 0)"
check "EXACTLY six signals — no more, no fewer" \
      "$([ "$(grep -cE ' (out-of-lane|wrong-cwd|error|denied|stall) ' "$OUT")" = 6 ] && echo 1 || echo 0)"
check "the per-tick summary names the jobs and the agent counts" \
      "$(grep -E '^jobs: .*agents: [0-9]+ live, [0-9]+ returned' "$OUT" >/dev/null && echo 1 || echo 0)"

# --------------------------------------------------------------------------- #
# 2. The state file dedups: a second --once emits the summary and nothing else.
# --------------------------------------------------------------------------- #
OUT2="$T/out2.txt"
"$PY" -B "$WATCH" --run-dir "$RUN" --transcripts "$SESSION" --once --state "$ST" >"$OUT2" 2>&1
check "a second --once with the same --state repeats no signal" \
      "$([ "$(grep -cE ' (out-of-lane|wrong-cwd|error|denied|stall) ' "$OUT2")" = 0 ] && echo 1 || echo 0)"
check "...but still prints the summary" \
      "$(grep -q '^jobs: ' "$OUT2" && echo 1 || echo 0)"

# --------------------------------------------------------------------------- #
# 3. --json: one object per signal, with the six contracted keys.
# --------------------------------------------------------------------------- #
JOUT="$T/out3.json"
"$PY" -B "$WATCH" --run-dir "$RUN" --transcripts "$SESSION" --once --state "$T/state3.json" \
      --json >"$JOUT" 2>/dev/null
check "--json emits six parseable objects carrying ts/job/agent/signal/evidence/line" \
      "$("$PY" -B -c '
import json,sys
need={"ts","job","agent","signal","evidence","line"}
n=0
for raw in open(sys.argv[1]):
    raw=raw.strip()
    if not raw: continue
    o=json.loads(raw)
    if not isinstance(o,dict): sys.exit(1)
    if not need.issubset(o.keys()): sys.exit(1)
    n+=1
sys.exit(0 if n==6 else 1)' "$JOUT" && echo 1 || echo 0)"

# --------------------------------------------------------------------------- #
# 4. --wf overrides discovery; a session with no matching workflow says so
#    without crashing.
# --------------------------------------------------------------------------- #
OUT4="$T/out4.txt"
"$PY" -B "$WATCH" --run-dir "$RUN" --transcripts "$SESSION" --wf wf_other --once \
      --state "$T/state4.json" >"$OUT4" 2>&1
check "--wf overrides discovery and reads the named workflow" \
      "$(grep -q 'wf_other' "$OUT4" && echo 1 || echo 0)"
check "an unregistered agent's write is an out-of-lane candidate" \
      "$(grep -E '\(unregistered\).*out-of-lane.*zzz\.md' "$OUT4" >/dev/null && echo 1 || echo 0)"

mkdir -p "$T/empty"
OUT5="$T/out5.txt"
"$PY" -B "$WATCH" --run-dir "$RUN" --transcripts "$T/empty" --once \
      --state "$T/state5.json" >"$OUT5" 2>&1
RC5=$?
check "a session with no matching transcripts says so and exits 0" \
      "$([ "$RC5" = 0 ] && grep -qi 'no transcripts found' "$OUT5" && echo 1 || echo 0)"

# --------------------------------------------------------------------------- #
# 5. READ-ONLY: nothing is written into the run directory or the repository,
#    including when --state is left to its default (the OS temp dir).
# --------------------------------------------------------------------------- #
BEFORE="$(cd "$RUN" && find . | sort)"
"$PY" -B "$WATCH" --run-dir "$RUN" --transcripts "$SESSION" --once >/dev/null 2>&1
AFTER="$(cd "$RUN" && find . | sort)"
check "the run directory is byte-for-byte unchanged in its file list" \
      "$([ "$BEFORE" = "$AFTER" ] && echo 1 || echo 0)"
check "the repository working tree stays clean (default --state is NOT in it)" \
      "$([ -z "$(git -C "$SANDBOX" status --porcelain)" ] && echo 1 || echo 0)"

# --------------------------------------------------------------------------- #
# 6. One matcher, one YAML loader, one denial literal — verified in the source.
# --------------------------------------------------------------------------- #
check "the path matcher is imported BY PATH from compound-v-scope-check.py" \
      "$(grep -q 'compound-v-scope-check.py' "$WATCH" && grep -q 'spec_from_file_location' "$WATCH" && echo 1 || echo 0)"
check "...and no second glob matcher is written here (no fnmatch, no glob_to_regex)" \
      "$(grep -qE 'fnmatch|def glob_to_regex' "$WATCH" && echo 0 || echo 1)"
check "load_yaml is imported BY PATH from compound-v-validate-manifest.py" \
      "$(grep -q 'compound-v-validate-manifest.py' "$WATCH" && echo 1 || echo 0)"
check "...with no PyYAML import of its own" \
      "$(grep -qE '^ *import yaml|^ *import +yaml' "$WATCH" && echo 0 || echo 1)"
check "the denied signal's literal is defined exactly once, as a constant" \
      "$([ "$(grep -c "^DENY_LITERAL = \"Compound V lane guard: job '\"" "$WATCH")" = 1 ] && echo 1 || echo 0)"

# ...and the FAILED-OPEN notice is checked by BEHAVIOUR, not by a grep: the
# script is allowed to NAME the string in prose (it explains why it is not a
# denial); what it must never do is signal on it.
WF3="$SESSION/subagents/workflows/wf_openonly"
mkdir -p "$WF3"
cat >"$WF3/agent-$A5.jsonl" <<JSONL
{"type":"assistant","agentId":"$A5","timestamp":"$NOW","message":{"role":"assistant","content":[{"type":"tool_use","id":"y1","name":"Bash","input":{"command":"true"}}]}}
{"type":"user","agentId":"$A5","timestamp":"$NOW","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"y1","content":"Compound V lane-guard FAILED OPEN: no manifest could be read; allowing"}]}}
JSONL
OUT6="$T/out6.txt"
"$PY" -B "$WATCH" --run-dir "$RUN" --transcripts "$SESSION" --wf wf_openonly --once \
      --state "$T/state6.json" >"$OUT6" 2>&1
check "...so a FAILED-OPEN notice on its own produces no signal at all" \
      "$([ "$(grep -cE ' (out-of-lane|wrong-cwd|error|denied|stall) ' "$OUT6")" = 0 ] && echo 1 || echo 0)"

# --------------------------------------------------------------------------- #
# 7. The script's own --selftest, run through this suite so CI cannot lose it.
# --------------------------------------------------------------------------- #
"$PY" -B "$WATCH" --selftest >"$T/selftest.txt" 2>&1
RC7=$?
check "--selftest is green" "$([ "$RC7" = 0 ] && echo 1 || echo 0)"

# --------------------------------------------------------------------------- #
printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" = "0" ] || exit 1
exit 0
