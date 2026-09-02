# Direct-mode writer — the shape that was blocked by our own files

Dogfood note for run `2026-09-02-df2c-direct-retry`, job `direct-writer`.

This job runs at `direct` isolation — in the project checkout itself, not a
worktree. Direct-mode jobs have no worktree to merge from, so they must not
report a worktree path as their result: doing so is what allowed 3.0.1 to
apply a direct job's patch into the wrong repository.

Lane registration pinned this job's baseline commit
(`c9fe7d5ccd7f0a15fb006fba7cce7c9f18200da2`) before any writes happened, so
the scope gate below is measured against a HEAD that could not have moved
out from under it.

Write-allowed for this job: this file only.
