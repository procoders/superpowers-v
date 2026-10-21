"""Re-attempts and supersession, register-lane, resume-prepare and integrated-jobs."""

from __future__ import annotations

import os
import sys
import argparse
import datetime
import json
import subprocess
import time

from .util import (
    FASTPATH_DEFAULT, _run, _git, _atomic_write, _run_dir_lock, _read_json, lane_map_path,
    test_contract_path, register_lane, _load_state, _save_state, _head_commit, _manifest_job,
)
from .digest import (
    sha256_file,
)
from .recall import (
    load_recall_argument,
)
from .prompts import (
    worker_prompt_path, launch_argv_path, baseline_pin_path, read_pinned_baseline,
)
from .plan import (
    _provision_spec,
)
from .gate import (
    _file_digest, write_preexisting, _preexisting_snapshot, _resolve_test_contract,
)
from .finalize import (
    _load_manifest_dict,
)


# --------------------------------------------------------------------------- #
# re-attempt detection and supersession (v3.6.3)
#
# `register-lane` pinned `jobs/<id>.baseline` ONCE and, before this, never
# rewrote it — only `resume-prepare` (called by `/v:resume`) cleared it. That
# left a door `/v:resume` does not guard: a human re-running `/v:dispatch` on a
# halted run directory gets a fresh worktree branched from the CURRENT HEAD, but
# the gate still diffs against the FIRST attempt's pin, so every bookkeeping
# commit the pipeline made between attempts (`manifest.yaml`,
# `dispatch.workflow.js`, `state.json`, `results/<id>.json`,
# `preexisting/<id>.txt`) is charged to the job as an out-of-lane write — finding
# 146 (2026-09-03), reached through the un-guarded door.
# --------------------------------------------------------------------------- #
def _prior_attempt_concluded(run_dir, job_id, state_entry):
    """True iff a PREVIOUS attempt at `job_id` reached a pipeline-written
    conclusion and was never integrated.

    "Concluded" means a gate receipt (`receipts/<id>.gate.json`) or a Record
    result (`results/<id>.json`) already exists on disk — both are written by
    the PIPELINE (the gate / Record), never by the worker, which is why this is
    a signal `register-lane` can trust without asking the worker anything — for
    a WORKTREE job. Its lane is the worktree; the run directory lives in the
    checkout, outside every worktree lane, and even a worker that reached it
    would gain nothing from a re-pin: the gate diffs the sealed patch against
    the new pin, so a commit hidden behind it never merges. A DIRECT worker can
    write anywhere in the checkout, including a forged `results/<id>.json`,
    which is why the caller only ever re-pins in worktree mode and, in direct
    mode, refuses a stale pin instead (exit 2, naming `/v:resume`).

    `merged.integrated: true` vetoes it — an integrated job's registration is
    not a re-attempt at anything; there is nothing left to supersede.
    """
    merged = (state_entry or {}).get("merged") or {}
    if isinstance(merged, dict) and merged.get("integrated"):
        return False
    receipt = os.path.join(run_dir, "receipts", "%s.gate.json" % job_id)
    if os.path.exists(receipt):
        return True
    result = os.path.join(run_dir, "results", "%s.json" % job_id)
    if not os.path.exists(result):
        return False
    # A result this attempt already superseded is not a NEW conclusion: without
    # this, every registration inside attempt 2 re-photographed the tree and
    # forgave whatever the worker had already written outside its lane.
    return sha256_file(result) != (state_entry or {}).get("superseded_result")


def _resume_in_place(entry):
    """A codex worktree job `resume-prepare` deliberately leaves pinned: its
    failure was environmental, its session is recorded and its worktree exists,
    so `codex exec resume <uuid>` continues it (commands/v-resume.md)."""
    wt = entry.get("worktree")
    return bool(entry.get("failure_class") in ("timeout", "network")
                and entry.get("session_id")
                and isinstance(wt, str) and wt and os.path.isdir(wt))


def _reattempt_guidance(run_dir):
    run_id = os.path.basename(os.path.normpath(run_dir))
    return ("run `/v:resume %s` — or, by hand, `compound-v-emit-workflow.py "
            "resume-prepare --run-dir %s` — before dispatching again: it retires "
            "the previous attempt's pin and bookkeeping so the gate measures "
            "this attempt from the current HEAD." % (run_id, run_dir))


def _stale_attempt_pins(run_dir, job_ids, head):
    """{job_id: pin} for every job a fresh dispatch would run again although a
    concluded previous attempt (a receipt or result on disk) still holds a pin
    that is no longer `head`: not integrated, not superseded, not a
    resume-in-place job. A pin equal to HEAD charges the job with nothing."""
    jobs = (_load_state(run_dir).get("jobs") or {})
    stale = {}
    for job_id in job_ids:
        entry = jobs.get(job_id)
        entry = entry if isinstance(entry, dict) else {}
        if _resume_in_place(entry) or not _prior_attempt_concluded(run_dir, job_id, entry):
            continue
        pin = read_pinned_baseline(run_dir, job_id, entry)
        if pin and pin != head:
            stale[job_id] = pin
    return stale


# Run-dir files `register-lane` rewrites for a job on every registration: their
# attempt-1 digests can never match attempt 2's bytes. Nothing else is re-hashed.
SUPERSEDE_REHASH = ("jobs/{id}.baseline", "jobs/{id}.test-contract.json",
                    "lane-map.json", "preexisting/{id}.verified.txt")


def _retire_snapshot(run_dir, job_id, isolation):
    snap = os.path.join(run_dir, "preexisting", "%s.txt" % job_id)
    verified = os.path.join(run_dir, "preexisting", "%s.verified.txt" % job_id)
    if isolation == "worktree":
        cleared = False
        for p in (snap, verified):
            if os.path.exists(p):
                os.remove(p)
                cleared = True
        return "cleared" if cleared else None
    if os.path.exists(verified):
        os.remove(verified)
    if not os.path.isfile(snap):
        return None
    targets = [os.path.join(run_dir, t.replace("{id}", job_id)).replace(os.sep, "/")
               for t in SUPERSEDE_REHASH]
    with open(snap, "r", encoding="utf-8") as fh:
        lines = [ln.rstrip("\n") for ln in fh if ln.strip()]
    kept = []
    for ln in lines:
        parts = ln.split("  ", 1)
        rel = parts[1].strip() if len(parts) == 2 else ln.strip()
        # Matched as a path suffix of the run-dir file itself, so a symlinked
        # spelling of the repo root (/var vs /private/var) cannot defeat it.
        if any(t.endswith("/" + rel) for t in targets):
            continue
        kept.append(ln)
    _atomic_write(snap, "\n".join(kept) + ("\n" if kept else ""))
    return "rehash:%d" % (len(lines) - len(kept))


def _supersede_attempt(run_dir, job_id, entry, wts, keep_cwd=None, isolation=None):
    """Retire a concluded attempt at `job_id`: unpin its baseline, reset it to
    `pending`, drop its lane-map worktree entries, and archive its gate receipt
    so the integration authority never reads a superseded attempt's verdict as
    the current one's.

    Factored out of `cmd_resume_prepare`, which was the only caller until
    `cmd_register_lane` gained its own re-attempt door (v3.6.3) — the archive
    tag/collision logic is moved here verbatim, not duplicated.

    Mutates `entry` (a `state["jobs"][job_id]` dict) and `wts` (a
    `lane-map.json` `"worktrees"` mapping, or `None`) IN PLACE; the caller is
    responsible for saving both under its own `_run_dir_lock`. `keep_cwd`, when
    given, is a worktree path this call must NOT drop from `wts` even if it is
    currently mapped to `job_id` — used when the caller is about to register
    that exact path itself, so a lane-map cleanup pass here can't undo work its
    own caller hasn't done yet.

    The before-image is retired too, by isolation (`isolation`, else the
    entry's own): a worktree job's snapshot describes a tree that is gone, so
    both files are deleted and the next registration re-provisions. A direct
    job's snapshot is KEPT — re-photographing the checkout would excuse whatever
    a halted attempt left out of lane — and only the lines for the files
    registration itself rewrites (`SUPERSEDE_REHASH`) are dropped, so the next
    `register-lane` digests them afresh instead of carrying attempt 1's bytes.

    Returns `{"was": <old pinned baseline sha, or None>,
              "lane_entries_dropped": <int>,
              "receipt_archived": <path relative to run_dir, or None>,
              "snapshot": "cleared" | "rehash:<n>" | None}`.
    """
    was = read_pinned_baseline(run_dir, job_id, entry)
    snapshot = _retire_snapshot(run_dir, job_id,
                                isolation or entry.get("isolation") or "direct")
    pin_path = baseline_pin_path(run_dir, job_id)
    if os.path.exists(pin_path):
        os.remove(pin_path)
    entry.pop("baseline", None)
    entry["status"] = "pending"
    entry["worktree"] = None
    _result = os.path.join(run_dir, "results", "%s.json" % job_id)
    if os.path.isfile(_result):
        entry["superseded_result"] = sha256_file(_result)
    lane_entries_dropped = 0
    if wts is not None:
        dropped = [cwd for cwd, jid in wts.items()
                  if jid == job_id and cwd != keep_cwd]
        for cwd in dropped:
            wts.pop(cwd, None)
        lane_entries_dropped = len(dropped)
    receipt_archived = None
    receipt = os.path.join(run_dir, "receipts", "%s.gate.json" % job_id)
    if os.path.exists(receipt):
        doc = _read_json(receipt, None) or {}
        tag = (str(doc.get("realised_commit") or "")[:12]
               or datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
        dest = os.path.join(run_dir, "receipts", "%s.gate.superseded-%s.json" % (job_id, tag))
        n = 2
        while os.path.exists(dest):  # a second attempt at the same commit must not clobber the first
            dest = os.path.join(run_dir, "receipts", "%s.gate.superseded-%s-%d.json" % (job_id, tag, n))
            n += 1
        os.replace(receipt, dest)
        receipt_archived = os.path.relpath(dest, run_dir)
    return {"was": was, "lane_entries_dropped": lane_entries_dropped,
            "receipt_archived": receipt_archived, "snapshot": snapshot}


# --------------------------------------------------------------------------- #
# register-lane
# --------------------------------------------------------------------------- #
def cmd_register_lane(argv):
    ap = argparse.ArgumentParser(prog="compound-v-emit-workflow.py register-lane")
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--job-id", required=True)
    ap.add_argument("--cwd",
                    help="the job's working tree. Omitted, it is the directory "
                         "this command runs in.")
    ap.add_argument("--manifest")
    ap.add_argument("--repo-root", required=True,
                    help="the PROJECT root. Required: a direct job's baseline is "
                         "this tree's HEAD, and it is never defaulted.")
    ap.add_argument("--isolation", required=True,
                    choices=["direct", "worktree"],
                    help="from the MANIFEST. Decides which tree the baseline is "
                         "pinned from; never inferred from --cwd.")
    ap.add_argument("--agent-id",
                    help="the PreToolUse payload's agent_id, IF the runtime ever "
                         "exposes it to the agent itself. It does not on 2.1.238.")
    ap.add_argument("--fastpath", default=FASTPATH_DEFAULT)
    ap.add_argument("--python", default=(sys.executable or "python3"))
    ap.add_argument("--no-test-contract", action="store_true",
                    help="skip resolving this job's test contract (the lane map "
                         "is still written)")
    ap.add_argument("--recall-check-json", dest="recall_check_json",
                    help="this job's EMIT-TIME recall verdict, recorded into "
                         "state.json: a path to the JSON `emit` wrote (the usual "
                         "form, and what the prompt hands you) or the JSON "
                         "document itself. Unreadable input is noted, never a "
                         "refusal — recall is evidence, and a job must not fail "
                         "to start because a memory read did.")
    args = ap.parse_args(argv)
    args.cwd = os.path.abspath(args.cwd or os.getcwd())
    run_dir = os.path.abspath(args.run_dir)
    # ---- A REPOSITORY WITH NO FIRST COMMIT: refused before anything is written.
    _pin_root = (os.path.abspath(args.repo_root) if args.isolation == "direct"
                 else args.cwd)
    if (os.path.isdir(_pin_root) and not _head_commit(_pin_root)
            and _git(_pin_root, ["rev-parse", "--git-dir"])[0] == 0):
        sys.stderr.write(
            "cannot pin a baseline: %s is a git repository with no commits yet. "
            "Make a first commit (for example `git add -A && git commit -m "
            "\"initial commit\"`) and dispatch again.\n" % _pin_root)
        return 2
    # An external job's wrapper (backend != claude) is listed, never a claim on
    # the checkout (finding 78). Read the backend off the manifest when given.
    _is_external_wrapper = False
    # DEFAULTED, exactly as `record` defaults it. The emitted prompt's register-lane
    # command carries no `--manifest`, so a manifest read only when the flag is
    # present is a manifest never read in a real run — and everything downstream of
    # it (the backend flag, and now the job's `provision_command`) would be dead
    # code that every selftest passing `--manifest` by hand would still exercise.
    _reg_manifest_path = os.path.abspath(
        args.manifest or os.path.join(run_dir, "manifest.yaml"))
    _reg_manifest = {}
    _reg_job = None
    if os.path.exists(_reg_manifest_path):
        try:
            _reg_manifest = _load_manifest_dict(_reg_manifest_path) or {}
            _reg_job = _manifest_job(_reg_manifest, args.job_id) if isinstance(_reg_manifest, dict) else None
            _is_external_wrapper = bool(_reg_job) and str(_reg_job.get("backend") or "claude") != "claude"
        except Exception:  # noqa: BLE001 — an unreadable manifest is the validator's problem, not this flag's
            _reg_manifest, _reg_job = {}, None
            _is_external_wrapper = False

    # ---- RE-ATTEMPT: retire a concluded previous attempt, BEFORE this lane is
    # registered (v3.6.3) ----------------------------------------------------
    # Must run before `register_lane(...)` below: that call is what adds THIS
    # registration's worktree entry to lane-map.json, and the worktree branch's
    # lane-map cleanup (inside `_supersede_attempt`) must not run after it and
    # drop the very entry being added. `keep_cwd` is a second guard against the
    # same hazard, not a substitute for the ordering.
    _reg_ack_reattempt = None
    _reg_ack_stale_pin_warning = None
    _reg_state_peek = _load_state(run_dir)
    _reg_state_entry = (_reg_state_peek.get("jobs") or {}).get(args.job_id) or {}
    if args.isolation == "worktree" and _prior_attempt_concluded(
            run_dir, args.job_id, _reg_state_entry):
        with _run_dir_lock(run_dir):
            _reg_state = _load_state(run_dir)
            _reg_entry = _reg_state["jobs"].setdefault(args.job_id, {})
            _reg_lm = _read_json(lane_map_path(run_dir), None)
            _reg_wts = (_reg_lm.get("worktrees")
                       if isinstance(_reg_lm, dict) and isinstance(_reg_lm.get("worktrees"), dict)
                       else None)
            # The old before-image is for a DIFFERENT worktree, so the helper
            # deletes it and the branch below re-runs `provision_command`.
            _reg_result = _supersede_attempt(
                run_dir, args.job_id, _reg_entry, _reg_wts,
                keep_cwd=args.cwd, isolation="worktree")
            if _reg_wts is not None:
                _reg_lm["worktrees"] = _reg_wts
                _atomic_write(lane_map_path(run_dir),
                              json.dumps(_reg_lm, indent=2, sort_keys=True) + "\n")
            _save_state(run_dir, _reg_state)
        _reg_ack_reattempt = {
            "superseded_receipt": _reg_result["receipt_archived"],
            "unpinned_was": _reg_result["was"],
            "snapshot_cleared": _reg_result["snapshot"] == "cleared",
        }
    elif args.isolation == "direct":
        # A direct worker can write ANYWHERE in the checkout, including a forged
        # `results/<id>.json`, so the one-shot pin is never rewritten here. A pin
        # that no longer matches HEAD on a job that has not integrated is a
        # previous attempt's: the gate would charge this one with every commit
        # since, so the call is REFUSED before it writes anything. Keyed on the
        # pin, not on a concluded receipt, so an attempt that died before Gate
        # is refused too.
        _reg_merged = _reg_state_entry.get("merged") or {}
        _reg_existing_pin = read_pinned_baseline(run_dir, args.job_id, _reg_state_entry)
        _reg_current_head = _head_commit(os.path.abspath(args.repo_root))
        if (_reg_existing_pin and _reg_current_head
                and _reg_existing_pin != _reg_current_head
                and not (isinstance(_reg_merged, dict) and _reg_merged.get("integrated"))):
            _reg_ack_stale_pin_warning = (
                "the pinned baseline %s predates HEAD %s; the gate would charge "
                "this job with every commit made since — %s"
                % (_reg_existing_pin, _reg_current_head, _reattempt_guidance(run_dir)))
            sys.stderr.write("REFUSING TO REGISTER direct job %s: %s\n"
                             % (args.job_id, _reg_ack_stale_pin_warning))
            print(json.dumps({"registered": None, "refused": args.job_id,
                              "stale_pin_warning": _reg_ack_stale_pin_warning},
                             indent=2, sort_keys=True))
            return 2

    lane = register_lane(
        run_dir, args.job_id, args.cwd,
        manifest_path=args.manifest, agent_id=args.agent_id, wrapper=_is_external_wrapper,
    )
    ack = {"registered": args.job_id,
           "worktrees": len(lane.get("worktrees") or {}),
           "agents": len(lane.get("agents") or {})}
    if _reg_ack_reattempt is not None:
        ack["reattempt"] = _reg_ack_reattempt
    if _reg_ack_stale_pin_warning:
        ack["stale_pin_warning"] = _reg_ack_stale_pin_warning

    # ---- SNAPSHOT WHAT WAS ALREADY DIRTY, before the implementer runs ------ #
    # Direct mode only. The gate measures the whole tree against the baseline, so
    # without a before-picture it attributes pre-existing dirt to this job. The
    # first live Engine C run (2026-09-01) was BLOCKED by exactly that: leftover
    # probe records and stray .pyc files, not by anything its job did.
    #
    # Taken HERE because this is the only point that provably precedes the work.
    # A snapshot taken later could not distinguish "was already there" from "the
    # job just wrote it", which is the whole property being bought.
    if (args.isolation or "direct") != "worktree":
        try:
            pre = _preexisting_snapshot(args.repo_root, sys.executable)
            snap_p = os.path.join(run_dir, "preexisting", "%s.txt" % args.job_id)
            os.makedirs(os.path.dirname(snap_p), exist_ok=True)
            # ONE-SHOT. A second `register-lane` for the same job must not re-take
            # the picture: the clamp admits repeated calls, so a worker that made
            # its changes and then re-registered could refresh the snapshot to
            # cover them. Re-running is otherwise legitimate (resume does it), so
            # this refuses the REWRITE rather than the call.
            if not os.path.exists(snap_p):
                ack["preexisting"] = write_preexisting(snap_p, args.repo_root, pre)
            else:
                ack["preexisting"] = "unchanged (snapshot already taken)"
        except Exception as exc:  # noqa: BLE001
            # Fail OPEN into a stricter gate, never a looser one: with no snapshot
            # the gate subtracts nothing and a dirty tree blocks. Loud, not silent.
            ack["preexisting_error"] = str(exc)
    else:
        # ---- WORKTREE MODE: PROVISION, THEN PHOTOGRAPH ---------------------- #
        # A fresh worktree starts clean and therefore starts WITHOUT the
        # dependencies the repository's own toolchain needs. A job that runs
        # `npm ci` or `pip install -e .` to get its tests to run then owns
        # `node_modules/` in the gate's eyes, and is BLOCKED for writes it was
        # required to make. The four external worker scripts already solve this
        # for themselves; a Claude job in a runtime-provided worktree has no
        # worker script, so this command is that half.
        #
        # ORDER IS THE WHOLE SAFETY ARGUMENT, and it is the same argument as
        # direct mode's: the command runs HERE, before the implementer has been
        # given anything to do, so the snapshot separates "the install put it
        # there" from "the job wrote it". The snapshot binds each path to its
        # bytes, so a dependency file the job later REWRITES is gated like any
        # other write; the subtraction forgives presence, never content.
        #
        # The model never runs this command and cannot choose it: it comes from
        # the manifest a human reviewed, and register-lane is the pipeline's own
        # tool call, not the job's.
        _prov_cmd, _prov_timeout = _provision_spec(_reg_manifest, _reg_job or {})
        snap_p = os.path.join(run_dir, "preexisting", "%s.txt" % args.job_id)
        if _prov_cmd and os.path.exists(snap_p):
            # ONE-SHOT, for the direct-mode reason: a second register-lane must
            # not re-photograph a tree the job has since written to. Reported the
            # way direct mode reports it — a sentence, not a `provision` object
            # with a null `rc` where every consumer expects an exit status.
            ack["preexisting"] = (
                "unchanged (snapshot already taken); provision_command not re-run")
        elif _prov_cmd:
            _t0 = time.time()
            try:
                _pp = subprocess.Popen(_prov_cmd, shell=True, cwd=os.path.abspath(args.cwd),
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                try:
                    _pout, _ = _pp.communicate(timeout=_prov_timeout)
                    _prc = _pp.returncode
                except subprocess.TimeoutExpired:
                    _pp.kill()
                    _pp.communicate()
                    _pout, _prc = b"", None
            except Exception as exc:  # noqa: BLE001
                _pout, _prc = str(exc).encode("utf-8", "replace"), None
            _secs = round(time.time() - _t0, 3)
            if _prc == 0:
                ack["provision"] = {"command": _prov_cmd, "rc": 0, "seconds": _secs}
                try:
                    pre = _preexisting_snapshot(args.cwd, sys.executable)
                    os.makedirs(os.path.dirname(snap_p), exist_ok=True)
                    ack["preexisting"] = write_preexisting(snap_p, args.cwd, pre)
                except Exception as exc:  # noqa: BLE001
                    ack["preexisting_error"] = str(exc)
            else:
                # NO SNAPSHOT ON A FAILED INSTALL, and the job still runs. A
                # half-finished install must not be photographed as if it were
                # the intended starting state — that would exempt whatever it
                # managed to write. The gate is left strict, the failure is named
                # with its exit code, and the job proceeds: a dependency install
                # that failed is a fact the human reading this run needs, not a
                # reason for the pipeline to refuse to start.
                ack["provision_error"] = (
                    "provision_command %r %s — no snapshot was taken, so every "
                    "path it created is gated as this job's own write%s"
                    % (_prov_cmd,
                       ("timed out after %s s" % _prov_timeout) if _prc is None
                       else ("exited rc %d" % _prc),
                       (": " + _pout.decode("utf-8", "replace").strip()[-300:])
                       if _pout else ""))

    # ---- PIN THE BASELINE, before anything has run ------------------------- #
    # This command is the Implement stage's FIRST tool call, which makes it the
    # only point in the Engine C lifecycle that happens before a worker launches.
    # 3.0.1 pinned nothing here, so state.json carried no baseline and the gate
    # filled one in from its own fallback AFTER execution — measuring the job
    # against a HEAD the job may itself have moved.
    #
    # The pin is written per-job (`jobs/<id>.baseline`) as well as into
    # state.json. Every job in a wave writes state.json, so a value that lived
    # only there could be lost to a sibling's save; the per-job file has exactly
    # one writer.
    #
    # The pin below is otherwise ONE-SHOT (`if not os.path.exists(pin_path)`) —
    # right against a WORKER re-registering after it has already committed. What
    # makes this block also correct for a HUMAN re-running `/v:dispatch` on a
    # halted run is the re-attempt handling ABOVE, before `register_lane(...)`:
    # for a worktree job whose previous attempt concluded (a receipt or a result
    # already on disk, and not `merged.integrated`), it already removed the old
    # pin file and popped `entry["baseline"]`, so `read_pinned_baseline` below
    # finds nothing and this block pins the NEW worktree's HEAD instead of
    # silently keeping the old one. A direct job's pin is never touched by that
    # block — a stale one is refused — so its one-shot rule holds unconditionally;
    # `/v:resume`'s `resume-prepare` (which calls the same `_supersede_attempt`
    # helper) remains the only way to clear a direct job's stale pin.
    repo_root = os.path.abspath(args.repo_root)
    pin_root = repo_root if args.isolation == "direct" else os.path.abspath(args.cwd)
    baseline = _head_commit(pin_root)
    if not baseline:
        sys.stderr.write(
            "cannot pin a baseline: %s has no resolvable HEAD. A gate with no "
            "pinned baseline measures a job against its own output, so this "
            "fails closed rather than letting the job start.\n" % pin_root
        )
        return 2
    pin_path = baseline_pin_path(run_dir, args.job_id)
    os.makedirs(os.path.dirname(pin_path), exist_ok=True)
    if not os.path.exists(pin_path):
        _atomic_write(pin_path, baseline + "\n")
    recall_doc, recall_err = load_recall_argument(args.recall_check_json)
    with _run_dir_lock(run_dir):
        state = _load_state(run_dir)
        entry = state["jobs"].setdefault(args.job_id, {})
        entry.setdefault("baseline",
                         read_pinned_baseline(run_dir, args.job_id, entry)
                         or baseline)
        entry["isolation"] = args.isolation
        if recall_doc is not None:
            entry["recall_check"] = recall_doc
        _save_state(run_dir, state)
    if recall_doc is not None:
        ack["recall_check"] = {
            "verdict": recall_doc.get("verdict"),
            "match_count": recall_doc.get("match_count"),
            "recall_check_ms": recall_doc.get("recall_check_ms"),
        }
    elif recall_err:
        ack["recall_check_error"] = recall_err
    ack["baseline"] = entry["baseline"]
    ack["baseline_pin"] = pin_path

    # ---- the handoff artefacts must already EXIST -------------------------- #
    # `emit` materializes them. If they are missing, the worker's --prompt-file
    # would point at nothing and the launcher would be an improvisation, which is
    # what 3.0.1 shipped. Refuse to let the job start rather than find out later.
    prompt_file = worker_prompt_path(run_dir, args.job_id)
    argv_file = launch_argv_path(run_dir, args.job_id)
    if os.path.exists(argv_file) and not os.path.exists(prompt_file):
        sys.stderr.write(
            "job %s has a materialized launcher argv but no prompt file at %s — "
            "the worker's --prompt-file would point at nothing. Re-run `emit`.\n"
            % (args.job_id, prompt_file)
        )
        return 2
    ack["prompt_file"] = prompt_file if os.path.exists(prompt_file) else None
    ack["launch_argv_file"] = argv_file if os.path.exists(argv_file) else None

    # ---- the test contract, resolved BEFORE the worker launches ------------
    # This is the Implement stage, and it is the only point in the Engine C
    # lifecycle that runs BEFORE an external worker starts. `gate-receipt` also
    # resolves a contract, but it runs AFTER the implementer has finished — so a
    # worker's `--test-contract-file` pointed at a file that did not yet exist,
    # and the flag was commented out to hide it. Resolving here is what makes the
    # flag real: on Engine C an external worker now genuinely RECEIVES the
    # contract instead of being told about one.
    #
    # The resolution is scoped to the PRE-CHANGE tree, which is the only tree
    # that exists yet. For `impacted` that means the impacted set is empty and the
    # slice is the floor (plus whatever the declared map yields for an empty
    # diff); the post-change resolution the FLOOR runs from is re-derived in
    # `gate-receipt`. Stated rather than hidden: this contract is the worker's
    # instruction, not the gate's measurement.
    if not args.no_test_contract:
        manifest_path = os.path.abspath(
            args.manifest or os.path.join(run_dir, "manifest.yaml")
        )
        state_job = (_load_state(run_dir)["jobs"].get(args.job_id) or {})
        out_path = test_contract_path(run_dir, args.job_id)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        written = _resolve_test_contract(
            args.fastpath, manifest_path, args.job_id, os.path.abspath(args.cwd),
            state_job.get("baseline"), args.python, out_path,
        )
        ack["test_contract"] = written
        if not written:
            # Never fabricated into a success: the manifest may simply declare no
            # `test_contract`, and the emitted prompt then carries no flag either.
            ack["test_contract_note"] = (
                "no contract resolved (the manifest may declare no `test_contract`, "
                "or resolution failed closed) — the worker runs no tests and reports "
                "no `tests` object"
            )

    # ---- THE PIPELINE'S OWN BOOKKEEPING IS NOT THE JOB'S WORK -------------- #
    # In DIRECT mode the run directory sits inside the tree the gate measures, so
    # every file this command writes for a job — the pre-existing snapshot, the
    # baseline pin, the resolved test contract, state.json — lands in that job's
    # changed set. Dogfood 2 (2026-09-02) blocked a dependent job for three of
    # them and the wave then refused integration as `forged`, which sends whoever
    # reads it hunting a forgery that never happened.
    #
    # THE FIRST FIX ENUMERATED THREE FILENAMES AND WAS WRONG. Dogfood 2b — the
    # narrowest reproduction, one direct-mode job — came back blocked for a
    # FOURTH, `state.json`, which the enumeration had missed because it was
    # written from reading the code path rather than from the evidence. A list of
    # names answers "did I remember them all?", and the honest answer is "not
    # yet".
    #
    # So the exemption is DERIVED: after this command has finished all of its own
    # writes, it lists the run directory as it stands and records that listing.
    # Whatever `register-lane` wrote is exempt BY CONSTRUCTION, and — the part
    # that matters for safety — anything the WORKER later adds to the run
    # directory is NOT in the listing and is still a violation. A worker cannot
    # forge a receipt or rewrite another job's baseline and have it ignored.
    #
    # A worktree job needs none of this: its run directory is outside its
    # worktree, and it gets no snapshot at all.
    if (args.isolation or "direct") != "worktree":
        try:
            repo_abs = os.path.abspath(args.repo_root)
            own = []
            for dirpath, _dirnames, filenames in os.walk(run_dir):
                for name in filenames:
                    full = os.path.abspath(os.path.join(dirpath, name))
                    rel = os.path.relpath(full, repo_abs)
                    if rel.startswith(".." + os.sep) or rel == "..":
                        continue          # outside the repo: not ours to exempt
                    own.append(rel.replace(os.sep, "/"))
            snap = os.path.join(run_dir, "preexisting", "%s.txt" % args.job_id)
            # EXISTING LINES ARE CARRIED FORWARD VERBATIM, never re-digested.
            #
            # The one-shot guard above covers the dirt snapshot; this block runs on
            # every call, and a first attempt re-digested the whole list here. Its
            # own test caught that: a worker could rewrite an exempted file, call
            # `register-lane` again — the clamp admits it — and the fresh digest
            # would re-bless the tampered bytes. Exactly the refresh-after-tamper
            # attack the cross-model review described, surviving in the half the
            # first fix did not cover.
            #
            # So an already-recorded path keeps the digest it was first bound to,
            # and only paths NEW to this listing are digested now.
            existing_lines, existing_rel = [], set()
            if os.path.exists(snap):
                with open(snap, "r", encoding="utf-8") as fh:
                    for ln in fh:
                        ln = ln.rstrip("\n").strip()
                        if not ln:
                            continue
                        existing_lines.append(ln)
                        parts = ln.split("  ", 1)
                        existing_rel.add(parts[1].strip()
                                         if len(parts) == 2 else ln)
            fresh = sorted(p for p in own if p not in existing_rel)
            new_lines = []
            for rel in fresh:
                dig = _file_digest(os.path.join(args.repo_root, rel))
                if dig:
                    new_lines.append("%s  %s" % (dig, rel))
            all_lines = existing_lines + new_lines
            _atomic_write(snap, "\n".join(all_lines) + ("\n" if all_lines else ""))
            ack["own_bookkeeping"] = len(new_lines)
        except Exception as exc:  # noqa: BLE001
            # Fail OPEN into a STRICTER gate, same rule as the snapshot itself:
            # without the listing the job is blocked for our files, which is loud.
            ack["own_bookkeeping_error"] = str(exc)

    print(json.dumps(ack, indent=2, sort_keys=True))
    return 0


def cmd_resume_prepare(argv):
    """`resume-prepare --run-dir R`: make a crashed run relaunchable without a stale pin.

    The first-pin-wins rule in register-lane is right against a WORKER that
    re-registers after committing. A resume is the ORCHESTRATOR re-dispatching a
    job that never integrated, in a fresh worktree branched from the current HEAD
    — so the crashed attempt's pin must go, or the gate's `git diff <pin>` charges
    the job with every commit that landed in between (finding 146: one docs commit
    after the death BLOCKED a clean implementation). Only the orchestrator calls
    this; nothing in the emitted script does, so a worker gains nothing from it.

    For every job whose state carries no `merged.integrated`: delete the pin file
    and the state `baseline`, set `status: pending`, clear `worktree`, drop its
    lane-map worktree entries, and move `receipts/<id>.gate.json` aside as
    `receipts/<id>.gate.superseded-<realised-or-ts>.json` so the integration
    authority never reads the crashed attempt's verdict as this attempt's — via
    `_supersede_attempt`, the same helper `register-lane` now calls on its own
    re-attempt door (v3.6.3), so the two paths retire an attempt identically.
    Integrated jobs are untouched HERE — `out["kept"]` below is exactly
    `cmd_integrated_jobs`'s `integrated` list, read from the same state — and
    the emitted script's own wave loop (`alreadyIntegratedIds` in JS_TEMPLATE)
    is what keeps them untouched on the relaunch this command prepares: without
    that second half, the relaunch re-ran Implement and Gate on every job kept
    here, and the Gate could only ever refuse (finding 146's twin for a job that
    already merged). The phase returns to PARTITION_VERIFIED.

    This remains the ONLY path that clears a `direct` job's pin: a direct
    worker can write anywhere in the checkout, including a forged
    `results/<id>.json`, so `register-lane` REFUSES a direct job whose pin
    predates HEAD (exit 2, `ack["stale_pin_warning"]`) rather than re-pinning
    it, and `emit` refuses a run dir holding such a pin — the operator runs this
    command (or `/v:resume`) first. A direct job's snapshot is kept and only
    its registration-rewritten lines are dropped (`_retire_snapshot`).
    """
    ap = argparse.ArgumentParser(prog="compound-v-emit-workflow.py resume-prepare")
    ap.add_argument("--run-dir", required=True)
    args = ap.parse_args(argv)
    run_dir = os.path.abspath(args.run_dir)
    out = {"run_dir": run_dir, "unpinned": [], "kept": [], "lane_entries_dropped": 0,
           "receipts_archived": []}
    with _run_dir_lock(run_dir):
        state = _load_state(run_dir)
        lm = _read_json(lane_map_path(run_dir), None)
        wts = lm.get("worktrees") if isinstance(lm, dict) and isinstance(lm.get("worktrees"), dict) else None
        for job_id, entry in sorted((state.get("jobs") or {}).items()):
            if not isinstance(entry, dict):
                continue
            merged = entry.get("merged") or {}
            if isinstance(merged, dict) and merged.get("integrated"):
                out["kept"].append(job_id)
                continue
            # A codex worktree job whose failure was ENVIRONMENTAL and whose worktree still
            # exists is resumed IN PLACE (`codex exec resume <uuid>`, the resume-eligibility
            # rule in commands/v-resume.md) — its pin and worktree stay; clearing them here
            # would make that rule unreachable (pr-review 2026-09-04).
            if _resume_in_place(entry):
                out.setdefault("resume_in_place", []).append(job_id)
                continue
            _res = _supersede_attempt(run_dir, job_id, entry, wts)
            if _res["snapshot"]:
                out.setdefault("snapshots", {})[job_id] = _res["snapshot"]
            out["lane_entries_dropped"] += _res["lane_entries_dropped"]
            if _res["receipt_archived"]:
                out["receipts_archived"].append(_res["receipt_archived"])
                _left = _leftover_violations(run_dir, _res["receipt_archived"])
                if _left:
                    out.setdefault("leftover_violations", {})[job_id] = _left
            out["unpinned"].append({"job": job_id, "was": _res["was"]})
        if wts is not None:
            lm["worktrees"] = wts
            _atomic_write(lane_map_path(run_dir), json.dumps(lm, indent=2, sort_keys=True) + "\n")
        if out["unpinned"]:
            state["phase"] = "PARTITION_VERIFIED"
        _save_state(run_dir, state)
    if out.get("leftover_violations"):
        out["leftover_note"] = (
            "these paths blocked the superseded attempt of a direct job and are still in "
            "the working tree; the next attempt will be blocked on them again. Remove or "
            "revert them first — resume-prepare never forgives them.")
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


def _leftover_violations(run_dir, archived_rel):
    """Paths a superseded DIRECT attempt was blocked on that still exist in the tree."""
    doc = _read_json(os.path.join(run_dir, archived_rel), None) or {}
    if doc.get("worktree"):
        return []
    try:
        parsed = json.loads(doc.get("raw_stdout") or "{}")
    except ValueError:
        return []
    paths = (parsed or {}).get("violations") or []
    rc, top, _err = _run(["git", "-C", run_dir, "rev-parse", "--show-toplevel"])
    root = (top or "").strip() if rc == 0 else ""
    if not root:
        return []
    paths = [p for p in paths if isinstance(p, str) and p]
    if not paths:
        return []
    # Still a leftover only if git still sees it as changed or untracked: a file the
    # user already restored to HEAD is clean and must not be reported.
    rc, st, _err = _run(["git", "-C", root, "status", "--porcelain", "-z",
                         "--untracked-files=all", "--"] + paths)
    if rc != 0:
        return []
    dirty = set()
    for rec in (st or "").split("\0"):
        if len(rec) > 3:
            dirty.add(rec[3:])
    return [p for p in paths if p in dirty]


def cmd_integrated_jobs(argv):
    """`integrated-jobs --run-dir R`: job ids state.json already records as
    `merged.integrated: true` — read via `_load_state`, the SAME helper
    `cmd_finalize_wave`'s own "ALREADY MERGED? ASK GIT, NOT state.json" check
    reads (`state_job.get("merged")`) and `cmd_resume_prepare`'s `kept` list is
    built from. This is not a second source of truth; it is the one existing
    source, read for a different caller.

    The emitted script's wave loop (`alreadyIntegratedIds` in JS_TEMPLATE) runs
    this, via one clamped transport agent, ONCE before wave 0 — a relaunch
    (native crash-resume, or `/v:resume`'s `resume-prepare` then relaunch-by-
    `scriptPath`) re-executes the whole script with the SAME embedded job list,
    and a job already integrated has nothing left to do: re-running Implement
    and Gate on it can only produce a false verdict (the Gate's `git diff`
    against that job's pinned baseline sees every commit landed since — the
    merge-time twin of finding 146), for the cost of two full agent spawns.

    READ-ONLY, and it never itself decides at-most-once: a caller that skips a
    job on this answer is trusting an EARLIER attempt's proof, and the
    finalizer's own git-derived check stays the authority that actually
    prevents a double merge.
    """
    ap = argparse.ArgumentParser(prog="compound-v-emit-workflow.py integrated-jobs")
    ap.add_argument("--run-dir", required=True)
    args = ap.parse_args(argv)
    run_dir = os.path.abspath(args.run_dir)
    state = _load_state(run_dir)
    integrated = sorted(
        job_id for job_id, entry in (state.get("jobs") or {}).items()
        if isinstance(entry, dict) and isinstance(entry.get("merged"), dict)
        and entry["merged"].get("integrated")
    )
    print(json.dumps({"integrated": integrated}, indent=2, sort_keys=True))
    return 0
