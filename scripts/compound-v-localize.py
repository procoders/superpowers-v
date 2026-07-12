#!/usr/bin/env python3
"""
Compound V — bounded, read-only LOCALIZATION (v2.9 Task A1).

The pre-eval scoring engine (A3) is forbidden from returning any `low` verdict until a
BOUNDED read-only step has resolved the request to real repo paths, a fan-out count, and
semantic flags (Iron-Invariant #2). "make button X red" may be a global design token or an
a11y contrast state — this module DISCOVERS that before the decision, not after.

    localize(request, repo, taxonomy) -> {resolved_paths[], fan_out, flags[], confidence}
        confidence in {exact, ambiguous, failed}

It ALSO writes a committed, WRITE-ONCE localization artifact at
    docs/superpowers/pre-eval/<pre_eval_id>.localization.json
referenced by `fast_path.localization_ref`. That artifact carries this module's four fields
plus its own canonical-JSON `digest` (record_digest, exclude_field='digest'); that digest is
the value bound across manifest + pre-eval record + artifact by C1 (AC-13). The dispatcher
COMMITS it — this module NEVER runs git.

Design constraints honored (from the three audits + the plan Lifecycle protocol):
  * Python 3.9-safe, stdlib-only, soft-PyYAML fallback (delegated to the shared taxonomy
    loader — this file never does `import yaml`).
  * BOUNDED, not mini-archaeology: `rg -> git grep -> grep` DEGRADE order (never a hard
    ripgrep dependency; AC-10 / C3), a hard cap on files inspected, a per-CLI wall-clock
    timeout, a per-file read cap. Cannot resolve within the cap -> `ambiguous`
    (-> Layer-A override #1 -> FULL_PIPELINE). Zero matches / no token / all backends
    unavailable -> `failed` (also override #1). Fail-closed everywhere.
  * EVERY external CLI (rg/git/grep) is launched THROUGH the shared process-group timeout
    supervisor `compound-v-run-with-timeout.py` with stdin=DEVNULL, a killable process
    group, and an ENFORCED bounded output sink (`--max-output-bytes`, CR5-8). NEVER a bare
    `subprocess.run(timeout=...)` on an external CLI (CR3-8).
  * Classification reuses the shared Taxonomy loader (`compound-v-taxonomy.py`) — matching
    semantics are NOT reimplemented here. Flags surfaced for A3's Layer-A overrides:
    `sensitive_path` (#2), `shared_token` / `is_a11y_state` / `is_generated` (#3), plus
    `content:<kind>` evidence for feature_flag / legal_copy / i18n_placeholder /
    config_literal, and `regex_timeout` (fail-closed regex evidence).
  * Path containment (CR4-6): every resolved path is normalized, repo-relative (no absolute,
    no `..`), realpath-under-repo-root, and a committed-able REGULAR file (an escaping
    symlink is dropped) before it can appear in `resolved_paths`.

Usage:
    compound-v-localize.py --selftest
    compound-v-localize.py --request "make button X red" --repo . [--taxonomy PATH]
        [--pre-eval-id 2026-07-12T101500Z-make-button-red-a1b2 --write-artifact]
"""

import argparse
import json
import os
import re
import sys


# ---------------------------------------------------------------------------- #
# Reuse the shared siblings BY PATH (no recopy) — the taxonomy loader/matcher +
# the digest convention live in compound-v-taxonomy.py; the timeout supervisor is
# compound-v-run-with-timeout.py. Loaded lazily so an import-time hiccup never
# hard-fails this module.
# ---------------------------------------------------------------------------- #
_TAX_MODULE = None


def _load_sibling(modname, filename):
    import importlib.util

    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, filename)
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _taxonomy_module():
    global _TAX_MODULE
    if _TAX_MODULE is None:
        _TAX_MODULE = _load_sibling("compound_v_taxonomy", "compound-v-taxonomy.py")
    return _TAX_MODULE


def _supervisor_path():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "compound-v-run-with-timeout.py")


# ---------------------------------------------------------------------------- #
# Bounds (all declared tunables — the whole point is "bounded, not archaeology").
# ---------------------------------------------------------------------------- #
FILE_CAP = 25               # > this many resolved files -> ambiguous (too broad)
MAX_TOKENS = 6              # candidate query tokens searched (bounded)
SEARCH_TIMEOUT_S = 8        # per-CLI wall-clock cap (via the supervisor)
OUTPUT_CAP_BYTES = 1 << 16  # bounded CLI output sink (--max-output-bytes)
MAX_FILE_READ_BYTES = 1 << 16  # per-file content read cap for classification

BACKENDS = ("rg", "git-grep", "grep")

PRE_EVAL_ID_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{6}Z-[A-Za-z0-9._-]+-[A-Za-z0-9]+$"
)

# Built-in generated-artifact globs (matched via the shared taxonomy glob matcher —
# not a reimplementation). A generated file is a Layer-A override #3 escalation.
_GENERATED_GLOBS = (
    "**/dist/**", "dist/**", "**/build/**", "build/**", "**/out/**",
    "**/node_modules/**", "**/vendor/**", "**/generated/**", "**/__generated__/**",
    "**/*.min.js", "**/*.min.css", "**/*_pb2.py", "**/*.pb.go", "**/*.g.dart",
    "**/*.generated.*", "**/*.lock", "package-lock.json", "yarn.lock",
    "pnpm-lock.yaml", "poetry.lock", "Cargo.lock",
)
_GENERATED_MARKERS = (
    "@generated", "Code generated", "DO NOT EDIT", "autogenerated",
    "AUTO-GENERATED", "auto-generated", "This file is generated",
)

# Stopwords so token extraction stays bounded + deterministic. Colors/verbs common in
# UI-change requests are dropped so a real symbol/selector/identifier survives.
_STOPWORDS = frozenset("""
the a an and or to in on of for with make making made change changing changed update
updating updated add adding remove removing fix fixing set setting please can you it its
this that these those color colour red blue green yellow black white gray grey orange
purple pink brown bold size larger smaller bigger left right top bottom center new old
""".split())


# ---------------------------------------------------------------------------- #
# Query-token extraction (bounded, deterministic — NOT NLP).
# ---------------------------------------------------------------------------- #
def extract_query_tokens(request):
    """Extract up to MAX_TOKENS candidate symbols/selectors/tokens from free-text.

    Priority: quoted / backticked spans and CSS-ish selectors (`.btn`, `#id`, `--token`,
    `{{var}}`) first, then identifier-ish words (>=3 chars, not a stopword). Deterministic
    order, de-duplicated, capped. Empty request -> [] -> caller returns `failed`."""
    if not request or not isinstance(request, str):
        return []
    tokens = []
    seen = set()

    def _push(tok):
        tok = tok.strip()
        if not tok or tok in seen:
            return
        seen.add(tok)
        tokens.append(tok)

    # 1) quoted / backticked spans (highest signal)
    for m in re.finditer(r"[\"'`]([^\"'`]{2,64})[\"'`]", request):
        _push(m.group(1))
    # 2) CSS-ish / templating selectors and design tokens
    for m in re.finditer(r"(--[A-Za-z0-9_-]{2,}|[.#][A-Za-z_][\w-]{1,}|\{\{[^}]{1,40}\}\})",
                         request):
        _push(m.group(1))
    # 3) identifier-ish words (camelCase / snake_case / hyphenated / plain)
    for m in re.finditer(r"[A-Za-z_][A-Za-z0-9_-]{2,}", request):
        w = m.group(0)
        if w.lower() in _STOPWORDS:
            continue
        _push(w)
    return tokens[:MAX_TOKENS]


# ---------------------------------------------------------------------------- #
# Path containment (CR4-6) — reject absolute, `..`, or realpath-escaping paths.
# ---------------------------------------------------------------------------- #
def _contained_regular_file(repo, rel):
    """Return the normalized repo-relative path iff it is a repo-relative, non-escaping
    REGULAR file under `repo`; else None. Rejects absolute paths, `..` traversal, and
    escaping symlinks (realpath must stay under the repo root)."""
    if not rel or os.path.isabs(rel):
        return None
    norm = os.path.normpath(rel).replace("\\", "/").lstrip("./")
    norm = os.path.normpath(norm)
    if norm in (".", "") or norm.startswith("..") or norm.split("/")[0] == "..":
        return None
    root_real = os.path.realpath(repo)
    full_real = os.path.realpath(os.path.join(repo, norm))
    if full_real != root_real and not full_real.startswith(root_real + os.sep):
        return None
    if not os.path.isfile(full_real):
        return None
    return norm


# ---------------------------------------------------------------------------- #
# THE external-CLI boundary — every rg/git/grep goes THROUGH the supervisor.
# ---------------------------------------------------------------------------- #
def _run_cli_search(tool_argv, repo, timeout_s=SEARCH_TIMEOUT_S,
                    cap_bytes=OUTPUT_CAP_BYTES, env=None):
    """Run one external search CLI UNDER the shared process-group timeout supervisor.

    Returns (returncode, output_text, meta). The supervisor runs `tool_argv` with
    stdin=DEVNULL, in its own session/process-group (killed as a group on timeout), and
    an enforced `--max-output-bytes` sink so output can never exceed `cap_bytes` on disk.
    This module NEVER calls `subprocess.run(timeout=...)` on rg/git/grep directly (CR3-8).
    """
    import subprocess
    import shutil
    import tempfile

    sup = _supervisor_path()
    tmpd = tempfile.mkdtemp(prefix="cv-localize-")
    outfile = os.path.join(tmpd, "out")
    full = [
        sys.executable, sup,
        "--timeout", str(int(timeout_s)), "--grace", "1",
        "--cwd", repo, "--stdout", outfile,
        "--max-output-bytes", str(int(cap_bytes)),
        "--",
    ] + list(tool_argv)
    meta = {"argv": full, "supervisor": sup, "outfile": outfile}
    try:
        # stdin=DEVNULL here too (belt); the supervisor independently closes the TOOL's
        # stdin. We pass NO timeout= — the supervisor is the sole wall-clock authority.
        proc = subprocess.run(
            full, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
        )
        rc = proc.returncode
        raw = b""
        try:
            with open(outfile, "rb") as fh:
                raw = fh.read()
        except OSError:
            raw = b""
        capped = len(raw) >= int(cap_bytes)
        meta["capped"] = capped
        return rc, raw.decode("utf-8", "replace"), meta
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)


def _backend_argv(backend, token):
    """Argv for a `--files-with-matches`, fixed-string, binary-skipping search."""
    if backend == "rg":
        return ["rg", "--no-config", "--fixed-strings", "--files-with-matches",
                "--no-messages", "--", token]
    if backend == "git-grep":
        return ["git", "grep", "-I", "--files-with-matches", "--fixed-strings",
                "-e", token]
    if backend == "grep":
        return ["grep", "-rIl", "--fixed-strings", "--", token, "."]
    raise ValueError("unknown backend %r" % backend)


def _parse_files(output_text, capped):
    """Parse a `--files-with-matches` listing into normalized relative paths. If the
    output was byte-capped mid-stream, drop the trailing (possibly partial) line."""
    lines = output_text.split("\n")
    if capped and lines and not output_text.endswith("\n"):
        lines = lines[:-1]
    files = []
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        ln = ln[2:] if ln.startswith("./") else ln
        files.append(ln)
    return files


def _search_repo(tokens, repo, timeout_s, cap_bytes, env):
    """Degrade rg -> git grep -> grep. Pick the FIRST backend that actually RUNS (a clean
    exit 0=matches or 1=no-matches). 127 (missing) / 124 (timeout) / other -> next backend.
    Union matches across all tokens on the chosen backend.

    Returns (files, backend, ran, incomplete). `incomplete` is True when the evidence is
    uncertain and the verdict must degrade to at best `ambiguous`, i.e.:
      * any backend search hit its file/result byte cap (`meta['capped']`) — later matches
        past the cap are unknown, so a capped listing is NOT a complete listing; or
      * a LATER token's search exited non-0/1 (124 timeout / error) — that token's matches
        are unknown, so silently treating it as "no match" would be a fail-open.
    Fail-closed: when in doubt, `incomplete=True`."""
    chosen = None
    incomplete = False
    for backend in BACKENDS:
        if not tokens:
            break
        rc, out, meta = _run_cli_search(_backend_argv(backend, tokens[0]), repo,
                                        timeout_s, cap_bytes, env)
        if rc in (0, 1):
            chosen = backend
            if rc == 0:
                first_capped = meta.get("capped", False)
                first_files = _parse_files(out, first_capped)
                if first_capped:
                    incomplete = True  # bug #1: a capped listing is not complete
            else:
                first_files = []
            break
    if chosen is None:
        return [], None, False, False

    union = set(first_files)
    for token in tokens[1:]:
        rc, out, meta = _run_cli_search(_backend_argv(chosen, token), repo,
                                        timeout_s, cap_bytes, env)
        if rc == 0:
            if meta.get("capped", False):
                incomplete = True  # bug #1: a capped listing is not complete
            union.update(_parse_files(out, meta.get("capped", False)))
        elif rc == 1:
            pass  # clean no-match for this token
        else:
            # bug #2: 124 timeout / error -> this token's matches are unknown, NOT "no match".
            incomplete = True
    return sorted(union), chosen, True, incomplete


# ---------------------------------------------------------------------------- #
# Generated-file detection (via the shared glob matcher + a bounded marker scan).
# ---------------------------------------------------------------------------- #
def _is_generated(rel, content):
    tax = _taxonomy_module()
    for g in _GENERATED_GLOBS:
        if tax.glob_match(rel, g):
            return True
    if content:
        head = content[:4096]
        for marker in _GENERATED_MARKERS:
            if marker in head:
                return True
    return False


# ---------------------------------------------------------------------------- #
# Flag mapping: shared taxonomy classify() -> A1's Layer-A-override vocabulary.
# ---------------------------------------------------------------------------- #
def _map_classify_flags(classify_flags):
    mapped = set()
    for f in classify_flags:
        if f == "sensitive_path":
            mapped.add("sensitive_path")
        elif f == "regex_timeout":
            mapped.add("regex_timeout")
        elif f.startswith("content:"):
            kind = f.split(":", 1)[1]
            if kind == "shared_token":
                mapped.add("shared_token")
            elif kind == "a11y":
                mapped.add("is_a11y_state")
            else:
                mapped.add("content:" + kind)
    return mapped


def _classify_paths(repo, resolved, taxonomy):
    """Read each resolved file (bounded) and classify it via the SHARED loader. Returns
    (sorted A1 flag list, incomplete). Matching semantics are NOT reimplemented here.

    `incomplete` is True iff any file exceeded MAX_FILE_READ_BYTES: the content-based
    classification then only saw the first cap bytes, so a sensitive/shared-token match
    living past the cap could be missed. We read `MAX_FILE_READ_BYTES + 1` and treat an
    over-cap read as a truncated (uncertain) scan — the caller degrades to `ambiguous`
    rather than silently trusting a partial classification. Fail-closed."""
    tax = _taxonomy_module()
    flags = set()
    incomplete = False
    for rel in resolved:
        try:
            with open(os.path.join(repo, rel), "rb") as fh:
                raw = fh.read(MAX_FILE_READ_BYTES + 1)
        except OSError:
            raw = b""
        if len(raw) > MAX_FILE_READ_BYTES:
            # File is larger than the per-file read cap -> this scan is incomplete.
            incomplete = True
            raw = raw[:MAX_FILE_READ_BYTES]
        content = raw.decode("utf-8", "replace")
        c = tax.classify(taxonomy or {}, path=rel, content=content)
        flags |= _map_classify_flags(c.get("flags", []))
        if _is_generated(rel, content):
            flags.add("is_generated")
    return sorted(flags), incomplete


# ---------------------------------------------------------------------------- #
# THE public localize() contract.
# ---------------------------------------------------------------------------- #
def localize(request, repo, taxonomy, *, file_cap=FILE_CAP, timeout_s=SEARCH_TIMEOUT_S,
             cap_bytes=OUTPUT_CAP_BYTES, env=None):
    """Bounded read-only localization.

    Returns {"resolved_paths": [...], "fan_out": int, "flags": [...], "confidence": str}
    with confidence in {exact, ambiguous, failed}:
      * failed    — no extractable token, a COMPLETE search with zero matches, or every
                    backend unavailable/timed out (-> Layer-A override #1 -> FULL_PIPELINE).
      * ambiguous — more than `file_cap` matching files (too broad to judge), OR the
                    evidence is INCOMPLETE — a search that hit its file/result byte cap, a
                    per-token timeout/error, or a file larger than MAX_FILE_READ_BYTES whose
                    tail went unscanned. Incomplete evidence must NEVER be labeled `exact`
                    (fail-closed -> override #1 -> FULL_PIPELINE).
      * exact     — 1..file_cap matching files resolved within the cap from COMPLETE evidence
                    (un-capped search, no per-token timeout, every file scanned in full).
                    `flags` may still carry shared_token / is_a11y_state / sensitive_path /
                    is_generated etc., which A3's Layer-A overrides act on.
    NEVER runs git; NEVER launches an external CLI outside the timeout supervisor.
    """
    repo = repo or "."
    tokens = extract_query_tokens(request)
    if not tokens:
        return {"resolved_paths": [], "fan_out": 0, "flags": [], "confidence": "failed"}

    files, _backend, ran, search_incomplete = _search_repo(
        tokens, repo, timeout_s, cap_bytes, env)
    if not ran:
        # Every backend was unavailable/timed-out -> cannot resolve -> fail-closed.
        return {"resolved_paths": [], "fan_out": 0, "flags": [], "confidence": "failed"}

    # Containment filter: keep only repo-relative, non-escaping regular files.
    resolved = []
    for rel in files:
        norm = _contained_regular_file(repo, rel)
        if norm is not None and norm not in resolved:
            resolved.append(norm)
    resolved.sort()

    if not resolved:
        # Zero surviving matches. A COMPLETE search that found nothing is a genuine
        # no-match -> failed. But if the search was capped/timed-out we cannot conclude
        # "no match" (the missed evidence could be a sensitive/shared-token hit) ->
        # degrade to ambiguous (Layer-A override #1 -> FULL_PIPELINE). Fail-closed.
        if search_incomplete:
            return {"resolved_paths": [], "fan_out": 0, "flags": [],
                    "confidence": "ambiguous"}
        return {"resolved_paths": [], "fan_out": 0, "flags": [], "confidence": "failed"}

    if len(resolved) > file_cap:
        # Too broad to judge within the bound -> ambiguous. Still surface bounded evidence.
        capped = resolved[:file_cap]
        flags, _ = _classify_paths(repo, capped, taxonomy)
        return {"resolved_paths": capped, "fan_out": len(resolved), "flags": flags,
                "confidence": "ambiguous"}

    flags, classify_incomplete = _classify_paths(repo, resolved, taxonomy)
    # `exact` requires COMPLETE evidence: a full (un-capped, no-timeout) search AND a full
    # (un-truncated) per-file scan. Any incompleteness -> ambiguous (override #1), never
    # a silently-mislabeled `exact`. Fail-closed.
    confidence = "ambiguous" if (search_incomplete or classify_incomplete) else "exact"
    return {"resolved_paths": resolved, "fan_out": len(resolved), "flags": flags,
            "confidence": confidence}


# ---------------------------------------------------------------------------- #
# Write-once localization artifact.
# ---------------------------------------------------------------------------- #
def artifact_rel_path(pre_eval_id):
    return os.path.join("docs", "superpowers", "pre-eval",
                        pre_eval_id + ".localization.json")


def build_artifact(result):
    """Artifact body = the four localize fields + a self-excluding canonical-JSON digest
    (record_digest, exclude_field='digest') — the value C1 binds across manifest+record."""
    tax = _taxonomy_module()
    art = {k: result[k] for k in ("resolved_paths", "fan_out", "flags", "confidence")}
    art["digest"] = tax.record_digest(art, exclude_field="digest")
    return art


def write_localization_artifact(repo, pre_eval_id, result):
    """Write docs/superpowers/pre-eval/<pre_eval_id>.localization.json WRITE-ONCE (atomic
    O_EXCL; reject overwrite). Returns the repo-relative path. NEVER commits (the dispatcher
    does, per the Lifecycle protocol Phase-P step 1)."""
    if not PRE_EVAL_ID_RE.match(pre_eval_id or ""):
        raise ValueError("invalid pre_eval_id (must match %s): %r"
                         % (PRE_EVAL_ID_RE.pattern, pre_eval_id))
    rel = artifact_rel_path(pre_eval_id)
    full = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    art = build_artifact(result)
    try:
        fd = os.open(full, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        raise FileExistsError(
            "localization artifact already exists (write-once): %s" % rel
        )
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(art, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    return rel


# ---------------------------------------------------------------------------- #
# CLI.
# ---------------------------------------------------------------------------- #
def _load_taxonomy_arg(path):
    if not path:
        return {}
    tax = _taxonomy_module()
    return tax.load_taxonomy(path=path)


def main(argv):
    if "--selftest" in argv[1:]:
        return _selftest()

    ap = argparse.ArgumentParser(prog="compound-v-localize.py")
    ap.add_argument("--request", help="the free-text change request")
    ap.add_argument("--repo", default=".", help="repo root (default: cwd)")
    ap.add_argument("--taxonomy", help="taxonomy YAML path (optional)")
    ap.add_argument("--pre-eval-id", dest="pre_eval_id",
                    help="write-once localization-artifact id")
    ap.add_argument("--write-artifact", action="store_true",
                    help="also write the write-once localization artifact")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv[1:])

    if args.request is None:
        ap.error("--request is required (or use --selftest)")
    try:
        taxonomy = _load_taxonomy_arg(args.taxonomy)
    except (ValueError, OSError, RuntimeError) as e:
        # Fail-closed: an unreadable taxonomy must NOT crash localization; A3 turns an
        # absent/malformed taxonomy into an unconditional FULL_PIPELINE.
        sys.stderr.write("warning: taxonomy unreadable (%s) — classifying without it\n" % e)
        taxonomy = {}

    result = localize(args.request, args.repo, taxonomy)
    out = dict(result)
    if args.write_artifact:
        if not args.pre_eval_id:
            ap.error("--write-artifact requires --pre-eval-id")
        try:
            rel = write_localization_artifact(args.repo, args.pre_eval_id, result)
            out["localization_ref"] = rel
            out["digest"] = build_artifact(result)["digest"]
        except FileExistsError as e:
            sys.stderr.write(str(e) + "\n")
            return 3
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


# ---------------------------------------------------------------------------- #
# Self-test (TDD). Includes the CR3-8 fake-CLI containment proof + the Step-1
# shared-token CSS case + write-once artifact.
# ---------------------------------------------------------------------------- #
_SHARED_TOKEN_TAXONOMY = """
version: 1
path_patterns:
  - glob: "src/ui/**"
    difficulty_band: low
    impact_band: low
  - glob: "src/auth/**"
    difficulty_band: high
    impact_band: high
content_patterns:
  - match: "var(--"
    pattern_type: literal
    case: sensitive
    scan: content
    kind: shared_token
    impact_band: high
  - match: "aria-label"
    pattern_type: literal
    case: sensitive
    scan: content
    kind: a11y
    impact_band: high
sensitive_path_list:
  - "src/auth/**"
"""


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _make_fake_cli(bindir, name, matches="", big=0, rc=0, sleep=0, slow_token=""):
    """A fake search CLI that records (a) whether it is a session/process-group leader
    (os.getsid(0)==getpid() — TRUE only under the supervisor's start_new_session) and
    (b) whether its stdin is DEVNULL (immediate EOF), then emits `matches` followed by
    `big` padding bytes, and exits `rc`. Shebang points at THIS interpreter so PATH need
    only contain `bindir` (proving backend selection by presence/absence).

    `slow_token`: if non-empty and it appears anywhere in argv, the fake hangs (long
    sleep) so the supervisor kills it with exit 124 — lets a test time out one specific
    query token while other tokens on the same backend return promptly."""
    os.makedirs(bindir, exist_ok=True)
    script = "#!%s\n" % sys.executable + '''
import os, sys, json, select, time
name = %(name)r
mdir = os.environ["CV_FAKE_MARKER_DIR"]
try:
    sid_self = (os.getsid(0) == os.getpid())
except Exception:
    sid_self = None
try:
    r, _, _ = select.select([0], [], [], 0.5)
    stdin_eof = (os.read(0, 16) == b"") if r else False
except Exception:
    stdin_eof = None
with open(os.path.join(mdir, name + ".json"), "w") as fh:
    json.dump({"name": name, "sid_self": sid_self, "stdin_eof": stdin_eof,
               "argv": sys.argv}, fh)
slow_token = %(slow_token)r
if slow_token and slow_token in sys.argv:
    time.sleep(30)
sleep = %(sleep)d
if sleep:
    time.sleep(sleep)
sys.stdout.write(%(matches)r)
big = %(big)d
if big:
    sys.stdout.write("Z" * big)
sys.stdout.flush()
sys.exit(%(rc)d)
''' % {"name": name, "matches": matches, "big": big, "rc": rc, "sleep": sleep,
       "slow_token": slow_token}
    p = os.path.join(bindir, name)
    with open(p, "w") as fh:
        fh.write(script)
    os.chmod(p, 0o755)
    return p


def _selftest():
    import tempfile

    failures = []

    def expect(name, cond):
        print(("  ok   - " if cond else "  FAIL - ") + name)
        if not cond:
            failures.append(name)

    tax_mod = _taxonomy_module()
    taxonomy = tax_mod.load_taxonomy(text=_SHARED_TOKEN_TAXONOMY)

    # ----- token extraction -----
    toks = extract_query_tokens("make button X red")
    expect("token extraction drops stopwords/colors, keeps 'button'",
           "button" in toks and "red" not in toks and "make" not in toks)
    expect("token extraction picks quoted spans",
           "col-primary" in extract_query_tokens('change the "col-primary" token'))
    expect("empty request -> no tokens", extract_query_tokens("") == [])

    # ----- containment -----
    with tempfile.TemporaryDirectory() as repo:
        _write(os.path.join(repo, "src/ui/a.css"), "x")
        expect("contained regular file kept",
               _contained_regular_file(repo, "./src/ui/a.css") == "src/ui/a.css")
        expect("absolute path rejected",
               _contained_regular_file(repo, "/etc/passwd") is None)
        expect("traversal rejected",
               _contained_regular_file(repo, "../outside.txt") is None)
        expect("nonexistent file rejected",
               _contained_regular_file(repo, "src/ui/missing.css") is None)
        # escaping symlink rejected
        outside = os.path.join(repo, "..", "escape-target.txt")
        try:
            _write(os.path.realpath(outside), "secret")
            link = os.path.join(repo, "src/ui/link.css")
            os.symlink(os.path.realpath(outside), link)
            expect("escaping symlink rejected (realpath leaves repo)",
                   _contained_regular_file(repo, "src/ui/link.css") is None)
        finally:
            try:
                os.remove(os.path.realpath(outside))
            except OSError:
                pass

    # ===================================================================== #
    # CR3-8 — the fake-CLI containment proof. Every fallback MUST route through
    # the supervisor with stdin=DEVNULL, process-group termination, and a bounded
    # output sink. An ordinary subprocess.run(timeout=...) MUST fail the test.
    # ===================================================================== #
    with tempfile.TemporaryDirectory() as td:
        bindir = os.path.join(td, "bin")
        mdir = os.path.join(td, "markers")
        os.makedirs(mdir)
        matches = "src/ui/button.css\nsrc/ui/card.css\n"
        # A fake that also emits 200000 padding bytes to exercise the byte cap.
        _make_fake_cli(bindir, "rg", matches=matches, big=200000, rc=0)
        fake_env = dict(os.environ)
        fake_env["PATH"] = bindir
        fake_env["CV_FAKE_MARKER_DIR"] = mdir

        rc, out, meta = _run_cli_search(_backend_argv("rg", "button"), td,
                                        timeout_s=5, cap_bytes=1000, env=fake_env)
        expect("supervisor path: CLI ran (rc==0)", rc == 0)
        expect("supervisor path: argv routes through compound-v-run-with-timeout.py",
               any("compound-v-run-with-timeout.py" in a for a in meta["argv"]))
        expect("supervisor path: --max-output-bytes present in argv",
               "--max-output-bytes" in meta["argv"])
        expect("bounded output sink enforced (captured <= cap)", len(out) <= 1000)
        expect("bounded output still retained the leading matches",
               "src/ui/button.css" in out)
        with open(os.path.join(mdir, "rg.json")) as fh:
            marker = json.load(fh)
        expect("CR3-8: CLI launched as session/process-group leader (start_new_session)",
               marker["sid_self"] is True)
        expect("CR3-8: CLI stdin is DEVNULL (immediate EOF)", marker["stdin_eof"] is True)

        # NEGATIVE CONTROL: the SAME fake run via a bare subprocess.run(timeout=...) is
        # NOT a session leader — proving the discriminator the supervisor path passes and
        # a naive `subprocess.run(timeout=...)` implementation would FAIL.
        import subprocess
        os.remove(os.path.join(mdir, "rg.json"))
        subprocess.run([os.path.join(bindir, "rg"), "button"],
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, env=fake_env, timeout=5)
        with open(os.path.join(mdir, "rg.json")) as fh:
            bare_marker = json.load(fh)
        expect("CR3-8: bare subprocess.run(timeout) is NOT a session leader "
               "(so it FAILS the supervisor-only assertion)",
               bare_marker["sid_self"] is False)

    # ----- backend selection + degrade order via presence/absence on PATH -----
    def _run_selection(present):
        with tempfile.TemporaryDirectory() as td:
            bindir = os.path.join(td, "bin")
            mdir = os.path.join(td, "markers")
            os.makedirs(mdir)
            repo = os.path.join(td, "repo")
            _write(os.path.join(repo, "src/ui/button.css"), "/* button */ .b{color:red}")
            for tool in present:
                _make_fake_cli(bindir, tool, matches="src/ui/button.css\n", rc=0)
            fenv = dict(os.environ)
            fenv["PATH"] = bindir
            fenv["CV_FAKE_MARKER_DIR"] = mdir
            localize("make button red", repo, {}, timeout_s=5,
                     cap_bytes=OUTPUT_CAP_BYTES, env=fenv)
            return set(os.listdir(mdir))

    ran = _run_selection(["rg", "git", "grep"])
    expect("degrade: rg chosen first (rg marker present, no git/grep)",
           "rg.json" in ran and "git.json" not in ran and "grep.json" not in ran)
    ran = _run_selection(["git", "grep"])
    expect("degrade: rg absent -> git grep chosen (git marker, no grep)",
           "git.json" in ran and "grep.json" not in ran and "rg.json" not in ran)
    ran = _run_selection(["grep"])
    expect("degrade: rg+git absent -> grep chosen", ran == {"grep.json"})

    # ----- timeout -> process-group kill via the supervisor (returns promptly) -----
    with tempfile.TemporaryDirectory() as td:
        bindir = os.path.join(td, "bin")
        mdir = os.path.join(td, "markers")
        os.makedirs(mdir)
        _make_fake_cli(bindir, "rg", matches="x\n", rc=0, sleep=30)
        fenv = dict(os.environ)
        fenv["PATH"] = bindir
        fenv["CV_FAKE_MARKER_DIR"] = mdir
        import time
        t0 = time.time()
        rc, out, meta = _run_cli_search(_backend_argv("rg", "button"), td,
                                        timeout_s=1, cap_bytes=1000, env=fenv)
        elapsed = time.time() - t0
        expect("hung CLI killed by supervisor -> exit 124", rc == 124)
        expect("hung CLI killed promptly (<6s wall)", elapsed < 6)

    # ===================================================================== #
    # STEP-1 primary case — a shared-token CSS request with the REAL toolchain.
    # ===================================================================== #
    with tempfile.TemporaryDirectory() as repo:
        # A global design token used by two components -> fan_out>1, shared_token.
        _write(os.path.join(repo, "src/ui/button.css"),
               "/* button styles */\n.btn { color: var(--color-primary); }\n")
        _write(os.path.join(repo, "src/ui/card.css"),
               "/* card with a button */\n.card-btn { background: var(--color-primary); }\n")
        _write(os.path.join(repo, "README.md"), "no button here at all-ish\n")

        res = localize("make button X red", repo, taxonomy)
        expect("STEP-1: confidence == exact", res["confidence"] == "exact")
        expect("STEP-1: fan_out > 1 (shared token across components)", res["fan_out"] > 1)
        expect("STEP-1: flags include shared_token", "shared_token" in res["flags"])
        expect("STEP-1: both css files resolved",
               "src/ui/button.css" in res["resolved_paths"]
               and "src/ui/card.css" in res["resolved_paths"])

        # write-once artifact
        peid = "2026-07-12T101500Z-make-button-red-a1b2"
        rel = write_localization_artifact(repo, peid, res)
        expect("artifact written at the pre-eval path",
               rel == "docs/superpowers/pre-eval/%s.localization.json" % peid)
        art = json.load(open(os.path.join(repo, rel)))
        expect("artifact carries the four fields + a sha256 digest",
               set(art) == {"resolved_paths", "fan_out", "flags", "confidence", "digest"}
               and art["digest"].startswith("sha256:"))
        expect("artifact digest matches record_digest(exclude self)",
               art["digest"] == tax_mod.record_digest(art, exclude_field="digest"))
        # write-once: a second write MUST be rejected
        rejected = False
        try:
            write_localization_artifact(repo, peid, res)
        except FileExistsError:
            rejected = True
        expect("write-once: overwrite rejected", rejected)
        expect("invalid pre_eval_id rejected",
               _rejects(lambda: write_localization_artifact(repo, "bad id/../x", res),
                        ValueError))

    # ----- sensitive-path flag surfaces (override #2 evidence) -----
    with tempfile.TemporaryDirectory() as repo:
        _write(os.path.join(repo, "src/auth/login.py"), "def authtoken_login():\n    pass\n")
        res = localize("fix the authtoken_login flow", repo, taxonomy)
        expect("sensitive path surfaces sensitive_path flag",
               res["confidence"] == "exact" and "sensitive_path" in res["flags"])

    # ----- is_generated flag -----
    with tempfile.TemporaryDirectory() as repo:
        _write(os.path.join(repo, "dist/bundle.js"), "// generated_marker_symbol build\n")
        res = localize("touch generated_marker_symbol", repo, taxonomy)
        expect("generated path surfaces is_generated flag",
               "is_generated" in res["flags"])

    # ----- failed / ambiguous -----
    with tempfile.TemporaryDirectory() as repo:
        _write(os.path.join(repo, "src/ui/x.css"), "nothing relevant\n")
        res = localize("adjust zzunfindabletokenqqq", repo, taxonomy)
        expect("no match -> confidence failed", res["confidence"] == "failed"
               and res["resolved_paths"] == [])
        res_empty = localize("", repo, taxonomy)
        expect("empty request -> failed", res_empty["confidence"] == "failed")

    with tempfile.TemporaryDirectory() as repo:
        for i in range(6):
            _write(os.path.join(repo, "src/ui/f%d.css" % i), "shared_widget token\n")
        res = localize("shared_widget", repo, taxonomy, file_cap=3)
        expect("more than file_cap matches -> ambiguous",
               res["confidence"] == "ambiguous" and res["fan_out"] > 3
               and len(res["resolved_paths"]) == 3)

    # ===================================================================== #
    # HIGH-8 — incomplete evidence MUST degrade to `ambiguous`, never `exact`.
    # ===================================================================== #

    # (a) a search that HIT the file/result byte cap -> ambiguous (not exact). The fake rg
    #     emits ONE real match line then floods padding past cap_bytes, so the supervisor's
    #     --max-output-bytes sink caps the listing -> `capped` -> the listing is incomplete.
    with tempfile.TemporaryDirectory() as td:
        bindir = os.path.join(td, "bin")
        mdir = os.path.join(td, "markers")
        os.makedirs(mdir)
        repo = os.path.join(td, "repo")
        _write(os.path.join(repo, "src/ui/button.css"), ".b{color:red}\n")
        # One real match, then a flood that overruns the (small) output cap.
        _make_fake_cli(bindir, "rg", matches="src/ui/button.css\n", big=200000, rc=0)
        fenv = dict(os.environ)
        fenv["PATH"] = bindir
        fenv["CV_FAKE_MARKER_DIR"] = mdir
        res = localize("touch button widget", repo, {}, timeout_s=5, cap_bytes=1000,
                       env=fenv)
        expect("HIGH-8(a): capped search listing -> ambiguous (NOT exact)",
               res["confidence"] == "ambiguous"
               and "src/ui/button.css" in res["resolved_paths"])

    # (b) a LATER token whose backend TIMES OUT (fake-CLI hangs -> supervisor exit 124)
    #     -> ambiguous. First token returns a clean match; the second token hangs.
    with tempfile.TemporaryDirectory() as td:
        bindir = os.path.join(td, "bin")
        mdir = os.path.join(td, "markers")
        os.makedirs(mdir)
        repo = os.path.join(td, "repo")
        _write(os.path.join(repo, "src/ui/alpha.css"), "alphatoken here\n")
        # rg hangs whenever "betaslowtoken" is the query token (the 2nd token) -> 124.
        _make_fake_cli(bindir, "rg", matches="src/ui/alpha.css\n", rc=0,
                       slow_token="betaslowtoken")
        fenv = dict(os.environ)
        fenv["PATH"] = bindir
        fenv["CV_FAKE_MARKER_DIR"] = mdir
        import time as _t
        t0 = _t.time()
        res = localize("alphatoken betaslowtoken", repo, {}, timeout_s=1,
                       cap_bytes=OUTPUT_CAP_BYTES, env=fenv)
        elapsed = _t.time() - t0
        expect("HIGH-8(b): later-token timeout (exit 124) -> ambiguous (NOT exact)",
               res["confidence"] == "ambiguous"
               and "src/ui/alpha.css" in res["resolved_paths"])
        expect("HIGH-8(b): later-token timeout killed promptly by supervisor (<8s)",
               elapsed < 8)

    # (c) a file LARGER than MAX_FILE_READ_BYTES -> the content scan is incomplete (a match
    #     past the read cap could be missed) -> ambiguous. Real toolchain (same as STEP-1).
    with tempfile.TemporaryDirectory() as repo:
        oversized = ("oversizedtokenqqq at the top\n"
                     + "A" * (MAX_FILE_READ_BYTES + 4096) + "\n")
        _write(os.path.join(repo, "src/ui/huge.css"), oversized)
        res = localize("oversizedtokenqqq", repo, taxonomy)
        expect("HIGH-8(c): file > MAX_FILE_READ_BYTES -> scan incomplete -> ambiguous",
               res["confidence"] == "ambiguous"
               and "src/ui/huge.css" in res["resolved_paths"])
        # Direct unit check on the classifier's incompleteness signal.
        _flags, _incomplete = _classify_paths(repo, ["src/ui/huge.css"], taxonomy)
        expect("HIGH-8(c): _classify_paths flags the oversized file as incomplete",
               _incomplete is True)
        # Guard: a small in-cap file is NOT flagged incomplete (keeps `exact` reachable).
        _write(os.path.join(repo, "src/ui/small.css"), "smalltok\n")
        _f2, _inc2 = _classify_paths(repo, ["src/ui/small.css"], taxonomy)
        expect("HIGH-8(c): a small in-cap file is NOT flagged incomplete",
               _inc2 is False)

    if failures:
        print("\nSELFTEST FAILED: %d case(s)" % len(failures))
        return 1
    print("\nSELFTEST PASSED")
    return 0


def _rejects(fn, exc):
    try:
        fn()
        return False
    except exc:
        return True
    except Exception:  # noqa: BLE001
        return False


if __name__ == "__main__":
    sys.exit(main(sys.argv))
