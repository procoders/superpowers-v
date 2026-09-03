#!/usr/bin/env python3
"""
Compound V model discovery — turn a backend's live model catalog into a tier map.

The model broker routes by INTENT (tier ∈ frontier/deep/standard/light), resolving to a concrete
model through a refreshable `models` block in .claude/compound-v.json
(see compound-v-resolve-model.py). This script does the DISCOVERY half deterministically:
it reads a backend's catalog (a plain list of model names, one per line) and PROPOSES a
frontier/deep/standard/light assignment, so /v:models and /v:init can suggest a real, current map
instead of a hand-curated one that rots when the provider ships new models.

I/O is intentionally split: the CALLER fetches the catalog (e.g. `agy models </dev/null`)
and pipes it in; this script only PARSES + RANKS (so it is pure and testable, and never
hangs on a backend call). It never invents names — it only ranks what it was given.

Ranking (antigravity / Gemini-family default):
  - Prefer the configured family (default "Gemini") for error-decorrelation from the
    Claude planner; other families in the catalog (e.g. GPT-OSS, Claude-via-agy) are
    reported under `available` and can be set explicitly, but are not auto-assigned.
  - A model name carries its effort in trailing parens, e.g. "Gemini 3.1 Pro (High)".
  - deep  = strongest series (Pro > Flash; higher version breaks ties) at its TOP effort.
  - frontier = the same as deep for every external backend (no vendor rung above it).
  - light = weakest series at its LOWEST effort.
  - standard = the strong series at a LOWER effort if it has one (a capable model, cheaper);
    else the weak series at its top effort; else the median of the catalog.

Usage:
  agy models </dev/null | compound-v-discover-models.py --backend antigravity
  compound-v-discover-models.py --backend antigravity --from-file catalog.txt \
      --write-config .claude/compound-v.json
  compound-v-discover-models.py --selftest

Python 3.9-safe, stdlib only.
"""

import argparse
import json
import os
import re
import sys

_EFFORT_RANK = {"high": 3, "thinking": 3, "max": 4, "medium": 2, "standard": 2, "low": 1}


# Stance names, mirrored from compound-v-resolve-model.py VALID_STANCES (the selftest
# asserts parity so the two cannot drift apart silently).
_STANCES = ("balanced", "conservative", "cost-aware", "claude-only")


def _parse_line(line):
    """'Gemini 3.1 Pro (High)' -> dict(full, series, version, strength, effort_rank).

    agy >= 1.1 prints two columns, ``id<TAB>Display Name`` (verified 1.1.22:
    ``gemini-3.1-pro-low\tGemini 3.1 Pro (Low)``); older builds printed the display
    name alone. Rank on the display column and keep it as the value written — agy
    1.1.22 accepts both forms for ``--model`` (probed live 2026-09-03), and every
    adapter doc, fixture and built-in default already uses the display name.
    """
    full = line.strip()
    if "\t" in full:
        full = full.split("\t")[-1].strip()
    if not full:
        return None
    m = re.search(r"\(([^)]+)\)\s*$", full)
    effort = m.group(1).strip().lower() if m else ""
    series = re.sub(r"\s*\([^)]*\)\s*$", "", full).strip()  # name without the effort paren
    ver_m = re.search(r"(\d+(?:\.\d+)?)", series)
    version = float(ver_m.group(1)) if ver_m else 0.0
    low = series.lower()
    if "ultra" in low:
        strength = 3
    elif "pro" in low:
        strength = 2
    elif "flash" in low or "spark" in low or "mini" in low:
        strength = 1
    else:
        strength = 2  # unknown tier — treat as mid/strong, not throwaway
    # effort_rank: default 2 (medium) when the catalog omits an effort suffix
    eff = 2
    for key, rank in _EFFORT_RANK.items():
        if key in effort:
            eff = rank
            break
    return {"full": full, "series": series, "version": version,
            "strength": strength, "effort_rank": eff}


def _family_of(series):
    """First token is the family label, e.g. 'Gemini', 'Claude', 'GPT-OSS'."""
    return series.split()[0] if series.split() else series


def propose(catalog_lines, family="Gemini"):
    """Return {'available': [...], 'proposed': {deep,standard,light}|None, 'note': str}."""
    parsed = [p for p in (_parse_line(l) for l in catalog_lines) if p]
    available = [p["full"] for p in parsed]
    if not parsed:
        return {"available": [], "proposed": None, "note": "empty catalog"}

    fam_lower = family.lower()
    fam = [p for p in parsed if _family_of(p["series"]).lower() == fam_lower]
    note = ""
    if not fam:
        fam = parsed
        note = "no '%s' models in catalog; ranked across all families" % family

    # Group by series label; rank series by (strength, version).
    series_groups = {}
    for p in fam:
        series_groups.setdefault(p["series"], []).append(p)

    def series_key(label):
        g = series_groups[label]
        return (g[0]["strength"], g[0]["version"])

    labels = sorted(series_groups, key=series_key)  # weakest .. strongest
    strongest = labels[-1]
    # `light` is the NEWEST series of the weakest strength class at its lowest effort —
    # the Flash line ships a new version every few weeks, and the newest one is the
    # cheap, fast, current model (3.4.14: the catalog carried 3.6/3.7/3.8 Flash and the
    # oldest was being proposed). The oldest series is never the answer for a moving line.
    weakest_strength = series_groups[labels[0]][0]["strength"]
    weakest = max((l for l in labels if series_groups[l][0]["strength"] == weakest_strength),
                  key=lambda l: series_groups[l][0]["version"])

    deep = max(series_groups[strongest], key=lambda p: p["effort_rank"])["full"]
    light = min(series_groups[weakest], key=lambda p: p["effort_rank"])["full"]

    strong_efforts = sorted(series_groups[strongest], key=lambda p: p["effort_rank"])
    weak_efforts = sorted(series_groups[weakest], key=lambda p: p["effort_rank"])
    if len(strong_efforts) > 1:
        standard = strong_efforts[0]["full"]          # strong series, cheaper effort
    elif len(weak_efforts) > 1:
        standard = weak_efforts[-1]["full"]           # weak series, top effort
    else:
        ordered = sorted(fam, key=lambda p: (p["strength"], p["version"], p["effort_rank"]))
        standard = ordered[len(ordered) // 2]["full"]

    # `frontier` is the extreme seat (v3.0.5). For an external backend it is the
    # SAME model as `deep`: no vendor here ships a rung above its own top model, and
    # proposing a distinct one would be a fabricated route. Only `claude` genuinely
    # separates them, and its map is native aliases, not a discovered catalog.
    return {"available": available,
            "proposed": {"frontier": deep, "deep": deep,
                         "standard": standard, "light": light},
            "note": note}


def write_config(config_path, backend, tier_map):
    """Merge {backend: tier_map} into the config's `models` block, preserving the rest."""
    data = {}
    if os.path.isfile(config_path):
        with open(config_path, "r") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("config root is not a JSON object: %s" % config_path)
    models = data.get("models")
    if not isinstance(models, dict):
        models = {}
    keys = list(models.keys())
    if keys and all(k in _STANCES for k in keys):
        # Per-stance shape — what /v:init Step 4a writes. The resolver discriminates the
        # two shapes by "EVERY top-level key is a stance name", so a flat `models.<backend>`
        # key dropped beside stance blocks flips the WHOLE map to the legacy branch and
        # silently disables every other backend's override (finding 142). Seed every stance.
        for st in keys:
            if isinstance(models[st], dict):
                models[st][backend] = dict(tier_map)
    else:
        models[backend] = tier_map
    data["models"] = models
    d = os.path.dirname(config_path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with open(config_path, "w") as fh:
        fh.write(json.dumps(data, indent=2) + "\n")


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

    catalog = [
        "Gemini 3.5 Flash (Medium)", "Gemini 3.5 Flash (High)", "Gemini 3.5 Flash (Low)",
        "Gemini 3.1 Pro (Low)", "Gemini 3.1 Pro (High)",
        "Claude Sonnet 4.6 (Thinking)", "Claude Opus 4.6 (Thinking)", "GPT-OSS 120B (Medium)",
    ]
    r = propose(catalog, family="Gemini")
    p = r["proposed"]
    check("deep = Pro High", p["deep"] == "Gemini 3.1 Pro (High)")
    check("standard = Pro Low", p["standard"] == "Gemini 3.1 Pro (Low)")
    check("light = Flash Low", p["light"] == "Gemini 3.5 Flash (Low)")
    check("avoids non-Gemini families", all("Gemini" in v for v in p.values()))
    check("available lists all 8", len(r["available"]) == 8)

    # only one Pro effort -> standard falls to Flash top effort
    cat2 = ["Gemini 3.1 Pro (High)", "Gemini 3.5 Flash (Low)", "Gemini 3.5 Flash (High)"]
    p2 = propose(cat2, family="Gemini")["proposed"]
    check("deep (single-pro)", p2["deep"] == "Gemini 3.1 Pro (High)")
    check("standard falls to Flash High", p2["standard"] == "Gemini 3.5 Flash (High)")
    check("light Flash Low", p2["light"] == "Gemini 3.5 Flash (Low)")

    # no Gemini -> ranks across families with a note
    cat3 = ["GPT-OSS 120B (Medium)", "GPT-OSS 20B (Low)"]
    r3 = propose(cat3, family="Gemini")
    check("no-family note", "no 'Gemini'" in r3["note"])
    check("still proposes something", r3["proposed"] is not None)
    check("proposal carries every tier the resolver knows",
          set(r3["proposed"]) == {"frontier", "deep", "standard", "light"})
    check("frontier mirrors deep for an external backend",
          r3["proposed"]["frontier"] == r3["proposed"]["deep"])

    check("empty catalog -> None", propose([], "Gemini")["proposed"] is None)

    # agy >= 1.1 two-column catalog (id<TAB>display): rank on the display column, never
    # write the id or the tab (finding 138 — the whole line used to be parsed as a name,
    # the family check failed, and GPT-OSS 120B won deep/frontier on "version 120").
    cat_tsv = ["gemini-3.8-flash-low\tGemini 3.8 Flash (Low)", "gemini-3.1-pro-high\tGemini 3.1 Pro (High)",
               "gemini-3.1-pro-low\tGemini 3.1 Pro (Low)", "gpt-oss-120b-medium\tGPT-OSS 120B (Medium)"]
    p4 = propose(cat_tsv, family="Gemini")["proposed"]
    check("tsv: deep = Pro High", p4["deep"] == "Gemini 3.1 Pro (High)")
    check("tsv: light = Flash Low", p4["light"] == "Gemini 3.8 Flash (Low)")
    check("tsv: no tab or id in any value", all("\t" not in v and not v.startswith("gemini-") for v in p4.values()))
    check("tsv: avoids non-Gemini families", all("Gemini" in v for v in p4.values()))

    # 3.4.14: three Flash generations in the catalog -> light is the NEWEST Flash at Low,
    # standard stays the Pro line's cheaper effort, deep the Pro line's top effort.
    cat5 = ["Gemini 3.8 Flash (High)", "Gemini 3.8 Flash (Low)", "Gemini 3.7 Flash (Low)",
            "Gemini 3.6 Flash (High)", "Gemini 3.6 Flash (Low)",
            "Gemini 3.1 Pro (High)", "Gemini 3.1 Pro (Low)"]
    p5 = propose(cat5, family="Gemini")["proposed"]
    check("moving Flash line: light = newest Flash (Low)", p5["light"] == "Gemini 3.8 Flash (Low)")
    check("moving Flash line: deep/standard stay on Pro", p5["deep"] == "Gemini 3.1 Pro (High)"
          and p5["standard"] == "Gemini 3.1 Pro (Low)")

    # Per-stance config (/v:init Step 4a shape): the seed lands in EVERY stance block and
    # never as a flat sibling key, and the resolver actually reads it back (finding 142).
    import importlib.util
    rp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "compound-v-resolve-model.py")
    spec = importlib.util.spec_from_file_location("cv_resolve", rp)
    rmod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rmod)
    check("stance names mirror the resolver", set(_STANCES) == set(rmod.VALID_STANCES))
    import tempfile
    fd, path2 = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        per_stance = {st: {"claude": {"deep": "opus"}, "antigravity": {"deep": "OLD"}} for st in _STANCES}
        with open(path2, "w") as fh:
            json.dump({"stance": "balanced", "models": per_stance}, fh)
        write_config(path2, "antigravity", {"frontier": "P", "deep": "P", "standard": "Q", "light": "R"})
        with open(path2) as fh:
            got2 = json.load(fh)["models"]
        check("per-stance: no flat sibling key", set(got2) == set(_STANCES))
        check("per-stance: every stance seeded", all(got2[st]["antigravity"]["deep"] == "P" for st in _STANCES))
        check("per-stance: other backends untouched", all(got2[st]["claude"] == {"deep": "opus"} for st in _STANCES))
        check("per-stance: resolver reads the seed back",
              rmod._config_cell(got2, "balanced", "antigravity", "deep") == "P"
              and rmod._config_cell(got2, "cost-aware", "claude", "deep") == "opus")
    finally:
        os.unlink(path2)

    # write_config merges, preserving other backends
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        with open(path, "w") as fh:
            json.dump({"models": {"codex": {"deep": "gpt-5.5"}}, "other": 1}, fh)
        write_config(path, "antigravity", {"deep": "X", "standard": "Y", "light": "Z"})
        with open(path) as fh:
            got = json.load(fh)
        check("merge preserves codex", got["models"]["codex"]["deep"] == "gpt-5.5")
        check("merge adds antigravity", got["models"]["antigravity"]["deep"] == "X")
        check("merge preserves other keys", got.get("other") == 1)
    finally:
        os.unlink(path)

    print("SELFTEST: %d ok, %d fail" % (ok, fail))
    return 0 if fail == 0 else 1


def main(argv):
    p = argparse.ArgumentParser(description="Compound V model discovery / tier proposal.")
    p.add_argument("--backend", default="antigravity",
                   help="backend label the proposal is for (config key)")
    p.add_argument("--family", default="Gemini",
                   help="preferred model family to auto-assign (default Gemini)")
    p.add_argument("--from-file", help="read the catalog from a file instead of stdin")
    p.add_argument("--write-config", help="merge the proposal into this config JSON's models block")
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args(argv)

    if args.selftest:
        return _selftest()

    if args.from_file:
        with open(args.from_file, "r", errors="replace") as fh:
            lines = fh.read().splitlines()
    else:
        lines = sys.stdin.read().splitlines()

    result = propose(lines, family=args.family)
    result["backend"] = args.backend

    if args.write_config:
        if not result["proposed"]:
            print("discover: empty/unusable catalog — nothing written to %s" % args.write_config,
                  file=sys.stderr)
            return 1
        write_config(args.write_config, args.backend, result["proposed"])
        result["written_to"] = args.write_config

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
