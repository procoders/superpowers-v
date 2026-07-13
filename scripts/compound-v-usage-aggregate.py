#!/usr/bin/env python3
"""
Compound V usage aggregator.

Scans a run's `results/*.json` job_result files, reads each one's OPTIONAL
`usage` object (the field written by compound-v-usage-extract.py and threaded
through compound-v-collect-results.py), and produces honest per-run totals for
`/v:status` and any epic/feature roll-up.

Design contract (v2.12 usage & advisor, anti-ruflo charter):

  - PER-METRIC, INDEPENDENT aggregation. Token sums require valid token
    measurement (`usage.measured == true` AND a valid non-negative integer for
    that side). `advisor_calls` is aggregated INDEPENDENTLY of token
    measurement: a non-null, non-negative integer `advisor_calls` contributes
    REGARDLESS of `usage.measured` — because `measured` describes TOKEN
    measurement, and a Claude job legitimately has measured:false tokens AND a
    real worker-counted advisor_calls.
  - NULL, NEVER A FABRICATED ZERO. Every token/advisor total starts null. A
    numeric sum is emitted for a metric ONLY when at least one valid
    measurement contributed to it; otherwise the total renders as null (json)
    / "—" (text). With 0 measured jobs the token totals are null, never 0.
  - FAIL-OPEN, NEVER CRASH A STATUS RENDER. A missing/empty `results/` dir
    yields null totals plus a clear `note`, exit 0. A single unreadable or
    malformed result file is skipped (recorded in `note`), never fatal.
  - NEVER INVENT NUMBERS. Absent counts stay null/omitted; only real measured
    values are summed.

Input (one of):
  --run-dir docs/superpowers/execution/<run-id>   (reads <run-dir>/results/)
  --results-dir <dir>                             (reads <dir> directly)

Output:
  --format json  (default) : full per-job + totals object
  --format text            : one-line summary, e.g.
      measured: in=1234 out=567 advisor_calls=3 | 4 measured, 2 unmeasured

Optional annotation (grouping is per-run; these only label the output):
  --feature <name>   --epic <name>

Python 3.9-safe, stdlib only. `--selftest` writes tiny fixtures and asserts the
sums + unmeasured count, exit 0 on pass.
"""

import argparse
import json
import os
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple


def _read_usage(result_path: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Return (usage_or_None, error_or_None) for one result file.

    A file that cannot be read or parsed yields (None, "<basename>: <reason>")
    so the caller can record it in `note` without ever crashing.
    """
    try:
        with open(result_path, "r") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        return None, "%s: unreadable (%s)" % (os.path.basename(result_path), exc.__class__.__name__)
    if not isinstance(data, dict):
        return None, "%s: not a JSON object" % os.path.basename(result_path)
    usage = data.get("usage")
    if usage is not None and not isinstance(usage, dict):
        # Present but wrong shape — treat as unmeasured, note it, never crash.
        return None, "%s: usage is not an object" % os.path.basename(result_path)
    return usage, None


def _valid_int(val: Any) -> Optional[int]:
    """Return `val` iff it is a non-negative JSON INTEGER, else None.

    Anti-ruflo: a count is trustworthy only when it is a real, non-negative
    integer. bool is an int subclass but never a valid count; strings, floats,
    and negatives are rejected. Rejected/absent values are never coerced to 0.
    """
    if isinstance(val, bool):
        return None
    if isinstance(val, int) and val >= 0:
        return val
    return None


def _job_id_from_path(path: str) -> str:
    base = os.path.basename(path)
    if base.endswith(".json"):
        base = base[: -len(".json")]
    return base


def aggregate(results_dir: str,
              feature: Optional[str] = None,
              epic: Optional[str] = None) -> Dict[str, Any]:
    """Aggregate `usage` across every results/*.json under results_dir.

    Fail-open: a missing dir returns empty totals + a note, never raises.
    """
    notes = []  # type: List[str]
    jobs = []  # type: List[Dict[str, Any]]

    if not results_dir or not os.path.isdir(results_dir):
        notes.append("no results/ directory (%s) — pending or not yet dispatched" %
                     (results_dir or "<unset>"))
        return _assemble(jobs, notes, feature, epic)

    try:
        names = sorted(
            n for n in os.listdir(results_dir)
            if n.endswith(".json") and os.path.isfile(os.path.join(results_dir, n))
        )
    except OSError as exc:
        notes.append("could not list results dir (%s)" % exc.__class__.__name__)
        return _assemble(jobs, notes, feature, epic)

    if not names:
        notes.append("results/ is empty — no job results yet")

    for name in names:
        path = os.path.join(results_dir, name)
        usage, err = _read_usage(path)
        if err is not None:
            notes.append(err)
        job_id = _job_id_from_path(path)
        measured = bool(usage.get("measured")) if isinstance(usage, dict) else False
        in_tok = _valid_int(usage.get("input_tokens")) if isinstance(usage, dict) else None
        out_tok = _valid_int(usage.get("output_tokens")) if isinstance(usage, dict) else None
        adv = _valid_int(usage.get("advisor_calls")) if isinstance(usage, dict) else None
        jobs.append({
            "id": job_id,
            "measured": measured,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "advisor_calls": adv,
        })

    return _assemble(jobs, notes, feature, epic)


def _assemble(jobs: List[Dict[str, Any]],
              notes: List[str],
              feature: Optional[str],
              epic: Optional[str]) -> Dict[str, Any]:
    """Build the output object: per-job list + per-metric, null-safe totals.

    Every total starts null and becomes numeric only when a valid measurement
    contributed. Token sums require token measurement (measured:true + a valid
    non-negative int for that side). advisor_calls is aggregated INDEPENDENTLY:
    any valid non-negative int advisor_calls counts, even on a measured:false
    (e.g. Claude) job whose tokens are unmeasured.
    """
    sum_in = None      # type: Optional[int]
    sum_out = None     # type: Optional[int]
    sum_adv = None     # type: Optional[int]
    measured_jobs = 0
    unmeasured_jobs = 0
    advisor_jobs = 0

    for j in jobs:
        if j["measured"]:
            measured_jobs += 1
            # Token sides only sum when they are valid non-negative ints. A
            # missing/invalid side contributes nothing (never a fabricated 0).
            if j["input_tokens"] is not None:
                sum_in = (sum_in or 0) + j["input_tokens"]
            if j["output_tokens"] is not None:
                sum_out = (sum_out or 0) + j["output_tokens"]
        else:
            # measured==false OR no usage key: TOKENS honestly unmeasured.
            unmeasured_jobs += 1

        # advisor_calls is independent of token `measured`: a worker-counted,
        # non-null non-negative integer contributes regardless.
        if j["advisor_calls"] is not None:
            sum_adv = (sum_adv or 0) + j["advisor_calls"]
            advisor_jobs += 1

    totals = {
        "input_tokens": sum_in,
        "output_tokens": sum_out,
        "advisor_calls": sum_adv,
        "measured_jobs": measured_jobs,
        "unmeasured_jobs": unmeasured_jobs,
        "advisor_jobs": advisor_jobs,
    }
    out = {
        "jobs": jobs,
        "totals": totals,
    }  # type: Dict[str, Any]
    if feature:
        out["feature"] = feature
    if epic:
        out["epic"] = epic
    if notes:
        out["note"] = "; ".join(notes)
    return out


def _fmt_num(val: Optional[int]) -> str:
    """Render a null total as an em dash — never a fabricated 0."""
    return "—" if val is None else str(val)


def _format_text(agg: Dict[str, Any]) -> str:
    """One-line, measured-only summary. A null total prints "—", never a 0."""
    t = agg["totals"]
    return "measured: in=%s out=%s advisor_calls=%s | %d measured, %d unmeasured" % (
        _fmt_num(t["input_tokens"]), _fmt_num(t["output_tokens"]), _fmt_num(t["advisor_calls"]),
        t["measured_jobs"], t["unmeasured_jobs"],
    )


def _resolve_results_dir(args: argparse.Namespace) -> str:
    if args.results_dir:
        return args.results_dir
    if args.run_dir:
        return os.path.join(args.run_dir, "results")
    return ""


# --------------------------------------------------------------------------
# Selftest. Writes tiny job_result fixtures (some measured, some measured:false,
# some with NO usage key) and asserts the sums + unmeasured count.
# --------------------------------------------------------------------------
def _write_result(results_dir: str, job_id: str, obj: Dict[str, Any]) -> None:
    with open(os.path.join(results_dir, job_id + ".json"), "w") as fh:
        json.dump(obj, fh)


def _base_result(**overrides: Any) -> Dict[str, Any]:
    r = {
        "status": "success",
        "blocked": False,
        "files_changed": [],
        "violations": [],
        "summary": "ok",
        "session_id": "",
        "worktree": "",
        "exit_code": 0,
        "failure_class": None,
        "retry_after_seconds": 0,
    }
    r.update(overrides)
    return r


def _selftest() -> int:
    failures = []  # type: List[str]

    def check(name: str, got: Any, want: Any) -> None:
        if got != want:
            failures.append("%s: got %r, want %r" % (name, got, want))

    tmp = tempfile.mkdtemp(prefix="cv-usage-agg-selftest-")
    run_dir = os.path.join(tmp, "run")
    results_dir = os.path.join(run_dir, "results")
    os.makedirs(results_dir)

    # measured codex job
    _write_result(results_dir, "task-0-schema", _base_result(usage={
        "input_tokens": 1000, "output_tokens": 400, "advisor_calls": 2,
        "backend": "codex", "measured": True,
    }))
    # measured opencode job, null advisor_calls (counts as 0 in the sum)
    _write_result(results_dir, "task-1-slice", _base_result(usage={
        "input_tokens": 234, "output_tokens": 167, "advisor_calls": None,
        "backend": "opencode", "measured": True,
    }))
    # measured:false job (agy) — unmeasured, NOT summed as zero
    _write_result(results_dir, "task-2-agy", _base_result(usage={
        "input_tokens": None, "output_tokens": None, "advisor_calls": None,
        "backend": "agy", "measured": False,
    }))
    # NO usage key at all (older worker / claude Task) — unmeasured
    _write_result(results_dir, "task-3-claude", _base_result())
    # a second measured job to exercise advisor_calls summation
    _write_result(results_dir, "task-4-advisor", _base_result(usage={
        "input_tokens": 10, "output_tokens": 0, "advisor_calls": 1,
        "backend": "codex", "measured": True,
    }))
    # FIX 4: measured:false (Claude) job WITH a real worker-counted advisor_calls.
    # Its advisor_calls MUST contribute even though its tokens are unmeasured.
    _write_result(results_dir, "task-5-claude-advisor", _base_result(usage={
        "input_tokens": None, "output_tokens": None, "advisor_calls": 3,
        "backend": "claude", "measured": False,
    }))

    agg = aggregate(results_dir)
    t = agg["totals"]
    check("input_tokens", t["input_tokens"], 1244)          # 1000 + 234 + 10
    check("output_tokens", t["output_tokens"], 567)         # 400 + 167 + 0
    check("advisor_calls", t["advisor_calls"], 6)           # 2 + 0 + 1 + 3(measured:false)
    check("measured_jobs", t["measured_jobs"], 3)
    check("unmeasured_jobs", t["unmeasured_jobs"], 3)       # agy + claude(no-usage) + claude-advisor
    check("advisor_jobs", t["advisor_jobs"], 3)             # task-0, task-4, task-5
    check("job_count", len(agg["jobs"]), 6)

    # per-job fidelity for the no-usage job
    claude_job = [j for j in agg["jobs"] if j["id"] == "task-3-claude"][0]
    check("claude.measured", claude_job["measured"], False)
    check("claude.input_tokens", claude_job["input_tokens"], None)

    # text format
    txt = _format_text(agg)
    check("text", txt, "measured: in=1244 out=567 advisor_calls=6 | 3 measured, 3 unmeasured")

    # via run-dir resolution (results subdir)
    ns = argparse.Namespace(run_dir=run_dir, results_dir=None)
    agg2 = aggregate(_resolve_results_dir(ns))
    check("run_dir.input_tokens", agg2["totals"]["input_tokens"], 1244)

    # FIX 3: zero measured jobs -> NULL token totals + "—" text, never a real 0.
    zero_dir = os.path.join(tmp, "zero", "results")
    os.makedirs(zero_dir)
    _write_result(zero_dir, "z0-agy", _base_result(usage={
        "input_tokens": None, "output_tokens": None, "advisor_calls": None,
        "backend": "agy", "measured": False,
    }))
    _write_result(zero_dir, "z1-claude", _base_result())  # no usage key at all
    zagg = aggregate(zero_dir)
    zt = zagg["totals"]
    check("zero.input_tokens", zt["input_tokens"], None)
    check("zero.output_tokens", zt["output_tokens"], None)
    check("zero.advisor_calls", zt["advisor_calls"], None)
    check("zero.measured_jobs", zt["measured_jobs"], 0)
    check("zero.unmeasured_jobs", zt["unmeasured_jobs"], 2)
    check("zero.text", _format_text(zagg),
          "measured: in=— out=— advisor_calls=— | 0 measured, 2 unmeasured")

    # FIX 4 (isolated): advisor_calls contributes with ZERO measured token jobs.
    adv_dir = os.path.join(tmp, "advonly", "results")
    os.makedirs(adv_dir)
    _write_result(adv_dir, "a0-claude", _base_result(usage={
        "input_tokens": None, "output_tokens": None, "advisor_calls": 3,
        "backend": "claude", "measured": False,
    }))
    aagg = aggregate(adv_dir)
    at = aagg["totals"]
    check("advonly.advisor_calls", at["advisor_calls"], 3)
    check("advonly.input_tokens", at["input_tokens"], None)   # tokens stay null
    check("advonly.output_tokens", at["output_tokens"], None)
    check("advonly.measured_jobs", at["measured_jobs"], 0)
    check("advonly.advisor_jobs", at["advisor_jobs"], 1)
    check("advonly.text", _format_text(aagg),
          "measured: in=— out=— advisor_calls=3 | 0 measured, 1 unmeasured")

    # fail-open: missing results dir -> NULL totals + note, no crash
    agg3 = aggregate(os.path.join(tmp, "does-not-exist", "results"))
    check("missing.input_tokens", agg3["totals"]["input_tokens"], None)
    check("missing.advisor_calls", agg3["totals"]["advisor_calls"], None)
    check("missing.measured_jobs", agg3["totals"]["measured_jobs"], 0)
    check("missing.unmeasured_jobs", agg3["totals"]["unmeasured_jobs"], 0)
    check("missing.has_note", "note" in agg3 and bool(agg3["note"]), True)

    # fail-open: a malformed result file is skipped, noted, never fatal
    with open(os.path.join(results_dir, "task-6-broken.json"), "w") as fh:
        fh.write("{ this is not valid json ")
    agg4 = aggregate(results_dir)
    check("broken.measured_jobs", agg4["totals"]["measured_jobs"], 3)
    check("broken.unmeasured_jobs", agg4["totals"]["unmeasured_jobs"], 4)  # +broken
    check("broken.has_note", "note" in agg4 and "task-6-broken" in agg4["note"], True)

    # cleanup
    try:
        import shutil
        shutil.rmtree(tmp)
    except OSError:
        pass

    if failures:
        sys.stdout.write("SELFTEST FAIL (%d):\n" % len(failures))
        for f in failures:
            sys.stdout.write("  - %s\n" % f)
        return 1
    sys.stdout.write(
        "SELFTEST PASS: measured-only sums, unmeasured count "
        "(measured:false + no-usage), fail-open, text format OK\n")
    return 0


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Aggregate measured-only `usage` across a run's "
                    "results/*.json job results (anti-ruflo)."
    )
    p.add_argument("--run-dir",
                   help="Run directory (reads <run-dir>/results/), e.g. "
                        "docs/superpowers/execution/<run-id>")
    p.add_argument("--results-dir",
                   help="Results directory to scan directly (overrides --run-dir)")
    p.add_argument("--feature", help="Optional label included in the output object")
    p.add_argument("--epic", help="Optional label included in the output object")
    p.add_argument("--format", choices=("json", "text"), default="json",
                   help="Output format (default: json)")
    p.add_argument("--selftest", action="store_true",
                   help="Run inline fixtures and exit 0 on success, non-zero on failure")
    return p.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    if args.selftest:
        return _selftest()

    results_dir = _resolve_results_dir(args)
    if not results_dir:
        sys.stderr.write("error: pass --run-dir or --results-dir (or --selftest)\n")
        return 1

    agg = aggregate(results_dir, feature=args.feature, epic=args.epic)
    if args.format == "text":
        sys.stdout.write(_format_text(agg) + "\n")
    else:
        sys.stdout.write(json.dumps(agg, indent=2, sort_keys=False) + "\n")
    # Fail-open: even an empty/missing run is exit 0 so a status render never breaks.
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
