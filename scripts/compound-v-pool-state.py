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
        if not isinstance(opened_at, str) or not opened_at:
            errors.append("%s.opened_at must be a non-empty string" % path)
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


def select_frozen_member(state, tier, index):
    """Select from the frozen ring, skipping unavailable/open slots without resize."""
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
        if member.get("available") is not True or breaker_is_open:
            continue
        model = member.get("model")
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

    if failures:
        print("\nSELFTEST: %d ok, %d fail" % (checked[0] - len(failures), len(failures)))
        return 1
    print("\nSELFTEST: %d ok, 0 fail" % checked[0])
    return 0


def main(argv):
    if "--selftest" in argv[1:]:
        return _selftest()
    if len(argv) != 2 or argv[1] not in ("freeze", "validate", "resume", "select"):
        sys.stderr.write(
            "usage: compound-v-pool-state.py "
            "{freeze|validate|resume|select} < request.json\n"
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
