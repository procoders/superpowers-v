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

printf '%s\n' '{"enforcement": {"pipeline_bypass": true}}' >"$N/.claude/compound-v.json"
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
printf '%s\n' '{"enforcement": {"pipeline_bypass": true}}' >"$O/.claude/compound-v.json"
printf 'print("changed")\n' >>"$O/scripts/app.py"
mkdir -p "$O/docs/superpowers/execution/2026-07-26-run"
printf '%s\n' '{"phase":"DISPATCHED"}' >"$O/docs/superpowers/execution/2026-07-26-run/state.json"
run_hook "$(stdin_json Stop sess-O "$O")"
check "ENFORCEMENT: a run record present -> silent, exit 0" \
  "$([ "$RC" = "0" ] && [ -z "$OUT" ] && echo 1 || echo 0)"

# docs/superpowers/** alone is NOT source (arming a goal must not self-trigger)
P="$WORK/projP"; mkproj "$P"
printf '%s\n' '{"enforcement": {"pipeline_bypass": true}}' >"$P/.claude/compound-v.json"
git -C "$P" add -A >/dev/null 2>&1
git -C "$P" -c user.email=t@t -c user.name=t commit -qm cfg >/dev/null 2>&1
arm "$P" sess-P 5   # mutates docs/superpowers/**/epic-state.json only
run_hook "$(stdin_json Stop sess-PX "$P")"   # session mismatch: goal rule inert
check "ENFORCEMENT excludes docs/superpowers/** (arming a goal is not 'source changed')" \
  "$([ "$RC" = "0" ] && [ -z "$OUT" ] && echo 1 || echo 0)"

# ---------------------------------------------------------------------------
# 13. PRECEDENCE — both rules eligible on one Stop
# ---------------------------------------------------------------------------
Q="$WORK/projQ"; mkproj "$Q"
printf '%s\n' '{"enforcement": {"pipeline_bypass": true}}' >"$Q/.claude/compound-v.json"
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
# 14. Fail-open is MECHANICAL — both independent mechanisms
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
#     registration. A syntax error is fatal BEFORE any trap can run — which is
#     exactly why mechanism (a) has to exist independently of mechanism (b).
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
