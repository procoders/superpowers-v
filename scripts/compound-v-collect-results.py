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
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional

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
    # per-job advisor JSONL log (like the git-derived enforcement fields). When
    # the log is present, overwrite/set advisor_calls to the derived count; when
    # absent, leave it as the worker emitted (null). Fail-open on a missing log.
    advisor_calls = _count_advisor_calls(args.run_dir, args.job_id)
    if advisor_calls is not None:
        if usage is None:
            usage = {
                "input_tokens": None,
                "output_tokens": None,
                "advisor_calls": advisor_calls,
                "backend": args.backend or "",
                "measured": False,
            }
        else:
            usage["advisor_calls"] = advisor_calls

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
    return errs


def _default_schema_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "schemas", "job_result.schema.json")


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
    return p.parse_args(argv)


def main(argv: List[str]) -> int:
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
