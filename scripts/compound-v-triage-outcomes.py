#!/usr/bin/env python3
"""
Compound V — append-only THREE-event triage-outcomes stream + cohort-separated
Tier 2 + fast-path precision (v2.9 Task F1, spec §6 / AC-3 / AC-12).

The stream ``docs/superpowers/memory/triage-outcomes.jsonl`` is STRICTLY append-only
(AC-3 — no back-fill, no mutated line). Each triaged request is modeled as THREE
separate appended lines, joined at read time on the write-once ``pre_eval_id``:

    {"event":"predicted", ts, pre_eval_id, decision, difficulty_band, impact_band,
     taxonomy_sha, localization:{resolved_paths, fan_out, flags}}     # at PRE_EVAL_DONE
    {"event":"bind", ts, pre_eval_id, run_id}                         # when the run dir exists
    {"event":"actual", ts, pre_eval_id, run_id, escalated, review_result,
     test_result, diff_files, diff_lines, sensitive_hit}             # at MERGED / ESCALATION

A declined / full-pipeline request has ``predicted`` and no ``bind``. NEVER one mutated
object — three lines.

Event keying (CR4-5)
--------------------
The reduce key is ``(pre_eval_id, run_id, event)`` — ``run_id`` is ``None`` for
``predicted`` (no run exists yet). Including ``run_id`` is what lets an ESCALATION CHILD
carry its OWN run-id whose ``bind``/``actual`` do NOT overwrite the fast-path parent's
events. Duplicate / out-of-order events: **last-writer-wins per key** (later line in file
order replaces the earlier).

Cohort separation (Iron-Invariant #3)
-------------------------------------
Only an **accepted fast-path** outcome may support a healthy / lowering signal. A
full-pipeline outcome — including an escalation CHILD — contributes **escalation evidence
ONLY**, never low-corroboration. A run is a *fast-path parent* iff its ``predicted``
decision is ``FASTPATH_ELIGIBLE`` AND it is not marked ``escalation_child``. Everything
else (missing/declined ``predicted``, or ``escalation_child:true``) is full-pipeline.
At launch every ``predicted`` is ``FULL_PIPELINE`` → Tier 2 is escalation-only by
construction. Fail-closed: an unknown / missing ``predicted`` decision → full-pipeline.

Precision (fast-path PARENT outcome only)
-----------------------------------------
    precision       = fastpath_runs_not_escalated_and_review_passed / fastpath_runs_total
    escalation_rate = escalated                                     / fastpath_runs_total
``fastpath_runs_total`` counts fast-path parent runs that have a **terminal** ``actual``.
CR5-4: a terminal ``actual`` counts only AFTER merge — a precision-IGNORED
``merge_pending`` ``actual`` (``merge_pending:true``) may precede it and is treated like a
missing ``actual`` (excluded, logged, never fabricated). A fast-path parent with no
terminal ``actual`` is excluded from BOTH numerator and denominator (logged, never
counted as a success or a failure).

CRIT-2 (genuinely git-DERIVED terminal verification)
----------------------------------------------------
A terminal ``actual`` is COUNTED only when **committed git truth** backs it, never on a
working-tree file or a caller-supplied ``approved`` string. At read/count time every field
is read from the **committed blob at HEAD** (``git show HEAD:<relpath>`` / ``git cat-file``,
routed through the process-group timeout supervisor with ``stdin </dev/null``):

  * the run's ``state.json`` and the review ``receipt.json`` are read from HEAD — a
    working-tree-only / uncommitted state.json does NOT verify (fail-closed);
  * the recorded merge SHA must resolve to a REAL commit object
    (``git cat-file -e <sha>^{commit}``) — a fictitious 40-char string never verifies;
  * the triage stream file itself must be committed at HEAD (git-tracked audit trail).

Any unverifiable / uncommitted / fake-SHA terminal actual is excluded (precision-IGNORED,
treated exactly like ``merge_pending``), never fabricated into a success. The append path
stays strictly append-only (AC-3); this verification is read/count-time only.

Reuse (no recopy)
-----------------
``append_line`` — the forbidden-basename guard + ``makedirs`` + append-never-rewrite
discipline — is imported by path from ``compound-v-update-memory.py``. ``min_sample_count``
is read through the shared ``compound-v-project-config.py`` loader. This module recopies
neither.

This stream is triage-only telemetry — evidence for the Tier-2 gate, NEVER a routing
input beyond the triage boundary. No fabricated cost / token metrics anywhere.

Python 3.9-safe, stdlib only. NEVER a hard ``import yaml`` (this module needs no YAML).

Usage:
    compound-v-triage-outcomes.py predicted --pre-eval-id ID --decision D [--field k=v ...]
    compound-v-triage-outcomes.py bind      --pre-eval-id ID --run-id R
    compound-v-triage-outcomes.py actual    --pre-eval-id ID --run-id R [--escalated] ...
    compound-v-triage-outcomes.py precision [--repo DIR] [--min-sample N]
    compound-v-triage-outcomes.py tier2     [--repo DIR] [--min-sample N]
    compound-v-triage-outcomes.py --selftest
"""

import argparse
import datetime
import importlib.util
import json
import os
import re
import subprocess
import sys

STREAM_RELPATH = os.path.join("docs", "superpowers", "memory", "triage-outcomes.jsonl")
STREAM_BASENAME = "triage-outcomes.jsonl"

EVENT_PREDICTED = "predicted"
EVENT_BIND = "bind"
EVENT_ACTUAL = "actual"
EVENTS = (EVENT_PREDICTED, EVENT_BIND, EVENT_ACTUAL)

FASTPATH_DECISION = "FASTPATH_ELIGIBLE"
# A review is "passed" for precision if it lands one of these normalized verdicts.
_REVIEW_PASSED = ("approved", "pass", "passed")


# ---------------------------------------------------------------------------- #
# Reuse siblings by path (no recopy). Loaded lazily.
# ---------------------------------------------------------------------------- #
def _load_sibling(basename, modname):
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, basename)
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_UPDATE_MEMORY = None
_PROJECT_CONFIG = None
_VALIDATE_MANIFEST = None
_VALIDATE_MANIFEST_TRIED = False


def _update_memory():
    """The update-memory module — we reuse its ``append_line`` (the forbidden-basename
    guard + makedirs + append-never-rewrite discipline), never recopy it."""
    global _UPDATE_MEMORY
    if _UPDATE_MEMORY is None:
        _UPDATE_MEMORY = _load_sibling("compound-v-update-memory.py",
                                       "compound_v_update_memory")
    return _UPDATE_MEMORY


def _project_config():
    global _PROJECT_CONFIG
    if _PROJECT_CONFIG is None:
        _PROJECT_CONFIG = _load_sibling("compound-v-project-config.py",
                                        "compound_v_project_config")
    return _PROJECT_CONFIG


def _validate_manifest():
    """The validate-manifest module — we reuse its SHARED sealed-receipt verifier
    (``verify_sealed_receipt``) so triage counts a receipt only when the producer
    (``compound-v-fastpath-run.py`` seal) and the consumer (``validate-manifest``) also
    would (CRIT-2). Never recopied. Loaded ONCE, fail-closed: any load failure leaves it
    ``None`` and the receipt check below fails closed (an unverifiable receipt never
    counts)."""
    global _VALIDATE_MANIFEST, _VALIDATE_MANIFEST_TRIED
    if not _VALIDATE_MANIFEST_TRIED:
        _VALIDATE_MANIFEST_TRIED = True
        try:
            _VALIDATE_MANIFEST = _load_sibling("compound-v-validate-manifest.py",
                                               "compound_v_validate_manifest")
        except Exception:  # noqa: BLE001 - any load failure -> fail-closed (None)
            _VALIDATE_MANIFEST = None
    return _VALIDATE_MANIFEST


# ---------------------------------------------------------------------------- #
# Paths + config.
# ---------------------------------------------------------------------------- #
def _repo_root():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(here)


def default_stream_path():
    return os.path.join(_repo_root(), STREAM_RELPATH)


def resolve_min_sample_count(repo=None, override=None):
    """Effective ``pre_eval.min_sample_count``. Explicit ``override`` wins; else read
    through the shared project-config loader (fail-closed to its declared default on a
    malformed config — never fail open)."""
    if override is not None:
        return int(override)
    pc = _project_config()
    try:
        cfg = pc.load_project_config(repo if repo is not None else _repo_root())
    except ValueError:
        cfg = {}  # malformed config → safe defaults (caller may warn separately)
    values, _warnings = pc.resolve_pre_eval(cfg)
    return int(values["min_sample_count"])


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------- #
# Append side — THREE events, each ONE append via the reused append_line discipline.
# ---------------------------------------------------------------------------- #
def _append_event(obj, stream_path=None):
    """Append exactly one JSONL event. Delegates the write to update-memory's
    ``append_line`` (append-only, makedirs, forbidden-basename guard). Belt-and-suspenders:
    this module ONLY ever writes triage-outcomes.jsonl."""
    path = stream_path or default_stream_path()
    if os.path.basename(path) != STREAM_BASENAME:
        raise ValueError(
            "refusing to write %r — triage-outcomes only appends to %s"
            % (path, STREAM_BASENAME)
        )
    _update_memory().append_line(path, obj)


def append_predicted(pre_eval_id, decision=None, difficulty_band=None, impact_band=None,
                     taxonomy_sha=None, localization=None, ts=None, stream_path=None,
                     **extra):
    """Append the ``predicted`` event (at PRE_EVAL_DONE). Keyed by ``pre_eval_id`` alone
    (no run exists yet). ``decision`` is what the cohort split reads — a
    ``FASTPATH_ELIGIBLE`` prediction is the only kind that can later become a fast-path
    parent outcome."""
    if not pre_eval_id:
        raise ValueError("append_predicted requires a pre_eval_id")
    obj = {
        "event": EVENT_PREDICTED,
        "ts": ts or _now_iso(),
        "pre_eval_id": pre_eval_id,
        "decision": decision,
        "difficulty_band": difficulty_band,
        "impact_band": impact_band,
        "taxonomy_sha": taxonomy_sha,
        "localization": localization if localization is not None else {},
    }
    obj.update(extra)
    _append_event(obj, stream_path)
    return obj


def bind_run(pre_eval_id, run_id, escalation_child=False, ts=None, stream_path=None,
             **extra):
    """Append the ``bind`` event (``pre_eval_id`` → ``run_id``) when the run dir is
    created. An escalation CHILD binds under the SAME ``pre_eval_id`` but its OWN
    ``run_id`` and marks ``escalation_child:true`` so cohort separation keeps it out of
    the fast-path outcome set (CR4-5 / Iron-Invariant #3)."""
    if not pre_eval_id:
        raise ValueError("bind_run requires a pre_eval_id")
    if not run_id:
        raise ValueError("bind_run requires a run_id")
    obj = {
        "event": EVENT_BIND,
        "ts": ts or _now_iso(),
        "pre_eval_id": pre_eval_id,
        "run_id": run_id,
    }
    if escalation_child:
        obj["escalation_child"] = True
    obj.update(extra)
    _append_event(obj, stream_path)
    return obj


def append_actual(pre_eval_id, run_id, escalated=False, review_result=None,
                  test_result=None, merge_pending=False, escalation_child=False,
                  ts=None, stream_path=None, **extra):
    """Append the ``actual`` event at MERGED / ESCALATION. CR5-4: a TERMINAL actual is
    emitted only AFTER the merge/commit boundary; a precision-IGNORED intermediate may be
    appended first with ``merge_pending:true`` (last-writer-wins means the terminal actual
    that follows replaces it). ``escalated:true`` marks a fast-path parent that escalated;
    ``escalation_child:true`` marks the full-pipeline child run itself."""
    if not pre_eval_id:
        raise ValueError("append_actual requires a pre_eval_id")
    if not run_id:
        raise ValueError("append_actual requires a run_id")
    obj = {
        "event": EVENT_ACTUAL,
        "ts": ts or _now_iso(),
        "pre_eval_id": pre_eval_id,
        "run_id": run_id,
        "escalated": bool(escalated),
        "review_result": review_result,
        "test_result": test_result,
    }
    if merge_pending:
        obj["merge_pending"] = True
    if escalation_child:
        obj["escalation_child"] = True
    obj.update(extra)
    _append_event(obj, stream_path)
    return obj


# ---------------------------------------------------------------------------- #
# Read side — reduce the append-only log, join, classify cohorts.
# ---------------------------------------------------------------------------- #
def _parse_events(line_iter):
    """Parse an iterable of raw JSONL lines into ``(objs, malformed_count)``. A malformed
    or unknown-event line is skipped and counted (fail-closed: it can only SHRINK the
    sample, never fabricate). Source-agnostic — the same parser reduces the working-tree
    file (structural helpers) and the COMMITTED blob (the count path, CRIT-1)."""
    objs = []
    malformed = 0
    for raw in line_iter:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except ValueError:
            malformed += 1
            continue
        if isinstance(obj, dict) and obj.get("event") in EVENTS:
            objs.append(obj)
        else:
            malformed += 1
    return objs, malformed


def _read_events(stream_path):
    """``(objs, malformed_count)`` read from the WORKING-TREE stream file. A missing file
    yields nothing. Used by the structural ``_reduce_stream`` helper (and its selftests);
    the COUNT path reads the committed blob instead (``_reduce_committed``, CRIT-1)."""
    path = stream_path or default_stream_path()
    if not os.path.isfile(path):
        return [], 0
    with open(path, "r", encoding="utf-8") as fh:
        return _parse_events(fh)


def _reduce_objs(objs, malformed):
    """Reduce parsed events to last-writer-wins state (source-agnostic core).

    Returns a dict:
      {"predicted": {pre_eval_id: obj},
       "runs": {(pre_eval_id, run_id): {"bind": obj|None, "actual": obj|None}},
       "malformed": int}

    Reduce key is ``(pre_eval_id, run_id, event)`` (run_id None for predicted); the LAST
    line in file order wins.
    """
    predicted = {}
    runs = {}
    for obj in objs:
        ev = obj.get("event")
        pid = obj.get("pre_eval_id")
        if not pid:
            malformed += 1
            continue
        if ev == EVENT_PREDICTED:
            predicted[pid] = obj  # last-writer-wins per (pre_eval_id, "predicted")
            continue
        rid = obj.get("run_id")
        if not rid:
            malformed += 1
            continue
        slot = runs.setdefault((pid, rid), {"bind": None, "actual": None})
        slot[ev] = obj  # last-writer-wins per (pre_eval_id, run_id, event)
    return {"predicted": predicted, "runs": runs, "malformed": malformed}


def _reduce_stream(stream_path=None):
    """Reduce the WORKING-TREE stream to last-writer-wins state. Structural helper used by
    the selftests to assert the three-event join; the COUNT path deliberately reduces the
    COMMITTED blob instead (``_reduce_committed`` — CRIT-1), so an uncommitted appended /
    overriding event can never move precision / Tier-2."""
    objs, malformed = _read_events(stream_path)
    return _reduce_objs(objs, malformed)


def _review_passed(review_result):
    return isinstance(review_result, str) and review_result.lower() in _REVIEW_PASSED


def _is_escalation_child(slot):
    """A run is an escalation child if either its bind or its actual says so."""
    for key in ("bind", "actual"):
        ev = slot.get(key)
        if isinstance(ev, dict) and ev.get("escalation_child"):
            return True
    return False


def _terminal_actual(slot):
    """The run's terminal ``actual`` (merge complete), or None. A ``merge_pending`` actual
    is NOT terminal (CR5-4) and is treated like a missing actual."""
    a = slot.get("actual")
    if not isinstance(a, dict):
        return None
    if a.get("merge_pending"):
        return None
    return a


# ---------------------------------------------------------------------------- #
# Genuinely git-DERIVED terminal verification (CRIT-2). A terminal ``actual`` is
# COUNTED (into precision / Tier 2) only when the COMMITTED git blob at HEAD backs
# it — NEVER a working-tree file, and NEVER a caller-provided ``approved``/``pass``
# string. An unverifiable / uncommitted / fake-SHA terminal actual is treated
# exactly like a precision-IGNORED ``merge_pending`` one (excluded from BOTH
# numerator and denominator, never fabricated into a success). The append itself
# stays strictly append-only (AC-3); this verification happens at READ/COUNT time
# and reads only from ``git`` (routed through the process-group timeout supervisor
# with ``stdin </dev/null`` — never a bare ``subprocess.run(timeout=...)`` on git).
# ---------------------------------------------------------------------------- #
_EXEC_RELPATH = os.path.join("docs", "superpowers", "execution")
_RUN_STATE_BASENAME = "state.json"
# The receipt path mirrors validate-manifest's _RECEIPT_SUBPATH (review/receipt.json).
_RECEIPT_SUBPATH = os.path.join("review", "receipt.json")
_MERGE_SHA_KEYS = ("merge_sha", "merged_sha", "merge_commit", "merged_commit")
_PHASE_MERGED = "MERGED"
_PHASE_ESCALATION = "ESCALATION_REQUIRED"

# External-git boundary: every git read is bounded by the shared process-group
# timeout supervisor (stdin </dev/null, bounded output) — see compound-v-churn.py.
_GIT_TIMEOUT_S = 20
_GIT_OUTPUT_CAP_BYTES = 4 * 1024 * 1024
# A merge SHA must LOOK like an object name before we ever hand it to git (defends
# ``cat-file -e <sha>^{commit}`` against a ref-name / refspec injection).
_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")


def _supervisor_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "compound-v-run-with-timeout.py")


def _run_git(argv, cwd, timeout_s=_GIT_TIMEOUT_S, cap_bytes=_GIT_OUTPUT_CAP_BYTES):
    """Run a git command UNDER the shared process-group timeout supervisor.

    Returns ``(returncode, stdout_bytes)``; ``(None, b"")`` if the launch itself
    failed (missing supervisor / OSError) — a fail-closed sentinel. stdin is
    ``DEVNULL``, the command leads its own session/process-group (SIGKILL'd as a
    group on timeout), and ``--max-output-bytes`` bounds captured stdout on disk.
    NEVER a bare ``subprocess.run(timeout=...)`` on git (external-launch invariant)."""
    import shutil as _shutil
    import tempfile as _tempfile

    sup = _supervisor_path()
    if not os.path.isfile(sup) or not cwd or not os.path.isdir(cwd):
        return None, b""
    tmpd = _tempfile.mkdtemp(prefix="cv-triage-git-")
    outfile = os.path.join(tmpd, "out")
    full = [
        sys.executable, sup,
        "--timeout", str(int(timeout_s)), "--grace", "1",
        "--cwd", cwd, "--stdout", outfile,
        "--max-output-bytes", str(int(cap_bytes)),
        "--", "git",
    ] + list(argv)
    try:
        proc = subprocess.run(
            full, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            with open(outfile, "rb") as fh:
                raw = fh.read()
        except OSError:
            raw = b""
        return proc.returncode, raw
    except OSError:
        return None, b""
    finally:
        _shutil.rmtree(tmpd, ignore_errors=True)


def _relposix(abspath, root):
    """``abspath`` expressed relative to git ``root``, POSIX-separated, or None when it
    escapes the repo. Both sides are ``realpath``-normalized first so a symlinked temp
    root (``/tmp`` → ``/private/tmp`` on macOS) does not produce a bogus ``../..`` path."""
    try:
        rel = os.path.relpath(os.path.realpath(abspath), os.path.realpath(root))
    except (ValueError, OSError):
        return None
    if rel == os.pardir or rel.startswith(os.pardir + os.sep):
        return None
    return rel.replace(os.sep, "/")


def _git_toplevel(dirpath):
    """The git work-tree root containing ``dirpath`` (``rev-parse --show-toplevel``), or
    None. A non-existent dir or a non-repo fails closed (None)."""
    if not dirpath or not os.path.isdir(dirpath):
        return None
    rc, out = _run_git(["rev-parse", "--show-toplevel"], cwd=dirpath)
    if rc != 0:
        return None
    top = out.decode("utf-8", "replace").strip()
    return top or None


def _make_git_ctx(exec_dir, stream_path=None):
    """Resolve the git context used by all terminal verification in one place: the repo
    root (derived from ``exec_dir``), a per-relpath ``git show`` cache, a per-SHA
    commit-object cache, and whether the triage STREAM file is committed at HEAD.

    No repo, or a stream that is not committed at HEAD, means NOTHING verifies — the
    whole read is fail-closed (an uncommitted audit trail is never a fabricated success)."""
    ctx = {"repo_root": None, "show_cache": {}, "commit_cache": {},
           "stream_committed": False}
    root = _git_toplevel(exec_dir)
    ctx["repo_root"] = root
    if root:
        sp = os.path.abspath(stream_path or default_stream_path())
        ctx["stream_committed"] = _git_path_committed(ctx, sp)
    return ctx


def _git_path_committed(ctx, abspath):
    """Is ``abspath`` committed at HEAD (git-tracked)? ``git cat-file -e HEAD:<rel>`` —
    cheap existence probe, reads no blob content."""
    root = ctx.get("repo_root")
    if not root:
        return False
    rel = _relposix(abspath, root)
    if rel is None:
        return False
    rc, _ = _run_git(["cat-file", "-e", "HEAD:" + rel], cwd=root)
    return rc == 0


def _git_read_json(ctx, abspath):
    """Parse the COMMITTED blob at ``HEAD:<abspath>`` as a JSON object, or None. A path
    that is not committed, or a non-object / unparseable blob, fails closed (None). The
    working-tree copy is deliberately NEVER read — that is the whole point of CRIT-2."""
    root = ctx.get("repo_root")
    if not root:
        return None
    rel = _relposix(abspath, root)
    if rel is None:
        return None
    cache = ctx["show_cache"]
    if rel in cache:
        return cache[rel]
    rc, out = _run_git(["show", "HEAD:" + rel], cwd=root)
    obj = None
    if rc == 0:
        try:
            parsed = json.loads(out.decode("utf-8"))
            if isinstance(parsed, dict):
                obj = parsed
        except (ValueError, UnicodeDecodeError):
            obj = None
    cache[rel] = obj
    return obj


def _git_read_stream_lines(ctx, abspath):
    """The COMMITTED triage-stream blob at ``HEAD:<abspath>`` as a list of raw lines, or
    ``[]``. The working-tree copy is deliberately NEVER read (CRIT-1) — an uncommitted
    appended / overriding event must not affect precision / Tier-2. Bounded output +
    ``stdin </dev/null`` come from the shared timeout supervisor via ``_run_git``."""
    root = ctx.get("repo_root")
    if not root:
        return []
    rel = _relposix(abspath, root)
    if rel is None:
        return []
    rc, out = _run_git(["show", "HEAD:" + rel], cwd=root)
    if rc != 0:
        return []
    return out.decode("utf-8", "replace").splitlines()


def _reduce_committed(ctx, stream_abspath):
    """Reduce the triage stream FROM THE COMMITTED BLOB AT HEAD (CRIT-1) to last-writer-
    wins state. No repo, or a stream not committed at HEAD, reduces to the EMPTY state
    (fail-closed — an uncommitted audit trail counts nothing). This is the ONLY reducer the
    count path uses, so an uncommitted appended / overriding ``actual`` cannot change
    precision / Tier-2 even though the append path itself stays working-tree + append-only.
    """
    if not ctx.get("repo_root") or not ctx.get("stream_committed"):
        return {"predicted": {}, "runs": {}, "malformed": 0}
    objs, malformed = _parse_events(_git_read_stream_lines(ctx, stream_abspath))
    return _reduce_objs(objs, malformed)


def _git_commit_exists(ctx, sha):
    """Does ``sha`` name a REAL commit object in this repo? ``git cat-file -e
    <sha>^{commit}`` — a tree/blob or a fictitious 40-char string peels/resolves to
    nothing and fails closed. The ``_SHA_RE`` guard keeps a ref-name from being smuggled
    in as a "SHA"."""
    root = ctx.get("repo_root")
    if not root or not isinstance(sha, str) or not _SHA_RE.match(sha):
        return False
    cache = ctx["commit_cache"]
    if sha in cache:
        return cache[sha]
    rc, _ = _run_git(["cat-file", "-e", sha + "^{commit}"], cwd=root)
    val = rc == 0
    cache[sha] = val
    return val


def _resolve_exec_dir(stream_path=None, exec_dir=None, repo=None):
    """Resolve the run-directory root (``docs/superpowers/execution``) that holds each
    run's committed ``state.json``. Explicit ``exec_dir`` wins; else derive it two levels
    up from the stream (the sibling of the stream's ``memory`` dir) so a stream and its
    run dirs stay co-located; else off ``repo`` / repo-root. Real layout:
    ``…/docs/superpowers/memory/triage-outcomes.jsonl`` → ``…/docs/superpowers/execution``."""
    if exec_dir is not None:
        return exec_dir
    if stream_path:
        sp = os.path.abspath(stream_path)
        return os.path.join(os.path.dirname(os.path.dirname(sp)), "execution")
    base = repo if repo is not None else _repo_root()
    return os.path.join(base, _EXEC_RELPATH)


def _read_run_state(ctx, exec_dir, run_id):
    """Read the run's ``state.json`` FROM THE COMMITTED BLOB AT HEAD (git-derived truth),
    or None. A working-tree-only / uncommitted / unreadable / non-object state fails
    closed (None)."""
    if not exec_dir or not run_id:
        return None
    path = os.path.join(exec_dir, run_id, _RUN_STATE_BASENAME)
    return _git_read_json(ctx, path)


def _merge_sha(state):
    """A non-empty merge SHA recorded in ``state.json`` (any accepted alias), or None.
    NOTE: this only EXTRACTS the string — ``_git_commit_exists`` decides whether it names
    a real commit object."""
    for key in _MERGE_SHA_KEYS:
        val = state.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _read_receipt(ctx, exec_dir, run_id):
    """Read the fast-path review receipt (``<run>/review/receipt.json``) FROM THE COMMITTED
    BLOB AT HEAD, or None."""
    if not exec_dir or not run_id:
        return None
    path = os.path.join(exec_dir, run_id, _RECEIPT_SUBPATH)
    return _git_read_json(ctx, path)


def _receipt_sealed_and_bound(receipt, pre_eval_id, run_id):
    """The fast-path review receipt is FULLY SEALED and bound — verified through
    validate-manifest's SHARED ``verify_sealed_receipt`` (CRIT-2), the same authority the
    producer (``compound-v-fastpath-run.py`` seal) and the consumer (``validate-manifest``)
    use. It validates schema shape + the REQUIRED ``record_digest(receipt,
    exclude_field="digest")`` self-seal + ``verdict=='approved'`` + ``run_id`` /
    ``pre_eval_id`` binding + reviewer backend:claude ⇒ Claude Opus — so a receipt that is
    bound but NOT self-sealed (or missing reviewer fields) no longer counts here while it is
    rejected there. Fail-closed: the shared verifier being unimportable, or a non-dict
    receipt, returns False (an unverifiable receipt never counts)."""
    if not isinstance(receipt, dict):
        return False
    vm = _validate_manifest()
    if vm is None or not hasattr(vm, "verify_sealed_receipt"):
        return False
    try:
        ok, _reason = vm.verify_sealed_receipt(receipt, pre_eval_id, run_id)
        return bool(ok)
    except Exception:  # noqa: BLE001 - any verifier error -> fail-closed
        return False


def _verify_terminal_actual(ctx, pre_eval_id, run_id, slot, actual, is_fastpath, exec_dir):
    """Genuinely git-DERIVED gate (CRIT-2): does COMMITTED git truth back this terminal
    ``actual``? Counted only when ALL hold (else fail-closed → excluded, like a
    ``merge_pending``):

      * the git repo exists AND the triage stream itself is committed at HEAD
        (an uncommitted audit trail is never a fabricated success);
      * a matching ``bind`` event exists for the same ``(pre_eval_id, run_id)``;
      * the run's ``state.json``, READ FROM THE COMMITTED BLOB AT HEAD, records the right
        terminal phase — ``MERGED`` + a merge SHA that resolves to a REAL commit object,
        or ``ESCALATION_REQUIRED`` + an ``escalated_to`` child link for a fast-path
        parent that escalated;
      * a non-escalated fast-path PARENT additionally carries an ``approved`` review
        receipt (also read from the committed blob) bound to this ``(pre_eval_id, run_id)``.

    Never trusts the model's self-reported ``approved``/``pass`` and never reads the
    working tree — the evidence is committed git state, so an injected terminal actual
    with no committed run behind it (or a fictitious merge SHA) can never be fabricated
    into a success.
    """
    if not ctx.get("repo_root") or not ctx.get("stream_committed"):
        return False
    if not isinstance(slot.get("bind"), dict):
        return False
    state = _read_run_state(ctx, exec_dir, run_id)
    if state is None:
        return False
    phase = state.get("phase")
    escalated = bool(actual.get("escalated"))
    if is_fastpath and escalated:
        return phase == _PHASE_ESCALATION and bool(state.get("escalated_to"))
    if phase != _PHASE_MERGED:
        return False
    if not _git_commit_exists(ctx, _merge_sha(state)):
        return False
    if is_fastpath:
        return _receipt_sealed_and_bound(
            _read_receipt(ctx, exec_dir, run_id), pre_eval_id, run_id)
    return True


def _cohorts(stream_path=None, exec_dir=None, repo=None):
    """Split reduced runs into the two cohorts, honoring Iron-Invariant #3.

    Returns:
      {"fastpath": [ {pre_eval_id, run_id, actual|None, terminal:bool} ... ],
       "fullpipeline": [ ... same shape ... ],
       "malformed": int}

    A fast-path PARENT run: predicted.decision == FASTPATH_ELIGIBLE AND not
    escalation_child. Everything else (declined/missing predicted → fail-closed, or an
    escalation child) is full-pipeline (escalation evidence only).

    ``terminal`` is now git-DERIVED (CRIT-2): a non-``merge_pending`` ``actual`` counts as
    terminal ONLY when the COMMITTED git blob at HEAD backs it (``_verify_terminal_actual``
    — committed state.json + a real merge-commit object + a committed bound receipt). An
    unverifiable terminal actual is excluded (``actual`` set to None, ``terminal`` False)
    — treated exactly like a precision-IGNORED ``merge_pending`` one, never a success.
    """
    exec_dir = _resolve_exec_dir(stream_path, exec_dir, repo)
    ctx = _make_git_ctx(exec_dir, stream_path)
    stream_abspath = os.path.abspath(stream_path or default_stream_path())
    # CRIT-1: reduce the COMMITTED blob at HEAD, never the mutable working-tree file — an
    # uncommitted appended / overriding event must not affect precision / Tier-2.
    state = _reduce_committed(ctx, stream_abspath)
    predicted = state["predicted"]
    fastpath = []
    fullpipeline = []
    for (pid, rid), slot in state["runs"].items():
        pred = predicted.get(pid)
        decision = pred.get("decision") if isinstance(pred, dict) else None
        is_fastpath = decision == FASTPATH_DECISION and not _is_escalation_child(slot)
        term = _terminal_actual(slot)
        verified = term is not None and _verify_terminal_actual(
            ctx, pid, rid, slot, term, is_fastpath, exec_dir)
        entry = {
            "pre_eval_id": pid,
            "run_id": rid,
            "actual": term if verified else None,
            "terminal": verified,
        }
        if is_fastpath:
            fastpath.append(entry)
        else:
            fullpipeline.append(entry)
    return {"fastpath": fastpath, "fullpipeline": fullpipeline,
            "malformed": state["malformed"]}


def precision_stats(stream_path=None, min_sample_count=None, repo=None, exec_dir=None):
    """Fast-path precision + escalation-rate, computed from the fast-path PARENT outcome
    only (spec §6 / AC-12), counting ONLY git-VERIFIED terminal actuals (HIGH-9 — an
    injected ``approved`` with no committed run behind it is precision-ignored, never a
    fabricated success). Returns either::

        {"precision": float, "escalation_rate": float, "n": int,
         "excluded_no_terminal_actual": int}

    or, when there is nothing (or not enough) to compute::

        {"status": "insufficient", "n": int, "excluded_no_terminal_actual": int,
         "min_sample_count": int|None}

    ``n`` = ``fastpath_runs_total`` (fast-path parents with a git-VERIFIED terminal actual).
    Parents with no verified terminal actual (missing / merge_pending / evidence-unbacked
    per HIGH-9) are excluded from BOTH numerator and denominator and reported in
    ``excluded_no_terminal_actual`` — never fabricated.
    ``insufficient`` when ``n == 0`` or (when a floor is given) ``n < min_sample_count``.
    """
    cohorts = _cohorts(stream_path, exec_dir=exec_dir, repo=repo)
    fastpath = cohorts["fastpath"]
    counted = [e for e in fastpath if e["terminal"]]
    excluded = len(fastpath) - len(counted)
    total = len(counted)

    floor = None
    if min_sample_count is not None:
        floor = int(min_sample_count)

    if total == 0 or (floor is not None and total < floor):
        return {"status": "insufficient", "n": total,
                "excluded_no_terminal_actual": excluded,
                "min_sample_count": floor}

    escalated = sum(1 for e in counted if e["actual"].get("escalated"))
    passed = sum(1 for e in counted
                 if not e["actual"].get("escalated")
                 and _review_passed(e["actual"].get("review_result")))
    return {
        "precision": passed / total,
        "escalation_rate": escalated / total,
        "n": total,
        "excluded_no_terminal_actual": excluded,
    }


def tier2_lookup(min_sample_count=None, stream_path=None, repo=None, exec_dir=None):
    """Cohort-separated Tier-2 corroboration signal (Iron-Invariant #3). Returns either::

        {"health": "healthy"|"unhealthy", "n": int}     # n = fast-path cohort size

    when ``n_fastpath >= min_sample_count`` (a calibrated, accepted-fast-path cohort
    exists), or::

        {"status": "insufficient", "n": int, "escalation_evidence_n": int,
         "min_sample_count": int}

    below the floor. A full-pipeline / escalation-child outcome NEVER contributes to
    ``health`` — it only accrues as ``escalation_evidence_n``. At launch every outcome is
    full-pipeline, so this stays ``insufficient`` (escalation-only) by construction. Only
    git-VERIFIED terminal outcomes count on either side (HIGH-9).

    ``health`` is conservative: ``healthy`` requires the sampled fast-path cohort to be
    clean (zero escalations AND every review passed); any bad outcome → ``unhealthy``
    (raises ceremony). This is evidence, never a routing input.

    MED-11: an EMPTY fast-path cohort (``n_fastpath == 0``) is NEVER ``healthy`` — empty
    history is escalation-only (the launch invariant), independent of the floor. A
    ``min_sample_count < 1`` is clamped to at least 1 (defensive — ``all([])`` is True and
    would otherwise read an empty stream as calibrated-healthy).
    """
    floor = min_sample_count
    if floor is None:
        floor = resolve_min_sample_count(repo=repo)
    floor = int(floor)
    if floor < 1:
        floor = 1  # MED-11: clamp min_sample_count >= 1 (defensive; config side also clamps)

    cohorts = _cohorts(stream_path, exec_dir=exec_dir, repo=repo)
    fastpath_counted = [e for e in cohorts["fastpath"] if e["terminal"]]
    fullpipeline_counted = [e for e in cohorts["fullpipeline"] if e["terminal"]]
    n_fastpath = len(fastpath_counted)
    escalation_evidence_n = len(fullpipeline_counted)

    # MED-11: fail closed on an empty cohort BEFORE any all()-over-empty can read healthy.
    if n_fastpath == 0 or n_fastpath < floor:
        return {"status": "insufficient", "n": n_fastpath,
                "escalation_evidence_n": escalation_evidence_n,
                "min_sample_count": floor}

    clean = all(
        (not e["actual"].get("escalated"))
        and _review_passed(e["actual"].get("review_result"))
        for e in fastpath_counted
    )
    return {"health": "healthy" if clean else "unhealthy", "n": n_fastpath}


# ---------------------------------------------------------------------------- #
# CLI.
# ---------------------------------------------------------------------------- #
def _parse_fields(pairs):
    """``k=v`` pairs → dict, with JSON-parsed values where possible (else string)."""
    out = {}
    for p in pairs or []:
        if "=" not in p:
            raise ValueError("--field expects k=v, got %r" % p)
        k, v = p.split("=", 1)
        try:
            out[k] = json.loads(v)
        except ValueError:
            out[k] = v
    return out


def main(argv):
    if "--selftest" in argv[1:]:
        return _selftest()

    parser = argparse.ArgumentParser(prog="compound-v-triage-outcomes.py")
    sub = parser.add_subparsers(dest="cmd")

    p_pred = sub.add_parser("predicted")
    p_pred.add_argument("--pre-eval-id", required=True)
    p_pred.add_argument("--decision")
    p_pred.add_argument("--difficulty-band")
    p_pred.add_argument("--impact-band")
    p_pred.add_argument("--taxonomy-sha")
    p_pred.add_argument("--field", action="append", help="extra k=v (repeatable)")
    p_pred.add_argument("--stream")

    p_bind = sub.add_parser("bind")
    p_bind.add_argument("--pre-eval-id", required=True)
    p_bind.add_argument("--run-id", required=True)
    p_bind.add_argument("--escalation-child", action="store_true")
    p_bind.add_argument("--stream")

    p_act = sub.add_parser("actual")
    p_act.add_argument("--pre-eval-id", required=True)
    p_act.add_argument("--run-id", required=True)
    p_act.add_argument("--escalated", action="store_true")
    p_act.add_argument("--review-result")
    p_act.add_argument("--test-result")
    p_act.add_argument("--merge-pending", action="store_true")
    p_act.add_argument("--escalation-child", action="store_true")
    p_act.add_argument("--field", action="append", help="extra k=v (repeatable)")
    p_act.add_argument("--stream")

    for name in ("precision", "tier2"):
        q = sub.add_parser(name)
        q.add_argument("--repo")
        q.add_argument("--min-sample", type=int)
        q.add_argument("--stream")
        q.add_argument("--exec-dir",
                       help="run-directory root (default: derived from stream/repo)")

    args = parser.parse_args(argv[1:])
    if not args.cmd:
        parser.print_usage(sys.stderr)
        return 2

    try:
        if args.cmd == "predicted":
            obj = append_predicted(
                args.pre_eval_id, decision=args.decision,
                difficulty_band=args.difficulty_band, impact_band=args.impact_band,
                taxonomy_sha=args.taxonomy_sha, stream_path=args.stream,
                **_parse_fields(args.field))
            print(json.dumps(obj, ensure_ascii=False))
            return 0
        if args.cmd == "bind":
            obj = bind_run(args.pre_eval_id, args.run_id,
                           escalation_child=args.escalation_child, stream_path=args.stream)
            print(json.dumps(obj, ensure_ascii=False))
            return 0
        if args.cmd == "actual":
            obj = append_actual(
                args.pre_eval_id, args.run_id, escalated=args.escalated,
                review_result=args.review_result, test_result=args.test_result,
                merge_pending=args.merge_pending, escalation_child=args.escalation_child,
                stream_path=args.stream, **_parse_fields(args.field))
            print(json.dumps(obj, ensure_ascii=False))
            return 0
        if args.cmd == "precision":
            print(json.dumps(precision_stats(stream_path=args.stream,
                                              min_sample_count=args.min_sample,
                                              repo=args.repo,
                                              exec_dir=args.exec_dir), indent=2))
            return 0
        if args.cmd == "tier2":
            print(json.dumps(tier2_lookup(min_sample_count=args.min_sample,
                                          stream_path=args.stream, repo=args.repo,
                                          exec_dir=args.exec_dir),
                             indent=2))
            return 0
    except ValueError as e:
        sys.stderr.write("error: %s\n" % e)
        return 1
    return 2


# ---------------------------------------------------------------------------- #
# Self-test (TDD — written first).
# ---------------------------------------------------------------------------- #
def _selftest():
    import tempfile

    failures = []

    def expect(name, cond):
        print(("  ok   - " if cond else "  FAIL - ") + name)
        if not cond:
            failures.append(name)

    # A FULLY sealed fast-path review receipt, built through the SAME shared record_digest
    # primitive the producer seals with and the validator verifies against (CRIT-2). A
    # bound-but-unsealed receipt (``seal_it=False`` → no valid self-digest) is the negative
    # fixture for "triage's receipt check == validate-manifest's verify".
    _tax = _load_sibling("compound-v-taxonomy.py", "cv_triage_selftest_taxonomy")

    def _sealed_receipt(run_id, pre_eval_id, verdict="approved", seal_it=True, **over):
        _d = "sha256:" + "0" * 64
        rc = {
            "run_id": run_id, "pre_eval_id": pre_eval_id,
            "manifest_digest": _d, "baseline_sha": "b" * 40, "final_diff_digest": _d,
            "reviewer_backend": "claude", "reviewer_tier": "deep",
            "reviewer_model": "claude-opus-4-8", "worktree": "/wt",
            "attempt_id": 1, "ts": "2026-07-11T00:00:00Z", "verdict": verdict,
            "integration_rationale": "single-job fast-path: no cross-job seams",
        }
        rc.update(over)
        if seal_it:
            rc["digest"] = _tax.record_digest(rc, exclude_field="digest")
        return rc

    # ---- git fixture helpers: a REAL throwaway repo in a tempdir OUTSIDE the worktree.
    # CRIT-2 made verification genuinely git-derived, so evidence must be actually
    # COMMITTED (git init + commit the state.json + receipt + stream) for a terminal
    # actual to count — a working-tree-only / uncommitted state.json must NOT verify.
    def _fx_env():
        env = dict(os.environ)
        env.update({
            "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@example.com",
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
        })
        return env

    def _fx_git(cwd, *args):
        subprocess.run(["git", "-C", cwd] + list(args), env=_fx_env(),
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=True)

    def _fx_git_out(cwd, *args):
        p = subprocess.run(["git", "-C", cwd] + list(args), env=_fx_env(),
                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, check=True)
        return p.stdout.decode("utf-8", "replace").strip()

    def _fx_commit_all(repo, msg="fixture"):
        _fx_git(repo, "add", "-A")
        _fx_git(repo, "commit", "--allow-empty", "-q", "-m", msg)

    # A run dir at <td>/execution/<run-id>/ is what _resolve_exec_dir derives for EVERY
    # stream below (two dirs up from the stream + "execution"). CRIT-2: a terminal actual
    # counts only once the committed state.json (+ receipt) that backs it is COMMITTED,
    # so mk_run writes the evidence AND commits it (with the already-appended stream) into
    # HEAD. ``commit=False`` seeds working-tree-only evidence for the negative cases.
    def mk_run(exec_dir, run_id, phase, pre_eval_id=None, merge_sha=None,
               receipt=False, escalated_to=None, commit=True, sealed_receipt=True):
        repo = os.path.dirname(os.path.abspath(exec_dir))  # == <td>
        rd = os.path.join(exec_dir, run_id)
        os.makedirs(rd, exist_ok=True)
        st = {"run_id": run_id, "phase": phase, "pre_eval_id": pre_eval_id,
              "escalated_to": escalated_to}
        if merge_sha:
            st["merge_sha"] = merge_sha
        with open(os.path.join(rd, _RUN_STATE_BASENAME), "w", encoding="utf-8") as fh:
            json.dump(st, fh)
        if receipt:
            revdir = os.path.join(rd, "review")
            os.makedirs(revdir, exist_ok=True)
            # CRIT-2: a counted fast-path receipt must be FULLY sealed (schema + self-digest
            # + reviewer-opus + binding) so triage's check agrees byte-for-byte with the
            # producer's seal and validate-manifest's verify. ``sealed_receipt=False`` seeds
            # the bound-but-unsealed negative fixture (no valid digest → must NOT count).
            rc = _sealed_receipt(run_id, pre_eval_id, seal_it=sealed_receipt)
            with open(os.path.join(revdir, "receipt.json"), "w", encoding="utf-8") as fh:
                json.dump(rc, fh)
        if commit:
            _fx_commit_all(repo)

    FAKE_SHA = "a" * 40  # NOT a real object → never resolves to a commit (CRIT-2)

    with tempfile.TemporaryDirectory() as td:
        _fx_git(td, "init", "-q")
        _fx_git(td, "commit", "--allow-empty", "-q", "-m", "root")
        REAL_SHA = _fx_git_out(td, "rev-parse", "HEAD")  # a genuine commit object

        stream = os.path.join(td, "memdir", STREAM_BASENAME)
        exec_dir = os.path.join(td, "execution")  # == _resolve_exec_dir for every stream

        # --- THREE append events joined on pre_eval_id (never a mutated line) --------
        pid = "2026-07-11T181200Z-make-button-red-a1b2"
        rid = "2026-07-11-make-button-red"
        append_predicted(pid, decision=FASTPATH_DECISION, difficulty_band="low",
                         impact_band="low", ts="2026-07-11T18:12:00Z", stream_path=stream,
                         localization={"resolved_paths": ["src/ui/button.css"],
                                       "fan_out": 1, "flags": []})
        bind_run(pid, rid, ts="2026-07-11T18:20:00Z", stream_path=stream)
        append_actual(pid, rid, escalated=False, review_result="approved",
                      test_result="pass", ts="2026-07-11T18:40:00Z", stream_path=stream,
                      diff_files=1, diff_lines=3, sensitive_hit=False)
        # HIGH-9: back the terminal actual with committed run state + an approved receipt.
        mk_run(exec_dir, rid, _PHASE_MERGED, pre_eval_id=pid, merge_sha=REAL_SHA,
               receipt=True)
        with open(stream, "r", encoding="utf-8") as fh:
            lines = [l for l in fh.read().splitlines() if l.strip()]
        expect("three separate appended lines", len(lines) == 3)
        expect("line 1 is predicted", json.loads(lines[0])["event"] == EVENT_PREDICTED)
        expect("line 2 is bind", json.loads(lines[1])["event"] == EVENT_BIND)
        expect("line 3 is actual", json.loads(lines[2])["event"] == EVENT_ACTUAL)
        state = _reduce_stream(stream)
        expect("reduce joins predicted on pre_eval_id", pid in state["predicted"])
        expect("reduce joins run on (pre_eval_id, run_id)", (pid, rid) in state["runs"])
        expect("bind + actual under one run slot",
               state["runs"][(pid, rid)]["bind"] is not None
               and state["runs"][(pid, rid)]["actual"] is not None)

        # --- append_line discipline: NEVER writes anywhere but triage-outcomes.jsonl --
        def wrong_basename():
            _append_event({"event": EVENT_BIND, "pre_eval_id": "x", "run_id": "y"},
                          stream_path=os.path.join(td, "routing-lessons.md"))
        try:
            wrong_basename()
            expect("refuses a non-triage-outcomes basename", False)
        except ValueError:
            expect("refuses a non-triage-outcomes basename", True)

        # --- Tier 2 insufficient below min_sample (single fast-path outcome) ----------
        t2 = tier2_lookup(min_sample_count=5, stream_path=stream)
        expect("tier2 insufficient below min_sample",
               t2.get("status") == "insufficient" and t2["n"] == 1)
        expect("tier2 reports the floor", t2["min_sample_count"] == 5)
        t2ok = tier2_lookup(min_sample_count=1, stream_path=stream)
        expect("tier2 at/above floor yields a health signal", "health" in t2ok)
        expect("clean fast-path cohort is healthy", t2ok["health"] == "healthy")

        # === A full-pipeline outcome is NOT low-corroboration (escalation evidence) ===
        stream2 = os.path.join(td, "fp", STREAM_BASENAME)
        fpid = "2026-07-11T090000Z-refactor-auth-zz99"
        frid = "2026-07-11-refactor-auth"
        append_predicted(fpid, decision="FULL_PIPELINE", difficulty_band="high",
                         impact_band="high", stream_path=stream2)
        bind_run(fpid, frid, stream_path=stream2)
        # A perfectly clean, non-escalated, review-passed FULL-PIPELINE outcome...
        append_actual(fpid, frid, escalated=False, review_result="approved",
                      test_result="pass", stream_path=stream2)
        mk_run(exec_dir, frid, _PHASE_MERGED, pre_eval_id=fpid, merge_sha=REAL_SHA)
        t2fp = tier2_lookup(min_sample_count=1, stream_path=stream2)
        expect("full-pipeline outcome does NOT create a healthy signal",
               t2fp.get("status") == "insufficient")
        expect("full-pipeline outcome accrues as escalation evidence ONLY",
               t2fp["escalation_evidence_n"] == 1 and t2fp["n"] == 0)
        pfp = precision_stats(stream_path=stream2)
        expect("full-pipeline outcome contributes nothing to precision",
               pfp.get("status") == "insufficient" and pfp["n"] == 0)

        # === Precision numerator/denominator match declared fixtures =================
        # 4 fast-path PARENTS with terminal actuals:
        #   P1 not-escalated + approved   -> numerator hit
        #   P2 not-escalated + approved   -> numerator hit
        #   P3 escalated (child minted)   -> denominator only (escalation)
        #   P4 not-escalated + changes    -> denominator only (review failed)
        # + 1 fast-path parent P5 with NO terminal actual (only merge_pending) -> excluded
        # + P3's escalation CHILD (own run-id) -> escalation evidence, NEVER precision
        stream3 = os.path.join(td, "prec", STREAM_BASENAME)

        def fastpath_run(tag, escalated, review, merge_pending_only=False):
            ppid = "PID-" + tag
            prid = "RUN-" + tag
            append_predicted(ppid, decision=FASTPATH_DECISION, difficulty_band="low",
                             impact_band="low", stream_path=stream3)
            bind_run(ppid, prid, stream_path=stream3)
            if merge_pending_only:
                append_actual(ppid, prid, escalated=False, review_result=review,
                              merge_pending=True, stream_path=stream3)
                # merge_pending is not terminal → no committed run backs it (excluded).
            else:
                append_actual(ppid, prid, escalated=escalated, review_result=review,
                              test_result="pass", stream_path=stream3)
                if escalated:
                    # HIGH-9: an escalated parent is backed by ESCALATION_REQUIRED + child.
                    mk_run(exec_dir, prid, _PHASE_ESCALATION, pre_eval_id=ppid,
                           escalated_to=prid + "-child")
                else:
                    # HIGH-9: a merged parent is backed by MERGED + sha + approved receipt.
                    # (The receipt proves the run genuinely merged; precision's numerator
                    # still reads the stream's self-reported review_result — so P4's
                    # changes_requested stays denominator-only, not a numerator hit.)
                    mk_run(exec_dir, prid, _PHASE_MERGED, pre_eval_id=ppid,
                           merge_sha=REAL_SHA, receipt=True)
            return ppid, prid

        fastpath_run("P1", False, "approved")
        fastpath_run("P2", False, "approved")
        p3id, _ = fastpath_run("P3", True, "approved")   # escalated parent
        fastpath_run("P4", False, "changes_requested")   # review NOT passed
        fastpath_run("P5", False, "approved", merge_pending_only=True)  # excluded
        # P3's escalation child: SAME pre_eval_id, its OWN run-id, marked escalation_child.
        child_rid = "RUN-P3-child"
        bind_run(p3id, child_rid, escalation_child=True, stream_path=stream3)
        append_actual(p3id, child_rid, escalated=False, review_result="approved",
                      test_result="pass", escalation_child=True, stream_path=stream3)
        # CRIT-1: the count reduces the COMMITTED blob — P5 and the child were appended
        # after P4's mk_run, so commit them before counting (they must be IN the sample).
        _fx_commit_all(td)

        prec = precision_stats(stream_path=stream3)
        # denominator = P1,P2,P3,P4 = 4 (P5 merge_pending excluded, child excluded).
        expect("fastpath_runs_total = 4 (merge_pending + child excluded)", prec["n"] == 4)
        expect("one parent excluded for no terminal actual (merge_pending)",
               prec["excluded_no_terminal_actual"] == 1)
        # numerator = P1,P2 = 2 (not escalated AND review passed).
        expect("precision = 2/4", abs(prec["precision"] - 0.5) < 1e-9)
        # escalation_rate = P3 = 1/4.
        expect("escalation_rate = 1/4", abs(prec["escalation_rate"] - 0.25) < 1e-9)

        # CR4-5: the escalation child did NOT overwrite the parent's terminal outcome.
        cohorts = _cohorts(stream3)
        parent_p3 = [e for e in cohorts["fastpath"]
                     if e["pre_eval_id"] == p3id and e["run_id"] == "RUN-P3"]
        child_p3 = [e for e in cohorts["fullpipeline"]
                    if e["pre_eval_id"] == p3id and e["run_id"] == child_rid]
        expect("parent P3 stays in the fast-path cohort (escalated:true intact)",
               len(parent_p3) == 1 and parent_p3[0]["actual"]["escalated"] is True)
        expect("escalation child is full-pipeline cohort (never fast-path)",
               len(child_p3) == 1)
        expect("escalation child accrues as escalation evidence, not precision",
               all(not (e["pre_eval_id"] == p3id and e["run_id"] == child_rid)
                   for e in cohorts["fastpath"]))

        # === Duplicate / out-of-order: last-writer-wins per (pre_eval_id, event) ======
        stream4 = os.path.join(td, "lww", STREAM_BASENAME)
        did = "PID-DUP"
        drid = "RUN-DUP"
        # actual appended BEFORE bind (out of order) + a first, later-corrected verdict.
        append_predicted(did, decision=FASTPATH_DECISION, stream_path=stream4)
        append_actual(did, drid, escalated=False, review_result="approved",
                      stream_path=stream4)                       # first (wins? no)
        bind_run(did, drid, stream_path=stream4)                 # out-of-order bind
        append_actual(did, drid, escalated=True, review_result="approved",
                      stream_path=stream4)                       # corrected -> LAST wins
        # HIGH-9: the winning terminal is escalated → back it with escalation state.
        mk_run(exec_dir, drid, _PHASE_ESCALATION, pre_eval_id=did,
               escalated_to=drid + "-child")
        redu = _reduce_stream(stream4)
        expect("out-of-order bind still joins the run", (did, drid) in redu["runs"])
        expect("last-writer-wins: latest actual (escalated:true) wins",
               redu["runs"][(did, drid)]["actual"]["escalated"] is True)
        pdup = precision_stats(stream_path=stream4)
        expect("last-writer-wins reflected in precision (escalated, 0/1 passed)",
               pdup["n"] == 1 and abs(pdup["precision"] - 0.0) < 1e-9
               and abs(pdup["escalation_rate"] - 1.0) < 1e-9)
        # A duplicate predicted with a changed decision: last one wins (once committed —
        # CRIT-1: the reclassifying predicted must be in the COMMITTED blob to take effect).
        append_predicted(did, decision="FULL_PIPELINE", stream_path=stream4)
        _fx_commit_all(td)
        pdup2 = precision_stats(stream_path=stream4)
        expect("last predicted (FULL_PIPELINE) reclassifies the run out of fast-path",
               pdup2.get("status") == "insufficient" and pdup2["n"] == 0)

        # === merge_pending precedes a terminal actual (CR5-4) ========================
        stream5 = os.path.join(td, "mp", STREAM_BASENAME)
        mpid, mrid = "PID-MP", "RUN-MP"
        append_predicted(mpid, decision=FASTPATH_DECISION, stream_path=stream5)
        bind_run(mpid, mrid, stream_path=stream5)
        append_actual(mpid, mrid, escalated=False, review_result="approved",
                      merge_pending=True, stream_path=stream5)   # precision-IGNORED
        _fx_commit_all(td)  # CRIT-1: commit so the merge_pending run is IN the counted blob
        pmp = precision_stats(stream_path=stream5)
        expect("merge_pending-only run is insufficient (excluded, not fabricated)",
               pmp.get("status") == "insufficient" and pmp["n"] == 0
               and pmp["excluded_no_terminal_actual"] == 1)
        append_actual(mpid, mrid, escalated=False, review_result="approved",
                      test_result="pass", stream_path=stream5)   # terminal AFTER merge
        mk_run(exec_dir, mrid, _PHASE_MERGED, pre_eval_id=mpid, merge_sha=REAL_SHA,
               receipt=True)                                     # HIGH-9: back the merge
        pmp2 = precision_stats(stream_path=stream5)
        expect("terminal actual after merge is counted (1/1)",
               pmp2["n"] == 1 and abs(pmp2["precision"] - 1.0) < 1e-9)

        # === Missing actual → excluded from precision, logged (never fabricated) =====
        stream6 = os.path.join(td, "miss", STREAM_BASENAME)
        append_predicted("PID-A", decision=FASTPATH_DECISION, stream_path=stream6)
        bind_run("PID-A", "RUN-A", stream_path=stream6)           # bound, no actual yet
        append_predicted("PID-B", decision=FASTPATH_DECISION, stream_path=stream6)
        bind_run("PID-B", "RUN-B", stream_path=stream6)
        append_actual("PID-B", "RUN-B", escalated=False, review_result="approved",
                      test_result="pass", stream_path=stream6)
        mk_run(exec_dir, "RUN-B", _PHASE_MERGED, pre_eval_id="PID-B", merge_sha=REAL_SHA,
               receipt=True)                                     # HIGH-9: back RUN-B
        pmiss = precision_stats(stream_path=stream6)
        expect("bound-but-no-actual parent excluded from denominator",
               pmiss["n"] == 1 and pmiss["excluded_no_terminal_actual"] == 1)

        # === Malformed lines are skipped, never crash / fabricate ====================
        stream7 = os.path.join(td, "bad", STREAM_BASENAME)
        append_predicted("PID-G", decision=FASTPATH_DECISION, stream_path=stream7)
        bind_run("PID-G", "RUN-G", stream_path=stream7)
        append_actual("PID-G", "RUN-G", escalated=False, review_result="approved",
                      test_result="pass", stream_path=stream7)
        mk_run(exec_dir, "RUN-G", _PHASE_MERGED, pre_eval_id="PID-G", merge_sha=REAL_SHA,
               receipt=True)                                     # HIGH-9: back RUN-G
        with open(stream7, "a", encoding="utf-8") as fh:
            fh.write("this is not json\n")
            fh.write('{"event":"predicted"}\n')       # missing pre_eval_id
            fh.write('{"event":"bogus","pre_eval_id":"x"}\n')  # unknown event
        st7 = _reduce_stream(stream7)
        expect("malformed / unknown lines counted, not crashing", st7["malformed"] >= 2)
        _fx_commit_all(td)  # CRIT-1: commit the malformed neighbors INTO the counted blob
        p7 = precision_stats(stream_path=stream7)
        expect("valid outcome still computes despite malformed neighbors", p7["n"] == 1)

        # === Empty / missing stream → insufficient (never fail open) =================
        pempty = precision_stats(stream_path=os.path.join(td, "nope", STREAM_BASENAME))
        expect("missing stream -> precision insufficient",
               pempty.get("status") == "insufficient" and pempty["n"] == 0)
        t2empty = tier2_lookup(min_sample_count=5,
                               stream_path=os.path.join(td, "nope", STREAM_BASENAME))
        expect("missing stream -> tier2 insufficient (escalation-only)",
               t2empty.get("status") == "insufficient")

        # === min_sample floor applies to precision when supplied =====================
        pfloor = precision_stats(stream_path=stream3, min_sample_count=99)
        expect("precision insufficient below an explicit floor",
               pfloor.get("status") == "insufficient" and pfloor["n"] == 4)

        # === resolve_min_sample_count reads the shared config (default 5) ============
        expect("min_sample default resolves to 5 for an un-onboarded repo",
               resolve_min_sample_count(repo=td) == 5)

        # ==================================================================== #
        # HIGH-9 — a terminal actual is counted only when git-derived run state #
        # backs it; an injected approved/pass string is NEVER a fabricated hit. #
        # ==================================================================== #

        # H9-a: terminal actual with NO matching bind → precision-ignored (no bind slot).
        s_nobind = os.path.join(td, "h9-nobind", STREAM_BASENAME)
        append_predicted("PID-NB", decision=FASTPATH_DECISION, stream_path=s_nobind)
        append_actual("PID-NB", "RUN-NB", escalated=False, review_result="approved",
                      test_result="pass", stream_path=s_nobind)   # actual, but no bind
        # (even a MERGED run dir must not rescue it — the missing bind fails closed)
        mk_run(exec_dir, "RUN-NB", _PHASE_MERGED, pre_eval_id="PID-NB", merge_sha=REAL_SHA,
               receipt=True)
        p_nb = precision_stats(stream_path=s_nobind)
        expect("terminal actual with no matching bind is NOT a success (precision-ignored)",
               p_nb.get("status") == "insufficient" and p_nb["n"] == 0
               and p_nb["excluded_no_terminal_actual"] == 1)

        # H9-b: an injected approved with NO merge evidence (bind present, no state.json)
        #       → does not raise precision (stays insufficient, never a fabricated hit).
        s_noev = os.path.join(td, "h9-noev", STREAM_BASENAME)
        append_predicted("PID-NE", decision=FASTPATH_DECISION, stream_path=s_noev)
        bind_run("PID-NE", "RUN-NE", stream_path=s_noev)
        append_actual("PID-NE", "RUN-NE", escalated=False, review_result="approved",
                      test_result="pass", stream_path=s_noev)     # injected "success"
        # deliberately NO run dir / state.json for RUN-NE — but commit the stream so the
        # parent IS in the counted blob (CRIT-1) and is excluded for want of merge evidence.
        _fx_commit_all(td)
        p_ne = precision_stats(stream_path=s_noev)
        expect("injected approved with no merge evidence does not raise precision",
               p_ne.get("status") == "insufficient" and p_ne["n"] == 0
               and p_ne["excluded_no_terminal_actual"] == 1)
        t2_ne = tier2_lookup(min_sample_count=1, stream_path=s_noev)
        expect("injected approved with no merge evidence never reads healthy",
               t2_ne.get("status") == "insufficient" and t2_ne["n"] == 0)

        # H9-c: MERGED state but WRONG/absent evidence still fails closed:
        #   - a merged fast-path parent with no receipt → not counted
        #   - a merged fast-path parent with a receipt bound to the WRONG run → not counted
        s_rcpt = os.path.join(td, "h9-rcpt", STREAM_BASENAME)
        append_predicted("PID-NR", decision=FASTPATH_DECISION, stream_path=s_rcpt)
        bind_run("PID-NR", "RUN-NR", stream_path=s_rcpt)
        append_actual("PID-NR", "RUN-NR", escalated=False, review_result="approved",
                      test_result="pass", stream_path=s_rcpt)
        mk_run(exec_dir, "RUN-NR", _PHASE_MERGED, pre_eval_id="PID-NR", merge_sha=REAL_SHA,
               receipt=False)                                     # MERGED but NO receipt
        p_nr = precision_stats(stream_path=s_rcpt)
        expect("merged fast-path parent with no review receipt is not counted",
               p_nr.get("status") == "insufficient" and p_nr["n"] == 0)
        # now COMMIT a FULLY SEALED receipt but bind it to a DIFFERENT run-id (replay
        # defense): the shared verifier's binding check must reject it even though it is a
        # genuinely committed, self-sealed receipt at HEAD.
        _rev = os.path.join(exec_dir, "RUN-NR", "review")
        os.makedirs(_rev, exist_ok=True)
        with open(os.path.join(_rev, "receipt.json"), "w", encoding="utf-8") as fh:
            json.dump(_sealed_receipt("SOME-OTHER-RUN", "PID-NR"), fh)
        _fx_commit_all(td)  # commit the wrong-bound receipt → tests binding, not commit-ness
        p_nr2 = precision_stats(stream_path=s_rcpt)
        expect("merged fast-path parent with a committed but unbound (wrong run_id) receipt "
               "is not counted", p_nr2.get("status") == "insufficient" and p_nr2["n"] == 0)

        # H9-d: a GENUINELY verified fast-path success (bind + MERGED + sha + bound approved
        #       receipt) IS counted — precision 1/1, cohort healthy.
        s_ok = os.path.join(td, "h9-ok", STREAM_BASENAME)
        append_predicted("PID-OK", decision=FASTPATH_DECISION, stream_path=s_ok)
        bind_run("PID-OK", "RUN-OK", stream_path=s_ok)
        append_actual("PID-OK", "RUN-OK", escalated=False, review_result="approved",
                      test_result="pass", stream_path=s_ok)
        mk_run(exec_dir, "RUN-OK", _PHASE_MERGED, pre_eval_id="PID-OK", merge_sha=REAL_SHA,
               receipt=True)
        p_ok = precision_stats(stream_path=s_ok)
        expect("genuinely verified fast-path success is counted (1/1)",
               p_ok["n"] == 1 and abs(p_ok["precision"] - 1.0) < 1e-9)
        t2_ok = tier2_lookup(min_sample_count=1, stream_path=s_ok)
        expect("genuinely verified fast-path success reads healthy",
               t2_ok.get("health") == "healthy" and t2_ok["n"] == 1)

        # ==================================================================== #
        # MED-11 — an empty fast-path cohort is NEVER calibrated-healthy.       #
        # ==================================================================== #

        # M11-a: empty stream with --min-sample 0 → insufficient (never healthy n=0).
        s_empty = os.path.join(td, "m11-empty", STREAM_BASENAME)
        t2_e0 = tier2_lookup(min_sample_count=0, stream_path=s_empty)
        expect("tier2 empty stream with --min-sample 0 is insufficient (never healthy n=0)",
               t2_e0.get("status") == "insufficient" and t2_e0["n"] == 0
               and t2_e0.get("health") is None)
        expect("tier2 clamps min_sample_count < 1 to at least 1",
               t2_e0["min_sample_count"] == 1)

        # M11-b: a NON-empty cohort that is entirely full-pipeline (no fast-path parents),
        #        with --min-sample 0, is still insufficient (n_fastpath == 0), never healthy.
        t2_fp0 = tier2_lookup(min_sample_count=0, stream_path=stream2)
        expect("all-full-pipeline cohort with --min-sample 0 is insufficient, not healthy",
               t2_fp0.get("status") == "insufficient" and t2_fp0["n"] == 0
               and t2_fp0["escalation_evidence_n"] == 1)

        # ==================================================================== #
        # CRIT-2 — verification is GENUINELY git-derived: read the committed     #
        # blob at HEAD, and the merge SHA must be a REAL commit object. An       #
        # uncommitted state.json / a fictitious SHA is NEVER a fabricated hit.   #
        # (These use a REAL temp git repo — git init + commit — above.)          #
        # ==================================================================== #

        # C2-a: a COMMITTED MERGED state with a REAL merge-commit SHA + a bound approved
        #       receipt is counted (the positive control for the git-derived path).
        s_c2ok = os.path.join(td, "c2-ok", STREAM_BASENAME)
        append_predicted("PID-C2", decision=FASTPATH_DECISION, stream_path=s_c2ok)
        bind_run("PID-C2", "RUN-C2", stream_path=s_c2ok)
        append_actual("PID-C2", "RUN-C2", escalated=False, review_result="approved",
                      test_result="pass", stream_path=s_c2ok)
        mk_run(exec_dir, "RUN-C2", _PHASE_MERGED, pre_eval_id="PID-C2",
               merge_sha=REAL_SHA, receipt=True)  # committed, real commit SHA, bound receipt
        p_c2 = precision_stats(stream_path=s_c2ok)
        expect("committed MERGED + real merge-commit SHA + bound receipt is counted (1/1)",
               p_c2["n"] == 1 and abs(p_c2["precision"] - 1.0) < 1e-9)

        # C2-b: THE e2e GAP — an UNCOMMITTED state.json carrying a fictitious 40-char SHA
        #       must NOT verify. Seed the evidence in the WORKING TREE only (commit=False),
        #       exactly as the old read-the-working-tree bug would have happily accepted.
        s_c2unc = os.path.join(td, "c2-uncommitted", STREAM_BASENAME)
        append_predicted("PID-UC", decision=FASTPATH_DECISION, stream_path=s_c2unc)
        bind_run("PID-UC", "RUN-UC", stream_path=s_c2unc)
        append_actual("PID-UC", "RUN-UC", escalated=False, review_result="approved",
                      test_result="pass", stream_path=s_c2unc)
        # Commit the STREAM (so the parent is in the counted blob, CRIT-1) but leave the
        # state.json + receipt WORKING-TREE ONLY (commit=False) — exactly the e2e gap: the
        # old working-tree read would have accepted it; the committed-blob read must not.
        _fx_commit_all(td)
        mk_run(exec_dir, "RUN-UC", _PHASE_MERGED, pre_eval_id="PID-UC",
               merge_sha=FAKE_SHA, receipt=True, commit=False)  # working-tree only + fake SHA
        p_uc = precision_stats(stream_path=s_c2unc)
        expect("uncommitted state.json with a fictitious SHA is NOT counted (the e2e gap)",
               p_uc.get("status") == "insufficient" and p_uc["n"] == 0
               and p_uc["excluded_no_terminal_actual"] == 1)
        t2_uc = tier2_lookup(min_sample_count=1, stream_path=s_c2unc)
        expect("uncommitted fake-SHA actual never reads healthy",
               t2_uc.get("status") == "insufficient" and t2_uc["n"] == 0)

        # C2-c: a COMMITTED MERGED state whose merge SHA is not a REAL git object
        #       (fictitious 40-char string) must NOT verify — non-empty is not enough.
        s_c2fake = os.path.join(td, "c2-fakesha", STREAM_BASENAME)
        append_predicted("PID-FS", decision=FASTPATH_DECISION, stream_path=s_c2fake)
        bind_run("PID-FS", "RUN-FS", stream_path=s_c2fake)
        append_actual("PID-FS", "RUN-FS", escalated=False, review_result="approved",
                      test_result="pass", stream_path=s_c2fake)
        mk_run(exec_dir, "RUN-FS", _PHASE_MERGED, pre_eval_id="PID-FS",
               merge_sha=FAKE_SHA, receipt=True)  # COMMITTED, but the SHA is not a commit
        p_fs = precision_stats(stream_path=s_c2fake)
        expect("committed MERGED whose merge SHA is not a real commit object is NOT counted",
               p_fs.get("status") == "insufficient" and p_fs["n"] == 0
               and p_fs["excluded_no_terminal_actual"] == 1)

        # C2-d: an escalated fast-path PARENT backed by a COMMITTED ESCALATION_REQUIRED
        #       state + escalated_to child link IS counted (escalation-rate denominator).
        s_c2esc = os.path.join(td, "c2-esc", STREAM_BASENAME)
        append_predicted("PID-ES", decision=FASTPATH_DECISION, stream_path=s_c2esc)
        bind_run("PID-ES", "RUN-ES", stream_path=s_c2esc)
        append_actual("PID-ES", "RUN-ES", escalated=True, review_result="approved",
                      test_result="pass", stream_path=s_c2esc)
        mk_run(exec_dir, "RUN-ES", _PHASE_ESCALATION, pre_eval_id="PID-ES",
               escalated_to="RUN-ES-child")  # committed ESCALATION_REQUIRED + child link
        p_es = precision_stats(stream_path=s_c2esc)
        expect("committed ESCALATION_REQUIRED + escalated_to parent is counted (esc-rate 1/1)",
               p_es["n"] == 1 and abs(p_es["escalation_rate"] - 1.0) < 1e-9
               and abs(p_es["precision"] - 0.0) < 1e-9)

        # C2-e: git-derived means the WORKING TREE is never consulted — a COMMITTED valid
        #       MERGED state that is then OVERWRITTEN in the working tree with a bogus phase
        #       still verifies from HEAD (and, conversely, a working-tree-only edit can
        #       neither fabricate nor destroy a committed truth).
        s_c2wt = os.path.join(td, "c2-worktree", STREAM_BASENAME)
        append_predicted("PID-WT", decision=FASTPATH_DECISION, stream_path=s_c2wt)
        bind_run("PID-WT", "RUN-WT", stream_path=s_c2wt)
        append_actual("PID-WT", "RUN-WT", escalated=False, review_result="approved",
                      test_result="pass", stream_path=s_c2wt)
        mk_run(exec_dir, "RUN-WT", _PHASE_MERGED, pre_eval_id="PID-WT",
               merge_sha=REAL_SHA, receipt=True)  # committed-good
        with open(os.path.join(exec_dir, "RUN-WT", _RUN_STATE_BASENAME),
                  "w", encoding="utf-8") as fh:
            json.dump({"run_id": "RUN-WT", "phase": "GARBAGE"}, fh)  # working-tree tamper
        p_wt = precision_stats(stream_path=s_c2wt)
        expect("verification reads HEAD, not the working tree (committed truth wins)",
               p_wt["n"] == 1 and abs(p_wt["precision"] - 1.0) < 1e-9)

        # ==================================================================== #
        # CRIT-1 (round 3) — the terminal events are REDUCED from the committed  #
        # blob, not the working tree. An uncommitted appended / overriding      #
        # `actual` (working-tree only) must NOT move precision / Tier-2.         #
        # ==================================================================== #
        s_c1 = os.path.join(td, "r3-crit1", STREAM_BASENAME)
        append_predicted("PID-C1", decision=FASTPATH_DECISION, stream_path=s_c1)
        bind_run("PID-C1", "RUN-C1", stream_path=s_c1)
        append_actual("PID-C1", "RUN-C1", escalated=False, review_result="approved",
                      test_result="pass", stream_path=s_c1)
        # committed, real merge-commit SHA, fully-sealed bound receipt → a verified 1/1.
        mk_run(exec_dir, "RUN-C1", _PHASE_MERGED, pre_eval_id="PID-C1",
               merge_sha=REAL_SHA, receipt=True)
        p_c1_before = precision_stats(stream_path=s_c1)
        expect("CRIT-1 baseline: committed clean fast-path success is 1/1",
               p_c1_before["n"] == 1 and abs(p_c1_before["precision"] - 1.0) < 1e-9)
        t2_c1_before = tier2_lookup(min_sample_count=1, stream_path=s_c1)
        expect("CRIT-1 baseline: committed clean cohort reads healthy",
               t2_c1_before.get("health") == "healthy" and t2_c1_before["n"] == 1)
        # Now append an OVERRIDING actual to the WORKING TREE ONLY (escalated:true). Under
        # the old working-tree reduce, last-writer-wins would flip precision to 0/1 and the
        # cohort to unhealthy. With the committed-blob reduce it must be INVISIBLE.
        append_actual("PID-C1", "RUN-C1", escalated=True, review_result="changes_requested",
                      test_result="fail", stream_path=s_c1)  # NOT committed
        # Sanity: the working tree really does carry the overriding (escalated) actual, so
        # the "unchanged precision" below is due to the committed-blob read, not a no-op.
        wt_reduced = _reduce_stream(s_c1)
        expect("CRIT-1: the working tree DOES carry the overriding escalated actual",
               wt_reduced["runs"][("PID-C1", "RUN-C1")]["actual"]["escalated"] is True)
        p_c1_after = precision_stats(stream_path=s_c1)
        expect("CRIT-1: an UNCOMMITTED appended actual does NOT change precision (still 1/1)",
               p_c1_after["n"] == 1 and abs(p_c1_after["precision"] - 1.0) < 1e-9
               and abs(p_c1_after["escalation_rate"] - 0.0) < 1e-9)
        t2_c1_after = tier2_lookup(min_sample_count=1, stream_path=s_c1)
        expect("CRIT-1: an uncommitted appended actual does NOT change Tier-2 (still healthy)",
               t2_c1_after.get("health") == "healthy" and t2_c1_after["n"] == 1)

        # ==================================================================== #
        # CRIT-2 (round 3) — triage's receipt check == validate-manifest's       #
        # verify_sealed_receipt. A receipt that is BOUND but NOT self-sealed     #
        # (no valid digest) must NOT count; only a FULLY-sealed one does.        #
        # ==================================================================== #
        s_c2seal = os.path.join(td, "r3-crit2", STREAM_BASENAME)
        append_predicted("PID-C2S", decision=FASTPATH_DECISION, stream_path=s_c2seal)
        bind_run("PID-C2S", "RUN-C2S", stream_path=s_c2seal)
        append_actual("PID-C2S", "RUN-C2S", escalated=False, review_result="approved",
                      test_result="pass", stream_path=s_c2seal)
        # committed MERGED + real merge SHA, but the receipt is BOUND yet UNSEALED (no valid
        # self-digest). The old verdict/run_id/pre_eval_id-only check would have accepted it;
        # the shared verify_sealed_receipt (schema + record_digest self-seal) must reject it.
        mk_run(exec_dir, "RUN-C2S", _PHASE_MERGED, pre_eval_id="PID-C2S",
               merge_sha=REAL_SHA, receipt=True, sealed_receipt=False)
        p_unsealed = precision_stats(stream_path=s_c2seal)
        expect("CRIT-2: a bound-but-UNSEALED receipt (no valid digest) is NOT counted",
               p_unsealed.get("status") == "insufficient" and p_unsealed["n"] == 0
               and p_unsealed["excluded_no_terminal_actual"] == 1)
        # Replace ONLY the receipt with a fully-sealed one (same run, same MERGED state, same
        # real SHA) and commit — now producer/validator/triage agree and it IS counted.
        with open(os.path.join(exec_dir, "RUN-C2S", "review", "receipt.json"),
                  "w", encoding="utf-8") as fh:
            json.dump(_sealed_receipt("RUN-C2S", "PID-C2S"), fh)
        _fx_commit_all(td)
        p_sealed = precision_stats(stream_path=s_c2seal)
        expect("CRIT-2: the SAME run with a fully-sealed committed receipt IS counted (1/1)",
               p_sealed["n"] == 1 and abs(p_sealed["precision"] - 1.0) < 1e-9)

    if failures:
        print("\nSELFTEST FAILED: %d case(s)" % len(failures))
        return 1
    print("\nSELFTEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
