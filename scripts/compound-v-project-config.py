#!/usr/bin/env python3
"""
Compound V — shared project-config loader (``.claude/compound-v.json``).

THE single fail-closed reader of the project config (CR2-11). Before v2.9 the only
config surface was ``models`` (read by ``compound-v-resolve-model.py`` via its own
``load_config_models``). v2.9 adds the ``pre_eval.*`` block, and both the resolver
and the pre-eval engine (A3) must read the SAME file with the SAME rules — so the
loader lives here once and ``load_config_models`` becomes a thin wrapper over it.

Fail-closed contract
--------------------
- **Missing file** is NOT an error — the built-in defaults cover it (an
  un-onboarded repo still routes with the default model map and pre-eval defaults).
  ``load_config_file`` returns ``{}``.
- **Structural malformation** (not valid JSON, root not an object, or a known
  object block such as ``models`` / ``pre_eval`` / ``pools`` /
  ``backend_max_parallel`` present but not an object) → **raise** ``ValueError``
  so the CALLER can warn-once and fall back to all-defaults. A malformed config is
  NEVER silently treated as an auto-route (Iron-Invariant #5 / #4).
- **Per-key invalid values inside ``pre_eval``** (e.g. ``fast_path: "banana"``,
  ``min_sample_count: "x"``) are NOT structural — ``resolve_pre_eval`` coerces each
  bad/missing key back to its declared default and RETURNS the offending keys in a
  ``warnings`` list so the caller can warn-once. Never fail open, never auto-route.

This module is intentionally tiny and dependency-free (pure stdlib, Python 3.9-safe)
so it can be imported by other standalone scripts by path.

Usage:
    compound-v-project-config.py <repo-dir>     # print resolved config + warnings
    compound-v-project-config.py --selftest
"""

import json
import os
import sys

# Config file location relative to the repo root.
CONFIG_RELPATH = os.path.join(".claude", "compound-v.json")

# ---------------------------------------------------------------------------- #
# pre_eval.* declared keys + fail-closed defaults (spec §7 / pre-eval-config.md).
# Every default is the SAFE (never-auto-route) value. `fast_path: ask` OFFERS,
# never routes; `off` is a hard kill-switch. `remember` is an explicit, revocable
# per-category opt-in (AC-11) and defaults to empty (ask every time).
# ---------------------------------------------------------------------------- #
PRE_EVAL_DEFAULTS = {
    "enabled": True,            # pre-eval stage runs (fail-closed to FULL_PIPELINE anyway)
    "fast_path": "ask",         # ask | off  — ask OFFERS, off is the hard kill-switch
    "min_sample_count": 5,      # Tier-2 needs >= this many fast-path outcomes before lowering
    "fan_out_threshold": 1,     # Layer-B: fast-path only when fan_out <= this (single-path)
    "token_cap": 20000,         # whole-stage token budget; overrun → abort → FULL_PIPELINE
    "remember": {},             # {category: "fastpath"} — explicit, revocable (AC-11)
}
_FAST_PATH_VALUES = ("ask", "off")

# ---------------------------------------------------------------------------- #
# brainstorm.* declared keys + fail-closed defaults (v2.16 decision-preferences).
# `preferences` governs the decision memory+challenge surface in the elicitation
# driver: `off` = nothing; `on-demand` (default, least-intrusive) = the human PULLS
# past history, no unsolicited surface; `marked` = a *qualifying* fork carries a
# falsifiable dated BADGE (never a pre-selected default) always paired with the
# mandatory divergent challenge. The safe default is `on-demand` — a pull can't nudge.
# This is the FIRST Python reader of a `brainstorm.*` key in this module (by design).
# ---------------------------------------------------------------------------- #
BRAINSTORM_DEFAULTS = {
    "preferences": "on-demand",   # off | on-demand | marked — on-demand is the safe default
}
_PREFERENCES_VALUES = ("off", "on-demand", "marked")

# Tier-pool vocabulary is duplicated intentionally in this standalone stdlib
# reader. ``zai`` is part of the PR-1 merge prerequisite for this feature; a
# branch without that prerequisite can normalize the config but model resolution
# still fails closed until the backend exists in the resolver.
VALID_POOL_STANCES = ("balanced", "conservative", "cost-aware", "claude-only")
VALID_POOL_TIERS = ("deep", "standard", "light")
VALID_POOL_BACKENDS = (
    "claude", "codex", "antigravity", "cursor", "devin", "opencode", "zai",
)
# Deterministic safety bounds: weights are expanded into in-memory positional
# rings, so both the per-member and per-tier totals are capped before expansion.
MAX_POOL_WEIGHT = 100
MAX_EXPANDED_POOL_SLOTS = 256


def load_config_file(config_path):
    """Return the parsed config object for ``config_path``.

    Missing file → ``{}`` (defaults apply). Present-but-malformed (invalid JSON or
    a non-object root) → raise ``ValueError`` so the caller warns and uses defaults.
    """
    if not config_path or not os.path.isfile(config_path):
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except ValueError as e:
        raise ValueError("config is not valid JSON (%s): %s" % (config_path, e))
    if not isinstance(data, dict):
        raise ValueError("config root is not a JSON object: %s" % config_path)
    return data


def config_path_for_repo(repo):
    return os.path.join(repo or ".", CONFIG_RELPATH)


def load_project_config_path(config_path):
    """Fail-closed load of one project-config path with the full shared verdict."""
    cfg = load_config_file(config_path)
    for key in ("models", "pre_eval", "brainstorm", "pools",
                "backend_max_parallel"):
        value = cfg.get(key)
        if value is not None and not isinstance(value, dict):
            raise ValueError("config '%s' is not an object: %s" % (key, config_path))
    return cfg


def load_project_config(repo):
    """Fail-closed load of ``<repo>/.claude/compound-v.json`` -> dict.

    Structural sanity is checked by ``load_project_config_path`` so path-based
    and repo-based consumers share one verdict. Known object blocks, including
    ``models``, ``pre_eval``, ``pools``, and ``backend_max_parallel``, MUST be
    objects when present (else raise). The raw dict is returned unchanged
    otherwise; use the block readers below to extract normalized views.
    """
    return load_project_config_path(config_path_for_repo(repo))


def get_models(cfg):
    """The ``models`` mapping from a parsed config, or ``{}``.

    Absent ``models`` is fine (built-in defaults cover it). A present-but-non-object
    ``models`` is a structural error and raises — mirrors the legacy
    ``load_config_models`` behaviour exactly so the resolver stays behaviour-preserving.
    """
    if not isinstance(cfg, dict):
        return {}
    models = cfg.get("models")
    if models is None:
        return {}
    if not isinstance(models, dict):
        raise ValueError("config 'models' is not an object")
    return models


def resolve_pools(cfg):
    """Return ``(normalized, warnings)`` for per-stance weighted tier pools.

    The only accepted shape is ``{stance: {tier: [member, ...]}}``. A member
    requires one known backend, accepts an optional non-empty model override,
    and defaults ``weight`` to 1. Nested malformation warns and drops; a
    present-but-non-object top-level ``pools`` value is structural and raises.
    """
    raw = {}
    if isinstance(cfg, dict):
        candidate = cfg.get("pools")
        if candidate is not None and not isinstance(candidate, dict):
            raise ValueError("config 'pools' is not an object")
        if isinstance(candidate, dict):
            raw = candidate

    normalized = {}
    warnings = []
    for stance, stance_value in raw.items():
        if stance not in VALID_POOL_STANCES:
            warnings.append("pools.%s is not a known stance; ignored" % stance)
            continue
        if not isinstance(stance_value, dict):
            warnings.append("pools.%s must be an object keyed by tier; ignored" % stance)
            continue
        tiers = {}
        for tier, members in stance_value.items():
            path = "pools.%s.%s" % (stance, tier)
            if tier not in VALID_POOL_TIERS:
                warnings.append("%s is not a known tier; ignored" % path)
                continue
            if not isinstance(members, list):
                warnings.append("%s must be a list of member objects; ignored" % path)
                continue
            clean = []
            seen_backends = set()
            expanded_slots = 0
            for index, member in enumerate(members):
                member_path = "%s[%d]" % (path, index)
                if not isinstance(member, dict):
                    warnings.append("%s must be an object; ignored" % member_path)
                    continue
                backend = member.get("backend")
                if (not isinstance(backend, str)
                        or backend not in VALID_POOL_BACKENDS):
                    warnings.append("%s.backend must be one of %s; ignored"
                                    % (member_path, VALID_POOL_BACKENDS))
                    continue
                model = member.get("model")
                if "model" in member and (
                        not isinstance(model, str) or not model.strip()):
                    warnings.append("%s.model must be a non-empty string; ignored"
                                    % member_path)
                    continue
                weight = member.get("weight", 1)
                if (not isinstance(weight, int) or isinstance(weight, bool)
                        or weight <= 0 or weight > MAX_POOL_WEIGHT):
                    warnings.append(
                        "%s.weight must be a positive integer <= %d; ignored"
                        % (member_path, MAX_POOL_WEIGHT)
                    )
                    continue
                extra_keys = sorted(
                    k for k in member if k not in ("backend", "model", "weight")
                )
                if extra_keys:
                    warnings.append(
                        "%s has unexpected key(s) %s; ignored"
                        % (member_path, extra_keys)
                    )
                if backend in seen_backends:
                    warnings.append("%s duplicates backend %r; ignored"
                                    % (member_path, backend))
                    continue
                if expanded_slots + weight > MAX_EXPANDED_POOL_SLOTS:
                    warnings.append(
                        "%s would exceed the %d-slot expanded pool limit; ignored"
                        % (member_path, MAX_EXPANDED_POOL_SLOTS)
                    )
                    continue
                seen_backends.add(backend)
                expanded_slots += weight
                clean_member = {"backend": backend, "weight": weight}
                if model is not None:
                    clean_member["model"] = model.strip()
                clean.append(clean_member)
            tiers[tier] = clean
        if tiers:
            normalized[stance] = tiers
    return normalized, warnings


def resolve_backend_max_parallel(cfg):
    """Return normalized concrete-backend concurrency hints plus warnings."""
    raw = {}
    if isinstance(cfg, dict):
        candidate = cfg.get("backend_max_parallel")
        if candidate is not None and not isinstance(candidate, dict):
            raise ValueError("config 'backend_max_parallel' is not an object")
        if isinstance(candidate, dict):
            raw = candidate

    normalized = {}
    warnings = []
    for backend, value in raw.items():
        if backend not in VALID_POOL_BACKENDS:
            warnings.append("backend_max_parallel.%s is not a known backend; ignored"
                            % backend)
            continue
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            warnings.append("backend_max_parallel.%s must be a positive integer; ignored"
                            % backend)
            continue
        normalized[backend] = value
    return normalized, warnings


def resolve_pre_eval(cfg):
    """Return ``(values, warnings)``: the effective ``pre_eval`` config with every
    missing/invalid key coerced to its declared default, plus a list of human-readable
    warnings for the caller to surface once. NEVER raises on a bad per-key value —
    a bad value can only DEGRADE to the safe default, never become an auto-route.
    """
    values = dict(PRE_EVAL_DEFAULTS)
    values["remember"] = {}  # fresh copy — never share the module-level dict
    warnings = []
    raw = {}
    if isinstance(cfg, dict) and isinstance(cfg.get("pre_eval"), dict):
        raw = cfg["pre_eval"]

    # enabled: bool
    if "enabled" in raw:
        v = raw["enabled"]
        if isinstance(v, bool):
            values["enabled"] = v
        else:
            warnings.append("pre_eval.enabled must be true/false; using default %r"
                            % PRE_EVAL_DEFAULTS["enabled"])

    # fast_path: ask | off
    if "fast_path" in raw:
        v = raw["fast_path"]
        if isinstance(v, str) and v in _FAST_PATH_VALUES:
            values["fast_path"] = v
        else:
            warnings.append("pre_eval.fast_path must be one of %s; using default %r"
                            % (_FAST_PATH_VALUES, PRE_EVAL_DEFAULTS["fast_path"]))

    # positive-int knobs. min_sample_count has a floor of 1 (Codex MED-11): a floor of 0 makes an
    # empty fast-path cohort read as "calibrated healthy" (all([]) is True), which would let Tier 2
    # lower ceremony on zero history — violating the launch invariant (empty history = escalation-only).
    _min_allowed = {"min_sample_count": 1, "fan_out_threshold": 0, "token_cap": 1}
    for key in ("min_sample_count", "fan_out_threshold", "token_cap"):
        if key in raw:
            v = raw[key]
            # bool is an int subclass in Python — reject it explicitly.
            if isinstance(v, int) and not isinstance(v, bool) and v >= _min_allowed[key]:
                values[key] = v
            else:
                warnings.append("pre_eval.%s must be an int >= %d; using default %r"
                                % (key, _min_allowed[key], PRE_EVAL_DEFAULTS[key]))

    # remember: {category: "fastpath"} — drop any non-"fastpath" value (fail-closed).
    if "remember" in raw:
        v = raw["remember"]
        if isinstance(v, dict):
            clean = {}
            for cat, choice in v.items():
                if isinstance(cat, str) and choice == "fastpath":
                    clean[cat] = "fastpath"
                else:
                    warnings.append("pre_eval.remember[%r]=%r is not a valid "
                                    "'fastpath' opt-in; ignored" % (cat, choice))
            values["remember"] = clean
        else:
            warnings.append("pre_eval.remember must be an object {category: 'fastpath'}; "
                            "using default {}")

    return values, warnings


def resolve_brainstorm(cfg):
    """Return ``(values, warnings)``: the effective ``brainstorm`` config with every
    missing/invalid key coerced to its declared default, plus human-readable warnings
    for the caller to surface once. Mirrors ``resolve_pre_eval`` exactly — NEVER raises
    on a bad per-key value; a bad ``preferences`` value can only DEGRADE to the safe
    ``on-demand`` default (a pull can't nudge), never silently enable ``marked``.
    """
    values = dict(BRAINSTORM_DEFAULTS)   # fresh copy — never share the module-level dict
    warnings = []
    raw = {}
    if isinstance(cfg, dict) and isinstance(cfg.get("brainstorm"), dict):
        raw = cfg["brainstorm"]

    # preferences: off | on-demand | marked
    if "preferences" in raw:
        v = raw["preferences"]
        # bool is an int subclass in Python and would `in`-compare falsely against
        # nothing here, but guard it explicitly so a JSON `true` never masquerades
        # as a value — mirrors the pre_eval int-knob bool guard.
        if isinstance(v, bool):
            warnings.append("brainstorm.preferences must be one of %s; using default %r"
                            % (_PREFERENCES_VALUES, BRAINSTORM_DEFAULTS["preferences"]))
        elif isinstance(v, str) and v in _PREFERENCES_VALUES:
            values["preferences"] = v
        else:
            warnings.append("brainstorm.preferences must be one of %s; using default %r"
                            % (_PREFERENCES_VALUES, BRAINSTORM_DEFAULTS["preferences"]))

    return values, warnings


def main(argv):
    if "--selftest" in argv[1:]:
        return _selftest()
    if len(argv) < 2:
        sys.stderr.write("usage: compound-v-project-config.py <repo-dir> | --selftest\n")
        return 2
    repo = argv[1]
    try:
        cfg = load_project_config(repo)
    except ValueError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        return 1
    values, warnings = resolve_pre_eval(cfg)
    bvalues, bwarnings = resolve_brainstorm(cfg)
    pools, pool_warnings = resolve_pools(cfg)
    backend_max_parallel, cap_warnings = resolve_backend_max_parallel(cfg)
    print(json.dumps({"models": get_models(cfg), "pre_eval": values,
                      "brainstorm": bvalues,
                      "pools": pools,
                      "backend_max_parallel": backend_max_parallel,
                      "warnings": warnings + bwarnings + pool_warnings + cap_warnings},
                     indent=2))
    return 0


# ---------------------------------------------------------------------------- #
# Self-test.
# ---------------------------------------------------------------------------- #
def _selftest():
    import tempfile
    failures = []

    def expect(name, cond):
        print(("  ok   - " if cond else "  FAIL - ") + name)
        if not cond:
            failures.append(name)

    def raises(fn):
        try:
            fn()
            return False
        except ValueError:
            return True

    with tempfile.TemporaryDirectory() as td:
        # Missing file -> {} (defaults), NEVER an error.
        expect("missing config file -> {}", load_project_config(td) == {})
        v, w = resolve_pre_eval(load_project_config(td))
        expect("missing config -> pre_eval all defaults", v == dict(PRE_EVAL_DEFAULTS))
        expect("missing config -> no warnings", w == [])
        expect("missing config -> models {}", get_models(load_project_config(td)) == {})
        bv, bw = resolve_brainstorm(load_project_config(td))
        expect("missing config -> brainstorm default on-demand",
               bv == dict(BRAINSTORM_DEFAULTS) and bv["preferences"] == "on-demand")
        expect("missing config -> brainstorm no warnings", bw == [])

        cfgdir = os.path.join(td, ".claude")
        os.makedirs(cfgdir)
        cpath = os.path.join(cfgdir, "compound-v.json")

        def write(obj_or_text):
            with open(cpath, "w") as fh:
                if isinstance(obj_or_text, str):
                    fh.write(obj_or_text)
                else:
                    json.dump(obj_or_text, fh)

        # Structural malformation raises (so the caller warns + defaults).
        write("{ not json ")
        expect("invalid JSON raises", raises(lambda: load_project_config(td)))
        write("[1, 2, 3]")
        expect("non-object root raises", raises(lambda: load_project_config(td)))
        write({"models": "not-an-object"})
        expect("non-object models raises", raises(lambda: load_project_config(td)))
        write({"pre_eval": "not-an-object"})
        expect("non-object pre_eval raises", raises(lambda: load_project_config(td)))
        write({"brainstorm": "not-an-object"})
        expect("non-object brainstorm raises", raises(lambda: load_project_config(td)))
        write({"pools": ["not", "an", "object"]})
        expect("non-object pools raises", raises(lambda: load_project_config(td)))
        write({"backend_max_parallel": "not-an-object"})
        expect("non-object backend_max_parallel raises",
               raises(lambda: load_project_config(td)))

        # Tier-pool config is per-stance only. Structural errors raise above;
        # malformed nested entries fail closed by warning + dropping the entry.
        _pool_reader = globals().get("resolve_pools")
        _cap_reader = globals().get("resolve_backend_max_parallel")

        def read_pools(obj):
            if not callable(_pool_reader):
                return None, None
            return _pool_reader(obj)

        def read_caps(obj):
            if not callable(_cap_reader):
                return None, None
            return _cap_reader(obj)

        pools, pool_warnings = read_pools({})
        expect("absent pools normalizes to empty object",
               pools == {} and pool_warnings == [])
        caps, cap_warnings = read_caps({})
        expect("absent backend_max_parallel normalizes to empty object",
               caps == {} and cap_warnings == [])

        valid_pool_cfg = {
            "pools": {
                "balanced": {
                    "light": [
                        {"backend": "codex"},
                        {"backend": "claude", "model": "sonnet", "weight": 2},
                    ],
                    "standard": [],
                }
            }
        }
        pools, pool_warnings = read_pools(valid_pool_cfg)
        expect("pool members normalize with optional model and default weight", pools == {
            "balanced": {
                "light": [
                    {"backend": "codex", "weight": 1},
                    {"backend": "claude", "model": "sonnet", "weight": 2},
                ],
                "standard": [],
            }
        } and pool_warnings == [])

        bad_pool_cfg = {
            "pools": {
                "balanced": {
                    "light": [
                        {"backend": "codex"},
                        {"backend": "codex", "model": "duplicate"},
                        {"model": "missing-backend"},
                        {"backend": "unknown-provider"},
                        {"backend": "claude", "model": ""},
                        {"backend": "antigravity", "weight": 0},
                        {"backend": "cursor", "weight": -1},
                        {"backend": "devin", "weight": True},
                        {"backend": "opencode", "weight": "2"},
                        "not-an-object",
                    ],
                    "turbo": [{"backend": "claude"}],
                },
                "unknown-stance": {"light": [{"backend": "claude"}]},
                "cost-aware": "not-an-object",
            }
        }
        pools, pool_warnings = read_pools(bad_pool_cfg)
        expect("malformed and duplicate pool entries warn and drop",
               pools == {"balanced": {"light": [
                   {"backend": "codex", "weight": 1}
               ]}} and isinstance(pool_warnings, list) and len(pool_warnings) == 12)

        # resolve_pools' OWN top-level "pools is not an object" raise is
        # currently redundant behind load_project_config's separate
        # structural sweep — every real caller goes through that sweep first,
        # so this reader's own guard was previously unreachable from any
        # fixture. Call it directly so the guard has its own regression test.
        pool_reader_raises = False
        if read_pools:
            try:
                read_pools({"pools": "not-an-object"})
            except ValueError:
                pool_reader_raises = True
        expect("resolve_pools raises directly on a non-object pools block "
               "(not only via load_project_config's structural sweep)",
               pool_reader_raises)

        caps, cap_warnings = read_caps({
            "backend_max_parallel": {
                "codex": 3,
                "claude": 1,
                "antigravity": 0,
                "cursor": -1,
                "devin": True,
                "opencode": "2",
                "unknown-provider": 4,
            }
        })
        expect("backend_max_parallel keeps only positive non-bool backend integers",
               caps == {"codex": 3, "claude": 1}
               and isinstance(cap_warnings, list) and len(cap_warnings) == 5)

        limited_pools, limit_warnings = read_pools({"pools": {"balanced": {"light": [
            {"backend": "codex", "weight": 101},
            {"backend": "claude", "weight": 100},
            {"backend": "cursor", "weight": 100},
            {"backend": "devin", "weight": 100},
        ]}}})
        expect("pool weights and aggregate expansion are deterministically bounded",
               limited_pools == {"balanced": {"light": [
                   {"backend": "claude", "weight": 100},
                   {"backend": "cursor", "weight": 100},
               ]}} and isinstance(limit_warnings, list) and len(limit_warnings) == 2)

        # An unknown/typo'd member key (e.g. "wieght" instead of "weight") warns
        # but does NOT drop the member or change its normalized weight.
        typo_pools, typo_warnings = read_pools({"pools": {"balanced": {"light": [
            {"backend": "codex", "wieght": 50},
        ]}}})
        expect("typo'd member key warns but keeps member with default weight",
               typo_pools == {"balanced": {"light": [
                   {"backend": "codex", "weight": 1},
               ]}}
               and any("wieght" in w for w in typo_warnings))

        # A member that is BOTH a duplicate backend AND would exceed the
        # expanded-slot cap must report the more specific duplicate-backend
        # warning, not the slot-limit warning (message ordering, not survival).
        dup_over_cap_pools, dup_over_cap_warnings = read_pools({"pools": {"balanced": {"light": [
            {"backend": "claude", "weight": 100},
            {"backend": "cursor", "weight": 100},
            {"backend": "claude", "weight": 100},
        ]}}})
        expect("duplicate-and-over-cap member reports duplicate, not slot-limit",
               dup_over_cap_pools == {"balanced": {"light": [
                   {"backend": "claude", "weight": 100},
                   {"backend": "cursor", "weight": 100},
               ]}}
               and any("duplicates backend" in w for w in dup_over_cap_warnings)
               and not any("expanded pool limit" in w for w in dup_over_cap_warnings))

        # Valid config round-trips models + pre_eval.
        write({
            "models": {"balanced": {"claude": {"deep": "opus"}}},
            "pre_eval": {"enabled": True, "fast_path": "off", "min_sample_count": 3,
                         "fan_out_threshold": 2, "token_cap": 5000,
                         "remember": {"css-only": "fastpath"}},
        })
        cfg = load_project_config(td)
        expect("valid models round-trips",
               get_models(cfg) == {"balanced": {"claude": {"deep": "opus"}}})
        v, w = resolve_pre_eval(cfg)
        expect("valid pre_eval round-trips", v == {
            "enabled": True, "fast_path": "off", "min_sample_count": 3,
            "fan_out_threshold": 2, "token_cap": 5000,
            "remember": {"css-only": "fastpath"}})
        expect("valid pre_eval -> no warnings", w == [])

        # Per-key bad values -> coerce to default + warn (never raise, never auto-route).
        write({"pre_eval": {"fast_path": "banana", "min_sample_count": "x",
                            "token_cap": -1, "enabled": "yes",
                            "remember": {"css-only": "always", "auth": "fastpath"}}})
        cfg = load_project_config(td)
        v, w = resolve_pre_eval(cfg)
        expect("bad fast_path -> default 'ask'", v["fast_path"] == "ask")
        expect("bad min_sample_count -> default 5", v["min_sample_count"] == 5)
        expect("negative token_cap -> default", v["token_cap"] == PRE_EVAL_DEFAULTS["token_cap"])
        expect("non-bool enabled -> default True", v["enabled"] is True)
        expect("remember keeps only valid 'fastpath' opt-ins",
               v["remember"] == {"auth": "fastpath"})
        expect("bad per-key values produce warnings", len(w) >= 4)

        # remember default is a FRESH dict (never the shared module default).
        v2, _ = resolve_pre_eval({})
        v2["remember"]["x"] = "fastpath"
        expect("remember default is not shared mutable state",
               PRE_EVAL_DEFAULTS["remember"] == {})

        # -- brainstorm.preferences resolver (mirrors resolve_pre_eval) --
        # absent brainstorm block -> default on-demand, no warnings.
        write({"pre_eval": {"fast_path": "off"}})
        bv, bw = resolve_brainstorm(load_project_config(td))
        expect("absent brainstorm block -> default on-demand",
               bv["preferences"] == "on-demand" and bw == [])
        # each valid value passes untouched, no warning.
        for good in _PREFERENCES_VALUES:
            write({"brainstorm": {"preferences": good}})
            bv, bw = resolve_brainstorm(load_project_config(td))
            expect("valid preferences %r passes clean" % good,
                   bv["preferences"] == good and bw == [])
        # a bad string coerces to on-demand + warns (never raises, never auto-enables).
        write({"brainstorm": {"preferences": "always-on"}})
        cfg = load_project_config(td)
        bv, bw = resolve_brainstorm(cfg)
        expect("bad preferences -> coerced to on-demand", bv["preferences"] == "on-demand")
        expect("bad preferences -> produces a warning", len(bw) == 1)
        # a JSON bool must NOT pass as a value (bool-is-int-subclass guard) -> coerce+warn.
        write({"brainstorm": {"preferences": True}})
        bv, bw = resolve_brainstorm(load_project_config(td))
        expect("bool preferences -> coerced to on-demand (not accepted as value)",
               bv["preferences"] == "on-demand" and len(bw) == 1)
        # brainstorm defaults are a FRESH dict (never shared module state).
        bv3, _ = resolve_brainstorm({})
        bv3["preferences"] = "marked"
        expect("brainstorm default is not shared mutable state",
               BRAINSTORM_DEFAULTS["preferences"] == "on-demand")
        # non-object brainstorm raises structurally (parity with pre_eval).
        write({"brainstorm": [1, 2, 3]})
        expect("non-object brainstorm (list) raises",
               raises(lambda: load_project_config(td)))

    if failures:
        print("\nSELFTEST FAILED: %d case(s)" % len(failures))
        return 1
    print("\nSELFTEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
