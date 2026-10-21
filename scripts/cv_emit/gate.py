"""gate-receipt: the preexisting snapshot, the run-dir exemptions and the Gate stage's command."""

from __future__ import annotations

import os
import sys
import argparse
import hashlib
import json
import re

from .util import (
    SCOPE_CHECK_DEFAULT, FASTPATH_DEFAULT, _run, _load_yaml, _atomic_write, _atomic_write_bytes,
    _read_json, test_contract_path, _load_state, _head_commit, _manifest_job,
)
from .digest import (
    manifest_digest_fault, patch_artifact_path, build_sealed_patch, compute_diff_digest,
)
from .prompts import (
    read_pinned_baseline,
)
from .plan import (
    _toolchain_artifacts_spec,
)


# --------------------------------------------------------------------------- #
# gate-receipt — the Gate stage's single clamped command
# --------------------------------------------------------------------------- #
def _file_digest(path):
    """sha256 of a file's bytes, or None when it cannot be read."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(65536)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except Exception:  # noqa: BLE001
        return None


def write_preexisting(snapshot_path, repo_root, paths):
    """Write the exemption as ``<sha256>  <relpath>`` lines.

    PATHS ALONE ARE NOT AN EXEMPTION. A cross-model review called that CRITICAL and
    was right: once a run-directory file is listed by name, a worker can rewrite its
    CONTENTS — another job's baseline, a receipt, `state.json` — and the gate cannot
    tell that from untouched bookkeeping. The comment above it claimed a worker
    "cannot forge a receipt"; the code did not support the claim.

    Binding each path to the digest it had at registration turns the exemption into
    "this file, unchanged" instead of "this filename, whatever it now says". A
    file whose bytes moved is no longer exempt and is gated like any other write.

    A DIRECTORY is written as ``dir  <path>`` and exempted BY NAME: git reports an
    untracked directory as one entry, a directory has no bytes to digest, and
    dropping it broke the pre-existing-dirt exemption that had worked since 3.0
    (dogfood 10). Anything else whose digest cannot be taken — unreadable, already
    gone — is written with NO line at all and is therefore never exempted: fail
    closed into a stricter gate, the same rule the snapshot itself follows.

    An earlier version of this docstring said directories were "never exempted",
    which was the opposite of what the code beneath it does.
    """
    lines = []
    for rel in paths:
        full = os.path.join(repo_root, rel)
        dig = _file_digest(full)
        if dig:
            lines.append("%s  %s" % (dig, rel))
        elif os.path.isdir(full.rstrip("/")) or rel.endswith("/"):
            # A DIRECTORY CANNOT BE DIGESTED, AND DROPPING IT BREAKS THE SNAPSHOT.
            # git reports an untracked directory as ONE entry (`.claude/worktrees/x/`),
            # and the first digest-only version silently dropped every such entry —
            # so fifteen leftover harness worktrees, which the path-only snapshot had
            # correctly exempted since 3.0, came back as violations against the next
            # direct-mode job. Dogfood 10 blocked on exactly that.
            #
            # `dir` is a by-name exemption, and it is the right trade here: a
            # directory entry says nothing about its contents either way, and the
            # files INSIDE it are listed separately when git reports them.
            lines.append("dir  %s" % rel)
    _atomic_write(snapshot_path, "\n".join(lines) + ("\n" if lines else ""))
    return len(lines)


def read_preexisting_unchanged(snapshot_path, repo_root):
    """The exempt paths whose bytes still match the digest recorded at register time.

    A line with no digest is DROPPED, loudly. It used to be honoured as a legacy
    bare path, which let a worker append one and exempt any file it liked — the
    lane-widening chain in the comment below. Nothing this project writes produces
    that shape, and an old snapshot that exempts nothing fails closed.
    """
    keep = []
    skipped_legacy = []
    try:
        with open(snapshot_path, "r", encoding="utf-8") as fh:
            raw = [ln.rstrip("\n") for ln in fh]
    except Exception:  # noqa: BLE001
        return keep
    for line in raw:
        line = line.strip()
        if not line:
            continue
        parts = line.split("  ", 1)
        if len(parts) == 2 and re.match(r"^[0-9a-f]{64}$", parts[0]):
            rel = parts[1].strip()
            if _file_digest(os.path.join(repo_root, rel)) == parts[0]:
                keep.append(rel)
        elif len(parts) == 2 and parts[0] == "dir":
            keep.append(parts[1].strip())      # by-name: see write_preexisting
        else:
            # A LINE WITHOUT A DIGEST IS NOT AN EXEMPTION, and accepting one was a
            # full attack chain. A cross-model review walked it: a direct worker
            # writes out of lane, edits `manifest.yaml` to widen `write_allowed`,
            # then appends a bare `manifest.yaml` line here. This branch accepted
            # it as "legacy", the manifest became exempt, the gate loaded the
            # WIDENED manifest, the digest excluded the run directory so both
            # forgeries were invisible, and the authority independently derived the
            # same false pass from the same widened manifest. The out-of-lane write
            # was then committed.
            #
            # The comments above this function claimed that attack was closed. It
            # was not, and backward compatibility for a format that shipped the same
            # day is not worth a lane-widening hole. An unparsable line is DROPPED:
            # a snapshot written by an older build simply exempts nothing, which
            # blocks loudly instead of passing quietly.
            skipped_legacy.append(line)
    if skipped_legacy:
        sys.stderr.write(
            "compound-v: ignored %d exemption line(s) with no digest in %s — "
            "an exemption without a digest cannot be trusted (see the comment "
            "above read_preexisting_unchanged)\n"
            % (len(skipped_legacy), snapshot_path)
        )
    return keep


# THE EXACT, CLOSED LIST of run-directory files that are exempt BY NAME.
#
# The first version exempted every descendant of the run directory except the
# baseline pin, and a cross-model review found the hole in one move:
# `manifest.yaml` lives there, and the manifest DEFINES `write_allowed`. A worker
# could write out of lane, rewrite its own manifest to widen the lane, and both the
# gate and the integration authority would then read the widened manifest and agree
# it was in scope. The baseline and the digest could stay perfectly honest, because
# neither of them binds the document that says what "in scope" means.
#
# So the by-name pass is a CLOSED LIST — RUN_DIR_EXEMPT_BY_NAME below, one entry
# per file class with the reason it cannot be digest-bound — and every other file
# in the run directory, manifest.yaml included, falls back to the digest-bound
# listing taken at register time. Rewrite the manifest and its digest stops
# matching, the exemption is lost, and the write is a violation.
#
# Every entry is self-referential, shared, or written by the pipeline AFTER the
# gate built its list — consequences, not choices. Exempting a file from the SCOPE
# check does not make it trusted: the receipt, the result and the sealed patch are
# each verified by `compound-v-integration-gate.py` (digest against the tree,
# exactly one result per job, the artifact hashed against the receipt), and the
# documented limit stands — in `direct` mode a worker can write anywhere, which is
# why the authority is the backstop and the baseline pin stays digest-bound.
#
# The selftest is generated from THIS list: every entry must be exempt, and a
# sibling name beside each must not be (ninth review pass, item 2).


# (template, why) — `{id}` is the job id. Order is documentation, not precedence.
RUN_DIR_EXEMPT_BY_NAME = (
    ("state.json",
     "shared: every job's Record rewrites it, so a register-time digest can never match"),
    ("preexisting/{id}.txt",
     "the exemption list itself: it records digests INCLUDING ITS OWN"),
    ("preexisting/{id}.verified.txt",
     "written BY the gate, after the list that would have to contain it was built"),
    ("receipts/{id}.gate.json",
     "written by the gate after its verdict; verified by the authority's digest binding"),
    ("jobs/{id}.patch",
     "the sealed patch, written by the gate after its verdict; hashed against the receipt"),
    ("results/{id}.json",
     "written by Record after the gate; the authority requires exactly one per job"),
)
# A re-attempt archives its predecessor as results/attempts/<id>.<n>.json, written
# by the same Record call, for the same reason — an unbounded family, matched by
# pattern below.
RUN_DIR_EXEMPT_ATTEMPTS = r"^results/attempts/{id}\.\d+\.json$"
# A superseded attempt's gate receipt, archived by `_supersede_attempt` under the
# tag it computes (realised sha prefix or UTC stamp, plus `-N` on a collision).
RUN_DIR_EXEMPT_SUPERSEDED = r"^receipts/{id}\.gate\.superseded-[0-9A-Za-z]+(-\d+)?\.json$"


def run_dir_owned_by_name(rel, run_dir_rel, job_id):
    """True iff ``rel`` is one of the pipeline's own files for THIS job in THIS
    run's directory — exactly the classes in RUN_DIR_EXEMPT_BY_NAME plus the
    results/attempts/ and superseded-receipt families. Everything else — manifest,
    prompts, and anything a worker invents — is NOT exempt here."""
    if not run_dir_rel:
        return False
    prefix = run_dir_rel.rstrip("/") + "/"
    if not rel.startswith(prefix):
        return False
    tail = rel[len(prefix):]
    if tail in tuple(t.replace("{id}", job_id) for t, _why in RUN_DIR_EXEMPT_BY_NAME):
        return True
    for pattern in (RUN_DIR_EXEMPT_ATTEMPTS, RUN_DIR_EXEMPT_SUPERSEDED):
        if re.match(pattern.replace("{id}", re.escape(job_id)), tail):
            return True
    return False


def _preexisting_snapshot(root, python_bin):
    """Repo-relative paths already dirty BEFORE this job ran (direct mode only).

    In `direct` mode the gate measures the whole working tree against the baseline,
    so it cannot tell a job's writes from dirt that was already there. Dogfooded
    2026-09-01: the first live Engine C run was BLOCKED not by its job — which
    stayed in its lane — but by leftover probe records, an untracked pre-eval
    directory and stray .pyc files. Every agent that day hit the same thing and
    passed `--preexisting` by hand.

    Captured at REGISTER time, before the implementer runs, so it is a genuine
    before-picture rather than a post-hoc excuse: anything appearing after this
    snapshot is the job's and is still gated. A worktree job needs none of this —
    its tree starts clean by construction.
    """
    out = _run([python_bin, "-B", "-c", (
        "import subprocess,sys\n"
        "def q(*a):\n"
        "    r = subprocess.run(['git','-C',sys.argv[1]]+list(a),"
        " capture_output=True, text=True)\n"
        "    return [x for x in r.stdout.split('\\0') if x]\n"
        "s = set(q('diff','--name-only','-z','HEAD'))\n"
        "s |= set(q('ls-files','--others','--exclude-standard','-z'))\n"
        "s |= set(q('ls-files','--others','--ignored','--exclude-standard','-z','--'))\n"
        "print('\\n'.join(sorted(s)))"), root])[1]
    return [ln for ln in out.splitlines() if ln.strip()]


def _run_scope_check(scope_check, mode, root, baseline, allow, python_bin,
                     preexisting=None, toolchain_artifacts=None):
    cmd = [python_bin, "-B", scope_check]
    cmd += ["--worktree" if mode == "worktree" else "--repo", root]
    if baseline:
        cmd += ["--baseline", baseline]
    for glob in allow:
        cmd += ["--allow", glob]
    # --preexisting takes a FILE of paths, one per line — not a repeatable value.
    # Passing paths individually made argparse keep only the last and try to open
    # it as a filename, so the subtraction silently did nothing. Caught on the
    # third live Engine C run, by the gate still reporting paths the snapshot had
    # captured correctly.
    if preexisting:
        cmd += ["--preexisting", preexisting]
    # `toolchain_artifacts` (issue #22): repeatable, one `--toolchain-artifact
    # <glob>` per manifest-declared glob, none when the manifest declares none.
    for glob in (toolchain_artifacts or []):
        cmd += ["--toolchain-artifact", glob]
    rc, out, err = _run(cmd)
    try:
        parsed = json.loads(out) if out.strip() else None
    except Exception:  # noqa: BLE001
        parsed = None
    return rc, out, err, parsed


def _run_test_floor(fastpath, manifest_path, job_id, worktree, baseline,
                    python_bin, last_result=None):
    """The floor, via the producer task-3 built.

    This is what replaces the `--test-cmd <configured-tests>` placeholder. That
    placeholder never had a value, which is why the floor had never executed once
    before today. `test-floor --manifest --job-id` resolves the command set from
    the manifest's `test_contract` and the job's `test_scope` — in Python, where
    the glob resolution can be tested — and the worker only executes it.
    """
    if not os.path.exists(fastpath):
        return None, "fastpath-run.py not found at %s" % fastpath
    cmd = [python_bin, "-B", fastpath, "test-floor", "--worktree", worktree,
           "--manifest", manifest_path, "--job-id", job_id]
    if baseline:
        cmd += ["--baseline", baseline]
    if last_result and os.path.exists(last_result):
        cmd += ["--last-result", last_result]
    else:
        cmd += ["--no-prior-run"]
    rc, out, err = _run(cmd)
    try:
        parsed = json.loads(out) if out.strip() else None
    except Exception:  # noqa: BLE001
        parsed = None
    if parsed is None:
        return None, "test floor produced no JSON (rc=%d): %s" % (rc, (err or out)[:400])
    return parsed, None


def _resolve_test_contract(fastpath, manifest_path, job_id, worktree, baseline,
                           python_bin, out_path):
    """Write jobs/<job-id>.test-contract.json — the slice a worker is HANDED.

    `job_spec.test_contract` is the resolved contract for exactly one job, and it
    travels as `--test-contract-file`, a real argument, never as prompt prose. A
    value a model has to notice is not a contract.
    """
    if not os.path.exists(fastpath):
        return None
    cmd = [python_bin, "-B", fastpath, "resolve-tests", "--worktree", worktree,
           "--manifest", manifest_path, "--job-id", job_id, "--out", out_path,
           "--no-prior-run"]
    if baseline:
        cmd += ["--baseline", baseline]
    rc, _, _ = _run(cmd)
    return out_path if rc == 0 and os.path.exists(out_path) else None


def _lane_map_worktree_for(run_dir, job_id, repo_root):
    """The worktree lane-map.json registered for `job_id` (the cwd the lane guard
    enforced for it), or None. Exactly one entry, an existing directory, and not the
    checkout itself — anything else is not a locator this gate may trust."""
    lm = _read_json(os.path.join(run_dir, "lane-map.json"), None)
    if not isinstance(lm, dict):
        return None
    cands = [p for p, j in (lm.get("worktrees") or {}).items() if j == job_id]
    if len(cands) != 1:
        return None
    cand = os.path.abspath(cands[0])
    if not os.path.isdir(cand) or cand == os.path.abspath(repo_root):
        return None
    return cand


def cmd_gate_receipt(argv):
    ap = argparse.ArgumentParser(prog="compound-v-emit-workflow.py gate-receipt")
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--job-id", required=True)
    ap.add_argument("--worktree", required=True)
    ap.add_argument("--impl-no-result", dest="impl_no_result", action="store_true",
                    help="the implementer returned no result; for a Claude worktree job "
                         "resolve the tree from lane-map.json's registration and tag the "
                         "receipt, so Record can refuse this job with evidence")
    ap.add_argument("--escalated-from", dest="escalated_from",
                    help="the model this job was lifted FROM after its retry budget "
                         "was exhausted (the reviewer lift). Recorded on the receipt "
                         "as the REQUESTED escalation: an org allowlist can substitute "
                         "a model silently, so the claim is what was asked for.")
    ap.add_argument("--manifest")
    ap.add_argument("--mode", choices=["worktree", "direct"], default="worktree")
    ap.add_argument("--repo-root", required=True,
                    help="the PROJECT root. Required: a `direct` job is gated in "
                         "this tree, and a defaulted root gates the wrong repo.")
    ap.add_argument("--scope-check", default=SCOPE_CHECK_DEFAULT)
    ap.add_argument("--fastpath", default=FASTPATH_DEFAULT)
    ap.add_argument("--python", default=(sys.executable or "python3"))
    ap.add_argument("--manifest-digest",
                    help="sha256:<hex> the manifest MUST hash to, baked in by "
                         "`emit`. A mismatch refuses: the manifest is the lane "
                         "map this gate measures against.")
    ap.add_argument("--now")
    args = ap.parse_args(argv)
    if getattr(args, "impl_no_result", False) and not (args.worktree or "").strip():
        _lm_wt = _lane_map_worktree_for(os.path.abspath(args.run_dir), args.job_id,
                                        os.path.abspath(args.repo_root))
        if args.mode != "worktree" or not _lm_wt:
            out = {"job_id": args.job_id, "verdict": "error", "source": "gate-receipt",
                   "impl_no_result": True,
                   "reason": "implementer returned no result and lane-map.json holds no "
                             "single registered worktree for this job — fails closed"}
            print(json.dumps(out, indent=2, sort_keys=True))
            return 2
        args.worktree = _lm_wt

    run_dir = os.path.abspath(args.run_dir)
    manifest_path = os.path.abspath(
        args.manifest or os.path.join(run_dir, "manifest.yaml")
    )
    job_id = args.job_id
    out = {"job_id": job_id, "verdict": "error", "source": "gate-receipt"}

    fault = manifest_digest_fault(manifest_path, args.manifest_digest)
    if fault:
        out["reason"] = fault
        print(json.dumps(out, indent=2, sort_keys=True))
        return 2

    try:
        manifest = _load_yaml(manifest_path) or {}
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        out["reason"] = "manifest unreadable: %s" % exc
        print(json.dumps(out, indent=2, sort_keys=True))
        return 2

    job = _manifest_job(manifest, job_id)
    if job is None:
        out["reason"] = "no job %s in the manifest" % job_id
        print(json.dumps(out, indent=2, sort_keys=True))
        return 2

    # `toolchain_artifacts` (issue #22): the manifest's declared exemption for
    # build artifacts the test floor writes on first run. MANIFEST-level only —
    # resolved once, here, and threaded through to the scope check below.
    manifest_toolchain_artifacts = _toolchain_artifacts_spec(manifest)

    repo_root = os.path.abspath(args.repo_root)
    reasons = []

    # WHERE TO GATE follows the MODE, which follows the manifest's isolation —
    # never a locator an agent chose. A `direct` job is gated in the project
    # checkout; the caller still passes `--worktree` so a disagreement is caught
    # rather than silently resolved in the agent's favour.
    if args.mode == "direct":
        root = repo_root
        if os.path.abspath(args.worktree) != repo_root:
            out["reason"] = (
                "direct job reported worktree %s, which is not the project root "
                "%s — a direct job has no worktree, and 3.0.1 turned exactly this "
                "mismatch into a patch applied to the wrong repository"
                % (os.path.abspath(args.worktree), repo_root)
            )
            print(json.dumps(out, indent=2, sort_keys=True))
            return 2
    else:
        root = os.path.abspath(args.worktree)
    if not os.path.isdir(root):
        out["reason"] = "gate root does not exist: %s" % root
        print(json.dumps(out, indent=2, sort_keys=True))
        return 2

    # The baseline is the PINNED pre-launch SHA, never a live HEAD, and its
    # ABSENCE FAILS CLOSED. 3.0.1 fell back to the gate root's HEAD, which is
    # exactly the value a worker that commits inside its worktree has already
    # moved — so the fallback measured the job against its own output and
    # reported a clean tree. An unknown baseline is not a passing one.
    state = _load_state(run_dir)
    state_job = state["jobs"].get(job_id) or {}
    baseline = read_pinned_baseline(run_dir, job_id, state_job)
    if not baseline:
        out["reason"] = (
            "no baseline pinned for job %s (neither state.json nor "
            "jobs/%s.baseline). register-lane pins it before the worker launches; "
            "without it the gate would measure against a HEAD the worker can move, "
            "so this fails closed" % (job_id, job_id)
        )
        print(json.dumps(out, indent=2, sort_keys=True))
        return 2
    realised = _head_commit(root)

    allow = job.get("write_allowed") or []
    # BOTH MODES subtract what was already there when the job registered, and both
    # subtract it the same way: only paths whose bytes are UNCHANGED since the
    # snapshot. The two modes differ in what the snapshot photographs, not in how
    # far it is trusted.
    #
    #   direct   — the checkout's pre-dispatch dirt, which the job did not make.
    #   worktree — what this job's `provision_command` installed into the fresh
    #              worktree before the implementer was handed anything to do.
    #
    # Worktree mode was excluded until 3.6 on the reasoning that "a worktree starts
    # clean, so a subtraction there could only ever hide a real violation". That
    # held while nothing but the model ever wrote into a worktree. A provisioned
    # worktree does not start clean — it starts with a dependency tree the pipeline
    # put there — and the exclusion made the gate blame the job for it. What keeps
    # the subtraction honest is unchanged and is not the mode: the snapshot is
    # taken before the work, and every path in it is verified by digest, so a
    # dependency file the job rewrites is gated like any other write.
    foreign = []
    pre = None
    candidate = os.path.join(args.run_dir, "preexisting", "%s.txt" % args.job_id)
    if os.path.isfile(candidate):
        # The snapshot binds each path to the digest it had at register time.
        # Only paths whose bytes STILL match are exempt; a bookkeeping file the
        # worker rewrote is gated like any other write. scope-check's
        # `--preexisting` takes a plain path list, so the verified subset is
        # materialised next to the snapshot rather than handed over whole.
        kept = read_preexisting_unchanged(candidate, root)
        # Plus everything the pipeline owns in THIS run directory, by name.
        # `state.json` is shared — a sibling job's Record rewrites it between
        # this job registering and its gate running, so a digest taken at
        # register time can never match again — and `<id>.verified.txt` is
        # written by this very block, after registration. Both were violations
        # until dogfood 10 ran a two-wave direct-mode job and blocked its own
        # reviewer over them. The two levers a worker could actually pull —
        # `jobs/<id>.baseline` and `preexisting/<id>.txt` — are excluded from
        # this by-name pass and stay digest-bound.
        run_rel = os.path.relpath(os.path.abspath(args.run_dir),
                                  os.path.abspath(root))
        if not run_rel.startswith(".." + os.sep):
            run_rel = run_rel.replace(os.sep, "/")
            seen = set(kept)
            for dirpath, _dn, filenames in os.walk(args.run_dir):
                for name in filenames:
                    rel = os.path.relpath(
                        os.path.abspath(os.path.join(dirpath, name)),
                        os.path.abspath(root)).replace(os.sep, "/")
                    if rel in seen:
                        continue
                    if run_dir_owned_by_name(rel, run_rel, args.job_id):
                        kept.append(rel)
                        seen.add(rel)
        verified = os.path.join(args.run_dir, "preexisting",
                                "%s.verified.txt" % args.job_id)
        # THE FILE MUST LIST ITSELF. It is written after `kept` is built, so the
        # run-directory walk above cannot have seen it — dogfood 12 blocked on
        # this one path and nothing else, the self-reference one layer deeper
        # than dogfood 11's. Adding its own path is the whole fix: a list that
        # does not exempt itself can never let a direct-mode job pass.
        # THE FILES THAT DO NOT EXIST YET, ADDED BY CONSTRUCTION.
        #
        # The walk above can only list what is on disk NOW. Three of this job's
        # pipeline files are written LATER — this verified list, the gate's own
        # receipt, and Record's result — so a predicate that recognises them is
        # not enough; they have to be named. Dogfood 21 proved that the hard
        # way: the predicate was right, the walk simply could not see them, and
        # the run failed on the same two paths as dogfood 20.
        #
        # Chasing these one per run cost five dogfoods. They are enumerated here
        # ONCE, from the three places in this file that write them.
        _later_paths = [verified,
                        os.path.join(args.run_dir, "receipts",
                                     "%s.gate.json" % args.job_id),
                        patch_artifact_path(args.run_dir, args.job_id),
                        os.path.join(args.run_dir, "results",
                                     "%s.json" % args.job_id)]
        # A re-attempt: Record will archive the previous result as the next free
        # results/attempts/<id>.<n>.json (the same numbering it uses).
        if os.path.exists(_later_paths[-1]):
            _att_dir = os.path.join(args.run_dir, "results", "attempts")
            _n = 1
            while os.path.exists(os.path.join(_att_dir, "%s.%d.json" % (args.job_id, _n))):
                _n += 1
            _later_paths.append(os.path.join(_att_dir, "%s.%d.json" % (args.job_id, _n)))
        for _later in _later_paths:
            _rel = os.path.relpath(os.path.abspath(_later),
                                   os.path.abspath(root)).replace(os.sep, "/")
            if not _rel.startswith("../") and _rel not in kept:
                kept.append(_rel)
        _atomic_write(verified, "\n".join(kept) + ("\n" if kept else ""))
        pre = verified
    rc, raw_stdout, err, parsed = _run_scope_check(
        args.scope_check, args.mode, root, baseline, allow, args.python, preexisting=pre,
        toolchain_artifacts=manifest_toolchain_artifacts,
    )
    # What the gate forgave under `toolchain_artifacts`, distinct from `changed`
    # and `violations` — recorded even on a `blocked`/`error` verdict, and `[]`
    # rather than absent when the manifest declared none or the gate produced no
    # JSON, so a reader never has to distinguish "declared nothing" from "gate
    # didn't run" by checking for the key's existence.
    out["toolchain_artifacts"] = (parsed or {}).get("toolchain_artifacts") or []
    # NAME THE OPERATOR'S FOOTPRINTS SEPARATELY.
    #
    # A `direct`-mode job measures the whole tree, so ANYTHING written while
    # it runs is attributed to it — including another run's manifest that a
    # human was preparing in the next terminal. That is not a gate bug; the
    # gate cannot tell two writers apart. But the resulting refusal reads as
    # "your job wrote five files it should not have", which is the opposite
    # of what happened, and this has now confused three dogfood runs — all
    # three mine.
    #
    # So paths under the execution root that belong to some OTHER run are
    # still violations, and are additionally listed under
    # `foreign_execution_paths` so the diagnosis is immediate. A worker that
    # genuinely writes into another run's directory is caught exactly as
    # before; only the explanation improves.
    exec_root = "docs/superpowers/execution/"
    this_run = os.path.basename(os.path.normpath(args.run_dir))
    for p in ((parsed or {}).get("violations") or []):
        if p.startswith(exec_root):
            seg = p[len(exec_root):].split("/", 1)[0]
            if seg and seg != this_run:
                foreign.append(p)

    if baseline:
        # In DIRECT mode the run directory sits inside the measured tree and the
        # pipeline keeps writing into it after this point (Record, receipts,
        # state.json). Excluding it here — and identically in the authority — is
        # what makes the two digests comparable at all. It is the ONLY exclusion:
        # everything else the pipeline writes now happens after the authority has
        # run, so no tracked file needs forgiving by name.
        _digest_excl = None
        if args.mode != "worktree":
            _rel = os.path.relpath(os.path.abspath(args.run_dir), os.path.abspath(root))
            if not _rel.startswith(".." + os.sep):
                _digest_excl = [_rel.replace(os.sep, "/")]
        digest, digest_err = compute_diff_digest(root, baseline,
                                                 exclude_prefixes=_digest_excl)
    else:
        digest, digest_err = None, "no baseline to diff against"

    if parsed and parsed.get("verdict") in ("pass", "blocked"):
        verdict = parsed["verdict"]
    elif rc == 0:
        verdict = "pass"
    elif rc == 1:
        verdict = "blocked"
    else:
        verdict = "error"

    out["verdict"] = verdict
    out["exit_code"] = rc
    out["raw_stdout"] = raw_stdout
    if foreign:
        out["foreign_execution_paths"] = foreign
        out["foreign_execution_note"] = (
            "%d violation(s) live under another run's execution directory. A "
            "`direct`-mode job measures the WHOLE tree, so anything written while it "
            "ran is attributed to it — including files a human was preparing in "
            "another terminal. These are still violations (a worker writing into "
            "another run's directory must be caught), but if you were editing during "
            "this run, they are yours, not the job's." % len(foreign)
        )
    # The tree this gate MEASURED, carried forward to Record explicitly. Empty
    # for a direct job — that is a value, not a missing one, and Record branches
    # on the manifest's isolation rather than on whether this string is blank.
    out["worktree"] = "" if args.mode == "direct" else root
    if getattr(args, "impl_no_result", False):
        # Carried into the receipt so Record refuses the JOB (status error, with the
        # measured tree as evidence) rather than the authority voiding the wave.
        out["impl_no_result"] = True
    _esc_from = str(getattr(args, "escalated_from", "") or "").strip()
    if _esc_from:
        # The REQUESTED escalation, not a claim about what ran: an allowlist can
        # substitute the model without telling anyone, so the receipt says which
        # rung the run ASKED to leave, and nothing about which one answered.
        out["escalated_from"] = _esc_from
    if baseline:
        out["baseline_commit"] = baseline
    if realised:
        out["realised_commit"] = realised
    if digest:
        out["diff_digest"] = digest
    elif digest_err:
        reasons.append("diff digest not computed: %s" % digest_err)
    if verdict == "error" and err.strip():
        reasons.append(err.strip())

    # Tests run AFTER the gate and only when the job would otherwise pass.
    # Running them first would let a coverage file or a cache dir a test wrote
    # become a false violation. The flip side is the caller's problem and is
    # handled at merge: staging is restricted to the gate-approved paths.
    # A job that declared write_allowed and changed NOTHING did not do its work.
    # "No files changed" is not "clean" — it is "no work", and the two are opposite
    # conclusions that the gate's pass/blocked axis cannot tell apart on its own.
    # Dogfooded 2026-09-01 on a two-wave run: the dependent job returned
    # files_changed: [], the gate passed it, Record wrote success, and the wave
    # finalizer honestly reported "nothing left to commit" — so the whole chain
    # reported success for work that never happened. The manifest is what makes
    # this decidable: a job with an empty write_allowed (a reviewer) is expected to
    # change nothing; a job with lanes is not.
    gate_changed = (parsed or {}).get("changed") or []
    if verdict == "pass" and (job.get("write_allowed") or []) and not gate_changed:
        # `blocked`, not a new verdict word: job_result.schema.json pins
        # gate_receipt.verdict to pass|blocked|error, and the authority cross-checks
        # verdict against exit_code. A fourth value produced an INCOHERENT receipt
        # that the authority correctly read as `forged` — a refusal for the wrong
        # reason is only marginally better than no refusal, because it sends whoever
        # reads it hunting a forgery that never happened.
        verdict = "blocked"
        out["verdict"] = verdict
        out["exit_code"] = 1
        out["no_work"] = True
        out["reason"] = (
            "job %r declares write_allowed but changed no files. That is not a clean "
            "tree, it is an absent implementation — failing closed rather than "
            "recording a success nobody can point at." % job_id)

    if verdict == "pass":
        # Re-resolved here against the job's REALISED diff. The Implement stage
        # already wrote one (that is the copy an external worker was handed,
        # before it changed anything); this one is what the floor about to run
        # was scoped from, and it is what `record` reads `scope` back out of.
        contract_out = test_contract_path(run_dir, job_id)
        os.makedirs(os.path.dirname(contract_out), exist_ok=True)
        _resolve_test_contract(
            args.fastpath, manifest_path, job_id, root, baseline,
            args.python, contract_out,
        )
        tests, test_err = _run_test_floor(
            args.fastpath, manifest_path, job_id, root, baseline, args.python
        )
        if tests is not None:
            out["tests"] = tests
        elif test_err:
            reasons.append("test floor: %s" % test_err)

    # ---- SEAL WHAT THIS GATE APPROVED -------------------------------------- #
    # The merge used to take a FRESH diff of the live tree whenever the finalizer
    # got round to it, so whatever the tree said THEN is what landed — gate or no
    # gate. Everything between the two moments rode along: a revert, a post-gate
    # edit to an in-lane file, the test floor's own byproducts. The artifact is
    # written here, from the paths this gate approved and nothing else, and its
    # sha256 goes into the receipt. `finalize-wave` applies this file.
    #
    # Sealed on a BLOCKED verdict too, deliberately: nothing will apply it, and a
    # human reading a refused run gets the exact diff that was refused.
    approved = [pth for pth in gate_changed
                if pth not in ((parsed or {}).get("violations") or [])]
    if baseline and approved:
        patch_bytes, patch_err = build_sealed_patch(root, baseline, approved)
        if patch_err:
            reasons.append("sealed patch not written: %s" % patch_err)
        else:
            patch_path = patch_artifact_path(run_dir, job_id)
            os.makedirs(os.path.dirname(patch_path), exist_ok=True)
            _atomic_write_bytes(patch_path, patch_bytes)
            out["patch_path"] = patch_path
            out["patch_sha256"] = ("sha256:"
                                   + hashlib.sha256(patch_bytes).hexdigest())
            out["patch_paths"] = approved
    elif baseline and verdict == "pass" and not approved:
        # A pass with nothing approved is already refused above (`no_work`) for any
        # job that declared lanes; a reviewer legitimately approves nothing, and
        # there is nothing to seal.
        out["patch_paths"] = []

    if reasons:
        out["reason"] = " | ".join(reasons)

    receipt_dir = os.path.join(run_dir, "receipts")
    os.makedirs(receipt_dir, exist_ok=True)
    receipt_path = os.path.join(receipt_dir, "%s.gate.json" % job_id)
    _atomic_write(receipt_path, json.dumps(out, indent=2, sort_keys=True) + "\n")
    out["receipt_path"] = receipt_path

    print(json.dumps(out, indent=2, sort_keys=True))
    return 0
