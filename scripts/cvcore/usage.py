from __future__ import annotations

import json
import mmap
import re
from pathlib import Path

from . import run

NEEDLE = b'"cost-state"'
BEFORE_BUILD = ("brainstorm", "preflight", "plan")
PRICES = json.loads(Path(__file__).with_name("prices.json").read_text(encoding="utf-8"))  # cited


def _parse(line: bytes):
    try:  # a line still being written is skipped; reading it as "no turn yet" restarted the count
        d = json.loads(line.decode("utf-8"))
        if isinstance(d, dict) and d.get("type") == "cost-state":
            return {"session": d.get("sessionId"), "total_usd": float(d["totalCostUSD"]),
                    "unknown_cost": bool(d.get("hasUnknownModelCost"))}
    except (ValueError, KeyError, TypeError):
        return None


def last_cost_state(transcript):
    """The newest cost-state anywhere in the file (mapped, not read), its offset, the timestamp before it."""
    try:
        with open(transcript, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as buf:
            end = len(buf)
            while (i := buf.rfind(NEEDLE, 0, end)) != -1:
                start, stop = buf.rfind(b"\n", 0, i), buf.find(b"\n", i)
                found = _parse(buf[start + 1:stop if stop != -1 else len(buf)])
                if found:
                    ts = re.findall(rb'"timestamp": ?"([^"]+)"', buf[max(0, start - 262144):start + 1])
                    return dict(found, offset=start + 1, anchor=ts[-1].decode() if ts else "")
                end = max(start, 0)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):  # also an empty file
        return None


def _requests(main: Path, offset: int, anchor: str) -> list:  # after the anchor, main + subagents
    out = {}  # subagents/**/ takes in Workflow agents (subagents/workflows/wf_*/agent-*.jsonl)
    for path in [main, *sorted(main.with_suffix("").glob("subagents/**/agent-*.jsonl"))]:
        with open(path, "rb") as f:
            f.seek(offset if path == main else 0)
            for line in f:
                try:
                    d = json.loads(line) if b'"usage"' in line else {}
                except ValueError:
                    continue
                m, ts = (d.get("message"), d.get("timestamp")) if isinstance(d, dict) else (None, None)
                if isinstance(m, dict) and d.get("type") == "assistant" and isinstance(ts, str) \
                        and isinstance(m.get("usage"), dict) and ts > anchor:
                    out[m.get("id") or d.get("uuid")] = (ts, m)
    return list(out.values())


def _usd(m: dict):
    """List price of one response; None when its model, a price modifier or a count is not covered."""
    u, model = m["usage"], m.get("model")
    w = u.get("cache_creation") if isinstance(u.get("cache_creation"), dict) else {}
    try:
        w1 = w.get("ephemeral_1h_input_tokens") or 0
        toks = [float(u.get("input_tokens") or 0), float(w.get("ephemeral_5m_input_tokens", (
            u.get("cache_creation_input_tokens") or 0) - w1) or 0), float(w1),
            float(u.get("cache_read_input_tokens") or 0), float(u.get("output_tokens") or 0)]
        searches = float((u.get("server_tool_use") or {}).get("web_search_requests") or 0)
    except (TypeError, ValueError, AttributeError):
        return None
    long = PRICES["long_prompt"].get(model, {})
    rate = long["prices"] if sum(toks[:4]) > long.get("over_tokens", 1e18) else PRICES["models"].get(model)
    if rate is None or u.get("speed") not in (None, "standard") or u.get("inference_geo") not in (None, "", "global"):
        return None
    return sum(t * r for t, r in zip(toks, rate)) / 1e6 + searches * PRICES["web_search_usd"]


def apply_cost(rec, session_id, cs, baseline=None) -> bool:
    total, u = cs["total_usd"], rec.setdefault("usage", {}).get(session_id)
    by = rec.setdefault("usage_by_stage", {})
    key = "before_build" if rec["stage"] in BEFORE_BUILD else rec["stage"]
    seen = {k: cs.get(k, d) for k, d in (("cli_usd", total), ("estimated_usd", 0.0), ("unpriced", 0))}
    if u is None:
        start = cs.get("at_created", total) if baseline is None else baseline
        rec["usage"][session_id] = {"start_usd": start, "last_usd": total, **seen,
                                    "start_estimated": baseline is None and start > seen["cli_usd"],
                                    "unknown_cost": cs["unknown_cost"]}
        if total > start:
            by[key] = round(by.get(key, 0.0) + total - start, 6)
        return True
    if total == u["last_usd"] and seen["unpriced"] == u.get("unpriced", 0) \
            and (u.get("unknown_cost") or not cs["unknown_cost"]):
        return False
    if seen["cli_usd"] < u.get("cli_usd", u["last_usd"]):  # a new process; never an estimate
        u["start_usd"], u["last_usd"] = u["start_usd"] - u["last_usd"], 0.0
    by[key] = round(max(0.0, by.get(key, 0.0) + total - u["last_usd"]), 6)
    u.update(seen, last_usd=total, unknown_cost=bool(u.get("unknown_cost") or cs["unknown_cost"]))
    return True


def cost_state(session_id, transcript_path, created_at=None):
    """The CLI's last cost-state (turn end) plus the later requests, priced as an estimate."""
    if not (session_id and transcript_path):
        return None
    path = Path(transcript_path)
    try:
        cs = last_cost_state(path)
        if cs is None and path.is_file():  # no turn has finished yet
            cs = {"session": session_id, "total_usd": 0.0, "unknown_cost": False, "offset": 0, "anchor": ""}
        priced = [(t, _usd(m)) for t, m in _requests(path, cs["offset"], cs["anchor"])]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None  # also: a missing transcript
    known = [(t, v) for t, v in priced if v is not None]
    cs.update(cli_usd=cs["total_usd"], estimated_usd=round(sum(v for _, v in known), 6), unpriced=len(priced) - len(known))
    cs["total_usd"] = round(cs["cli_usd"] + cs["estimated_usd"], 6)
    at = str(created_at or "").replace("+00:00", "Z")  # run.start writes UTC
    before = [v for t, v in priced if t <= at]  # a later unpriced request does not move the start
    if at and at >= cs["anchor"] and None not in before:
        cs["at_created"] = round(cs["cli_usd"] + sum(before), 6)
    return cs


def record(repo, rec, session_id, transcript_path, baseline=None) -> dict:
    cs = cost_state(session_id, transcript_path, rec.get("created_at"))
    if cs is not None and apply_cost(json.loads(json.dumps(rec)), session_id, cs, baseline):
        run.update(repo, rec, lambda r: apply_cost(r, session_id, cs, baseline))
    return rec


def run_cost(rec):
    sessions = list((rec.get("usage") or {}).values())
    if not sessions or any(u.get("unknown_cost") or u.get("unpriced") for u in sessions):
        return None
    return round(sum(u["last_usd"] - u["start_usd"] for u in sessions), 6)


def cost_basis(rec) -> str:  # 'estimate': has requests the CLI had not priced; 'unpriced': no price
    us = list((rec.get("usage") or {}).values())
    return "unpriced" if any(u.get("unpriced") for u in us) else "estimate" if any(
        u.get("estimated_usd") or u.get("start_estimated") for u in us) else "cli"
