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

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

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
                args.append(":(exclude)%s" % str(p).strip().rstrip("/") + "/**")
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
            allow_globs = job.get("write_allowed") or []
            # The SAME matcher the scope gate uses — never a second one. A
            # verifier that matches differently from the gate is a verifier that
            # can disagree with it for reasons neither of them is about.
            _sc = None
            try:
                import importlib.util as _ilu
                _spec = _ilu.spec_from_file_location("cv_scope_check", scope_check)
                if _spec and _spec.loader:
                    _sc = _ilu.module_from_spec(_spec)
                    _spec.loader.exec_module(_sc)
            except Exception:  # noqa: BLE001
                _sc = None
            _m_fn = getattr(_sc, "is_allowed", None) if _sc else None
            if _m_fn is None:
                in_lane = False
                out["notes"].append(
                    "could not load the scope matcher to check the merge's lanes")
            else:
                in_lane = bool(touched) and any(_m_fn(p, allow_globs)
                                                for p in touched)
            if rc_e == 0 and rc_a == 0 and in_lane:
                out["verdict"] = "pass"
                out["receipt"] = "merged"
                out["notes"].append(
                    "gate root is gone because this job was merged as %s, which "
                    "EXISTS, is an ancestor of HEAD, and touches this job's declared "
                    "lanes — verified from git, not from state.json" % _commit[:12]
                )
                return out
            out["verdict"] = "unverifiable"
            out["reasons"].append(
                "state.json claims this job merged as %s but git does not confirm "
                "it (exists=%s ancestor-of-HEAD=%s touches-its-lanes=%s). A recorded "
                "merge is a claim; state.json is writable by a direct worker, so it "
                "cannot prove one." % (_commit[:12] or "?", rc_e == 0, rc_a == 0,
                                       in_lane)
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
    # outside the worktree entirely.
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
def evaluate_run(run_dir, repo_root, scope_check, manifest_path=None, only=None):
    """Evaluate every job (or ``only``) and return the report dict."""
    manifest_path = manifest_path or os.path.join(run_dir, "manifest.yaml")
    if not os.path.isfile(manifest_path):
        raise RuntimeError("manifest not found: %s" % manifest_path)
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
            args.run_dir, repo_root, scope_check, args.manifest, only
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

        # (3d) A RETIRED WORKTREE OF AN ALREADY-MERGED JOB IS NOT UNVERIFIABLE.
        wt_r, run_r = fresh_case("retired",
                                 lambda w: write(w, "scripts/allowed.py", "1\n"))
        _put_result(run_r, "job-a",
                    _result(wt_r, receipt=_honest_receipt(scope_check, wt_r, base,
                                                          allow)))
        with open(os.path.join(run_r, "state.json")) as fh:
            st_r = json.load(fh)
        # A REAL merge: the commit must exist, be an ancestor of HEAD, and touch
        # this job's declared lanes. A fabricated sha is the thing being excluded.
        write(repo, "scripts/allowed.py", "merged for real\n")
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
        expect("...and says git confirmed it, not state.json",
               any("verified from git" in n for n in rep_r["results"][0]["notes"]))
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
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    total = passed[0] + failed[0]
    print("\n%d/%d checks passed" % (passed[0], total))
    return 0 if failed[0] == 0 else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        sys.exit(_selftest())
    sys.exit(main(sys.argv))
