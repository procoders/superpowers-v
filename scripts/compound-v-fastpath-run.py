#!/usr/bin/env python3
"""
Compound V — fast-path runner (v2.9 Task H1). CR1-10 / CR2-5 / CR4-9.

WHAT THIS IS
------------
The concrete, non-skippable test/review FLOOR for an accepted fast-path run, plus the
review HANDOFF. It is the runner the parallel-dispatcher (``agents/parallel-dispatcher.md``,
owned by C2) drives across the ONE authoritative dispatch order (Lifecycle & commit-ordering
protocol, CR4-9):

    implementer → tests (THIS floor) → scope gate → F2 (pinned baseline, pre-merge)
      → review (needs_review Task; dispatcher writes the receipt)
      → post-review receipt validation → final scope recheck → merge

This script owns the two seams the dispatcher cannot express as prose:

  1. ``test-floor``   — run the proportionate test floor as a concrete ladder:
                          tier-1 configured project tests (if a test command is configured)
                        → tier-2 guarded language parse-check (``python3 -m py_compile`` [C1 —
                          MODULE form, never the non-binary ``py_compile``], ``node --check``,
                          ``tsc --noEmit`` iff a tsconfig, ``go build`` iff a go.mod, ``ruby -c``,
                          ``php -l``), each gated on binary-present ∧ project-manifest-present and
                          degrading (never crashing) when a toolchain is absent [C2]
                        → tier-3 one cheap diff-read.
                        A floor FAILURE blocks the merge (Iron-Invariant #6 / spec §4). Every
                        external checker runs THROUGH ``compound-v-run-with-timeout.py`` with
                        ``stdin`` </dev/null and a bounded output sink.

  2. review HANDOFF   — the combined Opus SPEC+QUALITY review is **NOT** dispatched from Python
                        (CR2-5, exactly like the T3 classify). Instead:
                          * ``review-spec``   emits a bounded ``needs_review`` job spec (the
                                              bounded diff + the combined SPEC+QUALITY prompt +
                                              the recorded VACUOUS INTEGRATION rationale + the
                                              anti-stale-replay binding: run_id / pre_eval_id /
                                              manifest_digest / baseline_sha / final_diff_digest /
                                              attempt_id). The PARENT harness runs the in-harness
                                              ``deep``/opus Task with this prompt and writes the
                                              invocation receipt (schemas/fastpath-review-receipt).
                          * ``accept-review`` validates the review RESULT the parent returns on
                                              re-entry, across the four failure modes — malformed /
                                              rejected / timed-out / wrong-tier — plus the
                                              anti-stale-replay binding check. Only a clean
                                              ``approved`` result from a ``deep``/``claude``/opus
                                              reviewer, bound to THIS diff, may advance to merge.

ORDER IS ENFORCED, NOT ASSUMED (CR4-9). ``review-spec`` FAILS CLOSED — it refuses to emit the
review request unless it is handed proof that the floor PASSED, the scope gate was CLEAN, and
F2 did NOT escalate. F2 therefore always runs BEFORE review; a floor failure or an F2 escalation
can never reach the reviewer.

CONSTRAINTS: Python 3.9-safe, stdlib only. No Python→Claude model call anywhere (the review is a
parent-run Task; this script only builds the request and validates the returned result). Every
external CLI routes through the timeout supervisor with a closed stdin and a bounded sink. No
fabricated metrics. Fail-closed on any ambiguity.

CLI:
    compound-v-fastpath-run.py test-floor  --worktree DIR [--baseline SHA]
        [--changed-file paths.txt] [--test-cmd "CMD"] [--out result.json]
    compound-v-fastpath-run.py review-spec --worktree DIR --baseline SHA --manifest FILE
        --run-id ID --pre-eval-id ID [--attempt-id N] --floor-result FILE
        --scope-clean --f2-result FILE [--out spec.json]
    compound-v-fastpath-run.py accept-review --spec spec.json --result result.json [--out v.json]
    compound-v-fastpath-run.py --selftest

Exit codes: 0 = phase OK / floor holds / review accepted; 1 = floor failed, review-spec refused
(blocked), or review rejected. Non-zero is advisory — the dispatcher owns the merge decision.
"""

import argparse
import datetime as _dt
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile


# --------------------------------------------------------------------------- #
# Tunables (fast-path = tiny changes; conservative, bounded by design).
# --------------------------------------------------------------------------- #
TEST_TIMEOUT_S = 300        # tier-1 configured project test command
PARSE_TIMEOUT_S = 60        # tier-2 per-language parse-check
GIT_TIMEOUT_S = 30          # tier-3 diff-read / diff digest
MAX_OUTPUT_BYTES = 262144   # bounded sink for any supervised child (256 KiB)
MAX_DIFF_BYTES = 1_000_000  # bounded `git diff` capture (spec + tier-3)
MAX_PROMPT_DIFF_BYTES = 60000   # diff slice embedded in the review prompt

# The recorded rationale that a single-job fast-path has a VACUOUS INTEGRATION pass
# (no cross-job seams). An auto-pass WITH a stated reason — never a silent skip
# (spec §4 review-pass matrix).
VACUOUS_INTEGRATION_RATIONALE = (
    "INTEGRATION pass is vacuous for a single-job fast-path run: there is exactly one "
    "implementer job and therefore no cross-job seams to integrate. Auto-pass WITH this "
    "recorded rationale (never a silent skip); the combined SPEC+QUALITY pass is the real gate."
)

# Fields the review request binds so a stale review result from an earlier attempt cannot be
# replayed against a changed diff (mirrors the receipt binding, CR5-6).
_BINDING_FIELDS = (
    "run_id", "pre_eval_id", "manifest_digest", "baseline_sha",
    "final_diff_digest", "attempt_id",
)


# --------------------------------------------------------------------------- #
# Language parse-check registry (tier-2). Each entry:
#   ext -> {bin, cmd, manifest, whole_program}
# ``bin``           : the executable that must be on PATH (binary-present gate).
# ``cmd``           : argv template; the file (per-file) is appended, or run as-is
#                     (whole_program) in the worktree.
# ``manifest``      : a repo-root file that must exist (project-manifest-present gate),
#                     or None when the checker is a self-contained single-file compiler.
# ``whole_program`` : True → run once in the worktree (tsc/go); False → run per changed file.
# python3 is invoked as ``python3 -m py_compile`` (C1: MODULE form — ``py_compile`` is not a
# binary). ``tsc --noEmit`` is a whole-program type-check and is only meaningful with a tsconfig
# (audit C2: absent tsconfig ⇒ skip to the next tier).
# --------------------------------------------------------------------------- #
def _default_checkers():
    py = sys.executable or "python3"
    return {
        ".py":  {"bin": py,    "cmd": [py, "-m", "py_compile"], "manifest": None, "whole_program": False},
        ".js":  {"bin": "node", "cmd": ["node", "--check"], "manifest": "package.json", "whole_program": False},
        ".jsx": {"bin": "node", "cmd": ["node", "--check"], "manifest": "package.json", "whole_program": False},
        ".mjs": {"bin": "node", "cmd": ["node", "--check"], "manifest": "package.json", "whole_program": False},
        ".cjs": {"bin": "node", "cmd": ["node", "--check"], "manifest": "package.json", "whole_program": False},
        ".ts":  {"bin": "tsc",  "cmd": ["tsc", "--noEmit"], "manifest": "tsconfig.json", "whole_program": True},
        ".tsx": {"bin": "tsc",  "cmd": ["tsc", "--noEmit"], "manifest": "tsconfig.json", "whole_program": True},
        ".go":  {"bin": "go",   "cmd": ["go", "build", "./..."], "manifest": "go.mod", "whole_program": True},
        ".rb":  {"bin": "ruby", "cmd": ["ruby", "-c"], "manifest": None, "whole_program": False},
        ".php": {"bin": "php",  "cmd": ["php", "-l"], "manifest": None, "whole_program": False},
    }


# --------------------------------------------------------------------------- #
# Supervised execution — every external CLI runs through the process-group
# timeout supervisor with stdin </dev/null and a bounded output sink.
# --------------------------------------------------------------------------- #
def _script_dir():
    return os.path.dirname(os.path.abspath(__file__))


def _supervisor_path():
    return os.path.join(_script_dir(), "compound-v-run-with-timeout.py")


def _run_supervised(cmd, cwd, timeout_s, cap_bytes=MAX_OUTPUT_BYTES):
    """Run ``cmd`` (a list) under the timeout supervisor, capturing bounded stdout.
    Returns ``(rc, stdout_bytes)``: ``rc`` is the command's own exit code (or 124 on
    timeout, 127 if missing). stdin is DEVNULL (enforced by the supervisor AND here);
    stderr is discarded. Never raises — a supervisor launch failure degrades to a
    fail-closed non-zero rc."""
    tmp = tempfile.mkdtemp(prefix="cv-h1-")
    try:
        outf = os.path.join(tmp, "out")
        full = [
            sys.executable, _supervisor_path(),
            "--timeout", str(int(max(1, timeout_s))), "--grace", "1",
            "--stdout", outf, "--max-output-bytes", str(int(cap_bytes)),
            "--",
        ] + list(cmd)
        try:
            proc = subprocess.run(
                full, cwd=(cwd or None), stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            rc = proc.returncode
        except Exception:  # noqa: BLE001 — cannot even launch the supervisor
            return 126, b""
        data = b""
        try:
            with open(outf, "rb") as fh:
                data = fh.read()
        except OSError:
            data = b""
        return rc, data
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _git(worktree, args, timeout_s=GIT_TIMEOUT_S, cap_bytes=MAX_DIFF_BYTES):
    return _run_supervised(["git", "-C", worktree] + list(args), None, timeout_s, cap_bytes)


# --------------------------------------------------------------------------- #
# Digests (anti-stale-replay binding; same prefixed-sha256 shape as the receipt).
# --------------------------------------------------------------------------- #
def _sha256_prefixed(data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _manifest_digest(path):
    """'sha256:'+sha256 of the manifest.yaml bytes, or None if unreadable (fail-closed)."""
    try:
        with open(path, "rb") as fh:
            return _sha256_prefixed(fh.read())
    except OSError:
        return None


def _diff_bytes(worktree, baseline):
    """Bounded ``git diff <baseline>`` capture. Returns ``(data, ok)`` — ``ok`` is False on
    a git error OR when the capture hit the bounded sink (ambiguous ⇒ caller fails closed)."""
    rc, out = _git(worktree, ["diff", "--no-color", baseline], GIT_TIMEOUT_S, MAX_DIFF_BYTES)
    if rc != 0:
        return b"", False
    if len(out) >= MAX_DIFF_BYTES:
        return out, False
    return out, True


# --------------------------------------------------------------------------- #
# Optional sibling: derive changed paths from the scope gate (soft, read-only).
# Kept injectable so the floor is testable without git plumbing.
# --------------------------------------------------------------------------- #
def _changed_from_scope(worktree, baseline):
    import importlib.util
    path = os.path.join(_script_dir(), "compound-v-scope-check.py")
    try:
        spec = importlib.util.spec_from_file_location("compound_v_scope_check", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return list(mod.changed_files(worktree, baseline))
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------------------- #
# Tier 2 — guarded per-language parse-checks.
# --------------------------------------------------------------------------- #
def _manifest_present(worktree, manifest):
    if manifest is None:
        return True
    return os.path.isfile(os.path.join(worktree, manifest))


def _run_parse_checks(worktree, changed_paths, checkers):
    """Run the applicable, available parse-checkers over ``changed_paths``.

    Returns ``(checks, ran_any, failed_any)`` where ``checks`` is a list of per-check
    records. A checker is applied only when its binary is on PATH AND its project
    manifest is present (degrade-never-crash for absent toolchains, C2). Whole-program
    checkers (tsc/go) run ONCE per applicable extension; per-file checkers run per file.
    A non-zero exit (or timeout) is a parse FAILURE (floor-blocking)."""
    checks = []
    ran_any = False
    failed_any = False
    whole_done = set()

    for path in sorted(set(changed_paths)):
        ext = os.path.splitext(path)[1].lower()
        spec = checkers.get(ext)
        if spec is None:
            checks.append({"file": path, "ext": ext, "status": "skip",
                           "reason": "no parse-checker for extension"})
            continue
        if shutil.which(spec["bin"]) is None and not os.path.isabs(spec["bin"]):
            # sys.executable is absolute and always present; other bins gate on PATH.
            checks.append({"file": path, "ext": ext, "checker": spec["bin"],
                           "status": "skip", "reason": "binary '%s' not on PATH" % spec["bin"]})
            continue
        if not _manifest_present(worktree, spec["manifest"]):
            checks.append({"file": path, "ext": ext, "checker": spec["bin"], "status": "skip",
                           "reason": "project manifest '%s' absent" % spec["manifest"]})
            continue

        if spec["whole_program"]:
            if ext in whole_done:
                continue
            whole_done.add(ext)
            rc, _ = _run_supervised(list(spec["cmd"]), worktree, PARSE_TIMEOUT_S)
            rec = {"file": "<whole-program>", "ext": ext,
                   "checker": " ".join(spec["cmd"]), "rc": rc, "whole_program": True}
        else:
            abspath = os.path.join(worktree, path)
            if not os.path.isfile(abspath):
                checks.append({"file": path, "ext": ext, "checker": spec["bin"],
                               "status": "skip", "reason": "file absent in worktree "
                               "(deleted/renamed — structural axis is F2's, not the floor's)"})
                continue
            rc, _ = _run_supervised(list(spec["cmd"]) + [abspath], worktree, PARSE_TIMEOUT_S)
            rec = {"file": path, "ext": ext, "checker": " ".join(spec["cmd"]), "rc": rc}

        ran_any = True
        if rc == 0:
            rec["status"] = "pass"
        else:
            rec["status"] = "fail"
            rec["reason"] = ("timeout" if rc == 124 else
                             "missing checker binary" if rc == 127 else
                             "non-zero exit")
            failed_any = True
        checks.append(rec)

    return checks, ran_any, failed_any


# --------------------------------------------------------------------------- #
# The test floor (concrete ladder).
# --------------------------------------------------------------------------- #
def run_test_floor(worktree, baseline="HEAD", changed_paths=None, test_cmd=None,
                   checkers=None, test_timeout_s=TEST_TIMEOUT_S):
    """Run the proportionate fast-path test floor as a concrete ladder.

    tier-1 configured project tests (``test_cmd``) → tier-2 guarded language parse-checks
    → tier-3 one cheap diff-read. Returns a result dict::

        {"phase":"test_floor", "tier_used":1|2|3|0, "passed":bool, "merge_blocked":bool,
         "checks":[...], "reasons":[...]}

    ``merge_blocked`` is True on any floor FAILURE (Iron-Invariant #6). A tier is only
    "used" when it actually produced a verdict; an empty/unavailable tier falls through.
    """
    if checkers is None:
        checkers = _default_checkers()
    changed_paths = list(changed_paths) if changed_paths is not None else None
    result = {"phase": "test_floor", "tier_used": 0, "passed": False,
              "merge_blocked": True, "checks": [], "reasons": []}

    # tier-1: configured project tests.
    if test_cmd:
        cmd = shlex.split(test_cmd) if isinstance(test_cmd, str) else list(test_cmd)
        if not cmd:
            result["reasons"].append("tier-1: configured test command is empty (fail-closed)")
            return result
        rc, _ = _run_supervised(cmd, worktree, test_timeout_s)
        result["tier_used"] = 1
        result["checks"].append({"tier": 1, "checker": " ".join(cmd), "rc": rc,
                                 "status": "pass" if rc == 0 else "fail"})
        if rc == 0:
            result["passed"] = True
            result["merge_blocked"] = False
        else:
            result["reasons"].append(
                "tier-1: configured tests failed (rc=%s%s)"
                % (rc, "; timeout" if rc == 124 else ""))
        return result

    # Derive changed paths if not supplied (soft; fail-closed if underivable).
    if changed_paths is None:
        changed_paths = _changed_from_scope(worktree, baseline)
        if changed_paths is None:
            result["reasons"].append(
                "cannot derive changed paths (scope-check unavailable) — fail-closed")
            return result

    # tier-2: guarded per-language parse-checks.
    checks, ran_any, failed_any = _run_parse_checks(worktree, changed_paths, checkers)
    result["checks"].extend(checks)
    if ran_any:
        result["tier_used"] = 2
        if failed_any:
            result["reasons"].append("tier-2: a language parse-check failed")
            return result
        result["passed"] = True
        result["merge_blocked"] = False
        return result

    # tier-3: one cheap diff-read (the weakest, non-skippable floor). A materialized
    # change may be a tracked modification (visible in `git diff <baseline>`), a
    # worker-committed change (also baseline-relative in the diff), OR an UNTRACKED new
    # file (invisible to `git diff` — surfaced via `git status --porcelain`). All three
    # count; a truly empty change fails closed (an accepted fast-path with no diff is wrong).
    result["tier_used"] = 3
    rc_diff, diff_out = _git(worktree, ["diff", "--no-color", baseline],
                             GIT_TIMEOUT_S, MAX_DIFF_BYTES)
    rc_st, st_out = _git(worktree, ["status", "--porcelain"], GIT_TIMEOUT_S, MAX_DIFF_BYTES)
    if rc_diff != 0 and rc_st != 0:
        result["reasons"].append(
            "tier-3: git diff/status both unreadable against baseline %s — fail-closed" % baseline)
        result["checks"].append({"tier": 3, "checker": "git diff/status", "status": "fail"})
        return result
    tracked_change = rc_diff == 0 and (bool(diff_out.strip()) or len(diff_out) >= MAX_DIFF_BYTES)
    untracked_change = rc_st == 0 and bool(st_out.strip())
    if not tracked_change and not untracked_change:
        result["reasons"].append(
            "tier-3: empty change on a fast-path run (nothing to review) — fail-closed")
        result["checks"].append({"tier": 3, "checker": "git diff/status", "status": "empty"})
        return result
    result["checks"].append({"tier": 3, "checker": "git diff/status", "status": "read",
                             "tracked_bytes": len(diff_out),
                             "untracked": untracked_change,
                             "note": "weakest floor tier — the combined Opus review is the "
                                     "real gate"})
    result["passed"] = True
    result["merge_blocked"] = False
    return result


# --------------------------------------------------------------------------- #
# Review HANDOFF — build the needs_review request (CR2-5). NO model call here.
# --------------------------------------------------------------------------- #
def _build_review_prompt(changed_paths, diff_text):
    if len(diff_text.encode("utf-8")) > MAX_PROMPT_DIFF_BYTES:
        clipped = diff_text.encode("utf-8")[:MAX_PROMPT_DIFF_BYTES].decode("utf-8", "replace")
        diff_text = clipped + "\n[... diff truncated to the bounded review budget ...]"
    files = "\n".join("  - %s" % p for p in sorted(set(changed_paths))) or "  (none listed)"
    return (
        "Combined SPEC+QUALITY fast-path review (single pass, deep/opus reviewer).\n\n"
        "This is an accepted Compound V fast-path run: exactly one implementer job over a tiny, "
        "localized diff. Review BOTH axes in one pass:\n"
        "  - SPEC: the change does what the request asked, nothing more, nothing less.\n"
        "  - QUALITY: correctness, no regressions, no fabricated metrics, house style.\n\n"
        "INTEGRATION is vacuous here (single job, no cross-job seams) — do NOT hunt for "
        "integration issues; that pass auto-passes with a recorded rationale.\n\n"
        "Changed files:\n%s\n\n"
        "Return a normalized verdict: 'approved' (merge may proceed), 'issues' (block), or "
        "'error' (block). Echo the binding fields unchanged.\n\n"
        "--- BEGIN DIFF ---\n%s\n--- END DIFF ---\n" % (files, diff_text)
    )


def build_review_spec(run_id, pre_eval_id, worktree, baseline, manifest_path,
                      changed_paths, floor_result, scope_clean, f2_result,
                      attempt_id=1, review_decl=None, ts=None):
    """Build the bounded ``needs_review`` job spec — OR a ``blocked`` spec when a prior gate
    did not pass (fail-closed enforcement of the CR4-9 order: tests → scope gate → F2 →
    review). The parent harness runs the deep/opus Task with ``spec['prompt']`` and writes
    the receipt; the review is NEVER dispatched from here.

    Returns a dict with ``kind`` == ``needs_review`` (emit) or ``blocked`` (refused)."""
    reasons = []

    # Gate 1 — the test floor must have PASSED (a floor failure blocks merge).
    if not isinstance(floor_result, dict) or not floor_result.get("passed") \
            or floor_result.get("merge_blocked"):
        reasons.append("test floor did not pass (floor failure blocks merge)")
    # Gate 2 — the scope gate must have been CLEAN.
    if not scope_clean:
        reasons.append("scope gate not proven clean (a worker wrote outside write_allowed, "
                       "or no scope verdict was supplied) — fail-closed")
    # Gate 3 — F2 post-hoc reclassification must NOT have escalated.
    if not isinstance(f2_result, dict):
        reasons.append("no F2 reclassification result supplied — fail-closed")
    elif f2_result.get("escalate"):
        f2_reasons = f2_result.get("reasons") or []
        reasons.append("F2 reclassifier escalated: %s"
                       % ("; ".join(f2_reasons) if f2_reasons else "reasons unspecified"))

    if reasons:
        return {"kind": "blocked", "merge_blocked": True, "reasons": reasons,
                "integration_rationale": VACUOUS_INTEGRATION_RATIONALE}

    # All gates passed → assemble the binding + prompt.
    mdigest = _manifest_digest(manifest_path)
    if mdigest is None:
        return {"kind": "blocked", "merge_blocked": True,
                "reasons": ["manifest '%s' unreadable — cannot bind the review request "
                            "(fail-closed)" % manifest_path],
                "integration_rationale": VACUOUS_INTEGRATION_RATIONALE}

    diff_data, ok = _diff_bytes(worktree, baseline)
    if not ok:
        return {"kind": "blocked", "merge_blocked": True,
                "reasons": ["cannot capture a bounded final diff against baseline %s — "
                            "fail-closed" % baseline],
                "integration_rationale": VACUOUS_INTEGRATION_RATIONALE}
    diff_text = diff_data.decode("utf-8", "replace")

    decl = review_decl or {"backend": "claude", "tier": "deep", "model": None}
    spec = {
        "kind": "needs_review",
        "review": {"backend": decl.get("backend", "claude"),
                   "tier": decl.get("tier", "deep"),
                   "model": decl.get("model")},
        "run_id": str(run_id),
        "pre_eval_id": str(pre_eval_id),
        "manifest_digest": mdigest,
        "baseline_sha": str(baseline),
        "final_diff_digest": _sha256_prefixed(diff_data),
        "attempt_id": attempt_id,
        "ts": ts,
        # The diff-root the producer hashed the final_diff_digest against — carried so the
        # receipt (and the validator recomputing the diff) bind to the SAME worktree, never a
        # divergent root. Producer-trusted metadata, NOT a reviewer-echoed binding field.
        "worktree": str(worktree),
        "changed_files": sorted(set(changed_paths)),
        "integration_rationale": VACUOUS_INTEGRATION_RATIONALE,
        "prompt": _build_review_prompt(changed_paths, diff_text),
        "acceptance": {
            "verdict_enum": ["approved", "issues", "error"],
            "required_reviewer": {"backend": "claude", "tier": "deep", "model_contains": "opus"},
            "note": "The dispatcher runs this as an in-harness deep/opus Task and writes the "
                    "invocation receipt; re-enter this runner with 'accept-review' to validate "
                    "the returned result.",
        },
    }
    return spec


# --------------------------------------------------------------------------- #
# Review RESULT validation (re-entry). Four failure modes + anti-stale-replay.
# --------------------------------------------------------------------------- #
_RESULT_REQUIRED = ("kind", "status", "verdict", "reviewer_backend", "reviewer_tier",
                    "reviewer_model") + _BINDING_FIELDS


def accept_review(spec, result):
    """Validate the review RESULT the parent returned on re-entry against the ``needs_review``
    ``spec``. Handles the four failure modes (malformed / rejected / timed-out / wrong-tier)
    plus the anti-stale-replay binding check. Returns::

        {"accepted":bool, "merge_ok":bool, "failure_modes":[...], "reasons":[...],
         "verdict":<str|None>, "integration_rationale":<str>, "receipt_fields":{...}|None}

    ``merge_ok`` is True ONLY for a clean, bound, 'approved' result from a deep/claude/opus
    reviewer. Everything else fails closed."""
    out = {"accepted": False, "merge_ok": False, "failure_modes": [], "reasons": [],
           "verdict": None, "integration_rationale": VACUOUS_INTEGRATION_RATIONALE,
           "receipt_fields": None}

    def fail(mode, reason):
        if mode not in out["failure_modes"]:
            out["failure_modes"].append(mode)
        out["reasons"].append(reason)

    # --- malformed: not a dict / missing required fields ---
    if not isinstance(result, dict):
        fail("malformed", "review result is not a JSON object")
        return out
    for k in _RESULT_REQUIRED:
        if k not in result:
            fail("malformed", "review result missing required field '%s'" % k)
    if result.get("kind") not in (None, "review_result"):
        fail("malformed", "review result has unexpected kind %r (expected 'review_result')"
             % result.get("kind"))
    if out["failure_modes"]:
        return out  # cannot trust anything else about a malformed result

    out["verdict"] = result.get("verdict")

    # --- timed-out: the review Task itself did not complete ---
    if str(result.get("status")).lower() == "timeout":
        fail("timed_out", "review Task timed out (status=timeout) — fail-closed")

    # --- wrong-tier: reviewer must be deep / claude / opus (reviewer-Opus invariant) ---
    if str(result.get("reviewer_backend", "")).lower() != "claude":
        fail("wrong_tier", "reviewer_backend %r is not 'claude' (reviewer-Opus invariant, CR5-5)"
             % result.get("reviewer_backend"))
    if str(result.get("reviewer_tier", "")).lower() != "deep":
        fail("wrong_tier", "reviewer_tier %r is not 'deep'" % result.get("reviewer_tier"))
    if "opus" not in str(result.get("reviewer_model", "")).lower():
        fail("wrong_tier", "reviewer_model %r is not Claude Opus" % result.get("reviewer_model"))

    # --- anti-stale-replay: the result MUST be bound to THIS review request ---
    if isinstance(spec, dict):
        for k in _BINDING_FIELDS:
            if str(result.get(k)) != str(spec.get(k)):
                fail("malformed", "binding mismatch on '%s' (%r != request %r) — possible stale "
                     "or misrouted review result" % (k, result.get(k), spec.get(k)))

    # --- rejected: any verdict other than 'approved' blocks the merge ---
    verdict = str(result.get("verdict", "")).lower()
    if verdict != "approved":
        if verdict in ("issues", "error"):
            fail("rejected", "review verdict is %r — merge blocked" % result.get("verdict"))
        else:
            fail("malformed", "review verdict %r not in {approved, issues, error}"
                 % result.get("verdict"))

    if out["failure_modes"]:
        return out

    # Clean, bound, approved, deep/claude/opus → may advance to merge. Hand the dispatcher the
    # exact fields it will stamp into the invocation receipt.
    out["accepted"] = True
    out["merge_ok"] = True
    out["receipt_fields"] = {
        "run_id": result.get("run_id"),
        "pre_eval_id": result.get("pre_eval_id"),
        "manifest_digest": result.get("manifest_digest"),
        "baseline_sha": result.get("baseline_sha"),
        "final_diff_digest": result.get("final_diff_digest"),
        "reviewer_backend": "claude",
        "reviewer_tier": "deep",
        "reviewer_model": result.get("reviewer_model"),
        "attempt_id": result.get("attempt_id"),
        "verdict": "approved",
        "integration_rationale": VACUOUS_INTEGRATION_RATIONALE,
    }
    return out


# --------------------------------------------------------------------------- #
# Receipt SEALING (re-entry, post-acceptance). The runner emits the canonical
# fast-path review receipt ONLY after acceptance succeeds — a fully-sealed,
# self-digested record the validator (post-review) + triage read. The self-digest
# uses the SHARED compound-v-taxonomy.record_digest primitive (imported by path) so
# producer and consumer agree byte-for-byte; a rejected/timed-out/wrong-tier result
# never produces a receipt (fail-closed).
# --------------------------------------------------------------------------- #
# Standard on-disk location, relative to a run directory (matches the validator's
# _RECEIPT_SUBPATH: <run>/review/receipt.json).
RECEIPT_SUBPATH = os.path.join("review", "receipt.json")

# The receipt's required, fully-sealed field set (mirrors the schema `required`
# minus the derived `digest`, plus the optional diff-root/tier signals we always emit).
_RECEIPT_REQUIRED = (
    "run_id", "pre_eval_id", "manifest_digest", "baseline_sha", "final_diff_digest",
    "reviewer_backend", "reviewer_model", "attempt_id", "ts", "verdict",
    "integration_rationale",
)


def _now_iso_utc():
    """ISO-8601 UTC timestamp (Z-suffixed, second precision) for the seal moment."""
    now = _dt.datetime.now(_dt.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_taxonomy():
    """Import compound-v-taxonomy.py BY PATH — the SAME record_digest primitive the
    validator uses to verify the receipt. Returns the module, or None (fail-closed:
    an unsealed receipt must never be written)."""
    import importlib.util
    path = os.path.join(_script_dir(), "compound-v-taxonomy.py")
    try:
        spec = importlib.util.spec_from_file_location("compound_v_taxonomy", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if not hasattr(mod, "record_digest"):
            return None
        return mod
    except Exception:  # noqa: BLE001 — any import failure ⇒ cannot seal ⇒ fail-closed
        return None


def build_sealed_receipt(spec, accept_out, ts=None, tax=None):
    """Build the FULLY-SEALED canonical review receipt from an ACCEPTED ``accept_review``
    output + the producer-trusted ``needs_review`` spec. Returns ``(receipt, None)`` or
    ``(None, err)``.

    Refuses (returns an error, NEVER a receipt) unless the review was accepted AND merge_ok
    — so a rejected / timed-out / wrong-tier result yields no receipt (fail-closed). The
    self-``digest`` is computed LAST over the receipt-without-digest via the shared
    ``record_digest`` primitive, so producer and consumer agree byte-for-byte."""
    if not isinstance(accept_out, dict) or not accept_out.get("accepted") \
            or not accept_out.get("merge_ok"):
        return None, ("refusing to seal a receipt for a non-accepted review result "
                      "(only a clean, bound, approved deep/claude/opus result is sealed)")
    rf = accept_out.get("receipt_fields")
    if not isinstance(rf, dict):
        return None, "accepted review output carries no receipt_fields to seal"
    if tax is None:
        tax = _load_taxonomy()
    if tax is None:
        return None, ("shared taxonomy record_digest primitive unavailable — cannot seal "
                      "the receipt (fail-closed)")

    receipt = {
        "run_id": rf.get("run_id"),
        "pre_eval_id": rf.get("pre_eval_id"),
        "manifest_digest": rf.get("manifest_digest"),
        "baseline_sha": rf.get("baseline_sha"),
        "final_diff_digest": rf.get("final_diff_digest"),
        "reviewer_backend": "claude",
        "reviewer_tier": rf.get("reviewer_tier", "deep"),
        "reviewer_model": rf.get("reviewer_model"),
        "attempt_id": rf.get("attempt_id"),
        "ts": ts or _now_iso_utc(),
        "verdict": "approved",
        "integration_rationale": rf.get("integration_rationale")
        or VACUOUS_INTEGRATION_RATIONALE,
    }
    # Diff-root signal for the validator's diff recompute — the worktree the producer hashed
    # the final_diff_digest against (from the trusted spec, never a reviewer-echoed field).
    if isinstance(spec, dict) and spec.get("worktree"):
        receipt["worktree"] = str(spec.get("worktree"))
    # No mandatory field may be missing/blank — an unsealed-looking receipt fails closed here
    # rather than being written and rejected downstream.
    for k in _RECEIPT_REQUIRED:
        if receipt.get(k) in (None, ""):
            return None, "cannot seal receipt: required field '%s' is missing/blank" % k

    try:
        receipt["digest"] = tax.record_digest(receipt, exclude_field="digest")
    except Exception as e:  # noqa: BLE001
        return None, "cannot compute the receipt self-digest (%s) — fail-closed" % e
    return receipt, None


def _atomic_write_json(path, obj):
    """Write ``obj`` as pretty JSON to ``path`` ATOMICALLY (tmp in the same dir + os.replace),
    creating parent dirs. The on-disk pretty-print is irrelevant to the self-digest — the
    validator re-parses and re-canonicalizes before verifying record_digest."""
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".receipt-", suffix=".json", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _receipt_dest(run_dir=None, receipt_out=None):
    """Resolve the receipt destination path: an explicit ``receipt_out`` wins, else
    ``<run_dir>/review/receipt.json``, else None (pure-validation mode: no receipt written)."""
    if receipt_out:
        return receipt_out
    if run_dir:
        return os.path.join(run_dir, RECEIPT_SUBPATH)
    return None


# --------------------------------------------------------------------------- #
# CLI.
# --------------------------------------------------------------------------- #
def _read_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _emit(obj, out_path):
    text = json.dumps(obj, indent=2)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    print(text)


def _cmd_test_floor(args):
    changed = None
    if args.changed_file:
        with open(args.changed_file, "r", encoding="utf-8") as fh:
            changed = [ln.strip() for ln in fh if ln.strip()]
    res = run_test_floor(args.worktree, args.baseline, changed, args.test_cmd)
    _emit(res, args.out)
    return 0 if res.get("passed") and not res.get("merge_blocked") else 1


def _cmd_review_spec(args):
    floor = _read_json(args.floor_result)
    f2 = _read_json(args.f2_result)
    changed = []
    if args.changed_file:
        with open(args.changed_file, "r", encoding="utf-8") as fh:
            changed = [ln.strip() for ln in fh if ln.strip()]
    elif isinstance(floor, dict):
        changed = [c.get("file") for c in floor.get("checks", [])
                   if c.get("file") and not str(c.get("file", "")).startswith("<")]
    spec = build_review_spec(
        args.run_id, args.pre_eval_id, args.worktree, args.baseline, args.manifest,
        changed, floor, args.scope_clean, f2, attempt_id=args.attempt_id, ts=args.ts)
    _emit(spec, args.out)
    return 0 if spec.get("kind") == "needs_review" else 1


def _cmd_accept_review(args):
    spec = _read_json(args.spec)
    result = _read_json(args.result)
    out = accept_review(spec, result)
    dest = _receipt_dest(getattr(args, "run_dir", None), getattr(args, "receipt_out", None))
    # Seal + write the receipt ONLY after acceptance succeeds. A rejected / timed-out /
    # wrong-tier / malformed result writes NO receipt (fail-closed).
    if out.get("accepted") and out.get("merge_ok") and dest:
        receipt, err = build_sealed_receipt(spec, out, ts=getattr(args, "ts", None))
        if receipt is None:
            # Acceptance held but the receipt could not be sealed (e.g. taxonomy primitive
            # missing) → refuse to emit an unsealed receipt AND fail the phase closed.
            out["accepted"] = False
            out["merge_ok"] = False
            out.setdefault("reasons", []).append("receipt seal failed: %s" % err)
            out["receipt_path"] = None
            _emit(out, args.out)
            return 1
        _atomic_write_json(dest, receipt)
        out["receipt_path"] = dest
        out["receipt"] = receipt
    _emit(out, args.out)
    return 0 if out.get("accepted") and out.get("merge_ok") else 1


def main(argv):
    if "--selftest" in argv[1:]:
        return _selftest()
    ap = argparse.ArgumentParser(prog="compound-v-fastpath-run.py")
    sub = ap.add_subparsers(dest="phase")

    p1 = sub.add_parser("test-floor")
    p1.add_argument("--worktree", required=True)
    p1.add_argument("--baseline", default="HEAD")
    p1.add_argument("--changed-file")
    p1.add_argument("--test-cmd")
    p1.add_argument("--out")
    p1.set_defaults(func=_cmd_test_floor)

    p2 = sub.add_parser("review-spec")
    p2.add_argument("--worktree", required=True)
    p2.add_argument("--baseline", required=True)
    p2.add_argument("--manifest", required=True)
    p2.add_argument("--run-id", required=True)
    p2.add_argument("--pre-eval-id", required=True)
    p2.add_argument("--attempt-id", type=int, default=1)
    p2.add_argument("--floor-result", required=True)
    p2.add_argument("--scope-clean", action="store_true")
    p2.add_argument("--f2-result", required=True)
    p2.add_argument("--changed-file")
    p2.add_argument("--ts")
    p2.add_argument("--out")
    p2.set_defaults(func=_cmd_review_spec)

    p3 = sub.add_parser("accept-review")
    p3.add_argument("--spec", required=True)
    p3.add_argument("--result", required=True)
    p3.add_argument("--run-dir", dest="run_dir",
                    help="run directory; the sealed receipt is written to "
                         "<run-dir>/review/receipt.json on acceptance")
    p3.add_argument("--receipt-out", dest="receipt_out",
                    help="explicit receipt path (overrides --run-dir)")
    p3.add_argument("--ts", help="override the receipt seal timestamp (ISO-8601); "
                                 "defaults to now (UTC)")
    p3.add_argument("--out")
    p3.set_defaults(func=_cmd_accept_review)

    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv[1:])
    if not getattr(args, "func", None):
        ap.error("a phase is required: test-floor | review-spec | accept-review (or --selftest)")
    return args.func(args)


# --------------------------------------------------------------------------- #
# Self-test — throwaway git repos in $TMPDIR (OUTSIDE the worktree). TDD floor.
# --------------------------------------------------------------------------- #
def _sprint(s):
    """Print ASCII-safely: under a C/POSIX locale stdout may be an ASCII codec, so
    encode-replace any non-ASCII (arrows, dashes in test names) instead of crashing.
    Keeps real glyphs on a UTF-8 terminal. Guarantees the selftest is GREEN under
    ``LANG=C PYTHONUTF8=0``."""
    enc = sys.stdout.encoding or "ascii"
    sys.stdout.write(s.encode(enc, "replace").decode(enc, "replace") + "\n")


def _selftest():
    failures = []

    def expect(name, cond):
        _sprint(("  ok   - " if cond else "  FAIL - ") + name)
        if not cond:
            failures.append(name)

    tmp = tempfile.mkdtemp(prefix="cv-h1-selftest-")

    def new_repo(name):
        repo = os.path.join(tmp, name)
        os.makedirs(repo)
        for cmd in (["git", "init", "-q"],
                    ["git", "config", "user.email", "t@t.t"],
                    ["git", "config", "user.name", "t"]):
            subprocess.run(cmd, cwd=repo, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return repo

    def git(repo, args):
        subprocess.run(["git", "-C", repo] + args, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def head(repo):
        return subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                              stdout=subprocess.PIPE, universal_newlines=True,
                              check=True).stdout.strip()

    def write(repo, rel, content):
        p = os.path.join(repo, rel)
        d = os.path.dirname(p)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(content)

    try:
        # ---- TEST FLOOR ----------------------------------------------------
        # 1. tier-1 configured tests PASS (exit 0) → floor holds.
        r = new_repo("t1-pass")
        write(r, "a.py", "x = 1\n"); git(r, ["add", "-A"]); git(r, ["commit", "-qm", "b"])
        res = run_test_floor(r, "HEAD", changed_paths=["a.py"], test_cmd="sh -c 'exit 0'")
        expect("tier-1 tests pass → floor passed", res["passed"] and not res["merge_blocked"])
        expect("tier-1 tests pass → tier_used==1", res["tier_used"] == 1)

        # 2. tier-1 configured tests FAIL (exit 1) → floor blocks merge.
        res = run_test_floor(r, "HEAD", changed_paths=["a.py"], test_cmd="sh -c 'exit 1'")
        expect("tier-1 tests fail → floor NOT passed", res["passed"] is False)
        expect("tier-1 tests fail → merge_blocked", res["merge_blocked"] is True)

        # 2b. tier-1 empty command string → fail-closed.
        res = run_test_floor(r, "HEAD", changed_paths=["a.py"], test_cmd="   ")
        expect("tier-1 empty test command → merge_blocked", res["merge_blocked"] is True)

        # 3. tier-2 Python parse-check: valid file → pass; broken file → fail.
        r = new_repo("t2-py")
        write(r, "ok.py", "def f(a):\n    return a\n")
        git(r, ["add", "-A"]); git(r, ["commit", "-qm", "b"]); base = head(r)
        write(r, "ok.py", "def f(a):\n    return a + 1\n")
        res = run_test_floor(r, base, changed_paths=["ok.py"])
        expect("tier-2 valid .py parses → floor passed (tier 2)",
               res["passed"] and res["tier_used"] == 2)
        write(r, "ok.py", "def f(a:\n    return a\n")  # syntax error
        res = run_test_floor(r, base, changed_paths=["ok.py"])
        expect("tier-2 broken .py → merge_blocked (py_compile module form)",
               res["merge_blocked"] is True and res["tier_used"] == 2)

        # 3b. py_compile is invoked as the MODULE form (never the bare non-binary name).
        chk = _default_checkers()[".py"]["cmd"]
        expect("py parse-check uses '-m py_compile' module form",
               "-m" in chk and "py_compile" in chk)

        # 4. Absent-toolchain fake fixture: a checker whose binary does NOT exist degrades
        #    (skip, no crash) and the ladder FALLS THROUGH to tier-3.
        r = new_repo("t2-absent")
        write(r, "keep.md", "hi\n"); git(r, ["add", "-A"]); git(r, ["commit", "-qm", "b"])
        base = head(r)
        write(r, "thing.zz", "code\n")  # untracked
        fake_checkers = {".zz": {"bin": "definitely-not-a-real-binary-xyz",
                                 "cmd": ["definitely-not-a-real-binary-xyz", "--check"],
                                 "manifest": None, "whole_program": False}}
        res = run_test_floor(r, base, changed_paths=["thing.zz"], checkers=fake_checkers)
        expect("absent toolchain degrades (no crash) and falls through to tier-3",
               res["tier_used"] == 3 and res["passed"] is True)
        expect("absent toolchain recorded as skip",
               any(c.get("status") == "skip" for c in res["checks"]))

        # 4b. A PRESENT fake checker that FAILS (exit 1) blocks the floor — proves the
        #     supervised parse path fails closed on a non-zero parser exit.
        fake_bad = os.path.join(tmp, "fake_bad.py")
        with open(fake_bad, "w") as fh:
            fh.write("#!/usr/bin/env python3\nimport sys\nsys.exit(1)\n")
        bad_checkers = {".zz": {"bin": sys.executable,
                                "cmd": [sys.executable, fake_bad],
                                "manifest": None, "whole_program": False}}
        res = run_test_floor(r, base, changed_paths=["thing.zz"], checkers=bad_checkers)
        expect("present failing parser → merge_blocked (fail-closed)",
               res["merge_blocked"] is True and res["tier_used"] == 2)

        # 4c. Manifest gate: a checker whose project manifest is ABSENT skips (degrade).
        gated = {".zz": {"bin": sys.executable, "cmd": [sys.executable, "-c", "pass"],
                         "manifest": "tsconfig.json", "whole_program": False}}
        res = run_test_floor(r, base, changed_paths=["thing.zz"], checkers=gated)
        expect("manifest-absent checker skips and falls through to tier-3",
               res["tier_used"] == 3 and res["passed"] is True)

        # 5. tier-3 diff-read: only a non-code (.md) file changed → tier-3 read pass.
        r = new_repo("t3-read")
        write(r, "doc.md", "one\n"); git(r, ["add", "-A"]); git(r, ["commit", "-qm", "b"])
        base = head(r)
        write(r, "doc.md", "one\ntwo\n")
        res = run_test_floor(r, base, changed_paths=["doc.md"])
        expect("tier-3 diff-read on a readable non-empty diff → floor passed",
               res["passed"] and res["tier_used"] == 3)

        # 5b. tier-3 empty diff (nothing changed) → fail-closed.
        r = new_repo("t3-empty")
        write(r, "doc.md", "one\n"); git(r, ["add", "-A"]); git(r, ["commit", "-qm", "b"])
        res = run_test_floor(r, "HEAD", changed_paths=["doc.md"])
        expect("tier-3 empty diff → merge_blocked (fail-closed)", res["merge_blocked"] is True)

        # ---- REVIEW HANDOFF ------------------------------------------------
        # Build a real diff + manifest to bind against.
        r = new_repo("review")
        write(r, "manifest.yaml", "run_id: r1\nfast_path:\n  eligible: true\n")
        write(r, "styles/app.css", ".a { color: red; }\n")
        git(r, ["add", "-A"]); git(r, ["commit", "-qm", "b"]); base = head(r)
        write(r, "styles/app.css", ".a { color: blue; }\n")
        manifest_path = os.path.join(r, "manifest.yaml")
        floor_ok = {"phase": "test_floor", "passed": True, "merge_blocked": False,
                    "tier_used": 3, "checks": [], "reasons": []}
        f2_clean = {"escalate": False, "reasons": []}

        # 6. Well-formed needs_review spec when floor passed + scope clean + F2 not escalated.
        spec = build_review_spec("r1", "2026-07-11T0Z-css-a1b2", r, base, manifest_path,
                                 ["styles/app.css"], floor_ok, True, f2_clean, attempt_id=1)
        expect("review-spec emits kind=needs_review", spec.get("kind") == "needs_review")
        expect("review-spec has all binding fields",
               all(spec.get(k) is not None or k == "ts" for k in _BINDING_FIELDS))
        expect("review-spec final_diff_digest is prefixed sha256",
               str(spec.get("final_diff_digest", "")).startswith("sha256:"))
        expect("review-spec prompt is bounded and non-empty",
               spec.get("prompt") and len(spec["prompt"].encode("utf-8"))
               < MAX_PROMPT_DIFF_BYTES + 4000)
        expect("review-spec records the vacuous INTEGRATION rationale",
               "vacuous" in spec.get("integration_rationale", "").lower())
        expect("review-spec declares deep/claude reviewer",
               spec["review"]["backend"] == "claude" and spec["review"]["tier"] == "deep")

        # 7. Floor failure blocks merge — review-spec REFUSES to emit.
        floor_bad = {"phase": "test_floor", "passed": False, "merge_blocked": True,
                     "tier_used": 2, "checks": [], "reasons": ["parse-check failed"]}
        blocked = build_review_spec("r1", "pe", r, base, manifest_path, ["styles/app.css"],
                                    floor_bad, True, f2_clean)
        expect("floor failure → review-spec refuses (kind=blocked)", blocked.get("kind") == "blocked")
        expect("floor failure → merge_blocked", blocked.get("merge_blocked") is True)

        # 8. F2 escalation blocks review-spec (F2 runs BEFORE review, CR4-9).
        f2_esc = {"escalate": True, "reasons": ["src/auth/x.ts: touches sensitive path"]}
        blocked2 = build_review_spec("r1", "pe", r, base, manifest_path, ["styles/app.css"],
                                     floor_ok, True, f2_esc)
        expect("F2 escalation → review-spec refuses", blocked2.get("kind") == "blocked")
        expect("F2 escalation reason surfaced",
               any("F2" in x for x in blocked2.get("reasons", [])))

        # 8b. Scope-not-clean blocks review-spec.
        blocked3 = build_review_spec("r1", "pe", r, base, manifest_path, ["styles/app.css"],
                                     floor_ok, False, f2_clean)
        expect("scope-not-clean → review-spec refuses", blocked3.get("kind") == "blocked")

        # ---- ACCEPT REVIEW (four failure modes + anti-replay) --------------
        def good_result():
            return {"kind": "review_result", "status": "ok", "verdict": "approved",
                    "reviewer_backend": "claude", "reviewer_tier": "deep",
                    "reviewer_model": "claude-opus-4-8",
                    "run_id": spec["run_id"], "pre_eval_id": spec["pre_eval_id"],
                    "manifest_digest": spec["manifest_digest"],
                    "baseline_sha": spec["baseline_sha"],
                    "final_diff_digest": spec["final_diff_digest"],
                    "attempt_id": spec["attempt_id"]}

        # 9. Valid approved result → accepted, merge_ok, receipt_fields present.
        out = accept_review(spec, good_result())
        expect("valid approved review → accepted", out["accepted"] is True)
        expect("valid approved review → merge_ok", out["merge_ok"] is True)
        expect("accepted review → receipt_fields present + opus",
               out["receipt_fields"] and "opus" in out["receipt_fields"]["reviewer_model"])
        expect("accepted review records vacuous INTEGRATION rationale",
               "vacuous" in out["integration_rationale"].lower())

        # 10. Malformed (missing required field) → not accepted.
        bad = good_result(); del bad["verdict"]
        out = accept_review(spec, bad)
        expect("malformed review (missing field) → not accepted", out["accepted"] is False)
        expect("malformed review → failure_mode 'malformed'", "malformed" in out["failure_modes"])
        out2 = accept_review(spec, "not-a-dict")
        expect("non-object review result → malformed", "malformed" in out2["failure_modes"])

        # 11. Wrong-tier (backend/tier/model not deep/claude/opus) → not accepted.
        wt = good_result(); wt["reviewer_tier"] = "light"; wt["reviewer_model"] = "sonnet"
        out = accept_review(spec, wt)
        expect("wrong-tier review → not accepted", out["accepted"] is False)
        expect("wrong-tier review → failure_mode 'wrong_tier'", "wrong_tier" in out["failure_modes"])
        wt2 = good_result(); wt2["reviewer_backend"] = "codex"
        out = accept_review(spec, wt2)
        expect("non-claude reviewer → wrong_tier", "wrong_tier" in out["failure_modes"])

        # 12. Timed-out review → not accepted.
        to = good_result(); to["status"] = "timeout"
        out = accept_review(spec, to)
        expect("timed-out review → not accepted", out["accepted"] is False)
        expect("timed-out review → failure_mode 'timed_out'", "timed_out" in out["failure_modes"])

        # 13. Rejected verdict (issues/error) → not accepted, merge blocked.
        rj = good_result(); rj["verdict"] = "issues"
        out = accept_review(spec, rj)
        expect("rejected review (issues) → not accepted", out["accepted"] is False)
        expect("rejected review → failure_mode 'rejected'", "rejected" in out["failure_modes"])
        expect("rejected review → merge_ok False", out["merge_ok"] is False)

        # 14. Anti-stale-replay: a result bound to a DIFFERENT diff digest is rejected.
        stale = good_result(); stale["final_diff_digest"] = "sha256:" + "0" * 64
        out = accept_review(spec, stale)
        expect("stale/mismatched binding → not accepted", out["accepted"] is False)
        expect("stale binding → reason mentions binding mismatch",
               any("binding mismatch" in x for x in out["reasons"]))

        # 15. End-to-end CLI smoke: test-floor → review-spec → accept-review via files.
        floor_f = os.path.join(tmp, "floor.json")
        with open(floor_f, "w") as fh:
            json.dump(floor_ok, fh)
        f2_f = os.path.join(tmp, "f2.json")
        with open(f2_f, "w") as fh:
            json.dump(f2_clean, fh)
        spec_f = os.path.join(tmp, "spec.json")
        rc = main(["prog", "review-spec", "--worktree", r, "--baseline", base,
                   "--manifest", manifest_path, "--run-id", "r1", "--pre-eval-id", "pe1",
                   "--floor-result", floor_f, "--scope-clean", "--f2-result", f2_f,
                   "--changed-file", _write_changed(tmp, ["styles/app.css"]),
                   "--out", spec_f])
        expect("CLI review-spec exits 0 on a clean gate", rc == 0)
        cli_spec = _read_json(spec_f)
        result_f = os.path.join(tmp, "result.json")
        with open(result_f, "w") as fh:
            json.dump({"kind": "review_result", "status": "ok", "verdict": "approved",
                       "reviewer_backend": "claude", "reviewer_tier": "deep",
                       "reviewer_model": "claude-opus-4-8",
                       "run_id": cli_spec["run_id"], "pre_eval_id": cli_spec["pre_eval_id"],
                       "manifest_digest": cli_spec["manifest_digest"],
                       "baseline_sha": cli_spec["baseline_sha"],
                       "final_diff_digest": cli_spec["final_diff_digest"],
                       "attempt_id": cli_spec["attempt_id"]}, fh)
        rc = main(["prog", "accept-review", "--spec", spec_f, "--result", result_f,
                   "--out", os.path.join(tmp, "verdict.json")])
        expect("CLI accept-review exits 0 on a clean approved result", rc == 0)

        # ---- RECEIPT SEALING (HIGH-3: accept-review emits a fully-sealed receipt) ----
        tax_mod = _load_taxonomy()
        expect("shared taxonomy record_digest primitive loads for sealing", tax_mod is not None)

        # Load the receipt schema for a faithful, dependency-free schema check.
        schema_path = os.path.join(os.path.dirname(_script_dir()), "schemas",
                                   "fastpath-review-receipt.schema.json")
        with open(schema_path, "r", encoding="utf-8") as fh:
            receipt_schema = json.load(fh)

        def schema_problems(rec):
            probs = []
            props = receipt_schema.get("properties", {})
            for req in receipt_schema.get("required", []):
                if req not in rec:
                    probs.append("missing required '%s'" % req)
            if receipt_schema.get("additionalProperties") is False:
                for k in rec:
                    if k not in props:
                        probs.append("unknown field '%s'" % k)
            return probs

        # 17. Accepted result → build_sealed_receipt yields a schema-valid, self-verifying receipt.
        ok_accept = accept_review(spec, good_result())
        receipt, err = build_sealed_receipt(spec, ok_accept, ts="2026-07-12T00:00:00Z",
                                            tax=tax_mod)
        expect("sealed receipt built for an accepted result",
               receipt is not None and err is None)
        expect("sealed receipt is schema-valid (required present, no unknown fields)",
               receipt is not None and schema_problems(receipt) == [])
        expect("sealed receipt has a present digest matching the sha256 pattern",
               receipt is not None and isinstance(receipt.get("digest"), str)
               and receipt["digest"].startswith("sha256:") and len(receipt["digest"]) == 71)
        expect("sealed receipt self-digest VERIFIES via record_digest",
               receipt is not None
               and tax_mod.record_digest(receipt, exclude_field="digest") == receipt["digest"])
        expect("sealed receipt carries ts", bool(receipt and receipt.get("ts")))
        expect("sealed receipt carries ALL binding fields",
               receipt is not None
               and all(receipt.get(k) not in (None, "") for k in _BINDING_FIELDS))
        expect("sealed receipt records worktree diff-root + deep tier",
               receipt is not None and receipt.get("worktree") == r
               and receipt.get("reviewer_tier") == "deep")
        expect("sealed receipt verdict normalized to approved",
               receipt is not None and receipt.get("verdict") == "approved")

        # 18. Any tampering breaks the self-digest (the seal is load-bearing).
        if receipt is not None:
            tampered = dict(receipt); tampered["verdict"] = "issues"
            expect("tampering any field breaks the self-digest",
                   tax_mod.record_digest(tampered, exclude_field="digest")
                   != tampered["digest"])

        # 19. Rejected / timed-out / wrong-tier results seal NO receipt (fail-closed).
        for label, res in (("rejected", dict(good_result(), verdict="issues")),
                           ("timed-out", dict(good_result(), status="timeout")),
                           ("wrong-tier", dict(good_result(), reviewer_model="sonnet"))):
            rcp, e = build_sealed_receipt(spec, accept_review(spec, res))
            expect("%s result seals NO receipt (fail-closed)" % label,
                   rcp is None and bool(e))

        # 20. CLI accept-review WRITES the sealed receipt to <run-dir>/review/receipt.json on
        #     acceptance; a rejected result writes NOTHING and exits non-zero.
        run_dir = os.path.join(tmp, "run-accept")
        rc = main(["prog", "accept-review", "--spec", spec_f, "--result", result_f,
                   "--run-dir", run_dir, "--out", os.path.join(tmp, "verdict2.json")])
        written = os.path.join(run_dir, "review", "receipt.json")
        expect("CLI accept-review exits 0 and writes <run-dir>/review/receipt.json",
               rc == 0 and os.path.isfile(written))
        if os.path.isfile(written):
            disk = _read_json(written)
            expect("written receipt is schema-valid AND its self-digest verifies",
                   schema_problems(disk) == []
                   and tax_mod.record_digest(disk, exclude_field="digest")
                   == disk.get("digest"))

        reject_f = os.path.join(tmp, "reject.json")
        rr = _read_json(result_f); rr["verdict"] = "issues"
        with open(reject_f, "w") as fh:
            json.dump(rr, fh)
        run_dir2 = os.path.join(tmp, "run-reject")
        rc = main(["prog", "accept-review", "--spec", spec_f, "--result", reject_f,
                   "--run-dir", run_dir2, "--out", os.path.join(tmp, "verdict3.json")])
        expect("CLI accept-review on a rejected result exits 1 and writes NO receipt",
               rc == 1 and not os.path.exists(
                   os.path.join(run_dir2, "review", "receipt.json")))

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        print("\nSELFTEST FAILED: %d case(s)" % len(failures))
        return 1
    print("\nSELFTEST PASSED")
    return 0


def _write_changed(tmp, paths):
    p = os.path.join(tmp, "changed-%d.txt" % len(os.listdir(tmp)))
    with open(p, "w", encoding="utf-8") as fh:
        fh.write("\n".join(paths) + "\n")
    return p


if __name__ == "__main__":
    sys.exit(main(sys.argv))
