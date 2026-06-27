#!/usr/bin/env python3
"""
Compound V epic-state manager — multi-feature autonomous build (PRD §8 / v1.1).

A v1.0 run executes ONE plan (one feature). "Epic mode" chains several: an ordered set
of features, each run through the full v1.0 pipeline (spec -> pre-flights -> plan ->
manifest -> dispatch -> review), in dependency order, accumulating onto one branch. This
is the deterministic state spine for that meta-loop — one level up from state.json, the
same shape of discipline (resumable, topological, no daemon).

epic-state.json:
  {"epic_id", "title", "status": "running|done|blocked",
   "features": [{"id","title","depends_on":[...],"status":"pending|running|done|failed",
                 "run_id": <id|null>}]}

The orchestrator drives the loop; this script owns the bookkeeping:
  --init      build epic-state.json from a features list (validates refs + cycles)
  --next      print the next RUNNABLE feature (pending, all deps done) or a stop reason
  --update    set a feature's status/run_id
  --summary   render the feature table
  --selftest

Usage:
  compound-v-epic-state.py --init --features features.json --epic-id E --title T --out S
  compound-v-epic-state.py --next  --state S
  compound-v-epic-state.py --update --feature F --status done [--run-id R] --state S
  compound-v-epic-state.py --summary --state S

`features.json` is a JSON array: [{"id","title","depends_on":[...]}, ...].
Python 3.9-safe, stdlib only.
"""

import argparse
import json
import os
import sys

ID_RE_OK = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
STATUSES = ("pending", "running", "done", "failed")


def _id_ok(s):
    return bool(s) and s not in (".", "..") and all(c in ID_RE_OK for c in s)


def _detect_cycle(features):
    """Return a cycle path (list of ids) if the depends_on graph has one, else None."""
    graph = {f["id"]: list(f.get("depends_on", []) or []) for f in features}
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {fid: WHITE for fid in graph}
    stack = []

    def visit(node):
        color[node] = GRAY
        stack.append(node)
        for dep in graph.get(node, []):
            if dep not in graph:
                continue  # dangling ref handled separately
            if color[dep] == GRAY:
                return stack[stack.index(dep):] + [dep]
            if color[dep] == WHITE:
                c = visit(dep)
                if c:
                    return c
        color[node] = BLACK
        stack.pop()
        return None

    for fid in graph:
        if color[fid] == WHITE:
            c = visit(fid)
            if c:
                return c
    return None


def validate_features(features):
    """Return a list of error strings (empty = valid)."""
    errs = []
    if not isinstance(features, list) or not features:
        return ["features must be a non-empty list"]
    ids = []
    for i, f in enumerate(features):
        if not isinstance(f, dict):
            errs.append("feature %d is not an object" % i)
            continue
        fid = f.get("id")
        if not _id_ok(str(fid)):
            errs.append("feature %d has an invalid id %r (allowed: A-Za-z0-9._-)" % (i, fid))
        else:
            ids.append(fid)
    dup = sorted({x for x in ids if ids.count(x) > 1})
    if dup:
        errs.append("duplicate feature ids: %s" % ", ".join(dup))
    idset = set(ids)
    for f in features:
        for d in (f.get("depends_on") or []):
            if d not in idset:
                errs.append("feature %r depends_on unknown id %r" % (f.get("id"), d))
    cyc = _detect_cycle([f for f in features if isinstance(f, dict) and _id_ok(str(f.get("id")))])
    if cyc:
        errs.append("dependency cycle: %s" % " -> ".join(cyc))
    return errs


def build_state(features, epic_id, title):
    feats = []
    for f in features:
        feats.append({
            "id": f["id"],
            "title": f.get("title", f["id"]),
            "depends_on": list(f.get("depends_on", []) or []),
            "status": "pending",
            "run_id": None,
        })
    return {"epic_id": epic_id, "title": title, "status": "running", "features": feats}


def next_feature(state):
    """Return (feature|None, reason).

    The order of the guards encodes the documented stop/resume model (commands/v-epic.md):
    a failure or a crashed run HALTS the epic until a human reconciles it — the loop never
    autonomously routes around a failed/stale feature.
    """
    feats = state["features"]
    done = {f["id"] for f in feats if f["status"] == "done"}
    failed = sorted(f["id"] for f in feats if f["status"] == "failed")
    running = sorted(f["id"] for f in feats if f["status"] == "running")
    pending = [f for f in feats if f["status"] == "pending"]

    # FAIL-FAST: any failed feature halts the WHOLE epic — even independent pending
    # features wait. A failure may be systemic; do not burn more autonomous runs until a
    # human retries (--update --status pending) or drops it.
    if failed:
        return None, ("epic blocked: feature(s) failed (%s) — retry "
                      "(--update --status pending) or drop them, then re-run" % ", ".join(failed))

    # RECONCILE: epic mode is sequential — the orchestrator calls --next only BETWEEN
    # features, so a 'running' feature seen here means a prior run CRASHED mid-feature.
    # Stop and force reconciliation; never hand out new work over a stale run.
    if running:
        return None, ("epic needs reconcile: feature(s) still 'running' (%s) — a prior run "
                      "crashed; mark each --status failed (abandon) or pending (retry), then "
                      "re-run" % ", ".join(running))

    if not pending:
        return None, "epic complete: all features done"

    # Clean state: hand out the next runnable pending feature in topological order. With a
    # DAG validated at --init, one always exists here; the final return is defensive.
    runnable = [f for f in pending if all(d in done for d in f["depends_on"])]
    if runnable:
        return runnable[0], "runnable"
    return None, ("epic blocked: no runnable feature — unsatisfiable dependencies among %s"
                  % ", ".join(f["id"] for f in pending))


def _read_json(path):
    with open(path, "r", errors="replace") as fh:
        return json.load(fh)


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

    feats = [
        {"id": "auth", "title": "Auth", "depends_on": []},
        {"id": "api", "title": "API", "depends_on": ["auth"]},
        {"id": "ui", "title": "UI", "depends_on": ["api"]},
    ]
    check("valid graph", validate_features(feats) == [])
    check("dangling ref", any("unknown" in e for e in validate_features(
        [{"id": "a", "depends_on": ["nope"]}])))
    check("cycle", any("cycle" in e for e in validate_features(
        [{"id": "a", "depends_on": ["b"]}, {"id": "b", "depends_on": ["a"]}])))
    check("bad id", any("invalid id" in e for e in validate_features(
        [{"id": "../x", "depends_on": []}])))
    check("dup id", any("duplicate" in e for e in validate_features(
        [{"id": "a", "depends_on": []}, {"id": "a", "depends_on": []}])))

    st = build_state(feats, "e1", "Epic")
    f, why = next_feature(st)
    check("first runnable = auth", f and f["id"] == "auth")
    st["features"][0]["status"] = "done"
    f, _ = next_feature(st)
    check("then api", f and f["id"] == "api")
    st["features"][1]["status"] = "running"
    f, why = next_feature(st)
    check("crashed 'running' -> reconcile stop", f is None and "reconcile" in why)
    st["features"][1]["status"] = "done"
    st["features"][2]["status"] = "done"
    f, why = next_feature(st)
    check("complete", f is None and "complete" in why)
    # failed dependency blocks dependents
    st2 = build_state(feats, "e2", "E")
    st2["features"][0]["status"] = "failed"
    f, why = next_feature(st2)
    check("blocked by failed dep", f is None and "blocked" in why)
    # FAIL-FAST (#1): a failure halts even an INDEPENDENT pending feature
    indep = [{"id": "x", "depends_on": []}, {"id": "y", "depends_on": []}]
    st3 = build_state(indep, "e3", "E")
    st3["features"][0]["status"] = "failed"
    f, why = next_feature(st3)
    check("fail-fast halts independent pending", f is None and "blocked" in why)
    # recovery (#1): retrying the failed feature re-opens the epic
    st3["features"][0]["status"] = "pending"
    f, why = next_feature(st3)
    check("retry re-opens epic", f is not None and f["id"] in ("x", "y"))
    print("SELFTEST: %d ok, %d fail" % (ok, fail))
    return 0 if fail == 0 else 1


def main(argv):
    p = argparse.ArgumentParser(description="Compound V epic-state manager.")
    p.add_argument("--init", action="store_true")
    p.add_argument("--next", dest="want_next", action="store_true")
    p.add_argument("--update", action="store_true")
    p.add_argument("--summary", action="store_true")
    p.add_argument("--selftest", action="store_true")
    p.add_argument("--features", help="features list JSON (for --init)")
    p.add_argument("--epic-id", default="epic")
    p.add_argument("--title", default="")
    p.add_argument("--state", help="path to epic-state.json")
    p.add_argument("--out", help="output path for --init (default = --state)")
    p.add_argument("--feature", help="feature id (for --update)")
    p.add_argument("--status", choices=STATUSES)
    p.add_argument("--run-id")
    args = p.parse_args(argv)

    if args.selftest:
        return _selftest()

    if args.init:
        if not args.features:
            p.error("--init needs --features <json>")
        feats = _read_json(args.features)
        errs = validate_features(feats)
        if errs:
            for e in errs:
                print("epic-init error: %s" % e, file=sys.stderr)
            return 1
        state = build_state(feats, args.epic_id, args.title or args.epic_id)
        out = args.out or args.state
        if not out:
            p.error("--init needs --out (or --state)")
        od = os.path.dirname(out)
        if od and not os.path.isdir(od):
            os.makedirs(od)
        with open(out, "w") as fh:
            fh.write(json.dumps(state, indent=2) + "\n")
        print("wrote %s (%d features)" % (out, len(state["features"])))
        return 0

    if not args.state or not os.path.exists(args.state):
        p.error("--state <epic-state.json> is required and must exist")
    state = _read_json(args.state)

    if args.want_next:
        f, why = next_feature(state)
        print(json.dumps({"feature": f, "reason": why}))
        return 0 if f is not None or "complete" in why else 0  # info, not an error

    if args.update:
        if not args.feature or not args.status:
            p.error("--update needs --feature and --status")
        hit = None
        for f in state["features"]:
            if f["id"] == args.feature:
                hit = f
                break
        if hit is None:
            print("epic-update error: no feature %r" % args.feature, file=sys.stderr)
            return 1
        hit["status"] = args.status
        if args.run_id is not None:
            hit["run_id"] = args.run_id
        # roll up epic status (fail-fast: any failure blocks the epic immediately)
        sts = [f["status"] for f in state["features"]]
        if all(s == "done" for s in sts):
            state["status"] = "done"
        elif any(s == "failed" for s in sts):
            state["status"] = "blocked"
        else:
            state["status"] = "running"
        with open(args.state, "w") as fh:
            fh.write(json.dumps(state, indent=2) + "\n")
        print(json.dumps({"feature": args.feature, "status": args.status, "epic_status": state["status"]}))
        return 0

    if args.summary:
        print("EPIC %s — %s  [%s]" % (state.get("epic_id"), state.get("title"), state.get("status")))
        for f in state["features"]:
            deps = ",".join(f["depends_on"]) or "-"
            print("  [%-7s] %-20s deps=%s run=%s" % (f["status"], f["id"], deps, f["run_id"] or "-"))
        return 0

    p.error("one of --init / --next / --update / --summary / --selftest is required")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
