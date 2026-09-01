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

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

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
def _import_integration_gate(path=None):
    target = path or INTEGRATION_GATE_DEFAULT
    if not os.path.exists(target):
        return None
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("cv_integration_gate", target)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:  # noqa: BLE001
        return None


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


def compute_diff_digest(root, baseline, gate_module=None):
    module = gate_module if gate_module is not None else _import_integration_gate()
    if module is not None and hasattr(module, "compute_diff_digest"):
        try:
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


def resolve_agent_type(job_type, plugin_dir=None):
    """(agent_type or None, reason). Never guesses a name."""
    role = AGENT_TYPE_BY_JOB_TYPE.get((job_type or "").strip())
    if not role:
        return None, None
    root = plugin_dir or os.path.dirname(HERE)
    if not os.path.exists(os.path.join(root, "agents", "%s.md" % role)):
        return None, "no agents/%s.md under %s" % (role, root)
    manifest = os.path.join(root, ".claude-plugin", "plugin.json")
    doc = _read_json(manifest, None)
    name = (doc or {}).get("name")
    if not (isinstance(name, str) and name.strip()):
        return None, "plugin manifest %s declares no name" % manifest
    return "%s:%s" % (name.strip(), role), None


def _clamp_rules(job, python_bin, self_path, worker_script_for):
    """The bashCommandClamp for one job's IMPLEMENT agent.

    Spec D5.1: a non-`claude` job's clamp MUST admit
    `scripts/compound-v-run-<backend>-worker.sh`, or carry no clamp. A clamp that
    can bind nothing makes the runtime refuse the spawn — which fails loudly
    rather than degrading, but it still means the second family cannot launch.

    Rule syntax is the standard permission rule, validated by the runtime:
    `Bash(<command or prefix>)`, tool name case-sensitive, no whitespace padding
    inside the parens. An entry that parses to a tool with no rule content is an
    "inert clamp entry" and the spawn is refused.
    """
    backend = job.get("backend") or "claude"
    rules = ["Bash(%s %s register-lane:*)" % (python_bin, self_path)]
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


def resolve_job_model(job, python_bin, resolve_model=None):
    """(model, error). An explicit `model` wins; otherwise `tier` is resolved.

    Fails closed: an external backend's argv cannot be completed without a
    concrete model, and `--model` is one of the worker script's own required
    arguments. Guessing one here would be a fabricated routing decision.
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
    cmd = [python_bin, target, "--backend", job.get("backend") or "claude",
           "--tier", tier.strip()]
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


def render_worker_prompt(job, run_id):
    """The task itself, as the file the worker is handed via `--prompt-file`."""
    lines = ["# %s" % (job.get("title") or job.get("id")),
             "",
             "Compound V run `%s`, job `%s`." % (run_id, job.get("id")),
             ""]
    body = job.get("description") or job.get("prompt") or job.get("spec")
    if isinstance(body, str) and body.strip():
        lines += [body.strip(), ""]
    deps = job.get("depends_on") or []
    if isinstance(deps, str):
        deps = [deps]
    if deps:
        lines += ["Prerequisites, already merged and COMMITTED into your base "
                  "before this worktree was created: %s." % ", ".join(deps), ""]
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
    lines += [
        "## What you must NOT report",
        "",
        "Do not report `blocked`, `files_changed` or `violations`. Those are",
        "enforcement fields, they are derived from git by the caller, and a",
        "constrained party filling in its own enforcement fields is the",
        "fabricated-evidence pattern.",
    ]
    return "\n".join(lines) + "\n"


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
        argv += ["--timeout-sec", str(timeout)]
    effort = job.get("effort")
    if isinstance(effort, str) and effort.strip():
        argv += ["--effort", effort.strip()]
    argv += ["--events-log", os.path.join(run_dir, "logs", "%s.events.jsonl" % job["id"])]
    if entry.get("test_contract_file"):
        argv += ["--test-contract-file", entry["test_contract_file"]]
    return argv


def _shell_join(argv):
    try:
        import shlex
        return " \\\n  ".join(shlex.quote(a) for a in argv)
    except Exception:  # noqa: BLE001
        return " ".join(argv)


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
        entry = {
            "id": job_id,
            "job_type": job.get("type"),
            "agent_type": agent_type,
            "agent_type_note": agent_type_note,
            "title": job.get("title") or job_id,
            "backend": backend,
            "tier": job.get("tier"),
            "effort": job.get("effort"),
            "model": job.get("model"),
            "isolation": isolation,
            "agent_isolation": "worktree" if isolation == "worktree" else None,
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
            "implement_clamp": clamp,
            "prompt_file": worker_prompt_path(abs_run_dir, job_id),
            "launch_argv_file": None,
            "launch_argv": None,
            "launch_command": None,
        }
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
            model, err = resolve_job_model(job, python_bin)
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
        "python": python_bin,
        "emitter": self_path,
        "scope_check": scope_check,
        "fastpath": fastpath,
        "max_parallel": max_parallel,
        "budget_reserve_per_agent": BUDGET_RESERVE_PER_AGENT,
        "narrow_disallowed": NARROW_DISALLOWED,
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
        # The Record stage reports whether it appended the run's triage `actual`.
        # RECORD_SCHEMA is additionalProperties:false, so a field the ack emits
        # and the schema does not declare would make the Record agent's
        # structured result invalid — and Record is the stage that must never be
        # the thing that fails.
        "triage_actual": {"type": "string"},
    },
}


def _implement_prompt(job, plan):
    """The implementer's prompt. Ends with the enforcement-field lock."""
    lines = []
    if job.get("agent_type"):
        # Spawned BY ROLE. The role contract lives in that agent's own
        # definition, so this prompt supplies the job's inputs and nothing else —
        # restating the contract here is how the two copies drift apart.
        lines.append("You are spawned as `%s`. Your role, your passes and your "
                     "verdict vocabulary come from your OWN agent definition; "
                     "this prompt carries only Compound V job `%s`'s inputs."
                     % (job["agent_type"], job["id"]))
    else:
        lines.append("You are the implementer for Compound V job `%s`." % job["id"])
    lines.append("")
    lines.append("TITLE: %s" % job["title"])
    lines.append("")
    lines.append("FIRST COMMAND, BEFORE ANY OTHER TOOL CALL — register your lane.")
    lines.append("This is what lets `hooks/lane-guard.sh` resolve which job an")
    lines.append("out-of-lane write belongs to. Without it the guard resolves")
    lines.append("nothing, fails open, and silently allows every write:")
    lines.append("")
    lines.append("```bash")
    lines.append('%s %s register-lane \\' % (plan["python"], plan["emitter"]))
    lines.append('  --run-dir %s --job-id %s --cwd "$PWD" \\'
                 % (plan["run_dir"], job["id"]))
    lines.append('  --repo-root %s --isolation %s'
                 % (plan["repo_root"], job["isolation"]))
    lines.append("```")
    lines.append("")
    lines.append("That command also PINS this job's baseline commit before anything")
    lines.append("changes, and it fails closed if it cannot. A gate measured against a")
    lines.append("HEAD that moved is a gate that passes the run it should have caught.")
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
    elif job["isolation"] == "worktree":
        lines.append("You are running in your OWN git worktree. Return its absolute path")
        lines.append("(`pwd`) as `worktree` — that is the tree the Gate measures.")
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
        "%s %s gate-receipt --run-dir %s --job-id %s --repo-root %s "
        "--mode %s --worktree <ABSOLUTE_GATE_ROOT>"
        % (plan["python"], plan["emitter"], plan["run_dir"], job["id"],
           plan["repo_root"],
           "worktree" if job["isolation"] == "worktree" else "direct")
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
        "python": plan["python"],
        "emitter": plan["emitter"],
        "budget_reserve_per_agent": plan["budget_reserve_per_agent"],
        "narrow_disallowed": plan["narrow_disallowed"],
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
// Stage 1 — Implement. Returns a RAW result, never a job_result.
// ---------------------------------------------------------------------------
async function implementStage(job) {
  try {
    const p = CFG.prompts[job.id];
    const opts = {
      label: 'implement ' + job.id,
      phase: 'Implement',
      schema: IMPLEMENT_SCHEMA
    };
    if (job.model) opts.model = job.model;
    if (job.effort) opts.effort = job.effort;
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
    const raw = await agent(p.implement, opts);
    return { job: job, implement: raw };
  } catch (e) {
    // A THROW here would drop the item and skip Gate AND Record — the v2.6.4
    // audit-trail loss, structurally. Return the failure as a value instead, so
    // the Gate reads it as null-is-FAIL and Record still writes a result.
    log('implement ' + job.id + ' threw: ' + String(e && e.message ? e.message : e));
    return { job: job, implement: null };
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
  try {
    if (prev === null || prev === undefined) {
      return gateFailure(job.id, 'implement stage produced null (skipped, or a terminal API error)');
    }
    const impl = prev.implement;
    if (impl === null || impl === undefined) {
      return gateFailure(job.id, 'implement agent returned null — treated as FAIL, never as a clean tree');
    }

    // WHERE TO GATE is decided by the MANIFEST's isolation, never by whether the
    // agent happened to return a non-empty locator. A `direct` job works in the
    // project checkout, so that checkout is the tree — and an agent that reports
    // some other pwd for a direct job is the exact failure this branch removes.
    let gateRoot;
    if (job.isolation === 'worktree') {
      gateRoot = (impl.worktree || '').trim();
      if (!gateRoot) {
        return gateFailure(job.id, 'worktree job reported no worktree; there is no tree to gate — fails closed');
      }
    } else {
      gateRoot = CFG.repo_root;
    }

    const cmd = CFG.python + ' ' + CFG.emitter + ' gate-receipt' +
      ' --run-dir ' + q(CFG.run_dir) +
      ' --job-id ' + q(job.id) +
      ' --repo-root ' + q(CFG.repo_root) +
      ' --worktree ' + q(gateRoot) +
      ' --manifest ' + q(CFG.manifest_path) +
      ' --mode ' + q(job.isolation === 'worktree' ? 'worktree' : 'direct') +
      (NOW ? ' --now ' + q(NOW) : '');

    const prompt =
      'Run EXACTLY this one command and return its JSON output verbatim as your ' +
      'structured result. Do not summarise it, do not re-run it, do not run ' +
      'anything else — your shell is clamped to this command form and any other ' +
      'command is denied.\n\n```bash\n' + cmd + '\n```\n';

    const opts = {
      label: 'gate ' + job.id,
      phase: 'Gate',
      schema: GATE_SCHEMA,
      // Narrow at spawn. Bash stays (a clamp on a Bash-less agent can bind
      // nothing and the runtime refuses the spawn); StructuredOutput stays or
      // schema mode is denied and the spawn is likewise refused.
      disallowedTools: CFG.narrow_disallowed,
      bashCommandClamp: [
        'Bash(' + CFG.python + ' ' + CFG.emitter + ' gate-receipt:*)'
      ]
    };

    const verdict = await agent(prompt, opts);
    if (verdict === null || verdict === undefined) {
      return gateFailure(job.id, 'gate agent returned null — FAIL, never pass');
    }
    if (!verdict.verdict) {
      return gateFailure(job.id, 'gate agent returned no verdict field');
    }
    return verdict;
  } catch (e) {
    // Everything. Including budget exhaustion, which throws.
    return gateFailure(job.id, 'gate stage caught: ' + String(e && e.message ? e.message : e));
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
    const v = verdict || gateFailure(job.id, 'record received a null verdict');
    const cmd = CFG.python + ' ' + CFG.emitter + ' record' +
      ' --run-dir ' + q(CFG.run_dir) +
      ' --job-id ' + q(job.id) +
      ' --repo-root ' + q(CFG.repo_root) +
      ' --manifest ' + q(CFG.manifest_path) +
      ' --verdict-json ' + q(JSON.stringify(v)) +
      (NOW ? ' --now ' + q(NOW) : '');

    const prompt =
      'Run EXACTLY this one command and return its JSON output verbatim as your ' +
      'structured result. It is idempotent; do not re-run it, and do not run ' +
      'anything else.\n\n```bash\n' + cmd + '\n```\n';

    const ack = await agent(prompt, {
      label: 'record ' + job.id,
      phase: 'Record',
      schema: RECORD_SCHEMA,
      disallowedTools: CFG.narrow_disallowed,
      bashCommandClamp: [
        'Bash(' + CFG.python + ' ' + CFG.emitter + ' record:*)'
      ]
    });
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
    const cmd = CFG.python + ' ' + CFG.emitter + ' finalize-wave' +
      ' --run-dir ' + q(CFG.run_dir) +
      ' --repo-root ' + q(CFG.repo_root) +
      ' --manifest ' + q(CFG.manifest_path) +
      ' --wave ' + q(String(waveIndex + 1)) +
      ' --jobs ' + q(ids) +
      (NOW ? ' --now ' + q(NOW) : '');

    const prompt =
      'Run EXACTLY this one command and return its JSON output verbatim as your ' +
      'structured result. It runs the integration authority over this wave and, ' +
      'only if the authority permits, merges and commits the wave. Do not ' +
      'summarise it, do not re-run it, do not run anything else.\n\n```bash\n' +
      cmd + '\n```\n';

    const res = await agent(prompt, {
      label: 'finalize ' + title,
      phase: 'Finalize',
      schema: FINALIZE_SCHEMA,
      disallowedTools: CFG.narrow_disallowed,
      bashCommandClamp: [
        'Bash(' + CFG.python + ' ' + CFG.emitter + ' finalize-wave:*)'
      ]
    });
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


def register_lane(run_dir, job_id, cwd, manifest_path=None, agent_id=None):
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
def _run_scope_check(scope_check, mode, root, baseline, allow, python_bin):
    cmd = [python_bin, scope_check]
    cmd += ["--worktree" if mode == "worktree" else "--repo", root]
    if baseline:
        cmd += ["--baseline", baseline]
    for glob in allow:
        cmd += ["--allow", glob]
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
    cmd = [python_bin, fastpath, "test-floor", "--worktree", worktree,
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
    cmd = [python_bin, fastpath, "resolve-tests", "--worktree", worktree,
           "--manifest", manifest_path, "--job-id", job_id, "--out", out_path,
           "--no-prior-run"]
    if baseline:
        cmd += ["--baseline", baseline]
    rc, _, _ = _run(cmd)
    return out_path if rc == 0 and os.path.exists(out_path) else None


def cmd_gate_receipt(argv):
    ap = argparse.ArgumentParser(prog="compound-v-emit-workflow.py gate-receipt")
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--job-id", required=True)
    ap.add_argument("--worktree", required=True)
    ap.add_argument("--manifest")
    ap.add_argument("--mode", choices=["worktree", "direct"], default="worktree")
    ap.add_argument("--repo-root", required=True,
                    help="the PROJECT root. Required: a `direct` job is gated in "
                         "this tree, and a defaulted root gates the wrong repo.")
    ap.add_argument("--scope-check", default=SCOPE_CHECK_DEFAULT)
    ap.add_argument("--fastpath", default=FASTPATH_DEFAULT)
    ap.add_argument("--python", default=(sys.executable or "python3"))
    ap.add_argument("--now")
    args = ap.parse_args(argv)

    run_dir = os.path.abspath(args.run_dir)
    manifest_path = os.path.abspath(
        args.manifest or os.path.join(run_dir, "manifest.yaml")
    )
    job_id = args.job_id
    out = {"job_id": job_id, "verdict": "error", "source": "gate-receipt"}

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
    rc, raw_stdout, err, parsed = _run_scope_check(
        args.scope_check, args.mode, root, baseline, allow, args.python
    )
    if baseline:
        digest, digest_err = compute_diff_digest(root, baseline)
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
    # The tree this gate MEASURED, carried forward to Record explicitly. Empty
    # for a direct job — that is a value, not a missing one, and Record branches
    # on the manifest's isolation rather than on whether this string is blank.
    out["worktree"] = "" if args.mode == "direct" else root
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
    """Stage exactly these paths. Returns (ok, error)."""
    for path in paths:
        if not path:
            continue
        rc, _, err = _git(worktree, ["add", "-A", "--", path])
        if rc != 0:
            return False, "git add failed for %r: %s" % (path, err.strip())
    return True, None


def merge_back(worktree, repo_root, baseline, files_changed):
    """Apply the gate-approved slice of a worktree into the main tree."""
    if not baseline:
        return False, "no pinned baseline; refusing to merge against a moving HEAD"
    if not files_changed:
        return True, None  # nothing approved, nothing to land
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
#     falls back to the job's declared `test_scope`, then to `full` — which is
#     the resolver's OWN default for an unset scope, not a guess about this run.
# --------------------------------------------------------------------------- #
TESTS_SCOPES = ("full", "impacted", "floor_only")


def _tests_block_from_floor(floor, contract=None, job=None):
    """Translate a `test-floor` document into the schema's `tests` block.

    Returns None when the floor ran no command — the schema says to omit the
    object entirely rather than report a fabricated zero.
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
        scope = "full"

    block = {
        "command": "\n".join(commands),
        "exit_code": int(exit_code),
        "scope": scope,
        "selected_count": len(commands),
    }
    failures = floor.get("failures")
    if isinstance(failures, list):
        block["failures"] = [str(f) for f in failures]
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
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("cv_triage_outcomes", target)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:  # noqa: BLE001
        return None


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


def _job_result_from(verdict, job, state_job, tests=None, contract=None,
                     isolation=None):
    """The canonical job_result. Enforcement fields come from the GATE, not the
    implementer: `blocked`, `files_changed` and `violations` are git-derived.

    `tests` is the RAW `test-floor` document; it is translated here into the
    schema's four-field block (see `_tests_block_from_floor`)."""
    raw = verdict.get("raw_stdout") or ""
    scope = None
    try:
        scope = json.loads(raw) if raw.strip() else None
    except Exception:  # noqa: BLE001
        scope = None
    changed = (scope or {}).get("changed") or []
    violations = (scope or {}).get("violations") or []
    gate_verdict = verdict.get("verdict")

    if gate_verdict == "pass":
        status = "success"
    elif gate_verdict == "blocked":
        status = "blocked"
    else:
        status = "error"

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
        worktree = state_job.get("worktree") or ""
    else:
        worktree = ""

    result = {
        "status": status,
        "blocked": gate_verdict == "blocked",
        "files_changed": changed,
        "violations": violations,
        "summary": verdict.get("reason") or (job.get("title") or job.get("id") or ""),
        "session_id": state_job.get("session_id") or "",
        "worktree": worktree,
        "exit_code": exit_code,
        # `unknown` is not in the schema's failure_class enum — `other` is the
        # declared bucket for "a non-success this producer cannot classify".
        "failure_class": None if status in ("success", "blocked") else "other",
        "retry_after_seconds": retry_after,
    }
    tests_block = _tests_block_from_floor(tests, contract, job)
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
    ap.add_argument("--verdict-json", required=True)
    ap.add_argument("--repo-root", required=True,
                    help="the PROJECT root. REQUIRED even though `record` no "
                         "longer writes to it: it is where the triage stream "
                         "lives, and a defaulted root wrote into the plugin's "
                         "own repository.")
    ap.add_argument("--now")
    ap.add_argument("--no-merge", action="store_true",
                    help="accepted and ignored. `record` never merges any more — "
                         "the wave finalizer does, after the authority runs.")
    args = ap.parse_args(argv)

    run_dir = os.path.abspath(args.run_dir)
    job_id = args.job_id
    ack = {"job_id": job_id, "recorded": False, "merged": False}

    try:
        verdict = json.loads(args.verdict_json)
    except Exception as exc:  # noqa: BLE001
        ack["reason"] = "verdict JSON unparseable: %s" % exc
        print(json.dumps(ack, indent=2, sort_keys=True))
        return 2
    if not isinstance(verdict, dict):
        verdict = {"verdict": "error", "reason": "verdict was not an object"}

    manifest_path = os.path.abspath(
        args.manifest or os.path.join(run_dir, "manifest.yaml")
    )
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
    isolation = job.get("isolation")
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
            ack["reason"] = (
                "the gate verdict for worktree job %r carries no observed "
                "`worktree`. Record will not reconstruct one from lane-map.json — "
                "that map holds the wrapper agent's cwd — so this fails closed"
                % job_id
            )
            print(json.dumps(ack, indent=2, sort_keys=True))
            return 2
        state_job["worktree"] = os.path.abspath(gate_worktree.strip())
    else:
        state_job["worktree"] = ""

    pinned = read_pinned_baseline(run_dir, job_id, state_job)
    if pinned:
        state_job["baseline"] = pinned
    elif verdict.get("baseline_commit"):
        state_job["baseline"] = verdict["baseline_commit"]

    result = _job_result_from(verdict, job, state_job, tests=tests,
                              contract=contract, isolation=isolation)

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

    # Merge this job's entry into a FRESHLY READ state.json, under the lock. The
    # triage join's third event is appended by whichever Record call finds every
    # job terminal — inside the same critical section, so "am I the last?" is
    # answered against the state that is about to be written, not a stale copy,
    # and the idempotence latch lands in the same write.
    with _run_dir_lock(run_dir):
        state = _load_state(run_dir)
        state["jobs"].setdefault(job_id, {}).update(state_job)
        note = _maybe_append_run_actual(
            run_dir, manifest, state, os.path.abspath(args.repo_root)
        )
        if note:
            ack["triage_actual"] = note
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

    # ---- 1. THE AUTHORITY, first ------------------------------------------- #
    rc, gate_out, gate_err = _run([
        args.python, args.integration_gate,
        "--run-dir", run_dir, "--repo-root", repo_root,
        "--manifest", manifest_path, "--jobs", ",".join(job_ids), "--json",
    ])
    try:
        report = json.loads(gate_out) if gate_out.strip() else None
    except Exception:  # noqa: BLE001
        report = None
    if not isinstance(report, dict):
        out["reason"] = ("the integration authority produced no report (rc=%d): %s"
                         % (rc, (gate_err or gate_out)[:300]))
        return emit(1)
    if report.get("integration") != "permitted":
        out["refused"] = report.get("refused") or job_ids
        out["reason"] = (
            "integration REFUSED by scripts/compound-v-integration-gate.py: %s. "
            "Nothing was merged and nothing was committed."
            % json.dumps(report.get("tally") or {})
        )
        return emit(1)

    # ---- 2. merge the permitted slices ------------------------------------- #
    manifest = {}
    if os.path.exists(manifest_path):
        try:
            manifest = _load_yaml(manifest_path) or {}
        except Exception:  # noqa: BLE001
            manifest = {}
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
            _save_state(run_dir, fresh, now=now)

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
        merged_record = state_job.get("merged") or {}

        if realised and merged_record.get("realised_commit") == realised \
                and merged_record.get("integrated"):
            approved.extend(files)
            out["merged"].append(job_id)
            continue  # at-most-once: a relaunch re-runs completed agents

        if isolation == "worktree":
            worktree = result.get("worktree") or state_job.get("worktree")
            if not worktree:
                out["refused"].append(job_id)
                out["reason"] = (
                    "job %s is isolation:worktree but resolves to no worktree; "
                    "there is nothing to merge FROM, so it fails closed" % job_id
                )
                break
            ok, err = merge_back(worktree, repo_root,
                                 read_pinned_baseline(run_dir, job_id, state_job),
                                 files)
            if not ok:
                out["refused"].append(job_id)
                out["reason"] = "merge-back failed for %s: %s" % (job_id, err)
                break
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
            return emit(1)
        if sha:
            out["commit"] = sha
            for job_id in out["merged"]:
                merged = dict(job_updates.get(job_id, {}).get("merged") or {})
                merged.update({"commit": sha, "integrated": True})
                job_updates.setdefault(job_id, {})["merged"] = merged
        else:
            out["commit"] = _head_commit(repo_root) or ""
            out["reason"] = ("nothing left to commit — this wave's work is already "
                             "in HEAD (idempotent re-finalize)")

    out["integrated"] = not out["refused"]
    if out["refused"]:
        out.setdefault("reason", "some jobs did not reach `success`")
    _apply(now=args.now)
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
    lane = register_lane(
        run_dir, args.job_id, args.cwd,
        manifest_path=args.manifest, agent_id=args.agent_id,
    )
    ack = {"registered": args.job_id,
           "worktrees": len(lane.get("worktrees") or {}),
           "agents": len(lane.get("agents") or {})}

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
    return {"run_id": "selftest-run", "max_parallel": max_parallel, "jobs": jobs}


def _plan_for(manifest, tmp, workers_dir=None):
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
        ext_plan = build_plan(ext_manifest, tmp, tmp, "/usr/bin/python3",
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
            {"run_id": "r", "jobs": [{"id": "x", "backend": "codex",
                                      "model": "gpt-5.6-sol",
                                      "isolation": "worktree",
                                      "write_allowed": ["src/**"]}]},
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

        # HIGH 3 — the handoff keeps its invocation, its worktree and its pin.
        ext2 = build_plan(
            {"run_id": "r3", "test_contract": {"floor_command": "sh -c 'exit 0'"},
             "jobs": [{"id": "e1", "backend": "codex", "isolation": "worktree",
                       "model": "gpt-5.6-sol", "effort": "high",
                       "timeout_sec": 900, "test_scope": "floor_only",
                       "write_allowed": ["src/**"]}]},
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
        _check("an ordinary implementation job stays anonymous",
               rev_entries["impl"]["agent_type"] is None)
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
               "return { job: job, implement: null };" in rev_script)

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
