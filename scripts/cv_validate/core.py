"""validate() and validate_text(): every invariant over a parsed manifest."""

from .yamlload import ManifestParseError, load_yaml
from .globs import glob_match, globs_overlap
from .rules import (
    VALID_TIERS, VALID_EFFORTS, VALID_BACKENDS, VALID_ISOLATIONS, VALID_RUNS,
    VALID_STANCES, TIMEOUT_SEC_MIN, TIMEOUT_SEC_MAX, VALID_TEST_SCOPES,
    DEFAULT_TEST_SCOPE, TOPLEVEL_REQUIRED, JOB_REQUIRED, _id_is_safe, _is_reviewer)
from .fastpath import _validate_fast_path
from .triage import _validate_triage, _validate_cross_model_receipt
from .blocks import (
    _validate_test_contract, _validate_retry, _validate_provision,
    _validate_toolchain_artifacts, _validate_global_constraints, _validate_interfaces)


def validate(manifest, mode=None, repo_root=None, config_path=None,
             receipt_path=None, manifest_bytes=None, diff_root=None,
             expected_attempt=None, require_triage=False, taxonomy_path=None,
             cross_model_receipt=None, expected_diff_digest=None):
    """Return a list of violation strings; empty list means valid.

    ``mode``/``repo_root``/``config_path``/``receipt_path``/``diff_root`` drive the
    v2.9 conditional fast-path checks (only when a top-level ``fast_path`` block is
    present); a legacy manifest ignores them entirely (backward compatible).
    ``diff_root`` (CR-CRIT-1) is the worker's linked worktree the producer hashed;
    the post-review final-diff recompute runs there, falling back to ``repo_root``
    only when it is unset.

    ``require_triage`` (v3.0, Feature A2) turns the top-level ``triage`` block from
    optional into mandatory. It is DEFAULT OFF in every mode; ``/v:dispatch`` passes
    it on every live dispatch and the CI historical sweep does not.
    ``taxonomy_path`` overrides where the ``taxonomy_digest`` is checked against.

    ``cross_model_receipt`` (v3.4.1) is the path to the SCOPED+ cross-model receipt;
    when set, the receipt is verified against its schema and bound to this manifest's
    ``run_id`` / ``triage.pre_eval_id``, with ``expected_diff_digest`` re-asserting
    the bytes the caller sealed. It is independent of ``require_triage``: `/v:dispatch`
    step 8 passes it only for a ``scoped_plus`` run, after the review has run."""
    problems = []

    if not isinstance(manifest, dict):
        return ["manifest is not a mapping"]

    # Top-level required fields (validated BEFORE invariant checks).
    for field in TOPLEVEL_REQUIRED:
        if manifest.get(field) in (None, "", [], {}):
            problems.append("manifest missing required top-level field '%s'" % field)

    # Structural TYPE checks on top-level fields (wrong type is its own,
    # specific violation — distinct from "missing"). Only checked when the
    # field is present and non-None, so the missing-field loop above owns
    # absence; this loop owns mis-typing.
    if "jobs" in manifest and manifest.get("jobs") is not None:
        jv = manifest.get("jobs")
        if not isinstance(jv, list) or not jv:
            problems.append("manifest 'jobs' must be a non-empty list")
    if "acceptance_criteria" in manifest and manifest.get("acceptance_criteria") is not None:
        if not isinstance(manifest.get("acceptance_criteria"), list):
            problems.append("manifest 'acceptance_criteria' must be a list")
    if "audits" in manifest and manifest.get("audits") is not None:
        if not isinstance(manifest.get("audits"), dict):
            problems.append("manifest 'audits' must be a mapping")
    if "max_parallel" in manifest and manifest.get("max_parallel") is not None:
        mp = manifest.get("max_parallel")
        # bool is an int subclass in Python; a YAML true/false here is wrong.
        if not isinstance(mp, int) or isinstance(mp, bool):
            problems.append("manifest 'max_parallel' must be an int")
    for _sf in ("run_id", "feature", "spec_path", "plan_path"):
        if _sf in manifest and manifest.get(_sf) is not None:
            if not isinstance(manifest.get(_sf), str):
                problems.append("manifest '%s' must be a string" % _sf)

    # routing_stance enum (only when present).
    stance = manifest.get("routing_stance")
    if stance is not None and str(stance).lower() not in VALID_STANCES:
        problems.append(
            "manifest routing_stance '%s' invalid (expected one of %s)"
            % (stance, ", ".join(VALID_STANCES))
        )

    # Top-level run_id id-safety (becomes a run-dir / path segment).
    run_id = manifest.get("run_id")
    if run_id is not None and run_id != "" and not _id_is_safe(run_id):
        problems.append(
            "manifest run_id '%s' has invalid characters "
            "(allowed: A-Za-z0-9._-, not . or ..)" % run_id
        )

    # v3.0 (Feature A2): the triage block, only when the caller demands it. Checked
    # BEFORE the jobs early-return so a missing block is reported even for a manifest
    # that is broken in other ways.
    if require_triage:
        problems.extend(_validate_triage(manifest, repo_root, taxonomy_path))

    # v3.4.1: the SCOPED+ cross-model receipt. Checked here, before the jobs
    # early-return, for the same reason the triage block is — a manifest broken in
    # some other way must not hide a missing or stale second opinion.
    if cross_model_receipt not in (None, ""):
        problems.extend(_validate_cross_model_receipt(
            manifest, cross_model_receipt, expected_diff_digest))

    # v3.4.8 (Task B): the optional top-level `retry` block. Checked here, before
    # the jobs early-return, for the same reason triage/cross_model_receipt are —
    # a manifest broken in some other way must not hide a malformed retry block.
    problems.extend(_validate_retry(manifest))

    # v3.4.17: the optional top-level `global_constraints` list — the plan's
    # `## Global Constraints` lines, verbatim. Checked here, before the jobs
    # early-return, for the same reason the blocks above are: a manifest broken
    # in some other way must not hide a malformed constraints list.
    problems.extend(_validate_global_constraints(manifest))

    # provision_command / provision_timeout_s: same reasoning as the blocks above —
    # checked before the jobs early-return so a broken manifest never hides them.
    problems.extend(_validate_provision(manifest))

    # toolchain_artifacts (issue #22): same reasoning as the blocks above —
    # checked before the jobs early-return so a broken manifest never hides a
    # catch-all glob or a malformed list.
    problems.extend(_validate_toolchain_artifacts(manifest))

    jobs = manifest.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        problems.append("manifest has no non-empty 'jobs' list")
        return problems

    # Structural sanity + collect per-job globs.
    seen_ids = set()
    job_globs = []  # (job_id, [globs])
    job_scopes = []  # (job_id, test_scope or None) — v3.0 Feature B2
    job_deps = []   # (job_id, [depends_on ids]) — for ref + cycle validation
    all_ids = []    # job ids in declared order (for cycle reporting)
    for idx, job in enumerate(jobs):
        if not isinstance(job, dict):
            problems.append("job #%d is not a mapping" % idx)
            continue
        jid = job.get("id")
        if not jid:
            problems.append("job #%d missing 'id'" % idx)
            jid = "<job#%d>" % idx
        elif not _id_is_safe(jid):
            problems.append(
                "job '%s' id has invalid characters "
                "(allowed: A-Za-z0-9._-, not . or ..)" % jid
            )
        if jid in seen_ids:
            problems.append("duplicate job id '%s'" % jid)
        seen_ids.add(jid)
        all_ids.append(jid)

        # Collect depends_on (validated for refs + cycles after the loop).
        dep = job.get("depends_on")
        if dep is None:
            deps = []
        elif isinstance(dep, list):
            deps = [str(d) for d in dep]
        else:
            problems.append("job '%s' depends_on must be a list" % jid)
            deps = []
        job_deps.append((jid, deps))

        # Per-job required fields (validated BEFORE the invariant checks below).
        for field in JOB_REQUIRED:
            val = job.get(field)
            # write_allowed may legitimately be an empty list (reviewers); only
            # flag it when the key is entirely absent.
            if field == "write_allowed":
                if "write_allowed" not in job:
                    problems.append("job '%s' missing required field 'write_allowed'" % jid)
                continue
            if val in (None, "", [], {}):
                problems.append("job '%s' missing required field '%s'" % (jid, field))

        # Per-job structural TYPE checks: these three are list-valued fields.
        # (write_allowed list-ness is also re-checked below where it is consumed;
        # checking here keeps the violation specific and ordered with the job.)
        for _lf in ("write_allowed", "read_allowed", "acceptance"):
            if _lf in job and job.get(_lf) is not None:
                if not isinstance(job.get(_lf), list):
                    problems.append("job '%s' %s must be a list" % (jid, _lf))

        # v3.4.17: the optional per-job `interfaces` mapping — the plan task's
        # `**Interfaces:**` block, verbatim. ABSENT is valid (a pre-6.2.0 plan
        # has no such block); either key may be absent on its own.
        problems.extend(_validate_interfaces(job, jid))

        # never-Haiku policy (execution layer). The frontmatter linter only sees
        # agent/skill frontmatter; a manifest job can pin an execution-layer
        # `model` override, so an explicit model containing "haiku" (any case,
        # e.g. `haiku` or `claude-haiku-...`) must be rejected here too.
        model_raw = job.get("model")
        if model_raw is not None and "haiku" in str(model_raw).lower():
            problems.append(
                "job '%s' model '%s' violates the never-Haiku policy "
                "(no Haiku as an execution-layer model override)"
                % (jid, model_raw)
            )

        if not job.get("backend"):
            problems.append("job '%s' missing 'backend'" % jid)
        else:
            backend_val = str(job.get("backend")).lower()
            if backend_val not in VALID_BACKENDS:
                problems.append(
                    "job '%s' backend '%s' invalid (expected one of %s)"
                    % (jid, job.get("backend"), ", ".join(VALID_BACKENDS))
                )

        # isolation / run enum checks (only when present).
        iso_val = job.get("isolation")
        if iso_val is not None and str(iso_val).lower() not in VALID_ISOLATIONS:
            problems.append(
                "job '%s' isolation '%s' invalid (expected one of %s)"
                % (jid, iso_val, ", ".join(VALID_ISOLATIONS))
            )
        run_val = job.get("run")
        if run_val is not None and str(run_val).lower() not in VALID_RUNS:
            problems.append(
                "job '%s' run '%s' invalid (expected one of %s)"
                % (jid, run_val, ", ".join(VALID_RUNS))
            )

        # Invariant 6: parallel ⇒ worktree (per-job scope attribution). A repo-wide
        # git diff cannot attribute a parallel direct job's writes, so parallel jobs
        # MUST be isolated in a worktree; direct is only valid with serial.
        if (str(run_val).lower() == "parallel"
                and str(iso_val).lower() == "direct"):
            problems.append(
                "job '%s' uses run: parallel with isolation: direct — parallel "
                "jobs require worktree isolation for per-job scope attribution; "
                "use isolation: worktree or run: serial" % jid
            )

        # Invariant 5: intent routing — every job must carry model OR tier
        # (model is now an optional override; tier routes by intent).
        has_model = bool(job.get("model"))
        has_tier = bool(job.get("tier"))
        if not has_model and not has_tier:
            problems.append(
                "job '%s' must have 'model' or 'tier' "
                "(model is an optional override)" % jid
            )

        # Invariant 5: tier / effort enum validation (only when present).
        tier_val = job.get("tier")
        if tier_val is not None and str(tier_val).lower() not in VALID_TIERS:
            problems.append(
                "job '%s' tier '%s' invalid (expected one of %s)"
                % (jid, tier_val, ", ".join(VALID_TIERS))
            )
        effort_val = job.get("effort")
        if effort_val is not None and str(effort_val).lower() not in VALID_EFFORTS:
            problems.append(
                "job '%s' effort '%s' invalid (expected one of %s)"
                % (jid, effort_val, ", ".join(VALID_EFFORTS))
            )

        # xhigh ⇒ codex only: `effort: xhigh` is valid iff `backend: codex`
        # (every other backend rejects it with a clear error naming the rule).
        if (effort_val is not None and str(effort_val).lower() == "xhigh"
                and str(job.get("backend", "")).lower() != "codex"):
            problems.append(
                "job '%s' has effort 'xhigh' with backend '%s': xhigh is "
                "codex-only (kernel: model_reasoning_effort); use high"
                % (jid, job.get("backend"))
            )

        # Optional `timeout_sec` (only when present). ABSENT is valid and means
        # the worker script's own DEFAULT_TIMEOUT_SEC=900 — untouched, so every
        # existing manifest behaves exactly as it did. NO unknown-key rejection is
        # introduced anywhere in this validator: adding one would retroactively
        # invalidate the manifests already committed under
        # docs/superpowers/execution/.
        if "timeout_sec" in job and job.get("timeout_sec") is not None:
            ts = job.get("timeout_sec")
            # bool is an int subclass in Python; a YAML true/false here is wrong
            # (same guard as `max_parallel` above).
            if not isinstance(ts, int) or isinstance(ts, bool):
                problems.append(
                    "job '%s' timeout_sec must be an integer number of seconds "
                    "(got %r)" % (jid, ts)
                )
            elif ts < TIMEOUT_SEC_MIN or ts > TIMEOUT_SEC_MAX:
                problems.append(
                    "job '%s' timeout_sec %d out of range (must be between %d "
                    "and %d seconds inclusive)"
                    % (jid, ts, TIMEOUT_SEC_MIN, TIMEOUT_SEC_MAX)
                )

        # v3.0 (Feature B2): optional per-job `test_scope`. ABSENT is valid and
        # means `full` — which is what every manifest committed before 3.0 relies
        # on. The cross-check against `test_contract` runs after this loop, where
        # the contract is in scope.
        scope_val = job.get("test_scope")
        if scope_val is not None and str(scope_val) not in VALID_TEST_SCOPES:
            problems.append(
                "job '%s' test_scope '%s' invalid (expected one of %s)"
                % (jid, scope_val, ", ".join(VALID_TEST_SCOPES))
            )
            scope_val = None
        job_scopes.append((jid, str(scope_val) if scope_val is not None
                           else DEFAULT_TEST_SCOPE))

        wa = job.get("write_allowed")
        if wa is None:
            wa = []
        if not isinstance(wa, list):
            problems.append("job '%s' write_allowed is not a list" % jid)
            wa = []
        job_globs.append((jid, [str(g) for g in wa]))

        # Invariant 2: codex => worktree, antigravity => worktree, cursor => worktree,
        # opencode => worktree. All four are EXTERNAL workers. Codex has a kernel
        # sandbox scoped to a directory; antigravity and cursor have NO kernel
        # write-confinement at all (antigravity runs with
        # --dangerously-skip-permissions; cursor's headless `-f` grants arbitrary
        # write+shell); opencode has NO kernel write-confinement and defaults to
        # allowing all operations. For all four, worktree + git-diff is the ONLY
        # file-scope enforcement that actually holds. A non-worktree external worker
        # cannot be deterministically attributed and is rejected.
        backend_lc = str(job.get("backend", "")).lower()
        if backend_lc in ("codex", "antigravity", "cursor", "opencode"):
            if str(job.get("isolation", "")).lower() != "worktree":
                problems.append(
                    "job '%s' uses backend %s but isolation is '%s' "
                    "(%s requires worktree)"
                    % (jid, backend_lc, job.get("isolation"), backend_lc)
                )

        # WORKER-ONLY enforcement: opencode is a lower-trust, opt-in backend
        # (see adapter-opencode.md) meant for IMPLEMENTER jobs only. A reviewer
        # job routed to it would silently satisfy the Review Gate's opus/deep
        # guarantee through a low-trust external router instead of Claude Opus,
        # defeating the guarantee entirely. Reject unconditionally, independent
        # of tier/model — a reviewer job must never carry backend: opencode,
        # full stop.
        if _is_reviewer(job) and backend_lc in ("opencode",):
            problems.append(
                "reviewer job '%s' uses backend '%s' — opencode is a "
                "lower-trust, opt-in, WORKER-ONLY backend (see "
                "adapter-opencode.md) and must never be "
                "used for a reviewer job; route reviewers to backend: "
                "claude with tier: deep or model: opus"
                % (jid, backend_lc)
            )

        # opencode provider/model shape: every EXPLICIT opencode model
        # override must be a genuine non-empty "provider/model" STRING (a
        # bare name would silently pass here but fail opencode's own model
        # resolution / the worker's `-m` argument at run time). Only checked
        # when a model key is actually present — a tier-only job resolves
        # through compound-v-resolve-model.py's own shape check at resolution
        # time. A NON-STRING model (int/list/dict from YAML) is itself a
        # violation: it can never be a valid provider/model string and must
        # NOT slip through by skipping the check.
        if backend_lc == "opencode" and "model" in job:
            m_val = job.get("model")
            _shaped = False
            if isinstance(m_val, str) and m_val.strip():
                _prov, _sep, _rest = m_val.partition("/")
                _shaped = bool(_sep) and bool(_prov.strip()) and bool(_rest.strip())
            if not _shaped:
                problems.append(
                    "job '%s' backend opencode has model %r which is not a "
                    "valid 'provider/model' string (must be a non-empty "
                    "string, non-empty on both sides of exactly one '/')"
                    % (jid, m_val)
                )

        # Invariant 3: reviewers => deep reasoning OR STRONGER. Satisfied by
        # tier: deep / frontier, or model: opus / fable. The rule was written
        # in v3.0.5 before the frontier tier existed and read "deep or opus"
        # literally, which refused a reviewer lifted to Fable when Opus was
        # overloaded (three API 529s in a row, 2026-09-03, finding 119) — a
        # stronger seat failing a "strong enough" check. Never weaker.
        if _is_reviewer(job):
            is_deep = str(job.get("tier", "")).lower() in ("deep", "frontier")
            is_opus = str(job.get("model", "")).lower() in ("opus", "fable")
            if not is_deep and not is_opus:
                problems.append(
                    "reviewer job '%s' must resolve to deep reasoning or stronger "
                    "(tier: deep|frontier or model: opus|fable), got tier='%s' model='%s'"
                    % (jid, job.get("tier"), job.get("model"))
                )

        # Invariant 4 (structural half): shared_foundation => serial.
        if str(job.get("type", "")).lower() == "shared_foundation":
            if str(job.get("run", "")).lower() != "serial":
                problems.append(
                    "shared_foundation job '%s' must run serial, got '%s'"
                    % (jid, job.get("run"))
                )

    # v3.0 (Feature B2): the test contract + the scopes collected above.
    problems.extend(_validate_test_contract(manifest, job_scopes))

    # Invariant 1: disjoint write scope across distinct jobs.
    for a_i in range(len(job_globs)):
        id_a, globs_a = job_globs[a_i]
        for b_i in range(a_i + 1, len(job_globs)):
            id_b, globs_b = job_globs[b_i]
            for ga in globs_a:
                for gb in globs_b:
                    if globs_overlap(ga, gb):
                        problems.append(
                            "write_allowed overlap: job '%s' (%s) and job '%s' "
                            "(%s) can both own the same path"
                            % (id_a, ga, id_b, gb)
                        )

    # depends_on validation: every referenced id must exist (no dangling ref),
    # and the dependency graph must be acyclic (no cycles).
    id_set = set(all_ids)
    dep_graph = {}  # id -> list of dep ids that actually exist in id_set
    for jid, deps in job_deps:
        existing = []
        for d in deps:
            if d not in id_set:
                problems.append(
                    "job '%s' depends_on references unknown job id '%s'"
                    % (jid, d)
                )
            else:
                existing.append(d)
        # Last writer wins on duplicate ids; harmless for cycle detection.
        dep_graph[jid] = existing

    # Cycle detection via iterative DFS with a recursion stack. Reports the
    # first cycle found, naming the jobs on it.
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {}
    for nid in all_ids:
        color.setdefault(nid, WHITE)
    cycle_found = [None]

    def _find_cycle(start):
        # stack holds (node, iterator over its deps); path mirrors the GRAY set.
        stack = [(start, iter(dep_graph.get(start, [])))]
        path = [start]
        color[start] = GRAY
        while stack:
            node, it = stack[-1]
            advanced = False
            for nxt in it:
                if color.get(nxt, WHITE) == GRAY:
                    # Found a back-edge: nxt..node is the cycle.
                    idx = path.index(nxt)
                    cycle_found[0] = path[idx:] + [nxt]
                    return True
                if color.get(nxt, WHITE) == WHITE:
                    color[nxt] = GRAY
                    stack.append((nxt, iter(dep_graph.get(nxt, []))))
                    path.append(nxt)
                    advanced = True
                    break
            if advanced:
                continue
            color[node] = BLACK
            stack.pop()
            path.pop()
        return False

    for nid in all_ids:
        if color.get(nid, WHITE) == WHITE:
            if _find_cycle(nid):
                break
    if cycle_found[0]:
        problems.append(
            "depends_on cycle detected: %s" % " -> ".join(cycle_found[0])
        )

    # Invariant 4 (resource half): declared shared resources must be owned by a
    # shared_foundation serial job.
    shared = manifest.get("shared_resources")
    if isinstance(shared, list) and shared:
        foundation_jobs = [
            j
            for j in jobs
            if isinstance(j, dict)
            and str(j.get("type", "")).lower() == "shared_foundation"
            and str(j.get("run", "")).lower() == "serial"
        ]
        for res in shared:
            res = str(res)
            owned = False
            for j in foundation_jobs:
                wa = j.get("write_allowed") or []
                if isinstance(wa, list):
                    for g in wa:
                        if glob_match(res, str(g)) or res == str(g):
                            owned = True
                            break
                if owned:
                    break
            if not owned:
                problems.append(
                    "shared resource '%s' is not written by any "
                    "shared_foundation serial job" % res
                )

    # v2.9 conditional fast-path: only engaged when a top-level `fast_path` block
    # is present (a legacy manifest is fully unaffected — backward compatible).
    if "fast_path" in manifest and manifest.get("fast_path") is not None:
        problems.extend(_validate_fast_path(
            manifest, manifest.get("fast_path"), mode, repo_root,
            config_path, receipt_path, manifest_bytes, diff_root=diff_root,
            expected_attempt=expected_attempt))

    return problems


def validate_text(text, mode=None, repo_root=None, config_path=None,
                  receipt_path=None, manifest_bytes=None, diff_root=None,
                  expected_attempt=None, require_triage=False, taxonomy_path=None,
                  cross_model_receipt=None, expected_diff_digest=None):
    try:
        data = load_yaml(text)
    except ManifestParseError as exc:
        return [str(exc)]
    # The manifest_digest binding (CR5-6) is computed over the manifest's raw
    # bytes. When a caller supplies the exact on-disk bytes (main() does), use
    # them verbatim; otherwise fall back to the UTF-8 encoding of the text.
    if manifest_bytes is None and isinstance(text, str):
        manifest_bytes = text.encode("utf-8")
    return validate(data, mode=mode, repo_root=repo_root,
                    config_path=config_path, receipt_path=receipt_path,
                    manifest_bytes=manifest_bytes, diff_root=diff_root,
                    expected_attempt=expected_attempt,
                    require_triage=require_triage, taxonomy_path=taxonomy_path,
                    cross_model_receipt=cross_model_receipt,
                    expected_diff_digest=expected_diff_digest)
