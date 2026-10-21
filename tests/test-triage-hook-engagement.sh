#!/usr/bin/env bash
# tests/test-triage-hook-engagement.sh — why hooks/triage-prompt-nudge.sh stayed
# silent on a fresh project (3.9.0), one section per cause:
#   A. a failed scoring, or a first prompt like "Read prd.md", spent the session
#   B. a project with no Compound V surface got no word at all
#   C. a missing jq disabled the hook without a word
#   D. a FULL tier only asked Claude to "offer" the pipeline
# No case spends a real model call: both classify routes are disabled or faked.
# bash 3.2 compatible. Run: bash tests/test-triage-hook-engagement.sh
set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd -P)"
NUDGE="${TRIAGE_NUDGE_SRC:-$REPO/hooks/triage-prompt-nudge.sh}"

pass=0
fail=0
ok()  { pass=$((pass + 1)); printf 'PASS %s\n' "$1"; }
bad() { fail=$((fail + 1)); printf 'FAIL %s\n' "$1"; }
check() { if [ "$2" = "1" ]; then ok "$1"; else bad "$1"; fi; }

command -v jq >/dev/null 2>&1 || { echo "FATAL: jq required"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "FATAL: python3 required"; exit 1; }
command -v git >/dev/null 2>&1 || { echo "FATAL: git required"; exit 1; }

WORK="$(mktemp -d)"
WORK="$(cd "$WORK" && pwd -P)"
trap 'rm -rf "$WORK"' EXIT
export TMPDIR="$WORK/tmp"
mkdir -p "$TMPDIR"
export PYTHONDONTWRITEBYTECODE=1
export CLAUDE_PLUGIN_ROOT="$REPO"
export CV_CLASSIFY_CLAUDE_BIN=""
export CV_CLASSIFY_CODEX_BIN=""
unset CURSOR_PLUGIN_ROOT COPILOT_CLI CV_DISABLED_HOOKS CV_HEADLESS_CLASSIFY 2>/dev/null || true
STORE="$TMPDIR/compound-v-triage-nudge"

mkrepo() { mkdir -p "$1" && git -C "$1" init -q; }

payload() { # session prompt cwd
  jq -n --arg s "$1" --arg p "$2" --arg c "$3" \
    '{hook_event_name:"UserPromptSubmit", session_id:$s, cwd:$c, prompt:$p}'
}
RC=0
run() { # session prompt cwd [env...]
  local s="$1" p="$2" c="$3"
  shift 3
  OUT="$(payload "$s" "$p" "$c" | env "$@" bash "$NUDGE" 2>/dev/null)"
  RC=$?
}
ctx() { printf '%s' "$OUT" | jq -r '.hookSpecificOutput.additionalContext // ""' 2>/dev/null; }
sysmsg() { printf '%s' "$OUT" | jq -r '.systemMessage // ""' 2>/dev/null; }
has() { case "$1" in *"$2"*) return 0 ;; *) return 1 ;; esac; }
records_for() { # dir session
  find "$1/docs/superpowers/pre-eval" -maxdepth 1 -type f -name '*.json' 2>/dev/null \
    | while IFS= read -r f; do
        jq -e --arg s "$2" '(type == "object") and (.session_id == $s)' "$f" \
          >/dev/null 2>&1 && printf '%s\n' "$f"
      done
}
markers() { find "$STORE" -name "$1" 2>/dev/null | wc -l | tr -d ' '; }

# A configured project with no taxonomy: the engine scores every request FULL.
PROJ="$WORK/proj"
mkrepo "$PROJ"
mkdir -p "$PROJ/.claude"
printf '{"stance": "cost-aware"}\n' >"$PROJ/.claude/compound-v.json"
printf '# prd\n' >"$PROJ/prd.md"

# The whole scripts/ tree with only the engine replaced by one that fails.
BROKEN="$WORK/brokenplugin"
mkdir -p "$BROKEN"
cp -R "$REPO/scripts" "$BROKEN/scripts"
printf '#!/usr/bin/env python3\nimport sys\nsys.exit(3)\n' >"$BROKEN/scripts/compound-v-preeval.py"

# --------------------------------------------------------------------------- #
echo "=== A. the session is spent only by a decision ==="
run sA1 'add a retry to the uploader' "$PROJ" CLAUDE_PLUGIN_ROOT="$BROKEN"
check "A: a failed scoring exits 0 with the reminder" \
  "$([ "$RC" = 0 ] && has "$(ctx)" 'could not size this prompt' && echo 1 || echo 0)"
check "A: a failed scoring leaves NO spent-marker" "$([ "$(markers 'nudged-*')" = 0 ] && echo 1 || echo 0)"
run sA1 'add a retry to the uploader, with backoff' "$PROJ"
check "A: the next prompt in that session is scored (the session stayed armed)" \
  "$([ "$RC" = 0 ] && has "$(ctx)" 'TIER: FULL' && echo 1 || echo 0)"
check "A: ...and wrote a record bound to that session" \
  "$([ -n "$(records_for "$PROJ" sA1)" ] && echo 1 || echo 0)"
check "A: ...and only then wrote the spent-marker" "$([ "$(markers 'nudged-*')" = 1 ] && echo 1 || echo 0)"
run sA1 'and bump the timeout as well' "$PROJ"
check "A: after a decision the session is spent (silent)" \
  "$([ "$RC" = 0 ] && [ -z "$OUT" ] && echo 1 || echo 0)"
check "A: ...with exactly one record for it" \
  "$([ "$(records_for "$PROJ" sA1 | wc -l | tr -d ' ')" = 1 ] && echo 1 || echo 0)"

n=0
for i in 1 2 3; do
  run sA2 "add a retry to the mailer, take $i" "$PROJ" CLAUDE_PLUGIN_ROOT="$BROKEN"
  has "$(ctx)" 'could not size this prompt' && n=$((n + 1))
done
check "A: three failed attempts each degrade to the reminder" "$([ "$n" = 3 ] && echo 1 || echo 0)"
run sA2 'add a retry to the mailer, take 4' "$PROJ" CLAUDE_PLUGIN_ROOT="$BROKEN"
check "A: the attempt cap spends the session after three failures" \
  "$([ "$RC" = 0 ] && [ -z "$OUT" ] && echo 1 || echo 0)"
run sA2 'add a retry to the mailer, take 5' "$PROJ"
check "A: ...even once the engine works again (bounded, not per-prompt)" \
  "$([ -z "$OUT" ] && [ -z "$(records_for "$PROJ" sA2)" ] && echo 1 || echo 0)"

for p in 'Read prd.md' 'explain the booking flow' 'show me the routes' 'summarize prd.md'; do
  run sA3 "$p" "$PROJ"
  check "A: a short read instruction is skipped: '$p'" \
    "$([ "$RC" = 0 ] && [ -z "$OUT" ] && echo 1 || echo 0)"
done
check "A: ...and none of them minted a record" \
  "$([ -z "$(records_for "$PROJ" sA3)" ] && echo 1 || echo 0)"
run sA3 'Build the salon booking app described in prd.md' "$PROJ"
check "A: the change request after 'Read prd.md' is scored" \
  "$(has "$(ctx)" 'TIER: FULL' && echo 1 || echo 0)"
run sA4 'Read prd.md and build the booking app' "$PROJ"
check "A: a read verb with a second clause is still scored" \
  "$(has "$(ctx)" 'TIER: ' && echo 1 || echo 0)"
run sA5 'what does this do?' "$PROJ"
check "A: a short question is still skipped" "$([ -z "$OUT" ] && echo 1 || echo 0)"
run sA5 '/v:status' "$PROJ"
check "A: a slash command is still skipped" "$([ -z "$OUT" ] && echo 1 || echo 0)"

# A T3 classify that times out writes the engine's working artifacts on the way;
# they must not count as the session's record, or the retry would be silenced.
T3="$WORK/projT3"
mkrepo "$T3"
mkdir -p "$T3/.claude" "$T3/src"
printf '{}\n' >"$T3/.claude/compound-v.json"
printf 'def upload(chunk):\n    return chunk\n' >"$T3/src/uploader.py"
cat >"$T3/.claude/compound-v-impact-taxonomy.yaml" <<'YAML'
version: 1

path_patterns:
  - glob: "docs/**"
    difficulty_band: low
    impact_band: low

content_patterns:
  - match: "terms of service"
    pattern_type: literal
    case: insensitive
    scan: content
    kind: legal_copy
    impact_band: high

sensitive_path_list:
  - "**/*.env"
  - "**/secrets/**"

churn:
  exclude_paths:
    - "**/*.lock"
  format_commit_patterns:
    - "^chore: format"
YAML
FAKE_CLAUDE="$WORK/fake-claude.sh"
cat >"$FAKE_CLAUDE" <<'FAKE'
#!/usr/bin/env bash
[ -n "${FAKE_CLAUDE_SLEEP:-}" ] && sleep "$FAKE_CLAUDE_SLEEP"
printf '%s\n' "${FAKE_CLAUDE_REPLY:-plumbing}"
FAKE
chmod +x "$FAKE_CLAUDE"
run sT3 'please add a retry loop to the uploader module at src/uploader.py' "$T3" \
  CV_CLASSIFY_CLAUDE_BIN="$FAKE_CLAUDE" FAKE_CLAUDE_SLEEP=10 CV_CLASSIFY_TIMEOUT_S=1
check "A/T3: a timed-out classify degrades to the reminder" \
  "$(has "$(ctx)" 'could not size this prompt' && echo 1 || echo 0)"
run sT3 'please add a retry loop to the uploader module at src/uploader.py, with jitter' "$T3" \
  CV_CLASSIFY_CLAUDE_BIN="$FAKE_CLAUDE" FAKE_CLAUDE_REPLY=user-facing-minor
check "A/T3: the retry is scored, not silenced by the first try's working files" \
  "$(has "$(ctx)" 'TIER: SCOPED' && echo 1 || echo 0)"

# --------------------------------------------------------------------------- #
echo "=== B. not set up here: one line, nothing written ==="
BARE="$WORK/bare"
mkrepo "$BARE"
printf 'x\n' >"$BARE/app.txt"
git -C "$BARE" add app.txt
before="$(cd "$BARE" && find . -path ./.git -prune -o -print | sort)"
run sB1 'add a booking form' "$BARE"
check "B: exits 0 and emits a notice" "$([ "$RC" = 0 ] && [ -n "$OUT" ] && echo 1 || echo 0)"
check "B: the user sees it (systemMessage) and it names /v:init" \
  "$(has "$(sysmsg)" '/v:init' && has "$(sysmsg)" 'not set up' && echo 1 || echo 0)"
check "B: the model sees it too (additionalContext)" \
  "$(has "$(ctx)" '/v:init' && echo 1 || echo 0)"
check "B: it is one line" "$([ "$(sysmsg | wc -l | tr -d ' ')" -le 1 ] && echo 1 || echo 0)"
after="$(cd "$BARE" && find . -path ./.git -prune -o -print | sort)"
check "B: nothing was written into the repository" \
  "$([ "$before" = "$after" ] \
     && [ "$(git -C "$BARE" status --porcelain --untracked-files=all)" = "A  app.txt" ] \
     && echo 1 || echo 0)"
check "B: its marker lives in the temp-dir store, outside the repository" \
  "$([ "$(markers 'setup-*')" = 1 ] && [ -z "$(find "$BARE" -name 'setup-*' -o -name 'nudged-*')" ] && echo 1 || echo 0)"
run sB1 'add a booking form, again' "$BARE"
check "B: once per session (second prompt silent)" "$([ "$RC" = 0 ] && [ -z "$OUT" ] && echo 1 || echo 0)"
run sB2 'add a booking form' "$BARE"
check "B: a new session is told again" "$(has "$(sysmsg)" '/v:init' && echo 1 || echo 0)"
run sB3 '/v:init' "$BARE"
check "B: a slash command (e.g. /v:init itself) gets no notice" "$([ -z "$OUT" ] && echo 1 || echo 0)"
run sB4 'add a booking form' "$BARE" CV_DISABLED_HOOKS=triage-prompt-nudge
check "B: CV_DISABLED_HOOKS still silences it" "$([ "$RC" = 0 ] && [ -z "$OUT" ] && echo 1 || echo 0)"
run sB5 'add a booking form' "$BARE" CV_HEADLESS_CLASSIFY=1
check "B: the headless-classify guard still silences it" "$([ -z "$OUT" ] && echo 1 || echo 0)"
mkdir -p "$BARE/.tmp-in-repo"
run sB6 'add a booking form' "$BARE" TMPDIR="$BARE/.tmp-in-repo"
check "B: a TMPDIR inside the repository -> silent, and no marker in the repo" \
  "$([ -z "$OUT" ] && [ -z "$(find "$BARE/.tmp-in-repo" -type f)" ] && echo 1 || echo 0)"
rmdir "$BARE/.tmp-in-repo"
run sB7 'add a booking form' "$BARE" CURSOR_PLUGIN_ROOT="$REPO"
check "B: the Cursor shape carries the notice as additional_context" \
  "$(printf '%s' "$OUT" | jq -r '.additional_context // ""' | grep -q '/v:init' && echo 1 || echo 0)"

# --------------------------------------------------------------------------- #
echo "=== C. no jq: one line naming jq ==="
NOJQ="$WORK/nojq"
mkdir -p "$NOJQ"
printf '#!/bin/sh\nexit 127\n' >"$NOJQ/jq"
chmod +x "$NOJQ/jq"
run_nojq() { # raw-payload [env...]
  local p="$1"
  shift
  OUT="$(printf '%s' "$p" | env PATH="$NOJQ:$PATH" "$@" bash "$NUDGE" 2>/dev/null)"
  RC=$?
}
P1="$(payload sC1 'add a retry to the mailer' "$PROJ")"
run_nojq "$P1"
check "C: exits 0 with output" "$([ "$RC" = 0 ] && [ -n "$OUT" ] && echo 1 || echo 0)"
check "C: the output is valid JSON with a systemMessage naming jq" \
  "$(printf '%s' "$OUT" | python3 -c '
import json, sys
d = json.load(sys.stdin)
m = d.get("systemMessage", "")
c = (d.get("hookSpecificOutput") or {}).get("additionalContext", "")
sys.exit(0 if "jq" in m and m == c and "\n" not in m
         and d["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit" else 1)
' 2>/dev/null && echo 1 || echo 0)"
run_nojq "$P1"
check "C: once per session" "$([ "$RC" = 0 ] && [ -z "$OUT" ] && echo 1 || echo 0)"
run_nojq "$(payload sC2 'add a retry' "$BARE")"
check "C: a new session is told again" "$(printf '%s' "$OUT" | grep -q 'jq is not installed' && echo 1 || echo 0)"
run_nojq '{"hook_event_name":"UserPromptSubmit","prompt":"add a retry"}'
check "C: no session id -> silent" "$([ "$RC" = 0 ] && [ -z "$OUT" ] && echo 1 || echo 0)"
run_nojq '{"hook_event_name":"PreToolUse","session_id":"sC3","tool_name":"Write"}'
check "C: another event -> silent" "$([ -z "$OUT" ] && echo 1 || echo 0)"
run_nojq '{"hook_event_name":"UserPromptSubmit","session_id":"../../etc","prompt":"x"}'
check "C: a session id outside the safe charset cannot name a path outside the store" \
  "$([ ! -e "$TMPDIR/etc" ] && [ ! -e "$WORK/etc" ] && echo 1 || echo 0)"
run_nojq "$(payload sC4 'add a retry' "$PROJ")" CV_DISABLED_HOOKS=triage-prompt-nudge
check "C: CV_DISABLED_HOOKS still silences it" "$([ -z "$OUT" ] && echo 1 || echo 0)"
check "C: nothing was scored without jq" "$([ -z "$(records_for "$PROJ" sC1)" ] && echo 1 || echo 0)"

# --------------------------------------------------------------------------- #
echo "=== D. FULL is a directive, SCOPED stays an offer ==="
run sD1 'add online payments to the booking flow' "$PROJ"
c="$(ctx)"
check "D: the FULL line says Claude is starting the pipeline" \
  "$(has "$c" 'TIER: FULL' && has "$c" 'you are starting the Compound V pipeline' && echo 1 || echo 0)"
check "D: ...names the chain brainstorming -> writing-plans -> /v:orchestrate -> /v:dispatch" \
  "$(printf '%s' "$c" | grep -q 'superpowers:brainstorming → superpowers:writing-plans → /v:orchestrate → /v:dispatch' && echo 1 || echo 0)"
check "D: ...unless the user says to skip it" "$(has "$c" 'unless they say to skip it' && echo 1 || echo 0)"
check "D: ...and no longer only asks to offer it" \
  "$(has "$c" 'FULL — offer it to the user' && echo 0 || echo 1)"
check "D: the not-a-change-request escape is kept" \
  "$(has "$c" 'If this prompt was NOT a change request' && echo 1 || echo 0)"
rec="$(records_for "$PROJ" sD1 | head -1)"
check "D: the record is still written and still FULL" \
  "$([ -n "$rec" ] && jq -e '.tier == "FULL"' "$rec" >/dev/null 2>&1 && echo 1 || echo 0)"
check "D: SCOPED is still an offer" \
  "$(grep -q 'SCOPED — offer it to the user; on acceptance' "$NUDGE" && echo 1 || echo 0)"


# --------------------------------------------------------------------------- #
echo "=== E. small talk and DIRECT prompts do not spend the session ==="
PROJE="$WORK/proje"
mkrepo "$PROJE"
mkdir -p "$PROJE/.claude"
printf '{"stance": "cost-aware"}\n' >"$PROJE/.claude/compound-v.json"
printf '# prd\n' >"$PROJE/prd.md"
git -C "$PROJE" add -A && git -C "$PROJE" -c user.email=t@t -c user.name=t commit -qm seed
python3 "$REPO/scripts/compound-v-onboard.py" draft-taxonomy --repo "$PROJE" --emit-yaml \
  >"$PROJE/.claude/compound-v-impact-taxonomy.yaml" 2>/dev/null
for p in 'hi' 'Ok' 'thanks a lot'; do
  run sE1 "$p" "$PROJE"
  check "E: small talk '$p' is silent" "$([ "$RC" = 0 ] && [ -z "$OUT" ] && echo 1 || echo 0)"
done
check "E: ...and minted no record" "$([ -z "$(records_for "$PROJE" sE1)" ] && echo 1 || echo 0)"
run sE2 'Please read prd.md' "$PROJE"
check "E: a polite read of a doc is scored DIRECT" "$(has "$(ctx)" 'TIER: DIRECT' && echo 1 || echo 0)"
check "E: ...and a DIRECT decision writes no spent-marker" \
  "$(find "$STORE" -name 'nudged-*' -newer "$PROJE/prd.md" 2>/dev/null | wc -l | tr -d ' ' | grep -qx 0 && echo 1 || echo 0)"
run sE2 'Build a salon booking app with stylists, services and online payments' "$PROJE"
check "E: the salon request after a DIRECT prompt still gets the FULL directive" \
  "$(has "$(ctx)" 'TIER: FULL' && has "$(ctx)" 'you are starting the Compound V pipeline' && echo 1 || echo 0)"
run sE2 'and now rename the stylist model to staff member everywhere' "$PROJE"
check "E: after FULL the session is spent" "$([ -z "$OUT" ] && echo 1 || echo 0)"
run sE3 'Build salon app' "$PROJE"
check "E: a three-word change request is still scored" "$(has "$(ctx)" 'TIER:' && echo 1 || echo 0)"

printf 'tests/test-triage-hook-engagement.sh: %d passed, %d failed\n' "$pass" "$fail"
[ "$fail" = "0" ] || exit 1
