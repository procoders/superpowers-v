"""build_plan: a manifest turned into the waves, jobs and artefacts the script embeds."""

from __future__ import annotations

import os
import sys
import json

from .util import (
    NARROW_DISALLOWED, IMPLEMENT_DISALLOWED, BUDGET_RESERVE_PER_AGENT, _read_json,
    test_contract_path,
)
from .digest import (
    sha256_file,
)
from .roles import (
    topo_waves, agent_role_for, resolve_role_agent_type, resolve_agent_type, agent_definition,
    resolve_job_model,
)
from .clamp import (
    _clamp_rules,
)
from .retry import (
    PROJECT_STANCES, escalation_ladder, escalation_map, retry_config, _is_reviewer_job,
    prior_attempt_failed, escalate_claude_model,
)
from .recall import (
    TIER_RAISE, RECALL_REVIEW_CLAUSE, run_recall_check, review_recall_query, run_recall_search,
    recall_check_path,
)
from .prompts import (
    worker_prompt_path, launch_argv_path, _job_interfaces, render_worker_prompt,
)


# A harness Bash call is capped at 600 s. The external worker runs INSIDE one, and
# then runs the test floor, so its own wall-clock cap must leave headroom.
EXTERNAL_WORKER_TIMEOUT_CAP = 480


PROVISION_TIMEOUT_DEFAULT = 600


def _provision_spec(manifest, job):
    """(command, timeout_s) for this job. Command is None when nothing is declared.

    `provision_command` is a MANIFEST-level declaration — one dependency install
    for one run — and a job may override it. Reading both costs nothing and means
    the emitter agrees with the validator whichever level a manifest uses.

    The timeout is the DOCUMENTED default (600 s) whenever the declared value is
    absent or not a usable positive integer. It is never left implicit: the worker
    scripts and the register-lane prompt both need a number, and an implicit one
    is how `--test-timeout-sec` came to default to a figure no document named.
    """
    # MANIFEST-LEVEL ONLY. A job entry carrying these keys is IGNORED, and `job`
    # stays in the signature because every caller has it and a reader deserves to
    # see that it is deliberately unused rather than forgotten.
    #
    # The first draft read the job entry first. That shipped per-job provisioning,
    # which the 3.6.0 spec names under Out of scope, and it shipped it UNVALIDATED:
    # `_validate_provision` reads the manifest only, and the validator rejects no
    # unknown job key, so the single-line check that exists at top level never ran
    # on a job-level value. A multi-line string on a job entry would have passed
    # validation clean and reached `/bin/bash -c` inside the worktree — the exact
    # value the top-level check exists to refuse, with a selftest row naming it.
    # Found by the Review Gate, not by a test: no gate compares code with a spec's
    # Out of scope list.
    command = None
    raw = (manifest or {}).get("provision_command") if isinstance(manifest, dict) else None
    if isinstance(raw, str) and raw.strip():
        command = raw.strip()
    timeout = PROVISION_TIMEOUT_DEFAULT
    raw = (manifest or {}).get("provision_timeout_s") if isinstance(manifest, dict) else None
    if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0:
        timeout = raw
    return command, timeout


def _toolchain_artifacts_spec(manifest):
    """The manifest's top-level `toolchain_artifacts` globs, or `[]` (issue #22).

    MANIFEST-LEVEL ONLY, same reasoning as `_provision_spec`: `toolchain_artifacts`
    is a run-wide declaration, not a per-job one, so there is no job-level
    override to read. `compound-v-validate-manifest.py` is where a malformed
    value is REFUSED — a bare string, a catch-all glob, a non-string entry; this
    function only decides what the emitter passes through, and it fails closed
    into "nothing declared" rather than trying to salvage a partially-valid list,
    which would make the emitter's idea of the manifest disagree with the
    validator's.
    """
    raw = (manifest or {}).get("toolchain_artifacts") if isinstance(manifest, dict) else None
    if isinstance(raw, list) and raw and all(isinstance(g, str) and g.strip() for g in raw):
        return list(raw)
    return []


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
    # The dependency install the worker runs inside its own fresh worktree,
    # BEFORE the model launches. Both flags travel together or neither does: a
    # `--provision-timeout-sec` with no command bounds nothing, and a command
    # with no bound would sit under the worker script's own default rather than
    # under the number the manifest declared.
    if entry.get("provision_command"):
        argv += ["--provision-command", entry["provision_command"],
                 "--provision-timeout-sec",
                 str(entry.get("provision_timeout_s") or PROVISION_TIMEOUT_DEFAULT)]
    # `toolchain_artifacts` (issue #22): a MANIFEST-level list, not a per-job one
    # (same reasoning as `provision_command` above), passed through to the
    # external worker's own scope-check invocation unchanged — one repeatable
    # `--toolchain-artifact <glob>` flag per glob, none when the manifest
    # declares none.
    for _glob in (entry.get("toolchain_artifacts") or []):
        argv += ["--toolchain-artifact", _glob]
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


def _agent_isolation_downgraded(job, abs_repo_root):
    """True when the manifest asked for ``worktree`` but the AGENT will run in the
    main checkout anyway — the `depends_on` rule, unless `worktree.baseRef: head`.

    Only a CLAUDE job can be downgraded this way. An external backend (codex, cursor,
    antigravity, …) owns its own worktree: `job_entry` pins its manifest isolation to
    `direct`, and the gate still runs in worktree mode over the worker's tree via the
    `externalBackend` branch of the emitted script. Such a job is fully attributable
    and must NOT be serialized — treating it as downgraded would cost parallelism for
    nothing.

    This is the exact NEGATION of the `agent_isolation` expression in `job_entry`,
    written as one predicate rather than a second copy of the positive condition:
    the agent runs in the main checkout whenever it does not get a real worktree. A
    manifest-`direct` claude job is therefore counted too — it is also a main-tree
    writer, and two of those in one wave is the same unattributable shape (invariant
    7 makes that unreachable through a validated manifest, but `build_plan` does not
    validate, so the predicate should not depend on it).
    """
    if (job.get("backend") or "claude") != "claude":
        return False
    gets_real_worktree = (
        (job.get("isolation") or "direct") == "worktree"
        and (not (job.get("depends_on") or [])
             or _worktree_base_is_head(abs_repo_root))
    )
    return not gets_real_worktree


def _serialize_unattributable_waves(waves, abs_repo_root):
    """Split a wave that would run TWO OR MORE downgraded jobs at once in ONE tree.

    A downgraded job runs its agent in the main checkout, and direct mode attributes
    its writes with a single before-image snapshot. One such job per wave is exactly
    what that snapshot handles, and the comment on `agent_isolation` says so. Two is
    a different thing: one before-image cannot separate two concurrent writers, so
    each job's diff contains the other's files and BOTH are BLOCKED for out-of-lane
    writes — a run that is guaranteed to fail before any code is judged.

    Observed on a seven-job run in a project with no `.claude/settings.json`: wave 2
    ran `task-1` ∥ `task-2`, both `isolation: worktree`, both `depends_on` the wave-0
    job; each blocked carrying the other's entire lane.

    The validator REQUIRES `isolation: worktree` for parallel jobs and
    partition-reviewer verifies it, so the manifest passes an invariant the run then
    does not honour. Rather than emit that run, give each downgraded job its own
    wave: a wave is already a barrier, so more barriers is strictly safer, and one
    writer at a time is the case attribution can actually handle. Jobs that were NOT
    downgraded keep their real worktrees and stay together.

    Returns ``(waves, notes)``; ``notes`` is empty when nothing was re-ordered.
    """
    out, notes = [], []
    for wave in waves:
        downgraded = [j for j in wave if _agent_isolation_downgraded(j, abs_repo_root)]
        if len(downgraded) < 2:
            out.append(wave)
            continue
        # Partition by id, not by dict equality: `j not in downgraded` compares job
        # dicts by VALUE, which is only safe while topo_waves rejects duplicate ids.
        _down_ids = {j.get("id") for j in downgraded}
        others = [j for j in wave if j.get("id") not in _down_ids]
        if others:
            out.append(others)
        for job in downgraded:
            out.append([job])
        notes.append(
            "wave with %s concurrent main-checkout jobs (%s) serialized: their "
            "manifest `isolation: worktree` is downgraded because they carry "
            "depends_on and this project has no `worktree.baseRef: \"head\"` in "
            ".claude/settings.json, and one before-image cannot attribute two "
            "concurrent writers. Set that key to get real worktrees and full "
            "parallelism." % (len(downgraded), ", ".join(
                str(j.get("id")) for j in downgraded)))
    return out, notes


def build_plan(manifest, run_dir, repo_root, python_bin, self_path,
               scope_check, fastpath, workers_dir, recall=True,
               recall_results_root=None, recall_engine=None):
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
    # v3.4.17: the plan's `## Global Constraints` lines (Superpowers 6.2.0),
    # copied into the manifest by /v:orchestrate and binding on EVERY job. Read
    # once here; every job's prompt renders the same list. Absent ⇒ empty ⇒ the
    # block is not rendered at all, which is what every pre-6.2.0 run looks like.
    global_constraints = [c for c in (manifest.get("global_constraints") or [])
                          if isinstance(c, str) and c.strip()]
    config_path = os.path.join(abs_repo_root, ".claude", "compound-v.json")
    if not os.path.isfile(config_path):
        config_path = None
    # A manifest without `routing_stance` falls back to the project's `stance`, the
    # key /v:init writes; without it a cost-aware project resolved frontier to Fable.
    if stance is None and config_path:
        _cfg_stance = (_read_json(config_path, {}) or {}).get("stance")
        if isinstance(_cfg_stance, str) and _cfg_stance.strip() in PROJECT_STANCES:
            stance = _cfg_stance.strip()
    # Gate, Record and Finalize are TRANSPORT: each runs exactly one clamped
    # command and returns its JSON verbatim, and the command's real logic is
    # Python that the integration authority re-verifies from git. That is the
    # `light` tier by definition, so they are routed through the same resolver
    # rather than inheriting whatever the session happens to be running.
    transport_model, transport_note = resolve_job_model(
        {"id": "__transport__", "backend": "claude", "tier": "light"},
        python_bin, stance=stance, config_path=config_path)
    # The escalation ceiling is the stance's own `frontier` cell, resolved the
    # way every job's model is: cost-aware caps both ladders at Opus.
    _frontier_model, _ = resolve_job_model(
        {"id": "__ceiling__", "backend": "claude", "tier": "frontier"},
        python_bin, stance=stance, config_path=config_path)
    ladder, ladder_note = escalation_ladder(_frontier_model, stance)
    # `agents/transport.md` (3.6.4) — resolved ONCE per run, never per job or
    # per stage, because Gate/Record/Finalize/Continuity are not job types and
    # never key off a job's own `type` the way `AGENT_TYPE_BY_JOB_TYPE` does.
    # `None` when the file or the plugin manifest name cannot be found, exactly
    # like every other `agentType` resolution here — the JS_TEMPLATE's
    # `agentTransport` reads `CFG.transport_agent_type` and spawns anonymously
    # when it is falsy, so a missing definition degrades, it never breaks emit.
    transport_agent_type, transport_agent_type_note = resolve_role_agent_type(
        "transport")
    artefacts = {}
    max_parallel = manifest.get("max_parallel") or 4
    jobs = manifest.get("jobs") or []
    waves = topo_waves(jobs, max_parallel)
    # A wave whose agents were all downgraded into the SAME checkout cannot be
    # attributed (see _serialize_unattributable_waves). Serialize it here rather
    # than emit a run that is guaranteed to BLOCK, and tell the operator why —
    # the downgrade was previously invisible until the gate failed two waves later.
    waves, _isolation_notes = _serialize_unattributable_waves(waves, abs_repo_root)
    for _note in _isolation_notes:
        sys.stderr.write("compound-v: %s\n" % _note)
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

    # ---- recall, once, before any job entry is built ---------------------- #
    # Computed for EVERY job up front rather than inside `job_entry`, because one
    # of its consequences is not local to a job: a `review` job's acceptance
    # gains a re-check clause naming the OTHER jobs that tightened, and a
    # per-job loop cannot know them yet.
    # `memory.auto_tighten` is the /v:init Step 3b choice and lives in the PROJECT
    # config (`.claude/compound-v.json`, the `config_path` computed above) — the
    # manifest's optional `memory:` block is a per-run override only (v3.4.10
    # review-1, item 2: the first cut read a manifest key nothing writes).
    memory_cfg = {}
    if config_path:
        _cfg_doc = _read_json(config_path, None)
        if isinstance(_cfg_doc, dict) and isinstance(_cfg_doc.get("memory"), dict):
            memory_cfg.update(_cfg_doc["memory"])
    _man_mem = manifest.get("memory")
    if isinstance(_man_mem, dict):
        memory_cfg.update(_man_mem)
    # Exact JSON booleans only (Codex receipt finding 5): "false" the string must
    # not enable tightening, and any other type reads as the default.
    auto_tighten = memory_cfg.get("auto_tighten") is True
    # `memory.auto_recall` (default true) is the /v:init "Manual only" switch;
    # `emit --no-recall` forces it off for one emit. Review-2 of v3.4.10, item 1:
    # until now no script read it and /v:init offered a switch that reached nothing.
    _auto_recall = memory_cfg.get("auto_recall", True)
    recall = bool(recall) and (_auto_recall is not False)
    recall_results_root = os.path.abspath(
        recall_results_root
        or os.path.join(abs_repo_root, "docs", "superpowers", "execution")
    )
    recalls = {}
    for _job in jobs:
        _jid = _job.get("id")
        if not _jid:
            continue
        if recall and str(_job.get("type") or "implement") == "review":
            # A reviewer declares no implementation lane; the bridge is about
            # prior failures on the files an IMPLEMENTER is about to touch
            # (review-1, item 5: spec says implement jobs, code ran every job).
            # Ordered AFTER the recall switch so `--no-recall` / auto_recall off
            # records `unavailable` for every job alike (review-2, item 3).
            recalls[_jid] = {"verdict": "none", "match_count": 0, "evidence": [],
                             "note": "review job: recall-check is for implement lanes",
                             "recall_check_ms": 0}
            continue
        if recall:
            recalls[_jid] = run_recall_check(
                _job.get("write_allowed") or [], recall_results_root, python_bin,
                engine=recall_engine, repo_root=abs_repo_root,
            )
        else:
            recalls[_jid] = {
                "verdict": "unavailable", "match_count": 0, "evidence": [],
                "note": "recall not run for this emit (`--no-recall`, or memory.auto_recall is false)",
                "recall_check_ms": 0,
            }
    tightened = sorted(jid for jid, doc in recalls.items()
                       if doc.get("verdict") == "tighten")
    # ---- V-memory search for the review jobs, ONCE per emit (v3.7.2) ------ #
    # One query for the whole run (the feature and its acceptance criteria), so
    # every reviewer is shown the same evidence and the engine runs once, not
    # once per review job. Same switch as recall-check: `--no-recall` or
    # `memory.auto_recall: false` records `unavailable` and renders no block.
    _reviewers = [j for j in jobs if j.get("id") and _is_reviewer_job(j)]
    recall_search = None
    if _reviewers and recall:
        recall_search = run_recall_search(
            review_recall_query(manifest, _reviewers), python_bin,
            engine=recall_engine, repo_root=abs_repo_root)
    elif _reviewers:
        recall_search = {
            "status": "unavailable", "query": review_recall_query(manifest, _reviewers),
            "hits": [], "block": "",
            "note": "recall not run for this emit (`--no-recall`, or memory.auto_recall is false)",
            "summary": "recall: unavailable (not run for this emit: `--no-recall` or "
                       "memory.auto_recall is false)",
            "recall_ms": 0,
        }

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
        # ---- the recall verdict, and its one mechanical consequence -------- #
        recall_doc = dict(recalls.get(job_id) or {
            "verdict": "none", "match_count": 0, "evidence": [],
            "recall_check_ms": 0,
        })
        # `routed_job` is what the RESOLVER sees. The manifest's own job dict is
        # never mutated — the digest that pins it is taken from the file, and a
        # plan that quietly disagreed with the manifest it hashes is the whole
        # class of defect the digest exists to catch.
        routed_job = job
        entry_tier = job.get("tier")
        explicit_model = isinstance(job.get("model"), str) and job["model"].strip()
        if (auto_tighten and recall_doc.get("verdict") == "tighten"
                and not explicit_model):
            _cur = str(job.get("tier") or "").strip()
            _next = TIER_RAISE.get(_cur)
            if _next and _next != _cur:
                routed_job = dict(job)
                routed_job["tier"] = _next
                entry_tier = _next
                recall_doc["tier_raised"] = "%s → %s" % (_cur, _next)
            elif _cur:
                recall_doc["tier_raised"] = "none (%s is the top rung)" % _cur
        elif auto_tighten and recall_doc.get("verdict") == "tighten":
            # An explicit `model:` is a decision someone wrote down. Recall
            # records that it declined to override it rather than doing so
            # silently.
            recall_doc["tier_raised"] = "none (explicit `model:` wins)"
        # A reviewer is told what tightened in this RUN, not in its own lane —
        # reviewers usually declare no write lane at all, so their own verdict is
        # `none` by construction and would say nothing useful.
        acceptance = list(job.get("acceptance") or [])
        if auto_tighten and tightened and str(job.get("type") or "") == "review":
            acceptance.append(RECALL_REVIEW_CLAUSE % ", ".join(tightened))
        entry = {
            "id": job_id,
            "job_type": job.get("type"),
            "agent_type": agent_type,
            "agent_type_note": agent_type_note,
            "agent_definition": agent_def,
            "title": job.get("title") or job_id,
            "backend": backend,
            "tier": entry_tier,
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
            # Resolved HERE, where the manifest is still in hand: `build_launch_argv`
            # is handed the entry, not the manifest, and the implement prompt reads
            # the timeout to size its own Bash call.
            "provision_command": _provision_spec(manifest, job)[0],
            "provision_timeout_s": _provision_spec(manifest, job)[1],
            # `toolchain_artifacts` (issue #22): MANIFEST-level only, same reasoning
            # as `provision_command` above — resolved here, where the manifest is
            # still in hand, so `build_launch_argv` (handed the entry, not the
            # manifest) can pass it straight through to the external worker.
            "toolchain_artifacts": _toolchain_artifacts_spec(manifest),
            "write_allowed": job.get("write_allowed") or [],
            "read_allowed": job.get("read_allowed") or [],
            # v3.4.17: this task's `**Interfaces:**` block from the plan — the
            # ONLY view an isolated implementer gets of the names and signatures
            # its neighbours rely on. Absent ⇒ `{}` ⇒ nothing is rendered.
            "interfaces": _job_interfaces(job),
            "acceptance": acceptance,
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
            # The emit-time recall verdict, carried in the job entry the emitted
            # script serializes — so the run's own artefact records what recall
            # said, whether or not anything acted on it.
            "recall_check": recall_doc,
            "recall_check_file": (
                recall_check_path(abs_run_dir, job_id)
                if recall_doc.get("verdict") == "tighten" else None
            ),
            # The emit-time V-memory search a REVIEW job's prompt was built from
            # (query, verdict line, hits, the exact block) — recorded on the entry
            # the script serializes, so the run's artefact shows what the reviewer
            # was shown. None for every other job type.
            "recall_search": (dict(recall_search)
                              if recall_search is not None and _is_reviewer_job(job)
                              else None),
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
            resolved, merr = resolve_job_model(routed_job, python_bin, stance=stance,
                                               config_path=config_path)
            if resolved:
                entry["model"] = resolved
                entry["model_source"] = ("explicit" if job.get("model") else "tier")
                # A job that already failed in this run is re-dispatched one rung
                # up, never past the stance's ceiling. Reviewers are exempt: a
                # sealed review receipt must carry a Claude Opus `reviewer_model`,
                # so escalating one would invalidate the very receipt it exists
                # to produce. An explicit manifest pin stays pinned.
                if (not explicit_model and not _is_reviewer_job(job)
                        and prior_attempt_failed(abs_run_dir, job_id)):
                    stepped, capped = escalate_claude_model(resolved, ladder)
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
            "prompt_text": render_worker_prompt(job, run_id, global_constraints),
            "launch_argv_file": None,
            "launch_argv": None,
            # Written only for a job that tightened, because that is the only
            # job whose prompt hands the path back to `register-lane`.
            "recall_file": entry["recall_check_file"],
            "recall_text": (
                json.dumps(recall_doc, indent=2, sort_keys=True) + "\n"
                if entry["recall_check_file"] else None
            ),
        }
        if backend != "claude":
            if not entry["worker_script"]:
                raise ValueError(
                    "job %r runs on backend %r but scripts/compound-v-run-%s-worker.sh "
                    "is not present — the handoff cannot be materialized, and an "
                    "unmaterialized handoff is what 3.0.1 shipped"
                    % (job_id, backend, backend)
                )
            model, err = resolve_job_model(routed_job, python_bin, stance=stance,
                                           config_path=config_path)
            if not model:
                raise ValueError(
                    "job %r cannot be launched: %s. `--model` is required by the "
                    "worker script, so this fails closed rather than guessing"
                    % (job_id, err)
                )
            argv = build_launch_argv(routed_job, entry, run_id, abs_repo_root,
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
        "global_constraints": global_constraints,
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
        "transport_agent_type": transport_agent_type,
        "transport_agent_type_note": transport_agent_type_note,
        # The workflow's retry budget and the escalation ladder, resolved ONCE
        # here so the emitted script never re-derives either.
        "retry": retry_config(manifest, config_path),
        "escalation": escalation_map(ladder),
        "escalation_ceiling": ladder[-1],
        "escalation_ceiling_note": ladder_note,
        "waves": [[job_entry(j) for j in wave] for wave in waves],
        # WHY THE WAVE PLAN MAY NOT MATCH THE PARTITION MAP. A stderr line is gone
        # the moment emit finishes, and `dispatch.workflow.js` is what gets committed
        # — an auditor comparing the reviewed partition (N waves) against the run
        # (N+k) would otherwise have no explanation for the difference. Empty on
        # every run that was not re-shaped.
        "isolation_notes": list(_isolation_notes),
    }
