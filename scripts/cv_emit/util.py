"""Shared helpers: paths, subprocess and git, atomic writes, the run-dir lock, the lane map and state.json."""

from __future__ import annotations

import os
import json
import re
import subprocess
import tempfile


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENTRY_PATH = os.path.join(HERE, "compound-v-emit-workflow.py")

# THERE IS NO DEFAULT REPOSITORY ROOT, and its absence is the point.
#
# Until 3.0.2 this module carried `REPO_DEFAULT = os.path.dirname(HERE)` — the
# repository containing the INSTALLED SCRIPT — and handed it to `record` as the
# `--repo-root` default. Since the emitted Record command passed no `--repo-root`
# at all, a job that edited `README.md` in /work/app had its patch applied into
# /plugins/superpowers-v. A wrong-repository write is the same class as this
# project's 2026-07-13 incident, so the root is now REQUIRED everywhere it
# decides a destination, and its absence FAILS CLOSED rather than picking one.
SCOPE_CHECK_DEFAULT = os.path.join(HERE, "compound-v-scope-check.py")
FASTPATH_DEFAULT = os.path.join(HERE, "compound-v-fastpath-run.py")
INTEGRATION_GATE_DEFAULT = os.path.join(HERE, "compound-v-integration-gate.py")
RESOLVE_MODEL_DEFAULT = os.path.join(HERE, "compound-v-resolve-model.py")

# --------------------------------------------------------------------------- #
# Determinism constraints of the Workflow runtime (verified against the
# installed Claude Code 2.1.238 binary and its own error strings):
#
#   "Workflow scripts must be deterministic: Date.now()/Math.random()/new Date()
#    are unavailable (breaks resume). Stamp results after the workflow returns,
#    or pass timestamps via args."
#
# NOTE, and this is precisely why the check below exists rather than being left
# to the runtime: that static pre-check is applied ONLY to the inline `script`
# input (the guard reads `if (input.script && isNonDeterministic(body))`). A
# workflow launched by `scriptPath` — which is the form Engine C forces, so the
# committed artefact is what ran — SKIPS it and only discovers the problem when
# the global throws mid-run. The generator is the real backstop.
# --------------------------------------------------------------------------- #
FORBIDDEN_PATTERNS = [
    (r"\bDate\.now\s*\(", "Date.now()"),
    (r"\bMath\.random\s*\(", "Math.random()"),
    (r"\bnew\s+Date\s*\(\s*\)", "bare new Date()"),
    (r"(?<![\w.$])import\s*\(", "import()"),
]

# The Gate/Record agents are narrowed at spawn. `disallowedTools` is a DENY list
# of tool names, so this enumerates what to remove; Bash must survive, because a
# `bashCommandClamp` whose agent has no Bash "can bind nothing" and the runtime
# REFUSES THE SPAWN outright (verbatim from the binary). StructuredOutput must
# survive too, or schema mode is denied and the spawn is likewise refused.
#
# Honest limit: a denylist cannot cover a tool this build does not have yet. The
# confinement that actually holds is the clamp, which is an ALLOWLIST of command
# forms and is fail-closed ("no clamp rule matches this command" -> deny;
# "permission check crashed" -> deny).
#
# `TodoWrite` plus the checklist family (native-mechanisms audit, 2.1.268/2.1.277
# facts, verified against code.claude.com/docs/en/tools-reference and
# /changelog on the installed 2.1.278 binary): `TaskCreate`, `TaskGet`,
# `TaskList` and `TaskUpdate` are the CURRENT default for the same session
# checklist `TodoWrite` used to be — "TodoWrite: disabled by default in favor
# of TaskCreate, TaskGet, TaskList, and TaskUpdate" — and both forms are
# offered only on Claude 3.x, Opus 4.0-4.7, Sonnet 4.0-4.6 and Haiku 4.5 by
# default, or on any model under `CLAUDE_CODE_ENABLE_TODO_TOOLS=1` (2.1.268).
# `TodoWrite` alone left the modern family completely undenied on exactly the
# model range where it is offered by default — a gap this list closes rather
# than one it was ever meant to leave open. `TaskStop` joins them for the same
# reason `IMPLEMENT_DISALLOWED` denies `Task`/`Agent` below: it can act on
# ANOTHER job's running background command, a cross-job blast radius a
# single-command transport has no legitimate reason to reach. `TaskOutput` is
# deliberately NOT listed: the binary removed it outright in 2.1.277 ("Claude
# reads a background task's output file with Read instead"), and a denylist
# entry for a tool that no longer exists denies nothing.
NARROW_DISALLOWED = [
    "Read", "Write", "Edit", "MultiEdit", "NotebookEdit", "NotebookRead",
    "Glob", "Grep", "WebFetch", "WebSearch", "Task", "Agent", "TodoWrite",
    "TaskCreate", "TaskGet", "TaskList", "TaskUpdate", "TaskStop",
    "SlashCommand", "Skill", "Artifact", "ExitPlanMode",
]

# What the IMPLEMENT stage loses. It is not the transport narrowing above — an
# implementer must keep Read/Write/Edit, Glob/Grep and Bash to do the work. It loses
# the tools that either defeat lane attribution or widen the trust boundary:
#
#   Task / Agent   A nested spawn is not the job. `hooks/lane-guard.sh` resolves a
#                  write by `agent_id` FIRST (`resolve_job`, :355-372); a nested agent
#                  carries a different one, and the only fallback is cwd-under-a-
#                  REGISTERED-WORKTREE — which a `direct`-mode job does not have. So a
#                  nested agent's writes are logged "job unresolved" and ALLOWED. The
#                  git-derived gate still sees the bytes afterwards, but attributes
#                  them to a job that did not write them, which is precisely the
#                  attribution the whole enforcement chain rests on.
#   SlashCommand   An implementer running `/v:dispatch` re-enters the pipeline from
#                  inside one of its own jobs.
#   WebFetch /     Research is a PRE-FLIGHT phase in this plugin (Trigger 0, the
#   WebSearch      doc-validator). An implementer holding write access and pulling
#                  untrusted web content into its own context is the injection surface
#                  the charter exists for. A job that genuinely needs external material
#                  gets it the same way every other job does: through a pre-flight, or
#                  pinned into `read_allowed` and the prompt.
#
# This is a REMOVAL of capability, deliberately. It is stated here rather than
# discovered by whoever wonders why their implementer cannot search.
IMPLEMENT_DISALLOWED = ["Task", "Agent", "SlashCommand", "WebFetch", "WebSearch"]

# What an implementer's shell may run, beyond the three plumbing forms.
#
# Dogfood r2 (2026-09-02, wf_f0505df2-99c) was the first REAL code job Engine C
# dispatched, and it could not do the job: the clamp admitted register-lane and
# two recall reads and nothing else, so the implementer could not run a test, a
# selftest, shellcheck, or `git rm`. Job A wrote "NOTHING IS VERIFIED" in its
# summary and was merged anyway because the Gate ran the floor; job B claimed a
# deletion it had been denied. Every docs-only dogfood before it never needed a
# shell, which is why the clamp survived 3.0.6 to 3.3.7 looking sound.
#
# The narrowing that matters is the one this list still expresses by OMISSION:
# no network (curl, wget, ssh, scp), no privilege (sudo), no scheduler
# (launchctl, crontab, open, osascript), no package installs, and no git that
# commits, pushes, rewrites history, or touches worktrees/remotes — merge-back
# and the wave commit belong to the finalizer. Writes outside the lane are still
# refused by lane-guard where it can parse them and by the git-derived scope gate
# in every case; the clamp is defence in depth, never the authority.
IMPLEMENT_SHELL = [
    "Bash(bash:*)", "Bash(sh:*)", "Bash(python3:*)", "Bash(/usr/bin/python3:*)",
    "Bash(python:*)", "Bash(node:*)", "Bash(npm:*)", "Bash(npx:*)", "Bash(pytest:*)",
    "Bash(make:*)", "Bash(go:*)", "Bash(cargo:*)", "Bash(shellcheck:*)",
    "Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)", "Bash(git show:*)",
    "Bash(git ls-files:*)", "Bash(git grep:*)", "Bash(git rm:*)", "Bash(git mv:*)",
    "Bash(git add:*)", "Bash(git rev-parse:*)",
    "Bash(ls:*)", "Bash(cat:*)", "Bash(head:*)", "Bash(tail:*)", "Bash(grep:*)",
    "Bash(find:*)", "Bash(wc:*)", "Bash(diff:*)", "Bash(sed:*)", "Bash(awk:*)",
    "Bash(sort:*)", "Bash(uniq:*)", "Bash(cut:*)", "Bash(tr:*)", "Bash(xargs:*)",
    "Bash(pwd:*)", "Bash(echo:*)", "Bash(printf:*)", "Bash(test:*)", "Bash(true:*)",
    "Bash(mkdir:*)", "Bash(rm:*)", "Bash(mv:*)", "Bash(cp:*)", "Bash(touch:*)",
    "Bash(chmod:*)", "Bash(cd:*)", "Bash(env:*)", "Bash(which:*)", "Bash(date:*)",
]

# "Continuity" runs once, before wave 0's Implement: it is the check that lets a
# relaunch skip a job state.json already records as merged.integrated, instead
# of re-spawning Implement and Gate on work that already landed (see
# `alreadyIntegratedIds` in JS_TEMPLATE and `cmd_integrated_jobs`).
STAGE_PHASES = ["Continuity", "Implement", "Gate", "Record", "Finalize"]

# Reserve, in tokens, assumed per queued agent when guarding fan-out against the
# native `budget` ceiling. Deliberately a round, declared constant rather than a
# measured figure: we have never measured per-agent spend, and inventing a number
# here would be a fabricated metric. It only has to be large enough that we stop
# scheduling BEFORE `agent()` throws, because a throw skips Record.
BUDGET_RESERVE_PER_AGENT = 50000


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def _run(cmd, cwd=None, env=None, text=True):
    """Run a command; never raise. Returns (rc, out, err)."""
    full_env = dict(os.environ)
    full_env["PYTHONDONTWRITEBYTECODE"] = "1"
    if env:
        full_env.update(env)
    try:
        proc = subprocess.Popen(
            cmd, cwd=cwd, env=full_env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        out, err = proc.communicate()
        if text:
            return (proc.returncode,
                    out.decode("utf-8", "replace"),
                    err.decode("utf-8", "replace"))
        return proc.returncode, out, err.decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 - a gate path must never raise
        return 127, ("" if text else b""), str(exc)


def _git(root, args, env=None, text=True):
    return _run(["git", "-C", root] + list(args), env=env, text=text)


def _load_yaml(path):
    try:
        import yaml
    except ImportError:
        raise SystemExit(
            "PyYAML is required. On macOS use /usr/bin/python3, which ships it."
        )
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _atomic_write(path, data):
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory or ".", prefix=".cv-tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
        os.replace(tmp, path)
        tmp = None
    finally:
        if tmp is not None and os.path.exists(tmp):
            os.unlink(tmp)


def _atomic_write_bytes(path, data):
    """`_atomic_write` for a binary artefact — the sealed patch is raw bytes.

    A `--binary` diff is not text: it carries literal-byte hunks and paths in
    whatever encoding the tree uses, and re-encoding it would change the very
    bytes whose sha256 the receipt pins.
    """
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory or ".", prefix=".cv-tmp-")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
        tmp = None
    finally:
        if tmp is not None and os.path.exists(tmp):
            os.unlink(tmp)


class _run_dir_lock(object):
    """Hold an exclusive lock across a whole READ-MODIFY-WRITE of a shared file.

    `_atomic_write` makes one WRITE atomic. It does nothing whatsoever for the
    READ that preceded it, and every shared file in a run dir — lane-map.json,
    state.json — is updated read-modify-write by agents that run CONCURRENTLY
    within a wave. Two implementers both read the pre-write map, both merge their
    own entry into it, and the second write drops the first's.

    The entry that goes missing is a LANE. hooks/lane-guard.sh resolves the
    acting job from that map; with no entry it resolves nothing, FAILS OPEN, and
    silently allows every write that job makes. That is the same hole as the map
    having no producer at all — only intermittent, and only under concurrency, so
    it presents as a flake rather than as a missing enforcement boundary.

    POSIX `flock` is the mechanism. If it cannot be taken, this RAISES rather
    than proceeding unlocked: an unserialized merge is exactly the failure being
    prevented, and "we could not lock, so we did it anyway" is fail-open.
    """

    def __init__(self, run_dir, name="run"):
        self.path = os.path.join(run_dir, ".%s.lock" % name)
        self.run_dir = run_dir
        self._fh = None

    def __enter__(self):
        import fcntl
        os.makedirs(self.run_dir, exist_ok=True)
        self._fh = open(self.path, "a+")
        fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        if self._fh is not None:
            try:
                import fcntl
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            finally:
                self._fh.close()
                self._fh = None
        return False


def _read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return default


def _js_json(obj):
    """JSON safe to paste into a JS source file.

    U+2028/U+2029 are legal inside JSON strings but are line terminators to some
    JS parsers; escape them rather than find out which parser we got.
    """
    text = json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False)
    return text.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def neutralize_in_data(json_text):
    """Escape a forbidden construct's `(` where it appears inside embedded DATA.

    A manifest's own prose legitimately talks about these constructs — this
    release's task-9 acceptance criterion literally reads "no `Date.now`,
    `Math.random`, bare `new Date()` or `import()`" — and that text is carried
    into the script as a JSON string inside an agent prompt. It is data, not
    code, and it would never execute. But the check that guards this file cannot
    tell the difference by looking, and neither can the runtime's own scanner, so
    a manifest that documents the rule would be unable to run under it.

    Escaping the `(` as `\\u0028` inside the JSON string leaves the DECODED value
    byte-identical — the agent reads exactly the prompt the manifest wrote — while
    the emitted source carries no literal forbidden construct. Applied ONLY to the
    JSON data blobs, never to the template's executable body: real code in the
    template must still be refused outright.
    """
    def escape_paren(match):
        text = match.group(0)
        idx = text.rindex("(")
        return text[:idx] + "\\u0028" + text[idx + 1:]

    for pattern, _name in FORBIDDEN_PATTERNS:
        json_text = re.sub(pattern, escape_paren, json_text)
    return json_text


def forbidden_hits(script_text):
    """Every forbidden-construct hit in an emitted script. [] means clean."""
    hits = []
    for pattern, name in FORBIDDEN_PATTERNS:
        for match in re.finditer(pattern, script_text):
            line = script_text.count("\n", 0, match.start()) + 1
            hits.append({"construct": name, "line": line})
    return hits


# --------------------------------------------------------------------------- #
# lane map — Feature E's missing producer
#
# hooks/lane-guard.sh resolves the acting job from the PreToolUse payload's
# `agent_id`, falling back to `cwd` -> worktree -> job. NOTHING WROTE THAT MAP:
# no run dir carries any of those fields, so the guard resolved no job, failed
# open, and silently allowed every write. Engine C writes it.
#
# HONEST LIMIT, stated because the alternative is a fabricated claim: on Claude
# Code 2.1.238 a spawned agent is not told its own `agent_id` — there is no
# CLAUDE_AGENT_ID (or equivalent) in its environment, and `agent()` does not
# return one to the script. So Engine C populates the `worktrees` half, which is
# the guard's documented second resolution step and the one the 1D probe proved
# works ("`cwd` IS the agent's worktree"). `agents` stays an empty object rather
# than being filled with something invented.
# --------------------------------------------------------------------------- #
def lane_map_path(run_dir):
    return os.path.join(run_dir, "lane-map.json")


def test_contract_path(run_dir, job_id):
    """`jobs/<job-id>.test-contract.json` — the resolved slice a worker is HANDED
    as `--test-contract-file`, and the slice `record` reads `scope` back out of."""
    return os.path.join(run_dir, "jobs", "%s.test-contract.json" % job_id)


def register_lane(run_dir, job_id, cwd, manifest_path=None, agent_id=None, wrapper=False):
    """Bind one job to its real worktree (and agent id, if ever available).

    MERGES; never overwrites — and the merge is SERIALIZED, which is what makes
    that claim true. Concurrent implementers in the same wave each call this, and
    an unlocked read-modify-write let the second writer drop the first's lane:
    `_atomic_write` protects the write, not the read that chose what to write.
    A dropped lane is a job the guard cannot resolve, and an unresolved job is a
    guard that fails open and allows every write it makes.
    """
    path = lane_map_path(run_dir)
    run_id = os.path.basename(os.path.normpath(run_dir))
    with _run_dir_lock(run_dir):
        existing = _read_json(path, None)
        if not isinstance(existing, dict):
            existing = {}
        existing.setdefault("run_id", run_id)
        existing.setdefault("agents", {})
        existing.setdefault("worktrees", {})
        existing["manifest"] = (
            manifest_path
            or existing.get("manifest")
            or os.path.join(run_dir, "manifest.yaml")
        )
        if cwd:
            if wrapper:
                # An external job's WRAPPER runs at the checkout and writes nothing
                # itself; recording the checkout as its "worktree" made the lane
                # guard's cwd fallback attribute every sibling worktree job (the
                # root is a prefix of all of them) to the wrapper's job and deny its
                # writes (stage-4 dogfood, finding 78). A wrapper is listed, never
                # claimed.
                existing.setdefault("wrappers", {})[os.path.abspath(cwd)] = job_id
                existing["worktrees"].pop(os.path.abspath(cwd), None)
            else:
                existing["worktrees"][os.path.abspath(cwd)] = job_id
        if agent_id:
            existing["agents"][agent_id] = job_id
        _atomic_write(path, json.dumps(existing, indent=2, sort_keys=True) + "\n")
    return existing


# --------------------------------------------------------------------------- #
# state.json — the fields the integration authority needs
#
# A smoke run of compound-v-integration-gate.py against THIS release's own run
# dir returned `unverifiable` for EVERY job: no results/ directory, `worktree`
# null, no `baseline`. The gate fails closed correctly, so AC-24 is inert until
# something records them. That something is here.
# --------------------------------------------------------------------------- #
def _load_state(run_dir):
    state = _read_json(os.path.join(run_dir, "state.json"), None)
    if not isinstance(state, dict):
        state = {
            "run_id": os.path.basename(os.path.normpath(run_dir)),
            "phase": "DISPATCHED",
            "jobs": {},
        }
    state.setdefault("jobs", {})
    return state


def _utc_stamp():
    """ISO-8601 UTC seconds, the shape every other stamp in the run dir uses."""
    import time as _time
    return _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())


def _save_state(run_dir, state, now=None):
    if now:
        state["updated_at"] = now
    _atomic_write(
        os.path.join(run_dir, "state.json"),
        json.dumps(state, indent=2, sort_keys=False) + "\n",
    )


def _head_commit(root):
    rc, out, _ = _git(root, ["rev-parse", "HEAD"])
    if rc != 0:
        return None
    out = out.strip()
    return out if re.match(r"^[0-9a-f]{40}$", out) else None


def _manifest_job(manifest, job_id):
    for job in (manifest.get("jobs") or []):
        if job.get("id") == job_id:
            return job
    return None
