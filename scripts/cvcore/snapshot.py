from __future__ import annotations

import fnmatch
import hashlib
import os
import subprocess
import tempfile
from pathlib import Path

from .gitio import GitError, git, require_commit, zsplit

EVIDENCE_EXCLUDES = ("docs/compound-v/runs",)
CANON = ("-c", "core.autocrlf=false", "-c", "core.fileMode=true",
         "-c", f"core.excludesFile={os.devnull}", "-c", "core.safecrlf=false")
ENV_GLOBS = (".env*", "*.env", "*.local.*")
_BIG = 1 << 20


class SnapshotError(Exception):
    pass


class SnapshotMismatch(SnapshotError):
    pass


def _excludes():
    return [f":(exclude){p}" for p in EVIDENCE_EXCLUDES]


def tree(repo) -> str:
    require_commit(repo)
    with tempfile.TemporaryDirectory(prefix="cv-idx-") as tmp:
        env = {"GIT_INDEX_FILE": os.path.join(tmp, "index")}
        # Seeding from HEAD keeps tracked-but-ignored files in the snapshot.
        git(repo, *CANON, "read-tree", "HEAD", env=env)
        git(repo, *CANON, "rm", "-r", "--cached", "-q", "--ignore-unmatch", "--",
            *EVIDENCE_EXCLUDES, env=env)
        git(repo, *CANON, "add", "-A", "--", ".", *_excludes(), env=env)
        return git(repo, *CANON, "write-tree", env=env).decode().strip()


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
    data = git(repo, "archive", "--format=tar", tree_id)
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

