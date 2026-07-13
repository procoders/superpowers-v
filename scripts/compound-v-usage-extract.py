#!/usr/bin/env python3
"""
Compound V usage extractor.

Reads a backend's own structured events log and prints a canonical `usage`
object (the optional field in schemas/job_result.schema.json) to stdout:

  {"input_tokens": int|null, "output_tokens": int|null,
   "advisor_calls": int|null, "backend": str, "measured": bool}

Design contract (v2.12 usage & advisor, anti-ruflo charter):

  - MEASURED-ONLY. Token counts come exclusively from the backend's OWN
    structured usage events, using the EXACT field names live-probed in
    docs/superpowers/library-audit/2026-07-13-usage-and-advisor.md. Each
    backend uses a different casing/shape, so normalization is per-backend.
  - FAIL-OPEN, NEVER FABRICATE. If the events log is missing, empty, or
    unparseable — or the backend emits no machine-readable usage at all
    (agy/antigravity, claude Task subagent, devin) — emit measured:false
    with null token counts. A null is honest; a made-up number is not.
  - A usage event contributes to the measured sum ONLY when BOTH required
    token fields are present AND are non-negative JSON INTEGERS. A malformed
    or incomplete usage event (empty `{}`, only one side present, string /
    float / bool / negative value) contributes NOTHING — it is never
    substituted with a zero. If no valid usage event is found, the token
    counts stay null and measured stays false. A genuine well-formed 0 from a
    real event is fine; an empty/absent usage object is NOT a real zero.
  - Non-JSON lines and error/deprecation event items are SKIPPED, never fatal.
  - `advisor_calls` is NOT extracted here. It is worker-COUNTED by the advisor
    executor (times it actually consulted the advisor) and folded in elsewhere.
    This extractor always leaves it null.

Per-backend token sources (field names are exact, from the library audit):

  codex     : JSONL. SUM over every `type=="turn.completed"` line of
              .usage.input_tokens and .usage.output_tokens.
  opencode  : JSONL. SUM over every `type=="step_finish"` line of
              .part.tokens.input and .part.tokens.output.
  cursor    : JSONL. The final `type=="result"` line's
              .usage.inputTokens and .usage.outputTokens.
  agy/antigravity, claude, devin : no machine-readable usage -> measured:false.

Python 3.9-safe, stdlib only. Exit 0 on a printed usage object; the --selftest
mode exits 0 on success, non-zero on failure.
"""

import argparse
import json
import os
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple

# Backends that expose no machine-readable per-job token usage. For these we
# always emit measured:false + null tokens (never a fabricated number).
UNMEASURED_BACKENDS = frozenset(
    ("agy", "antigravity", "claude", "devin")
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
        "advisor_calls": None,
        "backend": backend,
        "measured": False,
    }


def _measured(backend: str, input_tokens: int, output_tokens: int) -> Dict[str, Any]:
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "advisor_calls": None,
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
    check("codex.advisor_calls", u["advisor_calls"], None)
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
    for b in ("agy", "antigravity", "claude", "devin"):
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

    if failures:
        sys.stdout.write("SELFTEST FAIL (%d):\n" % len(failures))
        for f in failures:
            sys.stdout.write("  - %s\n" % f)
        return 1
    sys.stdout.write("SELFTEST PASS: codex/opencode/cursor sums + unmeasured + fail-open OK\n")
    return 0


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Extract a canonical, measured-only `usage` object from a "
                    "backend's structured events log."
    )
    p.add_argument("--backend", help="Backend name (codex|opencode|cursor|agy|"
                                     "antigravity|claude|devin)")
    p.add_argument("--events-log", help="Path to the backend's structured events log (JSONL)")
    p.add_argument("--selftest", action="store_true",
                   help="Run inline fixtures and exit 0 on success, non-zero on failure")
    return p.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    if args.selftest:
        return _selftest()
    if not args.backend:
        sys.stderr.write("error: --backend is required (or use --selftest)\n")
        return 1
    usage = extract_usage(args.backend, args.events_log)
    sys.stdout.write(json.dumps(usage, indent=2, sort_keys=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
