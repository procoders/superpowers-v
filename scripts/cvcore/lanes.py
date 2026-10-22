from __future__ import annotations

import os

from . import run
from .gitio import GitError, git, resolve, worktrees, zsplit
from .receipts import execute
from .run import RunError
from .scope import check, skipped


def _dirty(path) -> bool:
    return bool(git(path, "status", "--porcelain", "-z", "--untracked-files=all", "--", ".",
                    *skipped(path)).strip(b"\0"))


def _merging(repo) -> bool:
    try:
        git(repo, "rev-parse", "-q", "--verify", "MERGE_HEAD")
        return True
    except GitError:
        return False


def _abort(repo) -> None:
    if _merging(repo):
        git(repo, "merge", "--abort", check=False)


def _refuse(repo, rec, task, branch, reason, violations=()) -> dict:
    rec.setdefault("lane_state", {})[task] = {"branch": branch, "status": "refused",
                                              "reason": reason}
    run.save(repo, rec)
    return {"status": "refused", "reason": reason, "violations": list(violations)}


def finish(repo, rec, task, branch) -> dict:
    if task not in rec.get("lanes", {}):
        raise RunError(f"task {task!r} has no lane in this run's plan")
    if not rec.get("test_cmd"):
        raise RunError("the run has no test_cmd to run on the merged tree")
    done = rec.get("lane_state", {}).get(task) or {}
    if done.get("status") == "merged" and done.get("branch") == branch:
        return {"status": "merged", "reason": "already merged", "violations": []}
    tip = resolve(repo, branch)
    root = os.path.realpath(str(repo))
    if _merging(repo):
        return _refuse(repo, rec, task, branch, "a merge is already in progress")
    if _dirty(repo) or git(repo, "diff", "--cached", "--name-only", "-z").strip(b"\0"):
        return _refuse(repo, rec, task, branch, "main tree dirty")
    wt = next((w["path"] for w in worktrees(repo) if w["branch"] == f"refs/heads/{branch}"), None)
    if wt and os.path.realpath(wt) != root and _dirty(wt):
        return _refuse(repo, rec, task, branch, "interrupted: uncommitted changes")
    base = git(repo, "merge-base", "HEAD", tip).decode().strip()
    if git(repo, "rev-list", "--count", f"{base}..{tip}").strip() == b"0":
        return _refuse(repo, rec, task, branch, "no commits")
    res = check(repo, base, rec["lanes"][task], head=tip)
    if res["verdict"] != "pass":
        return _refuse(repo, rec, task, branch, "outside lane", res["violations"])
    added = zsplit(git(repo, "diff", "--name-only", "-z", "--no-renames", "--diff-filter=A",
                       base, tip))
    hit = [p for p in added if os.path.lexists(os.path.join(root, p))]
    if hit:
        return _refuse(repo, rec, task, branch, "would overwrite untracked or ignored file", hit)
    try:
        git(repo, "merge", "--no-ff", "--no-commit", "--no-overwrite-ignore", tip)
    except GitError:
        _abort(repo)
        return _refuse(repo, rec, task, branch, "conflict")
    rc, tail, *_ = execute(rec["test_cmd"], repo, rec.get("timeout_s") or run.TIMEOUT_S)
    if rc != 0:
        _abort(repo)
        return _refuse(repo, rec, task, branch, "tests failed")
    try:
        git(repo, "commit", "-q", "-m", f"merge lane {task}")
    except GitError as e:
        _abort(repo)
        return _refuse(repo, rec, task, branch, f"commit failed: {e}")
    rec.setdefault("lane_state", {})[task] = {
        "branch": branch, "base": base, "status": "merged",
        "commit": git(repo, "rev-parse", "HEAD").decode().strip()}
    run.save(repo, rec)
    return {"status": "merged", "reason": "", "violations": []}

