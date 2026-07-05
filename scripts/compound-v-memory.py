#!/usr/bin/env python3
"""
Compound V — V-memory engine (PRD docs/superpowers/specs/2026-06-27-v-memory-prd.md, v2.0).

A local-first RECALL layer over docs/superpowers/** prose. It EXTENDS the two-half memory
(task-outcomes.jsonl / scorecard + human-curated routing-lessons.md); it never rewrites them.

Two lanes:
  - CORE  : SQLite FTS5 BM25 over GIT-TRACKED prose. Pure stdlib, offline, always on.
  - DENSE : multilingual-e5-small embeddings via an ISOLATED onnxruntime venv that lives
            OUTSIDE the repo (~/.cache/compound-v/memory/<repo-id>/). Opt-in, scale-gated,
            degrade-safe: absent/broken venv ⇒ silently FTS5-only.

Hard invariants (see PRD §3): cache outside repo (no .gitignore edit — the scope gate uses
`git ls-files --others --exclude-standard`, which an ignore under docs/superpowers/ would
blind); index only git-tracked files; fts5_escape + try/except on every MATCH (raw
MATCH 'index.ts' throws on stock sqlite); fcntl.flock loser-noop + BEGIN IMMEDIATE reindex;
hooks NEVER bootstrap; embeddings identity-checked (model+dim+lib+fingerprint) & degrade-safe;
recall stays subordinate to routing-lessons.md + scorecard; no fabricated metrics.

The recall->action bridge (`recall-check`) is deterministic + conservative-only: a STRUCTURED
recurring-failure match (job_result status/blocked + files_changed/violations on the same file
pattern, N>=k) -> auto-TIGHTEN (force worktree / extra review pass / fold into Task 0). It
NEVER reroutes to a lower-trust backend and never loosens. Embedding similarity stays advisory.

Python 3.9-safe; the CORE imports stdlib only. numpy/onnxruntime live only inside the venv,
reached via subprocess. Exit 0 on success; 1 on usage/runtime error; --selftest exits 0/1.
"""

import argparse
import fcntl
import fnmatch
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time

CHUNKER_VERSION = "2"
DEFAULT_MODEL = "intfloat/multilingual-e5-small"
DEFAULT_DIM = 384
QUICK_MAX_CHANGED = 20          # --quick skips a refresh larger than this
SCALE_GATE_MIN_CHUNKS = int(os.environ.get("COMPOUND_V_SCALE_GATE", "80"))  # dense dormant below this
RECALL_K = 2                    # "two is a pattern" — matches the scorecard's MIN-pattern rule
MAX_CHUNK_CHARS = 1800          # ~450 tokens — stays within the e5 512-token window (quality + no onnx crash)
CHUNK_OVERLAP_CHARS = 200

# A whole PEM private-key block (begin line + body + end line), matched across newlines.
PEM_RE = re.compile(r"-----BEGIN[ A-Z]*KEY-----.*?-----END[ A-Z]*KEY-----", re.DOTALL)
# Single-token secret families. sk- allows interior '-'/'_' (e.g. sk-proj-…) so a hyphen
# before 8 alnum no longer slips through.
SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9][A-Za-z0-9_-]{12,}"
    r"|ghp_[A-Za-z0-9]{20,}"
    r"|gho_[A-Za-z0-9]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|AKIA[0-9A-Z]{12,}"
    r"|xox[baprs]-[A-Za-z0-9-]{10,})"
)

DOCS_REL = os.path.join("docs", "superpowers")


# --------------------------------------------------------------------------- #
# paths / repo identity
# --------------------------------------------------------------------------- #
def find_repo_root(start: str) -> str:
    """git toplevel of `start`, else `start` itself (non-git fallback)."""
    try:
        out = subprocess.run(
            ["git", "-C", start, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            return os.path.realpath(out.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return os.path.realpath(start)


def repo_id(root: str) -> str:
    return hashlib.sha1(os.path.realpath(root).encode("utf-8")).hexdigest()[:12]


def cache_dir(root: str) -> str:
    """Disposable cache OUTSIDE the repo. Override with COMPOUND_V_MEMORY_HOME (used by tests)."""
    base = os.environ.get("COMPOUND_V_MEMORY_HOME")
    if not base:
        xdg = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
        base = os.path.join(xdg, "compound-v", "memory")
    return os.path.join(base, repo_id(root))


def cache_paths(root: str):
    d = cache_dir(root)
    return {
        "dir": d,
        "db": os.path.join(d, "index.sqlite"),
        "lock": os.path.join(d, "lock"),
        "venv": os.path.join(d, "venv"),
        "venv_py": os.path.join(d, "venv", "bin", "python"),
        "embedder": os.path.join(d, "embedder.py"),
        "model_cache": os.path.join(d, "model"),
    }


def config_wants_embeddings(root: str) -> bool:
    """The project's DENSE-lane opt-in from `.claude/compound-v.json` (`memory.embeddings`),
    set by /v:init. Missing/unreadable ⇒ False (FTS5-only). This makes the init choice take
    effect everywhere — including the background hook — WITHOUT ever installing: actual
    embedding is still gated by is_bootstrapped(), and bootstrap is the only network step."""
    path = os.path.join(root, ".claude", "compound-v.json")
    try:
        with open(path) as fh:
            cfg = json.load(fh)
        return bool(cfg.get("memory", {}).get("embeddings", False))
    except (OSError, ValueError, AttributeError, TypeError):
        return False


# --------------------------------------------------------------------------- #
# redaction + content helpers
# --------------------------------------------------------------------------- #
def redact(text: str) -> str:
    text = PEM_RE.sub("[REDACTED KEY BLOCK]", text)   # whole key block, not just the BEGIN line
    return SECRET_RE.sub("[REDACTED]", text)


ONBOARD_ROOT_DOC_TYPES = {
    "AGENTS.md": "agents", "CLAUDE.md": "claude",
    "CONVENTIONS.md": "conventions", "DESIGN.md": "design",
}


def doc_type_for(relpath: str) -> str:
    parts = relpath.replace("\\", "/").split("/")
    # relpath is repo-relative; strip the docs/superpowers/ prefix if present
    if len(parts) >= 3 and parts[0] == "docs" and parts[1] == "superpowers":
        return parts[2] if len(parts) > 3 else "root"
    if len(parts) == 1 and parts[0] in ONBOARD_ROOT_DOC_TYPES:
        return ONBOARD_ROOT_DOC_TYPES[parts[0]]
    return parts[0] if parts else "root"


_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def date_for(relpath: str) -> str:
    m = _DATE_RE.search(relpath)
    return m.group(1) if m else ""


# --------------------------------------------------------------------------- #
# chunking
# --------------------------------------------------------------------------- #
def _split_long(text: str):
    text = text.strip()
    if len(text) <= MAX_CHUNK_CHARS:
        return [text] if text else []
    out = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + MAX_CHUNK_CHARS, n)
        out.append(text[start:end].strip())
        if end >= n:
            break
        start = end - CHUNK_OVERLAP_CHARS
    return [c for c in out if c]


def chunk_markdown(text: str):
    """Split by markdown headings; each (heading, body) becomes one chunk (sub-split if long)."""
    lines = text.splitlines()
    sections = []
    cur_heading = ""
    cur_body = []
    heading_re = re.compile(r"^#{1,6}\s+(.*)$")
    for ln in lines:
        m = heading_re.match(ln)
        if m:
            if cur_heading or "".join(cur_body).strip():
                sections.append((cur_heading, "\n".join(cur_body)))
            cur_heading = m.group(1).strip()
            cur_body = [ln]
        else:
            cur_body.append(ln)
    if cur_heading or "".join(cur_body).strip():
        sections.append((cur_heading, "\n".join(cur_body)))
    chunks = []
    for heading, body in sections:
        for piece in _split_long(body):
            chunks.append((heading, piece))
    return chunks


def chunk_jsonl(text: str):
    chunks = []
    for ln in text.splitlines():
        ln = ln.strip()
        if ln:
            chunks.append(("", ln))
    return chunks


def chunk_file(abspath: str, relpath: str):
    try:
        with open(abspath, "r", encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
    except OSError:
        return []
    raw = redact(raw)
    if relpath.endswith(".jsonl"):
        pairs = chunk_jsonl(raw)
    else:
        pairs = chunk_markdown(raw)
    dt = doc_type_for(relpath)
    dat = date_for(relpath)
    out = []
    for i, (heading, body) in enumerate(pairs):
        out.append({
            "chunk_index": i, "heading": heading, "text": body,
            "doc_type": dt, "date": dat,
        })
    return out


# --------------------------------------------------------------------------- #
# git-tracked file discovery
# --------------------------------------------------------------------------- #
def _in_git_worktree(root: str) -> bool:
    try:
        out = subprocess.run(
            ["git", "-C", root, "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, timeout=10,
        )
        return out.returncode == 0 and out.stdout.strip() == "true"
    except (OSError, subprocess.SubprocessError):
        return False


def tracked_files(root: str):
    """Repo-relative *.md/*.jsonl under docs/superpowers, GIT-TRACKED only.

    Inside a git worktree this trusts ONLY `git ls-files` (so .gitignore + the scope
    discipline are inherited) and FAILS CLOSED — a transient git error returns [] rather
    than over-indexing untracked/ignored prose. The filesystem walk is used ONLY for a
    non-git root (self-tests / demos).
    """
    docs_abs = os.path.join(root, DOCS_REL)
    if _in_git_worktree(root):
        try:
            out = subprocess.run(
                ["git", "-C", root, "ls-files", "-z", "--", DOCS_REL],
                capture_output=True, timeout=30,
            )
            if out.returncode == 0:
                rels = [p for p in out.stdout.decode("utf-8", "replace").split("\0") if p]
                roots = subprocess.run(
                    ["git", "-C", root, "ls-files", "-z", "--",
                     "AGENTS.md", "CLAUDE.md", "CONVENTIONS.md", "DESIGN.md"],
                    capture_output=True, timeout=30,
                )
                if roots.returncode == 0:
                    rels += [p for p in roots.stdout.decode("utf-8", "replace").split("\0") if p]
                return sorted(r for r in rels if r.endswith(".md") or r.endswith(".jsonl"))
        except (OSError, subprocess.SubprocessError):
            pass
        return []  # fail closed: inside git but ls-files failed — index nothing, never untracked
    # non-git root only: filesystem walk
    rels = []
    for dirpath, _dirs, files in os.walk(docs_abs):
        for f in files:
            if f.endswith(".md") or f.endswith(".jsonl"):
                rels.append(os.path.relpath(os.path.join(dirpath, f), root))
    return sorted(rels)


def file_sha(abspath: str) -> str:
    h = hashlib.sha256()
    try:
        with open(abspath, "rb") as fh:
            for blk in iter(lambda: fh.read(65536), b""):
                h.update(blk)
    except OSError:
        return ""
    return h.hexdigest()


# --------------------------------------------------------------------------- #
# sqlite schema / open
# --------------------------------------------------------------------------- #
_SCHEMA = """
CREATE TABLE IF NOT EXISTS indexed_files (
  path TEXT PRIMARY KEY, content_hash TEXT NOT NULL, indexed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
  id INTEGER PRIMARY KEY,
  path TEXT NOT NULL, chunk_index INTEGER NOT NULL, heading TEXT,
  text TEXT NOT NULL, doc_type TEXT, date TEXT, embedding BLOB
);
CREATE INDEX IF NOT EXISTS chunks_path ON chunks(path);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  text, content='chunks', content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
  INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES('delete', old.id, old.text);
END;
CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES('delete', old.id, old.text);
  INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS query_cache (
  qhash TEXT NOT NULL, model TEXT NOT NULL, vec TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY (qhash, model)
);
"""


def open_db(path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    conn.executescript(_SCHEMA)
    return conn


def meta_get(conn, key, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def meta_set(conn, key, value):
    conn.execute("INSERT INTO meta(key,value) VALUES(?,?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


# --------------------------------------------------------------------------- #
# FTS5 query escaping (crash-safety — raw MATCH 'index.ts' throws)
# --------------------------------------------------------------------------- #
def fts5_escape(q: str):
    """Tokenize on word chars, double-quote each term, OR-join. None if no usable token."""
    toks = re.findall(r"\w+", q, re.UNICODE)
    if not toks:
        return None
    return " OR ".join('"%s"' % t for t in toks)


# --------------------------------------------------------------------------- #
# embeddings (DENSE lane) — runs inside the out-of-repo venv via subprocess
# --------------------------------------------------------------------------- #
EMBEDDER_SRC = r'''#!/usr/bin/env python3
# Auto-written by compound-v-memory.py bootstrap. Runs INSIDE the isolated venv.
# Default lane = DIRECT onnxruntime over the Xenova ONNX export (light: onnxruntime +
# tokenizers + huggingface_hub + numpy, NO torch). gte/quality tier = sentence-transformers.
import json, sys, argparse
import numpy as np

ONNX_REPO = {
    "intfloat/multilingual-e5-small": "Xenova/multilingual-e5-small",
    "intfloat/multilingual-e5-base": "Xenova/multilingual-e5-base",
}

def _is_onnx_model(model):
    return ("e5" in model) or model.startswith("Xenova/")

class E5Onnx:
    def __init__(self, model):
        from huggingface_hub import hf_hub_download
        import onnxruntime as ort
        from tokenizers import Tokenizer
        repo = ONNX_REPO.get(model, model if model.startswith("Xenova/")
                             else "Xenova/multilingual-e5-small")
        self.tok = Tokenizer.from_file(hf_hub_download(repo, "tokenizer.json"))
        self.tok.enable_truncation(max_length=512)   # e5 context window; long chunks would else crash onnx
        self.sess = ort.InferenceSession(hf_hub_download(repo, "onnx/model.onnx"),
                                         providers=["CPUExecutionProvider"])
        self.in_names = [i.name for i in self.sess.get_inputs()]
    def embed(self, texts, kind):
        pref = "query: " if kind == "query" else "passage: "
        texts = [pref + t for t in texts]
        encs = [self.tok.encode(t) for t in texts]
        maxlen = max((len(e.ids) for e in encs), default=1)
        ids = np.zeros((len(encs), maxlen), dtype=np.int64)
        mask = np.zeros((len(encs), maxlen), dtype=np.int64)
        for i, e in enumerate(encs):
            ids[i, :len(e.ids)] = e.ids
            mask[i, :len(e.attention_mask)] = e.attention_mask
        feed = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self.in_names:
            feed["token_type_ids"] = np.zeros_like(ids)
        out = self.sess.run(None, feed)[0]            # last_hidden_state [B,T,H]
        m = mask[:, :, None].astype("float32")        # mean-pool over tokens
        pooled = (out * m).sum(1) / np.clip(m.sum(1), 1e-9, None)
        return [list(map(float, v)) for v in pooled]

class STModel:
    def __init__(self, model):
        from sentence_transformers import SentenceTransformer
        kw = {"trust_remote_code": True} if "gte" in model else {}
        self.m = SentenceTransformer(model, **kw)
    def embed(self, texts, kind):
        return [list(map(float, v)) for v in self.m.encode(texts)]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--kind", default="passage")
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", dest="out", required=True)
    a = ap.parse_args()
    with open(a.inp) as fh:
        texts = json.load(fh)
    model = E5Onnx(a.model) if _is_onnx_model(a.model) else STModel(a.model)
    vecs = model.embed(texts, a.kind) if texts else []
    with open(a.out, "w") as fh:
        json.dump({"dim": len(vecs[0]) if vecs else 0, "vecs": vecs}, fh)

if __name__ == "__main__":
    main()
'''


def is_bootstrapped(paths) -> bool:
    return os.path.exists(paths["venv_py"]) and os.path.exists(paths["embedder"])


def ensure_embedder(paths) -> None:
    """Keep the deployed embedder.py in sync with EMBEDDER_SRC, so an embedder code change
    (e.g. a tokenizer-truncation fix) deploys on the next refresh without a re-bootstrap."""
    try:
        cur = open(paths["embedder"]).read() if os.path.exists(paths["embedder"]) else ""
    except OSError:
        cur = ""
    if cur != EMBEDDER_SRC:
        os.makedirs(os.path.dirname(paths["embedder"]), exist_ok=True)
        with open(paths["embedder"], "w") as fh:
            fh.write(EMBEDDER_SRC)


def embed_texts(paths, model, kind, texts, allow_download=False):
    """Return list[list[float]] or None (degrade) — runs the venv embedder via subprocess.

    `allow_download` is False for all normal refresh/search paths: the embedder is forced
    OFFLINE (HF_HUB_OFFLINE=1), so a missing model degrades to FTS5-only instead of fetching
    over the network. Only `bootstrap` passes allow_download=True (the one network step)."""
    if not texts or not is_bootstrapped(paths):
        return None
    try:
        with tempfile.TemporaryDirectory() as td:
            inp = os.path.join(td, "in.json")
            out = os.path.join(td, "out.json")
            with open(inp, "w") as fh:
                json.dump(texts, fh)
            env = dict(os.environ)
            env["HF_HOME"] = paths["model_cache"]
            env["TOKENIZERS_PARALLELISM"] = "false"
            env["HF_HUB_OFFLINE"] = "0" if allow_download else "1"
            env["TRANSFORMERS_OFFLINE"] = "0" if allow_download else "1"
            r = subprocess.run(
                [paths["venv_py"], paths["embedder"], "--model", model,
                 "--kind", kind, "--in", inp, "--out", out],
                capture_output=True, text=True, timeout=300, env=env,
            )
            if r.returncode != 0 or not os.path.exists(out):
                return None
            with open(out) as fh:
                data = json.load(fh)
            return data.get("vecs") or None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _fingerprint(vec) -> str:
    return hashlib.sha256(",".join("%.4f" % x for x in vec).encode()).hexdigest()[:16]


def _embedder_src_hash() -> str:
    return hashlib.sha256(EMBEDDER_SRC.encode()).hexdigest()[:16]


def identity_matches(conn, model) -> bool:
    """The PRD identity tuple {embed_model, dim, chunker_version, embedder code}. A mismatch
    means stored vectors are stale — dense must NOT compare them to new query vectors."""
    return (meta_get(conn, "embed_model") == model
            and meta_get(conn, "chunker_version") == CHUNKER_VERSION
            and meta_get(conn, "embedder_src") == _embedder_src_hash())


def cosine(a, b) -> float:
    if len(a) != len(b):          # dimension guard — stale-identity vectors never half-match
        return 0.0
    s = da = db = 0.0
    for x, y in zip(a, b):
        s += x * y
        da += x * x
        db += y * y
    if da <= 0 or db <= 0:
        return 0.0
    return s / ((da ** 0.5) * (db ** 0.5))


def dense_active(conn, paths, model) -> bool:
    """Dense lane engages only when bootstrapped, the FULL embed identity matches (model +
    dim + chunker + embedder code), and the corpus clears the scale gate. Else FTS5-only —
    so a model/chunker/embedder change can never silently compare stale vectors."""
    if not is_bootstrapped(paths) or not identity_matches(conn, model):
        return False
    n = conn.execute("SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL").fetchone()[0]
    return n >= SCALE_GATE_MIN_CHUNKS


# --------------------------------------------------------------------------- #
# locking
# --------------------------------------------------------------------------- #
def acquire_lock(lock_path):
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return fd


def release_lock(fd):
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


# --------------------------------------------------------------------------- #
# refresh / indexing
# --------------------------------------------------------------------------- #
def _persist_chunks(conn, root, rel, chunks, vecs):
    """Atomically replace one file's chunks (+ optional embeddings) and update indexed_files;
    triggers the sync FTS. A None/short `vecs` (or a None element) degrades that chunk to a NULL
    embedding — never crashes. Returns the chunk count."""
    abspath = os.path.join(root, rel)
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM chunks WHERE path=?", (rel,))
        for i, c in enumerate(chunks):
            blob = None
            if vecs is not None and i < len(vecs) and vecs[i] is not None:
                blob = json.dumps(vecs[i]).encode("utf-8")
            conn.execute(
                "INSERT INTO chunks(path,chunk_index,heading,text,doc_type,date,embedding) "
                "VALUES(?,?,?,?,?,?,?)",
                (rel, c["chunk_index"], c["heading"], c["text"], c["doc_type"], c["date"], blob),
            )
        conn.execute(
            "INSERT INTO indexed_files(path,content_hash,indexed_at) VALUES(?,?,?) "
            "ON CONFLICT(path) DO UPDATE SET content_hash=excluded.content_hash, "
            "indexed_at=excluded.indexed_at",
            (rel, file_sha(abspath), _now()),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return len(chunks)


def reindex_file(conn, root, rel, embedder):
    """Per-file (re)index: chunk -> optional per-file embed -> persist. Used when embeddings are
    OFF (FTS5-only) and as a fallback. When many files are embedded at once, cmd_refresh uses
    reindex_batch so the isolated-venv embedder loads the model ONCE, not once per file."""
    abspath = os.path.join(root, rel)
    chunks = chunk_file(abspath, rel)
    vecs = None
    if embedder is not None and chunks:
        vecs = embedder([c["text"] for c in chunks])
    return _persist_chunks(conn, root, rel, chunks, vecs)


def reindex_batch(conn, root, rels, embedder):
    """Re-index many files, embedding ALL their chunks in a SINGLE embedder call — so the isolated
    venv embedder loads the ONNX model ONCE per refresh instead of once per file. Chunks are
    flattened in order, embedded together, then the vectors are sliced back per file. Degrade-safe:
    a None result (embed failed) persists every file with NULL embeddings (FTS5-only). Returns the
    number of files processed."""
    per_file = [(rel, chunk_file(os.path.join(root, rel), rel)) for rel in rels]
    flat = [c["text"] for _, chunks in per_file for c in chunks]
    all_vecs = embedder(flat) if (embedder is not None and flat) else None
    offset = 0
    for rel, chunks in per_file:
        n = len(chunks)
        vecs = all_vecs[offset:offset + n] if all_vecs is not None else None
        offset += n
        _persist_chunks(conn, root, rel, chunks, vecs)
    return len(per_file)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def cmd_refresh(args) -> int:
    root = find_repo_root(args.repo or os.getcwd())
    paths = cache_paths(root)
    lock = acquire_lock(paths["lock"])
    if lock is None:
        print("V-memory: refresh already running — skipped.")
        return 0
    try:
        conn = open_db(paths["db"])
        if args.rebuild:
            conn.executescript(
                "DROP TABLE IF EXISTS chunks_fts; DROP TABLE IF EXISTS chunks; "
                "DROP TABLE IF EXISTS indexed_files;"
            )
            conn.executescript(_SCHEMA)

        files = tracked_files(root)
        present = set(files)
        known = {r[0]: r[1] for r in conn.execute("SELECT path,content_hash FROM indexed_files")}

        changed = [f for f in files if file_sha(os.path.join(root, f)) != known.get(f)]
        removed = [p for p in known if p not in present]

        if args.quick and len(changed) > QUICK_MAX_CHANGED:
            print("V-memory: %d changed files exceed --quick limit (%d); run a full refresh."
                  % (len(changed), QUICK_MAX_CHANGED))
            return 0

        # embeddings: enabled by --with-embeddings OR the project's .claude/compound-v.json
        # opt-in (memory.embeddings, set by /v:init), AND only when ALREADY bootstrapped —
        # a hook/refresh NEVER installs (bootstrap is the one network step).
        embedder = None
        model = meta_get(conn, "embed_model", DEFAULT_MODEL)
        want_embed = args.with_embeddings or config_wants_embeddings(root)
        if want_embed and is_bootstrapped(paths):
            ensure_embedder(paths)  # redeploy embedder.py from EMBEDDER_SRC (sync code changes)
            embedder = lambda texts: embed_texts(paths, model, "passage", texts)  # noqa: E731

        # Which files to (re)index? Content-changed always. When embedding, ALSO re-embed
        # files that have missing vectors, and re-embed everything on an identity drift
        # (model/chunker/embedder changed) — so `bootstrap` then `refresh --with-embeddings`
        # actually populates vectors even when the FTS index already exists.
        to_index = list(changed)
        if embedder is not None:
            if not identity_matches(conn, model):
                to_index = list(files)  # identity drift ⇒ re-embed the whole corpus
            else:
                missing = {r[0] for r in conn.execute(
                    "SELECT DISTINCT path FROM chunks WHERE embedding IS NULL")}
                for f in files:
                    if f in missing and f not in to_index:
                        to_index.append(f)

        # Embed ALL files' chunks in ONE embedder call (one model load per refresh); the per-file
        # path stays for the FTS5-only case (embedder is None).
        if embedder is not None:
            n_idx = reindex_batch(conn, root, to_index, embedder)
        else:
            n_idx = 0
            for f in to_index:
                n_idx += 1
                reindex_file(conn, root, f, embedder)
        for p in removed:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM chunks WHERE path=?", (p,))
            conn.execute("DELETE FROM indexed_files WHERE path=?", (p,))
            conn.execute("COMMIT")

        meta_set(conn, "chunker_version", CHUNKER_VERSION)
        if embedder is not None:  # record the embed identity so a later drift forces a rebuild
            meta_set(conn, "embed_model", model)
            meta_set(conn, "embedder_src", _embedder_src_hash())
        conn.commit()
        total = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        nvec = conn.execute("SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL").fetchone()[0]
        print("V-memory: indexed/updated %d, removed %d, unchanged %d, %d chunks total%s"
              % (n_idx, len(removed), len(files) - n_idx, total,
                 (" (%d with vectors)" % nvec) if embedder else " (FTS5-only)"))
        return 0
    finally:
        release_lock(lock)


# --------------------------------------------------------------------------- #
# search
# --------------------------------------------------------------------------- #
def bm25_search(conn, q, limit):
    m = fts5_escape(q)
    if not m:
        return []
    try:
        rows = conn.execute(
            "SELECT c.id,c.path,c.heading,c.text,c.doc_type,c.date,bm25(chunks_fts) "
            "FROM chunks_fts JOIN chunks c ON c.id=chunks_fts.rowid "
            "WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts) LIMIT ?",
            (m, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [dict(id=r[0], path=r[1], heading=r[2], text=r[3], doc_type=r[4], date=r[5]) for r in rows]


QUERY_CACHE_MAX = 500


def _query_vec(conn, paths, model, q, embed=None):
    """The query embedding, with a small SQLite cache. A repeated query skips the isolated-venv
    embedder subprocess entirely — otherwise EVERY dense search pays one ONNX model load
    (seconds). Keyed by (sha256(query), model), so a model change naturally misses; bounded to
    QUERY_CACHE_MAX most-recent rows. Degrade-safe: any cache problem falls back to embedding."""
    qh = hashlib.sha256(q.encode("utf-8")).hexdigest()
    try:
        row = conn.execute("SELECT vec FROM query_cache WHERE qhash=? AND model=?",
                           (qh, model)).fetchone()
        if row:
            return json.loads(row[0])
    except (sqlite3.Error, ValueError, TypeError):
        pass
    embed = embed or (lambda texts: embed_texts(paths, model, "query", texts))
    vecs = embed([q])
    if not vecs:
        return None
    try:
        conn.execute("INSERT OR REPLACE INTO query_cache(qhash,model,vec,created_at) "
                     "VALUES(?,?,?,?)", (qh, model, json.dumps(vecs[0]), _now()))
        conn.execute("DELETE FROM query_cache WHERE rowid NOT IN "
                     "(SELECT rowid FROM query_cache ORDER BY created_at DESC, rowid DESC LIMIT ?)",
                     (QUERY_CACHE_MAX,))
        conn.commit()
    except sqlite3.Error:
        pass  # cache is an optimization, never a failure mode
    return vecs[0]


def dense_search(conn, paths, model, q, limit):
    qv = _query_vec(conn, paths, model, q)
    if not qv:
        return []
    rows = conn.execute(
        "SELECT id,path,heading,text,doc_type,date,embedding FROM chunks WHERE embedding IS NOT NULL"
    ).fetchall()
    scored = []
    for r in rows:
        try:
            ev = json.loads(r[6])
        except (ValueError, TypeError):
            continue
        scored.append((cosine(qv, ev),
                       dict(id=r[0], path=r[1], heading=r[2], text=r[3], doc_type=r[4], date=r[5])))
    scored.sort(key=lambda x: -x[0])
    return [d for _s, d in scored[:limit]]


_FAIL_RE = re.compile(r"\b(blocked|rejected|violation|scope|failed|timeout|error)\b", re.I)


def _boost(item) -> float:
    b = 0.0
    if item.get("doc_type") in ("execution", "memory"):
        b += 0.05
    if _FAIL_RE.search(item.get("text", "")):
        b += 0.10  # engineering memory weights past failures higher
    d = item.get("date") or ""
    if d >= "2026-01-01":
        b += 0.05
    return b


def rank_union(bm25_list, dense_list, top):
    """Lightweight reciprocal-rank merge (NOT the full RRF+graph+diversity the review cut) +
    a small failure/recency boost. Deterministic, scale-free across the two retrievers."""
    agg = {}
    for rank, item in enumerate(bm25_list):
        e = agg.setdefault(item["id"], {"item": item, "score": 0.0})
        e["score"] += 1.0 / (rank + 1)
    for rank, item in enumerate(dense_list):
        e = agg.setdefault(item["id"], {"item": item, "score": 0.0})
        e["score"] += 1.0 / (rank + 1)
    for e in agg.values():
        e["score"] += _boost(e["item"])
    ranked = sorted(agg.values(), key=lambda e: -e["score"])
    return [e["item"] for e in ranked[:top]]


def context_pack(results, q, as_json):
    if as_json:
        return json.dumps([
            {"path": r["path"], "heading": r["heading"], "doc_type": r["doc_type"],
             "date": r["date"], "snippet": (r["text"] or "")[:280]} for r in results
        ], ensure_ascii=False, indent=2)
    out = ["# V-memory recall", "", "Query: %s" % q, ""]
    if not results:
        out.append("_No matching prior context._")
        return "\n".join(out)
    out.append("## Evidence")
    for i, r in enumerate(results, 1):
        loc = r["path"] + (" — " + r["heading"] if r["heading"] else "")
        out.append("\n### %d. %s" % (i, loc))
        snip = " ".join((r["text"] or "").split())[:280]
        out.append(snip)
    return "\n".join(out)


def index_staleness(conn, root):
    """Cheap path-set staleness (no hashing, ~one `git ls-files`): how many git-tracked docs
    are not yet indexed, and how many indexed docs are gone. This is the MULTI-DEV freshness
    signal — after a `git pull` brings teammates' new docs, search can say the index is behind
    before a refresh catches up. Knowledge accumulates via the committed corpus; this just tells
    you your local cache hasn't caught up yet."""
    files = set(tracked_files(root))
    known = {r[0] for r in conn.execute("SELECT path FROM indexed_files")}
    return len(files - known), len(known - files)


def cmd_search(args) -> int:
    root = find_repo_root(args.repo or os.getcwd())
    paths = cache_paths(root)
    if not os.path.exists(paths["db"]):
        print("V-memory index not found. Run: python3 scripts/compound-v-memory.py refresh")
        return 1
    conn = open_db(paths["db"])
    pool = max(args.top * 4, 20)
    bm25_list = bm25_search(conn, args.query, pool)
    dense_list = []
    if not args.no_embed and dense_active(conn, paths, meta_get(conn, "embed_model", DEFAULT_MODEL)):
        dense_list = dense_search(conn, paths, meta_get(conn, "embed_model", DEFAULT_MODEL), args.query, pool)
    results = rank_union(bm25_list, dense_list, args.top)
    new, removed = index_staleness(conn, root)
    if new or removed:
        # multi-dev: a teammate's pulled docs aren't indexed yet (or some were removed).
        sys.stderr.write("V-memory: index is %d new / %d removed docs behind the repo — "
                         "run /v:memory-refresh to include the latest pulled knowledge.\n"
                         % (new, removed))
    print(context_pack(results, args.query, args.json))
    return 0


# --------------------------------------------------------------------------- #
# recall-check — the deterministic, conservative-only recall->action bridge
# --------------------------------------------------------------------------- #
FAIL_STATUSES = {"blocked", "error", "timeout"}


def scan_failures(results_root):
    """Yield (run, status, files) for every job_result.json under results_root that FAILED.
    Reads the authoritative git-derived record (schemas/job_result.schema.json), not prose."""
    out = []
    if not os.path.isdir(results_root):
        return out
    for dirpath, _dirs, files in os.walk(results_root):
        if os.path.basename(dirpath) != "results":
            continue
        for f in files:
            if not f.endswith(".json"):
                continue
            try:
                with open(os.path.join(dirpath, f)) as fh:
                    rec = json.load(fh)
            except (OSError, ValueError):
                continue
            if not isinstance(rec, dict):
                continue
            failed = bool(rec.get("blocked")) or rec.get("status") in FAIL_STATUSES
            if not failed:
                continue
            files_changed = rec.get("violations") or rec.get("files_changed") or []
            if not isinstance(files_changed, list):
                continue
            out.append({"run": os.path.relpath(os.path.join(dirpath, f), results_root),
                        "status": rec.get("status"), "files": [str(x) for x in files_changed]})
    return out


def _file_matches(changed, globs):
    """Anchored match only — no substring fallback (so `src/api` can't match `src/api2/…`).
    A bare directory/prefix means "anything under it" via an explicit `<g>/*` form."""
    for g in globs:
        if fnmatch.fnmatch(changed, g):
            return True
        if fnmatch.fnmatch(changed, g.rstrip("/") + "/*"):
            return True
    return False


def recall_check(file_globs, results_root, k):
    """Conservative-only verdict: N>=k structurally-recorded failures on the same file pattern
    => TIGHTEN. Never reroutes, never loosens. Gated by structured match, not embeddings."""
    failures = scan_failures(results_root)
    matched = []
    for fl in failures:
        for changed in fl["files"]:
            if _file_matches(changed, file_globs):
                matched.append({"run": fl["run"], "status": fl["status"], "file": changed})
                break
    verdict = "tighten" if len(matched) >= k else "none"
    actions = []
    if verdict == "tighten":
        actions = ["force_worktree", "extra_review_pass", "fold_into_task0"]
    return {
        "verdict": verdict, "match_count": len(matched), "k": k,
        "files_queried": file_globs, "actions": actions, "evidence": matched[:10],
        "note": "conservative-only: may tighten the next run; never reroutes to a lower-trust "
                "backend and never loosens. Authority remains routing-lessons.md + scorecard.",
    }


def cmd_recall_check(args) -> int:
    root = find_repo_root(args.repo or os.getcwd())
    results_root = args.results_root or os.path.join(root, DOCS_REL, "execution")
    verdict = recall_check(args.files, results_root, args.k)
    if args.json:
        print(json.dumps(verdict, ensure_ascii=False, indent=2))
    else:
        print("recall-check: %s (%d/%d match on %s)"
              % (verdict["verdict"], verdict["match_count"], verdict["k"], ", ".join(args.files)))
        if verdict["verdict"] == "tighten":
            print("  recommend (conservative-only): " + ", ".join(verdict["actions"]))
            for e in verdict["evidence"]:
                print("  - %s: %s on %s" % (e["run"], e["status"], e["file"]))
    return 0


# --------------------------------------------------------------------------- #
# bootstrap / doctor
# --------------------------------------------------------------------------- #
def cmd_bootstrap(args) -> int:
    """The ONLY network step. Creates the out-of-repo venv, installs the embedding deps,
    writes the embedder, validates by encoding a probe, atomically activates. Failure ⇒
    stays FTS5-only (no partial venv left active)."""
    root = find_repo_root(args.repo or os.getcwd())
    paths = cache_paths(root)
    model = args.model or DEFAULT_MODEL
    os.makedirs(paths["dir"], exist_ok=True)
    venv_tmp = paths["venv"] + ".tmp"
    import shutil
    shutil.rmtree(venv_tmp, ignore_errors=True)
    print("V-memory bootstrap: creating venv (this is the only network/install step)…")
    try:
        subprocess.run([sys.executable, "-m", "venv", venv_tmp], check=True, timeout=120)
        vpy = os.path.join(venv_tmp, "bin", "python")
        subprocess.run([vpy, "-m", "pip", "install", "-q", "--upgrade", "pip"], timeout=300)
        # Default (e5 / Xenova ONNX): light direct-onnxruntime lane, no torch.
        reqs = ["onnxruntime", "tokenizers", "huggingface_hub", "numpy"]
        if "gte" in model:  # quality tier needs the torch-backed sentence-transformers
            reqs = ["sentence-transformers", "einops", "numpy"]
        subprocess.run([vpy, "-m", "pip", "install", "-q"] + reqs, check=True, timeout=1800)
    except (OSError, subprocess.SubprocessError) as e:
        shutil.rmtree(venv_tmp, ignore_errors=True)
        print("V-memory bootstrap FAILED (%s) — staying FTS5-only." % type(e).__name__)
        return 1
    # write embedder into tmp, validate by encoding a probe
    emb_tmp = os.path.join(venv_tmp, "embedder.py")
    with open(emb_tmp, "w") as fh:
        fh.write(EMBEDDER_SRC)
    probe_paths = dict(paths)
    probe_paths["venv_py"] = os.path.join(venv_tmp, "bin", "python")
    probe_paths["embedder"] = emb_tmp
    # bootstrap is the ONE place a download is allowed.
    vecs = embed_texts(probe_paths, model, "passage", ["compound-v memory probe"],
                       allow_download=True)
    if not vecs or not vecs[0]:
        shutil.rmtree(venv_tmp, ignore_errors=True)
        print("V-memory bootstrap: probe encode failed — staying FTS5-only.")
        return 1
    dim = len(vecs[0])
    fp = _fingerprint(vecs[0])
    # atomically activate
    shutil.rmtree(paths["venv"], ignore_errors=True)
    os.rename(venv_tmp, paths["venv"])
    with open(paths["embedder"], "w") as fh:
        fh.write(EMBEDDER_SRC)
    conn = open_db(paths["db"])
    meta_set(conn, "embed_model", model)
    meta_set(conn, "embed_dim", dim)
    meta_set(conn, "embed_fingerprint", fp)
    meta_set(conn, "embedder_src", _embedder_src_hash())   # part of the enforced identity
    conn.commit()
    print("V-memory bootstrap OK: model=%s dim=%d fp=%s. Run "
          "`refresh --with-embeddings` to populate vectors." % (model, dim, fp))
    return 0


def cmd_doctor(args) -> int:
    root = find_repo_root(args.repo or os.getcwd())
    paths = cache_paths(root)
    print("V-memory doctor")
    print("  repo        : %s" % root)
    print("  cache (ext) : %s" % paths["dir"])
    has_db = os.path.exists(paths["db"])
    print("  index       : %s" % ("present" if has_db else "absent (run refresh)"))
    if has_db:
        conn = open_db(paths["db"])
        n = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        nf = conn.execute("SELECT COUNT(*) FROM indexed_files").fetchone()[0]
        nv = conn.execute("SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL").fetchone()[0]
        print("  files/chunks: %d files, %d chunks (%d with vectors)" % (nf, n, nv))
        print("  embed_model : %s" % meta_get(conn, "embed_model", "(none)"))
        files = tracked_files(root)
        present = set(files)
        known = {r[0]: r[1] for r in conn.execute("SELECT path,content_hash FROM indexed_files")}
        new = [f for f in files if f not in known]
        changed = [f for f in files if f in known and file_sha(os.path.join(root, f)) != known[f]]
        removed = [p for p in known if p not in present]
        print("  staleness   : %d new, %d changed, %d removed (run refresh to sync)"
              % (len(new), len(changed), len(removed)))
    print("  embeddings  : %s" % ("bootstrapped" if is_bootstrapped(paths) else "not bootstrapped (FTS5-only)"))
    print("  scale gate  : dense engages at >= %d vectors" % SCALE_GATE_MIN_CHUNKS)
    return 0


# --------------------------------------------------------------------------- #
# self-tests (stdlib only — no network, no model)
# --------------------------------------------------------------------------- #
def _selftest() -> int:
    import shutil
    fails = []

    def check(name, cond):
        if not cond:
            fails.append(name)
            print("  FAIL %s" % name)
        else:
            print("  ok   %s" % name)

    # repo_id determinism
    check("repo_id stable", repo_id("/a/b") == repo_id("/a/b") and repo_id("/a/b") != repo_id("/a/c"))

    # redaction — token families incl. sk- with an interior hyphen (Codex finding)
    r = redact("k sk-proj-abcd1234EFGH5678 and ghp_abcdefabcdefabcdef12 plus AKIA0123456789AB e")
    check("redact tokens", "sk-proj-abcd" not in r and "ghp_abcdef" not in r
          and "AKIA0123" not in r and "[REDACTED]" in r)
    pem = ("h\n-----BEGIN RSA PRIVATE KEY-----\nMIIBVQIBADANBgkqhkiG\n9w0BAQ\n"
           "-----END RSA PRIVATE KEY-----\nt")
    rp = redact(pem)
    check("redact whole PEM block", "MIIBVQIBADANBg" not in rp and "PRIVATE KEY" not in rp
          and "h\n" in rp and rp.endswith("\nt"))

    # doc_type / date
    check("doc_type", doc_type_for("docs/superpowers/execution/2026-06-27-x/results/a.json") == "execution")
    check("doc_type specs", doc_type_for("docs/superpowers/specs/x.md") == "specs")
    check("date", date_for("docs/superpowers/plans/2026-06-26-x.md") == "2026-06-26")

    # chunking
    md = "# A\nintro\n## B\nbody b\n## C\nbody c"
    cm = chunk_markdown(md)
    check("md chunks by heading", len(cm) == 3 and cm[0][0] == "A" and cm[1][0] == "B")
    jl = chunk_jsonl('{"a":1}\n\n{"b":2}\n')
    check("jsonl one chunk per line", len(jl) == 2)
    long = "# H\n" + ("x " * 4000)
    check("long split", len(chunk_markdown(long)) >= 2)

    # fts5_escape — the crash-class inputs
    check("fts5 escape filename", fts5_escape("index.ts") == '"index" OR "ts"')
    check("fts5 escape operator", fts5_escape("blocked OR") == '"blocked" OR "OR"')
    check("fts5 escape punct-only", fts5_escape("...") is None)
    check("fts5 escape quote", fts5_escape('"x') == '"x"')

    # end-to-end index + search in a temp repo + temp cache (non-git fallback path)
    tmp = tempfile.mkdtemp()
    try:
        os.environ["COMPOUND_V_MEMORY_HOME"] = os.path.join(tmp, "cache")
        docs = os.path.join(tmp, DOCS_REL)
        os.makedirs(os.path.join(docs, "execution", "2026-06-27-demo", "results"))
        os.makedirs(os.path.join(docs, "specs"))
        with open(os.path.join(docs, "specs", "2026-06-27-thing.md"), "w") as fh:
            fh.write("# Thing\nThe codex worker touched index.ts and was blocked on scope.\n")
        with open(os.path.join(docs, "memory.md"), "w") as fh:
            fh.write("# Notes\nSonnet is a narrow carve-out; Opus is the default planner.\n")

        class A:  # args shim
            repo = tmp; rebuild = True; quick = False; with_embeddings = False
        check("refresh ok", cmd_refresh(A()) == 0)

        paths = cache_paths(find_repo_root(tmp))
        conn = open_db(paths["db"])
        # the crash query must NOT throw and should find the doc
        res = bm25_search(conn, "index.ts", 10)
        check("search filename no-crash + hit", any("thing" in r["path"] for r in res))
        res2 = bm25_search(conn, "who is the default planner", 10)
        check("search semantic-ish lexical hit", any("memory.md" in r["path"] for r in res2))
        check("search punct-only empty", bm25_search(conn, "%%%", 10) == [])

        # incremental: unchanged -> 0 reindex; change one -> reindex; remove -> purge
        class A2:
            repo = tmp; rebuild = False; quick = False; with_embeddings = False
        before = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        cmd_refresh(A2())
        check("incremental stable", conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == before)

        # --- v2.5.4: reindex_batch embeds ALL files' chunks in ONE embedder call (model loads once)
        root = find_repo_root(tmp)
        rels = [r[0] for r in conn.execute("SELECT path FROM indexed_files")]

        def _enc(t):  # content-dependent scalar so a mis-sliced vector would not match its chunk
            return float(sum(t.encode("utf-8")) % 1000000)
        _calls = {"n": 0}

        def _fake_embed(texts):
            _calls["n"] += 1
            return [[_enc(t)] for t in texts]
        reindex_batch(conn, root, rels, _fake_embed)
        check("reindex_batch: ONE embedder call for many files (model loaded once)",
              _calls["n"] == 1 and len(rels) >= 2)
        _rows = list(conn.execute("SELECT text, embedding FROM chunks WHERE embedding IS NOT NULL"))
        check("reindex_batch: each chunk's vector matches its own text (slicing correct)",
              len(_rows) > 0 and all(json.loads(bytes(e).decode()) == [_enc(t)] for t, e in _rows))
        reindex_batch(conn, root, rels, lambda texts: None)   # failed embed -> degrade
        _tot = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        _nul = conn.execute("SELECT COUNT(*) FROM chunks WHERE embedding IS NULL").fetchone()[0]
        check("reindex_batch: failed embed degrades to NULL (FTS5-only), no crash",
              _tot > 0 and _nul == _tot)

        # --- v2.5.5: query-vector cache — a repeated query skips the embedder (model load) ---
        _qc = {"n": 0}

        def _fake_q(texts):
            _qc["n"] += 1
            return [[1.0, 2.0]]
        v1 = _query_vec(conn, None, "m1", "scope gate", embed=_fake_q)
        v2 = _query_vec(conn, None, "m1", "scope gate", embed=_fake_q)   # cache HIT
        check("query cache: repeat query skips the embedder (1 call, same vec)",
              _qc["n"] == 1 and v1 == v2 == [1.0, 2.0])
        _query_vec(conn, None, "m2", "scope gate", embed=_fake_q)        # model change -> MISS
        check("query cache: model change misses (re-embeds)", _qc["n"] == 2)
        check("query cache: failed embed returns None, nothing cached",
              _query_vec(conn, None, "m3", "x", embed=lambda t: None) is None
              and conn.execute("SELECT COUNT(*) FROM query_cache WHERE model='m3'").fetchone()[0] == 0)

        # lock: a held lock makes a second acquire a no-op (separate open file descriptions)
        fd = acquire_lock(paths["lock"])
        fd2 = acquire_lock(paths["lock"])
        check("flock loser is no-op", fd is not None and fd2 is None)
        release_lock(fd)

        # recall-check bridge: fixtures -> tightening
        rdir = os.path.join(docs, "execution", "2026-06-27-demo", "results")
        for i, fn in enumerate(["j1.json", "j2.json"]):
            with open(os.path.join(rdir, fn), "w") as fh:
                json.dump({"status": "blocked", "blocked": True,
                           "files_changed": ["src/api/types.ts"],
                           "violations": ["src/api/types.ts"]}, fh)
        with open(os.path.join(rdir, "ok.json"), "w") as fh:
            json.dump({"status": "success", "blocked": False,
                       "files_changed": ["src/ui/button.tsx"], "violations": []}, fh)
        v = recall_check(["src/api/*.ts"], os.path.join(docs, "execution"), RECALL_K)
        check("recall tighten on repeated failure", v["verdict"] == "tighten" and v["match_count"] == 2)
        v2 = recall_check(["src/ui/*.tsx"], os.path.join(docs, "execution"), RECALL_K)
        check("recall none on success file", v2["verdict"] == "none")
        v3 = recall_check(["src/api/*.ts"], os.path.join(docs, "execution"), 5)
        check("recall respects k threshold", v3["verdict"] == "none")

        # anchored matching: a bare dir prefix matches UNDER it but not a sibling dir
        with open(os.path.join(rdir, "j3.json"), "w") as fh:
            json.dump({"status": "blocked", "blocked": True,
                       "files_changed": ["src/api2/x.ts"], "violations": ["src/api2/x.ts"]}, fh)
        v4 = recall_check(["src/api"], os.path.join(docs, "execution"), RECALL_K)
        check("recall bare-prefix matches under dir, not sibling", v4["match_count"] == 2)

        # degrade: dense inactive without bootstrap -> search still returns (FTS5-only)
        check("degrade FTS5-only", not dense_active(conn, paths, DEFAULT_MODEL))

        # multi-dev staleness: a new tracked doc not yet indexed reads as "behind the repo"
        with open(os.path.join(docs, "specs", "teammate-pulled.md"), "w") as fh:
            fh.write("# Pulled\nA teammate's freshly pulled knowledge, not yet indexed locally.\n")
        s_new, s_removed = index_staleness(conn, find_repo_root(tmp))
        check("staleness flags an un-indexed pulled doc", s_new >= 1)

        # /v:init opt-in: .claude/compound-v.json drives the dense lane (no --with-embeddings flag)
        cfgdir = os.path.join(tmp, ".claude"); os.makedirs(cfgdir, exist_ok=True)
        check("config embeddings default false", config_wants_embeddings(tmp) is False)
        json.dump({"memory": {"embeddings": True}}, open(os.path.join(cfgdir, "compound-v.json"), "w"))
        check("config embeddings true is read", config_wants_embeddings(tmp) is True)
        json.dump({"stance": "balanced"}, open(os.path.join(cfgdir, "compound-v.json"), "w"))
        check("config without memory key => false", config_wants_embeddings(tmp) is False)

        # cosine dimension guard — stale-identity vectors must not half-match
        check("cosine dim guard", cosine([1.0, 0.0], [1.0, 0.0, 0.0]) == 0.0
              and abs(cosine([1.0, 0.0], [1.0, 0.0]) - 1.0) < 1e-9)

        # embedding identity enforcement (model + chunker + embedder code)
        meta_set(conn, "embed_model", DEFAULT_MODEL)
        meta_set(conn, "chunker_version", CHUNKER_VERSION)
        meta_set(conn, "embedder_src", _embedder_src_hash())
        conn.commit()
        check("identity matches when aligned", identity_matches(conn, DEFAULT_MODEL))
        meta_set(conn, "chunker_version", "STALE"); conn.commit()
        check("identity drift on chunker change", not identity_matches(conn, DEFAULT_MODEL))
        meta_set(conn, "chunker_version", CHUNKER_VERSION)
        meta_set(conn, "embedder_src", "deadbeef"); conn.commit()
        check("identity drift on embedder change", not identity_matches(conn, DEFAULT_MODEL))
    finally:
        os.environ.pop("COMPOUND_V_MEMORY_HOME", None)
        shutil.rmtree(tmp, ignore_errors=True)

    # onboarding: doc_type_for clean labels for root files (no filename leak)
    check("doc_type root agents", doc_type_for("AGENTS.md") == "agents")
    check("doc_type root claude", doc_type_for("CLAUDE.md") == "claude")
    check("doc_type root conventions", doc_type_for("CONVENTIONS.md") == "conventions")
    check("doc_type root design", doc_type_for("DESIGN.md") == "design")
    # unchanged: a non-onboarding root path still falls back to parts[0]
    check("doc_type other root", doc_type_for("README.md") == "README.md")

    # onboarding: tracked_files unions root onboarding files when git-tracked
    # (tempfile is already imported at module scope; only alias subprocess here to
    # avoid shadowing the module-level `tempfile` used by the end-to-end block above)
    import subprocess as _sp
    d = tempfile.mkdtemp()
    try:
        _sp.run(["git", "-C", d, "init", "-q"], check=True)
        os.makedirs(os.path.join(d, "docs", "superpowers", "architecture"))
        for rel in ["AGENTS.md", "CONVENTIONS.md",
                    os.path.join("docs", "superpowers", "architecture", "architecture.md")]:
            with open(os.path.join(d, rel), "w") as fh:
                fh.write("# x\n")
        _sp.run(["git", "-C", d, "add", "-A"], check=True)
        tf = tracked_files(d)
        check("tracked_files unions roots",
              "AGENTS.md" in tf and "CONVENTIONS.md" in tf
              and any(p.endswith("architecture.md") for p in tf))
    finally:
        shutil.rmtree(d, ignore_errors=True)

    print("\n%d failed" % len(fails))
    if fails:
        print("FAILED: " + ", ".join(fails))
        return 1
    print("all self-tests passed")
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser():
    p = argparse.ArgumentParser(description="Compound V — V-memory recall engine")
    p.add_argument("--selftest", action="store_true", help="run stdlib self-tests and exit")
    sub = p.add_subparsers(dest="cmd")

    def add_repo(sp):
        sp.add_argument("--repo", help="repo root (default: cwd / git toplevel)")

    sp = sub.add_parser("refresh", help="incrementally index git-tracked docs/superpowers prose")
    add_repo(sp)
    sp.add_argument("--rebuild", action="store_true")
    sp.add_argument("--quick", action="store_true", help="skip if too many files changed")
    sp.add_argument("--with-embeddings", dest="with_embeddings", action="store_true")

    sp = sub.add_parser("search", help="recall: FTS5 (+ dense if bootstrapped) -> context pack")
    add_repo(sp)
    sp.add_argument("query")
    sp.add_argument("--top", type=int, default=8)
    sp.add_argument("--intent", choices=["planning", "review"], default=None)
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--no-embed", dest="no_embed", action="store_true")

    sp = sub.add_parser("recall-check", help="deterministic recurring-failure -> tighten verdict")
    add_repo(sp)
    sp.add_argument("--files", nargs="+", required=True, help="file globs of the current diff")
    sp.add_argument("--k", type=int, default=RECALL_K)
    sp.add_argument("--results-root", dest="results_root", default=None)
    sp.add_argument("--json", action="store_true")

    sp = sub.add_parser("bootstrap", help="(opt-in, network) create the out-of-repo embedding venv")
    add_repo(sp)
    sp.add_argument("--model", default=None)

    sp = sub.add_parser("doctor", help="report index / venv / staleness health")
    add_repo(sp)
    return p


def main(argv) -> int:
    args = build_parser().parse_args(argv)
    if args.selftest:
        return _selftest()
    if not args.cmd:
        build_parser().print_help()
        return 1
    return {
        "refresh": cmd_refresh, "search": cmd_search, "recall-check": cmd_recall_check,
        "bootstrap": cmd_bootstrap, "doctor": cmd_doctor,
    }[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
