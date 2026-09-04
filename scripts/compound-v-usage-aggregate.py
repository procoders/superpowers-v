#!/usr/bin/env python3
"""
Compound V usage aggregator.

Scans a run's `results/*.json` job_result files, reads each one's OPTIONAL
`usage` object (the field written by compound-v-usage-extract.py and threaded
through compound-v-collect-results.py), and produces honest per-run totals for
`/v:status` and any epic/feature roll-up.

Design contract (v2.12 usage, anti-ruflo charter):

  - PER-METRIC, INDEPENDENT aggregation. Token sums require valid token
    measurement (`usage.measured == true` AND a valid non-negative integer for
    that side).
  - NULL, NEVER A FABRICATED ZERO. Every token total starts null. A
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

Sources (v3.4.17). `usage` now arrives from either of two records, and this
aggregator treats them IDENTICALLY: `backend-events` (an external backend's own
structured events) and `workflow-transcript` (an Engine C job's Claude Code
subagent transcripts). Totals semantics are unchanged — measured-only, null over
a fabricated zero, per-metric independence. The transcript source additionally
reports `cache_read_input_tokens` / `cache_creation_input_tokens`; those are
summed under the same rules and, because a backend-events result carries neither
key, a pre-3.4.17 run totals them as null and its text line is byte-identical to
what it was before.

Output:
  --format json  (default) : full per-job + totals object
  --format text            : one-line summary, e.g.
      measured: in=1234 out=567 | 4 measured, 2 unmeasured
    and, when a source reported the cache metrics:
      measured: in=174 out=40680 cache_read=6174478 cache_create=286647 | 2 measured, 0 unmeasured

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
        # v3.4.17: the workflow-transcript source also reports the two prompt-cache
        # metrics. They are carried through UNCHANGED in kind — measured-only,
        # null when absent — and kept SEPARATE from input_tokens, because on a
        # real Engine C job the cache-read figure dwarfs the uncached input
        # (1.77M vs 62 on run 2026-09-03-glob-parity-one-matcher-r3) and folding
        # them together would misstate both. A backend-events result simply has
        # neither key, so it contributes nothing to them: the existing
        # input/output totals are byte-identical to what they were before.
        cr_tok = _valid_int(usage.get("cache_read_input_tokens")) if isinstance(usage, dict) else None
        cc_tok = _valid_int(usage.get("cache_creation_input_tokens")) if isinstance(usage, dict) else None
        jobs.append({
            "id": job_id,
            "measured": measured,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "cache_read_input_tokens": cr_tok,
            "cache_creation_input_tokens": cc_tok,
            "source": usage.get("source") if isinstance(usage, dict) else None,
        })

    return _assemble(jobs, notes, feature, epic)


def _assemble(jobs: List[Dict[str, Any]],
              notes: List[str],
              feature: Optional[str],
              epic: Optional[str]) -> Dict[str, Any]:
    """Build the output object: per-job list + per-metric, null-safe totals.

    Every total starts null and becomes numeric only when a valid measurement
    contributed. Token sums require token measurement (measured:true + a valid
    non-negative int for that side).
    """
    sum_in = None      # type: Optional[int]
    sum_out = None     # type: Optional[int]
    sum_cr = None      # type: Optional[int]
    sum_cc = None      # type: Optional[int]
    measured_jobs = 0
    unmeasured_jobs = 0

    for j in jobs:
        if j["measured"]:
            measured_jobs += 1
            # Token sides only sum when they are valid non-negative ints. A
            # missing/invalid side contributes nothing (never a fabricated 0).
            if j["input_tokens"] is not None:
                sum_in = (sum_in or 0) + j["input_tokens"]
            if j["output_tokens"] is not None:
                sum_out = (sum_out or 0) + j["output_tokens"]
            # Same rule for the two cache metrics: a source that does not report
            # them leaves them null, and null contributes nothing. A run of
            # backend-events results therefore still totals them as null, not 0.
            if j.get("cache_read_input_tokens") is not None:
                sum_cr = (sum_cr or 0) + j["cache_read_input_tokens"]
            if j.get("cache_creation_input_tokens") is not None:
                sum_cc = (sum_cc or 0) + j["cache_creation_input_tokens"]
        else:
            # measured==false OR no usage key: TOKENS honestly unmeasured.
            unmeasured_jobs += 1

    totals = {
        "input_tokens": sum_in,
        "output_tokens": sum_out,
        "cache_read_input_tokens": sum_cr,
        "cache_creation_input_tokens": sum_cc,
        "measured_jobs": measured_jobs,
        "unmeasured_jobs": unmeasured_jobs,
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


def _null_dash():  # type: () -> str
    """The character standing for "not measured", safe for THIS stdout.

    "—" is the documented rendering (commands/v-status.md), but a stream whose
    encoding is ASCII — `PYTHONIOENCODING=ascii`, or a C locale on a Python
    without UTF-8 mode — cannot encode it, and the write raised UnicodeEncodeError
    and took the whole render down. A status line that crashes is worse than one
    that prints "-". The one thing that must never happen either way is a 0
    standing in for a number nobody measured.

    NOTE: compound-v-usage-extract.py carries the identical helper. It is a
    property of the caller's own stdout, asked locally, not a shared constant —
    but keep the two in step.
    """
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        u"\u2014".encode(encoding)
    except (LookupError, UnicodeEncodeError):
        return "-"
    return u"\u2014"


def _fmt_num(val: Optional[int]) -> str:
    """Render a null total as a dash — never a fabricated 0."""
    return _null_dash() if val is None else str(val)


def _format_text(agg: Dict[str, Any]) -> str:
    """One-line, measured-only summary. A null total prints "—", never a 0.

    The cache clause is APPENDED ONLY when a source actually reported the two
    cache metrics (today: `workflow-transcript`). A run of backend-events
    results renders exactly the string it rendered before 3.4.17 — nothing is
    printed for a metric nobody measured. It is not cosmetic: on Engine C the
    cache-read figure is four orders of magnitude larger than the uncached
    input, so a line that showed only `in=` would understate the run's real
    prompt volume while looking complete.
    """
    t = agg["totals"]
    line = "measured: in=%s out=%s" % (
        _fmt_num(t["input_tokens"]), _fmt_num(t["output_tokens"]))
    if t.get("cache_read_input_tokens") is not None \
            or t.get("cache_creation_input_tokens") is not None:
        line += " cache_read=%s cache_create=%s" % (
            _fmt_num(t.get("cache_read_input_tokens")),
            _fmt_num(t.get("cache_creation_input_tokens")))
    return "%s | %d measured, %d unmeasured" % (
        line, t["measured_jobs"], t["unmeasured_jobs"])


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
        "input_tokens": 1000, "output_tokens": 400,
        "backend": "codex", "measured": True,
    }))
    # measured opencode job
    _write_result(results_dir, "task-1-slice", _base_result(usage={
        "input_tokens": 234, "output_tokens": 167,
        "backend": "opencode", "measured": True,
    }))
    # measured:false job (agy) — unmeasured, NOT summed as zero
    _write_result(results_dir, "task-2-agy", _base_result(usage={
        "input_tokens": None, "output_tokens": None,
        "backend": "agy", "measured": False,
    }))
    # NO usage key at all (older worker / claude Task) — unmeasured
    _write_result(results_dir, "task-3-claude", _base_result())
    # a second measured job to exercise token summation
    _write_result(results_dir, "task-4-extra", _base_result(usage={
        "input_tokens": 10, "output_tokens": 0,
        "backend": "codex", "measured": True,
    }))
    # a second measured:false (Claude) job — unmeasured, never summed as zero
    _write_result(results_dir, "task-5-claude", _base_result(usage={
        "input_tokens": None, "output_tokens": None,
        "backend": "claude", "measured": False,
    }))

    agg = aggregate(results_dir)
    t = agg["totals"]
    check("input_tokens", t["input_tokens"], 1244)          # 1000 + 234 + 10
    check("output_tokens", t["output_tokens"], 567)         # 400 + 167 + 0
    check("measured_jobs", t["measured_jobs"], 3)
    check("unmeasured_jobs", t["unmeasured_jobs"], 3)       # agy + claude(no-usage) + claude
    check("job_count", len(agg["jobs"]), 6)

    # per-job fidelity for the no-usage job
    claude_job = [j for j in agg["jobs"] if j["id"] == "task-3-claude"][0]
    check("claude.measured", claude_job["measured"], False)
    check("claude.input_tokens", claude_job["input_tokens"], None)

    # text format — UNCHANGED for backend-events results (no cache clause)
    txt = _format_text(agg)
    check("text", txt, "measured: in=1244 out=567 | 3 measured, 3 unmeasured")
    check("no_cache_totals", (t["cache_read_input_tokens"],
                              t["cache_creation_input_tokens"]), (None, None))

    # via run-dir resolution (results subdir)
    ns = argparse.Namespace(run_dir=run_dir, results_dir=None)
    agg2 = aggregate(_resolve_results_dir(ns))
    check("run_dir.input_tokens", agg2["totals"]["input_tokens"], 1244)

    # v3.4.17: a `workflow-transcript` run aggregates with the SAME semantics,
    # and its two extra cache metrics roll up under the same null-safe rule.
    wf_dir = os.path.join(tmp, "wf", "results")
    os.makedirs(wf_dir)
    _write_result(wf_dir, "load-bearing-row", _base_result(usage={
        "input_tokens": 62, "output_tokens": 10202,
        "cache_read_input_tokens": 1767605,
        "cache_creation_input_tokens": 125639,
        "backend": "claude", "measured": True,
        "source": "workflow-transcript",
        "transcripts": ["agent-a027dffb35f90a354.jsonl"],
    }))
    _write_result(wf_dir, "spec-review-1", _base_result(usage={
        "input_tokens": 112, "output_tokens": 30478,
        "cache_read_input_tokens": 4406873,
        "cache_creation_input_tokens": 161008,
        "backend": "claude", "measured": True,
        "source": "workflow-transcript",
        "transcripts": ["agent-a26c40b0a6bdb887a.jsonl"],
    }))
    # A job the transcript scan could not measure stays unmeasured, exactly as
    # an agy job does — the source changes, the honesty rule does not.
    _write_result(wf_dir, "no-transcript", _base_result())
    wfagg = aggregate(wf_dir)
    wt = wfagg["totals"]
    check("wf.input_tokens", wt["input_tokens"], 174)
    check("wf.output_tokens", wt["output_tokens"], 40680)
    check("wf.cache_read", wt["cache_read_input_tokens"], 6174478)
    check("wf.cache_create", wt["cache_creation_input_tokens"], 286647)
    check("wf.measured_jobs", wt["measured_jobs"], 2)
    check("wf.unmeasured_jobs", wt["unmeasured_jobs"], 1)
    check("wf.text", _format_text(wfagg),
          "measured: in=174 out=40680 cache_read=6174478 cache_create=286647 "
          "| 2 measured, 1 unmeasured")
    wf_job = [j for j in wfagg["jobs"] if j["id"] == "spec-review-1"][0]
    check("wf.job.source", wf_job["source"], "workflow-transcript")
    wf_none = [j for j in wfagg["jobs"] if j["id"] == "no-transcript"][0]
    check("wf.job.no_source", wf_none["source"], None)
    check("wf.job.no_cache", wf_none["cache_read_input_tokens"], None)

    # FIX 3: zero measured jobs -> NULL token totals + "—" text, never a real 0.
    zero_dir = os.path.join(tmp, "zero", "results")
    os.makedirs(zero_dir)
    _write_result(zero_dir, "z0-agy", _base_result(usage={
        "input_tokens": None, "output_tokens": None,
        "backend": "agy", "measured": False,
    }))
    _write_result(zero_dir, "z1-claude", _base_result())  # no usage key at all
    zagg = aggregate(zero_dir)
    zt = zagg["totals"]
    check("zero.input_tokens", zt["input_tokens"], None)
    check("zero.output_tokens", zt["output_tokens"], None)
    check("zero.measured_jobs", zt["measured_jobs"], 0)
    check("zero.unmeasured_jobs", zt["unmeasured_jobs"], 2)
    # The dash is whatever THIS stdout can encode, so the expectation is built
    # the same way — an ASCII stream must not turn a passing test into a crash.
    _d = _fmt_num(None)
    check("zero.text", _format_text(zagg),
          "measured: in=%s out=%s | 0 measured, 2 unmeasured" % (_d, _d))

    # fail-open: missing results dir -> NULL totals + note, no crash
    agg3 = aggregate(os.path.join(tmp, "does-not-exist", "results"))
    check("missing.input_tokens", agg3["totals"]["input_tokens"], None)
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
