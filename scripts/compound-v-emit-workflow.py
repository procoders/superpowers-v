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
                 results/<job-id>.json + state.json, and merge the worktree back
                 AT MOST ONCE per realised commit.
  register-lane  the Implement agent's FIRST command: bind its real worktree to
                 its job id in lane-map.json, which is what makes
                 hooks/lane-guard.sh able to resolve an acting job at all.

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
REPO_DEFAULT = os.path.dirname(HERE)

SCOPE_CHECK_DEFAULT = os.path.join(HERE, "compound-v-scope-check.py")
FASTPATH_DEFAULT = os.path.join(HERE, "compound-v-fastpath-run.py")
INTEGRATION_GATE_DEFAULT = os.path.join(HERE, "compound-v-integration-gate.py")

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

STAGE_PHASES = ["Implement", "Gate", "Record"]

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


def build_plan(manifest, run_dir, repo_root, python_bin, self_path,
               scope_check, fastpath, workers_dir):
    """Everything the emitted script needs, as plain data."""
    run_id = manifest.get("run_id") or os.path.basename(os.path.normpath(run_dir))
    max_parallel = manifest.get("max_parallel") or 4
    jobs = manifest.get("jobs") or []
    waves = topo_waves(jobs, max_parallel)

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
        return {
            "id": job_id,
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
            "implement_clamp": clamp,
        }

    return {
        "run_id": run_id,
        "run_dir": os.path.abspath(run_dir),
        "repo_root": os.path.abspath(repo_root),
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
    },
}


def _implement_prompt(job, plan):
    """The implementer's prompt. Ends with the enforcement-field lock."""
    lines = []
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
    lines.append('  --run-dir %s --job-id %s --cwd "$PWD"' % (plan["run_dir"], job["id"]))
    lines.append("```")
    lines.append("")
    if job["backend"] != "claude" and job["worker_script"]:
        lines.append("THIS JOB RUNS ON AN EXTERNAL BACKEND (%s)." % job["backend"])
        lines.append("You do not implement it yourself. Launch the worker script,")
        lines.append("which creates and OWNS its own git worktree — you are running at")
        lines.append("`direct` isolation precisely so no worktree is nested inside another:")
        lines.append("")
        lines.append("```bash")
        lines.append("%s ..." % job["worker_script"])
        lines.append("  # --test-contract-file %s"
                     % os.path.join(plan["run_dir"], "jobs",
                                    "%s.test-contract.json" % job["id"]))
        lines.append("```")
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
    lines.append("RETURN a raw result: `status`, the absolute `worktree` you worked in")
    lines.append("(`pwd`), and a `summary`.")
    lines.append("")
    lines.append("DO NOT report `blocked`, `files_changed` or `violations`. Those are")
    lines.append("enforcement fields, they are git-derived by the caller, and a")
    lines.append("constrained party filling in its own enforcement fields is the")
    lines.append("fabricated-evidence pattern. The gate derives them from git.")
    return "\n".join(lines)


def _gate_command(job, plan):
    return (
        "%s %s gate-receipt --run-dir %s --job-id %s --worktree <ABSOLUTE_WORKTREE>"
        % (plan["python"], plan["emitter"], plan["run_dir"], job["id"])
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
  const raw = await agent(p.implement, opts);
  return { job: job, implement: raw };
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
    const worktree = (impl.worktree || '').trim();
    if (!worktree) {
      return gateFailure(job.id, 'implement agent reported no worktree; nothing to gate');
    }

    const cmd = CFG.python + ' ' + CFG.emitter + ' gate-receipt' +
      ' --run-dir ' + q(CFG.run_dir) +
      ' --job-id ' + q(job.id) +
      ' --worktree ' + q(worktree) +
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
// Stage 3 — Record. Idempotent, and every commit merged AT MOST ONCE.
//
// Idempotence alone is not enough: a relaunch re-runs every agent that started
// after a failed one, INCLUDING completed ones, so a finished job can implement,
// gate and record a second time. The at-most-once property is keyed to an
// immutable commit hash in Python (see `record`), not to this stage running once.
// ---------------------------------------------------------------------------
async function recordStage(verdict, job) {
  try {
    const v = verdict || gateFailure(job.id, 'record received a null verdict');
    const cmd = CFG.python + ' ' + CFG.emitter + ' record' +
      ' --run-dir ' + q(CFG.run_dir) +
      ' --job-id ' + q(job.id) +
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
// Waves. Each wave is a BARRIER, and the barrier is load-bearing.
//
// A prerequisite's merge-back only STAGES (`git apply --index` does not commit),
// so a dependent worktree created at HEAD would not contain it. Record commits
// inside the wave, and the next wave's agents — hence the next wave's worktrees —
// are not spawned until this whole wave has resolved. Do not flatten the waves.
// ---------------------------------------------------------------------------
const summary = { run_id: CFG.run_id, waves: [], stopped_for_budget: false };

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
  summary.waves.push(waveSummary);
  log(title + ' done: ' + JSON.stringify(waveSummary.jobs));
}

log('Engine C finished. The workflow gate is defence in depth and an early exit — ' +
    'run scripts/compound-v-integration-gate.py before integrating any commit.');

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


def register_lane(run_dir, job_id, cwd, manifest_path=None, agent_id=None):
    """Bind one job to its real worktree (and agent id, if ever available).

    MERGES; never overwrites. Concurrent implementers in the same wave each call
    this, so a last-writer-wins overwrite would erase its siblings' lanes and put
    the guard straight back to failing open.
    """
    path = lane_map_path(run_dir)
    run_id = os.path.basename(os.path.normpath(run_dir))
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
    ap.add_argument("--repo-root", default=REPO_DEFAULT)
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

    root = os.path.abspath(args.worktree)
    if not os.path.isdir(root):
        out["reason"] = "worktree does not exist: %s" % root
        print(json.dumps(out, indent=2, sort_keys=True))
        return 2

    # The baseline is the PINNED pre-launch SHA recorded on state.json, never a
    # live HEAD. Pinning it is what keeps an executor that COMMITS inside its
    # worktree visible to the gate; measured against HEAD such a job looks clean.
    state = _load_state(run_dir)
    state_job = state["jobs"].get(job_id) or {}
    baseline = state_job.get("baseline")
    reasons = []
    if not baseline:
        baseline = _head_commit(root)
        reasons.append(
            "state.json pinned no baseline for this job; fell back to the "
            "worktree HEAD, which a worker that commits can move"
        )
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
        contract_out = os.path.join(run_dir, "jobs", "%s.test-contract.json" % job_id)
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


def _job_result_from(verdict, job, state_job, tests=None):
    """The canonical job_result. Enforcement fields come from the GATE, not the
    implementer: `blocked`, `files_changed` and `violations` are git-derived."""
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

    result = {
        "status": status,
        "blocked": gate_verdict == "blocked",
        "files_changed": changed,
        "violations": violations,
        "summary": verdict.get("reason") or (job.get("title") or job.get("id") or ""),
        "session_id": state_job.get("session_id"),
        "worktree": state_job.get("worktree"),
        "exit_code": verdict.get("exit_code", 0),
        "failure_class": None if status in ("success", "blocked") else "unknown",
        "retry_after_seconds": None,
    }
    if tests is not None:
        result["tests"] = tests

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
    ap.add_argument("--repo-root", default=REPO_DEFAULT)
    ap.add_argument("--now")
    ap.add_argument("--no-merge", action="store_true",
                    help="persist only; used by the selftest and by /v:collect")
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

    state = _load_state(run_dir)
    state_job = state["jobs"].setdefault(job_id, {})

    # The receipt binds to the worktree the gate observed, so record it: the
    # integration authority reads `worktree` from state.json (or the result) to
    # decide WHERE to gate, and a null there is why every job read `unverifiable`.
    receipt_path = os.path.join(run_dir, "receipts", "%s.gate.json" % job_id)
    receipt_doc = _read_json(receipt_path, {}) or {}
    tests = receipt_doc.get("tests")

    lane = _read_json(lane_map_path(run_dir), {}) or {}
    for path, mapped in (lane.get("worktrees") or {}).items():
        if mapped == job_id:
            state_job["worktree"] = path
            break
    if verdict.get("baseline_commit"):
        state_job.setdefault("baseline", verdict["baseline_commit"])

    result = _job_result_from(verdict, job, state_job, tests=tests)

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

    # ---- merge-back, AT MOST ONCE per realised commit ----------------------
    realised = verdict.get("realised_commit")
    merged_record = state_job.get("merged") or {}
    if result["status"] != "success":
        ack["reason"] = "not merged: gate verdict was %r" % verdict.get("verdict")
    elif args.no_merge:
        ack["reason"] = "merge suppressed by --no-merge"
    elif realised and merged_record.get("realised_commit") == realised:
        ack["reason"] = (
            "already merged for realised commit %s — a relaunch re-runs completed "
            "agents, so this is the at-most-once guard doing its job" % realised[:12]
        )
    elif not state_job.get("worktree"):
        ack["reason"] = "direct job (no worktree): changes are already in the tree"
        state_job["merged"] = {"realised_commit": realised, "mode": "direct"}
    else:
        ok, err = merge_back(
            state_job["worktree"], os.path.abspath(args.repo_root),
            state_job.get("baseline"), result["files_changed"],
        )
        if ok:
            ack["merged"] = True
            state_job["merged"] = {"realised_commit": realised, "mode": "worktree"}
        else:
            ack["reason"] = "merge-back failed: %s" % err
            result["status"] = "error"
            _atomic_write(
                result_path, json.dumps(result, indent=2, sort_keys=True) + "\n"
            )
            ack["status"] = "error"

    state_job["status"] = {
        "success": "done", "blocked": "blocked",
    }.get(result["status"], "failed")
    state_job.setdefault("isolation", job.get("isolation") or "direct")
    _save_state(run_dir, state, now=args.now)

    print(json.dumps(ack, indent=2, sort_keys=True))
    return 0


# --------------------------------------------------------------------------- #
# register-lane
# --------------------------------------------------------------------------- #
def cmd_register_lane(argv):
    ap = argparse.ArgumentParser(prog="compound-v-emit-workflow.py register-lane")
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--job-id", required=True)
    ap.add_argument("--cwd", required=True)
    ap.add_argument("--manifest")
    ap.add_argument("--agent-id",
                    help="the PreToolUse payload's agent_id, IF the runtime ever "
                         "exposes it to the agent itself. It does not on 2.1.238.")
    args = ap.parse_args(argv)
    lane = register_lane(
        os.path.abspath(args.run_dir), args.job_id, args.cwd,
        manifest_path=args.manifest, agent_id=args.agent_id,
    )
    print(json.dumps(
        {"registered": args.job_id,
         "worktrees": len(lane.get("worktrees") or {}),
         "agents": len(lane.get("agents") or {})},
        indent=2, sort_keys=True,
    ))
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
    ap.add_argument("--repo-root", default=REPO_DEFAULT)
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

    plan = build_plan(
        manifest, run_dir, args.repo_root, args.python,
        os.path.abspath(__file__), args.scope_check, args.fastpath,
        args.workers_dir,
    )
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
    report = {
        "script": out_path,
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
             "write_allowed": ["x/**"]},
            {"id": "g1", "backend": "gemini", "isolation": "worktree",
             "write_allowed": ["y/**"]},
        ]
        cplan = _plan_for(_tiny_manifest(codex_jobs), tmp, workers_dir=workers)
        entries = {j["id"]: j for w in cplan["waves"] for j in w}
        _check("a non-claude job runs its AGENT at direct isolation (no nesting)",
               entries["c1"]["isolation"] == "direct"
               and entries["c1"]["agent_isolation"] is None)
        _check("a non-claude job's clamp admits its worker script",
               any(worker_sh in rule for rule in entries["c1"]["implement_clamp"]))
        _check("no worker script ⇒ NO clamp, rather than a clamp that binds nothing",
               entries["g1"]["implement_clamp"] is None)
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
                "job_id": "j1", "verdict": "pass",
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
    "register-lane": cmd_register_lane,
}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        print("usage: compound-v-emit-workflow.py "
              "{emit,gate-receipt,record,register-lane} ... | --selftest")
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
