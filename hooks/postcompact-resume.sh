#!/usr/bin/env bash
# Compound V — PostCompact resume context (Feature E3, v3.0)
#
# WHAT THIS IS
# ------------
# `PostCompact` is the precise event for "the conversation was just compacted",
# and — unlike `SessionStart` — IT RECEIVES THE SUMMARY. v2.19 put a stateful
# resume banner on `SessionStart` because that was the only event known at the
# time (docs/superpowers/architecture/native-mechanisms.md: "Сидели на
# `SessionStart`; не знали, что `PostCompact` отдаёт саммари"). This hook is
# that row closed: it reads the summary the compaction actually produced and
# says whether the unfinished work is IN it.
#
# WHAT IT REUSES, AND WHY IT REIMPLEMENTS NOTHING
# -----------------------------------------------
# `scripts/compound-v-dashboard.py resume` already owns:
#   * what counts as an unfinished run or epic (`_is_unfinished`)
#   * how fresh it has to be to still matter (72 h)
#   * the one-line rendering (`format_resume_line`)
# and — the part that must not be re-derived here — its freshness comes from the
# RECORDED timestamp, never a file mtime: git rewrites mtimes on every clone and
# branch switch, so an mtime-based age would make every historical run in the
# repository look seconds old and this hook would announce ancient work after
# every compaction. So the line below is the dashboard's line verbatim.
#
# WHAT THIS HOOK ADDS THAT THE BANNER CANNOT
# ------------------------------------------
# The summary itself. Having both the active run ids and `compact_summary`, it
# can say the one thing neither the banner nor the summary can say alone:
# whether the run survived the compaction in writing. "The summary does not
# mention run X" is a fact about this compaction, not a reconstruction from
# disk, and it is exactly the moment the position gets lost.
#
# HONESTY ABOUT WHERE THE OUTPUT LANDS — probed, not assumed.
# In the installed runtime (2.1.238) the PostCompact executor folds hook stdout
# into `userDisplayMessage` and returns nothing else; that value ends up as the
# compaction's display text. There is NO `hookSpecificOutput` variant for
# PostCompact in the runtime's output schema at all (the variants are PreToolUse,
# UserPromptSubmit, UserPromptExpansion, SessionStart, Setup, SubagentStart,
# PostToolUse, …), and the message-rendering path injects hook stdout into the
# MODEL's context for exactly three events: SessionStart, UserPromptSubmit and
# UserPromptExpansion. So:
#
#   this hook's line is shown AT THE COMPACTION BOUNDARY; it is not injected
#   into the model's context in 2.1.238.
#
# It therefore COMPLEMENTS the v2.19 `SessionStart` banner (which fires with
# source=compact and does reach the model) rather than replacing it. Nothing
# here should be described as re-injecting context. Because the output shape is
# plain display text, this hook emits PLAIN TEXT — a JSON object would be
# rendered to the user as raw JSON, and a `hookSpecificOutput` block naming an
# event the schema has no variant for is a shape the runtime rejects.
#
# FAIL-OPEN / FAIL-SILENT
#   * unparseable stdin, no jq, no interpreter, missing dashboard → say nothing
#   * nothing unfinished → say nothing (the overwhelmingly common case)
#   * every path exits 0; the `|| true` registration is the outer half
# A compaction is already a bad moment to be interrupted by a broken hook.
#
# COST. Two `compound-v-dashboard.py` invocations (the rendered line, then the
# ids behind it) plus one `jq` per id: ~147 ms measured on the development
# machine, mean of 10 runs. It runs once per compaction, not once per turn, and
# `timeout: 10` in hooks/hooks.json bounds it regardless.

# Status 0 on EVERY exit path. `hook_main` clears this trap for itself.
trap 'exit 0' EXIT

# No `set -e`: this hook must never fail closed.
set -uo pipefail

_HOOK_TAG="compound-v/postcompact-resume"

_log() { printf '%s: %s\n' "$_HOOK_TAG" "$*" >&2; }

# From the canonicalized cwd, walk UP to the nearest ancestor holding `.git`;
# fall back to the cwd itself. Bounded to 40 levels. (Duplicated from
# epic-goal-stop.sh rather than shared: a hooks/ library file is not in this
# job's lane, and a sourced file is one more thing each hook must survive the
# absence of.)
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

# Plugin root first (how the hook actually runs), then a repo-relative sibling
# (how a source checkout runs).
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

_python() {
  local py="${CV_PYTHON:-}"
  if [ -z "$py" ]; then
    py="$(command -v python3 2>/dev/null || true)"
    [ -n "$py" ] || py=/usr/bin/python3
  fi
  command -v "$py" >/dev/null 2>&1 || return 1
  printf '%s' "$py"
}

# At most this many ids are named. The dashboard already caps its own line at
# two records; this only bounds the mention scan.
_MAX_IDS=4

# --- main --------------------------------------------------------------------
# Returns 0 having printed the line on stdout, or non-zero having printed
# nothing at all.
hook_main() {
  trap - EXIT

  command -v jq >/dev/null 2>&1 || return 1

  local input
  input="$(cat)" || return 1
  [ -n "$input" ] || return 1

  # ONE jq pass for the two small fields. `compact_summary` is NOT read into a
  # shell variable — it is a whole conversation summary, and the only question
  # asked of it is "does it contain this id", which jq answers below without
  # ever moving it through the shell.
  # The parse must SUCCEED, not merely produce empty fields: stdin that is not
  # JSON at all would otherwise leave every field empty, `cwd` would fall back to
  # $PWD, and the hook would answer for whatever repository the harness happened
  # to be standing in. (Caught by a live probe, not by reasoning.)
  local fields
  fields="$(printf '%s' "$input" | jq -r '
    ((.hook_event_name // "") | tostring | gsub("[^A-Za-z]"; "")),
    (((.trigger // "") | tostring) | gsub("[^a-z]"; "")),
    (((.cwd // "") | tostring) | gsub("[\n\r]"; ""))
  ' 2>/dev/null)" || return 1
  [ -n "$fields" ] || return 1

  local ev trigger cwdv
  {
    read -r ev
    read -r trigger
    read -r cwdv
  } <<EOF
${fields}
EOF

  case "${ev:-}" in
    '' | PostCompact) : ;;
    *) _log "ignoring event=${ev} (this hook is PostCompact only)"; return 1 ;;
  esac

  local root proj
  [ -n "${cwdv:-}" ] || cwdv="$PWD"
  root="$(cd "$cwdv" 2>/dev/null && pwd -P)" || return 1
  [ -n "$root" ] || return 1
  proj="$(_project_root "$root")"
  [ -n "$proj" ] || return 1

  local xroot="${proj}/docs/superpowers/execution"
  [ -d "$xroot" ] || return 1

  local dash py
  dash="$(_locate_dashboard)" || return 1
  py="$(_python)" || return 1

  # The line, rendered by the one function that owns the vocabulary. Empty means
  # nothing is unfinished — the common case, and the hook says nothing.
  local line
  line="$(PYTHONDONTWRITEBYTECODE=1 "$py" "$dash" resume \
            --execution-root "$xroot" 2>/dev/null)" || return 1
  [ -n "$line" ] || return 1

  # The ids behind that line, from the same command's machine-readable mode, so
  # the two can never disagree about which runs are active.
  local ids
  ids="$(PYTHONDONTWRITEBYTECODE=1 "$py" "$dash" resume --json \
           --execution-root "$xroot" 2>/dev/null \
         | jq -r '.active[]? | .id // empty' 2>/dev/null \
         | head -n "$_MAX_IDS")" || ids=""

  # Which of them the compaction summary did NOT carry through.
  local id missing="" present=""
  while IFS= read -r id; do
    [ -n "$id" ] || continue
    if printf '%s' "$input" | jq -e --arg id "$id" \
         '((.compact_summary // "") | tostring | contains($id))' \
         >/dev/null 2>&1; then
      present="${present}${present:+, }${id}"
    else
      missing="${missing}${missing:+, }${id}"
    fi
  done <<EOF
${ids}
EOF

  local note
  if [ -z "$ids" ]; then
    # The line exists but the id query failed. Say only what is known.
    note="(the compaction summary was not checked for these ids — the id query did not return)"
  elif [ -n "$missing" ]; then
    note="The compaction summary does NOT mention ${missing} — this position is not in the summary, so re-read it from disk (/v:status) rather than from context before acting."
  else
    note="The compaction summary does mention ${present}; verify it against /v:status before acting on it, since a summary is a paraphrase and the run directory is the record."
  fi

  printf 'Compound V resume context after compaction (trigger=%s). %s %s\n' \
    "${trigger:-unknown}" "$line" "$note"
  return 0
}

out="$(hook_main)"
rc=$?
if [ "$rc" -eq 0 ] && [ -n "${out:-}" ]; then
  printf '%s\n' "$out"
fi
exit 0
