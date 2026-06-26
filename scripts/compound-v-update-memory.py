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
import sys
from typing import Any, Dict, List, Optional

OUTCOMES_RELPATH = os.path.join("docs", "superpowers", "memory", "task-outcomes.jsonl")
STATUS_VALUES = ("success", "blocked", "timeout", "error")

# Hard guard: this script must never name routing-lessons.md as a write target.
_FORBIDDEN_BASENAME = "routing-lessons.md"


def _read_json(path: str) -> Optional[Any]:
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r") as fh:
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
    with open(path, "a") as fh:
        fh.write(line + "\n")


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
    return p.parse_args(argv)


def main(argv: List[str]) -> int:
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
