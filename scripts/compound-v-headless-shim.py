#!/usr/bin/env python3
"""
Compound V headless resurrection shim -- v2.14 Feature B (NEW file, PRESENT-ONLY generator).

Prints -- never installs -- an OS-level scheduler artifact (a macOS launchd plist or a
Linux crontab line) plus a runbook, so a user can OPT IN to headless resurrection of a
marathon epic while the Claude Code desktop app is closed. Today's Tier-2 scheduler
(mcp__scheduled-tasks) fires only while the app is OPEN; a user who wants resurrection
while the app is CLOSED needs an OS-level scheduler. This file GENERATES that add-on --
it is the user, never the plugin, who installs it.

Hard boundaries (each mirrors an acceptance criterion in the v2.14 spec, Feature B):

  * PRESENT-ONLY. This script NEVER shells out to `launchctl` or `crontab`, and never runs
    the generated agent. The ONLY subprocess it ever spawns is
    `compound-v-epic-watch.py emit-prompt` (to capture the Tier-2 resume prompt at emit
    time) -- a pure text producer, no scheduler, no model call. `launchctl`/`crontab`
    appear in this file ONLY inside the emitted-text/runbook strings, never as a
    subprocess argument. (--selftest asserts exactly one subprocess.run and that no
    subprocess line names launchctl/crontab.)

  * SAFE POSTURE + HONEST BOUNDARY. The emitted `claude` invocation uses
    `--permission-mode dontAsk` plus a NON-EMPTY, curated read-mostly `--allowedTools`
    allowlist (`ALLOWED_TOOLS`). A headless `claude -p` under the user's INTERACTIVE posture
    STALLS on the first tool prompt (no TTY); the naive "fix"
    `--dangerously-skip-permissions` is (a) the flag that DELETED this very repo on
    2026-07-13 and (b) not even the real headless flag (it still prompts on first use).
    `dontAsk` runs read-only + the allowlist and REFUSES everything else -- it never blocks
    and never bypasses. The default allowlist is deliberately the SAFE SUBSET: it covers the
    resume CLAIM + liveness + read/report, but NOT the build. The resume prompt's Branch A
    (/v:epic -> Task subagents + dispatch + git add/git commit) and Branch C
    (mcp__scheduled-tasks__* self-disarm) are OFF the default list, so under it a fired
    session claims + reports then STOPS, refusing the build/commit/re-arm steps -- the safety
    system working BY DESIGN. Running a full marathon headless is an UNATTENDED-AUTONOMY
    decision only the user can make: `emit --allow-build` bakes in exactly the wider
    `BUILD_TOOLS` set (Task, git add/commit, scheduled-tasks). Neither posture ever emits
    `--dangerously-skip-permissions` / `--allow-dangerously-skip-permissions` / `--yolo` /
    blanket `Bash(*)`.

  * LAUNCHD TRAPS PRE-EMPTED (macOS). The plist bakes the ABSOLUTE `claude` path (resolved
    via shutil.which at emit time -- the emit FAILS with a clear stderr message + nonzero
    exit if unresolved, never emitting a bare `claude` that launchd's minimal PATH would
    fail to find), sets `WorkingDirectory` = the epic's ABSOLUTE repo root (else launchd
    starts in an unrelated cwd and the resume prompt's RELATIVE `scripts/...` calls fail),
    sets `StandardInPath` = /dev/null (else `claude -p` exits "no stdin data received"),
    routes `StandardOutPath`/`StandardErrorPath` to a log file so a silent failure is
    diagnosable, uses `StartCalendarInterval` = array of two dicts (Minute 17 / Minute 47,
    NO Hour key => hourly), and sets `RunAtLoad` false (scheduled only). The PRIMARY install
    command printed is `launchctl bootstrap gui/$(id -u) <plist>`
    (+ `launchctl bootout gui/$(id -u)/<label>` teardown), with legacy `load`/`unload`
    noted as a fallback for old macOS -- always a USER step, never executed here.

  * LINUX CRON. A crontab line `17,47 * * * *` (matching compound-v-epic-watch.py's
    TIER1_CRON_SCHEDULE) that `cd`s into the epic's ABSOLUTE repo root before running the
    ABSOLUTE `claude` path (so the resume prompt's RELATIVE `scripts/...` calls resolve),
    with a `< /dev/null` redirect and the same `dontAsk` + allowlist posture. Any path
    landing on the command line is rejected if it contains a `%` (cron treats an unescaped
    `%` as a newline/stdin separator that would corrupt the line). Installed by the USER via
    `crontab -e` / append.

  * REPO ROOT. Resolved deterministically at emit time (resolve_repo_root): walk up from the
    --state file's directory to a `.git`, else fall back to this script's own location. If
    neither yields a repo root the emit FAILS -- never emit an artifact that would cd
    nowhere.

CLI:
  compound-v-headless-shim.py emit --epic-id E --state S [--interval-min 30]
      [--os macos|linux] [--allow-build]
  compound-v-headless-shim.py --selftest

  --allow-build (OFF by default) ALSO bakes the wider build/commit/re-arm tools (Task,
  git add, git commit, scheduled-tasks) into the emitted allowlist so the headless session
  can run the FULL pipeline UNATTENDED -- an explicit unattended-autonomy opt-in. Without it,
  the emitted artifact carries only the SAFE SUBSET (claim + liveness + report, then stops).

  --os defaults to auto-detection from sys.platform (darwin -> macos, linux -> linux).
  --interval-min is accepted but the schedule stays the off-minute :17/:47 twin cadence
  (launchd/cron coalesce missed slots => effectively one catch-up per wake); a malformed or
  non-positive value is a clean nonzero-exit refusal, never a traceback.

Python 3.9-safe, stdlib only (argparse, shutil, plistlib, subprocess-only-for-epic-watch).
LANG=C-clean (stdout/stderr reconfigured to utf-8/replace; all emitted text is plain ASCII).
No fabricated cost/token/performance metrics anywhere in this file.
"""
import argparse
import io
import os
import plistlib
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EPIC_WATCH_SCRIPT = os.path.join(HERE, "compound-v-epic-watch.py")

# Same charset compound-v-epic-state.py / -epic-watch.py validate an epic_id against. The
# epic id is interpolated into a launchd Label, a log filename, and (on Linux) a shell
# command line -- so a structurally unsafe id is refused outright, never interpolated.
_ID_RE_OK = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"

# A path we embed inside a single-quoted POSIX-shell command substitution (the Linux cron
# line). Reject anything that could break out of that quoting or inject a command. The
# double-quote/newline/CR/NUL subset already matches epic-watch's own _validate_state_path;
# the single-quote/backtick/$ additions are specific to the shell-embedding on this path.
_STATE_SHELL_BAD = re.compile(r"['\"`$\r\n\x00]")

# Off-minute twin cadence: fires at :17 and :47 past the hour (~30 min apart), avoiding the
# top-of-hour rush other jobs cluster on. Byte-identical to compound-v-epic-watch.py:80's
# TIER1_CRON_SCHEDULE so both schedulers agree.
CRON_SCHEDULE = "17,47 * * * *"
CAL_MINUTES = (17, 47)

# Safe non-interactive posture. dontAsk RUNS read-only + this allowlist and REFUSES
# everything off-list -- it never stalls (unlike the user's interactive posture) and never
# bypasses (unlike --dangerously-skip-permissions).
#
# HONEST BOUNDARY (this is the SAFE SUBSET, NOT the full resume surface). This default
# allowlist deliberately covers ONLY the resume CLAIM + liveness + read/report -- the part
# that is safe to run headless with no human present. It does NOT cover what the resume
# prompt (compound-v-epic-watch.py's PROMPT_TEMPLATE) needs to actually COMPLETE a build:
#   - BRANCH A drives `/v:epic`, which spawns `Task` subagents, dispatches the pipeline, and
#     commits with `git add` / `git commit` -- NONE on this list.
#   - BRANCH C calls the `mcp__scheduled-tasks__*` MCP tools to self-disarm -- NOT on this
#     list.
# So under this default a fired session runs Step 1 (--now), Step 2 (--claim-resume), reads
# and REPORTS -- then STOPS, refusing the build/commit/re-arm steps. That refusal is the
# safety system working BY DESIGN, not a bug (see BUILD_TOOLS + the runbook BOUNDARY block
# for how a user consciously widens it). What the safe subset DOES cover:
#   - `Bash(python3 -c:*)`                              STEP 1 computes the UTC --now value
#   - `Bash(python3 scripts/compound-v-epic-state.py:*)` STEP 2 --claim-resume (the CLAIM)
#   - `Bash(python3 scripts/compound-v-epic-watch.py:*)`  read/inspect the watcher liveness
#   - Read,Grep,Glob                                    inspection + reporting
#   - `Bash(git status:*)`,`Bash(git log:*)`            read-only VCS inspection
# Under launchd/cron the cwd is set to the repo root (see resolve_repo_root), so these
# RELATIVE `scripts/...` patterns match the commands the prompt runs verbatim. Comma-
# separated so the space inside each Bash() specifier stays within one field.
ALLOWED_TOOLS = (
    "Read,Grep,Glob,"
    "Bash(python3 -c:*),"
    "Bash(python3 scripts/compound-v-epic-state.py:*),"
    "Bash(python3 scripts/compound-v-epic-watch.py:*),"
    "Bash(git status:*),Bash(git log:*)"
)

# The wider patterns a FULL headless marathon needs but the safe default WITHHOLDS. Branch A
# of the resume prompt spawns `Task` subagents + runs the dispatch pipeline + commits with
# `git add`/`git commit`; Branch C calls the scheduled-tasks MCP tools to self-disarm.
# Enabling these headless grants UNATTENDED AUTONOMOUS EXECUTION of the whole pipeline -- the
# exact risk class behind this repo's 2026-07-13 deletion incident -- so they are OFF by
# default and added ONLY when the user EXPLICITLY passes `emit --allow-build`. This set is a
# NARROW, SPECIFIC widening: it NEVER includes any `--dangerously-*` / `--yolo` / blanket
# `Bash(*)` (those stay banned regardless of --allow-build).
BUILD_TOOLS = (
    "Task,"
    "Bash(git add:*),Bash(git commit:*),"
    "mcp__scheduled-tasks__*"
)

# The exact widening list, human-readable, quoted once so the runbook + preamble + selftest
# all reference the SAME literal string (no drift between doc text and the baked allowlist).
WIDEN_LIST_TEXT = "Task, Bash(git add:*), Bash(git commit:*), mcp__scheduled-tasks__*"


def allowed_tools_for(allow_build=False):
    """The allowlist baked into an emitted artifact. Default = the SAFE SUBSET (claim +
    liveness + report). With allow_build=True ALSO append BUILD_TOOLS (Task + git add/commit
    + scheduled-tasks) so a user who has consciously accepted unattended autonomy gets a
    working full-marathon artifact without hand-editing. NEVER adds a bypass flag."""
    if allow_build:
        return ALLOWED_TOOLS + "," + BUILD_TOOLS
    return ALLOWED_TOOLS

# Bypass tokens that must NEVER appear in an emitted artifact (the repo-deletion incident
# class). Asserted absent by --selftest for both OSes.
_BANNED_FLAGS = (
    "--dangerously-skip-permissions",
    "--allow-dangerously-skip-permissions",
    "--yolo",
)


def _validate_epic_id(value):
    if not value or value in (".", "..") or any(c not in _ID_RE_OK for c in value):
        raise ValueError("--epic-id must match [A-Za-z0-9._-]+ (got %r)" % (value,))
    return value


def _validate_state_for_shell(value):
    """The Linux cron line embeds --state inside a single-quoted `$(... --state '<S>')`
    substitution, so reject any char that could break that quoting or inject a command.
    (macOS never needs this: the state there lives only inside the captured prompt text,
    which epic-watch already validated.)"""
    if not value:
        raise ValueError("--state must be a non-empty path")
    if _STATE_SHELL_BAD.search(value):
        raise ValueError(
            "--state contains a shell-unsafe character (quote/backtick/$/newline); "
            "refusing to embed it in a crontab line (got %r)" % (value,))
    return value


def _validate_shell_single_quoted(value, label):
    """Reject any char that could break out of a single-quoted POSIX-shell field or inject a
    command. Used for paths (repo root) embedded in the Linux cron `cd '<...>'` prefix."""
    if not value:
        raise ValueError("%s must be a non-empty path" % (label,))
    if _STATE_SHELL_BAD.search(value):
        raise ValueError(
            "%s contains a shell-unsafe character (quote/backtick/$/newline); "
            "refusing to embed it in a crontab line (got %r)" % (label, value))
    return value


def _reject_cron_percent(value, label):
    """cron treats an unescaped `%` in the command specially (it becomes a newline/stdin
    separator), so a path containing `%` would silently corrupt the crontab line. Reject it
    with a clear message. Linux cron path ONLY -- the macOS plist is unaffected by `%`."""
    if "%" in value:
        raise ValueError(
            "%s contains a '%%' character, which cron treats specially (it becomes a "
            "newline/stdin separator and would corrupt the crontab line); refusing to embed "
            "it -- rename the path to drop the '%%' (got %r)" % (label, value))
    return value


def _find_git_root(start_dir):
    """Walk up from start_dir looking for a `.git` entry (a DIR normally, or a FILE in a git
    worktree -- Compound V dispatches inside worktrees, so both must count). Returns the
    absolute dir that contains it, or None. A pure path walk: it does NOT require start_dir
    itself to exist, so it also resolves for a not-yet-created --state path."""
    d = os.path.abspath(start_dir)
    while True:
        if os.path.exists(os.path.join(d, ".git")):
            return d
        parent = os.path.dirname(d)
        if parent == d:  # reached the filesystem root
            return None
        d = parent


def resolve_repo_root(state, here=None):
    """Resolve the ABSOLUTE repo root the resume must run from. launchd and cron start in an
    unrelated cwd, but the captured resume prompt invokes RELATIVE paths like
    `scripts/compound-v-epic-state.py` -- so the emitted artifact MUST cd into the repo
    first (plist WorkingDirectory / cron `cd '<root>' &&`). Deterministic resolution order:
    (1) walk up from the --state file's directory to a `.git`; (2) fall back to walking up
    from THIS script's own location (the plugin lives in the repo). Returns an absolute path
    or None -- the caller FAILS the emit rather than emit a cd-nowhere artifact."""
    state_root = _find_git_root(os.path.dirname(os.path.abspath(state)))
    if state_root:
        return state_root
    return _find_git_root(here or HERE)


def _normalize_os(value):
    if value in ("macos", "linux"):
        return value
    if value is None or value == "auto":
        plat = sys.platform
        if plat == "darwin":
            return "macos"
        if plat.startswith("linux"):
            return "linux"
        raise ValueError(
            "cannot auto-detect a supported OS from sys.platform=%r; pass --os macos|linux"
            % (plat,))
    raise ValueError("--os must be macos or linux (got %r)" % (value,))


def resolve_claude(claude_bin=None, env=None):
    """Resolve the ABSOLUTE `claude` path at emit time. launchd/cron run with a minimal
    PATH, so a bare `claude` would silently never be found -- we bake the absolute path or
    fail the emit. Test seam: an explicit `claude_bin` (or COMPOUND_V_HEADLESS_CLAUDE_BIN)
    lets --selftest run on a machine without claude installed and never touches a real
    binary. Returns an absolute path string, or None if unresolved."""
    env = env if env is not None else os.environ
    override = claude_bin or env.get("COMPOUND_V_HEADLESS_CLAUDE_BIN")
    if override:
        return os.path.abspath(override)
    # Honor env's PATH so callers/tests can simulate a claude-less environment (env={"PATH":
    # ""}); path=None makes shutil.which fall back to the real os.environ PATH.
    found = shutil.which("claude", path=env.get("PATH"))
    return os.path.abspath(found) if found else None


def label_for(epic_id):
    """launchd Label / plist basename stem: dev.compound-v.watch.<epic-id>."""
    return "dev.compound-v.watch.%s" % (epic_id,)


def macos_log_path(epic_id):
    return os.path.expanduser("~/Library/Logs/compound-v-watch-%s.log" % (epic_id,))


def macos_plist_path(epic_id):
    return os.path.expanduser("~/Library/LaunchAgents/%s.plist" % (label_for(epic_id),))


def linux_log_path(epic_id):
    return os.path.expanduser("~/.cache/compound-v/watch-%s.log" % (epic_id,))


def _capture_resume_prompt(epic_id, state, python_bin=None, watch_script=None):
    """Capture the Tier-2 resume prompt from compound-v-epic-watch.py emit-prompt. This is
    the ONE and ONLY subprocess this file ever spawns -- a pure text producer (no scheduler,
    no model). epic-watch validates --epic-id/--state itself, so a malformed value surfaces
    here as a nonzero rc + stderr, which we forward as a clean refusal. Returns
    (prompt_str, None) on success or (None, error_str) on failure; never raises."""
    exe = python_bin or sys.executable or "python3"
    script = watch_script or EPIC_WATCH_SCRIPT
    if not os.path.isfile(script):
        return None, "compound-v-epic-watch.py not found next to this script (%s)" % (script,)
    try:
        proc = subprocess.run(
            [exe, script, "emit-prompt", "--epic-id", epic_id, "--state", state],
            stdin=subprocess.DEVNULL, capture_output=True,
            encoding="utf-8", errors="replace", timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, str(exc)
    if proc.returncode != 0:
        return None, (proc.stderr or proc.stdout or "").strip() or (
            "compound-v-epic-watch.py emit-prompt exited %d" % proc.returncode)
    return proc.stdout, None


# --------------------------------------------------------------------------- macOS plist

def build_plist(epic_id, prompt, claude_abs, working_dir, allowed_tools=ALLOWED_TOOLS,
                log_path=None):
    """Build a valid-XML launchd plist (bytes) that runs the captured resume prompt headless
    on the :17/:47 twin cadence. The absolute claude path + dontAsk + allowlist + the
    captured prompt live in ProgramArguments; WorkingDirectory=<repo root> makes the
    prompt's RELATIVE `scripts/...` calls resolve (launchd otherwise starts in an unrelated
    cwd); StandardInPath=/dev/null and the log paths pre-empt launchd's silent-failure
    traps."""
    if not (claude_abs and os.path.isabs(claude_abs)):
        raise ValueError("build_plist requires an absolute claude path (got %r)" % (claude_abs,))
    if not (working_dir and os.path.isabs(working_dir)):
        raise ValueError(
            "build_plist requires an absolute working directory / repo root (got %r)"
            % (working_dir,))
    log_path = log_path or macos_log_path(epic_id)
    program_args = [
        claude_abs,
        "-p",
        "--permission-mode", "dontAsk",
        "--allowedTools", allowed_tools,
        prompt,
    ]
    plist = {
        "Label": label_for(epic_id),
        "ProgramArguments": program_args,
        "WorkingDirectory": working_dir,
        "StartCalendarInterval": [{"Minute": m} for m in CAL_MINUTES],
        "StandardInPath": "/dev/null",
        "StandardOutPath": log_path,
        "StandardErrorPath": log_path,
        "RunAtLoad": False,
    }
    return plistlib.dumps(plist)  # XML plist by default -- valid, DOCTYPE'd XML.


def build_macos_runbook(epic_id, plist_path, log_path):
    label = label_for(epic_id)
    return RUNBOOK_MACOS_TMPL.format(
        epic_id=epic_id, label=label, plist_path=plist_path, log_path=log_path,
        boundary=_BOUNDARY_BLOCK, honesty=_HONESTY_BLOCK, donot=_DONOT_BLOCK)


# --------------------------------------------------------------------------- Linux cron

def build_cron_line(epic_id, state, claude_abs, python_abs, watch_script, repo_root,
                    allowed_tools=ALLOWED_TOOLS, log_path=None):
    """Build the crontab line. The multi-line resume prompt cannot live literally on a
    single crontab line, so we regenerate it at fire time via a command substitution of
    epic-watch emit-prompt -- with ABSOLUTE python + watch-script paths so cron's minimal
    PATH cannot break it. The command is prefixed with `cd '<repo_root>' &&` so the resume
    prompt's RELATIVE `scripts/...` calls resolve (cron otherwise starts in an unrelated
    cwd). Absolute claude path + `< /dev/null` + dontAsk + allowlist as on macOS. Any path
    embedded here is rejected if it contains a shell-unsafe char or a `%` (cron treats an
    unescaped `%` as a newline/stdin separator that would corrupt the line)."""
    if not (claude_abs and os.path.isabs(claude_abs)):
        raise ValueError("build_cron_line requires an absolute claude path (got %r)" % (claude_abs,))
    if not (python_abs and os.path.isabs(python_abs)):
        raise ValueError("build_cron_line requires an absolute python path (got %r)" % (python_abs,))
    if not os.path.isabs(watch_script):
        raise ValueError("build_cron_line requires an absolute watch-script path (got %r)"
                         % (watch_script,))
    if not (repo_root and os.path.isabs(repo_root)):
        raise ValueError("build_cron_line requires an absolute repo root (got %r)" % (repo_root,))
    _validate_state_for_shell(state)
    _validate_shell_single_quoted(repo_root, "repo root")
    log_path = log_path or linux_log_path(epic_id)
    # `%` hazard: reject it in EVERY path that lands on the cron command line.
    for _val, _label in ((state, "--state"), (repo_root, "repo root"), (log_path, "log path")):
        _reject_cron_percent(_val, _label)
    prompt_sub = "\"$('%s' '%s' emit-prompt --epic-id '%s' --state '%s')\"" % (
        python_abs, watch_script, epic_id, state)
    return (
        "%s cd '%s' && '%s' -p --permission-mode dontAsk --allowedTools '%s' %s "
        "< /dev/null >> '%s' 2>&1"
    ) % (CRON_SCHEDULE, repo_root, claude_abs, allowed_tools, prompt_sub, log_path)


def build_linux_runbook(epic_id, cron_line, log_path):
    return RUNBOOK_LINUX_TMPL.format(
        epic_id=epic_id, cron_line=cron_line, log_path=log_path,
        boundary=_BOUNDARY_BLOCK, honesty=_HONESTY_BLOCK, donot=_DONOT_BLOCK)


# --------------------------------------------------------------------------- runbook text

_HONESTY_BLOCK = """\
HONESTY -- what this actually buys you (and what it does not)
-------------------------------------------------------------
- It REMOVES the "desktop app must be open" dependency: an OS-level scheduler fires this
  headless, app closed.
- While the machine is AWAKE it fires on the :17/:47 cadence. On WAKE-FROM-SLEEP it runs
  once to catch up -- missed slots COALESCE into a single catch-up run, so expect roughly
  one catch-up per wake, not one run per missed slot.
- It does NOT run while the machine is POWERED OFF (those slots are simply lost until the
  next live slot) and it does NOT run DURING sleep itself.
- On macOS a `gui/$UID` LaunchAgent only loads once you are logged into the GUI session --
  a FileVault pre-login screen is a dead zone (nothing fires until you log in).
- `max_resume_count` in the epic state still bounds the TOTAL number of resume fires -- this
  scheduler cannot exceed that cap.
- Genuinely always-on resurrection (through power-off, before login, etc.) needs remote
  infrastructure -- that is out of scope here and intentionally not claimed.
"""

_BOUNDARY_BLOCK = """\
BOUNDARY -- what the SHIPPED DEFAULT allowlist lets this headless session do
----------------------------------------------------------------------------
Under the default --allowedTools this artifact ships with, the fired headless session
performs the resume CLAIM + liveness + read/report and then STOPS. It CANNOT complete a
build: the resume prompt's Branch A drives /v:epic (which spawns Task subagents, dispatches
the pipeline, and runs `git add` / `git commit`) and Branch C calls the scheduled-tasks MCP
tools to self-disarm -- NONE of those are on the default allowlist, so the session REFUSES
them and stops. That refusal is the safety system working BY DESIGN, not a failure.

We ship the SAFE SUBSET that claims + reports. Completing a full marathon headless -- build,
commit, and re-arm, all with NO human present -- requires YOU to consciously widen
--allowedTools with EXACTLY these additional patterns:
    Task, Bash(git add:*), Bash(git commit:*), mcp__scheduled-tasks__*
Doing so grants UNATTENDED AUTONOMOUS EXECUTION of the whole pipeline: enabling the build
steps headless is an unattended-autonomy decision only you can make, never the plugin's
default. Widen at your own risk -- and still NEVER via --dangerously-skip-permissions (that
is what deleted this repo; see the DO-NOT block below). Passing `--allow-build` to this
shim's `emit` bakes exactly those patterns into the allowlist for you.
"""

_DONOT_BLOCK = """\
!! DO NOT -- read before you "fix" a stall !!
---------------------------------------------
Never add --dangerously-skip-permissions / --yolo to this job. A headless bypass agent with
NO human present has deleted a repository in this project's own history (2026-07-13).
ALLOWLIST NOTE: under --permission-mode dontAsk the agent runs read-only plus the curated
--allowedTools list and REFUSES anything off it. A resume that needs a tool outside the list
will therefore refuse and stop -- that is the safety system working as designed, not a bug.
The correct response is to WIDEN --allowedTools DELIBERATELY for the specific tools you need
(the BOUNDARY block above names the exact set), never to bypass the permission system.
"""

RUNBOOK_MACOS_TMPL = """\
==============================================================================
Compound V headless resurrection shim -- macOS launchd (PRESENT-ONLY)
Epic: {epic_id}
==============================================================================
This is GENERATED TEXT. Nothing was installed. YOU install it, and YOU can remove it.

STEP 1 -- Save the plist above to:
    {plist_path}

STEP 2 -- Install it (PRIMARY, modern macOS):
    launchctl bootstrap gui/$(id -u) {plist_path}

    (Legacy fallback for old macOS only -- `bootstrap`/`bootout` are preferred now:
        launchctl load {plist_path} )

STEP 3 -- Verify it is registered:
    launchctl print gui/$(id -u)/{label}

TEARDOWN -- stop and unregister it:
    launchctl bootout gui/$(id -u)/{label}
    (Legacy fallback: launchctl unload {plist_path} )

LOG -- diagnose a silent run here (StandardOut/StandardError are routed to it):
    {log_path}

{boundary}
{honesty}
{donot}"""

RUNBOOK_LINUX_TMPL = """\
==============================================================================
Compound V headless resurrection shim -- Linux cron (PRESENT-ONLY)
Epic: {epic_id}
==============================================================================
This is GENERATED TEXT. Nothing was installed. YOU install it, and YOU can remove it.

STEP 1 -- Add the crontab line above:
    crontab -e
  then paste the line as a new entry (or append it to your crontab), and save.

STEP 2 -- Verify it is registered:
    crontab -l

TEARDOWN -- remove that line:
    crontab -e   (delete the line, save)

LOG -- diagnose a silent run here (stdout/stderr are appended to it):
    {log_path}

Note: ensure the log directory exists before the first fire, e.g.:
    mkdir -p "$(dirname '{log_path}')"

{boundary}
{honesty}
{donot}"""


# --------------------------------------------------------------------------- emit

def _artifact_preamble(allow_build):
    """The loud, up-front boundary statement printed ABOVE the scheduler artifact (mirrors
    the runbook BOUNDARY block so the boundary is stated in BOTH places, never buried). The
    default preamble says the session claims + reports then STOPS; the --allow-build preamble
    says the wider build tools are now baked in (unattended autonomy accepted)."""
    if allow_build:
        return (
            "!! --allow-build: this artifact's --allowedTools ALSO bakes in the build/commit/"
            "re-arm tools (%s). The fired headless session can run the FULL pipeline "
            "UNATTENDED with no human present -- an autonomy decision you have accepted. It "
            "still carries NO --dangerously-skip-permissions.\n\n" % WIDEN_LIST_TEXT)
    return (
        "NOTE: under this artifact's SHIPPED DEFAULT --allowedTools, the fired headless "
        "session performs the resume CLAIM + liveness + report and then STOPS -- it REFUSES "
        "the build/commit/re-arm steps (that refusal is the safety system, BY DESIGN). To run "
        "a full marathon headless you must widen --allowedTools with EXACTLY: %s (unattended "
        "autonomy -- your call, never --dangerously-skip-permissions). See the BOUNDARY "
        "section in the runbook below.\n\n" % WIDEN_LIST_TEXT)


def emit(epic_id, state, os_name, claude_bin=None, python_bin=None,
         watch_script=None, env=None, interval_min=None, allow_build=False):
    """Produce (artifact_text, error). On success artifact_text is the full stdout payload
    (boundary preamble + scheduler artifact + runbook); on failure error is a human-readable
    string. interval_min is accepted for the CLI contract but never changes the :17/:47 twin
    cadence (coalescing makes a finer interval meaningless for a wake-catch-up scheduler).
    allow_build=False (default) bakes the SAFE SUBSET allowlist (claim + report); True ALSO
    bakes BUILD_TOOLS (Task + git add/commit + scheduled-tasks) -- an explicit unattended-
    autonomy opt-in, never a bypass flag."""
    try:
        epic_id = _validate_epic_id(epic_id)
        os_name = _normalize_os(os_name)
    except ValueError as exc:
        return None, str(exc)
    if interval_min is not None and interval_min <= 0:
        return None, "--interval-min must be a positive integer of minutes (got %r)" % (interval_min,)

    claude_abs = resolve_claude(claude_bin=claude_bin, env=env)
    if not claude_abs:
        return None, (
            "could not resolve an absolute `claude` path (shutil.which('claude') found "
            "nothing). launchd/cron run with a minimal PATH, so a bare `claude` would never "
            "be found -- install the Claude Code CLI, or set COMPOUND_V_HEADLESS_CLAUDE_BIN "
            "to its absolute path, then re-run.")

    repo_root = resolve_repo_root(state)
    if not repo_root:
        return None, (
            "could not resolve the repository root (no `.git` found walking up from the "
            "--state path %r or from this script's location). launchd/cron start in an "
            "unrelated cwd, but the resume prompt runs RELATIVE `scripts/...` commands, so "
            "the artifact MUST cd into the repo first -- refusing to emit one that would cd "
            "nowhere. Point --state at a path inside the epic's git repo, then re-run."
            % (state,))

    if os_name == "linux":
        try:
            _validate_state_for_shell(state)
            _reject_cron_percent(state, "--state")
            _reject_cron_percent(repo_root, "repo root")
        except ValueError as exc:
            return None, str(exc)

    prompt, perr = _capture_resume_prompt(epic_id, state, python_bin=python_bin,
                                          watch_script=watch_script)
    if prompt is None:
        return None, "could not capture the resume prompt: %s" % (perr,)

    allowed_tools = allowed_tools_for(allow_build)
    preamble = _artifact_preamble(allow_build)

    if os_name == "macos":
        log_path = macos_log_path(epic_id)
        plist_path = macos_plist_path(epic_id)
        try:
            plist_bytes = build_plist(epic_id, prompt, claude_abs, repo_root,
                                      allowed_tools=allowed_tools, log_path=log_path)
        except ValueError as exc:
            return None, str(exc)
        plist_xml = plist_bytes.decode("utf-8", "replace")
        runbook = build_macos_runbook(epic_id, plist_path, log_path)
        artifact = (
            "%s----- BEGIN plist: %s -----\n%s----- END plist -----\n\n%s"
            % (preamble, plist_path, plist_xml, runbook))
        return artifact, None

    # linux
    log_path = linux_log_path(epic_id)
    python_abs = os.path.abspath(python_bin or sys.executable or "python3")
    script = os.path.abspath(watch_script or EPIC_WATCH_SCRIPT)
    try:
        cron_line = build_cron_line(epic_id, state, claude_abs, python_abs, script,
                                    repo_root, allowed_tools=allowed_tools, log_path=log_path)
    except ValueError as exc:
        return None, str(exc)
    runbook = build_linux_runbook(epic_id, cron_line, log_path)
    artifact = (
        "%s----- BEGIN crontab line -----\n%s\n----- END crontab line -----\n\n%s"
        % (preamble, cron_line, runbook))
    return artifact, None


def cmd_emit(args):
    artifact, err = emit(
        args.epic_id, args.state, args.os,
        interval_min=args.interval_min, allow_build=args.allow_build,
    )
    if artifact is None:
        print("headless-shim emit error: %s" % err, file=sys.stderr)
        return 1
    if args.allow_build:
        print(
            "headless-shim WARNING: --allow-build baked the build/commit/re-arm tools (%s) "
            "into --allowedTools. The fired headless session can run the FULL pipeline "
            "UNATTENDED with no human present -- this is your unattended-autonomy decision, "
            "not the plugin's default. (No --dangerously-skip-permissions is ever added.)"
            % WIDEN_LIST_TEXT, file=sys.stderr)
    print(artifact)
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

    fake_claude = "/opt/fake/bin/claude"  # absolute; never touched, never executed.

    def _emit(os_name, epic_id="epic-alpha", state="/repo/exec/epic-alpha/epic-state.json",
              **kw):
        kw.setdefault("claude_bin", fake_claude)
        return emit(epic_id, state, os_name, **kw)

    # ---- unit: validators --------------------------------------------------------------
    check("_validate_epic_id accepts a normal id", _validate_epic_id("my-epic.1") == "my-epic.1")
    for bad in ["", "..", "has/slash", "has space", "with\nnl", "with|pipe"]:
        expect_raises("_validate_epic_id rejects %r" % (bad,), _validate_epic_id, bad)

    check("_validate_state_for_shell accepts a normal path",
          _validate_state_for_shell("/tmp/x/epic-state.json").endswith("epic-state.json"))
    for bad in ["", "has'quote", 'has"quote', "has`tick", "has$var", "has\nnl"]:
        expect_raises("_validate_state_for_shell rejects %r" % (bad,),
                      _validate_state_for_shell, bad)

    # H4.1: repo-root resolution + M6: `%` rejection unit coverage.
    check("resolve_repo_root falls back to this repo when --state is outside any repo",
          os.path.isabs(resolve_repo_root("/dev/null") or ""))
    check("resolve_repo_root(this-file-dir) finds a .git-bearing root",
          os.path.exists(os.path.join(resolve_repo_root("/dev/null") or "", ".git")))
    with tempfile.TemporaryDirectory() as _td:
        # a start dir with no .git anywhere above AND a here= with no .git => None.
        check("resolve_repo_root returns None when neither state nor here has a .git",
              resolve_repo_root(os.path.join(_td, "x/epic-state.json"), here="/") is None)
    check("_reject_cron_percent accepts a %-free path",
          _reject_cron_percent("/tmp/x/epic-state.json", "--state").endswith("epic-state.json"))
    expect_raises("_reject_cron_percent rejects a path with %",
                  _reject_cron_percent, "/tmp/we%rd.json", "--state")
    check("_validate_shell_single_quoted accepts a normal repo path",
          _validate_shell_single_quoted("/Users/x/repo", "repo root") == "/Users/x/repo")
    for bad in ["has'quote", "has`tick", "has$var"]:
        expect_raises("_validate_shell_single_quoted rejects %r" % (bad,),
                      _validate_shell_single_quoted, bad, "repo root")

    check("_normalize_os: macos passthrough", _normalize_os("macos") == "macos")
    check("_normalize_os: linux passthrough", _normalize_os("linux") == "linux")
    expect_raises("_normalize_os rejects garbage", _normalize_os, "windows")

    check("resolve_claude returns absolute for an override",
          os.path.isabs(resolve_claude(claude_bin="rel/claude")))
    check("resolve_claude honors COMPOUND_V_HEADLESS_CLAUDE_BIN env",
          resolve_claude(env={"COMPOUND_V_HEADLESS_CLAUDE_BIN": "/x/y/claude"}) == "/x/y/claude")
    check("ALLOWED_TOOLS is a non-empty allowlist", bool(ALLOWED_TOOLS.strip()))
    check("ALLOWED_TOOLS names dontAsk-compatible read tools", "Read" in ALLOWED_TOOLS)
    # The SAFE SUBSET covers the CLAIM + liveness + read/report the resume can do headless.
    check("ALLOWED_TOOLS covers the epic-state --claim-resume call (STEP 2)",
          "Bash(python3 scripts/compound-v-epic-state.py:*)" in ALLOWED_TOOLS)
    check("ALLOWED_TOOLS covers the epic-watch liveness read",
          "Bash(python3 scripts/compound-v-epic-watch.py:*)" in ALLOWED_TOOLS)
    check("ALLOWED_TOOLS covers `python3 -c` (STEP 1 computes --now)",
          "Bash(python3 -c:*)" in ALLOWED_TOOLS)
    check("ALLOWED_TOOLS covers read-only git inspection",
          "Bash(git status:*)" in ALLOWED_TOOLS and "Bash(git log:*)" in ALLOWED_TOOLS)
    # HONEST BOUNDARY: the DEFAULT allowlist must NOT contain the build/commit/re-arm tools --
    # those belong to the resume prompt's Branch A (/v:epic -> Task + git commit) and Branch C
    # (scheduled-tasks self-disarm), and are withheld unless the user opts in via --allow-build.
    check("DEFAULT ALLOWED_TOOLS does NOT grant Task (Branch A subagent spawn)",
          "Task" not in ALLOWED_TOOLS)
    check("DEFAULT ALLOWED_TOOLS does NOT grant git add (Branch A commit)",
          "git add" not in ALLOWED_TOOLS)
    check("DEFAULT ALLOWED_TOOLS does NOT grant git commit (Branch A commit)",
          "git commit" not in ALLOWED_TOOLS)
    check("DEFAULT ALLOWED_TOOLS does NOT grant scheduled-tasks (Branch C disarm)",
          "mcp__scheduled-tasks" not in ALLOWED_TOOLS)
    # BUILD_TOOLS / allowed_tools_for: the wider opt-in set, and never a bypass.
    check("BUILD_TOOLS grants Task", "Task" in BUILD_TOOLS)
    check("BUILD_TOOLS grants git add + git commit",
          "Bash(git add:*)" in BUILD_TOOLS and "Bash(git commit:*)" in BUILD_TOOLS)
    check("BUILD_TOOLS grants scheduled-tasks MCP", "mcp__scheduled-tasks__*" in BUILD_TOOLS)
    for _bad in ("--dangerously", "--yolo", "Bash(*)"):
        check("BUILD_TOOLS never contains a bypass token %r" % (_bad,), _bad not in BUILD_TOOLS)
    check("allowed_tools_for() default == the safe subset",
          allowed_tools_for() == ALLOWED_TOOLS and allowed_tools_for(False) == ALLOWED_TOOLS)
    check("allowed_tools_for(True) == safe subset + BUILD_TOOLS",
          allowed_tools_for(True) == ALLOWED_TOOLS + "," + BUILD_TOOLS)
    _abt = allowed_tools_for(True)
    for _bad in ("--dangerously-skip-permissions", "--yolo", "Bash(*)"):
        check("allowed_tools_for(True) never contains %r" % (_bad,), _bad not in _abt)

    # ---- REQ 1: present-only -- no launchctl/crontab subprocess in the code path -------
    # Robust structural proof via AST (ignores string-literal contents, so these very
    # assertion strings -- which name launchctl/crontab/subprocess.run -- don't false-fail):
    # there is EXACTLY ONE subprocess.* call in the whole file, it is subprocess.run, and it
    # lives in _capture_resume_prompt, whose source names epic-watch emit-prompt but NEVER
    # launchctl/crontab.
    import ast
    import inspect
    with open(os.path.abspath(__file__), "r", encoding="utf-8") as fh:
        src = fh.read()
    subprocess_attrs = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call):
            fn = node.func
            if (isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name)
                    and fn.value.id == "subprocess"):
                subprocess_attrs.append(fn.attr)
    check("REQ1: exactly one subprocess.* call in the file, and it is subprocess.run",
          subprocess_attrs == ["run"])
    cap_src = inspect.getsource(_capture_resume_prompt)
    check("REQ1: the sole subprocess captures epic-watch emit-prompt",
          "emit-prompt" in cap_src and "compound-v-epic-watch.py" in EPIC_WATCH_SCRIPT)
    check("REQ1: the subprocess helper never names launchctl/crontab (never shells to them)",
          "launchctl" not in cap_src and "crontab" not in cap_src)

    # ---- macOS emit --------------------------------------------------------------------
    mac_art, mac_err = _emit("macos")
    check("macos emit succeeds", mac_art is not None and mac_err is None)
    if mac_art is not None:
        # (a) valid XML: the embedded plist round-trips through plistlib.
        start = mac_art.index("<?xml")
        end = mac_art.index("----- END plist -----")
        plist_xml = mac_art[start:end]
        parsed = None
        try:
            parsed = plistlib.loads(plist_xml.encode("utf-8"))
        except Exception:
            parsed = None
        check("REQ3(a): emitted plist is valid XML (round-trips via plistlib)", parsed is not None)
        if parsed is not None:
            check("REQ3: Label is dev.compound-v.watch.<epic-id>",
                  parsed.get("Label") == "dev.compound-v.watch.epic-alpha")
            pa = parsed.get("ProgramArguments") or []
            check("REQ2/3: ProgramArguments[0] is the ABSOLUTE claude path",
                  bool(pa) and pa[0] == fake_claude and os.path.isabs(pa[0]))
            check("REQ2: ProgramArguments carries --permission-mode dontAsk",
                  "--permission-mode" in pa and "dontAsk" in pa)
            check("REQ2: ProgramArguments carries --allowedTools + the non-empty allowlist",
                  "--allowedTools" in pa and ALLOWED_TOOLS in pa)
            check("REQ3(b): the captured resume prompt is embedded (contains /v:epic + epic id)",
                  any("/v:epic epic-alpha" in x for x in pa))
            check("REQ3: StartCalendarInterval is two Minute-only dicts (17/47, no Hour)",
                  parsed.get("StartCalendarInterval") == [{"Minute": 17}, {"Minute": 47}])
            check("H4.1: WorkingDirectory is an ABSOLUTE repo path (cwd trap pre-empted)",
                  bool(parsed.get("WorkingDirectory"))
                  and os.path.isabs(parsed.get("WorkingDirectory")))
            check("H4.1: WorkingDirectory resolves to a .git-bearing root",
                  os.path.exists(os.path.join(parsed.get("WorkingDirectory") or "", ".git")))
            check("REQ3(e): StandardInPath is /dev/null (no-stdin trap pre-empted)",
                  parsed.get("StandardInPath") == "/dev/null")
            check("REQ3: StandardOutPath + StandardErrorPath set to a log path",
                  bool(parsed.get("StandardOutPath")) and bool(parsed.get("StandardErrorPath")))
            check("REQ3: RunAtLoad is False (scheduled only)", parsed.get("RunAtLoad") is False)
        # (c) no bypass flag in the emitted COMMAND (the plist XML incl. ProgramArguments +
        # embedded prompt). NB: the runbook's DO-NOT block deliberately NAMES these flags to
        # warn against them, so this negative assertion is scoped to plist_xml, not mac_art.
        for flag in _BANNED_FLAGS:
            check("REQ2/3(c): the macOS plist command contains NO %s" % (flag,),
                  flag not in plist_xml)
        # (f) LaunchAgents target + bootstrap/bootout install as USER steps.
        check("REQ3(f): macOS runbook targets ~/Library/LaunchAgents",
              "Library/LaunchAgents" in mac_art)
        check("REQ3(f): macOS runbook prints `launchctl bootstrap gui/$(id -u)` (primary)",
              "launchctl bootstrap gui/$(id -u)" in mac_art)
        check("REQ3(f): macOS runbook prints `launchctl bootout gui/$(id -u)/` teardown",
              "launchctl bootout gui/$(id -u)/dev.compound-v.watch.epic-alpha" in mac_art)
        check("REQ3: legacy load/unload noted as a fallback",
              "launchctl load" in mac_art and "launchctl unload" in mac_art)
        # REQ5: honesty + DO-NOT blocks present.
        check("REQ5: macOS runbook has the wake/coalesce honesty line",
              "coalesce" in mac_art.lower() and "wake" in mac_art.lower())
        check("REQ5: macOS runbook notes powered-off + FileVault dead zones",
              "powered off" in mac_art.lower() and "filevault" in mac_art.lower())
        check("REQ5: macOS runbook mentions max_resume_count still bounds fires",
              "max_resume_count" in mac_art)
        check("REQ5: macOS runbook carries the prominent DO-NOT-bypass block",
              "DO NOT" in mac_art and "deleted a repository" in mac_art
              and "--dangerously-skip-permissions" in mac_art)

    # ---- Linux emit --------------------------------------------------------------------
    lin_art, lin_err = _emit("linux")
    check("linux emit succeeds", lin_art is not None and lin_err is None)
    if lin_art is not None:
        # Isolate just the crontab COMMAND line (the runbook below it deliberately names the
        # banned flags in its DO-NOT block, so the negative assertion must not scan it).
        cron_only = lin_art.split("----- BEGIN crontab line -----\n", 1)[1]
        cron_only = cron_only.split("\n----- END crontab line -----", 1)[0]
        check("REQ4: crontab line uses the :17/:47 twin cadence",
              "17,47 * * * *" in lin_art)
        # H4.1: the command cds into the repo root BEFORE running claude, so the resume
        # prompt's relative scripts/... calls resolve under cron's unrelated cwd.
        _repo = resolve_repo_root("/repo/exec/epic-alpha/epic-state.json")
        check("H4.1: crontab command cds into the absolute repo root before claude",
              _repo is not None and ("cd '%s' && " % _repo) in cron_only
              and cron_only.index("cd '%s'" % _repo) < cron_only.index(fake_claude))
        check("REQ4: crontab line uses the ABSOLUTE claude path",
              ("'%s'" % fake_claude) in lin_art)
        check("REQ4: crontab line redirects stdin from /dev/null",
              "< /dev/null" in lin_art)
        check("REQ4: crontab line carries --permission-mode dontAsk",
              "--permission-mode dontAsk" in lin_art)
        check("REQ4: crontab line carries --allowedTools + the non-empty allowlist",
              "--allowedTools" in lin_art and ALLOWED_TOOLS in lin_art)
        check("REQ4(b): crontab line names the epic id (via the emit-prompt substitution)",
              "--epic-id 'epic-alpha'" in lin_art)
        check("REQ4: crontab line regenerates the prompt via emit-prompt command-substitution",
              "emit-prompt" in lin_art and "$(" in lin_art)
        for flag in _BANNED_FLAGS:
            check("REQ4(c): the crontab command line contains NO %s" % (flag,),
                  flag not in cron_only)
        check("REQ5: Linux runbook has the wake/coalesce honesty line",
              "coalesce" in lin_art.lower())
        check("REQ5: Linux runbook carries the prominent DO-NOT-bypass block",
              "DO NOT" in lin_art and "deleted a repository" in lin_art)

    # ---- BLOCKER FIX: honest boundary (default = safe subset; --allow-build widens) -----
    # Helper: extract just the emitted COMMAND (not the runbook, which deliberately names the
    # wider tools + banned flags in its BOUNDARY/DO-NOT blocks -- so a negative assert on the
    # command must never scan the runbook prose).
    def _command_of(artifact, os_name):
        if os_name == "macos":
            return artifact[artifact.index("<?xml"):artifact.index("----- END plist -----")]
        c = artifact.split("----- BEGIN crontab line -----\n", 1)[1]
        return c.split("\n----- END crontab line -----", 1)[0]

    def _runbook_of(artifact, os_name):
        marker = "----- END plist -----" if os_name == "macos" else "----- END crontab line -----"
        return artifact.split(marker, 1)[1]

    _WIDER = ("Task", "Bash(git add:*)", "Bash(git commit:*)", "mcp__scheduled-tasks__*")
    for _os in ("macos", "linux"):
        # (1) DEFAULT emit -- command carries the safe subset and NONE of the wider patterns.
        _def_art, _def_err = _emit(_os)
        check("boundary: %s default emit succeeds" % _os,
              _def_art is not None and _def_err is None)
        if _def_art is not None:
            _cmd = _command_of(_def_art, _os)
            check("boundary: %s default command carries the safe-subset allowlist" % _os,
                  ALLOWED_TOOLS in _cmd)
            for _w in _WIDER:
                check("boundary: %s default command does NOT contain %r" % (_os, _w),
                      _w not in _cmd)
            # (4) prior invariant: still no bypass token in the default command.
            for _flag in _BANNED_FLAGS:
                check("boundary: %s default command still contains NO %s" % (_os, _flag),
                      _flag not in _cmd)
            # (3) runbook states the boundary + the EXACT widening list.
            _rb = _runbook_of(_def_art, _os)
            check("boundary: %s runbook has the BOUNDARY section header" % _os, "BOUNDARY" in _rb)
            check("boundary: %s runbook says it claims + reports then STOPS" % _os,
                  "claims + reports" in _rb and "STOPS" in _rb)
            check("boundary: %s runbook says widen at your own risk" % _os,
                  "Widen at your own risk" in _rb)
            check("boundary: %s runbook names the EXACT widening list" % _os,
                  WIDEN_LIST_TEXT in _rb)
            # preamble (stated loudly ABOVE the artifact too, not only in the runbook).
            check("boundary: %s default preamble states the claim+report+stop boundary" % _os,
                  "then STOPS" in _def_art.split("----- BEGIN", 1)[0]
                  and WIDEN_LIST_TEXT in _def_art.split("----- BEGIN", 1)[0])

        # (2) --allow-build emit -- command DOES carry the wider patterns, still no bypass.
        _ab_art, _ab_err = _emit(_os, allow_build=True)
        check("boundary: %s --allow-build emit succeeds" % _os,
              _ab_art is not None and _ab_err is None)
        if _ab_art is not None:
            _cmd_ab = _command_of(_ab_art, _os)
            check("boundary: %s --allow-build command carries the safe subset + BUILD_TOOLS" % _os,
                  allowed_tools_for(True) in _cmd_ab)
            for _w in _WIDER:
                check("boundary: %s --allow-build command DOES contain %r" % (_os, _w),
                      _w in _cmd_ab)
            for _flag in list(_BANNED_FLAGS) + ["--yolo", "Bash(*)"]:
                check("boundary: %s --allow-build command STILL contains NO %s" % (_os, _flag),
                      _flag not in _cmd_ab)
            check("boundary: %s --allow-build preamble warns of unattended autonomy" % _os,
                  "--allow-build" in _ab_art.split("----- BEGIN", 1)[0]
                  and "UNATTENDED" in _ab_art.split("----- BEGIN", 1)[0])

    # ---- REQ: unresolved claude fails the emit with a clear message, nonzero -----------
    art_noclaude, err_noclaude = emit("epic-x", "/tmp/s.json", "macos",
                                      claude_bin="", env={"PATH": ""})
    check("REQ3: emit FAILS (clean message, no artifact) when claude is unresolved",
          art_noclaude is None and err_noclaude is not None and "claude" in err_noclaude)

    # ---- REQ6: malformed --interval-min is a clean refusal, not a traceback ------------
    art_bad_iv, err_bad_iv = _emit("macos", interval_min=0)
    check("REQ6: --interval-min <= 0 is a clean refusal", art_bad_iv is None and err_bad_iv is not None)
    art_ok_iv, _ = _emit("macos", interval_min=30)
    check("REQ6: a valid --interval-min still emits", art_ok_iv is not None)
    check("REQ6: --interval-min never changes the macOS Minute cadence",
          art_ok_iv is not None and "<integer>17</integer>" in art_ok_iv
          and "<integer>47</integer>" in art_ok_iv)

    # ---- malformed epic-id / shell-unsafe state are clean refusals ---------------------
    art_bad_id, err_bad_id = emit("bad id\nnl", "/tmp/s.json", "macos", claude_bin=fake_claude)
    check("malformed --epic-id is a clean refusal", art_bad_id is None and err_bad_id is not None)
    art_bad_state, err_bad_state = emit("epic-ok", "/tmp/wei'rd.json", "linux",
                                        claude_bin=fake_claude)
    check("shell-unsafe --state is a clean refusal on linux",
          art_bad_state is None and err_bad_state is not None)
    # M6: a `%` in the --state path corrupts a cron line -> clean refusal on linux.
    art_pct, err_pct = emit("epic-ok", "/tmp/we%rd/epic-state.json", "linux",
                            claude_bin=fake_claude)
    check("M6: `%` in --state is cleanly refused on linux (never a corrupt cron line)",
          art_pct is None and err_pct is not None and "%" in err_pct)
    # ...and the SAME `%` path is harmless on macOS (the plist is unaffected by cron's `%`).
    art_pct_mac, _ = emit("epic-ok", "/tmp/we%rd/epic-state.json", "macos",
                          claude_bin=fake_claude)
    check("M6: `%` in --state still emits fine on macOS (plist unaffected)",
          art_pct_mac is not None)

    # ---- CLI wiring --------------------------------------------------------------------
    old_env = os.environ.get("COMPOUND_V_HEADLESS_CLAUDE_BIN")
    os.environ["COMPOUND_V_HEADLESS_CLAUDE_BIN"] = fake_claude
    try:
        with tempfile.TemporaryDirectory() as td:
            state_path = os.path.join(td, "epic-state.json")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(["emit", "--epic-id", "epic-cli", "--state", state_path, "--os", "macos"])
            check("CLI emit --os macos exits 0", rc == 0)
            check("CLI emit --os macos prints a plist + runbook",
                  "<?xml" in buf.getvalue() and "launchctl bootstrap" in buf.getvalue())

            buf2 = io.StringIO()
            with contextlib.redirect_stdout(buf2):
                rc2 = main(["emit", "--epic-id", "epic-cli", "--state", state_path, "--os", "linux"])
            check("CLI emit --os linux exits 0", rc2 == 0)
            check("CLI emit --os linux prints a crontab line",
                  "17,47 * * * *" in buf2.getvalue() and "crontab -e" in buf2.getvalue())

            # CLI --allow-build: exits 0, bakes BUILD_TOOLS into the command, warns on stderr.
            buf_ab = io.StringIO()
            err_ab = io.StringIO()
            with contextlib.redirect_stdout(buf_ab), contextlib.redirect_stderr(err_ab):
                rc_ab = main(["emit", "--epic-id", "epic-cli", "--state", state_path,
                              "--os", "macos", "--allow-build"])
            check("CLI emit --allow-build exits 0", rc_ab == 0)
            check("CLI emit --allow-build bakes the wider tools into the plist command",
                  allowed_tools_for(True) in buf_ab.getvalue())
            check("CLI emit --allow-build prints a prominent stderr autonomy warning",
                  "WARNING" in err_ab.getvalue() and "UNATTENDED" in err_ab.getvalue())
            buf_def = io.StringIO()
            err_def = io.StringIO()
            with contextlib.redirect_stdout(buf_def), contextlib.redirect_stderr(err_def):
                main(["emit", "--epic-id", "epic-cli", "--state", state_path, "--os", "macos"])
            check("CLI default emit prints NO autonomy WARNING on stderr",
                  "WARNING" not in err_def.getvalue())
            check("CLI default emit command carries only the safe subset (no Task)",
                  "Task," not in buf_def.getvalue()[
                      buf_def.getvalue().index("<?xml"):
                      buf_def.getvalue().index("----- END plist -----")])

            # error path: unresolved claude via CLI -> nonzero, stderr message
            os.environ.pop("COMPOUND_V_HEADLESS_CLAUDE_BIN", None)
            old_path = os.environ.get("PATH")
            os.environ["PATH"] = td  # a dir with no `claude`
            try:
                buf3 = io.StringIO()
                errbuf = io.StringIO()
                with contextlib.redirect_stdout(buf3), contextlib.redirect_stderr(errbuf):
                    rc3 = main(["emit", "--epic-id", "epic-cli", "--state", state_path, "--os", "macos"])
                check("CLI emit fails nonzero when claude unresolvable", rc3 != 0)
            finally:
                if old_path is None:
                    os.environ.pop("PATH", None)
                else:
                    os.environ["PATH"] = old_path
    finally:
        if old_env is None:
            os.environ.pop("COMPOUND_V_HEADLESS_CLAUDE_BIN", None)
        else:
            os.environ["COMPOUND_V_HEADLESS_CLAUDE_BIN"] = old_env

    print("\n%d failed" % len(fails))
    if fails:
        print("FAILED: " + ", ".join(fails))
        return 1
    print("all self-tests passed")
    return 0


# --------------------------------------------------------------------------- CLI

def build_parser():
    p = argparse.ArgumentParser(
        description="Compound V headless resurrection shim (v2.14 Feature B, present-only)")
    p.add_argument("--selftest", action="store_true", help="run stdlib self-tests and exit")
    sub = p.add_subparsers(dest="cmd")

    sp = sub.add_parser("emit",
                        help="print an OS scheduler artifact + runbook (never installs)")
    sp.add_argument("--epic-id", required=True)
    sp.add_argument("--state", required=True, help="path to epic-state.json")
    sp.add_argument("--interval-min", type=int, default=None,
                    help="accepted for the contract; cadence stays the off-minute :17/:47 twin")
    sp.add_argument("--os", dest="os", choices=["macos", "linux"], default=None,
                    help="target OS (default: auto-detect from sys.platform)")
    sp.add_argument("--allow-build", dest="allow_build", action="store_true",
                    help="ALSO bake the build/commit/re-arm tools (Task, git add, git commit, "
                         "scheduled-tasks) into the allowlist so the headless session can run "
                         "the FULL pipeline UNATTENDED -- an unattended-autonomy opt-in you "
                         "accept. Never adds --dangerously-*/--yolo. Default: safe subset only")
    return p


def main(argv):
    # LANG=C-clean: non-ASCII in stdout/stderr must not crash the process (mirrors the
    # other scripts/*.py in this plugin).
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
    if args.cmd == "emit":
        return cmd_emit(args)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
