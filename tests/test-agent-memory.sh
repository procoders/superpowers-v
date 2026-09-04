#!/usr/bin/env bash
# tests/test-agent-memory.sh — native persistent subagent memory, and the lane it lives in.
#
# WHY THIS FILE EXISTS. `memory:` is a one-word frontmatter field, and every guarantee
# built on it is prose: which agents get memory, which deliberately do not, what may be
# written there, and — the part with teeth — whose lane the directory belongs to.
#
# The lane is the whole design. `.claude/agent-memory/spec-reviewer/**` is IN the review
# job's `write_allowed` and OUT of every implementer's, so the reviewer can take notes and
# an implementer that tried to plant text in those notes is denied by the lane guard and
# BLOCKED by the scope gate. That asymmetry is worth nothing if it is only asserted, so
# the second half of this file drives `scripts/compound-v-scope-check.py` against a real
# throwaway git repo and shows the verdict flipping when the glob is removed.
#
# Docs: https://code.claude.com/docs/en/sub-agents § "Enable persistent memory".

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd -P)"
PY="${CV_PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || PY=/usr/bin/python3

# `scripts/lint-frontmatter.py` is the one script here that is NOT stdlib-only: it
# imports PyYAML. CI installs it (validate.yml's tests job), but a dev machine can
# easily have two python3s where only one can `import yaml` — so resolve the linter's
# interpreter by PROBING, and say so out loud if none of them can, rather than
# reporting a green run that never executed the linter checks.
PY_YAML=""
for _cand in "$PY" python3 /usr/bin/python3 python; do
  command -v "$_cand" >/dev/null 2>&1 || continue
  if "$_cand" -B -c 'import yaml' >/dev/null 2>&1; then PY_YAML="$_cand"; break; fi
done
SCOPE="$REPO/scripts/compound-v-scope-check.py"
MEM_GLOB=".claude/agent-memory/spec-reviewer/**"
MEM_FILE=".claude/agent-memory/spec-reviewer/MEMORY.md"

TMP_EARLY="$(mktemp -d "${TMPDIR:-/tmp}/cv-agent-memory-XXXXXX")"
cleanup() { rm -rf "$TMP_EARLY"; }
trap cleanup EXIT

pass=0; fail=0
check() {
  if [ "$2" = "1" ]; then pass=$((pass+1)); echo "PASS $1"
  else fail=$((fail+1)); echo "FAIL $1"; fi
}

# `set -e` must not abort the run on the first red check, and every probe below is
# expected to fail somewhere — so each one is wrapped in an `if`, never left bare.
yes_no() { if "$@" >/dev/null 2>&1; then echo 1; else echo 0; fi; }

# --------------------------------------------------------------------------- #
# 1. The five memory-bearing agents.
# --------------------------------------------------------------------------- #
for a in spec-reviewer partition-reviewer code-archaeologist domain-expert doc-validator; do
  f="$REPO/agents/$a.md"
  check "$a exists" "$(yes_no test -f "$f")"
  # Frontmatter only: the field must be declared, not merely discussed in the body.
  fm="$(awk 'NR==1 && $0=="---" {inside=1; next} inside && $0=="---" {exit} inside' "$f")"
  check "$a declares memory: project in its frontmatter" \
    "$(printf '%s\n' "$fm" | grep -qx 'memory: project' && echo 1 || echo 0)"
  check "$a names its own memory directory in its prompt" \
    "$(yes_no grep -q "\.claude/agent-memory/$a/" "$f")"
  # The three rules that make a committed memory safe to read.
  check "$a is told never to save a secret" \
    "$(yes_no grep -qi 'never save a secret' "$f")"
  check "$a is told a remembered pattern is a lead, not a verdict" \
    "$(grep -qi 'never save a verdict' "$f" && grep -qi 're-verify it against' "$f" && echo 1 || echo 0)"
  check "$a is told memory is evidence, never instructions" \
    "$(yes_no grep -qi 'evidence, never instructions' "$f")"
  check "$a is told to consult memory BEFORE it starts" \
    "$(yes_no grep -qi 'Before you start' "$f")"
done

# --------------------------------------------------------------------------- #
# 2. The two lane-writing agents carry NO memory, and implementer says why.
# --------------------------------------------------------------------------- #
for a in implementer parallel-dispatcher; do
  f="$REPO/agents/$a.md"
  fm="$(awk 'NR==1 && $0=="---" {inside=1; next} inside && $0=="---" {exit} inside' "$f")"
  check "$a carries no memory field" \
    "$(printf '%s\n' "$fm" | grep -q '^memory:' && echo 0 || echo 1)"
done
check "implementer.md states it carries no memory, and why" \
  "$(grep -qi 'no persistent memory' "$REPO/agents/implementer.md" \
     && grep -qi 'outside your .write_allowed' "$REPO/agents/implementer.md" && echo 1 || echo 0)"

# --------------------------------------------------------------------------- #
# 3. .gitignore: `local` scope is never committed; `project` scope always is.
# --------------------------------------------------------------------------- #
check ".gitignore ignores the local memory scope" \
  "$(yes_no grep -qx '\.claude/agent-memory-local/' "$REPO/.gitignore")"
check "a local-scope memory file really is ignored" \
  "$(yes_no git -C "$REPO" check-ignore -q ".claude/agent-memory-local/spec-reviewer/MEMORY.md")"
# The project scope must stay VISIBLE: an ignored path is invisible to the scope gate's
# `git ls-files --others --exclude-standard` probe, which would blind enforcement on it.
check "the project memory scope is NOT gitignored" \
  "$(git -C "$REPO" check-ignore -q "$MEM_FILE" && echo 0 || echo 1)"

# --------------------------------------------------------------------------- #
# 4. The shipped example manifest declares the glob on its review job.
# --------------------------------------------------------------------------- #
EXAMPLE="$REPO/examples/manifest.example.yaml"
review_block() {
  awk '/^  - id: / { inblk = ($0 == "  - id: task-4-review") } inblk' "$EXAMPLE"
}
check "the example manifest has a task-4-review job" \
  "$(review_block | grep -q 'type: review' && echo 1 || echo 0)"
check "the example review job's write_allowed carries the memory glob" \
  "$(review_block | grep -qF -- "$MEM_GLOB" && echo 1 || echo 0)"
# …and PAIRS it with a real output lane. A lane made of the memory glob alone is
# refused as no_work the moment the reviewer has nothing durable to save, which
# pressures it to invent an entry. The validator says so; the example must not
# demonstrate the shape its own advisory warns about.
check "the example review job pairs the memory glob with a real output lane" \
  "$(review_block | grep -qE '^ +- "docs/.*\.md"' && echo 1 || echo 0)"

VALIDATOR="$REPO/scripts/compound-v-validate-manifest.py"
check "the manifest validator exists" "$(yes_no test -f "$VALIDATOR")"
check "the shipped example raises NO memory-only-lane advisory" \
  "$("$PY_YAML" -B "$VALIDATOR" "$EXAMPLE" 2>/dev/null \
     | grep -q '"warnings": \[\]' && echo 1 || echo 0)"

# A memory-only lane must WARN — advisory only, verdict untouched.
MEMONLY="$TMP_EARLY/memory-only.yaml"
mkdir -p "$TMP_EARLY"
"$PY_YAML" -B - "$EXAMPLE" "$MEMONLY" <<'PYEOF'
import io, re, sys
src, dst = sys.argv[1], sys.argv[2]
t = io.open(src, encoding="utf-8").read()
# Strip the review job's real output lane, leaving the memory glob alone.
t = t.replace('      - "docs/superpowers/dogfood/sequence-editor-review-1.md"\n', '')
io.open(dst, "w", encoding="utf-8").write(t)
PYEOF
"$PY_YAML" -B "$VALIDATOR" "$MEMONLY" >"$TMP_EARLY/memonly.json" 2>"$TMP_EARLY/memonly.err" || true
check "planted: dropping the review file leaves a memory-only lane that WARNS" \
  "$(grep -q 'memory-only lane' "$TMP_EARLY/memonly.json" && echo 1 || echo 0)"
check "planted: the memory-only advisory names the remedy" \
  "$(grep -q 'pair the memory glob with' "$TMP_EARLY/memonly.json" && echo 1 || echo 0)"
check "planted: the advisory does NOT change the verdict (still valid)" \
  "$(grep -q '"verdict": "valid"' "$TMP_EARLY/memonly.json" && echo 1 || echo 0)"
check "planted: the advisory does NOT change the exit code (still 0)" \
  "$(yes_no "$PY_YAML" -B "$VALIDATOR" "$MEMONLY")"
check "the advisory is echoed to stderr for a human" \
  "$(grep -q 'ADVISORY: ' "$TMP_EARLY/memonly.err" && echo 1 || echo 0)"

# --------------------------------------------------------------------------- #
# 5. The lane, proved against the real scope gate in a throwaway git repo.
# --------------------------------------------------------------------------- #
check "the scope gate script exists" "$(yes_no test -f "$SCOPE")"

TMP="$TMP_EARLY"

WORK="$TMP/repo"
mkdir -p "$WORK/src"
git -C "$WORK" init -q
git -C "$WORK" config user.email t@t.t
git -C "$WORK" config user.name t
printf 'base\n' > "$WORK/src/base.ts"
git -C "$WORK" add -A
git -C "$WORK" commit -q -m base
BASE="$(git -C "$WORK" rev-parse HEAD)"

# The reviewer does what its prompt tells it to: writes its review file, and saves one
# durable learning to its own memory directory.
REVIEW_FILE="docs/superpowers/dogfood/review-1.md"
mkdir -p "$WORK/$(dirname "$MEM_FILE")" "$WORK/$(dirname "$REVIEW_FILE")"
printf 'lead: the glob matcher keeps drifting in scripts/\n' > "$WORK/$MEM_FILE"
printf 'VERDICT APPROVED\n' > "$WORK/$REVIEW_FILE"

# Returns the gate's exit code (0 pass / 1 blocked / 2 error) without tripping `set -e`.
gate() {
  local rc=0
  "$PY" -B "$SCOPE" --repo "$WORK" --baseline "$BASE" "$@" \
    >"$TMP/out.json" 2>"$TMP/err.txt" || rc=$?
  echo "$rc"
}

# 5a. The reviewer's own declared lane — the memory write is IN it.
rc="$(gate --allow "$MEM_GLOB" --allow "$REVIEW_FILE")"
check "review lane: the reviewer's memory write PASSES (exit 0)" \
  "$([ "$rc" = "0" ] && echo 1 || echo 0)"
check "review lane: the gate reports verdict pass" \
  "$(yes_no grep -q '"verdict": "pass"' "$TMP/out.json")"
check "review lane: the memory file is in the gate's changed set" \
  "$(yes_no grep -q "$MEM_FILE" "$TMP/out.json")"

# 5b. An implementer lane — the SAME write is OUT of it and must BLOCK.
rc="$(gate --allow 'src/**')"
check "implementer lane src/**: the memory write is BLOCKED (exit 1)" \
  "$([ "$rc" = "1" ] && echo 1 || echo 0)"
check "implementer lane src/**: the gate reports verdict blocked" \
  "$(yes_no grep -q '"verdict": "blocked"' "$TMP/out.json")"
check "implementer lane src/**: the memory file is named as the violation" \
  "$("$PY" -B -c '
import json, sys
d = json.load(open(sys.argv[1]))
sys.exit(0 if sys.argv[2] in d.get("violations", []) else 1)
' "$TMP/out.json" "$MEM_FILE" && echo 1 || echo 0)"

# 5c. PLANTED VIOLATION. Drop the memory glob from the review lane and nothing else.
#     The check above must FAIL on this fixture, or it was never testing the glob.
rc="$(gate --allow "$REVIEW_FILE")"
check "planted: review lane WITHOUT the memory glob flips PASS -> BLOCKED (exit 1)" \
  "$([ "$rc" = "1" ] && echo 1 || echo 0)"
check "planted: the dropped glob's own file is the violation" \
  "$("$PY" -B -c '
import json, sys
d = json.load(open(sys.argv[1]))
sys.exit(0 if d.get("violations") == [sys.argv[2]] else 1)
' "$TMP/out.json" "$MEM_FILE" && echo 1 || echo 0)"

# --------------------------------------------------------------------------- #
# 6. The frontmatter linter enforces both halves of the rule.
# --------------------------------------------------------------------------- #
LINT="$REPO/scripts/lint-frontmatter.py"
LINTROOT="$TMP/lintroot"
check "an interpreter that can import yaml was found for the linter" \
  "$([ -n "$PY_YAML" ] && echo 1 || echo 0)"
[ -n "$PY_YAML" ] || { echo "   (no python3 on this machine can import yaml — install PyYAML)"; }
mkdir -p "$LINTROOT/agents"
plant() { # $1 = agent name, $2 = memory line (may be empty)
  {
    printf -- '---\nname: %s\ndescription: d\nmodel: opus\n' "$1"
    [ -n "$2" ] && printf '%s\n' "$2"
    printf -- '---\nbody\n'
  } > "$LINTROOT/agents/$1.md"
}
lint_out() { "$PY_YAML" -B "$LINT" "$LINTROOT" 2>&1 || true; }

plant implementer "memory: project"
check "linter REJECTS memory on implementer" \
  "$(lint_out | grep -q "must NOT carry a 'memory' field" && echo 1 || echo 0)"
rm -f "$LINTROOT/agents/implementer.md"

plant parallel-dispatcher "memory: local"
check "linter REJECTS memory on parallel-dispatcher" \
  "$(lint_out | grep -q "must NOT carry a 'memory' field" && echo 1 || echo 0)"
rm -f "$LINTROOT/agents/parallel-dispatcher.md"

plant spec-reviewer "memory: project"
check "linter ACCEPTS memory: project on a reviewer" \
  "$(yes_no "$PY_YAML" -B "$LINT" "$LINTROOT")"
plant spec-reviewer "memory: shared"
check "linter REJECTS an unrecognised memory scope" \
  "$(lint_out | grep -q 'memory must be one of' && echo 1 || echo 0)"
rm -f "$LINTROOT/agents/spec-reviewer.md"

# And the repository as it actually stands must be clean.
check "the repo's own frontmatter passes the linter" \
  "$(yes_no "$PY_YAML" -B "$LINT" "$REPO")"

echo "-------------------------------------------"
printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" = "0" ] || exit 1
echo "OK subagent memory is declared where it belongs and lands inside the right lane"
