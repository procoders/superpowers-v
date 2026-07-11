#!/usr/bin/env python3
"""
Compound V scope gate — the git-diff authority behind SCOPE LOCK prose.

This is the deterministic enforcement script the dispatcher calls after EVERY
job, regardless of isolation. Prose SCOPE LOCK is advisory; this script decides.

What it does
------------
Computes the set of files a job actually changed, purely from git:

    changed = (git diff --name-only --no-renames -z <baseline>)
              ∪ (git ls-files --others --exclude-standard -z)
              ∪ (git ls-files --others --ignored --exclude-standard -z -- .)
              − (preexisting untracked/ignored snapshot, direct mode only)

All three probes use NUL-delimited (``-z``) output and are split on ``\0``, not
``\n`` — NUL is the only byte that cannot appear in a POSIX path, so a filename
containing a newline cannot smuggle additional paths past the gate.

The first term diffs the WORKING TREE against ``<baseline>`` — and because a
``git diff <baseline>`` includes anything COMMITTED since that baseline, a worker
that COMMITS inside its worktree to make the tree look clean is still caught (the
worker passes the pre-``worktree add`` baseline SHA, not a moving ``HEAD``).
``--no-renames`` keeps rename detection OFF: with detection on, ``git mv
docs/x.md src/y.md`` collapses to a single R-record whose ``--name-only`` output
is just the destination — the out-of-scope deletion of ``docs/x.md`` became
invisible and the gate passed. With ``--no-renames`` both sides surface (a
delete + an add), so the out-of-scope source path is a violation again.

The third term catches GITIGNORED writes — a worker writing a gitignored path
(dist/, .env, build/) would otherwise be invisible to the gate.

Escaping-symlink scan
---------------------
On top of the git-derived set, the verdict path scans the WHOLE gate root
(``os.walk`` with ``followlinks=False`` — symlinks only, so it stays cheap) for
any symlink whose ``os.path.realpath`` resolves OUTSIDE the root. Each such link
is reported as a violation ``"<path> (symlink escapes the worktree)"`` —
regardless of ``write_allowed`` and regardless of who created it. That covers
BOTH a job-created escaping symlink AND a pre-existing one (committed before the
baseline): a write through either lands outside the tree where git sees nothing,
so the only reliable gate-time signal is the link itself. A directory the walk
CANNOT READ is itself a violation ("unreadable during symlink scan") — loud and
conservative, because chmod-000 on a dir would otherwise hide a link inside it;
only individual entries that vanish mid-scan are skipped.

HONESTY: the gate DETECTS the escaping-symlink channel; it cannot observe writes
already made through it — by the time the gate runs, a byte written through such
a link is outside the tree and outside git's view. Kernel-level write confinement
(the codex backend's sandbox) is the preventive layer; this scan is the
detection layer.

The optional ``--preexisting`` subtraction (direct mode) drops paths that were
ALREADY untracked/ignored before the job started, so a normal dirty tree does not
produce false BLOCKs for files this job never touched.

then matches each changed path against the job's ``write_allowed`` glob list.
Any changed file that matches NO allowed glob is a violation. One or more
violations ⇒ BLOCKED (non-zero exit). A BLOCKED job must never be merged.

Two modes (mutually exclusive)
------------------------------
* worktree mode (``--worktree <dir>``): run git inside the worktree
  (``git -C <dir> ...``). Baseline defaults to ``HEAD`` (the commit the worktree
  was created at) unless ``--baseline`` is given.
* direct mode (``--repo <dir> --baseline <commit>``): run git inside the repo,
  diffing against an explicit pre-dispatch baseline commit/ref. ``--baseline`` is
  REQUIRED here — a direct job's baseline must be the recorded pre-dispatch
  commit, never a defaulted (and possibly-moved) HEAD.

``write_allowed`` source
------------------------
Either repeated ``--allow <glob>`` flags, or ``--allow-file <path>`` (one glob
per line, ``#`` comments and blanks ignored), or both (unioned).

Glob semantics (fnmatch-like, with ``**``)
------------------------------------------
* ``*``   matches within a single path segment (not ``/``).
* ``**``  matches across segments, including ``/`` (recursive).
* ``dir/**`` also matches ``dir`` itself and everything beneath it.
* ``?``   matches one non-``/`` character.
* ``[`` and ``]`` are LITERAL. fnmatch character classes are deliberately NOT
  supported: bracketed path segments are the norm in modern frameworks
  (Next.js ``app/[locale]/[uid]/page.tsx``, SvelteKit ``[slug]``), and a
  char-class reading turns those allow-globs into false BLOCKED verdicts.
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
import errno
import json
import os
import stat
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


def _split_nul(blob):
    """Split git ``-z`` (NUL-delimited) output into paths.

    NUL is the one byte that cannot appear in a POSIX path, so splitting on it —
    instead of on newlines — means a filename containing a literal newline cannot
    smuggle extra paths past the gate. Each record is a complete path; we keep it
    verbatim (no strip) except for dropping empty trailing records.
    """
    out = []
    for rec in blob.split("\0"):
        if rec:
            out.append(rec)
    return out


def changed_files(cwd, baseline, preexisting=None):
    """Union of tracked-diff, untracked, AND gitignored files, repo-relative.

    Three sources, because a worker can write outside write_allowed in any of them:
      1. tracked edits        — git diff --name-only --no-renames <baseline>
      2. untracked new files  — git ls-files --others --exclude-standard
      3. IGNORED new files     — git ls-files --others --ignored --exclude-standard
    Source 1 diffs the working tree against ``baseline``; because it also includes
    anything COMMITTED since that baseline, a worker that commits inside its worktree
    to fake a clean tree is still detected (the caller passes the pre-``worktree add``
    baseline SHA, never a moving HEAD). ``--no-renames`` is load-bearing: with git's
    default rename detection, a rename collapses to its DESTINATION path in
    ``--name-only`` output, hiding the out-of-scope source — ``git mv`` out of the
    allowed area would slip the gate. Detection off ⇒ both the deleted source and
    the added destination surface, and each is matched against write_allowed.
    Source 3 is the one the old gate MISSED: --exclude-standard drops gitignored
    paths, so a worker could write a gitignored file (e.g. dist/, .env, build/)
    completely undetected. We union it in so any ignored write outside write_allowed
    is reported as a violation.

    ``preexisting`` (optional set/iterable of repo-relative paths) is SUBTRACTED
    from the union: in direct mode the dispatcher snapshots untracked/ignored paths
    that existed BEFORE the job, so files this job never created are not attributed
    to it. (Worktree mode passes nothing — a fresh ``worktree add HEAD`` has no
    pre-existing untracked.) Result is deduped/sorted, repo-relative.
    """
    # All three probes use NUL-delimited (-z) output, split on '\0'. NUL is the
    # only byte that cannot occur in a path, so a filename containing a newline
    # (or other whitespace) cannot smuggle additional paths past the gate.
    rc1, diff_out, diff_err = _git(
        cwd, ["diff", "--name-only", "--no-renames", "-z", baseline]
    )
    if rc1 != 0:
        raise RuntimeError(
            "git diff failed (baseline %r): %s" % (baseline, diff_err.strip())
        )
    rc2, oth_out, oth_err = _git(
        cwd, ["ls-files", "--others", "--exclude-standard", "-z"]
    )
    if rc2 != 0:
        raise RuntimeError("git ls-files failed: %s" % oth_err.strip())
    # Ignored untracked files. Needs an explicit pathspec ('-- .') so git lists
    # ignored paths under the tree rather than nothing.
    rc3, ign_out, ign_err = _git(
        cwd,
        ["ls-files", "--others", "--ignored", "--exclude-standard", "-z", "--", "."],
    )
    if rc3 != 0:
        raise RuntimeError("git ls-files (ignored) failed: %s" % ign_err.strip())

    files = (
        set(_split_nul(diff_out))
        | set(_split_nul(oth_out))
        | set(_split_nul(ign_out))
    )
    if preexisting:
        files -= set(preexisting)
    return sorted(files)


def glob_to_regex(pattern):
    """
    Translate a path glob (with ``**``) into a fully-anchored regex string.

    Hand-rolled rather than fnmatch.translate so that ``*`` does NOT cross ``/``
    while ``**`` does. ``dir/**`` also matches ``dir`` itself. ``[`` / ``]``
    are literal (no character classes) so App-Router segments like
    ``app/[locale]`` match their real on-disk paths.
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
        # NOTE: '[' / ']' fall through to the literal branch below on purpose —
        # treating them as fnmatch char classes made `app/[locale]/**` match
        # "one char of {l,o,c,a,e}" instead of the real Next.js directory and
        # produced false BLOCKED verdicts (plus a regex FutureWarning).
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


def load_preexisting_file(path):
    """Read a snapshot of pre-existing repo-relative paths (one per line)."""
    out = []
    with open(path, "r") as fh:
        for raw in fh:
            line = raw.strip()
            if line:
                out.append(line)
    return out


def scan_escaping_symlinks(root):
    """Return LABELED violation strings: escaping symlinks under ``root``, plus
    directories the scan could not read (loud-conservative — an unreadable dir
    could hide an escaping link).

    Scans the WHOLE gate root (not just git-changed paths): a PRE-EXISTING escaping
    symlink — committed before the baseline, with no new changes at all — is just as
    writable-through as a job-created one, and git shows nothing for either write.
    The link itself is the only reliable gate-time signal, so every escaping link is
    a violation regardless of write_allowed or provenance.

    ``os.walk(followlinks=False)`` never descends through links; only ``islink``
    entries pay a ``realpath``, so the scan stays cheap. ``.git`` is pruned (its
    internals are git's own, and packed refs etc. are not job writes). Entries that
    error on ``islink``/``realpath`` (unreadable, vanished mid-scan) are skipped —
    degrade-safe: an unreadable entry can make the scan miss a link, never crash
    the gate.

    DETECTION, not prevention: a write already made through an escaping link landed
    outside the tree before the gate ran and cannot be observed here. Kernel-level
    confinement (the codex backend's sandbox) is the preventive layer.
    """
    escapes = []
    unreadable = []
    root_real = os.path.realpath(root)
    prefix = root_real.rstrip(os.sep) + os.sep

    def _escaping(p):
        # Classify by errno, NOT via os.path.islink — os.path.islink internally
        # SWALLOWS OSError and returns False, so a 0400 (readable-but-not-
        # searchable) parent dir makes islink() report "not a link" for a real
        # escaping symlink inside it → false-PASS (Codex v2.8 round-4). os.lstat
        # RAISES instead, letting us tell the cases apart:
        #   ENOENT (vanished mid-scan)       -> genuinely gone, skip
        #   EACCES/EPERM (permission denied) -> real but unresolvable link; LOUD
        try:
            st = os.lstat(p)
        except OSError as e:
            if e.errno == errno.ENOENT:
                return False  # vanished — degrade-safe skip
            unreadable.append(os.path.relpath(p, root))
            return False  # counted as unreadable, never a clean pass
        if not stat.S_ISLNK(st.st_mode):
            return False
        try:
            target = os.path.realpath(p)
        except OSError as e:
            if e.errno == errno.ENOENT:
                return False
            unreadable.append(os.path.relpath(p, root))
            return False
        return target != root_real and not target.startswith(prefix)

    root_norm = os.path.normpath(root)

    def _on_walk_error(err):
        # An unreadable directory could HIDE an escaping link (worker: create
        # link inside, then chmod 000 the dir — Codex v2.8 round-3). Loud and
        # conservative: unreadable ⇒ violation, never a silent skip.
        p = getattr(err, "filename", None) or root
        unreadable.append(os.path.relpath(p, root))

    for dirpath, dirnames, filenames in os.walk(
        root, followlinks=False, onerror=_on_walk_error
    ):
        # CLASSIFY .git BEFORE pruning: a nested entry NAMED ".git" that is an
        # escaping SYMLINK is itself a violation (git treats .git specially, so
        # git-derived detection is blind here). Prune ONLY the ROOT's own real
        # .git (git's internals) — a NESTED real .git directory is job-created
        # content that git ignores entirely, so it must be DESCENDED into: an
        # escaping link hidden inside it is invisible to every other signal
        # (Codex v2.8 round-2 #1).
        if ".git" in dirnames:
            if _escaping(os.path.join(dirpath, ".git")):
                escapes.append(os.path.relpath(os.path.join(dirpath, ".git"), root))
                dirnames.remove(".git")  # never descend THROUGH a link
            elif os.path.normpath(dirpath) == root_norm:
                dirnames.remove(".git")  # the repo/worktree's own metadata dir
        for name in dirnames + filenames:
            p = os.path.join(dirpath, name)
            if _escaping(p):
                escapes.append(os.path.relpath(p, root))
    return sorted(
        ["%s (symlink escapes the worktree)" % p for p in escapes]
        + [
            "%s (unreadable during symlink scan — cannot rule out an escaping link)" % p
            for p in unreadable
        ]
    )


def check(cwd, baseline, allowed, preexisting=None):
    changed = changed_files(cwd, baseline, preexisting=preexisting)
    violations = [p for p in changed if not is_allowed(p, allowed)]
    # Escaping symlinks are violations unconditionally — even inside the allowed
    # area, even pre-existing: the link is a write channel out of the tree.
    violations.extend(scan_escaping_symlinks(cwd))
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
        help="baseline commit/ref. In --worktree mode defaults to HEAD (the "
        "worktree is fresh from HEAD). REQUIRED in --repo (direct) mode: a "
        "direct job's baseline must be the recorded pre-dispatch commit, not "
        "whatever HEAD happens to be now.",
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
    p.add_argument(
        "--preexisting",
        metavar="PATH",
        help="file of repo-relative paths (one per line) that existed BEFORE the "
        "job (untracked/ignored snapshot); these are EXCLUDED from the changed/"
        "violation set. Direct mode: the dispatcher snapshots pre-existing "
        "untracked+ignored paths before launch and passes them here so a normal "
        "dirty tree does not produce false BLOCKs.",
    )
    p.add_argument("--selftest", action="store_true", help="run built-in tests")
    return p


def main(argv):
    args = build_parser().parse_args(argv[1:])

    if args.worktree:
        cwd = args.worktree
        mode = "worktree"
        # Worktrees are created fresh from HEAD, so HEAD is the correct baseline.
        baseline = args.baseline or "HEAD"
    else:
        cwd = args.repo
        mode = "direct"
        # Direct mode REQUIRES an explicit baseline: it must be the recorded
        # pre-dispatch commit, never a defaulted HEAD (which may have moved and
        # would silently hide a job's writes against the wrong reference).
        if not args.baseline:
            print(
                json.dumps(
                    {
                        "verdict": "error",
                        "error": "--baseline is required in --repo (direct) mode "
                        "(must be the recorded pre-dispatch commit)",
                    }
                ),
                file=sys.stderr,
            )
            return 2
        baseline = args.baseline

    if not os.path.isdir(cwd):
        print(
            json.dumps({"verdict": "error", "error": "not a directory: %s" % cwd}),
            file=sys.stderr,
        )
        return 2

    allowed = list(args.allow)
    if args.allow_file:
        allowed.extend(load_allow_file(args.allow_file))

    preexisting = None
    if args.preexisting:
        preexisting = load_preexisting_file(args.preexisting)

    try:
        changed, violations = check(cwd, baseline, allowed, preexisting=preexisting)
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
        # Bracketed dynamic-route segments are LITERAL (Next.js App Router):
        ("app/[locale]/x/[uid]/page.tsx", "app/[locale]/x/**", True),
        ("app/[locale]/compound-v/result/[uid]/opengraph-image.tsx",
         "app/[locale]/compound-v/result/**", True),
        ("app/l/x/page.tsx", "app/[locale]/x/**", False),
        ("app/[locale]/page.tsx", "app/[locale]/page.tsx", True),
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

        # COMMITTED-INSIDE-WORKTREE case: a worker that COMMITS a forbidden file
        # inside its worktree makes `git diff HEAD` look clean — but the gate
        # baselines against the pre-`worktree add` SHA, so `git diff <sha>` still
        # includes the committed change and BLOCKS it. Capture the worktree's
        # baseline SHA, commit a forbidden file inside the worktree, and verify the
        # gate (baselined at that SHA) still flags it.
        wt2 = os.path.join(tmp, "wt2")
        run(["git", "worktree", "add", "-q", wt2, "HEAD"])
        base_sha = subprocess.run(
            ["git", "-C", wt2, "rev-parse", "HEAD"],
            stdout=subprocess.PIPE, universal_newlines=True, check=True,
        ).stdout.strip()
        os.makedirs(os.path.join(wt2, "docs"))
        with open(os.path.join(wt2, "docs", "committed_leak.md"), "w") as f:
            f.write("leak via commit\n")
        run(["git", "add", "-A"], cwd=wt2)
        run(["git", "commit", "-q", "-m", "sneaky commit inside worktree"], cwd=wt2)
        # `git diff HEAD` now sees NOTHING (the commit moved HEAD), so a HEAD-baselined
        # gate would falsely PASS. The SHA-baselined gate must still detect + block it.
        changed_head, _ = check(wt2, "HEAD", ["src/**"])
        expect(
            "committed: HEAD-baseline would MISS the committed leak (clean tree)",
            "docs/committed_leak.md" not in changed_head,
        )
        changed_sha, viol_sha = check(wt2, base_sha, ["src/**"])
        expect(
            "committed: baseline-SHA detects the committed-inside-worktree file",
            "docs/committed_leak.md" in changed_sha,
        )
        expect(
            "committed: committed file outside write_allowed BLOCKS",
            "docs/committed_leak.md" in viol_sha,
        )

        # PRE-EXISTING (direct mode) case: a file untracked BEFORE the job (passed
        # via --preexisting) must NOT be flagged, while a NEW untracked file outside
        # write_allowed still BLOCKS. Use the first repo (direct-style check).
        with open(os.path.join(repo, "docs", "preexisting.md"), "w") as f:
            f.write("was here before the job\n")
        with open(os.path.join(repo, "docs", "new_leak.md"), "w") as f:
            f.write("created by the job\n")
        # Without the snapshot: BOTH untracked docs files are flagged.
        _, viol_no_snap = check(repo, "HEAD", ["src/**"])
        expect(
            "preexisting: without snapshot both docs files flagged",
            "docs/preexisting.md" in viol_no_snap and "docs/new_leak.md" in viol_no_snap,
        )
        # With the snapshot listing the pre-existing file: it is excluded; the new
        # file outside write_allowed still BLOCKS.
        changed_snap, viol_snap = check(
            repo, "HEAD", ["src/**"], preexisting=["docs/preexisting.md"]
        )
        expect(
            "preexisting: snapshotted file NOT flagged",
            "docs/preexisting.md" not in changed_snap
            and "docs/preexisting.md" not in viol_snap,
        )
        expect(
            "preexisting: new file outside write_allowed still BLOCKS",
            "docs/new_leak.md" in viol_snap,
        )

        # IGNORED-FILE case: a worker writes a gitignored path OUTSIDE
        # write_allowed. --exclude-standard would hide it, so the gate must union
        # in `--others --ignored` and BLOCK on it. Set up a fresh repo with a
        # .gitignore so the write lands in an ignored path.
        irepo = os.path.join(tmp, "irepo")
        os.makedirs(os.path.join(irepo, "src"))
        run(["git", "init", "-q"], cwd=irepo)
        run(["git", "config", "user.email", "t@t.t"], cwd=irepo)
        run(["git", "config", "user.name", "t"], cwd=irepo)
        with open(os.path.join(irepo, ".gitignore"), "w") as f:
            f.write("dist/\n.env\n")
        with open(os.path.join(irepo, "src", "base.ts"), "w") as f:
            f.write("base\n")
        run(["git", "add", "-A"], cwd=irepo)
        run(["git", "commit", "-q", "-m", "base"], cwd=irepo)
        # Worker writes a GITIGNORED build artifact outside write_allowed.
        os.makedirs(os.path.join(irepo, "dist"))
        with open(os.path.join(irepo, "dist", "leak.js"), "w") as f:
            f.write("leaked\n")
        changed, violations = check(irepo, "HEAD", ["src/**"])
        expect(
            "ignored: dist/leak.js detected despite .gitignore",
            "dist/leak.js" in changed,
        )
        expect(
            "ignored: dist/leak.js BLOCKS (violation outside write_allowed)",
            "dist/leak.js" in violations,
        )

        # UNUSUAL-FILENAME case: with NUL-delimited (-z) parsing, a path with a
        # space — and (where the OS allows) a literal newline — is attributed as a
        # SINGLE path, not split into phantom paths. A newline-containing name on a
        # line-split parser would smuggle the second half past the gate; the -z gate
        # must keep it intact and attribute it correctly.
        nrepo = os.path.join(tmp, "nrepo")
        os.makedirs(os.path.join(nrepo, "src"))
        run(["git", "init", "-q"], cwd=nrepo)
        run(["git", "config", "user.email", "t@t.t"], cwd=nrepo)
        run(["git", "config", "user.name", "t"], cwd=nrepo)
        with open(os.path.join(nrepo, "src", "base.ts"), "w") as f:
            f.write("base\n")
        run(["git", "add", "-A"], cwd=nrepo)
        run(["git", "commit", "-q", "-m", "base"], cwd=nrepo)
        # A file with a space in the name, OUTSIDE write_allowed → must BLOCK as one path.
        with open(os.path.join(nrepo, "docs with space.md"), "w") as f:
            f.write("space\n")
        changed_sp, viol_sp = check(nrepo, "HEAD", ["src/**"])
        expect(
            "unusual: 'docs with space.md' attributed as one path",
            "docs with space.md" in changed_sp,
        )
        expect(
            "unusual: spaced filename BLOCKS (outside write_allowed)",
            "docs with space.md" in viol_sp,
        )
        # A file whose name contains a literal newline (best-effort: skip if the
        # filesystem rejects it). The whole name must be ONE changed path, and the
        # text after the newline must NOT appear as a separate phantom path.
        nl_name = "weird\nname.md"
        try:
            with open(os.path.join(nrepo, nl_name), "w") as f:
                f.write("nl\n")
            created_nl = True
        except (OSError, ValueError):
            created_nl = False
        if created_nl:
            changed_nl, viol_nl = check(nrepo, "HEAD", ["src/**"])
            expect(
                "unusual: newline filename kept intact as one path",
                nl_name in changed_nl,
            )
            expect(
                "unusual: newline filename does not split into a phantom path",
                "name.md" not in changed_nl,
            )
            expect(
                "unusual: newline filename BLOCKS (outside write_allowed)",
                nl_name in viol_nl,
            )
        else:
            expect("unusual: newline filename (skipped — FS rejected name)", True)

        # RENAME-OUT-OF-SCOPE case (A1): with git's default rename detection, a
        # `git mv docs/important.md src/renamed.md` collapses to its DESTINATION in
        # --name-only output — the out-of-scope deletion of docs/important.md was
        # invisible and the gate PASSED (reproduced exploit). --no-renames makes
        # both sides surface; the old path must be listed and must BLOCK.
        rrepo = os.path.join(tmp, "rrepo")
        os.makedirs(os.path.join(rrepo, "src"))
        os.makedirs(os.path.join(rrepo, "docs"))
        run(["git", "init", "-q"], cwd=rrepo)
        run(["git", "config", "user.email", "t@t.t"], cwd=rrepo)
        run(["git", "config", "user.name", "t"], cwd=rrepo)
        with open(os.path.join(rrepo, "src", "base.ts"), "w") as f:
            f.write("base\n")
        with open(os.path.join(rrepo, "docs", "important.md"), "w") as f:
            f.write("do not move me\n")
        run(["git", "add", "-A"], cwd=rrepo)
        run(["git", "commit", "-q", "-m", "base"], cwd=rrepo)
        run(["git", "mv", "docs/important.md", "src/renamed.md"], cwd=rrepo)
        changed_rn, viol_rn = check(rrepo, "HEAD", ["src/**"])
        expect(
            "rename: out-of-scope source docs/important.md surfaces in changed",
            "docs/important.md" in changed_rn,
        )
        expect(
            "rename: out-of-scope rename source BLOCKS (old path listed)",
            "docs/important.md" in viol_rn,
        )
        expect(
            "rename: in-scope destination src/renamed.md is not a violation",
            "src/renamed.md" in changed_rn and "src/renamed.md" not in viol_rn,
        )

        # JOB-CREATED ESCAPING SYMLINK case (A2): a symlink INSIDE the allowed
        # area pointing OUTSIDE the gate root is a write channel out of the tree —
        # glob-matching the link's own path said PASS (reproduced exploit). The
        # whole-root symlink scan must BLOCK it; an in-root symlink must not trip.
        srepo = os.path.join(tmp, "srepo")
        os.makedirs(os.path.join(srepo, "src"))
        run(["git", "init", "-q"], cwd=srepo)
        run(["git", "config", "user.email", "t@t.t"], cwd=srepo)
        run(["git", "config", "user.name", "t"], cwd=srepo)
        with open(os.path.join(srepo, "src", "base.ts"), "w") as f:
            f.write("base\n")
        run(["git", "add", "-A"], cwd=srepo)
        run(["git", "commit", "-q", "-m", "base"], cwd=srepo)
        outside_dir = os.path.join(tmp, "outside-target")
        if not os.path.isdir(outside_dir):
            os.makedirs(outside_dir)
        os.symlink(outside_dir, os.path.join(srepo, "src", "escape"))
        os.symlink("base.ts", os.path.join(srepo, "src", "inside_link"))
        changed_sl, viol_sl = check(srepo, "HEAD", ["src/**"])
        expect(
            "symlink: job-created escaping link BLOCKS despite matching src/**",
            "src/escape (symlink escapes the worktree)" in viol_sl,
        )
        expect(
            "symlink: in-root relative link is NOT flagged",
            not any(v.startswith("src/inside_link") for v in viol_sl),
        )

        # PRE-EXISTING ESCAPING SYMLINK case (A2): the link was COMMITTED before
        # the baseline and the job changed NOTHING — git reports an empty diff, so
        # only the whole-root scan can see the open channel. Must still BLOCK.
        perepo = os.path.join(tmp, "perepo")
        os.makedirs(os.path.join(perepo, "src"))
        run(["git", "init", "-q"], cwd=perepo)
        run(["git", "config", "user.email", "t@t.t"], cwd=perepo)
        run(["git", "config", "user.name", "t"], cwd=perepo)
        with open(os.path.join(perepo, "src", "base.ts"), "w") as f:
            f.write("base\n")
        os.symlink(outside_dir, os.path.join(perepo, "src", "pre_escape"))
        run(["git", "add", "-A"], cwd=perepo)
        run(["git", "commit", "-q", "-m", "base with escaping symlink"], cwd=perepo)
        changed_pe, viol_pe = check(perepo, "HEAD", ["src/**"])
        expect(
            "symlink: pre-existing (committed) escaping link — git diff is empty",
            changed_pe == [],
        )
        expect(
            "symlink: pre-existing escaping link still BLOCKS",
            "src/pre_escape (symlink escapes the worktree)" in viol_pe,
        )

        # NESTED .git-NAMED ESCAPING SYMLINK (Codex v2.8 round-1 #1): a directory
        # symlink NAMED ".git" nested in the tree used to be pruned from the walk
        # BEFORE the islink test — invisible. Git also treats .git specially, so
        # git-derived detection is blind here. Both job-created and pre-existing
        # variants must BLOCK; the repo root's own real .git must NOT be flagged.
        os.makedirs(os.path.join(srepo, "src", "vendor"))
        os.symlink(outside_dir, os.path.join(srepo, "src", "vendor", ".git"))
        _, viol_gl = check(srepo, "HEAD", ["src/**"])
        expect(
            "symlink: nested .git-named escaping link BLOCKS (job-created)",
            "src/vendor/.git (symlink escapes the worktree)" in viol_gl,
        )
        expect(
            "symlink: the real root .git is NOT flagged",
            not any(v.startswith(".git ") for v in viol_gl),
        )
        # git REFUSES to track any path with a ".git" component (verified: `git add`
        # fails) — so this channel is permanently invisible to every git-derived signal,
        # including ls-files --others. Only the FS scan can see it: create it
        # UNTRACKED (as a leftover from a prior job / base image would be).
        os.makedirs(os.path.join(perepo, "sub"))
        os.symlink(outside_dir, os.path.join(perepo, "sub", ".git"))
        _, viol_gp = check(perepo, "HEAD", ["src/**", "sub/**"])
        expect(
            "symlink: nested .git-named escaping link BLOCKS (untracked leftover)",
            "sub/.git (symlink escapes the worktree)" in viol_gp,
        )

        # NESTED REAL .git DIRECTORY hiding an escaping link INSIDE it (Codex
        # v2.8 round-2 #1): only the ROOT's own .git is pruned; a job-created
        # real directory named .git is descended into — git ignores everything
        # under any .git path, so the FS scan is again the only detector.
        os.makedirs(os.path.join(perepo, "deep", ".git"))
        os.symlink(outside_dir, os.path.join(perepo, "deep", ".git", "out"))
        _, viol_gd = check(perepo, "HEAD", ["src/**", "sub/**", "deep/**"])
        expect(
            "symlink: escaping link INSIDE a nested real .git dir BLOCKS",
            "deep/.git/out (symlink escapes the worktree)" in viol_gd,
        )
        expect(
            "symlink: root's own real .git still not scanned/flagged",
            not any(v.startswith(".git") for v in viol_gd),
        )

        # UNREADABLE DIRECTORY (Codex v2.8 round-3): create a link inside a dir,
        # chmod 000 the dir — the walk cannot see the link, so the unreadable
        # dir ITSELF must be a loud violation, never a silent skip.
        hidden = os.path.join(perepo, "hidden")
        os.makedirs(hidden)
        os.symlink(outside_dir, os.path.join(hidden, "sneak"))
        os.chmod(hidden, 0)
        try:
            _, viol_ur = check(perepo, "HEAD", ["src/**", "sub/**", "deep/**", "hidden/**"])
            expect(
                "symlink: chmod-000 dir is a loud violation (cannot rule out a link)",
                any("hidden" in v and "unreadable during symlink scan" in v for v in viol_ur),
            )
        finally:
            os.chmod(hidden, 0o700)  # restore so rmtree cleanup works

        # 0400 (readable but NOT searchable) dir: os.walk enumerates children,
        # but islink() on each child fails EACCES — the round-3 onerror never
        # fires. _escaping must count that child as unreadable, not a clean pass
        # (Codex v2.8 round-4 false-PASS).
        nx = os.path.join(perepo, "noexec")
        os.makedirs(nx)
        os.symlink(outside_dir, os.path.join(nx, "sneak"))
        os.chmod(nx, 0o400)
        try:
            _, viol_nx = check(perepo, "HEAD",
                               ["src/**", "sub/**", "deep/**", "hidden/**", "noexec/**"])
            expect(
                "symlink: 0400 non-searchable dir surfaces as unreadable (no false PASS)",
                any("noexec" in v and "unreadable during symlink scan" in v for v in viol_nx),
            )
        finally:
            os.chmod(nx, 0o700)
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
