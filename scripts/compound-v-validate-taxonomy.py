#!/usr/bin/env python3
"""
Compound V impact-taxonomy validator — the DETERMINISTIC schema gate (v2.9 Task B1).

Validates a `compound-v-impact-taxonomy.yaml` (authored/offered by `/v:onboard`,
consumed by A1 localization, A3 scoring, F2 post-diff reclassify, D1 churn). It backs
no LLM judgment: either it passes or it fails with a specific list of violations.

It **delegates all MATCHING semantics to the single shared loader**
`compound-v-taxonomy.py` (never recopied): band vocabulary (`VALID_BANDS`), the six
content kinds (`CONTENT_KINDS`), the pattern-type set (`PATTERN_TYPES`), the safe-regex
subset (`is_safe_regex` — the SAME validator the loader/matcher runs, so an "unbounded"
[nested-quantifier / over-length] regex is rejected identically here and at match time,
AC-16), the glob translation (`glob_match`, used to prove a glob compiles), and the
soft-PyYAML+stdlib `load_yaml` (never a hard `import yaml` — AC-10 / N2 / CR-Global).

Taxonomy shape (validated here):

    version: 1
    path_patterns:                       # optional
      - {glob, difficulty_band, impact_band}     # bands ∈ low|medium|high
    content_patterns:                    # optional; the AC-8 content-pattern side
      - {match, pattern_type, case, scan, kind, impact_band}
        # pattern_type ∈ literal|glob|regex ; case ∈ sensitive|insensitive ;
        # scan ∈ content|path ; kind ∈ the SIX CONTENT_KINDS (legal_copy,
        # i18n_placeholder, feature_flag, config_literal, shared_token, a11y —
        # shared_token & a11y are FIRST-CLASS kinds because F2's post-diff re-check
        # reads them, CR4-4) ; a regex `match` MUST pass the safe subset.
    sensitive_path_list: [glob]          # REQUIRED (missing → fail-closed violation)
    churn:                               # REQUIRED, single-sourced (CR4-10) so D1
      exclude_paths: [glob]              # never invents its own excludes
      format_commit_patterns: [regex]    # each a BOUNDED (safe-subset) regex

Fail-closed: a parse failure, an unknown enum, a missing required section, or an
unbounded regex is a VIOLATION (never silently accepted).

Usage
-----
    compound-v-validate-taxonomy.py <taxonomy.yaml>
    compound-v-validate-taxonomy.py --selftest

Exit codes: 0 = valid, 1 = one or more violations (printed), 2 = usage/parse error.

Python 3.9-safe, stdlib only (PyYAML used opportunistically via the shared loader).
"""

import importlib.util
import json
import os
import sys


# --------------------------------------------------------------------------- #
# Reuse the SINGLE shared loader by path (no recopy). It owns matching semantics
# (bands, kinds, pattern types, safe-regex subset, glob translation) and the
# soft-PyYAML+stdlib load_yaml.
# --------------------------------------------------------------------------- #
_LOADER = None


def _loader():
    global _LOADER
    if _LOADER is not None:
        return _LOADER
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "compound-v-taxonomy.py")
    spec = importlib.util.spec_from_file_location("compound_v_taxonomy", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _LOADER = mod
    return _LOADER


# Enum vocabularies for the fields the loader does NOT export a constant for. These
# are STRUCTURAL enums (what the validator owns), not matching semantics (which the
# loader owns). Kept as literals so a taxonomy typo is a specific, named violation.
VALID_CASES = ("sensitive", "insensitive")
VALID_SCANS = ("content", "path")


def load_yaml(text):
    """Soft-PyYAML+stdlib YAML load, delegated to the shared loader (whose single
    yaml import site lives in validate-manifest.py). NEVER a hard `import yaml`."""
    return _loader().load_yaml(text)


# --------------------------------------------------------------------------- #
# Validation.
# --------------------------------------------------------------------------- #
def _is_list(v):
    return isinstance(v, list)


def _glob_ok(g):
    """A glob is well-formed iff it is a non-empty string that the shared loader's
    glob translation can compile (delegated matching semantics)."""
    if not isinstance(g, str) or g == "":
        return False
    try:
        _loader().glob_match("witness", g)  # compiles the glob; raises if malformed
        return True
    except Exception:  # noqa: BLE001 — an uncompilable glob is simply invalid
        return False


def _check_band(problems, where, band):
    ld = _loader()
    if band not in ld.VALID_BANDS:
        problems.append(
            "%s band '%s' invalid (expected one of %s)"
            % (where, band, ", ".join(ld.VALID_BANDS))
        )


def _check_glob_list(problems, where, value, required=True):
    if value is None:
        if required:
            problems.append("%s is missing (required)" % where)
        return
    if not _is_list(value):
        problems.append("%s must be a list of globs" % where)
        return
    for i, g in enumerate(value):
        if not _glob_ok(g):
            problems.append("%s[%d] '%s' is not a valid glob" % (where, i, g))


def _check_regex_list(problems, where, value):
    """Every entry must be a BOUNDED (safe-subset) regex per the shared is_safe_regex."""
    ld = _loader()
    if value is None:
        problems.append("%s is missing (required)" % where)
        return
    if not _is_list(value):
        problems.append("%s must be a list of regexes" % where)
        return
    for i, rx in enumerate(value):
        if not isinstance(rx, str) or rx == "":
            problems.append("%s[%d] must be a non-empty regex string" % (where, i))
            continue
        ok, reason = ld.is_safe_regex(rx)
        if not ok:
            problems.append(
                "%s[%d] '%s' is not a bounded/safe regex (%s)" % (where, i, rx, reason)
            )


def validate(taxonomy):
    """Return a list of violation strings; empty list means valid."""
    problems = []
    ld = _loader()

    if not isinstance(taxonomy, dict):
        return ["taxonomy root is not a mapping"]

    # version — required, must be an int.
    version = taxonomy.get("version")
    if version is None:
        problems.append("taxonomy missing required top-level field 'version'")
    elif isinstance(version, bool) or not isinstance(version, int):
        problems.append("taxonomy 'version' must be an int (got %r)" % version)

    # path_patterns — optional; each row {glob, difficulty_band, impact_band}.
    pp = taxonomy.get("path_patterns")
    if pp is not None:
        if not _is_list(pp):
            problems.append("taxonomy 'path_patterns' must be a list")
        else:
            for i, row in enumerate(pp):
                where = "path_patterns[%d]" % i
                if not isinstance(row, dict):
                    problems.append("%s is not a mapping" % where)
                    continue
                if not isinstance(row.get("glob"), str) or not row.get("glob"):
                    problems.append("%s missing string 'glob'" % where)
                elif not _glob_ok(row.get("glob")):
                    problems.append("%s glob '%s' is not a valid glob"
                                    % (where, row.get("glob")))
                for band_field in ("difficulty_band", "impact_band"):
                    if band_field not in row:
                        problems.append("%s missing '%s'" % (where, band_field))
                    else:
                        _check_band(problems, "%s.%s" % (where, band_field),
                                    row.get(band_field))

    # content_patterns — optional; the AC-8 content-pattern side. Every field is
    # REQUIRED to be explicit (pattern_type/case/scan/kind/impact_band + match).
    cp = taxonomy.get("content_patterns")
    if cp is not None:
        if not _is_list(cp):
            problems.append("taxonomy 'content_patterns' must be a list")
        else:
            for i, row in enumerate(cp):
                where = "content_patterns[%d]" % i
                if not isinstance(row, dict):
                    problems.append("%s is not a mapping" % where)
                    continue
                match = row.get("match")
                if not isinstance(match, str) or match == "":
                    problems.append("%s missing non-empty string 'match'" % where)

                ptype = row.get("pattern_type")
                if ptype is None:
                    problems.append("%s missing 'pattern_type'" % where)
                elif ptype not in ld.PATTERN_TYPES:
                    problems.append(
                        "%s pattern_type '%s' invalid (expected one of %s)"
                        % (where, ptype, ", ".join(ld.PATTERN_TYPES)))

                case = row.get("case")
                if case is None:
                    problems.append("%s missing 'case'" % where)
                elif case not in VALID_CASES:
                    problems.append(
                        "%s case '%s' invalid (expected one of %s)"
                        % (where, case, ", ".join(VALID_CASES)))

                scan = row.get("scan")
                if scan is None:
                    problems.append("%s missing 'scan'" % where)
                elif scan not in VALID_SCANS:
                    problems.append(
                        "%s scan '%s' invalid (expected one of %s)"
                        % (where, scan, ", ".join(VALID_SCANS)))

                kind = row.get("kind")
                if kind is None:
                    problems.append("%s missing 'kind'" % where)
                elif kind not in ld.CONTENT_KINDS:
                    problems.append(
                        "%s kind '%s' invalid (expected one of the six kinds: %s)"
                        % (where, kind, ", ".join(ld.CONTENT_KINDS)))

                if "impact_band" not in row:
                    problems.append("%s missing 'impact_band'" % where)
                else:
                    _check_band(problems, "%s.impact_band" % where,
                                row.get("impact_band"))

                # A regex `match` MUST pass the SAME safe subset the matcher runs
                # (unbounded / nested-quantifier → rejected here, never executed there).
                if ptype == "regex" and isinstance(match, str) and match != "":
                    ok, reason = ld.is_safe_regex(match)
                    if not ok:
                        problems.append(
                            "%s regex match '%s' is not a bounded/safe regex (%s)"
                            % (where, match, reason))
                elif ptype == "glob" and isinstance(match, str) and match != "":
                    if not _glob_ok(match):
                        problems.append("%s glob match '%s' is not a valid glob"
                                        % (where, match))

    # sensitive_path_list — REQUIRED (fail-closed).
    if "sensitive_path_list" not in taxonomy or taxonomy.get("sensitive_path_list") is None:
        problems.append(
            "taxonomy missing required top-level field 'sensitive_path_list' "
            "(the fail-closed override #2 path-list — a taxonomy without it cannot gate)")
    else:
        _check_glob_list(problems, "sensitive_path_list",
                         taxonomy.get("sensitive_path_list"), required=True)

    # churn — REQUIRED, single-sourced (CR4-10) so D1 reuses these excludes.
    churn = taxonomy.get("churn")
    if churn is None:
        problems.append(
            "taxonomy missing required 'churn' block "
            "(exclude_paths + format_commit_patterns; single-sourced for D1, CR4-10)")
    elif not isinstance(churn, dict):
        problems.append("taxonomy 'churn' must be a mapping")
    else:
        _check_glob_list(problems, "churn.exclude_paths",
                         churn.get("exclude_paths"), required=True)
        _check_regex_list(problems, "churn.format_commit_patterns",
                          churn.get("format_commit_patterns"))

    return problems


def validate_text(text):
    data = load_yaml(text)
    return validate(data)


# --------------------------------------------------------------------------- #
# CLI.
# --------------------------------------------------------------------------- #
def main(argv):
    args = argv[1:]
    if "--selftest" in args:
        return _selftest()
    if not args:
        print("usage: compound-v-validate-taxonomy.py <taxonomy.yaml> | --selftest",
              file=sys.stderr)
        return 2
    path = args[0]
    if not os.path.isfile(path):
        print("error: not a file: %s" % path, file=sys.stderr)
        return 2
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    try:
        problems = validate_text(text)
    except Exception as e:  # noqa: BLE001 — fail-closed on a parse error
        print(json.dumps({"verdict": "error", "error": str(e)}), file=sys.stderr)
        return 2

    if problems:
        print("TAXONOMY INVALID: %d violation(s)" % len(problems), file=sys.stderr)
        for p in problems:
            print("  - %s" % p, file=sys.stderr)
        print(json.dumps({"verdict": "invalid", "violations": problems}, indent=2))
        return 1
    print(json.dumps({"verdict": "valid", "violations": []}, indent=2))
    return 0


# --------------------------------------------------------------------------- #
# Self-test (TDD — written FIRST, must fail against the stub, pass against impl).
# --------------------------------------------------------------------------- #

# A fully-VALID taxonomy: path patterns + ALL SIX content kinds (each with an
# explicit pattern_type/case/scan/kind/impact_band) + sensitive_path_list + churn.
# Raw string so regex backslashes survive; single-quoted YAML scalars keep them
# literal for BOTH PyYAML and the stdlib _mini_yaml fallback.
GOOD_TAXONOMY = r"""
version: 1
path_patterns:
  - glob: "src/auth/**"
    difficulty_band: high
    impact_band: high
  - glob: "src/ui/**"
    difficulty_band: low
    impact_band: low
content_patterns:
  - match: "By clicking you agree"
    pattern_type: literal
    case: insensitive
    scan: content
    kind: legal_copy
    impact_band: high
  - match: "{{*}}"
    pattern_type: glob
    case: sensitive
    scan: content
    kind: i18n_placeholder
    impact_band: high
  - match: 'feature_flag\s*=\s*\w+'
    pattern_type: regex
    case: sensitive
    scan: content
    kind: feature_flag
    impact_band: high
  - match: 'timeout\s*=\s*\d+'
    pattern_type: regex
    case: sensitive
    scan: content
    kind: config_literal
    impact_band: high
  - match: "var(--"
    pattern_type: literal
    case: sensitive
    scan: content
    kind: shared_token
    impact_band: medium
  - match: "aria-label"
    pattern_type: literal
    case: sensitive
    scan: content
    kind: a11y
    impact_band: high
sensitive_path_list:
  - "src/auth/**"
  - "**/migrations/**"
churn:
  exclude_paths:
    - "**/*.min.js"
    - "**/dist/**"
  format_commit_patterns:
    - '^chore\(fmt\)'
    - '^style:'
"""

# Missing sensitive_path_list — MUST fail.
MISSING_SENSITIVE = r"""
version: 1
path_patterns:
  - glob: "src/**"
    difficulty_band: medium
    impact_band: medium
churn:
  exclude_paths:
    - "**/*.min.js"
  format_commit_patterns:
    - '^chore'
"""

# Bad band — MUST fail.
BAD_BAND = r"""
version: 1
path_patterns:
  - glob: "src/**"
    difficulty_band: critical
    impact_band: medium
sensitive_path_list:
  - "src/auth/**"
churn:
  exclude_paths:
    - "**/*.min.js"
  format_commit_patterns:
    - '^chore'
"""

# Unbounded (nested-quantifier) regex in a content pattern — MUST fail.
UNBOUNDED_REGEX = r"""
version: 1
content_patterns:
  - match: '(a+)+$'
    pattern_type: regex
    case: sensitive
    scan: content
    kind: config_literal
    impact_band: high
sensitive_path_list:
  - "src/auth/**"
churn:
  exclude_paths:
    - "**/*.min.js"
  format_commit_patterns:
    - '^chore'
"""

# Churn block with an unbounded format-commit regex — MUST fail.
BAD_CHURN_REGEX = r"""
version: 1
sensitive_path_list:
  - "src/auth/**"
churn:
  exclude_paths:
    - "**/*.min.js"
  format_commit_patterns:
    - '(a+)+$'
"""

# Missing churn block — MUST fail (single-sourced for D1, CR4-10).
MISSING_CHURN = r"""
version: 1
sensitive_path_list:
  - "src/auth/**"
"""


def _selftest():
    failures = []

    def expect(name, cond):
        print(("  ok   - " if cond else "  FAIL - ") + name)
        if not cond:
            failures.append(name)

    # GOOD taxonomy → zero violations, and all six content kinds are present.
    good = validate_text(GOOD_TAXONOMY)
    expect("good taxonomy: zero violations (%r)" % good, good == [])

    parsed = load_yaml(GOOD_TAXONOMY)
    kinds = {r.get("kind") for r in (parsed.get("content_patterns") or [])}
    expect("good taxonomy: all SIX content kinds present (incl. shared_token/a11y)",
           kinds == set(_loader().CONTENT_KINDS) and len(kinds) == 6)

    # Missing sensitive_path_list → fails, naming the field.
    ms = validate_text(MISSING_SENSITIVE)
    expect("missing sensitive_path_list fails",
           any("sensitive_path_list" in p for p in ms))

    # Bad band → fails.
    bb = validate_text(BAD_BAND)
    expect("bad band 'critical' rejected",
           any("band 'critical' invalid" in p for p in bb))

    # Unbounded regex (content pattern) → fails, naming the safe-subset.
    ur = validate_text(UNBOUNDED_REGEX)
    expect("unbounded content regex rejected",
           any("not a bounded/safe regex" in p for p in ur))

    # Bad churn regex → fails.
    bc = validate_text(BAD_CHURN_REGEX)
    expect("unbounded churn format_commit_pattern rejected",
           any("format_commit_patterns" in p and "bounded/safe regex" in p
               for p in bc))

    # Churn block validates (globs + bounded regexes) on the GOOD fixture — i.e. the
    # good churn produced NO churn violation at all.
    expect("good churn block validates (no churn violation)",
           not any("churn" in p for p in good))

    # Missing churn block → fails (single-sourced, CR4-10).
    mc = validate_text(MISSING_CHURN)
    expect("missing churn block fails",
           any("churn" in p for p in mc))

    # The shipped example file (if present next to this script under .claude/) is valid.
    here = os.path.dirname(os.path.abspath(__file__))
    example = os.path.join(os.path.dirname(here), ".claude",
                           "compound-v-impact-taxonomy.example.yaml")
    if os.path.isfile(example):
        with open(example, "r", encoding="utf-8") as fh:
            ex_text = fh.read()
        ex = validate_text(ex_text)
        expect("shipped example taxonomy is valid (%r)" % ex, ex == [])
        # And it parses + validates under the NO-PyYAML stdlib fallback too, since
        # downstream consumers may run without PyYAML (CI/cron/minimal Docker).
        vm = _loader()._validate_manifest_module()
        if vm:
            fb = validate(vm._mini_yaml(ex_text))
            expect("example valid under the stdlib _mini_yaml fallback (%r)" % fb,
                   fb == [])

    # Non-mapping root → single clear violation (fail-closed, no crash).
    expect("non-mapping root rejected", validate("not a mapping") != [])
    expect("empty version-only doc fails (missing required sections)",
           validate_text("version: 1") != [])

    if failures:
        print("\nSELFTEST FAILED: %d case(s)" % len(failures))
        return 1
    print("\nSELFTEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
