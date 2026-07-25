#!/usr/bin/env python3
"""
Compound V — co-change advisory (v2.17 Feature A).

The **inverse of the scope gate**. The scope gate answers *"did a worker write OUTSIDE
its lane?"* — containment. This answers the opposite, equally real failure: *"does a
partition cover file A but FORGET partner file B, which our own git history says almost
always moves with it?"*

Two subcommands, both **git-derived with ZERO model involvement**:

``rules``
    Mine **ORDERED** rules ``A -> B`` (never a symmetric pair — the question is "A is in
    the partition, is B missing?", which is directional; requiring the reverse direction
    suppresses exactly the asymmetric couplings that matter). A rule fires only when ALL
    four hold:

    ===========================  =======  ===================================================
    joint support                >= 8     a handful of co-occurrences is not a rule
    point rate ``P(B|A)``        >= 0.70  the rule must usually hold
    95% Wilson **lower bound**   >= 0.50  guards small-sample luck: 8/11 *looks* like 0.73
                                          but its lower bound is 0.43
    **narrow** support           >= 3     at least three co-changes in NON-release,
                                          NON-format commits touching <= 10 files — a pair
                                          that only ever co-occurs inside a wide release
                                          commit is an artifact of the release, not a
                                          coupling
    ===========================  =======  ===================================================

    NORMAL output contains **only firing rules**. Sub-threshold candidates are silent —
    never surfaced with a hedge. ``--explain-rejections`` is a diagnostic mode (which
    ``check`` never invokes and never consumes) that additionally reports candidates
    which cleared ``--min-support`` but failed a later gate, with the reason.

``check``
    Given the manifest (or an explicit **glob** list), report partners that are missing
    from the union of every job's ``write_allowed``. It takes GLOBS, never a literal file
    list: ``write_allowed`` holds patterns like ``scripts/**``, so a literal list would
    miss every antecedent covered by a pattern and shell expansion would additionally
    miss files that do not exist yet. **Exit status is 0 whether or not findings exist**
    — a non-zero exit is reserved strictly for an operational error (git failed, bad
    arguments). A finding is data, never a failure signal; that is what structurally
    prevents a caller from turning this advisory into a gate.

Honesty contract (anti-ruflo):

* **Counts and measured frequencies ONLY** — no fabricated "risk score", no confidence %.
* **An incomplete scan is never a clean scan.** If git output was byte-capped, or the
  history is too short to clear the support bar, the result is ``complete: false`` with a
  ``scan_incomplete`` / ``insufficient_history`` reason and **no rules at all**. Dropping
  a truncated trailing line repairs syntax, not missing commits, and biased support /
  Wilson values presented as complete would be exactly the fabricated-evidence failure
  this project exists to prevent. A caller must be able to tell "no missing partners"
  apart from "we could not tell".
* **A non-zero git exit is SURFACED**, never flattened into "no rules".
* **Every output carries provenance**: ``head_sha``, the exact ``since``/``until`` bounds,
  the eligible-commit count and the active filter configuration.
* **Declared portability limit.** ``--narrow-max-files 10`` is calibrated on this repo's
  commit shape (largest commit 33 files). A young repo, a squash-merge-only history or a
  wide monorepo will legitimately produce **no** rules — which surfaces as
  ``insufficient_history``, never as a clean bill of health. Thresholds are deliberately
  NOT repo-tunable in v1: fitting a knob to an imagined shape before a second repo's data
  exists is worse than a declared limit.

IMPORT, never fork (CONVENTIONS.md: reuse canonical shared constants/helpers):

* ``compound_v_churn._run_git`` — the shared process-group timeout supervisor wrapper.
  Every git call goes through it (``stdin=DEVNULL``, byte-capped stdout, SIGKILL'd as a
  group on timeout). This module NEVER calls ``subprocess.run(timeout=...)`` on git.
* ``compound_v_churn.load_churn_config`` (single-sourced excludes — on THIS repo that
  resolves to zero exclusions, because ``.claude/`` holds only the ``.example`` taxonomy
  and the loader refuses that fallback by design; the contract is honored for downstream
  repos), plus ``_compile_format_patterns`` / ``_is_format_subject``.
* ``compound_v_taxonomy.glob_match`` — a third copy of a path-glob matcher is precisely
  what CONVENTIONS.md forbids.

Because ``load_churn_config`` returns **empty** format patterns when no real taxonomy is
present, an imported matcher fed only that list would reject **nothing**. This module
therefore ships a **tested built-in default** release/version/format subject pattern set
(``DEFAULT_SUBJECT_PATTERNS``) that is **unioned** with any taxonomy-supplied patterns.

Git contract, every branch decided explicitly:

* ``git log --no-merges -M --name-only``. **``-M`` is for HERMETICITY, not a live bug
  fix**: bare ``git log --name-only`` already resolves renames (``diff.renames`` has
  defaulted true since git 2.9 and is unset here), so ``-M`` and no flag behave
  identically on this repo — only an explicit ``--no-renames`` produces the two-path
  artifact. We pass ``-M`` so the result is immune to a repo that sets
  ``diff.renames=false``. A below-50%-similarity move is NOT unified by ``-M``; that is a
  documented limit, covered by the selftest.
* The ``capped`` truncation flag is honored (truncated trailing line dropped) AND turns
  the whole scan incomplete.
* Partners that no longer exist at HEAD are filtered, or ``check`` would name a deleted
  file forever.

No cache, no cache file, no committed artifact: a full scan of this repo's history is
sub-second, so v1 computes on demand.

Python 3.9-safe, stdlib only. Deterministic JSON (``indent=2, sort_keys=True,
ensure_ascii=True`` + trailing newline).

Usage:
    compound-v-cochange.py rules [--repo DIR] [--since DATE] [--until DATE]
                                 [--min-support 8] [--min-rate 0.70] [--min-wilson 0.50]
                                 [--min-narrow 3] [--narrow-max-files 10] [--max-files 200]
                                 [--explain-rejections]
    compound-v-cochange.py check [--repo DIR] (--manifest PATH | --patterns GLOB [GLOB ...])
                                 [--since DATE] ...
    compound-v-cochange.py --selftest
"""

import argparse
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

TOOL_ID = "cochange-v1"

# Thresholds — the r6 spec pins these; they are NOT repo-tunable in v1 (declared limit).
DEFAULT_MIN_SUPPORT = 8
DEFAULT_MIN_RATE = 0.70
DEFAULT_MIN_WILSON = 0.50
DEFAULT_MIN_NARROW = 3
DEFAULT_NARROW_MAX_FILES = 10

# Pair-explosion guard: a commit touching more than this many files is a mechanical bulk
# operation, not evidence of coupling, and would contribute O(n^2) meaningless pairs. It
# drops 0 of this repo's real commits (largest is 33 files), so only a fixture can
# exercise it. Dropped commits are REPORTED in provenance, never silently swallowed.
DEFAULT_MAX_FILES = 200

# 97.5th percentile of the standard normal => a 95% two-sided Wilson interval.
WILSON_Z = 1.959963984540054

# Built-in release/version/format subject defaults. `_is_format_subject` uses `search`,
# so each is explicitly anchored with `^`; `(?i)` is inline (leading) so the imported
# `_compile_format_patterns` — a plain `re.compile` — honors case-insensitivity.
#
# Calibrated and TESTED against this repo's real subjects: they match
# "release(z1): v2.14.1 ...", "chore(release): ...", "v0.1.3: rename marketplace ..." and
# NOT "fix(scope-gate): ... release lockstep 2.8.0", "docs(v1.1): release-gate audit ...",
# "feat(v2.9): Z1 ... bump ...", "Initial release: Compound V ..." — an unanchored
# "release"/"bump" match would have wrongly swallowed those four.
DEFAULT_SUBJECT_PATTERNS = [
    r"(?i)^\s*release\b",
    r"(?i)^\s*(?:chore|build|ci|docs|deploy)\s*\(\s*release\s*\)",
    r"(?i)^\s*(?:chore|build|ci)\s*:\s*release\b",
    r"(?i)^\s*v?\d+\.\d+\.\d+",
    r"(?i)^\s*(?:chore|build|ci)\s*\(\s*(?:version|bump)\s*\)",
    r"(?i)^\s*bump\s+version\b",
    r"(?i)^\s*style\b",
    r"(?i)^\s*(?:re)?format\b",
    r"(?i)^\s*lint\b",
    r"(?i)^\s*(?:chore|build|ci|refactor)\s*\(\s*(?:fmt|format|style|lint|prettier|whitespace)\s*\)",
    r"(?i)^\s*(?:chore|build|ci)\s*:\s*(?:re)?format\b",
    r"(?i)^\s*(?:chore|build|ci)\s*:\s*lint\b",
]

_SOH = "\x01"


class OperationalError(Exception):
    """A real failure (git failed, bad arguments, unreadable manifest).

    Distinct from a FINDING: findings exit 0, operational errors do not."""

    def __init__(self, message, git_exit=None):
        Exception.__init__(self, message)
        self.message = message
        self.git_exit = git_exit


# ---------------------------------------------------------------------------- #
# Sibling reuse (hyphenated filenames -> importlib). IMPORTED, never re-implemented.
# ---------------------------------------------------------------------------- #
def _here():
    return os.path.dirname(os.path.abspath(__file__))


def _load_sibling(filename, module_name):
    import importlib.util

    path = os.path.join(_here(), filename)
    if not os.path.isfile(path):
        raise OperationalError("required sibling module not found: %s" % path)
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as e:  # noqa: BLE001
        raise OperationalError("cannot load sibling module %s: %s" % (path, e))
    return mod


_CHURN = None
_TAXONOMY = None


def churn():
    """``compound-v-churn.py`` — source of ``_run_git``, ``load_churn_config``,
    ``_compile_format_patterns`` and ``_is_format_subject``."""
    global _CHURN
    if _CHURN is None:
        _CHURN = _load_sibling("compound-v-churn.py", "compound_v_churn")
    return _CHURN


def taxonomy():
    """``compound-v-taxonomy.py`` — source of ``glob_match`` and ``load_yaml``."""
    global _TAXONOMY
    if _TAXONOMY is None:
        _TAXONOMY = _load_sibling("compound-v-taxonomy.py", "compound_v_taxonomy")
    return _TAXONOMY


def match_path(path, pattern):
    """Segment-aware path glob — the IMPORTED matcher, never a forked copy."""
    return taxonomy().glob_match(path, pattern)


def compile_subject_patterns(repo, taxonomy_path=None):
    """Built-in defaults UNIONED with any taxonomy ``format_commit_patterns``.

    Returns ``(compiled, exclude_globs, raw_patterns)``. With no real taxonomy the
    imported loader yields EMPTY patterns — which is exactly why the built-in defaults
    exist: an imported matcher fed an empty list rejects nothing."""
    ch = churn()
    exclude_globs, tax_patterns = ch.load_churn_config(repo, taxonomy_path)
    raw = list(DEFAULT_SUBJECT_PATTERNS) + list(tax_patterns or [])
    return ch._compile_format_patterns(raw), list(exclude_globs or []), raw


def is_release_or_format_subject(subject, compiled):
    """IMPORTED predicate (`churn._is_format_subject`), fed the unioned pattern set."""
    return churn()._is_format_subject(subject, compiled)


# ---------------------------------------------------------------------------- #
# Git extraction — THROUGH the imported supervisor wrapper, always.
# ---------------------------------------------------------------------------- #
def _git(repo, argv, cap_bytes=None):
    """Call churn's ``_run_git`` and surface a non-zero exit instead of flattening it."""
    ch = churn()
    if cap_bytes is None:
        cap_bytes = ch.OUTPUT_CAP_BYTES
    rc, out, capped = ch._run_git(argv, repo, cap_bytes=cap_bytes)
    return rc, out, capped


def git_head_sha(repo):
    rc, out, _ = _git(repo, ["git", "rev-parse", "HEAD"], cap_bytes=4096)
    if rc != 0:
        raise OperationalError(
            "git rev-parse HEAD failed in %s (exit %d)" % (repo, rc), git_exit=rc)
    sha = out.strip()
    if not sha:
        raise OperationalError("git rev-parse HEAD returned no sha in %s" % repo)
    return sha


def git_head_files(repo):
    """Every path present in the HEAD tree — used to filter partners deleted at HEAD."""
    rc, out, capped = _git(
        repo, ["git", "-c", "core.quotePath=false", "ls-tree", "-r", "--name-only", "HEAD"])
    if rc != 0:
        raise OperationalError(
            "git ls-tree HEAD failed in %s (exit %d)" % (repo, rc), git_exit=rc)
    lines = out.split("\n")
    if capped and lines and not out.endswith("\n"):
        lines = lines[:-1]
    return set(line for line in lines if line)


def collect_commits(repo, since=None, until=None):
    """One extraction pass -> ``(commits, capped)``.

    ``commits`` is a list of ``{"sha", "ct", "subject", "files"}`` in git-log order.
    ``--no-merges -M --name-only``; ``-c core.quotePath=false`` keeps non-ASCII paths
    unquoted; the SOH-delimited header format keeps a subject holding spaces/pipes
    unambiguous."""
    argv = ["git", "-c", "core.quotePath=false", "log", "--no-merges", "-M",
            "--name-only", "--format=%x01%H%x01%ct%x01%s"]
    if since:
        argv.append("--since=%s" % since)
    if until:
        argv.append("--until=%s" % until)
    rc, out, capped = _git(repo, argv)
    if rc != 0:
        raise OperationalError(
            "git log failed in %s (exit %d)" % (repo, rc), git_exit=rc)

    lines = out.split("\n")
    if capped and lines and not out.endswith("\n"):
        lines = lines[:-1]  # a byte-capped read may end mid-line

    commits = []
    cur = None
    for line in lines:
        if not line:
            continue
        if line.startswith(_SOH):
            parts = line.split(_SOH)
            if len(parts) < 4:
                cur = None
                continue
            try:
                ct = int(parts[2])
            except ValueError:
                ct = 0
            cur = {"sha": parts[1], "ct": ct, "subject": _SOH.join(parts[3:]),
                   "files": set()}
            commits.append(cur)
            continue
        if cur is not None:
            cur["files"].add(line)
    return commits, capped


# ---------------------------------------------------------------------------- #
# Pure statistics (no I/O — deterministic on identical input).
# ---------------------------------------------------------------------------- #
def wilson_lower_bound(successes, trials, z=WILSON_Z):
    """Lower bound of the 95% Wilson score interval for a binomial proportion.

    The point rate alone is not evidence at small n: 8/11 reads as 0.73 but its lower
    bound is 0.43. No smoothing, no prior, no invented confidence — a textbook interval."""
    if trials <= 0:
        return 0.0
    p = float(successes) / float(trials)
    z2 = z * z
    denom = 1.0 + z2 / trials
    centre = (p + z2 / (2.0 * trials)) / denom
    margin = (z / denom) * math.sqrt(
        (p * (1.0 - p) / trials) + (z2 / (4.0 * trials * trials)))
    lower = centre - margin
    if lower < 0.0:
        return 0.0
    if lower > 1.0:
        return 1.0
    return lower


def _round(value):
    """4 decimal places: the spec's 2-dp table is a rendering of this, never the reverse.
    Every threshold comparison uses full precision; rounding is display only."""
    return round(float(value), 4)


def tally(commits, compiled_subjects, exclude_globs, narrow_max_files, max_files):
    """Fold commits into per-file and per-pair counters.

    Returns ``(file_counts, pairs, eligible, dropped_oversized)`` where ``pairs`` maps an
    UNORDERED ``(a, b)`` key (a < b) to ``{joint, narrow, release, bulk}``."""
    file_counts = {}
    pairs = {}
    eligible = 0
    dropped = 0

    for commit in commits:
        files = commit["files"]
        if exclude_globs:
            files = set(
                f for f in files
                if not any(match_path(f, g) for g in exclude_globs))
        if len(files) > max_files:
            dropped += 1
            continue
        eligible += 1
        for f in files:
            file_counts[f] = file_counts.get(f, 0) + 1
        if len(files) < 2:
            continue
        is_release = is_release_or_format_subject(commit["subject"], compiled_subjects)
        is_bulk = len(files) > narrow_max_files
        is_narrow = (not is_release) and (not is_bulk)
        ordered = sorted(files)
        for i in range(len(ordered)):
            for j in range(i + 1, len(ordered)):
                key = (ordered[i], ordered[j])
                rec = pairs.get(key)
                if rec is None:
                    rec = {"joint": 0, "narrow": 0, "release": 0, "bulk": 0}
                    pairs[key] = rec
                rec["joint"] += 1
                if is_release:
                    rec["release"] += 1
                if is_bulk:
                    rec["bulk"] += 1
                if is_narrow:
                    rec["narrow"] += 1
    return file_counts, pairs, eligible, dropped


def _candidate(antecedent, consequent, rec, antecedent_commits):
    support = rec["joint"]
    rate = float(support) / float(antecedent_commits) if antecedent_commits else 0.0
    return {
        "antecedent": antecedent,
        "consequent": consequent,
        "support": support,
        "antecedent_commits": antecedent_commits,
        "rate": rate,
        "wilson_lower": wilson_lower_bound(support, antecedent_commits),
        "narrow_support": rec["narrow"],
        "release_commits": rec["release"],
        "bulk_commits": rec["bulk"],
    }


def _emit(cand):
    """Public rule shape — counts and measured frequencies only."""
    return {
        "antecedent": cand["antecedent"],
        "consequent": cand["consequent"],
        "support": cand["support"],
        "antecedent_commits": cand["antecedent_commits"],
        "rate": _round(cand["rate"]),
        "wilson_lower": _round(cand["wilson_lower"]),
        "narrow_support": cand["narrow_support"],
        "release_commits": cand["release_commits"],
        "bulk_commits": cand["bulk_commits"],
    }


def _rejection_reasons(cand, min_rate, min_wilson, min_narrow):
    """Gates failed, in a FIXED order (rate -> wilson -> narrow). ``reason`` is the first."""
    reasons = []
    if cand["rate"] < min_rate:
        reasons.append("rate_below_min")
    if cand["wilson_lower"] < min_wilson:
        reasons.append("wilson_lower_below_min")
    if cand["narrow_support"] < min_narrow:
        reasons.append("narrow_support_below_min")
    return reasons


def mine_rules(repo, since=None, until=None, taxonomy_path=None,
               min_support=DEFAULT_MIN_SUPPORT, min_rate=DEFAULT_MIN_RATE,
               min_wilson=DEFAULT_MIN_WILSON, min_narrow=DEFAULT_MIN_NARROW,
               narrow_max_files=DEFAULT_NARROW_MAX_FILES,
               max_files=DEFAULT_MAX_FILES, explain_rejections=False):
    """The whole engine. Raises ``OperationalError`` on any git failure."""
    repo = os.path.abspath(repo)
    head_sha = git_head_sha(repo)
    compiled, exclude_globs, raw_patterns = compile_subject_patterns(repo, taxonomy_path)
    commits, capped = collect_commits(repo, since=since, until=until)
    file_counts, pairs, eligible, dropped = tally(
        commits, compiled, exclude_globs, narrow_max_files, max_files)

    provenance = {
        "tool": TOOL_ID,
        "head_sha": head_sha,
        "since": since,
        "until": until,
        "eligible_commits": eligible,
        "dropped_oversized_commits": dropped,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "filters": {
            "min_support": min_support,
            "min_rate": min_rate,
            "min_wilson": min_wilson,
            "min_narrow": min_narrow,
            "narrow_max_files": narrow_max_files,
            "max_files": max_files,
            "no_merges": True,
            "rename_detection": "-M",
            "exclude_paths": sorted(exclude_globs),
            "subject_patterns": raw_patterns,
        },
    }

    # An incomplete scan is NEVER a clean scan: no rules at all, and a reason a caller
    # can branch on. "No missing partners" and "we could not tell" must not look alike.
    if capped:
        return {"complete": False, "reason": "scan_incomplete",
                "detail": ("git output hit the %d-byte cap; support and Wilson values "
                           "computed from a partial history would be biased"
                           % churn().OUTPUT_CAP_BYTES),
                "rules": [], "provenance": provenance}
    if eligible < min_support:
        return {"complete": False, "reason": "insufficient_history",
                "detail": ("%d eligible commit(s) in the window cannot clear a support "
                           "bar of %d" % (eligible, min_support)),
                "rules": [], "provenance": provenance}

    rules = []
    rejections = []
    for (left, right), rec in pairs.items():
        if rec["joint"] < min_support:
            continue  # not a candidate at all — silent, never surfaced with a hedge
        for antecedent, consequent in ((left, right), (right, left)):
            cand = _candidate(antecedent, consequent, rec,
                              file_counts.get(antecedent, 0))
            reasons = _rejection_reasons(cand, min_rate, min_wilson, min_narrow)
            if not reasons:
                rules.append(_emit(cand))
            elif explain_rejections:
                row = _emit(cand)
                row["reason"] = reasons[0]
                row["reasons"] = reasons
                rejections.append(row)

    rules.sort(key=lambda r: (-r["support"], r["antecedent"], r["consequent"]))
    result = {"complete": True, "rules": rules, "provenance": provenance}
    if explain_rejections:
        rejections.sort(key=lambda r: (-r["support"], r["antecedent"], r["consequent"]))
        result["rejections"] = rejections
    return result


# ---------------------------------------------------------------------------- #
# check — missing partners for a set of ownership GLOBS.
# ---------------------------------------------------------------------------- #
def patterns_from_manifest(manifest_path):
    """Union of every job's ``write_allowed`` globs (never a literal file list)."""
    try:
        with open(manifest_path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError as e:
        raise OperationalError("cannot read manifest %s: %s" % (manifest_path, e))
    try:
        data = taxonomy().load_yaml(text)
    except Exception as e:  # noqa: BLE001
        raise OperationalError("cannot parse manifest %s: %s" % (manifest_path, e))
    if not isinstance(data, dict):
        raise OperationalError("manifest %s is not a mapping" % manifest_path)
    patterns = []
    for job in data.get("jobs", []) or []:
        if not isinstance(job, dict):
            continue
        for pattern in job.get("write_allowed", []) or []:
            if isinstance(pattern, str) and pattern not in patterns:
                patterns.append(pattern)
    return patterns


def check_partition(repo, patterns, **kwargs):
    """Missing partners for ``patterns``. NEVER a gate — the caller exits 0 regardless."""
    mined = mine_rules(repo, **kwargs)
    out = {
        "complete": mined["complete"],
        "patterns": list(patterns),
        "findings": [],
        "provenance": mined["provenance"],
    }
    if not mined["complete"]:
        out["reason"] = mined["reason"]
        out["detail"] = mined["detail"]
        return out

    head_files = git_head_files(os.path.abspath(repo))
    for rule in mined["rules"]:
        matched = None
        for pattern in patterns:
            if match_path(rule["antecedent"], pattern):
                matched = pattern
                break
        if matched is None:
            continue  # the partition does not own the antecedent
        if any(match_path(rule["consequent"], p) for p in patterns):
            continue  # the partner is already covered
        if rule["consequent"] not in head_files:
            continue  # deleted at HEAD — never name a file that no longer exists
        finding = dict(rule)
        finding["matched_pattern"] = matched
        finding["missing_partner"] = rule["consequent"]
        out["findings"].append(finding)
    out["findings"].sort(
        key=lambda f: (-f["support"], f["antecedent"], f["missing_partner"]))
    return out


# ---------------------------------------------------------------------------- #
# CLI.
# ---------------------------------------------------------------------------- #
def dumps(obj):
    """Deterministic JSON + trailing newline."""
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def _add_common(parser):
    parser.add_argument("--repo", default=".", help="repository root (default: cwd)")
    parser.add_argument("--since", default=None, help="git --since bound (e.g. 2026-01-01)")
    parser.add_argument("--until", default=None, help="git --until bound")
    parser.add_argument("--taxonomy", default=None,
                        help="taxonomy YAML (excludes + extra subject patterns)")
    parser.add_argument("--min-support", type=int, default=DEFAULT_MIN_SUPPORT)
    parser.add_argument("--min-rate", type=float, default=DEFAULT_MIN_RATE)
    parser.add_argument("--min-wilson", type=float, default=DEFAULT_MIN_WILSON)
    parser.add_argument("--min-narrow", type=int, default=DEFAULT_MIN_NARROW)
    parser.add_argument("--narrow-max-files", type=int, default=DEFAULT_NARROW_MAX_FILES)
    parser.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES,
                        help="skip commits touching more than N files (bulk guard; "
                             "dropped commits are reported in provenance)")


def _mining_kwargs(args):
    return {
        "since": args.since, "until": args.until, "taxonomy_path": args.taxonomy,
        "min_support": args.min_support, "min_rate": args.min_rate,
        "min_wilson": args.min_wilson, "min_narrow": args.min_narrow,
        "narrow_max_files": args.narrow_max_files, "max_files": args.max_files,
    }


def build_parser():
    parser = argparse.ArgumentParser(
        prog="compound-v-cochange.py",
        description="Co-change advisory — ordered, git-derived, model-free.")
    subs = parser.add_subparsers(dest="command")

    rules_p = subs.add_parser("rules", help="mine ordered co-change rules")
    _add_common(rules_p)
    rules_p.add_argument("--explain-rejections", action="store_true",
                         help="diagnostic: also report candidates that cleared "
                              "--min-support but failed a later gate (check never "
                              "invokes or consumes this)")

    check_p = subs.add_parser("check", help="report partners missing from a partition")
    _add_common(check_p)
    group = check_p.add_mutually_exclusive_group(required=True)
    group.add_argument("--manifest", default=None,
                       help="execution manifest; uses the union of every job's "
                            "write_allowed GLOBS")
    group.add_argument("--patterns", nargs="+", default=None,
                       help="ownership GLOBS (e.g. 'scripts/**') — never a literal "
                            "file list")
    return parser


def main(argv):
    if "--selftest" in argv[1:]:
        return _selftest()

    parser = build_parser()
    args = parser.parse_args(argv[1:])
    if not args.command:
        parser.print_help()
        return 2

    try:
        if args.command == "rules":
            result = mine_rules(args.repo,
                                explain_rejections=args.explain_rejections,
                                **_mining_kwargs(args))
        else:
            if args.manifest:
                patterns = patterns_from_manifest(args.manifest)
            else:
                patterns = list(args.patterns)
            result = check_partition(args.repo, patterns, **_mining_kwargs(args))
    except OperationalError as e:
        payload = {"error": e.message, "command": args.command}
        if e.git_exit is not None:
            payload["git_exit"] = e.git_exit
        sys.stderr.write(dumps(payload))
        return 2

    sys.stdout.write(dumps(result))
    # `check` exits 0 WHETHER OR NOT findings exist. Non-zero is reserved for an
    # operational error — this is what structurally prevents a caller from gating on a
    # correlation.
    return 0


# ---------------------------------------------------------------------------- #
# Self-test — a fixture git repo in a tempdir OUTSIDE the worktree. Offline, ASCII-safe
# under LANG=C, no real taxonomy, pinned identity + dates.
# ---------------------------------------------------------------------------- #
FIX_BASE_TS = 1700000000


def _fixture_git(cwd, *args, **kwargs):
    env = dict(os.environ)
    env.update({
        "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@example.com",
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
        "LANG": "C", "LC_ALL": "C",
    })
    date = kwargs.get("date")
    if date is not None:
        env["GIT_AUTHOR_DATE"] = date
        env["GIT_COMMITTER_DATE"] = date
    subprocess.run(["git", "-C", cwd] + list(args), env=env,
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, check=True)


class _Fixture(object):
    """Builds a deterministic history; every commit gets its own pinned timestamp."""

    def __init__(self, repo):
        self.repo = repo
        self.n = 0

    def write(self, rel, text):
        full = os.path.join(self.repo, rel)
        parent = os.path.dirname(full)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(text)

    def commit(self, subject):
        self.n += 1
        stamp = "%d +0000" % (FIX_BASE_TS + self.n * 3600)
        _fixture_git(self.repo, "add", "-A")
        _fixture_git(self.repo, "commit", "-q", "-m", subject, date=stamp)


def _build_fixture(repo):
    """One history covering every acceptance case. No .claude/ taxonomy on purpose."""
    _fixture_git(repo, "init", "-q", "-b", "main")
    fx = _Fixture(repo)

    fx.write("README.md", "fixture\n")
    fx.commit("feat: bootstrap")

    # (1) A clean firing pair: c.txt <-> d.txt, 10 narrow non-release co-changes.
    for i in range(10):
        fx.write("c.txt", "c %d\n" % i)
        fx.write("d.txt", "d %d\n" % i)
        fx.commit("feat: c/d change %d" % i)

    # (2) RENAME DANCE at production support. a.txt is renamed to/from a2.txt 16 times;
    # every rename commit also touches b.txt. WITHOUT rename unification each of those
    # commits would list BOTH paths, giving the phantom pair (a.txt, a2.txt) support 16
    # and rate 1.0 — comfortably over the production bar. With -M the pair never forms.
    fx.write("a.txt", "a body\n" * 20)
    fx.write("b.txt", "b 0\n")
    fx.commit("feat: add a and b")
    for i in range(16):
        src, dst = ("a.txt", "a2.txt") if i % 2 == 0 else ("a2.txt", "a.txt")
        _fixture_git(repo, "mv", src, dst)
        fx.write("b.txt", "b %d\n" % (i + 1))
        fx.commit("refactor: move %s to %s" % (src, dst))

    # (3) A below-50%-similarity move that -M does NOT unify (documented limit).
    fx.write("e.txt", "alpha alpha alpha\n" * 20)
    fx.commit("feat: add e")
    os.remove(os.path.join(repo, "e.txt"))
    fx.write("f.txt", "zulu zulu zulu\n" * 20)
    fx.write("b.txt", "b dissimilar\n")
    fx.commit("move: dissimilar rewrite of e into f")

    # (4) Release-subject-confounded pair: 12 co-changes, 10 of them release commits.
    # With NO taxonomy present the imported loader yields empty patterns, so this pair
    # is rejected ONLY because the built-in subject defaults fire.
    for i in range(10):
        fx.write("g.txt", "g %d\n" % i)
        fx.write("h.txt", "h %d\n" % i)
        fx.commit("release(z1): v1.%d.0 lockstep bump" % i)
    for i in range(2):
        fx.write("g.txt", "g plain %d\n" % i)
        fx.write("h.txt", "h plain %d\n" % i)
        fx.commit("feat: g/h plain change %d" % i)

    # (5) Bulk-confounded pair: 8 of 10 co-changes sit in 15-file commits.
    for i in range(8):
        fx.write("i.txt", "i %d\n" % i)
        fx.write("j.txt", "j %d\n" % i)
        for k in range(13):
            fx.write("bulk/f%02d.txt" % k, "filler %d %d\n" % (i, k))
        fx.commit("feat: wide sweep %d" % i)
    for i in range(2):
        fx.write("i.txt", "i narrow %d\n" % i)
        fx.write("j.txt", "j narrow %d\n" % i)
        fx.commit("feat: i/j narrow change %d" % i)

    # (6) Small-sample pair: k.txt/l.txt co-change 8x, then k.txt moves alone 3x.
    # k->l is 8/11 (rate 0.73, Wilson LB 0.43) => rejected on the bound;
    # l->k is 8/8 => fires. The asymmetry is the point of ORDERED rules.
    for i in range(8):
        fx.write("k.txt", "k %d\n" % i)
        fx.write("l.txt", "l %d\n" % i)
        fx.commit("feat: k/l change %d" % i)
    for i in range(3):
        fx.write("k.txt", "k solo %d\n" % i)
        fx.commit("feat: k solo change %d" % i)

    # (7) A partner DELETED at HEAD.
    for i in range(10):
        fx.write("m.txt", "m %d\n" % i)
        fx.write("n.txt", "n %d\n" % i)
        fx.commit("feat: m/n change %d" % i)
    os.remove(os.path.join(repo, "n.txt"))
    fx.commit("feat: drop n")

    # (8) A nested pair for glob coverage ('*' and '**').
    for i in range(10):
        fx.write("sub/deep/c3.txt", "c3 %d\n" % i)
        fx.write("other/d3.txt", "d3 %d\n" % i)
        fx.commit("feat: nested change %d" % i)


def _run_main(argv):
    """Run ``main`` capturing stdout/stderr -> ``(rc, stdout, stderr)``."""
    import contextlib
    import io

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out):
        with contextlib.redirect_stderr(err):
            rc = main(argv)
    return rc, out.getvalue(), err.getvalue()


def _has_rule(rules, antecedent, consequent):
    return any(r["antecedent"] == antecedent and r["consequent"] == consequent
               for r in rules)


def _find(rows, antecedent, consequent):
    for row in rows:
        if row["antecedent"] == antecedent and row["consequent"] == consequent:
            return row
    return None


def _selftest():
    import shutil

    failures = []

    def expect(name, cond):
        print(("  ok   - " if cond else "  FAIL - ") + name)
        if not cond:
            failures.append(name)

    # --- pure statistics ----------------------------------------------------- #
    expect("wilson 34/34 -> 0.90", round(wilson_lower_bound(34, 34), 2) == 0.90)
    expect("wilson 34/36 -> 0.82", round(wilson_lower_bound(34, 36), 2) == 0.82)
    expect("wilson 33/36 -> 0.78", round(wilson_lower_bound(33, 36), 2) == 0.78)
    expect("wilson 17/18 -> 0.74", round(wilson_lower_bound(17, 18), 2) == 0.74)
    expect("wilson 17/21 -> 0.60", round(wilson_lower_bound(17, 21), 2) == 0.60)
    expect("wilson 8/11 -> 0.43 (the small-sample trap)",
           round(wilson_lower_bound(8, 11), 2) == 0.43)
    expect("wilson 8/8 -> 0.68", round(wilson_lower_bound(8, 8), 2) == 0.68)
    expect("wilson of zero trials is 0.0", wilson_lower_bound(0, 0) == 0.0)

    # --- built-in subject defaults (no taxonomy involved) --------------------- #
    compiled = churn()._compile_format_patterns(DEFAULT_SUBJECT_PATTERNS)
    for subject in ("release(z1): v2.14.1 - CI safety-net fixes",
                    "release: v2.15.0 - observability dashboard",
                    "chore(release): complete v2.6.4 manifest lockstep bump",
                    "v0.1.3: rename marketplace to procoders",
                    "style: reformat everything",
                    "chore(fmt): gofmt"):
        expect("built-in default matches %r" % subject[:34],
               is_release_or_format_subject(subject, compiled) is True)
    for subject in ("fix(scope-gate): close rename-bypass; release lockstep 2.8.0",
                    "docs(v1.1): release-gate audit - bump to 1.1.0",
                    "feat(v2.9): Z1 - e2e AC fixtures + v2.9.0 bump",
                    "Initial release: Compound V (Superpowers sidekick) v0.1.0",
                    "feat: add pr-review skill"):
        expect("built-in default does NOT over-match %r" % subject[:34],
               is_release_or_format_subject(subject, compiled) is False)
    expect("an EMPTY pattern list rejects nothing (why the defaults exist)",
           is_release_or_format_subject("release: v1.0.0",
                                        churn()._compile_format_patterns([])) is False)

    # --- imported, never forked ---------------------------------------------- #
    with open(os.path.abspath(__file__), "r", encoding="utf-8") as fh:
        src = fh.read()
    # Grep the CODE, not the module docstring — the prose legitimately names the helpers
    # it imports, and a naive substring grep would match its own explanation.
    code = src.split('"""', 2)[-1]
    for name in ("glob_match", "_run_git", "load_churn_config", "_is_format_subject",
                 "_compile_format_patterns", "glob_to_regex"):
        expect("no forked copy of %s (it is imported)" % name,
               re.search(r"(?m)^\s*def " + re.escape(name) + r"\(", code) is None)
    expect("no git call carries a bare process timeout (external-launch invariant)",
           "timeout" + "=" not in code)
    expect("glob_match resolves to the taxonomy module's function",
           match_path("scripts/a/b.py", "scripts/**") is
           taxonomy().glob_match("scripts/a/b.py", "scripts/**"))

    # --- glob semantics via the imported matcher ------------------------------ #
    expect("glob exact path", match_path("c.txt", "c.txt") is True)
    expect("glob '*' is segment-bound",
           match_path("other/d3.txt", "other/*") is True
           and match_path("sub/deep/c3.txt", "sub/*") is False)
    expect("glob '**' crosses segments", match_path("sub/deep/c3.txt", "sub/**") is True)
    expect("glob matches a path that does not exist at HEAD",
           match_path("newdir/not-created-yet.py", "newdir/**") is True)

    # --- deterministic JSON --------------------------------------------------- #
    blob = dumps({"b": 1, "a": {"z": "café"}})
    expect("json sorted, ascii-escaped, trailing newline",
           blob.endswith("\n") and blob.index('"a"') < blob.index('"b"')
           and "\\u00e9" in blob and all(ord(ch) < 128 for ch in blob))

    # --- end-to-end fixture ---------------------------------------------------- #
    tmp = tempfile.mkdtemp(prefix="cv-cochange-selftest-")
    try:
        repo = os.path.join(tmp, "repo")
        os.makedirs(repo)
        try:
            _build_fixture(repo)
        except (subprocess.CalledProcessError, OSError) as e:
            expect("fixture git repo built (git available)", False)
            print("    (git fixture unavailable: %s)" % e)
            return _finish(failures)

        mined = mine_rules(repo, explain_rejections=True)
        rules = mined["rules"]
        rejected = mined["rejections"]
        expect("scan is complete", mined["complete"] is True)
        expect("provenance carries head_sha (40-hex)",
               len(mined["provenance"]["head_sha"]) == 40)
        expect("provenance carries the eligible-commit count",
               mined["provenance"]["eligible_commits"] > 0)
        expect("provenance carries the active filter config",
               mined["provenance"]["filters"]["min_support"] == DEFAULT_MIN_SUPPORT)
        expect("no rule carries a risk score or confidence %",
               all(set(r.keys()) == {"antecedent", "consequent", "support",
                                     "antecedent_commits", "rate", "wilson_lower",
                                     "narrow_support", "release_commits",
                                     "bulk_commits"} for r in rules))

        # (a) rename detection, asserted AT the production support bar.
        expect("(a) clean pair fires at production thresholds",
               _has_rule(rules, "c.txt", "d.txt") and _has_rule(rules, "d.txt", "c.txt"))
        expect("(a) renamed path still forms a real rule (a2.txt -> b.txt)",
               _has_rule(rules, "a2.txt", "b.txt"))
        expect("(a) NO phantom old-path/new-path rule (16 renames would have fired)",
               not _has_rule(rules, "a.txt", "a2.txt")
               and not _has_rule(rules, "a2.txt", "a.txt"))
        expect("(a) the phantom pair is not merely sub-threshold - it never forms",
               _find(rejected, "a.txt", "a2.txt") is None
               and _find(rejected, "a2.txt", "a.txt") is None)

        # (b) a below-50%-similarity move is NOT unified by -M (documented limit).
        commits, _cap = collect_commits(repo)
        move = [c for c in commits if c["subject"].startswith("move: dissimilar")]
        expect("(b) the dissimilar-move commit exists", len(move) == 1)
        expect("(b) -M does NOT unify a below-50%-similarity move (both paths listed)",
               bool(move) and "e.txt" in move[0]["files"] and "f.txt" in move[0]["files"])

        # (c) built-in release/format defaults with NO taxonomy present.
        gh = _find(rejected, "g.txt", "h.txt")
        expect("(c) release-confounded pair does NOT fire",
               not _has_rule(rules, "g.txt", "h.txt"))
        expect("(c) it is rejected on narrow support, with 10 release commits counted",
               gh is not None and gh["reason"] == "narrow_support_below_min"
               and gh["release_commits"] == 10 and gh["narrow_support"] == 2)

        # (d) bulk-confounded pair rejected by narrow support.
        ij = _find(rejected, "i.txt", "j.txt")
        expect("(d) bulk-confounded pair does NOT fire",
               not _has_rule(rules, "i.txt", "j.txt"))
        expect("(d) it is rejected on narrow support, with 8 bulk commits counted",
               ij is not None and ij["reason"] == "narrow_support_below_min"
               and ij["bulk_commits"] == 8 and ij["narrow_support"] == 2)
        expect("(d) filler pairs inside the wide commits never fire",
               not any(r["antecedent"].startswith("bulk/") for r in rules))

        # (e) small-sample pair rejected by the Wilson bound; the reverse fires.
        kl = _find(rejected, "k.txt", "l.txt")
        expect("(e) k->l (8/11) does NOT fire", not _has_rule(rules, "k.txt", "l.txt"))
        expect("(e) it is rejected on the Wilson lower bound, not on the point rate",
               kl is not None and kl["reason"] == "wilson_lower_below_min"
               and kl["rate"] >= DEFAULT_MIN_RATE and kl["wilson_lower"] < 0.5)
        expect("(e) the REVERSE direction l->k fires (rules are ordered, not symmetric)",
               _has_rule(rules, "l.txt", "k.txt"))

        # (f) a partner deleted at HEAD is filtered out of findings.
        expect("(f) the historical rule m->n still exists",
               _has_rule(rules, "m.txt", "n.txt"))
        deleted = check_partition(repo, ["m.txt"])
        expect("(f) a partner deleted at HEAD is filtered from findings",
               deleted["findings"] == [])

        # (h) check exits 0 WITH findings (the structural anti-gate).
        rc, out, _err = _run_main(["prog", "check", "--repo", repo, "--patterns", "c.txt"])
        payload = json.loads(out)
        expect("(h) check EXITS 0 with findings present",
               rc == 0 and len(payload["findings"]) >= 1)
        expect("(h) the finding names the missing partner with its evidence",
               payload["findings"][0]["missing_partner"] == "d.txt"
               and payload["findings"][0]["support"] == 10
               and payload["findings"][0]["matched_pattern"] == "c.txt")
        rc_empty, out_empty, _e2 = _run_main(
            ["prog", "check", "--repo", repo, "--patterns", "does/not/exist/**"])
        expect("(h) check also exits 0 with NO findings",
               rc_empty == 0 and json.loads(out_empty)["findings"] == [])

        # (j) glob matching end to end: exact, '*', '**', and a path absent at HEAD.
        star = check_partition(repo, ["other/*"])
        expect("(j) '*' pattern matches an antecedent",
               any(f["missing_partner"] == "sub/deep/c3.txt" for f in star["findings"]))
        deep = check_partition(repo, ["sub/**"])
        expect("(j) '**' pattern matches a nested antecedent",
               any(f["missing_partner"] == "other/d3.txt" for f in deep["findings"]))
        absent = check_partition(repo, ["n.txt"])
        expect("(j) an antecedent ABSENT at HEAD is still matched by its glob",
               any(f["missing_partner"] == "m.txt" for f in absent["findings"]))

        # check --manifest reads the union of write_allowed GLOBS.
        manifest_path = os.path.join(tmp, "manifest.yaml")
        with open(manifest_path, "w", encoding="utf-8") as fh:
            fh.write("jobs:\n"
                     "  - id: j1\n"
                     "    write_allowed:\n"
                     "      - \"sub/**\"\n")
        expect("check --manifest uses the union of write_allowed globs",
               patterns_from_manifest(manifest_path) == ["sub/**"])
        rc_m, out_m, _e3 = _run_main(
            ["prog", "check", "--repo", repo, "--manifest", manifest_path])
        expect("check --manifest exits 0 and finds the uncovered partner",
               rc_m == 0
               and any(f["missing_partner"] == "other/d3.txt"
                       for f in json.loads(out_m)["findings"]))

        # (i) --max-files bulk filtering (drops 0 real commits here, fixture-only).
        capped_run = mine_rules(repo, max_files=12, explain_rejections=True)
        expect("(i) --max-files drops the 8 oversized commits, and REPORTS them",
               capped_run["provenance"]["dropped_oversized_commits"] == 8)
        expect("(i) pairs that existed only inside dropped commits disappear",
               _find(capped_run["rejections"], "i.txt", "j.txt") is None
               and not _has_rule(capped_run["rules"], "i.txt", "j.txt"))

        # Insufficient history: no rules AT ALL, plus a reason a caller can branch on.
        short = mine_rules(repo, min_support=10 ** 6)
        expect("insufficient history yields complete:false + NO rules",
               short["complete"] is False and short["reason"] == "insufficient_history"
               and short["rules"] == [])
        short_check = check_partition(repo, ["c.txt"], min_support=10 ** 6)
        expect("check propagates incompleteness instead of reporting a clean bill",
               short_check["complete"] is False
               and short_check["reason"] == "insufficient_history"
               and short_check["findings"] == [])

        # NORMAL output is silent about rejections; the diagnostic mode is opt-in.
        normal = mine_rules(repo)
        expect("normal output carries NO rejections key",
               "rejections" not in normal
               and normal["rules"] == mined["rules"])

        # (g) a non-zero git exit is SURFACED, never flattened into "no rules".
        not_a_repo = os.path.join(tmp, "not-a-repo")
        os.makedirs(not_a_repo)
        rc_g, out_g, err_g = _run_main(["prog", "rules", "--repo", not_a_repo])
        expect("(g) a non-zero git exit exits non-zero with an error payload",
               rc_g != 0 and out_g == "" and "git" in err_g)
        rc_gc, _out_gc, err_gc = _run_main(
            ["prog", "check", "--repo", not_a_repo, "--patterns", "c.txt"])
        expect("(g) check surfaces an operational error as non-zero (NOT as a finding)",
               rc_gc != 0 and "git" in err_gc)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    return _finish(failures)


def _finish(failures):
    if failures:
        print("\nSELFTEST FAILED: %d case(s)" % len(failures))
        return 1
    print("\nSELFTEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
