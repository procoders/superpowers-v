"""Fast-path support: sibling loading, git containment, schemas and sealed receipts."""

import json
import os
import re
import sys

from . import _SCRIPTS_DIR


# --------------------------------------------------------------------------- #
# v2.9 conditional fast-path support (only engaged when a top-level `fast_path`
# block is present). Sibling scripts are loaded by path (their filenames have
# hyphens, so they are not importable module names).
# --------------------------------------------------------------------------- #
FASTPATH_MODES = ("pre-dispatch", "post-review")
_EXEC_DIR = os.path.join("docs", "superpowers", "execution")
_RECEIPT_SUBPATH = os.path.join("review", "receipt.json")
_RECEIPT_SCHEMA = os.path.join("schemas", "fastpath-review-receipt.schema.json")
# v3.4.1 — the SCOPED+ cross-model receipt and the advisory review nested inside it.
_CROSS_MODEL_SCHEMA = os.path.join("schemas", "cross-model-receipt.schema.json")
_PLAN_REVIEW_SCHEMA = os.path.join("schemas", "plan-review.schema.json")

# The two reviewer_backend values a cross-model receipt may carry, and the
# `cross_model` boolean each one is honest at. codex is a genuine second
# opinion (a different model family); claude-advisor (v2.12) is the SAME
# family as the implementer, run instead when Codex is unavailable/declined.
_CROSS_MODEL_EXPECTED = {"codex": True, "claude-advisor": False}
# Bounded `git diff` capture for the anti-stale-replay diff-digest recompute —
# MUST match the producer's cap (compound-v-fastpath-run.py MAX_DIFF_BYTES) so a
# receipt written by the producer content-addresses to the same value here.
_MAX_DIFF_BYTES = 1_000_000
_GIT_DIFF_TIMEOUT_S = 30
# Bounded wall-clock cap for the HEAD-containment `git cat-file -e` probe, which is
# routed through the shared process-group timeout supervisor (MED-8).
_GIT_PROBE_TIMEOUT_S = 30
# MED-8 sentinel: git IS present (the tree has a `.git`) but the HEAD-containment
# probe could NOT complete — the supervisor/launch itself failed (None → mapped
# here), the probe timed out (supervisor exit 124), or the git binary is missing
# (exit 127). This is DISTINCT from ``None`` (no `.git` at all → the legitimate
# no-git degrade the pre-dispatch fixtures rely on): a ``require_committed`` caller
# must fail CLOSED on this sentinel rather than silently skip the containment check.
_GIT_UNAVAILABLE = object()

_SIBLING_CACHE = {}


def _load_sibling(basename):
    import importlib.util

    here = _SCRIPTS_DIR
    path = os.path.join(here, basename)
    try:
        modname = "cv_" + re.sub(r"[^0-9A-Za-z_]", "_", basename)
        spec = importlib.util.spec_from_file_location(modname, path)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:  # noqa: BLE001 - any load failure -> caller degrades
        return None


def _sibling(basename):
    if basename not in _SIBLING_CACHE:
        _SIBLING_CACHE[basename] = _load_sibling(basename)
    return _SIBLING_CACHE[basename]


def _read_json_file(repo_root, relpath):
    """Read a JSON file relative to ``repo_root``; return (obj, err_or_None)."""
    try:
        with open(os.path.join(repo_root, relpath), "r", encoding="utf-8") as fh:
            return json.load(fh), None
    except Exception as e:  # noqa: BLE001 - any read/parse failure -> fail-closed
        return None, str(e)


def _is_claude_opus(model):
    """A resolved model counts as Claude Opus iff its name contains 'opus'
    (case-insensitive). A config override to sonnet/gpt/etc. therefore fails."""
    return isinstance(model, str) and "opus" in model.lower()


# Canonical content-digest shape: 'sha256:' + 64 hex chars (pre-eval-config.md §2).
_DIGEST_RE = re.compile(r"sha256:[0-9a-fA-F]{64}\Z")


def _is_digest_shaped(v):
    """True iff ``v`` is a well-formed canonical content-digest ('sha256:<64-hex>').
    A missing/non-string/mis-shaped digest is NOT shaped, so a caller can fail
    closed on absence instead of silently skipping the comparison."""
    return isinstance(v, str) and _DIGEST_RE.match(v) is not None


def _is_git_tracked(repo_root, relpath):
    """True/False if a git tree is present (worktree ``.git`` is a FILE, so we test
    existence not is-dir); None when git is unavailable so the caller can skip."""
    import subprocess

    if not os.path.exists(os.path.join(repo_root, ".git")):
        return None
    try:
        r = subprocess.run(
            ["git", "-C", repo_root, "ls-files", "--error-unmatch", relpath],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return r.returncode == 0
    except Exception:  # noqa: BLE001 - git missing/broken -> skip the tracked check
        return None


def _git_via_supervisor(cwd, git_args, timeout_s=_GIT_PROBE_TIMEOUT_S):
    """Run ``git -C cwd <git_args>`` UNDER the shared process-group timeout
    supervisor (``compound-v-run-with-timeout.py``) with ``stdin </dev/null`` and a
    bounded wall-clock cap — never a bare ``subprocess.run(timeout=...)`` on git (the
    external-launch invariant the rest of the pipeline holds; MED-8). Returns the
    git command's own exit code, or ``None`` when the supervisor itself cannot be
    launched (script absent / OSError). A timeout surfaces as 124 and a missing git
    binary as 127 (supervisor conventions); both are fail-closed at the caller."""
    import subprocess

    sup = os.path.join(_SCRIPTS_DIR,
                       "compound-v-run-with-timeout.py")
    if not os.path.isfile(sup):
        return None
    cmd = [sys.executable, sup, "--timeout", str(int(timeout_s)), "--grace", "1",
           "--", "git", "-C", cwd] + list(git_args)
    try:
        r = subprocess.run(
            cmd, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return r.returncode
    except Exception:  # noqa: BLE001 - cannot launch the supervisor -> fail-closed
        return None


def _is_committed_at_head(repo_root, relpath):
    """Whether ``relpath`` exists in the HEAD *commit* tree — committed, not merely
    tracked-or-staged. ``git ls-files`` accepts a newly-STAGED path that is absent
    from every commit; artifacts must live in a commit (execution-manifest.md), so a
    staged-but-uncommitted artifact must fail. Returns:

      * ``True``  — the path is present in a commit at HEAD;
      * ``False`` — git ran cleanly and the object is absent from HEAD (staged-only,
        untracked, or a repo with no commits — ``cat-file -e`` exits 1/128);
      * ``None``  — there is NO ``.git`` at all (the legitimate no-git degrade the
        pre-dispatch fixtures rely on — a fixture with no repo behaves as before);
      * ``_GIT_UNAVAILABLE`` — a ``.git`` IS present but the probe could not COMPLETE
        (supervisor/launch failure, timeout=124, or git-not-found=127). MED-8: a
        ``require_committed`` caller fails CLOSED on this, never silently skips it.

    The probe (``git cat-file -e HEAD:<path>``) runs through the process-group
    timeout supervisor (``stdin </dev/null``, bounded), like every other git read."""
    if not os.path.exists(os.path.join(repo_root, ".git")):
        return None
    rc = _git_via_supervisor(repo_root, ["cat-file", "-e", "HEAD:" + relpath])
    if rc is None or rc in (124, 127):
        # supervisor/launch failure, timeout, or missing git binary while a `.git`
        # IS present -> the probe could not complete -> fail closed (MED-8).
        return _GIT_UNAVAILABLE
    if rc == 0:
        return True
    return False  # git ran; object absent from HEAD (exit 1/128) -> not committed


def _containment_problems(label, relpath, repo_root, must_exist=True,
                          require_committed=False):
    """CR4-6 path containment. The path MUST be normalized, repo-relative (no
    absolute, no ``..`` segment), realpath-under-repo-root (this also rejects any
    escaping symlink in the chain — realpath resolves every link), and a committed
    regular file (never a symlink). Mirrors scope-check.py's realpath containment
    intent; the whole-tree escaping-symlink scan is scope-check.py's job at gate
    time. Returns a list of violation strings."""
    problems = []
    if not isinstance(relpath, str) or not relpath.strip():
        return ["%s is empty or not a string" % label]
    if os.path.isabs(relpath) or (len(relpath) >= 2 and relpath[1] == ":"):
        return ["%s '%s' must be repo-relative (absolute path rejected)"
                % (label, relpath)]
    parts = re.split(r"[\\/]", relpath)
    if ".." in parts:
        return ["%s '%s' contains a '..' traversal segment (rejected)"
                % (label, relpath)]
    norm = os.path.normpath(relpath)
    if norm != relpath:
        problems.append("%s '%s' is not normalized (expected '%s')"
                        % (label, relpath, norm))
    if repo_root is None:
        return problems
    root_real = os.path.realpath(repo_root)
    prefix = root_real.rstrip(os.sep) + os.sep
    full = os.path.join(repo_root, norm)
    real = os.path.realpath(full)
    if not (real == root_real or real.startswith(prefix)):
        problems.append("%s '%s' resolves outside the repo root "
                        "(symlink/realpath escape)" % (label, relpath))
        return problems
    if must_exist:
        if not os.path.lexists(full):
            problems.append("%s '%s' does not exist (expected a committed "
                            "regular file)" % (label, relpath))
            return problems
        if os.path.islink(full):
            problems.append("%s '%s' is a symlink (must be a committed regular "
                            "file, not a symlink)" % (label, relpath))
            return problems
        if not os.path.isfile(full):
            problems.append("%s '%s' is not a regular file" % (label, relpath))
            return problems
        tracked = _is_git_tracked(repo_root, norm)
        if tracked is False:
            problems.append("%s '%s' is not committed (git does not track it)"
                            % (label, relpath))
        elif require_committed:
            # MED-9: `git ls-files` (the tracked check above) also accepts a
            # newly-STAGED path absent from every commit. Artifacts referenced by
            # the manifest MUST be durable in a commit, so verify HEAD directly.
            committed = _is_committed_at_head(repo_root, norm)
            if committed is False:
                problems.append(
                    "%s '%s' is not present in a commit at HEAD — a staged-only "
                    "or uncommitted artifact is not durable; referenced artifacts "
                    "must be committed (fail-closed)" % (label, relpath))
            elif committed is _GIT_UNAVAILABLE:
                # MED-8: a `.git` IS present but the HEAD probe errored / timed out
                # / git is unavailable. The prior code returned None here and the
                # caller only treated literal False as a violation, so a git error
                # PASSED containment. A committed-artifact requirement must fail
                # CLOSED on an unverifiable probe — never a silent skip.
                problems.append(
                    "%s '%s' HEAD-commit containment could not be verified — the "
                    "git probe errored, timed out, or git is unavailable while a "
                    "'.git' is present; a committed-artifact requirement fails "
                    "closed on an unverifiable probe (MED-8)" % (label, relpath))
            # committed is True -> present at HEAD (ok); committed is None -> no
            # `.git` at all -> the legitimate no-git degrade (skip).
    return problems


def _review_resolution(review, stance, repo_root, config_path):
    """Validate + RESOLVE the fast_path.review DECLARATION through the real
    resolver (CR5-5/CR4-8). Returns (problems, resolved_model). The declaration
    MUST be backend:claude + (tier:deep OR model:opus), and the concrete resolved
    model MUST be Claude Opus."""
    problems = []
    if not isinstance(review, dict) or not review:
        return (["fast_path.review declaration is missing or not a mapping"], None)
    backend = str(review.get("backend", "")).lower()
    tier = review.get("tier")
    model = review.get("model")
    if backend != "claude":
        problems.append(
            "fast_path.review backend '%s' invalid — the reviewer-Opus guarantee "
            "requires backend: claude (CR5-5)" % review.get("backend"))
    has_deep = str(tier or "").lower() == "deep"
    has_opus_pin = str(model or "").lower() == "opus"
    if not has_deep and not has_opus_pin:
        problems.append(
            "fast_path.review must declare tier: deep OR model: opus "
            "(CR4-8), got tier=%r model=%r" % (tier, model))

    rm = _sibling("compound-v-resolve-model.py")
    if rm is None:
        problems.append("cannot load compound-v-resolve-model.py to resolve the "
                        "fast_path.review declaration — fail-closed")
        return (problems, None)
    cfg_path = config_path
    if cfg_path is None and repo_root is not None:
        cand = os.path.join(repo_root, ".claude", "compound-v.json")
        cfg_path = cand if os.path.isfile(cand) else None
    try:
        config_models = rm.load_config_models(cfg_path) if cfg_path else {}
    except Exception as e:  # noqa: BLE001 - malformed config -> fail-closed
        problems.append("fast_path.review: project config models unreadable "
                        "(%s) — fail-closed" % e)
        return (problems, None)
    try:
        res = rm.resolve(
            backend="claude", tier="deep", config_models=config_models,
            explicit_model=(model if has_opus_pin else None),
            stance=(stance or "balanced"))
        resolved_model = res.get("model")
    except Exception as e:  # noqa: BLE001 - unresolvable -> fail-closed
        problems.append("fast_path.review does not resolve to a concrete model "
                        "(%s) — fail-closed" % e)
        return (problems, None)
    if not _is_claude_opus(resolved_model):
        problems.append(
            "fast_path.review resolves to '%s', not Claude Opus — reviewers must "
            "be Opus (CR5-5); a models.<stance>.claude.deep override that isn't "
            "opus fails" % resolved_model)
    return (problems, resolved_model)


def _load_bundled_schema(relpath, label):
    """Load a JSON schema that SHIPS in this repo. Returns ``(schema, None)`` or
    ``(None, err)``. Every failure mode — absent, unreadable, malformed, not an
    object — is an ANOMALY rather than an expected "no schema" case, so the caller
    must treat ``(None, err)`` as a verification PROBLEM and fail closed. This is
    the generic form of the rule MED-3 pinned for the fast-path receipt; the
    cross-model receipt reuses it verbatim rather than inventing a second policy."""
    here = _SCRIPTS_DIR
    path = os.path.join(os.path.dirname(here), relpath)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            schema = json.load(fh)
    except Exception as e:  # noqa: BLE001 - missing/unreadable/malformed all fail closed
        return None, ("%s schema '%s' could not be loaded (%s) — it ships in-repo, "
                      "so this is an anomaly; fail-closed, shape validation cannot "
                      "be skipped" % (label, relpath, e))
    if not isinstance(schema, dict):
        return None, ("%s schema '%s' is not a JSON object — fail-closed"
                      % (label, relpath))
    return schema, None


def _load_receipt_schema():
    """Load the bundled fast-path receipt JSON-schema. Returns ``(schema, None)`` on
    success, else ``(None, err)``. MED-3: the schema SHIPS in-repo at
    ``schemas/fastpath-review-receipt.schema.json``, so a missing / unreadable /
    malformed schema is an ANOMALY, not an expected "schema absent" case — the caller
    MUST treat ``(None, err)`` as a verification PROBLEM and fail closed, NEVER skip
    the shape validation (a receipt carrying only ids+backend+verdict must not slip
    through because the schema failed to load)."""
    here = _SCRIPTS_DIR
    path = os.path.join(os.path.dirname(here), _RECEIPT_SCHEMA)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            schema = json.load(fh)
    except Exception as e:  # noqa: BLE001 - missing/unreadable/malformed all fail closed
        return None, ("review-receipt schema '%s' could not be loaded (%s) — it ships "
                      "in-repo, so this is an anomaly; fail-closed, shape validation "
                      "cannot be skipped (MED-3)" % (_RECEIPT_SCHEMA, e))
    if not isinstance(schema, dict):
        return None, ("review-receipt schema '%s' is not a JSON object — fail-closed "
                      "(MED-3)" % _RECEIPT_SCHEMA)
    return schema, None


def _json_type_ok(v, t):
    types = t if isinstance(t, list) else [t]
    for tt in types:
        if tt == "string" and isinstance(v, str):
            return True
        if tt == "integer" and isinstance(v, int) and not isinstance(v, bool):
            return True
        if tt == "number" and isinstance(v, (int, float)) and not isinstance(v, bool):
            return True
        if tt == "array" and isinstance(v, list):
            return True
        if tt == "object" and isinstance(v, dict):
            return True
        if tt == "boolean" and isinstance(v, bool):
            return True
        if tt == "null" and v is None:
            return True
    return False


def _schema_lite_value(v, spec, label):
    problems = []
    t = spec.get("type")
    if t is not None and not _json_type_ok(v, t):
        return ["%s has wrong type (expected %s)" % (label, t)]
    if "const" in spec and v != spec["const"]:
        problems.append("%s must be %r (got %r)" % (label, spec["const"], v))
    if "enum" in spec and v not in spec["enum"]:
        problems.append("%s must be one of %s (got %r)" % (label, spec["enum"], v))
    if "pattern" in spec and isinstance(v, str) and re.search(spec["pattern"], v) is None:
        problems.append("%s does not match pattern %s" % (label, spec["pattern"]))
    return problems


def _schema_lite(obj, schema, label):
    """A tiny JSON-Schema subset checker (required / additionalProperties:false /
    type / const / enum / pattern on a flat object). Enough to structurally
    validate the receipt without a jsonschema dependency."""
    problems = []
    if schema.get("type") == "object":
        if not isinstance(obj, dict):
            return ["%s is not a JSON object" % label]
        props = schema.get("properties", {})
        for req in schema.get("required", []):
            if req not in obj:
                problems.append("%s missing required field '%s'" % (label, req))
        if schema.get("additionalProperties") is False:
            for k in obj:
                if k not in props:
                    problems.append("%s has unknown field '%s'" % (label, k))
        for k, spec in props.items():
            if k in obj:
                problems.extend(_schema_lite_value(obj[k], spec, "%s.%s" % (label, k)))
    return problems


def _read_run_baseline(repo_root, run_id, sole_job_id):
    """Read the IMMUTABLE pre-launch baseline SHA from the run's state.json (the
    scope gate + F2 reclassifier ran against it; never HEAD, CR5-3). The baseline
    is the trust anchor — the receipt's baseline_sha is checked against THIS, and
    the diff-digest is recomputed against THIS, never against a receipt-supplied
    value. Returns (baseline_str, None) or (None, err) — fail-closed on absence."""
    if repo_root is None or run_id in (None, ""):
        return None, "no repo root or run_id to locate the run state"
    state_full = os.path.join(repo_root, _EXEC_DIR, str(run_id), "state.json")
    try:
        with open(state_full, "r", encoding="utf-8") as fh:
            state = json.load(fh)
    except Exception as e:  # noqa: BLE001 - any read/parse failure -> fail-closed
        return None, "run state.json unreadable (%s)" % e
    jobs = state.get("jobs") if isinstance(state, dict) else None
    if not isinstance(jobs, dict) or not jobs:
        return None, "run state.json has no 'jobs' map"
    entry = None
    if sole_job_id is not None and sole_job_id in jobs:
        entry = jobs[sole_job_id]
    elif len(jobs) == 1:
        entry = next(iter(jobs.values()))
    if not isinstance(entry, dict):
        return None, "run state.json has no entry for the fast-path job"
    base = entry.get("baseline")
    if not isinstance(base, str) or not base.strip():
        return None, "the fast-path job has no recorded immutable baseline SHA"
    return base.strip(), None


def _recompute_diff_digest(diff_root, baseline, tax):
    """Recompute the FINAL diff digest — 'sha256:'+sha256(git diff --no-color
    <baseline>) — the anti-stale-replay comparison value (same command + convention
    as the producer). CRIT-1: ``diff_root`` MUST be the SAME checkout the producer
    hashed (the worker's linked WORKTREE), NOT necessarily the main repo — the
    caller passes the run's worktree and falls back to the repo root only when none
    was supplied. Returns (digest, None) or (None, err). Fail-closed on a git error
    (an unavailable/wrong-checkout diff_root exits non-zero here), a non-object-id
    baseline, or a truncated (over-cap) capture."""
    import subprocess

    if diff_root is None:
        return None, "no diff root"
    if tax is None:
        return None, "shared digest primitive unavailable"
    if not re.fullmatch(r"[0-9a-fA-F]{7,64}", str(baseline or "")):
        return None, "baseline '%s' is not a git object id" % baseline
    try:
        p = subprocess.run(
            ["git", "-C", diff_root, "diff", "--no-color", str(baseline)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=_GIT_DIFF_TIMEOUT_S)
    except Exception as e:  # noqa: BLE001 - git missing/broken/timeout -> fail-closed
        return None, "git diff failed (%s)" % e
    if p.returncode != 0:
        return None, ("git diff against baseline '%s' exited %d"
                      % (baseline, p.returncode))
    data = p.stdout or b""
    if len(data) >= _MAX_DIFF_BYTES:
        return None, "diff exceeds the bounded capture — ambiguous, fail-closed"
    return tax.taxonomy_digest_bytes(data), None


def _sealed_receipt_problems(receipt, pre_eval_id, run_id):
    """The SEALED-receipt verification problem list (empty ⇒ verified). This is the
    portion of the fast-path review receipt that is self-contained to the receipt
    object plus the two binding ids — no repo / diff / manifest context. Backs
    ``verify_sealed_receipt``; kept as a list so ``_validate_receipt`` can preserve
    the exact per-check messages its regression suite asserts on."""
    problems = []
    # MED-3: a schema-load failure is itself a verification PROBLEM (fail-closed) — the
    # schema ships in-repo, so an unloadable schema must REJECT, never silently skip the
    # shape checks (which would let a receipt with only ids+backend+verdict pass).
    schema, sch_err = _load_receipt_schema()
    if sch_err is not None:
        problems.append(sch_err)
    elif schema is not None:
        problems.extend(_schema_lite(receipt, schema, "review receipt"))
    if not isinstance(receipt, dict):
        return problems
    tax = _sibling("compound-v-taxonomy.py")

    # --- identity binding: run_id + pre_eval_id ---
    if str(receipt.get("run_id")) != str(run_id):
        problems.append("review receipt run_id '%s' != expected run_id '%s'"
                        % (receipt.get("run_id"), run_id))
    if str(receipt.get("pre_eval_id")) != str(pre_eval_id):
        problems.append("review receipt pre_eval_id '%s' != expected pre_eval_id "
                        "'%s'" % (receipt.get("pre_eval_id"), pre_eval_id))

    # --- reviewer must resolve to Claude Opus (CR5-5) ---
    if str(receipt.get("reviewer_backend", "")).lower() != "claude":
        problems.append("review receipt reviewer_backend '%s' invalid — must be "
                        "claude (CR5-5)" % receipt.get("reviewer_backend"))
    if not _is_claude_opus(receipt.get("reviewer_model")):
        problems.append("review receipt reviewer_model '%s' is not Claude Opus "
                        "(CR5-5)" % receipt.get("reviewer_model"))

    # --- verdict MUST be an explicit, normalized 'approved' (CR5-6) ---
    verdict = receipt.get("verdict")
    if not isinstance(verdict, str) or verdict.strip().lower() != "approved":
        problems.append("review receipt verdict %r is not 'approved' — a "
                        "non-approved or absent verdict blocks the merge "
                        "(fail-closed, CR5-6)" % verdict)

    # --- receipt self-digest: REQUIRED + verified via the SHARED primitive ---
    rdig = receipt.get("digest")
    if not isinstance(rdig, str) or not rdig:
        problems.append("review receipt is missing its self-digest — cannot "
                        "verify integrity (fail-closed, CR5-6)")
    elif tax is None:
        problems.append("review receipt self-digest cannot be verified — shared "
                        "taxonomy digest primitive unavailable (fail-closed)")
    else:
        try:
            if tax.record_digest(receipt, exclude_field="digest") != rdig:
                problems.append("review receipt self-digest mismatch — the "
                                "receipt was tampered (fail-closed, CR5-6)")
        except Exception as e:  # noqa: BLE001
            problems.append("review receipt self-digest cannot be recomputed "
                            "(%s) — fail-closed" % e)
    return problems


def verify_sealed_receipt(receipt, pre_eval_id, run_id):
    """Reusable sealed-receipt verification — the SINGLE authority for the receipt
    checks that need no repo/diff/manifest context. Verifies, in order:

      * schema shape (via the bundled fastpath-review-receipt schema, when present);
      * the REQUIRED self-integrity digest matches the SHARED canonical-JSON
        primitive ``compound-v-taxonomy.record_digest(receipt, exclude_field=
        "digest")`` — the same primitive the producer seals the receipt with;
      * ``verdict``, normalized, is exactly ``'approved'``;
      * ``run_id`` and ``pre_eval_id`` bind to the supplied ids;
      * ``reviewer_backend`` is ``'claude'`` AND ``reviewer_model`` is Claude Opus.

    Returns ``(ok: bool, reason: str)`` — ``reason`` is empty on success, else the
    ``'; '``-joined list of every failing check. Fail-closed: a non-dict receipt, an
    unavailable shared digest primitive, or a missing self-digest all return False.

    ``compound-v-triage-outcomes.py`` imports this by path so its precision gate
    applies the SAME verification as the post-review validator, instead of a weaker
    parallel ``verdict``/``run_id``/``pre_eval_id``-only check. The post-review path
    (``_validate_receipt``) also calls this, then adds the repo-context bindings
    (manifest digest, baseline, final diff, worktree) it alone can recompute."""
    problems = _sealed_receipt_problems(receipt, pre_eval_id, run_id)
    return (len(problems) == 0, "; ".join(problems))
