#!/usr/bin/env python3
"""
Compound V — liveness probe (hang detector).

Classifies each `running` job in a run's `state.json` from GIT + FILESYSTEM signals only —
never model-self-report (same ethos as the scope gate). Turns silent forever-waits into
detected, acted-upon states so the dispatcher (and `/v:status`) can stop guessing whether a
job is alive.

Classes (per running job):
  LIKELY-DONE : the job's worktree HEAD is a commit PAST its recorded `baseline` — the work
                landed, only the completion notification is stuck. (The exact case that forced
                a human to nudge the dispatcher by hand.) Checked FIRST.
  WORKING     : a progress signal (newest working-tree mtime, or an optional `log` mtime) moved
                within `stale_sec`.
  STALE       : alive but no progress for longer than `stale_sec` — a suspected hang.
  DEAD        : a recorded `pid` is not alive and there is no commit/progress. (Best-effort:
                only emitted when a `pid` is present — Claude subagents expose none.)
  UNKNOWN     : no worktree / pid / log to probe, or the signal is unreadable. Never crashes.

Why git+FS and not pids: the external workers (codex/cursor/agy) already run under the
process-group timeout supervisor (a hard cap), so they cannot hang the dispatcher past their
timeout — the probe does not need to police them. Its unique value is the Claude subagent case
(no cap, can "park" after committing), which has no pid to poll — so LIKELY-DONE/STALE are
derived from the worktree's git HEAD + file mtimes, which always exist.

`.git` internals are EXCLUDED from the mtime walk: a `git init`/commit touches `.git`, which
would mask staleness — and a real commit is already caught by the LIKELY-DONE rule.

Pure stdlib, Python 3.9-safe.

Usage:
  compound-v-liveness.py <run-dir> [--stale-sec N] [--json]
  compound-v-liveness.py --selftest

Exit: 0 if nothing is STALE/DEAD (LIKELY-DONE is exit 0 — it is good news: collect it);
      3 if any running job is STALE or DEAD (attention needed);
      2 on usage / unreadable-state error.
"""
import argparse
import json
import os
import subprocess
import sys
import time

LIVENESS_CLASSES = ("WORKING", "LIKELY-DONE", "STALE", "DEAD", "UNKNOWN")
DEFAULT_STALE_SEC = 600
ATTENTION = ("STALE", "DEAD")


def _git(args, cwd):
    """Run `git -C <cwd> <args>`; return stdout stripped, or None on any failure."""
    try:
        out = subprocess.run(
            ["git", "-C", cwd] + list(args),
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip()


def _newest_mtime(path):
    """Newest mtime among working-tree FILES under `path`, EXCLUDING `.git`. None if unreadable
    or empty. Excluding `.git` means a commit/`git init` does not read as file-edit progress —
    a real commit is caught by the LIKELY-DONE rule instead."""
    newest = None
    try:
        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if d != ".git"]
            for name in files:
                try:
                    m = os.stat(os.path.join(root, name)).st_mtime
                except OSError:
                    continue
                if newest is None or m > newest:
                    newest = m
    except OSError:
        return None
    return newest


def _pid_alive(pid):
    """True iff the pid is a live process (signal 0 probe)."""
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError, TypeError):
        return False
    return True


def classify_job(job, now, stale_sec):
    """Classify one running job dict → (liveness, evidence, last_progress_s).

    `job` fields consumed (all optional, degrade-safe): worktree, baseline, pid, log.
    """
    wt = job.get("worktree")
    baseline = job.get("baseline")
    pid = job.get("pid")
    log = job.get("log")

    have_wt = bool(wt) and os.path.isdir(wt)

    # 1. LIKELY-DONE — a commit landed past the dispatch baseline (notification stuck).
    if have_wt and baseline:
        head = _git(["rev-parse", "HEAD"], wt)
        if head and head != baseline:
            return ("LIKELY-DONE",
                    "worktree HEAD %s != baseline %s (committed, not yet collected)"
                    % (head[:7], str(baseline)[:7]),
                    None)

    # 2. mtime progress signal — newest working-tree file, plus an optional external log.
    mtime = _newest_mtime(wt) if have_wt else None
    if log and os.path.isfile(log):
        try:
            lm = os.stat(log).st_mtime
            mtime = lm if (mtime is None or lm > mtime) else mtime
        except OSError:
            pass

    if mtime is not None:
        age = int(max(0, now - mtime))
        if age <= stale_sec:
            return ("WORKING", "progress %ds ago (<= %ds)" % (age, stale_sec), age)
        if pid is not None and not _pid_alive(pid):
            return ("DEAD", "pid %s not alive; no progress for %ds" % (pid, age), age)
        return ("STALE", "no progress for %ds (> %ds)" % (age, stale_sec), age)

    # 3. no worktree/log signal — fall back to pid liveness if one was recorded.
    if pid is not None:
        if _pid_alive(pid):
            return ("UNKNOWN", "pid %s alive but no worktree/log signal" % pid, None)
        return ("DEAD", "pid %s not alive and no worktree/log signal" % pid, None)

    return ("UNKNOWN", "no worktree, pid, or log to probe", None)


def probe(run_dir, stale_sec, now):
    """Classify every `running` job in <run-dir>/state.json. Returns
    {job_id: {liveness, evidence, last_progress_s}}. Raises ValueError on unreadable state."""
    state_path = os.path.join(run_dir, "state.json")
    try:
        with open(state_path) as fh:
            state = json.load(fh)
    except (OSError, ValueError) as exc:
        raise ValueError("cannot read %s: %s" % (state_path, exc))

    results = {}
    for jid, job in (state.get("jobs") or {}).items():
        if not isinstance(job, dict) or job.get("status") != "running":
            continue
        liveness, evidence, last_prog = classify_job(job, now, stale_sec)
        results[jid] = {"liveness": liveness, "evidence": evidence, "last_progress_s": last_prog}
    return results


def _render(results):
    if not results:
        return "no running jobs (nothing to probe)"
    lines = []
    for jid in sorted(results):
        r = results[jid]
        lines.append("%-28s %-11s  %s" % (jid, r["liveness"], r["evidence"]))
    return "\n".join(lines)


def _exit_code(results):
    return 3 if any(r["liveness"] in ATTENTION for r in results.values()) else 0


# --------------------------------------------------------------------------- selftest

def _selftest():
    import tempfile
    fails = []

    def check(name, cond):
        print(("  ok   " if cond else "  FAIL ") + name)
        if not cond:
            fails.append(name)

    now = time.time()

    def cls(job, stale=DEFAULT_STALE_SEC):
        return classify_job(job, now, stale)[0]

    # --- LIKELY-DONE: a real git repo with a commit past baseline ---
    with tempfile.TemporaryDirectory() as repo:
        env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)

        def g(*a):
            subprocess.run(["git", "-C", repo] + list(a), check=True,
                           capture_output=True, env=env)
        g("init", "-q")
        g("config", "user.email", "t@t")
        g("config", "user.name", "t")
        with open(os.path.join(repo, "f0.txt"), "w") as fh:
            fh.write("0")
        g("add", "-A")
        g("commit", "-q", "-m", "baseline")
        baseline = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                                  capture_output=True, text=True, env=env).stdout.strip()
        with open(os.path.join(repo, "f1.txt"), "w") as fh:
            fh.write("1")
        g("add", "-A")
        g("commit", "-q", "-m", "work landed")
        check("LIKELY-DONE: worktree HEAD past baseline",
              cls({"status": "running", "worktree": repo, "baseline": baseline}) == "LIKELY-DONE")
        # same repo, baseline == HEAD ⇒ NOT likely-done (falls to mtime; files are fresh ⇒ WORKING)
        head = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                              capture_output=True, text=True, env=env).stdout.strip()
        check("no false LIKELY-DONE when HEAD == baseline",
              cls({"status": "running", "worktree": repo, "baseline": head}) != "LIKELY-DONE")

    # --- WORKING: plain dir, fresh file (non-git ⇒ rev-parse fails ⇒ mtime path) ---
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "a.txt"), "w") as fh:
            fh.write("x")
        check("WORKING: fresh mtime",
              cls({"status": "running", "worktree": d, "baseline": "deadbeef"}) == "WORKING")

        # --- STALE: same dir, age every file well past the threshold ---
        old = now - 4000
        for root, dirs, files in os.walk(d):
            for name in files:
                os.utime(os.path.join(root, name), (old, old))
        check("STALE: mtime older than stale_sec",
              cls({"status": "running", "worktree": d, "baseline": "deadbeef"}, stale=600) == "STALE")
        check("STALE flips to WORKING under a larger --stale-sec",
              cls({"status": "running", "worktree": d, "baseline": "deadbeef"}, stale=9000) == "WORKING")

    # --- DEAD: a recorded pid that is no longer alive, no worktree ---
    dead = subprocess.Popen(["sh", "-c", "exit 0"])
    dead.wait()
    check("DEAD: dead pid, no worktree",
          cls({"status": "running", "pid": dead.pid}) == "DEAD")

    # --- UNKNOWN: nothing to probe / live pid but no FS signal ---
    check("UNKNOWN: no worktree/pid/log",
          cls({"status": "running"}) == "UNKNOWN")
    check("UNKNOWN: live pid but no FS signal",
          cls({"status": "running", "pid": os.getpid()}) == "UNKNOWN")

    # --- probe(): only running jobs; exit-code aggregation ---
    with tempfile.TemporaryDirectory() as rundir:
        state = {"jobs": {
            "j-done":    {"status": "done"},
            "j-run":     {"status": "running"},          # UNKNOWN
        }}
        with open(os.path.join(rundir, "state.json"), "w") as fh:
            json.dump(state, fh)
        res = probe(rundir, DEFAULT_STALE_SEC, now)
        check("probe skips non-running jobs", list(res.keys()) == ["j-run"])
        check("exit 0 when nothing STALE/DEAD", _exit_code(res) == 0)
        check("exit 3 when a STALE is present",
              _exit_code({"x": {"liveness": "STALE"}}) == 3)

    # --- degrade-safe: unreadable state raises ValueError (caught in main → exit 2) ---
    raised = False
    try:
        probe(tempfile.gettempdir() + "/compound-v-nonexistent-run-xyz", DEFAULT_STALE_SEC, now)
    except ValueError:
        raised = True
    check("unreadable state.json raises ValueError", raised)

    print("\n%d failed" % len(fails))
    if fails:
        print("FAILED: " + ", ".join(fails))
        return 1
    print("all self-tests passed")
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description="Compound V liveness probe (hang detector)")
    ap.add_argument("run_dir", nargs="?", help="path to docs/superpowers/execution/<run-id>/")
    ap.add_argument("--stale-sec", type=int, default=DEFAULT_STALE_SEC,
                    help="no-progress seconds before a job is STALE (default %d)" % DEFAULT_STALE_SEC)
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()
    if not args.run_dir:
        ap.error("run_dir is required (or use --selftest)")
    if args.stale_sec <= 0:
        ap.error("--stale-sec must be a positive integer")

    try:
        results = probe(args.run_dir, args.stale_sec, time.time())
    except ValueError as exc:
        sys.stderr.write("%s\n" % exc)
        return 2

    if args.json:
        print(json.dumps(results, indent=2, sort_keys=True))
    else:
        print(_render(results))
    return _exit_code(results)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
