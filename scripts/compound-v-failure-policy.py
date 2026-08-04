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
                                      job to the next viable frozen pool member when pool
                                      context exists, otherwise use the concrete backend's
                                      env-aware fallback. If no fallback -> halt (resumable).
  * rate_limited/overloaded/network/timeout -> retry SAME backend, exp backoff + jitter,
                                      honoring retry-after; capped per class AND by a
                                      run-level max_total_retries (anti retry-storm).
  * context_length                 -> escalate to a bigger tier (or split the job).

Usage:
  compound-v-failure-policy.py --failure-class rate_limited --backend codex --attempts 1
      [--total-retries 0] [--max-total-retries 12] [--retry-after 0] [--no-jitter]
      [--pool-members '[{"backend":"codex"},{"backend":"zai"}]']
      [--current-pool-index 0]
      [--circuit-open '{"zai":{"open":true,"reason":"out_of_credits",
        "opened_at":"2026-08-01T00:00:00Z","cleared_by":null}}']
  compound-v-failure-policy.py --selftest

Output (stdout): JSON {action, reason, backoff_seconds, reroute_to, escalate_tier,
circuit_break, next_pool_index, consume_total_retry, earliest_reset_seconds,
clear_assignment, circuit_break_backend}. Exit 0 (the decision IS the result); 2 on
usage error.

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

# Backend fallback chain — every external backend reroutes to claude (always available); claude
# itself has no further local fallback. Mirrors routing-policy's env-aware reroute. The lower-trust
# external workers (antigravity, cursor, zai) reroute UP to claude on a circuit-break, never down.
#
# A MISSING key yields None, which decide() reads as "nowhere to reroute" and turns into `halt` —
# stopping the whole run. That is why zai is listed explicitly. NOTE: `devin` and `opencode` are
# still absent and therefore still halt a run on a credit wall; that is a pre-existing gap,
# deliberately not changed here.
FALLBACK = {"codex": "claude", "antigravity": "claude", "cursor": "claude",
            "zai": "claude", "claude": None}

CONCRETE_BACKENDS = (
    "codex", "claude", "antigravity", "cursor", "devin", "opencode", "zai",
)

BACKOFF_BASE = 2
BACKOFF_CAP = 60
RESET_FIELDS = ("reset_seconds", "retry_after_seconds", "resets_in_seconds")
# Kept in sync by hand with the identical canonical-breaker constants/rules in
# compound-v-pool-state.py (_circuit_open_errors); verified semantically
# equivalent by review — re-diff both if either changes.
CIRCUIT_REASONS = ("out_of_credits", "auth")
CIRCUIT_CLEARED_BY = ("top_up", "reauth", "probe")
CIRCUIT_ENTRY_FIELDS = frozenset(("open", "reason", "opened_at", "cleared_by"))


def _backoff(attempts, retry_after, jitter):
    if retry_after and retry_after > 0:
        return float(retry_after)
    base = BACKOFF_BASE * (2 ** attempts)
    if jitter:
        base += random.uniform(0, BACKOFF_BASE)  # full-ish jitter to de-sync siblings
    return round(min(base, BACKOFF_CAP), 2)


def _member_backend(member):
    if isinstance(member, str):
        return member
    if isinstance(member, dict):
        value = member.get("backend")
        if isinstance(value, str):
            return value
    return None


def _canonical_breaker_is_open(member, circuit_open):
    backend = _member_backend(member)
    return (
        isinstance(circuit_open, dict)
        and backend in circuit_open
        and circuit_open[backend].get("open") is True
    )


def _member_is_viable(member, exhausted_backend, circuit_open):
    backend = _member_backend(member)
    if not backend or backend == "pool" or backend == exhausted_backend:
        return False
    if isinstance(member, dict) and member.get("available") is False:
        return False
    return not _canonical_breaker_is_open(member, circuit_open)


def _next_pool_member(pool_members, current_pool_index, exhausted_backend,
                      circuit_open):
    if not isinstance(pool_members, (list, tuple)) or not pool_members:
        return None, None
    if (not isinstance(current_pool_index, int)
            or isinstance(current_pool_index, bool)
            or current_pool_index < 0
            or current_pool_index >= len(pool_members)):
        return None, None
    for offset in range(1, len(pool_members) + 1):
        index = (current_pool_index + offset) % len(pool_members)
        member = pool_members[index]
        if _member_is_viable(member, exhausted_backend, circuit_open):
            return index, _member_backend(member)
    return None, None


def _validate_pool_context(backend, pool_members, current_pool_index,
                           circuit_open):
    supplied_members = pool_members is not None
    supplied_index = current_pool_index is not None
    if supplied_members != supplied_index:
        raise ValueError("pool_members and current_pool_index must be supplied together")
    if circuit_open is not None and not isinstance(circuit_open, dict):
        raise ValueError("circuit_open must be an object keyed by concrete backend")
    if isinstance(circuit_open, dict):
        for breaker_backend, entry in circuit_open.items():
            if breaker_backend not in CONCRETE_BACKENDS:
                raise ValueError("circuit_open key must be a concrete backend (got %r)"
                                 % breaker_backend)
            if not isinstance(entry, dict):
                raise ValueError("circuit_open[%s] must be an object"
                                 % breaker_backend)
            if frozenset(entry.keys()) != CIRCUIT_ENTRY_FIELDS:
                raise ValueError("circuit_open[%s] must contain exactly open, reason, "
                                 "opened_at, cleared_by" % breaker_backend)
            is_open = entry.get("open")
            reason = entry.get("reason")
            opened_at = entry.get("opened_at")
            cleared_by = entry.get("cleared_by")
            if not isinstance(is_open, bool):
                raise ValueError("circuit_open[%s].open must be true/false"
                                 % breaker_backend)
            if is_open is True and reason not in CIRCUIT_REASONS:
                raise ValueError("circuit_open[%s].reason must be out_of_credits or "
                                 "auth while open" % breaker_backend)
            if not isinstance(opened_at, str) or not opened_at:
                raise ValueError("circuit_open[%s].opened_at must be a non-empty string"
                                 % breaker_backend)
            if cleared_by is not None and cleared_by not in CIRCUIT_CLEARED_BY:
                raise ValueError("circuit_open[%s].cleared_by must be null, top_up, "
                                 "reauth, or probe" % breaker_backend)
            if is_open is True and cleared_by is not None:
                raise ValueError("circuit_open[%s].cleared_by must be null while open"
                                 % breaker_backend)
            if is_open is False:
                if reason == "auth" and cleared_by != "reauth":
                    raise ValueError("circuit_open[%s] closed auth breaker must be "
                                     "cleared_by reauth" % breaker_backend)
                if (reason == "out_of_credits"
                        and cleared_by not in ("top_up", "probe")):
                    raise ValueError("circuit_open[%s] closed out_of_credits breaker "
                                     "must be cleared_by top_up or probe"
                                     % breaker_backend)
                if reason not in CIRCUIT_REASONS:
                    raise ValueError("circuit_open[%s] closed reason must be "
                                     "out_of_credits or auth" % breaker_backend)
    if not supplied_members:
        return False
    if not isinstance(pool_members, (list, tuple)) or not pool_members:
        raise ValueError("pool_members must be a non-empty ordered array")
    if (not isinstance(current_pool_index, int)
            or isinstance(current_pool_index, bool)
            or current_pool_index < 0
            or current_pool_index >= len(pool_members)):
        raise ValueError("current_pool_index is outside pool_members")
    for member in pool_members:
        candidate = _member_backend(member)
        if candidate not in CONCRETE_BACKENDS:
            raise ValueError("pool candidate backend must be concrete (got %r)"
                             % candidate)
        if isinstance(member, dict):
            if "available" in member and not isinstance(member["available"], bool):
                raise ValueError("pool candidate available must be boolean")
            if "circuit_open" in member:
                raise ValueError("pool member circuit_open is invalid; use canonical "
                                 "top-level circuit_open state")
    if _member_backend(pool_members[current_pool_index]) != backend:
        raise ValueError("current pool member does not match assigned backend %r" % backend)
    return True


def _earliest_reset_seconds(pool_members, retry_after):
    values = []
    if isinstance(retry_after, (int, float)) and not isinstance(retry_after, bool):
        if retry_after > 0:
            values.append(retry_after)
    if isinstance(pool_members, (list, tuple)):
        for member in pool_members:
            if not isinstance(member, dict):
                continue
            for field in RESET_FIELDS:
                value = member.get(field)
                if (isinstance(value, (int, float))
                        and not isinstance(value, bool) and value > 0):
                    values.append(value)
    return min(values) if values else None


def _validate_retry_counters(attempts, total_retries, max_total_retries):
    for name, value in (("attempts", attempts), ("total_retries", total_retries)):
        if (not isinstance(value, int) or isinstance(value, bool) or value < 0):
            raise ValueError("%s must be a non-negative integer" % name)
    if (not isinstance(max_total_retries, int)
            or isinstance(max_total_retries, bool)
            or max_total_retries <= 0):
        raise ValueError("max_total_retries must be a positive integer")


def decide(failure_class, backend, attempts, total_retries, max_total_retries,
           retry_after=0, jitter=True, fallback_available=True, current_tier=None,
           pool_members=None, current_pool_index=None, circuit_open=None):
    if backend not in CONCRETE_BACKENDS:
        raise ValueError("backend must be concrete (got %r)" % backend)
    _validate_retry_counters(attempts, total_retries, max_total_retries)
    in_pool = _validate_pool_context(
        backend, pool_members, current_pool_index, circuit_open)
    earliest_reset = _earliest_reset_seconds(pool_members, retry_after)

    def out(action, reason, **kw):
        d = {"action": action, "reason": reason, "backoff_seconds": 0,
             "reroute_to": None, "escalate_tier": False, "circuit_break": False,
             "next_pool_index": None, "consume_total_retry": False,
             # earliest_reset_seconds describes the terminal exhausted-pool halt
             # (what /v:status renders); stamping it onto proceed/retry/reroute
             # results too would let an ordinary retry's Retry-After leak into a
             # field nothing but the halt path ever clears.
             "earliest_reset_seconds": earliest_reset if action == "halt" else None,
             "clear_assignment": False,
             "circuit_break_backend": None}
        d.update(kw)
        return d

    if failure_class == "none":
        return out("proceed", "no failure")

    if failure_class == "auth":
        # Auth won't self-heal by retrying; stop and let the human re-auth (/v:init).
        return out("halt", "auth failure on %s — fix the key/login (e.g. /v:init), then "
                   "/v:resume" % backend, circuit_break=True,
                   circuit_break_backend=backend)

    if failure_class == "out_of_credits":
        if in_pool and total_retries >= max_total_retries:
            return out("halt", "run-level retry budget exhausted (%d/%d) while %s "
                       "was out of credits — anti retry-storm cap; /v:resume"
                       % (total_retries, max_total_retries, backend),
                       circuit_break=True, circuit_break_backend=backend)

        if in_pool:
            next_index, next_backend = _next_pool_member(
                pool_members, current_pool_index, backend, circuit_open)
            if next_backend:
                return out("reroute", "%s out of credits — circuit-break only it and "
                           "re-route this job to next pool member %s (announce the cost "
                           "change)" % (backend, next_backend),
                           reroute_to=next_backend, circuit_break=True,
                           circuit_break_backend=backend,
                           next_pool_index=next_index, consume_total_retry=True,
                           clear_assignment=True)

        # Re-route ONLY if a fallback exists AND it is actually viable (not itself
        # circuit-open / out-of-credits / unauthenticated). Caller passes that health in.
        fb = FALLBACK.get(backend)
        if fb and fallback_available:
            return out("reroute", "%s out of credits — circuit-break it and re-route "
                       "remaining jobs to %s (announce the cost change)" % (backend, fb),
                       reroute_to=fb, circuit_break=True,
                       circuit_break_backend=backend,
                       consume_total_retry=in_pool, clear_assignment=in_pool)
        return out("halt", "%s out of credits and the fallback (%s) is unavailable too — "
                   "top up / fix the fallback, then /v:resume" % (backend, fb or "none"),
                   circuit_break=True, circuit_break_backend=backend)

    if failure_class == "context_length":
        # Escalate to a bigger tier — UNLESS we are already at the deepest tier, in which
        # case a bigger model does not exist and the job must be split (back to planning).
        if current_tier == "deep":
            return out("halt", "context too large for %s even at the deepest tier — split "
                       "the job (back to planning); no bigger tier exists" % backend)
        # A pool-routed job that escalates tier leaves its pool ring: the frozen
        # slot it holds was resolved for the OLD (smaller) tier, and pools do
        # not cover `deep` (a Non-goal), so the recorded pool assignment can no
        # longer describe where this job is about to run. Clear it exactly like
        # out_of_credits does, so the dispatcher re-resolves at the new tier and
        # records the result as an ordinary assignment_source: fallback pair —
        # never leaving a stale pool_index the validator would then reject.
        return out("reroute", "context too large for %s at tier %s — escalate to a bigger "
                   "tier" % (backend, current_tier or "?"), escalate_tier=True,
                   clear_assignment=in_pool)

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
                   backoff_seconds=_backoff(attempts, retry_after, jitter),
                   consume_total_retry=True)

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
    # zai reroutes UP to claude like every other external worker. Without a FALLBACK entry
    # the table yields None and this returns `halt`, stopping the WHOLE run on the first
    # z.ai credit wall.
    d = decide("out_of_credits", "zai", 0, 0, 12)
    check("ooc-zai", d["action"], "reroute", d["reroute_to"] == "claude" and d["circuit_break"])
    d = decide("rate_limited", "zai", 0, 0, 12)
    check("ratelimit-zai retries", d["action"], "retry")
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
    d = decide("out_of_credits", "codex", 0, 0, 12, fallback_available=False)
    check("ooc-no-fallback", d["action"], "halt", d["circuit_break"])
    d = decide("context_length", "codex", 0, 0, 12, current_tier="deep")
    check("ctx-deep", d["action"], "halt")
    d = decide("context_length", "codex", 0, 0, 12, current_tier="standard")
    check("ctx-standard", d["action"], "reroute", d["escalate_tier"])
    check("ctx-standard-non-pool-keeps-its-recorded-assignment",
          True, True, d["clear_assignment"] is False)
    d = decide("context_length", "codex", 0, 0, 12, current_tier="light",
               pool_members=[{"backend": "codex"}, {"backend": "zai"}],
               current_pool_index=0)
    check("ctx-pool-clears-the-now-stale-pool-assignment", d["action"], "reroute",
          d["escalate_tier"] is True and d["clear_assignment"] is True)
    d = decide("none", "codex", 0, 0, 12, retry_after=30)
    check("earliest-reset-not-leaked-onto-proceed", d["action"], "proceed",
          d.get("earliest_reset_seconds") is None)
    d = decide("rate_limited", "codex", 0, 0, 12, retry_after=30, jitter=False)
    check("earliest-reset-not-leaked-onto-an-ordinary-retry", d["action"], "retry",
          d.get("earliest_reset_seconds") is None)
    # backoff is capped and grows
    b0 = decide("rate_limited", "codex", 0, 0, 99, jitter=False)["backoff_seconds"]
    b1 = decide("rate_limited", "codex", 1, 0, 99, jitter=False)["backoff_seconds"]
    bcap = _backoff(10, 0, False)  # exercise the ceiling directly (policy caps attempts first)
    check("backoff-grows", True, True, b1 > b0)
    check("backoff-capped", True, True, bcap == BACKOFF_CAP)

    # Pool-aware quota semantics. These call the public decide() API exactly as the
    # dispatcher does: members are ordered frozen slots and the backend argument is
    # always the concrete current assignment, never the routing token ``pool``.
    members = [
        {"backend": "codex", "model": "gpt-5.6", "reset_seconds": 300},
        {"backend": "zai", "model": "glm-5.2", "reset_seconds": 120},
        {"backend": "cursor", "model": "composer-2"},
    ]
    try:
        d = decide("rate_limited", "codex", 0, 0, 12, jitter=False,
                   pool_members=members, current_pool_index=0)
        check("pool-rate-limit-preserves-assignment", d["action"], "retry",
              d.get("reroute_to") is None
              and d.get("next_pool_index") is None
              and d.get("clear_assignment") is False)
    except (TypeError, KeyError) as e:
        check("pool-rate-limit-preserves-assignment", "error", "retry", str(e))

    try:
        d = decide("out_of_credits", "codex", 0, 0, 12,
                   pool_members=members, current_pool_index=0)
        check("pool-ooc-advances", d["action"], "reroute",
              d.get("reroute_to") == "zai"
              and d.get("next_pool_index") == 1
              and d.get("circuit_break_backend") == "codex"
              and d.get("consume_total_retry") is True
              and d.get("clear_assignment") is True)
    except (TypeError, KeyError) as e:
        check("pool-ooc-advances", "error", "reroute", str(e))

    skipped = [
        {"backend": "codex"},
        {"backend": "zai", "available": False},
        {"backend": "cursor"},
        {"backend": "antigravity"},
    ]
    try:
        d = decide("out_of_credits", "codex", 0, 1, 12,
                   pool_members=skipped, current_pool_index=0,
                   circuit_open={"cursor": {
                       "open": True, "reason": "out_of_credits",
                       "opened_at": "2026-08-01T00:00:00Z", "cleared_by": None,
                   }})
        check("pool-ooc-skips-unavailable-and-open", d["action"], "reroute",
              d.get("reroute_to") == "antigravity"
              and d.get("next_pool_index") == 3)
    except (TypeError, KeyError) as e:
        check("pool-ooc-skips-unavailable-and-open", "error", "reroute", str(e))

    exhausted = [
        {"backend": "codex", "reset_seconds": 300},
        {"backend": "zai", "resets_in_seconds": 120},
    ]
    try:
        d = decide("out_of_credits", "codex", 0, 1, 12,
                   pool_members=exhausted, current_pool_index=0,
                   circuit_open={"zai": {
                       "open": True, "reason": "out_of_credits",
                       "opened_at": "2026-08-01T00:00:00Z", "cleared_by": None,
                   }})
        check("pool-exhaustion-uses-concrete-fallback", d["action"], "reroute",
              d.get("reroute_to") == "claude"
              and d.get("next_pool_index") is None
              and d.get("consume_total_retry") is True)
        d = decide("out_of_credits", "codex", 0, 12, 12, retry_after=200,
                   fallback_available=False, pool_members=exhausted,
                   current_pool_index=0,
                   circuit_open={"zai": {
                       "open": True, "reason": "out_of_credits",
                       "opened_at": "2026-08-01T00:00:00Z", "cleared_by": None,
                   }})
        check("pool-terminal-halt-reset-and-budget", d["action"], "halt",
              d.get("earliest_reset_seconds") == 120
              and d.get("consume_total_retry") is False)
    except (TypeError, KeyError) as e:
        check("pool-exhaustion-and-terminal-reset", "error", "reroute", str(e))

    check("pool-never-enters-concrete-fallback-table", True, True,
          "pool" not in FALLBACK)
    try:
        # Regression guard for the anti retry-storm cap itself: an exhausted
        # run-level budget must HALT even when the pool still has a live,
        # non-circuit-open member to reroute to — the cap exists precisely to
        # stop a pool from papering over an exhausted budget forever.
        d = decide("out_of_credits", "codex", 0, 12, 12,
                   pool_members=[{"backend": "codex"}, {"backend": "zai"}],
                   current_pool_index=0)
        check("pool-budget-exhaustion-halts-despite-a-viable-member",
              d["action"], "halt",
              d.get("circuit_break") is True
              and d.get("reroute_to") is None
              and d.get("next_pool_index") is None)
    except (TypeError, KeyError, ValueError) as e:
        check("pool-budget-exhaustion-halts-despite-a-viable-member", "error", "halt", str(e))
    try:
        d = decide("out_of_credits", "zai", 0, 1, 12,
                   pool_members=[{"backend": "zai"},
                                 {"backend": "codex"}],
                   current_pool_index=0,
                   circuit_open={"codex": {
                       "open": True, "reason": "out_of_credits",
                       "opened_at": "2026-08-01T00:00:00Z", "cleared_by": None,
                   }})
        check("pool-zai-exhaustion-uses-ordinary-fallback", d["action"], "reroute",
              d.get("reroute_to") == "claude")
    except (TypeError, KeyError, ValueError) as e:
        check("pool-zai-exhaustion-uses-ordinary-fallback", "error", "reroute", str(e))
    try:
        decide("rate_limited", "pool", 0, 0, 12)
        check("policy-rejects-routing-token", "retry", "error", False)
    except ValueError:
        check("policy-rejects-routing-token", "error", "error")
    try:
        d = decide(
            "out_of_credits", "codex", 0, 0, 12,
            pool_members=[{"backend": "codex"}, {"backend": "zai"},
                          {"backend": "cursor"}],
            current_pool_index=0,
            circuit_open={"zai": {
                "open": True, "reason": "out_of_credits",
                "opened_at": "2026-08-01T00:00:00Z", "cleared_by": None,
            }},
        )
        check("pool-skips-canonical-open-breaker", d["action"], "reroute",
              d.get("reroute_to") == "cursor" and d.get("next_pool_index") == 2)
    except (TypeError, KeyError, ValueError) as e:
        check("pool-skips-canonical-open-breaker", "error", "reroute", str(e))
    try:
        decide("out_of_credits", "codex", 0, 0, 12,
               pool_members=[{"backend": "codex"}, {"backend": "mystery"}],
               current_pool_index=0)
        check("pool-rejects-unknown-candidate", "reroute", "error", False)
    except ValueError:
        check("pool-rejects-unknown-candidate", "error", "error")
    malformed_contexts = [
        {"pool_members": [{"backend": "codex"}]},
        {"current_pool_index": 0},
        {"pool_members": "codex,zai", "current_pool_index": 0},
        {"pool_members": [{"backend": "codex"}], "current_pool_index": 3},
    ]
    malformed_rejected = True
    for context in malformed_contexts:
        try:
            decide("out_of_credits", "codex", 0, 0, 12, **context)
            malformed_rejected = False
        except ValueError:
            pass
    check("pool-rejects-partial-or-malformed-context", "error", "error",
          malformed_rejected)
    try:
        d = decide(
            "out_of_credits", "codex", 0, 12, 12, fallback_available=False,
            pool_members=[
                {"backend": "codex", "reset_seconds": 300,
                 "retry_after_seconds": 60, "resets_in_seconds": 180},
                {"backend": "zai", "reset_seconds": 120},
            ],
            current_pool_index=0,
            circuit_open={"zai": {
                "open": True, "reason": "out_of_credits",
                "opened_at": "2026-08-01T00:00:00Z", "cleared_by": None,
            }},
        )
        check("pool-reset-minimum-considers-every-field", d["action"], "halt",
              d.get("earliest_reset_seconds") == 60)
    except (TypeError, KeyError, ValueError) as e:
        check("pool-reset-minimum-considers-every-field", "error", "halt", str(e))
    invalid_breaker_maps = [
        {"codex": True},
        {"codex": {}},
        {"codex": {"open": "yes"}},
        {"pool": {"open": True}},
        {"mystery": {"open": True}},
    ]
    invalid_breakers_rejected = True
    for breakers in invalid_breaker_maps:
        try:
            decide("out_of_credits", "codex", 0, 0, 12,
                   pool_members=[{"backend": "codex"}, {"backend": "zai"}],
                   current_pool_index=0, circuit_open=breakers)
            invalid_breakers_rejected = False
        except ValueError:
            pass
    check("canonical-breakers-reject-booleans-malformed-and-unknown-keys",
          "error", "error", invalid_breakers_rejected)
    try:
        decide("out_of_credits", "codex", 0, 0, 12,
               pool_members=[{"backend": "codex"},
                             {"backend": "zai", "circuit_open": True}],
               current_pool_index=0)
        check("member-local-breaker-is-rejected", "reroute", "error", False)
    except ValueError:
        check("member-local-breaker-is-rejected", "error", "error")
    exact_contract_rejected = True
    for breakers in [
        {"codex": {"open": False}},
        {"codex": {"open": True, "reason": "bogus",
                   "opened_at": "2026-08-01T00:00:00Z", "cleared_by": None}},
        {"codex": {"open": True, "reason": "auth",
                   "opened_at": "2026-08-01T00:00:00Z", "cleared_by": "reauth"}},
        {"codex": {"open": False, "reason": "bogus",
                   "opened_at": "2026-08-01T00:00:00Z", "cleared_by": None}},
        {"codex": {"open": False, "reason": None,
                   "opened_at": "", "cleared_by": "probe"}},
        {"codex": {"open": False, "reason": None,
                   "opened_at": "2026-08-01T00:00:00Z", "cleared_by": "manual"}},
    ]:
        try:
            decide("out_of_credits", "codex", 0, 0, 12,
                   pool_members=[{"backend": "codex"}, {"backend": "zai"}],
                   current_pool_index=0, circuit_open=breakers)
            exact_contract_rejected = False
        except ValueError:
            pass
    check("canonical-breaker-exact-fields-and-reason-contract",
          "error", "error", exact_contract_rejected)
    try:
        d = decide(
            "rate_limited", "codex", 0, 0, 12, jitter=False,
            pool_members=[{"backend": "codex"}, {"backend": "zai"}],
            current_pool_index=0,
            circuit_open={"zai": {
                "open": False, "reason": "out_of_credits",
                "opened_at": "2026-08-01T00:00:00Z", "cleared_by": "probe",
            }},
        )
        check("canonical-closed-breaker-valid-combination", d["action"], "retry")
    except ValueError as e:
        check("canonical-closed-breaker-valid-combination", "error", "retry", str(e))
    try:
        d = decide(
            "rate_limited", "codex", 0, 0, 12, jitter=False,
            pool_members=[{"backend": "codex"}, {"backend": "zai"}],
            current_pool_index=0,
            circuit_open={"zai": {
                "open": False, "reason": "auth",
                "opened_at": "2026-08-01T00:00:00Z", "cleared_by": "reauth",
            }},
        )
        check("canonical-closed-auth-reauth-valid", d["action"], "retry")
    except ValueError as e:
        check("canonical-closed-auth-reauth-valid", "error", "retry", str(e))
    mismatched_transitions_rejected = True
    for reason, cleared_by in [
        ("auth", "top_up"),
        ("auth", "probe"),
        ("out_of_credits", "reauth"),
        ("auth", None),
        ("out_of_credits", None),
        (None, None),
        (None, "probe"),
    ]:
        try:
            decide(
                "rate_limited", "codex", 0, 0, 12, jitter=False,
                pool_members=[{"backend": "codex"}, {"backend": "zai"}],
                current_pool_index=0,
                circuit_open={"zai": {
                    "open": False, "reason": reason,
                    "opened_at": "2026-08-01T00:00:00Z", "cleared_by": cleared_by,
                }},
            )
            mismatched_transitions_rejected = False
        except ValueError:
            pass
    check("closed-breaker-reason-must-match-clear-transition",
          "error", "error", mismatched_transitions_rejected)
    corrupt_counters_rejected = True
    for attempts, total_retries, max_total_retries in [
        (-100, 0, 12),
        (0, -100, 12),
        (0, 0, -100),
        (True, 0, 12),
        (0, False, 12),
        (0, 0, True),
        (0.5, 0, 12),
        (0, 0.5, 12),
        (0, 0, 12.5),
        (0, 0, 0),
    ]:
        try:
            decide("rate_limited", "codex", attempts, total_retries,
                   max_total_retries, jitter=False)
            corrupt_counters_rejected = False
        except ValueError:
            pass
    check("retry-counters-reject-negative-bool-noninteger-and-zero-max",
          "error", "error", corrupt_counters_rejected)
    print("SELFTEST: %d ok, %d fail" % (ok, fail))
    return 0 if fail == 0 else 1


def main(argv):
    p = argparse.ArgumentParser(description="Decide the action for a classified failure.")
    p.add_argument("--failure-class")
    p.add_argument("--backend", choices=CONCRETE_BACKENDS, default="codex")
    p.add_argument("--attempts", type=int, default=0,
                   help="how many times THIS job has already been retried")
    p.add_argument("--total-retries", type=int, default=0,
                   help="total retries across the whole run so far")
    p.add_argument("--max-total-retries", type=int, default=12,
                   help="run-level retry budget (anti retry-storm)")
    p.add_argument("--retry-after", type=float, default=0,
                   help="seconds from the provider's Retry-After, if known")
    p.add_argument("--fallback-open", action="store_true",
                   help="set when the fallback backend is itself circuit-open/unavailable")
    p.add_argument("--current-tier", choices=["deep", "standard", "light"],
                   help="the job's current tier (for context_length escalation)")
    p.add_argument("--pool-members", type=json.loads,
                   help="ordered frozen pool member JSON array")
    p.add_argument("--current-pool-index", type=int,
                   help="current assignment's index in --pool-members")
    p.add_argument("--circuit-open", type=json.loads,
                   help="canonical state.json circuit_open object")
    p.add_argument("--no-jitter", action="store_true")
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args(argv)

    if args.selftest:
        return _selftest()
    if not args.failure_class:
        p.error("--failure-class is required (or use --selftest)")

    d = decide(args.failure_class, args.backend, args.attempts, args.total_retries,
               args.max_total_retries, retry_after=args.retry_after,
               jitter=not args.no_jitter, fallback_available=not args.fallback_open,
               current_tier=args.current_tier, pool_members=args.pool_members,
               current_pool_index=args.current_pool_index,
               circuit_open=args.circuit_open)
    print(json.dumps(d))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
