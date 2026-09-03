#!/usr/bin/env python3
"""
Compound V — transcript play-ahead (read-only).

Reads the workers' OWN transcripts while they are still running and reports, per
job, the five things that a person watching `/workflows` would otherwise learn
minutes later from the gate: an out-of-lane write, a wrong cwd, an error, a lane
guard denial, and a stall. It is ADVISORY. It decides nothing, acts on nothing,
and — this is the load-bearing property — writes nothing except its own state
file, which lives in the OS temp directory, never in the run directory and never
in the repository.

    scripts/compound-v-transcript-watch.py --run-dir <run> [--wf <wf_id>]
        [--transcripts <dir>] [--once | --every <s>] [--state <file>] [--json]
        [--stall-minutes N] [--selftest]

Exit code is 0 on every advisory path — including "no transcripts found", an
unreadable manifest, and a state file it could not write. Only a usage fault
(no --run-dir, a run directory that is not a directory, --every 0) exits 2. A
watcher that fails the run it is watching is worse than no watcher.

WHAT IT READS (all of it native, none of it ours)
  <session>/subagents/workflows/<wf_id>/agent-<id>.jsonl — one JSON object per
  line. `message.content` arrives in THREE shapes and a parser that knows only
  one crashes on a real transcript: a bare string (the worker's prompt, the
  first line), an array of `tool_use` / `text` / `thinking` items (assistant
  lines), and an array of `tool_result` items (the following user lines). Lines
  of `type:"attachment"` carry no `message` key at all. All four are handled.
  Alongside them: `agent-<id>.meta.json` (every key optional — `model` is absent
  on some agents, so every read is `.get()`) and `journal.jsonl`
  (`started` / `result` / `failed` per agent).

THREE RULES THIS FILE DOES NOT GET TO RE-DECIDE
  1. ONE PATH MATCHER. `is_allowed` is imported by path from
     `compound-v-scope-check.py`, exactly as `hooks/lane-guard.sh` does. A second
     glob matcher that disagreed with the gate's would report lanes the gate does
     not enforce, which is worse than reporting nothing.
  2. ONE YAML LOADER. "Python 3.9 stdlib" cannot read `manifest.yaml`;
     `load_yaml` is imported by path from `compound-v-validate-manifest.py`,
     which already prefers PyYAML and carries the subset parser's selftests.
     There is no `import yaml` in this file.
  3. AGENT → JOB COMES FROM THE AGENT'S OWN `register-lane --job-id`, never from
     `lane-map.json`'s cwd→worktree map. That map's entry for a *direct* job is
     the bare repository root, which prefix-matches every cwd in the checkout;
     reusing it is what let a finished run's job claim an unrelated agent
     (finding 68), and it would misattribute signals here the same way. An agent
     with no successful `register-lane` is reported as `(unregistered)`.

     `lane-map.json` IS read, for one narrow purpose: turning an absolute path
     into a repo-relative one for a job whose worktree the map already names.
     Only the worktrees mapped to THIS agent's own job are consulted, so another
     job's worktree can never launder a path into a lane that allows it.

AND ONE STRING IT DOES NOT GET TO GUESS
  The `denied` signal matches the literal `Compound V lane guard: job '` and
  nothing else. `Compound V lane-guard FAILED OPEN:` (hyphenated) is an
  allow-with-notice, not a denial, and the harness's own bashCommandClamp denial
  is unrelated to lanes and fires on routine retries. Folding either into
  `denied` would train the reader to ignore the signal.

  MATCHING THAT LITERAL IS NOT THE SAME AS FINDING IT ANYWHERE. Every detector
  here is ANCHORED, because this repository's prose is largely ABOUT denials,
  blocked jobs and tracebacks: an agent reading its own manifest, plan, audit or
  the guard's own source quotes all three, and a bare substring match reported
  twelve such quotes as violations. A denial counts only when it comes back from
  a tool the guard is registered on AND either the harness marked the result
  `is_error` or the literal stands at the start of a line; the error patterns
  carry the same start-of-line rule. Both render the MATCHING line as evidence,
  never the result's first line.

THE `(unregistered)` POLICY, STATED
  A write seen before any successful `register-lane` has no lane to be measured
  against, so it is reported as `out-of-lane` — the same semantics as the lane
  guard's own `lane-guard-unresolved.jsonl` record, which keeps the unresolved
  write visible rather than dropping it. Reporting nothing would make the one
  gap the guard documents about itself invisible here too.

  A path with NO repository-relative form is a different case and is not
  reported at all: `/dev/null`, a scratchpad file, another checkout. A lane is a
  repository-relative contract, so such a path is not a lane question, and
  reporting it made the first out-of-lane signal of every real run a redirect to
  `/dev/null` — on the one signal the orchestrator is told to stop a run for.

Pure stdlib beyond those two by-path imports. Python 3.9-safe.
"""

import sys

# Nobody writes bytecode. The scope gate forgives no path by extension, so a
# `.pyc` this process left beside a sibling script would BLOCK the very job it
# is watching. Set before either by-path import runs.
sys.dont_write_bytecode = True

import argparse  # noqa: E402
import glob as globmod  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shlex  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

SIGNALS = ("out-of-lane", "wrong-cwd", "error", "denied", "stall")
DEFAULT_STALL_MINUTES = 8
UNREGISTERED = "(unregistered)"

# The lane guard's genuine denial, and only that. See the module docstring.
DENY_LITERAL = "Compound V lane guard: job '"

# Read at most this much of a transcript when only asking "does it mention the
# run directory?" — discovery must stay cheap on a session with many workflows.
DISCOVERY_HEAD_BYTES = 1024 * 1024

ERROR_PATTERNS = [
    re.compile(r"Traceback \(most recent"),
    re.compile(r"Permission denied"),
    re.compile(r"command not found"),
    re.compile(r"No such file or directory"),
    re.compile(r"SELFTEST FAILED"),
    re.compile(r"\bBLOCKED\b"),
    re.compile(r"exit code [1-9]"),
]

# Tools whose input names a file this agent is about to write.
WRITE_TOOLS = {"Write": "file_path", "Edit": "file_path", "NotebookEdit": "notebook_path"}

# The tools hooks/lane-guard.sh is registered on, and therefore the only ones
# whose result can carry a genuine denial. A `Read` result that happens to
# contain the literal is a document ABOUT the guard, not a refusal by it. An
# unknown tool (an id whose tool_use fell outside the window) is left in.
DENIABLE_TOOLS = {"Write", "Edit", "NotebookEdit", "Bash", ""}

# How many tool_use ids to carry forward between ticks. The table exists to
# survive a poll landing mid-exchange, not to remember a whole run.
TOOL_NAME_CAP = 400

_SEPARATORS = {";", "&&", "||", "|", "&", "\n"}
_REDIRECT = re.compile(r"^(\d*)(>>?)(.*)$")


# --------------------------------------------------------------------------- #
# The two by-path imports. Never a second matcher, never a third YAML parser.
# --------------------------------------------------------------------------- #
def _sibling(env_var, filename):
    src = os.environ.get(env_var)
    if src and os.path.isfile(src):
        return src
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, filename)


def _load_module(name, path):
    import importlib.util

    if not os.path.isfile(path):
        raise RuntimeError("%s not found at %s" % (name, path))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_matcher():
    """`is_allowed` from scripts/compound-v-scope-check.py — the gate's own."""
    return _load_module(
        "_cv_scope", _sibling("CV_SCOPE_CHECK", "compound-v-scope-check.py")
    ).is_allowed


def load_yaml_fn():
    """`load_yaml` from scripts/compound-v-validate-manifest.py — the repo's own."""
    return _load_module(
        "_cv_vm", _sibling("CV_VALIDATE_MANIFEST", "compound-v-validate-manifest.py")
    ).load_yaml


# --------------------------------------------------------------------------- #
# Small, total helpers. Every one of them degrades instead of raising: this
# process reads files another process is still writing.
# --------------------------------------------------------------------------- #
def _read_json(path, default=None):
    try:
        with open(path, "r") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001 - missing, partial, or malformed: same answer
        return default


def _parse_ts(raw):
    """ISO-8601 (with a trailing Z) -> epoch seconds, or None."""
    if not isinstance(raw, str) or not raw:
        return None
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _hhmmss(epoch):
    if not epoch:
        return time.strftime("%H:%M:%S")
    return time.strftime("%H:%M:%S", time.localtime(epoch))


def _norm(path):
    return os.path.normpath(path) if path else path


def _rel_under(path, root):
    """Repo-relative form of `path` under `root`, or None. normpath first, then
    realpath — a temp dir reached through a symlink (macOS /var) matches on the
    second attempt and would silently miss on the first."""
    if not path or not root:
        return None
    for a, b in ((_norm(path), _norm(root)), (_real(path), _real(root))):
        if not a or not b:
            continue
        if a == b:
            return ""
        base = b.rstrip("/") + "/"
        if a.startswith(base):
            return a[len(base):]
    return None


def _real(path):
    """realpath, or None. TypeError is caught alongside the OS errors on
    purpose: `repo_root_for` returns None for a run directory outside any git
    checkout, and a watcher that raises there fails the run it is watching."""
    try:
        return os.path.realpath(path)
    except (OSError, ValueError, TypeError):
        return None


def _text_of(content):
    """A tool_result's content: a string, or a list of blocks, or something else."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                for key in ("text", "content"):
                    val = item.get(key)
                    if isinstance(val, str):
                        parts.append(val)
                        break
        return "\n".join(parts)
    if content is None:
        return ""
    try:
        return json.dumps(content)
    except (TypeError, ValueError):
        return str(content)


# --------------------------------------------------------------------------- #
# Bash write-target extraction — a HEURISTIC, and conservative in both
# directions, the same posture hooks/lane-guard.sh documents about its own. It
# skips whatever it cannot resolve (a $var, a substitution, a glob) rather than
# guessing, because a false out-of-lane line costs the reader more than a missed
# one: this is a play-ahead, and the gate is still the authority.
# --------------------------------------------------------------------------- #
def _tokenize(command):
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:
        try:
            return shlex.split(command)
        except ValueError:
            return command.split()


def _unresolvable(token):
    return (not token) or any(ch in token for ch in ("$", "`", "*", "?"))


def _args_until_separator(tokens):
    out = []
    for tok in tokens:
        if tok in _SEPARATORS:
            break
        out.append(tok)
    return out


def bash_write_targets(command):
    """Paths a shell command would WRITE, as far as this can honestly tell."""
    if not isinstance(command, str) or not command.strip():
        return []
    tokens = _tokenize(command)
    targets = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        match = _REDIRECT.match(tok) if tok.startswith((">", "1", "2", "3")) else None
        if match and match.group(2):
            rest = match.group(3)
            if rest.startswith("&"):  # 2>&1 — a descriptor, not a file
                i += 1
                continue
            if rest:
                targets.append(rest)
                i += 1
                continue
            if i + 1 < len(tokens):
                targets.append(tokens[i + 1])
                i += 2
                continue
            i += 1
            continue
        if tok in ("mv", "cp"):
            args = [a for a in _args_until_separator(tokens[i + 1:]) if not a.startswith("-")]
            if len(args) >= 2:
                targets.append(args[-1])
        elif tok == "git" and tokens[i + 1:i + 2] == ["rm"]:
            for arg in _args_until_separator(tokens[i + 2:]):
                if not arg.startswith("-"):
                    targets.append(arg)
        i += 1
    return [t for t in targets if not _unresolvable(t)]


# --------------------------------------------------------------------------- #
# register-lane parsing. The call that SUCCEEDED is the one that counts: the
# bashCommandClamp routinely denies a first attempt that used "$PWD", and its
# --cwd is an unexpanded shell variable, not a path.
# --------------------------------------------------------------------------- #
_REGISTER_FLAGS = ("--job-id", "--cwd", "--isolation", "--run-dir", "--repo-root")


def parse_register_lane(command):
    """{flag: value} for a `register-lane` command line, or None."""
    if not isinstance(command, str) or "register-lane" not in command:
        return None
    tokens = _tokenize(command)
    if "register-lane" not in tokens:
        return None
    found = {}
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        for flag in _REGISTER_FLAGS:
            if tok == flag and i + 1 < len(tokens):
                found[flag] = tokens[i + 1]
                i += 1
                break
            if tok.startswith(flag + "="):
                found[flag] = tok[len(flag) + 1:]
                break
        i += 1
    for key, val in list(found.items()):
        if _unresolvable(val):
            found.pop(key)
    return found or None


# --------------------------------------------------------------------------- #
# Transcript reading
# --------------------------------------------------------------------------- #
def iter_tool_events(path, start_line=0):
    """Yield the tool_use / tool_result events of one agent transcript.

    `start_line` skips lines already accounted for by a previous tick. A partial
    trailing line (the file is being appended to right now) is skipped, not
    raised on — the same discipline compound-v-liveness.py uses for a growing
    worker log.
    """
    try:
        fh = open(path, "r")
    except OSError:
        return
    with fh:
        for lineno, raw in enumerate(fh, start=1):
            if lineno <= start_line:
                continue
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(obj, dict):
                continue
            ts = _parse_ts(obj.get("timestamp"))
            message = obj.get("message")
            if not isinstance(message, dict):
                yield {"kind": "other", "line": lineno, "ts": ts}
                continue
            content = message.get("content")
            if not isinstance(content, list):  # a bare string prompt, or nothing
                yield {"kind": "other", "line": lineno, "ts": ts}
                continue
            for item in content:
                if not isinstance(item, dict):
                    continue
                kind = item.get("type")
                if kind == "tool_use":
                    yield {
                        "kind": "tool_use",
                        "line": lineno,
                        "ts": ts,
                        "id": item.get("id"),
                        "name": item.get("name") or "",
                        "input": item.get("input") if isinstance(item.get("input"), dict) else {},
                    }
                elif kind == "tool_result":
                    yield {
                        "kind": "tool_result",
                        "line": lineno,
                        "ts": ts,
                        "tool_use_id": item.get("tool_use_id"),
                        "is_error": bool(item.get("is_error")),
                        "text": _text_of(item.get("content")),
                    }
                else:
                    yield {"kind": "other", "line": lineno, "ts": ts}


def read_journal(wf_dir):
    """agentId -> "returned" | "live", from the workflow's own journal."""
    out = {}
    path = os.path.join(wf_dir, "journal.jsonl")
    try:
        fh = open(path, "r")
    except OSError:
        return out
    with fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(obj, dict):
                continue
            agent = obj.get("agentId")
            if not agent:
                continue
            kind = obj.get("type")
            if kind in ("result", "failed"):
                out[agent] = "returned"
            elif kind == "started":
                out.setdefault(agent, "live")
    return out


def agent_meta(wf_dir, agent_id):
    """`.meta.json` for one agent. EVERY key is optional — `model` is missing on
    real agents, not null — so callers must use .get() on what comes back."""
    meta = _read_json(os.path.join(wf_dir, "agent-%s.meta.json" % agent_id), {})
    return meta if isinstance(meta, dict) else {}


# --------------------------------------------------------------------------- #
# Discovery: find the workflow directory by the run directory's own path.
# --------------------------------------------------------------------------- #
def encoded_project(path):
    """~/.claude/projects/<cwd with every "/" replaced by "-">."""
    return (path or "").replace("/", "-")


def session_roots(repo_root):
    """The session directories of this project, newest first.

    A falsy `repo_root` — the run directory sits outside any git checkout — has
    no encoded project directory to look in, so it is an empty answer, not an
    error. `~/.claude` is overridable by CLAUDE_CONFIG_DIR, which is how the
    suite exercises this default path without pointing at a real session.
    """
    if not repo_root:
        return []
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    proj = os.path.join(base, "projects", encoded_project(_real(repo_root) or repo_root))
    try:
        entries = [os.path.join(proj, n) for n in os.listdir(proj)]
    except OSError:
        return []
    dirs = [d for d in entries if os.path.isdir(d)]
    return sorted(dirs, key=_mtime, reverse=True)


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def workflow_dirs(root):
    """Every plausible workflow directory at or under `root`.

    Workflow-spawned agents — the only kind Compound V dispatches — live under
    `<session>/subagents/workflows/<wf_id>/`. A plain Task agent lands one level
    higher, in `<session>/subagents/`, and is deliberately NOT matched. `root`
    itself is accepted when it already holds `agent-*.jsonl`, so `--transcripts`
    can name either a session directory or a workflow directory outright.
    """
    if not root or not os.path.isdir(root):
        return []
    found = []
    if globmod.glob(os.path.join(root, "agent-*.jsonl")):
        found.append(root)
    for pattern in ("subagents/workflows/*", "workflows/*", "*/subagents/workflows/*"):
        for cand in globmod.glob(os.path.join(root, pattern)):
            if os.path.isdir(cand) and globmod.glob(os.path.join(cand, "agent-*.jsonl")):
                found.append(cand)
    seen = set()
    out = []
    for d in found:
        key = _norm(d)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def mentions_run_dir(wf_dir, run_dir):
    """Does any agent in this workflow name the run directory?

    Every worker prompt carries it, in the `register-lane` command the worker is
    told to run first — which is why discovery needs no new state field.
    """
    needles = {n for n in (run_dir, _norm(run_dir), _real(run_dir)) if n}
    for path in sorted(globmod.glob(os.path.join(wf_dir, "agent-*.jsonl"))):
        try:
            with open(path, "r") as fh:
                head = fh.read(DISCOVERY_HEAD_BYTES)
        except OSError:
            continue
        for needle in needles:
            if needle in head:
                return True
    return False


def find_transcripts(run_dir, transcripts=None, wf=None, repo_root=None):
    """Candidate workflow directories for this run, newest first."""
    if wf and os.path.isdir(wf) and globmod.glob(os.path.join(wf, "agent-*.jsonl")):
        return [wf]

    roots = [transcripts] if transcripts else session_roots(repo_root)
    cands = []
    for root in roots:
        cands.extend(workflow_dirs(root))

    if wf:
        cands = [c for c in cands if os.path.basename(c.rstrip("/")) == wf]
    else:
        cands = [c for c in cands if mentions_run_dir(c, run_dir)]
    return sorted(cands, key=_mtime, reverse=True)


# --------------------------------------------------------------------------- #
# The run's own context: manifest lanes, lane map, job statuses.
# --------------------------------------------------------------------------- #
def repo_root_for(run_dir):
    """Walk up from the run directory to the checkout that contains it."""
    cur = _norm(os.path.abspath(run_dir))
    while True:
        if os.path.exists(os.path.join(cur, ".git")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def load_run_context(run_dir, load_yaml=None):
    """{jobs: {id: {isolation, write_allowed}}, worktrees: {path: job}, status:{}}."""
    ctx = {"jobs": {}, "worktrees": {}, "status": {}, "notes": []}

    manifest_path = os.path.join(run_dir, "manifest.yaml")
    data = None
    if os.path.isfile(manifest_path):
        try:
            loader = load_yaml or load_yaml_fn()
            with open(manifest_path, "r") as fh:
                data = loader(fh.read())
        except Exception as exc:  # noqa: BLE001 - advisory: degrade, never fail
            ctx["notes"].append("manifest unreadable (%s)" % exc)
    else:
        ctx["notes"].append("no manifest.yaml in the run directory")

    jobs = (data or {}).get("jobs") if isinstance(data, dict) else None
    if isinstance(jobs, dict):
        jobs = [dict(v, id=k) for k, v in jobs.items() if isinstance(v, dict)]
    for job in jobs or []:
        if not isinstance(job, dict) or not job.get("id"):
            continue
        allowed = job.get("write_allowed") or []
        ctx["jobs"][job["id"]] = {
            "isolation": job.get("isolation"),
            "write_allowed": [g for g in allowed if isinstance(g, str)],
        }

    lane_map = _read_json(os.path.join(run_dir, "lane-map.json"), {}) or {}
    worktrees = lane_map.get("worktrees") if isinstance(lane_map, dict) else None
    if isinstance(worktrees, dict):
        ctx["worktrees"] = {k: v for k, v in worktrees.items() if isinstance(v, str)}

    state = _read_json(os.path.join(run_dir, "state.json"), {}) or {}
    sjobs = state.get("jobs") if isinstance(state, dict) else None
    if isinstance(sjobs, dict):
        for jid, rec in sjobs.items():
            ctx["status"][jid] = (rec or {}).get("status", "?") if isinstance(rec, dict) else "?"
    return ctx


# --------------------------------------------------------------------------- #
# The five detectors
# --------------------------------------------------------------------------- #
def _roots_for(job, reg, ctx, repo_root):
    """Where an absolute path may be made repo-relative FOR THIS AGENT.

    Its own registered cwd, the checkout, and the worktrees the lane map assigns
    to ITS OWN job — never another job's worktree, which would let a path be
    laundered into a lane that happens to allow it.
    """
    roots = []
    if reg and reg.get("--cwd"):
        roots.append(reg["--cwd"])
    for path, mapped in (ctx.get("worktrees") or {}).items():
        if job and mapped == job:
            roots.append(path)
    if repo_root:
        roots.append(repo_root)
    return roots


def _repo_relative(path, roots):
    """The DEEPEST root that contains `path` wins: a worktree nested inside the
    checkout must yield `src/x.py`, not `.claude/worktrees/wf-1/src/x.py`."""
    best = None
    for root in roots:
        rel = _rel_under(path, root)
        if rel is None or rel == "":
            continue
        if best is None or len(rel) < len(best):
            best = rel
    return best


def out_of_lane_targets(event, job, reg, ctx, repo_root, is_allowed):
    """[(evidence, rel_or_abs)] for the writes this tool_use would perform."""
    name = event.get("name") or ""
    inp = event.get("input") or {}
    raw_targets = []
    if name in WRITE_TOOLS:
        val = inp.get(WRITE_TOOLS[name])
        if isinstance(val, str) and val:
            raw_targets.append((name, val))
    elif name == "Bash":
        for target in bash_write_targets(inp.get("command")):
            raw_targets.append(("Bash", target))
    if not raw_targets:
        return []

    allowed = ((ctx.get("jobs") or {}).get(job) or {}).get("write_allowed") or []
    roots = _roots_for(job, reg, ctx, repo_root)
    base = (reg or {}).get("--cwd") or repo_root or os.getcwd()

    out = []
    for tool, target in raw_targets:
        path = target if os.path.isabs(target) else os.path.join(base, target)
        rel = _repo_relative(path, roots)
        if rel is None:
            # Under no root this agent owns: /dev/null, a scratchpad file, a
            # path in another checkout entirely. A lane is a repository-relative
            # contract, so a path that HAS no repository-relative form is not a
            # lane question at all. Reporting it anyway is what made the first
            # out-of-lane signal of every real run `Bash /dev/null` — on the one
            # signal v-dispatch tells the orchestrator to stop a workflow for.
            continue
        if job and allowed and is_allowed(rel, allowed):
            continue
        out.append("%s %s" % (tool, rel))
    return out


def wrong_cwd_reason(reg, ctx, repo_root):
    """Why this register-lane call disagrees with the manifest, or None."""
    job = reg.get("--job-id")
    if not job:
        return None
    declared = ((ctx.get("jobs") or {}).get(job) or {}).get("isolation")
    if not declared:
        return None
    got = reg.get("--isolation")
    if got and got != declared:
        return "registered --isolation %s but the manifest says %s" % (got, declared)
    cwd = reg.get("--cwd")
    root = reg.get("--repo-root") or repo_root
    if declared == "worktree" and cwd and root and _rel_under(cwd, root) == "":
        return "registered --cwd at the repository root while the manifest says worktree"
    return None


def _matching_line(text, index):
    """The whole line `index` falls on, stripped — the evidence a reader needs
    in order to see WHAT fired. Never the first line of the result: this file
    once rendered `splitlines()[0]` for a denial and printed `total 184`."""
    start = text.rfind("\n", 0, index) + 1
    end = text.find("\n", index)
    return text[start:end if end != -1 else len(text)].strip()


def _at_line_start(text, index):
    return index == 0 or text[index - 1] == "\n"


def error_evidence(text, is_error=False):
    """The failing line of a Bash result, or None.

    ANCHORED, because this repository's prose is largely ABOUT blocked jobs and
    tracebacks. On a result the harness itself marked `is_error` the pattern may
    match anywhere; on an ordinary result it must stand at the START of a line —
    which is where a real traceback, a real `command not found` and a real
    `Permission denied` all appear, and where a sentence mentioning one does
    not. Without this the watcher reported its own selftest output (`PASS exit
    code 0 is not an error, exit code 1 is`) as an error.
    """
    if not text:
        return None
    for pattern in ERROR_PATTERNS:
        for match in pattern.finditer(text):
            if not is_error and not _at_line_start(text, match.start()):
                continue
            return _matching_line(text, match.start()) or match.group(0)
    return None


def denial_evidence(text, is_error=False, tool_name=None):
    """The lane guard's own denial line, or None.

    Anchored the same way, and once more besides. A denial is a REFUSAL that
    came back from a call the guard is registered on, so it must (a) come from
    one of those tools and (b) either be the harness's error result or stand at
    the start of a line. A bare `DENY_LITERAL in text` reported five quotes of
    the literal — the manifest, the spec, the plan, the audit, and the guard's
    own source — as violations in the run this detector was reviewed against,
    every one of them from an agent reading its own instructions.
    """
    if not text:
        return None
    if tool_name is not None and tool_name not in DENIABLE_TOOLS:
        return None
    index = text.find(DENY_LITERAL) if is_error else -1
    if index < 0:
        if text.startswith(DENY_LITERAL):
            index = 0
        else:
            found = text.find("\n" + DENY_LITERAL)
            index = found + 1 if found >= 0 else -1
    if index < 0:
        return None
    return _matching_line(text, index) or DENY_LITERAL


# --------------------------------------------------------------------------- #
# Per-agent analysis
# --------------------------------------------------------------------------- #
def _cap_tools(table, cap=TOOL_NAME_CAP):
    """The most recent `cap` entries of an insertion-ordered id -> name table."""
    if len(table) <= cap:
        return table
    keys = list(table)[-cap:]
    return dict((k, table[k]) for k in keys)


def analyze_agent(path, agent_id, ctx, repo_root, is_allowed, start_line=0,
                  prior_job=None, prior_reg=None, prior_tools=None,
                  prior_pending=None):
    """(signals, last_line, last_ts, job, reg, tools, pending) for one agent.

    `tools` (tool_use id -> tool name) and `pending` (the register-lane calls
    whose result has not arrived yet) are taken in AND handed back, so the
    caller can persist them. They used to be locals, which meant a poll landing
    between a register-lane and its result orphaned that result for good: the
    agent stayed `(unregistered)` for the rest of the run, every in-lane write
    it made was then reported out-of-lane, and every Bash failure was missed
    because the tool behind the id was no longer known. `--every` is the mode
    v-dispatch prescribes, and register-lane is the first command every job runs.
    """
    job = prior_job
    reg = dict(prior_reg) if prior_reg else None
    signals = []
    last_line = start_line
    last_ts = None
    tool_names = dict(prior_tools) if isinstance(prior_tools, dict) else {}
    pending_register = {}
    if isinstance(prior_pending, dict):
        for uid, rec in prior_pending.items():
            if isinstance(rec, dict) and isinstance(rec.get("parsed"), dict):
                pending_register[uid] = rec

    for event in iter_tool_events(path, start_line):
        last_line = max(last_line, event["line"])
        if event.get("ts"):
            last_ts = event["ts"]
        kind = event["kind"]

        if kind == "tool_use":
            tool_names[event.get("id")] = event.get("name") or ""
            parsed = parse_register_lane((event.get("input") or {}).get("command"))
            if parsed is not None:
                pending_register[event.get("id")] = {
                    "parsed": parsed, "line": event["line"], "ts": event.get("ts"),
                }
                continue
            for evidence in out_of_lane_targets(event, job, reg, ctx, repo_root, is_allowed):
                signals.append({
                    "signal": "out-of-lane", "job": job or UNREGISTERED,
                    "agent": agent_id, "line": event["line"], "ts": event.get("ts"),
                    "evidence": evidence,
                })
            continue

        if kind != "tool_result":
            continue

        use_id = event.get("tool_use_id")
        if use_id in pending_register:
            rec = pending_register.pop(use_id)
            parsed = rec["parsed"]
            # ONLY the call that succeeded. A clamp-denied first attempt carries
            # an unexpanded "$PWD", not a path.
            if not event.get("is_error"):
                if parsed.get("--job-id"):
                    job = parsed["--job-id"]
                reg = parsed
                reason = wrong_cwd_reason(parsed, ctx, repo_root)
                if reason:
                    signals.append({
                        "signal": "wrong-cwd", "job": job or UNREGISTERED,
                        "agent": agent_id, "line": rec.get("line") or event["line"],
                        "ts": rec.get("ts") or event.get("ts"),
                        "evidence": reason,
                    })
            continue

        text = event.get("text") or ""
        tool = tool_names.get(use_id)
        evidence = denial_evidence(text, event.get("is_error"), tool)
        if evidence:
            signals.append({
                "signal": "denied", "job": job or UNREGISTERED, "agent": agent_id,
                "line": event["line"], "ts": event.get("ts"),
                "evidence": evidence,
            })
            continue
        if tool == "Bash":
            evidence = error_evidence(text, event.get("is_error"))
            if evidence:
                signals.append({
                    "signal": "error", "job": job or UNREGISTERED, "agent": agent_id,
                    "line": event["line"], "ts": event.get("ts"), "evidence": evidence,
                })

    return (signals, last_line, last_ts, job, reg,
            _cap_tools(tool_names), pending_register)


# --------------------------------------------------------------------------- #
# State — per-agent line offsets and the keys already emitted, so `--every`
# never repeats itself. It lives in the OS temp directory by default and is
# NEVER written into the run directory or the repository.
# --------------------------------------------------------------------------- #
STATE_EMITTED_CAP = 5000


def default_state_path(run_dir):
    digest = hashlib.sha1(os.path.abspath(run_dir).encode("utf-8")).hexdigest()[:12]
    return os.path.join(tempfile.gettempdir(), "cv-transcript-watch-%s.json" % digest)


def load_state(path):
    data = _read_json(path, None)
    if not isinstance(data, dict):
        return {"version": 1, "agents": {}, "emitted": []}
    data.setdefault("agents", {})
    data.setdefault("emitted", [])
    if not isinstance(data["agents"], dict):
        data["agents"] = {}
    if not isinstance(data["emitted"], list):
        data["emitted"] = []
    return data


def save_state(path, state):
    """Atomic, and advisory: an unwritable state file degrades to "repeats every
    tick", never to a failed run."""
    state["emitted"] = state.get("emitted", [])[-STATE_EMITTED_CAP:]
    directory = os.path.dirname(os.path.abspath(path)) or "."
    try:
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".cv-watch-", suffix=".json")
        with os.fdopen(fd, "w") as fh:
            json.dump(state, fh)
        os.replace(tmp, path)
        return True
    except OSError as exc:
        sys.stderr.write("transcript-watch: state file not written (%s); "
                         "signals may repeat next tick\n" % exc)
        return False


def signal_key(sig):
    if sig["signal"] == "stall":  # one per agent, not one per tick
        return "%s|stall" % sig["agent"]
    return "%s|%s|%s|%s" % (sig["agent"], sig["signal"], sig["line"], sig["evidence"][:80])


# --------------------------------------------------------------------------- #
# One tick
# --------------------------------------------------------------------------- #
def tick(wf_dir, ctx, state, repo_root, is_allowed, stall_minutes, now=None):
    """(new_signals, summary) for one pass over one workflow directory."""
    now = now if now is not None else time.time()
    journal = read_journal(wf_dir)
    agents = sorted(globmod.glob(os.path.join(wf_dir, "agent-*.jsonl")))
    emitted = set(state.get("emitted", []))
    fresh = []
    roster = []
    live = returned = 0

    for path in agents:
        agent_id = os.path.basename(path)[len("agent-"):-len(".jsonl")]
        rec = state["agents"].get(agent_id) or {}
        signals, last_line, last_ts, job, reg, tools, pending = analyze_agent(
            path, agent_id, ctx, repo_root, is_allowed,
            start_line=int(rec.get("line") or 0),
            prior_job=rec.get("job"), prior_reg=rec.get("reg"),
            prior_tools=rec.get("tools"), prior_pending=rec.get("pending"),
        )
        if last_ts is None:
            last_ts = rec.get("last_ts") or _mtime(path)

        status = journal.get(agent_id, "live")
        if status == "returned":
            returned += 1
        else:
            live += 1
            idle = now - float(last_ts or 0)
            if last_ts and idle > stall_minutes * 60:
                signals.append({
                    "signal": "stall", "job": job or UNREGISTERED, "agent": agent_id,
                    "line": last_line, "ts": last_ts,
                    "evidence": "no tool use for %d min (still running)" % int(idle // 60),
                })

        roster.append((agent_id, job or UNREGISTERED, status))
        state["agents"][agent_id] = {
            "line": last_line, "last_ts": last_ts, "job": job, "reg": reg,
            "tools": tools, "pending": pending,
        }
        for sig in signals:
            key = signal_key(sig)
            if key in emitted:
                continue
            emitted.add(key)
            state.setdefault("emitted", []).append(key)
            fresh.append(sig)

    jobs_text = " ".join(
        "%s=%s" % (jid, ctx["status"].get(jid, "?"))
        for jid in sorted(set(list(ctx["jobs"].keys()) + list(ctx["status"].keys())))
    ) or "(none)"
    # A ROSTER, not just counts: one line per agent of the workflow with the job
    # it registered and whether it is still running, so a reader can see the
    # agents that emitted nothing — including any that never registered a lane.
    lines = ["jobs: %s  agents: %d live, %d returned" % (jobs_text, live, returned)]
    for agent_id, job, status in roster:
        lines.append("%-8s %-24s %s" % (agent_id[:8], job, status))
    return fresh, "\n".join(lines)


def render(sig):
    return "%s %s %s %s %s" % (
        _hhmmss(sig.get("ts")), sig["job"], (sig["agent"] or "")[:8],
        sig["signal"], (sig.get("evidence") or "")[:140],
    )


def as_json(sig):
    ts = sig.get("ts")
    return {
        "ts": datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")
        if ts else datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "job": sig["job"],
        "agent": sig["agent"],
        "signal": sig["signal"],
        "evidence": (sig.get("evidence") or "")[:140],
        "line": sig.get("line"),
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser():
    ap = argparse.ArgumentParser(
        prog="compound-v-transcript-watch.py",
        description="Read a Compound V run's live worker transcripts and report "
                    "out-of-lane writes, wrong cwds, errors, lane-guard denials "
                    "and stalls. Read-only, advisory, exit 0.",
    )
    ap.add_argument("--run-dir", help="docs/superpowers/execution/<run-id>/")
    ap.add_argument("--wf", help="workflow id (or directory) — overrides discovery")
    ap.add_argument("--transcripts", help="session or workflow directory — overrides discovery")
    ap.add_argument("--once", action="store_true", help="one pass (the default)")
    ap.add_argument("--every", type=int, metavar="SECONDS",
                    help="poll every SECONDS until interrupted")
    ap.add_argument("--state", help="offsets file (default: the OS temp directory)")
    ap.add_argument("--json", action="store_true", help="one JSON object per signal")
    ap.add_argument("--stall-minutes", type=int, default=DEFAULT_STALL_MINUTES)
    ap.add_argument("--selftest", action="store_true")
    return ap


def main(argv):
    args = build_parser().parse_args(argv[1:])
    if args.selftest:
        return _selftest()

    if not args.run_dir:
        sys.stderr.write("usage fault: --run-dir is required\n")
        return 2
    run_dir = os.path.abspath(args.run_dir)
    if not os.path.isdir(run_dir):
        sys.stderr.write("usage fault: %s is not a directory\n" % run_dir)
        return 2
    if args.every is not None and args.every <= 0:
        sys.stderr.write("usage fault: --every must be a positive number of seconds\n")
        return 2
    if args.every is not None and args.once:
        sys.stderr.write("usage fault: --once and --every are mutually exclusive\n")
        return 2

    # Everything past this point is advisory and must exit 0.
    out = sys.stdout
    note = sys.stderr if args.json else sys.stdout

    try:
        is_allowed = load_matcher()
    except Exception as exc:  # noqa: BLE001
        note.write("transcript-watch: the scope gate's matcher could not be "
                   "imported (%s); nothing to report\n" % exc)
        return 0

    repo_root = repo_root_for(run_dir)
    ctx = load_run_context(run_dir)
    for line in ctx["notes"]:
        note.write("transcript-watch: %s\n" % line)

    state_path = args.state or default_state_path(run_dir)
    state = load_state(state_path)

    interval = args.every
    announced = None
    while True:
        cands = find_transcripts(run_dir, args.transcripts, args.wf, repo_root)
        if not cands:
            note.write("no transcripts found for %s (searched %s)\n" % (
                run_dir, args.transcripts or args.wf or "~/.claude/projects/%s/*"
                % encoded_project(repo_root or "")))
            if interval is None:
                return 0
        else:
            wf_dir = cands[0]
            if announced != wf_dir:
                announced = wf_dir
                note.write("watching %s (%d agent transcripts) for %s\n" % (
                    os.path.basename(wf_dir.rstrip("/")),
                    len(globmod.glob(os.path.join(wf_dir, "agent-*.jsonl"))),
                    os.path.basename(run_dir)))
            signals, summary = tick(wf_dir, ctx, state, repo_root,
                                    is_allowed, args.stall_minutes)
            for sig in signals:
                if args.json:
                    out.write(json.dumps(as_json(sig)) + "\n")
                else:
                    out.write(render(sig) + "\n")
            note.write(summary + "\n")
            out.flush()
            save_state(state_path, state)

        if interval is None:
            return 0
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            return 0
        ctx = load_run_context(run_dir)  # statuses move while we watch


# --------------------------------------------------------------------------- #
# --selftest — the parsers and one end-to-end pass, on fixtures built here.
# --------------------------------------------------------------------------- #
def _selftest():  # noqa: C901 - a linear list of cases reads better than five helpers
    import shutil

    failures = []

    def expect(name, cond):
        if cond:
            print("PASS %s" % name)
        else:
            failures.append(name)
            print("FAIL %s" % name)

    # --- the two by-path imports are real, and are the repo's own -----------
    try:
        is_allowed = load_matcher()
        expect("the matcher imports from compound-v-scope-check.py", True)
    except Exception as exc:  # noqa: BLE001
        expect("the matcher imports from compound-v-scope-check.py (%s)" % exc, False)
        return 1
    expect("...and it is the gate's matcher, not a local one",
           is_allowed("src/a.py", ["src/**"]) and not is_allowed("README.md", ["src/**"]))
    try:
        loader = load_yaml_fn()
        expect("load_yaml imports from compound-v-validate-manifest.py",
               loader("a: 1") == {"a": 1})
    except Exception as exc:  # noqa: BLE001
        expect("load_yaml imports from compound-v-validate-manifest.py (%s)" % exc, False)
        return 1

    # --- bash write-target extraction ---------------------------------------
    expect("a > redirect is a write target",
           bash_write_targets("echo x > /r/notes.txt") == ["/r/notes.txt"])
    expect("...and so is >> with no space",
           bash_write_targets("echo x >>/r/n.txt") == ["/r/n.txt"])
    expect("2>&1 is a descriptor, not a file",
           bash_write_targets("run 2>&1") == [])
    expect("mv/cp name their destination",
           bash_write_targets("mv a.py b.py") == ["b.py"]
           and bash_write_targets("cp -r a b") == ["b"])
    expect("git rm names its operands",
           bash_write_targets("git rm -f docs/x.md") == ["docs/x.md"])
    expect("an unresolvable target is skipped, never guessed",
           bash_write_targets("echo x > $OUT") == []
           and bash_write_targets("echo x > /r/*.txt") == [])
    expect("a '>' inside a quoted argument is not a redirect",
           bash_write_targets('echo "a > b"') == [])

    # --- register-lane parsing ----------------------------------------------
    parsed = parse_register_lane(
        "python3 emit.py register-lane --run-dir /r/run --job-id a --cwd /wt "
        "--isolation worktree")
    expect("register-lane flags parse in the spaced form",
           parsed and parsed.get("--job-id") == "a" and parsed.get("--cwd") == "/wt")
    parsed_eq = parse_register_lane("emit.py register-lane --job-id=b --isolation=direct")
    expect("...and in the --flag=value form",
           parsed_eq and parsed_eq.get("--job-id") == "b"
           and parsed_eq.get("--isolation") == "direct")
    parsed_var = parse_register_lane('emit.py register-lane --job-id a --cwd "$PWD"')
    expect("an unexpanded $PWD is dropped, never treated as a path",
           parsed_var is not None and "--cwd" not in parsed_var)
    expect("a command that is not register-lane parses to None",
           parse_register_lane("git status") is None)

    # --- the denial literal, and its two anchors -----------------------------
    real_denial = "Compound V lane guard: job 'a' is not allowed to write 'x'"
    expect("the lane guard's real denial is a denial",
           denial_evidence(real_denial, True, "Write") == real_denial)
    expect("...and at the start of a line, even without is_error",
           denial_evidence("ok\n" + real_denial, False, "Bash") == real_denial)
    expect("the hyphenated FAILED-OPEN notice is NOT a denial",
           denial_evidence("Compound V lane-guard FAILED OPEN: no manifest", True, "Bash")
           is None)
    expect("the harness's bashCommandClamp denial is NOT a lane denial",
           denial_evidence("Permission to use Bash with command foo has been denied: "
                           "this agent's Bash use is clamped", True, "Bash") is None)
    quoting = "The plan says the literal `" + real_denial + "` must anchor."
    expect("a result that merely QUOTES the literal mid-line is NOT a denial",
           denial_evidence(quoting, False, "Bash") is None)
    expect("...nor when a Read of that same document is what returned it",
           denial_evidence(real_denial, True, "Read") is None)
    expect("an unknown tool is still allowed to carry a denial",
           denial_evidence(real_denial, True, None) == real_denial)

    # --- error evidence ------------------------------------------------------
    expect("a Traceback reads as an error",
           error_evidence("ok\nTraceback (most recent call last):\n  File x") is not None)
    expect("a clean result does not",
           error_evidence("File created successfully at: /a/b") is None)
    expect("exit code 0 is not an error, exit code 1 is",
           error_evidence("exit code 0") is None and error_evidence("exit code 1") is not None)
    expect("a pattern quoted mid-sentence is not an error",
           error_evidence("PASS exit code 0 is not an error, exit code 1 is") is None
           and error_evidence("show the phase, one of SPEC_READY to BLOCKED to DONE") is None)
    expect("...but on a result the harness marked is_error it counts anywhere",
           error_evidence("job a is BLOCKED by the gate", True) is not None)
    expect("the evidence is the MATCHING line, never the first",
           error_evidence("total 184\nTraceback (most recent call last):\n  File x")
           == "Traceback (most recent call last):")

    # --- the advisory paths that must never raise ---------------------------
    expect("a run directory outside any git checkout yields no session roots",
           session_roots(None) == [] and session_roots("") == [])
    expect("realpath of None is None, not a TypeError", _real(None) is None)

    # --- transcript shapes ---------------------------------------------------
    tmp = tempfile.mkdtemp(prefix="cv-watch-selftest-")
    try:
        run_dir = os.path.join(tmp, "repo", "run")
        repo = os.path.join(tmp, "repo")
        wt = os.path.join(tmp, "wt-a")
        wf = os.path.join(tmp, "session", "subagents", "workflows", "wf_x")
        os.makedirs(run_dir)
        os.makedirs(wf)
        os.makedirs(os.path.join(wt, "src"))
        os.makedirs(os.path.join(repo, ".git"))
        with open(os.path.join(run_dir, "manifest.yaml"), "w") as fh:
            fh.write("run_id: r\njobs:\n  - id: a\n    isolation: worktree\n"
                     "    write_allowed:\n      - \"src/**\"\n")
        with open(os.path.join(run_dir, "lane-map.json"), "w") as fh:
            json.dump({"worktrees": {wt: "a"}, "run_id": "r"}, fh)
        with open(os.path.join(run_dir, "state.json"), "w") as fh:
            json.dump({"jobs": {"a": {"status": "running"}}}, fh)

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        old_iso = datetime.fromtimestamp(time.time() - 7200, timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z")

        def line(obj):
            return json.dumps(obj) + "\n"

        def use(agent, ts, uid, name, inp):
            return line({"type": "assistant", "agentId": agent, "timestamp": ts,
                         "message": {"role": "assistant", "content": [
                             {"type": "tool_use", "id": uid, "name": name, "input": inp}]}})

        def result(agent, ts, uid, text, is_error=False):
            return line({"type": "user", "agentId": agent, "timestamp": ts,
                         "message": {"role": "user", "content": [
                             {"type": "tool_result", "tool_use_id": uid,
                              "is_error": is_error, "content": text}]}})

        reg_cmd = ("python3 emit.py register-lane --run-dir %s --job-id a --cwd %s "
                   "--repo-root %s --isolation worktree" % (run_dir, wt, repo))
        with open(os.path.join(wf, "agent-aaa1.jsonl"), "w") as fh:
            # a bare-string prompt line, and an attachment line with no message
            fh.write(line({"type": "user", "agentId": "aaa1", "timestamp": now_iso,
                           "message": {"role": "user", "content": "prompt for %s" % run_dir}}))
            fh.write(line({"type": "attachment", "agentId": "aaa1", "timestamp": now_iso,
                           "attachment": {"type": "skill_listing"}}))
            fh.write(use("aaa1", now_iso, "t1", "Bash", {"command": reg_cmd}))
            fh.write(result("aaa1", now_iso, "t1", "{\"registered\": \"a\"}"))
            fh.write(use("aaa1", now_iso, "t2", "Write",
                         {"file_path": os.path.join(wt, "src", "ok.py")}))
            fh.write(result("aaa1", now_iso, "t2", "File created successfully"))
            fh.write(use("aaa1", now_iso, "t3", "Write",
                         {"file_path": os.path.join(wt, "README.md")}))
            fh.write(result("aaa1", now_iso, "t3", "File created successfully"))
            fh.write(use("aaa1", now_iso, "t4", "Bash",
                         {"command": "python3 x.py"}))
            fh.write(result("aaa1", now_iso, "t4",
                            "Traceback (most recent call last):\n  File x", True))
            fh.write(result("aaa1", now_iso, "t5",
                            "Compound V lane guard: job 'a' is not allowed to write 'z'"))
        with open(os.path.join(wf, "agent-aaa1.meta.json"), "w") as fh:
            json.dump({"agentType": "workflow-subagent", "spawnDepth": 1}, fh)
        with open(os.path.join(wf, "agent-bbb2.jsonl"), "w") as fh:
            fh.write(use("bbb2", old_iso, "u1", "Read", {"file_path": "/x"}))
        with open(os.path.join(wf, "journal.jsonl"), "w") as fh:
            fh.write(line({"type": "started", "agentId": "aaa1"}))
            fh.write(line({"type": "result", "agentId": "aaa1"}))
            fh.write(line({"type": "started", "agentId": "bbb2"}))

        expect("meta.json without a `model` key reads as None, and does not raise",
               agent_meta(wf, "aaa1").get("model") is None
               and agent_meta(wf, "aaa1").get("agentType") == "workflow-subagent")
        expect("a missing meta.json is an empty dict, not a crash",
               agent_meta(wf, "nope") == {})

        ctx = load_run_context(run_dir)
        expect("the manifest's lane and isolation load through load_yaml",
               ctx["jobs"]["a"]["write_allowed"] == ["src/**"]
               and ctx["jobs"]["a"]["isolation"] == "worktree")
        expect("the lane map's worktrees load", ctx["worktrees"].get(wt) == "a")

        found = find_transcripts(run_dir, os.path.join(tmp, "session"))
        expect("discovery finds the workflow that mentions the run directory",
               found and os.path.basename(found[0]) == "wf_x")
        expect("discovery of an unrelated tree finds nothing, cleanly",
               find_transcripts(run_dir, os.path.join(tmp, "repo")) == [])

        state = {"version": 1, "agents": {}, "emitted": []}
        signals, summary = tick(wf, ctx, state, repo, is_allowed, 8)
        kinds = sorted(s["signal"] for s in signals)
        expect("one pass yields exactly denied+error+out-of-lane+stall",
               kinds == ["denied", "error", "out-of-lane", "stall"])
        expect("the in-lane write produced no signal",
               not any("ok.py" in (s.get("evidence") or "") for s in signals))
        expect("the out-of-lane write is repo-relative, against its own worktree",
               any(s["signal"] == "out-of-lane" and s["evidence"].endswith("README.md")
                   for s in signals))
        expect("the stalled agent has no lane and is named (unregistered)",
               any(s["signal"] == "stall" and s["job"] == UNREGISTERED for s in signals))
        expect("the summary names the job and counts the agents",
               "a=running" in summary and "1 live, 1 returned" in summary)

        again, _ = tick(wf, ctx, state, repo, is_allowed, 8)
        expect("a second pass over the same state repeats nothing", again == [])

        rendered = render(signals[0])
        expect("the text line is <time> <job> <agent8> <signal> <evidence>",
               len(rendered.split(" ", 4)) == 5
               and re.match(r"^\d\d:\d\d:\d\d ", rendered) is not None)
        payload = as_json(signals[0])
        expect("the JSON object carries ts/job/agent/signal/evidence/line",
               set(payload) == {"ts", "job", "agent", "signal", "evidence", "line"})

        # A wrong-cwd registration, read off the call that SUCCEEDED.
        wf2 = os.path.join(tmp, "session2", "subagents", "workflows", "wf_y")
        os.makedirs(wf2)
        bad = ("python3 emit.py register-lane --run-dir %s --job-id a --cwd %s "
               "--repo-root %s --isolation direct" % (run_dir, repo, repo))
        clamped = ('python3 emit.py register-lane --run-dir %s --job-id nope '
                   '--cwd "$PWD" --isolation worktree' % run_dir)
        with open(os.path.join(wf2, "agent-ccc3.jsonl"), "w") as fh:
            fh.write(use("ccc3", now_iso, "v1", "Bash", {"command": clamped}))
            fh.write(result("ccc3", now_iso, "v1",
                            "Permission to use Bash with command ... has been denied", True))
            fh.write(use("ccc3", now_iso, "v2", "Bash", {"command": bad}))
            fh.write(result("ccc3", now_iso, "v2", "{\"registered\": \"a\"}"))
        with open(os.path.join(wf2, "journal.jsonl"), "w") as fh:
            fh.write(line({"type": "started", "agentId": "ccc3"}))
            fh.write(line({"type": "result", "agentId": "ccc3"}))
        state2 = {"version": 1, "agents": {}, "emitted": []}
        sigs2, _ = tick(wf2, ctx, state2, repo, is_allowed, 8)
        expect("a mis-declared isolation is one wrong-cwd signal",
               [s["signal"] for s in sigs2] == ["wrong-cwd"])
        expect("...attributed to the job of the call that SUCCEEDED",
               sigs2[0]["job"] == "a")

        # An unregistered agent's write is an out-of-lane candidate.
        wf3 = os.path.join(tmp, "session3", "subagents", "workflows", "wf_z")
        os.makedirs(wf3)
        with open(os.path.join(wf3, "agent-ddd4.jsonl"), "w") as fh:
            fh.write(use("ddd4", now_iso, "w1", "Write",
                         {"file_path": os.path.join(repo, "zzz.md")}))
            fh.write(result("ddd4", now_iso, "w1", "File created successfully"))
        with open(os.path.join(wf3, "journal.jsonl"), "w") as fh:
            fh.write(line({"type": "result", "agentId": "ddd4"}))
        state3 = {"version": 1, "agents": {}, "emitted": []}
        sigs3, _ = tick(wf3, ctx, state3, repo, is_allowed, 8)
        expect("a write with no lane registered is an out-of-lane candidate",
               [s["signal"] for s in sigs3] == ["out-of-lane"]
               and sigs3[0]["job"] == UNREGISTERED)

        # A malformed / half-written trailing line is skipped, never raised on.
        with open(os.path.join(wf3, "agent-ddd4.jsonl"), "a") as fh:
            fh.write('{"type":"assistant","message":{"role":"assis')
        expect("a partial trailing line is skipped, not raised on",
               list(iter_tool_events(os.path.join(wf3, "agent-ddd4.jsonl"))) is not None)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        print("\nSELFTEST FAILED: %d case(s)" % len(failures))
        return 1
    print("\nSELFTEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
