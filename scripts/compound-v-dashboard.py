#!/usr/bin/env python3
"""
Compound V execution-state reader -- PRESENT-ONLY, read-only.

Reads the run/epic JSON under docs/superpowers/execution/** WITHOUT a daemon, a persistent
service, or any write/control surface. One subcommand + a self-test:

  * resume -- print one line naming unfinished runs/epics (the SessionStart banner input,
            also consumed by the PreCompact / PostCompact hooks and the triage nudge).

For a view of a run, use `/v:status` and the harness's native `/workflows` (running Compound V
dispatches) and `/tasks` (state.json / epic-state.json progress) surfaces. The static HTML
snapshot this file once emitted was removed together with the dashboard command that was its
only caller.

Design posture -- "observe in the UI, act via the CLI": there is NO merge/kill/retry/edit
control anywhere. Enforcement stays with the git-derived gates; this reader only reflects.

ANTI-RUFLO (the identity -- a reader that does not lie):
  * Report ONLY what is in the state files. NO fabricated progress percentages -- only real
    counts (N/M jobs|features done).
  * Every timestamp comes from a state-file field (updated_at / started_at / last_progress_at /
    recorded_at) or a real file mtime -- never datetime.now().

DEGRADE-SAFE:
  * A run dir with only manifest.yaml (no state.json) -> an honest "NO STATE" record.
  * Malformed/partial JSON -> an "UNPARSEABLE" status on that record, never a crash.
  * Empty execution root -> nothing at all.

Pure Python 3.9-safe stdlib only (json, argparse, os, inspect, ast, datetime). No
third-party imports. LANG=C clean (all file I/O is explicitly utf-8; the source is ASCII-only).

Run the self-test with:  python3 scripts/compound-v-dashboard.py --selftest
"""

import argparse
import ast
import datetime
import inspect
import json
import os
import sys
import time

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_EXECUTION_ROOT = "docs/superpowers/execution"

DONE_JOB_STATES = ("done", "success")

# --- resume context (v2.19) --------------------------------------------------
# A compaction re-injects the SessionStart banner but NOT the agent's position in
# a pipeline. `resume` answers the one question a just-compacted agent cannot
# answer from context alone: "was I in the middle of a Compound V run?"
# Read-only, present-only, degrade-silent -- the same contract as the rest of
# this script.
TERMINAL_RUN_PHASES = ("merged",)
TERMINAL_EPIC_STATUSES = ("done", "completed")
# Freshness window. The two errors are NOT symmetric: a false positive costs one
# line of banner noise, a false negative costs exactly the amnesia this exists to
# fix. So the window is generous rather than tight -- it exists only to stop a
# long-abandoned run nagging forever, not to be a precise liveness signal.
DEFAULT_RESUME_MAX_AGE_HOURS = 72.0
# The banner is a single line. Cap how much of it one feature may claim.
RESUME_MAX_RECORDS = 2


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

    `root` MUST be an os.path.realpath'd absolute directory (`active_records` resolves it
    once): every reader below is realpath-contained to this exact root.
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
# Self-test
# ---------------------------------------------------------------------------


def _selftest():
    import tempfile

    failures = []

    def _fx_write(path, text):
        """The ONE and ONLY write path in this program -- a SELF-TEST FIXTURE writer.
        The AST assertion below proves nothing outside it ever opens a file for
        writing, which is what "present-only, read-only" means here."""
        parent = os.path.dirname(os.path.abspath(path))
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def check(cond, msg):
        if not cond:
            failures.append(msg)

    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "execution")
        os.makedirs(root)

        # --- fixture 1: a full run (state + results, measured + unmeasured usage) ---
        run_dir = os.path.join(root, "2099-06-01-fullrun")
        os.makedirs(os.path.join(run_dir, "results"))
        _fx_write(os.path.join(run_dir, "manifest.yaml"), (
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
        _fx_write(os.path.join(run_dir, "state.json"), json.dumps({
            "run_id": "2099-06-01-fullrun",
            "phase": "MERGED",
            "updated_at": "2099-06-01T12:00:00Z",
            "jobs": {
                "task-0-base": {"status": "done", "isolation": "direct"},
                "task-1-ui": {"status": "done", "isolation": "worktree"},
            },
        }))
        # measured-usage result
        _fx_write(os.path.join(run_dir, "results", "task-0-base.json"), json.dumps({
            "status": "success", "blocked": False,
            "files_changed": ["src/base.ts"], "violations": [],
            "summary": "base done", "session_id": "", "worktree": "",
            "exit_code": 0, "failure_class": None, "retry_after_seconds": 0,
            "usage": {"input_tokens": 1234, "output_tokens": 567,
                      "backend": "claude", "measured": True},
        }))
        # unmeasured-usage result (measured false -> must render em-dash, never 0)
        _fx_write(os.path.join(run_dir, "results", "task-1-ui.json"), json.dumps({
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
        _fx_write(os.path.join(manonly, "manifest.yaml"), (
            "run_id: 2099-05-01-manifestonly\n"
            "feature: \"Manifest only\"\n"
            "jobs:\n"
            "  - id: task-x\n"
            "    backend: claude\n"
            "    tier: light\n"))

        # --- fixture 3: malformed state.json ---
        badrun = os.path.join(root, "2099-04-01-badjson")
        os.makedirs(badrun)
        _fx_write(os.path.join(badrun, "manifest.yaml"),
                    "run_id: 2099-04-01-badjson\nfeature: \"Bad json\"\njobs:\n  - id: task-y\n    backend: claude\n")
        _fx_write(os.path.join(badrun, "state.json"), "{ this is not valid json ")

        # --- fixture 4: an epic with a confirmed + a SUSPECTED blocker ---
        epic_dir = os.path.join(root, "epics", "2099-07-01-epicfix")
        os.makedirs(epic_dir)
        _fx_write(os.path.join(epic_dir, "epic-state.json"), json.dumps({
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

        # ---- (1) read the fixtures back as records ----
        recs = {r["id"]: r for r in build_records(os.path.realpath(root))}

        check("2099-06-01-fullrun" in recs, "read: full run missing")
        check("2099-07-01-epicfix" in recs, "read: epic missing")
        full = recs.get("2099-06-01-fullrun") or {}
        check(full.get("kind") == "run", "read: full run not typed as a run")
        check(full.get("status") == "MERGED", "read: run phase not carried")
        check((full.get("done"), full.get("total")) == (2, 2),
              "read: run job counts wrong, got "
              + repr((full.get("done"), full.get("total"))))
        check(full.get("display_ts") == "2099-06-01T12:00:00Z",
              "anti-ruflo: display_ts not sourced from the state file")
        # usage is carried verbatim from results/*.json -- measured stays measured,
        # unmeasured stays null and is NEVER coerced to a fabricated 0.
        r0 = ((full.get("results") or {}).get("task-0-base") or {}).get("obj") or {}
        r1 = ((full.get("results") or {}).get("task-1-ui") or {}).get("obj") or {}
        check(r0.get("usage", {}).get("input_tokens") == 1234,
              "anti-ruflo: measured token count not read back")
        check(r1.get("usage", {}).get("measured") is False
              and r1.get("usage", {}).get("input_tokens") is None,
              "anti-ruflo: unmeasured usage must stay null, never 0")

        epic = recs.get("2099-07-01-epicfix") or {}
        check(epic.get("kind") == "epic", "read: epic not typed as an epic")
        check(epic.get("status") == "running_with_failures", "read: epic status not carried")
        check((epic.get("done"), epic.get("total")) == (1, 2),
              "read: epic feature counts wrong")
        ledger = (epic.get("state") or {}).get("blocker_ledger") or []
        check(len(ledger) == 2 and ledger[0].get("confirmed") is True
              and ledger[1].get("confirmed") is False,
              "read: blocker ledger confirmed/suspected not carried")

        # degrade-safe reading
        check((recs.get("2099-05-01-manifestonly") or {}).get("status") == "NO STATE",
              "degrade: manifest-only run must read as NO STATE")
        check((recs.get("2099-04-01-badjson") or {}).get("status") == "UNPARSEABLE",
              "degrade: malformed state.json must read as UNPARSEABLE")

        # empty-root honesty
        empty_root = os.path.join(tmp, "empty")
        os.makedirs(empty_root)
        check(build_records(os.path.realpath(empty_root)) == [], "degrade: empty root")

        # HIGH-1 (containment): a run whose state.json symlinks OUTSIDE the root must be
        # skipped (never read), not followed.
        leak_run = os.path.join(root, "2099-01-01-leakrun")
        os.makedirs(leak_run)
        _fx_write(os.path.join(leak_run, "manifest.yaml"), "jobs: []\n")
        secret = os.path.join(tmp, "render_secret.json")
        _fx_write(secret, '{"phase": "READ_LEAK_MARKER"}')
        try:
            os.symlink(secret, os.path.join(leak_run, "state.json"))
            leaked = build_records(os.path.realpath(root))
            check(all(r.get("status") != "READ_LEAK_MARKER" for r in leaked),
                  "read: out-of-root symlink content followed")
        except (OSError, NotImplementedError):
            pass  # symlinks unsupported -> skip this assertion only

        # MEDIUM-6 (union denominator): 2 manifest jobs + a 3rd state-only done job must never
        # produce an impossible "3/2 done"; the denominator unions manifest + state job ids.
        cnt_run = os.path.join(root, "2099-02-02-countrun")
        os.makedirs(os.path.join(cnt_run, "results"))
        _fx_write(os.path.join(cnt_run, "manifest.yaml"),
                  "jobs:\n  - id: j1\n  - id: j2\n")
        _fx_write(os.path.join(cnt_run, "state.json"),
                  '{"phase": "DISPATCHED", "jobs": {"j1": {"status": "done"}, '
                  '"j2": {"status": "done"}, "j3": {"status": "done"}}}')
        cnt = [r for r in build_records(os.path.realpath(root))
               if r.get("id") == "2099-02-02-countrun"][0]
        check(cnt["done"] <= cnt["total"] and cnt["total"] == 3,
              "read: impossible progress count -- denominator not unioned")

        # ---- present-only, via source introspection ----
        # Needles built via concatenation so this self-test's own assertion strings
        # do not themselves trip the "present in source" checks.
        src = inspect.getsource(sys.modules[__name__])
        check(("0.0.0" + ".0") not in src, "present-only: public-bind literal in source")
        check(("web" + "browser") not in src, "present-only: browser-launch module referenced")
        check(("sub" + "process") not in src, "present-only: process-spawn module referenced")

        # AST: the only write-mode open() lives inside the self-test's fixture writer
        tree = ast.parse(src)
        write_calls = []
        wt_range = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_fx_write":
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
                  "present-only: write-mode open() outside the fixture writer")

    # -----------------------------------------------------------------
    # resume context (v2.19) -- the anti-amnesia banner input
    # -----------------------------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        rroot = os.path.join(tmp, "execution")
        os.makedirs(rroot)
        now = 1000000000.0

        def _iso(hours_ago):
            dt = datetime.datetime.fromtimestamp(now - hours_ago * 3600.0,
                                                 datetime.timezone.utc)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        def _mkrun(name, phase, hours_ago, jobs=2, done=1, with_state=True):
            d = os.path.join(rroot, name)
            os.makedirs(d)
            _fx_write(os.path.join(d, "manifest.yaml"),
                        "run_id: " + name + "\njobs:\n"
                        + "".join("  - id: j%d\n" % i for i in range(jobs)))
            if with_state:
                _fx_write(os.path.join(d, "state.json"), json.dumps({
                    "run_id": name, "phase": phase, "updated_at": _iso(hours_ago),
                    "jobs": dict(("j%d" % i,
                                  {"status": "done" if i < done else "pending"})
                                 for i in range(jobs)),
                }))

        # empty root -> silent, and never raises
        check(active_records(rroot, now=now) == [], "resume: empty root must be empty")
        check(format_resume_line([]) == "", "resume: empty records -> empty line")

        _mkrun("2099-01-01-live", "DISPATCHED", 2.0)          # fresh + unfinished
        _mkrun("2099-01-02-merged", "MERGED", 1.0)            # fresh but finished
        _mkrun("2099-01-03-oldopen", "DISPATCHED", 500.0)     # unfinished but stale
        _mkrun("2099-01-04-alldone", "PARTITION_VERIFIED", 2.0, done=3)  # fresh, jobs all done
        _mkrun("2099-01-05-halted", "BLOCKED", 2.0)          # fresh, halted for a human
        _mkrun("2099-01-04-nostate", "", 0.0, with_state=False)  # no recorded ts

        ids = sorted(r["id"] for r in active_records(rroot, now=now))
        check(ids == ["2099-01-01-live", "2099-01-04-alldone", "2099-01-05-halted"],
              "resume: the banner names every fresh unfinished run, got " + repr(ids))
        # The triage hook's question is narrower: a run whose jobs are all
        # terminal waits for a person and a BLOCKED run was halted for one;
        # neither is mid-pipeline for a NEW request (stage-1 finding 45/47).
        ids_open = [r["id"] for r in active_records(rroot, now=now, open_jobs_only=True)]
        check(ids_open == ["2099-01-01-live"],
              "resume --open-jobs: only the run with a pending job, got " + repr(ids_open))

        # REGRESSION (found live): freshness must come from the RECORDED timestamp,
        # never a file mtime -- git rewrites mtimes on clone/branch-switch, which
        # would make every historical run look seconds old on a fresh checkout.
        for dirpath, _dn, fns in os.walk(rroot):
            for fn in fns:
                os.utime(os.path.join(dirpath, fn), (now, now))
        ids2 = [r["id"] for r in active_records(rroot, now=now, open_jobs_only=True)]
        check(ids2 == ["2099-01-01-live"],
              "resume: mtime touch must not resurrect stale/untimestamped runs, got "
              + repr(ids2))

        line = format_resume_line(active_records(rroot, now=now, open_jobs_only=True))
        check("2099-01-01-live" in line, "resume: line must name the active run")
        check("DISPATCHED" in line and "1/2" in line,
              "resume: line must carry phase and job progress")
        check("/v:status" in line, "resume: line must name the recovery command")

        # epics: terminal status excluded, live status included
        for name, status, hours in (("2099-02-01-epicrun", "running", 3.0),
                                    ("2099-02-02-epicdone", "done", 3.0)):
            d = os.path.join(rroot, name)
            os.makedirs(d)
            _fx_write(os.path.join(d, "epic-state.json"), json.dumps({
                "epic_id": name, "status": status, "updated_at": _iso(hours),
                "features": [{"id": "f1", "status": "done"},
                             {"id": "f2", "status": "pending"}],
            }))
        eids = [r["id"] for r in active_records(rroot, now=now) if r["kind"] == "epic"]
        check(eids == ["2099-02-01-epicrun"],
              "resume: only the non-terminal epic is active, got " + repr(eids))

        # the banner is one line: cap records and say how many were withheld
        _mkrun("2099-01-05-live2", "COLLECTED", 4.0)
        many = active_records(rroot, now=now)
        check(len(many) > RESUME_MAX_RECORDS,
              "resume: fixture should exceed the cap for the +N check")
        capped = format_resume_line(many)
        check("+{} more".format(len(many) - RESUME_MAX_RECORDS) in capped,
              "resume: over-cap records must be counted, not dropped silently")

    if failures:
        print("SELFTEST FAILED ({} issue(s)):".format(len(failures)))
        for f in failures:
            print("  - " + f)
        return 1
    print("SELFTEST PASSED")
    return 0


# ---------------------------------------------------------------------------
# Resume context (read-only; consumed by the SessionStart banner)
# ---------------------------------------------------------------------------

def _is_unfinished(rec):
    """True when a record represents work that still has a next step."""
    status = str(rec.get("status") or "").strip().lower()
    if rec.get("kind") == "epic":
        return status not in TERMINAL_EPIC_STATUSES
    # A run dir with a manifest but no state.json is materialized-but-never-run.
    # That is unfinished in the most literal sense, so it counts.
    return status not in TERMINAL_RUN_PHASES


def _parse_ts(raw):
    """ISO-8601 -> epoch seconds (UTC). None when absent or unparseable."""
    if not raw:
        return None
    text = str(raw).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.timestamp()


def _age_hours(rec, now):
    """Age from the RECORDED timestamp only -- never from an mtime.

    `sort_ts` is a file mtime, and git rewrites mtimes on every clone and branch
    switch, which would make every historical run in the repo look seconds old.
    A record with no recorded timestamp is therefore treated as unknown-age and
    stays silent: we would rather say nothing than fabricate freshness out of a
    filesystem artifact.
    """
    ts = _parse_ts(rec.get("display_ts"))
    if ts is None:
        return None
    return max(0.0, (now - ts) / 3600.0)


def _fmt_age(hours):
    if hours is None:
        return "age unknown"
    if hours < 1.0:
        return "updated <1h ago"
    if hours < 48.0:
        return "updated {}h ago".format(int(round(hours)))
    return "updated {}d ago".format(int(hours // 24))


OPEN_JOB_STATES = ("pending", "running", "dispatched", "queued")


def _has_open_job(rec):
    """True when a RUN still has a job the pipeline itself may move next.

    The banner's notion of unfinished ("phase is not merged") is the right one
    for a human resuming work. It is the wrong one for deciding whether a NEW
    request may be sized: a run whose jobs are all terminal is waiting for a
    person, a BLOCKED run has been halted for one, and neither is "mid-pipeline"
    in the sense that a fresh triage record could contaminate it. On 2026-09-03
    five superseded runs of one night kept the triage hook silent for the whole
    repository (stage-1 finding 45/47). Epics are left to the caller's window.
    """
    if rec.get("kind") == "epic":
        return True
    if str(rec.get("status") or "").strip().lower() == "blocked":
        return False
    state_jobs = rec.get("state_jobs") or {}
    if not state_jobs:
        # materialized but never run: nothing is moving, nothing to contaminate
        return False
    return any(isinstance(jv, dict)
               and str(jv.get("status") or "").strip().lower() in OPEN_JOB_STATES
               for jv in state_jobs.values())


def active_records(root, max_age_hours=DEFAULT_RESUME_MAX_AGE_HOURS, now=None,
                   open_jobs_only=False):
    """Unfinished runs/epics touched within `max_age_hours`, newest first.

    `open_jobs_only` narrows to work the pipeline may still move by itself
    (see `_has_open_job`); the triage hook asks with it, the banner without.
    """
    now = time.time() if now is None else now
    out = []
    for rec in build_records(os.path.realpath(root)):
        if not _is_unfinished(rec):
            continue
        if open_jobs_only and not _has_open_job(rec):
            continue
        age = _age_hours(rec, now)
        if age is None or age > max_age_hours:
            continue
        rec = dict(rec)
        rec["age_hours"] = age
        out.append(rec)
    return out


def format_resume_line(records):
    """One terse line for the SessionStart banner. Empty string when nothing is active."""
    if not records:
        return ""
    parts = []
    for rec in records[:RESUME_MAX_RECORDS]:
        label = "epic" if rec.get("kind") == "epic" else "run"
        parts.append("{} {} \u2014 {}, {}/{} {} done, {}".format(
            label, rec.get("id"), rec.get("status"),
            rec.get("done", 0), rec.get("total", 0),
            "features" if label == "epic" else "jobs",
            _fmt_age(rec.get("age_hours")),
        ))
    more = len(records) - len(parts)
    if more > 0:
        parts.append("+{} more".format(more))
    return ("\u23f8 UNFINISHED COMPOUND V WORK: " + "; ".join(parts)
            + ". You are mid-pipeline: run /v:status (and /v:resume <run-id>) "
              "before starting anything new. Earlier compliance in this session "
              "does NOT carry -- a rescope re-enters the pipeline at the top.")


def cmd_resume(args):
    records = active_records(args.execution_root, args.max_age_hours,
                             open_jobs_only=bool(getattr(args, "open_jobs", False)))
    if args.as_json:
        payload = [{k: r.get(k) for k in
                    ("kind", "id", "status", "done", "total", "age_hours", "display_ts")}
                   for r in records]
        print(json.dumps({"active": payload}, indent=2, sort_keys=True))
        return 0
    line = format_resume_line(records)
    if line:
        print(line)
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="compound-v-dashboard.py",
        description="Present-only, read-only reader over docs/superpowers/execution/** "
                    "(for a view of a run use /v:status and the harness's native "
                    "/workflows and /tasks surfaces).")
    parser.add_argument("--selftest", action="store_true",
                        help="run the built-in self-test and exit")
    sub = parser.add_subparsers(dest="cmd")

    p_resume = sub.add_parser("resume",
                              help="print one line naming unfinished runs/epics (banner input)")
    p_resume.add_argument("--execution-root", default=DEFAULT_EXECUTION_ROOT,
                          help="execution root to read (default: %(default)s)")
    p_resume.add_argument("--max-age-hours", type=float,
                          default=DEFAULT_RESUME_MAX_AGE_HOURS,
                          help="ignore work older than this (default: %(default)s)")
    p_resume.add_argument("--json", dest="as_json", action="store_true",
                          help="machine-readable output")
    p_resume.add_argument("--open-jobs", dest="open_jobs", action="store_true",
                          help="only work the pipeline may still move by itself: a run with a "
                               "pending/running job and not BLOCKED (the triage hook's question)")

    args = parser.parse_args(argv)

    if args.selftest:
        return _selftest()
    if args.cmd == "resume":
        return cmd_resume(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
