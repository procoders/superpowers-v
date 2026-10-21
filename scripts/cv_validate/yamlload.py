"""YAML loading for the manifest validator: PyYAML first, the embedded subset parser as fallback."""

import re


# --------------------------------------------------------------------------- #
# YAML loading: prefer PyYAML, fall back to an embedded subset parser.
# --------------------------------------------------------------------------- #
class ManifestParseError(ValueError):
    """PyYAML is present and refused the document (finding 53): a hard violation."""


def load_yaml(text):
    """Parse ``text``: PyYAML when importable, the embedded subset parser else.

    THE FALLBACK IS NOT SILENT (fifth review pass, 2026-09-02). It used to be:
    one ``except Exception`` covered both "PyYAML is not installed" and "PyYAML
    read this document and REFUSED it", and the second case is not a fallback at
    all — a document the full parser rejected is not a document the subset parser
    understood better. It is announced on stderr so the degradation is visible to
    whoever is looking at the failure, instead of surfacing three layers later as
    a manifest that mysteriously has no jobs.
    """
    try:
        import yaml  # noqa: WPS433 (intentional optional dep)
    except ImportError:  # PyYAML absent — the designed, ordinary fallback
        return _mini_yaml(text)
    try:
        return yaml.safe_load(text)
    except Exception as exc:  # noqa: BLE001 - PyYAML READ it and refused
        # FAIL CLOSED (stage-2 dogfood, 2026-09-03, finding 53). Announcing the
        # degradation was not enough: this validator said "valid" for a manifest
        # whose `title:` carried an inner ": " — the subset parser read it, CI's
        # PyYAML would not have, and the orchestrator was told the document was
        # fine. A document the reference parser refuses is not a valid manifest;
        # the subset parser is for the machine WITHOUT PyYAML, never a second
        # opinion on one that has it.
        raise ManifestParseError(
            "PyYAML rejected this document (%s) — the reference parser must read a "
            "manifest; quote scalars that contain ': ' or '#', and do not rely on the "
            "embedded subset parser to accept what PyYAML refuses" % str(exc).replace("\n", " "))


def _strip_comment(line):
    """Remove a trailing ``# comment`` not inside quotes."""
    out = []
    in_s = None
    i = 0
    while i < len(line):
        ch = line[i]
        if in_s:
            out.append(ch)
            if ch == in_s:
                in_s = None
        elif ch in ("'", '"'):
            in_s = ch
            out.append(ch)
        elif ch == "#":
            break
        else:
            out.append(ch)
        i += 1
    return "".join(out).rstrip()


def _scalar(tok):
    tok = tok.strip()
    if tok == "" or tok == "~" or tok.lower() == "null":
        return None
    if tok.startswith("'") and tok.endswith("'") and len(tok) >= 2:
        # YAML escapes a single quote inside a single-quoted scalar by doubling
        # it. Leaving `Gate''s` unescaped made the fallback parser disagree with
        # PyYAML on the very field a folded manifest exercises.
        return tok[1:-1].replace("''", "'")
    if tok.startswith('"') and tok.endswith('"') and len(tok) >= 2:
        return tok[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if tok.lower() == "true":
        return True
    if tok.lower() == "false":
        return False
    if re.match(r"^-?\d+$", tok):
        return int(tok)
    if re.match(r"^-?\d+\.\d+$", tok):
        return float(tok)
    return tok


def _inline_list(tok):
    inner = tok.strip()[1:-1].strip()
    if not inner:
        return []
    return [_scalar(p) for p in _split_commas(inner)]


def _split_commas(s):
    parts = []
    buf = []
    in_s = None
    for ch in s:
        if in_s:
            buf.append(ch)
            if ch == in_s:
                in_s = None
        elif ch in ("'", '"'):
            in_s = ch
            buf.append(ch)
        elif ch == ",":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return parts


def _open_quote(s):
    """The quote character left OPEN at the end of ``s``, or ``None``.

    Doubled quotes inside a quoted scalar (YAML's ``''`` escape) close and
    reopen, so a complete ``'Gate''s seven issues'`` reads as balanced and a
    truncated ``'Gate''s seven`` reads as open — which is exactly the signal a
    folded quoted scalar leaves on its first line.
    """
    in_s = None
    for ch in s:
        if in_s:
            if ch == in_s:
                in_s = None
        elif ch in ("'", '"'):
            in_s = ch
    return in_s


def _value_part(content):
    """The scalar VALUE a stripped line ends with, or ``None`` when it opens a
    nested block (``key:`` with nothing after the colon)."""
    if content.startswith("- "):
        content = content[2:].strip()
        if content == "":
            return None
    idx = _colon_index(content)
    if idx < 0:
        return content          # a plain list item, or a fold continuation
    return content[idx + 1:].strip()


def _is_continuation(prev, indent, content):
    """True iff ``(indent, content)`` continues the scalar on line ``prev``."""
    prev_indent, prev_content = prev
    if indent <= prev_indent:
        return False
    if content.startswith("- "):
        return False
    value = _value_part(prev_content)
    if not value:
        return False            # `key:` opens a block; it has no scalar to fold
    if value[:1] in ("'", '"') and _open_quote(value):
        # An unterminated quoted scalar: the fold is unambiguous, and the
        # continuation may legitimately contain a `: ` inside the quotes.
        return True
    return _colon_index(content) < 0


# `key: |`, `key: >`, with the optional chomping and explicit-indent indicators.
_BLOCK_SCALAR_RE = re.compile(r"^[|>][+-]?\d*$")


def _fold_plain_scalars(lines):
    """Join YAML's multi-line scalars back onto one line.

    ``yaml.safe_dump`` wraps every long scalar at ``width`` — 80 by default, 100
    for the manifests this repo writes — so a long value arrives as its first
    line plus one or more MORE-INDENTED continuation lines::

        feature: Close the fifth review pass, a lane guard that actually
          enforces, and honest acceptance greps

    The shipped parser had no notion of that. ``parse_map`` saw the deeper
    continuation, broke out of the mapping, and EVERYTHING AFTER IT IN THE
    DOCUMENT WAS SILENTLY DROPPED — ``jobs:`` included. That is the defect the
    fifth review pass found in ``hooks/lane-guard.sh``: driven with a real run's
    manifest on an interpreter without PyYAML, the guard read a manifest with no
    jobs, resolved no lane, and failed open on every out-of-lane write.

    A block scalar (``key: |`` / ``key: >``) is consumed here too, and FLATTENED
    onto one line rather than reproduced: this parser has no line-preserving
    representation, and what it did before was worse — it stored the bare ``|``
    and then `parse_map` broke on the block's first line, dropping the remainder
    of the document exactly as the fold did. The flattening is lossy (newlines
    and blank lines become single spaces, and a ``#`` inside the block is still
    treated as a comment); PyYAML is the parser that gets block scalars right,
    and this one only has to keep the document intact enough to read a lane.
    """
    out = []
    i = 0
    while i < len(lines):
        indent, content = lines[i]
        i += 1
        value = _value_part(content)
        if value and _BLOCK_SCALAR_RE.match(value):
            body = []
            while i < len(lines) and lines[i][0] > indent:
                body.append(lines[i][1])
                i += 1
            head = content[:content.rindex(value)]
            out.append([indent, head + " ".join(body)])
            continue
        if out and _is_continuation(out[-1], indent, content):
            out[-1][1] = out[-1][1] + " " + content
            continue
        out.append([indent, content])
    return [(indent, content) for indent, content in out]


# A top-level ``jobs:`` key, at column 0. ``(?m)`` so ``^`` is a line start.
_TOP_LEVEL_JOBS_RE = re.compile(r"(?m)^jobs:[ \t]*(\S.*)?$")


def _assert_jobs_survived(text, doc):
    """A document whose top-level ``jobs:`` vanished in parsing is a PARSE
    FAILURE, not a manifest with no jobs.

    Every consumer spells the read ``(data or {}).get("jobs") or []``, so a
    truncated parse and an empty manifest are indistinguishable downstream — and
    the one place that matters most, ``hooks/lane-guard.sh``, turns "no jobs"
    into "no lane to enforce" and allows the write. Raising here makes the
    truncation loud at the only point that can still tell the difference.
    """
    match = _TOP_LEVEL_JOBS_RE.search(text)
    if not match:
        return
    if (match.group(1) or "").strip() in ("[]", "{}"):
        return                  # explicitly empty, and parsed faithfully
    jobs = doc.get("jobs") if isinstance(doc, dict) else None
    if jobs:
        return
    raise ValueError(
        "the embedded YAML subset parser found a top-level `jobs:` in this "
        "document but produced none: the parse is TRUNCATED, not empty. The "
        "document uses YAML this parser does not model (an anchor, a block "
        "scalar, a merge key). Install PyYAML — on macOS /usr/bin/python3 ships "
        "it — or simplify the document. Do NOT read this as a manifest with no "
        "jobs.")


def _mini_yaml(text):
    """
    Minimal YAML-subset parser. Handles the manifest shape we emit:
    nested mappings, lists of mappings, inline ``[a, b]`` lists, block
    ``- item`` lists of scalars, and scalars folded across lines the way
    ``yaml.safe_dump`` writes them.

    This is a fallback only; PyYAML is used when available.
    """
    lines = []
    for raw in text.splitlines():
        s = _strip_comment(raw)
        if s.strip() == "":
            continue
        if s.strip() == "---":
            continue
        indent = len(s) - len(s.lstrip(" "))
        lines.append([indent, s.strip()])

    lines = _fold_plain_scalars(lines)

    pos = [0]

    def parse_block(min_indent):
        # Decide mapping vs list by the first line at this indent.
        if pos[0] >= len(lines):
            return None
        indent, content = lines[pos[0]]
        if indent < min_indent:
            return None
        if content.startswith("- "):
            return parse_list(indent)
        return parse_map(indent)

    def parse_list(indent):
        items = []
        while pos[0] < len(lines):
            cur_indent, content = lines[pos[0]]
            if cur_indent != indent or not content.startswith("- "):
                if cur_indent < indent:
                    break
                if not content.startswith("- "):
                    break
            rest = content[2:].strip()
            pos[0] += 1
            if ":" in rest and not _looks_scalar(rest):
                # First key of a list-of-mappings item.
                item = {}
                key, val = _kv(rest)
                _assign(item, key, val, indent + 2)
                # Continue consuming deeper keys belonging to this item.
                while pos[0] < len(lines):
                    n_indent, n_content = lines[pos[0]]
                    if n_indent <= indent:
                        break
                    if n_content.startswith("- "):
                        break
                    pos[0] += 1
                    k2, v2 = _kv(n_content)
                    _assign(item, k2, v2, n_indent + 2)
                items.append(item)
            else:
                items.append(_scalar(rest))
        return items

    def parse_map(indent):
        obj = {}
        while pos[0] < len(lines):
            cur_indent, content = lines[pos[0]]
            if cur_indent != indent:
                break
            if content.startswith("- "):
                break
            pos[0] += 1
            key, val = _kv(content)
            _assign(obj, key, val, indent + 2)
        return obj

    def _assign(obj, key, val, child_indent):
        if val is not None and val != "":
            obj[key] = val
            return
        child = parse_block(child_indent)
        if child is None and pos[0] < len(lines):
            # A BLOCK SEQUENCE MAY SIT AT ITS PARENT KEY'S OWN INDENTATION, and
            # that is exactly how `yaml.safe_dump` writes one:
            #
            #     jobs:
            #     - id: guard-honest
            #
            # The shipped parser only looked one level deeper, found nothing,
            # recorded `jobs: None`, and then `parse_map` broke on the `- ` line
            # — dropping the rest of the document. Every manifest this repo
            # emits is safe_dump output, so the parser's happy path was the one
            # shape it could not read. Deliberately narrow: only when the VERY
            # NEXT line is a `- ` item at exactly this key's own indent.
            n_indent, n_content = lines[pos[0]]
            if n_indent == child_indent - 2 and n_content.startswith("- "):
                child = parse_list(n_indent)
        obj[key] = child

    def _kv(content):
        idx = _colon_index(content)
        if idx < 0:
            return content.strip(), None
        key = content[:idx].strip()
        rest = content[idx + 1:].strip()
        if rest == "":
            return key, None
        if rest.startswith("["):
            return key, _inline_list(rest)
        return key, _scalar(rest)

    doc = parse_block(0)
    _assert_jobs_survived(text, doc)
    return doc


def _looks_scalar(rest):
    # A list item like "- foo" with no key:value mapping.
    return _colon_index(rest) < 0


def _colon_index(content):
    in_s = None
    for i, ch in enumerate(content):
        if in_s:
            if ch == in_s:
                in_s = None
        elif ch in ("'", '"'):
            in_s = ch
        elif ch == ":":
            if i + 1 >= len(content) or content[i + 1] in (" ", "\t"):
                return i
    return -1
