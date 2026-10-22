from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import snapshot
from .gitio import GitError, repo_root


def _out(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def cmd_snapshot(a, repo):
    _out({"tree": snapshot.tree(repo), "ignored_env": snapshot.ignored_env_digest(repo)})


def cmd_checkout(a, repo):
    dest = Path(a.dest).resolve()
    tid = snapshot.materialize(repo, snapshot.tree(repo), dest)
    _out({"tree": tid, "dest": str(dest)})


def parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", default=".")
    p = argparse.ArgumentParser(prog="compound-v.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("snapshot", parents=[common]).set_defaults(fn=cmd_snapshot)
    c = sub.add_parser("checkout", parents=[common])
    c.add_argument("--dest", required=True)
    c.set_defaults(fn=cmd_checkout)
    return p


ERRORS = (GitError, snapshot.SnapshotError, OSError, ValueError)


def main(argv=None) -> int:
    a = parser().parse_args(argv)
    try:
        rc = a.fn(a, repo_root(a.repo))
    except ERRORS as e:
        print(f"compound-v: {str(e).splitlines()[0] if str(e) else type(e).__name__}",
              file=sys.stderr)
        return 2
    return rc or 0
