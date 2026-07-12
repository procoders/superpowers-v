#!/usr/bin/env python3
"""
Compound V — append-only THREE-event triage-outcomes stream + cohort-separated
Tier 2 + fast-path precision (v2.9 Task F1, spec §6 / AC-3 / AC-12).

The stream ``docs/superpowers/memory/triage-outcomes.jsonl`` is STRICTLY append-only
(AC-3 — no back-fill, no mutated line). Each triaged request is modeled as THREE
separate appended lines, joined at read time on the write-once ``pre_eval_id``:

    {"event":"predicted", ts, pre_eval_id, decision, difficulty_band, impact_band,
     taxonomy_sha, localization:{resolved_paths, fan_out, flags}}     # at PRE_EVAL_DONE
    {"event":"bind", ts, pre_eval_id, run_id}                         # when the run dir exists
    {"event":"actual", ts, pre_eval_id, run_id, escalated, review_result,
     test_result, diff_files, diff_lines, sensitive_hit}             # at MERGED / ESCALATION

A declined / full-pipeline request has ``predicted`` and no ``bind``. NEVER one mutated
object — three lines.

Event keying (CR4-5)
--------------------
The reduce key is ``(pre_eval_id, run_id, event)`` — ``run_id`` is ``None`` for
``predicted`` (no run exists yet). Including ``run_id`` is what lets an ESCALATION CHILD
carry its OWN run-id whose ``bind``/``actual`` do NOT overwrite the fast-path parent's
events. Duplicate / out-of-order events: **last-writer-wins per key** (later line in file
order replaces the earlier).

Cohort separation (Iron-Invariant #3)
-------------------------------------
Only an **accepted fast-path** outcome may support a healthy / lowering signal. A
full-pipeline outcome — including an escalation CHILD — contributes **escalation evidence
ONLY**, never low-corroboration. A run is a *fast-path parent* iff its ``predicted``
decision is ``FASTPATH_ELIGIBLE`` AND it is not marked ``escalation_child``. Everything
else (missing/declined ``predicted``, or ``escalation_child:true``) is full-pipeline.
At launch every ``predicted`` is ``FULL_PIPELINE`` → Tier 2 is escalation-only by
construction. Fail-closed: an unknown / missing ``predicted`` decision → full-pipeline.

Precision (fast-path PARENT outcome only)
-----------------------------------------
    precision       = fastpath_runs_not_escalated_and_review_passed / fastpath_runs_total
    escalation_rate = escalated                                     / fastpath_runs_total
``fastpath_runs_total`` counts fast-path parent runs that have a **terminal** ``actual``.
CR5-4: a terminal ``actual`` counts only AFTER merge — a precision-IGNORED
``merge_pending`` ``actual`` (``merge_pending:true``) may precede it and is treated like a
missing ``actual`` (excluded, logged, never fabricated). A fast-path parent with no
terminal ``actual`` is excluded from BOTH numerator and denominator (logged, never
counted as a success or a failure).

Reuse (no recopy)
-----------------
``append_line`` — the forbidden-basename guard + ``makedirs`` + append-never-rewrite
discipline — is imported by path from ``compound-v-update-memory.py``. ``min_sample_count``
is read through the shared ``compound-v-project-config.py`` loader. This module recopies
neither.

This stream is triage-only telemetry — evidence for the Tier-2 gate, NEVER a routing
input beyond the triage boundary. No fabricated cost / token metrics anywhere.

Python 3.9-safe, stdlib only. NEVER a hard ``import yaml`` (this module needs no YAML).

Usage:
    compound-v-triage-outcomes.py predicted --pre-eval-id ID --decision D [--field k=v ...]
    compound-v-triage-outcomes.py bind      --pre-eval-id ID --run-id R
    compound-v-triage-outcomes.py actual    --pre-eval-id ID --run-id R [--escalated] ...
    compound-v-triage-outcomes.py precision [--repo DIR] [--min-sample N]
    compound-v-triage-outcomes.py tier2     [--repo DIR] [--min-sample N]
    compound-v-triage-outcomes.py --selftest
"""

import argparse
import datetime
import importlib.util
import json
import os
import sys

STREAM_RELPATH = os.path.join("docs", "superpowers", "memory", "triage-outcomes.jsonl")
STREAM_BASENAME = "triage-outcomes.jsonl"

EVENT_PREDICTED = "predicted"
EVENT_BIND = "bind"
EVENT_ACTUAL = "actual"
EVENTS = (EVENT_PREDICTED, EVENT_BIND, EVENT_ACTUAL)

FASTPATH_DECISION = "FASTPATH_ELIGIBLE"
# A review is "passed" for precision if it lands one of these normalized verdicts.
_REVIEW_PASSED = ("approved", "pass", "passed")


# ---------------------------------------------------------------------------- #
# Reuse siblings by path (no recopy). Loaded lazily.
# ---------------------------------------------------------------------------- #
def _load_sibling(basename, modname):
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, basename)
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_UPDATE_MEMORY = None
_PROJECT_CONFIG = None


def _update_memory():
    """The update-memory module — we reuse its ``append_line`` (the forbidden-basename
    guard + makedirs + append-never-rewrite discipline), never recopy it."""
    global _UPDATE_MEMORY
    if _UPDATE_MEMORY is None:
        _UPDATE_MEMORY = _load_sibling("compound-v-update-memory.py",
                                       "compound_v_update_memory")
    return _UPDATE_MEMORY


def _project_config():
    global _PROJECT_CONFIG
    if _PROJECT_CONFIG is None:
        _PROJECT_CONFIG = _load_sibling("compound-v-project-config.py",
                                        "compound_v_project_config")
    return _PROJECT_CONFIG


# ---------------------------------------------------------------------------- #
# Paths + config.
# ---------------------------------------------------------------------------- #
def _repo_root():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(here)


def default_stream_path():
    return os.path.join(_repo_root(), STREAM_RELPATH)


def resolve_min_sample_count(repo=None, override=None):
    """Effective ``pre_eval.min_sample_count``. Explicit ``override`` wins; else read
    through the shared project-config loader (fail-closed to its declared default on a
    malformed config — never fail open)."""
    if override is not None:
        return int(override)
    pc = _project_config()
    try:
        cfg = pc.load_project_config(repo if repo is not None else _repo_root())
    except ValueError:
        cfg = {}  # malformed config → safe defaults (caller may warn separately)
    values, _warnings = pc.resolve_pre_eval(cfg)
    return int(values["min_sample_count"])


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------- #
# Append side — THREE events, each ONE append via the reused append_line discipline.
# ---------------------------------------------------------------------------- #
def _append_event(obj, stream_path=None):
    """Append exactly one JSONL event. Delegates the write to update-memory's
    ``append_line`` (append-only, makedirs, forbidden-basename guard). Belt-and-suspenders:
    this module ONLY ever writes triage-outcomes.jsonl."""
    path = stream_path or default_stream_path()
    if os.path.basename(path) != STREAM_BASENAME:
        raise ValueError(
            "refusing to write %r — triage-outcomes only appends to %s"
            % (path, STREAM_BASENAME)
        )
    _update_memory().append_line(path, obj)


def append_predicted(pre_eval_id, decision=None, difficulty_band=None, impact_band=None,
                     taxonomy_sha=None, localization=None, ts=None, stream_path=None,
                     **extra):
    """Append the ``predicted`` event (at PRE_EVAL_DONE). Keyed by ``pre_eval_id`` alone
    (no run exists yet). ``decision`` is what the cohort split reads — a
    ``FASTPATH_ELIGIBLE`` prediction is the only kind that can later become a fast-path
    parent outcome."""
    if not pre_eval_id:
        raise ValueError("append_predicted requires a pre_eval_id")
    obj = {
        "event": EVENT_PREDICTED,
        "ts": ts or _now_iso(),
        "pre_eval_id": pre_eval_id,
        "decision": decision,
        "difficulty_band": difficulty_band,
        "impact_band": impact_band,
        "taxonomy_sha": taxonomy_sha,
        "localization": localization if localization is not None else {},
    }
    obj.update(extra)
    _append_event(obj, stream_path)
    return obj


def bind_run(pre_eval_id, run_id, escalation_child=False, ts=None, stream_path=None,
             **extra):
    """Append the ``bind`` event (``pre_eval_id`` → ``run_id``) when the run dir is
    created. An escalation CHILD binds under the SAME ``pre_eval_id`` but its OWN
    ``run_id`` and marks ``escalation_child:true`` so cohort separation keeps it out of
    the fast-path outcome set (CR4-5 / Iron-Invariant #3)."""
    if not pre_eval_id:
        raise ValueError("bind_run requires a pre_eval_id")
    if not run_id:
        raise ValueError("bind_run requires a run_id")
    obj = {
        "event": EVENT_BIND,
        "ts": ts or _now_iso(),
        "pre_eval_id": pre_eval_id,
        "run_id": run_id,
    }
    if escalation_child:
        obj["escalation_child"] = True
    obj.update(extra)
    _append_event(obj, stream_path)
    return obj


def append_actual(pre_eval_id, run_id, escalated=False, review_result=None,
                  test_result=None, merge_pending=False, escalation_child=False,
                  ts=None, stream_path=None, **extra):
    """Append the ``actual`` event at MERGED / ESCALATION. CR5-4: a TERMINAL actual is
    emitted only AFTER the merge/commit boundary; a precision-IGNORED intermediate may be
    appended first with ``merge_pending:true`` (last-writer-wins means the terminal actual
    that follows replaces it). ``escalated:true`` marks a fast-path parent that escalated;
    ``escalation_child:true`` marks the full-pipeline child run itself."""
    if not pre_eval_id:
        raise ValueError("append_actual requires a pre_eval_id")
    if not run_id:
        raise ValueError("append_actual requires a run_id")
    obj = {
        "event": EVENT_ACTUAL,
        "ts": ts or _now_iso(),
        "pre_eval_id": pre_eval_id,
        "run_id": run_id,
        "escalated": bool(escalated),
        "review_result": review_result,
        "test_result": test_result,
    }
    if merge_pending:
        obj["merge_pending"] = True
    if escalation_child:
        obj["escalation_child"] = True
    obj.update(extra)
    _append_event(obj, stream_path)
    return obj


# ---------------------------------------------------------------------------- #
# Read side — reduce the append-only log, join, classify cohorts.
# ---------------------------------------------------------------------------- #
def _read_events(stream_path):
    """Yield ``(obj, malformed_count)``. A missing file yields nothing. A malformed line
    is skipped and counted (fail-closed: it can only SHRINK the sample, never fabricate)."""
    path = stream_path or default_stream_path()
    if not os.path.isfile(path):
        return [], 0
    objs = []
    malformed = 0
    with open(path, "r", encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except ValueError:
                malformed += 1
                continue
            if isinstance(obj, dict) and obj.get("event") in EVENTS:
                objs.append(obj)
            else:
                malformed += 1
    return objs, malformed


def _reduce_stream(stream_path=None):
    """Reduce the append-only log to last-writer-wins state.

    Returns a dict:
      {"predicted": {pre_eval_id: obj},
       "runs": {(pre_eval_id, run_id): {"bind": obj|None, "actual": obj|None}},
       "malformed": int}

    Reduce key is ``(pre_eval_id, run_id, event)`` (run_id None for predicted); the LAST
    line in file order wins.
    """
    objs, malformed = _read_events(stream_path)
    predicted = {}
    runs = {}
    for obj in objs:
        ev = obj.get("event")
        pid = obj.get("pre_eval_id")
        if not pid:
            malformed += 1
            continue
        if ev == EVENT_PREDICTED:
            predicted[pid] = obj  # last-writer-wins per (pre_eval_id, "predicted")
            continue
        rid = obj.get("run_id")
        if not rid:
            malformed += 1
            continue
        slot = runs.setdefault((pid, rid), {"bind": None, "actual": None})
        slot[ev] = obj  # last-writer-wins per (pre_eval_id, run_id, event)
    return {"predicted": predicted, "runs": runs, "malformed": malformed}


def _review_passed(review_result):
    return isinstance(review_result, str) and review_result.lower() in _REVIEW_PASSED


def _is_escalation_child(slot):
    """A run is an escalation child if either its bind or its actual says so."""
    for key in ("bind", "actual"):
        ev = slot.get(key)
        if isinstance(ev, dict) and ev.get("escalation_child"):
            return True
    return False


def _terminal_actual(slot):
    """The run's terminal ``actual`` (merge complete), or None. A ``merge_pending`` actual
    is NOT terminal (CR5-4) and is treated like a missing actual."""
    a = slot.get("actual")
    if not isinstance(a, dict):
        return None
    if a.get("merge_pending"):
        return None
    return a


def _cohorts(stream_path=None):
    """Split reduced runs into the two cohorts, honoring Iron-Invariant #3.

    Returns:
      {"fastpath": [ {pre_eval_id, run_id, actual|None, terminal:bool} ... ],
       "fullpipeline": [ ... same shape ... ],
       "malformed": int}

    A fast-path PARENT run: predicted.decision == FASTPATH_ELIGIBLE AND not
    escalation_child. Everything else (declined/missing predicted → fail-closed, or an
    escalation child) is full-pipeline (escalation evidence only).
    """
    state = _reduce_stream(stream_path)
    predicted = state["predicted"]
    fastpath = []
    fullpipeline = []
    for (pid, rid), slot in state["runs"].items():
        pred = predicted.get(pid)
        decision = pred.get("decision") if isinstance(pred, dict) else None
        term = _terminal_actual(slot)
        entry = {
            "pre_eval_id": pid,
            "run_id": rid,
            "actual": term,
            "terminal": term is not None,
        }
        if decision == FASTPATH_DECISION and not _is_escalation_child(slot):
            fastpath.append(entry)
        else:
            fullpipeline.append(entry)
    return {"fastpath": fastpath, "fullpipeline": fullpipeline,
            "malformed": state["malformed"]}


def precision_stats(stream_path=None, min_sample_count=None, repo=None):
    """Fast-path precision + escalation-rate, computed from the fast-path PARENT outcome
    only (spec §6 / AC-12). Returns either::

        {"precision": float, "escalation_rate": float, "n": int,
         "excluded_no_terminal_actual": int}

    or, when there is nothing (or not enough) to compute::

        {"status": "insufficient", "n": int, "excluded_no_terminal_actual": int,
         "min_sample_count": int|None}

    ``n`` = ``fastpath_runs_total`` (fast-path parents WITH a terminal actual). Parents
    with no terminal actual (missing / merge_pending) are excluded from BOTH numerator and
    denominator and reported in ``excluded_no_terminal_actual`` — never fabricated.
    ``insufficient`` when ``n == 0`` or (when a floor is given) ``n < min_sample_count``.
    """
    cohorts = _cohorts(stream_path)
    fastpath = cohorts["fastpath"]
    counted = [e for e in fastpath if e["terminal"]]
    excluded = len(fastpath) - len(counted)
    total = len(counted)

    floor = None
    if min_sample_count is not None:
        floor = int(min_sample_count)

    if total == 0 or (floor is not None and total < floor):
        return {"status": "insufficient", "n": total,
                "excluded_no_terminal_actual": excluded,
                "min_sample_count": floor}

    escalated = sum(1 for e in counted if e["actual"].get("escalated"))
    passed = sum(1 for e in counted
                 if not e["actual"].get("escalated")
                 and _review_passed(e["actual"].get("review_result")))
    return {
        "precision": passed / total,
        "escalation_rate": escalated / total,
        "n": total,
        "excluded_no_terminal_actual": excluded,
    }


def tier2_lookup(min_sample_count=None, stream_path=None, repo=None):
    """Cohort-separated Tier-2 corroboration signal (Iron-Invariant #3). Returns either::

        {"health": "healthy"|"unhealthy", "n": int}     # n = fast-path cohort size

    when ``n_fastpath >= min_sample_count`` (a calibrated, accepted-fast-path cohort
    exists), or::

        {"status": "insufficient", "n": int, "escalation_evidence_n": int,
         "min_sample_count": int}

    below the floor. A full-pipeline / escalation-child outcome NEVER contributes to
    ``health`` — it only accrues as ``escalation_evidence_n``. At launch every outcome is
    full-pipeline, so this stays ``insufficient`` (escalation-only) by construction.

    ``health`` is conservative: ``healthy`` requires the sampled fast-path cohort to be
    clean (zero escalations AND every review passed); any bad outcome → ``unhealthy``
    (raises ceremony). This is evidence, never a routing input.
    """
    floor = min_sample_count
    if floor is None:
        floor = resolve_min_sample_count(repo=repo)
    floor = int(floor)

    cohorts = _cohorts(stream_path)
    fastpath_counted = [e for e in cohorts["fastpath"] if e["terminal"]]
    fullpipeline_counted = [e for e in cohorts["fullpipeline"] if e["terminal"]]
    n_fastpath = len(fastpath_counted)
    escalation_evidence_n = len(fullpipeline_counted)

    if n_fastpath < floor:
        return {"status": "insufficient", "n": n_fastpath,
                "escalation_evidence_n": escalation_evidence_n,
                "min_sample_count": floor}

    clean = all(
        (not e["actual"].get("escalated"))
        and _review_passed(e["actual"].get("review_result"))
        for e in fastpath_counted
    )
    return {"health": "healthy" if clean else "unhealthy", "n": n_fastpath}


# ---------------------------------------------------------------------------- #
# CLI.
# ---------------------------------------------------------------------------- #
def _parse_fields(pairs):
    """``k=v`` pairs → dict, with JSON-parsed values where possible (else string)."""
    out = {}
    for p in pairs or []:
        if "=" not in p:
            raise ValueError("--field expects k=v, got %r" % p)
        k, v = p.split("=", 1)
        try:
            out[k] = json.loads(v)
        except ValueError:
            out[k] = v
    return out


def main(argv):
    if "--selftest" in argv[1:]:
        return _selftest()

    parser = argparse.ArgumentParser(prog="compound-v-triage-outcomes.py")
    sub = parser.add_subparsers(dest="cmd")

    p_pred = sub.add_parser("predicted")
    p_pred.add_argument("--pre-eval-id", required=True)
    p_pred.add_argument("--decision")
    p_pred.add_argument("--difficulty-band")
    p_pred.add_argument("--impact-band")
    p_pred.add_argument("--taxonomy-sha")
    p_pred.add_argument("--field", action="append", help="extra k=v (repeatable)")
    p_pred.add_argument("--stream")

    p_bind = sub.add_parser("bind")
    p_bind.add_argument("--pre-eval-id", required=True)
    p_bind.add_argument("--run-id", required=True)
    p_bind.add_argument("--escalation-child", action="store_true")
    p_bind.add_argument("--stream")

    p_act = sub.add_parser("actual")
    p_act.add_argument("--pre-eval-id", required=True)
    p_act.add_argument("--run-id", required=True)
    p_act.add_argument("--escalated", action="store_true")
    p_act.add_argument("--review-result")
    p_act.add_argument("--test-result")
    p_act.add_argument("--merge-pending", action="store_true")
    p_act.add_argument("--escalation-child", action="store_true")
    p_act.add_argument("--field", action="append", help="extra k=v (repeatable)")
    p_act.add_argument("--stream")

    for name in ("precision", "tier2"):
        q = sub.add_parser(name)
        q.add_argument("--repo")
        q.add_argument("--min-sample", type=int)
        q.add_argument("--stream")

    args = parser.parse_args(argv[1:])
    if not args.cmd:
        parser.print_usage(sys.stderr)
        return 2

    try:
        if args.cmd == "predicted":
            obj = append_predicted(
                args.pre_eval_id, decision=args.decision,
                difficulty_band=args.difficulty_band, impact_band=args.impact_band,
                taxonomy_sha=args.taxonomy_sha, stream_path=args.stream,
                **_parse_fields(args.field))
            print(json.dumps(obj, ensure_ascii=False))
            return 0
        if args.cmd == "bind":
            obj = bind_run(args.pre_eval_id, args.run_id,
                           escalation_child=args.escalation_child, stream_path=args.stream)
            print(json.dumps(obj, ensure_ascii=False))
            return 0
        if args.cmd == "actual":
            obj = append_actual(
                args.pre_eval_id, args.run_id, escalated=args.escalated,
                review_result=args.review_result, test_result=args.test_result,
                merge_pending=args.merge_pending, escalation_child=args.escalation_child,
                stream_path=args.stream, **_parse_fields(args.field))
            print(json.dumps(obj, ensure_ascii=False))
            return 0
        if args.cmd == "precision":
            print(json.dumps(precision_stats(stream_path=args.stream,
                                              min_sample_count=args.min_sample,
                                              repo=args.repo), indent=2))
            return 0
        if args.cmd == "tier2":
            print(json.dumps(tier2_lookup(min_sample_count=args.min_sample,
                                          stream_path=args.stream, repo=args.repo),
                             indent=2))
            return 0
    except ValueError as e:
        sys.stderr.write("error: %s\n" % e)
        return 1
    return 2


# ---------------------------------------------------------------------------- #
# Self-test (TDD — written first).
# ---------------------------------------------------------------------------- #
def _selftest():
    import tempfile

    failures = []

    def expect(name, cond):
        print(("  ok   - " if cond else "  FAIL - ") + name)
        if not cond:
            failures.append(name)

    with tempfile.TemporaryDirectory() as td:
        stream = os.path.join(td, "memdir", STREAM_BASENAME)

        # --- THREE append events joined on pre_eval_id (never a mutated line) --------
        pid = "2026-07-11T181200Z-make-button-red-a1b2"
        rid = "2026-07-11-make-button-red"
        append_predicted(pid, decision=FASTPATH_DECISION, difficulty_band="low",
                         impact_band="low", ts="2026-07-11T18:12:00Z", stream_path=stream,
                         localization={"resolved_paths": ["src/ui/button.css"],
                                       "fan_out": 1, "flags": []})
        bind_run(pid, rid, ts="2026-07-11T18:20:00Z", stream_path=stream)
        append_actual(pid, rid, escalated=False, review_result="approved",
                      test_result="pass", ts="2026-07-11T18:40:00Z", stream_path=stream,
                      diff_files=1, diff_lines=3, sensitive_hit=False)
        with open(stream, "r", encoding="utf-8") as fh:
            lines = [l for l in fh.read().splitlines() if l.strip()]
        expect("three separate appended lines", len(lines) == 3)
        expect("line 1 is predicted", json.loads(lines[0])["event"] == EVENT_PREDICTED)
        expect("line 2 is bind", json.loads(lines[1])["event"] == EVENT_BIND)
        expect("line 3 is actual", json.loads(lines[2])["event"] == EVENT_ACTUAL)
        state = _reduce_stream(stream)
        expect("reduce joins predicted on pre_eval_id", pid in state["predicted"])
        expect("reduce joins run on (pre_eval_id, run_id)", (pid, rid) in state["runs"])
        expect("bind + actual under one run slot",
               state["runs"][(pid, rid)]["bind"] is not None
               and state["runs"][(pid, rid)]["actual"] is not None)

        # --- append_line discipline: NEVER writes anywhere but triage-outcomes.jsonl --
        def wrong_basename():
            _append_event({"event": EVENT_BIND, "pre_eval_id": "x", "run_id": "y"},
                          stream_path=os.path.join(td, "routing-lessons.md"))
        try:
            wrong_basename()
            expect("refuses a non-triage-outcomes basename", False)
        except ValueError:
            expect("refuses a non-triage-outcomes basename", True)

        # --- Tier 2 insufficient below min_sample (single fast-path outcome) ----------
        t2 = tier2_lookup(min_sample_count=5, stream_path=stream)
        expect("tier2 insufficient below min_sample",
               t2.get("status") == "insufficient" and t2["n"] == 1)
        expect("tier2 reports the floor", t2["min_sample_count"] == 5)
        t2ok = tier2_lookup(min_sample_count=1, stream_path=stream)
        expect("tier2 at/above floor yields a health signal", "health" in t2ok)
        expect("clean fast-path cohort is healthy", t2ok["health"] == "healthy")

        # === A full-pipeline outcome is NOT low-corroboration (escalation evidence) ===
        stream2 = os.path.join(td, "fp", STREAM_BASENAME)
        fpid = "2026-07-11T090000Z-refactor-auth-zz99"
        frid = "2026-07-11-refactor-auth"
        append_predicted(fpid, decision="FULL_PIPELINE", difficulty_band="high",
                         impact_band="high", stream_path=stream2)
        bind_run(fpid, frid, stream_path=stream2)
        # A perfectly clean, non-escalated, review-passed FULL-PIPELINE outcome...
        append_actual(fpid, frid, escalated=False, review_result="approved",
                      test_result="pass", stream_path=stream2)
        t2fp = tier2_lookup(min_sample_count=1, stream_path=stream2)
        expect("full-pipeline outcome does NOT create a healthy signal",
               t2fp.get("status") == "insufficient")
        expect("full-pipeline outcome accrues as escalation evidence ONLY",
               t2fp["escalation_evidence_n"] == 1 and t2fp["n"] == 0)
        pfp = precision_stats(stream_path=stream2)
        expect("full-pipeline outcome contributes nothing to precision",
               pfp.get("status") == "insufficient" and pfp["n"] == 0)

        # === Precision numerator/denominator match declared fixtures =================
        # 4 fast-path PARENTS with terminal actuals:
        #   P1 not-escalated + approved   -> numerator hit
        #   P2 not-escalated + approved   -> numerator hit
        #   P3 escalated (child minted)   -> denominator only (escalation)
        #   P4 not-escalated + changes    -> denominator only (review failed)
        # + 1 fast-path parent P5 with NO terminal actual (only merge_pending) -> excluded
        # + P3's escalation CHILD (own run-id) -> escalation evidence, NEVER precision
        stream3 = os.path.join(td, "prec", STREAM_BASENAME)

        def fastpath_run(tag, escalated, review, merge_pending_only=False):
            ppid = "PID-" + tag
            prid = "RUN-" + tag
            append_predicted(ppid, decision=FASTPATH_DECISION, difficulty_band="low",
                             impact_band="low", stream_path=stream3)
            bind_run(ppid, prid, stream_path=stream3)
            if merge_pending_only:
                append_actual(ppid, prid, escalated=False, review_result=review,
                              merge_pending=True, stream_path=stream3)
            else:
                append_actual(ppid, prid, escalated=escalated, review_result=review,
                              test_result="pass", stream_path=stream3)
            return ppid, prid

        fastpath_run("P1", False, "approved")
        fastpath_run("P2", False, "approved")
        p3id, _ = fastpath_run("P3", True, "approved")   # escalated parent
        fastpath_run("P4", False, "changes_requested")   # review NOT passed
        fastpath_run("P5", False, "approved", merge_pending_only=True)  # excluded
        # P3's escalation child: SAME pre_eval_id, its OWN run-id, marked escalation_child.
        child_rid = "RUN-P3-child"
        bind_run(p3id, child_rid, escalation_child=True, stream_path=stream3)
        append_actual(p3id, child_rid, escalated=False, review_result="approved",
                      test_result="pass", escalation_child=True, stream_path=stream3)

        prec = precision_stats(stream_path=stream3)
        # denominator = P1,P2,P3,P4 = 4 (P5 merge_pending excluded, child excluded).
        expect("fastpath_runs_total = 4 (merge_pending + child excluded)", prec["n"] == 4)
        expect("one parent excluded for no terminal actual (merge_pending)",
               prec["excluded_no_terminal_actual"] == 1)
        # numerator = P1,P2 = 2 (not escalated AND review passed).
        expect("precision = 2/4", abs(prec["precision"] - 0.5) < 1e-9)
        # escalation_rate = P3 = 1/4.
        expect("escalation_rate = 1/4", abs(prec["escalation_rate"] - 0.25) < 1e-9)

        # CR4-5: the escalation child did NOT overwrite the parent's terminal outcome.
        cohorts = _cohorts(stream3)
        parent_p3 = [e for e in cohorts["fastpath"]
                     if e["pre_eval_id"] == p3id and e["run_id"] == "RUN-P3"]
        child_p3 = [e for e in cohorts["fullpipeline"]
                    if e["pre_eval_id"] == p3id and e["run_id"] == child_rid]
        expect("parent P3 stays in the fast-path cohort (escalated:true intact)",
               len(parent_p3) == 1 and parent_p3[0]["actual"]["escalated"] is True)
        expect("escalation child is full-pipeline cohort (never fast-path)",
               len(child_p3) == 1)
        expect("escalation child accrues as escalation evidence, not precision",
               all(not (e["pre_eval_id"] == p3id and e["run_id"] == child_rid)
                   for e in cohorts["fastpath"]))

        # === Duplicate / out-of-order: last-writer-wins per (pre_eval_id, event) ======
        stream4 = os.path.join(td, "lww", STREAM_BASENAME)
        did = "PID-DUP"
        drid = "RUN-DUP"
        # actual appended BEFORE bind (out of order) + a first, later-corrected verdict.
        append_predicted(did, decision=FASTPATH_DECISION, stream_path=stream4)
        append_actual(did, drid, escalated=False, review_result="approved",
                      stream_path=stream4)                       # first (wins? no)
        bind_run(did, drid, stream_path=stream4)                 # out-of-order bind
        append_actual(did, drid, escalated=True, review_result="approved",
                      stream_path=stream4)                       # corrected -> LAST wins
        redu = _reduce_stream(stream4)
        expect("out-of-order bind still joins the run", (did, drid) in redu["runs"])
        expect("last-writer-wins: latest actual (escalated:true) wins",
               redu["runs"][(did, drid)]["actual"]["escalated"] is True)
        pdup = precision_stats(stream_path=stream4)
        expect("last-writer-wins reflected in precision (escalated, 0/1 passed)",
               pdup["n"] == 1 and abs(pdup["precision"] - 0.0) < 1e-9
               and abs(pdup["escalation_rate"] - 1.0) < 1e-9)
        # A duplicate predicted with a changed decision: last one wins.
        append_predicted(did, decision="FULL_PIPELINE", stream_path=stream4)
        pdup2 = precision_stats(stream_path=stream4)
        expect("last predicted (FULL_PIPELINE) reclassifies the run out of fast-path",
               pdup2.get("status") == "insufficient" and pdup2["n"] == 0)

        # === merge_pending precedes a terminal actual (CR5-4) ========================
        stream5 = os.path.join(td, "mp", STREAM_BASENAME)
        mpid, mrid = "PID-MP", "RUN-MP"
        append_predicted(mpid, decision=FASTPATH_DECISION, stream_path=stream5)
        bind_run(mpid, mrid, stream_path=stream5)
        append_actual(mpid, mrid, escalated=False, review_result="approved",
                      merge_pending=True, stream_path=stream5)   # precision-IGNORED
        pmp = precision_stats(stream_path=stream5)
        expect("merge_pending-only run is insufficient (excluded, not fabricated)",
               pmp.get("status") == "insufficient" and pmp["n"] == 0
               and pmp["excluded_no_terminal_actual"] == 1)
        append_actual(mpid, mrid, escalated=False, review_result="approved",
                      test_result="pass", stream_path=stream5)   # terminal AFTER merge
        pmp2 = precision_stats(stream_path=stream5)
        expect("terminal actual after merge is counted (1/1)",
               pmp2["n"] == 1 and abs(pmp2["precision"] - 1.0) < 1e-9)

        # === Missing actual → excluded from precision, logged (never fabricated) =====
        stream6 = os.path.join(td, "miss", STREAM_BASENAME)
        append_predicted("PID-A", decision=FASTPATH_DECISION, stream_path=stream6)
        bind_run("PID-A", "RUN-A", stream_path=stream6)           # bound, no actual yet
        append_predicted("PID-B", decision=FASTPATH_DECISION, stream_path=stream6)
        bind_run("PID-B", "RUN-B", stream_path=stream6)
        append_actual("PID-B", "RUN-B", escalated=False, review_result="approved",
                      test_result="pass", stream_path=stream6)
        pmiss = precision_stats(stream_path=stream6)
        expect("bound-but-no-actual parent excluded from denominator",
               pmiss["n"] == 1 and pmiss["excluded_no_terminal_actual"] == 1)

        # === Malformed lines are skipped, never crash / fabricate ====================
        stream7 = os.path.join(td, "bad", STREAM_BASENAME)
        append_predicted("PID-G", decision=FASTPATH_DECISION, stream_path=stream7)
        bind_run("PID-G", "RUN-G", stream_path=stream7)
        append_actual("PID-G", "RUN-G", escalated=False, review_result="approved",
                      test_result="pass", stream_path=stream7)
        with open(stream7, "a", encoding="utf-8") as fh:
            fh.write("this is not json\n")
            fh.write('{"event":"predicted"}\n')       # missing pre_eval_id
            fh.write('{"event":"bogus","pre_eval_id":"x"}\n')  # unknown event
        st7 = _reduce_stream(stream7)
        expect("malformed / unknown lines counted, not crashing", st7["malformed"] >= 2)
        p7 = precision_stats(stream_path=stream7)
        expect("valid outcome still computes despite malformed neighbors", p7["n"] == 1)

        # === Empty / missing stream → insufficient (never fail open) =================
        pempty = precision_stats(stream_path=os.path.join(td, "nope", STREAM_BASENAME))
        expect("missing stream -> precision insufficient",
               pempty.get("status") == "insufficient" and pempty["n"] == 0)
        t2empty = tier2_lookup(min_sample_count=5,
                               stream_path=os.path.join(td, "nope", STREAM_BASENAME))
        expect("missing stream -> tier2 insufficient (escalation-only)",
               t2empty.get("status") == "insufficient")

        # === min_sample floor applies to precision when supplied =====================
        pfloor = precision_stats(stream_path=stream3, min_sample_count=99)
        expect("precision insufficient below an explicit floor",
               pfloor.get("status") == "insufficient" and pfloor["n"] == 4)

        # === resolve_min_sample_count reads the shared config (default 5) ============
        expect("min_sample default resolves to 5 for an un-onboarded repo",
               resolve_min_sample_count(repo=td) == 5)

    if failures:
        print("\nSELFTEST FAILED: %d case(s)" % len(failures))
        return 1
    print("\nSELFTEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
