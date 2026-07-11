#!/usr/bin/env python3
"""
Compound V — process-group timeout supervisor.

Runs a command under a HARD wall-clock cap that signals the command's whole PROCESS GROUP on
timeout, not just the direct child. A backend worker (cursor-agent / codex / agy) can spawn
tool/shell children; if only the top process is signalled, those children can outlive the cap
and write files AFTER the scope gate has run — the exact scope-leak the gate exists to stop.
GNU `timeout` and a bash watchdog both signal only the direct child; this supervisor does not.

How: the command starts in a NEW SESSION (`start_new_session=True` → `setsid`), so it and its
descendants share one process group. On expiry: `os.killpg(SIGTERM)`, a grace interval, then —
ALWAYS — `os.killpg(SIGKILL)` (a descendant that *ignores* SIGTERM is still reaped; the direct
child exiting is NOT proof the group is empty). The parent keeps no copy of the command's
stdout/stderr fds, so a hung child can never hold a capture pipe open.

CONTRACT / limitation (honest): this signals the command's INITIAL process group — the agent
plus its normal (non-daemonizing) children. A descendant that itself calls `setsid` into a new
session/group escapes the killpg; true containment of *that* needs cgroups (Linux) / job objects
(Windows) / a subreaper, which is out of scope for a portable stdlib tool. Backend agents'
tool/shell children do not daemonize, so the initial-group kill covers the real case.

Pure stdlib, Python 3.9-safe. Reusable by every external worker.

Usage:
  compound-v-run-with-timeout.py --timeout <sec> [--grace <sec>] [--cwd <dir>]
      [--stdout <file>] [--stderr <file>] -- <command> [args...]
  compound-v-run-with-timeout.py --selftest

Exit: 124 on timeout (GNU `timeout` convention); 127 if the command does not exist (shell
convention, with a clean one-line message instead of a Popen traceback); otherwise the
command's own exit code (a command killed by signal N reports 128+N, the shell convention).
"""
import argparse
import os
import signal
import subprocess
import sys
import time

TIMEOUT_EXIT_CODE = 124


def _signal_group(pgid, sig):
    try:
        os.killpg(pgid, sig)
    except OSError:
        pass


def _kill_tree(pgid, proc, grace):
    """SIGTERM the group, allow `grace` for a clean exit, then ALWAYS SIGKILL the group — a
    descendant that ignores SIGTERM must still be reaped. Direct-child exit is NOT proof the
    group is empty, so we never short-circuit the SIGKILL. Finally reap the direct child."""
    _signal_group(pgid, signal.SIGTERM)
    deadline = time.time() + max(0.0, grace)
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        time.sleep(0.05)
    _signal_group(pgid, signal.SIGKILL)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def run(timeout, grace, cwd, stdout_path, stderr_path, cmd):
    out = err = None
    try:
        if stdout_path:
            out = open(stdout_path, "wb")
        if stderr_path:
            err = open(stderr_path, "wb")
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=cwd or None,
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=err,
                start_new_session=True,   # setsid: command leads a new session + process group
            )
        except FileNotFoundError:
            # A9: nonexistent command — report cleanly and use the shell convention
            # ("command not found" = 127), not a raw Popen traceback. Scoped to Popen only,
            # so a missing --stdout/--stderr parent dir still surfaces as its own error.
            sys.stderr.write("compound-v-run-with-timeout: command not found: %s\n" % cmd[0])
            return 127
    finally:
        # Parent keeps NO copy of the command's output fds (a hung child holds no pipe; no leak
        # even if the second open() above raised).
        if out is not None:
            out.close()
        if err is not None:
            err.close()

    try:
        pgid = os.getpgid(proc.pid)
    except OSError:
        pgid = proc.pid

    # If the supervisor itself is signalled, take the command's group down with it before exiting
    # (otherwise the new-session child would be orphaned and keep running past the worker).
    def _on_signal(signum, _frame):
        _signal_group(pgid, signal.SIGKILL)
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
        sys.exit(128 + signum)

    prev_int = signal.signal(signal.SIGINT, _on_signal)
    prev_term = signal.signal(signal.SIGTERM, _on_signal)
    timed_out = False
    try:
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_tree(pgid, proc, grace)
    finally:
        signal.signal(signal.SIGINT, prev_int)
        signal.signal(signal.SIGTERM, prev_term)

    if timed_out:
        return TIMEOUT_EXIT_CODE
    rc = proc.returncode
    if rc is None:
        return 1
    if rc < 0:                # terminated by signal -rc
        return 128 + (-rc)
    return rc


def _selftest():
    import tempfile
    fails = []

    def check(name, cond):
        print(("  ok   " if cond else "  FAIL ") + name)
        if not cond:
            fails.append(name)

    check("passthrough exit code", run(5, 1, None, None, None, ["sh", "-c", "exit 7"]) == 7)

    # A9: nonexistent command -> clean 127 (shell convention), not a Popen traceback
    import io
    from contextlib import redirect_stderr
    buf = io.StringIO()
    with redirect_stderr(buf):
        rc127 = run(5, 1, None, None, None, ["definitely-not-a-real-command-xyz"])
    check("nonexistent command -> 127 + message",
          rc127 == 127 and "command not found" in buf.getvalue())

    t0 = time.time()
    rc = run(1, 1, None, None, None, ["sh", "-c", "sleep 30"])
    check("timeout -> 124", rc == TIMEOUT_EXIT_CODE)
    check("timeout returns promptly (<4s)", time.time() - t0 < 4)

    # tree reap: a backgrounded descendant that writes AFTER the cap is reaped first.
    with tempfile.TemporaryDirectory() as td:
        leak = os.path.join(td, "leaked")
        run(1, 1, None, None, None, ["sh", "-c", "( sleep 3; echo leak > '%s' ) & sleep 30" % leak])
        time.sleep(4)
        check("descendant reaped (no post-timeout write)", not os.path.exists(leak))

    # the CRITICAL case Codex caught: a descendant that IGNORES SIGTERM must still be SIGKILL'd.
    with tempfile.TemporaryDirectory() as td:
        leak2 = os.path.join(td, "leak2")
        run(1, 1, None, None, None,
            ["sh", "-c", "( trap '' TERM; sleep 3; echo x > '%s' ) & sleep 30" % leak2])
        time.sleep(4)
        check("SIGTERM-ignoring descendant reaped by SIGKILL", not os.path.exists(leak2))

    with tempfile.TemporaryDirectory() as td:
        of = os.path.join(td, "out")
        run(5, 1, None, of, None, ["sh", "-c", "printf HELLO"])
        with open(of) as fh:
            check("stdout captured to file", fh.read() == "HELLO")

    print("\n%d failed" % len(fails))
    if fails:
        print("FAILED: " + ", ".join(fails))
        return 1
    print("all self-tests passed")
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description="Process-group timeout supervisor")
    ap.add_argument("--timeout", type=int)
    ap.add_argument("--grace", type=int, default=3)
    ap.add_argument("--cwd")
    ap.add_argument("--stdout")
    ap.add_argument("--stderr")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()

    if args.timeout is None or args.timeout <= 0:
        ap.error("--timeout must be a positive integer (seconds)")
    if args.grace < 0:
        ap.error("--grace must be >= 0")
    cmd = args.cmd
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        ap.error("no command given (use: --timeout N -- cmd args...)")
    if args.cwd and not os.path.isdir(args.cwd):
        ap.error("--cwd not a directory: %s" % args.cwd)
    return run(args.timeout, args.grace, args.cwd, args.stdout, args.stderr, cmd)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
