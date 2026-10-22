from __future__ import annotations

import functools
import os
import re

from .gitio import git, zsplit
from .snapshot import CANON

EVIDENCE = "docs/compound-v"
EXCLUDE = f":(exclude){EVIDENCE}"


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
                      "--", ".", EXCLUDE))


def changed(repo, base) -> list:
    diff = git(repo, *CANON, "diff", "--name-only", "-z", "--no-renames", "--no-ext-diff",
               base, "--", ".", EXCLUDE)
    return sorted(set(zsplit(diff)) | set(untracked(repo)))


def _escapes(root: str, path: str) -> bool:
    full = os.path.join(root, path)
    if not os.path.lexists(full):
        return False
    real = os.path.realpath(full)
    return not (real == root or real.startswith(root + os.sep))


def check(repo, base, allow) -> dict:
    files = changed(repo, base)
    root = os.path.realpath(str(repo))
    bad = [p for p in files if not matches(p, allow) or _escapes(root, p)]
    return {"verdict": "blocked" if bad else "pass", "changed": files, "violations": bad}
