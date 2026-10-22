from __future__ import annotations

import os

from . import run
from .gitio import GitError, git, resolve
from .receipts import execute
from .run import RunError
from .scope import EXCLUDES, check


def _worktrees(repo) -> dict:
    trees, path = {}, None
    out = git(repo, "worktree", "list", "--porcelain").decode("utf-8", "surrogateescape")
    for line in out.split("\n"):
        if line.startswith("worktree "):
            path = line[len("worktree "):]
        elif line.startswith("branch ") and path:
            trees[line[len("branch "):]] = path
    return trees


def _dirty(path, extra=()) -> bool:
    return bool(git(path, "status", "--porcelain", "-z", "--untracked-files=all", "--", ".",
                    *EXCLUDES, *extra).strip(b"\0"))


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
    tip = resolve(repo, branch)
    root = os.path.realpath(str(repo))
    trees = _worktrees(repo)
    inside = [os.path.relpath(os.path.realpath(p), root) for p in trees.values()
              if os.path.realpath(p).startswith(root + os.sep)]
    if _dirty(repo, [f":(exclude){p}" for p in inside]):
        return _refuse(repo, rec, task, branch, "main tree dirty")
    wt = trees.get(f"refs/heads/{branch}")
    if wt and os.path.realpath(wt) != root and _dirty(wt):
        return _refuse(repo, rec, task, branch, "interrupted: uncommitted changes")
    base = git(repo, "merge-base", "HEAD", tip).decode().strip()
    if git(repo, "rev-list", "--count", f"{base}..{tip}").strip() == b"0":
        return _refuse(repo, rec, task, branch, "no commits")
    res = check(repo, base, rec["lanes"][task], head=tip)
    if res["verdict"] != "pass":
        return _refuse(repo, rec, task, branch, "outside lane", res["violations"])
    try:
        git(repo, "merge", "--no-ff", "--no-commit", tip)
    except GitError:
        git(repo, "merge", "--abort", check=False)
        return _refuse(repo, rec, task, branch, "conflict")
    rc, tail, _ = execute(rec["test_cmd"], repo, rec.get("timeout_s") or run.TIMEOUT_S)
    if rc != 0:
        git(repo, "merge", "--abort", check=False)
        return _refuse(repo, rec, task, branch, "tests failed")
    try:
        git(repo, "commit", "-q", "-m", f"merge lane {task}")
    except GitError as e:
        git(repo, "merge", "--abort", check=False)
        return _refuse(repo, rec, task, branch, f"commit failed: {e}")
    rec.setdefault("lane_state", {})[task] = {
        "branch": branch, "base": base, "status": "merged",
        "commit": git(repo, "rev-parse", "HEAD").decode().strip()}
    run.save(repo, rec)
    return {"status": "merged", "reason": "", "violations": []}

