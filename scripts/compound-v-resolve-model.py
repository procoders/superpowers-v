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
  tier   ∈ { frontier, deep, standard, light }
  effort ∈ { low, medium, high, xhigh }
                                   (orthogonal hint; passed through, default
                                    pairing deep→high / standard→medium /
                                    light→low when --effort omitted.
                                    `xhigh` is valid iff backend is codex —
                                    every other backend rejects it with a clear
                                    error naming the rule; use `high` instead)

Output: a single JSON object on stdout, e.g.
  {"backend": "codex", "tier": "deep", "model": "gpt-6.1-sol", "effort": "high"}

For `backend: claude`, the CLI (not the `resolve()` function — see
`apply_effort_cap`) also reads the project's and user's Claude Code
`settings.json`/`settings.local.json` for a `maxEffortLevel` cap
(Claude Code 2.1.267+) and adds `effort_capped`:
  {"backend": "claude", "tier": "deep", "model": "opus", "effort": "medium",
   "effort_capped": {"requested": "high", "cap": "medium",
                      "source": ".claude/settings.json"}}
`effort_capped` is `null` when nothing capped the request (including on every
non-claude backend, which `maxEffortLevel` cannot affect).

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
# Per-backend tier→model maps. `claude` has two stance variants — cost-aware routes the
# `standard` tier to sonnet (Sonnet 5 via Claude Code's native alias); deep stays opus.
# codex/antigravity/cursor are identical across stances. NEVER 'haiku' anywhere.
#
# The claude ladder, set by the maintainer on 2026-09-02, on two axes:
#   * EXECUTION vs JUDGMENT. Sonnet executes — a spec that survived brainstorming
#     and planning, HTML/CSS, Node plumbing, translations, and READING code.
#     Opus judges — deciding, and connecting parts of code to each other.
#   * COUPLING. Business logic with many code-level dependencies is Opus, however
#     mechanical each individual edit looks.
# `frontier` is the extreme case and is deliberately hard to reach: it is what a
# re-attempt escalates INTO, not a seat a planner routinely assigns.
_CLAUDE_BALANCED = {"frontier": "fable", "deep": "opus",
                    "standard": "sonnet", "light": "sonnet"}
# Conservative keeps `standard` on Opus — that is what the stance means.
_CLAUDE_CONSERVATIVE = {"frontier": "fable", "deep": "opus",
                        "standard": "opus", "light": "sonnet"}
# Cost-aware never reaches for the most expensive seat; its ceiling is Opus.
_CLAUDE_COST_AWARE = {"frontier": "opus", "deep": "opus",
                      "standard": "sonnet", "light": "sonnet"}
# GPT-6 family (Astra/Sol/Luna), probed 2026-09-24 on codex-cli 0.156.1 via
# `codex debug models` (the raw catalog dump; Codex now HAS a model-list command --
# several docs in this repo used to say otherwise, which is now false). Catalog
# order by priority: gpt-6-astra ("Frontier intelligence for the most demanding
# work"), gpt-6-sol ("Workhorse model for coding and everyday work"), gpt-6-luna
# ("Fast and affordable model for easier tasks") -- there is no gpt-6-terra. All
# three answered a trivial `codex exec` with this repo's pinned flag set (rc 0,
# `thread.started` present), so the flag set is re-verified on 0.156.1.
# 2026-09-30, codex-cli 0.159.1: `gpt-6.1-sol` ("Latest workhorse model for coding and
# everyday work") joined at priority 1, gpt-6-sol became "Previous generation workhorse",
# and gpt-6-astra (priority 2) is still the frontier model. gpt-6.1-sol and gpt-6-astra
# both answered with the pinned flag set at xhigh (rc 0, `thread.started`), so
# deep/standard move to gpt-6.1-sol and frontier stays on Astra.
# `deep` and `standard` deliberately SHARE gpt-6.1-sol and differ only by effort --
# tier and effort are orthogonal axes in this resolver, and Sol has no separate
# "standard-strength" sibling the way Astra/Sol/Luna cover frontier/deep/light.
# The older GPT-5.6 family (Sol/Terra/Luna, verified live 2026-07-10 on codex-cli
# 0.144.1) is listed "Older ..." in the catalog and still works -- gpt-5.5 is
# also still listed but retires 2026-10-14 (upgrade target per the catalog: gpt-6.1-sol as of 0.160.0). An
# under-floor client fails LOUD (not silent; the failure-policy retries once
# then halts cleanly).
_CODEX = {"frontier": "gpt-6-astra", "deep": "gpt-6.1-sol",
          "standard": "gpt-6.1-sol", "light": "gpt-6-luna"}
# Antigravity (agy): FALLBACK default; the live catalog is discoverable headlessly
# (`agy models </dev/null`), and /v:models/+/v:init pipe it through
# compound-v-discover-models.py to OVERRIDE this map in .claude/compound-v.json. Names
# VERIFIED against `agy models` (1.1.22, 2026-09-03: 3.6/3.7/3.8 Flash + 3.1 Pro; light = the NEWEST Flash at Low). Effort is baked into the agy model NAME (no
# separate effort flag); the worker omits --model if the value is empty. Gemini family
# chosen for error-decorrelation; override with --model.
_ANTIGRAVITY = {"frontier": "Gemini 3.1 Pro (High)", "deep": "Gemini 3.1 Pro (High)",
                "standard": "Gemini 3.1 Pro (Low)", "light": "Gemini 3.8 Flash (Low)"}
# Cursor (cursor-agent): "auto" is the SAFE DEFAULT for every tier — a FREE plan can ONLY
# use Auto (named models error: "Named models unavailable"). Paid plans override per-tier
# via /v:models — `cursor-agent models` lists the live catalog for manual discovery (not
# auto-ranked: it spans unrelated vendor families with no shared naming convention).
# Lower-trust tier (no kernel sandbox; headless -f required).
_CURSOR = {"frontier": "auto", "deep": "auto", "standard": "auto", "light": "auto"}
# opencode (opencode-ai): provider-agnostic router -- every cell is a full "provider/model"
# string (e.g. "anthropic/claude-opus-5-5"), and the provider is allowed to DIFFER per
# cell (unlike every other backend's single-vendor map) -- this is the key design point
# from the research: the resolver treats every model string as opaque, so no schema
# change is needed. `light` legitimately points at one of opencode's own curated
# credential-free models (VERIFIED live via `opencode models` with zero stored
# credentials: opencode/mimo-v2.5-free et al) -- the one backend where a real free tier
# exists out of the box. Lower-trust tier: opencode has NO kernel write-confinement and,
# per its own docs, defaults to allowing all operations -- see
# skills/backend-launcher/adapter-opencode.md for the mandatory env-scrub + pinned
# opencode.json mitigation. NEVER haiku anywhere (light is a free model, not haiku).
# 2026-10-05: frontier/deep -> anthropic/claude-opus-5-5 and standard -> openai/gpt-6.1-sol
# (were claude-opus-4-6 and gpt-5.6-terra). Checked against models.dev, the registry
# opencode reads its catalog from: both ids are listed under their providers there.
# NOT run through `opencode run` -- this machine has no anthropic/openai provider
# configured in opencode -- so treat them as registry-verified, not live-verified.
_OPENCODE = {
    "frontier": "anthropic/claude-opus-5-5",
    "deep": "anthropic/claude-opus-5-5",
    "standard": "openai/gpt-6.1-sol",
    "light": "opencode/mimo-v2.5-free",
}


def _stance_map(claude_map):
    """Assemble a full {backend -> {tier -> model}} map for one stance. Only the claude
    sub-map varies by stance; codex/antigravity/cursor/opencode are shared
    (read-only)."""
    return {
        "claude": claude_map,
        "codex": _CODEX,
        "antigravity": _ANTIGRAVITY,
        "cursor": _CURSOR,
        "opencode": _OPENCODE,
    }


# Built-in default map, now keyed by STANCE.
DEFAULT_MODELS_BY_STANCE = {
    "balanced": _stance_map(_CLAUDE_BALANCED),
    "conservative": _stance_map(_CLAUDE_CONSERVATIVE),
    "cost-aware": _stance_map(_CLAUDE_COST_AWARE),
    "claude-only": _stance_map(_CLAUDE_BALANCED),
}
# Derived alias so stance-unaware references (selftest loop, the resolve() fallback) keep
# working unchanged: balanced is the default stance.
DEFAULT_MODELS = DEFAULT_MODELS_BY_STANCE["balanced"]

BACKENDS = ("claude", "codex", "antigravity", "cursor", "opencode")
TIERS = ("frontier", "deep", "standard", "light")
# `xhigh` is valid iff backend == "codex": it maps to codex's kernel
# model_reasoning_effort dimension, which live-accepts xhigh (verified
# 2026-07-11 on codex-cli 0.144.1, re-verified 2026-09-24 on 0.156.1).
# resolve() rejects xhigh for every other backend with a clear error naming
# the rule. The 2026-09-24 GPT-6 catalog probe (`codex debug models`) also
# lists `ultra` (astra/sol only -- "Maximum reasoning with automatic task
# delegation") and `max` above xhigh on the ladder; NEITHER is adopted into
# this vocabulary. `ultra` auto-delegates to sub-agents that would write
# outside a job's declared lane, breaking the scope-gate model; `max` is
# simply not adopted this release. Both stay routable only by an explicit
# --explicit-model / manifest override, never through the tier/effort map.
EFFORTS = ("low", "medium", "high", "xhigh")
# Stance vocabulary — DUPLICATED on purpose from compound-v-validate-manifest.py:VALID_STANCES.
# Both scripts are standalone, stdlib-only CLIs; do NOT introduce a shared import. Keep in sync.
VALID_STANCES = ("balanced", "conservative", "cost-aware", "claude-only")

# Default effort pairing when --effort is omitted. Independently tunable per
# task-type by passing --effort explicitly; this is only the fallback.
DEFAULT_EFFORT_FOR_TIER = {"frontier": "high", "deep": "high",
                           "standard": "medium", "light": "low"}

# --------------------------------------------------------------------------- #
# Effort cap from Claude Code's own `maxEffortLevel` setting (2.1.267+).
#
# Verified against https://code.claude.com/docs/en/settings-reference (fetched
# via curl of the `.md` source; WebFetch's own summary of this page truncated
# before the actual `### maxEffortLevel` / `### modelSettings` bodies, so the
# quotes below come straight from the underlying markdown):
#
#   maxEffortLevel: "Cap the effort level a session can use, leaving lower
#   levels available. Any higher level runs at the cap instead, including one
#   from /effort, the /model picker, --effort, CLAUDE_CODE_EFFORT_LEVEL, a
#   skill's or subagent's `effort` frontmatter, or the model's own default. ...
#   Scope: Any file. ... When several scopes set a cap, the lowest applies, so
#   a cap set in one scope can't be raised from another. Type: string, one of
#   "low", "medium", "high", "xhigh", or "max". A "max" value sets no cap. ...
#   Per-model caps: add maxEffortLevel to a model's modelSettings entry. That
#   entry REPLACES this key for the model only within the settings source that
#   sets both ... Set "max" there to exempt the model from that source's cap;
#   Claude Code still applies caps from other sources."
#
#   modelSettings: "Type: object mapping a model name to an object with an
#   effortLevel field ..., a maxEffortLevel field, or both." Claude Code itself
#   "matches that model's alias, date-suffixed, [1m], and recognized
#   provider-specific IDs to the same entry" — that alias table is internal to
#   Claude Code; this script has no access to it (see _alias_matches_model_key).
#
# NOTE on the task's original phrasing ("takes the LOWEST maxEffortLevel found,
# top-level or per-model when present"): a naive min-of-everything gets the
# doc's own worked example wrong (top-level "medium" + per-model "max" on one
# model means UNCAPPED for that model, not "medium"). The correct algorithm,
# implemented below, is per-file first (per-model REPLACES top-level within
# that one file), then MIN across files.
#
# This only ever caps `backend: claude` jobs — `maxEffortLevel` is a Claude
# Code client setting; it has no meaning for a codex/antigravity/cursor/
# opencode worker process, which Claude Code never applies it to.
# --------------------------------------------------------------------------- #

# Same ladder the doc states for maxEffortLevel. `max` is a cap-only sentinel
# ("sets no cap") — this resolver's own EFFORTS never produces "max" as a
# *requested* value — but it still needs a rank, above xhigh, purely so the
# MIN-across-files comparison below treats an exempting per-model "max" as
# "never the tightest cap in the room."
EFFORT_RANK = {"low": 0, "medium": 1, "high": 2, "xhigh": 3, "max": 4}


def _user_claude_dir():
    """``~/.claude`` unless overridden — the exact precedence
    ``compound-v-transcript-watch.py:session_roots`` already uses for the same
    directory (mirrored here, not imported: that script is a standalone CLI
    with no shared-library role, per CONVENTIONS.md keep-in-sync-by-comment
    style already used elsewhere in this file)."""
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")


def _project_claude_dir(config_path=None, repo_dir=None):
    """The project ``.claude/`` directory to read ``settings.json`` /
    ``settings.local.json`` from. Every real caller already passes
    ``--config .claude/compound-v.json`` (execution-manifest.md), so prefer the
    directory that already holds ``--config`` — no new flag needed on existing
    call sites. Falls back to ``<repo_dir or cwd>/.claude`` for a caller that
    passes neither (e.g. an explicit-model-only resolution)."""
    if config_path:
        parent = os.path.dirname(os.path.abspath(config_path))
        if os.path.basename(parent) == ".claude":
            return parent
    return os.path.join(os.path.abspath(repo_dir or os.getcwd()), ".claude")


def default_settings_paths(config_path=None, repo_dir=None):
    """Ordered ``[(path, label), ...]`` of the Claude Code settings files this
    resolver reads **read-only** to compute an effort cap: project settings,
    project LOCAL settings, then the user's own settings. This does **not**
    reach organization-managed settings (a separate, OS-specific path — see
    /docs/en/managed-settings) — a managed ``maxEffortLevel`` still applies at
    runtime; this resolver just can't see it, so a job can still get silently
    capped by the harness even when this function reports ``effort_capped:
    null``. Order only decides the tie-break for which path lands in
    ``effort_capped.source`` when two files set the identical lowest cap — the
    cap value itself is a MIN over every file (see effective_effort_cap), so
    read order never changes the *answer*, only its attribution."""
    claude_dir = _project_claude_dir(config_path, repo_dir)
    user_dir = _user_claude_dir()
    project = os.path.join(claude_dir, "settings.json")
    local = os.path.join(claude_dir, "settings.local.json")
    user = os.path.join(user_dir, "settings.json")
    return [(project, project), (local, local), (user, user)]


def _load_settings_file(path):
    """Parsed dict for one settings JSON file, or ``None`` if it is missing,
    unreadable, not valid JSON, or its root is not an object. Read-only; never
    raises — a settings file this resolver can't parse degrades to "sets no
    cap", never a crash (this is a routing side-lookup, not the resolver's
    contract)."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _alias_matches_model_key(model, key):
    """Best-effort match between the resolver's own tier alias (``opus`` /
    ``sonnet`` / ``fable``) and a ``modelSettings`` key a human wrote in their
    OWN settings file. Claude Code's real alias table (canonical id, dated
    snapshot, ``[1m]`` suffix, provider-specific id — settings-reference.md
    `modelSettings`) is internal and unavailable here, so this is deliberately
    narrower: an exact match, or a key whose ``-``-separated segments contain
    the alias (covers the realistic case of a canonical id like
    ``claude-opus-5`` written for the alias ``opus``). A cap this narrower
    match misses is invisible to THIS script but still applies at runtime."""
    if key == model:
        return True
    return model in key.split("-")


def _file_effort_cap(settings, model):
    """The effective ``maxEffortLevel`` ONE settings dict sets for ``model``,
    or ``None`` if it sets none. A matching ``modelSettings.<key>`` entry
    REPLACES the top-level ``maxEffortLevel`` for that model within this one
    file — it does not additionally lower it — so a per-model ``"max"`` here
    means this file sets NO cap for the model even under a stricter top-level
    key. Malformed values (wrong type, unrecognized level name) are ignored."""
    if not isinstance(settings, dict):
        return None
    model_settings = settings.get("modelSettings")
    if isinstance(model_settings, dict):
        for key, entry in model_settings.items():
            if not isinstance(entry, dict) or not _alias_matches_model_key(model, str(key)):
                continue
            per_model = entry.get("maxEffortLevel")
            if isinstance(per_model, str) and per_model in EFFORT_RANK:
                return per_model  # replaces the top-level key for this model
    top = settings.get("maxEffortLevel")
    if isinstance(top, str) and top in EFFORT_RANK:
        return top
    return None


def effective_effort_cap(model, settings_paths):
    """``(cap, source)`` — the LOWEST per-file effective cap (see
    ``_file_effort_cap``) across ``settings_paths`` for ``model``, or
    ``(None, None)`` if none of them cap it. An overall winning cap of
    ``"max"`` means, per the doc, no cap at all — return ``(None, None)`` for
    it rather than a cap named "max"."""
    best_cap = None
    best_source = None
    for path, label in settings_paths:
        cap = _file_effort_cap(_load_settings_file(path), model)
        if cap is None:
            continue
        if best_cap is None or EFFORT_RANK[cap] < EFFORT_RANK[best_cap]:
            best_cap, best_source = cap, label
    if best_cap == "max":
        return None, None
    return best_cap, best_source


def apply_effort_cap(result, settings_paths):
    """Return a NEW result dict with ``effort_capped`` added, lowering
    ``effort`` to the cap when the resolved effort ranks above it. Only
    ``backend: claude`` results are affected — ``maxEffortLevel`` is a Claude
    Code client setting with no meaning for an external worker process.

    Deliberately kept OUT of ``resolve()``: that function is imported and
    called directly (not just via subprocess) by
    ``compound-v-epic-arbiter.py`` and ``compound-v-classify-request.py``, and
    it must stay a pure function of its arguments — no filesystem reads. Only
    ``main()`` calls this, after ``resolve()`` returns."""
    out = dict(result)
    if out.get("backend") != "claude":
        out["effort_capped"] = None
        return out
    requested = out.get("effort")
    cap, source = effective_effort_cap(out.get("model"), settings_paths)
    if cap is not None and requested in EFFORT_RANK and EFFORT_RANK[requested] > EFFORT_RANK[cap]:
        out["effort_capped"] = {"requested": requested, "cap": cap, "source": source}
        out["effort"] = cap
    else:
        out["effort_capped"] = None
    return out


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
            stance="balanced"):
    """Resolve to a concrete model. Precedence: explicit_model > config_models > the
    stance's built-in default map. Raises ValueError on unknown backend/tier/effort/stance
    or an unresolvable cell."""
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
        return {"backend": backend, "tier": tier, "model": explicit_model,
                "effort": resolved_effort}

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

    return {"backend": backend, "tier": tier, "model": model, "effort": resolved_effort}


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
    parser.add_argument("--stance", default="balanced", choices=list(VALID_STANCES),
                        help="routing stance (default balanced)")
    parser.add_argument("--config", default=None, help="path to compound-v.json")
    parser.add_argument(
        "--explicit-model",
        default=None,
        help="manifest model override; always wins, skips resolution",
    )
    parser.add_argument(
        "--repo-dir",
        default=None,
        help=(
            "project root to locate .claude/settings.json and settings.local.json "
            "under (for the maxEffortLevel cap); default is --config's own "
            "directory when it ends in .claude, else the current directory"
        ),
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
            stance=args.stance,
        )
    except ValueError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        return 1

    settings_paths = default_settings_paths(config_path=args.config, repo_dir=args.repo_dir)
    result = apply_effort_cap(result, settings_paths)

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

    # opencode (provider-agnostic router): every cell resolves, AND every cell is a
    # genuine "provider/model" string (a bare name would silently pass --model but
    # likely fail opencode's own model resolution) -- the key structural invariant
    # from the design (resolve-model.py treats every cell as opaque; opencode is the
    # one backend where that opaque string legitimately varies its provider prefix
    # per tier).
    expect(
        "opencode/deep -> anthropic/claude-opus-5-5",
        resolve("opencode", "deep")["model"] == "anthropic/claude-opus-5-5",
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
        resolve("opencode", "deep", explicit_model="anthropic/claude-opus-5-5")["model"]
        == "anthropic/claude-opus-5-5",
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
    expect("default stance is balanced (claude/standard -> sonnet)",
           resolve("claude", "standard")["model"] == "sonnet")
    expect("cost-aware claude/standard -> sonnet",
           resolve("claude", "standard", stance="cost-aware")["model"] == "sonnet")
    expect("cost-aware claude/deep stays opus (sensitive/reviewer guard)",
           resolve("claude", "deep", stance="cost-aware")["model"] == "opus")
    expect("cost-aware claude/light -> sonnet",
           resolve("claude", "light", stance="cost-aware")["model"] == "sonnet")
    expect("cost-aware codex/standard unchanged",
           resolve("codex", "standard", stance="cost-aware")["model"]
           == DEFAULT_MODELS["codex"]["standard"])
    expect("balanced claude/standard -> sonnet (execution, not judgment)",
           resolve("claude", "standard", stance="balanced")["model"] == "sonnet")
    expect("conservative claude/standard stays opus",
           resolve("claude", "standard", stance="conservative")["model"] == "opus")
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
           resolve("claude", "standard", stance="balanced", config_models=_perstance)["model"] == "sonnet")

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
    expect("balanced claude/standard -> sonnet (regression guard)",
           resolve("claude", "standard")["model"] == "sonnet")

    # --- the frontier tier (v3.0.5) -------------------------------------------
    # Fable is the extreme seat. It exists so a re-attempt has somewhere to
    # escalate INTO; it is not a routine planner assignment.
    expect("balanced claude/frontier -> fable",
           resolve("claude", "frontier")["model"] == "fable")
    expect("conservative claude/frontier -> fable",
           resolve("claude", "frontier", stance="conservative")["model"] == "fable")
    expect("cost-aware never reaches fable (frontier caps at opus)",
           resolve("claude", "frontier", stance="cost-aware")["model"] == "opus")
    expect("frontier pairs with high effort by default",
           resolve("claude", "frontier")["effort"] == "high")
    expect("frontier resolves on every backend",
           all(resolve(b, "frontier")["model"] for b in BACKENDS))
    expect("no tier resolves to haiku on any backend or stance",
           not any("haiku" in str(DEFAULT_MODELS_BY_STANCE[st][b][t]).lower()
                   for st in VALID_STANCES for b in BACKENDS for t in TIERS))
    expect("every stance/backend cell is populated for every tier",
           all(isinstance(DEFAULT_MODELS_BY_STANCE[st][b].get(t), str)
               and DEFAULT_MODELS_BY_STANCE[st][b][t].strip()
               for st in VALID_STANCES for b in BACKENDS for t in TIERS))
    # Pin the literal codex default map (2026-09-24 GPT-6 update) -- the structural checks
    # above ("frontier resolves", "no haiku", "every cell populated") pass regardless of
    # WHICH model each cell names, so a stale or wrong string would slip through unnoticed
    # without this exact-match guard. frontier/light are the distinct rungs (astra/luna);
    # deep and standard deliberately share gpt-6.1-sol, differing only by effort.
    expect("codex default map matches the 2026-09-24 GPT-6 decision",
           DEFAULT_MODELS["codex"] == {"frontier": "gpt-6-astra", "deep": "gpt-6.1-sol",
                                       "standard": "gpt-6.1-sol", "light": "gpt-6-luna"})

    # --- effort cap from Claude Code settings (Fact 1, maxEffortLevel 2.1.267+) ---
    def _write_json(path, obj):
        with open(path, "w") as fh:
            json.dump(obj, fh)

    with tempfile.TemporaryDirectory() as _sd:
        _proj = os.path.join(_sd, "settings.json")
        _local = os.path.join(_sd, "settings.local.json")
        _user = os.path.join(_sd, "user-settings.json")
        _paths = [(_proj, ".claude/settings.json"),
                  (_local, ".claude/settings.local.json"),
                  (_user, "~/.claude/settings.json")]

        _write_json(_proj, {"maxEffortLevel": "medium"})
        _write_json(_local, {})
        _write_json(_user, {})
        capped = apply_effort_cap(resolve("claude", "deep"), _paths)  # default effort: high
        expect(
            "cap below request -> capped with source",
            capped["effort"] == "medium"
            and capped["effort_capped"] == {
                "requested": "high", "cap": "medium", "source": ".claude/settings.json",
            },
        )

        _write_json(_proj, {"maxEffortLevel": "xhigh"})
        capped = apply_effort_cap(resolve("claude", "light"), _paths)  # default effort: low
        expect(
            "cap above request -> effort_capped null",
            capped["effort"] == "low" and capped["effort_capped"] is None,
        )

        _write_json(_proj, {
            "maxEffortLevel": "xhigh",
            "modelSettings": {"opus": {"maxEffortLevel": "low"}},
        })
        capped = apply_effort_cap(resolve("claude", "deep"), _paths)  # -> opus, effort high
        expect(
            "per-model cap overrides top-level when lower",
            capped["effort"] == "low" and capped["effort_capped"]["cap"] == "low",
        )

        # Doc's own worked example: a per-model "max" REPLACES (never intersects
        # with) a stricter top-level cap within the SAME file, so the model is
        # fully exempt from this file even though its top-level cap is stricter.
        _write_json(_proj, {
            "maxEffortLevel": "medium",
            "modelSettings": {"opus": {"maxEffortLevel": "max"}},
        })
        capped = apply_effort_cap(resolve("claude", "deep"), _paths)
        expect(
            "per-model max exempts the model despite a stricter top-level cap",
            capped["effort"] == "high" and capped["effort_capped"] is None,
        )

        # modelSettings keyed by a canonical id (not the bare alias) still
        # matches, via the narrower segment-based heuristic.
        _write_json(_proj, {"modelSettings": {"claude-opus-5": {"maxEffortLevel": "low"}}})
        capped = apply_effort_cap(resolve("claude", "deep"), _paths)
        expect(
            "canonical-id modelSettings key matches the opus alias",
            capped["effort_capped"] is not None and capped["effort_capped"]["cap"] == "low",
        )

        # Malformed settings (wrong types) are ignored, never a crash.
        _write_json(_proj, {"maxEffortLevel": 3})
        _write_json(_local, {"modelSettings": "not-a-map"})
        _write_json(_user, "not-an-object")
        capped = apply_effort_cap(resolve("claude", "deep"), _paths)
        expect(
            "malformed settings ignored, no crash",
            capped["effort_capped"] is None and capped["effort"] == "high",
        )

        # A non-claude backend is never capped, even with a matching restrictive
        # file present.
        _write_json(_proj, {"maxEffortLevel": "low"})
        _write_json(_local, {})
        _write_json(_user, {})
        r = resolve("codex", "deep")
        capped = apply_effort_cap(r, _paths)
        expect(
            "non-claude backend never capped",
            capped["effort"] == r["effort"] and capped["effort_capped"] is None,
        )

        # The lowest cap across scopes wins, wherever it lives.
        _write_json(_proj, {"maxEffortLevel": "medium"})
        _write_json(_user, {"maxEffortLevel": "low"})
        capped = apply_effort_cap(resolve("claude", "deep"), _paths)
        expect(
            "lowest cap across scopes wins",
            capped["effort_capped"]["cap"] == "low"
            and capped["effort_capped"]["source"] == "~/.claude/settings.json",
        )

        # No settings files at all -> uncapped, no crash.
        os.remove(_proj)
        os.remove(_local)
        os.remove(_user)
        capped = apply_effort_cap(resolve("claude", "deep"), _paths)
        expect(
            "missing settings files -> uncapped, no crash",
            capped["effort_capped"] is None and capped["effort"] == "high",
        )

        # default_settings_paths wiring: CLAUDE_CONFIG_DIR relocates the user
        # file, and a --config under a literal .claude/ dir relocates the
        # project files, with no new flag needed at real call sites.
        _proj_dir = os.path.join(_sd, "proj", ".claude")
        os.makedirs(_proj_dir)
        _write_json(os.path.join(_proj_dir, "settings.json"), {"maxEffortLevel": "medium"})
        _user_dir = os.path.join(_sd, "userhome")
        os.makedirs(_user_dir)
        _write_json(os.path.join(_user_dir, "settings.json"), {"maxEffortLevel": "low"})
        _old_cfgdir = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = _user_dir
        try:
            _dsp = default_settings_paths(
                config_path=os.path.join(_proj_dir, "compound-v.json")
            )
            capped = apply_effort_cap(resolve("claude", "deep"), _dsp)
        finally:
            if _old_cfgdir is None:
                os.environ.pop("CLAUDE_CONFIG_DIR", None)
            else:
                os.environ["CLAUDE_CONFIG_DIR"] = _old_cfgdir
        expect(
            "default_settings_paths finds project (via --config) and "
            "CLAUDE_CONFIG_DIR-relocated user settings; lowest (user, low) wins",
            capped["effort_capped"] is not None
            and capped["effort_capped"]["cap"] == "low",
        )

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
