#!/usr/bin/env python3
"""
Compound V worker scorecard — data-driven routing signal (PRD §8 / v1.1).

Routing today is a STATIC guess (routing-policy.md): a task-type maps to a fixed
backend/tier. This script makes it ADAPTIVE: it tallies how each backend has ACTUALLY
performed per task-type in THIS repo and emits a `health` signal the router consults
before trusting the static default. It does NOT decide on its own and NEVER fabricates
cost/token metrics — it only counts real, git-derived job outcomes (anti-ruflo).

TWO sources feed the tally, unioned (v3.4: native-first):
  1. --from-runs <execution_root> (PRIMARY, regenerated from files each run): every
     manifest.yaml `jobs[]` entry (id, type, backend, tier/model) under the execution
     root, joined against that same run's `results/<job-id>.json` (status, blocked —
     the SAME git-derived job_result the dashboard reads). A job with no matching
     results file (never dispatched, or still running) is simply skipped, never
     fabricated as a zero.
  2. memory/task-outcomes.jsonl (LEGACY, machine-appended, kept for continuity):
     {"run_id","type","backend","model","status","blocked","rework_rounds"}

Output (memory/worker-performance.jsonl, one object per (backend, type)):
  {"backend","type","total","success","blocked","error","timeout",
   "avg_rework","block_rate","error_rate","success_rate","health"}

`health` ∈ insufficient_data | healthy | watch | unhealthy. A backend that, for a given
task-type, blocks or needs rework too often is `unhealthy`; the router then prefers the
alternative (or escalates) instead of blindly following the static default.

Usage:
  compound-v-scorecard.py --update [--from-runs docs/superpowers/execution] [--outcomes P] [--out P]
  compound-v-scorecard.py --query --backend codex --type large_isolated [--outcomes P]
  compound-v-scorecard.py --selftest

Python 3.9-safe, stdlib only. NEVER reads/writes routing-lessons.md (human-curated).
"""

import argparse
import json
import os
import sys

MIN_SAMPLES = 5  # below this we cannot judge a backend fairly -> insufficient_data

_REPO_MEM = os.path.join("docs", "superpowers", "memory")
DEFAULT_OUTCOMES = os.path.join(_REPO_MEM, "task-outcomes.jsonl")
DEFAULT_OUT = os.path.join(_REPO_MEM, "worker-performance.jsonl")


def _read_outcomes(path):
    """Yield outcome dicts from a JSONL file; tolerate blank/garbage lines."""
    recs = []
    if not os.path.exists(path):
        return recs
    with open(path, "r", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict) and obj.get("backend") and obj.get("type"):
                recs.append(obj)
    return recs


# ---------------------------------------------------------------------------
# --from-runs: manifest jobs x results/*.json (v3.4: native-first)
# ---------------------------------------------------------------------------
# A tiny, purpose-built manifest reader -- not a general YAML parser. It only needs
# to pull scalar fields off `jobs:` block-sequence-of-maps entries, the one shape
# every Compound V manifest actually uses (see examples/manifest.example.yaml).

def _scalar(val):
    val = val.strip()
    if not val:
        return None
    if val[0] in "\"'":
        quote = val[0]
        end = val.find(quote, 1)
        return val[1:end] if end != -1 else val[1:]
    hpos = val.find(" #")
    if hpos != -1:
        val = val[:hpos].strip()
    return val


def _parse_manifest_jobs(text):
    """Return (run_id, [job_dict, ...]) from a manifest.yaml's text.

    Recognizes a top-level `run_id: ...` scalar and a top-level `jobs:` block
    sequence of maps (`  - id: ...` followed by more-indented `key: value` lines),
    matching the shape every manifest.yaml in this repo is generated in. Anything
    it does not recognize is silently skipped -- degrade-safe, never a crash.
    """
    run_id = None
    jobs = []
    lines = text.split("\n")
    i = 0
    n = len(lines)
    in_jobs = False
    jobs_indent = None
    cur = None
    cur_indent = None
    while i < n:
        raw = lines[i]
        i += 1
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        stripped = raw.strip()

        if not in_jobs:
            if stripped.startswith("run_id:"):
                run_id = _scalar(stripped[len("run_id:"):])
            elif stripped == "jobs:" and indent == 0:
                in_jobs = True
                jobs_indent = None
            continue

        # inside the jobs: block
        if indent == 0 and not stripped.startswith("- "):
            # dedented back to top level -> jobs block ended
            in_jobs = False
            if cur is not None:
                jobs.append(cur)
                cur = None
            if stripped.startswith("run_id:"):
                run_id = _scalar(stripped[len("run_id:"):])
            continue

        if stripped.startswith("- "):
            if jobs_indent is None:
                jobs_indent = indent
            if indent != jobs_indent:
                # a nested sequence (e.g. write_allowed:/depends_on: items) -- part
                # of the current job entry, not a new one; ignore its scalar items.
                continue
            if cur is not None:
                jobs.append(cur)
            cur = {}
            cur_indent = indent + 2
            key, _, val = stripped[2:].partition(":")
            key = key.strip()
            val = val.strip()
            if val:
                cur[key] = _scalar(val)
            continue

        # a `key: value` line belonging to the current job entry
        if cur is not None and indent >= cur_indent and ":" in stripped:
            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip()
            if val and val not in ("[]",) and not val.startswith("["):
                cur[key] = _scalar(val)
            # sequence-valued keys (write_allowed:, depends_on:) are irrelevant to
            # the scorecard and intentionally left unset.

    if in_jobs and cur is not None:
        jobs.append(cur)
    return run_id, jobs


def _read_manifest_jobs(manifest_path):
    try:
        with open(manifest_path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return None, []
    try:
        return _parse_manifest_jobs(text)
    except Exception:  # noqa: BLE001 -- degrade-safe: an unparseable manifest yields nothing
        return None, []


def _read_result(results_dir, job_id):
    path = os.path.join(results_dir, "{}.json".format(job_id))
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            obj = json.load(fh)
    except (OSError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def records_from_runs(execution_root):
    """Walk `execution_root`; every (manifest job, matching results/*.json) pair
    becomes one outcome record, in the same shape `_read_outcomes` produces.

    A job never dispatched (no results file yet) or an unparseable result is
    skipped -- never counted as a fabricated success or failure.
    """
    out = []
    if not os.path.isdir(execution_root):
        return out
    for dirpath, _dirnames, filenames in os.walk(execution_root):
        if "manifest.yaml" not in filenames:
            continue
        manifest_path = os.path.join(dirpath, "manifest.yaml")
        run_id, jobs = _read_manifest_jobs(manifest_path)
        if not jobs:
            continue
        run_id = run_id or os.path.basename(dirpath.rstrip(os.sep))
        results_dir = os.path.join(dirpath, "results")
        for job in jobs:
            job_id = job.get("id")
            backend = job.get("backend")
            typ = job.get("type")
            if not job_id or not backend or not typ:
                continue
            result = _read_result(results_dir, job_id)
            if result is None:
                continue
            status = result.get("status")
            if status not in ("success", "blocked", "error", "timeout"):
                continue
            out.append({
                "run_id": run_id,
                "type": typ,
                "backend": backend,
                "model": job.get("model") or job.get("tier"),
                "status": status,
                "blocked": bool(result.get("blocked")),
                # rework_rounds is not part of job_result -- absent from this source
                # means "not tracked here", left at 0 rather than fabricated.
                "rework_rounds": 0,
            })
    return out


def _health(total, blocked, errors, avg_rework):
    if total < MIN_SAMPLES:
        return "insufficient_data"
    block_rate = blocked / total
    error_rate = errors / total
    if block_rate > 0.30 or error_rate > 0.30 or avg_rework > 1.5:
        return "unhealthy"
    if block_rate > 0.10 or error_rate > 0.10 or avg_rework > 0.5:
        return "watch"
    return "healthy"


def aggregate(records):
    """Return a list of per-(backend,type) scorecard rows."""
    buckets = {}  # (backend, type) -> running tally
    for r in records:
        key = (str(r.get("backend")), str(r.get("type")))
        b = buckets.setdefault(key, {"total": 0, "success": 0, "blocked": 0,
                                     "error": 0, "timeout": 0, "rework": 0})
        b["total"] += 1
        status = r.get("status")
        if status in ("success", "blocked", "error", "timeout"):
            b[status] += 1
        # `blocked` boolean is the authoritative scope verdict; count it even if the
        # status string disagrees (defensive).
        if r.get("blocked") is True and status != "blocked":
            b["blocked"] += 1
        try:
            b["rework"] += int(r.get("rework_rounds") or 0)
        except (TypeError, ValueError):
            pass

    rows = []
    for (backend, typ), b in sorted(buckets.items()):
        total = b["total"]
        errors = b["error"] + b["timeout"]
        avg_rework = round(b["rework"] / total, 3) if total else 0.0
        rows.append({
            "backend": backend,
            "type": typ,
            "total": total,
            "success": b["success"],
            "blocked": b["blocked"],
            "error": b["error"],
            "timeout": b["timeout"],
            "avg_rework": avg_rework,
            "block_rate": round(b["blocked"] / total, 3) if total else 0.0,
            "error_rate": round(errors / total, 3) if total else 0.0,
            "success_rate": round(b["success"] / total, 3) if total else 0.0,
            "health": _health(total, b["blocked"], errors, avg_rework),
        })
    return rows


def query(records, backend, typ):
    for row in aggregate(records):
        if row["backend"] == backend and row["type"] == typ:
            return row
    # No data for this pair yet.
    return {"backend": backend, "type": typ, "total": 0, "success": 0, "blocked": 0,
            "error": 0, "timeout": 0, "avg_rework": 0.0, "block_rate": 0.0,
            "error_rate": 0.0, "success_rate": 0.0, "health": "insufficient_data"}


def _selftest():
    ok = 0
    fail = 0

    def check(name, cond):
        nonlocal ok, fail
        if cond:
            ok += 1
        else:
            fail += 1
            print("  FAIL %s" % name)

    def rec(backend, typ, status, blocked=False, rework=0):
        return {"run_id": "r", "type": typ, "backend": backend, "model": "m",
                "status": status, "blocked": blocked, "rework_rounds": rework}

    # codex on large_isolated: 8 success, 1 blocked, 2 error (11 total) + some rework
    recs = []
    recs += [rec("codex", "large_isolated", "success") for _ in range(8)]
    recs += [rec("codex", "large_isolated", "blocked", blocked=True)]
    recs += [rec("codex", "large_isolated", "error") for _ in range(2)]
    recs += [rec("codex", "large_isolated", "success", rework=2) for _ in range(2)]  # extra
    # opus on core_feature: 10 clean
    recs += [rec("claude", "core_feature", "success") for _ in range(10)]
    # too-few-samples bucket
    recs += [rec("claude", "docs", "success") for _ in range(2)]

    q = query(recs, "codex", "large_isolated")
    check("codex total", q["total"] == 13)
    check("codex blocked counted", q["blocked"] == 1)
    check("codex error_rate", abs(q["error_rate"] - round(2 / 13, 3)) < 1e-9)
    check("codex health unhealthy-or-watch", q["health"] in ("watch", "unhealthy"))
    q2 = query(recs, "claude", "core_feature")
    check("claude healthy", q2["health"] == "healthy")
    q3 = query(recs, "claude", "docs")
    check("few samples -> insufficient_data", q3["health"] == "insufficient_data")
    q4 = query(recs, "codex", "never_seen")
    check("unseen pair -> insufficient_data", q4["health"] == "insufficient_data" and q4["total"] == 0)
    # a heavily-blocked backend is unhealthy
    bad = [rec("codex", "x", "blocked", blocked=True) for _ in range(6)]
    check("all-blocked -> unhealthy", query(bad, "codex", "x")["health"] == "unhealthy")

    # --- records_from_runs: manifest jobs x results/*.json, over a sandbox run dir ---
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp(prefix="cv-scorecard-selftest-")
    try:
        run_dir = os.path.join(tmp, "2099-01-01-sandbox")
        os.makedirs(os.path.join(run_dir, "results"))
        with open(os.path.join(run_dir, "manifest.yaml"), "w") as fh:
            fh.write(
                "run_id: 2099-01-01-sandbox\n"
                "jobs:\n"
                "  - id: job-a\n"
                "    type: large_isolated\n"
                "    backend: codex\n"
                "    tier: deep\n"
                "    write_allowed:\n"
                "      - \"src/a.ts\"\n"
                "  - id: job-b\n"
                "    type: docs\n"
                "    backend: claude\n"
                "    tier: light\n"
                "  - id: job-never-dispatched\n"
                "    type: docs\n"
                "    backend: claude\n"
                "    tier: light\n"
            )
        with open(os.path.join(run_dir, "results", "job-a.json"), "w") as fh:
            json.dump({"status": "success", "blocked": False, "files_changed": ["src/a.ts"],
                       "violations": [], "summary": "", "session_id": "", "worktree": "",
                       "exit_code": 0, "failure_class": None, "retry_after_seconds": 0}, fh)
        with open(os.path.join(run_dir, "results", "job-b.json"), "w") as fh:
            json.dump({"status": "blocked", "blocked": True, "files_changed": ["oops.txt"],
                       "violations": ["oops.txt"], "summary": "", "session_id": "", "worktree": "",
                       "exit_code": 0, "failure_class": None, "retry_after_seconds": 0}, fh)
        # a dir with NO manifest.yaml -> silently skipped
        os.makedirs(os.path.join(tmp, "not-a-run"))

        recs = records_from_runs(tmp)
        check("from-runs: exactly the 2 dispatched jobs", len(recs) == 2)
        ra = next((r for r in recs if r["backend"] == "codex"), None)
        check("from-runs: job-a run_id from manifest", ra is not None and ra["run_id"] == "2099-01-01-sandbox")
        check("from-runs: job-a type from manifest", ra is not None and ra["type"] == "large_isolated")
        check("from-runs: job-a status success", ra is not None and ra["status"] == "success")
        check("from-runs: job-a not blocked", ra is not None and ra["blocked"] is False)
        rb = next((r for r in recs if r["backend"] == "claude"), None)
        check("from-runs: job-b blocked True", rb is not None and rb["blocked"] is True)
        check("from-runs: job-b status blocked", rb is not None and rb["status"] == "blocked")
        # never-dispatched job (no results/job-never-dispatched.json) never fabricated
        check("from-runs: never-dispatched job skipped, not zero-filled",
              all(r.get("run_id") != "2099-01-01-sandbox" or "never-dispatched" not in json.dumps(r)
                  for r in recs))
        # aggregate() accepts run-derived records the same as legacy ones
        row = query(recs, "codex", "large_isolated")
        check("from-runs: aggregates through the same pipeline", row["total"] == 1 and row["success"] == 1)
        # empty / missing root -> empty, never a crash
        check("from-runs: missing root -> []", records_from_runs(os.path.join(tmp, "does-not-exist")) == [])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("SELFTEST: %d ok, %d fail" % (ok, fail))
    return 0 if fail == 0 else 1


def main(argv):
    p = argparse.ArgumentParser(description="Compound V worker scorecard.")
    p.add_argument("--update", action="store_true", help="tally outcomes -> worker-performance.jsonl")
    p.add_argument("--query", action="store_true", help="print the scorecard row for one (backend, type)")
    p.add_argument("--backend")
    p.add_argument("--type", dest="typ")
    p.add_argument("--from-runs", dest="from_runs", default=None,
                    help="execution root to derive outcomes from (manifest jobs x results/*.json), "
                         "unioned with --outcomes")
    p.add_argument("--outcomes", default=DEFAULT_OUTCOMES)
    p.add_argument("--out", default=DEFAULT_OUT)
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args(argv)

    if args.selftest:
        return _selftest()

    records = _read_outcomes(args.outcomes)
    run_records = records_from_runs(args.from_runs) if args.from_runs else []
    records = records + run_records

    if args.query:
        if not args.backend or not args.typ:
            p.error("--query needs --backend and --type")
        print(json.dumps(query(records, args.backend, args.typ)))
        return 0

    if args.update:
        rows = aggregate(records)
        out_dir = os.path.dirname(args.out)
        if out_dir and not os.path.isdir(out_dir):
            os.makedirs(out_dir)
        with open(args.out, "w") as fh:
            for row in rows:
                fh.write(json.dumps(row) + "\n")
        print("wrote %s (%d backend/type rows from %d outcomes: %d run-derived + %d legacy)"
              % (args.out, len(rows), len(records), len(run_records), len(records) - len(run_records)))
        return 0

    p.error("one of --update / --query / --selftest is required")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
