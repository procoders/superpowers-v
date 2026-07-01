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
        # NOTE: this input-side scan is ADVISORY. It surfaces secret-shaped strings
        # anywhere in the repo — including test fixtures and docs that *document*
        # secret patterns — for the human gate to eyeball; it does NOT hard-block the
        # run. The BLOCKING refusal is scan_output_files() on the GENERATED docs, per
        # the spec invariant "no credential reaches a generated, committed file".
        "secret_scan": {"clean": not secret_hits, "hits": secret_hits},
    }


def scan_output_files(repo: str, rels) -> dict:
    """OUTPUT-side secret gate (BLOCKING). Scan the GENERATED files about to be
    written/committed (architecture/*, CONVENTIONS.md, AGENTS.md, CLAUDE.md). A match
    here is a hard refusal — a credential must never enter a committed doc (e.g. via a
    citation snippet). The pack() input scan is advisory; THIS is the gate before WRITE."""
    hits = []
    for rel in rels:
        ab = rel if os.path.isabs(rel) else os.path.join(repo, rel)
        try:
            with open(ab, "r", errors="replace") as fh:
                for h in scan_secrets(fh.read()):
                    hits.append({"path": rel, "family": h["family"]})
        except OSError:
            continue
    return {"clean": not hits, "hits": hits}


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


# --------------------------------------------------------------------------- MCP recommender
# Signal -> tool recommendations. CURATED + currency-verified (2026-07-01, WebSearch). Bias: an
# already-authenticated CLI over an MCP server when a good one exists. github.com -> gh CLI (NOT
# a GitHub MCP: avoids the broad-PAT toxic flow). Least-privilege flags pre-filled.
MCP_RULES = {
    "github":   {"id": "github", "kind": "cli", "tool": "gh CLI", "flags": [], "trifecta": False,
                 "note": "Use the authenticated gh CLI, NOT a GitHub MCP server — avoids the broad-PAT toxic flow."},
    "supabase": {"id": "supabase", "kind": "mcp", "tool": "Supabase MCP",
                 "package": "@supabase/mcp-server-supabase",
                 "flags": ["--read-only", "--project-ref=<dev-or-branch-ref>"], "trifecta": True,
                 "note": "Read-only + project-scoped defuses the 2025 service-role toxic flow at the source."},
    "postgres": {"id": "postgres", "kind": "mcp", "tool": "Postgres MCP",
                 "package": "crystaldba/postgres-mcp", "flags": ["--access-mode=restricted"], "trifecta": True,
                 "note": "Restricted access mode = read-only, safe for exploration."},
    "playwright": {"id": "playwright", "kind": "mcp", "tool": "Playwright MCP",
                   "package": "@playwright/mcp@>=0.0.40", "flags": [], "trifecta": False,
                   "note": "Pin >=0.0.40 (CVE-2025-9611: DNS-rebinding via missing Origin validation)."},
    "context7": {"id": "context7", "kind": "mcp", "tool": "Context7",
                 "package": "@upstash/context7-mcp", "flags": [], "trifecta": False,
                 "note": "Up-to-date library docs for fast-moving deps."},
    "sentry":   {"id": "sentry", "kind": "mcp", "tool": "Sentry MCP",
                 "package": "@sentry/mcp-server", "flags": [], "trifecta": False,
                 "note": "Error/issue context from Sentry."},
}
FASTMOVING = ("react", "next", "vue", "svelte", "@sveltejs/kit", "nuxt", "tailwindcss",
              "prisma", "@prisma/client", "astro", "solid-js")
TRIFECTA_REMEDY = ("run read-only (pre-filled) + scope to a dev/branch DB (not prod), and keep "
                   "it a single-repo session so untrusted content can't exfiltrate private data")


def _git_remote(repo):
    try:
        out = subprocess.run(["git", "-C", repo, "remote", "-v"],
                             capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def _pkg_deps(repo):
    """Dependency names from package.json (deps + devDeps). Returns ({name: ver}, evidence|None)."""
    pj = os.path.join(repo, "package.json")
    if not os.path.isfile(pj):
        return {}, None
    try:
        with open(pj) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}, None
    deps = {}
    for key in ("dependencies", "devDependencies"):
        d = data.get(key)
        if isinstance(d, dict):
            deps.update(d)
    return deps, "package.json"


def _rec(rule_id, evidence):
    r = dict(MCP_RULES[rule_id])
    r["evidence"] = evidence
    return r


def recommend_mcp(repo):
    """Deterministic signal -> tool recommender. Returns {recommendations, warnings}. Each
    recommendation is an MCP_RULES row + `evidence`; an unknown stack yields an empty set (no
    invented tools). CLI-over-MCP bias: a github remote yields the gh CLI, never a GitHub MCP."""
    recs, seen = [], set()

    def add(rule_id, evidence):
        if rule_id not in seen:
            recs.append(_rec(rule_id, evidence))
            seen.add(rule_id)

    remote = _git_remote(repo)
    if remote and "github.com" in remote:
        add("github", "git remote references github.com")

    deps, dep_ev = _pkg_deps(repo)
    if any(d.startswith("@supabase/") for d in deps):
        add("supabase", dep_ev)
    if any(d.startswith("@sentry/") for d in deps):
        add("sentry", dep_ev)
    if any(d in deps for d in ("pg", "prisma", "@prisma/client")):
        add("postgres", dep_ev)
    if any(d in deps for d in FASTMOVING):
        add("context7", dep_ev)

    for name in ("playwright.config.ts", "playwright.config.js", "playwright.config.mjs"):
        if os.path.isfile(os.path.join(repo, name)):
            add("playwright", name)
            break

    warnings = [{"id": r["id"],
                 "message": "%s combines private-data access with write capability (lethal-trifecta risk)." % r["tool"],
                 "remedy": TRIFECTA_REMEDY}
                for r in recs if r["trifecta"]]
    return {"recommendations": recs, "warnings": warnings}


def mcp_json_config(recommendations, existing=None):
    """Additive .mcp.json for the kind=='mcp' recommendations. Never clobbers an existing
    same-named server; CLI recs (e.g. gh) are excluded (surfaced as setup instructions)."""
    servers = dict((existing or {}).get("mcpServers", {}))
    for r in recommendations:
        if r.get("kind") != "mcp" or r["id"] in servers:
            continue
        servers[r["id"]] = {"command": "npx", "args": ["-y", r["package"]] + list(r["flags"])}
    return {"mcpServers": servers}


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

    # OUTPUT-side secret gate: blocks a secret in a GENERATED doc, passes clean prose.
    d6 = tempfile.mkdtemp()
    try:
        with open(os.path.join(d6, "architecture.md"), "w") as fh:
            fh.write("# Arch\nThe scope gate unions git diff with ls-files.\n")
        with open(os.path.join(d6, "bad.md"), "w") as fh:
            fh.write("leaked token ghp_" + "a" * 22 + " pulled into a generated doc\n")
        check("scan-output passes clean generated doc",
              scan_output_files(d6, ["architecture.md"])["clean"] is True)
        _r = scan_output_files(d6, ["bad.md"])
        check("scan-output blocks secret in generated doc",
              _r["clean"] is False and any(h["path"] == "bad.md" for h in _r["hits"]))
    finally:
        shutil.rmtree(d6, ignore_errors=True)

    # --- recommend-mcp (v2.5.1) ---
    d7 = tempfile.mkdtemp()
    try:
        _sp.run(["git", "-C", d7, "init", "-q"], check=True, capture_output=True)
        _sp.run(["git", "-C", d7, "remote", "add", "origin",
                 "https://github.com/acme/app.git"], check=True, capture_output=True)
        with open(os.path.join(d7, "package.json"), "w") as fh:
            json.dump({"dependencies": {"@supabase/supabase-js": "^2", "next": "^15", "pg": "^8"}}, fh)
        with open(os.path.join(d7, "playwright.config.ts"), "w") as fh:
            fh.write("export default {};\n")
        out = recommend_mcp(d7)
        ids = sorted(r["id"] for r in out["recommendations"])
        check("recommend: github -> gh CLI (kind cli, no MCP)",
              any(r["id"] == "github" and r["kind"] == "cli" for r in out["recommendations"]))
        check("recommend: supabase MCP with --read-only",
              any(r["id"] == "supabase" and "--read-only" in r["flags"] for r in out["recommendations"]))
        check("recommend: postgres (pg dep) restricted",
              any(r["id"] == "postgres" and "--access-mode=restricted" in r["flags"] for r in out["recommendations"]))
        check("recommend: fast-moving dep -> context7", "context7" in ids)
        check("recommend: playwright.config -> playwright MCP", "playwright" in ids)
        check("recommend: every rec carries evidence",
              all(r.get("evidence") for r in out["recommendations"]))
        check("recommend: lethal-trifecta warning w/ remedy for supabase/postgres",
              any(w["id"] in ("supabase", "postgres") and w["remedy"] for w in out["warnings"]))
        cfg = mcp_json_config(out["recommendations"])
        check("mcp_json: cli (github) excluded, supabase MCP present",
              "github" not in cfg["mcpServers"] and "supabase" in cfg["mcpServers"])
        check("mcp_json: supabase carries --read-only",
              "--read-only" in cfg["mcpServers"]["supabase"]["args"])
        merged = mcp_json_config(out["recommendations"], existing={"mcpServers": {"custom": {"command": "x"}}})
        check("mcp_json: additive merge preserves existing",
              "custom" in merged["mcpServers"] and "supabase" in merged["mcpServers"])
        clobber = mcp_json_config(out["recommendations"], existing={"mcpServers": {"supabase": {"command": "MINE"}}})
        check("mcp_json: never clobbers an existing same-name server",
              clobber["mcpServers"]["supabase"]["command"] == "MINE")
        d7b = tempfile.mkdtemp()
        try:
            check("recommend: unknown stack -> empty set",
                  recommend_mcp(d7b)["recommendations"] == [])
        finally:
            shutil.rmtree(d7b, ignore_errors=True)
    finally:
        shutil.rmtree(d7, ignore_errors=True)

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
    sp = sub.add_parser("scan-output")
    sp.add_argument("--files", nargs="+", required=True)
    sp.add_argument("--repo", default="."); sp.add_argument("--json", action="store_true")
    sp = sub.add_parser("recommend-mcp")
    sp.add_argument("--repo", default=".")
    sp.add_argument("--mcp-config", default=None, help="existing .mcp.json to merge into (diff view)")
    sp.add_argument("--json", action="store_true")
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
    if args.cmd == "scan-output":
        result = scan_output_files(os.path.abspath(args.repo), args.files)
        print(json.dumps(result, indent=2))
        return 0 if result["clean"] else 2
    if args.cmd == "recommend-mcp":
        repo = os.path.abspath(args.repo)
        out = recommend_mcp(repo)
        existing = None
        if args.mcp_config and os.path.isfile(args.mcp_config):
            try:
                with open(args.mcp_config) as fh:
                    existing = json.load(fh)
            except (OSError, ValueError):
                existing = None
        out["mcp_json"] = mcp_json_config(out["recommendations"], existing)
        print(json.dumps(out, indent=2))
        return 0
    build_parser().print_help(); return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
