"""Engine selection, the emit subcommand and the subcommand table."""

from __future__ import annotations

import os
import sys
import argparse
import json

from .util import (
    HERE, ENTRY_PATH, SCOPE_CHECK_DEFAULT, FASTPATH_DEFAULT, _run, _load_yaml, _atomic_write,
    forbidden_hits, _head_commit,
)
from .recall import (
    RECALL_ENGINE_DEFAULT,
)
from .plan import (
    build_plan,
)
from .script_js import (
    emit_script,
)
from .gate import (
    cmd_gate_receipt,
)
from .record import (
    cmd_record,
)
from .finalize import (
    cmd_finalize_wave,
)
from .lane import (
    _reattempt_guidance, _stale_attempt_pins, cmd_register_lane, cmd_resume_prepare,
    cmd_integrated_jobs,
)


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
    ap.add_argument("--no-recall", dest="recall", action="store_false",
                    default=True,
                    help="skip the emit-time recall read entirely. Every job then "
                         "records `recall_check: {verdict: unavailable, ...}` and "
                         "no prompt carries a prior-failures section.")
    ap.add_argument("--recall-results-root", dest="recall_results_root",
                    help="where recall scans for recorded job_results. Default: "
                         "<repo-root>/docs/superpowers/execution")
    ap.add_argument("--recall-engine", dest="recall_engine",
                    default=RECALL_ENGINE_DEFAULT,
                    help="the recall engine, run as a SUBPROCESS. A missing or "
                         "failing one is recorded, never fatal.")
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

    # A PREVIOUS ATTEMPT'S PINS STILL IN PLACE. Re-emitting into this run dir
    # starts a new attempt whose gate would diff against the old pins and charge
    # each job with every commit made since them. `--print` writes nothing and
    # stays open.
    if not args.to_stdout:
        _stale = _stale_attempt_pins(run_dir, [
            str(j.get("id")) for j in (manifest.get("jobs") or [])
            if isinstance(j, dict) and j.get("id")], _head_commit(repo_root))
        if _stale:
            sys.stderr.write(
                "REFUSING TO EMIT: run directory %s still holds a previous "
                "attempt for %s (pinned baseline%s %s). %s\n"
                % (run_dir, ", ".join(sorted(_stale)),
                   "s" if len(_stale) > 1 else "",
                   ", ".join(_stale[k][:12] for k in sorted(_stale)),
                   _reattempt_guidance(run_dir)))
            return 2

    try:
        plan = build_plan(
            manifest, run_dir, repo_root, args.python,
            ENTRY_PATH, args.scope_check, args.fastpath,
            args.workers_dir, recall=args.recall,
            recall_results_root=args.recall_results_root,
            recall_engine=args.recall_engine,
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
        if doc.get("recall_file") and doc.get("recall_text"):
            _atomic_write(doc["recall_file"], doc["recall_text"])
            artefacts.append(doc["recall_file"])

    recall_report = {}
    for wave in plan["waves"]:
        for job in wave:
            doc = job.get("recall_check") or {}
            row = {"verdict": doc.get("verdict"),
                   "match_count": doc.get("match_count"),
                   "recall_check_ms": doc.get("recall_check_ms")}
            for key in ("note", "tier_raised"):
                if doc.get(key):
                    row[key] = doc[key]
            recall_report[job["id"]] = row

    # The review jobs' V-memory search: one per emit, so one row, naming the jobs
    # that carry it.
    search_report = None
    for wave in plan["waves"]:
        for job in wave:
            doc = job.get("recall_search")
            if doc is None:
                continue
            if search_report is None:
                search_report = {k: doc.get(k) for k in (
                    "status", "summary", "query", "hits", "note", "recall_ms")}
                search_report["jobs"] = []
            search_report["jobs"].append(job["id"])

    report = {
        "recall_check": recall_report,
        "recall_search": search_report,
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
# CLI
# --------------------------------------------------------------------------- #
SUBCOMMANDS = {
    "emit": cmd_emit,
    "gate-receipt": cmd_gate_receipt,
    "record": cmd_record,
    "finalize-wave": cmd_finalize_wave,
    "register-lane": cmd_register_lane,
    "resume-prepare": cmd_resume_prepare,
    "integrated-jobs": cmd_integrated_jobs,
}
