from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import run, snapshot
from .gitio import GitError, repo_root


def _out(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def cmd_snapshot(a, repo):
    _out({"tree": snapshot.tree(repo), "ignored_env": snapshot.ignored_env_digest(repo)})


def cmd_checkout(a, repo):
    dest = Path(a.dest).resolve()
    tid = snapshot.materialize(repo, snapshot.tree(repo), dest)
    _out({"tree": tid, "dest": str(dest)})


def _pick(repo, a) -> dict:
    if getattr(a, "id", None):
        return run.load(repo, a.id)
    rec = run.active(repo, getattr(a, "session", None))
    if rec is None:
        raise run.RunError("no open run (pass --id)")
    return rec


def cmd_run(a, repo):
    if a.action == "start":
        src = sys.stdin if a.request_file == "-" else open(a.request_file, encoding="utf-8")
        with src:
            request = src.read().strip()
        rec = run.start(repo, tier=a.tier, request=request, spec=a.spec, base=a.base,
                        change_set=a.change_set)
    elif a.action == "stage":
        rec = run.set_stage(repo, _pick(repo, a), a.to)
    elif a.action == "plan":
        rec = run.attach_plan(repo, _pick(repo, a), a.plan)
    elif a.action == "bind":
        rec = run.bind(repo, _pick(repo, argparse.Namespace(id=a.id)), a.session)
    else:
        rec = _pick(repo, a)
    _out(rec)


def parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", default=".")
    p = argparse.ArgumentParser(prog="compound-v.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("snapshot", parents=[common]).set_defaults(fn=cmd_snapshot)
    c = sub.add_parser("checkout", parents=[common])
    c.add_argument("--dest", required=True)
    c.set_defaults(fn=cmd_checkout)
    r = sub.add_parser("run").add_subparsers(dest="action", required=True)
    withid = argparse.ArgumentParser(add_help=False, parents=[common])
    withid.add_argument("--id")
    s = r.add_parser("start", parents=[common])
    s.add_argument("--tier", required=True, choices=run.TIERS)
    s.add_argument("--request-file", required=True)
    s.add_argument("--spec")
    s.add_argument("--base", default="HEAD")
    s.add_argument("--change-set", action="append", default=[])
    r.add_parser("stage", parents=[withid]).add_argument("--to", required=True,
                                                         choices=run.STAGES)
    r.add_parser("plan", parents=[withid]).add_argument("--plan", required=True)
    r.add_parser("show", parents=[withid])
    r.add_parser("bind", parents=[withid]).add_argument("--session", required=True)
    for name in ("start", "stage", "plan", "show", "bind"):
        r.choices[name].set_defaults(fn=cmd_run)
    return p


ERRORS = (GitError, run.RunError, snapshot.SnapshotError, OSError, ValueError)


def main(argv=None) -> int:
    a = parser().parse_args(argv)
    try:
        rc = a.fn(a, repo_root(a.repo))
    except ERRORS as e:
        print(f"compound-v: {str(e).splitlines()[0] if str(e) else type(e).__name__}",
              file=sys.stderr)
        return 2
    return rc or 0
