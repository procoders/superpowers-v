"""Dependency waves, agent roles and definitions, and each job's model and turn cap."""

from __future__ import annotations

import os
import json

from .util import (
    HERE, RESOLVE_MODEL_DEFAULT, _run, _read_json,
)


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
# So exactly ONE mapping BY JOB TYPE is made here, and only where a job's own
# declared type says the work IS that role — this dict never grows a `gate` or
# `record` entry, because those are not job types.
#
# Gate, Record, Finalize and Continuity are a SEPARATE case, resolved once per
# run (not per job) by `resolve_role_agent_type("transport")` below and carried
# as `CFG.transport_agent_type` — see `agentTransport` in the JS_TEMPLATE. Until
# 3.6.4 the reason they stayed anonymous was that every agent under `agents/`
# declared no `tools:` restriction, so spawning a de-tooled single-command
# transport by role would have hand it back the whole toolbox — the opposite of
# `disallowedTools` + `bashCommandClamp`. `agents/transport.md` is the fix:
# it declares its OWN `tools: Bash, StructuredOutput`, so spawning it by role
# ADDS a restriction (native, on top of the same `disallowedTools` +
# `bashCommandClamp` opts these calls already carried) instead of removing one,
# and its `omitClaudeMd: true` is the actual payoff — four spawns per job plus
# one per wave stop loading this repository's own CLAUDE.md/AGENTS.md for an
# agent whose entire job is "run one command and return its JSON verbatim".
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


def resolve_role_agent_type(role, plugin_dir=None):
    """(agent_type or None, reason) for a BARE role name — no job-type mapping.

    Split out of `resolve_agent_type` (3.6.4) so a fixed, non-job-scoped role
    (`transport`, spawned uniformly by Gate/Record/Finalize/Continuity, never
    keyed to any job's `type`) can resolve through the identical file-exists +
    plugin-manifest-name lookup `agent_role_for` feeds `resolve_agent_type`
    with. Never guesses a name: an agent file or a manifest name that cannot be
    found returns `None`, and the caller stays anonymous rather than emitting
    an `agentType` that resolves to nothing.
    """
    root = plugin_dir or os.path.dirname(HERE)
    if not os.path.exists(os.path.join(root, "agents", "%s.md" % role)):
        return None, "no agents/%s.md under %s" % (role, root)
    manifest = os.path.join(root, ".claude-plugin", "plugin.json")
    doc = _read_json(manifest, None)
    name = (doc or {}).get("name")
    if not (isinstance(name, str) and name.strip()):
        return None, "plugin manifest %s declares no name" % manifest
    return "%s:%s" % (name.strip(), role), None


def resolve_agent_type(job_type, plugin_dir=None):
    """(agent_type or None, reason). Never guesses a name."""
    role, decline = agent_role_for(job_type)
    if not role:
        return None, decline
    return resolve_role_agent_type(role, plugin_dir=plugin_dir)


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
