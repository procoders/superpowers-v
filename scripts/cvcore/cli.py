from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import escalate, hud, lanes, receipts, review, run, scope, snapshot, usage
from .gitio import GitError, repo_root


def _out(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def cmd_snapshot(a, repo):
    _out({"tree": snapshot.tree(repo), "ignored_env": snapshot.ignored_env_digest(repo)})


def cmd_checkout(a, repo):
    dest = Path(a.dest).resolve()
    tid = snapshot.materialize(repo, snapshot.tree(repo), dest)
    try:
        receipts.note_checkout(repo, _pick(repo, a), tid, dest)
    except run.RunError:
        pass
    _out({"tree": tid, "dest": str(dest)})


def _pick(repo, a) -> dict:
    if getattr(a, "id", None):
        return run.load(repo, a.id)
    if getattr(a, "session", None):
        rec = run.active(repo, a.session)
    else:
        runs = run.open_runs(repo)
        if len(runs) > 1:
            raise run.RunError(f"several open runs ({', '.join(r['id'] for r in runs)}): pass --id")
        rec = runs[0] if runs else None
    if rec is None:
        raise run.RunError("no open run (pass --id)")
    return rec


def cmd_run(a, repo):
    if a.action == "start":
        src = sys.stdin if a.request_file == "-" else open(a.request_file, encoding="utf-8")
        with src:
            request = src.read().strip()
        rec = run.start(repo, tier=a.tier, request=request, spec=a.spec, base=a.base,
                        change_set=a.change_set, live_cmd=a.live_cmd)
    elif a.action == "stage":
        rec = run.set_stage(repo, _pick(repo, a), a.to)
    elif a.action == "plan":
        rec = run.attach_plan(repo, _pick(repo, a), a.plan)
    elif a.action == "bind":
        rec = run.bind(repo, _pick(repo, argparse.Namespace(id=a.id)), a.session)
    else:
        rec = _pick(repo, a)
        if a.brief:
            print(f"{rec['id']} · stage {rec['stage']} ({rec['tier']}) · outcome "
                  f"{rec['outcome'] or 'open'} · plan {rec.get('plan') or 'none'} · test_cmd "
                  f"{rec.get('test_cmd') or 'none'} · live_cmd {rec.get('live_cmd') or 'none'} · "
                  f"reviewer {rec.get('reviewer') or 'claude'} · review round {rec['review_round']}")
            return 0
    _out(rec)


def cmd_scope(a, repo):
    rec = None if a.base and a.allow else _pick(repo, a)
    allow = a.allow or list(rec["change_set"]) + [g for gs in rec["lanes"].values() for g in gs]
    res = scope.check(repo, a.base or rec["base_commit"], allow)
    _out(res)
    return 0 if res["verdict"] == "pass" else 1


def cmd_escalate(a, repo):
    _out(escalate.classify_diff(repo, a.base or _pick(repo, a)["base_commit"]))


def cmd_classify_request(a, repo):
    src = sys.stdin if a.text_file in (None, "-") else open(a.text_file, encoding="utf-8")
    with src:
        _out({"tier": escalate.classify_request(src.read())})


def _say(a, r: dict, line: str) -> int:
    if getattr(a, "json", False):
        _out(r)
    else:
        print(line)
    return 0 if r["result"] == "pass" else 1


def _receipt_line(r: dict) -> str:
    head = f"{r['step']}: {r['result']} (exit {r.get('exit')}, {r.get('duration_s') or 0}s)"
    if r["result"] == "pass":
        return head
    lines = [head + (f" — {r['reason']}" if r.get("reason") else "")]
    return "\n".join(lines + ["  " + x for x in (r.get("tail") or "").splitlines()[-5:]])


def _review_line(r: dict) -> str:
    if r["result"] == "error":
        return f"review: error — {r.get('reason')}"
    found = r.get("findings") or []
    return (f"review round {r['round']}: {r['result']} ({len(r.get('open') or [])} blocker/high "
            f"of {len(found)} findings) {r.get('findings_file')}")


def cmd_receipt(a, repo):
    r = receipts.run_step(repo, _pick(repo, a), a.step)
    return _say(a, r, _receipt_line(r))


def cmd_review(a, repo):
    rec = _pick(repo, a)
    if a.action == "codex-plan":
        out = a.out or str(Path(repo) / run.RUNS / f"{rec['id']}-plan-review.json")
        _out({"plan_review": str(review.codex_plan(repo, a.plan, out, model=a.model,
                                                    request=rec.get("request") or ""))})
        return 0
    if a.action == "codex":
        out = receipts.findings_path(repo, rec, rec["review_round"] + 1)
        findings = review.codex(repo, rec, out, model=a.model, timeout_s=a.timeout)
        r = receipts.record_review(repo, run.load(repo, rec["id"]), findings, "codex")
    else:
        r = receipts.record_review(repo, rec, a.findings, a.reviewer)
    return _say(a, r, _review_line(r))


def cmd_waive(a, repo):
    _out(receipts.waive(repo, _pick(repo, a), a.step, a.reason))


STATUS_RC = {"verified": 0, "pending": 3, "incomplete": 4, "failed": 5}


def cmd_status(a, repo):
    s = receipts.status(repo, _pick(repo, a))
    print(json.dumps(s, ensure_ascii=False, separators=(",", ":")))
    return STATUS_RC[s["outcome"]]


def cmd_usage(a, repo):
    rec = usage.record(repo, _pick(repo, a), a.session, a.transcript)
    _out({"usage": rec.get("usage"), "usage_by_stage": rec.get("usage_by_stage"),
          "run_cost_usd": usage.run_cost(rec), "cost_basis": usage.cost_basis(rec)})


def cmd_hud(a, repo):
    if a.brief:
        print(hud.brief(repo, a.session))
    else:
        _out(hud.band(repo, a.session))


def cmd_cochange(a, repo):
    _out(hud.cochange(repo, a.path, max_commits=a.max_commits, top=a.top))


def cmd_lane(a, repo):
    r = lanes.finish(repo, _pick(repo, a), a.task, a.branch)
    _out(r)
    return 0 if r["status"] == "merged" else 1


def parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", default=".")
    p = argparse.ArgumentParser(prog="compound-v.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    withid = argparse.ArgumentParser(add_help=False, parents=[common])
    withid.add_argument("--id")
    sub.add_parser("snapshot", parents=[common]).set_defaults(fn=cmd_snapshot)
    c = sub.add_parser("checkout", parents=[withid])
    c.add_argument("--dest", required=True)
    c.set_defaults(fn=cmd_checkout)
    r = sub.add_parser("run").add_subparsers(dest="action", required=True)
    s = r.add_parser("start", parents=[common])
    s.add_argument("--tier", required=True, choices=run.TIERS)
    s.add_argument("--request-file", required=True)
    s.add_argument("--spec")
    s.add_argument("--base", default="HEAD")
    s.add_argument("--live-cmd")
    s.add_argument("--change-set", action="append", default=[])
    r.add_parser("stage", parents=[withid]).add_argument("--to", required=True,
                                                         choices=run.STAGES)
    r.add_parser("plan", parents=[withid]).add_argument("--plan", required=True)
    r.add_parser("show", parents=[withid]).add_argument("--brief", action="store_true")
    r.add_parser("bind", parents=[withid]).add_argument("--session", required=True)
    for name in ("start", "stage", "plan", "show", "bind"):
        r.choices[name].set_defaults(fn=cmd_run)
    sc = sub.add_parser("scope", parents=[withid])
    sc.add_argument("--base")
    sc.add_argument("--allow", action="append", default=[])
    sc.set_defaults(fn=cmd_scope)
    es = sub.add_parser("escalate", parents=[withid])
    es.add_argument("--base")
    es.set_defaults(fn=cmd_escalate)
    cr = sub.add_parser("classify-request", parents=[common])
    cr.add_argument("--text-file")
    cr.set_defaults(fn=cmd_classify_request)
    rc = sub.add_parser("receipt", parents=[withid])
    rc.add_argument("--json", action="store_true")
    rc.add_argument("step", choices=("tests", "live", "scope"))
    rc.set_defaults(fn=cmd_receipt)
    rv = sub.add_parser("review").add_subparsers(dest="action", required=True)
    co = rv.add_parser("codex", parents=[withid])
    co.add_argument("--json", action="store_true")
    co.add_argument("--model", default=review.MODEL)
    co.add_argument("--timeout", type=int, default=1200)
    cp = rv.add_parser("codex-plan", parents=[withid])
    cp.add_argument("--plan", required=True)
    cp.add_argument("--out")
    cp.add_argument("--model", default=review.MODEL)
    rr = rv.add_parser("record", parents=[withid])
    rr.add_argument("--json", action="store_true")
    rr.add_argument("--findings", required=True)
    rr.add_argument("--reviewer", required=True, choices=("claude",))
    for x in (co, cp, rr):
        x.set_defaults(fn=cmd_review)
    wv = sub.add_parser("waive", parents=[withid])
    wv.add_argument("step", choices=receipts.WAIVABLE)
    wv.add_argument("--reason", required=True)
    wv.set_defaults(fn=cmd_waive)
    sub.add_parser("status", parents=[withid]).set_defaults(fn=cmd_status)
    us = sub.add_parser("usage", parents=[withid])
    us.add_argument("--session", required=True)
    us.add_argument("--transcript", required=True)
    us.set_defaults(fn=cmd_usage)
    hd = sub.add_parser("hud", parents=[common])
    hd.add_argument("--brief", action="store_true")
    hd.add_argument("--session")
    hd.set_defaults(fn=cmd_hud)
    cc = sub.add_parser("cochange", parents=[common])
    cc.add_argument("--path", action="append", required=True)
    cc.add_argument("--max-commits", type=int, default=500)
    cc.add_argument("--top", type=int, default=10)
    cc.set_defaults(fn=cmd_cochange)
    ln = sub.add_parser("lane").add_subparsers(dest="action", required=True)
    lf = ln.add_parser("finish", parents=[withid])
    lf.add_argument("--task", required=True)
    lf.add_argument("--branch", required=True)
    lf.set_defaults(fn=cmd_lane)
    return p


ERRORS = (GitError, run.RunError, review.ReviewError, snapshot.SnapshotError, OSError, ValueError)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["hook"]:
        from . import hooks
        return hooks.main(argv[1] if len(argv) > 1 else "")
    a = parser().parse_args(argv)
    try:
        rc = a.fn(a, repo_root(a.repo))
    except ERRORS as e:
        print(f"compound-v: {str(e).splitlines()[0] if str(e) else type(e).__name__}",
              file=sys.stderr)
        return 2
    return rc or 0
