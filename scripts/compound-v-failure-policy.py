#!/usr/bin/env python3
"""Deterministic backend-failure policy returning transition intent only.

The policy decides retry, pool advance, concrete fallback, or resumable halt.  It
never reads persisted state and never accepts or scans frozen pool members; the
pool-state helper is the sole executable assignment authority.

Python 3.9-safe, stdlib only.
"""

import argparse
import datetime
import importlib.util
import json
import os
import random
import sys


RETRYABLE = {"rate_limited", "overloaded", "network", "timeout", "other"}
SHORT_POOL_TRANSIENTS = {"rate_limited", "overloaded"}
PER_CLASS_MAX = {
    "rate_limited": 3,
    "overloaded": 2,
    "network": 2,
    "timeout": 1,
    "other": 1,
}

FALLBACK = {
    "codex": "claude",
    "antigravity": "claude",
    "cursor": "claude",
    "zai": "claude",
    "claude": None,
}
CONCRETE_BACKENDS = (
    "codex", "claude", "antigravity", "cursor", "devin", "opencode", "zai",
)

BACKOFF_BASE = 2
BACKOFF_CAP = 60
MAX_INLINE_WAIT_SECONDS = 60
NETWORK_PAUSE_SECONDS = 60

RESET_FIELDS = ("reset_seconds", "retry_after_seconds", "resets_in_seconds")
# Kept in sync by hand with the identical canonical-breaker constants/rules in
# compound-v-pool-state.py (_circuit_open_errors); verified semantically
# equivalent by review — re-diff both if either changes.
CIRCUIT_REASONS = ("out_of_credits", "auth")
CIRCUIT_CLEARED_BY = ("top_up", "reauth", "probe")
CIRCUIT_ENTRY_FIELDS = frozenset(("open", "reason", "opened_at", "cleared_by"))


def _load_provider_time():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "compound-v-provider-time.py")
    spec = importlib.util.spec_from_file_location("compound_v_provider_time_policy", path)
    if spec is None or spec.loader is None:
        raise ValueError("cannot load sibling provider-time helper: %s" % path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_PROVIDER_TIME = _load_provider_time()
parse_utc_timestamp = _PROVIDER_TIME.parse_utc_timestamp
format_utc_timestamp = _PROVIDER_TIME.format_utc_timestamp
parse_delay = _PROVIDER_TIME.parse_delay


def _candidate_wait(attempts, retry_after, jitter, jitter_seconds=None,
                    include_provider_jitter=False):
    """Return the provider minimum or raw computed wait before inline gating."""
    provider_wait = parse_delay(retry_after, "retry_after")
    if jitter_seconds is not None:
        extra = parse_delay(jitter_seconds, "jitter_seconds") if jitter else 0
    else:
        extra = random.uniform(0, BACKOFF_BASE) if jitter else 0
    if provider_wait > 0:
        # Legacy behavior treats the rendered provider delay as the complete wait.
        return round(float(provider_wait) + (extra if include_provider_jitter else 0), 2)
    base = BACKOFF_BASE * (2 ** attempts)
    base += extra
    return round(base, 2)


def _backoff(attempts, retry_after, jitter):
    """Compatibility helper: a value emitted for inline sleep is always capped."""
    return min(_candidate_wait(attempts, retry_after, jitter),
               MAX_INLINE_WAIT_SECONDS)


def _utc_now(now):
    if now is None:
        return datetime.datetime.now(datetime.timezone.utc)
    return parse_utc_timestamp(now, "now")


def _absolute_after(now_value, seconds):
    return format_utc_timestamp(
        now_value + datetime.timedelta(seconds=float(seconds)))


def _normalize_retry_at(retry_at):
    if retry_at is None:
        return None
    return format_utc_timestamp(parse_utc_timestamp(retry_at, "retry_at"))


def _validate_inputs(pool_routed, assigned_model, attempt_id, network_scope,
                     correlated_network_failures, completed_provider_success):
    if not isinstance(pool_routed, bool):
        raise ValueError("pool_routed must be true/false")
    if assigned_model is not None and (
            not isinstance(assigned_model, str) or not assigned_model):
        raise ValueError("assigned_model must be a non-empty string when supplied")
    if attempt_id is not None and (
            not isinstance(attempt_id, str) or not attempt_id):
        raise ValueError("attempt_id must be a non-empty string when supplied")
    if network_scope not in (None, "no_response", "provider_reported"):
        raise ValueError("network_scope must be no_response, provider_reported, or null")
    if (not isinstance(correlated_network_failures, int)
            or isinstance(correlated_network_failures, bool)
            or correlated_network_failures < 0):
        raise ValueError("correlated_network_failures must be a non-negative integer")
    if not isinstance(completed_provider_success, bool):
        raise ValueError("completed_provider_success must be true/false")


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
           pool_routed=False, assigned_model=None, attempt_id=None, retry_at=None,
           now=None, network_scope=None, correlated_network_failures=0,
           completed_provider_success=False, jitter_seconds=None):
    """Return a pure transition intent; never inspect frozen pool membership."""
    if backend not in CONCRETE_BACKENDS:
        raise ValueError("backend must be concrete (got %r)" % backend)
    _validate_retry_counters(attempts, total_retries, max_total_retries)
    _validate_inputs(pool_routed, assigned_model, attempt_id, network_scope,
                     correlated_network_failures, completed_provider_success)
    retry_after = parse_delay(retry_after, "retry_after")
    if jitter_seconds is not None:
        parse_delay(jitter_seconds, "jitter_seconds")
    normalized_retry_at = _normalize_retry_at(retry_at)
    now_value = _utc_now(now)
    earliest_reset = retry_after if retry_after > 0 else None

    def out(action, reason, **kw):
        result = {
            # Causal facts consumed by the pool-state transition authority.
            "failure_class": failure_class,
            "attempt_id": attempt_id,
            "result": (None if failure_class == "none" else "failure"),
            "backend": backend,
            # Legacy output keys stay present for existing consumers.
            "action": action,
            "reason": reason,
            "backoff_seconds": 0,
            "reroute_to": None,
            "escalate_tier": False,
            "circuit_break": False,
            "next_pool_index": None,
            "consume_total_retry": False,
            # earliest_reset_seconds describes the terminal exhausted-pool/backend
            # halt (what /v:status renders) — never proceed/retry/reroute, and not
            # every halt either: a structural halt (auth, model_unavailable,
            # deepest-tier context_length) or one that already carries its own
            # precise next_retry_at (network pause, usage-window, the >60s
            # inline-wait halt) has nothing to do with a retry budget resetting.
            # Only the call sites that are genuinely "the budget/backend is
            # exhausted, retry in about this long" pass it explicitly below.
            "earliest_reset_seconds": None,
            "clear_assignment": False,
            "circuit_break_backend": None,
            # PR 3 intent keys. Pool-state constructs and validates canonical state.
            "cooldown_backend": None,
            "cooldown_reason": None,
            "cooldown_until": None,
            "advance_pool": False,
            "network_pause": False,
            "next_retry_at": None,
            # Normalized pool-state transition facts. The dispatcher resolves
            # fallback_assignment when the frozen ring may exhaust.
            "network_scope": network_scope,
            "exclude_assignment": None,
        }
        result.update(kw)
        return result

    def budget_exhausted(reason_suffix=""):
        if total_retries < max_total_retries:
            return None
        suffix = (" " + reason_suffix) if reason_suffix else ""
        return out(
            "halt",
            "run-level retry budget exhausted (%d/%d) — anti retry-storm cap; "
            "/v:resume%s" % (total_retries, max_total_retries, suffix),
            earliest_reset_seconds=earliest_reset,
        )

    def cooldown_advance(reason, until):
        exhausted = budget_exhausted("before pool advance")
        if exhausted is not None:
            exhausted.update({
                "cooldown_backend": backend,
                "cooldown_reason": reason,
                "cooldown_until": until,
                "next_retry_at": until,
            })
            return exhausted
        return out(
            "reroute",
            "%s on %s — cool the backend and advance this pool job"
            % (reason, backend),
            cooldown_backend=backend,
            cooldown_reason=reason,
            cooldown_until=until,
            advance_pool=True,
            consume_total_retry=True,
            clear_assignment=True,
        )

    if failure_class == "none":
        return out("proceed", "no failure")

    if failure_class == "auth":
        return out(
            "halt",
            "auth failure on %s — fix the key/login (e.g. /v:init), then /v:resume"
            % backend,
            circuit_break=True,
            circuit_break_backend=backend,
        )

    if failure_class == "out_of_credits":
        if pool_routed:
            exhausted = budget_exhausted("while %s was out of credits" % backend)
            if exhausted is not None:
                exhausted["circuit_break"] = True
                exhausted["circuit_break_backend"] = backend
                return exhausted
            return out(
                "reroute",
                "%s out of credits — circuit-break it and advance this pool job"
                % backend,
                reroute_to=FALLBACK.get(backend),
                circuit_break=True,
                circuit_break_backend=backend,
                advance_pool=True,
                consume_total_retry=True,
                clear_assignment=True,
            )
        fallback = FALLBACK.get(backend)
        if fallback and fallback_available:
            return out(
                "reroute",
                "%s out of credits — circuit-break it and re-route remaining jobs "
                "to %s (announce the cost change)" % (backend, fallback),
                reroute_to=fallback,
                circuit_break=True,
                circuit_break_backend=backend,
            )
        return out(
            "halt",
            "%s out of credits and the fallback (%s) is unavailable too — top up / "
            "fix the fallback, then /v:resume" % (backend, fallback or "none"),
            circuit_break=True,
            circuit_break_backend=backend,
            earliest_reset_seconds=earliest_reset,
        )

    if failure_class == "model_unavailable":
        if assigned_model is None:
            raise ValueError("model_unavailable requires assigned_model")
        if not pool_routed:
            return out(
                "halt",
                "model %s is unavailable on %s and this job is not pool-routed"
                % (assigned_model, backend),
            )
        exhausted = budget_exhausted("before exact-model pool advance")
        if exhausted is not None:
            return exhausted
        return out(
            "reroute",
            "model %s is unavailable on %s — advance this pool job only"
            % (assigned_model, backend),
            advance_pool=True,
            exclude_assignment={"backend": backend, "model": assigned_model},
            consume_total_retry=True,
            clear_assignment=True,
        )

    if failure_class == "usage_window_exhausted":
        if normalized_retry_at is not None:
            parsed_reset = parse_utc_timestamp(normalized_retry_at, "retry_at")
            until = (format_utc_timestamp(now_value)
                     if parsed_reset < now_value else normalized_retry_at)
        else:
            until = _absolute_after(
                now_value, _candidate_wait(
                    attempts, retry_after, jitter, jitter_seconds,
                    include_provider_jitter=pool_routed))
        if pool_routed:
            return cooldown_advance("usage_window_exhausted", until)
        return out(
            "halt",
            "usage window exhausted on %s — wait until %s, then /v:resume"
            % (backend, until),
            next_retry_at=until,
        )

    if failure_class == "context_length":
        if current_tier == "deep":
            return out(
                "halt",
                "context too large for %s even at the deepest tier — split the job "
                "(back to planning); no bigger tier exists" % backend,
            )
        # A pool-routed job that escalates tier leaves its pool ring: the frozen
        # slot it holds was resolved for the OLD (smaller) tier, and pools do
        # not cover `deep` (a Non-goal), so the recorded pool assignment can no
        # longer describe where this job is about to run. Clear it exactly like
        # out_of_credits does, so the dispatcher re-resolves at the new tier and
        # records the result as an ordinary assignment_source: fallback pair —
        # never leaving a stale pool_index the validator would then reject.
        return out(
            "reroute",
            "context too large for %s at tier %s — escalate to a bigger tier"
            % (backend, current_tier or "?"),
            escalate_tier=True,
            clear_assignment=pool_routed,
        )

    if failure_class == "network":
        if (network_scope == "no_response"
                and correlated_network_failures >= 2
                and not completed_provider_success):
            until = _absolute_after(now_value, NETWORK_PAUSE_SECONDS)
            return out(
                "halt",
                "correlated no-response failures — pause provider launches",
                network_pause=True,
                next_retry_at=until,
            )

        # A completed sibling success disproves a common outage. After one local
        # retry, a pooled endpoint may cool and advance; provider-reported network
        # failures use the same endpoint path and never count toward global pause.
        if pool_routed and attempts >= 1 and (
                completed_provider_success or network_scope == "provider_reported"):
            until = normalized_retry_at or _absolute_after(
                now_value, _candidate_wait(
                    attempts, retry_after, jitter, jitter_seconds,
                    include_provider_jitter=pool_routed))
            return cooldown_advance("network", until)

    if failure_class in RETRYABLE:
        cap = PER_CLASS_MAX.get(failure_class, 1)
        wait = _candidate_wait(
            attempts, retry_after, jitter, jitter_seconds,
            include_provider_jitter=pool_routed)
        if normalized_retry_at is not None:
            retry_in = max(
                0.0,
                (parse_utc_timestamp(normalized_retry_at, "retry_at") - now_value)
                .total_seconds(),
            )
            wait = retry_in

        if wait > MAX_INLINE_WAIT_SECONDS:
            until = normalized_retry_at or _absolute_after(now_value, wait)
            if pool_routed:
                return cooldown_advance(failure_class, until)
            return out(
                "halt",
                "%s on %s requires waiting until %s — no foreground sleep; /v:resume"
                % (failure_class, backend, until),
                next_retry_at=until,
            )

        if attempts >= cap:
            return out(
                "halt",
                "%s: per-class retries exhausted (%d/%d) — /v:resume after the "
                "condition clears" % (failure_class, attempts, cap),
                earliest_reset_seconds=earliest_reset,
            )
        exhausted = budget_exhausted()
        if exhausted is not None:
            return exhausted

        # A pooled short throttle/overload gets exactly one same-assignment retry.
        if pool_routed and failure_class in SHORT_POOL_TRANSIENTS and attempts >= 1:
            return cooldown_advance(
                failure_class, _absolute_after(now_value, wait))

        return out(
            "retry",
            "%s on %s — retry (attempt %d/%d)"
            % (failure_class, backend, attempts + 1, cap),
            backoff_seconds=float(wait),
            consume_total_retry=True,
        )

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
            print("  FAIL %s: action=%s (want %s) extra=%s"
                  % (name, got_action, want_action, extra))

    def rejects(name, fn):
        try:
            fn()
        except (TypeError, ValueError):
            check(name, "error", "error")
        else:
            check(name, "accepted", "error")

    # Legacy non-pool behavior and permanent failure paths.
    d = decide("none", "codex", 0, 0, 12)
    check("none", d["action"], "proceed")
    d = decide("out_of_credits", "codex", 0, 0, 12)
    check("ooc-codex", d["action"], "reroute",
          d["reroute_to"] == "claude" and d["circuit_break"])
    d = decide("out_of_credits", "zai", 0, 0, 12)
    check("ooc-zai", d["action"], "reroute",
          d["reroute_to"] == "claude" and d["circuit_break"])
    d = decide("out_of_credits", "claude", 0, 0, 12)
    check("ooc-claude", d["action"], "halt", d["circuit_break"])
    d = decide("auth", "codex", 0, 0, 12)
    check("auth", d["action"], "halt",
          d["circuit_break"] and d["circuit_break_backend"] == "codex")
    d = decide("rate_limited", "codex", 0, 0, 12, jitter=False)
    check("rl-first", d["action"], "retry", d["backoff_seconds"] == 2.0)
    d = decide("rate_limited", "codex", 3, 0, 12)
    check("rl-exhausted", d["action"], "halt")
    d = decide("rate_limited", "codex", 1, 12, 12)
    check("rl-budget", d["action"], "halt")
    d = decide("rate_limited", "codex", 0, 0, 12,
               retry_after=30, jitter=False)
    check("rl-retryafter", d["action"], "retry",
          d["backoff_seconds"] == 30.0)
    d = decide("timeout", "codex", 0, 0, 12, jitter=False)
    check("timeout-1", d["action"], "retry")
    d = decide("timeout", "codex", 1, 0, 12)
    check("timeout-exhausted", d["action"], "halt")
    d = decide("context_length", "codex", 0, 0, 12)
    check("ctx", d["action"], "reroute", d["escalate_tier"])
    d = decide("context_length", "codex", 0, 0, 12, current_tier="deep")
    check("ctx-deep", d["action"], "halt")
    d = decide("out_of_credits", "codex", 0, 0, 12,
               fallback_available=False)
    check("ooc-no-fallback", d["action"], "halt", d["circuit_break"])
    check("backoff-grows", True, True,
          _backoff(1, 0, False) > _backoff(0, 0, False))
    check("backoff-capped", True, True,
          _backoff(10, 0, False) == MAX_INLINE_WAIT_SECONDS)
    d = decide("context_length", "codex", 0, 0, 12, current_tier="standard")
    check("ctx-standard", d["action"], "reroute", d["escalate_tier"])
    check("ctx-standard-non-pool-keeps-its-recorded-assignment",
          True, True, d["clear_assignment"] is False)
    d = decide("context_length", "codex", 0, 0, 12, current_tier="light",
               pool_routed=True)
    check("ctx-pool-clears-the-now-stale-pool-assignment", d["action"], "reroute",
          d["escalate_tier"] is True and d["clear_assignment"] is True)
    d = decide("none", "codex", 0, 0, 12, retry_after=30)
    check("earliest-reset-not-leaked-onto-proceed", d["action"], "proceed",
          d.get("earliest_reset_seconds") is None)
    d = decide("rate_limited", "codex", 0, 0, 12, retry_after=30, jitter=False)
    check("earliest-reset-not-leaked-onto-an-ordinary-retry", d["action"], "retry",
          d.get("earliest_reset_seconds") is None)
    d = decide("auth", "codex", 0, 0, 12, retry_after=30)
    check("earliest-reset-not-leaked-onto-a-structural-auth-halt", d["action"], "halt",
          d.get("earliest_reset_seconds") is None)
    d = decide("context_length", "codex", 0, 0, 12, current_tier="deep", retry_after=30)
    check("earliest-reset-not-leaked-onto-a-structural-deepest-tier-halt",
          d["action"], "halt", d.get("earliest_reset_seconds") is None)
    d = decide("model_unavailable", "codex", 0, 0, 12, assigned_model="gpt-5.6-sol",
               retry_after=30)
    check("earliest-reset-not-leaked-onto-a-structural-model-unavailable-halt",
          d["action"], "halt", d.get("earliest_reset_seconds") is None)
    d = decide("rate_limited", "codex", 3, 0, 12, retry_after=30, jitter=False)
    check("earliest-reset-present-on-a-genuine-per-class-exhaustion-halt",
          d["action"], "halt", d.get("earliest_reset_seconds") == 30)
    d = decide("out_of_credits", "codex", 0, 0, 12, retry_after=30,
               fallback_available=False)
    check("earliest-reset-present-on-a-genuine-out-of-credits-no-fallback-halt",
          d["action"], "halt", d.get("earliest_reset_seconds") == 30)
    d = decide("rate_limited", "codex", 1, 12, 12, retry_after=30, jitter=False)
    check("earliest-reset-present-on-a-genuine-run-budget-exhausted-halt",
          d["action"], "halt", d.get("earliest_reset_seconds") == 30)

    # PR 3 intent-only cases.
    now = "2026-08-01T07:20:00Z"
    d = decide("rate_limited", "zai", 0, 0, 12, retry_after=30,
               pool_routed=True, assigned_model="glm-5.2",
               attempt_id="task-a:1", now=now, jitter=False)
    check("pool-first-short-rate-limit-retries-same-assignment",
          d["action"], "retry",
          d["backoff_seconds"] == 30.0
          and not d["advance_pool"] and d["consume_total_retry"])

    d = decide("rate_limited", "zai", 1, 1, 12, retry_after=30,
               pool_routed=True, assigned_model="glm-5.2",
               attempt_id="task-a:2", now=now, jitter=False)
    check("pool-second-short-rate-limit-cools-and-advances",
          d["action"], "reroute",
          d["backoff_seconds"] == 0
          and d["cooldown_backend"] == "zai"
          and d["cooldown_reason"] == "rate_limited"
          and d["cooldown_until"] == "2026-08-01T07:20:30Z"
          and d["advance_pool"] and d["consume_total_retry"])

    d = decide("overloaded", "codex", 1, 1, 12, pool_routed=True,
               assigned_model="gpt-5.6-terra", attempt_id="task-a:3",
               now=now, jitter=False)
    check("pool-second-overload-cools-and-advances", d["action"], "reroute",
          d["cooldown_reason"] == "overloaded" and d["advance_pool"])

    d = decide("usage_window_exhausted", "zai", 0, 0, 12,
               retry_at="2026-08-05T00:00:00Z", pool_routed=True,
               assigned_model="glm-5.2", attempt_id="task-b:1",
               now=now, jitter=False)
    check("explicit-usage-window-advances-without-futile-retry",
          d["action"], "reroute",
          d["backoff_seconds"] == 0
          and d["cooldown_until"] == "2026-08-05T00:00:00Z"
          and d["cooldown_reason"] == "usage_window_exhausted"
          and d["advance_pool"])

    d = decide("usage_window_exhausted", "zai", 0, 0, 12,
               retry_at="2026-07-31T00:00:00Z", pool_routed=True,
               assigned_model="glm-5.2", attempt_id="task-b:2", now=now)
    check("past-usage-reset-is-immediately-probe-eligible",
          d["action"], "reroute",
          d["cooldown_until"] == "2026-08-01T07:20:00Z")

    d = decide("model_unavailable", "zai", 0, 0, 12,
               pool_routed=True, assigned_model="glm-5.2",
               attempt_id="task-c:1", now=now)
    check("model-unavailable-excludes-exact-assignment-only",
          d["action"], "reroute",
          d["advance_pool"]
          and d["exclude_assignment"] == {
              "backend": "zai", "model": "glm-5.2"}
          and d["cooldown_backend"] is None and not d["circuit_break"])

    d = decide("rate_limited", "zai", 0, 0, 12, retry_after=61,
               pool_routed=True, assigned_model="glm-5.2",
               attempt_id="task-d:1", now=now, jitter=False)
    check("pool-never-sleeps-a-61-second-provider-minimum",
          d["action"], "reroute",
          d["backoff_seconds"] == 0
          and d["cooldown_until"] == "2026-08-01T07:21:01Z"
          and d["advance_pool"])

    d = decide("rate_limited", "zai", 0, 0, 12, retry_after=61,
               pool_routed=False, jitter=False, now=now)
    check("never sleep 61s", d["action"], "halt",
          d["backoff_seconds"] == 0
          and d["next_retry_at"] == "2026-08-01T07:21:01Z")

    d = decide("rate_limited", "zai", 3, 0, 12, retry_after=3600,
               pool_routed=False, jitter=False, now=now)
    check("known-long-reset-survives-per-class-exhaustion",
          d["action"], "halt",
          d["backoff_seconds"] == 0
          and d["next_retry_at"] == "2026-08-01T08:20:00Z")

    d = decide("rate_limited", "zai", 0, 12, 12, retry_after=3600,
               pool_routed=False, jitter=False, now=now)
    check("known-long-reset-survives-run-budget-exhaustion",
          d["action"], "halt",
          d["backoff_seconds"] == 0
          and d["next_retry_at"] == "2026-08-01T08:20:00Z")

    d = decide("rate_limited", "zai", 0, 0, 12, retry_after=60,
               pool_routed=False, jitter=False, now=now)
    check("exactly-60-seconds-remains-inline", d["action"], "retry",
          d["backoff_seconds"] == 60.0)

    d = decide("rate_limited", "zai", 0, 0, 12, retry_after=59,
               pool_routed=True, assigned_model="glm-5.2",
               attempt_id="task-d:2", now=now, jitter=True,
               jitter_seconds=1)
    check("pool-provider-minimum-plus-jitter-at-60-stays-inline",
          d["action"], "retry", d["backoff_seconds"] == 60.0)
    d = decide("rate_limited", "zai", 0, 0, 12, retry_after=60,
               pool_routed=True, assigned_model="glm-5.2",
               attempt_id="task-d:3", now=now, jitter=True,
               jitter_seconds=1)
    check("pool-provider-minimum-plus-jitter-at-61-does-not-sleep",
          d["action"], "reroute",
          d["backoff_seconds"] == 0
          and d["cooldown_until"] == "2026-08-01T07:21:01Z")

    d = decide("out_of_credits", "zai", 0, 0, 12,
               pool_routed=True, assigned_model="glm-5.2",
               attempt_id="task-e:1", now=now)
    check("pool-credit-failure-preserves-permanent-breaker-intent",
          d["action"], "reroute",
          d["circuit_break"] and d["circuit_break_backend"] == "zai"
          and d["advance_pool"] and d["cooldown_backend"] is None)

    d = decide("auth", "zai", 0, 0, 12, pool_routed=True,
               assigned_model="glm-5.2", attempt_id="task-e:2", now=now)
    check("auth-preserves-reason-specific-permanent-breaker",
          d["action"], "halt",
          d["circuit_break"] and d["circuit_break_backend"] == "zai"
          and not d["advance_pool"])

    d = decide("network", "codex", 0, 0, 12, pool_routed=True,
               assigned_model="gpt-5.6-terra", attempt_id="task-f:1",
               network_scope="no_response", correlated_network_failures=1,
               completed_provider_success=False, now=now, jitter=False)
    check("single-network-failure-keeps-bounded-same-assignment-retry",
          d["action"], "retry",
          d["backoff_seconds"] == 2.0
          and not d["network_pause"] and not d["advance_pool"])

    d = decide("network", "zai", 0, 1, 12, pool_routed=True,
               assigned_model="glm-5.2", attempt_id="task-g:1",
               network_scope="no_response", correlated_network_failures=2,
               completed_provider_success=False, now=now, jitter=False)
    check("two-correlated-no-response-failures-open-network-pause-intent",
          d["action"], "halt",
          d["network_pause"]
          and d["next_retry_at"] == "2026-08-01T07:21:00Z"
          and d["backoff_seconds"] == 0 and not d["consume_total_retry"])

    d = decide("network", "zai", 1, 1, 12, pool_routed=True,
               assigned_model="glm-5.2", attempt_id="task-g:2",
               network_scope="provider_reported",
               correlated_network_failures=9,
               completed_provider_success=False, now=now, jitter=False)
    check("provider-reported-network-never-opens-global-pause",
          d["action"], "reroute",
          not d["network_pause"] and d["advance_pool"]
          and d["cooldown_reason"] == "network")

    d = decide("network", "zai", 1, 1, 12, pool_routed=True,
               assigned_model="glm-5.2", attempt_id="task-g:3",
               network_scope="no_response", correlated_network_failures=1,
               completed_provider_success=True, now=now, jitter=False)
    check("completed-sibling-success-permits-endpoint-cooldown",
          d["action"], "reroute",
          not d["network_pause"] and d["advance_pool"])

    d = decide("rate_limited", "zai", 1, 12, 12, retry_after=30,
               pool_routed=True, assigned_model="glm-5.2",
               attempt_id="task-h:2", now=now, jitter=False)
    check("run-budget-exhaustion-halts-before-pool-advance",
          d["action"], "halt",
          not d["advance_pool"] and not d["consume_total_retry"])

    d = decide("usage_window_exhausted", "zai", 0, 12, 12,
               retry_at="2026-08-05T00:00:00Z", pool_routed=True,
               assigned_model="glm-5.2", attempt_id="task-h:3",
               now=now, jitter=False)
    check("budget-halt-still-persists-explicit-usage-window",
          d["action"], "halt",
          d["backoff_seconds"] == 0
          and d["cooldown_backend"] == "zai"
          and d["cooldown_reason"] == "usage_window_exhausted"
          and d["cooldown_until"] == "2026-08-05T00:00:00Z"
          and d["next_retry_at"] == "2026-08-05T00:00:00Z"
          and not d["advance_pool"] and not d["consume_total_retry"])

    legacy_keys = {
        "failure_class", "attempt_id", "result", "backend",
        "action", "reason", "backoff_seconds", "reroute_to", "escalate_tier",
        "circuit_break", "next_pool_index", "consume_total_retry",
        "earliest_reset_seconds", "clear_assignment", "circuit_break_backend",
    }
    intent_keys = {
        "cooldown_backend", "cooldown_reason", "cooldown_until", "advance_pool",
        "network_pause", "next_retry_at", "network_scope", "exclude_assignment",
    }
    check("output-retains-legacy-and-adds-intent-keys", True, True,
          legacy_keys | intent_keys == set(d.keys()))

    rejects("policy-rejects-routing-token",
            lambda: decide("rate_limited", "pool", 0, 0, 12))
    rejects("policy-does-not-accept-pool-members",
            lambda: decide("rate_limited", "zai", 0, 0, 12,
                           pool_members=[{"backend": "zai"}]))
    rejects("model-unavailable-requires-exact-model",
            lambda: decide("model_unavailable", "zai", 0, 0, 12,
                           pool_routed=True))
    rejects("negative-provider-delay-fails-closed",
            lambda: decide("rate_limited", "zai", 0, 0, 12,
                           retry_after=-1))
    rejects("invalid-network-scope-fails-closed",
            lambda: decide("network", "zai", 0, 0, 12,
                           network_scope="internet_maybe"))
    rejects("bool-correlated-count-fails-closed",
            lambda: decide("network", "zai", 0, 0, 12,
                           correlated_network_failures=True))
    for attempts, total_retries, max_total_retries in (
            (-100, 0, 12), (0, -100, 12), (0, 0, -100),
            (True, 0, 12), (0, False, 12), (0, 0, True),
            (0.5, 0, 12), (0, 0.5, 12), (0, 0, 12.5), (0, 0, 0)):
        rejects(
            "retry-counters-reject-%r-%r-%r"
            % (attempts, total_retries, max_total_retries),
            lambda a=attempts, t=total_retries, m=max_total_retries:
                decide("rate_limited", "codex", a, t, m, jitter=False),
        )

    print("SELFTEST: %d ok, %d fail" % (ok, fail))
    return 0 if fail == 0 else 1


def _build_parser():
    parser = argparse.ArgumentParser(
        description="Decide transition intent for a classified backend failure.")
    parser.add_argument("--failure-class")
    parser.add_argument("--backend", choices=CONCRETE_BACKENDS, default="codex")
    parser.add_argument("--attempts", type=int, default=0)
    parser.add_argument("--total-retries", type=int, default=0)
    parser.add_argument("--max-total-retries", type=int, default=12)
    parser.add_argument("--retry-after", type=float, default=0)
    parser.add_argument("--retry-at")
    parser.add_argument("--now")
    parser.add_argument("--fallback-open", action="store_true")
    parser.add_argument("--current-tier", choices=["deep", "standard", "light"])
    parser.add_argument("--pool-routed", action="store_true")
    parser.add_argument("--assigned-model")
    parser.add_argument("--attempt-id")
    parser.add_argument("--network-scope",
                        choices=["no_response", "provider_reported"])
    parser.add_argument("--correlated-network-failures", type=int, default=0)
    parser.add_argument("--completed-provider-success", action="store_true")
    parser.add_argument("--no-jitter", action="store_true")
    parser.add_argument("--jitter-seconds", type=float)
    parser.add_argument("--selftest", action="store_true")
    return parser


def main(argv):
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.selftest:
        return _selftest()
    if not args.failure_class:
        parser.error("--failure-class is required (or use --selftest)")

    decision = decide(
        args.failure_class,
        args.backend,
        args.attempts,
        args.total_retries,
        args.max_total_retries,
        retry_after=args.retry_after,
        retry_at=args.retry_at,
        jitter=not args.no_jitter,
        fallback_available=not args.fallback_open,
        current_tier=args.current_tier,
        pool_routed=args.pool_routed,
        assigned_model=args.assigned_model,
        attempt_id=args.attempt_id,
        now=args.now,
        network_scope=args.network_scope,
        correlated_network_failures=args.correlated_network_failures,
        completed_provider_success=args.completed_provider_success,
        jitter_seconds=args.jitter_seconds,
    )
    print(json.dumps(decision))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
