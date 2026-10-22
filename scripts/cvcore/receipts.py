from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
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
from . import usage
from .usage import run_cost

# Inside the repo's git dir: the Claude Code sandbox lets commands write there, not to ~/.claude.
KEY_PATH = None
STEPS = ("tests", "review", "live", "scope")
WAIVABLE = ("live",)
BLOCKING = ("blocker", "high")
MAX_ROUNDS = 2
TIMEOUT_PY = Path(__file__).resolve().parents[1] / "compound-v-run-with-timeout.py"
SEVERITIES = ("blocker", "high", "medium", "low")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def key_path(repo) -> Path:
    if KEY_PATH is not None:
        return Path(KEY_PATH)
    common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=str(repo),
                            capture_output=True, text=True, check=True).stdout.strip()
    return Path(common) / "compound-v" / "receipt.key"


def _key(repo) -> bytes:
    path = key_path(repo)
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


def _mac(repo, receipt: dict) -> str:
    body = json.dumps({k: v for k, v in receipt.items() if k != "mac"}, sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hmac.new(_key(repo), body, hashlib.sha256).hexdigest()


def _current(repo, rec) -> dict:
    return {"snapshot": tree(repo), "ignored_env": ignored_env_digest(repo),
            "acceptance_rev": rec.get("acceptance_rev"), "tier": rec["tier"]}


def _receipt(repo, rec, step, cur, fields) -> dict:
    receipt = {"step": step, "run": rec["id"], "at": _now(), "exit": None, "cmd": None,
               "duration_s": None, "tail": "", **cur, **fields}
    receipt["mac"] = _mac(repo, receipt)
    return receipt


def _store(repo, rec, step, cur, fields) -> dict:
    receipt = _receipt(repo, rec, step, cur, fields)

    def apply(r):
        run._reopen(r, f"receipt {step}")
        r["receipts"][step] = receipt
    run.update(repo, rec, apply)
    return receipt


def _escalate(r: dict, reasons) -> None:
    if r["tier"] == "light" and r.get("outcome") is None:
        r["tier"] = "full"
        r["receipts"] = {}
        r.setdefault("escalations", []).append({"at": _now(), "reasons": reasons})


def required(rec, repo, write=True) -> list:
    diff = classify_diff(repo, rec["base_commit"])
    if rec["tier"] == "light" and diff["tier"] == "full" and rec.get("outcome") is None:
        if write:
            run.update(repo, rec, lambda r: _escalate(r, diff["reasons"]))
        else:
            _escalate(rec, diff["reasons"])
    if rec["tier"] == "full":
        return list(STEPS)
    return ["tests", "scope"] + (["live"] if diff["touches_ui"] else [])


BROWSER_LAUNCH = re.compile(
    r"bootstrap_check_in|Permission denied \(1100\)|failed to copy trust settings", re.I)
SOCKET_LAUNCH = re.compile(
    r"listen EPERM|(socket|bind|listen|connect|launch|spawn)[^\n]{0,80}Operation not permitted"
    r"|Operation not permitted[^\n]{0,80}(socket|bind|listen|launch|spawn)", re.I)
TEST_RAN = re.compile(r"\b[1-9]\d* (passed|passing)\b|^\s*(✓|✔|ok \d)", re.I | re.M)
TEST_RESULT = re.compile(r"\b\d+ (passed|passing|failed|failing)\b|^\s*(✓|✔|✘|×|ok \d|not ok \d)"
                         r"|^(PASS|FAIL)\b", re.I | re.M)
ASSERTION = re.compile(r"assert(ion)?(Error| failed)|\bexpected\b|expect\(", re.I)


def launch_blocked(text: str) -> bool:
    if ASSERTION.search(text) or TEST_RAN.search(text):
        return False
    return bool(BROWSER_LAUNCH.search(text)) or (
        bool(SOCKET_LAUNCH.search(text)) and not TEST_RESULT.search(text))
SANDBOX_REASON = ("the command could not start inside the sandbox — run `compound-v.py receipt "
                  "{step} --id {id}` alone, with no pipe, redirect or chain "
                  "(sandbox.excludedCommands only matches a bare call)")


def _read(*paths) -> str:
    text = []
    for p in paths:
        try:
            text.append(Path(p).read_text(encoding="utf-8", errors="replace"))
        except OSError:
            pass
    return "\n".join(text)


def _tail(text: str) -> str:
    return "\n".join(line[:300] for line in text.splitlines()[-20:])


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
        text = _read(out, err)
        return p.returncode, _tail(text), round(time.monotonic() - t0, 3), text


def run_step(repo, rec, step) -> dict:
    if step not in ("tests", "live", "scope"):
        raise RunError(f"unknown step {step!r}")
    run.reopen(repo, rec, f"receipt {step}")
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
    rc, tail, dur, text = execute(cmd, repo, rec.get("timeout_s") or run.TIMEOUT_S)
    fields = {"exit": rc, "cmd": cmd, "duration_s": dur, "tail": tail,
              "result": "pass" if rc == 0 else "fail"}
    if rc in (124, 127):
        fields.update(result="error", reason="timeout" if rc == 124 else "command not found")
    elif rc != 0 and launch_blocked(text):
        fields.update(result="error", reason=SANDBOX_REASON.format(step=step, id=rec["id"]))
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
    if not isinstance(data.get("coverage"), list) or \
            not all(isinstance(c, str) for c in data["coverage"]):
        raise RunError("findings JSON needs coverage[]: the probe ids run, or '<n> skipped: <why>'")


ROUND1_PROBES = {"0", "1", "2", "3", "4"}
_OUT_OF_BUDGET = re.compile(r"budget|turns? (ran|run) out|out of turns|no time|not checked", re.I)


def coverage_gap(repo, data: dict, rec: dict):
    cov = [c.strip() for c in data["coverage"]]
    if any(_OUT_OF_BUDGET.search(c) for c in cov) or _OUT_OF_BUDGET.search(data["summary"]):
        return "the reviewer ran out of budget or left checks undone"
    if rec["review_round"] == 0:
        done = {c.split()[0] for c in cov if c and c.split()[0].isdigit()}
        missing = sorted(ROUND1_PROBES - done)
        return f"probes {', '.join(missing)} not covered" if missing else None
    try:
        last = Path(repo) / rec["reviews"][-1]["file"]
        prior = [f["id"] for f in json.loads(last.read_text(encoding="utf-8"))["findings"]
                 if f.get("severity") in ("blocker", "high", "medium")]
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        prior = []
    missing = [i for i in prior if not any(c.split()[0] == i for c in cov if c)]
    return f"round-1 findings {', '.join(missing)} not re-checked" if missing else None


def findings_path(repo, rec, n) -> Path:
    return Path(repo) / run.RUNS / f"{rec['id']}-review-{n}.json"


def record_review(repo, rec, findings_file, reviewer) -> dict:
    if reviewer not in ("codex", "claude"):
        raise RunError("reviewer must be codex or claude")
    run.reopen(repo, rec, "review")
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
    found = None
    if reviewer == "claude":
        issued = [c for c in rec.get("checkouts", []) if c.get("tree") == data["snapshot"]]
        found = _reviewer_transcript(repo, rec, issued) if issued else None
    out = {}

    def apply(r):
        if r["review_round"] >= MAX_ROUNDS:
            raise RunError("review rounds exhausted")
        stops = _evidence(r, data["snapshot"], reviewer, found)
        if not stops:
            out["r"] = r["receipts"]["review"] = _receipt(repo, r, "review", cur, {
                "result": "error", "reason": "no reviewer run recorded", "cmd": reviewer})
            return
        stops[0]["consumed"] = True
        run._reopen(r, "review")
        gap = coverage_gap(repo, data, r)
        if gap:
            out["r"] = r["receipts"]["review"] = _receipt(repo, r, "review", cur, {
                "result": "error", "reason": f"review incomplete: {gap}", "cmd": reviewer})
            return
        n = r["review_round"] + 1
        dest = findings_path(repo, r, n)
        dest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        open_ = [f["id"] for f in data["findings"] if f["severity"] in BLOCKING]
        result = "fail" if open_ else "pass"
        r["review_round"] = n
        r.setdefault("reviews", []).append({"round": n, "result": result, "reviewer": reviewer,
                                            "open": open_, "file": f"{run.RUNS}/{dest.name}"})
        out["r"] = r["receipts"]["review"] = _receipt(repo, r, "review", cur, {
            "result": result, "cmd": reviewer, "round": n, "findings": data["findings"],
            "findings_file": f"{run.RUNS}/{dest.name}",
            "tail": data["summary"][:2000], "open": open_})
    run.update(repo, rec, apply)
    return out["r"]


def _evidence(r: dict, snap: str, reviewer: str, found) -> list:
    if reviewer == "codex":
        return [e for e in r.get("external", {}).get("codex", [])
                if e.get("ok") and e.get("tree") == snap and not e.get("consumed")]
    first = min((c["at"] for c in r.get("checkouts", []) if c.get("tree") == snap), default=None)
    stops = [s for s in r.get("reviewer_stops", [])
             if not s.get("consumed") and first and s.get("at", "") > first]
    used = {s.get("agent_id") for s in r.get("reviewer_stops", []) if s.get("consumed")}
    if not stops and found and found[0] not in used:
        r.setdefault("reviewer_stops", []).append(
            {"agent_id": found[0], "agent_type": found[1], "at": _now(), "source": "transcript"})
        stops = r["reviewer_stops"][-1:]
    return stops


def note_checkout(repo, rec, tree_id: str, dest) -> dict:
    entry = {"tree": tree_id, "dest": str(dest), "at": _now()}
    return run.update(repo, rec, lambda r: r.setdefault("checkouts", []).append(entry))


def note_reviewer_stop(repo, rec, agent_id, agent_type) -> dict:
    entry = {"agent_id": agent_id, "agent_type": agent_type, "at": _now()}
    return run.update(repo, rec, lambda r: r.setdefault("reviewer_stops", []).append(entry))


def _ts(text: str) -> datetime:
    t = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _subagent_dirs(repo, rec) -> list:
    dirs = [Path(p).with_suffix("") / "subagents" for p in (rec.get("transcripts") or {}).values()]
    home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "projects"
    for root in {str(repo), os.path.realpath(str(repo))}:
        # Undocumented layout, read fail-closed: a miss only means no evidence was found.
        dirs += sorted((home / re.sub(r"[^A-Za-z0-9-]", "-", root)).glob("*/subagents"))
    return dirs


def _reviewer_transcript(repo, rec, issued):
    used = {s.get("agent_id") for s in rec.get("reviewer_stops", []) if s.get("consumed")}
    for meta in (m for d in _subagent_dirs(repo, rec) for m in sorted(d.glob("agent-*.meta.json"))):
        try:
            kind = str(json.loads(meta.read_text(encoding="utf-8"))["agentType"])
            aid = meta.name[len("agent-"):-len(".meta.json")]
            if kind.split(":")[-1] != "reviewer" or aid in used:
                continue
            with open(meta.with_name(f"agent-{aid}.jsonl"), "rb") as f:
                body = f.read(4_000_000)
                f.seek(max(0, f.seek(0, 2) - 262_144))
                tail = f.read().rstrip(b"\n").rsplit(b"\n", 1)[-1]
            started = _ts(json.loads(body.split(b"\n", 1)[0])["timestamp"])
            last = json.loads(tail)
            if last.get("type") != "assistant" or \
                    last.get("message", {}).get("stop_reason") not in ("end_turn", "stop_sequence"):
                continue
            for c in issued:
                dest = str(c["dest"])
                forms = {dest, dest[len("/private"):] if dest.startswith("/private/") else dest}
                if started > _ts(c["at"]) and any(x.encode() in body for x in forms):
                    return aid, kind
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            continue
    return None


def _bound(rec, step, r) -> bool:
    cmd = {"tests": "test_cmd", "live": "live_cmd"}.get(step)
    return r.get("step") == step and r.get("run") == rec["id"] \
        and (cmd is None or r.get("cmd") == rec.get(cmd))


def waive(repo, rec, step, reason: str) -> dict:
    if step not in WAIVABLE:
        raise RunError(f"only {', '.join(WAIVABLE)} can be waived")
    if not reason.strip():
        raise RunError("a waiver needs the user's reason")
    run.reopen(repo, rec, f"waive {step}")
    waiver = {"reason": reason.strip(), "at": _now(), "by": "user-in-chat (not machine-verifiable)"}
    def apply(r):
        run._reopen(r, f"waive {step}")
        r["waivers"][step] = waiver
    run.update(repo, rec, apply)
    return waiver


def budget(rec) -> dict:
    limit, spent = rec.get("budget_usd"), run_cost(rec)
    split, by = rec.get("budget_split") or run.BUDGET_SPLIT, rec.get("usage_by_stage") or {}
    over = [s for s, v in sorted(by.items()) if limit and s in split and v > split[s] * limit]
    return {"limit": limit, "spent": spent, "known": spent is not None,
            "exceeded": spent is not None and bool(limit) and spent > limit,
            "by_stage": by, "stage_exceeded": over}


def status(repo, rec, write=True) -> dict:
    for sid, path in (rec.get("transcripts") or {}).items() if write else ():
        usage.record(repo, rec, sid, path)
    req = required(rec, repo, write)
    cur = _current(repo, rec)
    out = {"missing": [], "stale": [], "failed": [], "waived": [], "errors": []}
    for step in req:
        r = rec["receipts"].get(step)
        valid = bool(r) and hmac.compare_digest(str(r.get("mac", "")), _mac(repo, r))
        current = valid and _bound(rec, step, r) and all(r.get(k) == v for k, v in cur.items())
        if current and r.get("result") == "pass":
            continue
        if current and r.get("result") == "fail":
            out["failed"].append(step)
        elif step in rec["waivers"] and step in WAIVABLE:
            out["waived"].append(step)
        elif not r:
            out["missing"].append(step)
        elif not current:
            out["stale"].append(step)
        else:
            out["errors"].append(step)
    reviews = rec.get("reviews", [])
    exhausted = rec["review_round"] >= MAX_ROUNDS and bool(reviews) \
        and reviews[-1]["result"] != "pass"
    b = budget(rec)
    if exhausted or b["exceeded"] or out["errors"]:
        outcome = "incomplete"
    elif not (out["missing"] or out["stale"] or out["failed"]):
        outcome = "verified"
    elif out["failed"] and rec["review_round"] >= MAX_ROUNDS:
        outcome = "failed"
    else:
        outcome = "pending"
    # A stored incomplete/failed stays until new evidence verifies; a stored verified never hides new evidence.
    if rec.get("outcome") in ("incomplete", "failed") and outcome != "verified":
        outcome = rec["outcome"]
    return {"outcome": outcome, "required": req, **out, "rounds_exhausted": exhausted,
            "budget": b}
