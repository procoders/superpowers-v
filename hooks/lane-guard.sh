#!/usr/bin/env bash
# Compound V — PreToolUse lane guard (Feature E, v3.0)
#
# WHAT THIS IS
# ------------
# A native `PreToolUse` DENY that refuses a write outside the acting job's
# `write_allowed` lane BEFORE the bytes land, instead of noticing afterwards.
#
# WHAT THIS IS NOT
# ----------------
# It is NOT a replacement for `scripts/compound-v-scope-check.py`. That script
# is git-derived, sees every path a job actually touched no matter how it was
# touched, and REMAINS THE AUTHORITY: a job whose git verdict is BLOCKED is
# still BLOCKED, and the D1 integration postcondition still decides what enters
# the tree. This hook is DEFENCE IN DEPTH — a floor under that verdict.
#
# The honest reason for the caveat is in `bash_targets()` below: for the `Bash`
# matcher this hook has to INSPECT A SHELL COMMAND STRING, and shell command
# inspection is a parsing problem with unbounded evasions (`eval`, an
# interpreter one-liner, a variable holding the path, a build step, a script
# that writes on the guard's behalf). Every one of those walks straight past
# this hook and straight into the git gate. A deny that can be walked around is
# a supplement, never a replacement — see the spec's Feature E / E2.
#
# WHY IT MATCHES `Bash` AT ALL
# ----------------------------
# The 1D live probe (commit 0982ce0) established that a `Write|Edit`-only
# matcher is decorative: this environment actively nudges agents toward `cat`,
# `sed` and heredocs over the Write tool, and none of those reach a Write|Edit
# matcher. So `Bash` is matched too, on the understanding above.
#
# FAIL-OPEN CONTRACT
# ------------------
# A false deny inside a long autonomous run is far more expensive than a missed
# write the git gate catches anyway. Therefore: ANY uncertainty allows.
#   * unparseable stdin                 -> allow, log
#   * no lane map / job unresolvable    -> allow, log   (the normal case for an
#                                         ordinary human session)
#   * manifest missing or malformed     -> allow, log, AND say so in
#                                         additionalContext (the guard was
#                                         supposed to be active and could not be)
#   * a path this hook cannot resolve   -> allow, log
#   * the interpreter itself crashing   -> allow (the wrapper below discards any
#                                         non-JSON output and exits 0)
# Only a POSITIVELY IDENTIFIED, fully resolved, out-of-lane path denies.
#
# COST
# ----
# PreToolUse hooks share a tight time budget, so every path here is bounded: at
# most 8 run directories are inspected, resolution stops at the first match, and
# the manifest is only parsed AFTER a job has been resolved. Measured on the
# development machine (macOS, /usr/bin/python3 3.9), mean of 10 runs:
#   bare interpreter start        ~54 ms   (the floor -- nothing can beat it)
#   unresolved job (human session) ~112 ms  (no manifest parse)
#   full deny path                 ~152 ms
# A result cache was considered and rejected: it would save ~40 ms and buy a
# cache-invalidation bug in the one component whose failure mode is a false deny.
#
# CARVE-OUT: EXTERNAL WORKERS
# ---------------------------
# A command invoking `scripts/compound-v-run-*-worker.sh` is NEVER denied
# (spec D5.2). What that OS process writes happens in its own worktree, in a
# separate process, outside any hook this session controls; it is covered by the
# worker script's own scope-gate call plus the D1 integration postcondition.
# Denying it here would only break the second family, never police it.
#
# REGISTRATION
# ------------
# This job does NOT register the hook — `hooks/hooks.json` belongs to task-16.
# The intended registration is a `PreToolUse` entry with matcher
# `Write|Edit|MultiEdit|NotebookEdit|Bash`.
#
# LANE MAP CONTRACT (how a tool call becomes a job id)
# ----------------------------------------------------
# Resolution order, first hit wins:
#   1. $CV_LANE_MAP           — explicit path to a lane-map JSON (tests, and any
#                               dispatcher that wants to be explicit)
#   2. <project>/docs/superpowers/execution/<run-id>/lane-map.json
#   3. <project>/docs/superpowers/execution/<run-id>/state.json, whose
#      jobs.<id> may carry "agent_id" (or "agent_ids": [...]) and "worktree"
# Lane-map shape:
#   {"run_id": "...", "manifest": "<path, default <rundir>/manifest.yaml>",
#    "agents":    {"<agent_id>": "<job-id>"},
#    "worktrees": {"<abs worktree path>": "<job-id>"}}
# Within a run dir, `agent_id` is tried first (the probe proved the payload
# carries it); the `cwd`->worktree map is the fallback, because the probe also
# showed `cwd` IS the agent's worktree (`.claude/worktrees/<runId>-<n>`).
#
# The glob matcher is IMPORTED from scripts/compound-v-scope-check.py, never
# reimplemented: two glob engines that disagree is a bug factory, and that one
# has reproduced-exploit selftests behind it.
#
# ENV
#   CV_LANE_MAP        explicit lane-map JSON (overrides discovery)
#   CV_PROJECT_DIR     project root override (else CLAUDE_PROJECT_DIR, else
#                      derived from the payload cwd)
#   CV_SCOPE_CHECK     path to compound-v-scope-check.py
#   CV_LANE_GUARD_LOG  log file (default $TMPDIR/compound-v-lane-guard.log).
#                      Defaults OUTSIDE the repo on purpose: a guard that logs
#                      into the worktree would create the very untracked file
#                      the scope gate then blocks the job for.
#   CV_PYTHON          interpreter override

# No `set -e`: this hook must never fail closed.
set -uo pipefail

HOOK_DIR="$(cd "$(dirname "$0")" && pwd -P 2>/dev/null || echo .)"
: "${CV_SCOPE_CHECK:=${CLAUDE_PLUGIN_ROOT:-$HOOK_DIR/..}/scripts/compound-v-scope-check.py}"
: "${CV_VALIDATE_MANIFEST:=${CLAUDE_PLUGIN_ROOT:-$HOOK_DIR/..}/scripts/compound-v-validate-manifest.py}"
export CV_SCOPE_CHECK CV_VALIDATE_MANIFEST

# Importing the matcher must not leave __pycache__/*.pyc next to the scripts:
# those are untracked files the scope gate unions into the job's changed set,
# i.e. the guard would BLOCK the job it is guarding.
export PYTHONDONTWRITEBYTECODE=1

PY="${CV_PYTHON:-}"
if [ -z "$PY" ]; then
  PY="$(command -v python3 2>/dev/null || true)"
  [ -n "$PY" ] || PY=/usr/bin/python3
fi

# Read the Python source into a variable WITHOUT a $(...) command substitution:
# bash parses the inside of $( ) even around a quoted heredoc, and a bare
# backtick in the Python source is then a syntax error in this file.
# `read -d ''` returns non-zero at EOF by design; the variable is still set.
IFS= read -r -d '' LANE_GUARD_PY <<'PYEOF' || true
import json
import os
import re
import shlex
import sys

LOG = (os.environ.get("CV_LANE_GUARD_LOG")
       or os.path.join(os.environ.get("TMPDIR", "/tmp"),
                       "compound-v-lane-guard.log"))


def log(msg):
    """Best effort. A logging failure must never influence the decision."""
    try:
        with open(LOG, "a") as fh:
            fh.write(str(msg).replace("\n", " ")[:2000] + "\n")
    except Exception:
        pass


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}))


def open_notice(reason):
    """Fail open, and SAY SO. Used only once a job was resolved and the guard
    was therefore supposed to be active -- an unresolved agent is the ordinary
    case (a human session) and stays silent."""
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "additionalContext": (
            "Compound V lane-guard FAILED OPEN: " + reason
            + " This write was NOT checked against the job's write_allowed. "
              "The git-derived scope gate (scripts/compound-v-scope-check.py) "
              "is unaffected and remains the authority."),
    }}))


# --------------------------------------------------------------------------- #
# path helpers
# --------------------------------------------------------------------------- #
def _rel_under(path, root):
    """Repo-relative path if `path` is inside `root`, else None.

    Compared both lexically and through realpath, because on macOS a worktree
    handed to us as /tmp/... is really /private/tmp/... and a lexical-only
    comparison would silently place every target OUTSIDE the root (= allow
    everything)."""
    if not root:
        return None
    pairs = [(os.path.normpath(path), os.path.normpath(root))]
    try:
        pairs.append((os.path.realpath(path), os.path.realpath(root)))
    except Exception:
        pass
    for p, r in pairs:
        r = r.rstrip(os.sep)
        if p == r:
            return "."
        if p.startswith(r + os.sep):
            return p[len(r) + 1:]
    return None


UNRESOLVABLE = ("$", "`", "\n")


def _resolvable(token):
    return token and not any(ch in token for ch in UNRESOLVABLE)


# --------------------------------------------------------------------------- #
# lane resolution
# --------------------------------------------------------------------------- #
def project_roots(cwd):
    out = []

    def add(p):
        if p:
            p = os.path.normpath(p)
            if p not in out:
                out.append(p)

    add(os.environ.get("CV_PROJECT_DIR"))
    add(os.environ.get("CLAUDE_PROJECT_DIR"))
    cur = os.path.normpath(cwd or ".")
    # The probe showed workflow worktrees live at <project>/.claude/worktrees/<id>,
    # so the MAIN checkout (which holds the live state.json) is derivable.
    m = re.match(r"^(.*)/\.claude/worktrees/[^/]+", cur)
    if m:
        add(m.group(1))
    for _ in range(12):  # bounded walk
        if os.path.isdir(os.path.join(cur, "docs", "superpowers", "execution")):
            add(cur)
            break
        nxt = os.path.dirname(cur)
        if nxt == cur:
            break
        cur = nxt
    return out


def _mtime(p):
    try:
        return os.path.getmtime(p)
    except OSError:
        return 0.0


def map_files(cwd, limit=8):
    """Lane-map candidates, newest run first. Bounded: PreToolUse hooks share a
    tight time budget, so this never walks more than `limit` run dirs."""
    explicit = os.environ.get("CV_LANE_MAP")
    if explicit:
        return [explicit]
    found = []
    for root in project_roots(cwd):
        base = os.path.join(root, "docs", "superpowers", "execution")
        try:
            names = os.listdir(base)
        except OSError:
            continue
        dirs = [os.path.join(base, n) for n in names]
        dirs = [d for d in dirs if os.path.isdir(d)]
        dirs.sort(key=_mtime, reverse=True)
        for d in dirs[:limit]:
            for cand in ("lane-map.json", "state.json"):
                p = os.path.join(d, cand)
                if os.path.isfile(p):
                    found.append(p)
                    break
        if found:
            break
    return found[:limit]


def read_map(path):
    """-> (agents{aid: job}, worktrees{path: job}, manifest_path) or None."""
    try:
        with open(path, "r") as fh:
            data = json.load(fh)
    except Exception as exc:
        log("lane-map unreadable %s: %s" % (path, exc))
        return None
    if not isinstance(data, dict):
        return None
    rundir = os.path.dirname(path)
    manifest = data.get("manifest") or os.path.join(rundir, "manifest.yaml")
    if not os.path.isabs(manifest):
        manifest = os.path.join(rundir, manifest)
    agents, worktrees = {}, {}
    for aid, job in (data.get("agents") or {}).items():
        if isinstance(job, str):
            agents[aid] = job
    for wt, job in (data.get("worktrees") or {}).items():
        if isinstance(job, str):
            worktrees[wt] = job
    # state.json fallback shape: jobs.<id>.{agent_id|agent_ids, worktree}
    jobs = data.get("jobs")
    if isinstance(jobs, dict):
        for job_id, rec in jobs.items():
            if not isinstance(rec, dict):
                continue
            aid = rec.get("agent_id")
            if isinstance(aid, str) and aid:
                agents.setdefault(aid, job_id)
            for aid in (rec.get("agent_ids") or []):
                if isinstance(aid, str) and aid:
                    agents.setdefault(aid, job_id)
            wt = rec.get("worktree")
            if isinstance(wt, str) and wt:
                worktrees.setdefault(wt, job_id)
    return agents, worktrees, manifest


def resolve_job(agent_id, cwd):
    """-> (job_id, manifest_path, root, project_root, how) or None."""
    for path in map_files(cwd):
        parsed = read_map(path)
        if not parsed:
            continue
        agents, worktrees, manifest = parsed
        # <project>/docs/superpowers/execution/<run>/<file>
        proj = os.path.normpath(os.path.join(os.path.dirname(path),
                                             "..", "..", "..", ".."))
        if agent_id and agent_id in agents:
            job = agents[agent_id]
            root = None
            for wt, j in worktrees.items():
                if j == job:
                    root = wt
                    break
            return job, manifest, root or cwd, proj, "agent_id"
        for wt, job in worktrees.items():
            if cwd and _rel_under(cwd, wt) is not None:
                return job, manifest, wt, proj, "cwd->worktree"
    return None


def write_allowed_for(manifest_path, job_id):
    """Read the job's lane out of the manifest. Reuses the repo's own YAML
    loader (scripts/compound-v-validate-manifest.py) rather than a third
    parser."""
    import importlib.util
    src = os.environ.get("CV_VALIDATE_MANIFEST")
    if not src or not os.path.isfile(src):
        raise RuntimeError("validate-manifest loader not found")
    spec = importlib.util.spec_from_file_location("_cv_vm", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with open(manifest_path, "r") as fh:
        data = mod.load_yaml(fh.read())
    jobs = (data or {}).get("jobs") or []
    if isinstance(jobs, dict):
        jobs = [dict(v, id=k) for k, v in jobs.items() if isinstance(v, dict)]
    for job in jobs:
        if isinstance(job, dict) and job.get("id") == job_id:
            allowed = job.get("write_allowed") or []
            return [g for g in allowed if isinstance(g, str)]
    raise RuntimeError("job %r not in %s" % (job_id, manifest_path))


def load_matcher():
    import importlib.util
    src = os.environ.get("CV_SCOPE_CHECK")
    if not src or not os.path.isfile(src):
        raise RuntimeError("scope-check matcher not found")
    spec = importlib.util.spec_from_file_location("_cv_scope", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.is_allowed


# --------------------------------------------------------------------------- #
# Bash command inspection
#
# READ THIS BEFORE TRUSTING IT. This is a heuristic extractor of paths a command
# would WRITE. It is deliberately conservative in BOTH directions:
#   * it skips anything it cannot resolve (a `$var`, a command substitution, a
#     relative path after a `cd`) rather than guessing -- guessing produces
#     false denies, and a false deny stalls an autonomous run;
#   * everything it does not model at all is simply invisible to it.
#
# What it CANNOT see (non-exhaustive, and that is the point):
#   * interpreters: python3 -c / node -e / perl -e / awk / ruby writing a file
#   * eval, base64 | sh, a script invoked by path that writes on its own
#   * a path held in a variable, or produced by command substitution
#   * build/format tooling: make, npm run build, prettier --write, go generate
#   * git subcommands that rewrite the tree without naming paths
#     (checkout <branch>, restore, apply, clean, stash, reset --hard)
#   * relative paths in a segment that follows a `cd` (skipped on purpose)
#   * an in-lane path that is a symlink pointing out of lane
#   * anything a background/long-running process writes after the call returns
# All of the above are seen by the git-derived gate afterwards. That is exactly
# why the git gate keeps the authority.
# --------------------------------------------------------------------------- #
WORKER_RE = re.compile(r"compound-v-run-[A-Za-z0-9_.-]+-worker\.sh")
SEGMENT_RE = re.compile(r"\|\||&&|;|\||\n|&")
REDIR_WORDS = (">", ">>", ">|", "&>", "&>>", "1>", "1>>", "2>", "2>>")
REDIR_ATTACHED = re.compile(r"^(?:[0-9]*|&)>>?\|?(?P<t>.+)$")
CD_LIKE = ("cd", "pushd", "popd", "chdir")
WRAPPERS = ("env", "sudo", "command", "nohup", "time", "exec", "builtin")
# all non-flag args are write targets
ALL_ARGS = ("rm", "rmdir", "unlink", "shred", "touch", "tee", "mv", "truncate",
            "patch")
# only the LAST non-flag arg is the destination
DEST_LAST = ("cp", "install", "rsync", "ln")
# In-place editors REQUIRE the file to already exist -- if it does not, no write
# happens and allowing is correct. That fact resolves the otherwise unparseable
# "is this token the script, the -i suffix, or the file?" ambiguity: keep only
# the non-flag args that name something on disk.
EXISTING_ONLY = ("sed", "perl", "ruby", "patch")
# flags that consume the following token (kept small on purpose: a value
# mistaken for a path is a false deny)
VALUE_FLAGS = {
    "truncate": ("-s", "--size", "-r", "--reference"),
    "install": ("-m", "--mode", "-o", "--owner", "-g", "--group", "-t",
                "--target-directory"),
    "cp": ("-t", "--target-directory", "-S", "--suffix"),
    "mv": ("-t", "--target-directory", "-S", "--suffix"),
    "rsync": ("-e", "--rsh", "--exclude", "--include", "--files-from"),
    "tee": ("-p",),
    # NOTE: -i / --in-place is deliberately ABSENT. BSD sed spells it
    # `-i '' <script> <file>` and GNU sed `-i <script> <file>`; treating -i as
    # value-taking makes the GNU form swallow the script and lose the file, a
    # false ALLOW on exactly the case AC-20 names. Both forms are disambiguated
    # by the existence filter instead (see EXISTING_ONLY).
    "sed": ("-e", "--expression", "-f", "--file", "-l", "--line-length"),
    "patch": ("-p", "--strip", "-d", "--directory", "-D", "-F", "-r", "-z"),
}


def _tokens(segment):
    try:
        lx = shlex.shlex(segment, posix=True)
        lx.whitespace_split = True
        return list(lx)
    except ValueError:
        return segment.split()


def _nonflag(args, cmd):
    """Non-flag arguments, honouring `--` and a small value-flag table."""
    out = []
    value_flags = VALUE_FLAGS.get(cmd, ())
    skip_next = False
    end_of_flags = False
    for tok in args:
        if skip_next:
            skip_next = False
            continue
        if not end_of_flags:
            if tok == "--":
                end_of_flags = True
                continue
            if tok.startswith("-") and len(tok) > 1:
                if tok in value_flags:
                    skip_next = True
                continue
        out.append(tok)
    return out


def bash_targets(cmd_string, cwd):
    """-> (targets, saw_cd). `saw_cd` means relative paths from that point on
    are unresolvable, so the caller must only evaluate absolute ones."""

    def existing(tokens):
        keep = []
        for t in tokens:
            if not _resolvable(t):
                continue
            p = t if os.path.isabs(t) else os.path.join(cwd or ".", t)
            try:
                if os.path.exists(p):
                    keep.append(t)
            except Exception:
                pass
        return keep

    targets = []
    saw_cd = False
    for segment in SEGMENT_RE.split(cmd_string):
        segment = segment.strip()
        if not segment:
            continue
        toks = _tokens(segment)
        words = []
        i = 0
        while i < len(toks):
            tok = toks[i]
            if tok in REDIR_WORDS:
                if i + 1 < len(toks) and not toks[i + 1].startswith("&"):
                    targets.append((toks[i + 1], saw_cd))
                i += 2
                continue
            if tok.startswith("<"):
                # `< file`, `<<EOF`, `<<<word` -- reads, and the heredoc
                # delimiter must not be mistaken for a path.
                i += 2 if tok in ("<", "<<", "<<-", "<<<") else 1
                continue
            m = REDIR_ATTACHED.match(tok)
            if m:
                t = m.group("t")
                if not t.startswith("&"):
                    targets.append((t, saw_cd))
                i += 1
                continue
            words.append(tok)
            i += 1
        # command word: skip VAR=val assignments and thin wrappers
        idx = 0
        while idx < len(words) and (
                re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[idx])
                or os.path.basename(words[idx]) in WRAPPERS):
            idx += 1
        if idx >= len(words):
            continue
        cmd = os.path.basename(words[idx])
        args = words[idx + 1:]
        if cmd in CD_LIKE:
            saw_cd = True
            continue
        if cmd == "dd":
            for a in args:
                if a.startswith("of="):
                    targets.append((a[3:], saw_cd))
            continue
        if cmd in ("sed", "perl", "ruby"):
            # Only the in-place forms write. Without -i these are filters and
            # any write is a redirection, which the redirection scan above
            # already caught.
            if not any(a == "-i" or a.startswith("-i") or a == "--in-place"
                       or a.startswith("--in-place") for a in args):
                continue
            targets.extend((f, saw_cd)
                           for f in existing(_nonflag(args, cmd)))
            continue
        if cmd == "git":
            sub = args[0] if args else ""
            rest = args[1:]
            if sub in ("mv", "rm"):
                targets.extend((f, saw_cd) for f in _nonflag(rest, "git"))
            elif "--" in rest:
                # `git checkout -- <paths>` / `git restore -- <paths>`: only
                # after `--` is a token unambiguously a path. A bare
                # `git checkout <branch>` is NOT treated as a path (that would
                # deny every branch switch).
                after = rest[rest.index("--") + 1:]
                targets.extend((f, saw_cd) for f in after)
            continue
        if cmd in ALL_ARGS:
            files = _nonflag(args, cmd)
            if cmd in EXISTING_ONLY:
                files = existing(files)
            targets.extend((f, saw_cd) for f in files)
            continue
        if cmd in DEST_LAST:
            files = _nonflag(args, cmd)
            if files:
                targets.append((files[-1], saw_cd))
            continue
    return targets, saw_cd


# --------------------------------------------------------------------------- #
def main():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("payload is not an object")
    except Exception as exc:
        log("ALLOW (malformed input): %s" % exc)
        return 0

    tool = payload.get("tool_name") or ""
    if tool not in ("Write", "Edit", "MultiEdit", "NotebookEdit", "Bash"):
        return 0

    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        log("ALLOW (no tool_input) tool=%s" % tool)
        return 0

    command = tool_input.get("command") or ""
    if tool == "Bash" and WORKER_RE.search(command):
        # D5.2 -- never deny the external family's launcher.
        log("ALLOW (external worker invocation, D5.2): %s" % command[:200])
        return 0

    cwd = payload.get("cwd") or os.getcwd()
    agent_id = payload.get("agent_id") or ""

    resolved = resolve_job(agent_id, cwd)
    if not resolved:
        # The ordinary case for a plain human session. Silent by design: an
        # additionalContext line on every tool call would be pure noise.
        log("ALLOW (job unresolved) tool=%s agent_id=%r cwd=%s"
            % (tool, agent_id, cwd))
        return 0
    job_id, manifest, root, project_root, how = resolved

    try:
        allowed = write_allowed_for(manifest, job_id)
        is_allowed = load_matcher()
    except Exception as exc:
        log("ALLOW (guard degraded) job=%s: %s" % (job_id, exc))
        open_notice("job %s resolved, but its lane could not be read (%s)."
                    % (job_id, exc))
        return 0
    if not allowed:
        log("ALLOW (empty write_allowed) job=%s" % job_id)
        open_notice("job %s has no write_allowed globs to enforce." % job_id)
        return 0

    if tool == "Bash":
        raw_targets, _ = bash_targets(command, cwd)
    else:
        p = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        raw_targets = [(p, False)] if p else []

    if not raw_targets:
        log("ALLOW (no write target identified) job=%s tool=%s" % (job_id, tool))
        return 0

    for target, after_cd in raw_targets:
        if not _resolvable(target):
            log("ALLOW-SKIP (unresolvable token) job=%s target=%r"
                % (job_id, target))
            continue
        if not os.path.isabs(target):
            if after_cd:
                # A `cd` earlier in the command means this hook no longer knows
                # what this relative path resolves to. Guessing here is how a
                # false deny happens, so it skips.
                log("ALLOW-SKIP (relative path after cd) job=%s target=%r"
                    % (job_id, target))
                continue
            target = os.path.join(cwd, target)
        rel = _rel_under(target, root)
        if rel is None:
            other = _rel_under(target, project_root)
            if other is not None and _rel_under(project_root, root) is None:
                deny("Compound V lane guard: job '%s' (%s) tried to write "
                     "'%s', which is in the main checkout but OUTSIDE its own "
                     "worktree %s. A job writes only inside its own tree. "
                     "(Defence in depth; the git-derived scope gate remains "
                     "the authority.)" % (job_id, tool, other, root))
                log("DENY (cross-tree) job=%s target=%s" % (job_id, target))
                return 0
            log("ALLOW-SKIP (outside the gated tree) job=%s target=%s"
                % (job_id, target))
            continue
        if is_allowed(rel, allowed):
            continue
        deny("Compound V lane guard: job '%s' is not allowed to write '%s'. "
             "Its write_allowed lane is: %s. Resolved via %s. Write only "
             "inside the lane; if the change genuinely belongs elsewhere, stop "
             "and report it rather than widening the lane yourself. (This deny "
             "is defence in depth -- the git-derived scope gate "
             "scripts/compound-v-scope-check.py still runs afterwards and "
             "remains the authority.)"
             % (job_id, rel, ", ".join(allowed), how))
        log("DENY job=%s tool=%s target=%s lane=%s"
            % (job_id, tool, rel, allowed))
        return 0

    return 0


try:
    sys.exit(main())
except SystemExit:
    raise
except Exception as _exc:  # absolute last resort: never fail closed
    log("ALLOW (internal error): %r" % (_exc,))
    sys.exit(0)
PYEOF

# The wrapper is the second half of the fail-open contract: if the interpreter
# is missing, crashes, or emits anything that is not a JSON object, the hook
# produces NO decision and exits 0. Only well-formed JSON is ever passed on.
out="$("$PY" -c "$LANE_GUARD_PY" 2>/dev/null)" || out=""
case "$out" in
  '{'*) printf '%s\n' "$out" ;;
  *) : ;;
esac
exit 0
