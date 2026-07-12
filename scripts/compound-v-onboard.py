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


DSN_RE = re.compile(r"postgres(?:ql)?://")
# Trifecta-risky server ids -> the least-privilege flag that defuses them.
TRIFECTA_SERVERS = {"supabase": "--read-only", "postgres": "--access-mode=restricted"}


def _pkg_deps(repo):
    """Dependency names from package.json (deps + devDeps). Returns ({name: ver}, {name: line})."""
    pj = os.path.join(repo, "package.json")
    if not os.path.isfile(pj):
        return {}, {}
    try:
        with open(pj) as fh:
            text = fh.read()
        data = json.loads(text)
    except (OSError, ValueError):
        return {}, {}
    deps = {}
    for key in ("dependencies", "devDependencies"):
        d = data.get(key)
        if isinstance(d, dict):
            deps.update(d)
    lines = text.splitlines()
    line_of = {}
    for name in deps:
        needle = '"%s"' % name
        for i, ln in enumerate(lines, 1):
            if needle in ln:
                line_of[name] = i
                break
    return deps, line_of


def _dep_ev(line_of, name):
    """Citation-grade evidence for a matched dependency: `package.json:<line>` (file-level fallback)."""
    n = line_of.get(name)
    return "package.json:%d" % n if n else "package.json"


def _postgres_dsn(repo):
    """A Postgres DSN in a common config file -> `<relpath>:<line>`, else None. Catches Postgres
    repos with no pg/prisma npm dep (e.g. Python / other-language stacks)."""
    for rel in (".env", ".env.local", ".env.example", "prisma/schema.prisma"):
        p = os.path.join(repo, rel)
        if not os.path.isfile(p):
            continue
        try:
            with open(p, errors="ignore") as fh:
                for i, ln in enumerate(fh, 1):
                    if DSN_RE.search(ln):
                        return "%s:%d" % (rel, i)
        except OSError:
            continue
    return None


def _rec(rule_id, evidence):
    r = dict(MCP_RULES[rule_id])
    r["evidence"] = evidence
    return r


def _trifecta_warn(rid, tool):
    return {"id": rid,
            "message": "%s combines private-data access with write capability (lethal-trifecta risk)." % tool,
            "remedy": TRIFECTA_REMEDY}


def _existing_trifecta_warnings(existing):
    """Warn on an EXISTING .mcp.json server that looks like a private-data+write MCP (supabase /
    postgres) but is MISSING its least-privilege flag — the user's own prior config, not our rec."""
    out = []
    servers = (existing or {}).get("mcpServers", {})
    if not isinstance(servers, dict):
        return out
    for name, cfg in servers.items():
        args = [str(a) for a in (cfg or {}).get("args", [])]
        blob = (name + " " + " ".join(args)).lower()
        rid = "supabase" if "supabase" in blob else ("postgres" if ("postgres" in blob or "postgresql" in blob) else None)
        if rid is None:
            continue
        flag = TRIFECTA_SERVERS[rid].split("=")[0]
        if not any(flag in a for a in args):
            out.append({"id": "existing:%s" % name,
                        "message": "Existing .mcp.json server '%s' looks like a %s server WITHOUT its least-privilege flag (%s) — lethal-trifecta risk." % (name, rid, TRIFECTA_SERVERS[rid]),
                        "remedy": TRIFECTA_REMEDY})
    return out


def recommend_mcp(repo, existing=None):
    """Deterministic signal -> tool recommender. Returns {recommendations, warnings}. Each
    recommendation is an MCP_RULES row + citation-grade `evidence`; an unknown stack yields an
    empty set (no invented tools). CLI-over-MCP bias: a github remote yields the gh CLI, never a
    GitHub MCP. When `existing` (a parsed .mcp.json) is given, its write-enabled servers are also
    scanned for lethal-trifecta risk."""
    recs, seen = [], set()

    def add(rule_id, evidence):
        if rule_id not in seen:
            recs.append(_rec(rule_id, evidence))
            seen.add(rule_id)

    remote = _git_remote(repo)
    if remote and "github.com" in remote:
        add("github", "git remote references github.com")

    deps, line_of = _pkg_deps(repo)

    def first(names):
        for n in names:
            if n in deps:
                return n
        return None

    def first_prefix(pfx):
        for d in deps:
            if d.startswith(pfx):
                return d
        return None

    m = first_prefix("@supabase/")
    if m:
        add("supabase", _dep_ev(line_of, m))
    m = first_prefix("@sentry/")
    if m:
        add("sentry", _dep_ev(line_of, m))
    m = first(("pg", "prisma", "@prisma/client"))
    if m:
        add("postgres", _dep_ev(line_of, m))
    else:
        dsn = _postgres_dsn(repo)
        if dsn:
            add("postgres", dsn)
    m = first(FASTMOVING)
    if m:
        add("context7", _dep_ev(line_of, m))

    for name in ("playwright.config.ts", "playwright.config.js", "playwright.config.mjs"):
        if os.path.isfile(os.path.join(repo, name)):
            add("playwright", "%s:1" % name)
            break

    warnings = [_trifecta_warn(r["id"], r["tool"]) for r in recs if r["trifecta"]]
    warnings += _existing_trifecta_warnings(existing)
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


# --------------------------------------------------------------------------- autoskills recommender
AUTOSKILLS_MARKERS = ("package.json", "pyproject.toml", "requirements.txt", "Gemfile",
                      "go.mod", "Cargo.toml", "composer.json", "pom.xml", "build.gradle")
AUTOSKILLS_CAUTION = ("autoskills installs multiple stack skills; overlapping skill descriptions "
                      "can degrade auto-triggering across your WHOLE skill set (onboarding Skills "
                      "stance). Review the --dry-run and prefer a focused subset before installing.")


def recommend_autoskills(repo):
    """`npx autoskills` applicability: any recognizable project manifest means it can match stack
    skills. Present-only — the gated --dry-run preview + the user-run install are the onboarding
    walk's job. Returns {applicable, evidence, command, caution}; unknown repo -> applicable False."""
    ev = None
    for marker in AUTOSKILLS_MARKERS:
        if os.path.isfile(os.path.join(repo, marker)):
            ev = marker
            break
    if ev is None:
        try:
            for f in sorted(os.listdir(repo)):
                # a real *.tf FILE (not a directory named foo.tf); evidence = the actual filename
                if f.endswith(".tf") and os.path.isfile(os.path.join(repo, f)):
                    ev = f
                    break
        except OSError:
            pass
    if ev is None:
        return {"applicable": False, "evidence": None, "command": None, "caution": None}
    return {"applicable": True, "evidence": ev,
            "command": "npx autoskills --dry-run", "caution": AUTOSKILLS_CAUTION}


# --------------------------------------------------------------------------- draft-taxonomy (D2)
# /v:onboard DRAFTS a first-cut impact-taxonomy from the repo's directory/module structure +
# detected stack (path_patterns from REAL dirs; the six content-pattern kinds — the four core
# surfaces always OFFERED per-repo, shared_token/a11y OFFERED only when a UI is detected; a starter
# sensitive_path_list; the single-sourced churn block). Present-then-confirm (recommend-mcp
# precedent): it emits a PROPOSAL and NEVER auto-writes the real
# `.claude/compound-v-impact-taxonomy.yaml`. Output is BLOCK-STYLE YAML only — the no-PyYAML stdlib
# fallback (_mini_yaml) silently drops inline flow `{}` mappings, so a flow-style draft would parse
# EMPTY without PyYAML. The emitted draft self-validates against compound-v-validate-taxonomy.py (B1).

_CHURN_EXCLUDES = ["**/*.min.js", "**/*.min.css", "**/dist/**", "**/build/**",
                   "**/vendor/**", "**/node_modules/**", "**/*.lock", "**/package-lock.json"]
_CHURN_FORMATS = [r"^chore\(fmt\)", r"^style:", r"^format:"]

# path_patterns drafted ONLY for surfaces that actually exist in the repo (glob, difficulty, impact).
_PATH_LOW_EXTS = [("css", "**/*.css"), ("scss", "**/*.scss"), ("sass", "**/*.sass"),
                  ("less", "**/*.less"), ("md", "**/*.md")]
_PATH_MED_EXTS = [("jsx", "**/*.jsx"), ("tsx", "**/*.tsx"), ("vue", "**/*.vue"),
                  ("svelte", "**/*.svelte")]
_PATH_HIGH_EXTS = [("sql", "**/*.sql"), ("tf", "**/*.tf")]
_PATH_HIGH_SEGS = [("auth", "**/auth/**"), ("payments", "**/payments/**"),
                   ("billing", "**/billing/**"), ("migrations", "**/migrations/**")]

# sensitive_path_list — always-on secret-file surfaces (so the required list is NEVER empty, even on
# a bare repo — fail-closed) unioned with evidence-driven high-blast surfaces.
_SENS_ALWAYS = ["**/*.pem", "**/*.key", "**/*.env"]
_SENS_SEGS = [("auth", "**/auth/**"), ("session", "**/session/**"),
              ("credentials", "**/credentials/**"), ("payments", "**/payments/**"),
              ("billing", "**/billing/**"), ("migrations", "**/migrations/**")]
_SENS_EXTS = [("sql", "**/*.sql"), ("tf", "**/*.tf")]

# content_patterns — the four CORE impact surfaces, always offered per-repo (content patterns only
# ever RAISE impact, so a starter set is safe; the human prunes at the GATE).
_CONTENT_CORE = [
    {"match": "terms of service", "pattern_type": "literal", "case": "insensitive",
     "scan": "content", "kind": "legal_copy", "impact_band": "high"},
    {"match": "privacy policy", "pattern_type": "literal", "case": "insensitive",
     "scan": "content", "kind": "legal_copy", "impact_band": "high"},
    {"match": "consent", "pattern_type": "literal", "case": "insensitive",
     "scan": "content", "kind": "legal_copy", "impact_band": "high"},
    {"match": r"\{\{[a-zA-Z0-9_]+\}\}", "pattern_type": "regex", "case": "sensitive",
     "scan": "content", "kind": "i18n_placeholder", "impact_band": "high"},
    {"match": "%[sd]", "pattern_type": "regex", "case": "sensitive",
     "scan": "content", "kind": "i18n_placeholder", "impact_band": "high"},
    {"match": "feature_flag", "pattern_type": "literal", "case": "insensitive",
     "scan": "content", "kind": "feature_flag", "impact_band": "high"},
    {"match": "isEnabled", "pattern_type": "literal", "case": "insensitive",
     "scan": "content", "kind": "feature_flag", "impact_band": "medium"},
    {"match": "timeout", "pattern_type": "literal", "case": "insensitive",
     "scan": "content", "kind": "config_literal", "impact_band": "medium"},
    {"match": "rate_limit", "pattern_type": "literal", "case": "insensitive",
     "scan": "content", "kind": "config_literal", "impact_band": "high"},
    {"match": "price", "pattern_type": "literal", "case": "insensitive",
     "scan": "content", "kind": "config_literal", "impact_band": "high"},
]
# content_patterns — shared_token + a11y are UI-conditional: a "cosmetic" color or aria construct is
# a high-impact surface, so they are OFFERED only when a UI is detected (else offered=False, with a
# reason the human can override at the GATE).
_CONTENT_UI = [
    {"match": "--color-", "pattern_type": "literal", "case": "insensitive",
     "scan": "content", "kind": "shared_token", "impact_band": "high"},
    {"match": "theme.tokens", "pattern_type": "literal", "case": "insensitive",
     "scan": "content", "kind": "shared_token", "impact_band": "high"},
    {"match": "aria-label", "pattern_type": "literal", "case": "insensitive",
     "scan": "content", "kind": "a11y", "impact_band": "high"},
    {"match": "alt=", "pattern_type": "literal", "case": "insensitive",
     "scan": "content", "kind": "a11y", "impact_band": "medium"},
]

_TAXONOMY_TARGET_REL = os.path.join(".claude", "compound-v-impact-taxonomy.yaml")
_CHURN_TARGET_REL = os.path.join("docs", "superpowers", "memory", "churn-cache.json")


def _load_sibling(filename):
    """Load a sibling script (hyphenated → importlib) by path. None if unavailable/broken."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
    if not os.path.isfile(path):
        return None
    try:
        spec = importlib.util.spec_from_file_location("cv_" + re.sub(r"\W", "_", filename), path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:  # noqa: BLE001 — a broken sibling degrades, never crashes onboarding
        return None


def _repo_files(repo):
    """Repo-relative file paths. Prefer git-tracked (ground truth); fall back to an os.walk that
    prunes VENDOR_DIRS so draft-taxonomy still works on a not-yet-committed tree."""
    tracked = _git_tracked(repo)
    if tracked:
        return tracked
    files = []
    for root, dirs, names in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in VENDOR_DIRS]
        for nm in names:
            rel = os.path.relpath(os.path.join(root, nm), repo)
            files.append(rel.replace(os.sep, "/"))
    return files


def _scan_index(files):
    exts, segs, basenames = set(), set(), set()
    for f in files:
        parts = f.split("/")
        basenames.add(parts[-1])
        for seg in parts[:-1]:
            segs.add(seg)
        if "." in parts[-1]:
            exts.add(parts[-1].rsplit(".", 1)[1].lower())
    return exts, segs, basenames


def _first_ext(files, ext):
    suf = "." + ext
    for f in files:
        if f.lower().endswith(suf):
            return f
    return None


def _first_seg(files, seg):
    for f in files:
        if seg in f.split("/")[:-1]:
            return f
    return None


def _draft_path_patterns(files, segs):
    rows = []

    def add(glob, dband, iband, evidence):
        rows.append({"glob": glob, "difficulty_band": dband,
                     "impact_band": iband, "evidence": evidence})

    for ext, glob in _PATH_LOW_EXTS:
        ev = _first_ext(files, ext)
        if ev:
            add(glob, "low", "low", ev)
    for ext, glob in _PATH_MED_EXTS:
        ev = _first_ext(files, ext)
        if ev:
            add(glob, "medium", "medium", ev)
    for ext, glob in _PATH_HIGH_EXTS:
        ev = _first_ext(files, ext)
        if ev:
            add(glob, "high", "high", ev)
    for seg, glob in _PATH_HIGH_SEGS:
        ev = _first_seg(files, seg)
        if ev:
            add(glob, "high", "high", ev)
    if ".github" in segs:
        add(".github/**", "high", "high", _first_seg(files, ".github"))
    return rows


def _draft_content_patterns(ui):
    rows = list(_CONTENT_CORE)
    reason_core = "core impact surface (offered per-repo)"
    kinds = [
        {"kind": "legal_copy", "offered": True, "reason": reason_core},
        {"kind": "i18n_placeholder", "offered": True, "reason": reason_core},
        {"kind": "feature_flag", "offered": True, "reason": reason_core},
        {"kind": "config_literal", "offered": True, "reason": reason_core},
    ]
    if ui:
        rows += _CONTENT_UI
        kinds += [
            {"kind": "shared_token", "offered": True,
             "reason": "UI detected — a shared design token is a cosmetic-looking high-impact surface"},
            {"kind": "a11y", "offered": True,
             "reason": "UI detected — accessibility constructs silently break WCAG"},
        ]
    else:
        kinds += [
            {"kind": "shared_token", "offered": False,
             "reason": "no UI detected — offer if this repo has a design-token system"},
            {"kind": "a11y", "offered": False,
             "reason": "no UI detected — offer if this repo renders user-facing markup"},
        ]
    return kinds, rows


def _draft_sensitive(files, segs, basenames):
    out = [{"glob": g, "evidence": "default (secret-file surface)"} for g in _SENS_ALWAYS]
    for seg, glob in _SENS_SEGS:
        ev = _first_seg(files, seg)
        if ev:
            out.append({"glob": glob, "evidence": ev})
    for ext, glob in _SENS_EXTS:
        ev = _first_ext(files, ext)
        if ev:
            out.append({"glob": glob, "evidence": ev})
    if ".github" in segs:
        out.append({"glob": ".github/**", "evidence": _first_seg(files, ".github")})
    if "Dockerfile" in basenames:
        ev = next((f for f in files if f.split("/")[-1] == "Dockerfile"), None)
        out.append({"glob": "**/Dockerfile", "evidence": ev})
    seen, dedup = set(), []
    for e in out:
        if e["glob"] not in seen:
            seen.add(e["glob"])
            dedup.append(e)
    return dedup


def _dq(s):
    """Double-quoted YAML scalar (for globs / literal matches — no backslashes)."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _sq(s):
    """Single-quoted YAML scalar (for regex — NO escape processing under PyYAML OR the _mini_yaml
    fallback, so the pattern is byte-identical either way; only a literal `'` needs doubling)."""
    return "'" + s.replace("'", "''") + "'"


def _render_match(row):
    return _sq(row["match"]) if row.get("pattern_type") == "regex" else _dq(row["match"])


def emit_taxonomy_yaml(path_patterns, content_rows, sensitive, churn_block):
    """Emit a BLOCK-STYLE taxonomy YAML (never inline flow `{}` — the _mini_yaml fallback drops
    flow maps). Optional empty sections are omitted; sensitive_path_list + churn are always present."""
    L = [
        "# Compound V — impact taxonomy (v2.9 Pre-Evaluation). DRAFTED by /v:onboard from this repo's",
        "# directory/module structure + detected stack; a FIRST CUT only. A human keeps/edits it at the",
        "# GATE and it is NEVER auto-applied. Schema authority: scripts/compound-v-taxonomy.py.",
        "# Bands: low | medium | high. Validate: python3 scripts/compound-v-validate-taxonomy.py <file>.",
        "# BLOCK-STYLE ONLY — never inline flow mappings: the no-PyYAML stdlib fallback drops them.",
        "#",
        "# The real project taxonomy lives at .claude/compound-v-impact-taxonomy.yaml (present-then-",
        "# confirm: /v:onboard proposes this text; WRITE writes it only after you approve at the GATE).",
        "",
        "version: 1",
    ]
    if path_patterns:
        L += ["", "path_patterns:"]
        for r in path_patterns:
            L.append("  - glob: " + _dq(r["glob"]))
            L.append("    difficulty_band: " + r["difficulty_band"])
            L.append("    impact_band: " + r["impact_band"])
    if content_rows:
        L += ["", "content_patterns:"]
        for r in content_rows:
            L.append("  - match: " + _render_match(r))
            L.append("    pattern_type: " + r["pattern_type"])
            L.append("    case: " + r["case"])
            L.append("    scan: " + r["scan"])
            L.append("    kind: " + r["kind"])
            L.append("    impact_band: " + r["impact_band"])
    L += ["", "sensitive_path_list:"]
    for e in sensitive:
        L.append("  - " + _dq(e["glob"]))
    L += ["", "churn:", "  exclude_paths:"]
    for g in churn_block["exclude_paths"]:
        L.append("    - " + _dq(g))
    L.append("  format_commit_patterns:")
    for rx in churn_block["format_commit_patterns"]:
        L.append("    - " + _sq(rx))
    return "\n".join(L) + "\n"


def _validate_taxonomy_text(text):
    """Self-validate the drafted taxonomy against B1 (compound-v-validate-taxonomy.py). Returns
    (valid|None, violations). None = validator unavailable (reported, never a silent pass)."""
    mod = _load_sibling("compound-v-validate-taxonomy.py")
    if mod is None:
        return None, ["validator unavailable (compound-v-validate-taxonomy.py)"]
    try:
        problems = mod.validate_text(text)
    except Exception as e:  # noqa: BLE001 — fail-closed: a validator crash is "not valid"
        return False, ["validator error: %s" % e]
    return (not problems), problems


def draft_taxonomy(repo):
    """Draft a first-cut impact-taxonomy PROPOSAL from the repo. Present-then-confirm: returns the
    proposal (incl. the block-style YAML + per-decision evidence + a self-validation verdict) and
    writes NOTHING. The real `.claude/compound-v-impact-taxonomy.yaml` is written only at WRITE,
    behind the human GATE (per skills/compound-v/onboarding.md)."""
    files = _repo_files(repo)
    _, segs, basenames = _scan_index(files)
    ui = detect_ui(repo)
    path_patterns = _draft_path_patterns(files, segs)
    content_kinds, content_rows = _draft_content_patterns(ui)
    sensitive = _draft_sensitive(files, segs, basenames)
    churn_block = {"exclude_paths": list(_CHURN_EXCLUDES),
                   "format_commit_patterns": list(_CHURN_FORMATS)}
    yaml_text = emit_taxonomy_yaml(path_patterns, content_rows, sensitive, churn_block)
    valid, violations = _validate_taxonomy_text(yaml_text)
    return {
        "target_path": _TAXONOMY_TARGET_REL,
        "written": False,          # present-then-confirm — NEVER auto-written
        "ui": ui,
        "path_patterns": path_patterns,
        "content_kinds": content_kinds,
        "sensitive_path_list": sensitive,
        "churn": churn_block,
        "taxonomy_yaml": yaml_text,
        "valid": valid,
        "violations": violations,
    }


def draft_churn_summary(repo, taxonomy_yaml):
    """Build the normalized churn cache IN MEMORY from the DRAFTED taxonomy (so the churn excludes
    are single-sourced from the same draft the human is reviewing), and return a PROPOSAL summary.
    Present-then-confirm: writes NOTHING — the real docs/superpowers/memory/churn-cache.json is
    written at WRITE via `compound-v-churn.py --out …` once the human confirms."""
    import shutil
    import tempfile
    churn = _load_sibling("compound-v-churn.py")
    if churn is None:
        return {"available": False, "reason": "churn module unavailable"}
    tmpd = tempfile.mkdtemp(prefix="cv-onboard-churn-")
    try:
        tax_path = os.path.join(tmpd, "impact-taxonomy.yaml")
        with open(tax_path, "w", encoding="utf-8") as fh:
            fh.write(taxonomy_yaml)
        cache = churn.build_churn_cache(repo=repo, taxonomy_path=tax_path)
    except Exception as e:  # noqa: BLE001 — churn is escalation-only; a build failure degrades
        return {"available": False, "reason": "churn build failed: %s" % e}
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)
    paths = cache.get("paths", {})
    hot = sorted(p for p, v in paths.items() if v.get("hot"))
    return {
        "available": True,
        "target_path": _CHURN_TARGET_REL,
        "written": False,          # present-then-confirm — NEVER auto-written
        "head_sha": cache.get("head_sha"),
        "formula_id": cache.get("formula_id"),
        "paths": len(paths),
        "hot": hot,
    }


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
        # (Codex-caught) evidence is citation-grade file:line
        check("recommend: evidence is citation-grade (package.json:<line>)",
              any(r["id"] == "supabase" and ":" in r["evidence"] for r in out["recommendations"]))
        # (Codex-caught) existing write-enabled .mcp.json server -> trifecta warning
        exwarn = recommend_mcp(d7, existing={"mcpServers": {
            "supabase": {"command": "npx", "args": ["-y", "@supabase/mcp-server-supabase"]}}})["warnings"]
        check("recommend: warns on EXISTING write-enabled supabase server",
              any(w["id"] == "existing:supabase" for w in exwarn))
        okwarn = recommend_mcp(d7, existing={"mcpServers": {
            "supabase": {"command": "npx", "args": ["-y", "@supabase/mcp-server-supabase", "--read-only"]}}})["warnings"]
        check("recommend: no existing-warning when the least-priv flag is present",
              not any(w["id"] == "existing:supabase" for w in okwarn))
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
        # (Codex-caught) Postgres DSN with no pg/prisma dep still recommends Postgres MCP
        d7c = tempfile.mkdtemp()
        try:
            with open(os.path.join(d7c, ".env"), "w") as fh:
                fh.write("DATABASE_URL=postgres://u:p@localhost:5432/app\n")
            dsn_recs = recommend_mcp(d7c)["recommendations"]
            check("recommend: Postgres DSN (no pg dep) -> postgres rec, .env evidence",
                  any(r["id"] == "postgres" and r["evidence"].startswith(".env") for r in dsn_recs))
        finally:
            shutil.rmtree(d7c, ignore_errors=True)
    finally:
        shutil.rmtree(d7, ignore_errors=True)

    # --- recommend-autoskills (v2.5.3) ---
    d8 = tempfile.mkdtemp()
    try:
        with open(os.path.join(d8, "package.json"), "w") as fh:
            fh.write("{}")
        r8 = recommend_autoskills(d8)
        check("autoskills: package.json -> applicable, evidence, --dry-run command",
              r8["applicable"] and r8["evidence"] == "package.json"
              and r8["command"] == "npx autoskills --dry-run" and bool(r8["caution"]))
        os.remove(os.path.join(d8, "package.json"))
        check("autoskills: empty repo -> not applicable",
              recommend_autoskills(d8)["applicable"] is False)
        with open(os.path.join(d8, "pyproject.toml"), "w") as fh:
            fh.write("[project]\n")
        check("autoskills: pyproject.toml -> applicable",
              recommend_autoskills(d8)["applicable"] is True)
    finally:
        shutil.rmtree(d8, ignore_errors=True)

    # (Codex-caught) top-level *.tf FILE -> applicable with the real filename as evidence;
    # a DIRECTORY named *.tf must NOT count as a manifest (no false positive).
    d8c = tempfile.mkdtemp()
    try:
        with open(os.path.join(d8c, "main.tf"), "w") as fh:
            fh.write("resource {}\n")
        rtf = recommend_autoskills(d8c)
        check("autoskills: top-level main.tf -> applicable, evidence is the filename",
              rtf["applicable"] and rtf["evidence"] == "main.tf")
        os.remove(os.path.join(d8c, "main.tf"))
        os.mkdir(os.path.join(d8c, "infra.tf"))
        check("autoskills: a directory named *.tf is not a manifest (no false positive)",
              recommend_autoskills(d8c)["applicable"] is False)
    finally:
        shutil.rmtree(d8c, ignore_errors=True)

    # --- draft-taxonomy (v2.9 Task D2) ---
    _SIX_KINDS = {"legal_copy", "i18n_placeholder", "feature_flag",
                  "config_literal", "shared_token", "a11y"}

    def _touch(base, rel, txt="x\n"):
        full = os.path.join(base, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as fh:
            fh.write(txt)

    d9 = tempfile.mkdtemp()
    try:
        # A fixture tree with mixed surfaces + a UI signal (tailwind.config.js → detect_ui True).
        for rel in ("src/ui/button.css", "src/auth/login.ts", "db/migrations/001.sql",
                    ".github/workflows/ci.yml", "components/App.tsx", "README.md",
                    "Dockerfile", "infra/main.tf"):
            _touch(d9, rel)
        _touch(d9, "tailwind.config.js", "module.exports={}\n")

        prop = draft_taxonomy(d9)
        check("draft-taxonomy: self-validates (B1) zero violations",
              prop["valid"] is True and prop["violations"] == [])
        check("draft-taxonomy: never auto-writes the real taxonomy",
              prop["written"] is False
              and not os.path.exists(os.path.join(d9, ".claude",
                                                  "compound-v-impact-taxonomy.yaml")))
        check("draft-taxonomy: target is .claude/compound-v-impact-taxonomy.yaml",
              prop["target_path"] == _TAXONOMY_TARGET_REL)

        vt = _load_sibling("compound-v-validate-taxonomy.py")
        vm = _load_sibling("compound-v-validate-manifest.py")
        check("draft-taxonomy: emitted YAML passes the B1 validator",
              vt is not None and vt.validate_text(prop["taxonomy_yaml"]) == [])
        # Must ALSO parse + validate under the NO-PyYAML _mini_yaml fallback (block-style guard):
        # a flow-`{}` draft would parse EMPTY here.
        parsed_fb = vm._mini_yaml(prop["taxonomy_yaml"])
        check("draft-taxonomy: valid under the no-PyYAML _mini_yaml fallback (block-style)",
              vt.validate(parsed_fb) == [])
        check("draft-taxonomy: fallback recovers path_patterns (flow-map guard)",
              isinstance(parsed_fb.get("path_patterns"), list)
              and len(parsed_fb["path_patterns"]) >= 1)
        check("draft-taxonomy: fallback recovers content_patterns",
              isinstance(parsed_fb.get("content_patterns"), list)
              and len(parsed_fb["content_patterns"]) >= 1)
        check("draft-taxonomy: fallback recovers churn block",
              isinstance(parsed_fb.get("churn"), dict)
              and isinstance(parsed_fb["churn"].get("format_commit_patterns"), list))

        globs = [r["glob"] for r in prop["path_patterns"]]
        check("draft-taxonomy: css low-surface from a real dir", "**/*.css" in globs)
        check("draft-taxonomy: tsx medium surface", "**/*.tsx" in globs)
        check("draft-taxonomy: migrations high surface", "**/migrations/**" in globs)
        check("draft-taxonomy: auth high surface", "**/auth/**" in globs)
        check("draft-taxonomy: .github high surface", ".github/**" in globs)
        check("draft-taxonomy: sql/tf high surfaces",
              "**/*.sql" in globs and "**/*.tf" in globs)
        check("draft-taxonomy: every path row carries evidence",
              all(r.get("evidence") for r in prop["path_patterns"]))

        sens = [e["glob"] for e in prop["sensitive_path_list"]]
        check("draft-taxonomy: sensitive list carries secret defaults (fail-closed non-empty)",
              "**/*.pem" in sens and "**/*.key" in sens)
        check("draft-taxonomy: Dockerfile sensitive from evidence", "**/Dockerfile" in sens)
        check("draft-taxonomy: sql sensitive surface", "**/*.sql" in sens)

        kinds = {k["kind"]: k["offered"] for k in prop["content_kinds"]}
        check("draft-taxonomy: all six content kinds enumerated", set(kinds) == _SIX_KINDS)
        check("draft-taxonomy: four core kinds offered",
              all(kinds[k] for k in ("legal_copy", "i18n_placeholder",
                                     "feature_flag", "config_literal")))
        check("draft-taxonomy: shared_token/a11y offered when UI present",
              prop["ui"] is True and kinds["shared_token"] and kinds["a11y"])
        drafted_kinds = {r["kind"] for r in parsed_fb.get("content_patterns", [])}
        check("draft-taxonomy: UI repo draft includes shared_token + a11y rows",
              "shared_token" in drafted_kinds and "a11y" in drafted_kinds)
    finally:
        shutil.rmtree(d9, ignore_errors=True)

    # Non-UI repo: still valid; shared_token/a11y NOT auto-offered.
    d9b = tempfile.mkdtemp()
    try:
        _touch(d9b, "main.py", "print(1)\n")
        prop_b = draft_taxonomy(d9b)
        check("draft-taxonomy: non-UI repo draft still valid (B1)", prop_b["valid"] is True)
        kb = {k["kind"]: k["offered"] for k in prop_b["content_kinds"]}
        check("draft-taxonomy: shared_token/a11y NOT auto-offered without UI",
              prop_b["ui"] is False and kb["shared_token"] is False and kb["a11y"] is False)
        b_kinds = {r["kind"] for r in (_load_sibling("compound-v-validate-manifest.py")
                                       ._mini_yaml(prop_b["taxonomy_yaml"])
                                       .get("content_patterns", []))}
        check("draft-taxonomy: non-UI draft omits shared_token/a11y rows",
              "shared_token" not in b_kinds and "a11y" not in b_kinds)
        check("draft-taxonomy: bare-repo sensitive list still non-empty (fail-closed)",
              len(prop_b["sensitive_path_list"]) >= 1)
    finally:
        shutil.rmtree(d9b, ignore_errors=True)

    # Churn wiring (git-gated): builds a PROPOSAL summary, writes nothing.
    d9c = tempfile.mkdtemp()
    try:
        _env = dict(os.environ)
        _env.update({"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@e.com",
                     "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@e.com",
                     "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull})

        def _g(*a):
            _sp.run(["git", "-C", d9c] + list(a), env=_env, check=True,
                    stdin=_sp.DEVNULL, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
        try:
            _g("init", "-q", "-b", "main")
            _touch(d9c, "src/app.py", "print('a')\n")
            _g("add", "-A")
            _g("commit", "-q", "-m", "feat: app")
            prop_c = draft_taxonomy(d9c)
            summary = draft_churn_summary(d9c, prop_c["taxonomy_yaml"])
            check("draft-taxonomy: churn summary built and NOT written",
                  summary.get("available") is True and summary.get("written") is False
                  and not os.path.exists(os.path.join(d9c, "docs", "superpowers",
                                                      "memory", "churn-cache.json")))
            check("draft-taxonomy: churn summary reports formula_id + head_sha",
                  summary.get("formula_id") and summary.get("head_sha"))
        except (_sp.CalledProcessError, OSError):
            check("draft-taxonomy: churn wiring (skipped — git unavailable)", True)
    finally:
        shutil.rmtree(d9c, ignore_errors=True)

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
    sp = sub.add_parser("recommend-autoskills")
    sp.add_argument("--repo", default=".")
    sp.add_argument("--json", action="store_true")
    sp = sub.add_parser("draft-taxonomy")
    sp.add_argument("--repo", default=".")
    sp.add_argument("--with-churn", action="store_true",
                    help="also build a churn-cache PROPOSAL from the drafted taxonomy (not written)")
    sp.add_argument("--emit-yaml", action="store_true",
                    help="print ONLY the block-style taxonomy YAML (for the WRITE step to redirect)")
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
        existing = None
        if args.mcp_config and os.path.isfile(args.mcp_config):
            try:
                with open(args.mcp_config) as fh:
                    existing = json.load(fh)
            except (OSError, ValueError):
                existing = None
        out = recommend_mcp(repo, existing)
        out["mcp_json"] = mcp_json_config(out["recommendations"], existing)
        print(json.dumps(out, indent=2))
        return 0
    if args.cmd == "recommend-autoskills":
        print(json.dumps(recommend_autoskills(os.path.abspath(args.repo)), indent=2))
        return 0
    if args.cmd == "draft-taxonomy":
        repo = os.path.abspath(args.repo)
        proposal = draft_taxonomy(repo)
        if args.with_churn:
            proposal["churn_cache"] = draft_churn_summary(repo, proposal["taxonomy_yaml"])
        if args.emit_yaml:
            sys.stdout.write(proposal["taxonomy_yaml"])
            return 0 if proposal.get("valid") else 2
        print(json.dumps(proposal, indent=2))
        return 0 if proposal.get("valid") else 2
    build_parser().print_help(); return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
