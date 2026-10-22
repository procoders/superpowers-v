from __future__ import annotations

import functools
import os
import re

from .gitio import git, zsplit
from .snapshot import CANON, WORKTREES

EVIDENCE = "docs/compound-v"
EXCLUDES = (f":(exclude){EVIDENCE}", f":(exclude){WORKTREES}")


def _braces(glob: str) -> list:
    m = re.search(r"\{([^{}]*)\}", glob)
    if not m:
        return [glob]
    out = []
    for alt in m.group(1).split(","):
        out += _braces(glob[:m.start()] + alt + glob[m.end():])
    return out


@functools.lru_cache(maxsize=512)
def _compile(glob: str):
    parts = []
    for g in _braces(glob):
        rx, i = "", 0
        while i < len(g):
            if g.startswith("**/", i):
                rx, i = rx + "(?:[^/]*/)*", i + 3
            elif g.startswith("**", i):
                rx, i = rx + ".*", i + 2
            elif g[i] == "*":
                rx, i = rx + "[^/]*", i + 1
            elif g[i] == "?":
                rx, i = rx + "[^/]", i + 1
            else:
                rx, i = rx + re.escape(g[i]), i + 1
        parts.append(rx)
    return re.compile("(?:" + "|".join(parts) + r")\Z", re.S)


def matches(path: str, globs) -> bool:
    if "\n" in path:
        return False
    return any(_compile(g).match(path) for g in globs)


def untracked(repo) -> list:
    return zsplit(git(repo, *CANON, "ls-files", "-z", "--others", "--exclude-standard",
                      "--", ".", *EXCLUDES))


def changed(repo, base, head=None) -> list:
    revs = [base, head] if head else [base]
    diff = set(zsplit(git(repo, *CANON, "diff", "--name-only", "-z", "--no-renames",
                          "--no-ext-diff", *revs, "--", ".", *EXCLUDES)))
    return sorted(diff if head else diff | set(untracked(repo)))


def _escapes(root: str, path: str) -> bool:
    full = os.path.join(root, path)
    if not os.path.lexists(full):
        return False
    real = os.path.realpath(full)
    return not (real == root or real.startswith(root + os.sep))


def _committed_links(repo, head, files) -> dict:
    links, wanted = {}, set(files)
    for entry in git(repo, "ls-tree", "-r", "-z", head).split(b"\0"):
        meta, _, name = entry.partition(b"\t")
        if meta.startswith(b"120000 ") and os.fsdecode(name) in wanted:
            target = git(repo, "cat-file", "blob", meta.split()[2].decode())
            links[os.fsdecode(name)] = os.fsdecode(target)
    return links


def _link_escapes(root: str, path: str, target: str) -> bool:
    real = os.path.normpath(os.path.join(root, os.path.dirname(path), target))
    return not (real == root or real.startswith(root + os.sep))


def check(repo, base, allow, head=None) -> dict:
    files = changed(repo, base, head)
    root = os.path.realpath(str(repo))
    if head:
        links = _committed_links(repo, head, files)
        bad = [p for p in files if not matches(p, allow)
               or (p in links and _link_escapes(root, p, links[p]))]
    else:
        bad = [p for p in files if not matches(p, allow) or _escapes(root, p)]
    return {"verdict": "blocked" if bad else "pass", "changed": files, "violations": bad}
