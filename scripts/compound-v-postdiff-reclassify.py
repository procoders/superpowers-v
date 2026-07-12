#!/usr/bin/env python3
"""
Compound V — post-hoc reclassifier (v2.9 Task F2). AC-5 / AC-7 / AC-16 / CR1-3 /
CR1-11 / CR2-9 / CR2-10 / CR3-3 / CR3-6.

WHY THIS IS A SIBLING, NOT AN EXTENSION OF scope-check (H7 / AC-5)
-----------------------------------------------------------------
`compound-v-scope-check.py` is a HARDENED, name-only enforcement gate with
reproduced-exploit selftests. It must stay name-only and MUST NOT learn to read
diff CONTENT. This module is a *separate* analyzer that runs on the fast-path,
pre-merge, against the SAME pinned baseline SHA and the SAME authoritative
changed-path set the scope gate used. It REUSES scope-check's changed-path set +
its `matches` globber (imported by path, read-only) — it never modifies, subclasses,
or re-copies scope-check.

It answers ONE question: "does the actual, materialized diff still deserve the
fast-path, or must it ESCALATE to the full pipeline?" It returns
``{"escalate": bool, "reasons": [...]}`` — never a routing decision of its own; the
orchestrator escalates on ``escalate=True``.

Fail-closed is the law (Iron-Invariant #5). ANY uncertainty escalates:
unsupported/absent parser, parse failure, binary / deleted / renamed change,
unreadable path, a git error, an oversized file, or any taxonomy content-flag hit.

WHAT IT CHECKS (all unioned into `reasons`; a non-empty reasons list ⇒ escalate)
-------------------------------------------------------------------------------
1. Sensitive-path touch — intersect the changed-path set with the taxonomy
   ``sensitive_path_list`` using scope-check's `matches`. Any hit escalates.
2. Size accounting (CR3-6) — TRACKED size from ``git diff --numstat <baseline>``;
   UNTRACKED size measured SEPARATELY (bounded reads) and UNIONED, because
   ``git diff`` never reports untracked files. A total-changed-lines budget and a
   per-untracked-file byte cap both escalate on overflow. Binary (tracked numstat
   ``-`` OR a NUL byte in the worktree file) escalates.
3. Content re-check (CR3-3) — run the SHARED taxonomy ``match_content`` over the
   CHANGED HUNK lines (added + removed) and, for untracked files, the whole file.
   Any shared_token / a11y / feature_flag / legal_copy / i18n / config_literal hit
   escalates. A string-literal change is treated as SEMANTIC: the taxonomy IS the
   "parser" for string meaning — a string that matches no content pattern is inert,
   one that matches a pattern (a feature-flag name, legal copy, an i18n placeholder,
   a config literal) escalates.
4. Typed structural pass (CR2-9 / CR2-10) — Python has a REAL analyzer (stdlib
   ``ast``): parse the baseline + worktree versions and escalate iff the
   function/class SIGNATURE map changed OR any scope's CONTROL-FLOW fingerprint
   changed — a per-scope count of branches/loops/handlers (If, For, While, Try,
   ExceptHandler, With, comprehensions, boolean operators, raise/return/break/
   continue, calls). A body edit that adds an ``if``/loop/``try``/handler changes the
   fingerprint and ESCALATES; a pure rename/whitespace/comment/docstring or
   constant-value-only edit changes neither map and is allowed through (the content
   axis still runs separately, so a string-literal that hits a taxonomy pattern still
   escalates via check 3). JS / TS / Go / Ruby escalate FAIL-CLOSED
   unless the change is PROVABLY trivial (only blank / single-line-comment changed
   lines — a strict test, never string/brace/code) OR a language parser binary is
   registered for the extension, in which case it runs as a syntax check THROUGH the
   timeout supervisor (``compound-v-run-with-timeout.py``, ``stdin`` </dev/null,
   process-group kill) and escalates on any non-zero / timeout / parse-failure.
   Non-code text (``.css`` / ``.md`` / ``.json`` / …) has no structural axis — it is
   judged by size + content + sensitivity only, so a clean tiny CSS diff does NOT
   escalate while one introducing a shared token / a11y construct DOES.

CONSTRAINTS: Python 3.9-safe, stdlib only. Every external CLI (git, any parser)
runs through the timeout supervisor with ``stdin`` DEVNULL and a bounded output
sink. YAML is loaded only via the shared soft-PyYAML loader (CLI path only).

Interface:
    reclassify(baseline_sha, changed_paths, worktree, taxonomy,
               parsers=None, max_total_lines=..., max_untracked_bytes=...,
               git_timeout_s=...) -> {"escalate": bool, "reasons": [str, ...]}

CLI:
    compound-v-postdiff-reclassify.py --worktree DIR [--baseline SHA]
        --taxonomy taxonomy.yaml [--changed-file paths.txt] [--max-total-lines N]
        [--max-untracked-bytes N]
    compound-v-postdiff-reclassify.py --selftest
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile


# --------------------------------------------------------------------------- #
# Tunables (fast-path = tiny changes; conservative by design).
# --------------------------------------------------------------------------- #
MAX_TOTAL_LINES = 50            # union of tracked (numstat) + untracked line counts
MAX_UNTRACKED_BYTES = 20000     # per untracked file
GIT_TIMEOUT_S = 30
PARSER_TIMEOUT_S = 20
MAX_DIFF_BYTES = 1_000_000      # bounded sink for `git diff`/`git show`
MAX_NUMSTAT_BYTES = 4_000_000
MAX_FILE_READ_BYTES = 5_000_000  # bounded read for untracked/binary/AST source
BINARY_SNIFF_BYTES = 8192

# Recognized CODE languages WITHOUT a bundled Python-grade analyzer: fail-closed
# unless provably trivial or an explicitly-registered parser passes.
_FAILCLOSED_CODE_EXTS = {
    ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go", ".rb",
}

# Default language-parser registry is EMPTY on purpose: we NEVER claim to ship a
# JS/Go/Ruby parser, so with no parser a non-trivial change fails closed. A caller
# may inject {".js": ["node", "--check"], ".rb": ["ruby", "-c"], ...} — each is run
# as `<cmd...> <file>` through the timeout supervisor as a syntax check (exit 0 =
# parses/clean ⇒ no escalate; non-zero/timeout ⇒ escalate).
_DEFAULT_PARSERS = {}


# --------------------------------------------------------------------------- #
# Reuse siblings by path (read-only, no recopy, never a hard top-level import).
# Same lazy-import-by-path pattern the taxonomy module uses for validate-manifest.
# --------------------------------------------------------------------------- #
def _script_dir():
    return os.path.dirname(os.path.abspath(__file__))


def _load_sibling(basename, modname):
    import importlib.util

    path = os.path.join(_script_dir(), basename)
    try:
        spec = importlib.util.spec_from_file_location(modname, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:  # noqa: BLE001
        return None


_SCOPE_MOD = None
_TAX_MOD = None


def _scope_module():
    global _SCOPE_MOD
    if _SCOPE_MOD is None:
        _SCOPE_MOD = _load_sibling("compound-v-scope-check.py", "compound_v_scope_check") or False
    return _SCOPE_MOD


def _taxonomy_module():
    global _TAX_MOD
    if _TAX_MOD is None:
        _TAX_MOD = _load_sibling("compound-v-taxonomy.py", "compound_v_taxonomy") or False
    return _TAX_MOD


def _path_matches(path, glob):
    """Reuse scope-check's globber for "touches path X"; fall back to the taxonomy
    module's glob_match if scope-check cannot be imported (both are the same
    segment-aware `*`, recursive `**`, literal-`[` semantics)."""
    sc = _scope_module()
    if sc:
        return sc.matches(path, glob)
    tx = _taxonomy_module()
    if tx:
        return tx.glob_match(path, glob)
    # Last resort: exact match only — degrade-safe (a missed glob over-escalates
    # nothing here; the caller still has the other axes).
    return path == glob


def _match_content(taxonomy, text):
    tx = _taxonomy_module()
    if not tx:
        # Cannot run the shared matcher → fail-closed: report a synthetic hit so the
        # content axis never silently passes when its engine is unavailable.
        return [{"kind": "content_engine_unavailable", "impact_band": "high",
                 "pattern_type": "literal", "match": "", "timed_out": True}]
    return tx.match_content(taxonomy, text, scan="content")


# --------------------------------------------------------------------------- #
# Supervised git / parser execution (timeout supervisor, stdin </dev/null).
# --------------------------------------------------------------------------- #
def _supervisor_path():
    return os.path.join(_script_dir(), "compound-v-run-with-timeout.py")


def _run_supervised(cmd, timeout_s, cap_bytes):
    """Run ``cmd`` (a list) under the process-group timeout supervisor, capturing
    stdout to a bounded temp file. Returns ``(rc, stdout_bytes)`` where ``rc`` is the
    command's own exit code (or 124 on timeout, 127 if missing). stdin is DEVNULL
    (enforced by the supervisor); stderr is discarded."""
    tmp = tempfile.mkdtemp(prefix="cv-f2-")
    try:
        outf = os.path.join(tmp, "out")
        full = [
            sys.executable, _supervisor_path(),
            "--timeout", str(int(max(1, timeout_s))), "--grace", "1",
            "--stdout", outf, "--max-output-bytes", str(int(cap_bytes)),
            "--",
        ] + list(cmd)
        proc = subprocess.run(
            full, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        data = b""
        try:
            with open(outf, "rb") as fh:
                data = fh.read()
        except OSError:
            data = b""
        return proc.returncode, data
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def _git(worktree, args, timeout_s, cap_bytes):
    return _run_supervised(["git", "-C", worktree] + list(args), timeout_s, cap_bytes)


# --------------------------------------------------------------------------- #
# Size accounting.
# --------------------------------------------------------------------------- #
def _numstat_map(worktree, baseline, timeout_s):
    """``git diff --numstat --no-renames -z <baseline>`` → dict path -> (add, del)
    ints, or the string ``"binary"`` for a ``-\\t-`` binary record. Returns
    ``(map, ok)``. ``--no-renames`` mirrors the scope gate: a rename surfaces as a
    delete + an add rather than collapsing to its destination."""
    rc, out = _git(worktree, ["diff", "--numstat", "--no-renames", "-z", baseline],
                   timeout_s, MAX_NUMSTAT_BYTES)
    if rc != 0:
        return {}, False
    result = {}
    for rec in out.split(b"\0"):
        if not rec:
            continue
        parts = rec.split(b"\t", 2)
        if len(parts) != 3:
            continue
        added, deleted, path = parts
        path = path.decode("utf-8", "replace")
        if added == b"-" or deleted == b"-":
            result[path] = "binary"
            continue
        try:
            result[path] = (int(added), int(deleted))
        except ValueError:
            result[path] = "binary"  # unparseable counts → conservative
    return result, True


def _read_bounded(abspath, cap):
    """Read AT MOST ``cap+1`` bytes. Returns ``(data, overflow, err)``: ``overflow``
    is True if the file is larger than ``cap``; ``err`` is a string on any OS error."""
    try:
        with open(abspath, "rb") as fh:
            data = fh.read(cap + 1)
    except OSError as e:
        return b"", False, str(e)
    overflow = len(data) > cap
    return data[:cap], overflow, None


def _looks_binary(abspath):
    """A NUL byte in the first sniff window ⇒ binary. Errors ⇒ True (fail-closed:
    an unreadable file is treated as an opaque/binary blob and escalates)."""
    try:
        with open(abspath, "rb") as fh:
            chunk = fh.read(BINARY_SNIFF_BYTES)
    except OSError:
        return True
    return b"\0" in chunk


# --------------------------------------------------------------------------- #
# Changed-line extraction (content re-check + triviality).
# --------------------------------------------------------------------------- #
def _changed_lines(worktree, baseline, path, tracked, abspath, timeout_s):
    """Return ``(lines, err)`` — the CHANGED lines to feed content/structural checks.

    Tracked: parse ``git diff --no-renames <baseline> -- <path>`` and keep both added
    (`+`) and removed (`-`) body lines (prefix stripped, `+++`/`---` headers dropped),
    so an INTRODUCED *or* REMOVED sensitive construct is seen. Untracked: the whole
    (bounded) file is the added hunk. ``err`` is set on any git/read failure or a
    diff that hit the output cap (ambiguous → caller fails closed)."""
    if not tracked:
        data, overflow, err = _read_bounded(abspath, MAX_FILE_READ_BYTES)
        if err:
            return None, err
        if overflow:
            return None, "untracked file exceeds bounded read cap"
        return data.decode("utf-8", "replace").splitlines(), None

    rc, out = _git(worktree, ["diff", "--no-renames", baseline, "--", path],
                   timeout_s, MAX_DIFF_BYTES)
    if rc != 0:
        return None, "git diff failed (rc=%s)" % rc
    if len(out) >= MAX_DIFF_BYTES:
        return None, "diff exceeds bounded output cap"
    lines = []
    for raw in out.decode("utf-8", "replace").splitlines():
        if raw.startswith("+++") or raw.startswith("---"):
            continue
        if raw.startswith("+") or raw.startswith("-"):
            lines.append(raw[1:])
    return lines, None


# --------------------------------------------------------------------------- #
# Typed structural pass.
# --------------------------------------------------------------------------- #
def _cf_label_map():
    """type(node) -> control-flow label, built for the running ``ast`` (3.9-safe).
    Constants, names, assignments, binops, etc. are DELIBERATELY absent: a
    constant-value-only edit or a pure rename leaves every counted label unchanged,
    so it does not escalate. Only branch/loop/handler/call *shape* is tracked."""
    import ast

    m = {
        ast.If: "if", ast.IfExp: "ifexp",
        ast.For: "for", ast.While: "while",
        ast.Try: "try", ast.ExceptHandler: "except",
        ast.With: "with", ast.Raise: "raise",
        ast.Return: "return", ast.Break: "break",
        ast.Continue: "continue", ast.Call: "call",
        ast.BoolOp: "boolop", ast.comprehension: "comprehension",
        ast.Assert: "assert",
    }
    # Version-gated nodes: absent on Python 3.9 (Match/match_case/TryStar).
    for name, label in (("AsyncFor", "for"), ("AsyncWith", "with"),
                        ("Await", "await"), ("TryStar", "try"),
                        ("Match", "match"), ("match_case", "match_case")):
        node = getattr(ast, name, None)
        if node is not None:
            m[node] = label
    return m


def _py_fingerprints(source):
    """Parse ``source`` and return ``(sig_map, cf_map)``.

    ``sig_map``: qualified-scope-name -> signature tuple for every def/class
    (kind, argspec/bases, returns, decorators). ``cf_map``: qualified-scope-name ->
    a sorted tuple of (control-flow-label, count) for that scope's OWN body, PLUS a
    synthetic ``"<module>"`` scope for module-level control flow. Nested defs/classes
    are their OWN scope entries (not counted in the parent), so a change is attributed
    to the scope it lives in.

    Raises ``SyntaxError`` on unparseable source; any OTHER surprise propagates and the
    caller fails closed. Conservative: same-qualname collisions (e.g. two defs in
    opposite branches) coalesce — matching the prior analyzer's stance."""
    import ast

    tree = ast.parse(source)
    cf_labels = _cf_label_map()
    scope_types = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

    def _argspec(a):
        def names(seq):
            return tuple(x.arg for x in seq)
        posonly = names(getattr(a, "posonlyargs", []) or [])
        args = names(a.args)
        kwonly = names(a.kwonlyargs)
        vararg = a.vararg.arg if a.vararg else None
        kwarg = a.kwarg.arg if a.kwarg else None
        ndef = len(a.defaults)
        nkwdef = len([d for d in a.kw_defaults if d is not None])
        return (posonly, args, kwonly, vararg, kwarg, ndef, nkwdef)

    def _decos(node):
        out = []
        for d in node.decorator_list:
            try:
                out.append(ast.dump(d))
            except Exception:  # noqa: BLE001
                out.append("<deco>")
        return tuple(out)

    def _scope_cf(scope_node):
        """Count control-flow constructs lexically inside ``scope_node``, descending
        through control-flow blocks (if/for/while/try/with bodies) but STOPPING at
        nested def/class scopes (they are counted separately under their own key)."""
        counts = {}

        def walk(node):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, scope_types):
                    continue  # separate scope — counted under its own qualname
                label = cf_labels.get(type(child))
                if label is not None:
                    counts[label] = counts.get(label, 0) + 1
                walk(child)

        walk(scope_node)
        return tuple(sorted(counts.items()))

    sig_map = {}
    cf_map = {"<module>": _scope_cf(tree)}

    def descend(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qn = prefix + child.name
                returns = ast.dump(child.returns) if child.returns is not None else None
                sig_map[qn] = ("func", _argspec(child.args), returns, _decos(child))
                cf_map[qn] = _scope_cf(child)
                descend(child, qn + ".<locals>.")
            elif isinstance(child, ast.ClassDef):
                qn = prefix + child.name
                bases = tuple(sorted(ast.dump(b) for b in child.bases))
                sig_map[qn] = ("class", bases, _decos(child))
                cf_map[qn] = _scope_cf(child)
                descend(child, qn + ".")
            else:
                descend(child, prefix)  # keep prefix; find defs nested in if/for/…

    descend(tree, "")
    return sig_map, cf_map


def _python_structural(path, abspath, worktree, baseline, timeout_s):
    """Escalate iff, between baseline and worktree, the Python function/class SIGNATURE
    map changed OR any scope's control-flow fingerprint changed (an added/removed
    branch, loop, exception handler, boolean operator, comprehension, raise/return/
    break/continue, or call), or either side fails to parse / analyze. A pure
    rename/whitespace/comment/docstring or constant-value-only edit changes neither
    map and passes (the content axis still runs separately)."""
    cur, overflow, err = _read_bounded(abspath, MAX_FILE_READ_BYTES)
    if err or overflow:
        return ["%s: cannot read Python source (%s)" % (path, err or "over read cap")]
    # Baseline version via `git show <baseline>:<path>`; a new file (absent at
    # baseline) → git non-zero → treat baseline source as empty.
    rc, base_bytes = _git(worktree, ["show", "%s:%s" % (baseline, path)],
                          timeout_s, MAX_FILE_READ_BYTES)
    base_src = base_bytes.decode("utf-8", "replace") if rc == 0 else ""
    try:
        cur_sig, cur_cf = _py_fingerprints(cur.decode("utf-8", "replace"))
    except SyntaxError as e:
        return ["%s: Python parse failure in worktree (%s)" % (path, e.__class__.__name__)]
    except Exception as e:  # noqa: BLE001 — analysis surprise ⇒ fail-closed
        return ["%s: Python structural analysis error (%s) — fail-closed"
                % (path, e.__class__.__name__)]
    try:
        base_sig, base_cf = _py_fingerprints(base_src)
    except SyntaxError:
        # Baseline unparseable but worktree parses: cannot prove the change inert.
        return ["%s: Python baseline unparseable — cannot prove structure unchanged" % path]
    except Exception as e:  # noqa: BLE001 — analysis surprise ⇒ fail-closed
        return ["%s: Python baseline structural analysis error (%s) — fail-closed"
                % (path, e.__class__.__name__)]
    reasons = []
    if cur_sig != base_sig:
        reasons.append("%s: Python function/class signature changed" % path)
    if cur_cf != base_cf:
        reasons.append("%s: Python control-flow structure changed" % path)
    return reasons


def _all_trivial(lines, ext):
    """STRICT triviality: every changed line is blank or a single-line comment for
    the language. Anything else (string, brace, code) ⇒ NOT trivial ⇒ escalate.
    Block comments (`/* */`) are deliberately NOT treated as trivial — too hard to
    prove line-by-line, and fail-closed is the safe direction."""
    marker = "#" if ext == ".rb" else "//"
    for raw in lines:
        s = raw.strip()
        if s == "":
            continue
        if s.startswith(marker):
            continue
        return False
    return True


def _run_parser(cmd_template, abspath, worktree, timeout_s):
    """Run a registered language parser as a syntax check through the supervisor.
    Convention: exit 0 = parses/clean; any non-zero / timeout / missing = escalate.
    Returns ``(rc, ok)`` where ``ok`` is True only on rc==0."""
    rc, _ = _run_supervised(list(cmd_template) + [abspath], timeout_s, 65536)
    return rc, rc == 0


def _structural_pass(path, abspath, worktree, baseline, changed_lines, parsers, timeout_s):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".py":
        return _python_structural(path, abspath, worktree, baseline, timeout_s)
    if ext in _FAILCLOSED_CODE_EXTS:
        if changed_lines is None:
            return ["%s: cannot read change for structural check (ambiguous)" % path]
        if _all_trivial(changed_lines, ext):
            return []
        if ext in parsers:
            rc, ok = _run_parser(parsers[ext], abspath, worktree, timeout_s)
            if ok:
                return []
            return ["%s: language parser reported non-clean parse (rc=%s)" % (path, rc)]
        return ["%s: non-trivial %s change with no parser present (fail-closed)" % (path, ext)]
    # Non-code text: no structural axis (size + content + sensitivity decide).
    return []


# --------------------------------------------------------------------------- #
# Path-safety guard.
# --------------------------------------------------------------------------- #
def _safe_join(worktree, path):
    """Join + confirm the result stays under the worktree. Returns ``(abspath, ok)``.
    A ``..``-escaping or absolute changed path (should never come from git, but be
    defensive) is rejected → caller fails closed."""
    if path.startswith("/") or ".." in path.split("/"):
        return None, False
    abspath = os.path.normpath(os.path.join(worktree, path))
    root = os.path.normpath(worktree)
    if abspath != root and not abspath.startswith(root + os.sep):
        return None, False
    return abspath, True


# --------------------------------------------------------------------------- #
# The reclassifier.
# --------------------------------------------------------------------------- #
def reclassify(baseline_sha, changed_paths, worktree, taxonomy,
               parsers=None, max_total_lines=MAX_TOTAL_LINES,
               max_untracked_bytes=MAX_UNTRACKED_BYTES,
               git_timeout_s=GIT_TIMEOUT_S):
    """Post-hoc reclassification of a fast-path diff. See module docstring.

    Returns {"escalate": bool, "reasons": [str, ...]} — reasons deduped + sorted.
    Fail-closed: ANY uncertainty adds a reason (⇒ escalate)."""
    if parsers is None:
        parsers = dict(_DEFAULT_PARSERS)
    reasons = []
    sensitive = taxonomy.get("sensitive_path_list", []) if isinstance(taxonomy, dict) else []

    numstat, ok = _numstat_map(worktree, baseline_sha, git_timeout_s)
    if not ok:
        reasons.append("git diff --numstat failed against baseline %s" % baseline_sha)
        numstat = {}

    total_lines = 0
    for path in sorted(set(changed_paths)):
        try:
            # 1. Sensitive-path touch (reuse scope-check's globber).
            for g in sensitive:
                if _path_matches(path, g):
                    reasons.append("%s: touches sensitive path (%s)" % (path, g))
                    break

            abspath, safe = _safe_join(worktree, path)
            if not safe:
                reasons.append("%s: path escapes worktree (ambiguous)" % path)
                continue

            tracked = path in numstat

            # 2a. Deleted (was changed, absent from the worktree).
            if not os.path.exists(abspath) and not os.path.islink(abspath):
                reasons.append("%s: deleted/renamed-away (not present in worktree)" % path)
                continue

            # 2b. Binary (tracked numstat '-' OR NUL byte in the file).
            if numstat.get(path) == "binary" or _looks_binary(abspath):
                reasons.append("%s: binary change" % path)
                continue

            # 2c. Size accounting — tracked lines from numstat, untracked measured.
            if tracked:
                val = numstat.get(path)
                if isinstance(val, tuple):
                    total_lines += val[0] + val[1]
            else:
                data, overflow, err = _read_bounded(abspath, max_untracked_bytes)
                if err:
                    reasons.append("%s: unreadable untracked file (%s)" % (path, err))
                    continue
                if overflow:
                    reasons.append(
                        "%s: untracked file exceeds %d-byte cap" % (path, max_untracked_bytes)
                    )
                total_lines += data.decode("utf-8", "replace").count("\n") + 1

            # 3+4. Extract changed lines ONCE, feed content re-check + structural pass.
            changed_lines, cl_err = _changed_lines(
                worktree, baseline_sha, path, tracked, abspath, git_timeout_s
            )
            if cl_err:
                reasons.append("%s: cannot extract changed hunk (%s)" % (path, cl_err))

            # 3. Content re-check over the changed hunk (added + removed lines).
            if changed_lines:
                hits = _match_content(taxonomy, "\n".join(changed_lines))
                seen = set()
                for h in hits:
                    kind = h.get("kind") or "content"
                    key = (kind, h.get("match", ""), bool(h.get("timed_out")))
                    if key in seen:
                        continue
                    seen.add(key)
                    if h.get("timed_out"):
                        reasons.append(
                            "%s: content pattern unresolved/fail-closed (%s)" % (path, kind)
                        )
                    else:
                        reasons.append(
                            "%s: content flag %s (%r)" % (path, kind, h.get("match", ""))
                        )

            # 4. Typed structural pass.
            reasons.extend(_structural_pass(
                path, abspath, worktree, baseline_sha, changed_lines, parsers, git_timeout_s
            ))
        except Exception as e:  # noqa: BLE001 — any surprise fails closed
            reasons.append("%s: analyzer error (%s) — fail-closed" % (path, e.__class__.__name__))

    if total_lines > max_total_lines:
        reasons.append("total changed lines %d exceeds threshold %d" % (total_lines, max_total_lines))

    reasons = sorted(set(reasons))
    return {"escalate": len(reasons) > 0, "reasons": reasons}


# --------------------------------------------------------------------------- #
# CLI.
# --------------------------------------------------------------------------- #
def _changed_from_scope(worktree, baseline):
    sc = _scope_module()
    if not sc:
        raise RuntimeError("cannot import compound-v-scope-check.py to derive changed paths")
    return sc.changed_files(worktree, baseline)


def main(argv):
    if "--selftest" in argv[1:]:
        return _selftest()

    ap = argparse.ArgumentParser(prog="compound-v-postdiff-reclassify.py")
    ap.add_argument("--worktree", required=True, help="worktree root")
    ap.add_argument("--baseline", default="HEAD", help="pinned baseline SHA/ref (default HEAD)")
    ap.add_argument("--taxonomy", required=True, help="taxonomy YAML path")
    ap.add_argument("--changed-file", help="file of repo-relative changed paths (one/line); "
                    "default: derive from scope-check")
    ap.add_argument("--max-total-lines", type=int, default=MAX_TOTAL_LINES)
    ap.add_argument("--max-untracked-bytes", type=int, default=MAX_UNTRACKED_BYTES)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv[1:])

    if not os.path.isdir(args.worktree):
        print(json.dumps({"error": "not a directory: %s" % args.worktree}), file=sys.stderr)
        return 2

    tx = _taxonomy_module()
    if not tx:
        print(json.dumps({"error": "cannot import compound-v-taxonomy.py"}), file=sys.stderr)
        return 2
    try:
        taxonomy = tx.load_taxonomy(path=args.taxonomy)
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"error": "cannot load taxonomy: %s" % e}), file=sys.stderr)
        return 2

    if args.changed_file:
        with open(args.changed_file, "r", encoding="utf-8") as fh:
            changed = [ln.strip() for ln in fh if ln.strip()]
    else:
        try:
            changed = _changed_from_scope(args.worktree, args.baseline)
        except RuntimeError as e:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
            return 2

    result = reclassify(
        args.baseline, changed, args.worktree, taxonomy,
        max_total_lines=args.max_total_lines,
        max_untracked_bytes=args.max_untracked_bytes,
    )
    print(json.dumps(result, indent=2))
    # Exit 0 = fast-path holds; 1 = ESCALATE. (Non-zero is advisory; caller decides.)
    return 1 if result["escalate"] else 0


# --------------------------------------------------------------------------- #
# Self-test — builds throwaway git repos in $TMPDIR (OUTSIDE the worktree).
# --------------------------------------------------------------------------- #
_TAXONOMY = """
version: 1
path_patterns:
  - glob: "**/*.css"
    difficulty_band: low
    impact_band: low
content_patterns:
  - match: "--color-"
    pattern_type: literal
    case: insensitive
    scan: content
    kind: shared_token
    impact_band: high
  - match: "aria-label"
    pattern_type: literal
    case: insensitive
    scan: content
    kind: a11y
    impact_band: high
  - match: "feature_flag"
    pattern_type: literal
    case: insensitive
    scan: content
    kind: feature_flag
    impact_band: high
  - match: "consent"
    pattern_type: literal
    case: insensitive
    scan: content
    kind: legal_copy
    impact_band: high
  - match: "%[sd]"
    pattern_type: regex
    case: sensitive
    scan: content
    kind: i18n_placeholder
    impact_band: high
sensitive_path_list:
  - "src/auth/**"
  - "**/*.sql"
churn:
  exclude_paths: []
  format_commit_patterns: []
"""


def _selftest():
    import shutil

    tx = _taxonomy_module()
    if not tx:
        print("FAIL - cannot import compound-v-taxonomy.py")
        return 1
    sc = _scope_module()
    if not sc:
        print("FAIL - cannot import compound-v-scope-check.py")
        return 1
    taxonomy = tx.load_taxonomy(text=_TAXONOMY)

    failures = []

    def expect(name, cond):
        print(("  ok   - " if cond else "  FAIL - ") + name)
        if not cond:
            failures.append(name)

    tmp = tempfile.mkdtemp(prefix="cv-f2-selftest-")

    def new_repo(name):
        repo = os.path.join(tmp, name)
        os.makedirs(repo)
        for cmd in (["git", "init", "-q"],
                    ["git", "config", "user.email", "t@t.t"],
                    ["git", "config", "user.name", "t"]):
            subprocess.run(cmd, cwd=repo, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return repo

    def git(repo, args):
        subprocess.run(["git", "-C", repo] + args, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def head(repo):
        return subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                              stdout=subprocess.PIPE, universal_newlines=True,
                              check=True).stdout.strip()

    def write(repo, rel, content, binary=False):
        p = os.path.join(repo, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if binary:
            with open(p, "wb") as fh:
                fh.write(content)
        else:
            # Explicit UTF-8 so non-ASCII fixture content writes identically under a
            # C/POSIX locale (LANG=C), not the locale's ascii default.
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(content)

    # Build changed_paths via scope-check (proves the sibling reuse), then reclassify.
    def run(repo, baseline, parsers=None, **kw):
        changed = sc.changed_files(repo, baseline)
        return reclassify(baseline, changed, repo, taxonomy, parsers=parsers, **kw), changed

    try:
        # 1. Sensitive-path touch escalates.
        r = new_repo("sensitive")
        write(r, "src/auth/login.ts", "// base\n")
        write(r, "README.md", "hi\n")
        git(r, ["add", "-A"]); git(r, ["commit", "-qm", "base"])
        base = head(r)
        write(r, "src/auth/login.ts", "// base\nconst x = 1;\n")
        res, changed = run(r, base)
        expect("sensitive-path touch escalates", res["escalate"] is True)
        expect("sensitive reason names the glob",
               any("sensitive" in x for x in res["reasons"]))

        # 2. Size over threshold (tracked) escalates.
        r = new_repo("size")
        write(r, "notes.txt", "l0\n")
        git(r, ["add", "-A"]); git(r, ["commit", "-qm", "base"])
        base = head(r)
        write(r, "notes.txt", "".join("line %d\n" % i for i in range(80)))
        res, _ = run(r, base, max_total_lines=50)
        expect("tracked size over threshold escalates", res["escalate"] is True)
        expect("size reason present", any("total changed lines" in x for x in res["reasons"]))

        # 3. Oversized untracked TEXT escalates (measured directly, CR3-6).
        r = new_repo("untracked-text")
        write(r, "keep.md", "x\n")
        git(r, ["add", "-A"]); git(r, ["commit", "-qm", "base"])
        base = head(r)
        write(r, "big.txt", "A" * 25000 + "\n")  # untracked, > 20000-byte cap
        res, changed = run(r, base)
        expect("untracked file is seen in changed set", "big.txt" in changed)
        expect("oversized untracked text escalates", res["escalate"] is True)
        expect("untracked-cap reason present",
               any("exceeds" in x and "byte cap" in x for x in res["reasons"]))

        # 4. Oversized untracked BINARY escalates.
        r = new_repo("untracked-bin")
        write(r, "keep.md", "x\n")
        git(r, ["add", "-A"]); git(r, ["commit", "-qm", "base"])
        base = head(r)
        write(r, "blob.bin", b"\x00\x01\x02BINARY" * 4000, binary=True)
        res, _ = run(r, base)
        expect("oversized untracked binary escalates", res["escalate"] is True)
        expect("binary reason present", any("binary change" in x for x in res["reasons"]))

        # 5. Changed Python SIGNATURE escalates (via ast).
        r = new_repo("py-sig")
        write(r, "mod.py", "def foo(a):\n    return a\n")
        git(r, ["add", "-A"]); git(r, ["commit", "-qm", "base"])
        base = head(r)
        write(r, "mod.py", "def foo(a, b):\n    return a + b\n")
        res, _ = run(r, base)
        expect("changed Python signature escalates", res["escalate"] is True)
        expect("py signature reason present",
               any("signature changed" in x for x in res["reasons"]))

        # 5b. Python BODY-ONLY change (unchanged signature, no content hit) does NOT
        #     escalate — proves ast lets a genuinely inert Python edit through.
        r = new_repo("py-body")
        write(r, "mod.py", "def foo(a):\n    return a\n")
        git(r, ["add", "-A"]); git(r, ["commit", "-qm", "base"])
        base = head(r)
        write(r, "mod.py", "def foo(a):\n    return a + 0\n")
        res, _ = run(r, base)
        expect("python body-only change does NOT escalate", res["escalate"] is False)

        # 5c. Adding an `if` to a function body (unchanged signature) ESCALATES on the
        #     control-flow axis — the HIGH-7 repro: identical signature set, added branch.
        r = new_repo("py-cf-if")
        write(r, "mod.py", "def foo(a):\n    return a\n")
        git(r, ["add", "-A"]); git(r, ["commit", "-qm", "base"])
        base = head(r)
        write(r, "mod.py", "def foo(a):\n    if a:\n        return a\n    return 0\n")
        res, _ = run(r, base)
        expect("adding an if to a function body escalates", res["escalate"] is True)
        expect("control-flow reason present",
               any("control-flow structure changed" in x for x in res["reasons"]))
        expect("added-if is NOT a signature change (control-flow axis only)",
               not any("signature changed" in x for x in res["reasons"]))

        # 5d. Adding a `for` loop escalates.
        r = new_repo("py-cf-for")
        write(r, "mod.py", "def foo(a):\n    return a\n")
        git(r, ["add", "-A"]); git(r, ["commit", "-qm", "base"])
        base = head(r)
        write(r, "mod.py", "def foo(a):\n    for x in a:\n        pass\n    return a\n")
        res, _ = run(r, base)
        expect("adding a for loop escalates", res["escalate"] is True)

        # 5e. Adding a `while` loop escalates.
        r = new_repo("py-cf-while")
        write(r, "mod.py", "def foo(a):\n    return a\n")
        git(r, ["add", "-A"]); git(r, ["commit", "-qm", "base"])
        base = head(r)
        write(r, "mod.py", "def foo(a):\n    while a:\n        a = a - 1\n    return a\n")
        res, _ = run(r, base)
        expect("adding a while loop escalates", res["escalate"] is True)

        # 5f. Adding a `try`/`except` handler escalates.
        r = new_repo("py-cf-try")
        write(r, "mod.py", "def foo(a):\n    return a\n")
        git(r, ["add", "-A"]); git(r, ["commit", "-qm", "base"])
        base = head(r)
        write(r, "mod.py",
              "def foo(a):\n    try:\n        return a\n    except Exception:\n        return 0\n")
        res, _ = run(r, base)
        expect("adding a try/except escalates", res["escalate"] is True)

        # 5g. Adding a boolean-branch operator (and/or) escalates.
        r = new_repo("py-cf-boolop")
        write(r, "mod.py", "def foo(a, b):\n    return a\n")
        git(r, ["add", "-A"]); git(r, ["commit", "-qm", "base"])
        base = head(r)
        write(r, "mod.py", "def foo(a, b):\n    return a and b\n")
        res, _ = run(r, base)
        expect("adding a boolean operator escalates", res["escalate"] is True)

        # 5h. Pure comment/whitespace change (no AST delta) does NOT escalate.
        r = new_repo("py-comment")
        write(r, "mod.py", "def foo(a):\n    return a\n")
        git(r, ["add", "-A"]); git(r, ["commit", "-qm", "base"])
        base = head(r)
        write(r, "mod.py", "def foo(a):\n    # a harmless note\n    return  a\n")
        res, _ = run(r, base)
        expect("python comment/whitespace change does NOT escalate", res["escalate"] is False)

        # 5i. Docstring text change does NOT escalate (Constant value, not control flow).
        r = new_repo("py-docstring")
        write(r, "mod.py", 'def foo(a):\n    """old helper"""\n    return a\n')
        git(r, ["add", "-A"]); git(r, ["commit", "-qm", "base"])
        base = head(r)
        write(r, "mod.py", 'def foo(a):\n    """new helper text"""\n    return a\n')
        res, _ = run(r, base)
        expect("python docstring change does NOT escalate", res["escalate"] is False)

        # 5j. Constant-literal change with NO control-flow delta does NOT escalate.
        r = new_repo("py-const")
        write(r, "mod.py", "def foo():\n    return 1\n")
        git(r, ["add", "-A"]); git(r, ["commit", "-qm", "base"])
        base = head(r)
        write(r, "mod.py", "def foo():\n    return 2\n")
        res, _ = run(r, base)
        expect("python constant-literal change does NOT escalate", res["escalate"] is False)

        # 6. Clean tiny CSS diff does NOT escalate.
        r = new_repo("css-clean")
        write(r, "styles/app.css", ".a { color: red; }\n")
        git(r, ["add", "-A"]); git(r, ["commit", "-qm", "base"])
        base = head(r)
        write(r, "styles/app.css", ".a { color: blue; }\n")
        res, _ = run(r, base)
        expect("clean tiny CSS diff does NOT escalate", res["escalate"] is False)

        # 7. Tiny CSS diff introducing a SHARED TOKEN escalates (content re-check).
        r = new_repo("css-token")
        write(r, "styles/app.css", ".a { color: red; }\n")
        git(r, ["add", "-A"]); git(r, ["commit", "-qm", "base"])
        base = head(r)
        write(r, "styles/app.css", ".a { color: var(--color-primary); }\n")
        res, _ = run(r, base)
        expect("CSS introducing shared token escalates", res["escalate"] is True)
        expect("shared_token content reason present",
               any("shared_token" in x for x in res["reasons"]))

        # 7b. Tiny CSS diff introducing an a11y construct escalates.
        r = new_repo("css-a11y")
        write(r, "c.css", "/* x */\n")
        git(r, ["add", "-A"]); git(r, ["commit", "-qm", "base"])
        base = head(r)
        write(r, "c.css", "/* x */\n/* aria-label tweak */\n")
        res, _ = run(r, base)
        expect("CSS introducing a11y construct escalates", res["escalate"] is True)

        # 8. String-literal hunk matching a content pattern escalates (body-only Python).
        r = new_repo("str-literal")
        write(r, "flags.py", "def cfg():\n    return {}\n")
        git(r, ["add", "-A"]); git(r, ["commit", "-qm", "base"])
        base = head(r)
        write(r, "flags.py", 'def cfg():\n    return {"feature_flag": True}\n')
        res, _ = run(r, base)
        expect("string-literal feature_flag hunk escalates", res["escalate"] is True)
        expect("feature_flag content reason present",
               any("feature_flag" in x for x in res["reasons"]))

        # 9. Parse-failure escalates (Python syntax error in worktree).
        r = new_repo("parse-fail")
        write(r, "broke.py", "def ok():\n    return 1\n")
        git(r, ["add", "-A"]); git(r, ["commit", "-qm", "base"])
        base = head(r)
        write(r, "broke.py", "def ok(:\n    return 1\n")  # syntax error
        res, _ = run(r, base)
        expect("python parse-failure escalates", res["escalate"] is True)
        expect("parse-failure reason present",
               any("parse failure" in x for x in res["reasons"]))

        # 10. JS non-trivial change with NO parser escalates (fail-closed).
        r = new_repo("js-noparser")
        write(r, "app.js", "const a = 1;\n")
        git(r, ["add", "-A"]); git(r, ["commit", "-qm", "base"])
        base = head(r)
        write(r, "app.js", "const a = 1;\nconst b = compute(a);\n")
        res, _ = run(r, base)  # default parsers = empty
        expect("JS non-trivial change with no parser escalates", res["escalate"] is True)
        expect("no-parser fail-closed reason present",
               any("no parser present" in x for x in res["reasons"]))

        # 10b. Go + Ruby non-trivial, no parser → escalate too.
        for ext, code in ((".go", "x := doThing()\n"), (".rb", "y = do_thing\n")):
            r = new_repo("lang" + ext.replace(".", ""))
            write(r, "f" + ext, "// base\n" if ext == ".go" else "# base\n")
            git(r, ["add", "-A"]); git(r, ["commit", "-qm", "base"])
            base = head(r)
            write(r, "f" + ext, ("// base\n" if ext == ".go" else "# base\n") + code)
            res, _ = run(r, base)
            expect("%s non-trivial change with no parser escalates" % ext, res["escalate"] is True)

        # 11. Provably-trivial COMMENT-ONLY change does NOT escalate (JS).
        r = new_repo("js-comment")
        write(r, "app.js", "const a = 1;\n")
        git(r, ["add", "-A"]); git(r, ["commit", "-qm", "base"])
        base = head(r)
        write(r, "app.js", "const a = 1;\n// a harmless note\n")
        res, _ = run(r, base)
        expect("JS comment-only change does NOT escalate", res["escalate"] is False)

        # 11b. Ruby comment-only change does NOT escalate.
        r = new_repo("rb-comment")
        write(r, "a.rb", "x = 1\n")
        git(r, ["add", "-A"]); git(r, ["commit", "-qm", "base"])
        base = head(r)
        write(r, "a.rb", "x = 1\n# just a comment\n")
        res, _ = run(r, base)
        expect("Ruby comment-only change does NOT escalate", res["escalate"] is False)

        # 12. Deleted file escalates; renamed (git mv) escalates via the deleted source.
        r = new_repo("delete")
        write(r, "a.txt", "one\n")
        write(r, "b.txt", "two\n")
        git(r, ["add", "-A"]); git(r, ["commit", "-qm", "base"])
        base = head(r)
        git(r, ["rm", "-q", "a.txt"])
        res, changed = run(r, base)
        expect("deleted file is in changed set", "a.txt" in changed)
        expect("deleted file escalates", res["escalate"] is True)

        r = new_repo("rename")
        write(r, "docs/keep.md", "keep\n")
        write(r, "src/mod.py", "x = 1\n")
        git(r, ["add", "-A"]); git(r, ["commit", "-qm", "base"])
        base = head(r)
        git(r, ["mv", "docs/keep.md", "src/keep.md"])
        res, changed = run(r, base)
        expect("renamed source path surfaces (--no-renames)", "docs/keep.md" in changed)
        expect("renamed change escalates", res["escalate"] is True)

        # 13. Worker-COMMITTED-in-worktree change is seen (baseline-relative). Commit a
        #     sensitive-path change inside the worktree; diffing HEAD would look clean,
        #     but the pinned baseline still surfaces + escalates it.
        r = new_repo("committed")
        write(r, "src/auth/x.ts", "// base\n")
        git(r, ["add", "-A"]); git(r, ["commit", "-qm", "base"])
        base = head(r)
        write(r, "src/auth/x.ts", "// base\nexport const leak = 1;\n")
        git(r, ["add", "-A"]); git(r, ["commit", "-qm", "sneaky in-worktree commit"])
        # HEAD-baselined view is clean:
        changed_head = sc.changed_files(r, "HEAD")
        expect("committed-in-worktree: HEAD view is clean", changed_head == [])
        # Pinned-baseline view sees + escalates it:
        res, changed = run(r, base)
        expect("committed-in-worktree change seen (baseline-relative)",
               "src/auth/x.ts" in changed)
        expect("committed-in-worktree change escalates", res["escalate"] is True)

        # 14. Injected FAKE parser proves the parser path runs through the supervisor.
        #     Clean parse (exit 0) → no escalate; failing parser (exit 1) → escalate.
        fake_ok = os.path.join(tmp, "fake_ok.py")
        with open(fake_ok, "w") as fh:
            fh.write("#!/usr/bin/env python3\nimport sys\nsys.exit(0)\n")
        fake_bad = os.path.join(tmp, "fake_bad.py")
        with open(fake_bad, "w") as fh:
            fh.write("#!/usr/bin/env python3\nimport sys\nsys.exit(1)\n")

        r = new_repo("js-parser")
        write(r, "app.js", "const a = 1;\n")
        git(r, ["add", "-A"]); git(r, ["commit", "-qm", "base"])
        base = head(r)
        write(r, "app.js", "const a = 1;\nconst b = compute(a);\n")  # non-trivial
        res_ok, _ = run(r, base, parsers={".js": [sys.executable, fake_ok]})
        expect("JS non-trivial + clean parser present -> does NOT escalate",
               res_ok["escalate"] is False)
        res_bad, _ = run(r, base, parsers={".js": [sys.executable, fake_bad]})
        expect("JS non-trivial + failing parser -> escalates", res_bad["escalate"] is True)

        # 15. Non-ASCII content under any locale must not crash (routes the regex
        #     content pattern through the UTF-8 subprocess path). Escalates on the
        #     i18n %s hit; the point is it returns cleanly under LANG=C.
        r = new_repo("nonascii")
        write(r, "copy.txt", "hello\n")
        git(r, ["add", "-A"]); git(r, ["commit", "-qm", "base"])
        base = head(r)
        write(r, "copy.txt", "hello\nBonjour %s — café naïve\n")
        res, _ = run(r, base)
        expect("non-ASCII scan returns without crashing (escalates on %s i18n)",
               res["escalate"] is True)

        # 16. Baseline-empty NEW Python file WITH a def escalates (new signature);
        #     new Python file WITHOUT any def and no content hit does NOT.
        r = new_repo("newpy")
        write(r, "keep.md", "x\n")
        git(r, ["add", "-A"]); git(r, ["commit", "-qm", "base"])
        base = head(r)
        write(r, "newmod.py", "def brand_new(a, b):\n    return a\n")  # untracked new file
        res, _ = run(r, base)
        expect("new Python file with a def escalates", res["escalate"] is True)

        r = new_repo("newpy-nodef")
        write(r, "keep.md", "x\n")
        git(r, ["add", "-A"]); git(r, ["commit", "-qm", "base"])
        base = head(r)
        write(r, "const.py", "X = 1\n")  # untracked, no def, no content hit, tiny
        res, _ = run(r, base)
        expect("new tiny Python file with no def/content does NOT escalate",
               res["escalate"] is False)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        print("\nSELFTEST FAILED: %d case(s)" % len(failures))
        return 1
    print("\nSELFTEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
