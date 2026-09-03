#!/usr/bin/env python3
"""
Compound V integration authority — the git-derived postcondition of spec D1.

WHY THIS EXISTS
---------------
A workflow ``Gate`` stage is an ``agent()`` call. Narrowing it with
``disallowedTools`` + ``bashCommandClamp`` limits what that agent CAN DO; it does
not limit what it RETURNS, and its structured-output schema proves the SHAPE of
the JSON, never that the scope check ever ran. The workflow script has no shell
of its own, so nothing inside the run can observe the check happening. A model
can therefore return a schema-valid ``verdict: "pass"`` having done nothing at
all.

So the workflow's gate is defence in depth and an early exit. THIS script is the
authority. It runs outside the workflow, in a real shell, over the real trees,
and it refuses integration until every job in the run resolves to a verdict it
derived or verified itself.

THE VERDICT TABLE
-----------------
Per job, exactly one of:

  pass           receipt present, every binding verified against the tree, and an
                 INDEPENDENT re-derivation agrees ⇒ this job may be integrated.
  blocked        a real scope violation — either a verified receipt saying so, or
                 one this script derived itself ⇒ integration refused.
  forged         a receipt that is PRESENT and well-formed but whose bindings
                 disagree with the tree (wrong baseline, wrong realised commit,
                 wrong digest, or internally inconsistent) ⇒ refused OUTRIGHT.
                 No re-derivation is attempted, deliberately: re-deriving would
                 reward a false claim with a second chance at a clean verdict.
  contradicted   bindings verify, but the receipt's own verdict disagrees with
                 the verdict this script derives from the same tree ⇒ refused.
                 Distinct from `forged` because the receipt is bound to the right
                 tree; the disagreement is about the CONCLUSION, and this script
                 does not need to prove intent to refuse.
  unverifiable   the job resolves to no tree this script can gate (worktree gone,
                 no recorded baseline for a direct job, git fault) ⇒ refused.
                 Fails CLOSED: an unknown is never a pass.

MISSING IS NOT INVALID, AND THAT DISTINCTION IS THE WHOLE DESIGN
----------------------------------------------------------------
A receipt that is absent, ``null``, or PARTIAL (any of the six fields missing,
empty or of the wrong type — the schema says "a partial receipt is a missing
receipt") is an HONEST ABSENCE. It is re-derived: this script runs
``compound-v-scope-check.py`` itself and the derived verdict is authoritative.
A clean re-derivation lets integration PROCEED — anything else deadlocks every
run whose jobs simply did not emit a receipt. A job that vanished entirely (an
Implement-stage throw drops its item to ``null`` and skips every later stage) is
the same case: missing, therefore re-derived, never silently passed.

A receipt that is present and well-formed but wrong is a different thing: a
forged claim. It is refused, not re-derived.

DIFF DIGEST — THE SEAM THAT MATTERS MOST
----------------------------------------
The recipe is PINNED in ``schemas/job_result.schema.json`` (the ``diff_digest``
property description), so a producer and this verification layer cannot diverge:

    git -C <gate-root> add -A
    sha256( raw bytes of: git -C <gate-root> diff --cached --binary <baseline> )
    rendered as  sha256:<64-hex>

If this script computed the digest any other way, every HONEST receipt would read
as forged and the release would refuse every run. It is implemented verbatim,
with one non-observable deviation: the ``add -A`` is performed against a COPY of
the index under ``GIT_INDEX_FILE`` so verifying a receipt does not mutate the
worktree it is verifying. The index CONTENT is identical either way, so the
resulting bytes — and therefore the digest — are identical.

Known limit of the pinned recipe, recorded rather than silently patched:
``git add -A`` honours ``.gitignore``, so a GITIGNORED write is not part of the
digest — while ``compound-v-scope-check.py`` DOES see ignored files. The digest
is a binding, not a complete content address of the violation surface. This is
why a verified receipt is still cross-checked against an independent
re-derivation instead of being trusted on the strength of the digest alone.

THE INDIRECT WRITER
-------------------
``hooks/lane-guard.sh`` matches ``Write``/``Edit``/``Bash`` and inspects the
command. It documents its own honest limit: a write laundered through
``python3 -c``, a build step, or any interpreter it cannot parse never reaches a
matcher it can decide on. Those writes are still in the tree, and git sees them.
This gate is the backstop that makes that limit acceptable.

USAGE
-----
    compound-v-integration-gate.py --run-dir docs/superpowers/execution/<run-id>
        [--repo-root DIR] [--manifest FILE] [--scope-check PATH]
        [--jobs id,id,...] [--quiet]
    compound-v-integration-gate.py --selftest

Exit codes: 0 = integration may proceed, 1 = integration REFUSED,
2 = usage / environment fault. (Same convention as the scope gate it calls.)

Python 3.9-safe, stdlib only (PyYAML is used when present, via the repo's
existing loader, which falls back to its own mini-parser).
"""

import os
import json
import subprocess
import tempfile
import shutil
import sys

# Nobody writes bytecode. The scope gate forgives no path by extension (fourth
# review pass, 2026-09-02), so a `__pycache__` entry this authority leaves beside
# a script is an out-of-lane write that BLOCKS the job it just judged. Set before
# ANY other import, and long before the importlib load of the scope-gate matcher
# below, which is exactly when a cache entry would otherwise be written.
sys.dont_write_bytecode = True


def _harden_sys_path():
    """Drop this script's own directory and the cwd from ``sys.path``.

    CPython puts the script's directory at ``sys.path[0]``, and this authority
    lives in ``scripts/`` — a directory a gated job may hold a write lane over. A
    job that writes ``scripts/yaml.py`` would otherwise have it imported HERE, by
    the `import yaml` in ``load_manifest``, and the manifest is the document that
    declares every job's ``write_allowed``. A shadowed loader could therefore
    hand this authority a WIDENED lane list and be judged compliant against it.
    The cwd (``''``) is removed for the same reason on ``-c``/``-m`` invocations.

    The scope matcher this file genuinely needs is loaded by explicit path, never
    by name, so removing these entries costs nothing.
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

import argparse  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402

HEX_COMMIT = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")
DIGEST = re.compile(r"^[a-z0-9]+:[0-9a-f]+$")
VERDICTS = ("pass", "blocked", "error")
EXIT_FOR_VERDICT = {"pass": 0, "blocked": 1, "error": 2}
RECEIPT_FIELDS = (
    "baseline_commit",
    "realised_commit",
    "diff_digest",
    "verdict",
    "raw_stdout",
    "exit_code",
)

# Verdict classes that permit integration. Everything else refuses.
CLEAN = ("pass",)


# --------------------------------------------------------------------------- #
# git helpers
# --------------------------------------------------------------------------- #
def _git_text(root, args):
    """``git -C root <args>`` → (rc, stdout, stderr) as text."""
    try:
        proc = subprocess.run(
            ["git", "-C", root] + list(args),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
    except OSError as exc:  # git missing / root unusable
        return 127, "", str(exc)
    return proc.returncode, proc.stdout, proc.stderr


def _is_ancestor(maybe_ancestor, descendant, root=None):
    """True iff ``maybe_ancestor`` is an ancestor of ``descendant`` in ``root``.

    `git merge-base --is-ancestor` exits 0 for yes, 1 for no, and something else
    for a real error. Only a clean 0 is a yes: an unknown commit or a broken repo
    must not be read as "the tree merely moved forward".
    """
    rc, _out, _err = _git_text(root or ".", ["merge-base", "--is-ancestor",
                                             maybe_ancestor, descendant])
    return rc == 0


def _git_bytes(root, args, env=None):
    """``git -C root <args>`` → (rc, stdout BYTES, stderr text).

    Bytes, not text: the digest is taken over the RAW bytes of a ``--binary``
    diff. Decoding it first would make the digest depend on the locale, and two
    machines would then disagree about an honest receipt.
    """
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    try:
        proc = subprocess.run(
            ["git", "-C", root] + list(args),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=full_env,
        )
    except OSError as exc:
        return 127, b"", str(exc)
    return proc.returncode, proc.stdout, proc.stderr.decode("utf-8", "replace")


def head_commit(root):
    """Full HEAD SHA of the tree at ``root``, or None."""
    rc, out, _ = _git_text(root, ["rev-parse", "HEAD"])
    if rc != 0:
        return None
    out = out.strip()
    return out or None


# THE RUN DIRECTORY IS THE ONLY DIGEST EXCLUSION, here and in the gate's twin
# (compound-v-emit-workflow.py). 3.4.0 development also excluded two tracked
# files by name, because the pipeline wrote them between a direct-mode job's
# Gate and this re-derivation and an honest receipt read as `contradicted`. The
# fourth review pass withdrew that: a path this authority does not digest is a
# path a worker may rewrite unseen, and the pipeline commits
# triage-outcomes.jsonl by name. The ordering was fixed instead — the wave
# finalizer appends the run's `actual` AFTER this authority has run — so the
# window those exclusions papered over no longer exists.


def compute_diff_digest(root, baseline, exclude_prefixes=None):
    """The PINNED recipe from schemas/job_result.schema.json (diff_digest).

    Returns (digest, error). ``add -A`` runs against a COPY of the index under
    GIT_INDEX_FILE: the index CONTENT is what the diff reads, so the bytes are
    identical to the literal recipe, but verifying a receipt no longer mutates
    the tree under verification.

    ``exclude_prefixes`` — repo-relative directory prefixes left OUT of the diff.
    It exists for one reason, found by dogfood 15: a `direct`-mode job's digest is
    taken over the whole tree, and the PIPELINE keeps writing into that tree after
    the gate has run. Record writes `results/<id>.json`, `receipts/<id>.gate.json`
    and `state.json` — all inside the run directory, all inside the measured tree —
    so the authority, recomputing later, could NEVER match the gate's digest and
    every honest direct-mode receipt read as `forged`.

    Excluding the run directory from BOTH sides makes them comparable again. It
    removes nothing a worker could hide behind: the run directory's contents are
    covered by the scope gate's own violation list and by the digest-bound
    exemption snapshot, and a worker writing anywhere ELSE is still in the diff.
    """
    rc, gitpath, err = _git_text(root, ["rev-parse", "--git-path", "index"])
    if rc != 0:
        return None, "cannot locate git index: %s" % (err.strip() or "rc=%d" % rc)
    index_path = gitpath.strip()
    if not os.path.isabs(index_path):
        index_path = os.path.join(root, index_path)

    tmpdir = tempfile.mkdtemp(prefix="cv-intgate-idx-")
    tmp_index = os.path.join(tmpdir, "index")
    try:
        if os.path.exists(index_path):
            shutil.copyfile(index_path, tmp_index)
        env = {"GIT_INDEX_FILE": tmp_index}

        rc, _, err = _git_bytes(root, ["add", "-A"], env=env)
        if rc != 0:
            return None, "git add -A failed: %s" % (err.strip() or "rc=%d" % rc)

        args = ["diff", "--cached", "--binary", baseline]
        prefixes = [p for p in (exclude_prefixes or []) if str(p or "").strip()]
        if prefixes:
            # Pathspec exclusion, after `--`, so a prefix that looks like a flag
            # cannot be read as one.
            args.append("--")
            args.append(".")
            for p in prefixes:
                p = str(p).strip().rstrip("/")
                # A directory prefix is excluded with /**; an entry naming an
                # existing FILE (the pipeline's bookkeeping) is excluded exactly.
                if os.path.isfile(os.path.join(root, p)):
                    args.append(":(exclude)%s" % p)
                else:
                    args.append(":(exclude)%s/**" % p)
        rc, blob, err = _git_bytes(root, args, env=env)
        if rc != 0:
            return None, "git diff --cached failed: %s" % (
                err.strip() or "rc=%d" % rc
            )
        return "sha256:" + hashlib.sha256(blob).hexdigest(), None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# --------------------------------------------------------------------------- #
# manifest / state / results loading
# --------------------------------------------------------------------------- #
def load_manifest(path):
    """Load a Compound V manifest, reusing the repo's existing YAML loader.

    ``compound-v-validate-manifest.py`` already resolves PyYAML-or-mini-parser.
    Importing it is the same rule task-15 follows for the scope-gate matcher:
    one parser, not two that can disagree.
    """
    with open(path, "r") as fh:
        text = fh.read()
    try:
        import yaml  # noqa: WPS433 (intentional optional dep)

        return yaml.safe_load(text)
    except ImportError:
        pass
    here = os.path.dirname(os.path.abspath(__file__))
    validator = os.path.join(here, "compound-v-validate-manifest.py")
    if not os.path.exists(validator):
        raise RuntimeError(
            "PyYAML is absent and %s (its fallback loader) is missing" % validator
        )
    import importlib.util

    spec = importlib.util.spec_from_file_location("_cv_validate_manifest", validator)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.load_yaml(text)


def load_json(path):
    """Read a JSON file → (obj, error). A malformed file is an error, not {}."""
    try:
        with open(path, "r") as fh:
            return json.load(fh), None
    except (IOError, OSError) as exc:
        return None, str(exc)
    except ValueError as exc:
        return None, "malformed JSON: %s" % exc


def result_files_for(results_dir, job_id):
    """(primary, extras) result files for one job.

    ``<id>.json`` is the primary; ``<id>.<anything>.json`` is an EXTRA attempt.
    Job ids never contain a dot, so the split is unambiguous — and it is the
    only way to notice a job carrying MORE than one receipt, which D1 forbids
    ("exactly one gate receipt").
    """
    primary = None
    extras = []
    if not os.path.isdir(results_dir):
        return None, []
    for name in sorted(os.listdir(results_dir)):
        if not name.endswith(".json"):
            continue
        stem = name[: -len(".json")]
        if stem == job_id:
            primary = os.path.join(results_dir, name)
        elif stem.startswith(job_id + "."):
            extras.append(os.path.join(results_dir, name))
    return primary, extras


# --------------------------------------------------------------------------- #
# receipt structure
# --------------------------------------------------------------------------- #
def receipt_is_missing(receipt):
    """True when the receipt is absent / null / PARTIAL.

    The schema is explicit: "Emit the object only when all six fields are
    genuinely known; a partial receipt is a missing receipt." A structurally
    broken receipt is therefore an ABSENCE (re-derived), not a forgery
    (refused): a producer that could not observe a field and said so is being
    honest, and punishing that would push producers toward inventing values.
    """
    if receipt is None or not isinstance(receipt, dict):
        return True
    for field in RECEIPT_FIELDS:
        if field not in receipt:
            return True
        val = receipt[field]
        if val is None:
            return True
        if field == "exit_code":
            if not isinstance(val, int) or isinstance(val, bool):
                return True
        else:
            if not isinstance(val, str) or val == "":
                return True
    # Values present but not even the right SHAPE: still an incomplete receipt
    # rather than a claim about the tree.
    if not HEX_COMMIT.match(receipt["baseline_commit"]):
        return True
    if not HEX_COMMIT.match(receipt["realised_commit"]):
        return True
    if not DIGEST.match(receipt["diff_digest"]):
        return True
    if receipt["verdict"] not in VERDICTS:
        return True
    return False


def load_scope_matcher(scope_check):
    """(``is_allowed`` callable, error) — the scope gate's OWN matcher, from source.

    A verifier that matches differently from the gate is a verifier that can
    disagree with it for reasons neither of them is about, so the matcher is
    never reimplemented here; it is loaded out of
    ``scripts/compound-v-scope-check.py`` itself.

    It is loaded FROM SOURCE, never from a cache beside it. A forged
    ``scripts/__pycache__/compound-v-scope-check.<tag>.pyc`` — an unchecked
    hash-based one, which CPython never validates against its source — would
    otherwise execute HERE, in this process, and could hand back an
    ``is_allowed`` that returns True for every path. ``sys.pycache_prefix`` moves
    both the read and the write of that cache to a private directory outside the
    tree.

    AND IF THAT PRIVATE DIRECTORY CANNOT BE CREATED, NOTHING IS LOADED. The first
    version swallowed the mkdtemp failure and executed the module under the
    DEFAULT cache location — the in-tree ``__pycache__`` the redirect exists to
    avoid. A full or unwritable temp dir is a condition an attacker can arrange,
    so the protection had an off switch. This fails closed with a reason instead.
    """
    prev_prefix = getattr(sys, "pycache_prefix", None)
    tmp_pycache = None
    module = None
    try:
        import importlib.util as _ilu
        try:
            tmp_pycache = tempfile.mkdtemp(prefix="cv-pycache-")
            sys.pycache_prefix = tmp_pycache
        except Exception as exc:  # noqa: BLE001
            return None, (
                "refusing to import the scope matcher without a private bytecode "
                "cache (%s): the default cache is the in-tree __pycache__ a forged "
                ".pyc would be planted in" % exc
            )
        spec = _ilu.spec_from_file_location("cv_scope_check", scope_check)
        if not (spec and spec.loader):
            return None, "no import spec for %s" % scope_check
        module = _ilu.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001
        return None, "loading %s raised: %s" % (scope_check, exc)
    finally:
        try:
            sys.pycache_prefix = prev_prefix
        except Exception:  # noqa: BLE001
            pass
        if tmp_pycache:
            shutil.rmtree(tmp_pycache, ignore_errors=True)
    fn = getattr(module, "is_allowed", None)
    if not callable(fn):
        return None, "%s defines no is_allowed()" % scope_check
    return fn, None


# --------------------------------------------------------------------------- #
# the SEALED PATCH artifact
#
# A digest binds a receipt to a tree at gate time. It does not stop that tree
# from moving afterwards, and the merge used to take a FRESH diff of the live
# worktree — so whatever the tree said at merge time is what landed, gate or no
# gate. Three real shapes came out of that: a worktree reverted to baseline
# merged as "nothing to do" and was pruned; test byproducts written after the
# gate turned an honest pass into a `contradicted`; and any post-gate write to an
# in-lane file rode into the commit unmeasured.
#
# So the gate SEALS what it approved: `jobs/<id>.patch`, the binary diff of the
# approved paths against the pinned baseline, with its sha256 recorded in the
# gate's receipt document. The authority validates the artifact against that
# digest, and the finalizer applies THAT ARTIFACT — never a fresh diff.
# --------------------------------------------------------------------------- #
def patch_artifact_path(run_dir, job_id):
    return os.path.join(run_dir, "jobs", "%s.patch" % job_id)


def sha256_file(path):
    """``sha256:<64hex>`` of a file's raw bytes, or None when it cannot be read."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return "sha256:" + h.hexdigest()
    except (IOError, OSError):
        return None


def gate_receipt_document(run_dir, job_id):
    """``receipts/<id>.gate.json`` — the gate's own document, or None.

    The six-field ``gate_receipt`` inside ``results/<id>.json`` is pinned by
    ``schemas/job_result.schema.json`` with ``additionalProperties: false``, so
    the sealed-patch digest cannot live there. It lives in the gate's receipt
    document, and the two are BOUND: the authority refuses a pair that disagrees
    about the diff digest or the baseline, which is what stops a rewritten
    receipt document from sealing content the result never claimed.
    """
    doc, _err = load_json(os.path.join(run_dir, "receipts", "%s.gate.json" % job_id))
    return doc if isinstance(doc, dict) else None


def _read_json_file(path):
    """A JSON document or None — never an exception, the caller decides."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
        return doc if isinstance(doc, dict) else None
    except Exception:  # noqa: BLE001
        return None


def sealed_post_image(repo_root, baseline, patch_bytes):
    """({path: blob-oid or None for a deletion}, error) — git's answer for the
    sealed patch applied to its own baseline in a THROWAWAY index. Twin of the
    emitter's function of the same name; the authority never imports the
    emitter, so the proof it computes cannot be steered by the code it judges."""
    if not patch_bytes:
        return {}, None
    tmpdir = tempfile.mkdtemp(prefix="cv-auth-postimg-")
    try:
        tmp_index = os.path.join(tmpdir, "index")
        env = dict(os.environ)
        env["GIT_INDEX_FILE"] = tmp_index
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        r = subprocess.run(["git", "-C", repo_root, "read-tree", baseline],
                           capture_output=True, text=True, env=env)
        if r.returncode != 0:
            return None, "git read-tree %s failed: %s" % (baseline, r.stderr.strip())
        proc = subprocess.Popen(["git", "-C", repo_root, "apply", "--cached", "--binary", "-"],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=env)
        _o, aerr = proc.communicate(patch_bytes)
        if proc.returncode != 0:
            return None, ("the sealed patch does not apply to its own baseline: %s"
                          % aerr.decode("utf-8", "replace").strip()[:300])
        r = subprocess.run(["git", "-C", repo_root, "diff", "--cached", "--name-only", baseline],
                           capture_output=True, text=True, env=env)
        if r.returncode != 0:
            return None, "git diff --cached --name-only failed: %s" % r.stderr.strip()
        image = {}
        for path in [n.strip() for n in r.stdout.splitlines() if n.strip()]:
            r2 = subprocess.run(["git", "-C", repo_root, "ls-files", "--stage", "--", path],
                                capture_output=True, text=True, env=env)
            oid = None
            if r2.returncode == 0 and r2.stdout.strip():
                parts = r2.stdout.splitlines()[0].split("\t", 1)[0].split()
                if len(parts) >= 2:
                    oid = parts[1]
            image[path] = oid
        return image, None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def head_matches_post_image(repo_root, image):
    """(True, None) iff every path in `image` is in HEAD with exactly that blob."""
    if image is None:
        return False, "no post-image to prove against"
    for path, oid in sorted(image.items()):
        r = subprocess.run(["git", "-C", repo_root, "rev-parse", "--verify", "HEAD:%s" % path],
                           capture_output=True, text=True)
        actual = r.stdout.strip() if r.returncode == 0 else None
        if oid is None:
            if actual:
                return False, "%s is still present in HEAD, but the sealed patch deletes it" % path
            continue
        if actual != oid:
            return False, ("%s in HEAD is %s, but the sealed patch produces %s"
                           % (path, actual or "absent", oid))
    return True, None


def sealed_patch_faults(run_dir, job_id, receipt, gate_doc):
    """(faults, sealed_digest). Empty faults + a digest ⇒ a validated artifact.

    A gate document that records no ``patch_sha256`` is an OLDER receipt, from
    before sealing existed: no artifact is required and none is trusted. A gate
    document that DOES record one must be backed by a file that hashes to it.
    """
    if not isinstance(gate_doc, dict):
        return [], None
    declared = gate_doc.get("patch_sha256")
    if not (isinstance(declared, str) and DIGEST.match(declared or "")):
        return [], None
    faults = []
    for field in ("diff_digest", "baseline_commit"):
        theirs, ours = gate_doc.get(field), receipt.get(field)
        if theirs and ours and theirs != ours:
            faults.append(
                "sealed patch: receipts/%s.gate.json reports %s %s but the result's "
                "receipt claims %s — the two halves of one receipt disagree"
                % (job_id, field, theirs, ours)
            )
    path = patch_artifact_path(run_dir, job_id)
    if not os.path.isfile(path):
        faults.append(
            "sealed patch: the receipt records patch_sha256 %s but jobs/%s.patch is "
            "missing — the merge applies that artifact, so an absent one is refused "
            "rather than replaced by a fresh diff of a tree that has moved"
            % (declared, job_id)
        )
        return faults, None
    actual = sha256_file(path)
    if actual != declared:
        faults.append(
            "sealed patch: jobs/%s.patch hashes to %s, not the %s the receipt "
            "records — the artifact was replaced after the gate sealed it"
            % (job_id, actual, declared)
        )
        return faults, None
    return faults, declared


def patch_paths(patch_bytes):
    """Repo-relative paths a `git diff --binary` patch touches, best effort."""
    paths = []
    for line in (patch_bytes or b"").splitlines():
        if not line.startswith(b"+++ ") and not line.startswith(b"--- "):
            continue
        raw = line[4:].strip()
        if raw == b"/dev/null":
            continue
        try:
            text = raw.decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            continue
        if text.startswith(("a/", "b/")):
            text = text[2:]
        if text and text not in paths:
            paths.append(text)
    return paths


def head_moved_under_job(receipt, observed_head, root=None):
    """True iff the ONLY thing wrong is that the tree's HEAD advanced past the
    commit this job was measured at — a `stale` receipt, not a forged one.

    Dogfood 2c (2026-09-02) produced exactly this, and the run reported FORGED. The
    cause was mundane: a human committed to the repository while a `direct`-mode job
    was in flight, so HEAD moved under it. Nothing was forged; the ground truth
    moved. `forged` is the authority's accusation of tampering, and spending it on
    an ordinary race sends whoever reads it hunting a forgery that never happened —
    the same mistake 3.0.4 corrected when a no-work refusal was dressed as one.

    The distinction is decidable: the receipt's realised_commit must be an ANCESTOR
    of the observed HEAD. An ancestor means the tree moved forward past a real
    commit the job was measured at. A non-ancestor means the receipt names a commit
    on no path to HEAD, which is not a race — that stays `forged`.
    """
    realised = receipt.get("realised_commit")
    if not (realised and observed_head) or realised == observed_head:
        return False
    return _is_ancestor(realised, observed_head, root)


def receipt_binding_faults(receipt, pinned_baseline, observed_head, observed_digest):
    """Reasons this PRESENT, well-formed receipt disagrees with the tree.

    A non-empty list ⇒ `forged`: refused outright, with NO re-derivation — UNLESS
    `head_moved_under_job` says the tree simply advanced, in which case the caller
    reports `stale`. Both refuse; only the word and the remedy differ.
    """
    faults = []
    if pinned_baseline and receipt["baseline_commit"] != pinned_baseline:
        faults.append(
            "baseline_commit %s is not the run's recorded pre-dispatch baseline %s"
            % (receipt["baseline_commit"], pinned_baseline)
        )
    if observed_head and receipt["realised_commit"] != observed_head:
        faults.append(
            "realised_commit %s is not the tree's HEAD at gate time %s"
            % (receipt["realised_commit"], observed_head)
        )
    if observed_digest and receipt["diff_digest"] != observed_digest:
        faults.append(
            "diff_digest %s does not match the tree's recomputed digest %s"
            % (receipt["diff_digest"], observed_digest)
        )
    expected_exit = EXIT_FOR_VERDICT[receipt["verdict"]]
    if receipt["exit_code"] != expected_exit:
        faults.append(
            "exit_code %d contradicts verdict %r (the gate exits %d for it)"
            % (receipt["exit_code"], receipt["verdict"], expected_exit)
        )
    # raw_stdout is the gate's literal verdict document. If it parses as JSON its
    # verdict must be the one copied into the receipt; a receipt whose evidence
    # says something else is not evidence.
    #
    # _leading_json, not a bare json.loads: on a BLOCKED verdict the scope gate
    # prints its JSON and THEN a human "BLOCKED: n file(s)…" tail on the same
    # stream. A bare parse fails on that tail, and every HONEST blocked receipt
    # would then be reported as forged — the exact producer/verifier divergence
    # this whole seam exists to prevent. Caught by tests/test-integration-gate.sh.
    try:
        doc = json.loads(_leading_json(receipt["raw_stdout"]))
    except (ValueError, TypeError):
        doc = None
    if isinstance(doc, dict) and "verdict" in doc:
        if doc["verdict"] != receipt["verdict"]:
            faults.append(
                "raw_stdout reports verdict %r but the receipt claims %r"
                % (doc["verdict"], receipt["verdict"])
            )
    elif receipt["verdict"] != "error":
        # `error` is the one case the gate may emit on stderr / non-JSON.
        faults.append("raw_stdout is not the gate's JSON verdict document")
    return faults


# --------------------------------------------------------------------------- #
# re-derivation
# --------------------------------------------------------------------------- #
def run_scope_check(scope_check, mode, root, baseline, allow, preexisting=None):
    """Invoke scripts/compound-v-scope-check.py as a SUBPROCESS.

    A subprocess, not an import: this script must not be able to perturb the
    matcher it is checking against, and the matcher belongs to another lane.
    Returns (verdict, stdout, exit_code, error).
    """
    cmd = [sys.executable, scope_check]
    cmd += ["--worktree" if mode == "worktree" else "--repo", root]
    if baseline:
        cmd += ["--baseline", baseline]
    for glob in allow:
        cmd += ["--allow", glob]
    if preexisting:
        cmd += ["--preexisting", preexisting]
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
    except OSError as exc:
        return None, "", None, "cannot run scope gate: %s" % exc

    raw = proc.stdout or proc.stderr
    verdict = None
    for chunk in (proc.stdout, proc.stderr):
        if not chunk:
            continue
        try:
            doc = json.loads(_leading_json(chunk))
        except (ValueError, TypeError):
            continue
        if isinstance(doc, dict) and doc.get("verdict") in VERDICTS:
            verdict = doc["verdict"]
            raw = chunk
            break
    if verdict is None:
        # Fall back to the exit code, which is the gate's other contract.
        verdict = {0: "pass", 1: "blocked"}.get(proc.returncode, "error")
    return verdict, raw, proc.returncode, None


def _leading_json(text):
    """The first balanced JSON object embedded in ``text``.

    The scope gate prints an indented JSON verdict on stdout and, when blocked, a
    human 'BLOCKED: …' tail on STDERR. A producer that captures the two streams
    together (``2>&1``) gets both — and because stdout is block-buffered when it
    is a pipe while stderr is not, the tail routinely arrives BEFORE the JSON.
    So the document has to be located, not merely truncated: skipping the tail
    only when it comes last would still read every honest blocked receipt from a
    ``2>&1`` producer as forged. Observed, not hypothesised — this is what
    tests/test-integration-gate.sh reproduced.
    """
    start = text.find("{")
    if start < 0:
        return text
    text = text[start:]
    depth = 0
    in_str = False
    esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[: i + 1]
    return text


# --------------------------------------------------------------------------- #
# per-job evaluation
# --------------------------------------------------------------------------- #
def evaluate_job(job, state_job, run_dir, repo_root, scope_check):
    """Resolve one job to exactly one verdict class. Never raises."""
    job_id = job.get("id") or "<unnamed>"
    out = {
        "job": job_id,
        "verdict": None,
        "receipt": None,
        "reasons": [],
        "notes": [],
        "gate_root": None,
        "mode": None,
        "baseline": None,
        "violations": [],
    }
    state_job = state_job or {}

    allow = job.get("write_allowed") or []
    if not isinstance(allow, list):
        out["verdict"] = "unverifiable"
        out["reasons"].append("manifest write_allowed is not a list")
        return out

    # ---- result file(s) ---------------------------------------------------- #
    results_dir = os.path.join(run_dir, "results")
    primary, extras = result_files_for(results_dir, job_id)
    if extras:
        out["verdict"] = "forged"
        out["receipt"] = "duplicate"
        out["reasons"].append(
            "D1 requires EXACTLY ONE receipt per job; found %d extra result file(s): %s"
            % (len(extras), ", ".join(os.path.basename(p) for p in extras))
        )
        return out

    result = None
    if primary:
        result, err = load_json(primary)
        if err:
            out["notes"].append("result unreadable (%s) — treated as missing" % err)
            result = None
    else:
        out["notes"].append("no results/%s.json — job produced no result" % job_id)

    receipt = None
    if isinstance(result, dict):
        receipt = result.get("gate_receipt")

    # ---- where do we gate? ------------------------------------------------- #
    worktree = None
    for candidate in (
        (result or {}).get("worktree"),
        state_job.get("worktree"),
    ):
        if isinstance(candidate, str) and candidate.strip():
            worktree = candidate.strip()
            break

    if worktree:
        mode, gate_root = "worktree", worktree
    else:
        mode, gate_root = "direct", repo_root
    out["mode"] = mode
    out["gate_root"] = gate_root

    if not os.path.isdir(gate_root):
        # ALREADY MERGED IS NOT UNVERIFIABLE. Since 3.3.0 the wave finalizer
        # retires the worktree of every job it merged, so re-running this authority
        # over a finished run finds the gate root gone — and called it
        # `unverifiable`, which reads as "we could not check this" rather than "this
        # was checked, passed, merged and committed, and its scratch tree was tidied
        # up afterwards". Dogfood 15 produced exactly that on a re-verification.
        #
        # The state file is the evidence, and it is specific: the job must be
        # recorded merged AND integrated AND carry the commit it landed in. That
        # combination is written only by a finalizer that already ran this authority
        # over the job and got a pass, so this is not a shortcut around the check —
        # it is the record OF the check.
        # A RECORDED MERGE IS A CLAIM, NOT A PROOF — and this branch treated it as
        # one. A cross-model review pointed out that `state.json` is exempt by name
        # and writable by a direct worker, so any truthy `integrated` + `commit`
        # bought a `pass` BEFORE receipt, baseline, digest, result or scope were
        # checked. The commit did not even have to exist.
        #
        # It must still exist, be reachable from HEAD, and actually contain this
        # job's declared lanes — three things a worker cannot fabricate by editing a
        # JSON file, because they are git's answer and not ours. Anything less is
        # `unverifiable`: the honest word for "the tree that would prove this is
        # gone".
        _m = (state_job or {}).get("merged") or {}
        _commit = str(_m.get("commit") or "").strip()
        if _m.get("integrated") and re.match(r"^[0-9a-f]{7,40}$", _commit):
            rc_e, _o, _e = _git_text(repo_root, ["cat-file", "-e", _commit + "^{commit}"])
            rc_a, _o2, _e2 = _git_text(repo_root, ["merge-base", "--is-ancestor",
                                                   _commit, "HEAD"])
            touched = set()
            if rc_e == 0:
                rc_s, out_s, _ = _git_text(
                    repo_root, ["show", "--name-only", "--pretty=format:", _commit])
                if rc_s == 0:
                    touched = {p.strip() for p in out_s.splitlines() if p.strip()}
            # PROOF, NOT OVERLAP (ninth review pass, item 1; Codex round 4 H4).
            # A commit that exists, is an ancestor of HEAD and touches one of this
            # job's lanes is still not proof that THIS job's patch is in HEAD — a
            # decoy commit touching an in-lane file satisfied that test while the
            # sealed patch sat unread. The only proof is the artifact the gate
            # sealed: apply it to its own baseline, read back the blobs git
            # produces, and require HEAD to carry exactly those blobs. No sealed
            # patch (a pre-3.4.0 receipt) ⇒ unverifiable, never pass.
            _gate_doc = _read_json_file(os.path.join(run_dir, "receipts",
                                                     "%s.gate.json" % job.get("id", "")))
            _result_doc = _read_json_file(os.path.join(run_dir, "results",
                                                       "%s.json" % job.get("id", "")))
            _receipt = ((_result_doc or {}).get("gate_receipt") or _gate_doc or {})
            _faults, _sealed = sealed_patch_faults(run_dir, job.get("id", ""),
                                                   _receipt, _gate_doc or {})
            _proved, _why = False, None
            if _faults:
                _why = "; ".join(_faults)
            elif not _sealed:
                _why = ("no sealed patch was recorded for this job (a receipt from "
                        "before sealing), so the commit cannot be proven to carry it — "
                        "pathname overlap is not proof")
            else:
                _baseline = (state_job.get("baseline") or (_gate_doc or {}).get("baseline_commit")
                             or _receipt.get("baseline_commit") or "")
                try:
                    with open(patch_artifact_path(run_dir, job.get("id", "")), "rb") as _fh:
                        _patch_bytes = _fh.read()
                except OSError as _exc:
                    _patch_bytes, _why = None, "cannot read the sealed patch: %s" % _exc
                if _patch_bytes is not None:
                    _image, _ierr = sealed_post_image(repo_root, _baseline, _patch_bytes)
                    if _ierr:
                        _why = _ierr
                    else:
                        _proved, _why = head_matches_post_image(repo_root, _image)
            if rc_e == 0 and rc_a == 0 and _proved:
                out["verdict"] = "pass"
                out["receipt"] = "merged"
                out["notes"].append(
                    "gate root is gone because this job was merged as %s, which EXISTS, "
                    "is an ancestor of HEAD, and HEAD carries exactly the blobs the "
                    "sealed patch %s produces — proven from git and the artifact, not "
                    "from state.json or a pathname" % (_commit[:12], _sealed[:19])
                )
                return out
            out["verdict"] = "unverifiable"
            out["reasons"].append(
                "state.json claims this job merged as %s but that is not proven "
                "(exists=%s ancestor-of-HEAD=%s sealed-patch-in-HEAD=%s%s). A recorded "
                "merge is a claim; state.json is writable by a direct worker, and a "
                "commit touching a lane is overlap, not proof."
                % (_commit[:12] or "?", rc_e == 0, rc_a == 0, _proved,
                   (": " + _why) if _why else "")
            )
            return out
        out["verdict"] = "unverifiable"
        out["reasons"].append(
            "gate root %s does not exist — nothing to derive a verdict from "
            "(fails closed; an unknown is never a pass)" % gate_root
        )
        return out
    if _git_text(gate_root, ["rev-parse", "--git-dir"])[0] != 0:
        out["verdict"] = "unverifiable"
        out["reasons"].append("gate root %s is not a git tree" % gate_root)
        return out

    # ---- the baseline ------------------------------------------------------ #
    pinned = state_job.get("baseline")
    if not (isinstance(pinned, str) and HEX_COMMIT.match(pinned.strip() or "")):
        pinned = None
    complete_receipt = not receipt_is_missing(receipt)
    baseline = pinned
    if baseline is None:
        if complete_receipt:
            # No pinned baseline, but a complete receipt names one. Use THAT for
            # both the digest and the re-derivation: computing the two against
            # different references would manufacture disagreements out of nothing.
            # It is weaker than a pinned SHA — the receipt's producer chose it —
            # so it is recorded, never passed off as equivalent.
            baseline = receipt["baseline_commit"]
            out["notes"].append(
                "state.json pins no baseline for this job; verifying against the "
                "receipt's own claimed baseline_commit, which its producer chose"
            )
        elif mode == "worktree":
            # The gate's own documented default: a worktree is created fresh at
            # HEAD. Weaker than a pinned SHA (a worker that COMMITS moves HEAD),
            # so it is recorded as a note, never passed off as equivalent.
            baseline = head_commit(gate_root)
            out["notes"].append(
                "state.json records no pinned baseline for this job; falling back "
                "to the worktree HEAD, which a worker that commits can move"
            )
        if baseline is None:
            out["verdict"] = "unverifiable"
            out["reasons"].append(
                "no recorded pre-dispatch baseline for a %s job — the scope gate "
                "cannot be run without one" % mode
            )
            return out
    out["baseline"] = baseline

    # THE SAME LIST THE GATE USED, which is the `.verified.txt` the gate WROTE —
    # not the raw `<id>.txt` it was derived from.
    #
    # The raw file is the digest-bound record. The gate turns it into the actual
    # exemption set: it drops entries whose bytes moved, adds the pipeline files
    # that are exempt by name, and adds itself. Re-deriving here from the RAW file
    # gave the authority a different exemption set than the gate had, so the two
    # reached different conclusions about the same tree — reported as
    # `contradicted`, which is the verdict for exactly that, arrived at for a reason
    # that was ours rather than the worker's. Dogfood 19, on a deliberately quiet
    # tree, with nothing else left to blame.
    #
    # Falling back to the raw file keeps an older run verifiable; it will simply be
    # stricter, which is the safe direction.
    preexisting = os.path.join(run_dir, "preexisting", "%s.verified.txt" % job_id)
    if not os.path.isfile(preexisting):
        preexisting = os.path.join(run_dir, "preexisting", "%s.txt" % job_id)
    if not os.path.isfile(preexisting):
        preexisting = None

    # ---- MISSING ⇒ re-derive ---------------------------------------------- #
    if not complete_receipt:
        out["receipt"] = "missing"
        if receipt is not None and isinstance(receipt, dict):
            out["notes"].append(
                "a PARTIAL receipt is a missing receipt (schema), so this is "
                "re-derived rather than refused"
            )
        verdict, raw, code, err = run_scope_check(
            scope_check, mode, gate_root, baseline, allow, preexisting
        )
        if err:
            out["verdict"] = "unverifiable"
            out["reasons"].append(err)
            return out
        out["derived"] = {"verdict": verdict, "exit_code": code}
        out["violations"] = _violations_of(raw)
        if verdict == "pass":
            out["verdict"] = "pass"
            out["notes"].append(
                "receipt absent; re-derived CLEAN — integration proceeds "
                "(a missing receipt must not deadlock an honest run)"
            )
        elif verdict == "blocked":
            out["verdict"] = "blocked"
            out["reasons"].append(
                "re-derived from git: %d path(s) written outside write_allowed"
                % len(out["violations"])
            )
        else:
            out["verdict"] = "unverifiable"
            out["reasons"].append(
                "the scope gate itself errored (%s) — fails closed" % (raw or "")[:200]
            )
        return out

    # ---- PRESENT ⇒ verify bindings BEFORE anything else -------------------- #
    out["receipt"] = "present"
    observed_head = head_commit(gate_root)
    # THE SAME EXCLUSION THE GATE USED. A direct job's run directory is inside the
    # tree being digested and the pipeline writes into it between the gate and this
    # point, so without this the two digests can never agree and an honest receipt
    # is refused as forged. Worktree jobs exclude nothing: their run directory is
    # outside the worktree entirely. And the run directory is ALL that is excluded
    # — see the note beside compute_diff_digest.
    _excl = None
    if mode != "worktree":
        _r = os.path.relpath(os.path.abspath(run_dir), os.path.abspath(gate_root))
        if not _r.startswith(".." + os.sep):
            _excl = [_r.replace(os.sep, "/")]
    observed_digest, digest_err = compute_diff_digest(gate_root, baseline,
                                                      exclude_prefixes=_excl)
    if digest_err:
        out["verdict"] = "unverifiable"
        out["reasons"].append("cannot recompute diff_digest: %s" % digest_err)
        return out

    faults = receipt_binding_faults(receipt, pinned, observed_head, observed_digest)
    # THE SEALED ARTIFACT IS PART OF THE RECEIPT, and it is checked here so a
    # missing or replaced one refuses on the same path a wrong digest does. It is
    # appended AFTER the binding faults deliberately: a sealed-patch fault does
    # not start with `realised_commit ` or `diff_digest `, so it can never be
    # excused by the stale/race branch below.
    _gate_doc = gate_receipt_document(run_dir, job_id)
    _seal_faults, _sealed = sealed_patch_faults(run_dir, job_id, receipt, _gate_doc)
    faults = faults + _seal_faults
    if _sealed:
        out["sealed_patch"] = _sealed
    if faults:
        # Refused OUTRIGHT. No re-derivation: a present-but-wrong receipt is a
        # forged claim, and re-deriving would hand it a second chance at clean.
        #
        # STALE IS NOT FORGED (3.3.0). If the receipt's realised_commit is an
        # ANCESTOR of the observed HEAD, the tree simply advanced past the commit
        # this job was measured at — someone committed while a `direct`-mode job
        # was in flight. Dogfood 2c produced exactly that and the run said FORGED,
        # which is an accusation of tampering spent on an ordinary race. Both
        # verdicts refuse and neither re-derives; only the word and the remedy
        # differ, and the remedy matters: re-run the job, do not go hunting a
        # forgery that never happened.
        # STALE ONLY WHEN THE HEAD MOVE IS THE ONLY THING WRONG. The first version
        # asked only "is realised_commit an ancestor of HEAD?", and a cross-model
        # review showed what that lets through: a receipt with a FORGED
        # baseline_commit, or an exit code contradicting its verdict, or raw
        # evidence disagreeing with it, would be filed as `stale` — a race — purely
        # because its realised_commit happened to be an ancestor. Ancestry may
        # explain the HEAD mismatch and the digest mismatch that follows from it.
        # It explains nothing else, and must not excuse anything else.
        _race_only = all(
            f.startswith("realised_commit ") or f.startswith("diff_digest ")
            for f in faults
        )
        if _race_only and head_moved_under_job(receipt, observed_head, gate_root):
            out["verdict"] = "stale"
            out["reasons"].extend(faults)
            out["notes"].append(
                "STALE, not forged: realised_commit is an ancestor of HEAD, so the "
                "tree advanced under this job — re-run it against the current HEAD. "
                "A `direct`-mode run needs an otherwise-quiet repository."
            )
            return out
        out["verdict"] = "forged"
        out["reasons"].extend(faults)
        out["notes"].append(
            "not re-derived, deliberately: MISSING is re-derived, FORGED is refused"
        )
        return out

    # ---- bindings hold; confirm the CONCLUSION independently --------------- #
    verdict, raw, code, err = run_scope_check(
        scope_check, mode, gate_root, baseline, allow, preexisting
    )
    if err:
        out["verdict"] = "unverifiable"
        out["reasons"].append(err)
        return out
    out["derived"] = {"verdict": verdict, "exit_code": code}
    out["violations"] = _violations_of(raw)

    if verdict != receipt["verdict"]:
        # THE ARTIFACT, NOT THE LIVE TREE, IS WHAT LANDS — and that settles one
        # disagreement honestly rather than by forgiving a path.
        #
        # `gate-receipt` runs the test floor AFTER the scope check, on purpose, so
        # a coverage dir or `.pytest_cache/` written by those tests exists by the
        # time this authority re-derives. `git add -A` honours .gitignore, so the
        # digest never saw them and the receipt still binds; the scope gate
        # deliberately DOES see ignored paths, so the re-derivation reports them
        # and an honest pass read as `contradicted`. Dogfooded, twice.
        #
        # A path that is not in the sealed patch cannot reach the project: the
        # finalizer applies the artifact and nothing else. So when the artifact
        # validates, the job ran in its own worktree, and EVERY newly objected-to
        # path is outside that artifact, the disagreement is about a tree nobody
        # will merge. Note it, do not refuse it. If even one violation IS in the
        # artifact, this does not apply and the contradiction stands.
        if (_sealed and mode == "worktree" and receipt["verdict"] == "pass"
                and verdict == "blocked"):
            try:
                with open(patch_artifact_path(run_dir, job_id), "rb") as _fh:
                    _sealed_paths = set(patch_paths(_fh.read()))
            except (IOError, OSError):
                _sealed_paths = None
            if _sealed_paths is not None and out["violations"] and all(
                    v not in _sealed_paths for v in out["violations"]):
                out["verdict"] = "pass"
                out["notes"].append(
                    "the re-derivation objects to %d path(s) that appeared after the "
                    "gate sealed its patch (%s) and that the sealed artifact does not "
                    "contain. The finalizer applies the artifact, never a fresh diff, "
                    "so none of them can reach the project — this is not a "
                    "contradiction about anything that will be merged."
                    % (len(out["violations"]), ", ".join(out["violations"][:5]))
                )
                return out
        out["verdict"] = "contradicted"
        out["reasons"].append(
            "receipt claims verdict %r but the same tree derives %r — the digest "
            "binds a receipt to a TREE, not to a conclusion, so a bound receipt "
            "still has to agree with the check"
            % (receipt["verdict"], verdict)
        )
        return out

    if verdict == "pass":
        out["verdict"] = "pass"
    elif verdict == "blocked":
        out["verdict"] = "blocked"
        out["reasons"].append(
            "verified receipt and independent re-derivation both report %d "
            "out-of-lane path(s)" % len(out["violations"])
        )
    else:
        out["verdict"] = "unverifiable"
        out["reasons"].append("gate verdict %r is not a pass — fails closed" % verdict)
    return out


def _violations_of(raw):
    try:
        doc = json.loads(_leading_json(raw or ""))
    except (ValueError, TypeError):
        return []
    if isinstance(doc, dict) and isinstance(doc.get("violations"), list):
        return doc["violations"]
    return []


# --------------------------------------------------------------------------- #
# run-level evaluation
# --------------------------------------------------------------------------- #
def evaluate_run(run_dir, repo_root, scope_check, manifest_path=None, only=None,
                 manifest_digest=None):
    """Evaluate every job (or ``only``) and return the report dict."""
    manifest_path = manifest_path or os.path.join(run_dir, "manifest.yaml")
    if not os.path.isfile(manifest_path):
        raise RuntimeError("manifest not found: %s" % manifest_path)
    # THE MANIFEST IS THE LANE MAP, so it is verified before it is believed.
    #
    # Every `write_allowed` this authority judges a job against comes from this
    # file, and the file sits in a run directory the pipeline exempts by name from
    # the scope gate. A job that widens its own lanes here would be judged
    # compliant against the widened list — the check would run, pass, and prove
    # nothing. `emit` bakes sha256(manifest.yaml) into the workflow script at
    # generation time and every later stage carries it forward, so the manifest
    # that is enforced is provably the manifest that was reviewed.
    if manifest_digest:
        actual = sha256_file(manifest_path)
        if actual != manifest_digest:
            return {
                "integration": "refused",
                "run_dir": os.path.abspath(run_dir),
                "manifest": os.path.abspath(manifest_path),
                "jobs_evaluated": 0,
                "tally": {"manifest_digest_mismatch": 1},
                "refused": sorted(only) if only else ["<all jobs>"],
                "results": [],
                "reason": (
                    "manifest %s hashes to %s, not the %s this run was emitted "
                    "against. The manifest declares every job's write_allowed, so a "
                    "lane map that changed after emit is refused rather than "
                    "enforced." % (manifest_path, actual, manifest_digest)
                ),
            }
    manifest = load_manifest(manifest_path)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("jobs"), list):
        raise RuntimeError("manifest %s has no jobs list" % manifest_path)

    state = {}
    state_path = os.path.join(run_dir, "state.json")
    if os.path.isfile(state_path):
        loaded, err = load_json(state_path)
        if err:
            raise RuntimeError("state.json unreadable: %s" % err)
        state = loaded if isinstance(loaded, dict) else {}
    state_jobs = state.get("jobs") if isinstance(state.get("jobs"), dict) else {}

    jobs = manifest["jobs"]
    if only:
        wanted = set(only)
        known = set(j.get("id") for j in jobs)
        unknown = sorted(wanted - known)
        if unknown:
            raise RuntimeError(
                "--jobs names %s, which the manifest does not define" % ", ".join(unknown)
            )
        jobs = [j for j in jobs if j.get("id") in wanted]

    evaluated = []
    for job in jobs:
        evaluated.append(
            evaluate_job(
                job,
                state_jobs.get(job.get("id")),
                run_dir,
                repo_root,
                scope_check,
            )
        )

    refused = [e for e in evaluated if e["verdict"] not in CLEAN]
    tally = {}
    for e in evaluated:
        tally[e["verdict"]] = tally.get(e["verdict"], 0) + 1
    return {
        "integration": "refused" if refused else "permitted",
        "run_dir": os.path.abspath(run_dir),
        "manifest": os.path.abspath(manifest_path),
        "jobs_evaluated": len(evaluated),
        "tally": tally,
        "refused": [e["job"] for e in refused],
        "results": evaluated,
    }


def render_human(report, stream):
    stream.write("\nIntegration authority — spec D1 (git-derived postcondition)\n")
    stream.write("run: %s\n\n" % report["run_dir"])
    if not report["results"] and report.get("reason"):
        stream.write("INTEGRATION REFUSED — %s\n" % report["reason"])
        return
    width = max([len(e["job"]) for e in report["results"]] + [3])
    for e in report["results"]:
        stream.write(
            "  %-*s  %-13s receipt=%-8s %s\n"
            % (
                width,
                e["job"],
                e["verdict"].upper(),
                e["receipt"] or "-",
                (e["reasons"] or e["notes"] or [""])[0],
            )
        )
    stream.write("\n")
    if report["integration"] == "permitted":
        stream.write(
            "INTEGRATION PERMITTED — %d job(s), every one resolved to a verdict this "
            "gate derived or verified itself.\n" % report["jobs_evaluated"]
        )
    else:
        stream.write(
            "INTEGRATION REFUSED — %d of %d job(s) did not resolve clean: %s\n"
            % (
                len(report["refused"]),
                report["jobs_evaluated"],
                ", ".join(report["refused"]),
            )
        )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser():
    p = argparse.ArgumentParser(
        description="Compound V integration authority (spec D1): refuse integration "
        "until every job resolves to a gate verdict this script derived or verified.",
    )
    p.add_argument("--run-dir", help="docs/superpowers/execution/<run-id>")
    p.add_argument("--repo-root", help="repo root (default: this script's repo)")
    p.add_argument("--manifest", help="manifest path (default: <run-dir>/manifest.yaml)")
    p.add_argument("--scope-check", help="path to compound-v-scope-check.py")
    p.add_argument("--jobs", help="comma-separated job ids to evaluate (default: all)")
    p.add_argument("--manifest-digest",
                   help="sha256:<hex> the manifest MUST hash to. Baked into the "
                        "emitted workflow script at generation time; a mismatch "
                        "refuses integration rather than enforcing a lane map that "
                        "changed after review.")
    p.add_argument("--json", action="store_true", help="emit only the JSON report")
    p.add_argument("--selftest", action="store_true", help="run built-in tests")
    return p


def main(argv):
    args = build_parser().parse_args(argv[1:])
    if not args.run_dir:
        print(
            json.dumps({"integration": "error", "error": "--run-dir is required"}),
            file=sys.stderr,
        )
        return 2

    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(args.repo_root or os.path.dirname(here))
    scope_check = os.path.abspath(
        args.scope_check or os.path.join(here, "compound-v-scope-check.py")
    )
    if not os.path.isfile(scope_check):
        print(
            json.dumps(
                {
                    "integration": "error",
                    "error": "scope gate not found: %s (this gate INVOKES it; it is "
                    "not a second matcher)" % scope_check,
                }
            ),
            file=sys.stderr,
        )
        return 2

    only = None
    if args.jobs:
        only = [j.strip() for j in args.jobs.split(",") if j.strip()]

    try:
        report = evaluate_run(
            args.run_dir, repo_root, scope_check, args.manifest, only,
            manifest_digest=args.manifest_digest,
        )
    except (RuntimeError, IOError, OSError, ValueError) as exc:
        print(
            json.dumps({"integration": "error", "error": str(exc)}), file=sys.stderr
        )
        return 2

    print(json.dumps(report, indent=2))
    if not args.json:
        render_human(report, sys.stderr)
    return 0 if report["integration"] == "permitted" else 1


# --------------------------------------------------------------------------- #
# selftest
# --------------------------------------------------------------------------- #
def _sh(cwd, *args):
    proc = subprocess.run(
        list(args),
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )
    if proc.returncode != 0:
        raise RuntimeError("%s failed in %s:\n%s" % (" ".join(args), cwd, proc.stdout))
    return proc.stdout


def _mkrepo(path):
    os.makedirs(path)
    _sh(path, "git", "init", "-q")
    _sh(path, "git", "config", "user.email", "selftest@example.invalid")
    _sh(path, "git", "config", "user.name", "selftest")
    _sh(path, "git", "config", "commit.gpgsign", "false")
    with open(os.path.join(path, "README.md"), "w") as fh:
        fh.write("seed\n")
    os.makedirs(os.path.join(path, "scripts"))
    with open(os.path.join(path, "scripts", "keep.py"), "w") as fh:
        fh.write("# keep\n")
    _sh(path, "git", "add", "-A")
    _sh(path, "git", "commit", "-q", "-m", "seed")
    return _sh(path, "git", "rev-parse", "HEAD").strip()


_MANIFEST_TMPL = """version: 1
run_id: selftest-run
jobs:
  - id: job-a
    title: "a"
    backend: claude
    isolation: direct
    write_allowed:
      - "scripts/allowed.py"
"""


def _write_run(run_dir, worktree, baseline):
    os.makedirs(os.path.join(run_dir, "results"), exist_ok=True)
    with open(os.path.join(run_dir, "manifest.yaml"), "w") as fh:
        fh.write(_MANIFEST_TMPL)
    with open(os.path.join(run_dir, "state.json"), "w") as fh:
        json.dump(
            {
                "run_id": "selftest-run",
                "jobs": {
                    "job-a": {
                        "status": "done",
                        "isolation": "worktree",
                        "worktree": worktree,
                        "baseline": baseline,
                    }
                },
            },
            fh,
        )


def _result(worktree, receipt=None, omit_receipt=False):
    doc = {
        "status": "success",
        "blocked": False,
        "files_changed": [],
        "violations": [],
        "summary": "selftest",
        "session_id": "",
        "worktree": worktree,
        "exit_code": 0,
        "failure_class": None,
        "retry_after_seconds": 0,
    }
    if not omit_receipt:
        doc["gate_receipt"] = receipt
    return doc


def _put_result(run_dir, job_id, doc):
    with open(os.path.join(run_dir, "results", "%s.json" % job_id), "w") as fh:
        json.dump(doc, fh)


def _honest_receipt(scope_check, wt, baseline, allow):
    verdict, raw, code, err = run_scope_check(
        scope_check, "worktree", wt, baseline, allow
    )
    assert err is None, err
    digest, derr = compute_diff_digest(wt, baseline)
    assert derr is None, derr
    return {
        "baseline_commit": baseline,
        "realised_commit": head_commit(wt),
        "diff_digest": digest,
        "verdict": verdict,
        "raw_stdout": raw,
        "exit_code": code,
    }


def _selftest():
    here = os.path.dirname(os.path.abspath(__file__))
    scope_check = os.path.join(here, "compound-v-scope-check.py")
    if not os.path.isfile(scope_check):
        print("FATAL: %s missing — this gate INVOKES it" % scope_check)
        return 1

    passed = [0]
    failed = [0]

    def expect(label, cond):
        if cond:
            passed[0] += 1
            print("PASS %s" % label)
        else:
            failed[0] += 1
            print("FAIL %s" % label)

    tmp = tempfile.mkdtemp(prefix="cv-intgate-selftest-")
    try:
        # ---------- pure-function layer ---------------------------------- #
        full = "a" * 40
        good = {
            "baseline_commit": full,
            "realised_commit": full,
            "diff_digest": "sha256:" + "b" * 64,
            "verdict": "pass",
            "raw_stdout": '{"verdict": "pass"}',
            "exit_code": 0,
        }
        expect("complete receipt is not missing", not receipt_is_missing(good))
        expect("absent receipt is missing", receipt_is_missing(None))
        expect("null-valued field ⇒ missing", receipt_is_missing(dict(good, verdict=None)))
        for field in RECEIPT_FIELDS:
            partial = dict(good)
            del partial[field]
            expect(
                "partial receipt (no %s) is MISSING, not forged" % field,
                receipt_is_missing(partial),
            )
        expect(
            "empty raw_stdout ⇒ missing",
            receipt_is_missing(dict(good, raw_stdout="")),
        )
        expect(
            "non-hex baseline ⇒ missing (shape, not a claim)",
            receipt_is_missing(dict(good, baseline_commit="HEAD")),
        )
        expect(
            "bool exit_code ⇒ missing",
            receipt_is_missing(dict(good, exit_code=True)),
        )
        expect(
            "bound receipt has no faults",
            receipt_binding_faults(good, full, full, good["diff_digest"]) == [],
        )
        expect(
            "wrong digest ⇒ binding fault",
            any(
                "diff_digest" in f
                for f in receipt_binding_faults(good, full, full, "sha256:" + "c" * 64)
            ),
        )
        expect(
            "wrong baseline ⇒ binding fault",
            any(
                "baseline_commit" in f
                for f in receipt_binding_faults(good, "d" * 40, full, good["diff_digest"])
            ),
        )
        expect(
            "wrong realised_commit ⇒ binding fault",
            any(
                "realised_commit" in f
                for f in receipt_binding_faults(good, full, "e" * 40, good["diff_digest"])
            ),
        )
        expect(
            "exit_code contradicting verdict ⇒ binding fault",
            any(
                "exit_code" in f
                for f in receipt_binding_faults(
                    dict(good, exit_code=1), full, full, good["diff_digest"]
                )
            ),
        )
        expect(
            "raw_stdout disagreeing with verdict ⇒ binding fault",
            any(
                "raw_stdout" in f
                for f in receipt_binding_faults(
                    dict(good, raw_stdout='{"verdict": "blocked"}'),
                    full,
                    full,
                    good["diff_digest"],
                )
            ),
        )
        expect(
            "_leading_json strips the gate's human tail",
            json.loads(_leading_json('{"verdict": "blocked"}\nBLOCKED: 1 file\n'))[
                "verdict"
            ]
            == "blocked",
        )
        expect(
            "_leading_json finds the document when the tail arrives FIRST "
            "(2>&1 interleaving: stderr unbuffered, stdout block-buffered)",
            json.loads(_leading_json('BLOCKED: 1 file\n  - x\n{"verdict": "blocked"}'))[
                "verdict"
            ]
            == "blocked",
        )
        expect(
            "_leading_json is not fooled by a brace inside a string",
            json.loads(_leading_json('noise {"v": "a{b", "w": 1} tail'))["w"] == 1,
        )

        # ---------- digest determinism ------------------------------------ #
        repo = os.path.join(tmp, "repo")
        base = _mkrepo(repo)

        # NO tracked file is excluded by name any more (fourth review pass). An
        # append to triage-outcomes.jsonl MOVES the direct-mode digest, and that is
        # the point: an unreported rewrite of that stream by a worker must be
        # visible to this authority, because the pipeline commits it by name.
        _mem = os.path.join(repo, "docs", "superpowers", "memory")
        os.makedirs(_mem, exist_ok=True)
        _to = os.path.join(_mem, "triage-outcomes.jsonl")
        with open(_to, "a") as _fh:
            _fh.write('{"event":"predicted"}\n')
        _d_b, _ = compute_diff_digest(repo, base)
        with open(_to, "a") as _fh:
            _fh.write('{"event":"actual","merge_pending":true}\n')
        _d_a, _ = compute_diff_digest(repo, base)
        expect("an append to triage-outcomes.jsonl MOVES the digest — no path is "
               "forgiven by name", _d_b != _d_a)
        _d_run, _ = compute_diff_digest(
            repo, base, exclude_prefixes=["docs/superpowers/execution/some-run"])
        expect("...and the run-directory exclusion does not forgive it either",
               _d_run == _d_a)
        # leave the sandbox as it was: the next check asserts verification
        # does not dirty the tree, and this block's appends are not verification
        os.remove(_to)
        for _d in (_mem, os.path.dirname(_mem), os.path.dirname(os.path.dirname(_mem))):
            try:
                os.rmdir(_d)
            except OSError:
                break
        d1, e1 = compute_diff_digest(repo, base)
        d2, e2 = compute_diff_digest(repo, base)
        expect("digest computes without error", e1 is None and e2 is None)
        expect("digest is stable across calls", d1 == d2)
        expect("digest renders as sha256:<64hex>", bool(DIGEST.match(d1 or "")))
        expect(
            "verifying does not dirty the tree",
            _sh(repo, "git", "status", "--porcelain").strip() == "",
        )
        with open(os.path.join(repo, "scripts", "allowed.py"), "w") as fh:
            fh.write("x = 1\n")
        d3, _ = compute_diff_digest(repo, base)
        expect("digest changes when the tree changes", d3 != d1)

        # ---------- end-to-end: the four verdict rows --------------------- #
        def fresh_case(name, mutate):
            """A worktree at `base`, mutated, with a run dir pointing at it."""
            wt = os.path.join(tmp, "wt-" + name)
            _sh(repo, "git", "worktree", "add", "-q", "--detach", wt, base)
            mutate(wt)
            run_dir = os.path.join(tmp, "run-" + name)
            _write_run(run_dir, wt, base)
            return wt, run_dir

        def write(wt, rel, text):
            path = os.path.join(wt, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as fh:
                fh.write(text)

        allow = ["scripts/allowed.py"]

        # (1) MISSING receipt + clean tree ⇒ re-derive ⇒ PASS
        wt, run_dir = fresh_case("clean", lambda w: write(w, "scripts/allowed.py", "1\n"))
        _put_result(run_dir, "job-a", _result(wt, omit_receipt=True))
        rep = evaluate_run(run_dir, repo, scope_check)
        row = rep["results"][0]
        expect(
            "MISSING + clean tree ⇒ re-derived PASS (no deadlock)",
            row["verdict"] == "pass" and row["receipt"] == "missing",
        )
        expect("clean run permits integration", rep["integration"] == "permitted")

        # (2) MISSING receipt + out-of-lane write ⇒ re-derive ⇒ BLOCKED
        wt, run_dir = fresh_case(
            "dirty",
            lambda w: (
                write(w, "scripts/allowed.py", "1\n"),
                write(w, "scripts/sneaky.py", "pwn\n"),
            ),
        )
        _put_result(run_dir, "job-a", _result(wt, receipt=None))
        rep = evaluate_run(run_dir, repo, scope_check)
        row = rep["results"][0]
        expect(
            "MISSING + real violation ⇒ re-derived BLOCKED",
            row["verdict"] == "blocked" and "scripts/sneaky.py" in row["violations"],
        )
        expect("blocked run refuses integration", rep["integration"] == "refused")

        # (3) HONEST receipt ⇒ PASS
        wt, run_dir = fresh_case(
            "honest", lambda w: write(w, "scripts/allowed.py", "1\n")
        )
        honest = _honest_receipt(scope_check, wt, base, allow)
        _put_result(run_dir, "job-a", _result(wt, receipt=honest))
        rep = evaluate_run(run_dir, repo, scope_check)
        expect(
            "honest bound receipt ⇒ PASS",
            rep["results"][0]["verdict"] == "pass"
            and rep["results"][0]["receipt"] == "present",
        )

        # (3b) HONEST receipt reporting a REAL block ⇒ BLOCKED, not forged.
        # Regression guard: on a block the scope gate prints its JSON and then a
        # human "BLOCKED: …" tail, so raw_stdout must be parsed with
        # _leading_json. A bare json.loads made every honest blocked receipt
        # read as forged.
        wt, run_dir = fresh_case(
            "honestblocked",
            lambda w: (
                write(w, "scripts/allowed.py", "1\n"),
                write(w, "scripts/sneaky.py", "pwn\n"),
            ),
        )
        hb = _honest_receipt(scope_check, wt, base, allow)
        _put_result(run_dir, "job-a", _result(wt, receipt=hb))
        rep = evaluate_run(run_dir, repo, scope_check)
        expect(
            "honest receipt reporting a REAL block ⇒ blocked, never forged",
            rep["results"][0]["verdict"] == "blocked",
        )
        # The gate writes the tail to STDERR, so a producer capturing stdout only
        # gets clean JSON while one capturing 2>&1 gets JSON + tail. BOTH are
        # legitimate readings of "the gate's literal stdout", so both must verify.
        hb_merged = dict(
            hb,
            raw_stdout=hb["raw_stdout"].rstrip("\n")
            + "\nBLOCKED: 1 file(s) written outside write_allowed:\n"
            + "  - scripts/sneaky.py\n",
        )
        expect(
            "the merged fixture really carries the human tail",
            "BLOCKED" in hb_merged["raw_stdout"],
        )
        _put_result(run_dir, "job-a", _result(wt, receipt=hb_merged))
        rep = evaluate_run(run_dir, repo, scope_check)
        expect(
            "raw_stdout with the gate's human tail still parses ⇒ blocked, not forged",
            rep["results"][0]["verdict"] == "blocked",
        )

        # (3d) A RETIRED WORKTREE OF AN ALREADY-MERGED JOB IS NOT UNVERIFIABLE —
        # when, and only when, the SEALED PATCH proves the merge (ninth review pass,
        # item 1 / Codex round 4 H4). Three cases, one fixture.
        wt_r, run_r = fresh_case("retired",
                                 lambda w: write(w, "scripts/allowed.py", "1\n"))
        rcpt_r = _honest_receipt(scope_check, wt_r, base, allow)
        subprocess.run(["git", "-C", wt_r, "add", "-A"], capture_output=True)
        patch_r = subprocess.run(["git", "-C", wt_r, "diff", "--cached", "--binary", base],
                                 capture_output=True).stdout
        os.makedirs(os.path.join(run_r, "jobs"), exist_ok=True)
        os.makedirs(os.path.join(run_r, "receipts"), exist_ok=True)
        with open(patch_artifact_path(run_r, "job-a"), "wb") as fh:
            fh.write(patch_r)
        sealed_r = sha256_file(patch_artifact_path(run_r, "job-a"))
        rcpt_sealed = dict(rcpt_r, patch_sha256=sealed_r)
        with open(os.path.join(run_r, "receipts", "job-a.gate.json"), "w") as fh:
            json.dump(rcpt_sealed, fh)
        _put_result(run_r, "job-a", _result(wt_r, receipt=rcpt_sealed))
        with open(os.path.join(run_r, "state.json")) as fh:
            st_r = json.load(fh)
        st_r["jobs"]["job-a"]["baseline"] = base
        # CASE A — the commit carries EXACTLY the sealed patch's blobs ⇒ pass.
        write(repo, "scripts/allowed.py", "1\n")
        _sh(repo, "git", "add", "-A")
        _sh(repo, "git", "commit", "-q", "-m", "wave merged")
        rc_h, real_sha, _ = _git_text(repo, ["rev-parse", "HEAD"])
        real_sha = real_sha.strip()
        st_r["jobs"]["job-a"]["merged"] = {"integrated": True, "commit": real_sha}
        with open(os.path.join(run_r, "state.json"), "w") as fh:
            json.dump(st_r, fh)
        shutil.rmtree(wt_r, ignore_errors=True)
        rep_r = evaluate_run(run_r, repo, scope_check)
        expect("a REAL merge whose worktree was retired reads pass",
               rep_r["results"][0]["verdict"] == "pass")
        expect("...and says the sealed patch proved it, not state.json or a pathname",
               any("sealed patch" in n for n in rep_r["results"][0]["notes"]))
        # CASE B — a DECOY commit that touches the lane with OTHER content ⇒ not proof.
        write(repo, "scripts/allowed.py", "decoy content\n")
        _sh(repo, "git", "add", "-A")
        _sh(repo, "git", "commit", "-q", "-m", "decoy touching the lane")
        rc_h, decoy_sha, _ = _git_text(repo, ["rev-parse", "HEAD"])
        st_r["jobs"]["job-a"]["merged"] = {"integrated": True, "commit": decoy_sha.strip()}
        with open(os.path.join(run_r, "state.json"), "w") as fh:
            json.dump(st_r, fh)
        rep_d = evaluate_run(run_r, repo, scope_check)
        expect("a decoy commit touching the lane with other content is NOT proof",
               rep_d["results"][0]["verdict"] == "unverifiable")
        expect("...and the reason says overlap is not proof",
               any("not proof" in r for r in rep_d["results"][0]["reasons"]))
        # CASE C — no sealed patch at all (a pre-sealing receipt) ⇒ unverifiable.
        os.remove(patch_artifact_path(run_r, "job-a"))
        with open(os.path.join(run_r, "receipts", "job-a.gate.json"), "w") as fh:
            json.dump(rcpt_r, fh)
        _put_result(run_r, "job-a", _result(wt_r, receipt=rcpt_r))
        st_r["jobs"]["job-a"]["merged"] = {"integrated": True, "commit": real_sha}
        with open(os.path.join(run_r, "state.json"), "w") as fh:
            json.dump(st_r, fh)
        rep_n = evaluate_run(run_r, repo, scope_check)
        expect("without a sealed patch, even the real commit is unverifiable — overlap is not proof",
               rep_n["results"][0]["verdict"] == "unverifiable"
               and any("pathname overlap is not proof" in r for r in rep_n["results"][0]["reasons"]))
        # HIGH from round 3: state.json is worker-writable, so a claimed merge with
        # a fabricated sha must NOT buy a pass before anything is verified.
        st_r["jobs"]["job-a"]["merged"] = {"integrated": True, "commit": "a" * 40}
        with open(os.path.join(run_r, "state.json"), "w") as fh:
            json.dump(st_r, fh)
        rep_f = evaluate_run(run_r, repo, scope_check)
        expect("a FABRICATED merge commit is unverifiable, never pass",
               rep_f["results"][0]["verdict"] == "unverifiable")
        expect("...and says a recorded merge is a claim, not a proof",
               any("is a claim" in r for r in rep_f["results"][0]["reasons"]))
        wt_u, run_u = fresh_case("retired-unmerged",
                                 lambda w: write(w, "scripts/allowed.py", "1\n"))
        _put_result(run_u, "job-a",
                    _result(wt_u, receipt=_honest_receipt(scope_check, wt_u, base,
                                                          allow)))
        shutil.rmtree(wt_u, ignore_errors=True)
        rep_u = evaluate_run(run_u, repo, scope_check)
        expect("a MISSING worktree with no recorded merge is still unverifiable",
               rep_u["results"][0]["verdict"] == "unverifiable")

        # (3b-stale) THE TREE MOVED UNDER THE JOB. Dogfood 2c: someone committed
        # while a direct-mode job was in flight, HEAD advanced past the commit the
        # job was measured at, and the run reported FORGED — an accusation of
        # tampering spent on an ordinary race. Both verdicts refuse; the remedy
        # differs, and that is the whole point of separating them.
        expect("head_moved_under_job: an unrelated pair is not 'moved'",
               head_moved_under_job({"realised_commit": "a" * 40}, "b" * 40, ".")
               is False)
        expect("head_moved_under_job: identical commits are not 'moved'",
               head_moved_under_job({"realised_commit": "c" * 40}, "c" * 40, ".")
               is False)
        expect("head_moved_under_job: a missing side is never 'moved'",
               head_moved_under_job({"realised_commit": ""}, "d" * 40, ".") is False
               and head_moved_under_job({"realised_commit": "d" * 40}, "", ".")
               is False)
        wt, run_dir = fresh_case(
            "stale", lambda w: write(w, "scripts/allowed.py", "1\n")
        )
        stale_receipt = _honest_receipt(scope_check, wt, base, allow)
        _put_result(run_dir, "job-a", _result(wt, receipt=stale_receipt))
        # Advance the tree the receipt was measured against, exactly as a human
        # committing mid-run does.
        write(wt, "unrelated.txt", "moved on\n")
        _sh(wt, "git", "add", "-A")
        _git_text(wt, ["commit", "-q", "-m", "someone committed mid-run"])
        rep = evaluate_run(run_dir, repo, scope_check)
        expect("a tree that advanced under the job reads STALE, not forged",
               rep["results"][0]["verdict"] == "stale")
        expect("STALE still refuses integration",
               rep["integration"] == "refused")
        expect("STALE names the remedy, not a forgery",
               any("re-run it" in n for n in rep["results"][0]["notes"]))

        # (3c) state.json pins NO baseline, but the receipt names one. The digest
        # and the re-derivation must use the SAME reference, or the gate invents a
        # disagreement and reports an honest receipt as contradicted.
        wt, run_dir = fresh_case(
            "unpinned", lambda w: write(w, "scripts/allowed.py", "1\n")
        )
        unpinned = _honest_receipt(scope_check, wt, base, allow)
        _put_result(run_dir, "job-a", _result(wt, receipt=unpinned))
        with open(os.path.join(run_dir, "state.json")) as fh:
            st = json.load(fh)
        del st["jobs"]["job-a"]["baseline"]
        with open(os.path.join(run_dir, "state.json"), "w") as fh:
            json.dump(st, fh)
        rep = evaluate_run(run_dir, repo, scope_check)
        expect(
            "no pinned baseline + honest receipt ⇒ pass, verified against ONE reference",
            rep["results"][0]["verdict"] == "pass",
        )
        expect(
            "and the weaker baseline source is disclosed, not hidden",
            any("pins no baseline" in n for n in rep["results"][0]["notes"]),
        )

        # (4) FORGED receipt (valid shape, wrong digest) ⇒ refused outright
        wt, run_dir = fresh_case(
            "forged", lambda w: write(w, "scripts/allowed.py", "1\n")
        )
        forged = dict(_honest_receipt(scope_check, wt, base, allow))
        forged["diff_digest"] = "sha256:" + "0" * 64
        _put_result(run_dir, "job-a", _result(wt, receipt=forged))
        rep = evaluate_run(run_dir, repo, scope_check)
        row = rep["results"][0]
        expect(
            "FORGED digest ⇒ verdict 'forged', not re-derived to a pass",
            row["verdict"] == "forged",
        )
        expect(
            "forged refusal names the digest",
            any("diff_digest" in r for r in row["reasons"]),
        )

        # (5) A schema-valid PASS over a DIRTY tree ⇒ contradicted
        wt, run_dir = fresh_case(
            "lying",
            lambda w: (
                write(w, "scripts/allowed.py", "1\n"),
                write(w, "scripts/sneaky.py", "pwn\n"),
            ),
        )
        lying = {
            "baseline_commit": base,
            "realised_commit": head_commit(wt),
            "diff_digest": compute_diff_digest(wt, base)[0],
            "verdict": "pass",
            "raw_stdout": '{"verdict": "pass", "violations": []}',
            "exit_code": 0,
        }
        _put_result(run_dir, "job-a", _result(wt, receipt=lying))
        rep = evaluate_run(run_dir, repo, scope_check)
        expect(
            "bound receipt whose CONCLUSION is false ⇒ contradicted, never pass",
            rep["results"][0]["verdict"] == "contradicted",
        )

        # (6) receipt bound to the WRONG baseline ⇒ forged
        wt, run_dir = fresh_case(
            "wrongbase", lambda w: write(w, "scripts/allowed.py", "1\n")
        )
        wrong = dict(_honest_receipt(scope_check, wt, base, allow))
        wrong["baseline_commit"] = "f" * 40
        _put_result(run_dir, "job-a", _result(wt, receipt=wrong))
        rep = evaluate_run(run_dir, repo, scope_check)
        expect(
            "receipt bound to the wrong baseline ⇒ forged",
            rep["results"][0]["verdict"] == "forged",
        )

        # (7) job vanished entirely (no result file) ⇒ re-derive
        wt, run_dir = fresh_case(
            "vanished", lambda w: write(w, "scripts/sneaky.py", "pwn\n")
        )
        rep = evaluate_run(run_dir, repo, scope_check)
        expect(
            "vanished job (no result at all) ⇒ re-derived, and BLOCKED here",
            rep["results"][0]["verdict"] == "blocked",
        )

        # (8) gate root gone ⇒ unverifiable, fails closed
        wt, run_dir = fresh_case(
            "gone", lambda w: write(w, "scripts/allowed.py", "1\n")
        )
        _put_result(run_dir, "job-a", _result(wt, omit_receipt=True))
        _sh(repo, "git", "worktree", "remove", "--force", wt)
        rep = evaluate_run(run_dir, repo, scope_check)
        expect(
            "missing gate root ⇒ unverifiable ⇒ refused (never a silent pass)",
            rep["results"][0]["verdict"] == "unverifiable"
            and rep["integration"] == "refused",
        )

        # (9) more than one receipt for a job ⇒ refused (D1: exactly one)
        wt, run_dir = fresh_case(
            "dupe", lambda w: write(w, "scripts/allowed.py", "1\n")
        )
        _put_result(run_dir, "job-a", _result(wt, omit_receipt=True))
        with open(os.path.join(run_dir, "results", "job-a.attempt2.json"), "w") as fh:
            json.dump(_result(wt, omit_receipt=True), fh)
        rep = evaluate_run(run_dir, repo, scope_check)
        expect(
            "a second receipt for one job ⇒ refused (D1 says EXACTLY one)",
            rep["results"][0]["verdict"] == "forged",
        )

        # (10) --jobs scoping rejects an unknown id rather than passing vacuously
        try:
            evaluate_run(run_dir, repo, scope_check, only=["no-such-job"])
            expect("--jobs with an unknown id raises", False)
        except RuntimeError:
            expect("--jobs with an unknown id raises", True)

        # (11) an INDIRECT writer — the lane guard's documented blind spot
        wt, run_dir = fresh_case(
            "indirect", lambda w: write(w, "scripts/allowed.py", "1\n")
        )
        subprocess.run(
            [
                sys.executable,
                "-c",
                "open('scripts/laundered.py','w').write('indirect\\n')",
            ],
            cwd=wt,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        _put_result(run_dir, "job-a", _result(wt, omit_receipt=True))
        rep = evaluate_run(run_dir, repo, scope_check)
        expect(
            "a write laundered through python3 -c is caught by the git-derived gate",
            rep["results"][0]["verdict"] == "blocked"
            and "scripts/laundered.py" in rep["results"][0]["violations"],
        )
        # ---------- THE SEALED PATCH ARTIFACT ------------------------------ #
        # The digest binds a receipt to a tree at gate time; the artifact binds
        # the MERGE to that same tree. An artifact that is missing, or that no
        # longer hashes to what the receipt recorded, is refused — the finalizer
        # applies that file, so there is nothing left to apply.
        def seal(wt, run_dir, receipt, paths, corrupt=None, drop=False):
            """Write receipts/job-a.gate.json + jobs/job-a.patch for a case."""
            os.makedirs(os.path.join(run_dir, "receipts"), exist_ok=True)
            os.makedirs(os.path.join(run_dir, "jobs"), exist_ok=True)
            idx = os.path.join(tmp, "seal-index")
            if os.path.exists(idx):
                os.remove(idx)
            env = {"GIT_INDEX_FILE": idx}
            _git_bytes(wt, ["read-tree", base], env=env)
            _git_bytes(wt, ["add", "-A"], env=env)
            args = ["diff", "--cached", "--binary", base, "--"] + list(paths)
            _rc, blob, _e = _git_bytes(wt, args, env=env)
            if corrupt:
                blob = blob + corrupt
            digest = "sha256:" + hashlib.sha256(blob).hexdigest()
            if not drop:
                with open(patch_artifact_path(run_dir, "job-a"), "wb") as fh:
                    fh.write(blob)
            doc = dict(receipt)
            doc["patch_sha256"] = digest
            with open(os.path.join(run_dir, "receipts", "job-a.gate.json"),
                      "w") as fh:
                json.dump(doc, fh)
            return digest

        wt, run_dir = fresh_case(
            "sealed-ok", lambda w: write(w, "scripts/allowed.py", "1\n"))
        r_ok = _honest_receipt(scope_check, wt, base, allow)
        _put_result(run_dir, "job-a", _result(wt, receipt=r_ok))
        seal(wt, run_dir, r_ok, ["scripts/allowed.py"])
        rep = evaluate_run(run_dir, repo, scope_check)
        expect("a receipt whose sealed patch is present and intact ⇒ pass",
               rep["results"][0]["verdict"] == "pass")

        wt, run_dir = fresh_case(
            "sealed-gone", lambda w: write(w, "scripts/allowed.py", "1\n"))
        r_g = _honest_receipt(scope_check, wt, base, allow)
        _put_result(run_dir, "job-a", _result(wt, receipt=r_g))
        seal(wt, run_dir, r_g, ["scripts/allowed.py"], drop=True)
        rep = evaluate_run(run_dir, repo, scope_check)
        expect("a receipt that records a sealed patch but has none ⇒ refused",
               rep["results"][0]["verdict"] == "forged")
        expect("...and the refusal names the missing artifact",
               any("jobs/job-a.patch is missing" in r
                   for r in rep["results"][0]["reasons"]))

        wt, run_dir = fresh_case(
            "sealed-swapped", lambda w: write(w, "scripts/allowed.py", "1\n"))
        r_s = _honest_receipt(scope_check, wt, base, allow)
        _put_result(run_dir, "job-a", _result(wt, receipt=r_s))
        seal(wt, run_dir, r_s, ["scripts/allowed.py"])
        with open(patch_artifact_path(run_dir, "job-a"), "ab") as fh:
            fh.write(b"\n# swapped after sealing\n")
        rep = evaluate_run(run_dir, repo, scope_check)
        expect("an artifact replaced after sealing ⇒ refused, never re-derived",
               rep["results"][0]["verdict"] == "forged")
        expect("...and it is not excused as a race: only realised_commit and "
               "diff_digest faults may be, and this is neither",
               any("was replaced after the gate sealed it" in r
                   for r in rep["results"][0]["reasons"]))

        # A gate document that disagrees with the result's own receipt is not a
        # second opinion; it is one receipt whose halves contradict each other.
        wt, run_dir = fresh_case(
            "sealed-split", lambda w: write(w, "scripts/allowed.py", "1\n"))
        r_sp = _honest_receipt(scope_check, wt, base, allow)
        _put_result(run_dir, "job-a", _result(wt, receipt=r_sp))
        seal(wt, run_dir, dict(r_sp, diff_digest="sha256:" + "9" * 64),
             ["scripts/allowed.py"])
        rep = evaluate_run(run_dir, repo, scope_check)
        expect("a gate document that disagrees with the result's receipt ⇒ refused",
               rep["results"][0]["verdict"] == "forged")

        # ---------- (b) POST-GATE TEST BYPRODUCTS -------------------------- #
        # `gate-receipt` runs the test floor AFTER the scope check, so a
        # `.pytest_cache/` written by those tests exists by the time this
        # authority looks. `git add -A` honours .gitignore so the digest never
        # saw it and the receipt still binds; the scope gate deliberately DOES
        # see ignored paths, so the re-derivation objects and an honest pass
        # read as `contradicted`. The artifact settles it: that path is not in
        # the sealed patch, so nothing will merge it.
        write(repo, ".gitignore", ".pytest_cache/\n")
        _sh(repo, "git", "add", "-A")
        _sh(repo, "git", "commit", "-q", "-m", "ignore pytest cache")
        ign_base = _sh(repo, "git", "rev-parse", "HEAD").strip()

        def ign_case(name):
            wt = os.path.join(tmp, "wt-" + name)
            _sh(repo, "git", "worktree", "add", "-q", "--detach", wt, ign_base)
            write(wt, "scripts/allowed.py", "1\n")
            run_dir = os.path.join(tmp, "run-" + name)
            _write_run(run_dir, wt, ign_base)
            rcpt = _honest_receipt(scope_check, wt, ign_base, allow)
            _put_result(run_dir, "job-a", _result(wt, receipt=rcpt))
            return wt, run_dir, rcpt

        wt, run_dir, rcpt = ign_case("byproducts")
        idx = os.path.join(tmp, "seal-index-b")
        if os.path.exists(idx):
            os.remove(idx)
        _git_bytes(wt, ["read-tree", ign_base], env={"GIT_INDEX_FILE": idx})
        _git_bytes(wt, ["add", "-A"], env={"GIT_INDEX_FILE": idx})
        _rc, blob, _e = _git_bytes(
            wt, ["diff", "--cached", "--binary", ign_base, "--",
                 "scripts/allowed.py"], env={"GIT_INDEX_FILE": idx})
        os.makedirs(os.path.join(run_dir, "receipts"), exist_ok=True)
        os.makedirs(os.path.join(run_dir, "jobs"), exist_ok=True)
        with open(patch_artifact_path(run_dir, "job-a"), "wb") as fh:
            fh.write(blob)
        with open(os.path.join(run_dir, "receipts", "job-a.gate.json"), "w") as fh:
            json.dump(dict(rcpt, patch_sha256="sha256:"
                           + hashlib.sha256(blob).hexdigest()), fh)
        # Only NOW, after the gate sealed its patch, do the tests run.
        write(wt, ".pytest_cache/CACHEDIR.TAG", "Signature: 8a477f597d28d172\n")
        write(wt, ".pytest_cache/v/cache/lastfailed", "{}\n")
        rep = evaluate_run(run_dir, repo, scope_check)
        expect("ignored byproducts written after the gate do NOT contradict the "
               "receipt — the authority validates the artifact, and they are not "
               "in it",
               rep["results"][0]["verdict"] == "pass")
        expect("...and the reason is recorded rather than the paths forgiven",
               any("sealed artifact does not contain" in n
                   for n in rep["results"][0]["notes"]))

        # The leniency is exactly that narrow: a violation INSIDE the artifact is
        # still a contradiction.
        wt, run_dir, rcpt = ign_case("byproducts-inlane")
        write(wt, "scripts/sneaky.py", "pwn\n")
        idx = os.path.join(tmp, "seal-index-c")
        if os.path.exists(idx):
            os.remove(idx)
        _git_bytes(wt, ["read-tree", ign_base], env={"GIT_INDEX_FILE": idx})
        _git_bytes(wt, ["add", "-A"], env={"GIT_INDEX_FILE": idx})
        _rc, blob, _e = _git_bytes(
            wt, ["diff", "--cached", "--binary", ign_base, "--",
                 "scripts/allowed.py", "scripts/sneaky.py"],
            env={"GIT_INDEX_FILE": idx})
        os.makedirs(os.path.join(run_dir, "receipts"), exist_ok=True)
        os.makedirs(os.path.join(run_dir, "jobs"), exist_ok=True)
        with open(patch_artifact_path(run_dir, "job-a"), "wb") as fh:
            fh.write(blob)
        with open(os.path.join(run_dir, "receipts", "job-a.gate.json"), "w") as fh:
            json.dump(dict(rcpt, patch_sha256="sha256:"
                           + hashlib.sha256(blob).hexdigest()), fh)
        rep = evaluate_run(run_dir, repo, scope_check)
        expect("a violation that IS in the sealed patch is still a refusal",
               rep["results"][0]["verdict"] in ("forged", "contradicted"))

        # ---------- THE MANIFEST DIGEST ------------------------------------ #
        # The manifest is the lane map. It lives in a run directory the pipeline
        # exempts by name from the scope gate, so a job could widen its own lanes
        # and every later check would agree with the widened list.
        wt, run_dir = fresh_case(
            "mdigest", lambda w: write(w, "scripts/allowed.py", "1\n"))
        _put_result(run_dir, "job-a", _result(wt, omit_receipt=True))
        man = os.path.join(run_dir, "manifest.yaml")
        good_digest = sha256_file(man)
        rep = evaluate_run(run_dir, repo, scope_check, manifest_digest=good_digest)
        expect("the run's own manifest satisfies its digest",
               rep["integration"] == "permitted")
        with open(man, "a") as fh:
            fh.write('      - "**"\n')
        rep = evaluate_run(run_dir, repo, scope_check, manifest_digest=good_digest)
        expect("a manifest widened after emit is REFUSED, not enforced",
               rep["integration"] == "refused")
        expect("...and the refusal says the lane map changed",
               "write_allowed" in (rep.get("reason") or ""))

        # ---------- THE IMPORT SURFACE ------------------------------------- #
        # A job with a lane over `scripts/**` can write `scripts/yaml.py`. Until
        # sys.path[0] was removed, THIS process imported it — from the very
        # `import yaml` that loads the manifest declaring that job's lanes.
        plug = os.path.join(tmp, "planted", "scripts")
        os.makedirs(plug)
        for name in ("compound-v-integration-gate.py", "compound-v-scope-check.py",
                     "compound-v-validate-manifest.py"):
            src = os.path.join(here, name)
            if os.path.exists(src):
                shutil.copyfile(src, os.path.join(plug, name))
        with open(os.path.join(plug, "yaml.py"), "w") as fh:
            fh.write(
                "def safe_load(text):\n"
                "    return {'version': 1, 'run_id': 'gate-test', 'jobs': [\n"
                "        {'id': 'job-a', 'title': 'widened', 'backend': 'claude',\n"
                "         'isolation': 'worktree', 'write_allowed': ['**']}]}\n"
                "def safe_dump(*a, **k):\n"
                "    raise RuntimeError('planted')\n"
            )
        wt, run_dir = fresh_case(
            "planted",
            lambda w: (write(w, "scripts/allowed.py", "1\n"),
                       write(w, "scripts/sneaky.py", "pwn\n")))
        _put_result(run_dir, "job-a", _result(wt, omit_receipt=True))
        proc = subprocess.run(
            [sys.executable, "-B", os.path.join(plug, "compound-v-integration-gate.py"),
             "--run-dir", run_dir, "--repo-root", repo, "--json"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True)
        try:
            planted_rep = json.loads(proc.stdout)
        except ValueError:
            planted_rep = {}
        if (planted_rep.get("results") or [{}])[0].get("verdict") != "blocked":
            print("      planted stdout: %s" % proc.stdout[:400])
            print("      planted stderr: %s" % proc.stderr[:400])
        expect("a planted scripts/yaml.py does NOT widen the lane map the "
               "authority enforces",
               (planted_rep.get("results") or [{}])[0].get("verdict") == "blocked",
               )
        expect("...and the out-of-lane write is still named",
               "scripts/sneaky.py" in
               ((planted_rep.get("results") or [{}])[0].get("violations") or []))

        # ---------- THE BYTECODE CACHE ------------------------------------- #
        # The matcher is loaded from source with the cache redirected outside the
        # tree. When that private directory cannot be made, NOTHING is loaded:
        # falling back to the default cache location would execute exactly the
        # in-tree `.pyc` the redirect exists to avoid.
        planted_cache = os.path.join(plug, "__pycache__")
        os.makedirs(planted_cache, exist_ok=True)
        with open(os.path.join(planted_cache, "compound-v-scope-check.pyc"),
                  "wb") as fh:
            fh.write(b"not real bytecode")
        real_mkdtemp = tempfile.mkdtemp

        def _no_tmp(*a, **k):
            raise OSError("no space left on device")

        tempfile.mkdtemp = _no_tmp
        try:
            fn, why = load_scope_matcher(os.path.join(plug,
                                                      "compound-v-scope-check.py"))
        finally:
            tempfile.mkdtemp = real_mkdtemp
        expect("no private bytecode cache ⇒ the matcher is NOT executed",
               fn is None)
        expect("...and it fails closed WITH a reason, not silently",
               "private bytecode cache" in (why or ""))
        expect("...and nothing was written into the planted cache directory",
               sorted(os.listdir(planted_cache)) == ["compound-v-scope-check.pyc"])

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    total = passed[0] + failed[0]
    print("\n%d/%d checks passed" % (passed[0], total))
    return 0 if failed[0] == 0 else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        sys.exit(_selftest())
    sys.exit(main(sys.argv))
