from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from . import run
from .escalate import classify_diff
from .run import RunError
from .scope import check
from .snapshot import ignored_env_digest, tree
from .usage import run_cost

KEY_PATH = Path.home() / ".claude/compound-v/receipt.key"
STEPS = ("tests", "review", "live", "scope")
WAIVABLE = ("live",)
BLOCKING = ("blocker", "high")
MAX_ROUNDS = 2
TIMEOUT_PY = Path(__file__).resolve().parents[1] / "compound-v-run-with-timeout.py"
SEVERITIES = ("blocker", "high", "medium", "low")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _key() -> bytes:
    path = Path(KEY_PATH)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        key = path.read_bytes()
        if len(key) < 32:
            raise RunError(f"receipt key {path} is damaged; delete it to start over")
        return key
    with os.fdopen(fd, "wb") as f:
        f.write(os.urandom(32))
    return path.read_bytes()


def _mac(receipt: dict) -> str:
    body = json.dumps({k: v for k, v in receipt.items() if k != "mac"}, sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hmac.new(_key(), body, hashlib.sha256).hexdigest()


def _current(repo, rec) -> dict:
    return {"snapshot": tree(repo), "ignored_env": ignored_env_digest(repo),
            "acceptance_rev": rec.get("acceptance_rev"), "tier": rec["tier"]}


def _store(repo, rec, step, cur, fields) -> dict:
    receipt = {"step": step, "run": rec["id"], "at": _now(), "exit": None, "cmd": None,
               "duration_s": None, "tail": "", **cur, **fields}
    receipt["mac"] = _mac(receipt)
    rec["receipts"][step] = receipt
    run.save(repo, rec)
    return receipt


def required(rec, repo) -> list:
    diff = classify_diff(repo, rec["base_commit"])
    if rec["tier"] == "light" and diff["tier"] == "full":
        rec["tier"] = "full"
        rec["receipts"] = {}
        rec.setdefault("escalations", []).append({"at": _now(), "reasons": diff["reasons"]})
        run.save(repo, rec)
    if rec["tier"] == "full":
        return list(STEPS)
    return ["tests", "scope"] + (["live"] if diff["touches_ui"] else [])


def _tail(*paths) -> str:
    lines = []
    for p in paths:
        try:
            lines += Path(p).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            pass
    return "\n".join(line[:300] for line in lines[-20:])


def execute(cmd, cwd, timeout_s, stdin_file=None):
    with tempfile.TemporaryDirectory(prefix="cv-step-") as tmp:
        out, err = os.path.join(tmp, "out"), os.path.join(tmp, "err")
        argv = ["sh", "-c", cmd] if isinstance(cmd, str) else list(cmd)
        if stdin_file:
            argv = ["sh", "-c", 'f=$1; shift; exec "$@" < "$f"', "sh", str(stdin_file), *argv]
        t0 = time.monotonic()
        p = subprocess.run([sys.executable, str(TIMEOUT_PY), "--timeout", str(int(timeout_s)),
                            "--cwd", str(cwd), "--stdout", out, "--stderr", err,
                            "--max-output-bytes", "1000000", "--", *argv],
                           stdin=subprocess.DEVNULL)
        return p.returncode, _tail(out, err), round(time.monotonic() - t0, 3)


def run_step(repo, rec, step) -> dict:
    if step not in ("tests", "live", "scope"):
        raise RunError(f"unknown step {step!r}")
    required(rec, repo)
    cur = _current(repo, rec)
    if step == "scope":
        allow = list(rec["change_set"]) + [g for gs in rec["lanes"].values() for g in gs]
        res = check(repo, rec["base_commit"], allow)
        ok = res["verdict"] == "pass"
        return _store(repo, rec, step, cur, {
            "result": "pass" if ok else "fail", "exit": 0 if ok else 1, "cmd": "scope",
            "violations": res["violations"], "tail": "\n".join(res["violations"][:20])})
    key = "test_cmd" if step == "tests" else "live_cmd"
    cmd = rec.get(key)
    if not cmd:
        return _store(repo, rec, step, cur, {"result": "error", "reason": f"no {key}"})
    rc, tail, dur = execute(cmd, repo, rec.get("timeout_s") or run.TIMEOUT_S)
    fields = {"exit": rc, "cmd": cmd, "duration_s": dur, "tail": tail,
              "result": "pass" if rc == 0 else "fail"}
    if rc in (124, 127):
        fields.update(result="error", reason="timeout" if rc == 124 else "command not found")
    elif tree(repo) != cur["snapshot"]:
        fields.update(result="error",
                      reason="the step changed the working tree; gitignore what it writes")
    if step == "tests":
        gone = sorted(p for p in rec.get("test_files", {}) if not (Path(repo) / p).is_file())
        if gone:
            fields.update(result="fail", reason="tests removed: " + ", ".join(gone[:20]))
    return _store(repo, rec, step, cur, fields)


def _validate(data) -> None:
    if not isinstance(data, dict) or not isinstance(data.get("snapshot"), str) \
            or not isinstance(data.get("summary"), str) \
            or not isinstance(data.get("findings"), list):
        raise RunError("findings JSON needs snapshot, summary and findings[]")
    for f in data["findings"]:
        if not isinstance(f, dict) or not all(k in f for k in
                                              ("id", "severity", "title", "evidence", "reproduce")):
            raise RunError("each finding needs id, severity, title, evidence, reproduce")
        if f["severity"] not in SEVERITIES:
            raise RunError(f"finding {f.get('id')}: severity must be one of {SEVERITIES}")


def findings_path(repo, rec, n) -> Path:
    return Path(repo) / run.RUNS / f"{rec['id']}-review-{n}.json"


def record_review(repo, rec, findings_file, reviewer) -> dict:
    if reviewer not in ("codex", "claude"):
        raise RunError("reviewer must be codex or claude")
    if rec["review_round"] >= MAX_ROUNDS:
        raise RunError("review rounds exhausted")
    try:
        data = json.loads(Path(findings_file).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise RunError(f"cannot read findings {findings_file}: {e}") from None
    _validate(data)
    cur = _current(repo, rec)
    if data["snapshot"] != cur["snapshot"]:
        return _store(repo, rec, "review", cur, {
            "result": "error", "reason": "stale review", "cmd": reviewer,
            "review_snapshot": data["snapshot"]})
    n = rec["review_round"] + 1
    dest = findings_path(repo, rec, n)
    dest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    open_ = [f["id"] for f in data["findings"] if f["severity"] in BLOCKING]
    result = "fail" if open_ else "pass"
    rec["review_round"] = n
    rec.setdefault("reviews", []).append({"round": n, "result": result, "reviewer": reviewer,
                                          "open": open_, "file": f"{run.RUNS}/{dest.name}"})
    return _store(repo, rec, "review", cur, {
        "result": result, "cmd": reviewer, "round": n, "findings": data["findings"],
        "findings_file": f"{run.RUNS}/{dest.name}",
        "tail": data["summary"][:2000], "open": open_})


def waive(repo, rec, step, reason: str) -> dict:
    if step not in WAIVABLE:
        raise RunError(f"only {', '.join(WAIVABLE)} can be waived")
    if not reason.strip():
        raise RunError("a waiver needs the user's reason")
    rec["waivers"][step] = {"reason": reason.strip(), "at": _now(),
                            "by": "user-in-chat (not machine-verifiable)"}
    run.save(repo, rec)
    return rec["waivers"][step]


def budget(rec) -> dict:
    limit, spent = rec.get("budget_usd"), run_cost(rec)
    split, by = rec.get("budget_split") or run.BUDGET_SPLIT, rec.get("usage_by_stage") or {}
    over = [s for s, v in sorted(by.items()) if limit and s in split and v > split[s] * limit]
    return {"limit": limit, "spent": spent, "known": spent is not None,
            "exceeded": spent is not None and bool(limit) and spent > limit,
            "by_stage": by, "stage_exceeded": over}


def status(repo, rec) -> dict:
    req = required(rec, repo)
    cur = _current(repo, rec)
    out = {"missing": [], "stale": [], "failed": [], "waived": [], "errors": []}
    for step in req:
        r = rec["receipts"].get(step)
        valid = bool(r) and hmac.compare_digest(str(r.get("mac", "")), _mac(r))
        current = valid and all(r.get(k) == v for k, v in cur.items())
        if current and r.get("result") == "pass":
            continue
        if step in rec["waivers"] and step in WAIVABLE:
            out["waived"].append(step)
        elif not r:
            out["missing"].append(step)
        elif not current:
            out["stale"].append(step)
        elif r.get("result") == "fail":
            out["failed"].append(step)
        else:
            out["errors"].append(step)
    reviews = rec.get("reviews", [])
    exhausted = rec["review_round"] >= MAX_ROUNDS and bool(reviews) \
        and reviews[-1]["result"] != "pass"
    b = budget(rec)
    if rec.get("outcome"):
        outcome = rec["outcome"]
    elif exhausted or b["exceeded"] or out["errors"]:
        outcome = "incomplete"
    elif not (out["missing"] or out["stale"] or out["failed"]):
        outcome = "verified"
    elif out["failed"] and rec["review_round"] >= MAX_ROUNDS:
        outcome = "failed"
    else:
        outcome = "pending"
    return {"outcome": outcome, "required": req, **out, "rounds_exhausted": exhausted,
            "budget": b}
