#!/usr/bin/env bash
# Compound V — UserPromptSubmit triage nudge (Feature A / E3, v3.0)
#
# WHAT THIS IS
# ------------
# `UserPromptSubmit` is the native event for "a change request just arrived".
# That is the activation surface the sizing engine never had: the skill
# description that was supposed to start triage fires at the FOUR Superpowers
# phase transitions, all of which happen AFTER the moment the size of the change
# is decided — which is why a 7,883-line scorer has produced zero artifacts in
# its entire history (docs/superpowers/architecture/native-mechanisms.md).
#
# WHAT THIS IS NOT
# ----------------
# It is a NUDGE, not an invocation, and the distinction is load-bearing.
#
#   * This hook fires on EVERY prompt.
#   * `/v:triage` WRITES AND COMMITS a pre-eval record.
#
# Multiply those two facts together and an unguarded hook mints a record for
# "status?", for "what does this do?", for every mid-run check-in. Each spurious
# record lands in `docs/superpowers/memory/triage-outcomes.jsonl` (the stream
# task-2's circuit breaker computes its rolling rate from) and each one is a new
# candidate the Stop rule in `hooks/epic-goal-stop.sh` will consider when it asks
# which record covers this diff. So the rule here is absolute:
#
#   THIS HOOK NEVER WRITES A RECORD, NEVER COMMITS, AND NEVER RUNS /v:triage.
#   It prints at most one line of advice and gets out of the way.
#
# The mechanical closures stay exactly where the spec put them:
#   * `compound-v-validate-manifest.py --require-triage`, passed by `/v:dispatch`
#     in every mode — a manifest without a well-formed `triage` block fails.
#   * the triage rule inside `hooks/epic-goal-stop.sh` — at turn end, blocking,
#     off by default under `enforcement.triage_gate`.
# This hook is the reminder in front of both. It cannot make triage happen, and
# nothing here should be described as enforcement.
#
# FIRE CONDITION (all must hold; any doubt stays silent)
# ------------------------------------------------------
#   1. the payload parses and is a UserPromptSubmit event
#   2. the prompt does not begin with `/` (a slash command is an invocation, not
#      a change request — and `/v:triage` itself is one)
#   2b. the prompt is not a SHORT QUESTION (<=200 chars ending in `?`). A question
#      is not a change request, and spending the session's one nudge on it is the
#      hole the audit named. Skipping here leaves the session ARMED.
#   3. a `session_id` is present (without it there is nothing to deduplicate on,
#      and a nudge on every prompt is worse than no nudge)
#   4. the project looks Compound-V-enabled: `docs/superpowers/` or
#      `.claude/compound-v.json` exists. Present-only, like the dashboard
#   5. this session has not been nudged before (temp-dir marker)
#   6. NO covering triage record: no `docs/superpowers/pre-eval/*.json` carries
#      this `session_id`
#   7. NO active run: `compound-v-dashboard.py resume` prints nothing
#
# WHY 6 AND 7 ARE THE WHOLE DESIGN. Firing during a run is not merely noisy —
# it points a mid-pipeline agent at the one command that would contaminate the
# outcome stream the run is being measured by. Firing when a record already
# exists asks for a second record for work that is already sized.
#
# CANNOT-TELL IS TREATED AS "ACTIVE". If `compound-v-dashboard.py` or a Python
# interpreter cannot be found, or the resume query fails, condition 7 cannot be
# ASSERTED — so the hook stays silent rather than nudging on a guess. The cost
# is a silently inert nudge on a broken install; the alternative is nudging in
# the middle of every run on a machine where the check does not work.
#
# WHAT "COVERING" MEANS HERE, AND WHERE IT IS WEAKER THAN THE STOP RULE.
# At prompt-submit time there is no diff yet, so "covering" can only mean "a
# record exists for this session" — it cannot mean "and its declared_paths
# contain the changed files", which is what `_covered_by_records` in
# `epic-goal-stop.sh` checks at turn end when a diff exists. The consequence,
# stated rather than hidden: triage the README, then ask for an unrelated change
# in the same session, and this hook stays quiet. The Stop rule is what catches
# that, by path coverage, with a diff in hand. The two are deliberately not the
# same check; this one is first contact, that one is the audit.
#
# ONCE PER SESSION. The marker makes this idempotent in the sense that matters:
# a second prompt does not produce a second nudge. The cost, stated: a session
# whose first prompt is a question consumes the nudge, and the change request at
# prompt 20 gets no line. The Stop rule and `--require-triage` still stand
# behind it. A per-prompt nudge was rejected — a reminder that arrives every
# single turn is one the reader learns to skip, and it would cost ~150 ms of
# subprocesses on every prompt forever.
#
# NO CONFIG KEY, ON PURPOSE. `enforcement.*` in `.claude/compound-v.json` is
# documented (commands/v-init.md:619) as the map of *blocking Stop-hook* gates,
# every one defaulting OFF. This hook blocks nothing, so it does not belong
# there, and inventing an `enforcement.triage_nudge` that no shipped document
# declares would add exactly the kind of undeclared key this release exists to
# stop. It behaves like the plugin's two other reminder hooks
# (`brainstorm-trigger0-nudge.sh`, `plan-saved-nudge.sh`): always eligible,
# never blocking, disabled by disabling the hook.
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
# OUTPUT. `hookSpecificOutput.additionalContext` — verified against the runtime:
# UserPromptSubmit is one of the three events whose additionalContext is
# injected into the model's context (with SessionStart and UserPromptExpansion).
#
# COST, measured on the development machine (macOS, /usr/bin/python3, mean of
# 10 runs against this repository):
#   early exit (slash command, short question, or marker set) ~9 ms
#   full eligibility path (records scan + resume query)     ~89 ms
# The full path runs at most once per session — except while a run is active,
# when no marker is written and conditions 6-7 are re-evaluated on each prompt.
# That is deliberate: a run that ends mid-session should not permanently
# suppress the nudge, and ~89 ms is a fair price for not being wrong about it.

# Mechanism (b), first half: status 0 on EVERY exit path. `hook_main` clears
# this trap for itself so its own return code still reaches the caller.
trap 'exit 0' EXIT

# No `set -e`: this hook must never fail closed.
set -uo pipefail

_HOOK_TAG="compound-v/triage-prompt-nudge"

_log() { printf '%s: %s\n' "$_HOOK_TAG" "$*" >&2; }

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

# The read-only dashboard owns the definition of "unfinished run" (v2.19), and
# its freshness comes from the RECORDED timestamp, never a file mtime — git
# rewrites mtimes on clone and branch switch, which would make every historical
# run in the repo look seconds old. Plugin root first (how the hook runs), then
# a repo-relative sibling (how a source checkout runs).
_locate_dashboard() {
  local c
  if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ]; then
    c="${CLAUDE_PLUGIN_ROOT}/scripts/compound-v-dashboard.py"
    [ -f "$c" ] && { printf '%s' "$c"; return 0; }
  fi
  c="$(dirname "$0")/../scripts/compound-v-dashboard.py"
  [ -f "$c" ] && { printf '%s' "$c"; return 0; }
  return 1
}

# Records cap. Beyond this the scan is skipped rather than run unbounded; the
# failure direction is a nudge that should have stayed quiet, never a missed
# blocking decision — this hook makes none.
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
  # error exits non-zero here and the nudge proceeds.
  jq -e -s --arg sid "$sid" \
    'any(.[]?; (type == "object")
                and (((.session_id // "") | tostring) == $sid))' \
    "$@" >/dev/null 2>&1
}

# 0 when a Compound V run or epic is still unfinished.
_has_active_run() {
  local proj="$1" dash py line
  dash="$(_locate_dashboard)" || return 0   # cannot tell ⇒ treat as ACTIVE
  py="${CV_PYTHON:-}"
  if [ -z "$py" ]; then
    py="$(command -v python3 2>/dev/null || true)"
    [ -n "$py" ] || py=/usr/bin/python3
  fi
  command -v "$py" >/dev/null 2>&1 || return 0
  # Importing must not leave __pycache__/*.pyc next to the scripts: those are
  # untracked files a scope gate would union into a job's changed set.
  line="$(PYTHONDONTWRITEBYTECODE=1 "$py" "$dash" resume \
            --execution-root "${proj}/docs/superpowers/execution" 2>/dev/null)" \
    || return 0                              # cannot tell ⇒ treat as ACTIVE
  [ -n "$line" ]
}

# --- main --------------------------------------------------------------------
# Returns 0 having printed the nudge on stdout, or non-zero having printed
# nothing at all.
hook_main() {
  trap - EXIT

  command -v jq >/dev/null 2>&1 || return 1

  local input
  input="$(cat)" || return 1
  [ -n "$input" ] || return 1

  # ONE jq pass. `slash` is the first character of the prompt reduced to `/` or
  # nothing, so a multi-line prompt cannot shift the fields below it.
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

  # A mis-registration must not nudge on every tool call.
  case "${ev:-}" in
    '' | UserPromptSubmit) : ;;
    *) _log "ignoring event=${ev} (this hook is UserPromptSubmit only)"; return 1 ;;
  esac

  # A slash command is an invocation, not a change request — `/v:triage`,
  # `/v:status` and `/clear` all arrive here.
  [ -z "${slash:-}" ] || return 1

  # A SHORT QUESTION IS NOT A CHANGE REQUEST, AND MUST NOT SPEND THE NUDGE.
  #
  # The nudge is once per session, and the audit named the hole precisely: a
  # session whose first prompt is "what does this do?" burns the reminder on a
  # question and the real change request that follows gets nothing. Returning
  # here — BEFORE the marker is written and before the ~89 ms eligibility path —
  # leaves the session armed and costs the ~9 ms early exit.
  #
  # The test is deliberately narrow, because the general problem (is this a
  # change request?) is not decidable in a hook: a prompt of at most 200
  # characters that ENDS IN A QUESTION MARK. Nothing else is treated as a
  # question. "Rename getUser to fetchUser, ok?" is 33 characters and ends in
  # `?` and will be skipped — that is the deliberate direction of the error: a
  # missed nudge costs a reminder, a spent one costs the session's only reminder.
  # A long prompt that happens to end in `?` is a description with a question
  # attached, and still nudges.
  if [ "${question:-}" = "q" ]; then
    return 1
  fi

  # No session id ⇒ nothing to deduplicate on ⇒ stay silent.
  [ -n "${sid:-}" ] || return 1

  local root proj
  [ -n "${cwdv:-}" ] || cwdv="$PWD"
  root="$(cd "$cwdv" 2>/dev/null && pwd -P)" || return 1
  [ -n "$root" ] || return 1
  proj="$(_project_root "$root")"
  [ -n "$proj" ] || return 1

  # Present-only: never nag inside a repository that does not use Compound V.
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

  # Mid-pipeline ⇒ the correction here would be the wrong one, and a record
  # minted now would contaminate the stream the run is measured by.
  if _has_active_run "$proj"; then
    _log "a run or epic is still unfinished (or could not be checked) — silent"
    return 1
  fi

  # Marker BEFORE the nudge, and a marker we cannot write means we say nothing:
  # a reminder we cannot bound to once is one we do not give.
  mkdir -p "$store" 2>/dev/null || return 1
  : >"$marker" 2>/dev/null || return 1

  _log "nudging session ${sid} (no covering record, no active run)"

  local msg
  msg="💉 Compound V — no triage record covers this session and no run is active. \
IF this prompt is a change request (not a question, a status check, or work an \
existing record already covers), size it first: run /v:triage <what the change \
is>. It classifies the change, writes and COMMITS the pre-eval record, and \
prints the tier — DIRECT (implement in place, run the floor, commit), SCOPED \
(manifest + run dir + scope gate + one combined review pass) or FULL (the whole \
pipeline). That committed record is what /v:dispatch's --require-triage and the \
Stop-time triage gate both look for. If this prompt is NOT a change request, \
ignore this line and do not mint a record for it — a record per question is how \
the outcome stream stops meaning anything. This is a reminder, not enforcement: \
it fires once per session, and it never writes or commits anything itself."

  if [ -n "${CURSOR_PLUGIN_ROOT:-}" ]; then
    jq -n --arg ctx "$msg" '{additional_context: $ctx}' 2>/dev/null || return 1
  elif [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -z "${COPILOT_CLI:-}" ]; then
    jq -n --arg ctx "$msg" \
      '{hookSpecificOutput: {hookEventName: "UserPromptSubmit", additionalContext: $ctx}}' \
      2>/dev/null || return 1
  else
    jq -n --arg ctx "$msg" '{additionalContext: $ctx}' 2>/dev/null || return 1
  fi
  return 0
}

out="$(hook_main)"
rc=$?
if [ "$rc" -eq 0 ] && [ -n "${out:-}" ]; then
  printf '%s\n' "$out"
fi
exit 0
