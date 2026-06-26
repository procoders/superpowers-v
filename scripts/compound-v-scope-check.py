#!/usr/bin/env python3
"""
Compound V scope gate — the git-diff authority behind SCOPE LOCK prose.

This is the deterministic enforcement script the dispatcher calls after EVERY
job, regardless of isolation. Prose SCOPE LOCK is advisory; this script decides.

What it does
------------
Computes the set of files a job actually changed, purely from git:

    changed = (git diff --name-only <baseline>)  ∪  (git ls-files --others --exclude-standard)

then matches each changed path against the job's ``write_allowed`` glob list.
Any changed file that matches NO allowed glob is a violation. One or more
violations ⇒ BLOCKED (non-zero exit). A BLOCKED job must never be merged.

Two modes (mutually exclusive)
------------------------------
* worktree mode (``--worktree <dir>``): run git inside the worktree
  (``git -C <dir> ...``). Baseline defaults to ``HEAD`` (the commit the worktree
  was created at) unless ``--baseline`` is given.
* direct mode (``--repo <dir> --baseline <commit>``): run git inside the repo,
  diffing against an explicit pre-dispatch baseline commit/ref.

``write_allowed`` source
------------------------
Either repeated ``--allow <glob>`` flags, or ``--allow-file <path>`` (one glob
per line, ``#`` comments and blanks ignored), or both (unioned).

Glob semantics (fnmatch-compatible, with ``**``)
------------------------------------------------
* ``*``   matches within a single path segment (not ``/``).
* ``**``  matches across segments, including ``/`` (recursive).
* ``dir/**`` also matches ``dir`` itself and everything beneath it.
* ``?`` and ``[...]`` behave like fnmatch.
Matching is anchored to the full repo-relative path.

Output
------
A small JSON verdict on stdout::

    {"verdict": "pass"|"blocked", "mode": "...", "baseline": "...",
     "changed": [...], "allowed": [...], "violations": [...]}

Exit codes: 0 = pass, 1 = blocked (violations present), 2 = usage/git error.

Python 3.9-safe, stdlib only. Targets stock-macOS python3 3.9.6.
"""

import argparse
import json
import os
import subprocess
import sys


def _git(cwd, args):
    """Run ``git -C <cwd> <args>``; return (exit_code, stdout, stderr)."""
    proc = subprocess.run(
        ["git", "-C", cwd] + args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,  # py3.9: text= alias, kept 3.9-friendly
    )
    return proc.returncode, proc.stdout, proc.stderr


def _split_lines(blob):
    out = []
    for line in blob.splitlines():
        line = line.strip()
        if line:
            out.append(line)
    return out


def changed_files(cwd, baseline):
    """Union of tracked-diff and untracked files, repo-relative, deduped/sorted."""
    rc1, diff_out, diff_err = _git(cwd, ["diff", "--name-only", baseline])
    if rc1 != 0:
        raise RuntimeError(
            "git diff failed (baseline %r): %s" % (baseline, diff_err.strip())
        )
    rc2, oth_out, oth_err = _git(
        cwd, ["ls-files", "--others", "--exclude-standard"]
    )
    if rc2 != 0:
        raise RuntimeError("git ls-files failed: %s" % oth_err.strip())

    files = set(_split_lines(diff_out)) | set(_split_lines(oth_out))
    return sorted(files)


def glob_to_regex(pattern):
    """
    Translate a path glob (with ``**``) into a fully-anchored regex string.

    Hand-rolled rather than fnmatch.translate so that ``*`` does NOT cross ``/``
    while ``**`` does. ``dir/**`` also matches ``dir`` itself.
    """
    import re

    i = 0
    n = len(pattern)
    out = ["(?s:"]
    while i < n:
        c = pattern[i]
        if c == "*":
            # Look for a run of consecutive '*'.
            j = i
            while j < n and pattern[j] == "*":
                j += 1
            star_count = j - i
            if star_count >= 2:
                # '**' : match across segments (greedy, includes '/').
                at_segment_start = out[-1] in ("(?s:", "/")
                if (
                    out
                    and out[-1] == "/"
                    and (j >= n or pattern[j] == "/")
                ):
                    # "dir/**" — also match 'dir' itself: replace the just-
                    # emitted '/' so ".../" + "**" becomes "...(/.*)?".
                    out[-1] = "(?:/.*)?"
                elif at_segment_start and j < n and pattern[j] == "/":
                    # Leading/mid "**/" — match zero-or-more leading segments
                    # so '**/x' also matches 'x'. Consume the trailing '/'
                    # here so the prefix can collapse to nothing.
                    out.append("(?:.*/)?")
                    i = j + 1
                    continue
                else:
                    out.append(".*")
            else:
                # single '*': anything but '/'
                out.append("[^/]*")
            i = j
            continue
        if c == "?":
            out.append("[^/]")
            i += 1
            continue
        if c == "[":
            # Character class — find the closing ']'.
            k = i + 1
            if k < n and pattern[k] == "!":
                k += 1
            if k < n and pattern[k] == "]":
                k += 1
            while k < n and pattern[k] != "]":
                k += 1
            if k >= n:
                # No closing bracket — treat '[' literally.
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


def matches(path, pattern):
    import re

    return re.compile(glob_to_regex(pattern)).match(path) is not None


def is_allowed(path, allowed):
    for pat in allowed:
        if matches(path, pat):
            return True
    return False


def load_allow_file(path):
    out = []
    with open(path, "r") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            out.append(line)
    return out


def check(cwd, baseline, allowed):
    changed = changed_files(cwd, baseline)
    violations = [p for p in changed if not is_allowed(p, allowed)]
    return changed, violations


def build_parser():
    p = argparse.ArgumentParser(
        prog="compound-v-scope-check.py",
        description="Git-derived scope gate for Compound V jobs.",
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--worktree", metavar="DIR", help="worktree mode root")
    mode.add_argument("--repo", metavar="DIR", help="direct mode repo root")
    p.add_argument(
        "--baseline",
        metavar="COMMIT",
        default=None,
        help="baseline commit/ref (default HEAD; required-ish for --repo)",
    )
    p.add_argument(
        "--allow",
        action="append",
        default=[],
        metavar="GLOB",
        help="an allowed write glob (repeatable)",
    )
    p.add_argument(
        "--allow-file",
        metavar="PATH",
        help="file of allowed globs, one per line (# comments ok)",
    )
    p.add_argument("--selftest", action="store_true", help="run built-in tests")
    return p


def main(argv):
    args = build_parser().parse_args(argv[1:])

    if args.worktree:
        cwd = args.worktree
        mode = "worktree"
        baseline = args.baseline or "HEAD"
    else:
        cwd = args.repo
        mode = "direct"
        baseline = args.baseline or "HEAD"

    if not os.path.isdir(cwd):
        print(
            json.dumps({"verdict": "error", "error": "not a directory: %s" % cwd}),
            file=sys.stderr,
        )
        return 2

    allowed = list(args.allow)
    if args.allow_file:
        allowed.extend(load_allow_file(args.allow_file))

    try:
        changed, violations = check(cwd, baseline, allowed)
    except RuntimeError as e:
        print(json.dumps({"verdict": "error", "error": str(e)}), file=sys.stderr)
        return 2

    verdict = "blocked" if violations else "pass"
    report = {
        "verdict": verdict,
        "mode": mode,
        "baseline": baseline,
        "changed": changed,
        "allowed": allowed,
        "violations": violations,
    }
    print(json.dumps(report, indent=2))
    if violations:
        print(
            "BLOCKED: %d file(s) written outside write_allowed:" % len(violations),
            file=sys.stderr,
        )
        for v in violations:
            print("  - %s" % v, file=sys.stderr)
        return 1
    return 0


# --------------------------------------------------------------------------- #
# Self-test (invoked with --selftest). Builds throwaway git repos in $TMPDIR.
# --------------------------------------------------------------------------- #
def _selftest():
    import tempfile
    import shutil

    failures = []

    def expect(name, cond):
        if cond:
            print("  ok   - %s" % name)
        else:
            print("  FAIL - %s" % name)
            failures.append(name)

    # --- glob unit tests (no git needed) ---
    cases = [
        ("src/a.ts", "src/*", True),
        ("src/sub/a.ts", "src/*", False),
        ("src/sub/a.ts", "src/**", True),
        ("src", "src/**", True),
        ("src/deep/x/y.tsx", "src/features/sequences/components/**", False),
        (
            "src/features/sequences/components/Editor.tsx",
            "src/features/sequences/components/**",
            True,
        ),
        ("db/migrations/001.sql", "db/migrations/*", True),
        ("README.md", "*.md", True),
        ("docs/x.md", "*.md", False),
        ("docs/x.md", "**/*.md", True),
        ("x.md", "**/*.md", True),
        ("a/b/c.md", "**/*.md", True),
        ("a.py", "**/*.md", False),
        ("a/c", "a/**/c", True),
        ("a/b/x/c", "a/**/c", True),
        ("scripts/compound-v-scope-check.py", "scripts/compound-v-scope-check.py", True),
        ("scripts/other.py", "scripts/compound-v-scope-check.py", False),
        ("src/x.tsx", "src/*.tsx", True),
        ("src/x.ts", "src/*.tsx", False),
    ]
    for path, pat, want in cases:
        got = matches(path, pat)
        expect("glob %r vs %r == %s" % (path, pat, want), got == want)

    # --- git integration tests ---
    tmp = tempfile.mkdtemp(prefix="cv-scope-selftest-")
    try:
        repo = os.path.join(tmp, "repo")
        os.makedirs(os.path.join(repo, "src"))
        os.makedirs(os.path.join(repo, "docs"))

        def run(args, cwd=repo):
            subprocess.run(
                args, cwd=cwd, check=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )

        run(["git", "init", "-q"])
        run(["git", "config", "user.email", "t@t.t"])
        run(["git", "config", "user.name", "t"])
        with open(os.path.join(repo, "src", "base.ts"), "w") as f:
            f.write("base\n")
        run(["git", "add", "-A"])
        run(["git", "commit", "-q", "-m", "base"])

        # GOOD case: modify an allowed file + add an allowed untracked file.
        with open(os.path.join(repo, "src", "base.ts"), "w") as f:
            f.write("base modified\n")
        with open(os.path.join(repo, "src", "extra.ts"), "w") as f:
            f.write("extra\n")
        changed, violations = check(repo, "HEAD", ["src/*"])
        expect(
            "good: changed detects both files",
            set(changed) == {"src/base.ts", "src/extra.ts"},
        )
        expect("good: no violations under src/*", violations == [])

        # BAD case: also touch a forbidden file outside write_allowed.
        with open(os.path.join(repo, "docs", "leak.md"), "w") as f:
            f.write("leak\n")
        changed, violations = check(repo, "HEAD", ["src/*"])
        expect("bad: docs/leak.md flagged as violation", violations == ["docs/leak.md"])

        # ** recursion BAD: nested file not matched by single-star glob.
        os.makedirs(os.path.join(repo, "src", "nested"))
        with open(os.path.join(repo, "src", "nested", "deep.ts"), "w") as f:
            f.write("deep\n")
        changed, violations = check(repo, "HEAD", ["src/*"])
        expect(
            "bad: src/nested/deep.ts violates src/* (single-star)",
            "src/nested/deep.ts" in violations,
        )

        # ** recursion GOOD: src/** allows the nested file.
        changed, violations = check(repo, "HEAD", ["src/**", "docs/*"])
        expect("good: src/** + docs/* clears all", violations == [])

        # worktree mode: create a worktree, change a file, gate it.
        wt = os.path.join(tmp, "wt")
        run(["git", "worktree", "add", "-q", wt, "HEAD"])
        with open(os.path.join(wt, "src", "wt_only.ts"), "w") as f:
            f.write("wt\n")
        changed, violations = check(wt, "HEAD", ["src/**"])
        expect("worktree: wt_only.ts detected", "src/wt_only.ts" in changed)
        expect("worktree: no violation under src/**", violations == [])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        print("\nSELFTEST FAILED: %d case(s)" % len(failures))
        return 1
    print("\nSELFTEST PASSED")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        sys.exit(_selftest())
    sys.exit(main(sys.argv))
