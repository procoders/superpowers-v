from __future__ import annotations

import os
import subprocess
from pathlib import Path

# Inherited from a git hook these would redirect every call to someone else's repo or index.
_DROP = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_PREFIX", "GIT_COMMON_DIR")


class GitError(Exception):
    pass


def git(repo, *args, env=None, input=None, check=True) -> bytes:
    full = {k: v for k, v in os.environ.items() if k not in _DROP}
    full.update({"LC_ALL": "C", "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"})
    full.update(env or {})
    try:
        p = subprocess.run(["git", "-C", str(repo), *args], env=full, input=input,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as e:
        raise GitError(f"git not runnable: {e}") from e
    if check and p.returncode != 0:
        msg = p.stderr.decode("utf-8", "replace").strip().splitlines()
        raise GitError(f"git {args[0] if args else ''} failed: {msg[-1] if msg else p.returncode}")
    return p.stdout


def zsplit(out: bytes) -> list:
    return [os.fsdecode(x) for x in out.split(b"\0") if x]


def repo_root(path) -> Path:
    try:
        out = git(path, "rev-parse", "--show-toplevel")
    except GitError:
        raise GitError(f"not a git repository: {path}") from None
    return Path(os.fsdecode(out.rstrip(b"\n")))


def require_commit(repo) -> str:
    try:
        return git(repo, "rev-parse", "--verify", "-q", "HEAD^{commit}").decode().strip()
    except GitError:
        raise GitError(f"no commit yet in {repo}: make a first commit") from None


def resolve(repo, rev: str) -> str:
    try:
        return git(repo, "rev-parse", "--verify", "-q", f"{rev}^{{commit}}").decode().strip()
    except GitError:
        raise GitError(f"unknown revision: {rev}") from None
