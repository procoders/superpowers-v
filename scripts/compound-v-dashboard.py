#!/usr/bin/env python3
"""
Compound V observability dashboard -- v2.15.0 (NEW file, PRESENT-ONLY, read-only).

Closes the plugin's observability gap over docs/superpowers/execution/** WITHOUT a daemon,
a persistent service, or any write/control surface. Two subcommands + a self-test:

  * emit  -- read the run/epic JSON under an execution root and write ONE self-contained,
            theme-aware HTML snapshot (all CSS/JS inlined, offline, no CDN, no external
            http(s) resource). Prints the path. The static page stamps
            "snapshot -- generated from files as of <newest state-file mtime>".

  * serve -- an EPHEMERAL, READ-ONLY, foreground http.server viewer. Binds the loopback
            address ONLY (never a public/hostname bind), default port 8787 (falls back to an
            OS-chosen free port if taken). GET/HEAD only -- every other method is 405.
            Realpath-contained to the execution root; serves only .json/.html/.yaml/.yml;
            no directory index. Serves a live page at "/" that re-polls every ~3s and
            re-renders. Runs serve_forever() until Ctrl-C, then shuts down cleanly.

Design posture -- "observe in the UI, act via the CLI": there is NO merge/kill/retry/edit
control anywhere. Enforcement stays with the git-derived gates; the dashboard only reflects.

ANTI-RUFLO (the identity -- a dashboard that does not lie):
  * Render ONLY what is in the state files. NO fabricated progress percentages -- only real
    counts (N/M jobs|features done). The whole document is written with ZERO "%" characters
    so a percentage can never sneak in.
  * Usage is MEASURED-ONLY: a job whose usage.measured != true (or has no usage object) shows
    an em-dash, NEVER a fabricated 0.
  * Every timestamp comes from a state-file field (updated_at / started_at / last_progress_at /
    recorded_at) or a real file mtime -- never datetime.now(). All rendered data is escaped
    with html.escape.

DEGRADE-SAFE:
  * A run dir with only manifest.yaml (no state.json) -> an honest "no state yet" card.
  * Malformed/partial JSON -> an "unparseable" note on that card, never a crash.
  * Empty execution root -> "no runs yet".

Pure Python 3.9-safe stdlib only (json, html, http.server, socketserver, argparse, pathlib,
urllib.parse, os, io, socket, inspect, ast, datetime). No third-party imports. LANG=C clean
(all file I/O is explicitly utf-8; the source is ASCII-only and emits HTML entities for symbols).

Run the self-test with:  python3 scripts/compound-v-dashboard.py --selftest
"""

import argparse
import ast
import datetime
import html
import http.server
import inspect
import io
import json
import os
import socketserver
import sys
import urllib.parse

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_EXECUTION_ROOT = "docs/superpowers/execution"
DEFAULT_OUT = "docs/superpowers/execution/dashboard.html"
DEFAULT_PORT = 8787
# Loopback bind ONLY -- unreachable from the network. A public/all-interfaces bind is never
# constructed anywhere in this file (the self-test asserts the literal is absent from source).
BIND_HOST = "127.0.0.1"
ALLOWED_SUFFIXES = (".json", ".html", ".yaml", ".yml")

DONE_JOB_STATES = ("done", "success")
MDASH = "&mdash;"

CONTENT_TYPES = {
    ".json": "application/json; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".yaml": "text/plain; charset=utf-8",
    ".yml": "text/plain; charset=utf-8",
}


# ---------------------------------------------------------------------------
# Minimal block-YAML parser (stdlib only) -- handles the regular, machine-generated
# manifest.yaml subset: mappings, scalars, block sequences, and lists-of-maps.
# ---------------------------------------------------------------------------

def _scalar(val):
    """Coerce a YAML scalar token to a Python value (quote-strip, inline-comment-strip)."""
    val = val.strip()
    if not val:
        return None
    if val[0] in "\"'":
        quote = val[0]
        end = val.find(quote, 1)
        if end != -1:
            return val[1:end]
        return val[1:]
    # strip a trailing inline comment ( space + '#' )
    hpos = val.find(" #")
    if hpos != -1:
        val = val[:hpos].strip()
    if val in ("[]",):
        return []
    if val.startswith("[") and val.endswith("]"):
        inner = val[1:-1].strip()
        if not inner:
            return []
        return [_scalar(p) for p in inner.split(",")]
    low = val.lower()
    if low in ("null", "~", "none"):
        return None
    if low == "true":
        return True
    if low == "false":
        return False
    try:
        return int(val)
    except ValueError:
        return val


def _tokenize_yaml(text):
    toks = []
    for raw in text.split("\n"):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        toks.append((indent, raw.strip()))
    return toks


class _YamlParser:
    def __init__(self, toks):
        self.toks = toks
        self.i = 0

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else None

    def parse(self):
        tok = self.peek()
        if tok is None:
            return None
        return self._block(tok[0])

    def _block(self, indent):
        tok = self.peek()
        if tok is None:
            return None
        if tok[1].startswith("- "):
            return self._seq(indent)
        return self._map(indent)

    def _map(self, indent):
        out = {}
        while True:
            tok = self.peek()
            if tok is None or tok[0] < indent or tok[0] > indent:
                break
            if tok[1].startswith("- "):
                break
            self.i += 1
            key, _, val = tok[1].partition(":")
            key = key.strip()
            val = val.strip()
            out[key] = self._value(val, indent)
        return out

    def _value(self, val, indent):
        if val != "":
            return _scalar(val)
        nxt = self.peek()
        if nxt is None:
            return None
        if nxt[0] > indent:
            return self._block(nxt[0])
        if nxt[0] == indent and nxt[1].startswith("- "):
            return self._seq(indent)
        return None

    def _seq(self, indent):
        items = []
        while True:
            tok = self.peek()
            if tok is None or tok[0] != indent or not tok[1].startswith("- "):
                break
            inner = tok[1][2:].strip()
            if inner and ":" in inner and inner[0] not in "\"'":
                items.append(self._seq_map(indent, inner))
            else:
                self.i += 1
                items.append(_scalar(inner))
        return items

    def _seq_map(self, dash_indent, first_inner):
        body_indent = dash_indent + 2
        self.i += 1
        out = {}
        key, _, val = first_inner.partition(":")
        out[key.strip()] = self._value(val.strip(), body_indent)
        while True:
            tok = self.peek()
            if tok is None or tok[0] != body_indent or tok[1].startswith("- "):
                break
            self.i += 1
            k2, _, v2 = tok[1].partition(":")
            out[k2.strip()] = self._value(v2.strip(), body_indent)
        return out


def parse_yaml(text):
    return _YamlParser(_tokenize_yaml(text)).parse()


# ---------------------------------------------------------------------------
# Safe file readers (degrade-safe: return (value, error_message))
# ---------------------------------------------------------------------------

def _read_text(path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def read_json(path):
    try:
        return json.loads(_read_text(path)), None
    except Exception as exc:  # noqa: BLE001 -- degrade-safe by contract
        return None, str(exc)


def read_yaml(path):
    try:
        return parse_yaml(_read_text(path)), None
    except Exception as exc:  # noqa: BLE001 -- degrade-safe by contract
        return None, str(exc)


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _fmt_mtime(ts):
    return datetime.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%SZ")


def _contained(path, root):
    """True iff `path`'s realpath is exactly `root` or strictly under it.

    `root` MUST already be an os.path.realpath'd absolute directory. This is the single
    containment gate: any candidate file whose real target escapes the resolved execution
    root (via a symlink or otherwise) is refused -- it is never read, rendered, or inlined.
    Fail-closed: an unresolvable path returns False rather than raising.
    """
    try:
        cand = os.path.realpath(path)
    except OSError:
        return False
    # `root + os.sep` would double the separator when root is the filesystem root ("/"),
    # wrongly rejecting every child; normalize so root=="/" (or any sep-terminated root) works.
    prefix = root if root.endswith(os.sep) else root + os.sep
    return cand == root or cand.startswith(prefix)


def _shape_error(raw, existed, err):
    """Promote a structurally-wrong-but-valid document (e.g. a top-level list) to an
    explicit 'invalid shape' error, so it renders as unparseable instead of a silent UNKNOWN."""
    if err is None and existed and not isinstance(raw, dict):
        return "unexpected top-level shape (expected an object)"
    return err


# ---------------------------------------------------------------------------
# Model builders
# ---------------------------------------------------------------------------

def load_run(dirpath, root):
    rec = {"kind": "run", "id": os.path.basename(dirpath.rstrip("/")), "path": dirpath}
    man_path = os.path.join(dirpath, "manifest.yaml")
    state_path = os.path.join(dirpath, "state.json")

    # HIGH-1: every reader used to build the rendered model is realpath-contained to `root`.
    # A file whose real target escapes the root is skipped (never read), not crashed on.
    if _contained(man_path, root):
        manifest, m_err = read_yaml(man_path)
    else:
        manifest, m_err = None, None
    # containment FIRST (short-circuit) so isfile never even stats an escaping symlink target
    m_err = _shape_error(manifest, _contained(man_path, root) and os.path.isfile(man_path), m_err)
    rec["manifest"] = manifest if isinstance(manifest, dict) else None
    rec["manifest_error"] = m_err

    # has_state is honest AND contained: a symlink escaping the root is treated as "no state".
    rec["has_state"] = _contained(state_path, root) and os.path.isfile(state_path)
    state, s_err = (read_json(state_path) if rec["has_state"] else (None, None))
    s_err = _shape_error(state, rec["has_state"], s_err)
    rec["state"] = state if isinstance(state, dict) else None
    rec["state_error"] = s_err

    # per-job results (results/<id>.json) -- each candidate realpath-contained before reading
    results = {}
    res_dir = os.path.join(dirpath, "results")
    # HIGH-1: contain the results DIR itself before listing it, so a symlinked `results/`
    # pointing outside the root cannot leak external filenames (each file is contained too, below).
    if _contained(res_dir, root) and os.path.isdir(res_dir):
        try:
            names = sorted(os.listdir(res_dir))
        except OSError:
            names = []
        for name in names:
            if name.endswith(".json"):
                cand = os.path.join(res_dir, name)
                if not _contained(cand, root):
                    continue
                obj, err = read_json(cand)
                results[name[:-5]] = {"obj": obj if isinstance(obj, dict) else None, "err": err}
    rec["results"] = results

    # jobs from manifest (authoritative order) falling back to state
    jobs = []
    if rec["manifest"] and isinstance(rec["manifest"].get("jobs"), list):
        for j in rec["manifest"]["jobs"]:
            if isinstance(j, dict):
                jobs.append(j)
    rec["jobs"] = jobs

    # counts (real, never fabricated)
    state_jobs = rec["state"].get("jobs") if rec["state"] and isinstance(rec["state"].get("jobs"), dict) else {}
    done = 0
    for jid, jv in (state_jobs or {}).items():
        if isinstance(jv, dict) and str(jv.get("status", "")).lower() in DONE_JOB_STATES:
            done += 1
    # MEDIUM-6: total is the UNION of manifest job ids and state.json job ids, so that a
    # state-only job can never push `done` past `total` (no impossible "3/2 jobs done").
    manifest_ids = [j.get("id") for j in jobs if isinstance(j, dict) and j.get("id")]
    state_ids = list(state_jobs.keys()) if isinstance(state_jobs, dict) else []
    total = len(set(manifest_ids) | set(state_ids))
    rec["total"] = total
    rec["done"] = done
    rec["state_jobs"] = state_jobs

    # status pill = run phase (or an honest degraded label)
    if rec["state"] and rec["state"].get("phase"):
        rec["status"] = str(rec["state"]["phase"])
    elif not rec["has_state"]:
        rec["status"] = "NO STATE"
    elif rec["state_error"]:
        rec["status"] = "UNPARSEABLE"
    else:
        rec["status"] = "UNKNOWN"

    # newest real timestamp: prefer a state-file field, else a real file mtime
    ts_field = None
    if rec["state"]:
        for key in ("updated_at",):
            if rec["state"].get(key):
                ts_field = str(rec["state"][key])
                break
    rec["display_ts"] = ts_field
    # HIGH-1: only read an mtime from a CONTAINED path -- never follow an escaping symlink,
    # which would leak an out-of-root file's mtime into the rendered/sort timestamps.
    st_ts = _mtime(state_path) if rec["has_state"] else 0.0
    mn_ts = _mtime(man_path) if _contained(man_path, root) else 0.0
    rec["sort_ts"] = max(st_ts, mn_ts)
    rec["feature"] = (rec["manifest"] or {}).get("feature") if rec["manifest"] else None
    return rec


def load_epic(dirpath, root):
    rec = {"kind": "epic", "id": os.path.basename(dirpath.rstrip("/")), "path": dirpath}
    es_path = os.path.join(dirpath, "epic-state.json")
    # HIGH-1: skip (do not read) an epic-state.json whose real target escapes the root.
    if _contained(es_path, root):
        state, err = read_json(es_path)
        err = _shape_error(state, os.path.isfile(es_path), err)
    else:
        state, err = None, None
    rec["state"] = state if isinstance(state, dict) else None
    rec["state_error"] = err

    features = []
    if rec["state"] and isinstance(rec["state"].get("features"), list):
        for f in rec["state"]["features"]:
            if isinstance(f, dict):
                features.append(f)
    rec["features"] = features
    rec["total"] = len(features)
    rec["done"] = sum(1 for f in features if str(f.get("status", "")).lower() == "done")

    if rec["state"] and rec["state"].get("status"):
        rec["status"] = str(rec["state"]["status"])
    elif rec["state_error"]:
        rec["status"] = "UNPARSEABLE"
    else:
        rec["status"] = "UNKNOWN"

    rec["title"] = (rec["state"] or {}).get("title") if rec["state"] else None
    # newest real timestamp
    ts_field = None
    st = rec["state"] or {}
    for key in ("last_progress_at", "updated_at", "recorded_at"):
        if st.get(key):
            ts_field = str(st[key])
            break
    if ts_field is None:
        auto = st.get("autonomy") if isinstance(st.get("autonomy"), dict) else {}
        if auto.get("started_at"):
            ts_field = str(auto["started_at"])
    rec["display_ts"] = ts_field
    # HIGH-1: mtime only from a contained epic-state (never follow an escaping symlink).
    rec["sort_ts"] = _mtime(es_path) if _contained(es_path, root) else 0.0
    return rec


def build_records(root):
    """Walk the execution root; a dir with manifest.yaml is a run, one with epic-state.json an epic.

    `root` MUST be an os.path.realpath'd absolute directory (render_html resolves it once, at
    startup): every reader below is realpath-contained to this exact root.
    """
    records = []
    if not os.path.isdir(root):
        return records
    for dirpath, _dirnames, filenames in os.walk(root):
        if "epic-state.json" in filenames:
            records.append(load_epic(dirpath, root))
        if "manifest.yaml" in filenames:
            records.append(load_run(dirpath, root))
    records.sort(key=lambda r: r.get("sort_ts", 0.0), reverse=True)
    return records


# ---------------------------------------------------------------------------
# HTML rendering (all data html.escape'd; zero "%" characters in the document)
# ---------------------------------------------------------------------------

def _esc(val):
    if val is None:
        return MDASH
    return html.escape(str(val))


def _pill_class(status):
    s = str(status).lower()
    if s in ("merged", "done", "success", "done_with_blockers", "reviewed"):
        return "pill-ok"
    if s in ("blocked", "failed", "error", "timeout", "blocked_needing_human",
             "escalation_required", "unparseable"):
        return "pill-bad"
    if s in ("dispatched", "collected", "running", "fastpath_dispatched",
             "running_with_failures", "spec_ready", "preflight_done", "partition_verified"):
        return "pill-run"
    return "pill-neutral"


def _pill(status):
    return '<span class="pill {cls}">{txt}</span>'.format(
        cls=_pill_class(status), txt=_esc(status))


def _usage_cell(result_obj):
    """Measured-only: absent/measured!=true -> em-dash, never a fabricated 0."""
    if not isinstance(result_obj, dict):
        return MDASH
    usage = result_obj.get("usage")
    if not isinstance(usage, dict) or usage.get("measured") is not True:
        return MDASH
    it = usage.get("input_tokens")
    ot = usage.get("output_tokens")
    it_txt = _esc(it) if it is not None else MDASH
    ot_txt = _esc(ot) if ot is not None else MDASH
    return "in {i} / out {o}".format(i=it_txt, o=ot_txt)


CSS = """
:root{
  --bg:#f7f8fa; --fg:#1b1f24; --muted:#5a6472; --card:#ffffff; --border:#d8dee6;
  --ok-bg:#e3f6e9; --ok-fg:#166534; --bad-bg:#fde7e7; --bad-fg:#9b1c1c;
  --run-bg:#e5eefc; --run-fg:#1d4ed8; --neu-bg:#eceff3; --neu-fg:#414b57;
  --thead:#eef1f5; --code:#f0f2f5;
}
@media (prefers-color-scheme: dark){
  :root{
    --bg:#0f1216; --fg:#e6e9ee; --muted:#9aa5b1; --card:#181c22; --border:#2a313a;
    --ok-bg:#123324; --ok-fg:#6ee7a8; --bad-bg:#3a1717; --bad-fg:#f4a3a3;
    --run-bg:#132447; --run-fg:#8fb6ff; --neu-bg:#22272e; --neu-fg:#c1c9d2;
    --thead:#20262e; --code:#12161b;
  }
}
:root[data-theme="dark"]{
  --bg:#0f1216; --fg:#e6e9ee; --muted:#9aa5b1; --card:#181c22; --border:#2a313a;
  --ok-bg:#123324; --ok-fg:#6ee7a8; --bad-bg:#3a1717; --bad-fg:#f4a3a3;
  --run-bg:#132447; --run-fg:#8fb6ff; --neu-bg:#22272e; --neu-fg:#c1c9d2;
  --thead:#20262e; --code:#12161b;
}
:root[data-theme="light"]{
  --bg:#f7f8fa; --fg:#1b1f24; --muted:#5a6472; --card:#ffffff; --border:#d8dee6;
  --ok-bg:#e3f6e9; --ok-fg:#166534; --bad-bg:#fde7e7; --bad-fg:#9b1c1c;
  --run-bg:#e5eefc; --run-fg:#1d4ed8; --neu-bg:#eceff3; --neu-fg:#414b57;
  --thead:#eef1f5; --code:#f0f2f5;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  line-height:1.45;font-size:15px}
.wrap{max-width:64rem;margin:0 auto;padding:1.25rem}
header.top{display:flex;flex-wrap:wrap;align-items:baseline;gap:0.6rem;
  border-bottom:1px solid var(--border);padding-bottom:0.75rem;margin-bottom:1rem}
header.top h1{font-size:1.25rem;margin:0}
.stamp{color:var(--muted);font-size:0.82rem}
.card{background:var(--card);border:1px solid var(--border);border-radius:10px;
  padding:0.85rem 1rem;margin-bottom:0.9rem}
.card > summary{list-style:none;cursor:pointer;display:flex;flex-wrap:wrap;
  align-items:center;gap:0.55rem}
.card > summary::-webkit-details-marker{display:none}
.rid{font-weight:600;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:0.92rem}
.kind{font-size:0.7rem;text-transform:uppercase;letter-spacing:0.06em;color:var(--muted);
  border:1px solid var(--border);border-radius:5px;padding:0.05rem 0.35rem}
.title{color:var(--muted);font-size:0.88rem}
.counts{margin-left:auto;color:var(--muted);font-size:0.82rem;white-space:nowrap}
.pill{display:inline-block;font-size:0.72rem;font-weight:600;border-radius:999px;
  padding:0.12rem 0.5rem;letter-spacing:0.02em}
.pill-ok{background:var(--ok-bg);color:var(--ok-fg)}
.pill-bad{background:var(--bad-bg);color:var(--bad-fg)}
.pill-run{background:var(--run-bg);color:var(--run-fg)}
.pill-neutral{background:var(--neu-bg);color:var(--neu-fg)}
.detail{margin-top:0.8rem}
.tablewrap{overflow-x:auto}
table{border-collapse:collapse;font-size:0.82rem;min-width:34rem}
th,td{text-align:left;padding:0.32rem 0.55rem;border-bottom:1px solid var(--border);
  vertical-align:top}
thead th{background:var(--thead);position:sticky;top:0}
td.mono,th.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.note{color:var(--muted);font-size:0.85rem;margin:0.4rem 0}
.note.bad{color:var(--bad-fg)}
.deps{font-size:0.78rem;color:var(--muted)}
.deps code,.evid code{background:var(--code);border-radius:4px;padding:0.03rem 0.28rem;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.panel{display:flex;flex-wrap:wrap;gap:0.5rem;margin:0.6rem 0}
.metric{background:var(--code);border:1px solid var(--border);border-radius:8px;
  padding:0.35rem 0.6rem;font-size:0.8rem}
.metric b{display:block;font-size:1rem}
h3.sect{font-size:0.9rem;margin:0.9rem 0 0.35rem}
.empty{color:var(--muted);padding:2rem 0;text-align:center}
.evid{font-size:0.8rem;color:var(--muted)}
ul.ledger{margin:0.3rem 0;padding-left:1.1rem}
ul.ledger li{margin:0.25rem 0}
""".strip()

POLL_JS = """
(function(){
  function tick(){
    fetch(window.location.pathname+'?_t='+Date.now(),{cache:'no-store'})
      .then(function(r){return r.text();})
      .then(function(t){
        var doc=new DOMParser().parseFromString(t,'text/html');
        var fresh=doc.getElementById('dash-body');
        var cur=document.getElementById('dash-body');
        if(fresh&&cur){cur.innerHTML=fresh.innerHTML;}
        // MEDIUM-4: the header stamp is a real, file-sourced time from the fetched HTML
        // (newest state-file mtime). NO viewer wall-clock is ever synthesised here.
        var fs=doc.getElementById('page-stamp');
        var cs=document.getElementById('page-stamp');
        if(fs&&cs){cs.textContent=fs.textContent;}
      })
      .catch(function(){/* transient; keep polling */});
  }
  setInterval(tick,3000);
})();
""".strip()


def _render_run_detail(rec):
    parts = []
    if rec.get("manifest_error"):
        parts.append('<p class="note bad">unparseable manifest.yaml: {}</p>'.format(
            _esc(rec["manifest_error"])))
    if rec.get("state_error"):
        parts.append('<p class="note bad">unparseable state.json: {}</p>'.format(
            _esc(rec["state_error"])))
    if not rec.get("has_state"):
        parts.append('<p class="note">not dispatched / no state yet.</p>')

    jobs = rec.get("jobs") or []
    state_jobs = rec.get("state_jobs") or {}
    if not jobs and not state_jobs:
        parts.append('<p class="note">no jobs found.</p>')
        return "\n".join(parts)

    rows = []
    # union of manifest jobs and state-only job ids
    ordered_ids = [j.get("id") for j in jobs if j.get("id")]
    for jid in state_jobs:
        if jid not in ordered_ids:
            ordered_ids.append(jid)
    job_by_id = {j.get("id"): j for j in jobs if j.get("id")}

    for jid in ordered_ids:
        j = job_by_id.get(jid, {})
        sj = state_jobs.get(jid, {}) if isinstance(state_jobs, dict) else {}
        status = sj.get("status") if isinstance(sj, dict) else None
        res = rec["results"].get(jid, {}) if rec.get("results") else {}
        robj = res.get("obj")
        rerr = res.get("err")
        # scope gate -- MEDIUM-3: PASS is asserted ONLY on a complete, well-typed clean result.
        # A partial ({}), a contradictory ({"blocked":false,"violations":[...]}), or a wrong-typed
        # result renders UNKNOWN (never a false PASS); every len()/count is type-guarded so a
        # scalar `violations`/`files_changed` cannot crash or be counted as characters.
        if rerr:
            gate = '<span class="pill pill-bad">UNPARSEABLE</span>'
            files_changed = MDASH
        elif isinstance(robj, dict):
            blocked = robj.get("blocked")
            violations = robj.get("violations")
            viol_is_list = isinstance(violations, list)
            if blocked is True or (viol_is_list and len(violations) > 0):
                nviol = len(violations) if viol_is_list else 0
                gate = '<span class="pill pill-bad">BLOCKED ({})</span>'.format(nviol)
            elif blocked is False and viol_is_list and len(violations) == 0:
                gate = '<span class="pill pill-ok">PASS</span>'
            else:
                gate = '<span class="pill pill-neutral">UNKNOWN</span>'
            fc = robj.get("files_changed")
            files_changed = _esc(len(fc)) if isinstance(fc, list) else MDASH
        else:
            gate = MDASH
            files_changed = MDASH
        rows.append(
            "<tr><td class=\"mono\">{id}</td><td>{backend}</td><td>{tier}</td>"
            "<td>{status}</td><td>{gate}</td><td>{fc}</td><td>{usage}</td></tr>".format(
                id=_esc(jid),
                backend=_esc(j.get("backend")),
                tier=_esc(j.get("tier") or j.get("model")),
                status=_pill(status) if status else MDASH,
                gate=gate,
                fc=files_changed,
                usage=_usage_cell(robj),
            ))

    table = (
        '<div class="tablewrap"><table><thead><tr>'
        '<th class="mono">id</th><th>backend</th><th>tier</th><th>status</th>'
        '<th>scope-gate</th><th>files</th><th>usage</th>'
        "</tr></thead><tbody>{}</tbody></table></div>".format("".join(rows)))
    parts.append(table)

    # depends_on edges as a simple textual list (no graph lib)
    dep_lines = []
    for j in jobs:
        deps = j.get("depends_on")
        if isinstance(deps, list) and deps:
            dep_lines.append("<li><code>{jid}</code> &larr; {deps}</li>".format(
                jid=_esc(j.get("id")),
                deps=", ".join("<code>{}</code>".format(_esc(d)) for d in deps)))
    if dep_lines:
        parts.append('<h3 class="sect">depends_on</h3><ul class="deps">{}</ul>'.format(
            "".join(dep_lines)))
    return "\n".join(parts)


def _render_epic_detail(rec):
    parts = []
    if rec.get("state_error"):
        parts.append('<p class="note bad">unparseable epic-state.json: {}</p>'.format(
            _esc(rec["state_error"])))
        return "\n".join(parts)
    if not rec.get("state"):
        parts.append('<p class="note">no epic state.</p>')
        return "\n".join(parts)

    features = rec.get("features") or []
    if features:
        rows = []
        for f in features:
            rows.append(
                "<tr><td class=\"mono\">{id}</td><td>{status}</td>"
                "<td class=\"mono\">{run}</td><td>{att}</td><td>{disp}</td></tr>".format(
                    id=_esc(f.get("id")),
                    status=_pill(f.get("status")) if f.get("status") else MDASH,
                    run=_esc(f.get("run_id")),
                    att=_esc(f.get("attempts")) if f.get("attempts") is not None else MDASH,
                    disp=_esc(f.get("disposition")) if f.get("disposition") is not None else MDASH,
                ))
        parts.append(
            '<div class="tablewrap"><table><thead><tr>'
            '<th class="mono">feature</th><th>status</th><th class="mono">run_id</th>'
            '<th>attempts</th><th>disposition</th>'
            "</tr></thead><tbody>{}</tbody></table></div>".format("".join(rows)))

    # marathon / watch panel (breaker axes) -- counts only, never a fabricated cost
    st = rec["state"]
    auto = st.get("autonomy") if isinstance(st.get("autonomy"), dict) else {}
    if auto:
        metrics = [
            ("total_attempts", st.get("total_attempts")),
            ("no_progress_cycles", st.get("no_progress_cycles")),
            ("resume_count", st.get("resume_count")),
        ]
        watch_on = bool(auto.get("watch"))
        watchers = st.get("watcher_registry") if isinstance(st.get("watcher_registry"), list) else []
        armed = sum(1 for w in watchers if isinstance(w, dict) and w.get("status") == "armed")
        cells = []
        for label, val in metrics:
            if val is not None:
                cells.append('<span class="metric"><b>{v}</b>{l}</span>'.format(
                    v=_esc(val), l=_esc(label)))
        cells.append('<span class="metric"><b>{v}</b>watcher armed</span>'.format(
            v=(_esc(armed) if watch_on else "off")))
        parts.append('<h3 class="sect">marathon / watch</h3><div class="panel">{}</div>'.format(
            "".join(cells)))

    # blocker ledger
    ledger = st.get("blocker_ledger") if isinstance(st.get("blocker_ledger"), list) else []
    if ledger:
        items = []
        for entry in ledger:
            if not isinstance(entry, dict):
                continue
            confirmed = entry.get("confirmed") is True
            tag = ('<span class="pill pill-ok">confirmed</span>' if confirmed
                   else '<span class="pill pill-bad">SUSPECTED</span>')
            fams = entry.get("families_agreeing")
            if isinstance(fams, list):
                fams = ", ".join(str(x) for x in fams)
            evid = entry.get("evidence")
            items.append(
                "<li>{tag} <code>{feat}</code> &middot; category: {cat} &middot; "
                "families: {fams}{evid}</li>".format(
                    tag=tag,
                    feat=_esc(entry.get("feature") or entry.get("feature_id")),
                    cat=_esc(entry.get("category") or entry.get("blocker_category")),
                    fams=_esc(fams),
                    evid=(' &middot; <span class="evid">{}</span>'.format(_esc(evid)) if evid else ""),
                ))
        if items:
            parts.append('<h3 class="sect">blocker ledger</h3><ul class="ledger">{}</ul>'.format(
                "".join(items)))
    return "\n".join(parts)


def _render_card(rec):
    if rec["kind"] == "run":
        counts = "{d}/{t} jobs done".format(d=rec["done"], t=rec["total"])
        title = rec.get("feature")
        detail = _render_run_detail(rec)
    else:
        counts = "{d}/{t} features done".format(d=rec["done"], t=rec["total"])
        title = rec.get("title")
        detail = _render_epic_detail(rec)

    ts = rec.get("display_ts")
    ts_html = ('<span class="stamp">{}</span>'.format(_esc(ts)) if ts else "")
    title_html = ('<span class="title">{}</span>'.format(_esc(title)) if title else "")
    return (
        '<details class="card"><summary>'
        '<span class="kind">{kind}</span>'
        '<span class="rid">{rid}</span>'
        '{title}{pill}'
        '<span class="counts">{counts} {ts}</span>'
        "</summary>"
        '<div class="detail">{detail}</div>'
        "</details>").format(
            kind=_esc(rec["kind"]),
            rid=_esc(rec["id"]),
            title=title_html,
            pill=_pill(rec["status"]),
            counts=_esc(counts),
            ts=ts_html,
            detail=detail)


def render_html(root, live=False):
    # HIGH-1: resolve the execution root ONCE, here, and thread that SAME realpath'd root
    # through every reader. Never render from an unresolved root (defeats containment/TOCTOU).
    root = os.path.realpath(root)
    records = build_records(root)
    if records:
        newest = max(r.get("sort_ts", 0.0) for r in records)
        as_of = _fmt_mtime(newest) if newest else MDASH
    else:
        as_of = MDASH

    if live:
        # MEDIUM-4: NO client-side clock. The stamp is the newest state-file mtime -- a real,
        # file-sourced time recomputed server-side on each poll -- or a bare "live" when none.
        head_stamp = ("live" if as_of == MDASH
                      else "live &middot; data as of {}".format(as_of))
        script = "<script>{}</script>".format(POLL_JS)
    else:
        head_stamp = "snapshot &middot; generated from files as of {}".format(as_of)
        script = ""

    if records:
        body_inner = "\n".join(_render_card(r) for r in records)
    else:
        body_inner = '<div class="empty">no runs yet</div>'

    return (
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>Compound V dashboard</title><style>{css}</style></head>"
        "<body><div class=\"wrap\">"
        "<header class=\"top\"><h1>Compound V &middot; execution dashboard</h1>"
        "<span class=\"stamp\" id=\"page-stamp\">{stamp}</span></header>"
        "<div id=\"dash-body\">{body}</div>"
        "</div>{script}</body></html>").format(
            css=CSS, stamp=head_stamp, body=body_inner, script=script)


# ---------------------------------------------------------------------------
# emit
# ---------------------------------------------------------------------------

def _write_text(path, text):
    """The ONE and ONLY write path in this program (self-test asserts this via AST)."""
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def cmd_emit(args):
    root = args.execution_root
    out = args.out
    html_text = render_html(root, live=False)
    _write_text(out, html_text)
    print(os.path.abspath(out))
    return 0


# ---------------------------------------------------------------------------
# serve -- ephemeral, read-only, loopback-only
# ---------------------------------------------------------------------------

class _ReadOnlyHandler(http.server.BaseHTTPRequestHandler):
    """GET/HEAD only, realpath-contained, allowed-suffix only, no directory index.

    serve_root and html_provider are injected as class attributes by _make_handler.
    Every non-GET/HEAD verb is answered 405 -- there is NO write/upload code path.
    """

    protocol_version = "HTTP/1.1"
    serve_root = ""            # absolute realpath of the execution root
    html_provider = None       # callable -> str (regenerated from files each request)

    # -- silence the default stderr access log (keeps the foreground console clean) --
    def log_message(self, fmt, *a):  # noqa: A003
        return

    # -- read verbs --
    def do_GET(self):  # noqa: N802
        self._handle(write_body=True)

    def do_HEAD(self):  # noqa: N802
        self._handle(write_body=False)

    # -- every mutating / non-read verb is rejected; NO write path exists --
    def _reject(self):
        self.send_error(405, "Method Not Allowed")

    do_POST = _reject
    do_PUT = _reject
    do_DELETE = _reject
    do_PATCH = _reject
    do_OPTIONS = _reject
    do_CONNECT = _reject
    do_TRACE = _reject

    # MEDIUM-5: any verb other than GET/HEAD -- including unknown ones like BREW or a
    # lowercase `post` -- resolves to _reject (405), never BaseHTTPRequestHandler's 501.
    def __getattr__(self, name):
        if name.startswith("do_"):
            return self._reject
        raise AttributeError(name)

    # HIGH-2: reject DNS-rebinding. Only an exact loopback host+port (the one we bound) is
    # accepted; a missing or foreign Host header is a same-origin attempt from a rebinding
    # page and is refused before any file or the dashboard is served.
    def _host_allowed(self):
        host = self.headers.get("Host") if self.headers is not None else None
        if not host:
            return False
        try:
            port = self.server.server_address[1]
        except Exception:  # noqa: BLE001 -- fail-closed if the port is unknowable
            return False
        return host in ("127.0.0.1:{}".format(port), "localhost:{}".format(port))

    def _send_bytes(self, code, content_type, payload, write_body):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if write_body:
            self.wfile.write(payload)

    def _handle(self, write_body):
        # HIGH-2: validate Host before serving ANYTHING (the dashboard or any file).
        if not self._host_allowed():
            self.send_error(403, "Forbidden")
            return

        parsed = urllib.parse.urlsplit(self.path)
        raw = urllib.parse.unquote(parsed.path)
        if "\x00" in raw:
            self.send_error(400, "Bad Request")
            return

        # live dashboard at the root
        if raw in ("", "/"):
            body = self.html_provider().encode("utf-8")
            self._send_bytes(200, "text/html; charset=utf-8", body, write_body)
            return

        rel = raw.lstrip("/")
        # explicit parent-traversal is refused outright
        if any(seg == ".." for seg in rel.split("/")):
            self.send_error(403, "Forbidden")
            return

        root = self.serve_root
        candidate = os.path.realpath(os.path.join(root, rel))
        # realpath containment (shared gate): rejects symlink escapes and any path outside the root
        if not _contained(candidate, root):
            self.send_error(403, "Forbidden")
            return

        suffix = os.path.splitext(candidate)[1].lower()
        if suffix not in ALLOWED_SUFFIXES:
            self.send_error(404, "Not Found")
            return
        if not os.path.isfile(candidate):
            # directories included -> no listing leak
            self.send_error(404, "Not Found")
            return

        try:
            with open(candidate, "rb") as fh:
                payload = fh.read()
        except OSError:
            self.send_error(404, "Not Found")
            return
        ctype = CONTENT_TYPES.get(suffix, "application/octet-stream")
        self._send_bytes(200, ctype, payload, write_body)


def _make_handler(serve_root, html_provider):
    class _H(_ReadOnlyHandler):
        pass
    _H.serve_root = os.path.realpath(serve_root)
    _H.html_provider = staticmethod(html_provider)
    return _H


def _build_server(serve_root, port):
    """Construct a loopback-bound server. Falls back to an OS-chosen free port if `port` is taken."""
    # HIGH-1 (TOCTOU): resolve the root ONCE and thread the SAME realpath'd value into both the
    # request handler AND the HTML provider, so a retargeted root symlink can never make direct
    # file-serving and dashboard rendering operate on two different roots.
    resolved_root = os.path.realpath(serve_root)
    handler = _make_handler(resolved_root, lambda: render_html(resolved_root, live=True))
    server_cls = http.server.ThreadingHTTPServer
    try:
        return server_cls((BIND_HOST, port), handler)
    except OSError:
        # requested port taken -> bind an ephemeral free port (0) and report the chosen one
        return server_cls((BIND_HOST, 0), handler)


def cmd_serve(args):
    root = args.execution_root
    if not os.path.isdir(root):
        print("execution root not found: {}".format(root), file=sys.stderr)
        return 1
    server = _build_server(root, args.port)
    host, port = server.server_address[0], server.server_address[1]
    url = "http://{host}:{port}/".format(host=host, port=port)
    print("Compound V dashboard (read-only, loopback, ephemeral)")
    print("serving {root}".format(root=os.path.realpath(root)))
    print(url)
    print("Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping...")
    finally:
        server.shutdown()
        server.server_close()
    print("stopped. no files were modified.")
    return 0


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

class _FakeServer(object):
    """Minimal stand-in so a bare handler can read the bound port for the Host check."""
    def __init__(self, port=8787):
        self.server_address = ("127.0.0.1", port)


def _invoke_handler(handler_cls, method, path, host="127.0.0.1:8787"):
    """Drive a handler without opening a socket: construct bare, set the request, dispatch.
    `host` defaults to the exact loopback host+port the HIGH-2 Host gate accepts; pass a
    foreign/None host to exercise the DNS-rebinding rejection."""
    h = handler_cls.__new__(handler_cls)
    h.server = _FakeServer(8787)
    h.wfile = io.BytesIO()
    h.rfile = io.BytesIO()
    h.headers = {"Host": host} if host is not None else {}
    h.command = method
    h.path = path
    h.client_address = ("127.0.0.1", 0)
    h.request_version = "HTTP/1.1"
    h.requestline = "{} {} HTTP/1.1".format(method, path)
    getattr(h, "do_" + method)()
    data = h.wfile.getvalue()
    status_line = data.split(b"\r\n", 1)[0].decode("latin-1")
    return int(status_line.split()[1])


def _selftest():
    import tempfile

    failures = []

    def check(cond, msg):
        if not cond:
            failures.append(msg)

    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "execution")
        os.makedirs(root)

        # --- fixture 1: a full run (state + results, measured + unmeasured usage) ---
        run_dir = os.path.join(root, "2099-06-01-fullrun")
        os.makedirs(os.path.join(run_dir, "results"))
        _write_text(os.path.join(run_dir, "manifest.yaml"), (
            "run_id: 2099-06-01-fullrun\n"
            "feature: \"Full run fixture\"\n"
            "jobs:\n"
            "  - id: task-0-base\n"
            "    backend: claude\n"
            "    tier: deep\n"
            "    write_allowed:\n"
            "      - \"src/base.ts\"\n"
            "  - id: task-1-ui\n"
            "    backend: codex\n"
            "    tier: standard\n"
            "    depends_on:\n"
            "      - task-0-base\n"
            "    write_allowed:\n"
            "      - \"src/ui/**\"\n"))
        _write_text(os.path.join(run_dir, "state.json"), json.dumps({
            "run_id": "2099-06-01-fullrun",
            "phase": "MERGED",
            "updated_at": "2099-06-01T12:00:00Z",
            "jobs": {
                "task-0-base": {"status": "done", "isolation": "direct"},
                "task-1-ui": {"status": "done", "isolation": "worktree"},
            },
        }))
        # measured-usage result
        _write_text(os.path.join(run_dir, "results", "task-0-base.json"), json.dumps({
            "status": "success", "blocked": False,
            "files_changed": ["src/base.ts"], "violations": [],
            "summary": "base done", "session_id": "", "worktree": "",
            "exit_code": 0, "failure_class": None, "retry_after_seconds": 0,
            "usage": {"input_tokens": 1234, "output_tokens": 567,
                      "backend": "claude", "measured": True},
        }))
        # unmeasured-usage result (measured false -> must render em-dash, never 0)
        _write_text(os.path.join(run_dir, "results", "task-1-ui.json"), json.dumps({
            "status": "success", "blocked": False,
            "files_changed": ["src/ui/a.ts", "src/ui/b.ts"], "violations": [],
            "summary": "ui done", "session_id": "", "worktree": "",
            "exit_code": 0, "failure_class": None, "retry_after_seconds": 0,
            "usage": {"input_tokens": None, "output_tokens": None,
                      "backend": "codex", "measured": False},
        }))

        # --- fixture 2: manifest-only run (no state.json) ---
        manonly = os.path.join(root, "2099-05-01-manifestonly")
        os.makedirs(manonly)
        _write_text(os.path.join(manonly, "manifest.yaml"), (
            "run_id: 2099-05-01-manifestonly\n"
            "feature: \"Manifest only\"\n"
            "jobs:\n"
            "  - id: task-x\n"
            "    backend: claude\n"
            "    tier: light\n"))

        # --- fixture 3: malformed state.json ---
        badrun = os.path.join(root, "2099-04-01-badjson")
        os.makedirs(badrun)
        _write_text(os.path.join(badrun, "manifest.yaml"),
                    "run_id: 2099-04-01-badjson\nfeature: \"Bad json\"\njobs:\n  - id: task-y\n    backend: claude\n")
        _write_text(os.path.join(badrun, "state.json"), "{ this is not valid json ")

        # --- fixture 4: an epic with a confirmed + a SUSPECTED blocker ---
        epic_dir = os.path.join(root, "epics", "2099-07-01-epicfix")
        os.makedirs(epic_dir)
        _write_text(os.path.join(epic_dir, "epic-state.json"), json.dumps({
            "epic_id": "2099-07-01-epicfix",
            "title": "Epic fixture",
            "status": "running_with_failures",
            "last_progress_at": "2099-07-01T09:00:00Z",
            "features": [
                {"id": "auth", "title": "Auth", "status": "done",
                 "run_id": "2099-07-01-auth", "attempts": 1, "disposition": None},
                {"id": "api", "title": "API", "status": "blocked",
                 "run_id": "2099-07-01-api", "attempts": 2, "disposition": "blocked_external"},
            ],
            "autonomy": {"stance": "marathon", "watch": True, "max_resume_count": 20},
            "total_attempts": 3, "no_progress_cycles": 1, "resume_count": 2,
            "watcher_registry": [{"provider": "cron", "task_id": "t1", "status": "armed"}],
            "blocker_ledger": [
                {"feature": "api", "confirmed": True, "category": "credential",
                 "families_agreeing": ["GPT", "Gemini"], "evidence": "needs a paid API key"},
                {"feature": "extra", "confirmed": False, "category": "infra",
                 "families_agreeing": ["GPT"], "evidence": "single-family only"},
            ],
        }))

        # ---- (1) emit over the fixtures ----
        out = os.path.join(tmp, "dash.html")
        # pin the newest state-file mtime to a fixed epoch to prove the stamp is mtime-derived
        fixed_epoch = 4084992000  # 2099-06-01T00:00:00Z, well beyond "now"
        os.utime(os.path.join(run_dir, "state.json"), (fixed_epoch, fixed_epoch))
        html_text = render_html(root, live=False)
        _write_text(out, html_text)

        # parses as HTML/XML-ish? at minimum well-formed enough for ElementTree tolerance:
        check(html_text.strip().startswith("<!doctype html>"), "emit: missing doctype")
        check(html_text.count("<html") == 1 and "</html>" in html_text, "emit: html wrapper")

        # run + epic ids present
        check("2099-06-01-fullrun" in html_text, "emit: full run id missing")
        check("2099-07-01-epicfix" in html_text, "emit: epic id missing")
        # status pills present
        check("MERGED" in html_text, "emit: run phase pill missing")
        check("running_with_failures" in html_text, "emit: epic status pill missing")
        check('class="pill' in html_text, "emit: no pills rendered")

        # measured usage shows the real number; unmeasured shows an em-dash, never 0
        check("1234" in html_text, "anti-ruflo: measured token count not rendered")
        check("in 1234 / out 567" in html_text, "anti-ruflo: measured usage format")
        check(MDASH in html_text, "anti-ruflo: em-dash placeholder missing")
        # the unmeasured job must NOT render a fabricated 0 usage
        check("in 0 / out 0" not in html_text, "anti-ruflo: fabricated 0 usage rendered")

        # NO percent-progress anywhere in the document (zero '%' chars)
        check("%" not in html_text, "anti-ruflo: '%' present (possible fabricated progress)")

        # no invented timestamp: the 'generated as of' stamp is the pinned file mtime
        expected_stamp = _fmt_mtime(fixed_epoch)
        check(expected_stamp in html_text, "anti-ruflo: stamp not sourced from file mtime")
        # and no current-year ISO wall clock leaked in (fixtures are all year 2099)
        this_year_iso = str(datetime.datetime.utcnow().year) + "-"
        check(this_year_iso not in html_text, "anti-ruflo: current-year timestamp leaked")

        # degrade-safe rendering
        check("no state yet" in html_text, "degrade: manifest-only 'no state yet' missing")
        check("unparseable" in html_text, "degrade: malformed json 'unparseable' missing")

        # blocker ledger: confirmed vs SUSPECTED
        check("confirmed" in html_text, "epic: confirmed blocker label missing")
        check("SUSPECTED" in html_text, "epic: SUSPECTED blocker label missing")
        # watcher-armed panel + breaker axes
        check("watcher armed" in html_text, "epic: watcher panel missing")
        check("total_attempts" in html_text, "epic: breaker axis missing")

        # empty-root honesty
        empty_root = os.path.join(tmp, "empty")
        os.makedirs(empty_root)
        check("no runs yet" in render_html(empty_root, live=False), "degrade: empty root")

        # ---- (2) serve handler security (no live network) ----
        handler_cls = _make_handler(root, lambda: "<html></html>")

        # non-GET methods -> 405
        for m in ("POST", "PUT", "DELETE", "PATCH", "OPTIONS"):
            check(_invoke_handler(handler_cls, m, "/") == 405, "serve: {} not 405".format(m))

        # legit .json under root -> 200
        rel_json = "2099-06-01-fullrun/state.json"
        check(_invoke_handler(handler_cls, "GET", "/" + rel_json) == 200,
              "serve: legit .json not served")
        # root dashboard -> 200
        check(_invoke_handler(handler_cls, "GET", "/") == 200, "serve: root not served")

        # .. traversal -> 403
        check(_invoke_handler(handler_cls, "GET", "/../../etc/passwd") == 403,
              "serve: .. traversal not blocked")
        # absolute-ish path outside allowed suffix -> 404 (contained, wrong suffix)
        check(_invoke_handler(handler_cls, "GET", "/etc/passwd") == 404,
              "serve: outside path not 404")
        # .py / .sh suffix -> 404
        _write_text(os.path.join(run_dir, "evil.py"), "print('x')\n")
        _write_text(os.path.join(run_dir, "evil.sh"), "echo x\n")
        check(_invoke_handler(handler_cls, "GET", "/2099-06-01-fullrun/evil.py") == 404,
              "serve: .py suffix not 404")
        check(_invoke_handler(handler_cls, "GET", "/2099-06-01-fullrun/evil.sh") == 404,
              "serve: .sh suffix not 404")

        # symlink escaping the root -> 403 (realpath containment)
        outside = os.path.join(tmp, "outside_secret.json")
        _write_text(outside, "{}")
        link = os.path.join(run_dir, "escape.json")
        try:
            os.symlink(outside, link)
            check(_invoke_handler(handler_cls, "GET", "/2099-06-01-fullrun/escape.json") == 403,
                  "serve: symlink escape not blocked")
        except (OSError, NotImplementedError):
            pass  # symlinks unsupported on this platform -> skip that assertion only

        # HIGH-2 (DNS-rebinding): a foreign or missing Host -> 403 even for the dashboard root;
        # only the exact loopback host+port the server bound is accepted.
        check(_invoke_handler(handler_cls, "GET", "/", host="evil.example.com:8787") == 403,
              "serve: foreign Host not rejected (DNS-rebinding)")
        check(_invoke_handler(handler_cls, "GET", "/", host=None) == 403,
              "serve: missing Host not rejected")
        check(_invoke_handler(handler_cls, "GET", "/", host="localhost:8787") == 200,
              "serve: exact localhost Host not accepted")

        # MEDIUM-5 (blanket 405): an UNKNOWN verb and a lowercase verb -> 405, never 501.
        check(_invoke_handler(handler_cls, "BREW", "/") == 405, "serve: unknown verb (BREW) not 405")
        check(_invoke_handler(handler_cls, "get", "/") == 405, "serve: lowercase verb not 405")

        # HIGH-1 (render-path containment): a run whose state.json symlinks OUTSIDE the root must
        # be skipped by GET / (render_html), not read+rendered. Direct requests already 403 above.
        leak_run = os.path.join(root, "2099-01-01-leakrun")
        os.makedirs(leak_run)
        _write_text(os.path.join(leak_run, "manifest.yaml"), "jobs: []\n")
        secret = os.path.join(tmp, "render_secret.json")
        _write_text(secret, '{"phase": "RENDER_LEAK_MARKER"}')
        try:
            os.symlink(secret, os.path.join(leak_run, "state.json"))
            leaked = render_html(root, live=False)
            check("RENDER_LEAK_MARKER" not in leaked,
                  "render: out-of-root symlink content leaked via GET /")
        except (OSError, NotImplementedError):
            pass  # symlinks unsupported -> skip this assertion only

        # MEDIUM-4 (no fabricated clock): neither static nor live HTML uses the viewer's clock.
        static_html = render_html(root, live=False)
        live_html = render_html(root, live=True)
        check("new Date(" not in static_html and "toLocaleTimeString" not in static_html,
              "render: static HTML uses a client-side clock (anti-ruflo)")
        check("new Date(" not in live_html and "toLocaleTimeString" not in live_html,
              "render: live HTML uses a client-side clock (anti-ruflo)")

        # MEDIUM-6 (union denominator): 2 manifest jobs + a 3rd state-only done job must never
        # render an impossible "3/2 done"; the denominator unions manifest + state job ids.
        cnt_run = os.path.join(root, "2099-02-02-countrun")
        os.makedirs(os.path.join(cnt_run, "results"))
        _write_text(os.path.join(cnt_run, "manifest.yaml"),
                    "jobs:\n  - id: j1\n  - id: j2\n")
        _write_text(os.path.join(cnt_run, "state.json"),
                    '{"phase": "DISPATCHED", "jobs": {"j1": {"status": "done"}, '
                    '"j2": {"status": "done"}, "j3": {"status": "done"}}}')
        cnt_html = render_html(root, live=False)
        check("3/2" not in cnt_html, "render: impossible progress count (3/2) -- denominator not unioned")

        # ---- server binds loopback ONLY (introspect, no serve_forever, no public socket) ----
        srv = _build_server(root, 0)
        try:
            check(srv.server_address[0] == BIND_HOST, "serve: server not bound to loopback")
        finally:
            srv.server_close()

        # ---- (3) present-only, via source introspection ----
        # Needles built via concatenation so this self-test's own assertion strings
        # do not themselves trip the "present in source" checks.
        src = inspect.getsource(sys.modules[__name__])
        check(("0.0.0" + ".0") not in src, "present-only: public-bind literal in source")
        check(("web" + "browser") not in src, "present-only: browser-launch module referenced")
        check(("sub" + "process") not in src, "present-only: process-spawn module referenced")

        # AST: the only write-mode open() lives inside _write_text
        tree = ast.parse(src)
        write_calls = []
        wt_range = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_write_text":
                wt_range = (node.lineno, node.end_lineno)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
                mode = None
                if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                    mode = node.args[1].value
                for kw in node.keywords:
                    if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                        mode = kw.value.value
                if isinstance(mode, str) and ("w" in mode or "a" in mode):
                    write_calls.append(node.lineno)
        check(len(write_calls) == 1, "present-only: expected exactly one write-mode open()")
        if write_calls and wt_range:
            ln = write_calls[0]
            check(wt_range[0] <= ln <= wt_range[1],
                  "present-only: write-mode open() outside _write_text")

    if failures:
        print("SELFTEST FAILED ({} issue(s)):".format(len(failures)))
        for f in failures:
            print("  - " + f)
        return 1
    print("SELFTEST PASSED")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="compound-v-dashboard.py",
        description="Present-only, read-only observability dashboard over "
                    "docs/superpowers/execution/** (emit a static snapshot or serve an "
                    "ephemeral loopback-only live viewer).")
    parser.add_argument("--selftest", action="store_true",
                        help="run the built-in self-test and exit")
    sub = parser.add_subparsers(dest="cmd")

    p_emit = sub.add_parser("emit", help="write a self-contained HTML snapshot; print its path")
    p_emit.add_argument("--execution-root", default=DEFAULT_EXECUTION_ROOT,
                        help="execution root to read (default: %(default)s)")
    p_emit.add_argument("--out", default=DEFAULT_OUT,
                        help="output HTML path (default: %(default)s)")

    p_serve = sub.add_parser("serve", help="ephemeral read-only loopback live viewer")
    p_serve.add_argument("--execution-root", default=DEFAULT_EXECUTION_ROOT,
                         help="execution root to serve (default: %(default)s)")
    p_serve.add_argument("--port", type=int, default=DEFAULT_PORT,
                         help="preferred port (default: %(default)s; falls back to a free port)")

    args = parser.parse_args(argv)

    if args.selftest:
        return _selftest()
    if args.cmd == "emit":
        return cmd_emit(args)
    if args.cmd == "serve":
        return cmd_serve(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
