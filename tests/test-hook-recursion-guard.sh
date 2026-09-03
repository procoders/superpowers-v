#!/bin/bash
# tests/test-hook-recursion-guard.sh — finding 131: the headless T3 classifier's nested
# `claude -p` loads the same project hooks; with CV_HEADLESS_CLASSIFY=1 in its
# environment every hook must exit 0 immediately, print nothing, and write nothing.
# Run explicitly under /bin/bash (bash 3.2 on macOS).
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
pass=0; fail=0
ok()  { pass=$((pass + 1)); printf 'PASS %s\n' "$1"; }
bad() { fail=$((fail + 1)); printf 'FAIL %s\n' "$1"; }
before=$(find "$REPO/docs/superpowers/pre-eval" -type f 2>/dev/null | wc -l | tr -d ' ')
for h in triage-prompt-nudge session-banner epic-goal-stop memory-refresh lane-guard plan-saved-nudge brainstorm-trigger0-nudge precompact-snapshot postcompact-resume; do
  payload=$(printf '{"hook_event_name":"UserPromptSubmit","session_id":"s-guard","cwd":"%s","prompt":"Add a --version flag to scripts/compound-v-liveness.py","tool_name":"Write","tool_input":{"file_path":"%s/README.md"}}' "$REPO" "$REPO")
  out=$(printf '%s' "$payload" | CV_HEADLESS_CLASSIFY=1 bash "$REPO/hooks/$h.sh" 2>/dev/null); rc=$?
  if [ "$rc" = "0" ] && [ -z "$out" ]; then ok "$h: silent exit 0 under CV_HEADLESS_CLASSIFY=1"; else bad "$h: rc=$rc out=${out:0:80}"; fi
done
after=$(find "$REPO/docs/superpowers/pre-eval" -type f 2>/dev/null | wc -l | tr -d ' ')
if [ "$before" = "$after" ]; then ok "no pre-eval record was written by any guarded hook"; else bad "pre-eval records changed: $before -> $after"; fi
# the guard must be the FIRST thing after set: a hook that does work before it is not guarded
for h in triage-prompt-nudge session-banner epic-goal-stop memory-refresh lane-guard plan-saved-nudge brainstorm-trigger0-nudge precompact-snapshot postcompact-resume; do
  if awk '/^set -/{s=1; next} s==1 && /CV_HEADLESS_CLASSIFY/{found=1; exit} s==1 && !/^[[:space:]]*(#|$)/{exit} END{exit !found}' "$REPO/hooks/$h.sh"; then ok "$h: the guard is the first statement after set"; else bad "$h: guard not first after set"; fi
done
# the classifier marks its child's environment
if grep -q 'env=_headless_env()' "$REPO/scripts/compound-v-classify-request.py" && grep -q 'HEADLESS_ENV_MARKER = "CV_HEADLESS_CLASSIFY"' "$REPO/scripts/compound-v-classify-request.py"; then ok "classify-request marks the nested claude/codex environment"; else bad "classify-request does not mark the environment"; fi
printf 'tests/test-hook-recursion-guard.sh: %d passed, %d failed\n' "$pass" "$fail"
[ "$fail" = "0" ] || exit 1
