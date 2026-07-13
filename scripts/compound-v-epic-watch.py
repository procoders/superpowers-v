#!/usr/bin/env python3
"""
Compound V epic watcher -- v2.11 Scheduler Auto-Resurrection, Component 2 (NEW file).

Emits the watcher's scheduler resume prompt and advises the two scheduler tiers; the
DRIVER (Component 3 -- v-epic.md / epic-mode.md / v-init.md, not yet built) makes the
actual harness scheduling calls (CronCreate / mcp__scheduled-tasks__create_scheduled_task)
and owns the real arm/disarm wiring. This file never talks to a scheduler directly.

This file NEVER re-implements scripts/compound-v-epic-state.py's ("V1") lease/terminal/
breaker/registry logic -- every fact it needs (liveness, terminality, the watcher
registry) is obtained by invoking V1 as a subprocess and reading its JSON stdout. See
compound-v-epic-state.py's own docstring, section "CLI contract (v2.11 V1 -- Scheduler
Auto-Resurrection...)", for the frozen contract this file consumes:
  --liveness --state S --now T [--stale-after-min N]
      -> {"incomplete","stale","held","lease_expired","epic_status","terminal","resume_count"}
  --claim-resume --state S --owner-pid P --now T [--lease-ttl-min M]
      -> {"claimed","reason":"claimed|live-lease-held|terminal|resume-cap","resume_count"}
  --list-watchers --state S -> [{"provider","task_id","armed_at","status"}, ...] (armed only)
  --record-watcher-armed / --record-watcher-disarmed --state S --provider P --task-id ID
  is_terminal(state) -- the canonical terminal classifier folded into --liveness/--claim-resume.

Two subcommands:

  emit-prompt --epic-id E --state S
      Prints a SELF-CONTAINED scheduler resume prompt: plain text meant to be handed to a
      scheduler tool (CronCreate's prompt / scheduled-tasks' prompt) so a FRESH, memoryless
      session can act on it with zero conversational context. It instructs that session to
      call V1's --claim-resume (the one atomic resume authority), branch on the result
      (resume via /v:epic, no-op on a live foreign lease, or a full inline DISARM on a
      terminal/resume-cap verdict), and carries the global model/commit/no-fabricated-
      metrics constraints. Never touches epic-state.json itself -- it only prints text.

  plan --state S --now T [--stale-after-min N]
      Prints JSON: {"tier1":{"cron":<cron-expr>,"disarm":bool},
                     "tier2":{"cadence":<str>,"disarm":bool},
                     "disable_cron_detected":bool, "terminal":bool}.
      Derives "terminal"/"disarm" from V1's --liveness (which folds in is_terminal) --
      disarm is true ONLY when the epic is truly terminal, never mid-run. Off-minute cron
      cadence (:17/:47) avoids the top-of-hour rush other jobs cluster on. NOTE: Tier-1
      (session CronCreate) tasks additionally expire after ~7 days even inside a
      continuously open session -- re-arm before that window closes, or lean on Tier-2.

  --selftest  (top-level flag, mirrors this plugin's other scripts/*.py)

Usage:
  compound-v-epic-watch.py emit-prompt --epic-id E --state S
  compound-v-epic-watch.py plan --state S --now T [--stale-after-min N]
  compound-v-epic-watch.py --selftest

Python 3.9-safe, stdlib only. LANG=C-clean (stdout/stderr reconfigured to utf-8/replace;
all printed prompt/JSON text is plain ASCII). No fabricated cost/token/performance metrics
anywhere in this file.
"""
import argparse
import io
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
EPIC_STATE_SCRIPT = os.path.join(HERE, "compound-v-epic-state.py")

# Off-minute cadence: fires at :17 and :47 past the hour (~30 min apart), avoiding the
# top-of-hour rush other cron jobs cluster on. Matches the v2.11 spec's "Off-minute cadence".
TIER1_CRON_SCHEDULE = "17,47 * * * *"
TIER2_CADENCE = "~30m"
# Tier-1 (session CronCreate) is session-scoped AND additionally expires after 7 days even
# if the session stays open continuously -- re-arm before that window closes, or lean on
# Tier-2 (scheduled-tasks), which is on-disk and does not carry this expiry.
TIER1_CRON_EXPIRY_DAYS = 7

# Mirrors compound-v-epic-state.py's ID_RE_OK -- the same charset an epic_id is validated
# against at --init. Duplicated here (not imported) so this file stays a standalone,
# dependency-free CLI that only ever talks to V1 over a subprocess boundary (same
# "duplicate small idioms, never import" discipline as compound-v-epic-arbiter.py).
_ID_RE_OK = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
_TOKEN_BAD_CHARS = re.compile(r"[\r\n\x00]")


def _validate_epic_id(value):
    """--epic-id must be a plain id (same charset V1 enforces at --init) -- this prompt
    embeds it verbatim into shell commands and an /v:epic invocation, so a structurally
    unsafe id is rejected outright rather than silently interpolated."""
    if not value or value in (".", "..") or any(c not in _ID_RE_OK for c in value):
        raise ValueError("--epic-id must match [A-Za-z0-9._-]+ (got %r)" % (value,))
    return value


def _validate_state_path(value):
    """--state is embedded inside double-quoted shell commands in the emitted prompt --
    reject an empty value, embedded newline/CR/NUL, or an embedded double quote that could
    break out of that quoting."""
    if not value or _TOKEN_BAD_CHARS.search(value) or '"' in value:
        raise ValueError("--state must be a non-empty single-line path with no embedded "
                          "quote (got %r)" % (value,))
    return value


def deterministic_task_id(epic_id, provider):
    """Placeholder deterministic naming for the Tier-1/Tier-2 fallback delete in the
    terminal-DISARM branch of the emitted prompt: if arming ever crashed before its
    watcher_registry record was written, --list-watchers cannot see the orphaned task, so
    the disarm also tries a well-known name directly. V3 (driver + /v:init wiring) is NOT
    yet built and owns the REAL arming convention -- this is a conservative, self-consistent
    placeholder that MUST be reconciled with V3's actual naming once it exists, not silently
    assumed to already match it."""
    if provider == "cron":
        return "compound-v-watch-%s-cron" % epic_id
    if provider == "scheduled-tasks":
        return "compound-v-watch-%s-scheduled-tasks" % epic_id
    raise ValueError("unknown provider %r" % (provider,))


def _run_epic_state(args, python_bin=None, epic_state_script=None):
    """Invoke compound-v-epic-state.py <args> as a subprocess -- the ONLY way this file
    ever reads epic-state.json. Never re-implements V1's lease/terminal/breaker logic.
    Returns (returncode, stdout_str, stderr_str); never raises. Explicit utf-8/replace
    decoding (not bare text=True) keeps this LANG=C-clean regardless of the parent's
    locale-derived default codec."""
    script = epic_state_script or EPIC_STATE_SCRIPT
    exe = python_bin or sys.executable or "python3"
    try:
        proc = subprocess.run(
            [exe, script] + list(args),
            stdin=subprocess.DEVNULL, capture_output=True,
            encoding="utf-8", errors="replace", timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 2, "", str(exc)
    return proc.returncode, proc.stdout, proc.stderr


def _disable_cron_detected(env=None):
    """CLAUDE_CODE_DISABLE_CRON is a boolean-ish opt-out env var. Absent, empty, or one of
    the common false spellings ("0"/"false"/"no", case-insensitive) reads as NOT set;
    anything else present reads as set. Conservative choice: a caller-supplied `env` dict
    (defaults to os.environ) makes this independently unit-testable without mutating the
    real process environment."""
    env = env if env is not None else os.environ
    v = env.get("CLAUDE_CODE_DISABLE_CRON")
    if v is None:
        return False
    return v.strip().lower() not in ("", "0", "false", "no")


# --------------------------------------------------------------------------- emit-prompt

PROMPT_TEMPLATE = """\
COMPOUND V -- SCHEDULED EPIC RESUME (v2.11 auto-resurrection watcher)

This prompt is fully self-contained. You are a fresh session with no memory of any
earlier conversation, and none is assumed here -- everything you need to act is written
below. Do not look for, or refer to, any prior chat history.

Epic id:         {epic_id}
Epic-state file: {state_path}

===============================================================================
STEP 1 -- Determine your own identity and the current time
===============================================================================
- Your own OS process id (owner-pid):
    python3 -c "import os; print(os.getpid())"
- The current UTC time in ISO-8601 (for --now):
    python3 -c "import datetime; print(datetime.datetime.now(datetime.timezone.utc).isoformat())"

===============================================================================
STEP 2 -- Attempt the ONE atomic resume claim
===============================================================================
This is the sole authority for whether you may resume this epic. Never skip it and never
reimplement its logic yourself -- call it exactly as written, substituting Step 1's values:

    python3 scripts/compound-v-epic-state.py --claim-resume \\
      --state "{state_path}" --owner-pid <YOUR_PID_FROM_STEP_1> --now <UTC_ISO_FROM_STEP_1>

It prints exactly one JSON object:
    {{"claimed": true|false, "reason": "claimed|live-lease-held|terminal|resume-cap", "resume_count": N}}

===============================================================================
STEP 3 -- Branch on the result
===============================================================================

BRANCH A -- claimed == true (reason "claimed")
  A live, crash-safe resume was granted. Re-invoke:

      /v:epic {epic_id}

  Let it run to its next natural stopping point. Obey the GLOBAL CONSTRAINTS below for
  any work you perform in this branch.

BRANCH B -- claimed == false AND reason == "live-lease-held"
  Another owner is actively working this epic (its lease is still live, or its recorded
  owner_pid is still a live OS process). This is a normal, expected outcome, not an error.
  Do NOT resume. Do NOT disarm anything. Exit now -- no further action needed.

BRANCH C -- claimed == false AND reason is "terminal" OR "resume-cap"
  The epic is permanently done, blocked_needing_human, or has exhausted its resume cap --
  it will never make further autonomous progress without a human. Do NOT re-invoke
  /v:epic. Instead, perform the FULL DISARM below, then exit.

===============================================================================
BRANCH C -- FULL DISARM (only when reason is "terminal" or "resume-cap")
===============================================================================
1. List every still-armed watcher for this epic:

    python3 scripts/compound-v-epic-state.py --list-watchers --state "{state_path}"

   This prints a JSON array of {{"provider","task_id","armed_at","status"}} entries (only
   entries whose status is "armed").

2. For EACH entry returned:
   - If its "provider" is "cron": delete that Tier-1 scheduler task with the CronDelete
     tool, passing the entry's "task_id".
   - If its "provider" is "scheduled-tasks": delete that Tier-2 scheduler task with the
     mcp__scheduled-tasks__delete_scheduled_task tool, passing the entry's "task_id".
   - Then record the disarm so the registry stays accurate:

       python3 scripts/compound-v-epic-state.py --record-watcher-disarmed \\
         --state "{state_path}" --provider <that entry's provider> --task-id "<that entry's task_id>"

3. Deterministic-id fallback (belt-and-suspenders): if a prior arm ever crashed before its
   registry record was written, --list-watchers cannot see that orphaned task. So also
   attempt to delete a Tier-1 task named "{cron_fallback}" via CronDelete, and a Tier-2
   task named "{sched_fallback}" via mcp__scheduled-tasks__delete_scheduled_task. A delete
   against a name that does not exist is expected and harmless -- ignore a not-found error
   from either tool; it is not a failure.

===============================================================================
GLOBAL CONSTRAINTS (apply to any work performed under BRANCH A)
===============================================================================
- Model policy: use Opus by default for this work; Sonnet is a narrow, justified
  exception; NEVER use Haiku.
- Two-command commit discipline: stage changes with `git add <files>`, then create the
  commit with a separate `git commit -m "..."` command -- never chain them into one
  combined command.
- No fabricated metrics: never invent cost, token, timing, or performance numbers in any
  commit message, log entry, or report.

Take no action beyond what is written above. Do not start new epic features on your own
initiative outside of re-invoking /v:epic under BRANCH A.
"""


def build_resume_prompt(epic_id, state_path):
    """Build the self-contained scheduler resume prompt for `emit-prompt`. Raises
    ValueError on a structurally unsafe --epic-id/--state (see the validators above)."""
    epic_id = _validate_epic_id(epic_id)
    state_path = _validate_state_path(state_path)
    return PROMPT_TEMPLATE.format(
        epic_id=epic_id,
        state_path=state_path,
        cron_fallback=deterministic_task_id(epic_id, "cron"),
        sched_fallback=deterministic_task_id(epic_id, "scheduled-tasks"),
    )


def cmd_emit_prompt(args):
    try:
        prompt = build_resume_prompt(args.epic_id, args.state)
    except ValueError as exc:
        print("epic-watch emit-prompt error: %s" % exc, file=sys.stderr)
        return 1
    print(prompt)
    return 0


# --------------------------------------------------------------------------- plan

def build_plan(state_path, now_iso, stale_after_min=None, epic_state_script=None,
               python_bin=None, env=None):
    """Advise the two scheduler tiers for `plan`, purely by reading V1's --liveness (which
    folds in the canonical is_terminal classifier -- see this file's module docstring).
    Returns (result_dict|None, error|None). disarm is true ONLY when the epic is truly
    terminal (done / blocked_needing_human / breaker-tripped / unsatisfiable DAG), never
    mid-run."""
    cmd = ["--liveness", "--state", state_path, "--now", now_iso]
    if stale_after_min is not None:
        cmd += ["--stale-after-min", str(stale_after_min)]
    rc, out, err = _run_epic_state(cmd, python_bin=python_bin, epic_state_script=epic_state_script)
    if rc != 0:
        msg = (err or out or "").strip()
        return None, msg or ("compound-v-epic-state.py --liveness exited %d" % rc)
    try:
        liveness = json.loads(out)
    except ValueError as exc:
        return None, "unparseable --liveness output: %s" % exc
    if not isinstance(liveness, dict) or "terminal" not in liveness:
        return None, "unexpected --liveness output shape: %r" % (liveness,)
    terminal = bool(liveness["terminal"])
    return {
        "tier1": {"cron": TIER1_CRON_SCHEDULE, "disarm": terminal},
        "tier2": {"cadence": TIER2_CADENCE, "disarm": terminal},
        "disable_cron_detected": _disable_cron_detected(env=env),
        "terminal": terminal,
    }, None


def cmd_plan(args):
    result, err = build_plan(args.state, args.now, stale_after_min=args.stale_after_min)
    if result is None:
        print("epic-watch plan error: %s" % err, file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


# --------------------------------------------------------------------------- selftest

def _selftest():
    import contextlib
    import tempfile

    fails = []

    def check(name, cond):
        print(("  ok   " if cond else "  FAIL ") + name)
        if not cond:
            fails.append(name)

    def expect_raises(name, fn, *a, **kw):
        raised = False
        try:
            fn(*a, **kw)
        except ValueError:
            raised = True
        check(name, raised)

    def _write_json(path, obj):
        with open(path, "w") as fh:
            json.dump(obj, fh)

    def _iso_now():
        return datetime.now(timezone.utc).isoformat()

    # ---- unit: token validation --------------------------------------------------------
    check("_validate_epic_id accepts a normal id", _validate_epic_id("my-epic.1") == "my-epic.1")
    for bad in ["", "with\nnewline", "with\rcr", "with\x00nul", "..", "has/slash", "has space"]:
        expect_raises("_validate_epic_id rejects %r" % (bad,), _validate_epic_id, bad)

    check("_validate_state_path accepts a normal path",
          _validate_state_path("/tmp/x/epic-state.json") == "/tmp/x/epic-state.json")
    for bad in ["", "has\nnewline", 'has"quote', "has\x00nul"]:
        expect_raises("_validate_state_path rejects %r" % (bad,), _validate_state_path, bad)

    check("deterministic_task_id: cron", deterministic_task_id("E1", "cron") == "compound-v-watch-E1-cron")
    check("deterministic_task_id: scheduled-tasks",
          deterministic_task_id("E1", "scheduled-tasks") == "compound-v-watch-E1-scheduled-tasks")
    expect_raises("deterministic_task_id rejects an unknown provider",
                  deterministic_task_id, "E1", "bogus")

    # ---- unit: disable-cron detection ---------------------------------------------------
    check("_disable_cron_detected: unset -> False", _disable_cron_detected({}) is False)
    check("_disable_cron_detected: empty string -> False",
          _disable_cron_detected({"CLAUDE_CODE_DISABLE_CRON": ""}) is False)
    for falsy in ("0", "false", "False", "no", "NO"):
        check("_disable_cron_detected: %r -> False" % (falsy,),
              _disable_cron_detected({"CLAUDE_CODE_DISABLE_CRON": falsy}) is False)
    for truthy in ("1", "true", "yes", "on"):
        check("_disable_cron_detected: %r -> True" % (truthy,),
              _disable_cron_detected({"CLAUDE_CODE_DISABLE_CRON": truthy}) is True)

    # ---- emit-prompt self-containment ---------------------------------------------------
    prompt = build_resume_prompt(
        "epic-alpha", "/repo/docs/superpowers/execution/epic-alpha/epic-state.json")
    must_contain = [
        "epic-alpha",
        "/repo/docs/superpowers/execution/epic-alpha/epic-state.json",
        "--claim-resume",
        "--owner-pid",
        "--now",
        "/v:epic epic-alpha",
        "live-lease-held",
        "--list-watchers",
        "CronDelete",
        "mcp__scheduled-tasks__delete_scheduled_task",
        "--record-watcher-disarmed",
        "Opus",
        "Haiku",
        "Two-command",
        "fabricated metrics",
        "resume-cap",
        "terminal",
    ]
    for token in must_contain:
        check("emit-prompt contains %r" % (token,), token in prompt)

    banned_phrases = [
        "as we discussed", "as discussed earlier", "earlier in this conversation",
        "as i mentioned", "as you mentioned", "you said earlier", "recall that we",
        "our conversation", "this conversation", "previously discussed",
        "like we talked about", "per our chat", "as before",
    ]
    lowered = prompt.lower()
    for phrase in banned_phrases:
        check("emit-prompt has NO conversation-relative phrase %r" % (phrase,),
              phrase not in lowered)

    expect_raises("build_resume_prompt rejects a malformed epic-id",
                  build_resume_prompt, "bad id\nwith newline", "/tmp/x.json")
    expect_raises("build_resume_prompt rejects an empty state path",
                  build_resume_prompt, "epic-1", "")

    # ---- CLI wiring: emit-prompt via argv ------------------------------------------------
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["emit-prompt", "--epic-id", "epic-beta", "--state", "/tmp/epic-beta/state.json"])
    check("CLI emit-prompt exits 0", rc == 0)
    check("CLI emit-prompt prints the epic id", "epic-beta" in buf.getvalue())
    check("CLI emit-prompt prints the state path", "/tmp/epic-beta/state.json" in buf.getvalue())

    # ---- integration: plan() against real compound-v-epic-state.py fixtures -------------
    if not os.path.isfile(EPIC_STATE_SCRIPT):
        check("compound-v-epic-state.py is present next to this script (V1 dependency)", False)
    else:
        with tempfile.TemporaryDirectory() as td:
            feats_path = os.path.join(td, "features.json")
            _write_json(feats_path, [{"id": "f1", "title": "F1", "depends_on": []}])

            # -- fixture 1: fresh incomplete marathon+watch epic -> not terminal, no disarm
            live_state = os.path.join(td, "live-state.json")
            rc, out, err = _run_epic_state([
                "--init", "--stance", "marathon", "--watch",
                "--features", feats_path, "--epic-id", "epic-live", "--out", live_state,
            ])
            check("fixture: fresh marathon+watch --init succeeds", rc == 0)

            plan, perr = build_plan(live_state, _iso_now())
            check("plan(): fresh incomplete epic -> ok", plan is not None and perr is None)
            if plan is not None:
                check("plan(): fresh incomplete epic -> terminal False", plan["terminal"] is False)
                check("plan(): fresh incomplete epic -> tier1 disarm False",
                      plan["tier1"]["disarm"] is False)
                check("plan(): fresh incomplete epic -> tier2 disarm False",
                      plan["tier2"]["disarm"] is False)
                check("plan(): tier1 cron cadence", plan["tier1"]["cron"] == TIER1_CRON_SCHEDULE)
                check("plan(): tier2 cadence", plan["tier2"]["cadence"] == TIER2_CADENCE)
                check("plan(): output shape",
                      set(plan.keys()) == {"tier1", "tier2", "disable_cron_detected", "terminal"})

            # -- fixture 2: terminal via "done" (all features done + final_review passed)
            done_state = os.path.join(td, "done-state.json")
            rc, out, err = _run_epic_state([
                "--init", "--stance", "marathon", "--watch",
                "--features", feats_path, "--epic-id", "epic-done", "--out", done_state,
            ])
            check("fixture: done-epic --init succeeds", rc == 0)
            rc, out, err = _run_epic_state([
                "--update", "--state", done_state, "--feature", "f1", "--status", "done",
            ])
            check("fixture: mark f1 done", rc == 0)
            rc, out, err = _run_epic_state([
                "--record-final-review", "--state", done_state, "--status", "passed",
            ])
            check("fixture: record final review passed", rc == 0)

            plan2, perr2 = build_plan(done_state, _iso_now())
            check("plan(): done epic -> ok", plan2 is not None and perr2 is None)
            if plan2 is not None:
                check("plan(): done epic -> terminal True", plan2["terminal"] is True)
                check("plan(): done epic -> tier1 disarm True", plan2["tier1"]["disarm"] is True)
                check("plan(): done epic -> tier2 disarm True", plan2["tier2"]["disarm"] is True)

            # -- fixture 3: terminal via resume-cap (a breaker trip mid-run, not "done")
            cap_state = os.path.join(td, "cap-state.json")
            rc, out, err = _run_epic_state([
                "--init", "--stance", "marathon", "--watch", "--max-resume-count", "1",
                "--features", feats_path, "--epic-id", "epic-cap", "--out", cap_state,
            ])
            check("fixture: resume-cap epic --init succeeds", rc == 0)

            dead = subprocess.Popen([sys.executable, "-c", "pass"])
            dead.wait()
            dead_pid = dead.pid

            t0 = datetime.now(timezone.utc)
            rc, out, err = _run_epic_state([
                "--claim-resume", "--state", cap_state, "--owner-pid", str(dead_pid),
                "--now", t0.isoformat(), "--lease-ttl-min", "1",
            ])
            check("fixture: first claim-resume succeeds (exit 0)", rc == 0)
            first = json.loads(out) if rc == 0 else {}
            check("fixture: first claim-resume claimed", first.get("claimed") is True)

            t1 = t0 + timedelta(minutes=2)  # past the 1-minute lease TTL; dead_pid stays dead
            rc, out, err = _run_epic_state([
                "--claim-resume", "--state", cap_state, "--owner-pid", str(dead_pid),
                "--now", t1.isoformat(), "--lease-ttl-min", "1",
            ])
            check("fixture: second claim-resume succeeds (exit 0)", rc == 0)
            second = json.loads(out) if rc == 0 else {}
            check("fixture: second claim-resume trips the resume cap",
                  second.get("claimed") is False and second.get("reason") == "resume-cap")

            plan3, perr3 = build_plan(cap_state, (t1 + timedelta(minutes=1)).isoformat())
            check("plan(): resume-cap epic -> ok", plan3 is not None and perr3 is None)
            if plan3 is not None:
                check("plan(): resume-cap epic -> terminal True", plan3["terminal"] is True)
                check("plan(): resume-cap epic -> tier1 disarm True", plan3["tier1"]["disarm"] is True)
                check("plan(): resume-cap epic -> tier2 disarm True", plan3["tier2"]["disarm"] is True)

            # -- disable_cron_detected surfaced end-to-end (real env, saved/restored) -----
            old_env = os.environ.get("CLAUDE_CODE_DISABLE_CRON")
            try:
                os.environ["CLAUDE_CODE_DISABLE_CRON"] = "1"
                plan_on, _ = build_plan(live_state, _iso_now())
                check("plan(): disable_cron_detected True when env set",
                      plan_on is not None and plan_on["disable_cron_detected"] is True)
                os.environ.pop("CLAUDE_CODE_DISABLE_CRON", None)
                plan_off, _ = build_plan(live_state, _iso_now())
                check("plan(): disable_cron_detected False when env unset",
                      plan_off is not None and plan_off["disable_cron_detected"] is False)
            finally:
                if old_env is None:
                    os.environ.pop("CLAUDE_CODE_DISABLE_CRON", None)
                else:
                    os.environ["CLAUDE_CODE_DISABLE_CRON"] = old_env

            # -- CLI wiring for plan --------------------------------------------------------
            buf2 = io.StringIO()
            with contextlib.redirect_stdout(buf2):
                rc = main(["plan", "--state", live_state, "--now", _iso_now()])
            check("CLI plan exits 0", rc == 0)
            try:
                cli_plan = json.loads(buf2.getvalue())
                check("CLI plan prints valid JSON with the expected shape",
                      set(cli_plan.keys()) == {"tier1", "tier2", "disable_cron_detected", "terminal"})
            except ValueError:
                check("CLI plan prints valid JSON", False)

            # -- error path: plan against a nonexistent state file surfaces a controlled error
            buf3 = io.StringIO()
            with contextlib.redirect_stdout(buf3):
                rc3 = main(["plan", "--state", os.path.join(td, "does-not-exist.json"),
                           "--now", _iso_now()])
            check("CLI plan on a missing state file fails (nonzero, no crash)", rc3 != 0)

    print("\n%d failed" % len(fails))
    if fails:
        print("FAILED: " + ", ".join(fails))
        return 1
    print("all self-tests passed")
    return 0


# --------------------------------------------------------------------------- CLI

def build_parser():
    p = argparse.ArgumentParser(
        description="Compound V epic watcher (v2.11 Scheduler Auto-Resurrection, V2)")
    p.add_argument("--selftest", action="store_true", help="run stdlib self-tests and exit")
    sub = p.add_subparsers(dest="cmd")

    sp = sub.add_parser("emit-prompt",
                        help="print a self-contained scheduler resume prompt for a fresh session")
    sp.add_argument("--epic-id", required=True)
    sp.add_argument("--state", required=True, help="path to epic-state.json")

    sp = sub.add_parser("plan",
                        help="advise the cron/scheduled-tasks tiers from V1's --liveness")
    sp.add_argument("--state", required=True, help="path to epic-state.json")
    sp.add_argument("--now", required=True, help="ISO-8601 timestamp to evaluate liveness at")
    sp.add_argument("--stale-after-min", type=float, default=None,
                    help="passed through to V1's --liveness (default: V1's own default)")
    return p


def main(argv):
    # LANG=C-clean: any non-ASCII in stdout/stderr must not crash the process (mirrors
    # compound-v-epic-state.py's own main()).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    p = build_parser()
    args = p.parse_args(argv)

    if args.selftest:
        return _selftest()
    if not args.cmd:
        p.print_help()
        return 1
    if args.cmd == "emit-prompt":
        return cmd_emit_prompt(args)
    if args.cmd == "plan":
        return cmd_plan(args)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
