#!/usr/bin/env bash
# tests/hooks/test-skills.sh — the four cycle skills and the five agents carry the
# hooks the CLI and the hooks rely on (plan Task 9, Step 1).
set -uo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd -P)"
pass=0; fail=0
check() { if [ "$2" = 1 ]; then pass=$((pass + 1)); echo "PASS $1"; else fail=$((fail + 1)); echo "FAIL $1"; fi; }
has()   { grep -qF -- "$2" "$REPO/$1" 2>/dev/null && echo 1 || echo 0; }
field() { awk 'NR==1&&/^---$/{f=1;next} f&&/^---$/{exit} f' "$REPO/$1" 2>/dev/null | grep -q "^$2:" && echo 1 || echo 0; }

for s in brainstorm plan build verify; do
  f="skills/$s/SKILL.md"
  check "$f exists" "$([ -f "$REPO/$f" ] && echo 1 || echo 0)"
  check "$f has name" "$(field "$f" name)"
  check "$f has description" "$(field "$f" description)"
  check "$f is at most 150 lines" "$([ -f "$REPO/$f" ] && [ "$(wc -l <"$REPO/$f")" -le 150 ] && echo 1 || echo 0)"
done

check "brainstorm mentions territory.md" "$(has skills/brainstorm/SKILL.md territory.md)"
check "brainstorm mentions run start"    "$(has skills/brainstorm/SKILL.md 'run start')"
check "brainstorm mentions how deep"     "$(has skills/brainstorm/SKILL.md 'how deep')"
check "brainstorm territory.md exists"   "$([ -f "$REPO/skills/brainstorm/territory.md" ] && echo 1 || echo 0)"
check "plan mentions compound-v-plan"    "$(has skills/plan/SKILL.md compound-v-plan)"
check "plan mentions ## Acceptance"      "$(has skills/plan/SKILL.md '## Acceptance')"
check "plan checklists.md exists"        "$([ -f "$REPO/skills/plan/checklists.md" ] && echo 1 || echo 0)"
check "verify mentions review record"    "$(has skills/verify/SKILL.md 'review record')"
check "verify mentions waive live"       "$(has skills/verify/SKILL.md 'waive live')"
check "verify mentions status"           "$(has skills/verify/SKILL.md 'status')"

for s in init onboard; do
  f="skills/$s/SKILL.md"
  check "$f has name and description" "$( [ "$(field "$f" name)$(field "$f" description)" = 11 ] && echo 1 || echo 0)"
  check "$f is at most 150 lines" "$([ -f "$REPO/$f" ] && [ "$(wc -l <"$REPO/$f")" -le 150 ] && echo 1 || echo 0)"
done
check "init writes worktree.baseRef head"   "$(has skills/init/SKILL.md '"baseRef": "head"')"
check "init writes the Edit deny rule"      "$(has skills/init/SKILL.md 'Edit(/docs/compound-v/runs/**)')"
check "init writes no Write() path rule"    "$(grep -q '"Write(' "$REPO/skills/init/SKILL.md" && echo 0 || echo 1)"
check "init warns about the codex stop-review gate" "$(has skills/init/SKILL.md stopReviewGate)"
check "init offers to disable Superpowers"  "$(has skills/init/SKILL.md 'superpowers@claude-plugins-official": false')"
check "pr-review points at docs/compound-v/specs" "$(has skills/pr-review/SKILL.md docs/compound-v/specs)"

for a in v-memory code-archaeologist doc-validator domain-expert reviewer; do
  check "agents/$a.md exists" "$([ -f "$REPO/agents/$a.md" ] && echo 1 || echo 0)"
done

check "lint-frontmatter selftest passes" \
  "$(python3 "$REPO/scripts/lint-frontmatter.py" --selftest >/dev/null 2>&1 && echo 1 || echo 0)"
check "lint-frontmatter passes on the plugin" \
  "$(cd "$REPO" && python3 scripts/lint-frontmatter.py . >/dev/null 2>&1 && echo 1 || echo 0)"

# Only the read-only v-memory agent may name Haiku.
haiku="$(cd "$REPO" && grep -ril haiku agents skills | sort | tr '\n' ' ')"
check "only agents/v-memory.md names haiku (found: ${haiku:-none})" \
  "$([ "$haiku" = "agents/v-memory.md " ] && echo 1 || echo 0)"

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" = 0 ]
