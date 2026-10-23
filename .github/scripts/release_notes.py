"""Release notes and title for one version, from CHANGELOG.md.

Usage: release_notes.py <version> <owner/repo> [--changelog PATH] [--out PATH]
Writes the notes to --out (default _release_notes.md) and prints `title_suffix=<text>`.

Title order: an explicit `<!-- title: ... -->` line in the version's section; else the text after the dash
in `## [X.Y.Z] — <text>` when it is not a date; else nothing. A `###` subsection heading is never used:
4.0.0 shipped titled "— and why ([transition table](…))" that way.
"""
from __future__ import annotations

import argparse
import re
import sys

LIMIT = 6000


def section(changelog: str, version: str) -> tuple:
    heads = list(re.finditer(r'(?m)^## \[?(\d+\.\d+\.\d+)\]?(.*)$', changelog))
    for i, m in enumerate(heads):
        if m.group(1) == version:
            end = heads[i + 1].start() if i + 1 < len(heads) else len(changelog)
            return m.group(2), changelog[m.end():end].strip()
    return "", ""


def plain(text: str) -> str:
    text = re.sub(r'!?\[([^\]]*)\]\([^)]*\)', r'\1', text)
    text = text.replace('`', '').replace('**', '').replace('*', '')
    return re.sub(r'\s+', ' ', text).strip()


def title_suffix(head_rest: str, body: str) -> str:
    m = re.search(r'(?m)^<!--\s*title:\s*(.+?)\s*-->\s*$', body)
    if m:
        return plain(m.group(1))[:80]
    rest = re.sub(r'^\s*[—–-]\s*', '', head_rest).strip()
    if rest and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', rest):
        return plain(rest)[:80]
    return ""


def absolute_links(body: str, repo: str) -> str:
    base = f"https://github.com/{repo}/blob/main/"

    def fix(m):
        target = m.group(2)
        if re.match(r'^(?:[a-z][a-z0-9+.-]*:|#|/)', target, re.I):
            return m.group(0)
        return f"{m.group(1)}({base}{target.lstrip('./')})"

    return re.sub(r'(\[[^\]]*\])\(([^)\s]+)\)', fix, body)


def notes(body: str, repo: str) -> str:
    body = re.sub(r'(?m)^<!--\s*title:.*-->\s*\n?', '', body).strip()
    body = absolute_links(body or "See the CHANGELOG for details.", repo)
    if len(body) > LIMIT:
        body = body[:LIMIT].rsplit("\n", 1)[0].rstrip() + "\n\n…"
    return body + f"\n\nFull detail in the [CHANGELOG](https://github.com/{repo}/blob/main/CHANGELOG.md)."


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("version")
    ap.add_argument("repo")
    ap.add_argument("--changelog", default="CHANGELOG.md")
    ap.add_argument("--out", default="_release_notes.md")
    a = ap.parse_args(argv)
    with open(a.changelog, encoding="utf-8") as fh:
        head_rest, body = section(fh.read(), a.version)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(notes(body, a.repo))
    print(f"title_suffix={title_suffix(head_rest, body)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
