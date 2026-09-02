#!/usr/bin/env bash
# tests/test-agent-recall.sh — every agent that should consult V-memory does.
#
# WHY THIS FILE EXISTS. V-memory shipped in v2.0 and no agent ever called it:
# recall was a command a human ran, so the code archaeologist re-read code the
# repository had already described and the domain expert re-derived conclusions
# already written into an ADR. That is the same defect this release line kept
# finding — a mechanism with no caller — one layer up, in prose instead of code.
#
# A prose instruction has no compiler, so this file is its compiler. It asserts the
# instruction is present, that it says the two things that keep recall safe, and
# that the command it names actually exists with the flags it uses.

set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd -P)"
pass=0; fail=0
check() { if [ "$2" = "1" ]; then pass=$((pass+1)); echo "PASS $1"; else fail=$((fail+1)); echo "FAIL $1"; fi; }

# The three pre-flight auditors and the two reviewers. `parallel-dispatcher` is
# deliberately absent: it executes a decided manifest and must not acquire opinions
# from prose mid-dispatch.
for a in code-archaeologist domain-expert doc-validator spec-reviewer partition-reviewer; do
  f="$REPO/agents/$a.md"
  check "$a exists" "$([ -f "$f" ] && echo 1 || echo 0)"
  check "$a is told to consult V-memory" \
    "$(grep -qi 'V-memory' "$f" && echo 1 || echo 0)"
  check "$a names a runnable recall command" \
    "$(grep -q 'compound-v-memory.py \(search\|recall-check\)' "$f" && echo 1 || echo 0)"
  check "$a says recall is NEVER a routing input" \
    "$(grep -qi 'never a routing input\|never.*routing input' "$f" && echo 1 || echo 0)"
  check "$a says a missing/empty result must not block it" \
    "$(grep -qiE 'empty result is a normal answer|never a reason to (block|withhold)' "$f" && echo 1 || echo 0)"
done

# The dispatcher must NOT have acquired one.
check "parallel-dispatcher stays out of it" \
  "$(grep -qi 'V-memory' "$REPO/agents/parallel-dispatcher.md" && echo 0 || echo 1)"

# The commands the prose names must exist with the flags it uses.
check "search --intent planning is a real flag" \
  "$(python3 "$REPO/scripts/compound-v-memory.py" search --help 2>&1 | grep -q 'intent' && echo 1 || echo 0)"
check "recall-check --files is a real flag" \
  "$(python3 "$REPO/scripts/compound-v-memory.py" recall-check --help 2>&1 | grep -q 'files' && echo 1 || echo 0)"
check "the escalation-only verdict is really called 'tighten'" \
  "$(grep -q '"tighten"' "$REPO/scripts/compound-v-memory.py" && echo 1 || echo 0)"

echo "-------------------------------------------"
printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" = "0" ] || exit 1
echo "OK every agent that should consult V-memory does"
