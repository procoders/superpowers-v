#!/usr/bin/env bash
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
export HOME="$T/home" CV_STATE_DIR="$T/state" CLAUDE_PLUGIN_ROOT="$ROOT" PYTHONDONTWRITEBYTECODE=1
mkdir -p "$HOME"
fails=0
check() { if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "FAIL $1: expected [$3] got [$2]"; fails=$((fails + 1)); fi; }
payload() { printf '{"hook_event_name":"%s","session_id":"s1","cwd":"%s","prompt":"add a login page","tool_name":"Write","tool_input":{"file_path":"a.txt"}}' "$1" "$2"; }

newrepo() {
  mkdir -p "$1" && git -C "$1" init -q && git -C "$1" config user.email t@example.invalid \
    && git -C "$1" config user.name T && git -C "$1" config commit.gpgsign false \
    && echo a >"$1/a.txt" && git -C "$1" add -A && git -C "$1" commit -q -m init
}

test_hooks_silent_outside_git() {
  local d="$T/plain" out rc
  mkdir -p "$d"
  for pair in stop:Stop prompt:UserPromptSubmit session:SessionStart guard:PreToolUse subagent:SubagentStop; do
    out="$(cd "$d" && payload "${pair#*:}" "$d" | "$ROOT/hooks/${pair%%:*}.sh")"; rc=$?
    check "silent outside git: ${pair%%:*}" "$rc:$out" "0:"
  done
  mkdir -p "$T/nocommit" && git -C "$T/nocommit" init -q
  out="$(payload UserPromptSubmit "$T/nocommit" | "$ROOT/hooks/prompt.sh")"; rc=$?
  check "silent without a first commit" "$rc:$out" "0:"
}

test_broken_python_fails_open() {
  local fake="$T/fakebin" out rc
  mkdir -p "$fake"
  printf '#!/bin/sh\nexit 1\n' >"$fake/python3" && chmod +x "$fake/python3"
  newrepo "$T/broken"
  out="$(payload Stop "$T/broken" | PATH="$fake:/usr/bin:/bin" "$ROOT/hooks/stop.sh")"; rc=$?
  check "broken python fails open" "$rc:$out" "0:"
}

test_not_set_up_notice_once() {
  local r="$T/notsetup" first second
  newrepo "$r"
  first="$(payload UserPromptSubmit "$r" | "$ROOT/hooks/prompt.sh")"
  second="$(payload UserPromptSubmit "$r" | "$ROOT/hooks/prompt.sh")"
  case "$first" in *"not set up here"*) check "not-set-up notice shown" ok ok ;;
    *) check "not-set-up notice shown" "$first" "notice" ;; esac
  check "not-set-up notice only once" "$second" ""
}

test_stop_wrapper_blocks_open_run() {
  local r="$T/setup" out
  newrepo "$r"
  mkdir -p "$r/.claude" && echo '{"test_cmd": "true"}' >"$r/.claude/compound-v.json"
  echo "fix typo" >"$T/req.txt"
  (cd "$r" && python3 "$ROOT/scripts/compound-v.py" run start --tier light \
    --request-file "$T/req.txt" >/dev/null)
  out="$(payload Stop "$r" | "$ROOT/hooks/stop.sh")"
  case "$out" in *'"decision": "block"'*) check "stop wrapper blocks an open run" ok ok ;;
    *) check "stop wrapper blocks an open run" "$out" "block" ;; esac
  out="$(payload Stop "$r" | "$ROOT/hooks/stop.sh")"
  check "second stop allowed" "$out" ""
}

test_hooks_silent_outside_git
test_broken_python_fails_open
test_not_set_up_notice_once
test_stop_wrapper_blocks_open_run
[ "$fails" -eq 0 ] || { echo "$fails failure(s)"; exit 1; }
echo "all hook wrapper tests passed"
