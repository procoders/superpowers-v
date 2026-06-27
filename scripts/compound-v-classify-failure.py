#!/usr/bin/env python3
"""
Compound V backend-failure classifier — the deterministic discriminator.

A backend (codex/claude) failure is NOT classifiable by exit code alone: for OpenAI
"out of credits" (HTTP 429 + type=insufficient_quota) and "rate limited" (HTTP 429 +
rate_limit_exceeded) share a status, and for Anthropic "out of credits" arrives as a
400/402 (`credit balance is too low`) — the inverse trap. So we branch on the error
TYPE/text in the captured stderr (codex) or the stream-json `api_retry.error` enum
(claude), never the status/exit code alone.

Classes (mirrors LiteLLM/OpenRouter's taxonomy):
  none            success — no failure
  out_of_credits  quota/billing exhausted — NOT retryable; circuit-break + re-route
  rate_limited    throttled — retryable with backoff (honor retry-after)
  overloaded      5xx / server overloaded — retryable with backoff
  auth            bad/expired key or login — NOT retryable; halt, human fixes it
  context_length  prompt too large — NOT retryable as-is; re-route to a bigger tier
  timeout         our wall-clock wrapper fired (exit 124) — retryable once, longer
  network         transport/DNS failure, no HTTP status — retryable with backoff
  other           unclassified non-zero — retry once, then halt

Usage:
  compound-v-classify-failure.py --backend codex|claude --exit-code N [--stderr-file P]
  compound-v-classify-failure.py --backend codex --exit-code 1 < stderr.txt
  compound-v-classify-failure.py --selftest

Output (stdout): JSON {failure_class, retryable, matched}. Exit 0 always (the class IS
the result); exit 2 on usage error.

Python 3.9-safe, stdlib only.
"""

import argparse
import json
import re
import sys

TIMEOUT_EXIT_CODE = 124

RETRYABLE = {"rate_limited", "overloaded", "timeout", "network", "other"}

# Substring signatures, checked in PRIORITY ORDER (most specific first). Lowercased
# before matching. out_of_credits MUST be checked before rate_limited (an
# insufficient_quota error is also a 429 and also mentions "quota"); the Anthropic
# credit error must be checked before context_length/other (it is a 400).
_CODEX_RULES = [
    ("out_of_credits", [
        "hit your usage limit", "usage limit reached", "insufficient_quota",
        "insufficient quota", "exceeded your current quota", "quota exceeded",
        "billing_hard_limit", "billing hard limit", "credit balance is too low",
        "out of credits", "no credits",
    ]),
    ("auth", [
        "invalid_api_key", "incorrect api key", "unauthorized", "401",
        "not logged in", "please run `codex login`", "authentication", "403 forbidden",
    ]),
    ("context_length", [
        "context_length_exceeded", "maximum context length", "context length",
        "too many tokens", "reduce the length",
    ]),
    ("rate_limited", [
        "rate limit", "rate_limit", "exceeded retry limit", "too many requests",
        "429",
    ]),
    ("overloaded", [
        "overloaded", "is currently overloaded", "server_error", "internal server error",
        "503", "502", "504", "500 internal", "bad gateway", "service unavailable",
    ]),
    ("network", [
        "connection reset", "econnreset", "connection refused", "could not connect",
        "network is unreachable", "dns", "getaddrinfo", "tls handshake",
        "connection error", "temporary failure in name resolution",
    ]),
]

# Antigravity / agy (Gemini backend): substring signatures over Gemini/agy error text,
# checked in PRIORITY ORDER. Gemini reuses `RESOURCE_EXHAUSTED` for BOTH quota
# exhaustion AND throttling, so the quota/billing needles MUST come FIRST — when the
# text mentions quota/billing/usage-limit, out_of_credits wins over rate_limited; a bare
# `resource_exhausted` / `429` with no quota wording falls through to rate_limited.
_ANTIGRAVITY_RULES = [
    # Gemini reuses RESOURCE_EXHAUSTED for BOTH quota exhaustion and per-minute throttling,
    # so these needles are deliberately quota/billing/credit-SPECIFIC. Even bare "quota" is
    # NOT here: Gemini's rate-limit message is literally "Quota exceeded for quota metric
    # '…' limit '… per minute'" — a transient throttle, not out of credits. Bare "insufficient"
    # / "exceeded your" / "usage limit" / "quota" were all removed because they stole throttle
    # text from rate_limited and forced a needless backend reroute. Hard exhaustion is matched
    # only by billing/credit phrasing or the specific "exceeded your current quota"; everything
    # else ambiguous falls through to rate_limited (transient, retry) — the safer default.
    ("out_of_credits", [
        "billing", "out of credit", "insufficient credit",
        "insufficient funds", "exceeded your current quota", "purchase a plan",
    ]),
    ("auth", [
        "permission_denied", "unauthenticated", "api key", "401", "403",
    ]),
    ("context_length", [
        "exceeds the maximum", "token count", "context window",
    ]),
    ("rate_limited", [
        "resource_exhausted", "rate limit", "429", "too many requests",
        "quota metric", "per minute", "per day", "request limit",
    ]),
    ("overloaded", [
        "unavailable", "503", "500", "overloaded", "internal error",
    ]),
    ("network", [
        "econnreset", "getaddrinfo", "connection refused", "dns",
    ]),
]

# Anthropic / claude: the AUTHORITATIVE path is the stream-json `api_retry.error` enum
# (see CLAUDE_ENUM + _parse_claude_json). These substrings are only the FALLBACK when the
# output isn't JSON. Deliberately NARROW — no bare "context"/"invalid_request" (they
# misclassify unrelated failures as context_length and wrongly trigger tier escalation).
_CLAUDE_RULES = [
    ("out_of_credits", ["billing_error", "credit balance is too low"]),
    ("auth", ["authentication_failed", "oauth_org_not_allowed", "authentication_error",
              "permission_error"]),
    ("context_length", ["max_output_tokens", "prompt is too long",
                        "context window exceeded", "context_length_exceeded"]),
    ("rate_limited", ["rate_limit", "too many requests"]),
    ("overloaded", ["overloaded_error", "529 overloaded", "server_error"]),
    ("network", ["econnreset", "getaddrinfo", "connection refused"]),
]

# Exact `api_retry.error` enum values -> class (claude headless stream-json).
CLAUDE_ENUM = {
    "billing_error": "out_of_credits",
    "rate_limit": "rate_limited",
    "overloaded": "overloaded",
    "overloaded_error": "overloaded",
    "server_error": "overloaded",
    "authentication_failed": "auth",
    "authentication_error": "auth",
    "oauth_org_not_allowed": "auth",
    "permission_error": "auth",
    "max_output_tokens": "context_length",
    "invalid_request": "other",   # too generic to escalate a tier — treat as other
    "model_not_found": "other",
    "unknown": "other",
}


def _parse_claude_json(text):
    """Scan claude stream-json lines for an error event; return (class, raw) or None.

    Parses actual JSONL — selects objects carrying an `error` (the `api_retry` event's
    enum) and maps the EXACT enum value. Falls through to None (then the narrow substring
    fallback runs) when no JSON error object is present.
    """
    found = None
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{") or '"error"' not in line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        err = obj.get("error")
        if isinstance(err, dict):
            err = err.get("type") or err.get("message")
        if not isinstance(err, str):
            continue
        key = err.strip().lower()
        if key in CLAUDE_ENUM:
            return CLAUDE_ENUM[key], err          # exact enum wins immediately
        for k, c in CLAUDE_ENUM.items():          # else a known enum as a substring
            if k in key:
                found = (c, err)
    return found


_RETRY_AFTER_RES = [
    re.compile(r"retry[- ]after[:=\s]+(\d+)", re.I),
    re.compile(r"try again in\s+(\d+)\s*(second|sec|minute|min|hour|day)s?", re.I),
]
_UNIT_SECONDS = {"second": 1, "sec": 1, "minute": 60, "min": 60, "hour": 3600, "day": 86400}


def _extract_retry_after(text):
    """Best-effort seconds-until-retry from a provider message; 0 if unknown."""
    for rx in _RETRY_AFTER_RES:
        m = rx.search(text)
        if m:
            n = int(m.group(1))
            if m.lastindex and m.lastindex >= 2:
                return n * _UNIT_SECONDS.get(m.group(2).lower().rstrip("s"), 1)
            return n
    return 0


def classify(backend, exit_code, stderr):
    """Return (failure_class, matched_signature_or_None, retry_after_seconds)."""
    if exit_code == 0:
        return "none", None, 0
    if exit_code == TIMEOUT_EXIT_CODE:
        return "timeout", "exit %d (timeout wrapper)" % TIMEOUT_EXIT_CODE, 0
    raw = stderr or ""
    retry_after = _extract_retry_after(raw)
    if backend == "claude":
        hit = _parse_claude_json(raw)
        if hit is not None:
            return hit[0], hit[1], retry_after
    text = raw.lower()
    if backend == "claude":
        rules = _CLAUDE_RULES
    elif backend == "antigravity":
        rules = _ANTIGRAVITY_RULES
    else:
        rules = _CODEX_RULES
    for cls, needles in rules:
        for n in needles:
            if n in text:
                return cls, n, retry_after
    return "other", None, retry_after


def _result(cls, matched, retry_after):
    return {"failure_class": cls, "retryable": cls in RETRYABLE, "matched": matched,
            "retry_after": retry_after}


def _selftest():
    cases = [
        # backend, exit, stderr, expected_class
        ("codex", 0, "", "none"),
        ("codex", 124, "", "timeout"),
        ("codex", 1, "stream error: You've hit your usage limit. Try again in 5 days.", "out_of_credits"),
        ("codex", 1, "Error: 429 insufficient_quota: You exceeded your current quota", "out_of_credits"),
        ("codex", 1, "exceeded retry limit, last status: 429 Too Many Requests", "rate_limited"),
        ("codex", 1, "Rate limit reached for gpt-5.5", "rate_limited"),
        ("codex", 1, "error sending request: engine is currently overloaded", "overloaded"),
        ("codex", 1, "openai 500 server_error: internal", "overloaded"),
        ("codex", 1, "401 Unauthorized: invalid_api_key", "auth"),
        ("codex", 1, "not logged in, please run `codex login`", "auth"),
        ("codex", 1, "400 context_length_exceeded: maximum context length is 400000", "context_length"),
        ("codex", 1, "error: Connection reset by peer (ECONNRESET)", "network"),
        ("codex", 1, "panic: something totally unexpected", "other"),
        # Anthropic / claude — note out_of_credits arrives as 400, not 429
        ("claude", 1, '{"type":"system","subtype":"api_retry","error":"billing_error"}', "out_of_credits"),
        ("claude", 1, "400 invalid_request_error: Your credit balance is too low to access the API", "out_of_credits"),
        ("claude", 1, '{"error":"rate_limit"}', "rate_limited"),
        ("claude", 1, '{"error":"overloaded"}', "overloaded"),
        ("claude", 1, '{"error":"authentication_failed"}', "auth"),
        ("claude", 1, '{"error":"oauth_org_not_allowed"}', "auth"),
        # narrow needles: a benign mention of "context" must NOT become context_length
        ("claude", 1, "log: building the context of the request (no error)", "other"),
        ("claude", 1, '{"type":"system","subtype":"api_retry","error":"overloaded"}', "overloaded"),
        # Antigravity / agy (Gemini) — quota/billing wins over the shared 429/RESOURCE_EXHAUSTED.
        ("antigravity", 1, "Error: 429 RESOURCE_EXHAUSTED: You exceeded your current quota", "out_of_credits"),
        ("antigravity", 1, "PERMISSION_DENIED: The caller does not have permission (403)", "auth"),
        ("antigravity", 1, "429 RESOURCE_EXHAUSTED: rate limit, please retry", "rate_limited"),
        ("antigravity", 1, "429 RESOURCE_EXHAUSTED: You have exceeded your rate limit, retry later", "rate_limited"),
        ("antigravity", 1, "429 RESOURCE_EXHAUSTED: Quota exceeded for quota metric 'GenerateContent request limit per minute'. Please retry.", "rate_limited"),
        ("antigravity", 1, "503 UNAVAILABLE: model is overloaded, try again later", "overloaded"),
        ("antigravity", 1, "input token count exceeds the maximum number of tokens", "context_length"),
        ("antigravity", 1, "getaddrinfo ENOTFOUND: dns lookup failed", "network"),
        ("antigravity", 1, "panic: totally unexpected agy crash", "other"),
    ]
    ok = 0
    fail = 0
    for backend, code, err, want in cases:
        got, _m, _ra = classify(backend, code, err)
        if got == want:
            ok += 1
        else:
            fail += 1
            print("  FAIL [%s] exit=%d %r -> %s (want %s)" % (backend, code, err[:48], got, want))
    # retryability + retry_after sanity
    assert _result("out_of_credits", None, 0)["retryable"] is False
    assert _result("auth", None, 0)["retryable"] is False
    assert _result("rate_limited", None, 0)["retryable"] is True
    assert _extract_retry_after("Retry-After: 30") == 30
    assert _extract_retry_after("please try again in 5 days") == 5 * 86400
    assert classify("codex", 1, "rate limited, retry-after: 12")[2] == 12
    print("SELFTEST: %d ok, %d fail" % (ok, fail))
    return 0 if fail == 0 else 1


def main(argv):
    p = argparse.ArgumentParser(description="Classify a backend failure.")
    p.add_argument("--backend", choices=["codex", "claude", "antigravity"])
    p.add_argument("--exit-code", type=int)
    p.add_argument("--stderr-file")
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args(argv)

    if args.selftest:
        return _selftest()
    if args.backend is None or args.exit_code is None:
        p.error("--backend and --exit-code are required (or use --selftest)")

    if args.stderr_file:
        try:
            with open(args.stderr_file, "r", errors="replace") as fh:
                stderr = fh.read()
        except OSError as e:
            print("classify-failure: cannot read stderr file: %s" % e, file=sys.stderr)
            return 2
    else:
        stderr = "" if sys.stdin.isatty() else sys.stdin.read()

    cls, matched, retry_after = classify(args.backend, args.exit_code, stderr)
    print(json.dumps(_result(cls, matched, retry_after)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
