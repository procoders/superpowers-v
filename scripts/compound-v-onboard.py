#!/usr/bin/env python3
"""Compound V — /v:onboard deterministic toolkit (stdlib only)."""
import argparse, json, os, re, subprocess, sys, importlib.util

# Reuse the engine's canonical secret families (do NOT fork a second list).
_ENGINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "compound-v-memory.py")
_spec = importlib.util.spec_from_file_location("cv_memory", _ENGINE)
cv_memory = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(cv_memory)
SECRET_RE, PEM_RE = cv_memory.SECRET_RE, cv_memory.PEM_RE


def scan_secrets(text: str):
    hits = []
    if PEM_RE.search(text):
        hits.append({"family": "pem-key"})
    for m in SECRET_RE.finditer(text):
        hits.append({"family": "token"})
    return hits


VENDOR_DIRS = ("node_modules", "vendor", "dist", "build", ".git", "__pycache__")


def _git_tracked(repo: str):
    out = subprocess.run(["git", "-C", repo, "ls-files", "-z"],
                         capture_output=True, timeout=60)
    if out.returncode != 0:
        return []
    return [p for p in out.stdout.decode("utf-8", "replace").split("\0") if p]


def _exclude_reason(rel: str):
    low = rel.lower()
    if any(("/" + d + "/") in ("/" + low) or low.startswith(d + "/") for d in VENDOR_DIRS):
        return "vendored"
    if low.endswith((".min.js", ".lock")) or "/generated/" in low:
        return "generated"
    if low.endswith((".png", ".jpg", ".gif", ".pdf", ".ico", ".woff", ".woff2")):
        return "binary"
    return None


def pack(repo: str, token_budget: int = 200_000) -> dict:
    files = _git_tracked(repo)
    included, excluded, secret_hits = [], [], []
    for rel in files:
        reason = _exclude_reason(rel)
        if reason:
            excluded.append({"path": rel, "reason": reason}); continue
        included.append(rel)
        try:
            with open(os.path.join(repo, rel), "r", errors="replace") as fh:
                for h in scan_secrets(fh.read()):
                    secret_hits.append({"path": rel, "family": h["family"]})
        except OSError:
            pass
    return {
        "repo_shape": "single",
        "token_budget": token_budget,
        "included": sorted(included),
        "excluded": sorted(excluded, key=lambda e: e["path"]),
        "truncated": [],
        "secret_scan": {"clean": not secret_hits, "hits": secret_hits},
    }


def _line_count(abspath: str) -> int:
    try:
        with open(abspath, "rb") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return -1


def tier1_check(claim: dict, repo: str):
    reasons = []
    for c in claim.get("citations", []):
        ab = os.path.join(repo, c.get("path", ""))
        n = _line_count(ab)
        if n < 0:
            reasons.append("bad-path"); continue
        s, e = c.get("startLine", 0), c.get("endLine", 0)
        if s > e:
            reasons.append("range-inverted")
        elif not (1 <= s <= e <= n):
            reasons.append("range-out-of-bounds")
    if not claim.get("citations"):
        reasons.append("bad-path")
    return reasons


def apply_tier2(claims, verdicts):
    by_idx = {v["index"]: v["support"] for v in verdicts}
    blocked, downgraded = [], []
    for i, cl in enumerate(claims):
        sup = by_idx.get(i, "yes")
        if sup == "yes":
            continue
        if cl.get("load_bearing"):
            blocked.append({"index": i, "reason": "load-bearing-unsupported"})
        else:
            downgraded.append({"index": i, "to": "observed" if sup == "partial" else "inference"})
    return blocked, downgraded


def cmd_verify(args) -> int:
    repo = os.path.abspath(args.repo)
    claims = json.load(open(args.claims))["claims"]
    blocked, downgraded = [], []
    for i, cl in enumerate(claims):
        for r in tier1_check(cl, repo):
            blocked.append({"index": i, "reason": r})
    if args.tier2:
        verdicts = json.load(open(args.tier2))["verdicts"]
        b2, dg = apply_tier2(claims, verdicts)
        blocked += b2; downgraded += dg
    verdict = {"ok": not blocked, "blocked": blocked, "downgraded": downgraded,
               "passed": len(claims) - len({b["index"] for b in blocked})}
    print(json.dumps(verdict, indent=2))
    return 0 if verdict["ok"] else 2


MANIFEST_REL = os.path.join("docs", "superpowers", "architecture", ".onboard-manifest.json")


def write_manifest(repo: str, docmap: dict) -> str:
    import datetime
    docs = {}
    for doc, srcs in docmap.items():
        cited = {}
        for src in srcs:
            ab = os.path.join(repo, src)
            cited[src] = cv_memory.file_sha(ab) if os.path.exists(ab) else ""
        docs[doc] = {"cited": cited}
    man = {"generated": datetime.date.today().isoformat(), "docs": docs}
    path = os.path.join(repo, MANIFEST_REL)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(man, fh, indent=2)
    return path


def check_staleness(repo: str) -> dict:
    path = os.path.join(repo, MANIFEST_REL)
    if not os.path.exists(path):
        return {"stale": [], "count": 0}
    man = json.load(open(path))
    stale = []
    cited_paths = set()
    for doc, info in man.get("docs", {}).items():
        for src, sha in info.get("cited", {}).items():
            cited_paths.add(src)
            ab = os.path.join(repo, src)
            if not os.path.exists(ab):
                stale.append({"doc": doc, "reason": "cited-deleted"})
            elif cv_memory.file_sha(ab) != sha:
                stale.append({"doc": doc, "reason": "cited-changed"})
    # uncited-new-file heuristic: a new file in a cited doc's path-space nothing references
    cited_dirs = {os.path.dirname(p) for p in cited_paths}
    tracked = set(_git_tracked(repo))
    for f in tracked:
        if os.path.dirname(f) in cited_dirs and f not in cited_paths:
            stale.append({"doc": "(path-space)", "reason": "uncited-new-file"})
            break
    return {"stale": stale, "count": len(stale)}


def cmd_staleness(args) -> int:
    repo = os.path.abspath(args.repo)
    if args.write:
        docmap = json.load(open(args.docmap))["docs"] if args.docmap else {}
        write_manifest(repo, docmap)
        if not args.quiet:
            print(json.dumps({"written": MANIFEST_REL}, indent=2))
        return 0
    result = check_staleness(repo)
    if args.quiet:
        print(result["count"])
    else:
        print(json.dumps(result, indent=2))
    return 0


UI_SIGNALS = ("tailwind.config.js", "tailwind.config.ts", "postcss.config.js")
UI_EXT = (".tsx", ".jsx", ".vue", ".svelte")


def detect_ui(repo: str) -> bool:
    for s in UI_SIGNALS:
        if os.path.exists(os.path.join(repo, s)):
            return True
    for f in _git_tracked(repo):
        if f.endswith(UI_EXT):
            return True
    return False


def _design_result_ok(result: dict) -> bool:
    return int(result.get("summary", {}).get("errors", 1)) == 0


def design_lint(file: str) -> dict:
    try:
        out = subprocess.run(["npx", "--yes", "@google/design.md", "lint", file, "--json"],
                             capture_output=True, timeout=120)
        if out.returncode not in (0, 1):  # tool ran; 1 == findings present
            return {"ok": False, "errors": -1, "warnings": 0, "findings": [], "note": "tool-unavailable"}
        result = json.loads(out.stdout.decode("utf-8", "replace") or "{}")
        s = result.get("summary", {})
        return {"ok": _design_result_ok(result), "errors": int(s.get("errors", 1)),
                "warnings": int(s.get("warnings", 0)), "findings": result.get("findings", [])}
    except (OSError, subprocess.SubprocessError, ValueError):
        return {"ok": False, "errors": -1, "warnings": 0, "findings": [], "note": "tool-unavailable"}


def _selftest() -> int:
    fails = []
    def check(name, cond):
        print(("  ok   " if cond else "  FAIL ") + name)
        if not cond: fails.append(name)

    check("scan_secrets finds ghp_", scan_secrets("x ghp_" + "a"*22 + " y") != [])
    check("scan_secrets finds PEM",
          scan_secrets("-----BEGIN RSA PRIVATE KEY-----\nz\n-----END RSA PRIVATE KEY-----") != [])
    check("scan_secrets clean text", scan_secrets("just normal prose") == [])

    import tempfile, subprocess as _sp, shutil
    d = tempfile.mkdtemp()
    try:
        _sp.run(["git", "-C", d, "init", "-q"], check=True)
        os.makedirs(os.path.join(d, "node_modules", "x"))
        with open(os.path.join(d, "app.py"), "w") as fh: fh.write("print(1)\n")
        with open(os.path.join(d, "node_modules", "x", "y.js"), "w") as fh: fh.write("//\n")
        with open(os.path.join(d, "leak.env"), "w") as fh: fh.write("KEY=ghp_" + "a"*22 + "\n")
        _sp.run(["git", "-C", d, "add", "-A"], check=True)
        m = pack(d)
        check("pack includes source", "app.py" in m["included"])
        check("pack excludes vendored", any(e["reason"] == "vendored" for e in m["excluded"]))
        check("pack secret scan blocks", m["secret_scan"]["clean"] is False
              and any(h["path"] == "leak.env" for h in m["secret_scan"]["hits"]))
    finally:
        shutil.rmtree(d, ignore_errors=True)

    d2 = tempfile.mkdtemp()
    try:
        with open(os.path.join(d2, "f.py"), "w") as fh: fh.write("a\nb\nc\n")  # 3 lines
        good = {"text": "t", "type": "architecture", "citations": [{"path": "f.py", "startLine": 1, "endLine": 2}],
                "load_bearing": False, "load_bearing_reason": "other", "confidence": "high", "target_doc_section": "x"}
        badpath = {**good, "citations": [{"path": "nope.py", "startLine": 1, "endLine": 1}]}
        oob = {**good, "citations": [{"path": "f.py", "startLine": 1, "endLine": 9}]}
        inv = {**good, "citations": [{"path": "f.py", "startLine": 3, "endLine": 1}]}
        check("tier1 ok", tier1_check(good, d2) == [])
        check("tier1 bad path", "bad-path" in tier1_check(badpath, d2))
        check("tier1 range oob", "range-out-of-bounds" in tier1_check(oob, d2))
        check("tier1 range inverted", "range-inverted" in tier1_check(inv, d2))
    finally:
        shutil.rmtree(d2, ignore_errors=True)

    claims3 = [
        {"text": "secures", "type": "architecture", "citations": [], "load_bearing": True,
         "load_bearing_reason": "security", "confidence": "high", "target_doc_section": "s"},
        {"text": "ordinary", "type": "architecture", "citations": [], "load_bearing": False,
         "load_bearing_reason": "other", "confidence": "low", "target_doc_section": "o"},
    ]
    v_no = {"verdicts": [{"index": 0, "support": "no"}, {"index": 1, "support": "no"}]}
    b, dg = apply_tier2(claims3, v_no["verdicts"])
    check("tier2 blocks load-bearing unsupported",
          any(x["index"] == 0 and x["reason"] == "load-bearing-unsupported" for x in b))
    check("tier2 downgrades ordinary unsupported",
          any(x["index"] == 1 and x["to"] in ("observed", "inference") for x in dg))
    v_yes = {"verdicts": [{"index": 0, "support": "yes"}, {"index": 1, "support": "yes"}]}
    b2, dg2 = apply_tier2(claims3, v_yes["verdicts"])
    check("tier2 supported passes", b2 == [] and dg2 == [])

    d4 = tempfile.mkdtemp()
    try:
        arch = os.path.join(d4, "docs", "superpowers", "architecture"); os.makedirs(arch)
        with open(os.path.join(d4, "src.py"), "w") as fh: fh.write("v1\n")
        man = {"generated": "2026-06-30", "docs": {
            "docs/superpowers/architecture/architecture.md": {
                "cited": {"src.py": cv_memory.file_sha(os.path.join(d4, "src.py"))}}}}
        with open(os.path.join(arch, ".onboard-manifest.json"), "w") as fh: json.dump(man, fh)
        check("staleness clean when unchanged", check_staleness(d4)["count"] == 0)
        with open(os.path.join(d4, "src.py"), "w") as fh: fh.write("v2 changed\n")
        st = check_staleness(d4)
        check("staleness flags cited-changed", any(s["reason"] == "cited-changed" for s in st["stale"]))
        os.remove(os.path.join(d4, "src.py"))
        check("staleness flags cited-deleted", any(s["reason"] == "cited-deleted" for s in check_staleness(d4)["stale"]))
    finally:
        shutil.rmtree(d4, ignore_errors=True)

    fake_ok = {"findings": [{"severity": "warning", "path": "c.b", "message": "ok"}],
               "summary": {"errors": 0, "warnings": 1, "info": 0}}
    fake_bad = {"findings": [{"severity": "error", "path": "c.b", "message": "contrast"}],
                "summary": {"errors": 1, "warnings": 0, "info": 0}}
    check("design_lint ok parses", _design_result_ok(fake_ok) is True)
    check("design_lint error blocks", _design_result_ok(fake_bad) is False)
    d5 = tempfile.mkdtemp()
    try:
        with open(os.path.join(d5, "tailwind.config.js"), "w") as fh: fh.write("module.exports={}\n")
        check("detect_ui true on tailwind", detect_ui(d5) is True)
    finally:
        shutil.rmtree(d5, ignore_errors=True)
    check("detect_ui false on bare", detect_ui(tempfile.mkdtemp()) is False)

    print("FAILED %d" % len(fails) if fails else "OK")
    return 1 if fails else 0


def build_parser():
    p = argparse.ArgumentParser(description="Compound V — /v:onboard toolkit")
    p.add_argument("--selftest", action="store_true")
    sub = p.add_subparsers(dest="cmd")
    sp = sub.add_parser("pack"); sp.add_argument("--repo", default="."); sp.add_argument("--json", action="store_true")
    sp = sub.add_parser("verify-citations")
    sp.add_argument("--claims", required=True); sp.add_argument("--tier2", default=None)
    sp.add_argument("--repo", default="."); sp.add_argument("--json", action="store_true")
    sp = sub.add_parser("staleness")
    sp.add_argument("--repo", default="."); sp.add_argument("--write", action="store_true")
    sp.add_argument("--docmap", default=None); sp.add_argument("--quiet", action="store_true")
    sp.add_argument("--json", action="store_true")
    sp = sub.add_parser("design-lint")
    sp.add_argument("--file", required=True); sp.add_argument("--json", action="store_true")
    sp = sub.add_parser("detect-ui"); sp.add_argument("--repo", default=".")
    return p


def main(argv) -> int:
    args = build_parser().parse_args(argv)
    if args.selftest:
        return _selftest()
    if args.cmd == "pack":
        print(json.dumps(pack(os.path.abspath(args.repo)), indent=2))
        return 0
    if args.cmd == "verify-citations":
        return cmd_verify(args)
    if args.cmd == "staleness":
        return cmd_staleness(args)
    if args.cmd == "design-lint":
        result = design_lint(args.file)
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 2
    if args.cmd == "detect-ui":
        print("ui" if detect_ui(os.path.abspath(args.repo)) else "no-ui")
        return 0
    build_parser().print_help(); return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
