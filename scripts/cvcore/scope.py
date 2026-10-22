from __future__ import annotations

import functools
import re


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
