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
- **Structural malformation** (not valid JSON, root not an object, ``models`` present
  but not an object, ``pre_eval`` present but not an object) → **raise** ``ValueError``
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


def load_config_file(config_path):
    """Return the parsed config object for ``config_path``.

    Missing file → ``{}`` (defaults apply). Present-but-malformed (invalid JSON or
    a non-object root) → raise ``ValueError`` so the caller warns and uses defaults.
    """
    if not config_path or not os.path.isfile(config_path):
        return {}
    try:
        with open(config_path, "r") as fh:
            data = json.load(fh)
    except ValueError as e:
        raise ValueError("config is not valid JSON (%s): %s" % (config_path, e))
    if not isinstance(data, dict):
        raise ValueError("config root is not a JSON object: %s" % config_path)
    return data


def config_path_for_repo(repo):
    return os.path.join(repo or ".", CONFIG_RELPATH)


def load_project_config(repo):
    """Fail-closed load of ``<repo>/.claude/compound-v.json`` -> dict.

    Structural sanity is checked here so every consumer shares one verdict:
    ``models`` and ``pre_eval``, when present, MUST be objects (else raise). The raw
    dict is returned unchanged otherwise; use ``get_models`` / ``resolve_pre_eval``
    to extract normalized views.
    """
    cfg = load_config_file(config_path_for_repo(repo))
    models = cfg.get("models")
    if models is not None and not isinstance(models, dict):
        raise ValueError("config 'models' is not an object: %s" % config_path_for_repo(repo))
    pre_eval = cfg.get("pre_eval")
    if pre_eval is not None and not isinstance(pre_eval, dict):
        raise ValueError("config 'pre_eval' is not an object: %s" % config_path_for_repo(repo))
    return cfg


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

    # positive-int knobs
    for key in ("min_sample_count", "fan_out_threshold", "token_cap"):
        if key in raw:
            v = raw[key]
            # bool is an int subclass in Python — reject it explicitly.
            if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
                values[key] = v
            else:
                warnings.append("pre_eval.%s must be a non-negative int; using default %r"
                                % (key, PRE_EVAL_DEFAULTS[key]))

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
    print(json.dumps({"models": get_models(cfg), "pre_eval": values,
                      "warnings": warnings}, indent=2))
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

    if failures:
        print("\nSELFTEST FAILED: %d case(s)" % len(failures))
        return 1
    print("\nSELFTEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
