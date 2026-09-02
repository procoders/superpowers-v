#!/usr/bin/env bash
# tests/test-epic-goal-stop.sh — the decision table of hooks/epic-goal-stop.sh,
# driven by SYNTHETIC STDIN.
#
# Repo precedent: tests/test-session-banner-staleness.sh tests hooks/session-banner.sh;
# no hook in this plugin ships an inline --selftest, so the test home is here.
#
# THE ONE RULE THIS FILE EXISTS TO DEFEND: a `Stop` hook that exits non-zero has
# BLOCKED the user's turn. So every single invocation below is asserted to exit
# 0, and a block is only ever recognised as valid JSON on stdout.
#
# Uses the repo's own scripts/compound-v-epic-state.py. Override with
# EPIC_STATE_SRC=<path> when running against a checkout whose copy predates the
# v2.18 --goal-status CLI.

set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd -P)"
HOOK_SRC="$REPO/hooks/epic-goal-stop.sh"
EPIC_STATE_SRC="${EPIC_STATE_SRC:-$REPO/scripts/compound-v-epic-state.py}"
# The interpreter the HOOK runs under. Set HOOK_BASH=/bin/bash on macOS to run
# the decision table against bash 3.2 — the oldest bash the plugin supports.
HOOK_BASH="${HOOK_BASH:-bash}"

pass=0
fail=0
ok()   { pass=$((pass + 1)); printf 'PASS %s\n' "$1"; }
bad()  { fail=$((fail + 1)); printf 'FAIL %s\n' "$1"; }
check(){ if [ "$2" = "1" ]; then ok "$1"; else bad "$1"; fi; }

# ---------------------------------------------------------------------------
# Preconditions — loud, never silently skipped.
# ---------------------------------------------------------------------------
[ -f "$HOOK_SRC" ] || { echo "FATAL: $HOOK_SRC missing"; exit 1; }
[ -x "$HOOK_SRC" ] || { echo "FATAL: $HOOK_SRC is not executable"; exit 1; }
command -v jq >/dev/null 2>&1 || { echo "FATAL: jq required to run these tests"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "FATAL: python3 required"; exit 1; }
[ -f "$EPIC_STATE_SRC" ] || { echo "FATAL: $EPIC_STATE_SRC missing"; exit 1; }
if ! python3 "$EPIC_STATE_SRC" --help 2>&1 | grep -q -- '--goal-status'; then
  echo "FATAL: $EPIC_STATE_SRC has no --goal-status (v2.18 Feature A). This is a"
  echo "       REAL failure, not a skip: the hook's only read path does not exist."
  exit 1
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# A sandbox "plugin root": the hook resolves its CLI as <hook dir>/../scripts/.
PLUGIN="$WORK/plugin"
mkdir -p "$PLUGIN/hooks" "$PLUGIN/scripts"
cp "$HOOK_SRC" "$PLUGIN/hooks/epic-goal-stop.sh"
chmod +x "$PLUGIN/hooks/epic-goal-stop.sh"
cp "$EPIC_STATE_SRC" "$PLUGIN/scripts/compound-v-epic-state.py"
HOOK="$PLUGIN/hooks/epic-goal-stop.sh"
ES="$PLUGIN/scripts/compound-v-epic-state.py"

STORE_BASE="$WORK/store"
mkdir -p "$STORE_BASE"
# The hook's store lives at $TMPDIR/compound-v-stop-hook.
HOOK_STORE="$STORE_BASE/compound-v-stop-hook"

IS_ROOT=0
[ "$(id -u)" = "0" ] && IS_ROOT=1

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# stdin_json <event> <session> <cwd> [stop_hook_active]
stdin_json() {
  jq -n --arg e "$1" --arg s "$2" --arg c "$3" \
        --argjson a "${4:-false}" \
        '{hook_event_name: $e, session_id: $s, cwd: $c, transcript_path: "/dev/null", stop_hook_active: $a}'
}

# run_hook <stdin> [extra env assignments...] -> sets RC / OUT / ERRLOG
# ALWAYS asserts rc == 0 — a non-zero exit from a Stop hook is a block.
# stdin is fed from a FILE, never a pipe: the hook legitimately exits before
# draining stdin on several paths (the jq guard, the event gate), and a pipe
# would hand the TEST a SIGPIPE that has nothing to do with the hook.
RC=0; OUT=""
run_hook() {
  local payload="$1"; shift
  local errf="$WORK/stderr.txt" inf="$WORK/stdin.json"
  printf '%s' "$payload" >"$inf"
  OUT="$(env TMPDIR="$STORE_BASE" "$@" "$HOOK_BASH" "$HOOK" <"$inf" 2>"$errf")"
  RC=$?
  if [ "$RC" -ne 0 ]; then
    bad "INVARIANT: hook exited $RC (a non-zero Stop-hook exit IS a block)"
    sed 's/^/    stderr| /' "$errf"
  fi
  return 0
}

# json_docs <string> -> how many JSON documents it contains
json_docs() { printf '%s' "${1:-}" | jq -s 'length' 2>/dev/null || echo "ERR"; }

is_block() {
  [ -n "${1:-}" ] || return 1
  [ "$(json_docs "$1")" = "1" ] || return 1
  [ "$(printf '%s' "$1" | jq -r '.decision // empty' 2>/dev/null)" = "block" ]
}

# mkproj <dir> — a git repo with a marathon epic state at the canonical path
mkproj() {
  local d="$1"
  mkdir -p "$d/docs/superpowers/execution/epics/e1" "$d/.claude" "$d/scripts"
  git -C "$d" init -q 2>/dev/null
  printf '%s' '[{"id":"f1","title":"F1","depends_on":[]}]' >"$d/feats.json"
  python3 "$ES" --init --stance marathon --features "$d/feats.json" \
    --epic-id e1 --title E1 --out "$d/docs/superpowers/execution/epics/e1/epic-state.json" >/dev/null
  printf 'print("hello")\n' >"$d/scripts/app.py"
  git -C "$d" add -A >/dev/null 2>&1
  git -C "$d" -c user.email=t@t -c user.name=t commit -qm init >/dev/null 2>&1
}

statefile() { printf '%s/docs/superpowers/execution/epics/e1/epic-state.json' "$1"; }

arm() { # arm <dir> <session> <max_continues> [condition]
  local d="$1" s="$2" m="$3" c="${4:-all_features_done}"
  python3 "$ES" --arm-goal --condition "$c" --session-id "$s" --max-continues "$m" \
    --state "$(statefile "$d")" >/dev/null 2>&1
}

sha256_of() { # sha256 of stdin, however this box spells it
  if command -v shasum >/dev/null 2>&1; then shasum -a 256 | cut -d' ' -f1
  else sha256sum | cut -d' ' -f1; fi
}

# The hook's store slot for a project+session — computed the same way the hook
# computes it: digest(canonical project root | session_id | arm_id).
slot_for() {
  local d="$1" s="$2" aid k
  aid="$(python3 "$ES" --goal-status --state "$(statefile "$d")" 2>/dev/null | jq -r '.arm_id // empty')"
  [ -n "$aid" ] || return 1
  k="$(printf '%s|%s|%s' "$(cd "$d" && pwd -P)" "$s" "$aid" | sha256_of)"
  printf '%s/goal-%s' "$HOOK_STORE" "$k"
}

fingerprint() { # content digest + mtime of a file
  local f="$1" h
  if command -v shasum >/dev/null 2>&1; then h="$(shasum -a 256 "$f" | cut -d' ' -f1)"
  else h="$(sha256sum "$f" | cut -d' ' -f1)"; fi
  printf '%s|%s' "$h" "$(python3 -c 'import os,sys;print(os.stat(sys.argv[1]).st_mtime_ns)' "$f")"
}

echo "== hooks/epic-goal-stop.sh decision table =="

# ---------------------------------------------------------------------------
# 1. Inert when nothing is armed
# ---------------------------------------------------------------------------
A="$WORK/projA"; mkproj "$A"
run_hook "$(stdin_json Stop sess-A "$A")"
check "absent armed record -> silent, exit 0" \
  "$([ "$RC" = "0" ] && [ -z "$OUT" ] && echo 1 || echo 0)"

# ---------------------------------------------------------------------------
# 2. THE EVENT GATE — the difference between working and trapping every
#    subagent Compound V dispatches.
# ---------------------------------------------------------------------------
arm "$A" sess-A 5
for ev in SubagentStop StopFailure PreCompact ""; do
  if [ -z "$ev" ]; then
    payload="$(jq -n --arg s sess-A --arg c "$A" \
      '{session_id: $s, cwd: $c, stop_hook_active: false}')"
    label="missing hook_event_name"
  else
    payload="$(stdin_json "$ev" sess-A "$A")"
    label="hook_event_name=$ev"
  fi
  run_hook "$payload"
  check "EVENT GATE: $label -> silent, exit 0 (armed goal ignored)" \
    "$([ "$RC" = "0" ] && [ -z "$OUT" ] && echo 1 || echo 0)"
done
check "EVENT GATE: no store slot was created by any non-Stop event" \
  "$([ ! -d "$HOOK_STORE" ] && echo 1 || echo 0)"

# ---------------------------------------------------------------------------
# 3. Session isolation
# ---------------------------------------------------------------------------
run_hook "$(stdin_json Stop sess-OTHER "$A")"
check "session mismatch -> silent, exit 0" \
  "$([ "$RC" = "0" ] && [ -z "$OUT" ] && echo 1 || echo 0)"

# ---------------------------------------------------------------------------
# 4. The happy path — armed, unmet, under the counter -> ONE block.
#    Plus: the hook must not have written epic-state.json.
# ---------------------------------------------------------------------------
SF="$(statefile "$A")"
before="$(fingerprint "$SF")"
run_hook "$(stdin_json Stop sess-A "$A")"
after="$(fingerprint "$SF")"
check "goal armed + unmet -> exactly ONE JSON block" \
  "$(is_block "$OUT" && echo 1 || echo 0)"
check "the block names the continuation count (1 of 5)" \
  "$(printf '%s' "$OUT" | jq -r '.reason' 2>/dev/null | grep -q '1 of 5' && echo 1 || echo 0)"
check "THE HOOK NEVER WRITES epic-state.json (digest + mtime unchanged)" \
  "$([ "$before" = "$after" ] && echo 1 || echo 0)"

run_hook "$(stdin_json Stop sess-A "$A" true)"
check "second Stop increments rather than restarting (2 of 5)" \
  "$(printf '%s' "$OUT" | jq -r '.reason' 2>/dev/null | grep -q '2 of 5' && echo 1 || echo 0)"
check "stop_hook_active=true does NOT stop the hook blocking (it would cap at one)" \
  "$(is_block "$OUT" && echo 1 || echo 0)"

# ---------------------------------------------------------------------------
# 5. Counter exhausted -> release the turn
# ---------------------------------------------------------------------------
B="$WORK/projB"; mkproj "$B"; arm "$B" sess-B 1
run_hook "$(stdin_json Stop sess-B "$B")"
check "counter: first continuation blocks (1 of 1)" "$(is_block "$OUT" && echo 1 || echo 0)"
run_hook "$(stdin_json Stop sess-B "$B" true)"
check "counter exhausted -> silent, exit 0" \
  "$([ "$RC" = "0" ] && [ -z "$OUT" ] && echo 1 || echo 0)"

# ---------------------------------------------------------------------------
# 6. Sequential re-arm starts at 0 (arm_id is part of the store key)
# ---------------------------------------------------------------------------
old_slot="$(slot_for "$B" sess-B)"
python3 "$ES" --disarm-goal --state "$(statefile "$B")" >/dev/null 2>&1
arm "$B" sess-B 1
new_slot="$(slot_for "$B" sess-B)"
check "SEQUENTIAL RE-ARM: a fresh arm_id means a fresh store slot" \
  "$([ "$old_slot" != "$new_slot" ] && echo 1 || echo 0)"
# A fresh turn (stop_hook_active=false) — the normal shape after a re-arm.
run_hook "$(stdin_json Stop sess-B "$B")"
check "SEQUENTIAL RE-ARM starts at 0 — the second epic does not inherit the first's count" \
  "$(is_block "$OUT" && printf '%s' "$OUT" | jq -r '.reason' | grep -q '1 of 1' && echo 1 || echo 0)"

# The deliberate conservative edge: a re-arm inside a turn that ALREADY blocked
# cannot be told apart from a swept store, so it fails OPEN. Stopping autonomy
# is the acceptable failure; granting an unbounded extra tranche is not.
python3 "$ES" --disarm-goal --state "$(statefile "$B")" >/dev/null 2>&1
arm "$B" sess-B 1
run_hook "$(stdin_json Stop sess-B "$B" true)"
check "RE-ARM mid-blocked-turn -> conservatively FAILS OPEN (documented, not silent)" \
  "$([ "$RC" = "0" ] && [ -z "$OUT" ] && echo 1 || echo 0)"

# ---------------------------------------------------------------------------
# 7. Two projects, one session, must not share a slot
# ---------------------------------------------------------------------------
C="$WORK/projC"; mkproj "$C"; arm "$C" sess-SHARED 5
D="$WORK/projD"; mkproj "$D"; arm "$D" sess-SHARED 5
run_hook "$(stdin_json Stop sess-SHARED "$C")"
c1="$(printf '%s' "$OUT" | jq -r '.reason' 2>/dev/null | grep -c '1 of 5')"
run_hook "$(stdin_json Stop sess-SHARED "$D")"
d1="$(printf '%s' "$OUT" | jq -r '.reason' 2>/dev/null | grep -c '1 of 5')"
check "TWO PROJECTS one session: each keeps its own counter (both at 1 of 5)" \
  "$([ "$c1" = "1" ] && [ "$d1" = "1" ] && echo 1 || echo 0)"

# ---------------------------------------------------------------------------
# 8. Goal genuinely MET -> release (and never claim completion for a dead epic)
# ---------------------------------------------------------------------------
E="$WORK/projE"; mkproj "$E"; arm "$E" sess-E 5
python3 "$ES" --update --feature f1 --status "done" --state "$(statefile "$E")" >/dev/null
python3 "$ES" --record-final-review --status passed --state "$(statefile "$E")" >/dev/null
run_hook "$(stdin_json Stop sess-E "$E")"
check "goal MET -> silent, exit 0" \
  "$([ "$RC" = "0" ] && [ -z "$OUT" ] && echo 1 || echo 0)"

# The headline distinction: is_terminal is ALSO true for a halted / breaker-
# tripped / unsatisfiable epic. Using it as the completion test would declare
# the goal met at the moment the epic FAILED. `--goal-status` reports met=false
# + should_continue=false here, and the hook must therefore release the turn
# WITHOUT blocking and WITHOUT burning a continuation.
F="$WORK/projF"; mkproj "$F"; arm "$F" sess-F 5
python3 "$ES" --record-disposition --feature f1 --disposition halt_epic \
  --reason "test halt" --state "$(statefile "$F")" >/dev/null 2>&1
term="$(python3 "$ES" --goal-status --state "$(statefile "$F")" | jq -r '.terminal, .met' | tr '\n' ' ')"
check "fixture check: the epic is terminal but the goal is NOT met ($term)" \
  "$([ "$term" = "true false " ] && echo 1 || echo 0)"
run_hook "$(stdin_json Stop sess-F "$F")"
check "epic TERMINAL but goal NOT met (halt_epic) -> silent, exit 0 (no fabricated completion)" \
  "$([ "$RC" = "0" ] && [ -z "$OUT" ] && echo 1 || echo 0)"
check "epic TERMINAL but goal NOT met -> no counter was burned (no slot created)" \
  "$([ ! -d "$(slot_for "$F" sess-F)" ] && echo 1 || echo 0)"

# ---------------------------------------------------------------------------
# 9. Fault injection — every one of these must exit 0 and emit nothing
# ---------------------------------------------------------------------------
G="$WORK/projG"; mkproj "$G"; arm "$G" sess-G 5
printf 'NOT JSON {{{\n' >"$(statefile "$G")"
run_hook "$(stdin_json Stop sess-G "$G")"
check "FAULT: corrupt epic-state.json -> fail open, exit 0, no output" \
  "$([ "$RC" = "0" ] && [ -z "$OUT" ] && echo 1 || echo 0)"

if [ "$IS_ROOT" = "0" ]; then
  H="$WORK/projH"; mkproj "$H"; arm "$H" sess-H 5
  chmod 000 "$(statefile "$H")"
  run_hook "$(stdin_json Stop sess-H "$H")"
  check "FAULT: UNREADABLE epic-state.json -> fail open, exit 0, no output" \
    "$([ "$RC" = "0" ] && [ -z "$OUT" ] && echo 1 || echo 0)"
  chmod 644 "$(statefile "$H")"
else
  echo "SKIP unreadable-state case (running as root)"
fi

run_hook "this is not json at all"
check "FAULT: malformed stdin -> fail open, exit 0, no output" \
  "$([ "$RC" = "0" ] && [ -z "$OUT" ] && echo 1 || echo 0)"

run_hook ""
check "FAULT: empty stdin -> fail open, exit 0, no output" \
  "$([ "$RC" = "0" ] && [ -z "$OUT" ] && echo 1 || echo 0)"

# absent jq: an empty PATH removes it (the hook needs no external binary to
# reach its own `command -v jq` guard).
mkdir -p "$WORK/emptybin"
stdin_json Stop sess-A "$A" >"$WORK/stdin.json"
BASH_ABS="$(command -v "$HOOK_BASH" || printf %s "$HOOK_BASH")"
OUT="$(env TMPDIR="$STORE_BASE" PATH="$WORK/emptybin" "$BASH_ABS" "$HOOK" <"$WORK/stdin.json" 2>/dev/null)"
RC=$?
check "FAULT: absent jq -> exit 0, no output" \
  "$([ "$RC" = "0" ] && [ -z "$OUT" ] && echo 1 || echo 0)"

# ---------------------------------------------------------------------------
# 10. Store faults — the two shapes that must NOT restart the counter
# ---------------------------------------------------------------------------
I="$WORK/projI"; mkproj "$I"; arm "$I" sess-I 5
run_hook "$(stdin_json Stop sess-I "$I")"           # creates the slot, count=1
slot="$(slot_for "$I" sess-I)"
check "store: this arm's slot holds count=1 after the first block" \
  "$([ -f "$slot/count" ] && [ "$(cat "$slot/count" 2>/dev/null)" = "1" ] && echo 1 || echo 0)"
rm -f "$slot/count"
run_hook "$(stdin_json Stop sess-I "$I" true)"
check "MISSING STORE during an active arm -> FAILS OPEN, exit 0, no output" \
  "$([ "$RC" = "0" ] && [ -z "$OUT" ] && echo 1 || echo 0)"
check "MISSING STORE: the counter was NOT recreated at zero" \
  "$([ ! -f "$slot/count" ] && echo 1 || echo 0)"

# whole-store sweep mid-turn: stop_hook_active proves a block already happened,
# so a vanished slot is loss, not novelty.
J="$WORK/projJ"; mkproj "$J"; arm "$J" sess-J 5
run_hook "$(stdin_json Stop sess-J "$J" true)"
check "WHOLE STORE swept + stop_hook_active=true -> FAILS OPEN (does not restart at zero)" \
  "$([ "$RC" = "0" ] && [ -z "$OUT" ] && echo 1 || echo 0)"

# failed store write, shape 1 (works as any user): the slot path is a FILE, so
# the hook's mkdir cannot create the slot.
K="$WORK/projK"; mkproj "$K"; arm "$K" sess-K 5
kslot="$(slot_for "$K" sess-K)"
mkdir -p "$HOOK_STORE"
: >"$kslot"
run_hook "$(stdin_json Stop sess-K "$K")"
check "FAILED STORE WRITE (slot path unusable) -> fail open, exit 0, no output" \
  "$([ "$RC" = "0" ] && [ -z "$OUT" ] && echo 1 || echo 0)"
rm -f "$kslot"

# failed store write, shape 2 (read-only slot dir) — meaningless as root.
if [ "$IS_ROOT" = "0" ]; then
  mkdir -p "$kslot"
  printf '0\n' >"$kslot/count"
  chmod 500 "$kslot"
  run_hook "$(stdin_json Stop sess-K "$K")"
  check "FAILED STORE WRITE (read-only slot) -> fail open, exit 0, no output" \
    "$([ "$RC" = "0" ] && [ -z "$OUT" ] && echo 1 || echo 0)"
  check "FAILED STORE WRITE: the counter was not advanced" \
    "$([ "$(cat "$kslot/count" 2>/dev/null)" = "0" ] && echo 1 || echo 0)"
  chmod 700 "$kslot"
else
  echo "SKIP read-only-slot case (running as root)"
fi

# ---------------------------------------------------------------------------
# 11. Discovery fails open on zero or multiple matches
# ---------------------------------------------------------------------------
L="$WORK/projL"; mkproj "$L"; arm "$L" sess-L 5
mkdir -p "$L/docs/superpowers/execution/epics/e2"
cp "$(statefile "$L")" "$L/docs/superpowers/execution/epics/e2/epic-state.json"
run_hook "$(stdin_json Stop sess-L "$L")"
check "DISCOVERY: two epic-state.json files -> fail open, exit 0, no output" \
  "$([ "$RC" = "0" ] && [ -z "$OUT" ] && echo 1 || echo 0)"

M="$WORK/projM"; mkdir -p "$M"; git -C "$M" init -q 2>/dev/null
run_hook "$(stdin_json Stop sess-M "$M")"
check "DISCOVERY: no epic at all -> fail open, exit 0, no output" \
  "$([ "$RC" = "0" ] && [ -z "$OUT" ] && echo 1 || echo 0)"

# ---------------------------------------------------------------------------
# 12. Enforcement (Feature B) — OFF unless configured
# ---------------------------------------------------------------------------
N="$WORK/projN"; mkproj "$N"
printf 'print("changed")\n' >>"$N/scripts/app.py"
run_hook "$(stdin_json Stop sess-N "$N")"
check "ENFORCEMENT is OFF by default: source changed, no config -> silent, exit 0" \
  "$([ "$RC" = "0" ] && [ -z "$OUT" ] && echo 1 || echo 0)"

printf '%s\n' '{"enforcement": {"pipeline_bypass": true, "triage_gate": false}}' >"$N/.claude/compound-v.json"
run_hook "$(stdin_json Stop sess-N "$N")"
check "ENFORCEMENT on + source changed + no run record -> exactly ONE JSON block" \
  "$(is_block "$OUT" && echo 1 || echo 0)"
check "the correction names the sanctioned shortcut (Pre-Evaluation fast-path)" \
  "$(printf '%s' "$OUT" | jq -r '.reason' 2>/dev/null | grep -qi 'fast-path' && echo 1 || echo 0)"
run_hook "$(stdin_json Stop sess-N "$N" true)"
check "ENFORCEMENT blocks at most once while the marker survives" \
  "$([ "$RC" = "0" ] && [ -z "$OUT" ] && echo 1 || echo 0)"

# a run record present -> no correction
O="$WORK/projO"; mkproj "$O"
printf '%s\n' '{"enforcement": {"pipeline_bypass": true, "triage_gate": false}}' >"$O/.claude/compound-v.json"
printf 'print("changed")\n' >>"$O/scripts/app.py"
mkdir -p "$O/docs/superpowers/execution/2026-07-26-run"
printf '%s\n' '{"phase":"DISPATCHED"}' >"$O/docs/superpowers/execution/2026-07-26-run/state.json"
run_hook "$(stdin_json Stop sess-O "$O")"
check "ENFORCEMENT: a run record present -> silent, exit 0" \
  "$([ "$RC" = "0" ] && [ -z "$OUT" ] && echo 1 || echo 0)"

# docs/superpowers/** alone is NOT source (arming a goal must not self-trigger)
P="$WORK/projP"; mkproj "$P"
printf '%s\n' '{"enforcement": {"pipeline_bypass": true, "triage_gate": false}}' >"$P/.claude/compound-v.json"
git -C "$P" add -A >/dev/null 2>&1
git -C "$P" -c user.email=t@t -c user.name=t commit -qm cfg >/dev/null 2>&1
arm "$P" sess-P 5   # mutates docs/superpowers/**/epic-state.json only
run_hook "$(stdin_json Stop sess-PX "$P")"   # session mismatch: goal rule inert
check "ENFORCEMENT excludes docs/superpowers/** (arming a goal is not 'source changed')" \
  "$([ "$RC" = "0" ] && [ -z "$OUT" ] && echo 1 || echo 0)"

# ---------------------------------------------------------------------------
# 13. THE TRIAGE GATE (v3.0 Feature C) — a second RULE in this script, never a
#     second registration. Two blocking `Stop` registrations have undefined
#     ordering; this file's whole shape exists to keep one response per event.
# ---------------------------------------------------------------------------

# The gate keys its marker on project+session only (no arm_id — it is not the
# goal rule), so the test computes the same key the hook does.
triage_marker() { printf '%s/triage-%s' "$HOOK_STORE" \
  "$(printf '%s|%s' "$(cd "$1" && pwd -P)" "$2" | sha256_of)"; }
triage_incomplete() { printf '%s/triage-incomplete-%s' "$HOOK_STORE" \
  "$(printf '%s|%s' "$(cd "$1" && pwd -P)" "$2" | sha256_of)"; }

# mkproj_gate <dir> — a project whose triage gate is ON and whose config is
# already COMMITTED, so the only dirty path is the one each case introduces.
mkproj_gate() {
  local d="$1"
  mkproj "$d"
  printf '%s\n' '{"enforcement": {"triage_gate": true}}' >"$d/.claude/compound-v.json"
  git -C "$d" add -A >/dev/null 2>&1
  git -C "$d" -c user.email=t@t -c user.name=t commit -qm gate >/dev/null 2>&1
}

# record <dir> <name> <session> <decision> <run_id|""> <declared...>
record() {
  local d="$1" name="$2" s="$3" dec="$4" rid="$5"; shift 5
  mkdir -p "$d/docs/superpowers/pre-eval"
  local paths; paths="$(printf '%s\n' "$@" | jq -R . | jq -s .)"
  jq -n --arg s "$s" --arg dec "$dec" --arg rid "$rid" --argjson p "$paths" \
     '{pre_eval_id: "2026-09-01T120000Z-t-a1", status: "PRE_EVAL_DONE",
       session_id: $s, decision: $dec, declared_paths: $p}
      + (if $rid == "" then {} else {run_id: $rid} end)' \
     >"$d/docs/superpowers/pre-eval/${name}.json"
}

# --- OFF by default: a false positive here bricks a stranger's session -------
R="$WORK/projR"; mkproj "$R"
printf 'print("changed")\n' >>"$R/scripts/app.py"
run_hook "$(stdin_json Stop sess-R "$R")"
check "TRIAGE GATE is OFF by default: changes, no config -> silent, exit 0" \
  "$([ "$RC" = "0" ] && [ -z "$OUT" ] && echo 1 || echo 0)"
# 3.2.0 flipped the default. An ABSENT `triage_gate` now means ON — but only
# once a `.claude/compound-v.json` exists at all, which is what keeps a project
# that never ran /v:init untouched (asserted immediately above).
printf '%s\n' '{"enforcement": {"pipeline_bypass": false}}' >"$R/.claude/compound-v.json"
run_hook "$(stdin_json Stop sess-R "$R")"
check "TRIAGE GATE is ON when the config exists and omits triage_gate (3.2.0)" \
  "$([ "$RC" = "0" ] && [ -n "$OUT" ] \
     && printf '%s' "$OUT" | jq -r '.reason' 2>/dev/null | grep -q 'no triage record' \
     && echo 1 || echo 0)"
check "TRIAGE GATE: the marker IS written when it fires" \
  "$([ -e "$(triage_marker "$R" sess-R)" ] && echo 1 || echo 0)"

# The opt-out, which is the whole reason flipping the default is reversible.
RO="$WORK/projRO"; mkproj "$RO"
printf '%s\n' '{"enforcement": {"triage_gate": false}}' >"$RO/.claude/compound-v.json"
printf 'print("changed")\n' >>"$RO/scripts/app.py"
run_hook "$(stdin_json Stop sess-RO "$RO")"
check "TRIAGE GATE: an explicit false opts out" \
  "$([ "$RC" = "0" ] && [ -z "$OUT" ] && echo 1 || echo 0)"
check "TRIAGE GATE: an explicit false writes nothing to the store" \
  "$([ ! -e "$(triage_marker "$RO" sess-RO)" ] && echo 1 || echo 0)"

# --- armed: blocks ONCE, and only once --------------------------------------
S="$WORK/projS"; mkproj_gate "$S"
printf 'print("changed")\n' >>"$S/scripts/app.py"
run_hook "$(stdin_json Stop sess-S "$S")"
check "TRIAGE GATE armed + an uncovered change -> exactly ONE JSON block" \
  "$(is_block "$OUT" && echo 1 || echo 0)"
check "TRIAGE GATE: the block names the uncovered path and /v:triage" \
  "$(printf '%s' "$OUT" | jq -r '.reason' 2>/dev/null \
     | grep -q 'scripts/app.py' && printf '%s' "$OUT" | jq -r '.reason' | grep -q '/v:triage' && echo 1 || echo 0)"
check "TRIAGE GATE: it set its OWN marker" \
  "$([ -e "$(triage_marker "$S" sess-S)" ] && echo 1 || echo 0)"

# stop_hook_active is a CONSECUTIVE-BLOCK COUNTER the harness may reset, and
# CLAUDE_CODE_STOP_HOOK_BLOCK_CAP lets it override us outright — so the bound has
# to be our own marker. Both values of the flag must yield silence here.
run_hook "$(stdin_json Stop sess-S "$S" true)"
check "TRIAGE GATE does NOT block twice (marker, not the harness counter)" \
  "$([ "$RC" = "0" ] && [ -z "$OUT" ] && echo 1 || echo 0)"
run_hook "$(stdin_json Stop sess-S "$S" false)"
check "TRIAGE GATE stays silent with stop_hook_active=false as well" \
  "$([ "$RC" = "0" ] && [ -z "$OUT" ] && echo 1 || echo 0)"

# --- a record that COVERS the diff exempts it -------------------------------
T="$WORK/projT"; mkproj_gate "$T"
printf 'print("changed")\n' >>"$T/scripts/app.py"
record "$T" r1 sess-T FASTPATH_ELIGIBLE "" "scripts/app.py"
run_hook "$(stdin_json Stop sess-T "$T")"
check "TRIAGE GATE: a DIRECT record covering the diff -> silent, exit 0" \
  "$([ "$RC" = "0" ] && [ -z "$OUT" ] && echo 1 || echo 0)"

# A directory-suffixed declaration covers what is under it.
T2="$WORK/projT2"; mkproj_gate "$T2"
printf 'print("changed")\n' >>"$T2/scripts/app.py"
record "$T2" r1 sess-T2 FASTPATH_ELIGIBLE "" "scripts/"
run_hook "$(stdin_json Stop sess-T2 "$T2")"
check "TRIAGE GATE: a 'scripts/' declaration covers scripts/app.py" \
  "$([ "$RC" = "0" ] && [ -z "$OUT" ] && echo 1 || echo 0)"

# --- a record that exists but does NOT declare the changed path -------------
# THE HEADLINE CASE. Existence is not coverage: one triage of "change the
# README" must not license a later edit to this very hook in the same session.
U="$WORK/projU"; mkproj_gate "$U"
printf 'print("changed")\n' >>"$U/scripts/app.py"
record "$U" r1 sess-U FASTPATH_ELIGIBLE "" "README.md"
run_hook "$(stdin_json Stop sess-U "$U")"
check "TRIAGE GATE: a record whose declared_paths EXCLUDE the diff does NOT exempt it" \
  "$(is_block "$OUT" && echo 1 || echo 0)"

# A bare directory name is not a prefix declaration — widening a declared set by
# accident is the one direction this must never fail in.
U2="$WORK/projU2"; mkproj_gate "$U2"
printf 'print("changed")\n' >>"$U2/scripts/app.py"
record "$U2" r1 sess-U2 FASTPATH_ELIGIBLE "" "scripts"
run_hook "$(stdin_json Stop sess-U2 "$U2")"
check "TRIAGE GATE: a bare 'scripts' does NOT silently cover scripts/app.py" \
  "$(is_block "$OUT" && echo 1 || echo 0)"

# --- session isolation: another session's record is not this session's cover -
V="$WORK/projV"; mkproj_gate "$V"
printf 'print("changed")\n' >>"$V/scripts/app.py"
record "$V" r1 sess-OTHER FASTPATH_ELIGIBLE "" "scripts/app.py"
run_hook "$(stdin_json Stop sess-V "$V")"
check "TRIAGE GATE: a covering record from ANOTHER session does not exempt" \
  "$(is_block "$OUT" && echo 1 || echo 0)"

# --- SCOPED / FULL need a run directory, not just a record ------------------
W="$WORK/projW"; mkproj_gate "$W"
printf 'print("changed")\n' >>"$W/scripts/app.py"
record "$W" r1 sess-W SCOPED_PIPELINE 2026-09-01-run "scripts/app.py"
run_hook "$(stdin_json Stop sess-W "$W")"
check "TRIAGE GATE: a SCOPED record with NO run directory is an intention, not a cover" \
  "$(is_block "$OUT" && echo 1 || echo 0)"
rm -f "$(triage_marker "$W" sess-W)"
mkdir -p "$W/docs/superpowers/execution/2026-09-01-run"
printf '%s\n' '{"phase":"DISPATCHED"}' >"$W/docs/superpowers/execution/2026-09-01-run/state.json"
run_hook "$(stdin_json Stop sess-W "$W")"
check "TRIAGE GATE: the same SCOPED record WITH its run directory does exempt" \
  "$([ "$RC" = "0" ] && [ -z "$OUT" ] && echo 1 || echo 0)"

# --- the pipeline's own paper trail is never 'changed source' ---------------
X="$WORK/projX"; mkproj_gate "$X"
mkdir -p "$X/docs/superpowers/pre-eval"
printf '%s\n' '{}' >"$X/docs/superpowers/pre-eval/scratch.json"
run_hook "$(stdin_json Stop sess-X "$X")"
check "TRIAGE GATE: a change confined to docs/superpowers/** is not 'changed'" \
  "$([ "$RC" = "0" ] && [ -z "$OUT" ] && echo 1 || echo 0)"

# --- a malformed record is not an exemption ---------------------------------
Y="$WORK/projY"; mkproj_gate "$Y"
printf 'print("changed")\n' >>"$Y/scripts/app.py"
mkdir -p "$Y/docs/superpowers/pre-eval"
printf 'NOT JSON {{{\n' >"$Y/docs/superpowers/pre-eval/broken.json"
run_hook "$(stdin_json Stop sess-Y "$Y")"
check "TRIAGE GATE: an unreadable record set -> fail OPEN, exit 0, no block" \
  "$([ "$RC" = "0" ] && [ -z "$OUT" ] && echo 1 || echo 0)"
check "TRIAGE GATE: ...and it was RECORDED, not passed silently" \
  "$([ -s "$(triage_incomplete "$Y" sess-Y)" ] && echo 1 || echo 0)"
check "TRIAGE GATE: an incomplete check does NOT burn the once-per-session marker" \
  "$([ ! -e "$(triage_marker "$Y" sess-Y)" ] && echo 1 || echo 0)"

# --- THE BOUNDED CHECK -------------------------------------------------------
# All `Stop` hooks share a 1.5s budget, and a `git` that overruns it is a SILENT
# no-op — the dead-guard shape this project has already shipped once. A real slow
# `git` on PATH proves the bound exists, that the hook returns promptly, and that
# the overrun is written down rather than looking like a clean pass.
Z="$WORK/projZ"; mkproj_gate "$Z"
printf 'print("changed")\n' >>"$Z/scripts/app.py"
SLOWBIN="$WORK/slowbin"; mkdir -p "$SLOWBIN"
REAL_GIT="$(command -v git)"
{ printf '#!/bin/sh\n'; printf 'sleep 5\n'; printf 'exec %s "$@"\n' "$REAL_GIT"; } >"$SLOWBIN/git"
chmod +x "$SLOWBIN/git"
t0="$(date +%s)"
run_hook "$(stdin_json Stop sess-Z "$Z")" \
  "PATH=$SLOWBIN:$PATH" "COMPOUND_V_TRIAGE_GATE_BUDGET_MS=200"
t1="$(date +%s)"
check "BOUNDED CHECK: a slow git -> exit 0 and NO block" \
  "$([ "$RC" = "0" ] && [ -z "$OUT" ] && echo 1 || echo 0)"
check "BOUNDED CHECK: the hook returned well inside the shared 1.5s budget ($((t1 - t0))s, not 5s)" \
  "$([ "$((t1 - t0))" -le 2 ] && echo 1 || echo 0)"
check "BOUNDED CHECK: the overrun was RECORDED, not passed silently" \
  "$(grep -q 'triage-gate-incomplete' "$(triage_incomplete "$Z" sess-Z)" 2>/dev/null && echo 1 || echo 0)"
check "BOUNDED CHECK: the recorded line names the budget it could not meet" \
  "$(grep -q '100ms' "$(triage_incomplete "$Z" sess-Z)" 2>/dev/null && echo 1 || echo 0)"
check "BOUNDED CHECK: an unfinished check does NOT set the once-per-session marker" \
  "$([ ! -e "$(triage_marker "$Z" sess-Z)" ] && echo 1 || echo 0)"
# ...and the very next Stop, with a healthy git, still gets its one block.
run_hook "$(stdin_json Stop sess-Z "$Z")"
check "BOUNDED CHECK: the next turn retries and blocks (the gate was not consumed)" \
  "$(is_block "$OUT" && echo 1 || echo 0)"

# --- PRECEDENCE -------------------------------------------------------------
# One event, one response. The goal rule outranks both corrections; between the
# two corrections the triage gate goes first, because `/v:triage` is the first
# step of the correction the bypass rule asks for.
AA="$WORK/projAA"; mkproj_gate "$AA"
printf '%s\n' '{"enforcement": {"triage_gate": true, "pipeline_bypass": true}}' \
  >"$AA/.claude/compound-v.json"
printf 'print("changed")\n' >>"$AA/scripts/app.py"
run_hook "$(stdin_json Stop sess-AA "$AA")"
check "PRECEDENCE: triage gate + bypass rule both eligible -> exactly ONE response" \
  "$([ "$(json_docs "$OUT")" = "1" ] && echo 1 || echo 0)"
check "PRECEDENCE: the TRIAGE GATE wins over the bypass rule" \
  "$(printf '%s' "$OUT" | jq -r '.reason' 2>/dev/null | grep -q 'no triage record covers' && echo 1 || echo 0)"
check "PRECEDENCE: the bypass rule's marker was NOT set (one state update)" \
  "$([ ! -e "$HOOK_STORE/enforce-$(printf '%s|%s' "$(cd "$AA" && pwd -P)" sess-AA | sha256_of)" ] && echo 1 || echo 0)"

AB="$WORK/projAB"; mkproj_gate "$AB"
printf 'print("changed")\n' >>"$AB/scripts/app.py"
arm "$AB" sess-AB 5
run_hook "$(stdin_json Stop sess-AB "$AB")"
check "PRECEDENCE: the GOAL rule still outranks the triage gate" \
  "$(printf '%s' "$OUT" | jq -r '.reason' 2>/dev/null | grep -q 'epic goal is armed' && echo 1 || echo 0)"
check "PRECEDENCE: the goal rule blocking left the triage marker unset" \
  "$([ ! -e "$(triage_marker "$AB" sess-AB)" ] && echo 1 || echo 0)"

# --- 3.2.0: the triage gate SHADOWS the bypass rule, deliberately -----------
# Both rules say "you changed code without X" and only one response per event is
# permitted, so the more specific diagnosis goes first: /v:triage is the first
# step of the correction the bypass rule asks for. Flipping the triage default to
# ON therefore CHANGES which message a project with `pipeline_bypass: true` and no
# `triage_gate` key sees — from the bypass wording to the triage wording. That is
# by design, and it is pinned here so it can never become an accident.
SH="$WORK/projSH"; mkproj "$SH"
printf '%s\n' '{"enforcement": {"pipeline_bypass": true}}' >"$SH/.claude/compound-v.json"
printf 'print("changed")\n' >>"$SH/scripts/app.py"
run_hook "$(stdin_json Stop sess-SH "$SH")"
check "SHADOW: with both eligible, the TRIAGE diagnosis wins" \
  "$(printf '%s' "$OUT" | jq -r '.reason' 2>/dev/null | grep -q 'no triage record' \
     && echo 1 || echo 0)"
check "SHADOW: still exactly ONE JSON response" \
  "$([ "$(json_docs "$OUT")" = "1" ] && echo 1 || echo 0)"
SH2="$WORK/projSH2"; mkproj "$SH2"
printf '%s\n' '{"enforcement": {"pipeline_bypass": true, "triage_gate": false}}' \
  >"$SH2/.claude/compound-v.json"
printf 'print("changed")\n' >>"$SH2/scripts/app.py"
run_hook "$(stdin_json Stop sess-SH2 "$SH2")"
check "SHADOW: opting the triage gate out restores the bypass diagnosis" \
  "$(printf '%s' "$OUT" | jq -r '.reason' 2>/dev/null | grep -qv 'no triage record' \
     && [ -n "$OUT" ] && echo 1 || echo 0)"

# ---------------------------------------------------------------------------
# 14. PRECEDENCE — the goal rule and the bypass rule on one Stop
# ---------------------------------------------------------------------------
Q="$WORK/projQ"; mkproj "$Q"
printf '%s\n' '{"enforcement": {"pipeline_bypass": true, "triage_gate": false}}' >"$Q/.claude/compound-v.json"
printf 'print("changed")\n' >>"$Q/scripts/app.py"
arm "$Q" sess-Q 5
before_markers="$(find "$HOOK_STORE" -maxdepth 1 -name 'enforce-*' 2>/dev/null | wc -l | tr -d ' ')"
run_hook "$(stdin_json Stop sess-Q "$Q")"
after_markers="$(find "$HOOK_STORE" -maxdepth 1 -name 'enforce-*' 2>/dev/null | wc -l | tr -d ' ')"
check "PRECEDENCE: exactly ONE JSON response when both rules are eligible" \
  "$([ "$(json_docs "$OUT")" = "1" ] && echo 1 || echo 0)"
check "PRECEDENCE: the GOAL rule wins (the response is the continuation, not the correction)" \
  "$(printf '%s' "$OUT" | jq -r '.reason' 2>/dev/null | grep -q 'epic goal is armed' && echo 1 || echo 0)"
check "PRECEDENCE: exactly ONE state update — the enforcement marker was NOT set" \
  "$([ "$before_markers" = "$after_markers" ] && echo 1 || echo 0)"

# ---------------------------------------------------------------------------
# 15. Fail-open is MECHANICAL — both independent mechanisms
# ---------------------------------------------------------------------------
# (a) the registration in hooks.json carries `|| true`
reg="$(jq -r '.hooks.Stop[]?.hooks[]?.command // empty' "$REPO/hooks/hooks.json" 2>/dev/null \
       | grep 'epic-goal-stop' || true)"
check "REGISTRATION: hooks.json registers the Stop hook" "$([ -n "$reg" ] && echo 1 || echo 0)"
check "REGISTRATION: it is suffixed with '|| true'" \
  "$(printf '%s' "$reg" | grep -q '|| true' && echo 1 || echo 0)"
check "REGISTRATION: Stop carries NO matcher (it is not a tool event)" \
  "$(jq -e '[.hooks.Stop[]? | has("matcher")] | any | not' "$REPO/hooks/hooks.json" >/dev/null 2>&1 && echo 1 || echo 0)"

# (a) proven: a DELIBERATELY BROKEN script still yields 0 through that
#     registration. A script whose FIRST command will not parse never reaches its
#     own `trap` line, so mechanism (b) is not installed yet — which is exactly
#     why mechanism (a) has to exist independently of it.
broken="$WORK/broken.sh"
printf '#!/usr/bin/env bash\nthis is ( not valid bash\n' >"$broken"
chmod +x "$broken"
sh -c "'$broken'" </dev/null >/dev/null 2>&1
raw_rc=$?
sh -c "'$broken' || true" </dev/null >/dev/null 2>&1
wrapped_rc=$?
check "MECHANISM (a): a syntactically broken hook DOES exit non-zero on its own (the hazard is real)" \
  "$([ "$raw_rc" != "0" ] && echo 1 || echo 0)"
check "MECHANISM (a): the '|| true' registration turns that into exit 0" \
  "$([ "$wrapped_rc" = "0" ] && echo 1 || echo 0)"

# EXIT 2 IS THE BLOCKING CODE, and bash uses it for a PARSE ERROR. That is the
# whole reason mechanism (a) has to exist independently of mechanism (b): a
# script that fails to parse never runs a line of itself, so its own EXIT trap
# is not registered and cannot save it. Three shapes, all of them ordinary
# editing accidents, are probed here rather than asserted.
i=0
for shape in 'if true; then\n  echo hi\nfi\nfi\n' \
             'echo "unterminated\n' \
             'f() {\n  echo hi\n'; do
  i=$((i + 1))
  pe="$WORK/parse-error-$i.sh"
  { printf '#!/usr/bin/env bash\n'; printf "$shape"; } >"$pe"
  chmod +x "$pe"
  "$HOOK_BASH" "$pe" </dev/null >/dev/null 2>&1
  pe_raw=$?
  sh -c "'$HOOK_BASH' '$pe' || true" </dev/null >/dev/null 2>&1
  pe_wrapped=$?
  check "PARSE ERROR shape $i: the raw script exits EXACTLY 2 — the blocking code (got $pe_raw)" \
    "$([ "$pe_raw" = "2" ] && echo 1 || echo 0)"
  check "PARSE ERROR shape $i: the '|| true' registration still fails open (exit 0)" \
    "$([ "$pe_wrapped" = "0" ] && echo 1 || echo 0)"
done

# WHERE the parse error sits decides which mechanism saves the session, and that
# is sharper than "a syntax error is fatal before any trap can run". Probed, not
# assumed: bash parses a script INCREMENTALLY, one complete command at a time, so
# a malformed command is only reached when execution gets to it.
#
#   * error ABOVE `trap 'exit 0' EXIT` -> the trap was never registered -> exit 2,
#     and ONLY the `|| true` registration stands between that and a wedged turn.
#   * error BELOW it -> the trap is already installed and forces 0.
#
# Both are asserted, because the second is the one that would quietly rot: if a
# future edit ever moves that trap down the file, mechanism (b)'s reach shrinks
# and this test is what says so.
break_hook_at() { # <dst> <'above'|'below'>
  python3 - "$HOOK" "$1" "$2" <<'INNERPY'
import sys
src, dst, where = sys.argv[1], sys.argv[2], sys.argv[3]
text = open(src).read()
anchor = "trap 'exit 0' EXIT\n"
assert text.count(anchor) == 1, "trap anchor not found exactly once in the hook"
text = text.replace(anchor, "fi\n" + anchor if where == "above" else anchor + "fi\n", 1)
open(dst, "w").write(text)
INNERPY
  chmod +x "$1"
}

stdin_json Stop sess-A "$A" >"$WORK/stdin.json"

hook_above="$PLUGIN/hooks/broken-above.sh"
break_hook_at "$hook_above" above
ba_out="$(env TMPDIR="$STORE_BASE" "$HOOK_BASH" "$hook_above" <"$WORK/stdin.json" 2>/dev/null)"
ba_raw=$?
env TMPDIR="$STORE_BASE" sh -c "'$HOOK_BASH' '$hook_above' || true" <"$WORK/stdin.json" >/dev/null 2>&1
ba_wrapped=$?
check "PARSE ERROR in THIS hook, ABOVE the trap: exits EXACTLY 2 - the blocking code (got $ba_raw)" \
  "$([ "$ba_raw" = "2" ] && echo 1 || echo 0)"
check "PARSE ERROR in THIS hook, ABOVE the trap: emits nothing on stdout" \
  "$([ -z "$ba_out" ] && echo 1 || echo 0)"
check "PARSE ERROR in THIS hook, ABOVE the trap: ONLY the '|| true' registration saves it" \
  "$([ "$ba_wrapped" = "0" ] && echo 1 || echo 0)"

hook_below="$PLUGIN/hooks/broken-below.sh"
break_hook_at "$hook_below" below
bb_out="$(env TMPDIR="$STORE_BASE" "$HOOK_BASH" "$hook_below" <"$WORK/stdin.json" 2>/dev/null)"
bb_raw=$?
check "PARSE ERROR in THIS hook, BELOW the trap: the already-installed trap forces 0 (got $bb_raw)" \
  "$([ "$bb_raw" = "0" ] && echo 1 || echo 0)"
check "PARSE ERROR in THIS hook, BELOW the trap: still emits nothing on stdout" \
  "$([ -z "$bb_out" ] && echo 1 || echo 0)"

# (b) proven: a runtime abort INSIDE hook_main emits nothing and exits 0
injected="$PLUGIN/hooks/injected.sh"
python3 - "$HOOK" "$injected" <<'PY'
import sys
src, dst = sys.argv[1], sys.argv[2]
text = open(src).read()
anchor = "  trap - EXIT\n"
assert anchor in text, "anchor for fault injection not found in the hook"
text = text.replace(
    anchor,
    anchor + '  echo "PARTIAL GARBAGE ON STDOUT"\n  exit 3\n', 1)
open(dst, "w").write(text)
PY
chmod +x "$injected"
stdin_json Stop sess-A "$A" >"$WORK/stdin.json"
OUT="$(env TMPDIR="$STORE_BASE" "$HOOK_BASH" "$injected" <"$WORK/stdin.json" 2>/dev/null)"
RC=$?
check "MECHANISM (b): a mid-run abort inside hook_main -> exit 0 and NO partial output" \
  "$([ "$RC" = "0" ] && [ -z "$OUT" ] && echo 1 || echo 0)"

# (b) also covers an abort in the OUTER wrapper, where the EXIT trap is the
# only thing standing between a bug and a wedged session.
injected2="$PLUGIN/hooks/injected2.sh"
{ cat "$HOOK"; printf '\nfalse\nexit 7\n'; } >"$injected2"
chmod +x "$injected2"
stdin_json Stop sess-M "$M" >"$WORK/stdin.json"
env TMPDIR="$STORE_BASE" "$HOOK_BASH" "$injected2" <"$WORK/stdin.json" >/dev/null 2>&1
trap_rc=$?
check "MECHANISM (b): the EXIT trap forces status 0 even on a trailing 'exit 7'" \
  "$([ "$trap_rc" = "0" ] && echo 1 || echo 0)"

# ---------------------------------------------------------------------------
echo "-------------------------------------------"
printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" = "0" ] || exit 1
echo "✅ epic-goal-stop.sh decision table green"
