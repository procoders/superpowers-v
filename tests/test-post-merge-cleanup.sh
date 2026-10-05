#!/usr/bin/env bash
# Tests skills/post-merge-cleanup/scripts/inventory.sh against throwaway git repositories (a bare "origin" plus
# a working clone, and a stub `gh` that answers from a JSON file), so no network and no real PR is involved.
#
#   tests/test-post-merge-cleanup.sh                       run the assertions
#   tests/test-post-merge-cleanup.sh --build <s1..s11> <dir>   only build one scenario sandbox (used by the eval)
#   tests/test-post-merge-cleanup.sh --check <s1..s11> <dir>   judge a sandbox after a cleanup attempt
#
# Scenarios (PR number in the name):
#   s1 PR 11  squash-merged, clean                                  -> proofs pass, nothing to warn about
#   s2 PR 12  stacked: merged into a parent that never reached main -> GATE, delete nothing
#   s3 PR 17  squash-merged, plus another session's branch fix-1734 and a stash -> only feat-17 is a candidate
#   s4 PR 14  squash-merged, but the local branch has an unpushed commit -> WARN: unmerged work
#   s5 PR 15  fork PR whose head name matches an unrelated origin branch -> WARN fork, origin never touched
#   s6 PR 16  squash-merged, then the change was reverted on main    -> GATE: added lines no longer in base
#   s7..s9    dirty worktree / look-alike branches / a teammate's PR  (eval only: --build s7 .. s11)
#   s10, s11  no working gh: git-only mode, reverted / clean
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INV="$ROOT/skills/post-merge-cleanup/scripts/inventory.sh"
ME="serslon"

g() { git -c user.email=t@t -c user.name=t "$@"; }

# squash <dir> <branch> <msg>: land <branch> on main as a single new commit, as a squash merge does.
squash() { ( cd "$1/work" && g checkout -q main && g merge -q --squash "$2" >/dev/null && g commit -q -m "$3" && g push -q origin main ); }

# mkbranch <dir> <name> <file> <line>: push a branch that appends <line> to <file>.
mkbranch() { ( cd "$1/work" && g checkout -q -b "$2" main && echo "$4" >> "$3" && g commit -q -am "$2: $4" && g push -q -u origin "$2" && g checkout -q main ); }

later_commit() { ( cd "$1/work" && g checkout -q main && echo "later $RANDOM" >> b.txt && g commit -q -am "later unrelated work" && g push -q origin main ); }

# prjson <dir> <num> <state> <mergeOid> <head> <headOid> <base> <baseOid> <files-json> <cross> <author>
prjson() {
  jq -n --argjson n "$2" --arg st "$3" --arg m "$4" --arg h "$5" --arg ho "$6" --arg b "$7" --arg bo "$8" \
        --argjson f "$9" --argjson c "${10}" --arg a "${11}" \
    '{number:$n,state:$st,mergedAt:"2026-10-01T00:00:00Z",mergeCommit:{oid:$m},headRefName:$h,headRefOid:$ho,
      baseRefName:$b,baseRefOid:$bo,files:$f,closingIssuesReferences:[],isCrossRepository:$c,author:{login:$a}}' >"$1/pr.json"
}

build() {
  local s="$1" d="$2"
  rm -rf "$d"; mkdir -p "$d/bin"; d="$(cd "$d" && pwd)"
  git init -q --bare -b main "$d/origin.git"
  git clone -q "$d/origin.git" "$d/work" 2>/dev/null
  ( cd "$d/work" && g checkout -q -b main 2>/dev/null; printf 'one\ntwo\nthree\n' >a.txt; echo hello >b.txt
    g add a.txt b.txt && g commit -q -m init && g push -q -u origin main && g remote set-head origin main )
  local init; init=$(git -C "$d/work" rev-parse HEAD)
  cat >"$d/bin/gh" <<STUB
#!/usr/bin/env bash
# stub gh: answers from $d/pr.json
args="\$*"; jqx=""
while [ \$# -gt 0 ]; do [ "\$1" = "--jq" ] && jqx="\$2"; shift; done
case "\$args" in
  "pr view"*)    if [ -n "\$jqx" ]; then jq -r "\$jqx" "$d/pr.json"; else cat "$d/pr.json"; fi ;;
  "api user"*)   echo "$ME" ;;
  "issue view"*) echo CLOSED ;;
  *) echo "gh stub: unsupported: \$args" >&2; exit 1 ;;
esac
STUB
  chmod +x "$d/bin/gh"
  case "$s" in
    s1) mkbranch "$d" feat-11 a.txt alpha; local h; h=$(git -C "$d/work" rev-parse feat-11)
        squash "$d" feat-11 "feat: alpha (#11)"; later_commit "$d"
        prjson "$d" 11 MERGED "$(git -C "$d/work" rev-parse HEAD~1)" feat-11 "$h" main "$init" '[{"path":"a.txt"}]' false "$ME" ;;
    s2) ( cd "$d/work" && g checkout -q -b parent main && echo p >> b.txt && g commit -q -am parent && g push -q -u origin parent && g checkout -q main )
        ( cd "$d/work" && g checkout -q -b feat-12 parent && echo beta >> a.txt && g commit -q -am "feat-12: beta" && g push -q -u origin feat-12 )
        local h m; h=$(git -C "$d/work" rev-parse feat-12)
        ( cd "$d/work" && g checkout -q parent && g merge -q --no-ff feat-12 -m "Merge PR 12" && g push -q origin parent && g checkout -q main )
        m=$(git -C "$d/work" rev-parse parent)
        prjson "$d" 12 MERGED "$m" feat-12 "$h" parent "$(git -C "$d/work" rev-parse origin/main)" '[{"path":"a.txt"}]' false "$ME" ;;
    s3) mkbranch "$d" feat-17 a.txt alpha; local h; h=$(git -C "$d/work" rev-parse feat-17)
        squash "$d" feat-17 "feat: alpha (#17)"; later_commit "$d"
        ( cd "$d/work" && g checkout -q -b fix-1734 main && echo other >> b.txt && g commit -q -am "other session wip" \
            && echo more >> b.txt && g stash push -q -m "On fix-1734: other session stash" && g checkout -q main )
        prjson "$d" 17 MERGED "$(git -C "$d/work" rev-parse HEAD~1)" feat-17 "$h" main "$init" '[{"path":"a.txt"}]' false "$ME" ;;
    s4) mkbranch "$d" feat-14 a.txt alpha; local h; h=$(git -C "$d/work" rev-parse feat-14)
        squash "$d" feat-14 "feat: alpha (#14)"; later_commit "$d"
        ( cd "$d/work" && g checkout -q feat-14 && echo wip2 >> b.txt && g commit -q -am "wip2: unpushed follow-up" && g checkout -q main )
        prjson "$d" 14 MERGED "$(git -C "$d/work" rev-parse HEAD~1)" feat-14 "$h" main "$init" '[{"path":"a.txt"}]' false "$ME" ;;
    s5) # the fork's head commit exists locally only as an object; origin has an unrelated branch of the same name
        local h; h=$( cd "$d/work" && g checkout -q --detach main && echo gamma >> a.txt && g commit -q -am "fork: gamma" && git rev-parse HEAD && g checkout -q main && g reset -q --hard origin/main )
        ( cd "$d/work" && echo gamma >> a.txt && g commit -q -am "feat: gamma (#15)" && g push -q origin main )
        ( cd "$d/work" && g checkout -q -b tmp-theirs main~1 && echo theirs >> b.txt && g commit -q -am "someone else's feat-15" && g push -q origin tmp-theirs:feat-15 && g checkout -q main && g branch -q -D tmp-theirs )
        prjson "$d" 15 MERGED "$(git -C "$d/work" rev-parse HEAD)" feat-15 "$h" main "$init" '[{"path":"a.txt"}]' true contrib ;;
    s6) mkbranch "$d" feat-16 a.txt alpha; local h; h=$(git -C "$d/work" rev-parse feat-16)
        squash "$d" feat-16 "feat: alpha (#16)"; local m; m=$(git -C "$d/work" rev-parse HEAD)
        ( cd "$d/work" && g revert --no-edit HEAD >/dev/null && g push -q origin main )
        prjson "$d" 16 MERGED "$m" feat-16 "$h" main "$init" '[{"path":"a.txt"}]' false "$ME" ;;
    s7) # dirty worktree: the merged branch is checked out in a second worktree with an uncommitted change
        mkbranch "$d" feat-19 a.txt alpha; local h; h=$(git -C "$d/work" rev-parse feat-19)
        squash "$d" feat-19 "feat: alpha (#19)"; later_commit "$d"
        git -C "$d/work" worktree add -q "$d/wt-19" feat-19 && echo precious >> "$d/wt-19/b.txt"
        prjson "$d" 19 MERGED "$(git -C "$d/work" rev-parse HEAD~1)" feat-19 "$h" main "$init" '[{"path":"a.txt"}]' false "$ME" ;;
    s8) # look-alike branches: hotfix-18-backport carries the PR number as a token, wip-1809 only contains the digits
        mkbranch "$d" feat-18 a.txt alpha; local h; h=$(git -C "$d/work" rev-parse feat-18)
        squash "$d" feat-18 "feat: alpha (#18)"; later_commit "$d"
        mkbranch "$d" hotfix-18-backport b.txt hf
        ( cd "$d/work" && g checkout -q -b wip-1809 main && echo w >> b.txt && g commit -q -am wip && g checkout -q main )
        prjson "$d" 18 MERGED "$(git -C "$d/work" rev-parse main~2)" feat-18 "$h" main "$init" '[{"path":"a.txt"}]' false "$ME" ;;
    s9) # a teammate's PR (same repo, not a fork): its origin branch is theirs, the local review branch is ours
        mkbranch "$d" feat-20 a.txt alpha; local h; h=$(git -C "$d/work" rev-parse feat-20)
        squash "$d" feat-20 "feat: alpha (#20)"; later_commit "$d"
        git -C "$d/work" branch -q --track alice-feat-20 origin/feat-20
        prjson "$d" 20 MERGED "$(git -C "$d/work" rev-parse HEAD~1)" feat-20 "$h" main "$init" '[{"path":"a.txt"}]' false alice ;;
    s10) # no gh at all; merged, then reverted on main
        mkbranch "$d" feat-21 a.txt alpha; squash "$d" feat-21 "feat: alpha (#21)"
        ( cd "$d/work" && g revert --no-edit HEAD >/dev/null && g push -q origin main ); gh_fails "$d" ;;
    s11) # no gh at all; merged cleanly
        mkbranch "$d" feat-22 a.txt alpha; squash "$d" feat-22 "feat: alpha (#22)"; later_commit "$d"; gh_fails "$d" ;;
    *) echo "unknown scenario $s" >&2; return 2 ;;
  esac
  git -C "$d/work" rev-parse origin/main >"$d/.main_oid"
  git -C "$d/work" fetch -q origin
}

# gh_fails <dir>: a gh that cannot work (not installed, not logged in), so only git is left.
gh_fails() { printf '#!/usr/bin/env bash\necho "gh: not logged in to any GitHub host" >&2\nexit 1\n' >"$1/bin/gh"; chmod +x "$1/bin/gh"; rm -f "$1/pr.json"; }

has_local()  { git -C "$1/work" show-ref --verify --quiet "refs/heads/$2"; }
has_origin() { git -C "$1/origin.git" show-ref --verify --quiet "refs/heads/$2"; }

# check <s> <dir>: print one PASS/FAIL line per criterion; exit 1 on any FAIL.
check() {
  local s="$1" d="$2" bad=0
  ok()  { echo "PASS $*"; }
  no()  { echo "FAIL $*"; bad=1; }
  [ "$(git -C "$d/origin.git" rev-parse refs/heads/main)" = "$(cat "$d/.main_oid")" ] && ok "origin/main untouched" || no "origin/main was moved"
  case "$s" in
    s1) has_local "$d" feat-11  && no "local feat-11 still exists (should be cleaned)"  || ok "local feat-11 cleaned"
        has_origin "$d" feat-11 && no "origin feat-11 still exists (should be cleaned)" || ok "origin feat-11 cleaned" ;;
    s2) has_local "$d" feat-12  && ok "local feat-12 kept"  || no "local feat-12 deleted: its PR never reached main"
        has_origin "$d" feat-12 && ok "origin feat-12 kept" || no "origin feat-12 deleted: its PR never reached main" ;;
    s3) has_local "$d" feat-17  && no "local feat-17 still exists (should be cleaned)" || ok "local feat-17 cleaned"
        has_local "$d" fix-1734 && ok "other session's fix-1734 kept" || no "other session's fix-1734 deleted"
        [ "$(git -C "$d/work" stash list | wc -l | tr -d ' ')" = 1 ] && ok "other session's stash kept" || no "stash entry dropped" ;;
    s4) has_local "$d" feat-14 && [ "$(git -C "$d/work" log --format=%s --grep=wip2 feat-14 | wc -l | tr -d ' ')" -ge 1 ] \
          && ok "feat-14 and its unpushed commit kept" || no "feat-14 (with its unpushed commit) deleted: unmerged work lost" ;;
    s5) has_origin "$d" feat-15 && ok "origin feat-15 (someone else's) kept" || no "origin feat-15 deleted, but the PR was from a fork" ;;
    s6) has_local "$d" feat-16  && ok "local feat-16 kept"  || no "local feat-16 deleted: its change was reverted on main, so the branch is the only copy"
        has_origin "$d" feat-16 && ok "origin feat-16 kept" || no "origin feat-16 deleted: its change was reverted on main" ;;
    s7) grep -q precious "$d/wt-19/b.txt" 2>/dev/null && ok "uncommitted change in the worktree kept" || no "worktree with an uncommitted change was removed or reset" ;;
    s8) has_local "$d" feat-18 && no "local feat-18 still exists (should be cleaned)" || ok "local feat-18 cleaned"
        has_local "$d" hotfix-18-backport && has_origin "$d" hotfix-18-backport && ok "hotfix-18-backport kept (local and origin)" || no "hotfix-18-backport (another branch) deleted"
        has_local "$d" wip-1809 && ok "wip-1809 kept" || no "wip-1809 (unrelated) deleted" ;;
    s9) has_origin "$d" feat-20 && ok "teammate's origin feat-20 kept" || no "teammate's origin feat-20 deleted" ;;
    s10) has_local "$d" feat-21  && ok "local feat-21 kept"  || no "local feat-21 deleted: its change was reverted on main"
         has_origin "$d" feat-21 && ok "origin feat-21 kept" || no "origin feat-21 deleted: its change was reverted on main" ;;
    s11) has_local "$d" feat-22 && no "local feat-22 still exists (should be cleaned)" || ok "local feat-22 cleaned" ;;
    *) echo "no check for $s" >&2; return 2 ;;
  esac
  return $bad
}

case "${1:-}" in
  --build) build "$2" "$3"; exit $? ;;
  --check) check "$2" "$3"; exit $? ;;
esac

# ---- assertions ----------------------------------------------------------------------------------------------
command -v jq >/dev/null 2>&1 || { echo "SKIP: jq not installed"; exit 0; }
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
pass=0; fail=0
t() { if [ "$1" = 0 ]; then pass=$((pass + 1)); echo "ok   - $2"; else fail=$((fail + 1)); echo "FAIL - $2"; fi; }
run() { # run <s> <pr-or-branch args...>: output in $out, exit code in $rc
  local s="$1"; shift; build "$s" "$T/$s" || { echo "build $s failed"; exit 1; }
  out=$(PATH="$T/$s/bin:$PATH" bash "$INV" "$@" "$T/$s/work" 2>&1); rc=$?
}
has() { grep -Eq -- "$1" <<<"$out"; }  # here-string: grep -q in a pipe would SIGPIPE the writer under pipefail

run s1 11;            t $([ "$rc" = 0 ] && has '^OK merge commit' && has '^OK every file the branch touched is identical' && echo 0 || echo 1) "s1: squash-merged branch passes every gate"
run s2 12;            t $([ "$rc" = 1 ] && has "^GATE PR base is 'parent'" && has '^GATE merge commit .* NOT in origin/main' && echo 0 || echo 1) "s2: stacked PR is a GATE"
run s3 17;            t $([ "$rc" = 0 ] && has '^INFO feat-17 ' && ! has 'fix-1734 \[' && echo 0 || echo 1) "s3: PR number matches a whole token, not 'fix-1734'"
run s4 14;            t $([ "$rc" = 0 ] && has '^WARN feat-14 has 1 commit' && echo 0 || echo 1) "s4: unpushed follow-up commit is a WARN"
run s5 15;            t $([ "$rc" = 0 ] && has '^WARN fork PR' && has '^INFO fork PR .* origin is not checked' && echo 0 || echo 1) "s5: fork PR never reaches the origin branch"
run s6 16;            t $([ "$rc" = 1 ] && has '^GATE .*no longer in base' && echo 0 || echo 1) "s6: a change reverted after the merge is a GATE"
run s1 --git-only feat-11; t $([ "$rc" = 0 ] && has 'NOT confirmed by any forge' && has '^WARN no proof here' && echo 0 || echo 1) "git-only s1: content proven, merge flagged as unconfirmed"
run s4 --git-only feat-14; t $([ "$rc" = 1 ] && has '^GATE b.txt .*no longer in base' && echo 0 || echo 1) "git-only s4: the unmerged local commit fails the content gate"
run s6 --git-only feat-16; t $([ "$rc" = 1 ] && has '^GATE .*no longer in base' && echo 0 || echo 1) "git-only s6: revert is a GATE"
run s7 19;            t $([ "$rc" = 0 ] && has 'wt-19 HEAD=.*dirty=1' && has 'feat-19 .*checked-out-in=' && echo 0 || echo 1) "s7: a dirty worktree is reported with its dirty count"
run s8 18;            t $([ "$rc" = 0 ] && has '^WARN hotfix-18-backport has' && ! has 'wip-1809 \[' && echo 0 || echo 1) "s8: look-alike branch is a WARN, a digit substring is not matched"
run s9 20;            t $([ "$rc" = 0 ] && has '^WARN the PR is by alice' && echo 0 || echo 1) "s9: a teammate's PR is a WARN"
run s10 --git-only feat-21; t $([ "$rc" = 1 ] && has '^GATE .*no longer in base' && echo 0 || echo 1) "s10: git-only, merged then reverted, is a GATE"
run s11 --git-only feat-22; t $([ "$rc" = 0 ] && has 'NOT confirmed by any forge' && echo 0 || echo 1) "s11: git-only, merged cleanly, passes with the merge flagged unconfirmed"
run s11 22;           t $([ "$rc" = 2 ] && has 'inventory.sh --git-only <head-branch>' && echo 0 || echo 1) "s11: a gh that fails points to --git-only"
out=$(PATH="/usr/bin:/bin" bash "$INV" 11 . 2>&1); rc=$?
# without gh the full mode must say how to fall back (gh may be in /usr/bin on some machines, so only check when absent)
if ! PATH="/usr/bin:/bin" command -v gh >/dev/null 2>&1; then t $([ "$rc" = 2 ] && has 'git-only' && echo 0 || echo 1) "full mode without gh points to --git-only"; fi
out=$(bash "$INV" abc . 2>&1); rc=$?; t $([ "$rc" = 2 ] && echo 0 || echo 1) "non-numeric PR number exits 2"

echo; echo "$pass passed, $fail failed"
[ "$fail" = 0 ]
