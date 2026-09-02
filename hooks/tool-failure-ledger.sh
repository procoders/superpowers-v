#!/usr/bin/env bash
# Compound V — PostToolUseFailure ledger (v3.3.0)
#
# WHAT THIS IS
# ------------
# `PostToolUseFailure` fires after a tool call FAILS. It is the only native event
# that sees a failure at the moment it happens, with the tool name and the input
# that produced it, attributed to the agent that made the call.
#
# Compound V already owns a failure vocabulary — `compound-v-classify-failure.py`
# maps a backend's error output onto a class, and `compound-v-failure-policy.py`
# turns a class into one action. Both of those only ever see failures an EXTERNAL
# worker script captured and reported. A `backend: claude` implementer's failed
# Bash was seen by nobody: it never reached the classifier, never reached the
# scorecard, and left no trace in the run's evidence. "Доказательство, что
# изменилось" is this plugin's product; "доказательство, что НЕ получилось" was
# missing for the majority backend.
#
# WHAT IT IS NOT
# --------------
#   * It does NOT classify, decide, retry, or block. It appends one line and
#     exits. Classification belongs to the script that already owns it, on the
#     evidence this ledger collects — a hook that started making routing
#     decisions from a single failed tool call would be inventing a policy
#     nobody wrote.
#   * It does NOT write into the project. The ledger lives in the session's temp
#     store. A failure ledger is diagnostics, not audit; the v2.6.4 incident was
#     audit written where it could be deleted, and the fix was to commit audit
#     properly, not to promote diagnostics into it.
#   * It records no tool INPUT field. Tool name, agent id, timestamp, and a
#     bounded error excerpt only.
#
#     AND THAT IS NOT THE SAME AS "NO SECRETS", which is what an earlier version of
#     this comment implied. A cross-model review called that out: tool errors
#     routinely echo the command, its arguments, a URL with a token in it, or the
#     content that was rejected. Omitting `tool_input` does not make the excerpt
#     safe — it only stops the OBVIOUS copy.
#
#     So the excerpt stays (a category with no text diagnoses nothing), and the
#     store is treated as sensitive instead of pretending it is not: `umask 077`,
#     directory 0700, files 0600, under the invoking user's own TMPDIR. Anyone
#     shipping this ledger anywhere else should read it as "may contain secrets".
#
# FIRE CONDITION (any doubt writes nothing)
#   1. the payload parses and is a PostToolUseFailure event
#   2. `cwd` resolves and the project looks Compound-V-enabled
#   3. the store is writable
#
# OUTPUT. Status 0 always, and NOTHING on stdout: a failing tool already produced
# an error the model can see, and a second voice narrating it is noise on the one
# path where the model is already dealing with a problem.

trap 'exit 0' EXIT
set -uo pipefail

# BEFORE anything is created. A ledger of error text inherits the caller's umask
# otherwise, which on a default 022 means a world-readable 0644 file of whatever
# those errors echoed.
umask 077

_HOOK_TAG="compound-v/tool-failure-ledger"
_log() { printf '%s: %s\n' "$_HOOK_TAG" "$*" >&2; }

_store_dir() {
  local t="${TMPDIR:-/tmp}"
  while [ "${t}" != "/" ] && [ "${t%/}" != "${t}" ]; do t="${t%/}"; done
  [ -n "$t" ] || t="/tmp"
  printf '%s/compound-v-failures' "$t"
}

_digest() {
  if command -v shasum >/dev/null 2>&1; then
    printf '%s' "$1" | shasum -a 256 2>/dev/null | cut -d' ' -f1
  elif command -v sha256sum >/dev/null 2>&1; then
    printf '%s' "$1" | sha256sum 2>/dev/null | cut -d' ' -f1
  else
    return 1
  fi
}

ledger_path() {
  local key
  key="$(_digest "${1}|${2}")" || return 1
  [ -n "$key" ] || return 1
  printf '%s/fail-%s.jsonl' "$(_store_dir)" "$key"
}

# A ledger that grows without bound in a temp directory is a disk leak wearing a
# diagnostics badge. 2000 lines is far more than any run produces and small
# enough to never matter.
_LEDGER_MAX_LINES=2000

hook_main() {
  trap - EXIT
  command -v jq >/dev/null 2>&1 || return 1

  local input
  input="$(cat)" || return 1
  [ -n "$input" ] || return 1

  # ONE jq pass, and the parse must SUCCEED. `error` is bounded HERE rather than
  # after the fact: a multi-megabyte stderr must never reach the shell as a
  # variable, and a newline inside it must never shift the fields below it.
  local fields
  fields="$(printf '%s' "$input" | jq -r '
    ((.hook_event_name // "") | tostring | gsub("[^A-Za-z]"; "")),
    (((.session_id // "") | tostring) | gsub("[^A-Za-z0-9._:-]"; "")),
    (((.cwd // "") | tostring) | gsub("[\n\r]"; "")),
    (((.tool_name // "") | tostring) | gsub("[^A-Za-z0-9_-]"; "")),
    (((.agent_id // "") | tostring) | gsub("[^A-Za-z0-9._:-]"; "")),
    ((((.tool_response.error // .tool_response.stderr // .error // "")
       | tostring)[0:300]) | gsub("[\n\r\t]"; " "))
  ' 2>/dev/null)" || return 1
  [ -n "$fields" ] || return 1

  local ev sid cwdv tool aid err
  {
    read -r ev
    read -r sid
    read -r cwdv
    read -r tool
    read -r aid
    read -r err
  } <<EOF
${fields}
EOF

  case "${ev:-}" in
    PostToolUseFailure) : ;;
    *) _log "ignoring event=${ev:-} (this hook is PostToolUseFailure only)"; return 1 ;;
  esac
  [ -n "${cwdv:-}" ] && [ -d "$cwdv" ] || return 1
  [ -d "${cwdv}/docs/superpowers" ] || [ -f "${cwdv}/.claude/compound-v.json" ] || return 1
  [ -n "${sid:-}" ] || return 1

  local store path
  store="$(_store_dir)"
  mkdir -p "$store" 2>/dev/null || return 1
  # Explicit, not merely umask-derived: the directory may predate this version, or
  # have been created by something with a looser umask.
  chmod 700 "$store" 2>/dev/null || true
  path="$(ledger_path "$cwdv" "$sid")" || return 1

  # `date` is the timestamp source on purpose: the hook has no other clock, and
  # an entry without one cannot be ordered against a run.
  local ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null)" || ts=""

  local line
  line="$(jq -c -n \
    --arg ts "$ts" --arg tool "${tool:-unknown}" --arg agent "${aid:-}" \
    --arg err "${err:-}" --arg sid "$sid" \
    '{ts: $ts, tool: $tool, agent_id: $agent, session_id: $sid, error: $err}' \
    2>/dev/null)" || return 1
  [ -n "$line" ] || return 1

  printf '%s\n' "$line" >>"$path" 2>/dev/null || return 1
  chmod 600 "$path" 2>/dev/null || true

  # Trim from the FRONT: the newest failures are the ones a caller wants.
  local n
  n="$(wc -l <"$path" 2>/dev/null | tr -d ' ')" || n=0
  if [ "${n:-0}" -gt "$_LEDGER_MAX_LINES" ]; then
    # Explicit if, not `A && B || C`: shellcheck 0.9 flags that shape (SC2015)
    # and it is genuinely not if-then-else — C runs when A succeeds and B fails,
    # which here would delete the trimmed file after failing to install it and
    # leave the untrimmed one in place. This repo already shipped one of these.
    if tail -n "$_LEDGER_MAX_LINES" "$path" >"${path}.trim" 2>/dev/null; then
      if ! mv -f "${path}.trim" "$path" 2>/dev/null; then
        rm -f "${path}.trim" 2>/dev/null
      fi
    else
      rm -f "${path}.trim" 2>/dev/null
    fi
  fi
  return 1   # nothing on stdout, ever
}

out="$(hook_main)"
rc=$?
if [ "$rc" -eq 0 ] && [ -n "${out:-}" ]; then
  printf '%s\n' "$out"
fi
exit 0
