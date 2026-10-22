from __future__ import annotations

from collections import Counter

from .gitio import git, zsplit
from .receipts import status
from .run import active
from .usage import run_cost

NEXT = {"brainstorm": "brainstorm", "preflight": "build", "plan": "build", "build": "build",
        "verify": "verify"}


def _steps(s: dict) -> dict:
    marks = {}
    for key, mark in (("missing", "missing"), ("stale", "stale"), ("failed", "fail"),
                      ("waived", "waived"), ("errors", "error")):
        for step in s[key]:
            marks[step] = mark
    return {step: marks.get(step, "pass") for step in s["required"]}


def band(repo, session_id=None) -> dict:
    rec = active(repo, session_id)
    if rec is None:
        return {}
    s = status(repo, rec)
    return {"run": rec["id"], "stage": rec["stage"], "tier": rec["tier"], "steps": _steps(s),
            "review_round": rec["review_round"], "outcome": s["outcome"],
            "cost_usd": run_cost(rec)}


def brief(repo, session_id=None) -> str:
    b = band(repo, session_id)
    if not b:
        return ""
    parts = []
    for mark in ("missing", "stale", "fail", "error"):
        steps = [k for k, v in b["steps"].items() if v == mark]
        if steps:
            parts.append(f"{mark} {', '.join(steps)}")
    if b["cost_usd"] is not None:
        parts.append(f"cost ${b['cost_usd']:.2f}")
    nxt = NEXT.get(b["stage"], "verify")
    if b["stage"] == "build" and b["tier"] == "light":
        nxt = "verify"
    head = f"Compound V run {b['run']}: stage {b['stage']} ({b['tier']}); "
    return head + "; ".join(parts or ["all steps current"]) + f"; next: /compound-v:{nxt}"


def cochange(repo, paths, max_commits=500, top=10) -> list:
    out = git(repo, "log", "-z", "--name-only", "--no-renames", "--pretty=format:%x01",
              "-n", str(max_commits))
    want, counts = set(paths), Counter()
    for chunk in out.split(b"\x01"):
        files = set(zsplit(chunk.strip(b"\n")))
        if files & want:
            counts.update(files - want)
    return [{"path": p, "count": n}
            for p, n in sorted(counts.items(), key=lambda x: (-x[1], x[0]))[:top]]
