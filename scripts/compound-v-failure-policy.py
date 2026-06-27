#!/usr/bin/env python3
"""
Compound V backend-failure policy — the deterministic decision table.

Given a `failure_class` (from compound-v-classify-failure.py), the backend, and the
per-job/per-run retry state, decide ONE action. This is LiteLLM's per-exception policy
+ OpenRouter's two-layer fallback realized as a STATIC TABLE (no daemon, no event loop)
— the circuit breaker is just `state.json` fields the dispatcher reads at batch
boundaries.

Actions:
  proceed   no failure — nothing to do
  retry     transient — re-dispatch SAME backend after `backoff_seconds`
  reroute   switch backend (out_of_credits -> fallback) or escalate tier (context_length)
  halt      stop; the run stays /v:resume-able (top up credits / fix key, then resume)

Key rules (grounded in the research):
  * out_of_credits / auth          -> NEVER retry (retrying burns time + rate-limits harder)
  * out_of_credits                 -> circuit-break the backend for the run + re-route the
                                      remaining jobs to the fallback (codex -> claude), the
                                      SAME env-aware rewrite used when codex is absent. If
                                      no fallback -> halt (resumable).
  * rate_limited/overloaded/network/timeout -> retry SAME backend, exp backoff + jitter,
                                      honoring retry-after; capped per class AND by a
                                      run-level max_total_retries (anti retry-storm).
  * context_length                 -> escalate to a bigger tier (or split the job).

Usage:
  compound-v-failure-policy.py --failure-class rate_limited --backend codex --attempts 1
      [--total-retries 0] [--max-total-retries 12] [--retry-after 0] [--no-jitter]
  compound-v-failure-policy.py --selftest

Output (stdout): JSON {action, reason, backoff_seconds, reroute_to, escalate_tier,
circuit_break}. Exit 0 (the decision IS the result); 2 on usage error.

Python 3.9-safe, stdlib only.
"""

import argparse
import json
import random
import sys

RETRYABLE = {"rate_limited", "overloaded", "network", "timeout", "other"}

# Per-class retry ceilings (LiteLLM-style per-exception counts). out_of_credits/auth
# are deliberately absent (0 retries).
PER_CLASS_MAX = {
    "rate_limited": 3,
    "overloaded": 2,
    "network": 2,
    "timeout": 1,
    "other": 1,
}

# Backend fallback chain (codex -> claude). claude has no further local fallback in 1.0
# (antigravity is a 1.1 stub). Mirrors routing-policy's env-aware codex->claude rewrite.
FALLBACK = {"codex": "claude", "antigravity": "claude", "claude": None}

BACKOFF_BASE = 2
BACKOFF_CAP = 60


def _backoff(attempts, retry_after, jitter):
    if retry_after and retry_after > 0:
        return float(retry_after)
    base = BACKOFF_BASE * (2 ** attempts)
    if jitter:
        base += random.uniform(0, BACKOFF_BASE)  # full-ish jitter to de-sync siblings
    return round(min(base, BACKOFF_CAP), 2)


def decide(failure_class, backend, attempts, total_retries, max_total_retries,
           retry_after=0, jitter=True):
    def out(action, reason, **kw):
        d = {"action": action, "reason": reason, "backoff_seconds": 0,
             "reroute_to": None, "escalate_tier": False, "circuit_break": False}
        d.update(kw)
        return d

    if failure_class == "none":
        return out("proceed", "no failure")

    if failure_class == "auth":
        # Auth won't self-heal by retrying; stop and let the human re-auth (/v:init).
        return out("halt", "auth failure on %s — fix the key/login (e.g. /v:init), then "
                   "/v:resume" % backend, circuit_break=True)

    if failure_class == "out_of_credits":
        fb = FALLBACK.get(backend)
        if fb:
            return out("reroute", "%s out of credits — circuit-break it and re-route "
                       "remaining jobs to %s (announce the cost change)" % (backend, fb),
                       reroute_to=fb, circuit_break=True)
        return out("halt", "%s out of credits and no fallback backend — top up, then "
                   "/v:resume" % backend, circuit_break=True)

    if failure_class == "context_length":
        return out("reroute", "context too large for %s at this tier — escalate to a "
                   "bigger tier; if already deepest, split the job (back to planning)"
                   % backend, escalate_tier=True)

    if failure_class in RETRYABLE:
        cap = PER_CLASS_MAX.get(failure_class, 1)
        if attempts >= cap:
            return out("halt", "%s: per-class retries exhausted (%d/%d) — /v:resume after "
                       "the condition clears" % (failure_class, attempts, cap))
        if total_retries >= max_total_retries:
            return out("halt", "run-level retry budget exhausted (%d/%d) — anti retry-"
                       "storm cap; /v:resume" % (total_retries, max_total_retries))
        return out("retry", "%s on %s — retry (attempt %d/%d)"
                   % (failure_class, backend, attempts + 1, cap),
                   backoff_seconds=_backoff(attempts, retry_after, jitter))

    return out("halt", "unclassified failure on %s" % backend)


def _selftest():
    ok = 0
    fail = 0

    def check(name, got_action, want_action, extra=True):
        nonlocal ok, fail
        if got_action == want_action and extra:
            ok += 1
        else:
            fail += 1
            print("  FAIL %s: action=%s (want %s) extra=%s" % (name, got_action, want_action, extra))

    d = decide("none", "codex", 0, 0, 12)
    check("none", d["action"], "proceed")
    d = decide("out_of_credits", "codex", 0, 0, 12)
    check("ooc-codex", d["action"], "reroute", d["reroute_to"] == "claude" and d["circuit_break"])
    d = decide("out_of_credits", "claude", 0, 0, 12)
    check("ooc-claude", d["action"], "halt", d["circuit_break"])
    d = decide("auth", "codex", 0, 0, 12)
    check("auth", d["action"], "halt")
    d = decide("rate_limited", "codex", 0, 0, 12, jitter=False)
    check("rl-first", d["action"], "retry", d["backoff_seconds"] > 0)
    d = decide("rate_limited", "codex", 3, 0, 12)
    check("rl-exhausted", d["action"], "halt")
    d = decide("rate_limited", "codex", 1, 12, 12)
    check("rl-budget", d["action"], "halt")
    d = decide("rate_limited", "codex", 0, 0, 12, retry_after=30, jitter=False)
    check("rl-retryafter", d["action"], "retry", d["backoff_seconds"] == 30.0)
    d = decide("timeout", "codex", 0, 0, 12)
    check("timeout-1", d["action"], "retry")
    d = decide("timeout", "codex", 1, 0, 12)
    check("timeout-exhausted", d["action"], "halt")
    d = decide("context_length", "codex", 0, 0, 12)
    check("ctx", d["action"], "reroute", d["escalate_tier"])
    # backoff is capped and grows
    b0 = decide("rate_limited", "codex", 0, 0, 99, jitter=False)["backoff_seconds"]
    b1 = decide("rate_limited", "codex", 1, 0, 99, jitter=False)["backoff_seconds"]
    bcap = _backoff(10, 0, False)  # exercise the ceiling directly (policy caps attempts first)
    check("backoff-grows", True, True, b1 > b0)
    check("backoff-capped", True, True, bcap == BACKOFF_CAP)
    print("SELFTEST: %d ok, %d fail" % (ok, fail))
    return 0 if fail == 0 else 1


def main(argv):
    p = argparse.ArgumentParser(description="Decide the action for a classified failure.")
    p.add_argument("--failure-class")
    p.add_argument("--backend", default="codex")
    p.add_argument("--attempts", type=int, default=0,
                   help="how many times THIS job has already been retried")
    p.add_argument("--total-retries", type=int, default=0,
                   help="total retries across the whole run so far")
    p.add_argument("--max-total-retries", type=int, default=12,
                   help="run-level retry budget (anti retry-storm)")
    p.add_argument("--retry-after", type=float, default=0,
                   help="seconds from the provider's Retry-After, if known")
    p.add_argument("--no-jitter", action="store_true")
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args(argv)

    if args.selftest:
        return _selftest()
    if not args.failure_class:
        p.error("--failure-class is required (or use --selftest)")

    d = decide(args.failure_class, args.backend, args.attempts, args.total_retries,
               args.max_total_retries, retry_after=args.retry_after,
               jitter=not args.no_jitter)
    print(json.dumps(d))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
