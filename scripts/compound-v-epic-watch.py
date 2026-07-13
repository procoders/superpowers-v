#!/usr/bin/env python3
"""
Compound V epic watcher -- v2.11 Scheduler Auto-Resurrection, Component 2 (NEW file).

Emits the watcher's scheduler resume prompt and advises the two scheduler tiers; the
DRIVER (Component 3 -- v-epic.md / epic-mode.md / v-init.md, not yet built) makes the
actual harness scheduling calls (CronCreate / mcp__scheduled-tasks__create_scheduled_task)
and owns the real arm/disarm wiring. This file never talks to a scheduler directly.

This file NEVER re-implements scripts/compound-v-epic-state.py's ("V1") liveness/terminal/
breaker/registry logic -- every fact it needs (liveness, terminality, the watcher
registry) is obtained by invoking V1 as a subprocess and reading its JSON stdout. See
compound-v-epic-state.py's own docstring, section "CLI contract (v2.11 V1 -- Scheduler
Auto-Resurrection...)", for the frozen contract this file consumes. Post-integration-review
BLOCKER fix: V1's `owner_pid`/lease were REMOVED entirely (the Claude Code harness has no
stable driver pid) -- `last_progress_at` + V1's `--claim-resume` flock are now the sole
liveness/ownership authority; this file never had any pid logic of its own to fix:
  --liveness --state S --now T [--stale-after-min N]
      -> {"incomplete","stale","epic_status","terminal","resume_count"}
  --claim-resume --state S --now T [--stale-after-min N]
      -> {"claimed","reason":"claimed|live|terminal|resume-cap","resume_count"}
  --list-watchers --state S -> [{"provider","task_id","armed_at","status"}, ...] (armed only)
  --record-watcher-armed / --record-watcher-disarmed --state S --provider P --task-id ID
  is_terminal(state) -- the canonical terminal classifier folded into --liveness/--claim-resume.

Two subcommands:

  emit-prompt --epic-id E --state S
      Prints a SELF-CONTAINED scheduler resume prompt: plain text meant to be handed to a
      scheduler tool (CronCreate's prompt / scheduled-tasks' prompt) so a FRESH, memoryless
      session can act on it with zero conversational context. It instructs that session to
      call V1's --claim-resume (the one atomic resume authority), branch on the result
      (resume via /v:epic, no-op on a live foreign lease, or an inline terminal handler on
      a terminal/resume-cap verdict). Post-integration-review BLOCKER fix: that terminal
      handler ONLY pauses its own Tier-2 task (mcp__scheduled-tasks__update_scheduled_task,
      enabled: false) -- a scheduled firing can never delete the very task that launched it
      (self-deletion is refused), and it never attempts a Tier-1 CronList/CronDelete sweep
      either, since Tier-1 is session-scoped and, by the time ANY scheduled firing of this
      prompt runs, the original session that might have held it is already gone. A full
      hard-delete of both tiers happens only from a LIVE, non-scheduled driver session
      (v-epic.md's own "Watch disarm"), never from this prompt. Also carries the global
      model/commit/no-fabricated-metrics constraints. Never touches epic-state.json itself
      -- it only prints text.

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


def deterministic_id_prefix(epic_id):
    """The shared textual prefix underlying both deterministic ids -- 'compound-v-watch-
    <epic_id>-'. Tier-2's exact `taskId` is this prefix + 'tier2'.

    v2.11 HIGH-1 fix: this prefix is INFORMATIONAL/derivational ONLY -- kept because
    `deterministic_task_id` is built from it -- and MUST NEVER be used for matching/adopt/
    disarm decisions. Epic ids legally contain hyphens (`ID_RE_OK` includes '-'), so this
    prefix for epic "foo" ("compound-v-watch-foo-") is itself a literal STRING PREFIX of a
    DIFFERENT epic "foo-bar"'s own id/marker ("compound-v-watch-foo-bar-tier2", or the
    Tier-1 marker text) -- a prefix/substring sweep keyed on this value would wrongly treat
    "foo-bar"'s watcher as "foo"'s own. Every operational match in this file uses either
    EXACT equality (Tier-2's `taskId`, via `deterministic_task_id`) or the `|`-delimited
    `tier1_marker` token instead -- see both docstrings."""
    return "compound-v-watch-%s-" % epic_id


_TIER1_MARKER_TMPL = "[compound-v-watch|%s|tier1]"


def tier1_marker(epic_id):
    """v2.11 HIGH-1 fix: the UNAMBIGUOUS delimited token embedded in a Tier-1 (session cron)
    task's own prompt text -- the ONLY string a CronList adopt/disarm sweep may match on for
    Tier-1. Bounded by literal "|" on both sides of the epic id, so the id is matched
    EXACTLY, never as a bare prefix/substring. That distinction matters because epic ids
    legally contain hyphens (`ID_RE_OK` includes "-"): the OLD design's plain string prefix
    "compound-v-watch-<epic_id>-" for epic "foo" IS itself a literal prefix of epic
    "foo-bar"'s own id/marker text, so a prefix/substring sweep for epic "foo" would also
    match (and delete) epic "foo-bar"'s Tier-1 watcher -- a genuine cross-epic collision.
    Delimiting the id between two "|" characters closes that: "[compound-v-watch|foo|tier1]"
    is never a substring of "[compound-v-watch|foo-bar|tier1]" or vice versa, regardless of
    any shared hyphenated prefix between the two epic ids.

    Safety of the delimiter itself: `_validate_epic_id` enforces the SAME fixed charset
    (`_ID_RE_OK`) already used at `--init` (compound-v-epic-state.py's `ID_RE_OK`), which
    never contains "|", whitespace, or "/" -- so no epic id that passes validation can ever
    break out of, or collide with, this delimiting. The `assert` below is defense-in-depth
    only (guards a future accidental charset widening), not the primary guard."""
    epic_id = _validate_epic_id(epic_id)
    assert "|" not in epic_id and "\n" not in epic_id  # _validate_epic_id already guarantees this
    return _TIER1_MARKER_TMPL % (epic_id,)


def deterministic_task_id(epic_id, provider):
    """The deterministic per-(epic, tier) id -- the sole naming convention (not a fallback).

    Tier-2 (scheduled-tasks): mcp__scheduled-tasks__create_scheduled_task REQUIRES a
    caller-chosen `taskId` ("used as the directory name and storage key", auto-sanitized) --
    so this value IS the real taskId whenever this flow created it, and
    list_scheduled_tasks will surface it under this EXACT id if it exists. BOTH arm-adopt
    and disarm match this value by EXACT string equality only (never startswith/contains) --
    closing both the crash window where a Tier-2 task could be created but never recorded,
    and (v2.11 HIGH-1 fix) the cross-epic collision a prefix/substring match would risk,
    since epic ids can contain hyphens.

    Tier-1 (session CronCreate): this return value is a DISPLAY-ONLY id ("compound-v-watch-
    <epic_id>-tier1") -- the harness's cron-create schema does not document a caller-chosen
    id, so Tier-1 never uses this string for matching. The OPERATIONAL Tier-1 identifier is
    `tier1_marker(epic_id)` (the `|`-delimited token embedded verbatim in the cron task's
    own prompt text via PROMPT_TEMPLATE) -- CronList reconciliation matches on that exact
    delimited token, never on this function's plain, ambiguous-prefix return value."""
    if provider == "cron":
        return deterministic_id_prefix(epic_id) + "tier1"
    if provider == "scheduled-tasks":
        return deterministic_id_prefix(epic_id) + "tier2"
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
STEP 1 -- Determine the current time
===============================================================================
- The current UTC time in ISO-8601 (for --now):
    python3 -c "import datetime; print(datetime.datetime.now(datetime.timezone.utc).isoformat())"

===============================================================================
STEP 2 -- Attempt the ONE atomic resume claim
===============================================================================
This is the sole authority for whether you may resume this epic. Never skip it and never
reimplement its logic yourself -- call it exactly as written, substituting Step 1's value:

    python3 scripts/compound-v-epic-state.py --claim-resume \\
      --state "{state_path}" --now <UTC_ISO_FROM_STEP_1>

It prints exactly one JSON object:
    {{"claimed": true|false, "reason": "claimed|live|terminal|resume-cap", "resume_count": N}}

===============================================================================
STEP 3 -- Branch on the result
===============================================================================

BRANCH A -- claimed == true (reason "claimed")
  A live, crash-safe resume was granted. Re-invoke:

      /v:epic {epic_id}

  Let it run to its next natural stopping point. Obey the GLOBAL CONSTRAINTS below for
  any work you perform in this branch.

BRANCH B -- claimed == false AND reason == "live"
  Another process is actively working this epic (its heartbeat is still fresh -- something
  bumped last_progress_at recently). This is a normal, expected outcome, not an error. Do
  NOT resume. Do NOT disarm anything. Exit now -- no further action needed.

BRANCH C -- claimed == false AND reason is "terminal" OR "resume-cap"
  The epic is permanently done, blocked_needing_human, or has exhausted its resume cap --
  it will never make further autonomous progress without a human. Do NOT re-invoke
  /v:epic. Instead, perform the FULL DISARM below, then exit.

===============================================================================
BRANCH C -- FULL DISARM (only when reason is "terminal" or "resume-cap")
===============================================================================
This SCHEDULED firing may have been launched by EITHER tier -- it never knows which for
certain, and it must never assume it is "self" for a tier it did not verify. It ONLY ever
PAUSES its own Tier-2 task below (never deletes anything, on either tier). A full
hard-delete of both tiers happens separately, only from a LIVE, non-scheduled `/v:epic`
driver session (its own "Watch disarm" section) -- never from this scheduled prompt.

MATCH EXACTLY -- never a shared string prefix. Epic ids can contain hyphens, so a bare
prefix/substring sweep is UNSAFE: it would also match (and delete/pause) a DIFFERENT epic
whose id happens to start with this epic's id plus a hyphen (e.g. this epic "{epic_id}" vs
some other epic "{epic_id}-something-else"). Use exact equality below, nothing looser.

1. Tier-2 self-pause (scheduled-tasks): call mcp__scheduled-tasks__list_scheduled_tasks (it
   takes no arguments -- it returns every scheduled task). Find the task whose "taskId" is
   EXACTLY "{sched_id}" (exact string equality -- never startswith/contains). If found:
   - PAUSE it -- never delete it: mcp__scheduled-tasks__update_scheduled_task, passing that
     exact "taskId" and enabled: false. A scheduled firing can never delete the very task
     that launched it (the scheduler REFUSES self-deletion on delete_scheduled_task), so a
     delete call here would simply fail and leave the task live forever; update with
     enabled: false is allowed on self and permanently stops it from firing again, which is
     everything a terminal epic needs from this tier.
   - Record the disarm (a permanently paused task will never fire again, so the registry
     treats it exactly like a deleted one):

       python3 scripts/compound-v-epic-state.py --record-watcher-disarmed \\
         --state "{state_path}" --provider scheduled-tasks --task-id "{sched_id}"

   No task with that exact taskId is expected and harmless -- not a failure.

2. Tier-1 (session cron): take NO action here -- do not list this session's cron tasks and
   do not delete anything on this tier from this branch. Tier-1 is session-scoped -- if
   THIS firing arrived via Tier-2, the ORIGINAL session that might have held a Tier-1
   session-cron task for this epic is already gone (that is precisely what made this a
   scheduled resurrection), and its Tier-1 task died with it; there is nothing left for
   this cold, memoryless session to find. A LIVE, non-scheduled driver session performs the
   real Tier-1 hard-delete when one still exists (see its "Watch disarm" section) -- never
   a scheduled firing.
   (Identification only, not an instruction: this epic's Tier-1 delimited marker is
   "{tier1_marker}" -- it is embedded here only so that a LIVE driver's own session-cron
   crash-reconciliation sweep can still find and adopt/remove an orphaned Tier-1 job by
   this exact token; this firing itself never searches for or acts on it.)

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
        sched_id=deterministic_task_id(epic_id, "scheduled-tasks"),
        tier1_marker=tier1_marker(epic_id),
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

    check("deterministic_id_prefix", deterministic_id_prefix("E1") == "compound-v-watch-E1-")
    check("deterministic_task_id: cron -> tier1 id (display only, NEVER matched on)",
          deterministic_task_id("E1", "cron") == "compound-v-watch-E1-tier1")
    check("deterministic_task_id: scheduled-tasks -> tier2 EXACT taskId",
          deterministic_task_id("E1", "scheduled-tasks") == "compound-v-watch-E1-tier2")
    expect_raises("deterministic_task_id rejects an unknown provider",
                  deterministic_task_id, "E1", "bogus")

    # ---- HIGH-1 fix: namespace-safe watcher ids -- epic "foo" vs epic "foo-bar" must NEVER
    # collide on arm-adopt or disarm. Epic ids legally contain hyphens (ID_RE_OK includes
    # "-"), so a bare prefix/substring match is unsafe: the OLD id_prefix for "foo" IS a
    # literal string prefix of "foo-bar"'s own deterministic ids/markers -- demonstrated
    # below as the documented reason the fix exists, NOT as behavior this file still uses
    # for matching.
    check("regression proof: the OLD id_prefix for 'foo' IS a substring of 'foo-bar''s "
          "Tier-2 taskId (why a prefix sweep is unsafe and must never be used for matching)",
          deterministic_task_id("foo-bar", "scheduled-tasks").startswith(deterministic_id_prefix("foo")))

    check("tier1_marker: builds the delimited token", tier1_marker("foo") == "[compound-v-watch|foo|tier1]")
    marker_foo = tier1_marker("foo")
    marker_foobar = tier1_marker("foo-bar")
    check("HIGH-1: tier1_marker('foo') is NOT a substring of tier1_marker('foo-bar')",
          marker_foo not in marker_foobar)
    check("HIGH-1: tier1_marker('foo-bar') is NOT a substring of tier1_marker('foo')",
          marker_foobar not in marker_foo)
    sched_foo = deterministic_task_id("foo", "scheduled-tasks")
    sched_foobar = deterministic_task_id("foo-bar", "scheduled-tasks")
    check("HIGH-1: Tier-2 exact taskIds for 'foo' and 'foo-bar' are different strings",
          sched_foo != sched_foobar)
    check("HIGH-1: an EXACT-equality Tier-2 match for 'foo' never matches 'foo-bar''s taskId "
          "(the disarm/adopt check must use ==, never startswith/in)",
          sched_foo != sched_foobar and sched_foo not in sched_foobar)

    expect_raises("tier1_marker rejects a structurally unsafe epic-id",
                  tier1_marker, "bad id\nwith newline")
    for weird in ["a.b", "a_b", "a123"]:
        check("tier1_marker accepts a valid, delimiter-safe epic-id %r" % (weird,),
              "|" not in weird and tier1_marker(weird) == "[compound-v-watch|%s|tier1]" % (weird,))
    # Defense in depth: NO character in the fixed ID_RE_OK charset can ever break the "|"
    # delimiter -- confirms tier1_marker's own internal assert can never fire via a
    # legitimately-validated epic id (the primary guard is _validate_epic_id's charset).
    check("ID_RE_OK charset (what _validate_epic_id enforces) never contains '|'",
          "|" not in _ID_RE_OK)

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
        "--now",
        "/v:epic epic-alpha",
        "reason == \"live\"",
        "mcp__scheduled-tasks__list_scheduled_tasks",
        "mcp__scheduled-tasks__update_scheduled_task",
        "enabled: false",
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

    # BLOCKER 2 fix: a SCHEDULED Tier-2 firing can never delete the very task that
    # launched it (mcp__scheduled-tasks__delete_scheduled_task REFUSES self-deletion) --
    # the terminal branch must PAUSE its own Tier-2 task (update_scheduled_task,
    # enabled: false), never attempt to delete it, and must never attempt a Tier-1 self
    # cron delete either (a scheduled firing's own session never created Tier-1, and by
    # the time ANY scheduled firing of this prompt runs, the ORIGINAL session that might
    # have held a Tier-1 CronCreate task is already gone, taking that Tier-1 task with
    # it -- session-only). Only a LIVE, non-scheduled driver session (v-epic.md's own
    # "Watch disarm") still hard-deletes via delete_scheduled_task/CronDelete.
    check("emit-prompt terminal branch does NOT attempt to delete its own Tier-2 task",
          "mcp__scheduled-tasks__delete_scheduled_task" not in prompt)
    check("emit-prompt terminal branch does NOT attempt a Tier-1 CronDelete",
          "CronDelete" not in prompt)
    check("emit-prompt terminal branch does NOT call CronList (nothing to sweep -- "
          "Tier-1, if it ever existed, died with the original session)",
          "CronList" not in prompt)

    # v2.11 crash-window fix: the terminal branch's Tier-2 self-pause must reconcile
    # against the PROVIDER'S OWN list (list_scheduled_tasks) -- never the epic-state.json
    # watcher_registry alone (that is only a cache and cannot be trusted for existence; a
    # task created but never recorded would otherwise be invisible to a registry-only
    # check, letting a Tier-2 task orphan forever, live and unpaused).
    check("emit-prompt DISARM branch no longer keys off the registry's --list-watchers",
          "--list-watchers" not in prompt)

    # v2.11 HIGH-1 fix: DISARM must match EXACT ids/markers, never a shared string prefix
    # (epic ids can contain hyphens -- "foo" vs "foo-bar" collide on a prefix sweep).
    sched_alpha = deterministic_task_id("epic-alpha", "scheduled-tasks")
    marker_alpha = tier1_marker("epic-alpha")
    check("emit-prompt names the Tier-2 EXACT taskId to match", sched_alpha in prompt)
    check("emit-prompt's Tier-2 pause instructs EXACT equality, not startswith/contains",
          "EXACTLY" in prompt or "exact equality" in prompt.lower())
    check("emit-prompt no longer instructs a 'starts with'-style prefix sweep for DISARM",
          "starts with" not in prompt.lower() and "prefix sweep" not in prompt.lower())

    # BLOCKER 2 fix: the Tier-1 delimited marker is still embedded verbatim in the prompt
    # (it IS the cron task's own prompt text, so a LIVE driver's later CronList
    # crash-reconciliation sweep -- see v-epic.md's arming/"Watch disarm" -- can still find
    # an orphaned Tier-1 job by this exact token), but this SCHEDULED firing's own terminal
    # branch never instructs itself to search for or act on it -- see the CronList/CronDelete
    # absence checks above. "delimited marker" documents the token for identification only.
    check("emit-prompt still embeds the Tier-1 delimited marker (crash-reconciliation "
          "identification only, never an instruction to this firing)", marker_alpha in prompt)
    check("emit-prompt documents the marker as identification-only via the phrase "
          "'delimited marker'", "delimited marker" in prompt.lower())

    # post-integration-review BLOCKER fix: the prompt must NEVER instruct a fresh session to
    # compute or pass its own OS pid -- there is no stable driver pid in this harness, which
    # is the whole reason owner_pid/lease were removed from V1's --claim-resume contract.
    check("emit-prompt drops the pid step entirely (no --owner-pid anywhere)",
          "--owner-pid" not in prompt and "os.getpid" not in prompt)

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

            # -- fixture 3: terminal via resume-cap (a breaker trip mid-run, not "done").
            # Post-integration-review BLOCKER fix: no more --owner-pid/--lease-ttl-min --
            # staleness (last_progress_at age vs. the default 45min threshold) is now the
            # sole liveness signal. --init's own --now seeds started_at well in the past so
            # the FIRST claim-resume already sees a genuinely stale epic and wins.
            cap_state = os.path.join(td, "cap-state.json")
            t0 = datetime.now(timezone.utc)
            t_started = t0 - timedelta(minutes=50)  # > default 45min stale_after_min
            rc, out, err = _run_epic_state([
                "--init", "--stance", "marathon", "--watch", "--max-resume-count", "1",
                "--features", feats_path, "--epic-id", "epic-cap", "--out", cap_state,
                "--now", t_started.isoformat(),
            ])
            check("fixture: resume-cap epic --init succeeds", rc == 0)

            rc, out, err = _run_epic_state([
                "--claim-resume", "--state", cap_state, "--now", t0.isoformat(),
            ])
            check("fixture: first claim-resume succeeds (exit 0)", rc == 0)
            first = json.loads(out) if rc == 0 else {}
            check("fixture: first claim-resume claimed", first.get("claimed") is True)

            # The win at t0 bumped last_progress_at to t0 -- the epic is fresh again right
            # after. It must go stale ONCE MORE (> 45min later) before the resume-cap check
            # is even reached (claim_resume checks freshness BEFORE the cap -- see its
            # docstring), at which point resume_count(1) >= max_resume_count(1) trips it.
            t1 = t0 + timedelta(minutes=50)
            rc, out, err = _run_epic_state([
                "--claim-resume", "--state", cap_state, "--now", t1.isoformat(),
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
