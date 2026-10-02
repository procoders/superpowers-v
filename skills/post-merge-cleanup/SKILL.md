---
name: post-merge-cleanup
description: Clean the local machine after a pull request is merged — local and remote branches, git worktrees, temp files, dev servers — and close out the ticket, deleting only what is provably yours or provably merged. Use when the user says the PR is merged and asks to tidy up ("смержено, чисти", "clean up after merge", "delete my branches/worktree"), and before deleting any branch or worktree whose PR was squash- or rebase-merged.
---

# Post-merge cleanup

The goal is a machine with no trace of finished work and **zero lost work**. Those two pull in
opposite directions, so the whole skill is about one distinction: what you can *prove* (check it
yourself, act without asking) versus what you can only *assume* (ask first).

Deletion is the one step that cannot be undone, and the things most likely to be destroyed by
mistake look exactly like your leftovers: another session's branch, the app's worktree pool, a stash
entry from a different worktree, a secret the user placed by hand. So the default for anything you
did not create in this work is "leave it and mention it", not "clean it".

## Step 1 — Prove the merge (read-only)

Run the bundled inventory, `scripts/inventory.sh` in this skill's base directory. It only fetches and
reads; it never deletes, checks out or pushes. It needs `git`, `gh` (logged in to the repo's account) and `jq`:

```bash
bash <skill-base-dir>/scripts/inventory.sh <pr-number> <repo-dir>
```

Every line starts with `OK` / `WARN` / `INFO`. Read it against these gates. **Any failed gate stops
the cleanup**: report the failure and do not delete anything.

| Gate | Why the obvious check is not enough |
|---|---|
| PR state is `MERGED` | — |
| Merge commit is an ancestor of `origin/<base>` | A stacked PR can merge into its parent branch *after* that parent already landed. GitHub shows MERGED, and the code never reaches main. The badge is not proof. |
| Every file the PR touched is identical in `origin/<base>`, or differs only because of later commits on base | Squash and rebase merges create new commits. `git branch -d` refuses and `git branch --merged` lies, so content comparison is the only proof. If a file differs and no later commit explains it, the PR content may be missing. |
| Issues the PR closes are `CLOSED` | An issue still open despite "Closes #N" is the classic sign of the stacked-merge race above. |

Spot-check one distinctive line of the change in `origin/<base>` (`git show origin/main:<file> | grep -c '<line>'`).
"A later commit touched the file" is not proof that it kept your change.

## Step 2 — Close out the work before removing it

Do this first, because cleanup removes the commits these steps derive data from:

- If the repo has a ticket workflow (a project skill or doc describing how tickets are closed), run its ship step:
  Done status, actual end date, actual hours. A squash merge leaves one commit, so hours cannot be
  derived from history. Give an honest estimate and say it is an estimate.
- Update or close any memory note about the work ("✅ DONE, PR #N merged <date>").

## Step 3 — Build the deletion list: only what is provably yours

An item is **yours** when this conversation (or its memory note) shows you created it for this work.
A name that merely contains the ticket number is a hint, not proof. Typical items:

- the PR's head branch, locally and on `origin`;
- the branch the session started on (for example an app-created `claude/<slug>` branch) — only if it
  holds no commits beyond base;
- temp files you wrote: eval output, PR body drafts, files under the session scratchpad or `$TMPDIR`;
- dev servers or background processes you started (stop them with the tool that started them).

An item is **deletable without asking** only when it is yours *and* safe:

- **Branch:** all its commits are in the PR head (`commits-after-PR-head=0`), so nothing on it is
  unmerged. On the remote, it still points at the PR head (nobody pushed after the merge).
- **Temp file:** it holds only output you can regenerate.

## Step 4 — Ask before touching any of these

Ask once, as a short list, and act only on a clear yes. Each one needs a question for its own reason:

| Item | Why it needs a yes |
|---|---|
| Uncommitted changes, or commits not in the PR (`commits-after-PR-head>0`, `dirty>0`) | This is unmerged work, and deleting it is unrecoverable. |
| The worktree this session is running in | Removing it from inside breaks the session. If the desktop app created it, the clean path is archiving the session, which ends the conversation, so the user must agree. Never `rm -rf` it. |
| Detached worktrees you did not create (for example a "kept ready" pool under `.claude/worktrees/`) | The app reuses them and reaps them itself. |
| Branches, worktrees or stash entries of other sessions or teammates | Parallel sessions share the repo. Their work looks like stale leftovers. |
| A remote branch that moved past the PR head, or a PR authored by someone else | Someone may still be using it. |
| Any `git stash` entry | The stash is shared across every worktree. Report it; never pop or drop it. |
| Secrets or config the user placed (`.env.local`, API keys), memory notes | These were the user's deliberate input, not your leftovers. |
| Global caches (`pnpm store prune`, Docker images, `~/Library/Caches`) | They affect every project on the machine. Worth offering when disk is short, never a silent part of cleanup. |

## Step 5 — Delete, in a safe order

1. Temp files and scratch output.
2. Remote branch: `git push origin --delete <head>` (only when step 3 cleared it).
3. Local branches. A branch checked out in your own worktree cannot be deleted, so first
   `git checkout --detach origin/<base>` there. Use `git branch -D` only after the content proof in
   step 1; that proof is what makes `-D` safe after a squash merge.
4. `git fetch --prune origin` so stale remote-tracking refs go too.
5. The worktree itself, last, and only with the user's yes from step 4.

Re-run `inventory.sh` afterwards. The PR's branches should be gone and nothing new should show as WARN.

## Report

Lead with the one open decision (usually "archive the session to remove the worktree?"), then list:

- **Proven:** merge commit in base, content in base, issue closed;
- **Deleted:** each branch, remote branch and file group;
- **Left on purpose:** each item with its reason (user's secret, app pool, other session's branch);
- **Closed out:** ticket status and hours, marking estimated hours as estimates.
