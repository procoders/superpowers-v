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
  resume-prepare what /v:resume runs BEFORE relaunching a crashed run: clear the
                 crashed attempt's baseline pin for every job that has not
                 integrated, reset those jobs to pending, drop their stale
                 lane-map entries and archive their superseded receipts. A
                 relaunch branches a fresh worktree from the CURRENT HEAD, and a
                 pin from the crashed attempt charges the job with every commit
                 landed since (proven BLOCKED on 2026-09-03, finding 146).
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

import importlib  # noqa: E402
import importlib.util  # noqa: E402
import json  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

PACKAGE = "cv_emit"
SUBMODULES = (
    "util", "digest", "roles", "clamp", "retry", "recall", "prompts", "plan", "script_js", "gate",
    "record", "finalize", "lane", "emit", "selftest",
)


def _load_package():
    """Load scripts/cv_emit by explicit path, reading no bytecode cache beside it."""
    for name in [n for n in sys.modules if n == PACKAGE or n.startswith(PACKAGE + ".")]:
        del sys.modules[name]
    prev_prefix = getattr(sys, "pycache_prefix", None)
    try:
        tmp_pycache = tempfile.mkdtemp(prefix="cv-pycache-")
    except Exception as exc:  # noqa: BLE001
        raise ImportError("%s not loaded: no private bytecode cache directory (%s)"
                          % (PACKAGE, exc))
    sys.pycache_prefix = tmp_pycache
    try:
        pkg_dir = os.path.join(HERE, PACKAGE)
        spec = importlib.util.spec_from_file_location(
            PACKAGE, os.path.join(pkg_dir, "__init__.py"),
            submodule_search_locations=[pkg_dir])
        package = importlib.util.module_from_spec(spec)
        sys.modules[PACKAGE] = package
        spec.loader.exec_module(package)
        for sub in SUBMODULES:
            importlib.import_module(PACKAGE + "." + sub)
    finally:
        sys.pycache_prefix = prev_prefix
        shutil.rmtree(tmp_pycache, ignore_errors=True)


try:
    _load_package()
except ImportError as _exc:
    if __name__ != "__main__":
        raise
    sys.stderr.write("compound-v-emit-workflow.py: %s\n" % _exc)
    sys.exit(2)

from cv_emit.util import (  # noqa: E402
    ENTRY_PATH, SCOPE_CHECK_DEFAULT, FASTPATH_DEFAULT, INTEGRATION_GATE_DEFAULT,
    RESOLVE_MODEL_DEFAULT, FORBIDDEN_PATTERNS, NARROW_DISALLOWED, IMPLEMENT_DISALLOWED,
    IMPLEMENT_SHELL, STAGE_PHASES, BUDGET_RESERVE_PER_AGENT, _run, _git, _load_yaml, _atomic_write,
    _atomic_write_bytes, _run_dir_lock, _read_json, _js_json, neutralize_in_data, forbidden_hits,
    lane_map_path, test_contract_path, register_lane, _load_state, _utc_stamp, _save_state,
    _head_commit, _manifest_job,
)
from cv_emit.digest import (  # noqa: E402
    _load_module_from_path, sha256_file, manifest_digest_fault, patch_artifact_path,
    build_sealed_patch, sealed_post_image, head_matches_post_image, _import_integration_gate,
    _compute_diff_digest_local, compute_diff_digest,
)
from cv_emit.roles import (  # noqa: E402
    topo_waves, AGENT_TYPE_BY_JOB_TYPE, DEFAULT_AGENT_ROLE, REVIEWER_JOB_TYPES, agent_role_for,
    resolve_role_agent_type, resolve_agent_type, PLUGIN_ROOT, agent_definition, resolve_job_model,
    TURN_CAP_BY_TIER, TURN_CAP_DEFAULT, job_turn_cap,
)
from cv_emit.clamp import (  # noqa: E402
    _clamp_rules,
)
from cv_emit.retry import (  # noqa: E402
    CLAUDE_ESCALATION, PROJECT_STANCES, RETRY_MAX_ATTEMPTS_DEFAULT,
    RETRY_ESCALATE_REVIEWER_DEFAULT, RETRY_BACKOFF_BASE_MS, RETRY_BACKOFF_CAP_MS,
    RETRY_EXHAUSTED_REASON, retry_backoff_ms, _ladder_rung, escalation_ladder, escalation_map,
    _retry_value_ok, retry_config, RETRY_ENTRY_KEYS, _sanitize_retry_meta, apply_retry_meta,
    REVIEWER_TOKENS, _is_reviewer_job, prior_attempt_failed, escalate_claude_model,
)
from cv_emit.recall import (  # noqa: E402
    RECALL_ENGINE_DEFAULT, RECALL_TIMEOUT_SEC, RECALL_EVIDENCE_MAX, RECALL_REASON_LABELS,
    TIER_RAISE, RECALL_REVIEW_CLAUSE, _recall_ms, _recall_unavailable, run_recall_check,
    RECALL_TOP, RECALL_SEARCH_TIMEOUT_SEC, RECALL_QUERY_MAX, RECALL_SNIPPET_MAX, RECALL_FIELD_MAX,
    RECALL_BLOCK_MAX_BYTES, RECALL_HEADING, RECALL_FRAMING, RECALL_END, RECALL_CHARS_PER_TOKEN,
    RECALL_EXPAND, _one_line, _quoted, _hit_snippet, normalize_hits, render_recall_block,
    _cut_words, review_recall_query, _search_unavailable, run_recall_search, recall_check_path,
    load_recall_argument,
)
from cv_emit.prompts import (  # noqa: E402
    worker_prompt_path, launch_argv_path, baseline_pin_path, read_pinned_baseline, _job_interfaces,
    _constraint_lines, _interface_lines, render_worker_prompt,
)
from cv_emit.plan import (  # noqa: E402
    EXTERNAL_WORKER_TIMEOUT_CAP, PROVISION_TIMEOUT_DEFAULT, _provision_spec,
    _toolchain_artifacts_spec, build_launch_argv, _shell_join, _worktree_base_is_head,
    _agent_isolation_downgraded, _serialize_unattributable_waves, build_plan,
)
from cv_emit.script_js import (  # noqa: E402
    IMPLEMENT_SCHEMA, GATE_SCHEMA, FINALIZE_SCHEMA, RECORD_SCHEMA, INTEGRATED_JOBS_SCHEMA,
    _implement_prompt, _gate_command, emit_script, JS_TEMPLATE,
)
from cv_emit.gate import (  # noqa: E402
    _file_digest, write_preexisting, read_preexisting_unchanged, RUN_DIR_EXEMPT_BY_NAME,
    RUN_DIR_EXEMPT_ATTEMPTS, RUN_DIR_EXEMPT_SUPERSEDED, run_dir_owned_by_name,
    _preexisting_snapshot, _run_scope_check, _run_test_floor, _resolve_test_contract,
    _lane_map_worktree_for, cmd_gate_receipt,
)
from cv_emit.record import (  # noqa: E402
    _stage_paths, read_sealed_patch, apply_patch, merge_back, TESTS_SCOPES,
    _tests_block_from_floor, TRIAGE_OUTCOMES_DEFAULT, TERMINAL_JOB_STATES, _import_triage_outcomes,
    _run_test_result, _maybe_append_run_actual, _UUID_RE, external_session_id, _job_result_from,
    VERDICT_DISAGREEMENT_MESSAGE, _bind_receipt, cmd_record, _gate_mode_from_receipt,
)
from cv_emit.finalize import (  # noqa: E402
    _stage_run_bookkeeping, _commit_paths, _retire_lane_map, _retire_run_lock, _load_manifest_dict,
    cmd_finalize_wave,
)
from cv_emit.lane import (  # noqa: E402
    _prior_attempt_concluded, _resume_in_place, _reattempt_guidance, _stale_attempt_pins,
    SUPERSEDE_REHASH, _retire_snapshot, _supersede_attempt, cmd_register_lane, cmd_resume_prepare,
    _leftover_violations, cmd_integrated_jobs,
)
from cv_emit.emit import (  # noqa: E402
    ENGINE_PROBE_ENV, ENGINE_PROBE_SNIPPET, engine_probe_report, cmd_emit, SUBCOMMANDS,
)
from cv_emit.selftest import (  # noqa: E402
    _js_parses, _run_emitted_wave_loop, _FAILURES, _PASSES, _quiet, _cfg_of, _check,
    _tiny_manifest, _with_body, _plan_for, _init_repo, selftest,
)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        print("usage: compound-v-emit-workflow.py "
              "{emit,gate-receipt,record,finalize-wave,register-lane,resume-prepare,"
              "integrated-jobs} ... "
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
