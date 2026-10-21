"""record: merge-back helpers, the job_result builder and the Record stage's command."""

from __future__ import annotations

import os
import argparse
import hashlib
import json
import re
import subprocess

from .util import (
    HERE, _git, _load_yaml, _atomic_write, _run_dir_lock, _read_json, test_contract_path,
    _load_state, _save_state, _manifest_job,
)
from .digest import (
    _load_module_from_path, manifest_digest_fault, patch_artifact_path,
)
from .retry import (
    _sanitize_retry_meta, apply_retry_meta,
)
from .prompts import (
    read_pinned_baseline,
)
from .plan import (
    _worktree_base_is_head,
)


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

    `-f` (force) because a path may sit under a GITIGNORED PARENT. A repository
    that ignores `docs/` — a generated-docs convention, and not a rare one —
    makes every run-directory artefact invisible to a plain `git add`, which
    fails with "ignored by one of your .gitignore files" and takes the whole
    finalize with it. The pathspec is not a wildcard: every path here was named
    by the gate's `files_changed` or by the pipeline's own bookkeeping list, so
    forcing adds exactly what was already approved and nothing a scan swept up.
    """
    for path in paths:
        if not path:
            continue
        rc, _, err = _git(worktree, ["add", "-A", "-f", "--", path])
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
                     contract_declared=False,
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
    result_summary_suffix = ""
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

    # A CONTRACTED FLOOR THAT RESOLVED TO NO COMMAND IS NOT A PASS.
    #
    # `run_test_floor` initialises every result `{"passed": False, "merge_blocked":
    # True}` — refusal is the floor's default state — and ADR 0003 relies on it:
    # "already merge-blocking and already fail-closed on an empty command", with
    # Consequences: "A job reporting no test command at all is a FAIL, not a pass."
    # `spec-reviewer.md` enforces that in prose (ISSUE: NO_TEST_EVIDENCE, "Silence
    # is not success").
    #
    # The fast path's own consumer honours it (`build_review_spec` gate 1 refuses on
    # `not passed or merge_blocked`). THIS consumer did not: it reads the floor only
    # through `_tests_block_from_floor`, which returns None when no check carries a
    # `checker`, so `merge_blocked: True` was never consulted and the job kept the
    # scope verdict's `success`. One floor document, two consumers, opposite
    # conclusions. Dogfood 14 moved the RED half of the rule from prose into this
    # function; this is the empty half, at the same layer, for the same reason.
    #
    # The predicate is the MANIFEST's declaration, not the resolved slice. `contract`
    # above is read from `jobs/<id>.test-contract.json`, which does not exist when
    # resolution FAILED — precisely the case that must be caught. Keying on it would
    # leave the reachable hole open.
    #
    # Unchanged: an uncontracted manifest still records `success` with no `tests`
    # object — "no floor at all is not a failure".
    if status == "success" and tests_block is None and contract_declared:
        if tests is None:
            # No floor document at all: `fastpath-run.py` was absent or died before
            # writing JSON. The machinery IS broken here, so `error`, not `blocked`.
            status = "error"
        else:
            status = "blocked"
        _floor_reasons = [str(r) for r in ((tests or {}).get("reasons") or []) if r]
        if _floor_reasons:
            # Without this the refusal carries no cause: the floor's own
            # "test contract did not resolve (fail-closed): ..." is dropped and the
            # summary falls back to the job title, which is a refusal for an
            # unstated reason.
            result_summary_suffix = "; ".join(_floor_reasons[:3])
        else:
            result_summary_suffix = ("the manifest declares a test_contract but the "
                                     "floor resolved to no command")

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
                    + (verdict.get("reason") or (job.get("title") or job.get("id") or ""))
                    + (" - " + result_summary_suffix if result_summary_suffix else "")),
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


VERDICT_DISAGREEMENT_MESSAGE = (
    "gate verdict disagreement: receipt %s says %s, the workflow held %s; "
    "this comparison establishes no cause"
)


def _bind_receipt(verdict, receipt_file, job_id, exp_verdict, exp_digest):
    """Bind a receipt read from a FILE to what the workflow saw. (verdict, disagreement).

    WHY THE RECEIPT WINS ON THE VERDICT FIELD, AND ONLY THERE.
    The receipt is the artefact the gate wrote and the artefact the integration
    authority re-derives against; the workflow's `--expect-verdict` is a value
    carried through an agent's transport, and an agent that mis-reads or re-types
    one field is the likelier of the two failures. Until 3.6 a mismatch produced
    `status: error` and a summary asserting "the receipt was rewritten between
    Gate and Record" — a CAUSE the code never established. A difference between
    two readings is a difference; it is recorded as one, both values named, and
    the receipt's own verdict is what gets recorded.

    WHAT RECEIPT-WINS ACTUALLY RESTS ON — three checks this code performs:

      1. the receipt is read from a path the caller named, and its `job_id` must
         equal the job being recorded (a receipt for another job is an `error`,
         never a silent record against the wrong lane);
      2. `diff_digest` must match the workflow's, when the workflow holds one —
         the content binding. A digest mismatch is FORGERY, not a disagreement,
         and it is checked FIRST so a receipt that mismatches both surfaces the
         forgery rather than the softer verdict finding;
      3. a workflow that bound the verdict but sent NO digest, against a receipt
         that carries one, is a degraded transport — refused, because a missing
         digest is not agreement. Treating it as agreement is exactly the hole a
         forger would use: rewrite the receipt AND drop the digest flag.

    There is deliberately NO manifest_digest condition here. GATE_SCHEMA carries
    no such field and `gate-receipt` writes none, so a comment claiming the
    manifest is bound *by the receipt* would name a check the code cannot run.
    The manifest IS bound, on both sides and independently: `manifest_digest_fault`
    compares it against the emit-time digest in `gate-receipt` and again in
    `record`. That is the whole of it.
    """
    receipt_verdict = str(verdict.get("verdict"))
    path = receipt_file or ""

    receipt_job = verdict.get("job_id")
    if isinstance(receipt_job, str) and receipt_job.strip() and receipt_job != job_id:
        # No `verdict_disagreement` on this branch: that field's `field` is a
        # two-value vocabulary (`verdict` | `diff_digest`) other jobs render and
        # validate against, and a receipt for another job is not a disagreement
        # about a gate — it is the wrong document. The reason names both ids.
        return {"verdict": "error", "reason":
                "receipt %s is job %r, but this record is for %r — a receipt is "
                "bound to the job it was written for"
                % (path, receipt_job, job_id)}, None

    receipt_digest = verdict.get("diff_digest")
    receipt_digest_s = "" if receipt_digest is None else str(receipt_digest)
    if exp_digest and receipt_digest_s != exp_digest:
        return {"verdict": "error", "reason":
                "receipt %s carries diff_digest %s, the workflow held %s — the "
                "digests bind the receipt to the tree the gate measured, so a "
                "mismatch is refused rather than recorded"
                % (path, receipt_digest_s or "none", exp_digest)}, {
                    "field": "diff_digest", "receipt": receipt_digest_s,
                    "workflow": exp_digest, "receipt_path": path}
    if exp_verdict and not exp_digest and receipt_digest_s:
        return {"verdict": "error", "reason":
                "receipt %s carries diff_digest %s and the workflow passed none — "
                "an unbound digest is not an agreeing one, and the record refuses "
                "rather than accepting a receipt nothing binds to a tree"
                % (path, receipt_digest_s)}, {
                    "field": "diff_digest", "receipt": receipt_digest_s,
                    "workflow": "", "receipt_path": path}

    if exp_verdict and receipt_verdict != exp_verdict:
        return verdict, {"field": "verdict", "receipt": receipt_verdict,
                         "workflow": exp_verdict, "receipt_path": path}
    return verdict, None


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
    verdict_disagreement = None
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
                verdict, verdict_disagreement = _bind_receipt(
                    verdict, args.verdict_file, job_id, _exp_v, _exp_d)
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
            and not _worktree_base_is_head(args.repo_root):
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

    # Whether the MANIFEST declared a floor — not whether the slice resolved. The
    # slice is absent exactly when resolution failed, which is the case that must
    # not pass silently. Mirrors `declares_contract` in build_plan.
    _contract_declared = isinstance(manifest.get("test_contract"), dict) and bool(
        manifest.get("test_contract"))
    result = _job_result_from(verdict, job, state_job, tests=tests,
                              contract=contract, isolation=isolation, tier=tier,
                              contract_declared=_contract_declared)

    # ---- the two readings differed; say so, and say nothing more ------------
    # It rides on the ACK and on state.json, never as a new top-level key on the
    # result: schemas/job_result.schema.json is `additionalProperties: false`,
    # and that file is outside this change's write lane. The result carries the
    # fact where the schema allows one — in `summary`, naming both values.
    if verdict_disagreement:
        ack["verdict_disagreement"] = verdict_disagreement
        state_job["verdict_disagreement"] = verdict_disagreement
        if verdict_disagreement.get("field") == "verdict":
            _msg = VERDICT_DISAGREEMENT_MESSAGE % (
                verdict_disagreement.get("receipt_path") or "(inline)",
                verdict_disagreement.get("receipt"),
                verdict_disagreement.get("workflow"))
            _prior = str(result.get("summary") or "").strip()
            result["summary"] = (_prior + " — " + _msg) if _prior else _msg

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
