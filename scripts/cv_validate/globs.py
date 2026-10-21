"""Deterministic glob matching and overlap detection for write_allowed partitions."""

import re


# --------------------------------------------------------------------------- #
# Glob overlap (deterministic).
# --------------------------------------------------------------------------- #
def glob_to_regex(pattern):
    i = 0
    n = len(pattern)
    out = ["(?s:"]
    while i < n:
        c = pattern[i]
        if c == "*":
            j = i
            while j < n and pattern[j] == "*":
                j += 1
            if j - i >= 2:
                at_seg = out[-1] in ("(?s:", "/")
                if out[-1] == "/" and (j >= n or pattern[j] == "/"):
                    out[-1] = "(?:/.*)?"
                elif at_seg and j < n and pattern[j] == "/":
                    out.append("(?:.*/)?")
                    i = j + 1
                    continue
                else:
                    out.append(".*")
            else:
                out.append("[^/]*")
            i = j
            continue
        if c == "?":
            out.append("[^/]")
            i += 1
            continue
        if c == "[":
            k = i + 1
            if k < n and pattern[k] == "!":
                k += 1
            if k < n and pattern[k] == "]":
                k += 1
            while k < n and pattern[k] != "]":
                k += 1
            if k >= n:
                out.append(re.escape("["))
                i += 1
                continue
            inner = pattern[i + 1:k]
            if inner.startswith("!"):
                inner = "^" + inner[1:]
            out.append("[" + inner + "]")
            i = k + 1
            continue
        out.append(re.escape(c))
        i += 1
    out.append(")\\Z")
    return "".join(out)


def glob_match(path, pattern):
    return re.compile(glob_to_regex(pattern)).match(path) is not None


def witness(pattern):
    """A canonical concrete path that the glob matches (best effort)."""
    out = []
    i = 0
    n = len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            j = i
            while j < n and pattern[j] == "*":
                j += 1
            if j - i >= 2:
                # '**' -> two segments to exercise recursion.
                if out and out[-1] == "/" and (j >= n or pattern[j] == "/"):
                    out.append("x/x")
                    if j < n and pattern[j] == "/":
                        i = j + 1
                        continue
                else:
                    out.append("x/x")
            else:
                out.append("x")
            i = j
            continue
        if c == "?":
            out.append("x")
            i += 1
            continue
        if c == "[":
            k = i + 1
            neg = False
            if k < n and pattern[k] == "!":
                neg = True
                k += 1
            start = k
            if k < n and pattern[k] == "]":
                k += 1
            while k < n and pattern[k] != "]":
                k += 1
            if k >= n:
                out.append("[")
                i += 1
                continue
            inner = pattern[start:k]
            out.append("y" if neg else (inner[0] if inner else "x"))
            i = k + 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _seg_is_literal(s):
    return not any(c in s for c in "*?[")


def _literal_prefix(s):
    out = []
    for c in s:
        if c in "*?[":
            break
        out.append(c)
    return "".join(out)


def _literal_suffix(s):
    out = []
    for c in reversed(s):
        if c in "*?[":
            break
        out.append(c)
    return "".join(reversed(out))


def _seg_disjoint(pa, pb):
    """SOUND: True only when single segments pa, pb (no '/') provably share no string."""
    if _seg_is_literal(pa) and _seg_is_literal(pb):
        return pa != pb
    # Fixed leading literals that disagree on their common length -> no common string.
    apre, bpre = _literal_prefix(pa), _literal_prefix(pb)
    n = min(len(apre), len(bpre))
    if apre[:n] != bpre[:n]:
        return True
    # Fixed trailing literals that disagree on their common length -> no common string.
    asuf, bsuf = _literal_suffix(pa), _literal_suffix(pb)
    m = min(len(asuf), len(bsuf))
    if m > 0 and asuf[len(asuf) - m:] != bsuf[len(bsuf) - m:]:
        return True
    return False


def _provably_disjoint(a, b):
    """SOUND: True only when globs a, b provably match no common path.

    Aligns segments from both ends, stopping at any ``**`` (which spans a variable
    number of segments). A literal-segment conflict in the fixed prefix or suffix —
    or differing fixed segment counts when neither side has ``**`` — proves disjoint.
    Anything else is treated as a POSSIBLE overlap by the caller (conservative).
    """
    sa, sb = a.split("/"), b.split("/")
    # Left-align across the fixed prefix (until a '**' appears on either side).
    i = 0
    while i < len(sa) and i < len(sb) and sa[i] != "**" and sb[i] != "**":
        if _seg_disjoint(sa[i], sb[i]):
            return True
        i += 1
    # Right-align across the fixed suffix (until a '**' appears on either side).
    k = 0
    while (k < len(sa) - i and k < len(sb) - i
           and sa[-1 - k] != "**" and sb[-1 - k] != "**"):
        if _seg_disjoint(sa[-1 - k], sb[-1 - k]):
            return True
        k += 1
    # No '**' on either side and different fixed lengths -> disjoint.
    if "**" not in sa and "**" not in sb and len(sa) != len(sb):
        return True
    return False


def globs_overlap(a, b):
    """Conservative SOUND overlap test (no false negatives) between two write globs.

    A false negative here is dangerous — it would let two jobs silently own the same
    file. So we only declare 'disjoint' when we can PROVE it; otherwise we flag overlap
    (worst case: a genuinely-disjoint manifest is sent for human review). This fixes the
    earlier single-witness strategy, which missed e.g. ``src/*/test.ts`` vs
    ``src/foo/*.ts`` (overlap at ``src/foo/test.ts``).
    """
    if a == b:
        return True
    # Fast positive: a concrete witness of one matched by the other proves overlap.
    if glob_match(witness(a), b) or glob_match(witness(b), a):
        return True
    # Otherwise: overlap unless provably disjoint.
    return not _provably_disjoint(a, b)
