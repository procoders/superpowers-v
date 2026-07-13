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
  effort ∈ { low, medium, high, xhigh }
                                   (orthogonal hint; passed through, default
                                    pairing deep→high / standard→medium /
                                    light→low when --effort omitted.
                                    `xhigh` is valid iff backend is codex —
                                    every other backend rejects it with a clear
                                    error naming the rule; use `high` instead)

Output: a single JSON object on stdout, e.g.
  {"backend": "codex", "tier": "deep", "model": "gpt-5.6-sol", "effort": "high"}

Exit non-zero if a tier cannot be resolved for a backend (and no
--explicit-model was given).

Usage
-----
    compound-v-resolve-model.py --backend codex --tier deep
    compound-v-resolve-model.py --backend claude --tier light --effort low
    compound-v-resolve-model.py --backend codex --tier standard --config .claude/compound-v.json
    compound-v-resolve-model.py --backend codex --tier deep --explicit-model gpt-5.6
    compound-v-resolve-model.py --backend claude --tier standard --job-type bounded_crud
    compound-v-resolve-model.py --advisor-eligible --tier standard --job-type bounded_crud
    compound-v-resolve-model.py --select-advisor --executor claude --available codex,claude
    compound-v-resolve-model.py --selftest

Advisor helpers (v2.12, Feature B1):
  * ``advisor_eligible`` — a `standard`-tier / core-slice implementer OR a fast-path
    Claude worker MAY carry an advisor; reviewer/docs/shared_foundation jobs may not.
  * ``select_advisor`` — cross-brand advisor picker restricted to backends with an
    IMPLEMENTED read-only consult path: codex (cross-brand, preferred) > opus fallback
    (backend claude, model opus). cursor/antigravity/devin/opencode have NO consult
    adapter, so they are NEVER offered as advisors. NEVER haiku.

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
# Per-backend tier→model maps. `claude` has two stance variants — cost-aware routes the
# `standard` tier to sonnet (Sonnet 5 via Claude Code's native alias); deep stays opus.
# codex/antigravity/cursor are identical across stances. NEVER 'haiku' anywhere.
_CLAUDE_DEFAULT = {"deep": "opus", "standard": "opus", "light": "sonnet"}
_CLAUDE_COST_AWARE = {"deep": "opus", "standard": "sonnet", "light": "sonnet"}
# GPT-5.6 family (Sol/Terra/Luna), verified live 2026-07-10: all three confirmed working on
# codex-cli 0.144.1. gpt-5.6-sol specifically requires codex-cli >= 0.143.0 (confirmed: broken
# with a clear 400 "requires a newer version of Codex" on 0.142.5, works on 0.144.1) -- an
# under-floor client fails LOUD (not silent; the failure-policy retries once then halts cleanly).
_CODEX = {"deep": "gpt-5.6-sol", "standard": "gpt-5.6-terra", "light": "gpt-5.6-luna"}
# Antigravity (agy): FALLBACK default; the live catalog is discoverable headlessly
# (`agy models </dev/null`), and /v:models/+/v:init pipe it through
# compound-v-discover-models.py to OVERRIDE this map in .claude/compound-v.json. Names
# VERIFIED against `agy models` (1.0.13). Effort is baked into the agy model NAME (no
# separate effort flag); the worker omits --model if the value is empty. Gemini family
# chosen for error-decorrelation; override with --model.
_ANTIGRAVITY = {"deep": "Gemini 3.1 Pro (High)", "standard": "Gemini 3.1 Pro (Low)",
                "light": "Gemini 3.5 Flash (Low)"}
# Cursor (cursor-agent): "auto" is the SAFE DEFAULT for every tier — a FREE plan can ONLY
# use Auto (named models error: "Named models unavailable"). Paid plans override per-tier
# via /v:models — `cursor-agent models` lists the live catalog for manual discovery (not
# auto-ranked: it spans unrelated vendor families with no shared naming convention).
# Lower-trust tier (no kernel sandbox; headless -f required).
_CURSOR = {"deep": "auto", "standard": "auto", "light": "auto"}
# Devin (devin-cli): multi-vendor model broker (like Cursor, unlike Codex/Antigravity's
# single-family catalogs) -- `--model` is a free string, no `devin models`/`--list-models`
# equivalent exists, so this curated map mirrors the Codex pattern (curated +
# user-overridable roster). DOC-CLAIMED aliases (devin-cli 3000.1.27's own --help text
# uses these exact strings as its examples, but no authenticated run has confirmed they
# resolve -- see skills/backend-launcher/adapter-devin.md). Lower-trust tier: devin's
# --sandbox is a live [Research Preview] kernel flag (unlike antigravity/cursor), but its
# non-shell-tool coverage and network confinement are unverified, so it ships in the same
# opt-in/lower-trust tier for v1. NEVER haiku.
_DEVIN = {"deep": "claude-opus-4.6", "standard": "claude-sonnet-4", "light": "gpt-5.5"}
# opencode (opencode-ai): provider-agnostic router -- every cell is a full "provider/model"
# string (e.g. "anthropic/claude-opus-4-6"), and the provider is allowed to DIFFER per
# cell (unlike every other backend's single-vendor map) -- this is the key design point
# from the research: the resolver treats every model string as opaque, so no schema
# change is needed. `light` legitimately points at one of opencode's own curated
# credential-free models (VERIFIED live via `opencode models` with zero stored
# credentials: opencode/mimo-v2.5-free et al) -- the one backend where a real free tier
# exists out of the box. Lower-trust tier: opencode has NO kernel write-confinement and,
# per its own docs, defaults to allowing all operations -- see
# skills/backend-launcher/adapter-opencode.md for the mandatory env-scrub + pinned
# opencode.json mitigation. NEVER haiku anywhere (light is a free model, not haiku).
_OPENCODE = {
    "deep": "anthropic/claude-opus-4-6",
    "standard": "openai/gpt-5.6-terra",
    "light": "opencode/mimo-v2.5-free",
}


def _stance_map(claude_map):
    """Assemble a full {backend -> {tier -> model}} map for one stance. Only the claude
    sub-map varies by stance; codex/antigravity/cursor/devin/opencode are shared
    (read-only)."""
    return {
        "claude": claude_map,
        "codex": _CODEX,
        "antigravity": _ANTIGRAVITY,
        "cursor": _CURSOR,
        "devin": _DEVIN,
        "opencode": _OPENCODE,
    }


# Built-in default map, now keyed by STANCE.
DEFAULT_MODELS_BY_STANCE = {
    "balanced": _stance_map(_CLAUDE_DEFAULT),
    "conservative": _stance_map(_CLAUDE_DEFAULT),
    "cost-aware": _stance_map(_CLAUDE_COST_AWARE),
    "claude-only": _stance_map(_CLAUDE_DEFAULT),
}
# Derived alias so stance-unaware references (selftest loop, the resolve() fallback) keep
# working unchanged: balanced is the default stance.
DEFAULT_MODELS = DEFAULT_MODELS_BY_STANCE["balanced"]

BACKENDS = ("claude", "codex", "antigravity", "cursor", "devin", "opencode")
TIERS = ("deep", "standard", "light")
# `xhigh` is valid iff backend == "codex": it maps to codex's kernel
# model_reasoning_effort dimension, which live-accepts xhigh (verified
# 2026-07-11 on codex-cli 0.144.1). resolve() rejects xhigh for every other
# backend with a clear error naming the rule.
EFFORTS = ("low", "medium", "high", "xhigh")
# Stance vocabulary — DUPLICATED on purpose from compound-v-validate-manifest.py:VALID_STANCES.
# Both scripts are standalone, stdlib-only CLIs; do NOT introduce a shared import. Keep in sync.
VALID_STANCES = ("balanced", "conservative", "cost-aware", "claude-only")

# Default effort pairing when --effort is omitted. Independently tunable per
# task-type by passing --effort explicitly; this is only the fallback.
DEFAULT_EFFORT_FOR_TIER = {"deep": "high", "standard": "medium", "light": "low"}


def _project_config_module():
    """Load the sibling ``compound-v-project-config.py`` by path.

    The filename has hyphens (not an importable module name), so we load it via
    importlib. Returns the module, or ``None`` if it cannot be loaded (in which
    case ``load_config_models`` falls back to its own inline logic — this script
    stays standalone-robust even if the sibling is missing).
    """
    import importlib.util

    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "compound-v-project-config.py")
    try:
        spec = importlib.util.spec_from_file_location("compound_v_project_config", path)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:  # noqa: BLE001 - any load failure -> use the inline fallback
        return None


def load_config_models(config_path):
    """
    Return the ``models`` mapping from a config JSON, or an empty dict.

    Thin wrapper over the shared ``load_project_config`` loader (CR2-11) so the
    resolver and the pre-eval engine read the SAME file with the SAME fail-closed
    rules. Behaviour-preserving: missing file / absent ``models`` → ``{}``;
    non-object root or non-object ``models`` → raise. If the shared loader cannot
    be loaded, an equivalent inline fallback keeps this script standalone.
    """
    if not config_path:
        return {}
    mod = _project_config_module()
    if mod is not None:
        cfg = mod.load_config_file(config_path)  # missing → {}, malformed → raise
        return mod.get_models(cfg)               # absent → {}, non-object → raise
    # Fallback (sibling unavailable): the original inline logic, unchanged.
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


def _config_cell(config_models, stance, backend, tier):
    """Config override for (stance, backend, tier). Supports BOTH the legacy flat shape
    {backend: {tier: model}} (applied to every stance) and the per-stance shape
    {stance: {backend: {tier: model}}}, discriminated by whether EVERY top-level key is a
    stance name. Returns a non-empty model string, or None to fall back to the default map."""
    if not config_models:
        return None
    keys = list(config_models.keys())
    if keys and all(k in VALID_STANCES for k in keys):           # per-stance shape
        stance_cfg = config_models.get(stance)
        backend_map = stance_cfg.get(backend) if isinstance(stance_cfg, dict) else None
    else:                                                         # legacy flat shape
        backend_map = config_models.get(backend)
    if isinstance(backend_map, dict):
        candidate = backend_map.get(tier)
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return None


def _is_provider_model_shaped(model):
    """True iff ``model`` is a genuine non-empty 'provider/model' string: exactly the
    shape opencode's own `-m`/`--model` flag requires (see adapter-opencode.md). A
    bare name (no '/') or a malformed value with an empty side ('anthropic/', '/x')
    would silently resolve here but fail opencode's own model resolution at run
    time, so every opencode resolution — regardless of source (explicit override,
    config override, or the built-in default map) — is shape-checked."""
    if not isinstance(model, str):
        return False
    provider, sep, rest = model.partition("/")
    return bool(sep) and bool(provider.strip()) and bool(rest.strip())


def resolve(backend, tier, effort=None, config_models=None, explicit_model=None,
            stance="balanced", job_type=None, fast_path=False):
    """Resolve to a concrete model. Precedence: explicit_model > config_models > the
    stance's built-in default map. Raises ValueError on unknown backend/tier/effort/stance
    or an unresolvable cell. When ``job_type`` is provided (enough context), the returned
    dict also carries an additive ``advisor_eligible`` boolean; callers that only read
    ``["model"]`` ignore it."""
    if backend not in BACKENDS:
        raise ValueError("unknown backend '%s' (expected one of %s)" % (backend, ", ".join(BACKENDS)))
    if tier not in TIERS:
        raise ValueError("unknown tier '%s' (expected one of %s)" % (tier, ", ".join(TIERS)))
    if effort is not None and effort not in EFFORTS:
        raise ValueError("unknown effort '%s' (expected one of %s)" % (effort, ", ".join(EFFORTS)))
    if effort == "xhigh" and backend != "codex":
        raise ValueError(
            "effort 'xhigh' is not valid for backend '%s': xhigh is codex-only "
            "(kernel: model_reasoning_effort); use high" % backend
        )
    if stance not in VALID_STANCES:
        raise ValueError("unknown stance '%s' (expected one of %s)" % (stance, ", ".join(VALID_STANCES)))

    resolved_effort = effort if effort is not None else DEFAULT_EFFORT_FOR_TIER[tier]

    if explicit_model:
        if backend == "opencode" and not _is_provider_model_shaped(explicit_model):
            raise ValueError(
                "opencode explicit model override '%s' is not a valid "
                "'provider/model' string (must be non-empty on both sides of "
                "exactly one '/'); bare or malformed model names are rejected"
                % explicit_model
            )
        _r = {"backend": backend, "tier": tier, "model": explicit_model, "effort": resolved_effort}
        if job_type is not None:
            _r["advisor_eligible"] = advisor_eligible(
                tier=tier, job_type=job_type, backend=backend, fast_path=fast_path
            )
        return _r

    model = _config_cell(config_models, stance, backend, tier)
    if model is None:
        model = DEFAULT_MODELS_BY_STANCE[stance].get(backend, {}).get(tier)

    if not model:
        raise ValueError(
            "cannot resolve a model for stance '%s' backend '%s' tier '%s' "
            "(no config override and no built-in default)" % (stance, backend, tier)
        )

    if backend == "opencode" and not _is_provider_model_shaped(model):
        raise ValueError(
            "opencode resolved to model '%s' (stance '%s' backend '%s' tier "
            "'%s'), which is not a valid 'provider/model' string; a config "
            "override that isn't shaped as provider/model is rejected"
            % (model, stance, backend, tier)
        )

    result = {"backend": backend, "tier": tier, "model": model, "effort": resolved_effort}
    if job_type is not None:
        result["advisor_eligible"] = advisor_eligible(
            tier=tier, job_type=job_type, backend=backend, fast_path=fast_path
        )
    return result


# --------------------------------------------------------------------------- #
# Advisor eligibility + cross-brand advisor selector (v2.12, Feature B1).
#
# The "cheap executor + on-demand cross-brand advisor" pattern lets a cheap
# implementer (a `standard`-tier / core-slice job, or a fast-path Claude worker)
# consult a DIFFERENT-brand advisor on a hard sub-decision. Two pure helpers:
#
#   advisor_eligible(...) -> bool
#       Is THIS job allowed to carry an advisor? Reviewers, docs, and
#       shared_foundation jobs are structurally ineligible (they are not
#       core-slice implementers); a `standard`-tier implementer OR a fast-path
#       Claude worker is eligible.
#
#   select_advisor(executor_backend, available_backends) -> {advisor_backend, tier, model}
#       Given the executor's backend and the backends available in this run,
#       pick the advisor backend, PREFERRING a different brand than the executor —
#       but ONLY among backends with an implemented read-only consult path:
#           codex (cross-brand, preferred) > opus fallback
#       cursor/antigravity/devin/opencode are NEVER selected as advisors — no consult
#       adapter exists for them, so choosing one would be deterministic death
#       ("unsupported advisor backend"). Opus fallback = backend "claude", model "opus"
#       (always available, never haiku).
# --------------------------------------------------------------------------- #

# Job-type tokens that are NEVER advisor-eligible (substring match, mirroring the
# reviewer-token convention in compound-v-validate-manifest.py). A reviewer, a
# docs job, or a shared_foundation job is not a core-slice implementer.
ADVISOR_INELIGIBLE_TYPE_TOKENS = ("review", "reviewer", "docs", "shared_foundation")

# Non-claude advisor backends with an IMPLEMENTED read-only consult path — the ONLY
# non-claude backends select_advisor may return. codex is the cross-brand preferred
# advisor; the sole other consultable path is the Claude/opus fallback (below).
# cursor/antigravity/devin/opencode have NO consult adapter, so offering them as an
# advisor is deterministic death — they are deliberately excluded. NEVER haiku.
ADVISOR_CONSULTABLE_NONCLAUDE = ("codex",)


def advisor_eligible(tier=None, job_type=None, backend=None, fast_path=False):
    """True iff a job MAY carry an advisor block. Structurally-ineligible job
    types (reviewer/docs/shared_foundation) are rejected regardless of tier; a
    `standard`-tier implementer OR a fast-path Claude worker is eligible."""
    jt = str(job_type or "").strip().lower()
    for tok in ADVISOR_INELIGIBLE_TYPE_TOKENS:
        if tok and tok in jt:
            return False
    b = str(backend or "").strip().lower()
    t = str(tier or "").strip().lower()
    if fast_path and b == "claude":
        return True
    if t == "standard":
        return True
    return False


def select_advisor(executor_backend, available_backends, stance="balanced"):
    """Pick the cross-brand advisor backend, restricted to backends with an IMPLEMENTED
    read-only consult path. Prefer a DIFFERENT brand than the executor: codex > opus
    fallback. cursor/antigravity/devin/opencode are NEVER returned (no consult adapter —
    selecting one would be deterministic 'unsupported advisor backend' death). Returns a
    dict with ``advisor_backend`` / ``tier`` / ``model``. The opus fallback (backend
    'claude', model 'opus') is always available. NEVER haiku."""
    exec_b = str(executor_backend or "").strip().lower()
    avail = set(
        str(b).strip().lower() for b in (available_backends or []) if str(b).strip()
    )
    for cand in ADVISOR_CONSULTABLE_NONCLAUDE:
        if cand in avail and cand != exec_b:
            model = resolve(cand, "deep", stance=stance)["model"]
            return {"advisor_backend": cand, "tier": "deep", "model": model}
    # Opus fallback — the only other backend with an implemented consult path; a
    # different brand than any non-claude executor, and always available.
    return {"advisor_backend": "claude", "tier": "deep", "model": "opus"}


def _main_advisor_eligible(argv):
    """CLI: --advisor-eligible --tier <t> --job-type <jt> [--backend <b>] [--fast-path]
    Prints 'true' or 'false'."""
    parser = argparse.ArgumentParser(
        prog="compound-v-resolve-model.py --advisor-eligible",
        description="Is this job advisor-eligible?",
    )
    parser.add_argument("--advisor-eligible", action="store_true")
    parser.add_argument("--tier", default=None, choices=list(TIERS))
    parser.add_argument("--job-type", default=None)
    parser.add_argument("--backend", default=None, choices=list(BACKENDS))
    parser.add_argument("--fast-path", action="store_true")
    args = parser.parse_args(argv[1:])
    ok = advisor_eligible(
        tier=args.tier, job_type=args.job_type,
        backend=args.backend, fast_path=args.fast_path,
    )
    print("true" if ok else "false")
    return 0


def _main_select_advisor(argv):
    """CLI: --select-advisor --executor <b> --available codex,claude [--stance <s>]
    Prints a JSON object {advisor_backend, tier, model}."""
    parser = argparse.ArgumentParser(
        prog="compound-v-resolve-model.py --select-advisor",
        description="Pick the cross-brand advisor backend.",
    )
    parser.add_argument("--select-advisor", action="store_true")
    parser.add_argument("--executor", required=True,
                        help="the executor backend (advisor prefers a different brand)")
    parser.add_argument("--available", required=True,
                        help="comma-separated list of available backends")
    parser.add_argument("--stance", default="balanced", choices=list(VALID_STANCES))
    args = parser.parse_args(argv[1:])
    available = [b for b in args.available.split(",") if b.strip()]
    result = select_advisor(args.executor, available, stance=args.stance)
    print(json.dumps(result))
    return 0


def main(argv):
    if "--selftest" in argv[1:]:
        return _selftest()
    if "--select-advisor" in argv[1:]:
        return _main_select_advisor(argv)
    if "--advisor-eligible" in argv[1:]:
        return _main_advisor_eligible(argv)

    parser = argparse.ArgumentParser(
        prog="compound-v-resolve-model.py",
        description="Resolve (backend, tier, effort) -> concrete model.",
    )
    parser.add_argument("--backend", required=True, choices=list(BACKENDS))
    parser.add_argument("--tier", required=True, choices=list(TIERS))
    parser.add_argument("--effort", default=None, choices=list(EFFORTS))
    parser.add_argument("--stance", default="balanced", choices=list(VALID_STANCES),
                        help="routing stance (default balanced)")
    parser.add_argument("--config", default=None, help="path to compound-v.json")
    parser.add_argument(
        "--explicit-model",
        default=None,
        help="manifest model override; always wins, skips resolution",
    )
    parser.add_argument("--job-type", default=None,
                        help="job type; when given, output carries advisor_eligible")
    parser.add_argument("--fast-path", action="store_true",
                        help="mark this as a fast-path worker (advisor-eligibility input)")
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
            stance=args.stance,
            job_type=args.job_type,
            fast_path=args.fast_path,
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

    def raises(fn):
        try:
            fn()
            return False
        except ValueError:
            return True

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

    # Devin (multi-vendor broker, curated DOC-CLAIMED aliases) resolves for every tier.
    expect(
        "devin/deep -> claude-opus-4.6",
        resolve("devin", "deep")["model"] == "claude-opus-4.6",
    )
    expect(
        "devin/standard -> claude-sonnet-4",
        resolve("devin", "standard")["model"] == "claude-sonnet-4",
    )
    expect(
        "devin/light -> gpt-5.5",
        resolve("devin", "light")["model"] == "gpt-5.5",
    )

    # opencode (provider-agnostic router): every cell resolves, AND every cell is a
    # genuine "provider/model" string (a bare name would silently pass --model but
    # likely fail opencode's own model resolution) -- the key structural invariant
    # from the design (resolve-model.py treats every cell as opaque; opencode is the
    # one backend where that opaque string legitimately varies its provider prefix
    # per tier).
    expect(
        "opencode/deep -> anthropic/claude-opus-4-6",
        resolve("opencode", "deep")["model"] == "anthropic/claude-opus-4-6",
    )
    expect(
        "opencode/light -> credential-free opencode/* model",
        resolve("opencode", "light")["model"] == "opencode/mimo-v2.5-free",
    )
    expect(
        "every opencode tier cell is a provider/model string",
        all("/" in _OPENCODE[t] for t in TIERS),
    )

    # opencode provider/model shape enforcement: a bare or malformed model is
    # REJECTED regardless of where it came from (explicit override or config
    # override) — never silently accepted and passed to the worker's -m flag.
    expect(
        "opencode explicit bare model rejected",
        raises(lambda: resolve("opencode", "deep", explicit_model="gpt-5.6")),
    )
    expect(
        "opencode explicit malformed model rejected (empty right side)",
        raises(lambda: resolve("opencode", "deep", explicit_model="anthropic/")),
    )
    expect(
        "opencode explicit malformed model rejected (empty left side)",
        raises(lambda: resolve("opencode", "deep", explicit_model="/claude-opus")),
    )
    expect(
        "opencode config-override bare model rejected",
        raises(lambda: resolve(
            "opencode", "deep",
            config_models={"opencode": {"deep": "gpt-5.6"}})),
    )
    expect(
        "opencode explicit provider/model accepted",
        resolve("opencode", "deep", explicit_model="anthropic/claude-opus-4-6")["model"]
        == "anthropic/claude-opus-4-6",
    )
    expect(
        "non-opencode backend is NOT shape-checked (bare model fine)",
        resolve("codex", "deep", explicit_model="gpt-5.6")["model"] == "gpt-5.6",
    )

    # No 'haiku' anywhere in any stance map.
    flat = json.dumps(DEFAULT_MODELS_BY_STANCE).lower()
    expect("no haiku in any stance map", "haiku" not in flat)

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

    # xhigh is codex-only: `xhigh` is valid iff backend == codex (live-verified
    # 2026-07-11 on codex-cli 0.144.1); every other backend rejects it with a
    # clear error naming the rule.
    expect(
        "codex+xhigh accepted",
        resolve("codex", "deep", effort="xhigh")["effort"] == "xhigh",
    )
    expect(
        "claude+xhigh rejected",
        raises(lambda: resolve("claude", "deep", effort="xhigh")),
    )
    expect(
        "antigravity+xhigh rejected",
        raises(lambda: resolve("antigravity", "deep", effort="xhigh")),
    )
    expect(
        "cursor+xhigh rejected",
        raises(lambda: resolve("cursor", "deep", effort="xhigh")),
    )
    expect(
        "devin+xhigh rejected",
        raises(lambda: resolve("devin", "deep", effort="xhigh")),
    )
    expect(
        "opencode+xhigh rejected",
        raises(lambda: resolve("opencode", "deep", effort="xhigh")),
    )
    _xhigh_msg = ""
    try:
        resolve("claude", "deep", effort="xhigh")
    except ValueError as e:
        _xhigh_msg = str(e)
    expect(
        "claude+xhigh error names the rule",
        "xhigh is codex-only (kernel: model_reasoning_effort); use high"
        in _xhigh_msg,
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

    # --- stance-aware resolution (v2.4.0) ---
    expect("default stance is balanced (claude/standard -> opus)",
           resolve("claude", "standard")["model"] == "opus")
    expect("cost-aware claude/standard -> sonnet",
           resolve("claude", "standard", stance="cost-aware")["model"] == "sonnet")
    expect("cost-aware claude/deep stays opus (sensitive/reviewer guard)",
           resolve("claude", "deep", stance="cost-aware")["model"] == "opus")
    expect("cost-aware claude/light -> sonnet",
           resolve("claude", "light", stance="cost-aware")["model"] == "sonnet")
    expect("cost-aware codex/standard unchanged",
           resolve("codex", "standard", stance="cost-aware")["model"]
           == DEFAULT_MODELS["codex"]["standard"])
    expect("balanced claude/standard -> opus",
           resolve("claude", "standard", stance="balanced")["model"] == "opus")
    expect("unknown stance raises", raises(lambda: resolve("claude", "deep", stance="turbo")))
    _flat = {"claude": {"standard": "flat-override"}}
    expect("legacy flat config applies under balanced",
           resolve("claude", "standard", config_models=_flat)["model"] == "flat-override")
    expect("legacy flat config applies under cost-aware too",
           resolve("claude", "standard", stance="cost-aware", config_models=_flat)["model"] == "flat-override")
    _perstance = {"cost-aware": {"claude": {"standard": "perstance-override"}}}
    expect("per-stance config overrides its stance",
           resolve("claude", "standard", stance="cost-aware", config_models=_perstance)["model"]
           == "perstance-override")
    expect("per-stance config leaves other stances on built-in default",
           resolve("claude", "standard", stance="balanced", config_models=_perstance)["model"] == "opus")

    # --- load_config_models wrapper over the shared load_project_config (CR2-11) ---
    import tempfile
    with tempfile.TemporaryDirectory() as _td:
        _cp = os.path.join(_td, "compound-v.json")
        with open(_cp, "w") as _fh:
            json.dump({"models": {"codex": {"deep": "gpt-from-file"}}}, _fh)
        _m = load_config_models(_cp)
        expect("wrapper reads models from a real file",
               _m == {"codex": {"deep": "gpt-from-file"}})
        expect("wrapper-read config applies through resolve()",
               resolve("codex", "deep", config_models=_m)["model"] == "gpt-from-file")
        _missing = os.path.join(_td, "nope.json")
        expect("wrapper: missing file -> {}", load_config_models(_missing) == {})
        with open(_cp, "w") as _fh:
            _fh.write("[not, an, object]")
        expect("wrapper: malformed config raises",
               raises(lambda: load_config_models(_cp)))
    # Behaviour-preserving guarantees the dispatcher relies on between waves:
    expect("balanced claude/deep -> opus (regression guard)",
           resolve("claude", "deep")["model"] == "opus")
    expect("balanced claude/standard -> opus (regression guard)",
           resolve("claude", "standard")["model"] == "opus")

    # --- advisor eligibility (v2.12, B1) ---
    expect("standard-tier implementer is advisor-eligible",
           advisor_eligible(tier="standard", job_type="bounded_crud") is True)
    expect("fast-path Claude worker is advisor-eligible (tier not standard)",
           advisor_eligible(tier="light", job_type="bounded_crud",
                            backend="claude", fast_path=True) is True)
    expect("deep-tier non-fast-path implementer is NOT advisor-eligible",
           advisor_eligible(tier="deep", job_type="bounded_crud") is False)
    expect("light-tier docs job is NOT advisor-eligible",
           advisor_eligible(tier="light", job_type="docs") is False)
    expect("reviewer job is NOT advisor-eligible",
           advisor_eligible(tier="deep", job_type="review") is False)
    expect("shared_foundation is NOT advisor-eligible even at standard tier",
           advisor_eligible(tier="standard", job_type="shared_foundation") is False)
    expect("fast-path but non-claude backend is NOT eligible via fast-path alone",
           advisor_eligible(tier="light", job_type="bounded_crud",
                            backend="codex", fast_path=True) is False)
    # resolve() carries advisor_eligible ONLY when job_type is supplied (additive).
    expect("resolve without job_type has NO advisor_eligible key (backward compat)",
           "advisor_eligible" not in resolve("claude", "standard"))
    expect("resolve WITH job_type carries advisor_eligible=True",
           resolve("claude", "standard", job_type="bounded_crud")["advisor_eligible"] is True)
    expect("resolve WITH docs job_type carries advisor_eligible=False",
           resolve("claude", "light", job_type="docs")["advisor_eligible"] is False)
    expect("resolve advisor_eligible does not disturb model key",
           resolve("claude", "standard", job_type="bounded_crud")["model"] == "opus")

    # --- cross-brand advisor selector (v2.12, B1) ---
    expect("selector prefers codex over opus when codex available",
           select_advisor("claude", ["codex", "claude"])["advisor_backend"] == "codex")
    expect("selector codex advisor resolves to a concrete deep model",
           select_advisor("claude", ["codex", "claude"])["model"]
           == DEFAULT_MODELS["codex"]["deep"])
    expect("selector falls back to opus when only claude available",
           select_advisor("claude", ["claude"])
           == {"advisor_backend": "claude", "tier": "deep", "model": "opus"})
    expect("selector skips SAME-brand executor (codex exec) -> opus fallback",
           select_advisor("codex", ["codex", "claude"])["advisor_backend"] == "claude")
    # FIX 6: only codex + the opus fallback have an implemented read-only consult path.
    # cursor/antigravity/devin/opencode must NEVER be offered as advisors (no consult
    # adapter => deterministic 'unsupported advisor backend' death).
    expect("selector does NOT offer cursor -> opus fallback (not cursor)",
           select_advisor("claude", ["cursor", "claude"])
           == {"advisor_backend": "claude", "tier": "deep", "model": "opus"})
    expect("selector does NOT offer antigravity/devin/opencode -> opus fallback",
           select_advisor("claude", ["antigravity", "devin", "opencode", "claude"])
           == {"advisor_backend": "claude", "tier": "deep", "model": "opus"})
    expect("selector still picks codex when available (executor claude)",
           select_advisor("claude", ["codex", "claude"])["advisor_backend"] == "codex")
    expect("selector prefers codex even when a non-consultable brand is also present",
           select_advisor("claude", ["cursor", "codex"])["advisor_backend"] == "codex")
    expect("selector opus fallback is never haiku",
           select_advisor("codex", [])["model"] == "opus")

    # Unknown backend / tier / effort raise.
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
