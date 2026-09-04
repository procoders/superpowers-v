#!/usr/bin/env python3
"""
Compound V usage extractor.

Reads a backend's own structured events log and prints a canonical `usage`
object (the optional field in schemas/job_result.schema.json) to stdout:

  {"input_tokens": int|null, "output_tokens": int|null,
   "backend": str, "measured": bool}

Design contract (v2.12 usage, anti-ruflo charter):

  - MEASURED-ONLY. Token counts come exclusively from the backend's OWN
    structured usage events, using the EXACT field names live-probed in
    docs/superpowers/library-audit/2026-07-13-usage-and-advisor.md. Each
    backend uses a different casing/shape, so normalization is per-backend.
  - FAIL-OPEN, NEVER FABRICATE. If the events log is missing, empty, or
    unparseable — or the backend emits no machine-readable usage at all
    (agy/antigravity, claude Task subagent) — emit measured:false
    with null token counts. A null is honest; a made-up number is not.
  - A usage event contributes to the measured sum ONLY when BOTH required
    token fields are present AND are non-negative JSON INTEGERS. A malformed
    or incomplete usage event (empty `{}`, only one side present, string /
    float / bool / negative value) contributes NOTHING — it is never
    substituted with a zero. If no valid usage event is found, the token
    counts stay null and measured stays false. A genuine well-formed 0 from a
    real event is fine; an empty/absent usage object is NOT a real zero.
  - Non-JSON lines and error/deprecation event items are SKIPPED, never fatal.

Per-backend token sources (field names are exact, from the library audit):

  codex     : JSONL. SUM over every `type=="turn.completed"` line of
              .usage.input_tokens and .usage.output_tokens.
  opencode  : JSONL. SUM over every `type=="step_finish"` line of
              .part.tokens.input and .part.tokens.output.
  cursor    : JSONL. The final `type=="result"` line's
              .usage.inputTokens and .usage.outputTokens.
  agy/antigravity : no machine-readable usage -> measured:false.
  claude    : NO events log exists, so `--events-log` can never measure it.
              Engine C's agents leave subagent TRANSCRIPTS instead; see the
              --workflow-transcript mode below. Without that flag a claude job
              stays honestly unmeasured, exactly as it was before 3.4.17.

--------------------------------------------------------------------------
ENGINE C (v3.4.17): --workflow-transcript
--------------------------------------------------------------------------

Engine C (`compound-v-emit-workflow.py emit` -> `dispatch.workflow.js` -> the
native Workflow tool) runs every job stage as a Claude Code subagent, and each
subagent leaves a JSONL transcript. That transcript is the ONLY machine-readable
token record Engine C produces, which is why every Engine C `results/<job>.json`
shipped with no `usage` field until now.

  usage: compound-v-usage-extract.py --backend claude \
             --workflow-transcript <dir> --run-dir <run-dir> [--write]

OBSERVED LOCATION RULE (verified 2026-09-04 against this repo's own runs):

  ~/.claude/projects/<project-slug>/<session-uuid>/subagents/workflows/<wf-id>/agent-<id>.jsonl

  <project-slug> is the session's absolute cwd with every "/" replaced by "-"
  (so /Users/oleg/Dev/superpowers-v -> -Users-oleg-Dev-superpowers-v).
  Workflow-spawned agents nest one level deeper than plain Task subagents, which
  land directly in `<session-uuid>/subagents/`. `<dir>` may point at any level:
  the scan is RECURSIVE for `agent-*.jsonl`.

LINE FORMAT: one JSON object per line. The first `type=="user"` line carries the
stage prompt; `type=="assistant"` lines carry `message.usage` with the keys
`input_tokens`, `output_tokens`, `cache_read_input_tokens`,
`cache_creation_input_tokens`.

TRANSCRIPT -> JOB, FROM ONE AUTHORITATIVE STAGE COMMAND. A prompt is prose plus
the command the stage must run, and ONLY that command's own arguments identify
the job. Every Engine C stage command carries `--run-dir`, `--job-id` and
`--repo-root`:

  implement : `... register-lane --run-dir <run-dir> --job-id <job> ...`
  gate      : `... gate-receipt --run-dir '<run-dir>' --job-id '<job>' ...`
  record    : `... record       --run-dir '<run-dir>' --job-id '<job>' ...`

A command is recognised by the emitter's path plus one of the emitter's OWN
subcommands (its dispatch table, compound-v-emit-workflow.py:8887-8892), and its
arguments are TOKENIZED with `shlex`, never regex-scanned. Both matter:

  * matching any lowercase word after the path turned prose — "…-emit-workflow.py
    and scripts/compound-v-integration-gate.py…" — into a bogus second command in
    4 of this repo's 833 transcripts;
  * `record` passes the gate's whole JSON verdict as one quoted `--verdict-json`
    value, and that value CONTAINS the text `--run-dir '/somewhere/else'`. A
    regex reads a second run dir; a tokenizer reads one string argument.

A transcript matches iff ALL of these hold:

  * the prompt yields EXACTLY ONE distinct (run-dir, job-id, repo-root) triple
    across its stage commands. A run dir that appears only in PROSE is ignored
    entirely — reading the whole prompt credited a transcript to this run
    because a sentence mentioned it, while the command it actually ran named
    another run.
  * that command's `--run-dir` CANONICALISES to this run's directory —
    `os.path.realpath` of both sides, with a relative value resolved against the
    SAME command's `--repo-root` and otherwise treated as unresolvable. There is
    no basename fallback: `/repo-b/.../run-7` is not `/repo-a/.../run-7`, and a
    moved run is unmeasured rather than plausibly wrong.
  * the command carries EXACTLY ONE `--job-id`, and that id is a job of this
    run. Two different ids, or an id this run does not have, is unmatched —
    never a guess. The prose sentence "Compound V job `x`" is NOT a key:
    hand-written prompts quote that phrase (5 of the 8 matches in this repo's
    history are hand-written), and a sentence is not a stage argument.

The run dir is what disambiguates: job ids like `spec-review-1` repeat across
runs (14 transcripts in this repo's own history carry that id), so a job id
ALONE would silently attribute another run's tokens to this one.

A JOB ID IS A FILENAME. It becomes `<run-dir>/results/<id>.json`, so an id that
is not one plain path segment (`^[A-Za-z0-9][A-Za-z0-9._-]*$`) is refused before
matching and again before writing, and the resolved path must still be exactly
`<results>/<id>.json` after `realpath` — which also refuses a symlinked result
file. Without both gates a manifest carrying `- id: /tmp/victim` made `--write`
clobber a file outside the run directory.

Wave-level stages (`finalize-wave`) name the run but no single `--job-id` — they
carry `--jobs a,b`. Splitting one wave's tokens across its jobs would be an
invention, so they are reported on their own `run_level:` line and never folded
into a job.

DEDUPLICATION IS MANDATORY, SPANS THE WHOLE JOB, AND IS ORDERED BY THE RECORD.
One assistant MESSAGE is written to several JSONL lines as its content blocks
stream in (thinking, then text, then tool_use), and every one of those lines
repeats the SAME cumulative `message.usage`. Summing per LINE therefore
double-counts — and so does totalling each transcript separately and adding the
totals, because a message id identifies a message, not a file. All of a job's
transcripts are merged into one id-keyed map before anything is summed.

WHICH snapshot of an id counts is decided by `(timestamp, apiBlockIndex)` read
off the record, not by the order the filenames happen to sort in: a lexically
later file can hold an OLDER snapshot. Measured on this repo's 833 workflow
transcripts (17049 assistant lines): `timestamp` present on 100%, `apiBlockIndex`
on 84.4%, and for all 6298 multi-line message ids the (timestamp, apiBlockIndex)
order equals the file order — 0 disagreements. When an id's records carry no
usable timestamp the fallback is monotonic: max `output_tokens`, invariant
values for the rest, and if those invariants DISAGREE the id is counted as
malformed rather than guessed at. An assistant record with usage but no
`message.id` is malformed too: without an id there is no way to tell a
re-streamed snapshot from a second message, and counting it can only inflate. Measured on job `load-bearing-row` of run
2026-09-03-glob-parity-one-matcher-r3, per-line sums against per-message sums:
input 98 vs 62 (+58.1%), cache_read 2673132 vs 1767605 (+51.2%),
cache_creation 236634 vs 125639 (+88.3%), output 10320 vs 10202 (+1.2%).
Usage is therefore accumulated per `message.id`, LAST occurrence winning
(output_tokens grows monotonically as the message streams; across all 833
workflow transcripts in this repo's history it never decreased, and the input
and cache figures never changed within one id).

Python 3.9-safe, stdlib only. Exit 0 on a printed usage object; 2 when a
requested transcript dir or run dir does not exist; the --selftest mode exits 0
on success, non-zero on failure.
"""

import argparse
import datetime
import glob as _glob
import json
import os
import re
import shlex
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple

# Backends that expose no machine-readable per-job token usage. For these we
# always emit measured:false + null tokens (never a fabricated number).
#
# `claude` stays here for the EVENTS-LOG path: a Claude worker writes no events
# log, so `--events-log` can never measure it. The --workflow-transcript path
# below is a DIFFERENT source (the harness's own subagent transcript) and is not
# governed by this set.
UNMEASURED_BACKENDS = frozenset(
    ("agy", "antigravity", "claude")
)

# The source label written into the `usage` object by the transcript path, so a
# reader can tell a harness-transcript measurement from a backend-events one.
WORKFLOW_TRANSCRIPT_SOURCE = "workflow-transcript"

# The four token metrics a Claude Code assistant line reports.
_TOKEN_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)


def _iter_json_lines(path: str) -> List[Any]:
    """Yield parsed JSON objects from a JSONL file.

    Missing/empty file -> []. Non-JSON lines are skipped, never fatal.
    """
    objs = []  # type: List[Any]
    if not path or not os.path.exists(path):
        return objs
    try:
        with open(path, "r") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    objs.append(json.loads(line))
                except ValueError:
                    # Non-JSON banner/log line — skip, don't crash.
                    continue
    except OSError:
        return []
    return objs


def _valid_int(val: Any) -> Optional[int]:
    """Return `val` iff it is a non-negative JSON INTEGER, else None.

    Anti-ruflo: a token count is trustworthy only when it is a real,
    non-negative integer. bool is an int subclass but never a valid count;
    strings, floats (including truncated/partial), and negatives are all
    rejected. Rejected/absent values must never be coerced into a zero.
    """
    if isinstance(val, bool):
        return None
    if isinstance(val, int) and val >= 0:
        return val
    return None


def _unmeasured(backend: str) -> Dict[str, Any]:
    return {
        "input_tokens": None,
        "output_tokens": None,
        "backend": backend,
        "measured": False,
    }


def _measured(backend: str, input_tokens: int, output_tokens: int) -> Dict[str, Any]:
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "backend": backend,
        "measured": True,
    }


def _extract_codex(objs: List[Any], backend: str) -> Dict[str, Any]:
    """SUM .usage.input_tokens / .usage.output_tokens over turn.completed lines.

    Non-JSON already filtered upstream. type=="error"/deprecation items carry no
    turn.completed usage, so they are simply not matched here.
    """
    total_in = 0
    total_out = 0
    saw = False
    for obj in objs:
        if not isinstance(obj, dict) or obj.get("type") != "turn.completed":
            continue
        usage = obj.get("usage")
        if not isinstance(usage, dict):
            continue
        i = _valid_int(usage.get("input_tokens"))
        o = _valid_int(usage.get("output_tokens"))
        # Contribute ONLY when BOTH sides are valid non-negative integers. A
        # malformed/incomplete usage block (empty, one side missing, non-int,
        # negative) contributes nothing — never a fabricated zero.
        if i is None or o is None:
            continue
        total_in += i
        total_out += o
        saw = True
    if not saw:
        return _unmeasured(backend)
    return _measured(backend, total_in, total_out)


def _extract_opencode(objs: List[Any], backend: str) -> Dict[str, Any]:
    """SUM .part.tokens.input / .part.tokens.output over step_finish lines."""
    total_in = 0
    total_out = 0
    saw = False
    for obj in objs:
        if not isinstance(obj, dict) or obj.get("type") != "step_finish":
            continue
        part = obj.get("part")
        if not isinstance(part, dict):
            continue
        tokens = part.get("tokens")
        if not isinstance(tokens, dict):
            continue
        i = _valid_int(tokens.get("input"))
        o = _valid_int(tokens.get("output"))
        # Both sides must be valid non-negative integers; else contribute nothing.
        if i is None or o is None:
            continue
        total_in += i
        total_out += o
        saw = True
    if not saw:
        return _unmeasured(backend)
    return _measured(backend, total_in, total_out)


def _extract_cursor(objs: List[Any], backend: str) -> Dict[str, Any]:
    """The FINAL type=="result" line with a VALID .usage.inputTokens/outputTokens.

    A result whose usage is malformed/incomplete (missing side, non-int,
    negative) contributes nothing; we fall back to the last result that had
    both sides valid. If none qualifies, honest unmeasured.
    """
    last_pair = None  # type: Optional[Tuple[int, int]]
    for obj in objs:
        if isinstance(obj, dict) and obj.get("type") == "result":
            usage = obj.get("usage")
            if not isinstance(usage, dict):
                continue
            i = _valid_int(usage.get("inputTokens"))
            o = _valid_int(usage.get("outputTokens"))
            if i is None or o is None:
                continue
            last_pair = (i, o)
    if last_pair is None:
        return _unmeasured(backend)
    return _measured(backend, last_pair[0], last_pair[1])


def extract_usage(backend: str, events_log: Optional[str]) -> Dict[str, Any]:
    """Dispatch to the per-backend normalizer; fail-open to unmeasured."""
    backend = (backend or "").strip()
    if backend in UNMEASURED_BACKENDS:
        return _unmeasured(backend)

    objs = _iter_json_lines(events_log) if events_log else []
    if backend == "codex":
        return _extract_codex(objs, backend)
    if backend == "opencode":
        return _extract_opencode(objs, backend)
    if backend == "cursor":
        return _extract_cursor(objs, backend)
    # Unknown backend: honest unmeasured, never a fabricated count.
    return _unmeasured(backend)


# --------------------------------------------------------------------------
# Engine C: per-job usage from Claude Code subagent transcripts (v3.4.17).
# --------------------------------------------------------------------------

# THE AUTHORITATIVE STAGE COMMAND. A prompt is prose plus one command the stage
# must run, and only that command's own arguments may identify the job. Scanning
# the WHOLE prompt for `--run-dir` credited a transcript to this run because the
# string appeared in a sentence, while the command it actually ran named a
# different run (round-2 review, the still-open finding).
#
# The subcommand set is the emitter's own dispatch table
# (scripts/compound-v-emit-workflow.py:8887-8892). It is closed on purpose:
# matching any lowercase word after the script path turned prose like
# "...compound-v-emit-workflow.py and scripts/compound-v-integration-gate.py..."
# into a second, bogus "command" in 4 of this repo's 833 transcripts.
_EMITTER_SUBCOMMANDS = frozenset((
    "emit", "gate-receipt", "record", "finalize-wave", "register-lane",
    "resume-prepare",
))
# EVERY occurrence, not the first: `a.py finalize-wave --run-dir R --jobs j;
# a.py record --run-dir R --job-id j` used to parse as ONE command whose tail
# swallowed the second invocation's flags, so a wave-level line was attributed
# to a job (round-3 review, finding 1). The path alone is the segment boundary —
# the subcommand is checked per segment — because an invocation whose next word
# is prose still ENDS the previous command's arguments.
_EMITTER_PATH_RE = re.compile(
    r"(?:^|\s)\S*compound-v-emit-workflow\.py(?=\s|$)"
)
_SUBCOMMAND_RE = re.compile(r"^\s+([a-z][a-z0-9-]*)")
# A rendered command may be split over several lines with a trailing backslash;
# one real prompt in this repo's history is. Join them before scanning.
_CONTINUATION_RE = re.compile(r"\\\n[ \t]*")
_STAGE_FLAGS = ("--run-dir", "--job-id", "--repo-root")


def stage_commands(prompt):  # type: (str) -> List[Dict[str, List[str]]]
    """Every authoritative stage command in `prompt`, argv-tokenized.

    Tokenizing with `shlex` rather than regex-scanning the tail is what makes
    the parse honest: `record` passes the gate's whole JSON verdict as a single
    quoted `--verdict-json` value, and that value CONTAINS the text
    `--run-dir '/some/other/path'`. A regex sees a second run dir; a tokenizer
    sees one string argument. Across this repo's 833 transcripts the tokenizer
    yields exactly one `--run-dir` for every one of the 784 prompts that carry a
    command, where the regex found two in some of them.

    A line may hold SEVERAL invocations (`...; ...` or `... && ...`). Each one
    bounds the previous one's arguments, so the line is split at every
    occurrence of the emitter path and each segment is tokenized on its own.
    A command whose quoting will not tokenize is skipped, not guessed at.
    """
    found = []  # type: List[Dict[str, List[str]]]
    for line in _CONTINUATION_RE.sub(" ", prompt).splitlines():
        starts = [m.end() for m in _EMITTER_PATH_RE.finditer(line)]
        if not starts:
            continue
        bounds = [m.start() for m in _EMITTER_PATH_RE.finditer(line)][1:]
        bounds.append(len(line))
        for start, stop in zip(starts, bounds):
            segment = line[start:stop]
            head = _SUBCOMMAND_RE.match(segment)
            if not head or head.group(1) not in _EMITTER_SUBCOMMANDS:
                continue
            try:
                tokens = shlex.split(segment[head.end():])
            except ValueError:
                continue
            cmd = dict((f, []) for f in _STAGE_FLAGS)  # type: Dict[str, List[str]]
            idx = 0
            while idx < len(tokens):
                token = tokens[idx]
                for flag in _STAGE_FLAGS:
                    if token == flag and idx + 1 < len(tokens):
                        cmd[flag].append(tokens[idx + 1])
                        idx += 1
                        break
                    if token.startswith(flag + "="):
                        cmd[flag].append(token[len(flag) + 1:])
                        break
                idx += 1
            cmd["subcommand"] = [head.group(1)]
            found.append(cmd)
    return found

# A job id becomes a FILENAME under <run-dir>/results/, so it must be one path
# segment and nothing else. Without this a manifest carrying `- id: /tmp/victim`
# (or `../../etc/x`) made `--write` clobber a file outside the run directory:
# os.path.join discards everything before an absolute component. Round-1
# cross-model review, finding 1.
_JOB_ID_SAFE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _safe_job_id(job_id):  # type: (Any) -> bool
    """True iff `job_id` is safe to use as a results/<id>.json basename."""
    return isinstance(job_id, str) and bool(_JOB_ID_SAFE_RE.match(job_id))


def _canonical_run_dir(path, base=None):  # type: (str, Optional[str]) -> Optional[str]
    """A run dir reduced to ONE canonical form, or None when unresolvable.

    THE RULE, stated once (round-1 cross-model review, finding 2):

      * an ABSOLUTE path is expanded (`~`) and `os.path.realpath`-ed;
      * a RELATIVE path is resolved against `base` — the `--repo-root` the SAME
        stage command carries — and then realpath-ed;
      * a relative path with no usable `--repo-root` is UNRESOLVABLE and returns
        None, so the transcript simply does not match.

    Comparison is on this canonical string alone. There is NO basename fallback:
    accepting `run-7` from /repo-b as /repo-a's `run-7` credited another
    checkout's tokens to this run. A run directory that has MOVED since its
    transcripts were written is therefore unmeasured — which is honest, and is
    the outcome we prefer to a plausible-looking wrong number.
    """
    if not path:
        return None
    # EVERY os.path call here is fed a string the TRANSCRIPT chose, and a
    # JSON-escaped NUL in a command path used to abort the entire scan
    # (round-3 review, finding 2). TWO layers, because one is not portable:
    #
    #   * REJECT A NUL OUTRIGHT. No filesystem path can contain one, so this is
    #     never a false refusal — and it is the only DETERMINISTIC half. On
    #     macOS/CPython 3.9 `os.path.realpath` swallows the NUL and hands back a
    #     path still carrying it; on Linux the same call reaches `os.lstat` and
    #     raises ValueError. A guard that only caught the exception would be
    #     untestable on half the machines that run this.
    #   * CATCH ValueError AS WELL AS OSError, for whatever else a hostile
    #     string can do to a stat call on a platform we have not tried.
    #
    # `expanduser`/`isabs`/`join` are pure string operations, but they sit
    # inside the same guard so a future os.path call added here cannot
    # reintroduce the hole.
    if "\x00" in path or (base and "\x00" in base):
        return None
    try:
        p = os.path.expanduser(path)
        if not os.path.isabs(p):
            if not base or not os.path.isabs(base):
                return None
            p = os.path.join(base, p)
        return os.path.realpath(p)
    except (OSError, ValueError):
        return None


def find_transcripts(root):  # type: (str) -> List[str]
    """Every `agent-*.jsonl` at or under `root`, sorted, deterministic.

    `root` may be a single workflow dir, a `subagents/` dir, a session dir, or
    the whole project dir — the walk is recursive either way.
    """
    found = []  # type: List[str]
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            if name.startswith("agent-") and name.endswith(".jsonl"):
                found.append(os.path.join(dirpath, name))
    return sorted(found)


def _message_text(msg):  # type: (Any) -> str
    """Flatten a transcript message's content to plain text."""
    if not isinstance(msg, dict):
        return ""
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []  # type: List[str]
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "".join(parts)
    return ""


def first_user_prompt(path):  # type: (str) -> Tuple[Optional[str], bool]
    """(first `type=="user"` message text or None, transcript-is-unreadable).

    Reads only as far as that line: the matching pass must not pay for the whole
    of every transcript in a tree it is going to reject.

    UTF-8 IS DECODED WITH errors="replace". A single 0xff byte anywhere in one
    transcript used to raise UnicodeDecodeError and abort the entire scan, so one
    corrupt file lost the usage of every job (round-1 cross-model review,
    finding 5). A replacement character can only make a prompt fail to match; it
    can never invent a match, because the keys matched on are ASCII flag values.

    The second return value is True when the file could not be opened at all, or
    when its FIRST non-empty line is not JSON — a file that is not a transcript,
    reported rather than silently swallowed by the `unmatched` count.
    """
    try:
        fh = open(path, "r", encoding="utf-8", errors="replace")
    except OSError:
        return None, True
    first_seen = False
    with fh:
        try:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except (ValueError, RecursionError):
                    # A line this parser cannot read — bad syntax, or nesting
                    # deep enough to exhaust the stack. Never fatal to the scan.
                    if not first_seen:
                        return None, True
                    first_seen = True
                    continue
                first_seen = True
                if isinstance(obj, dict) and obj.get("type") == "user":
                    return _message_text(obj.get("message")), False
        except (OSError, UnicodeError):
            # A read fault mid-file: honest "cannot classify", never a crash.
            return None, True
    return None, not first_seen


def classify_transcript(prompt, run_real, job_ids):
    # type: (Optional[str], str, Any) -> Tuple[str, Optional[str]]
    """Map one transcript's first prompt to ("job"|"run"|"other", job_id|None).

    "job"   — this run, and EXACTLY ONE `--job-id` on the stage command, which
              is a job of this run.
    "run"   — this run, and NO `--job-id` on the command: a wave-level stage
              such as finalize-wave, whose `--jobs a,b` cannot be split without
              inventing a division. Attributed to the run, never to a job.
    "other" — everything else: another run, no stage command at all, two
              different (run-dir, job-id, repo-root) tuples, a run dir that only
              appears in prose, or a job id this run does not have. Ambiguity is
              unmatched, never a guess.

    THE KEY IS THE COMMAND, NOT THE PROMPT. Every identifying value is read from
    ONE authoritative stage command and from nowhere else, and the (run-dir,
    job-id, repo-root) triple must come from that same command. Scanning the
    whole prompt let a run dir mentioned in a SENTENCE match while the command
    the stage actually ran named a different run (round-2 review).

    The prose key "Compound V job `x`" was removed in round 1 for the same
    reason: hand-written prompts quote that phrase, and a sentence is not an
    argument. Every real Engine C stage command carries `--job-id` — 628 of the
    784 command-carrying prompts in this repo's history, the other 156 being
    wave-level — so nothing measurable was lost with it.
    """
    if not prompt:
        return "other", None

    commands = stage_commands(prompt)
    if not commands:
        return "other", None

    # A prompt that mixes a WAVE-level command (no --job-id) with a job command
    # has no single owner. The distinct-tuple test below would reject it too,
    # but state the rule outright: run-level usage is never job-attributed
    # (round-3 review, finding 1).
    if any(cmd["--job-id"] for cmd in commands) and \
            any(not cmd["--job-id"] for cmd in commands):
        return "other", None

    tuples = set()
    for cmd in commands:
        tuples.add((
            tuple(sorted(set(cmd["--run-dir"]))),
            tuple(sorted(set(cmd["--job-id"]))),
            tuple(sorted(set(cmd["--repo-root"]))),
        ))
    if len(tuples) != 1:
        # Two different stage commands in one prompt: which one is the stage?
        # There is no honest answer, so there is no attribution.
        return "other", None

    run_dirs, ids, roots = tuples.pop()
    if len(run_dirs) != 1 or len(ids) > 1 or len(roots) > 1:
        return "other", None

    base = None  # type: Optional[str]
    if roots:
        # Same reasoning as _canonical_run_dir: the value is transcript-chosen.
        try:
            expanded = os.path.expanduser(roots[0])
            if os.path.isabs(expanded):
                base = expanded
        except (OSError, ValueError):
            base = None
    if _canonical_run_dir(run_dirs[0], base) != run_real:
        return "other", None

    if not ids:
        return "run", None
    if ids[0] in job_ids:
        return "job", ids[0]
    return "other", None


def _parse_timestamp(val):  # type: (Any) -> Optional[datetime.datetime]
    """A transcript `timestamp` as a comparable aware datetime, else None.

    Real lines look like `2026-09-03T20:05:50.326Z`. A naive value is read as
    UTC so aware and naive can never be compared against each other and raise.
    """
    if not isinstance(val, str) or not val.strip():
        return None
    text = val.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


def scan_transcript(path):  # type: (str) -> Tuple[List[Tuple[Any, Any, Dict[str, Optional[int]]]], int]
    """([(message id, order key or None, per-metric values)], malformed count).

    NO TOTALLING HAPPENS HERE. The caller folds several transcripts of one job
    together and deduplicates ACROSS them, because a message id is unique to a
    message, not to a file: totalling per file and adding the totals counted a
    shared id once per transcript (round-1 review, finding 4). Nor does this
    function pick a winner among an id's snapshots — that needs every
    transcript's snapshots side by side, so it belongs to the caller too
    (round-2 review, NEW 2).

    THE ORDER KEY is `(timestamp, apiBlockIndex)` off the transcript RECORD, not
    the file it happens to sit in. Evidence from this repo's 833 workflow
    transcripts (17049 assistant lines): `timestamp` is present on 100% of them,
    `apiBlockIndex` on 84.4%, and for all 6298 message ids that span more than
    one line the (timestamp, apiBlockIndex) order matches the file order exactly
    — 0 disagreements. So the key costs nothing on real data and is correct on
    data that arrives out of order, which filename sort order was not.

    A message contributes only when BOTH `input_tokens` and `output_tokens` are
    valid non-negative integers (the same rule the events-log path applies); the
    two cache metrics are carried when they too are valid. A malformed or
    incomplete usage block contributes NOTHING and is never read as a zero.

    A usage-bearing assistant record with NO non-empty string `message.id` is
    counted as MALFORMED and contributes nothing (round-2 review, NEW 3).
    Treating each id-less record as its own message double-counted the streamed
    snapshots of one message; there were 0 such records in 17049 real lines, so
    refusing them costs nothing measurable and cannot inflate a total.

    Decoding uses errors="replace" so one corrupt byte cannot abort the scan,
    and RecursionError from a deeply nested line is caught like a parse error.
    """
    entries = []  # type: List[Tuple[Any, Any, Dict[str, Optional[int]]]]
    malformed = 0
    try:
        fh = open(path, "r", encoding="utf-8", errors="replace")
    except OSError:
        return [], 0
    with fh:
        try:
            lines = list(fh)
        except (OSError, UnicodeError):
            return [], 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (ValueError, RecursionError):
            # RecursionError: ~1100 nested arrays on one line exhausts the
            # parser's stack. It is a line this parser cannot read, exactly like
            # a syntax error, and it must not take the scan down with it.
            malformed += 1
            continue
        if not isinstance(obj, dict) or obj.get("type") != "assistant":
            continue
        msg = obj.get("message")
        if not isinstance(msg, dict):
            continue
        usage = msg.get("usage")
        if not isinstance(usage, dict):
            continue
        i = _valid_int(usage.get("input_tokens"))
        o = _valid_int(usage.get("output_tokens"))
        if i is None or o is None:
            continue
        key = msg.get("id")
        if not isinstance(key, str) or not key:
            # No id means no way to tell a re-streamed snapshot of ONE message
            # from a second message. Counting it is a guess that can only ever
            # inflate; refusing it is a fact we can defend.
            malformed += 1
            continue
        stamp = _parse_timestamp(obj.get("timestamp"))
        block = obj.get("apiBlockIndex")
        if not isinstance(block, int) or isinstance(block, bool):
            block = -1
        order_key = None if stamp is None else (stamp, block)
        entries.append((key, order_key, {
            "input_tokens": i,
            "output_tokens": o,
            "cache_read_input_tokens": _valid_int(
                usage.get("cache_read_input_tokens")),
            "cache_creation_input_tokens": _valid_int(
                usage.get("cache_creation_input_tokens")),
        }))
    return entries, malformed


def _manifest_run_id_and_jobs(run_dir):  # type: (str) -> Tuple[Optional[str], List[str]]
    """`run_id` + job ids from <run-dir>/manifest.yaml, WITHOUT PyYAML.

    Stdlib-only per CONVENTIONS.md, and a manifest that will not parse must not
    stop a usage read: the caller unions this with the results/*.json basenames,
    so a job is found either way.
    """
    path = os.path.join(run_dir, "manifest.yaml")
    run_id = None  # type: Optional[str]
    jobs = []  # type: List[str]
    in_jobs = False
    try:
        # Explicit UTF-8: CI runs these tests under LANG=C, where the locale
        # default would refuse a manifest whose `feature:` carries an em dash.
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                line = raw.rstrip("\n")
                if not in_jobs:
                    m = re.match(r"^run_id:\s*['\"]?([^'\"\s#]+)", line)
                    if m:
                        run_id = m.group(1)
                        continue
                if re.match(r"^jobs:\s*$", line):
                    in_jobs = True
                    continue
                if in_jobs:
                    # A new top-level key ends the jobs block.
                    if re.match(r"^[A-Za-z_]", line):
                        in_jobs = False
                        continue
                    m = re.match(r"^-\s+id:\s*['\"]?([^'\"\s#]+)", line)
                    if m:
                        jobs.append(m.group(1))
    except (OSError, UnicodeError):
        return run_id, jobs
    return run_id, jobs


def results_root(run_dir):  # type: (str) -> Optional[str]
    """`<run-dir>/results` if it is safe to read and write, else None.

    CANONICALISING `results/` FIRST MADE IT ITS OWN TRUSTED ROOT. With
    `<run>/results` a symlink to `/tmp/victim-results`, `realpath` returned
    `/tmp/victim-results`, every path under it satisfied "inside the results
    root", and `--write` replaced a file outside the run (round-3 review,
    finding 3). The containment check has to be anchored on the RUN, not on
    whatever `results/` points at.

    Three conditions, all required, all `lstat`-based so a link is seen as a
    link:

      * `<run-dir>` is a real directory (not a file, not a dangling name);
      * `<run-dir>/results` is NOT a symlink;
      * `realpath(<run-dir>/results)` is exactly `realpath(<run-dir>)/results`,
        which also rejects a `results` reached through a symlinked ancestor
        that resolves elsewhere.

    Returns the REALPATH of the directory, so callers compare canonical
    against canonical.
    """
    if not run_dir:
        return None
    try:
        if not os.path.isdir(run_dir) or os.path.islink(run_dir.rstrip(os.sep)):
            return None
        candidate = os.path.join(run_dir, "results")
        if os.path.islink(candidate) or not os.path.isdir(candidate):
            return None
        real = os.path.realpath(candidate)
        if real != os.path.join(os.path.realpath(run_dir), "results"):
            return None
    except (OSError, ValueError):
        return None
    return real


def _results_job_ids(run_dir):  # type: (str) -> List[str]
    root = results_root(run_dir)
    if root is None:
        return []
    return sorted(
        os.path.basename(p)[: -len(".json")]
        for p in _glob.glob(os.path.join(root, "*.json"))
    )


def _results_path(run_dir, job_id):  # type: (str, str) -> Optional[str]
    """The path `--write` may write for `job_id`, or None if it is not safe.

    TWO independent gates, because either alone has a hole (round-1 review,
    finding 1). The NAME gate rejects anything that is not a single, ordinary
    path segment — an absolute id silently discards the directory in
    os.path.join, and `..` walks out of it. The CONTAINMENT gate then realpaths
    the result and demands it still be exactly <results>/<job>.json, which also
    refuses a results entry that is a SYMLINK pointing somewhere else — a name
    check alone cannot see that.
    """
    if not _safe_job_id(job_id):
        return None
    root = results_root(run_dir)
    if root is None:
        return None
    target = os.path.join(root, job_id + ".json")
    try:
        real = os.path.realpath(target)
    except (OSError, ValueError):
        return None
    if os.path.dirname(real) != root:
        return None
    if os.path.basename(real) != job_id + ".json":
        return None
    return target


def extract_workflow_usage(run_dir, transcript_root, backend="claude"):
    # type: (str, str, str) -> Dict[str, Any]
    """Per-job measured usage for one Engine C run, from its subagent transcripts.

    Returns {run_id, jobs: {job: usage}, unmeasured: [...], unmatched: int,
             run_level: usage|None, malformed_lines: int, scanned: int,
             unreadable_transcripts: int, rejected_jobs: [...]}.
    """
    run_real = os.path.realpath(os.path.expanduser(run_dir))
    # A refused results root is not "a run with no results": nothing can be read
    # from it and nothing will be written to it, and a reader deserves to know
    # which of those two it is looking at.
    results_refused = results_root(run_dir) is None
    manifest_run_id, manifest_jobs = _manifest_run_id_and_jobs(run_dir)
    run_id = manifest_run_id or os.path.basename(run_real)

    # A job id is a results/ FILENAME. One that is not a plain path segment is
    # refused HERE, before it can be matched or written (finding 1) — and named
    # in the report, because a job dropped in silence is a job nobody notices.
    all_ids = sorted(set(manifest_jobs) | set(_results_job_ids(run_dir)))
    job_ids = [j for j in all_ids if _safe_job_id(j)]
    rejected_jobs = [j for j in all_ids if not _safe_job_id(j)]

    per_job = dict((j, []) for j in job_ids)  # type: Dict[str, List[str]]
    run_level = []  # type: List[str]
    unmatched = 0
    scanned = 0
    unreadable = 0

    for path in find_transcripts(transcript_root):
        scanned += 1
        prompt, bad_file = first_user_prompt(path)
        if bad_file:
            unreadable += 1
        kind, job = classify_transcript(prompt, run_real, set(job_ids))
        if kind == "job" and job is not None:
            per_job[job].append(path)
        elif kind == "run":
            run_level.append(path)
        else:
            unmatched += 1

    malformed_total = 0
    jobs_out = {}  # type: Dict[str, Dict[str, Any]]
    unmeasured = []  # type: List[str]
    for job in job_ids:
        usage, malformed = _fold(per_job[job], backend)
        malformed_total += malformed
        jobs_out[job] = usage
        if not usage["measured"]:
            unmeasured.append(job)

    run_usage = None  # type: Optional[Dict[str, Any]]
    if run_level:
        run_usage, malformed = _fold(run_level, backend)
        malformed_total += malformed

    return {
        "run_id": run_id,
        "run_dir": run_real,
        "jobs": jobs_out,
        "unmeasured": unmeasured,
        "unmatched": unmatched,
        "run_level": run_usage,
        "malformed_lines": malformed_total,
        "scanned": scanned,
        "unreadable_transcripts": unreadable,
        "rejected_jobs": rejected_jobs,
        "results_refused": results_refused,
    }


_INVARIANT_KEYS = ("input_tokens", "cache_read_input_tokens",
                   "cache_creation_input_tokens")


def _pick_snapshot(snapshots):
    # type: (List[Tuple[Any, Dict[str, Optional[int]]]]) -> Optional[Dict[str, Optional[int]]]
    """The one true reading for ONE message id, or None if it cannot be told.

    TWO RULES, in order (round-2 review, NEW 2):

    1. ORDERED. If EVERY snapshot of this id carries a usable `(timestamp,
       apiBlockIndex)` key, sort by it and take the last. That is a real
       ordering off the record itself, so a lexically later FILE holding an
       OLDER snapshot can no longer win — which is what filename sort order did.
       Requiring *every* snapshot to have a key keeps the rule total: a partial
       order would just be a different guess.

    2. MONOTONIC FALLBACK, for an id whose records carry no usable timestamp.
       `output_tokens` grows as a message streams, so its maximum is the final
       value. The other three are INVARIANT across the snapshots of one message
       — 0 disagreements in 17049 real assistant lines — so if they DISAGREE
       here, these are not snapshots of one message and no reading of them is
       defensible: return None, and the caller counts the id as malformed. A
       maximum taken over contradictory records would be a number with nothing
       behind it.
    """
    if not snapshots:
        return None
    if all(key is not None for key, _ in snapshots):
        # `sorted` is stable, so equal keys keep discovery order (paths order,
        # then line order) — deterministic without an artificial tie-break.
        return sorted(snapshots, key=lambda pair: pair[0])[-1][1]

    first = snapshots[0][1]
    for _key, vals in snapshots[1:]:
        for name in _INVARIANT_KEYS:
            if vals.get(name) != first.get(name):
                return None
    best = dict(first)
    outputs = [vals.get("output_tokens") for _key, vals in snapshots
               if vals.get("output_tokens") is not None]
    best["output_tokens"] = max(outputs) if outputs else None
    return best


def _fold(paths, backend):  # type: (List[str], str) -> Tuple[Dict[str, Any], int]
    """Fold several transcripts into one canonical `usage` object.

    Deduplication spans the WHOLE set, not each file: `paths` are the stages of
    ONE job, a message id identifies a message rather than a file, and a resumed
    or replayed stage that re-emits the same message in a second transcript must
    still be counted once. `_pick_snapshot` decides WHICH reading of an id
    counts; an id it cannot decide is counted as malformed and contributes
    nothing.
    """
    totals = dict((k, None) for k in _TOKEN_KEYS)  # type: Dict[str, Optional[int]]
    malformed = 0
    merged = {}  # type: Dict[Any, List[Tuple[Any, Dict[str, Optional[int]]]]]
    order = []  # type: List[Any]
    for path in paths:
        entries, bad = scan_transcript(path)
        malformed += bad
        for key, order_key, vals in entries:
            if key not in merged:
                order.append(key)
                merged[key] = []
            merged[key].append((order_key, vals))
    messages = 0
    for key in order:
        vals = _pick_snapshot(merged[key])
        if vals is None:
            # Contradictory snapshots of one id: refused, not averaged.
            malformed += 1
            continue
        messages += 1
        for name in _TOKEN_KEYS:
            val = vals.get(name)
            if val is not None:
                totals[name] = (totals[name] or 0) + val

    usage = {
        "input_tokens": totals["input_tokens"],
        "output_tokens": totals["output_tokens"],
        "cache_read_input_tokens": totals["cache_read_input_tokens"],
        "cache_creation_input_tokens": totals["cache_creation_input_tokens"],
        "backend": backend,
        # MEASURED means at least one real assistant message was read. A job
        # with no transcript, or a transcript with no well-formed usage, stays
        # measured:false with null counts — never a fabricated zero.
        "measured": messages > 0,
        "source": WORKFLOW_TRANSCRIPT_SOURCE,
        "transcripts": sorted(os.path.basename(p) for p in paths),
    }
    return usage, malformed


def _null_dash():  # type: () -> str
    """The character standing for "not measured", safe for THIS stdout.

    "—" is the documented rendering (commands/v-status.md), but a stream whose
    encoding is ASCII — `PYTHONIOENCODING=ascii`, or a C locale on a Python
    without UTF-8 mode — cannot encode it, and the write raised UnicodeEncodeError
    and took the whole render down. A status line that crashes is worse than one
    that prints "-". The one thing that must never happen either way is a 0
    standing in for a number nobody measured.

    NOTE: compound-v-usage-aggregate.py carries the identical helper. It is a
    property of the caller's own stdout, asked locally, not a shared constant —
    but keep the two in step.
    """
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        u"\u2014".encode(encoding)
    except (LookupError, UnicodeEncodeError):
        return "-"
    return u"\u2014"


def _fmt_tok(val):  # type: (Optional[int]) -> str
    """A null metric prints as a dash, never as a 0 that was never measured."""
    return _null_dash() if val is None else str(val)


def format_workflow_report(report):  # type: (Dict[str, Any]) -> str
    """The dry-run report: one line per job, then unmeasured / unmatched."""
    lines = []  # type: List[str]
    for job in sorted(report["jobs"]):
        u = report["jobs"][job]
        lines.append("%s input=%s output=%s cache_read=%s cache_create=%s "
                     "transcripts=%d"
                     % (job, _fmt_tok(u["input_tokens"]),
                        _fmt_tok(u["output_tokens"]),
                        _fmt_tok(u["cache_read_input_tokens"]),
                        _fmt_tok(u["cache_creation_input_tokens"]),
                        len(u["transcripts"])))
    lines.append("unmeasured: %s"
                 % (", ".join(report["unmeasured"]) if report["unmeasured"]
                    else "(none)"))
    lines.append("unmatched: %d" % report["unmatched"])
    run_level = report.get("run_level")
    if run_level:
        # Wave-level stages: real spend on this run that belongs to NO single
        # job. Reported, never divided among the jobs.
        lines.append("run_level: input=%s output=%s cache_read=%s "
                     "cache_create=%s transcripts=%d"
                     % (_fmt_tok(run_level["input_tokens"]),
                        _fmt_tok(run_level["output_tokens"]),
                        _fmt_tok(run_level["cache_read_input_tokens"]),
                        _fmt_tok(run_level["cache_creation_input_tokens"]),
                        len(run_level["transcripts"])))
    if report["malformed_lines"]:
        lines.append("malformed_lines: %d" % report["malformed_lines"])
    if report.get("unreadable_transcripts"):
        lines.append("unreadable_transcripts: %d"
                     % report["unreadable_transcripts"])
    if report.get("results_refused"):
        lines.append("results_refused: <run-dir>/results is not a plain "
                     "directory inside the run (symlink or missing) - nothing "
                     "was read from it or written to it")
    if report.get("rejected_jobs"):
        # Named, never silently dropped: a job id that cannot be a results
        # filename is a broken manifest, and a broken manifest should be loud.
        lines.append("rejected_jobs (unsafe id, never written): %s"
                     % ", ".join(report["rejected_jobs"]))
    return "\n".join(lines)


def write_workflow_usage(run_dir, report):  # type: (str, Dict[str, Any]) -> List[str]
    """Merge each MEASURED job's `usage` into results/<job>.json. Idempotent.

    The object REPLACES any previous `usage` (it is recomputed from the
    transcripts every time), so a second run cannot double-count. A job with no
    measurement is left untouched: an absent `usage` is the schema's own way of
    saying "no measurement", and stamping measured:false over a file would add
    noise without adding a fact.
    """
    written = []  # type: List[str]
    for job in sorted(report["jobs"]):
        usage = report["jobs"][job]
        if not usage["measured"]:
            continue
        # Re-checked at the point of writing, not only where job ids were
        # collected: this function is reachable with a caller-built report, and
        # a containment rule that only runs somewhere else is not a rule.
        path = _results_path(run_dir, job)
        if path is None or not os.path.isfile(path):
            continue
        # lstat, not stat: `os.path.isfile` follows a symlink and reports the
        # TARGET. Refusing the link itself is the only way to be sure the bytes
        # land where the name says they do.
        if os.path.islink(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError, UnicodeError):
            continue
        if not isinstance(doc, dict):
            continue
        doc["usage"] = usage
        # BYTE-FOR-BYTE the producer's own serializer
        # (compound-v-emit-workflow.py `record`: json.dumps(indent=2,
        # sort_keys=True) + "\n", ensure_ascii left at its default True). Any
        # other setting rewrites lines this merge never touched — an
        # ensure_ascii=False first cut re-encoded every escaped em dash in
        # `summary`, so the diff claimed a change to a field it had not read.
        text = json.dumps(doc, indent=2, sort_keys=True) + "\n"
        # mkstemp, not "<path>.cv-usage-tmp": the old name was PREDICTABLE, so a
        # symlink pre-placed there was followed by open(..., "w") and the write
        # landed on whatever it pointed at — then os.replace installed the
        # symlink as the result file (round-2 review, NEW 1, HIGH). mkstemp
        # opens O_CREAT|O_EXCL on a random name in the SAME directory, so the
        # descriptor cannot be pre-empted and os.replace stays atomic.
        target_dir = os.path.dirname(path)
        fd, tmp = tempfile.mkstemp(dir=target_dir, prefix=".cv-usage-",
                                   suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
            tmp = None
        finally:
            if tmp is not None and os.path.exists(tmp):
                os.unlink(tmp)
        written.append(path)
    return written


# --------------------------------------------------------------------------
# Selftest. Inline fixtures are shaped EXACTLY like the real events documented
# in the library audit (turn.completed.usage.{input_tokens,output_tokens},
# step_finish.part.tokens.{input,output}, result.usage.{inputTokens,outputTokens}).
# --------------------------------------------------------------------------
def _write_tmp(lines: List[str]) -> str:
    fd, path = tempfile.mkstemp(prefix="cv-usage-selftest-", suffix=".jsonl")
    with os.fdopen(fd, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def _selftest() -> int:
    failures = []  # type: List[str]

    def check(name: str, got: Any, want: Any) -> None:
        if got != want:
            failures.append("%s: got %r, want %r" % (name, got, want))

    # --- codex: SUM across turn.completed; skip non-JSON + error/deprecation ---
    codex_lines = [
        '{"type":"thread.started","thread_id":"11111111-2222-3333-4444-555555555555"}',
        'not json at all, a plain banner line',
        '{"type":"turn.completed","usage":{"input_tokens":100,"cached_input_tokens":10,"output_tokens":40,"reasoning_output_tokens":5}}',
        '{"type":"error","message":"transient"}',
        '{"type":"turn.completed","usage":{"input_tokens":200,"cached_input_tokens":0,"output_tokens":60,"reasoning_output_tokens":0}}',
    ]
    p = _write_tmp(codex_lines)
    try:
        u = extract_usage("codex", p)
    finally:
        os.remove(p)
    check("codex.measured", u["measured"], True)
    check("codex.input_tokens", u["input_tokens"], 300)
    check("codex.output_tokens", u["output_tokens"], 100)
    check("codex.backend", u["backend"], "codex")

    # --- opencode: SUM across step_finish.part.tokens ---
    opencode_lines = [
        '{"type":"step_start"}',
        '{"type":"step_finish","part":{"tokens":{"input":500,"output":120,"reasoning":0,"cache":{"read":0,"write":0},"total":620},"cost":0.01}}',
        '{"type":"step_finish","part":{"tokens":{"input":300,"output":80,"reasoning":0,"cache":{"read":0,"write":0},"total":380}}}',
    ]
    p = _write_tmp(opencode_lines)
    try:
        u = extract_usage("opencode", p)
    finally:
        os.remove(p)
    check("opencode.measured", u["measured"], True)
    check("opencode.input_tokens", u["input_tokens"], 800)
    check("opencode.output_tokens", u["output_tokens"], 200)
    check("opencode.backend", u["backend"], "opencode")

    # --- cursor: FINAL result.usage wins ---
    cursor_lines = [
        '{"type":"assistant","message":"working"}',
        '{"type":"result","usage":{"inputTokens":111,"outputTokens":22,"cacheReadTokens":0,"cacheWriteTokens":0}}',
        '{"type":"result","usage":{"inputTokens":1234,"outputTokens":567,"cacheReadTokens":10,"cacheWriteTokens":5}}',
    ]
    p = _write_tmp(cursor_lines)
    try:
        u = extract_usage("cursor", p)
    finally:
        os.remove(p)
    check("cursor.measured", u["measured"], True)
    check("cursor.input_tokens", u["input_tokens"], 1234)
    check("cursor.output_tokens", u["output_tokens"], 567)
    check("cursor.backend", u["backend"], "cursor")

    # --- unmeasured backends: always measured:false + null tokens ---
    for b in ("agy", "antigravity", "claude"):
        u = extract_usage(b, None)
        check("%s.measured" % b, u["measured"], False)
        check("%s.input_tokens" % b, u["input_tokens"], None)
        check("%s.output_tokens" % b, u["output_tokens"], None)
        check("%s.backend" % b, u["backend"], b)

    # --- fail-open: missing events log for a measurable backend ---
    u = extract_usage("codex", "/no/such/events/log.jsonl")
    check("codex.missing.measured", u["measured"], False)
    check("codex.missing.input_tokens", u["input_tokens"], None)
    check("codex.missing.output_tokens", u["output_tokens"], None)

    # --- fail-open: empty events log ---
    p = _write_tmp([""])
    try:
        u = extract_usage("opencode", p)
    finally:
        os.remove(p)
    check("opencode.empty.measured", u["measured"], False)
    check("opencode.empty.input_tokens", u["input_tokens"], None)

    # --- fail-open: garbage / no matching events ---
    p = _write_tmp(["totally not json", '{"type":"other"}'])
    try:
        u = extract_usage("cursor", p)
    finally:
        os.remove(p)
    check("cursor.garbage.measured", u["measured"], False)
    check("cursor.garbage.output_tokens", u["output_tokens"], None)

    # --- FIX 1: malformed / incomplete usage must NEVER become a measured 0 ---
    # Each of these events is the ONLY relevant event in its log, so a correct
    # extractor yields measured:false + null tokens (not measured:true + 0).
    malformed_cases = [
        # (backend, line, label)
        ("codex", '{"type":"turn.completed","usage":{}}', "codex.empty_usage"),
        ("codex", '{"type":"turn.completed","usage":{"input_tokens":"100","output_tokens":"40"}}', "codex.string_tokens"),
        ("codex", '{"type":"turn.completed","usage":{"input_tokens":-5,"output_tokens":40}}', "codex.negative_tokens"),
        ("codex", '{"type":"turn.completed","usage":{"input_tokens":12.5,"output_tokens":40.0}}', "codex.float_tokens"),
        ("codex", '{"type":"turn.completed","usage":{"input_tokens":100}}', "codex.partial_input_only"),
        ("codex", '{"type":"turn.completed","usage":{"output_tokens":40}}', "codex.partial_output_only"),
        ("codex", '{"type":"turn.completed","usage":{"input_tokens":true,"output_tokens":false}}', "codex.bool_tokens"),
        ("opencode", '{"type":"step_finish","part":{"tokens":{}}}', "opencode.empty_tokens"),
        ("opencode", '{"type":"step_finish","part":{"tokens":{"input":"500","output":"120"}}}', "opencode.string_tokens"),
        ("opencode", '{"type":"step_finish","part":{"tokens":{"input":-1,"output":120}}}', "opencode.negative_tokens"),
        ("opencode", '{"type":"step_finish","part":{"tokens":{"input":5.5,"output":6.5}}}', "opencode.float_tokens"),
        ("opencode", '{"type":"step_finish","part":{"tokens":{"input":500}}}', "opencode.partial_only"),
        ("cursor", '{"type":"result","usage":{}}', "cursor.empty_usage"),
        ("cursor", '{"type":"result","usage":{"inputTokens":"111","outputTokens":"22"}}', "cursor.string_tokens"),
        ("cursor", '{"type":"result","usage":{"inputTokens":-3,"outputTokens":22}}', "cursor.negative_tokens"),
        ("cursor", '{"type":"result","usage":{"inputTokens":1.5,"outputTokens":2.5}}', "cursor.float_tokens"),
        ("cursor", '{"type":"result","usage":{"inputTokens":111}}', "cursor.partial_only"),
    ]
    for backend, line, label in malformed_cases:
        p = _write_tmp([line])
        try:
            u = extract_usage(backend, p)
        finally:
            os.remove(p)
        check("%s.measured" % label, u["measured"], False)
        check("%s.input_tokens" % label, u["input_tokens"], None)
        check("%s.output_tokens" % label, u["output_tokens"], None)

    # --- FIX 1: a genuine well-formed 0 IS a real measurement (not fabricated) ---
    p = _write_tmp(['{"type":"turn.completed","usage":{"input_tokens":0,"output_tokens":0}}'])
    try:
        u = extract_usage("codex", p)
    finally:
        os.remove(p)
    check("codex.real_zero.measured", u["measured"], True)
    check("codex.real_zero.input_tokens", u["input_tokens"], 0)
    check("codex.real_zero.output_tokens", u["output_tokens"], 0)

    # --- FIX 1: a malformed event must not poison a valid one in the same log ---
    p = _write_tmp([
        '{"type":"turn.completed","usage":{"input_tokens":100,"output_tokens":40}}',
        '{"type":"turn.completed","usage":{"input_tokens":"bad"}}',
        '{"type":"turn.completed","usage":{"input_tokens":200,"output_tokens":60}}',
    ])
    try:
        u = extract_usage("codex", p)
    finally:
        os.remove(p)
    check("codex.mixed.measured", u["measured"], True)
    check("codex.mixed.input_tokens", u["input_tokens"], 300)
    check("codex.mixed.output_tokens", u["output_tokens"], 100)

    _selftest_workflow(check)

    if failures:
        sys.stdout.write("SELFTEST FAIL (%d):\n" % len(failures))
        for f in failures:
            sys.stdout.write("  - %s\n" % f)
        return 1
    sys.stdout.write("SELFTEST PASS: codex/opencode/cursor sums + unmeasured + "
                     "fail-open + Engine C transcript mode OK\n")
    return 0


# --------------------------------------------------------------------------
# Engine C selftest. The fixture is shaped EXACTLY like a real transcript tree:
# one `type=="user"` prompt line carrying the stage command, then `type ==
# "assistant"` lines whose `message.usage` repeats per streamed content block.
# --------------------------------------------------------------------------
def _tx_user(text):  # type: (str) -> str
    return json.dumps({"type": "user", "isSidechain": True,
                       "message": {"role": "user", "content": text}})


def _tx_assistant(mid, i, o, cr, cc, ts=None, block=0):
    # type: (Any, int, int, int, int, Optional[str], int) -> str
    """One streamed assistant line, shaped like the real thing.

    `mid` of None omits `message.id` entirely (the NEW-3 case); `ts` of None
    omits `timestamp` (the ordering fallback case).
    """
    message = {
        "role": "assistant", "model": "claude-opus-5",
        "usage": {
            "input_tokens": i, "output_tokens": o,
            "cache_read_input_tokens": cr,
            "cache_creation_input_tokens": cc,
            # Real transcripts carry extra keys; they must be ignored.
            "service_tier": "standard",
            "iterations": [{"input_tokens": i, "output_tokens": o}],
        },
    }  # type: Dict[str, Any]
    if mid is not None:
        message["id"] = mid
    record = {"type": "assistant", "apiBlockIndex": block,
              "message": message}  # type: Dict[str, Any]
    if ts is not None:
        record["timestamp"] = ts
    return json.dumps(record)


def _write_transcript(path, lines):  # type: (str, List[str]) -> None
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def _write_transcript_bytes(path, blob):  # type: (str, bytes) -> None
    """A transcript containing bytes that are NOT valid UTF-8 (finding 5)."""
    with open(path, "wb") as fh:
        fh.write(blob)


# The literal emitter path a real stage prompt carries. The matcher keys on this
# name plus one of the emitter's own subcommands, so a fixture that used a made-up
# `emit.py` would be testing a shape no run ever produces.
_EMIT = "/repo/scripts/compound-v-emit-workflow.py"


def _emitter_dispatch_table():  # type: () -> Optional[frozenset]
    """The subcommand names in the emitter's own `SUBCOMMANDS = {...}` block,
    parsed from source (never executed). None when the sibling is not there."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "compound-v-emit-workflow.py")
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            src = fh.read()
    except OSError:
        return None
    m = re.search(r"^SUBCOMMANDS = \{(.*?)^\}", src, re.S | re.M)
    if not m:
        return None
    return frozenset(re.findall(r'^\s*"([a-z-]+)":', m.group(1), re.M))


def _selftest_workflow(check):  # type: (Any) -> None
    """Two jobs (one with two transcripts), unmatched transcripts, malformed
    lines, a job with no transcript, hostile job ids, and an idempotent --write."""
    import shutil

    # Drift guard: _EMITTER_SUBCOMMANDS is a hand copy of the emitter's dispatch
    # table. A subcommand added there and not here would make its stage prompt
    # invisible to the matcher (silently unmeasured), so the copy is checked
    # against the emitter's source on every selftest run.
    table = _emitter_dispatch_table()
    check("wf.emitter_subcommands_in_step", table is not None and table == _EMITTER_SUBCOMMANDS,
          True)

    tmp = tempfile.mkdtemp(prefix="cv-usage-wf-selftest-")
    try:
        run_dir = os.path.join(tmp, "docs", "superpowers", "execution",
                               "2026-09-04-selftest-run")
        results = os.path.join(run_dir, "results")
        os.makedirs(results)
        tx = os.path.join(tmp, "transcripts", "wf_deadbeef")
        os.makedirs(tx)

        # Two of these job ids are HOSTILE: an absolute path and a `..` walk.
        # A manifest can carry anything, and `--write` turns a job id into a
        # filename — so the extractor must refuse them, not sanitise them into
        # something plausible (round-1 review, finding 1).
        victim_abs = os.path.join(tmp, "victim")
        escape_rel = "../../escape"
        # SENTINELS at both escape targets. The hazard is not "a new file
        # appears" — `--write` only touches an EXISTING result — it is that an
        # existing file elsewhere gets overwritten, so the proof has to be a
        # file that already exists and must survive untouched.
        escape_target = os.path.join(tmp, "docs", "superpowers", "execution",
                                     "escape.json")
        for sentinel in (victim_abs + ".json", escape_target):
            with open(sentinel, "w", encoding="utf-8") as fh:
                fh.write('{"sentinel": "untouched"}\n')

        with open(os.path.join(run_dir, "manifest.yaml"), "w",
                  encoding="utf-8") as fh:
            fh.write("run_id: 2026-09-04-selftest-run\n"
                     "feature: selftest — an em dash, so LANG=C cannot decode\n"
                     "jobs:\n"
                     "- id: job-alpha\n"
                     "  type: implement\n"
                     "- id: job-beta\n"
                     "  type: implement\n"
                     "- id: job-gamma\n"
                     "  type: review\n"
                     "- id: job-epsilon\n"
                     "  type: implement\n"
                     "- id: job-zeta\n"
                     "  type: implement\n"
                     "- id: %s\n"
                     "  type: implement\n"
                     "- id: %s\n"
                     "  type: implement\n"
                     "max_parallel: 2\n" % (victim_abs, escape_rel))

        base = {
            "status": "success", "blocked": False, "files_changed": [],
            "violations": [], "summary": "ok", "session_id": "", "worktree": "",
            "exit_code": 0, "failure_class": None, "retry_after_seconds": 0,
        }
        for job in ("job-alpha", "job-beta", "job-gamma", "job-epsilon",
                    "job-zeta"):
            with open(os.path.join(results, job + ".json"), "w",
                      encoding="utf-8") as fh:
                fh.write(json.dumps(dict(base), indent=2, sort_keys=True) + "\n")

        def prompt(stage, job, rd=run_dir, root="/repo"):
            return ("Run EXACTLY this one command.\n\n```bash\n"
                    "/usr/bin/python3 -B %s %s --run-dir '%s' "
                    "--job-id '%s' --repo-root '%s'\n```\n"
                    % (_EMIT, stage, rd, job, root))

        # job-alpha: TWO transcripts (implement + gate). The implement one
        # carries a MALFORMED line that must be counted, not fatal; its first
        # message is written TWICE (streaming) and must be counted ONCE.
        _write_transcript(os.path.join(tx, "agent-aaaa1.jsonl"), [
            _tx_user("You are the implementer for Compound V job `job-alpha`.\n"
                     "```bash\n/usr/bin/python3 -B %s register-lane "
                     "--run-dir %s --job-id job-alpha --cwd /x "
                     "--repo-root /repo\n```" % (_EMIT, run_dir)),
            _tx_assistant("msg_A1", 10, 5, 100, 200, "2026-09-04T10:00:00.100Z", 0),
            "{ this line is not json",
            _tx_assistant("msg_A1", 10, 40, 100, 200, "2026-09-04T10:00:00.900Z", 1),
            _tx_assistant("msg_A2", 3, 7, 300, 0, "2026-09-04T10:00:01.000Z", 0),
        ])
        # ...and append a line of invalid UTF-8 to that SAME transcript. Without
        # errors="replace" the decode raises and job-alpha loses every token it
        # has (round-1 review, finding 5).
        with open(os.path.join(tx, "agent-aaaa1.jsonl"), "ab") as _fh:
            _fh.write(b"\xff\xfe garbage tail\n")
        # ...and a line ~1100 arrays deep, which exhausts the JSON parser's
        # stack. RecursionError must be caught like a syntax error (NEW 4).
        with open(os.path.join(tx, "agent-aaaa1.jsonl"), "a",
                  encoding="utf-8") as _fh:
            _fh.write("[" * 1200 + "]" * 1200 + "\n")
        _write_transcript(os.path.join(tx, "agent-aaaa2.jsonl"), [
            _tx_user(prompt("gate-receipt", "job-alpha")),
            _tx_assistant("msg_A3", 1, 2, 4, 8, "2026-09-04T10:00:02.000Z", 0),
        ])

        # job-beta: TWO transcripts that BOTH carry `msg_B1`. A message id
        # identifies a message, not a file, so the later snapshot (700) must
        # replace the earlier (500) — not add to it (round-1 review, finding 4).
        _write_transcript(os.path.join(tx, "agent-bbbb1.jsonl"), [
            _tx_user(prompt("record", "job-beta")),
            _tx_assistant("msg_B1", 1000, 500, 20, 30,
                          "2026-09-04T11:00:00.000Z", 0),
        ])
        _write_transcript(os.path.join(tx, "agent-bbbb2.jsonl"), [
            _tx_user(prompt("gate-receipt", "job-beta")),
            _tx_assistant("msg_B1", 1000, 700, 20, 30,
                          "2026-09-04T11:00:05.000Z", 0),   # SAME id, LATER
            _tx_assistant("msg_B2", 1, 1, 1, 1,
                          "2026-09-04T11:00:06.000Z", 0),
        ])

        # job-zeta: THE ORDERING CASE (round-2 review, NEW 2). The lexically
        # LATER file holds the OLDER snapshot. Filename order picks 999; the
        # timestamp picks 42, which is what actually happened last.
        _write_transcript(os.path.join(tx, "agent-zzzz1.jsonl"), [
            _tx_user(prompt("record", "job-zeta")),
            _tx_assistant("msg_Z1", 5, 42, 6, 7,
                          "2026-09-04T12:00:09.000Z", 1),   # NEWER
        ])
        _write_transcript(os.path.join(tx, "agent-zzzz2.jsonl"), [
            _tx_user(prompt("gate-receipt", "job-zeta")),
            _tx_assistant("msg_Z1", 5, 999, 6, 7,
                          "2026-09-04T12:00:01.000Z", 0),   # OLDER
        ])

        # job-gamma: NO transcript at all -> unmeasured.
        # UNMATCHED: same job id, DIFFERENT run. This is the collision the run
        # key exists to defend against; without it these 999 tokens would be
        # credited to this run's job-alpha.
        other_run = os.path.join(tmp, "docs", "superpowers", "execution",
                                 "2026-09-04-some-other-run")
        os.makedirs(other_run)
        _write_transcript(os.path.join(tx, "agent-cccc1.jsonl"), [
            _tx_user(prompt("gate-receipt", "job-alpha", rd=other_run)),
            _tx_assistant("msg_C1", 999, 999, 999, 999,
                          "2026-09-04T13:00:00.000Z", 0),
        ])
        # A wave-level stage of THIS run: no --job-id, so run_level, not a job.
        _write_transcript(os.path.join(tx, "agent-dddd1.jsonl"), [
            _tx_user("```bash\n/usr/bin/python3 -B %s finalize-wave "
                     "--run-dir '%s' --wave '1' --jobs 'job-alpha'\n```"
                     % (_EMIT, run_dir)),
            _tx_assistant("msg_D1", 7, 9, 11, 13,
                          "2026-09-04T14:00:00.000Z", 0),
        ])
        # UNMATCHED: ANOTHER CHECKOUT, SAME RUN ID. The basename is identical;
        # only the absolute path differs (round-1 review, finding 2).
        other_repo_run = os.path.join(tmp, "other-repo", "docs", "superpowers",
                                      "execution", "2026-09-04-selftest-run")
        os.makedirs(other_repo_run)
        _write_transcript(os.path.join(tx, "agent-eeee1.jsonl"), [
            _tx_user(prompt("gate-receipt", "job-alpha", rd=other_repo_run)),
            _tx_assistant("msg_E9", 888, 888, 888, 888,
                          "2026-09-04T15:00:00.000Z", 0),
        ])
        # RUN-LEVEL, NOT job-beta: this run's dir, and the prose sentence names
        # a job — but the command carries no --job-id (round-1 review, finding 3).
        _write_transcript(os.path.join(tx, "agent-ffff1.jsonl"), [
            _tx_user("Please review Compound V job `job-beta` for me.\n"
                     "```bash\n%s finalize-wave --run-dir '%s' "
                     "--repo-root '/repo'\n```" % (_EMIT, run_dir)),
            _tx_assistant("msg_F1", 5, 6, 7, 8,
                          "2026-09-04T16:00:00.000Z", 0),
        ])
        # UNMATCHED: two DIFFERENT --job-id values. Ambiguity is not a guess.
        _write_transcript(os.path.join(tx, "agent-gggg1.jsonl"), [
            _tx_user("```bash\n%s record --run-dir '%s' --job-id "
                     "'job-alpha' --job-id 'job-beta'\n```" % (_EMIT, run_dir)),
            _tx_assistant("msg_G1", 777, 777, 777, 777,
                          "2026-09-04T17:00:00.000Z", 0),
        ])
        # UNMATCHED: names the REJECTED absolute job id. It is not a job of this
        # run, because an unsafe id never becomes one.
        _write_transcript(os.path.join(tx, "agent-hhhh1.jsonl"), [
            _tx_user("```bash\n%s record --run-dir '%s' --job-id '%s'\n```"
                     % (_EMIT, run_dir, victim_abs)),
            _tx_assistant("msg_H1", 666, 666, 666, 666,
                          "2026-09-04T18:00:00.000Z", 0),
        ])
        # UNREADABLE: a transcript whose first byte sequence is not UTF-8 at
        # all. It must be reported, and it must NOT abort the scan (finding 5).
        _write_transcript_bytes(os.path.join(tx, "agent-iiii1.jsonl"),
                                b"\xff\xfe not a transcript\n")
        # job-epsilon: a RELATIVE --run-dir, resolved against the SAME command's
        # --repo-root. This is the stated resolution rule, exercised end to end.
        _write_transcript(os.path.join(tx, "agent-jjjj1.jsonl"), [
            _tx_user("```bash\n%s record --run-dir "
                     "docs/superpowers/execution/2026-09-04-selftest-run "
                     "--job-id 'job-epsilon' --repo-root '%s'\n```"
                     % (_EMIT, tmp)),
            _tx_assistant("msg_J1", 2, 4, 6, 8,
                          "2026-09-04T19:00:00.000Z", 0),
        ])
        # UNMATCHED: the same relative --run-dir with NO --repo-root. There is
        # nothing to resolve it against, so it is unresolvable, not "probably
        # ours".
        _write_transcript(os.path.join(tx, "agent-kkkk1.jsonl"), [
            _tx_user("```bash\n%s record --run-dir "
                     "docs/superpowers/execution/2026-09-04-selftest-run "
                     "--job-id 'job-alpha'\n```" % _EMIT),
            _tx_assistant("msg_K1", 555, 555, 555, 555,
                          "2026-09-04T20:00:00.000Z", 0),
        ])
        # UNMATCHED, THE STILL-OPEN CASE (round-2 review). The PROSE names THIS
        # run's dir; the authoritative command names another run's. Scanning the
        # whole prompt credited these tokens to job-alpha.
        _write_transcript(os.path.join(tx, "agent-llll1.jsonl"), [
            _tx_user("Context: the run under discussion is --run-dir '%s'.\n"
                     "```bash\n%s record --run-dir '%s' --job-id 'job-alpha' "
                     "--repo-root '/repo'\n```" % (run_dir, _EMIT, other_run)),
            _tx_assistant("msg_L1", 444, 444, 444, 444,
                          "2026-09-04T21:00:00.000Z", 0),
        ])
        # MALFORMED, NOT DOUBLE-COUNTED: two streamed snapshots of one message
        # with NO message.id at all (round-2 review, NEW 3). Both are refused,
        # so this transcript contributes nothing but two malformed lines — and
        # job-alpha's totals below are unchanged by it.
        _write_transcript(os.path.join(tx, "agent-aaaa3.jsonl"), [
            _tx_user(prompt("record", "job-alpha")),
            _tx_assistant(None, 90, 100, 90, 90, "2026-09-04T22:00:00.000Z", 0),
            _tx_assistant(None, 90, 900, 90, 90, "2026-09-04T22:00:01.000Z", 1),
        ])

        # UNMATCHED (round-3, finding 1): TWO invocations on ONE line. The first
        # is wave-level, the second names a job. Seeing only the first command
        # and letting its argument parse run to end-of-line attributed the whole
        # line to `job-alpha`.
        _write_transcript(os.path.join(tx, "agent-mmmm1.jsonl"), [
            _tx_user("```bash\n%s finalize-wave --run-dir '%s' --jobs "
                     "'job-alpha'; %s record --run-dir '%s' --job-id "
                     "'job-alpha'\n```" % (_EMIT, run_dir, _EMIT, run_dir)),
            _tx_assistant("msg_M1", 222, 222, 222, 222,
                          "2026-09-04T23:00:00.000Z", 0),
        ])
        # UNMATCHED (round-3, finding 2): a NUL inside the command's --run-dir.
        # No path can hold one; the scan must refuse it, not die on it.
        _write_transcript(os.path.join(tx, "agent-nnnn1.jsonl"), [
            _tx_user("```bash\n%s record --run-dir '%s' --job-id 'job-alpha' "
                     "--repo-root '/repo'\n```"
                     % (_EMIT, run_dir[:-1] + chr(0) + run_dir[-1:])),
            _tx_assistant("msg_N1", 111, 111, 111, 111,
                          "2026-09-05T00:00:00.000Z", 0),
        ])

        job_ids_expected = ["job-alpha", "job-beta", "job-epsilon",
                            "job-gamma", "job-zeta"]

        rep = extract_workflow_usage(run_dir, tx)
        check("wf.run_id", rep["run_id"], "2026-09-04-selftest-run")
        check("wf.scanned", rep["scanned"], 19)
        # cccc1 (other run) + eeee1 (other checkout, same run id) + gggg1 (two
        # job ids) + hhhh1 (rejected id) + iiii1 (not a transcript) + kkkk1
        # (unresolvable relative run dir) + llll1 (prose run dir, other command)
        # + mmmm1 (two invocations on one line) + nnnn1 (NUL in the run dir).
        check("wf.unmatched", rep["unmatched"], 9)
        # aaaa1: "{ this line is not json", the invalid-UTF-8 tail, and the
        # 1200-deep line. aaaa3: two id-less usage records.
        check("wf.malformed_lines", rep["malformed_lines"], 5)
        check("wf.unmeasured", rep["unmeasured"], ["job-gamma"])
        check("wf.unreadable_transcripts", rep["unreadable_transcripts"], 1)

        # --- FINDING 1: an unsafe job id is refused, named, and never written -
        check("wf.rejected_jobs", rep["rejected_jobs"],
              sorted([victim_abs, escape_rel]))
        check("wf.rejected_not_a_job", victim_abs in rep["jobs"], False)
        check("wf.escape_not_a_job", escape_rel in rep["jobs"], False)
        check("wf.jobs_are_only_the_safe_ones", sorted(rep["jobs"]),
              job_ids_expected)
        # The containment gate on its own, independent of the name gate: a
        # results entry that is a SYMLINK out of the run is refused too.
        outside = os.path.join(tmp, "outside.json")
        with open(outside, "w", encoding="utf-8") as fh:
            fh.write("{}\n")
        os.symlink(outside, os.path.join(results, "job-symlink.json"))
        check("wf.path.safe_job", _results_path(run_dir, "job-alpha"),
              os.path.join(os.path.realpath(results), "job-alpha.json"))
        check("wf.path.absolute_id", _results_path(run_dir, victim_abs), None)
        check("wf.path.parent_walk", _results_path(run_dir, escape_rel), None)
        check("wf.path.leading_dot", _results_path(run_dir, ".hidden"), None)
        check("wf.path.symlink_out", _results_path(run_dir, "job-symlink"), None)
        os.unlink(os.path.join(results, "job-symlink.json"))

        # --- FINDING 2: canonical run-dir equality, no basename fallback ------
        check("wf.other_checkout_unmatched",
              classify_transcript(
                  "%s gate-receipt --run-dir '%s' --job-id 'job-alpha'"
                  % (_EMIT, other_repo_run), os.path.realpath(run_dir),
                  set(job_ids_expected)), ("other", None))
        check("wf.relative_with_repo_root",
              _canonical_run_dir("docs/superpowers/execution/"
                                 "2026-09-04-selftest-run", tmp),
              os.path.realpath(run_dir))
        check("wf.relative_without_base",
              _canonical_run_dir("docs/superpowers/execution/x", None), None)

        # --- FINDING 3: the prose sentence is not a key ----------------------
        check("wf.prose_only_is_run_level",
              classify_transcript(
                  "Please review Compound V job `job-beta`.\n%s "
                  "finalize-wave --run-dir '%s'" % (_EMIT, run_dir),
                  os.path.realpath(run_dir), set(job_ids_expected)),
              ("run", None))
        check("wf.two_job_ids_unmatched",
              classify_transcript(
                  "%s record --run-dir '%s' --job-id 'job-alpha' "
                  "--job-id 'job-beta'" % (_EMIT, run_dir),
                  os.path.realpath(run_dir), set(job_ids_expected)),
              ("other", None))

        # --- ROUND 2, STILL OPEN: only the COMMAND identifies the job --------
        _run_real = os.path.realpath(run_dir)
        check("wf.prose_run_dir_never_matches",
              classify_transcript(
                  "The run is --run-dir '%s'.\n%s record --run-dir '%s' "
                  "--job-id 'job-alpha' --repo-root '/repo'"
                  % (run_dir, _EMIT, other_run), _run_real,
                  set(job_ids_expected)), ("other", None))
        check("wf.no_command_never_matches",
              classify_transcript(
                  "Have a look at --run-dir '%s' --job-id 'job-alpha'."
                  % run_dir, _run_real, set(job_ids_expected)),
              ("other", None))
        check("wf.two_commands_unmatched",
              classify_transcript(
                  "%s record --run-dir '%s' --job-id 'job-alpha' "
                  "--repo-root '/repo'\n%s record --run-dir '%s' "
                  "--job-id 'job-beta' --repo-root '/repo'"
                  % (_EMIT, run_dir, _EMIT, run_dir), _run_real,
                  set(job_ids_expected)), ("other", None))
        # A `--run-dir` INSIDE a quoted argument is a string, not a flag. This
        # is why the command is tokenized rather than regex-scanned.
        check("wf.embedded_flag_in_quoted_value",
              classify_transcript(
                  "%s record --run-dir '%s' --job-id 'job-alpha' "
                  "--verdict-json '{\"cmd\": \"--run-dir /elsewhere\"}'"
                  % (_EMIT, run_dir), _run_real, set(job_ids_expected)),
              ("job", "job-alpha"))
        # A prose word after the emitter path is not a subcommand.
        check("wf.prose_after_emitter_is_not_a_command",
              classify_transcript(
                  "%s and the gate both read --run-dir '%s' --job-id "
                  "'job-alpha'" % (_EMIT, run_dir), _run_real,
                  set(job_ids_expected)), ("other", None))
        # A backslash-continued command is one command.
        check("wf.continued_command",
              classify_transcript(
                  "%s record \\\n  --run-dir '%s' \\\n  --job-id 'job-alpha'"
                  % (_EMIT, run_dir), _run_real, set(job_ids_expected)),
              ("job", "job-alpha"))

        # --- ROUND 3, finding 1: EVERY invocation on a line is a command -----
        _two_on_one = ("%s finalize-wave --run-dir '%s' --jobs 'job-alpha'; "
                       "%s record --run-dir '%s' --job-id 'job-alpha'"
                       % (_EMIT, run_dir, _EMIT, run_dir))
        check("wf.line_holds_two_commands", len(stage_commands(_two_on_one)), 2)
        check("wf.second_command_args_not_swallowed",
              stage_commands(_two_on_one)[0]["--job-id"], [])
        check("wf.wave_plus_job_on_one_line_unmatched",
              classify_transcript(_two_on_one, _run_real,
                                  set(job_ids_expected)), ("other", None))
        # The same mix across two LINES is refused by the same rule.
        check("wf.wave_plus_job_on_two_lines_unmatched",
              classify_transcript(
                  "%s finalize-wave --run-dir '%s' --jobs 'job-alpha'\n"
                  "%s record --run-dir '%s' --job-id 'job-alpha'"
                  % (_EMIT, run_dir, _EMIT, run_dir), _run_real,
                  set(job_ids_expected)), ("other", None))
        # ...while a single invocation on its own line is still a command.
        check("wf.single_command_still_matches",
              classify_transcript(
                  "%s record --run-dir '%s' --job-id 'job-alpha'"
                  % (_EMIT, run_dir), _run_real, set(job_ids_expected)),
              ("job", "job-alpha"))

        # --- ROUND 3, finding 2: a NUL must be refused, never raise ----------
        _nul = chr(0)
        check("wf.canonical_nul_path_is_refused",
              _canonical_run_dir("/tmp/a" + _nul + "b", None), None)
        check("wf.canonical_nul_base_is_refused",
              _canonical_run_dir("relative/path", "/tmp/a" + _nul + "b"), None)
        check("wf.classify_nul_run_dir_unmatched",
              classify_transcript(
                  "%s record --run-dir '%s' --job-id 'job-alpha' "
                  "--repo-root '/repo'"
                  % (_EMIT, run_dir[:-1] + _nul + run_dir[-1:]), _run_real,
                  set(job_ids_expected)), ("other", None))

        # --- ROUND 3, finding 3: results/ is anchored on the RUN -------------
        _sym_run = os.path.join(tmp, "symlinked-results-run")
        os.makedirs(_sym_run)
        _victim_results = os.path.join(tmp, "victim-results")
        os.makedirs(_victim_results)
        with open(os.path.join(_victim_results, "job-alpha.json"), "w",
                  encoding="utf-8") as fh:
            fh.write('{"victim": "untouched"}\n')
        os.symlink(_victim_results, os.path.join(_sym_run, "results"))
        check("wf.results_root.symlinked_dir_refused",
              results_root(_sym_run), None)
        check("wf.results_root.no_job_ids_read_through_it",
              _results_job_ids(_sym_run), [])
        check("wf.results_root.no_write_path_through_it",
              _results_path(_sym_run, "job-alpha"), None)
        check("wf.results_root.honest_root_accepted",
              results_root(run_dir), os.path.realpath(results))
        check("wf.results_root.missing_run_refused",
              results_root(os.path.join(tmp, "no-such-run")), None)
        # ...and --write through that run touches nothing.
        _sym_rep = extract_workflow_usage(_sym_run, tx)
        check("wf.results_root.reported_refused",
              _sym_rep["results_refused"], True)
        check("wf.results_root.report_line",
              "results_refused:" in format_workflow_report(_sym_rep), True)
        write_workflow_usage(_sym_run, rep)
        with open(os.path.join(_victim_results, "job-alpha.json"),
                  encoding="utf-8") as fh:
            check("wf.results_root.victim_untouched", fh.read(),
                  '{"victim": "untouched"}\n')

        # --- ROUND 2, NEW 2: the snapshot winner is chosen by ORDER ----------
        _ts = "2026-09-04T09:00:0%d.000Z"
        newer = (_parse_timestamp(_ts % 9), 0)
        older = (_parse_timestamp(_ts % 1), 0)
        vals_new = {"input_tokens": 5, "output_tokens": 42,
                    "cache_read_input_tokens": 6,
                    "cache_creation_input_tokens": 7}
        vals_old = {"input_tokens": 5, "output_tokens": 999,
                    "cache_read_input_tokens": 6,
                    "cache_creation_input_tokens": 7}
        check("wf.pick.by_timestamp_not_file_order",
              _pick_snapshot([(newer, vals_new), (older, vals_old)]), vals_new)
        # No usable order key: monotonic fallback takes the max output...
        check("wf.pick.fallback_max_output",
              _pick_snapshot([(None, vals_new), (None, vals_old)])["output_tokens"],
              999)
        # ...but contradictory invariants are refused, not maximised.
        vals_bad = dict(vals_old)
        vals_bad["cache_read_input_tokens"] = 60
        check("wf.pick.fallback_invariant_disagreement",
              _pick_snapshot([(None, vals_new), (None, vals_bad)]), None)

        a = rep["jobs"]["job-alpha"]
        # msg_A1 counted ONCE at its LAST snapshot (40, not 5+40), + A2 + A3.
        # These also carry findings 5 and NEW 3/4: an invalid-UTF-8 line, a
        # 1200-deep line and two id-less records sit in job-alpha's transcripts,
        # and every one of them must contribute exactly nothing.
        check("wf.alpha.input", a["input_tokens"], 10 + 3 + 1)
        check("wf.alpha.output", a["output_tokens"], 40 + 7 + 2)
        check("wf.alpha.cache_read", a["cache_read_input_tokens"], 100 + 300 + 4)
        check("wf.alpha.cache_create", a["cache_creation_input_tokens"], 200 + 0 + 8)
        check("wf.alpha.measured", a["measured"], True)
        check("wf.alpha.source", a["source"], WORKFLOW_TRANSCRIPT_SOURCE)
        check("wf.alpha.backend", a["backend"], "claude")
        check("wf.alpha.transcripts", a["transcripts"],
              ["agent-aaaa1.jsonl", "agent-aaaa2.jsonl", "agent-aaaa3.jsonl"])

        # --- FINDING 4: msg_B1 appears in BOTH of job-beta's transcripts ------
        b = rep["jobs"]["job-beta"]
        check("wf.beta.input", b["input_tokens"], 1000 + 1)
        check("wf.beta.output", b["output_tokens"], 700 + 1)
        check("wf.beta.cache_read", b["cache_read_input_tokens"], 20 + 1)
        check("wf.beta.cache_create", b["cache_creation_input_tokens"], 30 + 1)
        check("wf.beta.transcripts", b["transcripts"],
              ["agent-bbbb1.jsonl", "agent-bbbb2.jsonl"])

        # --- NEW 2 end to end: the lexically later file holds the OLDER read --
        z = rep["jobs"]["job-zeta"]
        check("wf.zeta.output_is_the_newer_snapshot", z["output_tokens"], 42)
        check("wf.zeta.input", z["input_tokens"], 5)
        check("wf.zeta.transcripts", z["transcripts"],
              ["agent-zzzz1.jsonl", "agent-zzzz2.jsonl"])

        # job-epsilon proves the relative-run-dir rule end to end.
        e = rep["jobs"]["job-epsilon"]
        check("wf.epsilon.input", e["input_tokens"], 2)
        check("wf.epsilon.output", e["output_tokens"], 4)
        check("wf.epsilon.transcripts", e["transcripts"], ["agent-jjjj1.jsonl"])

        g = rep["jobs"]["job-gamma"]
        check("wf.gamma.measured", g["measured"], False)
        check("wf.gamma.input", g["input_tokens"], None)
        check("wf.gamma.output", g["output_tokens"], None)
        check("wf.gamma.transcripts", g["transcripts"], [])

        rl = rep["run_level"]
        check("wf.run_level.present", isinstance(rl, dict), True)
        check("wf.run_level.input", rl["input_tokens"], 7 + 5)
        check("wf.run_level.output", rl["output_tokens"], 9 + 6)
        check("wf.run_level.transcripts", rl["transcripts"],
              ["agent-dddd1.jsonl", "agent-ffff1.jsonl"])

        # The report's job lines, and that an unmeasured job prints a dash.
        text = format_workflow_report(rep)
        check("wf.report.alpha_line",
              "job-alpha input=14 output=49 cache_read=404 cache_create=208 "
              "transcripts=3" in text, True)
        _d = _fmt_tok(None)
        check("wf.report.gamma_dash",
              "job-gamma input=%s output=%s cache_read=%s cache_create=%s "
              "transcripts=0" % (_d, _d, _d, _d) in text, True)
        # Whatever the dash is, it is NEVER a zero: that is the whole point.
        check("wf.report.gamma_not_zero", "job-gamma input=0" in text, False)
        check("wf.report.unmeasured", "unmeasured: job-gamma" in text, True)
        check("wf.report.unmatched", "unmatched: 9" in text, True)
        check("wf.report.unreadable",
              "unreadable_transcripts: 1" in text, True)
        check("wf.report.rejected",
              "rejected_jobs (unsafe id, never written): " in text, True)
        check("wf.report.beta_line",
              "job-beta input=1001 output=701 cache_read=21 cache_create=31 "
              "transcripts=2" in text, True)

        # --- --write, and that a SECOND write does not double-count ----------
        # NEW 1: a symlink pre-placed at the OLD predictable temp name. mkstemp
        # never uses that name, so the file it points at must survive.
        tmp_bait = os.path.join(results, "job-alpha.json.cv-usage-tmp")
        bait_target = os.path.join(tmp, "bait.json")
        with open(bait_target, "w", encoding="utf-8") as fh:
            fh.write('{"bait": "untouched"}\n')
        os.symlink(bait_target, tmp_bait)

        written = write_workflow_usage(run_dir, rep)
        check("wf.write.count", len(written), 4)   # gamma is untouched
        with open(bait_target, encoding="utf-8") as fh:
            check("wf.write.predictable_tmp_symlink_not_followed", fh.read(),
                  '{"bait": "untouched"}\n')
        check("wf.write.bait_symlink_survives", os.path.islink(tmp_bait), True)
        os.unlink(tmp_bait)
        # ...and no stray temp file was left behind in results/.
        check("wf.write.no_stray_temp",
              [n for n in os.listdir(results) if n.startswith(".cv-usage-")], [])
        # FINDING 1, the outcome that matters: nothing was written outside the
        # run directory, by either hostile id.
        for label, sentinel in (("absolute", victim_abs + ".json"),
                                ("parent_walk", escape_target)):
            with open(sentinel, encoding="utf-8") as fh:
                check("wf.write.no_%s_escape" % label, fh.read(),
                      '{"sentinel": "untouched"}\n')

        alpha_path = os.path.join(results, "job-alpha.json")
        gamma_path = os.path.join(results, "job-gamma.json")
        with open(alpha_path, encoding="utf-8") as fh:
            first_text = fh.read()
        doc = json.loads(first_text)
        check("wf.write.alpha_usage_in", doc["usage"]["input_tokens"], 14)
        check("wf.write.alpha_usage_out", doc["usage"]["output_tokens"], 49)
        check("wf.write.alpha_measured", doc["usage"]["measured"], True)
        check("wf.write.preserved_status", doc["status"], "success")
        with open(gamma_path, encoding="utf-8") as fh:
            gamma_doc = json.load(fh)
        check("wf.write.gamma_untouched", "usage" in gamma_doc, False)

        # NEW 1, the other half: a RESULT file that is itself a symlink is
        # refused outright, so the bytes never reach what it points at.
        link_target = os.path.join(tmp, "linked-result.json")
        with open(link_target, "w", encoding="utf-8") as fh:
            fh.write('{"linked": "untouched"}\n')
        os.unlink(alpha_path)
        os.symlink(link_target, alpha_path)
        write_workflow_usage(run_dir, rep)
        with open(link_target, encoding="utf-8") as fh:
            check("wf.write.symlinked_result_refused", fh.read(),
                  '{"linked": "untouched"}\n')
        os.unlink(alpha_path)
        with open(alpha_path, "w", encoding="utf-8") as fh:
            fh.write(first_text)

        rep2 = extract_workflow_usage(run_dir, tx)
        write_workflow_usage(run_dir, rep2)
        with open(alpha_path, encoding="utf-8") as fh:
            second_text = fh.read()
        check("wf.write.idempotent_bytes", second_text, first_text)
        check("wf.write.idempotent_input",
              json.loads(second_text)["usage"]["input_tokens"], 14)

        # --- the written `usage` must satisfy the SHIPPED sub-schema ---------
        # A structural check, not a jsonschema import: this script is stdlib-only
        # (CONVENTIONS.md), and `usage` is additionalProperties:false, so a key
        # we invent here would break every consumer that validates.
        # tests/test-usage-workflow.sh runs the full jsonschema validation.
        schema_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "..", "schemas", "job_result.schema.json")
        try:
            with open(schema_path, encoding="utf-8") as fh:
                usage_schema = json.load(fh)["properties"]["usage"]
        except (OSError, ValueError, KeyError):
            usage_schema = None
        check("wf.schema.readable", usage_schema is not None, True)
        if usage_schema is not None:
            declared = set(usage_schema.get("properties", {}))
            check("wf.schema.no_undeclared_keys",
                  sorted(set(doc["usage"]) - declared), [])
            check("wf.schema.additional_false",
                  usage_schema.get("additionalProperties"), False)
            src = usage_schema.get("properties", {}).get("source", {})
            check("wf.schema.source_enum_has_transcript",
                  WORKFLOW_TRANSCRIPT_SOURCE in (src.get("enum") or []), True)

        # --- the aggregator reads the new source with UNCHANGED semantics ----
        agg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "compound-v-usage-aggregate.py")
        if os.path.isfile(agg_path):
            import importlib.util
            spec = importlib.util.spec_from_file_location("_cv_agg", agg_path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            agg = mod.aggregate(results)
            check("wf.agg.input", agg["totals"]["input_tokens"],
                  14 + 1001 + 2 + 5)
            check("wf.agg.output", agg["totals"]["output_tokens"],
                  49 + 701 + 4 + 42)
            check("wf.agg.measured_jobs", agg["totals"]["measured_jobs"], 4)
            check("wf.agg.unmeasured_jobs", agg["totals"]["unmeasured_jobs"], 1)

        # --- fixed-CLI plumbing: main() returns 2 for a missing dir/run ------
        # Their diagnostics go to stderr; swallow them so the selftest's own
        # output stays readable (the RETURN CODE is what is under test).
        real_err, real_out = sys.stderr, sys.stdout
        try:
            devnull = open(os.devnull, "w")
            sys.stderr = devnull
            sys.stdout = devnull
            rc_missing_tx = main(["--backend", "claude",
                                  "--workflow-transcript", os.path.join(tmp, "nope"),
                                  "--run-dir", run_dir])
            rc_missing_run = main(["--backend", "claude",
                                   "--workflow-transcript", tx,
                                   "--run-dir", os.path.join(tmp, "no-such-run")])
            rc_backend = main(["--backend", "codex", "--workflow-transcript", tx,
                               "--run-dir", run_dir])
            rc_ok = main(["--backend", "claude", "--workflow-transcript", tx,
                          "--run-dir", run_dir])
        finally:
            sys.stderr, sys.stdout = real_err, real_out
            devnull.close()
        check("wf.main.missing_transcript_dir", rc_missing_tx, 2)
        check("wf.main.missing_run_dir", rc_missing_run, 2)
        check("wf.main.wrong_backend", rc_backend, 1)
        check("wf.main.dry_run_ok", rc_ok, 0)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Extract a canonical, measured-only `usage` object — from a "
                    "backend's structured events log (--events-log), or, for an "
                    "Engine C run, from its jobs' Claude Code subagent "
                    "transcripts (--workflow-transcript + --run-dir)."
    )
    p.add_argument("--backend", help="Backend name (codex|opencode|cursor|agy|"
                                     "antigravity|claude)")
    p.add_argument("--events-log", help="Path to the backend's structured events log (JSONL)")
    p.add_argument("--workflow-transcript",
                   help="Engine C mode: directory to scan RECURSIVELY for "
                        "Claude Code subagent transcripts (agent-*.jsonl), e.g. "
                        "~/.claude/projects/<project-slug>/<session-uuid>/subagents")
    p.add_argument("--run-dir",
                   help="Run directory (docs/superpowers/execution/<run-id>) "
                        "whose jobs the transcripts are matched against; with "
                        "--write, the directory whose results/*.json are updated")
    p.add_argument("--write", action="store_true",
                   help="Merge the measured `usage` object into "
                        "<run-dir>/results/<job>.json (idempotent)")
    p.add_argument("--format", choices=("text", "json"), default="text",
                   help="Engine C mode output format (default: text)")
    p.add_argument("--selftest", action="store_true",
                   help="Run inline fixtures and exit 0 on success, non-zero on failure")
    return p.parse_args(argv)


def _main_workflow(args: argparse.Namespace) -> int:
    """Engine C mode: --workflow-transcript + --run-dir."""
    backend = (args.backend or "claude").strip()
    if backend != "claude":
        sys.stderr.write(
            "error: --workflow-transcript reads Claude Code subagent "
            "transcripts; --backend must be `claude` (got %r)\n" % backend)
        return 1
    if not args.run_dir:
        sys.stderr.write("error: --workflow-transcript requires --run-dir\n")
        return 1
    root = os.path.expanduser(args.workflow_transcript)
    if not os.path.isdir(root):
        sys.stderr.write("error: transcript dir not found: %s\n" % root)
        return 2
    run_dir = os.path.expanduser(args.run_dir)
    if not os.path.isdir(run_dir):
        sys.stderr.write("error: run dir not found: %s\n" % run_dir)
        return 2

    report = extract_workflow_usage(run_dir, root, backend)
    if args.write:
        written = write_workflow_usage(run_dir, report)
        report["written"] = written
    if args.format == "json":
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(format_workflow_report(report) + "\n")
        if args.write:
            for path in report.get("written", []):
                sys.stdout.write("wrote: %s\n" % path)
    return 0


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    if args.selftest:
        return _selftest()
    if args.workflow_transcript:
        return _main_workflow(args)
    if not args.backend:
        sys.stderr.write("error: --backend is required (or use --selftest)\n")
        return 1
    usage = extract_usage(args.backend, args.events_log)
    sys.stdout.write(json.dumps(usage, indent=2, sort_keys=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
