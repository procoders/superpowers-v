#!/usr/bin/env bash
# INVENTORY of everything a merged PR left on this machine.
# It never deletes, checks out, stashes or pushes, and never touches the working tree or any local branch.
# The one write is `git fetch`, which updates remote-tracking refs (origin/<base>, the PR head object).
#
#   inventory.sh <pr-number> [repo-dir]                       full mode: needs git, gh (logged in), jq
#   inventory.sh --git-only <head-branch> [repo-dir]          git only: no gh, no jq, no network but origin
#                                                             (BASE=<branch> overrides the detected base)
#
# Prints sections: PR, MERGE PROOF, CONTENT PROOF, ISSUES, LOCAL BRANCHES, REMOTE BRANCH,
# WORKTREES, STASH. Each line starts with OK / INFO / WARN / GATE so the reader can triage at a glance:
#   GATE = a failed gate. Cleanup must stop. The script then exits 1.
#   WARN = ask the user before touching that item. Does not change the exit code.
#
# Git-only mode cannot see the forge, so it cannot know a PR exists or that it merged. It proves what git can
# (the branch is in base, or every line it added is in base) and says the rest out loud: the user must confirm
# the merge, and fork/author/issue checks are not done.
#
# Exit codes: 0 all gates passed; 1 at least one gate failed; 2 the script could not run.
set -uo pipefail

MODE=full
if [ "${1:-}" = "--git-only" ]; then
  MODE=git; shift
  HEAD="${1:?usage: inventory.sh --git-only <head-branch> [repo-dir]}"; PR=""
else
  PR="${1:?usage: inventory.sh <pr-number> [repo-dir] | --git-only <head-branch> [repo-dir]}"
  case "$PR" in ''|*[!0-9]*) echo "WARN PR number must be digits, got '$PR' (for a branch name use --git-only)"; exit 2;; esac
fi
DIR="${2:-.}"

need="git"; [ "$MODE" = full ] && need="git gh jq"
for tool in $need; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "WARN required tool not found: $tool"
    [ "$MODE" = full ] && echo "INFO without gh/jq run: inventory.sh --git-only <head-branch>  (weaker proof, see SKILL.md)"
    exit 2; }
done
cd "$DIR" || { echo "WARN cannot cd to $DIR"; exit 2; }
git rev-parse --git-dir >/dev/null 2>&1 || { echo "WARN $DIR is not a git repository"; exit 2; }

GATES=0
gate() { echo "GATE $*"; GATES=$((GATES + 1)); }

if [ "$MODE" = full ]; then
  json=$(gh pr view "$PR" --json number,state,mergedAt,mergeCommit,headRefName,headRefOid,baseRefName,baseRefOid,files,closingIssuesReferences,isCrossRepository,author 2>/dev/null) \
    || { echo "WARN gh cannot read PR $PR (wrong account or repo?)"; exit 2; }
  q() { printf '%s' "$json" | jq -r "$1"; }

  STATE=$(q .state); HEAD=$(q .headRefName); HEAD_OID=$(q .headRefOid); BASE=$(q .baseRefName)
  BASE_OID=$(q .baseRefOid)
  MERGE_OID=$(q '.mergeCommit.oid // ""'); AUTHOR=$(q .author.login); CROSS=$(q .isCrossRepository)
  ME=$(gh api user --jq .login 2>/dev/null || echo "?")
else
  STATE="unknown"; CROSS="unknown"; MERGE_OID=""; AUTHOR="?"; ME="?"
  BASE="${BASE:-$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||')}"
  BASE="${BASE:-main}"
  # The branch tip: the local branch if there is one, else the remote-tracking ref.
  HEAD_OID=$(git rev-parse --verify --quiet "refs/heads/$HEAD^{commit}" || git rev-parse --verify --quiet "refs/remotes/origin/$HEAD^{commit}" || true)
  [ -n "$HEAD_OID" ] || { echo "WARN no local or origin branch named '$HEAD' — nothing to inventory"; exit 2; }
fi

# The branch every proof is taken against: the repository's default branch, not the PR's own base. A stacked PR
# merged into its parent shows MERGED, yet says nothing about the default branch.
DEFAULT=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||')
CMP="$BASE"; [ "$MODE" = full ] && [ -n "$DEFAULT" ] && CMP="$DEFAULT"

echo "== PR"
if [ "$MODE" = full ]; then
  echo "INFO #$PR state=$STATE head=$HEAD base=$BASE author=$AUTHOR (you: $ME) fork=$CROSS mergedAt=$(q '.mergedAt // "-"')"
  [ "$STATE" = "MERGED" ] || gate "PR is not merged — stop: there is nothing to clean up yet"
  if [ "$BASE" != "$CMP" ]; then
    gate "PR base is '$BASE', not the default branch '$CMP': merging there reaches $CMP only if $BASE does. Proofs below are against $CMP — verify by hand"
  fi
  if [ "$AUTHOR" != "$ME" ]; then
    echo "WARN the PR is by $AUTHOR, not by you ($ME) — its branches are not yours; ask before deleting any"
  fi
  if [ "$CROSS" = "true" ]; then
    echo "WARN fork PR — the head branch lives in the author's fork, not in origin. Never delete '$HEAD' on origin: a same-named branch there is someone else's"
  fi
else
  echo "INFO git-only mode: head=$HEAD (${HEAD_OID:0:9}) base=$BASE. No forge: PR state, author, fork and closing issues are NOT checked"
  echo "WARN no proof here that a PR for '$HEAD' was ever opened or merged — the user must confirm it merged. Do not delete a remote branch unless it is yours and they confirm"
fi

git fetch -q origin "$CMP" 2>/dev/null || echo "WARN could not fetch origin/$CMP — results below may be stale"
git rev-parse --verify --quiet "origin/$CMP" >/dev/null || { echo "WARN origin/$CMP does not exist"; exit 2; }

echo "== MERGE PROOF (the badge is not proof: a stacked PR can show MERGED and never reach $BASE)"
if [ "$MODE" = full ]; then
  if [ -n "$MERGE_OID" ] && git cat-file -e "$MERGE_OID" 2>/dev/null; then
    if git merge-base --is-ancestor "$MERGE_OID" "origin/$CMP"; then
      echo "OK merge commit ${MERGE_OID:0:9} is in origin/$CMP"
    else
      gate "merge commit ${MERGE_OID:0:9} is NOT in origin/$CMP — it merged into another branch; do not delete anything"
    fi
  else
    gate "merge commit not available locally (${MERGE_OID:-none})"
  fi
elif git merge-base --is-ancestor "$HEAD_OID" "origin/$CMP"; then
  echo "OK branch tip ${HEAD_OID:0:9} is an ancestor of origin/$CMP (a merge commit or fast-forward put it there)"
else
  echo "INFO branch tip ${HEAD_OID:0:9} is not an ancestor of origin/$CMP — normal after a squash or rebase merge; the content proof below decides"
fi

echo "== CONTENT PROOF (squash/rebase merges hide the branch from git branch --merged)"
if [ "$MODE" = full ]; then
  # Make sure the PR head commit is local so its files can be compared even if every branch is gone.
  git cat-file -e "$HEAD_OID" 2>/dev/null || git fetch -q origin "pull/$PR/head" 2>/dev/null
else
  BASE_OID=$(git merge-base "$HEAD_OID" "origin/$CMP" 2>/dev/null || true)
fi
if git cat-file -e "$HEAD_OID" 2>/dev/null && [ -n "${BASE_OID:-}" ] && git cat-file -e "$BASE_OID" 2>/dev/null; then
  if [ "$MODE" = full ]; then files=$(q '.files[].path'); else files=$(git diff --name-only "$BASE_OID" "$HEAD_OID"); fi
  differ=0; nfiles=0
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    nfiles=$((nfiles + 1))
    git diff --quiet "$HEAD_OID" "origin/$CMP" -- "$f" 2>/dev/null && continue
    differ=1
    # The file differs. A later commit may explain that, but "a later commit touched it" is not
    # proof that it kept the change. The proof is every line the PR added still being in base.
    if ! git cat-file -e "$HEAD_OID:$f" 2>/dev/null; then
      if git cat-file -e "origin/$CMP:$f" 2>/dev/null; then
        gate "$f was deleted by the PR but exists in origin/$CMP — the deletion may be missing"
      else
        echo "OK $f was deleted by the PR and is absent in origin/$CMP"
      fi
      continue
    fi
    if git diff --numstat "$BASE_OID" "$HEAD_OID" -- "$f" | grep -q '^-'; then
      gate "$f is binary and differs from origin/$CMP — cannot prove the PR content is there; compare by hand"
      continue
    fi
    base_text=$(git show "origin/$CMP:$f" 2>/dev/null || true)
    missing=0; total=0
    while IFS= read -r line; do
      total=$((total + 1))
      # Here-string, not a pipe: grep -q exits on the first match, and under pipefail the SIGPIPE it
      # sends to printf would make a line that IS present count as missing.
      grep -Fxq -- "$line" <<<"$base_text" || missing=$((missing + 1))
    done < <(git diff -U0 "$BASE_OID" "$HEAD_OID" -- "$f" | grep '^+' | grep -v '^+++' | cut -c2-)
    if [ "$missing" = 0 ]; then
      echo "INFO $f differs from origin/$CMP, but all $total line(s) the PR added are still there (later commits changed other parts)"
    else
      gate "$f differs from origin/$CMP and $missing of $total line(s) the PR added are no longer in base — reverted, or rewritten by later commits; verify by hand"
    fi
  done <<<"$files"
  [ "$differ" = 0 ] && [ "$nfiles" -gt 0 ] && echo "OK every file the branch touched is identical in origin/$CMP"
  if [ "$nfiles" = 0 ]; then
    if [ "$MODE" = git ]; then gate "the branch changes no file relative to its merge base — nothing to prove it was merged"; else echo "INFO the PR touched no files"; fi
  fi
else
  gate "branch head ${HEAD_OID:0:9} or its base ${BASE_OID:-none} not available — content cannot be proven"
fi

echo "== ISSUES the PR closes"
if [ "$MODE" = full ]; then
  n=$(q '.closingIssuesReferences | length')
  [ "$n" = 0 ] && echo "INFO PR closes no issue by keyword"
  for i in $(q '.closingIssuesReferences[].number'); do
    s=$(gh issue view "$i" --json state --jq .state 2>/dev/null || echo "?")
    if [ "$s" = "CLOSED" ]; then echo "OK #$i closed"; else gate "#$i is $s — the classic sign of a stacked-merge race"; fi
  done
else
  echo "INFO not checked in git-only mode"
fi

echo "== LOCAL BRANCHES (by name, by PR number as a whole token in the name, or pointing at the PR head)"
git for-each-ref --format='%(refname:short) %(objectname)' refs/heads | while read -r b oid; do
  hit=""
  [ "$b" = "$HEAD" ] && hit="head-branch"
  [ "$oid" = "$HEAD_OID" ] && hit="${hit:+$hit,}at-pr-head"
  if [ -n "$PR" ] && printf '%s' "$b" | grep -Eq "(^|[^0-9])$PR([^0-9]|$)"; then hit="${hit:+$hit,}name-has-$PR"; fi
  [ -z "$hit" ] && continue
  extra=$(git rev-list --count "origin/$CMP..$b" 2>/dev/null || echo "?")
  beyond=$(git rev-list --count "$HEAD_OID..$b" 2>/dev/null || echo "?")
  co=$(git worktree list --porcelain | awk -v r="refs/heads/$b" '$1=="worktree"{w=substr($0,10)} $1=="branch" && $2==r {print w}')
  echo "INFO $b [$hit] commits-not-in-$CMP=$extra commits-after-PR-head=$beyond${co:+ checked-out-in=$co}"
  [ "$beyond" != "0" ] && [ "$beyond" != "?" ] && echo "WARN $b has $beyond commit(s) the PR never contained — unmerged work, ask before deleting"
done

echo "== REMOTE BRANCH"
if [ "$CROSS" = "true" ]; then
  echo "INFO fork PR — '$HEAD' is in the author's fork; origin is not checked and must not be deleted from"
elif git ls-remote --exit-code --heads origin "$HEAD" >/dev/null 2>&1; then
  r=$(git ls-remote --heads origin "$HEAD" | cut -c1-40)
  if [ "$r" = "$HEAD_OID" ]; then echo "INFO origin/$HEAD still exists at the branch tip"
  elif [ "$MODE" = git ]; then echo "WARN origin/$HEAD exists and is not at the local tip (${r:0:9}) — it may be someone else's branch, or moved after the merge; ask"
  else echo "WARN origin/$HEAD exists but moved past the PR head (${r:0:9}) — someone pushed after the merge, ask"; fi
else
  echo "OK origin/$HEAD already gone"
fi

echo "== WORKTREES (path, HEAD, branch, dirty files)"
# Paths can contain spaces, so take everything after "worktree " instead of splitting on whitespace.
git worktree list --porcelain | awk '
  $1=="worktree" {if (w!="") print w "\t" h "\t" b; w=substr($0,10); h=""; b="(detached)"}
  $1=="HEAD"     {h=substr($2,1,9)}
  $1=="branch"   {b=$2; sub("refs/heads/","",b)}
  END            {if (w!="") print w "\t" h "\t" b}' \
  | sort -u | while IFS=$'\t' read -r w h b; do
    [ -d "$w" ] || { echo "WARN $w registered but missing on disk (prunable)"; continue; }
    d=$(git -C "$w" status --porcelain 2>/dev/null | wc -l | tr -d ' ')
    echo "INFO $w HEAD=$h branch=$b dirty=$d"
  done

echo "== STASH (shared by every worktree and session — report only)"
if [ -n "$PR" ]; then stash_hits=$(git stash list --format='%gd %gs' | grep -F -e "$HEAD" -e "#$PR" || true)
else stash_hits=$(git stash list --format='%gd %gs' | grep -F -e "$HEAD" || true); fi
if [ -n "$stash_hits" ]; then printf '%s\n' "$stash_hits" | sed 's/^/WARN /'; else echo "OK no stash entry mentions $HEAD${PR:+ or #$PR}"; fi

if [ "$GATES" -gt 0 ]; then
  echo "== RESULT: $GATES gate(s) failed — stop, delete nothing"
  exit 1
fi
if [ "$MODE" = git ]; then
  echo "== RESULT: git-only — content gates passed, but the merge itself is NOT confirmed by any forge. Ask the user to confirm it merged before deleting anything"
else
  echo "== RESULT: all gates passed — still ask before deleting (see SKILL.md step 4)"
fi
