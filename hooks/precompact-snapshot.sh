#!/usr/bin/env bash
# Compound V — PreCompact resume snapshot (v3.3.0)
#
# WHAT THIS IS
# ------------
# `PreCompact` fires BEFORE the conversation is compacted. It is the last moment
# at which the session still knows what it was doing, and it is the only one of
# the three compaction-adjacent events that runs while that knowledge is intact:
#
#   PreCompact   <- here. Everything is still in context.
#   PostCompact  <- receives the summary, but its stdout is DISPLAY-ONLY on
#                   2.1.238 (the additionalContext injection path lists exactly
#                   SessionStart, UserPromptSubmit and UserPromptExpansion —
#                   verified by `strings` against the binary, not from docs).
#   SessionStart <- can inject context, but runs a session later.
#
# The complaint that started the 3.0 line was "Клод забывает" — the model losing
# its position across a compaction. v2.19 answered it with a SessionStart banner
# and v3.0 added a PostCompact one. Both READ state at the moment they run. This
# hook WRITES it at the moment it is still true, so what those two later read is
# a snapshot of the live session rather than a re-derivation from disk after the
# fact.
#
# WHAT IT IS NOT
# --------------
#   * It NEVER blocks compaction. The runtime supports it ("Compaction blocked by
#     PreCompact hook") and this hook must never use it: a blocked compaction on a
#     full context is a wedged session, and nothing here is worth that.
#   * It writes ONE file, into the session's own temp store, never into the
#     project. The v2.6.4 incident was Compound V's audit trail being written
#     where a worktree removal could delete it; a snapshot is not audit and has no
#     business in the repository.
#   * It re-derives NOTHING. `compound-v-dashboard.py resume` already owns what
#     an unfinished run is, how fresh it must be, and how to render one line.
#     This hook calls it and stores the answer.
#
# FIRE CONDITION (all must hold; any doubt writes nothing and stays silent)
#   1. the payload parses and is a PreCompact event
#   2. a `session_id` is present (the snapshot is keyed by it)
#   3. `cwd` resolves and the project looks Compound-V-enabled
#   4. the dashboard query succeeds and prints something
#
# COST. One bounded python call, on an event that fires at most a handful of
# times per session. Not on any per-prompt or per-tool path.
#
# OUTPUT. Status 0 always; stdout is a single JSON object with `systemMessage`
# only when a snapshot was actually taken, so a session with no unfinished work
# sees nothing.

trap 'exit 0' EXIT
set -uo pipefail

_HOOK_TAG="compound-v/precompact-snapshot"
_log() { printf '%s: %s\n' "$_HOOK_TAG" "$*" >&2; }

_store_dir() {
  local t="${TMPDIR:-/tmp}"
  while [ "${t}" != "/" ] && [ "${t%/}" != "${t}" ]; do t="${t%/}"; done
  [ -n "$t" ] || t="/tmp"
  printf '%s/compound-v-precompact' "$t"
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

# The snapshot path for one (project, session). Exported shape so the readers —
# postcompact-resume.sh and session-banner.sh — can find it without guessing.
snapshot_path() {
  local key
  key="$(_digest "${1}|${2}")" || return 1
  [ -n "$key" ] || return 1
  printf '%s/snap-%s' "$(_store_dir)" "$key"
}

hook_main() {
  trap - EXIT
  command -v jq >/dev/null 2>&1 || return 1

  local input
  input="$(cat)" || return 1
  [ -n "$input" ] || return 1

  # The parse must SUCCEED, not merely yield empty fields — the sibling
  # PostCompact hook demonstrably answered for $PWD under a live probe before
  # its own version of this check existed.
  local fields
  fields="$(printf '%s' "$input" | jq -r '
    ((.hook_event_name // "") | tostring | gsub("[^A-Za-z]"; "")),
    (((.session_id // "") | tostring) | gsub("[^A-Za-z0-9._:-]"; "")),
    (((.cwd // "") | tostring) | gsub("[\n\r]"; "")),
    (((.trigger // "") | tostring) | gsub("[^a-z]"; ""))
  ' 2>/dev/null)" || return 1
  [ -n "$fields" ] || return 1

  local ev sid cwdv trig
  {
    read -r ev
    read -r sid
    read -r cwdv
    read -r trig
  } <<EOF
${fields}
EOF

  case "${ev:-}" in
    PreCompact) : ;;
    *) _log "ignoring event=${ev:-} (this hook is PreCompact only)"; return 1 ;;
  esac
  [ -n "${sid:-}" ] || return 1
  [ -n "${cwdv:-}" ] && [ -d "$cwdv" ] || return 1
  # Key on the RESOLVED path. A trailing slash or a symlinked checkout would
  # otherwise produce a different digest than the reader computes, and the
  # snapshot would be written somewhere nobody looks — a mechanism with no
  # caller, which is the exact defect this release is about.
  local rootv
  rootv="$(cd "$cwdv" 2>/dev/null && pwd -P)" || return 1
  [ -n "$rootv" ] || return 1

  # Present-only, exactly like the dashboard: a project that never adopted
  # Compound V gets nothing written and nothing said.
  [ -d "${cwdv}/docs/superpowers" ] || [ -f "${cwdv}/.claude/compound-v.json" ] || return 1

  local py=""
  for c in python3 /usr/bin/python3; do
    command -v "$c" >/dev/null 2>&1 && { py="$c"; break; }
  done
  [ -n "$py" ] || return 1

  local dash="${cwdv}/scripts/compound-v-dashboard.py"
  if [ ! -f "$dash" ]; then
    dash="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd)/scripts/compound-v-dashboard.py"
  fi
  [ -f "$dash" ] || return 1

  # `--execution-root`, NOT an invented `--repo`. The first draft of this hook
  # passed `--repo`, argparse rejected it, the query exited non-zero and the hook
  # silently wrote nothing — caught by its own live probe before it ever shipped.
  # This project has killed an invented flag this way before (`--advisor`, v2.12).
  local line
  line="$("$py" "$dash" resume --execution-root "${cwdv}/docs/superpowers/execution" 2>/dev/null)" || return 1
  line="$(printf '%s' "$line" | sed '/^$/d')"
  [ -n "$line" ] || return 1

  local snap store
  store="$(_store_dir)"
  mkdir -p "$store" 2>/dev/null || return 1
  snap="$(snapshot_path "$rootv" "$sid")" || return 1

  # Written whole, then moved: a reader that arrives mid-write must never see a
  # half-file and believe it.
  printf '%s\n' "$line" >"${snap}.part" 2>/dev/null || return 1
  mv -f "${snap}.part" "$snap" 2>/dev/null || { rm -f "${snap}.part" 2>/dev/null; return 1; }

  jq -n --arg t "${trig:-unknown}" '{
    systemMessage: ("Compound V: unfinished work snapshotted before the " + $t +
                    " compaction — the resume banner will read it back."),
    suppressOutput: true
  }' 2>/dev/null || return 1
}

out="$(hook_main)"
rc=$?
if [ "$rc" -eq 0 ] && [ -n "${out:-}" ]; then
  printf '%s\n' "$out"
fi
exit 0
