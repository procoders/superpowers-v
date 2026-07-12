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
    churn: {exclude_paths: ["**/*.min.js"], format_commit_patterns: ["^chore\\(fmt\\)"]}

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
       "matched": [ {glob, difficulty_band, impact_band}, ... ],   # rows that matched
       "sensitive": bool,                                          # a sensitive_path_list hit
       "difficulty_band": band|None,   # conservative-max over matched rows
       "impact_band": band|None}
    """
    matched = [row for row in taxonomy.get("path_patterns", [])
               if glob_match(path, row["glob"])]
    sensitive = any(glob_match(path, g) for g in taxonomy.get("sensitive_path_list", []))
    return {
        "path": path,
        "matched": matched,
        "sensitive": sensitive,
        "difficulty_band": max_band(r.get("difficulty_band") for r in matched),
        "impact_band": max_band(r.get("impact_band") for r in matched),
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
