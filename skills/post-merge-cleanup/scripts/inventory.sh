#!/usr/bin/env bash
# READ-ONLY inventory of everything a merged PR left on this machine.
# It never deletes, checks out, stashes or pushes. It only fetches (so the answer is current) and reads.
#
#   inventory.sh <pr-number> [repo-dir]
#
# Prints sections: PR, MERGE PROOF, CONTENT PROOF, ISSUES, LOCAL BRANCHES, REMOTE BRANCH,
# WORKTREES, STASH. Each line starts with OK / WARN / INFO so the reader can triage at a glance.
set -uo pipefail

PR="${1:?usage: inventory.sh <pr-number> [repo-dir]}"
DIR="${2:-.}"
cd "$DIR" || { echo "WARN cannot cd to $DIR"; exit 2; }
git rev-parse --git-dir >/dev/null 2>&1 || { echo "WARN $DIR is not a git repository"; exit 2; }

json=$(gh pr view "$PR" --json number,state,mergedAt,mergeCommit,headRefName,headRefOid,baseRefName,files,closingIssuesReferences,isCrossRepository,author 2>/dev/null) \
  || { echo "WARN gh cannot read PR $PR (wrong account or repo?)"; exit 2; }
q() { printf '%s' "$json" | jq -r "$1"; }

STATE=$(q .state); HEAD=$(q .headRefName); HEAD_OID=$(q .headRefOid); BASE=$(q .baseRefName)
MERGE_OID=$(q '.mergeCommit.oid // ""'); AUTHOR=$(q .author.login); CROSS=$(q .isCrossRepository)
ME=$(gh api user --jq .login 2>/dev/null || echo "?")

echo "== PR"
echo "INFO #$PR state=$STATE head=$HEAD base=$BASE author=$AUTHOR (you: $ME) fork=$CROSS mergedAt=$(q '.mergedAt // "-"')"
[ "$STATE" = "MERGED" ] || echo "WARN PR is not merged — stop: there is nothing to clean up yet"

git fetch -q origin "$BASE" --prune 2>/dev/null || echo "WARN could not fetch origin/$BASE — results below may be stale"

echo "== MERGE PROOF (the badge is not proof: a stacked PR can show MERGED and never reach $BASE)"
if [ -n "$MERGE_OID" ] && git cat-file -e "$MERGE_OID" 2>/dev/null; then
  if git merge-base --is-ancestor "$MERGE_OID" "origin/$BASE"; then
    echo "OK merge commit ${MERGE_OID:0:9} is in origin/$BASE"
  else
    echo "WARN merge commit ${MERGE_OID:0:9} is NOT in origin/$BASE — it merged into another branch; do not delete anything"
  fi
else
  echo "WARN merge commit not available locally (${MERGE_OID:-none})"
fi

echo "== CONTENT PROOF (squash/rebase merges hide the branch from git branch --merged)"
# Make sure the PR head commit is local so its files can be compared even if every branch is gone.
git cat-file -e "$HEAD_OID" 2>/dev/null || git fetch -q origin "pull/$PR/head" 2>/dev/null
if git cat-file -e "$HEAD_OID" 2>/dev/null; then
  differ=0
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    if ! git diff --quiet "$HEAD_OID" "origin/$BASE" -- "$f" 2>/dev/null; then
      differ=1
      later=$(git log --oneline "${MERGE_OID:-$HEAD_OID}..origin/$BASE" -- "$f" 2>/dev/null | wc -l | tr -d ' ')
      if [ "$later" = 0 ]; then
        echo "WARN $f differs from origin/$BASE and no later commit explains it — the PR content may be missing"
      else
        echo "INFO $f differs from origin/$BASE, explained by $later later commit(s) on $BASE"
      fi
    fi
  done < <(q '.files[].path')
  [ "$differ" = 0 ] && echo "OK every file the PR touched is identical in origin/$BASE"
  true
else
  echo "WARN PR head ${HEAD_OID:0:9} not fetchable — content cannot be proven"
fi

echo "== ISSUES the PR closes"
n=$(q '.closingIssuesReferences | length')
[ "$n" = 0 ] && echo "INFO PR closes no issue by keyword"
for i in $(q '.closingIssuesReferences[].number'); do
  s=$(gh issue view "$i" --json state --jq .state 2>/dev/null || echo "?")
  [ "$s" = "CLOSED" ] && echo "OK #$i closed" || echo "WARN #$i is $s"
done

echo "== LOCAL BRANCHES (by name, by PR number in the name, or pointing at the PR head)"
git for-each-ref --format='%(refname:short) %(objectname)' refs/heads | while read -r b oid; do
  hit=""
  [ "$b" = "$HEAD" ] && hit="head-branch"
  [ "$oid" = "$HEAD_OID" ] && hit="${hit:+$hit,}at-pr-head"
  case "$b" in *"$PR"*) hit="${hit:+$hit,}name-has-$PR";; esac
  [ -z "$hit" ] && continue
  extra=$(git rev-list --count "origin/$BASE..$b" 2>/dev/null || echo "?")
  beyond=$(git rev-list --count "$HEAD_OID..$b" 2>/dev/null || echo "?")
  co=$(git worktree list --porcelain | awk -v r="refs/heads/$b" '$1=="worktree"{w=$2} $1=="branch" && $2==r {print w}')
  echo "INFO $b [$hit] commits-not-in-$BASE=$extra commits-after-PR-head=$beyond${co:+ checked-out-in=$co}"
  [ "$beyond" != "0" ] && [ "$beyond" != "?" ] && echo "WARN $b has $beyond commit(s) the PR never contained — unmerged work, ask before deleting"
done

echo "== REMOTE BRANCH"
if git ls-remote --exit-code --heads origin "$HEAD" >/dev/null 2>&1; then
  r=$(git ls-remote --heads origin "$HEAD" | cut -c1-40)
  if [ "$r" = "$HEAD_OID" ]; then echo "INFO origin/$HEAD still exists at the PR head"
  else echo "WARN origin/$HEAD exists but moved past the PR head (${r:0:9}) — someone pushed after the merge, ask"; fi
else
  echo "OK origin/$HEAD already gone"
fi

echo "== WORKTREES (path, HEAD, branch, dirty files)"
git worktree list --porcelain | awk '$1=="worktree"{w=$2;b="(detached)"} $1=="HEAD"{h=substr($2,1,9)} $1=="branch"{sub("refs/heads/","",$2);b=$2} $0==""{print w"\t"h"\t"b} END{if(w!="")print w"\t"h"\t"b}' \
  | sort -u | while IFS=$'\t' read -r w h b; do
    [ -d "$w" ] || { echo "WARN $w registered but missing on disk (prunable)"; continue; }
    d=$(git -C "$w" status --porcelain 2>/dev/null | wc -l | tr -d ' ')
    echo "INFO $w HEAD=$h branch=$b dirty=$d"
  done

echo "== STASH (shared by every worktree and session — report only)"
stash_hits=$(git stash list --format='%gd %gs' | grep -F -e "$HEAD" -e "#$PR" || true)
if [ -n "$stash_hits" ]; then printf '%s\n' "$stash_hits" | sed 's/^/WARN /'; else echo "OK no stash entry mentions $HEAD or #$PR"; fi
