"""The advisory channel: hints that never change the verdict."""

import os

from . import _SCRIPTS_DIR
from .yamlload import ManifestParseError, load_yaml


# --------------------------------------------------------------------------- #
# ADVISORIES (v3.5.0). Advisory ≠ violation, and the split is load-bearing: an
# advisory NEVER enters `validate()`'s return, never changes the verdict, and never
# changes the exit code. It travels in its own `warnings` channel — the one
# `agents/partition-reviewer.md` surfaces under WARNINGS, where the co-change
# advisory already lives — because the thing it describes is a design smell the
# author may have chosen deliberately, not a broken manifest.
# --------------------------------------------------------------------------- #

# `.claude/agent-memory/<agent>/` (scope `project`) and `.claude/agent-memory-local/`
# (scope `local`) are where Claude Code's native persistent subagent memory lives.
AGENT_MEMORY_ROOTS = (".claude/agent-memory-local", ".claude/agent-memory")


def is_agent_memory_glob(glob):
    """True iff ``glob`` addresses nothing but a subagent-memory directory.

    Deliberately tolerant of the FORMS a hand-written manifest uses — a leading
    `./`, a stray leading `/`, surrounding quotes, trailing whitespace, with or
    without a `/**` tail — because the advisory exists to catch a lane the author
    typed, and a detector that only recognises one spelling catches nothing.
    """
    g = (glob or "").strip().strip('"').strip("'").strip()
    while g.startswith("./"):
        g = g[2:]
    g = g.lstrip("/")
    for root in AGENT_MEMORY_ROOTS:
        if g == root or g.startswith(root + "/"):
            return True
    return False


def unnamespaced_agent_memory_name(glob):
    """Return the bare agent name if ``glob`` addresses a non-namespaced,
    project-scope agent-memory directory (``.claude/agent-memory/<agent>/**``),
    else ``None``.

    Excludes the ``-local`` scope root: that directory is gitignored (never
    committed, see ``tests/test-agent-memory.sh``), so it cannot collide with
    another plugin's memory. Also excludes any glob already namespaced
    ``superpowers-v-<agent>`` — that IS the recommended form. Tolerant of the
    same forms ``is_agent_memory_glob`` is (leading ``./``, a stray leading
    ``/``, quotes)."""
    g = (glob or "").strip().strip('"').strip("'").strip()
    while g.startswith("./"):
        g = g[2:]
    g = g.lstrip("/")
    root = ".claude/agent-memory"
    if g == root or not g.startswith(root + "/"):
        return None
    agent = g[len(root) + 1:].split("/", 1)[0]
    if not agent or agent.startswith("superpowers-v-"):
        return None
    return agent


# --------------------------------------------------------------------------- #
# WAVE_EXCEEDS_RUNTIME_CONCURRENCY (v3.6.4) — advisory only, never a violation.
#
# The native Workflow runtime runs "up to 16 concurrent agents by default,
# fewer when Claude Code has fewer CPUs available, including inside a
# CPU-limited container"; `CLAUDE_CODE_WORKFLOW_MAX_CONCURRENT_AGENTS` (1-256,
# Claude Code >= 2.1.269) raises it (docs: code.claude.com/docs/en/workflows,
# "Behavior and limits", fetched 2026-09-21).
#
# TRANSPORT_AGENT_HEADROOM = 0, DERIVED, not guessed — from
# `scripts/compound-v-emit-workflow.py`'s own JS_TEMPLATE:
#   - `pipeline(wave, implementStage, gateStage, recordStage)` (l.3493) chains
#     the three stages PER ITEM: `gateStage(prev, job)` (l.3093) and
#     `recordStage(verdict, job)` (l.3226) each take the PRIOR stage's awaited
#     result, so a job is in exactly one of {Implement, Gate, Record} at a time.
#   - Every retry path is itself a sequential `await`: `withRetry` (l.2895)
#     loops attempts with `await fn()`, and the one-shot reviewer escalation in
#     `implementStage` (l.3013-3031) `await`s its lifted attempt after the
#     first has already exhausted — never alongside it.
#   - `register-lane` is NOT a spawned agent: it is the Implement agent's own
#     FIRST BASH COMMAND (l.2592), run inside that same agent, not a second one.
#   - `alreadyIntegratedIds()` (the one-off Continuity agent) runs ONCE, before
#     wave 0 (l.3466); `finalizeWave` runs once per wave, AFTER `pipeline()` has
#     already resolved (l.3538 `await pipeline(...)`, l.3538+ `await
#     finalizeWave(...)`). Neither overlaps a wave's own job agents.
#   - `IMPLEMENT_DISALLOWED` (l.205) denies `Task`/`Agent` to every implementer,
#     so a job cannot fan out a nested agent that would add to the count either.
# So the emitter's own peak concurrent-agent count for a wave of W jobs is
# exactly W — never a multiple of it — and the runtime's 16-agent default
# applies to wave WIDTH directly, with no headroom to subtract.
RUNTIME_CONCURRENCY_DEFAULT = 16
TRANSPORT_AGENT_HEADROOM = 0


def _emit_workflow_module():
    """Load ``compound-v-emit-workflow.py``'s ``topo_waves`` by path (read-only
    sibling reuse, the pattern this project already uses elsewhere — e.g.
    ``compound-v-classify-request.py``'s ``_resolve_model_module``) so the
    WAVE_EXCEEDS_RUNTIME_CONCURRENCY advisory groups jobs into EXACTLY the
    waves Engine C would dispatch, instead of forking a second copy of that
    grouping algorithm. Cached after the first load. ``None`` on any failure —
    degrade-safe, same as every other advisory: the hard invariant checks above
    already own dangling-ref/cycle/type problems, so a wave computation that
    cannot run here costs nothing but this one extra hint.
    """
    global _EMIT_WORKFLOW_MODULE
    if _EMIT_WORKFLOW_MODULE is not None:
        return _EMIT_WORKFLOW_MODULE
    import importlib.util

    path = os.path.join(_SCRIPTS_DIR,
                        "compound-v-emit-workflow.py")
    try:
        spec = importlib.util.spec_from_file_location("_cv_emit_workflow_wavecheck", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _EMIT_WORKFLOW_MODULE = mod
        return mod
    except Exception:  # noqa: BLE001 — never let this sink the whole validator
        return None


_EMIT_WORKFLOW_MODULE = None


def wave_concurrency_advisories(manifest):
    """Return WAVE_EXCEEDS_RUNTIME_CONCURRENCY advisory strings — never
    violations, never verdict-changing (see the module docstring at the top of
    the ADVISORIES section). Fires when a dependency wave `topo_waves()` would
    actually dispatch has more jobs than
    ``RUNTIME_CONCURRENCY_DEFAULT - TRANSPORT_AGENT_HEADROOM`` (16 - 0 = 16
    today). Silent (returns []) on anything that isn't a clean, already-valid
    DAG with an int ``max_parallel`` — the hard checks above own a dangling
    ref, a cycle, or a malformed field, and this advisory must never be the
    thing that raises on a broken manifest.
    """
    out = []
    if not isinstance(manifest, dict):
        return out
    jobs = manifest.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        return out
    mp = manifest.get("max_parallel")
    try:
        max_parallel = int(mp)
    except (TypeError, ValueError):
        return out
    mod = _emit_workflow_module()
    if mod is None:
        return out
    try:
        waves = mod.topo_waves(jobs, max_parallel)
    except Exception:  # noqa: BLE001 — cycles/dangling refs are reported elsewhere
        return out
    limit = RUNTIME_CONCURRENCY_DEFAULT - TRANSPORT_AGENT_HEADROOM
    for idx, wave in enumerate(waves, start=1):
        width = len(wave)
        if width <= limit:
            continue
        ids = ", ".join(sorted(j.get("id") or "<no id>" for j in wave
                               if isinstance(j, dict)))
        out.append(
            "wave %d (%s): %d jobs exceeds the native Workflow runtime's default "
            "concurrency cap of %d concurrent agents — the run will queue rather "
            "than fail, but the wave will not actually run at %d-wide unless you "
            "raise CLAUDE_CODE_WORKFLOW_MAX_CONCURRENT_AGENTS (1-256, Claude Code "
            ">= 2.1.269) before launching"
            % (idx, ids, width, RUNTIME_CONCURRENCY_DEFAULT, width)
        )
    return out


def advisories(manifest):
    """Return a list of ADVISORY strings. Never violations; never verdict-changing.

    **memory-only lane.** A job whose `write_allowed` is nothing but agent-memory
    globs is a trap: `compound-v-emit-workflow.py` refuses a job that declares a lane
    and changes no files (`no_work`), so such a job passes only when the agent
    happens to have something durable to save — and fails when it honestly has
    nothing. That pressures an agent to invent a memory entry to get its job green,
    which is the fabricated-evidence pattern wearing a new hat. The fix is structural
    and belongs to the author: pair the memory glob with the job's real output lane,
    or declare `write_allowed: []` and let the agent's memory write fail loudly
    instead of quietly deciding the job's verdict.

    **memory lane not namespaced (MEMORY_LANE_UNNAMESPACED).** A job's committed,
    project-scope memory directory `.claude/agent-memory/<agent>/**` is shared with
    every plugin installed in the same repo; an unnamespaced agent name (`spec-reviewer`
    rather than `superpowers-v-spec-reviewer`) can collide with another plugin's
    memory-bearing agent of the same name. Independent of the memory-only-lane check
    above — it fires whether or not the memory glob is paired with a real output lane.
    """
    out = []
    if not isinstance(manifest, dict):
        return out
    jobs = manifest.get("jobs")
    if not isinstance(jobs, list):
        return out
    for job in jobs:
        if not isinstance(job, dict):
            continue
        globs = job.get("write_allowed")
        if not isinstance(globs, list) or not globs:
            continue
        jid = job.get("id") or "<no id>"

        seen_agents = set()
        for g in globs:
            if not isinstance(g, str):
                continue
            agent = unnamespaced_agent_memory_name(g)
            if agent is None or agent in seen_agents:
                continue
            seen_agents.add(agent)
            out.append(
                "job %r: memory lane '.claude/agent-memory/%s/**' is not "
                "namespaced — this project's own agents write to "
                "'.claude/agent-memory/superpowers-v-%s/**'; a committed, "
                "project-scope memory directory is shared with every plugin "
                "in the repo, and an unnamespaced agent name can collide "
                "with another plugin's memory-bearing agent of the same name"
                % (jid, agent, agent)
            )

        if not all(isinstance(g, str) and is_agent_memory_glob(g) for g in globs):
            continue
        out.append(
            "job %r: memory-only lane: a job that writes nothing else is blocked as "
            "no_work; pair the memory glob with the job's real output lane or declare "
            "write_allowed: []" % (jid,)
        )
    out.extend(wave_concurrency_advisories(manifest))
    return out


def cross_model_receipt_advisories(receipt):
    """Return ADVISORY strings for a (already-parsed) cross-model receipt.
    Never violations; never verdict-changing — called independently of
    ``_validate_cross_model_receipt``, which owns the hard fail-closed checks.

    **SECOND_OPINION_SAME_FAMILY.** A receipt with `reviewer_backend:
    claude-advisor` and `cross_model: false` is a VALID, honestly-labelled
    receipt — the validator's disagreement check in
    ``_validate_cross_model_receipt`` already refuses the dishonest shape
    (claude-advisor + `cross_model: true`). But honest is not the same as a
    genuine second opinion: the advisor is the SAME model family that wrote
    the code and reviews it in-harness, so this is a same-family opinion, and
    the orchestrator should know that even on a clean PASS."""
    out = []
    if not isinstance(receipt, dict):
        return out
    if (str(receipt.get("reviewer_backend")) == "claude-advisor"
            and receipt.get("cross_model") is False):
        out.append(
            "cross-model receipt reviewer_backend 'claude-advisor' is the SAME "
            "model family as the implementer and the in-harness reviewer — "
            "cross_model: false makes this explicit. This is a same-family "
            "second opinion, not an independent one"
        )
    return out


def advisories_text(text):
    """``advisories`` over raw manifest text. An unparseable manifest yields none —
    the violation channel is what reports a parse failure, and an advisory must never
    be the first thing a reader sees about a broken file."""
    try:
        return advisories(load_yaml(text))
    except ManifestParseError:
        return []
