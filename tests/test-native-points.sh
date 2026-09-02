#!/usr/bin/env bash
# tests/test-native-points.sh — the decision tables of hooks/triage-prompt-nudge.sh
# (UserPromptSubmit) and hooks/postcompact-resume.sh (PostCompact), plus the
# hooks.json registration that makes both of them real.
#
# Repo precedent: tests/test-epic-goal-stop.sh and tests/test-lane-guard.sh do the
# same for the Stop hook and the lane guard; no hook in this plugin ships an
# inline --selftest, so the test home is here.
#
# THE THREE RULES THIS FILE EXISTS TO DEFEND
#
#   1. THE NUDGE MUST NOT BECOME AN INVOCATION. The hook fires on EVERY prompt
#      while `/v:triage` WRITES AND COMMITS a record. If eligibility or dedup
#      breaks, a mid-run "status?" mints a record that lands in the outcome
#      stream the miscalibration breaker computes its rolling rate from, and
#      changes which record the Stop rule sees as covering the diff. So: no
#      covering record, no active run, once per session — each asserted here,
#      and the project tree is asserted UNCHANGED after a fire.
#
#   2. UNPARSEABLE STDIN MUST NOT ANSWER FOR THE CURRENT DIRECTORY. This is a
#      REGRESSION TEST for a defect a live probe caught and reasoning had not:
#      junk on stdin left every field empty, `cwd` fell back to $PWD, and
#      postcompact-resume.sh reported on whatever repository the harness
#      happened to be standing in. The guard is that the jq parse must SUCCEED,
#      not merely yield empty fields — and below, that guard is REMOVED from a
#      copy of the hook and the old bug is shown to come back, because a guard
#      nobody has watched fail is a guard nobody should trust.
#
#   3. NEITHER HOOK MAY EVER BLOCK A TURN. UserPromptSubmit is blocking-capable:
#      exit 2 REJECTS THE USER'S PROMPT, and exit 2 is exactly what bash returns
#      for a parse error above the in-script trap. Every invocation below is
#      asserted to exit 0, the `|| true` registration is asserted present on
#      both new events, and the two halves of the fail-open contract are probed
#      rather than assumed — a break ABOVE the trap (registration saves it) and
#      a break BELOW it (the trap saves it).
#
# Payloads are JSON-encoded by jq rather than hand-quoted: a shell-quoting
# accident that silently rewrote a prompt or a summary would make a green run
# meaningless.

set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd -P)"
NUDGE="${TRIAGE_NUDGE_SRC:-$REPO/hooks/triage-prompt-nudge.sh}"
PC="${POSTCOMPACT_SRC:-$REPO/hooks/postcompact-resume.sh}"
HOOKS_JSON="$REPO/hooks/hooks.json"

pass=0
fail=0
ok()  { pass=$((pass + 1)); printf 'PASS %s\n' "$1"; }
bad() { fail=$((fail + 1)); printf 'FAIL %s\n' "$1"; }
check(){ if [ "$2" = "1" ]; then ok "$1"; else bad "$1"; fi; }

# --------------------------------------------------------------------------- #
# Preconditions — loud, never silently skipped.
# --------------------------------------------------------------------------- #
[ -f "$NUDGE" ] || { echo "FATAL: $NUDGE missing"; exit 1; }
[ -x "$NUDGE" ] || { echo "FATAL: $NUDGE is not executable"; exit 1; }
[ -f "$PC" ]    || { echo "FATAL: $PC missing"; exit 1; }
[ -x "$PC" ]    || { echo "FATAL: $PC is not executable"; exit 1; }
[ -f "$HOOKS_JSON" ] || { echo "FATAL: $HOOKS_JSON missing"; exit 1; }
command -v jq >/dev/null 2>&1 || { echo "FATAL: jq required"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "FATAL: python3 required"; exit 1; }
command -v shasum >/dev/null 2>&1 || { echo "FATAL: shasum required"; exit 1; }
[ -f "$REPO/scripts/compound-v-dashboard.py" ] \
  || { echo "FATAL: the resume renderer both hooks reuse is missing"; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# The store both hooks would write into lives under TMPDIR. Point it at the
# sandbox so a developer's real markers can neither leak in nor be clobbered.
export TMPDIR="$WORK/tmp"
mkdir -p "$TMPDIR"
export PYTHONDONTWRITEBYTECODE=1
# How the hooks actually run: the harness always sets this, and it is what
# selects the Claude-shaped hookSpecificOutput branch.
export CLAUDE_PLUGIN_ROOT="$REPO"
unset CURSOR_PLUGIN_ROOT 2>/dev/null || true
unset COPILOT_CLI 2>/dev/null || true

# --------------------------------------------------------------------------- #
# Sandbox project: a git-rooted tree with a Compound V surface.
# --------------------------------------------------------------------------- #
PROJ="$WORK/proj"
PREEVAL="$PROJ/docs/superpowers/pre-eval"
XROOT="$PROJ/docs/superpowers/execution"
RUN="$XROOT/2099-01-01-sandbox"
mkdir -p "$PROJ/.git" "$PREEVAL" "$RUN"
# A run dir is only a run to the dashboard when it holds a manifest.
printf 'feature: sandbox\njobs:\n  - id: task-1\n  - id: task-2\n' >"$RUN/manifest.yaml"

# A project WITHOUT any Compound V surface.
OTHER="$WORK/other"
mkdir -p "$OTHER/.git"

now_ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }

set_run_phase() { # phase [timestamp]
  jq -n --arg p "$1" --arg ts "${2:-$(now_ts)}" \
    '{run_id:"2099-01-01-sandbox", phase:$p, updated_at:$ts,
      jobs:{"task-1":{status:"running"},"task-2":{status:"pending"}}}' \
    >"$RUN/state.json"
}

prompt_payload() { # session prompt [cwd]
  jq -n --arg s "$1" --arg p "$2" --arg c "${3:-$PROJ}" \
    '{hook_event_name:"UserPromptSubmit", session_id:$s, cwd:$c, prompt:$p,
      transcript_path:"/dev/null", permission_mode:"default"}'
}

compact_payload() { # session summary [cwd] [trigger]
  jq -n --arg s "$1" --arg sum "$2" --arg c "${3:-$PROJ}" --arg t "${4:-auto}" \
    '{hook_event_name:"PostCompact", session_id:$s, cwd:$c, trigger:$t,
      compact_summary:$sum, transcript_path:"/dev/null"}'
}

# Every invocation goes through these two, which record the exit status: rule 3
# says a non-zero exit is a defect on its own, whatever the output was.
NUDGE_RC=0
run_nudge() {
  local out
  out="$(prompt_payload "$@" | bash "$NUDGE" 2>/dev/null)"
  NUDGE_RC=$?
  printf '%s' "$out"
}
PC_RC=0
run_pc() {
  local out
  out="$(compact_payload "$@" | bash "$PC" 2>/dev/null)"
  PC_RC=$?
  printf '%s' "$out"
}

tree_digest() { find "$PROJ" -type f -exec shasum -a 256 {} + 2>/dev/null | sort | shasum -a 256; }

# --------------------------------------------------------------------------- #
# 1. The nudge fires exactly once, and only when it is entitled to.
# --------------------------------------------------------------------------- #
set_run_phase MERGED            # nothing active

out="$(run_nudge sess-A 'add a retry to the uploader')"
check "eligible prompt exits 0" "$([ "$NUDGE_RC" = 0 ] && echo 1 || echo 0)"
check "eligible prompt emits UserPromptSubmit additionalContext" \
  "$(printf '%s' "$out" | jq -e '.hookSpecificOutput.hookEventName == "UserPromptSubmit"
                                 and (.hookSpecificOutput.additionalContext | test("/v:triage"))' \
     >/dev/null 2>&1 && echo 1 || echo 0)"
check "the nudge names the tiers it is asking about" \
  "$(printf '%s' "$out" | grep -q 'DIRECT' && printf '%s' "$out" | grep -q 'SCOPED' && echo 1 || echo 0)"
check "the nudge says it writes nothing itself" \
  "$(printf '%s' "$out" | grep -qi 'never writes or commits' && echo 1 || echo 0)"
check "the nudge does NOT tell the model to triage unconditionally" \
  "$(printf '%s' "$out" | grep -qi 'if this prompt is NOT a change request' && echo 1 || echo 0)"

# RULE 1, mechanically: firing must leave the project tree byte-identical.
tree_before="$(tree_digest)"
out_again="$(run_nudge sess-A2 'change the parser')"
tree_after="$(tree_digest)"
check "a fire writes NOTHING into the project (no record is minted)" \
  "$([ "$tree_before" = "$tree_after" ] && [ -n "$out_again" ] && echo 1 || echo 0)"
check "the once-marker lives OUTSIDE the project (under TMPDIR)" \
  "$([ -z "$(find "$PROJ" -name 'nudged-*' 2>/dev/null)" ] \
     && [ -n "$(find "$TMPDIR" -name 'nudged-*' 2>/dev/null)" ] && echo 1 || echo 0)"

out2="$(run_nudge sess-A 'and also bump the timeout')"
check "a second prompt in the SAME session is silent (idempotent)" \
  "$([ -z "$out2" ] && [ "$NUDGE_RC" = 0 ] && echo 1 || echo 0)"

out3="$(run_nudge sess-B 'rename the config key')"
check "a different session fires again" "$([ -n "$out3" ] && echo 1 || echo 0)"

# --- 3.1.0: a QUESTION must not spend the session's one nudge -----------------
# The audit named this hole precisely: the nudge fires at most once per session,
# so a session whose first prompt is "what does this do?" burned the reminder and
# the real change request that followed got nothing. A short question now returns
# BEFORE the marker is written, leaving the session armed.
q_out="$(run_nudge sess-Q 'what does this do?')"
check "a short question does not nudge" "$([ -z "$q_out" ] && echo 1 || echo 0)"
q_after="$(run_nudge sess-Q 'add a retry to the uploader')"
check "the question did NOT burn the session's nudge" \
  "$([ -n "$q_after" ] && echo 1 || echo 0)"
q_third="$(run_nudge sess-Q 'and bump the timeout too')"
check "the nudge is still once-per-session after a question" \
  "$([ -z "$q_third" ] && echo 1 || echo 0)"
markers_before="$(find "$TMPDIR" -name 'nudged-*' 2>/dev/null | wc -l | tr -d ' ')"
_="$(run_nudge sess-Q2 'why is this failing?')"
markers_after="$(find "$TMPDIR" -name 'nudged-*' 2>/dev/null | wc -l | tr -d ' ')"
check "a question leaves NO marker behind (the session stays armed)" \
  "$([ "$markers_before" = "$markers_after" ] && echo 1 || echo 0)"
# The test is narrow on purpose: only a SHORT prompt ending in `?` is a question.
long_q="refactor the pricing module and propagate the new type to every caller, \
then re-check the callers in the billing package and the reporting package, and \
make sure the VAT rounding still matches the fixtures, right?"
lq_out="$(run_nudge sess-LQ "$long_q")"
check "a long prompt that merely ends in '?' still nudges" \
  "$([ -n "$lq_out" ] && echo 1 || echo 0)"
nq_out="$(run_nudge sess-NQ 'rename getUser to fetchUser')"
check "a plain change request is unaffected" \
  "$([ -n "$nq_out" ] && echo 1 || echo 0)"

# --------------------------------------------------------------------------- #
# 2. Exemptions.
# --------------------------------------------------------------------------- #
i=0
for cmd in '/v:status' '/v:triage add a retry' '/clear'; do
  i=$((i + 1))
  o="$(run_nudge "sess-slash-$i" "$cmd")"
  check "a slash command is silent: $cmd" "$([ -z "$o" ] && echo 1 || echo 0)"
done

# A covering record for THIS session silences it; one for another session does not.
jq -n '{id:"2099-01-01-x", session_id:"sess-D", decision:"FASTPATH_ELIGIBLE",
        tier:"DIRECT", declared_paths:["README.md"]}' >"$PREEVAL/x.json"
o="$(run_nudge sess-D 'change the readme')"
check "a pre-eval record for this session silences it" "$([ -z "$o" ] && echo 1 || echo 0)"
o="$(run_nudge sess-E 'change the readme')"
check "a record for ANOTHER session does not silence it" "$([ -n "$o" ] && echo 1 || echo 0)"

# A record that cannot be read is NOT an exemption (the Stop rule's stance).
printf '{ this is not json' >"$PREEVAL/broken.json"
o="$(run_nudge sess-D2 'change the readme')"
check "an unreadable record is not an exemption" "$([ -n "$o" ] && echo 1 || echo 0)"
rm -f "$PREEVAL/broken.json"

# An active run silences it; a finished one does not.
set_run_phase DISPATCHED
o="$(run_nudge sess-F 'add a retry')"
check "an active run silences it" "$([ -z "$o" ] && echo 1 || echo 0)"
o="$(run_nudge sess-F2 'add a retry')"
check "an active run silences it on EVERY prompt, not just the first" \
  "$([ -z "$o" ] && echo 1 || echo 0)"
set_run_phase MERGED
o="$(run_nudge sess-G 'add a retry')"
check "a MERGED run no longer silences it" "$([ -n "$o" ] && echo 1 || echo 0)"

# Freshness comes from the RECORDED timestamp, never an mtime -- git rewrites
# mtimes on clone and branch switch, which would make every historical run in
# the repository look seconds old.
set_run_phase DISPATCHED "2020-01-01T00:00:00Z"
o="$(run_nudge sess-G2 'add a retry')"
check "a run whose RECORDED timestamp is ancient does not silence it (fresh mtime notwithstanding)" \
  "$([ -n "$o" ] && echo 1 || echo 0)"
set_run_phase MERGED

# --------------------------------------------------------------------------- #
# 3. Fail-open / fail-silent inputs.
# --------------------------------------------------------------------------- #
o="$(printf 'not json at all' | bash "$NUDGE" 2>/dev/null)"; rc=$?
check "junk stdin: exit 0 and no output" "$([ "$rc" = 0 ] && [ -z "$o" ] && echo 1 || echo 0)"
o="$(printf '' | bash "$NUDGE" 2>/dev/null)"; rc=$?
check "empty stdin: exit 0 and no output" "$([ "$rc" = 0 ] && [ -z "$o" ] && echo 1 || echo 0)"
o="$(printf '"a bare json string"' | bash "$NUDGE" 2>/dev/null)"; rc=$?
check "a non-object JSON payload: exit 0 and no output" \
  "$([ "$rc" = 0 ] && [ -z "$o" ] && echo 1 || echo 0)"

o="$(jq -n --arg c "$PROJ" '{hook_event_name:"PreToolUse", session_id:"sess-H",
                             cwd:$c, tool_name:"Write"}' | bash "$NUDGE" 2>/dev/null)"
check "a non-UserPromptSubmit payload is silent (a mis-registration must not nudge on tool calls)" \
  "$([ -z "$o" ] && echo 1 || echo 0)"

o="$(run_nudge sess-I 'add a retry' "$OTHER")"
check "a project with no Compound V surface is silent" "$([ -z "$o" ] && echo 1 || echo 0)"

o="$(jq -n --arg c "$PROJ" '{hook_event_name:"UserPromptSubmit", cwd:$c,
                             prompt:"add a retry"}' | bash "$NUDGE" 2>/dev/null)"
check "a payload with no session_id is silent (nothing to deduplicate on)" \
  "$([ -z "$o" ] && echo 1 || echo 0)"

# --------------------------------------------------------------------------- #
# 4. PostCompact.
# --------------------------------------------------------------------------- #
set_run_phase DISPATCHED

o="$(run_pc sess-J 'We were refactoring the uploader and fixing a flaky test.')"
check "PostCompact exits 0 with an active run" "$([ "$PC_RC" = 0 ] && echo 1 || echo 0)"
check "PostCompact names the unfinished run" \
  "$(printf '%s' "$o" | grep -q '2099-01-01-sandbox' && echo 1 || echo 0)"
check "PostCompact reuses the dashboard's line verbatim" \
  "$(printf '%s' "$o" | grep -q 'UNFINISHED COMPOUND V WORK' && echo 1 || echo 0)"
check "PostCompact reports a summary that does NOT carry the id" \
  "$(printf '%s' "$o" | grep -q 'does NOT mention' && echo 1 || echo 0)"
check "PostCompact reports the trigger it was handed" \
  "$(printf '%s' "$o" | grep -q 'trigger=auto' && echo 1 || echo 0)"
# The runtime folds PostCompact stdout into the compaction's DISPLAY text and has
# no hookSpecificOutput variant for this event, so JSON here would be rendered
# raw to the user (probed on Claude Code 2.1.238).
check "PostCompact emits PLAIN TEXT, never a JSON object" \
  "$(printf '%s' "$o" | grep -q '^{' && echo 0 || echo 1)"

o="$(run_pc sess-K 'Mid-run on 2099-01-01-sandbox, task-1 still going.')"
check "a summary that carries the id is reported as mentioned" \
  "$(printf '%s' "$o" | grep -q 'does mention' && echo 1 || echo 0)"

o="$(run_pc sess-K2 'manual compaction' "$PROJ" manual)"
check "the manual trigger is reported as manual" \
  "$(printf '%s' "$o" | grep -q 'trigger=manual' && echo 1 || echo 0)"

set_run_phase MERGED
o="$(run_pc sess-L 'anything at all')"
check "nothing unfinished -> PostCompact is silent" \
  "$([ -z "$o" ] && [ "$PC_RC" = 0 ] && echo 1 || echo 0)"

o="$(jq -n --arg c "$PROJ" '{hook_event_name:"SessionStart", cwd:$c, source:"compact"}' \
     | bash "$PC" 2>/dev/null)"
check "a non-PostCompact payload is silent" "$([ -z "$o" ] && echo 1 || echo 0)"

o="$(run_pc sess-N 'x' "$OTHER")"
check "a project with no execution root is silent" "$([ -z "$o" ] && echo 1 || echo 0)"

set_run_phase DISPATCHED "2020-01-01T00:00:00Z"
o="$(run_pc sess-M 'x')"
check "a run whose RECORDED timestamp is ancient stays silent after compaction" \
  "$([ -z "$o" ] && echo 1 || echo 0)"
set_run_phase DISPATCHED

# --------------------------------------------------------------------------- #
# 5. REGRESSION + PLANTED VIOLATION: unparseable stdin must not answer for $PWD.
#
# The defect, as it actually happened: junk on stdin made every jq field empty,
# `cwd` fell back to $PWD, and the hook reported on whatever repository the
# harness was standing in. Below, the hook is run FROM INSIDE the sandbox
# project, which has an active run -- so a hook that falls back to $PWD prints,
# and a correct one says nothing. Then the guard is REMOVED from a copy and the
# bug is shown to come back, because a guard nobody has watched fail is a guard
# nobody should trust.
# --------------------------------------------------------------------------- #
o="$( (cd "$PROJ" && printf 'junk' | bash "$PC" 2>/dev/null) )"; rc=$?
check "REGRESSION: junk stdin does not report on the current directory" \
  "$([ -z "$o" ] && [ "$rc" = 0 ] && echo 1 || echo 0)"
o="$( (cd "$PROJ" && printf '' | bash "$PC" 2>/dev/null) )"; rc=$?
check "REGRESSION: empty stdin does not report on the current directory" \
  "$([ -z "$o" ] && [ "$rc" = 0 ] && echo 1 || echo 0)"

MUT="$WORK/postcompact-unguarded.sh"
python3 - "$PC" "$MUT" <<'PYEOF'
import sys
src, dst = sys.argv[1], sys.argv[2]
text = open(src).read()
subs = [("  ' 2>/dev/null)\" || return 1", "  ' 2>/dev/null)\" || true"),
        ('[ -n "$fields" ] || return 1', ':')]
for old, new in subs:
    if text.count(old) != 1:
        sys.exit("MUTATION TARGET NOT UNIQUE (%d hits): %r" % (text.count(old), old))
    text = text.replace(old, new)
open(dst, "w").write(text)
PYEOF
mut_built=$?
check "the planted violation could be built (the guard is where the test says it is)" \
  "$([ "$mut_built" = 0 ] && echo 1 || echo 0)"
if [ "$mut_built" = 0 ]; then
  chmod +x "$MUT"
  o="$( (cd "$PROJ" && printf 'junk' | bash "$MUT" 2>/dev/null) )"
  check "PLANTED VIOLATION: without the parse-success guard the old bug returns" \
    "$([ -n "$o" ] && echo 1 || echo 0)"
fi

# --------------------------------------------------------------------------- #
# 6. The fail-open contract, both halves.
#
# Exit 2 is the blocking code, and bash uses it for a PARSE ERROR. A script whose
# first command will not parse never reaches its own `trap` line -- which is
# exactly why the `|| true` registration has to exist independently of the trap.
# For UserPromptSubmit the stake is higher than for Stop: exit 2 there REJECTS
# THE USER'S PROMPT.
# --------------------------------------------------------------------------- #
broken="$WORK/broken.sh"
printf '#!/usr/bin/env bash\nthis is ( not valid bash\n' >"$broken"
chmod +x "$broken"
sh -c "'$broken'" </dev/null >/dev/null 2>&1; raw_rc=$?
sh -c "'$broken' || true" </dev/null >/dev/null 2>&1; wrapped_rc=$?
check "MECHANISM (a): a syntactically broken hook exits non-zero on its own (rc=$raw_rc)" \
  "$([ "$raw_rc" != "0" ] && echo 1 || echo 0)"
check "MECHANISM (a): exit 2 is what bash returns for it, and 2 is the blocking code" \
  "$([ "$raw_rc" = "2" ] && echo 1 || echo 0)"
check "MECHANISM (a): the '|| true' registration turns that into exit 0" \
  "$([ "$wrapped_rc" = "0" ] && echo 1 || echo 0)"

for h in "$NUDGE" "$PC"; do
  name="$(basename "$h")"
  mid="$WORK/mid-$name"
  sed 's/^_HOOK_TAG=.*/_HOOK_TAG="x"; this is ( not valid/' "$h" >"$mid"
  o="$(printf '{}' | bash "$mid" 2>/dev/null)"; rc=$?
  check "MECHANISM (b): a break BELOW the trap in $name still exits 0 with no output (rc=$rc)" \
    "$([ "$rc" = "0" ] && [ -z "$o" ] && echo 1 || echo 0)"
done

# --------------------------------------------------------------------------- #
# 7. Registration. A hook nobody registered is the defect this whole release is
#    about, so the wiring is asserted, not assumed.
# --------------------------------------------------------------------------- #
check "hooks.json is valid JSON" \
  "$(jq empty "$HOOKS_JSON" >/dev/null 2>&1 && echo 1 || echo 0)"

ups="$(jq -r '.hooks.UserPromptSubmit[]?.hooks[]?.command // empty' "$HOOKS_JSON" 2>/dev/null \
       | grep 'triage-prompt-nudge' || true)"
check "REGISTRATION: UserPromptSubmit runs triage-prompt-nudge.sh" \
  "$([ -n "$ups" ] && echo 1 || echo 0)"
check "REGISTRATION: it carries '|| true' (exit 2 on this event rejects the prompt)" \
  "$(printf '%s' "$ups" | grep -q '|| true' && echo 1 || echo 0)"
check "REGISTRATION: UserPromptSubmit carries NO matcher (it is not a tool event)" \
  "$(jq -e '[.hooks.UserPromptSubmit[]? | has("matcher")] | any | not' "$HOOKS_JSON" \
     >/dev/null 2>&1 && echo 1 || echo 0)"

pcr="$(jq -r '.hooks.PostCompact[]?.hooks[]?.command // empty' "$HOOKS_JSON" 2>/dev/null \
       | grep 'postcompact-resume' || true)"
check "REGISTRATION: PostCompact runs postcompact-resume.sh" \
  "$([ -n "$pcr" ] && echo 1 || echo 0)"
check "REGISTRATION: it carries '|| true'" \
  "$(printf '%s' "$pcr" | grep -q '|| true' && echo 1 || echo 0)"
check "REGISTRATION: PostCompact carries no matcher, so manual AND auto fire" \
  "$(jq -e '[.hooks.PostCompact[]? | has("matcher")] | any | not' "$HOOKS_JSON" \
     >/dev/null 2>&1 && echo 1 || echo 0)"

# The lane guard: a PreToolUse non-zero exit is NOT a deny, and lane-guard.sh's
# own wrapper already forces exit 0, so copying the Stop idiom here would be
# cargo-culting a mechanism that does not apply.
lg="$(jq -r '.hooks.PreToolUse[]? | select((.hooks[]?.command // "") | test("lane-guard"))
             | .hooks[]?.command' "$HOOKS_JSON" 2>/dev/null | grep 'lane-guard' || true)"
check "REGISTRATION: the lane guard is registered on PreToolUse" \
  "$([ -n "$lg" ] && echo 1 || echo 0)"
check "REGISTRATION: the lane guard does NOT carry '|| true'" \
  "$(printf '%s' "$lg" | grep -q '|| true' && echo 0 || echo 1)"
check "REGISTRATION: its matcher is exactly Write|Edit|MultiEdit|NotebookEdit|Bash" \
  "$(jq -e '[.hooks.PreToolUse[]? | select((.hooks[]?.command // "") | test("lane-guard"))
            | .matcher] == ["Write|Edit|MultiEdit|NotebookEdit|Bash"]' "$HOOKS_JSON" \
     >/dev/null 2>&1 && echo 1 || echo 0)"
check "REGISTRATION: the lane guard runs synchronously (async false)" \
  "$(jq -e '[.hooks.PreToolUse[]? | select((.hooks[]?.command // "") | test("lane-guard"))
            | .hooks[]?.async] == [false]' "$HOOKS_JSON" >/dev/null 2>&1 && echo 1 || echo 0)"
# Registering it on Bash is the point: a Write|Edit-only matcher is decorative in
# an environment that nudges agents toward sed and heredocs (1D probe, 0982ce0).
check "REGISTRATION: the matcher matches the tool set the hook itself accepts" \
  "$(grep -q '"Write", "Edit", "MultiEdit", "NotebookEdit", "Bash"' \
     "$REPO/hooks/lane-guard.sh" && echo 1 || echo 0)"

# The Stop registration is another suite's assertion; what belongs HERE is that
# editing this file did not leave a dangling command behind.
missing=0
while IFS= read -r cmd; do
  [ -n "$cmd" ] || continue
  f="${cmd#\"}"
  f="${f%%\"*}"
  f="${f/\$\{CLAUDE_PLUGIN_ROOT\}/$REPO}"
  case "$f" in
    "$REPO"/hooks/*.sh) [ -x "$f" ] || missing=$((missing + 1)) ;;
    *) missing=$((missing + 1)) ;;
  esac
done <<EOF
$(jq -r '.hooks | to_entries[] | .value[]? | .hooks[]? | .command // empty' "$HOOKS_JSON" 2>/dev/null)
EOF
check "REGISTRATION: every registered command points at an executable hook file" \
  "$([ "$missing" = "0" ] && echo 1 || echo 0)"

echo "-------------------------------------------"
printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" = "0" ] || exit 1
echo "OK native-points decision tables green"
