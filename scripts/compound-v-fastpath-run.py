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

v3.0 (Feature B1/B2/B3) — the floor finally has a PRODUCER and three sets:

  * ``resolve-tests`` turns a manifest's ``test_contract`` (``floor_command`` /
    ``full_command`` / ``impacted_map``) plus one job's ``test_scope`` into the ordered,
    deduped command list — the file every worker takes as ``--test-contract-file``. Before
    this, ``--test-cmd`` had no producer anywhere in the repo (``"$CFG_TESTS"`` was an
    unbound shell placeholder), so tier-1 had never executed once.
  * ``test-floor --manifest`` runs that same resolved set at tier-1.
  * At ``test_scope: impacted`` the set is the UNION OF THREE — impacted ∪
    previously-failing ∪ newly-added — with every MATCHING ``impacted_map`` rule unioned,
    an unmapped path resolving to ``full_command``, and an uncomputable previously-failing
    set (no ``tests.failures[]`` in the last recorded run) also resolving to
    ``full_command`` rather than being silently dropped.
  * The changed-path derivation now happens BEFORE the tier-1 return, which is what makes
    a configured-tests floor diff-proportionate at all.

v3.4.1 (decision 4) — a SCOPED job runs the tests in its scope, never the whole app:

  * an unmapped path resolves to ``full_command`` only at tier FULL (or when the manifest
    declares no tier). At SCOPED and DIRECT it resolves to ``referencing_tests()`` — the
    test files that NAME the changed module, sorted, bounded and capped at five — and to
    the floor alone when there are none. The slice is then labelled
    ``impacted+referencing`` and carries ``selected_count``.

  THE FLOOR IS EARLY FEEDBACK, NOT A GUARANTEE. It does not restore what the full suite
  guaranteed; CI does. The three sets structurally omit every existing, previously-passing
  test the declared map fails to select — change ``src/parser.py``, break
  ``tests/test_cli_integration.py`` through an indirect import, and no set selects it.

CLI:
    compound-v-fastpath-run.py test-floor  --worktree DIR [--baseline SHA]
        [--changed-file paths.txt] [--test-cmd "CMD"]
        [--manifest manifest.yaml --job-id ID | --scope SCOPE]
        [--last-result job_result.json | --no-prior-run] [--out result.json]
    compound-v-fastpath-run.py resolve-tests --worktree DIR --manifest manifest.yaml
        [--baseline SHA] [--job-id ID | --scope full|impacted|floor_only]
        [--last-result job_result.json | --no-prior-run] [--out contract.json]
    compound-v-fastpath-run.py review-spec --worktree DIR --baseline SHA --manifest FILE
        --run-id ID --pre-eval-id ID [--attempt-id N] --floor-result FILE
        --scope-clean --f2-result FILE [--out spec.json]
    compound-v-fastpath-run.py accept-review --spec spec.json --result result.json
        (--run-dir DIR | --receipt-out FILE) [--ts ISO] [--out v.json]
        (exactly one receipt destination is REQUIRED — acceptance always seals a receipt)
    compound-v-fastpath-run.py --selftest

Exit codes: 0 = phase OK / floor holds / review accepted; 1 = floor failed, review-spec refused
(blocked), or review rejected. Non-zero is advisory — the dispatcher owns the merge decision.
"""

import argparse
import datetime as _dt
import fnmatch
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
TEST_TIMEOUT_S = 480        # tier-1 configured project test command
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
_SCOPE_CHECK_CACHE = []


def _scope_check():
    """Import ``compound-v-scope-check.py`` by path, or return None.

    It is the repo's ONE path-glob authority (``glob_to_regex`` / ``matches``: ``*`` does
    not cross ``/``, ``**`` does, ``[`` is literal). Feature B2's ``impacted_map`` matching
    reuses it rather than reaching for ``fnmatch`` — a second, weaker matcher would diverge
    from the gate, and a divergence here silently DROPS tests."""
    if _SCOPE_CHECK_CACHE:
        return _SCOPE_CHECK_CACHE[0]
    import importlib.util
    path = os.path.join(_script_dir(), "compound-v-scope-check.py")
    try:
        spec = importlib.util.spec_from_file_location("compound_v_scope_check", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception:  # noqa: BLE001
        return None
    _SCOPE_CHECK_CACHE.append(mod)
    return mod


# Paths that are BOOKKEEPING NOISE — never build inputs, never test inputs. This
# is a NAMED list, not "whatever git ignores", and the difference is the whole
# point: a cross-model review called the ignored-status proxy HIGH and was right.
# `.env`, generated sources, fixtures, vendored artifacts and local config are all
# routinely gitignored AND can absolutely change what a test does. Using git's
# ignore status to mean "cannot affect tests" would silently narrow the selected
# set on exactly the changes that most deserve a full run.
#
# So only these two shapes are dropped, and only when git also ignores them:
#   * this project's own harness worktrees (`.claude/worktrees/`, `.worktrees/`)
#   * Python bytecode caches
# Anything else that is ignored stays in the changed set and, matching no `when`
# glob, resolves to `full_command` — the safe direction.
_TEST_NOISE_PREFIXES = (".claude/worktrees/", ".worktrees/", ".v29-worktrees/")
# A COMPONENT, not a substring: `fixtures_not__pycache__/` contains the string and
# is not a bytecode cache, and dropping real generated fixtures from test selection
# is exactly the silent narrowing this list was rewritten to avoid.
_TEST_NOISE_COMPONENTS = ("__pycache__",)
_TEST_NOISE_SUFFIXES = (".pyc", ".pyo")


def _is_test_noise(rel):
    # NOT `lstrip("./")` — lstrip strips CHARACTERS, so it ate the leading dot of
    # `.claude/worktrees/...` and turned it into `claude/worktrees/...`, which
    # matched no prefix and made this predicate answer False for the single most
    # common noise path in this repo. Caught by its own test on the first run.
    r = str(rel or "")
    while r.startswith("./"):
        r = r[2:]
    if any(r.startswith(p) for p in _TEST_NOISE_PREFIXES):
        return True
    if any(part in _TEST_NOISE_COMPONENTS for part in r.split("/")):
        return True
    return any(r.endswith(suf) for suf in _TEST_NOISE_SUFFIXES)


def _git_check_ignore(worktree, candidates):
    """Ask git which of ``candidates`` it ignores, in ONE ``git check-ignore --stdin``
    call. Returns the ignored subset, or ``None`` when the answer cannot be trusted
    (any git/launch failure). Exit status is 0 when at least one path was ignored,
    1 when none were, and >1 on a real error — so 1 is success with an empty answer,
    not a failure. Shared by ``_drop_gitignored`` and the unmapped-promotion
    bookkeeping filter — both need the SAME "does git ignore this" primitive, just
    over different candidate sets."""
    if not candidates:
        return set()
    try:
        # `universal_newlines=True` (not `text=`) — Python 3.6-compatible, and this
        # file is 3.9-safe by policy. WITHOUT it, communicate() is handed a str on a
        # bytes pipe, raises TypeError, and the except below quietly returns None —
        # which falls back to the unfiltered union and looks exactly like "nothing
        # was ignored". The first draft did precisely that, and the dogfood caught it
        # by the path count not moving.
        proc = subprocess.Popen(
            ["git", "-C", worktree, "check-ignore", "--stdin"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True)
        out, _ = proc.communicate("\n".join(candidates) + "\n", timeout=30)
    except Exception:  # noqa: BLE001
        return None
    if proc.returncode not in (0, 1):
        return None
    return {ln.strip() for ln in (out or "").splitlines() if ln.strip()}


def _drop_gitignored(worktree, paths):
    """``paths`` minus IGNORED BOOKKEEPING NOISE. None when it cannot be decided.

    Two conditions, both required: the path must look like harness noise
    (`_is_test_noise`) AND git must actually ignore it. The second stops a real
    source file that merely lives under a similarly-named directory from vanishing;
    the first stops the ignore list from being read as "irrelevant to tests".
    """
    if not paths:
        return list(paths or [])
    candidates = [p for p in paths if _is_test_noise(p)]
    if not candidates:
        return list(paths)
    ignored = _git_check_ignore(worktree, candidates)
    if ignored is None:
        return None
    return [p for p in paths if p not in ignored]


# Bookkeeping paths that can NEVER change what a test does — this project's own
# audit trail under a run directory (lockfiles, state.json, lane maps). Named,
# not inferred: a repo could plausibly keep real fixtures under a directory that
# merely SOUNDS like bookkeeping, so this is one literal prefix, not a heuristic.
_UNMAPPED_BOOKKEEPING_PREFIX = "docs/superpowers/execution/"


def _bookkeeping_for_unmapped(worktree, paths):
    """Split ``paths`` for the unmapped⇒full_command PROMOTION decision ONLY — never
    for the executed test set, never for ``_changed_from_scope``'s general changed-path
    derivation. Two exclusions, unioned:

      * this project's own run-directory bookkeeping (``_UNMAPPED_BOOKKEEPING_PREFIX``) —
        a lockfile or a state.json under a run's own audit trail is not a build input;
      * anything git itself ignores (ONE ``git check-ignore --stdin`` call over what the
        prefix rule left).

    A path excluded here still matched no ``when`` glob — it is simply not treated as
    "unknown blast radius" for the purpose of dragging in the whole suite. Everything
    else about the unmapped path is unaffected: it still contributes no command to
    ``ordered``, and a single REAL unmapped path anywhere in the union still promotes.

    Returns ``(real, ignored_count)``. On any git failure the git-ignore half of the
    exclusion is simply skipped (paths stay REAL) — the safe direction here is running
    the wider suite, not narrowing it on an unreadable git call."""
    if not paths:
        return list(paths or []), 0

    def _rel(p):
        r = str(p or "")
        while r.startswith("./"):
            r = r[2:]
        return r

    prefixed = {p for p in paths if _rel(p).startswith(_UNMAPPED_BOOKKEEPING_PREFIX)}
    rest = [p for p in paths if p not in prefixed]
    ignored = _git_check_ignore(worktree, rest) if worktree and rest else set()
    if ignored is None:
        ignored = set()
    bookkeeping = prefixed | (ignored & set(rest))
    real = [p for p in paths if p not in bookkeeping]
    return real, len(bookkeeping)


def _changed_from_scope(worktree, baseline):
    """The changed set FOR TEST SELECTION — which is not the scope gate's set.

    `compound-v-scope-check.py:changed_files` unions tracked edits, untracked files
    AND gitignored ones, deliberately: a worker that writes `.env` or into `dist/`
    must be caught, and dropping ignored paths there was a real exploit this project
    fixed in 2.8. That same union is WRONG as the input to test selection, and
    dogfood 1 caught it before the run started: twelve leftover `.claude/worktrees/**`
    and `__pycache__/*.pyc` entries matched no `when` glob, the "unmapped path ⇒
    unknown blast radius ⇒ full_command" rule fired on pure noise, and the scoping
    3.1.0 shipped collapsed straight back to running everything. In any repository
    with ordinary untracked churn it would have been defeated on arrival.

    One function, two questions — the same defect `isolation` had in 3.0.4, where a
    manifest-layer name and an agent-layer name were the same word.

    So: tracked edits and untracked-but-not-ignored files (a brand-new source file is
    a real change with a real blast radius) — and NOT the ignored set, which by
    construction is not part of the build and cannot affect a test. If the ignored
    set cannot be determined, the FULL union is returned unchanged: over-selecting
    tests is the safe direction, and silently narrowing on a failed git call is not.
    """
    mod = _scope_check()
    if mod is None:
        return None
    try:
        full = list(mod.changed_files(worktree, baseline))
    except Exception:  # noqa: BLE001
        return None
    filtered = _drop_gitignored(worktree, full)
    return full if filtered is None else filtered


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
# v3.0 Feature B2/B3 — the test contract RESOLVER: the producer `--test-cmd` never had.
#
# WHAT THE FLOOR IS, SAID WITHOUT VARNISH. The floor is an EARLY-FEEDBACK OPTIMIZATION.
# It does NOT restore what the full suite guaranteed; CI does. The union of impacted,
# previously-failing and newly-added structurally omits every existing, previously-passing
# test the declared map fails to select: change `src/parser.py`, break
# `tests/test_cli_integration.py` through an indirect import, and NO set selects it — the
# floor passes and only the merge-blocking CI run catches it. A hand-written glob map
# carries strictly less information than a call graph, and call-graph-derived selection is
# already measured at 0.2%-10.6% unsafe per revision, so 0.2% is an optimistic floor and
# not an expectation. Nothing here may be described as preserving pre-merge safety.
#
# Resolution belongs to the CALLER (this Python), execution to the worker: the resolved
# slice reaches an external worker as `--test-contract-file`, a real argument, never as
# prose in a prompt. See skills/backend-launcher/SKILL.md and
# skills/compound-v/execution-manifest.md — this code is their mechanical half.
# --------------------------------------------------------------------------- #
# INPUT enum. A manifest declares one of exactly these three, and 3.4.1 does not add a
# fourth: `impacted+referencing` is an OUTPUT label on the resolved slice, never a value
# a job may write in its `test_scope`.
VALID_TEST_SCOPES = ("full", "impacted", "floor_only")


def default_scope_for(contract, tier=None):
    """(scope, why). The default a job gets when it declares no ``test_scope``.

    Until 3.1.0 that default was the literal string ``"full"``, which meant a
    two-line change ran the entire suite — twenty to thirty thousand tests in a real
    application — because nobody had written ``test_scope:`` on the job. The maintainer's
    rule, set 2026-09-02: **run the tests related to the change, and running the whole
    project is not a default, it is a decision.**

    The default is now DERIVED from what the repository has actually told us:

    * ``DIRECT`` triage tier with a declared floor ⇒ ``floor_only``. A change small
      enough to skip the pipeline gets the floor and nothing else.
    * a declared, non-empty ``impacted_map`` ⇒ ``impacted``. The map IS the repository
      saying which tests relate to which paths; honouring it is not a guess.
    * otherwise ⇒ ``full``, because with no map there is no information about what
      relates to what, and the honest answer to "which tests matter here?" is "all of
      them". The `why` string says so, so the fix — write an ``impacted_map`` — is
      visible instead of mysterious.

    What this does NOT change: the union rule (impacted ∪ previously-failing ∪
    newly-added), the fail-closed empty-set refusal, and the standing statement that the
    scoped floor is EARLY FEEDBACK and does not restore what a full suite guarantees. A
    glob map carries strictly less information than a call graph, and call-graph
    selection is already measured at 0.2%-10.6% unsafe per revision.
    """
    contract = contract if isinstance(contract, dict) else {}
    tier_s = str(tier or "").strip().upper()
    floor = contract.get("floor_command")
    has_floor = isinstance(floor, str) and floor.strip()
    if tier_s == "DIRECT" and has_floor:
        return "floor_only", ("triage tier DIRECT with a declared floor_command — the "
                              "floor is the whole test obligation at this tier")
    rows = contract.get("impacted_map")
    if isinstance(rows, list) and rows:
        return "impacted", ("test_contract declares an impacted_map (%d rule(s)) — the "
                            "repository has said which tests relate to which paths, so "
                            "the default honours it instead of running everything"
                            % len(rows))
    return "full", ("test_contract declares no impacted_map, so nothing here knows which "
                    "tests relate to this change and 'all of them' is the only truthful "
                    "answer — declare an impacted_map to scope this")


class TestContractError(Exception):
    """A test contract that cannot resolve to a non-empty command set. Fail-closed:
    a scope must never resolve to running NOTHING, and a silent zero is a fabricated
    pass wearing a green tick."""


def _decode(data):
    if isinstance(data, bytes):
        return data.decode("utf-8", "replace")
    return data or ""


def added_paths(worktree, baseline="HEAD"):
    """The NEWLY-ADDED set: ``git diff --name-only --diff-filter=A <baseline>``.

    Returns ``None`` when git could not answer — the caller then fails closed rather
    than reading "no answer" as "nothing was added". Note the honest boundary: this
    sees files added *against the baseline* (worktree or committed), and does not see
    an untracked file git has never been told about; the scope gate unions
    ``ls-files --others`` for exactly that reason, and the spec pins this set to the
    ``--diff-filter=A`` form."""
    rc, out = _git(worktree, ["diff", "--name-only", "--diff-filter=A", baseline])
    if rc != 0:
        return None
    return [ln.strip() for ln in _decode(out).splitlines() if ln.strip()]


def previously_failing(last_result):
    """The PREVIOUSLY-FAILING set, read from the last recorded run's ``tests.failures[]``
    (``schemas/job_result.schema.json``, Feature B3).

    Returns ``(failures, available)``:

    * ``last_result`` is ``None``  → ``([], True)``. No prior run was recorded, so nothing
      is *known to have failed*; the set is empty BY CONSTRUCTION, not unknown. (The CLI
      makes the caller say this out loud with ``--no-prior-run``, so a forgotten
      ``--last-result`` cannot quietly become "nothing was failing".)
    * a prior run with a measured ``failures`` array → ``(list, True)``. An EMPTY array is
      measured-and-nothing-failed, which is a real answer.
    * a prior run whose ``tests`` block or ``failures`` field is ABSENT → ``(None, False)``.
      The runner reported nothing machine-readable, the set is UNCOMPUTABLE, and B2's rule
      applies: the floor falls back to ``full_command`` rather than silently dropping the
      set and degrading three sets to two."""
    if last_result is None:
        return [], True
    if not isinstance(last_result, dict):
        return None, False
    tests = last_result.get("tests")
    if not isinstance(tests, dict) or "failures" not in tests:
        return None, False
    failures = tests.get("failures")
    if not isinstance(failures, list):
        return None, False
    out = [str(f) for f in failures if str(f).strip()]
    return out, True


def _impacted_for(contract, paths):
    """Map changed paths onto ``impacted_map`` commands.

    EVERY matching rule contributes its ``run`` — the rules UNION. First-match-wins would
    silently drop coverage the map explicitly DECLARES, which is worse than never having
    declared it. ``{path}`` in a ``run`` is substituted with the matching path.

    Returns ``(commands, unmapped)``: ``unmapped`` are the paths that matched no ``when``
    glob at all — unknown blast radius, which the caller resolves to ``full_command``,
    never to "nothing to run"."""
    mod = _scope_check()
    if mod is None:
        raise TestContractError(
            "the path-glob authority (compound-v-scope-check.py) failed to load — "
            "refusing to resolve impacted_map with a second, weaker matcher")
    rows = contract.get("impacted_map") or []
    if not isinstance(rows, list):
        raise TestContractError("test_contract.impacted_map must be a list of {when, run}")
    commands = []
    unmapped = []
    for path in paths:
        matched = False
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                raise TestContractError(
                    "test_contract.impacted_map[%d] must be a mapping with 'when' and 'run'"
                    % i)
            when = row.get("when")
            run = row.get("run")
            if not isinstance(when, str) or not when.strip() \
                    or not isinstance(run, str) or not run.strip():
                raise TestContractError(
                    "test_contract.impacted_map[%d] is half-declared (both 'when' and "
                    "'run' are mandatory) — a half-declared rule selects nothing" % i)
            if mod.matches(path, when):
                matched = True
                commands.append(run.replace("{path}", path))
        if not matched:
            unmapped.append(path)
    return commands, unmapped


def _dedupe(items):
    """Stable de-duplication: first occurrence wins, order preserved (the floor is first)."""
    seen = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


# --------------------------------------------------------------------------- #
# v3.4.1 decision 4 — what a SCOPED job owes.
#
# An unmapped path is unknown blast radius, and until 3.4.1 that resolved to
# `full_command` at EVERY tier — so a two-line change the triage engine had already
# called SCOPED still ran the whole suite the moment one changed file matched no
# `when` glob. Decision 4, taken 2026-09-03: at SCOPED and DIRECT an unmapped path
# resolves instead to the tests that REFERENCE the changed module, capped, and to the
# floor alone when there are none. FULL keeps today's rule, and CI stays the
# merge-blocking backstop either way.
#
# This is a HEURISTIC and is labelled as one. A textual reference is not a call graph:
# it over-selects (a test that merely names the file in a comment) and under-selects
# (a test that reaches the module through three layers of indirection and never spells
# its name). It buys early feedback proportionate to the change; it does not restore
# what the full suite guaranteed, and nothing here may be written as if it did.
# --------------------------------------------------------------------------- #
REFERENCING_CAP = 5              # suites selected beyond impacted + floor
REFERENCING_MAX_FILES = 2000     # candidate test files considered (bounded walk)
REFERENCING_READ_BYTES = 200000  # bytes read per candidate (bounded read)
REFERENCING_MIN_TOKEN = 3        # a 1-2 char token would "reference" everything

TEST_DIR_NAMES = ("tests", "test", "spec", "__tests__")
TEST_FILE_GLOBS = ("*_test.*", "test_*.*", "*.spec.*")
_REFERENCING_SKIP_DIRS = frozenset((
    "node_modules", "__pycache__", "venv", "vendor", "dist", "build",
    "target", "coverage", "site-packages",
))
# Language-agnostic on purpose: a suffix known to be executable gets a runner, and
# everything else is REPORTED and not run rather than guessed at. A guessed runner
# that exits 0 because it did nothing is a fabricated pass wearing a green tick.
_TEST_RUNNERS = ((".sh", "bash"), (".py", "python3"))


def _is_test_path(rel):
    """The repository's test surface, by convention only: any file under a ``tests/``,
    ``test/``, ``spec/`` or ``__tests__/`` directory at any depth, plus the three
    filename conventions (``*_test.*``, ``test_*.*``, ``*.spec.*``) anywhere."""
    parts = rel.split("/")
    if any(part in TEST_DIR_NAMES for part in parts[:-1]):
        return True
    name = parts[-1]
    return any(fnmatch.fnmatchcase(name, pat) for pat in TEST_FILE_GLOBS)


def _test_runner_for(rel):
    """``bash <file>`` / ``python3 <file>``, or None when nothing here knows how to run
    it. None means REPORTED, never run — see the note above."""
    for suffix, runner in _TEST_RUNNERS:
        if rel.endswith(suffix):
            return "%s %s" % (runner, shlex.quote(rel))
    return None


def referencing_tests(repo, changed_paths, cap=REFERENCING_CAP):
    """The tests that mention the changed paths: ``[{"file": rel, "run": cmd|None}]``.

    A candidate is a test file (``_is_test_path``) whose first ``REFERENCING_READ_BYTES``
    contain the basename of a changed path or its module name (that basename without its
    extension). Plain substring matching, so it is LANGUAGE-AGNOSTIC — a Go test naming
    ``parser.go``, a shell test naming ``deploy.sh`` and a Python test importing
    ``compound_v_thing`` are all found by the same rule, with no per-language parser to
    keep current.

    BOUNDED in three directions, because this runs on every SCOPED job: the walk visits
    at most ``REFERENCING_MAX_FILES`` candidates, each file is read up to
    ``REFERENCING_READ_BYTES``, and at most ``cap`` results are returned. The walk and
    the result are SORTED by repository-relative path, so the same worktree always yields
    the same list — a test set that varies with filesystem order is not a contract. A
    changed path never selects itself.

    Tokens shorter than ``REFERENCING_MIN_TOKEN`` are dropped: ``a`` would "reference"
    almost every file in the repository, which is the full suite wearing a scoped label.
    """
    repo = repo or "."
    try:
        cap = int(cap)
    except (TypeError, ValueError):
        cap = REFERENCING_CAP
    if cap <= 0:
        return []

    tokens = set()
    changed_set = set()
    for path in changed_paths or []:
        rel = str(path).strip().replace("\\", "/")
        while rel.startswith("./"):
            rel = rel[2:]
        if not rel:
            continue
        changed_set.add(rel)
        base = rel.rsplit("/", 1)[-1]
        stem = base.rsplit(".", 1)[0] if "." in base else base
        for token in (base, stem):
            if len(token) >= REFERENCING_MIN_TOKEN:
                tokens.add(token)
    if not tokens:
        return []

    candidates = []
    for dirpath, dirnames, filenames in os.walk(repo):
        # Prune before descending: dot-directories (`.git`, `.venv`, `.tox`, and the
        # `.claude/worktrees` trees this pipeline itself creates) and the usual vendored
        # ones. Symlinked directories are not followed (os.walk's default).
        dirnames[:] = sorted(d for d in dirnames
                             if not d.startswith(".") and d not in _REFERENCING_SKIP_DIRS)
        for name in sorted(filenames):
            rel = os.path.relpath(os.path.join(dirpath, name), repo)
            rel = rel.replace(os.sep, "/")
            if rel in changed_set or not _is_test_path(rel):
                continue
            candidates.append(rel)
            if len(candidates) >= REFERENCING_MAX_FILES:
                break
        if len(candidates) >= REFERENCING_MAX_FILES:
            break

    out = []
    for rel in sorted(candidates):
        try:
            with open(os.path.join(repo, rel), "rb") as fh:
                blob = fh.read(REFERENCING_READ_BYTES)
        except (OSError, IOError):
            continue
        text = blob.decode("utf-8", "replace")
        if any(token in text for token in tokens):
            out.append({"file": rel, "run": _test_runner_for(rel)})
            if len(out) >= cap:
                break
    return out


def resolve_test_commands(contract, scope, changed_paths=None, new_paths=None,
                          prev_failures=None, prev_failures_available=True,
                          tier=None, referencing=None, worktree=None):
    """Resolve a manifest ``test_contract`` + one job's ``test_scope`` into the ordered,
    deduped command list a worker executes.

    Returns ``(slice, notes)``. ``slice`` holds EXACTLY the keys the worker's
    ``--test-contract-file`` validator accepts (``scope``, ``resolved_commands``, the
    informational ``floor_command`` / ``full_command`` when declared, and ``timeout_s``
    when the contract declares one) — nothing else, so a typo cannot pass silently as
    "nothing to run". ``notes`` is the human-readable record of WHY each command is in
    the set; it is deliberately NOT part of the slice.

    The rules, in one place:

    * the floor always runs, at every tier, and comes FIRST;
    * ``floor_only`` means ONLY the floor — never nothing;
    * ``full`` runs the floor plus ``full_command``;
    * ``impacted`` runs the floor plus the UNION OF THREE SETS —
      impacted ∪ previously-failing ∪ newly-added — because running only the impacted set
      is the mistake regression-test-selection practice already made and corrected;
    * a changed path matching no ``when`` glob resolves to ``full_command`` — but only at
      tier FULL or when no tier was given (v3.4.1 decision 4). At SCOPED and DIRECT it
      resolves instead to ``referencing`` (the list ``referencing_tests()`` computed),
      and to the floor alone when that list is empty. Before that promotion decision,
      bookkeeping noise — this project's own ``docs/superpowers/execution/**`` audit
      trail, and anything git itself ignores — is dropped from the unmapped set FOR THE
      PROMOTION ONLY (finding 102/105): it still selected no command, it just does not
      drag in the whole suite by itself;
    * an uncomputable previously-failing set also resolves to ``full_command``, at every
      tier — that is a fail-closed rule about DATA THIS RUN COULD NOT READ, not about the
      size of the change, and the tier has nothing to say about it.

    ``tier`` is the manifest's ``triage.tier``; ``referencing`` is the caller's already-
    computed referencing list, so this function stays a pure resolver and the filesystem
    walk happens exactly once, in ``resolve_from_manifest``. ``worktree`` is used ONLY for
    the bookkeeping git-ignore check above; every other input here is data the caller
    already derived.

    Raises ``TestContractError`` whenever the answer would be an empty command set."""
    contract = contract if isinstance(contract, dict) else {}
    derived_note = None
    if scope in (None, ""):
        scope, derived_note = default_scope_for(contract)
    scope = str(scope)
    tier_s = str(tier or "").strip().upper()
    scoped_tier = tier_s in ("SCOPED", "DIRECT")
    scope_label = None
    if scope not in VALID_TEST_SCOPES:
        raise TestContractError(
            "test_scope %r is not one of %s" % (scope, ", ".join(VALID_TEST_SCOPES)))

    def _text(key):
        val = contract.get(key)
        return val.strip() if isinstance(val, str) and val.strip() else None

    floor = _text("floor_command")
    full = _text("full_command")
    notes = []
    ordered = []
    if derived_note:
        notes.append("scope: no test_scope declared, defaulted to %r — %s"
                     % (scope, derived_note))

    if floor:
        ordered.append(floor)
        notes.append("floor: floor_command runs at every tier and comes first")
    elif scope == "floor_only":
        raise TestContractError(
            "test_scope 'floor_only' with no test_contract.floor_command — floor_only "
            "means ONLY the floor, never nothing")
    else:
        notes.append("floor: no floor_command declared (nothing always-on to run first)")

    if scope == "full":
        if not full:
            raise TestContractError(
                "test_scope 'full' with no test_contract.full_command — the full scope "
                "would resolve to nothing")
        ordered.append(full)
        notes.append("full: full_command (the declared whole suite)")

    elif scope == "impacted":
        if not full:
            raise TestContractError(
                "test_scope 'impacted' with no test_contract.full_command — an unmapped "
                "path and an uncomputable failing set both resolve to it, so it is "
                "mandatory")
        changed = list(changed_paths or [])
        new = list(new_paths or [])

        # SET 1 — impacted: every matching rule for every changed path.
        impacted_cmds, unmapped = _impacted_for(contract, changed)
        ordered.extend(impacted_cmds)
        notes.append("impacted: %d command(s) from %d changed path(s) (every matching "
                     "rule unions)" % (len(impacted_cmds), len(changed)))

        # SET 2 — previously failing: the exact identifiers the LAST run measured.
        if prev_failures_available:
            failing = list(prev_failures or [])
            ordered.extend(failing)
            notes.append("previously-failing: %d command(s) from the last run's "
                         "tests.failures[]" % len(failing))
        else:
            ordered.append(full)
            notes.append("previously-failing: UNCOMPUTABLE (the last run reported no "
                         "machine-readable tests.failures[]) — falling back to "
                         "full_command rather than silently dropping the set")
            # Same label rule as the unmapped branch (review-2 of 3.4.1, finding 4):
            # full_command is in the set, so the slice says so — never a
            # `impacted+referencing` label beside a note that ran the whole suite.
            scope = "full"
            notes.append("scope: labelled `full` — full_command was added because the "
                         "previously-failing set is uncomputable")

        # SET 3 — newly added: run through the SAME map; an added file nothing declares
        # is unknown blast radius exactly like a changed one.
        new_cmds, new_unmapped = _impacted_for(contract, new)
        ordered.extend(new_cmds)
        notes.append("newly-added: %d command(s) from %d added path(s) "
                     "(git diff --diff-filter=A)" % (len(new_cmds), len(new)))

        if unmapped or new_unmapped:
            missing = ", ".join(sorted(set(unmapped + new_unmapped)))
            if not scoped_tier:
                # finding 102/105: bookkeeping noise never TRIGGERS the promotion —
                # it still ran no command, and a real unmapped path anywhere else in
                # the union still promotes exactly as before.
                promoting, ignored_n = _bookkeeping_for_unmapped(
                    worktree, sorted(set(unmapped + new_unmapped)))
                if ignored_n:
                    notes.append("ignored %d bookkeeping path(s) for the unmapped rule"
                                 % ignored_n)
                if promoting:
                    ordered.append(full)
                    notes.append(
                        "unmapped: %s matched no `when` glob — unknown blast radius "
                        "resolves to full_command, never to nothing"
                        % ", ".join(sorted(promoting)))
                    # The label follows the obligation (review-1 of 3.4.1, issue 4): a
                    # FULL-tier job whose unmapped path pulled in `full_command` ran the
                    # whole suite, and `scope: impacted` beside it made a correct run
                    # trip the reviewer's "must match what the tier owes" rule.
                    scope = "full"
                    notes.append(
                        "scope: labelled `full` — full_command was added for an "
                        "unmapped path at this tier, so the whole suite is what ran")
            else:
                # v3.4.1 decision 4. The triage engine has already said this change is
                # small; answering "then run everything" contradicts the tier that was
                # just computed. Take the tests that NAME the changed module instead.
                rows = [r for r in (referencing or []) if isinstance(r, dict)]
                runnable = [str(r.get("run")).strip() for r in rows
                            if str(r.get("run") or "").strip()]
                reported = [str(r.get("file")) for r in rows
                            if not str(r.get("run") or "").strip()]
                if runnable:
                    ordered.extend(runnable)
                    scope_label = "impacted+referencing"
                    notes.append(
                        "unmapped: %s matched no `when` glob — at tier %s that resolves "
                        "to the %d test(s) REFERENCING the changed module(s), not to "
                        "full_command (v3.4.1 decision 4; capped at %d). This is a "
                        "textual heuristic, not a call graph: CI stays the backstop"
                        % (missing, tier_s, len(runnable), REFERENCING_CAP))
                else:
                    notes.append("unmapped: referencing tests found none — floor only "
                                 "at tier %s" % tier_s)
                if reported:
                    notes.append("unmapped: %d referencing file(s) REPORTED and not run "
                                 "(no known runner for them): %s"
                                 % (len(reported), ", ".join(reported)))

    ordered = _dedupe([c for c in ordered if str(c).strip()])
    if not ordered:
        raise TestContractError(
            "test_scope %r resolved to an EMPTY command set — a scope must never resolve "
            "to running nothing (declare floor_command / full_command / impacted_map)"
            % scope)

    # The label is OUTPUT-ONLY. `VALID_TEST_SCOPES` is unchanged as an INPUT enum — no
    # manifest may declare `test_scope: impacted+referencing` — but a slice whose
    # unmapped paths were answered by the referencing heuristic says so, because a
    # reviewer reading `impacted` could not otherwise tell which rule selected the set.
    # `selected_count` rides with it: the number of commands, a count and never a saving.
    if scope == "full":
        scope_label = None  # a promotion to full outranks the referencing label
    slice_ = {"scope": scope_label or scope, "resolved_commands": ordered}
    if scope_label:
        slice_["selected_count"] = len(ordered)
    if floor:
        slice_["floor_command"] = floor
    if full:
        slice_["full_command"] = full
    timeout_s = contract.get("timeout_s")
    if timeout_s is not None:
        if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)) \
                or timeout_s <= 0:
            raise TestContractError(
                "test_contract.timeout_s must be a positive number when declared "
                "(got %r)" % (timeout_s,))
        slice_["timeout_s"] = timeout_s
    return slice_, notes


def resolve_from_manifest(manifest, job_id=None, scope=None, worktree=None,
                          baseline="HEAD", changed_paths=None, new_paths=None,
                          last_result=None, no_prior_run=False):
    """Resolve the contract for one job straight off a parsed manifest.

    ``scope`` (explicit) wins; otherwise the named job's ``test_scope`` is used; an absent
    ``test_scope`` is DERIVED by ``default_scope_for`` from the contract's own
    ``impacted_map`` and the manifest's triage tier — it is no longer the hardcoded
    ``full`` that made a two-line change run the entire suite. The changed and
    newly-added sets are derived from git when not supplied.

    The previously-failing set is the one input a caller can get wrong by SAYING NOTHING,
    so silence is the conservative answer here: pass ``last_result`` (a parsed
    ``job_result``) or assert ``no_prior_run=True``. Neither ⇒ the set is treated as
    uncomputable and the floor falls back to ``full_command``.

    v3.4.1: the manifest's ``triage.tier`` is read UNCONDITIONALLY (it used to be consulted
    only when the scope had to be derived) and passed to ``resolve_test_commands``, because
    the tier now decides how an unmapped path resolves — not just what the default scope
    is. At SCOPED and DIRECT this also computes ``referencing_tests()`` from the worktree.
    Returns ``(slice, notes)``."""
    manifest = manifest if isinstance(manifest, dict) else {}
    contract = manifest.get("test_contract")
    triage = manifest.get("triage")
    tier = triage.get("tier") if isinstance(triage, dict) else None
    if scope in (None, "") and job_id:
        for job in manifest.get("jobs") or []:
            if isinstance(job, dict) and str(job.get("id")) == str(job_id):
                scope = job.get("test_scope")
                break
    derived_note = None
    if scope in (None, ""):
        scope, derived_note = default_scope_for(contract, tier)

    if scope == "impacted":
        # Fail-closed applies to a scope the manifest ASKED FOR. A scope this function
        # DERIVED is a convenience, and a convenience that halts a run is worse than the
        # behaviour it replaced — so a derived `impacted` that cannot compute its inputs
        # degrades to `full`, loudly. An explicit `test_scope: impacted` still stops:
        # someone declared it, and silently widening their declaration would be the
        # fabricated-scope failure this whole resolver exists to prevent.
        degrade = None
        if changed_paths is None:
            changed_paths = _changed_from_scope(worktree, baseline)
            if changed_paths is None:
                degrade = ("cannot derive changed paths (scope-check unavailable)")
        if degrade is None and new_paths is None:
            new_paths = added_paths(worktree, baseline)
            if new_paths is None:
                degrade = ("cannot derive the newly-added set "
                           "(git diff --diff-filter=A failed)")
        if degrade is not None:
            if derived_note is None:
                raise TestContractError(
                    "%s and test_scope is 'impacted' — fail-closed rather than scoping "
                    "off an empty diff" % degrade)
            scope = "full"
            derived_note = ("%s, so the DERIVED 'impacted' default degraded to 'full' "
                            "rather than halting the run" % degrade)

    # v3.4.1: the referencing set only matters where an unmapped path could resolve to
    # it — `impacted` at SCOPED/DIRECT. Computing it anywhere else would be a filesystem
    # walk whose result nothing reads.
    referencing = None
    if scope == "impacted" and str(tier or "").strip().upper() in ("SCOPED", "DIRECT"):
        referencing = referencing_tests(
            worktree, list(changed_paths or []) + list(new_paths or []))

    if no_prior_run:
        failures, available = [], True      # empty BY CONSTRUCTION — nothing has run
    elif last_result is None:
        failures, available = None, False   # undeclared ⇒ uncomputable ⇒ full fallback
    else:
        failures, available = previously_failing(last_result)
    resolved, notes = resolve_test_commands(contract, scope, changed_paths, new_paths,
                                           failures, available, tier=tier,
                                           referencing=referencing, worktree=worktree)
    if derived_note:
        notes = ["scope: no test_scope declared, defaulted to %r — %s"
                 % (scope, derived_note)] + list(notes)
    return resolved, notes


# --------------------------------------------------------------------------- #
# The test floor (concrete ladder).
# --------------------------------------------------------------------------- #
def run_test_floor(worktree, baseline="HEAD", changed_paths=None, test_cmd=None,
                   checkers=None, test_timeout_s=TEST_TIMEOUT_S, test_commands=None):
    """Run the proportionate fast-path test floor as a concrete ladder.

    tier-1 configured project tests (``test_commands`` / ``test_cmd``) → tier-2 guarded
    language parse-checks → tier-3 one cheap diff-read. Returns a result dict::

        {"phase":"test_floor", "tier_used":1|2|3|0, "passed":bool, "merge_blocked":bool,
         "changed_paths":[...]|None, "checks":[...], "reasons":[...]}

    ``merge_blocked`` is True on any floor FAILURE (Iron-Invariant #6). A tier is only
    "used" when it actually produced a verdict; an empty/unavailable tier falls through.

    ``test_commands`` is the ORDERED, already-resolved list from ``resolve_test_commands``
    (the floor first). ``test_cmd`` remains the single-command form. Both are executed at
    tier-1; no command is short-circuited, so the recorded failures are complete.

    THE FLOOR IS EARLY FEEDBACK, NOT A GUARANTEE. Passing here does not restore what the
    full suite guaranteed — the merge-blocking CI run does. See the resolver's header."""
    if checkers is None:
        checkers = _default_checkers()
    changed_paths = list(changed_paths) if changed_paths is not None else None
    result = {"phase": "test_floor", "tier_used": 0, "passed": False,
              "merge_blocked": True, "checks": [], "reasons": []}

    # --- The diff comes FIRST. ---------------------------------------------------------
    # This derivation used to sit BELOW the tier-1 return, so on the one path where a
    # project actually HAS configured tests the floor knew nothing about what changed and
    # could not be proportionate to the diff at all. It is computed before any tier runs.
    # An underivable diff is only fatal for the tiers that NEED it (2 and 3): a tier-1 set
    # that the caller already resolved is executed regardless, and the loss of
    # proportionality is recorded rather than swallowed.
    if changed_paths is None:
        changed_paths = _changed_from_scope(worktree, baseline)
    result["changed_paths"] = list(changed_paths) if changed_paths is not None else None

    # tier-1: the resolved project test set.
    resolved = list(test_commands) if test_commands else ([test_cmd] if test_cmd else [])
    if resolved:
        result["tier_used"] = 1
        if changed_paths is None:
            result["reasons"].append(
                "tier-1: changed paths underivable (scope-check unavailable) — the "
                "resolved set still runs, but this floor is NOT diff-proportionate")
        # Keep the ORIGINAL string beside the argv. `" ".join(shlex.split(x))` is
        # lossy — `sh -c "exit 0"` comes back as `sh -c exit 0`, which is a
        # different command. That matters beyond cosmetics: B2 computes the next
        # run's "previously failing" set from these strings, so a recorded command
        # that cannot be re-run silently drops coverage instead of restoring it.
        argvs = []
        for raw in resolved:
            cmd = shlex.split(raw) if isinstance(raw, str) else list(raw)
            if not cmd:
                result["reasons"].append(
                    "tier-1: configured test command is empty (fail-closed)")
                return result
            spelling = raw if isinstance(raw, str) else " ".join(
                shlex.quote(part) for part in cmd)
            argvs.append((cmd, spelling))
        failed_cmds = []
        for cmd, spelling in argvs:
            rc, _ = _run_supervised(cmd, worktree, test_timeout_s)
            result["checks"].append({"tier": 1, "checker": spelling, "rc": rc,
                                     "status": "pass" if rc == 0 else "fail"})
            if rc != 0:
                failed_cmds.append((spelling, rc))
        if not failed_cmds:
            result["passed"] = True
            result["merge_blocked"] = False
        else:
            for name, rc in failed_cmds:
                result["reasons"].append(
                    "tier-1: configured tests failed (rc=%s%s): %s"
                    % (rc, "; timeout" if rc == 124 else "", name))
        # rc==124 is the supervisor's own timeout signal (never a checker's own exit
        # code — see `_run_supervised`). The identifier gets a distinct label because
        # "sh -c 'sleep 2'" alone does not say WHY it failed, and this is the only
        # field the review gate / the next run's previously-failing set ever reads.
        # `failure_class` is a different, backend-level classification (job-level,
        # produced by compound-v-classify-failure.py) and is untouched here.
        result["failures"] = [
            ("timeout after %s s: %s" % (int(test_timeout_s), name)) if rc == 124
            else name
            for name, rc in failed_cmds]
        return result

    # Tiers 2 and 3 cannot work without the diff (soft; fail-closed if underivable).
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
# minus the derived `digest`). worktree + reviewer_tier are now MANDATORY (MED-6): the
# post-review validator compares receipt.worktree to the diff-root, so an unseal-able receipt
# without them fails CLOSED here rather than being written and rejected downstream.
_RECEIPT_REQUIRED = (
    "run_id", "pre_eval_id", "manifest_digest", "baseline_sha", "final_diff_digest",
    "reviewer_backend", "reviewer_tier", "reviewer_model", "worktree", "attempt_id", "ts",
    "verdict", "integration_rationale",
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

    # Diff-root signal for the validator's diff recompute — the worktree the producer hashed
    # the final_diff_digest against (from the trusted spec, never a reviewer-echoed field).
    # ALWAYS emitted (MED-6): if the spec carries no worktree, it is left blank so the
    # required-field check below refuses to seal (fail-closed) rather than writing a receipt
    # the validator's worktree/diff-root binding could not verify.
    wt = spec.get("worktree") if isinstance(spec, dict) else None
    receipt = {
        "run_id": rf.get("run_id"),
        "pre_eval_id": rf.get("pre_eval_id"),
        "manifest_digest": rf.get("manifest_digest"),
        "baseline_sha": rf.get("baseline_sha"),
        "final_diff_digest": rf.get("final_diff_digest"),
        "reviewer_backend": "claude",
        "reviewer_tier": rf.get("reviewer_tier") or "deep",
        "reviewer_model": rf.get("reviewer_model"),
        "worktree": str(wt) if wt else "",
        "attempt_id": rf.get("attempt_id"),
        "ts": ts or _now_iso_utc(),
        "verdict": "approved",
        "integration_rationale": rf.get("integration_rationale")
        or VACUOUS_INTEGRATION_RATIONALE,
    }
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
    ``<run_dir>/review/receipt.json``, else None (no destination supplied). ``accept-review``
    REQUIRES a destination (HIGH-3) so this returns None only when the caller passed neither."""
    if receipt_out:
        return receipt_out
    if run_dir:
        return os.path.join(run_dir, RECEIPT_SUBPATH)
    return None


def _invalidate_receipt(dest):
    """Remove any existing receipt at ``dest`` BEFORE a (re-)review attempt, so a rejected /
    timed-out re-review can never leave a stale prior-approved receipt usable (CR5-6/HIGH-4).
    Idempotent: a missing receipt is a no-op. Returns True iff the destination is clear
    afterwards (removed or already absent); False only if a receipt SURVIVES removal — the
    caller MUST then fail closed rather than risk a stale receipt validating against an
    unchanged diff."""
    if not dest:
        return True
    try:
        if os.path.isfile(dest):
            os.unlink(dest)
    except OSError:
        pass
    return not os.path.isfile(dest)


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


_VALIDATOR_CACHE = []


def _load_manifest(path):
    """Parse a manifest.yaml through the VALIDATOR's own loader (PyYAML when present, its
    ``_mini_yaml`` block fallback otherwise) so this script and the gate never disagree
    about what a manifest says."""
    if not _VALIDATOR_CACHE:
        import importlib.util
        vp = os.path.join(_script_dir(), "compound-v-validate-manifest.py")
        spec = importlib.util.spec_from_file_location("compound_v_validate_manifest", vp)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _VALIDATOR_CACHE.append(mod)
    with open(path, "r", encoding="utf-8") as fh:
        return _VALIDATOR_CACHE[0].load_yaml(fh.read())


def _resolve_args(args):
    """Shared producer for the resolved test slice. Returns ``(slice, notes)`` or raises
    ``TestContractError``. This is the producer ``--test-cmd`` never had."""
    manifest = _load_manifest(args.manifest)
    last_result = None
    if getattr(args, "last_result", None):
        last_result = _read_json(args.last_result)
    if not getattr(args, "no_prior_run", False) and last_result is None:
        # Refuse to guess. Silence here would quietly drop the previously-failing set,
        # which is exactly the degradation B2 calls out by name.
        raise TestContractError(
            "the previously-failing set is undeclared: pass --last-result <job_result.json> "
            "(the last recorded run) or --no-prior-run (nothing has run yet). Without one "
            "of them the set is uncomputable and the floor falls back to full_command")
    changed = None
    if getattr(args, "changed_file", None):
        with open(args.changed_file, "r", encoding="utf-8") as fh:
            changed = [ln.strip() for ln in fh if ln.strip()]
    return resolve_from_manifest(
        manifest, job_id=getattr(args, "job_id", None), scope=getattr(args, "scope", None),
        worktree=args.worktree, baseline=args.baseline, changed_paths=changed,
        last_result=last_result, no_prior_run=getattr(args, "no_prior_run", False))


def _cmd_resolve_tests(args):
    """Emit the resolved test-contract slice — the file every worker takes as
    ``--test-contract-file``, and the same list ``test-floor`` executes at tier-1."""
    if not args.manifest:
        sys.stderr.write("REFUSED: resolve-tests needs --manifest (the declared "
                         "test_contract is the only producer there is)\n")
        return 2
    try:
        slice_, notes = _resolve_args(args)
    except TestContractError as e:
        sys.stderr.write("REFUSED (fail-closed): %s\n" % e)
        return 2
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(slice_, indent=2) + "\n")
    print(json.dumps({"contract": slice_, "notes": notes}, indent=2))
    return 0


def _cmd_test_floor(args):
    changed = None
    if args.changed_file:
        with open(args.changed_file, "r", encoding="utf-8") as fh:
            changed = [ln.strip() for ln in fh if ln.strip()]

    # --test-cmd's PRODUCER (v3.0 Feature B1): --manifest resolves the declared
    # test_contract + this job's test_scope into the ordered command set. --test-cmd stays
    # for the one-off/explicit case and, when both are given, wins — an operator typing an
    # explicit command should not be silently overruled by a declaration.
    test_commands = None
    notes = []
    slice_ = {}
    if args.manifest and not args.test_cmd:
        try:
            slice_, notes = _resolve_args(args)
        except TestContractError as e:
            _emit({"phase": "test_floor", "tier_used": 0, "passed": False,
                   "merge_blocked": True, "checks": [],
                   "reasons": ["test contract did not resolve (fail-closed): %s" % e]},
                  args.out)
            return 1
        test_commands = slice_["resolved_commands"]

    res = run_test_floor(args.worktree, args.baseline, changed, args.test_cmd,
                         test_commands=test_commands,
                         test_timeout_s=slice_.get("timeout_s", TEST_TIMEOUT_S))
    if notes:
        res["contract_notes"] = notes
    _emit(res, args.out)
    return 0 if res.get("passed") and not res.get("merge_blocked") else 1


def _cmd_review_spec(args):
    floor = _read_json(args.floor_result)
    f2 = _read_json(args.f2_result)
    changed = []
    if args.changed_file:
        with open(args.changed_file, "r", encoding="utf-8") as fh:
            changed = [ln.strip() for ln in fh if ln.strip()]
    elif isinstance(floor, dict) and isinstance(floor.get("changed_paths"), list):
        # v3.0: prefer the floor's own recorded diff. Tier-1 checks carry a command, not a
        # file, so scraping `checks` returned an EMPTY changed list on exactly the path the
        # producer has now made reachable for the first time.
        changed = list(floor["changed_paths"])
    elif isinstance(floor, dict):
        changed = [c.get("file") for c in floor.get("checks", [])
                   if c.get("file") and not str(c.get("file", "")).startswith("<")]
    spec = build_review_spec(
        args.run_id, args.pre_eval_id, args.worktree, args.baseline, args.manifest,
        changed, floor, args.scope_clean, f2, attempt_id=args.attempt_id, ts=args.ts)
    _emit(spec, args.out)
    return 0 if spec.get("kind") == "needs_review" else 1


def _cmd_accept_review(args):
    run_dir = getattr(args, "run_dir", None)
    receipt_out = getattr(args, "receipt_out", None)

    # HIGH-3: acceptance MUST ALWAYS produce a sealed receipt at a known path — require
    # EXACTLY ONE destination. Refuse (nonzero, NO acceptance, NO receipt) when neither is
    # given (the bug: accept-review used to 'succeed' without ever sealing) or when both are
    # given (ambiguous). We refuse BEFORE reading/accepting anything so no acceptance leaks out.
    if bool(run_dir) == bool(receipt_out):
        problem = ("no receipt destination: accept-review requires exactly one of --run-dir "
                   "or --receipt-out so acceptance always seals a receipt (fail-closed)"
                   if not run_dir else
                   "ambiguous receipt destination: pass exactly one of --run-dir or "
                   "--receipt-out, not both")
        refusal = {"accepted": False, "merge_ok": False,
                   "failure_modes": ["no_receipt_destination"], "reasons": [problem],
                   "verdict": None, "receipt_path": None}
        _emit(refusal, args.out)
        return 1

    dest = _receipt_dest(run_dir, receipt_out)

    # HIGH-4 (a): invalidate ANY existing receipt at the destination BEFORE this attempt, so a
    # rejected / timed-out / wrong-tier re-review can never leave a stale prior-approved receipt
    # behind (it would otherwise still validate against an unchanged diff). If a receipt cannot
    # be removed, fail CLOSED rather than risk replaying it.
    if not _invalidate_receipt(dest):
        refusal = {"accepted": False, "merge_ok": False,
                   "failure_modes": ["receipt_invalidation_failed"],
                   "reasons": ["could not invalidate the prior receipt at %s before re-review "
                               "— fail-closed" % dest],
                   "verdict": None, "receipt_path": None}
        _emit(refusal, args.out)
        return 1

    spec = _read_json(args.spec)

    # HIGH-1: bind acceptance to the EXPLICIT attempt the caller declares. The spec
    # (produced by review-spec --attempt-id N) carries the attempt this review request
    # was built for; a mismatch means the caller is accepting a review from a DIFFERENT
    # attempt than it believes — refuse to seal a mis-attributed receipt (fail-closed).
    # We only reach here after the pre-attempt invalidation cleared any stale receipt,
    # so a refusal leaves NO receipt behind.
    if str(spec.get("attempt_id")) != str(args.attempt_id):
        refusal = {"accepted": False, "merge_ok": False,
                   "failure_modes": ["attempt_mismatch"],
                   "reasons": ["accept-review --attempt-id %r != the review spec's "
                               "attempt_id %r — refusing to seal a mis-attributed "
                               "receipt (fail-closed, HIGH-1)"
                               % (args.attempt_id, spec.get("attempt_id"))],
                   "verdict": None, "receipt_path": None}
        _emit(refusal, args.out)
        return 1

    result = _read_json(args.result)
    out = accept_review(spec, result)
    out["receipt_path"] = None
    # Seal + write the receipt ONLY after acceptance succeeds. A rejected / timed-out /
    # wrong-tier / malformed result writes NO receipt — and the pre-attempt invalidation above
    # guarantees no earlier receipt survives either (fail-closed).
    if out.get("accepted") and out.get("merge_ok"):
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


def _cmd_invalidate_receipt(args):
    """Standalone receipt invalidation the DISPATCHER runs BEFORE dispatching a
    (re-)review (HIGH-1). It closes the crash-between-review-and-accept window: if the
    harness dies AFTER the review Task runs but BEFORE accept-review seals, no stale
    prior-attempt receipt survives into the review window. Idempotent (a missing
    receipt is a clean no-op). Fail-closed: exits non-zero if a receipt survives
    removal."""
    run_dir = getattr(args, "run_dir", None)
    receipt_out = getattr(args, "receipt_out", None)
    if bool(run_dir) == bool(receipt_out):
        problem = ("invalidate-receipt requires exactly one of --run-dir or "
                   "--receipt-out" if not run_dir else
                   "ambiguous: pass exactly one of --run-dir or --receipt-out, not both")
        _emit({"invalidated": False, "receipt_path": None, "reasons": [problem]}, args.out)
        return 2
    dest = _receipt_dest(run_dir, receipt_out)
    ok = _invalidate_receipt(dest)
    _emit({"invalidated": bool(ok), "receipt_path": dest,
           "reasons": [] if ok else
           ["a receipt survived removal at %s — fail-closed" % dest]}, args.out)
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv[1:]:
        return _selftest()
    ap = argparse.ArgumentParser(prog="compound-v-fastpath-run.py")
    sub = ap.add_subparsers(dest="phase")

    def _contract_flags(p):
        p.add_argument("--manifest", help="manifest.yaml carrying the v3.0 `test_contract` "
                                          "block — THE PRODUCER for the test command set")
        p.add_argument("--job-id", dest="job_id",
                       help="job whose `test_scope` to honour (absent test_scope ⇒ full)")
        p.add_argument("--scope", choices=list(VALID_TEST_SCOPES),
                       help="explicit test_scope override; wins over the job's")
        p.add_argument("--last-result", dest="last_result",
                       help="the LAST recorded job_result.json; its tests.failures[] is "
                            "the previously-failing set. Absent tests.failures[] ⇒ the "
                            "floor falls back to full_command, never to dropping the set")
        p.add_argument("--no-prior-run", dest="no_prior_run", action="store_true",
                       help="assert that NO prior run was recorded, so the "
                            "previously-failing set is empty by construction. Required "
                            "when --last-result is absent: silence must not become "
                            "'nothing was failing'")

    p1 = sub.add_parser("test-floor")
    p1.add_argument("--worktree", required=True)
    p1.add_argument("--baseline", default="HEAD")
    p1.add_argument("--changed-file")
    p1.add_argument("--test-cmd")
    _contract_flags(p1)
    p1.add_argument("--out")
    p1.set_defaults(func=_cmd_test_floor)

    p1b = sub.add_parser("resolve-tests",
                         help="resolve test_contract + test_scope into the ordered "
                              "command set (the worker's --test-contract-file)")
    p1b.add_argument("--worktree", required=True)
    p1b.add_argument("--baseline", default="HEAD")
    p1b.add_argument("--changed-file")
    _contract_flags(p1b)
    p1b.add_argument("--out", help="write the slice (and ONLY the slice) here")
    p1b.set_defaults(func=_cmd_resolve_tests)

    p2 = sub.add_parser("review-spec")
    p2.add_argument("--worktree", required=True)
    p2.add_argument("--baseline", required=True)
    p2.add_argument("--manifest", required=True)
    p2.add_argument("--run-id", required=True)
    p2.add_argument("--pre-eval-id", required=True)
    p2.add_argument("--attempt-id", type=int, required=True,
                    help="EXPLICIT, monotonic review attempt number (HIGH-1): the "
                         "caller increments it per review attempt. No silent default "
                         "to 1 — a re-review MUST pass the incremented attempt so the "
                         "sealed receipt records the CURRENT attempt, and a stale "
                         "prior-attempt receipt cannot be replayed.")
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
                         "<run-dir>/review/receipt.json on acceptance. REQUIRED unless "
                         "--receipt-out is given (exactly one destination)")
    p3.add_argument("--receipt-out", dest="receipt_out",
                    help="explicit receipt path; use INSTEAD of --run-dir (exactly one "
                         "destination is required so acceptance always seals a receipt)")
    p3.add_argument("--attempt-id", type=int, required=True,
                    help="EXPLICIT review attempt this acceptance is for (HIGH-1). MUST "
                         "equal the review spec's attempt_id (built by review-spec "
                         "--attempt-id N); a mismatch means the caller is accepting a "
                         "review from a DIFFERENT attempt and is refused (fail-closed).")
    p3.add_argument("--ts", help="override the receipt seal timestamp (ISO-8601); "
                                 "defaults to now (UTC)")
    p3.add_argument("--out")
    p3.set_defaults(func=_cmd_accept_review)

    # Standalone receipt invalidation — the dispatcher calls this BEFORE dispatching a
    # (re-)review, closing the crash-between-review-and-accept window (HIGH-1): no stale
    # prior-attempt receipt can survive into the review window.
    p4 = sub.add_parser("invalidate-receipt")
    p4.add_argument("--run-dir", dest="run_dir",
                    help="run directory; removes <run-dir>/review/receipt.json. Pass "
                         "exactly one of --run-dir or --receipt-out.")
    p4.add_argument("--receipt-out", dest="receipt_out",
                    help="explicit receipt path to remove; use INSTEAD of --run-dir.")
    p4.add_argument("--out")
    p4.set_defaults(func=_cmd_invalidate_receipt)

    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv[1:])
    if not getattr(args, "func", None):
        ap.error("a phase is required: test-floor | review-spec | accept-review | "
                 "invalidate-receipt (or --selftest)")
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

        # ---- v3.0 Feature B1/B2: the producer, the three sets, the moved return ----
        CONTRACT = {
            "floor_command": "sh -c 'exit 0'",
            "full_command": "sh -c 'echo full'",
            "impacted_map": [
                {"when": "scripts/compound-v-*.py", "run": "python3 {path} --selftest"},
                {"when": "scripts/**", "run": "sh -c 'lint scripts'"},
                {"when": "docs/**", "run": "sh -c 'docs check'"},
            ],
        }

        def cmds(scope, changed=None, new=None, failing=None, available=True,
                 contract=CONTRACT):
            slice_, _notes = resolve_test_commands(contract, scope, changed, new,
                                                   failing, available)
            return slice_["resolved_commands"]

        # B2: the floor always runs, at every tier, and comes FIRST.
        expect("B2: floor_command is first in every resolved set",
               cmds("full")[0] == "sh -c 'exit 0'"
               and cmds("floor_only")[0] == "sh -c 'exit 0'"
               and cmds("impacted", ["docs/x.md"], [], [], True)[0] == "sh -c 'exit 0'")
        expect("B2: floor_only resolves to ONLY the floor",
               cmds("floor_only") == ["sh -c 'exit 0'"])
        expect("B2: full resolves to floor + full_command",
               cmds("full") == ["sh -c 'exit 0'", "sh -c 'echo full'"])

        # B2: a scope must NEVER resolve to nothing.
        def _raises(fn):
            try:
                fn()
            except TestContractError:
                return True
            return False
        expect("B2: floor_only with no floor_command is REFUSED (never nothing)",
               _raises(lambda: cmds("floor_only", contract={"full_command": "x"})))
        expect("B2: impacted with no full_command is REFUSED (the fallback is mandatory)",
               _raises(lambda: cmds("impacted", ["a.py"], [], [], True,
                                    contract={"floor_command": "f"})))
        expect("B2: an entirely empty contract is REFUSED, not silently green",
               _raises(lambda: cmds("full", contract={})))
        expect("B2: a half-declared impacted_map rule is REFUSED",
               _raises(lambda: cmds("impacted", ["scripts/x.py"], [], [], True,
                                    contract={"floor_command": "f", "full_command": "F",
                                              "impacted_map": [{"when": "scripts/**"}]})))

        # B2: EVERY matching rule unions — first-match-wins would drop declared coverage.
        both = cmds("impacted", ["scripts/compound-v-preeval.py"], [], [], True)
        expect("B2: overlapping `when` globs UNION (both matching rules selected)",
               "python3 scripts/compound-v-preeval.py --selftest" in both
               and "sh -c 'lint scripts'" in both)
        expect("B2: `{path}` is substituted with the matching path",
               "python3 scripts/compound-v-preeval.py --selftest" in both)
        expect("B2: a fully-mapped impacted set does NOT drag in full_command",
               "sh -c 'echo full'" not in both)

        # B2: an unmapped path is unknown blast radius → full_command, never nothing.
        un = cmds("impacted", ["src/parser.py"], [], [], True)
        expect("B2: an unmapped changed path resolves to full_command",
               "sh -c 'echo full'" in un)

        # findings 102/105: docs/superpowers/execution/** bookkeeping paths never
        # trigger the unmapped⇒full_command promotion on their own — 1 REAL mapped
        # path + 3 bookkeeping paths stays `impacted`, never `full`.
        BK_CONTRACT = {"floor_command": "sh -c 'exit 0'",
                       "full_command": "sh -c 'echo full'",
                       "impacted_map": [{"when": "scripts/**",
                                        "run": "sh -c 'lint scripts'"}]}
        bk_changed = ["scripts/a.py",
                      "docs/superpowers/execution/x/jobs/a/.run.lock",
                      "docs/superpowers/execution/x/jobs/b/.run.lock",
                      "docs/superpowers/execution/x/jobs/c/.run.lock"]
        s_bk, n_bk = resolve_test_commands(BK_CONTRACT, "impacted", bk_changed,
                                           [], [], True)
        expect("105: docs/superpowers/execution/** bookkeeping paths never promote "
               "to full",
               s_bk["scope"] == "impacted"
               and "sh -c 'echo full'" not in s_bk["resolved_commands"])
        expect("105: the mapped path's own command still ran",
               "sh -c 'lint scripts'" in s_bk["resolved_commands"])
        expect("105: the contract note records how many bookkeeping paths were "
               "ignored, in the pinned words",
               any("ignored 3 bookkeeping path(s) for the unmapped rule" in n
                   for n in n_bk))

        # A REAL unmapped path beside bookkeeping noise still promotes — the
        # exclusion only removes the bookkeeping paths from the decision, it does
        # not blanket-suppress the rule.
        s_bk2, _ = resolve_test_commands(
            BK_CONTRACT, "impacted",
            bk_changed + ["src/real_unmapped.py"], [], [], True)
        expect("105: a genuine unmapped path alongside bookkeeping noise still "
               "promotes to full",
               s_bk2["scope"] == "full"
               and "sh -c 'echo full'" in s_bk2["resolved_commands"])

        # B1/102: timeout_s on the contract is copied into the slice verbatim;
        # absent ⇒ absent (the worker default, TEST_TIMEOUT_S, applies downstream).
        s_notimeout, _ = resolve_test_commands(CONTRACT, "floor_only")
        expect("102: no test_contract.timeout_s ⇒ no timeout_s in the slice",
               "timeout_s" not in s_notimeout)
        TIMED_CONTRACT = dict(CONTRACT, timeout_s=45)
        s_timed, _ = resolve_test_commands(TIMED_CONTRACT, "floor_only")
        expect("102: test_contract.timeout_s is copied into the slice verbatim",
               s_timed.get("timeout_s") == 45)
        expect("102: a bool timeout_s is REFUSED (true is not 1)",
               _raises(lambda: resolve_test_commands(
                   dict(CONTRACT, timeout_s=True), "floor_only")))
        expect("102: a non-positive timeout_s is REFUSED",
               _raises(lambda: resolve_test_commands(
                   dict(CONTRACT, timeout_s=0), "floor_only")))

        # ---- v3.4.1 decision 4: what a SCOPED job owes ----
        REF = [{"file": "tests/test_parser.py", "run": "python3 tests/test_parser.py"},
               {"file": "tests/parser_notes.md", "run": None}]

        def sl(tier=None, referencing=None, changed=None):
            slice_, notes = resolve_test_commands(
                CONTRACT, "impacted", changed or ["src/parser.py"], [], [], True,
                tier=tier, referencing=referencing)
            return slice_, notes

        s_full, _ = sl(tier="FULL", referencing=REF)
        s_unc, _ = resolve_test_commands(CONTRACT, "impacted", ["src/parser.py"], [], None, False,
                                         tier="SCOPED", referencing=REF)
        expect("review-2 finding 4: an uncomputable previously-failing set at SCOPED adds "
               "full_command AND labels the slice `full` (never `impacted+referencing` beside it)",
               "sh -c 'echo full'" in s_unc["resolved_commands"] and s_unc["scope"] == "full"
               and "selected_count" not in s_unc)
        expect("C: at tier FULL an unmapped path still resolves to full_command, "
               "and the label says `full` (review-1 issue 4)",
               "sh -c 'echo full'" in s_full["resolved_commands"]
               and s_full["scope"] == "full"
               and "selected_count" not in s_full)
        s_none, _ = sl(tier=None, referencing=REF)
        expect("C: with NO tier the unmapped rule is unchanged (full_command)",
               "sh -c 'echo full'" in s_none["resolved_commands"])

        s_sc, n_sc = sl(tier="SCOPED", referencing=REF)
        expect("C: at tier SCOPED an unmapped path resolves to the referencing test, "
               "NOT full_command",
               s_sc["resolved_commands"] == ["sh -c 'exit 0'",
                                             "python3 tests/test_parser.py"])
        expect("C: the slice is labelled impacted+referencing and counts its commands",
               s_sc["scope"] == "impacted+referencing" and s_sc["selected_count"] == 2)
        expect("C: a referencing file with no known runner is REPORTED, never run",
               any("REPORTED and not run" in n for n in n_sc)
               and not any("parser_notes.md" in c for c in s_sc["resolved_commands"]))
        s_dir, _ = sl(tier="DIRECT", referencing=REF)
        expect("C: DIRECT behaves exactly as SCOPED",
               s_dir["resolved_commands"] == s_sc["resolved_commands"]
               and s_dir["scope"] == "impacted+referencing")

        s_bare, n_bare = sl(tier="SCOPED", referencing=[])
        expect("C: no referencing test at SCOPED ⇒ the floor only, never full_command",
               s_bare["resolved_commands"] == ["sh -c 'exit 0'"]
               and "sh -c 'echo full'" not in s_bare["resolved_commands"])
        expect("C: and the note says so, in the pinned words",
               any("referencing tests found none — floor only at tier SCOPED" in n
                   for n in n_bare))
        expect("C: a floor-only referencing result keeps the plain `impacted` label",
               s_bare["scope"] == "impacted" and "selected_count" not in s_bare)

        # The cap is the caller's (referencing_tests) AND is honoured verbatim here:
        # whatever the caller hands over is what runs, so seven rows never become seven
        # commands by accident — referencing_tests already capped them at five.
        seven = [{"file": "tests/t%d_test.py" % i, "run": "python3 tests/t%d_test.py" % i}
                 for i in range(7)]
        expect("C: the resolver runs exactly what it is handed (the cap lives in "
               "referencing_tests, which is where the reading happens)",
               len(sl(tier="SCOPED", referencing=seven)[0]["resolved_commands"]) == 8)

        # An UNCOMPUTABLE previously-failing set is a data failure, not a size decision:
        # it still falls back to full_command at SCOPED.
        s_unc, _ = resolve_test_commands(CONTRACT, "impacted", ["src/parser.py"], [],
                                         None, False, tier="SCOPED", referencing=REF)
        expect("C: an uncomputable previously-failing set still reaches full_command at "
               "SCOPED (fail-closed on DATA, not on size)",
               "sh -c 'echo full'" in s_unc["resolved_commands"])

        # referencing_tests() itself, against a REAL tree.
        r = new_repo("referencing")
        write(r, "src/parser.py", "def parse():\n    return 1\n")
        write(r, "tests/test_parser.py", "import parser  # exercises src/parser.py\n")
        write(r, "tests/test_unrelated.py", "x = 1\n")
        write(r, "tests/smoke_test.sh", "# checks parser.py end to end\n")
        write(r, "tests/notes.txt", "parser.py is described here\n")
        write(r, "docs/parser.md", "parser.py — not a test file\n")
        git(r, ["add", "-A"]); git(r, ["commit", "-qm", "seed"])
        rows = referencing_tests(r, ["src/parser.py"])
        files = [row["file"] for row in rows]
        expect("C: referencing_tests finds the tests that NAME the changed module",
               "tests/test_parser.py" in files and "tests/smoke_test.sh" in files)
        expect("C: a test that never names it is not selected",
               "tests/test_unrelated.py" not in files)
        expect("C: a non-test file that names it is not selected (docs/parser.md)",
               "docs/parser.md" not in files)
        expect("C: language-agnostic runners — bash for .sh, python3 for .py, None else",
               {row["file"]: row["run"] for row in rows}["tests/smoke_test.sh"]
               == "bash tests/smoke_test.sh"
               and {row["file"]: row["run"] for row in rows}["tests/test_parser.py"]
               == "python3 tests/test_parser.py"
               and {row["file"]: row["run"] for row in rows}.get("tests/notes.txt", "x")
               is None)
        expect("C: the result is sorted by path (a deterministic set, not FS order)",
               files == sorted(files))
        expect("C: a changed path never selects itself",
               "tests/test_parser.py" not in
               [row["file"] for row in referencing_tests(r, ["tests/test_parser.py"])])

        # The cap: seven candidates, five run.
        r2 = new_repo("referencing-cap")
        write(r2, "src/widget.py", "x = 1\n")
        for i in range(7):
            write(r2, "tests/test_w%d.py" % i, "# widget.py and zz\n")
        git(r2, ["add", "-A"]); git(r2, ["commit", "-qm", "seed"])
        expect("C: referencing_tests caps at 5 (and the cap is a parameter)",
               len(referencing_tests(r2, ["src/widget.py"])) == 5
               and len(referencing_tests(r2, ["src/widget.py"], cap=2)) == 2)
        expect("C: a 1-2 character token selects NOTHING even though every candidate "
               "contains it (it would otherwise select the whole repository)",
               referencing_tests(r2, ["zz"]) == [])

        # B2 set 2 — previously failing.
        pf = cmds("impacted", ["docs/a.md"], [], ["pytest tests/test_x.py::test_y"], True)
        expect("B2: previously-failing commands are unioned into the set",
               "pytest tests/test_x.py::test_y" in pf)
        drop = cmds("impacted", ["docs/a.md"], [], None, False)
        expect("B2: an UNCOMPUTABLE previously-failing set falls back to full_command "
               "(never silently dropped)", "sh -c 'echo full'" in drop)
        _slice, _notes = resolve_test_commands(CONTRACT, "impacted", ["docs/a.md"], [],
                                               None, False)
        expect("B2: the fallback states its reason in the notes",
               any("UNCOMPUTABLE" in n for n in _notes))

        # B2 set 3 — newly added, run through the SAME map.
        na = cmds("impacted", ["docs/a.md"], ["scripts/compound-v-new.py"], [], True)
        expect("B2: a newly-added path is mapped like a changed one",
               "python3 scripts/compound-v-new.py --selftest" in na)
        na2 = cmds("impacted", ["docs/a.md"], ["src/brand-new.py"], [], True)
        expect("B2: an unmapped NEWLY-ADDED path also resolves to full_command",
               "sh -c 'echo full'" in na2)

        # The union is deduped and order-stable (floor first).
        dd = cmds("impacted", ["scripts/a.py", "scripts/b.py"], [], [], True)
        expect("B2: the resolved set is deduped, order-stable, floor-first",
               dd[0] == "sh -c 'exit 0'" and len(dd) == len(set(dd))
               and dd.count("sh -c 'lint scripts'") == 1)

        # The slice carries ONLY the keys the worker's --test-contract-file accepts.
        slice_only, _ = resolve_test_commands(CONTRACT, "full")
        expect("B3: the slice holds only {scope, resolved_commands, floor_command, "
               "full_command} (+ selected_count, 3.4.1, only when the referencing "
               "heuristic contributed)",
               set(slice_only) <= {"scope", "resolved_commands", "floor_command",
                                   "full_command"}
               and slice_only["scope"] == "full"
               and set(s_sc) <= {"scope", "resolved_commands", "floor_command",
                                 "full_command", "selected_count"})

        # previously_failing() — the three honest answers.
        expect("B3: no prior run ⇒ empty BY CONSTRUCTION (not unknown)",
               previously_failing(None) == ([], True))
        expect("B3: a measured empty failures[] ⇒ measured-and-nothing-failed",
               previously_failing({"tests": {"failures": []}}) == ([], True))
        expect("B3: measured failures[] are returned verbatim",
               previously_failing({"tests": {"failures": ["cmd a"]}}) == (["cmd a"], True))
        expect("B3: an ABSENT tests block ⇒ uncomputable (full fallback)",
               previously_failing({"status": "success"}) == (None, False))
        expect("B3: a tests block with NO failures field ⇒ uncomputable",
               previously_failing({"tests": {"command": "x", "exit_code": 0}})
               == (None, False))

        # B1: newly-added derivation, against a REAL repo.
        r = new_repo("added")
        write(r, "keep.md", "hi\n"); git(r, ["add", "-A"]); git(r, ["commit", "-qm", "b"])
        base = head(r)
        write(r, "brand/new.py", "x = 1\n")
        git(r, ["add", "-A"]); git(r, ["commit", "-qm", "add"])
        expect("B1: added_paths() reports the newly-added file (--diff-filter=A)",
               added_paths(r, base) == ["brand/new.py"])
        expect("B1: added_paths() does NOT report a merely modified file",
               "keep.md" not in (added_paths(r, base) or []))

        # B1: the moved return — tier-1 is now diff-proportionate at all.
        r = new_repo("t1-diff")
        write(r, "a.py", "x = 1\n"); git(r, ["add", "-A"]); git(r, ["commit", "-qm", "b"])
        base = head(r)
        write(r, "a.py", "x = 2\n")
        res = run_test_floor(r, base, test_cmd="sh -c 'exit 0'")
        expect("B1: tier-1 now reports changed_paths (the return moved BELOW the diff)",
               res["tier_used"] == 1 and res.get("changed_paths") == ["a.py"])

        # B1: the resolved set runs in order and is NOT short-circuited.
        marker = os.path.join(tmp, "second-ran")
        res = run_test_floor(r, base, changed_paths=["a.py"], test_commands=[
            "sh -c 'exit 1'", "sh -c 'touch %s'" % marker])
        expect("B1: a failing command in the set blocks the merge",
               res["merge_blocked"] is True and res["passed"] is False)
        expect("B1: later commands still RUN (no short-circuit ⇒ complete failures)",
               os.path.isfile(marker))
        # Recorded VERBATIM, not shlex-joined. B2 rebuilds the next run's
        # "previously failing" set from these strings, so the test asserts the
        # property that matters — the recorded spelling re-parses to the argv
        # that actually ran — rather than a particular rendering of it.
        expect("B1: the failing command is recorded by name",
               res.get("failures") == ["sh -c 'exit 1'"])
        expect("B1: the recorded failure is re-runnable, not lossily joined",
               shlex.split(res.get("failures", [""])[0]) == ["sh", "-c", "exit 1"])
        res = run_test_floor(r, base, changed_paths=["a.py"],
                             test_commands=["sh -c 'exit 0'", "sh -c 'exit 0'"])
        expect("B1: an all-green resolved set passes the floor",
               res["passed"] is True and res["merge_blocked"] is False
               and len([c for c in res["checks"] if c.get("tier") == 1]) == 2)

        # findings 102/105: a checker that outlives its budget is the SUPERVISOR's
        # own 124, distinct from the checker's own exit code, and is recorded with a
        # `timeout after N s:` prefix — the only field the next run's
        # previously-failing set or a reviewer ever reads for "why did this fail".
        res = run_test_floor(r, base, changed_paths=["a.py"],
                             test_commands=["sh -c 'sleep 2'"], test_timeout_s=1)
        expect("102: a checker exceeding test_timeout_s exits 124",
               any(c.get("rc") == 124 for c in res["checks"] if c.get("tier") == 1))
        expect("102: rc==124 blocks the merge like any other tier-1 failure",
               res["merge_blocked"] is True and res["passed"] is False)
        expect("102: the failures[] entry is `timeout after N s: <checker>`, in the "
               "pinned words",
               res.get("failures") == ["timeout after 1 s: sh -c 'sleep 2'"])
        expect("102: a timeout never invents a failure_class key on this dict",
               "failure_class" not in res)

        # resolve_from_manifest: test_scope comes off the job; absent ⇒ full.
        man = {"test_contract": CONTRACT,
               "jobs": [{"id": "task-1", "test_scope": "floor_only"},
                        {"id": "task-2"}]}
        s1, _ = resolve_from_manifest(man, job_id="task-1", no_prior_run=True)
        expect("B2: a job's test_scope drives resolution",
               s1["scope"] == "floor_only" and s1["resolved_commands"] == ["sh -c 'exit 0'"])
        s2, _ = resolve_from_manifest(man, job_id="task-2", no_prior_run=True)
        expect("B2: an ABSENT test_scope is `full` (what every pre-3.0 manifest relies on)",
               s2["scope"] == "full")

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
                   "--attempt-id", "1",
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
        rc = main(["prog", "accept-review", "--attempt-id", "1", "--spec", spec_f, "--result", result_f,
                   "--run-dir", os.path.join(tmp, "run-cli15"),
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
        rc = main(["prog", "accept-review", "--attempt-id", "1", "--spec", spec_f, "--result", result_f,
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
        rc = main(["prog", "accept-review", "--attempt-id", "1", "--spec", spec_f, "--result", reject_f,
                   "--run-dir", run_dir2, "--out", os.path.join(tmp, "verdict3.json")])
        expect("CLI accept-review on a rejected result exits 1 and writes NO receipt",
               rc == 1 and not os.path.exists(
                   os.path.join(run_dir2, "review", "receipt.json")))

        # ---- ROUND-3: HIGH-3 destination-required, HIGH-4 invalidation, MED-6 schema ----
        # 21. HIGH-3: accept-review with NO destination REFUSES (nonzero, no acceptance) — the
        #     authoritative flow can no longer 'succeed' without ever sealing a receipt.
        nod_out = os.path.join(tmp, "verdict-nodest.json")
        rc = main(["prog", "accept-review", "--attempt-id", "1", "--spec", spec_f, "--result", result_f,
                   "--out", nod_out])
        nod = _read_json(nod_out)
        expect("HIGH-3: accept-review with NO destination refuses (exit 1)", rc == 1)
        expect("HIGH-3: no-destination refusal is NOT accepted / not merge_ok",
               nod.get("accepted") is False and nod.get("merge_ok") is False
               and "no_receipt_destination" in nod.get("failure_modes", []))

        # 21b. HIGH-3: BOTH destinations is ambiguous → also refuses (exactly one).
        both_a = os.path.join(tmp, "run-both")
        both_b = os.path.join(tmp, "receipt-both.json")
        rc = main(["prog", "accept-review", "--attempt-id", "1", "--spec", spec_f, "--result", result_f,
                   "--run-dir", both_a, "--receipt-out", both_b,
                   "--out", os.path.join(tmp, "verdict-both.json")])
        expect("HIGH-3: both destinations refuses (exit 1) and writes NO receipt",
               rc == 1 and not os.path.exists(both_b)
               and not os.path.exists(os.path.join(both_a, "review", "receipt.json")))

        # 22. HIGH-4: an existing receipt is INVALIDATED before a new attempt; a rejected
        #     re-review over a prior APPROVED receipt leaves NO valid receipt behind.
        run_re = os.path.join(tmp, "run-reattempt")
        receipt_path = os.path.join(run_re, "review", "receipt.json")
        rc = main(["prog", "accept-review", "--attempt-id", "1", "--spec", spec_f, "--result", result_f,
                   "--run-dir", run_re, "--out", os.path.join(tmp, "v-approve.json")])
        expect("HIGH-4: first approved attempt seals a receipt",
               rc == 0 and os.path.isfile(receipt_path))
        rc = main(["prog", "accept-review", "--attempt-id", "1", "--spec", spec_f, "--result", reject_f,
                   "--run-dir", run_re, "--out", os.path.join(tmp, "v-rereject.json")])
        expect("HIGH-4: rejected re-review invalidates the prior receipt — none survives",
               rc == 1 and not os.path.exists(receipt_path))

        # 22b. HIGH-4: a TIMED-OUT re-review over a prior approved receipt also leaves none.
        run_to = os.path.join(tmp, "run-timeout")
        to_path = os.path.join(run_to, "review", "receipt.json")
        rc = main(["prog", "accept-review", "--attempt-id", "1", "--spec", spec_f, "--result", result_f,
                   "--run-dir", run_to, "--out", os.path.join(tmp, "v-approve2.json")])
        timeout_f = os.path.join(tmp, "timeout.json")
        tr = _read_json(result_f); tr["status"] = "timeout"
        with open(timeout_f, "w") as fh:
            json.dump(tr, fh)
        rc = main(["prog", "accept-review", "--attempt-id", "1", "--spec", spec_f, "--result", timeout_f,
                   "--run-dir", run_to, "--out", os.path.join(tmp, "v-retimeout.json")])
        expect("HIGH-4: timed-out re-review leaves no valid receipt",
               rc == 1 and not os.path.exists(to_path))

        # 22c. _invalidate_receipt is idempotent: clears an existing file, no-op when absent.
        inv_f = os.path.join(tmp, "inv", "receipt.json")
        os.makedirs(os.path.dirname(inv_f))
        with open(inv_f, "w") as fh:
            fh.write("{}")
        expect("HIGH-4: _invalidate_receipt removes an existing receipt",
               _invalidate_receipt(inv_f) is True and not os.path.exists(inv_f))
        expect("HIGH-4: _invalidate_receipt on a missing path is a clean no-op",
               _invalidate_receipt(inv_f) is True)

        # 23. The sealed receipt ALWAYS carries worktree + reviewer_tier + attempt_id, and its
        #     self-digest verifies via the SHARED record_digest primitive.
        seal_accept = accept_review(spec, good_result())
        rcp3, _e3 = build_sealed_receipt(spec, seal_accept, ts="2026-07-12T00:00:00Z",
                                         tax=tax_mod)
        expect("sealed receipt always carries worktree + reviewer_tier(deep) + attempt_id",
               rcp3 is not None and rcp3.get("worktree") == r
               and rcp3.get("reviewer_tier") == "deep"
               and rcp3.get("attempt_id") not in (None, ""))
        expect("sealed receipt's attempt_id equals the request attempt_id",
               rcp3 is not None and rcp3.get("attempt_id") == spec["attempt_id"])
        expect("sealed receipt self-digest verifies via record_digest (round-3)",
               rcp3 is not None
               and tax_mod.record_digest(rcp3, exclude_field="digest") == rcp3.get("digest"))

        # 23b. MED-6 fail-closed: a spec with NO worktree cannot be sealed (validator needs it).
        spec_nowt = dict(spec); spec_nowt.pop("worktree", None)
        rcp4, e4 = build_sealed_receipt(spec_nowt, accept_review(spec, good_result()),
                                        tax=tax_mod)
        expect("MED-6: no-worktree spec seals NO receipt (fail-closed) with a worktree reason",
               rcp4 is None and bool(e4) and "worktree" in e4)

        # 24. MED-6: the schema now REQUIRES worktree + reviewer_tier + digest.
        req = set(receipt_schema.get("required", []))
        expect("MED-6: schema requires worktree + reviewer_tier + digest",
               {"worktree", "reviewer_tier", "digest"}.issubset(req))

        # ---- ROUND-4: HIGH-1 explicit/monotonic attempt binding + standalone invalidate ----
        # 25. review-spec now REQUIRES --attempt-id (no silent default to 1): omitting it
        #     is a usage error (argparse exits 2 → SystemExit), never a spec built at 1.
        try:
            main(["prog", "review-spec", "--worktree", r, "--baseline", base,
                  "--manifest", manifest_path, "--run-id", "r1", "--pre-eval-id", "pe1",
                  "--floor-result", floor_f, "--scope-clean", "--f2-result", f2_f,
                  "--out", os.path.join(tmp, "spec-noattempt.json")])
            _no_attempt_rejected = False
        except SystemExit as se:
            _no_attempt_rejected = (se.code not in (0, None))
        expect("HIGH-1: review-spec REQUIRES --attempt-id (no silent default to 1)",
               _no_attempt_rejected)

        # 26. review-spec --attempt-id 2 stamps attempt 2 into the spec (monotonic).
        spec2_f = os.path.join(tmp, "spec-a2.json")
        rc = main(["prog", "review-spec", "--worktree", r, "--baseline", base,
                   "--manifest", manifest_path, "--run-id", "r1", "--pre-eval-id", "pe1",
                   "--attempt-id", "2",
                   "--floor-result", floor_f, "--scope-clean", "--f2-result", f2_f,
                   "--changed-file", _write_changed(tmp, ["styles/app.css"]),
                   "--out", spec2_f])
        cli_spec2 = _read_json(spec2_f)
        expect("HIGH-1: review-spec --attempt-id 2 records attempt_id 2 in the spec",
               rc == 0 and cli_spec2.get("attempt_id") == 2)

        # 27. accept-review --attempt-id must EQUAL the spec's attempt_id — a mismatch is
        #     refused (no acceptance, no receipt sealed): the caller cannot accept a review
        #     from a different attempt than it declares.
        run_mis = os.path.join(tmp, "run-attempt-mismatch")
        mis_out = os.path.join(tmp, "v-attempt-mismatch.json")
        rc = main(["prog", "accept-review", "--attempt-id", "2", "--spec", spec_f,
                   "--result", result_f, "--run-dir", run_mis, "--out", mis_out])
        mis = _read_json(mis_out)
        expect("HIGH-1: accept-review --attempt-id != spec.attempt_id is refused (exit 1)",
               rc == 1 and mis.get("accepted") is False
               and "attempt_mismatch" in mis.get("failure_modes", [])
               and not os.path.exists(os.path.join(run_mis, "review", "receipt.json")))

        # 28. accept-review --attempt-id matching the spec still accepts + seals normally.
        run_match = os.path.join(tmp, "run-attempt-match")
        rc = main(["prog", "accept-review", "--attempt-id", "1", "--spec", spec_f,
                   "--result", result_f, "--run-dir", run_match,
                   "--out", os.path.join(tmp, "v-attempt-match.json")])
        expect("HIGH-1: accept-review --attempt-id == spec.attempt_id accepts + seals",
               rc == 0 and os.path.isfile(
                   os.path.join(run_match, "review", "receipt.json")))

        # 29. Standalone invalidate-receipt subcommand removes an existing receipt (the
        #     dispatcher runs this BEFORE dispatching a re-review, closing the
        #     crash-between-review-and-accept window). Idempotent afterwards.
        run_inv = os.path.join(tmp, "run-standalone-invalidate")
        rc = main(["prog", "accept-review", "--attempt-id", "1", "--spec", spec_f,
                   "--result", result_f, "--run-dir", run_inv,
                   "--out", os.path.join(tmp, "v-inv-seed.json")])
        inv_receipt = os.path.join(run_inv, "review", "receipt.json")
        seeded = os.path.isfile(inv_receipt)
        rc_inv = main(["prog", "invalidate-receipt", "--run-dir", run_inv,
                       "--out", os.path.join(tmp, "v-inv.json")])
        expect("HIGH-1: invalidate-receipt removes an existing receipt (exit 0)",
               seeded and rc_inv == 0 and not os.path.exists(inv_receipt))
        rc_inv2 = main(["prog", "invalidate-receipt", "--run-dir", run_inv,
                        "--out", os.path.join(tmp, "v-inv2.json")])
        expect("HIGH-1: invalidate-receipt on an already-clear run is a clean no-op (exit 0)",
               rc_inv2 == 0)

        # 30. invalidate-receipt requires exactly one destination (fail-closed).
        rc_inv3 = main(["prog", "invalidate-receipt",
                        "--out", os.path.join(tmp, "v-inv3.json")])
        expect("HIGH-1: invalidate-receipt with NO destination is refused (exit 2)",
               rc_inv3 == 2)

        # --- v3.3.0: the test-selection change set is NOT the gate's --------
        # Dogfood 1 caught this before its run started: leftover worktrees and
        # __pycache__ matched no `when` glob, "unmapped ⇒ full_command" fired on
        # pure noise, and 3.1.0's scoping collapsed back to running everything.
        _gi = os.path.join(tmp, "girepo")
        os.makedirs(os.path.join(_gi, "src"), exist_ok=True)
        os.makedirs(os.path.join(_gi, "build"), exist_ok=True)
        _git(_gi, ["init", "-q", "."])
        open(os.path.join(_gi, ".gitignore"), "w").write("build/\n*.pyc\n")
        open(os.path.join(_gi, "src", "a.py"), "w").write("x\n")
        open(os.path.join(_gi, "build", "out.o"), "w").write("x\n")
        open(os.path.join(_gi, "src", "a.pyc"), "w").write("x\n")
        _kept = _drop_gitignored(_gi, ["src/a.py", "build/out.o", "src/a.pyc",
                                       ".gitignore"])
        expect("ignored BYTECODE is dropped from the TEST change set",
               _kept is not None and "src/a.pyc" not in _kept)
        expect("an ignored file that is NOT harness noise SURVIVES — .env, "
               "fixtures and generated sources can all change what a test does",
               _kept is not None and "build/out.o" in _kept)
        expect("real source changes survive the filter",
               _kept is not None and "src/a.py" in _kept)
        expect("a harness worktree path is noise",
               _is_test_noise(".claude/worktrees/wf_x-1/") is True)
        expect("a source file is never noise",
               _is_test_noise("src/app.py") is False
               and _is_test_noise("tests/test_env.py") is False)
        expect("__pycache__ must be a whole path COMPONENT",
               _is_test_noise("src/__pycache__/a.txt") is True
               and _is_test_noise("tests/fixtures_not__pycache__/data.json") is False)
        # `_gi`'s .gitignore is `build/` + `*.pyc`, so a harness-worktree path is
        # noise-SHAPED but not ignored there — and must survive. Both conditions
        # are required, which is what stops a real file under a similarly-named
        # directory from vanishing.
        expect("a noise-SHAPED path that git does not ignore still survives",
               ".claude/worktrees/x/a.py"
               in (_drop_gitignored(_gi, [".claude/worktrees/x/a.py"]) or []))
        expect("an empty input is not an error",
               _drop_gitignored(_gi, []) == [])
        expect("a non-repo cannot decide, and says so rather than narrowing",
               _drop_gitignored(os.path.join(tmp, "definitely-not-a-repo"),
                                ["src/a.pyc"]) is None)
        expect("nothing noise-shaped means nothing to decide, not a failure",
               _drop_gitignored(os.path.join(tmp, "definitely-not-a-repo"),
                                ["src/app.py"]) == ["src/app.py"])

        # --- v3.1.0: the DERIVED default scope ------------------------------
        # The rule set 2026-09-02: running the whole project is a DECISION, not
        # a default. These pin every branch of that decision, including the one
        # branch where "all of them" is still the honest answer.
        _c_map = {"floor_command": "sh -c 'exit 0'", "full_command": "pytest",
                  "impacted_map": [{"when": "src/**", "run": "pytest tests/unit"}]}
        _c_nomap = {"floor_command": "sh -c 'exit 0'", "full_command": "pytest"}
        expect("a declared impacted_map makes 'impacted' the default",
               default_scope_for(_c_map)[0] == "impacted")
        expect("no impacted_map still defaults to full — nothing knows what relates",
               default_scope_for(_c_nomap)[0] == "full")
        expect("the full default explains itself, so the fix is visible",
               "impacted_map" in default_scope_for(_c_nomap)[1])
        expect("DIRECT tier with a floor defaults to floor_only",
               default_scope_for(_c_map, tier="DIRECT")[0] == "floor_only")
        expect("DIRECT tier WITHOUT a floor does not invent one",
               default_scope_for({"impacted_map": [{"when": "a/**", "run": "x"}]},
                                 tier="DIRECT")[0] == "impacted")
        expect("tier is matched case-insensitively",
               default_scope_for(_c_map, tier="direct")[0] == "floor_only")
        expect("SCOPED and FULL tiers do not override the map",
               default_scope_for(_c_map, tier="SCOPED")[0] == "impacted"
               and default_scope_for(_c_map, tier="FULL")[0] == "impacted")
        expect("an empty impacted_map is not a map",
               default_scope_for({"full_command": "pytest",
                                  "impacted_map": []})[0] == "full")
        _bad_wt = os.path.join(tmp, "no-such-worktree")
        _man_derived = {"test_contract": _c_map, "jobs": [{"id": "j"}]}
        _sl_d, _notes_d = resolve_from_manifest(_man_derived, job_id="j",
                                                no_prior_run=True, worktree=_bad_wt)
        expect("a derived impacted degrades to full rather than halting the run",
               any("degraded to 'full'" in n for n in _notes_d))
        _man_explicit = {"test_contract": _c_map,
                         "jobs": [{"id": "j", "test_scope": "impacted"}]}
        _halted = False
        try:
            resolve_from_manifest(_man_explicit, job_id="j", no_prior_run=True,
                                  worktree=_bad_wt)
        except TestContractError:
            _halted = True
        expect("an EXPLICIT impacted still fails closed", _halted)
        _man_direct = {"test_contract": _c_map, "triage": {"tier": "DIRECT"},
                       "jobs": [{"id": "j"}]}
        _sl_t, _notes_t = resolve_from_manifest(_man_direct, job_id="j",
                                                no_prior_run=True, worktree=tmp)
        expect("the manifest's triage tier reaches the default",
               any("DIRECT" in n for n in _notes_t))

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
