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
        "overloaded", "is currently overloaded", "503", "502", "500 internal",
        "bad gateway", "service unavailable",
    ]),
    ("network", [
        "connection reset", "econnreset", "connection refused", "could not connect",
        "network is unreachable", "dns", "getaddrinfo", "tls handshake",
        "connection error", "temporary failure in name resolution",
    ]),
]

# Anthropic / claude stream-json `api_retry.error` enum -> class (also matched as
# substrings against stderr when the enum isn't available).
_CLAUDE_RULES = [
    ("out_of_credits", ["billing_error", "credit balance is too low", "billing"]),
    ("auth", ["authentication_failed", "oauth_org_not_allowed", "authentication_error",
              "permission_error", "401", "403"]),
    ("context_length", ["max_output_tokens", "context", "prompt is too long",
                        "invalid_request"]),
    ("rate_limited", ["rate_limit", "429", "too many requests"]),
    ("overloaded", ["overloaded", "overloaded_error", "server_error", "529", "503",
                    "500"]),
    ("network", ["connection", "econnreset", "network", "dns", "getaddrinfo"]),
]


def classify(backend, exit_code, stderr):
    """Return (failure_class, matched_signature_or_None)."""
    if exit_code == 0:
        return "none", None
    if exit_code == TIMEOUT_EXIT_CODE:
        return "timeout", "exit %d (timeout wrapper)" % TIMEOUT_EXIT_CODE
    text = (stderr or "").lower()
    rules = _CLAUDE_RULES if backend == "claude" else _CODEX_RULES
    for cls, needles in rules:
        for n in needles:
            if n in text:
                return cls, n
    return "other", None


def _result(cls, matched):
    return {"failure_class": cls, "retryable": cls in RETRYABLE, "matched": matched}


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
    ]
    ok = 0
    fail = 0
    for backend, code, err, want in cases:
        got, _m = classify(backend, code, err)
        if got == want:
            ok += 1
        else:
            fail += 1
            print("  FAIL [%s] exit=%d %r -> %s (want %s)" % (backend, code, err[:48], got, want))
    # retryability sanity
    assert _result("out_of_credits", None)["retryable"] is False
    assert _result("auth", None)["retryable"] is False
    assert _result("rate_limited", None)["retryable"] is True
    print("SELFTEST: %d ok, %d fail" % (ok, fail))
    return 0 if fail == 0 else 1


def main(argv):
    p = argparse.ArgumentParser(description="Classify a backend failure.")
    p.add_argument("--backend", choices=["codex", "claude"])
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

    cls, matched = classify(args.backend, args.exit_code, stderr)
    print(json.dumps(_result(cls, matched)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
