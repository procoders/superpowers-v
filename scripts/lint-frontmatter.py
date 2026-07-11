#!/usr/bin/env python3
"""
Compound V frontmatter linter.

Parses every Markdown file in the plugin and validates its YAML frontmatter
against Claude Code's plugin spec + this project's conventions:

  - Path-class PRESENCE gate (A4): `agents/*.md`, `commands/*.md`, and
    `skills/*/SKILL.md` MUST have a frontmatter block; every other .md is exempt.
    Path classes anchor at the lint root — run from the plugin root, as CI does
    (`python3 scripts/lint-frontmatter.py .`).
  - Frontmatter parses as valid YAML mapping
  - Required `name` and `description` fields present (commands exempt — name = filename;
    the commands/ check uses path.parts, never substring matching — A6)
  - `description` <= 500 chars (soft), <= 1024 total frontmatter (hard)
  - No Haiku model assignment (project policy)
  - `model: opus` REQUIRED on `agents/*.md` (A5) — the documented model policy
    (Opus default; execution-layer models never live in frontmatter)
  - Closing `---` at EOF without a trailing newline is accepted (A6)
  - Common YAML pitfalls (unquoted globs in `paths`)

Exit 0 = clean, exit 1 = violations found.

Usage: python3 scripts/lint-frontmatter.py [path]
       python3 scripts/lint-frontmatter.py --selftest
"""

import pathlib
import sys

import yaml

DESCRIPTION_SOFT_MAX = 500
FRONTMATTER_HARD_MAX = 1024

# Path classes (relative to the lint root) that MUST carry frontmatter (A4).
CLASS_AGENT = "agent"
CLASS_COMMAND = "command"
CLASS_SKILL = "skill"


def path_class(rel):
    """Classify a path RELATIVE to the lint root: "agent" | "command" | "skill" | None.

    Uses path.parts, never substring matching (A6) — `mycommands/x.md` or
    `docs/commands-history.md` can no longer masquerade as a command.

    RECURSIVE semantics, deliberate (Codex v2.8 round-1 #7): ANY `.md` under
    `agents/` or `commands/` (nested dirs included) is gated, and ANY file
    literally named `SKILL.md` at ANY depth under `skills/` is gated — stricter
    than the docstring's `skills/*/SKILL.md` glob reads. Rationale: a nested
    `commands/sub/x.md` would still be loaded as a command by the plugin
    runtime, and a reference file has no business being named SKILL.md; if one
    ever legitimately is, rename it rather than weakening the gate.
    """
    parts = rel.parts
    if len(parts) < 2 or rel.suffix != ".md":
        return None
    if parts[0] == "agents":
        return CLASS_AGENT
    if parts[0] == "commands":
        return CLASS_COMMAND
    if parts[0] == "skills" and len(parts) >= 3 and parts[-1] == "SKILL.md":
        return CLASS_SKILL
    return None


def lint_file(path: pathlib.Path, rel=None) -> list:
    """Lint one file. `rel` is the path relative to the lint root (for path-class
    rules); defaults to `path` itself when the caller has no separate root."""
    issues: list = []
    txt = path.read_text()
    cls = path_class(pathlib.PurePath(rel if rel is not None else path))

    if not txt.startswith("---\n"):
        if cls is not None:
            issues.append(
                f"missing frontmatter — {cls} files (agents/*.md, commands/*.md, "
                "skills/*/SKILL.md) must start with a '---' block"
            )
        return issues  # other .md without frontmatter: exempt, not a plugin file

    end = txt.find("\n---\n", 4)
    if end < 0 and txt.endswith("\n---"):
        # Closing --- at EOF without a trailing newline is a VALID close (A6).
        end = len(txt) - len("\n---")
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
    if cls != CLASS_COMMAND and "name" not in data:
        issues.append("missing required 'name' field")

    if "description" not in data:
        issues.append("missing required 'description' field")

    desc = data.get("description", "") or ""
    if len(desc) > DESCRIPTION_SOFT_MAX:
        issues.append(
            f"description is {len(desc)} chars (soft max {DESCRIPTION_SOFT_MAX})"
        )

    # Project policy: no Haiku
    model = str(data.get("model") or "").strip().lower()
    if "haiku" in model:
        issues.append(f"model '{model}' contains 'haiku' — project policy forbids Haiku")

    # Project policy (A5): agents carry exactly `model: opus` — Opus-by-default is
    # documented as ENFORCED; execution-layer models (manifest backend/model) never
    # appear in frontmatter.
    if cls == CLASS_AGENT and model != "opus":
        found = f"'{model}'" if model else "no model field"
        issues.append(
            f"agents must carry 'model: opus' (found {found}) — project model policy"
        )

    # Common gotcha: unquoted glob in paths field
    paths_val = data.get("paths")
    if isinstance(paths_val, str) and any(c in paths_val for c in "{}[]"):
        issues.append(
            f"'paths' field contains glob chars — quote it: paths: \"{paths_val}\""
        )

    return issues


def _selftest() -> int:
    import shutil
    import tempfile

    fails = []

    def check(name, cond):
        print(("  ok   " if cond else "  FAIL ") + name)
        if not cond:
            fails.append(name)

    root = pathlib.Path(tempfile.mkdtemp())

    def issues_for(relpath, text):
        p = root / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return lint_file(p, rel=p.relative_to(root))

    AGENT_OK = "---\nname: x\ndescription: d\nmodel: opus\n---\nbody\n"
    try:
        # presence gate (A4): the three gated classes flag a missing block…
        check("agent without frontmatter flagged",
              any("missing frontmatter" in i for i in issues_for("agents/a.md", "# doc\n")))
        check("command without frontmatter flagged",
              any("missing frontmatter" in i for i in issues_for("commands/c.md", "# doc\n")))
        check("SKILL.md without frontmatter flagged",
              any("missing frontmatter" in i
                  for i in issues_for("skills/foo/SKILL.md", "# doc\n")))
        # …and everything else stays exempt
        check("plain doc exempt", issues_for("docs/notes.md", "# doc\n") == [])
        check("skill reference file exempt",
              issues_for("skills/foo/reference.md", "# doc\n") == [])
        check("nested agents/ dir NOT gated (anchored at root)",
              issues_for("docs/agents/readme.md", "# doc\n") == [])

        # happy paths
        check("valid agent clean", issues_for("agents/good.md", AGENT_OK) == [])
        check("valid command clean (name exempt)",
              issues_for("commands/good.md", "---\ndescription: d\n---\nbody\n") == [])
        check("valid skill clean",
              issues_for("skills/foo/SKILL.md",
                         "---\nname: s\ndescription: d\n---\nbody\n") == [])

        # A6: closing --- at EOF without trailing newline is a valid close
        check("EOF-terminated frontmatter accepted",
              issues_for("commands/eof.md", "---\ndescription: d\n---") == [])
        check("truly unclosed frontmatter still flagged",
              any("no closing" in i for i in issues_for("commands/open.md",
                                                        "---\ndescription: d\n")))

        # A6: commands/ detection by path.parts, not substring — a dir merely
        # CONTAINING "commands" gets no name exemption
        check("substring 'commands' dir is not a command (name required)",
              any("missing required 'name'" in i
                  for i in issues_for("subcommands/x.md", "---\ndescription: d\n---\nb\n")))

        # Recursive path-class semantics are DELIBERATE (Codex v2.8 r1 #7):
        # nested commands and any SKILL.md at depth are gated
        check("nested commands/sub/x.md requires frontmatter",
              any("must start with a '---'" in i
                  for i in issues_for("commands/sub/x.md", "no frontmatter here\n")))
        check("nested skills/foo/refs/SKILL.md requires frontmatter",
              any("must start with a '---'" in i
                  for i in issues_for("skills/foo/refs/SKILL.md", "plain body\n")))

        # A5: agents must carry model: opus
        check("agent with model sonnet flagged",
              any("model: opus" in i for i in issues_for(
                  "agents/sonnet.md", "---\nname: x\ndescription: d\nmodel: sonnet\n---\nb\n")))
        check("agent with no model field flagged",
              any("model: opus" in i for i in issues_for(
                  "agents/nomodel.md", "---\nname: x\ndescription: d\n---\nb\n")))

        # unchanged policies still hold
        check("haiku still rejected anywhere",
              any("haiku" in i for i in issues_for(
                  "skills/foo/SKILL.md",
                  "---\nname: s\ndescription: d\nmodel: haiku\n---\nb\n")))
        check("description soft max still enforced",
              any("soft max" in i for i in issues_for(
                  "commands/long.md", "---\ndescription: %s\n---\nb\n" % ("x" * 501))))
        check("unquoted glob in paths still flagged",
              any("glob chars" in i for i in issues_for(
                  "skills/foo/SKILL.md",
                  '---\nname: s\ndescription: d\npaths: src/{a,b}/**\n---\nb\n')))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\n%d failed" % len(fails))
    if fails:
        print("FAILED: " + ", ".join(fails))
        return 1
    print("all self-tests passed")
    return 0


def main(argv: list) -> int:
    if "--selftest" in argv[1:]:
        return _selftest()
    root = pathlib.Path(argv[1]) if len(argv) > 1 else pathlib.Path(".")
    total = 0
    for f in sorted(root.rglob("*.md")):
        parts = f.parts
        if "node_modules" in parts or ".git" in parts:
            continue
        issues = lint_file(f, rel=f.relative_to(root))
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
