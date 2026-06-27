#!/usr/bin/env python3
"""
Compound V model broker — resolve (backend, tier, effort) -> concrete model.

The plugin routes work by INTENT (a stable tier vocabulary) instead of
hardcoding model strings that rot whenever a provider ships a new model. This
script is the generic resolution layer: given a backend and a tier, it returns
the concrete model string the dispatcher should pass to that backend's worker.

No backend-specific routing logic is baked in here — every backend is just a
``{tier -> model}`` map. Three layers of precedence, lowest to highest:

  1. BUILT-IN default map (below) so the resolver works with NO config file.
  2. ``models.<backend>.<tier>`` in the --config JSON, if present, OVERRIDES
     the built-in value for that single (backend, tier) cell.
  3. ``--explicit-model M`` (a manifest-level model override) always wins and
     skips the map entirely.

Vocabulary (never changes when models churn):
  tier   ∈ { deep, standard, light }
  effort ∈ { low, medium, high }   (orthogonal hint; passed through, default
                                    pairing deep→high / standard→medium /
                                    light→low when --effort omitted)

Output: a single JSON object on stdout, e.g.
  {"backend": "codex", "tier": "deep", "model": "gpt-5.5", "effort": "high"}

Exit non-zero if a tier cannot be resolved for a backend (and no
--explicit-model was given).

Usage
-----
    compound-v-resolve-model.py --backend codex --tier deep
    compound-v-resolve-model.py --backend claude --tier light --effort low
    compound-v-resolve-model.py --backend codex --tier standard --config .claude/compound-v.json
    compound-v-resolve-model.py --backend codex --tier deep --explicit-model gpt-5.6
    compound-v-resolve-model.py --selftest

Python 3.9-safe (no match, no X|Y unions), stdlib only.
"""

import argparse
import json
import os
import sys


# --------------------------------------------------------------------------- #
# Built-in default model map. Mirrors the documented seed in /v:init and the
# /v:models refresh surface. NEVER 'haiku' anywhere.
# --------------------------------------------------------------------------- #
DEFAULT_MODELS = {
    "claude": {"deep": "opus", "standard": "opus", "light": "sonnet"},
    "codex": {
        "deep": "gpt-5.5",
        "standard": "gpt-5.5",
        "light": "gpt-5.3-codex-spark",
    },
    # Antigravity (agy) map below is a FALLBACK default. The live catalog IS discoverable
    # headlessly — `agy models </dev/null` returns it in ~2s (the bare command waits on
    # stdin; the redirect is the same fix as `agy --print`). `/v:models` and `/v:init` pipe
    # it through compound-v-discover-models.py to refresh `.claude/compound-v.json`, which
    # OVERRIDES this map. These fallback names are VERIFIED against `agy models` (1.0.13)
    # and accepted by `agy --model` live.
    # Effort is baked into the model NAME for agy (unlike codex/claude, which take a
    # separate effort flag), so each tier picks a name+effort combo; refresh via
    # /v:models. The worker omits `--model` entirely if the resolved value is empty.
    # Gemini family is chosen for error-decorrelation (agy can also serve
    # "Claude Opus 4.6 (Thinking)" / "GPT-OSS 120B (Medium)" — override with --model).
    "antigravity": {
        "deep": "Gemini 3.1 Pro (High)",
        "standard": "Gemini 3.1 Pro (Low)",
        "light": "Gemini 3.5 Flash (Low)",
    },
    # Cursor (cursor-agent) map below is a FALLBACK default. The model ids are the ones
    # VERIFIED in `cursor-agent --help` (gpt-5 / sonnet-4 / sonnet-4-thinking). cursor-agent
    # exposes NO `models` list command, so the richer catalog (opus, gpt-5.5, composer/auto)
    # is set via config / `/v:models` and OVERRIDES this map. The worker omits `--model` when
    # the resolved value is empty (cursor then uses its configured default). Cursor is the
    # LOWER-TRUST tier (no kernel sandbox; `-f` required headlessly) — like antigravity.
    "cursor": {
        "deep": "sonnet-4-thinking",
        "standard": "sonnet-4",
        "light": "gpt-5",
    },
}

BACKENDS = ("claude", "codex", "antigravity", "cursor")
TIERS = ("deep", "standard", "light")
EFFORTS = ("low", "medium", "high")

# Default effort pairing when --effort is omitted. Independently tunable per
# task-type by passing --effort explicitly; this is only the fallback.
DEFAULT_EFFORT_FOR_TIER = {"deep": "high", "standard": "medium", "light": "low"}


def load_config_models(config_path):
    """
    Return the ``models`` mapping from a config JSON, or an empty dict.

    Missing file or absent ``models`` key is NOT an error — the built-in
    default map covers it. A present-but-malformed file is reported by raising.
    """
    if not config_path:
        return {}
    if not os.path.isfile(config_path):
        return {}
    with open(config_path, "r") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("config root is not a JSON object: %s" % config_path)
    models = data.get("models")
    if models is None:
        return {}
    if not isinstance(models, dict):
        raise ValueError("config 'models' is not an object: %s" % config_path)
    return models


def resolve(backend, tier, effort=None, config_models=None, explicit_model=None):
    """
    Resolve to a concrete model. Returns the output dict.

    Precedence: explicit_model > config_models[backend][tier] > DEFAULT_MODELS.
    Raises ValueError on unknown backend/tier or an unresolvable cell.
    """
    if backend not in BACKENDS:
        raise ValueError(
            "unknown backend '%s' (expected one of %s)"
            % (backend, ", ".join(BACKENDS))
        )
    if tier not in TIERS:
        raise ValueError(
            "unknown tier '%s' (expected one of %s)" % (tier, ", ".join(TIERS))
        )
    if effort is not None and effort not in EFFORTS:
        raise ValueError(
            "unknown effort '%s' (expected one of %s)"
            % (effort, ", ".join(EFFORTS))
        )

    resolved_effort = effort if effort is not None else DEFAULT_EFFORT_FOR_TIER[tier]

    # Highest precedence: an explicit manifest model override skips the map.
    if explicit_model:
        return {
            "backend": backend,
            "tier": tier,
            "model": explicit_model,
            "effort": resolved_effort,
        }

    model = None
    # Config override for this single (backend, tier) cell, if present & valid.
    if config_models:
        backend_map = config_models.get(backend)
        if isinstance(backend_map, dict):
            candidate = backend_map.get(tier)
            if isinstance(candidate, str) and candidate.strip():
                model = candidate

    # Fall back to the built-in default map.
    if model is None:
        model = DEFAULT_MODELS.get(backend, {}).get(tier)

    if not model:
        raise ValueError(
            "cannot resolve a model for backend '%s' tier '%s' "
            "(no config override and no built-in default)" % (backend, tier)
        )

    return {
        "backend": backend,
        "tier": tier,
        "model": model,
        "effort": resolved_effort,
    }


def main(argv):
    if "--selftest" in argv[1:]:
        return _selftest()

    parser = argparse.ArgumentParser(
        prog="compound-v-resolve-model.py",
        description="Resolve (backend, tier, effort) -> concrete model.",
    )
    parser.add_argument("--backend", required=True, choices=list(BACKENDS))
    parser.add_argument("--tier", required=True, choices=list(TIERS))
    parser.add_argument("--effort", default=None, choices=list(EFFORTS))
    parser.add_argument("--config", default=None, help="path to compound-v.json")
    parser.add_argument(
        "--explicit-model",
        default=None,
        help="manifest model override; always wins, skips resolution",
    )
    parser.add_argument(
        "--selftest", action="store_true", help="run built-in self-tests"
    )
    args = parser.parse_args(argv[1:])

    try:
        config_models = load_config_models(args.config)
    except Exception as e:  # noqa: BLE001 - report config errors cleanly
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        return 2

    try:
        result = resolve(
            backend=args.backend,
            tier=args.tier,
            effort=args.effort,
            config_models=config_models,
            explicit_model=args.explicit_model,
        )
    except ValueError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        return 1

    print(json.dumps(result))
    return 0


# --------------------------------------------------------------------------- #
# Self-test.
# --------------------------------------------------------------------------- #
def _selftest():
    failures = []

    def expect(name, cond):
        if cond:
            print("  ok   - %s" % name)
        else:
            print("  FAIL - %s" % name)
            failures.append(name)

    # Default resolution for every (backend, tier) cell.
    for backend in BACKENDS:
        for tier in TIERS:
            r = resolve(backend, tier)
            expect(
                "default %s/%s -> %s" % (backend, tier, r["model"]),
                r["model"] == DEFAULT_MODELS[backend][tier]
                and r["backend"] == backend
                and r["tier"] == tier,
            )

    # Antigravity (agy) curated map resolves for its strongest tier.
    expect(
        "antigravity/deep -> curated Gemini",
        resolve("antigravity", "deep")["model"] == "Gemini 3.1 Pro (High)"
        and resolve("antigravity", "deep")["effort"] == "high",
    )

    # No 'haiku' anywhere in the default map.
    flat = json.dumps(DEFAULT_MODELS).lower()
    expect("no haiku in default map", "haiku" not in flat)

    # Default effort pairing when --effort omitted.
    expect("deep default effort high", resolve("claude", "deep")["effort"] == "high")
    expect(
        "standard default effort medium",
        resolve("claude", "standard")["effort"] == "medium",
    )
    expect("light default effort low", resolve("claude", "light")["effort"] == "low")

    # Explicit effort passes through and overrides the default pairing.
    expect(
        "explicit effort overrides pairing",
        resolve("codex", "deep", effort="low")["effort"] == "low",
    )

    # Config override beats the built-in default for one cell only.
    cfg = {"codex": {"deep": "gpt-9.9-custom"}}
    r = resolve("codex", "deep", config_models=cfg)
    expect("config override applied", r["model"] == "gpt-9.9-custom")
    r2 = resolve("codex", "light", config_models=cfg)
    expect(
        "config override is per-cell (other tiers fall back to default)",
        r2["model"] == DEFAULT_MODELS["codex"]["light"],
    )

    # Malformed/empty config cells fall back to default rather than break.
    bad_cfg = {"codex": {"deep": ""}}
    expect(
        "empty config cell falls back to default",
        resolve("codex", "deep", config_models=bad_cfg)["model"]
        == DEFAULT_MODELS["codex"]["deep"],
    )
    not_map_cfg = {"codex": "not-a-map"}
    expect(
        "non-dict backend map falls back to default",
        resolve("codex", "deep", config_models=not_map_cfg)["model"]
        == DEFAULT_MODELS["codex"]["deep"],
    )

    # Explicit model always wins, skipping the map (even with a config present).
    r = resolve(
        "codex", "deep", config_models=cfg, explicit_model="gpt-pinned-1.0"
    )
    expect("explicit model wins over config", r["model"] == "gpt-pinned-1.0")
    r = resolve("claude", "light", explicit_model="opus")
    expect("explicit model wins over default", r["model"] == "opus")
    expect(
        "explicit model still gets resolved effort",
        resolve("claude", "deep", explicit_model="opus")["effort"] == "high",
    )

    # Unknown backend / tier / effort raise.
    def raises(fn):
        try:
            fn()
            return False
        except ValueError:
            return True

    expect("unknown backend raises", raises(lambda: resolve("gemini", "deep")))
    expect("unknown tier raises", raises(lambda: resolve("claude", "turbo")))
    expect(
        "unknown effort raises",
        raises(lambda: resolve("claude", "deep", effort="extreme")),
    )

    if failures:
        print("\nSELFTEST FAILED: %d case(s)" % len(failures))
        return 1
    print("\nSELFTEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
