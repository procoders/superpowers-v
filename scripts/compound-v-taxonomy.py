#!/usr/bin/env python3
"""
Compound V — the SINGLE shared impact-taxonomy loader + matcher (v2.9 Task 0).

Every v2.9 consumer reads the impact taxonomy through THIS module — the localizer
(A1), the pre-eval scoring engine (A3), the taxonomy validator (B1, which delegates
its matching semantics here), and the post-hoc reclassifier (F2). No other task
recopies the loader or the matcher; they import this by path.

Taxonomy shape (authored by `/v:onboard`, validated by compound-v-validate-taxonomy.py):

    version: 1
    path_patterns:
      - {glob: "src/auth/**", difficulty_band: high, impact_band: high}
    content_patterns:
      - {match: "aria-label", pattern_type: literal, case: sensitive,
         scan: content, kind: a11y, impact_band: high}
    sensitive_path_list: ["src/auth/**", "**/migrations/**"]
    content_scan_exclude: ["**/*.md"]         # v3.4.1 A5 — optional, default empty: paths
                                              # whose CONTENT is never scanned (path rows
                                              # and sensitive_path_list still apply)
    auto_route_allow: ["CHANGELOG.md"]        # v3.0 A4 predicate 4 — optional, default empty
    auto_route_max_lines: 20                  # v3.0 A4 predicate 8 — optional, default 20
    churn: {exclude_paths: ["**/*.min.js"], format_commit_patterns: ["^chore\\(fmt\\)"]}

The two `auto_route_*` keys are the v3.0 DIRECT auto-route class (spec §A4). They are
OPTIONAL and fail-closed by absence: a taxonomy without `auto_route_allow` grants nothing,
which is exactly the pre-3.0 behaviour. `match_auto_route()` is the single implementation
of predicates 4 and 5; no consumer re-derives allow/sensitive membership itself.

Bands are `low | medium | high` (never a raw number — Iron-Invariant #1). Matching is
**conservative-max**: a single strong `high` signal is never diluted by a weak one.

content_patterns declare an explicit `pattern_type`:
  - `literal` : plain substring test (respects `case`).
  - `glob`    : shell-style `*`/`?` translated to a bounded regex, searched anywhere.
  - `regex`   : a documented **SAFE SUBSET** (no nested quantifiers), deterministically
                validated by `is_safe_regex`, AND — because Python 3.9 `re` has NO match
                timeout — matched inside a **killable subprocess** via the shared timeout
                supervisor (`compound-v-run-with-timeout.py`). An adversarial nested-
                quantifier input therefore terminates within a fixed wall-clock bound
                even if a pattern slips validation (defense in depth — AC-16 / CR2-7).

Reuse (no recopy): `glob_match`/`_seg_is_literal`/`load_yaml` from
compound-v-validate-manifest.py (soft-PyYAML + stdlib fallback — never a hard
`import yaml`), and the timeout supervisor for the regex subprocess.

Digest convention (canonical-JSON, referenced by CR5-6/CR5-7 and documented in full in
docs/superpowers/architecture/pre-eval-config.md) also lives here so downstream C1 tests
consume ONE implementation:
  - `canonical_json(obj)`   : json.dumps(obj, sort_keys=True, separators=(",",":"),
                              ensure_ascii=False, allow_nan=False)  (recursively key-sorted)
  - `record_digest(obj, exclude_field)` : "sha256:"+sha256(canonical_json(obj minus the
                              self-digest field).encode("utf-8"))  — for pre-eval / receipt /
                              localization records.
  - `taxonomy_digest_bytes(b)` : "sha256:"+sha256(b)  — over the RAW immutable snapshot
                              bytes (content-address, not a re-serialization).

Usage:
    compound-v-taxonomy.py <taxonomy.yaml>          # parse + print normalized JSON
    compound-v-taxonomy.py --digest <taxonomy.yaml> # print the snapshot digest
    compound-v-taxonomy.py --selftest
    compound-v-taxonomy.py --regex-search --patterns-file P --text-file T  # internal worker

Python 3.9-safe, stdlib only.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile


# ---------------------------------------------------------------------------- #
# Reuse siblings by path (no recopy). Loaded lazily; each has an inline fallback
# so this module never hard-fails if a sibling is briefly unavailable.
# ---------------------------------------------------------------------------- #
_VM_MODULE = None


def _validate_manifest_module():
    global _VM_MODULE
    if _VM_MODULE is not None:
        return _VM_MODULE
    import importlib.util

    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "compound-v-validate-manifest.py")
    try:
        spec = importlib.util.spec_from_file_location("compound_v_validate_manifest", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _VM_MODULE = mod
    except Exception:  # noqa: BLE001
        _VM_MODULE = False
    return _VM_MODULE


def glob_match(path, pattern):
    """Path glob match (segment-aware `*`, recursive `**`, literal `[`). Reuses
    validate-manifest.glob_match; falls back to a minimal inline translation."""
    mod = _validate_manifest_module()
    if mod:
        return mod.glob_match(path, pattern)
    # Fallback: fnmatch-translate with **-across-segments.
    rx = ["(?s:"]
    i, n = 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            j = i
            while j < n and pattern[j] == "*":
                j += 1
            rx.append(".*" if j - i >= 2 else "[^/]*")
            i = j
            continue
        if c == "?":
            rx.append("[^/]")
        else:
            rx.append(re.escape(c))
        i += 1
    rx.append(")\\Z")
    return re.compile("".join(rx)).match(path) is not None


def load_yaml(text):
    """Soft-PyYAML + stdlib-fallback YAML load, reusing validate-manifest.load_yaml
    (its `import yaml` is THE single yaml import site in the codebase — this module
    never hard-imports yaml). Fallback: soft-import yaml here, else raise a clear error."""
    mod = _validate_manifest_module()
    if mod:
        return mod.load_yaml(text)
    try:  # last-resort soft import — still never a HARD top-level import
        import yaml  # noqa: WPS433
        return yaml.safe_load(text)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "cannot parse taxonomy YAML: validate-manifest fallback parser is "
            "unavailable and PyYAML is not installed (%s)" % e
        )


# ---------------------------------------------------------------------------- #
# Bands (conservative-max).
# ---------------------------------------------------------------------------- #
VALID_BANDS = ("low", "medium", "high")
_BAND_RANK = {"low": 1, "medium": 2, "high": 3}
CONTENT_KINDS = (
    "legal_copy", "i18n_placeholder", "feature_flag", "config_literal",
    "shared_token", "a11y",
)
PATTERN_TYPES = ("literal", "glob", "regex")

MAX_REGEX_LEN = 200
DEFAULT_REGEX_TIMEOUT_S = 2
_REGEX_RESULT_CAP_BYTES = 1 << 16  # bounded output sink for the regex worker


# v3.0 §A4 — the DIRECT auto-route class.
#
# DEFAULT_AUTO_ROUTE_MAX_LINES is the spec default applied when the taxonomy is silent. A
# MALFORMED value is not defaulted, it is floored to 0 (nothing can auto-route) — a broken
# budget must never silently become a permissive one.
DEFAULT_AUTO_ROUTE_MAX_LINES = 20

# MANDATORY_SENSITIVE: the policy files, treated as sensitive for auto-route purposes in EVERY
# project whether or not the taxonomy lists them. Spec §A4.5: "a policy that does not protect
# itself is not a policy", and §A4.8's attack is precisely an implementer editing only the
# taxonomy to widen `auto_route_allow`. A seed that forgets these rows must not re-open it, so
# the floor lives in code and the taxonomy can only ADD to it. Deliberately scoped to
# auto-route eligibility: `match_path`'s `sensitive` (hard override #2) still reports exactly
# what the taxonomy declares, so no existing verdict changes shape.
MANDATORY_SENSITIVE = (
    ".claude/compound-v-impact-taxonomy.yaml",
    ".claude/compound-v.json",
)


def glob_is_broad(pattern):
    """v3.4.1 §A1 — is this glob a "everything under here" pattern?

    TRUE when the pattern contains `**` or ends in `/*`. BREADTH IS A PROPERTY OF THE
    GLOB, NEVER OF THE REPOSITORY: counting the files a pattern matches would cost a
    repo scan on every prompt, and a pattern that says "everything under here" is broad
    by construction whether the directory holds one file or ten thousand.

    The scoring engine reads this per matched row to decide whether T1's bands are a
    statement about THIS file or about a whole directory — the second is the only case
    in which a light classify is allowed to demote the tier (spec §A2).
    """
    if not isinstance(pattern, str) or not pattern:
        return False
    return "**" in pattern or pattern.endswith("/*")


def band_rank(band):
    return _BAND_RANK.get(band, 0)


def max_band(bands):
    """Conservative-max over an iterable of bands; None if none are valid."""
    best = None
    for b in bands:
        if b in _BAND_RANK and (best is None or _BAND_RANK[b] > _BAND_RANK[best]):
            best = b
    return best


# ---------------------------------------------------------------------------- #
# Safe-regex subset validator (deterministic — no nested quantifiers).
# ---------------------------------------------------------------------------- #
def _quant_at(pattern, i):
    """If a quantifier starts at index i, return (length, dangerous). `dangerous`
    means a REPETITION that can match variably/multiply (`*`, `+`, `{n,}`, `{n,m}`
    with m>=2) — the outer half of a catastrophic nested quantifier. `?`, `{0,1}`,
    `{1}`, `{1,1}` are non-dangerous (bounded, no exponential blow-up)."""
    c = pattern[i]
    if c in "*+":
        return 1, True
    if c == "?":
        return 1, False
    if c == "{":
        m = re.match(r"\{(\d*)(,(\d*))?\}", pattern[i:])
        if not m:
            return 0, False  # a literal '{'
        lo = m.group(1)
        has_comma = m.group(2) is not None
        hi = m.group(3)
        if has_comma:
            # {n,}  -> unbounded (dangerous); {n,m} -> dangerous iff m>=2
            dangerous = (hi == "") or (hi.isdigit() and int(hi) >= 2)
        else:
            dangerous = lo.isdigit() and int(lo) >= 2  # {2} repeats; {0}/{1} do not
        return len(m.group(0)), dangerous
    return 0, False


def is_safe_regex(pattern):
    """(ok, reason). The SAFE SUBSET: compiles, bounded length, and NO nested
    quantifier — a repetition quantifier applied to a group that itself contains a
    quantifier (the `(a+)+` catastrophic-backtracking shape). Python's own compiler
    already rejects adjacent double-quantifiers (`a**`); this adds the group check.
    Conservative by design; the killable subprocess is the runtime backstop."""
    if not isinstance(pattern, str):
        return False, "pattern is not a string"
    if len(pattern) > MAX_REGEX_LEN:
        return False, "pattern exceeds %d chars" % MAX_REGEX_LEN
    try:
        re.compile(pattern)
    except re.error as e:
        return False, "does not compile: %s" % e

    stack = []  # per open group: has_quant (a quantifier occurred at/under this group)
    i, n = 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c == "\\":
            i += 2  # escaped literal — skip the next char
            continue
        if c == "[":  # character class: quantifier chars inside are literal
            j = i + 1
            if j < n and pattern[j] == "^":
                j += 1
            if j < n and pattern[j] == "]":
                j += 1
            while j < n and pattern[j] != "]":
                if pattern[j] == "\\":
                    j += 1
                j += 1
            i = j + 1
            continue
        if c == "(":
            stack.append(False)
            i += 1
            continue
        if c == ")":
            inner_has_quant = stack.pop() if stack else False
            # A quantifier immediately following this ')' applies to the group.
            if i + 1 < n:
                qlen, dangerous = _quant_at(pattern, i + 1)
                if qlen and dangerous and inner_has_quant:
                    return False, "nested quantifier (quantified group containing a quantifier)"
                if qlen:
                    # the group itself is now quantified → propagate as a quantifier
                    # occurrence to the parent so ((a+))+ is also caught
                    inner_has_quant = inner_has_quant or dangerous
            if stack:
                stack[-1] = stack[-1] or inner_has_quant
            i += 1
            continue
        qlen, dangerous = _quant_at(pattern, i)
        if qlen:
            if stack and dangerous:
                stack[-1] = True
            i += qlen
            continue
        i += 1
    return True, "ok"


# ---------------------------------------------------------------------------- #
# Regex matching in a KILLABLE SUBPROCESS via the timeout supervisor.
# ---------------------------------------------------------------------------- #
def _timeout_supervisor_path():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "compound-v-run-with-timeout.py")


def _regex_search_batch(patterns, text, timeout_s=DEFAULT_REGEX_TIMEOUT_S):
    """Run a batch of regex searches against ``text`` in ONE killable subprocess.

    ``patterns`` is a list of ``{"idx": int, "pattern": str, "flags": int}``. Returns
    ``(matched_idxs, timed_out)``. On timeout/any worker failure the whole batch is
    reported as ``timed_out=True`` and ``matched_idxs`` is empty — the CALLER treats a
    timed-out batch as fail-closed (every pattern in it is a potential hit). Because
    Python 3.9 `re` cannot self-interrupt, the ONLY safe bound is the supervisor's
    process-group SIGKILL (AC-16)."""
    import subprocess

    if not patterns:
        return set(), False
    tmp = tempfile.mkdtemp(prefix="cv-taxonomy-rx-")
    try:
        pfile = os.path.join(tmp, "patterns.json")
        tfile = os.path.join(tmp, "text.txt")
        rfile = os.path.join(tmp, "result.json")
        # Write in UTF-8 explicitly so the worker's UTF-8 read matches even under a
        # C/POSIX locale (LANG=C in CI/cron/minimal Docker) — otherwise non-ASCII
        # i18n/a11y/legal_copy scan text would raise UnicodeEncodeError and CRASH the
        # scan instead of fail-closing, on exactly the content this module scans.
        with open(pfile, "w", encoding="utf-8") as fh:
            json.dump(patterns, fh)
        with open(tfile, "w", encoding="utf-8") as fh:
            fh.write(text)
        cmd = [
            sys.executable, os.path.abspath(__file__), "--regex-search",
            "--patterns-file", pfile, "--text-file", tfile,
        ]
        sup = _timeout_supervisor_path()
        full = [
            sys.executable, sup,
            "--timeout", str(int(timeout_s)), "--grace", "1",
            "--stdout", rfile, "--max-output-bytes", str(_REGEX_RESULT_CAP_BYTES),
            "--",
        ] + cmd
        # The supervisor runs the worker with stdin=DEVNULL, in its own process group,
        # and SIGKILLs the whole group on timeout — the killable-subprocess guarantee.
        proc = subprocess.run(full, stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if proc.returncode != 0:
            return set(), True  # 124 timeout OR any worker error → fail-closed
        try:
            with open(rfile, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return set(int(x) for x in data.get("matched", [])), False
        except (ValueError, OSError):
            return set(), True
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def _regex_worker(patterns_file, text_file):
    """Internal worker (runs UNDER the timeout supervisor). Prints {"matched":[idx,...]}."""
    with open(patterns_file, "r", encoding="utf-8") as fh:
        patterns = json.load(fh)
    with open(text_file, "rb") as fh:
        text = fh.read().decode("utf-8", errors="replace")
    matched = []
    for p in patterns:
        try:
            if re.search(p["pattern"], text, p.get("flags", 0)) is not None:
                matched.append(p["idx"])
        except re.error:
            continue  # an un-compilable pattern never "matches"
    sys.stdout.write(json.dumps({"matched": matched}))
    return 0


# ---------------------------------------------------------------------------- #
# In-process literal / glob content matching (bounded, safe).
# ---------------------------------------------------------------------------- #
def _content_glob_to_regex(glob):
    out = []
    for c in glob:
        if c == "*":
            out.append(".*")
        elif c == "?":
            out.append(".")
        else:
            out.append(re.escape(c))
    return "".join(out)


def _literal_hit(text, needle, case):
    if case == "insensitive":
        return needle.lower() in text.lower()
    return needle in text


def _glob_hit(text, glob, case):
    flags = re.IGNORECASE if case == "insensitive" else 0
    return re.search(_content_glob_to_regex(glob), text, flags) is not None


# ---------------------------------------------------------------------------- #
# Loading + normalization.
# ---------------------------------------------------------------------------- #
def _as_list(v):
    return v if isinstance(v, list) else ([] if v is None else [v])


def load_taxonomy(path=None, text=None):
    """Load + normalize a taxonomy from a file path OR raw text. Returns a dict with
    always-present sections. Tolerant: structural validation (bands/kinds/regex safety)
    is B1's `compound-v-validate-taxonomy.py`; this loader only normalizes shape."""
    if text is None:
        if path is None:
            raise ValueError("load_taxonomy needs path= or text=")
        with open(path, "r", encoding="utf-8") as fh:  # explicit UTF-8 (matches the rb digest path)
            text = fh.read()
    data = load_yaml(text)
    if not isinstance(data, dict):
        raise ValueError("taxonomy root is not a mapping")

    norm = {
        "version": data.get("version"),
        "path_patterns": [],
        "content_patterns": [],
        "sensitive_path_list": [str(g) for g in _as_list(data.get("sensitive_path_list"))],
        # v3.4.1 §A5 — paths whose CONTENT is never scanned for content_patterns. Optional
        # and DEFAULT EMPTY, so a taxonomy that predates this release behaves exactly as it
        # did. Path rows still apply to an excluded path; only the content scan is skipped.
        "content_scan_exclude": [
            str(g) for g in _as_list(data.get("content_scan_exclude"))],
        "auto_route_allow": [str(g) for g in _as_list(data.get("auto_route_allow"))],
        "auto_route_max_lines": _auto_route_max_lines(data.get("auto_route_max_lines")),
        "churn": {"exclude_paths": [], "format_commit_patterns": []},
    }
    for row in _as_list(data.get("path_patterns")):
        if isinstance(row, dict) and row.get("glob"):
            norm["path_patterns"].append({
                "glob": str(row.get("glob")),
                "difficulty_band": row.get("difficulty_band"),
                "impact_band": row.get("impact_band"),
            })
    for row in _as_list(data.get("content_patterns")):
        if isinstance(row, dict) and row.get("match") is not None:
            norm["content_patterns"].append({
                "match": str(row.get("match")),
                "pattern_type": (row.get("pattern_type") or "literal"),
                "case": (row.get("case") or "sensitive"),
                "scan": (row.get("scan") or "content"),
                "kind": row.get("kind"),
                "impact_band": row.get("impact_band"),
            })
    churn = data.get("churn")
    if isinstance(churn, dict):
        norm["churn"]["exclude_paths"] = [str(g) for g in _as_list(churn.get("exclude_paths"))]
        norm["churn"]["format_commit_patterns"] = [
            str(g) for g in _as_list(churn.get("format_commit_patterns"))
        ]
    return norm


# ---------------------------------------------------------------------------- #
# Matchers — documented return shapes.
# ---------------------------------------------------------------------------- #
def match_path(taxonomy, path):
    """Match a repo-relative path against path_patterns + sensitive_path_list.

    Returns:
      {"path": str,
       "matched": [ {glob, difficulty_band, impact_band, broad}, ... ],  # rows that matched
       "sensitive": bool,                                          # a sensitive_path_list hit
       "difficulty_band": band|None,   # conservative-max over matched rows
       "impact_band": band|None}

    Each matched row is a COPY carrying `broad` (v3.4.1 §A1, `glob_is_broad`) — a copy so
    that the loaded taxonomy's own rows are never mutated by a match, and per-row rather
    than once for the path because the scorer's demotion signal is "EVERY row that produced
    these bands was broad": one specifically-named row among them is enough to say the
    taxonomy meant this file.
    """
    matched = [dict(row, broad=glob_is_broad(row["glob"]))
               for row in taxonomy.get("path_patterns", [])
               if glob_match(path, row["glob"])]
    sensitive = any(glob_match(path, g) for g in taxonomy.get("sensitive_path_list", []))
    return {
        "path": path,
        "matched": matched,
        "sensitive": sensitive,
        "difficulty_band": max_band(r.get("difficulty_band") for r in matched),
        "impact_band": max_band(r.get("impact_band") for r in matched),
    }


def content_scan_excluded(taxonomy, path):
    """v3.4.1 §A5 — True iff `path` matches one of the taxonomy's `content_scan_exclude`
    globs, i.e. its CONTENT must not be matched against `content_patterns`. Path rows and
    `sensitive_path_list` are unaffected: this suppresses one signal, never a protection."""
    if not path:
        return False
    return any(glob_match(path, g)
               for g in (taxonomy or {}).get("content_scan_exclude", []))


def _auto_route_max_lines(raw):
    """Normalize `auto_route_max_lines`. Absent -> the spec default (20). Malformed (a bool, a
    non-int, a negative) -> 0, i.e. no change fits the budget. Fail-closed, never permissive."""
    if raw is None:
        return DEFAULT_AUTO_ROUTE_MAX_LINES
    if isinstance(raw, bool):
        return 0
    if isinstance(raw, int):
        return raw if raw >= 0 else 0
    if isinstance(raw, str):
        try:
            v = int(raw.strip())
        except ValueError:
            return 0
        return v if v >= 0 else 0
    return 0


def auto_route_sensitive_globs(taxonomy):
    """The sensitive set as auto-route sees it: everything the taxonomy declares PLUS the
    MANDATORY_SENSITIVE policy-file floor. Order-stable, de-duplicated."""
    out = []
    for g in list(taxonomy.get("sensitive_path_list", [])) + list(MANDATORY_SENSITIVE):
        if g not in out:
            out.append(g)
    return out


def taxonomy_self_protects(taxonomy):
    """True when the taxonomy's OWN declared sensitive_path_list already covers every
    MANDATORY_SENSITIVE policy file (spec §A4.5). False means the code floor is doing the work
    and the taxonomy should be fixed — reportable, never silently tolerated."""
    declared = taxonomy.get("sensitive_path_list", [])
    return all(any(glob_match(p, g) for g in declared) for p in MANDATORY_SENSITIVE)


def match_auto_route(taxonomy, path):
    """Spec §A4 predicates 4 and 5 for ONE repo-relative path — the single implementation
    every consumer (triage, the post-diff re-validation, the reclassifier) calls instead of
    re-deriving membership.

    Fail-closed throughout: an absent/empty `auto_route_allow` grants nothing, and sensitivity
    is evaluated against `auto_route_sensitive_globs` (taxonomy + mandatory policy floor), so
    the class can never be widened by an edit to the policy file it is authorizing.

    Returns:
      {"path": str,
       "allowed": bool,          # predicate 4 — matches auto_route_allow
       "sensitive": bool,        # predicate 5 — matches the sensitive set (floor included)
       "eligible": bool,         # allowed AND NOT sensitive
       "max_lines": int,         # the line budget predicate 8 re-checks post-diff
       "reasons": [str, ...]}    # why NOT eligible; empty when eligible
    """
    allow = taxonomy.get("auto_route_allow", []) or []
    allowed = any(glob_match(path, g) for g in allow)
    sensitive = any(glob_match(path, g) for g in auto_route_sensitive_globs(taxonomy))
    reasons = []
    if not allow:
        reasons.append("auto_route_allow is empty (fail-closed: nothing auto-routes)")
    elif not allowed:
        reasons.append("path matches no auto_route_allow entry (predicate 4)")
    if sensitive:
        reasons.append("path matches the sensitive set (predicate 5)")
    return {
        "path": path,
        "allowed": allowed,
        "sensitive": sensitive,
        "eligible": bool(allowed and not sensitive),
        "max_lines": _auto_route_max_lines(taxonomy.get("auto_route_max_lines")),
        "reasons": reasons,
    }


def match_content(taxonomy, text, scan="content", regex_timeout_s=DEFAULT_REGEX_TIMEOUT_S):
    """Match text against content_patterns whose ``scan`` equals ``scan`` (default
    'content'; pass a path as ``text`` with scan='path' to match path-scanned content
    patterns). regex patterns run in the killable subprocess; a timed-out batch is
    reported fail-closed (every regex pattern in the batch becomes a `timed_out` hit).

    Returns a list of hit dicts:
      {"kind": str|None, "impact_band": band|None, "pattern_type": str,
       "match": str, "timed_out": bool}
    """
    hits = []
    regex_batch = []      # {"idx", "pattern", "flags"} for the subprocess
    regex_meta = []       # parallel: the source pattern dict for each idx
    for pat in taxonomy.get("content_patterns", []):
        if (pat.get("scan") or "content") != scan:
            continue
        ptype = pat.get("pattern_type") or "literal"
        case = pat.get("case") or "sensitive"
        needle = pat.get("match", "")
        if ptype == "literal":
            if _literal_hit(text, needle, case):
                hits.append(_mk_hit(pat, False))
        elif ptype == "glob":
            if _glob_hit(text, needle, case):
                hits.append(_mk_hit(pat, False))
        elif ptype == "regex":
            ok, _ = is_safe_regex(needle)
            if not ok:
                # An unsafe pattern is never trusted to run — fail-closed hit.
                hits.append(_mk_hit(pat, True))
                continue
            idx = len(regex_meta)
            flags = re.IGNORECASE if case == "insensitive" else 0
            regex_batch.append({"idx": idx, "pattern": needle, "flags": flags})
            regex_meta.append(pat)
        else:
            # Unknown pattern_type → fail-closed hit (never silently ignored).
            hits.append(_mk_hit(pat, True))

    if regex_batch:
        matched, timed_out = _regex_search_batch(regex_batch, text, regex_timeout_s)
        for i, pat in enumerate(regex_meta):
            if timed_out:
                hits.append(_mk_hit(pat, True))     # fail-closed: whole batch unproven
            elif i in matched:
                hits.append(_mk_hit(pat, False))
    return hits


def _mk_hit(pat, timed_out):
    return {
        "kind": pat.get("kind"),
        "impact_band": pat.get("impact_band"),
        "pattern_type": pat.get("pattern_type") or "literal",
        "match": pat.get("match", ""),
        "timed_out": bool(timed_out),
    }


def classify(taxonomy, path=None, content=None, regex_timeout_s=DEFAULT_REGEX_TIMEOUT_S):
    """Combine path + content signals into a normalized classification. Impact is
    conservative-max across path rows AND content hits (content may only RAISE impact,
    never lower it). Difficulty is taxonomy-path primary. The scoring engine (A3) layers
    the truth-table / overrides on top of this; this only reports matched evidence.

    Returns:
      {"difficulty_band": band|None, "impact_band": band|None, "sensitive": bool,
       "flags": [str, ...],           # sensitive_path + distinct content kinds (+ regex_timeout)
       "content_hits": [hit, ...], "path_matched": bool}
    """
    pflags = []
    difficulty = impact = None
    sensitive = False
    path_matched = False
    if path is not None:
        pr = match_path(taxonomy, path)
        difficulty = pr["difficulty_band"]
        impact = pr["impact_band"]
        sensitive = pr["sensitive"]
        path_matched = bool(pr["matched"])
        if sensitive:
            pflags.append("sensitive_path")

    content_hits = []
    # v3.4.1 §A5 — content patterns do not apply to prose. A path listed in
    # `content_scan_exclude` keeps its PATH rows (and its `sensitive_path` flag) but its
    # text is never matched: the words a compliance pattern looks for ("consent", "price",
    # "timeout") occur in ordinary documentation, and treating a README paragraph as a
    # legal-copy hit is how a typo fix scored `high` impact.
    if content is not None and path is not None and content_scan_excluded(taxonomy, path):
        content = None
    if content is not None:
        content_hits = match_content(taxonomy, content, scan="content",
                                     regex_timeout_s=regex_timeout_s)
        impact = max_band([impact] + [h.get("impact_band") for h in content_hits])
        seen = set()
        for h in content_hits:
            k = h.get("kind")
            if k and k not in seen:
                seen.add(k)
                pflags.append("content:%s" % k)
            if h.get("timed_out"):
                if "regex_timeout" not in pflags:
                    pflags.append("regex_timeout")

    return {
        "difficulty_band": difficulty,
        "impact_band": impact,
        "sensitive": sensitive,
        "flags": pflags,
        "content_hits": content_hits,
        "path_matched": path_matched,
    }


# ---------------------------------------------------------------------------- #
# Digest convention (CR5-6 / CR5-7). Precisely documented in pre-eval-config.md.
# ---------------------------------------------------------------------------- #
def canonical_json(obj):
    """Deterministic canonical JSON: recursively key-sorted, compact separators,
    UTF-8-preserving, NaN-forbidden. THE single encoding all v2.9 digests use."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def sha256_hex(data_bytes):
    return hashlib.sha256(data_bytes).hexdigest()


def record_digest(obj, exclude_field="digest"):
    """Canonical-JSON digest of a record, EXCLUDING its own self-digest field so a
    record can carry its own digest without a chicken-and-egg. Returns 'sha256:<hex>'."""
    if not isinstance(obj, dict):
        raise ValueError("record_digest expects a dict")
    payload = {k: v for k, v in obj.items() if k != exclude_field}
    return "sha256:" + sha256_hex(canonical_json(payload).encode("utf-8"))


def taxonomy_digest_bytes(data_bytes):
    """Content-address of an immutable taxonomy SNAPSHOT: 'sha256:<hex>' over the RAW
    bytes (not a re-serialization — the snapshot file is byte-for-byte immutable)."""
    return "sha256:" + sha256_hex(data_bytes)


def taxonomy_digest_file(path):
    with open(path, "rb") as fh:
        return taxonomy_digest_bytes(fh.read())


# ---------------------------------------------------------------------------- #
# CLI.
# ---------------------------------------------------------------------------- #
def main(argv):
    if "--selftest" in argv[1:]:
        return _selftest()

    parser = argparse.ArgumentParser(prog="compound-v-taxonomy.py")
    parser.add_argument("taxonomy", nargs="?", help="taxonomy YAML path")
    parser.add_argument("--digest", metavar="PATH", help="print the snapshot digest of PATH")
    parser.add_argument("--regex-search", action="store_true",
                        help="internal killable-subprocess regex worker")
    parser.add_argument("--patterns-file")
    parser.add_argument("--text-file")
    args = parser.parse_args(argv[1:])

    if args.regex_search:
        if not args.patterns_file or not args.text_file:
            sys.stderr.write("--regex-search needs --patterns-file and --text-file\n")
            return 2
        return _regex_worker(args.patterns_file, args.text_file)

    if args.digest:
        print(taxonomy_digest_file(args.digest))
        return 0

    if not args.taxonomy:
        sys.stderr.write("usage: compound-v-taxonomy.py <taxonomy.yaml> | --selftest\n")
        return 2
    try:
        tax = load_taxonomy(path=args.taxonomy)
    except (ValueError, OSError, RuntimeError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        return 1
    print(json.dumps(tax, indent=2))
    return 0


# ---------------------------------------------------------------------------- #
# Self-test.
# ---------------------------------------------------------------------------- #
_EXAMPLE_TAXONOMY = """
version: 1
path_patterns:
  - glob: "src/auth/**"
    difficulty_band: high
    impact_band: high
  - glob: "src/ui/**"
    difficulty_band: low
    impact_band: low
  - glob: "src/**"
    difficulty_band: medium
    impact_band: medium
content_patterns:
  - match: "aria-label"
    pattern_type: literal
    case: sensitive
    scan: content
    kind: a11y
    impact_band: high
  - match: "{{*}}"
    pattern_type: glob
    case: sensitive
    scan: content
    kind: i18n_placeholder
    impact_band: high
  - match: "feature_flag\\\\s*=\\\\s*\\\\w+"
    pattern_type: regex
    case: sensitive
    scan: content
    kind: feature_flag
    impact_band: high
sensitive_path_list:
  - "src/auth/**"
  - "**/migrations/**"
churn:
  exclude_paths:
    - "**/*.min.js"
  format_commit_patterns:
    - "^chore"
"""


_AUTO_ROUTE_TAXONOMY = """
version: 1
sensitive_path_list:
  - "docs/secrets/**"
auto_route_allow:
  - "CHANGELOG.md"
  - "docs/**/*.md"
auto_route_max_lines: 12
churn:
  exclude_paths:
    - "**/*.min.js"
  format_commit_patterns:
    - "^chore"
"""

# A DELIBERATELY BAD seed: it allows the policy file and never lists it as sensitive. This is
# the §A4.8 self-widening attack expressed as a taxonomy; MANDATORY_SENSITIVE must refuse it.
_SELF_WIDENING_TAXONOMY = """
version: 1
sensitive_path_list:
  - "src/auth/**"
auto_route_allow:
  - ".claude/**"
churn:
  exclude_paths:
    - "**/*.min.js"
  format_commit_patterns:
    - "^chore"
"""


# v3.4.1 §A1/§A5 breadth + content-scan exclusion fixture. Four path rows chosen so that
# "broad" is decided by the GLOB's shape and nothing else: `scripts/**` contains `**`,
# `lib/*` ends in `/*`, while `scripts/one.py` and `docs/*.md` name a bounded set.
_BREADTH_TAXONOMY = """
version: 1
path_patterns:
  - glob: "scripts/**"
    difficulty_band: high
    impact_band: high
  - glob: "scripts/one.py"
    difficulty_band: medium
    impact_band: low
  - glob: "lib/*"
    difficulty_band: low
    impact_band: low
  - glob: "docs/*.md"
    difficulty_band: low
    impact_band: low
content_patterns:
  - match: "privacy policy"
    pattern_type: literal
    case: insensitive
    scan: content
    kind: legal_copy
    impact_band: high
sensitive_path_list:
  - "**/*.env"
content_scan_exclude:
  - "**/*.md"
churn:
  exclude_paths: []
  format_commit_patterns: []
"""


def _selftest():
    import time

    failures = []

    def expect(name, cond):
        print(("  ok   - " if cond else "  FAIL - ") + name)
        if not cond:
            failures.append(name)

    # --- bands ---
    expect("max_band conservative-max", max_band(["low", "high", "medium"]) == "high")
    expect("max_band ignores unknown/None", max_band([None, "low", "bogus"]) == "low")
    expect("max_band all-invalid -> None", max_band([None, "x"]) is None)

    # --- load + normalize ---
    tax = load_taxonomy(text=_EXAMPLE_TAXONOMY)
    expect("loads 3 path_patterns", len(tax["path_patterns"]) == 3)
    expect("loads 3 content_patterns", len(tax["content_patterns"]) == 3)
    expect("loads sensitive_path_list", "src/auth/**" in tax["sensitive_path_list"])
    expect("loads churn excludes", tax["churn"]["exclude_paths"] == ["**/*.min.js"])

    # --- match_path (conservative-max + sensitive) ---
    mp = match_path(tax, "src/auth/login.ts")
    expect("auth path is sensitive", mp["sensitive"] is True)
    expect("auth path conservative-max difficulty=high", mp["difficulty_band"] == "high")
    expect("auth path impact=high", mp["impact_band"] == "high")
    mp2 = match_path(tax, "src/ui/button.css")
    expect("ui path not sensitive", mp2["sensitive"] is False)
    expect("ui path conservative-max over ui+src -> medium",
           mp2["difficulty_band"] == "medium")
    mp3 = match_path(tax, "db/migrations/003.sql")
    expect("migrations path is sensitive (glob **/migrations/**)", mp3["sensitive"] is True)
    mp4 = match_path(tax, "README.md")
    expect("unmatched path -> None bands", mp4["difficulty_band"] is None)

    # --- v3.4.1 §A1 — BREADTH is a property of the glob, reported per matched row ----- #
    # `broad` is what the scoring engine (compound-v-preeval.py) reads to decide whether
    # T1's bands came from a "everything under here" pattern and may therefore be handed
    # to the T3 demotion. The engine-side cells for that demotion, for `scoped_plus`,
    # for `new_file` and for NEVER_DEMOTE_GLOBS live in compound-v-preeval.py's selftest;
    # what is under test HERE is only the signal those cells consume.
    btax = load_taxonomy(text=_BREADTH_TAXONOMY)
    b_one = match_path(btax, "scripts/one.py")
    expect("breadth: a path matching both a broad and a specific row keeps both rows",
           len(b_one["matched"]) == 2)
    expect("breadth: `scripts/**` is broad (contains **)",
           [r["broad"] for r in b_one["matched"] if r["glob"] == "scripts/**"] == [True])
    expect("breadth: `scripts/one.py` is NOT broad (a named file)",
           [r["broad"] for r in b_one["matched"] if r["glob"] == "scripts/one.py"] == [False])
    expect("breadth: not every row broad -> the engine's all() signal is False",
           all(r["broad"] for r in b_one["matched"]) is False)
    b_two = match_path(btax, "scripts/two.py")
    expect("breadth: a path matched ONLY by a ** row is broad throughout",
           len(b_two["matched"]) == 1 and b_two["matched"][0]["broad"] is True)
    expect("breadth: a glob ending in `/*` is broad",
           match_path(btax, "lib/a.txt")["matched"][0]["broad"] is True)
    expect("breadth: `docs/*.md` is NOT broad (bounded segment + extension)",
           match_path(btax, "docs/x.md")["matched"][0]["broad"] is False)
    expect("breadth: match_path does NOT mutate the loaded taxonomy rows",
           all("broad" not in r for r in btax["path_patterns"]))
    expect("breadth: bands are unchanged by the new key",
           b_one["difficulty_band"] == "high" and b_one["impact_band"] == "high")

    # --- v3.4.1 §A5 — content_scan_exclude: content patterns do not apply to prose --- #
    expect("content_scan_exclude loads", btax["content_scan_exclude"] == ["**/*.md"])
    expect("content_scan_exclude absent -> empty (every other repo unchanged)",
           tax["content_scan_exclude"] == [])
    c_md = classify(btax, path="docs/x.md", content="see our privacy policy for details")
    expect("content_scan_exclude: an excluded path runs NO content scan",
           c_md["content_hits"] == [] and c_md["flags"] == [])
    expect("content_scan_exclude: the excluded path keeps its PATH bands",
           c_md["impact_band"] == "low" and c_md["difficulty_band"] == "low")
    c_code = classify(btax, path="lib/a.txt", content="see our privacy policy for details")
    expect("content_scan_exclude: a non-excluded path still scans content",
           "content:legal_copy" in c_code["flags"] and c_code["impact_band"] == "high")
    c_nopath = classify(btax, path=None, content="see our privacy policy for details")
    expect("content_scan_exclude: no path -> nothing to exclude, the scan still runs",
           "content:legal_copy" in c_nopath["flags"])

    # --- v3.0 §A4 auto-route class (predicates 4, 5 and the line budget) ---
    # A taxonomy with NO auto_route_* keys is the pre-3.0 shape: it must grant nothing and
    # report the spec default budget.
    expect("no auto_route_allow key -> empty allow list", tax["auto_route_allow"] == [])
    expect("no auto_route_max_lines key -> spec default 20",
           tax["auto_route_max_lines"] == DEFAULT_AUTO_ROUTE_MAX_LINES)
    ar_none = match_auto_route(tax, "CHANGELOG.md")
    expect("absent auto_route_allow -> not eligible (fail-closed)", ar_none["eligible"] is False)
    expect("absent auto_route_allow -> says so", any("empty" in r for r in ar_none["reasons"]))

    ar_tax = load_taxonomy(text=_AUTO_ROUTE_TAXONOMY)
    expect("auto_route_allow loads", ar_tax["auto_route_allow"] == ["CHANGELOG.md", "docs/**/*.md"])
    expect("auto_route_max_lines loads", ar_tax["auto_route_max_lines"] == 12)
    ok_row = match_auto_route(ar_tax, "CHANGELOG.md")
    expect("allowed + non-sensitive -> eligible", ok_row["eligible"] is True)
    expect("eligible row carries no reasons", ok_row["reasons"] == [])
    expect("eligible row carries the line budget", ok_row["max_lines"] == 12)
    expect("recursive allow glob matches", match_auto_route(ar_tax, "docs/a/b.md")["eligible"] is True)
    expect("unlisted path not eligible (predicate 4)",
           match_auto_route(ar_tax, "scripts/x.py")["eligible"] is False)
    both = match_auto_route(ar_tax, "docs/secrets/deploy.md")
    expect("allowed BUT sensitive -> not eligible (predicate 5 wins)", both["eligible"] is False)
    expect("sensitive-wins reason names predicate 5",
           any("sensitive" in r for r in both["reasons"]))

    # The §A4.8 attack: a taxonomy that ALLOWS the policy file and forgets to list it as
    # sensitive must STILL be refused — MANDATORY_SENSITIVE is a code floor the YAML can only
    # add to, never remove.
    attack = load_taxonomy(text=_SELF_WIDENING_TAXONOMY)
    atk = match_auto_route(attack, ".claude/compound-v-impact-taxonomy.yaml")
    expect("policy file allowed by a bad seed is STILL sensitive (mandatory floor)",
           atk["sensitive"] is True)
    expect("policy file can never be auto-routed (A4.8 self-widening closed)",
           atk["eligible"] is False)
    expect("the other policy file is floored too",
           match_auto_route(attack, ".claude/compound-v.json")["sensitive"] is True)
    expect("taxonomy_self_protects False when the seed omits the policy rows",
           taxonomy_self_protects(attack) is False)

    # Malformed budgets are floored to 0, never defaulted to a permissive 20.
    expect("malformed max_lines (string junk) -> 0",
           load_taxonomy(text="version: 1\nauto_route_max_lines: \"abc\"\n")["auto_route_max_lines"] == 0)
    expect("negative max_lines -> 0", _auto_route_max_lines(-1) == 0)
    expect("bool max_lines -> 0 (True is not 1 here)", _auto_route_max_lines(True) == 0)
    expect("numeric-string max_lines parses", _auto_route_max_lines("15") == 15)
    expect("absent max_lines -> spec default", _auto_route_max_lines(None) == 20)

    # --- dogfood: THIS repo's own taxonomy, when present ---
    _repo_tax = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             ".claude", "compound-v-impact-taxonomy.yaml")
    if os.path.isfile(_repo_tax):
        rt = load_taxonomy(path=_repo_tax)
        expect("repo taxonomy declares its own policy self-protection",
               taxonomy_self_protects(rt) is True)
        expect("repo taxonomy: CHANGELOG.md is auto-routable",
               match_auto_route(rt, "CHANGELOG.md")["eligible"] is True)
        expect("repo taxonomy: a skill doc is sensitive, not auto-routable",
               match_auto_route(rt, "skills/compound-v/SKILL.md")["eligible"] is False)
        expect("repo taxonomy: an engine script is not auto-routable",
               match_auto_route(rt, "scripts/compound-v-preeval.py")["eligible"] is False)
        expect("repo taxonomy: README.md scores a real (non-unknown) band",
               match_path(rt, "README.md")["impact_band"] == "low")
        # v3.4.1 §A5: this repository excludes markdown from the content scan, which is what
        # stops a README typo reading `high` off the word "consent" in a paragraph of prose.
        expect("repo taxonomy: content_scan_exclude covers markdown",
               rt["content_scan_exclude"] == ["**/*.md"])
        expect("repo taxonomy: a README paragraph mentioning legal words scores NO "
               "content flag (the exclusion suppressed the scan)",
               classify(rt, path="README.md",
                        content="you consent to the privacy policy")["flags"] == [])
        expect("repo taxonomy: the same prose in a NON-excluded path still flags",
               "content:legal_copy" in classify(
                   rt, path="lib/notice.txt",
                   content="you consent to the privacy policy")["flags"])
        # v3.4.1 §A3: the engine's NEVER_DEMOTE_GLOBS (secrets + CI) are a hard code floor;
        # this repository's taxonomy must also carry them as sensitive, or the two would
        # disagree about the same path.
        expect("repo taxonomy: every NEVER_DEMOTE glob (.pem/.key/.env/.github) is sensitive",
               all(match_path(rt, p)["sensitive"] is True
                   for p in ("deploy/server.pem", "deploy/id.key",
                             "config/app.env", ".github/workflows/ci.yml")))
    else:
        expect("repo taxonomy dogfood (skipped — .claude taxonomy absent)", True)

    # --- match_content literal + glob + regex(subprocess) ---
    hits = match_content(tax, 'button.setAttribute("aria-label", x)')
    expect("literal a11y hit", any(h["kind"] == "a11y" for h in hits))
    hits_i18n = match_content(tax, "Hello {{name}}")
    expect("glob i18n placeholder hit", any(h["kind"] == "i18n_placeholder" for h in hits_i18n))
    hits_ff = match_content(tax, "  feature_flag = enabled\n")
    expect("regex feature_flag hit (via subprocess)",
           any(h["kind"] == "feature_flag" and not h["timed_out"] for h in hits_ff))
    hits_none = match_content(tax, "nothing interesting here")
    expect("no spurious content hits", hits_none == [])

    # Non-ASCII scan text must route through the UTF-8 temp-file write/read without
    # crashing — regression guard for a C/POSIX-locale UnicodeEncodeError on exactly
    # the i18n/a11y/legal content this module scans. The shell harness re-runs this
    # whole selftest under LANG=C/PYTHONUTF8=0 to prove the locale independence.
    non_ascii = 'café — feature_flag = enabléd — {{prénom}} setAttribute("aria-label","x")'
    hits_na = match_content(tax, non_ascii)
    expect("non-ASCII regex-scan finds feature_flag (no crash under any locale)",
           any(h["kind"] == "feature_flag" and not h["timed_out"] for h in hits_na))
    expect("non-ASCII scan also finds literal a11y + glob i18n",
           any(h["kind"] == "a11y" for h in hits_na)
           and any(h["kind"] == "i18n_placeholder" for h in hits_na))

    # --- classify combines path + content (impact only RAISES) ---
    c = classify(tax, path="src/ui/button.css",
                 content='el.setAttribute("aria-label","x")')
    expect("classify: content raises impact to high", c["impact_band"] == "high")
    expect("classify: a11y flag surfaced", "content:a11y" in c["flags"])
    expect("classify: difficulty stays taxonomy-path (medium)", c["difficulty_band"] == "medium")

    # --- is_safe_regex: reject nested quantifiers, accept the safe subset ---
    unsafe = ["(a+)+", "(a+)*", "(a*)*", "((a+))+", "(a+){2,}", "(.*)+$", "([a-z]+)+"]
    for p in unsafe:
        ok, reason = is_safe_regex(p)
        expect("unsafe rejected: %s" % p, ok is False)
    safe = ["aria-label", r"\{\{\s*\w+\s*\}\}", "%[sd]", "(true|false)", "(abc)+",
            "(a+)?", r"feature_flag\s*=\s*\w+", r"\bTODO\b", "a{2,4}", "[A-Z]{3}",
            "colou?r", r"x\+y"]
    for p in safe:
        ok, reason = is_safe_regex(p)
        expect("safe accepted: %s (%s)" % (p, reason), ok is True)
    expect("non-compiling regex rejected", is_safe_regex("(unclosed")[0] is False)
    expect("over-long regex rejected", is_safe_regex("a" * (MAX_REGEX_LEN + 1))[0] is False)

    # --- ADVERSARIAL nested-quantifier fixture MUST terminate within a fixed bound ---
    # Bypass validation and drive the catastrophic pattern straight through the
    # killable subprocess. Without the process-group SIGKILL this backtracks for
    # ages; the supervisor bounds it to ~timeout+grace and reports timed_out.
    evil_pattern = [{"idx": 0, "pattern": "(a+)+$", "flags": 0}]
    evil_text = "a" * 40 + "!"
    t0 = time.time()
    matched, timed_out = _regex_search_batch(evil_pattern, evil_text, timeout_s=2)
    elapsed = time.time() - t0
    expect("adversarial regex terminates within a fixed bound (<8s wall)", elapsed < 8)
    expect("adversarial regex reported timed_out (fail-closed)", timed_out is True)
    expect("adversarial regex matched nothing (killed, not completed)", matched == set())
    # And through the public API: an unsafe pattern in the taxonomy → fail-closed hit
    # WITHOUT even running (rejected by is_safe_regex).
    evil_tax = {"content_patterns": [{"match": "(a+)+$", "pattern_type": "regex",
                                      "case": "sensitive", "scan": "content",
                                      "kind": "config_literal", "impact_band": "high"}]}
    ev_hits = match_content(evil_tax, evil_text)
    expect("unsafe taxonomy regex -> fail-closed timed_out hit (never executed)",
           len(ev_hits) == 1 and ev_hits[0]["timed_out"] is True)

    # --- digest convention ---
    a = {"b": 2, "a": 1, "nested": {"y": 2, "x": 1}}
    b = {"a": 1, "nested": {"x": 1, "y": 2}, "b": 2}
    expect("canonical_json is key-order-independent", canonical_json(a) == canonical_json(b))
    expect("canonical_json is compact + sorted",
           canonical_json(a) == '{"a":1,"b":2,"nested":{"x":1,"y":2}}')
    rec = {"pre_eval_id": "x", "decision": "FULL_PIPELINE", "digest": "sha256:STALE"}
    d1 = record_digest(rec, exclude_field="digest")
    rec2 = dict(rec)
    rec2["digest"] = "sha256:DIFFERENT"
    expect("record_digest excludes the self-digest field",
           d1 == record_digest(rec2, exclude_field="digest"))
    expect("record_digest is sha256-prefixed", d1.startswith("sha256:"))
    expect("record_digest changes when a real field changes",
           d1 != record_digest({"pre_eval_id": "y", "decision": "FULL_PIPELINE"},
                               exclude_field="digest"))
    expect("taxonomy_digest_bytes over raw bytes",
           taxonomy_digest_bytes(b"abc") == "sha256:" + sha256_hex(b"abc"))
    expect("taxonomy_digest stable for identical bytes",
           taxonomy_digest_bytes(b"same") == taxonomy_digest_bytes(b"same"))

    # --- schema representability: absent-taxonomy FULL_PIPELINE record validates ---
    try:
        import jsonschema
        here = os.path.dirname(os.path.abspath(__file__))
        schema_path = os.path.join(os.path.dirname(here), "schemas",
                                   "pre-eval-record.schema.json")
        with open(schema_path, "r", encoding="utf-8") as fh:
            schema = json.load(fh)

        absent = {
            "pre_eval_id": "2026-07-12T101500Z-no-taxonomy-a1", "request_slug": "no-taxonomy",
            "ts": "2026-07-12T10:15:00Z", "status": "PRE_EVAL_DONE",
            "taxonomy_version": None, "taxonomy_ref": None, "taxonomy_digest": None,
            "difficulty": {"band": "unknown"}, "impact": {"band": "unknown"},
            "tiers_signalled": [], "override_fired": None, "decision": "FULL_PIPELINE",
            "min_sample_status": "insufficient",
            "localization": {"resolved_paths": [], "fan_out": 0, "flags": [],
                             "confidence": "failed"},
        }
        jsonschema.validate(absent, schema)  # must NOT raise (nullable taxonomy fields)
        expect("absent-taxonomy FULL_PIPELINE record validates against the schema", True)

        # A FASTPATH_ELIGIBLE record with a null taxonomy MUST fail (the if/then guard).
        elig_null = dict(absent)
        elig_null["decision"] = "FASTPATH_ELIGIBLE"
        try:
            jsonschema.validate(elig_null, schema)
            elig_null_ok = False
        except jsonschema.ValidationError:
            elig_null_ok = True
        expect("FASTPATH_ELIGIBLE with null taxonomy is REJECTED (if/then guard)",
               elig_null_ok)

        # A proper FASTPATH_ELIGIBLE record (real snapshot + digest) validates.
        elig_ok = {
            "pre_eval_id": "2026-07-12T101500Z-make-button-red-a1b2",
            "request_slug": "make-button-red", "ts": "2026-07-12T10:15:00Z",
            "status": "PRE_EVAL_DONE", "taxonomy_version": 1,
            "taxonomy_ref": "docs/superpowers/execution/r/taxonomy-snapshot.yaml",
            "taxonomy_digest": "sha256:" + "0" * 64,
            "difficulty": {"band": "low", "display": 2}, "impact": {"band": "low", "display": 2},
            "tiers_signalled": ["T1", "localization"], "override_fired": None,
            "decision": "FASTPATH_ELIGIBLE", "min_sample_status": "insufficient",
            "localization": {"resolved_paths": ["src/ui/button.css"], "fan_out": 1,
                             "flags": [], "confidence": "exact"},
        }
        jsonschema.validate(elig_ok, schema)
        expect("valid FASTPATH_ELIGIBLE record (real snapshot) validates", True)
    except ImportError:
        expect("schema validation (skipped — jsonschema not installed)", True)

    if failures:
        print("\nSELFTEST FAILED: %d case(s)" % len(failures))
        return 1
    print("\nSELFTEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
