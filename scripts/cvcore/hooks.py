from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from . import run, usage
from .escalate import classify_request, is_action
from .gitio import GitError, git, repo_root, require_commit, zsplit
from .hud import brief
from .receipts import note_reviewer_stop, status
from .scope import changed
from .snapshot import tree

MAX_ATTEMPTS = 3
CONFIG = ".claude/compound-v.json"
FULL_TEXT = ("Compound V: this is a change request (full). "
             "Start with the compound-v:brainstorm skill.")
LIGHT_TEXT = "Compound V: small change (light). Make it, then run the compound-v:verify skill."
SETUP_TEXT = "Compound V is installed but not set up here — run /compound-v:init."
NO_RUN_TEXT = ("This session got a change request but no Compound V run was started. Start one "
               "with the compound-v skills, or say that no files changed and stop again.")
EARLY_TEXT = ("Code changed before the plan was attached to run {id}. Attach the plan and move to "
              "build, or revert, then stop again.")
CONTINUE_TEXT = ("Continue with /compound-v:verify, or, if you are waiting on the user or a step "
                 "cannot run, say so and stop again — the run will be recorded incomplete.")
_READ = re.compile(r"^(read|show me|explain|summari[sz]e|look at|cat)\s")
_GREETING = re.compile(
    r"^(hi|hello|hey|yo|ok|okay|k|thanks|thank you|thx|ty|yes|yep|no|nope|sure|cool|great|nice"
    r"|got it|good|perfect|done|привет|спасибо|ок|окей|да|нет|понял|отлично|хорошо|супер)"
    r"( there| a lot| so much| you)?$")
WRITE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")


def default_state_dir() -> Path:
    d = Path(os.environ.get("CV_STATE_DIR") or
             Path(tempfile.gettempdir()) / f"compound-v-{os.getuid()}")
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    return d


def _key(session) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(session or "none"))[:80]


def _block(reason: str) -> dict:
    return {"decision": "block", "reason": reason}


def _code_changed(repo, old_tree: str, new_tree: str) -> list:
    out = git(repo, "diff-tree", "-r", "--name-only", "-z", "--no-renames", old_tree, new_tree)
    return [p for p in zsplit(out) if not p.startswith("docs/")]


def _attach(repo, rec, sid, transcript, sd: Path) -> None:
    base = sd / f"baseline-{_key(sid)}"
    baseline = None
    try:
        baseline = float(base.read_text()) if base.exists() else None
    except ValueError:
        pass
    cs = usage.cost_state(sid, transcript, rec.get("created_at"))

    def apply(r):
        if sid not in r.setdefault("sessions", []):
            r["sessions"].append(sid)
        if transcript:
            r.setdefault("transcripts", {})[sid] = transcript
        if cs is not None:
            usage.apply_cost(r, sid, cs, None if sid in (r.get("usage") or {}) else baseline)
    run.update(repo, rec, apply)
    if base.exists() and sid in (rec.get("usage") or {}):
        base.unlink()


def stop_hook(payload: dict, repo: Path, budget_s=6.0, state_dir=None):
    t0 = time.monotonic()
    try:
        if payload.get("hook_event_name") != "Stop" or not payload.get("session_id"):
            return None
        sid, again = payload["session_id"], bool(payload.get("stop_hook_active"))
        sd = Path(state_dir) if state_dir else default_state_dir()
        change, refused = sd / f"change-{_key(sid)}", sd / f"bypass-refused-{_key(sid)}"
        rec = run.active(repo, sid)
        if rec is None:
            if change.exists() and not refused.exists() and not again \
                    and _code_changed(repo, change.read_text().strip(), tree(repo)):
                refused.touch()
                return _block(NO_RUN_TEXT)
            return None
        if change.exists():
            change.unlink()
        _attach(repo, rec, sid, payload.get("transcript_path"), sd)
        if rec["stage"] in ("brainstorm", "preflight", "plan"):
            early = [p for p in changed(repo, rec["base_commit"]) if not p.startswith("docs/")]
            key = f"{tree(repo)}:{rec['stage']}:early-code"
            if early and not again and key not in rec["stop_refusals"]:
                run.update(repo, rec, lambda r: r["stop_refusals"].append(key))
                return _block(EARLY_TEXT.format(id=rec["id"]))
            return None
        if rec["stage"] not in ("build", "verify") or time.monotonic() - t0 > budget_s:
            return None
        said = {}

        # Judged on the fresh record under its lock, so evidence written meanwhile is never overruled.
        def decide(r):
            if r.get("outcome") or r["stage"] not in ("build", "verify"):
                return
            s = said["s"] = status(repo, r, write=False)
            key = f"{tree(repo)}:{r['stage']}"
            if s["outcome"] == "verified":
                r.update(outcome="verified", stage="done")
            elif key in r["stop_refusals"]:
                r["outcome"] = "failed" if s["failed"] else "incomplete"
            elif not again:
                r["stop_refusals"].append(key)
                said["block"] = True
        run.update(repo, rec, decide)
        if said.get("block"):
            return _block(f"Compound V run {rec['id']} is not verified: {_gaps(said['s'])}. "
                          + CONTINUE_TEXT)
        return None
    except Exception as e:
        _fail_open(repo, "stop", e)
        return None


def _fail_open(repo, hook: str, e: Exception) -> None:
    try:
        _event(repo, {"event": "hook_error", "hook": hook, "error": str(e)[:200]})
    except Exception:
        pass


def subagent_stop_hook(payload: dict, repo: Path, state_dir=None):
    try:
        kind = str(payload.get("agent_type") or "")
        if payload.get("hook_event_name") != "SubagentStop":
            return None
        sid = payload.get("session_id")
        live, own = (run.active(repo, sid), run.reopenable(repo, sid)) if sid else (None, None)
        bound = live is not None and sid in live.get("sessions", [])  # read before _attach adds the session
        if live is not None and (bound or own is None):  # binds a run started inside this turn, so its cost is seen
            _attach(repo, live, sid, payload.get("transcript_path"), Path(state_dir or default_state_dir()))
        if kind.split(":")[-1] != "reviewer":
            _event(repo, {"event": "subagent_stop", "agent_type": kind, "recorded": False})
            return None
        # the reviewer works on the newest checkout; without one the session's own run (even one the Stop hook closed) wins
        rec = max((r for r in (live, own) if r is not None), default=None, key=lambda r: (
            max((str(c.get("at", "")) for c in r.get("checkouts", [])), default=""), r is own or bound))
        if rec is not None:
            note_reviewer_stop(repo, rec, payload.get("agent_id"), kind)
        _event(repo, {"event": "subagent_stop", "agent_type": kind, "recorded": rec is not None})
    except Exception:
        pass
    return None


def _event(repo, row: dict) -> None:
    path = Path(repo) / run.RUNS / "triage.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **row}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def _gaps(s: dict) -> str:
    parts = [f"{k} {', '.join(s[k])}" for k in ("missing", "stale", "failed", "errors") if s[k]]
    if s.get("rounds_exhausted"):
        parts.append("review rounds exhausted with findings open")
    if s["budget"].get("exceeded"):
        parts.append("budget exceeded")
    return "; ".join(parts) or s["outcome"]


def _log(repo, sid, tier, reason, chars) -> None:
    _event(repo, {"session": sid, "tier": tier, "reason": reason, "prompt_chars": chars})


HARNESS = ("<task-notification", "<system-reminder", "[system notification", "<local-command")


def _filtered(text: str):
    low = text.strip().lower()
    if low.startswith(HARNESS):
        return "harness notice"
    if low.startswith("/"):
        return "slash command"
    if 0 < len(low) <= 200 and low.endswith("?") and not is_action(low):
        return "question"
    if len(low) <= 80 and _READ.match(low) and not re.search(r"[\n;,]| and | then | also ", low):
        return "read instruction"
    if _GREETING.match(re.sub(r"[\s!.,)(]+$", "", low)):
        return "greeting"
    return None


def _once(path: Path) -> bool:
    if path.exists():
        return False
    path.touch()
    return True


def prompt_hook(payload: dict, repo: Path, state_dir: Path):
    try:
        if payload.get("hook_event_name") not in (None, "", "UserPromptSubmit"):
            return None
        sid, text = payload.get("session_id"), str(payload.get("prompt") or "")
        sd, k = Path(state_dir), _key(sid)
        sd.mkdir(parents=True, exist_ok=True)
        if not (Path(repo) / CONFIG).exists():
            return SETUP_TEXT if _once(sd / f"notice-{k}") else None
        transcript = payload.get("transcript_path")
        unbound = [r for r in run.open_runs(repo) if not r.get("sessions")]
        if unbound and sid:
            _attach(repo, unbound[0], sid, transcript, sd)
        why = _filtered(text)
        if why:
            _log(repo, sid, None, why, len(text))
            return None
        rec = run.active(repo, sid) if sid else None
        if rec and sid in rec.get("sessions", []):
            if (sd / f"change-{k}").exists():
                (sd / f"change-{k}").unlink()
            _attach(repo, rec, sid, transcript, sd)
            _log(repo, sid, rec["tier"], "open run", len(text))
            text_brief = brief(repo, sid)
            digest = hashlib.sha256(text_brief.encode()).hexdigest()
            seen = sd / f"brief-{k}"
            if seen.exists() and seen.read_text() == digest:
                return None
            seen.write_text(digest)
            return text_brief
        tier = classify_request(text)
        _arm(repo, sd, k, transcript)
        counter = sd / f"nudges-{k}"
        count = len(counter.read_text()) if counter.exists() else 0
        if count >= MAX_ATTEMPTS:
            _log(repo, sid, tier or "full", "nudges spent", len(text))
            return None
        with open(counter, "a") as f:
            f.write("x")
        _log(repo, sid, tier or "full", "classified" if tier else "unclassified", len(text))
        return LIGHT_TEXT if tier == "light" else FULL_TEXT
    except Exception:
        return None


def _arm(repo, sd: Path, k: str, transcript) -> None:
    (sd / f"change-{k}").write_text(tree(repo))
    if (sd / f"bypass-refused-{k}").exists():
        (sd / f"bypass-refused-{k}").unlink()
    base = sd / f"baseline-{k}"
    if not base.exists():
        cs = usage.cost_state("-", transcript)
        if cs is not None and not cs["unpriced"]:
            base.write_text(repr(cs["total_usd"]))


def session_hook(payload: dict, repo: Path):
    try:
        lines = [brief(repo, payload.get("session_id"))]
        manifest = Path(repo) / "docs/compound-v/architecture/.onboard-manifest.json"
        if manifest.exists():
            lines.append(_staleness(repo))
        text = "\n".join(x for x in lines if x)
        return text or None
    except Exception:
        return None


def _staleness(repo) -> str:
    script = Path(__file__).resolve().parents[1] / "compound-v-onboard.py"
    try:
        out = subprocess.run([sys.executable, str(script), "staleness", "--quiet"], cwd=str(repo),
                             capture_output=True, text=True, timeout=3).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""
    if out == "unregistered":
        return ("The onboard manifest registers no cited files, so doc staleness cannot be "
                "checked — run /compound-v:onboard --refresh.")
    if out.isdigit() and int(out) > 0:
        return (f"{out} generated doc(s) cite files that changed since they were verified — "
                "run /compound-v:onboard --refresh.")
    return ""


def guard_hook(payload: dict):
    try:
        if payload.get("tool_name") not in WRITE_TOOLS:
            return None
        ti = payload.get("tool_input") or {}
        target = ti.get("file_path") or ti.get("notebook_path")
        if not target:
            return None
        cwd = payload.get("cwd") or os.getcwd()
        try:
            root = str(repo_root(cwd))
        except GitError:
            root = cwd
        full = os.path.realpath(os.path.join(cwd, target))
        rel = os.path.relpath(full, os.path.realpath(root)).replace(os.sep, "/")
        if not rel.startswith(run.RUNS + "/"):
            return None
        return {"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": "Run records are written by scripts/compound-v.py only."}}
    except Exception:
        return None


def _context(event: str, text):
    if not text:
        return None
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}


def main(event: str) -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if not isinstance(payload, dict):
            return 0
        run.LOCK_WAIT_S = 2.0
        if event == "guard":
            out = guard_hook(payload)
        else:
            repo = repo_root(payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or ".")
            require_commit(repo)
            if event == "stop":
                out = stop_hook(payload, repo)
            elif event == "subagent":
                out = subagent_stop_hook(payload, repo)
            elif event == "prompt":
                out = _context("UserPromptSubmit", prompt_hook(payload, repo, default_state_dir()))
            else:
                out = _context("SessionStart", session_hook(payload, repo))
        if out:
            print(json.dumps(out, ensure_ascii=False))
    except Exception:
        pass
    return 0
