"""finalize-wave: the serialized end of every wave."""

from __future__ import annotations

import os
import sys
import argparse
import json
import subprocess

from .util import (
    HERE, INTEGRATION_GATE_DEFAULT, _run, _load_yaml, _run_dir_lock, _read_json, lane_map_path,
    _load_state, _utc_stamp, _save_state, _head_commit, _manifest_job,
)
from .digest import (
    manifest_digest_fault, sealed_post_image, head_matches_post_image,
)
from .prompts import (
    read_pinned_baseline,
)
from .record import (
    _stage_paths, read_sealed_patch, apply_patch, merge_back, _maybe_append_run_actual,
    _gate_mode_from_receipt,
)


# --------------------------------------------------------------------------- #
# finalize-wave — the ONLY writer into the project checkout
#
# Order is the whole point, and it is: AUTHORITY -> MERGE -> COMMIT.
#
# 3.0.1 had Record call `git apply --index` in the main checkout before
# `/v:dispatch` step 7 ran `compound-v-integration-gate.py`, and Record never
# committed. Two consequences, both real:
#
#   * a job could LAND without the authority ever running — the session dies
#     after Record stages, a later plain `git commit` (`/v:orchestrate` runs one)
#     sweeps the staged patch into history, and nothing ever gated it. The
#     authority was bypassed, not defeated: it is a correct script that the
#     integration path had already walked past;
#   * a dependent could not SEE its prerequisite — `git apply --index` stages,
#     and the next wave's worktree is created from an unchanged HEAD.
#
# Both close by making a wave's integration one serialized step that runs the
# authority over exactly this wave's jobs, refuses everything on anything other
# than `permitted`, and finishes with a real commit.
# --------------------------------------------------------------------------- #
def _stage_run_bookkeeping(repo_root, run_dir):
    """Stage the run's own record. Returns the run dir's repo-relative path, or None.

    THE FORCE FLAG IS THE POINT. This is a directory SCAN, not a named pathspec
    like `_stage_paths`, and a repository whose `.gitignore` carries `docs/`
    (generated documentation is commonly ignored, and Compound V's run directory
    lives at `docs/superpowers/execution/<run-id>/`) makes every artefact of the
    run invisible to a plain `git add -A -- <dir>`: git refuses the pathspec as
    ignored, the bookkeeping commit finds nothing staged, and the run finalizes
    with its state.json, receipts and results untracked — the exact shape of the
    v2.6.4 data loss, where `git worktree remove` then deleted the audit trail.
    What is forced is bounded by the pathspec: this run's own directory and the
    two pipeline-owned memory streams, never the tree at large.

    The lock file is un-staged again right after, because it is the one thing in
    the run directory that belongs to a process and not to the record.
    """
    bk_rel = os.path.relpath(os.path.abspath(run_dir), os.path.abspath(repo_root))
    if bk_rel.startswith(".." + os.sep) or bk_rel == "..":
        return None
    _run(["git", "-C", repo_root, "add", "-A", "-f", "--", bk_rel])
    _run(["git", "-C", repo_root, "reset", "-q", "--",
          os.path.join(bk_rel, ".run.lock")])
    for stream in ("docs/superpowers/memory/triage-outcomes.jsonl",
                   "docs/superpowers/memory/worker-performance.jsonl"):
        if os.path.exists(os.path.join(repo_root, stream)):
            _run(["git", "-C", repo_root, "add", "-f", "--", stream])
    return bk_rel


def _commit_paths(repo_root, paths, message):
    """Commit exactly these paths. Returns (sha or None, error or None).

    Restricted to a pathspec on purpose: a bare `git commit` in a shared checkout
    commits whatever else is staged, which is the mechanism by which an ungated
    patch reached history in the first place. NUL-delimited because a path may
    legitimately contain a newline.
    """
    if not paths:
        return None, None
    ok, err = _stage_paths(repo_root, paths)
    if not ok:
        return None, err
    payload = "\0".join(paths).encode("utf-8")
    try:
        proc = subprocess.Popen(
            ["git", "-C", repo_root, "commit",
             "--pathspec-from-file=-", "--pathspec-file-nul", "-m", message],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        out, cerr = proc.communicate(payload)
        rc = proc.returncode
    except Exception as exc:  # noqa: BLE001
        return None, "git commit raised: %s" % exc
    if rc != 0:
        text = (out + cerr).decode("utf-8", "replace")
        if "nothing to commit" in text or "no changes added" in text:
            return None, None  # already committed; idempotent, not a failure
        return None, "git commit failed: %s" % text.strip()[:400]
    return _head_commit(repo_root), None


def _retire_lane_map(run_dir):
    """Delete the run's lane-map.json at a TERMINAL phase (finding 68).

    The lane map is runtime state: it tells the lane guard which worktree —
    or, for a direct job, which checkout — belongs to which job WHILE the run
    is live. A direct job's 'worktree' is the repository root, which exists
    forever, so a finished run's map kept claiming the checkout and the guard
    denied the next feature's pre-flight auditors as that run's review job.
    The guard now also skips terminal runs; this removes the claim at source.
    Best-effort, never fatal."""
    try:
        os.remove(lane_map_path(run_dir))
        return True
    except OSError:
        return False


def _retire_run_lock(run_dir):
    """Delete the run's OWN `.run.lock` at the same TERMINAL phase transition
    that retires lane-map.json (finding 105).

    `.run.lock` is `_run_dir_lock`'s file, never committed (the finalizer's
    own bookkeeping commit `git reset`s it back out by name). Stale ones
    accumulate on disk regardless: 46 of them across old finished runs were
    still THERE for the test-contract resolver's own change-scan to see as a
    changed gitignored path — the very thing that promoted every DIRECT job's
    slice to `full_command` for a run that had already finished. A run past
    MERGED/BLOCKED will not `register-lane` again, so nothing needs this file
    to still exist. Best-effort, never fatal, and called only AFTER any
    `with _run_dir_lock(...)` that covered this same transition has already
    exited — deleting the file this process is still holding open would
    leave a concurrent `_run_dir_lock` free to flock a freshly-created inode
    at the same path while this one's descriptor (and its lock) is still
    live."""
    # The rule, stated once: the lock goes when the RUN is terminal (MERGED or
    # BLOCKED), read from state.json — not when some other retirement happened
    # to return True (v3.4.6 review-1, item 6: two of three call sites were
    # gated on `_retire_lane_map`'s return value, the third was not).
    _st = _read_json(os.path.join(run_dir, "state.json"), None) or {}
    if str(_st.get("phase") or "").upper() not in ("MERGED", "BLOCKED"):
        return False
    try:
        os.remove(os.path.join(run_dir, ".run.lock"))
        return True
    except OSError:
        return False


def _load_manifest_dict(path):
    """The manifest as a dict, through the validator's loader (one parser)."""
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    try:
        import yaml  # noqa: WPS433
        return yaml.safe_load(text)
    except ImportError:
        pass
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_cv_validate_manifest_for_lane", os.path.join(HERE, "compound-v-validate-manifest.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.load_yaml(text)


def cmd_finalize_wave(argv):
    ap = argparse.ArgumentParser(prog="compound-v-emit-workflow.py finalize-wave")
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--repo-root", required=True,
                    help="the PROJECT root — the tree this wave merges into. "
                         "Never defaulted.")
    ap.add_argument("--manifest")
    ap.add_argument("--jobs", required=True,
                    help="comma-separated job ids belonging to THIS wave")
    ap.add_argument("--wave", type=int, default=0)
    ap.add_argument("--integration-gate", default=INTEGRATION_GATE_DEFAULT)
    ap.add_argument("--python", default=(sys.executable or "python3"))
    ap.add_argument("--manifest-digest",
                    help="sha256:<hex> the manifest MUST hash to, baked in by "
                         "`emit`. Verified here AND forwarded to the integration "
                         "authority: nothing merges against a lane map that "
                         "changed after review.")
    ap.add_argument("--now")
    ap.add_argument("--no-commit", action="store_true",
                    help="merge but do not commit; for tests only")
    args = ap.parse_args(argv)

    run_dir = os.path.abspath(args.run_dir)
    repo_root = os.path.abspath(args.repo_root)
    manifest_path = os.path.abspath(
        args.manifest or os.path.join(run_dir, "manifest.yaml")
    )
    job_ids = [j.strip() for j in args.jobs.split(",") if j.strip()]
    out = {"wave": args.wave, "integrated": False, "merged": [], "refused": []}

    def emit(code):
        print(json.dumps(out, indent=2, sort_keys=True))
        return code

    if not job_ids:
        out["reason"] = "--jobs named no job ids"
        return emit(2)
    if not os.path.exists(args.integration_gate):
        out["reason"] = (
            "the integration authority is not at %s. Nothing merges without it — "
            "an absent authority is a refusal, never a waiver" % args.integration_gate
        )
        return emit(2)
    fault = manifest_digest_fault(manifest_path, args.manifest_digest)
    if fault:
        out["reason"] = fault
        out["refused"] = job_ids
        return emit(1)

    # ---- 1. THE AUTHORITY, first ------------------------------------------- #
    _gate_argv = [
        args.python, "-B", args.integration_gate,
        "--run-dir", run_dir, "--repo-root", repo_root,
        "--manifest", manifest_path, "--jobs", ",".join(job_ids), "--json",
    ]
    if args.manifest_digest:
        _gate_argv += ["--manifest-digest", args.manifest_digest]
    rc, gate_out, gate_err = _run(_gate_argv)
    try:
        report = json.loads(gate_out) if gate_out.strip() else None
    except Exception:  # noqa: BLE001
        report = None
    if not isinstance(report, dict):
        out["reason"] = ("the integration authority produced no report (rc=%d): %s"
                         % (rc, (gate_err or gate_out)[:300]))
        return emit(1)

    manifest = {}
    if os.path.exists(manifest_path):
        try:
            manifest = _load_yaml(manifest_path) or {}
        except Exception:  # noqa: BLE001
            manifest = {}

    # ---- 1a. THE RUN'S `actual` — AFTER the authority, BEFORE the commit ---- #
    #
    # This is the pipeline's one write into a TRACKED file outside the run
    # directory, and its POSITION is the safety property. Record used to do it,
    # which put that append between a direct-mode job's gate and this authority's
    # re-derivation of the same tree: the digests disagreed and an honest receipt
    # was refused as `contradicted` (run v3.4-r6). 3.4.0 development answered that
    # by excluding the path from both digests — which also made a WORKER's rewrite
    # of it invisible, in a stream the pipeline commits by name and which resolves
    # last-writer-wins into the Tier-2 precision gate. The fourth review pass
    # withdrew the exclusion and moved the write here: the authority has already
    # re-derived this wave, so nothing it measures can be disturbed, and the
    # commit below is pathspec-restricted so this file is never swept into it.
    #
    # AFTER THE AUTHORITY RAN, NOT AFTER IT PERMITTED. A refused wave is still an
    # outcome the predicted<->actual join has to carry, and gating the append on
    # `permitted` would silently drop the `actual` for exactly the runs whose
    # outcome matters most. `_maybe_append_run_actual` is latched on state.json
    # and fires at most once per run, only once EVERY manifest job is terminal.
    with _run_dir_lock(run_dir):
        _fresh = _load_state(run_dir)
        _note = _maybe_append_run_actual(run_dir, manifest, _fresh, repo_root)
        if _note:
            out["triage_actual"] = _note
        _save_state(run_dir, _fresh, now=args.now)

    if report.get("integration") != "permitted":
        out["refused"] = report.get("refused") or job_ids
        out["reason"] = (
            "integration REFUSED by scripts/compound-v-integration-gate.py: %s. "
            "Nothing was merged and nothing was committed."
            % json.dumps(report.get("tally") or {})
        )
        # The workflow halts on this wave, so the RUN is halted: record it as
        # BLOCKED with the reason (see the same rule in `_apply`), so the run is
        # not left PARTITION_VERIFIED with jobs pending forever.
        with _run_dir_lock(run_dir):
            _halted = _load_state(run_dir)
            _halted["phase"] = "BLOCKED"
            _halted["blocked_reason"] = ("wave %s: %s" % (args.wave, out["reason"]))[:300]
            _halted["blocked_at"] = args.now or _utc_stamp()
            _save_state(run_dir, _halted, now=args.now)
        if _retire_lane_map(run_dir):
            out["lane_map_retired"] = True
        _retire_run_lock(run_dir)
        return emit(1)

    # ---- 2. merge the permitted slices ------------------------------------- #
    # Read once for the git work; every WRITE goes through _apply below, which
    # re-reads under the run-dir lock. The finalizer is serialized by the wave
    # loop, but a straggler Record from a relaunched wave is not, and an unlocked
    # read-modify-write here would erase whatever it had just written.
    state = _load_state(run_dir)
    job_updates = {}

    def _apply(now=None):
        with _run_dir_lock(run_dir):
            fresh = _load_state(run_dir)
            for jid, updates in job_updates.items():
                fresh["jobs"].setdefault(jid, {}).update(updates)
            fresh.setdefault("waves", {})[str(args.wave)] = {
                "jobs": job_ids, "merged": out["merged"],
                "commit": out.get("commit"), "integrated": out.get("integrated"),
            }
            # THE PHASE ADVANCE IS THIS FINALIZER'S, NOT A PROSE STEP. Until
            # 3.4.1 only /v:dispatch step 9 — a human step — wrote MERGED, and
            # fourteen finished runs of one night sat at PARTITION_VERIFIED: the
            # dashboard called every one of them unfinished for 72 hours and the
            # triage hook stayed silent for the whole repository (stage-1
            # finding 45). A wave that integrated moves the run to DISPATCHED;
            # the wave after which every manifest job is integrated moves it to
            # MERGED. A refused wave leaves the phase alone.
            if out.get("integrated"):
                _all_ids = [str(j.get("id")) for j in (manifest.get("jobs") or [])
                            if isinstance(j, dict) and j.get("id")]
                _done = bool(_all_ids) and all(
                    ((fresh["jobs"].get(_j) or {}).get("merged") or {}).get("integrated")
                    for _j in _all_ids)
                fresh["phase"] = "MERGED" if _done else "DISPATCHED"
                if _done:
                    fresh["merged_at"] = now or _utc_stamp()
                    if _retire_lane_map(run_dir):
                        out["lane_map_retired"] = True
            elif out["refused"]:
                # A refused job halts the workflow (the script stops on a wave
                # that did not integrate), so the RUN is halted: say BLOCKED,
                # with the reason, instead of leaving PARTITION_VERIFIED with
                # jobs pending forever. The banner still lists it (unfinished);
                # the triage hook's narrower question (`--open-jobs`) excludes a
                # BLOCKED run, so a halted run no longer silences sizing for the
                # follow-up that repairs it (stage-2 r2, finding 47's residual).
                fresh["phase"] = "BLOCKED"
                fresh["blocked_reason"] = ("wave %s refused: %s" % (
                    args.wave, ", ".join(out["refused"])))[:300]
                fresh["blocked_at"] = now or _utc_stamp()
                if _retire_lane_map(run_dir):
                    out["lane_map_retired"] = True
            _save_state(run_dir, fresh, now=now)

    merged_worktrees = {}
    post_images = {}
    approved = []
    for job_id in job_ids:
        job = _manifest_job(manifest, job_id) or {"id": job_id}
        state_job = state["jobs"].get(job_id) or {}
        result = _read_json(os.path.join(run_dir, "results", "%s.json" % job_id), None)
        if not isinstance(result, dict) or result.get("status") != "success":
            out["refused"].append(job_id)
            continue
        files = [p for p in (result.get("files_changed") or []) if p]
        isolation = job.get("isolation") or state_job.get("isolation") or "direct"
        realised = state_job.get("realised_commit")
        pinned = read_pinned_baseline(run_dir, job_id, state_job)

        # ---- THE SEALED ARTIFACT, and what git says about it ---------------- #
        gate_doc = _read_json(
            os.path.join(run_dir, "receipts", "%s.gate.json" % job_id), None)
        # WHERE THE AGENT ACTUALLY RAN decides how to merge — and the gate
        # receipt says so in the emitter's own words (`--mode`, written into the
        # script by this file, never by the agent). The manifest's `isolation` is
        # a scope-attribution label that a dependent job keeps as `worktree`
        # while its agent runs direct (3.0.5 rule); reading only the label
        # refused every such job with "resolves to no worktree" (finding 60).
        isolation = _gate_mode_from_receipt(gate_doc) or isolation
        sealed, seal_err = read_sealed_patch(run_dir, job_id, gate_doc)
        if seal_err:
            out["refused"].append(job_id)
            out["reason"] = "sealed patch unusable for %s: %s" % (job_id, seal_err)
            break
        image = None
        if sealed is not None and pinned:
            image, img_err = sealed_post_image(repo_root, pinned, sealed)
            if img_err:
                out["refused"].append(job_id)
                out["reason"] = ("cannot derive the post-image of %s's sealed "
                                 "patch: %s" % (job_id, img_err))
                break
            post_images[job_id] = image
            if image:
                files = sorted(image)

        # ---- ALREADY MERGED? ASK GIT, NOT state.json ------------------------ #
        # `state.json` is exempt by name from the scope gate and writable by a
        # direct worker, so `merged.integrated: true` is a CACHE line, not a
        # proof. Reading it as one let a forged entry skip a job's merge entirely
        # — the finalizer would report it merged, and the work would never land.
        # Git is asked instead: is this artifact's post-image already in HEAD?
        # The cache is still consulted, but only as a hint about which jobs to
        # ask about, never as the answer.
        if image:
            proven, _why = head_matches_post_image(repo_root, image)
            if proven:
                approved.extend(files)
                out["merged"].append(job_id)
                job_updates[job_id] = {
                    "merged": {"realised_commit": realised, "mode": isolation,
                               "integrated": True, "proof": "head-matches-artifact"}}
                continue  # at-most-once, proven from git
        elif sealed is None:
            merged_record = state_job.get("merged") or {}
            if realised and merged_record.get("realised_commit") == realised \
                    and merged_record.get("integrated"):
                # No artifact to prove anything against (a pre-3.4.0 receipt), so
                # the old cache-only test is all there is. Recorded as such.
                approved.extend(files)
                out["merged"].append(job_id)
                out.setdefault("unproven_skips", []).append(job_id)
                continue

        if isolation == "worktree":
            # The receipt names the tree the gate measured — first (finding 89:
            # result and state both carried "" for a dependent job that ran in a
            # real worktree, and this refused "resolves to no worktree").
            worktree = ((gate_doc or {}).get("worktree") if isinstance(gate_doc, dict) else None) \
                or result.get("worktree") or state_job.get("worktree")
            if not worktree:
                out["refused"].append(job_id)
                out["reason"] = (
                    "job %s is isolation:worktree but resolves to no worktree; "
                    "there is nothing to merge FROM, so it fails closed" % job_id
                )
                break
            if sealed is not None:
                # APPLY THE ARTIFACT, never a fresh diff of the live tree. The
                # worktree is not read at all here — it may have been reverted,
                # rebuilt or filled with test byproducts since the gate ran, and
                # none of that may change what lands.
                ok, err = apply_patch(repo_root, sealed)
            else:
                ok, err = merge_back(worktree, repo_root, pinned, files)
            if not ok:
                out["refused"].append(job_id)
                out["reason"] = "merge-back failed for %s: %s" % (job_id, err)
                break
            # Remembered HERE, from the value this pass actually merged. The
            # cleanup below must never re-read this from state.json — see the
            # comment there. An idempotent re-finalize (`continue` above) never
            # reaches this line, so a job whose work was already merged in an
            # earlier pass is never a cleanup candidate either.
            merged_worktrees[job_id] = worktree
        # A `direct` job changed the checkout in place; there is nothing to apply,
        # only something to commit.
        approved.extend(files)
        job_updates[job_id] = {"merged": {"realised_commit": realised,
                                          "mode": isolation, "integrated": True}}
        out["merged"].append(job_id)

    # ---- 3. COMMIT -------------------------------------------------------- #
    # Reached even when the loop BROKE on a refusal. A sibling that already
    # merged has its patch in the index; returning early would leave it staged
    # and uncommitted, which is CRITICAL 2's own shape — an ungated-looking patch
    # waiting for someone else's `git commit` to sweep it in. Everything staged
    # here was permitted by the authority, so it is committed; the refusal is
    # still a refusal, `integrated` stays false, and the wave loop halts.
    unique = []
    for path in approved:
        if path not in unique:
            unique.append(path)
    if args.no_commit:
        out["reason"] = "merged but not committed (--no-commit)"
    else:
        message = "compound-v: wave %d of run %s (%s)" % (
            args.wave,
            state.get("run_id") or os.path.basename(run_dir),
            ", ".join(out["merged"]) or "no jobs",
        )
        sha, err = _commit_paths(repo_root, unique, message)
        if err:
            out["reason"] = err
            out["integrated"] = False
            _apply(now=args.now)
            # `_apply`'s own `with _run_dir_lock(...)` has released by the time
            # it returns, so retiring the lock file here (never inside that
            # `with`) cannot race the lock this same process still holds.
            _retire_run_lock(run_dir)
            return emit(1)
        if sha:
            out["commit"] = sha
            for job_id in out["merged"]:
                merged = dict(job_updates.get(job_id, {}).get("merged") or {})
                merged.update({"commit": sha, "integrated": True})
                job_updates.setdefault(job_id, {})["merged"] = merged
        else:
            out["commit"] = _head_commit(repo_root) or ""
            # TWO DIFFERENT SITUATIONS, and dogfood 16 showed them wearing one
            # message. "Nothing to commit" because the work is already in HEAD is a
            # clean idempotent re-finalize. "Nothing to commit" because every job
            # was REFUSED is the opposite: nothing was merged and nothing should
            # have been. Reporting the second as the first told a reader that
            # refused work was already in HEAD — a refusal explained as a success,
            # which is the third time in this release line that a correct decision
            # arrived under the wrong name.
            if out["refused"] and not out["merged"]:
                # Keep the SPECIFIC refusal (a merge-back error names its cause);
                # this generic line was overwriting it, and r4's "pathspec did
                # not match" had to be reproduced by hand to be seen at all.
                generic = (
                    "nothing was merged: every job in this wave was refused (%s). "
                    "HEAD is unchanged by this wave."
                    % ", ".join(out["refused"])
                )
                out["reason"] = ("%s — %s" % (out["reason"], generic)
                                 if out.get("reason") else generic)
            else:
                out["reason"] = ("nothing left to commit — this wave's work is "
                                 "already in HEAD (idempotent re-finalize)")

    # ---- PROVE THE COMMIT CARRIES THE ARTIFACT ----------------------------- #
    # Asked of git, after the commit and before anything is deleted: for every job
    # whose patch was sealed, is that patch's post-image what HEAD now holds?
    #
    # This is the check whose absence destroyed work. A worktree reverted to its
    # baseline after the gate produced an empty fresh diff, the finalizer read
    # that as "already landed", marked the job integrated and pruned the tree —
    # the only copy. Nothing in that chain ever asked git whether the content was
    # actually there. A job that cannot be proven is NOT pruned and the wave does
    # not report itself integrated; the worktree stays for a human to look at.
    unproven = []
    if not args.no_commit:
        for job_id in list(out["merged"]):
            image = post_images.get(job_id)
            if not image:
                continue
            proven, why = head_matches_post_image(repo_root, image)
            if not proven:
                unproven.append("%s: %s" % (job_id, why))
    if unproven:
        out["unproven"] = unproven
        generic = ("the commit does not carry the sealed patch for %d job(s): %s. "
                   "Nothing is pruned — a worktree is retired only after git "
                   "confirms its diff is in HEAD." % (len(unproven),
                                                      "; ".join(unproven)[:400]))
        out["reason"] = ("%s — %s" % (out["reason"], generic)
                         if out.get("reason") else generic)

    out["integrated"] = not out["refused"] and not unproven
    if out["refused"]:
        out.setdefault("reason", "some jobs did not reach `success`")

    # ---- RETIRE THE WORKTREES THIS WAVE ACTUALLY MERGED --------------------- #
    # A worktree whose diff is committed to the project is dead weight, and the
    # runtime only auto-removes the ones that CHANGED NOTHING. Eleven runs into a
    # day of dogfooding this repository had nineteen of them, and they are not
    # merely untidy: `git status` fills up, and in `direct` mode the scope gate —
    # which deliberately sees gitignored paths — attributed all fifteen leftovers
    # to the next job and blocked it. Dogfood 10 died of exactly that.
    #
    # ONLY the merged ones. A refused job's worktree still holds the work someone
    # will want to look at, and deleting it would destroy the one copy — the v2.6.4
    # incident in this project was `git worktree remove` taking an audit trail with
    # it, and the lesson was to be specific about what is safe to drop.
    #
    # Best-effort and never fatal: a wave that integrated correctly must not be
    # reported as failed because a directory could not be unlinked.
    # AND ONLY WHEN THIS PASS PRODUCED A COMMIT. A re-finalize whose merge-back
    # applied nothing (`sha` is None) has not put the worktree's diff in HEAD, and
    # `git worktree remove --force` on it destroys the one copy of the work —
    # which is what happened on 2026-09-02 to job triage-hook of run
    # v3.4-native-first-r2 (recovered from the agent transcript). A worktree is
    # retired only after the commit that carries its diff exists.
    pruned, prune_errors = [], []
    if out["merged"] and not args.no_commit and out.get("commit") and merged_worktrees \
            and not unproven \
            and not str(out.get("reason") or "").startswith("nothing left to commit"):
        for job_id in out["merged"]:
            # THE PATH THAT WAS ACTUALLY MERGED, recorded locally at merge time —
            # not re-read from state.json. A cross-model review called the re-read
            # CRITICAL: `state.json` is exempt by name, so a worker can rewrite
            # another job's `worktree` locator, and this loop would then
            # `--force`-delete a REFUSED job's tree — destroying the one copy of
            # work the refusal exists to preserve, which is the exact outcome the
            # comment above promises cannot happen.
            wt = merged_worktrees.get(job_id)
            if not (isinstance(wt, str) and wt.strip()):
                continue
            wt = os.path.abspath(wt.strip())
            # Never outside the project, never the project itself.
            if wt == os.path.abspath(repo_root):
                continue
            if os.path.relpath(wt, repo_root).startswith(".." + os.sep):
                continue
            rc, _o, err = _run(["git", "-C", repo_root, "worktree", "remove",
                                "--force", wt])
            if rc == 0:
                pruned.append(job_id)
            else:
                prune_errors.append("%s: %s" % (job_id, (err or "").strip()[:120]))
        if pruned:
            _run(["git", "-C", repo_root, "worktree", "prune"])
    if pruned:
        out["worktrees_pruned"] = pruned
    if prune_errors:
        out["worktrees_prune_errors"] = prune_errors

    # ---- BEST-EFFORT scorecard refresh, after a successful wave commit ------ #
    # The scorecard is regenerated FROM FILES (manifest jobs x results/*.json),
    # so this is a convenience re-run, never the source of truth -- a run whose
    # finalize is skipped or fails here is just as readable next time someone
    # runs the scorecard by hand. Never fatal: a wave that integrated correctly
    # must not be reported as failed because the scorecard update hiccuped.
    if out["integrated"]:
        scorecard_script = os.path.join(HERE, "compound-v-scorecard.py")
        exec_root = os.path.dirname(run_dir.rstrip(os.sep)) or run_dir
        if os.path.exists(scorecard_script) and os.path.isdir(exec_root):
            rc_sc, _out_sc, err_sc = _run([
                args.python, "-B", scorecard_script, "--update",
                "--from-runs", exec_root,
            ], cwd=repo_root)
            if rc_sc == 0:
                out["scorecard_updated"] = True
            else:
                out["scorecard_update_error"] = (err_sc or "").strip()[:200]

    _apply(now=args.now)
    # Same rule as the refusal path above: `_apply`'s own run-dir lock has
    # already been released, so the retirement runs here, never inside it.
    _retire_run_lock(run_dir)

    # ---- COMMIT THE RUN'S OWN RECORD, separately from the work -------------- #
    # The audit-trail gate requires a committed state.json, and finishing a
    # branch removes worktrees — an uncommitted run dir is exactly what the
    # v2.6.4 incident lost. Until 3.4.1 this commit was the orchestrator's by
    # hand after every wave. It is NEVER folded into the wave commit, which
    # carries the sealed patch and nothing else (that is what the authority
    # proves); it is a second, plain commit of pipeline-owned paths only: the
    # run directory (minus its lock) and the two memory streams Record and the
    # scorecard append to. Best-effort: a wave that integrated is not reported
    # failed because its bookkeeping could not be committed.
    # WHENEVER THIS WAVE MOVED HEAD — not only when it integrated. Stage-2 r1
    # merged four jobs and refused one: HEAD moved, and gating this on
    # `integrated` left state/receipts/results untracked, which the audit-trail
    # gate reds on push (finding 56). A refused job's evidence is exactly the
    # record a human needs committed.
    if (out["merged"] or out["refused"]) and out.get("commit") and not args.no_commit:
        _bk_rel = _stage_run_bookkeeping(repo_root, run_dir)
        if _bk_rel:
            _rc_q, _, _ = _run(["git", "-C", repo_root, "diff", "--cached", "--quiet"])
            if _rc_q != 0:
                _rc_bk, _, _err_bk = _run([
                    "git", "-C", repo_root, "commit", "-q", "-m",
                    "bookkeeping(%s): wave %s finalized" % (
                        os.path.basename(os.path.normpath(run_dir)), args.wave)])
                if _rc_bk == 0:
                    out["bookkeeping_commit"] = _head_commit(repo_root) or ""
                else:
                    out["bookkeeping_error"] = (_err_bk or "").strip()[:200]
    return emit(0 if out["integrated"] else 1)
