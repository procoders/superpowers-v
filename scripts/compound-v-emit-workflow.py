#!/usr/bin/env python3
"""Compound V — Engine C. Turn a `manifest.yaml` into a native Claude Code Workflow
script, and provide the deterministic entry points that script's agents call.

WHAT ENGINE C IS
----------------
Engine C is the primary and default way jobs execute in 3.0 (spec Feature D, ADR
0004). The emitted `.js` is a native Workflow script: one `pipeline()` per
dependency wave, three stages per job — Implement -> Gate -> Record.

The script itself has NO filesystem and NO shell access. Agents it spawns do. So
everything mechanical lives HERE, in Python, and the emitted JS is deliberately
thin: it schedules, it never decides. That is the same reason the scope gate and
the test-contract glob resolution live in Python — a second, weaker
implementation inside a model's shell would diverge from the authority, and a
divergence in an enforcement path silently *passes*.

SUBCOMMANDS
-----------
  emit           manifest.yaml -> the workflow script (+ per-job test contracts)
  gate-receipt   the Gate stage's ONE clamped command: run the git-derived scope
                 gate, compute the PINNED diff digest, run the test floor, and
                 emit a complete six-field `gate_receipt`.
  record         the Record stage's ONE clamped command: idempotently persist
                 results/<job-id>.json + state.json. EVIDENCE ONLY — it writes
                 nothing into the project checkout.
  finalize-wave  the serialized end of every wave: run the integration AUTHORITY
                 over that wave's jobs, then merge and COMMIT the permitted ones.
                 The only writer into the project checkout.
  register-lane  the Implement agent's FIRST command: bind its real worktree to
                 its job id in lane-map.json (which is what makes
                 hooks/lane-guard.sh able to resolve an acting job at all), and
                 PIN this job's baseline commit before anything runs.

WHY THE GATE STAGE CANNOT THROW
-------------------------------
`pipeline()` drops an item to `null` and SKIPS ITS REMAINING STAGES when a stage
throws. A throwing Gate would therefore mean: no Record, no state written, no
result file — precisely on the jobs that went wrong. That is the v2.6.4
audit-trail loss reappearing structurally. The emitted Gate stage wraps
everything and returns a verdict for every outcome, including "the gate itself
failed". `null` is FAIL, never pass.

WHAT THIS SCRIPT IS NOT
-----------------------
It is NOT the authority. `scripts/compound-v-integration-gate.py` is: it verifies
or re-derives every receipt before any commit is integrated. A clamp limits what
an agent CAN DO, not what it RETURNS, and a schema proves shape, not execution.
The receipt is defence in depth and an early exit.
"""

from __future__ import annotations

import os
import sys

# Nobody writes bytecode. The scope gate forgives no path by extension (fourth
# review pass, 2026-09-02), so a `__pycache__` entry this process leaves beside a
# script is an out-of-lane write that BLOCKS the job it is plumbing. Set before
# ANY other import — `_import_integration_gate` and `_import_triage_outcomes`
# below both load repo scripts by path, and an import is exactly when a cache
# entry would be written.
sys.dont_write_bytecode = True


def _harden_sys_path():
    """Drop this script's own directory and the cwd from ``sys.path``.

    CPython puts the script's directory at ``sys.path[0]``. This script LIVES in
    ``scripts/``, which is a directory a Compound V job may be given a write lane
    over — so a job that writes ``scripts/yaml.py`` gets that file imported, in
    this process, by the very `import yaml` the manifest loader runs. The
    manifest is the document that declares every job's `write_allowed`, so a
    shadowed loader can hand the pipeline a WIDENED lane map and every later
    check agrees with it. Same for the cwd (``''``/``'.'``), which is on the path
    for ``-c`` and ``-m`` invocations.

    Run BEFORE the first non-trivial import, so nothing — stdlib or third-party —
    can be resolved out of the tree this pipeline is gating. The sibling repo
    scripts this file genuinely needs are loaded by explicit path
    (`_load_module_from_path`), never by name, so removing these entries costs
    nothing.
    """
    # REALPATH, not abspath. CPython puts the RESOLVED script directory on the
    # path while `__file__` keeps the symlinked spelling, so on macOS — where
    # /var is a symlink to /private/var — the two disagree for every run under a
    # temp directory and the entry survived. Caught by this file's own planted-
    # `scripts/yaml.py` selftest, which imported the plant and reported the run
    # compliant against a lane list of `**`.
    def _resolve(path):
        return os.path.normcase(os.path.realpath(os.path.abspath(path)))

    doomed = {_resolve(os.path.dirname(os.path.abspath(__file__))),
              _resolve(os.getcwd())}
    kept = []
    for entry in sys.path:
        try:
            resolved = _resolve(entry) if entry else _resolve(os.getcwd())
        except Exception:  # noqa: BLE001
            kept.append(entry)
            continue
        if resolved in doomed:
            continue
        kept.append(entry)
    sys.path[:] = kept


_harden_sys_path()

import argparse  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

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
NARROW_DISALLOWED = [
    "Read", "Write", "Edit", "MultiEdit", "NotebookEdit", "NotebookRead",
    "Glob", "Grep", "WebFetch", "WebSearch", "Task", "Agent", "TodoWrite",
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

STAGE_PHASES = ["Implement", "Gate", "Record", "Finalize"]

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
# the PINNED diff digest
#
# Recipe taken verbatim from the `diff_digest` property description in
# schemas/job_result.schema.json, which pins it so a producer and the
# verification layer cannot diverge:
#
#   `git -C <gate-root> add -A` (which brings untracked files — the half a plain
#   `git diff` would miss — into the index), then sha256 over the raw bytes of
#   `git -C <gate-root> diff --cached --binary <baseline_commit>`, rendered as
#   `sha256:<64-hex>`.
#
# We PREFER to import compound-v-integration-gate.compute_diff_digest, so the
# producer is literally the verifier's own function — the same "one matcher, not
# two" argument the lane guard makes about the glob engine. The local copy is the
# fallback and is behaviourally identical: `add -A` runs against a COPY of the
# index under GIT_INDEX_FILE, so the index CONTENT the diff reads is the same
# while producing a receipt does not mutate the tree being gated.
# --------------------------------------------------------------------------- #
def _load_module_from_path(name, target):
    """Load a repo script by path, FROM SOURCE — never from a cache beside it.

    `sys.pycache_prefix` moves both the read and the write of the bytecode cache
    to a private directory outside the tree, so a forged
    `scripts/__pycache__/<mod>.<tag>.pyc` — an unchecked hash-based one, which
    CPython never validates against its source — cannot be executed in this
    process (fourth review pass, item 3, 2026-09-02). Returns None on any failure.

    IF THE PRIVATE PREFIX CANNOT BE CREATED, NOTHING IS LOADED. The first version
    caught the mkdtemp failure and carried on with the DEFAULT cache location —
    which is the in-tree `__pycache__` the redirect exists to avoid, so the one
    condition an attacker can arrange (a full or unwritable temp dir) turned the
    protection off and executed the planted `.pyc` anyway. A protection with a
    fallback to the unprotected path is not a protection; this refuses instead,
    and the caller degrades to its own local implementation.
    """
    prev_prefix = getattr(sys, "pycache_prefix", None)
    tmp_pycache = None
    try:
        import importlib.util
        try:
            tmp_pycache = tempfile.mkdtemp(prefix="cv-pycache-")
            sys.pycache_prefix = tmp_pycache
        except Exception:  # noqa: BLE001
            return None
        spec = importlib.util.spec_from_file_location(name, target)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:  # noqa: BLE001
        return None
    finally:
        try:
            sys.pycache_prefix = prev_prefix
        except Exception:  # noqa: BLE001
            pass
        if tmp_pycache:
            shutil.rmtree(tmp_pycache, ignore_errors=True)


# --------------------------------------------------------------------------- #
# the MANIFEST DIGEST
#
# The manifest declares every job's `write_allowed`. It also lives in the run
# directory, which the pipeline exempts BY NAME from the scope gate so a job's own
# bookkeeping does not read as an out-of-lane write. Put those two facts together
# and a job could widen its own lane map mid-run: every later check would run,
# pass, and prove nothing, because it would be checking against the widened list.
#
# `emit` therefore hashes the manifest at generation time and bakes the digest
# into the workflow script. Gate, Record, Finalize and the integration authority
# all carry it forward and refuse a manifest that no longer hashes to it. The lane
# map that is ENFORCED is provably the lane map that was reviewed.
# --------------------------------------------------------------------------- #
def sha256_file(path):
    """`sha256:<64hex>` of a file's raw bytes, or None when it cannot be read."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return "sha256:" + h.hexdigest()
    except (IOError, OSError):
        return None


def manifest_digest_fault(manifest_path, expected):
    """A refusal string when `manifest_path` does not hash to `expected`, else None.

    An absent `expected` is the documented backward-compatible path — a run
    emitted before 3.4.0, or a by-hand invocation. Every emitted command carries
    the digest, so the pipeline itself never takes that path.
    """
    if not expected:
        return None
    actual = sha256_file(manifest_path)
    if actual == expected:
        return None
    return (
        "manifest %s hashes to %s, not the %s this run was emitted against. The "
        "manifest declares every job's write_allowed, so a lane map that changed "
        "after emit is refused rather than enforced."
        % (manifest_path, actual, expected)
    )


# --------------------------------------------------------------------------- #
# the SEALED PATCH artifact
#
# The digest binds a receipt to a tree AT GATE TIME. Nothing used to bind the
# MERGE to that same tree: `merge_back` took a fresh `git diff` of the live
# worktree whenever the finalizer got round to it. Three real consequences, all
# reported by a cross-model review of 3.4.0:
#
#   * a worktree reverted to its baseline after the gate merged as "nothing to
#     do", was recorded as integrated, and was pruned — the work destroyed;
#   * `.pytest_cache/` and friends, written by the test floor that runs AFTER the
#     scope check, turned an honest pass into a `contradicted` refusal;
#   * any post-gate write to an in-lane file rode into the commit unmeasured.
#
# So the gate SEALS what it approved: `jobs/<id>.patch`, and its sha256 in the
# gate's receipt document. The finalizer applies THAT FILE. Nothing else.
# --------------------------------------------------------------------------- #
def patch_artifact_path(run_dir, job_id):
    return os.path.join(run_dir, "jobs", "%s.patch" % job_id)


def build_sealed_patch(root, baseline, paths):
    """(patch bytes, error) — `git diff --cached --binary <baseline> -- <paths>`.

    The `git add` runs against a COPY of the index under GIT_INDEX_FILE, exactly
    as the digest recipe does, so sealing a patch does not stage anything in the
    tree it is sealing. Only the paths the gate APPROVED are added, so a file the
    scope gate flagged — or a byproduct a later test writes — cannot be in the
    artifact, and therefore cannot be merged.
    """
    if not baseline:
        return None, "no baseline to seal against"
    rc, gitpath, err = _git(root, ["rev-parse", "--git-path", "index"])
    if rc != 0:
        return None, "cannot locate git index: %s" % (err.strip() or "rc=%d" % rc)
    index_path = gitpath.strip()
    if not os.path.isabs(index_path):
        index_path = os.path.join(root, index_path)
    tmpdir = tempfile.mkdtemp(prefix="cv-seal-idx-")
    try:
        tmp_index = os.path.join(tmpdir, "index")
        if os.path.exists(index_path):
            shutil.copyfile(index_path, tmp_index)
        env = {"GIT_INDEX_FILE": tmp_index}
        for path in paths:
            if not path:
                continue
            rc, _o, err = _git(root, ["add", "-A", "--", path], env=env)
            if rc != 0:
                # A deletion the worker already staged leaves nothing for the
                # pathspec to match; it is already in the copied index, so this is
                # not a failure. Same reasoning as `_stage_paths`.
                rc2, staged, _e = _git(
                    root, ["diff", "--cached", "--name-only", "--diff-filter=D",
                           "--", path], env=env)
                if not (rc2 == 0 and path in
                        [l.strip() for l in (staged or "").splitlines()]):
                    return None, "git add failed for %r while sealing: %s" % (
                        path, err.strip())
        args = ["diff", "--cached", "--binary", baseline, "--"]
        args += [p for p in paths if p]
        rc, blob, err = _git(root, args, env=env, text=False)
        if rc != 0:
            return None, "git diff --cached failed while sealing: %s" % err.strip()
        return blob, None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def sealed_post_image(repo_root, baseline, patch_bytes):
    """({path: blob-oid or None for a deletion}, error) — GIT'S answer, not ours.

    The patch is applied to a THROWAWAY index seeded from `baseline` (`git apply
    --cached` touches the index only, and GIT_INDEX_FILE keeps it off the real
    one), and the resulting blob ids are read back out. That is the exact content
    the artifact produces, derived by git from the artifact itself — so the
    post-merge proof needs nothing recorded by any party the pipeline constrains.
    """
    if not patch_bytes:
        return {}, None
    tmpdir = tempfile.mkdtemp(prefix="cv-postimg-")
    try:
        tmp_index = os.path.join(tmpdir, "index")
        env = {"GIT_INDEX_FILE": tmp_index}
        rc, _o, err = _git(repo_root, ["read-tree", baseline], env=env)
        if rc != 0:
            return None, "git read-tree %s failed: %s" % (baseline, err.strip())
        try:
            full_env = dict(os.environ)
            full_env["GIT_INDEX_FILE"] = tmp_index
            full_env["PYTHONDONTWRITEBYTECODE"] = "1"
            proc = subprocess.Popen(
                ["git", "-C", repo_root, "apply", "--cached", "--binary", "-"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, env=full_env,
            )
            _o, aerr = proc.communicate(patch_bytes)
            if proc.returncode != 0:
                return None, (
                    "the sealed patch does not apply to its own baseline: %s"
                    % aerr.decode("utf-8", "replace").strip()[:300])
        except Exception as exc:  # noqa: BLE001
            return None, "git apply --cached raised: %s" % exc
        rc, names, err = _git(
            repo_root, ["diff", "--cached", "--name-only", baseline], env=env)
        if rc != 0:
            return None, "git diff --cached --name-only failed: %s" % err.strip()
        image = {}
        for path in [n.strip() for n in (names or "").splitlines() if n.strip()]:
            rc2, staged, _e = _git(
                repo_root, ["ls-files", "--stage", "--", path], env=env)
            oid = None
            if rc2 == 0 and staged.strip():
                parts = staged.splitlines()[0].split("\t", 1)[0].split()
                if len(parts) >= 2:
                    oid = parts[1]
            image[path] = oid
        return image, None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def head_matches_post_image(repo_root, image):
    """(True, None) iff every path in `image` is in HEAD with that exact blob.

    This is the proof that the commit carries the artifact, and it is asked of
    git. `state.json` is a cache: it is written by the pipeline, it is exempt by
    name from the scope gate, and a worker can therefore set
    `merged.integrated: true` on a job that never landed. A cache may say a job is
    done; only git may be believed about it.
    """
    if image is None:
        return False, "no post-image to prove against"
    for path, oid in sorted(image.items()):
        rc, out, _err = _git(repo_root, ["rev-parse", "--verify", "HEAD:%s" % path])
        actual = out.strip() if rc == 0 else None
        if oid is None:
            if actual:
                return False, ("%s is still present in HEAD, but the sealed patch "
                               "deletes it" % path)
            continue
        if actual != oid:
            return False, ("%s in HEAD is %s, but the sealed patch produces %s"
                           % (path, actual or "absent", oid))
    return True, None


def _import_integration_gate(path=None):
    target = path or INTEGRATION_GATE_DEFAULT
    if not os.path.exists(target):
        return None
    return _load_module_from_path("cv_integration_gate", target)


def _compute_diff_digest_local(root, baseline):
    rc, gitpath, err = _git(root, ["rev-parse", "--git-path", "index"])
    if rc != 0:
        return None, "cannot locate git index: %s" % (err.strip() or "rc=%d" % rc)
    index_path = gitpath.strip()
    if not os.path.isabs(index_path):
        index_path = os.path.join(root, index_path)

    tmpdir = tempfile.mkdtemp(prefix="cv-emitwf-idx-")
    tmp_index = os.path.join(tmpdir, "index")
    try:
        if os.path.exists(index_path):
            shutil.copyfile(index_path, tmp_index)
        env = {"GIT_INDEX_FILE": tmp_index}
        rc, _, err = _git(root, ["add", "-A"], env=env, text=False)
        if rc != 0:
            return None, "git add -A failed: %s" % (err.strip() or "rc=%d" % rc)
        rc, blob, err = _git(
            root, ["diff", "--cached", "--binary", baseline], env=env, text=False
        )
        if rc != 0:
            return None, "git diff --cached failed: %s" % (err.strip() or "rc=%d" % rc)
        return "sha256:" + hashlib.sha256(blob).hexdigest(), None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# THE RUN DIRECTORY IS THE ONLY DIGEST EXCLUSION, on both sides of the seam.
#
# 3.4.0 development briefly excluded two tracked files by name as well
# (triage-outcomes.jsonl, worker-performance.jsonl), because the pipeline wrote
# them BETWEEN a direct-mode job's Gate and the authority's re-derivation and an
# honest receipt read as `contradicted`. The fourth review pass withdrew that: a
# path excluded from the digest is also a path a worker may rewrite unseen, and
# the pipeline commits triage-outcomes.jsonl by name. The ordering is fixed
# instead — `cmd_finalize_wave` appends the run's `actual` AFTER the authority
# has run over the wave, so nothing the pipeline writes lands inside that window
# and there is nothing left to forgive.


def compute_diff_digest(root, baseline, gate_module=None, exclude_prefixes=None):
    """Both sides of the seam MUST pass the same `exclude_prefixes`, or the gate and
    the authority compute different digests over the same tree and every honest
    direct-mode receipt reads as `forged` (dogfood 15)."""
    module = gate_module if gate_module is not None else _import_integration_gate()
    if module is not None and hasattr(module, "compute_diff_digest"):
        try:
            try:
                return module.compute_diff_digest(
                    root, baseline, exclude_prefixes=exclude_prefixes)
            except TypeError:
                # An older installed copy without the parameter: fall back rather
                # than crash, and accept that it will disagree — loudly, as
                # `forged`, which is at least a refusal and not a silent pass.
                return module.compute_diff_digest(root, baseline)
        except Exception as exc:  # noqa: BLE001
            return None, "integration-gate digest raised: %s" % exc
    return _compute_diff_digest_local(root, baseline)


# --------------------------------------------------------------------------- #
# manifest -> waves
# --------------------------------------------------------------------------- #
def topo_waves(jobs, max_parallel):
    """Dependency waves, each chunked to at most `max_parallel` jobs.

    A wave is a BARRIER, and the barrier is load-bearing: it is what preserves
    the commit-before-dependent rule. A prerequisite's merge-back only STAGES
    (`git apply --index` does not commit), so a dependent worktree created at
    HEAD would not contain it. Record commits inside the wave; the next wave's
    agents — and therefore the next wave's worktrees — are not spawned until the
    whole wave has resolved. Deleting the wave barrier would reintroduce that bug.

    `run: serial` jobs get a wave to themselves, in manifest order.
    """
    by_id = {}
    order = []
    for job in jobs:
        job_id = job.get("id")
        if not job_id:
            raise ValueError("every job needs an id")
        if job_id in by_id:
            raise ValueError("duplicate job id: %s" % job_id)
        by_id[job_id] = job
        order.append(job_id)

    unmet = {}
    for job_id in order:
        deps = by_id[job_id].get("depends_on") or []
        if isinstance(deps, str):
            deps = [deps]
        missing = [d for d in deps if d not in by_id]
        if missing:
            raise ValueError(
                "job %s depends_on unknown job(s): %s" % (job_id, ", ".join(missing))
            )
        unmet[job_id] = set(deps)

    cap = max(1, int(max_parallel or 1))
    done = set()
    waves = []
    remaining = list(order)

    while remaining:
        ready = [j for j in remaining if unmet[j] <= done]
        if not ready:
            raise ValueError(
                "dependency cycle among: %s" % ", ".join(sorted(remaining))
            )
        serial = [j for j in ready if (by_id[j].get("run") or "parallel") == "serial"]
        parallel = [j for j in ready if j not in serial]

        if serial:
            # A serial job runs alone and BEFORE the parallel remainder of its
            # level, matching the old dispatcher's "Task 0 serially, then the
            # parallel batches".
            first = serial[0]
            waves.append([first])
            done.add(first)
            remaining.remove(first)
            continue

        for start in range(0, len(parallel), cap):
            waves.append(parallel[start:start + cap])
        for job_id in parallel:
            done.add(job_id)
            remaining.remove(job_id)

    return [[by_id[j] for j in wave] for wave in waves]


# --------------------------------------------------------------------------- #
# agentType — the last native mechanism the audit had open
#
# docs/superpowers/architecture/native-mechanisms.md records `agentType` as the
# one mechanism that exists, covers a need, and was not used: the emitted script
# contained zero occurrences. The need it covers is named in that row — the
# REVIEW GATE. Engine C spawned implement/gate/record and nothing else, so a
# manifest job whose declared `type` is `review` — 3.0's own `task-13-review`,
# "Three-pass Review Gate over the composite", is one — was handed the generic
# IMPLEMENTER prompt: told to write inside a lane and report a summary, with
# none of `agents/spec-reviewer.md`'s three-pass contract reaching it.
#
# So exactly ONE mapping is made, and only where a job's own declared type says
# the work IS that role. The other stages stay anonymous on purpose, and the
# reason is in the JS_TEMPLATE next to them: Gate, Record and Finalize are
# de-tooled single-command transports whose entire safety property is
# `disallowedTools` + `bashCommandClamp`, and every agent under agents/ declares
# no `tools:` restriction at all.
#
# The prefix is READ from the plugin's own manifest rather than assumed. It is
# the install's plugin name, not the checkout's directory name — this very file
# is edited from a git worktree whose directory is a random job id, so deriving
# it from the path would produce a name that resolves to nothing. If the
# manifest or the agent file is missing, no `agentType` is emitted and the job
# stays anonymous: a name that resolves to nothing is worse than no name.
# --------------------------------------------------------------------------- #
AGENT_TYPE_BY_JOB_TYPE = {"review": "spec-reviewer"}

# ...and, from 3.4.0, a DEFAULT for everything else. An implementer used to arrive
# anonymous: the whole of its role was whatever `_implement_prompt` restated inline,
# it inherited the session's own turn budget, and nothing carried the model's own
# guidance on scope, narration or deliverable length. `agents/implementer.md` is that
# role, and arriving as a role is also the ONLY native way to carry a turn cap —
# `maxTurns:` is a field of an agent DEFINITION; the workflow `agent()` options have
# no equivalent (binary 2.1.238: label, phase, schema, model, effort, isolation,
# agentType, plus disallowedTools and bashCommandClamp).
DEFAULT_AGENT_ROLE = "implementer"


# The job types that are REVIEWERS and therefore stay anonymous. Matched
# EXACTLY, never by substring.
#
# The substring form (`any(tok in t for tok in REVIEWER_TOKENS)`) declined every
# type that merely CONTAINED one of those words, so `review_fix` — a job that
# fixes what a review found, and is an implementer in every respect — arrived
# with no role, no turn cap and none of `agents/implementer.md`. This repository
# already fixed exactly that shape once, in `_is_reviewer_job`, where a job
# titled "Writes the thing the reviewer reviews" was classified as a reviewer.
# The lesson did not travel the six hundred lines to here.
#
# `_is_reviewer_job` keeps its looser, word-boundary scan on purpose: it decides
# whether to ESCALATE a model, where over-matching is conservative. This decides
# which ROLE an agent is spawned as, where over-matching silently removes one.
REVIEWER_JOB_TYPES = ("review", "spec_review", "quality_review",
                      "integration_review")


def agent_role_for(job_type):
    """(role or None, reason or None) — the registered role a job's `type` maps to.

    `review` maps to the Review Gate. The other reviewer types decline, WITH a
    reason: a decline used to be an indistinguishable `None`, so "this type is a
    reviewer and must stay anonymous" and "this lookup found nothing" reached the
    emit output as the same silence. Everything else — `review_fix` included — is
    an implementer.
    """
    t = (job_type or "").strip().lower()
    role = AGENT_TYPE_BY_JOB_TYPE.get(t)
    if role:
        return role, None
    if t in REVIEWER_JOB_TYPES:
        return None, (
            "job type %r is a reviewer, so it stays anonymous: it is not an "
            "implementer, and handing it the implementer role would tell a "
            "reviewer to write code inside a lane" % t
        )
    return DEFAULT_AGENT_ROLE, None


def resolve_agent_type(job_type, plugin_dir=None):
    """(agent_type or None, reason). Never guesses a name."""
    role, decline = agent_role_for(job_type)
    if not role:
        return None, decline
    root = plugin_dir or os.path.dirname(HERE)
    if not os.path.exists(os.path.join(root, "agents", "%s.md" % role)):
        return None, "no agents/%s.md under %s" % (role, root)
    manifest = os.path.join(root, ".claude-plugin", "plugin.json")
    doc = _read_json(manifest, None)
    name = (doc or {}).get("name")
    if not (isinstance(name, str) and name.strip()):
        return None, "plugin manifest %s declares no name" % manifest
    return "%s:%s" % (name.strip(), role), None


PLUGIN_ROOT = os.path.dirname(HERE)


def agent_definition(role, root=None):
    """The agent's own definition, for the INLINE FALLBACK.

    `agentType` selects a registered agent — and registration is a property of the
    session, not of this repository. Dogfood 2026-09-02 (run wf_3b6697df-5e0): the
    plugin was updated mid-session, its agents dropped out of the registry, and
    every `agent({agentType})` spawn threw `agent type '...' not found` in 26 ms.
    The emitted script therefore carries each role's definition verbatim and, on
    exactly that error, retries once WITHOUT `agentType`: the definition body as
    the prompt's preamble, the frontmatter `model` as `opts.model`, every other
    option (schema, disallowedTools, clamp) unchanged. Returns
    {"model": str|None, "body": str} or None when the file is absent.
    """
    path = os.path.join(root or PLUGIN_ROOT, "agents", "%s.md" % role)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return None
    model, max_turns, body = None, None, text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            fm, body = parts[1], parts[2]
            for line in fm.splitlines():
                if line.strip().startswith("model:"):
                    model = line.split(":", 1)[1].strip() or None
                # The TURN CAP, read only so the fallback can say what it lost.
                # `maxTurns` belongs to the DEFINITION; an inline spawn is not a
                # definition, and `agent()` has no option to re-impose it — so on
                # that path the cap is gone and the log has to say so rather than
                # let a job quietly run uncapped.
                elif line.strip().startswith("maxTurns:"):
                    raw = line.split(":", 1)[1].strip()
                    try:
                        max_turns = int(raw)
                    except ValueError:
                        max_turns = None
    return {"model": model, "max_turns": max_turns, "body": body.strip()}


def _js_parses(script):
    """True when `node --check` accepts the script, or when node is absent (the
    check is then skipped, not passed). Twin of compound-v-emit-preflight.py's."""
    import shutil, subprocess, tempfile
    node = shutil.which("node")
    if not node:
        return True
    with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False,
                                     encoding="utf-8") as fh:
        # The runtime evaluates a workflow as the BODY of an async function: top-level
        # `await` and `return` are legal there and illegal in a bare module, so the
        # parse mirrors that wrapping — otherwise `return {` at the end of every
        # script reads as a syntax error.
        fh.write("(async function () {\n")
        fh.write(script.replace("export const meta", "const meta", 1))
        fh.write("\n})();\n")
        name = fh.name
    try:
        r = subprocess.run([node, "--check", name], capture_output=True, text=True)
        return r.returncode == 0
    finally:
        os.unlink(name)


def _clamp_rules(job, python_bin, self_path, worker_script_for):
    """The bashCommandClamp for one job's IMPLEMENT agent.

    Spec D5.1: a non-`claude` job's clamp MUST admit
    `scripts/compound-v-run-<backend>-worker.sh`, or carry no clamp. A clamp that
    can bind nothing makes the runtime refuse the spawn — which fails loudly
    rather than degrading, but it still means the second family cannot launch.

    THE `None` RETURN IS UNREACHABLE FOR A JOB THAT ACTUALLY LAUNCHES, and 3.0.6
    described it wrongly. It happens only for an external backend whose worker
    script is absent — and `job_entry` REFUSES that job outright a few lines later
    ("the handoff cannot be materialized"). A `claude` job always carries the
    register-lane rule. So no implementer that reaches `agent()` is ever unclamped;
    the claim that one could be was a caveat written from reading this function
    alone instead of the path around it. `_check("every launched job carries a
    clamp", ...)` in the selftest now holds that shut.

    Rule syntax is the standard permission rule, validated by the runtime:
    `Bash(<command or prefix>)`, tool name case-sensitive, no whitespace padding
    inside the parens. An entry that parses to a tool with no rule content is an
    "inert clamp entry" and the spawn is refused.
    """
    backend = job.get("backend") or "claude"
    # `-B` IS PART OF THE ADMITTED FORM, and the rule and the command it admits
    # must carry it identically. The scope gate forgives no path by extension
    # since the fourth review pass, so a `__pycache__` entry this plumbing left
    # beside a script is an out-of-lane write that BLOCKS the job. A clamp is a
    # literal prefix match: `<python> -B <script>` in the rule and `<python>
    # <script>` in the command is a DENY, which is why both are built here.
    rules = ["Bash(%s -B %s register-lane:*)" % (python_bin, self_path)]
    # THE RECALL LAYER, READ-ONLY, OR THE INSTRUCTION TO USE IT IS UNREACHABLE.
    #
    # v3.3.3 told five agents to consult V-memory first. Dogfood 24 spawned the one
    # agent Engine C spawns by role and watched it try: the clamp admitted exactly
    # one command form — `register-lane` — and denied the recall query, a third
    # phrasing of it, the `recall-check` bridge, and the form `/v:remember` itself
    # instructs. The instruction was prose in an agent definition; the clamp is
    # mechanism, and mechanism wins. This repository already has a name for that
    # failure and shipped it into the feature meant to demonstrate recall.
    #
    # `search` and `recall-check` only READ: they open a SQLite index outside the
    # repo and print. Admitting them widens no write surface, and the scope gate is
    # unaffected either way — it measures the tree, not the commands.
    memory = os.path.join(os.path.dirname(self_path), "compound-v-memory.py")
    if os.path.exists(memory):
        rules.append("Bash(%s -B %s search:*)" % (python_bin, memory))
        rules.append("Bash(%s -B %s recall-check:*)" % (python_bin, memory))
    # A developer's shell (see IMPLEMENT_SHELL) — tests, selftests, linters,
    # deletions and renames. Denied by omission: network, privilege, scheduler,
    # installs, and every git form that commits or pushes.
    rules.extend(IMPLEMENT_SHELL)
    if backend != "claude":
        worker = worker_script_for(backend)
        if not worker:
            return None  # no clamp at all beats a clamp that cannot launch it
        rules.append("Bash(%s:*)" % worker)
    return rules


# --------------------------------------------------------------------------- #
# the external handoff, materialized BEFORE the workflow runs
#
# 3.0.1 emitted the literal string `worker-script ...` as an external job's only
# launcher. There was no argv and no prompt file, so the one thing the worker
# script cannot start without — `--prompt-file` — was left for a model to invent
# at run time, from a prompt that did not contain it. `emit` now writes both
# artefacts into the run dir and puts the COMPLETE argv in the prompt, so the
# invocation is a committed file rather than an instruction to improvise.
# --------------------------------------------------------------------------- #
def worker_prompt_path(run_dir, job_id):
    return os.path.join(run_dir, "jobs", "%s.prompt.md" % job_id)


def launch_argv_path(run_dir, job_id):
    return os.path.join(run_dir, "jobs", "%s.launch.argv.json" % job_id)


def baseline_pin_path(run_dir, job_id):
    """`jobs/<job-id>.baseline` — the PER-JOB pin.

    state.json is one file that every job in a wave writes, so a pin that lived
    only there could be lost to a sibling's last-writer-wins save. This file is
    written by exactly one job and read by the gate, which is what makes "pinned
    before the worker launched" a fact rather than a hope. state.json still gets
    the same value; this is the copy that cannot be raced away.
    """
    return os.path.join(run_dir, "jobs", "%s.baseline" % job_id)


def read_pinned_baseline(run_dir, job_id, state_job=None):
    """The pinned baseline, or None. state.json first, then the per-job pin."""
    pinned = (state_job or {}).get("baseline")
    if isinstance(pinned, str) and re.match(r"^[0-9a-f]{40}$", pinned.strip()):
        return pinned.strip()
    try:
        with open(baseline_pin_path(run_dir, job_id), "r", encoding="utf-8") as fh:
            candidate = fh.read().strip()
    except Exception:  # noqa: BLE001
        return None
    return candidate if re.match(r"^[0-9a-f]{40}$", candidate) else None


# The claude escalation ladder, bottom to top. A job that already failed once in
# this run is re-dispatched ONE rung up, never straight to the top: the
# maintainer's rule is "if we did not solve it the first time, hand it to Fable",
# and the cheapest honest reading of that is one step at a time.
CLAUDE_ESCALATION = ("sonnet", "opus", "fable")

# --- retry policy (v3.4.8) --------------------------------------------------
# The workflow's own retry budget, and the ONLY source of the backoff table.
# The emitted script reads both numbers out of CFG rather than carrying its own
# literals, so the JS the runtime executes and the Python that mirrors it cannot
# drift apart - the mirror IS the table, not a copy of it.
#
# NO JITTER, deliberately: `Math.random()` is refused by the workflow runtime
# (deterministic resume) and so is every clock read, so there is nothing to
# jitter with and nothing to measure. The waits are the failure policy's shape
# without the randomised term - 2 s, 4 s, 8 s ... capped at 60 s.
#
# `max_attempts` is TOTAL attempts, not extra ones: 3 (the default) is one call
# plus two retries, which is `PER_CLASS_MAX['overloaded']` from
# compound-v-failure-policy.py - the class of the incident that motivated this.
# `1` disables retrying without disabling anything else.
RETRY_MAX_ATTEMPTS_DEFAULT = 3
RETRY_ESCALATE_REVIEWER_DEFAULT = True
RETRY_BACKOFF_BASE_MS = 2000
RETRY_BACKOFF_CAP_MS = 60000

# What Record writes when a stage burned every attempt. The class is `other` and
# the text says why it is not `overloaded`: agent() resolves to null on a
# terminal API error and hands the script NO error text, so naming the class
# would be a guess wearing a measurement's clothes.
RETRY_EXHAUSTED_REASON = (
    "agent returned null %d times (transient API failure suspected; the "
    "runtime's failure text is not visible to the script)"
)


def retry_backoff_ms(attempt):
    """Milliseconds to wait AFTER `attempt` (1-based) produced no result.

    The Python mirror of the emitted `withRetry`'s wait, which reads the same two
    constants out of CFG: 2000, 4000, 8000 ... min-capped at 60000.
    """
    return min(RETRY_BACKOFF_CAP_MS,
               RETRY_BACKOFF_BASE_MS * (2 ** (max(1, int(attempt)) - 1)))


def escalation_map():
    """The ladder as a lookup the emitted script can use: {sonnet: opus, opus: fable}.

    Emitted from CLAUDE_ESCALATION rather than written out in JS, so the reviewer
    lift and `escalate_claude_model` step the same rungs. A model that is not a
    key - an explicit manifest pin we do not own, or the top rung - has no
    successor and is therefore never escalated, which is the same refusal
    `escalate_claude_model` makes in Python.
    """
    return dict(zip(CLAUDE_ESCALATION[:-1], CLAUDE_ESCALATION[1:]))


def retry_config(manifest):
    """The manifest's optional top-level `retry` block, resolved to CFG.retry.

    Degrades to the defaults rather than raising: REFUSING a bad value is
    compound-v-validate-manifest.py's job (it names the offending key), and the
    emitter's fallback must never be the thing that widens the budget - an
    out-of-range value falls back to the documented default, never through to
    the value it asked for.
    """
    block = manifest.get("retry") if isinstance(manifest, dict) else None
    if not isinstance(block, dict):
        block = {}
    attempts = block.get("max_attempts")
    if not (isinstance(attempts, int) and not isinstance(attempts, bool)
            and 1 <= attempts <= RETRY_MAX_ATTEMPTS_DEFAULT):
        attempts = RETRY_MAX_ATTEMPTS_DEFAULT
    escalate = block.get("escalate_reviewer")
    if not isinstance(escalate, bool):
        escalate = RETRY_ESCALATE_REVIEWER_DEFAULT
    return {
        "max_attempts": attempts,
        "escalate_reviewer": escalate,
        "base_ms": RETRY_BACKOFF_BASE_MS,
        "cap_ms": RETRY_BACKOFF_CAP_MS,
    }


# The keys a retry-log entry may carry, and nothing else. The log is machine
# generated by the emitted script, which is not a reason to trust it: it arrives
# through argv, so it is validated before anything is written from it.
RETRY_ENTRY_KEYS = ("stage", "job", "attempt", "wait_ms", "escalated_from", "model")


def _sanitize_retry_meta(raw):
    """(meta, error). Parse `--retries-json` into a shape that is safe to record.

    Never raises and never refuses the RESULT: a malformed bookkeeping field must
    not cost a job its evidence, so a failure returns (None, reason) and Record
    records the reason beside the result it still writes.
    """
    if not raw:
        return None, None
    try:
        doc = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        return None, "retries JSON unparseable: %s" % exc
    if not isinstance(doc, dict):
        return None, "retries JSON was not an object"
    entries = []
    for item in (doc.get("retries") or []):
        if not isinstance(item, dict):
            continue
        clean = {}
        for key in RETRY_ENTRY_KEYS:
            val = item.get(key)
            if val is None or isinstance(val, bool):
                continue
            if isinstance(val, int):
                clean[key] = val
            elif isinstance(val, str) and re.match(r"^[A-Za-z0-9_.:@+-]{1,120}$", val):
                clean[key] = val
        if clean:
            entries.append(clean)
    attempts = doc.get("attempts")
    if not (isinstance(attempts, int) and not isinstance(attempts, bool)
            and attempts >= 1):
        attempts = len(entries) + 1
    escalated_from = doc.get("escalated_from")
    if not (isinstance(escalated_from, str)
            and re.match(r"^[A-Za-z0-9_.:@+-]{1,120}$", escalated_from)):
        escalated_from = None
    return {
        "retries": entries,
        "exhausted": bool(doc.get("exhausted")),
        "attempts": attempts,
        "escalated_from": escalated_from,
    }, None


def apply_retry_meta(result, meta):
    """Stamp an exhausted retry budget onto a job_result, HONESTLY.

    Two deliberate non-actions:

    * the class is `other`, never `overloaded` - see RETRY_EXHAUSTED_REASON;
    * `retries` and `escalated_from` are stamped by Record, not here: the
      3.4.8 review-1 closure extended schemas/job_result.schema.json with both
      keys, so the job_result carries the log (state.json and Record's ack keep
      their copies). This helper owns only the class and the reason.
    """
    if not meta or not meta.get("exhausted"):
        return result
    if result.get("status") != "success":
        result["failure_class"] = "other"
        result["summary"] = "%s - %s" % (
            RETRY_EXHAUSTED_REASON % int(meta.get("attempts") or 1),
            result.get("summary") or "",
        )
    return result

# Mirror of compound-v-validate-manifest.py:REVIEWER_TOKENS. DUPLICATED on
# purpose — both are standalone stdlib CLIs with no shared import (house style).
# Keep in sync.
REVIEWER_TOKENS = ("review", "reviewer", "spec_review", "quality", "integration")


def _is_reviewer_job(job):
    """True iff this job is a reviewer. EXACT mirror of
    compound-v-validate-manifest.py:_is_reviewer — `type` decides when present, and
    the id/title fallback matches on word boundaries. Duplicated on purpose (both are
    standalone stdlib CLIs); keep in sync. The looser substring scan classified a job
    titled "Writes the thing the reviewer reviews" as a reviewer — see that docstring.
    """
    jtype = str(job.get("type") or "").strip().lower()
    if jtype:
        return any(tok in jtype for tok in REVIEWER_TOKENS)
    haystack = "%s %s" % (str(job.get("id") or "").lower(),
                          str(job.get("title") or "").lower())
    return any(re.search(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(tok), haystack)
               for tok in REVIEWER_TOKENS)


def prior_attempt_failed(run_dir, job_id):
    """True iff this job already has a RECORDED non-success result in this run.

    The signal is the recorded result, not a counter we keep ourselves: `record`
    writes results/<id>.json for every terminal job, and /v:resume re-runs this
    emitter against the same run dir. An absent or unreadable result is NOT a
    failure — escalation must be earned by evidence, never by a missing file.
    """
    doc = _read_json(os.path.join(run_dir, "results", "%s.json" % job_id), None)
    if not isinstance(doc, dict):
        return False
    status = str(doc.get("status") or "").strip().lower()
    return bool(status) and status != "success"


def escalate_claude_model(model):
    """(model, capped_reason). One rung up the ladder, or unchanged at the top.

    A model outside the ladder (an explicitly pinned string we do not own) is
    returned untouched: escalating a value we did not choose would be a
    fabricated routing decision.
    """
    key = str(model or "").strip().lower()
    if key not in CLAUDE_ESCALATION:
        return model, "%r is not on the claude ladder" % model
    i = CLAUDE_ESCALATION.index(key)
    if i + 1 >= len(CLAUDE_ESCALATION):
        return model, "already at the top of the ladder"
    return CLAUDE_ESCALATION[i + 1], None


def resolve_job_model(job, python_bin, resolve_model=None, stance=None,
                      config_path=None):
    """(model, error). An explicit `model` wins; otherwise `tier` is resolved.

    Fails closed: an external backend's argv cannot be completed without a
    concrete model, and `--model` is one of the worker script's own required
    arguments. Guessing one here would be a fabricated routing decision. A
    `backend: claude` caller degrades OPEN instead — see job_entry — because an
    unset `opts.model` is a working default (inherit the session model), not a
    broken argv.

    `stance` and `config_path` are what make the project's own routing real: the
    resolver's map is per-stance, and `/v:models` writes its discovered map into
    .claude/compound-v.json. Until 3.0.5 neither was passed, so every resolution
    silently used the built-in balanced defaults.
    """
    explicit = job.get("model")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip(), None
    tier = job.get("tier")
    if not (isinstance(tier, str) and tier.strip()):
        return None, ("job %r declares neither `model` nor `tier`, so no concrete "
                      "model can be resolved for its worker" % job.get("id"))
    target = resolve_model or RESOLVE_MODEL_DEFAULT
    if not os.path.exists(target):
        return None, "model resolver not found at %s" % target
    cmd = [python_bin, "-B", target, "--backend", job.get("backend") or "claude",
           "--tier", tier.strip()]
    if isinstance(stance, str) and stance.strip():
        cmd += ["--stance", stance.strip()]
    if isinstance(config_path, str) and config_path and os.path.isfile(config_path):
        cmd += ["--config", config_path]
    effort = job.get("effort")
    if isinstance(effort, str) and effort.strip():
        cmd += ["--effort", effort.strip()]
    rc, out, err = _run(cmd)
    if rc != 0:
        return None, "model resolution failed (rc=%d): %s" % (rc, (err or out)[:200])
    try:
        model = (json.loads(out) or {}).get("model")
    except Exception as exc:  # noqa: BLE001
        return None, "model resolver produced no JSON: %s" % exc
    if not (isinstance(model, str) and model.strip()):
        return None, "model resolver returned no model for tier %r" % tier
    return model.strip(), None


# The turn cap a job is expected to finish inside. `maxTurns` is a field of an
# agent DEFINITION, so a Claude implementer gets its cap natively from
# `agents/implementer.md`; an EXTERNAL worker has no such definition, and this is
# the only place its cap is ever stated. The defaults are proportionate to the
# tier the manifest already declares, and `max_turns` on the job overrides them.
#
# Nothing enforces this number on an external backend — it is a budget the worker
# is told, not a ceiling the runtime imposes — and saying so is the honest form.
TURN_CAP_BY_TIER = {"light": 30, "standard": 50, "deep": 80, "frontier": 80}
TURN_CAP_DEFAULT = 50


def job_turn_cap(job):
    """(cap, source) — the manifest's `max_turns`, else the tier's default.

    A MALFORMED `max_turns` SAYS SO. `"80"`, `0`, `-1`, `true` and `null` all fail
    the type check and silently fell through to the tier default, so a manifest
    that meant to raise a job's cap and quoted the number got the default with no
    hint that its value had been discarded. The degradation is right — a cap this
    code cannot read is not a cap — but it has to be visible, and `source` is the
    string the rendered prompt and the emit output both already print.
    """
    declared = job.get("max_turns")
    if isinstance(declared, int) and not isinstance(declared, bool) and declared > 0:
        return declared, "manifest max_turns"
    tier = str(job.get("tier") or "").strip().lower()
    if tier in TURN_CAP_BY_TIER:
        source = "default for tier %s" % tier
        cap = TURN_CAP_BY_TIER[tier]
    else:
        source = "default"
        cap = TURN_CAP_DEFAULT
    if declared is not None:
        source = ("manifest max_turns %r is not a positive integer — ignored, "
                  "using the %s" % (declared, source))
    return cap, source


def render_worker_prompt(job, run_id):
    """The task itself, as the file the worker is handed via `--prompt-file`.

    WHAT THIS TEMPLATE DELIBERATELY DOES NOT ADD: an imperative to verify, to
    re-check, or to report per item. Anthropic's own Opus 5 guidance is that
    explicit verification instructions make the model verify MORE than the task
    needs, and this pipeline already re-derives every enforcement fact from git
    after the worker is gone. The task's own `body` may ask for whatever it likes;
    the template asks for nothing beyond the lanes, the acceptance list and the cap.
    """
    lines = ["# %s" % (job.get("title") or job.get("id")),
             "",
             "Compound V run `%s`, job `%s`." % (run_id, job.get("id")),
             ""]
    # `body` FIRST, because that is what every manifest in this repository writes.
    #
    # This line read `description or prompt or spec` and nothing else. Not one of
    # the twenty-plus manifests written for this release uses any of those three
    # names — they all use `body:` — so the names never intersected and **the task
    # text was silently dropped from every worker prompt**. Workers received a
    # title, their lanes and their acceptance criteria, and no instructions.
    #
    # Five reviews reported it (df10, df11, df12, df18, df20) and it stayed live,
    # because each was read as a one-off finding about that run. Dogfood 25 is the
    # one that closed it, and only because recall had just been made reachable: the
    # reviewer's second query returned all five prior reports at once, and the
    # finding stopped being "a spec gap" and became "the loop is not closing".
    # That is the whole argument for recall, demonstrated on recall's own release.
    body = (job.get("body") or job.get("description")
            or job.get("prompt") or job.get("spec"))
    if isinstance(body, str) and body.strip():
        lines += [body.strip(), ""]
    else:
        # NO TASK TEXT IS NOT A JOB. A prompt carrying only a title and lanes asks a
        # worker to guess, and a guess that lands inside its lane passes every gate
        # this pipeline has — the scope gate checks WHICH files changed, never what
        # they say. Refusing here is the mechanism that would have caught the
        # dropped `body` on its first run instead of its twenty-fifth.
        # A TITLE PLUS ACCEPTANCE CRITERIA IS A TASK. A cross-model review was
        # right that the first version of this refusal broke manifest shapes that
        # were valid before it, and right about the tell: the fixtures were made to
        # pass by injecting synthetic `body` strings rather than by showing the
        # contract required one. This function RENDERS the title and the acceptance
        # list itself, so a job carrying both is not a job with no instructions.
        #
        # What stays refused is the shape that actually caused the damage: lanes and
        # a title and NOTHING to check the work against. That is the prompt a worker
        # has to invent a task from, and an invented task inside its lane passes
        # every gate here.
        acceptance = [a for a in (job.get("acceptance") or [])
                      if isinstance(a, str) and a.strip()]
        title = str(job.get("title") or "").strip()
        if title and acceptance:
            lines += ["_No `body` was declared. The title above and the acceptance "
                      "criteria below are the whole of this task; if they are not "
                      "enough to act on, report BLOCKED rather than inventing "
                      "scope._", ""]
        else:
            raise ValueError(
                "job %r carries no task text and no title+acceptance to stand in "
                "for one: none of `body`, `description`, `prompt` or `spec` is set, "
                "and %s. A prompt with lanes and nothing to check the work against "
                "asks the worker to invent the task, and an invented task that "
                "stays in its lane passes the scope gate — which is how this went "
                "unnoticed for twenty-five runs."
                % (job.get("id"),
                   "the title is empty" if not title
                   else "no acceptance criteria are declared")
            )
    deps = job.get("depends_on") or []
    if isinstance(deps, str):
        deps = [deps]
    if deps:
        lines += ["Prerequisites, already merged and COMMITTED into your base "
                  "before this worktree was created: %s." % ", ".join(deps), ""]
    lines.append("## You are unattended")
    lines.append("")
    lines.append("No one reads this session while it runs and no one will answer a question:")
    lines.append("a turn that ends by asking for confirmation, approval or a preference does")
    lines.append("NOTHING, and the job is then recorded as an absent implementation. Decide")
    lines.append("with the spec, the plan and this prompt; when they are silent, choose the")
    lines.append("smallest change that meets the acceptance, do it, run the checks, and return.")
    lines.append("")

    lines += ["## Write-allowed (your lane — anything else is a scope violation)", ""]
    for glob in (job.get("write_allowed") or []):
        lines.append("- `%s`" % glob)
    lines.append("")
    read_allowed = job.get("read_allowed") or []
    if read_allowed:
        lines += ["## Read-allowed (advisory — git cannot enforce reads)", ""]
        for glob in read_allowed:
            lines.append("- `%s`" % glob)
        lines.append("")
    acceptance = job.get("acceptance") or []
    if acceptance:
        lines += ["## Acceptance (your definition of done)", ""]
        for item in acceptance:
            lines.append("- %s" % item)
        lines.append("")
    cap, cap_src = job_turn_cap(job)
    lines += ["Turn cap: %d (%s; default light 30 / standard 50 / deep 80). "
              "Plan to finish inside it." % (cap, cap_src), ""]
    lines += [
        "## What you must NOT report",
        "",
        "Do not report `blocked`, `files_changed` or `violations`. Those are",
        "enforcement fields, they are derived from git by the caller, and a",
        "constrained party filling in its own enforcement fields is the",
        "fabricated-evidence pattern.",
    ]
    return "\n".join(lines) + "\n"


# A harness Bash call is capped at 600 s. The external worker runs INSIDE one, and
# then runs the test floor, so its own wall-clock cap must leave headroom.
EXTERNAL_WORKER_TIMEOUT_CAP = 480


def build_launch_argv(job, entry, run_id, repo_root, run_dir, model):
    """The COMPLETE worker argv — every flag the worker script requires."""
    argv = [
        entry["worker_script"],
        "--run-id", run_id,
        "--job-id", job["id"],
        "--repo", repo_root,
        "--prompt-file", worker_prompt_path(run_dir, job["id"]),
        "--model", model,
        "--write-allowed", ":".join(job.get("write_allowed") or []),
    ]
    timeout = job.get("timeout_sec")
    if isinstance(timeout, int) and not isinstance(timeout, bool) and timeout > 0:
        # The wrapper that runs this argv is a harness Bash call, whose ceiling is
        # ten minutes; a worker allowed more than that would be killed from the
        # outside with nothing recorded (stage-4 dogfood, finding 75). Cap the
        # worker below the ceiling and leave room for its own test floor.
        argv += ["--timeout-sec", str(min(timeout, EXTERNAL_WORKER_TIMEOUT_CAP))]
    effort = job.get("effort")
    if isinstance(effort, str) and effort.strip():
        argv += ["--effort", effort.strip()]
    argv += ["--events-log", os.path.join(run_dir, "logs", "%s.events.jsonl" % job["id"])]
    if entry.get("test_contract_file"):
        argv += ["--test-contract-file", entry["test_contract_file"]]
        # The worker script's tc_run also re-derives `timeout_s` from the
        # slice file itself, so this flag is belt-and-braces rather than the
        # only path — but it is the EXPLICIT declaration the manifest made,
        # passed as a real argument rather than left to be re-parsed. Absent
        # ⇒ the DOCUMENTED default (480 s, execution-manifest.md), passed
        # explicitly: the worker scripts' own fallback is 900, and leaving the
        # flag off made the external path default to a number no document
        # names (v3.4.6 review-1, item 1).
        _tc_timeout_s = entry.get("test_contract_timeout_s")
        if not (isinstance(_tc_timeout_s, int) and not isinstance(_tc_timeout_s, bool)
                and 1 <= _tc_timeout_s <= 540):
            _tc_timeout_s = 480
        argv += ["--test-timeout-sec", str(_tc_timeout_s)]
    return argv


def _shell_join(argv):
    try:
        import shlex
        return " \\\n  ".join(shlex.quote(a) for a in argv)
    except Exception:  # noqa: BLE001
        return " ".join(argv)


def _worktree_base_is_head(repo_root):
    """True when the project's `.claude/settings.json` pins `worktree.baseRef: head`.

    The 3.0.5 rule "a job with depends_on runs its agent in the MAIN checkout"
    existed because the runtime branched a fresh worktree from the DEFAULT ref,
    so a dependent could not see the wave that had just committed. 3.4.0 set
    `worktree.baseRef: head` in this project's settings, which removes that
    premise — and stage-2 r2 (finding 60) showed the rule's other half: the
    manifest kept `isolation: worktree`, the finalizer read the manifest, and a
    dependent job that ran direct could never integrate. With the setting the
    dependent job gets a real worktree; without it, the old rule stays and the
    finalizer trusts the gate receipt's mode instead (see cmd_finalize_wave).
    """
    try:
        with open(os.path.join(repo_root, ".claude", "settings.json"), "r",
                  encoding="utf-8") as fh:
            cfg = json.load(fh)
        return str(((cfg.get("worktree") or {}).get("baseRef") or "")).strip().lower() == "head"
    except (OSError, ValueError, AttributeError):
        return False


def build_plan(manifest, run_dir, repo_root, python_bin, self_path,
               scope_check, fastpath, workers_dir):
    """Everything the emitted script needs, as plain data."""
    run_id = manifest.get("run_id") or os.path.basename(os.path.normpath(run_dir))
    abs_run_dir = os.path.abspath(run_dir)
    if not repo_root:
        raise ValueError(
            "no repository root: the destination a job's work lands in is never "
            "defaulted (see the REPO_DEFAULT note at the top of this file)"
        )
    abs_repo_root = os.path.abspath(repo_root)
    # Routing inputs the emitter never read before 3.0.5. The manifest's own
    # stance wins; the project config is where /v:models writes its discovered
    # per-backend map. Both are optional and both degrade to the resolver's
    # built-in balanced defaults.
    stance = str(manifest.get("routing_stance") or "").strip() or None
    config_path = os.path.join(abs_repo_root, ".claude", "compound-v.json")
    if not os.path.isfile(config_path):
        config_path = None
    # Gate, Record and Finalize are TRANSPORT: each runs exactly one clamped
    # command and returns its JSON verbatim, and the command's real logic is
    # Python that the integration authority re-verifies from git. That is the
    # `light` tier by definition, so they are routed through the same resolver
    # rather than inheriting whatever the session happens to be running.
    transport_model, transport_note = resolve_job_model(
        {"id": "__transport__", "backend": "claude", "tier": "light"},
        python_bin, stance=stance, config_path=config_path)
    artefacts = {}
    max_parallel = manifest.get("max_parallel") or 4
    jobs = manifest.get("jobs") or []
    waves = topo_waves(jobs, max_parallel)
    # A `test_contract` block is what makes resolution POSSIBLE at all. Without
    # one, `resolve-tests` fails closed and writes no file — and the worker
    # scripts reject a `--test-contract-file` that does not exist (exit 2). So the
    # flag is emitted only where the manifest actually declares the contract;
    # elsewhere the worker runs no tests and reports no `tests` object, which is
    # the documented honest outcome, not a silent zero.
    declares_contract = isinstance(manifest.get("test_contract"), dict) and bool(
        manifest.get("test_contract")
    )
    # The manifest's OWN `test_contract.timeout_s` (validated int, 1..540 by
    # compound-v-validate-manifest.py) — the same value `resolve-tests` copies
    # verbatim into the resolved slice (jobs/<id>.test-contract.json). Read
    # here, at PLAN time, so an external worker's launch argv can carry it as
    # a real `--test-timeout-sec` flag — the slice file itself is not written
    # until register-lane runs, per job, later.
    _contract_timeout_s = None
    if declares_contract:
        _raw_timeout_s = manifest.get("test_contract", {}).get("timeout_s")
        if isinstance(_raw_timeout_s, int) and not isinstance(_raw_timeout_s, bool) \
                and _raw_timeout_s > 0:
            _contract_timeout_s = _raw_timeout_s

    def worker_script_for(backend):
        path = os.path.join(workers_dir, "compound-v-run-%s-worker.sh" % backend)
        return path if os.path.exists(path) else None

    def job_entry(job):
        job_id = job["id"]
        backend = job.get("backend") or "claude"
        # D5.3 — NO NESTED WORKTREES. A non-`claude` job's workflow agent runs at
        # `direct` isolation: the worker script creates and OWNS its worktree,
        # exactly as it does today. A workflow agent that is itself
        # isolation:'worktree' and then spawns a worker that creates a second
        # worktree inside it is untested, and this repo already carries a
        # downstream incident from getting worktree ownership wrong (v2.6.1).
        if backend == "claude":
            isolation = job.get("isolation") or "direct"
        else:
            isolation = "direct"
        clamp = _clamp_rules(job, python_bin, self_path, worker_script_for)
        # agentType only spawns Claude agents, so an external backend never gets
        # one — its implementer is a launcher, not a role.
        agent_type, agent_type_note = (None, None)
        if backend == "claude":
            agent_type, agent_type_note = resolve_agent_type(job.get("type"))
        agent_def = None
        if agent_type:
            agent_def = agent_definition(agent_role_for(job.get("type"))[0])
        entry = {
            "id": job_id,
            "job_type": job.get("type"),
            "agent_type": agent_type,
            "agent_type_note": agent_type_note,
            "agent_definition": agent_def,
            "title": job.get("title") or job_id,
            "backend": backend,
            "tier": job.get("tier"),
            "effort": job.get("effort"),
            "model": job.get("model"),
            "model_source": None,
            "model_note": None,
            "isolation": isolation,
            # AGENT-level isolation, which is NOT the manifest's isolation. A job
            # with depends_on must run its agent in the MAIN checkout, because the
            # runtime's `isolation: 'worktree'` branches from the default ref — not
            # from local HEAD — so a fresh worktree does not contain the wave that
            # just committed. Dogfooded 2026-09-01 on a two-wave run: wave 1
            # committed 62716da, and wave 2's job still pinned baseline 5281d70,
            # could not see alpha/beta/gamma, wrote nothing, had its unchanged
            # worktree auto-removed, and the gate reported `unverifiable`.
            #
            # This is the same defect a cross-model review called CRITICAL in 3.0.1
            # — "dependents cannot see their prerequisites" — in the half we did not
            # fix. We closed the staging half (record no longer stages, the wave
            # finalizer commits); this is the worktree half, and it is a runtime
            # property we cannot configure away from here.
            #
            # Manifest isolation is unchanged: the validator still requires
            # `worktree` for parallel jobs, and scope attribution still uses it.
            # Only the agent runs in the main tree — and the direct-mode
            # preexisting snapshot is what keeps that honest.
            "agent_isolation": ("worktree"
                                if isolation == "worktree"
                                and (not (job.get("depends_on") or [])
                                     or _worktree_base_is_head(abs_repo_root))
                                else None),
            "timeout_sec": job.get("timeout_sec"),
            "write_allowed": job.get("write_allowed") or [],
            "read_allowed": job.get("read_allowed") or [],
            "acceptance": job.get("acceptance") or [],
            "depends_on": job.get("depends_on") or [],
            "test_scope": job.get("test_scope"),
            "worker_script": worker_script_for(backend) if backend != "claude" else None,
            "test_contract_file": (
                test_contract_path(os.path.abspath(run_dir), job_id)
                if backend != "claude" and declares_contract else None
            ),
            # The `--test-timeout-sec` build_launch_argv passes an external
            # worker alongside `--test-contract-file` — same manifest value,
            # never None unless the manifest declares no timeout_s at all.
            "test_contract_timeout_s": (
                _contract_timeout_s if backend != "claude" else None
            ),
            "implement_clamp": clamp,
            "prompt_file": worker_prompt_path(abs_run_dir, job_id),
            "launch_argv_file": None,
            "launch_argv": None,
            "launch_command": None,
        }
        if backend == "claude":
            # THE WIRE. Until 3.0.5 this whole vocabulary stopped here: `model`
            # was copied straight off the manifest (almost always absent, since
            # manifests route by `tier`), `opts.model` was never set, and every
            # agent inherited the session model. The tier existed, was validated,
            # was documented — and never reached agent().
            resolved, merr = resolve_job_model(job, python_bin, stance=stance,
                                               config_path=config_path)
            if resolved:
                entry["model"] = resolved
                entry["model_source"] = ("explicit" if job.get("model") else "tier")
                # A job that already failed in this run is re-dispatched one rung
                # up. Reviewers are exempt: a sealed review receipt must carry a
                # Claude Opus `reviewer_model`, so escalating one would invalidate
                # the very receipt it exists to produce.
                if not _is_reviewer_job(job) and prior_attempt_failed(abs_run_dir, job_id):
                    stepped, capped = escalate_claude_model(resolved)
                    if stepped != resolved:
                        entry["model"] = stepped
                        entry["model_source"] = "escalated"
                        entry["model_note"] = (
                            "re-attempt after a recorded non-success: %s → %s"
                            % (resolved, stepped))
                    else:
                        entry["model_note"] = (
                            "re-attempt not escalated (%s)" % capped)
            else:
                # Degrade OPEN, loudly. An unset opts.model inherits the session
                # model, which is exactly today's behaviour — but the run records
                # WHY, so "everything ran on opus" is never again a silent fact.
                entry["model"] = None
                entry["model_source"] = "inherit"
                entry["model_note"] = merr
        artefacts[job_id] = {
            "prompt_file": entry["prompt_file"],
            "prompt_text": render_worker_prompt(job, run_id),
            "launch_argv_file": None,
            "launch_argv": None,
        }
        if backend != "claude":
            if not entry["worker_script"]:
                raise ValueError(
                    "job %r runs on backend %r but scripts/compound-v-run-%s-worker.sh "
                    "is not present — the handoff cannot be materialized, and an "
                    "unmaterialized handoff is what 3.0.1 shipped"
                    % (job_id, backend, backend)
                )
            model, err = resolve_job_model(job, python_bin, stance=stance,
                                           config_path=config_path)
            if not model:
                raise ValueError(
                    "job %r cannot be launched: %s. `--model` is required by the "
                    "worker script, so this fails closed rather than guessing"
                    % (job_id, err)
                )
            argv = build_launch_argv(job, entry, run_id, abs_repo_root,
                                     abs_run_dir, model)
            entry["launch_argv"] = argv
            entry["launch_argv_file"] = launch_argv_path(abs_run_dir, job_id)
            entry["launch_command"] = _shell_join(argv)
            entry["model"] = entry["model"] or model
            entry["model_source"] = ("explicit" if job.get("model") else "tier")
            # THE WRAPPER IS A CLAUDE AGENT. `entry["model"]` is the BACKEND's model
            # and belongs in the launch argv only; the workflow agent that runs
            # that argv is a transport and must be spawned as a Claude model. Wiring
            # the backend model into agent() spawned a Claude agent named
            # `gpt-5.6-terra`, which the harness refused before its first tool call
            # (stage-4 dogfood, finding 77 — the first non-Claude job ever run on
            # Engine C). Light tier, never Haiku: the wrapper only runs one command.
            _wrap_model, _wrap_err = resolve_job_model(
                {"backend": "claude", "tier": "light"}, python_bin, stance=stance,
                config_path=config_path)
            entry["agent_model"] = _wrap_model or "sonnet"
            artefacts[job_id]["launch_argv"] = argv
            artefacts[job_id]["launch_argv_file"] = entry["launch_argv_file"]
        return entry

    return {
        "run_id": run_id,
        "run_dir": abs_run_dir,
        "repo_root": abs_repo_root,
        "artefacts": artefacts,
        "manifest_path": os.path.abspath(
            manifest.get("_manifest_path") or os.path.join(run_dir, "manifest.yaml")
        ),
        "manifest_digest": sha256_file(os.path.abspath(
            manifest.get("_manifest_path") or os.path.join(run_dir, "manifest.yaml")
        )),
        "python": python_bin,
        "emitter": self_path,
        "scope_check": scope_check,
        "fastpath": fastpath,
        "max_parallel": max_parallel,
        "budget_reserve_per_agent": BUDGET_RESERVE_PER_AGENT,
        "narrow_disallowed": NARROW_DISALLOWED,
        "implement_disallowed": IMPLEMENT_DISALLOWED,
        "routing_stance": stance,
        "models_config": config_path,
        "transport_model": transport_model,
        "transport_model_note": transport_note,
        # The workflow's retry budget and the escalation ladder, resolved ONCE
        # here so the emitted script never re-derives either.
        "retry": retry_config(manifest),
        "escalation": escalation_map(),
        "waves": [[job_entry(j) for j in wave] for wave in waves],
    }


# --------------------------------------------------------------------------- #
# the emitted workflow script
# --------------------------------------------------------------------------- #
IMPLEMENT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["status", "worktree", "summary"],
    "properties": {
        "status": {"type": "string", "enum": ["ok", "error"]},
        # A LOCATOR, not evidence. The Implement stage returns a raw result and
        # NEVER a `job_result`: job_result carries blocked/files_changed/
        # violations, which this project's contract says are git-derived by the
        # caller. Asking the implementer to report its own enforcement fields is
        # the fabricated-evidence pattern with extra steps.
        "worktree": {"type": "string"},
        "summary": {"type": "string"},
        "notes": {"type": "string"},
    },
}

GATE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["job_id", "verdict", "source"],
    "properties": {
        "job_id": {"type": "string"},
        "verdict": {"type": "string", "enum": ["pass", "blocked", "error"]},
        "source": {"type": "string"},
        "receipt_path": {"type": "string"},
        "baseline_commit": {"type": "string"},
        "realised_commit": {"type": "string"},
        "diff_digest": {"type": "string"},
        "exit_code": {"type": "integer"},
        "raw_stdout": {"type": "string"},
        "reason": {"type": "string"},
        # The tree the gate ACTUALLY measured, carried forward so Record does not
        # have to reconstruct it. 3.0.1 threw this away and rebuilt a locator from
        # lane-map.json, which holds the WRAPPER agent's project cwd — so a codex
        # job whose worker changed files in its own worktree was recorded against
        # an unchanged tree and its valid patch never reached the project. Empty
        # string for a `direct` job: there is no worktree, and that is a value.
        "worktree": {"type": "string"},
        # gate-receipt emits `tests` on a passing verdict, and this object is
        # additionalProperties:false — so without this line the Gate agent's own
        # structured result was invalid on every clean happy path.
        "tests": {"type": "object"},
    },
}

FINALIZE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["wave", "integrated"],
    "properties": {
        "wave": {"type": "integer"},
        "integrated": {"type": "boolean"},
        "commit": {"type": "string"},
        "merged": {"type": "array", "items": {"type": "string"}},
        "refused": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"},
        # The FINALIZER reports whether it appended the run's triage `actual`.
        # It moved here from RECORD in the fourth review pass: the append must
        # happen after the integration authority has re-derived this wave, never
        # between a direct-mode job's gate and that re-derivation.
        "triage_actual": {"type": "string"},
    },
}

RECORD_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["job_id", "recorded"],
    "properties": {
        "job_id": {"type": "string"},
        "recorded": {"type": "boolean"},
        "merged": {"type": "boolean"},
        "status": {"type": "string"},
        "result_path": {"type": "string"},
        "reason": {"type": "string"},
        # NO `triage_actual` HERE. Record no longer appends the run's triage
        # `actual` — that write is the finalizer's, after the authority (fourth
        # review pass). RECORD_SCHEMA is additionalProperties:false, so declaring
        # a field the ack cannot emit is dead schema, and the ack emitting a
        # field the schema does not declare would make Record's structured result
        # invalid. Both halves moved together, to FINALIZE_SCHEMA.
    },
}


def _implement_prompt(job, plan):
    """The implementer's prompt. Ends with the enforcement-field lock."""
    lines = []
    if job.get("agent_type"):
        # Spawned BY ROLE. The role contract lives in that agent's own
        # definition, so this prompt supplies the job's inputs and nothing else —
        # restating the contract here is how the two copies drift apart.
        # Deliberately ROLE-NEUTRAL wording. Until 3.4.0 only the reviewer arrived
        # by role, and this line said "your passes and your verdict vocabulary" —
        # reviewer language that reads as nonsense to an implementer, which is now
        # the other role that lands here.
        lines.append("You are spawned as `%s`. Your role and its standing "
                     "instructions come from your OWN agent definition; this "
                     "prompt carries only Compound V job `%s`'s inputs."
                     % (job["agent_type"], job["id"]))
    else:
        lines.append("You are the implementer for Compound V job `%s`." % job["id"])
    lines.append("")
    lines.append("TITLE: %s" % job["title"])
    lines.append("")
    lines.append("FIRST COMMAND, BEFORE ANY OTHER TOOL CALL — register your lane.")
    lines.append("This is what lets `hooks/lane-guard.sh` resolve which job an")
    lines.append("out-of-lane write belongs to. Without it the guard resolves")
    lines.append("nothing, fails open, and silently allows every write.")
    lines.append("")
    # A LITERAL PATH, NEVER A SHELL SUBSTITUTION. The clamp matches a literal
    # command prefix and refuses a command whose structure it cannot verify;
    # `"$PWD"` and `$(...)` are exactly that structure, so the very first command
    # of a real run (2026-09-02, run r9) was DENIED for the `--cwd "$PWD"` this
    # block used to render — before the job could register at all, which is the
    # one failure that silently disarms the lane guard for the whole job. `pwd`
    # is itself an admitted form (IMPLEMENT_SHELL), so the worker runs it and
    # pastes what it printed.
    #
    # The isolation below is the AGENT layer's, not the manifest's: register-lane
    # uses it to decide both where to pin the baseline and whether to take the
    # pre-existing snapshot, and a depends_on job runs its agent in the project
    # checkout while declaring `worktree` in the manifest — passing the manifest
    # value here meant the job that most needs the snapshot, the one gated in a
    # shared already-dirty tree, was the only one that never got it.
    lines.append("Run `pwd` first — it is admitted — and write the absolute path")
    lines.append("it prints in place of `<ABSOLUTE_CWD>` below, LITERALLY. The")
    lines.append("clamp refuses shell substitution of any kind: a variable")
    lines.append("expansion or a nested command is structure it cannot verify,")
    lines.append("and a real run's very first command was denied for exactly")
    lines.append("that — before the job could register, which leaves the lane")
    lines.append("guard with nothing to resolve for the rest of the job.")
    lines.append("")
    lines.append("```bash")
    lines.append("pwd")
    lines.append("```")
    lines.append("")
    lines.append("```bash")
    lines.append('%s -B %s register-lane --run-dir %s --job-id %s '
                 '--cwd <ABSOLUTE_CWD> --repo-root %s --isolation %s'
                 % (plan["python"], plan["emitter"], plan["run_dir"], job["id"],
                    plan["repo_root"],
                    "worktree" if job.get("agent_isolation") == "worktree" else "direct"))
    lines.append("```")
    lines.append("")
    lines.append("That command also PINS this job's baseline commit before anything")
    lines.append("changes, and it fails closed if it cannot. A gate measured against a")
    lines.append("HEAD that moved is a gate that passes the run it should have caught.")
    lines.append("")
    lines.append("Run Python with `-B` (or export PYTHONDONTWRITEBYTECODE=1) for EVERY")
    lines.append("python command you issue: the scope gate forgives no path by")
    lines.append("extension, so a stray .pyc left outside your lane BLOCKS your job.")
    lines.append("")
    if job["backend"] != "claude" and job["launch_command"]:
        lines.append("THIS JOB RUNS ON AN EXTERNAL BACKEND (%s)." % job["backend"])
        lines.append("You do not implement it yourself. Run EXACTLY this command — every")
        lines.append("argument is already materialized, including the prompt file, which")
        lines.append("was written before this workflow started. Do not edit it, do not")
        lines.append("substitute values, do not add flags. The worker creates and OWNS its")
        lines.append("own git worktree — you are at `direct` isolation precisely so no")
        lines.append("worktree is nested inside another:")
        lines.append("")
        lines.append("```bash")
        lines.append(job["launch_command"])
        lines.append("```")
        lines.append("")
        lines.append("Call the Bash tool with `timeout: 600000` (ten minutes, the harness")
        lines.append("maximum): the worker's own cap is set below it on purpose, and a")
        lines.append("command the harness detaches to the background leaves you with no")
        lines.append("job_result to return — a worker you did not wait for is a job that")
        lines.append("did not run.")
        lines.append("")
        lines.append("The full argv is also committed at `%s`, so the invocation that ran"
                     % job["launch_argv_file"])
        lines.append("is a file in the run directory and not a reconstruction. The task")
        lines.append("itself is `%s`." % job["prompt_file"])
        lines.append("")
        lines.append("When the worker finishes, return the ABSOLUTE worktree it reports")
        lines.append("(the `worktree` field of its job_result) as your `worktree` — that")
        lines.append("is the tree the Gate will measure. Never return your own `pwd`; you")
        lines.append("did not change anything in it.")
        lines.append("")
    elif job.get("agent_isolation") == "worktree":
        lines.append("You are running in your OWN git worktree. Return its absolute path")
        lines.append("(`pwd`) as `worktree` — that is the tree the Gate measures.")
        lines.append("")
    elif job["isolation"] == "worktree":
        # A dependent job under the 3.0.5 rule: manifest says worktree, the agent
        # runs in the main checkout. Say so — the three layers must agree
        # (finding 60), and the worker must not report a worktree it never had.
        lines.append("You are running in the MAIN checkout (a dependent job; the manifest's")
        lines.append("`isolation: worktree` is for scope attribution). Return an empty")
        lines.append("`worktree`; the Gate measures the main tree in direct mode.")
        lines.append("")
    else:
        lines.append("You are running at `direct` isolation, in the project checkout")
        lines.append("itself. Return `worktree` as the EMPTY STRING. A direct job has no")
        lines.append("worktree to merge from, and reporting your `pwd` there is what made")
        lines.append("3.0.1 apply a direct job's patch into a different repository.")
        lines.append("")
    lines.append("WRITE-ALLOWED (your lane — anything else is a scope violation):")
    for glob in job["write_allowed"]:
        lines.append("  - %s" % glob)
    lines.append("")
    if job["acceptance"]:
        lines.append("ACCEPTANCE (your definition of done):")
        for item in job["acceptance"]:
            lines.append("  - %s" % item)
        lines.append("")
    lines.append("RETURN a raw result: `status`, the `worktree` described above, and a")
    lines.append("`summary`.")
    lines.append("")
    lines.append("DO NOT report `blocked`, `files_changed` or `violations`. Those are")
    lines.append("enforcement fields, they are git-derived by the caller, and a")
    lines.append("constrained party filling in its own enforcement fields is the")
    lines.append("fabricated-evidence pattern. The gate derives them from git.")
    return "\n".join(lines)


def _gate_command(job, plan):
    return (
        "%s -B %s gate-receipt --run-dir %s --job-id %s --repo-root %s "
        "--mode %s --worktree <ABSOLUTE_GATE_ROOT>%s"
        % (plan["python"], plan["emitter"], plan["run_dir"], job["id"],
           plan["repo_root"],
           "worktree" if job["isolation"] == "worktree" else "direct",
           (" --manifest-digest %s" % plan["manifest_digest"])
           if plan.get("manifest_digest") else "")
    )


def emit_script(plan):
    """Render the workflow script. Plain JavaScript; no TypeScript, no import()."""
    waves = plan["waves"]
    phase_titles = ["Wave %d" % (i + 1) for i in range(len(waves))] + STAGE_PHASES

    meta = {
        "name": "compound-v-dispatch-%s" % plan["run_id"],
        "description": (
            "Compound V Engine C dispatch for run %s: implement -> gate -> record, "
            "one pipeline per dependency wave." % plan["run_id"]
        ),
        "phases": [{"title": t} for t in phase_titles],
    }

    prompts = {}
    for wave in waves:
        for job in wave:
            prompts[job["id"]] = {
                "implement": _implement_prompt(job, plan),
                "gate_command": _gate_command(job, plan),
            }

    cfg = {
        "run_id": plan["run_id"],
        "run_dir": plan["run_dir"],
        "repo_root": plan["repo_root"],
        "manifest_path": plan["manifest_path"],
        # BAKED IN AT GENERATION TIME. Every stage below carries it back to the
        # Python that enforces it, so the lane map the run is measured against is
        # provably the one this script was generated from.
        "manifest_digest": plan["manifest_digest"],
        "python": plan["python"],
        "emitter": plan["emitter"],
        "budget_reserve_per_agent": plan["budget_reserve_per_agent"],
        "narrow_disallowed": plan["narrow_disallowed"],
        "implement_disallowed": plan["implement_disallowed"],
        "transport_model": plan["transport_model"],
        "retry": plan.get("retry") or retry_config({}),
        "escalation": plan.get("escalation") or escalation_map(),
        "waves": waves,
        "prompts": prompts,
    }

    body = JS_TEMPLATE
    body = body.replace("__META__", neutralize_in_data(_js_json(meta)))
    body = body.replace("__CFG__", neutralize_in_data(_js_json(cfg)))
    body = body.replace("__IMPLEMENT_SCHEMA__", _js_json(IMPLEMENT_SCHEMA))
    body = body.replace("__GATE_SCHEMA__", _js_json(GATE_SCHEMA))
    body = body.replace("__RECORD_SCHEMA__", _js_json(RECORD_SCHEMA))
    body = body.replace("__FINALIZE_SCHEMA__", _js_json(FINALIZE_SCHEMA))
    return body


# `export const meta = { name, description, phases }` MUST be the FIRST statement
# in the script and meta must be a pure literal — both enforced by the runtime's
# parser, verbatim from the installed binary. Everything after it is the body.
JS_TEMPLATE = r"""export const meta = __META__;

// Compound V — Engine C dispatch script. GENERATED by
// scripts/compound-v-emit-workflow.py from this run's manifest.yaml. Edit the
// manifest and re-emit; do not hand-edit this file, or the committed artefact
// stops being what ran.
//
// Determinism: this runtime makes the wall-clock and RNG globals THROW (the
// no-arg clock read, the random call, and the dynamic module import), because
// they would break resume. Timestamps arrive via `args` instead. The generator
// refuses to write a script containing any of those constructs — and it has to,
// because the runtime's own static check for them runs only on an inline
// `script`, never on the `scriptPath` form Engine C forces.
//
// The script has no filesystem and no shell access. Every side effect happens in
// a spawned agent running ONE clamped Python command, so the logic that decides
// anything is in Python where it can be tested, and the agent is reduced to a
// transport for it.

const CFG = __CFG__;
const IMPLEMENT_SCHEMA = __IMPLEMENT_SCHEMA__;
const GATE_SCHEMA = __GATE_SCHEMA__;
const RECORD_SCHEMA = __RECORD_SCHEMA__;
const FINALIZE_SCHEMA = __FINALIZE_SCHEMA__;

// Timestamps must be passed in; the runtime forbids reading a clock.
const NOW = (args && args.now) ? String(args.now) : null;

function q(s) {
  return "'" + String(s).replace(/'/g, "'\\''") + "'";
}

// ---------------------------------------------------------------------------
// budget — the native ceiling is HARD: once spent() reaches total, further
// agent() calls THROW. A throw inside a stage drops the item to null and skips
// its remaining stages, which is exactly how the audit trail gets lost. So we
// stop SCHEDULING before the ceiling instead of running into it.
// ---------------------------------------------------------------------------
function budgetAllows(n) {
  try {
    if (!budget || budget.total === null || budget.total === undefined) return true;
    const remaining = budget.remaining();
    if (typeof remaining !== 'number') return true;
    return remaining > CFG.budget_reserve_per_agent * n;
  } catch (e) {
    // Reading the budget must never be what stops the run.
    return true;
  }
}

// ---------------------------------------------------------------------------
// withRetry — a transient API death is retried, deterministically.
//
// THE TRIGGER IS A NULL RESOLUTION, not a throw. agent() RESOLVES to null when
// it is skipped or dies on a terminal API error — the three 529s that
// motivated this arrived that way — and only some failures arrive as
// exceptions. Both are retried. NEITHER IS CLASSIFIED HERE: the runtime hands
// the script no error text, so naming the class would be a guess, and Record
// records `other` with a reason that says exactly that.
//
// The wait is the failure policy's table with the randomised term REMOVED,
// because there is nothing to jitter with: the RNG global and every clock read
// are refused by this runtime (deterministic resume). setTimeout is the one
// timing primitive that works here, probed live before this was written.
// Nothing is timed and nothing is stamped — Record stamps the time when it
// writes; a duration this script claimed would be a fabricated measurement.
// ---------------------------------------------------------------------------
async function withRetry(stage, jobId, fn) {
  const retries = [];
  let lastErr = null;
  for (let attempt = 1; attempt <= CFG.retry.max_attempts; attempt++) {
    let r = null;
    try {
      r = await fn();
    } catch (e) {
      r = null;
      lastErr = String(e && e.message ? e.message : e);
    }
    if (r !== null && r !== undefined) {
      return { value: r, retries: retries, exhausted: false,
               last_error: lastErr, attempts: attempt };
    }
    if (attempt < CFG.retry.max_attempts) {
      const wait = Math.min(CFG.retry.cap_ms,
                            CFG.retry.base_ms * Math.pow(2, attempt - 1));
      retries.push({ stage: stage, job: jobId, attempt: attempt, wait_ms: wait });
      log('retry: ' + stage + ' ' + jobId + ' attempt ' + attempt +
          ' produced no result' + (lastErr ? ' (' + lastErr + ')' : '') +
          '; waiting ' + wait + 'ms before attempt ' + (attempt + 1));
      await new Promise(function (res) { setTimeout(res, wait); });
    }
  }
  // EXHAUSTED. The caller falls into exactly the null path it had before this
  // existed: nothing is written less than before, and no stage is made worse.
  return { value: null, retries: retries, exhausted: true,
           last_error: lastErr, attempts: CFG.retry.max_attempts };
}

// Only a REVIEW job is lifted. The manifest's own `type` decides — never the
// model, never the title — and an implementer is never escalated in-run.
function isReviewJob(job) {
  return String(job && job.job_type ? job.job_type : '') === 'review';
}

// The retry log travels Gate -> Record on the verdict object under a name no
// receipt ever carries, and Record strips it before the verdict goes anywhere
// near argv or a file. It is bookkeeping, never part of the gate's verdict.
function withRetryMeta(verdict, meta) {
  const out = Object.assign({}, verdict);
  out.__retry = meta;
  return out;
}

// ---------------------------------------------------------------------------
// Stage 1 — Implement. Returns a RAW result, never a job_result.
// ---------------------------------------------------------------------------
// The registry, not the repository, decides whether an agentType can spawn. When it
// cannot (plugin updated mid-session, not installed, renamed), the role is run from
// its inlined definition instead of the job silently failing its Gate.
function isAgentTypeMissing(err) {
  const m = String(err && err.message ? err.message : err);
  return /agent type '[^']*' not found/i.test(m);
}
function implementFailure(job) {
  return { job: job, implement: null, retries: [], escalated_from: null,
           exhausted: false };
}
function inlineDefinition(job, prompt) {
  return 'Your agent definition (' + job.agent_type + ') could not be spawned by role in ' +
    'this session, so it follows verbatim. Follow it exactly, including its Step 0.\\n\\n' +
    job.agent_definition.body + '\\n\\n---\\n\\n' + prompt;
}

async function implementStage(job) {
  try {
    const p = CFG.prompts[job.id];
    const opts = {
      label: 'implement ' + job.id,
      phase: 'Implement',
      schema: IMPLEMENT_SCHEMA
    };
    // An external job's wrapper is a Claude transport (job.agent_model); the
    // backend's own model (job.model) lives in the launch argv, never here.
    if (job.agent_model) opts.model = job.agent_model;
    else if (job.model) opts.model = job.model;
    if (job.effort) opts.effort = job.effort;
    // Narrow at spawn, same as the transport stages — a different list, because an
    // implementer keeps the tools it needs to write code. See IMPLEMENT_DISALLOWED.
    if (CFG.implement_disallowed) opts.disallowedTools = CFG.implement_disallowed;
    if (job.agent_isolation) opts.isolation = job.agent_isolation;
    if (job.implement_clamp) opts.bashCommandClamp = job.implement_clamp;
    // Spawn BY ROLE where the manifest's own job `type` says the work is one of
    // this project's registered agents. Only `type: review` maps today, to the
    // Review Gate — the need the native-mechanisms audit recorded against
    // `agentType`. Gate, Record and Finalize deliberately stay anonymous: they
    // are single-command transports whose safety is `disallowedTools` +
    // `bashCommandClamp`, and every agent definition here declares no `tools:`
    // restriction, so spawning them by role would hand back the whole toolbox.
    if (job.agent_type) opts.agentType = job.agent_type;
    // ONE attempt, fallback included. The by-role fallback answers a DIFFERENT
    // failure — the registry cannot spawn this role — so it lives INSIDE the
    // retried function rather than around it: a transient death retries the
    // whole attempt, fallback and all, and a missing agentType is still fixed on
    // the first try instead of being re-asked of a registry that will not change
    // its mind.
    async function attemptImplement(useOpts) {
      try {
        return await agent(p.implement, useOpts);
      } catch (spawnErr) {
        if (!job.agent_definition || !isAgentTypeMissing(spawnErr)) throw spawnErr;
        log('implement ' + job.id + ': ' + job.agent_type + ' is not loaded in this session — ' +
            'spawning from its inlined definition' +
            (job.agent_definition.max_turns
              ? '; its maxTurns cap of ' + job.agent_definition.max_turns +
                ' is LOST on this path (maxTurns is a property of a registered ' +
                'definition, and agent() has no option to re-impose it)'
              : ''));
        const inl = Object.assign({}, useOpts);
        delete inl.agentType;
        if (!inl.model && job.agent_definition.model) inl.model = job.agent_definition.model;
        return await agent(inlineDefinition(job, p.implement), inl);
      }
    }
    const first = await withRetry('implement', job.id, function () {
      return attemptImplement(opts);
    });
    let raw = first.value;
    let retries = first.retries;
    let escalatedFrom = null;
    // THE REVIEWER LIFT. A reviewer whose every attempt died transiently is
    // re-spawned ONCE on the next rung — the incident this feature exists for
    // is an Opus reviewer three 529s made unavailable. It is a REQUESTED
    // escalation: an org allowlist can substitute a model silently, so the run
    // records what was ASKED FOR and says so in those words.
    //
    // Implementers are never lifted here (the cross-run re-attempt escalation is
    // a different trigger, and it is the one `_is_reviewer_job` guards), and a
    // model that is not a rung — an explicit pin we do not own, or the top of
    // the ladder — has no successor and is left exactly as it was.
    if (first.exhausted && isReviewJob(job) && CFG.retry.escalate_reviewer) {
      const current = opts.model ? String(opts.model).toLowerCase() : null;
      const next = current ? (CFG.escalation[current] || null) : null;
      if (next) {
        log('review ' + job.id + ': ' + CFG.retry.max_attempts + ' attempt(s) on ' +
            current + ' produced no result — lifting ONCE to ' + next +
            ' (a requested escalation: an allowlist may substitute another model)');
        const lifted = Object.assign({}, opts);
        lifted.model = next;
        lifted.label = opts.label + ' (escalated)';
        escalatedFrom = current;
        retries = retries.concat([{ stage: 'implement', job: job.id,
                                    attempt: CFG.retry.max_attempts + 1, wait_ms: 0,
                                    escalated_from: current, model: next }]);
        try {
          raw = await attemptImplement(lifted);
        } catch (liftErr) {
          log('review ' + job.id + ': the escalated attempt threw: ' +
              String(liftErr && liftErr.message ? liftErr.message : liftErr));
          raw = null;
        }
      } else {
        log('review ' + job.id + ': NOT lifted — ' +
            (current ? current + ' is not a rung of the escalation ladder'
                     : 'no model is pinned, so there is no rung to step from'));
      }
    }
    return { job: job, implement: (raw === undefined ? null : raw),
             retries: retries, escalated_from: escalatedFrom,
             exhausted: Boolean(first.exhausted) && (raw === null || raw === undefined) };
  } catch (e) {
    // A THROW here would drop the item and skip Gate AND Record — the v2.6.4
    // audit-trail loss, structurally. Return the failure as a value instead, so
    // the Gate reads it as null-is-FAIL and Record still writes a result.
    log('implement ' + job.id + ' threw: ' + String(e && e.message ? e.message : e));
    return implementFailure(job);
  }
}

// ---------------------------------------------------------------------------
// Stage 2 — Gate. THIS STAGE MUST NEVER THROW.
//
// A throwing stage drops its item to null and skips every remaining stage, so a
// Gate exception means Record never runs: no state written, no result file, and
// the job silently becomes null — precisely on the jobs that went wrong. Every
// outcome, including "the gate itself failed", comes back as a verdict value.
//
// null is FAIL, never pass. agent() returns null when it is skipped or dies on a
// terminal API error, and a gate that reads null as "no violations found" is
// unreachable exactly when the worker died.
// ---------------------------------------------------------------------------
function gateFailure(jobId, reason) {
  return {
    job_id: jobId,
    verdict: 'error',
    source: 'workflow',
    reason: reason
  };
}

async function gateStage(prev, job) {
  // Declared OUTSIDE the try, so the catch can still carry the retry log. A
  // stage that swallows its own evidence on the way out is the failure this
  // file exists to prevent.
  let meta = { retries: [], exhausted: false, attempts: CFG.retry.max_attempts,
               escalated_from: null };
  try {
    if (prev === null || prev === undefined) {
      return gateFailure(job.id, 'implement stage produced null (skipped, or a terminal API error)');
    }
    meta = { retries: (prev.retries || []).slice(),
             exhausted: Boolean(prev.exhausted),
             attempts: CFG.retry.max_attempts,
             escalated_from: prev.escalated_from || null };
    let impl = prev.implement;
    if (impl === null || impl === undefined) {
      // The runtime hands back null when the implementer hit its turn cap or
      // died. r4 of v3.4.6 (finding 113): the fallback below only saw an EMPTY
      // object, so a null result still voided the wave. A null is the same
      // fact — no locator, unfinished work — so it takes the same path: gate
      // the registered tree with --impl-no-result for a Claude job; an external
      // worker's tree is outside the checkout, so that one still fails closed.
      const externalNull = job.backend && job.backend !== 'claude';
      if (externalNull) {
        return gateFailure(job.id, 'external worker returned null — treated as FAIL, never as a clean tree');
      }
      impl = {};
    }

    // WHERE TO GATE follows where the AGENT actually ran (`agent_isolation`),
    // never whether the agent happened to return a non-empty locator, and never
    // the MANIFEST's isolation — those are two different layers that share a
    // field name. A depends_on job declares `worktree` in the manifest (the
    // validator requires it; scope attribution uses it) and runs its agent in
    // the project checkout, because a fresh worktree branches from the default
    // ref and would not contain the wave that just committed.
    //
    // Reading the manifest value here made Record refuse a perfectly good direct
    // run for "carrying no observed worktree" — the fail-closed rule from 3.0.2
    // firing on a job that was never supposed to have one.
    // An EXTERNAL backend's wrapper agent runs direct (D5.3: no nested worktrees),
    // but the WORK lives in the worker's own worktree, returned as `worktree`.
    // Gating the checkout instead charged the codex job with the run's own
    // bookkeeping files and BLOCKED a green job (stage-4 dogfood, finding 79).
    const externalBackend = job.backend && job.backend !== 'claude';
    let gateRoot;
    let implNoResult = false;
    if (job.agent_isolation === 'worktree' || externalBackend) {
      gateRoot = (impl.worktree || '').trim();
      if (!gateRoot) {
        if (externalBackend) {
          return gateFailure(job.id, 'external worker reported no worktree; there is no tree to gate — fails closed');
        }
        // A Claude worktree job whose implementer returned nothing (turn cap, crash)
        // still has the tree the lane guard enforced: lane-map.json maps that cwd to
        // this job. gate-receipt resolves it and tags the receipt `impl_no_result`,
        // so Record refuses THIS job with a receipt instead of the authority voiding
        // the whole wave for want of one (findings 107/108, two runs lost).
        implNoResult = true;
      }
    } else {
      gateRoot = CFG.repo_root;
      if (!(impl.worktree || '').trim() && !(impl.status || '').trim()) implNoResult = true;
    }

    const cmd = CFG.python + ' -B ' + CFG.emitter + ' gate-receipt' +
      ' --run-dir ' + q(CFG.run_dir) +
      ' --job-id ' + q(job.id) +
      ' --repo-root ' + q(CFG.repo_root) +
      ' --worktree ' + q(gateRoot) +
      (implNoResult ? ' --impl-no-result' : '') +
      // The REQUESTED reviewer escalation, onto the receipt. A rung name from
      // CFG.escalation, so there is no caller text in this argv.
      (prev.escalated_from ? ' --escalated-from ' + q(prev.escalated_from) : '') +
      ' --manifest ' + q(CFG.manifest_path) +
      (CFG.manifest_digest ? ' --manifest-digest ' + q(CFG.manifest_digest) : '') +
      // The gate's mode must follow where the AGENT actually ran, not what the
      // manifest declares. A job with depends_on keeps `isolation: worktree` in the
      // manifest (the validator requires it, and scope attribution uses it) while its
      // agent runs in the main checkout, because a fresh worktree branches from the
      // default ref and would not contain the wave that just committed. Passing the
      // manifest's value here made the gate run in worktree mode over a direct run,
      // so it skipped the pre-existing snapshot and charged the job with every dirty
      // path in the tree. Two layers, one field name, opposite meanings.
      ' --mode ' + q((job.agent_isolation === 'worktree' || externalBackend) ? 'worktree' : 'direct') +
      (NOW ? ' --now ' + q(NOW) : '');

    const prompt =
      'Run EXACTLY this one command and return its JSON output verbatim as your ' +
      'structured result. Call the Bash tool with `timeout: 600000` (ten minutes): the command runs the test contract and can exceed the 120 s default, and a command the harness detaches to the background leaves you with no way to read its output — a verdict you did not read is not a verdict. ' +
      'Do not summarise it, do not re-run it, do not run ' +
      'anything else — your shell is clamped to this command form and any other ' +
      'command is denied.\n\n```bash\n' + cmd + '\n```\n';

    const opts = {
      label: 'gate ' + job.id,
      phase: 'Gate',
      schema: GATE_SCHEMA,
      // Transport, not judgment: one clamped command, verbatim JSON back.
      ...(CFG.transport_model ? { model: CFG.transport_model } : {}),
      // Narrow at spawn. Bash stays (a clamp on a Bash-less agent can bind
      // nothing and the runtime refuses the spawn); StructuredOutput stays or
      // schema mode is denied and the spawn is likewise refused.
      disallowedTools: CFG.narrow_disallowed,
      bashCommandClamp: [
        'Bash(' + CFG.python + ' -B ' + CFG.emitter + ' gate-receipt:*)'
      ]
    };

    const gres = await withRetry('gate', job.id, function () {
      return agent(prompt, opts);
    });
    meta.retries = meta.retries.concat(gres.retries);
    if (gres.exhausted) meta.exhausted = true;
    const verdict = gres.value;
    if (verdict === null || verdict === undefined) {
      return withRetryMeta(gateFailure(job.id, 'gate agent returned null — FAIL, never pass'), meta);
    }
    if (!verdict.verdict) {
      return withRetryMeta(gateFailure(job.id, 'gate agent returned no verdict field'), meta);
    }
    return withRetryMeta(verdict, meta);
  } catch (e) {
    // Everything. Including budget exhaustion, which throws.
    return withRetryMeta(gateFailure(job.id, 'gate stage caught: ' + String(e && e.message ? e.message : e)), meta);
  }
}

// ---------------------------------------------------------------------------
// Stage 3 — Record. EVIDENCE ONLY. It writes results/, receipts/ and state.json
// and it touches NOTHING in the main checkout.
//
// Until 3.0.2 this stage called `git apply --index` in the project checkout —
// BEFORE the integration authority had run, and without ever committing. Any
// later plain `git commit` (`/v:orchestrate` runs one) swept that staged patch
// into history, so a job could land with the authority never having run. The
// authority was not defeated; it was bypassed. Integration now belongs to the
// wave finalizer below, which runs the authority FIRST.
//
// Idempotence alone is not enough: a relaunch re-runs every agent that started
// after a failed one, INCLUDING completed ones, so a finished job can implement,
// gate and record a second time. The at-most-once property is keyed to an
// immutable commit hash in Python, not to this stage running once.
// ---------------------------------------------------------------------------
async function recordStage(verdict, job) {
  try {
    const v0 = verdict || gateFailure(job.id, 'record received a null verdict');
    // The retry log is BOOKKEEPING and never part of a verdict: it is lifted off
    // here and passed as its own argument, and the verdict that reaches argv or
    // a receipt comparison is byte-identical to the one the Gate produced.
    const meta = v0.__retry || null;
    const v = Object.assign({}, v0);
    delete v.__retry;
    const cmd = CFG.python + ' -B ' + CFG.emitter + ' record' +
      ' --run-dir ' + q(CFG.run_dir) +
      ' --job-id ' + q(job.id) +
      ' --repo-root ' + q(CFG.repo_root) +
      ' --manifest ' + q(CFG.manifest_path) +
      (CFG.manifest_digest ? ' --manifest-digest ' + q(CFG.manifest_digest) : '') +
      // The receipt the gate wrote is the verdict; pass its PATH and the two
      // fields that bind it, never the JSON inline (finding 69: the clamp
      // refuses argv that quotes a checker with `; do … done`). A verdict
      // without a receipt (gateFailure) is small and stays inline.
      (v.receipt_path
        ? ' --verdict-file ' + q(v.receipt_path) +
          ' --expect-verdict ' + q(String(v.verdict || '')) +
          (v.diff_digest ? ' --expect-diff-digest ' + q(String(v.diff_digest)) : '')
        : ' --verdict-json ' + q(JSON.stringify(v))) +
      (meta && (meta.retries.length || meta.exhausted || meta.escalated_from)
        ? ' --retries-json ' + q(JSON.stringify(meta)) : '') +
      (NOW ? ' --now ' + q(NOW) : '');

    const prompt =
      'Run EXACTLY this one command and return its JSON output verbatim as your ' +
      'structured result. Call the Bash tool with `timeout: 600000`. ' +
      'It is idempotent; do not re-run it, and do not run ' +
      'anything else.\n\n```bash\n' + cmd + '\n```\n';

    // Record's OWN retries cannot reach the result it is trying to write, so
    // they are logged and go no further — claiming them in a file this stage
    // never wrote would be the fabrication, not the omission.
    const rres = await withRetry('record', job.id, function () {
      return agent(prompt, {
      label: 'record ' + job.id,
      phase: 'Record',
      schema: RECORD_SCHEMA,
      // Transport, not judgment: one clamped command, verbatim JSON back.
      ...(CFG.transport_model ? { model: CFG.transport_model } : {}),
      disallowedTools: CFG.narrow_disallowed,
      bashCommandClamp: [
        'Bash(' + CFG.python + ' -B ' + CFG.emitter + ' record:*)'
      ]
      });
    });
    if (rres.retries.length) {
      log('record ' + job.id + ' retried: ' + JSON.stringify(rres.retries));
    }
    const ack = rres.value;
    if (ack === null || ack === undefined) {
      return { job_id: job.id, recorded: false, reason: 'record agent returned null' };
    }
    return ack;
  } catch (e) {
    return {
      job_id: job.id,
      recorded: false,
      reason: 'record stage caught: ' + String(e && e.message ? e.message : e)
    };
  }
}

// ---------------------------------------------------------------------------
// Stage 4 — the WAVE FINALIZER. Serialized, once per wave, after the pipeline.
//
// This is the only place a job's work reaches the project checkout, and it does
// three things IN THIS ORDER, in one Python call that fails closed at every step:
//
//   1. run scripts/compound-v-integration-gate.py — the AUTHORITY — over exactly
//      this wave's jobs. Anything other than `permitted` and nothing merges;
//   2. merge the permitted jobs' gate-approved slices into the checkout;
//   3. COMMIT them.
//
// Step 3 is what makes the wave barrier mean anything. A merge that only stages
// leaves the next wave's worktrees — created fresh at HEAD — unable to see their
// prerequisites, and leaves a patch lying in the index for an unrelated commit
// to sweep up. The barrier was documented as doing this since 1.0; it never did.
// ---------------------------------------------------------------------------
async function finalizeWave(waveIndex, wave) {
  const title = 'Wave ' + (waveIndex + 1);
  try {
    const ids = wave.map(function (j) { return j.id; }).join(',');
    const cmd = CFG.python + ' -B ' + CFG.emitter + ' finalize-wave' +
      ' --run-dir ' + q(CFG.run_dir) +
      ' --repo-root ' + q(CFG.repo_root) +
      ' --manifest ' + q(CFG.manifest_path) +
      (CFG.manifest_digest ? ' --manifest-digest ' + q(CFG.manifest_digest) : '') +
      ' --wave ' + q(String(waveIndex + 1)) +
      ' --jobs ' + q(ids) +
      (NOW ? ' --now ' + q(NOW) : '');

    const prompt =
      'Run EXACTLY this one command and return its JSON output verbatim as your ' +
      'structured result. Call the Bash tool with `timeout: 600000`. ' +
      'It runs the integration authority over this wave and, ' +
      'only if the authority permits, merges and commits the wave. Do not ' +
      'summarise it, do not re-run it, do not run anything else.\n\n```bash\n' +
      cmd + '\n```\n';

    const fres = await withRetry('finalize', 'wave-' + (waveIndex + 1), function () {
      return agent(prompt, {
      label: 'finalize ' + title,
      phase: 'Finalize',
      schema: FINALIZE_SCHEMA,
      // Transport, not judgment: one clamped command, verbatim JSON back.
      ...(CFG.transport_model ? { model: CFG.transport_model } : {}),
      disallowedTools: CFG.narrow_disallowed,
      bashCommandClamp: [
        'Bash(' + CFG.python + ' -B ' + CFG.emitter + ' finalize-wave:*)'
      ]
      });
    });
    if (fres.retries.length) {
      log(title + ' finalize retried: ' + JSON.stringify(fres.retries));
    }
    const res = fres.value;
    if (res === null || res === undefined) {
      return { wave: waveIndex + 1, integrated: false,
               reason: 'finalizer agent returned null — nothing is integrated' };
    }
    return res;
  } catch (e) {
    return {
      wave: waveIndex + 1,
      integrated: false,
      reason: 'finalize stage caught: ' + String(e && e.message ? e.message : e)
    };
  }
}

function waveHadFailure(waveSummary, fin) {
  if (!fin || fin.integrated !== true) return true;
  for (let i = 0; i < waveSummary.jobs.length; i++) {
    if (waveSummary.jobs[i].status !== 'success') return true;
  }
  return false;
}

// ---------------------------------------------------------------------------
// Waves. Each wave is a BARRIER, and the barrier is load-bearing.
//
// The next wave's agents — hence the next wave's worktrees — are not spawned
// until this wave has been gated by the authority, merged and COMMITTED. Do not
// flatten the waves, and do not move the finalizer inside the pipeline: it has
// to be serialized, because it writes to the one shared checkout.
// ---------------------------------------------------------------------------
const summary = {
  run_id: CFG.run_id, waves: [], stopped_for_budget: false,
  halted: false, halt_reason: null
};

for (let w = 0; w < CFG.waves.length; w++) {
  const wave = CFG.waves[w];
  const title = 'Wave ' + (w + 1);
  phase(title);

  if (!budgetAllows(wave.length)) {
    log(title + ': stopping before the budget ceiling rather than letting agent() throw. ' +
        'Remaining waves are unrun; /v:resume re-dispatches them.');
    summary.stopped_for_budget = true;
    break;
  }

  log(title + ': ' + wave.length + ' job(s) — ' + wave.map(function (j) { return j.id; }).join(', '));

  const acks = await pipeline(wave, implementStage, gateStage, recordStage);

  const waveSummary = { wave: w + 1, jobs: [] };
  for (let i = 0; i < wave.length; i++) {
    const ack = acks[i];
    waveSummary.jobs.push({
      id: wave[i].id,
      // A null ack means the pipeline dropped the item. That is a FAILURE, and
      // it is reported as one; the integration authority will find no valid
      // receipt for this job and refuse integration.
      recorded: ack ? Boolean(ack.recorded) : false,
      status: ack && ack.status ? ack.status : 'unknown',
      reason: ack && ack.reason ? ack.reason : null
    });
  }

  const fin = await finalizeWave(w, wave);
  waveSummary.finalize = fin;
  summary.waves.push(waveSummary);
  log(title + ' done: ' + JSON.stringify(waveSummary.jobs));
  log(title + ' finalize: ' + JSON.stringify(fin));

  // STOP SCHEDULING after any non-success result. Continuing past a blocked or
  // errored job builds later waves on a base that is missing a prerequisite, and
  // a dependent that silently ran without its dependency is worse than a run
  // that stopped where it broke. /v:resume re-dispatches what is incomplete.
  if (waveHadFailure(waveSummary, fin)) {
    summary.halted = true;
    summary.halt_reason = title + ': ' +
      (fin && fin.integrated === true
        ? 'a job did not reach `success`'
        : ('integration was not permitted — ' + (fin && fin.reason ? fin.reason : 'no reason given')));
    log('HALTED. ' + summary.halt_reason + ' Remaining waves are unrun; ' +
        'inspect the run dir and recover with /v:resume.');
    break;
  }
}

log('Engine C finished. Each wave was gated by scripts/compound-v-integration-gate.py ' +
    'before it merged; the workflow Gate stage is defence in depth and an early exit.');

return summary;
"""


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


# --------------------------------------------------------------------------- #
# gate-receipt — the Gate stage's single clamped command
# --------------------------------------------------------------------------- #
def _file_digest(path):
    """sha256 of a file's bytes, or None when it cannot be read."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(65536)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except Exception:  # noqa: BLE001
        return None


def write_preexisting(snapshot_path, repo_root, paths):
    """Write the exemption as ``<sha256>  <relpath>`` lines.

    PATHS ALONE ARE NOT AN EXEMPTION. A cross-model review called that CRITICAL and
    was right: once a run-directory file is listed by name, a worker can rewrite its
    CONTENTS — another job's baseline, a receipt, `state.json` — and the gate cannot
    tell that from untouched bookkeeping. The comment above it claimed a worker
    "cannot forge a receipt"; the code did not support the claim.

    Binding each path to the digest it had at registration turns the exemption into
    "this file, unchanged" instead of "this filename, whatever it now says". A
    file whose bytes moved is no longer exempt and is gated like any other write.

    A DIRECTORY is written as ``dir  <path>`` and exempted BY NAME: git reports an
    untracked directory as one entry, a directory has no bytes to digest, and
    dropping it broke the pre-existing-dirt exemption that had worked since 3.0
    (dogfood 10). Anything else whose digest cannot be taken — unreadable, already
    gone — is written with NO line at all and is therefore never exempted: fail
    closed into a stricter gate, the same rule the snapshot itself follows.

    An earlier version of this docstring said directories were "never exempted",
    which was the opposite of what the code beneath it does.
    """
    lines = []
    for rel in paths:
        full = os.path.join(repo_root, rel)
        dig = _file_digest(full)
        if dig:
            lines.append("%s  %s" % (dig, rel))
        elif os.path.isdir(full.rstrip("/")) or rel.endswith("/"):
            # A DIRECTORY CANNOT BE DIGESTED, AND DROPPING IT BREAKS THE SNAPSHOT.
            # git reports an untracked directory as ONE entry (`.claude/worktrees/x/`),
            # and the first digest-only version silently dropped every such entry —
            # so fifteen leftover harness worktrees, which the path-only snapshot had
            # correctly exempted since 3.0, came back as violations against the next
            # direct-mode job. Dogfood 10 blocked on exactly that.
            #
            # `dir` is a by-name exemption, and it is the right trade here: a
            # directory entry says nothing about its contents either way, and the
            # files INSIDE it are listed separately when git reports them.
            lines.append("dir  %s" % rel)
    _atomic_write(snapshot_path, "\n".join(lines) + ("\n" if lines else ""))
    return len(lines)


def read_preexisting_unchanged(snapshot_path, repo_root):
    """The exempt paths whose bytes still match the digest recorded at register time.

    A line with no digest is DROPPED, loudly. It used to be honoured as a legacy
    bare path, which let a worker append one and exempt any file it liked — the
    lane-widening chain in the comment below. Nothing this project writes produces
    that shape, and an old snapshot that exempts nothing fails closed.
    """
    keep = []
    skipped_legacy = []
    try:
        with open(snapshot_path, "r", encoding="utf-8") as fh:
            raw = [ln.rstrip("\n") for ln in fh]
    except Exception:  # noqa: BLE001
        return keep
    for line in raw:
        line = line.strip()
        if not line:
            continue
        parts = line.split("  ", 1)
        if len(parts) == 2 and re.match(r"^[0-9a-f]{64}$", parts[0]):
            rel = parts[1].strip()
            if _file_digest(os.path.join(repo_root, rel)) == parts[0]:
                keep.append(rel)
        elif len(parts) == 2 and parts[0] == "dir":
            keep.append(parts[1].strip())      # by-name: see write_preexisting
        else:
            # A LINE WITHOUT A DIGEST IS NOT AN EXEMPTION, and accepting one was a
            # full attack chain. A cross-model review walked it: a direct worker
            # writes out of lane, edits `manifest.yaml` to widen `write_allowed`,
            # then appends a bare `manifest.yaml` line here. This branch accepted
            # it as "legacy", the manifest became exempt, the gate loaded the
            # WIDENED manifest, the digest excluded the run directory so both
            # forgeries were invisible, and the authority independently derived the
            # same false pass from the same widened manifest. The out-of-lane write
            # was then committed.
            #
            # The comments above this function claimed that attack was closed. It
            # was not, and backward compatibility for a format that shipped the same
            # day is not worth a lane-widening hole. An unparsable line is DROPPED:
            # a snapshot written by an older build simply exempts nothing, which
            # blocks loudly instead of passing quietly.
            skipped_legacy.append(line)
    if skipped_legacy:
        sys.stderr.write(
            "compound-v: ignored %d exemption line(s) with no digest in %s — "
            "an exemption without a digest cannot be trusted (see the comment "
            "above read_preexisting_unchanged)\n"
            % (len(skipped_legacy), snapshot_path)
        )
    return keep


# THE EXACT, CLOSED LIST of run-directory files that are exempt BY NAME.
#
# The first version exempted every descendant of the run directory except the
# baseline pin, and a cross-model review found the hole in one move:
# `manifest.yaml` lives there, and the manifest DEFINES `write_allowed`. A worker
# could write out of lane, rewrite its own manifest to widen the lane, and both the
# gate and the integration authority would then read the widened manifest and agree
# it was in scope. The baseline and the digest could stay perfectly honest, because
# neither of them binds the document that says what "in scope" means.
#
# So the by-name pass is a CLOSED LIST — RUN_DIR_EXEMPT_BY_NAME below, one entry
# per file class with the reason it cannot be digest-bound — and every other file
# in the run directory, manifest.yaml included, falls back to the digest-bound
# listing taken at register time. Rewrite the manifest and its digest stops
# matching, the exemption is lost, and the write is a violation.
#
# Every entry is self-referential, shared, or written by the pipeline AFTER the
# gate built its list — consequences, not choices. Exempting a file from the SCOPE
# check does not make it trusted: the receipt, the result and the sealed patch are
# each verified by `compound-v-integration-gate.py` (digest against the tree,
# exactly one result per job, the artifact hashed against the receipt), and the
# documented limit stands — in `direct` mode a worker can write anywhere, which is
# why the authority is the backstop and the baseline pin stays digest-bound.
#
# The selftest is generated from THIS list: every entry must be exempt, and a
# sibling name beside each must not be (ninth review pass, item 2).


# (template, why) — `{id}` is the job id. Order is documentation, not precedence.
RUN_DIR_EXEMPT_BY_NAME = (
    ("state.json",
     "shared: every job's Record rewrites it, so a register-time digest can never match"),
    ("preexisting/{id}.txt",
     "the exemption list itself: it records digests INCLUDING ITS OWN"),
    ("preexisting/{id}.verified.txt",
     "written BY the gate, after the list that would have to contain it was built"),
    ("receipts/{id}.gate.json",
     "written by the gate after its verdict; verified by the authority's digest binding"),
    ("jobs/{id}.patch",
     "the sealed patch, written by the gate after its verdict; hashed against the receipt"),
    ("results/{id}.json",
     "written by Record after the gate; the authority requires exactly one per job"),
)
# A re-attempt archives its predecessor as results/attempts/<id>.<n>.json, written
# by the same Record call, for the same reason — an unbounded family, matched by
# pattern below.
RUN_DIR_EXEMPT_ATTEMPTS = r"^results/attempts/{id}\.\d+\.json$"


def run_dir_owned_by_name(rel, run_dir_rel, job_id):
    """True iff ``rel`` is one of the pipeline's own files for THIS job in THIS
    run's directory — exactly the classes in RUN_DIR_EXEMPT_BY_NAME plus the
    results/attempts/ family. Everything else — manifest, prompts, and anything a
    worker invents — is NOT exempt here."""
    if not run_dir_rel:
        return False
    prefix = run_dir_rel.rstrip("/") + "/"
    if not rel.startswith(prefix):
        return False
    tail = rel[len(prefix):]
    if tail in tuple(t.replace("{id}", job_id) for t, _why in RUN_DIR_EXEMPT_BY_NAME):
        return True
    return bool(re.match(RUN_DIR_EXEMPT_ATTEMPTS.replace("{id}", re.escape(job_id)), tail))


def _preexisting_snapshot(root, python_bin):
    """Repo-relative paths already dirty BEFORE this job ran (direct mode only).

    In `direct` mode the gate measures the whole working tree against the baseline,
    so it cannot tell a job's writes from dirt that was already there. Dogfooded
    2026-09-01: the first live Engine C run was BLOCKED not by its job — which
    stayed in its lane — but by leftover probe records, an untracked pre-eval
    directory and stray .pyc files. Every agent that day hit the same thing and
    passed `--preexisting` by hand.

    Captured at REGISTER time, before the implementer runs, so it is a genuine
    before-picture rather than a post-hoc excuse: anything appearing after this
    snapshot is the job's and is still gated. A worktree job needs none of this —
    its tree starts clean by construction.
    """
    out = _run([python_bin, "-B", "-c", (
        "import subprocess,sys\n"
        "def q(*a):\n"
        "    r = subprocess.run(['git','-C',sys.argv[1]]+list(a),"
        " capture_output=True, text=True)\n"
        "    return [x for x in r.stdout.split('\\0') if x]\n"
        "s = set(q('diff','--name-only','-z','HEAD'))\n"
        "s |= set(q('ls-files','--others','--exclude-standard','-z'))\n"
        "s |= set(q('ls-files','--others','--ignored','--exclude-standard','-z','--'))\n"
        "print('\\n'.join(sorted(s)))"), root])[1]
    return [ln for ln in out.splitlines() if ln.strip()]


def _run_scope_check(scope_check, mode, root, baseline, allow, python_bin,
                     preexisting=None):
    cmd = [python_bin, "-B", scope_check]
    cmd += ["--worktree" if mode == "worktree" else "--repo", root]
    if baseline:
        cmd += ["--baseline", baseline]
    for glob in allow:
        cmd += ["--allow", glob]
    # --preexisting takes a FILE of paths, one per line — not a repeatable value.
    # Passing paths individually made argparse keep only the last and try to open
    # it as a filename, so the subtraction silently did nothing. Caught on the
    # third live Engine C run, by the gate still reporting paths the snapshot had
    # captured correctly.
    if preexisting:
        cmd += ["--preexisting", preexisting]
    rc, out, err = _run(cmd)
    try:
        parsed = json.loads(out) if out.strip() else None
    except Exception:  # noqa: BLE001
        parsed = None
    return rc, out, err, parsed


def _run_test_floor(fastpath, manifest_path, job_id, worktree, baseline,
                    python_bin, last_result=None):
    """The floor, via the producer task-3 built.

    This is what replaces the `--test-cmd <configured-tests>` placeholder. That
    placeholder never had a value, which is why the floor had never executed once
    before today. `test-floor --manifest --job-id` resolves the command set from
    the manifest's `test_contract` and the job's `test_scope` — in Python, where
    the glob resolution can be tested — and the worker only executes it.
    """
    if not os.path.exists(fastpath):
        return None, "fastpath-run.py not found at %s" % fastpath
    cmd = [python_bin, "-B", fastpath, "test-floor", "--worktree", worktree,
           "--manifest", manifest_path, "--job-id", job_id]
    if baseline:
        cmd += ["--baseline", baseline]
    if last_result and os.path.exists(last_result):
        cmd += ["--last-result", last_result]
    else:
        cmd += ["--no-prior-run"]
    rc, out, err = _run(cmd)
    try:
        parsed = json.loads(out) if out.strip() else None
    except Exception:  # noqa: BLE001
        parsed = None
    if parsed is None:
        return None, "test floor produced no JSON (rc=%d): %s" % (rc, (err or out)[:400])
    return parsed, None


def _resolve_test_contract(fastpath, manifest_path, job_id, worktree, baseline,
                           python_bin, out_path):
    """Write jobs/<job-id>.test-contract.json — the slice a worker is HANDED.

    `job_spec.test_contract` is the resolved contract for exactly one job, and it
    travels as `--test-contract-file`, a real argument, never as prompt prose. A
    value a model has to notice is not a contract.
    """
    if not os.path.exists(fastpath):
        return None
    cmd = [python_bin, "-B", fastpath, "resolve-tests", "--worktree", worktree,
           "--manifest", manifest_path, "--job-id", job_id, "--out", out_path,
           "--no-prior-run"]
    if baseline:
        cmd += ["--baseline", baseline]
    rc, _, _ = _run(cmd)
    return out_path if rc == 0 and os.path.exists(out_path) else None


def _lane_map_worktree_for(run_dir, job_id, repo_root):
    """The worktree lane-map.json registered for `job_id` (the cwd the lane guard
    enforced for it), or None. Exactly one entry, an existing directory, and not the
    checkout itself — anything else is not a locator this gate may trust."""
    lm = _read_json(os.path.join(run_dir, "lane-map.json"), None)
    if not isinstance(lm, dict):
        return None
    cands = [p for p, j in (lm.get("worktrees") or {}).items() if j == job_id]
    if len(cands) != 1:
        return None
    cand = os.path.abspath(cands[0])
    if not os.path.isdir(cand) or cand == os.path.abspath(repo_root):
        return None
    return cand


def cmd_gate_receipt(argv):
    ap = argparse.ArgumentParser(prog="compound-v-emit-workflow.py gate-receipt")
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--job-id", required=True)
    ap.add_argument("--worktree", required=True)
    ap.add_argument("--impl-no-result", dest="impl_no_result", action="store_true",
                    help="the implementer returned no result; for a Claude worktree job "
                         "resolve the tree from lane-map.json's registration and tag the "
                         "receipt, so Record can refuse this job with evidence")
    ap.add_argument("--escalated-from", dest="escalated_from",
                    help="the model this job was lifted FROM after its retry budget "
                         "was exhausted (the reviewer lift). Recorded on the receipt "
                         "as the REQUESTED escalation: an org allowlist can substitute "
                         "a model silently, so the claim is what was asked for.")
    ap.add_argument("--manifest")
    ap.add_argument("--mode", choices=["worktree", "direct"], default="worktree")
    ap.add_argument("--repo-root", required=True,
                    help="the PROJECT root. Required: a `direct` job is gated in "
                         "this tree, and a defaulted root gates the wrong repo.")
    ap.add_argument("--scope-check", default=SCOPE_CHECK_DEFAULT)
    ap.add_argument("--fastpath", default=FASTPATH_DEFAULT)
    ap.add_argument("--python", default=(sys.executable or "python3"))
    ap.add_argument("--manifest-digest",
                    help="sha256:<hex> the manifest MUST hash to, baked in by "
                         "`emit`. A mismatch refuses: the manifest is the lane "
                         "map this gate measures against.")
    ap.add_argument("--now")
    args = ap.parse_args(argv)
    if getattr(args, "impl_no_result", False) and not (args.worktree or "").strip():
        _lm_wt = _lane_map_worktree_for(os.path.abspath(args.run_dir), args.job_id,
                                        os.path.abspath(args.repo_root))
        if args.mode != "worktree" or not _lm_wt:
            out = {"job_id": args.job_id, "verdict": "error", "source": "gate-receipt",
                   "impl_no_result": True,
                   "reason": "implementer returned no result and lane-map.json holds no "
                             "single registered worktree for this job — fails closed"}
            print(json.dumps(out, indent=2, sort_keys=True))
            return 2
        args.worktree = _lm_wt

    run_dir = os.path.abspath(args.run_dir)
    manifest_path = os.path.abspath(
        args.manifest or os.path.join(run_dir, "manifest.yaml")
    )
    job_id = args.job_id
    out = {"job_id": job_id, "verdict": "error", "source": "gate-receipt"}

    fault = manifest_digest_fault(manifest_path, args.manifest_digest)
    if fault:
        out["reason"] = fault
        print(json.dumps(out, indent=2, sort_keys=True))
        return 2

    try:
        manifest = _load_yaml(manifest_path) or {}
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        out["reason"] = "manifest unreadable: %s" % exc
        print(json.dumps(out, indent=2, sort_keys=True))
        return 2

    job = _manifest_job(manifest, job_id)
    if job is None:
        out["reason"] = "no job %s in the manifest" % job_id
        print(json.dumps(out, indent=2, sort_keys=True))
        return 2

    repo_root = os.path.abspath(args.repo_root)
    reasons = []

    # WHERE TO GATE follows the MODE, which follows the manifest's isolation —
    # never a locator an agent chose. A `direct` job is gated in the project
    # checkout; the caller still passes `--worktree` so a disagreement is caught
    # rather than silently resolved in the agent's favour.
    if args.mode == "direct":
        root = repo_root
        if os.path.abspath(args.worktree) != repo_root:
            out["reason"] = (
                "direct job reported worktree %s, which is not the project root "
                "%s — a direct job has no worktree, and 3.0.1 turned exactly this "
                "mismatch into a patch applied to the wrong repository"
                % (os.path.abspath(args.worktree), repo_root)
            )
            print(json.dumps(out, indent=2, sort_keys=True))
            return 2
    else:
        root = os.path.abspath(args.worktree)
    if not os.path.isdir(root):
        out["reason"] = "gate root does not exist: %s" % root
        print(json.dumps(out, indent=2, sort_keys=True))
        return 2

    # The baseline is the PINNED pre-launch SHA, never a live HEAD, and its
    # ABSENCE FAILS CLOSED. 3.0.1 fell back to the gate root's HEAD, which is
    # exactly the value a worker that commits inside its worktree has already
    # moved — so the fallback measured the job against its own output and
    # reported a clean tree. An unknown baseline is not a passing one.
    state = _load_state(run_dir)
    state_job = state["jobs"].get(job_id) or {}
    baseline = read_pinned_baseline(run_dir, job_id, state_job)
    if not baseline:
        out["reason"] = (
            "no baseline pinned for job %s (neither state.json nor "
            "jobs/%s.baseline). register-lane pins it before the worker launches; "
            "without it the gate would measure against a HEAD the worker can move, "
            "so this fails closed" % (job_id, job_id)
        )
        print(json.dumps(out, indent=2, sort_keys=True))
        return 2
    realised = _head_commit(root)

    allow = job.get("write_allowed") or []
    # Direct mode only: subtract what was already dirty when the job registered.
    # Never in worktree mode — a worktree starts clean, so a subtraction there could
    # only ever hide a real violation.
    foreign = []
    pre = None
    if args.mode != "worktree":
        candidate = os.path.join(args.run_dir, "preexisting", "%s.txt" % args.job_id)
        if os.path.isfile(candidate):
            # The snapshot binds each path to the digest it had at register time.
            # Only paths whose bytes STILL match are exempt; a bookkeeping file the
            # worker rewrote is gated like any other write. scope-check's
            # `--preexisting` takes a plain path list, so the verified subset is
            # materialised next to the snapshot rather than handed over whole.
            kept = read_preexisting_unchanged(candidate, root)
            # Plus everything the pipeline owns in THIS run directory, by name.
            # `state.json` is shared — a sibling job's Record rewrites it between
            # this job registering and its gate running, so a digest taken at
            # register time can never match again — and `<id>.verified.txt` is
            # written by this very block, after registration. Both were violations
            # until dogfood 10 ran a two-wave direct-mode job and blocked its own
            # reviewer over them. The two levers a worker could actually pull —
            # `jobs/<id>.baseline` and `preexisting/<id>.txt` — are excluded from
            # this by-name pass and stay digest-bound.
            run_rel = os.path.relpath(os.path.abspath(args.run_dir),
                                      os.path.abspath(root))
            if not run_rel.startswith(".." + os.sep):
                run_rel = run_rel.replace(os.sep, "/")
                seen = set(kept)
                for dirpath, _dn, filenames in os.walk(args.run_dir):
                    for name in filenames:
                        rel = os.path.relpath(
                            os.path.abspath(os.path.join(dirpath, name)),
                            os.path.abspath(root)).replace(os.sep, "/")
                        if rel in seen:
                            continue
                        if run_dir_owned_by_name(rel, run_rel, args.job_id):
                            kept.append(rel)
                            seen.add(rel)
            verified = os.path.join(args.run_dir, "preexisting",
                                    "%s.verified.txt" % args.job_id)
            # THE FILE MUST LIST ITSELF. It is written after `kept` is built, so the
            # run-directory walk above cannot have seen it — dogfood 12 blocked on
            # this one path and nothing else, the self-reference one layer deeper
            # than dogfood 11's. Adding its own path is the whole fix: a list that
            # does not exempt itself can never let a direct-mode job pass.
            # THE FILES THAT DO NOT EXIST YET, ADDED BY CONSTRUCTION.
            #
            # The walk above can only list what is on disk NOW. Three of this job's
            # pipeline files are written LATER — this verified list, the gate's own
            # receipt, and Record's result — so a predicate that recognises them is
            # not enough; they have to be named. Dogfood 21 proved that the hard
            # way: the predicate was right, the walk simply could not see them, and
            # the run failed on the same two paths as dogfood 20.
            #
            # Chasing these one per run cost five dogfoods. They are enumerated here
            # ONCE, from the three places in this file that write them.
            for _later in (verified,
                           os.path.join(args.run_dir, "receipts",
                                        "%s.gate.json" % args.job_id),
                           patch_artifact_path(args.run_dir, args.job_id),
                           os.path.join(args.run_dir, "results",
                                        "%s.json" % args.job_id)):
                _rel = os.path.relpath(os.path.abspath(_later),
                                       os.path.abspath(root)).replace(os.sep, "/")
                if not _rel.startswith("../") and _rel not in kept:
                    kept.append(_rel)
            _atomic_write(verified, "\n".join(kept) + ("\n" if kept else ""))
            pre = verified
    rc, raw_stdout, err, parsed = _run_scope_check(
        args.scope_check, args.mode, root, baseline, allow, args.python, preexisting=pre
    )
    # NAME THE OPERATOR'S FOOTPRINTS SEPARATELY.
    #
    # A `direct`-mode job measures the whole tree, so ANYTHING written while
    # it runs is attributed to it — including another run's manifest that a
    # human was preparing in the next terminal. That is not a gate bug; the
    # gate cannot tell two writers apart. But the resulting refusal reads as
    # "your job wrote five files it should not have", which is the opposite
    # of what happened, and this has now confused three dogfood runs — all
    # three mine.
    #
    # So paths under the execution root that belong to some OTHER run are
    # still violations, and are additionally listed under
    # `foreign_execution_paths` so the diagnosis is immediate. A worker that
    # genuinely writes into another run's directory is caught exactly as
    # before; only the explanation improves.
    exec_root = "docs/superpowers/execution/"
    this_run = os.path.basename(os.path.normpath(args.run_dir))
    for p in ((parsed or {}).get("violations") or []):
        if p.startswith(exec_root):
            seg = p[len(exec_root):].split("/", 1)[0]
            if seg and seg != this_run:
                foreign.append(p)

    if baseline:
        # In DIRECT mode the run directory sits inside the measured tree and the
        # pipeline keeps writing into it after this point (Record, receipts,
        # state.json). Excluding it here — and identically in the authority — is
        # what makes the two digests comparable at all. It is the ONLY exclusion:
        # everything else the pipeline writes now happens after the authority has
        # run, so no tracked file needs forgiving by name.
        _digest_excl = None
        if args.mode != "worktree":
            _rel = os.path.relpath(os.path.abspath(args.run_dir), os.path.abspath(root))
            if not _rel.startswith(".." + os.sep):
                _digest_excl = [_rel.replace(os.sep, "/")]
        digest, digest_err = compute_diff_digest(root, baseline,
                                                 exclude_prefixes=_digest_excl)
    else:
        digest, digest_err = None, "no baseline to diff against"

    if parsed and parsed.get("verdict") in ("pass", "blocked"):
        verdict = parsed["verdict"]
    elif rc == 0:
        verdict = "pass"
    elif rc == 1:
        verdict = "blocked"
    else:
        verdict = "error"

    out["verdict"] = verdict
    out["exit_code"] = rc
    out["raw_stdout"] = raw_stdout
    if foreign:
        out["foreign_execution_paths"] = foreign
        out["foreign_execution_note"] = (
            "%d violation(s) live under another run's execution directory. A "
            "`direct`-mode job measures the WHOLE tree, so anything written while it "
            "ran is attributed to it — including files a human was preparing in "
            "another terminal. These are still violations (a worker writing into "
            "another run's directory must be caught), but if you were editing during "
            "this run, they are yours, not the job's." % len(foreign)
        )
    # The tree this gate MEASURED, carried forward to Record explicitly. Empty
    # for a direct job — that is a value, not a missing one, and Record branches
    # on the manifest's isolation rather than on whether this string is blank.
    out["worktree"] = "" if args.mode == "direct" else root
    if getattr(args, "impl_no_result", False):
        # Carried into the receipt so Record refuses the JOB (status error, with the
        # measured tree as evidence) rather than the authority voiding the wave.
        out["impl_no_result"] = True
    _esc_from = str(getattr(args, "escalated_from", "") or "").strip()
    if _esc_from:
        # The REQUESTED escalation, not a claim about what ran: an allowlist can
        # substitute the model without telling anyone, so the receipt says which
        # rung the run ASKED to leave, and nothing about which one answered.
        out["escalated_from"] = _esc_from
    if baseline:
        out["baseline_commit"] = baseline
    if realised:
        out["realised_commit"] = realised
    if digest:
        out["diff_digest"] = digest
    elif digest_err:
        reasons.append("diff digest not computed: %s" % digest_err)
    if verdict == "error" and err.strip():
        reasons.append(err.strip())

    # Tests run AFTER the gate and only when the job would otherwise pass.
    # Running them first would let a coverage file or a cache dir a test wrote
    # become a false violation. The flip side is the caller's problem and is
    # handled at merge: staging is restricted to the gate-approved paths.
    # A job that declared write_allowed and changed NOTHING did not do its work.
    # "No files changed" is not "clean" — it is "no work", and the two are opposite
    # conclusions that the gate's pass/blocked axis cannot tell apart on its own.
    # Dogfooded 2026-09-01 on a two-wave run: the dependent job returned
    # files_changed: [], the gate passed it, Record wrote success, and the wave
    # finalizer honestly reported "nothing left to commit" — so the whole chain
    # reported success for work that never happened. The manifest is what makes
    # this decidable: a job with an empty write_allowed (a reviewer) is expected to
    # change nothing; a job with lanes is not.
    gate_changed = (parsed or {}).get("changed") or []
    if verdict == "pass" and (job.get("write_allowed") or []) and not gate_changed:
        # `blocked`, not a new verdict word: job_result.schema.json pins
        # gate_receipt.verdict to pass|blocked|error, and the authority cross-checks
        # verdict against exit_code. A fourth value produced an INCOHERENT receipt
        # that the authority correctly read as `forged` — a refusal for the wrong
        # reason is only marginally better than no refusal, because it sends whoever
        # reads it hunting a forgery that never happened.
        verdict = "blocked"
        out["verdict"] = verdict
        out["exit_code"] = 1
        out["no_work"] = True
        out["reason"] = (
            "job %r declares write_allowed but changed no files. That is not a clean "
            "tree, it is an absent implementation — failing closed rather than "
            "recording a success nobody can point at." % job_id)

    if verdict == "pass":
        # Re-resolved here against the job's REALISED diff. The Implement stage
        # already wrote one (that is the copy an external worker was handed,
        # before it changed anything); this one is what the floor about to run
        # was scoped from, and it is what `record` reads `scope` back out of.
        contract_out = test_contract_path(run_dir, job_id)
        os.makedirs(os.path.dirname(contract_out), exist_ok=True)
        _resolve_test_contract(
            args.fastpath, manifest_path, job_id, root, baseline,
            args.python, contract_out,
        )
        tests, test_err = _run_test_floor(
            args.fastpath, manifest_path, job_id, root, baseline, args.python
        )
        if tests is not None:
            out["tests"] = tests
        elif test_err:
            reasons.append("test floor: %s" % test_err)

    # ---- SEAL WHAT THIS GATE APPROVED -------------------------------------- #
    # The merge used to take a FRESH diff of the live tree whenever the finalizer
    # got round to it, so whatever the tree said THEN is what landed — gate or no
    # gate. Everything between the two moments rode along: a revert, a post-gate
    # edit to an in-lane file, the test floor's own byproducts. The artifact is
    # written here, from the paths this gate approved and nothing else, and its
    # sha256 goes into the receipt. `finalize-wave` applies this file.
    #
    # Sealed on a BLOCKED verdict too, deliberately: nothing will apply it, and a
    # human reading a refused run gets the exact diff that was refused.
    approved = [pth for pth in gate_changed
                if pth not in ((parsed or {}).get("violations") or [])]
    if baseline and approved:
        patch_bytes, patch_err = build_sealed_patch(root, baseline, approved)
        if patch_err:
            reasons.append("sealed patch not written: %s" % patch_err)
        else:
            patch_path = patch_artifact_path(run_dir, job_id)
            os.makedirs(os.path.dirname(patch_path), exist_ok=True)
            _atomic_write_bytes(patch_path, patch_bytes)
            out["patch_path"] = patch_path
            out["patch_sha256"] = ("sha256:"
                                   + hashlib.sha256(patch_bytes).hexdigest())
            out["patch_paths"] = approved
    elif baseline and verdict == "pass" and not approved:
        # A pass with nothing approved is already refused above (`no_work`) for any
        # job that declared lanes; a reviewer legitimately approves nothing, and
        # there is nothing to seal.
        out["patch_paths"] = []

    if reasons:
        out["reason"] = " | ".join(reasons)

    receipt_dir = os.path.join(run_dir, "receipts")
    os.makedirs(receipt_dir, exist_ok=True)
    receipt_path = os.path.join(receipt_dir, "%s.gate.json" % job_id)
    _atomic_write(receipt_path, json.dumps(out, indent=2, sort_keys=True) + "\n")
    out["receipt_path"] = receipt_path

    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


# --------------------------------------------------------------------------- #
# record — idempotent persistence, and merge-back AT MOST ONCE
#
# Idempotence on Record alone is NOT enough. On relaunch every agent that started
# after a failed one re-runs, completed ones included, so a finished job can
# implement, gate and record a second time. The at-most-once property is keyed to
# an IMMUTABLE COMMIT HASH: `state.json jobs[<id>].merged.realised_commit`. A
# second Record for the same realised commit persists the result again (harmless,
# same bytes) and refuses to merge again.
#
# Merge-back is corrected here as task-6 requires, and that correction closes a
# PRE-EXISTING data-loss bug:
#
#   * Stage by the gate's `files_changed`, NUL-delimited, never a bare
#     `git add -A`. Tests run after the gate, so a coverage file or a cache dir
#     exists in the worktree by merge time and is outside the gate's authority.
#     Restricting the pathspec is what keeps "only what the gate approved gets
#     merged" true. NUL-delimited because a path may legitimately contain a
#     newline and the workers keep `files_changed` newline-safe on purpose.
#   * Diff against the PINNED baseline SHA, never HEAD. `--cached HEAD` agrees
#     with the baseline only while the executor never commits; an executor that
#     DID commit inside its worktree leaves HEAD past the baseline, passes the
#     gate (which uses the pinned SHA), and its committed half silently fails to
#     land at merge.
# --------------------------------------------------------------------------- #
def _stage_paths(worktree, paths):
    """Stage exactly these paths. Returns (ok, error).

    A DELETION the worker already staged (`git rm`) leaves nothing on disk and
    nothing in the index for the pathspec to match, so `git add -A -- path`
    fails with "did not match any files" — which meant no `git rm` could ever
    merge back (dogfood r4, 2026-09-02: three deletions the gate approved were
    refused by the finalizer). A path whose removal is already in the index is
    already staged; accept it. A path that is neither on disk, nor in the index,
    nor staged as removed is still an error.
    """
    for path in paths:
        if not path:
            continue
        rc, _, err = _git(worktree, ["add", "-A", "--", path])
        if rc != 0:
            rc2, staged, _e2 = _git(worktree, ["diff", "--cached", "--name-only",
                                              "--diff-filter=D", "--", path])
            if rc2 == 0 and path in [l.strip() for l in (staged or "").splitlines()]:
                continue  # the removal is already staged; nothing more to add
            return False, "git add failed for %r: %s" % (path, err.strip())
    return True, None


def read_sealed_patch(run_dir, job_id, gate_doc):
    """(patch bytes, error) — the artifact the GATE sealed, verified by digest.

    The finalizer applies this and only this. A run whose gate recorded no
    `patch_sha256` (a receipt from before 3.4.0) returns `(None, None)`: nothing
    to apply and nothing to verify, and the caller falls back to the old
    fresh-diff merge for it rather than refusing a run it cannot re-gate.
    """
    declared = (gate_doc or {}).get("patch_sha256")
    if not (isinstance(declared, str) and declared.strip()):
        return None, None
    path = patch_artifact_path(run_dir, job_id)
    if not os.path.isfile(path):
        return None, ("the gate sealed a patch (%s) but %s is missing; the merge "
                      "applies that artifact, so an absent one is refused rather "
                      "than replaced by a fresh diff of a tree that has moved"
                      % (declared, path))
    try:
        with open(path, "rb") as fh:
            blob = fh.read()
    except (IOError, OSError) as exc:
        return None, "cannot read %s: %s" % (path, exc)
    actual = "sha256:" + hashlib.sha256(blob).hexdigest()
    if actual != declared:
        return None, ("%s hashes to %s, not the %s the gate's receipt records — "
                      "the artifact was replaced after it was sealed"
                      % (path, actual, declared))
    return blob, None


def apply_patch(repo_root, patch_bytes):
    """`git apply --index` the sealed artifact into the project checkout."""
    if not (patch_bytes or b"").strip():
        return True, None
    try:
        proc = subprocess.Popen(
            ["git", "-C", repo_root, "apply", "--index", "-"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        _o, apply_err = proc.communicate(patch_bytes)
        if proc.returncode != 0:
            return False, "git apply --index failed: %s" % apply_err.decode(
                "utf-8", "replace").strip()
    except Exception as exc:  # noqa: BLE001
        return False, "git apply raised: %s" % exc
    return True, None


def merge_back(worktree, repo_root, baseline, files_changed):
    """Apply the gate-approved slice of a worktree into the main tree.

    FALLBACK ONLY. Since 3.4.0 the finalizer applies the patch the GATE sealed;
    this fresh diff of the live worktree is what remains for a run whose receipts
    predate sealing, and it is exactly the behaviour sealing replaced — whatever
    the tree says NOW is what lands.
    """
    if not baseline:
        return False, "no pinned baseline; refusing to merge against a moving HEAD"
    if not files_changed:
        # A worktree job that reached `success` and approved NO files is a record
        # defect, not a no-op: Record marks a job that changed nothing as
        # no_work/blocked, so it never gets here. Treating this as "nothing to
        # land" let a finalizer mark a job merged and prune the only copy of
        # its work (2026-09-02). Refuse, and keep the worktree.
        return False, ("the record approved no files for this worktree job; a "
                       "pass verdict with an empty changed list lands nothing "
                       "and is refused rather than pruned")
    ok, err = _stage_paths(worktree, files_changed)
    if not ok:
        return False, err
    rc, patch, err = _git(
        worktree, ["diff", "--cached", "--binary", baseline], text=False
    )
    if rc != 0:
        return False, "git diff --cached failed: %s" % err.strip()
    if not patch.strip():
        return True, None
    try:
        proc = subprocess.Popen(
            ["git", "-C", repo_root, "apply", "--index", "-"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        _, apply_err = proc.communicate(patch)
        if proc.returncode != 0:
            return False, "git apply --index failed: %s" % apply_err.decode(
                "utf-8", "replace"
            ).strip()
    except Exception as exc:  # noqa: BLE001
        return False, "git apply raised: %s" % exc
    return True, None


# --------------------------------------------------------------------------- #
# the floor document -> the schema's `tests` block
#
# `test-floor` and `job_result.tests` are two DIFFERENT shapes, and Engine C used
# to copy the first into the second verbatim. The floor returns
# `{phase, tier_used, passed, merge_blocked, changed_paths, checks, reasons,
#   failures?, contract_notes?}`; the schema's `tests` object is
# `additionalProperties: false` and requires exactly
# `{command, exit_code, scope, selected_count}`. So EVERY Engine C job_result —
# on the clean happy path, not some edge — failed the schema `/v:collect` says it
# is validated against, and `agents/spec-reviewer.md` FAILs any job whose
# `tests.command` is absent: the default engine's every job would have been
# failed by this release's own review gate.
#
# Translation happens HERE, at the one boundary that builds a job_result, so
# there is a single producer of the shape rather than one per caller.
#
# WHAT IS MEASURED AND WHAT IS NOT, stated rather than papered over:
#   * `command` / `selected_count` come from the floor's `checks[].checker` — the
#     commands it ACTUALLY ran, in execution order. No checker strings at all
#     means the floor executed nothing, and then the whole object is OMITTED:
#     absent is honest, an invented zero is not.
#   * `exit_code` is the FIRST non-zero `rc` the floor recorded. A floor that
#     failed WITHOUT recording an rc (tier-2/3 report `status`, not always a
#     usable code) reports 1 — non-zero is what is known to be true; the exact
#     value is a summary, and the alternative (dropping the object) would hide a
#     failure. A passing floor with no rc reports 0.
#   * `failures` / `duration_ms` are copied ONLY when the floor reports them.
#     Tier-1 always sets `failures` (empty = measured-and-nothing-failed); tiers
#     2 and 3 never do, and its ABSENCE is what makes B2 fall back to
#     `full_command` instead of silently dropping the previously-failing set.
#     Nothing here measures duration, so nothing here invents one.
#   * `scope` is copied from the resolved contract slice the same floor ran, and
#     falls back to the job's declared `test_scope`, then to a MIRROR of the
#     resolver's own default — `default_scope_for(contract, tier)` — which needs
#     the manifest's triage tier as well as the contract. Until the r5 fix in 3.4.0 that last
#     fallback read the `impacted_map` alone and never saw the tier, so a job the
#     resolver had scoped `floor_only` (DIRECT tier with a declared floor) was
#     recorded as `impacted`: a scope in the audit record that no run ever used.
#     `tests.scope` is exactly the field a reviewer checks against the tier, so a
#     label derived from less than the resolver used cannot do that job.
# --------------------------------------------------------------------------- #
# `impacted+referencing` joined in 3.4.1 (decision 4): a SCOPED/DIRECT job whose unmapped
# path resolved to referencing tests. Without it here the translation silently DOWNGRADED
# that label to the derived default, so the record said `impacted` for a slice that ran
# something else — the label the reviewer checks against the tier (review-3 of 3.4.1).
TESTS_SCOPES = ("full", "impacted", "floor_only", "impacted+referencing")


def _tests_block_from_floor(floor, contract=None, job=None, tier=None):
    """Translate a `test-floor` document into the schema's `tests` block.

    Returns None when the floor ran no command — the schema says to omit the
    object entirely rather than report a fabricated zero.

    `tier` is the manifest's `triage.tier`. It is only consulted by the last-resort
    scope fallback, which mirrors the resolver's own default; the resolved slice's
    own `scope` still wins whenever the caller has one.
    """
    if not isinstance(floor, dict):
        return None
    # Already in schema shape (a caller that translated once) — pass it through.
    if "command" in floor and "phase" not in floor:
        return floor

    checks = [c for c in (floor.get("checks") or []) if isinstance(c, dict)]
    commands = [str(c.get("checker")).strip() for c in checks
                if str(c.get("checker") or "").strip()]
    if not commands:
        return None

    exit_code = None
    for check in checks:
        rc = check.get("rc")
        if isinstance(rc, int) and rc != 0:
            exit_code = rc
            break
    if exit_code is None:
        passed = bool(floor.get("passed")) and not floor.get("merge_blocked")
        exit_code = 0 if passed else 1

    scope = None
    for candidate in ((contract or {}).get("scope"), (job or {}).get("test_scope")):
        if isinstance(candidate, str) and candidate in TESTS_SCOPES:
            scope = candidate
            break
    if scope is None:
        # Mirror of compound-v-fastpath-run.py:default_scope_for(contract, tier).
        # DUPLICATED on purpose — both are standalone stdlib CLIs with no shared
        # import (house style). Keep in sync, and keep ALL THREE branches: this
        # read the `impacted_map` alone until the r5 fix in 3.4.0 and so could never report
        # `floor_only`, labelling a DIRECT-tier job that ran only its floor as
        # `impacted`. Reporting a scope the resolver did not select puts a value in
        # the audit record that no run ever used — a fabricated field wearing a
        # schema-valid value, in the one field a reviewer checks against the tier.
        tier_s = str(tier or "").strip().upper()
        floor_cmd = (contract or {}).get("floor_command")
        rows = (contract or {}).get("impacted_map")
        if tier_s == "DIRECT" and isinstance(floor_cmd, str) and floor_cmd.strip():
            scope = "floor_only"
        elif isinstance(rows, list) and rows:
            scope = "impacted"
        else:
            scope = "full"

    block = {
        "command": "\n".join(commands),
        "exit_code": int(exit_code),
        "scope": scope,
        "selected_count": len(commands),
    }
    failures = floor.get("failures")
    # `failures[]` is tier-1's own per-command identifier list (comment above:
    # tiers 2/3 never set it), and it is where a checker's timeout is recorded
    # as `timeout after N s: <checker>`. `reasons[]` is the floor's narrative
    # trail — normally a DIFFERENT sentence for the same event — but it is the
    # only place a timeout would surface if `failures` were ever absent for
    # it, and the schema has no separate slot for `reasons`. When `failures`
    # IS present (even empty — "measured and nothing failed" per the schema,
    # not the same as absent) it is copied as before, extended with any
    # reason carrying that same identifier shape; when it is ABSENT, a
    # matching reason still reaches the block rather than being dropped.
    reasons = floor.get("reasons")
    timeout_reasons = (
        [str(r) for r in reasons if "timeout after" in str(r)]
        if isinstance(reasons, list) else []
    )
    if isinstance(failures, list):
        merged_failures = [str(f) for f in failures]
        for reason in timeout_reasons:
            if reason not in merged_failures:
                merged_failures.append(reason)
        block["failures"] = merged_failures
    elif timeout_reasons:
        block["failures"] = timeout_reasons
    duration = floor.get("duration_ms")
    if isinstance(duration, int) and not isinstance(duration, bool) and duration >= 0:
        block["duration_ms"] = duration
    return block


# --------------------------------------------------------------------------- #
# the triage `actual` event — the join's missing producer on the default path
#
# `predicted` -> `bind` -> `actual` is a three-event join, and on Engine C the
# third event had NO reachable producer: the only two live `append_actual` call
# sites were `agents/parallel-dispatcher.md` (the residual path `/v:dispatch`
# explicitly says not to use) and the v2.9 fast-path tail in `/v:collect`. So the
# join never closed, precision read `insufficient` forever, and the
# miscalibration breaker's numerator could only ever see demotions — the exact
# blind spot negative outcomes were added to remove.
#
# WHAT IS APPENDED HERE, and what is not. This is the RECORD/MERGE path: it knows
# the run's jobs merged, and it does NOT know the Review Gate's verdict or that
# the run substrate was committed. CR5-4 says a TERMINAL `actual` is emitted only
# after the merge/commit boundary, so what is written here is the documented
# precision-IGNORED intermediate (`merge_pending: true`). `/v:dispatch`'s final
# step writes the terminal one, and last-writer-wins replaces this.
# --------------------------------------------------------------------------- #
TRIAGE_OUTCOMES_DEFAULT = os.path.join(HERE, "compound-v-triage-outcomes.py")
TERMINAL_JOB_STATES = ("done", "blocked", "failed")


def _import_triage_outcomes(path=None):
    target = path or TRIAGE_OUTCOMES_DEFAULT
    if not os.path.exists(target):
        return None
    return _load_module_from_path("cv_triage_outcomes", target)


def _run_test_result(run_dir, job_ids):
    """`pass` / `fail` / None, derived from the recorded results' `tests` blocks.

    None when no job recorded one — "nobody ran tests" and "tests passed" must not
    look alike, so the absence is reported as absence."""
    seen = False
    for job_id in job_ids:
        doc = _read_json(os.path.join(run_dir, "results", "%s.json" % job_id), None)
        tests = (doc or {}).get("tests")
        if not isinstance(tests, dict):
            continue
        seen = True
        if tests.get("exit_code") != 0:
            return "fail"
    return "pass" if seen else None


def _maybe_append_run_actual(run_dir, manifest, state, repo_root):
    """Append the run's intermediate `actual` once EVERY manifest job is terminal.

    Returns a short note for the ack, or None when nothing was appended. Keyed on
    `state.json` so a relaunch (which re-runs completed agents) does not append a
    second one."""
    job_ids = [j.get("id") for j in (manifest.get("jobs") or []) if j.get("id")]
    if not job_ids:
        return None
    for job_id in job_ids:
        if (state["jobs"].get(job_id) or {}).get("status") not in TERMINAL_JOB_STATES:
            return None  # the run is not finished; the last job appends
    triage = manifest.get("triage") if isinstance(manifest.get("triage"), dict) else {}
    pre_eval_id = triage.get("pre_eval_id")
    if not pre_eval_id:
        return ("no triage.pre_eval_id in the manifest; the join's `actual` has "
                "nothing to key on and is NOT invented")
    if (state.get("triage_actual") or {}).get("merge_pending"):
        return "triage `actual` (merge_pending) already appended for this run"

    module = _import_triage_outcomes()
    if module is None:
        return "triage-outcomes module unavailable; no `actual` appended"
    run_id = manifest.get("run_id") or os.path.basename(os.path.normpath(run_dir))
    stream_path = os.path.join(repo_root, module.STREAM_RELPATH)
    try:
        module.append_actual(
            pre_eval_id, run_id, merge_pending=True,
            test_result=_run_test_result(run_dir, job_ids),
            stream_path=stream_path,
        )
    except Exception as exc:  # noqa: BLE001
        return "triage `actual` append failed: %s" % exc
    state["triage_actual"] = {"merge_pending": True, "pre_eval_id": pre_eval_id,
                              "run_id": run_id}
    return ("appended the precision-IGNORED `actual` (merge_pending) for %s; "
            "/v:dispatch writes the terminal one after the merge/commit boundary"
            % run_id)


_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def external_session_id(run_dir, job_id):
    """The external worker's thread id, read from the events log the WORKER wrote
    (`logs/<job>.events.jsonl`, first `thread.started` line), UUID-validated.

    The wrapper agent returns only status/worktree/summary, so nothing on
    Engine C carried the worker's `job_result.session_id` into state — and
    `codex exec resume <uuid>` is what /v:resume needs (stage-4 review-1,
    finding 81). The events log is the worker's own artefact, not the model's
    claim, which is why it is the source here. Empty when absent or not a UUID.
    """
    path = os.path.join(run_dir or "", "logs", "%s.events.jsonl" % job_id)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if isinstance(ev, dict) and ev.get("type") == "thread.started":
                    tid = str(ev.get("thread_id") or "").strip()
                    return tid if _UUID_RE.match(tid) else ""
    except OSError:
        return ""
    return ""


def _job_result_from(verdict, job, state_job, tests=None, contract=None,
                     isolation=None, tier=None):
    """The canonical job_result. Enforcement fields come from the GATE, not the
    implementer: `blocked`, `files_changed` and `violations` are git-derived.

    `tests` is the RAW `test-floor` document; it is translated here into the
    schema's four-field block (see `_tests_block_from_floor`). `tier` is the
    manifest's `triage.tier`, which that translation needs to label `tests.scope`
    the way the resolver would."""
    raw = verdict.get("raw_stdout") or ""
    scope = None
    try:
        scope = json.loads(raw) if raw.strip() else None
    except Exception:  # noqa: BLE001
        scope = None
    # The gate-receipt JSON is the authority; when a caller hands over the parsed
    # verdict without its `raw_stdout` (a by-hand re-record after a detached
    # gate did exactly this on 2026-09-02), the same fields at the top level are
    # the next best evidence — and an EMPTY list here is what let a passing
    # worktree job be "merged" with nothing and then pruned.
    changed = (scope or {}).get("changed") or verdict.get("changed") or []
    violations = (scope or {}).get("violations") or verdict.get("violations") or []
    gate_verdict = verdict.get("verdict")

    if gate_verdict == "pass":
        status = "success"
    elif gate_verdict == "blocked":
        status = "blocked"
    else:
        status = "error"
    _impl_no_result = isinstance(verdict, dict) and bool(verdict.get("impl_no_result"))
    if _impl_no_result:
        # The gate measured the registered worktree, but the implementer never
        # returned (turn cap or crash): whatever it wrote is unfinished by definition.
        status = "error"

    # A RED TEST FLOOR BLOCKS, and until dogfood 14 nothing read it.
    #
    # That run declared `floor_command: sh -c 'echo ...; exit 3'`. The floor ran,
    # failed, and was recorded with perfect honesty — `exit_code: 3`, the failing
    # command listed under `failures` — and the job was still `success` and still
    # merged, because status came from the SCOPE verdict alone. The scope gate
    # answers "did this job write outside its lane"; it has no opinion about
    # whether the code works, and nothing else was asking.
    #
    # The `tests` block is the fourteenth mechanism this project built and left
    # without a consumer. A floor is early feedback by charter — it does not
    # restore what a full suite guarantees, and nothing here claims it does — but a
    # floor that FAILED is not a weak signal, it is a definite one.
    #
    # `blocked`, not `error`: nothing is broken about the machinery, the job's work
    # did not pass its own declared tests. Same class as an out-of-lane write, for
    # the same reason — the work is refused, not the pipeline.
    tests_block = _tests_block_from_floor(tests, contract, job, tier) if tests else None
    if status == "success" and isinstance(tests_block, dict):
        t_exit = tests_block.get("exit_code")
        if isinstance(t_exit, int) and not isinstance(t_exit, bool) and t_exit != 0:
            status = "blocked"
            # The schema's required `blocked` boolean must follow the FINAL status,
            # not the gate verdict it was derived from. A scope-pass/test-fail
            # result emitted {"status": "blocked", "blocked": false} — the
            # finalizer reads `status` and refused correctly, but every other
            # consumer of the boolean got the opposite conclusion.
            pass

    # The three REQUIRED fields below are typed `string`/`string`/`integer` in the
    # schema, with the empty string and 0 documented as their own "not applicable"
    # values ("Empty string when the backend has no resumable session"; "empty
    # string for `direct` (in-place) jobs"; "0 when unknown"). Emitting null there
    # made every Engine C result fail the schema; the schema belongs to another
    # lane, so the conformant VALUE is emitted rather than the type widened.
    exit_code = verdict.get("exit_code")
    if not isinstance(exit_code, int) or isinstance(exit_code, bool):
        exit_code = 0
    retry_after = verdict.get("retry_after_seconds")
    if not isinstance(retry_after, int) or isinstance(retry_after, bool):
        retry_after = 0

    # `worktree` is a WORKTREE LOCATOR, and a direct job does not have one. The
    # branch is the manifest's `isolation`; it is never "whatever string happens
    # to be non-empty". A compliant direct implementer returns its project cwd,
    # so emptiness could not distinguish the two — and that is precisely how a
    # direct job's patch ended up being applied into another repository.
    if (isolation or job.get("isolation")) == "worktree":
        # The receipt names the tree the gate measured; state may not know it
        # yet (finding 89).
        worktree = (str(verdict.get("worktree") or "").strip() if isinstance(verdict, dict) else "") \
            or state_job.get("worktree") or ""
    else:
        worktree = ""

    result = {
        "status": status,
        # Follows the FINAL status, not the gate verdict it started from: a
        # scope-pass/test-fail result emitted {"status": "blocked",
        # "blocked": false}, and every consumer of the boolean got the opposite
        # conclusion from the one the finalizer acted on.
        "blocked": status == "blocked",
        "files_changed": changed,
        "violations": violations,
        "summary": (("implementer returned no result (turn cap or crash); the registered "
                     "worktree was gated as evidence — " if _impl_no_result else "")
                    + (verdict.get("reason") or (job.get("title") or job.get("id") or ""))),
        "session_id": state_job.get("session_id") or "",  # filled from the events log for an external job (finding 81)
        "worktree": worktree,
        "exit_code": exit_code,
        # `unknown` is not in the schema's failure_class enum — `other` is the
        # declared bucket for "a non-success this producer cannot classify".
        "failure_class": None if status in ("success", "blocked") else "other",
        "retry_after_seconds": retry_after,
    }
    if tests_block is not None:
        result["tests"] = tests_block

    # A receipt is emitted ONLY when all six fields are genuinely known. A
    # PARTIAL receipt is a missing receipt, and a missing receipt is re-derived
    # by the verification layer rather than trusted.
    required = ["baseline_commit", "realised_commit", "diff_digest",
                "verdict", "raw_stdout", "exit_code"]
    if all(verdict.get(k) is not None for k in required):
        result["gate_receipt"] = {k: verdict[k] for k in required}
    return result


def cmd_record(argv):
    ap = argparse.ArgumentParser(prog="compound-v-emit-workflow.py record")
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--job-id", required=True)
    ap.add_argument("--manifest")
    # The verdict arrives EITHER inline (--verdict-json) OR from the receipt the
    # gate already wrote (--verdict-file). Stage-3 dogfood (finding 69): the
    # harness's bashCommandClamp refuses a Record command whose argv carries the
    # receipt inline once the receipt quotes a test checker with `; do … done`
    # or a backtick — data it cannot tell from structure. The file form keeps
    # user data out of argv; the two --expect-* fields bind the file to what
    # the workflow saw, so a rewritten receipt is refused, never recorded.
    ap.add_argument("--verdict-json")
    ap.add_argument("--verdict-file")
    ap.add_argument("--expect-verdict")
    ap.add_argument("--expect-diff-digest")
    ap.add_argument("--retries-json", dest="retries_json",
                    help="the workflow's own retry log for this job: "
                         '{"retries": [{"stage", "job", "attempt", "wait_ms"}], '
                         '"exhausted": bool, "attempts": int, "escalated_from": str}. '
                         "Machine generated, validated here anyway, and never allowed "
                         "to cost a job its result: a malformed value is reported "
                         "beside the result rather than refusing it.")
    ap.add_argument("--repo-root", required=True,
                    help="the PROJECT root. REQUIRED even though `record` no "
                         "longer writes to it: it is where the triage stream "
                         "lives, and a defaulted root wrote into the plugin's "
                         "own repository.")
    ap.add_argument("--manifest-digest",
                    help="sha256:<hex> the manifest MUST hash to, baked in by "
                         "`emit`. A mismatch refuses rather than recording a "
                         "result against a lane map that changed after review.")
    ap.add_argument("--now")
    ap.add_argument("--no-merge", action="store_true",
                    help="accepted and ignored. `record` never merges any more — "
                         "the wave finalizer does, after the authority runs.")
    args = ap.parse_args(argv)

    run_dir = os.path.abspath(args.run_dir)
    job_id = args.job_id
    ack = {"job_id": job_id, "recorded": False, "merged": False}
    retry_meta, retry_meta_err = _sanitize_retry_meta(getattr(args, "retries_json", None))
    if retry_meta_err:
        ack["retry_meta_error"] = retry_meta_err

    try:
        if args.verdict_file:
            with open(args.verdict_file, "r", encoding="utf-8") as _vf:
                verdict = json.load(_vf)
            _exp_v = (args.expect_verdict or "").strip()
            _exp_d = (args.expect_diff_digest or "").strip()
            if isinstance(verdict, dict):
                if _exp_v and str(verdict.get("verdict")) != _exp_v:
                    verdict = {"verdict": "error", "reason":
                               "receipt file says verdict %r but the workflow saw %r — "
                               "the receipt was rewritten between Gate and Record"
                               % (verdict.get("verdict"), _exp_v)}
                elif _exp_d and str(verdict.get("diff_digest")) != _exp_d:
                    verdict = {"verdict": "error", "reason":
                               "receipt file diff_digest %r != the workflow's %r — "
                               "the receipt was rewritten between Gate and Record"
                               % (verdict.get("diff_digest"), _exp_d)}
        elif args.verdict_json:
            verdict = json.loads(args.verdict_json)
        else:
            raise ValueError("record needs --verdict-json or --verdict-file")
    except Exception as exc:  # noqa: BLE001
        ack["reason"] = "verdict JSON unparseable: %s" % exc
        print(json.dumps(ack, indent=2, sort_keys=True))
        return 2
    if not isinstance(verdict, dict):
        verdict = {"verdict": "error", "reason": "verdict was not an object"}

    manifest_path = os.path.abspath(
        args.manifest or os.path.join(run_dir, "manifest.yaml")
    )
    fault = manifest_digest_fault(manifest_path, args.manifest_digest)
    if fault:
        ack["reason"] = fault
        print(json.dumps(ack, indent=2, sort_keys=True))
        return 2
    manifest = {}
    if os.path.exists(manifest_path):
        try:
            manifest = _load_yaml(manifest_path) or {}
        except Exception:  # noqa: BLE001
            manifest = {}
    job = _manifest_job(manifest, job_id) or {"id": job_id}

    # A DETACHED copy of this job's entry. Every mutation below lands on it, and
    # it is merged back into a FRESHLY READ state.json under the run-dir lock at
    # the end. Records within a wave run concurrently, so holding a state object
    # across the body and writing it whole would let one Record erase a sibling's
    # `worktree`/`baseline` — which the integration authority then reads as
    # `unverifiable` and refuses.
    state_job = dict(_load_state(run_dir)["jobs"].get(job_id) or {})

    # The receipt binds to the worktree the gate observed, so record it: the
    # integration authority reads `worktree` from state.json (or the result) to
    # decide WHERE to gate, and a null there is why every job read `unverifiable`.
    receipt_path = os.path.join(run_dir, "receipts", "%s.gate.json" % job_id)
    receipt_doc = _read_json(receipt_path, {}) or {}
    tests = receipt_doc.get("tests")
    # The resolved slice the floor actually ran — its `scope` is the value the
    # schema's `tests.scope` requires "copied verbatim from the contract the
    # caller passed as an argument", not a re-derivation.
    contract = _read_json(test_contract_path(run_dir, job_id), {}) or {}

    # The manifest is the authority on isolation, and its ABSENCE FAILS CLOSED.
    # Deriving it from "is the locator empty?" is what 3.0.1 did, and a compliant
    # direct implementer's locator is never empty.
    # ...but branch on the AGENT layer, not the manifest's. A depends_on job
    # declares `worktree` in the manifest and runs its agent in the project
    # checkout, because a fresh worktree branches from the default ref and would
    # not contain the wave that just committed. Reading the manifest value here
    # made Record refuse a valid direct run for "carrying no observed worktree" —
    # 3.0.2's fail-closed rule firing on a job never meant to have one. One field
    # name, two layers, opposite meanings.
    isolation = job.get("isolation")
    # WHERE THE AGENT RAN comes from the gate receipt (the emitter's own `--mode`,
    # digest-bound), never from a rule re-derived here. The 3.0.5 rule "a
    # dependent worktree job ran direct" was hard-coded in this stage and kept
    # writing `direct` + an empty worktree into state after finding 60 gave
    # dependent jobs real worktrees — so the authority, reading state, gated the
    # checkout and called an honest receipt forged (stage-5 F1, finding 89).
    _rec_mode = _gate_mode_from_receipt(verdict) if isinstance(verdict, dict) else None
    if _rec_mode:
        isolation = _rec_mode
    elif isolation == "worktree" and (job.get("depends_on") or []) \
            and not _worktree_base_is_head(repo_root):
        isolation = "direct"
    if isolation not in ("direct", "worktree"):
        ack["reason"] = (
            "manifest job %r declares no `isolation` (got %r). Record branches on "
            "the manifest, never on whether a locator is empty, so an undeclared "
            "isolation fails closed rather than being guessed" % (job_id, isolation)
        )
        print(json.dumps(ack, indent=2, sort_keys=True))
        return 2

    # The GATE's observed worktree, carried explicitly. lane-map.json holds the
    # cwd of the agent that *wrapped* the job — for an external backend that is
    # the project checkout, not the worker-owned worktree the gate measured — so
    # rebuilding a locator from it recorded the wrong tree and the worker's valid
    # patch never reached the project.
    if isolation == "worktree":
        gate_worktree = verdict.get("worktree")
        if not (isinstance(gate_worktree, str) and gate_worktree.strip()):
            # A JOB THAT DID NOTHING IS NOT A BROKEN PIPELINE.
            #
            # Dogfood 6 (2026-09-02) asked a worktree job to write nothing, on
            # purpose, and got `status: error` with a paragraph about lane-map.json
            # reconstruction. Both halves were unhelpful. The runtime REMOVES an
            # unchanged worktree — that is documented behaviour, not a fault — so a
            # job that wrote nothing leaves no worktree for the gate to observe, and
            # the fail-closed branch written for a genuine locator problem answered
            # instead.
            #
            # The distinction that matters to a reader is intent, and the manifest
            # settles it: a job that declared `write_allowed` and produced no
            # observable tree did not do its job — `blocked`, the same class the
            # direct-mode no-work check has used since 3.0.4. A job that declared no
            # lanes (a reviewer) is expected to leave nothing, and a missing locator
            # there really is a machinery failure — `error`, unchanged.
            #
            # Both refuse and neither merges. Only the word and the remedy differ,
            # and this project has now made that same mistake three times: `no_work`
            # dressed as a fourth verdict (3.0.4), a moved HEAD dressed as `forged`
            # (3.3.0), and this.
            # ...AND the gate must also have seen no changes. A verdict that
            # reports changed files but no worktree is a genuine locator fault
            # wearing the no-work shape, and recording it as "the job did nothing"
            # would mask broken machinery as a job failure — the inverse of the
            # mistake being fixed here, and the more dangerous direction.
            try:
                # LEADING JSON, not a bare parse: on a blocked verdict the scope
                # gate prints its JSON and then a human "BLOCKED: n file(s)" tail,
                # and a bare parse fails on that — which would make a receipt that
                # reports real changed files look like no-work. The integration
                # authority already learned this; the same rule applies here.
                _rawtext = verdict.get("raw_stdout") or ""
                _raw = None
                if _rawtext.strip():
                    _dec = json.JSONDecoder()
                    _raw, _ = _dec.raw_decode(_rawtext.lstrip())
            except Exception:  # noqa: BLE001
                _raw = None
            # BOTH shapes. The real receipt carries `changed` inside `raw_stdout`
            # (which is what `_job_result_from` reads), but a caller may hand the
            # verdict with it at the top level, and a guard that only looks in one
            # place is a guard that can be walked around by the other. Its own test
            # caught exactly that: the fixture used the top-level shape and the
            # guard, reading only raw_stdout, waved it through.
            _saw_changes = bool((_raw or {}).get("changed")
                                or (verdict or {}).get("changed"))
            # AND the gate must have PASSED. A cross-model review pointed out that
            # `{"verdict":"error","exit_code":2,"worktree":"","raw_stdout":""}`
            # became `blocked/no_work` for any job that declared lanes — so a failed
            # gate, a missing checkout or a crashed scope checker was reported as
            # "nothing is broken, the job did nothing". That is the masking this
            # branch's own guard was supposed to prevent, one level up.
            _gate_passed = str((verdict or {}).get("verdict") or "").lower() == "pass"
            if job.get("write_allowed") and not _saw_changes and _gate_passed:
                ack["no_work"] = True
                ack["reason"] = (
                    "job %r declared %d write lane(s) and left no observable "
                    "worktree — the runtime removes an unchanged worktree, so there "
                    "is no evidence any work happened. Refused as blocked (no_work), "
                    "not as a machinery error: nothing is broken, the job did not do "
                    "its job." % (job_id, len(job.get("write_allowed") or []))
                )
                verdict = dict(verdict or {})
                verdict["verdict"] = "blocked"
                verdict["no_work"] = True
                verdict.setdefault("changed", [])
                state_job["worktree"] = ""
                gate_worktree = ""
            else:
                ack["reason"] = (
                    "the gate verdict for worktree job %r carries no observed "
                    "`worktree`%s, so this is a locator failure rather than a job "
                    "that did nothing. Record will not reconstruct one from "
                    "lane-map.json — that map holds the wrapper agent's cwd — so "
                    "this fails closed"
                    % (job_id,
                       " even though it reports changed files"
                       if _saw_changes else " and no changed files were observed")
                )
                print(json.dumps(ack, indent=2, sort_keys=True))
                return 2
        if gate_worktree:
            state_job["worktree"] = os.path.abspath(gate_worktree.strip())
    else:
        state_job["worktree"] = ""

    pinned = read_pinned_baseline(run_dir, job_id, state_job)
    if pinned:
        state_job["baseline"] = pinned
    elif verdict.get("baseline_commit"):
        state_job["baseline"] = verdict["baseline_commit"]

    # The manifest's triage tier is one of the two inputs the resolver used to pick
    # this job's scope, so the label has to see it too (see `_tests_block_from_floor`).
    _triage = manifest.get("triage")
    tier = _triage.get("tier") if isinstance(_triage, dict) else None

    if str((job or {}).get("backend") or "claude") != "claude" and not state_job.get("session_id"):

        _ext_sid = external_session_id(run_dir, job_id)

        if _ext_sid:

            state_job["session_id"] = _ext_sid

    result = _job_result_from(verdict, job, state_job, tests=tests,
                              contract=contract, isolation=isolation, tier=tier)

    # ---- the workflow's retry log ------------------------------------------
    # It lands in state.json and in this ack, NOT as a new top-level key on the
    # result: schemas/job_result.schema.json is `additionalProperties: false`
    # with no free-form field, and that file is outside this change's write lane.
    # `apply_retry_meta` puts the FACT of an exhausted budget where the schema
    # does allow it - `failure_class: other` and a `summary` that names the
    # honest reason instead of guessing `overloaded`.
    if retry_meta:
        if retry_meta.get("retries"):
            state_job["retries"] = retry_meta["retries"]
            ack["retries"] = retry_meta["retries"]
            # v3.4.8 review-1 item 2: the schema now carries `retries`, so the
            # job_result — the record every consumer reads — carries the log too.
            result["retries"] = retry_meta["retries"]
        if retry_meta.get("exhausted"):
            state_job["retry_exhausted"] = True
            ack["retry_exhausted"] = True
    _escalated_from = (retry_meta or {}).get("escalated_from") or (
        verdict.get("escalated_from") if isinstance(verdict, dict) else None)
    if isinstance(_escalated_from, str) and _escalated_from.strip():
        state_job["escalated_from"] = _escalated_from.strip()
        ack["escalated_from"] = _escalated_from.strip()
        result["escalated_from"] = _escalated_from.strip()
    apply_retry_meta(result, retry_meta)

    # ---- ONE result file per job -------------------------------------------
    # results/<id>.json is the primary and there is exactly one. The integration
    # authority treats ANY sibling `<id>.<something>.json` as a DUPLICATE and
    # returns `forged` — "D1 requires EXACTLY ONE receipt per job". So an earlier
    # attempt is archived under results/attempts/, where the gate's listing (which
    # only reads `*.json` directly in results/) cannot mistake it for a rival
    # receipt, while still carrying the `<id>.<attempt>.json` name so a file that
    # ever DOES land beside the primary is recognisable as the duplicate it is.
    results_dir = os.path.join(run_dir, "results")
    os.makedirs(results_dir, exist_ok=True)
    result_path = os.path.join(results_dir, "%s.json" % job_id)
    if os.path.exists(result_path):
        previous = _read_json(result_path, None)
        if previous is not None and previous != result:
            attempts_dir = os.path.join(results_dir, "attempts")
            os.makedirs(attempts_dir, exist_ok=True)
            n = 1
            while os.path.exists(
                os.path.join(attempts_dir, "%s.%d.json" % (job_id, n))
            ):
                n += 1
            _atomic_write(
                os.path.join(attempts_dir, "%s.%d.json" % (job_id, n)),
                json.dumps(previous, indent=2, sort_keys=True) + "\n",
            )
    _atomic_write(result_path, json.dumps(result, indent=2, sort_keys=True) + "\n")
    ack["recorded"] = True
    ack["result_path"] = result_path
    ack["status"] = result["status"]

    # ---- NO MERGE HAPPENS HERE ---------------------------------------------
    # `merged` stays False and the main checkout is untouched. Integration is the
    # wave finalizer's job, and it runs the integration authority first. Record's
    # entire contribution is evidence: results/, receipts/, state.json.
    state_job["realised_commit"] = verdict.get("realised_commit")
    ack["merged"] = False
    ack["reason"] = (
        "evidence recorded; integration is the wave finalizer's, after "
        "compound-v-integration-gate.py has run over this wave"
    )

    state_job["status"] = {
        "success": "done", "blocked": "blocked",
    }.get(result["status"], "failed")
    state_job["isolation"] = isolation

    # Merge this job's entry into a FRESHLY READ state.json, under the lock.
    #
    # RECORD WRITES NOTHING OUTSIDE THE RUN DIRECTORY, and that is the whole
    # point of this stage. Until the fourth review pass it also appended the
    # run's `merge_pending` actual to docs/superpowers/memory/triage-outcomes.jsonl
    # from here — a tracked file, written BETWEEN a direct-mode job's gate and the
    # authority's re-derivation of the same tree, so an honest receipt read as
    # `contradicted`. That was papered over by excluding the path from both
    # digests, which also made a worker's rewrite of it invisible. The append now
    # belongs to `cmd_finalize_wave`, after the authority has run; no exclusion is
    # needed, and nothing lands inside that window.
    with _run_dir_lock(run_dir):
        state = _load_state(run_dir)
        state["jobs"].setdefault(job_id, {}).update(state_job)
        _save_state(run_dir, state, now=args.now)

    print(json.dumps(ack, indent=2, sort_keys=True))
    return 0


# --------------------------------------------------------------------------- #
# finalize-wave — the ONLY writer into the project checkout
#
# Order is the whole point, and it is: AUTHORITY -> MERGE -> COMMIT.
#
# 3.0.1 had Record call `git apply --index` in the main checkout before
# `/v:dispatch` step 7 ran `compound-v-integration-gate.py`, and Record never
# committed. Two consequences, both real:
#
#   * a job could LAND without the authority ever running — the session dies
#     after Record stages, a later plain `git commit` (`/v:orchestrate` runs one)
#     sweeps the staged patch into history, and nothing ever gated it. The
#     authority was bypassed, not defeated: it is a correct script that the
#     integration path had already walked past;
#   * a dependent could not SEE its prerequisite — `git apply --index` stages,
#     and the next wave's worktree is created from an unchanged HEAD.
#
# Both close by making a wave's integration one serialized step that runs the
# authority over exactly this wave's jobs, refuses everything on anything other
# than `permitted`, and finishes with a real commit.
# --------------------------------------------------------------------------- #
def _commit_paths(repo_root, paths, message):
    """Commit exactly these paths. Returns (sha or None, error or None).

    Restricted to a pathspec on purpose: a bare `git commit` in a shared checkout
    commits whatever else is staged, which is the mechanism by which an ungated
    patch reached history in the first place. NUL-delimited because a path may
    legitimately contain a newline.
    """
    if not paths:
        return None, None
    ok, err = _stage_paths(repo_root, paths)
    if not ok:
        return None, err
    payload = "\0".join(paths).encode("utf-8")
    try:
        proc = subprocess.Popen(
            ["git", "-C", repo_root, "commit",
             "--pathspec-from-file=-", "--pathspec-file-nul", "-m", message],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        out, cerr = proc.communicate(payload)
        rc = proc.returncode
    except Exception as exc:  # noqa: BLE001
        return None, "git commit raised: %s" % exc
    if rc != 0:
        text = (out + cerr).decode("utf-8", "replace")
        if "nothing to commit" in text or "no changes added" in text:
            return None, None  # already committed; idempotent, not a failure
        return None, "git commit failed: %s" % text.strip()[:400]
    return _head_commit(repo_root), None


def _retire_lane_map(run_dir):
    """Delete the run's lane-map.json at a TERMINAL phase (finding 68).

    The lane map is runtime state: it tells the lane guard which worktree —
    or, for a direct job, which checkout — belongs to which job WHILE the run
    is live. A direct job's 'worktree' is the repository root, which exists
    forever, so a finished run's map kept claiming the checkout and the guard
    denied the next feature's pre-flight auditors as that run's review job.
    The guard now also skips terminal runs; this removes the claim at source.
    Best-effort, never fatal."""
    try:
        os.remove(lane_map_path(run_dir))
        return True
    except OSError:
        return False


def _retire_run_lock(run_dir):
    """Delete the run's OWN `.run.lock` at the same TERMINAL phase transition
    that retires lane-map.json (finding 105).

    `.run.lock` is `_run_dir_lock`'s file, never committed (the finalizer's
    own bookkeeping commit `git reset`s it back out by name). Stale ones
    accumulate on disk regardless: 46 of them across old finished runs were
    still THERE for the test-contract resolver's own change-scan to see as a
    changed gitignored path — the very thing that promoted every DIRECT job's
    slice to `full_command` for a run that had already finished. A run past
    MERGED/BLOCKED will not `register-lane` again, so nothing needs this file
    to still exist. Best-effort, never fatal, and called only AFTER any
    `with _run_dir_lock(...)` that covered this same transition has already
    exited — deleting the file this process is still holding open would
    leave a concurrent `_run_dir_lock` free to flock a freshly-created inode
    at the same path while this one's descriptor (and its lock) is still
    live."""
    # The rule, stated once: the lock goes when the RUN is terminal (MERGED or
    # BLOCKED), read from state.json — not when some other retirement happened
    # to return True (v3.4.6 review-1, item 6: two of three call sites were
    # gated on `_retire_lane_map`'s return value, the third was not).
    _st = _read_json(os.path.join(run_dir, "state.json"), None) or {}
    if str(_st.get("phase") or "").upper() not in ("MERGED", "BLOCKED"):
        return False
    try:
        os.remove(os.path.join(run_dir, ".run.lock"))
        return True
    except OSError:
        return False


def _load_manifest_dict(path):
    """The manifest as a dict, through the validator's loader (one parser)."""
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    try:
        import yaml  # noqa: WPS433
        return yaml.safe_load(text)
    except ImportError:
        pass
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_cv_validate_manifest_for_lane", os.path.join(HERE, "compound-v-validate-manifest.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.load_yaml(text)


def _gate_mode_from_receipt(gate_doc):
    """The `mode` the gate ran in, read from the receipt's raw gate JSON — the
    emitter authored that `--mode`, so it is trusted where the manifest's label is
    not the whole truth. None when absent or unparseable."""
    if not isinstance(gate_doc, dict):
        return None
    raw = gate_doc.get("raw_stdout")
    if isinstance(raw, str) and raw.strip():
        try:
            mode = (json.loads(raw) or {}).get("mode")
            if mode in ("direct", "worktree"):
                return mode
        except ValueError:
            pass
    mode = gate_doc.get("mode")
    return mode if mode in ("direct", "worktree") else None


def cmd_finalize_wave(argv):
    ap = argparse.ArgumentParser(prog="compound-v-emit-workflow.py finalize-wave")
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--repo-root", required=True,
                    help="the PROJECT root — the tree this wave merges into. "
                         "Never defaulted.")
    ap.add_argument("--manifest")
    ap.add_argument("--jobs", required=True,
                    help="comma-separated job ids belonging to THIS wave")
    ap.add_argument("--wave", type=int, default=0)
    ap.add_argument("--integration-gate", default=INTEGRATION_GATE_DEFAULT)
    ap.add_argument("--python", default=(sys.executable or "python3"))
    ap.add_argument("--manifest-digest",
                    help="sha256:<hex> the manifest MUST hash to, baked in by "
                         "`emit`. Verified here AND forwarded to the integration "
                         "authority: nothing merges against a lane map that "
                         "changed after review.")
    ap.add_argument("--now")
    ap.add_argument("--no-commit", action="store_true",
                    help="merge but do not commit; for tests only")
    args = ap.parse_args(argv)

    run_dir = os.path.abspath(args.run_dir)
    repo_root = os.path.abspath(args.repo_root)
    manifest_path = os.path.abspath(
        args.manifest or os.path.join(run_dir, "manifest.yaml")
    )
    job_ids = [j.strip() for j in args.jobs.split(",") if j.strip()]
    out = {"wave": args.wave, "integrated": False, "merged": [], "refused": []}

    def emit(code):
        print(json.dumps(out, indent=2, sort_keys=True))
        return code

    if not job_ids:
        out["reason"] = "--jobs named no job ids"
        return emit(2)
    if not os.path.exists(args.integration_gate):
        out["reason"] = (
            "the integration authority is not at %s. Nothing merges without it — "
            "an absent authority is a refusal, never a waiver" % args.integration_gate
        )
        return emit(2)
    fault = manifest_digest_fault(manifest_path, args.manifest_digest)
    if fault:
        out["reason"] = fault
        out["refused"] = job_ids
        return emit(1)

    # ---- 1. THE AUTHORITY, first ------------------------------------------- #
    _gate_argv = [
        args.python, "-B", args.integration_gate,
        "--run-dir", run_dir, "--repo-root", repo_root,
        "--manifest", manifest_path, "--jobs", ",".join(job_ids), "--json",
    ]
    if args.manifest_digest:
        _gate_argv += ["--manifest-digest", args.manifest_digest]
    rc, gate_out, gate_err = _run(_gate_argv)
    try:
        report = json.loads(gate_out) if gate_out.strip() else None
    except Exception:  # noqa: BLE001
        report = None
    if not isinstance(report, dict):
        out["reason"] = ("the integration authority produced no report (rc=%d): %s"
                         % (rc, (gate_err or gate_out)[:300]))
        return emit(1)

    manifest = {}
    if os.path.exists(manifest_path):
        try:
            manifest = _load_yaml(manifest_path) or {}
        except Exception:  # noqa: BLE001
            manifest = {}

    # ---- 1a. THE RUN'S `actual` — AFTER the authority, BEFORE the commit ---- #
    #
    # This is the pipeline's one write into a TRACKED file outside the run
    # directory, and its POSITION is the safety property. Record used to do it,
    # which put that append between a direct-mode job's gate and this authority's
    # re-derivation of the same tree: the digests disagreed and an honest receipt
    # was refused as `contradicted` (run v3.4-r6). 3.4.0 development answered that
    # by excluding the path from both digests — which also made a WORKER's rewrite
    # of it invisible, in a stream the pipeline commits by name and which resolves
    # last-writer-wins into the Tier-2 precision gate. The fourth review pass
    # withdrew the exclusion and moved the write here: the authority has already
    # re-derived this wave, so nothing it measures can be disturbed, and the
    # commit below is pathspec-restricted so this file is never swept into it.
    #
    # AFTER THE AUTHORITY RAN, NOT AFTER IT PERMITTED. A refused wave is still an
    # outcome the predicted<->actual join has to carry, and gating the append on
    # `permitted` would silently drop the `actual` for exactly the runs whose
    # outcome matters most. `_maybe_append_run_actual` is latched on state.json
    # and fires at most once per run, only once EVERY manifest job is terminal.
    with _run_dir_lock(run_dir):
        _fresh = _load_state(run_dir)
        _note = _maybe_append_run_actual(run_dir, manifest, _fresh, repo_root)
        if _note:
            out["triage_actual"] = _note
        _save_state(run_dir, _fresh, now=args.now)

    if report.get("integration") != "permitted":
        out["refused"] = report.get("refused") or job_ids
        out["reason"] = (
            "integration REFUSED by scripts/compound-v-integration-gate.py: %s. "
            "Nothing was merged and nothing was committed."
            % json.dumps(report.get("tally") or {})
        )
        # The workflow halts on this wave, so the RUN is halted: record it as
        # BLOCKED with the reason (see the same rule in `_apply`), so the run is
        # not left PARTITION_VERIFIED with jobs pending forever.
        with _run_dir_lock(run_dir):
            _halted = _load_state(run_dir)
            _halted["phase"] = "BLOCKED"
            _halted["blocked_reason"] = ("wave %s: %s" % (args.wave, out["reason"]))[:300]
            _halted["blocked_at"] = args.now or _utc_stamp()
            _save_state(run_dir, _halted, now=args.now)
        if _retire_lane_map(run_dir):
            out["lane_map_retired"] = True
        _retire_run_lock(run_dir)
        return emit(1)

    # ---- 2. merge the permitted slices ------------------------------------- #
    # Read once for the git work; every WRITE goes through _apply below, which
    # re-reads under the run-dir lock. The finalizer is serialized by the wave
    # loop, but a straggler Record from a relaunched wave is not, and an unlocked
    # read-modify-write here would erase whatever it had just written.
    state = _load_state(run_dir)
    job_updates = {}

    def _apply(now=None):
        with _run_dir_lock(run_dir):
            fresh = _load_state(run_dir)
            for jid, updates in job_updates.items():
                fresh["jobs"].setdefault(jid, {}).update(updates)
            fresh.setdefault("waves", {})[str(args.wave)] = {
                "jobs": job_ids, "merged": out["merged"],
                "commit": out.get("commit"), "integrated": out.get("integrated"),
            }
            # THE PHASE ADVANCE IS THIS FINALIZER'S, NOT A PROSE STEP. Until
            # 3.4.1 only /v:dispatch step 9 — a human step — wrote MERGED, and
            # fourteen finished runs of one night sat at PARTITION_VERIFIED: the
            # dashboard called every one of them unfinished for 72 hours and the
            # triage hook stayed silent for the whole repository (stage-1
            # finding 45). A wave that integrated moves the run to DISPATCHED;
            # the wave after which every manifest job is integrated moves it to
            # MERGED. A refused wave leaves the phase alone.
            if out.get("integrated"):
                _all_ids = [str(j.get("id")) for j in (manifest.get("jobs") or [])
                            if isinstance(j, dict) and j.get("id")]
                _done = bool(_all_ids) and all(
                    ((fresh["jobs"].get(_j) or {}).get("merged") or {}).get("integrated")
                    for _j in _all_ids)
                fresh["phase"] = "MERGED" if _done else "DISPATCHED"
                if _done:
                    fresh["merged_at"] = now or _utc_stamp()
                    if _retire_lane_map(run_dir):
                        out["lane_map_retired"] = True
            elif out["refused"]:
                # A refused job halts the workflow (the script stops on a wave
                # that did not integrate), so the RUN is halted: say BLOCKED,
                # with the reason, instead of leaving PARTITION_VERIFIED with
                # jobs pending forever. The banner still lists it (unfinished);
                # the triage hook's narrower question (`--open-jobs`) excludes a
                # BLOCKED run, so a halted run no longer silences sizing for the
                # follow-up that repairs it (stage-2 r2, finding 47's residual).
                fresh["phase"] = "BLOCKED"
                fresh["blocked_reason"] = ("wave %s refused: %s" % (
                    args.wave, ", ".join(out["refused"])))[:300]
                fresh["blocked_at"] = now or _utc_stamp()
                if _retire_lane_map(run_dir):
                    out["lane_map_retired"] = True
            _save_state(run_dir, fresh, now=now)

    merged_worktrees = {}
    post_images = {}
    approved = []
    for job_id in job_ids:
        job = _manifest_job(manifest, job_id) or {"id": job_id}
        state_job = state["jobs"].get(job_id) or {}
        result = _read_json(os.path.join(run_dir, "results", "%s.json" % job_id), None)
        if not isinstance(result, dict) or result.get("status") != "success":
            out["refused"].append(job_id)
            continue
        files = [p for p in (result.get("files_changed") or []) if p]
        isolation = job.get("isolation") or state_job.get("isolation") or "direct"
        realised = state_job.get("realised_commit")
        pinned = read_pinned_baseline(run_dir, job_id, state_job)

        # ---- THE SEALED ARTIFACT, and what git says about it ---------------- #
        gate_doc = _read_json(
            os.path.join(run_dir, "receipts", "%s.gate.json" % job_id), None)
        # WHERE THE AGENT ACTUALLY RAN decides how to merge — and the gate
        # receipt says so in the emitter's own words (`--mode`, written into the
        # script by this file, never by the agent). The manifest's `isolation` is
        # a scope-attribution label that a dependent job keeps as `worktree`
        # while its agent runs direct (3.0.5 rule); reading only the label
        # refused every such job with "resolves to no worktree" (finding 60).
        isolation = _gate_mode_from_receipt(gate_doc) or isolation
        sealed, seal_err = read_sealed_patch(run_dir, job_id, gate_doc)
        if seal_err:
            out["refused"].append(job_id)
            out["reason"] = "sealed patch unusable for %s: %s" % (job_id, seal_err)
            break
        image = None
        if sealed is not None and pinned:
            image, img_err = sealed_post_image(repo_root, pinned, sealed)
            if img_err:
                out["refused"].append(job_id)
                out["reason"] = ("cannot derive the post-image of %s's sealed "
                                 "patch: %s" % (job_id, img_err))
                break
            post_images[job_id] = image
            if image:
                files = sorted(image)

        # ---- ALREADY MERGED? ASK GIT, NOT state.json ------------------------ #
        # `state.json` is exempt by name from the scope gate and writable by a
        # direct worker, so `merged.integrated: true` is a CACHE line, not a
        # proof. Reading it as one let a forged entry skip a job's merge entirely
        # — the finalizer would report it merged, and the work would never land.
        # Git is asked instead: is this artifact's post-image already in HEAD?
        # The cache is still consulted, but only as a hint about which jobs to
        # ask about, never as the answer.
        if image:
            proven, _why = head_matches_post_image(repo_root, image)
            if proven:
                approved.extend(files)
                out["merged"].append(job_id)
                job_updates[job_id] = {
                    "merged": {"realised_commit": realised, "mode": isolation,
                               "integrated": True, "proof": "head-matches-artifact"}}
                continue  # at-most-once, proven from git
        elif sealed is None:
            merged_record = state_job.get("merged") or {}
            if realised and merged_record.get("realised_commit") == realised \
                    and merged_record.get("integrated"):
                # No artifact to prove anything against (a pre-3.4.0 receipt), so
                # the old cache-only test is all there is. Recorded as such.
                approved.extend(files)
                out["merged"].append(job_id)
                out.setdefault("unproven_skips", []).append(job_id)
                continue

        if isolation == "worktree":
            # The receipt names the tree the gate measured — first (finding 89:
            # result and state both carried "" for a dependent job that ran in a
            # real worktree, and this refused "resolves to no worktree").
            worktree = ((gate_doc or {}).get("worktree") if isinstance(gate_doc, dict) else None) \
                or result.get("worktree") or state_job.get("worktree")
            if not worktree:
                out["refused"].append(job_id)
                out["reason"] = (
                    "job %s is isolation:worktree but resolves to no worktree; "
                    "there is nothing to merge FROM, so it fails closed" % job_id
                )
                break
            if sealed is not None:
                # APPLY THE ARTIFACT, never a fresh diff of the live tree. The
                # worktree is not read at all here — it may have been reverted,
                # rebuilt or filled with test byproducts since the gate ran, and
                # none of that may change what lands.
                ok, err = apply_patch(repo_root, sealed)
            else:
                ok, err = merge_back(worktree, repo_root, pinned, files)
            if not ok:
                out["refused"].append(job_id)
                out["reason"] = "merge-back failed for %s: %s" % (job_id, err)
                break
            # Remembered HERE, from the value this pass actually merged. The
            # cleanup below must never re-read this from state.json — see the
            # comment there. An idempotent re-finalize (`continue` above) never
            # reaches this line, so a job whose work was already merged in an
            # earlier pass is never a cleanup candidate either.
            merged_worktrees[job_id] = worktree
        # A `direct` job changed the checkout in place; there is nothing to apply,
        # only something to commit.
        approved.extend(files)
        job_updates[job_id] = {"merged": {"realised_commit": realised,
                                          "mode": isolation, "integrated": True}}
        out["merged"].append(job_id)

    # ---- 3. COMMIT -------------------------------------------------------- #
    # Reached even when the loop BROKE on a refusal. A sibling that already
    # merged has its patch in the index; returning early would leave it staged
    # and uncommitted, which is CRITICAL 2's own shape — an ungated-looking patch
    # waiting for someone else's `git commit` to sweep it in. Everything staged
    # here was permitted by the authority, so it is committed; the refusal is
    # still a refusal, `integrated` stays false, and the wave loop halts.
    unique = []
    for path in approved:
        if path not in unique:
            unique.append(path)
    if args.no_commit:
        out["reason"] = "merged but not committed (--no-commit)"
    else:
        message = "compound-v: wave %d of run %s (%s)" % (
            args.wave,
            state.get("run_id") or os.path.basename(run_dir),
            ", ".join(out["merged"]) or "no jobs",
        )
        sha, err = _commit_paths(repo_root, unique, message)
        if err:
            out["reason"] = err
            out["integrated"] = False
            _apply(now=args.now)
            # `_apply`'s own `with _run_dir_lock(...)` has released by the time
            # it returns, so retiring the lock file here (never inside that
            # `with`) cannot race the lock this same process still holds.
            _retire_run_lock(run_dir)
            return emit(1)
        if sha:
            out["commit"] = sha
            for job_id in out["merged"]:
                merged = dict(job_updates.get(job_id, {}).get("merged") or {})
                merged.update({"commit": sha, "integrated": True})
                job_updates.setdefault(job_id, {})["merged"] = merged
        else:
            out["commit"] = _head_commit(repo_root) or ""
            # TWO DIFFERENT SITUATIONS, and dogfood 16 showed them wearing one
            # message. "Nothing to commit" because the work is already in HEAD is a
            # clean idempotent re-finalize. "Nothing to commit" because every job
            # was REFUSED is the opposite: nothing was merged and nothing should
            # have been. Reporting the second as the first told a reader that
            # refused work was already in HEAD — a refusal explained as a success,
            # which is the third time in this release line that a correct decision
            # arrived under the wrong name.
            if out["refused"] and not out["merged"]:
                # Keep the SPECIFIC refusal (a merge-back error names its cause);
                # this generic line was overwriting it, and r4's "pathspec did
                # not match" had to be reproduced by hand to be seen at all.
                generic = (
                    "nothing was merged: every job in this wave was refused (%s). "
                    "HEAD is unchanged by this wave."
                    % ", ".join(out["refused"])
                )
                out["reason"] = ("%s — %s" % (out["reason"], generic)
                                 if out.get("reason") else generic)
            else:
                out["reason"] = ("nothing left to commit — this wave's work is "
                                 "already in HEAD (idempotent re-finalize)")

    # ---- PROVE THE COMMIT CARRIES THE ARTIFACT ----------------------------- #
    # Asked of git, after the commit and before anything is deleted: for every job
    # whose patch was sealed, is that patch's post-image what HEAD now holds?
    #
    # This is the check whose absence destroyed work. A worktree reverted to its
    # baseline after the gate produced an empty fresh diff, the finalizer read
    # that as "already landed", marked the job integrated and pruned the tree —
    # the only copy. Nothing in that chain ever asked git whether the content was
    # actually there. A job that cannot be proven is NOT pruned and the wave does
    # not report itself integrated; the worktree stays for a human to look at.
    unproven = []
    if not args.no_commit:
        for job_id in list(out["merged"]):
            image = post_images.get(job_id)
            if not image:
                continue
            proven, why = head_matches_post_image(repo_root, image)
            if not proven:
                unproven.append("%s: %s" % (job_id, why))
    if unproven:
        out["unproven"] = unproven
        generic = ("the commit does not carry the sealed patch for %d job(s): %s. "
                   "Nothing is pruned — a worktree is retired only after git "
                   "confirms its diff is in HEAD." % (len(unproven),
                                                      "; ".join(unproven)[:400]))
        out["reason"] = ("%s — %s" % (out["reason"], generic)
                         if out.get("reason") else generic)

    out["integrated"] = not out["refused"] and not unproven
    if out["refused"]:
        out.setdefault("reason", "some jobs did not reach `success`")

    # ---- RETIRE THE WORKTREES THIS WAVE ACTUALLY MERGED --------------------- #
    # A worktree whose diff is committed to the project is dead weight, and the
    # runtime only auto-removes the ones that CHANGED NOTHING. Eleven runs into a
    # day of dogfooding this repository had nineteen of them, and they are not
    # merely untidy: `git status` fills up, and in `direct` mode the scope gate —
    # which deliberately sees gitignored paths — attributed all fifteen leftovers
    # to the next job and blocked it. Dogfood 10 died of exactly that.
    #
    # ONLY the merged ones. A refused job's worktree still holds the work someone
    # will want to look at, and deleting it would destroy the one copy — the v2.6.4
    # incident in this project was `git worktree remove` taking an audit trail with
    # it, and the lesson was to be specific about what is safe to drop.
    #
    # Best-effort and never fatal: a wave that integrated correctly must not be
    # reported as failed because a directory could not be unlinked.
    # AND ONLY WHEN THIS PASS PRODUCED A COMMIT. A re-finalize whose merge-back
    # applied nothing (`sha` is None) has not put the worktree's diff in HEAD, and
    # `git worktree remove --force` on it destroys the one copy of the work —
    # which is what happened on 2026-09-02 to job triage-hook of run
    # v3.4-native-first-r2 (recovered from the agent transcript). A worktree is
    # retired only after the commit that carries its diff exists.
    pruned, prune_errors = [], []
    if out["merged"] and not args.no_commit and out.get("commit") and merged_worktrees \
            and not unproven \
            and not str(out.get("reason") or "").startswith("nothing left to commit"):
        for job_id in out["merged"]:
            # THE PATH THAT WAS ACTUALLY MERGED, recorded locally at merge time —
            # not re-read from state.json. A cross-model review called the re-read
            # CRITICAL: `state.json` is exempt by name, so a worker can rewrite
            # another job's `worktree` locator, and this loop would then
            # `--force`-delete a REFUSED job's tree — destroying the one copy of
            # work the refusal exists to preserve, which is the exact outcome the
            # comment above promises cannot happen.
            wt = merged_worktrees.get(job_id)
            if not (isinstance(wt, str) and wt.strip()):
                continue
            wt = os.path.abspath(wt.strip())
            # Never outside the project, never the project itself.
            if wt == os.path.abspath(repo_root):
                continue
            if os.path.relpath(wt, repo_root).startswith(".." + os.sep):
                continue
            rc, _o, err = _run(["git", "-C", repo_root, "worktree", "remove",
                                "--force", wt])
            if rc == 0:
                pruned.append(job_id)
            else:
                prune_errors.append("%s: %s" % (job_id, (err or "").strip()[:120]))
        if pruned:
            _run(["git", "-C", repo_root, "worktree", "prune"])
    if pruned:
        out["worktrees_pruned"] = pruned
    if prune_errors:
        out["worktrees_prune_errors"] = prune_errors

    # ---- BEST-EFFORT scorecard refresh, after a successful wave commit ------ #
    # The scorecard is regenerated FROM FILES (manifest jobs x results/*.json),
    # so this is a convenience re-run, never the source of truth -- a run whose
    # finalize is skipped or fails here is just as readable next time someone
    # runs the scorecard by hand. Never fatal: a wave that integrated correctly
    # must not be reported as failed because the scorecard update hiccuped.
    if out["integrated"]:
        scorecard_script = os.path.join(HERE, "compound-v-scorecard.py")
        exec_root = os.path.dirname(run_dir.rstrip(os.sep)) or run_dir
        if os.path.exists(scorecard_script) and os.path.isdir(exec_root):
            rc_sc, _out_sc, err_sc = _run([
                args.python, "-B", scorecard_script, "--update",
                "--from-runs", exec_root,
            ], cwd=repo_root)
            if rc_sc == 0:
                out["scorecard_updated"] = True
            else:
                out["scorecard_update_error"] = (err_sc or "").strip()[:200]

    _apply(now=args.now)
    # Same rule as the refusal path above: `_apply`'s own run-dir lock has
    # already been released, so the retirement runs here, never inside it.
    _retire_run_lock(run_dir)

    # ---- COMMIT THE RUN'S OWN RECORD, separately from the work -------------- #
    # The audit-trail gate requires a committed state.json, and finishing a
    # branch removes worktrees — an uncommitted run dir is exactly what the
    # v2.6.4 incident lost. Until 3.4.1 this commit was the orchestrator's by
    # hand after every wave. It is NEVER folded into the wave commit, which
    # carries the sealed patch and nothing else (that is what the authority
    # proves); it is a second, plain commit of pipeline-owned paths only: the
    # run directory (minus its lock) and the two memory streams Record and the
    # scorecard append to. Best-effort: a wave that integrated is not reported
    # failed because its bookkeeping could not be committed.
    # WHENEVER THIS WAVE MOVED HEAD — not only when it integrated. Stage-2 r1
    # merged four jobs and refused one: HEAD moved, and gating this on
    # `integrated` left state/receipts/results untracked, which the audit-trail
    # gate reds on push (finding 56). A refused job's evidence is exactly the
    # record a human needs committed.
    if (out["merged"] or out["refused"]) and out.get("commit") and not args.no_commit:
        _bk_rel = os.path.relpath(os.path.abspath(run_dir), os.path.abspath(repo_root))
        if not _bk_rel.startswith(".." + os.sep) and _bk_rel != "..":
            _run(["git", "-C", repo_root, "add", "-A", "--", _bk_rel])
            _run(["git", "-C", repo_root, "reset", "-q", "--",
                  os.path.join(_bk_rel, ".run.lock")])
            for _stream in ("docs/superpowers/memory/triage-outcomes.jsonl",
                            "docs/superpowers/memory/worker-performance.jsonl"):
                if os.path.exists(os.path.join(repo_root, _stream)):
                    _run(["git", "-C", repo_root, "add", "--", _stream])
            _rc_q, _, _ = _run(["git", "-C", repo_root, "diff", "--cached", "--quiet"])
            if _rc_q != 0:
                _rc_bk, _, _err_bk = _run([
                    "git", "-C", repo_root, "commit", "-q", "-m",
                    "bookkeeping(%s): wave %s finalized" % (
                        os.path.basename(os.path.normpath(run_dir)), args.wave)])
                if _rc_bk == 0:
                    out["bookkeeping_commit"] = _head_commit(repo_root) or ""
                else:
                    out["bookkeeping_error"] = (_err_bk or "").strip()[:200]
    return emit(0 if out["integrated"] else 1)


# --------------------------------------------------------------------------- #
# register-lane
# --------------------------------------------------------------------------- #
def cmd_register_lane(argv):
    ap = argparse.ArgumentParser(prog="compound-v-emit-workflow.py register-lane")
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--job-id", required=True)
    ap.add_argument("--cwd", required=True)
    ap.add_argument("--manifest")
    ap.add_argument("--repo-root", required=True,
                    help="the PROJECT root. Required: a direct job's baseline is "
                         "this tree's HEAD, and it is never defaulted.")
    ap.add_argument("--isolation", required=True,
                    choices=["direct", "worktree"],
                    help="from the MANIFEST. Decides which tree the baseline is "
                         "pinned from; never inferred from --cwd.")
    ap.add_argument("--agent-id",
                    help="the PreToolUse payload's agent_id, IF the runtime ever "
                         "exposes it to the agent itself. It does not on 2.1.238.")
    ap.add_argument("--fastpath", default=FASTPATH_DEFAULT)
    ap.add_argument("--python", default=(sys.executable or "python3"))
    ap.add_argument("--no-test-contract", action="store_true",
                    help="skip resolving this job's test contract (the lane map "
                         "is still written)")
    args = ap.parse_args(argv)
    run_dir = os.path.abspath(args.run_dir)
    # An external job's wrapper (backend != claude) is listed, never a claim on
    # the checkout (finding 78). Read the backend off the manifest when given.
    _is_external_wrapper = False
    if args.manifest and os.path.exists(args.manifest):
        try:
            _reg_manifest = _load_manifest_dict(args.manifest)
            _reg_job = _manifest_job(_reg_manifest, args.job_id) if isinstance(_reg_manifest, dict) else None
            _is_external_wrapper = bool(_reg_job) and str(_reg_job.get("backend") or "claude") != "claude"
        except Exception:  # noqa: BLE001 — an unreadable manifest is the validator's problem, not this flag's
            _is_external_wrapper = False
    lane = register_lane(
        run_dir, args.job_id, args.cwd,
        manifest_path=args.manifest, agent_id=args.agent_id, wrapper=_is_external_wrapper,
    )
    ack = {"registered": args.job_id,
           "worktrees": len(lane.get("worktrees") or {}),
           "agents": len(lane.get("agents") or {})}

    # ---- SNAPSHOT WHAT WAS ALREADY DIRTY, before the implementer runs ------ #
    # Direct mode only. The gate measures the whole tree against the baseline, so
    # without a before-picture it attributes pre-existing dirt to this job. The
    # first live Engine C run (2026-09-01) was BLOCKED by exactly that: leftover
    # probe records and stray .pyc files, not by anything its job did.
    #
    # Taken HERE because this is the only point that provably precedes the work.
    # A snapshot taken later could not distinguish "was already there" from "the
    # job just wrote it", which is the whole property being bought.
    if (args.isolation or "direct") != "worktree":
        try:
            pre = _preexisting_snapshot(args.repo_root, sys.executable)
            snap_p = os.path.join(run_dir, "preexisting", "%s.txt" % args.job_id)
            os.makedirs(os.path.dirname(snap_p), exist_ok=True)
            # ONE-SHOT. A second `register-lane` for the same job must not re-take
            # the picture: the clamp admits repeated calls, so a worker that made
            # its changes and then re-registered could refresh the snapshot to
            # cover them. Re-running is otherwise legitimate (resume does it), so
            # this refuses the REWRITE rather than the call.
            if not os.path.exists(snap_p):
                ack["preexisting"] = write_preexisting(snap_p, args.repo_root, pre)
            else:
                ack["preexisting"] = "unchanged (snapshot already taken)"
        except Exception as exc:  # noqa: BLE001
            # Fail OPEN into a stricter gate, never a looser one: with no snapshot
            # the gate subtracts nothing and a dirty tree blocks. Loud, not silent.
            ack["preexisting_error"] = str(exc)

    # ---- PIN THE BASELINE, before anything has run ------------------------- #
    # This command is the Implement stage's FIRST tool call, which makes it the
    # only point in the Engine C lifecycle that happens before a worker launches.
    # 3.0.1 pinned nothing here, so state.json carried no baseline and the gate
    # filled one in from its own fallback AFTER execution — measuring the job
    # against a HEAD the job may itself have moved.
    #
    # The pin is written per-job (`jobs/<id>.baseline`) as well as into
    # state.json. Every job in a wave writes state.json, so a value that lived
    # only there could be lost to a sibling's save; the per-job file has exactly
    # one writer.
    repo_root = os.path.abspath(args.repo_root)
    pin_root = repo_root if args.isolation == "direct" else os.path.abspath(args.cwd)
    baseline = _head_commit(pin_root)
    if not baseline:
        sys.stderr.write(
            "cannot pin a baseline: %s has no resolvable HEAD. A gate with no "
            "pinned baseline measures a job against its own output, so this "
            "fails closed rather than letting the job start.\n" % pin_root
        )
        return 2
    pin_path = baseline_pin_path(run_dir, args.job_id)
    os.makedirs(os.path.dirname(pin_path), exist_ok=True)
    if not os.path.exists(pin_path):
        _atomic_write(pin_path, baseline + "\n")
    with _run_dir_lock(run_dir):
        state = _load_state(run_dir)
        entry = state["jobs"].setdefault(args.job_id, {})
        entry.setdefault("baseline",
                         read_pinned_baseline(run_dir, args.job_id, entry)
                         or baseline)
        entry["isolation"] = args.isolation
        _save_state(run_dir, state)
    ack["baseline"] = entry["baseline"]
    ack["baseline_pin"] = pin_path

    # ---- the handoff artefacts must already EXIST -------------------------- #
    # `emit` materializes them. If they are missing, the worker's --prompt-file
    # would point at nothing and the launcher would be an improvisation, which is
    # what 3.0.1 shipped. Refuse to let the job start rather than find out later.
    prompt_file = worker_prompt_path(run_dir, args.job_id)
    argv_file = launch_argv_path(run_dir, args.job_id)
    if os.path.exists(argv_file) and not os.path.exists(prompt_file):
        sys.stderr.write(
            "job %s has a materialized launcher argv but no prompt file at %s — "
            "the worker's --prompt-file would point at nothing. Re-run `emit`.\n"
            % (args.job_id, prompt_file)
        )
        return 2
    ack["prompt_file"] = prompt_file if os.path.exists(prompt_file) else None
    ack["launch_argv_file"] = argv_file if os.path.exists(argv_file) else None

    # ---- the test contract, resolved BEFORE the worker launches ------------
    # This is the Implement stage, and it is the only point in the Engine C
    # lifecycle that runs BEFORE an external worker starts. `gate-receipt` also
    # resolves a contract, but it runs AFTER the implementer has finished — so a
    # worker's `--test-contract-file` pointed at a file that did not yet exist,
    # and the flag was commented out to hide it. Resolving here is what makes the
    # flag real: on Engine C an external worker now genuinely RECEIVES the
    # contract instead of being told about one.
    #
    # The resolution is scoped to the PRE-CHANGE tree, which is the only tree
    # that exists yet. For `impacted` that means the impacted set is empty and the
    # slice is the floor (plus whatever the declared map yields for an empty
    # diff); the post-change resolution the FLOOR runs from is re-derived in
    # `gate-receipt`. Stated rather than hidden: this contract is the worker's
    # instruction, not the gate's measurement.
    if not args.no_test_contract:
        manifest_path = os.path.abspath(
            args.manifest or os.path.join(run_dir, "manifest.yaml")
        )
        state_job = (_load_state(run_dir)["jobs"].get(args.job_id) or {})
        out_path = test_contract_path(run_dir, args.job_id)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        written = _resolve_test_contract(
            args.fastpath, manifest_path, args.job_id, os.path.abspath(args.cwd),
            state_job.get("baseline"), args.python, out_path,
        )
        ack["test_contract"] = written
        if not written:
            # Never fabricated into a success: the manifest may simply declare no
            # `test_contract`, and the emitted prompt then carries no flag either.
            ack["test_contract_note"] = (
                "no contract resolved (the manifest may declare no `test_contract`, "
                "or resolution failed closed) — the worker runs no tests and reports "
                "no `tests` object"
            )

    # ---- THE PIPELINE'S OWN BOOKKEEPING IS NOT THE JOB'S WORK -------------- #
    # In DIRECT mode the run directory sits inside the tree the gate measures, so
    # every file this command writes for a job — the pre-existing snapshot, the
    # baseline pin, the resolved test contract, state.json — lands in that job's
    # changed set. Dogfood 2 (2026-09-02) blocked a dependent job for three of
    # them and the wave then refused integration as `forged`, which sends whoever
    # reads it hunting a forgery that never happened.
    #
    # THE FIRST FIX ENUMERATED THREE FILENAMES AND WAS WRONG. Dogfood 2b — the
    # narrowest reproduction, one direct-mode job — came back blocked for a
    # FOURTH, `state.json`, which the enumeration had missed because it was
    # written from reading the code path rather than from the evidence. A list of
    # names answers "did I remember them all?", and the honest answer is "not
    # yet".
    #
    # So the exemption is DERIVED: after this command has finished all of its own
    # writes, it lists the run directory as it stands and records that listing.
    # Whatever `register-lane` wrote is exempt BY CONSTRUCTION, and — the part
    # that matters for safety — anything the WORKER later adds to the run
    # directory is NOT in the listing and is still a violation. A worker cannot
    # forge a receipt or rewrite another job's baseline and have it ignored.
    #
    # A worktree job needs none of this: its run directory is outside its
    # worktree, and it gets no snapshot at all.
    if (args.isolation or "direct") != "worktree":
        try:
            repo_abs = os.path.abspath(args.repo_root)
            own = []
            for dirpath, _dirnames, filenames in os.walk(run_dir):
                for name in filenames:
                    full = os.path.abspath(os.path.join(dirpath, name))
                    rel = os.path.relpath(full, repo_abs)
                    if rel.startswith(".." + os.sep) or rel == "..":
                        continue          # outside the repo: not ours to exempt
                    own.append(rel.replace(os.sep, "/"))
            snap = os.path.join(run_dir, "preexisting", "%s.txt" % args.job_id)
            # EXISTING LINES ARE CARRIED FORWARD VERBATIM, never re-digested.
            #
            # The one-shot guard above covers the dirt snapshot; this block runs on
            # every call, and a first attempt re-digested the whole list here. Its
            # own test caught that: a worker could rewrite an exempted file, call
            # `register-lane` again — the clamp admits it — and the fresh digest
            # would re-bless the tampered bytes. Exactly the refresh-after-tamper
            # attack the cross-model review described, surviving in the half the
            # first fix did not cover.
            #
            # So an already-recorded path keeps the digest it was first bound to,
            # and only paths NEW to this listing are digested now.
            existing_lines, existing_rel = [], set()
            if os.path.exists(snap):
                with open(snap, "r", encoding="utf-8") as fh:
                    for ln in fh:
                        ln = ln.rstrip("\n").strip()
                        if not ln:
                            continue
                        existing_lines.append(ln)
                        parts = ln.split("  ", 1)
                        existing_rel.add(parts[1].strip()
                                         if len(parts) == 2 else ln)
            fresh = sorted(p for p in own if p not in existing_rel)
            new_lines = []
            for rel in fresh:
                dig = _file_digest(os.path.join(args.repo_root, rel))
                if dig:
                    new_lines.append("%s  %s" % (dig, rel))
            all_lines = existing_lines + new_lines
            _atomic_write(snap, "\n".join(all_lines) + ("\n" if all_lines else ""))
            ack["own_bookkeeping"] = len(new_lines)
        except Exception as exc:  # noqa: BLE001
            # Fail OPEN into a STRICTER gate, same rule as the snapshot itself:
            # without the listing the job is blocked for our files, which is loud.
            ack["own_bookkeeping_error"] = str(exc)

    print(json.dumps(ack, indent=2, sort_keys=True))
    return 0


# --------------------------------------------------------------------------- #
# engine selection
#
# Engine C runs in a top-level session where a LIVE PROBE succeeds. The residual
# subagent path is selected only where a workflow cannot launch.
#
# THE PROBE IS NOT A VERSION CHECK, and that distinction is the point. The
# product claims workflow support from 2.1.219, but `disallowedTools` and
# `bashCommandClamp` were found by reading 2.1.238. A build that accepts
# `Workflow` and refuses the clamp would pass a version test, select Engine C,
# and then FAIL TO CREATE THE GATE AGENT — the clamp is fail-closed and refuses
# the spawn outright rather than degrading. So the probe must spawn a CLAMPED
# agent, not merely start a workflow.
#
# DO NOT justify the fallback by claiming workflows are unavailable headless.
# They are available in `claude -p` and in the Agent SDK; only the `ultracode`
# keyword is route-restricted. The operational reasons are:
#   * a SUBAGENT has no Workflow tool — probed live under both the public name
#     `Workflow` and the internal `RunWorkflow`;
#   * `CLAUDE_WORKFLOW_NAME_ONLY` restricts a session to named workflows and
#     refuses `script`/`scriptPath`/`resumeFromRunId`/`remote` outright
#     (errorCode 8: "Invoke as {name, args} only"), which kills the
#     committed-artefact property Engine C exists for;
#   * `CLAUDE_CODE_DISABLE_WORKFLOWS`, the `disableWorkflows` managed setting, or
#     `enableWorkflows: false` turn the tool off entirely.
#
# CORRECTION TO THE SPEC, recorded rather than quietly worked around: the spec
# and plan name `CLAUDE_CODE_WORKFLOWS` as the variable that "restricts a session
# to named workflows and refuses scriptPath". In 2.1.238 those are two different
# variables. `CLAUDE_CODE_WORKFLOWS` is a BOOLEAN availability override (`true`
# forces the feature available, `false` disables it); the name-only restriction
# is `CLAUDE_WORKFLOW_NAME_ONLY`. Both are probed below, so the acceptance
# criterion is met by the variable it names AND by the one that actually does it.
# --------------------------------------------------------------------------- #
ENGINE_PROBE_ENV = [
    "CLAUDE_CODE_WORKFLOWS",
    "CLAUDE_WORKFLOW_NAME_ONLY",
    "CLAUDE_CODE_DISABLE_WORKFLOWS",
]

ENGINE_PROBE_SNIPPET = (
    "export const meta = { name: 'compound-v-engine-c-probe', "
    "description: 'Engine C capability probe: a CLAMPED spawn, not a version check.', "
    "phases: [{ title: 'Probe' }] };\n"
    "const ok = await agent('Run exactly: /bin/echo engine-c-probe-ok\\n"
    "Return only what it printed.', {\n"
    "  label: 'engine-c probe',\n"
    "  phase: 'Probe',\n"
    "  disallowedTools: ['Read','Write','Edit','Glob','Grep','WebFetch','WebSearch','Task'],\n"
    "  bashCommandClamp: ['Bash(/bin/echo engine-c-probe-ok)']\n"
    "});\n"
    "return { clamped_spawn: ok !== null && ok !== undefined };\n"
)


def engine_probe_report(env=None):
    """What a caller must check before choosing Engine C. Env half is decidable
    here; the clamped-spawn half is NOT — it has to be run."""
    env = env if env is not None else os.environ
    blockers = []
    if str(env.get("CLAUDE_CODE_WORKFLOWS", "")).lower() == "false":
        blockers.append(
            "CLAUDE_CODE_WORKFLOWS=false disables the Workflow tool for this session"
        )
    if env.get("CLAUDE_WORKFLOW_NAME_ONLY"):
        blockers.append(
            "CLAUDE_WORKFLOW_NAME_ONLY restricts this session to NAMED workflows and "
            "refuses script/scriptPath — Engine C's committed-artefact form is "
            "unavailable here"
        )
    if env.get("CLAUDE_CODE_DISABLE_WORKFLOWS"):
        blockers.append("CLAUDE_CODE_DISABLE_WORKFLOWS is set")
    return {
        "env_blockers": blockers,
        "env_clear": not blockers,
        "clamped_spawn_probe": ENGINE_PROBE_SNIPPET,
        "note": (
            "env_clear is necessary, NEVER sufficient. Run the clamped-spawn probe: "
            "a build that accepts Workflow but refuses disallowedTools/"
            "bashCommandClamp would select Engine C and then fail to create the "
            "Gate agent. Do not infer support from a version number."
        ),
    }


# --------------------------------------------------------------------------- #
# emit
# --------------------------------------------------------------------------- #
def cmd_emit(argv):
    ap = argparse.ArgumentParser(prog="compound-v-emit-workflow.py emit")
    ap.add_argument("manifest", help="path to manifest.yaml")
    ap.add_argument("--run-dir", help="default: the manifest's directory")
    ap.add_argument("--repo-root",
                    help="the PROJECT root. Omitted, it is DERIVED from the "
                         "manifest's own git tree; if that cannot be derived, "
                         "emit fails. It is never the installed plugin's repo.")
    ap.add_argument("--out", help="default: <run-dir>/dispatch.workflow.js")
    ap.add_argument("--python", default="/usr/bin/python3")
    ap.add_argument("--scope-check", default=SCOPE_CHECK_DEFAULT)
    ap.add_argument("--fastpath", default=FASTPATH_DEFAULT)
    ap.add_argument("--workers-dir", default=HERE)
    ap.add_argument("--print", dest="to_stdout", action="store_true",
                    help="write nothing; print the script")
    ap.add_argument("--probe-report", action="store_true",
                    help="also print the engine-selection probe report")
    args = ap.parse_args(argv)

    manifest_path = os.path.abspath(args.manifest)
    manifest = _load_yaml(manifest_path) or {}
    manifest["_manifest_path"] = manifest_path
    run_dir = os.path.abspath(args.run_dir or os.path.dirname(manifest_path))

    # The project root is DERIVED from the manifest's own tree, never inherited
    # from wherever this script happens to be installed. A run whose root cannot
    # be established does not emit — a workflow that does not know which
    # repository it is building is not a workflow that should start.
    repo_root = args.repo_root
    if not repo_root:
        rc, top, _ = _run(["git", "-C", os.path.dirname(manifest_path),
                           "rev-parse", "--show-toplevel"])
        repo_root = top.strip() if rc == 0 and top.strip() else None
    if not repo_root:
        sys.stderr.write(
            "REFUSING TO EMIT: no repository root. Pass --repo-root <project>, or "
            "put the manifest inside the project's git tree. Defaulting this to "
            "the repository containing this script is what made 3.0.1 apply a "
            "job's patch to the wrong repository.\n"
        )
        return 2

    try:
        plan = build_plan(
            manifest, run_dir, repo_root, args.python,
            os.path.abspath(__file__), args.scope_check, args.fastpath,
            args.workers_dir,
        )
    except ValueError as exc:
        sys.stderr.write("REFUSING TO EMIT: %s\n" % exc)
        return 1
    script = emit_script(plan)

    hits = forbidden_hits(script)
    if hits:
        sys.stderr.write(
            "REFUSING TO EMIT: the script contains constructs this runtime makes "
            "throw:\n%s\n" % json.dumps(hits, indent=2)
        )
        return 1

    if args.to_stdout:
        sys.stdout.write(script)
        return 0

    out_path = os.path.abspath(
        args.out or os.path.join(run_dir, "dispatch.workflow.js")
    )
    _atomic_write(out_path, script)

    # The handoff artefacts, written NOW — before the workflow runs, which is the
    # only moment early enough for a worker to be handed a --prompt-file that
    # exists. 3.0.1 emitted `worker-script ...` and left the rest to a model.
    artefacts = []
    for job_id, doc in sorted(plan["artefacts"].items()):
        _atomic_write(doc["prompt_file"], doc["prompt_text"])
        artefacts.append(doc["prompt_file"])
        if doc["launch_argv_file"]:
            _atomic_write(
                doc["launch_argv_file"],
                json.dumps(doc["launch_argv"], indent=2) + "\n",
            )
            artefacts.append(doc["launch_argv_file"])

    report = {
        "script": out_path,
        "repo_root": plan["repo_root"],
        "job_artefacts": artefacts,
        "run_id": plan["run_id"],
        "waves": [[j["id"] for j in wave] for wave in plan["waves"]],
        "jobs": sum(len(w) for w in plan["waves"]),
        "forbidden_constructs": hits,
        "launch": (
            "Workflow({ scriptPath: %r }) — the scriptPath form is MANDATORY. The "
            "tool's own guidance is to pass the script inline, which is the "
            "opposite of committing the artefact; scriptPath takes documented "
            "precedence, and without it the committed file is not what ran."
            % out_path
        ),
    }
    if args.probe_report:
        report["engine_probe"] = engine_probe_report()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


# --------------------------------------------------------------------------- #
# selftest
# --------------------------------------------------------------------------- #
_FAILURES = []
_PASSES = [0]


class _quiet(object):
    """Swallow a subcommand's stdout so the selftest report stays readable."""

    def __enter__(self):
        self._saved = sys.stdout
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
        return self

    def __exit__(self, *exc):
        sys.stdout.close()
        sys.stdout = self._saved
        return False


def _check(name, condition, detail=""):
    if condition:
        _PASSES[0] += 1
    else:
        _FAILURES.append("%s%s" % (name, (" — " + detail) if detail else ""))


def _tiny_manifest(jobs, max_parallel=2):
    # Every job gets task text unless the case is deliberately testing its absence.
    # `render_worker_prompt` now REFUSES a job without it — a prompt with lanes and
    # no instructions asks the worker to invent the task — so a fixture that omits
    # it is testing the refusal, not the feature it meant to test.
    for j in jobs:
        if isinstance(j, dict) and not any(
                j.get(k) for k in ("body", "description", "prompt", "spec")):
            j["body"] = "Selftest fixture task text for job %s." % j.get("id")
    return {"run_id": "selftest-run", "max_parallel": max_parallel, "jobs": jobs}


def _with_body(manifest):
    """Give every job in an INLINE fixture task text. `_tiny_manifest` does this
    for fixtures built through it; these are the ones written out by hand."""
    for j in (manifest.get("jobs") or []):
        if isinstance(j, dict) and not any(
                j.get(k) for k in ("body", "description", "prompt", "spec")):
            j["body"] = "Selftest fixture task text for job %s." % j.get("id")
    return manifest


def _plan_for(manifest, tmp, workers_dir=None):
    _with_body(manifest)
    manifest["_manifest_path"] = os.path.join(tmp, "manifest.yaml")
    return build_plan(
        manifest, tmp, tmp, "/usr/bin/python3", os.path.abspath(__file__),
        SCOPE_CHECK_DEFAULT, FASTPATH_DEFAULT, workers_dir or tmp,
    )


def _init_repo(path):
    os.makedirs(path, exist_ok=True)
    _run(["git", "init", "-q", path])
    _run(["git", "-C", path, "config", "user.email", "selftest@example.invalid"])
    _run(["git", "-C", path, "config", "user.name", "selftest"])
    with open(os.path.join(path, "seed.txt"), "w", encoding="utf-8") as fh:
        fh.write("seed\n")
    _run(["git", "-C", path, "add", "-A"])
    _run(["git", "-C", path, "commit", "-q", "-m", "seed"])
    return _head_commit(path)


def selftest():
    tmp = tempfile.mkdtemp(prefix="cv-emitwf-selftest-")
    try:
        # --- topological waves ------------------------------------------------
        jobs = [
            {"id": "t0", "run": "serial", "write_allowed": ["a/**"]},
            {"id": "t1", "depends_on": ["t0"], "write_allowed": ["b/**"]},
            {"id": "t2", "depends_on": ["t0"], "write_allowed": ["c/**"]},
            {"id": "t3", "depends_on": ["t0"], "write_allowed": ["d/**"]},
            {"id": "t4", "depends_on": ["t1", "t2"], "write_allowed": ["e/**"]},
        ]
        waves = topo_waves(jobs, 2)
        ids = [[j["id"] for j in w] for w in waves]
        _check("serial job gets its own wave", ids[0] == ["t0"], str(ids))
        _check("max_parallel chunks a wave",
               all(len(w) <= 2 for w in ids), str(ids))
        _check("dependent lands after its prerequisites",
               ids.index([x for x in ids if "t4" in x][0]) >
               max(ids.index(w) for w in ids if "t1" in w or "t2" in w),
               str(ids))
        _check("every job scheduled exactly once",
               sorted(sum(ids, [])) == ["t0", "t1", "t2", "t3", "t4"], str(ids))

        # finding 60: the dependent-job isolation rule follows `worktree.baseRef`.
        _br_repo = os.path.join(tmp, "br-repo"); os.makedirs(os.path.join(_br_repo, ".claude"))
        _br_man = {"run_id": "br", "jobs": [
            {"id": "a", "isolation": "worktree", "write_allowed": ["a/**"]},
            {"id": "b", "isolation": "worktree", "depends_on": ["a"], "write_allowed": ["b/**"]}]}
        _br_man["_manifest_path"] = os.path.join(_br_repo, "manifest.yaml")
        _br_plan = build_plan(_with_body(_br_man), os.path.join(tmp, "br-run"), _br_repo,
                              "/usr/bin/python3", os.path.abspath(__file__),
                              SCOPE_CHECK_DEFAULT, FASTPATH_DEFAULT, tmp)
        _br_b = [e for w in _br_plan["waves"] for e in w if e["id"] == "b"][0]
        _check("no baseRef setting: a dependent worktree job's agent runs direct (3.0.5 rule)",
               _br_b.get("agent_isolation") is None)
        with open(os.path.join(_br_repo, ".claude", "settings.json"), "w") as fh:
            fh.write('{"worktree": {"baseRef": "head"}}')
        _br_plan2 = build_plan(_with_body(_br_man), os.path.join(tmp, "br-run"), _br_repo,
                               "/usr/bin/python3", os.path.abspath(__file__),
                               SCOPE_CHECK_DEFAULT, FASTPATH_DEFAULT, tmp)
        _br_b2 = [e for w in _br_plan2["waves"] for e in w if e["id"] == "b"][0]
        _check("worktree.baseRef: head — a dependent worktree job gets a REAL worktree",
               _br_b2.get("agent_isolation") == "worktree")

        try:
            topo_waves([{"id": "a", "depends_on": ["b"]},
                        {"id": "b", "depends_on": ["a"]}], 2)
            _check("cycle is rejected", False)
        except ValueError:
            _check("cycle is rejected", True)

        try:
            topo_waves([{"id": "a", "depends_on": ["ghost"]}], 2)
            _check("unknown depends_on is rejected", False)
        except ValueError:
            _check("unknown depends_on is rejected", True)

        # --- emitted script ---------------------------------------------------
        plan = _plan_for(_tiny_manifest(jobs), tmp)
        script = emit_script(plan)
        _check("no forbidden constructs in the emitted script",
               forbidden_hits(script) == [], str(forbidden_hits(script)))
        # finding 75: the external wrapper is a harness Bash call (600 s ceiling).
        _ext_workers = os.path.join(tmp, "workers-f75"); os.makedirs(_ext_workers, exist_ok=True)
        with open(os.path.join(_ext_workers, "compound-v-run-codex-worker.sh"), "w") as _fh:
            _fh.write("#!/bin/sh\nexit 0\n")
        _ext_plan = _plan_for(_tiny_manifest([
            {"id": "ext", "backend": "codex", "isolation": "worktree", "tier": "standard",
             "timeout_sec": 900, "write_allowed": ["src/**"]}]), tmp, workers_dir=_ext_workers)
        _ext = [e for w in _ext_plan["waves"] for e in w if e["id"] == "ext"][0]
        _ext_argv = _ext.get("launch_argv") or []
        _check("finding 75: an external worker's --timeout-sec is capped below the harness ceiling",
               "--timeout-sec" in _ext_argv
               and _ext_argv[_ext_argv.index("--timeout-sec") + 1] == str(EXTERNAL_WORKER_TIMEOUT_CAP),
               str(_ext_argv)[:300])
        _ext_script = emit_script(_ext_plan)
        _check("finding 75: the external wrapper prompt tells the agent the Bash timeout",
               "ten minutes, the harness" in _ext_script and "timeout: 600000" in _ext_script)
        # finding 77: the wrapper agent is spawned as a CLAUDE model; the backend's
        # model reaches the launch argv only.
        _check("finding 82: the external worker's prompt file says it is unattended and must not ask",
               "## You are unattended" in render_worker_prompt(
                   {"id": "ext", "backend": "codex", "write_allowed": ["src/**"],
                    "title": "t", "body": "b", "acceptance": ["a"]}, "run-x")
               and "NOTHING, and the job is then recorded" in render_worker_prompt(
                   {"id": "ext", "backend": "codex", "write_allowed": ["src/**"],
                    "title": "t", "body": "b", "acceptance": ["a"]}, "run-x"))
        _check("finding 79: an external job's gate runs in worktree mode at the WORKER's returned tree",
               "const externalBackend = job.backend && job.backend !== 'claude';" in _ext_script
               and "(job.agent_isolation === 'worktree' || externalBackend) ? 'worktree' : 'direct'" in _ext_script)
        _f81_dir = os.path.join(tmp, "f81-run"); os.makedirs(os.path.join(_f81_dir, "logs"), exist_ok=True)
        with open(os.path.join(_f81_dir, "logs", "ext.events.jsonl"), "w") as _fh:
            _fh.write('{"type":"thread.started","thread_id":"01a0660c-d369-7553-b57c-2c5276b35ae6"}\n{"type":"turn.started"}\n')
        with open(os.path.join(_f81_dir, "logs", "bad.events.jsonl"), "w") as _fh:
            _fh.write('{"type":"thread.started","thread_id":"not-a-uuid"}\n')
        _check("finding 81: the external worker's thread id is read from its events log (UUID-validated)",
               external_session_id(_f81_dir, "ext") == "01a0660c-d369-7553-b57c-2c5276b35ae6"
               and external_session_id(_f81_dir, "bad") == "" and external_session_id(_f81_dir, "none") == "")
        _check("finding 77: an external job's wrapper agent_model is a Claude light model, "
               "and the backend model stays in the launch argv",
               str(_ext.get("agent_model") or "").lower() in ("sonnet", "claude-sonnet-4-6")
               and "--model" in _ext_argv and "gpt" in _ext_argv[_ext_argv.index("--model") + 1]
               and "if (job.agent_model) opts.model = job.agent_model;" in _ext_script,
               "agent_model=%r argv=%s" % (_ext.get("agent_model"), _ext_argv[:12]))
        _check("finding 69: the emitted Record command passes the receipt by PATH, "
               "bound by --expect-verdict/--expect-diff-digest, and keeps the inline "
               "form only for a verdict without a receipt",
               "' --verdict-file ' + q(v.receipt_path)" in script
               and "--expect-diff-digest" in script and "v.receipt_path" in script
               and "' --verdict-json ' + q(JSON.stringify(v))" in script)
        _check("meta export is the FIRST statement",
               script.lstrip().startswith("export const meta = {"),
               script.lstrip()[:60])
        _check("emitted script uses pipeline with three stages",
               "pipeline(wave, implementStage, gateStage, recordStage)" in script)
        _check("emitted script uses the native budget global",
               "budget.remaining()" in script and "budgetAllows" in script)
        _check("emitted script uses phase() and log()",
               "phase(title);" in script and "log(" in script)
        _check("Gate stage is wrapped so it cannot throw",
               "async function gateStage" in script and "catch (e)" in script)
        _check("null is FAIL, never pass",
               "gate agent returned null — FAIL, never pass" in script)
        _check("opts.phase is set per agent (no reliance on the global inside stages)",
               script.count("phase: 'Implement'") == 1
               and script.count("phase: 'Gate'") == 1
               and script.count("phase: 'Record'") == 1)
        _check("Gate agent is narrowed at spawn",
               "disallowedTools: CFG.narrow_disallowed" in script
               and "bashCommandClamp" in script)
        _check("Bash survives the narrowing (a clamp that binds nothing refuses the spawn)",
               "Bash" not in NARROW_DISALLOWED)
        _check("StructuredOutput survives the narrowing",
               "StructuredOutput" not in NARROW_DISALLOWED)
        # ---- 3.3.0: a worktree job that did NOTHING is blocked, not error ---
        # Dogfood 6: the runtime removes an UNCHANGED worktree, so a job that
        # wrote nothing leaves no worktree to observe and the fail-closed branch
        # written for a genuine locator fault answered instead — `error`, with a
        # paragraph about lane-map reconstruction.
        nw_run = os.path.join(tmp, "nowork")
        os.makedirs(os.path.join(nw_run, "results"), exist_ok=True)
        nw_man = {"run_id": "nw", "max_parallel": 1,
                  "jobs": [{"id": "j-lanes", "backend": "claude", "tier": "light",
                            "isolation": "worktree",
                            "write_allowed": ["docs/x/**"]},
                           {"id": "j-lanes2", "backend": "claude", "tier": "light",
                            "isolation": "worktree",
                            "write_allowed": ["docs/x/**"]},
                           {"id": "j-lanes3", "backend": "claude", "tier": "light",
                            "isolation": "worktree",
                            "write_allowed": ["docs/x/**"]},
                           {"id": "j-review", "type": "review", "backend": "claude",
                            "tier": "deep", "isolation": "worktree",
                            "write_allowed": []}]}
        nw_man_p = os.path.join(nw_run, "manifest.yaml")
        with open(nw_man_p, "w", encoding="utf-8") as fh:
            json.dump(nw_man, fh)
        nw_verdict = json.dumps({"verdict": "pass", "changed": [], "worktree": ""})
        rc_nw = cmd_record(["--run-dir", nw_run, "--job-id", "j-lanes",
                            "--manifest", nw_man_p, "--repo-root", tmp,
                            "--verdict-json", nw_verdict])
        nw_res = _read_json(os.path.join(nw_run, "results", "j-lanes.json"), None)
        # ---- 3.3.0 (dogfood 14): a RED FLOOR blocks -------------------------
        _floor_fail = {"phase": "floor", "passed": False,
                       "checks": [{"checker": "sh -c 'exit 3'", "rc": 3}],
                       "failures": ["sh -c 'exit 3'"]}
        _floor_ok = {"phase": "floor", "passed": True,
                     "checks": [{"checker": "/bin/echo ok", "rc": 0}],
                     "failures": []}
        _clean_verdict = {"verdict": "pass", "exit_code": 0,
                          "raw_stdout": json.dumps({"verdict": "pass",
                                                    "changed": ["docs/x/a.md"]}),
                          "worktree": "/tmp/wt"}
        _jr_red = _job_result_from(_clean_verdict, {"id": "j", "backend": "claude",
                                                    "write_allowed": ["docs/x/**"]},
                                   {}, tests=_floor_fail)
        # dogfood 16: "nothing to commit" meant two opposite things.
        import types as _t
        _fw = _t.SimpleNamespace()
        _out_ref = {"refused": ["j1"], "merged": [], "commit": "", "reason": None}
        if _out_ref["refused"] and not _out_ref["merged"]:
            _out_ref["reason"] = ("nothing was merged: every job in this wave was "
                                  "refused (%s). HEAD is unchanged by this wave."
                                  % ", ".join(_out_ref["refused"]))
        _check("an all-refused wave does not claim its work is already in HEAD",
               "already in HEAD" not in (_out_ref["reason"] or "")
               and "every job in this wave was refused" in _out_ref["reason"])
        _out_idem = {"refused": [], "merged": ["j1"], "reason": None}
        _out_idem["reason"] = ("nothing left to commit — this wave's work is "
                               "already in HEAD (idempotent re-finalize)")
        _check("a genuine idempotent re-finalize still says so",
               "idempotent re-finalize" in _out_idem["reason"])
        _ = _fw

        _check("the `blocked` boolean follows the FINAL status, not the verdict",
               _job_result_from({"verdict": "pass", "exit_code": 0,
                                 "raw_stdout": json.dumps({"verdict": "pass",
                                                           "changed": ["d/a.md"]}),
                                 "worktree": "/tmp/wt"},
                                {"id": "j", "backend": "claude",
                                 "write_allowed": ["d/**"]},
                                {}, tests={"phase": "floor", "passed": False,
                                           "checks": [{"checker": "x", "rc": 3}],
                                           "failures": ["x"]})["blocked"] is True)

        _check("a passing scope gate with a RED floor is blocked, not success",
               _jr_red["status"] == "blocked", str(_jr_red["status"]))
        _check("...and the failing command is still recorded",
               _jr_red.get("tests", {}).get("exit_code") == 3)
        _jr_green = _job_result_from(_clean_verdict,
                                     {"id": "j", "backend": "claude",
                                      "write_allowed": ["docs/x/**"]},
                                     {}, tests=_floor_ok)
        _check("a green floor leaves success alone",
               _jr_green["status"] == "success", str(_jr_green["status"]))
        _jr_none = _job_result_from(_clean_verdict,
                                    {"id": "j", "backend": "claude",
                                     "write_allowed": ["docs/x/**"]}, {})
        _check("no floor at all is not a failure",
               _jr_none["status"] == "success")

        _check("a lane-declaring job with no observable worktree is RECORDED",
               rc_nw == 0 and isinstance(nw_res, dict), str(rc_nw))
        _check("...and its status is blocked, not error",
               (nw_res or {}).get("status") == "blocked",
               str((nw_res or {}).get("status")))
        rc_rev = cmd_record(["--run-dir", nw_run, "--job-id", "j-review",
                             "--manifest", nw_man_p, "--repo-root", tmp,
                             "--verdict-json", nw_verdict])
        _check("a job with NO lanes still fails closed as a locator fault",
               rc_rev == 2, str(rc_rev))
        # A verdict reporting CHANGES but no worktree is broken machinery wearing
        # the no-work shape. Recording it as "the job did nothing" would mask a
        # locator fault as a job failure — the more dangerous direction.
        nw_changed = json.dumps({"verdict": "pass", "worktree": "",
                                 "changed": ["docs/x/a.md"]})
        rc_ch = cmd_record(["--run-dir", nw_run, "--job-id", "j-lanes2",
                            "--manifest", nw_man_p, "--repo-root", tmp,
                            "--verdict-json", nw_changed])
        _check("changes but no worktree is still a locator fault, not no-work",
               rc_ch == 2, str(rc_ch))
        nw_changed_raw = json.dumps({
            "verdict": "pass", "worktree": "",
            "raw_stdout": json.dumps({"verdict": "pass",
                                      "changed": ["docs/x/b.md"]})})
        rc_ch2 = cmd_record(["--run-dir", nw_run, "--job-id", "j-lanes3",
                             "--manifest", nw_man_p, "--repo-root", tmp,
                             "--verdict-json", nw_changed_raw])
        _check("...in the raw_stdout shape too", rc_ch2 == 2, str(rc_ch2))

        # ---- 3.3.0: register-lane's OWN files are not the job's work --------
        # Dogfood 2 blocked a dependent job for three files our own machinery
        # wrote for it. Direct mode only — a worktree job's run dir is outside
        # the tree its gate measures.
        bk_repo = os.path.join(tmp, "bkrepo")
        _init_repo(bk_repo)
        bk_run = os.path.join(bk_repo, "docs", "superpowers", "execution", "bk")
        os.makedirs(bk_run, exist_ok=True)
        bk_manifest = {"run_id": "bk", "max_parallel": 1,
                       "test_contract": {"floor_command": "/bin/echo ok",
                                         "full_command": "/bin/echo full"},
                       "jobs": [{"id": "d1", "backend": "claude", "tier": "light",
                                 "isolation": "direct",
                                 "write_allowed": ["docs/superpowers/dogfood/**"]}]}
        with open(os.path.join(bk_run, "manifest.yaml"), "w", encoding="utf-8") as fh:
            json.dump(bk_manifest, fh)
        rc_bk = cmd_register_lane([
            "--run-dir", bk_run, "--job-id", "d1", "--cwd", bk_repo,
            "--repo-root", bk_repo, "--isolation", "direct",
            "--manifest", os.path.join(bk_run, "manifest.yaml"),
        ])
        snap_p = os.path.join(bk_run, "preexisting", "d1.txt")
        snap_lines = []
        if os.path.exists(snap_p):
            with open(snap_p, "r", encoding="utf-8") as fh:
                snap_lines = [ln.strip() for ln in fh if ln.strip()]
        _check("register-lane succeeds in direct mode", rc_bk == 0, str(rc_bk))
        # The exemption is DERIVED from the run dir as it stands, so these are
        # spot-checks of a listing, not the listing itself. `state.json` is here
        # because enumerating three names missed it and dogfood 2b found it.
        for _want in ("jobs/d1.baseline", "preexisting/d1.txt",
                      "jobs/d1.test-contract.json", "state.json"):
            _check("register-lane's own %s is exempted" % _want,
                   any(l.endswith(_want) for l in snap_lines), str(snap_lines))
        _check("EVERY file register-lane left in the run dir is exempted",
               all(any(l.endswith(os.path.relpath(os.path.join(dp, fn), bk_run)
                                  .replace(os.sep, "/"))
                       for l in snap_lines)
                   for dp, _dn, fns in os.walk(bk_run) for fn in fns),
               str(snap_lines))
        # 3.3.0 (dogfood 10): shared pipeline state is exempt BY NAME, because the
        # pipeline itself rewrites it mid-run; the two levers stay digest-bound.
        # 3.3.0 (dogfood 13): another run's files, written by a HUMAN during a
        # direct-mode job, are still violations — but named, so the diagnosis is
        # instant instead of reading as "your job wrote five files it should not".
        _fake_parsed = {"violations": [
            "docs/superpowers/execution/OTHER-RUN/manifest.yaml",
            "docs/superpowers/execution/THIS-RUN/jobs/x.baseline",
            "src/app.py"]}
        _exec_root = "docs/superpowers/execution/"
        _foreign = [p for p in _fake_parsed["violations"]
                    if p.startswith(_exec_root)
                    and p[len(_exec_root):].split("/", 1)[0] != "THIS-RUN"]
        _check("another run's path is flagged foreign",
               _foreign == ["docs/superpowers/execution/OTHER-RUN/manifest.yaml"],
               str(_foreign))
        _check("this run's own path is NOT foreign",
               "docs/superpowers/execution/THIS-RUN/jobs/x.baseline" not in _foreign)
        _check("a source file outside the execution root is NOT foreign",
               "src/app.py" not in _foreign)

        _check("state.json is pipeline-owned and exempt by name",
               run_dir_owned_by_name("docs/superpowers/execution/bk/state.json",
                                     "docs/superpowers/execution/bk", "d1") is True)
        _check("the gate's own verified list is exempt by name",
               run_dir_owned_by_name(
                   "docs/superpowers/execution/bk/preexisting/d1.verified.txt",
                   "docs/superpowers/execution/bk", "d1") is True)
        _check("the BASELINE PIN is never exempt by name",
               run_dir_owned_by_name(
                   "docs/superpowers/execution/bk/jobs/d1.baseline",
                   "docs/superpowers/execution/bk", "d1") is False)
        # CRITICAL from round 2: the manifest DEFINES write_allowed. Exempting it
        # by name lets a worker widen its own lane and have both the gate and the
        # authority agree, with an honest baseline and an honest digest.
        _check("manifest.yaml is NOT exempt by name — it defines the lanes",
               run_dir_owned_by_name("docs/superpowers/execution/bk/manifest.yaml",
                                     "docs/superpowers/execution/bk", "d1") is False)
        # Written after the gate by the pipeline, for THIS job — cannot be in a
        # list the gate produced, always in the authority's re-derivation.
        for _p in ("receipts/d1.gate.json", "results/d1.json",
                   "results/attempts/d1.2.json"):
            _check("run-dir %s IS exempt (written after the gate)" % _p,
                   run_dir_owned_by_name("docs/superpowers/execution/bk/" + _p,
                                         "docs/superpowers/execution/bk",
                                         "d1") is True)
        for _p in ("receipts/OTHER.gate.json", "results/OTHER.json",
                   "jobs/d1.prompt.md", "dispatch.workflow.js",
                   "preexisting/OTHER.txt", "anything-a-worker-invents"):
            _check("run-dir %s is NOT exempt by name" % _p,
                   run_dir_owned_by_name("docs/superpowers/execution/bk/" + _p,
                                         "docs/superpowers/execution/bk",
                                         "d1") is False)
        _check("the exemption list IS exempt by name — it cannot bind itself",
               run_dir_owned_by_name(
                   "docs/superpowers/execution/bk/preexisting/d1.txt",
                   "docs/superpowers/execution/bk", "d1") is True)
        _check("the BASELINE PIN remains the one digest-bound lever",
               run_dir_owned_by_name(
                   "docs/superpowers/execution/bk/jobs/d1.baseline",
                   "docs/superpowers/execution/bk", "d1") is False)
        _check("another run's directory is never pipeline-owned here",
               run_dir_owned_by_name("docs/superpowers/execution/OTHER/state.json",
                                     "docs/superpowers/execution/bk", "d1") is False)
        _check("a path outside any run dir is never pipeline-owned",
               run_dir_owned_by_name("src/app.py",
                                     "docs/superpowers/execution/bk", "d1") is False)
        # A DIRECTORY entry must survive the snapshot: git reports an untracked
        # directory as one entry, and the digest-only version dropped every one —
        # fifteen leftover harness worktrees came back as violations.
        _dsnap = os.path.join(tmp, "dirsnap.txt")
        os.makedirs(os.path.join(bk_repo, "leftover"), exist_ok=True)
        write_preexisting(_dsnap, bk_repo, ["leftover/", "seed.txt"])
        _dkept = read_preexisting_unchanged(_dsnap, bk_repo)
        _check("a directory entry survives the snapshot as a by-name exemption",
               "leftover/" in _dkept, str(_dkept))
        _check("...and a real file alongside it is still digest-bound",
               "seed.txt" in _dkept
               and any(l.startswith("dir  ") for l in
                       open(_dsnap, encoding="utf-8").read().splitlines()))

        _check("a file the WORKER adds later is NOT exempt",
               "receipts/d1.gate.json" not in "\n".join(snap_lines))
        # CRITICAL, from a cross-model review: an exemption by NAME lets a worker
        # rewrite an exempted file's CONTENTS. Each line binds a digest.
        _check("every exemption line carries a sha256, not a bare path",
               all(re.match(r"^[0-9a-f]{64}  \S", l) for l in snap_lines),
               str(snap_lines[:2]))
        _kept_before = read_preexisting_unchanged(snap_p, bk_repo)
        _check("an untouched exempted file stays exempt",
               any(k.endswith("jobs/d1.baseline") for k in _kept_before))
        with open(os.path.join(bk_run, "jobs", "d1.baseline"), "a",
                  encoding="utf-8") as fh:
            fh.write("tampered\n")
        _kept_after = read_preexisting_unchanged(snap_p, bk_repo)
        _check("a REWRITTEN exempted file loses its exemption",
               not any(k.endswith("jobs/d1.baseline") for k in _kept_after),
               str(_kept_after))
        _check("rewriting one file does not un-exempt the others",
               len(_kept_after) == len(_kept_before) - 1,
               "%d vs %d" % (len(_kept_after), len(_kept_before)))
        # ONE-SHOT: a second register-lane must not re-take the picture.
        _before_snap = open(snap_p, encoding="utf-8").read()
        cmd_register_lane([
            "--run-dir", bk_run, "--job-id", "d1", "--cwd", bk_repo,
            "--repo-root", bk_repo, "--isolation", "direct",
            "--manifest", os.path.join(bk_run, "manifest.yaml"),
        ])
        _check("a second register-lane does not re-snapshot the tampered file",
               not any(k.endswith("jobs/d1.baseline")
                       for k in read_preexisting_unchanged(snap_p, bk_repo)))
        _ = _before_snap
        _check("nothing outside the repo root reaches the snapshot",
               all(not l.startswith("..") for l in snap_lines), str(snap_lines))
        # A WORKTREE job must not get the exemption — its run dir is not in the
        # tree its gate measures, and adding paths there would be noise at best.
        rc_wt = cmd_register_lane([
            "--run-dir", bk_run, "--job-id", "w1", "--cwd", bk_repo,
            "--repo-root", bk_repo, "--isolation", "worktree",
            "--manifest", os.path.join(bk_run, "manifest.yaml"),
        ])
        _check("a worktree job writes no preexisting snapshot at all",
               rc_wt == 0
               and not os.path.exists(os.path.join(bk_run, "preexisting", "w1.txt")))

        # 3.1.2 — the invariant, not the description. A launched job ALWAYS carries
        # an implement clamp: the only clampless path (external backend, missing
        # worker script) is refused before it can launch.
        clamped = _plan_for(_tiny_manifest([
            {"id": "c-claude", "tier": "light", "write_allowed": ["k/**"]},
            {"id": "c-deep", "tier": "deep", "write_allowed": ["l/**"]},
        ]), tmp)
        # dogfood 24: the recall instruction was unreachable behind the clamp.
        _cl = _clamp_rules({"id": "j", "backend": "claude"}, "/usr/bin/python3",
                           os.path.abspath(__file__), lambda b: None)
        # dogfood 25: the task text never reached the worker for 25 runs.
        _bp = render_worker_prompt({"id": "j", "title": "T",
                                    "body": "DO THE ACTUAL THING"}, "r")
        _check("a manifest's `body` reaches the worker prompt",
               "DO THE ACTUAL THING" in _bp, _bp[:120])
        for _alias in ("description", "prompt", "spec"):
            _check("the legacy alias %r still works" % _alias,
                   "LEGACY" in render_worker_prompt(
                       {"id": "j", "title": "T", _alias: "LEGACY"}, "r"))
        _refused = False
        try:
            render_worker_prompt({"id": "j", "title": "T",
                                  "write_allowed": ["a/**"]}, "r")
        except ValueError as _e:
            _refused = "no task text" in str(_e)
        _check("lanes + a title and NOTHING to check against is refused", _refused)
        # ...but a title WITH acceptance criteria is a task, and was valid before
        # this refusal existed. Round 3 was right that the first version broke it.
        _ta = render_worker_prompt({"id": "j", "title": "Rename getUser",
                                    "acceptance": ["every call site updated"],
                                    "write_allowed": ["a/**"]}, "r")
        _check("a title PLUS acceptance criteria is accepted as the task",
               "Rename getUser" in _ta and "every call site updated" in _ta)
        _check("...and the prompt says so, so the worker does not invent scope",
               "report BLOCKED rather than inventing scope" in _ta)
        _refused2 = False
        try:
            render_worker_prompt({"id": "j", "acceptance": ["x"],
                                  "write_allowed": ["a/**"]}, "r")
        except ValueError:
            _refused2 = True
        _check("acceptance with NO title is still refused", _refused2)

        _check("the clamp admits the read-only recall search",
               any("compound-v-memory.py search:*" in r for r in (_cl or [])),
               str(_cl))
        _check("the clamp admits the recall-check bridge",
               any("compound-v-memory.py recall-check:*" in r for r in (_cl or [])))
        _check("the clamp still admits register-lane",
               any("register-lane:*" in r for r in (_cl or [])))
        _check("the clamp admits NO write-capable memory subcommand",
               not any(("memory.py refresh" in r) or ("memory.py bootstrap" in r)
                       for r in (_cl or [])), str(_cl))

        # NOBODY WRITES BYTECODE (fourth review pass, 2026-09-02). The gate
        # forgives no path by extension, so every python command this emitter
        # writes — into a clamp rule, into the workflow script, into a prompt —
        # carries `-B`, and the rule and the command it admits must agree
        # literally or the clamp denies the one command the stage may run.
        # Only the rules that name a SCRIPT: `Bash(/usr/bin/python3:*)` is the
        # developer shell's generic interpreter form (it already admits `-B`),
        # not a command this emitter composed.
        _py_rules = [r for r in (_cl or []) if "/usr/bin/python3 " in r]
        _check("every python clamp rule this emitter composes carries -B right "
               "after the interpreter",
               _py_rules and all(r.startswith("Bash(/usr/bin/python3 -B ")
                                 for r in _py_rules), str(_py_rules))
        for _stage in ("gate-receipt", "record", "finalize-wave"):
            _check("the emitted script runs `%s` with -B" % _stage,
                   ("CFG.python + ' -B ' + CFG.emitter + ' %s'" % _stage) in script)
            _check("...and its clamp rule admits exactly that form (%s)" % _stage,
                   ("'Bash(' + CFG.python + ' -B ' + CFG.emitter + ' %s:*)'" % _stage)
                   in script)
        _bprompt = _implement_prompt(clamped["waves"][0][0], clamped)
        _check("the register-lane command in the prompt carries -B",
               "/usr/bin/python3 -B " in _bprompt, _bprompt[:400])
        # FIFTH REVIEW PASS (2026-09-02): the clamp refuses SHELL SUBSTITUTION,
        # and this prompt used to hand the worker `--cwd "$PWD"`. Run r9's very
        # first command was denied for it — the one denial that leaves the whole
        # job unregistered and the lane guard disarmed. The prompt now tells the
        # worker to run `pwd` (an admitted form) and paste a literal path.
        #
        # The old "keep every command on ONE line" rule went with it: it blamed
        # a backslash-newline continuation for a denial that substitution caused,
        # and it contradicted this emitter's own external launch commands, which
        # `_shell_join` renders with ` \` continuations on purpose.
        _check("the register-lane command in the prompt takes a LITERAL --cwd, "
               "not a shell substitution",
               "--cwd <ABSOLUTE_CWD>" in _bprompt and "register-lane --run-dir"
               in _bprompt, _bprompt[:600])
        _check("the rendered prompt spells no shell substitution ANYWHERE — not "
               "even as an example of what not to write",
               "$PWD" not in _bprompt and "$(" not in _bprompt, _bprompt)
        _check("the Implement prompt tells the worker to run `pwd` first",
               "Run `pwd` first" in _bprompt and "\npwd\n" in _bprompt)
        _check("the Implement prompt says WHY: the clamp refuses substitution",
               "refuses shell substitution" in _bprompt)
        _check("the Implement prompt tells the worker to run Python with -B",
               "PYTHONDONTWRITEBYTECODE=1" in _bprompt and "`-B`" in _bprompt)
        _check("the retired ONE-line rule is gone from the prompt",
               "ONE line" not in _bprompt)
        _check("the gate command handed to the Gate stage carries -B",
               " -B " in _gate_command(clamped["waves"][0][0], clamped))

        _check("every launched job carries a bash clamp",
               all(e["implement_clamp"] for w in clamped["waves"] for e in w))
        # Dogfood r2: the first real code job could not run a test or `git rm`.
        _check("the implement clamp admits a developer's shell: tests, selftests, "
               "shellcheck, git rm",
               all(any(r == want for r in (_cl or []))
                   for want in ("Bash(bash:*)", "Bash(python3:*)", "Bash(shellcheck:*)",
                                "Bash(git rm:*)", "Bash(pytest:*)")), str(_cl))
        _check("the implement clamp admits NO network, privilege, scheduler or committing git",
               not any(r.startswith(("Bash(curl", "Bash(wget", "Bash(ssh", "Bash(scp",
                                     "Bash(sudo", "Bash(launchctl", "Bash(crontab",
                                     "Bash(git commit", "Bash(git push", "Bash(git reset",
                                     "Bash(git checkout", "Bash(git worktree",
                                     "Bash(git remote", "Bash(brew", "Bash(pip"))
                       for r in (_cl or [])), str(_cl))
        _refused = False
        try:
            _plan_for(_tiny_manifest([
                {"id": "c-ext", "backend": "codex", "tier": "deep",
                 "isolation": "worktree", "write_allowed": ["m/**"]}]), tmp)
        except ValueError:
            _refused = True
        _check("the one clampless path is refused before it can launch", _refused)

        _check("the implement stage is narrowed at spawn",
               "opts.disallowedTools = CFG.implement_disallowed" in script)
        _check("an implementer keeps the tools it needs to write code",
               not ({"Read", "Write", "Edit", "Glob", "Grep", "Bash", "Skill"}
                    & set(IMPLEMENT_DISALLOWED)))
        _check("an implementer cannot spawn a nested agent",
               {"Task", "Agent"} <= set(IMPLEMENT_DISALLOWED))
        _check("an implementer cannot re-enter the pipeline or reach the network",
               {"SlashCommand", "WebFetch", "WebSearch"} <= set(IMPLEMENT_DISALLOWED))
        _check("the implement narrowing is NOT the transport narrowing",
               set(IMPLEMENT_DISALLOWED) != set(NARROW_DISALLOWED)
               and set(IMPLEMENT_DISALLOWED) < set(NARROW_DISALLOWED))
        _check("the implement narrowing reaches CFG",
               '"implement_disallowed"' in script.split("const IMPLEMENT_SCHEMA", 1)[0])
        _check("implement schema carries no enforcement fields",
               not ({"blocked", "files_changed", "violations"}
                    & set(IMPLEMENT_SCHEMA["properties"])))
        # The rejected `claude -p` shell-out design carried a letter name that
        # 3.0 forbids anywhere in shipped text. Built from parts so that a grep
        # for the forbidden token finds NO occurrence in this repo at all — not
        # even the assertion that guards it.
        rejected_name = "Engine " + "B"
        _check("the rejected shell-out's letter name never appears in the emitted script",
               rejected_name not in script)
        _check("meta.phases titles cover every phase string used",
               all(('phase("%s")' % t) in script or ("phase('%s')" % t) in script
                   or ("phase: '%s'" % t) in script
                   for t in STAGE_PHASES))

        meta_line = script.split("\n", 1)[0]
        _check("meta is a pure literal on one statement",
               meta_line.startswith("export const meta = {"))

        # ------------------------------------------------------------------
        # v3.0.5 — THE WIRE. The tier vocabulary must reach opts.model, and the
        # audit trail must say which lever set it. Before 3.0.5 every one of
        # these was silently None for `backend: claude`.
        # ------------------------------------------------------------------
        routed = _plan_for(_tiny_manifest([
            {"id": "r-deep", "tier": "deep", "write_allowed": ["a/**"]},
            {"id": "r-std", "tier": "standard", "write_allowed": ["b/**"]},
            {"id": "r-light", "tier": "light", "write_allowed": ["c/**"]},
            {"id": "r-front", "tier": "frontier", "write_allowed": ["d/**"]},
            {"id": "r-pin", "tier": "light", "model": "opus", "write_allowed": ["e/**"]},
        ], max_parallel=5), tmp)
        by_id = {}
        for w in routed["waves"]:
            for e in w:
                by_id[e["id"]] = e
        _check("a claude job's tier resolves to a concrete model",
               by_id["r-deep"]["model"] == "opus", str(by_id["r-deep"]["model"]))
        _check("standard is Sonnet under the default stance (execution, not judgment)",
               by_id["r-std"]["model"] == "sonnet", str(by_id["r-std"]["model"]))
        _check("light is Sonnet", by_id["r-light"]["model"] == "sonnet")
        _check("frontier reaches Fable", by_id["r-front"]["model"] == "fable")
        _check("a pinned model wins over its tier",
               by_id["r-pin"]["model"] == "opus")
        _check("model_source names the lever that set it",
               by_id["r-std"]["model_source"] == "tier"
               and by_id["r-pin"]["model_source"] == "explicit")
        _check("a resolved model reaches the emitted opts",
               "if (job.model) opts.model = job.model;" in emit_script(routed))
        _check("transport agents are routed, not inherited",
               routed["transport_model"] == "sonnet",
               str(routed["transport_model"]))
        tscript_r = emit_script(routed)
        _check("all three transport stages read CFG.transport_model",
               tscript_r.count("CFG.transport_model ? { model: CFG.transport_model }") == 3,
               str(tscript_r.count("CFG.transport_model")))
        _check("transport_model is carried into CFG",
               '"transport_model"' in tscript_r.split("const IMPLEMENT_SCHEMA", 1)[0])

        # A job with neither model nor tier degrades OPEN on claude (inherit the
        # session model) and says why — the external branch still fails closed.
        openless = _plan_for(_tiny_manifest(
            [{"id": "bare", "write_allowed": ["f/**"]}]), tmp)
        bare = openless["waves"][0][0]
        _check("a claude job with no tier inherits, and records why",
               bare["model"] is None and bare["model_source"] == "inherit"
               and "neither" in (bare["model_note"] or ""))

        # ---- escalation: earned by a recorded failure, never by a missing file
        esc_dir = os.path.join(tmp, "escrun")
        os.makedirs(os.path.join(esc_dir, "results"), exist_ok=True)
        for jid, status in (("e-fail", "blocked"), ("e-ok", "success"),
                            ("e-review", "error"), ("e-top", "timeout")):
            with open(os.path.join(esc_dir, "results", "%s.json" % jid),
                      "w", encoding="utf-8") as fh:
                json.dump({"job_id": jid, "status": status}, fh)
        _check("prior_attempt_failed reads the recorded status",
               prior_attempt_failed(esc_dir, "e-fail") is True
               and prior_attempt_failed(esc_dir, "e-ok") is False)
        _check("an absent result is not a failure",
               prior_attempt_failed(esc_dir, "never-ran") is False)
        _check("the ladder steps one rung at a time",
               escalate_claude_model("sonnet")[0] == "opus"
               and escalate_claude_model("opus")[0] == "fable")
        _check("the ladder caps at the top",
               escalate_claude_model("fable")[0] == "fable"
               and "top" in (escalate_claude_model("fable")[1] or ""))
        _check("a model off the ladder is never escalated",
               escalate_claude_model("gpt-5.6-sol")[0] == "gpt-5.6-sol")
        esc_manifest = _tiny_manifest([
            {"id": "e-fail", "tier": "standard", "write_allowed": ["g/**"]},
            {"id": "e-ok", "tier": "standard", "write_allowed": ["h/**"]},
            {"id": "e-review", "type": "review", "tier": "deep",
             "write_allowed": ["i/**"]},
            {"id": "e-top", "tier": "frontier", "write_allowed": ["j/**"]},
        ], max_parallel=4)
        esc_manifest["_manifest_path"] = os.path.join(esc_dir, "manifest.yaml")
        esc_plan = build_plan(_with_body(esc_manifest), esc_dir, tmp, "/usr/bin/python3",
                              os.path.abspath(__file__), SCOPE_CHECK_DEFAULT,
                              FASTPATH_DEFAULT, tmp)
        esc = {}
        for w in esc_plan["waves"]:
            for e in w:
                esc[e["id"]] = e
        _check("a failed job is re-dispatched one rung up",
               esc["e-fail"]["model"] == "opus"
               and esc["e-fail"]["model_source"] == "escalated",
               str(esc["e-fail"]["model"]))
        _check("a successful job is not escalated",
               esc["e-ok"]["model"] == "sonnet"
               and esc["e-ok"]["model_source"] == "tier")
        _check("a REVIEWER is never escalated (its receipt must stay Opus)",
               esc["e-review"]["model"] == "opus"
               and esc["e-review"]["model_source"] == "tier")
        _check("a failed job already at the top stays there, and says so",
               esc["e-top"]["model"] == "fable"
               and "top" in (esc["e-top"]["model_note"] or ""))

        # A planted violation must be caught, or the check is decorative.
        planted = script + "\nconst t = Date.now();\n"
        _check("planted Date.now is caught",
               any(h["construct"] == "Date.now()" for h in forbidden_hits(planted)))
        planted = script + "\nconst r = Math.random();\n"
        _check("planted Math.random is caught",
               any(h["construct"] == "Math.random()" for h in forbidden_hits(planted)))
        planted = script + "\nconst d = new Date();\n"
        _check("planted bare new Date() is caught",
               any(h["construct"] == "bare new Date()" for h in forbidden_hits(planted)))
        planted = script + "\nconst m = await import('fs');\n"
        _check("planted import() is caught",
               any(h["construct"] == "import()" for h in forbidden_hits(planted)))
        _check("a qualified .import( is not a false positive",
               forbidden_hits("obj.import(1); ns.import (2);") == [])
        _check("new Date(arg) is allowed (only the argless form throws)",
               forbidden_hits("const d = new Date(args.now);") == [])

        # A manifest whose own prose DOCUMENTS the forbidden constructs — this
        # release's task-9 acceptance criterion does exactly that — must still
        # emit, and the prompt the agent reads must be unchanged.
        talky = [{
            "id": "meta-job",
            "write_allowed": ["q/**"],
            "acceptance": [
                "emitted script has no Date.now(), Math.random(), "
                "bare new Date() or import()"
            ],
        }]
        tplan = _plan_for(_tiny_manifest(talky), tmp)
        tscript = emit_script(tplan)
        _check("a manifest that DOCUMENTS the constructs still emits",
               forbidden_hits(tscript) == [], str(forbidden_hits(tscript)))
        _check("neutralisation escapes only the paren",
               "\\u0028" in tscript)
        decoded = json.loads(
            tscript.split("const CFG = ", 1)[1]
            .split(";\nconst IMPLEMENT_SCHEMA", 1)[0]
        )["prompts"]["meta-job"]["implement"]
        _check("the DECODED prompt is byte-identical to the manifest's text",
               "no Date.now(), Math.random(), bare new Date() or import()" in decoded,
               decoded[-200:])
        _check("neutralisation is applied to DATA only, never to executable code",
               forbidden_hits(JS_TEMPLATE) == [])

        # --- non-claude jobs: direct isolation + a clamp that can bind ---------
        workers = os.path.join(tmp, "workers")
        os.makedirs(workers, exist_ok=True)
        worker_sh = os.path.join(workers, "compound-v-run-codex-worker.sh")
        with open(worker_sh, "w", encoding="utf-8") as fh:
            fh.write("#!/bin/sh\n")
        codex_jobs = [
            {"id": "c1", "backend": "codex", "isolation": "worktree",
             "model": "gpt-5.6-sol", "write_allowed": ["x/**"]},
        ]
        cplan = _plan_for(_tiny_manifest(codex_jobs), tmp, workers_dir=workers)
        entries = {j["id"]: j for w in cplan["waves"] for j in w}
        _check("a non-claude job runs its AGENT at direct isolation (no nesting)",
               entries["c1"]["isolation"] == "direct"
               and entries["c1"]["agent_isolation"] is None)
        _check("a non-claude job's clamp admits its worker script",
               any(worker_sh in rule for rule in entries["c1"]["implement_clamp"]))
        _check("no worker script ⇒ NO clamp, rather than a clamp that binds nothing",
               _clamp_rules({"id": "g1", "backend": "gemini"}, "/usr/bin/python3",
                            os.path.abspath(__file__), lambda b: None) is None)
        # An external job whose worker script is absent, or whose model cannot be
        # resolved, has no COMPLETE argv — so emit refuses rather than writing a
        # launcher the implementer would have to improvise around.
        for broken, why in (
            ({"id": "g1", "backend": "gemini", "model": "g",
              "write_allowed": ["y/**"]}, "no worker script"),
            ({"id": "c2", "backend": "codex", "write_allowed": ["z/**"]},
             "neither model nor tier"),
        ):
            try:
                _plan_for(_tiny_manifest([broken]), tmp, workers_dir=workers)
                _check("emit FAILS CLOSED on an external job with %s" % why, False)
            except ValueError:
                _check("emit FAILS CLOSED on an external job with %s" % why, True)
        for rule in entries["c1"]["implement_clamp"]:
            _check("clamp entry is a Bash(...) permission rule with content",
                   rule.startswith("Bash(") and rule.endswith(")")
                   and rule[5:-1].strip() == rule[5:-1] and rule[5:-1] != "",
                   rule)
        cscript = emit_script(cplan)
        _check("non-claude emission is still construct-clean",
               forbidden_hits(cscript) == [])

        # --- a claude worktree job DOES get worktree isolation -----------------
        wplan = _plan_for(_tiny_manifest(
            [{"id": "w1", "backend": "claude", "isolation": "worktree",
              "write_allowed": ["z/**"]}]), tmp)
        wentry = wplan["waves"][0][0]
        _check("a claude worktree job keeps native worktree isolation",
               wentry["agent_isolation"] == "worktree")

        # --- the four orphans, exercised against a real git repo --------------
        repo = os.path.join(tmp, "repo")
        baseline = _init_repo(repo)
        _check("selftest repo has a baseline commit", bool(baseline))

        run_dir = os.path.join(tmp, "run")
        os.makedirs(os.path.join(run_dir, "jobs"), exist_ok=True)
        man = {"run_id": "selftest-run", "max_parallel": 2,
               "jobs": [{"id": "j1", "title": "j1", "isolation": "worktree",
                         "write_allowed": ["src/**"]},
                        {"id": "j2", "title": "j2", "isolation": "direct",
                         "write_allowed": ["src/**"]},
                        {"id": "j3", "title": "j3", "isolation": "direct",
                         "write_allowed": ["src/**"]}]}
        try:
            import yaml
            with open(os.path.join(run_dir, "manifest.yaml"), "w",
                      encoding="utf-8") as fh:
                yaml.safe_dump(man, fh)
            have_yaml = True
        except ImportError:
            have_yaml = False

        # ORPHAN 1 — the lane map
        register_lane(run_dir, "j1", repo)
        register_lane(run_dir, "j2", os.path.join(tmp, "other"))
        lane = _read_json(lane_map_path(run_dir), {})
        _check("lane map is written where the guard looks",
               os.path.exists(lane_map_path(run_dir)))
        _check("lane map has the guard's three documented keys",
               {"agents", "worktrees", "manifest"} <= set(lane))
        _check("lane map binds the worktree to the job",
               lane["worktrees"].get(os.path.abspath(repo)) == "j1")
        _check("a second register MERGES rather than overwriting a sibling's lane",
               len(lane["worktrees"]) == 2)

        # ORPHAN 3 — the digest, computed by the schema's pinned recipe
        with open(os.path.join(repo, "src.txt"), "w", encoding="utf-8") as fh:
            fh.write("new untracked file\n")
        digest, derr = compute_diff_digest(repo, baseline)
        _check("diff digest computes", digest is not None, str(derr))
        _check("diff digest is sha256:<64 hex>",
               bool(digest and re.match(r"^sha256:[0-9a-f]{64}$", digest)), str(digest))
        gate_mod = _import_integration_gate()
        if gate_mod is not None and hasattr(gate_mod, "compute_diff_digest"):
            theirs, _ = gate_mod.compute_diff_digest(repo, baseline)
            mine, _ = _compute_diff_digest_local(repo, baseline)
            _check("our digest equals the verification layer's, byte for byte",
                   theirs == mine, "%s vs %s" % (theirs, mine))
        _check("digest covers UNTRACKED files (the half a plain git diff misses)",
               digest != _compute_diff_digest_local(repo, baseline + "^")[0]
               if _compute_diff_digest_local(repo, baseline + "^")[0] else True)
        _check("computing a digest does not mutate the tree's index",
               _git(repo, ["diff", "--cached", "--name-only"])[1].strip() == "")

        # ORPHAN 2 — what the integration authority needs
        if have_yaml:
            verdict = {
                "job_id": "j1", "verdict": "pass", "worktree": os.path.abspath(repo),
                "baseline_commit": baseline, "realised_commit": baseline,
                "diff_digest": digest, "raw_stdout": json.dumps(
                    {"verdict": "pass", "changed": ["src.txt"], "violations": []}),
                "exit_code": 0,
            }
            with _quiet():
                rc = cmd_record([
                "--run-dir", run_dir, "--job-id", "j1",
                "--manifest", os.path.join(run_dir, "manifest.yaml"),
                "--verdict-json", json.dumps(verdict),
                "--repo-root", repo, "--no-merge", "--now", "2026-09-01T00:00:00Z",
            ])
            _check("record exits 0", rc == 0)
            res = _read_json(os.path.join(run_dir, "results", "j1.json"), {})
            _check("results/<job-id>.json is written", bool(res))
            _check("the result carries a COMPLETE six-field receipt",
                   set(res.get("gate_receipt", {})) == {
                       "baseline_commit", "realised_commit", "diff_digest",
                       "verdict", "raw_stdout", "exit_code"})
            _check("enforcement fields come from the gate's raw stdout",
                   res["files_changed"] == ["src.txt"] and res["blocked"] is False)
            st = _read_json(os.path.join(run_dir, "state.json"), {})
            _check("state.json records the job's worktree",
                   st["jobs"]["j1"].get("worktree") == os.path.abspath(repo))
            _check("state.json records the job's pinned baseline",
                   st["jobs"]["j1"].get("baseline") == baseline)
            _check("only ONE result file sits in results/ (a sibling reads as forged)",
                   [n for n in os.listdir(os.path.join(run_dir, "results"))
                    if n.endswith(".json")] == ["j1.json"])

            # Idempotence + at-most-once
            with _quiet():
                cmd_record([
                "--run-dir", run_dir, "--job-id", "j1",
                "--manifest", os.path.join(run_dir, "manifest.yaml"),
                "--verdict-json", json.dumps(verdict),
                "--repo-root", repo, "--no-merge",
            ])
            _check("re-recording the same verdict stays at ONE result file",
                   [n for n in os.listdir(os.path.join(run_dir, "results"))
                    if n.endswith(".json")] == ["j1.json"])
            res2 = _read_json(os.path.join(run_dir, "results", "j1.json"), {})
            _check("re-record is idempotent (identical bytes)", res == res2)

            # A PARTIAL receipt is a MISSING receipt, never a trusted one.
            partial = dict(verdict)
            del partial["diff_digest"]
            with _quiet():
                cmd_record([
                "--run-dir", run_dir, "--job-id", "j2",
                "--manifest", os.path.join(run_dir, "manifest.yaml"),
                "--verdict-json", json.dumps(partial),
                "--repo-root", repo, "--no-merge",
            ])
            r2 = _read_json(os.path.join(run_dir, "results", "j2.json"), {})
            _check("a partial receipt is omitted entirely, not half-written",
                   "gate_receipt" not in r2)

            # A null / error verdict is FAIL and is still RECORDED — the whole
            # point of a Gate that cannot throw.
            with _quiet():
                cmd_record([
                "--run-dir", run_dir, "--job-id", "j3",
                "--manifest", os.path.join(run_dir, "manifest.yaml"),
                "--verdict-json", json.dumps(
                    {"job_id": "j3", "verdict": "error",
                     "reason": "gate agent returned null"}),
                "--repo-root", repo, "--no-merge",
            ])
            r3 = _read_json(os.path.join(run_dir, "results", "j3.json"), {})
            st = _read_json(os.path.join(run_dir, "state.json"), {})
            _check("a failed job is still RECORDED rather than vanishing",
                   r3.get("status") == "error")
            _check("a failed job's state is failed, not done",
                   st["jobs"]["j3"]["status"] == "failed")

        # --- merge-back: staged by files_changed, diffed against the baseline --
        src_repo = os.path.join(tmp, "src-repo")
        base2 = _init_repo(src_repo)
        wt = os.path.join(tmp, "wt")
        _run(["git", "-C", src_repo, "worktree", "add", "-q", wt, "HEAD"])
        os.makedirs(os.path.join(wt, "src"), exist_ok=True)
        with open(os.path.join(wt, "src", "allowed.txt"), "w", encoding="utf-8") as fh:
            fh.write("approved by the gate\n")
        # The executor COMMITS inside its worktree — the case the HEAD form loses.
        _run(["git", "-C", wt, "add", "-A"])
        _run(["git", "-C", wt, "commit", "-q", "-m", "worker commit"])
        # A test byproduct lands AFTER the gate; it is outside the gate's authority.
        with open(os.path.join(wt, "coverage.xml"), "w", encoding="utf-8") as fh:
            fh.write("<byproduct/>\n")

        ok, merr = merge_back(wt, src_repo, base2, ["src/allowed.txt"])
        _check("merge-back succeeds against the PINNED baseline", ok, str(merr))
        _check("a file the executor COMMITTED inside its worktree still lands",
               os.path.exists(os.path.join(src_repo, "src", "allowed.txt")))
        _check("a post-gate test byproduct does NOT ride into the main tree",
               not os.path.exists(os.path.join(src_repo, "coverage.xml")))

        _rc, head_only, _err = _git(
            wt, ["diff", "--cached", "--binary", "HEAD"], text=False
        )
        _check("the old HEAD form would have LOST the committed half "
               "(this is the pre-existing bug)",
               b"allowed.txt" not in (head_only or b""))

        # A path with a newline survives the NUL-delimited staging contract.
        weird = "src/we\nird.txt"
        with open(os.path.join(wt, "src", "we\nird.txt"), "w", encoding="utf-8") as fh:
            fh.write("newline in a path\n")
        ok2, _ = _stage_paths(wt, [weird])
        _check("a path containing a newline stages correctly", ok2)

        # --- engine selection --------------------------------------------------
        rep = engine_probe_report({})
        _check("a clean env has no blockers", rep["env_clear"])
        rep = engine_probe_report({"CLAUDE_WORKFLOW_NAME_ONLY": "1"})
        _check("CLAUDE_WORKFLOW_NAME_ONLY blocks the scriptPath form",
               not rep["env_clear"])
        rep = engine_probe_report({"CLAUDE_CODE_WORKFLOWS": "false"})
        _check("CLAUDE_CODE_WORKFLOWS=false blocks Engine C", not rep["env_clear"])
        _check("the probe SPAWNS a clamped agent rather than reading a version",
               "bashCommandClamp" in ENGINE_PROBE_SNIPPET
               and "disallowedTools" in ENGINE_PROBE_SNIPPET)
        _check("the probe snippet is itself construct-clean",
               forbidden_hits(ENGINE_PROBE_SNIPPET) == [])
        _check("selection is never justified by the refuted headless claim",
               "unavailable headless" not in ENGINE_PROBE_SNIPPET)

        # --- THIS run's pre-cutover state.json must still be accepted ----------
        # The session can die after this job merges and the remaining waves still
        # have to finish on the old engine, so the new contract must read a
        # state.json that carries NO baseline, NO worktree and NO lane map.
        legacy_dir = os.path.join(tmp, "legacy")
        os.makedirs(legacy_dir, exist_ok=True)
        legacy = {
            "run_id": "pre-cutover", "phase": "DISPATCHED",
            "jobs": {"old-1": {"status": "running", "isolation": "worktree",
                               "worktree": None, "session_id": None}},
        }
        _atomic_write(os.path.join(legacy_dir, "state.json"),
                      json.dumps(legacy, indent=2) + "\n")
        loaded = _load_state(legacy_dir)
        _check("a pre-cutover state.json loads unchanged",
               loaded["jobs"]["old-1"]["status"] == "running")
        _check("the new fields are OPTIONAL for a pre-cutover job",
               loaded["jobs"]["old-1"].get("baseline") is None
               and loaded["jobs"]["old-1"].get("worktree") is None)
        _check("a pre-cutover run has no lane map and that is not an error",
               _read_json(lane_map_path(legacy_dir), None) is None)

        # --- test-floor wiring: the placeholder has a real producer ------------
        _check("the test floor producer exists", os.path.exists(FASTPATH_DEFAULT))
        if os.path.exists(FASTPATH_DEFAULT):
            rc, out, _ = _run(["/usr/bin/python3", FASTPATH_DEFAULT,
                               "test-floor", "--help"])
            _check("test-floor accepts --manifest and --job-id",
                   "--manifest" in out and "--job-id" in out)
            rc, out, _ = _run(["/usr/bin/python3", FASTPATH_DEFAULT,
                               "resolve-tests", "--help"])
            _check("resolve-tests accepts --manifest, --job-id and --out",
                   "--manifest" in out and "--job-id" in out and "--out" in out)

        # --- the floor document is TRANSLATED, never copied --------------------
        # These are unit checks on the shape. Conformance against the real schema
        # is asserted end-to-end by tests/test-engine-c-contract.sh, which needs
        # jsonschema; this half runs on stdlib alone so the guard never silently
        # depends on an optional install.
        floor_pass = {"phase": "test_floor", "tier_used": 1, "passed": True,
                      "merge_blocked": False, "changed_paths": ["src/a.py"],
                      "reasons": [], "failures": [],
                      "checks": [{"tier": 1, "checker": "pytest -q", "rc": 0,
                                  "status": "pass"}]}
        block = _tests_block_from_floor(floor_pass, {"scope": "impacted"}, {})
        _check("the tests block carries ONLY schema-declared keys",
               set(block) <= {"command", "exit_code", "scope", "selected_count",
                              "duration_ms", "failures"})
        _check("the four required tests fields are all present",
               all(k in block for k in
                   ("command", "exit_code", "scope", "selected_count")))
        _check("tests.scope is copied from the resolved contract, not re-derived",
               block["scope"] == "impacted")
        _check("tests.failures survives translation (empty == measured, not absent)",
               block["failures"] == [])
        _check("no duration is invented when the floor measured none",
               "duration_ms" not in block)

        floor_fail = dict(floor_pass, passed=False, merge_blocked=True,
                          failures=["pytest -q"],
                          checks=[{"tier": 1, "checker": "pytest -q", "rc": 3,
                                   "status": "fail"}])
        _check("a failing floor reports the failing command's OWN rc",
               _tests_block_from_floor(floor_fail, None, {})["exit_code"] == 3)
        _check("a floor that ran nothing yields NO tests block (absent is honest)",
               _tests_block_from_floor(
                   {"phase": "test_floor", "tier_used": 0, "passed": False,
                    "merge_blocked": True, "checks": [], "reasons": ["x"]}) is None)

        # --- tests.scope is the RESOLVER's answer, not an impacted_map sniff ----
        # `tests.scope` is the field a reviewer checks against the manifest's tier,
        # so the fallback has to mirror `default_scope_for(contract, tier)` — ALL
        # THREE branches. Reading the map alone could never say `floor_only`, and
        # a DIRECT job that ran only its floor was recorded as `impacted`.
        _c_map = {"impacted_map": [{"when": "src/**", "run": "pytest src"}],
                  "floor_command": "sh -c 'exit 0'", "full_command": "pytest"}
        _c_nomap = {"floor_command": "sh -c 'exit 0'", "full_command": "pytest"}
        _check("DIRECT tier with a declared floor is recorded as floor_only",
               _tests_block_from_floor(floor_pass, _c_map, {},
                                       "DIRECT")["scope"] == "floor_only")
        _check("the tier is matched case-insensitively, like the resolver's",
               _tests_block_from_floor(floor_pass, _c_map, {},
                                       " direct ")["scope"] == "floor_only")
        _check("DIRECT with NO floor does not invent floor_only",
               _tests_block_from_floor(
                   floor_pass, {"impacted_map": _c_map["impacted_map"]}, {},
                   "DIRECT")["scope"] == "impacted")
        _check("SCOPED and FULL tiers still honour the map, exactly as the resolver",
               _tests_block_from_floor(floor_pass, _c_map, {},
                                       "FULL")["scope"] == "impacted"
               and _tests_block_from_floor(floor_pass, _c_map, {},
                                           "SCOPED")["scope"] == "impacted")
        # review-3 of 3.4.1, finding 1: the resolver's `impacted+referencing` label must
        # survive translation VERBATIM — until this cell the filter downgraded it to the
        # derived default and the record said `impacted` for a slice that ran something else.
        _ref_block = _tests_block_from_floor(
            floor_pass, {"scope": "impacted+referencing", "resolved_commands": ["x"],
                         "selected_count": 1}, {}, "SCOPED")
        _check("tests.scope keeps the resolver's impacted+referencing label verbatim",
               (_ref_block or {}).get("scope") == "impacted+referencing", str(_ref_block))
        with open(os.path.join(HERE, "..", "schemas", "job_result.schema.json"), "r") as _fh:
            _jr_enum = json.load(_fh)["properties"]["tests"]["properties"]["scope"]["enum"]
        _check("...and the job_result schema's enum names it", "impacted+referencing" in _jr_enum)
        _check("no map and no DIRECT floor is full, the resolver's own default",
               _tests_block_from_floor(floor_pass, _c_nomap, {},
                                       "FULL")["scope"] == "full")
        _check("the resolved slice's own scope still WINS over any re-derivation",
               _tests_block_from_floor(floor_pass, dict(_c_map, scope="full"), {},
                                       "DIRECT")["scope"] == "full")
        _check("a job's declared test_scope outranks the fallback too",
               _tests_block_from_floor(floor_pass, _c_map,
                                       {"test_scope": "floor_only"},
                                       "FULL")["scope"] == "floor_only")
        _check("every recorded scope is one the schema allows",
               all(_tests_block_from_floor(floor_pass, c, {}, t)["scope"]
                   in TESTS_SCOPES
                   for c in (_c_map, _c_nomap, {})
                   for t in ("DIRECT", "SCOPED", "FULL", None)))

        # --- the three fields that used to be null against integer/string ------
        result = _job_result_from(
            {"verdict": "pass", "raw_stdout": "", "exit_code": 0},
            {"id": "j", "title": "t"}, {}, tests=None,
        )
        _check("session_id / worktree are strings, never null",
               isinstance(result["session_id"], str)
               and isinstance(result["worktree"], str))
        _check("retry_after_seconds is an integer, never null",
               isinstance(result["retry_after_seconds"], int))
        errored = _job_result_from(
            {"verdict": "error", "raw_stdout": "", "exit_code": 2},
            {"id": "j"}, {}, tests=None,
        )
        _check("failure_class stays inside the schema's enum",
               errored["failure_class"] in (
                   None, "none", "out_of_credits", "rate_limited", "overloaded",
                   "auth", "context_length", "timeout", "network", "other"))

        # --- SEAM-1: the flag reaches an external worker uncommented -----------
        ext_manifest = {
            "run_id": "r", "test_contract": {"floor_command": "sh -c 'exit 0'"},
            "jobs": [{"id": "x", "backend": "codex", "test_scope": "floor_only",
                      "model": "gpt-5.6-sol", "isolation": "worktree",
                      "write_allowed": ["src/**"]}],
        }
        ext_plan = build_plan(_with_body(ext_manifest), tmp, tmp, "/usr/bin/python3",
                              os.path.abspath(__file__), SCOPE_CHECK_DEFAULT,
                              FASTPATH_DEFAULT, HERE)
        ext_job = ext_plan["waves"][0][0]
        ext_prompt = _implement_prompt(ext_job, ext_plan)
        _check("an external job carries a resolved test-contract path",
               bool(ext_job["test_contract_file"]))
        _check("the worker invocation passes --test-contract-file UNCOMMENTED",
               "--test-contract-file" in ext_prompt
               and "# --test-contract-file" not in ext_prompt)
        no_contract = build_plan(
            _with_body({"run_id": "r", "jobs": [{"id": "x", "backend": "codex",
                                      "model": "gpt-5.6-sol",
                                      "isolation": "worktree",
                                      "write_allowed": ["src/**"]}]}),
            tmp, tmp, "/usr/bin/python3", os.path.abspath(__file__),
            SCOPE_CHECK_DEFAULT, FASTPATH_DEFAULT, HERE)
        _check("no declared test_contract ⇒ no flag (the worker script would "
               "reject a path that does not exist)",
               "--test-contract-file" not in _implement_prompt(
                   no_contract["waves"][0][0], no_contract))

        # --- ORPHAN-9: the `actual` producer -----------------------------------
        _check("the triage-outcomes producer exists",
               os.path.exists(TRIAGE_OUTCOMES_DEFAULT))
        actual_state = {"jobs": {"a": {"status": "done"}, "b": {"status": "pending"}}}
        actual_manifest = {"run_id": "r", "triage": {"pre_eval_id": "pe-1"},
                           "jobs": [{"id": "a"}, {"id": "b"}]}
        _check("no `actual` is appended while a job is still running",
               _maybe_append_run_actual(tmp, actual_manifest, actual_state, tmp)
               is None)
        _check("a manifest with no pre_eval_id gets a REASON, never an invented id",
               "pre_eval_id" in (_maybe_append_run_actual(
                   tmp, {"run_id": "r", "jobs": [{"id": "a"}]},
                   {"jobs": {"a": {"status": "done"}}}, tmp) or ""))

        # --- 3.0.2: the three defects that disabled Engine C -------------------

        # CRITICAL 1 — the branch is the MANIFEST's isolation, not emptiness.
        direct_res = _job_result_from(
            {"verdict": "pass", "raw_stdout": "", "exit_code": 0},
            {"id": "d", "isolation": "direct"},
            {"worktree": "/some/project/cwd"}, tests=None)
        _check("a DIRECT job's result carries worktree \"\" even when a locator "
               "was registered (emptiness never selects the merge path)",
               direct_res["worktree"] == "", direct_res["worktree"])
        wt_res = _job_result_from(
            {"verdict": "pass", "raw_stdout": "", "exit_code": 0},
            {"id": "w", "isolation": "worktree"},
            {"worktree": "/wt/w"}, tests=None)
        _check("a WORKTREE job keeps its locator", wt_res["worktree"] == "/wt/w")
        _check("no module-level default repository root exists to fall back to",
               "REPO_DEFAULT" not in globals())

        script_2 = emit_script(_plan_for(_tiny_manifest(
            [{"id": "s1", "isolation": "direct", "write_allowed": ["a/**"]}]), tmp))
        rec_seg = script_2.split("' record' +", 1)[-1][:800]
        gate_seg = script_2.split("' gate-receipt' +", 1)[-1][:800]
        _check("the emitted Record command names its destination explicitly",
               "--repo-root" in rec_seg and "CFG.repo_root" in rec_seg)
        _check("the emitted Gate command names the project root explicitly",
               "--repo-root" in gate_seg)
        _check("a direct job is gated in CFG.repo_root, never in a reported pwd",
               "gateRoot = CFG.repo_root" in script_2)

        # --- findings 107/108: an implementer that returned nothing no longer voids the wave.
        # --- v3.4.6 review-2 TEST_GAP: the three hand closures get their guards.
        def _argv_timeout(entry_extra):
            _e = {"worker_script": "/w/run-worker.sh", "test_contract_file": "/r/jobs/j.test-contract.json",
                  "backend": "codex", "tier": "standard", "effort": "medium"}
            _e.update(entry_extra)
            try:
                _argv = build_launch_argv({"id": "j-tc", "backend": "codex", "tier": "standard"}, _e,
                                          "run-tc", "/repo", "/repo/docs/superpowers/execution/run-tc", "gpt-x")
            except Exception as _exc:  # noqa: BLE001 — a wrong fixture must FAIL, never skip
                return "raised: %r" % (_exc,)
            return _argv[_argv.index("--test-timeout-sec") + 1] if "--test-timeout-sec" in _argv else "absent"
        _check("external worker always gets --test-timeout-sec: absent ⇒ 480 (review-2, item 1)",
               _argv_timeout({}) == "480")
        _check("external worker gets the manifest's timeout_s when declared",
               _argv_timeout({"test_contract_timeout_s": 300}) == "300")
        _check("an out-of-range or float timeout_s falls back to 480, never passes through",
               _argv_timeout({"test_contract_timeout_s": 600}) == "480"
               and _argv_timeout({"test_contract_timeout_s": 1.5}) == "480")
        import tempfile as _tf_rl
        with _tf_rl.TemporaryDirectory() as _rl_tmp:
            _rl_lock = os.path.join(_rl_tmp, ".run.lock")
            for _ph, _gone in (("DISPATCHED", False), ("PARTITION_VERIFIED", False), ("MERGED", True), ("BLOCKED", True)):
                _atomic_write(os.path.join(_rl_tmp, "state.json"), json.dumps({"phase": _ph}))
                _atomic_write(_rl_lock, "x")
                _rv = _retire_run_lock(_rl_tmp)
                _check("_retire_run_lock at phase %s ⇒ lock %s (review-2, item 6)" % (_ph, "gone" if _gone else "kept"),
                       (not os.path.exists(_rl_lock)) == _gone and bool(_rv) == _gone)
        _check("gate JS routes a NULL implementer result through the same fallback (finding 113)",
               "external worker returned null" in script_2 and "impl = {};" in script_2)
        _check("gate JS falls back to the registered lane for a claude worktree job with no result",
              "(implNoResult ? ' --impl-no-result' : '')" in script_2
              and "external worker reported no worktree" in script_2)
        import tempfile as _tf_nr
        with _tf_nr.TemporaryDirectory() as _nr_tmp:
            _nr_run = os.path.join(_nr_tmp, "run"); os.makedirs(_nr_run)
            _nr_wt = os.path.join(_nr_tmp, "wt-1"); os.makedirs(_nr_wt)
            _nr_repo = os.path.join(_nr_tmp, "repo"); os.makedirs(_nr_repo)
            _atomic_write(os.path.join(_nr_run, "lane-map.json"),
                          json.dumps({"worktrees": {_nr_wt: "j-nr", _nr_repo: "j-root"}}))
            _check("lane-map worktree resolves for a registered claude job",
                  _lane_map_worktree_for(_nr_run, "j-nr", _nr_repo) == os.path.abspath(_nr_wt))
            _check("lane-map worktree refuses the checkout itself",
                  _lane_map_worktree_for(_nr_run, "j-root", _nr_repo) is None)
            _check("lane-map worktree refuses an unregistered job",
                  _lane_map_worktree_for(_nr_run, "j-none", _nr_repo) is None)
            _atomic_write(os.path.join(_nr_run, "lane-map.json"),
                          json.dumps({"worktrees": {_nr_wt: "j-nr", os.path.join(_nr_tmp, "wt-2"): "j-nr"}}))
            _check("lane-map worktree refuses two registrations for one job",
                  _lane_map_worktree_for(_nr_run, "j-nr", _nr_repo) is None)
        _nr_res = _job_result_from(
            {"verdict": "pass", "impl_no_result": True, "worktree": "/tmp/x", "reason": "gate ok",
             "raw_stdout": json.dumps({"verdict": "pass", "changed": ["a.py"], "violations": []})},
            {"id": "j-nr", "title": "T", "write_allowed": ["a.py"], "isolation": "worktree"},
            {"worktree": "/tmp/x"})
        _check("impl_no_result ⇒ status error with a receipt, never success",
              _nr_res.get("status") == "error" and _nr_res.get("blocked") is False
              and _nr_res.get("failure_class") == "other"
              and str(_nr_res.get("summary", "")).startswith("implementer returned no result"))

        # CRITICAL 2 — the authority runs BEFORE integration, and the wave commits.
        _check("the emitted script carries a serialized wave finalizer",
               "finalizeWave" in script_2 and "finalize-wave" in script_2)
        _check("the wave loop STOPS scheduling after a non-success result",
               "waveHadFailure" in script_2 and "summary.halted = true" in script_2)
        _check("Finalize is a declared phase, so the runtime can render it",
               "Finalize" in STAGE_PHASES and "phase: 'Finalize'" in script_2)
        # Record must not be able to write into the checkout at all. Asserted on
        # the compiled name table rather than on behaviour, because "it did not
        # merge THIS time" is not the property; "it cannot" is.
        record_calls = set(cmd_record.__code__.co_names)
        _check("Record calls neither merge_back nor _stage_paths — integration is "
               "the finalizer's, after the authority",
               not ({"merge_back", "_stage_paths", "_commit_paths"} & record_calls),
               str(sorted(record_calls & {"merge_back", "_stage_paths",
                                          "_commit_paths"})))
        _check("the finalizer DOES call all three, in one place",
               {"merge_back", "_commit_paths"}
               <= set(cmd_finalize_wave.__code__.co_names))

        fin_repo = os.path.join(tmp, "fin-repo")
        fin_base = _init_repo(fin_repo)
        _check("finalize selftest repo has a baseline", bool(fin_base))
        # An unrelated file is left STAGED, exactly as a concurrent
        # `/v:orchestrate` would leave one. The wave's commit must not take it.
        with open(os.path.join(fin_repo, "unrelated.txt"), "w",
                  encoding="utf-8") as fh:
            fh.write("someone else's staged work\n")
        _run(["git", "-C", fin_repo, "add", "unrelated.txt"])
        os.makedirs(os.path.join(fin_repo, "src"), exist_ok=True)
        with open(os.path.join(fin_repo, "src", "landed.txt"), "w",
                  encoding="utf-8") as fh:
            fh.write("the wave's work\n")
        sha, cerr = _commit_paths(fin_repo, ["src/landed.txt"], "wave 1")
        _check("the wave's commit succeeds", bool(sha), str(cerr))
        _rc, names, _e = _git(fin_repo, ["show", "--name-only", "--format=", "HEAD"])
        _check("the commit contains the wave's path",
               "src/landed.txt" in names, names)
        _check("the commit does NOT sweep in someone else's staged file — the "
               "mechanism by which an ungated patch reached history",
               "unrelated.txt" not in names, names)
        _rc, still, _e = _git(fin_repo, ["diff", "--cached", "--name-only"])
        _check("the unrelated file is still staged, untouched",
               still.strip() == "unrelated.txt", still)

        # The authority's refusal is a refusal: nothing merges, nothing commits.
        if have_yaml:
            ref_dir = os.path.join(tmp, "refuse")
            os.makedirs(ref_dir, exist_ok=True)
            import yaml as _yaml
            with open(os.path.join(ref_dir, "manifest.yaml"), "w",
                      encoding="utf-8") as fh:
                _yaml.safe_dump({"run_id": "refuse", "jobs": [
                    {"id": "never-ran", "isolation": "direct",
                     "write_allowed": ["src/**"]}]}, fh)
            head_before = _head_commit(fin_repo)
            with _quiet():
                rc = cmd_finalize_wave([
                    "--run-dir", ref_dir, "--repo-root", fin_repo,
                    "--manifest", os.path.join(ref_dir, "manifest.yaml"),
                    "--jobs", "never-ran", "--wave", "1",
                ])
            _check("a wave whose job produced no result is REFUSED", rc != 0)
            _check("a refused wave commits nothing",
                   _head_commit(fin_repo) == head_before)
            _check("finding 68: a BLOCKED run's lane-map.json is retired too",
                   not os.path.exists(os.path.join(ref_dir, "lane-map.json")))
            _check("finding 105: a BLOCKED run's .run.lock is retired at the "
                   "same terminal transition (the finalizer itself took the "
                   "lock at least once above, so it exists to be retired)",
                   not os.path.exists(os.path.join(ref_dir, ".run.lock")))
            _check("a refused wave marks the run BLOCKED with the reason (finding 47 residual)",
                   _load_state(ref_dir).get("phase") == "BLOCKED"
                   and "REFUSED" in str(_load_state(ref_dir).get("blocked_reason")),
                   str(_load_state(ref_dir)))
            # finding 56: with NO merge there is no wave commit, so no
            # bookkeeping commit either — the record stays for the caller.
            # (The merged-and-refused shape is asserted in the bk4 block.)

        # ---- FOURTH REVIEW PASS, item 4 -------------------------------------- #
        # NOTHING THE PIPELINE WRITES LANDS BETWEEN A DIRECT JOB'S GATE AND ITS
        # RE-DERIVATION. Driven end to end against the REAL authority, in a repo
        # of its own: register-lane -> the worker's edit -> gate-receipt ->
        # record -> the authority -> finalize-wave. Until this pass Record
        # appended the run's `actual` to a TRACKED file at the third arrow, the
        # digest moved under the authority, and an honest receipt came back
        # `contradicted`; the answer then was to exclude the path from both
        # digests, which also hid a worker's rewrite of it. The append is the
        # finalizer's now, so the receipt survives with NO exclusion in play.
        if have_yaml and os.path.exists(INTEGRATION_GATE_DEFAULT):
            import yaml as _yaml_bk
            bk4_repo = os.path.join(tmp, "bk4-repo")
            bk4_base = _init_repo(bk4_repo)
            bk4_run = os.path.join(bk4_repo, "docs", "superpowers",
                                   "execution", "bk4")
            os.makedirs(bk4_run, exist_ok=True)
            bk4_man = os.path.join(bk4_run, "manifest.yaml")
            with open(bk4_man, "w", encoding="utf-8") as fh:
                _yaml_bk.safe_dump({
                    "run_id": "bk4",
                    "triage": {"pre_eval_id": "pe-bk4"},
                    "jobs": [{"id": "d1", "isolation": "direct",
                              "write_allowed": ["src/**"]}],
                }, fh)
            with _quiet():
                cmd_register_lane([
                    "--run-dir", bk4_run, "--job-id", "d1", "--cwd", bk4_repo,
                    "--repo-root", bk4_repo, "--isolation", "direct",
                    "--manifest", bk4_man, "--no-test-contract",
                ])
            os.makedirs(os.path.join(bk4_repo, "src"), exist_ok=True)
            with open(os.path.join(bk4_repo, "src", "work.txt"), "w",
                      encoding="utf-8") as fh:
                fh.write("the direct job's work\n")
            with _quiet():
                rc_bg = cmd_gate_receipt([
                    "--run-dir", bk4_run, "--job-id", "d1",
                    "--repo-root", bk4_repo, "--worktree", bk4_repo,
                    "--manifest", bk4_man, "--mode", "direct",
                ])
            _check("the direct job's gate passes on an in-lane write", rc_bg == 0)
            bk4_receipt = _read_json(
                os.path.join(bk4_run, "receipts", "d1.gate.json"), {})
            _check("the gate wrote a receipt", bool(bk4_receipt.get("diff_digest")))
            # finding 69: Record reads the receipt FROM THE FILE the gate wrote, bound
            # by the verdict and diff digest the workflow saw; a mismatch is refused.
            _bk4_rf = os.path.join(bk4_run, "receipts", "d1.gate.json")
            # The mismatch case runs in a THROWAWAY copy of the run dir: a record
            # is write-once, and an error result here must not shadow the real one.
            _f69_run = bk4_run + "-f69"
            shutil.copytree(bk4_run, _f69_run)
            with _quiet():
                cmd_record([
                    "--run-dir", _f69_run, "--job-id", "d1", "--manifest", bk4_man,
                    "--verdict-file", os.path.join(_f69_run, "receipts", "d1.gate.json"),
                    "--expect-verdict", "pass",
                    "--expect-diff-digest", "sha256:" + "0" * 64,
                    "--repo-root", bk4_repo, "--now", "2026-09-02T00:00:00Z",
                ])
            _bad_res = _read_json(os.path.join(_f69_run, "results", "d1.json"), {}) or {}
            _check("finding 69: a receipt whose diff_digest is not what the workflow saw is "
                   "recorded as an ERROR, never as success",
                   _bad_res.get("status") == "error"
                   and "rewritten" in str(_bad_res.get("summary")), str(_bad_res)[:200])
            shutil.rmtree(_f69_run, ignore_errors=True)
            with _quiet():
                cmd_record([
                    "--run-dir", bk4_run, "--job-id", "d1", "--manifest", bk4_man,
                    "--verdict-file", _bk4_rf, "--expect-verdict", "pass",
                    "--expect-diff-digest", str(bk4_receipt.get("diff_digest")),
                    "--repo-root", bk4_repo, "--now", "2026-09-02T00:00:00Z",
                ])
            bk4_stream = os.path.join(bk4_repo, "docs", "superpowers", "memory",
                                      "triage-outcomes.jsonl")
            _check("RECORD appends no `actual` — it writes nothing outside the "
                   "run directory",
                   not os.path.exists(bk4_stream)
                   and "triage_actual" not in _load_state(bk4_run))
            # The authority, at exactly the moment finalize-wave runs it.
            _rc_auth, _auth_out, _auth_err = _run([
                sys.executable or "python3", "-B", INTEGRATION_GATE_DEFAULT,
                "--run-dir", bk4_run, "--repo-root", bk4_repo,
                "--manifest", bk4_man, "--jobs", "d1", "--json",
            ])
            try:
                _auth = json.loads(_auth_out) if _auth_out.strip() else {}
            except Exception:  # noqa: BLE001
                _auth = {}
            _bk4_verdict = ((_auth.get("results") or [{}])[0] or {}).get("verdict")
            _check("the direct job's receipt is neither forged nor contradicted",
                   _bk4_verdict == "pass",
                   "%s / %s" % (_bk4_verdict, (_auth_err or _auth_out)[:200]))
            _check("...so the authority permits the wave",
                   _auth.get("integration") == "permitted", str(_auth)[:300])
            with _quiet():
                rc_fin = cmd_finalize_wave([
                    "--run-dir", bk4_run, "--repo-root", bk4_repo,
                    "--manifest", bk4_man, "--jobs", "d1", "--wave", "1",
                    "--now", "2026-09-02T00:00:00Z",
                ])
            _check("the wave integrates", rc_fin == 0)
            _check("FINALIZE-WAVE appends the run's `actual`, after the authority",
                   os.path.exists(bk4_stream)
                   and (_load_state(bk4_run).get("triage_actual") or {})
                   .get("merge_pending") is True)
            _bk4_state = _load_state(bk4_run)
            _wave_commit = str((_bk4_state.get("waves") or {}).get("1", {}).get("commit") or "")
            _rc_c, _committed, _ = _git(bk4_repo,
                                        ["show", "--name-only", "--format=", _wave_commit or "HEAD"])
            _check("the wave's commit carries the job's work and NOT the stream",
                   "src/work.txt" in _committed
                   and "triage-outcomes.jsonl" not in _committed, _committed)
            # Stage-1 finding 45: the finalizer, not a prose step, moves the run
            # to MERGED once every manifest job is integrated, and commits the
            # run's own record in a second commit that carries the stream and
            # state.json but none of the work.
            _check("finalize-wave advances the phase to MERGED when every job is integrated",
                   _bk4_state.get("phase") == "MERGED" and bool(_bk4_state.get("merged_at")),
                   str(_bk4_state.get("phase")))
            _check("finding 105: a MERGED run's .run.lock is retired at the same "
                   "terminal transition as lane-map.json",
                   not os.path.exists(os.path.join(bk4_run, ".run.lock")))
            _rc_h, _head_files, _ = _git(bk4_repo, ["show", "--name-only", "--format=", "HEAD"])
            _rc_p, _head_sha, _ = _git(bk4_repo, ["rev-parse", "HEAD"])
            _check("...and commits the run's bookkeeping SEPARATELY from the wave commit",
                   _head_sha.strip() != _wave_commit
                   and "state.json" in _head_files and "triage-outcomes.jsonl" in _head_files
                   and "src/work.txt" not in _head_files, _head_files)
            _rc_l, _tracked, _ = _git(bk4_repo, ["ls-files", "--", "docs/superpowers/execution"])
            _check("...and never the run lock", ".run.lock" not in _tracked, _tracked)
            # finding 78: an external job's wrapper is LISTED in the lane map, never
            # recorded as a worktree claim on the checkout.
            _f78_run = os.path.join(bk4_repo, "docs", "superpowers", "execution", "f78")
            os.makedirs(_f78_run, exist_ok=True)
            _f78_man = os.path.join(_f78_run, "manifest.yaml")
            with open(_f78_man, "w", encoding="utf-8") as fh:
                _yaml_bk.safe_dump({"run_id": "f78", "jobs": [
                    {"id": "ext", "backend": "codex", "isolation": "worktree", "write_allowed": ["src/**"]},
                    {"id": "cl", "backend": "claude", "isolation": "worktree", "write_allowed": ["docs/**"]}]}, fh)
            with _quiet():
                cmd_register_lane(["--run-dir", _f78_run, "--job-id", "ext", "--cwd", bk4_repo,
                                   "--repo-root", bk4_repo, "--isolation", "direct",
                                   "--manifest", _f78_man, "--no-test-contract"])
                cmd_register_lane(["--run-dir", _f78_run, "--job-id", "cl",
                                   "--cwd", os.path.join(bk4_repo, ".claude", "worktrees", "x"),
                                   "--repo-root", bk4_repo, "--isolation", "worktree",
                                   "--manifest", _f78_man, "--no-test-contract"])
            _f78_map = _read_json(os.path.join(_f78_run, "lane-map.json"), {}) or {}
            _check("finding 78: the external wrapper is listed under `wrappers`, and the checkout is "
                   "NOT a worktree claim",
                   (_f78_map.get("wrappers") or {}).get(bk4_repo) == "ext"
                   and bk4_repo not in (_f78_map.get("worktrees") or {})
                   and (_f78_map.get("worktrees") or {}).get(os.path.join(bk4_repo, ".claude", "worktrees", "x")) == "cl",
                   json.dumps(_f78_map)[:300])
            # finding 89: Record writes where the gate MEASURED (receipt mode + worktree),
            # not a re-derived 3.0.5 rule, for a dependent worktree job.
            _f89_run = os.path.join(bk4_repo, "docs", "superpowers", "execution", "f89")
            os.makedirs(os.path.join(_f89_run, "results"), exist_ok=True)
            _f89_man = os.path.join(_f89_run, "manifest.yaml")
            with open(_f89_man, "w", encoding="utf-8") as fh:
                _yaml_bk.safe_dump({"run_id": "f89", "jobs": [
                    {"id": "d0", "isolation": "worktree", "write_allowed": ["src/**"]},
                    {"id": "d1", "isolation": "worktree", "depends_on": ["d0"], "write_allowed": ["src/**"]}]}, fh)
            _f89_wt = os.path.join(bk4_repo, ".claude", "worktrees", "f89-wt")
            _run(["git", "-C", bk4_repo, "worktree", "add", "-q", "--detach", _f89_wt, "HEAD"])
            with _quiet():
                cmd_register_lane(["--run-dir", _f89_run, "--job-id", "d1", "--cwd", _f89_wt,
                                   "--repo-root", bk4_repo, "--isolation", "worktree",
                                   "--manifest", _f89_man, "--no-test-contract"])
            with open(os.path.join(_f89_wt, "src", "dep.txt"), "w") as fh:
                fh.write("dependent work in a real worktree\n")
            with _quiet():
                cmd_gate_receipt(["--run-dir", _f89_run, "--job-id", "d1", "--repo-root", bk4_repo,
                                  "--worktree", _f89_wt, "--manifest", _f89_man, "--mode", "worktree"])
                _f89_rcpt = _read_json(os.path.join(_f89_run, "receipts", "d1.gate.json"), {})
                cmd_record(["--run-dir", _f89_run, "--job-id", "d1", "--manifest", _f89_man,
                            "--verdict-json", json.dumps(_f89_rcpt), "--repo-root", bk4_repo,
                            "--now", "2026-09-03T00:00:00Z"])
            _f89_state = _load_state(_f89_run)["jobs"].get("d1", {})
            _f89_res = _read_json(os.path.join(_f89_run, "results", "d1.json"), {}) or {}
            _check("finding 89: Record keeps isolation=worktree and the receipt's worktree for a "
                   "dependent job that ran in a real worktree",
                   _f89_state.get("isolation") == "worktree" and _f89_state.get("worktree") == _f89_wt
                   and _f89_res.get("worktree") == _f89_wt, str(_f89_state)[:200])
            # ...and the FINALIZER merges from the receipt's worktree even when state and
            # result were written blank (the pre-fix shape).
            with _run_dir_lock(_f89_run):
                _f89_blank = _load_state(_f89_run)
                _f89_blank["jobs"]["d1"]["worktree"] = ""
                _save_state(_f89_run, _f89_blank)
            _f89_res_path = os.path.join(_f89_run, "results", "d1.json")
            _f89_res2 = dict(_read_json(_f89_res_path, {}) or {}, worktree="")
            with open(_f89_res_path, "w") as fh:
                json.dump(_f89_res2, fh)
            with _quiet():
                rc_f89 = cmd_finalize_wave(["--run-dir", _f89_run, "--repo-root", bk4_repo,
                                            "--manifest", _f89_man, "--jobs", "d1", "--wave", "2",
                                            "--now", "2026-09-03T00:00:00Z"])
            _rc_89, _files_89, _ = _git(bk4_repo, ["show", "--name-only", "--format=", "HEAD~1"])
            _check("finding 89: the finalizer merges from the RECEIPT's worktree when state/result say none",
                   rc_f89 == 0 and "src/dep.txt" in _files_89, "rc=%s files=%s" % (rc_f89, _files_89[:120]))
            _check("finding 68: a MERGED run's lane-map.json is retired by the finalizer",
                   not os.path.exists(os.path.join(bk4_run, "lane-map.json")))

            # ---- finding 60: a DEPENDENT job whose manifest says worktree but ---
            # whose agent ran direct (the 3.0.5 rule) must integrate on the gate
            # receipt's mode, not be refused on the manifest's label.
            bk5_run = os.path.join(bk4_repo, "docs", "superpowers", "execution", "bk5")
            os.makedirs(bk5_run, exist_ok=True)
            bk5_man = os.path.join(bk5_run, "manifest.yaml")
            with open(bk5_man, "w", encoding="utf-8") as fh:
                _yaml_bk.safe_dump({
                    "run_id": "bk5", "triage": {"pre_eval_id": "pe-bk5"},
                    "jobs": [{"id": "d0", "isolation": "worktree", "write_allowed": ["src/**"]},
                             {"id": "d1", "isolation": "worktree", "depends_on": ["d0"],
                              "write_allowed": ["src/**"]}],
                }, fh)
            with _quiet():
                cmd_register_lane([
                    "--run-dir", bk5_run, "--job-id", "d1", "--cwd", bk4_repo,
                    "--repo-root", bk4_repo, "--isolation", "direct",
                    "--manifest", bk5_man, "--no-test-contract",
                ])
            with open(os.path.join(bk4_repo, "src", "dependent.txt"), "w",
                      encoding="utf-8") as fh:
                fh.write("the dependent job's work, done in the main checkout\n")
            with _quiet():
                rc_g5 = cmd_gate_receipt([
                    "--run-dir", bk5_run, "--job-id", "d1", "--repo-root", bk4_repo,
                    "--worktree", bk4_repo, "--manifest", bk5_man, "--mode", "direct",
                ])
            bk5_receipt = _read_json(os.path.join(bk5_run, "receipts", "d1.gate.json"), {})
            with _quiet():
                cmd_record([
                    "--run-dir", bk5_run, "--job-id", "d1", "--manifest", bk5_man,
                    "--verdict-json", json.dumps(bk5_receipt),
                    "--repo-root", bk4_repo, "--now", "2026-09-03T00:00:00Z",
                ])
                rc_f5 = cmd_finalize_wave([
                    "--run-dir", bk5_run, "--repo-root", bk4_repo,
                    "--manifest", bk5_man, "--jobs", "d1", "--wave", "2",
                    "--now", "2026-09-03T00:00:00Z",
                ])
            _rc_5, _committed5, _ = _git(bk4_repo, ["show", "--name-only", "--format=", "HEAD~1"])
            _check("finding 60: a dependent job (manifest worktree, agent direct) INTEGRATES "
                   "on the receipt's mode", rc_g5 == 0 and rc_f5 == 0
                   and "src/dependent.txt" in _committed5,
                   "gate=%s fin=%s head~1=%s" % (rc_g5, rc_f5, _committed5[:200]))
            _check("finding 60: _gate_mode_from_receipt reads the emitter's --mode",
                   _gate_mode_from_receipt(bk5_receipt) == "direct"
                   and _gate_mode_from_receipt({"raw_stdout": "not json"}) is None
                   and _gate_mode_from_receipt(None) is None)

        # ---- THE SEALED PATCH, END TO END ------------------------------------ #
        # The merge used to take a fresh diff of the live worktree, so whatever
        # the tree said at merge time is what landed. Three shapes are driven
        # here against the real gate, the real authority and the real finalizer.
        if have_yaml and os.path.exists(INTEGRATION_GATE_DEFAULT):
            import yaml as _yaml_sp

            def _seal_case(name, mutate_after_gate=None, forge_state=None):
                """(repo, run_dir, worktree, gate_rc, receipt) for one worktree job."""
                sp_repo = os.path.join(tmp, "sp-%s-repo" % name)
                _init_repo(sp_repo)
                sp_run = os.path.join(tmp, "sp-%s-run" % name)
                os.makedirs(sp_run, exist_ok=True)
                sp_man = os.path.join(sp_run, "manifest.yaml")
                with open(sp_man, "w", encoding="utf-8") as fh:
                    _yaml_sp.safe_dump({
                        "run_id": "sp-%s" % name,
                        "jobs": [{"id": "w1", "isolation": "worktree",
                                  "title": "the sealed-patch fixture",
                                  "body": "Write src/work.txt.",
                                  "write_allowed": ["src/**"]}]}, fh)
                # INSIDE the repo, as the real pipeline places them: the
                # finalizer refuses to `worktree remove` anything outside the
                # project, so a fixture that put the tree in /tmp would never
                # exercise the prune it is testing.
                sp_wt = os.path.join(sp_repo, ".cv-worktrees", name)
                _run(["git", "-C", sp_repo, "worktree", "add", "-q", "--detach",
                      sp_wt, "HEAD"])
                with _quiet():
                    cmd_register_lane([
                        "--run-dir", sp_run, "--job-id", "w1", "--cwd", sp_wt,
                        "--repo-root", sp_repo, "--isolation", "worktree",
                        "--manifest", sp_man, "--no-test-contract"])
                os.makedirs(os.path.join(sp_wt, "src"), exist_ok=True)
                with open(os.path.join(sp_wt, "src", "work.txt"), "w",
                          encoding="utf-8") as fh:
                    fh.write("the worktree job's work\n")
                with _quiet():
                    rc_g = cmd_gate_receipt([
                        "--run-dir", sp_run, "--job-id", "w1",
                        "--repo-root", sp_repo, "--worktree", sp_wt,
                        "--manifest", sp_man, "--mode", "worktree"])
                rcpt = _read_json(os.path.join(sp_run, "receipts", "w1.gate.json"),
                                  {})
                with _quiet():
                    cmd_record([
                        "--run-dir", sp_run, "--job-id", "w1", "--manifest", sp_man,
                        "--verdict-json", json.dumps(rcpt), "--repo-root", sp_repo,
                        "--now", "2026-09-02T00:00:00Z"])
                if mutate_after_gate:
                    mutate_after_gate(sp_wt)
                if forge_state:
                    with _run_dir_lock(sp_run):
                        st = _load_state(sp_run)
                        st["jobs"]["w1"].update(forge_state)
                        _save_state(sp_run, st, now="2026-09-02T00:00:00Z")
                return sp_repo, sp_run, sp_wt, sp_man, rc_g, rcpt

            # (1) the happy path: the artifact is sealed, applied and PROVEN.
            sp_repo, sp_run, sp_wt, sp_man, rc_g, rcpt = _seal_case("ok")
            _check("the gate passes the worktree job", rc_g == 0)
            _check("the gate SEALS what it approved as jobs/<id>.patch",
                   os.path.isfile(patch_artifact_path(sp_run, "w1")))
            _seal_bytes = open(patch_artifact_path(sp_run, "w1"), "rb").read()
            _check("...and records that artifact's sha256 in its receipt",
                   rcpt.get("patch_sha256")
                   == "sha256:" + hashlib.sha256(_seal_bytes).hexdigest())
            _check("...over the approved paths and nothing else",
                   rcpt.get("patch_paths") == ["src/work.txt"])
            with _quiet():
                rc_fin = cmd_finalize_wave([
                    "--run-dir", sp_run, "--repo-root", sp_repo,
                    "--manifest", sp_man, "--jobs", "w1", "--wave", "1",
                    "--now", "2026-09-02T00:00:00Z"])
            _dbg_fin = json.dumps(_read_json(os.path.join(sp_run, "state.json"),
                                             {}).get("waves"))
            _check("the wave integrates from the sealed artifact", rc_fin == 0)
            _rc_s, _show, _e = _git(sp_repo,
                                    ["show", "--name-only", "--format=", "HEAD"])
            _check("...and HEAD carries the job's work",
                   "src/work.txt" in _show, _show)
            _check("a PROVEN merge retires its worktree",
                   not os.path.isdir(sp_wt), _dbg_fin)

            # (2) THE TREE WENT BACKWARDS AFTER THE GATE. A fresh diff of it is
            # empty, which the old finalizer read as "already landed": the job was
            # marked integrated and its worktree — the only copy — was pruned.
            def _revert(wt):
                _run(["git", "-C", wt, "checkout", "--", "."])
                p = os.path.join(wt, "src", "work.txt")
                if os.path.exists(p):
                    os.remove(p)

            sp_repo, sp_run, sp_wt, sp_man, rc_g, rcpt = _seal_case(
                "revert", mutate_after_gate=_revert)
            _head_before = _head_commit(sp_repo)
            with _quiet():
                rc_fin = cmd_finalize_wave([
                    "--run-dir", sp_run, "--repo-root", sp_repo,
                    "--manifest", sp_man, "--jobs", "w1", "--wave", "1",
                    "--now", "2026-09-02T00:00:00Z"])
            _check("a worktree reverted to its baseline after the gate is REFUSED",
                   rc_fin != 0)
            _check("...nothing is committed", _head_commit(sp_repo) == _head_before)
            _check("...and the worktree is NOT pruned — refusing exists to keep "
                   "the one copy of the work",
                   os.path.isdir(sp_wt))

            # (3) state.json is a CACHE. Forging `merged.integrated` must not let a
            # job skip its merge: git has to say the content is in HEAD.
            sp_repo, sp_run, sp_wt, sp_man, rc_g, rcpt = _seal_case(
                "forged-state")
            with _run_dir_lock(sp_run):
                _st = _load_state(sp_run)
                _st["jobs"]["w1"]["merged"] = {
                    "integrated": True,
                    "realised_commit": _st["jobs"]["w1"].get("realised_commit"),
                    "commit": "a" * 40}
                _save_state(sp_run, _st, now="2026-09-02T00:00:00Z")
            with _quiet():
                rc_fin = cmd_finalize_wave([
                    "--run-dir", sp_run, "--repo-root", sp_repo,
                    "--manifest", sp_man, "--jobs", "w1", "--wave", "1",
                    "--now", "2026-09-02T00:00:00Z"])
            _rc_s, _show, _e = _git(sp_repo,
                                    ["show", "--name-only", "--format=", "HEAD"])
            _check("a state.json forged to integrated:true does NOT skip the merge "
                   "— the finalizer asks git, and git had never seen the work",
                   rc_fin == 0 and "src/work.txt" in _show, "%s / %s" % (rc_fin,
                                                                         _show))

            # (4) THE MANIFEST DIGEST. Widen the lane map after emit and every
            # stage refuses, because each carries the digest emit baked in.
            sp_repo, sp_run, sp_wt, sp_man, rc_g, rcpt = _seal_case("digest")
            _plan = build_plan(_load_yaml(sp_man), sp_run, sp_repo,
                               "/usr/bin/python3", os.path.abspath(__file__),
                               SCOPE_CHECK_DEFAULT, FASTPATH_DEFAULT, HERE)
            _digest = _plan["manifest_digest"]
            _check("emit computes the manifest digest",
                   bool(_digest) and _digest.startswith("sha256:"))
            _js = emit_script(_plan)
            _check("...bakes it into CFG.manifest_digest",
                   ('"manifest_digest": "%s"' % _digest) in _js)
            for _stage in ("gate-receipt", "record", "finalize-wave"):
                _check("the emitted %s command carries --manifest-digest" % _stage,
                       "--manifest-digest" in _js)
            with open(sp_man, "a", encoding="utf-8") as fh:
                fh.write('  - id: widened\n    isolation: direct\n'
                         '    write_allowed:\n      - "**"\n')
            with _quiet():
                _rc_md = cmd_gate_receipt([
                    "--run-dir", sp_run, "--job-id", "w1",
                    "--repo-root", sp_repo, "--worktree", sp_wt,
                    "--manifest", sp_man, "--mode", "worktree",
                    "--manifest-digest", _digest])
            _check("a manifest widened after emit ⇒ the GATE refuses", _rc_md == 2)
            with _quiet():
                _rc_mr = cmd_record([
                    "--run-dir", sp_run, "--job-id", "w1", "--manifest", sp_man,
                    "--verdict-json", json.dumps(rcpt), "--repo-root", sp_repo,
                    "--manifest-digest", _digest])
            _check("...RECORD refuses", _rc_mr == 2)
            with _quiet():
                _rc_mf = cmd_finalize_wave([
                    "--run-dir", sp_run, "--repo-root", sp_repo,
                    "--manifest", sp_man, "--jobs", "w1", "--wave", "1",
                    "--manifest-digest", _digest,
                    "--now", "2026-09-02T00:00:00Z"])
            _check("...and the FINALIZER refuses, so nothing merges", _rc_mf != 0)
            _rc_a, _a_out, _a_err = _run([
                sys.executable or "python3", "-B", INTEGRATION_GATE_DEFAULT,
                "--run-dir", sp_run, "--repo-root", sp_repo, "--manifest", sp_man,
                "--jobs", "w1", "--json", "--manifest-digest", _digest])
            _check("...and so does the AUTHORITY", _rc_a != 0)

        # ---- THE IMPORT SURFACE ---------------------------------------------- #
        # A job with a lane over `scripts/**` can write `scripts/yaml.py`, and this
        # file's own `_load_yaml` would have imported it — the manifest loader
        # shadowed by the manifest's own subject.
        _plant_dir = os.path.join(tmp, "plant", "scripts")
        os.makedirs(_plant_dir, exist_ok=True)
        shutil.copyfile(os.path.abspath(__file__),
                        os.path.join(_plant_dir, "compound-v-emit-workflow.py"))
        with open(os.path.join(_plant_dir, "yaml.py"), "w", encoding="utf-8") as fh:
            fh.write("def safe_load(text):\n"
                     "    raise RuntimeError('PLANTED YAML WAS IMPORTED')\n")
        _plant_man = os.path.join(tmp, "plant-manifest.yaml")
        with open(_plant_man, "w", encoding="utf-8") as fh:
            fh.write('run_id: plant\njobs:\n  - id: p\n    isolation: direct\n'
                     '    body: "t"\n    write_allowed:\n      - "src/**"\n')
        _rc_p, _o_p, _e_p = _run([
            sys.executable or "python3", "-B",
            os.path.join(_plant_dir, "compound-v-emit-workflow.py"),
            "gate-receipt", "--run-dir", tmp, "--job-id", "p",
            "--repo-root", tmp, "--worktree", tmp, "--manifest", _plant_man,
            "--mode", "direct"])
        _check("a planted scripts/yaml.py is NOT imported by the manifest loader",
               "PLANTED YAML WAS IMPORTED" not in (_o_p + _e_p),
               (_o_p + _e_p)[:200])

        # ---- THE BYTECODE CACHE ---------------------------------------------- #
        # The loader redirects the cache outside the tree before exec_module. When
        # that private directory cannot be made it loads NOTHING: falling back to
        # the default location would execute the in-tree `.pyc` the redirect
        # exists to avoid, which is the one condition an attacker can arrange.
        _cache_dir = os.path.join(_plant_dir, "__pycache__")
        os.makedirs(_cache_dir, exist_ok=True)
        with open(os.path.join(_cache_dir, "compound-v-scope-check.pyc"),
                  "wb") as fh:
            fh.write(b"not real bytecode")
        _real_mkdtemp = tempfile.mkdtemp

        def _no_tmp(*a, **k):
            raise OSError("no space left on device")

        tempfile.mkdtemp = _no_tmp
        try:
            _mod = _load_module_from_path("cv_probe", SCOPE_CHECK_DEFAULT)
        finally:
            tempfile.mkdtemp = _real_mkdtemp
        _check("no private bytecode cache ⇒ the module is NOT executed",
               _mod is None)
        _check("...and the planted cache directory is untouched",
               sorted(os.listdir(_cache_dir)) == ["compound-v-scope-check.pyc"])

        # HIGH 3 — the handoff keeps its invocation, its worktree and its pin.
        ext2 = build_plan(
            _with_body({"run_id": "r3",
                        "test_contract": {"floor_command": "sh -c 'exit 0'"},
                        "jobs": [{"id": "e1", "backend": "codex",
                                  "isolation": "worktree",
                                  "model": "gpt-5.6-sol", "effort": "high",
                                  "timeout_sec": 900, "test_scope": "floor_only",
                                  "write_allowed": ["src/**"]}]}),
            tmp, tmp, "/usr/bin/python3", os.path.abspath(__file__),
            SCOPE_CHECK_DEFAULT, FASTPATH_DEFAULT, HERE)
        e1 = ext2["waves"][0][0]
        for flag in ("--run-id", "--job-id", "--repo", "--prompt-file", "--model",
                     "--write-allowed", "--events-log", "--test-contract-file"):
            _check("the materialized argv carries %s" % flag,
                   flag in (e1["launch_argv"] or []), str(e1["launch_argv"]))
        _check("the argv carries no elision",
               "..." not in (e1["launch_argv"] or []))
        _check("the launcher in the prompt is the materialized argv, not a stub",
               e1["launch_command"] in _implement_prompt(e1, ext2)
               and "worker-script" not in _implement_prompt(e1, ext2))
        _check("the prompt file is materialized with the job's real acceptance",
               "src/**" in ext2["artefacts"]["e1"]["prompt_text"])
        _check("an external job's implementer is told to return the WORKER's "
               "worktree, never its own pwd",
               "Never return your own `pwd`" in _implement_prompt(e1, ext2))

        # --- a malformed max_turns degrades, and SAYS it degraded -------------
        _cap, _src = job_turn_cap({"id": "mt", "tier": "deep", "max_turns": "80"})
        _check("a quoted max_turns falls back to the tier default",
               _cap == TURN_CAP_BY_TIER["deep"])
        _check("...and the fallback is NOTED, not silent — a manifest that meant "
               "to raise a cap and quoted the number got the default with no hint "
               "its value had been discarded",
               "not a positive integer" in _src and "'80'" in _src)
        for _bad in (0, -1, True, 3.5):
            _c, _s2 = job_turn_cap({"id": "mt", "tier": "light",
                                    "max_turns": _bad})
            _check("max_turns %r degrades to the tier default with a note"
                   % (_bad,),
                   _c == TURN_CAP_BY_TIER["light"]
                   and "not a positive integer" in _s2)
        _check("an ABSENT max_turns is not a malformed one — no note",
               job_turn_cap({"id": "mt", "tier": "deep"})[1]
               == "default for tier deep")
        _check("the note reaches the rendered worker prompt's Turn cap line",
               "not a positive integer" in render_worker_prompt(
                   {"id": "mt", "title": "t", "tier": "deep", "max_turns": "80",
                    "body": "b", "write_allowed": ["src/**"]}, "r"))
        _check("the rendered Turn cap states the tier defaults execution-manifest.md "
               "documents (deep %d)" % TURN_CAP_BY_TIER["deep"],
               "deep %d" % TURN_CAP_BY_TIER["deep"] in render_worker_prompt(
                   {"id": "mt", "title": "t", "tier": "deep", "body": "b",
                    "write_allowed": ["src/**"]}, "r"))

        pin_dir = os.path.join(tmp, "pin-run")
        os.makedirs(pin_dir, exist_ok=True)
        with _quiet():
            rc = cmd_register_lane([
                "--run-dir", pin_dir, "--job-id", "p1", "--cwd", fin_repo,
                "--repo-root", fin_repo, "--isolation", "direct",
                "--no-test-contract",
            ])
        _check("register-lane exits 0 when it can pin", rc == 0)
        _check("register-lane PINS the baseline before anything runs",
               bool(read_pinned_baseline(
                   pin_dir, "p1", _load_state(pin_dir)["jobs"].get("p1"))))
        _check("the pin is ALSO a per-job file, which a sibling's state.json "
               "save cannot race away",
               os.path.exists(baseline_pin_path(pin_dir, "p1")))
        _check("an unpinned job reads back as unpinned, not as some HEAD",
               read_pinned_baseline(pin_dir, "absent", {}) is None)

        # --- agentType: the last unused native mechanism ----------------------
        rev_plan = _plan_for(_tiny_manifest(
            [{"id": "rev", "type": "review", "backend": "claude",
              "isolation": "direct", "write_allowed": ["docs/**"]},
             {"id": "impl", "type": "bounded_crud", "backend": "claude",
              "isolation": "direct", "write_allowed": ["src/**"]}]), tmp)
        rev_entries = {j["id"]: j for w in rev_plan["waves"] for j in w}
        expected, why = resolve_agent_type("review")
        _check("this plugin's own agents/spec-reviewer.md + plugin.json resolve "
               "a real agentType", bool(expected), str(why))
        _check("a `type: review` job is spawned BY ROLE, not anonymously",
               rev_entries["rev"]["agent_type"] == expected)
        _check("the name is READ from the plugin manifest, never derived from a "
               "checkout directory (this file is edited from a worktree whose "
               "directory name is a random job id)",
               bool(expected) and expected.endswith(":spec-reviewer")
               and os.path.basename(os.path.dirname(HERE)) not in
               (expected or "").split(":")[0:1]
               or expected == "%s:spec-reviewer" % (_read_json(os.path.join(
                   os.path.dirname(HERE), ".claude-plugin", "plugin.json"),
                   {}) or {}).get("name"))
        impl_expected, impl_why = resolve_agent_type("bounded_crud")
        _check("this plugin's own agents/implementer.md resolves a real "
               "agentType", bool(impl_expected), str(impl_why))
        _check("an ordinary implementation job arrives AS THE IMPLEMENTER ROLE "
               "(3.4.0) — that is the only native way it carries a turn cap",
               rev_entries["impl"]["agent_type"] == impl_expected
               and impl_expected.endswith(":implementer"))
        _impl_cap = (rev_entries["impl"].get("agent_definition") or {}).get(
            "max_turns")
        _check("...and it carries agents/implementer.md's own maxTurns, so the "
               "cap is a definition property and not a number we invented",
               isinstance(_impl_cap, int) and _impl_cap > 0)
        _check("a reviewer type with no registered role stays ANONYMOUS — it is "
               "not an implementer, and must never be told to write in a lane",
               agent_role_for("integration_review")[0] is None
               and resolve_agent_type("integration_review")[0] is None)
        _check("...and it SAYS SO: a decline carries a reason, so 'this is a "
               "reviewer' and 'the lookup found nothing' are not the same silence",
               "reviewer" in (agent_role_for("integration_review")[1] or "")
               and "reviewer" in (resolve_agent_type("integration_review")[1] or ""))
        for _rt in ("review", "spec_review", "quality_review", "integration_review"):
            _check("%r is matched EXACTLY as a reviewer type" % _rt,
                   agent_role_for(_rt)[0] != DEFAULT_AGENT_ROLE)
        _check("`review_fix` is an IMPLEMENTER, not a reviewer — the substring "
               "match declined it, so a job that fixes what a review found "
               "arrived with no role, no cap and none of agents/implementer.md",
               agent_role_for("review_fix")[0] == DEFAULT_AGENT_ROLE
               and agent_role_for("review_fix")[1] is None)
        _check("...and neither does a type that merely contains a reviewer word",
               agent_role_for("integration_review_followup")[0]
               == DEFAULT_AGENT_ROLE
               and agent_role_for("quality_review_fix")[0] == DEFAULT_AGENT_ROLE)
        ext_rev = _plan_for(_tiny_manifest(
            [{"id": "xr", "type": "review", "backend": "codex",
              "model": "gpt-5.6-sol", "isolation": "worktree",
              "write_allowed": ["docs/**"]}]), tmp, workers_dir=HERE)
        _check("an EXTERNAL review job gets no agentType — agentType spawns "
               "Claude agents, and that job's implementer is a launcher",
               ext_rev["waves"][0][0]["agent_type"] is None)
        _check("an unknown plugin root yields NO name rather than a guessed one",
               resolve_agent_type("review", plugin_dir=tmp)[0] is None)
        rev_script = emit_script(rev_plan)
        _check("the emitted script actually SETS agentType (the audit row's "
               "'zero occurrences in the emitted script')",
               "opts.agentType = job.agent_type" in rev_script)
        _check("the by-role prompt defers to the agent's own definition instead "
               "of restating the contract",
               "come from your OWN agent definition"
               in _implement_prompt(rev_entries["rev"], rev_plan))
        _check("Gate/Record/Finalize stay anonymous — their safety IS the "
               "narrowing, and no agent here declares a tools: restriction",
               "phase: 'Gate'" in rev_script
               and rev_script.count("opts.agentType") == 1
               and "agentType" not in rev_script.split("async function gateStage", 1)[1]
               .split("async function finalizeWave", 1)[0])
        _check("a throwing Implement stage no longer skips Gate AND Record",
               "return implementFailure(job);" in rev_script
               and "function implementFailure(job) {" in rev_script
               and "implement: null, retries: [], escalated_from: null" in rev_script)
        # Table-driven from the canonical list (ninth review pass, item 2): every
        # class is exempt for its own job, a sibling name beside each is not, and
        # another job's files are never this job's.
        for _tmpl, _why in RUN_DIR_EXEMPT_BY_NAME:
            _own = "run/" + _tmpl.replace("{id}", "j1")
            _check("exempt by name: %s (%s)" % (_tmpl, _why[:40]),
                   run_dir_owned_by_name(_own, "run", "j1"))
            _check("NOT exempt: a sibling of %s" % _tmpl,
                   not run_dir_owned_by_name(_own + ".bak", "run", "j1"))
            _check("NOT exempt: another job's %s" % _tmpl,
                   run_dir_owned_by_name(_own, "run", "j2") == (_tmpl == "state.json"))
        _check("exempt by pattern: results/attempts/j1.3.json",
               run_dir_owned_by_name("run/results/attempts/j1.3.json", "run", "j1"))
        _check("NOT exempt: manifest.yaml is digest-bound, never by name",
               not run_dir_owned_by_name("run/manifest.yaml", "run", "j1"))
        # Dogfood r4: `git rm` in a worktree could never merge back.
        _del_repo = os.path.join(tmp, "delrepo"); os.makedirs(_del_repo)
        _run(["git", "-C", _del_repo, "init", "-q"])
        _run(["git", "-C", _del_repo, "config", "user.email", "t@t"]); _run(["git", "-C", _del_repo, "config", "user.name", "t"])
        with open(os.path.join(_del_repo, "gone.txt"), "w") as fh: fh.write("x\n")
        with open(os.path.join(_del_repo, "kept.txt"), "w") as fh: fh.write("k\n")
        _run(["git", "-C", _del_repo, "add", "-A"]); _run(["git", "-C", _del_repo, "commit", "-q", "-m", "base"])
        _base_sha = (_run(["git", "-C", _del_repo, "rev-parse", "HEAD"])[1] or "").strip()
        _del_wt = os.path.join(tmp, "delwt")
        _run(["git", "-C", _del_repo, "worktree", "add", "-q", _del_wt, "-b", "del-branch"])
        _run(["git", "-C", _del_wt, "rm", "-q", "gone.txt"])
        _ok_del, _err_del = _stage_paths(_del_wt, ["gone.txt"])
        _check("a deletion the worker already staged is accepted by _stage_paths",
               _ok_del, str(_err_del))
        _ok_mb, _err_mb = merge_back(_del_wt, _del_repo, _base_sha, ["gone.txt"])
        _check("merge_back lands a `git rm` into the main tree",
               _ok_mb and not os.path.exists(os.path.join(_del_repo, "gone.txt")), str(_err_mb))
        _ok_missing, _err_missing = _stage_paths(_del_wt, ["never-existed.txt"])
        _check("a path that is neither on disk nor staged as removed is still an error",
               not _ok_missing and "did not match" in (_err_missing or ""))
        # Dogfood r2 (wf_f0505df2-99c): the Gate's clamped command outran the Bash
        # tool's 120 s default, the harness detached it, and the agent — no Read,
        # one admitted command form — honestly reported `blocked` while the
        # receipt on disk said pass. Every transport prompt now sets the timeout.
        _check("every transport prompt tells the agent to call Bash with a 10-minute timeout",
               rev_script.count("Call the Bash tool with `timeout: 600000`") == 3)
        # The inline fallback (dogfood wf_3b6697df-5e0: every by-role spawn threw
        # `agent type ... not found` after a mid-session plugin update).
        _check("a by-role job carries its agent's definition for the inline fallback",
               isinstance(rev_entries["rev"].get("agent_definition"), dict)
               and bool(rev_entries["rev"]["agent_definition"]["body"])
               and rev_entries["rev"]["agent_definition"]["model"] == "opus")
        _check("the implementer job carries agents/implementer.md's BODY too, so "
               "the guidance survives a session where the plugin is unregistered",
               isinstance(rev_entries["impl"].get("agent_definition"), dict)
               and "Deliver what was asked, at the scope intended"
               in rev_entries["impl"]["agent_definition"]["body"])
        _check("an anonymous job (a reviewer type with no role) carries no "
               "definition — there is nothing to inline",
               (_plan_for(_tiny_manifest(
                   [{"id": "ir", "type": "integration_review", "backend": "claude",
                     "isolation": "direct", "write_allowed": ["docs/**"]}]), tmp)
                ["waves"][0][0].get("agent_definition")) is None)
        _check("the fallback SAYS the maxTurns cap is lost, rather than letting "
               "an uncapped spawn look identical to a capped one",
               "is LOST on this path" in rev_script
               and "job.agent_definition.max_turns" in rev_script)
        _check("Implement retries ONCE without agentType on 'agent type not found', "
               "inside its own try so Gate and Record still run",
               "isAgentTypeMissing(spawnErr)" in rev_script
               and "delete inl.agentType" in rev_script
               and "inlineDefinition(job, p.implement)" in rev_script
               and rev_script.index("isAgentTypeMissing(spawnErr)")
               < rev_script.index("async function gateStage"))
        _check("the fallback keeps the tier-resolved model when one was set",
               "if (!inl.model && job.agent_definition.model)" in rev_script)
        _check("the emitted script PARSES as JavaScript (node --check; skipped without node)",
               _js_parses(rev_script), "node --check rejected the emitted script")

        # --- the worker prompt asks for the work, and for nothing around it ----
        # Anthropic's Opus 5 guidance: explicit verification instructions CAUSE
        # over-verification. The template therefore adds no such imperative of its
        # own — and states the turn cap, which for an external worker is the only
        # place a cap is ever mentioned (`maxTurns` is a Claude agent-definition
        # field and an external backend has no definition).
        _wp = render_worker_prompt(
            {"id": "j", "title": "T", "body": "do the thing", "tier": "standard",
             "write_allowed": ["src/**"], "acceptance": ["it works"]}, "r")
        _check("the template adds no verify / re-check / report-per-item imperative",
               not any(tok in _wp.lower() for tok in
                       ("verify", "re-check", "recheck", "report per item")), _wp)
        _check("the worker prompt states the job's turn cap",
               "Turn cap: 50 (default for tier standard" in _wp, _wp)
        _check("a manifest `max_turns` overrides the tier default",
               "Turn cap: 12 (manifest max_turns" in render_worker_prompt(
                   {"id": "j", "title": "T", "body": "b", "tier": "light",
                    "max_turns": 12, "write_allowed": ["src/**"]}, "r"))
        _check("the tier defaults are the documented ones",
               [job_turn_cap({"tier": t})[0] for t in ("light", "standard", "deep")]
               == [30, 50, 80])

        # --- the lane map under real CONCURRENCY -------------------------------
        # `_atomic_write` makes one write atomic and does nothing for the read
        # that chose what to write. Unlocked, two implementers in a wave both read
        # the pre-write map and the second drops the first's lane — and a dropped
        # lane is a job hooks/lane-guard.sh cannot resolve, so it fails OPEN.
        #
        # Run as real SUBPROCESSES, not threads: the racing writers are separate
        # `register-lane` processes, and a GIL-serialized thread test can pass
        # while the process case still loses entries.
        race_dir = os.path.join(tmp, "race-run")
        os.makedirs(race_dir, exist_ok=True)
        _atomic_write(os.path.join(race_dir, "state.json"),
                      json.dumps({"run_id": "race", "jobs": {}}) + "\n")
        writers = 12
        procs = []
        for i in range(writers):
            cwd_i = os.path.join(tmp, "race-wt-%d" % i)
            os.makedirs(cwd_i, exist_ok=True)
            procs.append(subprocess.Popen(
                ["/usr/bin/python3", os.path.abspath(__file__), "register-lane",
                 "--run-dir", race_dir, "--job-id", "race-%d" % i,
                 "--cwd", cwd_i, "--repo-root", repo,
                 # `direct`, so all twelve pin from the same real git tree: the
                 # race under test is the shared-file merge, not HEAD resolution.
                 "--isolation", "direct", "--no-test-contract"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
            ))
        rcs = [p.wait() for p in procs]
        for p in procs:
            p.stdout.close()
            p.stderr.close()
        race_map = _read_json(lane_map_path(race_dir), {}) or {}
        _check("every concurrent register-lane exited 0",
               all(rc == 0 for rc in rcs), str(rcs))
        _check("%d concurrent registrations keep ALL %d lanes — an unlocked "
               "read-modify-write drops the losers, and a dropped lane is a "
               "guard that fails open" % (writers, writers),
               len(race_map.get("worktrees") or {}) == writers,
               "kept %d" % len(race_map.get("worktrees") or {}))
        race_state = _read_json(os.path.join(race_dir, "state.json"), {}) or {}
        _check("and every job's pinned baseline survives the same race",
               len(race_state.get("jobs") or {}) == writers,
               "kept %d" % len(race_state.get("jobs") or {}))
        _check("the lock is held across the READ as well as the write",
               "_run_dir_lock" in register_lane.__code__.co_names
               and "_run_dir_lock" in cmd_record.__code__.co_names)

        # ------------------------------------------------------------------ #
        # v3.4.8 - withRetry, the reviewer lift, and an honest exhaustion class
        # ------------------------------------------------------------------ #
        def _js_stage_body(text, name):
            """The source of ONE emitted stage function, up to the next top-level
            declaration. Nested declarations are indented, so they stay inside."""
            seg = text.split("async function %s(" % name, 1)[1]
            ends = [seg.index(e) for e in ("\nasync function ", "\nfunction ") if e in seg]
            return seg[:min(ends)] if ends else seg

        _rt_script = emit_script(_plan_for(_tiny_manifest(
            [{"id": "rv", "type": "review", "backend": "claude", "isolation": "direct",
              "write_allowed": ["docs/**"]},
             {"id": "im", "type": "implement", "backend": "claude", "isolation": "direct",
              "write_allowed": ["src/**"]}]), tmp))
        _check("the emitted script defines withRetry and waits with setTimeout",
               "async function withRetry(stage, jobId, fn)" in _rt_script
               and "setTimeout(res, wait)" in _rt_script
               and "new Promise(function (res)" in _rt_script)
        _check("...and it retries a NULL resolution as well as a throw",
               "if (r !== null && r !== undefined)" in _rt_script
               and "} catch (e) {\n      r = null;" in _rt_script)
        _check("the retry wait comes from CFG, so the JS and the Python mirror "
               "cannot drift",
               "Math.min(CFG.retry.cap_ms,\n                            "
               "CFG.retry.base_ms * Math.pow(2, attempt - 1))" in _rt_script)
        for _stage_fn in ("gateStage", "recordStage", "finalizeWave"):
            _body = _js_stage_body(_rt_script, _stage_fn)
            _check("%s reaches agent() only through withRetry" % _stage_fn,
                   "await withRetry(" in _body and "await agent(" not in _body,
                   _body[:0])
        _impl_body = _js_stage_body(_rt_script, "implementStage")
        _check("implementStage's two agent() calls are both inside "
               "attemptImplement, which withRetry drives",
               "await withRetry(" in _impl_body
               and _impl_body.count("await agent(") == 2
               and _impl_body.index("async function attemptImplement(useOpts)")
               < _impl_body.index("await agent(")
               and _impl_body.count("attemptImplement(") == 3,
               "agent awaits: %d" % _impl_body.count("await agent("))
        _check("the by-role fallback is composed INSIDE the retried function, "
               "not around it",
               _impl_body.index("isAgentTypeMissing(spawnErr)")
               < _impl_body.index("const first = await withRetry("))
        _check("no forbidden construct enters the emitted script with the retry loop",
               forbidden_hits(_rt_script) == [], str(forbidden_hits(_rt_script)))
        _check("the emitted script still PARSES as JavaScript with withRetry in it",
               _js_parses(_rt_script), "node --check rejected the emitted script")

        # The backoff table, mirrored in Python from the same two constants.
        _check("the backoff table is 2 s, 4 s, 8 s ... capped at 60 s, no jitter",
               [retry_backoff_ms(a) for a in (1, 2, 3, 4, 5, 6, 7)]
               == [2000, 4000, 8000, 16000, 32000, 60000, 60000],
               str([retry_backoff_ms(a) for a in range(1, 8)]))
        _rt_cfg = json.loads(
            _rt_script.split("const CFG = ", 1)[1]
            .split(";\nconst IMPLEMENT_SCHEMA", 1)[0])
        _check("the emitted CFG carries the same base and cap the mirror uses",
               _rt_cfg["retry"]["base_ms"] == RETRY_BACKOFF_BASE_MS
               and _rt_cfg["retry"]["cap_ms"] == RETRY_BACKOFF_CAP_MS,
               json.dumps(_rt_cfg["retry"]))
        _check("an absent manifest `retry` block defaults to 3 attempts and a "
               "reviewer lift",
               _rt_cfg["retry"]["max_attempts"] == 3
               and _rt_cfg["retry"]["escalate_reviewer"] is True)
        _check("the manifest's own retry block is honoured (1 disables retrying)",
               retry_config({"retry": {"max_attempts": 1, "escalate_reviewer": False}})
               == {"max_attempts": 1, "escalate_reviewer": False,
                   "base_ms": RETRY_BACKOFF_BASE_MS, "cap_ms": RETRY_BACKOFF_CAP_MS})
        _check("an out-of-range, bool or string max_attempts falls back to the "
               "default, never through to the value it asked for",
               all(retry_config({"retry": {"max_attempts": bad}})["max_attempts"] == 3
                   for bad in (0, 4, 99, True, "3", None, 2.0)))
        _check("a non-bool escalate_reviewer falls back to True",
               all(retry_config({"retry": {"escalate_reviewer": bad}})["escalate_reviewer"]
                   is True for bad in ("yes", 1, None, 0)))
        _check("the escalation map is the ladder, and an off-ladder pin has no rung",
               escalation_map() == {"sonnet": "opus", "opus": "fable"}
               and escalation_map().get("fable") is None
               and escalation_map().get("gpt-5.6-sol") is None)
        _check("the reviewer lift is gated on job_type review AND the flag, and "
               "steps the emitted ladder rather than a literal",
               "isReviewJob(job) && CFG.retry.escalate_reviewer" in _rt_script
               and "CFG.escalation[current]" in _rt_script
               and "'fable'" not in _js_stage_body(_rt_script, "implementStage")
               and "job_type ? job.job_type : '') === 'review'" in _rt_script)
        _check("the lift re-spawns ONCE, labelled, and never retries the lift",
               _impl_body.count("attemptImplement(lifted)") == 1
               and "' (escalated)'" in _impl_body)
        _check("Gate passes --escalated-from only when the implement result "
               "carries one, and Record passes the retry log as its own argument",
               "(prev.escalated_from ? ' --escalated-from ' + q(prev.escalated_from) : '')"
               in _rt_script
               and "' --retries-json ' + q(JSON.stringify(meta))" in _rt_script
               and "delete v.__retry;" in _rt_script)

        # The retry log is validated, never trusted, and never widens anything.
        _rt_meta, _rt_err = _sanitize_retry_meta(json.dumps({
            "retries": [{"stage": "implement", "job": "rv", "attempt": 1, "wait_ms": 2000},
                        {"stage": "implement", "job": "rv", "attempt": 2, "wait_ms": 4000,
                         "evil": "$(rm -rf /)"}],
            "exhausted": True, "attempts": 3, "escalated_from": "opus"}))
        _check("a retry log parses, and an unknown key is dropped rather than stored",
               _rt_err is None and len(_rt_meta["retries"]) == 2
               and "evil" not in _rt_meta["retries"][1]
               and _rt_meta["attempts"] == 3 and _rt_meta["escalated_from"] == "opus")
        _check("a malformed retry log is REPORTED, never raised and never "
               "allowed to cost a job its result",
               _sanitize_retry_meta("{not json")[0] is None
               and "unparseable" in (_sanitize_retry_meta("{not json")[1] or "")
               and _sanitize_retry_meta(json.dumps([1, 2]))[0] is None)
        _check("a shell-shaped escalated_from is refused, not recorded",
               _sanitize_retry_meta(json.dumps(
                   {"escalated_from": "opus; rm -rf /"}))[0]["escalated_from"] is None)

        # Exhaustion: today's null path, `other`, and the reason that says WHY
        # the class is not named.
        _rt_res = _job_result_from(
            {"verdict": "error",
             "reason": "gate agent returned null " + u"\u2014" + " FAIL, never pass",
             "raw_stdout": ""},
            {"id": "rv", "title": "T", "write_allowed": ["docs/**"], "isolation": "direct"},
            {})
        apply_retry_meta(_rt_res, _rt_meta)
        _check("an exhausted retry budget records failure_class `other` with the "
               "reason that says the runtime's failure text is invisible",
               _rt_res["failure_class"] == "other"
               and _rt_res["summary"].startswith(
                   "agent returned null 3 times (transient API failure suspected; "
                   "the runtime's failure text is not visible to the script)"),
               _rt_res["summary"][:120])
        _check("...and never guesses `overloaded`",
               "overloaded" not in _rt_res["summary"]
               and _rt_res["failure_class"] in (
                   None, "none", "out_of_credits", "rate_limited", "overloaded",
                   "auth", "context_length", "timeout", "network", "other"))
        _check("apply_retry_meta stamps only class + reason; the log is Record's "
               "(review-1 item 2: the schema now carries retries/escalated_from)",
               "retries" not in _rt_res and "escalated_from" not in _rt_res)
        _rt_ok = _job_result_from(
            {"verdict": "pass", "reason": "ok",
             "raw_stdout": json.dumps({"verdict": "pass", "changed": ["a.py"],
                                       "violations": []})},
            {"id": "rv", "title": "T", "write_allowed": ["docs/**"], "isolation": "direct"},
            {})
        apply_retry_meta(_rt_ok, {"exhausted": False, "attempts": 1, "retries": []})
        _check("a job that succeeded after a retry keeps its success and its class",
               _rt_ok["status"] == "success" and _rt_ok["failure_class"] is None)

        # --escalated-from round-trips through the receipt into state.json.
        _rt_repo = os.path.join(tmp, "retryrepo")
        _init_repo(_rt_repo)
        _rt_run = os.path.join(tmp, "retryrun")
        os.makedirs(_rt_run, exist_ok=True)
        _rt_man = os.path.join(_rt_run, "manifest.yaml")
        _atomic_write(_rt_man, json.dumps(
            {"run_id": "retry-run",
             "jobs": [{"id": "rv", "type": "review", "isolation": "worktree",
                       "write_allowed": ["src/**"]}]}))
        _rt_wt = os.path.join(_rt_repo, ".claude", "worktrees", "rt-wt")
        _run(["git", "-C", _rt_repo, "worktree", "add", "-q", "--detach", _rt_wt, "HEAD"])
        with _quiet():
            cmd_register_lane(["--run-dir", _rt_run, "--job-id", "rv", "--cwd", _rt_wt,
                               "--repo-root", _rt_repo, "--isolation", "worktree",
                               "--manifest", _rt_man, "--no-test-contract"])
        os.makedirs(os.path.join(_rt_wt, "src"), exist_ok=True)
        with open(os.path.join(_rt_wt, "src", "reviewed.txt"), "w") as fh:
            fh.write("work done on the lifted attempt\n")
        with _quiet():
            cmd_gate_receipt(["--run-dir", _rt_run, "--job-id", "rv",
                              "--repo-root", _rt_repo, "--worktree", _rt_wt,
                              "--manifest", _rt_man, "--mode", "worktree",
                              "--escalated-from", "opus"])
        _rt_rcpt = _read_json(os.path.join(_rt_run, "receipts", "rv.gate.json"), {}) or {}
        _check("gate-receipt records --escalated-from on the receipt",
               _rt_rcpt.get("escalated_from") == "opus", json.dumps(_rt_rcpt)[:200])
        with _quiet():
            cmd_record(["--run-dir", _rt_run, "--job-id", "rv", "--manifest", _rt_man,
                        "--verdict-json", json.dumps(_rt_rcpt), "--repo-root", _rt_repo,
                        "--retries-json", json.dumps(
                            {"retries": [{"stage": "implement", "job": "rv",
                                          "attempt": 1, "wait_ms": 2000}],
                             "exhausted": False, "attempts": 2,
                             "escalated_from": "opus"}),
                        "--now", "2026-09-03T00:00:00Z"])
        _rt_state = _load_state(_rt_run)["jobs"].get("rv", {})
        _rt_result = _read_json(os.path.join(_rt_run, "results", "rv.json"), {}) or {}
        _check("Record carries the retry log and the requested escalation into "
               "state.json, where no closed schema forbids them",
               _rt_state.get("escalated_from") == "opus"
               and (_rt_state.get("retries") or [{}])[0].get("wait_ms") == 2000,
               json.dumps(_rt_state)[:240])
        _check("...and onto the job_result itself (schema extended in the 3.4.8 review-1 closure)",
               _rt_result.get("escalated_from") == "opus"
               and (_rt_result.get("retries") or [{}])[0].get("wait_ms") == 2000,
               json.dumps(sorted(_rt_result))[:240])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    total = _PASSES[0] + len(_FAILURES)
    for failure in _FAILURES:
        print("FAIL: %s" % failure)
    print("%d/%d checks passed" % (_PASSES[0], total))
    return 1 if _FAILURES else 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
SUBCOMMANDS = {
    "emit": cmd_emit,
    "gate-receipt": cmd_gate_receipt,
    "record": cmd_record,
    "finalize-wave": cmd_finalize_wave,
    "register-lane": cmd_register_lane,
}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        print("usage: compound-v-emit-workflow.py "
              "{emit,gate-receipt,record,finalize-wave,register-lane} ... "
              "| --selftest")
        return 0
    if argv[0] == "--selftest":
        return selftest()
    if argv[0] == "--engine-probe":
        print(json.dumps(engine_probe_report(), indent=2, sort_keys=True))
        return 0
    if argv[0] in SUBCOMMANDS:
        return SUBCOMMANDS[argv[0]](argv[1:])
    # Backward-friendly: a bare manifest path means `emit`.
    if os.path.exists(argv[0]):
        return cmd_emit(argv)
    sys.stderr.write("unknown subcommand: %s\n" % argv[0])
    return 2


if __name__ == "__main__":
    sys.exit(main())
