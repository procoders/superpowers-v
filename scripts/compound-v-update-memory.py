#!/usr/bin/env python3
"""
Compound V memory updater (outcomes log only).

Appends exactly ONE line per job to docs/superpowers/memory/task-outcomes.jsonl,
the lean, committed, machine-appended half of Compound V's memory (PRD §5.8).

Each line is a JSON object with this fixed shape:

  {"run_id": str, "type": str, "backend": str, "model": str,
   "status": str, "blocked": bool, "rework_rounds": int}

  - run_id        : the execution run id (manifest.run_id)
  - type          : the job's manifest `type` (shared_foundation, large_isolated, ...)
  - backend       : claude | codex | antigravity
  - model         : opus | sonnet | gpt-5.5 | ... (execution-layer datum)
  - status        : success | blocked | timeout | error (from the job_result)
  - blocked       : git-derived scope verdict
  - rework_rounds : how many fix/redispatch rounds the job took (>= 0)

This script ONLY appends to task-outcomes.jsonl. It NEVER reads, writes, or
touches routing-lessons.md — that file is human-curated (see plan §6 task
task-collector-memory, PRD §5.8). The routing-learning loop is: collector ->
this log (automatic) -> a human reads patterns -> routing-lessons.md (manual).

NO fabricated cost / token metrics are recorded (anti-ruflo, plan §7); the line
shape above is exhaustive.

Two input modes:
  1. From a normalized job_result file produced by the collector, plus the
     manifest-derived job metadata:
       --result <results/<id>.json> --run-id R --type T --backend B --model M
       [--rework-rounds N]
     (status + blocked are read from the result; flags override.)
  2. Fully explicit:
       --run-id R --type T --backend B --model M --status S
       [--blocked|--no-blocked] [--rework-rounds N]

Python 3.9-safe, stdlib only. Exit 0 on a written line; exit 1 on a usage error.
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
from typing import Any, Dict, List, Optional

OUTCOMES_RELPATH = os.path.join("docs", "superpowers", "memory", "task-outcomes.jsonl")
STATUS_VALUES = ("success", "blocked", "timeout", "error")

# Hard guard: this script must never name routing-lessons.md as a write target.
_FORBIDDEN_BASENAME = "routing-lessons.md"


def _read_json(path: str) -> Optional[Any]:
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (ValueError, OSError):
        return None


def _default_outcomes_path() -> str:
    """Default to <repo-root>/docs/superpowers/memory/task-outcomes.jsonl.

    Repo root is two levels up from this script (scripts/ -> root).
    """
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    return os.path.join(root, OUTCOMES_RELPATH)


def build_line(args: argparse.Namespace) -> Dict[str, Any]:
    result = _read_json(args.result) if args.result else None
    if not isinstance(result, dict):
        result = {}

    status = args.status
    if status is None:
        status = result.get("status")
    if status not in STATUS_VALUES:
        raise ValueError(
            "status must be one of %s (got %r); pass --status or a valid --result"
            % (", ".join(STATUS_VALUES), status)
        )

    if args.blocked is not None:
        blocked = args.blocked
    elif "blocked" in result:
        blocked = bool(result.get("blocked"))
    else:
        # Derive from status as a last resort.
        blocked = status == "blocked"

    rework = args.rework_rounds if args.rework_rounds is not None else 0
    if rework < 0:
        raise ValueError("rework-rounds must be >= 0")

    return {
        "run_id": args.run_id,
        "type": args.type,
        "backend": args.backend,
        "model": args.model,
        "status": status,
        "blocked": bool(blocked),
        "rework_rounds": int(rework),
    }


def append_line(path: str, line_obj: Dict[str, Any]) -> None:
    if os.path.basename(path) == _FORBIDDEN_BASENAME:
        # Belt-and-suspenders: never let an operator misroute output here.
        raise ValueError(
            "refusing to write to %s — it is human-curated, not script-written"
            % _FORBIDDEN_BASENAME
        )
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    # Compact, one object per line (JSONL). ensure_ascii=False keeps unicode readable.
    line = json.dumps(line_obj, ensure_ascii=False, sort_keys=False)
    # Explicit UTF-8: ensure_ascii=False can emit non-ASCII (e.g. a unicode request slug);
    # under a C/POSIX locale the default open() encoding is ASCII and would raise
    # UnicodeEncodeError. The reader side already opens UTF-8. (v2.9 locale-robustness.)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


# --------------------------------------------------------------------------
# Selftest. Exercises build_line (the outcome-line builder) and append_line
# (JSONL append) in-process. Uses only a tmp dir — NEVER the real memory ledger.
# No network, no subprocesses. ADDITIVE — runtime behavior is unchanged.
# --------------------------------------------------------------------------
_EXPECTED_KEYS = ("run_id", "type", "backend", "model", "status",
                  "blocked", "rework_rounds")


def _mk_args(**kw: Any) -> argparse.Namespace:
    defaults = dict(
        run_id="R1", type="shared_foundation", backend="claude", model="opus",
        result=None, status=None, out=None, rework_rounds=None, blocked=None,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _selftest() -> int:
    ok = [0]
    fail = [0]
    failures = []  # type: List[str]

    def check(name: str, cond: bool) -> None:
        if cond:
            ok[0] += 1
        else:
            fail[0] += 1
            failures.append(name)

    # build_line: a well-formed explicit outcome yields exactly the fixed shape.
    line = build_line(_mk_args(status="success", rework_rounds=2))
    check("build.keys", set(line.keys()) == set(_EXPECTED_KEYS))
    check("build.run_id", line["run_id"] == "R1")
    check("build.status", line["status"] == "success")
    check("build.blocked_type", isinstance(line["blocked"], bool))
    check("build.blocked_default", line["blocked"] is False)
    check("build.rework_type", isinstance(line["rework_rounds"], int))
    check("build.rework_val", line["rework_rounds"] == 2)

    # build_line: status + blocked read from a --result file when flags omit them.
    d = tempfile.mkdtemp(prefix="cv-mem-selftest-")
    try:
        rp = os.path.join(d, "result.json")
        with open(rp, "w", encoding="utf-8") as fh:
            json.dump({"status": "blocked", "blocked": True}, fh)
        rl = build_line(_mk_args(result=rp))
        check("build.from_result.status", rl["status"] == "blocked")
        check("build.from_result.blocked", rl["blocked"] is True)

        # build_line: an invalid status raises ValueError.
        raised = False
        try:
            build_line(_mk_args(status=None, result=None))
        except ValueError:
            raised = True
        check("build.invalid_status_raises", raised)

        # build_line: a negative rework count raises ValueError.
        raised2 = False
        try:
            build_line(_mk_args(status="error", rework_rounds=-1))
        except ValueError:
            raised2 = True
        check("build.negative_rework_raises", raised2)

        # append_line: N appends -> N valid, newline-terminated JSON lines.
        ledger = os.path.join(d, "task-outcomes.jsonl")
        objs = [
            build_line(_mk_args(run_id="R%d" % i, status="success", rework_rounds=i))
            for i in range(3)
        ]
        for obj in objs:
            append_line(ledger, obj)
        with open(ledger, "r", encoding="utf-8") as fh:
            raw = fh.read()
        check("append.newline_terminated", raw.endswith("\n"))
        lines = [ln for ln in raw.splitlines() if ln.strip()]
        check("append.line_count", len(lines) == 3)
        parsed_ok = True
        for i, ln in enumerate(lines):
            try:
                obj = json.loads(ln)
            except ValueError:
                parsed_ok = False
                break
            if obj.get("run_id") != "R%d" % i or set(obj.keys()) != set(_EXPECTED_KEYS):
                parsed_ok = False
                break
        check("append.all_valid_json", parsed_ok)

        # append_line: the routing-lessons.md guard fires (never script-written).
        guarded = False
        try:
            append_line(os.path.join(d, "routing-lessons.md"), objs[0])
        except ValueError:
            guarded = True
        check("append.forbidden_basename_guard", guarded)
    finally:
        shutil.rmtree(d, ignore_errors=True)

    sys.stdout.write("SELFTEST: %d ok, %d fail\n" % (ok[0], fail[0]))
    if failures:
        for name in failures:
            sys.stdout.write("  - FAIL: %s\n" % name)
        return 1
    return 0


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Append one outcome line to task-outcomes.jsonl"
    )
    p.add_argument("--run-id", required=True)
    p.add_argument("--type", required=True, help="Manifest job `type`")
    p.add_argument("--backend", required=True, help="claude | codex | antigravity")
    p.add_argument("--model", required=True, help="opus | sonnet | gpt-5.5 | ...")
    p.add_argument("--result", help="Path to the collector's results/<id>.json")
    p.add_argument("--status", choices=STATUS_VALUES, help="Override/supply status")
    p.add_argument("--out", help="Override outcomes file path (default: repo memory dir)")
    p.add_argument("--rework-rounds", type=int, help="Fix/redispatch rounds (>=0, default 0)")
    blk = p.add_mutually_exclusive_group()
    blk.add_argument("--blocked", dest="blocked", action="store_true", default=None)
    blk.add_argument("--no-blocked", dest="blocked", action="store_false")
    p.add_argument("--selftest", action="store_true",
                   help="Run inline tests and exit 0 on success, non-zero on failure")
    return p.parse_args(argv)


def main(argv: List[str]) -> int:
    # --selftest short-circuits before required-arg validation (needs no
    # run/type/backend/model and touches only a tmp dir).
    if "--selftest" in argv:
        return _selftest()

    args = parse_args(argv)
    try:
        line_obj = build_line(args)
    except ValueError as e:
        sys.stderr.write("error: %s\n" % e)
        return 1

    out_path = args.out or _default_outcomes_path()
    try:
        append_line(out_path, line_obj)
    except (ValueError, OSError) as e:
        sys.stderr.write("error: %s\n" % e)
        return 1

    sys.stdout.write(
        "appended outcome for %s/%s -> %s\n" % (line_obj["run_id"], args.type, out_path)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
