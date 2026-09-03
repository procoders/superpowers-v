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
#   1. THE HOOK SCORES, AND EVERY GATE THAT BOUNDS THE SCORING HOLDS. As of
#      v3.4 the UserPromptSubmit hook RUNS `compound-v-preeval.py triage` — it
#      writes a session-bound pre-eval record and appends a `predicted` event to
#      the stream the miscalibration breaker computes its rolling rate from. The
#      hook fires on EVERY prompt, so if eligibility or dedup breaks, a mid-run
#      "status?" mints a record that pollutes that stream and changes which
#      record the Stop rule sees as covering the diff. So: no covering record,
#      no active run, no slash command, no short question, once per session —
#      each asserted here. And what a fire writes is asserted to be EXACTLY the
#      pre-eval artifacts and the outcome stream: a hook that started touching
#      anything else in the project would be a different and much worse thing.
#      The one write it must never do is a commit; the emitted context says the
#      record is uncommitted and whose job the commit is, and that is asserted.
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
[ -f "$REPO/scripts/compound-v-preeval.py" ] \
  || { echo "FATAL: the scorer the UserPromptSubmit hook now runs is missing"; exit 1; }

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

# NO TEST IN THIS FILE MAY SPEND A REAL MODEL CALL. As of v3.4.1 the hook
# finishes T3 with a headless `claude -p` (and a codex fallback), and both
# routes resolve their binary from PATH unless these are set -- so on a
# developer machine, which has a real `claude`, a needs_t3 request would
# silently make a live call. An empty override DISABLES a route (see
# `_resolve_bin` in compound-v-classify-request.py); the T3 section below
# points them at fakes for the cases that need one, and every other case in
# this file inherits "no backend at all".
export CV_CLASSIFY_CLAUDE_BIN=""
export CV_CLASSIFY_CODEX_BIN=""
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

proj_files() { ( cd "$PROJ" && find . -type f 2>/dev/null | sed 's|^\./||' | sort ); }

# The context line the runtime actually reads, or empty.
ctx() { printf '%s' "$1" | jq -r '.hookSpecificOutput.additionalContext // ""' 2>/dev/null; }

# Every pre-eval record in the sandbox that is bound to session "$1".
records_for() {
  find "$PREEVAL" -maxdepth 1 -type f -name '*.json' 2>/dev/null \
    | while IFS= read -r f; do
        jq -e --arg s "$1" '(type == "object") and (.session_id == $s)' "$f" \
          >/dev/null 2>&1 && printf '%s\n' "$f"
      done
}
count_records() { find "$PREEVAL" -maxdepth 1 -type f -name '*.json' 2>/dev/null | wc -l | tr -d ' '; }

# --------------------------------------------------------------------------- #
# 1. The hook scores exactly once, and only when it is entitled to.
# --------------------------------------------------------------------------- #
set_run_phase MERGED            # nothing active

files_before="$WORK/files-before"; files_after="$WORK/files-after"
proj_files >"$files_before"
out="$(run_nudge sess-A 'add a retry to the uploader')"
proj_files >"$files_after"

check "eligible prompt exits 0" "$([ "$NUDGE_RC" = 0 ] && echo 1 || echo 0)"
check "eligible prompt emits UserPromptSubmit additionalContext" \
  "$(printf '%s' "$out" | jq -e '.hookSpecificOutput.hookEventName == "UserPromptSubmit"
                                 and ((.hookSpecificOutput.additionalContext | length) > 0)' \
     >/dev/null 2>&1 && echo 1 || echo 0)"

# THE POINT OF v3.4: the hook RAN THE SCORER. A record exists, it is bound to the
# session id that arrived on stdin (not to a pid, not to an invented value), and
# the emitted line names the tier the engine returned rather than asking someone
# to go and find it out.
rec_A="$(records_for sess-A | head -1)"
check "the hook WROTE a pre-eval record" "$([ -n "$rec_A" ] && echo 1 || echo 0)"
check "the record is bound to the session id from stdin" \
  "$([ -n "$rec_A" ] && jq -e '.session_id == "sess-A"' "$rec_A" >/dev/null 2>&1 \
     && echo 1 || echo 0)"
# The binding has to be INSIDE the digest. A producer that attached session_id
# after build_record would ship a record whose self-integrity digest silently no
# longer verifies — `digest` is optional and only checked when present, so the
# damage would be invisible until something tried to trust the record.
digest_ok=0
if [ -n "$rec_A" ]; then
  python3 - "$REPO" "$rec_A" >/dev/null 2>&1 <<'PYEOF'
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location(
    "cv_tax", sys.argv[1] + "/scripts/compound-v-taxonomy.py")
tx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tx)
rec = json.load(open(sys.argv[2]))
sys.exit(0 if tx.record_digest(rec, exclude_field="digest") == rec["digest"] else 1)
PYEOF
  [ $? = 0 ] && digest_ok=1
fi
check "the record's own integrity digest covers the binding" "$digest_ok"
tier_A="$([ -n "$rec_A" ] && jq -r '.tier // ""' "$rec_A" 2>/dev/null || printf '')"
check "the emitted line names the tier the engine actually returned ($tier_A)" \
  "$([ -n "$tier_A" ] && ctx "$out" | grep -q "TIER: ${tier_A}" && echo 1 || echo 0)"
check "the emitted line says the record is UNCOMMITTED and names it" \
  "$(ctx "$out" | grep -q 'UNCOMMITTED' \
     && ctx "$out" | grep -q 'docs/superpowers/pre-eval/' && echo 1 || echo 0)"
check "the emitted line does not treat a size decision as permission" \
  "$(ctx "$out" | grep -qi 'still need a human offer' && echo 1 || echo 0)"
# THE REASON FOR THE COMMIT IS DURABILITY, NOT VISIBILITY. `epic-goal-stop.sh`
# enumerates docs/superpowers/pre-eval with `find`, never with git, so an
# uncommitted record covers the turn exactly as a committed one does. This line
# reaches a model's context every session, so a false reason here teaches every
# session to believe a written record protects nothing.
check "the emitted line does NOT claim the Stop gate cannot see an uncommitted record" \
  "$(ctx "$out" | grep -qi 'invisible[^.]*stop' && echo 0 || echo 1)"
check "the emitted line gives DURABILITY as the reason to commit" \
  "$(ctx "$out" | grep -qi 'reads records off disk' \
     && ctx "$out" | grep -qi 'DURABILITY' && echo 1 || echo 0)"

# RULE 1, mechanically: a fire writes the pre-eval artifacts and the outcome
# stream, and NOTHING else in the project.
stray=0
while IFS= read -r f; do
  [ -n "$f" ] || continue
  case "$f" in
    docs/superpowers/pre-eval/*|docs/superpowers/memory/*) : ;;
    *) stray=$((stray + 1)) ;;
  esac
done <<EOF
$(comm -13 "$files_before" "$files_after")
EOF
check "a fire writes ONLY pre-eval artifacts and the outcome stream" \
  "$([ "$stray" = 0 ] && echo 1 || echo 0)"
check "a fire appends the predicted event the breaker reads" \
  "$([ -s "$PROJ/docs/superpowers/memory/triage-outcomes.jsonl" ] && echo 1 || echo 0)"
check "the once-marker lives OUTSIDE the project (under TMPDIR)" \
  "$([ -z "$(find "$PROJ" -name 'nudged-*' 2>/dev/null)" ] \
     && [ -n "$(find "$TMPDIR" -name 'nudged-*' 2>/dev/null)" ] && echo 1 || echo 0)"

n_before="$(count_records)"
out2="$(run_nudge sess-A 'and also bump the timeout')"
check "a second prompt in the SAME session is silent (idempotent)" \
  "$([ -z "$out2" ] && [ "$NUDGE_RC" = 0 ] && echo 1 || echo 0)"
check "and it mints NO second record" \
  "$([ "$(count_records)" = "$n_before" ] && echo 1 || echo 0)"

out3="$(run_nudge sess-B 'rename the config key')"
check "a different session fires again" "$([ -n "$out3" ] && echo 1 || echo 0)"
check "and its record is bound to THAT session" \
  "$([ -n "$(records_for sess-B)" ] && echo 1 || echo 0)"

# --- 3.1.0: a QUESTION must not spend the session --------------------------- #
# The audit named this hole precisely: the hook fires at most once per session,
# so a session whose first prompt is "what does this do?" burned it and the real
# change request that followed got nothing. A short question now returns BEFORE
# the marker is written, leaving the session armed. Since v3.4 the stake is
# higher than a lost reminder: a question that got through would mint a record
# and a `predicted` event for a prompt that changes nothing.
#
# Every request text below is DELIBERATELY UNIQUE. The engine resumes an existing
# intent record by request fingerprint, so a repeated request text reuses its
# pre_eval_id and then meets write-once with a different session binding — a real
# conflict, and one that would make these assertions measure the conflict path
# instead of the thing they name.
q_out="$(run_nudge sess-Q 'what does this do?')"
check "a short question does not score" "$([ -z "$q_out" ] && echo 1 || echo 0)"
check "and it writes no record for that session" \
  "$([ -z "$(records_for sess-Q)" ] && echo 1 || echo 0)"
q_after="$(run_nudge sess-Q 'add a retry to the downloader as well')"
check "the question did NOT burn the session" \
  "$([ -n "$q_after" ] && echo 1 || echo 0)"
q_third="$(run_nudge sess-Q 'and bump the timeout too')"
check "the hook is still once-per-session after a question" \
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
check "a long prompt that merely ends in '?' is still scored" \
  "$([ -n "$lq_out" ] && echo 1 || echo 0)"
nq_out="$(run_nudge sess-NQ 'rename getUser to fetchUser')"
check "a plain change request is unaffected" \
  "$([ -n "$nq_out" ] && echo 1 || echo 0)"

# --------------------------------------------------------------------------- #
# 2. Exemptions.
# --------------------------------------------------------------------------- #
i=0
n_before="$(count_records)"
for cmd in '/v:status' '/v:triage add a retry' '/clear'; do
  i=$((i + 1))
  o="$(run_nudge "sess-slash-$i" "$cmd")"
  check "a slash command is silent: $cmd" "$([ -z "$o" ] && echo 1 || echo 0)"
done
check "and no slash command minted a record" \
  "$([ "$(count_records)" = "$n_before" ] && echo 1 || echo 0)"

# A covering record for THIS session silences it; one for another session does not.
jq -n '{id:"2099-01-01-x", session_id:"sess-D", decision:"FASTPATH_ELIGIBLE",
        tier:"DIRECT", declared_paths:["README.md"]}' >"$PREEVAL/x.json"
o="$(run_nudge sess-D 'change the readme')"
check "a pre-eval record for this session silences it" "$([ -z "$o" ] && echo 1 || echo 0)"
o="$(run_nudge sess-E 'change the readme intro')"
check "a record for ANOTHER session does not silence it" "$([ -n "$o" ] && echo 1 || echo 0)"

# A record that cannot be read is NOT an exemption (the Stop rule's stance).
printf '{ this is not json' >"$PREEVAL/broken.json"
o="$(run_nudge sess-D2 'change the readme footer')"
check "an unreadable record is not an exemption" "$([ -n "$o" ] && echo 1 || echo 0)"
rm -f "$PREEVAL/broken.json"

# An active run silences it; a finished one does not. This is the gate that keeps
# the hook from minting a record mid-pipeline, which would contaminate the very
# stream the run is being measured by.
set_run_phase DISPATCHED
n_before="$(count_records)"
o="$(run_nudge sess-F 'add a retry to the mailer')"
check "an active run silences it" "$([ -z "$o" ] && echo 1 || echo 0)"
o="$(run_nudge sess-F2 'add a retry to the scheduler')"
check "an active run silences it on EVERY prompt, not just the first" \
  "$([ -z "$o" ] && echo 1 || echo 0)"
check "and an active run mints NO record" \
  "$([ "$(count_records)" = "$n_before" ] && echo 1 || echo 0)"
set_run_phase MERGED
o="$(run_nudge sess-G 'add a retry to the indexer')"
check "a MERGED run no longer silences it" "$([ -n "$o" ] && echo 1 || echo 0)"

# Freshness comes from the RECORDED timestamp, never an mtime -- git rewrites
# mtimes on clone and branch switch, which would make every historical run in
# the repository look seconds old.
set_run_phase DISPATCHED "2020-01-01T00:00:00Z"
o="$(run_nudge sess-G2 'add a retry to the exporter')"
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
check "a non-UserPromptSubmit payload is silent (a mis-registration must not score on every tool call)" \
  "$([ -z "$o" ] && echo 1 || echo 0)"

o="$(run_nudge sess-I 'add a retry' "$OTHER")"
check "a project with no Compound V surface is silent" "$([ -z "$o" ] && echo 1 || echo 0)"

n_before="$(count_records)"
o="$(jq -n --arg c "$PROJ" '{hook_event_name:"UserPromptSubmit", cwd:$c,
                             prompt:"add a retry to the webhook"}' \
     | bash "$NUDGE" 2>/dev/null)"
check "a payload with no session_id is silent (nothing to deduplicate on, and nothing to BIND to)" \
  "$([ -z "$o" ] && [ "$(count_records)" = "$n_before" ] && echo 1 || echo 0)"

# --------------------------------------------------------------------------- #
# 3b. The engine's own kill-switch, and the engine failing.
#
# `pre_eval.enabled: false` makes the whole stage a no-op that writes nothing.
# An operator who turned the stage off must get SILENCE, not a hook narrating
# that the stage is off — and above all not a record.
# --------------------------------------------------------------------------- #
DISPROJ="$WORK/projDisabled"
DISRUN="$DISPROJ/docs/superpowers/execution/2099-01-01-off"
mkdir -p "$DISPROJ/.git" "$DISPROJ/.claude" "$DISRUN"
printf '{"pre_eval": {"enabled": false}}\n' >"$DISPROJ/.claude/compound-v.json"
# A FINISHED run, not an absent execution root: "cannot tell" is treated as
# ACTIVE, so a sandbox the resume query cannot answer for would silence the hook
# for the wrong reason and this test would pass without ever reaching the engine.
printf 'feature: off\njobs:\n  - id: task-1\n' >"$DISRUN/manifest.yaml"
jq -n --arg ts "$(now_ts)" \
  '{run_id:"2099-01-01-off", phase:"MERGED", updated_at:$ts,
    jobs:{"task-1":{status:"done"}}}' >"$DISRUN/state.json"
o="$(prompt_payload sess-OFF 'add a retry to the disabled project' "$DISPROJ" \
     | bash "$NUDGE" 2>/dev/null)"; rc=$?
check "pre_eval.enabled=false: exit 0 and no output" \
  "$([ "$rc" = 0 ] && [ -z "$o" ] && echo 1 || echo 0)"
check "pre_eval.enabled=false: NO record is written" \
  "$([ ! -d "$DISPROJ/docs/superpowers/pre-eval" ] && echo 1 || echo 0)"

# A PLANTED ENGINE FAILURE. The hook now depends on a real program with real
# dependencies; it can be absent, raise, or be killed by the registration's
# timeout. Every one of those must degrade to the REMINDER the hook used to print
# unconditionally — asking for the thing that failed — and never to silence, and
# never to a non-zero exit (which on this event REJECTS THE USER'S PROMPT).
#
# The WHOLE scripts/ tree is copied and only the engine is replaced. Copying the
# engine's neighbours out from under it would break the resume query too, the
# hook would go silent for that reason instead, and this test would report a
# green reminder path it never took.
FAKEROOT="$WORK/fakeplugin"
mkdir -p "$FAKEROOT"
cp -R "$REPO/scripts" "$FAKEROOT/scripts"
printf '#!/usr/bin/env python3\nimport sys\nsys.stderr.write("boom\\n")\nsys.exit(3)\n' \
  >"$FAKEROOT/scripts/compound-v-preeval.py"
n_before="$(count_records)"
o="$(prompt_payload sess-BOOM 'add a retry to the broken engine path' \
     | CLAUDE_PLUGIN_ROOT="$FAKEROOT" bash "$NUDGE" 2>/dev/null)"; rc=$?
check "a planted engine failure still exits 0" "$([ "$rc" = 0 ] && echo 1 || echo 0)"
check "a planted engine failure yields the REMINDER text" \
  "$(ctx "$o" | grep -q 'could not size this prompt' \
     && ctx "$o" | grep -q '/v:triage' && echo 1 || echo 0)"
check "a planted engine failure mints no record" \
  "$([ "$(count_records)" = "$n_before" ] && echo 1 || echo 0)"

# --------------------------------------------------------------------------- #
# 3c. v3.4.1 — THE HOOK FINISHES T3 ITSELF (finding 50).
#
# Until 3.4.1 a `needs_t3` request was a DEGRADE: the hook printed the reminder
# because finishing T3 needs a light-tier classify and a hook cannot run a Task.
# The premise held and the conclusion did not — a hook cannot run a Task but it
# can run a PROCESS, and `compound-v-classify-request.py --classify-headless` is
# that one-shot. What is asserted here is the whole decision table of the new
# branch, driven by a FAKE `claude` so no case spends a real model call:
#
#   enum reply      -> the engine is re-invoked with --t3-category and a record
#                      with a real tier is written
#   garbage reply   -> `unknown` is a genuine classification: FULL, WITH a record
#   a hanging fake  -> nothing was classified: the reminder, inside the budget
#   no CLI at all   -> nothing was classified: the reminder
#
# The two halves of that table are the point. A model that RAN and said it
# cannot tell is not the same event as no model having run, and collapsing them
# would either write a made-up band onto a real record or throw away a real
# answer. The argv is asserted too: no `--bare` (it skips the login as well as
# the plugins) and a `--model` that is never a haiku.
# --------------------------------------------------------------------------- #
T3PROJ="$WORK/projT3"
T3PREEVAL="$T3PROJ/docs/superpowers/pre-eval"
T3RUN="$T3PROJ/docs/superpowers/execution/2099-01-01-t3"
mkdir -p "$T3PROJ/.git" "$T3PROJ/.claude" "$T3PROJ/src" "$T3PREEVAL" "$T3RUN"
printf 'def upload(chunk):\n    return chunk\n' >"$T3PROJ/src/uploader.py"
# A FINISHED run, for the same reason 3b needs one: "cannot tell" is treated as
# ACTIVE, so a sandbox the resume query cannot answer for would silence the hook
# for the wrong reason and every assertion below would pass without firing.
printf 'feature: t3\njobs:\n  - id: task-1\n' >"$T3RUN/manifest.yaml"
jq -n --arg ts "$(now_ts)" \
  '{run_id:"2099-01-01-t3", phase:"MERGED", updated_at:$ts,
    jobs:{"task-1":{status:"done"}}}' >"$T3RUN/state.json"

# A taxonomy that has SAFETY COVERAGE (without it the scorer returns FULL before
# it ever reaches T3) but bands nothing under src/ — which is exactly the shape
# that makes the engine ask for T3.
cat >"$T3PROJ/.claude/compound-v-impact-taxonomy.yaml" <<'YAML'
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
check "T3 SANDBOX: the taxonomy the T3 cases rely on is valid" \
  "$(python3 "$REPO/scripts/compound-v-validate-taxonomy.py" \
       "$T3PROJ/.claude/compound-v-impact-taxonomy.yaml" >/dev/null 2>&1 && echo 1 || echo 0)"

FAKE_CLAUDE="$WORK/fake-claude.sh"
cat >"$FAKE_CLAUDE" <<'FAKE'
#!/usr/bin/env bash
# Stand-in for `claude -p`. Records the argv it was given (one arg per line) and
# how many bytes of stdin it could read, then answers as the case asks.
if [ -n "${FAKE_CLAUDE_ARGV:-}" ]; then printf '%s\n' "$@" >"$FAKE_CLAUDE_ARGV"; fi
if [ -n "${FAKE_CLAUDE_STDIN:-}" ]; then wc -c >"$FAKE_CLAUDE_STDIN" 2>/dev/null; fi
[ -n "${FAKE_CLAUDE_SLEEP:-}" ] && sleep "$FAKE_CLAUDE_SLEEP"
printf '%s\n' "${FAKE_CLAUDE_REPLY:-plumbing}"
FAKE
chmod +x "$FAKE_CLAUDE"

t3_records_for() {
  find "$T3PREEVAL" -maxdepth 1 -type f -name '*.json' 2>/dev/null \
    | while IFS= read -r f; do
        jq -e --arg s "$1" '(type == "object") and (.session_id == $s)' "$f" \
          >/dev/null 2>&1 && printf '%s\n' "$f"
      done
}

ARGV_LOG="$WORK/fake-claude-argv"

# --- case 1: the fake answers with an enum -> a real tier, no reminder ------- #
export CV_CLASSIFY_CLAUDE_BIN="$FAKE_CLAUDE"
export FAKE_CLAUDE_ARGV="$ARGV_LOG"
export FAKE_CLAUDE_STDIN="$WORK/fake-claude-stdin"
export FAKE_CLAUDE_REPLY="user-facing-minor"
unset FAKE_CLAUDE_SLEEP 2>/dev/null || true

o="$(run_nudge sess-T3A 'please add a retry loop to the uploader module at src/uploader.py' "$T3PROJ")"
check "T3: a needs_t3 prompt still exits 0" "$([ "$NUDGE_RC" = 0 ] && echo 1 || echo 0)"
check "T3: the hook no longer degrades to the reminder when a classifier answers" \
  "$(ctx "$o" | grep -q 'could not size this prompt' && echo 0 || echo 1)"
rec_T3A="$(t3_records_for sess-T3A | head -1)"
check "T3: the re-invocation with --t3-category WROTE a record" \
  "$([ -n "$rec_T3A" ] && echo 1 || echo 0)"
check "T3: the record records the model-derived tier (T3 in tiers_signalled)" \
  "$([ -n "$rec_T3A" ] && jq -e '(.tiers_signalled // []) | index("T3")' "$rec_T3A" \
     >/dev/null 2>&1 && echo 1 || echo 0)"
tier_T3A="$([ -n "$rec_T3A" ] && jq -r '.tier // ""' "$rec_T3A" 2>/dev/null || printf '')"
check "T3: a user-facing-minor reply lands SCOPED (the enum reached the matrix)" \
  "$([ "$tier_T3A" = "SCOPED" ] && echo 1 || echo 0)"
check "T3: the emitted line names that tier (TIER: SCOPED)" \
  "$(ctx "$o" | grep -q 'TIER: SCOPED' && echo 1 || echo 0)"

# THE ARGV. Three properties, each of which was wrong in a draft of this route.
check "T3 ARGV: the classify NEVER passes --bare (it skips the login too)" \
  "$([ -f "$ARGV_LOG" ] && grep -qx -- '--bare' "$ARGV_LOG" && echo 0 || echo 1)"
check "T3 ARGV: it is a print run with the prompt immediately after -p" \
  "$([ -f "$ARGV_LOG" ] && [ "$(head -1 "$ARGV_LOG")" = "-p" ] \
     && [ -n "$(sed -n '2p' "$ARGV_LOG")" ] && echo 1 || echo 0)"
check "T3 ARGV: it asks for text output" \
  "$([ -f "$ARGV_LOG" ] && grep -qx -- '--output-format' "$ARGV_LOG" && echo 1 || echo 0)"
check "T3 ARGV: it disables tools" \
  "$([ -f "$ARGV_LOG" ] && grep -qx -- '--tools' "$ARGV_LOG" && echo 1 || echo 0)"
t3_model="$([ -f "$ARGV_LOG" ] && awk '$0=="--model"{getline; print; exit}' "$ARGV_LOG" || printf '')"
check "T3 ARGV: the model is resolved and is NEVER a haiku (got '${t3_model}')" \
  "$([ -n "$t3_model" ] && ! printf '%s' "$t3_model" | grep -qi haiku && echo 1 || echo 0)"
check "T3: the classify ran with stdin closed (0 bytes readable)" \
  "$([ -f "$WORK/fake-claude-stdin" ] \
     && [ "$(tr -d ' \n' <"$WORK/fake-claude-stdin")" = "0" ] && echo 1 || echo 0)"

# --- case 2: garbage reply -> `unknown` is a REAL answer -> FULL, with a record #
export FAKE_CLAUDE_REPLY="Well, I would probably call this plumbing of some sort."
o="$(run_nudge sess-T3B 'please add a retry loop to the downloader module at src/uploader.py' "$T3PROJ")"
rec_T3B="$(t3_records_for sess-T3B | head -1)"
check "T3: a non-enum reply is still a classification, so a record IS written" \
  "$([ -n "$rec_T3B" ] && echo 1 || echo 0)"
check "T3: ...and it fails closed to FULL" \
  "$([ -n "$rec_T3B" ] && jq -e '.tier == "FULL"' "$rec_T3B" >/dev/null 2>&1 \
     && echo 1 || echo 0)"
check "T3: ...recorded as a T3 verdict, not as an unbanded one" \
  "$([ -n "$rec_T3B" ] && jq -e '(.tiers_signalled // []) | index("T3")' "$rec_T3B" \
     >/dev/null 2>&1 && echo 1 || echo 0)"
check "T3: ...and the model was NOT asked to route it by hand" \
  "$(ctx "$o" | grep -q 'TIER: FULL' && echo 1 || echo 0)"

# --- case 3: a hanging fake -> nothing classified -> the reminder, in budget -- #
# The cap is CV_CLASSIFY_TIMEOUT_S here so the suite does not sit for 18 s; the
# constant that ships is asserted separately below.
export FAKE_CLAUDE_REPLY="plumbing"
export FAKE_CLAUDE_SLEEP=20
export CV_CLASSIFY_TIMEOUT_S=3
t0=$(date +%s)
o="$(run_nudge sess-T3C 'please add a retry loop to the exporter module at src/uploader.py' "$T3PROJ")"
t1=$(date +%s)
check "T3: a hanging classifier still exits 0" "$([ "$NUDGE_RC" = 0 ] && echo 1 || echo 0)"
check "T3: a hanging classifier yields the REMINDER (nothing was classified)" \
  "$(ctx "$o" | grep -q 'could not size this prompt' \
     && ctx "$o" | grep -q '/v:triage' && echo 1 || echo 0)"
# A SESSION-BOUND record, not a file count: the engine writes its `.intent.json`
# and `.localization.json` working artifacts on the way to `needs_t3` and those
# are resumable-by-fingerprint scaffolding, not a verdict. What must not exist is
# a RECORD bound to this session, because that is what the Stop gate reads and
# what the outcome stream keys on.
check "T3: a hanging classifier mints NO record (no invented band)" \
  "$([ -z "$(t3_records_for sess-T3C)" ] && echo 1 || echo 0)"
check "T3: and it returned inside the budget ($((t1 - t0))s for a 3s cap)" \
  "$([ "$((t1 - t0))" -lt 20 ] && echo 1 || echo 0)"
unset FAKE_CLAUDE_SLEEP CV_CLASSIFY_TIMEOUT_S

# --- case 4: no classifier on the machine at all -> the reminder ------------- #
# An override that is set but EMPTY disables a route outright, which is how this
# asserts the no-backend degrade on a machine that really does have `claude`.
export CV_CLASSIFY_CLAUDE_BIN=""
export CV_CLASSIFY_CODEX_BIN=""
o="$(run_nudge sess-T3D 'please add a retry loop to the importer module at src/uploader.py' "$T3PROJ")"
check "T3: with no classify backend at all the hook exits 0" \
  "$([ "$NUDGE_RC" = 0 ] && echo 1 || echo 0)"
check "T3: with no classify backend at all it degrades to the reminder" \
  "$(ctx "$o" | grep -q 'could not size this prompt' && echo 1 || echo 0)"
check "T3: ...and mints no record" \
  "$([ -z "$(t3_records_for sess-T3D)" ] && echo 1 || echo 0)"
unset FAKE_CLAUDE_ARGV FAKE_CLAUDE_STDIN FAKE_CLAUDE_REPLY

# --- the contract the hook and the registration have to agree on ------------- #
check "T3: the hook calls --classify-headless (not the Task-contract modes)" \
  "$(grep -q -- '--classify-headless' "$NUDGE" && echo 1 || echo 0)"
check "T3: the hook re-enters the engine with --t3-category" \
  "$(grep -q -- '--t3-category' "$NUDGE" && echo 1 || echo 0)"
check "T3: the hook's needs_t3 branch no longer degrades unconditionally" \
  "$(grep -q 'the request needs the T3 classify step . degrading' "$NUDGE" && echo 0 || echo 1)"
check "T3: the shipped classify cap is 15 s" \
  "$(grep -q '^_CLASSIFY_TIMEOUT_S=15$' "$NUDGE" && echo 1 || echo 0)"
check "T3: hooks.json gives UserPromptSubmit the 25 s the cap plus grace needs" \
  "$(jq -e '[.hooks.UserPromptSubmit[]?.hooks[]?.timeout] == [25]' "$HOOKS_JSON" \
     >/dev/null 2>&1 && echo 1 || echo 0)"
check "T3: and ONLY that event was raised (PostCompact still bounded at 10)" \
  "$(jq -e '[.hooks.PostCompact[]?.hooks[]?.timeout] == [10]' "$HOOKS_JSON" \
     >/dev/null 2>&1 && echo 1 || echo 0)"
check "T3: the SCOPED+ tier line exists for a small edit on a sensitive path" \
  "$(grep -q 'SCOPED+' "$NUDGE" && echo 1 || echo 0)"
check "T3: the classify engine's own selftest is green" \
  "$(python3 "$REPO/scripts/compound-v-classify-request.py" --selftest >/dev/null 2>&1 \
     && echo 1 || echo 0)"

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

# THE LEDGER IS GONE (v3.4). v3.3.0 registered hooks/tool-failure-ledger.sh on
# PostToolUseFailure and this suite asserted that the file it wrote grew. Nothing
# ever READ that file — not `compound-v-classify-failure.py`, not the scorecard,
# not any command — so the only thing the suite proved was that a hook could
# append to a temp file. A mechanism with no caller is the exact defect the
# native-mechanisms pass exists to find, so the event, the registration and the
# assertions went together, and `hooks/tool-failure-ledger.sh` is deleted with
# them. What is asserted here is the REGISTRATION, not the file: an unregistered
# script is inert, while an event still pointing at a script that is not there is
# a half-removal and worse than either end state.
check "REGISTRATION: there is NO PostToolUseFailure block (the ledger had no reader)" \
  "$(jq -e '.hooks | has("PostToolUseFailure") | not' "$HOOKS_JSON" \
     >/dev/null 2>&1 && echo 1 || echo 0)"
check "REGISTRATION: nothing registers tool-failure-ledger.sh any more" \
  "$(jq -r '.hooks | to_entries[] | .value[]? | .hooks[]? | .command // empty' "$HOOKS_JSON" \
     2>/dev/null | grep -q 'tool-failure-ledger' && echo 0 || echo 1)"


# =========================================================================== #
# v3.3.0 — the PreCompact snapshot
#
# The point of this one is NOT that it runs. It is that it has a CALLER: the
# snapshot is READ BACK by hooks/postcompact-resume.sh. This file's job is to
# prove that by writing with one hook and reading with the other — never by
# comparing the two sources, which would pass even if both agreed on a path
# nobody uses.
# =========================================================================== #
PRECOMPACT="${PRECOMPACT_SRC:-$REPO/hooks/precompact-snapshot.sh}"

npc_proj="$WORK/projPC"
mkdir -p "$npc_proj/scripts" "$npc_proj/docs/superpowers/execution/2026-01-01-x"
cp "$REPO/scripts/compound-v-dashboard.py" "$npc_proj/scripts/" 2>/dev/null || true
cat >"$npc_proj/docs/superpowers/execution/2026-01-01-x/state.json" <<'JSON'
{"run_id":"2026-01-01-x","phase":"DISPATCHED","updated_at":"2026-09-02T00:00:00Z",
 "jobs":{"a":{"status":"pending"},"b":{"status":"done"}}}
JSON
# A run dir is only a run dir to the dashboard when it carries a manifest as well
# as a state file — found by probing the real scanner, not by reading it.
printf 'run_id: 2026-01-01-x\n' >"$npc_proj/docs/superpowers/execution/2026-01-01-x/manifest.yaml"

run_pc() { OUT="$(printf '%s' "$1" | bash "$PRECOMPACT" 2>/dev/null)"; RC=$?; }
pc_json() { jq -n --arg cwd "$1" --arg sid "$2" --arg ev "$3" \
  '{hook_event_name:$ev,session_id:$sid,cwd:$cwd,trigger:"auto"}'; }

run_pc "$(pc_json "$npc_proj" pc-1 PreCompact)"
check "PRECOMPACT: takes a snapshot when work is unfinished" \
  "$([ "$RC" = 0 ] && [ -n "$(find "$TMPDIR" -name 'snap-*' 2>/dev/null)" ] && echo 1 || echo 0)"
check "PRECOMPACT: never blocks compaction (no continue:false, no decision)" \
  "$(printf '%s' "$OUT" | jq -e 'has("continue") or has("decision")' >/dev/null 2>&1 \
     && echo 0 || echo 1)"
run_pc "$(pc_json "$npc_proj" pc-1 PostCompact)"
check "PRECOMPACT: ignores every event but PreCompact" \
  "$([ -z "$OUT" ] && echo 1 || echo 0)"
nopc="$WORK/projNoPC"; mkdir -p "$nopc"
run_pc "$(pc_json "$nopc" pc-2 PreCompact)"
check "PRECOMPACT: a project without Compound V gets nothing" \
  "$([ -z "$OUT" ] && echo 1 || echo 0)"

# THE CALLER. Write with PreCompact, then make the DISK disagree, then read with
# PostCompact: the reported line must be the snapshot's, not the disk's.
/usr/bin/python3 - "$npc_proj" <<'PYX'
import io, json, sys, os
p = os.path.join(sys.argv[1], "docs/superpowers/execution/2026-01-01-x/state.json")
d = json.load(io.open(p))
d["phase"] = "MERGED"
for v in d["jobs"].values():
    v["status"] = "done"
io.open(p, "w").write(json.dumps(d))
PYX
OUT="$(printf '%s' "$(jq -n --arg cwd "$npc_proj" \
  '{hook_event_name:"PostCompact",session_id:"pc-1",cwd:$cwd,trigger:"auto",compact_summary:"nothing"}')" \
  | bash "${POSTCOMPACT_SRC:-$REPO/hooks/postcompact-resume.sh}" 2>/dev/null)"
check "THE CALLER: PostCompact reports the SNAPSHOT, not the changed disk" \
  "$(printf '%s' "$OUT" | grep -q 'UNFINISHED COMPOUND V WORK' && echo 1 || echo 0)"
OUT2="$(printf '%s' "$(jq -n --arg cwd "$npc_proj" \
  '{hook_event_name:"PostCompact",session_id:"no-snap",cwd:$cwd,trigger:"auto",compact_summary:"x"}')" \
  | bash "${POSTCOMPACT_SRC:-$REPO/hooks/postcompact-resume.sh}" 2>/dev/null)"
check "THE CALLER: without a snapshot it falls back to the live query" \
  "$([ -z "$OUT2" ] && echo 1 || echo 0)"


# =========================================================================== #
# v3.3.5 — three defects a Phase-1B audit found in these hooks
# =========================================================================== #
BANNER="${BANNER_SRC:-$REPO/hooks/session-banner.sh}"
bnproj="$WORK/projBanner"; mkdir -p "$bnproj/docs/superpowers" "$WORK/nojq"
printf '#!/bin/sh\nexit 127\n' > "$WORK/nojq/jq"; chmod +x "$WORK/nojq/jq"

# jq is installed by default on neither macOS nor most Linux images, and this
# hook runs under `set -euo pipefail`: a missing jq did not degrade the banner,
# it killed it on every session start with no diagnostic.
bn_out="$(printf '{"hook_event_name":"SessionStart","cwd":"%s","session_id":"s1"}' "$bnproj" \
  | PATH="$WORK/nojq:$PATH" CLAUDE_PLUGIN_ROOT="$REPO" bash "$BANNER" 2>/dev/null)"
check "BANNER: survives with NO jq on PATH" \
  "$([ -n "$bn_out" ] && echo 1 || echo 0)"
check "BANNER: still emits valid JSON without jq" \
  "$(printf '%s' "$bn_out" | python3 -c 'import json,sys; json.load(sys.stdin)' 2>/dev/null && echo 1 || echo 0)"

# A bare top-level additionalContext is an unrecognised key and is DISCARDED;
# the runtime reads it only inside hookSpecificOutput with a hookEventName.
check "BANNER: emits the shape the runtime actually reads" \
  "$(printf '%s' "$bn_out" | python3 -c '
import json,sys
h=(json.load(sys.stdin) or {}).get("hookSpecificOutput") or {}
sys.exit(0 if h.get("hookEventName")=="SessionStart" and h.get("additionalContext") else 1)
' 2>/dev/null && echo 1 || echo 0)"
check "BANNER: Claude shape is the DEFAULT, not conditional on CLAUDE_PLUGIN_ROOT" \
  "$(printf '{"hook_event_name":"SessionStart","cwd":"%s","session_id":"s2"}' "$bnproj" \
     | PATH="$WORK/nojq:$PATH" bash "$BANNER" 2>/dev/null \
     | grep -q 'hookSpecificOutput' && echo 1 || echo 0)"

# The snapshot hook named session-banner.sh as a reader. It contains zero
# references to the snapshot; naming a reader that does not read is the same
# defect as claiming a caller that does not call.
check "SNAPSHOT: does not claim session-banner.sh reads it" \
  "$(grep -q 'session-banner.sh . can find it' "$REPO/hooks/precompact-snapshot.sh" && echo 0 || echo 1)"
check "RESUME: distinguishes a failed id query from an empty one" \
  "$(grep -q 'ids_ok' "$REPO/hooks/postcompact-resume.sh" && echo 1 || echo 0)"
check "RESUME: no longer claims the line and the ids can never disagree" \
  "$(grep -q 'can never disagree' "$REPO/hooks/postcompact-resume.sh" && echo 0 || echo 1)"

echo "-------------------------------------------"
printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" = "0" ] || exit 1
echo "OK native-points decision tables green"
