#!/usr/bin/env python3
"""
Compound V result collector.

Normalizes one job's heterogeneous worker output into the canonical
`job_result` shape (schemas/job_result.schema.json) and writes it to
`<run-dir>/results/<job-id>.json`.

Design contract (PRD §4.2 #6, plan §3 / §4 Q6):

  - The ENFORCEMENT fields (`blocked`, `files_changed`, `violations`, `status`,
    `exit_code`) are GIT-DERIVED by the caller's scope gate, never self-reported
    by the worker model. This script folds the scope verdict in; it does not
    re-derive it from a model's claims. When a scope verdict is present, the
    `--blocked` / `--violations` / `--files-changed` flags are ADDITIVE-ONLY —
    they may force a block or add entries, but may NEVER clear a scope-gate block
    or drop a scope violation (the deterministic gate stays the authority).
  - The worker's free-text output (codex `--output-last-message`, or a Claude
    subagent's returned text) feeds ONLY the human `summary`. If that text is
    itself JSON matching the schema, its `summary`/`session_id`/`worktree` may
    be read, but its enforcement fields are IGNORED in favor of the scope verdict.
  - NO fabricated cost / token metrics. The schema has no cost field and this
    script never invents one (anti-ruflo charter, plan §7).
  - `usage.advisor_calls` is SCRIPT-DERIVED (like the git-derived enforcement
    fields), never worker-self-reported: it is the non-empty line count of the
    conventional per-job advisor log `<run-dir>/logs/<job-id>.advisor.jsonl`
    (appended one line per consult by compound-v-advisor-consult.sh). Present log
    ⇒ set/overwrite advisor_calls to the count; absent/empty ⇒ leave it null
    (fail-open, never fabricate). When the worker emitted no usage but a count was
    derived, a minimal usage object {input_tokens:null, output_tokens:null,
    advisor_calls:<count>, backend:<--backend>, measured:false} is synthesized.

Inputs (all paths absolute or run-dir-relative):

  --job-id      ID of the job (names the output file).
  --run-dir     Execution run directory; output goes to <run-dir>/results/<id>.json
                (overridable with --out).
  --scope       Path to the scope-gate verdict JSON (git-derived). Recognized keys:
                blocked, files_changed, violations, exit_code, session_id, worktree,
                status, timed_out. Any subset may be present. This is AUTHORITATIVE
                for the enforcement fields. For interop with
                scripts/compound-v-scope-check.py, the native verdict keys
                `verdict` ("pass"|"blocked") and `changed` are also accepted as
                aliases for `blocked` and `files_changed`.
  --worker-output
                Path to the worker's last-message text (codex .job_result.txt) or a
                Claude subagent summary. Used for `summary` only (and session_id/
                worktree if the scope verdict omits them and the text is schema JSON).
  --out         Explicit output path (default <run-dir>/results/<job-id>.json).
  --schema      Path to job_result.schema.json for a post-write conformance check
                (default: ../schemas/job_result.schema.json next to this script).

Scope-verdict and individual fields may also be supplied directly:
  --blocked / --no-blocked, --status, --exit-code, --session-id, --worktree
  --files-changed a,b,c   --violations a,b   (comma-separated)

ENFORCEMENT flags are ADDITIVE-ONLY when a --scope verdict is present. The
git-derived scope verdict is authoritative and can never be weakened by a flag:
  - blocked      = scope_blocked OR flag   (a flag may FORCE a block; --no-blocked
                   can NOT clear a scope-gate block)
  - violations   = union(scope, flag)      (a flag may ADD violations; it can NOT
                   remove a scope violation)
  - files_changed= union(scope, flag)      (additive)
When NO scope verdict is present, the direct flags supply the values outright.
Informational fields (status/session_id/worktree/summary/exit_code) still follow
the override order: direct flag > scope file > worker-output > default.

Python 3.9-safe, stdlib only. Exit 0 on a written + schema-valid result; exit 1
on a usage error or schema-conformance failure.
"""

import argparse
import bisect
import collections
import json
import os
import re
import shutil
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple

STATUS_VALUES = ("success", "blocked", "timeout", "error")

# A --job-id becomes the output filename (<run-dir>/results/<id>.json), so a
# `.`/`..`/`/` in it is a path-traversal vector. Restrict to the same safe
# allow-list the worker and validator enforce on ids.
_JOB_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _job_id_is_safe(value: str) -> bool:
    if value in (".", ".."):
        return False
    return _JOB_ID_RE.match(value) is not None


def _read_json(path: str) -> Optional[Any]:
    """Read a JSON file; return None if absent or unparseable."""
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r") as fh:
            return json.load(fh)
    except (ValueError, OSError):
        return None


def _read_text(path: str) -> str:
    if not path or not os.path.exists(path):
        return ""
    try:
        with open(path, "r") as fh:
            return fh.read()
    except OSError:
        return ""


def _as_str_list(val: Any) -> List[str]:
    if val is None:
        return []
    if isinstance(val, str):
        # comma-separated convenience form
        return [p.strip() for p in val.split(",") if p.strip()]
    if isinstance(val, (list, tuple)):
        out = []  # type: List[str]
        for item in val:
            if item is None:
                continue
            out.append(str(item))
        return out
    return [str(val)]


def _union_preserve_order(primary: List[str], extra: List[str]) -> List[str]:
    """Union of two string lists, primary order first, de-duplicated.

    Used for the additive-only fold of scope (primary) + flag (extra) lists, so a
    flag can ADD entries but the scope-derived entries are always retained.
    """
    out = []  # type: List[str]
    seen = set()  # type: set
    for item in list(primary) + list(extra):
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _advisor_log_path(run_dir: Optional[str], job_id: str) -> Optional[str]:
    """Conventional per-job advisor log: <run-dir>/logs/<job-id>.advisor.jsonl.

    Mirrors the results/<id>.json convention the collector already uses to locate
    output, so run-dir + job-id fully determine the log path. Returns None when no
    run-dir is known (e.g. --out was given without --run-dir).
    """
    if not run_dir:
        return None
    return os.path.join(run_dir, "logs", "%s.advisor.jsonl" % job_id)


def _count_advisor_calls(run_dir: Optional[str], job_id: str) -> Optional[int]:
    """Script-DERIVED advisor-consult count from the per-job advisor JSONL log.

    `compound-v-advisor-consult.sh` appends one JSON line per consult to
    <run-dir>/logs/<job-id>.advisor.jsonl. We count its non-empty lines — an
    honest, git/log-derived number (like the enforcement fields), never
    self-reported by the worker. Fail-open: a missing/unreadable/empty log yields
    None so advisor_calls stays null (never fabricate a count).
    """
    path = _advisor_log_path(run_dir, job_id)
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r") as fh:
            lines = fh.readlines()
    except OSError:
        return None
    count = 0
    for line in lines:
        if line.strip():
            count += 1
    return count if count > 0 else None


def _coerce_summary(worker_text: str) -> str:
    """
    Extract a human summary from the worker's last-message text. If the text is
    JSON with a `summary` key, use that; otherwise use the trimmed raw text.
    Enforcement fields inside the JSON are deliberately NOT read here.
    """
    worker_text = (worker_text or "").strip()
    if not worker_text:
        return ""
    if worker_text[0] in "{[":
        try:
            obj = json.loads(worker_text)
            if isinstance(obj, dict) and isinstance(obj.get("summary"), str):
                return obj["summary"].strip()
        except ValueError:
            pass
    return worker_text


def _worker_json(worker_text: str) -> Dict[str, Any]:
    """If worker text is a JSON object, return it; else {}."""
    worker_text = (worker_text or "").strip()
    if worker_text[:1] == "{":
        try:
            obj = json.loads(worker_text)
            if isinstance(obj, dict):
                return obj
        except ValueError:
            pass
    return {}


def _derive_status(blocked: bool, exit_code: int, scope_status: Optional[str],
                   timed_out: bool) -> str:
    """
    Status is derived, never trusted from the model. Precedence:
      blocked verdict  -> blocked
      explicit valid scope status -> honored (lets the gate force timeout/error)
      timed_out flag or exit 124 -> timeout
      exit_code != 0   -> error
      else             -> success
    """
    if blocked:
        return "blocked"
    if scope_status in STATUS_VALUES:
        return scope_status
    if timed_out or exit_code == 124:
        return "timeout"
    if exit_code != 0:
        return "error"
    return "success"


def build_result(args: argparse.Namespace) -> Dict[str, Any]:
    scope = _read_json(args.scope) if args.scope else None
    if not isinstance(scope, dict):
        scope = {}
    worker_text = _read_text(args.worker_output) if args.worker_output else ""
    wjson = _worker_json(worker_text)

    # --- enforcement fields: scope verdict is authoritative ---------------
    # Accept both this collector's native key names and the scope-check.py
    # verdict shape ({"verdict","changed","violations"}) as aliases.
    #
    # ADDITIVE-ONLY RULE: when a scope verdict is present, the --files-changed /
    # --violations / --blocked flags may only ADD to (never replace or clear) the
    # git-derived verdict. A flag can FORCE blocked=true or ADD violations/files,
    # but can NEVER clear a scope-gate block or drop a scope violation. This keeps
    # the deterministic gate the authority; flags are an annotation layer on top.
    have_scope = bool(scope)

    scope_files = _as_str_list(
        scope["files_changed"] if "files_changed" in scope else scope.get("changed")
    )
    flag_files = _as_str_list(args.files_changed) if args.files_changed is not None else []
    if have_scope:
        files_changed = _union_preserve_order(scope_files, flag_files)
    elif args.files_changed is not None:
        files_changed = flag_files
    else:
        files_changed = scope_files

    scope_violations = _as_str_list(scope.get("violations"))
    flag_violations = _as_str_list(args.violations) if args.violations is not None else []
    if have_scope:
        violations = _union_preserve_order(scope_violations, flag_violations)
    elif args.violations is not None:
        violations = flag_violations
    else:
        violations = scope_violations

    # blocked: any violation => blocked; a scope verdict can force it; a flag may
    # ADD a block but may NEVER clear a scope block (additive-only).
    scope_blocked = bool(scope.get("blocked", False)) or scope.get("verdict") == "blocked"
    blocked = scope_blocked or bool(violations)
    if args.blocked is not None:
        # --no-blocked sets args.blocked False; it must NOT override a scope block.
        blocked = blocked or bool(args.blocked)

    exit_code = scope.get("exit_code")
    if args.exit_code is not None:
        exit_code = args.exit_code
    if not isinstance(exit_code, int):
        try:
            exit_code = int(exit_code)
        except (TypeError, ValueError):
            exit_code = 0

    timed_out = bool(scope.get("timed_out", False))

    scope_status = scope.get("status")
    if args.status is not None:
        scope_status = args.status
    status = _derive_status(blocked, exit_code, scope_status, timed_out)

    # --- informational fields: worker text may inform, scope/flags win ----
    session_id = scope.get("session_id")
    if not session_id and isinstance(wjson.get("session_id"), str):
        session_id = wjson["session_id"]
    if args.session_id is not None:
        session_id = args.session_id
    session_id = "" if session_id is None else str(session_id)

    worktree = scope.get("worktree")
    if not worktree and isinstance(wjson.get("worktree"), str):
        worktree = wjson["worktree"]
    if args.worktree is not None:
        worktree = args.worktree
    worktree = "" if worktree is None else str(worktree)

    summary = _coerce_summary(worker_text)
    if not summary and isinstance(scope.get("summary"), str):
        summary = scope["summary"].strip()
    if args.summary is not None:
        summary = args.summary

    # Backend-failure classification. The codex worker emits these directly; for the
    # claude/direct path the dispatcher passes them in (from compound-v-classify-failure.py).
    # A successful job never carries a failure class. These are REQUIRED by the schema, so
    # the normalized result for EVERY backend must include them.
    failure_class = args.failure_class or None
    retry_after_seconds = args.retry_after_seconds or 0
    if status == "success":
        failure_class = None
        retry_after_seconds = 0

    result = {
        "status": status,
        "blocked": blocked,
        "files_changed": files_changed,
        "violations": violations,
        "summary": summary,
        "session_id": session_id,
        "worktree": worktree,
        "exit_code": exit_code,
        "failure_class": failure_class,
        "retry_after_seconds": retry_after_seconds,
    }  # type: Dict[str, Any]

    # OPTIONAL `usage` passthrough (informational / measured-only, worker-sourced
    # like `summary`). The usage object is extracted from the backend's own
    # structured events by compound-v-usage-extract.py and folded into the worker
    # JSON. It is NOT enforcement data and NEVER fabricated here.
    worker_usage = wjson.get("usage")
    usage = dict(worker_usage) if isinstance(worker_usage, dict) else None

    # advisor_calls is SCRIPT-DERIVED, never worker-self-reported: count the
    # per-job advisor JSONL log (like the git-derived enforcement fields). A
    # worker-supplied advisor_calls is ALWAYS DISCARDED (round-2: a malicious /
    # buggy worker could otherwise inject e.g. advisor_calls:999 with no log and
    # have it survive). The derived value is the count when the log exists, else
    # None (missing/unreadable/no-run-dir => null, fail-open, never fabricated).
    advisor_calls = _count_advisor_calls(args.run_dir, args.job_id)
    if usage is not None:
        # Overwrite unconditionally, dropping any worker-reported count.
        usage["advisor_calls"] = advisor_calls
    elif advisor_calls is not None:
        # No worker usage, but a real derived count: synthesize a minimal object.
        usage = {
            "input_tokens": None,
            "output_tokens": None,
            "advisor_calls": advisor_calls,
            "backend": args.backend or "",
            "measured": False,
        }

    # Include `usage` ONLY when the worker provided one OR we derived advisor_calls;
    # when neither, omit it entirely (usage is optional in the schema, so omission
    # stays conformant).
    if isinstance(usage, dict):
        result["usage"] = usage

    return result


# --------------------------------------------------------------------------
# Minimal, dependency-free conformance check against job_result.schema.json.
# Validates exactly the constraints this script must honor: required keys,
# additionalProperties:false, types, and the status enum. Not a general
# JSON-Schema engine — just enough to catch a malformed result.
# --------------------------------------------------------------------------
_TYPE_MAP = {
    "string": str,
    "boolean": bool,
    "integer": int,
    "array": list,
    "object": dict,
}


def _usage_conformance_errors(usage: Dict[str, Any],
                              usage_schema: Dict[str, Any]) -> List[str]:
    """TARGETED one-level check of the `usage` object against its sub-schema.

    The top-level checker only tests that `usage` is an object, so a bogus payload
    like {"bogus": 1} would slip through even though the real schema declares
    additionalProperties:false and five typed fields. This validates JUST the usage
    object (not a general recursive JSON-Schema engine): unknown keys are rejected,
    input_tokens/output_tokens/advisor_calls must be int-or-null, backend a string,
    measured a bool. Field types are read from the schema so they stay in sync.
    """
    errs = []  # type: List[str]
    if not isinstance(usage_schema, dict):
        return errs
    uprops = usage_schema.get("properties", {})
    uadditional = usage_schema.get("additionalProperties", True)

    if uadditional is False:
        for key in usage:
            if key not in uprops:
                errs.append(
                    "usage has unexpected key (additionalProperties:false): %s" % key
                )

    for key, spec in uprops.items():
        if key not in usage:
            continue
        want = spec.get("type")
        val = usage[key]
        want_list = want if isinstance(want, list) else ([want] if want else [])
        if val is None:
            if want_list and "null" not in want_list:
                errs.append("usage key %s must be %s, got null"
                            % (key, "/".join(want_list)))
            continue
        # bool is a subclass of int — reject a boolean for an int-only field.
        if "integer" in want_list and "boolean" not in want_list and isinstance(val, bool):
            errs.append("usage key %s must be integer, got boolean" % key)
            continue
        pytypes = tuple(_TYPE_MAP[t] for t in want_list if t in _TYPE_MAP)
        if pytypes and not isinstance(val, pytypes):
            errs.append("usage key %s must be %s, got %s"
                        % (key, "/".join(want_list), type(val).__name__))
    return errs


def _retries_conformance_errors(retries: List[Any],
                                 retries_schema: Dict[str, Any]) -> List[str]:
    """TARGETED one-level check of EACH `retries[]` item against its sub-schema.

    Same rationale as _usage_conformance_errors: the top-level loop only confirms
    `retries` is an array, so a bogus item like {"stage": "x", "bogus": 1} or one
    missing the required `stage` would slip through. This validates every item:
    unknown keys are rejected (additionalProperties:false), `stage` required as a
    string, `attempt` required as an integer >= 1 (a bool is not an integer here),
    and the optional job/wait_ms/escalated_from/model fields are type- and
    minimum-checked when present. Field types/required/minimum are read from the
    REAL items sub-schema so this stays in sync with job_result.schema.json.
    Errors name both the item's index and the offending key, per Task B.
    """
    errs = []  # type: List[str]
    if not isinstance(retries_schema, dict):
        return errs
    items_schema = retries_schema.get("items", {})
    if not isinstance(items_schema, dict):
        return errs
    iprops = items_schema.get("properties", {})
    iadditional = items_schema.get("additionalProperties", True)
    irequired = items_schema.get("required", [])

    for idx, item in enumerate(retries):
        if not isinstance(item, dict):
            errs.append("retries[%d] must be an object, got %s"
                        % (idx, type(item).__name__))
            continue

        for key in irequired:
            if key not in item:
                errs.append("retries[%d] missing required key: %s" % (idx, key))

        if iadditional is False:
            for key in item:
                if key not in iprops:
                    errs.append(
                        "retries[%d] has unexpected key "
                        "(additionalProperties:false): %s" % (idx, key)
                    )

        for key, spec in iprops.items():
            if key not in item:
                continue
            want = spec.get("type")
            val = item[key]
            want_list = want if isinstance(want, list) else ([want] if want else [])
            if val is None:
                if want_list and "null" not in want_list:
                    errs.append("retries[%d] key %s must be %s, got null"
                                % (idx, key, "/".join(want_list)))
                continue
            # bool is a subclass of int — reject a boolean for an int-only field
            # (this is exactly what catches a string/bool `attempt`).
            if "integer" in want_list and "boolean" not in want_list and isinstance(val, bool):
                errs.append("retries[%d] key %s must be integer, got boolean"
                            % (idx, key))
                continue
            pytypes = tuple(_TYPE_MAP[t] for t in want_list if t in _TYPE_MAP)
            if pytypes and not isinstance(val, pytypes):
                errs.append("retries[%d] key %s must be %s, got %s"
                            % (idx, key, "/".join(want_list), type(val).__name__))
                continue
            minimum = spec.get("minimum")
            if minimum is not None and isinstance(val, (int, float)) and val < minimum:
                errs.append("retries[%d] key %s must be >= %s, got %s"
                            % (idx, key, minimum, val))
    return errs


def conformance_errors(result: Dict[str, Any], schema_path: str) -> List[str]:
    errs = []  # type: List[str]
    schema = _read_json(schema_path)
    if not isinstance(schema, dict):
        # No schema to check against; treat as a soft skip, not a failure.
        return errs

    props = schema.get("properties", {})
    required = schema.get("required", [])
    additional = schema.get("additionalProperties", True)

    for key in required:
        if key not in result:
            errs.append("missing required key: %s" % key)

    if additional is False:
        for key in result:
            if key not in props:
                errs.append("unexpected key (additionalProperties:false): %s" % key)

    type_map = _TYPE_MAP
    for key, spec in props.items():
        if key not in result:
            continue
        want = spec.get("type")
        val = result[key]
        # `type` may be a single string OR a list (e.g. ["string","null"] for a nullable
        # field) — handle both. null is allowed only when "null" is among the listed types.
        want_list = want if isinstance(want, list) else ([want] if want else [])
        if val is None:
            if want_list and "null" not in want_list:
                errs.append("key %s must be %s, got null" % (key, "/".join(want_list)))
            continue
        # bool is a subclass of int — guard the integer case explicitly.
        if "integer" in want_list and "boolean" not in want_list and isinstance(val, bool):
            errs.append("key %s must be integer, got boolean" % key)
            continue
        pytypes = tuple(type_map[t] for t in want_list if t in type_map)
        if pytypes and not isinstance(val, pytypes):
            errs.append("key %s must be %s, got %s"
                        % (key, "/".join(want_list), type(val).__name__))
            continue
        if "array" in want_list:
            item_type = spec.get("items", {}).get("type")
            ipy = type_map.get(item_type)
            if ipy is not None:
                for el in val:
                    if not isinstance(el, ipy):
                        errs.append("key %s items must be %s" % (key, item_type))
                        break
        enum = spec.get("enum")
        if enum is not None and val not in enum:
            errs.append("key %s value %r not in enum %s" % (key, val, enum))

    # Deep-validate the `usage` object against its sub-schema. The top-level loop
    # only confirms usage is an object; without this a schema-INVALID usage payload
    # (unknown keys, wrong field types) would pass conformance.
    if isinstance(result.get("usage"), dict):
        errs.extend(_usage_conformance_errors(result["usage"], props.get("usage", {})))

    # Deep-validate `retries[]` the same way: the top-level loop only confirms
    # `retries` is an array, so a schema-INVALID item (unknown key, missing
    # `stage`, non-integer `attempt`) would otherwise pass conformance.
    if isinstance(result.get("retries"), list):
        errs.extend(_retries_conformance_errors(result["retries"], props.get("retries", {})))
    return errs


def _default_schema_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "schemas", "job_result.schema.json")


# --------------------------------------------------------------------------
# v2.17 — failure-prioritized, explicitly-lossy evidence packing.
#
# WHY: every truncator that feeds an external judge today is a TAIL-DROP
# (compound-v-epic-arbiter.py's `_bound_text` / `_cap_bytes_with_marker`), so it
# amputates exactly the traceback at the END of a log. `pack_evidence` keeps the
# FAILURE content instead and drops the filler.
#
# WHAT THIS IS NOT: it is NOT "bounded AND never drops a failure line" — those
# two are mutually impossible (failure lines alone can exceed any budget, and a
# log where every line starts with `ERROR` has no filler to drop). The guarantee
# is: **failure-prioritized, explicitly lossy, and always within the budget.**
#
# SECURITY ORDERING — NON-NEGOTIABLE: `sanitized_text` MUST already have been
# through the arbiter's `redact_uncapped()`. Packing BEFORE redaction is a real
# egress hole, not a style preference: dropping a private key's BEGIN/END lines
# (or a `password=` label line) destroys the multi-line structure `redact()`
# matches on, and a short secret then also evades the >=32-char opaque-token
# regex. Packing only DELETES whole lines from already-sanitized text, so it can
# never un-redact anything.
#
# DETERMINISM: the output is a function of the input. Every constant below is
# pinned by the spec rather than chosen here, because two implementations that
# retained different spans would elicit different judge VOTES.
# --------------------------------------------------------------------------

# `section_label` is a CLOSED ENUM, never free text — an arbitrary label could
# itself carry a filesystem path into the prompt.
EVIDENCE_SECTION_LABELS = (
    "job_stderr", "job_stdout", "test_output",
    "scope_gate", "review_notes", "diff_summary",
)

# Deliberately IDENTICAL to compound-v-epic-arbiter.py's TRUNC_MARKER: the
# marker vocabulary is reconciled with the existing dialect rather than becoming
# a third one. The arbiter's selftest asserts the two constants are equal.
TRUNC_MARKER = "\n...[TRUNCATED]"

# Omission markers are PATH-FREE by construction: a count of lines, never a file
# path and never a line range.
OMIT_MARKER_FMT = "[cv-omitted: %d lines]"

# Loss-hierarchy rung 6 (see pack_evidence).
BUDGET_EXHAUSTED_PLACEHOLDER = "[evidence omitted: budget exhausted]"
# Substituted by the CALLER when packing raises (never by pack_evidence itself).
PACKING_FAILED_PLACEHOLDER = "[evidence omitted: packing failed]"

# A matched line plus EXACTLY this many lines of context each side.
EVIDENCE_CONTEXT_RADIUS = 3

# A byte-truncated line must retain at least this much content, else the
# fragment is noise rather than evidence and the ladder descends instead.
MIN_TRUNC_CONTENT_BYTES = 80

# Rung 4 shrinks the header to this many bytes to free room for content. The
# header is short by construction, so this rung is narrow — it exists because
# the loss hierarchy is TOTAL and every rung must be reachable.
RUNG4_HEADER_MAX_BYTES = 10
_HEADER_ELLIPSIS = "..."

# Allocation probes the candidate length once per span, which is O(kept) per
# step. Pathological input (tens of thousands of 1-byte failure lines) would
# make that quadratic, so the walk stops after this many accepted spans. Any
# real budget is exhausted long before: 1000 spans inside a ~5 KB prompt budget
# means ~5-byte spans. The result stays a deterministic function of the input.
_ALLOC_MAX_ACCEPTED = 1000

# len(OMIT_MARKER_FMT % g) without paying for the string format on every probe.
_OMIT_MARKER_BASE_LEN = len(OMIT_MARKER_FMT % 0) - 1

# Priority ranks. Higher wins budget first.
_RANK_TRACEBACK = 4
_RANK_FAILED = 3
_RANK_ERROR = 2
_RANK_PANIC = 1
_RANK_OTHER = 0

# Failure matchers: case-insensitive, anchored at line start after leading
# whitespace. Evaluated highest-rank-first; the first match decides the rank.
_FAILURE_MATCHERS = tuple(
    (re.compile(r"[ \t]*" + re.escape(token), re.IGNORECASE), rank)
    for token, rank in (
        ("Traceback (most recent call last)", _RANK_TRACEBACK),
        ("FAILED", _RANK_FAILED),
        ("FAIL:", _RANK_FAILED),
        ("ERROR", _RANK_ERROR),
        ("Exception", _RANK_ERROR),
        ("panic:", _RANK_PANIC),
        ("fatal:", _RANK_PANIC),
        ("AssertionError", _RANK_OTHER),
        ("E   ", _RANK_OTHER),
    )
)

# text          : the packed evidence (byte-identical to the input at rung 0).
# rung          : which rung of the loss hierarchy was reached (0 = no loss).
# omit          : rung 7 — the CALLER must drop the evidence block entirely.
# original_bytes: the REAL pre-trim encoded size (never the post-trim size).
# packed_bytes  : encoded size of `text`; always <= budget_bytes when omit is False.
PackedEvidence = collections.namedtuple(
    "PackedEvidence", ["text", "rung", "omit", "original_bytes", "packed_bytes"])


def _blen(s: str) -> int:
    """Encoded (UTF-8) length. `errors="replace"` matches the arbiter's cap
    helper so byte accounting can never raise on a lone surrogate."""
    return len(s.encode("utf-8", errors="replace"))


def _cap_line_with_marker(s: str, max_bytes: int) -> Optional[str]:
    """Byte-truncate ONE line, reserving room for TRUNC_MARKER so the result
    never exceeds max_bytes. Returns None when the remaining room could not hold
    MIN_TRUNC_CONTENT_BYTES of real content (a shorter fragment is noise)."""
    marker_b = len(TRUNC_MARKER.encode("utf-8"))
    room = max_bytes - marker_b
    if room < MIN_TRUNC_CONTENT_BYTES:
        return None
    b = s.encode("utf-8", errors="replace")
    if len(b) <= max_bytes:
        return s
    return b[:room].decode("utf-8", errors="ignore") + TRUNC_MARKER


def _truncate_header(header: str, max_bytes: int) -> Optional[str]:
    """Rung 4: byte-truncate the header, EXPLICITLY MARKED with a trailing
    ellipsis. Returns None when not even one content byte plus the ellipsis
    fits."""
    if max_bytes < len(_HEADER_ELLIPSIS) + 1:
        return None
    b = header.encode("utf-8", errors="replace")
    room = max_bytes - len(_HEADER_ELLIPSIS)
    if len(b) <= room:
        return header
    return b[:room].decode("utf-8", errors="ignore") + _HEADER_ELLIPSIS


def _failure_rank(line: str) -> Optional[int]:
    """The priority rank of a failure line, or None when the line is filler."""
    for pattern, rank in _FAILURE_MATCHERS:
        if pattern.match(line):
            return rank
    return None


def _spans(lines: List[str], radius: int) -> Tuple[List[Tuple[int, int]], List[int]]:
    """Build the coalesced failure spans.

    Returns (spans_in_document_order, allocation_order_indices).

    A span is a matched line plus `radius` lines each side. Overlapping OR
    ADJACENT spans are coalesced BEFORE allocation, and a span coalesced from
    different ranks takes the HIGHEST contained rank (leaving that unspecified
    is a second way two implementations could retain different evidence).

    Allocation order walks ranks high->low and, within a rank, ORIGINAL MATCH
    POSITION earliest-first — the SOLE comparator. Match position is unique, so
    no further tie-break exists or is needed. Encoded byte length is NOT a
    selection input.

    NO-MATCH FALLBACK (documented degradation): when nothing matches the failure
    predicate there is nothing to prioritize, so every line becomes its own
    rank-0 span and the allocation order runs LAST line first. That degrades to
    a tail WINDOW rather than a head window, because the spec's objection to
    tail-drop is specifically that it amputates the traceback at the END.
    """
    matches = []  # type: List[Tuple[int, int]]
    for i, line in enumerate(lines):
        rank = _failure_rank(line)
        if rank is not None:
            matches.append((i, rank))

    if not matches:
        spans = [(i, i) for i in range(len(lines))]
        return spans, list(range(len(spans) - 1, -1, -1))

    raw = []  # type: List[Tuple[int, int, int, int]]  # start, end, rank, first_match
    for i, rank in matches:
        raw.append((max(0, i - radius), min(len(lines) - 1, i + radius), rank, i))

    merged = []  # type: List[List[int]]
    for start, end, rank, first in raw:
        if merged and start <= merged[-1][1] + 1:      # overlapping OR adjacent
            merged[-1][1] = max(merged[-1][1], end)
            merged[-1][2] = max(merged[-1][2], rank)   # highest contained rank
        else:
            merged.append([start, end, rank, first])

    spans = [(m[0], m[1]) for m in merged]
    order = sorted(range(len(merged)), key=lambda k: (-merged[k][2], merged[k][3]))
    return spans, order


def _render(lines: List[str], kept: List[Tuple[int, int, Optional[str]]],
            header: str, use_markers: bool) -> str:
    """Render retained spans in ORIGINAL DOCUMENT ORDER with their header, and
    omission markers AT THE ORIGINAL GAPS.

    Nothing is ever reordered: moving a failure away from its header would
    re-attribute the error to the wrong job, and the judge votes on that altered
    association.

    `kept` entries are (start, end, override); `override` replaces the text of
    the span's LAST line (byte-level truncation at rung 3/4).
    """
    out = []  # type: List[str]
    if header:
        out.append(header)
    prev_end = -1
    for start, end, override in kept:
        gap = start - prev_end - 1
        if gap > 0 and use_markers:
            out.append(OMIT_MARKER_FMT % gap)
        seg = list(lines[start:end + 1])
        if override is not None and seg:
            seg[-1] = override
        out.extend(seg)
        prev_end = end
    tail = len(lines) - prev_end - 1
    if tail > 0 and use_markers:
        out.append(OMIT_MARKER_FMT % tail)
    return "\n".join(out)


def _render_len(prefix_sums: List[int], total_lines: int,
                kept: List[Tuple[int, int, Optional[str]]],
                header: str, use_markers: bool) -> int:
    """The EXACT encoded byte length `_render` would produce, computed with
    integer arithmetic instead of building the string.

    Allocation probes this once per candidate span, so rendering there would be
    quadratic in string work on pathological input (tens of thousands of 1-byte
    failure lines). A selftest asserts this stays byte-exact against `_render`.
    """
    total = 0
    items = 0
    if header:
        total += _blen(header)
        items += 1
    prev_end = -1
    for start, end, override in kept:
        gap = start - prev_end - 1
        if gap > 0 and use_markers:
            total += _OMIT_MARKER_BASE_LEN + len(str(gap))
            items += 1
        total += prefix_sums[end + 1] - prefix_sums[start]
        items += end - start + 1
        if override is not None:
            total += _blen(override) - (prefix_sums[end + 1] - prefix_sums[end])
        prev_end = end
    tail = total_lines - prev_end - 1
    if tail > 0 and use_markers:
        total += _OMIT_MARKER_BASE_LEN + len(str(tail))
        items += 1
    return total + max(items - 1, 0)   # the "\n" separators of the join


def _prefix_sums(lines: List[str]) -> List[int]:
    sums = [0] * (len(lines) + 1)
    for i, line in enumerate(lines):
        sums[i + 1] = sums[i] + _blen(line)
    return sums


def _allocate(lines: List[str], spans: List[Tuple[int, int]], order: List[int],
              budget: int, header: str, use_markers: bool,
              allow_truncation: bool) -> Optional[List[Tuple[int, int, Optional[str]]]]:
    """Give budget to spans in priority order; return the retained spans in
    DOCUMENT order, or None when nothing could be retained.

    Selection takes the longest PREFIX of the priority order that fits and stops
    at the first span that does not (`break`, never `continue`). That keeps
    encoded byte length out of the selection decision entirely — length only
    decides where the walk stops, never which span outranks which.
    """
    sums = _prefix_sums(lines)
    total_lines = len(lines)
    # Kept spans stay sorted by document position as they are accepted (spans
    # are disjoint, so `start` is a unique key) — an insort, not a re-sort per
    # step.
    starts = []  # type: List[int]
    kept = []  # type: List[Tuple[int, int, Optional[str]]]
    for idx in order:
        if len(kept) >= _ALLOC_MAX_ACCEPTED:
            break
        start, end = spans[idx]
        pos = bisect.bisect_left(starts, start)
        starts.insert(pos, start)
        kept.insert(pos, (start, end, None))
        if _render_len(sums, total_lines, kept, header, use_markers) > budget:
            starts.pop(pos)
            kept.pop(pos)
            break
    if kept:
        return kept
    if not allow_truncation or not order:
        return None

    # Nothing fit whole. Truncate the single HIGHEST-priority span: first by
    # dropping its trailing lines (marked by the gap marker that grows in their
    # place), then, only if even its first line is too long, by byte-truncating
    # that line with the TRUNC_MARKER dialect.
    start, end = spans[order[0]]
    for last in range(end, start - 1, -1):
        if _render_len(sums, total_lines, [(start, last, None)],
                       header, use_markers) <= budget:
            return [(start, last, None)]
    empty = _render_len(sums, total_lines, [(start, start, "")], header, use_markers)
    room = budget - empty
    override = _cap_line_with_marker(lines[start], room) if room > 0 else None
    if override is None:
        return None
    return [(start, start, override)]


def pack_evidence(sanitized_text: str, budget_bytes: int,
                  section_label: str) -> PackedEvidence:
    """Pack ALREADY-REDACTED evidence into `budget_bytes`, failure first.

    Contract:
      - `sanitized_text` MUST be post-`redact_uncapped()` output. See the
        SECURITY ORDERING note above — packing before redaction is forbidden.
      - `section_label` must be a member of EVIDENCE_SECTION_LABELS; anything
        else is REJECTED with a ValueError.
      - The result is ALWAYS within `budget_bytes` (or `omit` is True, in which
        case the caller drops the evidence block entirely).
      - Small inputs are BYTE-IDENTICAL passthrough (rung 0).
      - Raises on a bad argument. Packing failure is handled AT THE CALLER,
        which substitutes PACKING_FAILED_PLACEHOLDER. Returning the oversized
        input instead would silently restore tail-drop with no signal, so
        unbounded input is NEVER returned.

    TOTAL loss hierarchy, applied in order until the result fits:
      0. everything fits                      -> byte-identical passthrough
      1. drop non-failure spans               (marked)
      2. shrink the context radius to zero    (marked)
      3. allocate by priority; truncate an oversized failure span   (marked)
      4. truncate the header                  (marked)
      5. drop the header and every marker; WHOLE retained lines only (unmarked)
      6. the fixed BUDGET_EXHAUSTED_PLACEHOLDER                      (unmarked)
      7. omit=True — the caller removes the evidence block           (unmarked)

    Rungs 5-7 are UNMARKED BY CONSTRUCTION: at that point there is no room left
    for a marker, so the rungs are themselves the signal (the caller logs the
    rung reached). Claiming every truncation is marked cannot hold there.

    Rung 5 emits only WHOLE lines — never a silently partial one — because a
    half-line that cannot carry a marker reads to a judge as a complete message.
    That is also what keeps rung 6 reachable rather than dead code.

    NOTE on rung 6 vs the spec sentence "at a non-positive budget emit the fixed
    placeholder": a non-positive budget cannot hold the placeholder either, so
    the ladder descends from 6 to 7 there. Rung 6 EMITS when the budget can hold
    the placeholder but not one whole retained line.
    """
    if section_label not in EVIDENCE_SECTION_LABELS:
        raise ValueError("section_label %r is not one of %s"
                         % (section_label, ", ".join(EVIDENCE_SECTION_LABELS)))
    if not isinstance(sanitized_text, str):
        raise TypeError("sanitized_text must be str, got %s"
                        % type(sanitized_text).__name__)
    if isinstance(budget_bytes, bool) or not isinstance(budget_bytes, int):
        raise TypeError("budget_bytes must be int, got %s"
                        % type(budget_bytes).__name__)

    original_bytes = _blen(sanitized_text)

    # Rung 0 — byte-identical passthrough.
    if budget_bytes > 0 and original_bytes <= budget_bytes:
        return PackedEvidence(sanitized_text, 0, False, original_bytes, original_bytes)

    lines = sanitized_text.split("\n")
    # A trailing newline yields a synthetic empty final element. Left in place it can be
    # selected as the "tail span" by the no-match fallback, so a 30 KB unmatched line
    # packs to a marker and ZERO retained content, and at a tiny budget rung 5 returns an
    # empty string instead of descending to the rung-6 placeholder. It carries no evidence
    # either way — drop it. (Codex code-review finding #1.)
    if len(lines) > 1 and lines[-1] == "":
        lines = lines[:-1]
    header = "[section: %s]" % section_label

    def _done(text: str, rung: int) -> PackedEvidence:
        return PackedEvidence(text, rung, False, original_bytes, _blen(text))

    sums = _prefix_sums(lines)

    # Rung 1 — drop non-failure spans (context radius 3).
    spans3, order3 = _spans(lines, EVIDENCE_CONTEXT_RADIUS)
    if spans3:
        kept3 = [(s, e, None) for s, e in spans3]
        if _render_len(sums, len(lines), kept3, header, True) <= budget_bytes:
            return _done(_render(lines, kept3, header, True), 1)

    # Rung 2 — shrink the context radius to zero.
    spans0, order0 = _spans(lines, 0)
    if spans0:
        kept0 = [(s, e, None) for s, e in spans0]
        if _render_len(sums, len(lines), kept0, header, True) <= budget_bytes:
            return _done(_render(lines, kept0, header, True), 2)

        # Rung 3 — priority allocation + truncation of an oversized span.
        kept = _allocate(lines, spans0, order0, budget_bytes, header, True, True)
        if kept is not None:
            return _done(_render(lines, kept, header, True), 3)

        # Rung 4 — truncate the header.
        short_header = _truncate_header(header, RUNG4_HEADER_MAX_BYTES)
        if short_header is not None and short_header != header:
            kept = _allocate(lines, spans0, order0, budget_bytes,
                             short_header, True, True)
            if kept is not None:
                return _done(_render(lines, kept, short_header, True), 4)

        # Rung 5 — no header, no markers, WHOLE lines only.
        kept = _allocate(lines, spans0, order0, budget_bytes, "", False, False)
        if kept is not None:
            return _done(_render(lines, kept, "", False), 5)

    # Rung 6 — the fixed placeholder, when it fits.
    if budget_bytes > 0 and _blen(BUDGET_EXHAUSTED_PLACEHOLDER) <= budget_bytes:
        return _done(BUDGET_EXHAUSTED_PLACEHOLDER, 6)

    # Rung 7 — the caller omits the evidence block entirely.
    return PackedEvidence("", 7, True, original_bytes, 0)


# --------------------------------------------------------------------------
# Selftest. Exercises the REAL conformance logic in-process (no workers, no
# network, no filesystem writes outside a tmp dir): build_result (the canonical
# builder), _derive_status, and _usage_conformance_errors (the targeted usage
# sub-schema check). ADDITIVE — it never changes runtime behavior.
# --------------------------------------------------------------------------
_REQUIRED_KEYS = (
    "status", "blocked", "files_changed", "violations", "summary",
    "session_id", "worktree", "exit_code", "failure_class",
    "retry_after_seconds",
)


def _mk_args(**kw: Any) -> argparse.Namespace:
    """Build an args Namespace with the same defaults parse_args would set."""
    defaults = dict(
        job_id="job-1", run_dir=None, out=None, scope=None,
        worker_output=None, schema=None, status=None, summary=None,
        session_id=None, worktree=None, exit_code=None,
        failure_class=None, retry_after_seconds=0, backend=None,
        files_changed=None, violations=None, blocked=None,
        print_result=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _selftest() -> int:
    ok = [0]
    fail = [0]
    failures = []  # type: List[str]

    def check(name: str, cond: bool) -> None:
        if cond:
            ok[0] += 1
        else:
            fail[0] += 1
            failures.append(name)

    # (a) A well-formed job produces a schema-shaped result with the 10 required
    #     keys and passes the real conformance check.
    res = build_result(_mk_args(files_changed="a.py,b.py", exit_code=0))
    for k in _REQUIRED_KEYS:
        check("wellformed.has_key.%s" % k, k in res)
    check("wellformed.status_success", res["status"] == "success")
    check("wellformed.files", res["files_changed"] == ["a.py", "b.py"])
    errs = conformance_errors(res, _default_schema_path())
    check("wellformed.conformant", errs == [])

    # (b) A schema-VIOLATING usage object is caught by _usage_conformance_errors,
    #     using the REAL usage sub-schema from job_result.schema.json.
    schema = _read_json(_default_schema_path())
    usage_schema = schema["properties"]["usage"] if isinstance(schema, dict) else {}
    good_usage = {"input_tokens": 1, "output_tokens": 2, "advisor_calls": 0,
                  "backend": "codex", "measured": True}
    check("usage.good_clean", _usage_conformance_errors(dict(good_usage), usage_schema) == [])
    extra = dict(good_usage)
    extra["bogus"] = 1  # additionalProperties:false violation
    check("usage.extra_key_caught", len(_usage_conformance_errors(extra, usage_schema)) > 0)
    wrongtype = dict(good_usage)
    wrongtype["input_tokens"] = "100"  # must be integer-or-null, not string
    check("usage.wrong_type_caught", len(_usage_conformance_errors(wrongtype, usage_schema)) > 0)
    boolint = dict(good_usage)
    boolint["output_tokens"] = True  # bool must not satisfy an integer field
    check("usage.bool_for_int_caught", len(_usage_conformance_errors(boolint, usage_schema)) > 0)
    nulls = dict(good_usage)
    nulls["input_tokens"] = None  # null IS allowed (["integer","null"])
    check("usage.null_ok", _usage_conformance_errors(nulls, usage_schema) == [])

    # (b2) A schema-VIOLATING retries[] item is caught by _retries_conformance_errors,
    #      using the REAL retries sub-schema from job_result.schema.json (Task B).
    retries_schema = schema["properties"]["retries"] if isinstance(schema, dict) else {}
    good_retries = [{"stage": "impl", "attempt": 1},
                    {"stage": "review", "job": "j1", "attempt": 2, "wait_ms": 500,
                     "escalated_from": "sonnet", "model": "opus"}]
    check("retries.good_clean",
          _retries_conformance_errors(good_retries, retries_schema) == [])
    unknown_key = [{"stage": "impl", "attempt": 1, "bogus": 1}]
    unknown_errs = _retries_conformance_errors(unknown_key, retries_schema)
    check("retries.unknown_key_caught", len(unknown_errs) > 0)
    check("retries.unknown_key_names_index_and_key",
          any("retries[0]" in e and "bogus" in e for e in unknown_errs))
    missing_stage = [{"attempt": 1}]
    missing_errs = _retries_conformance_errors(missing_stage, retries_schema)
    check("retries.missing_stage_caught", len(missing_errs) > 0)
    check("retries.missing_stage_names_index_and_key",
          any("retries[0]" in e and "stage" in e for e in missing_errs))
    string_attempt = [{"stage": "impl", "attempt": "1"}]
    string_errs = _retries_conformance_errors(string_attempt, retries_schema)
    check("retries.string_attempt_caught", len(string_errs) > 0)
    check("retries.string_attempt_names_index_and_key",
          any("retries[0]" in e and "attempt" in e for e in string_errs))
    bool_attempt = [{"stage": "impl", "attempt": True}]
    check("retries.bool_attempt_caught",
          len(_retries_conformance_errors(bool_attempt, retries_schema)) > 0)
    zero_attempt = [{"stage": "impl", "attempt": 0}]
    check("retries.attempt_below_minimum_caught",
          len(_retries_conformance_errors(zero_attempt, retries_schema)) > 0)
    negative_wait = [{"stage": "impl", "attempt": 1, "wait_ms": -1}]
    check("retries.negative_wait_ms_caught",
          len(_retries_conformance_errors(negative_wait, retries_schema)) > 0)

    # (b3) A schema-VIOLATING retries[] item hard-blocks the top-level conformance
    #      check exactly like usage: build_result + conformance_errors together
    #      refuse to write a result whose retries[] item fails.
    res_bad_retries = dict(res)
    res_bad_retries["retries"] = missing_stage
    check("retries.hard_blocks_conformance",
          len(conformance_errors(res_bad_retries, _default_schema_path())) > 0)
    res_good_retries = dict(res)
    res_good_retries["retries"] = good_retries
    check("retries.good_conformant",
          conformance_errors(res_good_retries, _default_schema_path()) == [])

    # (c) The "a successful job never carries a failure class" invariant: a
    #     failure_class/retry passed alongside a success status is zeroed out.
    res_c = build_result(_mk_args(files_changed="a.py", exit_code=0,
                                  failure_class="rate_limited",
                                  retry_after_seconds=30))
    check("success_no_failure_class.status", res_c["status"] == "success")
    check("success_no_failure_class.class", res_c["failure_class"] is None)
    check("success_no_failure_class.retry", res_c["retry_after_seconds"] == 0)

    # (d) usage.advisor_calls is SCRIPT-DERIVED: a worker-reported count is
    #     ALWAYS discarded. With no advisor log -> null (fail-open); with an N-line
    #     log -> N. Everything runs inside a tmp dir; no real filesystem touched.
    d = tempfile.mkdtemp(prefix="cv-collect-selftest-")
    try:
        wo = os.path.join(d, "worker.txt")
        with open(wo, "w") as fh:
            json.dump({"summary": "did the thing",
                       "usage": {"input_tokens": 10, "output_tokens": 5,
                                 "advisor_calls": 999, "backend": "codex",
                                 "measured": True}}, fh)
        args_d = _mk_args(job_id="job-d", run_dir=d, worker_output=wo)
        res_d = build_result(args_d)
        check("advisor.usage_present", isinstance(res_d.get("usage"), dict))
        check("advisor.worker_count_discarded", res_d["usage"]["advisor_calls"] is None)
        check("advisor.tokens_preserved", res_d["usage"]["input_tokens"] == 10)
        check("advisor.summary_from_worker", res_d["summary"] == "did the thing")

        logs = os.path.join(d, "logs")
        os.makedirs(logs, exist_ok=True)
        with open(os.path.join(logs, "job-d.advisor.jsonl"), "w") as fh:
            fh.write('{"consult":1}\n{"consult":2}\n{"consult":3}\n')
        res_d2 = build_result(args_d)
        check("advisor.derived_count", res_d2["usage"]["advisor_calls"] == 3)
    finally:
        shutil.rmtree(d, ignore_errors=True)

    # (e) Status derivation for success/blocked/timeout/error.
    check("status.success", _derive_status(False, 0, None, False) == "success")
    check("status.blocked", _derive_status(True, 0, None, False) == "blocked")
    check("status.timeout_flag", _derive_status(False, 0, None, True) == "timeout")
    check("status.timeout_124", _derive_status(False, 124, None, False) == "timeout")
    check("status.error_exit", _derive_status(False, 1, None, False) == "error")
    check("status.scope_forced_error", _derive_status(False, 0, "error", False) == "error")
    # A block always wins over an explicit scope status.
    check("status.block_wins", _derive_status(True, 0, "success", False) == "blocked")

    # ----------------------------------------------------------------------
    # (f) v2.17 — pack_evidence: determinism, ordering, the total loss
    #     hierarchy, and the byte budget. The packer feeds an EXTERNAL judge's
    #     vote, so "the output is a function of the input" is a correctness
    #     requirement, not a nicety.
    # ----------------------------------------------------------------------

    def blen(s):  # local alias so the checks read as byte assertions
        return len(s.encode("utf-8"))

    # -- argument contract --------------------------------------------------
    try:
        pack_evidence("x", 100, "not_a_real_label")
        check("pack.label_enum_rejected", False)
    except ValueError:
        check("pack.label_enum_rejected", True)
    for lbl in EVIDENCE_SECTION_LABELS:
        check("pack.label_accepted.%s" % lbl,
              pack_evidence("x", 100, lbl).text == "x")
    try:
        pack_evidence(b"bytes-not-str", 100, "job_stderr")  # type: ignore[arg-type]
        check("pack.non_str_rejected", False)
    except TypeError:
        check("pack.non_str_rejected", True)
    try:
        pack_evidence("x", "100", "job_stderr")  # type: ignore[arg-type]
        check("pack.non_int_budget_rejected", False)
    except TypeError:
        check("pack.non_int_budget_rejected", True)

    # -- rung 0: byte-identical passthrough ---------------------------------
    small = "ERROR: boom\nsecond line\n"
    r0 = pack_evidence(small, 10000, "job_stderr")
    check("pack.rung0_passthrough_identical", r0.text == small)
    check("pack.rung0_rung_is_zero", r0.rung == 0 and r0.omit is False)
    check("pack.rung0_reports_real_size", r0.original_bytes == blen(small))

    # -- the shared prioritization fixture ----------------------------------
    # An EARLY low-rank ERROR and a LATE high-rank traceback, far enough apart
    # that their radius-3 spans do not coalesce.
    early = "ERROR: an early failure that is quite long " + "e" * 60
    late = "Traceback (most recent call last): " + "t" * 60
    prio_lines = [early] + ["filler line %d " % i + "f" * 60 for i in range(10)] + [late]
    prio = "\n".join(prio_lines)

    # Original order is PRESERVED — nothing is ever reordered, because moving a
    # failure away from its header re-attributes the error to the wrong job and
    # the judge votes on that altered association.
    r_ord = pack_evidence(prio, 400, "test_output")
    check("pack.order_preserved_no_reordering",
          "an early failure" in r_ord.text and "Traceback" in r_ord.text
          and r_ord.text.index("an early failure") < r_ord.text.index("Traceback"))

    # Rank beats position: under a one-span budget the LATER traceback wins over
    # the EARLIER ERROR. (This is the case that would otherwise elicit different
    # judge votes from two implementations.)
    r_prio = pack_evidence(prio, 200, "test_output")
    check("pack.rank_beats_position",
          "Traceback" in r_prio.text and "an early failure" not in r_prio.text)
    check("pack.rank_beats_position_in_budget", blen(r_prio.text) <= 200)

    # Determinism: identical input -> identical output, twice.
    check("pack.deterministic_repeat",
          pack_evidence(prio, 200, "test_output").text == r_prio.text)

    # -- markers: at the ORIGINAL gaps, and PATH-FREE -----------------------
    check("pack.marker_at_original_gap", "[cv-omitted: 11 lines]" in r_prio.text)
    marker_lines = [ln for ln in r_prio.text.split("\n") if ln.startswith("[cv-omitted")]
    check("pack.markers_are_path_free",
          marker_lines and all(re.match(r"^\[cv-omitted: \d+ lines\]$", ln)
                               for ln in marker_lines))
    check("pack.header_present", r_prio.text.startswith("[section: test_output]"))

    # -- coalescing: overlapping/adjacent spans merge, keeping the HIGHEST rank
    co_lines = (["filler %d" % i for i in range(6)]
                + ["ERROR: near miss", "bridge line", "Traceback (most recent call last):"]
                + ["filler %d" % i for i in range(6, 30)]
                + ["FAILED: a distant lower-rank failure"])
    co = "\n".join(co_lines)
    spans_c, order_c = _spans(co_lines, EVIDENCE_CONTEXT_RADIUS)
    check("pack.coalesced_adjacent_spans_merge", len(spans_c) == 2)
    # The merged span (ERROR + traceback) must outrank the standalone FAILED, so
    # it is first in the allocation order despite starting later than nothing.
    first_span = spans_c[order_c[0]]
    check("pack.coalesced_takes_highest_rank",
          first_span[0] <= 6 and first_span[1] >= 8)
    # A coalesced span renders CONTIGUOUSLY: no omission marker inside it.
    r_co_wide = pack_evidence(co, 300, "job_stdout")
    check("pack.coalesced_renders_contiguously",
          "bridge line" in r_co_wide.text
          and "[cv-omitted" not in r_co_wide.text[
              r_co_wide.text.index("near miss"):r_co_wide.text.index("Traceback")])
    # Under a one-span budget the merged (rank-4) span beats the standalone
    # rank-3 FAILED, even though FAILED sits later and is smaller.
    r_co = pack_evidence(co, 110, "job_stdout")
    check("pack.coalesced_span_wins_budget",
          "Traceback" in r_co.text and "distant lower-rank" not in r_co.text)

    # -- the TOTAL loss hierarchy: every rung reachable ---------------------
    long_lines = ["ERROR: " + "x" * 500 for _ in range(20)]
    long_text = "\n".join(long_lines)
    rungs_seen = {}
    for label, text, budget in (
            ("r0", small, 10000),
            ("r1", prio, 700),
            ("r2", prio, 400),
            ("r3", prio, 200),
            ("r4", long_text, 130),
            ("r5", prio, 100),
            ("r6", long_text, 100),
            ("r7", long_text, 20)):
        res = pack_evidence(text, budget, "job_stderr")
        rungs_seen[label] = res.rung
        check("pack.within_budget.%s" % label, res.omit or blen(res.text) <= budget)
    for want, label in enumerate(("r0", "r1", "r2", "r3", "r4", "r5", "r6", "r7")):
        check("pack.rung_reachable.%d" % want, rungs_seen[label] == want)

    # Rungs 1-4 are explicitly MARKED; rungs 5-7 are unmarked BY CONSTRUCTION
    # (there is no room left for a marker) — the rung itself is the signal.
    check("pack.rung4_header_truncated_and_marked",
          pack_evidence(long_text, 130, "job_stderr").text.startswith("[sectio..."))
    r5 = pack_evidence(prio, 100, "job_stderr")
    check("pack.rung5_unmarked_whole_lines",
          "[cv-omitted" not in r5.text and "[section:" not in r5.text
          and all(ln in prio_lines for ln in r5.text.split("\n")))
    check("pack.rung6_fixed_placeholder",
          pack_evidence(long_text, 100, "job_stderr").text == BUDGET_EXHAUSTED_PLACEHOLDER)
    r7 = pack_evidence(long_text, 20, "job_stderr")
    check("pack.rung7_omit_signals_caller", r7.omit is True and r7.text == "")
    check("pack.rung7_reports_real_pretrim_size", r7.original_bytes == blen(long_text))
    check("pack.non_positive_budget_omits", pack_evidence(prio, 0, "job_stderr").omit is True)
    check("pack.negative_budget_omits", pack_evidence(prio, -50, "job_stderr").omit is True)

    # Rung 3 truncates an oversized span with the marker vocabulary the arbiter
    # already uses (TRUNC_MARKER), not a third dialect.
    check("pack.rung3_span_truncation_marked",
          TRUNC_MARKER.strip() in pack_evidence(long_text, 200, "job_stderr").text)

    # -- a FAILURE-ONLY input over budget still lands INSIDE the budget ------
    # (the case that makes "bounded AND never drops a failure line" impossible)
    all_fail = "\n".join("ERROR: failure number %d" % i for i in range(400))
    r_af = pack_evidence(all_fail, 1000, "test_output")
    check("pack.failure_only_over_budget_fits",
          not r_af.omit and blen(r_af.text) <= 1000)
    check("pack.failure_only_is_lossy_and_says_so",
          "[cv-omitted" in r_af.text and r_af.original_bytes > 1000)

    # -- BYTES, not characters ----------------------------------------------
    # A non-ASCII fixture: a character budget would pass while the byte budget
    # is blown, which is exactly how a downstream tail cut amputates a prompt.
    nonascii = "\n".join(["ERROR: échec du téléchargement " + "é" * 40
                          for _ in range(30)])
    check("pack.nonascii_fixture_is_multibyte", blen(nonascii) > len(nonascii))
    for budget in (2000, 900, 300, 150, 60, 30):
        r_na = pack_evidence(nonascii, budget, "review_notes")
        check("pack.nonascii_within_byte_budget.%d" % budget,
              r_na.omit or blen(r_na.text) <= budget)
    r_na = pack_evidence(nonascii, 900, "review_notes")
    check("pack.nonascii_content_retained", "échec" in r_na.text)

    # -- a wide budget sweep: the byte invariant NEVER breaks ----------------
    sweep_ok = True
    for text in (small, prio, long_text, all_fail, nonascii, "", "\n\n\n"):
        for budget in (-10, 0, 1, 17, 35, 36, 37, 80, 130, 200, 512, 4096, 100000):
            res = pack_evidence(text, budget, "scope_gate")
            if not res.omit and blen(res.text) > max(budget, 0):
                sweep_ok = False
    check("pack.budget_sweep_never_exceeds", sweep_ok)

    # -- no failure match: degrade to a TAIL window, never a head window ----
    # (tail-drop's specific sin is amputating the traceback at the END)
    nomatch = "\n".join("plain line %d" % i for i in range(500))
    r_nm = pack_evidence(nomatch, 300, "diff_summary")
    check("pack.no_match_keeps_the_tail",
          "plain line 499" in r_nm.text and "plain line 0\n" not in r_nm.text)
    check("pack.no_match_marks_the_gap", "[cv-omitted:" in r_nm.text)

    # -- _render_len is byte-exact against _render (allocation depends on it) --
    exact = True
    for text in (prio, co, nonascii, all_fail):
        ls = text.split("\n")
        sums = _prefix_sums(ls)
        sp, _o = _spans(ls, EVIDENCE_CONTEXT_RADIUS)
        for hdr in ("[section: job_stderr]", ""):
            for markers in (True, False):
                kept = [(s, e, None) for s, e in sp[:3]]
                if kept and _render_len(sums, len(ls), kept, hdr, markers) != \
                        blen(_render(ls, kept, hdr, markers)):
                    exact = False
                if kept:
                    ov = list(kept)
                    ov[-1] = (ov[-1][0], ov[-1][1], "OVERRIDDEN\n...[TRUNCATED]")
                    if _render_len(sums, len(ls), ov, hdr, markers) != \
                            blen(_render(ls, ov, hdr, markers)):
                        exact = False
    check("pack.render_len_is_byte_exact", exact)

    sys.stdout.write("SELFTEST: %d ok, %d fail\n" % (ok[0], fail[0]))
    if failures:
        for name in failures:
            sys.stdout.write("  - FAIL: %s\n" % name)
        return 1
    return 0


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Normalize one job's worker output into a canonical job_result.json"
    )
    p.add_argument("--job-id", required=True, help="Job id (names the output file)")
    p.add_argument("--run-dir", help="Execution run dir; output -> <run-dir>/results/<id>.json")
    p.add_argument("--out", help="Explicit output path (overrides --run-dir)")
    p.add_argument("--scope", help="Path to the git-derived scope-gate verdict JSON")
    p.add_argument("--worker-output", help="Path to the worker last-message text/JSON")
    p.add_argument("--schema", help="Path to job_result.schema.json for conformance check")

    # Direct overrides (highest precedence).
    p.add_argument("--status", choices=STATUS_VALUES, help="Force status")
    p.add_argument("--summary", help="Force summary text")
    p.add_argument("--session-id", help="Force session_id")
    p.add_argument("--worktree", help="Force worktree path")
    p.add_argument("--exit-code", type=int, help="Force exit_code")
    p.add_argument("--failure-class",
                   choices=["none", "out_of_credits", "rate_limited", "overloaded",
                            "auth", "context_length", "timeout", "network", "other"],
                   help="Backend-failure class (from compound-v-classify-failure.py); omit on success")
    p.add_argument("--retry-after-seconds", type=int, default=0,
                   help="Seconds-until-retry from the provider, 0 if unknown")
    p.add_argument("--backend",
                   help="Job backend name (codex|opencode|cursor|agy|antigravity|claude|devin); "
                        "labels a usage object synthesized purely from a derived advisor_calls count")
    p.add_argument("--files-changed", help="Comma-separated files_changed")
    p.add_argument("--violations", help="Comma-separated violations")
    blocked_grp = p.add_mutually_exclusive_group()
    blocked_grp.add_argument("--blocked", dest="blocked", action="store_true", default=None,
                             help="Force blocked=true")
    blocked_grp.add_argument("--no-blocked", dest="blocked", action="store_false",
                             help="Force blocked=false (unless violations present)")

    p.add_argument("--print", dest="print_result", action="store_true",
                   help="Also print the result JSON to stdout")
    p.add_argument("--selftest", action="store_true",
                   help="Run inline conformance tests and exit 0 on success, non-zero on failure")
    return p.parse_args(argv)


def main(argv: List[str]) -> int:
    # --selftest short-circuits before the required-arg validation (it needs no
    # --job-id / --run-dir and touches nothing outside a tmp dir).
    if "--selftest" in argv:
        return _selftest()

    args = parse_args(argv)

    # Validate --job-id BEFORE it is ever used to build a path. A `../x` (or any
    # path separator) would let the output escape <run-dir>/results/.
    if not _job_id_is_safe(args.job_id):
        sys.stderr.write(
            "error: --job-id has invalid characters "
            "(allowed: A-Za-z0-9._-, not . or ..): %s\n" % args.job_id
        )
        return 1

    if not args.out and not args.run_dir:
        sys.stderr.write("error: one of --out or --run-dir is required\n")
        return 1

    result = build_result(args)

    schema_path = args.schema or _default_schema_path()
    errs = conformance_errors(result, schema_path)
    if errs:
        sys.stderr.write("schema conformance FAILED for job %s:\n" % args.job_id)
        for e in errs:
            sys.stderr.write("  - %s\n" % e)
        return 1

    if args.out:
        out_path = args.out
    else:
        out_path = os.path.join(args.run_dir, "results", "%s.json" % args.job_id)
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    text = json.dumps(result, indent=2, sort_keys=False) + "\n"
    with open(out_path, "w") as fh:
        fh.write(text)

    if args.print_result:
        sys.stdout.write(text)
    else:
        sys.stdout.write("wrote %s (status=%s, blocked=%s)\n"
                         % (out_path, result["status"], result["blocked"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
