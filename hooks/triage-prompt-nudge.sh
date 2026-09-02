#!/usr/bin/env bash
# Compound V — UserPromptSubmit triage hook (v3.4)
#
# WHAT THIS IS
# ------------
# `UserPromptSubmit` is the native event for "a change request just arrived".
# That is the activation surface the sizing engine never had: the skill
# description that was supposed to start triage fires at the FOUR Superpowers
# phase transitions, all of which happen AFTER the moment the size of the change
# is decided — which is why a 7,883-line scorer produced zero artifacts in its
# entire history (docs/superpowers/architecture/native-mechanisms.md).
#
# WHAT CHANGED IN v3.4, AND WHY
# -----------------------------
# This hook used to print a REMINDER: a line asking the model to run `/v:triage`
# itself. That is prose enforcement wearing a hook's clothes. A reminder is
# skippable by construction, and the whole point of the native-mechanism pass is
# that the mechanism runs whether or not anybody remembered. So the hook now
# RUNS THE SCORER:
#
#     scripts/compound-v-preeval.py triage --request-env … --session-id …
#
# One subcommand, shared verbatim with `commands/v-triage.md` step T2 (see
# `triage_request`'s docstring, which names both callers). The engine scores the
# request, binds the record to THIS session id, writes it, and reports the tier;
# the hook prints the tier and the next step as `additionalContext`.
#
# THE COST OF MECHANIZING IT, STATED RATHER THAN HIDDEN
# ----------------------------------------------------
# A hook fires on every prompt, and this one now WRITES: a pre-eval record plus
# one `predicted` event on `docs/superpowers/memory/triage-outcomes.jsonl`, the
# stream the miscalibration circuit breaker computes its rolling rate from. A
# record minted for something that was not a change request is real pollution of
# a real safety input. It is not free, and the eligibility gates below are what
# keep the bill small rather than an argument that there is no bill:
#
#   * ONCE PER SESSION (a temp-dir marker) — so a long working session mints one
#     record, not forty.
#   * NOT A SLASH COMMAND — `/v:status`, `/clear` and `/v:triage` itself are
#     invocations, not change requests.
#   * NOT A SHORT QUESTION — `<=200` chars ending in `?`.
#   * NO ACTIVE RUN — mid-pipeline, the change is already sized and a fresh
#     record would contaminate the stream the run is measured by.
#   * NO COVERING RECORD for this session already.
#
# The engine's own `pre_eval.enabled: false` kill-switch is honoured at the far
# end: it makes the whole stage a no-op that writes nothing, and this hook then
# says nothing at all. An operator who turned the stage off gets silence, not a
# hook narrating that the stage is off.
#
# WHAT IT STILL IS NOT
# --------------------
# It does not COMMIT. The engine never runs git (v2.6.4 discipline: the
# orchestrator commits), and a hook that ran `git commit` on the user's behalf
# mid-prompt would be a far worse idea than the reminder it replaced. So the
# record it writes is UNCOMMITTED, and the emitted context says so and says whose
# job the commit is.
#
# THE REASON FOR THE COMMIT IS DURABILITY, NOT VISIBILITY — say it precisely,
# because this hook's message reaches a model's context every session and the
# wrong reason teaches the wrong model. The Stop-time triage gate reads records
# OFF DISK (`hooks/epic-goal-stop.sh` enumerates `docs/superpowers/pre-eval`
# with `find`, never with git), so an uncommitted record covers a turn exactly
# as a committed one does. What the commit buys is survival: an uncommitted
# record fails `compound-v-validate-manifest.py --require-triage` on ANOTHER
# clone or worktree, and `git worktree remove` deletes it outright (the v2.6.4
# data-loss shape). That is why the instruction to commit is in the message
# rather than assumed — see `skills/compound-v/phase-preeval.md`, which carries
# the same wording.
#
# It also does not ENFORCE. Nothing here blocks. The mechanical closures stay
# where the spec put them: `compound-v-validate-manifest.py --require-triage`,
# passed by `/v:dispatch` in every mode, and the triage rule inside
# `hooks/epic-goal-stop.sh`. This hook is what makes sure a record EXISTS for
# those two to find.
#
# FIRE CONDITION (all must hold; any doubt stays silent)
# ------------------------------------------------------
#   1. the payload parses and is a UserPromptSubmit event
#   2. the prompt does not begin with `/`
#   2b. the prompt is not a SHORT QUESTION (<=200 chars ending in `?`). Skipping
#      here happens BEFORE the marker is written, so the session stays ARMED.
#   3. a `session_id` is present — without it there is nothing to deduplicate on
#      AND nothing to bind the record to, and a record bound to null covers
#      nothing at the Stop gate. Both halves say the same thing: stay silent.
#   4. the project looks Compound-V-enabled: `docs/superpowers/` or
#      `.claude/compound-v.json` exists. Present-only, like the dashboard
#   5. this session has not been handled before (temp-dir marker)
#   6. NO covering triage record: no `docs/superpowers/pre-eval/*.json` carries
#      this `session_id`
#   7. NO active run: `compound-v-dashboard.py resume` prints nothing
#
# CANNOT-TELL IS TREATED AS "ACTIVE". If `compound-v-dashboard.py` or a Python
# interpreter cannot be found, or the resume query fails, condition 7 cannot be
# ASSERTED — so the hook stays silent rather than scoring on a guess.
#
# WHAT "COVERING" MEANS HERE, AND WHERE IT IS WEAKER THAN THE STOP RULE.
# At prompt-submit time there is no diff yet, so "covering" can only mean "a
# record exists for this session" — it cannot mean "and its declared_paths
# contain the changed files", which is what `_covered_by_records` in
# `epic-goal-stop.sh` checks at turn end when a diff exists. The consequence,
# stated rather than hidden: triage the README, then ask for an unrelated change
# in the same session, and this hook stays quiet. The Stop rule is what catches
# that, by path coverage, with a diff in hand.
#
# ONCE PER SESSION. A second prompt does not produce a second record. The cost,
# stated: the change request at prompt 20 of a session that opened with a
# statement gets no record from here, and `/v:triage` is still the way to size
# it. A per-prompt score was rejected outright — it is the pollution above,
# multiplied by every turn.
#
# TWO GATES, ON PURPOSE (spec WS2, AMENDED 2026-09-02). The spec first said the
# temp-dir marker was to be retired and "the record itself is the marker"
# (`_has_session_record`). It is not, and the amendment records why: the record
# only exists AFTER the engine returns. A crashed, killed or timed-out engine
# would leave the session still armed, and the next prompt would mint a second
# record for the same session — the exact per-turn pollution the once-rule
# exists to prevent, arriving through the failure path instead of the happy one.
# So the marker is written BEFORE the engine runs and both gates stand:
# `_has_session_record` answers "is this session already sized", the marker
# answers "has this session already been ATTEMPTED". The observable difference
# the amendment accepts: a session whose first scoring failed is spent, and only
# `/v:triage` can recover it. That is the fail-closed direction — one attempt
# per session, whatever the outcome.
#
# FAIL-OPEN CONTRACT — and here it is sharper than for a Stop hook.
# Probed in the installed runtime (2.1.238): UserPromptSubmit is in the
# blocking-capable event set, and `exit 2` REJECTS THE USER'S PROMPT. A parse
# error in this file is `exit 2` from bash. So both halves of the contract are
# mandatory:
#   (a) the `|| true` suffix in hooks/hooks.json — the only thing that survives
#       a parse error ABOVE the trap line, which never installs the trap
#   (b) the unconditional `trap 'exit 0' EXIT` below, plus withholding stdout
#       unless hook_main returned 0 — a half-written JSON object on stdout is
#       injected into the model's context verbatim
#
# AND A THIRD FAILURE MODE THE REMINDER VERSION DID NOT HAVE: the engine itself.
# It is a real program with real dependencies, and it can be absent, raise, or
# be too slow. Every one of those falls back to the REMINDER TEXT — the line the
# hook used to print unconditionally — which asks the model to run `/v:triage`.
# Degrading from "sized for you" to "please size it" is the right direction; the
# wrong one is a hook that says nothing when the mechanism it replaced would at
# least have spoken.
#
# OUTPUT. `hookSpecificOutput.additionalContext` — verified against the runtime:
# UserPromptSubmit is one of the three events whose additionalContext is
# injected into the model's context (with SessionStart and UserPromptExpansion).
#
# COST. The early exits (slash command, short question, or marker set) are ~9 ms.
# The eligibility path adds a records scan and a resume query (~89 ms), and the
# engine adds a bounded read-only localization pass on top — the dominant term,
# and the reason the registration carries `timeout: 10`. A run over that budget
# is killed by the harness and the prompt proceeds with no context line; the
# write-once artifacts a killed run left behind are resumable by request
# fingerprint, so the next `/v:triage` on the same text continues rather than
# re-mints. The whole path runs at most once per session — except while a run is
# active, when no marker is written and conditions 6-7 are re-evaluated on each
# prompt, so that a run ending mid-session does not permanently disarm the hook.

# Mechanism (b), first half: status 0 on EVERY exit path. `hook_main` clears
# this trap for itself so its own return code still reaches the caller.
trap 'exit 0' EXIT

# No `set -e`: this hook must never fail closed.
set -uo pipefail

_HOOK_TAG="compound-v/triage-prompt-nudge"

_log() { printf '%s: %s\n' "$_HOOK_TAG" "$*" >&2; }

# The request text is capped before it reaches the engine. A prompt is arbitrary
# user input and the scorer only needs enough of it to localize; an unbounded one
# would be carried through an environment variable, a slug and a fingerprint for
# no extra signal.
_REQUEST_MAX_CHARS=4000

# --- store -------------------------------------------------------------------
# Its OWN directory, not the Stop hook's: a temp sweep of one must not re-arm
# the other, and the two markers answer different questions.
_store_dir() {
  local t="${TMPDIR:-/tmp}"
  while [ "${t}" != "/" ] && [ "${t%/}" != "${t}" ]; do t="${t%/}"; done
  [ -n "$t" ] || t="/tmp"
  printf '%s/compound-v-triage-nudge' "$t"
}

# sha256 of "$1". No digest tool ⇒ we cannot key the store ⇒ stay silent.
# (Duplicated from epic-goal-stop.sh rather than shared: a hooks/ library file
# is not in this job's lane, and four lines of digest is a cheaper duplication
# than a sourced file two hooks would both have to survive the absence of.)
_digest() {
  if command -v shasum >/dev/null 2>&1; then
    printf '%s' "$1" | shasum -a 256 2>/dev/null | cut -d' ' -f1
  elif command -v sha256sum >/dev/null 2>&1; then
    printf '%s' "$1" | sha256sum 2>/dev/null | cut -d' ' -f1
  elif command -v openssl >/dev/null 2>&1; then
    printf '%s' "$1" | openssl dgst -sha256 2>/dev/null | awk '{print $NF}'
  else
    return 1
  fi
}

# From the canonicalized cwd, walk UP to the nearest ancestor holding `.git`;
# fall back to the cwd itself. Bounded to 40 levels.
_project_root() {
  local d="$1" i=0
  while [ "$i" -lt 40 ]; do
    [ -e "$d/.git" ] && { printf '%s' "$d"; return 0; }
    [ "$d" = "/" ] && break
    d="$(dirname "$d")" || break
    [ -n "$d" ] || break
    i=$((i + 1))
  done
  printf '%s' "$1"
}

# Plugin root first (how the hook runs), then a repo-relative sibling (how a
# source checkout runs). Both the dashboard and the engine live in `scripts/`.
_locate_script() {
  local c
  if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ]; then
    c="${CLAUDE_PLUGIN_ROOT}/scripts/$1"
    [ -f "$c" ] && { printf '%s' "$c"; return 0; }
  fi
  c="$(dirname "$0")/../scripts/$1"
  [ -f "$c" ] && { printf '%s' "$c"; return 0; }
  return 1
}

_python() {
  local py="${CV_PYTHON:-}"
  if [ -z "$py" ]; then
    py="$(command -v python3 2>/dev/null || true)"
    [ -n "$py" ] || py=/usr/bin/python3
  fi
  command -v "$py" >/dev/null 2>&1 || return 1
  printf '%s' "$py"
}

# Records cap. Beyond this the scan is skipped rather than run unbounded.
_MAX_RECORDS=500

# 0 when some pre-eval record belongs to this session.
_has_session_record() {
  local pdir="$1" sid="$2" files
  [ -d "$pdir" ] || return 1
  files="$(find "$pdir" -maxdepth 1 -type f -name '*.json' 2>/dev/null \
           | head -n "$_MAX_RECORDS")" || files=""
  [ -n "$files" ] || return 1
  local oldifs="$IFS"
  IFS=$'\n'
  # shellcheck disable=SC2086  # deliberate word-split on newline only.
  set -- $files
  IFS="$oldifs"
  # A record we cannot read is NOT an exemption (the Stop rule's stance): a jq
  # error exits non-zero here and the hook proceeds.
  jq -e -s --arg sid "$sid" \
    'any(.[]?; (type == "object")
                and (((.session_id // "") | tostring) == $sid))' \
    "$@" >/dev/null 2>&1
}

# 0 when a Compound V run or epic is still unfinished.
#
# The read-only dashboard owns the definition of "unfinished run" (v2.19), and
# its freshness comes from the RECORDED timestamp, never a file mtime — git
# rewrites mtimes on clone and branch switch, which would make every historical
# run in the repo look seconds old.
_has_active_run() {
  local proj="$1" dash py line
  dash="$(_locate_script compound-v-dashboard.py)" || return 0  # cannot tell ⇒ ACTIVE
  py="$(_python)" || return 0                                   # cannot tell ⇒ ACTIVE
  # Importing must not leave __pycache__/*.pyc next to the scripts: those are
  # untracked files a scope gate would union into a job's changed set.
  line="$(PYTHONDONTWRITEBYTECODE=1 "$py" "$dash" resume \
            --execution-root "${proj}/docs/superpowers/execution" 2>/dev/null)" \
    || return 0                                                 # cannot tell ⇒ ACTIVE
  [ -n "$line" ]
}

# --- the scorer --------------------------------------------------------------
# Prints the engine's JSON on stdout, or returns non-zero having printed nothing.
# `CV_TRIAGE_REQUEST` is how the prompt travels: `--request-env` exists precisely
# so arbitrary user text never has to survive argv quoting or show up in `ps`.
_run_engine() {
  local proj="$1" sid="$2" request="$3" engine py base out
  engine="$(_locate_script compound-v-preeval.py)" || return 1
  py="$(_python)" || return 1
  # The engine never runs git, by design — so HEAD is an input, supplied here.
  # Absent (not a repo, no commits yet) binds null rather than an invented value.
  base="$(git -C "$proj" rev-parse HEAD 2>/dev/null)" || base=""
  if [ -n "$base" ]; then
    out="$(CV_TRIAGE_REQUEST="$request" PYTHONDONTWRITEBYTECODE=1 \
           "$py" "$engine" triage --request-env CV_TRIAGE_REQUEST \
           --repo "$proj" --session-id "$sid" --base-commit "$base" --json \
           2>/dev/null)" || return 1
  else
    out="$(CV_TRIAGE_REQUEST="$request" PYTHONDONTWRITEBYTECODE=1 \
           "$py" "$engine" triage --request-env CV_TRIAGE_REQUEST \
           --repo "$proj" --session-id "$sid" --json 2>/dev/null)" || return 1
  fi
  [ -n "$out" ] || return 1
  printf '%s' "$out" | jq -e 'type == "object"' >/dev/null 2>&1 || return 1
  printf '%s' "$out"
}

# The line this hook used to print unconditionally. It is now the DEGRADED path:
# the engine could not run, or could not band the request without a model call
# that a hook cannot make. It asks for exactly the thing that failed.
_reminder_text() {
  printf '%s' "💉 Compound V — the triage engine could not size this prompt here, so \
this prompt has NO triage record. IF this prompt is a change request (not a question, a status \
check, or work an existing record already covers), size it first: run /v:triage <what \
the change is>. It classifies the change, writes and COMMITS the pre-eval record, and \
prints the tier — DIRECT (implement in place, run the floor, commit) or SCOPED \
(manifest + run dir + scope gate + one combined review pass) or FULL (the whole \
pipeline). The Stop-time triage gate looks for that record ON DISK, committed or not; \
committing it is what makes it survive — /v:dispatch's --require-triage on another \
clone or worktree, and \`git worktree remove\`. If this prompt is NOT a change request, ignore \
this line and do not mint a record for it — a record per question is how the outcome \
stream stops meaning anything."
}

_emit() {
  local msg="$1"
  if [ -n "${CURSOR_PLUGIN_ROOT:-}" ]; then
    jq -n --arg ctx "$msg" '{additional_context: $ctx}' 2>/dev/null || return 1
  elif [ -n "${COPILOT_CLI:-}" ]; then
    jq -n --arg ctx "$msg" '{additionalContext: $ctx}' 2>/dev/null || return 1
  else
    jq -n --arg ctx "$msg" \
      '{hookSpecificOutput: {hookEventName: "UserPromptSubmit", additionalContext: $ctx}}' \
      2>/dev/null || return 1
  fi
  return 0
}

# --- main --------------------------------------------------------------------
# Returns 0 having printed the hook's JSON on stdout, or non-zero having printed
# nothing at all.
hook_main() {
  trap - EXIT

  command -v jq >/dev/null 2>&1 || return 1

  local input
  input="$(cat)" || return 1
  [ -n "$input" ] || return 1

  # ONE jq pass for the DECISION fields. `slash` is the first character of the
  # prompt reduced to `/` or nothing, so a multi-line prompt cannot shift the
  # fields below it.
  #
  # The parse must SUCCEED, not merely produce empty fields: stdin that is not
  # JSON at all would otherwise leave every field empty and `cwd` would fall back
  # to $PWD, answering for whatever repository the harness happened to be
  # standing in. (The sibling PostCompact hook demonstrably did exactly that
  # under a live probe before this check existed.)
  local fields
  fields="$(printf '%s' "$input" | jq -r '
    ((.hook_event_name // "") | tostring | gsub("[^A-Za-z]"; "")),
    (((.prompt // "") | tostring)[0:1] | gsub("[^/]"; "")),
    (((.session_id // "") | tostring) | gsub("[^A-Za-z0-9._:-]"; "")),
    (((.cwd // "") | tostring) | gsub("[\n\r]"; "")),
    (((.prompt // "") | tostring) | ascii_downcase
       | gsub("^[[:space:]]+"; "") | gsub("[[:space:]]+$"; "")
       | if (length > 0 and length <= 200 and (.[-1:] == "?"))
         then "q" else "" end)
  ' 2>/dev/null)" || return 1
  [ -n "$fields" ] || return 1

  local ev slash sid cwdv question
  {
    read -r ev
    read -r slash
    read -r sid
    read -r cwdv
    read -r question
  } <<EOF
${fields}
EOF

  # A mis-registration must not score on every tool call.
  case "${ev:-}" in
    '' | UserPromptSubmit) : ;;
    *) _log "ignoring event=${ev} (this hook is UserPromptSubmit only)"; return 1 ;;
  esac

  # A slash command is an invocation, not a change request — `/v:triage`,
  # `/v:status` and `/clear` all arrive here.
  [ -z "${slash:-}" ] || return 1

  # A SHORT QUESTION IS NOT A CHANGE REQUEST, AND MUST NOT SPEND THE SESSION.
  #
  # Returning here — BEFORE the marker is written and before the engine runs —
  # leaves the session armed and costs the ~9 ms early exit.
  #
  # The test is deliberately narrow, because the general problem (is this a
  # change request?) is not decidable in a hook: a prompt of at most 200
  # characters that ENDS IN A QUESTION MARK. Nothing else is treated as a
  # question. "Rename getUser to fetchUser, ok?" is 33 characters and ends in
  # `?` and will be skipped — that is the deliberate direction of the error: a
  # missed record costs a reminder that /v:triage exists, a spurious one costs a
  # row on the stream the circuit breaker reads. A long prompt that happens to
  # end in `?` is a description with a question attached, and is still scored.
  if [ "${question:-}" = "q" ]; then
    return 1
  fi

  # No session id ⇒ nothing to deduplicate on AND nothing to bind to ⇒ silent.
  [ -n "${sid:-}" ] || return 1

  local root proj
  [ -n "${cwdv:-}" ] || cwdv="$PWD"
  root="$(cd "$cwdv" 2>/dev/null && pwd -P)" || return 1
  [ -n "$root" ] || return 1
  proj="$(_project_root "$root")"
  [ -n "$proj" ] || return 1

  # Present-only: never write into a repository that does not use Compound V.
  [ -d "${proj}/docs/superpowers" ] || [ -f "${proj}/.claude/compound-v.json" ] || return 1

  local store key marker
  store="$(_store_dir)"
  key="$(_digest "${proj}|${sid}")" || return 1
  [ -n "$key" ] || return 1
  marker="${store}/nudged-${key}"
  [ -e "$marker" ] && return 1

  # Covering record for THIS session ⇒ the size question was already asked.
  if _has_session_record "${proj}/docs/superpowers/pre-eval" "$sid"; then
    _log "session ${sid} already has a pre-eval record — silent"
    return 1
  fi

  # Mid-pipeline ⇒ the change is already sized, and a record minted now would
  # contaminate the stream the run is measured by.
  if _has_active_run "$proj"; then
    _log "a run or epic is still unfinished (or could not be checked) — silent"
    return 1
  fi

  # MARKER BEFORE THE ENGINE, and a marker we cannot write means we do nothing.
  # The order is load-bearing now that the hook writes: a crashed or timed-out
  # engine must not leave the session armed to mint a SECOND record on the next
  # prompt. Once per session means once, whatever the outcome.
  mkdir -p "$store" 2>/dev/null || return 1
  : >"$marker" 2>/dev/null || return 1

  # The RAW request, capped. Kept out of the decision-fields pass above because
  # that one deliberately strips and folds every field it reads.
  local request
  request="$(printf '%s' "$input" \
             | jq -r --argjson n "$_REQUEST_MAX_CHARS" \
                 '((.prompt // "") | tostring)[0:$n]' 2>/dev/null)" || request=""
  if [ -z "${request// /}" ]; then
    return 1
  fi

  _log "scoring session ${sid} (no covering record, no active run)"

  local res
  res="$(_run_engine "$proj" "$sid" "$request")" || {
    _log "the triage engine did not run — degrading to the reminder"
    _emit "$(_reminder_text)"
    return $?
  }

  local disabled needs_t3 tier decision pid record_ref declared
  disabled="$(printf '%s' "$res" | jq -r '.disabled // false' 2>/dev/null)"
  needs_t3="$(printf '%s' "$res" | jq -r '.needs_t3 // false' 2>/dev/null)"

  # `pre_eval.enabled: false` — the operator turned the stage off. The engine
  # wrote nothing, and narrating that the stage is off is not a service.
  if [ "$disabled" = "true" ]; then
    _log "pre_eval.enabled is false — the stage is a no-op, silent"
    return 1
  fi

  # The deterministic layers could not band the request; finishing needs a light
  # classify Task, and a hook cannot run one. Hand it to the command that can.
  if [ "$needs_t3" = "true" ]; then
    _log "the request needs the T3 classify step — degrading to the reminder"
    _emit "$(_reminder_text)"
    return $?
  fi

  tier="$(printf '%s' "$res" | jq -r '.tier // "unknown"' 2>/dev/null)"
  decision="$(printf '%s' "$res" | jq -r '.decision // "unknown"' 2>/dev/null)"
  pid="$(printf '%s' "$res" | jq -r '.pre_eval_id // ""' 2>/dev/null)"
  record_ref="$(printf '%s' "$res" | jq -r '.record_ref // ""' 2>/dev/null)"
  declared="$(printf '%s' "$res" \
              | jq -r '(.declared_paths // []) | join(", ")' 2>/dev/null)"
  [ -n "$record_ref" ] || {
    _log "the engine reported no record — degrading to the reminder"
    _emit "$(_reminder_text)"
    return $?
  }

  local next
  case "$tier" in
    DIRECT)
      next="DIRECT — implement it here, run the test floor, and commit it as an \
ORDINARY commit alongside the record. /v:triage --land is the UNATTENDED landing \
gate and is not what an attended change needs."
      ;;
    SCOPED)
      next="SCOPED — offer it to the user; on acceptance run /v:orchestrate (manifest, \
run dir, scope gate, floor, one combined SPEC+QUALITY review; recon and the three \
pre-flights are skipped), then /v:dispatch."
      ;;
    FULL)
      next="FULL — offer it to the user; on acceptance run the unchanged pipeline \
(recon, the three pre-flights, brainstorm, plan, /v:orchestrate, /v:dispatch)."
      ;;
    *)
      next="The engine reported tier ${tier}, which this hook does not recognise. \
Read ${record_ref} and route it by hand."
      ;;
  esac

  local msg
  msg="💉 Compound V sized this prompt before you read it. TIER: ${tier} (decision \
${decision}, pre_eval_id ${pid}). ${next} The record ${record_ref} is WRITTEN AND \
UNCOMMITTED — this hook never runs git, so committing it is yours to do and it is not \
optional. The Stop-time triage gate reads records off disk, so this one already covers \
this turn; the commit is for DURABILITY — an uncommitted record fails /v:dispatch's \
--require-triage on another clone or worktree, and \`git worktree remove\` deletes it. \
Commit it with the \
localization artifact, the taxonomy snapshot and \
docs/superpowers/memory/triage-outcomes.jsonl. Its declared_paths are: ${declared:-none} \
— if the work you are about to do is somewhere else, that record does not cover it and \
the Stop-time gate will say so. If this prompt was NOT a change request, leave the \
record uncommitted and say so rather than building on it. This is a size decision, not \
permission: SCOPED and FULL still need a human offer and acceptance."

  _emit "$msg"
  return $?
}

out="$(hook_main)"
rc=$?
if [ "$rc" -eq 0 ] && [ -n "${out:-}" ]; then
  printf '%s\n' "$out"
fi
exit 0
