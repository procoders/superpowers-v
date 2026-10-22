from __future__ import annotations

import json
from pathlib import Path

from . import run

NEEDLE = b'"cost-state"'
BLOCK = 1 << 20
BEFORE_BUILD = ("brainstorm", "preflight", "plan")


def _parse(line: bytes):
    d = json.loads(line.decode("utf-8"))
    if not isinstance(d, dict) or d.get("type") != "cost-state":
        return None
    per_model = {m: float(v["costUSD"]) for m, v in (d.get("modelUsage") or {}).items()
                 if isinstance(v, dict) and "costUSD" in v}
    return {"session": d.get("sessionId"), "total_usd": float(d["totalCostUSD"]),
            "per_model": per_model, "unknown_cost": bool(d.get("hasUnknownModelCost"))}


def last_cost_state(transcript, max_tail_bytes=8_000_000):
    try:
        with open(transcript, "rb") as f:
            f.seek(0, 2)
            pos = f.tell()
            limit = max(0, pos - max_tail_bytes)
            buf = b""
            while pos > limit:
                step = min(BLOCK, pos - limit)
                pos -= step
                f.seek(pos)
                buf = f.read(step) + buf
                first_nl = buf.find(b"\n")
                end = len(buf)
                while True:
                    i = buf.rfind(NEEDLE, 0, end)
                    if i == -1:
                        break
                    start = buf.rfind(b"\n", 0, i)
                    if start == -1 and pos > 0:
                        break
                    stop = buf.find(b"\n", i)
                    found = _parse(buf[start + 1:stop if stop != -1 else len(buf)])
                    if found:
                        return found
                    end = start if start != -1 else 0
                # Everything after the first newline is whole lines already searched.
                if first_nl != -1:
                    buf = buf[:first_nl + 1]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
    return None


def _stage_key(stage: str) -> str:
    return "before_build" if stage in BEFORE_BUILD else stage


def session_total(transcript_path, max_tail_bytes=8_000_000):
    cs = last_cost_state(Path(transcript_path), max_tail_bytes) if transcript_path else None
    if cs is not None:
        return cs["total_usd"]
    try:
        # A transcript shorter than the tail scan with no cost-state has not finished a turn.
        return 0.0 if Path(transcript_path).stat().st_size <= max_tail_bytes else None
    except (OSError, TypeError):
        return None


def apply_cost(rec, session_id, cs, baseline=None) -> bool:
    total, u = cs["total_usd"], rec.setdefault("usage", {}).get(session_id)
    by = rec.setdefault("usage_by_stage", {})
    key = _stage_key(rec["stage"])
    if u is None:
        rec["usage"][session_id] = {"start_usd": total if baseline is None else baseline,
                                    "last_usd": total, "unknown_cost": cs["unknown_cost"]}
        if baseline is not None and total > baseline:
            by[key] = round(by.get(key, 0.0) + total - baseline, 6)
        return True
    if total == u["last_usd"] and (u.get("unknown_cost") or not cs["unknown_cost"]):
        return False
    if total < u["last_usd"]:
        u["start_usd"] -= u["last_usd"]
        delta = total
    else:
        delta = total - u["last_usd"]
    by[key] = round(by.get(key, 0.0) + delta, 6)
    u["last_usd"] = total
    u["unknown_cost"] = u.get("unknown_cost") or cs["unknown_cost"]
    return True


def cost_state(session_id, transcript_path):
    return last_cost_state(Path(transcript_path)) if transcript_path and session_id else None


def record(repo, rec, session_id, transcript_path, baseline=None) -> dict:
    cs = cost_state(session_id, transcript_path)
    if cs is not None and apply_cost(json.loads(json.dumps(rec)), session_id, cs, baseline):
        run.update(repo, rec, lambda r: apply_cost(r, session_id, cs, baseline))
    return rec


def run_cost(rec):
    sessions = list((rec.get("usage") or {}).values())
    if not sessions or any(u.get("unknown_cost") for u in sessions):
        return None
    return round(sum(u["last_usd"] - u["start_usd"] for u in sessions), 6)
