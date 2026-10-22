from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

from .receipts import execute
from .snapshot import materialize, tree

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "schemas/review-findings.schema.json"
PROMPT = ROOT / "skills/verify/review-prompt.md"
CHECKLISTS = ROOT / "skills/plan/checklists.md"
MODEL = "gpt-6-astra"
PLAN_PROMPT = """Review this implementation plan adversarially before anything is built. Judge it
against the user's request, not against itself: missing acceptance rows, steps that cannot be
verified, unsafe defaults, wrong order. Do not edit files. Return only JSON matching the schema,
with snapshot "plan", a terse summary and findings (evidence = plan line or file:line).

Request:
{request}

Plan ({plan}):
{text}
"""


class ReviewError(Exception):
    pass


def _section(text: str, title: str) -> str:
    m = re.search(rf"^## {title}\b.*$", text, re.M)
    if not m:
        return ""
    nxt = re.search(r"^## ", text[m.end():], re.M)
    return text[m.end():m.end() + nxt.start() if nxt else len(text)].strip()


def _read(path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def prompt(repo, rec, snapshot_id: str) -> str:
    plan = ""
    if rec.get("plan"):
        try:
            plan = (Path(repo) / rec["plan"]).read_text(encoding="utf-8")
        except OSError:
            pass
    previous = ""
    if rec.get("reviews"):
        last = Path(repo) / rec["reviews"][-1]["file"]
        try:
            prior = json.loads(last.read_text(encoding="utf-8"))["findings"]
        except (OSError, ValueError, KeyError):
            prior = []
        previous = ("<previous_round>\nThis is the last review round. First check each finding "
                    "from the previous round: report it again with the same id if it is not "
                    "fixed, and name the fixed ones in the summary. Then look for regressions "
                    "the fixes introduced.\n" + json.dumps(prior, ensure_ascii=False, indent=1)
                    + "\n</previous_round>")
    slots = {"{request}": rec.get("request") or "(none recorded)",
             "{acceptance}": _section(plan, "Acceptance") or "(no acceptance table)",
             "{checklists}": _read(CHECKLISTS) or "(no checklists file)",
             "{snapshot}": snapshot_id, "{setup_cmd}": rec.get("setup_cmd") or "none",
             "{previous}": previous}
    text = PROMPT.read_text(encoding="utf-8")
    for k, v in slots.items():
        text = text.replace(k, v)
    return text


def _codex(cwd, out_path: Path, prompt_text: str, sandbox: str, model, timeout_s) -> dict:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()
    with tempfile.TemporaryDirectory(prefix="cv-prompt-") as tmp:
        pf = Path(tmp) / "prompt.md"
        pf.write_text(prompt_text, encoding="utf-8")
        argv = ["codex", "exec", "-s", sandbox, "-C", str(cwd), "--skip-git-repo-check",
                "--ephemeral", "--output-schema", str(SCHEMA), "-o", str(out_path)]
        if sandbox == "workspace-write":
            argv += ["-c", "sandbox_workspace_write.network_access=false"]
        rc, tail, dur = execute(argv + ["-m", model, "-"], cwd, timeout_s, stdin_file=pf)
    if rc != 0:
        raise ReviewError(f"codex exited {rc}: {tail.splitlines()[-1] if tail else ''}")
    try:
        data = json.loads(out_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ReviewError(f"codex output is not JSON: {e}") from None
    if not isinstance(data, dict):
        raise ReviewError("codex output is not a JSON object")
    data["_duration_s"] = dur
    return data


def codex(repo, rec, out_path, *, model=MODEL, timeout_s=1200) -> Path:
    tid = tree(repo)
    with tempfile.TemporaryDirectory(prefix="cv-review-") as tmp:
        dest = Path(tmp) / "checkout"
        materialize(repo, tid, dest)
        if rec.get("setup_cmd"):
            rc, tail, _ = execute(rec["setup_cmd"], dest, timeout_s)
            if rc != 0:
                raise ReviewError(f"setup_cmd exited {rc}: {tail[-300:]}")
        data = _codex(dest, out_path, prompt(repo, rec, tid), "workspace-write", model,
                      timeout_s)
    data.pop("_duration_s", None)
    data["snapshot"] = tid
    Path(out_path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
    return Path(out_path)


def codex_plan(repo, plan_path, out_path, *, model=MODEL, timeout_s=900, request="") -> Path:
    text = (Path(repo) / plan_path).read_text(encoding="utf-8")
    body = PLAN_PROMPT.format(request=request or "(see plan)", plan=plan_path, text=text)
    _codex(repo, out_path, body, "read-only", model, timeout_s)
    return Path(out_path)
