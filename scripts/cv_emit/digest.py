"""The pinned diff digest, the manifest digest and the sealed patch."""

from __future__ import annotations

import os
import sys
import hashlib
import shutil
import subprocess
import tempfile

from .util import (
    INTEGRATION_GATE_DEFAULT, _git,
)


# --------------------------------------------------------------------------- #
# the PINNED diff digest
#
# Recipe taken verbatim from the `diff_digest` property description in
# schemas/job_result.schema.json, which pins it so a producer and the
# verification layer cannot diverge:
#
#   `git -C <gate-root> add -A` (which brings untracked files — the half a plain
#   `git diff` would miss — into the index), then sha256 over the raw bytes of
#   `git -C <gate-root> diff --cached --binary <baseline_commit>`, rendered as
#   `sha256:<64-hex>`.
#
# We PREFER to import compound-v-integration-gate.compute_diff_digest, so the
# producer is literally the verifier's own function — the same "one matcher, not
# two" argument the lane guard makes about the glob engine. The local copy is the
# fallback and is behaviourally identical: `add -A` runs against a COPY of the
# index under GIT_INDEX_FILE, so the index CONTENT the diff reads is the same
# while producing a receipt does not mutate the tree being gated.
# --------------------------------------------------------------------------- #
def _load_module_from_path(name, target):
    """Load a repo script by path, FROM SOURCE — never from a cache beside it.

    `sys.pycache_prefix` moves both the read and the write of the bytecode cache
    to a private directory outside the tree, so a forged
    `scripts/__pycache__/<mod>.<tag>.pyc` — an unchecked hash-based one, which
    CPython never validates against its source — cannot be executed in this
    process (fourth review pass, item 3, 2026-09-02). Returns None on any failure.

    IF THE PRIVATE PREFIX CANNOT BE CREATED, NOTHING IS LOADED. The first version
    caught the mkdtemp failure and carried on with the DEFAULT cache location —
    which is the in-tree `__pycache__` the redirect exists to avoid, so the one
    condition an attacker can arrange (a full or unwritable temp dir) turned the
    protection off and executed the planted `.pyc` anyway. A protection with a
    fallback to the unprotected path is not a protection; this refuses instead,
    and the caller degrades to its own local implementation.
    """
    prev_prefix = getattr(sys, "pycache_prefix", None)
    tmp_pycache = None
    try:
        import importlib.util
        try:
            tmp_pycache = tempfile.mkdtemp(prefix="cv-pycache-")
            sys.pycache_prefix = tmp_pycache
        except Exception:  # noqa: BLE001
            return None
        spec = importlib.util.spec_from_file_location(name, target)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:  # noqa: BLE001
        return None
    finally:
        try:
            sys.pycache_prefix = prev_prefix
        except Exception:  # noqa: BLE001
            pass
        if tmp_pycache:
            shutil.rmtree(tmp_pycache, ignore_errors=True)


# --------------------------------------------------------------------------- #
# the MANIFEST DIGEST
#
# The manifest declares every job's `write_allowed`. It also lives in the run
# directory, which the pipeline exempts BY NAME from the scope gate so a job's own
# bookkeeping does not read as an out-of-lane write. Put those two facts together
# and a job could widen its own lane map mid-run: every later check would run,
# pass, and prove nothing, because it would be checking against the widened list.
#
# `emit` therefore hashes the manifest at generation time and bakes the digest
# into the workflow script. Gate, Record, Finalize and the integration authority
# all carry it forward and refuse a manifest that no longer hashes to it. The lane
# map that is ENFORCED is provably the lane map that was reviewed.
# --------------------------------------------------------------------------- #
def sha256_file(path):
    """`sha256:<64hex>` of a file's raw bytes, or None when it cannot be read."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return "sha256:" + h.hexdigest()
    except (IOError, OSError):
        return None


def manifest_digest_fault(manifest_path, expected):
    """A refusal string when `manifest_path` does not hash to `expected`, else None.

    An absent `expected` is the documented backward-compatible path — a run
    emitted before 3.4.0, or a by-hand invocation. Every emitted command carries
    the digest, so the pipeline itself never takes that path.
    """
    if not expected:
        return None
    actual = sha256_file(manifest_path)
    if actual == expected:
        return None
    return (
        "manifest %s hashes to %s, not the %s this run was emitted against. The "
        "manifest declares every job's write_allowed, so a lane map that changed "
        "after emit is refused rather than enforced."
        % (manifest_path, actual, expected)
    )


# --------------------------------------------------------------------------- #
# the SEALED PATCH artifact
#
# The digest binds a receipt to a tree AT GATE TIME. Nothing used to bind the
# MERGE to that same tree: `merge_back` took a fresh `git diff` of the live
# worktree whenever the finalizer got round to it. Three real consequences, all
# reported by a cross-model review of 3.4.0:
#
#   * a worktree reverted to its baseline after the gate merged as "nothing to
#     do", was recorded as integrated, and was pruned — the work destroyed;
#   * `.pytest_cache/` and friends, written by the test floor that runs AFTER the
#     scope check, turned an honest pass into a `contradicted` refusal;
#   * any post-gate write to an in-lane file rode into the commit unmeasured.
#
# So the gate SEALS what it approved: `jobs/<id>.patch`, and its sha256 in the
# gate's receipt document. The finalizer applies THAT FILE. Nothing else.
# --------------------------------------------------------------------------- #
def patch_artifact_path(run_dir, job_id):
    return os.path.join(run_dir, "jobs", "%s.patch" % job_id)


def build_sealed_patch(root, baseline, paths):
    """(patch bytes, error) — `git diff --cached --binary <baseline> -- <paths>`.

    The `git add` runs against a COPY of the index under GIT_INDEX_FILE, exactly
    as the digest recipe does, so sealing a patch does not stage anything in the
    tree it is sealing. Only the paths the gate APPROVED are added, so a file the
    scope gate flagged — or a byproduct a later test writes — cannot be in the
    artifact, and therefore cannot be merged.
    """
    if not baseline:
        return None, "no baseline to seal against"
    rc, gitpath, err = _git(root, ["rev-parse", "--git-path", "index"])
    if rc != 0:
        return None, "cannot locate git index: %s" % (err.strip() or "rc=%d" % rc)
    index_path = gitpath.strip()
    if not os.path.isabs(index_path):
        index_path = os.path.join(root, index_path)
    tmpdir = tempfile.mkdtemp(prefix="cv-seal-idx-")
    try:
        tmp_index = os.path.join(tmpdir, "index")
        if os.path.exists(index_path):
            shutil.copyfile(index_path, tmp_index)
        env = {"GIT_INDEX_FILE": tmp_index}
        for path in paths:
            if not path:
                continue
            rc, _o, err = _git(root, ["add", "-A", "--", path], env=env)
            if rc != 0:
                # A deletion the worker already staged leaves nothing for the
                # pathspec to match; it is already in the copied index, so this is
                # not a failure. Same reasoning as `_stage_paths`.
                rc2, staged, _e = _git(
                    root, ["diff", "--cached", "--name-only", "--diff-filter=D",
                           "--", path], env=env)
                if not (rc2 == 0 and path in
                        [l.strip() for l in (staged or "").splitlines()]):
                    return None, "git add failed for %r while sealing: %s" % (
                        path, err.strip())
        args = ["diff", "--cached", "--binary", baseline, "--"]
        args += [p for p in paths if p]
        rc, blob, err = _git(root, args, env=env, text=False)
        if rc != 0:
            return None, "git diff --cached failed while sealing: %s" % err.strip()
        return blob, None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def sealed_post_image(repo_root, baseline, patch_bytes):
    """({path: blob-oid or None for a deletion}, error) — GIT'S answer, not ours.

    The patch is applied to a THROWAWAY index seeded from `baseline` (`git apply
    --cached` touches the index only, and GIT_INDEX_FILE keeps it off the real
    one), and the resulting blob ids are read back out. That is the exact content
    the artifact produces, derived by git from the artifact itself — so the
    post-merge proof needs nothing recorded by any party the pipeline constrains.
    """
    if not patch_bytes:
        return {}, None
    tmpdir = tempfile.mkdtemp(prefix="cv-postimg-")
    try:
        tmp_index = os.path.join(tmpdir, "index")
        env = {"GIT_INDEX_FILE": tmp_index}
        rc, _o, err = _git(repo_root, ["read-tree", baseline], env=env)
        if rc != 0:
            return None, "git read-tree %s failed: %s" % (baseline, err.strip())
        try:
            full_env = dict(os.environ)
            full_env["GIT_INDEX_FILE"] = tmp_index
            full_env["PYTHONDONTWRITEBYTECODE"] = "1"
            proc = subprocess.Popen(
                ["git", "-C", repo_root, "apply", "--cached", "--binary", "-"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, env=full_env,
            )
            _o, aerr = proc.communicate(patch_bytes)
            if proc.returncode != 0:
                return None, (
                    "the sealed patch does not apply to its own baseline: %s"
                    % aerr.decode("utf-8", "replace").strip()[:300])
        except Exception as exc:  # noqa: BLE001
            return None, "git apply --cached raised: %s" % exc
        rc, names, err = _git(
            repo_root, ["diff", "--cached", "--name-only", baseline], env=env)
        if rc != 0:
            return None, "git diff --cached --name-only failed: %s" % err.strip()
        image = {}
        for path in [n.strip() for n in (names or "").splitlines() if n.strip()]:
            rc2, staged, _e = _git(
                repo_root, ["ls-files", "--stage", "--", path], env=env)
            oid = None
            if rc2 == 0 and staged.strip():
                parts = staged.splitlines()[0].split("\t", 1)[0].split()
                if len(parts) >= 2:
                    oid = parts[1]
            image[path] = oid
        return image, None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def head_matches_post_image(repo_root, image):
    """(True, None) iff every path in `image` is in HEAD with that exact blob.

    This is the proof that the commit carries the artifact, and it is asked of
    git. `state.json` is a cache: it is written by the pipeline, it is exempt by
    name from the scope gate, and a worker can therefore set
    `merged.integrated: true` on a job that never landed. A cache may say a job is
    done; only git may be believed about it.
    """
    if image is None:
        return False, "no post-image to prove against"
    for path, oid in sorted(image.items()):
        rc, out, _err = _git(repo_root, ["rev-parse", "--verify", "HEAD:%s" % path])
        actual = out.strip() if rc == 0 else None
        if oid is None:
            if actual:
                return False, ("%s is still present in HEAD, but the sealed patch "
                               "deletes it" % path)
            continue
        if actual != oid:
            return False, ("%s in HEAD is %s, but the sealed patch produces %s"
                           % (path, actual or "absent", oid))
    return True, None


def _import_integration_gate(path=None):
    target = path or INTEGRATION_GATE_DEFAULT
    if not os.path.exists(target):
        return None
    return _load_module_from_path("cv_integration_gate", target)


def _compute_diff_digest_local(root, baseline):
    rc, gitpath, err = _git(root, ["rev-parse", "--git-path", "index"])
    if rc != 0:
        return None, "cannot locate git index: %s" % (err.strip() or "rc=%d" % rc)
    index_path = gitpath.strip()
    if not os.path.isabs(index_path):
        index_path = os.path.join(root, index_path)

    tmpdir = tempfile.mkdtemp(prefix="cv-emitwf-idx-")
    tmp_index = os.path.join(tmpdir, "index")
    try:
        if os.path.exists(index_path):
            shutil.copyfile(index_path, tmp_index)
        env = {"GIT_INDEX_FILE": tmp_index}
        rc, _, err = _git(root, ["add", "-A"], env=env, text=False)
        if rc != 0:
            return None, "git add -A failed: %s" % (err.strip() or "rc=%d" % rc)
        rc, blob, err = _git(
            root, ["diff", "--cached", "--binary", baseline], env=env, text=False
        )
        if rc != 0:
            return None, "git diff --cached failed: %s" % (err.strip() or "rc=%d" % rc)
        return "sha256:" + hashlib.sha256(blob).hexdigest(), None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# THE RUN DIRECTORY IS THE ONLY DIGEST EXCLUSION, on both sides of the seam.
#
# 3.4.0 development briefly excluded two tracked files by name as well
# (triage-outcomes.jsonl, worker-performance.jsonl), because the pipeline wrote
# them BETWEEN a direct-mode job's Gate and the authority's re-derivation and an
# honest receipt read as `contradicted`. The fourth review pass withdrew that: a
# path excluded from the digest is also a path a worker may rewrite unseen, and
# the pipeline commits triage-outcomes.jsonl by name. The ordering is fixed
# instead — `cmd_finalize_wave` appends the run's `actual` AFTER the authority
# has run over the wave, so nothing the pipeline writes lands inside that window
# and there is nothing left to forgive.


def compute_diff_digest(root, baseline, gate_module=None, exclude_prefixes=None):
    """Both sides of the seam MUST pass the same `exclude_prefixes`, or the gate and
    the authority compute different digests over the same tree and every honest
    direct-mode receipt reads as `forged` (dogfood 15)."""
    module = gate_module if gate_module is not None else _import_integration_gate()
    if module is not None and hasattr(module, "compute_diff_digest"):
        try:
            try:
                return module.compute_diff_digest(
                    root, baseline, exclude_prefixes=exclude_prefixes)
            except TypeError:
                # An older installed copy without the parameter: fall back rather
                # than crash, and accept that it will disagree — loudly, as
                # `forged`, which is at least a refusal and not a silent pass.
                return module.compute_diff_digest(root, baseline)
        except Exception as exc:  # noqa: BLE001
            return None, "integration-gate digest raised: %s" % exc
    return _compute_diff_digest_local(root, baseline)
