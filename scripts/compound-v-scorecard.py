#!/usr/bin/env python3
"""
Compound V worker scorecard — data-driven routing signal (PRD §8 / v1.1).

Routing today is a STATIC guess (routing-policy.md): a task-type maps to a fixed
backend/tier. This script makes it ADAPTIVE: it tallies how each backend has ACTUALLY
performed per task-type in THIS repo (from the machine-appended task-outcomes.jsonl) and
emits a `health` signal the router consults before trusting the static default. It does
NOT decide on its own and NEVER fabricates cost/token metrics — it only counts real,
git-derived job outcomes (anti-ruflo).

Input  (memory/task-outcomes.jsonl, one JSON object per line):
  {"run_id","type","backend","model","status","blocked","rework_rounds"}
Output (memory/worker-performance.jsonl, one object per (backend, type)):
  {"backend","type","total","success","blocked","error","timeout",
   "avg_rework","block_rate","error_rate","success_rate","health"}

`health` ∈ insufficient_data | healthy | watch | unhealthy. A backend that, for a given
task-type, blocks or needs rework too often is `unhealthy`; the router then prefers the
alternative (or escalates) instead of blindly following the static default.

Usage:
  compound-v-scorecard.py --update [--outcomes P] [--out P]     # tally -> worker-performance.jsonl
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
    print("SELFTEST: %d ok, %d fail" % (ok, fail))
    return 0 if fail == 0 else 1


def main(argv):
    p = argparse.ArgumentParser(description="Compound V worker scorecard.")
    p.add_argument("--update", action="store_true", help="tally outcomes -> worker-performance.jsonl")
    p.add_argument("--query", action="store_true", help="print the scorecard row for one (backend, type)")
    p.add_argument("--backend")
    p.add_argument("--type", dest="typ")
    p.add_argument("--outcomes", default=DEFAULT_OUTCOMES)
    p.add_argument("--out", default=DEFAULT_OUT)
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args(argv)

    if args.selftest:
        return _selftest()

    records = _read_outcomes(args.outcomes)

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
        print("wrote %s (%d backend/type rows from %d outcomes)"
              % (args.out, len(rows), len(records)))
        return 0

    p.error("one of --update / --query / --selftest is required")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
