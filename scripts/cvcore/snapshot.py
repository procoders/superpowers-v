from __future__ import annotations

import fnmatch
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .gitio import GitError, git, require_commit, worktrees, zsplit

RUNS = "docs/compound-v/runs"
EVIDENCE_NAMES = re.compile(
    r"(\d{8}-\d{6}-[a-z0-9-]+(-review-\d+|-plan-review)?\.json|\.tmp-[^/]*\.json|\.[^/]*\.lock|triage\.log)\Z")
CANON = ("-c", "core.autocrlf=false", "-c", "core.fileMode=true",
         "-c", f"core.excludesFile={os.devnull}", "-c", "core.safecrlf=false",
         "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false")
ENV_GLOBS = (".env*", "*.env", "*.local.*")
_BIG = 1 << 20


class SnapshotError(Exception):
    pass


class SnapshotMismatch(SnapshotError):
    pass


def worktree_roots(repo) -> list:
    root = os.path.realpath(str(repo))
    paths = (os.path.realpath(w["path"]) for w in worktrees(repo))
    return sorted(os.path.relpath(p, root) for p in paths if p.startswith(root + os.sep))


def unhashed(repo) -> list:
    d = Path(repo) / RUNS
    names = sorted(os.listdir(d)) if d.is_dir() else []
    ours = [f"{RUNS}/{n}" for n in names if EVIDENCE_NAMES.match(n) and (d / n).is_file()]
    return ours + worktree_roots(repo)


def excludes(paths) -> list:
    return [f":(exclude,literal){p}" for p in paths]


def _seed(repo, env) -> None:
    src = Path(repo) / os.fsdecode(git(repo, "rev-parse", "--git-path", "index").strip())
    if src.is_file():
        shutil.copyfile(str(src), env["GIT_INDEX_FILE"])
    else:
        git(repo, *CANON, "read-tree", "HEAD", env=env)
    flagged = [e[2:] for e in zsplit(git(repo, "ls-files", "-v", "-z", env=env)) if e[:1].islower()]
    if flagged:
        git(repo, "update-index", "--no-assume-unchanged", "-z", "--stdin", env=env,
            input=b"\0".join(os.fsencode(p) for p in flagged))


def tree(repo) -> str:
    require_commit(repo)
    skip = unhashed(repo)
    with tempfile.TemporaryDirectory(prefix="cv-idx-") as tmp:
        env = {"GIT_INDEX_FILE": os.path.join(tmp, "index")}
        # A copy of the user's index keeps force-added ignored files; theirs is never written.
        _seed(repo, env)
        if skip:
            git(repo, *CANON, "rm", "-r", "--cached", "-q", "--ignore-unmatch", "--",
                *[f":(literal){p}" for p in skip], env=env)
        git(repo, *CANON, "add", "-A", "--", ".", *excludes(_not_ignored(repo, skip)), env=env)
        return git(repo, *CANON, "write-tree", env=env).decode().strip()


def _not_ignored(repo, paths) -> list:
    # git add errors on an exclude pathspec that names an ignored file; -A skips those anyway.
    if not paths:
        return []
    out = git(repo, "check-ignore", "-z", "--no-index", "--stdin", check=False,
              input=b"\0".join(os.fsencode(p) for p in paths))
    ignored = set(zsplit(out))
    return [p for p in paths if p not in ignored]


def verify_tracked(repo, tree_id: str, dest) -> list:
    gd = os.fsdecode(git(repo, "rev-parse", "--absolute-git-dir").strip())
    wt = ("--git-dir", gd, "--work-tree", str(dest))
    with tempfile.TemporaryDirectory(prefix="cv-verify-") as tmp:
        env = {"GIT_INDEX_FILE": os.path.join(tmp, "index")}
        git(repo, *wt, *CANON, "read-tree", tree_id, env=env)
        git(repo, *wt, *CANON, "update-index", "-q", "--refresh", env=env, check=False)
        return zsplit(git(repo, *wt, *CANON, "diff-files", "--name-only", "-z", env=env))


def _hash_dir(dest: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="cv-rehash-") as tmp:
        git(tmp, "init", "-q")
        wt = ("--git-dir", os.path.join(tmp, ".git"), "--work-tree", str(dest))
        env = {"GIT_INDEX_FILE": os.path.join(tmp, "index")}
        git(dest, *wt, *CANON, "add", "-A", "-f", "--", ".", env=env)
        return git(dest, *wt, *CANON, "write-tree", env=env).decode().strip()


def ignored_env_digest(repo) -> str:
    specs = [f":(glob)**/{g}" for g in ENV_GLOBS]
    out = git(repo, *CANON, "ls-files", "-z", "--others", "--ignored", "--exclude-standard",
              "--", *specs)
    paths = sorted(p for p in zsplit(out)
                   if any(fnmatch.fnmatchcase(os.path.basename(p), g) for g in ENV_GLOBS))
    if not paths:
        return "none"
    h = hashlib.sha256()
    for p in paths:
        full = os.path.join(str(repo), p)
        try:
            st = os.lstat(full)
            if os.path.islink(full):
                part = "link:" + os.readlink(full)
            elif st.st_size > _BIG:
                part = f"big:{st.st_size}:{st.st_mtime_ns}"
            else:
                with open(full, "rb") as f:
                    part = hashlib.sha256(f.read()).hexdigest()
        except OSError:
            part = "unreadable"
        h.update(os.fsencode(p) + b"\0" + part.encode() + b"\n")
    return h.hexdigest()


def materialize(repo, tree_id: str, dest: Path, _after_extract=None) -> str:
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    if any(dest.iterdir()):
        raise SnapshotError(f"checkout destination is not empty: {dest}")
    if any(e.startswith(b"160000 ") for e in git(repo, "ls-tree", "-r", "-z", tree_id).split(b"\0")):
        raise SnapshotError("submodules are not supported by the review checkout")
    data = git(repo, *CANON, "archive", "--format=tar", tree_id)
    p = subprocess.run(["tar", "-x", "-f", "-", "-C", str(dest)], input=data,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        raise SnapshotError("tar failed: " + p.stderr.decode("utf-8", "replace").strip()[-200:])
    if _after_extract:
        _after_extract(dest)
    got = _hash_dir(dest)
    if got != tree_id:
        raise SnapshotMismatch(f"checkout {got} does not match snapshot {tree_id}")
    return tree_id

