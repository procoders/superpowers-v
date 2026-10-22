from __future__ import annotations

import os
import re

from .gitio import git
from .scope import changed, skipped, matches, untracked
from .snapshot import CANON

_F = re.I | re.M
PREDICATES = [
    ("auth", re.compile(r"password|passwd|login|logout|session|jwt|bearer|oauth|csrf|cookie", _F)),
    ("payments", re.compile(r"payment|stripe|paypal|invoice|card_number|iban|checkout", _F)),
    ("personal_data", re.compile(
        r"email|phone|address|birth|passport|ssn|gdpr|erase|retention", _F)),
    ("endpoint", re.compile(
        r"\.(get|post|put|patch|delete)\(\s*['\"]/|@\w+\.(route|get|post|put|delete)\("
        r"|path\(|export (async )?function (GET|POST|PUT|PATCH|DELETE)\b"
        r"|^\s*(get|post|resources)\s", _F)),
    ("form", re.compile(r"<form\b|method=[\"']post|<input\b", _F)),
    ("schema", re.compile(r"CREATE TABLE|ALTER TABLE|migration", _F)),
    ("crypto", re.compile(r"hash|bcrypt|argon|hmac|encrypt|secret", _F)),
    ("upload", re.compile(r"multipart|upload", _F)),
]
UI_PATHS = ["**/*.html", "**/*.css", "**/*.{tsx,jsx,vue,svelte}", "**/templates/**",
            "**/views/**", "**/pages/**", "**/public/**"]
MAX_LINES = 300
_LIGHT = re.compile(r"typo|опечат|rename|переимен|wording|copy|текст|readme|comment|коммент"
                    r"|bump|version|config value", re.I)
_FULL = re.compile(r"add|implement|build|create|feature|fix|change|update|remove|delete|move"
                   r"|refactor|добав|сделай|реализ|исправ|измени|удали", re.I)
_BIG = 1 << 20


def _diff(repo, base, *opts) -> bytes:
    return git(repo, *CANON, "diff", *opts, "--no-color", "--no-ext-diff", "--no-textconv",
               "--no-renames", base, "--", ".", *skipped(repo))


def _added(repo, base) -> str:
    lines, in_hunk = [], False
    for line in _diff(repo, base, "-U0").split(b"\n"):
        if line.startswith(b"diff --git"):
            in_hunk = False
        elif line.startswith(b"@@"):
            in_hunk = True
        elif in_hunk and line[:1] in (b"+", b"-"):
            lines.append(line[1:].decode("utf-8", "replace"))
    return "\n".join(lines)


def classify_diff(repo, base) -> dict:
    texts, count, unclassifiable = [_added(repo, base)], 0, False
    for rec in _diff(repo, base, "--numstat", "-z").split(b"\0"):
        cols = rec.split(b"\t")
        if len(cols) < 3:
            continue
        if cols[0] == b"-" or cols[1] == b"-":
            unclassifiable = True
        else:
            count += int(cols[0]) + int(cols[1])
    for p in untracked(repo):
        full = os.path.join(str(repo), p)
        try:
            if os.path.islink(full):
                texts.append(os.readlink(full))
                continue
            if os.path.getsize(full) > _BIG:
                raise ValueError("too big")
            with open(full, "rb") as f:
                data = f.read()
            if b"\0" in data:
                raise ValueError("binary")
            text = data.decode("utf-8")
        except (OSError, ValueError):
            unclassifiable = True
            continue
        texts.append(text)
        count += text.count("\n") + (0 if text.endswith("\n") or not text else 1)
    blob = "\n".join(texts)
    reasons = [name for name, rx in PREDICATES if rx.search(blob)]
    if count > MAX_LINES:
        reasons.append(f"large: {count} changed lines")
    if unclassifiable:
        reasons.append("unclassifiable")
    return {"tier": "full" if reasons else "light", "reasons": reasons,
            "touches_ui": any(matches(p, UI_PATHS) for p in changed(repo, base))}


def is_action(text: str) -> bool:
    return bool(_LIGHT.search(text) or _FULL.search(text))


def classify_request(text: str):
    hit = any(rx.search(text) for _, rx in PREDICATES)
    if len(text) <= 300 and _LIGHT.search(text) and not hit:
        return "light"
    if hit or _FULL.search(text):
        return "full"
    return None
