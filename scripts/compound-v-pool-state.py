#!/usr/bin/env python3
"""Compound V weighted pool assignment state helpers (Python 3.9 stdlib).

The JSON CLI reads one request object from stdin and prints one result object:

``freeze``
    ``{"state", "jobs", "pools", "stance", "config_models"}`` -> frozen state.
``validate``
    ``{"state", "jobs"}`` -> ``{"valid", "errors"}``.
``resume``
    ``{"state", "job_id"}`` -> the recorded concrete assignment.
``select``
    ``{"state", "tier", "index"}`` -> one concrete frozen slot.
"""

import copy
import datetime
import importlib.util
import json
import os
import shutil
import sys


KNOWN_JOB_STATUSES = ("pending", "dispatched", "running", "done", "blocked", "failed")
VALID_POOL_TIERS = ("deep", "standard", "light")
VALID_CONCRETE_BACKENDS = (
    "claude", "codex", "antigravity", "cursor", "devin", "opencode", "zai",
)
VALID_ASSIGNMENT_SOURCES = ("pool", "fallback")
MAX_POOL_WEIGHT = 100
MAX_EXPANDED_POOL_SLOTS = 256
CIRCUIT_REASONS = ("out_of_credits", "auth")
CIRCUIT_CLEARED_BY = ("top_up", "reauth", "probe")
CIRCUIT_ENTRY_FIELDS = frozenset(("open", "reason", "opened_at", "cleared_by"))
COOLDOWN_REASONS = (
    "rate_limited", "overloaded", "usage_window_exhausted", "network",
)
COOLDOWN_ENTRY_FIELDS = frozenset((
    "until", "reason", "opened_at", "opened_by_attempt_id", "probe",
))
PROBE_FIELDS = frozenset((
    "status", "owner_job_id", "owner_attempt_id", "lease_until",
))
NETWORK_EVIDENCE_FIELDS = frozenset((
    "backend", "job_id", "attempt_id", "batch_id", "observed_at",
))
NETWORK_PAUSE_FIELDS = frozenset(("opened_at", "until", "evidence", "probe"))
NETWORK_CORRELATION_SECONDS = 60


def _provider_time_module():
    """Load the shared Python 3.9-safe timestamp contract."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "compound-v-provider-time.py")
    spec = importlib.util.spec_from_file_location("compound_v_provider_time_pool", path)
    if spec is None or spec.loader is None:
        raise ValueError("cannot load sibling provider time helper: %s" % path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _parse_timestamp(value, field):
    return _provider_time_module().parse_utc_timestamp(value, field)


def _format_timestamp(value):
    return _provider_time_module().format_utc_timestamp(value)


def _parse_nonnegative(value, field):
    return _provider_time_module().parse_delay(value, field)


def _parse_canonical_timestamp(value, field):
    """Parse persisted state time and require its single normalized UTC form."""
    parsed = _parse_timestamp(value, field)
    if value != _format_timestamp(parsed):
        raise ValueError("%s must use canonical UTC with terminal Z" % field)
    return parsed


def _idle_probe():
    return {
        "status": "idle",
        "owner_job_id": None,
        "owner_attempt_id": None,
        "lease_until": None,
    }


def _probe_errors(probe, path, state_jobs, opened_at=None):
    """Validate one idle/leased probe without using wall-clock time."""
    if not isinstance(probe, dict):
        return ["%s must be an object" % path]
    if frozenset(probe.keys()) != PROBE_FIELDS:
        return ["%s must contain exactly status, owner_job_id, "
                "owner_attempt_id, lease_until" % path]
    errors = []
    status = probe.get("status")
    owner_job_id = probe.get("owner_job_id")
    owner_attempt_id = probe.get("owner_attempt_id")
    lease_until = probe.get("lease_until")
    if status not in ("idle", "leased"):
        errors.append("%s.status must be idle or leased" % path)
    elif status == "idle":
        if any(value is not None for value in (
                owner_job_id, owner_attempt_id, lease_until)):
            errors.append("%s idle probe must have null owner, attempt, and lease" % path)
    else:
        if not isinstance(owner_job_id, str) or not owner_job_id:
            errors.append("%s leased probe requires owner_job_id" % path)
        if not isinstance(owner_attempt_id, str) or not owner_attempt_id:
            errors.append("%s leased probe requires owner_attempt_id" % path)
        owner = state_jobs.get(owner_job_id) if isinstance(state_jobs, dict) else None
        if not isinstance(owner, dict):
            errors.append("%s owner job does not exist in state.jobs" % path)
        elif owner.get("attempt_id") != owner_attempt_id:
            errors.append("%s owner attempt is not the job's current attempt" % path)
        try:
            lease_value = _parse_canonical_timestamp(
                lease_until, "%s.lease_until" % path)
            if opened_at is not None and lease_value < opened_at:
                errors.append("%s.lease_until precedes the state opening time" % path)
        except ValueError as error:
            errors.append(str(error))
    return errors


def _cooldown_errors(cooldowns, state_jobs):
    """Return errors for canonical transient backend cooldowns."""
    if not isinstance(cooldowns, dict):
        return ["state.cooldowns must be an object map"]
    errors = []
    leased_attempts = set()
    for backend, entry in cooldowns.items():
        path = "state.cooldowns[%r]" % backend
        if backend not in VALID_CONCRETE_BACKENDS:
            errors.append("%s uses an unknown concrete backend key" % path)
        if not isinstance(entry, dict):
            errors.append("%s must be a canonical object, never a bare timestamp" % path)
            continue
        if frozenset(entry.keys()) != COOLDOWN_ENTRY_FIELDS:
            errors.append("%s must contain exactly until, reason, opened_at, "
                          "opened_by_attempt_id, probe" % path)
            continue
        if entry.get("reason") not in COOLDOWN_REASONS:
            errors.append("%s.reason is not a transient cooldown reason" % path)
        attempt_id = entry.get("opened_by_attempt_id")
        if not isinstance(attempt_id, str) or not attempt_id:
            errors.append("%s.opened_by_attempt_id must be non-empty" % path)
        opened = None
        until = None
        try:
            opened = _parse_canonical_timestamp(
                entry.get("opened_at"), "%s.opened_at" % path)
        except ValueError as error:
            errors.append(str(error))
        try:
            until = _parse_canonical_timestamp(entry.get("until"), "%s.until" % path)
        except ValueError as error:
            errors.append(str(error))
        if opened is not None and until is not None and until < opened:
            errors.append("%s.until must not precede opened_at" % path)
        errors.extend(_probe_errors(entry.get("probe"), "%s.probe" % path,
                                    state_jobs, opened_at=opened))
        probe = entry.get("probe")
        if isinstance(probe, dict) and probe.get("status") == "leased":
            owner_attempt = probe.get("owner_attempt_id")
            if owner_attempt in leased_attempts:
                errors.append("%s duplicates probe ownership for attempt %r"
                              % (path, owner_attempt))
            leased_attempts.add(owner_attempt)
    return errors


def _network_evidence_errors(evidence, path="state.network_evidence", state_jobs=None):
    if not isinstance(evidence, list):
        return ["%s must be a list" % path]
    errors = []
    seen = set()
    for index, row in enumerate(evidence):
        row_path = "%s[%d]" % (path, index)
        if not isinstance(row, dict):
            errors.append("%s must be an object" % row_path)
            continue
        if frozenset(row.keys()) != NETWORK_EVIDENCE_FIELDS:
            errors.append("%s must contain exactly backend, job_id, attempt_id, "
                          "batch_id, observed_at" % row_path)
            continue
        backend = row.get("backend")
        if backend not in VALID_CONCRETE_BACKENDS:
            errors.append("%s.backend is unknown" % row_path)
        for field in ("job_id", "attempt_id", "batch_id"):
            if not isinstance(row.get(field), str) or not row.get(field):
                errors.append("%s.%s must be non-empty" % (row_path, field))
        job_id = row.get("job_id")
        attempt_id = row.get("attempt_id")
        if state_jobs is not None and job_id not in state_jobs:
            errors.append("%s.job_id does not exist in state.jobs" % row_path)
        if isinstance(job_id, str) and isinstance(attempt_id, str):
            prefix = "%s:" % job_id
            suffix = attempt_id[len(prefix):] if attempt_id.startswith(prefix) else ""
            if not suffix.isdigit() or int(suffix) < 1:
                errors.append("%s.attempt_id is not a valid job generation" % row_path)
        try:
            _parse_canonical_timestamp(
                row.get("observed_at"), "%s.observed_at" % row_path)
        except ValueError as error:
            errors.append(str(error))
        dedupe = (backend, row.get("attempt_id"))
        if dedupe in seen:
            errors.append("%s duplicates backend plus attempt_id evidence" % row_path)
        seen.add(dedupe)
    return errors


def _network_pause_errors(pause, state_jobs):
    if pause is None:
        return []
    path = "state.network_pause"
    if not isinstance(pause, dict):
        return ["%s must be an object" % path]
    if frozenset(pause.keys()) != NETWORK_PAUSE_FIELDS:
        return ["%s must contain exactly opened_at, until, evidence, probe" % path]
    errors = []
    opened = None
    until = None
    try:
        opened = _parse_canonical_timestamp(
            pause.get("opened_at"), "%s.opened_at" % path)
    except ValueError as error:
        errors.append(str(error))
    try:
        until = _parse_canonical_timestamp(pause.get("until"), "%s.until" % path)
    except ValueError as error:
        errors.append(str(error))
    if opened is not None and until is not None and until < opened:
        errors.append("%s.until must not precede opened_at" % path)
    evidence = pause.get("evidence")
    errors.extend(_network_evidence_errors(
        evidence, "%s.evidence" % path, state_jobs=state_jobs))
    if isinstance(evidence, list):
        batches = {row.get("batch_id") for row in evidence if isinstance(row, dict)}
        backends = {row.get("backend") for row in evidence if isinstance(row, dict)}
        if len(evidence) < 2 or len(backends) < 2:
            errors.append("%s requires evidence from two distinct providers" % path)
        if len(batches) != 1:
            errors.append("%s evidence must share exactly one batch_id" % path)
        observed = []
        for index, row in enumerate(evidence):
            if not isinstance(row, dict):
                continue
            try:
                observed.append(_parse_canonical_timestamp(
                    row.get("observed_at"), "%s.evidence[%d].observed_at" % (path, index)))
            except ValueError:
                pass
        if observed and (max(observed) - min(observed)).total_seconds() \
                > NETWORK_CORRELATION_SECONDS:
            errors.append("%s evidence exceeds the 60-second correlation window" % path)
    errors.extend(_probe_errors(pause.get("probe"), "%s.probe" % path,
                                state_jobs, opened_at=opened))
    return errors


def _cross_family_probe_errors(state):
    """Reject one persisted attempt leasing more than one health-state family."""
    owners = {}
    errors = []
    cooldowns = state.get("cooldowns")
    if isinstance(cooldowns, dict):
        for backend, entry in cooldowns.items():
            probe = entry.get("probe") if isinstance(entry, dict) else None
            if isinstance(probe, dict) and probe.get("status") == "leased":
                attempt_id = probe.get("owner_attempt_id")
                if isinstance(attempt_id, str):
                    owners.setdefault(attempt_id, []).append(
                        "state.cooldowns[%r].probe" % backend)
    pause = state.get("network_pause")
    if isinstance(pause, dict):
        probe = pause.get("probe")
        if isinstance(probe, dict) and probe.get("status") == "leased":
            attempt_id = probe.get("owner_attempt_id")
            if isinstance(attempt_id, str):
                owners.setdefault(attempt_id, []).append("state.network_pause.probe")
    for attempt_id, paths in owners.items():
        if len(paths) > 1:
            errors.append("duplicate probe ownership for attempt %r across %s"
                          % (attempt_id, ", ".join(paths)))
    return errors


def _transient_state_errors(state):
    if not isinstance(state, dict):
        return ["state root must be an object"]
    state_jobs = state.get("jobs")
    errors = _attempt_identity_errors(state_jobs)
    if "cooldowns" in state:
        errors.extend(_cooldown_errors(state.get("cooldowns"), state_jobs))
    if "network_evidence" in state:
        errors.extend(_network_evidence_errors(
            state.get("network_evidence"), state_jobs=state_jobs))
    if "network_successes" in state:
        errors.extend(_network_evidence_errors(
            state.get("network_successes"), path="state.network_successes",
            state_jobs=state_jobs))
    errors.extend(_network_pause_errors(state.get("network_pause"), state_jobs))
    errors.extend(_cross_family_probe_errors(state))
    return errors


def _attempt_identity_errors(state_jobs):
    """Validate optional persisted launch generations on every state job."""
    if not isinstance(state_jobs, dict):
        return []
    errors = []
    seen = set()
    for job_id, record in state_jobs.items():
        if not isinstance(record, dict):
            continue
        attempt_id = record.get("attempt_id")
        counter = record.get("attempt_counter")
        if attempt_id is None and counter is None:
            continue
        path = "state.jobs[%r]" % job_id
        if (not isinstance(counter, int) or isinstance(counter, bool) or counter < 1
                or attempt_id != "%s:%d" % (job_id, counter)):
            errors.append("%s has invalid persisted attempt identity" % path)
            continue
        if attempt_id in seen:
            errors.append("%s duplicates persisted attempt identity" % path)
        seen.add(attempt_id)
    return errors


def _circuit_open_errors(circuit_open):
    """Return errors for the canonical persisted circuit-breaker map."""
    if not isinstance(circuit_open, dict):
        return ["state.circuit_open must be an object map"]
    errors = []
    for backend, entry in circuit_open.items():
        path = "state.circuit_open[%r]" % backend
        if backend not in VALID_CONCRETE_BACKENDS:
            errors.append("%s uses an unknown concrete backend key" % path)
        if not isinstance(entry, dict):
            errors.append("%s must be an object, never a bare boolean" % path)
            continue
        if frozenset(entry.keys()) != CIRCUIT_ENTRY_FIELDS:
            errors.append("%s must contain exactly open, reason, opened_at, cleared_by"
                          % path)
            continue
        is_open = entry.get("open")
        reason = entry.get("reason")
        opened_at = entry.get("opened_at")
        cleared_by = entry.get("cleared_by")
        if not isinstance(is_open, bool):
            errors.append("%s.open must be true/false" % path)
        if reason not in CIRCUIT_REASONS:
            errors.append("%s.reason must be out_of_credits or auth" % path)
        try:
            _parse_canonical_timestamp(opened_at, "%s.opened_at" % path)
        except ValueError as error:
            errors.append(str(error))
        if cleared_by is not None and cleared_by not in CIRCUIT_CLEARED_BY:
            errors.append("%s.cleared_by must be null, top_up, reauth, or probe" % path)
        if is_open is True and cleared_by is not None:
            errors.append("%s.cleared_by must be null while the breaker is open" % path)
        if is_open is False and reason == "auth" and cleared_by != "reauth":
            errors.append("%s auth breaker may clear only via reauth" % path)
        if (is_open is False and reason == "out_of_credits"
                and cleared_by not in ("top_up", "probe")):
            errors.append("%s out_of_credits breaker may clear only via top_up or probe"
                          % path)
    return errors


def _resolver_module():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "compound-v-resolve-model.py")
    spec = importlib.util.spec_from_file_location("compound_v_resolve_model_pool", path)
    if spec is None or spec.loader is None:
        raise ValueError("cannot load sibling model resolver: %s" % path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def expand_members(members):
    """Expand positive integer weights into consecutive, unit-weight slots."""
    if not isinstance(members, list):
        raise ValueError("pool members must be a list")
    expanded = []
    for member in members:
        if not isinstance(member, dict):
            raise ValueError("pool member must be an object")
        weight = member.get("weight", 1)
        if (not isinstance(weight, int) or isinstance(weight, bool)
                or weight <= 0 or weight > MAX_POOL_WEIGHT):
            raise ValueError("pool member weight must be a positive integer <= %d"
                             % MAX_POOL_WEIGHT)
        if len(expanded) + weight > MAX_EXPANDED_POOL_SLOTS:
            raise ValueError("expanded pool exceeds the %d-slot limit"
                             % MAX_EXPANDED_POOL_SLOTS)
        for _unused in range(weight):
            slot = dict(member)
            slot["weight"] = 1
            expanded.append(slot)
    return expanded


def manifest_pool_ordinals(jobs):
    """Map pool job ids to manifest-order ordinals, counted independently per tier."""
    if not isinstance(jobs, list):
        raise ValueError("manifest jobs must be a list")
    counters = {}
    result = {}
    for job in jobs:
        if not isinstance(job, dict) or job.get("backend") != "pool":
            continue
        job_id = job.get("id")
        tier = job.get("tier")
        if not isinstance(job_id, str) or not job_id:
            raise ValueError("pool job is missing a non-empty id")
        if not isinstance(tier, str) or not tier:
            raise ValueError("pool job '%s' is missing a non-empty tier" % job_id)
        result[job_id] = counters.get(tier, 0)
        counters[tier] = counters.get(tier, 0) + 1
    return result


def backend_available(backend, env=None, which=None):
    """Evaluate the narrow documented pool precondition for one backend."""
    environment = os.environ if env is None else env
    find_binary = shutil.which if which is None else which
    if backend == "codex":
        return bool(find_binary("codex"))
    if backend == "zai":
        return bool(environment.get("ZAI_API_KEY"))
    return True


def freeze_pool_members(state, pools, stance, config_models, env=None, which=None):
    """Return state with expanded pool slots and availability frozen exactly once."""
    if not isinstance(state, dict):
        raise ValueError("state root must be an object")
    frozen_state = copy.deepcopy(state)
    frozen_state.setdefault("circuit_open", {})
    circuit_errors = _circuit_open_errors(frozen_state.get("circuit_open"))
    if circuit_errors:
        raise ValueError("; ".join(circuit_errors))
    transient_errors = _transient_state_errors(frozen_state)
    if transient_errors:
        raise ValueError("; ".join(transient_errors))
    if "pool_members" in frozen_state:
        if not isinstance(frozen_state["pool_members"], dict):
            raise ValueError("state.pool_members must be an object")
        return frozen_state

    stance_pools = pools.get(stance) if isinstance(pools, dict) else None
    if not isinstance(stance_pools, dict):
        raise ValueError("no configured pools for stance '%s'" % stance)

    resolver = _resolver_module()
    frozen_by_tier = {}
    for tier, members in stance_pools.items():
        frozen_slots = []
        for slot in expand_members(members):
            backend = slot.get("backend")
            if not isinstance(backend, str) or not backend:
                raise ValueError("pool member backend must be a non-empty string")
            available = backend_available(backend, env=env, which=which)
            model = None
            try:
                model = resolver.resolve(
                    backend=backend,
                    tier=tier,
                    config_models=config_models,
                    explicit_model=slot.get("model"),
                    stance=stance,
                )["model"]
            except ValueError:
                # A backend unavailable at freeze can remain as a positional
                # tombstone even when this branch lacks its resolver map. It is
                # never assignable; preserve an explicit override when present.
                if available:
                    raise
                explicit = slot.get("model")
                if isinstance(explicit, str) and explicit.strip():
                    model = explicit.strip()
            frozen = {"backend": backend, "available": available}
            if model is not None:
                frozen["model"] = model
            frozen_slots.append(frozen)
        frozen_by_tier[tier] = frozen_slots
    frozen_state["pool_members"] = frozen_by_tier
    return frozen_state


def select_frozen_member(state, tier, index, now=None, exclude_assignment=None):
    """Select a healthy slot without mutation; probes are acquired by transition."""
    if tier not in VALID_POOL_TIERS:
        raise ValueError("unknown frozen tier '%s'" % tier)
    if not isinstance(index, int) or isinstance(index, bool) or index < 0:
        raise ValueError("pool index must be a non-negative integer")
    members_by_tier = state.get("pool_members") if isinstance(state, dict) else None
    members = members_by_tier.get(tier) if isinstance(members_by_tier, dict) else None
    if not isinstance(members, list) or not members:
        raise ValueError("state has no frozen pool members for tier '%s'" % tier)
    circuit_open = state.get("circuit_open") if isinstance(state, dict) else None
    circuit_errors = _circuit_open_errors(circuit_open)
    if circuit_errors:
        raise ValueError("; ".join(circuit_errors))
    transient_errors = _transient_state_errors(state)
    if transient_errors:
        raise ValueError("; ".join(transient_errors))
    cooldowns = state.get("cooldowns", {})
    if cooldowns and now is None:
        raise ValueError("current aware UTC time is required when cooldowns exist")
    if now is not None:
        _parse_timestamp(now, "now")
    if exclude_assignment is not None:
        if (not isinstance(exclude_assignment, dict)
                or frozenset(exclude_assignment.keys()) != frozenset(("backend", "model"))
                or exclude_assignment.get("backend") not in VALID_CONCRETE_BACKENDS
                or not isinstance(exclude_assignment.get("model"), str)
                or not exclude_assignment.get("model")):
            raise ValueError("exclude_assignment must be an exact backend/model object")

    start = index % len(members)
    for offset in range(len(members)):
        slot_index = (start + offset) % len(members)
        member = members[slot_index]
        if not isinstance(member, dict):
            raise ValueError("frozen pool member must be an object")
        backend = member.get("backend")
        if backend not in VALID_CONCRETE_BACKENDS:
            raise ValueError("unknown concrete backend '%s' in frozen pool" % backend)
        breaker = circuit_open.get(backend)
        breaker_is_open = isinstance(breaker, dict) and breaker.get("open") is True
        model = member.get("model")
        exact_excluded = (isinstance(exclude_assignment, dict)
                          and exclude_assignment.get("backend") == backend
                          and exclude_assignment.get("model") == model)
        # A cooldown remains unavailable to this read-only selector even after
        # expiry: only transition_state may atomically lease the half-open probe.
        if (member.get("available") is not True or breaker_is_open
                or backend in cooldowns or exact_excluded):
            continue
        if not isinstance(backend, str) or not backend or backend == "pool":
            raise ValueError("frozen pool member has no concrete backend")
        if not isinstance(model, str) or not model:
            raise ValueError("frozen pool member '%s' has no concrete model" % backend)
        return {
            "assigned_backend": backend,
            "assigned_model": model,
            "pool_index": slot_index,
        }
    raise ValueError("no viable frozen pool member for tier '%s'" % tier)


def freeze_assignments(state, jobs, pools, stance, config_models,
                       env=None, which=None):
    """Freeze members and concrete assignments for all manifest pool jobs."""
    frozen = freeze_pool_members(
        state, pools, stance, config_models, env=env, which=which,
    )
    state_jobs = frozen.get("jobs")
    if state_jobs is None:
        state_jobs = {}
        frozen["jobs"] = state_jobs
    if not isinstance(state_jobs, dict):
        raise ValueError("state.jobs must be an object")

    ordinal_map = manifest_pool_ordinals(jobs)
    jobs_by_id = {
        job.get("id"): job for job in jobs
        if isinstance(job, dict) and isinstance(job.get("id"), str)
    }
    for job_id, ordinal in ordinal_map.items():
        record = state_jobs.setdefault(job_id, {})
        if not isinstance(record, dict):
            raise ValueError("state job '%s' must be an object" % job_id)
        if (isinstance(record.get("assigned_backend"), str)
                and record.get("assigned_backend")
                and isinstance(record.get("assigned_model"), str)
                and record.get("assigned_model")):
            continue
        assignment = select_frozen_member(
            frozen, jobs_by_id[job_id].get("tier"), ordinal,
        )
        record["assigned_backend"] = assignment["assigned_backend"]
        record["assigned_model"] = assignment["assigned_model"]
        record["pool_index"] = assignment["pool_index"]
        record["pool_tier"] = jobs_by_id[job_id].get("tier")
        record["assignment_source"] = "pool"
    return frozen


def _assignment_errors(state, record, tier, job_id):
    """Validate one recorded pool assignment against its exact frozen slot."""
    errors = []
    prefix = "pool job '%s'" % job_id
    if not isinstance(record, dict):
        return ["%s is missing from state.jobs" % prefix]
    if record.get("status") not in KNOWN_JOB_STATUSES:
        errors.append("%s has unknown status %r" % (prefix, record.get("status")))
    assignment_source = record.get("assignment_source", "pool")
    if assignment_source not in VALID_ASSIGNMENT_SOURCES:
        errors.append("%s has unknown assignment_source %r"
                      % (prefix, assignment_source))
    if tier not in VALID_POOL_TIERS:
        errors.append("%s has unknown frozen tier %r" % (prefix, tier))
    if record.get("pool_tier") != tier:
        errors.append("%s pool_tier does not match manifest tier '%s'" % (prefix, tier))

    backend = record.get("assigned_backend")
    model = record.get("assigned_model")
    if backend not in VALID_CONCRETE_BACKENDS:
        errors.append("%s has unknown concrete backend %r" % (prefix, backend))
    if not isinstance(backend, str) or not backend or backend == "pool":
        errors.append("%s is missing assigned_backend" % prefix)
    if not isinstance(model, str) or not model:
        errors.append("%s is missing assigned_model" % prefix)

    pool_index = record.get("pool_index")
    if (not isinstance(pool_index, int) or isinstance(pool_index, bool)
            or pool_index < 0):
        errors.append("%s has invalid pool_index" % prefix)
        return errors
    members_by_tier = state.get("pool_members") if isinstance(state, dict) else None
    members = members_by_tier.get(tier) if isinstance(members_by_tier, dict) else None
    if not isinstance(members, list) or pool_index >= len(members):
        errors.append("%s pool_index is outside the frozen tier ring" % prefix)
        return errors
    slot = members[pool_index]
    if not isinstance(slot, dict) or slot.get("available") is not True:
        errors.append("%s pool_index does not name an available frozen slot" % prefix)
        return errors
    if slot.get("backend") not in VALID_CONCRETE_BACKENDS:
        errors.append("%s frozen slot has unknown concrete backend %r"
                      % (prefix, slot.get("backend")))
    if (assignment_source != "fallback"
            and (backend != slot.get("backend") or model != slot.get("model"))):
        errors.append("%s backend/model pair does not match its frozen slot" % prefix)
    if (assignment_source == "fallback" and tier in VALID_POOL_TIERS
            and backend in VALID_CONCRETE_BACKENDS
            and isinstance(model, str) and model):
        if "haiku" in model.lower():
            errors.append("%s fallback model must never resolve to Haiku" % prefix)
        else:
            try:
                _resolver_module().resolve(
                    backend=backend,
                    tier=tier,
                    explicit_model=model,
                )
            except ValueError as error:
                errors.append("%s fallback model is invalid: %s" % (prefix, error))
    return errors


def validate_state(state, jobs):
    """Return errors for the narrow load-bearing pool state contract."""
    errors = []
    if not isinstance(state, dict):
        return ["state root must be an object"]
    if not isinstance(jobs, list):
        return ["manifest jobs must be provided as an explicit list"]
    state_jobs = state.get("jobs")
    if not isinstance(state_jobs, dict):
        return ["state.jobs must be an object"]
    errors.extend(_circuit_open_errors(state.get("circuit_open")))
    errors.extend(_transient_state_errors(state))
    pool_members = state.get("pool_members")
    if not isinstance(pool_members, dict):
        errors.append("state.pool_members must be an object")
    else:
        for tier, members in pool_members.items():
            if tier not in VALID_POOL_TIERS:
                errors.append("state.pool_members has unknown frozen tier %r" % tier)
            if not isinstance(members, list):
                errors.append("state.pool_members.%s must be a list" % tier)
                continue
            for index, member in enumerate(members):
                path = "state.pool_members.%s[%d]" % (tier, index)
                if not isinstance(member, dict):
                    errors.append("%s must be an object" % path)
                    continue
                backend = member.get("backend")
                if backend not in VALID_CONCRETE_BACKENDS:
                    errors.append("%s has unknown concrete backend %r" % (path, backend))
                if not isinstance(member.get("available"), bool):
                    errors.append("%s.available must be true/false" % path)
                if member.get("available") is True:
                    model = member.get("model")
                    if not isinstance(model, str) or not model:
                        errors.append("%s.model must be concrete when available" % path)

    for job in jobs:
        if not isinstance(job, dict) or job.get("backend") != "pool":
            continue
        job_id = job.get("id")
        record = state_jobs.get(job_id)
        errors.extend(_assignment_errors(state, record, job.get("tier"), job_id))
    return errors


def resume_assignment(state, job_id):
    """Return the recorded concrete assignment; never derive it from config/counters."""
    circuit_open = state.get("circuit_open") if isinstance(state, dict) else None
    circuit_errors = _circuit_open_errors(circuit_open)
    if circuit_errors:
        raise ValueError("; ".join(circuit_errors))
    transient_errors = _transient_state_errors(state)
    if transient_errors:
        raise ValueError("; ".join(transient_errors))
    jobs = state.get("jobs") if isinstance(state, dict) else None
    record = jobs.get(job_id) if isinstance(jobs, dict) else None
    if not isinstance(record, dict):
        raise ValueError("state has no job '%s'" % job_id)
    tier = record.get("pool_tier")
    errors = _assignment_errors(state, record, tier, job_id)
    if errors:
        raise ValueError("; ".join(errors))
    return {
        "assigned_backend": record["assigned_backend"],
        "assigned_model": record["assigned_model"],
    }


def migrate_legacy_cooldowns(state, now):
    """Explicitly convert legacy backend->timestamp entries exactly once."""
    if not isinstance(state, dict):
        raise ValueError("state root must be an object")
    now_value = _parse_timestamp(now, "now")
    replacement = copy.deepcopy(state)
    cooldowns = replacement.get("cooldowns", {})
    if not isinstance(cooldowns, dict):
        raise ValueError("state.cooldowns must be an object map")
    migrated = {}
    for backend, entry in cooldowns.items():
        if backend not in VALID_CONCRETE_BACKENDS:
            raise ValueError("legacy cooldown uses unknown backend %r" % backend)
        if isinstance(entry, dict):
            migrated[backend] = entry
            continue
        if not isinstance(entry, str):
            raise ValueError("legacy cooldown for %s must be a timestamp string" % backend)
        until_value = _parse_timestamp(entry, "legacy cooldown %s" % backend)
        if until_value < now_value:
            until_value = now_value
        migrated[backend] = {
            "until": _format_timestamp(until_value),
            "reason": "rate_limited",
            "opened_at": _format_timestamp(now_value),
            "opened_by_attempt_id": "legacy:migration:%s" % backend,
            "probe": _idle_probe(),
        }
    replacement["cooldowns"] = migrated
    errors = _transient_state_errors(replacement)
    if errors:
        raise ValueError("; ".join(errors))
    return replacement


def _manifest_job_ids(jobs):
    if not isinstance(jobs, list):
        raise ValueError("manifest jobs must be provided as an explicit list")
    result = set()
    for job in jobs:
        if not isinstance(job, dict):
            raise ValueError("manifest job must be an object")
        job_id = job.get("id")
        if not isinstance(job_id, str) or not job_id:
            raise ValueError("manifest job requires a non-empty id")
        if job_id in result:
            raise ValueError("manifest job ids must be unique")
        result.add(job_id)
    return result


def _current_attempt(record, job_id):
    attempt_id = record.get("attempt_id")
    counter = record.get("attempt_counter")
    if attempt_id is None and counter is None:
        return None, 0
    if (not isinstance(counter, int) or isinstance(counter, bool) or counter < 1
            or attempt_id != "%s:%d" % (job_id, counter)):
        raise ValueError("state job '%s' has invalid persisted attempt identity" % job_id)
    return attempt_id, counter


def _next_attempt(record, job_id):
    _unused, counter = _current_attempt(record, job_id)
    next_counter = counter + 1
    return "%s:%d" % (job_id, next_counter), next_counter


def _validate_result_attempt(state, job_id, intent, batch_id):
    backend = intent.get("backend")
    attempt_id = intent.get("attempt_id")
    if backend not in VALID_CONCRETE_BACKENDS:
        raise ValueError("result backend must be a known concrete backend")
    if not isinstance(attempt_id, str) or not attempt_id:
        raise ValueError("result attempt_id must be non-empty")
    record = state.get("jobs", {}).get(job_id)
    if not isinstance(record, dict):
        raise ValueError("state has no job '%s'" % job_id)
    current_attempt, _unused = _current_attempt(record, job_id)
    if current_attempt != attempt_id:
        raise ValueError("result attempt_id is not the job's current persisted attempt")
    if record.get("assigned_backend") != backend:
        raise ValueError("result backend is not the job's current persisted assignment")
    if record.get("batch_id") != batch_id:
        raise ValueError("result batch_id is not the job's current persisted launch batch")
    return backend, attempt_id


def _canonical_cooldown(backend, reason, until, now, attempt_id):
    if backend not in VALID_CONCRETE_BACKENDS:
        raise ValueError("cooldown backend must be a known concrete backend")
    if reason not in COOLDOWN_REASONS:
        raise ValueError("cooldown reason is not transient")
    if not isinstance(attempt_id, str) or not attempt_id:
        raise ValueError("cooldown attempt_id must be non-empty")
    now_value = _parse_timestamp(now, "now")
    until_value = _parse_timestamp(until, "cooldown_until")
    if until_value < now_value:
        until_value = now_value
    return {
        "until": _format_timestamp(until_value),
        "reason": reason,
        "opened_at": _format_timestamp(now_value),
        "opened_by_attempt_id": attempt_id,
        "probe": _idle_probe(),
    }


def _earliest_timestamp(values):
    parsed = []
    for value in values:
        if value is not None:
            parsed.append((_parse_timestamp(value, "next retry time"), value))
    if not parsed:
        return None
    return _format_timestamp(min(item[0] for item in parsed))


def _prune_network_evidence(rows, batch_id, now_value):
    """Keep only current-batch no-response rows inside the live 60s window."""
    kept = []
    for row in rows:
        if row.get("batch_id") != batch_id:
            continue
        observed = _parse_canonical_timestamp(
            row.get("observed_at"), "network observed_at")
        age = (now_value - observed).total_seconds()
        if 0 <= age <= NETWORK_CORRELATION_SECONDS:
            kept.append(row)
    return kept


def _release_dead_expired_probes(state, now_value, dead_attempt_ids):
    """Reclaim only leases whose owner liveness was explicitly reconciled dead."""
    if dead_attempt_ids is None:
        dead_attempt_ids = []
    if (not isinstance(dead_attempt_ids, list)
            or any(not isinstance(item, str) or not item for item in dead_attempt_ids)):
        raise ValueError("dead_attempt_ids must be a list of non-empty attempt ids")
    dead = set(dead_attempt_ids)
    for entry in state.get("cooldowns", {}).values():
        probe = entry.get("probe")
        if (isinstance(probe, dict) and probe.get("status") == "leased"
                and probe.get("owner_attempt_id") in dead
                and _parse_canonical_timestamp(
                    probe.get("lease_until"), "probe lease_until")
                    <= now_value):
            entry["probe"] = _idle_probe()
    pause = state.get("network_pause")
    if isinstance(pause, dict):
        probe = pause.get("probe")
        if (probe.get("status") == "leased"
                and probe.get("owner_attempt_id") in dead
                and _parse_canonical_timestamp(
                    probe.get("lease_until"), "network probe lease_until")
                    <= now_value):
            pause["probe"] = _idle_probe()


def _lease_probe(entry, job_id, attempt_id, now_value,
                 job_timeout_seconds, grace_seconds):
    timeout = _parse_nonnegative(job_timeout_seconds, "job_timeout_seconds")
    grace = _parse_nonnegative(grace_seconds, "grace_seconds")
    lease_until = now_value + datetime.timedelta(seconds=timeout + grace)
    entry["probe"] = {
        "status": "leased",
        "owner_job_id": job_id,
        "owner_attempt_id": attempt_id,
        "lease_until": _format_timestamp(lease_until),
    }


def _launch_assignment(state, jobs, job_id, batch_id, start_index, now_value,
                       job_timeout_seconds, grace_seconds,
                       exclude_assignment=None, network_probe=False):
    """Perform the sole bounded frozen-ring scan and atomically lease/assign."""
    record = state.get("jobs", {}).get(job_id)
    if not isinstance(record, dict):
        raise ValueError("state has no job '%s'" % job_id)
    tier = record.get("pool_tier")
    members = state.get("pool_members", {}).get(tier)
    if not isinstance(members, list) or not members:
        raise ValueError("state has no frozen pool members for tier '%s'" % tier)
    if exclude_assignment is not None:
        if (not isinstance(exclude_assignment, dict)
                or frozenset(exclude_assignment.keys()) != frozenset(("backend", "model"))
                or exclude_assignment.get("backend") not in VALID_CONCRETE_BACKENDS
                or not isinstance(exclude_assignment.get("model"), str)
                or not exclude_assignment.get("model")):
            raise ValueError("exclude_assignment must be an exact backend/model object")

    attempt_id, attempt_counter = _next_attempt(record, job_id)
    earliest = []
    selected = None
    selected_cooldown = None
    start = start_index % len(members)
    for offset in range(len(members)):
        slot_index = (start + offset) % len(members)
        member = members[slot_index]
        if not isinstance(member, dict):
            raise ValueError("frozen pool member must be an object")
        backend = member.get("backend")
        model = member.get("model")
        if backend not in VALID_CONCRETE_BACKENDS:
            raise ValueError("unknown concrete backend %r in frozen pool" % backend)
        if not isinstance(model, str) or not model:
            raise ValueError("frozen pool member '%s' has no concrete model" % backend)
        breaker = state.get("circuit_open", {}).get(backend)
        excluded = (isinstance(exclude_assignment, dict)
                    and exclude_assignment.get("backend") == backend
                    and exclude_assignment.get("model") == model)
        if (member.get("available") is not True or excluded
                or (isinstance(breaker, dict) and breaker.get("open") is True)):
            continue
        cooldown = state.get("cooldowns", {}).get(backend)
        if isinstance(cooldown, dict):
            until = _parse_canonical_timestamp(
                cooldown.get("until"), "cooldown.until")
            probe = cooldown.get("probe")
            if until > now_value:
                earliest.append(cooldown.get("until"))
                continue
            if probe.get("status") == "leased":
                lease_until = _parse_canonical_timestamp(
                    probe.get("lease_until"), "cooldown probe lease_until")
                if lease_until > now_value:
                    earliest.append(probe.get("lease_until"))
                continue
            selected_cooldown = cooldown
        selected = (slot_index, backend, model)
        break

    if selected is None:
        return None, _earliest_timestamp(earliest)

    slot_index, backend, model = selected
    record["attempt_counter"] = attempt_counter
    record["attempt_id"] = attempt_id
    record["batch_id"] = batch_id
    record["assigned_backend"] = backend
    record["assigned_model"] = model
    record["pool_index"] = slot_index
    record["assignment_source"] = "pool"
    record["status"] = "dispatched"
    if selected_cooldown is not None and not network_probe:
        _lease_probe(selected_cooldown, job_id, attempt_id, now_value,
                     job_timeout_seconds, grace_seconds)
    if network_probe:
        _lease_probe(state["network_pause"], job_id, attempt_id, now_value,
                     job_timeout_seconds, grace_seconds)
    return {
        "assigned_backend": backend,
        "assigned_model": model,
        "pool_index": slot_index,
        "attempt_id": attempt_id,
        "probe_backend": (backend
                          if selected_cooldown is not None and not network_probe
                          else None),
        "network_probe": bool(network_probe),
    }, None


def _normalized_policy_intent(state, job_id, intent):
    """Validate one failure-policy decision against its persisted attempt."""
    if "action" not in intent or "failure_class" not in intent:
        return None
    record = state.get("jobs", {}).get(job_id)
    if not isinstance(record, dict):
        raise ValueError("state has no job '%s'" % job_id)
    attempt_id = intent.get("attempt_id")
    current_attempt, _unused = _current_attempt(record, job_id)
    if not isinstance(attempt_id, str) or not attempt_id:
        raise ValueError("policy intent requires the current non-empty attempt_id")
    if attempt_id != current_attempt:
        raise ValueError("policy attempt_id is not the current persisted attempt")
    failure_class = intent.get("failure_class")
    if not isinstance(failure_class, str) or not failure_class:
        raise ValueError("policy intent requires failure_class")

    cooldown_backend = intent.get("cooldown_backend")
    cooldown_fields = (
        cooldown_backend, intent.get("cooldown_reason"),
        intent.get("cooldown_until"),
    )
    if any(value is not None for value in cooldown_fields) \
            and not all(value is not None for value in cooldown_fields):
        raise ValueError("active cooldown intent requires backend, reason, and until")
    if cooldown_backend is not None \
            and cooldown_backend != record.get("assigned_backend"):
        raise ValueError("cooldown backend is not the current persisted assignment")

    circuit_backend = intent.get("circuit_break_backend")
    if intent.get("circuit_break") is True:
        if circuit_backend != record.get("assigned_backend"):
            raise ValueError("circuit backend is not the current persisted assignment")
        if failure_class not in CIRCUIT_REASONS:
            raise ValueError("permanent circuit intent requires auth or out_of_credits")

    exclude_assignment = intent.get("exclude_assignment")
    if exclude_assignment is not None and (
            not isinstance(exclude_assignment, dict)
            or frozenset(exclude_assignment.keys()) != frozenset(("backend", "model"))
            or exclude_assignment.get("backend") not in VALID_CONCRETE_BACKENDS
            or not isinstance(exclude_assignment.get("model"), str)
            or not exclude_assignment.get("model")):
        raise ValueError("exact exclusion requires concrete backend and model")

    fallback = intent.get("fallback_assignment")
    fallback_valid = False
    if fallback is not None:
        reroute_to = intent.get("reroute_to")
        tier = record.get("pool_tier")
        if (isinstance(fallback, dict)
                and frozenset(fallback.keys()) == frozenset(("backend", "model"))
                and fallback.get("backend") in VALID_CONCRETE_BACKENDS
                and fallback.get("backend") == reroute_to
                and isinstance(fallback.get("model"), str)
                and fallback.get("model")
                and "haiku" not in fallback.get("model").lower()):
            try:
                _resolver_module().resolve(
                    backend=fallback["backend"], tier=tier,
                    explicit_model=fallback["model"],
                )
                fallback_valid = True
            except ValueError:
                fallback_valid = False
    return {
        "record": record,
        "attempt_id": attempt_id,
        "failure_class": failure_class,
        "cooldown_backend": cooldown_backend,
        "exclude_assignment": exclude_assignment,
        "fallback_assignment": fallback if fallback_valid else None,
        "fallback_supplied": fallback is not None,
        "fallback_valid": fallback_valid,
    }


def _launch_fallback_assignment(state, job_id, batch_id, fallback):
    """Persist one prevalidated external assignment after frozen-ring exhaustion."""
    record = state["jobs"][job_id]
    attempt_id, attempt_counter = _next_attempt(record, job_id)
    record["attempt_counter"] = attempt_counter
    record["attempt_id"] = attempt_id
    record["batch_id"] = batch_id
    record["assigned_backend"] = fallback["backend"]
    record["assigned_model"] = fallback["model"]
    record["assignment_source"] = "fallback"
    record["status"] = "dispatched"
    return {
        "assigned_backend": fallback["backend"],
        "assigned_model": fallback["model"],
        "pool_index": record["pool_index"],
        "attempt_id": attempt_id,
        "probe_backend": None,
        "network_probe": False,
    }


def _apply_result(state, job_id, intent, now_value, batch_id):
    backend, attempt_id = _validate_result_attempt(state, job_id, intent, batch_id)
    result = intent.get("result")
    if result not in ("success", "failure"):
        raise ValueError("result intent must be success or failure")
    changed = False

    cooldown = state.get("cooldowns", {}).get(backend)
    cooldown_probe = cooldown.get("probe") if isinstance(cooldown, dict) else None
    exact_cooldown_probe = (isinstance(cooldown_probe, dict)
                            and cooldown_probe.get("status") == "leased"
                            and cooldown_probe.get("owner_job_id") == job_id
                            and cooldown_probe.get("owner_attempt_id") == attempt_id)
    pause = state.get("network_pause")
    pause_probe = pause.get("probe") if isinstance(pause, dict) else None
    exact_network_probe = (isinstance(pause_probe, dict)
                           and pause_probe.get("status") == "leased"
                           and pause_probe.get("owner_job_id") == job_id
                           and pause_probe.get("owner_attempt_id") == attempt_id)

    if result == "success":
        if exact_cooldown_probe:
            del state["cooldowns"][backend]
            changed = True
        if exact_network_probe:
            state.pop("network_pause", None)
            changed = True
        # A completed success vetoes only earlier evidence in the same live
        # batch. Later failures begin a fresh correlation sequence.
        evidence = state.get("network_evidence", [])
        retained = [row for row in evidence if row.get("batch_id") != batch_id]
        if retained != evidence:
            state["network_evidence"] = retained
            changed = True
        successes = _prune_network_evidence(
            state.get("network_successes", []), batch_id, now_value,
        )
        success_row = {
            "backend": backend, "job_id": job_id, "attempt_id": attempt_id,
            "batch_id": batch_id, "observed_at": _format_timestamp(now_value),
        }
        success_key = (backend, attempt_id)
        if not any((item.get("backend"), item.get("attempt_id")) == success_key
                   for item in successes):
            successes.append(success_row)
        state["network_successes"] = successes
        return "complete" if changed else "complete"

    failure_class = intent.get("failure_class")
    if exact_cooldown_probe and failure_class in COOLDOWN_REASONS:
        retry_at = intent.get("retry_at")
        state["cooldowns"][backend] = _canonical_cooldown(
            backend, failure_class, retry_at, _format_timestamp(now_value), attempt_id,
        )
        changed = True
    elif exact_cooldown_probe and failure_class in CIRCUIT_REASONS:
        del state["cooldowns"][backend]
        state.setdefault("circuit_open", {})[backend] = {
            "open": True,
            "reason": failure_class,
            "opened_at": _format_timestamp(now_value),
            "cleared_by": None,
        }
        changed = True

    if failure_class == "network":
        scope = intent.get("network_scope")
        if scope not in ("no_response", "provider_reported"):
            raise ValueError("network failure requires a known network_scope")
        if exact_network_probe:
            if scope == "no_response":
                pause["until"] = _format_timestamp(
                    now_value + datetime.timedelta(seconds=NETWORK_CORRELATION_SECONDS))
                # Preserve the original two-provider evidence that justified
                # the pause. The exact leased real-job probe is the authority
                # for renewal; it does not need to fabricate a second outage
                # observation in a later correlation window.
                pause["probe"] = _idle_probe()
            else:
                state.pop("network_pause", None)
            return "state_updated"
        if scope == "provider_reported":
            return "state_updated"
        evidence = _prune_network_evidence(
            state.get("network_evidence", []), batch_id, now_value,
        )
        successes = _prune_network_evidence(
            state.get("network_successes", []), batch_id, now_value,
        )
        state["network_successes"] = successes
        row = {
            "backend": backend, "job_id": job_id, "attempt_id": attempt_id,
            "batch_id": batch_id, "observed_at": _format_timestamp(now_value),
        }
        dedupe = (backend, attempt_id)
        if not any((item.get("backend"), item.get("attempt_id")) == dedupe
                   for item in evidence):
            evidence.append(row)
        state["network_evidence"] = evidence
        if (len({item["backend"] for item in evidence}) >= 2
                and not successes):
            state["network_pause"] = {
                "opened_at": _format_timestamp(now_value),
                "until": _format_timestamp(
                    now_value + datetime.timedelta(seconds=NETWORK_CORRELATION_SECONDS)),
                "evidence": copy.deepcopy(evidence),
                "probe": _idle_probe(),
            }
            state["network_evidence"] = []
            return "network_paused"
    return "state_updated" if changed or result == "failure" else "complete"


def transition_state(state, jobs, job_id, intent, now, batch_id,
                     job_timeout_seconds, grace_seconds):
    """Validate, mutate, bounded-scan, and return one atomic launch decision."""
    if not isinstance(state, dict) or not isinstance(intent, dict):
        raise ValueError("state and intent must be objects")
    if not isinstance(job_id, str) or not job_id:
        raise ValueError("job_id must be non-empty")
    if not isinstance(batch_id, str) or not batch_id:
        raise ValueError("batch_id must be non-empty")
    if job_id not in _manifest_job_ids(jobs):
        raise ValueError("job_id is not present in manifest jobs")
    now_value = _parse_timestamp(now, "now")
    _parse_nonnegative(job_timeout_seconds, "job_timeout_seconds")
    _parse_nonnegative(grace_seconds, "grace_seconds")
    current_errors = validate_state(state, jobs)
    if current_errors:
        raise ValueError("; ".join(current_errors))
    replacement = copy.deepcopy(state)
    replacement.setdefault("cooldowns", {})
    _release_dead_expired_probes(
        replacement, now_value, intent.get("dead_attempt_ids", []),
    )

    policy_intent = _normalized_policy_intent(replacement, job_id, intent)

    # A normalized policy decision carries the completed failure fact and its
    # next action together. Apply the fact first, then continue through the
    # same atomic mutation/selection transaction. Standalone result events keep
    # their original result-only return contract.
    if intent.get("result") is not None:
        action = _apply_result(replacement, job_id, intent, now_value, batch_id)
        if policy_intent is None:
            errors = validate_state(replacement, jobs)
            if errors:
                raise ValueError("; ".join(errors))
            return {
                "state": replacement, "action": action,
                "assignment": None, "next_retry_at": None,
            }

    cooldown_backend = intent.get("cooldown_backend")
    if cooldown_backend is not None:
        record = replacement.get("jobs", {}).get(job_id)
        current_attempt, _unused = _current_attempt(record, job_id)
        attempt_id = intent.get("attempt_id")
        if current_attempt != attempt_id:
            raise ValueError("cooldown attempt_id is not the current persisted attempt")
        backend = cooldown_backend
        if record.get("assigned_backend") != backend:
            raise ValueError("cooldown backend is not the current persisted assignment")
        replacement["cooldowns"][backend] = _canonical_cooldown(
            backend, intent.get("cooldown_reason"), intent.get("cooldown_until"),
            _format_timestamp(now_value), attempt_id,
        )

    if intent.get("circuit_break") is True:
        replacement.setdefault("circuit_open", {})[
            intent.get("circuit_break_backend")
        ] = {
            "open": True,
            "reason": intent.get("failure_class"),
            "opened_at": _format_timestamp(now_value),
            "cleared_by": None,
        }

    wants_launch = (intent.get("launch") is True
                    or intent.get("advance_pool") is True
                    or (policy_intent is not None and intent.get("action") == "retry"))
    if not wants_launch:
        errors = validate_state(replacement, jobs)
        if errors:
            raise ValueError("; ".join(errors))
        halt = policy_intent is not None and intent.get("action") == "halt"
        retry_at = intent.get("next_retry_at") if halt else None
        pause = replacement.get("network_pause")
        if isinstance(pause, dict):
            retry_at = pause.get("until")
        return {
            "state": replacement, "action": ("halt" if halt else "state_updated"),
            "assignment": None, "next_retry_at": retry_at,
        }

    pause = replacement.get("network_pause")
    network_probe = False
    if isinstance(pause, dict):
        pause_until = _parse_canonical_timestamp(
            pause.get("until"), "network_pause.until")
        probe = pause.get("probe")
        if pause_until > now_value:
            return {
                "state": replacement, "action": "halt", "assignment": None,
                "next_retry_at": _format_timestamp(pause_until),
            }
        if probe.get("status") == "leased":
            lease_until = _parse_canonical_timestamp(
                probe.get("lease_until"), "network probe lease_until")
            return {
                "state": replacement, "action": "halt", "assignment": None,
                "next_retry_at": (probe.get("lease_until")
                                  if lease_until > now_value else None),
            }
        network_probe = True

    record = replacement.get("jobs", {}).get(job_id)
    start_index = record.get("pool_index")
    if not isinstance(start_index, int) or isinstance(start_index, bool):
        raise ValueError("job has no valid current pool_index")
    if intent.get("advance_pool") is True:
        start_index += 1
    assignment, next_retry_at = _launch_assignment(
        replacement, jobs, job_id, batch_id, start_index, now_value,
        job_timeout_seconds, grace_seconds,
        exclude_assignment=(policy_intent.get("exclude_assignment")
                            if policy_intent is not None
                            else intent.get("exclude_assignment")),
        network_probe=network_probe,
    )
    if (assignment is None and policy_intent is not None
            and policy_intent.get("fallback_valid")):
        assignment = _launch_fallback_assignment(
            replacement, job_id, batch_id,
            policy_intent["fallback_assignment"],
        )
        next_retry_at = None
    action = "launch" if assignment is not None else "halt"
    errors = validate_state(replacement, jobs)
    if errors:
        raise ValueError("; ".join(errors))
    return {
        "state": replacement, "action": action,
        "assignment": assignment, "next_retry_at": next_retry_at,
    }


def clear_cooldown(state, jobs, backend, now):
    """Remove one known transient cooldown without touching permanent circuits."""
    if backend not in VALID_CONCRETE_BACKENDS:
        raise ValueError("clear-cooldown requires a known concrete backend")
    _parse_timestamp(now, "now")
    current_errors = validate_state(state, jobs)
    if current_errors:
        raise ValueError("; ".join(current_errors))
    replacement = copy.deepcopy(state)
    cooldowns = replacement.setdefault("cooldowns", {})
    cooldowns.pop(backend, None)
    errors = validate_state(replacement, jobs)
    if errors:
        raise ValueError("; ".join(errors))
    return replacement


def handle_request(action, payload, env=None, which=None):
    """Pure request dispatcher used by the stdin/stdout JSON CLI."""
    if not isinstance(payload, dict):
        raise ValueError("request must be a JSON object")
    if action == "freeze":
        return freeze_assignments(
            payload.get("state", {}), payload.get("jobs", []),
            payload.get("pools", {}), payload.get("stance", "balanced"),
            payload.get("config_models", {}), env=env, which=which,
        )
    if action == "validate":
        errors = validate_state(payload.get("state"), payload.get("jobs"))
        return {"valid": not errors, "errors": errors}
    if action == "resume":
        return resume_assignment(payload.get("state"), payload.get("job_id"))
    if action == "select":
        return select_frozen_member(
            payload.get("state"), payload.get("tier"), payload.get("index"),
            now=payload.get("now"),
            exclude_assignment=payload.get("exclude_assignment"),
        )
    if action == "transition":
        return transition_state(
            payload.get("state"), payload.get("jobs"), payload.get("job_id"),
            payload.get("intent"), payload.get("now"), payload.get("batch_id"),
            payload.get("job_timeout_seconds"), payload.get("grace_seconds"),
        )
    if action == "clear-cooldown":
        return clear_cooldown(
            payload.get("state"), payload.get("jobs"), payload.get("backend"),
            payload.get("now"),
        )
    raise ValueError("unknown action '%s'" % action)


def _selftest():
    failures = []
    checked = [0]

    def expect(name, condition):
        checked[0] += 1
        print(("  ok   - " if condition else "  FAIL - ") + name)
        if not condition:
            failures.append(name)

    def function(name):
        candidate = globals().get(name)
        return candidate if callable(candidate) else None

    def raises_value(fn):
        try:
            fn()
            return False
        except ValueError:
            return True

    def value_or_none(fn):
        try:
            return fn()
        except ValueError:
            return None

    expand = function("expand_members")
    ordinals = function("manifest_pool_ordinals")
    freeze_members = function("freeze_pool_members")
    select = function("select_frozen_member")
    freeze_assignments = function("freeze_assignments")
    validate = function("validate_state")
    resume = function("resume_assignment")
    handle = function("handle_request")

    expanded = expand([
        {"backend": "codex", "weight": 2},
        {"backend": "claude", "weight": 1},
    ]) if expand else None
    expect("weights expand into consecutive A,A,B slots", expanded == [
        {"backend": "codex", "weight": 1},
        {"backend": "codex", "weight": 1},
        {"backend": "claude", "weight": 1},
    ])
    expect("expansion rejects a member weight above the deterministic cap",
           bool(expand) and raises_value(lambda: expand([
               {"backend": "codex", "weight": 101},
           ])))
    expect("expansion rejects aggregate slots above the deterministic cap",
           bool(expand) and raises_value(lambda: expand([
               {"backend": "codex", "weight": 100},
               {"backend": "claude", "weight": 100},
               {"backend": "cursor", "weight": 100},
           ])))

    manifest_jobs = [
        {"id": "light-1", "backend": "pool", "tier": "light"},
        {"id": "concrete", "backend": "codex", "tier": "light"},
        {"id": "standard-1", "backend": "pool", "tier": "standard"},
        {"id": "light-2", "backend": "pool", "tier": "light"},
        {"id": "standard-2", "backend": "pool", "tier": "standard"},
    ]
    ordinal_map = ordinals(manifest_jobs) if ordinals else None
    expect("manifest order assigns independent ordinals per tier", ordinal_map == {
        "light-1": 0, "standard-1": 0, "light-2": 1, "standard-2": 1,
    })

    availability_calls = []

    def first_which(name):
        availability_calls.append(name)
        return "/usr/bin/codex" if name == "codex" else None

    availability_pools = {
        "balanced": {
            "light": [
                {"backend": "codex", "model": "gpt-pinned", "weight": 1},
                {"backend": "zai", "model": "glm-pinned", "weight": 1},
            ]
        }
    }
    frozen = freeze_members(
        {}, availability_pools, "balanced", {}, env={}, which=first_which,
    ) if freeze_members else None
    expect("codex PATH and zai env availability are captured at freeze", frozen == {
        "circuit_open": {},
        "pool_members": {
            "light": [
                {"backend": "codex", "model": "gpt-pinned", "available": True},
                {"backend": "zai", "model": "glm-pinned", "available": False},
            ]
        }
    } and availability_calls == ["codex"])

    def later_which(name):
        availability_calls.append("later:" + name)
        return None

    refrozen = freeze_members(
        frozen, availability_pools, "balanced", {},
        env={"ZAI_API_KEY": "now-present"}, which=later_which,
    ) if freeze_members and isinstance(frozen, dict) else None
    expect("availability is evaluated only once and retained on re-freeze",
           refrozen == frozen and availability_calls == ["codex"])

    slot_state = {
        "pool_members": {
            "light": [
                {"backend": "codex", "model": "a", "available": True},
                {"backend": "claude", "model": "b", "available": True},
                {"backend": "cursor", "model": "c", "available": True},
            ]
        },
        "circuit_open": {
            "claude": {
                "open": True,
                "reason": "out_of_credits",
                "opened_at": "2026-08-01T00:00:00Z",
                "cleared_by": None,
            },
        },
    }
    selected = [select(slot_state, "light", i) for i in range(3)] if select else []
    expect("unavailable/open slot advances without resizing the frozen ring", [
        item.get("assigned_backend") for item in selected
    ] == ["codex", "cursor", "cursor"] and [
        item.get("pool_index") for item in selected
    ] == [0, 2, 2])

    pools = {
        "balanced": {
            "light": [
                {"backend": "codex", "weight": 2},
                {"backend": "claude", "weight": 1},
            ],
            "standard": [{"backend": "codex", "weight": 1}],
        }
    }
    state = {
        "jobs": {
            "light-1": {"status": "pending"},
            "standard-1": {"status": "pending"},
            "light-2": {"status": "pending"},
            "standard-2": {"status": "pending"},
        }
    }
    assigned = freeze_assignments(
        state, manifest_jobs, pools, "balanced", {},
        env={}, which=lambda name: "/usr/bin/codex",
    ) if freeze_assignments else None
    expect("freeze persists concrete backend and model on every pool job",
           isinstance(assigned, dict) and [
               assigned.get("jobs", {}).get(job_id, {}).get("assigned_backend")
               for job_id in ("light-1", "light-2", "standard-1", "standard-2")
           ] == ["codex", "codex", "codex", "codex"]
           and all(
               assigned.get("jobs", {}).get(job_id, {}).get("assigned_model")
               for job_id in ("light-1", "light-2", "standard-1", "standard-2")
           ))
    expect("freeze records each pool tier for standalone resume validation",
           isinstance(assigned, dict) and [
               assigned.get("jobs", {}).get(job_id, {}).get("pool_tier")
               for job_id in ("light-1", "light-2", "standard-1", "standard-2")
           ] == ["light", "light", "standard", "standard"])
    expect("freeze labels ring assignments with assignment_source pool",
           isinstance(assigned, dict) and all(
               assigned.get("jobs", {}).get(job_id, {}).get("assignment_source") == "pool"
               for job_id in ("light-1", "light-2", "standard-1", "standard-2")
           ))

    before_edit = json.loads(json.dumps(assigned)) if isinstance(assigned, dict) else None
    edited_pools = {
        "balanced": {
            "light": [{"backend": "cursor", "model": "changed", "weight": 1}],
            "standard": [{"backend": "cursor", "model": "changed", "weight": 1}],
        }
    }
    after_edit = freeze_assignments(
        assigned, manifest_jobs, edited_pools, "balanced",
        {"balanced": {"codex": {"light": "changed-too"}}},
        env={}, which=lambda name: None,
    ) if freeze_assignments and isinstance(assigned, dict) else None
    expect("config edits after freeze cannot alter members or assignments",
           isinstance(after_edit, dict) and after_edit == before_edit)

    if isinstance(assigned, dict):
        assigned.get("jobs", {}).get("light-1", {})["status"] = "dispatched"
    valid_errors = validate(assigned, manifest_jobs) if validate and assigned else None
    expect("frozen assignment state validates", valid_errors == [])

    canonical_breaker = {
        "open": True,
        "reason": "out_of_credits",
        "opened_at": "2026-08-01T00:00:00Z",
        "cleared_by": None,
    }
    bad_circuit_cases = [
        ("bare boolean", {"codex": True}),
        ("pool routing token key", {"pool": dict(canonical_breaker)}),
        ("unknown backend key", {"mystery": dict(canonical_breaker)}),
        ("missing canonical field", {"codex": {
            "open": True, "reason": "auth", "opened_at": "now",
        }}),
        ("non-bool open", {"codex": {
            "open": 1, "reason": "auth", "opened_at": "now", "cleared_by": None,
        }}),
        ("invalid open reason", {"codex": {
            "open": True, "reason": "network", "opened_at": "now", "cleared_by": None,
        }}),
        ("empty opened_at", {"codex": {
            "open": True, "reason": "auth", "opened_at": "", "cleared_by": None,
        }}),
        ("naive opened_at", {"codex": dict(
            canonical_breaker, opened_at="2026-08-01T00:00:00")}),
        ("non-canonical UTC offset opened_at", {"codex": dict(
            canonical_breaker, opened_at="2026-08-01T02:00:00+02:00")}),
        ("invalid cleared_by", {"codex": {
            "open": False, "reason": "auth", "opened_at": "now", "cleared_by": "manual",
        }}),
        ("extra field", {"codex": dict(canonical_breaker, extra=True)}),
        ("open breaker already cleared", {"codex": dict(canonical_breaker, cleared_by="probe")}),
    ]
    for circuit_name, circuit_value in bad_circuit_cases:
        bad_circuit_state = json.loads(json.dumps(assigned))
        bad_circuit_state["circuit_open"] = circuit_value
        circuit_errors = validate(bad_circuit_state, manifest_jobs) if validate else []
        expect("circuit_open rejects %s" % circuit_name,
               any("circuit_open" in error for error in circuit_errors))

    closed_circuit_state = json.loads(json.dumps(assigned))
    closed_circuit_state["circuit_open"] = {"codex": {
        "open": False,
        "reason": "auth",
        "opened_at": "2026-08-01T00:00:00Z",
        "cleared_by": "reauth",
    }}
    expect("canonical reconciled circuit entry validates",
           validate(closed_circuit_state, manifest_jobs) == [] if validate else False)

    incompatible_circuits = [
        ("auth cleared by top_up", "auth", "top_up"),
        ("auth cleared by probe", "auth", "probe"),
        ("credits cleared by reauth", "out_of_credits", "reauth"),
        ("closed breaker with null cleared_by", "out_of_credits", None),
    ]
    for circuit_name, circuit_reason, circuit_cleared_by in incompatible_circuits:
        incompatible_state = json.loads(json.dumps(assigned))
        incompatible_state["circuit_open"] = {"codex": {
            "open": False,
            "reason": circuit_reason,
            "opened_at": "2026-08-01T00:00:00Z",
            "cleared_by": circuit_cleared_by,
        }}
        incompatible_errors = validate(incompatible_state, manifest_jobs) if validate else []
        expect("circuit_open rejects %s" % circuit_name,
               any("circuit_open" in error for error in incompatible_errors))

    for token in ("top_up", "probe"):
        reconciled_state = json.loads(json.dumps(assigned))
        reconciled_state["circuit_open"] = {"codex": {
            "open": False,
            "reason": "out_of_credits",
            "opened_at": "2026-08-01T00:00:00Z",
            "cleared_by": token,
        }}
        expect("out_of_credits may reconcile via %s" % token,
               validate(reconciled_state, manifest_jobs) == [] if validate else False)

    bare_bool_state = json.loads(json.dumps(assigned))
    bare_bool_state["circuit_open"] = {"codex": True}
    expect("resume validates circuit_open before returning assignment",
           bool(resume) and raises_value(lambda: resume(bare_bool_state, "light-1")))
    expect("selection validates circuit_open before choosing a slot",
           bool(select) and raises_value(lambda: select(bare_bool_state, "light", 0)))
    expect("assignment freeze validates circuit_open before preserving assignments",
           bool(freeze_assignments) and raises_value(lambda: freeze_assignments(
               bare_bool_state, manifest_jobs, pools, "balanced", {},
               env={}, which=lambda name: "/usr/bin/codex",
           )))

    fallback_state = json.loads(json.dumps(assigned)) if isinstance(assigned, dict) else {}
    fallback_record = fallback_state.get("jobs", {}).get("light-1", {})
    fallback_record["status"] = "dispatched"
    fallback_record["assignment_source"] = "fallback"
    fallback_record["assigned_backend"] = "cursor"
    fallback_record["assigned_model"] = "auto"
    fallback_errors = validate(fallback_state, manifest_jobs) if validate else ["missing validator"]
    expect("explicit external fallback may differ from its originating frozen slot",
           fallback_errors == [])

    implicit_external = json.loads(json.dumps(fallback_state))
    implicit_external["jobs"]["light-1"].pop("assignment_source", None)
    implicit_errors = validate(implicit_external, manifest_jobs) if validate else []
    expect("external assignment without explicit fallback source is rejected",
           any("frozen slot" in error for error in implicit_errors))

    bad_source = json.loads(json.dumps(assigned)) if isinstance(assigned, dict) else {}
    bad_source["jobs"]["light-1"]["assignment_source"] = "rerouted-somehow"
    bad_source_errors = validate(bad_source, manifest_jobs) if validate else []
    expect("unknown assignment_source fails closed",
           any("assignment_source" in error for error in bad_source_errors))

    unknown_fallback = json.loads(json.dumps(fallback_state))
    unknown_fallback["jobs"]["light-1"]["assigned_backend"] = "mystery"
    unknown_fallback_errors = validate(unknown_fallback, manifest_jobs) if validate else []
    expect("fallback still requires a known concrete backend token",
           any("unknown concrete backend" in error for error in unknown_fallback_errors))

    contextless_fallback = json.loads(json.dumps(fallback_state))
    contextless_fallback["jobs"]["light-1"].pop("pool_index", None)
    contextless_errors = validate(contextless_fallback, manifest_jobs) if validate else []
    expect("fallback requires its originating pool index context",
           any("pool_index" in error for error in contextless_errors))

    fallback_haiku = json.loads(json.dumps(fallback_state))
    fallback_haiku["jobs"]["light-1"]["assigned_backend"] = "claude"
    fallback_haiku["jobs"]["light-1"]["assigned_model"] = "claude-haiku"
    fallback_haiku_errors = validate(fallback_haiku, manifest_jobs) if validate else []
    expect("fallback model validation rejects haiku",
           any("fallback model" in error for error in fallback_haiku_errors))

    fallback_bad_opencode = json.loads(json.dumps(fallback_state))
    fallback_bad_opencode["jobs"]["light-1"]["assigned_backend"] = "opencode"
    fallback_bad_opencode["jobs"]["light-1"]["assigned_model"] = "bare-model"
    fallback_opencode_errors = validate(fallback_bad_opencode, manifest_jobs) if validate else []
    expect("fallback model validation preserves opencode provider/model shape",
           any("fallback model" in error for error in fallback_opencode_errors))

    missing_index = json.loads(json.dumps(assigned)) if isinstance(assigned, dict) else {}
    missing_index.get("jobs", {}).get("light-1", {}).pop("pool_index", None)
    index_errors = validate(missing_index, manifest_jobs) if validate else []
    expect("pool assignment missing pool_index is rejected",
           any("pool_index" in error for error in index_errors))

    bool_index = json.loads(json.dumps(assigned)) if isinstance(assigned, dict) else {}
    bool_index.get("jobs", {}).get("light-1", {})["pool_index"] = True
    bool_index_errors = validate(bool_index, manifest_jobs) if validate else []
    expect("bool pool_index is rejected rather than accepted as integer",
           any("pool_index" in error for error in bool_index_errors))

    stale_backend = json.loads(json.dumps(assigned)) if isinstance(assigned, dict) else {}
    stale_backend.get("jobs", {}).get("light-1", {})["assigned_backend"] = "cursor"
    stale_backend_errors = validate(stale_backend, manifest_jobs) if validate else []
    expect("assigned backend must match its frozen expanded slot",
           any("frozen slot" in error for error in stale_backend_errors))

    stale_model = json.loads(json.dumps(assigned)) if isinstance(assigned, dict) else {}
    stale_model.get("jobs", {}).get("light-1", {})["assigned_model"] = "stale-model"
    stale_model_errors = validate(stale_model, manifest_jobs) if validate else []
    expect("assigned model must match its frozen resolved slot",
           any("frozen slot" in error for error in stale_model_errors))

    unknown_status = json.loads(json.dumps(assigned)) if isinstance(assigned, dict) else {}
    unknown_status.get("jobs", {}).get("light-1", {})["status"] = "mystery"
    status_errors = validate(unknown_status, manifest_jobs) if validate else []
    expect("unknown pool job status fails closed",
           any("status" in error for error in status_errors))

    turbo_state = json.loads(json.dumps(assigned)) if isinstance(assigned, dict) else {}
    turbo_state["pool_members"]["turbo"] = turbo_state["pool_members"].pop("light")
    turbo_state["jobs"]["light-1"]["pool_tier"] = "turbo"
    turbo_jobs = json.loads(json.dumps(manifest_jobs))
    turbo_jobs[0]["tier"] = "turbo"
    turbo_errors = validate(turbo_state, turbo_jobs) if validate else []
    expect("internally coherent unknown frozen tier is rejected",
           any("unknown frozen tier" in error for error in turbo_errors))

    mystery_state = json.loads(json.dumps(assigned)) if isinstance(assigned, dict) else {}
    mystery_slot = mystery_state["pool_members"]["light"][0]
    mystery_slot["backend"] = "mystery"
    mystery_state["jobs"]["light-1"]["assigned_backend"] = "mystery"
    mystery_errors = validate(mystery_state, manifest_jobs) if validate else []
    expect("internally coherent unknown concrete backend is rejected",
           any("unknown concrete backend" in error for error in mystery_errors))

    missing_backend = json.loads(json.dumps(assigned)) if isinstance(assigned, dict) else {}
    missing_backend.get("jobs", {}).get("light-1", {}).pop("assigned_backend", None)
    backend_errors = validate(missing_backend, manifest_jobs) if validate else []
    expect("dispatched pool job missing assigned_backend is rejected",
           any("assigned_backend" in error for error in backend_errors))

    missing_model = json.loads(json.dumps(assigned)) if isinstance(assigned, dict) else {}
    missing_model.get("jobs", {}).get("light-1", {}).pop("assigned_model", None)
    model_errors = validate(missing_model, manifest_jobs) if validate else []
    expect("dispatched pool job missing assigned_model is rejected",
           any("assigned_model" in error for error in model_errors))

    done_missing_model = json.loads(json.dumps(assigned)) if isinstance(assigned, dict) else {}
    done_missing_model.get("jobs", {}).get("light-1", {})["status"] = "done"
    done_missing_model.get("jobs", {}).get("light-1", {}).pop("assigned_model", None)
    done_errors = validate(done_missing_model, manifest_jobs) if validate else []
    expect("done pool job still requires its recorded assigned_model",
           any("assigned_model" in error for error in done_errors))

    if isinstance(assigned, dict):
        assigned.pop("pool_cursor", None)
    resumed = resume(assigned, "light-1") if resume and assigned else None
    expect("resume returns the recorded concrete assignment without a counter", resumed == {
        "assigned_backend": "codex",
        "assigned_model": "gpt-5.6-luna",
    })

    corrupt_resume = json.loads(json.dumps(assigned)) if isinstance(assigned, dict) else {}
    corrupt_resume.get("jobs", {}).get("light-1", {})["assigned_model"] = "stale-model"
    expect("resume rejects a pair that does not match the frozen slot",
           bool(resume) and raises_value(lambda: resume(corrupt_resume, "light-1")))
    missing_index_resume = json.loads(json.dumps(assigned)) if isinstance(assigned, dict) else {}
    missing_index_resume.get("jobs", {}).get("light-1", {}).pop("pool_index", None)
    expect("resume rejects a missing pool_index",
           bool(resume) and raises_value(lambda: resume(missing_index_resume, "light-1")))
    expect("resume returns a validated recorded external fallback without re-deriving",
           bool(resume) and value_or_none(
               lambda: resume(fallback_state, "light-1")
           ) == {
               "assigned_backend": "cursor", "assigned_model": "auto",
           })
    expect("resume rejects fallback haiku before returning it",
           bool(resume) and raises_value(lambda: resume(fallback_haiku, "light-1")))
    expect("resume rejects malformed opencode fallback before returning it",
           bool(resume) and raises_value(
               lambda: resume(fallback_bad_opencode, "light-1")
           ))
    expect("standalone resume rejects unknown frozen tier vocabulary",
           bool(resume) and raises_value(lambda: resume(turbo_state, "light-1")))
    expect("standalone resume rejects unknown concrete backend vocabulary",
           bool(resume) and raises_value(lambda: resume(mystery_state, "light-1")))

    handled = handle("resume", {"state": assigned, "job_id": "light-1"}) \
        if handle and assigned else None
    expect("request handler exposes resume for the JSON CLI",
           isinstance(handled, dict) and handled == resumed)
    missing_jobs_result = handle("validate", {"state": assigned}) \
        if handle and assigned else None
    expect("validate request missing jobs fails closed",
           isinstance(missing_jobs_result, dict)
           and missing_jobs_result.get("valid") is False
           and any("jobs" in error for error in missing_jobs_result.get("errors", [])))
    nonlist_jobs_result = handle(
        "validate", {"state": assigned, "jobs": {"not": "a list"}}
    ) if handle and assigned else None
    expect("validate request with non-list jobs fails closed",
           isinstance(nonlist_jobs_result, dict)
           and nonlist_jobs_result.get("valid") is False
           and any("jobs" in error for error in nonlist_jobs_result.get("errors", [])))

    # PR3 canonical cooldown/network transition contract. These fixtures are
    # deliberately literal: each expectation names a state-machine mutation
    # whose removal or broadening must fail the selftest.
    transition = function("transition_state")
    migrate = function("migrate_legacy_cooldowns")
    clear = function("clear_cooldown")
    route_jobs = [
        {"id": "job-a", "backend": "pool", "tier": "light"},
        {"id": "job-b", "backend": "pool", "tier": "light"},
    ]
    route_state = {
        "jobs": {
            "job-a": {
                "status": "failed", "assigned_backend": "codex",
                "assigned_model": "model-a", "pool_index": 0,
                "pool_tier": "light", "assignment_source": "pool",
            },
            "job-b": {
                "status": "failed", "assigned_backend": "claude",
                "assigned_model": "model-b", "pool_index": 1,
                "pool_tier": "light", "assignment_source": "pool",
            },
        },
        "pool_members": {"light": [
            {"backend": "codex", "model": "model-a", "available": True},
            {"backend": "claude", "model": "model-b", "available": True},
            {"backend": "zai", "model": "model-c", "available": True},
        ]},
        "circuit_open": {},
        "cooldowns": {},
    }
    idle_probe = {
        "status": "idle", "owner_job_id": None,
        "owner_attempt_id": None, "lease_until": None,
    }
    canonical_cooldown = {
        "until": "2026-08-01T07:30:00Z",
        "reason": "rate_limited",
        "opened_at": "2026-08-01T07:20:00Z",
        "opened_by_attempt_id": "job-a:1",
        "probe": dict(idle_probe),
    }
    canonical_state = json.loads(json.dumps(route_state))
    canonical_state["cooldowns"] = {"codex": canonical_cooldown}
    expect("canonical cooldown object validates",
           bool(validate) and validate(canonical_state, route_jobs) == [])

    null_cooldowns = json.loads(json.dumps(route_state))
    null_cooldowns["cooldowns"] = None
    null_evidence = json.loads(json.dumps(route_state))
    null_evidence["network_evidence"] = None
    missing_legacy_transient = json.loads(json.dumps(route_state))
    missing_legacy_transient.pop("cooldowns", None)
    missing_legacy_transient.pop("network_evidence", None)
    expect("present null cooldowns fail closed while a missing legacy key remains valid",
           any("cooldowns" in error for error in validate(
               null_cooldowns, route_jobs))
           and validate(missing_legacy_transient, route_jobs) == [])
    expect("present null network evidence fails closed",
           any("network_evidence" in error for error in validate(
               null_evidence, route_jobs)))

    offset_cooldown_state = json.loads(json.dumps(canonical_state))
    offset_cooldown_state["cooldowns"]["codex"]["until"] = \
        "2026-08-01T09:30:00+02:00"
    offset_errors = validate(offset_cooldown_state, route_jobs) if validate else []
    expect("persisted cooldown timestamps require normalized terminal Z",
           any("canonical UTC" in error for error in offset_errors))

    bare_cooldown_state = json.loads(json.dumps(route_state))
    bare_cooldown_state["cooldowns"] = {"codex": "2026-08-01T07:30:00Z"}
    bare_cooldown_errors = validate(bare_cooldown_state, route_jobs) \
        if validate else []
    expect("new bare-string cooldown fails closed",
           any("cooldown" in error for error in bare_cooldown_errors))
    migrated = value_or_none(lambda: migrate(
        bare_cooldown_state, "2026-08-01T07:20:00Z"
    )) if migrate else None
    expect("explicit legacy migration writes canonical cooldown once",
           isinstance(migrated, dict)
           and isinstance(migrated.get("cooldowns", {}).get("codex"), dict)
           and validate(migrated, route_jobs) == [])

    malformed_cooldown = json.loads(json.dumps(canonical_state))
    malformed_cooldown["cooldowns"]["codex"]["probe"]["owner_job_id"] = "job-a"
    malformed_errors = validate(malformed_cooldown, route_jobs) if validate else []
    expect("idle probe rejects a non-null owner",
           any("probe" in error for error in malformed_errors))

    two_cooling = json.loads(json.dumps(route_state))
    two_cooling["cooldowns"] = {
        "codex": dict(canonical_cooldown),
        "claude": dict(canonical_cooldown,
                       opened_by_attempt_id="job-b:1"),
    }
    advanced = value_or_none(lambda: transition(
        two_cooling, route_jobs, "job-a", {"advance_pool": True},
        "2026-08-01T07:21:00Z", "batch-1", 300, 3,
    )) if transition else None
    expect("two cooling providers select the healthy frozen slot",
           isinstance(advanced, dict)
           and advanced.get("action") == "launch"
           and advanced.get("assignment", {}).get("assigned_backend") == "zai"
           and advanced.get("assignment", {}).get("pool_index") == 2
           and len(advanced.get("state", {}).get("pool_members", {}).get("light", [])) == 3)

    exact_excluded = value_or_none(lambda: transition(
        route_state, route_jobs, "job-a", {
            "advance_pool": True,
            "exclude_assignment": {"backend": "claude", "model": "model-b"},
        }, "2026-08-01T07:21:00Z", "batch-1", 300, 3,
    )) if transition else None
    expect("exact backend-model exclusion skips only that frozen slot",
           isinstance(exact_excluded, dict)
           and exact_excluded.get("assignment", {}).get("assigned_backend") == "zai")

    all_cooling = json.loads(json.dumps(route_state))
    all_cooling["cooldowns"] = {
        "codex": dict(canonical_cooldown, until="2026-08-01T07:29:00Z"),
        "claude": dict(canonical_cooldown, until="2026-08-01T07:27:00Z",
                       opened_by_attempt_id="job-b:1"),
        "zai": dict(canonical_cooldown, until="2026-08-01T07:28:00Z",
                    opened_by_attempt_id="job-a:2"),
    }
    halted = value_or_none(lambda: transition(
        all_cooling, route_jobs, "job-a", {"advance_pool": True},
        "2026-08-01T07:21:00Z", "batch-1", 300, 3,
    )) if transition else None
    expect("one bounded scan halts with earliest absolute retry",
           isinstance(halted, dict) and halted.get("action") == "halt"
           and halted.get("assignment") is None
           and halted.get("next_retry_at") == "2026-08-01T07:27:00Z")

    first_launch = value_or_none(lambda: transition(
        route_state, route_jobs, "job-a", {"launch": True},
        "2026-08-01T07:21:00Z", "batch-1", 300, 3,
    )) if transition else None
    second_launch = value_or_none(lambda: transition(
        first_launch["state"], route_jobs, "job-a", {"launch": True},
        "2026-08-01T07:22:00Z", "batch-1", 300, 3,
    )) if isinstance(first_launch, dict) and transition else None
    expect("each persisted launch receives a unique monotonic attempt id",
           isinstance(second_launch, dict)
           and first_launch.get("assignment", {}).get("attempt_id") == "job-a:1"
           and second_launch.get("assignment", {}).get("attempt_id") == "job-a:2"
           and second_launch.get("state", {}).get("jobs", {}).get("job-a", {}).get(
               "attempt_id") == "job-a:2")
    expect("launch persists the exact current batch beside its attempt",
           isinstance(first_launch, dict)
           and first_launch.get("state", {}).get("jobs", {}).get(
               "job-a", {}).get("batch_id") == "batch-1")
    expect("result backend must match the persisted concrete assignment",
           isinstance(first_launch, dict) and bool(transition)
           and raises_value(lambda: transition(
               first_launch["state"], route_jobs, "job-a", {
                   "result": "failure", "failure_class": "network",
                   "network_scope": "no_response", "backend": "zai",
                   "attempt_id": "job-a:1",
               }, "2026-08-01T07:21:30Z", "batch-1", 300, 3,
           )))
    expect("result batch must match the persisted current launch batch",
           isinstance(first_launch, dict) and bool(transition)
           and raises_value(lambda: transition(
               first_launch["state"], route_jobs, "job-a", {
                   "result": "failure", "failure_class": "network",
                   "network_scope": "no_response", "backend": "codex",
                   "attempt_id": "job-a:1",
               }, "2026-08-01T07:21:30Z", "forged-batch", 300, 3,
           )))
    malformed_attempt_state = json.loads(json.dumps(first_launch["state"])) \
        if isinstance(first_launch, dict) else {}
    if malformed_attempt_state:
        malformed_attempt_state["jobs"]["job-a"]["attempt_id"] = "job-a:99"
    malformed_attempt_errors = validate(malformed_attempt_state, route_jobs) \
        if validate and malformed_attempt_state else []
    expect("malformed persisted attempt identity fails closed",
           any("attempt identity" in error for error in malformed_attempt_errors))

    opened_and_advanced = value_or_none(lambda: transition(
        first_launch["state"], route_jobs, "job-a", {
            "cooldown_backend": "codex",
            "cooldown_reason": "usage_window_exhausted",
            "cooldown_until": "2026-08-01T12:00:00Z",
            "attempt_id": "job-a:1", "advance_pool": True,
        }, "2026-08-01T07:21:30Z", "batch-1", 300, 3,
    )) if isinstance(first_launch, dict) and transition else None
    expect("cooldown intent persists canonical generation then advances once",
           isinstance(opened_and_advanced, dict)
           and opened_and_advanced.get("state", {}).get("cooldowns", {}).get(
               "codex", {}).get("opened_by_attempt_id") == "job-a:1"
           and opened_and_advanced.get("assignment", {}).get("assigned_backend") == "claude"
           and opened_and_advanced.get("assignment", {}).get("attempt_id") == "job-a:2")
    expect("cooldown intent cannot target a backend other than its persisted attempt",
           bool(transition) and isinstance(first_launch, dict)
           and raises_value(lambda: transition(
               first_launch["state"], route_jobs, "job-a", {
                   "cooldown_backend": "zai", "cooldown_reason": "rate_limited",
                   "cooldown_until": "2026-08-01T07:30:00Z",
                   "attempt_id": "job-a:1",
               }, "2026-08-01T07:21:30Z", "batch-1", 300, 3,
           )))

    expired_probe_state = json.loads(json.dumps(route_state))
    expired_probe_state["pool_members"]["light"] = [
        {"backend": "codex", "model": "model-a", "available": True},
    ]
    expired_probe_state["cooldowns"] = {
        "codex": dict(canonical_cooldown, until="2026-08-01T07:20:00Z"),
    }
    probe_launch = value_or_none(lambda: transition(
        expired_probe_state, route_jobs[:1], "job-a", {"launch": True},
        "2026-08-01T07:21:00Z", "batch-2", 300, 3,
    )) if transition else None
    probe_entry = probe_launch.get("state", {}).get("cooldowns", {}).get("codex", {}) \
        if isinstance(probe_launch, dict) else {}
    expect("expired cooldown grants one real-job half-open lease",
           probe_launch is not None and probe_launch.get("action") == "launch"
           and probe_entry.get("probe", {}).get("status") == "leased"
           and probe_entry.get("probe", {}).get("owner_attempt_id") == "job-a:1"
           and probe_entry.get("probe", {}).get("lease_until")
               == "2026-08-01T07:26:03Z")

    second_probe = value_or_none(lambda: transition(
        probe_launch["state"], route_jobs[:1], "job-a", {"launch": True},
        "2026-08-01T07:22:00Z", "batch-2", 300, 3,
    )) if isinstance(probe_launch, dict) and transition else None
    expect("active half-open lease prevents a second probe launch",
           isinstance(second_probe, dict) and second_probe.get("action") == "halt"
           and second_probe.get("assignment") is None)

    stale_probe_state = json.loads(json.dumps(route_state))
    stale_probe_state["jobs"]["job-a"].update({
        "attempt_counter": 1, "attempt_id": "job-a:1", "batch_id": "batch-2",
    })
    stale_probe_state["jobs"]["job-b"].update({
        "attempt_counter": 1, "attempt_id": "job-b:1",
        "batch_id": "batch-2",
        "assigned_backend": "codex", "assigned_model": "model-a",
        "pool_index": 0,
    })
    stale_probe_state["cooldowns"] = {"codex": dict(
        canonical_cooldown,
        until="2026-08-01T07:20:00Z",
        opened_by_attempt_id="job-b:1",
        probe={
            "status": "leased", "owner_job_id": "job-b",
            "owner_attempt_id": "job-b:1",
            "lease_until": "2026-08-01T07:26:03Z",
        },
    )}
    stale_success = value_or_none(lambda: transition(
        stale_probe_state, route_jobs, "job-a", {
            "result": "success", "backend": "codex", "attempt_id": "job-a:1",
        }, "2026-08-01T07:22:00Z", "batch-2", 300, 3,
    )) if transition else None
    expect("stale in-flight success cannot clear a newer cooldown",
           isinstance(stale_success, dict)
           and "codex" in stale_success.get("state", {}).get("cooldowns", {}))

    exact_success = value_or_none(lambda: transition(
        probe_launch["state"], route_jobs[:1], "job-a", {
            "result": "success", "backend": "codex", "attempt_id": "job-a:1",
        }, "2026-08-01T07:22:00Z", "batch-2", 300, 3,
    )) if isinstance(probe_launch, dict) and transition else None
    expect("only exact leased probe success clears backend cooldown",
           isinstance(exact_success, dict)
           and "codex" not in exact_success.get("state", {}).get("cooldowns", {}))

    renewed_probe = value_or_none(lambda: transition(
        probe_launch["state"], route_jobs[:1], "job-a", {
            "result": "failure", "failure_class": "overloaded",
            "backend": "codex", "attempt_id": "job-a:1",
            "retry_at": "2026-08-01T07:32:00Z",
        }, "2026-08-01T07:22:00Z", "batch-2", 300, 3,
    )) if isinstance(probe_launch, dict) and transition else None
    expect("matching transient probe failure renews cooldown and releases lease",
           isinstance(renewed_probe, dict)
           and renewed_probe.get("state", {}).get("cooldowns", {}).get(
               "codex", {}).get("until") == "2026-08-01T07:32:00Z"
           and renewed_probe.get("state", {}).get("cooldowns", {}).get(
               "codex", {}).get("probe") == idle_probe)

    permanent_probe = value_or_none(lambda: transition(
        probe_launch["state"], route_jobs[:1], "job-a", {
            "result": "failure", "failure_class": "out_of_credits",
            "backend": "codex", "attempt_id": "job-a:1",
        }, "2026-08-01T07:22:00Z", "batch-2", 300, 3,
    )) if isinstance(probe_launch, dict) and transition else None
    expect("permanent probe failure removes cooldown and opens existing circuit family",
           isinstance(permanent_probe, dict)
           and "codex" not in permanent_probe.get("state", {}).get("cooldowns", {})
           and permanent_probe.get("state", {}).get("circuit_open", {}).get(
               "codex", {}).get("open") is True)

    dead_lease_state = json.loads(json.dumps(probe_launch["state"])) \
        if isinstance(probe_launch, dict) else {}
    if dead_lease_state:
        dead_lease_state["cooldowns"]["codex"]["probe"]["lease_until"] = \
            "2026-08-01T07:20:30Z"
    unreconciled = value_or_none(lambda: transition(
        dead_lease_state, route_jobs[:1], "job-a", {"launch": True},
        "2026-08-01T07:22:00Z", "batch-2", 300, 3,
    )) if dead_lease_state and transition else None
    reclaimed = value_or_none(lambda: transition(
        dead_lease_state, route_jobs[:1], "job-a", {
            "launch": True, "dead_attempt_ids": ["job-a:1"],
        }, "2026-08-01T07:22:00Z", "batch-2", 300, 3,
    )) if dead_lease_state and transition else None
    expect("expired probe lease is not reclaimed before liveness reconciliation",
           isinstance(unreconciled, dict) and unreconciled.get("action") == "halt"
           and unreconciled.get("next_retry_at") is None
           and isinstance(reclaimed, dict) and reclaimed.get("action") == "launch"
           and reclaimed.get("assignment", {}).get("attempt_id") == "job-a:2")

    network_base = json.loads(json.dumps(route_state))
    network_base["jobs"]["job-a"].update({
        "attempt_counter": 1, "attempt_id": "job-a:1", "batch_id": "batch-net",
    })
    network_base["jobs"]["job-b"].update({
        "attempt_counter": 1, "attempt_id": "job-b:1", "batch_id": "batch-net",
    })
    network_one = value_or_none(lambda: transition(
        network_base, route_jobs, "job-a", {
            "result": "failure", "failure_class": "network",
            "network_scope": "no_response", "backend": "codex",
            "attempt_id": "job-a:1",
        }, "2026-08-01T07:20:00Z", "batch-net", 300, 3,
    )) if transition else None
    expect("one no-response failure records evidence without global pause",
           isinstance(network_one, dict)
           and network_one.get("action") == "state_updated"
           and network_one.get("state", {}).get("network_pause") is None
           and len(network_one.get("state", {}).get("network_evidence", [])) == 1)
    forged_evidence_state = json.loads(json.dumps(network_one["state"])) \
        if isinstance(network_one, dict) else {}
    if forged_evidence_state:
        forged_evidence_state["network_evidence"][0].update({
            "job_id": "missing-job", "attempt_id": "somebody-else:9",
        })
    forged_errors = validate(forged_evidence_state, route_jobs) \
        if validate and forged_evidence_state else []
    expect("network evidence rejects unknown job or forged attempt generation",
           any("network_evidence" in error for error in forged_errors))

    duplicate_network = value_or_none(lambda: transition(
        network_one["state"], route_jobs, "job-a", {
            "result": "failure", "failure_class": "network",
            "network_scope": "no_response", "backend": "codex",
            "attempt_id": "job-a:1",
        }, "2026-08-01T07:20:10Z", "batch-net", 300, 3,
    )) if isinstance(network_one, dict) and transition else None
    expect("network evidence deduplicates backend plus attempt id",
           isinstance(duplicate_network, dict)
           and len(duplicate_network.get("state", {}).get("network_evidence", [])) == 1
           and duplicate_network.get("state", {}).get("network_pause") is None)

    network_two = value_or_none(lambda: transition(
        network_one["state"], route_jobs, "job-b", {
            "result": "failure", "failure_class": "network",
            "network_scope": "no_response", "backend": "claude",
            "attempt_id": "job-b:1",
        }, "2026-08-01T07:20:30Z", "batch-net", 300, 3,
    )) if isinstance(network_one, dict) and transition else None
    expect("two providers in one batch inside 60 seconds open network pause",
           isinstance(network_two, dict)
           and network_two.get("action") == "network_paused"
           and len(network_two.get("state", {}).get(
               "network_pause", {}).get("evidence", [])) == 2)

    stale_network = value_or_none(lambda: transition(
        network_one["state"], route_jobs, "job-b", {
            "result": "failure", "failure_class": "network",
            "network_scope": "no_response", "backend": "claude",
            "attempt_id": "job-b:1",
        }, "2026-08-01T07:21:01Z", "batch-net", 300, 3,
    )) if isinstance(network_one, dict) and transition else None
    expect("network evidence older than correlation window is discarded",
           isinstance(stale_network, dict)
           and stale_network.get("state", {}).get("network_pause") is None
           and len(stale_network.get("state", {}).get("network_evidence", [])) == 1)

    provider_reported_state = json.loads(json.dumps(network_one["state"])) \
        if isinstance(network_one, dict) else None
    if isinstance(provider_reported_state, dict):
        provider_reported_state["jobs"]["job-b"].update({
            "assigned_backend": "zai", "assigned_model": "model-c", "pool_index": 2,
        })
    provider_reported = value_or_none(lambda: transition(
        provider_reported_state, route_jobs, "job-b", {
            "result": "failure", "failure_class": "network",
            "network_scope": "provider_reported", "backend": "zai",
            "attempt_id": "job-b:1",
        }, "2026-08-01T07:20:20Z", "batch-net", 300, 3,
    )) if isinstance(provider_reported_state, dict) and transition else None
    expect("provider-reported z.ai 1234 cannot count as offline evidence",
           isinstance(provider_reported, dict)
           and provider_reported.get("state", {}).get("network_pause") is None
           and len(provider_reported.get("state", {}).get("network_evidence", [])) == 1)

    after_success = value_or_none(lambda: transition(
        network_one["state"], route_jobs, "job-b", {
            "result": "success", "backend": "claude", "attempt_id": "job-b:1",
        }, "2026-08-01T07:20:15Z", "batch-net", 300, 3,
    )) if isinstance(network_one, dict) and transition else None
    after_success_state = json.loads(json.dumps(after_success["state"])) \
        if isinstance(after_success, dict) else None
    if isinstance(after_success_state, dict):
        after_success_state["jobs"]["job-b"].update({
            "attempt_counter": 2, "attempt_id": "job-b:2",
        })
    vetoed = value_or_none(lambda: transition(
        after_success_state, route_jobs, "job-b", {
            "result": "failure", "failure_class": "network",
            "network_scope": "no_response", "backend": "claude",
            "attempt_id": "job-b:2",
        }, "2026-08-01T07:20:30Z", "batch-net", 300, 3,
    )) if isinstance(after_success, dict) and transition else None
    expect("completed same-window success vetoes prior outage evidence",
           isinstance(vetoed, dict)
           and vetoed.get("state", {}).get("network_pause") is None
           and len(vetoed.get("state", {}).get("network_evidence", [])) == 1)

    success_first_state = json.loads(json.dumps(network_base))
    success_first = value_or_none(lambda: transition(
        success_first_state, route_jobs, "job-a", {
            "result": "success", "backend": "codex", "attempt_id": "job-a:1",
        }, "2026-08-01T07:20:00Z", "batch-net", 300, 3,
    )) if transition else None
    first_after_success_state = json.loads(json.dumps(success_first["state"])) \
        if isinstance(success_first, dict) else None
    if isinstance(first_after_success_state, dict):
        first_after_success_state["jobs"]["job-a"].update({
            "attempt_counter": 2, "attempt_id": "job-a:2",
        })
    first_after_success = value_or_none(lambda: transition(
        first_after_success_state, route_jobs, "job-a", {
            "result": "failure", "failure_class": "network",
            "network_scope": "no_response", "backend": "codex",
            "attempt_id": "job-a:2",
        }, "2026-08-01T07:20:10Z", "batch-net", 300, 3,
    )) if isinstance(first_after_success_state, dict) and transition else None
    second_after_success = value_or_none(lambda: transition(
        first_after_success["state"], route_jobs, "job-b", {
            "result": "failure", "failure_class": "network",
            "network_scope": "no_response", "backend": "claude",
            "attempt_id": "job-b:1",
        }, "2026-08-01T07:20:20Z", "batch-net", 300, 3,
    )) if isinstance(first_after_success, dict) and transition else None
    expect("persisted completed success vetoes two later failures in its batch window",
           isinstance(success_first, dict)
           and len(success_first.get("state", {}).get("network_successes", [])) == 1
           and isinstance(second_after_success, dict)
           and second_after_success.get("state", {}).get("network_pause") is None
           and len(second_after_success.get("state", {}).get(
               "network_evidence", [])) == 2)

    paused_launch = value_or_none(lambda: transition(
        network_two["state"], route_jobs, "job-a", {"launch": True},
        "2026-08-01T07:20:40Z", "batch-net", 300, 3,
    )) if isinstance(network_two, dict) and transition else None
    expect("active network pause prohibits provider launch",
           isinstance(paused_launch, dict) and paused_launch.get("action") == "halt"
           and paused_launch.get("next_retry_at") == "2026-08-01T07:21:30Z")

    network_probe = value_or_none(lambda: transition(
        network_two["state"], route_jobs, "job-a", {"launch": True},
        "2026-08-01T07:21:31Z", "batch-net", 300, 3,
    )) if isinstance(network_two, dict) and transition else None
    competing_network_probe = value_or_none(lambda: transition(
        network_probe["state"], route_jobs, "job-b", {"launch": True},
        "2026-08-01T07:21:32Z", "batch-net", 300, 3,
    )) if isinstance(network_probe, dict) and transition else None
    expect("network recovery leases exactly one real-job probe",
           isinstance(network_probe, dict) and network_probe.get("action") == "launch"
           and network_probe.get("state", {}).get("network_pause", {}).get(
               "probe", {}).get("owner_attempt_id") == "job-a:2"
           and isinstance(competing_network_probe, dict)
           and competing_network_probe.get("action") == "halt")

    dual_probe_state = json.loads(json.dumps(network_probe["state"])) \
        if isinstance(network_probe, dict) else None
    if isinstance(dual_probe_state, dict):
        dual_probe_state["cooldowns"] = {"codex": dict(
            canonical_cooldown,
            probe={
                "status": "leased", "owner_job_id": "job-a",
                "owner_attempt_id": "job-a:2",
                "lease_until": "2026-08-01T07:26:34Z",
            },
        )}
    expect("one attempt cannot own cooldown and network probes simultaneously",
           isinstance(dual_probe_state, dict)
           and any("probe ownership" in error for error in validate(
               dual_probe_state, route_jobs)))

    simultaneous_expiry = json.loads(json.dumps(network_two["state"])) \
        if isinstance(network_two, dict) else None
    if isinstance(simultaneous_expiry, dict):
        simultaneous_expiry["cooldowns"] = {"codex": dict(
            canonical_cooldown, until="2026-08-01T07:20:00Z",
        )}
    single_family_probe = value_or_none(lambda: transition(
        simultaneous_expiry, route_jobs, "job-a", {"launch": True},
        "2026-08-01T07:21:31Z", "batch-net", 300, 3,
    )) if isinstance(simultaneous_expiry, dict) and transition else None
    expect("network recovery acquisition leaves an expired cooldown probe idle",
           isinstance(single_family_probe, dict)
           and single_family_probe.get("state", {}).get(
               "network_pause", {}).get("probe", {}).get("status") == "leased"
           and single_family_probe.get("state", {}).get(
               "cooldowns", {}).get("codex", {}).get("probe") == idle_probe
           and single_family_probe.get("assignment", {}).get("probe_backend") is None
           and single_family_probe.get("assignment", {}).get("network_probe") is True)

    renewed_network = value_or_none(lambda: transition(
        network_probe["state"], route_jobs, "job-a", {
            "result": "failure", "failure_class": "network",
            "network_scope": "no_response", "backend": "codex",
            "attempt_id": "job-a:2",
        }, "2026-08-01T07:22:00Z", "batch-net", 300, 3,
    )) if isinstance(network_probe, dict) and transition else None
    expect("matching network probe failure renews pause without fan-out",
           isinstance(renewed_network, dict)
           and renewed_network.get("state", {}).get("network_pause", {}).get(
               "until") == "2026-08-01T07:23:00Z"
           and renewed_network.get("state", {}).get("network_pause", {}).get(
               "probe") == idle_probe)

    cleared_network = value_or_none(lambda: transition(
        network_probe["state"], route_jobs, "job-a", {
            "result": "success", "backend": "codex", "attempt_id": "job-a:2",
        }, "2026-08-01T07:22:00Z", "batch-net", 300, 3,
    )) if isinstance(network_probe, dict) and transition else None
    expect("exact network probe success clears run pause",
           isinstance(cleared_network, dict)
           and cleared_network.get("state", {}).get("network_pause") is None)

    clear_state = json.loads(json.dumps(canonical_state))
    clear_state["circuit_open"] = {"claude": dict(canonical_breaker)}
    cleared = value_or_none(lambda: clear(
        clear_state, route_jobs, "codex", "2026-08-01T07:21:00Z"
    )) if clear else None
    expect("clear-cooldown removes only transient state and preserves circuits",
           isinstance(cleared, dict)
           and "codex" not in cleared.get("cooldowns", {})
           and cleared.get("circuit_open") == clear_state.get("circuit_open"))
    expect("clear-cooldown rejects an unknown concrete backend",
           bool(clear) and raises_value(lambda: clear(
               clear_state, route_jobs, "mystery", "2026-08-01T07:21:00Z"
           )))
    handled_transition = value_or_none(lambda: handle("transition", {
        "state": route_state, "jobs": route_jobs, "job_id": "job-a",
        "intent": {"launch": True}, "now": "2026-08-01T07:21:00Z",
        "batch_id": "batch-cli", "job_timeout_seconds": 300,
        "grace_seconds": 3,
    })) if handle else None
    handled_clear = value_or_none(lambda: handle("clear-cooldown", {
        "state": canonical_state, "jobs": route_jobs, "backend": "codex",
        "now": "2026-08-01T07:21:00Z",
    })) if handle else None
    expect("JSON handler exposes transition and clear-cooldown",
           isinstance(handled_transition, dict)
           and handled_transition.get("action") == "launch"
           and isinstance(handled_clear, dict)
           and "codex" not in handled_clear.get("cooldowns", {}))

    # Cross-module contract: consume the real failure-policy decision rather
    # than a hand-shaped transition fixture. The dispatcher adds only the
    # persisted current attempt and an already-resolved exact fallback pair.
    policy_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "compound-v-failure-policy.py")
    policy_spec = importlib.util.spec_from_file_location(
        "compound_v_failure_policy_pool_contract", policy_path)
    policy_module = importlib.util.module_from_spec(policy_spec) \
        if policy_spec and policy_spec.loader else None
    if policy_module is not None:
        policy_spec.loader.exec_module(policy_module)
    decide = getattr(policy_module, "decide", None)

    def real_policy_intent(failure_class, state_value, job_id, attempts,
                           correlated=0, fallback_assignment=None):
        record = state_value["jobs"][job_id]
        decision = decide(
            failure_class, record["assigned_backend"], attempts, 0, 12,
            jitter=False, pool_routed=True,
            assigned_model=record["assigned_model"],
            now="2026-08-01T07:20:00Z",
            network_scope=("no_response" if failure_class == "network" else None),
            correlated_network_failures=correlated,
        )
        decision["attempt_id"] = record["attempt_id"]
        if fallback_assignment is not None:
            decision["fallback_assignment"] = fallback_assignment
        return decision

    integration_base = json.loads(json.dumps(route_state))
    integration_base["jobs"]["job-a"].update({
        "attempt_counter": 1, "attempt_id": "job-a:1", "batch_id": "batch-i",
    })
    integration_base["jobs"]["job-b"].update({
        "attempt_counter": 1, "attempt_id": "job-b:1", "batch_id": "batch-i",
    })

    first_transient = value_or_none(lambda: transition(
        integration_base, route_jobs, "job-a",
        real_policy_intent("rate_limited", integration_base, "job-a", 0),
        "2026-08-01T07:20:00Z", "batch-i", 300, 3,
    )) if decide and transition else None
    expect("real policy nullable cooldown is a no-op and first transient retries",
           isinstance(first_transient, dict)
           and first_transient.get("action") == "launch"
           and first_transient.get("assignment", {}).get("assigned_backend") == "codex"
           and first_transient.get("state", {}).get("cooldowns") == {})

    second_transient = value_or_none(lambda: transition(
        first_transient["state"], route_jobs, "job-a",
        real_policy_intent("rate_limited", first_transient["state"], "job-a", 1),
        "2026-08-01T07:20:10Z", "batch-i", 300, 3,
    )) if isinstance(first_transient, dict) else None
    expect("real policy second transient cools backend and advances bounded ring",
           isinstance(second_transient, dict)
           and second_transient.get("action") == "launch"
           and second_transient.get("assignment", {}).get("assigned_backend") == "claude"
           and second_transient.get("state", {}).get("cooldowns", {}).get(
               "codex", {}).get("reason") == "rate_limited")

    exact_model_state = json.loads(json.dumps(integration_base))
    exact_model_state["pool_members"]["light"] = [
        {"backend": "codex", "model": "model-a", "available": True},
        {"backend": "codex", "model": "model-alt", "available": True},
        {"backend": "claude", "model": "model-b", "available": True},
    ]
    exact_model = value_or_none(lambda: transition(
        exact_model_state, route_jobs[:1], "job-a",
        real_policy_intent("model_unavailable", exact_model_state, "job-a", 0),
        "2026-08-01T07:20:00Z", "batch-i", 300, 3,
    )) if decide and transition else None
    expect("real policy model-unavailable excludes only exact backend/model",
           isinstance(exact_model, dict)
           and exact_model.get("assignment", {}).get("assigned_backend") == "codex"
           and exact_model.get("assignment", {}).get("assigned_model") == "model-alt")

    permanent = value_or_none(lambda: transition(
        integration_base, route_jobs, "job-a",
        real_policy_intent("out_of_credits", integration_base, "job-a", 0),
        "2026-08-01T07:20:00Z", "batch-i", 300, 3,
    )) if decide and transition else None
    expect("real policy out-of-credits opens canonical circuit before ring advance",
           isinstance(permanent, dict)
           and permanent.get("assignment", {}).get("assigned_backend") == "claude"
           and permanent.get("state", {}).get("circuit_open", {}).get(
               "codex", {}).get("reason") == "out_of_credits")

    exhausted_base = json.loads(json.dumps(integration_base))
    exhausted_base["pool_members"]["light"] = [
        {"backend": "codex", "model": "model-a", "available": True},
    ]
    exact_fallback = {"backend": "claude", "model": "sonnet"}
    fallback_launch = value_or_none(lambda: transition(
        exhausted_base, route_jobs[:1], "job-a",
        real_policy_intent("out_of_credits", exhausted_base, "job-a", 0,
                           fallback_assignment=exact_fallback),
        "2026-08-01T07:20:00Z", "batch-i", 300, 3,
    )) if decide and transition else None
    missing_fallback = value_or_none(lambda: transition(
        exhausted_base, route_jobs[:1], "job-a",
        real_policy_intent("out_of_credits", exhausted_base, "job-a", 0),
        "2026-08-01T07:20:00Z", "batch-i", 300, 3,
    )) if decide and transition else None
    mismatched_fallback = value_or_none(lambda: transition(
        exhausted_base, route_jobs[:1], "job-a",
        real_policy_intent(
            "out_of_credits", exhausted_base, "job-a", 0,
            fallback_assignment={"backend": "zai", "model": "wrong"}),
        "2026-08-01T07:20:00Z", "batch-i", 300, 3,
    )) if decide and transition else None
    expect("pool exhaustion uses only explicit exact matching fallback assignment",
           isinstance(fallback_launch, dict)
           and fallback_launch.get("assignment", {}).get("assigned_backend") == "claude"
           and fallback_launch.get("state", {}).get("jobs", {}).get(
               "job-a", {}).get("assignment_source") == "fallback"
           and isinstance(missing_fallback, dict)
           and missing_fallback.get("action") == "halt"
           and isinstance(mismatched_fallback, dict)
           and mismatched_fallback.get("action") == "halt")

    auth_halt = value_or_none(lambda: transition(
        integration_base, route_jobs, "job-a",
        real_policy_intent("auth", integration_base, "job-a", 0),
        "2026-08-01T07:20:00Z", "batch-i", 300, 3,
    )) if decide and transition else None
    expect("real policy auth halt persists canonical permanent breaker",
           isinstance(auth_halt, dict) and auth_halt.get("action") == "halt"
           and auth_halt.get("state", {}).get("circuit_open", {}).get(
               "codex", {}).get("reason") == "auth")

    first_network = value_or_none(lambda: transition(
        integration_base, route_jobs, "job-a",
        real_policy_intent("network", integration_base, "job-a", 0, correlated=1),
        "2026-08-01T07:20:00Z", "batch-i", 300, 3,
    )) if decide and transition else None
    second_network = value_or_none(lambda: transition(
        first_network["state"], route_jobs, "job-b",
        real_policy_intent("network", first_network["state"], "job-b", 0,
                           correlated=2),
        "2026-08-01T07:20:20Z", "batch-i", 300, 3,
    )) if isinstance(first_network, dict) else None
    expect("real policy network pause remains backed by causal provider evidence",
           isinstance(second_network, dict)
           and second_network.get("action") == "halt"
           and {row.get("backend") for row in second_network.get(
               "state", {}).get("network_pause", {}).get("evidence", [])}
               == {"codex", "claude"})

    if failures:
        print("\nSELFTEST: %d ok, %d fail" % (checked[0] - len(failures), len(failures)))
        return 1
    print("\nSELFTEST: %d ok, 0 fail" % checked[0])
    return 0


def main(argv):
    if "--selftest" in argv[1:]:
        return _selftest()
    if len(argv) != 2 or argv[1] not in (
            "freeze", "validate", "resume", "select", "transition", "clear-cooldown"):
        sys.stderr.write(
            "usage: compound-v-pool-state.py "
            "{freeze|validate|resume|select|transition|clear-cooldown} < request.json\n"
            "       compound-v-pool-state.py --selftest\n"
        )
        return 2
    try:
        payload = json.load(sys.stdin)
        result = handle_request(argv[1], payload)
    except (ValueError, OSError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    if argv[1] == "validate" and not result.get("valid"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
