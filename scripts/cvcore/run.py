from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .gitio import git, require_commit, resolve, zsplit
from .scope import matches
from .snapshot import CANON, excludes, unhashed

RUNS = "docs/compound-v/runs"
STAGES = ("brainstorm", "preflight", "plan", "build", "verify", "done")
TIERS = ("light", "full")
BUDGET_USD = 7
BUDGET_SPLIT = {"before_build": 0.25, "build": 0.45, "verify": 0.30}
TEST_GLOBS = ["**/test*/**", "**/*test*.*", "**/*.spec.*"]
TIMEOUT_S = 900
_STR, _NUM = (str,), (int, float)
REQUIRED = (("test_cmd", _STR), ("change_set", list), ("is_web", bool), ("live_cmd", _STR))
OPTIONAL = (("setup_cmd", _STR), ("lanes", dict), ("budget_usd", _NUM),
            ("budget_split", dict), ("test_globs", list), ("timeout_s", _NUM))


try:
    import fcntl
except ImportError:  # Windows: run records are written without a lock
    fcntl = None

LOCK_WAIT_S = 30.0


class RunError(Exception):
    pass


def _dir(repo) -> Path:
    return Path(repo) / RUNS


def _config(repo) -> dict:
    try:
        cfg = json.loads((Path(repo) / ".claude/compound-v.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return cfg if isinstance(cfg, dict) else {}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:24].strip("-") or "run"


def hash_test_files(repo, globs) -> dict:
    out = git(repo, *CANON, "ls-files", "-z", "--cached", "--others", "--exclude-standard",
              "--", ".", *excludes(unhashed(repo)))
    found = {}
    for p in sorted(set(zsplit(out))):
        full = Path(repo) / p
        if matches(p, globs) and full.is_file() and not full.is_symlink():
            found[p] = hashlib.sha256(full.read_bytes()).hexdigest()
    return found


def start(repo, *, tier, request: str, spec=None, base: str = "HEAD", change_set=None,
          session_id=None, live_cmd=None) -> dict:
    if tier not in TIERS:
        raise RunError(f"tier must be one of {', '.join(TIERS)}")
    require_commit(repo)
    base_commit = resolve(repo, base)
    cfg = _config(repo)
    now = datetime.now(timezone.utc)
    d = _dir(repo)
    d.mkdir(parents=True, exist_ok=True)
    stem = now.strftime("%Y%m%d-%H%M%S-") + _slug(request)
    rid, n = stem, 1
    while True:
        try:
            os.close(os.open(str(d / f"{rid}.json"), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            break
        except FileExistsError:
            n += 1
            rid = f"{stem}-{n}"
    rec = {
        "id": rid, "created_at": now.isoformat(timespec="microseconds"),
        "tier": tier, "stage": "brainstorm" if tier == "full" else "build",
        "request": request, "spec": spec, "plan": None, "base_commit": base_commit,
        "change_set": list(change_set or []), "lanes": {},
        "test_cmd": cfg.get("test_cmd"), "live_cmd": live_cmd or cfg.get("live_cmd"),
        "setup_cmd": None, "is_web": bool(cfg.get("is_web", False)),
        "budget_usd": cfg.get("budget_usd", BUDGET_USD), "budget_split": dict(BUDGET_SPLIT),
        "reviewer": cfg.get("reviewer"), "test_globs": list(TEST_GLOBS), "timeout_s": TIMEOUT_S,
        "acceptance_rev": None, "test_files": hash_test_files(repo, TEST_GLOBS),
        "review_round": 0, "receipts": {}, "waivers": {}, "stop_refusals": [],
        "sessions": [session_id] if session_id else [], "usage": {}, "usage_by_stage": {},
        "escalations": [], "lane_state": {}, "external": {}, "outcome": None,
    }
    save(repo, rec)
    return rec


def load(repo, run_id: str) -> dict:
    if not run_id or "/" in run_id or run_id.startswith("."):
        raise RunError(f"bad run id: {run_id!r}")
    try:
        return json.loads((_dir(repo) / f"{run_id}.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise RunError(f"no run {run_id}") from None
    except ValueError as e:
        raise RunError(f"run {run_id} is not valid JSON: {e}") from None


def save(repo, rec: dict) -> None:
    d = _dir(repo)
    d.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(d), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, str(d / f"{rec['id']}.json"))
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


@contextmanager
def _locked(repo, run_id: str):
    d = _dir(repo)
    d.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(d / f".{run_id}.lock"), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        if fcntl:
            deadline = time.monotonic() + LOCK_WAIT_S
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise RunError(f"run {run_id} is busy (lock held)") from None
                    time.sleep(0.02)
        yield
    finally:
        os.close(fd)


def update(repo, rec, fn) -> dict:
    rid = rec if isinstance(rec, str) else rec["id"]
    with _locked(repo, rid):
        fresh = load(repo, rid)
        fn(fresh)
        save(repo, fresh)
    if isinstance(rec, dict):
        rec.clear()
        rec.update(fresh)
    return fresh


def _open_runs(repo) -> list:
    runs = []
    for p in _dir(repo).glob("*.json"):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(rec, dict) and rec.get("id") == p.stem and "stage" in rec \
                and rec.get("outcome") is None:
            runs.append(rec)
    return sorted(runs, key=lambda r: (str(r.get("created_at", "")), r["id"]), reverse=True)


def open_runs(repo) -> list:
    return _open_runs(repo)


def active(repo, session_id=None):
    runs = _open_runs(repo)
    if session_id is None:
        return runs[0] if runs else None
    for rec in runs:
        if session_id in rec.get("sessions", []):
            return rec
    for rec in runs:
        if not rec.get("sessions"):
            return rec
    return None


def bind(repo, rec: dict, session_id) -> dict:
    def apply(r):
        if session_id not in r.setdefault("sessions", []):
            r["sessions"].append(session_id)
    if session_id and session_id not in rec.get("sessions", []):
        update(repo, rec, apply)
    return rec


def _reopen(r: dict, reason: str) -> None:
    if r.get("outcome") in ("incomplete", "failed"):
        r.setdefault("outcomes", []).append({
            "outcome": r["outcome"], "reason": reason,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        r["outcome"] = None


def reopen(repo, rec: dict, reason: str) -> dict:
    if rec.get("outcome") in ("incomplete", "failed"):
        update(repo, rec, lambda r: _reopen(r, reason))
    return rec


def set_stage(repo, rec: dict, stage: str) -> dict:
    if stage not in STAGES:
        raise RunError(f"unknown stage {stage!r}")

    def apply(r):
        _reopen(r, f"stage {stage}")
        if r.get("outcome") is not None:
            raise RunError(f"run {r['id']} is closed ({r['outcome']})")
        cur, new = STAGES.index(r["stage"]), STAGES.index(stage)
        if new < cur and (r["stage"], stage) != ("verify", "build"):
            raise RunError(f"cannot move run back from {r['stage']} to {stage}")
        r["stage"] = stage
    return update(repo, rec, apply)


def _check(data: dict, key: str, typ, required: bool) -> None:
    if key not in data or data[key] is None:
        if required:
            raise RunError(f"compound-v-plan block is missing {key}")
        return
    v = data[key]
    ok = isinstance(v, typ) and not (typ == _NUM and isinstance(v, bool))
    if ok and typ is list:
        ok = all(isinstance(x, str) for x in v)
    if ok and key == "lanes":
        ok = all(isinstance(g, list) and all(isinstance(x, str) for x in g) for g in v.values())
    if ok and key == "budget_split":
        ok = set(v) == set(BUDGET_SPLIT) and all(isinstance(x, _NUM) for x in v.values())
    if not ok:
        raise RunError(f"compound-v-plan block has a bad {key}")


def attach_plan(repo, rec: dict, plan_path) -> dict:
    path = Path(repo) / plan_path
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise RunError(f"cannot read plan {plan_path}: {e}") from None
    blocks = re.findall(r"^```compound-v-plan[ \t]*\n(.*?)^```[ \t]*$", text, re.M | re.S)
    if len(blocks) != 1:
        raise RunError(f"plan needs exactly one compound-v-plan block, found {len(blocks)}")
    try:
        data = json.loads(blocks[0])
    except ValueError as e:
        raise RunError(f"compound-v-plan block is not JSON: {e}") from None
    if not isinstance(data, dict):
        raise RunError("compound-v-plan block must be a JSON object")
    for key, typ in REQUIRED:
        _check(data, key, typ, True)
    for key, typ in OPTIONAL:
        _check(data, key, typ, False)
    head = re.search(r"^## Acceptance\b.*$", text, re.M)
    if not head:
        raise RunError("plan has no '## Acceptance' section")
    nxt = re.search(r"^## ", text[head.end():], re.M)
    section = text[head.start():head.end() + nxt.start() if nxt else len(text)]
    globs = data.get("test_globs") or list(TEST_GLOBS)
    try:
        rel = path.resolve().relative_to(Path(repo).resolve()).as_posix()
    except ValueError:
        rel = str(path)
    fields = {
        "plan": rel, "test_cmd": data["test_cmd"], "live_cmd": data["live_cmd"],
        "is_web": data["is_web"], "change_set": data["change_set"],
        "setup_cmd": data.get("setup_cmd"), "lanes": data.get("lanes") or {},
        "budget_usd": data.get("budget_usd", BUDGET_USD),
        "budget_split": data.get("budget_split") or dict(BUDGET_SPLIT),
        "test_globs": globs, "timeout_s": data.get("timeout_s", TIMEOUT_S),
        "acceptance_rev": hashlib.sha256(section.encode("utf-8")).hexdigest(),
    }
    hashed = hash_test_files(repo, globs)
    return update(repo, rec, lambda r: r.update(
        fields, test_files={**hashed, **(r.get("test_files") or {})}))
