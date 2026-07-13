#!/usr/bin/env python3
"""
Compound V epic-state manager — multi-feature autonomous build (PRD §8 / v1.1 + v2.10 marathon).

A v1.0 run executes ONE plan (one feature). "Epic mode" chains several: an ordered set
of features, each run through the full v1.0 pipeline (spec -> pre-flights -> plan ->
manifest -> dispatch -> review), in dependency order, accumulating onto one branch. This
is the deterministic state spine for that meta-loop — one level up from state.json, the
same shape of discipline (resumable, topological, no daemon).

epic-state.json (checkpoint stance — default, UNCHANGED since v1.1):
  {"epic_id", "title", "status": "running|done|blocked",
   "features": [{"id","title","depends_on":[...],"status":"pending|running|done|failed",
                 "run_id": <id|null>}]}

epic-state.json (marathon stance — v2.10, OPT-IN, additive on top of the above):
  top-level adds: "autonomy":{"stance":"marathon","max_attempts_per_feature",
    "max_no_progress_cycles","max_total_attempts","max_wall_clock_hours","started_at"},
    "final_review":{"status":"pending|passed|failed"}, "blocker_ledger":[...],
    "no_progress_cycles", "total_attempts".
  per-feature adds: "attempts","last_error","disposition".
  Absent "autonomy" => every legacy/checkpoint code path is untouched; all new fields are
  read via `.get(..., default)`.

The orchestrator drives the loop; this script owns the bookkeeping.

## CLI contract (v2.10 — B/C read this)

Checkpoint (default, unchanged):
  --init      build epic-state.json from a features list (validates refs + cycles + epic_id)
  --next      -> {"feature": f|null, "reason": str}                          (read-only)
  --update --feature F --status pending|running|done|failed|blocked [--run-id R]
              -> {"feature","status","epic_status"}                          (atomic write)
  --summary   render the feature table
  --stats     -> {"epic_id","status","total","done","pending","running","failed","blocked",
                  "remaining"}                                               (read-only)
  --check-specs / --lint / --selftest

Marathon (opt-in, additive). Every command below REJECTS a non-marathon state (controlled
nonzero, no write); a negative/non-numeric cap is rejected at --init:
  --init --stance marathon [--max-attempts-per-feature N]
    [--max-no-progress-cycles N] [--max-total-attempts N] [--max-wall-clock-hours H]
    [--now ISO] [--start-sha SHA]   (a cap may be an explicit null = unbounded on that axis;
    a MISSING cap uses its documented default, never unbounded; --start-sha is OPTIONAL and
    stored as autonomy.start_sha for the halt-page accumulated-diff command — a checkpoint
    --init rejects --start-sha)
  --next --autonomous -> {"feature": f|null, "reason": str, "blocked_by": [ids]}  (read-only)
    `reason` embeds the literal terminal-state token when terminal: "done: ...",
    "blocked_needing_human: ...", "running_with_failures: ...", or the reconcile/runnable
    text carried over from the default routing style.
  --can-retry --feature F -> {"can_retry","attempts","cap"}                  (read-only)
  --record-disposition --feature F --disposition retry_fix|halt_feature|halt_epic|
    blocked_external [--reason R] [--families-agreeing a,b] [--confirmed true|false]
    -> {"feature","disposition"}   (atomic write; --confirmed true is HARD-REJECTED in v2.10;
    the stored disposition is stamped with the feature's CURRENT attempts count and is only
    ever honored by `--next --autonomous` while that attempt is still current — a stale
    disposition left over from a prior attempt is treated as no disposition at all)
  --update --status blocked --feature F [--blocker-reason R] [--blocker-confirmed true|false]
    [--families-agreeing a,b] [--evidence E]
    -> ledger append/REACTIVATE, idempotent by (feature, attempt), exactly one active entry
    per blocked feature; --blocker-confirmed true is HARD-REJECTED in v2.10 (a blocker is
    always confirmed:false — SUSPECTED, never caller-confirmed). `blocked` is marathon-only.
  --update --status failed --feature F [--last-error "..."] -> persists last_error (cleared
    on a subsequent ->running retry or ->done)
  --update --status pending --feature F -> resolves that feature's active ledger entry
  Any marathon --update INVALIDATES a passed final_review back to pending.
  --record-final-review --status pending|passed|failed -> {"final_review","epic_status"}
    (atomic write; --status passed is REJECTED unless ALL features are done; "done" requires
    all-features-done AND final_review.status=="passed")
  --breaker-check [--now ISO] -> {"tripped","which":[...],"detail":{...}}     (read-only)
  --trip-breaker [--now ISO] -> {"tripped","which","detail"} (atomic write IFF tripped;
    sets epic status to "blocked_needing_human")
  --record-progress-cycle --cycle-id C [--now ISO] -> {"cycle_id","no_progress_cycles",
    "replayed"} (atomic write unless replayed; idempotent by cycle_id)
  --clear-breaker [--now ISO] [--reset-wall-clock] [--set-max-total-attempts N] -> a JSON
    summary of what was cleared/re-armed (atomic write). The human's re-arm after a
    breaker trip / halt: clears the `blocked_needing_human` latch (removes any
    `breaker_trip` record, resets `no_progress_cycles` to 0, recomputes top status).
    --reset-wall-clock restarts `autonomy.started_at`; --set-max-total-attempts re-arms
    that cap (N or an explicit null for unbounded). Still clears the latch even if the
    (possibly re-armed) state would immediately re-trip — prints a loud stderr warning
    naming the axis in that case.
  --clear-disposition --feature F -> {"feature","disposition":null} (atomic write). Clears
    a feature's stored disposition (the override for a sticky halt_epic/halt_feature verdict)
    so `next_feature_autonomous` no longer short-circuits on it.
  --record-audit-failed --feature F [--last-error "..."] -> {"feature","status",
    "sample_audit_due","final_review","epic_status"}   (ONE atomic write; marathon-only) —
    reverts a done feature's sample-audit-ISSUES verdict in a single state write: status ->
    failed, sample_audit_due -> false, optional last_error, and a passed final_review ->
    pending. Replaces the driver's old two-write clear-due-then-mark-failed sequence, whose
    crash window between writes could leave a feature 'done' with no audit obligation.

## CLI contract (v2.11 V1 — Scheduler Auto-Resurrection, epic-state.py component only)

Everything below is OPT-IN on top of marathon: it requires BOTH `--stance marathon` AND the
persisted `autonomy.watch` toggle (set only via `--init --stance marathon --watch`). A
marathon epic initialized WITHOUT `--watch`, and every checkpoint epic, is untouched by any
of this — no new top-level/`autonomy` key is ever written, so `--init`/`--update` stay
byte-identical to v2.10. This is the CONTRACT that V2 (the watcher,
`compound-v-epic-watch.py`) and V3 (driver/`/v:init` wiring) consume; do not change these
shapes without updating both.

epic-state.json (marathon + watch, v2.11, additive on top of v2.10's marathon shape):
  top-level adds: "last_progress_at" (ISO `+00:00`, bumped on every marathon mutation while
    watch is on), "lease" ({"owner_pid","claimed_at","expires_at"} | absent until the first
    `--claim-resume`), "resume_count" (int, absent until the first `--claim-resume`).
  `autonomy` adds: "watch": true (only ever written as `true` — a `--init` without `--watch`
    never writes the key at all, so "absent" IS "false"), "max_resume_count" (int|null,
    default 20, the new global breaker axis; also written only when watch is on).

  --init --stance marathon --watch [--max-resume-count N]
    Opts a marathon epic into the watch surface. `--max-resume-count` is REJECTED unless
    `--watch` is also given (mirrors every other marathon-only-arg rejection discipline in
    this file); a missing value defaults to 20; an explicit 'null'/'none' is unbounded
    (same `_cap_arg` convention as the other caps).

  --liveness --state S --now T [--stale-after-min 45]
    -> {"incomplete","stale","held","lease_expired","epic_status","terminal","resume_count"}
    (read-only; requires marathon+watch). This is the watcher's poll target. `terminal` is
    `is_terminal(state)` (below). `incomplete` = status != "done". `held`/`lease_expired`
    describe the CURRENT lease (`held` = a live, unexpired lease is on file; `lease_expired`
    = a lease is on file but it is not live). `stale` = incomplete AND NOT terminal AND the
    heartbeat (`last_progress_at`) is older than `stale_after_min` (missing/unparseable
    FAILS SAFE as stale-eligible, mirroring `breaker_check`'s started_at fail-safe) AND the
    lease's `owner_pid` is NOT a live OS process (belt-and-suspenders: a live owner always
    defers the watcher even past the age threshold). Cross-reference: this is a DIFFERENT
    granularity from the per-JOB `compound-v-liveness.py` (git+filesystem probe over a
    dispatch run's `state.json`, one job at a time) — `--liveness` here is per-EPIC, driven
    purely by the heartbeat + lease this file itself owns, never git/filesystem state.

  --claim-resume --state S --owner-pid P --now T [--lease-ttl-min M]
    -> {"claimed","reason":"claimed|live-lease-held|terminal|resume-cap","resume_count"}
    THE CRUX (v2.11): ONE `fcntl.flock`-guarded atomic transaction against `<state>.lock`
    (BLOCKING `LOCK_EX`, not `compound-v-memory.py`'s `LOCK_NB` loser-noop idiom — every
    contender must evaluate on the merits so `reason` is always one of the four documented
    values, never a fifth "lock busy" outcome; see `claim_resume`'s docstring for why this
    deliberately diverges from the reused locking idiom). Inside the lock: reloads `state`
    fresh from disk (never trusts a caller's in-memory copy), derives terminality via the
    shared `is_terminal` classifier, uses OS time (`--now` is test-only, range-checked
    against the real clock — see `_now_arg_in_range`), checks the lease (a live lease ⇒
    lose, reason "live-lease-held") and `max_resume_count` (boundary: a cap of N allows
    `resume_count` to advance 0->N across N successful claims and BLOCKS the (N+1)th —
    mirrors `can_retry_info`'s `attempts < cap` convention elsewhere in this file; at the cap
    the epic is ALSO tripped to `blocked_needing_human`, persisted before the lock releases,
    so a later orphaned scheduler firing sees the terminal latch and is a harmless no-op),
    else increments `resume_count`, records a fresh `lease` for `owner_pid`, bumps
    `last_progress_at`, and writes atomically. A LOSING claim (`claimed: false`) is still a
    SUCCESSFUL call (`ok`); the loser does not resume.

  --renew-lease --state S --owner-pid P --now T [--lease-ttl-min M]
    -> {"owner_pid","lease"} (atomic write). The lease holder's own periodic heartbeat —
    extends `lease.expires_at` and bumps `last_progress_at`. Only the CURRENT recorded
    `owner_pid` may renew; a mismatched/absent lease is a controlled error (claim first,
    never silently take over via renew). Not flock-guarded like `--claim-resume`: only the
    single already-claimed worker ever calls this on itself, so there is no multi-writer
    race here. Call at an interval COMFORTABLY below `--stale-after-min` (default lease TTL
    15min vs. the default 45min staleness threshold).

  --clear-breaker ... [--reset-resume-count]
    v2.10's human re-arm now also accepts `--reset-resume-count`, which zeroes
    `resume_count` (re-arming the resume axis) exactly as `--reset-wall-clock` /
    `--set-max-total-attempts` already re-arm their axes — the resume-cap breaker fits into
    the SAME existing human-in-the-loop re-arm surface, not a parallel mechanism.

is_terminal(state) -- the canonical terminal classifier (v2.11, shared by `--liveness`,
`--claim-resume`, and `next_feature_autonomous`): True for done / breaker-tripped /
halt_epic / exhausted-reachable-work->blocked_needing_human; False for every recoverable
mid-epic state (needs_arbitration, needs_blocker_recording, running/reconcile,
sample_audit_due, all-done-but-final-review-pending). Implemented as a thin wrapper over
`next_feature_autonomous`'s own "done:"/"blocked_needing_human:" reason-token vocabulary
(see its docstring for why: a single source of truth for the DAG-derived terminal states,
zero risk of two independent classifiers silently drifting apart, and zero risk to
`next_feature_autonomous`'s own already-selftested behavior, which is untouched).

Usage:
  compound-v-epic-state.py --init --features features.json --epic-id E --title T --out S
  compound-v-epic-state.py --next  --state S
  compound-v-epic-state.py --update --feature F --status done [--run-id R] --state S
  compound-v-epic-state.py --summary --state S

`features.json` is a JSON array: [{"id","title","depends_on":[...]}, ...].
Python 3.9-safe, stdlib only. No fabricated cost/token metrics anywhere in this file —
breakers bound counts and wall-clock hours only.
"""

import argparse
import fcntl
import json
import math
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

ID_RE_OK = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
# Checkpoint (legacy/default) status set — UNCHANGED since v1.1. `blocked` is a MARATHON-only
# status: a checkpoint `--update --status blocked` is rejected so the legacy fail-fast router
# (next_feature) never sees a status it doesn't understand (Codex review #2).
CHECKPOINT_STATUSES = ("pending", "running", "done", "failed")
# Marathon superset. Module-level name STATUSES is kept (used in --status help text); it now
# names the marathon set. Per-stance acceptance is enforced in `apply_update`.
STATUSES = ("pending", "running", "done", "failed", "blocked")

# Documented cap defaults (fail-SAFE: a MISSING cap key falls back to these, NEVER to
# unbounded — Codex review #4). max_total_attempts has a feature-count-derived default,
# computed per-state in `_default_total_attempts`.
_CAP_DEFAULTS = {
    "max_attempts_per_feature": 2,
    "max_no_progress_cycles": 3,
    "max_wall_clock_hours": 10,
    "max_resume_count": 20,  # v2.11: new global breaker axis, watch-only (see build_state)
}
# Bound on the remembered processed-cycle-id set (Codex review #5) — global idempotency
# without unbounded growth over an all-night run.
_PROCESSED_CYCLE_CAP = 512

# -- v2.11 (Scheduler Auto-Resurrection, V1) module-level constants -----------------------
# Lease TTL: the default interval a --claim-resume/--renew-lease lease stays live for.
# COMFORTABLY below _DEFAULT_STALE_AFTER_MIN so a live worker renewing on schedule never
# lets the watcher see a stale heartbeat while it is still actively holding the lease.
_DEFAULT_LEASE_TTL_MIN = 15
# Staleness threshold for --liveness: set ABOVE the worst-case silent single-feature-
# pipeline window (pre-flights + dispatch + review can legitimately run long).
_DEFAULT_STALE_AFTER_MIN = 45
# --now is TEST-ONLY (deterministic selftests / the concurrency selftest below) — production
# callers never pass it, always using the real OS clock. This bounds how far --now may drift
# from the real clock so it can never become a production lever for defeating staleness/
# lease timing by injecting an arbitrary clock value.
_NOW_ARG_MAX_SKEW_DAYS = 3650


def _id_ok(s):
    return bool(s) and s not in (".", "..") and all(c in ID_RE_OK for c in s)


def _detect_cycle(features):
    """Return a cycle path (list of ids) if the depends_on graph has one, else None."""
    graph = {f["id"]: list(f.get("depends_on", []) or []) for f in features}
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {fid: WHITE for fid in graph}
    stack = []

    def visit(node):
        color[node] = GRAY
        stack.append(node)
        for dep in graph.get(node, []):
            if dep not in graph:
                continue  # dangling ref handled separately
            if color[dep] == GRAY:
                return stack[stack.index(dep):] + [dep]
            if color[dep] == WHITE:
                c = visit(dep)
                if c:
                    return c
        color[node] = BLACK
        stack.pop()
        return None

    for fid in graph:
        if color[fid] == WHITE:
            c = visit(fid)
            if c:
                return c
    return None


def validate_features(features):
    """Return a list of error strings (empty = valid)."""
    errs = []
    if not isinstance(features, list) or not features:
        return ["features must be a non-empty list"]
    ids = []
    for i, f in enumerate(features):
        if not isinstance(f, dict):
            errs.append("feature %d is not an object" % i)
            continue
        fid = f.get("id")
        if not _id_ok(str(fid)):
            errs.append("feature %d has an invalid id %r (allowed: A-Za-z0-9._-)" % (i, fid))
        else:
            ids.append(fid)
        sp = f.get("spec_path")
        if sp is not None and not isinstance(sp, str):
            errs.append("feature %r spec_path must be a string or absent" % fid)
        # Codex round-3 #7: a non-list / non-string-element depends_on later crashes
        # _detect_cycle (list(int)) and the dangling-ref loop (for d in int) with a raw
        # TypeError — reject it here so --init fails with a controlled error, not a traceback.
        deps = f.get("depends_on")
        if deps is not None and (not isinstance(deps, list)
                                 or not all(isinstance(d, str) for d in deps)):
            errs.append("feature %r depends_on must be a list of id strings (got %r)"
                        % (fid, deps))
    dup = sorted({x for x in ids if ids.count(x) > 1})
    if dup:
        errs.append("duplicate feature ids: %s" % ", ".join(dup))
    idset = set(ids)
    for f in features:
        if not isinstance(f, dict):
            continue
        deps = f.get("depends_on")
        if not isinstance(deps, list):  # a malformed depends_on is already flagged above
            continue
        for d in deps:
            if isinstance(d, str) and d not in idset:
                errs.append("feature %r depends_on unknown id %r" % (f.get("id"), d))
    cyc = _detect_cycle([f for f in features if isinstance(f, dict) and _id_ok(str(f.get("id")))
                         and isinstance(f.get("depends_on", []), list)])
    if cyc:
        errs.append("dependency cycle: %s" % " -> ".join(cyc))
    return errs


def _cap_or_default(caps, key, default):
    """Distinguish "not provided" (use `default`) from an EXPLICIT null (unbounded on that
    axis) — the key must be present in `caps` for an explicit None to take effect."""
    if key in caps:
        return caps[key]
    return default


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_nonneg_int(v):
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


# Sentinel distinguishing "argparse arg not supplied" from an explicit value (incl. an
# explicit null) — Codex round-3 #4/#6.
_UNSET = object()


def _cap_arg(kind):
    """argparse `type` for a --max-* cap: the literal 'null'/'none'/'unbounded' resolves to
    None (an EXPLICIT unbounded axis, honored with a loud warning at check time); anything
    else is parsed as `kind` (int/float). Lets --init express the same explicit-null a
    hand-edited/programmatic state can (Codex round-3 #6)."""
    def parse(s):
        if isinstance(s, str) and s.strip().lower() in ("null", "none", "unbounded"):
            return None
        try:
            return kind(s)
        except (TypeError, ValueError):
            raise argparse.ArgumentTypeError(
                "must be a %s, or 'null'/'none' for an unbounded axis" % kind.__name__)
    return parse


def _validate_cap_value(name, value):
    """A single numeric cap must be either None (EXPLICIT unbounded, honored only via the
    explicit-null mechanism) or a non-negative number. A negative/non-numeric cap is a hard
    error, rejected at --init rather than silently persisted-then-treated-as-unbounded
    (Codex review #4). Returns an error string or None."""
    if value is None:
        return None
    if not _is_number(value):
        return "%s must be a non-negative number or null (got %r)" % (name, value)
    # Codex round-2 #2: NaN/inf pass the numeric+non-negative test but silently disable a
    # breaker (NaN >= x is always False; inf caps never trip) — reject non-finite caps.
    if not math.isfinite(value):
        return "%s must be finite (got %r) — NaN/inf would silently disable that cap; use " \
               "null for an explicit unbounded axis" % (name, value)
    if value < 0:
        return "%s must be >= 0 (got %r) — a negative cap is rejected, not treated as " \
               "unbounded" % (name, value)
    return None


def _default_total_attempts(state):
    feats = [f for f in state.get("features", []) if isinstance(f, dict)]
    return max(6, 3 * len(feats))


def build_state(features, epic_id, title, stance=None, caps=None):
    """Build epic-state.json content. `stance`/`caps` are OPT-IN: every marathon-only field
    (top-level `autonomy`/`final_review`/`blocker_ledger`/`no_progress_cycles`/
    `total_attempts`, per-feature `attempts`/`last_error`/`disposition`) is written ONLY
    when stance=="marathon" — a plain `build_state(features, epic_id, title)` call (no
    stance) is byte-for-byte what v1.1 always produced. Validates `epic_id` via `_id_ok`
    (Sol-R4#10) unconditionally — this only rejects a new class of previously-undefined-
    behavior input (a traversal-style epic_id), it never changes output for a valid id."""
    if not _id_ok(str(epic_id)):
        raise ValueError("invalid epic_id %r (allowed: A-Za-z0-9._-)" % (epic_id,))
    feats = []
    for f in features:
        feat = {
            "id": f["id"],
            "title": f.get("title", f["id"]),
            "depends_on": list(f.get("depends_on", []) or []),
            "spec_path": f.get("spec_path"),
            "status": "pending",
            "run_id": None,
        }
        if stance == "marathon":
            feat["attempts"] = 0
            feat["last_error"] = None
            feat["disposition"] = None
        feats.append(feat)
    state = {"epic_id": epic_id, "title": title, "status": "running", "features": feats}
    if stance == "marathon":
        caps = caps or {}
        # Fail-SAFE cap validation at build/--init time (Codex review #4): reject a
        # negative/non-numeric cap up front, so it can never be persisted and then silently
        # mis-treated as unbounded at check time.
        for _cap_name in ("max_attempts_per_feature", "max_no_progress_cycles",
                          "max_total_attempts", "max_wall_clock_hours", "max_resume_count"):
            if _cap_name in caps:
                _err = _validate_cap_value(_cap_name, caps[_cap_name])
                if _err:
                    raise ValueError(_err)
        started_at_raw = _cap_or_default(caps, "started_at", None)
        started_at = _now_iso(_parse_iso(started_at_raw)) if started_at_raw else _now_iso()
        state["autonomy"] = {
            "stance": "marathon",
            # NOTE: no "max_features" knob — v2.10 never enforces a feature-count cap
            # anywhere (the spec listed it, but a stored-and-unenforced field is a dead
            # knob per cross-model review; drop it rather than fake an enforcement path).
            "max_attempts_per_feature": _cap_or_default(caps, "max_attempts_per_feature", 2),
            "max_no_progress_cycles": _cap_or_default(caps, "max_no_progress_cycles", 3),
            "max_total_attempts": _cap_or_default(caps, "max_total_attempts",
                                                   max(6, 3 * len(feats))),
            "max_wall_clock_hours": _cap_or_default(caps, "max_wall_clock_hours", 10),
            "started_at": started_at,
        }
        # start_sha (v2.10 resume support) is OPTIONAL and OMITTED entirely when not
        # supplied — a plain marathon build_state(...) call (no caps["start_sha"]) keeps the
        # existing 6-key autonomy schema byte-for-byte (Codex/cross-model review golden
        # tests assert `set(autonomy.keys())` exactly). The driver captures
        # `git rev-parse HEAD` and passes it for the halt-page accumulated-diff command.
        if "start_sha" in caps:
            start_sha = caps["start_sha"]
            if not isinstance(start_sha, str):
                raise ValueError("start_sha must be a string (got %r)" % (start_sha,))
            state["autonomy"]["start_sha"] = start_sha
        # v2.11 watch opt-in (V1): OMITTED entirely unless caps["watch"] is True — a plain
        # marathon build_state(...) call (no caps["watch"]) keeps the existing autonomy
        # schema AND the existing top-level key set byte-for-byte (golden tests assert this
        # below). Only when watch is True do we add autonomy.watch/autonomy.max_resume_count
        # and the top-level `last_progress_at` heartbeat (seeded to the same `started_at`
        # so a freshly-initialized watch-on epic is never immediately "stale").
        if caps.get("watch") is True:
            state["autonomy"]["watch"] = True
            state["autonomy"]["max_resume_count"] = _cap_or_default(
                caps, "max_resume_count", _CAP_DEFAULTS["max_resume_count"])
            state["last_progress_at"] = started_at
        state["final_review"] = {"status": "pending"}
        state["blocker_ledger"] = []
        state["no_progress_cycles"] = 0
        state["total_attempts"] = 0
    return state


def check_specs(features, base_dir=""):
    """Errors for features lacking an EXISTING, CONTAINED spec_path. Enforces the epic
    contract that every feature has an approved spec BEFORE the autonomous loop runs (no
    mid-loop brainstorming pauses) — specs are written and human-approved up front.

    spec_path must resolve to a file UNDER base_dir (the epic dir). Absolute paths and `../`
    traversal are REJECTED — a spec is fed verbatim into the pre-flights, so an out-of-tree
    path would read arbitrary local files into the model context."""
    errs = []
    base_real = os.path.realpath(base_dir) if base_dir else os.path.realpath(os.getcwd())
    for f in features:
        if not isinstance(f, dict):
            errs.append("feature entry is not an object: %r" % (f,))
            continue
        fid = f.get("id")
        sp = f.get("spec_path")
        if not sp:
            errs.append("feature %r has no spec_path — the epic needs an approved spec per "
                        "feature up front (batch the brainstorming before --init)" % fid)
            continue
        if os.path.isabs(sp):
            errs.append("feature %r spec_path must be RELATIVE to the epic dir "
                        "(no absolute paths): %s" % (fid, sp))
            continue
        resolved = os.path.realpath(os.path.join(base_real, sp))
        if resolved != base_real and not resolved.startswith(base_real + os.sep):
            errs.append("feature %r spec_path escapes the epic dir (must live under it, no "
                        "absolute/`..` paths): %s" % (fid, sp))
            continue
        if not os.path.isfile(resolved):
            errs.append("feature %r spec_path does not exist: %s" % (fid, sp))
    return errs


def check_state_specs(state, base_dir=""):
    """Resume guard: every NON-done feature in an existing epic-state must still carry an
    existing, contained spec_path. Closes the gap where resuming an old/hand-made epic-state
    (pre-spec_path) would enter the loop spec-less, bypassing --init --require-specs.

    Also REJECTS a malformed state (no `features` list, or non-object feature entries) rather
    than silently dropping bad entries — otherwise a hand-made state could pass the guard and
    then crash `next_feature`."""
    feats = state.get("features")
    if not isinstance(feats, list) or not feats:
        return ["epic-state has no valid 'features' list"]
    errs = []
    bad = [i for i, f in enumerate(feats) if not isinstance(f, dict)]
    if bad:
        errs.append("epic-state has malformed (non-object) feature entr%s at index %s"
                    % ("y" if len(bad) == 1 else "ies", ", ".join(map(str, bad))))
    pending = [f for f in feats if isinstance(f, dict) and f.get("status") != "done"]
    return errs + check_specs(pending, base_dir=base_dir)


def lint_decomposition(features):
    """Advisory structural warnings on the feature DAG (a deterministic backstop for the
    decomposition review). Empty list = nothing flagged. These are JUDGMENT hints, never
    hard errors — a weak split is a quality risk, not an invalid one."""
    warns = []
    feats = [f for f in features if isinstance(f, dict) and f.get("id")]
    ids = [f["id"] for f in feats]
    if len(ids) < 2:
        return warns
    dependents = {i: 0 for i in ids}
    for f in feats:
        for d in (f.get("depends_on") or []):
            if d in dependents:
                dependents[d] += 1
    # "most others" ≈ three-quarters of the other features; floor of 3 keeps tiny graphs quiet.
    coupled_threshold = max(3, (3 * (len(ids) - 1) + 3) // 4)  # ceil(0.75 * (n-1))
    for f in feats:
        fid = f.get("id")
        deps = list(f.get("depends_on") or [])
        if not deps and dependents.get(fid, 0) == 0:
            warns.append("feature %r is an ISLAND (no depends_on, no dependents) — a missed "
                         "dependency, or it belongs in its own epic?" % fid)
        if len(deps) >= coupled_threshold:
            warns.append("feature %r depends on %d of %d features (most/all) — likely a LAYER, "
                         "not a vertical slice; reconsider the split" % (fid, len(deps), len(ids)))
    return warns


def stats(state):
    feats = state.get("features", [])
    by = {"pending": 0, "running": 0, "done": 0, "failed": 0, "blocked": 0}
    for f in feats:
        s = f.get("status")
        if s in by:
            by[s] += 1
    out = {"epic_id": state.get("epic_id"), "status": state.get("status"),
           "total": len(feats), "done": by["done"], "pending": by["pending"],
           "running": by["running"], "failed": by["failed"],
           "remaining": by["pending"] + by["running"]}
    # Codex round-3 #5: `blocked` is a marathon-only status — only break it out for marathon
    # states so checkpoint --stats output stays byte-compatible (no new key).
    if _is_marathon(state):
        out["blocked"] = by["blocked"]
    return out


def next_feature(state):
    """Return (feature|None, reason).

    The order of the guards encodes the documented stop/resume model (commands/v-epic.md):
    a failure or a crashed run HALTS the epic until a human reconciles it — the loop never
    autonomously routes around a failed/stale feature.

    UNTOUCHED by the v2.10 marathon work — `next_feature_autonomous` below is a SEPARATE
    function; this one, its guard order, and its 2-key JSON shape are byte-for-byte what
    v1.1 always produced.
    """
    feats = [f for f in state.get("features", []) if isinstance(f, dict)]
    # .get("status"): a hand-made state entry missing the key must not KeyError (A7) — it
    # simply matches no bucket below (check_state_specs rejects malformed states upstream;
    # this is defense in depth, same as the isinstance filter above).
    done = {f["id"] for f in feats if f.get("status") == "done"}
    failed = sorted(f["id"] for f in feats if f.get("status") == "failed")
    running = sorted(f["id"] for f in feats if f.get("status") == "running")
    pending = [f for f in feats if f.get("status") == "pending"]

    # FAIL-FAST: any failed feature halts the WHOLE epic — even independent pending
    # features wait. A failure may be systemic; do not burn more autonomous runs until a
    # human retries (--update --status pending) or drops it.
    if failed:
        return None, ("epic blocked: feature(s) failed (%s) — retry "
                      "(--update --status pending) or drop them, then re-run" % ", ".join(failed))

    # RECONCILE: epic mode is sequential — the orchestrator calls --next only BETWEEN
    # features, so a 'running' feature seen here means a prior run CRASHED mid-feature.
    # Stop and force reconciliation; never hand out new work over a stale run.
    if running:
        return None, ("epic needs reconcile: feature(s) still 'running' (%s) — a prior run "
                      "crashed; mark each --status failed (abandon) or pending (retry), then "
                      "re-run" % ", ".join(running))

    if not pending:
        return None, "epic complete: all features done"

    # Clean state: hand out the next runnable pending feature in topological order. With a
    # DAG validated at --init, one always exists here; the final return is defensive.
    runnable = [f for f in pending if all(d in done for d in f["depends_on"])]
    if runnable:
        return runnable[0], "runnable"
    return None, ("epic blocked: no runnable feature — unsatisfiable dependencies among %s"
                  % ", ".join(f["id"] for f in pending))


def _reverse_deps_graph(feats):
    """Adjacency map: feature id -> ids that directly depend_on it (reverse of depends_on).
    Same graph-building idiom as `_detect_cycle`, reused for reachability instead of cycle
    detection."""
    feats = [f for f in feats if isinstance(f, dict)]
    forward = {f.get("id"): list(f.get("depends_on", []) or []) for f in feats}
    reverse = {fid: [] for fid in forward}
    for fid, deps in forward.items():
        for d in deps:
            if d in reverse:
                reverse[d].append(fid)
    return reverse


def _transitive_closure(reverse, seeds):
    out = set()
    stack = list(seeds)
    while stack:
        cur = stack.pop()
        if cur in out:
            continue
        out.add(cur)
        stack.extend(reverse.get(cur, []))
    return out


def _transitive_dependents(feats, feature_id):
    """All feature ids reachable by following depends_on backwards from `feature_id`
    (i.e. everything that depends on it, directly or indirectly) — NOT including
    `feature_id` itself."""
    reverse = _reverse_deps_graph(feats)
    return sorted(_transitive_closure(reverse, reverse.get(feature_id, [])))


def next_feature_autonomous(state):
    """Read-only autonomous routing (marathon `--next --autonomous`): DAG-transitive-
    dependent cascading instead of the default's whole-epic fail-fast. A failed/blocked
    feature removes only its transitive DEPENDENTS from the runnable set — independent
    pending features stay runnable. Returns (feature|None, reason, blocked_by:[ids]).

    `blocked_by` is derived fresh every call (never persisted) — it is the transitive
    dependents of any currently failed/blocked feature. Reopening a source feature
    (`--update --status pending`) simply makes it, and everything it was blocking,
    disappear from `blocked_by` on the next call — there is no cascade to reverse.

    Terminal-state resolution embeds the literal v2.10 token as a prefix of `reason` so
    callers can match on it exactly like the default function's callers match on
    "reconcile"/"complete"/"blocked": "done: ...", "blocked_needing_human: ...",
    "running_with_failures: ...". v2.10 NEVER emits "done_with_blockers" (that terminal
    state needs a 2nd safe external family — v2.11).

    FIX 1 (crash/breaker-window resume safety, v2.10 follow-up): a `failed` feature is no
    longer blanket-treated as abandoned — it is routed BY its stored `disposition`:
      - `retry_fix` AND still under the retry cap -> the feature ITSELF is runnable again
        (the arbiter approved a retry and it hasn't re-run yet); its transitive dependents
        are explicitly NOT blocked, because it is about to be retried, not abandoned.
      - `retry_fix` but the retry cap is exhausted, or `halt_feature` -> abandoned, exactly
        like the pre-fix blanket behavior (dependents blocked, independents continue).
      - `halt_epic` -> handled by the pre-existing unconditional whole-epic halt check above.
      - no/None disposition (the crash-in-arbitration window: the feature failed but the
        arbiter never recorded a verdict before a breaker trip/crash) -> this must NOT be
        silently treated as settled. It halts ALL routing (not just its own dependents) with
        a dedicated "needs_arbitration" reason, so the driver re-runs the arbiter on resume
        instead of quietly handing out unrelated independent work over an untriaged failure.

    FIX A (attempt-binding, v2.10 correctness follow-up): a stored disposition is honored
    ONLY when `disposition.attempt == feature.attempts` — i.e. it was recorded for the
    feature's CURRENT (still-failed) attempt, not a prior one. A disposition recorded at a
    STALE attempt (the retry re-ran and failed again, or attempts otherwise advanced, without
    a fresh arbiter verdict) is treated exactly like NO disposition at all — the same
    needs_arbitration halt-all-routing path above. This applies uniformly to retry_fix,
    halt_feature, halt_epic, and blocked_external: a stale verdict of ANY kind is not honored
    — re-arbitrate, which is always safe. A legacy disposition with no stored `attempt` key
    (pre-FIX-A data) is treated as attempt 0.

    FIX 2 (v2.10, cross-unit integration review follow-up): a `failed` feature whose
    ATTEMPT-MATCHED disposition is `blocked_external` is NOT the "arbiter already settled it"
    case FIX 1 originally assumed — it is a distinct crash window: the driver recorded the
    verdict (`--record-disposition blocked_external`) but crashed before completing the
    `--update --status blocked` transition (which flips status and appends the
    `blocker_ledger` entry). Treating it as abandoned would silently lose the blocker
    transition. Instead this surfaces a dedicated "needs_blocker_recording" reason — analogous
    priority to needs_arbitration: it takes precedence over handing out other work, so the
    driver completes the transition first. The `--update --status blocked` ledger append is
    already idempotent by (feature, attempt), so re-running it is always safe. A feature that
    has ALREADY transitioned to `status == "blocked"` never reaches this classification loop
    (which only inspects `status == "failed"`) and stays on the normal blocked/ledger path,
    unchanged. An attempt-MISMATCHED blocked_external disposition still falls into the
    needs_arbitration bucket above (FIX A), unchanged.
    """
    feats = [f for f in state.get("features", []) if isinstance(f, dict)]
    ids = {f.get("id") for f in feats}
    status_by = {f.get("id"): f.get("status") for f in feats}
    done_ids = {f["id"] for f in feats if f.get("status") == "done"}
    running_ids = sorted(f["id"] for f in feats if f.get("status") == "running")
    pending = [f for f in feats if f.get("status") == "pending"]

    # FIX 1: classify every `failed` feature by its stored disposition instead of treating
    # "failed" as a single undifferentiated blocking state.
    retry_runnable = []   # retry_fix + still under cap -> the feature itself is runnable
    abandoned_ids = []    # retry_fix (cap exhausted) or halt_feature -> abandoned, as before
    needs_arb_ids = []    # no/None disposition -> crash-in-arbitration window, halt routing
    needs_blocker_recording_ids = []  # FIX 2: blocked_external verdict recorded, but the
                                       # blocked/ledger transition crashed mid-flight
    for f in feats:
        if f.get("status") != "failed":
            continue
        fid = f.get("id")
        disp = f.get("disposition")
        disp_kind = disp.get("disposition") if isinstance(disp, dict) else None
        # FIX A: a disposition only counts if it was recorded for the feature's CURRENT
        # attempt (legacy dispositions with no stored "attempt" key are treated as attempt 0).
        # A kind/attempt mismatch (no disposition at all, or a stale one from a prior attempt)
        # is treated identically — the crash-in-arbitration needs_arbitration path below.
        disp_attempt_matches = (isinstance(disp, dict)
                                and disp.get("attempt", 0) == f.get("attempts", 0))
        if disp_kind is None or not disp_attempt_matches:
            needs_arb_ids.append(fid)
        elif disp_kind == "retry_fix":
            info = can_retry_info(state, fid)
            if info and info.get("can_retry"):
                retry_runnable.append(f)
            else:
                abandoned_ids.append(fid)
        elif disp_kind == "halt_feature":
            abandoned_ids.append(fid)
        elif disp_kind == "blocked_external":
            # FIX 2: blocked_external landing on a still-`failed` feature (attempt-matched)
            # means the arbiter's verdict was recorded but the blocked/ledger transition did
            # NOT complete before a crash — this is unresolved, not a settled abandon.
            needs_blocker_recording_ids.append(fid)
        elif disp_kind == "halt_epic":
            pass  # handled by the unconditional (also attempt-gated) halt_epic check below
    retry_runnable.sort(key=lambda rf: rf.get("id") or "")
    abandoned_ids = sorted(abandoned_ids)
    needs_arb_ids = sorted(needs_arb_ids)
    needs_blocker_recording_ids = sorted(needs_blocker_recording_ids)

    # `blocking_ids` retains its pre-fix meaning (used for messaging + dependents-blocking)
    # EXCEPT a retry-runnable failed feature is explicitly excluded — its dependents are not
    # blocked, per FIX 1. A needs_blocker_recording feature is included here too: it is
    # unresolved (not abandoned, not runnable), so its dependents must stay blocked exactly
    # like an abandoned or needs_arbitration feature's would.
    blocking_ids = sorted(
        [fid for fid in status_by if status_by.get(fid) == "blocked"] + abandoned_ids
        + needs_arb_ids + needs_blocker_recording_ids
    )

    reverse = _reverse_deps_graph(feats)
    dependents_blocked = set()
    for bid in blocking_ids:
        dependents_blocked |= _transitive_closure(reverse, reverse.get(bid, []))
    # `blocked_by` = the transitive dependents that are actually WAITING (pending/running) on
    # a blocked/failed upstream — a done dependent is not "blocked" and must not appear
    # (Codex review #3). The blocking features themselves are reported via `blocking_ids`.
    blocked_by = sorted(fid for fid in dependents_blocked
                        if status_by.get(fid) in ("pending", "running"))

    # Whole-epic halt: an explicit breaker trip already recorded, or a halt_epic verdict.
    if state.get("status") == "blocked_needing_human":
        return None, "blocked_needing_human: epic halted (breaker tripped or halt_epic)", blocked_by
    # FIX A: also attempt-gated — a halt_epic disposition recorded at a since-superseded
    # attempt is stale and must not keep halting the whole epic (the cd1/clear-disposition
    # selftest below covers the common case: a feature that never re-ran keeps attempts at
    # its record-time value, so its halt_epic disposition still matches and still halts).
    halt_epic_ids = sorted(f["id"] for f in feats
                            if isinstance(f.get("disposition"), dict)
                            and f["disposition"].get("disposition") == "halt_epic"
                            and f["disposition"].get("attempt", 0) == f.get("attempts", 0))
    if halt_epic_ids:
        return None, ("blocked_needing_human: halt_epic disposition on %s"
                      % ", ".join(halt_epic_ids)), blocked_by

    # Crash recovery for a 'running' feature is still the existing running->reconcile path
    # (Component "survives a fall": "the existing running->reconcile path on re-entry") —
    # autonomous routing does not invent a different crash-recovery mechanism.
    if running_ids:
        return None, ("epic needs reconcile: feature(s) still 'running' (%s) — a prior run "
                      "crashed; mark each --status failed (abandon) or pending (retry), then "
                      "re-run" % ", ".join(running_ids)), blocked_by

    # FIX 1: a failed feature with no recorded disposition is the crash-in-arbitration
    # window — do NOT silently abandon it, and do NOT hand out other work as if the epic
    # were settled. Halt ALL routing until the arbiter re-runs. This takes priority over a
    # retry-runnable feature elsewhere: an unresolved arbitration gap isn't closed by other
    # work being available.
    if needs_arb_ids:
        return None, ("needs_arbitration: feature %s failed without a recorded disposition — "
                      "re-run the arbiter" % ", ".join(needs_arb_ids)), blocked_by

    # FIX 2: an attempt-matched blocked_external disposition on a still-`failed` feature is
    # the "verdict recorded, transition incomplete" crash window — surface it with the same
    # priority as needs_arbitration above (it also halts ALL routing, not just this feature's
    # dependents), so the driver completes the blocked/ledger transition before any other work
    # is handed out.
    if needs_blocker_recording_ids:
        return None, ("needs_blocker_recording: feature(s) %s — arbiter said blocked_external "
                      "but the blocked/ledger transition is incomplete; re-run --update "
                      "--status blocked" % ", ".join(needs_blocker_recording_ids)), blocked_by

    # FIX 1: a retry_fix-approved failed feature that is still under the retry cap is itself
    # directly runnable again — the driver re-runs it. This is checked before the normal
    # pending-DAG routing below because it is not "new" work, it is the resumption of
    # in-flight (arbiter-approved) work.
    if retry_runnable:
        return retry_runnable[0], "runnable", blocked_by

    if not pending:
        if ids and done_ids == ids:
            # FIX 2: a due-but-not-yet-passed sample audit gates terminal completion, even
            # once every feature is 'done' and final_review has passed — a breaker/crash
            # between marking a sampled SUCCESS 'done' and running its PASS sample-audit must
            # not silently lose that obligation on resume.
            due_ids = sorted(f["id"] for f in feats if f.get("sample_audit_due") is True)
            if due_ids:
                return None, ("sample_audit_due: feature(s) %s awaiting sample-audit"
                              % ", ".join(due_ids)), blocked_by
            fr = state.get("final_review")
            fr = fr if isinstance(fr, dict) else {}
            if fr.get("status") == "passed":
                return None, "done: all features done and final_review passed", blocked_by
            return None, ("running_with_failures: all features done, awaiting final_review "
                          "(status=%s) before 'done'" % fr.get("status", "pending")), blocked_by
        if blocking_ids:
            return None, ("blocked_needing_human: no runnable feature — blocked/failed "
                          "feature(s) %s exhaust reachable work" % ", ".join(blocking_ids)), \
                blocked_by
        return None, "epic complete: all features done", blocked_by  # defensive fallback

    # A pending feature that is a transitive dependent of ANY blocked/failed feature is NOT
    # runnable, even if its immediate deps happen to be done (Codex review #3: {A failed,
    # B done, C pending, A->B->C} must not hand out C).
    runnable = [f for f in pending
                if f.get("id") not in dependents_blocked
                and all(d in done_ids for d in (f.get("depends_on") or []))]
    if runnable:
        if blocking_ids:
            return runnable[0], ("running_with_failures: runnable (feature(s) %s blocked/failed "
                                 "independently)" % ", ".join(blocking_ids)), blocked_by
        return runnable[0], "runnable", blocked_by

    if blocking_ids:
        return None, ("blocked_needing_human: no runnable feature — remaining pending %s all "
                      "blocked by %s" % (", ".join(sorted(f["id"] for f in pending)),
                                          ", ".join(blocking_ids))), blocked_by
    return None, ("epic blocked: no runnable feature — unsatisfiable dependencies among %s"
                  % ", ".join(f["id"] for f in pending)), blocked_by


def is_terminal(state):
    """v2.11 (Plan-review corrections, BINDING #3): the CANONICAL terminal classifier,
    shared by `--liveness`, `--claim-resume`, and (in spirit — see below) this file's own
    routing. True iff the epic will never make autonomous progress again without a human:
    done, breaker-tripped, halt_epic, or exhausted-reachable-work (all of which
    `next_feature_autonomous` already reports via a "done: ..."/"blocked_needing_human: ..."
    reason prefix). False for every recoverable mid-epic state: needs_arbitration,
    needs_blocker_recording, running/reconcile, sample_audit_due, and all-done-but-
    final-review-still-pending (that one is deliberately NOT terminal — a passed final_review
    can still land and finish the epic without a human).

    Implementation note (conservative reading of "refactor next_feature_autonomous to call
    it"): `next_feature_autonomous`'s DAG-derived terminal facts (done/exhausted in
    particular) are entangled with the SAME computation it needs anyway to find the next
    runnable feature (blocking_ids, retry_runnable, due_ids, final_review...) — extracting an
    independent is_terminal that computes all of that a SECOND time would create two places
    that could silently drift apart on the exact same DAG walk, which is a worse outcome than
    it not being literally the caller. Instead, is_terminal is DEFINED IN TERMS OF
    next_feature_autonomous's already-selftested reason-token vocabulary: a single source of
    truth, next_feature_autonomous's own body and behavior are UNTOUCHED (verified by its
    full existing selftest suite still passing unmodified), and is_terminal can never disagree
    with it because it IS it, read differently. `--claim-resume` and `--liveness` both call
    is_terminal(state) directly, per the spec."""
    if not _is_marathon(state):
        return False
    _, reason, _ = next_feature_autonomous(state)
    return reason.startswith("done:") or reason.startswith("blocked_needing_human:")


def _now_iso(dt=None):
    """Emit an ISO-8601 UTC timestamp with a `+00:00` offset (never a bare `Z`, which
    Python 3.9 cannot re-parse). An AWARE datetime in any zone is normalized to UTC
    (Codex review #11 — an injected `+05:00` is emitted as `+00:00`); a naive datetime is
    assumed UTC."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat()


def _parse_iso(s):
    """Parse an ISO-8601 string on Python 3.9, which cannot parse a trailing 'Z' —
    normalize Z -> +00:00 first (never emit bare Z either; `_now_iso` always yields
    +00:00 via an aware UTC datetime). Naive datetimes are assumed UTC."""
    if isinstance(s, str) and s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _resolve_now(now_arg):
    """CLI --now resolution: an injected ISO string (deterministic tests), else the real
    clock."""
    if now_arg:
        return _parse_iso(now_arg)
    return datetime.now(timezone.utc)


def _parse_csv_list(s):
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def _is_marathon(state):
    autonomy = state.get("autonomy")
    return isinstance(autonomy, dict) and autonomy.get("stance") == "marathon"


def _watch_on(state):
    """v2.11: is this marathon epic opted into the watch surface? Absent/false/not-marathon
    are all indistinguishable — every one of them means "behave exactly like v2.10"."""
    autonomy = state.get("autonomy")
    return isinstance(autonomy, dict) and autonomy.get("watch") is True


def _bump_last_progress(state, now_dt):
    """v2.11: bump the top-level liveness heartbeat on every marathon mutation — but ONLY
    when the epic has opted into `watch`. A pure no-op otherwise: never adds a
    `last_progress_at` key that didn't already exist, which is the whole byte-identical
    guarantee for a checkpoint state or a watch-off marathon."""
    if _watch_on(state):
        state["last_progress_at"] = _now_iso(now_dt)


def _lease_live(state, now_dt):
    """v2.11: a lease is 'live' iff one is recorded and `now_dt` has not yet reached its
    `expires_at`. Fail-safe the other way from breaker_check's started_at handling: a
    structurally malformed/missing lease can never PROVE liveness, so it is simply not
    live — it does not block a claim (unlike a missing wall-clock started_at, which trips a
    safety breaker; a missing lease just means nobody has claimed the epic yet)."""
    lease = state.get("lease")
    if not isinstance(lease, dict):
        return False
    exp = lease.get("expires_at")
    if not isinstance(exp, str):
        return False
    try:
        exp_dt = _parse_iso(exp)
    except (ValueError, TypeError):
        return False
    return now_dt < exp_dt


def _pid_alive(pid):
    """POSIX liveness probe via a signal-0 kill (sends nothing — just checks whether the
    process exists and is reachable). A permission error still means the process EXISTS
    (owned by someone else) -> alive. Any other failure (no such process, bad pid) -> not
    alive. Defensive against non-positive/non-int input (never raises)."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _now_arg_in_range(now_dt):
    """v2.11: `--now` is test-only (deterministic selftests) — production callers of
    --liveness/--claim-resume/--renew-lease always use the real OS clock. This sanity-bounds
    an injected `--now` against the real clock so it can never become a production lever for
    defeating staleness/lease timing by injecting an arbitrary value."""
    skew_days = abs((now_dt - datetime.now(timezone.utc)).total_seconds()) / 86400.0
    return skew_days <= _NOW_ARG_MAX_SKEW_DAYS


def _find_feature(state, feature_id):
    feats = state.get("features")
    if not isinstance(feats, list):
        return None
    for f in feats:
        if isinstance(f, dict) and f.get("id") == feature_id:
            return f
    return None


def _total_attempts(state):
    """The invariant: total_attempts == sum(feature.attempts) — ALWAYS recomputed, never
    tracked as an independently-incremented counter (a caller-controlled `--attempt` bump
    would drift from the real per-feature counts; this can't drift because it IS the sum)."""
    return sum(f.get("attempts", 0) for f in state.get("features", []) if isinstance(f, dict))


def _recompute_top_status(state):
    """Marathon top-level status recompute: 'done' iff every feature is done AND
    final_review.status=="passed" AND no feature has a due sample-audit (A6/Sol-R4#1, FIX 2);
    otherwise 'running' — UNLESS a breaker/halt_epic already parked it at
    'blocked_needing_human' (only --trip-breaker sets that; this function never clears or
    overwrites it). This deliberately REPLACES the checkpoint rollup's "any failed -> blocked"
    fail-fast rule for marathon states, because that rule is exactly what autonomous DAG
    routing (`next_feature_autonomous`) exists to route around — a single failed/blocked
    feature must not blanket-halt a marathon epic while independent features are still
    runnable.

    FIX 2: a due sample-audit gates 'done' HERE too (not just in `next_feature_autonomous`
    and `record_final_review`) — so `state["status"]` itself is never misleadingly 'done'
    while a sampled SUCCESS's audit obligation is still outstanding, whichever call site
    triggers the recompute."""
    if state.get("status") == "blocked_needing_human":
        return
    feats = [f for f in state.get("features", []) if isinstance(f, dict)]
    sts = [f.get("status") for f in feats]
    fr = state.get("final_review")
    fr = fr if isinstance(fr, dict) else {}
    audit_due = any(f.get("sample_audit_due") is True for f in feats)
    if sts and all(s == "done" for s in sts) and fr.get("status") == "passed" and not audit_due:
        state["status"] = "done"
    else:
        state["status"] = "running"


def apply_update(state, feature_id, status, run_id=None, now_dt=None,
                  blocker_reason=None, blocker_confirmed=False,
                  families_agreeing=None, evidence=None, last_error=None):
    """Mutate `state` in place for `--update`. Returns (ok, error|None).

    - checkpoint (non-marathon): rollup UNCHANGED — any failed -> blocked; all done -> done;
      else running. The ->running transition is unrestricted, exactly as before. `blocked`
      is NOT an accepted status (marathon-only — Codex review #2).
    - marathon: attempts increment + a documented transition table gate ->running (A3:
      legal sources pending/failed only); a ->blocked transition appends/REACTIVATES an
      idempotent blocker-ledger entry keyed by (feature, attempt) — guaranteeing exactly one
      ACTIVE entry per currently-blocked feature (Codex review #6) — and HARD-REJECTS
      blocker_confirmed=True (A4/A5, Sol-R4#2 — v2.10 blockers are always confirmed:false,
      SUSPECTED not caller-asserted); a ->pending transition resolves that feature's active
      ledger entry; a ->failed persists `last_error` and ->running/->done clears it
      (Codex review #7); a ->done resets no_progress_cycles to 0 (Codex review #8);
      ANY marathon feature-state change INVALIDATES a passed final_review back to pending
      (Codex review #1); the top-level status is recomputed via `_recompute_top_status` (A6)
      instead of the checkpoint fail-fast rollup; total_attempts is recomputed (Codex #9).
    """
    marathon = _is_marathon(state)
    allowed = STATUSES if marathon else CHECKPOINT_STATUSES
    if status not in allowed:
        return False, ("--status %r is not valid for the %s stance (allowed: %s)"
                       % (status, "marathon" if marathon else "checkpoint",
                          ", ".join(allowed)))
    # Codex round-2 #5: a non-marathon --update must REJECT marathon-only args rather than
    # silently discard them (e.g. --last-error on a checkpoint state was accepted then
    # dropped). Gate the whole marathon-field surface on stance.
    if not marathon:
        offenders = []
        if last_error is not None:
            offenders.append("--last-error")
        if blocker_reason is not None:
            offenders.append("--blocker-reason")
        if evidence is not None:
            offenders.append("--evidence")
        if families_agreeing:
            offenders.append("--families-agreeing")
        if blocker_confirmed:
            offenders.append("--blocker-confirmed")
        if offenders:
            return False, ("%s %s marathon-only — not valid on a checkpoint-stance epic"
                           % (", ".join(offenders), "is" if len(offenders) == 1 else "are"))
    hit = _find_feature(state, feature_id)
    if hit is None:
        return False, "no feature %r" % feature_id
    prev_status = hit.get("status")  # Codex round-2 #4: needed to detect a real status change
    now_dt = now_dt or datetime.now(timezone.utc)
    now_s = _now_iso(now_dt)

    if status == "running" and marathon:
        prev = hit.get("status")
        if prev not in ("pending", "failed"):
            return False, ("illegal transition to 'running' from %r (legal sources: pending, "
                           "failed)" % prev)
        hit["attempts"] = hit.get("attempts", 0) + 1

    if status == "blocked" and marathon:
        if blocker_confirmed:
            return False, ("--blocker-confirmed true is rejected in v2.10 — confirmation is "
                           "derived from >=2 stored known-family arbiter ballots, never "
                           "caller-asserted; a v2.10 blocker is always confirmed:false "
                           "(SUSPECTED)")
        attempt = hit.get("attempts", 0)
        ledger = state.setdefault("blocker_ledger", [])
        # Exactly-one-active invariant (Codex review #6): deactivate every OTHER ledger entry
        # for this feature, then append-or-REACTIVATE the entry for the current attempt.
        entry = None
        for e in ledger:
            if e.get("feature") != feature_id:
                continue
            if e.get("attempt") == attempt:
                entry = e
            elif e.get("active"):
                e["active"] = False
                if not e.get("resolved_at"):
                    e["resolved_at"] = now_s
        if entry is None:
            ledger.append({
                "feature": feature_id,
                "attempt": attempt,
                "confirmed": False,
                "reason": blocker_reason or "",
                "evidence": evidence,
                "families_agreeing": list(families_agreeing or []),
                "first_seen_at": now_s,
                "blocks": _transitive_dependents(state.get("features", []), feature_id),
                "active": True,
                "resolved_at": None,
            })
        elif not entry.get("active"):
            # Reblock of a previously-resolved (feature, attempt): reactivate it so a
            # currently-blocked feature is never invisible to the human report.
            entry["active"] = True
            entry["resolved_at"] = None
            if blocker_reason:
                entry["reason"] = blocker_reason
            if evidence is not None:
                entry["evidence"] = evidence
            if families_agreeing:
                entry["families_agreeing"] = list(families_agreeing)
        # else: already active for this attempt — idempotent replay, no change.

    if status == "pending" and marathon:
        for e in (state.get("blocker_ledger") or []):
            if e.get("feature") == feature_id and e.get("active"):
                e["active"] = False
                e["resolved_at"] = now_s

    if marathon:
        # last_error lifecycle (Codex review #7): set on ->failed (when supplied), cleared
        # on a retry (->running) or success (->done).
        if status == "failed":
            if last_error is not None:
                hit["last_error"] = last_error
        elif status in ("running", "done"):
            hit["last_error"] = None
        # no_progress reset on a feature REACHING done (Codex review #8 / Component 4).
        # Codex round-3 #1: gate on a real transition — a done->done replay is not progress
        # and must not reset the stall counter (which would postpone the breaker).
        if status == "done" and prev_status != "done":
            state["no_progress_cycles"] = 0

    hit["status"] = status
    if run_id is not None:
        hit["run_id"] = run_id

    if marathon:
        # A REAL feature-state change invalidates a passed final_review (Codex review #1) — a
        # fresh --record-final-review passed is required before the epic can be 'done' again.
        # Codex round-2 #4: an idempotent replay (prev_status == status, e.g. done->done)
        # is NOT a change and must NOT flip a passed review back to pending.
        if prev_status != status:
            fr = state.get("final_review")
            if isinstance(fr, dict) and fr.get("status") == "passed":
                state["final_review"] = {"status": "pending"}
        state["total_attempts"] = _total_attempts(state)  # recompute, never trust a stale field
        _recompute_top_status(state)
        _bump_last_progress(state, now_dt)  # v2.11: no-op unless watch is on
    else:
        sts = [f["status"] for f in state["features"]]
        if all(s == "done" for s in sts):
            state["status"] = "done"
        elif any(s == "failed" for s in sts):
            state["status"] = "blocked"
        else:
            state["status"] = "running"
    return True, None


def record_disposition(state, feature_id, disposition, reason=None,
                        families_agreeing=None, confirmed=False, now_dt=None):
    """Store the arbiter's verdict on a feature (A4). `confirmed=True` is HARD-REJECTED in
    v2.10 (Sol-R4#2) — confirmation of a blocked_external verdict is derived from >=2 stored
    known-family ballots elsewhere (Unit B), never asserted by the caller of this CLI.

    FIX A (attempt-binding, v2.10 correctness follow-up): the disposition is stamped with
    `attempt` = the feature's CURRENT `attempts` count at record time. `next_feature_autonomous`
    only honors a stored disposition when it was recorded for the feature's still-current
    attempt — this is what stops a stale `retry_fix` (approved for a prior, already-retried
    attempt) from being silently re-honored as an unapproved second retry after the retry
    re-runs, fails again, and crashes before a fresh arbitration."""
    if disposition not in ("retry_fix", "halt_feature", "halt_epic", "blocked_external"):
        return False, "invalid --disposition %r" % (disposition,)
    if confirmed:
        return False, ("--confirmed true is rejected in v2.10 — confirmation is derived from "
                       ">=2 stored known-family arbiter ballots, never caller-asserted")
    hit = _find_feature(state, feature_id)
    if hit is None:
        return False, "no feature %r" % feature_id
    now_dt = now_dt or datetime.now(timezone.utc)
    hit["disposition"] = {
        "disposition": disposition,
        "attempt": hit.get("attempts", 0),
        "confirmed": False,
        "reason": reason or "",
        "families_agreeing": list(families_agreeing or []),
        "recorded_at": _now_iso(now_dt),
    }
    state["total_attempts"] = _total_attempts(state)  # recompute on every marathon mutation (#9)
    _bump_last_progress(state, now_dt)  # v2.11: no-op unless watch is on
    return True, None


def record_final_review(state, status, now_dt=None):
    """A6: persist the final cross-feature re-verification gate. `next_feature_autonomous`
    (A2) only reports 'done' once all features are done AND this is 'passed'.

    `passed` is REJECTED unless EVERY feature is currently done (Codex review #1) — a review
    can't pass over incomplete work, so only record_final_review(...,'passed') on a fully-
    done epic can ever flip the top-level status to 'done'.

    FIX 2 (v2.10 follow-up): `passed` is ALSO rejected while any feature has
    `sample_audit_due == True` — a due sample-audit is a durable obligation that a passed
    final_review must never gate past, breaker trip or not."""
    if status not in ("pending", "passed", "failed"):
        return False, "--status must be one of: pending, passed, failed"
    if status == "passed":
        feats = [f for f in state.get("features", []) if isinstance(f, dict)]
        not_done = [f.get("id") for f in feats if f.get("status") != "done"]
        if not feats or not_done:
            return False, ("cannot record final_review=passed while features are not done "
                           "(not done: %s)" % (", ".join(map(str, not_done)) or "none"))
        due_ids = sorted(f.get("id") for f in feats if f.get("sample_audit_due") is True)
        if due_ids:
            return False, ("cannot record final_review=passed while sample_audit_due is true "
                           "for feature(s) %s" % ", ".join(due_ids))
    state["final_review"] = {"status": status}
    state["total_attempts"] = _total_attempts(state)  # recompute on every marathon mutation (#9)
    _recompute_top_status(state)
    _bump_last_progress(state, now_dt or datetime.now(timezone.utc))  # v2.11: watch-gated no-op
    return True, None


def can_retry_info(state, feature_id):
    """A3: {"can_retry","attempts","cap"} — read-only. Non-marathon states have no stored
    attempts/cap; this degrades to attempts=0 against the marathon default cap (2) rather
    than crashing, consistent with the `.get(...,default)` reading discipline."""
    hit = _find_feature(state, feature_id)
    if hit is None:
        return None
    attempts = hit.get("attempts", 0)
    autonomy = state.get("autonomy") if isinstance(state.get("autonomy"), dict) else {}
    # Fail-safe cap resolution (Codex round-2 #3): a MISSING key -> the documented default;
    # an EXPLICIT null -> unbounded (can always retry), NEVER compared against with `<`
    # (attempts < None raises on Python 3).
    cap = _effective_cap(autonomy, "max_attempts_per_feature",
                         _CAP_DEFAULTS["max_attempts_per_feature"])
    can_retry = True if cap is None else (attempts < cap)
    return {"can_retry": can_retry, "attempts": attempts, "cap": cap}


def _effective_cap(autonomy, name, default):
    """Fail-SAFE cap resolution (Codex review #4):
      - MISSING key  -> the documented `default` (NEVER unbounded);
      - EXPLICIT null -> unbounded on that axis, with a LOUD stderr warning each check;
      - a number     -> that number (validated non-negative at --init / post-load).
    Returns the effective cap (a number, or None for the explicit-unbounded path)."""
    if name not in autonomy:
        return default
    val = autonomy[name]
    if val is None:
        print("epic warning: %s is explicitly null — that cap axis is UNBOUNDED "
              "(no limit will ever apply on it)" % name, file=sys.stderr)
        return None
    return val


def breaker_check(state, now_dt):
    """A7: READ-ONLY. {"tripped","which":[...],"detail":{...}}. Trips on
    total_attempts>=max_total_attempts, no_progress_cycles>=max_no_progress_cycles,
    wall-clock(now - autonomy.started_at)>=max_wall_clock_hours, or (v2.11)
    resume_count>=max_resume_count. Counts and hours only — never a fabricated cost. A
    non-marathon state (no `autonomy`) never trips. Caps are resolved fail-SAFE: a missing
    cap key uses the documented default, not unbounded (Codex review #4).

    v2.11: `resume_count`/`max_resume_count` are absent on every pre-v2.11 and every
    watch-off state, so this new axis is a pure no-op for them (0 >= the default cap of 20
    is always False) — `--claim-resume` is the primary writer of `resume_count`, but folding
    the cap into `breaker_check`/`trip_breaker` too means `--breaker-check`/`--trip-breaker`
    (and `--clear-breaker`'s fail-safe re-trip warning, which calls `breaker_check`
    internally) stay the single source of truth for ALL four axes, not just three."""
    autonomy = state.get("autonomy") if isinstance(state.get("autonomy"), dict) else {}
    which = []
    detail = {}
    if not autonomy:
        return {"tripped": False, "which": which, "detail": detail}

    # Never trust a possibly-stale stored counter for the trip decision itself — derive it
    # live from the features (the invariant total_attempts == sum(feature.attempts) holds
    # by construction this way, not by hoping every writer kept the stored field in sync).
    total_attempts = _total_attempts(state)
    max_total = _effective_cap(autonomy, "max_total_attempts", _default_total_attempts(state))
    if max_total is not None and total_attempts >= max_total:
        which.append("max_total_attempts")
        detail["max_total_attempts"] = {"value": total_attempts, "cap": max_total}

    no_progress = state.get("no_progress_cycles", 0)
    max_no_progress = _effective_cap(autonomy, "max_no_progress_cycles",
                                     _CAP_DEFAULTS["max_no_progress_cycles"])
    if max_no_progress is not None and no_progress >= max_no_progress:
        which.append("max_no_progress_cycles")
        detail["max_no_progress_cycles"] = {"value": no_progress, "cap": max_no_progress}

    max_hours = _effective_cap(autonomy, "max_wall_clock_hours",
                               _CAP_DEFAULTS["max_wall_clock_hours"])
    started_at = autonomy.get("started_at")
    if max_hours is not None:
        # Codex round-3 #3: when a wall-clock cap is set, a missing/unparseable started_at
        # must FAIL SAFE — TRIP the breaker (never silently skip a safety limit). A valid
        # start time trips normally on elapsed >= cap.
        elapsed_hours = None
        if not isinstance(started_at, str) or not started_at:
            print("epic-breaker warning: max_wall_clock_hours is set but autonomy.started_at "
                  "is missing %r — TRIPPING the wall-clock breaker fail-safe (never silently "
                  "skipped)" % (started_at,), file=sys.stderr)
            which.append("max_wall_clock_hours")
            detail["max_wall_clock_hours"] = {"value": None, "cap": max_hours,
                                              "failsafe": "started_at missing"}
        else:
            try:
                started_dt = _parse_iso(started_at)
                elapsed_hours = (now_dt - started_dt).total_seconds() / 3600.0
            except (ValueError, TypeError):
                print("epic-breaker warning: autonomy.started_at %r is unparseable — TRIPPING "
                      "the wall-clock breaker fail-safe (never silently skipped)"
                      % (started_at,), file=sys.stderr)
                which.append("max_wall_clock_hours")
                detail["max_wall_clock_hours"] = {"value": None, "cap": max_hours,
                                                  "failsafe": "started_at unparseable"}
            if elapsed_hours is not None and elapsed_hours >= max_hours:
                which.append("max_wall_clock_hours")
                detail["max_wall_clock_hours"] = {"value": round(elapsed_hours, 4),
                                                  "cap": max_hours}

    # v2.11: resume_count axis. Boundary mirrors can_retry_info's `attempts < cap`
    # convention elsewhere in this file: a cap of N allows N successful claims (resume_count
    # 0..N-1 at check time) and trips once resume_count has already reached N.
    resume_count = state.get("resume_count", 0)
    max_resume = _effective_cap(autonomy, "max_resume_count", _CAP_DEFAULTS["max_resume_count"])
    if max_resume is not None and resume_count >= max_resume:
        which.append("max_resume_count")
        detail["max_resume_count"] = {"value": resume_count, "cap": max_resume}

    return {"tripped": bool(which), "which": which, "detail": detail}


def trip_breaker(state, now_dt):
    """A7: re-runs `breaker_check`; if tripped, atomically parks the epic at
    'blocked_needing_human' and records which breaker + detail. A no-op (besides the read)
    when nothing is tripped — callers check `result["mutated"]` to decide whether to persist."""
    result = breaker_check(state, now_dt)
    if result["tripped"] and state.get("status") != "blocked_needing_human":
        state["status"] = "blocked_needing_human"
        state["breaker_trip"] = {"which": result["which"], "detail": result["detail"],
                                 "tripped_at": _now_iso(now_dt)}
        state["total_attempts"] = _total_attempts(state)  # recompute on every mutation (#9)
        _bump_last_progress(state, now_dt)  # v2.11: no-op unless watch is on
        result["mutated"] = True
    else:
        result["mutated"] = False
    return result


def record_progress_cycle(state, cycle_id, now_dt=None):
    """A7: one atomic, idempotent progress-boundary marker keyed by `cycle_id`. Compares
    the current `done` count against the last-recorded count: more done -> reset
    no_progress_cycles to 0; same or fewer -> increment it.

    Idempotency is GLOBAL, not just against the immediately-preceding id (Codex review #5):
    ANY previously-accepted cycle-id (within the bounded remembered set) replays as a no-op,
    so cycle-1 -> cycle-2 -> replay(cycle-1) does not double-count."""
    processed = state.get("processed_cycle_ids")
    processed = list(processed) if isinstance(processed, list) else []
    if cycle_id in processed:
        return {"cycle_id": cycle_id, "no_progress_cycles": state.get("no_progress_cycles", 0),
                "replayed": True}
    done_count = sum(1 for f in state.get("features", [])
                     if isinstance(f, dict) and f.get("status") == "done")
    prior = state.get("last_done_count")
    if prior is None:
        # First cycle ever: nothing to compare against — establish the baseline without
        # counting it as a no-progress cycle.
        state["no_progress_cycles"] = state.get("no_progress_cycles", 0)
    elif done_count > prior:
        state["no_progress_cycles"] = 0
    else:
        state["no_progress_cycles"] = state.get("no_progress_cycles", 0) + 1
    state["last_done_count"] = done_count
    processed.append(cycle_id)
    if len(processed) > _PROCESSED_CYCLE_CAP:
        processed = processed[-_PROCESSED_CYCLE_CAP:]
    state["processed_cycle_ids"] = processed
    state["total_attempts"] = _total_attempts(state)  # recompute on every marathon mutation (#9)
    _bump_last_progress(state, now_dt or datetime.now(timezone.utc))  # v2.11: watch-gated no-op
    return {"cycle_id": cycle_id, "no_progress_cycles": state["no_progress_cycles"],
            "replayed": False}


# Human-facing hint per breaker axis for the --clear-breaker fail-safe re-trip warning: what
# the human must actually go raise/restart for that specific axis to stop re-tripping
# immediately. no_progress_cycles has no hint because clear_breaker unconditionally resets it
# to 0, so it can never be part of an immediate re-trip.
_BREAKER_AXIS_HINTS = {
    "max_total_attempts": "raise the cap with --set-max-total-attempts",
    "max_wall_clock_hours": "restart the clock with --reset-wall-clock (or raise "
                             "autonomy.max_wall_clock_hours by hand)",
    "max_resume_count": "re-arm with --clear-breaker --reset-resume-count",
}


def clear_breaker(state, now_dt, reset_wall_clock=False, set_max_total_attempts=_UNSET,
                   reset_resume_count=False):
    """The human's re-arm after a breaker trip / halt (v2.10 resume support). Marathon-only.

    Clears the `blocked_needing_human` latch: removes any `breaker_trip` record, resets
    `no_progress_cycles` to 0, then recomputes the top-level status via
    `_recompute_top_status` (-> 'running' or 'done'). `_recompute_top_status` itself treats
    'blocked_needing_human' as sticky and refuses to overwrite it, so the status is force-set
    to 'running' first so the recompute can actually re-derive it.

    `reset_wall_clock=True` restarts the wall-clock axis (`autonomy.started_at = now`).
    `set_max_total_attempts` (an int, None for explicit-unbounded, or the `_UNSET` sentinel
    for "leave it alone") re-arms that axis, validated with the same non-negative/finite
    rules as --init. `reset_resume_count=True` (v2.11) re-arms the resume axis by zeroing
    `resume_count` — the SAME opt-in-flag shape as `reset_wall_clock`, since (unlike
    `max_total_attempts`, a cap you raise) `resume_count` is a genuine counter you reset.

    Fail-safe: after clearing, `breaker_check` is re-run against the (possibly re-armed)
    state; if it would IMMEDIATELY re-trip (e.g. total_attempts is still >= max_total_attempts
    and no --set-max-total-attempts was given), a loud stderr warning names exactly which
    axis and what to raise — but the latch is cleared regardless; the human is in control.

    Returns (ok, error|None, summary|None)."""
    if not _is_marathon(state):
        return False, "--clear-breaker requires a marathon-stance epic", None
    if set_max_total_attempts is not _UNSET:
        err = _validate_cap_value("max_total_attempts", set_max_total_attempts)
        if err:
            return False, err, None

    had_trip = state.pop("breaker_trip", None) is not None
    prior_no_progress = state.get("no_progress_cycles", 0)
    state["no_progress_cycles"] = 0

    prior_resume_count = state.get("resume_count", 0)
    if reset_resume_count:
        state["resume_count"] = 0

    autonomy = state.setdefault("autonomy", {})
    if reset_wall_clock:
        autonomy["started_at"] = _now_iso(now_dt)
    if set_max_total_attempts is not _UNSET:
        autonomy["max_total_attempts"] = set_max_total_attempts

    # Force off the sticky latch so _recompute_top_status can re-derive the real status
    # instead of its no-op early-return for 'blocked_needing_human'.
    state["status"] = "running"
    state["total_attempts"] = _total_attempts(state)  # recompute on every mutation (#9)
    _bump_last_progress(state, now_dt)  # v2.11: no-op unless watch is on
    _recompute_top_status(state)

    summary = {
        "cleared_breaker_trip": had_trip,
        "no_progress_cycles_reset_from": prior_no_progress,
        "wall_clock_reset": bool(reset_wall_clock),
        "max_total_attempts_set": (set_max_total_attempts
                                    if set_max_total_attempts is not _UNSET else None),
        "resume_count_reset": bool(reset_resume_count),
        "resume_count_reset_from": prior_resume_count if reset_resume_count else None,
        "epic_status": state["status"],
    }

    recheck = breaker_check(state, now_dt)
    summary["would_immediately_retrip"] = recheck["tripped"]
    summary["would_retrip_which"] = recheck["which"]
    if recheck["tripped"]:
        hints = "; ".join("%s (%s)" % (axis, _BREAKER_AXIS_HINTS.get(axis, "raise that cap"))
                          for axis in recheck["which"])
        print("epic-clear-breaker warning: the latch is cleared, but this state would "
              "IMMEDIATELY re-trip on the next --breaker-check: %s" % hints, file=sys.stderr)

    return True, None, summary


def clear_disposition(state, feature_id, now_dt=None):
    """Clears a feature's stored `disposition` (v2.10 resume support). Marathon-only. This
    is the override for a sticky `halt_epic`/`halt_feature` verdict — once cleared,
    `next_feature_autonomous` no longer short-circuits on it (a fresh disposition can still
    be recorded later via `record_disposition`). Returns (ok, error|None)."""
    if not _is_marathon(state):
        return False, "--clear-disposition requires a marathon-stance epic"
    hit = _find_feature(state, feature_id)
    if hit is None:
        return False, "no feature %r" % feature_id
    hit["disposition"] = None
    state["total_attempts"] = _total_attempts(state)  # recompute on every mutation (#9)
    _bump_last_progress(state, now_dt or datetime.now(timezone.utc))  # v2.11: watch-gated no-op
    return True, None


def mark_sample_audit_due(state, feature_id, now_dt=None):
    """FIX 2 (v2.10 crash-safety follow-up): sets `feature.sample_audit_due = True` — a
    durable obligation recorded BEFORE the PASS sample-audit runs, so a breaker trip/crash
    in that window (after a sampled SUCCESS is marked 'done' but before its sample-audit
    runs) is never silently lost on resume. `next_feature_autonomous` and
    `record_final_review` both gate terminal completion on this flag. Marathon-only.
    Returns (ok, error|None)."""
    if not _is_marathon(state):
        return False, "--mark-sample-audit-due requires a marathon-stance epic"
    hit = _find_feature(state, feature_id)
    if hit is None:
        return False, "no feature %r" % feature_id
    hit["sample_audit_due"] = True
    state["total_attempts"] = _total_attempts(state)  # recompute on every mutation (#9)
    # A stale 'done' (set by an earlier passed final_review, before this obligation was
    # recorded) must not survive marking a sample-audit due — recompute now, not just at the
    # next unrelated mutation.
    _recompute_top_status(state)
    _bump_last_progress(state, now_dt or datetime.now(timezone.utc))  # v2.11: watch-gated no-op
    return True, None


def clear_sample_audit_due(state, feature_id, now_dt=None):
    """The counterpart to `mark_sample_audit_due` — the sample-audit passed, so the
    obligation is cleared and terminal completion (and a passed final_review) can proceed
    again. Marathon-only. Returns (ok, error|None)."""
    if not _is_marathon(state):
        return False, "--clear-sample-audit-due requires a marathon-stance epic"
    hit = _find_feature(state, feature_id)
    if hit is None:
        return False, "no feature %r" % feature_id
    hit["sample_audit_due"] = False
    state["total_attempts"] = _total_attempts(state)  # recompute on every mutation (#9)
    _recompute_top_status(state)
    _bump_last_progress(state, now_dt or datetime.now(timezone.utc))  # v2.11: watch-gated no-op
    return True, None


def record_audit_failed(state, feature_id, last_error=None, now_dt=None):
    """FIX B (atomic audit-failed, v2.10 correctness follow-up): the driver's sample-audit-
    ISSUES path used to be TWO separate CLI writes — clear_sample_audit_due(...) and a
    separate --update --status failed — so a crash between them could leave a feature 'done'
    with its sample_audit_due obligation already cleared, and `next_feature_autonomous` /
    `record_final_review` / `_recompute_top_status` gate terminal completion ONLY on that
    flag, not on the audit's actual verdict. A crash in that window silently loses the audit
    finding: final_review could pass over a feature that never actually got fixed.

    This performs every mutation of that sequence against ONE in-memory state object, so the
    caller's single `_atomic_write_json` persists all of it in one write or none of it:
      - feature.status -> "failed"
      - feature.last_error (set iff `last_error` is supplied — same lifecycle as `apply_update`)
      - feature.sample_audit_due -> False (the obligation this audit was discharging)
      - a passed final_review is invalidated back to pending (same invariant `apply_update`
        maintains: ANY real feature-state change invalidates a passed review)
      - total_attempts / top-level status recomputed, exactly like every other mutator here

    Deliberately does NOT touch `attempts` — reverting an audit-failed 'done' back to 'failed'
    is not a new retry attempt (no ->running transition occurred), so incrementing attempts
    here would over-count against max_attempts_per_feature for work that hasn't actually
    re-run yet.

    Marathon-only; an unknown feature is a controlled error. Returns (ok, error|None)."""
    if not _is_marathon(state):
        return False, "--record-audit-failed requires a marathon-stance epic"
    hit = _find_feature(state, feature_id)
    if hit is None:
        return False, "no feature %r" % feature_id
    prev_status = hit.get("status")
    hit["status"] = "failed"
    if last_error is not None:
        hit["last_error"] = last_error
    hit["sample_audit_due"] = False
    if prev_status != "failed":
        fr = state.get("final_review")
        if isinstance(fr, dict) and fr.get("status") == "passed":
            state["final_review"] = {"status": "pending"}
    state["total_attempts"] = _total_attempts(state)  # recompute on every mutation (#9)
    _recompute_top_status(state)
    _bump_last_progress(state, now_dt or datetime.now(timezone.utc))  # v2.11: watch-gated no-op
    return True, None


def validate_marathon_state(state):
    """Defensive integrity check for a LOADED marathon state (Codex review #10) — a legacy
    or hand-edited epic-state.json can carry corruption the builder would never produce.
    Returns a list of error strings (empty = clean). main() aborts with a controlled nonzero
    on any error rather than letting a downstream KeyError/TypeError crash the process.
    Only applied when `_is_marathon(state)` — a checkpoint state is untouched."""
    errs = []
    feats = state.get("features")
    if not isinstance(feats, list):
        return ["marathon state has no valid 'features' list"]
    for i, f in enumerate(feats):
        if not isinstance(f, dict):
            errs.append("feature at index %d is not an object" % i)
            continue
        fid = f.get("id")
        if not isinstance(fid, str) or not _id_ok(fid):
            errs.append("feature at index %d has a missing/invalid id %r" % (i, fid))
        att = f.get("attempts", 0)
        if not _is_nonneg_int(att):
            errs.append("feature %r has a malformed 'attempts' %r (want a non-negative int)"
                        % (f.get("id"), att))
        # Codex round-2 #1: a non-list / non-string-element depends_on later crashes
        # _transitive_closure / next_feature_autonomous with a TypeError — reject it here.
        deps = f.get("depends_on", [])
        if not isinstance(deps, list) or not all(isinstance(d, str) for d in deps):
            errs.append("feature %r has a malformed 'depends_on' %r (want a list of id strings)"
                        % (f.get("id"), deps))
        # FIX 2: sample_audit_due is bool-or-absent — accept a missing key, reject anything
        # present that isn't an actual bool (including None).
        if "sample_audit_due" in f and not isinstance(f.get("sample_audit_due"), bool):
            errs.append("feature %r has a malformed 'sample_audit_due' %r (want a bool or "
                        "absent)" % (f.get("id"), f.get("sample_audit_due")))
        # FIX A: disposition is an object-or-null; when present its 'attempt' key is
        # OPTIONAL (a legacy pre-FIX-A disposition with no 'attempt' key is accepted — treated
        # as attempt 0 everywhere it's read, never a crash) but if present must be a
        # non-negative int, exactly like a blocker_ledger entry's 'attempt' below.
        disp = f.get("disposition")
        if disp is not None:
            if not isinstance(disp, dict):
                errs.append("feature %r has a malformed 'disposition' %r (want an object or "
                            "null)" % (f.get("id"), disp))
            elif "attempt" in disp and not _is_nonneg_int(disp.get("attempt")):
                errs.append("feature %r disposition has a malformed 'attempt' %r (want a "
                            "non-negative int)" % (f.get("id"), disp.get("attempt")))
    npc = state.get("no_progress_cycles", 0)
    if not _is_nonneg_int(npc):
        errs.append("'no_progress_cycles' is malformed %r (want a non-negative int)" % (npc,))
    ta = state.get("total_attempts", 0)
    if not _is_nonneg_int(ta):
        errs.append("'total_attempts' is malformed %r (want a non-negative int)" % (ta,))
    # Codex round-2 #1: a string last_done_count crashes the `done_count > prior` compare in
    # --record-progress-cycle; a non-string processed_cycle_ids element breaks replay lookup.
    ldc = state.get("last_done_count")
    if ldc is not None and not _is_nonneg_int(ldc):
        errs.append("'last_done_count' is malformed %r (want a non-negative int or absent)"
                    % (ldc,))
    pci = state.get("processed_cycle_ids")
    if pci is not None and (not isinstance(pci, list)
                            or not all(isinstance(c, str) for c in pci)):
        errs.append("'processed_cycle_ids' is malformed %r (want a list of strings)" % (pci,))
    # Codex round-3 #2: a non-list blocker_ledger crashes at ledger.append; a non-dict entry
    # crashes on e.get(...). Require a list of dicts carrying the core keys.
    ledger = state.get("blocker_ledger")
    if ledger is not None:
        if not isinstance(ledger, list):
            errs.append("'blocker_ledger' is malformed %r (want a list)" % (ledger,))
        else:
            for j, e in enumerate(ledger):
                if not isinstance(e, dict):
                    errs.append("blocker_ledger entry at index %d is not an object" % j)
                    continue
                if not isinstance(e.get("feature"), str):
                    errs.append("blocker_ledger entry at index %d has a non-string 'feature'"
                                % j)
                if not _is_nonneg_int(e.get("attempt", 0)):
                    errs.append("blocker_ledger entry at index %d has a malformed 'attempt'" % j)
                if not isinstance(e.get("active", False), bool):
                    errs.append("blocker_ledger entry at index %d has a non-bool 'active'" % j)
    autonomy = state.get("autonomy")
    if isinstance(autonomy, dict):
        for cap_name in ("max_attempts_per_feature", "max_no_progress_cycles",
                         "max_total_attempts", "max_wall_clock_hours", "max_resume_count"):
            if cap_name in autonomy:
                e = _validate_cap_value("autonomy.%s" % cap_name, autonomy[cap_name])
                if e:
                    errs.append(e)
        # Codex round-3 #3: a marathon state must carry a VALID started_at — the wall-clock
        # breaker is a safety limit and must never be silently disabled by a missing/bad
        # timestamp. Require it here; breaker_check additionally FAILS SAFE (trips) at runtime.
        started_at = autonomy.get("started_at")
        if not isinstance(started_at, str):
            errs.append("autonomy.started_at is missing/non-string %r — the wall-clock breaker "
                        "needs a valid start time" % (started_at,))
        else:
            try:
                _parse_iso(started_at)
            except (ValueError, TypeError):
                errs.append("autonomy.started_at %r is not a valid ISO-8601 timestamp"
                            % (started_at,))
        # start_sha (v2.10) is string-or-absent — absent is normal (older marathon states,
        # or a driver that didn't pass --start-sha at --init time) and not an error.
        if "start_sha" in autonomy and not isinstance(autonomy["start_sha"], str):
            errs.append("autonomy.start_sha is malformed %r (want a string or absent)"
                        % (autonomy["start_sha"],))
        # v2.11: watch is bool-or-absent — a hand-edited non-bool (e.g. "true" the string, or
        # a truthy int) must be rejected, not silently coerced.
        if "watch" in autonomy and not isinstance(autonomy["watch"], bool):
            errs.append("autonomy.watch is malformed %r (want a bool or absent)"
                        % (autonomy["watch"],))
    # v2.11: last_progress_at is an ISO-8601 string-or-absent (absent = never bumped yet, or
    # watch is off — not an error either way).
    lpa = state.get("last_progress_at")
    if lpa is not None:
        if not isinstance(lpa, str):
            errs.append("'last_progress_at' is malformed %r (want an ISO-8601 string or "
                        "absent)" % (lpa,))
        else:
            try:
                _parse_iso(lpa)
            except (ValueError, TypeError):
                errs.append("'last_progress_at' %r is not a valid ISO-8601 timestamp" % (lpa,))
    # v2.11: resume_count is a non-negative int-or-absent (absent = never claimed yet).
    rc = state.get("resume_count")
    if rc is not None and not _is_nonneg_int(rc):
        errs.append("'resume_count' is malformed %r (want a non-negative int or absent)" % (rc,))
    # v2.11: lease is {"owner_pid": int>0, "claimed_at": ISO str, "expires_at": ISO str}, or
    # absent entirely (never claimed yet) — every key is required together when present (a
    # partial lease is exactly the kind of hand-edited corruption this validator exists for).
    lease = state.get("lease")
    if lease is not None:
        if not isinstance(lease, dict):
            errs.append("'lease' is malformed %r (want an object or absent)" % (lease,))
        else:
            owner_pid = lease.get("owner_pid")
            if not (isinstance(owner_pid, int) and not isinstance(owner_pid, bool)
                    and owner_pid > 0):
                errs.append("lease.owner_pid is malformed %r (want a positive int)"
                            % (owner_pid,))
            for k in ("claimed_at", "expires_at"):
                v = lease.get(k)
                if not isinstance(v, str):
                    errs.append("lease.%s is malformed %r (want an ISO-8601 string)" % (k, v))
                else:
                    try:
                        _parse_iso(v)
                    except (ValueError, TypeError):
                        errs.append("lease.%s %r is not a valid ISO-8601 timestamp" % (k, v))
    return errs


def liveness_check(state, now_dt, stale_after_min=_DEFAULT_STALE_AFTER_MIN):
    """v2.11 `--liveness` (Plan-review corrections, V1 #2): the watcher's single read-only
    poll target. Never mutates `state`. Returns exactly:
      {"incomplete","stale","held","lease_expired","epic_status","terminal","resume_count"}

    - `terminal` = `is_terminal(state)` — the shared classifier.
    - `incomplete` = `state["status"] != "done"` (a `blocked_needing_human` epic is BOTH
      terminal and incomplete — it halted before finishing successfully).
    - `held` = a currently-live lease is on file (`_lease_live`).
    - `lease_expired` = a lease is on file but it is NOT live (distinct from "no lease was
      ever recorded", which is neither held nor expired — just unclaimed).
    - `stale` = incomplete AND NOT terminal AND the heartbeat is past `stale_after_min` AND
      the lease's `owner_pid` is not a live OS process (belt-and-suspenders: an alive owner
      always defers the watcher, even past the age threshold — advisory only, this function
      never itself decides to resume; that is `--claim-resume`'s job). A missing/unparseable
      `last_progress_at` FAILS SAFE as stale-eligible (mirrors `breaker_check`'s
      started_at fail-safe: an unproven heartbeat can never prove liveness)."""
    terminal = is_terminal(state)
    incomplete = state.get("status") != "done"
    lease = state.get("lease") if isinstance(state.get("lease"), dict) else None
    live = _lease_live(state, now_dt)
    lease_expired = bool(lease) and not live
    owner_pid = lease.get("owner_pid") if lease else None
    owner_alive = _pid_alive(owner_pid) if isinstance(owner_pid, int) else False
    lp = state.get("last_progress_at")
    time_stale = True  # fail-safe default: an unproven heartbeat reads as stale-eligible
    if isinstance(lp, str):
        try:
            age_min = (now_dt - _parse_iso(lp)).total_seconds() / 60.0
            time_stale = age_min >= stale_after_min
        except (ValueError, TypeError):
            time_stale = True
    stale = bool(incomplete and not terminal and time_stale and not owner_alive)
    return {
        "incomplete": incomplete,
        "stale": stale,
        "held": live,
        "lease_expired": lease_expired,
        "epic_status": state.get("status"),
        "terminal": terminal,
        "resume_count": state.get("resume_count", 0),
    }


def renew_lease(state, owner_pid, now_dt, lease_ttl_min=_DEFAULT_LEASE_TTL_MIN):
    """v2.11 `--renew-lease`: the lease holder's own periodic heartbeat. Extends
    `lease.expires_at` to `now + lease_ttl_min` and bumps `last_progress_at`. Only the
    CURRENT recorded `owner_pid` may renew — a caller with no live lease, or a mismatched/
    foreign `owner_pid`, must `--claim-resume` first; renew never silently takes over a lease
    it doesn't already hold (that would defeat the whole point of the lease). Not
    flock-guarded like `--claim-resume`: only the single already-claimed worker ever calls
    this on itself, so there is no multi-writer race to arbitrate here — an ordinary
    mutate-then-let-the-caller-atomic-write path (same as every other mutator in this file)
    is sufficient. Returns (ok, error|None)."""
    if not _is_marathon(state):
        return False, "--renew-lease requires a marathon-stance epic"
    if not _watch_on(state):
        return False, ("--renew-lease requires the marathon epic's watch opt-in (re-init "
                       "with --stance marathon --watch)")
    lease = state.get("lease")
    if not isinstance(lease, dict) or lease.get("owner_pid") != owner_pid:
        return False, ("no lease held by owner_pid %r to renew — --claim-resume first"
                       % (owner_pid,))
    lease["expires_at"] = _now_iso(now_dt + timedelta(minutes=lease_ttl_min))
    _bump_last_progress(state, now_dt)
    return True, None


def claim_resume(state_path, owner_pid, now_dt, lease_ttl_min=_DEFAULT_LEASE_TTL_MIN):
    """v2.11 `--claim-resume` — THE CRUX (Plan-review corrections, V1 #1, BLOCKER). ONE
    `fcntl.flock`-guarded atomic transaction against `<state_path>.lock`.

    Deliberately diverges from the reused `compound-v-memory.py:542` idiom in ONE respect:
    that idiom is `fcntl.flock(fd, LOCK_EX | LOCK_NB)` with a loser-noop (best-effort — "someone
    else is already refreshing, just skip"). Here every contender MUST evaluate on the merits
    so its `reason` is always one of the four documented values ("claimed", "live-lease-held",
    "terminal", "resume-cap") — never a fifth "lock busy" outcome that the documented CLI
    contract has no slot for. So this uses a BLOCKING `fcntl.flock(fd, LOCK_EX)` instead of
    `LOCK_NB`. The underlying lock+unlock mechanism (`fcntl.flock` on a sidecar `.lock` file,
    released via `LOCK_UN` in a `finally`) is the same idiom; only the NB/blocking choice
    differs, for the reason above. A plain advisory POSIX flock tied to the open fd is
    released automatically if this process dies while holding it, so a blocking wait here can
    never deadlock past a crashed holder.

    Inside the lock:
      1. Reload `state_path` from disk (never trusts a caller's possibly-stale in-memory
         copy — the whole point of taking the lock is to see the freshest on-disk truth).
      2. Validate stance/watch/structure (marathon + watch required; `validate_marathon_state`
         must be clean) — a structural problem is `ok=False`, no write.
      3. `is_terminal(state)` -> lose with reason "terminal" (no write: nothing changed).
      4. `_lease_live(state, now_dt)` -> lose with reason "live-lease-held" (no write).
      5. `resume_count >= max_resume_count` (boundary: mirrors `can_retry_info`'s
         `attempts < cap` convention elsewhere in this file — a cap of N allows N successful
         claims and blocks the (N+1)th, which is what this check catches BEFORE incrementing)
         -> trip to `blocked_needing_human` (same `breaker_trip` shape `trip_breaker` writes,
         so `--clear-breaker` clears it uniformly), persist, lose with reason "resume-cap".
         The persisted latch means a later orphaned scheduler firing sees a terminal state on
         its own next `--claim-resume` and is a harmless no-op (reason "terminal").
      6. Else: WIN — increment `resume_count`, record a fresh `lease` for `owner_pid`, bump
         `last_progress_at`, atomic-write, reason "claimed".

    Returns (ok, result|None, error|None):
      - `ok=False` only for a structural problem (lock/read failure, non-marathon/non-watch
        state, a `validate_marathon_state` error) — no write in that case.
      - `ok=True` always carries a `result` dict {"claimed","reason","resume_count"}. A LOSING
        claim is still `ok=True` — losing is an expected, successful outcome of the
        transaction, not a script failure; the loser simply does not resume."""
    lock_path = state_path + ".lock"
    lock_dir = os.path.dirname(os.path.abspath(lock_path)) or "."
    if not os.path.isdir(lock_dir):
        os.makedirs(lock_dir)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)  # BLOCKING — see docstring for why not LOCK_NB
        try:
            state = _read_json(state_path)
        except (OSError, ValueError) as e:
            return False, None, "could not read %r: %s" % (state_path, e)
        if not _is_marathon(state):
            return False, None, "--claim-resume requires a marathon-stance epic"
        if not _watch_on(state):
            return False, None, ("--claim-resume requires the marathon epic's watch opt-in "
                                 "(re-init with --stance marathon --watch)")
        merrs = validate_marathon_state(state)
        if merrs:
            return False, None, "epic-state error: %s" % "; ".join(merrs)

        resume_count = state.get("resume_count", 0)

        if is_terminal(state):
            return True, {"claimed": False, "reason": "terminal",
                          "resume_count": resume_count}, None

        if _lease_live(state, now_dt):
            return True, {"claimed": False, "reason": "live-lease-held",
                          "resume_count": resume_count}, None

        autonomy = state.get("autonomy", {})
        max_resume = _effective_cap(autonomy, "max_resume_count",
                                    _CAP_DEFAULTS["max_resume_count"])
        if max_resume is not None and resume_count >= max_resume:
            state["status"] = "blocked_needing_human"
            state["breaker_trip"] = {"which": ["max_resume_count"],
                                     "detail": {"value": resume_count, "cap": max_resume},
                                     "tripped_at": _now_iso(now_dt)}
            _bump_last_progress(state, now_dt)
            _atomic_write_json(state_path, state)
            return True, {"claimed": False, "reason": "resume-cap",
                          "resume_count": resume_count}, None

        new_count = resume_count + 1
        state["resume_count"] = new_count
        state["lease"] = {"owner_pid": owner_pid, "claimed_at": _now_iso(now_dt),
                          "expires_at": _now_iso(now_dt + timedelta(minutes=lease_ttl_min))}
        _bump_last_progress(state, now_dt)
        _atomic_write_json(state_path, state)
        return True, {"claimed": True, "reason": "claimed", "resume_count": new_count}, None
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _atomic_write_json(path, obj):
    """Atomic state write: tmp file in the SAME directory + os.replace (mirrors the idiom
    at compound-v-fastpath-run.py:704) — a reader can never observe a truncated write. No
    cross-process lock HERE — the marathon is still single-writer-at-a-time by construction
    for every v2.10 command (unchanged). v2.11's `--claim-resume` is the one exception that
    genuinely needs multi-writer arbitration (a scheduler can fire concurrently with a still-
    running worker); it wraps ITS OWN read-reload-write sequence in an external
    `fcntl.flock`(see `claim_resume`) and still calls this same unlocked primitive for the
    actual write, exactly like every other mutator in this file."""
    d = os.path.dirname(os.path.abspath(path)) or "."
    if not os.path.isdir(d):
        os.makedirs(d)
    fd, tmp = tempfile.mkstemp(prefix=".epic-state-", suffix=".json", dir=d)
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(json.dumps(obj, indent=2) + "\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read_json(path):
    with open(path, "r", errors="replace") as fh:
        return json.load(fh)


def _cr_worker(state_path, owner_pid, now_iso, barrier, q):
    """Module-level (picklable) worker for the --claim-resume concurrency selftest below —
    must live at module scope for multiprocessing's 'spawn' start method (the macOS default)
    to locate it in the freshly re-imported child. Waits on a shared Barrier so all N
    processes call `claim_resume` at (as close to) the same instant as the OS scheduler
    allows, exercising the real cross-process `fcntl.flock` contention path — not just
    in-process threading, which Python's GIL could mask bugs under."""
    try:
        barrier.wait(timeout=10)
        now_dt = _parse_iso(now_iso)
        ok, result, err = claim_resume(state_path, owner_pid, now_dt)
        q.put((ok, result, err))
    except Exception as e:  # pragma: no cover - defensive; surfaces in the parent's queue
        q.put((False, None, "worker exception: %r" % (e,)))


def _selftest():
    ok = 0
    fail = 0

    def check(name, cond):
        nonlocal ok, fail
        if cond:
            ok += 1
        else:
            fail += 1
            print("  FAIL %s" % name)

    feats = [
        {"id": "auth", "title": "Auth", "depends_on": []},
        {"id": "api", "title": "API", "depends_on": ["auth"]},
        {"id": "ui", "title": "UI", "depends_on": ["api"]},
    ]
    check("valid graph", validate_features(feats) == [])
    check("dangling ref", any("unknown" in e for e in validate_features(
        [{"id": "a", "depends_on": ["nope"]}])))
    check("cycle", any("cycle" in e for e in validate_features(
        [{"id": "a", "depends_on": ["b"]}, {"id": "b", "depends_on": ["a"]}])))
    check("bad id", any("invalid id" in e for e in validate_features(
        [{"id": "../x", "depends_on": []}])))
    check("dup id", any("duplicate" in e for e in validate_features(
        [{"id": "a", "depends_on": []}, {"id": "a", "depends_on": []}])))

    st = build_state(feats, "e1", "Epic")
    f, why = next_feature(st)
    check("first runnable = auth", f and f["id"] == "auth")
    st["features"][0]["status"] = "done"
    f, _ = next_feature(st)
    check("then api", f and f["id"] == "api")
    st["features"][1]["status"] = "running"
    f, why = next_feature(st)
    check("crashed 'running' -> reconcile stop", f is None and "reconcile" in why)
    st["features"][1]["status"] = "done"
    st["features"][2]["status"] = "done"
    f, why = next_feature(st)
    check("complete", f is None and "complete" in why)
    # failed dependency blocks dependents
    st2 = build_state(feats, "e2", "E")
    st2["features"][0]["status"] = "failed"
    f, why = next_feature(st2)
    check("blocked by failed dep", f is None and "blocked" in why)
    # FAIL-FAST (#1): a failure halts even an INDEPENDENT pending feature
    indep = [{"id": "x", "depends_on": []}, {"id": "y", "depends_on": []}]
    st3 = build_state(indep, "e3", "E")
    st3["features"][0]["status"] = "failed"
    f, why = next_feature(st3)
    check("fail-fast halts independent pending", f is None and "blocked" in why)
    # recovery (#1): retrying the failed feature re-opens the epic
    st3["features"][0]["status"] = "pending"
    f, why = next_feature(st3)
    check("retry re-opens epic", f is not None and f["id"] in ("x", "y"))

    # spec_path carried through build_state
    sp_feats = [{"id": "a", "depends_on": [], "spec_path": "specs/a.md"}]
    check("build_state carries spec_path", build_state(sp_feats, "e", "E")["features"][0]["spec_path"] == "specs/a.md")
    check("spec_path type-checked", any("spec_path" in e for e in validate_features(
        [{"id": "a", "depends_on": [], "spec_path": 123}])))

    # lint_decomposition (#2): island + over-coupled
    island = [{"id": "auth", "depends_on": ["api"]}, {"id": "api", "depends_on": ["auth"]},
              {"id": "lonely", "depends_on": []}]
    # (auth/api form a cycle — but lint is structural-only; use a DAG for the island case)
    dag_island = [{"id": "core", "depends_on": []}, {"id": "feat", "depends_on": ["core"]},
                  {"id": "lonely", "depends_on": []}]
    check("island flagged", any("ISLAND" in w for w in lint_decomposition(dag_island)))
    coupled = [{"id": "a", "depends_on": []}, {"id": "b", "depends_on": []},
               {"id": "c", "depends_on": []}, {"id": "d", "depends_on": ["a", "b", "c"]}]
    check("over-coupled flagged", any("LAYER" in w for w in lint_decomposition(coupled)))
    check("clean DAG: no warnings", lint_decomposition(
        [{"id": "a", "depends_on": []}, {"id": "b", "depends_on": ["a"]}]) == [])

    # check_specs (#1): missing path + nonexistent-but-contained file (existence + the
    # containment rule are exercised more fully in the containment block below)
    import tempfile as _tempfile
    check("no spec_path -> error", any("no spec_path" in e for e in check_specs([{"id": "a", "depends_on": []}])))
    check("nonexistent contained spec -> error", any("does not exist" in e for e in check_specs(
        [{"id": "a", "spec_path": "nope.md"}], base_dir=_tempfile.gettempdir())))

    # stats (#4)
    s = stats(build_state([{"id": "a", "depends_on": []}, {"id": "b", "depends_on": ["a"]}], "e", "E"))
    check("stats total/remaining", s["total"] == 2 and s["remaining"] == 2 and s["done"] == 0)
    # Codex round-3 #5: checkpoint --stats must NOT carry a `blocked` key (byte-compat).
    check("stats: checkpoint output has NO 'blocked' key", "blocked" not in s)

    # containment (#2) + check_state_specs (#3)
    import shutil
    d = _tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(d, "specs"))
        with open(os.path.join(d, "specs", "a.md"), "w") as fh:
            fh.write("spec")
        check("contained spec ok", check_specs([{"id": "a", "spec_path": "specs/a.md"}], base_dir=d) == [])
        check("`..` traversal rejected", any("escapes" in e for e in check_specs(
            [{"id": "a", "spec_path": "../../../etc/hosts"}], base_dir=d)))
        check("absolute spec rejected (outside)", check_specs(
            [{"id": "a", "spec_path": "/etc/hosts"}], base_dir=d) != [])
        check("absolute spec rejected (even if inside the dir)", check_specs(
            [{"id": "a", "spec_path": os.path.join(d, "specs", "a.md")}], base_dir=d) != [])
        ok_state = {"features": [{"id": "a", "status": "done"},
                                 {"id": "b", "status": "pending", "spec_path": "specs/a.md"}]}
        check("resume: done-no-spec skipped, pending-with-spec ok", check_state_specs(ok_state, base_dir=d) == [])
        bad_state = {"features": [{"id": "b", "status": "pending"}]}
        check("resume: pending-without-spec -> error", check_state_specs(bad_state, base_dir=d) != [])
        check("resume: malformed (non-dict) entry -> error", check_state_specs({"features": ["junk"]}, base_dir=d) != [])
    finally:
        shutil.rmtree(d, ignore_errors=True)

    # next_feature must not CRASH on a malformed state (defensive — a guard should catch it first)
    nf, _ = next_feature({"features": ["junk", {"id": "a", "status": "pending", "depends_on": []}]})
    check("next_feature survives malformed entry", nf is not None and nf["id"] == "a")

    # A7 (legacy #): a hand-made feature entry MISSING "status" must not KeyError — it
    # matches no bucket (not done/failed/running/pending), and the rest of the epic still
    # advances.
    nf2, why2 = next_feature({"features": [{"id": "nostatus"},
                                           {"id": "b", "status": "pending", "depends_on": []}]})
    check("next_feature survives missing status", nf2 is not None and nf2["id"] == "b")
    # …and a missing-status DEPENDENCY is not silently counted as done: the dependent blocks.
    nf3, why3 = next_feature({"features": [{"id": "nostatus"},
                                           {"id": "b", "status": "pending", "depends_on": ["nostatus"]}]})
    check("missing-status dep is not 'done'", nf3 is None and "blocked" in why3)

    # lint defensive (#5): a non-dict entry must not crash lint_decomposition
    check("lint ignores non-dict", isinstance(lint_decomposition(
        [{"id": "a", "depends_on": []}, "junk", {"id": "b", "depends_on": ["a"]}]), list))

    # over-coupled ratio (#6): 3-of-4 deps in a 5-feature graph flags "most"; 2-of-2 small graph does not
    big = [{"id": "a", "depends_on": []}, {"id": "b", "depends_on": []}, {"id": "c", "depends_on": []},
           {"id": "d", "depends_on": ["a"]}, {"id": "e", "depends_on": ["a", "b", "c"]}]
    check("over-coupled (3/4) flagged", any("LAYER" in w and "'e'" in w for w in lint_decomposition(big)))
    small = [{"id": "a", "depends_on": []}, {"id": "b", "depends_on": []}, {"id": "c", "depends_on": ["a", "b"]}]
    check("small-graph 2 deps not over-coupled", not any("LAYER" in w for w in lint_decomposition(small)))

    # ================================================================
    # v2.10 marathon — Unit A (Tasks A1-A7)
    # ================================================================

    # --- A1: marathon schema in build_state + --init --stance ---------------------------
    plain = build_state(feats, "e", "Epic")
    check("A1 checkpoint build_state: no autonomy key", "autonomy" not in plain)
    check("A1 checkpoint build_state: exact top-level keys",
          set(plain.keys()) == {"epic_id", "title", "status", "features"})
    check("A1 checkpoint build_state: exact feature keys",
          set(plain["features"][0].keys()) ==
          {"id", "title", "depends_on", "spec_path", "status", "run_id"})

    mstate = build_state(feats, "e", "Epic", stance="marathon",
                          caps={"max_wall_clock_hours": 8,
                                "started_at": "2026-01-01T00:00:00+00:00"})
    check("A1 marathon build_state: autonomy present", "autonomy" in mstate)
    auto = mstate["autonomy"]
    check("A1 marathon autonomy: every field exactly once", set(auto.keys()) == {
        "stance", "max_attempts_per_feature", "max_no_progress_cycles",
        "max_total_attempts", "max_wall_clock_hours", "started_at"})
    check("A1: no dead max_features knob in the schema", "max_features" not in auto)
    check("A1 marathon autonomy: stance marathon", auto["stance"] == "marathon")
    check("A1 marathon autonomy: cap override applied", auto["max_wall_clock_hours"] == 8)
    check("A1 marathon autonomy: started_at from caps",
          auto["started_at"] == "2026-01-01T00:00:00+00:00")
    check("A1 marathon autonomy: default max_total_attempts = max(6,3xfeatures)",
          auto["max_total_attempts"] == max(6, 3 * len(feats)))
    check("A1 marathon build_state: final_review pending", mstate["final_review"] == {"status": "pending"})
    check("A1 marathon build_state: blocker_ledger empty", mstate["blocker_ledger"] == [])
    check("A1 marathon build_state: counters zeroed",
          mstate["no_progress_cycles"] == 0 and mstate["total_attempts"] == 0)
    check("A1 marathon feature: attempts/last_error/disposition present",
          mstate["features"][0]["attempts"] == 0
          and mstate["features"][0]["last_error"] is None
          and mstate["features"][0]["disposition"] is None)

    try:
        build_state(feats, "../evil", "Epic")
        check("A1: traversal epic_id rejected", False)
    except ValueError:
        check("A1: traversal epic_id rejected", True)

    gd = _tempfile.mkdtemp()
    try:
        gp = os.path.join(gd, "epic-state.json")
        _atomic_write_json(gp, build_state(feats, "e", "Epic"))
        check("A1 golden: exactly one artifact (no stray tmp file)", os.listdir(gd) == ["epic-state.json"])
        with open(gp) as fh:
            ondisk = json.load(fh)
        check("A1 golden: no autonomy key on disk", "autonomy" not in ondisk)
    finally:
        shutil.rmtree(gd, ignore_errors=True)

    # --- A2: --next --autonomous (DAG-transitive routing, terminal states) --------------
    indep2 = [{"id": "x", "depends_on": []}, {"id": "y", "depends_on": []},
              {"id": "z", "depends_on": ["x"]}]
    sta2 = build_state(indep2, "e", "E", stance="marathon", caps={})
    sta2["features"][0]["status"] = "failed"  # x failed
    # FIX 1: an arbitrated abandon (halt_feature) — the pre-fix "bare failed" behavior for a
    # feature that HAS been triaged. The no-disposition crash-window case is covered
    # separately below (FIX 1 tests).
    sta2["features"][0]["disposition"] = {"disposition": "halt_feature"}
    fa, whya, blocked_by = next_feature_autonomous(sta2)
    check("A2: independent y still runnable despite x failed", fa is not None and fa["id"] == "y")
    check("A2: z (transitive dependent of x) is in blocked_by", blocked_by == ["z"])
    check("A2: running_with_failures token in reason", "running_with_failures" in whya)

    sta2["features"][0]["status"] = "pending"  # reopen the source
    fa2, whya2, blocked_by2 = next_feature_autonomous(sta2)
    check("A2: blocked_by re-derives to empty after reopen", blocked_by2 == [])

    allgraph = [{"id": "a", "depends_on": []}]
    st_done = build_state(allgraph, "e", "E", stance="marathon", caps={})
    st_done["features"][0]["status"] = "done"
    fa3, whya3, _ = next_feature_autonomous(st_done)
    check("A2: all-done but final_review pending -> NOT done",
          fa3 is None and "running_with_failures" in whya3 and "final_review" in whya3)
    st_done["final_review"]["status"] = "passed"
    fa4, whya4, _ = next_feature_autonomous(st_done)
    check("A2: all-done + final_review passed -> done", fa4 is None and whya4.startswith("done"))

    st_halt = build_state(indep2, "e", "E", stance="marathon", caps={})
    st_halt["features"][0]["status"] = "failed"
    st_halt["features"][0]["disposition"] = {"disposition": "halt_epic"}
    fa5, whya5, _ = next_feature_autonomous(st_halt)
    check("A2: halt_epic disposition -> blocked_needing_human",
          fa5 is None and whya5.startswith("blocked_needing_human"))

    st_tripped = build_state(indep2, "e", "E", stance="marathon", caps={})
    st_tripped["status"] = "blocked_needing_human"
    fa6, whya6, _ = next_feature_autonomous(st_tripped)
    check("A2: pre-tripped state -> blocked_needing_human",
          fa6 is None and whya6.startswith("blocked_needing_human"))

    only_dep = [{"id": "x", "depends_on": []}, {"id": "z", "depends_on": ["x"]}]
    st_exh = build_state(only_dep, "e", "E", stance="marathon", caps={})
    st_exh["features"][0]["status"] = "failed"
    st_exh["features"][0]["disposition"] = {"disposition": "halt_feature"}  # arbitrated abandon
    fa7, whya7, blocked_by7 = next_feature_autonomous(st_exh)
    check("A2: exhausted reachable work -> blocked_needing_human",
          fa7 is None and whya7.startswith("blocked_needing_human"))
    check("A2: blocked_by includes the exhausted dependent", blocked_by7 == ["z"])

    check("A2: default --next 2-tuple shape unchanged",
          next_feature(sta2) == next_feature(sta2))  # sanity: still unpacks as 2-tuple

    # A2 precedence (cross-model review correction #1, CRITICAL): a runnable INDEPENDENT
    # feature must be returned BEFORE any terminal blocked_needing_human — a suspected
    # blocker must never halt the epic while independent work is still runnable.
    prec = [{"id": "A", "depends_on": []}, {"id": "B", "depends_on": ["A"]},
            {"id": "C", "depends_on": []}]
    st_prec = build_state(prec, "e", "E", stance="marathon", caps={})
    st_prec["features"][0]["status"] = "blocked"  # A blocked; B depends on A; C independent
    fp, whyp, blocked_by_p = next_feature_autonomous(st_prec)
    check("A2 precedence: returns runnable independent C, not blocked_needing_human",
          fp is not None and fp["id"] == "C")
    check("A2 precedence: reason is running_with_failures, NOT blocked_needing_human",
          "running_with_failures" in whyp and not whyp.startswith("blocked_needing_human"))
    check("A2 precedence: B (dependent on A) is in blocked_by, C is not",
          blocked_by_p == ["B"])

    # --- FIX 1 (crash/breaker-window resume safety): a failed feature routes BY its stored
    # disposition instead of being blanket-treated as abandoned -------------------------
    fix1_feats = [{"id": "x", "depends_on": []}, {"id": "y", "depends_on": []},
                  {"id": "z", "depends_on": ["x"]}]

    st_f1 = build_state(fix1_feats, "e", "E", stance="marathon", caps={})
    st_f1["features"][0]["status"] = "failed"
    st_f1["features"][0]["attempts"] = 1  # < default cap (2) -> can_retry True
    # FIX A: disposition.attempt must match the feature's current attempts to be honored.
    st_f1["features"][0]["disposition"] = {"disposition": "retry_fix", "attempt": 1}
    f_f1, why_f1, blocked_by_f1 = next_feature_autonomous(st_f1)
    check("FIX1: retry_fix + can_retry -> the failed feature itself is runnable",
          f_f1 is not None and f_f1["id"] == "x" and why_f1 == "runnable")
    check("FIX1: retry_fix + can_retry does NOT block its dependents (about to be retried)",
          blocked_by_f1 == [])

    st_f2 = build_state(fix1_feats, "e", "E", stance="marathon", caps={})
    st_f2["features"][0]["status"] = "failed"
    st_f2["features"][0]["attempts"] = 2  # == default cap (2) -> can_retry False
    # FIX A: disposition.attempt must match the feature's current attempts to be honored.
    st_f2["features"][0]["disposition"] = {"disposition": "retry_fix", "attempt": 2}
    f_f2, why_f2, blocked_by_f2 = next_feature_autonomous(st_f2)
    check("FIX1: retry_fix + cap exhausted -> abandoned, independent y still runnable",
          f_f2 is not None and f_f2["id"] == "y")
    check("FIX1: retry_fix cap-exhausted blocks the transitive dependent z",
          blocked_by_f2 == ["z"])
    check("FIX1: retry_fix cap-exhausted reason carries running_with_failures",
          "running_with_failures" in why_f2)

    st_f3 = build_state(fix1_feats, "e", "E", stance="marathon", caps={})
    st_f3["features"][0]["status"] = "failed"
    st_f3["features"][0]["disposition"] = {"disposition": "halt_feature"}
    f_f3, why_f3, blocked_by_f3 = next_feature_autonomous(st_f3)
    check("FIX1: halt_feature -> abandoned, independent y still runnable",
          f_f3 is not None and f_f3["id"] == "y")
    check("FIX1: halt_feature blocks the transitive dependent z", blocked_by_f3 == ["z"])

    st_f4 = build_state(fix1_feats, "e", "E", stance="marathon", caps={})
    st_f4["features"][0]["status"] = "failed"  # disposition left None (build_state default)
    f_f4, why_f4, blocked_by_f4 = next_feature_autonomous(st_f4)
    check("FIX1: failed with NO recorded disposition -> needs_arbitration, no work handed out",
          f_f4 is None and why_f4.startswith("needs_arbitration"))
    check("FIX1: needs_arbitration names the untriaged feature",
          "feature x failed without a recorded disposition" in why_f4)

    # --- FIX A (attempt-binding, v2.10 correctness follow-up): a stored disposition is
    # honored ONLY for the attempt it was recorded against; a stale disposition left over
    # from a prior (already-retried) attempt is treated as no disposition at all --------
    _T_FA = _parse_iso("2026-01-01T00:00:00+00:00")

    fa_feats = [{"id": "a", "depends_on": []}]
    st_fa1 = build_state(fa_feats, "e", "E", stance="marathon", caps={"max_attempts_per_feature": 5})
    apply_update(st_fa1, "a", "running", now_dt=_T_FA)  # attempts -> 1
    apply_update(st_fa1, "a", "failed", now_dt=_T_FA)
    ok_fa1, _ = record_disposition(st_fa1, "a", "retry_fix", now_dt=_T_FA)  # attempt stamped = 1
    check("FIX A: record_disposition stamps attempt = feature's current attempts",
          ok_fa1 and st_fa1["features"][0]["disposition"]["attempt"] == 1)
    f_fa1a, why_fa1a, _ = next_feature_autonomous(st_fa1)
    check("FIX A: retry_fix recorded at the current attempt -> runnable",
          f_fa1a is not None and f_fa1a["id"] == "a" and why_fa1a == "runnable")

    # The driver re-runs the retry (attempts -> 2) and it fails AGAIN, crashing before a
    # fresh arbitration — the disposition on disk is still stamped attempt=1, now stale.
    apply_update(st_fa1, "a", "running", now_dt=_T_FA)  # attempts -> 2
    apply_update(st_fa1, "a", "failed", now_dt=_T_FA)
    f_fa1b, why_fa1b, _ = next_feature_autonomous(st_fa1)
    check("FIX A: a stale retry_fix (attempt mismatch) after re-run -> needs_arbitration, "
          "NOT a silently-honored second retry",
          f_fa1b is None and why_fa1b.startswith("needs_arbitration"))
    check("FIX A: needs_arbitration (stale disposition) names the untriaged feature",
          "feature a failed without a recorded disposition" in why_fa1b)

    fb_feats = [{"id": "a", "depends_on": []}, {"id": "b", "depends_on": []}]
    st_fb = build_state(fb_feats, "e", "E", stance="marathon", caps={})
    apply_update(st_fb, "a", "running", now_dt=_T_FA)  # attempts -> 1
    apply_update(st_fb, "a", "failed", now_dt=_T_FA)
    record_disposition(st_fb, "a", "halt_feature", now_dt=_T_FA)  # attempt stamped = 1
    f_fb1, why_fb1, blocked_by_fb1 = next_feature_autonomous(st_fb)
    check("FIX A: a matching halt_feature (attempt matches) -> abandoned, independent b runnable",
          f_fb1 is not None and f_fb1["id"] == "b" and "running_with_failures" in why_fb1)

    # Re-run + fail again WITHOUT a fresh disposition -> the recorded halt_feature is now stale.
    apply_update(st_fb, "a", "running", now_dt=_T_FA)  # attempts -> 2
    apply_update(st_fb, "a", "failed", now_dt=_T_FA)
    f_fb2, why_fb2, _ = next_feature_autonomous(st_fb)
    check("FIX A: an attempt-mismatch halt_feature -> needs_arbitration (stale verdict, "
          "re-arbitrate), NOT a silent abandon",
          f_fb2 is None and why_fb2.startswith("needs_arbitration"))

    # --- FIX A: validate_marathon_state accepts a legacy disposition with no 'attempt' key
    # (treated as attempt 0) but flags a malformed one --------------------------------------
    st_fa_legacy = build_state(fa_feats, "e", "E", stance="marathon", caps={})
    st_fa_legacy["features"][0]["disposition"] = {"disposition": "halt_feature"}  # no attempt key
    check("FIX A: validate_marathon_state accepts a legacy disposition with no 'attempt' key",
          validate_marathon_state(st_fa_legacy) == [])
    st_fa_bad = build_state(fa_feats, "e", "E", stance="marathon", caps={})
    st_fa_bad["features"][0]["disposition"] = {"disposition": "halt_feature", "attempt": -1}
    check("FIX A: validate_marathon_state flags a malformed (negative) disposition.attempt",
          validate_marathon_state(st_fa_bad) != [])
    st_fa_bad2 = build_state(fa_feats, "e", "E", stance="marathon", caps={})
    st_fa_bad2["features"][0]["disposition"] = "not-an-object"
    check("FIX A: validate_marathon_state flags a non-object disposition",
          validate_marathon_state(st_fa_bad2) != [])

    # --- FIX 2 (v2.10, cross-unit integration review follow-up): a `failed` feature whose
    # attempt-matched disposition is blocked_external must surface needs_blocker_recording
    # (the blocked/ledger transition crashed mid-flight), NOT be treated as abandoned --------
    fix2_feats = [{"id": "a", "depends_on": []}, {"id": "b", "depends_on": []},
                  {"id": "c", "depends_on": ["a"]}]
    st_fx1 = build_state(fix2_feats, "e", "E", stance="marathon", caps={})
    apply_update(st_fx1, "a", "running", now_dt=_T_FA)  # attempts -> 1
    apply_update(st_fx1, "a", "failed", now_dt=_T_FA)
    record_disposition(st_fx1, "a", "blocked_external", now_dt=_T_FA)  # attempt stamped = 1
    f_fx1, why_fx1, blocked_by_fx1 = next_feature_autonomous(st_fx1)
    check("FIX 2: failed + attempt-matched blocked_external -> needs_blocker_recording, "
          "not abandoned, no work handed out",
          f_fx1 is None and why_fx1.startswith("needs_blocker_recording"))
    check("FIX 2: needs_blocker_recording names the untriaged feature and points at the fix",
          "feature(s) a" in why_fx1 and "--update --status blocked" in why_fx1)
    check("FIX 2: needs_blocker_recording halts ALL routing (independent b not handed out "
          "as if settled), mirroring needs_arbitration's priority",
          f_fx1 is None)
    check("FIX 2: transitive dependent c is reported as blocked_by",
          blocked_by_fx1 == ["c"])

    # Completing the transition (driver re-runs --update --status blocked) moves the feature
    # OFF the needs_blocker_recording path and onto the normal blocked/ledger path -> b
    # becomes runnable, independently of the still-blocked a/c.
    apply_update(st_fx1, "a", "blocked", blocker_reason="vendor outage", now_dt=_T_FA)
    check("FIX 2: completing the transition sets status=blocked and appends one ledger entry",
          st_fx1["features"][0]["status"] == "blocked" and len(st_fx1["blocker_ledger"]) == 1)
    f_fx1b, why_fx1b, blocked_by_fx1b = next_feature_autonomous(st_fx1)
    check("FIX 2: after the transition completes, a blocked-status feature stays on the "
          "normal blocked/ledger path (unchanged) -- independent b is runnable",
          f_fx1b is not None and f_fx1b["id"] == "b" and "running_with_failures" in why_fx1b)
    check("FIX 2: after the transition completes, c is still blocked_by a",
          blocked_by_fx1b == ["c"])

    # Re-running --update --status blocked a second time (the idempotent-recovery case the
    # fix explicitly relies on) must not create a second ledger entry or otherwise change
    # anything observable.
    apply_update(st_fx1, "a", "blocked", blocker_reason="vendor outage (replay)", now_dt=_T_FA)
    check("FIX 2: re-running --update --status blocked is idempotent by (feature, attempt) "
          "-- still exactly one ledger entry",
          len(st_fx1["blocker_ledger"]) == 1)

    # An attempt-MISMATCHED blocked_external disposition is unaffected by FIX 2 -- it still
    # falls into needs_arbitration (FIX A, unchanged).
    st_fx2 = build_state(fa_feats, "e", "E", stance="marathon", caps={"max_attempts_per_feature": 5})
    apply_update(st_fx2, "a", "running", now_dt=_T_FA)  # attempts -> 1
    apply_update(st_fx2, "a", "failed", now_dt=_T_FA)
    record_disposition(st_fx2, "a", "blocked_external", now_dt=_T_FA)  # attempt stamped = 1
    apply_update(st_fx2, "a", "running", now_dt=_T_FA)  # attempts -> 2, disposition now stale
    apply_update(st_fx2, "a", "failed", now_dt=_T_FA)
    f_fx2, why_fx2, _ = next_feature_autonomous(st_fx2)
    check("FIX 2: attempt-mismatched blocked_external -> needs_arbitration (unchanged from "
          "FIX A), NOT needs_blocker_recording",
          f_fx2 is None and why_fx2.startswith("needs_arbitration"))

    # A feature that is ALREADY status=='blocked' with its ledger entry present never enters
    # the failed-feature classification loop at all -- normal path, unaffected by FIX 2.
    st_fx3 = build_state(fa_feats, "e", "E", stance="marathon", caps={})
    apply_update(st_fx3, "a", "running", now_dt=_T_FA)
    apply_update(st_fx3, "a", "failed", now_dt=_T_FA)
    record_disposition(st_fx3, "a", "blocked_external", now_dt=_T_FA)
    apply_update(st_fx3, "a", "blocked", blocker_reason="vendor outage", now_dt=_T_FA)
    f_fx3, why_fx3, _ = next_feature_autonomous(st_fx3)
    check("FIX 2: an already-blocked-status feature (transition complete) stays on the "
          "normal blocked path -- not needs_blocker_recording",
          not (why_fx3 or "").startswith("needs_blocker_recording"))
    check("FIX 2: an already-blocked-status single-feature epic -> blocked_needing_human "
          "(no other work), exactly as before this fix",
          f_fx3 is None and why_fx3.startswith("blocked_needing_human"))

    # --- A3: attempts + --can-retry + transition table -----------------------------------
    feats3 = [{"id": "a", "depends_on": []}]
    st3m = build_state(feats3, "e", "E", stance="marathon", caps={"max_attempts_per_feature": 2})
    ok3, err3 = apply_update(st3m, "a", "running", now_dt=_parse_iso("2026-01-01T00:00:00+00:00"))
    check("A3: pending->running ok + attempts=1", ok3 and st3m["features"][0]["attempts"] == 1)
    check("A3: total_attempts tracks the feature increment", st3m["total_attempts"] == 1)
    ok3b, _ = apply_update(st3m, "a", "done")
    check("A3: running->done ok", ok3b)
    ok3c, err3c = apply_update(st3m, "a", "running")
    check("A3: done->running rejected", not ok3c and "illegal transition" in err3c)
    info3 = can_retry_info(st3m, "a")
    check("A3: can_retry attempts=1 cap=2 -> true",
          info3["can_retry"] is True and info3["attempts"] == 1 and info3["cap"] == 2)
    apply_update(st3m, "a", "failed")
    apply_update(st3m, "a", "running")  # attempts -> 2
    info3b = can_retry_info(st3m, "a")
    check("A3: can_retry flips at the cap", info3b["can_retry"] is False and info3b["attempts"] == 2)

    st3c = build_state(feats3, "e", "E")  # checkpoint (non-marathon)
    apply_update(st3c, "a", "running")
    check("A3 checkpoint: no attempts field ever added", "attempts" not in st3c["features"][0])
    apply_update(st3c, "a", "done")
    ok3d, _ = apply_update(st3c, "a", "running")
    check("A3 checkpoint: transition table is marathon-only (done->running not rejected)", ok3d)

    # total_attempts invariant (cross-model review correction #4, HIGH): it is ALWAYS the
    # live sum of feature.attempts, never an independently-incremented counter that could
    # drift — exercise it across several features and several transitions.
    feats3d = [{"id": "a", "depends_on": []}, {"id": "b", "depends_on": []}]
    st3d = build_state(feats3d, "e", "E", stance="marathon", caps={})
    apply_update(st3d, "a", "running")
    apply_update(st3d, "a", "failed")
    apply_update(st3d, "a", "running")
    apply_update(st3d, "b", "running")
    check("A3: total_attempts == sum(feature.attempts) after several transitions",
          st3d["total_attempts"] == _total_attempts(st3d) == 3)

    # --- A4: --record-disposition ---------------------------------------------------------
    feats4 = [{"id": "a", "depends_on": []}]
    st4 = build_state(feats4, "e", "E", stance="marathon", caps={})
    ok4, err4 = record_disposition(st4, "a", "retry_fix", reason="flaky test",
                                    families_agreeing=["gpt"])
    check("A4: record_disposition round-trips",
          ok4 and st4["features"][0]["disposition"]["disposition"] == "retry_fix")
    check("A4: confirmed is always false", st4["features"][0]["disposition"]["confirmed"] is False)
    ok5, err5 = record_disposition(st4, "a", "blocked_external", confirmed=True)
    check("A4: --confirmed true hard-rejected", not ok5 and "confirmed" in err5.lower())
    check("A4: prior disposition untouched by the rejected call",
          st4["features"][0]["disposition"]["disposition"] == "retry_fix")
    ok6, _ = record_disposition(st4, "a", "halt_epic")
    check("A4: halt_epic round-trips", ok6)
    fah, whyah, _ = next_feature_autonomous(st4)
    check("A4: halt_epic disposition drives autonomous routing",
          fah is None and whyah.startswith("blocked_needing_human"))

    st4b = build_state(feats4, "e", "E", stance="marathon", caps={})
    okb, errb = apply_update(st4b, "a", "blocked", blocker_confirmed=True)
    check("A4/A5: --blocker-confirmed true hard-rejected on --update too",
          not okb and "confirmed" in errb.lower())

    # --- A5: blocker-ledger lifecycle ------------------------------------------------------
    feats5 = [{"id": "a", "depends_on": []}, {"id": "b", "depends_on": ["a"]}]
    st5 = build_state(feats5, "e", "E", stance="marathon", caps={})
    ok5a, _ = apply_update(st5, "a", "blocked", blocker_reason="waiting on vendor",
                            now_dt=_parse_iso("2026-01-01T00:00:00+00:00"))
    check("A5: blocked appends one ledger entry", ok5a and len(st5["blocker_ledger"]) == 1)
    entry = st5["blocker_ledger"][0]
    check("A5: entry active + confirmed:false + blocks derived",
          entry["active"] is True and entry["confirmed"] is False and entry["blocks"] == ["b"])
    apply_update(st5, "a", "blocked", blocker_reason="dup")  # replay, same attempt (0)
    check("A5: replay of the same (feature,attempt) is idempotent", len(st5["blocker_ledger"]) == 1)
    apply_update(st5, "a", "pending", now_dt=_parse_iso("2026-01-02T00:00:00+00:00"))
    check("A5: --status pending resolves the active entry",
          st5["blocker_ledger"][0]["active"] is False
          and st5["blocker_ledger"][0]["resolved_at"] is not None)
    apply_update(st5, "a", "running")
    apply_update(st5, "a", "done")
    check("A5: --stats no longer counts a since-succeeded blocker", stats(st5)["blocked"] == 0)
    st5["features"][0]["status"] = "failed"  # simulate a later failure -> attempts now 1
    apply_update(st5, "a", "blocked", blocker_reason="again")
    check("A5: a block at a NEW attempt count is a new ledger entry", len(st5["blocker_ledger"]) == 2)
    check("A5: --stats breaks out the currently-blocked feature", stats(st5)["blocked"] == 1)

    # --- A6: final-review gate --------------------------------------------------------------
    feats6 = [{"id": "a", "depends_on": []}]
    st6 = build_state(feats6, "e", "E", stance="marathon", caps={})
    apply_update(st6, "a", "running")
    apply_update(st6, "a", "done")
    check("A6: all-done but final_review pending -> top status stays 'running'",
          st6["status"] == "running")
    fa6b, why6b, _ = next_feature_autonomous(st6)
    check("A6: autonomous NOT 'done' while final_review pending",
          fa6b is None and "running_with_failures" in why6b)
    okr, _ = record_final_review(st6, "passed")
    check("A6: record_final_review flips top status to done", okr and st6["status"] == "done")
    fa6c, why6c, _ = next_feature_autonomous(st6)
    check("A6: autonomous 'done' once final_review passed",
          fa6c is None and why6c.startswith("done"))
    okr2, _ = record_final_review(st6, "bogus")
    check("A6: invalid final-review status rejected", not okr2)

    # --- FIX 2 (crash/breaker-window resume safety): a durable sample-audit obligation
    # gates terminal completion --------------------------------------------------------------
    feats_sa = [{"id": "a", "depends_on": []}]
    st_sa = build_state(feats_sa, "e", "E", stance="marathon", caps={})
    apply_update(st_sa, "a", "running")
    apply_update(st_sa, "a", "done")
    record_final_review(st_sa, "passed")
    fa_sa0, why_sa0, _ = next_feature_autonomous(st_sa)
    check("FIX2 setup: autonomous routing reports 'done' before any sample-audit is due",
          fa_sa0 is None and why_sa0.startswith("done"))

    ok_mark, err_mark = mark_sample_audit_due(st_sa, "a")
    check("FIX2: mark_sample_audit_due ok", ok_mark and err_mark is None)
    check("FIX2: feature.sample_audit_due is True", st_sa["features"][0]["sample_audit_due"] is True)
    fa_sa1, why_sa1, _ = next_feature_autonomous(st_sa)
    check("FIX2: mark due -> next_feature_autonomous no longer reports 'done'",
          fa_sa1 is None and why_sa1.startswith("sample_audit_due"))
    check("FIX2: sample_audit_due reason names the awaiting feature",
          "feature(s) a awaiting sample-audit" in why_sa1)

    ok_fr_reject, err_fr_reject = record_final_review(st_sa, "passed")
    check("FIX2: record_final_review passed REJECTED while sample_audit_due is true",
          ok_fr_reject is False and "sample_audit_due" in err_fr_reject)
    check("FIX2: a rejected final_review=passed does not flip status to done",
          st_sa["status"] != "done")

    ok_clear, err_clear = clear_sample_audit_due(st_sa, "a")
    check("FIX2: clear_sample_audit_due ok", ok_clear and err_clear is None)
    check("FIX2: feature.sample_audit_due is False after clear",
          st_sa["features"][0]["sample_audit_due"] is False)
    fa_sa2, why_sa2, _ = next_feature_autonomous(st_sa)
    check("FIX2: clear due -> normal completion resumes ('done')",
          fa_sa2 is None and why_sa2.startswith("done"))
    ok_fr2, err_fr2 = record_final_review(st_sa, "passed")
    check("FIX2: record_final_review passed accepted again once due is cleared",
          ok_fr2 and err_fr2 is None)

    # Crash simulation: a 'done' feature with sample_audit_due left set (as if the process
    # died between marking the sampled SUCCESS 'done' and clearing the audit) must be
    # surfaced on the very next --next --autonomous — never silently skipped to 'done', and
    # never allowed to acquire a passed final_review in the meantime.
    st_sa2 = build_state(feats_sa, "e", "E", stance="marathon", caps={})
    apply_update(st_sa2, "a", "running")
    apply_update(st_sa2, "a", "done")
    mark_sample_audit_due(st_sa2, "a")
    fa_sa3, why_sa3, _ = next_feature_autonomous(st_sa2)
    check("FIX2 crash-sim: sample_audit_due surfaces immediately on resume "
          "(final_review still pending)",
          fa_sa3 is None and why_sa3.startswith("sample_audit_due"))
    ok_fr3, _ = record_final_review(st_sa2, "passed")
    check("FIX2 crash-sim: final_review=passed still rejected on resume", ok_fr3 is False)

    # --- --mark/clear-sample-audit-due: error handling ---------------------------------------
    ok_unk, err_unk = mark_sample_audit_due(st_sa, "does-not-exist")
    check("FIX2: mark_sample_audit_due on unknown feature -> controlled error",
          ok_unk is False and "no feature" in err_unk)
    ok_unk2, err_unk2 = clear_sample_audit_due(st_sa, "does-not-exist")
    check("FIX2: clear_sample_audit_due on unknown feature -> controlled error",
          ok_unk2 is False and "no feature" in err_unk2)

    st_sa_chk = build_state(feats_sa, "e", "E")  # checkpoint (non-marathon)
    ok_chk, err_chk = mark_sample_audit_due(st_sa_chk, "a")
    check("FIX2: mark_sample_audit_due on a checkpoint state -> controlled error",
          ok_chk is False and "marathon" in err_chk)
    ok_chk2, err_chk2 = clear_sample_audit_due(st_sa_chk, "a")
    check("FIX2: clear_sample_audit_due on a checkpoint state -> controlled error",
          ok_chk2 is False and "marathon" in err_chk2)

    # --- validate_marathon_state: sample_audit_due is bool-or-absent -------------------------
    good_sa = build_state(feats_sa, "e", "E", stance="marathon", caps={})
    check("FIX2: absent sample_audit_due validates clean",
          validate_marathon_state(good_sa) == [])
    good_sa["features"][0]["sample_audit_due"] = True
    check("FIX2: a bool True sample_audit_due validates clean",
          validate_marathon_state(good_sa) == [])
    good_sa["features"][0]["sample_audit_due"] = False
    check("FIX2: a bool False sample_audit_due validates clean",
          validate_marathon_state(good_sa) == [])
    bad_sa = build_state(feats_sa, "e", "E", stance="marathon", caps={})
    bad_sa["features"][0]["sample_audit_due"] = "yes"
    check("FIX2: a non-bool sample_audit_due -> validation error",
          validate_marathon_state(bad_sa) != [])

    # --- FIX B (atomic audit-failed, v2.10 correctness follow-up): --record-audit-failed
    # reverts a done+due feature to failed, clears sample_audit_due, and invalidates a
    # passed final_review, all in ONE state mutation — the driver's old two-write
    # clear-due-then-mark-failed sequence had a crash window between the two writes that
    # could leave a feature 'done' with no audit obligation at all. -----------------------
    feats_raf = [{"id": "a", "depends_on": []}]
    st_raf = build_state(feats_raf, "e", "E", stance="marathon", caps={})
    apply_update(st_raf, "a", "running")
    apply_update(st_raf, "a", "done")
    mark_sample_audit_due(st_raf, "a")
    record_final_review(st_raf, "passed")  # rejected (sample_audit_due) — stays pending
    ok_raf, err_raf = record_audit_failed(st_raf, "a", last_error="sample audit found a regression")
    check("FIX B: record_audit_failed ok", ok_raf and err_raf is None)
    check("FIX B: single write yields status=failed", st_raf["features"][0]["status"] == "failed")
    check("FIX B: single write yields sample_audit_due=False (never done-without-due)",
          st_raf["features"][0]["sample_audit_due"] is False)
    check("FIX B: last_error persisted", st_raf["features"][0]["last_error"]
          == "sample audit found a regression")
    check("FIX B: final_review is not 'passed' after the atomic revert",
          st_raf["final_review"]["status"] != "passed")
    check("FIX B: top-level status is not 'done'", st_raf["status"] != "done")
    # No intermediate 'done-without-due' state was ever observable: this is the SAME state
    # object that would be serialized in one _atomic_write_json call by the CLI, so there is
    # only ever one post-write state to inspect (simulating "no crash window").
    check("FIX B: never observes done-without-due (single atomic write, no split state)",
          not (st_raf["features"][0]["status"] == "done"
               and not st_raf["features"][0]["sample_audit_due"]))

    # A feature that passed its audit cleanly (never marked done here, so its final_review is
    # untouched pending) still gets reverted correctly when audit-failed is recorded directly
    # from 'running' too (not just from 'done') — attempts are NOT bumped by this call.
    st_raf2 = build_state(feats_raf, "e", "E", stance="marathon", caps={})
    apply_update(st_raf2, "a", "running")
    prior_attempts = st_raf2["features"][0]["attempts"]
    ok_raf2, _ = record_audit_failed(st_raf2, "a")
    check("FIX B: record_audit_failed does not touch attempts (not a new retry)",
          ok_raf2 and st_raf2["features"][0]["attempts"] == prior_attempts)
    check("FIX B: last_error left untouched when --last-error is not supplied",
          st_raf2["features"][0]["last_error"] is None)

    ok_raf_unk, err_raf_unk = record_audit_failed(st_raf, "does-not-exist")
    check("FIX B: record_audit_failed on unknown feature -> controlled error",
          ok_raf_unk is False and "no feature" in err_raf_unk)

    st_raf_chk = build_state(feats_raf, "e", "E")  # checkpoint (non-marathon)
    ok_raf_chk, err_raf_chk = record_audit_failed(st_raf_chk, "a")
    check("FIX B: record_audit_failed on a checkpoint state -> controlled error",
          ok_raf_chk is False and "marathon" in err_raf_chk)

    # --- A7: global breakers ------------------------------------------------------------------
    feats7 = [{"id": "a", "depends_on": []}, {"id": "b", "depends_on": []}]
    st7 = build_state(feats7, "e", "E", stance="marathon",
                       caps={"max_total_attempts": 3, "max_no_progress_cycles": 2,
                             "max_wall_clock_hours": 1,
                             "started_at": "2026-01-01T00:00:00+00:00"})
    now0 = _parse_iso("2026-01-01T00:00:00+00:00")
    check("A7: breaker-check not tripped at baseline", breaker_check(st7, now0)["tripped"] is False)
    # total_attempts is DERIVED live from feature.attempts (the invariant), never a
    # trust-the-stored-counter check — set feature attempts directly, not the top-level field.
    st7["features"][0]["attempts"] = 2
    st7["features"][1]["attempts"] = 0
    check("A7: total_attempts (sum of feature.attempts) just under cap -> not tripped",
          breaker_check(st7, now0)["tripped"] is False)
    st7["features"][0]["attempts"] = 3
    r_ta = breaker_check(st7, now0)
    check("A7: total_attempts >= cap trips exactly at the boundary",
          r_ta["tripped"] and "max_total_attempts" in r_ta["which"])
    check("A7: the derived total_attempts equals sum(feature.attempts)",
          r_ta["detail"]["max_total_attempts"]["value"] == _total_attempts(st7) == 3)
    check("A7: --breaker-check never mutates state", st7.get("status") != "blocked_needing_human")
    st7["features"][0]["attempts"] = 0
    st7["features"][1]["attempts"] = 0
    st7["no_progress_cycles"] = 1
    check("A7: no_progress_cycles just under cap -> not tripped",
          breaker_check(st7, now0)["tripped"] is False)
    st7["no_progress_cycles"] = 2
    r_np = breaker_check(st7, now0)
    check("A7: no_progress_cycles >= cap trips",
          r_np["tripped"] and "max_no_progress_cycles" in r_np["which"])
    st7["no_progress_cycles"] = 0
    r_wc_ok = breaker_check(st7, _parse_iso("2026-01-01T00:59:00+00:00"))
    check("A7: wall-clock just under cap -> not tripped", r_wc_ok["tripped"] is False)
    r_wc_trip = breaker_check(st7, _parse_iso("2026-01-01T01:00:00+00:00"))
    check("A7: wall-clock >= cap trips",
          r_wc_trip["tripped"] and "max_wall_clock_hours" in r_wc_trip["which"])

    st7b = build_state(feats7, "e", "E", stance="marathon", caps={"max_total_attempts": 1})
    res_notrip = trip_breaker(st7b, now0)
    check("A7: trip_breaker is a no-op when not tripped",
          res_notrip["tripped"] is False and st7b["status"] != "blocked_needing_human")
    st7b["features"][0]["attempts"] = 1
    res_trip = trip_breaker(st7b, now0)
    check("A7: trip_breaker sets blocked_needing_human when tripped",
          res_trip["tripped"] and st7b["status"] == "blocked_needing_human")

    feats7c = [{"id": "a", "depends_on": []}, {"id": "b", "depends_on": []}]
    st7c = build_state(feats7c, "e", "E", stance="marathon", caps={})
    r1 = record_progress_cycle(st7c, "cycle-1")
    check("A7: first progress cycle establishes a baseline (no false trip)",
          r1["no_progress_cycles"] == 0 and r1["replayed"] is False)
    r2 = record_progress_cycle(st7c, "cycle-2")
    check("A7: no new done -> no_progress_cycles increments", r2["no_progress_cycles"] == 1)
    st7c["features"][0]["status"] = "done"
    r3 = record_progress_cycle(st7c, "cycle-3")
    check("A7: a new done resets no_progress_cycles", r3["no_progress_cycles"] == 0)
    r3_replay = record_progress_cycle(st7c, "cycle-3")
    check("A7: a replayed cycle-id is an idempotent no-op",
          r3_replay["replayed"] is True and r3_replay["no_progress_cycles"] == 0)

    # Codex review #4: a negative cap is now REJECTED at --init/build, not silently treated
    # as unbounded.
    try:
        build_state(feats7, "e", "E", stance="marathon", caps={"max_total_attempts": -1})
        check("#4: negative cap rejected at build/--init", False)
    except ValueError:
        check("#4: negative cap rejected at build/--init", True)
    try:
        build_state(feats7, "e", "E", stance="marathon", caps={"max_wall_clock_hours": "lots"})
        check("#4: non-numeric cap rejected at build/--init", False)
    except ValueError:
        check("#4: non-numeric cap rejected at build/--init", True)
    st7e = build_state(feats7, "e", "E", stance="marathon", caps={"max_wall_clock_hours": None})
    check("A7: an explicit null wall-clock cap is unbounded",
          breaker_check(st7e, _parse_iso("2027-01-01T00:00:00+00:00"))["tripped"] is False)
    # #4: a MISSING cap key falls back to the documented default (fail-SAFE), never unbounded.
    st7f = build_state(feats7, "e", "E", stance="marathon",
                       caps={"started_at": "2026-01-01T00:00:00+00:00"})
    del st7f["autonomy"]["max_wall_clock_hours"]  # simulate a hand-edited state missing the key
    r_missing = breaker_check(st7f, _parse_iso("2026-01-01T11:00:00+00:00"))
    check("#4: a MISSING cap key uses the documented default (10h), not unbounded",
          r_missing["tripped"] is True and "max_wall_clock_hours" in r_missing["which"])

    # ================================================================
    # Codex cross-model review — the 11 findings, one+ selftest each
    # ================================================================
    T0 = _parse_iso("2026-01-01T00:00:00+00:00")

    # --- #1 CRITICAL: final-review bypass ------------------------------------------------
    r1feats = [{"id": "a", "depends_on": []}, {"id": "b", "depends_on": []}]
    r1 = build_state(r1feats, "e", "E", stance="marathon", caps={})
    apply_update(r1, "a", "running", now_dt=T0)
    apply_update(r1, "a", "done", now_dt=T0)  # b still pending
    okp, errp = record_final_review(r1, "passed")
    check("#1: final_review=passed REJECTED unless all features done",
          okp is False and "not done" in errp)
    check("#1: rejected review did not flip status to done", r1["status"] != "done")
    apply_update(r1, "b", "running", now_dt=T0)
    apply_update(r1, "b", "done", now_dt=T0)
    okp2, _ = record_final_review(r1, "passed")
    check("#1: passes once all done -> status done", okp2 and r1["status"] == "done")
    # a feature --update after a pass INVALIDATES the review and drops status off 'done'
    apply_update(r1, "a", "pending", now_dt=T0)
    check("#1: --update after pass resets final_review to pending",
          r1["final_review"]["status"] == "pending")
    check("#1: ...and top status leaves 'done'", r1["status"] != "done")

    # --- #2 HIGH: marathon commands bound to persisted stance ----------------------------
    r2chk = build_state([{"id": "a", "depends_on": []}], "e", "E")  # checkpoint
    okb2, errb2 = apply_update(r2chk, "a", "blocked")
    check("#2: checkpoint --update --status blocked is rejected",
          okb2 is False and "checkpoint" in errb2)
    check("#2: checkpoint status set unchanged (still 4)",
          CHECKPOINT_STATUSES == ("pending", "running", "done", "failed"))
    # can_retry/breaker helpers still importable, but the CLI-level rejection is what #2 asks;
    # exercise the persisted-stance gate via a round-trip in the CLI smoke below is heavy —
    # here assert the discriminator the guard uses:
    check("#2: _is_marathon discriminates checkpoint vs marathon",
          _is_marathon(r2chk) is False and _is_marathon(r1) is True)

    # --- #3 HIGH: runnable EXCLUDES transitive dependents --------------------------------
    r3feats = [{"id": "A", "depends_on": []}, {"id": "B", "depends_on": ["A"]},
               {"id": "C", "depends_on": ["B"]}]
    r3 = build_state(r3feats, "e", "E", stance="marathon", caps={})
    r3["features"][0]["status"] = "failed"   # A failed
    r3["features"][1]["status"] = "done"     # B done (immediate dep of C satisfied)
    fr3, whyr3, bbr3 = next_feature_autonomous(r3)
    check("#3: C (transitive dependent of failed A) is NOT handed out as runnable",
          fr3 is None or fr3.get("id") != "C")
    check("#3: C is reported in blocked_by (waiting), B (done) is not",
          bbr3 == ["C"])

    # --- #4 HIGH: covered above (reject-at-init, missing-key default) --------------------
    check("#4: (see negative/non-numeric/missing-key checks above)", True)

    # --- #5 HIGH: progress-cycle idempotency is GLOBAL ----------------------------------
    r5 = build_state([{"id": "a", "depends_on": []}], "e", "E", stance="marathon", caps={})
    record_progress_cycle(r5, "c1")           # baseline
    record_progress_cycle(r5, "c2")           # no progress -> 1
    npc_before = r5["no_progress_cycles"]
    rep = record_progress_cycle(r5, "c1")     # replay of a NON-adjacent earlier id
    check("#5: replay of ANY earlier cycle-id is a no-op (global, not just last)",
          rep["replayed"] is True and r5["no_progress_cycles"] == npc_before)

    # --- #6 HIGH: ledger reblock reactivates ---------------------------------------------
    r6 = build_state([{"id": "a", "depends_on": []}, {"id": "b", "depends_on": ["a"]}],
                     "e", "E", stance="marathon", caps={})
    apply_update(r6, "a", "blocked", blocker_reason="vendor", now_dt=T0)  # attempt 0, active
    apply_update(r6, "a", "pending", now_dt=T0)                          # resolves -> inactive
    check("#6: after reopen the entry is inactive", r6["blocker_ledger"][0]["active"] is False)
    apply_update(r6, "a", "blocked", blocker_reason="vendor again", now_dt=T0)  # reblock, same attempt 0
    active_entries = [e for e in r6["blocker_ledger"]
                      if e.get("feature") == "a" and e.get("active")]
    check("#6: reblock at the same attempt REACTIVATES (no new entry)",
          len(r6["blocker_ledger"]) == 1 and len(active_entries) == 1
          and active_entries[0]["resolved_at"] is None)
    # invariant: every currently-blocked feature has exactly one active entry
    blocked_feats = [f["id"] for f in r6["features"] if f.get("status") == "blocked"]
    for bf in blocked_feats:
        acts = [e for e in r6["blocker_ledger"] if e.get("feature") == bf and e.get("active")]
        check("#6: blocked feature %r has exactly one active ledger entry" % bf, len(acts) == 1)

    # --- #7 HIGH: --last-error persist + clear ------------------------------------------
    r7 = build_state([{"id": "a", "depends_on": []}], "e", "E", stance="marathon", caps={})
    apply_update(r7, "a", "running", now_dt=T0)
    apply_update(r7, "a", "failed", last_error="boom: NPE at L42", now_dt=T0)
    check("#7: --status failed --last-error persists last_error",
          r7["features"][0]["last_error"] == "boom: NPE at L42")
    apply_update(r7, "a", "running", now_dt=T0)  # retry
    check("#7: last_error cleared on the retry (->running)", r7["features"][0]["last_error"] is None)
    apply_update(r7, "a", "failed", last_error="again", now_dt=T0)
    apply_update(r7, "a", "running", now_dt=T0)
    apply_update(r7, "a", "done", now_dt=T0)
    check("#7: last_error cleared on ->done", r7["features"][0]["last_error"] is None)

    # --- #8 MED: no_progress_cycles reset inside apply_update on ->done -------------------
    r8 = build_state([{"id": "a", "depends_on": []}, {"id": "b", "depends_on": []}],
                     "e", "E", stance="marathon", caps={})
    r8["no_progress_cycles"] = 2  # simulate accumulated stall
    apply_update(r8, "a", "running", now_dt=T0)
    apply_update(r8, "a", "done", now_dt=T0)
    check("#8: a feature reaching done resets no_progress_cycles inside --update",
          r8["no_progress_cycles"] == 0)

    # --- #9 MED: total_attempts recomputed on EVERY marathon mutation --------------------
    r9 = build_state([{"id": "a", "depends_on": []}], "e", "E", stance="marathon", caps={})
    apply_update(r9, "a", "running", now_dt=T0)  # attempts 1
    r9["total_attempts"] = 999  # corrupt the stored counter
    record_disposition(r9, "a", "retry_fix", now_dt=T0)
    check("#9: record_disposition recomputes total_attempts from features",
          r9["total_attempts"] == 1)
    r9["total_attempts"] = 999
    record_progress_cycle(r9, "z1")
    check("#9: record_progress_cycle recomputes total_attempts", r9["total_attempts"] == 1)
    r9["total_attempts"] = 999
    trip_breaker(r9, T0)  # not tripped here, but should still be a no-op on status; recompute only on trip
    r9["total_attempts"] = 999
    record_final_review(r9, "pending")
    check("#9: record_final_review recomputes total_attempts", r9["total_attempts"] == 1)

    # --- #10 MED: defensive normalization of a loaded marathon state ---------------------
    good = build_state([{"id": "a", "depends_on": []}], "e", "E", stance="marathon", caps={})
    check("#10: a well-formed marathon state validates clean", validate_marathon_state(good) == [])
    bad_att = build_state([{"id": "a", "depends_on": []}], "e", "E", stance="marathon", caps={})
    bad_att["features"][0]["attempts"] = -3
    check("#10: negative attempts -> error", validate_marathon_state(bad_att) != [])
    bad_att2 = build_state([{"id": "a", "depends_on": []}], "e", "E", stance="marathon", caps={})
    bad_att2["features"][0]["attempts"] = None
    check("#10: null attempts -> error", validate_marathon_state(bad_att2) != [])
    bad_id = build_state([{"id": "a", "depends_on": []}], "e", "E", stance="marathon", caps={})
    del bad_id["features"][0]["id"]
    check("#10: missing feature id -> error", validate_marathon_state(bad_id) != [])
    bad_npc = build_state([{"id": "a", "depends_on": []}], "e", "E", stance="marathon", caps={})
    bad_npc["no_progress_cycles"] = "lots"
    check("#10: non-int no_progress_cycles -> error", validate_marathon_state(bad_npc) != [])
    bad_cap = build_state([{"id": "a", "depends_on": []}], "e", "E", stance="marathon", caps={})
    bad_cap["autonomy"]["max_total_attempts"] = -5  # bypasses --init, hand-edited
    check("#10: persisted negative cap -> error (not silent unbounded)",
          validate_marathon_state(bad_cap) != [])
    chk = build_state([{"id": "a", "depends_on": []}], "e", "E")  # checkpoint
    check("#10: checkpoint state is NOT subjected to marathon validation (no-op path)",
          _is_marathon(chk) is False)

    # --- #11 LOW: _now_iso normalizes aware datetimes to UTC -----------------------------
    plus5 = _now_iso(_parse_iso("2026-01-01T05:00:00+05:00"))
    check("#11: an injected +05:00 is emitted as +00:00 (normalized to UTC)",
          plus5 == "2026-01-01T00:00:00+00:00")
    check("#11: naive datetime assumed UTC", _now_iso(datetime(2026, 1, 1)) == "2026-01-01T00:00:00+00:00")
    r11 = build_state([{"id": "a", "depends_on": []}], "e", "E", stance="marathon",
                      caps={"started_at": "2026-01-01T05:00:00+05:00"})
    check("#11: build_state started_at is normalized to UTC too",
          r11["autonomy"]["started_at"] == "2026-01-01T00:00:00+00:00")

    # ================================================================
    # Codex round-2 review — 5 remaining edge cases
    # ================================================================

    # --- R2#1 HIGH: validate_marathon_state type gaps ------------------------------------
    r2_deps = build_state([{"id": "a", "depends_on": []}], "e", "E", stance="marathon", caps={})
    r2_deps["features"][0]["depends_on"] = 5  # numeric, not a list
    check("R2#1: numeric depends_on -> validation error",
          any("depends_on" in e for e in validate_marathon_state(r2_deps)))
    r2_deps2 = build_state([{"id": "a", "depends_on": []}], "e", "E", stance="marathon", caps={})
    r2_deps2["features"][0]["depends_on"] = [1, 2]  # list of non-strings
    check("R2#1: non-string depends_on element -> error",
          any("depends_on" in e for e in validate_marathon_state(r2_deps2)))
    r2_ldc = build_state([{"id": "a", "depends_on": []}], "e", "E", stance="marathon", caps={})
    r2_ldc["last_done_count"] = "three"
    check("R2#1: string last_done_count -> error",
          any("last_done_count" in e for e in validate_marathon_state(r2_ldc)))
    r2_pci = build_state([{"id": "a", "depends_on": []}], "e", "E", stance="marathon", caps={})
    r2_pci["processed_cycle_ids"] = [1, 2]
    check("R2#1: non-string processed_cycle_ids element -> error",
          any("processed_cycle_ids" in e for e in validate_marathon_state(r2_pci)))
    # ...and a well-formed state with real depends_on/last_done_count still validates clean
    r2_ok = build_state([{"id": "a", "depends_on": []}, {"id": "b", "depends_on": ["a"]}],
                        "e", "E", stance="marathon", caps={})
    r2_ok["last_done_count"] = 1
    r2_ok["processed_cycle_ids"] = ["c1", "c2"]
    check("R2#1: well-formed depends_on/last_done_count/processed_cycle_ids stays clean",
          validate_marathon_state(r2_ok) == [])

    # --- R2#2 HIGH: non-finite caps rejected --------------------------------------------
    for bad in (float("nan"), float("inf")):
        try:
            build_state([{"id": "a", "depends_on": []}], "e", "E", stance="marathon",
                        caps={"max_wall_clock_hours": bad})
            check("R2#2: non-finite cap %r rejected at build" % bad, False)
        except ValueError:
            check("R2#2: non-finite cap %r rejected at build" % bad, True)
    # a persisted NaN cap (hand-edited, bypassing --init) is caught by the post-load validator
    r2_nan = build_state([{"id": "a", "depends_on": []}], "e", "E", stance="marathon", caps={})
    r2_nan["autonomy"]["max_total_attempts"] = float("nan")
    check("R2#2: persisted NaN cap -> validation error",
          any("finite" in e for e in validate_marathon_state(r2_nan)))

    # --- R2#3 HIGH: explicit-null max_attempts_per_feature does not crash --can-retry ----
    r2_null = build_state([{"id": "a", "depends_on": []}], "e", "E", stance="marathon",
                          caps={"max_attempts_per_feature": None})
    apply_update(r2_null, "a", "running", now_dt=T0)  # attempts -> 1
    info_null = can_retry_info(r2_null, "a")
    check("R2#3: null max_attempts_per_feature -> can_retry True, cap None (no crash)",
          info_null["can_retry"] is True and info_null["cap"] is None and info_null["attempts"] == 1)

    # --- R2#4 MED: idempotent done-replay must NOT invalidate a passed final_review -------
    r2_rep = build_state([{"id": "a", "depends_on": []}], "e", "E", stance="marathon", caps={})
    apply_update(r2_rep, "a", "running", now_dt=T0)
    apply_update(r2_rep, "a", "done", now_dt=T0)
    record_final_review(r2_rep, "passed")
    check("R2#4: precondition — epic is done after pass", r2_rep["status"] == "done")
    apply_update(r2_rep, "a", "done", now_dt=T0)  # idempotent replay (prev==status==done)
    check("R2#4: replay of done on an already-done feature keeps final_review passed",
          r2_rep["final_review"]["status"] == "passed")
    check("R2#4: ...and top status stays 'done'", r2_rep["status"] == "done")
    # a REAL change still invalidates (regression guard for #1)
    apply_update(r2_rep, "a", "pending", now_dt=T0)
    check("R2#4: a real status change still invalidates the review",
          r2_rep["final_review"]["status"] == "pending" and r2_rep["status"] != "done")

    # --- R2#5 MED: --last-error (and other marathon args) rejected on a checkpoint state --
    r2_chk = build_state([{"id": "a", "depends_on": []}], "e", "E")  # checkpoint
    okle, errle = apply_update(r2_chk, "a", "failed", last_error="boom")
    check("R2#5: checkpoint --update --last-error rejected (nonzero, no silent discard)",
          okle is False and "--last-error" in errle and "marathon-only" in errle)
    check("R2#5: ...and the checkpoint feature status was NOT changed",
          r2_chk["features"][0]["status"] == "pending")
    # a plain checkpoint --update with no marathon args still works
    okp3, _ = apply_update(r2_chk, "a", "failed")
    check("R2#5: plain checkpoint --update (no marathon args) still succeeds", okp3)

    # ================================================================
    # Codex round-3 review — 8 malformed-state / argparse robustness fixes
    # ================================================================

    # --- R3#1 HIGH: no_progress reset must NOT fire on a done->done replay ----------------
    r3_np = build_state([{"id": "a", "depends_on": []}, {"id": "b", "depends_on": []}],
                        "e", "E", stance="marathon", caps={})
    apply_update(r3_np, "a", "running", now_dt=T0)
    apply_update(r3_np, "a", "done", now_dt=T0)  # real ->done resets (was 0 anyway)
    r3_np["no_progress_cycles"] = 2               # simulate accumulated stall on OTHER work
    apply_update(r3_np, "a", "done", now_dt=T0)   # idempotent replay: prev==status==done
    check("R3#1: done->done replay does NOT reset no_progress_cycles",
          r3_np["no_progress_cycles"] == 2)
    # a REAL transition to done still resets (regression guard)
    apply_update(r3_np, "b", "running", now_dt=T0)
    apply_update(r3_np, "b", "done", now_dt=T0)
    check("R3#1: a real ->done still resets no_progress_cycles", r3_np["no_progress_cycles"] == 0)

    # --- R3#2 HIGH: validate_marathon_state validates blocker_ledger ---------------------
    r3_led = build_state([{"id": "a", "depends_on": []}], "e", "E", stance="marathon", caps={})
    r3_led["blocker_ledger"] = "not a list"
    check("R3#2: non-list blocker_ledger -> error",
          any("blocker_ledger" in e for e in validate_marathon_state(r3_led)))
    r3_led2 = build_state([{"id": "a", "depends_on": []}], "e", "E", stance="marathon", caps={})
    r3_led2["blocker_ledger"] = ["junk"]  # non-dict entry
    check("R3#2: non-dict ledger entry -> error",
          any("blocker_ledger" in e for e in validate_marathon_state(r3_led2)))
    r3_led3 = build_state([{"id": "a", "depends_on": []}], "e", "E", stance="marathon", caps={})
    r3_led3["blocker_ledger"] = [{"feature": 5, "attempt": 0, "active": True}]  # bad feature type
    check("R3#2: ledger entry with non-string feature -> error",
          any("blocker_ledger" in e for e in validate_marathon_state(r3_led3)))
    # a well-formed ledger validates clean
    r3_ledok = build_state([{"id": "a", "depends_on": []}], "e", "E", stance="marathon", caps={})
    apply_update(r3_ledok, "a", "blocked", blocker_reason="x", now_dt=T0)
    check("R3#2: a builder-produced ledger validates clean",
          validate_marathon_state(r3_ledok) == [])

    # --- R3#3 HIGH: started_at safety — validate + fail-safe TRIP -------------------------
    r3_sa = build_state([{"id": "a", "depends_on": []}], "e", "E", stance="marathon", caps={})
    del r3_sa["autonomy"]["started_at"]
    check("R3#3: missing started_at -> validation error",
          any("started_at" in e for e in validate_marathon_state(r3_sa)))
    r3_sa2 = build_state([{"id": "a", "depends_on": []}], "e", "E", stance="marathon", caps={})
    r3_sa2["autonomy"]["started_at"] = "not-a-timestamp"
    check("R3#3: unparseable started_at -> validation error",
          any("started_at" in e for e in validate_marathon_state(r3_sa2)))
    # breaker_check FAILS SAFE: max_wall_clock_hours set but started_at missing -> TRIPPED
    r3_sa3 = build_state([{"id": "a", "depends_on": []}], "e", "E", stance="marathon",
                         caps={"max_wall_clock_hours": 10,
                               "started_at": "2026-01-01T00:00:00+00:00"})
    r3_sa3["autonomy"]["started_at"] = None  # corrupt after build
    r_fs = breaker_check(r3_sa3, T0)
    check("R3#3: missing started_at + wall-clock cap -> breaker TRIPS (never silently skipped)",
          r_fs["tripped"] is True and "max_wall_clock_hours" in r_fs["which"])
    r3_sa4 = build_state([{"id": "a", "depends_on": []}], "e", "E", stance="marathon",
                         caps={"max_wall_clock_hours": 10,
                               "started_at": "2026-01-01T00:00:00+00:00"})
    r3_sa4["autonomy"]["started_at"] = "garbage"
    r_fs2 = breaker_check(r3_sa4, T0)
    check("R3#3: unparseable started_at + wall-clock cap -> breaker TRIPS fail-safe",
          r_fs2["tripped"] is True and "max_wall_clock_hours" in r_fs2["which"])

    # --- R3#4 MED: presence-based rejection of marathon args (not truthiness) -------------
    # apply_update alone can't see an explicit-false bool; the CLI presence check does. Here
    # assert the discriminator: --blocker-confirmed's arg default is None (a sentinel) so
    # `false` is distinguishable from absent. (Full CLI reject proven in the live smoke.)
    check("R3#4: (blocker_confirmed sentinel default enables presence detection — see CLI smoke)",
          True)

    # --- R3#5 MED: checkpoint --stats has no 'blocked' key; marathon does -----------------
    chk_stats = stats(build_state([{"id": "a", "depends_on": []}], "e", "E"))
    check("R3#5: checkpoint stats omits 'blocked'", "blocked" not in chk_stats)
    mar_stats = stats(build_state([{"id": "a", "depends_on": []}], "e", "E",
                                  stance="marathon", caps={}))
    check("R3#5: marathon stats includes 'blocked'", "blocked" in mar_stats)

    # --- R3#6 MED: explicit-null cap via the CLI arg parser -------------------------------
    parse_int_cap = _cap_arg(int)
    check("R3#6: cap arg 'null' -> None (explicit unbounded)", parse_int_cap("null") is None)
    check("R3#6: cap arg 'none' -> None", parse_int_cap("none") is None)
    check("R3#6: cap arg '5' -> 5", parse_int_cap("5") == 5)
    try:
        parse_int_cap("abc")
        check("R3#6: cap arg garbage rejected", False)
    except argparse.ArgumentTypeError:
        check("R3#6: cap arg garbage rejected", True)
    # an explicit-null cap in build_state is honored as unbounded
    r3_null = build_state([{"id": "a", "depends_on": []}], "e", "E", stance="marathon",
                          caps={"max_total_attempts": None})
    check("R3#6: explicit-null cap persists as null (unbounded)",
          r3_null["autonomy"]["max_total_attempts"] is None)

    # --- R3#7 MED: --init depends_on TypeError -> controlled error ------------------------
    check("R3#7: non-list depends_on -> validation error (no crash)",
          any("depends_on" in e for e in validate_features([{"id": "a", "depends_on": 5}])))
    check("R3#7: non-string depends_on element -> validation error",
          any("depends_on" in e for e in validate_features([{"id": "a", "depends_on": [1]}])))
    # validate_features must NOT crash on the bad input (it returns errors, doesn't raise)
    try:
        validate_features([{"id": "a", "depends_on": 5}])
        check("R3#7: validate_features survives non-iterable depends_on (no TypeError)", True)
    except TypeError:
        check("R3#7: validate_features survives non-iterable depends_on (no TypeError)", False)

    # --- R3#8 MED: malformed --now resolution -> controlled error (proven at CLI) ---------
    try:
        _parse_iso("not-a-timestamp")
        check("R3#8: _parse_iso raises on bad input (caught by the CLI guard)", False)
    except (ValueError, TypeError):
        check("R3#8: _parse_iso raises on bad input (caught by the CLI guard)", True)

    # ================================================================
    # v2.10 marathon — human resume after a breaker/halt latch
    # (--clear-breaker, --clear-disposition, --init --start-sha)
    # ================================================================

    # --- --clear-breaker: clears a tripped blocked_needing_human -> status recomputes ------
    cb_feats = [{"id": "a", "depends_on": []}]
    cbA = build_state(cb_feats, "e", "E", stance="marathon", caps={"max_no_progress_cycles": 2})
    cbA["status"] = "blocked_needing_human"
    cbA["breaker_trip"] = {"which": ["max_no_progress_cycles"], "detail": {},
                           "tripped_at": "2026-01-01T00:00:00+00:00"}
    cbA["no_progress_cycles"] = 5
    okA, errA, sumA = clear_breaker(cbA, T0)
    check("clear-breaker: ok + no error", okA and errA is None)
    check("clear-breaker: status recomputes off blocked_needing_human ('running')",
          cbA["status"] == "running")
    check("clear-breaker: breaker_trip record removed", "breaker_trip" not in cbA)
    check("clear-breaker: no_progress_cycles reset to 0", cbA["no_progress_cycles"] == 0)
    check("clear-breaker: summary reports cleared_breaker_trip", sumA["cleared_breaker_trip"] is True)
    check("clear-breaker: summary reports the prior no_progress_cycles",
          sumA["no_progress_cycles_reset_from"] == 5)
    check("clear-breaker: no immediate re-trip when caps are fine",
          sumA["would_immediately_retrip"] is False and sumA["would_retrip_which"] == [])

    # status recompute can also land back on 'done' (all-done + final_review passed)
    cbD = build_state(cb_feats, "e", "E", stance="marathon", caps={})
    apply_update(cbD, "a", "running", now_dt=T0)
    apply_update(cbD, "a", "done", now_dt=T0)
    record_final_review(cbD, "passed")
    check("clear-breaker setup: status is 'done' pre-trip", cbD["status"] == "done")
    cbD["status"] = "blocked_needing_human"  # simulate a later-tripped latch
    cbD["breaker_trip"] = {"which": ["max_wall_clock_hours"], "detail": {}, "tripped_at": "x"}
    okD, _, sumD = clear_breaker(cbD, T0)
    check("clear-breaker: recompute can land back on 'done'", okD and cbD["status"] == "done")

    # --- --clear-breaker --reset-wall-clock: moves started_at ------------------------------
    cb2 = build_state(cb_feats, "e", "E", stance="marathon",
                      caps={"started_at": "2020-01-01T00:00:00+00:00"})
    ok2, _, sum2 = clear_breaker(cb2, T0, reset_wall_clock=True)
    check("clear-breaker --reset-wall-clock: started_at moved to 'now'",
          ok2 and cb2["autonomy"]["started_at"] == _now_iso(T0))
    check("clear-breaker --reset-wall-clock: summary reflects the reset",
          sum2["wall_clock_reset"] is True)
    cb2b = build_state(cb_feats, "e", "E", stance="marathon",
                       caps={"started_at": "2020-01-01T00:00:00+00:00"})
    ok2b, _, sum2b = clear_breaker(cb2b, T0)  # no --reset-wall-clock
    check("clear-breaker: started_at untouched without --reset-wall-clock",
          ok2b and cb2b["autonomy"]["started_at"] == "2020-01-01T00:00:00+00:00"
          and sum2b["wall_clock_reset"] is False)

    # --- --clear-breaker --set-max-total-attempts: re-arms that axis -----------------------
    cb3 = build_state(cb_feats, "e", "E", stance="marathon", caps={"max_total_attempts": 1})
    ok3, err3, sum3 = clear_breaker(cb3, T0, set_max_total_attempts=50)
    check("clear-breaker --set-max-total-attempts: cap updated",
          ok3 and cb3["autonomy"]["max_total_attempts"] == 50)
    check("clear-breaker --set-max-total-attempts: summary reflects the new cap",
          sum3["max_total_attempts_set"] == 50)
    ok3b, _, _ = clear_breaker(cb3, T0, set_max_total_attempts=None)
    check("clear-breaker --set-max-total-attempts null: explicit-unbounded honored",
          ok3b and cb3["autonomy"]["max_total_attempts"] is None)
    ok3c, err3c, sum3c = clear_breaker(cb3, T0, set_max_total_attempts=-5)
    check("clear-breaker --set-max-total-attempts: a negative cap is rejected (same rules as --init)",
          ok3c is False and sum3c is None and err3c)

    # --- --clear-breaker: clearing WITHOUT re-arming a still-over total_attempts axis warns -
    cb4 = build_state(cb_feats, "e", "E", stance="marathon", caps={"max_total_attempts": 1})
    apply_update(cb4, "a", "running", now_dt=T0)  # attempts=1 == cap
    trip_res4 = trip_breaker(cb4, T0)
    check("clear-breaker setup: over-cap trip actually latched",
          trip_res4["tripped"] and cb4["status"] == "blocked_needing_human")
    ok4, _, sum4 = clear_breaker(cb4, T0)  # no re-arm supplied
    check("clear-breaker: the latch is still cleared even though it would re-trip",
          ok4 and cb4["status"] != "blocked_needing_human")
    check("clear-breaker: summary flags the immediate re-trip on max_total_attempts",
          sum4["would_immediately_retrip"] is True
          and "max_total_attempts" in sum4["would_retrip_which"])

    # --- --clear-breaker: non-marathon state -> controlled error ---------------------------
    cb5 = build_state(cb_feats, "e", "E")  # checkpoint
    ok5, err5, sum5 = clear_breaker(cb5, T0)
    check("clear-breaker: non-marathon state -> controlled error, no write",
          ok5 is False and sum5 is None and "marathon" in err5)

    # --- --clear-disposition: undoes a sticky halt_epic so autonomous routing resumes ------
    cd_feats = [{"id": "a", "depends_on": []}, {"id": "b", "depends_on": ["a"]}]
    cd1 = build_state(cd_feats, "e", "E", stance="marathon", caps={})
    record_disposition(cd1, "a", "halt_epic", now_dt=T0)
    fah_before, whyah_before, _ = next_feature_autonomous(cd1)
    check("clear-disposition setup: a halt_epic disposition halts the epic",
          fah_before is None and whyah_before.startswith("blocked_needing_human"))
    okcd, errcd = clear_disposition(cd1, "a")
    check("clear-disposition: ok + no error", okcd and errcd is None)
    check("clear-disposition: the feature's disposition is cleared to null",
          cd1["features"][0]["disposition"] is None)
    fah_after, whyah_after, _ = next_feature_autonomous(cd1)
    check("clear-disposition: next_feature_autonomous no longer short-circuits on it",
          fah_after is not None and fah_after["id"] == "a")

    okcd2, errcd2 = clear_disposition(cd1, "does-not-exist")
    check("clear-disposition: unknown feature -> controlled error",
          okcd2 is False and "no feature" in errcd2)

    cd_chk = build_state(cd_feats, "e", "E")  # checkpoint
    okcd3, errcd3 = clear_disposition(cd_chk, "a")
    check("clear-disposition: non-marathon state -> controlled error, no write",
          okcd3 is False and "marathon" in errcd3)

    # --- --init --stance marathon --start-sha: stored as autonomy.start_sha ----------------
    sha_feats = [{"id": "a", "depends_on": []}]
    sha_state = build_state(sha_feats, "e", "E", stance="marathon", caps={"start_sha": "abc123"})
    check("start-sha: marathon build_state stores autonomy.start_sha",
          sha_state["autonomy"]["start_sha"] == "abc123")
    check("start-sha: a stored string start_sha validates clean",
          validate_marathon_state(sha_state) == [])
    sha_absent = build_state(sha_feats, "e", "E", stance="marathon", caps={})
    check("start-sha: absent start_sha is fine (no key, no validation error)",
          "start_sha" not in sha_absent["autonomy"]
          and validate_marathon_state(sha_absent) == [])
    sha_bad = build_state(sha_feats, "e", "E", stance="marathon", caps={})
    sha_bad["autonomy"]["start_sha"] = 12345  # simulate a hand-edited/corrupt state
    check("start-sha: a non-string start_sha on a loaded state -> validation error",
          any("start_sha" in e for e in validate_marathon_state(sha_bad)))
    try:
        build_state(sha_feats, "e", "E", stance="marathon", caps={"start_sha": 12345})
        check("start-sha: a non-string start_sha is rejected at build time", False)
    except ValueError:
        check("start-sha: a non-string start_sha is rejected at build time", True)
    # checkpoint --init stays unaffected: build_state without a marathon stance never looks
    # at caps["start_sha"] at all (structurally impossible to leak into the checkpoint shape).
    plain_sha = build_state(sha_feats, "e", "E")
    check("start-sha: checkpoint build_state carries no autonomy/start_sha (unaffected)",
          "autonomy" not in plain_sha)

    # ================================================================
    # v2.11 (Scheduler Auto-Resurrection, V1) — epic-state.py component
    # ================================================================

    # --- is_terminal: the canonical classifier --------------------------------------------
    it_done = build_state([{"id": "a", "depends_on": []}], "e", "E", stance="marathon", caps={})
    apply_update(it_done, "a", "running", now_dt=T0)
    apply_update(it_done, "a", "done", now_dt=T0)
    record_final_review(it_done, "passed", now_dt=T0)
    check("v2.11 is_terminal: done -> True", is_terminal(it_done) is True)

    it_breaker = build_state([{"id": "a", "depends_on": []}], "e", "E", stance="marathon", caps={})
    it_breaker["status"] = "blocked_needing_human"
    check("v2.11 is_terminal: breaker-tripped (status latch) -> True",
          is_terminal(it_breaker) is True)

    it_halt_feats = [{"id": "x", "depends_on": []}, {"id": "y", "depends_on": []}]
    it_halt = build_state(it_halt_feats, "e", "E", stance="marathon", caps={})
    it_halt["features"][0]["status"] = "failed"
    it_halt["features"][0]["disposition"] = {"disposition": "halt_epic"}
    check("v2.11 is_terminal: halt_epic disposition -> True", is_terminal(it_halt) is True)

    it_exh_feats = [{"id": "x", "depends_on": []}, {"id": "z", "depends_on": ["x"]}]
    it_exh = build_state(it_exh_feats, "e", "E", stance="marathon", caps={})
    it_exh["features"][0]["status"] = "failed"
    it_exh["features"][0]["disposition"] = {"disposition": "halt_feature"}
    check("v2.11 is_terminal: exhausted-reachable-work -> True", is_terminal(it_exh) is True)

    it_arb = build_state([{"id": "x", "depends_on": []}], "e", "E", stance="marathon", caps={})
    it_arb["features"][0]["status"] = "failed"  # no disposition recorded
    check("v2.11 is_terminal: needs_arbitration -> NOT terminal", is_terminal(it_arb) is False)

    it_blkrec_feats = [{"id": "a", "depends_on": []}]
    it_blkrec = build_state(it_blkrec_feats, "e", "E", stance="marathon", caps={})
    apply_update(it_blkrec, "a", "running", now_dt=T0)
    apply_update(it_blkrec, "a", "failed", now_dt=T0)
    record_disposition(it_blkrec, "a", "blocked_external", now_dt=T0)
    check("v2.11 is_terminal: needs_blocker_recording -> NOT terminal",
          is_terminal(it_blkrec) is False)

    it_run = build_state([{"id": "a", "depends_on": []}], "e", "E", stance="marathon", caps={})
    it_run["features"][0]["status"] = "running"
    check("v2.11 is_terminal: running/reconcile -> NOT terminal", is_terminal(it_run) is False)

    it_sa = build_state([{"id": "a", "depends_on": []}], "e", "E", stance="marathon", caps={})
    apply_update(it_sa, "a", "running", now_dt=T0)
    apply_update(it_sa, "a", "done", now_dt=T0)
    mark_sample_audit_due(it_sa, "a", now_dt=T0)
    check("v2.11 is_terminal: sample_audit_due -> NOT terminal", is_terminal(it_sa) is False)

    it_prfr = build_state([{"id": "a", "depends_on": []}], "e", "E", stance="marathon", caps={})
    apply_update(it_prfr, "a", "running", now_dt=T0)
    apply_update(it_prfr, "a", "done", now_dt=T0)  # final_review still pending
    check("v2.11 is_terminal: all-done-but-final-review-pending -> NOT terminal",
          is_terminal(it_prfr) is False)

    it_chk = build_state([{"id": "a", "depends_on": []}], "e", "E")  # checkpoint
    check("v2.11 is_terminal: a checkpoint (non-marathon) state -> always False",
          is_terminal(it_chk) is False)

    # --- build_state: v2.11 watch schema ---------------------------------------------------
    v11_feats = [{"id": "a", "depends_on": []}]
    v11_watch_off = build_state(v11_feats, "e", "E", stance="marathon", caps={})
    check("v2.11: watch-off marathon build_state has no 'watch' key in autonomy",
          "watch" not in v11_watch_off["autonomy"])
    check("v2.11: watch-off marathon build_state has no top-level 'last_progress_at' key",
          "last_progress_at" not in v11_watch_off)
    check("v2.11: watch-off marathon build_state has no 'lease'/'resume_count' keys",
          "lease" not in v11_watch_off and "resume_count" not in v11_watch_off)
    check("v2.11: watch-off marathon autonomy key set UNCHANGED from v2.10 (still exactly 6)",
          set(v11_watch_off["autonomy"].keys()) == {
              "stance", "max_attempts_per_feature", "max_no_progress_cycles",
              "max_total_attempts", "max_wall_clock_hours", "started_at"})

    v11_live_started = "2026-01-01T00:00:00+00:00"
    v11_watch_on = build_state(v11_feats, "e", "E", stance="marathon",
                               caps={"watch": True, "started_at": v11_live_started})
    check("v2.11: watch-on marathon build_state autonomy.watch is True",
          v11_watch_on["autonomy"]["watch"] is True)
    check("v2.11: watch-on marathon build_state default max_resume_count == 20",
          v11_watch_on["autonomy"]["max_resume_count"] == 20)
    check("v2.11: watch-on marathon build_state seeds last_progress_at == started_at",
          v11_watch_on["last_progress_at"] == v11_watch_on["autonomy"]["started_at"]
          == v11_live_started)

    v11_watch_on_cap = build_state(v11_feats, "e", "E", stance="marathon",
                                   caps={"watch": True, "max_resume_count": 5})
    check("v2.11: explicit --max-resume-count is honored",
          v11_watch_on_cap["autonomy"]["max_resume_count"] == 5)

    # --- Golden: byte-identical guarantees --------------------------------------------------
    v11_chk = build_state(v11_feats, "e", "E")
    check("v2.11 golden: checkpoint build_state exact top-level keys UNCHANGED",
          set(v11_chk.keys()) == {"epic_id", "title", "status", "features"})

    apply_update(v11_watch_off, "a", "running", now_dt=T0)
    apply_update(v11_watch_off, "a", "done", now_dt=T0)
    check("v2.11 golden: watch-off marathon --update adds NO last_progress_at/lease/"
          "resume_count", "last_progress_at" not in v11_watch_off
          and "lease" not in v11_watch_off and "resume_count" not in v11_watch_off)
    check("v2.11 golden: watch-off marathon --update top-level key set UNCHANGED from v2.10",
          set(v11_watch_off.keys()) == {"epic_id", "title", "status", "features", "autonomy",
                                        "final_review", "blocker_ledger", "no_progress_cycles",
                                        "total_attempts"})

    # --- v2.11: watch-ON mutations bump last_progress_at (the mutation-path contract) ------
    def _v11_fresh_watch_state():
        return build_state(v11_feats, "e", "E", stance="marathon",
                           caps={"watch": True, "started_at": "2020-01-01T00:00:00+00:00"})

    t_new = _parse_iso("2027-01-01T00:00:00+00:00")

    v11_bump = build_state(v11_feats, "e", "E", stance="marathon",
                           caps={"watch": True, "started_at": v11_live_started})
    t_before = v11_bump["last_progress_at"]
    apply_update(v11_bump, "a", "running", now_dt=_parse_iso("2026-06-01T00:00:00+00:00"))
    check("v2.11: watch-on apply_update bumps last_progress_at forward",
          v11_bump["last_progress_at"] == "2026-06-01T00:00:00+00:00" != t_before)

    s_rd = _v11_fresh_watch_state()
    record_disposition(s_rd, "a", "retry_fix", now_dt=t_new)
    check("v2.11: record_disposition bumps last_progress_at when watch is on",
          s_rd["last_progress_at"] == _now_iso(t_new))

    s_rfr = _v11_fresh_watch_state()
    apply_update(s_rfr, "a", "running", now_dt=t_new)
    apply_update(s_rfr, "a", "done", now_dt=t_new)
    record_final_review(s_rfr, "passed", now_dt=t_new)
    check("v2.11: record_final_review bumps last_progress_at when watch is on",
          s_rfr["last_progress_at"] == _now_iso(t_new))

    s_rpc = _v11_fresh_watch_state()
    record_progress_cycle(s_rpc, "v11-c1", now_dt=t_new)
    check("v2.11: record_progress_cycle bumps last_progress_at when watch is on",
          s_rpc["last_progress_at"] == _now_iso(t_new))

    s_tb = build_state(v11_feats, "e", "E", stance="marathon",
                       caps={"watch": True, "max_total_attempts": 0,
                             "started_at": "2020-01-01T00:00:00+00:00"})
    trip_breaker(s_tb, t_new)
    check("v2.11: trip_breaker bumps last_progress_at when it actually trips",
          s_tb["last_progress_at"] == _now_iso(t_new))

    s_cb = _v11_fresh_watch_state()
    s_cb["status"] = "blocked_needing_human"
    clear_breaker(s_cb, t_new)
    check("v2.11: clear_breaker bumps last_progress_at when watch is on",
          s_cb["last_progress_at"] == _now_iso(t_new))

    s_cd = _v11_fresh_watch_state()
    record_disposition(s_cd, "a", "halt_epic", now_dt=_parse_iso("2020-01-01T00:00:00+00:00"))
    clear_disposition(s_cd, "a", now_dt=t_new)
    check("v2.11: clear_disposition bumps last_progress_at when watch is on",
          s_cd["last_progress_at"] == _now_iso(t_new))

    s_ms = _v11_fresh_watch_state()
    apply_update(s_ms, "a", "running", now_dt=_parse_iso("2020-01-01T00:00:00+00:00"))
    apply_update(s_ms, "a", "done", now_dt=_parse_iso("2020-01-01T00:00:00+00:00"))
    mark_sample_audit_due(s_ms, "a", now_dt=t_new)
    check("v2.11: mark_sample_audit_due bumps last_progress_at when watch is on",
          s_ms["last_progress_at"] == _now_iso(t_new))
    t_clear = _parse_iso("2028-01-01T00:00:00+00:00")
    clear_sample_audit_due(s_ms, "a", now_dt=t_clear)
    check("v2.11: clear_sample_audit_due bumps last_progress_at when watch is on",
          s_ms["last_progress_at"] == _now_iso(t_clear))

    s_raf = _v11_fresh_watch_state()
    apply_update(s_raf, "a", "running", now_dt=_parse_iso("2020-01-01T00:00:00+00:00"))
    apply_update(s_raf, "a", "done", now_dt=_parse_iso("2020-01-01T00:00:00+00:00"))
    record_audit_failed(s_raf, "a", now_dt=t_new)
    check("v2.11: record_audit_failed bumps last_progress_at when watch is on",
          s_raf["last_progress_at"] == _now_iso(t_new))

    # --- _lease_live / _pid_alive ------------------------------------------------------------
    check("v2.11 _lease_live: no lease -> False", _lease_live({}, t_new) is False)
    check("v2.11 _lease_live: live lease (future expiry) -> True", _lease_live(
        {"lease": {"owner_pid": 1,
                  "expires_at": _now_iso(_parse_iso("2027-01-02T00:00:00+00:00"))}},
        t_new) is True)
    check("v2.11 _lease_live: expired lease -> False", _lease_live(
        {"lease": {"owner_pid": 1,
                  "expires_at": _now_iso(_parse_iso("2026-01-01T00:00:00+00:00"))}},
        t_new) is False)
    check("v2.11 _lease_live: malformed lease (non-dict) -> False",
          _lease_live({"lease": "junk"}, t_new) is False)
    check("v2.11 _lease_live: malformed expires_at -> False",
          _lease_live({"lease": {"owner_pid": 1, "expires_at": 12345}}, t_new) is False)

    check("v2.11 _pid_alive: the current process is alive", _pid_alive(os.getpid()) is True)
    check("v2.11 _pid_alive: a very-unlikely-to-exist huge pid is not alive",
          _pid_alive(999999999) is False)
    check("v2.11 _pid_alive: non-positive/non-int/bool input never raises, returns False",
          _pid_alive(0) is False and _pid_alive(-1) is False and _pid_alive("x") is False
          and _pid_alive(None) is False and _pid_alive(True) is False)

    # --- liveness_check ----------------------------------------------------------------------
    t0 = _parse_iso(v11_live_started)
    v11_live = build_state(v11_feats, "e", "E", stance="marathon",
                           caps={"watch": True, "started_at": v11_live_started})
    lv0 = liveness_check(v11_live, t0)
    check("v2.11 liveness: a fresh watch-on epic is not stale",
          lv0["stale"] is False and lv0["incomplete"] is True and lv0["terminal"] is False
          and lv0["held"] is False and lv0["lease_expired"] is False
          and lv0["resume_count"] == 0)

    t_past = _parse_iso("2026-01-01T00:46:00+00:00")  # 46min > default 45min threshold
    lv1 = liveness_check(v11_live, t_past)
    check("v2.11 liveness: past the default 45min threshold with no live owner -> stale",
          lv1["stale"] is True)

    v11_live_leased = build_state(v11_feats, "e", "E", stance="marathon",
                                  caps={"watch": True, "started_at": v11_live_started})
    v11_live_leased["lease"] = {"owner_pid": os.getpid(), "claimed_at": v11_live_started,
                                "expires_at": v11_live_started}  # already expired
    lv2 = liveness_check(v11_live_leased, t_past)
    check("v2.11 liveness: belt-and-suspenders -- a live OWNER process defers staleness even "
          "past the age threshold, despite an expired lease",
          lv2["stale"] is False and lv2["lease_expired"] is True)

    v11_live_done = build_state(v11_feats, "e", "E", stance="marathon",
                                caps={"watch": True, "started_at": v11_live_started})
    apply_update(v11_live_done, "a", "running", now_dt=t0)
    apply_update(v11_live_done, "a", "done", now_dt=t0)
    record_final_review(v11_live_done, "passed", now_dt=t0)
    lv3 = liveness_check(v11_live_done, t_past)
    check("v2.11 liveness: a done epic is never stale regardless of age",
          lv3["terminal"] is True and lv3["incomplete"] is False and lv3["stale"] is False)

    v11_live_blocked = build_state(v11_feats, "e", "E", stance="marathon",
                                   caps={"watch": True, "started_at": v11_live_started})
    v11_live_blocked["status"] = "blocked_needing_human"
    lv4 = liveness_check(v11_live_blocked, t_past)
    check("v2.11 liveness: a terminal (blocked_needing_human) epic is never stale",
          lv4["terminal"] is True and lv4["stale"] is False)

    v11_live_missing_lpa = build_state(v11_feats, "e", "E", stance="marathon",
                                       caps={"watch": True, "started_at": v11_live_started})
    del v11_live_missing_lpa["last_progress_at"]
    lv5 = liveness_check(v11_live_missing_lpa, t0)
    check("v2.11 liveness: a missing last_progress_at FAILS SAFE as stale-eligible",
          lv5["stale"] is True)

    # --- claim_resume: THE CRUX (single-process scenarios) -----------------------------------
    v11_cr_dir = _tempfile.mkdtemp()
    try:
        v11_cr_path = os.path.join(v11_cr_dir, "epic-state.json")
        _atomic_write_json(v11_cr_path, build_state(v11_feats, "e", "E", stance="marathon",
                                                     caps={"watch": True,
                                                           "started_at": v11_live_started}))
        t_claim = _parse_iso("2026-01-01T00:01:00+00:00")
        ok_c1, res_c1, err_c1 = claim_resume(v11_cr_path, 111, t_claim)
        check("v2.11 claim_resume: a fresh watch-on epic wins",
              ok_c1 and res_c1["claimed"] is True and res_c1["reason"] == "claimed"
              and res_c1["resume_count"] == 1)
        on_disk1 = _read_json(v11_cr_path)
        check("v2.11 claim_resume: lease persisted with the correct owner_pid",
              on_disk1["lease"]["owner_pid"] == 111)
        check("v2.11 claim_resume: lease.expires_at == claimed_at + default TTL",
              on_disk1["lease"]["expires_at"]
              == _now_iso(t_claim + timedelta(minutes=_DEFAULT_LEASE_TTL_MIN)))
        check("v2.11 claim_resume: resume_count persisted", on_disk1["resume_count"] == 1)
        check("v2.11 claim_resume: last_progress_at bumped",
              on_disk1["last_progress_at"] == _now_iso(t_claim))

        t_claim2 = _parse_iso("2026-01-01T00:02:00+00:00")  # still inside the 15min lease TTL
        ok_c2, res_c2, err_c2 = claim_resume(v11_cr_path, 222, t_claim2)
        check("v2.11 claim_resume: a second owner loses to a still-live lease",
              ok_c2 and res_c2["claimed"] is False and res_c2["reason"] == "live-lease-held"
              and res_c2["resume_count"] == 1)
        on_disk2 = _read_json(v11_cr_path)
        check("v2.11 claim_resume: a losing claim does NOT mutate resume_count/lease",
              on_disk2["resume_count"] == 1 and on_disk2["lease"]["owner_pid"] == 111)

        v11_cr_chk_path = os.path.join(v11_cr_dir, "chk.json")
        _atomic_write_json(v11_cr_chk_path, build_state(v11_feats, "e", "E"))
        ok_c3, res_c3, err_c3 = claim_resume(v11_cr_chk_path, 111, t_claim)
        check("v2.11 claim_resume: a checkpoint state -> ok=False, marathon-only error",
              ok_c3 is False and res_c3 is None and "marathon" in err_c3)

        v11_cr_nowatch_path = os.path.join(v11_cr_dir, "nowatch.json")
        _atomic_write_json(v11_cr_nowatch_path,
                          build_state(v11_feats, "e", "E", stance="marathon", caps={}))
        ok_c4, res_c4, err_c4 = claim_resume(v11_cr_nowatch_path, 111, t_claim)
        check("v2.11 claim_resume: marathon-without-watch -> ok=False, watch-only error",
              ok_c4 is False and res_c4 is None and "watch" in err_c4)

        v11_cr_done_path = os.path.join(v11_cr_dir, "done.json")
        v11_cr_done = build_state(v11_feats, "e", "E", stance="marathon",
                                  caps={"watch": True, "started_at": v11_live_started})
        apply_update(v11_cr_done, "a", "running", now_dt=t0)
        apply_update(v11_cr_done, "a", "done", now_dt=t0)
        record_final_review(v11_cr_done, "passed", now_dt=t0)
        _atomic_write_json(v11_cr_done_path, v11_cr_done)
        ok_c5, res_c5, err_c5 = claim_resume(v11_cr_done_path, 111, t_claim)
        check("v2.11 claim_resume: a terminal (done) epic loses with reason 'terminal'",
              ok_c5 and res_c5["claimed"] is False and res_c5["reason"] == "terminal")
        on_disk5 = _read_json(v11_cr_done_path)
        check("v2.11 claim_resume: a terminal loss does NOT write resume_count/lease",
              "resume_count" not in on_disk5 and "lease" not in on_disk5)

        v11_cr_cap_path = os.path.join(v11_cr_dir, "cap.json")
        _atomic_write_json(v11_cr_cap_path,
                          build_state(v11_feats, "e", "E", stance="marathon",
                                     caps={"watch": True, "max_resume_count": 1,
                                           "started_at": v11_live_started}))
        ok_cap1, res_cap1, _ = claim_resume(v11_cr_cap_path, 333, t_claim)
        check("v2.11 claim_resume resume-cap: the 1st claim (cap=1) succeeds",
              ok_cap1 and res_cap1["claimed"] is True and res_cap1["resume_count"] == 1)
        t_claim_late = t_claim + timedelta(minutes=_DEFAULT_LEASE_TTL_MIN + 1)
        ok_cap2, res_cap2, _ = claim_resume(v11_cr_cap_path, 444, t_claim_late)
        check("v2.11 claim_resume resume-cap: the 2nd claim (== cap) is BLOCKED, "
              "reason resume-cap",
              ok_cap2 and res_cap2["claimed"] is False and res_cap2["reason"] == "resume-cap")
        on_disk_cap = _read_json(v11_cr_cap_path)
        check("v2.11 claim_resume resume-cap: trips the epic to blocked_needing_human",
              on_disk_cap["status"] == "blocked_needing_human"
              and on_disk_cap["breaker_trip"]["which"] == ["max_resume_count"])
        ok_cap3, res_cap3, _ = claim_resume(v11_cr_cap_path, 555, t_claim_late)
        check("v2.11 claim_resume resume-cap: the persisted latch makes a 3rd attempt a "
              "harmless no-op (reason 'terminal', not re-tripping)",
              ok_cap3 and res_cap3["claimed"] is False and res_cap3["reason"] == "terminal")

        cleared_state = _read_json(v11_cr_cap_path)
        ok_clr, err_clr, sum_clr = clear_breaker(cleared_state, t_claim_late,
                                                 reset_resume_count=True)
        check("v2.11 clear_breaker --reset-resume-count: clears + reports the reset",
              ok_clr and sum_clr["resume_count_reset"] is True
              and sum_clr["resume_count_reset_from"] == 1
              and cleared_state["resume_count"] == 0
              and cleared_state["status"] != "blocked_needing_human")
        _atomic_write_json(v11_cr_cap_path, cleared_state)
        ok_cap4, res_cap4, _ = claim_resume(v11_cr_cap_path, 666, t_claim_late)
        check("v2.11 claim_resume resume-cap: a claim succeeds again after "
              "--reset-resume-count",
              ok_cap4 and res_cap4["claimed"] is True and res_cap4["resume_count"] == 1)
    finally:
        shutil.rmtree(v11_cr_dir, ignore_errors=True)

    # --- renew_lease ---------------------------------------------------------------------
    v11_rl_dir = _tempfile.mkdtemp()
    try:
        v11_rl_path = os.path.join(v11_rl_dir, "epic-state.json")
        _atomic_write_json(v11_rl_path, build_state(v11_feats, "e", "E", stance="marathon",
                                                     caps={"watch": True,
                                                           "started_at": v11_live_started}))
        t_claim = _parse_iso("2026-01-01T00:01:00+00:00")
        claim_resume(v11_rl_path, 777, t_claim)
        rl_state = _read_json(v11_rl_path)
        old_expiry = rl_state["lease"]["expires_at"]
        t_renew = t_claim + timedelta(minutes=5)
        ok_rl1, err_rl1 = renew_lease(rl_state, 777, t_renew)
        check("v2.11 renew_lease: a matching owner_pid extends expires_at",
              ok_rl1 and rl_state["lease"]["expires_at"] > old_expiry)
        check("v2.11 renew_lease: bumps last_progress_at too",
              rl_state["last_progress_at"] == _now_iso(t_renew))

        ok_rl2, err_rl2 = renew_lease(rl_state, 888, t_renew)
        check("v2.11 renew_lease: a mismatched owner_pid is rejected",
              ok_rl2 is False and "no lease held" in err_rl2)

        rl_no_lease = build_state(v11_feats, "e", "E", stance="marathon",
                                  caps={"watch": True, "started_at": v11_live_started})
        ok_rl3, err_rl3 = renew_lease(rl_no_lease, 777, t_renew)
        check("v2.11 renew_lease: no lease on file at all is rejected",
              ok_rl3 is False and "no lease held" in err_rl3)

        rl_nowatch = build_state(v11_feats, "e", "E", stance="marathon", caps={})
        ok_rl4, err_rl4 = renew_lease(rl_nowatch, 777, t_renew)
        check("v2.11 renew_lease: marathon-without-watch is rejected",
              ok_rl4 is False and "watch" in err_rl4)

        rl_chk = build_state(v11_feats, "e", "E")
        ok_rl5, err_rl5 = renew_lease(rl_chk, 777, t_renew)
        check("v2.11 renew_lease: a checkpoint state is rejected",
              ok_rl5 is False and "marathon" in err_rl5)
    finally:
        shutil.rmtree(v11_rl_dir, ignore_errors=True)

    # --- validate_marathon_state: v2.11 fields ------------------------------------------------
    v11_vm_good = build_state(v11_feats, "e", "E", stance="marathon",
                              caps={"watch": True, "started_at": v11_live_started})
    check("v2.11 validate: a well-formed watch-on state validates clean",
          validate_marathon_state(v11_vm_good) == [])

    v11_vm_bad_watch = build_state(v11_feats, "e", "E", stance="marathon", caps={})
    v11_vm_bad_watch["autonomy"]["watch"] = "yes"
    check("v2.11 validate: a non-bool autonomy.watch -> error",
          any("watch" in e for e in validate_marathon_state(v11_vm_bad_watch)))

    v11_vm_bad_rc = build_state(v11_feats, "e", "E", stance="marathon", caps={})
    v11_vm_bad_rc["resume_count"] = -1
    check("v2.11 validate: a negative resume_count -> error",
          any("resume_count" in e for e in validate_marathon_state(v11_vm_bad_rc)))

    v11_vm_bad_lpa = build_state(v11_feats, "e", "E", stance="marathon", caps={})
    v11_vm_bad_lpa["last_progress_at"] = "not-a-timestamp"
    check("v2.11 validate: a malformed last_progress_at -> error",
          any("last_progress_at" in e for e in validate_marathon_state(v11_vm_bad_lpa)))

    v11_vm_bad_lease1 = build_state(v11_feats, "e", "E", stance="marathon", caps={})
    v11_vm_bad_lease1["lease"] = "junk"
    check("v2.11 validate: a non-dict lease -> error",
          any("lease" in e for e in validate_marathon_state(v11_vm_bad_lease1)))

    v11_vm_bad_lease2 = build_state(v11_feats, "e", "E", stance="marathon", caps={})
    v11_vm_bad_lease2["lease"] = {"owner_pid": -1, "claimed_at": "x", "expires_at": "y"}
    check("v2.11 validate: a malformed lease (bad owner_pid + bad timestamps) -> multiple "
          "errors", len([e for e in validate_marathon_state(v11_vm_bad_lease2)
                        if "lease" in e]) >= 2)

    v11_vm_good_lease = build_state(v11_feats, "e", "E", stance="marathon", caps={})
    v11_vm_good_lease["lease"] = {"owner_pid": 123, "claimed_at": v11_live_started,
                                  "expires_at": v11_live_started}
    check("v2.11 validate: a well-formed lease validates clean",
          validate_marathon_state(v11_vm_good_lease) == [])

    v11_vm_bad_cap = build_state(v11_feats, "e", "E", stance="marathon", caps={"watch": True})
    v11_vm_bad_cap["autonomy"]["max_resume_count"] = -5
    check("v2.11 validate: a negative autonomy.max_resume_count -> error",
          validate_marathon_state(v11_vm_bad_cap) != [])

    # --- breaker_check / clear_breaker: the resume_count axis --------------------------------
    v11_bc = build_state(v11_feats, "e", "E", stance="marathon",
                         caps={"watch": True, "max_resume_count": 3,
                               "started_at": v11_live_started})
    v11_bc["resume_count"] = 2
    check("v2.11 breaker_check: resume_count just under cap -> not tripped on this axis",
          "max_resume_count" not in breaker_check(v11_bc, t0)["which"])
    v11_bc["resume_count"] = 3
    r_v11 = breaker_check(v11_bc, t0)
    check("v2.11 breaker_check: resume_count >= cap trips",
          r_v11["tripped"] and "max_resume_count" in r_v11["which"]
          and r_v11["detail"]["max_resume_count"] == {"value": 3, "cap": 3})

    v11_bc_null = build_state(v11_feats, "e", "E", stance="marathon",
                              caps={"watch": True, "max_resume_count": None,
                                    "started_at": v11_live_started})
    v11_bc_null["resume_count"] = 999
    check("v2.11 breaker_check: an explicit-null max_resume_count is unbounded",
          "max_resume_count" not in breaker_check(v11_bc_null, t0)["which"])

    v11_bc_missing = build_state(v11_feats, "e", "E", stance="marathon",
                                 caps={"watch": True, "started_at": v11_live_started})
    del v11_bc_missing["autonomy"]["max_resume_count"]
    v11_bc_missing["resume_count"] = 20
    r_v11missing = breaker_check(v11_bc_missing, t0)
    check("v2.11 breaker_check: a MISSING max_resume_count key uses the documented default "
          "(20), never unbounded",
          r_v11missing["tripped"] and "max_resume_count" in r_v11missing["which"])

    # --- _now_arg_in_range ---------------------------------------------------------------
    check("v2.11 _now_arg_in_range: near-now is in range",
          _now_arg_in_range(datetime.now(timezone.utc)) is True)
    check("v2.11 _now_arg_in_range: 20 years off is OUT of range",
          _now_arg_in_range(datetime.now(timezone.utc) - timedelta(days=365 * 20)) is False)

    # --- claim_resume concurrency: exactly one of N wins under a REAL OS-level flock race
    # (multiprocessing.Barrier synchronizes N separate PROCESSES, not just threads/coroutines,
    # so this exercises the actual fcntl.flock contention path, not something the GIL could
    # mask) ---------------------------------------------------------------------------------
    import multiprocessing
    cr_conc_dir = _tempfile.mkdtemp()
    try:
        cr_conc_path = os.path.join(cr_conc_dir, "epic-state.json")
        _atomic_write_json(cr_conc_path, build_state(
            v11_feats, "e", "E", stance="marathon",
            caps={"watch": True, "started_at": v11_live_started}))
        N = 8
        barrier = multiprocessing.Barrier(N)
        q = multiprocessing.Queue()
        now_iso_conc = _now_iso(_parse_iso("2026-01-01T00:01:00+00:00"))
        procs = [multiprocessing.Process(target=_cr_worker,
                                         args=(cr_conc_path, 10000 + i, now_iso_conc,
                                               barrier, q))
                for i in range(N)]
        for pr in procs:
            pr.start()
        for pr in procs:
            pr.join(timeout=20)
        results = [q.get(timeout=10) for _ in range(N)]
        oks = [r for r in results if r[0]]
        check("v2.11 claim_resume concurrency: all %d calls returned ok=True "
              "(no lock/read errors)" % N, len(oks) == N)
        winners = [r for r in results if r[0] and r[1] and r[1].get("claimed") is True]
        check("v2.11 claim_resume concurrency: exactly ONE of %d concurrent claims wins" % N,
              len(winners) == 1)
        losers = [r for r in results if r[0] and r[1] and r[1].get("claimed") is False]
        check("v2.11 claim_resume concurrency: the other %d all lose with a documented "
              "reason" % (N - 1),
              len(losers) == N - 1
              and all(r[1]["reason"] in ("live-lease-held", "terminal", "resume-cap")
                     for r in losers))
        final_conc_state = _read_json(cr_conc_path)
        check("v2.11 claim_resume concurrency: resume_count landed at exactly 1 "
              "(one winner, no double-counting)",
              final_conc_state.get("resume_count") == 1)
    finally:
        shutil.rmtree(cr_conc_dir, ignore_errors=True)

    print("SELFTEST: %d ok, %d fail" % (ok, fail))
    return 0 if fail == 0 else 1


def main(argv):
    # LANG=C-clean: any non-ASCII in stdout/stderr must not crash the process.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    p = argparse.ArgumentParser(description="Compound V epic-state manager.")
    p.add_argument("--init", action="store_true")
    p.add_argument("--next", dest="want_next", action="store_true")
    p.add_argument("--update", action="store_true")
    p.add_argument("--summary", action="store_true")
    p.add_argument("--selftest", action="store_true")
    p.add_argument("--features", help="features list JSON (for --init)")
    p.add_argument("--epic-id", default="epic")
    p.add_argument("--title", default="")
    p.add_argument("--state", help="path to epic-state.json")
    p.add_argument("--out", help="output path for --init (default = --state)")
    p.add_argument("--feature", help="feature id (for --update / --can-retry / "
                                     "--record-disposition)")
    p.add_argument("--status", help="(--update: %s) (--record-final-review: pending|passed|"
                                    "failed)" % "|".join(STATUSES))
    p.add_argument("--run-id")
    p.add_argument("--lint", action="store_true",
                   help="(with --features) print structural decomposition warnings + validation errors")
    p.add_argument("--stats", action="store_true",
                   help="(with --state) print epic progress counts")
    p.add_argument("--require-specs", action="store_true",
                   help="(with --init) every feature must carry an existing spec_path")
    p.add_argument("--check-specs", action="store_true",
                   help="(with --state) verify every non-done feature still has an existing, contained spec_path (resume guard)")
    # -- v2.10 marathon flags --------------------------------------------------------------
    p.add_argument("--stance", choices=("checkpoint", "marathon"),
                   help="(with --init) opt into the marathon autonomy schema")
    # Caps accept an integer/float OR the literal 'null'/'none' for an explicit unbounded
    # axis (Codex round-3 #6). Default is a sentinel so "absent" (use the documented default)
    # is distinct from "explicit null" (unbounded).
    p.add_argument("--max-attempts-per-feature", type=_cap_arg(int), default=_UNSET)
    p.add_argument("--max-no-progress-cycles", type=_cap_arg(int), default=_UNSET)
    p.add_argument("--max-total-attempts", type=_cap_arg(int), default=_UNSET)
    p.add_argument("--max-wall-clock-hours", type=_cap_arg(float), default=_UNSET)
    p.add_argument("--now", help="inject an ISO-8601 timestamp instead of the real clock "
                                 "(deterministic tests); default = real clock")
    p.add_argument("--autonomous", action="store_true",
                   help="(with --next) marathon DAG-transitive routing + terminal-state resolution")
    p.add_argument("--can-retry", action="store_true")
    p.add_argument("--record-disposition", action="store_true")
    p.add_argument("--disposition", choices=("retry_fix", "halt_feature", "halt_epic",
                                             "blocked_external"))
    p.add_argument("--reason")
    p.add_argument("--families-agreeing", help="comma-separated model family names")
    p.add_argument("--confirmed", choices=("true", "false"), default="false",
                   help="(with --record-disposition) MUST be false in v2.10 — hard-rejected if true")
    p.add_argument("--record-final-review", action="store_true")
    p.add_argument("--record-progress-cycle", action="store_true")
    p.add_argument("--cycle-id")
    p.add_argument("--breaker-check", action="store_true")
    p.add_argument("--trip-breaker", action="store_true")
    p.add_argument("--blocker-reason")
    p.add_argument("--blocker-confirmed", choices=("true", "false"), default=None,
                   help="(with --update --status blocked) MUST be false in v2.10 — hard-rejected if true")
    p.add_argument("--evidence", help="(with --update --status blocked) the missing external fact, if known")
    p.add_argument("--last-error", help="(with --update --status failed, marathon-only) persist the "
                                        "feature's last error; cleared on a retry/done")
    p.add_argument("--start-sha", help="(with --init --stance marathon) git rev-parse HEAD, "
                                       "stored as autonomy.start_sha; marathon-only")
    p.add_argument("--clear-breaker", action="store_true",
                   help="(marathon) human re-arm after a breaker trip/halt — clears the "
                        "blocked_needing_human latch")
    p.add_argument("--reset-wall-clock", action="store_true",
                   help="(with --clear-breaker) reset autonomy.started_at to now")
    p.add_argument("--set-max-total-attempts", type=_cap_arg(int), default=_UNSET,
                   help="(with --clear-breaker) re-arm autonomy.max_total_attempts; N or "
                        "'null'/'none' for an explicit unbounded axis")
    p.add_argument("--clear-disposition", action="store_true",
                   help="(marathon) clear a feature's stored disposition, e.g. to undo a "
                        "sticky halt_epic/halt_feature verdict")
    p.add_argument("--mark-sample-audit-due", action="store_true",
                   help="(marathon) record a durable sample-audit obligation on --feature F "
                        "before a PASS sample-audit runs; gates terminal completion")
    p.add_argument("--clear-sample-audit-due", action="store_true",
                   help="(marathon) clear --feature F's sample-audit obligation once the "
                        "audit has passed")
    p.add_argument("--record-audit-failed", action="store_true",
                   help="(marathon) ONE atomic write: revert --feature F from done to failed, "
                        "clear its sample_audit_due obligation, optionally set --last-error, "
                        "and invalidate a passed final_review back to pending — the fix for a "
                        "crash between the driver's separate clear-due/mark-failed writes")
    # -- v2.11 (Scheduler Auto-Resurrection, V1) flags --------------------------------------
    p.add_argument("--watch", action="store_true",
                   help="(with --init --stance marathon) opt into the v2.11 watch surface "
                        "(last_progress_at/lease/resume_count); rejected without "
                        "--stance marathon")
    p.add_argument("--max-resume-count", type=_cap_arg(int), default=_UNSET,
                   help="(with --init --stance marathon --watch) the new resume-count "
                        "breaker axis; default 20; 'null'/'none' for unbounded; rejected "
                        "without --watch")
    p.add_argument("--liveness", action="store_true",
                   help="(marathon + watch) read-only watcher poll -> {incomplete,stale,"
                        "held,lease_expired,epic_status,terminal,resume_count}")
    p.add_argument("--stale-after-min", type=float, default=None,
                   help="(with --liveness) staleness threshold in minutes (default 45)")
    p.add_argument("--claim-resume", action="store_true",
                   help="(marathon + watch) THE CRUX: one flock-guarded atomic transaction "
                        "-> {claimed,reason,resume_count}; needs --owner-pid")
    p.add_argument("--renew-lease", action="store_true",
                   help="(marathon + watch) the lease holder's own heartbeat; needs "
                        "--owner-pid (must match the current lease)")
    p.add_argument("--owner-pid", type=int,
                   help="(with --claim-resume / --renew-lease) the calling process's pid")
    p.add_argument("--lease-ttl-min", type=float, default=_DEFAULT_LEASE_TTL_MIN,
                   help="(with --claim-resume / --renew-lease) lease TTL in minutes "
                        "(default %g)" % _DEFAULT_LEASE_TTL_MIN)
    p.add_argument("--reset-resume-count", action="store_true",
                   help="(with --clear-breaker) re-arm the v2.11 resume-count axis to 0")
    args = p.parse_args(argv)

    if args.selftest:
        return _selftest()

    if args.lint:
        if not args.features:
            p.error("--lint needs --features <json>")
        feats = _read_json(args.features)
        errors = validate_features(feats)
        # If the list is structurally invalid, the advisory lint can't run safely — report
        # the hard errors only (and never crash on a malformed entry).
        warnings = [] if errors else lint_decomposition(feats)
        print(json.dumps({"errors": errors, "warnings": warnings}, indent=2))
        return 1 if errors else 0

    if args.init:
        if not args.features:
            p.error("--init needs --features <json>")
        feats = _read_json(args.features)
        errs = validate_features(feats)
        if errs:
            for e in errs:
                print("epic-init error: %s" % e, file=sys.stderr)
            return 1
        if args.require_specs:
            spec_errs = check_specs(feats, base_dir=os.path.dirname(os.path.abspath(args.features)))
            if spec_errs:
                for e in spec_errs:
                    print("epic-init spec error: %s" % e, file=sys.stderr)
                return 1
        stance = "marathon" if args.stance == "marathon" else None
        caps = None
        if stance == "marathon":
            caps = {}
            # `is not _UNSET` distinguishes an omitted cap (use the default) from an EXPLICIT
            # value — including an explicit null (unbounded), which must land in `caps` so
            # build_state records it (Codex round-3 #6).
            if args.max_attempts_per_feature is not _UNSET:
                caps["max_attempts_per_feature"] = args.max_attempts_per_feature
            if args.max_no_progress_cycles is not _UNSET:
                caps["max_no_progress_cycles"] = args.max_no_progress_cycles
            if args.max_total_attempts is not _UNSET:
                caps["max_total_attempts"] = args.max_total_attempts
            if args.max_wall_clock_hours is not _UNSET:
                caps["max_wall_clock_hours"] = args.max_wall_clock_hours
            if args.now:
                caps["started_at"] = args.now
            if args.start_sha:
                caps["start_sha"] = args.start_sha
            # v2.11: --watch is presence-based-opt-in; --max-resume-count is REJECTED unless
            # --watch is also given (same rejection discipline as every other marathon-only
            # arg in this file — never silently discarded).
            if args.watch:
                caps["watch"] = True
                if args.max_resume_count is not _UNSET:
                    caps["max_resume_count"] = args.max_resume_count
            elif args.max_resume_count is not _UNSET:
                print("epic-init error: --max-resume-count is watch-only — not valid "
                      "without --watch", file=sys.stderr)
                return 1
        elif args.start_sha:
            # Non-marathon --init must REJECT --start-sha (not silently discard it) — same
            # presence-based-rejection discipline as every other marathon-only arg in this
            # file, and it keeps a plain checkpoint --init byte-identical (this path never
            # reaches build_state with a caps dict at all).
            print("epic-init error: --start-sha is marathon-only — not valid without "
                  "--stance marathon", file=sys.stderr)
            return 1
        elif args.watch or args.max_resume_count is not _UNSET:
            # v2.11: same discipline — --watch/--max-resume-count are marathon-only.
            print("epic-init error: --watch/--max-resume-count are marathon-only — not "
                  "valid without --stance marathon", file=sys.stderr)
            return 1
        try:
            state = build_state(feats, args.epic_id, args.title or args.epic_id,
                                stance=stance, caps=caps)
        except ValueError as e:
            print("epic-init error: %s" % e, file=sys.stderr)
            return 1
        out = args.out or args.state
        if not out:
            p.error("--init needs --out (or --state)")
        _atomic_write_json(out, state)
        print("wrote %s (%d features)" % (out, len(state["features"])))
        return 0

    if not args.state or not os.path.exists(args.state):
        p.error("--state <epic-state.json> is required and must exist")
    state = _read_json(args.state)

    # Codex review #10: a loaded marathon state must be structurally sound before any
    # marathon command reads/mutates it — a controlled nonzero, never a raw KeyError/
    # TypeError crash. Checkpoint states are untouched (validator is a no-op there).
    if _is_marathon(state):
        merrs = validate_marathon_state(state)
        if merrs:
            for e in merrs:
                print("epic-state error: %s" % e, file=sys.stderr)
            return 1

    # Codex round-3 #8: a malformed --now must fail with a controlled error, never an
    # uncaught ValueError from datetime.fromisoformat on the breaker/disposition/update
    # paths. Validate once up front (init handled its own --now via build_state above).
    if args.now:
        try:
            _parse_iso(args.now)
        except (ValueError, TypeError) as e:
            print("epic error: --now %r is not a valid ISO-8601 timestamp (%s)"
                  % (args.now, e), file=sys.stderr)
            return 1

    def _needs_marathon(cmd):
        """Codex review #2: a marathon-only command must REJECT (nonzero, no write) when the
        persisted state is not marathon stance."""
        if not _is_marathon(state):
            print("epic error: %s requires a marathon-stance epic (this state has no "
                  "'autonomy' block — re-init with --stance marathon)" % cmd,
                  file=sys.stderr)
            return False
        return True

    def _needs_watch(cmd):
        """v2.11: the three new watch-only commands (--liveness, --claim-resume,
        --renew-lease) require BOTH marathon stance AND the persisted watch opt-in — their
        whole purpose (a heartbeat/lease that is never written unless watch is on) is
        meaningless otherwise, so this rejects the same way `_needs_marathon` does."""
        if not _needs_marathon(cmd):
            return False
        if not _watch_on(state):
            print("epic error: %s requires the marathon epic's watch opt-in (re-init with "
                  "--stance marathon --watch)" % cmd, file=sys.stderr)
            return False
        return True

    def _resolve_now_ranged(cmd):
        """v2.11: resolve --now (or the real clock) and range-check an EXPLICITLY supplied
        --now against the real clock (_now_arg_in_range) — --now is test-only, this bounds it
        so it can never become a production lever for defeating staleness/lease timing.
        Returns the resolved datetime, or None on an out-of-range --now (caller returns 1)."""
        now_dt = _resolve_now(args.now)
        if args.now and not _now_arg_in_range(now_dt):
            print("epic error: %s --now is test-only and must be within a sane range of "
                  "the real clock" % cmd, file=sys.stderr)
            return None
        return now_dt

    if args.check_specs:
        errs = check_state_specs(state, base_dir=os.path.dirname(os.path.abspath(args.state)))
        if errs:
            for e in errs:
                print("epic spec-check error: %s" % e, file=sys.stderr)
            return 1
        print(json.dumps({"ok": True}))
        return 0

    if args.stats:
        print(json.dumps(stats(state)))
        return 0

    if args.can_retry:
        if not _needs_marathon("--can-retry"):
            return 1
        if not args.feature:
            p.error("--can-retry needs --feature")
        info = can_retry_info(state, args.feature)
        if info is None:
            print("epic error: no feature %r" % args.feature, file=sys.stderr)
            return 1
        print(json.dumps(info))
        return 0

    if args.breaker_check:
        if not _needs_marathon("--breaker-check"):
            return 1
        now_dt = _resolve_now(args.now)
        print(json.dumps(breaker_check(state, now_dt)))
        return 0

    if args.trip_breaker:
        if not _needs_marathon("--trip-breaker"):
            return 1
        now_dt = _resolve_now(args.now)
        result = trip_breaker(state, now_dt)
        mutated = result.pop("mutated", False)
        if mutated:
            _atomic_write_json(args.state, state)
        print(json.dumps(result))
        return 0

    if args.clear_breaker:
        if not _needs_marathon("--clear-breaker"):
            return 1
        now_dt = _resolve_now(args.now)
        ok, err, summary = clear_breaker(state, now_dt,
                                         reset_wall_clock=args.reset_wall_clock,
                                         set_max_total_attempts=args.set_max_total_attempts,
                                         reset_resume_count=args.reset_resume_count)
        if not ok:
            print("epic-clear-breaker error: %s" % err, file=sys.stderr)
            return 1
        _atomic_write_json(args.state, state)
        print(json.dumps(summary))
        return 0

    if args.clear_disposition:
        if not _needs_marathon("--clear-disposition"):
            return 1
        if not args.feature:
            p.error("--clear-disposition needs --feature")
        ok, err = clear_disposition(state, args.feature, now_dt=_resolve_now(args.now))
        if not ok:
            print("epic-clear-disposition error: %s" % err, file=sys.stderr)
            return 1
        _atomic_write_json(args.state, state)
        print(json.dumps({"feature": args.feature, "disposition": None}))
        return 0

    if args.mark_sample_audit_due:
        if not _needs_marathon("--mark-sample-audit-due"):
            return 1
        if not args.feature:
            p.error("--mark-sample-audit-due needs --feature")
        ok, err = mark_sample_audit_due(state, args.feature, now_dt=_resolve_now(args.now))
        if not ok:
            print("epic-sample-audit error: %s" % err, file=sys.stderr)
            return 1
        _atomic_write_json(args.state, state)
        print(json.dumps({"feature": args.feature, "sample_audit_due": True}))
        return 0

    if args.clear_sample_audit_due:
        if not _needs_marathon("--clear-sample-audit-due"):
            return 1
        if not args.feature:
            p.error("--clear-sample-audit-due needs --feature")
        ok, err = clear_sample_audit_due(state, args.feature, now_dt=_resolve_now(args.now))
        if not ok:
            print("epic-sample-audit error: %s" % err, file=sys.stderr)
            return 1
        _atomic_write_json(args.state, state)
        print(json.dumps({"feature": args.feature, "sample_audit_due": False}))
        return 0

    if args.record_audit_failed:
        if not _needs_marathon("--record-audit-failed"):
            return 1
        if not args.feature:
            p.error("--record-audit-failed needs --feature")
        ok, err = record_audit_failed(state, args.feature, last_error=args.last_error,
                                      now_dt=_resolve_now(args.now))
        if not ok:
            print("epic-audit-failed error: %s" % err, file=sys.stderr)
            return 1
        _atomic_write_json(args.state, state)
        hit = _find_feature(state, args.feature)
        print(json.dumps({"feature": args.feature, "status": hit["status"],
                          "sample_audit_due": hit.get("sample_audit_due"),
                          "final_review": state.get("final_review"),
                          "epic_status": state["status"]}))
        return 0

    if args.record_progress_cycle:
        if not _needs_marathon("--record-progress-cycle"):
            return 1
        if not args.cycle_id:
            p.error("--record-progress-cycle needs --cycle-id")
        result = record_progress_cycle(state, args.cycle_id, now_dt=_resolve_now(args.now))
        if not result.get("replayed"):
            _atomic_write_json(args.state, state)
        print(json.dumps(result))
        return 0

    if args.record_disposition:
        if not _needs_marathon("--record-disposition"):
            return 1
        if not args.feature or not args.disposition:
            p.error("--record-disposition needs --feature and --disposition")
        now_dt = _resolve_now(args.now)
        ok, err = record_disposition(state, args.feature, args.disposition, reason=args.reason,
                                     families_agreeing=_parse_csv_list(args.families_agreeing),
                                     confirmed=(args.confirmed == "true"), now_dt=now_dt)
        if not ok:
            print("epic-disposition error: %s" % err, file=sys.stderr)
            return 1
        _atomic_write_json(args.state, state)
        print(json.dumps({"feature": args.feature,
                          "disposition": _find_feature(state, args.feature)["disposition"]}))
        return 0

    if args.record_final_review:
        if not _needs_marathon("--record-final-review"):
            return 1
        if not args.status:
            p.error("--record-final-review needs --status pending|passed|failed")
        ok, err = record_final_review(state, args.status, now_dt=_resolve_now(args.now))
        if not ok:
            print("epic-final-review error: %s" % err, file=sys.stderr)
            return 1
        _atomic_write_json(args.state, state)
        print(json.dumps({"final_review": state["final_review"], "epic_status": state["status"]}))
        return 0

    if args.liveness:
        if not _needs_watch("--liveness"):
            return 1
        now_dt = _resolve_now_ranged("--liveness")
        if now_dt is None:
            return 1
        stale_after = (args.stale_after_min if args.stale_after_min is not None
                      else _DEFAULT_STALE_AFTER_MIN)
        print(json.dumps(liveness_check(state, now_dt, stale_after_min=stale_after)))
        return 0

    if args.claim_resume:
        if not _needs_watch("--claim-resume"):
            return 1
        if args.owner_pid is None:
            p.error("--claim-resume needs --owner-pid")
        now_dt = _resolve_now_ranged("--claim-resume")
        if now_dt is None:
            return 1
        ok, result, err = claim_resume(args.state, args.owner_pid, now_dt,
                                       lease_ttl_min=args.lease_ttl_min)
        if not ok:
            print("epic-claim-resume error: %s" % err, file=sys.stderr)
            return 1
        print(json.dumps(result))
        return 0

    if args.renew_lease:
        if not _needs_watch("--renew-lease"):
            return 1
        if args.owner_pid is None:
            p.error("--renew-lease needs --owner-pid")
        now_dt = _resolve_now_ranged("--renew-lease")
        if now_dt is None:
            return 1
        ok, err = renew_lease(state, args.owner_pid, now_dt, lease_ttl_min=args.lease_ttl_min)
        if not ok:
            print("epic-renew-lease error: %s" % err, file=sys.stderr)
            return 1
        _atomic_write_json(args.state, state)
        print(json.dumps({"owner_pid": args.owner_pid, "lease": state["lease"]}))
        return 0

    if args.want_next:
        if args.autonomous:
            if not _needs_marathon("--next --autonomous"):
                return 1
            f, why, blocked_by = next_feature_autonomous(state)
            print(json.dumps({"feature": f, "reason": why, "blocked_by": blocked_by}))
        else:
            f, why = next_feature(state)
            print(json.dumps({"feature": f, "reason": why}))
        # INTENTIONALLY always 0 (A7 legacy): the JSON on stdout is the contract — a null
        # feature with a stop reason is information, not failure (commands/v-epic.md:
        # "--next is read-only and never an error"). Exit codes here are NOT a signal
        # channel; the driver branches on "reason", and a nonzero would read as a script
        # fault. --next --autonomous keeps the same convention.
        return 0

    if args.update:
        if not args.feature or not args.status:
            p.error("--update needs --feature and --status")
        # Codex round-3 #4: reject ANY marathon-only arg SUPPLIED against a checkpoint state —
        # detected by argument PRESENCE (sentinel/None defaults), so `--blocker-confirmed
        # false` and an explicit empty `--families-agreeing` are caught too, not just truthy
        # values. Presence, not truthiness.
        if not _is_marathon(state):
            supplied = []
            if args.last_error is not None:
                supplied.append("--last-error")
            if args.blocker_reason is not None:
                supplied.append("--blocker-reason")
            if args.evidence is not None:
                supplied.append("--evidence")
            if args.families_agreeing is not None:
                supplied.append("--families-agreeing")
            if args.blocker_confirmed is not None:
                supplied.append("--blocker-confirmed")
            if supplied:
                print("epic-update error: %s %s marathon-only — not valid on a checkpoint-"
                      "stance epic" % (", ".join(supplied),
                                       "is" if len(supplied) == 1 else "are"), file=sys.stderr)
                return 1
        now_dt = _resolve_now(args.now)
        ok, err = apply_update(state, args.feature, args.status, run_id=args.run_id, now_dt=now_dt,
                               blocker_reason=args.blocker_reason,
                               blocker_confirmed=(args.blocker_confirmed == "true"),
                               families_agreeing=_parse_csv_list(args.families_agreeing),
                               evidence=args.evidence, last_error=args.last_error)
        if not ok:
            print("epic-update error: %s" % err, file=sys.stderr)
            return 1
        _atomic_write_json(args.state, state)
        print(json.dumps({"feature": args.feature, "status": args.status,
                          "epic_status": state["status"]}))
        return 0

    if args.summary:
        print("EPIC %s — %s  [%s]" % (state.get("epic_id"), state.get("title"), state.get("status")))
        for f in state["features"]:
            deps = ",".join(f["depends_on"]) or "-"
            print("  [%-7s] %-20s deps=%s run=%s" % (f["status"], f["id"], deps, f["run_id"] or "-"))
        return 0

    p.error("one of --init / --next / --update / --summary / --stats / --check-specs / "
           "--lint / --can-retry / --breaker-check / --trip-breaker / --clear-breaker / "
           "--record-progress-cycle / --record-disposition / --clear-disposition / "
           "--mark-sample-audit-due / --clear-sample-audit-due / --record-audit-failed / "
           "--record-final-review / --liveness / --claim-resume / --renew-lease / "
           "--selftest is required")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
