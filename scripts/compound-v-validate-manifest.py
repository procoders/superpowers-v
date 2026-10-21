#!/usr/bin/env python3
"""
Compound V manifest validator — the DETERMINISTIC invariant gate.

Backs the ``partition-reviewer`` agent with a script that either passes or
fails with specifics. No LLM judgment, no network, no fabricated metrics.

Invariants enforced (from PRD §5.1/§5.5 + plan §5/§6)
----------------------------------------------------
1. **Disjoint write scope.** No file can be owned by two jobs. Because
   ``write_allowed`` entries are globs, we detect overlap deterministically:
   two globs conflict if a canonical witness path generated from one is
   matched by the other (checked both directions), or if they are identical.
2. **Codex ⇒ worktree.** Any job with ``backend: codex`` must have
   ``isolation: worktree``.
3. **Reviewers ⇒ deep/opus.** Any job whose ``type`` or ``id`` marks it a
   reviewer (spec/quality/integration/partition review) must resolve to the
   strongest reasoning: either ``tier: deep`` or ``model: opus``.
4. **Shared foundation serial.** Files declared shared/contract (via the
   ``shared_resources`` top-level list, if present) must each be written by a
   ``shared_foundation`` job whose ``run`` is ``serial``. Independently, any
   job typed ``shared_foundation`` must run ``serial``.
5. **Intent routing.** Jobs route by intent, not hardcoded model strings.
   Every job MUST carry ``model`` OR ``tier`` (model is now an optional
   override; existing explicit-model jobs stay valid — backward compatible).
   If present, ``tier`` ∈ {frontier, deep, standard, light} and ``effort`` ∈
   {low, medium, high, xhigh}. ``effort: xhigh`` is valid iff
   ``backend: codex`` (codex's kernel model_reasoning_effort accepts it —
   verified 2026-07-11 on codex-cli 0.144.1, re-verified 2026-09-24 on 0.156.1);
   any other backend with
   xhigh is a violation naming the rule.

Required-field + enum validation (before invariant checks)
-----------------------------------------------------------
All required fields per ``execution-manifest.md`` are checked first. Top-level:
``run_id``, ``jobs``, ``feature``, ``spec_path``, ``plan_path``, ``audits``,
``acceptance_criteria``, ``routing_stance``, ``max_parallel``. Per-job: ``id``,
``title``, ``type``, ``backend``, ``isolation``, ``run``, ``write_allowed``,
``read_allowed``, ``acceptance``, plus (``model`` OR ``tier``). Enums: ``backend``
∈ {claude, codex, antigravity, cursor, opencode} (``none`` is the routing
"return to planning" sentinel, NOT a dispatched job backend; ``opencode``
is a lower-trust, opt-in, WORKER-ONLY backend — see adapter-opencode.md);
``isolation`` ∈ {direct, worktree};
``run`` ∈ {serial, parallel};
``routing_stance`` ∈ {balanced, conservative, cost-aware, claude-only};
``tier`` ∈ {frontier, deep, standard, light}; ``effort`` ∈ {low, medium, high, xhigh}
(``xhigh`` valid iff ``backend: codex``).

Job ``id`` (and top-level ``run_id``) MUST match ``^[A-Za-z0-9._-]+$`` and not be
``.`` / ``..`` — ids become path segments, so a ``../x`` id is a path-traversal
vector and is rejected before dispatch.

**Parallel ⇒ worktree.** A ``run: parallel`` job MUST be ``isolation: worktree``
(per-job scope attribution needs isolation); ``isolation: direct`` is only valid
with ``run: serial``.

Structural sanity is also checked (jobs is a non-empty list; each job has an
``id``; ids unique; ``backend`` present; ``write_allowed`` is a list).

Structural TYPE checks: ``jobs`` non-empty list, ``acceptance_criteria`` list,
``audits`` mapping, ``max_parallel`` int, ``run_id``/``feature``/``spec_path``/
``plan_path`` strings, and per-job ``write_allowed``/``read_allowed``/``acceptance``
lists. A wrong-typed field is its own specific violation.

never-Haiku (execution layer): any job whose explicit ``model`` contains
``haiku`` (case-insensitive — ``haiku``, ``claude-haiku-...``) is rejected. The
frontmatter linter only sees agent/skill frontmatter; this closes the
execution-layer override path.

``depends_on``: every referenced id must exist among the manifest job ids (a
dangling ref is a violation) and the dependency graph must be acyclic (a cycle is
a violation naming the jobs on it).

v2.9 — conditional fast-path (only when a top-level ``fast_path`` block is present)
-----------------------------------------------------------------------------------
A ``fast_path`` manifest adds: single-literal-path partition, block-YAML audit
skip-records, cross-artifact binding (AC-13/CR2-3: the sole ``write_allowed``
literal == ``localization.resolved_paths[0]``; ``pre_eval_id`` / ``FASTPATH_ELIGIBLE``
decision / ``taxonomy_digest`` / localization content-digest equal across the
manifest + pinned pre-eval record + localization artifact), CR4-6 path containment
(normalized, repo-relative, realpath-under-root, committed regular file), a pinned-
snapshot taxonomy denylist, and TWO validation modes (CR4-1) — a ``fast_path``
manifest with **no** ``--mode`` is rejected (fail-closed):
  * ``--mode pre-dispatch`` validates the ``fast_path.review`` DECLARATION
    (``backend:claude`` + ``tier:deep`` OR ``model:opus``, resolved through
    compound-v-resolve-model.py to a concrete Claude Opus; CR4-8/CR5-5) and FORBIDS
    a receipt (it cannot exist yet).
  * ``--mode post-review`` REQUIRES + verifies the dispatcher-written invocation
    receipt (``schemas/fastpath-review-receipt.schema.json``) naming the resolved
    model before REVIEWED/MERGED.
A legacy (non-fast_path) manifest ignores ``--mode`` entirely — backward compatible.

v3.0 — `triage` (Feature A2) and `test_contract` (Feature B2)
--------------------------------------------------------------
Two OPTIONAL top-level blocks, both absent-valid so every manifest committed before
3.0 keeps validating unchanged.

``triage: {tier, pre_eval_id, taxonomy_digest, decided_at}`` becomes MANDATORY under
``--require-triage``, which ships **default OFF in every mode**: a mode-scoped default
is circular, since the block is emitted by the fast-path materializer and would red
that task's own e2e suite. The closure is behavioural — ``/v:dispatch`` passes the flag
on every live dispatch, while the CI historical sweep stays mode-less, which is what
keeps the committed run manifests valid WITHOUT a back-filled record. Under the flag a
missing block, a malformed one, a ``tier`` outside {DIRECT, SCOPED, FULL}, and a
``taxonomy_digest`` that disagrees with the taxonomy on disk (``--taxonomy FILE``,
default ``.claude/compound-v-impact-taxonomy.yaml``) are each a failure; an absent or
unreadable taxonomy fails CLOSED rather than skipping the comparison.

v3.4.1 adds ONE optional key, ``triage.flavor``, whose ONLY value is ``scoped_plus``
— a small edit on a sensitive path, banded SCOPED but reviewed like a FULL. Under
``--require-triage`` a ``scoped_plus`` manifest must carry a ``type: review`` job with
``tier: deep`` and ``backend: claude``; unknown triage keys stay rejected. The other
half of the SCOPED+ promise — an independent cross-model second opinion — cannot be
checked before dispatch, because its evidence does not exist yet, so it is checked
after the fact by ``--require-cross-model-receipt FILE`` (schema, ``run_id``,
``triage.pre_eval_id``, and a ``diff_digest`` that is well-formed, sealed under the
receipt's self-digest and equal to ``--expected-diff-digest`` when the caller passes
the bytes it sealed).

``test_contract: {floor_command, full_command, impacted_map[{when, run}]}`` plus per-job
``test_scope ∈ {full, impacted, floor_only}`` (absent ⇒ ``full``). Both halves of an
``impacted_map`` entry are mandatory, and a scope may never resolve to running NOTHING:
``floor_only`` requires a non-empty ``floor_command``, and ``impacted`` requires a
non-empty ``full_command`` because an unmapped path resolves to the full suite.

Usage
-----
    compound-v-validate-manifest.py <manifest.yaml>
    compound-v-validate-manifest.py --mode pre-dispatch|post-review \\
        [--repo-root DIR] [--config FILE] [--receipt FILE] <manifest.yaml>
    compound-v-validate-manifest.py [--require-triage] [--taxonomy FILE] <manifest.yaml>
    compound-v-validate-manifest.py --require-cross-model-receipt FILE \\
        [--expected-diff-digest sha256:...] <manifest.yaml>
    compound-v-validate-manifest.py --selftest

Exit codes: 0 = all invariants hold, 1 = one or more violations (printed),
2 = usage / parse error.

Python 3.9-safe, stdlib only. PyYAML used if importable; otherwise a tiny
embedded YAML-subset parser handles the manifest shape we emit.
"""

import sys


# --------------------------------------------------------------------------- #
# sys.path hardening — BEFORE the first import that can be shadowed
# (eighth review pass, item C2, 2026-09-03).
#
# THE ATTACK: this file runs with its OWN DIRECTORY first on `sys.path`, and it
# imports `yaml` to read the document that DEFINES every job's `write_allowed`.
# A `yaml.py` planted beside it — or in the CWD, which is on `sys.path` whenever
# this module is loaded by `python3 -c`, exactly how `hooks/lane-guard.sh` loads
# it from inside a worker's own worktree — is imported instead of PyYAML, and its
# `safe_load` then returns whatever lane it likes to the guard that is about to
# enforce it. Same shape for `json` and `re`.
#
# `python3 -P` / `PYTHONSAFEPATH` does this properly, and arrived in 3.11; this
# file targets stock-macOS 3.9.6, so it is done by hand. Two passes, because the
# first cannot use `os` — importing `os` is one of the things being made safe:
# strings first, then an exact realpath comparison once `os` is in hand.
def _harden_sys_path():
    here = __file__
    cut = here.rfind("/")
    unsafe = {"", ".", (here[:cut] if cut > 0 else ".")}
    sys.path[:] = [p for p in sys.path if p not in unsafe]

    import os  # noqa: E402 - after the string pass above, on purpose

    drop = set()
    try:
        drop.add(os.path.realpath(os.path.dirname(os.path.abspath(__file__))))
    except (OSError, ValueError):
        pass
    try:
        drop.add(os.path.realpath(os.getcwd()))
    except (OSError, ValueError):
        pass
    keep = []
    for p in sys.path:
        try:
            resolved = os.path.realpath(p)
        except (OSError, ValueError):
            keep.append(p)
            continue
        if resolved in drop:
            continue
        keep.append(p)
    sys.path[:] = keep


_harden_sys_path()

import json  # noqa: E402 - deliberately after _harden_sys_path()
import os  # noqa: E402
import re  # noqa: E402
import importlib.machinery
import importlib.util


class _SourceOnlyLoader(importlib.machinery.SourceFileLoader):
    def get_code(self, fullname):
        path = self.get_filename(fullname)
        return self.source_to_code(self.get_data(path), path)


_PACKAGE = "cv_validate"
_PACKAGE_MODULES = (
    "yamlload", "globs", "rules", "fastpath_support", "fastpath", "triage", "blocks",
    "core")


def _load_package():
    pkg_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), _PACKAGE)
    for name in [n for n in sys.modules if n == _PACKAGE or n.startswith(_PACKAGE + ".")]:
        del sys.modules[name]
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        pkg = None
        for sub in ("__init__",) + _PACKAGE_MODULES:
            is_pkg = sub == "__init__"
            name = _PACKAGE if is_pkg else _PACKAGE + "." + sub
            path = os.path.join(pkg_dir, sub + ".py")
            spec = importlib.util.spec_from_file_location(
                name, path, loader=_SourceOnlyLoader(name, path),
                submodule_search_locations=[pkg_dir] if is_pkg else None)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
            if is_pkg:
                pkg = mod
            else:
                setattr(pkg, sub, mod)
    finally:
        sys.dont_write_bytecode = saved


_load_package()

from cv_validate.yamlload import (
    ManifestParseError, load_yaml, _strip_comment, _scalar, _inline_list, _split_commas,
    _open_quote, _value_part, _is_continuation, _BLOCK_SCALAR_RE, _fold_plain_scalars,
    _TOP_LEVEL_JOBS_RE, _assert_jobs_survived, _mini_yaml, _looks_scalar, _colon_index)
from cv_validate.globs import (
    glob_to_regex, glob_match, witness, _seg_is_literal, _literal_prefix,
    _literal_suffix, _seg_disjoint, _provably_disjoint, globs_overlap)
from cv_validate.rules import (
    REVIEWER_TOKENS, VALID_TIERS, VALID_EFFORTS, VALID_BACKENDS, VALID_ISOLATIONS,
    VALID_RUNS, VALID_STANCES, TIMEOUT_SEC_MIN, TIMEOUT_SEC_MAX, VALID_TRIAGE_TIERS,
    TRIAGE_REQUIRED_KEYS, VALID_TRIAGE_FLAVORS, TRIAGE_OPTIONAL_KEYS,
    TRIAGE_ALLOWED_KEYS, TRIAGE_DISABLED_FLAG, PRE_EVAL_DIR_REL, DEFAULT_TAXONOMY_REL,
    VALID_TEST_SCOPES, DEFAULT_TEST_SCOPE, TEST_CONTRACT_ALLOWED_KEYS,
    IMPACTED_MAP_REQUIRED_KEYS, RETRY_ALLOWED_KEYS, INTERFACES_ALLOWED_KEYS,
    TOPLEVEL_REQUIRED, JOB_REQUIRED, _ID_RE, _id_is_safe, _is_reviewer)
from cv_validate.fastpath_support import (
    FASTPATH_MODES, _EXEC_DIR, _RECEIPT_SUBPATH, _RECEIPT_SCHEMA, _CROSS_MODEL_SCHEMA,
    _PLAN_REVIEW_SCHEMA, _CROSS_MODEL_EXPECTED, _MAX_DIFF_BYTES, _GIT_DIFF_TIMEOUT_S,
    _GIT_PROBE_TIMEOUT_S, _GIT_UNAVAILABLE, _SIBLING_CACHE, _load_sibling, _sibling,
    _read_json_file, _is_claude_opus, _DIGEST_RE, _is_digest_shaped, _is_git_tracked,
    _git_via_supervisor, _is_committed_at_head, _containment_problems,
    _review_resolution, _load_bundled_schema, _load_receipt_schema, _json_type_ok,
    _schema_lite_value, _schema_lite, _read_run_baseline, _recompute_diff_digest,
    _sealed_receipt_problems, verify_sealed_receipt)
from cv_validate.fastpath import _validate_receipt, _validate_fast_path
from cv_validate.triage import (
    _iso8601_ok, _validate_triage, _DECISION_TO_TIER, _triage_record_problems,
    _is_deep_claude_review_job, _validate_triage_flavor, _null_digest_message,
    _triage_disabled_problems, _triage_digest_problems, _validate_cross_model_receipt)
from cv_validate.blocks import (
    _validate_test_contract, _validate_retry, _validate_provision,
    _string_list_problems, _CATCH_ALL_TOOLCHAIN_GLOBS, _validate_toolchain_artifacts,
    _validate_global_constraints, _validate_interfaces)
from cv_validate.core import validate, validate_text
from cv_validate import fastpath_support as _fastpath_support


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

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
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


def _find_repo_root(start):
    """Walk up from ``start`` to the nearest dir containing ``.git`` (a dir OR a
    worktree ``.git`` file); fall back to the CWD when none is found."""
    d = os.path.abspath(start)
    while True:
        if os.path.exists(os.path.join(d, ".git")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return os.getcwd()
        d = parent


def _get_opt(args, name):
    """Pop ``--name VALUE`` from a mutable args list; return VALUE or None."""
    if name in args:
        i = args.index(name)
        if i + 1 < len(args):
            val = args[i + 1]
            del args[i:i + 2]
            return val
        del args[i:i + 1]
    return None


def main(argv):
    args = list(argv[1:])
    if "--selftest" in args:
        return _selftest()
    # v3.0 (Feature A2): a BOOLEAN flag, default OFF in every mode. /v:dispatch
    # passes it on every live dispatch; the CI historical sweep does not.
    require_triage = "--require-triage" in args
    while "--require-triage" in args:
        args.remove("--require-triage")
    mode = _get_opt(args, "--mode")
    repo_root = _get_opt(args, "--repo-root")
    config_path = _get_opt(args, "--config")
    receipt_path = _get_opt(args, "--receipt")
    # Where triage.taxonomy_digest is checked against; absent ⇒
    # <repo-root>/.claude/compound-v-impact-taxonomy.yaml.
    taxonomy_path = _get_opt(args, "--taxonomy")
    # v3.4.1: the SCOPED+ cross-model receipt (/v:dispatch step 8 passes it for a
    # `triage.flavor: scoped_plus` run, and only after the review has run).
    # `--expected-diff-digest` is optional and re-asserts the sealed patch bytes the
    # caller handed the reviewer against the digest the receipt claims.
    cross_model_receipt = _get_opt(args, "--require-cross-model-receipt")
    expected_diff_digest = _get_opt(args, "--expected-diff-digest")
    # CRIT-1: the worker's linked worktree — the checkout the producer hashed the
    # final diff in. The post-review recompute runs there; absent ⇒ repo_root.
    diff_root = _get_opt(args, "--worktree")
    # HIGH-1(b): the CURRENT review attempt (the caller reads it from the run's
    # state.json). When supplied, the post-review receipt's attempt_id MUST equal it —
    # a stale prior-attempt receipt cannot be replayed against a newer attempt.
    expected_attempt = _get_opt(args, "--expected-attempt")
    if expected_attempt is not None:
        try:
            expected_attempt = int(expected_attempt)
        except (TypeError, ValueError):
            print("error: --expected-attempt must be an integer", file=sys.stderr)
            return 2
    # Drop any remaining flags; the first non-flag token is the manifest path.
    positional = [a for a in args if not a.startswith("--")]
    if not positional:
        print("usage: compound-v-validate-manifest.py [--mode pre-dispatch|"
              "post-review] [--repo-root DIR] [--worktree DIR] [--config FILE] "
              "[--receipt FILE] [--expected-attempt N] [--require-triage] "
              "[--taxonomy FILE] [--require-cross-model-receipt FILE] "
              "[--expected-diff-digest sha256:...] <manifest.yaml>",
              file=sys.stderr)
        return 2
    if mode is not None and mode not in FASTPATH_MODES:
        print("error: --mode '%s' invalid (expected one of %s)"
              % (mode, ", ".join(FASTPATH_MODES)), file=sys.stderr)
        return 2
    path = positional[0]
    if not os.path.isfile(path):
        print("error: not a file: %s" % path, file=sys.stderr)
        return 2
    if repo_root is None:
        repo_root = _find_repo_root(os.path.dirname(os.path.abspath(path)))
    # Read the RAW bytes so the manifest_digest binding (CR5-6) content-addresses
    # to exactly what the producer digested; decode for YAML parsing separately.
    with open(path, "rb") as fh:
        raw = fh.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        print(json.dumps({"verdict": "error", "error": "manifest is not UTF-8 "
                          "(%s)" % e}), file=sys.stderr)
        return 2
    try:
        problems = validate_text(text, mode=mode, repo_root=repo_root,
                                 config_path=config_path,
                                 receipt_path=receipt_path,
                                 manifest_bytes=raw, diff_root=diff_root,
                                 expected_attempt=expected_attempt,
                                 require_triage=require_triage,
                                 taxonomy_path=taxonomy_path,
                                 cross_model_receipt=cross_model_receipt,
                                 expected_diff_digest=expected_diff_digest)
    except Exception as e:  # noqa: BLE001 - report parse failure cleanly
        print(json.dumps({"verdict": "error", "error": str(e)}), file=sys.stderr)
        return 2

    # ADVISORY channel (v3.5.0). Computed on BOTH paths and printed on both, so a
    # reader never has to make a manifest valid before they can see the advice. It
    # cannot change `problems`, the verdict, or the exit code — that separation is
    # the whole contract, and `agents/partition-reviewer.md` restates it.
    warnings = advisories_text(text)
    # The cross-model receipt is a separate file the manifest text alone can't see;
    # read it independently, same fail-soft rule as everything in this channel — an
    # unreadable/absent receipt contributes no advisory (the hard checks above
    # already fail-closed on that; this channel never duplicates a violation).
    if cross_model_receipt not in (None, ""):
        try:
            with open(cross_model_receipt, "r", encoding="utf-8") as _cm_fh:
                _cm_receipt = json.load(_cm_fh)
        except Exception:  # noqa: BLE001 - advisory channel is fail-soft
            _cm_receipt = None
        warnings.extend(cross_model_receipt_advisories(_cm_receipt))
    for w in warnings:
        print("ADVISORY: %s" % w, file=sys.stderr)

    if problems:
        print("MANIFEST INVALID: %d violation(s)" % len(problems), file=sys.stderr)
        for p in problems:
            print("  - %s" % p, file=sys.stderr)
        print(json.dumps({"verdict": "invalid", "violations": problems,
                          "warnings": warnings}, indent=2))
        return 1
    print(json.dumps({"verdict": "valid", "violations": [],
                      "warnings": warnings}, indent=2))
    return 0


# --------------------------------------------------------------------------- #
# Self-test.
# --------------------------------------------------------------------------- #
GOOD_MANIFEST = """
run_id: 2026-06-26-demo
feature: "demo"
spec_path: docs/superpowers/specs/2026-06-26-demo.md
plan_path: docs/superpowers/plans/2026-06-26-demo.md
audits:
  archaeology: docs/superpowers/archaeology/2026-06-26-demo.md
  domain: docs/superpowers/expert/2026-06-26-demo.md
  library: docs/superpowers/library-audit/2026-06-26-demo.md
routing_stance: balanced
max_parallel: 4
shared_resources:
  - src/types/shared.ts
acceptance_criteria:
  - "ships"
jobs:
  - id: task-0-foundation
    title: "shared foundation"
    type: shared_foundation
    backend: claude
    model: opus
    isolation: direct
    run: serial
    write_allowed: [src/types/shared.ts, src/db/schema.ts]
    read_allowed: [src/db/**]
    acceptance: ["types exported"]
  - id: task-1-editor
    title: "editor slice"
    type: large_isolated
    backend: codex
    model: gpt-5.5
    isolation: worktree
    run: parallel
    depends_on: [task-0-foundation]
    write_allowed: [src/features/editor/**]
    read_allowed: [src/features/editor/**]
    acceptance: ["create/edit"]
  - id: task-2-api
    title: "api slice"
    type: bounded_crud
    backend: claude
    tier: standard
    effort: medium
    isolation: worktree
    run: parallel
    write_allowed: [src/features/api/**]
    read_allowed: [src/server/**]
    acceptance: ["crud"]
  - id: task-3-spec-review
    title: "spec review gate"
    type: review
    backend: claude
    tier: deep
    effort: high
    isolation: direct
    run: serial
    write_allowed: []
    read_allowed: [src/**]
    acceptance: ["AC met"]
"""

# The shape `yaml.safe_dump(..., width=100)` actually emits, and the shape the
# subset parser could not read until the fifth review pass: a folded plain
# scalar (`feature`), a folded list item (`acceptance_criteria`), and block
# sequences sitting at their parent key's OWN indent (`jobs`, `write_allowed`).
# Kept as literal bytes so the fixture is evidence rather than a re-derivation;
# `_selftest` re-dumps it through PyYAML and asserts it is byte-identical.
FOLDED_FEATURE = ("Close the fifth review pass: a lane guard that actually "
                  "enforces, a register-lane the clamp accepts, and honest "
                  "acceptance greps")
FOLDED_CRITERION = (r"grep -rnE '^PIPELINE_BOOKKEEPING\s*=' scripts hooks "
                    "returns nothing, and the split literals are gone from "
                    "both files")
FOLDED_MANIFEST = r"""run_id: 2026-09-02-folded
feature: 'Close the fifth review pass: a lane guard that actually enforces, a register-lane the clamp
  accepts, and honest acceptance greps'
acceptance_criteria:
- grep -rnE '^PIPELINE_BOOKKEEPING\s*=' scripts hooks returns nothing, and the split literals are gone
  from both files
jobs:
- id: guard-honest
  type: core_slice
  backend: claude
  tier: deep
  write_allowed:
  - hooks/lane-guard.sh
  - tests/test-lane-guard.sh
  read_allowed:
  - '**'
"""

# Deliberately broken: codex w/o worktree, reviewer w/ sonnet, overlapping
# write globs, non-serial shared_foundation, unowned shared resource.
BAD_MANIFEST = """
run_id: 2026-06-26-bad
shared_resources:
  - src/types/orphan.ts
jobs:
  - id: task-0-foundation
    type: shared_foundation
    backend: claude
    model: opus
    isolation: direct
    run: parallel
    write_allowed: [src/db/schema.ts]
  - id: task-1-codex
    type: large_isolated
    backend: codex
    model: gpt-5.5
    isolation: direct
    run: parallel
    write_allowed: [src/features/**]
  - id: task-2-overlap
    type: bounded_crud
    backend: claude
    model: sonnet
    isolation: direct
    run: parallel
    write_allowed: [src/features/api/**]
  - id: task-3-review
    type: integration_review
    backend: claude
    model: sonnet
    isolation: direct
    run: serial
    write_allowed: []
  - id: task-4-no-routing
    type: docs
    backend: claude
    isolation: direct
    run: parallel
    write_allowed: [docs/orphan-area.md]
  - id: task-5-bad-vocab
    type: docs
    backend: claude
    tier: turbo
    effort: extreme
    isolation: direct
    run: parallel
    write_allowed: [docs/another-area.md]
"""


# A complete, otherwise-valid manifest whose ONE defect is parallel + direct.
PARALLEL_DIRECT_MANIFEST = """
run_id: 2026-06-26-pd
feature: "pd"
spec_path: docs/superpowers/specs/2026-06-26-pd.md
plan_path: docs/superpowers/plans/2026-06-26-pd.md
audits:
  archaeology: docs/superpowers/archaeology/2026-06-26-pd.md
  domain: docs/superpowers/expert/2026-06-26-pd.md
  library: docs/superpowers/library-audit/2026-06-26-pd.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-build
    title: "build slice"
    type: bounded_crud
    backend: claude
    tier: standard
    isolation: direct
    run: parallel
    write_allowed: [src/build/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""

# A complete manifest whose ONE defect is a path-traversal job id.
BAD_ID_MANIFEST = """
run_id: 2026-06-26-badid
feature: "badid"
spec_path: docs/superpowers/specs/2026-06-26-badid.md
plan_path: docs/superpowers/plans/2026-06-26-badid.md
audits:
  archaeology: docs/superpowers/archaeology/2026-06-26-badid.md
  domain: docs/superpowers/expert/2026-06-26-badid.md
  library: docs/superpowers/library-audit/2026-06-26-badid.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: ../x
    title: "evil"
    type: bounded_crud
    backend: claude
    tier: standard
    isolation: worktree
    run: parallel
    write_allowed: [src/evil/**]
    read_allowed: [src/**]
    acceptance: ["x"]
"""


# A complete, otherwise-valid manifest whose ONE defect is a model: haiku
# execution-layer override (must be rejected by the never-Haiku policy).
HAIKU_MODEL_MANIFEST = """
run_id: 2026-06-26-haiku
feature: "haiku"
spec_path: docs/superpowers/specs/2026-06-26-haiku.md
plan_path: docs/superpowers/plans/2026-06-26-haiku.md
audits:
  archaeology: docs/superpowers/archaeology/2026-06-26-haiku.md
  domain: docs/superpowers/expert/2026-06-26-haiku.md
  library: docs/superpowers/library-audit/2026-06-26-haiku.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-cheap
    title: "cheap slice"
    type: docs
    backend: claude
    model: claude-haiku-4
    isolation: worktree
    run: parallel
    write_allowed: [docs/cheap.md]
    read_allowed: [src/**]
    acceptance: ["x"]
"""

# A complete manifest whose ONE defect is a dangling depends_on reference.
DANGLING_DEP_MANIFEST = """
run_id: 2026-06-26-dangling
feature: "dangling"
spec_path: docs/superpowers/specs/2026-06-26-dangling.md
plan_path: docs/superpowers/plans/2026-06-26-dangling.md
audits:
  archaeology: docs/superpowers/archaeology/2026-06-26-dangling.md
  domain: docs/superpowers/expert/2026-06-26-dangling.md
  library: docs/superpowers/library-audit/2026-06-26-dangling.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-build
    title: "build slice"
    type: bounded_crud
    backend: claude
    tier: standard
    isolation: worktree
    run: parallel
    depends_on: [task-0-missing]
    write_allowed: [src/build/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""

# A complete manifest whose ONE defect is a depends_on cycle (A→B→A).
CYCLE_DEP_MANIFEST = """
run_id: 2026-06-26-cycle
feature: "cycle"
spec_path: docs/superpowers/specs/2026-06-26-cycle.md
plan_path: docs/superpowers/plans/2026-06-26-cycle.md
audits:
  archaeology: docs/superpowers/archaeology/2026-06-26-cycle.md
  domain: docs/superpowers/expert/2026-06-26-cycle.md
  library: docs/superpowers/library-audit/2026-06-26-cycle.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-a
    title: "a"
    type: bounded_crud
    backend: claude
    tier: standard
    isolation: worktree
    run: parallel
    depends_on: [task-b]
    write_allowed: [src/a/**]
    read_allowed: [src/**]
    acceptance: ["a"]
  - id: task-b
    title: "b"
    type: bounded_crud
    backend: claude
    tier: standard
    isolation: worktree
    run: parallel
    depends_on: [task-a]
    write_allowed: [src/b/**]
    read_allowed: [src/**]
    acceptance: ["b"]
"""

# A complete manifest whose ONE defect is a wrong-typed required field
# (acceptance_criteria provided as a scalar string instead of a list).
WRONG_TYPE_MANIFEST = """
run_id: 2026-06-26-wrongtype
feature: "wrongtype"
spec_path: docs/superpowers/specs/2026-06-26-wrongtype.md
plan_path: docs/superpowers/plans/2026-06-26-wrongtype.md
audits:
  archaeology: docs/superpowers/archaeology/2026-06-26-wrongtype.md
  domain: docs/superpowers/expert/2026-06-26-wrongtype.md
  library: docs/superpowers/library-audit/2026-06-26-wrongtype.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria: "ships"
jobs:
  - id: task-1-build
    title: "build slice"
    type: bounded_crud
    backend: claude
    tier: standard
    isolation: worktree
    run: parallel
    write_allowed: [src/build/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""


# A complete, fully-VALID manifest: a codex job with effort: xhigh (xhigh is
# valid iff backend: codex — this is the accept direction of that rule).
XHIGH_CODEX_MANIFEST = """
run_id: 2026-07-11-xhigh-ok
feature: "xhigh-ok"
spec_path: docs/superpowers/specs/2026-07-11-xhigh-ok.md
plan_path: docs/superpowers/plans/2026-07-11-xhigh-ok.md
audits:
  archaeology: docs/superpowers/archaeology/2026-07-11-xhigh-ok.md
  domain: docs/superpowers/expert/2026-07-11-xhigh-ok.md
  library: docs/superpowers/library-audit/2026-07-11-xhigh-ok.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-codex-xhigh
    title: "codex xhigh slice"
    type: large_isolated
    backend: codex
    tier: deep
    effort: xhigh
    isolation: worktree
    run: parallel
    write_allowed: [src/features/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""

# A complete manifest whose ONE defect is effort: xhigh on a NON-codex backend
# (the reject direction: xhigh is codex-only).
XHIGH_CLAUDE_MANIFEST = """
run_id: 2026-07-11-xhigh-bad
feature: "xhigh-bad"
spec_path: docs/superpowers/specs/2026-07-11-xhigh-bad.md
plan_path: docs/superpowers/plans/2026-07-11-xhigh-bad.md
audits:
  archaeology: docs/superpowers/archaeology/2026-07-11-xhigh-bad.md
  domain: docs/superpowers/expert/2026-07-11-xhigh-bad.md
  library: docs/superpowers/library-audit/2026-07-11-xhigh-bad.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-claude-xhigh
    title: "claude xhigh slice"
    type: core_slice
    backend: claude
    tier: deep
    effort: xhigh
    isolation: worktree
    run: parallel
    write_allowed: [src/features/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""

def _timeout_manifest(timeout_line):
    """A complete, otherwise-valid single-codex-job manifest whose ONLY variable is
    the optional `timeout_sec` line. Pass "" to omit the field entirely (the ABSENT
    case, which must stay valid — that is what every already-committed manifest
    looks like)."""
    return """
run_id: 2026-07-26-timeout
feature: "timeout"
spec_path: docs/superpowers/specs/2026-07-26-timeout.md
plan_path: docs/superpowers/plans/2026-07-26-timeout.md
audits:
  archaeology: docs/superpowers/archaeology/2026-07-26-timeout.md
  domain: docs/superpowers/expert/2026-07-26-timeout.md
  library: docs/superpowers/library-audit/2026-07-26-timeout.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-timeout
    title: "timeout slice"
    type: large_isolated
    backend: codex
    tier: deep
    effort: high
    isolation: worktree
    run: parallel
%s    write_allowed: [src/features/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
""" % (("    timeout_sec: %s\n" % timeout_line) if timeout_line != "" else "")


def _v3_manifest(triage_block="", contract_block="", job_line="", retry_block="",
                 constraints_block=""):
    """A complete, otherwise-valid single-job manifest whose ONLY variables are the
    v3.0 additions: the top-level ``triage`` block (Feature A2), the top-level
    ``test_contract`` block (Feature B2), one extra per-job line (``test_scope``),
    the v3.4.8 top-level ``retry`` block (Task B), and the v3.4.17 top-level
    ``global_constraints`` list (``job_line`` also carries the per-job
    ``interfaces`` mapping, which is several lines rather than one).

    Pass "" to omit a block entirely — the ABSENT case, which is what every manifest
    committed before 3.0 looks like and which MUST stay valid when ``--require-triage``
    is not passed (that is what keeps the CI historical sweep and 3.0's own bootstrap
    manifest green)."""
    return """
run_id: 2026-09-01-v3
feature: "v3 contract"
spec_path: docs/superpowers/specs/2026-09-01-v3.md
plan_path: docs/superpowers/plans/2026-09-01-v3.md
audits:
  archaeology: docs/superpowers/archaeology/2026-09-01-v3.md
  domain: docs/superpowers/expert/2026-09-01-v3.md
  library: docs/superpowers/library-audit/2026-09-01-v3.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
%s%s%s%sjobs:
  - id: task-1-v3
    title: "v3 slice"
    type: bounded_crud
    backend: claude
    tier: standard
    effort: medium
    isolation: worktree
    run: parallel
%s    write_allowed: [src/features/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
""" % (triage_block, contract_block, retry_block, constraints_block, job_line)


# A well-formed `triage` block (Feature A2). `digest` is substituted so a test can
# plant a mismatch against the taxonomy bytes on disk.
def _triage_block(digest, tier="SCOPED", pre_eval_id="2026-09-01T101500Z-v3-a1b2",
                  decided_at="2026-09-01T10:15:00Z", drop=None, extra=""):
    lines = {
        "tier": "  tier: %s" % tier,
        "pre_eval_id": "  pre_eval_id: %s" % pre_eval_id,
        "taxonomy_digest": '  taxonomy_digest: "%s"' % digest,
        "decided_at": '  decided_at: "%s"' % decided_at,
    }
    if drop:
        lines.pop(drop, None)
    body = "\n".join(lines.values())
    return "triage:\n%s\n%s" % (body, extra)

# A complete, otherwise-valid manifest whose ONE defect is an antigravity job with
# isolation: direct (an external no-kernel-sandbox worker MUST be worktree-isolated).
# Uses run: serial so the ONLY violation is the antigravity⇒worktree invariant (not
# the parallel⇒worktree one).
ANTIGRAVITY_DIRECT_MANIFEST = """
run_id: 2026-06-27-agy
feature: "agy"
spec_path: docs/superpowers/specs/2026-06-27-agy.md
plan_path: docs/superpowers/plans/2026-06-27-agy.md
audits:
  archaeology: docs/superpowers/archaeology/2026-06-27-agy.md
  domain: docs/superpowers/expert/2026-06-27-agy.md
  library: docs/superpowers/library-audit/2026-06-27-agy.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-agy
    title: "antigravity slice"
    type: large_isolated
    backend: antigravity
    tier: standard
    isolation: direct
    run: serial
    write_allowed: [src/agy/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""


# A complete, otherwise-valid manifest whose ONE defect is an opencode job with
# isolation: direct (opencode has NO kernel write-confinement and defaults to
# allowing all operations, so worktree isolation is REQUIRED).
OPENCODE_DIRECT_MANIFEST = """
run_id: 2026-07-13-opencode
feature: "opencode"
spec_path: docs/superpowers/specs/2026-07-13-opencode.md
plan_path: docs/superpowers/plans/2026-07-13-opencode.md
audits:
  archaeology: docs/superpowers/archaeology/2026-07-13-opencode.md
  domain: docs/superpowers/expert/2026-07-13-opencode.md
  library: docs/superpowers/library-audit/2026-07-13-opencode.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-opencode
    title: "opencode slice"
    type: large_isolated
    backend: opencode
    tier: standard
    isolation: direct
    run: serial
    write_allowed: [src/opencode/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""


# A complete, VALID manifest with a single opencode job, worktree-isolated -- confirms
# "opencode" is accepted end-to-end (VALID_BACKENDS + the worktree invariant) once it
# is NOT paired with isolation: direct. model is a genuine "provider/model" string,
# matching the resolver's opencode convention.
OPENCODE_WORKTREE_MANIFEST = """
run_id: 2026-07-13-opencode-ok
feature: "opencode-ok"
spec_path: docs/superpowers/specs/2026-07-13-opencode-ok.md
plan_path: docs/superpowers/plans/2026-07-13-opencode-ok.md
audits:
  archaeology: docs/superpowers/archaeology/2026-07-13-opencode-ok.md
  domain: docs/superpowers/expert/2026-07-13-opencode-ok.md
  library: docs/superpowers/library-audit/2026-07-13-opencode-ok.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-opencode-ok
    title: "opencode slice"
    type: large_isolated
    backend: opencode
    model: "anthropic/claude-sonnet-4-6"
    isolation: worktree
    run: serial
    write_allowed: [src/opencode/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""


# A complete, otherwise-valid manifest whose ONE defect is a REVIEWER job routed to
# backend: opencode. opencode is a lower-trust, opt-in, WORKER-ONLY backend (see
# adapter-opencode.md) -- a reviewer job must never resolve its Review-Gate opus/deep
# guarantee through a low-trust external router. tier: deep + isolation: worktree are
# otherwise satisfied, so ONLY the WORKER-ONLY violation fires.
OPENCODE_REVIEWER_MANIFEST = """
run_id: 2026-07-13-opencode-reviewer
feature: "opencode-reviewer"
spec_path: docs/superpowers/specs/2026-07-13-opencode-reviewer.md
plan_path: docs/superpowers/plans/2026-07-13-opencode-reviewer.md
audits:
  archaeology: docs/superpowers/archaeology/2026-07-13-opencode-reviewer.md
  domain: docs/superpowers/expert/2026-07-13-opencode-reviewer.md
  library: docs/superpowers/library-audit/2026-07-13-opencode-reviewer.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-quality-review
    title: "quality review pass"
    type: quality_review
    backend: opencode
    tier: deep
    isolation: worktree
    run: serial
    write_allowed: []
    read_allowed: [src/**]
    acceptance: ["reviewed"]
"""


# A complete, otherwise-valid manifest whose ONE defect is an opencode job with a BARE
# (slash-less) explicit model override. opencode addresses models as a "provider/model"
# string with no single-vendor default (see adapter-opencode.md); a bare name would
# silently pass a naive validator but fail opencode's own model resolution / the
# worker's `-m` argument at run time, so it must be rejected here, before dispatch.
OPENCODE_BARE_MODEL_MANIFEST = """
run_id: 2026-07-13-opencode-bare-model
feature: "opencode-bare-model"
spec_path: docs/superpowers/specs/2026-07-13-opencode-bare-model.md
plan_path: docs/superpowers/plans/2026-07-13-opencode-bare-model.md
audits:
  archaeology: docs/superpowers/archaeology/2026-07-13-opencode-bare-model.md
  domain: docs/superpowers/expert/2026-07-13-opencode-bare-model.md
  library: docs/superpowers/library-audit/2026-07-13-opencode-bare-model.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-opencode-bare
    title: "opencode slice"
    type: large_isolated
    backend: opencode
    model: "gpt-6"
    isolation: worktree
    run: serial
    write_allowed: [src/opencode/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""


# Same defect, malformed shape variant: a trailing slash with an EMPTY model half
# ("anthropic/") — the '/' is present but one side is empty, still not a valid
# provider/model pair.
OPENCODE_MALFORMED_MODEL_MANIFEST = """
run_id: 2026-07-13-opencode-malformed-model
feature: "opencode-malformed-model"
spec_path: docs/superpowers/specs/2026-07-13-opencode-malformed-model.md
plan_path: docs/superpowers/plans/2026-07-13-opencode-malformed-model.md
audits:
  archaeology: docs/superpowers/archaeology/2026-07-13-opencode-malformed-model.md
  domain: docs/superpowers/expert/2026-07-13-opencode-malformed-model.md
  library: docs/superpowers/library-audit/2026-07-13-opencode-malformed-model.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-opencode-malformed
    title: "opencode slice"
    type: large_isolated
    backend: opencode
    model: "anthropic/"
    isolation: worktree
    run: serial
    write_allowed: [src/opencode/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""


# A family of opencode jobs whose explicit `model` is a NON-STRING (int / inline list
# / inline mapping). A non-string can never be a valid 'provider/model' string, and the
# shape check must NOT skip it (an earlier version only ran the check for str models, so
# a `model: 42` slipped through with zero violations). Each carries `tier: standard` so
# the model override is present-but-invalid without also tripping the model-or-tier
# requirement — isolating the shape violation as the guaranteed one.
OPENCODE_INT_MODEL_MANIFEST = """
run_id: 2026-07-13-opencode-int-model
feature: "opencode-int-model"
spec_path: docs/superpowers/specs/2026-07-13-opencode-int-model.md
plan_path: docs/superpowers/plans/2026-07-13-opencode-int-model.md
audits:
  archaeology: docs/superpowers/archaeology/2026-07-13-opencode-int-model.md
  domain: docs/superpowers/expert/2026-07-13-opencode-int-model.md
  library: docs/superpowers/library-audit/2026-07-13-opencode-int-model.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-opencode-int
    title: "opencode slice"
    type: large_isolated
    backend: opencode
    model: 42
    tier: standard
    isolation: worktree
    run: serial
    write_allowed: [src/opencode/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""


OPENCODE_LIST_MODEL_MANIFEST = """
run_id: 2026-07-13-opencode-list-model
feature: "opencode-list-model"
spec_path: docs/superpowers/specs/2026-07-13-opencode-list-model.md
plan_path: docs/superpowers/plans/2026-07-13-opencode-list-model.md
audits:
  archaeology: docs/superpowers/archaeology/2026-07-13-opencode-list-model.md
  domain: docs/superpowers/expert/2026-07-13-opencode-list-model.md
  library: docs/superpowers/library-audit/2026-07-13-opencode-list-model.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-opencode-list
    title: "opencode slice"
    type: large_isolated
    backend: opencode
    model: ["anthropic/claude-opus-4-6"]
    tier: standard
    isolation: worktree
    run: serial
    write_allowed: [src/opencode/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""


OPENCODE_DICT_MODEL_MANIFEST = """
run_id: 2026-07-13-opencode-dict-model
feature: "opencode-dict-model"
spec_path: docs/superpowers/specs/2026-07-13-opencode-dict-model.md
plan_path: docs/superpowers/plans/2026-07-13-opencode-dict-model.md
audits:
  archaeology: docs/superpowers/archaeology/2026-07-13-opencode-dict-model.md
  domain: docs/superpowers/expert/2026-07-13-opencode-dict-model.md
  library: docs/superpowers/library-audit/2026-07-13-opencode-dict-model.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-opencode-dict
    title: "opencode slice"
    type: large_isolated
    backend: opencode
    model: {}
    tier: standard
    isolation: worktree
    run: serial
    write_allowed: [src/opencode/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""


# --------------------------------------------------------------------------- #
# v2.9 fast-path self-test — builds on-disk fixtures in a temp repo root so the
# containment + cross-artifact-binding checks exercise real files. Digests are
# computed via the SHARED compound-v-taxonomy primitives (record_digest /
# taxonomy_digest_bytes) so a producer (M1) and this consumer can never diverge.
# --------------------------------------------------------------------------- #
def _fp_taxonomy_bytes():
    """The example taxonomy shipped with the plugin (a valid snapshot to test
    classification against)."""
    here = os.path.dirname(os.path.abspath(__file__))
    example = os.path.join(os.path.dirname(here),
                           ".claude", "compound-v-impact-taxonomy.example.yaml")
    with open(example, "rb") as fh:
        return fh.read()


def _fp_write(root, rel, data):
    full = os.path.join(root, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    mode = "wb" if isinstance(data, bytes) else "w"
    kw = {} if isinstance(data, bytes) else {"encoding": "utf-8"}
    with open(full, mode, **kw) as fh:
        fh.write(data)
    return full


def _fp_build(root, tax_mod, **opts):
    """Materialize a fast-path fixture under ``root``; return the manifest text.

    Knobs (all default to the VALID shape): write_path, resolved_path,
    record_decision, manifest_tax_digest, record_tax_digest, artifact_fan_out,
    manifest_pre_eval_id, review (dict), audits_flow, second_job, glob_write,
    symlink_write, loc_ref, tax_ref, pre_ref, make_receipt (dict|None),
    receipt_rel, artifact_drop_digest (MED-8), artifact_bad_shape_digest (MED-8).
    """
    pre_eval_id = "2026-07-12T101500Z-make-button-red-a1b2"
    run_id = pre_eval_id
    write_path = opts.get("write_path", "src/components/button.css")
    resolved_path = opts.get("resolved_path", write_path)

    pre_ref = opts.get("pre_ref",
                       "docs/superpowers/pre-eval/%s.json" % pre_eval_id)
    loc_ref = opts.get("loc_ref",
                       "docs/superpowers/pre-eval/%s.localization.json" % pre_eval_id)
    tax_ref = opts.get(
        "tax_ref",
        "docs/superpowers/execution/%s/taxonomy-snapshot.yaml" % run_id)

    # Immutable taxonomy snapshot + its content-address digest (RAW bytes).
    tax_bytes = _fp_taxonomy_bytes()
    _fp_write(root, tax_ref, tax_bytes)
    real_tax_digest = tax_mod.taxonomy_digest_bytes(tax_bytes)
    manifest_tax_digest = opts.get("manifest_tax_digest", real_tax_digest)
    record_tax_digest = opts.get("record_tax_digest", real_tax_digest)

    # Localization object (embedded in the record) + standalone artifact w/ digest.
    localization = {
        "resolved_paths": [resolved_path],
        "fan_out": 1,
        "flags": [],
        "confidence": "exact",
    }
    artifact = dict(localization)
    artifact["fan_out"] = opts.get("artifact_fan_out", 1)
    artifact["digest"] = tax_mod.record_digest(artifact)
    if opts.get("artifact_drop_digest"):
        artifact.pop("digest", None)              # MED-8: absent content-digest
    elif opts.get("artifact_bad_shape_digest"):
        artifact["digest"] = "not-a-valid-digest"  # MED-8: wrong-shape digest
    _fp_write(root, loc_ref, json.dumps(artifact))

    record = {
        "pre_eval_id": pre_eval_id,
        "request_slug": "make-button-red",
        "ts": "2026-07-12T10:15:00Z",
        "status": "PRE_EVAL_DONE",
        "taxonomy_version": 1,
        "taxonomy_ref": tax_ref,
        "taxonomy_digest": record_tax_digest,
        "difficulty": {"band": opts.get("record_difficulty_band", "low")},
        "impact": {"band": opts.get("record_impact_band", "low")},
        "tiers_signalled": ["localization"],
        "localization": localization,
        "override_fired": opts.get("record_override_fired", None),
        "decision": opts.get("record_decision", "FASTPATH_ELIGIBLE"),
        "min_sample_status": "insufficient",
    }
    # A genuine record carries its own canonical-JSON self-digest (the producer
    # sets it via record_digest); a fast-path consumer verifies it (CR5-6/CR5-7).
    record["digest"] = tax_mod.record_digest(record, exclude_field="digest")
    if opts.get("record_bad_digest"):
        record["digest"] = "sha256:" + ("0" * 64)  # tamper: valid shape, wrong value
    elif opts.get("record_drop_digest"):
        record.pop("digest", None)
    _fp_write(root, pre_ref, json.dumps(record))

    # The write target: a real committed-looking regular file (or an escaping
    # symlink for the containment tamper case).
    if opts.get("symlink_write"):
        outside = os.path.join(root, "..", "outside-secret.css")
        with open(os.path.join(root, "outside-secret.css"), "w") as fh:
            fh.write("body{}\n")  # a sibling target the symlink escapes to
        link_full = os.path.join(root, write_path)
        os.makedirs(os.path.dirname(link_full), exist_ok=True)
        os.symlink(os.path.abspath(os.path.join(root, "outside-secret.css")),
                   link_full)
    elif not opts.get("skip_write_file"):
        _fp_write(root, write_path, "body{}\n")

    if opts.get("make_receipt") is not None:
        receipt_rel = opts.get(
            "receipt_rel",
            "docs/superpowers/execution/%s/review/receipt.json" % run_id)
        _fp_write(root, receipt_rel, json.dumps(opts["make_receipt"]))

    manifest_pre_eval_id = opts.get("manifest_pre_eval_id", pre_eval_id)
    review = opts.get("review", {"backend": "claude", "tier": "deep"})
    review_lines = "\n".join(
        "    %s: %s" % (k, v) for k, v in review.items())

    if opts.get("audits_flow"):
        audits_block = (
            "audits:\n"
            "  archaeology: {}\n"
            "  domain: {}\n"
            "  library: {}\n"
        )
    else:
        skip = ("    skipped: true\n"
                "    reason: fastpath\n"
                "    localization: %s\n"
                "    taxonomy_version: 1\n") % loc_ref
        audits_block = (
            "audits:\n"
            "  archaeology:\n" + skip +
            "  domain:\n" + skip +
            "  library:\n" + skip
        )

    write_glob = "src/**" if opts.get("glob_write") else write_path
    second = ""
    if opts.get("second_job"):
        second = (
            "  - id: task-2-extra\n"
            "    title: \"extra\"\n"
            "    type: docs\n"
            "    backend: claude\n"
            "    tier: standard\n"
            "    isolation: direct\n"
            "    run: serial\n"
            "    write_allowed: [docs/extra.md]\n"
            "    read_allowed: [src/**]\n"
            "    acceptance: [\"x\"]\n"
        )

    text = (
        "run_id: %s\n"
        "feature: \"make button red\"\n"
        "spec_path: docs/superpowers/execution/%s/spec-stub.md\n"
        "plan_path: docs/superpowers/execution/%s/plan-stub.md\n"
        "%s"
        "routing_stance: balanced\n"
        "max_parallel: 1\n"
        "acceptance_criteria:\n"
        "  - \"button is red\"\n"
        "fast_path:\n"
        "  eligible: true\n"
        "  pre_eval_id: %s\n"
        "  pre_eval_ref: %s\n"
        "  localization_ref: %s\n"
        "  taxonomy_ref: %s\n"
        "  taxonomy_digest: \"%s\"\n"
        "  review:\n"
        "%s\n"
        "jobs:\n"
        "  - id: task-1-button\n"
        "    title: \"make button red\"\n"
        "    type: bounded_crud\n"
        "    backend: claude\n"
        "    tier: standard\n"
        "    isolation: direct\n"
        "    run: serial\n"
        "    write_allowed: [%s]\n"
        "    read_allowed: [src/**]\n"
        "    acceptance: [\"button red\"]\n"
        "%s"
    ) % (run_id, run_id, run_id, audits_block, manifest_pre_eval_id, pre_ref,
         loc_ref, tax_ref, manifest_tax_digest, review_lines, write_glob, second)
    return text


def _fp_receipt(**over):
    r = {
        "run_id": "2026-07-12T101500Z-make-button-red-a1b2",
        "pre_eval_id": "2026-07-12T101500Z-make-button-red-a1b2",
        "manifest_digest": "sha256:" + ("a" * 64),
        "baseline_sha": "a" * 40,
        "final_diff_digest": "sha256:" + ("b" * 64),
        "reviewer_backend": "claude",
        "reviewer_model": "opus",
        "attempt_id": 1,
        "ts": "2026-07-12T10:20:00Z",
        "verdict": "approved",
        "integration_rationale": "single-job fast-path: no cross-job seams",
    }
    r.update(over)
    return r


_FP_RUN_ID = "2026-07-12T101500Z-make-button-red-a1b2"
_FP_JOB_ID = "task-1-button"
_FP_WRITE_PATH = "src/components/button.css"


def _fp_git_and_state(d, tax_mod, manifest_text):
    """Turn the fixture dir into a real git repo with a committed pre-launch
    baseline + one worker change, and write the run's state.json baseline — so
    the post-review receipt binding (manifest_digest / baseline_sha /
    final_diff_digest, CR5-6) can be recomputed against real git state. Returns
    the correct binding values (or None when git is unavailable)."""
    import subprocess

    def g(*a):
        return subprocess.run(["git", "-C", d] + list(a),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if g("init", "-q").returncode != 0:
        return None
    g("config", "user.email", "selftest@example.com")
    g("config", "user.name", "cv-selftest")
    g("config", "commit.gpgsign", "false")
    g("config", "core.hooksPath", "/dev/null")  # ignore any global hooks in CI
    g("add", "-A")
    if g("commit", "-q", "--no-verify", "-m", "baseline").returncode != 0:
        return None
    rp = g("rev-parse", "HEAD")
    if rp.returncode != 0:
        return None
    baseline = rp.stdout.decode("utf-8", "replace").strip()

    # One worker change to the sole write target → a non-empty tracked diff.
    with open(os.path.join(d, _FP_WRITE_PATH), "a", encoding="utf-8") as fh:
        fh.write("/* changed by worker */\n")
    diff = g("diff", "--no-color", baseline)
    if diff.returncode != 0:
        return None
    diff_bytes = diff.stdout or b""

    state = {"run_id": _FP_RUN_ID,
             "jobs": {_FP_JOB_ID: {"status": "success", "baseline": baseline}}}
    _fp_write(d, "docs/superpowers/execution/%s/state.json" % _FP_RUN_ID,
              json.dumps(state))
    return {
        "run_id": _FP_RUN_ID,
        "manifest_digest": tax_mod.taxonomy_digest_bytes(
            manifest_text.encode("utf-8")),
        "baseline_sha": baseline,
        "final_diff_digest": tax_mod.taxonomy_digest_bytes(diff_bytes),
        "receipt_rel": "docs/superpowers/execution/%s/review/receipt.json"
                       % _FP_RUN_ID,
    }


def _fp_git_worktree_and_state(d, tax_mod, manifest_text):
    """CRIT-1 topology: a MAIN repo (``repo_root``) holding the committed artifacts
    + state.json, and a SEPARATE linked WORKTREE (``diff_root``) holding the
    worker's file change. The producer hashes the final diff in the worktree, so
    the validator must recompute there — NOT in the main checkout. Returns
    (info, worktree_path) or (None, None) when git/worktree is unavailable."""
    import subprocess

    def g(cwd, *a):
        return subprocess.run(["git", "-C", cwd] + list(a),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if g(d, "init", "-q").returncode != 0:
        return None, None
    g(d, "config", "user.email", "selftest@example.com")
    g(d, "config", "user.name", "cv-selftest")
    g(d, "config", "commit.gpgsign", "false")
    g(d, "config", "core.hooksPath", "/dev/null")
    g(d, "add", "-A")
    if g(d, "commit", "-q", "--no-verify", "-m", "baseline").returncode != 0:
        return None, None
    rp = g(d, "rev-parse", "HEAD")
    if rp.returncode != 0:
        return None, None
    baseline = rp.stdout.decode("utf-8", "replace").strip()

    wt = d + "-wt"
    if g(d, "worktree", "add", "-q", "--detach", wt, baseline).returncode != 0:
        return None, None
    # The worker change lives ONLY in the linked worktree (the main tree is clean).
    with open(os.path.join(wt, _FP_WRITE_PATH), "a", encoding="utf-8") as fh:
        fh.write("/* changed by the worker in the linked worktree */\n")
    diff = g(wt, "diff", "--no-color", baseline)
    if diff.returncode != 0:
        return None, None
    diff_bytes = diff.stdout or b""

    state = {"run_id": _FP_RUN_ID,
             "jobs": {_FP_JOB_ID: {"status": "success", "baseline": baseline}}}
    _fp_write(d, "docs/superpowers/execution/%s/state.json" % _FP_RUN_ID,
              json.dumps(state))
    return ({
        "run_id": _FP_RUN_ID,
        "manifest_digest": tax_mod.taxonomy_digest_bytes(
            manifest_text.encode("utf-8")),
        "baseline_sha": baseline,
        "final_diff_digest": tax_mod.taxonomy_digest_bytes(diff_bytes),
        "receipt_rel": "docs/superpowers/execution/%s/review/receipt.json"
                       % _FP_RUN_ID,
    }, wt)


def _fp_write_receipt(d, tax_mod, info, drop=None, bad_digest=False, **over):
    """Write a post-review receipt bound to the real git state in ``info``.
    ``over`` mutates a field (the self-digest is recomputed AFTER, so exactly the
    overridden binding fails); ``bad_digest`` breaks the self-digest; ``drop``
    removes fields entirely."""
    receipt = {
        "run_id": _FP_RUN_ID,
        "pre_eval_id": _FP_RUN_ID,
        "manifest_digest": info["manifest_digest"],
        "baseline_sha": info["baseline_sha"],
        "final_diff_digest": info["final_diff_digest"],
        "reviewer_backend": "claude",
        "reviewer_model": "opus",
        "reviewer_tier": "deep",  # schema-required (fastpath-run R3 MED-6)
        # MED-6: bind to the diff-root by default (the repo root ``d`` — the diff-root
        # when no separate worktree is passed). The CRIT-1 worktree topology overrides
        # this via ``worktree=<wt>`` so it matches the linked worktree diff_root.
        "worktree": d,
        "attempt_id": 1,
        "ts": "2026-07-12T10:20:00Z",
        "verdict": "approved",
        "integration_rationale": "single-job fast-path: no cross-job seams",
    }
    receipt.update(over)
    for k in (drop or []):
        receipt.pop(k, None)
    if "digest" in (drop or []):
        pass  # intentionally absent
    elif bad_digest:
        receipt["digest"] = "sha256:" + ("e" * 64)
    else:
        receipt["digest"] = tax_mod.record_digest(receipt, exclude_field="digest")
    _fp_write(d, info["receipt_rel"], json.dumps(receipt))


def _selftest_fastpath(expect):
    import tempfile

    tax_mod = _sibling("compound-v-taxonomy.py")
    if tax_mod is None:
        expect("fastpath: shared taxonomy module loads", False)
        return

    base = tempfile.mkdtemp(prefix="cv-c1-fp-")

    def case(name):
        d = os.path.join(base, name)
        os.makedirs(d, exist_ok=True)
        return d

    # (a) minimal fast_path manifest validates under pre-dispatch.
    d = case("valid_predispatch")
    txt = _fp_build(d, tax_mod)
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: valid manifest passes pre-dispatch (%r)" % res, res == [])

    # No-mode = fail-closed for a fast_path manifest.
    d = case("nomode")
    txt = _fp_build(d, tax_mod)
    res = validate_text(txt, mode=None, repo_root=d)
    expect("fastpath: no --mode is rejected (fail-closed)",
           any("mode" in p.lower() for p in res))

    # (b) a second jobs entry under fast_path fails.
    d = case("secondjob")
    txt = _fp_build(d, tax_mod, second_job=True)
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: second job rejected",
           any("exactly ONE" in p for p in res))

    # (c) glob write_allowed under fast_path rejected; one literal path passes.
    d = case("globwrite")
    txt = _fp_build(d, tax_mod, glob_write=True)
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: glob write_allowed rejected",
           any("LITERAL" in p for p in res))

    # (d) block-YAML skip-record validates; flow-{} rejected ("use block YAML").
    d = case("flowaudit")
    txt = _fp_build(d, tax_mod, audits_flow=True)
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: flow-{} audit rejected (use block YAML)",
           any("block YAML" in p for p in res))
    # _mini_yaml nested-mapping fixture: the skip-record parses as a real mapping.
    parsed = _mini_yaml(_fp_build(case("miniyaml"), tax_mod))
    expect("fastpath: _mini_yaml parses nested skip-record mapping",
           isinstance(parsed.get("audits", {}).get("archaeology"), dict)
           and parsed["audits"]["archaeology"].get("skipped") is True)

    # (e) taxonomy classification: a sensitive write target is rejected.
    d = case("sensitive")
    txt = _fp_build(d, tax_mod, write_path="src/auth/login.css",
                    resolved_path="src/auth/login.css")
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: sensitive-path write target rejected",
           any("sensitive" in p for p in res))
    # unreadable taxonomy snapshot -> fail-closed.
    d = case("badtax")
    txt = _fp_build(d, tax_mod)
    os.remove(os.path.join(
        d, "docs/superpowers/execution/2026-07-12T101500Z-make-button-red-a1b2/"
        "taxonomy-snapshot.yaml"))
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: unreadable taxonomy snapshot fails closed",
           any("taxonomy" in p.lower() and ("unreadable" in p or "does not exist"
               in p or "not a regular file" in p) for p in res))

    # (f) cross-artifact binding tampering — every mismatched field fails.
    d = case("tamper_path")
    _fp_write(d, "src/components/other.css", "body{}\n")
    txt = _fp_build(d, tax_mod, write_path="src/components/other.css",
                    resolved_path="src/components/button.css")
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: write literal != resolved_paths[0] rejected",
           any("resolved_paths[0]" in p for p in res))

    d = case("tamper_preid")
    txt = _fp_build(d, tax_mod, manifest_pre_eval_id="2026-07-12T101500Z-evil-9999")
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: pre_eval_id mismatch rejected",
           any("pre_eval_id" in p for p in res))

    d = case("tamper_decision")
    txt = _fp_build(d, tax_mod, record_decision="FULL_PIPELINE")
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: non-FASTPATH_ELIGIBLE record rejected",
           any("FASTPATH_ELIGIBLE" in p for p in res))

    # CRIT-2: pinned pre-eval record self-digest + FASTPATH_ELIGIBLE band gate.
    d = case("tamper_rec_selfdigest")
    txt = _fp_build(d, tax_mod, record_bad_digest=True)
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: pre-eval record self-digest mismatch rejected",
           any("record" in p and "self-digest" in p for p in res))

    d = case("tamper_rec_missing_digest")
    txt = _fp_build(d, tax_mod, record_drop_digest=True)
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: pre-eval record missing self-digest rejected",
           any("record" in p and "self-digest" in p for p in res))

    # A FULL_PIPELINE record whose decision is flipped to FASTPATH_ELIGIBLE with a
    # MEDIUM band (and a freshly-VALID self-digest) MUST still fail on the band gate.
    d = case("tamper_rec_medium_band")
    txt = _fp_build(d, tax_mod, record_impact_band="medium")
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: pinned record impact.band=medium rejected (not low)",
           any("impact.band" in p and "not 'low'" in p for p in res))

    d = case("tamper_rec_diff_band")
    txt = _fp_build(d, tax_mod, record_difficulty_band="high")
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: pinned record difficulty.band=high rejected (not low)",
           any("difficulty.band" in p and "not 'low'" in p for p in res))

    d = case("tamper_rec_override")
    txt = _fp_build(d, tax_mod, record_override_fired=3)
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: pinned record override_fired set rejected",
           any("override_fired" in p for p in res))

    d = case("tamper_taxdigest")
    txt = _fp_build(d, tax_mod, manifest_tax_digest="sha256:" + ("0" * 64))
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: taxonomy_digest mismatch rejected",
           any("taxonomy_digest" in p for p in res))

    d = case("tamper_locdigest")
    txt = _fp_build(d, tax_mod, artifact_fan_out=99)
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: localization content-digest mismatch rejected",
           any("localization" in p and "digest" in p for p in res))

    # MED-8: a MISSING localization-artifact content-digest previously slipped
    # through (only a present string was compared); absence must fail closed.
    d = case("med8_loc_missing_digest")
    txt = _fp_build(d, tax_mod, artifact_drop_digest=True)
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath MED-8: localization artifact missing content-digest "
           "rejected (absence fails closed)",
           any("localization artifact content-digest is missing" in p
               for p in res))

    # MED-8: a wrong-SHAPE localization-artifact digest also fails closed.
    d = case("med8_loc_badshape_digest")
    txt = _fp_build(d, tax_mod, artifact_bad_shape_digest=True)
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath MED-8: localization artifact malformed content-digest "
           "rejected (wrong shape fails closed)",
           any("missing or malformed" in p for p in res))

    # (g) two validation modes.
    d = case("declined_backend")
    txt = _fp_build(d, tax_mod, review={"backend": "codex", "tier": "deep"})
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: review backend != claude rejected",
           any("claude" in p and "review" in p.lower() for p in res))

    d = case("review_no_deep_no_opus")
    txt = _fp_build(d, tax_mod, review={"backend": "claude", "tier": "standard"})
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: review claude+standard (not deep/opus) rejected",
           any("deep" in p or "opus" in p for p in res))

    # pre-dispatch forbids a receipt.
    d = case("predispatch_receipt")
    txt = _fp_build(d, tax_mod, make_receipt=_fp_receipt())
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: pre-dispatch forbids an existing receipt",
           any("forbid" in p or "receipt" in p for p in res))

    # post-review requires + FULLY verifies the receipt (CR5-6). Real git repo so
    # manifest_digest / baseline_sha / final_diff_digest are recomputable; a stale
    # or mismatched binding, or a non-approved verdict, MUST fail closed.
    import shutil as _shutil
    if _shutil.which("git") is not None:
        def _postreview(name, drop=None, bad_digest=False, **over):
            d = case(name)
            txt = _fp_build(d, tax_mod)
            info = _fp_git_and_state(d, tax_mod, txt)
            if info is None:
                return None, d
            _fp_write_receipt(d, tax_mod, info, drop=drop,
                              bad_digest=bad_digest, **over)
            return validate_text(txt, mode="post-review", repo_root=d), d

        res, _ = _postreview("postreview_ok")
        expect("fastpath: post-review with a fully-bound receipt passes (%r)"
               % res, res == [])

        res, _ = _postreview("postreview_badbackend", reviewer_backend="codex")
        expect("fastpath: receipt reviewer_backend != claude rejected",
               res is not None and any("claude" in p for p in res))

        res, _ = _postreview("postreview_badmodel", reviewer_model="sonnet")
        expect("fastpath: receipt reviewer_model not Opus rejected",
               res is not None and any(
                   "opus" in p.lower() or "resolved" in p.lower() for p in res))

        res, _ = _postreview("postreview_verdict_issues", verdict="issues")
        expect("fastpath: receipt verdict 'issues' rejected",
               res is not None and any(
                   "verdict" in p.lower() and "approved" in p.lower()
                   for p in res))

        res, _ = _postreview("postreview_verdict_absent", drop=["verdict"])
        expect("fastpath: receipt with absent verdict rejected",
               res is not None and any("verdict" in p.lower() for p in res))

        res, _ = _postreview("postreview_bad_manifest_digest",
                             manifest_digest="sha256:" + ("0" * 64))
        expect("fastpath: receipt manifest_digest mismatch rejected "
               "(stale/wrong manifest)",
               res is not None and any("manifest_digest" in p for p in res))

        res, _ = _postreview("postreview_bad_baseline", baseline_sha="f" * 40)
        expect("fastpath: receipt baseline_sha mismatch rejected",
               res is not None and any(
                   "baseline" in p.lower() and "!=" in p for p in res))

        res, _ = _postreview("postreview_stale_diff",
                             final_diff_digest="sha256:" + ("0" * 64))
        expect("fastpath: receipt final_diff_digest mismatch rejected "
               "(stale-replay)",
               res is not None and any("final_diff_digest" in p for p in res))

        res, _ = _postreview("postreview_bad_selfdigest", bad_digest=True)
        expect("fastpath: receipt self-digest mismatch rejected",
               res is not None and any(
                   "receipt self-digest" in p.lower() for p in res))

        res, _ = _postreview("postreview_missing_selfdigest", drop=["digest"])
        expect("fastpath: receipt missing self-digest rejected",
               res is not None and any(
                   "missing its self-digest" in p.lower() for p in res))

        # A receipt that exists but the run has NO immutable baseline → fail-closed.
        d = case("postreview_nobaseline")
        txt = _fp_build(d, tax_mod)
        info = _fp_git_and_state(d, tax_mod, txt)
        if info is not None:
            _fp_write(d, "docs/superpowers/execution/%s/state.json" % _FP_RUN_ID,
                      json.dumps({"run_id": _FP_RUN_ID, "jobs": {}}))
            _fp_write_receipt(d, tax_mod, info)
            res = validate_text(txt, mode="post-review", repo_root=d)
            expect("fastpath: post-review with no run baseline fails closed",
                   any("baseline" in p.lower() for p in res))

        # CRIT-1: the final-diff recompute MUST run in the SAME checkout the
        # producer hashed — the worker's linked WORKTREE (diff_root) — not the
        # main repo the dispatcher passes as --repo-root.
        d = case("crit1_worktree_diff_root")
        txt = _fp_build(d, tax_mod)
        wt_info, wt = _fp_git_worktree_and_state(d, tax_mod, txt)
        if wt_info is not None:
            # MED-6: the receipt's worktree binding must name the linked worktree
            # (the diff-root the producer hashed) — not the main repo root.
            _fp_write_receipt(d, tax_mod, wt_info, worktree=wt)
            # (i) with --worktree the receipt's worktree-hashed diff recomputes to
            #     the same digest → PASS (the main tree is clean, so this only
            #     passes because the recompute honored diff_root).
            res = validate_text(txt, mode="post-review", repo_root=d,
                                diff_root=wt)
            expect("fastpath CRIT-1: post-review recomputes the diff in the "
                   "linked worktree -> passes (%r)" % res, res == [])
            # (ii) WITHOUT --worktree the recompute falls to the main repo, whose
            #      diff against baseline is empty → digest mismatch → fail-closed.
            #      Proves the recompute is NOT anchored to repo_root.
            res = validate_text(txt, mode="post-review", repo_root=d,
                                diff_root=None)
            expect("fastpath CRIT-1: recomputing in the main checkout (no "
                   "worktree change) fails closed on the diff digest",
                   any("final_diff_digest" in p for p in res))
            # (iii) an unavailable diff_root never silently passes — fail-closed.
            res = validate_text(txt, mode="post-review", repo_root=d,
                                diff_root=os.path.join(d, "no-such-worktree"))
            expect("fastpath CRIT-1: an unavailable diff-root fails closed",
                   any("recompute the final diff" in p for p in res))
        else:
            expect("fastpath CRIT-1: worktree diff-root suite (git worktree "
                   "unavailable - skipped)", True)

        # ---- ROUND-4 HIGH-1(b): post-review attempt binding (--expected-attempt) ----
        # A receipt sealed at attempt 1, validated when the run's CURRENT attempt is 2,
        # is a stale prior-attempt replay → REJECTED. A correctly-incremented receipt
        # passes. When --expected-attempt is absent, behavior is unchanged (back-compat).
        d = case("postreview_attempt_stale")
        txt = _fp_build(d, tax_mod)
        info = _fp_git_and_state(d, tax_mod, txt)
        if info is not None:
            _fp_write_receipt(d, tax_mod, info, attempt_id=1)
            expect("fastpath HIGH-1: attempt-1 receipt passes when NO expected "
                   "attempt is supplied (back-compat)",
                   validate_text(txt, mode="post-review", repo_root=d) == [])
            expect("fastpath HIGH-1: attempt-1 receipt passes --expected-attempt 1",
                   validate_text(txt, mode="post-review", repo_root=d,
                                 expected_attempt=1) == [])
            res_att = validate_text(txt, mode="post-review", repo_root=d,
                                    expected_attempt=2)
            expect("fastpath HIGH-1: attempt-1 receipt REJECTED under "
                   "--expected-attempt 2 (stale prior-attempt replay)",
                   any("attempt_id" in p and "expected review attempt" in p
                       for p in res_att))

        d = case("postreview_attempt_fresh")
        txt = _fp_build(d, tax_mod)
        info = _fp_git_and_state(d, tax_mod, txt)
        if info is not None:
            _fp_write_receipt(d, tax_mod, info, attempt_id=2)
            expect("fastpath HIGH-1: correctly-incremented attempt-2 receipt passes "
                   "--expected-attempt 2",
                   validate_text(txt, mode="post-review", repo_root=d,
                                 expected_attempt=2) == [])

        # ---- ROUND-4 MED-3: an unloadable receipt schema fails CLOSED (no shape skip) ----
        d = case("postreview_schema_unloadable")
        txt = _fp_build(d, tax_mod)
        info = _fp_git_and_state(d, tax_mod, txt)
        if info is not None:
            _fp_write_receipt(d, tax_mod, info)  # a fully-valid receipt
            expect("fastpath MED-3: baseline receipt passes with a loadable schema",
                   validate_text(txt, mode="post-review", repo_root=d) == [])
            # Stub the module's schema path at a MALFORMED file — the load must fail and
            # that failure must itself be a rejection (never a silent shape-check skip).
            _saved_schema = _RECEIPT_SCHEMA
            bad_schema = os.path.join(d, "bad-schema.json")
            with open(bad_schema, "w", encoding="utf-8") as fh:
                fh.write("{ this is not valid json")
            vars(_fastpath_support)["_RECEIPT_SCHEMA"] = bad_schema
            try:
                res_sch = validate_text(txt, mode="post-review", repo_root=d)
            finally:
                vars(_fastpath_support)["_RECEIPT_SCHEMA"] = _saved_schema
            expect("fastpath MED-3: malformed receipt schema REJECTS (fail-closed, "
                   "no shape-check skip)",
                   any("schema" in p.lower() and "fail-closed" in p.lower()
                       for p in res_sch))
            # A MISSING schema file also fails closed.
            vars(_fastpath_support)["_RECEIPT_SCHEMA"] = os.path.join(d, "does-not-exist.json")
            try:
                res_sch2 = validate_text(txt, mode="post-review", repo_root=d)
            finally:
                vars(_fastpath_support)["_RECEIPT_SCHEMA"] = _saved_schema
            expect("fastpath MED-3: missing receipt schema also REJECTS (fail-closed)",
                   any("schema" in p.lower() and "fail-closed" in p.lower()
                       for p in res_sch2))
    else:
        expect("fastpath: post-review git-binding suite (git unavailable — "
               "skipped)", True)

    # post-review still REQUIRES a receipt (independent of git availability).
    d = case("postreview_missing")
    txt = _fp_build(d, tax_mod)  # no receipt written
    res = validate_text(txt, mode="post-review", repo_root=d)
    expect("fastpath: post-review requires a receipt",
           any("receipt" in p for p in res))

    # (h) containment: traversal ref + escaping symlink write target.
    d = case("traversal_ref")
    txt = _fp_build(d, tax_mod, loc_ref="../evil.localization.json")
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: '..' traversal ref rejected",
           any("traversal" in p or ".." in p for p in res))

    if hasattr(os, "symlink"):
        d = case("symlink_write")
        try:
            txt = _fp_build(d, tax_mod, symlink_write=True)
            res = validate_text(txt, mode="pre-dispatch", repo_root=d)
            expect("fastpath: escaping-symlink write target rejected",
                   any("symlink" in p or "outside the repo" in p
                       or "escape" in p for p in res))
        except OSError:
            expect("fastpath: escaping-symlink write target rejected "
                   "(symlink unsupported — skipped)", True)

    # MED-9: a fast_path *_ref that is TRACKED/STAGED but absent from any commit
    # must fail — `git ls-files` is not proof of a commit (execution-manifest.md
    # §218-220: referenced artifacts must live in a commit).
    if _shutil.which("git") is not None:
        import subprocess as _sp

        def _gitstage(root, commit):
            r = _sp.run(["git", "-C", root, "init", "-q"],
                        stdout=_sp.PIPE, stderr=_sp.PIPE)
            if r.returncode != 0:
                return False
            for kv in (("user.email", "s@e.com"), ("user.name", "cv"),
                       ("commit.gpgsign", "false"), ("core.hooksPath", "/dev/null")):
                _sp.run(["git", "-C", root, "config"] + list(kv),
                        stdout=_sp.PIPE, stderr=_sp.PIPE)
            _sp.run(["git", "-C", root, "add", "-A"],
                    stdout=_sp.PIPE, stderr=_sp.PIPE)
            if commit:
                r = _sp.run(["git", "-C", root, "commit", "-q", "--no-verify",
                             "-m", "b"], stdout=_sp.PIPE, stderr=_sp.PIPE)
                return r.returncode == 0
            return True  # staged only — deliberately no commit, so no HEAD

        # (i) staged-not-committed: refs are tracked by ls-files yet in NO commit
        #     → the HEAD-commit check must reject (the pre-MED-9 code PASSED here).
        d = case("med9_staged_not_committed")
        txt = _fp_build(d, tax_mod)
        if _gitstage(d, commit=False):
            res = validate_text(txt, mode="pre-dispatch", repo_root=d)
            expect("fastpath MED-9: staged-but-uncommitted ref rejected "
                   "(ls-files is not a commit)",
                   any("not present in a commit" in p for p in res))
        else:
            expect("fastpath MED-9: staged-not-committed suite (git init failed "
                   "- skipped)", True)

        # (ii) genuinely committed refs pass under pre-dispatch — the HEAD check
        #      does not over-reject a durable artifact.
        d = case("med9_committed_ok")
        txt = _fp_build(d, tax_mod)
        if _gitstage(d, commit=True):
            res = validate_text(txt, mode="pre-dispatch", repo_root=d)
            expect("fastpath MED-9: committed refs pass pre-dispatch (%r)" % res,
                   res == [])
        else:
            expect("fastpath MED-9: committed-ok suite (commit failed - "
                   "skipped)", True)
    else:
        expect("fastpath MED-9: commit-containment suite (git unavailable - "
               "skipped)", True)

    # ---------------------------------------------------------------------- #
    # MED-6: the receipt's own ``worktree`` binding MUST equal the diff-root the
    # validator recomputes the final diff in. A missing binding, or one that
    # resolves to a DIFFERENT checkout, fails closed. (The matching-worktree
    # PASS is already proven by the CRIT-1 (i) case above with worktree=wt.)
    # ---------------------------------------------------------------------- #
    if _shutil.which("git") is not None:
        # (a) a receipt with NO worktree binding is rejected.
        d = case("med6_missing_worktree")
        txt = _fp_build(d, tax_mod)
        info = _fp_git_and_state(d, tax_mod, txt)
        if info is not None:
            _fp_write_receipt(d, tax_mod, info, drop=["worktree"])
            res = validate_text(txt, mode="post-review", repo_root=d)
            expect("fastpath MED-6: receipt without a 'worktree' binding rejected",
                   any("worktree" in p.lower() and "MED-6" in p for p in res))
        else:
            expect("fastpath MED-6: missing-worktree suite (git init failed - "
                   "skipped)", True)

        # (b) a receipt whose worktree resolves to a DIFFERENT checkout than the
        #     diff-root is rejected (a receipt sealed against another checkout).
        d = case("med6_wrong_worktree")
        txt = _fp_build(d, tax_mod)
        info = _fp_git_and_state(d, tax_mod, txt)
        if info is not None:
            other = os.path.join(d, "some", "other", "checkout")
            _fp_write_receipt(d, tax_mod, info, worktree=other)
            res = validate_text(txt, mode="post-review", repo_root=d)
            expect("fastpath MED-6: receipt worktree bound to a different checkout "
                   "rejected",
                   any("different checkout" in p and "MED-6" in p for p in res))
        else:
            expect("fastpath MED-6: wrong-worktree suite (git init failed - "
                   "skipped)", True)

        # (c) the correct binding (worktree == repo-root diff-root) still PASSES —
        #     the new gate does not over-reject a genuine single-tree receipt.
        d = case("med6_correct_worktree")
        txt = _fp_build(d, tax_mod)
        info = _fp_git_and_state(d, tax_mod, txt)
        if info is not None:
            _fp_write_receipt(d, tax_mod, info, worktree=d)
            res = validate_text(txt, mode="post-review", repo_root=d)
            expect("fastpath MED-6: correctly-bound worktree receipt passes (%r)"
                   % res, res == [])
        else:
            expect("fastpath MED-6: correct-worktree suite (git init failed - "
                   "skipped)", True)

    # ---------------------------------------------------------------------- #
    # MED-8: HEAD-commit containment fails CLOSED on a git error while a `.git`
    # IS present (was a silent skip), but still DEGRADES when there is no `.git`
    # at all (the legitimate no-git pre-dispatch path). The git-error condition
    # is simulated deterministically by stubbing the module-level probe to its
    # sentinels; the real probe is also exercised end-to-end.
    # ---------------------------------------------------------------------- #
    if _shutil.which("git") is not None:
        import subprocess as _sp8
        med8 = case("med8_headcheck")
        _fp_write(med8, "docs/a.json", "{}")

        def _g8(*a):
            return _sp8.run(["git", "-C", med8] + list(a),
                            stdout=_sp8.PIPE, stderr=_sp8.PIPE)

        _ok8 = _g8("init", "-q").returncode == 0
        for _kv in (("user.email", "s@e.com"), ("user.name", "cv"),
                    ("commit.gpgsign", "false"), ("core.hooksPath", "/dev/null")):
            _g8("config", *_kv)
        _g8("add", "-A")
        _ok8 = _ok8 and _g8("commit", "-q", "--no-verify", "-m", "b").returncode == 0

        if _ok8:
            g = vars(_fastpath_support)
            saved = g["_is_committed_at_head"]
            # (a) git-error sentinel while a `.git` is present -> fail closed.
            g["_is_committed_at_head"] = lambda rr, rp: _GIT_UNAVAILABLE
            try:
                probs = _containment_problems(
                    "artifact", "docs/a.json", med8,
                    must_exist=True, require_committed=True)
            finally:
                g["_is_committed_at_head"] = saved
            expect("fastpath MED-8: HEAD containment fails closed on a git error "
                   "(not a silent skip)",
                   any("could not be verified" in p and "MED-8" in p
                       for p in probs))

            # (b) the no-`.git` degrade sentinel (None) still SKIPS — the
            #     legitimate no-git path must not be turned into a violation.
            g["_is_committed_at_head"] = lambda rr, rp: None
            try:
                probs = _containment_problems(
                    "artifact", "docs/a.json", med8,
                    must_exist=True, require_committed=True)
            finally:
                g["_is_committed_at_head"] = saved
            expect("fastpath MED-8: no-.git containment still degrades (skip, not "
                   "a fail)",
                   not any("could not be verified" in p
                           or "not present in a commit" in p for p in probs))

            # (c) the REAL probe (through the timeout supervisor) returns True for
            #     a genuinely committed file.
            expect("fastpath MED-8: real _is_committed_at_head True for a "
                   "committed file",
                   _is_committed_at_head(med8, "docs/a.json") is True)
        else:
            expect("fastpath MED-8: git-error containment suite (git init/commit "
                   "failed - skipped)", True)
    else:
        expect("fastpath MED-8: git-error containment suite (git unavailable - "
               "skipped)", True)

    # (d) the REAL probe returns None (degrade) when there is no `.git` at all —
    #     independent of git availability, since it never shells out.
    nogit = case("med8_nogit")
    _fp_write(nogit, "docs/a.json", "{}")
    expect("fastpath MED-8: real _is_committed_at_head None when no .git (legit "
           "degrade)", _is_committed_at_head(nogit, "docs/a.json") is None)


def _selftest():
    failures = []

    def expect(name, cond):
        if cond:
            print("  ok   - %s" % name)
        else:
            print("  FAIL - %s" % name)
            failures.append(name)

    # Glob overlap units.
    expect("overlap: identical globs", globs_overlap("a/**", "a/**"))
    expect(
        "overlap: src/features/** vs src/features/api/**",
        globs_overlap("src/features/**", "src/features/api/**"),
    )
    expect(
        "disjoint: src/a/** vs src/b/**",
        not globs_overlap("src/a/**", "src/b/**"),
    )
    expect(
        "disjoint: src/types/x.ts vs src/db/y.ts",
        not globs_overlap("src/types/x.ts", "src/db/y.ts"),
    )
    expect(
        "overlap: dir/* vs dir/file.ts",
        globs_overlap("dir/*", "dir/file.ts"),
    )

    # GOOD manifest -> zero violations.
    good = validate_text(GOOD_MANIFEST)
    expect("good manifest: zero violations (%r)" % good, good == [])

    # BAD manifest -> catches each planted defect.
    bad = validate_text(BAD_MANIFEST)
    joined = " || ".join(bad)
    expect("bad manifest: has violations", len(bad) > 0)
    expect(
        "bad: codex-without-worktree caught",
        "backend codex" in joined and "isolation" in joined,
    )
    expect(
        "bad: reviewer-not-opus caught",
        "reviewer job" in joined and "opus" in joined,
    )
    expect("bad: write overlap caught", "overlap" in joined)
    expect(
        "bad: shared_foundation non-serial caught",
        "must run serial" in joined,
    )
    expect(
        "bad: orphan shared resource caught",
        "orphan.ts" in joined or "not written by any" in joined,
    )
    expect(
        "bad: missing model-or-tier caught",
        "must have 'model' or 'tier'" in joined,
    )
    expect(
        "bad: invalid tier caught",
        "tier 'turbo' invalid" in joined,
    )
    expect(
        "bad: invalid effort caught",
        "effort 'extreme' invalid" in joined,
    )

    # effort xhigh: valid iff backend codex — selftested BOTH ways.
    xh_ok = validate_text(XHIGH_CODEX_MANIFEST)
    expect("codex+xhigh manifest valid (%r)" % xh_ok, xh_ok == [])
    xh_bad = validate_text(XHIGH_CLAUDE_MANIFEST)
    expect(
        "claude+xhigh caught (xhigh is codex-only)",
        any("xhigh is codex-only (kernel: model_reasoning_effort); use high" in p
            for p in xh_bad),
    )
    expect(
        "bad: parallel+direct caught",
        "run: parallel with isolation: direct" in joined,
    )

    # timeout_sec: optional, integer seconds, bounded [60, 21600]. ABSENT is valid
    # and leaves the worker script's DEFAULT_TIMEOUT_SEC=900 in force.
    ts_absent = validate_text(_timeout_manifest(""))
    expect("timeout_sec absent: manifest valid (%r)" % ts_absent, ts_absent == [])
    ts_ok = validate_text(_timeout_manifest("1800"))
    expect("timeout_sec 1800: manifest valid (%r)" % ts_ok, ts_ok == [])
    for _edge in (TIMEOUT_SEC_MIN, TIMEOUT_SEC_MAX):
        _e = validate_text(_timeout_manifest(str(_edge)))
        expect("timeout_sec %d (inclusive bound) valid (%r)" % (_edge, _e), _e == [])
    ts_small = validate_text(_timeout_manifest(str(TIMEOUT_SEC_MIN - 1)))
    expect(
        "timeout_sec too small caught",
        any("timeout_sec 59 out of range" in p and "60" in p and "21600" in p
            for p in ts_small),
    )
    ts_large = validate_text(_timeout_manifest(str(TIMEOUT_SEC_MAX + 1)))
    expect(
        "timeout_sec too large caught",
        any("timeout_sec 21601 out of range" in p and "60" in p and "21600" in p
            for p in ts_large),
    )
    ts_bool = validate_text(_timeout_manifest("true"))
    expect(
        "timeout_sec bool caught (bool is an int subclass)",
        any("timeout_sec must be an integer number of seconds" in p
            for p in ts_bool),
    )
    ts_str = validate_text(_timeout_manifest('"900"'))
    expect(
        "timeout_sec string caught",
        any("timeout_sec must be an integer number of seconds" in p
            for p in ts_str),
    )
    expect(
        "no unknown-key rejection introduced (good manifest still clean)",
        not any("unknown" in p.lower() for p in good),
    )

    # never-Haiku policy: a model: haiku execution-layer override is INVALID.
    haiku = validate_text(HAIKU_MODEL_MANIFEST)
    expect(
        "model:haiku override caught (never-Haiku policy)",
        any("never-Haiku policy" in p for p in haiku),
    )

    # depends_on: dangling ref INVALID, cycle INVALID, valid DAG OK.
    dangling = validate_text(DANGLING_DEP_MANIFEST)
    expect(
        "dangling depends_on ref caught",
        any("references unknown job id 'task-0-missing'" in p for p in dangling),
    )
    cyc = validate_text(CYCLE_DEP_MANIFEST)
    expect(
        "depends_on cycle caught",
        any("cycle detected" in p for p in cyc),
    )
    expect(
        "valid DAG (good manifest) has no depends_on violation",
        not any("depends_on" in p or "cycle detected" in p for p in good),
    )

    # Structural type check: wrong-typed required field is a specific violation.
    wt_bad = validate_text(WRONG_TYPE_MANIFEST)
    expect(
        "wrong-typed acceptance_criteria caught",
        any("'acceptance_criteria' must be a list" in p for p in wt_bad),
    )

    # parallel ⇒ worktree, and a bad job id, each caught.
    pd_bad = validate_text(PARALLEL_DIRECT_MANIFEST)
    expect(
        "parallel+direct manifest invalid",
        any("run: parallel with isolation: direct" in p for p in pd_bad),
    )
    badid = validate_text(BAD_ID_MANIFEST)
    expect(
        "bad job id '../x' caught",
        any("invalid characters" in p for p in badid),
    )

    # antigravity ⇒ worktree: an external no-kernel-sandbox worker with
    # isolation: direct is INVALID (mirrors the codex⇒worktree invariant).
    agy_bad = validate_text(ANTIGRAVITY_DIRECT_MANIFEST)
    expect(
        "antigravity+direct caught (antigravity requires worktree)",
        any("backend antigravity but isolation" in p
            and "antigravity requires worktree" in p for p in agy_bad),
    )

    # opencode ⇒ worktree: same invariant, new backend (v1: worker-only, lower-trust).
    opencode_bad = validate_text(OPENCODE_DIRECT_MANIFEST)
    expect(
        "opencode+direct caught (opencode requires worktree)",
        any("backend opencode but isolation" in p
            and "opencode requires worktree" in p for p in opencode_bad),
    )
    opencode_ok = validate_text(OPENCODE_WORKTREE_MANIFEST)
    expect("opencode+worktree manifest is valid (provider/model string accepted)",
           opencode_ok == [])

    # WORKER-ONLY: a reviewer job MUST NEVER resolve to backend opencode,
    # even when tier: deep + isolation: worktree are otherwise satisfied.
    opencode_reviewer_bad = validate_text(OPENCODE_REVIEWER_MANIFEST)
    expect(
        "opencode reviewer job REJECTED (WORKER-ONLY)",
        any("reviewer job 'task-1-quality-review'" in p
            and "backend 'opencode'" in p
            and "WORKER-ONLY" in p for p in opencode_reviewer_bad),
    )

    # opencode provider/model shape: a bare (slash-less) or malformed (empty-side)
    # explicit model override is REJECTED before dispatch.
    opencode_bare_bad = validate_text(OPENCODE_BARE_MODEL_MANIFEST)
    expect(
        "bare opencode model 'gpt-6' REJECTED (not provider/model)",
        any("not a valid 'provider/model' string" in p for p in opencode_bare_bad),
    )
    opencode_malformed_bad = validate_text(OPENCODE_MALFORMED_MODEL_MANIFEST)
    expect(
        "malformed opencode model 'anthropic/' REJECTED (empty right side)",
        any("not a valid 'provider/model' string" in p
            for p in opencode_malformed_bad),
    )
    # NON-STRING opencode model (int / list / dict) must ALSO be rejected — it can
    # never be a provider/model string and must not skip the shape check.
    opencode_int_bad = validate_text(OPENCODE_INT_MODEL_MANIFEST)
    expect(
        "non-string opencode model (int 42) REJECTED",
        any("not a valid 'provider/model' string" in p
            for p in opencode_int_bad),
    )
    opencode_list_bad = validate_text(OPENCODE_LIST_MODEL_MANIFEST)
    expect(
        "non-string opencode model (list) REJECTED",
        any("not a valid 'provider/model' string" in p
            for p in opencode_list_bad),
    )
    opencode_dict_bad = validate_text(OPENCODE_DICT_MODEL_MANIFEST)
    expect(
        "non-string opencode model (dict) REJECTED",
        any("not a valid 'provider/model' string" in p
            for p in opencode_dict_bad),
    )

    # Reviewer satisfied by tier: deep (no model) — GOOD manifest task-3 uses
    # tier: deep and must not trip the reviewer invariant.
    expect(
        "reviewer via tier:deep accepted (no model)",
        not any("reviewer job 'task-3-spec-review'" in p for p in good),
    )
    # Finding 119: a reviewer lifted to the frontier tier (Fable) is STRONGER than
    # deep and must pass; a light-tier reviewer must still fail. The GOOD manifest
    # re-parsed, mutated, re-dumped — validate_text is the same entry the case
    # above used, so the two verdicts differ only in the reviewer's tier.
    import yaml as _yaml_f119
    _fr = _yaml_f119.safe_load(GOOD_MANIFEST)
    for _j in _fr.get("jobs", []):
        if _j.get("id") == "task-3-spec-review":
            _j["tier"] = "frontier"; _j.pop("model", None)
    _fr_probs = validate_text(_yaml_f119.safe_dump(_fr, sort_keys=False))
    expect("reviewer via tier:frontier accepted — stronger passes (finding 119)",
           not any("reviewer job 'task-3-spec-review'" in p for p in _fr_probs))
    for _j in _fr.get("jobs", []):
        if _j.get("id") == "task-3-spec-review":
            _j["tier"] = "light"
    _fr_probs2 = validate_text(_yaml_f119.safe_dump(_fr, sort_keys=False))
    expect("reviewer via tier:light still refused (finding 119 never weakens)",
           any("reviewer job 'task-3-spec-review'" in p for p in _fr_probs2))

    # Empty / malformed.
    expect("no jobs -> violation", validate_text("run_id: x") != [])
    expect("not a mapping -> violation", validate({}) != [])
    try:
        import yaml as _yaml_probe  # noqa: F401
        _have_pyyaml = True
    except ImportError:
        _have_pyyaml = False
    if _have_pyyaml:
        # finding 53: an inner ": " in an unquoted scalar is refused by PyYAML;
        # the validator must report it, never consult the subset parser instead.
        _fifty_three = validate_text("run_id: x\njobs:\n- id: a\n  title: Task A: the scorer\n"
                                     "  write_allowed: [a.py]\n")
        expect("PyYAML-rejected manifest is a VIOLATION, not a subset-parser pass (%r)"
               % _fifty_three, len(_fifty_three) == 1 and "PyYAML rejected" in _fifty_three[0])

    # Fallback parser parity: force the embedded parser on the good manifest.
    parsed = _mini_yaml(GOOD_MANIFEST)
    fb = validate(parsed)
    expect("fallback parser: good manifest clean (%r)" % fb, fb == [])
    fb_bad = validate(_mini_yaml(BAD_MANIFEST))
    expect("fallback parser: bad manifest flagged", len(fb_bad) > 0)

    # ------------------------------------------------------------------ #
    # FIFTH REVIEW PASS (2026-09-02) — the fallback parser could not read
    # what safe_dump writes.
    #
    # Every manifest in this repo is `yaml.safe_dump` output, and safe_dump
    # produces two shapes the shipped subset parser had no rule for: a scalar
    # FOLDED across lines at `width`, and a block SEQUENCE at its parent key's
    # own indentation. Each one made `parse_map` break early, so everything
    # after it — `jobs:` included — was silently dropped. `hooks/lane-guard.sh`
    # loads a manifest through this very function on an interpreter without
    # PyYAML; it read "no jobs", resolved no lane, and allowed every out-of-lane
    # write. FOLDED_MANIFEST below is literal safe_dump(width=100) output.
    folded = _mini_yaml(FOLDED_MANIFEST)
    expect("fallback parser: a folded plain scalar is joined, not truncated",
           folded.get("feature") == FOLDED_FEATURE)
    expect("fallback parser: a folded list item is joined too",
           folded.get("acceptance_criteria") == [FOLDED_CRITERION])
    expect("fallback parser: the document SURVIVES the fold (jobs present)",
           [j.get("id") for j in (folded.get("jobs") or [])] == ["guard-honest"])
    expect("fallback parser: the folded job's write_allowed lane is exact — "
           "this is the value the lane guard enforces on",
           folded["jobs"][0].get("write_allowed")
           == ["hooks/lane-guard.sh", "tests/test-lane-guard.sh"])

    # A TRUNCATED PARSE IS NOT A MANIFEST WITH NO JOBS. Multi-line flow
    # sequences are outside this parser's subset, so it recovers no jobs from
    # this document — and it must SAY SO rather than hand back a jobless
    # mapping that every caller reads as "nothing to enforce".
    _flow_jobs = "run_id: x\njobs: [\n  {id: a}\n]\n"
    try:
        _mini_yaml(_flow_jobs)
        _truncation_raised = ""
    except ValueError as _exc:
        _truncation_raised = str(_exc)
    expect("fallback parser: a top-level `jobs:` that yields no jobs RAISES",
           "TRUNCATED, not empty" in _truncation_raised)
    expect("...and the error says what to do about it (PyYAML)",
           "PyYAML" in _truncation_raised)
    expect("an explicitly empty `jobs: []` is parsed faithfully, not rejected",
           _mini_yaml("run_id: x\njobs: []\n") == {"run_id": "x", "jobs": []})
    expect("a document with no top-level `jobs:` at all is untouched by the check",
           _mini_yaml("run_id: x\n") == {"run_id": "x"})

    # The fixture is only evidence if it really is what safe_dump writes. When
    # PyYAML is importable, re-dump it and compare byte for byte; the CI floor
    # job installs PyYAML, so this runs there.
    try:
        import yaml as _y
    except ImportError:  # pragma: no cover - exercised on a PyYAML-less box
        expect("safe_dump cross-check SKIPPED — no PyYAML on this interpreter",
               True)
    else:
        _redump = _y.safe_dump(_y.safe_load(FOLDED_MANIFEST), width=100,
                               sort_keys=False, allow_unicode=True,
                               default_flow_style=False)
        expect("the folded fixture IS safe_dump(width=100) output, byte for byte",
               _redump == FOLDED_MANIFEST)
        expect("the fallback parser agrees with PyYAML on the folded manifest",
               _y.safe_load(FOLDED_MANIFEST) == folded)

    # --- v3.0 Feature A2: the `triage` block, behind --require-triage ---
    # The flag ships DEFAULT OFF in EVERY mode. A mode-scoped default was tried and
    # removed as circular: the block is emitted by the fast-path materializer, so
    # defaulting it on for --mode pre-dispatch would red the e2e suite inside the very
    # task that adds the emitter. `/v:dispatch` passes the flag explicitly on every
    # dispatch; the CI historical sweep does not.
    import glob as _glob3
    import tempfile as _tf3

    _tax_mod3 = _sibling("compound-v-taxonomy.py")
    _tri_root = _tf3.mkdtemp(prefix="cv-v3-triage-")
    os.makedirs(os.path.join(_tri_root, ".claude"), exist_ok=True)
    _tri_tax = os.path.join(_tri_root, DEFAULT_TAXONOMY_REL)
    # SYNTHESIZED taxonomy bytes: `.claude/compound-v-impact-taxonomy.yaml` does not
    # exist in this repo yet (it is generated by /v:onboard draft-taxonomy), so the
    # digest check is proven against bytes we write here, never against a file whose
    # absence would make the test vacuous.
    with open(_tri_tax, "wb") as _fh3:
        _fh3.write(b"version: 1\npath_patterns:\n  - glob: 'scripts/**'\n"
                   b"    impact_band: high\n    difficulty_band: medium\n")
    _tri_digest = (_tax_mod3.taxonomy_digest_file(_tri_tax)
                   if _tax_mod3 is not None else "sha256:" + "0" * 64)

    # WITHOUT the flag: a manifest with NO triage block is valid (the bootstrap
    # exemption 3.0 legitimately takes once), and so is a malformed one.
    _t_absent = validate_text(_v3_manifest(), repo_root=_tri_root)
    expect("triage: absent block valid without --require-triage (%r)" % _t_absent,
           _t_absent == [])
    _t_bad_off = validate_text(_v3_manifest(_triage_block(_tri_digest, tier="MAYBE")),
                               repo_root=_tri_root)
    expect("triage: malformed block ignored without the flag (historical sweep stays green)",
           _t_bad_off == [])

    # WITH the flag: absent block FAILS.
    _t_missing = validate_text(_v3_manifest(), repo_root=_tri_root, require_triage=True)
    expect("triage: absent block caught under --require-triage",
           any("missing required top-level 'triage' block" in p for p in _t_missing))

    # WITH the flag: a well-formed, digest-matched block is VALID.
    _t_good = validate_text(_v3_manifest(_triage_block(_tri_digest)),
                            repo_root=_tri_root, require_triage=True)
    expect("triage: well-formed digest-matched block valid (%r)" % _t_good, _t_good == [])

    # Each tier in the enum is accepted; anything else is not.
    for _tier in VALID_TRIAGE_TIERS:
        _r = validate_text(_v3_manifest(_triage_block(_tri_digest, tier=_tier)),
                           repo_root=_tri_root, require_triage=True)
        expect("triage: tier %s accepted (%r)" % (_tier, _r), _r == [])
    _t_tier = validate_text(_v3_manifest(_triage_block(_tri_digest, tier="direct")),
                            repo_root=_tri_root, require_triage=True)
    expect("triage: out-of-enum tier caught (case-sensitive — 'direct' is not DIRECT)",
           any("triage.tier 'direct' invalid" in p for p in _t_tier))

    # Malformed shapes: a missing key, a non-mapping block, an unknown key.
    for _key in TRIAGE_REQUIRED_KEYS:
        _r = validate_text(_v3_manifest(_triage_block(_tri_digest, drop=_key)),
                           repo_root=_tri_root, require_triage=True)
        expect("triage: missing '%s' caught" % _key,
               any("triage missing required field '%s'" % _key in p for p in _r))
    _t_scalar = validate_text(_v3_manifest("triage: SCOPED\n"),
                              repo_root=_tri_root, require_triage=True)
    expect("triage: non-mapping block caught",
           any("'triage' must be a mapping" in p for p in _t_scalar))
    _t_unknown = validate_text(
        _v3_manifest(_triage_block(_tri_digest, extra="  taxonomy-digest: oops\n")),
        repo_root=_tri_root, require_triage=True)
    expect("triage: unknown key caught (a 'taxonomy-digest' typo must not pass silently)",
           any("triage has unknown key 'taxonomy-digest'" in p for p in _t_unknown))

    # pre_eval_id becomes a path segment (docs/superpowers/pre-eval/<id>.json).
    _t_trav = validate_text(_v3_manifest(_triage_block(_tri_digest,
                                                       pre_eval_id="../../etc/passwd")),
                            repo_root=_tri_root, require_triage=True)
    expect("triage: path-traversal pre_eval_id caught",
           any("triage.pre_eval_id" in p and "path segment" in p for p in _t_trav))

    # decided_at: ISO-8601. Python 3.9's fromisoformat rejects a trailing 'Z', which
    # every producer writes — the Zulu suffix is stripped, so the CI floor and a newer
    # local interpreter agree.
    _t_zulu = validate_text(
        _v3_manifest(_triage_block(_tri_digest, decided_at="2026-09-01T10:15:00Z")),
        repo_root=_tri_root, require_triage=True)
    expect("triage: Zulu-suffixed decided_at parses on the 3.9 floor (%r)" % _t_zulu,
           _t_zulu == [])
    _t_when = validate_text(
        _v3_manifest(_triage_block(_tri_digest, decided_at="last tuesday")),
        repo_root=_tri_root, require_triage=True)
    expect("triage: unparseable decided_at caught",
           any("triage.decided_at" in p and "ISO-8601" in p for p in _t_when))

    # taxonomy_digest: shape, mismatch, and an unreadable taxonomy all fail closed.
    _t_shape = validate_text(_v3_manifest(_triage_block(_tri_digest, )).replace(
        _tri_digest, "not-a-digest"), repo_root=_tri_root, require_triage=True)
    expect("triage: malformed taxonomy_digest shape caught",
           any("triage.taxonomy_digest" in p and "sha256:<64-hex>" in p
               for p in _t_shape))
    _t_mismatch = validate_text(
        _v3_manifest(_triage_block("sha256:" + "b" * 64)),
        repo_root=_tri_root, require_triage=True)
    expect("triage: taxonomy_digest mismatch caught (synthesized taxonomy bytes)",
           any("triage.taxonomy_digest" in p and "does not match the taxonomy on disk" in p
               for p in _t_mismatch))
    _t_notax = validate_text(_v3_manifest(_triage_block(_tri_digest)),
                             repo_root=os.path.join(_tri_root, "no-such-root"),
                             require_triage=True)
    expect("triage: absent taxonomy on disk fails closed (never a silent skip)",
           any("triage.taxonomy_digest" in p and "unreadable" in p for p in _t_notax))
    # This task: an ABSENT taxonomy (the common "never ran /v:onboard" case)
    # names the real producer so the failure is actionable, not just diagnosed.
    expect("triage: absent taxonomy names /v:onboard draft-taxonomy as the fix",
           any("triage.taxonomy_digest" in p and "does not exist" in p
               and "/v:onboard" in p and "draft-taxonomy" in p for p in _t_notax))
    # The verdict must not blur with the DIGEST-MISMATCH case (taxonomy exists,
    # disagrees) — that is a different, more serious situation (the record
    # outlived the rules) and must never suggest re-running /v:onboard, only
    # /v:triage against the taxonomy that is already there.
    expect("triage: mismatch case (file exists) is never given the /v:onboard hint",
           not any("/v:onboard" in p for p in _t_mismatch))
    expect("triage: mismatch case still points at /v:triage, unchanged",
           any("re-run /v:triage" in p for p in _t_mismatch))
    # A taxonomy that exists but is unreadable for a DIFFERENT reason (here: the
    # configured path is a directory, not a file) must fall through to the
    # generic "unreadable" message, unchanged — the /v:onboard hint is specific
    # to genuine absence, not a stand-in for every unreadable-taxonomy case.
    _tri_taxdir = os.path.join(_tri_root, "a-directory-not-a-file")
    os.makedirs(_tri_taxdir, exist_ok=True)
    _t_taxisdir = validate_text(_v3_manifest(_triage_block(_tri_digest)),
                                repo_root=_tri_root, require_triage=True,
                                taxonomy_path=_tri_taxdir)
    expect("triage: taxonomy path that is a directory fails closed, generically",
           any("triage.taxonomy_digest" in p and "is unreadable" in p
               and "does not exist" not in p and "/v:onboard" not in p
               for p in _t_taxisdir))
    # --taxonomy overrides the default location.
    _t_over = validate_text(_v3_manifest(_triage_block(_tri_digest)),
                            repo_root=os.path.join(_tri_root, "no-such-root"),
                            require_triage=True, taxonomy_path=_tri_tax)
    expect("triage: --taxonomy override verifies against the named file (%r)" % _t_over,
           _t_over == [])

    # Fallback-parser parity: the same defects are caught without PyYAML.
    expect("triage: fallback parser flags a mismatched digest",
           any("does not match the taxonomy on disk" in p
               for p in validate(_mini_yaml(_v3_manifest(
                   _triage_block("sha256:" + "c" * 64))),
                   repo_root=_tri_root, require_triage=True)))

    # --- v3.9.0: a null taxonomy_digest says what to do; config-disabled FULL is the
    # one record a null digest is accepted for. ---
    def _null_block(pid, tier="FULL", extra=""):
        return ("triage:\n  tier: %s\n  pre_eval_id: %s\n  taxonomy_digest: null\n"
                '  decided_at: "2026-10-21T09:00:00Z"\n%s' % (tier, pid, extra))

    _nd_root = _tf3.mkdtemp(prefix="cv-v386-nulldigest-")
    _t_nd = validate_text(_v3_manifest(_null_block("2026-10-21T090000Z-x-a1b2")),
                          repo_root=_nd_root, require_triage=True)
    expect("triage: null digest without a taxonomy names the file, /v:init, /v:onboard "
           "and the re-triage (%r)" % _t_nd,
           any("missing required field 'taxonomy_digest'" in p and DEFAULT_TAXONOMY_REL in p
               and "/v:init" in p and "/v:onboard" in p and "re-run /v:triage" in p
               for p in _t_nd))
    _t_nd2 = validate_text(_v3_manifest(_null_block("2026-10-21T090000Z-x-a1b2")),
                           repo_root=_tri_root, require_triage=True)
    expect("triage: null digest once the taxonomy exists says the record predates it",
           any("missing required field 'taxonomy_digest'" in p and "predates" in p
               and "re-run /v:triage" in p for p in _t_nd2))

    _pe = _sibling("compound-v-preeval.py")
    expect("triage: the disabled-record flag is spelled as the producer spells it",
           _pe is not None and _pe.DISABLED_BY_CONFIG_FLAG == TRIAGE_DISABLED_FLAG)
    _dis_root = _tf3.mkdtemp(prefix="cv-v386-disabled-")
    os.makedirs(os.path.join(_dis_root, ".claude"), exist_ok=True)
    _dis_cfg = os.path.join(_dis_root, ".claude", "compound-v.json")
    with open(_dis_cfg, "w") as _fh:
        _fh.write('{"pre_eval": {"enabled": false}}\n')
    _dres = _pe.triage_request("add a booking page", repo=_dis_root, session_id="s",
                               record_disabled=True) if _pe is not None else {}
    _dpid = _dres.get("pre_eval_id") or "2026-10-21T090000Z-missing-a1b2"
    _dis_ok = "  disabled_by_config: true\n"
    _t_dis = validate_text(_v3_manifest(_null_block(_dpid, extra=_dis_ok)),
                           repo_root=_dis_root, require_triage=True)
    expect("triage: a config-disabled FULL record is accepted while disabled (%r)" % _t_dis,
           _t_dis == [])
    expect("triage: fallback parser agrees on the config-disabled block",
           validate(_mini_yaml(_v3_manifest(_null_block(_dpid, extra=_dis_ok))),
                    repo_root=_dis_root, require_triage=True) == [])
    _t_dis_tier = validate_text(_v3_manifest(_null_block(_dpid, tier="SCOPED",
                                                         extra=_dis_ok)),
                                repo_root=_dis_root, require_triage=True)
    expect("triage: config-disabled with a tier other than FULL is refused",
           any("requires tier FULL" in p for p in _t_dis_tier))
    _t_dis_dig = validate_text(_v3_manifest(_triage_block(_tri_digest, tier="FULL",
                                                          pre_eval_id=_dpid,
                                                          extra=_dis_ok)),
                               repo_root=_dis_root, require_triage=True)
    expect("triage: config-disabled with a non-null digest is refused",
           any("requires a null taxonomy_digest" in p for p in _t_dis_dig))
    _t_dis_norec = validate_text(_v3_manifest(_null_block("2026-10-21T090000Z-none-a1b2",
                                                          extra=_dis_ok)),
                                 repo_root=_dis_root, require_triage=True)
    expect("triage: config-disabled without the committed record is refused",
           any("could not be read" in p for p in _t_dis_norec))
    _t_dis_bad = validate_text(_v3_manifest(_null_block(_dpid, extra=(
        "  disabled_by_config: \"yes\"\n"))), repo_root=_dis_root, require_triage=True)
    expect("triage: disabled_by_config must be literally true",
           any("must be true when present" in p for p in _t_dis_bad))
    _drec_path = os.path.join(_dis_root, PRE_EVAL_DIR_REL, _dpid + ".json")
    _drec_bytes = open(_drec_path, "rb").read() if os.path.isfile(_drec_path) else b"{}"
    _drec = json.loads(_drec_bytes.decode("utf-8"))
    with open(_drec_path, "w") as _fh:
        json.dump(dict(_drec, localization=dict(_drec.get("localization") or {}, flags=[])),
                  _fh)
    _t_dis_plain = validate_text(_v3_manifest(_null_block(_dpid, extra=_dis_ok)),
                                 repo_root=_dis_root, require_triage=True)
    expect("triage: an ordinary null-digest FULL record cannot claim config-disabled",
           any("is not a config-disabled FULL record" in p for p in _t_dis_plain)
           and any("fails its own digest" in p for p in _t_dis_plain))
    with open(_drec_path, "wb") as _fh:
        _fh.write(_drec_bytes)
    with open(_dis_cfg, "w") as _fh:
        _fh.write('{"pre_eval": {"enabled": true}}\n')
    _t_dis_on = validate_text(_v3_manifest(_null_block(_dpid, extra=_dis_ok)),
                              repo_root=_dis_root, require_triage=True)
    expect("triage: the config-disabled record is refused once pre_eval is enabled again",
           any("pre_eval.enabled is not false" in p for p in _t_dis_on))
    os.remove(_dis_cfg)
    _t_dis_nocfg = validate_text(_v3_manifest(_null_block(_dpid, extra=_dis_ok)),
                                 repo_root=_dis_root, require_triage=True)
    expect("triage: no project config means the stage is on — refused",
           any("pre_eval.enabled is not false" in p for p in _t_dis_nocfg))
    import shutil as _shutil_386
    _shutil_386.rmtree(_nd_root, ignore_errors=True)
    _shutil_386.rmtree(_dis_root, ignore_errors=True)

    # --- v3.4.1: triage.flavor scoped_plus + the cross-model receipt ---
    # SCOPED+ is the band that says "small edit, sensitive path". It buys back the
    # two reviews plain SCOPED skips, and the validator refuses to take either on
    # trust: the deep in-harness reviewer is DECLARED in the manifest, so it is
    # checked before dispatch; the cross-model second opinion is EVIDENCE that does
    # not exist yet at that point, so it is checked afterwards, from its receipt.
    _DEEP_REVIEW_JOB = """  - id: review-v3
    title: "Review Gate"
    type: review
    backend: claude
    tier: deep
    effort: high
    isolation: direct
    run: serial
    depends_on: [task-1-v3]
    write_allowed: [docs/superpowers/dogfood/**]
    read_allowed: ["**"]
    acceptance: ["verdict written"]
"""
    _SP = "  flavor: scoped_plus\n"

    # 1. scoped_plus WITHOUT the deep Claude review job → violation naming the rule.
    _f_bare = validate_text(_v3_manifest(_triage_block(_tri_digest, extra=_SP)),
                            repo_root=_tri_root, require_triage=True)
    expect("triage.flavor: scoped_plus without a deep Claude review job is refused",
           any("scoped_plus' requires a review job" in p for p in _f_bare))

    # 2. WITH it → valid. The job is type/tier/backend-declared, never guessed from
    #    prose: a standard-tier one does not satisfy the rule.
    _f_ok = validate_text(
        _v3_manifest(_triage_block(_tri_digest, extra=_SP)) + _DEEP_REVIEW_JOB,
        repo_root=_tri_root, require_triage=True)
    expect("triage.flavor: scoped_plus with a deep Claude review job is valid (%r)"
           % _f_ok, _f_ok == [])
    _f_shallow = validate_text(
        _v3_manifest(_triage_block(_tri_digest, extra=_SP))
        + _DEEP_REVIEW_JOB.replace("tier: deep", "tier: standard"),
        repo_root=_tri_root, require_triage=True)
    expect("triage.flavor: a standard-tier review job does not satisfy the rule",
           any("scoped_plus' requires a review job" in p for p in _f_shallow))

    # 3. An out-of-enum flavor is a violation — flavor is a band, not free text.
    _f_bad = validate_text(
        _v3_manifest(_triage_block(_tri_digest, extra="  flavor: spicy\n")),
        repo_root=_tri_root, require_triage=True)
    expect("triage.flavor: unknown value caught",
           any("triage.flavor 'spicy' invalid" in p for p in _f_bad))
    # ...and `flavor` is ALLOWED rather than merely tolerated: an absent flavor stays
    # valid, and a near-miss key still fails the unknown-key walk.
    expect("triage: absent flavor stays valid (the key is optional)",
           validate_text(_v3_manifest(_triage_block(_tri_digest)),
                         repo_root=_tri_root, require_triage=True) == [])
    expect("triage: 'flavour' is still an unknown key (the walk reads ALLOWED_KEYS)",
           any("unknown key 'flavour'" in p for p in validate_text(
               _v3_manifest(_triage_block(_tri_digest,
                                          extra="  flavour: scoped_plus\n")),
               repo_root=_tri_root, require_triage=True)))

    # 4/5. --require-cross-model-receipt: the SCOPED+ second opinion, verified from
    # the file rather than believed. The receipt is sealed with the SAME shared
    # primitive the producer seals it with, so an edit after sealing is detectable.
    _cm_manifest = (_v3_manifest(_triage_block(_tri_digest, extra=_SP))
                    + _DEEP_REVIEW_JOB)
    _cm_dir = _tf3.mkdtemp(prefix="cv-cross-model-")

    def _cm_write(name, **over):
        body = {
            "run_id": "2026-09-01-v3",
            "pre_eval_id": "2026-09-01T101500Z-v3-a1b2",
            "diff_digest": "sha256:" + "a" * 64,
            "reviewer_backend": "codex",
            "reviewer_model": "gpt-5.6-sol",
            "cross_model": True,
            "produced_at": "2026-09-03T04:00:00Z",
            "review": {
                "verdict": "concerns",
                "summary": "One real objection, one blind spot checked.",
                "findings": [],
                "blind_spots_checked": ["partition disjointness"],
            },
        }
        body.update(over)
        if _tax_mod3 is not None:
            body["digest"] = _tax_mod3.record_digest(body, exclude_field="digest")
        full = os.path.join(_cm_dir, name)
        with open(full, "w", encoding="utf-8") as _fh:
            json.dump(body, _fh)
        return full

    _cm_good = _cm_write("good.json")
    _r_good = validate_text(_cm_manifest, repo_root=_tri_root, require_triage=True,
                            cross_model_receipt=_cm_good)
    expect("cross-model-receipt: a sealed, bound receipt validates (%r)" % _r_good,
           _r_good == [])
    # An advisory 'concerns' verdict is NOT a violation — the orchestrator arbitrates.
    expect("cross-model-receipt: a 'concerns' verdict is advisory, not a violation",
           not any("verdict" in p for p in _r_good))

    _r_absent = validate_text(_cm_manifest, repo_root=_tri_root, require_triage=True,
                              cross_model_receipt=os.path.join(_cm_dir, "nope.json"))
    expect("cross-model-receipt: a MISSING receipt fails closed",
           any("could not be read" in p for p in _r_absent))

    # Tampered after sealing: the bytes changed, the self-digest did not.
    _cm_tampered = os.path.join(_cm_dir, "tampered.json")
    with open(_cm_good, "r", encoding="utf-8") as _fh:
        _t_obj = json.load(_fh)
    _t_obj["diff_digest"] = "sha256:" + "b" * 64
    with open(_cm_tampered, "w", encoding="utf-8") as _fh:
        json.dump(_t_obj, _fh)
    _r_tamper = validate_text(_cm_manifest, repo_root=_tri_root, require_triage=True,
                              cross_model_receipt=_cm_tampered)
    expect("cross-model-receipt: self-digest mismatch caught (edited after sealing)",
           any("self-digest mismatch" in p for p in _r_tamper))

    # A sealed receipt over a DIFFERENT diff than the one the caller handed the
    # reviewer — the stale-replay case --expected-diff-digest exists for.
    _r_stale = validate_text(_cm_manifest, repo_root=_tri_root, require_triage=True,
                             cross_model_receipt=_cm_good,
                             expected_diff_digest="sha256:" + "c" * 64)
    expect("cross-model-receipt: diff_digest != the sealed patch caught (stale replay)",
           any("stale-replay" in p for p in _r_stale))

    # The three binding fields, each independently.
    _r_run = validate_text(_cm_manifest, repo_root=_tri_root, require_triage=True,
                           cross_model_receipt=_cm_write("wrongrun.json",
                                                         run_id="2026-01-01-other"))
    expect("cross-model-receipt: run_id binding enforced",
           any("run_id '2026-01-01-other' != manifest run_id" in p for p in _r_run))
    _r_pid = validate_text(_cm_manifest, repo_root=_tri_root, require_triage=True,
                           cross_model_receipt=_cm_write("wrongpid.json",
                                                         pre_eval_id="someone-elses"))
    expect("cross-model-receipt: pre_eval_id binding enforced",
           any("pre_eval_id 'someone-elses' !=" in p for p in _r_pid))
    _r_dd = validate_text(_cm_manifest, repo_root=_tri_root, require_triage=True,
                          cross_model_receipt=_cm_write("baddigest.json",
                                                        diff_digest="deadbeef"))
    expect("cross-model-receipt: malformed diff_digest caught",
           any("diff_digest 'deadbeef' is malformed" in p for p in _r_dd))

    # Schema shape: an unrecognised reviewer_backend is refused (enum), and an
    # unknown envelope field is a violation (additionalProperties: false).
    _r_fam = validate_text(_cm_manifest, repo_root=_tri_root, require_triage=True,
                           cross_model_receipt=_cm_write("claudereview.json",
                                                         reviewer_backend="claude"))
    expect("cross-model-receipt: an unrecognised reviewer_backend is refused",
           any("reviewer_backend must be one of" in p for p in _r_fam))

    # v3.6: reviewer_backend 'claude-advisor' beside 'codex', gated by `cross_model`.
    _r_advisor_ok = validate_text(
        _cm_manifest, repo_root=_tri_root, require_triage=True,
        cross_model_receipt=_cm_write("advisor-ok.json",
                                      reviewer_backend="claude-advisor",
                                      reviewer_model="claude-opus-4-5",
                                      cross_model=False))
    expect("cross-model-receipt: claude-advisor + cross_model:false is ACCEPTED "
           "(%r)" % _r_advisor_ok, _r_advisor_ok == [])
    expect("cross-model-receipt: claude-advisor + cross_model:false WARNs "
           "SECOND_OPINION_SAME_FAMILY",
           any("same-family" in w
               for w in cross_model_receipt_advisories(
                   {"reviewer_backend": "claude-advisor", "cross_model": False})))
    expect("cross-model-receipt: codex + cross_model:true never warns "
           "SECOND_OPINION_SAME_FAMILY",
           cross_model_receipt_advisories(
               {"reviewer_backend": "codex", "cross_model": True}) == [])

    _r_advisor_lie = validate_text(
        _cm_manifest, repo_root=_tri_root, require_triage=True,
        cross_model_receipt=_cm_write("advisor-lie.json",
                                      reviewer_backend="claude-advisor",
                                      reviewer_model="claude-opus-4-5",
                                      cross_model=True))
    expect("cross-model-receipt: claude-advisor + cross_model:true is REFUSED "
           "(disagreement)",
           any("disagrees with reviewer_backend" in p for p in _r_advisor_lie))

    _r_codex_lie = validate_text(
        _cm_manifest, repo_root=_tri_root, require_triage=True,
        cross_model_receipt=_cm_write("codex-lie.json", cross_model=False))
    expect("cross-model-receipt: codex + cross_model:false is REFUSED "
           "(disagreement)",
           any("disagrees with reviewer_backend" in p for p in _r_codex_lie))

    _r_unknown_backend = validate_text(
        _cm_manifest, repo_root=_tri_root, require_triage=True,
        cross_model_receipt=_cm_write("unknown-backend.json",
                                      reviewer_backend="gemini",
                                      cross_model=True))
    expect("cross-model-receipt: an unknown backend ('gemini') is refused",
           any("reviewer_backend must be one of" in p for p in _r_unknown_backend))
    _r_extra = validate_text(_cm_manifest, repo_root=_tri_root, require_triage=True,
                             cross_model_receipt=_cm_write("extra.json", note="hi"))
    expect("cross-model-receipt: unknown envelope field caught",
           any("unknown field 'note'" in p for p in _r_extra))
    # The NESTED review is checked against schemas/plan-review.schema.json.
    _r_review = validate_text(
        _cm_manifest, repo_root=_tri_root, require_triage=True,
        cross_model_receipt=_cm_write("badreview.json",
                                      review={"verdict": "lgtm", "summary": "s",
                                              "findings": [],
                                              "blind_spots_checked": []}))
    expect("cross-model-receipt: the nested review is validated against plan-review",
           any("receipt.review.verdict" in p for p in _r_review))

    # --- v3.0 Feature B2: test_contract + per-job test_scope ---
    # Both are OPTIONAL and unflagged: absent ⇒ `test_scope: full`, which is what every
    # manifest committed before 3.0 relies on.
    _CONTRACT_OK = ('test_contract:\n'
                    '  floor_command: "bash tests/test-epic-goal-stop.sh"\n'
                    '  full_command: "bash scripts/run-all-tests.sh"\n'
                    '  impacted_map:\n'
                    '    - when: "scripts/compound-v-*.py"\n'
                    '      run: "python3 {path} --selftest"\n')
    expect("test_contract: absent block + absent test_scope stays valid",
           validate_text(_v3_manifest()) == [])
    _c_ok = validate_text(_v3_manifest(contract_block=_CONTRACT_OK,
                                       job_line="    test_scope: impacted\n"))
    expect("test_contract: well-formed contract + test_scope: impacted valid (%r)" % _c_ok,
           _c_ok == [])
    for _sc in VALID_TEST_SCOPES:
        _r = validate_text(_v3_manifest(contract_block=_CONTRACT_OK,
                                        job_line="    test_scope: %s\n" % _sc))
        expect("test_contract: test_scope %s accepted (%r)" % (_sc, _r), _r == [])
    _c_enum = validate_text(_v3_manifest(contract_block=_CONTRACT_OK,
                                         job_line="    test_scope: some\n"))
    expect("test_contract: out-of-enum test_scope caught",
           any("test_scope 'some' invalid" in p for p in _c_enum))

    # impacted_map entries: `when` and `run` are both mandatory.
    _c_nowhen = validate_text(_v3_manifest(contract_block=(
        'test_contract:\n  floor_command: "f"\n  full_command: "F"\n'
        '  impacted_map:\n    - run: "python3 {path} --selftest"\n')))
    expect("test_contract: impacted_map entry without 'when' caught",
           any("impacted_map[0] missing required field 'when'" in p for p in _c_nowhen))
    _c_norun = validate_text(_v3_manifest(contract_block=(
        'test_contract:\n  floor_command: "f"\n  full_command: "F"\n'
        '  impacted_map:\n    - when: "scripts/*.py"\n')))
    expect("test_contract: impacted_map entry without 'run' caught",
           any("impacted_map[0] missing required field 'run'" in p for p in _c_norun))
    _c_scalar = validate_text(_v3_manifest(contract_block=(
        'test_contract:\n  floor_command: "f"\n  full_command: "F"\n'
        '  impacted_map:\n    - "scripts/*.py"\n')))
    expect("test_contract: non-mapping impacted_map entry caught",
           any("impacted_map[0] must be a mapping" in p for p in _c_scalar))
    _c_mapkeys = validate_text(_v3_manifest(contract_block=(
        'test_contract:\n  floor_command: "f"\n  full_command: "F"\n'
        '  impacted_map:\n    - when: "scripts/*.py"\n      run: "x"\n      why: "y"\n')))
    expect("test_contract: unknown impacted_map key caught",
           any("impacted_map[0] has unknown key 'why'" in p for p in _c_mapkeys))
    _c_maplist = validate_text(_v3_manifest(contract_block=(
        'test_contract:\n  floor_command: "f"\n  full_command: "F"\n'
        '  impacted_map: "scripts/*.py"\n')))
    expect("test_contract: non-list impacted_map caught",
           any("test_contract.impacted_map must be a list" in p for p in _c_maplist))
    _c_notmap = validate_text(_v3_manifest(contract_block='test_contract: "pytest"\n'))
    expect("test_contract: non-mapping test_contract caught",
           any("'test_contract' must be a mapping" in p for p in _c_notmap))
    _c_unknown = validate_text(_v3_manifest(contract_block=(
        'test_contract:\n  floor_command: "f"\n  full_command: "F"\n  floor_cmd: "f"\n')))
    expect("test_contract: unknown test_contract key caught",
           any("test_contract has unknown key 'floor_cmd'" in p for p in _c_unknown))

    # timeout_s: an optional bound on how long test_contract commands may run.
    _c_timeout_ok = validate_text(_v3_manifest(contract_block=(
        'test_contract:\n  floor_command: "f"\n  full_command: "F"\n'
        '  timeout_s: 480\n')))
    expect("test_contract: timeout_s 480 accepted (%r)" % _c_timeout_ok,
           _c_timeout_ok == [])
    for _bad_timeout in (0, -1, 541, "true", "480"):
        _tval_yaml = ('"%s"' % _bad_timeout if isinstance(_bad_timeout, str)
                      else str(_bad_timeout))
        _c_timeout_bad = validate_text(_v3_manifest(contract_block=(
            'test_contract:\n  floor_command: "f"\n  full_command: "F"\n'
            '  timeout_s: %s\n' % _tval_yaml)))
        expect("test_contract: timeout_s %r refused (%r)"
               % (_bad_timeout, _c_timeout_bad),
               any("test_contract.timeout_s must be an integer" in p
                   for p in _c_timeout_bad))
    _c_timeout_true = validate_text(_v3_manifest(contract_block=(
        'test_contract:\n  floor_command: "f"\n  full_command: "F"\n'
        '  timeout_s: true\n')))
    expect("test_contract: timeout_s true (bool) refused (%r)" % _c_timeout_true,
           any("test_contract.timeout_s must be an integer" in p
               for p in _c_timeout_true))

    # floor_only must never resolve to running NOTHING — the whole point of a floor.
    _c_floor_empty = validate_text(_v3_manifest(
        contract_block='test_contract:\n  floor_command: ""\n  full_command: "F"\n',
        job_line="    test_scope: floor_only\n"))
    expect("test_contract: floor_only with an EMPTY floor_command caught",
           any("floor_only" in p and "floor_command" in p for p in _c_floor_empty))
    _c_floor_absent = validate_text(_v3_manifest(
        job_line="    test_scope: floor_only\n"))
    expect("test_contract: floor_only with NO test_contract at all caught",
           any("floor_only" in p and "floor_command" in p for p in _c_floor_absent))
    _c_floor_ok = validate_text(_v3_manifest(
        contract_block='test_contract:\n  floor_command: "bash tests/x.sh"\n'
                       '  full_command: "F"\n',
        job_line="    test_scope: floor_only\n"))
    expect("test_contract: floor_only with a real floor_command valid (%r)" % _c_floor_ok,
           _c_floor_ok == [])
    # An unmapped path resolves to full_command, so `impacted` needs one to exist.
    _c_imp_nofull = validate_text(_v3_manifest(
        contract_block='test_contract:\n  floor_command: "f"\n',
        job_line="    test_scope: impacted\n"))
    expect("test_contract: impacted without a full_command caught (unmapped ⇒ full)",
           any("impacted" in p and "full_command" in p for p in _c_imp_nofull))

    # Fallback-parser parity for the contract half.
    expect("test_contract: fallback parser flags a floor_only with no floor_command",
           any("floor_only" in p for p in validate(_mini_yaml(_v3_manifest(
               job_line="    test_scope: floor_only\n")))))

    # --- v3.4.8 Task B: top-level `retry` block ---
    _r_absent = validate_text(_v3_manifest())
    expect("retry: absent block stays valid (%r)" % _r_absent, _r_absent == [])

    _r_ok = validate_text(_v3_manifest(
        retry_block="retry:\n  max_attempts: 2\n  escalate_reviewer: true\n"))
    expect("retry: well-formed block valid (%r)" % _r_ok, _r_ok == [])

    for _ma in (1, 2, 3):
        _r_ma_ok = validate_text(_v3_manifest(
            retry_block="retry:\n  max_attempts: %d\n" % _ma))
        expect("retry: max_attempts %d accepted (%r)" % (_ma, _r_ma_ok),
               _r_ma_ok == [])

    for _bad_ma in (0, 4, "3", -1):
        _ma_yaml = '"%s"' % _bad_ma if isinstance(_bad_ma, str) else str(_bad_ma)
        _r_ma_bad = validate_text(_v3_manifest(
            retry_block="retry:\n  max_attempts: %s\n" % _ma_yaml))
        expect("retry: max_attempts %r refused (%r)" % (_bad_ma, _r_ma_bad),
               any("retry.max_attempts must be an integer between 1 and 3" in p
                   for p in _r_ma_bad))

    _r_ma_bool = validate_text(_v3_manifest(
        retry_block="retry:\n  max_attempts: true\n"))
    expect("retry: max_attempts true (bool) refused (%r)" % _r_ma_bool,
           any("retry.max_attempts must be an integer between 1 and 3" in p
               for p in _r_ma_bool))

    for _er_bad in (1, "true", "yes"):
        _er_yaml = '"%s"' % _er_bad if isinstance(_er_bad, str) else str(_er_bad)
        _r_er_bad = validate_text(_v3_manifest(
            retry_block="retry:\n  escalate_reviewer: %s\n" % _er_yaml))
        expect("retry: escalate_reviewer %r refused (%r)" % (_er_bad, _r_er_bad),
               any("retry.escalate_reviewer must be a boolean" in p
                   for p in _r_er_bad))

    _r_er_ok = validate_text(_v3_manifest(
        retry_block="retry:\n  escalate_reviewer: false\n"))
    expect("retry: escalate_reviewer false accepted (%r)" % _r_er_ok, _r_er_ok == [])

    _r_unknown = validate_text(_v3_manifest(
        retry_block="retry:\n  max_attempts: 1\n  giveup: true\n"))
    expect("retry: unknown key caught (%r)" % _r_unknown,
           any("retry has unknown key 'giveup'" in p for p in _r_unknown))

    _r_notmap = validate_text(_v3_manifest(retry_block='retry: "twice"\n'))
    expect("retry: non-mapping retry caught (%r)" % _r_notmap,
           any("'retry' must be a mapping" in p for p in _r_notmap))

    # Fallback-parser parity for retry.
    _r_fallback = validate(_mini_yaml(_v3_manifest(
        retry_block="retry:\n  max_attempts: 5\n")))
    expect("retry: fallback parser flags an out-of-range max_attempts",
           any("retry.max_attempts must be an integer between 1 and 3" in p
               for p in _r_fallback))

    # --- v3.4.17: `global_constraints` + per-job `interfaces` ---------------- #
    # The two fields Superpowers 6.2.0's writing-plans added for isolated
    # implementers. ABSENT-VALID is the first row and the load-bearing one: every
    # manifest materialized from a pre-6.2.0 plan carries neither key.
    _gc_absent = validate_text(_v3_manifest())
    expect("6.2.0 fields: both absent stays valid (%r)" % _gc_absent,
           _gc_absent == [])

    _GC_OK = ('global_constraints:\n'
              '  - "Python 3.9-safe, stdlib only"\n'
              '  - "No new runtime dependency"\n')
    _IFACE_OK = ('    interfaces:\n'
                 '      consumes:\n'
                 '        - "load_yaml(text) -> dict"\n'
                 '      produces:\n'
                 '        - "validate(manifest) -> list[str]"\n')

    _gc_ok = validate_text(_v3_manifest(constraints_block=_GC_OK,
                                        job_line=_IFACE_OK))
    expect("6.2.0 fields: both present and well-formed valid (%r)" % _gc_ok,
           _gc_ok == [])

    _gc_only = validate_text(_v3_manifest(constraints_block=_GC_OK))
    expect("global_constraints: alone (no interfaces) valid (%r)" % _gc_only,
           _gc_only == [])

    _if_only = validate_text(_v3_manifest(job_line=_IFACE_OK))
    expect("interfaces: alone (no global_constraints) valid (%r)" % _if_only,
           _if_only == [])

    # Either interfaces key may be absent: a first task consumes nothing, a last
    # task produces nothing anyone else reads.
    for _half, _yaml_half in (
            ("consumes only",
             '    interfaces:\n      consumes:\n        - "f(x) -> y"\n'),
            ("produces only",
             '    interfaces:\n      produces:\n        - "g(x) -> y"\n'),
            ("empty mapping", '    interfaces: {}\n')):
        _if_half = validate_text(_v3_manifest(job_line=_yaml_half))
        expect("interfaces: %s accepted (%r)" % (_half, _if_half),
               _if_half == [])

    # An empty list is the absent case written longhand — not a violation.
    _gc_empty = validate_text(_v3_manifest(
        constraints_block="global_constraints: []\n"))
    expect("global_constraints: empty list accepted (%r)" % _gc_empty,
           _gc_empty == [])

    # A NULL VALUE IS NOT ABSENT (cross-model review r1, finding 6). A bare
    # `global_constraints:` / `interfaces:` / `consumes:` line parses to None in
    # BOTH parsers (verified), and reading that as "absent" let a materializer
    # write the key, fail to fill it, and validate clean — with every implementer
    # prompt silently losing the field. Only a MISSING key is absent.
    _gc_null = validate_text(_v3_manifest(
        constraints_block="global_constraints:\n"))
    expect("global_constraints: explicit null REFUSED, not read as absent (%r)"
           % _gc_null,
           any("'global_constraints' must be a list of strings" in p
               for p in _gc_null))

    _if_null = validate_text(_v3_manifest(job_line="    interfaces:\n"))
    expect("interfaces: explicit null REFUSED, not read as absent (%r)" % _if_null,
           any("interfaces must be a mapping with keys consumes/produces" in p
               for p in _if_null))

    for _nk in ("consumes", "produces"):
        _if_knull = validate_text(_v3_manifest(
            job_line="    interfaces:\n      %s:\n" % _nk))
        expect("interfaces.%s: explicit null REFUSED (%r)" % (_nk, _if_knull),
               any("interfaces.%s must be a list of strings" % _nk in p
                   for p in _if_knull))

    # Fallback-parser parity for the null case: the subset parser yields None for
    # a bare key too, so the machine WITHOUT PyYAML must refuse it identically.
    _gc_null_fb = validate(_mini_yaml(_v3_manifest(
        constraints_block="global_constraints:\n",
        job_line="    interfaces:\n      consumes:\n")))
    expect("null values: fallback parser refuses both, same messages",
           any("'global_constraints' must be a list of strings" in p
               for p in _gc_null_fb)
           and any("interfaces.consumes must be a list of strings" in p
                   for p in _gc_null_fb))

    # Wrong SHAPES, each with its own message.
    _gc_scalar = validate_text(_v3_manifest(
        constraints_block='global_constraints: "stdlib only"\n'))
    expect("global_constraints: scalar refused (%r)" % _gc_scalar,
           any("'global_constraints' must be a list of strings" in p
               for p in _gc_scalar))

    _gc_map = validate_text(_v3_manifest(
        constraints_block="global_constraints:\n  python: \"3.9\"\n"))
    expect("global_constraints: mapping refused (%r)" % _gc_map,
           any("'global_constraints' must be a list of strings" in p
               for p in _gc_map))

    for _bad_item, _bad_yaml in (("empty string", '  - ""\n'),
                                 ("boolean", "  - true\n"),
                                 ("integer", "  - 39\n")):
        _gc_bad = validate_text(_v3_manifest(
            constraints_block="global_constraints:\n" + _bad_yaml))
        expect("global_constraints: %s entry refused (%r)" % (_bad_item, _gc_bad),
               any("'global_constraints'[0] must be a non-empty string" in p
                   for p in _gc_bad))

    _if_scalar = validate_text(_v3_manifest(
        job_line='    interfaces: "consumes load_yaml"\n'))
    expect("interfaces: scalar refused (%r)" % _if_scalar,
           any("interfaces must be a mapping with keys consumes/produces" in p
               for p in _if_scalar))

    _if_list = validate_text(_v3_manifest(
        job_line='    interfaces:\n      - "load_yaml(text)"\n'))
    expect("interfaces: list refused (%r)" % _if_list,
           any("interfaces must be a mapping with keys consumes/produces" in p
               for p in _if_list))

    _if_unknown = validate_text(_v3_manifest(
        job_line='    interfaces:\n      requires:\n        - "load_yaml"\n'))
    expect("interfaces: unknown key caught (%r)" % _if_unknown,
           any("interfaces has unknown key 'requires'" in p
               for p in _if_unknown))

    _if_str = validate_text(_v3_manifest(
        job_line='    interfaces:\n      consumes: "load_yaml(text)"\n'))
    expect("interfaces: string-valued consumes refused (%r)" % _if_str,
           any("interfaces.consumes must be a list of strings" in p
               for p in _if_str))

    _if_blank = validate_text(_v3_manifest(
        job_line='    interfaces:\n      produces:\n        - ""\n'))
    expect("interfaces: blank produces entry refused (%r)" % _if_blank,
           any("interfaces.produces[0] must be a non-empty string" in p
               for p in _if_blank))

    # Fallback-parser parity for both fields (the machine WITHOUT PyYAML).
    _gc_fb = validate(_mini_yaml(_v3_manifest(constraints_block=_GC_OK,
                                              job_line=_IFACE_OK)))
    expect("6.2.0 fields: fallback parser accepts both (%r)" % _gc_fb,
           _gc_fb == [])
    _gc_fb_bad = validate(_mini_yaml(_v3_manifest(
        job_line='    interfaces:\n      requires:\n        - "x"\n')))
    expect("6.2.0 fields: fallback parser flags an unknown interfaces key",
           any("interfaces has unknown key 'requires'" in p
               for p in _gc_fb_bad))

    # The committed audit trail: every run manifest + the shipped example must still
    # validate WITHOUT the flag. This is the bootstrap exemption, and it is only honest
    # because /v:dispatch passes --require-triage on every live dispatch.
    _repo3 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _hist = sorted(_glob3.glob(os.path.join(_repo3, "docs", "superpowers", "execution",
                                          "*", "manifest.yaml")))
    _hist.append(os.path.join(_repo3, "examples", "manifest.example.yaml"))
    for _hm in _hist:
        if not os.path.isfile(_hm):
            continue
        with open(_hm, "r", encoding="utf-8") as _fh:
            _hp = validate_text(_fh.read(), repo_root=_repo3)
        expect("committed manifest validates without --require-triage: %s (%r)"
               % (os.path.basename(os.path.dirname(_hm)), _hp), _hp == [])

    # --- ADVISORIES: the memory-only lane (v3.5.0, Codex round-1 #8) -----------
    # A job whose whole lane is agent memory is refused as `no_work` the moment the
    # agent has nothing durable to save, which pressures it to invent an entry. The
    # advisory says so; it must NEVER become a violation, because pairing the glob
    # with a real output lane is the author's call, not the validator's.
    def _lane(*globs):
        return _v3_manifest().replace(
            "write_allowed: [src/features/**]",
            "write_allowed: [%s]" % ", ".join(globs))

    # Namespaced form (`superpowers-v-<agent>`) is the recommended shape, so it is
    # the "clean" baseline used below for cases that assert NO advisory fires for
    # a reason unrelated to namespacing.
    _mem_only = _lane('".claude/agent-memory/superpowers-v-spec-reviewer/**"')
    _mem_msgs = advisories_text(_mem_only)
    expect("advisory: a memory-only lane warns", len(_mem_msgs) == 1)
    # Bound-checked on purpose: a regressed detector must FAIL this row, not raise
    # an IndexError that ends the whole selftest before the later rows ever run.
    expect("advisory: the warning names the job and the remedy",
           bool(_mem_msgs) and all(s in _mem_msgs[0] for s in
                                   ("task-1-v3", "memory-only lane", "no_work",
                                    "pair the memory glob", "write_allowed: []")))
    # THE contract: advisory ≠ violation. Same manifest, still valid.
    expect("advisory: a memory-only lane does NOT change the verdict",
           validate_text(_mem_only) == [])
    expect("advisory: memory glob + a real output lane does NOT warn",
           advisories_text(_lane('".claude/agent-memory/superpowers-v-spec-reviewer/**"',
                                 '"docs/superpowers/dogfood/r-1.md"')) == [])
    expect("advisory: an empty write_allowed does NOT warn",
           advisories_text(_lane()) == [])
    expect("advisory: an ordinary code lane does NOT warn",
           advisories_text(_lane('"src/**"')) == [])
    # `in any form`: a detector that knows one spelling detects nothing.
    for _form in ('"./.claude/agent-memory/superpowers-v-spec-reviewer/**"',
                  '".claude/agent-memory/superpowers-v-spec-reviewer"',
                  '".claude/agent-memory-local/spec-reviewer/**"',
                  '"/.claude/agent-memory/superpowers-v-spec-reviewer/MEMORY.md"'):
        expect("advisory: memory-only lane detected as %s" % _form,
               len(advisories_text(_lane(_form))) == 1)
    expect("advisory: a look-alike path outside the memory roots does NOT warn",
           advisories_text(_lane('".claude/agent-memoryX/spec-reviewer/**"')) == [])
    expect("advisory: an unparseable manifest yields no advisory, only violations",
           advisories_text("\tnot: [valid") == [])

    # --- ADVISORIES: MEMORY_LANE_UNNAMESPACED (v3.6) --------------------------
    # A bare (non-namespaced) project-scope memory lane collides with another
    # plugin's memory-bearing agent of the same name; the namespaced form does
    # not. Independent of whether the lane is paired with a real output lane.
    for _bare in ('"./.claude/agent-memory/spec-reviewer/**"',
                  '".claude/agent-memory/spec-reviewer"',
                  '"/.claude/agent-memory/spec-reviewer/MEMORY.md"'):
        _u_msgs = advisories_text(
            _lane(_bare, '"docs/superpowers/dogfood/r-1.md"'))
        expect("advisory: bare memory lane %s raises MEMORY_LANE_UNNAMESPACED"
               % _bare,
               any("not namespaced" in w and "superpowers-v-spec-reviewer" in w
                   for w in _u_msgs))
    expect("advisory: the namespaced lane does NOT raise MEMORY_LANE_UNNAMESPACED",
           not any("not namespaced" in w for w in advisories_text(
               _lane('".claude/agent-memory/superpowers-v-spec-reviewer/**"',
                     '"docs/superpowers/dogfood/r-1.md"'))))
    expect("advisory: the gitignored -local scope never raises "
           "MEMORY_LANE_UNNAMESPACED",
           not any("not namespaced" in w for w in advisories_text(
               _lane('".claude/agent-memory-local/spec-reviewer/**"',
                     '"docs/superpowers/dogfood/r-1.md"'))))
    expect("advisory: MEMORY_LANE_UNNAMESPACED does NOT change the verdict",
           validate_text(_lane('".claude/agent-memory/spec-reviewer/**"',
                               '"docs/superpowers/dogfood/r-1.md"')) == [])
    expect("unnamespaced_agent_memory_name: bare form -> agent name",
           unnamespaced_agent_memory_name(".claude/agent-memory/spec-reviewer/**")
           == "spec-reviewer")
    expect("unnamespaced_agent_memory_name: namespaced form -> None",
           unnamespaced_agent_memory_name(
               ".claude/agent-memory/superpowers-v-spec-reviewer/**") is None)

    # --- ADVISORIES: WAVE_EXCEEDS_RUNTIME_CONCURRENCY (v3.6.4) -----------------
    # The native Workflow runtime's default cap is 16 concurrent agents, and the
    # emitter's own peak-concurrency arithmetic (see the constant's docstring
    # above `wave_concurrency_advisories`) is 1 agent per job in flight at a
    # time — so a wave this wide queues rather than dispatching all at once.
    def _wave_manifest(n_jobs, max_parallel):
        jobs = "\n".join(
            "  - id: task-w%d\n"
            "    title: \"wave job %d\"\n"
            "    type: bounded_crud\n"
            "    backend: claude\n"
            "    tier: standard\n"
            "    effort: medium\n"
            "    isolation: worktree\n"
            "    run: parallel\n"
            "    write_allowed: [src/wave%d/**]\n"
            "    read_allowed: [src/**]\n"
            "    acceptance: [\"builds\"]"
            % (i, i, i)
            for i in range(n_jobs)
        )
        return """
run_id: 2026-09-21-wave
feature: "wave width"
spec_path: docs/superpowers/specs/2026-09-21-wave.md
plan_path: docs/superpowers/plans/2026-09-21-wave.md
audits:
  archaeology: docs/superpowers/archaeology/2026-09-21-wave.md
  domain: docs/superpowers/expert/2026-09-21-wave.md
  library: docs/superpowers/library-audit/2026-09-21-wave.md
routing_stance: balanced
max_parallel: %d
acceptance_criteria:
  - "ships"
jobs:
%s
""" % (max_parallel, jobs)

    _wide = _wave_manifest(17, 20)
    _wide_msgs = advisories_text(_wide)
    expect("advisory: a 17-job single wave raises WAVE_EXCEEDS_RUNTIME_CONCURRENCY",
           any("17 jobs exceeds" in w and "wave 1" in w for w in _wide_msgs))
    expect("advisory: the warning names the runtime default and the env var",
           bool(_wide_msgs) and any(
               "concurrency cap of 16" in w
               and "CLAUDE_CODE_WORKFLOW_MAX_CONCURRENT_AGENTS" in w
               for w in _wide_msgs))
    expect("advisory: WAVE_EXCEEDS_RUNTIME_CONCURRENCY does NOT change the verdict",
           validate_text(_wide) == [])

    _narrow = _wave_manifest(4, 4)
    expect("advisory: a 4-job wave does NOT raise WAVE_EXCEEDS_RUNTIME_CONCURRENCY",
           not any("exceeds" in w and "concurrency cap" in w
                   for w in advisories_text(_narrow)))
    expect("wave-width test manifest (4-job) is itself a clean PASS",
           validate_text(_narrow) == [])

    # exactly-at-the-limit (16) must NOT warn; one over (17) must.
    expect("advisory: exactly 16 jobs in one wave does NOT warn",
           not any("concurrency cap" in w
                   for w in advisories_text(_wave_manifest(16, 20))))

    # --- v3.6: provision_command / provision_timeout_s -------------------------
    def _prov(extra):
        return _v3_manifest() + extra

    expect("provision: a valid command + timeout pair is PASS",
           validate_text(_prov("provision_command: \"npm ci\"\n"
                               "provision_timeout_s: 600\n")) == [])
    expect("provision: absent is valid (no key at all)",
           validate_text(_v3_manifest()) == [])
    expect("provision: provision_command 3 (not a string) is FAIL",
           any("provision_command" in p for p in
               validate_text(_prov("provision_command: 3\n"))))
    expect("provision: provision_command \"\" (empty) is FAIL",
           any("provision_command" in p for p in
               validate_text(_prov('provision_command: ""\n'))))
    expect("provision: provision_timeout_s 0 is FAIL",
           any("provision_timeout_s" in p for p in
               validate_text(_prov("provision_command: \"npm ci\"\n"
                                   "provision_timeout_s: 0\n"))))
    expect("provision: provision_timeout_s 1801 is FAIL",
           any("provision_timeout_s" in p for p in
               validate_text(_prov("provision_command: \"npm ci\"\n"
                                   "provision_timeout_s: 1801\n"))))
    expect("provision: provision_command with a newline is FAIL",
           any("provision_command" in p for p in
               _validate_provision({"provision_command": "npm ci\nrm -rf /"})))

    # --- issue #22: top-level toolchain_artifacts ------------------------------
    expect("toolchain_artifacts: absent is valid (no key at all)",
           validate_text(_v3_manifest()) == [])
    expect("toolchain_artifacts: a valid list of specific globs is PASS",
           validate_text(_prov(
               'toolchain_artifacts: ["tsconfig.tsbuildinfo", '
               '"node_modules/.vite/**"]\n')) == [])
    expect("toolchain_artifacts: a bare string (not a list) is FAIL",
           any("toolchain_artifacts" in p for p in
               validate_text(_prov('toolchain_artifacts: "x"\n'))))
    expect("toolchain_artifacts: [\"**\"] (catch-all) is FAIL",
           any("toolchain_artifacts" in p and "catch-all" in p for p in
               validate_text(_prov('toolchain_artifacts: ["**"]\n'))))
    expect("toolchain_artifacts: [\"\"] (empty entry) is FAIL",
           any("toolchain_artifacts" in p for p in
               validate_text(_prov('toolchain_artifacts: [""]\n'))))
    expect("toolchain_artifacts: null (bare key) is valid (same absent-vs-null "
           "rule as global_constraints)",
           validate_text(_prov("toolchain_artifacts:\n")) == [])
    # Every other catch-all spelling is refused too, not just bare "**".
    for _glob in ("*", "**/*", "/**", "./**"):
        expect("toolchain_artifacts: %r is a catch-all and FAILS" % _glob,
               any("catch-all" in p for p in _validate_toolchain_artifacts(
                   {"toolchain_artifacts": [_glob]})))
    # A catch-all mixed in with legitimate globs still fails the whole list —
    # one bad entry is enough, the good ones don't dilute it.
    expect("toolchain_artifacts: a catch-all mixed with valid globs still FAILS",
           any("catch-all" in p for p in _validate_toolchain_artifacts(
               {"toolchain_artifacts": ["tsconfig.tsbuildinfo", "**"]})))
    # A newline inside one entry is refused, same single-line discipline as
    # provision_command.
    expect("toolchain_artifacts: an entry with a newline is FAIL",
           any("toolchain_artifacts" in p and "single-line" in p
               for p in _validate_toolchain_artifacts(
                   {"toolchain_artifacts": ["tsconfig.tsbuildinfo\nrm -rf /"]})))
    # A non-string entry (bool/int) is caught by the shared shape check, not the
    # catch-all check crashing on a non-string.
    expect("toolchain_artifacts: a non-string entry (True) is FAIL, not a crash",
           any("toolchain_artifacts" in p for p in _validate_toolchain_artifacts(
               {"toolchain_artifacts": [True]})))

    # The SHIPPED example must not trip the advisory it documents.
    _ex = os.path.join(_repo3, "examples", "manifest.example.yaml")
    if os.path.isfile(_ex):
        with open(_ex, "r", encoding="utf-8") as _fh:
            _ex_warn = advisories_text(_fh.read())
        expect("advisory: examples/manifest.example.yaml raises none (%r)" % _ex_warn,
               _ex_warn == [])

    # v2.9 conditional fast-path suite (on-disk fixtures).
    _selftest_fastpath(expect)

    # --- C2: a `yaml.py` planted beside this script is NOT the parser ---------
    # (eighth review pass, 2026-09-03.) See `_harden_sys_path` at the top of this
    # file. This module reads the document that DEFINES every job's
    # `write_allowed`, and `hooks/lane-guard.sh` loads it by path from a process
    # whose CWD is the worker's own worktree — so both shadowing routes (the
    # script's directory and the CWD) are exercised here at once, with the plant
    # sitting in the directory that is both.
    import shutil as _shutil_c2
    import subprocess as _sp_c2
    import tempfile as _tempfile_c2

    _c2_tmp = _tempfile_c2.mkdtemp(prefix="cv-vm-shadow-")
    try:
        _c2_copy = os.path.join(_c2_tmp, "compound-v-validate-manifest.py")
        _shutil_c2.copy(os.path.abspath(__file__), _c2_copy)
        _shutil_c2.copytree(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "cv_validate"),
                            os.path.join(_c2_tmp, "cv_validate"))
        _c2_mark = os.path.join(_c2_tmp, "hostile-yaml-imported")
        with open(os.path.join(_c2_tmp, "yaml.py"), "w") as _fh_c2:
            _fh_c2.write(
                "open(%r, 'w').write('imported')\n"
                "def safe_load(text):\n"
                "    return {'jobs': [{'id': 'pwned', 'write_allowed': ['**']}]}\n"
                % _c2_mark)

        # The plant is POTENT: an unhardened process in that directory imports it.
        _sp_c2.run([sys.executable, "-B", "-c", "import yaml"], cwd=_c2_tmp,
                   stdout=_sp_c2.DEVNULL, stderr=_sp_c2.DEVNULL)
        expect("shadow: the planted yaml.py IS imported by an unhardened process "
               "(the plant is real)", os.path.exists(_c2_mark))
        if os.path.exists(_c2_mark):
            os.remove(_c2_mark)

        _c2_probe = (
            "import importlib.util, json, sys\n"
            "spec = importlib.util.spec_from_file_location('_cv_vm', sys.argv[1])\n"
            "mod = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(mod)\n"
            "print(json.dumps(mod.load_yaml('jobs:\\n- id: real\\n')))\n"
        )
        _c2_proc = _sp_c2.run(
            [sys.executable, "-B", "-c", _c2_probe, _c2_copy], cwd=_c2_tmp,
            stdout=_sp_c2.PIPE, stderr=_sp_c2.PIPE, universal_newlines=True)
        try:
            _c2_parsed = json.loads(_c2_proc.stdout or "{}")
        except ValueError:
            _c2_parsed = {}
        _c2_jobs = (_c2_parsed or {}).get("jobs") or []
        expect("shadow: the parse is unaffected — the real document is read",
               len(_c2_jobs) == 1 and _c2_jobs[0].get("id") == "real")
        expect("shadow: the planted yaml.py was never imported",
               not os.path.exists(_c2_mark))
    finally:
        _shutil_c2.rmtree(_c2_tmp, ignore_errors=True)

    if failures:
        print("\nSELFTEST FAILED: %d case(s)" % len(failures))
        return 1
    # --- 3.3.0: `type` decides who is a reviewer ---------------------------
    # Dogfood 10: a job TITLED "Writes the thing the reviewer reviews" was refused
    # for not being deep-tier. `integration` and `quality` are in the token list,
    # so ordinary titles were forcing jobs onto Opus by accident.
    expect("a declared review type is a reviewer",
           _is_reviewer({"type": "review", "id": "x", "title": "x"}) is True)
    expect("a docs job whose TITLE mentions a reviewer is NOT one",
           _is_reviewer({"type": "docs", "id": "impl-slice",
                         "title": "Writes the thing the reviewer reviews"}) is False)
    expect("'Add integration tests' is not a reviewer",
           _is_reviewer({"type": "tests_new", "id": "t1",
                         "title": "Add integration tests"}) is False)
    expect("'Refactor the quality metrics' is not a reviewer",
           _is_reviewer({"type": "mechanical_refactor", "id": "q1",
                         "title": "Refactor the quality metrics module"}) is False)
    expect("with NO type, the id/title fallback still catches a reviewer",
           _is_reviewer({"id": "spec-review", "title": "gate"}) is True)
    expect("the fallback matches WORD boundaries, so 'preview' is not 'review'",
           _is_reviewer({"id": "preview-builder",
                         "title": "build the preview"}) is False)
    expect("the fallback does not fire on 'disintegration'",
           _is_reviewer({"id": "d1", "title": "model disintegration study"}) is False)

    print("\nSELFTEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
