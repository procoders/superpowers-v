#!/usr/bin/env python3
"""
Compound V frontmatter linter.

Parses every Markdown file in the plugin and validates its YAML frontmatter
against Claude Code's plugin spec + this project's conventions:

  - Frontmatter parses as valid YAML mapping
  - Required `name` and `description` fields present (commands exempt — name = filename)
  - `description` <= 500 chars (soft), <= 1024 total frontmatter (hard)
  - No Haiku model assignment (project policy)
  - Common YAML pitfalls (unquoted globs in `paths`)

Exit 0 = clean, exit 1 = violations found.

Usage: python3 scripts/lint-frontmatter.py [path]
"""

import sys
import pathlib
import yaml

DESCRIPTION_SOFT_MAX = 500
FRONTMATTER_HARD_MAX = 1024


def lint_file(path: pathlib.Path) -> list[str]:
    issues: list[str] = []
    txt = path.read_text()

    if not txt.startswith("---\n"):
        return []  # no frontmatter, not a plugin file

    end = txt.find("\n---\n", 4)
    if end < 0:
        issues.append("no closing --- delimiter")
        return issues

    fm_raw = txt[4:end]

    # Hard char limit
    if len(fm_raw) > FRONTMATTER_HARD_MAX:
        issues.append(
            f"frontmatter is {len(fm_raw)} chars (hard max {FRONTMATTER_HARD_MAX})"
        )

    # Parse
    try:
        data = yaml.safe_load(fm_raw)
    except yaml.YAMLError as e:
        issues.append(f"YAML parse error: {e}")
        return issues

    if not isinstance(data, dict):
        issues.append(f"frontmatter parses as {type(data).__name__}, expected mapping")
        return issues

    # Commands use filename as name; skills/agents need name field
    is_command = "commands/" in str(path)
    if not is_command and "name" not in data:
        issues.append("missing required 'name' field")

    if "description" not in data:
        issues.append("missing required 'description' field")

    desc = data.get("description", "") or ""
    if len(desc) > DESCRIPTION_SOFT_MAX:
        issues.append(
            f"description is {len(desc)} chars (soft max {DESCRIPTION_SOFT_MAX})"
        )

    # Project policy: no Haiku
    model = (data.get("model") or "").lower()
    if "haiku" in model:
        issues.append(f"model '{model}' contains 'haiku' — project policy forbids Haiku")

    # Common gotcha: unquoted glob in paths field
    paths_val = data.get("paths")
    if isinstance(paths_val, str) and any(c in paths_val for c in "{}[]"):
        issues.append(
            f"'paths' field contains glob chars — quote it: paths: \"{paths_val}\""
        )

    return issues


def main(argv: list[str]) -> int:
    root = pathlib.Path(argv[1]) if len(argv) > 1 else pathlib.Path(".")
    total = 0
    for f in sorted(root.rglob("*.md")):
        if "/node_modules/" in str(f) or "/.git/" in str(f):
            continue
        issues = lint_file(f)
        for i in issues:
            print(f"❌ {f}: {i}")
            total += 1

    if total == 0:
        print("✅ All frontmatter clean")
        return 0
    print(f"\n❌ {total} issue(s) found")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
