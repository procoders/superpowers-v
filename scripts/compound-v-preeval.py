#!/usr/bin/env python3
"""
Compound V — the CORE pre-evaluation scoring engine (v2.9 Task A3).

The pre-eval stage runs FIRST, before Trigger 0 recon (spec §1). It scores a change
request on two SEPARATE axes (difficulty, impact) from tiered deterministic evidence and
routes it into one of THREE proportionate tiers (v3.0 spec §A1).

THE DECISION VOCABULARY — a stable INTERFACE for every downstream consumer
--------------------------------------------------------------------------
This module is the sole producer of the `decision` value. Consumers (the outcomes
stream, the fast-path materializer/runner, the post-diff reclassifier, `/v:triage`,
`/v:orchestrate`) read it and MUST branch on all three values explicitly. A consumer
that tests `== FASTPATH` and puts everything else in one `else` arm is a two-value
reader of a three-value enum, which is how a tier silently lands in a cohort or a
pipeline that means something else.

    DECISION_FASTPATH = "FASTPATH_ELIGIBLE"   # tier DIRECT — implement in place, floor,
                                              #   commit on the branch. No manifest/run dir.
    DECISION_SCOPED   = "SCOPED_PIPELINE"     # tier SCOPED — manifest, run dir, scope gate,
                                              #   floor, ONE combined SPEC+QUALITY review.
                                              #   Recon + the three pre-flights are skipped.
    DECISION_FULL     = "FULL_PIPELINE"       # tier FULL  — the whole pipeline, unchanged.

`DECISION_TO_TIER` maps each value to the manifest `triage.tier` token
(`DIRECT` / `SCOPED` / `FULL`) that `compound-v-validate-manifest.py` compares verbatim.

THE 3x3 BAND MATRIX (spec §A1) — computed INSIDE this engine, never post-hoc
---------------------------------------------------------------------------
                impact low   impact medium   impact high
    diff low      DIRECT        SCOPED          FULL
    diff medium   SCOPED        SCOPED          FULL
    diff high     FULL          FULL            FULL

Two rules make the matrix safe, and BOTH must live here rather than in a reader of the
verdict dict:

  * **Any fired override forces FULL.** Enforced structurally in `_verdict()`, the single
    construction point of every verdict. This is not belt-and-suspenders: override #4
    (semantic-vs-path disagreement) returns the GENUINE `low`/`low` bands beside
    `override_fired=4`, so a consumer that re-derived the tier from the record's two band
    fields would hand DIRECT — and with it the auto-route class — to a record whose own
    audit trail says a hard override fired.
  * **Unknown / unmapped bands fail closed to FULL.** Override #6 catches `unknown` first;
    the matrix lookup itself then defaults any pair it does not recognise to FULL.

DIRECT additionally keeps every Layer-B predicate (`fan_out <= threshold`, exactly one
literal normalized path). A `low`/`low` request that fails a Layer-B predicate is NOT
promoted to DIRECT and NOT dropped to FULL — it demotes ONE tier, to SCOPED, which is
where the matrix already puts its `low`/`medium` and `medium`/`low` neighbours.

IRON-INVARIANT #4, as amended by spec §A4
-----------------------------------------
    The score OFFERS by default. It auto-routes only inside the DIRECT auto-route class,
    whose membership is decided by mechanically checkable predicates and never by model
    judgement. Every other tier still requires a human offer and acceptance.

This engine emits the tier and the mechanical evidence for it. It never auto-routes by
itself: the auto-route class has nine predicates (spec §A4), of which this engine can only
establish the first six — the floor having run and passed, the full post-diff
re-validation against the PRE-EDIT taxonomy snapshot, and the miscalibration circuit
breaker are all post-decision and belong to `/v:triage` and the outcomes stream.

    score(localization, taxonomy, t3_category=None, ...) -> deterministic verdict dict

This engine embodies the spec §2 truth-table and is:

  * **No raw LLM magnitude** (Iron-Invariant #1). Bands are assembled by deterministic
    logic. The ONE model touch — Tier-3 `light`-tier classify — is **T3-AGNOSTIC here**:
    this engine NEVER calls a model. It accepts a pre-resolved `--t3-category` enum; when
    T3 is required but the category is unset it RETURNS `needs_t3` with a ready prompt so
    the PARENT harness runs the light Task and re-invokes (the A2 contract, CR1-5/CR2-5).
  * **Fail-closed everywhere** (Iron-Invariant #5). Absent / malformed / unreadable
    taxonomy or its snapshot → **unconditional `FULL_PIPELINE`** (spec §2 round-3 fix,
    CR3-4): without the sensitive-path + content-pattern protections there is no way to
    *prove* a change is safe, and T3 alone must never manufacture eligibility. Any
    ambiguity, unknown axis, tier disagreement, or token-budget overrun → `FULL_PIPELINE`.
  * **Localization-before-any-`low`** (Iron-Invariant #2): a `low` verdict is impossible
    until A1's bounded read-only `localize()` resolved real paths/tokens/fan-out.

Lifecycle & commit-ordering — Phase P (parent-owned; NO run_id yet; all artifacts under
`docs/superpowers/pre-eval/`). This engine WRITES the artifacts but NEVER runs git — the
orchestrator/dispatcher commits them (v2.6.4 commit-discipline; two-command primitive):

    1. write-once INTENT record   `<pre_eval_id>.intent.json`         (CR5-10, pre-localize)
    2. write-once LOCALIZATION     `<pre_eval_id>.localization.json`   (A1's writer, reused)
    3. write-once TAXONOMY SNAPSHOT `<pre_eval_id>.taxonomy-snapshot.yaml`  (content-address)
    4. write-once RECORD           `<pre_eval_id>.json`  (status:PRE_EVAL_DONE, decision)
    5. append PREDICTED triage event keyed by `pre_eval_id`            (F1's append_predicted)

Resume in Phase P: the write-once INTENT record maps a stable request fingerprint →
`pre_eval_id`, so a fresh-process re-entry with only the request text discovers partial
state and continues from the first missing artifact (never orphaning / re-minting).

The record conforms to `schemas/pre-eval-record.schema.json`. All bands + overrides are
git/taxonomy-derived, never model self-report. No fabricated cost/token metric is ever
emitted — the derived 1-10 is a post-decision band-midpoint DISPLAY label only.

Reuse (imported BY PATH, never recopied):
  * `compound-v-taxonomy.py`        — load_taxonomy / match_path / classify / max_band /
                                       record_digest / canonical_json / taxonomy_digest_bytes
  * `compound-v-localize.py`        — localize / write_localization_artifact / artifact paths
  * `compound-v-classify-request.py`— build_prompt (the T3 prompt the parent runs)
  * `compound-v-project-config.py`  — load_project_config / resolve_pre_eval (fail-closed)
  * `compound-v-validate-taxonomy.py`— validate_text (HIGH-3: malformed taxonomy → fail closed)
  * `compound-v-triage-outcomes.py` — append_predicted / tier2_lookup (append-only + cohort read)
  * `compound-v-churn.py`           — load_churn_cache / read_path (escalation-only)

Python 3.9-safe, stdlib only; soft-PyYAML via the shared taxonomy loader (never a hard
`import yaml`); no external CLI is launched from here (localize owns the supervisor boundary).

Usage:
    compound-v-preeval.py triage --request-env VAR --repo DIR [--session-id S]
        [--base-commit SHA] [--t3-category C] [--json]
        # Phase T: score + BIND + write the record, and report the tier with spec §A4
        # predicates 1-6. Its two callers are `hooks/triage-prompt-nudge.sh` (the
        # UserPromptSubmit producer) and `commands/v-triage.md` step T2 — see
        # `triage_request`, which both of them are one line on top of.
    compound-v-preeval.py --request "<text>" --repo DIR [--taxonomy PATH]
        [--t3-category plumbing|user-facing-minor|user-facing-major|unknown]
        [--pre-eval-id ID]                       # end-to-end Phase-P run (writes artifacts)
    compound-v-preeval.py --score-only --localization-json '{...}' [--taxonomy PATH]
        [--t3-category C] [--fan-out-threshold N]   # pure scoring, no writes
    compound-v-preeval.py --selftest
"""

import argparse
import datetime
import hashlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys

# --------------------------------------------------------------------------- #
# Constants.
# --------------------------------------------------------------------------- #
PRE_EVAL_DIR_REL = os.path.join("docs", "superpowers", "pre-eval")
DEFAULT_TAXONOMY_REL = os.path.join(".claude", "compound-v-impact-taxonomy.yaml")
STATUS_PRE_EVAL_DONE = "PRE_EVAL_DONE"
DECISION_FASTPATH = "FASTPATH_ELIGIBLE"
DECISION_SCOPED = "SCOPED_PIPELINE"
DECISION_FULL = "FULL_PIPELINE"

# The manifest `triage.tier` token each decision materializes as. `compound-v-validate-
# manifest.py` compares that token VERBATIM (case matters), so the mapping is single-sourced
# here rather than re-spelled by every producer.
DECISION_TO_TIER = {
    DECISION_FASTPATH: "DIRECT",
    DECISION_SCOPED: "SCOPED",
    DECISION_FULL: "FULL",
}

# --------------------------------------------------------------------------- #
# v3.1.0 — the cross-model review gate, derived from the SAME tier.
#
# The maintainer's rule, 2026-09-02: a cross-model second opinion follows the same
# entry criterion as brainstorming. "Если брейншторма не было, то смысл и кодекс
# запускать" — a change too small to brainstorm is too small to hand to a second
# model family, and a massive or business-logic-heavy ticket is exactly what a
# second family should read.
#
# This is DERIVED, never stored: the pre-eval record is digest-sealed, and adding a
# field to it would change the bytes of every future record while old ones keep
# theirs — a reused pre_eval_id would then be refused as a conflict for a field that
# carries no new information. The tier is already in the record; the gate is a
# function of it, so it is computed at read time and has exactly one source of truth.
#
# The stakes list in skills/compound-v/cross-model-review.md still applies WITHIN
# FULL — this decides whether the question is even asked.
CROSS_MODEL_REVIEW_BY_DECISION = {
    DECISION_FASTPATH: (False, "tier DIRECT — no brainstorm, no plan and no manifest "
                               "exist, so there is nothing for a second model to review"),
    DECISION_SCOPED: (False, "tier SCOPED — a bounded, localized change; the Opus "
                             "partition-reviewer and the deterministic manifest "
                             "validator already cover it. Ask for one explicitly if the "
                             "slice turns out to be coupled"),
    DECISION_FULL: (True, "tier FULL — the pipeline ran brainstorm and planning, which "
                          "is the same threshold a second opinion is worth paying for; "
                          "apply the stakes list in cross-model-review.md to choose the "
                          "depth, not whether to ask"),
}


def cross_model_review_for(decision_or_tier, flavor=None):
    """(required, why). Accepts either a decision constant or a manifest triage tier,
    plus the record's / manifest's `flavor` (v3.4.1): `scoped_plus` is the one SCOPED
    shape whose second opinion is mandatory, not a judgment call (spec §A3).

    Unknown input falls to True: not knowing the size of a change is itself a reason
    to have a second family read it, and this gate only ever spends tokens — it can
    never let a worse plan through.
    """
    if str(flavor or "").strip().lower() == "scoped_plus":
        return (True, "SCOPED+ (flavor scoped_plus) — a small edit on a SENSITIVE path: the "
                      "deep review and the cross-model second opinion are the obligation "
                      "that makes the flavor a promise instead of a label (v3.4.1 §A3); "
                      "run it on the sealed diff, never skip it")
    key = str(decision_or_tier or "").strip()
    if key in CROSS_MODEL_REVIEW_BY_DECISION:
        return CROSS_MODEL_REVIEW_BY_DECISION[key]
    for dec, tier in DECISION_TO_TIER.items():
        if key.upper() == tier:
            return CROSS_MODEL_REVIEW_BY_DECISION[dec]
    return (True, "tier %r is not one of %s — an unrecognised size falls to 'review', "
                  "because not knowing how big a change is, is itself a reason to have "
                  "a second family read it"
                  % (decision_or_tier, ", ".join(sorted(DECISION_TO_TIER.values()))))


# spec §A1 — the 3x3 difficulty x impact matrix. Keyed (difficulty, impact); ANY pair absent
# from this table (including every `unknown`/None combination) falls closed to FULL via
# `_matrix_decision`'s default. The `low`/`low` cell is a DIRECT *candidate* only: Layer B
# still has to prove the fan-out and single-literal-path predicates before it is granted.
_TIER_MATRIX = {
    ("low", "low"): DECISION_FASTPATH,
    ("low", "medium"): DECISION_SCOPED,
    ("low", "high"): DECISION_FULL,
    ("medium", "low"): DECISION_SCOPED,
    ("medium", "medium"): DECISION_SCOPED,
    ("medium", "high"): DECISION_FULL,
    ("high", "low"): DECISION_FULL,
    ("high", "medium"): DECISION_FULL,
    ("high", "high"): DECISION_FULL,
}

# spec §2 — T3 total truth table (deterministic; every enum → BOTH axes, no low/med
# ambiguity, round-3 fix). The T3 `light`-tier classify emits exactly one of these.
T3_TABLE = {
    "plumbing": ("low", "low"),
    "user-facing-minor": ("medium", "medium"),
    "user-facing-major": ("high", "high"),
    "unknown": ("unknown", "unknown"),
}
T3_CATEGORIES = tuple(T3_TABLE.keys())

# v3.4.1 — the two T3 answers that mean "this really is a small change". Both the §A2
# demotion and the §A3 SCOPED+ branch key on the SAME set, because they are the same
# judgement asked in two places; `user-facing-major` and `unknown` never demote anything.
DEMOTABLE_T3_CATEGORIES = ("plumbing", "user-facing-minor")

# v3.4.1 §A3 — SCOPED+ is not a fourth tier token. `DECISION_TO_TIER` still has exactly
# three values; a SCOPED+ verdict is `SCOPED_PIPELINE` wearing this flavor, which the
# manifest carries as `triage.flavor` and which obliges a deep review plus a cross-model
# second opinion. `_verdict` is the only place it can be attached, and it refuses to attach
# it to anything but SCOPED_PIPELINE.
FLAVOR_SCOPED_PLUS = "scoped_plus"
VALID_FLAVORS = (FLAVOR_SCOPED_PLUS,)

# v3.4.1 §A3 — the hard list no light classify can talk its way past. Secrets and CI are
# not "small edits": a one-line change to a private key or to a workflow file is exactly
# the shape of change that is catastrophic and looks trivial. A path matching any of these
# takes override #2 (FULL) whatever T3 says, and the check is a CODE floor rather than a
# taxonomy row so that editing the taxonomy cannot remove it.
NEVER_DEMOTE_GLOBS = ("**/*.pem", "**/*.key", "**/*.env", ".github/**")

# The fan-out ceiling for both proportionate paths (spec decisions 1 and 3: "fan_out ≤ 2").
# It is deliberately NOT `fan_out_threshold`: that config knob gates the DIRECT cell, which
# is a stricter question (exactly one literal path) than "still a small change".
DEMOTION_MAX_FAN_OUT = 2

# The reason a needs_t3 handoff was issued — for the caller's LOG only. The re-entry is
# identical in all three cases (`--t3-category <enum>`); nothing branches on this.
T3_REASONS = ("unbanded", "demotion", "sensitive")

# Derived 1-10 DISPLAY (spec §2 — post-decision label, NEVER the gate). Band-midpoint.
_BAND_DISPLAY = {"low": 2, "medium": 5, "high": 8}  # unknown/None → null

# Localization flags (from A1's `_map_classify_flags`) that trigger Layer-A overrides.
_OVERRIDE3_FLAGS = frozenset(("shared_token", "is_a11y_state", "is_generated"))
# Any of these means the change semantically IS a high-blast surface → raises impact and
# so blocks Layer B (AC-8: impact is what a change IS, not only where it lives). regex_timeout
# is a FAIL-CLOSED content signal (a content pattern could not be evaluated → treat as a hit).
# `content_scan_incomplete` (v3.4.1 §WS-B) joins them: a literal path whose file was too
# large to read is still EXACT by name — the localizer no longer degrades the whole
# localization to `ambiguous` over it — but the content patterns that would have decided
# its impact never ran, so the unknown falls on the impact axis. Fail-closed on impact,
# not on localization.
_IMPACT_RAISING_FLAGS = frozenset(("shared_token", "is_a11y_state", "regex_timeout",
                                   "content_scan_incomplete"))

# F2 (post-diff reclassifier) owns MAX_TOTAL_LINES=50 as its size threshold; the pre-eval
# scorer's only size lever is `fan_out_threshold` (from config, default 1 — single-site).

# Token-budget guard: a coarse chars/4 estimate, applied ONLY at the T3 boundary (the sole
# potential model spend). Overrun → abort → FULL_PIPELINE (spec §3 rule 3; never displayed).
_TOKENS_PER_CHAR = 0.25

PRE_EVAL_ID_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{6}Z-[A-Za-z0-9._-]+-[A-Za-z0-9]+$"
)


# --------------------------------------------------------------------------- #
# Sibling reuse by path (hyphenated filenames → importlib). Loaded lazily; each
# has an inline degrade so a briefly-missing sibling never hard-fails the module.
# --------------------------------------------------------------------------- #
def _here():
    return os.path.dirname(os.path.abspath(__file__))


_MOD_CACHE = {}


def _load_sibling(basename, modname):
    if basename in _MOD_CACHE:
        return _MOD_CACHE[basename]
    path = os.path.join(_here(), basename)
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _MOD_CACHE[basename] = mod
    return mod


def _tax():
    return _load_sibling("compound-v-taxonomy.py", "compound_v_taxonomy")


def _localize_mod():
    return _load_sibling("compound-v-localize.py", "compound_v_localize")


def _classify_mod():
    return _load_sibling("compound-v-classify-request.py", "compound_v_classify_request")


def _config_mod():
    return _load_sibling("compound-v-project-config.py", "compound_v_project_config")


def _triage_mod():
    return _load_sibling("compound-v-triage-outcomes.py", "compound_v_triage_outcomes")


def _churn_mod():
    return _load_sibling("compound-v-churn.py", "compound_v_churn")


def _validate_taxonomy_mod():
    return _load_sibling("compound-v-validate-taxonomy.py", "compound_v_validate_taxonomy")


# --------------------------------------------------------------------------- #
# Identity: slug, fingerprint, pre_eval_id.
# --------------------------------------------------------------------------- #
def slugify(request, maxlen=60):
    """Human-readable slug from request text: lowercase → non-alphanumeric runs → '-' →
    trim. Empty after normalization → a short hash of the raw text (never empty)."""
    s = (request or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    if len(s) > maxlen:
        s = s[:maxlen].rstrip("-")
    if not s:
        s = "req-" + hashlib.sha256((request or "").encode("utf-8")).hexdigest()[:8]
    return s


def normalize_request(request):
    """Stable normalization for the fingerprint: trim + collapse internal whitespace."""
    return re.sub(r"\s+", " ", (request or "").strip())


def request_fingerprint(request):
    """`sha256:` over the normalized request text — the stable key a resume recomputes from
    the request alone to discover an existing pre_eval_id before minting a new one."""
    return "sha256:" + hashlib.sha256(
        normalize_request(request).encode("utf-8")
    ).hexdigest()


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _compact_stamp(ts_iso):
    # 2026-07-12T10:15:00Z -> 2026-07-12T101500Z
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})Z$", ts_iso)
    if not m:
        # Fall back to now if a caller hands a non-canonical ts.
        return _compact_stamp(_now_iso())
    return "%s-%s-%sT%s%s%sZ" % m.groups()


def mint_pre_eval_id(request, ts_iso=None, nonce=None):
    """Mint a write-once pre_eval_id: `YYYY-MM-DDThhmmssZ-<slug>-<nonce>`."""
    ts_iso = ts_iso or _now_iso()
    slug = slugify(request)
    if nonce is None:
        nonce = hashlib.sha256(
            (request_fingerprint(request) + ts_iso).encode("utf-8")
        ).hexdigest()[:4]
    return "%s-%s-%s" % (_compact_stamp(ts_iso), slug, nonce)


# --------------------------------------------------------------------------- #
# Small helpers.
# --------------------------------------------------------------------------- #
def _band_display(band):
    return _BAND_DISPLAY.get(band)  # low/medium/high → int; unknown/None → None


def _axis(band):
    return {"band": band if band in ("low", "medium", "high", "unknown") else "unknown",
            "display": _band_display(band)}


_GLOB_METACHARS = set("*?[]{}")


def _is_single_literal_path(paths):
    """Layer-B path rule: EXACTLY one path, and that path is a literal normalized
    repo-relative path (no glob metachar, no `..`, not absolute). A1's containment already
    guarantees repo-relative regular files; this is the belt-and-suspenders literal check."""
    if not isinstance(paths, list) or len(paths) != 1:
        return False
    p = paths[0]
    if not isinstance(p, str) or not p:
        return False
    if os.path.isabs(p) or ".." in p.replace("\\", "/").split("/"):
        return False
    return not any(c in _GLOB_METACHARS for c in p)


def _content_raises_impact(flags):
    """True iff a localization flag indicates the change semantically IS a high-blast
    surface (any `content:<kind>` hit, or a fail-closed regex_timeout, or shared_token /
    a11y). Such a change can never be `impact == low` (AC-8)."""
    for f in flags or []:
        if isinstance(f, str) and (f.startswith("content:") or f in _IMPACT_RAISING_FLAGS):
            return True
    return False


def _matrix_decision(difficulty_band, impact_band):
    """spec §A1 — the 3x3 band matrix, as a pure lookup. FAIL-CLOSED BY CONSTRUCTION: any
    pair the table does not contain (`unknown`, `None`, a band a future taxonomy invents)
    returns FULL. Callers must still apply the Layer-B predicates before honouring a
    DIRECT (`DECISION_FASTPATH`) result — see `score`."""
    return _TIER_MATRIX.get((difficulty_band, impact_band), DECISION_FULL)


def _has_safety_coverage(taxonomy):
    """A loaded taxonomy provides *safety coverage* only if it carries a non-empty
    sensitive-path list — the core protection a fast-path relies on. Without it there is no
    way to prove a resolved path is not sensitive, so T3 alone must NOT manufacture
    eligibility (spec §2 round-3 fix, applied at the coverage boundary, fail-closed)."""
    return bool(taxonomy) and bool(taxonomy.get("sensitive_path_list"))


def estimate_t3_tokens(request_text, resolved_paths):
    """Coarse chars/4 token estimate for the T3 classify input (request + paths). A
    fail-safe budget guard only — never a displayed metric."""
    n = len(request_text or "")
    for p in resolved_paths or []:
        n += len(p) + 2
    return int(n * _TOKENS_PER_CHAR) + 1


# --------------------------------------------------------------------------- #
# THE deterministic truth-table (spec §2). Pure function — no I/O, no model call.
# --------------------------------------------------------------------------- #
def score(localization, taxonomy, t3_category=None, *, tier2=None, churn_hot=False,
          advisor_hot=False, fan_out_threshold=1, token_cap=None, request_text="",
          build_t3_prompt=None):
    """Score one request into a deterministic verdict (spec §2).

    Args:
      localization: A1's `{resolved_paths, fan_out, flags, confidence}` dict.
      taxonomy:     the loaded taxonomy dict, or **None** (absent/malformed/unreadable →
                    unconditional FULL_PIPELINE, CR3-4). The SAME dict localize() used.
      t3_category:  a pre-resolved T3 enum (T3-agnostic engine — never calls a model), or
                    None. When T3 is required and this is None, returns a `needs_t3` payload.
      tier2:        F1's tier2_lookup result (`{health,...}` calibrated | `{status:...}`), or
                    None. Corroborates `low` when calibrated-healthy; `unhealthy` RAISES.
      churn_hot:    True iff any resolved path is churn-`hot` (escalation-only, override #5).
      advisor_hot:  True iff a completed run's `results/*.json usage.advisor_calls` shows the
                    job outran its tier (escalation-only, override #7 — a POST-RUN reclassify
                    signal, mirror of churn_hot; absence never escalates). Pure-function-safe:
                    the file read happens only in caller-side `_advisor_hot_for`, never here.
      fan_out_threshold: Layer-B fan-out ceiling (config `pre_eval.fan_out_threshold`).
      token_cap:    whole-stage token budget; overrun at the T3 boundary → abort → FULL.

    Returns one of:
      {"needs_t3": True, "t3_prompt": str, "t3_reason": str}            # parent runs the Task
      {"decision", "override_fired", "difficulty", "impact",            # a completed verdict
       "tiers_signalled", "min_sample_status", "flavor"}                # + t3_demotion/t3_reason

    `t3_reason` (v3.4.1) says WHY the classify was asked for — `unbanded` (T1 could not band
    the path at all, the pre-3.4.1 case), `demotion` (T1 banded it, but only from a broad
    directory glob — §A2), or `sensitive` (a small edit on a sensitive path that may reach
    SCOPED+ — §A3). The re-entry is identical in all three: `--t3-category <enum>`. It is
    for the caller's LOG; nothing branches on it.

    A verdict's `flavor` is `scoped_plus` or None, and `t3_demotion` records what the
    taxonomy said before a light classify was allowed to answer back.

    `decision` is one of DECISION_FASTPATH / DECISION_SCOPED / DECISION_FULL (spec §A1's
    3x3 matrix, applied at Layer B). A non-null `override_fired` ALWAYS pairs with
    DECISION_FULL — `_verdict` enforces that, so no caller has to re-check it.
    """
    loc = localization or {}
    resolved = loc.get("resolved_paths", []) or []
    fan_out = int(loc.get("fan_out", 0) or 0)
    flags = loc.get("flags", []) or []
    confidence = loc.get("confidence")

    min_sample_status = "calibrated" if (isinstance(tier2, dict) and "health" in tier2) \
        else "insufficient"

    # -- Missing-data table (spec §2): absent/malformed taxonomy → unconditional FULL. ---
    # T3 NEVER manufactures eligibility without T1 safety coverage. This precedes Layer A:
    # with no taxonomy there are no sensitive-path / content-pattern protections at all.
    if not _has_safety_coverage(taxonomy):
        return _verdict(DECISION_FULL, override=None, diff="unknown", imp="unknown",
                        tiers=[], min_sample=min_sample_status)

    # v3.4.1 §A4: `new_file` is a LOCALIZED answer — the localizer named one path that does
    # not exist yet and whose parent directory does. T1 can still band it (match_path is
    # glob-based and needs no file on disk), so the tier is decidable. Layer B's DIRECT
    # predicate separately refuses it by name: a file nobody has read cannot be a fast-path.
    tiers = ["localization"] if confidence in ("exact", "new_file") else []
    tax = _tax()

    # ============================ Layer A — hard overrides ======================= #
    # Ordered 1→6, first match → FULL_PIPELINE with ZERO further cost. Overrides 1/2/3/5
    # need NO model call and are evaluated first so a fired override never triggers a T3
    # Task (AC-3 — zero model calls on any Layer-A override). Overrides 4 (tier
    # disagreement) and 6 (unknown axis) depend on the computed axes (T3 when T1 is
    # unclassified) and are evaluated after. When a cheap override and #4/#6 would both
    # fire, the cheap one wins — it is earlier and its FULL_PIPELINE verdict is identical.

    # #1 localization failed ∨ ambiguous → paths unknown, cannot judge.
    if confidence in ("failed", "ambiguous"):
        return _verdict(DECISION_FULL, override=1, diff="unknown", imp="unknown",
                        tiers=tiers, min_sample=min_sample_status)

    # #2 any resolved path is on the sensitive path-list (auth/payments/PII/migrations/…).
    # Belt-and-suspenders: trust A1's `sensitive_path` flag AND independently re-match the
    # taxonomy's sensitive_path_list here (path-only, cheap) so a missed flag still fails
    # closed — the scorer never trusts a single upstream signal for a hard-safety override.
    #
    # THE ROWS ARE RETAINED, not recomputed and thrown away. Two generator expressions
    # below used to call `match_path` a second and third time and keep only the bands;
    # §A2's demotion needs to know WHICH globs produced those bands (broad or specific),
    # so the rows are computed once, here, and read three times.
    path_matches = [tax.match_path(taxonomy, p) for p in resolved]
    sensitive = ("sensitive_path" in flags) or any(m["sensitive"] for m in path_matches)
    if sensitive:
        # v3.4.1 §A3 — SCOPED+. Override #2 becomes conditional: a genuinely small,
        # exactly-localized edit that a light classify calls plumbing is routed to SCOPED
        # with a `scoped_plus` flavor (a mandatory deep review + a cross-model second
        # opinion + the human accept) instead of the whole pipeline. Everything else on a
        # sensitive path is override #2 exactly as before, and four classes can never take
        # this route at all: a NEVER_DEMOTE path (secrets, CI), an inexact localization, a
        # fan-out above two, and any change a content pattern already calls high-impact.
        never_demote = any(_is_never_demote_path(p) for p in resolved)
        scoped_plus_open = (
            not never_demote
            and confidence == "exact"
            and fan_out <= DEMOTION_MAX_FAN_OUT
            and not _content_raises_impact(flags)
        )
        if scoped_plus_open:
            _from = {"difficulty": tax.max_band(
                         m["difficulty_band"] for m in path_matches) or "high",
                     "impact": tax.max_band(
                         m["impact_band"] for m in path_matches) or "high"}
            if t3_category is None:
                # Same budget guard as every other T3 boundary: an over-budget request
                # never buys a model call, it takes the override it would have taken.
                if token_cap is not None \
                        and estimate_t3_tokens(request_text, resolved) > token_cap:
                    return _verdict(DECISION_FULL, override=2, diff="high", imp="high",
                                    tiers=tiers + ["T1"], min_sample=min_sample_status)
                prompt = build_t3_prompt() if build_t3_prompt else _default_t3_prompt(
                    request_text, resolved, taxonomy)
                return {"needs_t3": True, "t3_prompt": prompt, "t3_reason": "sensitive",
                        "tiers_signalled": tiers + ["T1"],
                        "min_sample_status": min_sample_status}
            if t3_category in DEMOTABLE_T3_CATEGORIES:
                return _verdict(_matrix_decision("medium", "medium"), override=None,
                                diff="medium", imp="medium",
                                tiers=tiers + ["T1", "T3"],
                                min_sample=min_sample_status,
                                flavor=FLAVOR_SCOPED_PLUS,
                                t3_reason="sensitive",
                                t3_demotion={"from": _from, "category": t3_category,
                                             "applied": True, "sensitive": True})
        return _verdict(DECISION_FULL, override=2, diff="high", imp="high",
                        tiers=tiers + ["T1"], min_sample=min_sample_status)

    # #3 shared design token / generated artifact / a11y state ("button" = global token).
    if any(f in _OVERRIDE3_FLAGS for f in flags):
        return _verdict(DECISION_FULL, override=3, diff="high", imp="high",
                        tiers=tiers + ["T1"], min_sample=min_sample_status)

    # #5 churn-hot on any resolved path (escalation-only; low/insufficient never lowers).
    if churn_hot:
        return _verdict(DECISION_FULL, override=5, diff="high", imp="high",
                        tiers=tiers + ["churn"], min_sample=min_sample_status)

    # #7 advisor-hot: a completed run's `usage.advisor_calls` shows the job outran its tier
    # (escalation-only; a POST-RUN reclassification signal cloned from churn — absence never
    # lowers). Evaluated positionally right after #5 with the other CHEAP escalation-only
    # overrides (no model call); the id 7 is a NEW row appended to the spec's 1-6 space
    # (numeric label ≠ eval order — #6 unknown-axis is still evaluated later, after the axes).
    # override_fired=7 IS the audit trail here; no "advisor" tier tag is appended because the
    # write-once record's `tiers_signalled` enum (schemas/pre-eval-record.schema.json) is a
    # fixed set (T1/T2/T3/churn/localization) and the schema is out of this change's scope —
    # an out-of-enum tier would make a reclassification record fail schema validation.
    if advisor_hot:
        return _verdict(DECISION_FULL, override=7, diff="high", imp="high",
                        tiers=tiers, min_sample=min_sample_status)

    # -- Compute the two axes (conservative-max; may require the T3 fallback). ---------- #
    t1_diff = tax.max_band(m["difficulty_band"] for m in path_matches)
    t1_impact = tax.max_band(m["impact_band"] for m in path_matches)
    if t1_diff is not None or t1_impact is not None:
        if "T1" not in tiers:
            tiers.append("T1")

    # Content-pattern impact (localize already ran content patterns → surfaced as flags).
    content_impact_high = _content_raises_impact(flags)
    impact_band = tax.max_band(
        [t1_impact] + (["high"] if content_impact_high else []))
    difficulty_band = t1_diff

    # v3.4.1 §A2 — BREADTH. `t1_from_broad_glob` is true when every row that produced these
    # bands is a "everything under here" pattern (`**`, or a trailing `/*`), the change is
    # not on a sensitive path, and no content pattern has already called it high-impact.
    # It is the difference between "the taxonomy says THIS FILE is high" and "the taxonomy
    # says this DIRECTORY is high" — and only the second is a claim a light classify is
    # allowed to answer back to. `all()` over an empty list is True, so an unbanded path is
    # excluded explicitly: it takes the pre-existing unbanded T3 handoff, not this one.
    _t1_rows = [row for m in path_matches for row in m["matched"]]
    t1_from_broad_glob = (
        bool(_t1_rows)
        and all(row.get("broad") for row in _t1_rows)
        and not sensitive
        and not content_impact_high
    )
    t3_demotion = None
    t3_reason = None

    # T2 corroborates `low` but never independently CREATES it pre-calibration; `unhealthy`
    # RAISES difficulty (Iron-Invariant #3 counterfactual guard).
    if isinstance(tier2, dict) and tier2.get("health"):
        tiers.append("T2")
        if tier2["health"] == "unhealthy":
            difficulty_band = tax.max_band([difficulty_band or "medium", "medium"])

    # T3 fallback: reached ONLY when T1 left difficulty unclassified (∧ T2 can't create a
    # band). If T3 is needed and no category is supplied → hand the parent a ready prompt.
    t3_needed = difficulty_band is None
    if t3_needed:
        if t3_category is None:
            # Token-budget guard (spec §3 rule 3): overrun at the T3 boundary → abort →
            # FULL_PIPELINE (fail-safe; never call the model, never a displayed metric).
            if token_cap is not None and estimate_t3_tokens(request_text, resolved) > token_cap:
                return _verdict(DECISION_FULL, override=None, diff="unknown", imp="unknown",
                                tiers=tiers, min_sample=min_sample_status)
            prompt = build_t3_prompt() if build_t3_prompt else _default_t3_prompt(
                request_text, resolved, taxonomy)
            return {"needs_t3": True, "t3_prompt": prompt, "t3_reason": "unbanded",
                    "tiers_signalled": tiers, "min_sample_status": min_sample_status}
        # A category was supplied — but re-check the budget (an over-budget request that
        # somehow arrived with a category still aborts, honoring the whole-stage cap).
        if token_cap is not None and estimate_t3_tokens(request_text, resolved) > token_cap:
            return _verdict(DECISION_FULL, override=None, diff="unknown", imp="unknown",
                            tiers=tiers, min_sample=min_sample_status)
        t3_diff, t3_impact = T3_TABLE.get(t3_category, ("unknown", "unknown"))
        tiers.append("T3")
        difficulty_band = t3_diff
        # T3 impact may only RAISE, never lower below T1 (weaker text proxy — spec §2).
        impact_band = tax.max_band([impact_band, t3_impact]) or t3_impact

    # v3.4.1 §A2 — THE T3 DEMOTION (maintainer decision 1). T1 banded this change, but only
    # because a broad glob claimed the whole directory. Ask the light classify once, and let
    # `plumbing` / `user-facing-minor` bring the tier down to SCOPED.
    #
    # THE MATRIX GUARD IS PART OF THE BRANCH, not an optimisation on top of it. This is a
    # DEMOTION: if the bands already route the change to DIRECT or SCOPED there is nothing
    # to demote, and asking anyway would turn today's zero-cost README typo into a model
    # round trip that cannot improve its tier. So the branch is entered only where the
    # bands would otherwise force FULL.
    #
    # Override #4 (semantic-vs-path disagreement) is deliberately NOT evaluated on this
    # path — it lives in the `elif` below and this branch shadows it. Firing it here would
    # be incoherent: the whole premise is that T1 said `high` from a broad glob and T3 says
    # `plumbing`, which is exactly the disagreement #4 exists to punish. #4 keeps firing
    # wherever T1's bands came from a row that named the file.
    elif (t1_from_broad_glob and fan_out <= DEMOTION_MAX_FAN_OUT
            and _matrix_decision(difficulty_band, impact_band) == DECISION_FULL):
        if t3_category is None:
            if token_cap is not None \
                    and estimate_t3_tokens(request_text, resolved) > token_cap:
                return _verdict(DECISION_FULL, override=None, diff=difficulty_band,
                                imp=impact_band or "unknown", tiers=tiers,
                                min_sample=min_sample_status)
            prompt = build_t3_prompt() if build_t3_prompt else _default_t3_prompt(
                request_text, resolved, taxonomy)
            return {"needs_t3": True, "t3_prompt": prompt, "t3_reason": "demotion",
                    "tiers_signalled": tiers, "min_sample_status": min_sample_status}
        tiers.append("T3")
        # `t3_reason` records why T3 was CONSULTED, not what it answered — so it is set on
        # the refusal too. A record that says `applied: false` beside the category that
        # refused it is the audit trail for a change that asked to be small and was told no.
        t3_reason = "demotion"
        t3_demotion = {"from": {"difficulty": difficulty_band, "impact": impact_band},
                       "category": t3_category,
                       "applied": t3_category in DEMOTABLE_T3_CATEGORIES}
        if t3_demotion["applied"]:
            # Difficulty comes from the T3 table but is FLOORED AT MEDIUM: "DIRECT for code
            # stays unreachable" — a light classify calling a change plumbing is evidence
            # that it is small, never evidence that it may be committed unreviewed. Impact
            # is CAPPED at medium: the broad glob's `high` was a statement about the
            # directory, and T3 has now said this change is not that.
            difficulty_band = tax.max_band([T3_TABLE[t3_category][0], "medium"])
            if tax.band_rank(impact_band) > tax.band_rank("medium"):
                impact_band = "medium"

    # #4 semantic-vs-path disagreement: T1 classified AND a T3 category was supplied and
    # they conflict by ≥2 band ranks (T1 `low` vs T3 `user-facing-major`, or the converse).
    elif t3_category is not None and t3_category in T3_TABLE:
        t3_diff, t3_impact = T3_TABLE[t3_category]
        tiers.append("T3")
        if _bands_conflict(t1_impact, t3_impact) or _bands_conflict(t1_diff, t3_diff):
            return _verdict(DECISION_FULL, override=4, diff=difficulty_band or "unknown",
                            imp=impact_band or "unknown", tiers=tiers,
                            min_sample=min_sample_status)
        # No conflict → T3 may still RAISE impact (never lower).
        impact_band = tax.max_band([impact_band, t3_impact]) or impact_band

    # #6 any axis unknown → no signal → full pipeline.
    if difficulty_band == "unknown" or impact_band == "unknown" \
            or difficulty_band is None or impact_band is None:
        return _verdict(DECISION_FULL, override=6, diff=difficulty_band or "unknown",
                        imp=impact_band or "unknown", tiers=tiers,
                        min_sample=min_sample_status, t3_demotion=t3_demotion,
                        t3_reason=t3_reason)

    # ==================== Layer B — the 3x3 matrix + the DIRECT predicates ============ #
    # spec §A1. The matrix is applied HERE, inside the engine, on the bands as computed —
    # never re-derived downstream from the record's two band fields, because a fired
    # override can leave genuine `low`/`low` bands on a record that must never be DIRECT
    # (override #4; see the module docstring). `_verdict` is the structural backstop.
    decision = _matrix_decision(difficulty_band, impact_band)

    # DIRECT (`FASTPATH_ELIGIBLE`) additionally keeps every pre-existing Layer-B predicate:
    # fan_out ≤ threshold ∧ exactly one literal normalized path (not shared/generated/
    # config/migration — all already caught by overrides #2/#3 and content-flag impact, so
    # at Layer B `flags` is clean). Failing one does NOT fall to FULL: the bands are still
    # low/low, so the change demotes exactly ONE tier, to SCOPED — the tier the matrix
    # already assigns to this cell's low/medium and medium/low neighbours, and one that
    # still buys a manifest, a run directory, the scope gate, the floor and a review.
    if decision == DECISION_FASTPATH:
        direct_predicates_hold = (
            # v3.4.1 §A4 / pre-flight amendment 6 — `exact` BY NAME, never "not failed".
            # `new_file` is a localized answer (Layer A treats it as one) with low/low bands
            # from a directory glob and exactly one literal path, so every other predicate
            # here holds for it. Without this test it would reach DIRECT: a file nobody has
            # read, committed with no manifest, no run dir and no review.
            confidence == "exact"
            and fan_out <= int(fan_out_threshold)
            and _is_single_literal_path(resolved)
        )
        if not direct_predicates_hold:
            decision = DECISION_SCOPED

    return _verdict(decision, override=None, diff=difficulty_band, imp=impact_band,
                    tiers=tiers, min_sample=min_sample_status,
                    t3_demotion=t3_demotion, t3_reason=t3_reason)


def _bands_conflict(a, b):
    """Two classified bands conflict if both are real and differ by ≥2 ranks (low↔high)."""
    tax = _tax()
    ra, rb = tax.band_rank(a), tax.band_rank(b)
    return ra > 0 and rb > 0 and abs(ra - rb) >= 2


def _is_never_demote_path(path):
    """v3.4.1 §A3 — True iff `path` is on the hard NEVER_DEMOTE list (secrets, CI). A CODE
    floor, not a taxonomy row: a change that could edit the taxonomy must not be able to
    edit its way out of this."""
    tax = _tax()
    return any(tax.glob_match(path, g) for g in NEVER_DEMOTE_GLOBS)


def _verdict(decision, override, diff, imp, tiers, min_sample, flavor=None,
             t3_demotion=None, t3_reason=None):
    # THE INVARIANT, enforced at the single construction point of every verdict (spec §A1):
    # ANY FIRED OVERRIDE FORCES FULL. Every Layer-A row already passes DECISION_FULL, so
    # this normally changes nothing — it exists so that no future edit can introduce a
    # verdict carrying both a non-null `override_fired` and a proportionate decision. That
    # pairing is precisely what override #4 makes reachable: it returns the GENUINE
    # `low`/`low` bands beside `override_fired=4`, and a record on which the two disagreed
    # would let a post-hoc reader grant DIRECT — and the auto-route class with it — to a
    # change whose own audit trail says a hard override fired.
    if override is not None:
        decision = DECISION_FULL

    # THE FLAVOR INVARIANT, enforced at the same single point (v3.4.1 §A3). `scoped_plus`
    # is a PROMISE that a deep review and a cross-model second opinion will run, and the
    # manifest validator refuses a `scoped_plus` manifest without them. A flavor riding on
    # a FULL verdict would demand that ceremony of a pipeline that already exceeds it; one
    # riding on DIRECT would demand it of a change that has no manifest at all. Both are
    # nonsense, so the flavor survives on exactly one decision — and an unrecognised value
    # is dropped rather than forwarded, because the validator's enum would reject it
    # downstream, where the error is far from the line that invented it.
    if decision != DECISION_SCOPED or flavor not in VALID_FLAVORS:
        flavor = None

    # De-dup tiers preserving order; keep only the schema enum.
    allowed = ("T1", "T2", "T3", "churn", "localization")
    seen, ordered = set(), []
    for t in tiers:
        if t in allowed and t not in seen:
            seen.add(t)
            ordered.append(t)
    out = {
        "needs_t3": False,
        "decision": decision,
        "override_fired": override,
        "difficulty": _axis(diff),
        "impact": _axis(imp),
        "tiers_signalled": ordered,
        "min_sample_status": min_sample,
        "flavor": flavor,
    }
    # Present only when there is something to say — `build_record` copies them straight
    # through, and an always-present null would change the bytes (and so the digest) of
    # every record the engine has ever written for no new information.
    if t3_demotion is not None:
        out["t3_demotion"] = t3_demotion
    if t3_reason in T3_REASONS:
        out["t3_reason"] = t3_reason
    return out


def _default_t3_prompt(request_text, resolved_paths, taxonomy):
    """Build the bounded T3 classify prompt via A2's builder (reuse, no recopy). The taxonomy
    kinds are passed as context-only category hints."""
    try:
        cm = _classify_mod()
        hints = []
        for row in (taxonomy or {}).get("content_patterns", []):
            k = row.get("kind")
            if k and k not in hints:
                hints.append(k)
        return cm.build_prompt(request_text, resolved_paths, hints or None)
    except Exception:  # noqa: BLE001 — the prompt is advisory; never crash the engine
        return ("Classify this change request into EXACTLY ONE of: %s.\nREQUEST: %s"
                % (", ".join(T3_CATEGORIES), request_text or "(empty)"))


# --------------------------------------------------------------------------- #
# Write-once artifact writers (Phase P). NEVER commit — the orchestrator does.
# --------------------------------------------------------------------------- #
def pre_eval_dir(repo):
    return os.path.join(repo or ".", PRE_EVAL_DIR_REL)


def _rel(repo, full):
    return os.path.relpath(full, repo or ".").replace("\\", "/")


def _write_once_text(full_path, text):
    """Atomic O_EXCL write-once. Raises FileExistsError if the path already exists."""
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    fd = os.open(full_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)


def intent_path(repo, pre_eval_id):
    return os.path.join(pre_eval_dir(repo), pre_eval_id + ".intent.json")


def snapshot_path(repo, pre_eval_id):
    return os.path.join(pre_eval_dir(repo), pre_eval_id + ".taxonomy-snapshot.yaml")


def record_path(repo, pre_eval_id):
    return os.path.join(pre_eval_dir(repo), pre_eval_id + ".json")


def write_intent_record(repo, pre_eval_id, request, ts=None):
    """CR5-10: the write-once intent record (request fingerprint → pre_eval_id), written
    FIRST in Phase P so a fresh-process resume can find partial state. Idempotent: an
    existing intent for the same pre_eval_id is left untouched (returns its rel path)."""
    if not PRE_EVAL_ID_RE.match(pre_eval_id or ""):
        raise ValueError("invalid pre_eval_id: %r" % pre_eval_id)
    full = intent_path(repo, pre_eval_id)
    rel = _rel(repo, full)
    body = {
        "pre_eval_id": pre_eval_id,
        "request_fingerprint": request_fingerprint(request),
        "request_slug": slugify(request),
        "ts": ts or _now_iso(),
    }
    try:
        _write_once_text(full, json.dumps(body, indent=2, sort_keys=True,
                                          ensure_ascii=False) + "\n")
    except FileExistsError:
        pass  # write-once + idempotent resume: an existing intent is authoritative
    return rel


def find_pre_eval_id_by_request(repo, request):
    """Resume discovery: scan intent records for a matching request fingerprint; return the
    existing pre_eval_id or None. Never mints — the caller mints only on a miss."""
    fp = request_fingerprint(request)
    d = pre_eval_dir(repo)
    if not os.path.isdir(d):
        return None
    for name in sorted(os.listdir(d)):
        if not name.endswith(".intent.json"):
            continue
        try:
            with open(os.path.join(d, name), "r", encoding="utf-8") as fh:
                obj = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(obj, dict) and obj.get("request_fingerprint") == fp:
            pid = obj.get("pre_eval_id")
            if pid and PRE_EVAL_ID_RE.match(pid):
                return pid
    return None


def write_taxonomy_snapshot(repo, pre_eval_id, taxonomy_bytes):
    """Content-address the taxonomy: copy its RAW bytes to an immutable write-once snapshot
    and return (rel_path, digest). `taxonomy_digest` = sha256 over the raw bytes (a content
    address, NOT a re-serialization). Idempotent on resume (existing snapshot kept)."""
    tax = _tax()
    full = snapshot_path(repo, pre_eval_id)
    rel = _rel(repo, full)
    digest = tax.taxonomy_digest_bytes(taxonomy_bytes)
    try:
        os.makedirs(os.path.dirname(full), exist_ok=True)
        fd = os.open(full, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(fd, "wb") as fh:
            fh.write(taxonomy_bytes)
    except FileExistsError:
        # Resume: verify the existing snapshot still content-addresses to the same digest.
        with open(full, "rb") as fh:
            existing = fh.read()
        digest = tax.taxonomy_digest_bytes(existing)
    return rel, digest


def build_record(pre_eval_id, request, verdict, localization, taxonomy_version,
                 taxonomy_ref, taxonomy_digest, ts=None, binding=None):
    """Assemble the write-once pre-eval RECORD (conforms to pre-eval-record.schema.json).
    `status: PRE_EVAL_DONE` is a RECORD field, not a state.json phase (AC-7/CR2-8).

    binding: the OPTIONAL Feature-C coverage binding (spec §C) — a dict with any of
        `session_id`, `base_commit`, `declared_paths`. It is what lets the triage gate in
        `hooks/epic-goal-stop.sh` decide whether this record COVERS the current diff, and
        only `/v:triage` can supply it: this engine never sees a session. Absent (the
        default, and every call this module makes) the record is byte-for-byte what it was
        before v3.0 — no binding keys, and an identical `digest`.

        THE KWARG EXISTS TO REMOVE A FOOTGUN, not merely as a convenience. `digest` is
        computed over the whole record, so a producer that called `build_record` and THEN
        attached the binding fields would ship a record whose self-integrity digest no
        longer verifies — silently, because `digest` is optional and only checked when
        present. Passing the binding through here keeps the digest correct by construction.

        `tier` is NOT accepted from the caller. It is DERIVED from the decision via
        DECISION_TO_TIER whenever a binding is supplied, because the triage gate prefers
        `tier` over `decision`: accepting it as an argument would let a producer hand the
        gate a tier the record's own decision refuses. The schema pins the two together as
        well, so the disagreement is unrepresentable on both sides of the boundary.
    """
    tax = _tax()
    rec = {
        "pre_eval_id": pre_eval_id,
        "request_slug": slugify(request),
        "ts": ts or _now_iso(),
        "status": STATUS_PRE_EVAL_DONE,
        "taxonomy_version": taxonomy_version,
        "taxonomy_ref": taxonomy_ref,
        "taxonomy_digest": taxonomy_digest,
        "difficulty": verdict["difficulty"],
        "impact": verdict["impact"],
        "tiers_signalled": verdict["tiers_signalled"],
        "localization": {k: localization.get(k) for k in
                         ("resolved_paths", "fan_out", "flags", "confidence")},
        "override_fired": verdict["override_fired"],
        "decision": verdict["decision"],
        "min_sample_status": verdict["min_sample_status"],
        "confidence": _evidence_confidence(verdict, localization),
    }

    # v3.4.1 — the proportionate-tier evidence, written ONLY when there is any. A verdict
    # that took none of the new paths produces byte-for-byte the record it produced before
    # this release, which matters because `write_record` is write-once and re-running
    # triage on the same request must not collide with its own earlier answer.
    for _k in ("flavor", "t3_demotion", "t3_reason"):
        if verdict.get(_k) is not None:
            rec[_k] = verdict[_k]

    # Feature C coverage binding — added BEFORE the digest, never after (see the docstring).
    # Each key is emitted only when the caller supplied it, so an unbound record keeps its
    # pre-3.0 bytes exactly. `tier` rides along derived, never supplied.
    if binding:
        for _k in ("session_id", "base_commit", "declared_paths"):
            if binding.get(_k) is not None:
                rec[_k] = binding[_k]
        _tier = DECISION_TO_TIER.get(verdict["decision"])
        if _tier is not None:
            rec["tier"] = _tier

    rec["digest"] = tax.record_digest(rec, exclude_field="digest")
    return rec


def _evidence_confidence(verdict, localization):
    """An evidence-only confidence STRING (never a gating number): signalled tiers +
    localization confidence. Anti-ruflo: no cost/token figure."""
    tiers = ",".join(verdict.get("tiers_signalled", [])) or "none"
    return "localization:%s; tiers:%s" % (localization.get("confidence"), tiers)


def write_record(repo, pre_eval_id, record):
    """Write the write-once RECORD (O_EXCL — reject overwrite, CR1-9). Returns rel path.

    Re-running triage on the SAME request is a supported operation: `run_preeval`
    deliberately rediscovers an existing `pre_eval_id` via
    `find_pre_eval_id_by_request` rather than minting a second one. Until this was
    dogfooded (2026-09-01) that path then hit `O_EXCL` and died with a raw
    `FileExistsError` traceback — the discovery half and the write half
    contradicted each other.

    Resolution keeps write-once intact where it matters. Byte-identical content is
    an idempotent no-op, because rewriting a file with what it already holds
    changes nothing and refusing it only punishes a legitimate re-run. Content that
    DIFFERS is still refused, and now with the reason and the offending keys named
    instead of a stack trace: a record whose decision or bindings moved under a
    reused id is a real conflict, and silently overwriting it would destroy the
    audit trail this whole layer exists to produce.
    """
    full = record_path(repo, pre_eval_id)
    payload = json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if os.path.exists(full):
        try:
            existing = io.open(full, encoding="utf-8").read()
        except OSError as exc:
            raise ValueError("pre-eval record %s exists but is unreadable: %s"
                               % (pre_eval_id, exc))
        if existing == payload:
            # Byte-identical: an idempotent re-run. Signalled to the caller so it can
            # skip the PREDICTED append — this write is what stops the flow before
            # `append_predicted`, so returning "fine" without that signal would put a
            # SECOND predicted event on the stream the circuit breaker reads.
            return _rel(repo, full), True
        try:
            old_rec = json.loads(existing)
            moved = sorted(k for k in set(old_rec) | set(record)
                           if old_rec.get(k) != record.get(k))
        except ValueError:
            moved = ["<existing record is not valid JSON>"]
        raise ValueError(
            "pre-eval record %s already exists with DIFFERENT content; refusing to "
            "overwrite an audit artifact. Fields that differ: %s. Re-running the same "
            "request is fine — this means the same id now scores differently, which is "
            "a conflict a human should look at." % (pre_eval_id, ", ".join(moved) or "(none)"))
    _write_once_text(full, payload)
    return _rel(repo, full), False


# --------------------------------------------------------------------------- #
# Phase-P orchestrator: intent → localize → snapshot → score → record → predicted.
# --------------------------------------------------------------------------- #
def _load_taxonomy(repo, taxonomy_path):
    """Return (taxonomy_dict|None, raw_bytes|None, version|None). Absent / malformed /
    unreadable / VALIDATION-FAILING → (None, None, None) → the scorer routes to unconditional
    FULL_PIPELINE (spec §2 missing-data rule).

    HIGH-3 fail-closed: a taxonomy that PARSES but the shared validator REJECTS — e.g. a
    missing `churn` block, an unbounded content regex, an invalid band — is exactly as unsafe
    as an absent one (its sensitive-path / content-pattern protections cannot be trusted), so
    it fails closed the SAME way. Validation is not re-implemented here: it reuses
    `compound-v-validate-taxonomy.validate_text` (the same subset its CLI runs), fed the raw
    YAML text (not the normalized dict). Any violation → treat the taxonomy as absent."""
    tax = _tax()
    candidate = taxonomy_path or os.path.join(repo or ".", DEFAULT_TAXONOMY_REL)
    if not candidate or not os.path.isfile(candidate):
        return None, None, None
    try:
        with open(candidate, "rb") as fh:
            raw = fh.read()
        text = raw.decode("utf-8", "replace")
        data = tax.load_taxonomy(text=text)
    except (OSError, ValueError, RuntimeError):
        return None, None, None
    # Shared validation (reused, never recopied). A rejecting taxonomy is treated as ABSENT.
    try:
        problems = _validate_taxonomy_mod().validate_text(text)
    except Exception:  # noqa: BLE001 — a validator that itself errors → fail closed too
        return None, None, None
    if problems:
        return None, None, None
    return data, raw, data.get("version")


def _churn_hot_for(repo, resolved_paths):
    """Escalation-only churn signal: True iff any resolved path is `hot` in the committed
    churn cache. Absent/unreadable cache → False (absence never escalates or lowers)."""
    if not resolved_paths:
        return False
    cm = _churn_mod()
    cache_path = os.path.join(repo or ".", "docs", "superpowers", "memory",
                              "churn-cache.json")
    if not os.path.isfile(cache_path):
        return False
    try:
        cache = cm.load_churn_cache(cache_path)
    except (OSError, ValueError):
        return False
    return any(cm.read_path(cache, p).get("hot") for p in resolved_paths)


# Repeated advisor consults signal the job was harder than its tier: a fast-path/standard
# worker that had to stop and consult a cross-brand advisor MORE than a couple of times is
# evidence the work outran its classification. STRICTLY-greater-than gate (escalation-only —
# it can only push the tier UP on reclassification, never down).
ADVISOR_HOT_THRESHOLD = 2


def _advisor_hot_for(repo, run_dir):
    """Escalation-only advisor signal (mirror of `_churn_hot_for`): True iff any SUCCESSFUL
    `results/*.json` for the run records `usage.advisor_calls` exceeding ADVISOR_HOT_THRESHOLD.
    A POST-RUN reclassification read only — never called from the pure `score()`.

    Only a result with `status == "success"` is counted (round-2: a failed/blocked/timeout job
    that happened to consult the advisor before dying must NOT escalate a clean re-run — its
    advisor_calls reflect a dead attempt, not genuine difficulty of a completed unit).

    Absent/unreadable results dir, a missing/unreadable file, a non-success status, a
    null/absent/non-int `advisor_calls`, or no run_dir at all => False (absence NEVER escalates),
    fail-open exactly like churn. `run_dir` is the execution run directory
    (`<run_dir>/results/*.json`); it may be absolute or repo-relative."""
    if not run_dir:
        return False
    base = run_dir if os.path.isabs(run_dir) else os.path.join(repo or ".", run_dir)
    results_dir = os.path.join(base, "results")
    if not os.path.isdir(results_dir):
        return False
    try:
        names = os.listdir(results_dir)
    except OSError:
        return False
    for name in names:
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(results_dir, name), "r", encoding="utf-8") as fh:
                obj = json.load(fh)
        except (OSError, ValueError):
            continue  # unreadable/malformed result → absence, never escalates
        if not isinstance(obj, dict):
            continue
        if obj.get("status") != "success":
            continue  # only a completed, successful unit signals genuine difficulty
        usage = obj.get("usage")
        if not isinstance(usage, dict):
            continue
        calls = usage.get("advisor_calls")
        # bool is an int subclass — exclude it so a stray True never counts as a call count.
        if isinstance(calls, int) and not isinstance(calls, bool) \
                and calls > ADVISOR_HOT_THRESHOLD:
            return True
    return False


def _run_dir_contained(repo, run_dir):
    """Path-containment guard for a caller-supplied ``--run-dir``: True iff it resolves
    to a path inside the repo root (realpath-based, so a ``..`` traversal or an
    escaping symlink is rejected, and an absolute path pointing OUTSIDE the repo fails).
    ``run_dir`` may be repo-relative or absolute. Absence (falsy) => True (fail-open:
    nothing to validate — the advisor sensor simply stays off)."""
    if not run_dir:
        return True
    root_real = os.path.realpath(repo or ".")
    base = run_dir if os.path.isabs(run_dir) else os.path.join(repo or ".", run_dir)
    real = os.path.realpath(base)
    prefix = root_real.rstrip(os.sep) + os.sep
    return real == root_real or real.startswith(prefix)


def run_preeval(request, repo=".", taxonomy_path=None, t3_category=None,
                pre_eval_id=None, ts=None, config_values=None, tier2=None,
                churn_hot=None, advisor_hot=None, run_dir=None, _localize=None,
                write_localization=True, stream_path=None, append_predicted=True,
                binding=None):
    """End-to-end Phase-P run. Writes intent → (localization) → taxonomy snapshot → record,
    then appends the `predicted` triage event. NEVER runs git (the orchestrator commits).

    `binding` is the OPTIONAL Feature-C coverage binding (`session_id` / `base_commit`) that
    `triage_request` supplies. When given, `declared_paths` is derived HERE from the
    localization this run actually produced and the pair is threaded into `build_record`'s
    own `binding=` kwarg, so the record's `digest` covers the binding by construction. Paths
    `declare_paths` refuses come back on the result as `refused_paths`.

    This is a REAL parameter rather than a `globals()["build_record"]` patch (pre-flight
    amendment 2). The patch form captured the module global at call time, so two overlapping
    `triage_request` calls in one interpreter would leave the global pointing at the first
    call's closure — every later record bound to a stale `session_id`, which is a record
    claiming Stop-gate coverage it does not have. A parameter cannot do that.

    `_localize` is injectable for tests (a callable `(request, repo, taxonomy) -> loc dict`);
    defaults to A1's real `localize()`. On `needs_t3`, returns the payload WITHOUT writing
    the record or appending `predicted` — the parent runs the light Task and re-invokes with
    `--t3-category`. Resume: an existing intent record for the same request fingerprint reuses
    its pre_eval_id and continues from the first missing artifact.

    Config honored (fail-closed, HIGH-4): `pre_eval.enabled==false` → the whole stage is a
    no-op (no artifacts) → FULL_PIPELINE; `pre_eval.fast_path=="off"` → hard kill-switch, the
    score is still computed but the decision is forced FULL_PIPELINE (never
    FASTPATH_ELIGIBLE and never SCOPED_PIPELINE — both are proportionate tiers);
    `pre_eval.min_sample_count` floors the Tier-2 cohort lookup applied per the spec's cohort
    rule (healthy corroborates low, unhealthy raises, insufficient = no signal).
    """
    repo = repo or "."
    ts = ts or _now_iso()

    # Config (fail-closed): enabled, fast_path, fan_out_threshold, token_cap, min_sample_count.
    if config_values is None:
        cfg_mod = _config_mod()
        try:
            cfg = cfg_mod.load_project_config(repo)
        except ValueError:
            cfg = {}
        config_values, _warn = cfg_mod.resolve_pre_eval(cfg)
    fan_out_threshold = config_values.get("fan_out_threshold", 1)
    token_cap = config_values.get("token_cap")
    min_sample_count = config_values.get("min_sample_count")
    fast_path_off = config_values.get("fast_path") == "off"  # hard kill-switch (AC-10)

    # HIGH-4(a): pre_eval.enabled == false → the WHOLE stage is a no-op → FULL_PIPELINE.
    # Nothing is localized, scored, snapshotted, or recorded; the harness proceeds on the
    # normal (full-pipeline) path exactly as if pre-eval did not exist. No artifacts, no git.
    if config_values.get("enabled") is False:
        return {"needs_t3": False, "pre_eval_disabled": True,
                "decision": DECISION_FULL, "pre_eval_id": None}

    # Phase-P step 0/1: discover-or-mint pre_eval_id, then the write-once intent record.
    if not pre_eval_id:
        pre_eval_id = find_pre_eval_id_by_request(repo, request) \
            or mint_pre_eval_id(request, ts_iso=ts)
    intent_rel = write_intent_record(repo, pre_eval_id, request, ts=ts)

    # Load taxonomy (raw bytes for the content-address + dict for scoring).
    taxonomy, taxonomy_bytes, taxonomy_version = _load_taxonomy(repo, taxonomy_path)

    # Phase-P step 2: bounded read-only localization + its committed-later artifact (A1).
    localize_fn = _localize or _localize_mod().localize
    localization = localize_fn(request, repo, taxonomy or {})
    localization_ref = None
    if write_localization:
        lm = _localize_mod()
        try:
            localization_ref = lm.write_localization_artifact(repo, pre_eval_id, localization)
        except FileExistsError:
            localization_ref = lm.artifact_rel_path(pre_eval_id)  # resume: already written

    # Phase-P step 3: content-address the taxonomy into an immutable snapshot (only when a
    # taxonomy exists — an absent-taxonomy request has no snapshot and no digest).
    taxonomy_ref = taxonomy_digest = None
    if taxonomy_bytes is not None:
        taxonomy_ref, taxonomy_digest = write_taxonomy_snapshot(
            repo, pre_eval_id, taxonomy_bytes)

    # Churn signal (escalation-only) — computed if not supplied.
    if churn_hot is None:
        churn_hot = _churn_hot_for(repo, localization.get("resolved_paths", []))

    # Advisor signal (escalation-only, POST-RUN reclassification) — computed if not supplied.
    # In the common pre-dispatch case there is no run_dir/results yet, so this is False
    # (absence never escalates); it only fires on a reclassification pass that hands a run_dir.
    if advisor_hot is None:
        advisor_hot = _advisor_hot_for(repo, run_dir)

    # HIGH-4(c): Tier-2 historical corroboration — resolved via the shared cohort lookup when
    # not injected. min_sample_count-gated (config floor); healthy corroborates `low`,
    # UNHEALTHY raises difficulty, insufficient = no signal (Iron-Invariant #3). Fail-closed:
    # any read error → no signal (never fabricates corroboration).
    if tier2 is None:
        try:
            tier2 = _triage_mod().tier2_lookup(
                min_sample_count=min_sample_count, stream_path=stream_path, repo=repo)
        except (OSError, ValueError):
            tier2 = None

    # Phase-P step 4: SCORE (deterministic; may return needs_t3).
    verdict = score(localization, taxonomy, t3_category=t3_category, tier2=tier2,
                    churn_hot=churn_hot, advisor_hot=advisor_hot,
                    fan_out_threshold=fan_out_threshold,
                    token_cap=token_cap, request_text=request)

    # HIGH-4(b): fast_path == "off" is a HARD kill-switch on PROPORTIONATE routing — no
    # reduced-ceremony tier is EVER offered. The bands stay computed (for the record +
    # learning), but the DECISION is forced FULL_PIPELINE. When the score would need a T3
    # model call, we skip it entirely: a fast-path that can never be offered is not worth a
    # model spend (spec §3, near-free).
    #
    # v3.0: this branch names DECISION_SCOPED EXPLICITLY rather than letting it fall through
    # the `== DECISION_FASTPATH` test into the untouched arm. An operator who set
    # `fast_path: "off"` asked for the full pipeline; silently handing them a tier that also
    # skips recon and the three pre-flights would be the kill-switch failing open on a value
    # that did not exist when the switch was written.
    if fast_path_off:
        if verdict.get("needs_t3"):
            verdict = _verdict(DECISION_FULL, override=None, diff="unknown", imp="unknown",
                               tiers=verdict.get("tiers_signalled", []),
                               min_sample=verdict.get("min_sample_status", "insufficient"))
        elif verdict.get("decision") in (DECISION_FASTPATH, DECISION_SCOPED):
            # `flavor` goes with the decision it qualified: a SCOPED+ verdict forced to FULL
            # is a FULL verdict, and leaving `scoped_plus` on it would ask the manifest
            # validator for a SCOPED+ manifest the operator explicitly switched off.
            verdict = dict(verdict, decision=DECISION_FULL, flavor=None)

    if verdict.get("needs_t3"):
        # Pause: parent runs the light Task and re-invokes. Artifacts already durable.
        return {
            "needs_t3": True,
            "pre_eval_id": pre_eval_id,
            "t3_prompt": verdict["t3_prompt"],
            "t3_reason": verdict.get("t3_reason"),
            "intent_ref": intent_rel,
            "localization_ref": localization_ref,
            "taxonomy_ref": taxonomy_ref,
        }

    # Phase-P step 4 (write) + 5 (append): write-once record, then predicted event.
    # `declared_paths` is derived from THIS run's localization and rides in on the same
    # kwarg as the rest of the binding, so the digest covers all of it (build_record's
    # docstring: attaching binding fields after the fact silently breaks the digest).
    record_binding = None
    refused_paths = []
    if binding:
        declared, refused_paths = declare_paths(localization.get("resolved_paths"))
        record_binding = dict(binding, declared_paths=declared)
    record = build_record(pre_eval_id, request, verdict, localization,
                          taxonomy_version, taxonomy_ref, taxonomy_digest, ts=ts,
                          binding=record_binding)
    record_rel, record_already_existed = write_record(repo, pre_eval_id, record)

    predicted_event = None
    if append_predicted and not record_already_existed:
        tm = _triage_mod()
        predicted_event = tm.append_predicted(
            pre_eval_id,
            decision=verdict["decision"],
            difficulty_band=verdict["difficulty"]["band"],
            impact_band=verdict["impact"]["band"],
            taxonomy_sha=taxonomy_digest,
            localization={k: localization.get(k) for k in
                          ("resolved_paths", "fan_out", "flags")},
            ts=ts, stream_path=stream_path,
        )

    return {
        "needs_t3": False,
        "pre_eval_id": pre_eval_id,
        "decision": verdict["decision"],
        "flavor": verdict.get("flavor"),
        "override_fired": verdict["override_fired"],
        "record": record,
        "record_ref": record_rel,
        "intent_ref": intent_rel,
        "localization_ref": localization_ref,
        "taxonomy_ref": taxonomy_ref,
        "taxonomy_digest": taxonomy_digest,
        "predicted_event": predicted_event,
        "refused_paths": refused_paths,
    }


# --------------------------------------------------------------------------- #
# Phase T — the ONE implementation of "score this request and bind it", shared by
# BOTH of its callers.
#
# THE TWO CALLERS, NAMED (this is the point of the function existing):
#
#   1. `hooks/triage-prompt-nudge.sh` — the UserPromptSubmit hook. It is the
#      MECHANICAL producer: a change request arriving is the native event, and the
#      hook runs this subcommand on it, so a record exists before any work starts
#      without anyone remembering to ask for one.
#   2. `commands/v-triage.md`, step T2 — the human/agent entry point, for a request
#      the hook did not see (a second request in the same session, a slash-command
#      invocation, a re-score after `--t3-category`).
#
# BOTH used to carry their own copy of this logic — the hook carried none at all and
# the command carried ~120 lines of it inside a markdown heredoc, where nothing could
# test it and a second caller could only be written by copying it. A prose-hosted
# scorer with two producers is the drift this release exists to stop, so the logic
# lives here, in the module that already owns the vocabulary, and both callers are
# one line.
#
# WHAT THIS DOES NOT DO: git. The engine's standing invariant is that it never runs
# git (the orchestrator commits; v2.6.4 discipline), and Phase T is inside the engine,
# so `base_commit` is an INPUT. A caller that wants the binding runs `git rev-parse
# HEAD` itself and passes it; a caller that cannot gets a record with `base_commit`
# null, which is honest rather than invented.
# --------------------------------------------------------------------------- #

# Predicate 6's test-path set. The taxonomy has no test-file key, so this is a
# deliberately BROAD heuristic: every extra shape it catches removes a change from the
# auto-route class, which is the safe direction. Widen it freely; narrowing it is a
# policy change. `commands/v-triage.md` Phase L carries the same set for the REALISED
# path, which it re-derives post-diff.
_TEST_PATH_SEGMENTS = ("test", "tests", "spec", "specs", "__tests__", "testing")

# Control characters in a declared path. `hooks/epic-goal-stop.sh` silently DROPS a
# path it cannot read, so this producer refuses it loudly instead.
_CTRL_RE = re.compile(r"[\x00-\x1f]")


def is_test_path(path):
    """True when `path` looks like a test file (auto-route predicate 6)."""
    segs = str(path or "").split("/")
    if any(s.lower() in _TEST_PATH_SEGMENTS for s in segs[:-1]):
        return True
    base = segs[-1]
    if base in ("conftest.py",):
        return True
    stem = base.split(".")[0].lower()
    if stem.startswith(("test_", "test-")) or stem.endswith(("_test", "-test")):
        return True
    return any((".%s." % k) in base.lower() for k in ("test", "spec"))


def declare_paths(paths):
    """(declared, refused) in the exact vocabulary `hooks/epic-goal-stop.sh` reads back —
    an exact path, a `dir/` prefix, or a `*` glob. A bare `scripts` deliberately does NOT
    cover `scripts/app.py`.

    Entries that gate would silently DROP (a control character, a leading `/`, a `..`
    segment) are refused HERE instead, where the producer still learns about it: a
    declared path the reader discards is coverage the record claims and does not have.
    """
    declared, refused = [], []
    for p in paths or []:
        if not isinstance(p, str) or not p:
            continue
        if p.startswith("/") or _CTRL_RE.search(p) or ".." in p.split("/"):
            refused.append(p)
            continue
        if p not in declared:
            declared.append(p)
    return declared, refused


def auto_route_predicates(record, repo, pre_eval_id):
    """Spec §A4 predicates 1-6 for a written record — the six this side of the edit can
    establish. Returns a list of `{"n", "name", "pass", "why"}` in spec order.

    Predicates 7 (the floor), 8 (the full post-diff re-validation) and 9 (the circuit
    breaker) are POST-EDIT and belong to `commands/v-triage.md` Phase L; they are not
    evaluated here and are not reported as passing.

    Predicate 3 is a real digest match, not a restatement: the taxonomy is read back from
    the snapshot THIS RECORD PINNED and re-content-addressed, so a taxonomy edited between
    the record and this call is caught.
    """
    tax = _tax()
    decision = record.get("decision")
    paths = (record.get("localization") or {}).get("resolved_paths") or []

    snap = snapshot_path(repo, pre_eval_id)
    taxonomy = snap_digest = None
    if os.path.isfile(snap):
        try:
            with open(snap, "rb") as fh:
                snap_bytes = fh.read()
            snap_digest = tax.taxonomy_digest_bytes(snap_bytes)
            taxonomy = tax.load_taxonomy(text=snap_bytes.decode("utf-8", "replace"))
        except (OSError, ValueError, RuntimeError):
            taxonomy = snap_digest = None

    single = _is_single_literal_path(paths)
    one = paths[0] if single else None
    ar = tax.match_auto_route(taxonomy, one) if (taxonomy and one) else None
    bands_known = ((record.get("difficulty") or {}).get("band") in ("low", "medium", "high")
                   and (record.get("impact") or {}).get("band")
                   in ("low", "medium", "high"))

    out = [
        (1, "tier is DIRECT and no override fired",
         decision == DECISION_FASTPATH and record.get("override_fired") is None,
         "decision=%s override_fired=%s" % (decision, record.get("override_fired"))),
        (2, "exactly one resolved path, and it is a literal", bool(single),
         "resolved_paths=%s" % (paths,)),
        (3, "taxonomy present, digest-matched, bands not unknown",
         bool(taxonomy) and snap_digest == record.get("taxonomy_digest") and bands_known,
         "snapshot=%s record=%s bands=%s/%s"
         % (snap_digest, record.get("taxonomy_digest"),
            (record.get("difficulty") or {}).get("band"),
            (record.get("impact") or {}).get("band"))),
        (4, "path matches auto_route_allow", bool(ar and ar["allowed"]),
         "; ".join(ar["reasons"]) if ar else "not evaluated (no single literal path)"),
        (5, "path matches NO entry in the sensitive set", bool(ar and not ar["sensitive"]),
         "sensitive=%s" % (ar["sensitive"] if ar else "not evaluated")),
        (6, "no test file touched", bool(one) and not is_test_path(one),
         "path=%s" % one),
    ]
    return [{"n": n, "name": name, "pass": bool(ok), "why": why}
            for n, name, ok, why in out]


def triage_request(request, repo=".", session_id=None, base_commit=None,
                   t3_category=None, ts=None, **kwargs):
    """Score ONE change request, bind it, write its record, and report the tier.

    Called by `hooks/triage-prompt-nudge.sh` (the UserPromptSubmit hook, which is the
    mechanical producer) and by `commands/v-triage.md` step T2 (the human/agent entry
    point). Both go through here; neither re-derives any of it.

    Returns a dict with, always:
        pre_eval_id, tier, decision, flavor, needs_t3, record_ref, predicates,
        declared_paths
    plus `disabled` (the `pre_eval.enabled: false` no-op), `t3_prompt` + `t3_reason`
    when `needs_t3`,
    `member` (all six predicates hold), `override_fired`, `refused_paths`, and the
    binding echoed back.

    THE BINDING GOES THROUGH `build_record`'s kwarg, never onto the record afterwards.
    `digest` covers the whole record, so attaching the binding after the fact would ship
    a record whose own integrity digest no longer verifies — silently, because `digest`
    is optional and only checked when present. `run_preeval(binding=…)` is how the binding
    reaches the ONE place that keeps the digest correct by construction, while
    `run_preeval` keeps owning the config kill-switch, the taxonomy snapshot, the Tier-2
    lookup and the `predicted` event. It is a plain parameter, never a monkey-patch of the
    module's `build_record` global: a patch is not re-entrant, and two overlapping calls in
    one interpreter would leave later records bound to an earlier call's session.

    `session_id` is bound EXACTLY as given, and an empty one binds null. The Stop-time
    triage gate compares it verbatim, so an invented value would claim coverage that does
    not exist — the fail-closed direction is a record that covers nothing.
    """
    request = (request or "").strip()
    if not request:
        raise ValueError("triage needs a request")

    sid = (session_id or "").strip() or None
    base = (base_commit or "").strip() or None

    # THE OUTCOME STREAM BELONGS TO THE REPO THE RECORD BELONGS TO, and it has to be
    # said out loud here: `compound-v-triage-outcomes.default_stream_path()` derives its
    # path from the MODULE's location (the parent of `scripts/`), not from `repo`. In a
    # dogfooding checkout those are the same directory and the difference is invisible;
    # for `hooks/triage-prompt-nudge.sh`, which runs an installed plugin's engine against
    # a different project, they are not, and the `predicted` event would land in the
    # plugin checkout while the record it keys landed in the project. Pinning it from
    # `repo` keeps the pair together. A caller that knows better still wins.
    kwargs.setdefault("stream_path",
                      os.path.join(repo or ".", "docs", "superpowers", "memory",
                                   "triage-outcomes.jsonl"))

    binding = {"session_id": sid, "base_commit": base}

    res = run_preeval(request, repo=repo, t3_category=t3_category, ts=ts,
                      binding=binding, **kwargs)

    base_out = {
        "pre_eval_id": res.get("pre_eval_id"),
        "needs_t3": bool(res.get("needs_t3")),
        "record_ref": res.get("record_ref"),
        "predicates": [],
        "declared_paths": [],
        "refused_paths": list(res.get("refused_paths") or []),
        "session_id": sid,
        "base_commit": base,
        "disabled": bool(res.get("pre_eval_disabled")),
        "member": False,
        "override_fired": res.get("override_fired"),
        # v3.4.1 §A3 — ALWAYS present, null when there is no flavor. The hook and
        # `/v:orchestrate` both read it; an absent key would make "no flavor" and "an older
        # engine that cannot produce one" look identical to a caller.
        "flavor": None,
    }

    # `pre_eval.enabled: false` — the whole stage is a no-op. NOTHING was written, so
    # there is no record to report and no predicate to evaluate; the change is FULL by
    # the operator's own configuration.
    if res.get("pre_eval_disabled"):
        base_out.update(decision=DECISION_FULL,
                        tier=DECISION_TO_TIER[DECISION_FULL])
        return base_out

    # The deterministic layers could not band this request. No record was written and no
    # `predicted` event appended; the caller runs the light classify Task and re-invokes
    # with `t3_category`. A hook cannot run a Task, which is why the hook treats this as
    # "hand it to /v:triage" rather than as a result.
    if res.get("needs_t3"):
        base_out.update(decision=None, tier=None, t3_prompt=res.get("t3_prompt"),
                        t3_reason=res.get("t3_reason"),
                        t3_categories=list(T3_CATEGORIES))
        return base_out

    rec = res["record"]
    predicates = auto_route_predicates(rec, repo, res["pre_eval_id"])
    base_out.update(
        decision=rec["decision"],
        tier=DECISION_TO_TIER.get(rec["decision"]),
        predicates=predicates,
        declared_paths=list(rec.get("declared_paths") or []),
        member=all(p["pass"] for p in predicates),
        override_fired=rec.get("override_fired"),
        flavor=rec.get("flavor"),
    )
    return base_out


def _triage_cli(argv):
    """`compound-v-preeval.py triage …` — the subcommand both callers invoke."""
    ap = argparse.ArgumentParser(prog="compound-v-preeval.py triage")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--request", help="the change request as text")
    src.add_argument("--request-env", dest="request_env", metavar="NAME",
                     help="read the request from environment variable NAME. This is the "
                          "form both shipped callers use: a prompt is arbitrary user text "
                          "and does not belong on argv, where it is visible to every "
                          "process on the machine and has to survive shell quoting.")
    ap.add_argument("--repo", default=".", help="repo root (default: cwd)")
    ap.add_argument("--session-id", dest="session_id", default=None,
                    help="the harness session id to BIND this record to. Bound verbatim; "
                         "absent binds null, which covers nothing at the Stop gate.")
    ap.add_argument("--base-commit", dest="base_commit", default=None,
                    help="HEAD as the caller sees it. Supplied rather than read: this "
                         "module never runs git.")
    ap.add_argument("--t3-category", dest="t3_category", choices=list(T3_CATEGORIES),
                    help="pre-resolved T3 enum for a needs_t3 re-invocation")
    ap.add_argument("--taxonomy", help="taxonomy YAML path (default: .claude/…yaml)")
    ap.add_argument("--json", action="store_true",
                    help="emit the result as JSON (the only supported output today; the "
                         "flag is accepted so both callers can be explicit)")
    args = ap.parse_args(argv)

    if args.request_env:
        request = os.environ.get(args.request_env) or ""
    else:
        request = args.request or ""
    if not request.strip():
        sys.stderr.write("REFUSED: triage needs a non-empty request\n")
        return 2

    try:
        out = triage_request(request, repo=args.repo, session_id=args.session_id,
                             base_commit=args.base_commit,
                             t3_category=args.t3_category,
                             taxonomy_path=args.taxonomy)
    except (OSError, ValueError, RuntimeError) as exc:
        sys.stderr.write("triage failed: %s\n" % exc)
        return 1
    print(json.dumps(out, indent=2, sort_keys=True, default=str))
    return 0


# --------------------------------------------------------------------------- #
# CLI.
# --------------------------------------------------------------------------- #
def main(argv):
    if "--selftest" in argv[1:]:
        return _selftest()

    # A subcommand, not a flag: `triage` is a different verb from "score this
    # localization", and argparse cannot express both in one flag namespace without
    # making every existing flag optional-but-meaningless on the new path.
    if len(argv) > 1 and argv[1] == "triage":
        return _triage_cli(argv[2:])

    ap = argparse.ArgumentParser(prog="compound-v-preeval.py")
    ap.add_argument("--request", help="the free-text change request")
    ap.add_argument("--repo", default=".", help="repo root (default: cwd)")
    ap.add_argument("--taxonomy", help="taxonomy YAML path (default: .claude/…yaml)")
    ap.add_argument("--t3-category", dest="t3_category", choices=list(T3_CATEGORIES),
                    help="pre-resolved T3 enum (the engine never calls a model)")
    ap.add_argument("--pre-eval-id", dest="pre_eval_id", help="explicit pre_eval_id")
    ap.add_argument("--run-dir", dest="run_dir", default=None,
                    help="completed execution run directory (<run-dir>/results/*.json) for "
                         "the POST-RUN advisor-hot reclassification sensor. Absent => the "
                         "sensor is off (advisor_hot stays False; unchanged pre-dispatch "
                         "behavior). Must resolve inside the repo root.")
    ap.add_argument("--cross-model-review", metavar="TIER_OR_DECISION",
                    help="print the cross-model (second-family) review gate for a "
                         "triage tier or decision constant, as JSON, and exit. "
                         "Derived from the tier — the same entry criterion as "
                         "brainstorming: no brainstorm, no second opinion.")
    ap.add_argument("--flavor", default=None,
                    help="with --cross-model-review: the record's/manifest's triage "
                         "flavor (scoped_plus makes the second opinion mandatory)")
    ap.add_argument("--score-only", action="store_true",
                    help="pure scoring from --localization-json, no writes")
    ap.add_argument("--localization-json", dest="localization_json",
                    help="a localization dict (for --score-only)")
    ap.add_argument("--fan-out-threshold", type=int, default=1)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv[1:])
    if getattr(args, "cross_model_review", None):
        required, why = cross_model_review_for(args.cross_model_review,
                                               flavor=getattr(args, "flavor", None))
        print(json.dumps({"input": args.cross_model_review,
                          "cross_model_review": required,
                          "why": why}, indent=2, sort_keys=True))
        return 0

    if args.score_only:
        if not args.localization_json:
            ap.error("--score-only requires --localization-json")
        try:
            localization = json.loads(args.localization_json)
        except ValueError as e:
            ap.error("invalid --localization-json: %s" % e)
        taxonomy, _bytes, _v = _load_taxonomy(args.repo, args.taxonomy)
        # --score-only used to pass NEITHER churn_hot NOR tier2 NOR advisor_hot, while
        # run_preeval passes all three. The probe therefore reported a systematically
        # CHEAPER tier than the engine actually produces — always in the optimistic
        # direction, which is the worst direction for a surface people use to ask
        # "would this be DIRECT?". Observed 2026-09-01: README.md read low/low here and
        # low/high through run_preeval, from an identical localization.
        # These are computed the same way run_preeval computes them; each degrades to
        # its inert value rather than failing, exactly as it does there.
        try:
            churn_hot = _churn_hot_for(args.repo, localization.get("resolved_paths", []))
        except Exception:  # noqa: BLE001 — advisory signal, never break the probe
            churn_hot = False
        try:
            tier2 = _triage_mod().tier2_lookup(repo=args.repo)
        except Exception:  # noqa: BLE001
            tier2 = None
        verdict = score(localization, taxonomy, t3_category=args.t3_category,
                        tier2=tier2, churn_hot=churn_hot,
                        fan_out_threshold=args.fan_out_threshold,
                        request_text=args.request or "")
        print(json.dumps(verdict, indent=2, sort_keys=True))
        return 0

    if args.request is None:
        ap.error("--request is required (or use --selftest / --score-only)")
    if args.run_dir is not None and not _run_dir_contained(args.repo, args.run_dir):
        ap.error("--run-dir %r resolves outside the repo root (path-containment "
                 "rejected)" % args.run_dir)
    result = run_preeval(args.request, repo=args.repo, taxonomy_path=args.taxonomy,
                         t3_category=args.t3_category, pre_eval_id=args.pre_eval_id,
                         run_dir=args.run_dir)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


# --------------------------------------------------------------------------- #
# Self-test (TDD — the spec §2 truth-table fixtures).
# --------------------------------------------------------------------------- #
_EXAMPLE_TAXONOMY_TEXT = """
version: 1
path_patterns:
  - glob: "**/*.css"
    difficulty_band: low
    impact_band: low
  - glob: "**/*.tsx"
    difficulty_band: medium
    impact_band: medium
  - glob: "src/auth/**"
    difficulty_band: high
    impact_band: high
  - glob: "**/migrations/**"
    difficulty_band: high
    impact_band: high
content_patterns:
  - match: "feature_flag"
    pattern_type: literal
    case: insensitive
    scan: content
    kind: feature_flag
    impact_band: high
  - match: "--color-"
    pattern_type: literal
    case: insensitive
    scan: content
    kind: shared_token
    impact_band: high
sensitive_path_list:
  - "src/auth/**"
  - "**/migrations/**"
churn:
  exclude_paths: []
  format_commit_patterns: []
"""


# One glob per matrix cell, so a fixture selects a (difficulty, impact) pair by PATH alone
# and every cell test differs from its neighbours in nothing but the bands. `sensitive_path_list`
# is non-empty (and disjoint from `m/**`) because `_has_safety_coverage` fails closed without it.
#
# v3.4.1: every glob NAMES THE FILE rather than saying `m/<cell>/**`. The rows are the same
# rows and the bands are the same bands, but a broad glob would now hand the FULL cells to
# §A2's demotion branch, which is a different mechanism and has its own cells below. What is
# under test here is the band→tier mapping and nothing else, so the fixture says "the taxonomy
# means THIS file" as plainly as it can.
_MATRIX_TAXONOMY_TEXT = """
version: 1
path_patterns:
  - glob: "m/dlow-ilow/f.txt"
    difficulty_band: low
    impact_band: low
  - glob: "m/dlow-imedium/f.txt"
    difficulty_band: low
    impact_band: medium
  - glob: "m/dlow-ihigh/f.txt"
    difficulty_band: low
    impact_band: high
  - glob: "m/dmedium-ilow/f.txt"
    difficulty_band: medium
    impact_band: low
  - glob: "m/dmedium-imedium/f.txt"
    difficulty_band: medium
    impact_band: medium
  - glob: "m/dmedium-ihigh/f.txt"
    difficulty_band: medium
    impact_band: high
  - glob: "m/dhigh-ilow/f.txt"
    difficulty_band: high
    impact_band: low
  - glob: "m/dhigh-imedium/f.txt"
    difficulty_band: high
    impact_band: medium
  - glob: "m/dhigh-ihigh/f.txt"
    difficulty_band: high
    impact_band: high
content_patterns:
  - match: "--color-"
    pattern_type: literal
    case: insensitive
    scan: content
    kind: shared_token
    impact_band: high
sensitive_path_list:
  - "src/auth/**"
churn:
  exclude_paths: []
  format_commit_patterns: []
"""

# spec §A1's table, transcribed ONCE as data so the selftest asserts against the spec rather
# than against `_TIER_MATRIX` (asserting a table against itself proves nothing).
_SPEC_A1_MATRIX = {
    ("low", "low"): DECISION_FASTPATH,
    ("low", "medium"): DECISION_SCOPED,
    ("low", "high"): DECISION_FULL,
    ("medium", "low"): DECISION_SCOPED,
    ("medium", "medium"): DECISION_SCOPED,
    ("medium", "high"): DECISION_FULL,
    ("high", "low"): DECISION_FULL,
    ("high", "medium"): DECISION_FULL,
    ("high", "high"): DECISION_FULL,
}


# v3.4.1 §A2/§A3/§A5 — the breadth taxonomy. `scripts/**` and `hooks/**` are BROAD rows
# banded high/high (this repository's own shape); `src/specific/one.py` is a NAMED row so a
# path it matches can never be demoted; `**/*.md` is broad but already low/low, which is the
# fixture that proves the demotion never fires on a change the matrix already routes
# proportionately. `content_scan_exclude` suppresses the legal-copy scan on markdown.
_BREADTH_TAXONOMY_TEXT = """
version: 1
path_patterns:
  - glob: "scripts/**"
    difficulty_band: high
    impact_band: high
  - glob: "hooks/**"
    difficulty_band: high
    impact_band: high
  - glob: "docs/**"
    difficulty_band: low
    impact_band: low
  - glob: "**/*.md"
    difficulty_band: low
    impact_band: low
  - glob: "src/specific/one.py"
    difficulty_band: high
    impact_band: high
content_patterns:
  - match: "privacy policy"
    pattern_type: literal
    case: insensitive
    scan: content
    kind: legal_copy
    impact_band: high
sensitive_path_list:
  - "hooks/**"
  - "**/*.pem"
  - "**/*.key"
  - "**/*.env"
  - ".github/**"
content_scan_exclude:
  - "**/*.md"
churn:
  exclude_paths: []
  format_commit_patterns: []
"""


def _loc(paths, flags=None, fan_out=None, confidence="exact"):
    return {"resolved_paths": list(paths), "fan_out": fan_out if fan_out is not None
            else len(paths), "flags": list(flags or []), "confidence": confidence}


def _selftest():
    import tempfile

    failures = []

    def expect(name, cond):
        print(("  ok   - " if cond else "  FAIL - ") + name)
        if not cond:
            failures.append(name)

    tax = _tax()
    taxonomy = tax.load_taxonomy(text=_EXAMPLE_TAXONOMY_TEXT)

    # ---------- identity helpers ---------- #
    expect("slugify normalizes", slugify("Make BUTTON X red!") == "make-button-x-red")
    expect("slugify empty -> hashed", slugify("!!!").startswith("req-"))
    pid = mint_pre_eval_id("make button red", ts_iso="2026-07-12T10:15:00Z")
    expect("pre_eval_id matches the canonical pattern", bool(PRE_EVAL_ID_RE.match(pid)))
    expect("pre_eval_id carries the compact stamp", pid.startswith("2026-07-12T101500Z-"))
    expect("fingerprint stable across whitespace",
           request_fingerprint("make   button  red") == request_fingerprint("make button red"))

    # ================= Layer-A overrides — one deterministic fixture per row ========= #

    # AC-1 (MANDATORY) — "make button X red" → shared design token → override #3 → FULL.
    v = score(_loc(["src/ui/button.css", "src/ui/card.css"], flags=["shared_token"],
                   fan_out=2), taxonomy, request_text="make button X red")
    # --- v3.1.0: the cross-model review gate rides the SAME tier ----------------
    expect("DIRECT asks for no second opinion — nothing was brainstormed",
           cross_model_review_for(DECISION_FASTPATH)[0] is False)
    expect("SCOPED asks for no second opinion by default",
           cross_model_review_for(DECISION_SCOPED)[0] is False)
    expect("FULL asks for one",
           cross_model_review_for(DECISION_FULL)[0] is True)
    expect("the manifest's tier token answers identically to the decision constant",
           all(cross_model_review_for(t)[0] == cross_model_review_for(d)[0]
               for d, t in DECISION_TO_TIER.items()))
    # v3.4.1 (archaeology constraint 11): SCOPED+ is the one SCOPED shape whose
    # second opinion is mandatory — the helper must say so, or /v:dispatch would
    # read "no by default" for the very run the flavor exists to review harder.
    expect("SCOPED+ (flavor scoped_plus) asks for a second opinion, mandatory",
           cross_model_review_for(DECISION_SCOPED, flavor="scoped_plus")[0] is True
           and cross_model_review_for("SCOPED", flavor="scoped_plus")[0] is True)
    expect("a plain SCOPED with no flavor still asks for none",
           cross_model_review_for("SCOPED", flavor=None)[0] is False
           and cross_model_review_for("SCOPED", flavor="")[0] is False)
    expect("an unrecognised size falls to 'review', never to 'skip'",
           cross_model_review_for("something-else")[0] is True
           and cross_model_review_for(None)[0] is True)
    expect("every branch explains itself",
           all(len(cross_model_review_for(k)[1]) > 30
               for k in (DECISION_FASTPATH, DECISION_SCOPED, DECISION_FULL, "x")))
    expect("the gate covers every decision the engine can emit",
           set(CROSS_MODEL_REVIEW_BY_DECISION) == set(DECISION_TO_TIER))

    expect("AC-1: shared-token 'make button red' -> FULL_PIPELINE", v["decision"] == DECISION_FULL)
    expect("AC-1: override #3 (shared_token/a11y) fired", v["override_fired"] == 3)
    expect("AC-1: no model call needed (needs_t3 False)", v["needs_t3"] is False)

    # #1 localization failed ∨ ambiguous.
    v1a = score(_loc([], confidence="failed"), taxonomy)
    expect("override #1: localization failed -> FULL", v1a["override_fired"] == 1)
    v1b = score(_loc(["a.css", "b.css", "c.css"], confidence="ambiguous", fan_out=3),
                taxonomy)
    expect("override #1: localization ambiguous -> FULL",
           v1b["override_fired"] == 1 and v1b["decision"] == DECISION_FULL)

    # #2 sensitive path. REWRITTEN for v3.4.1 §A3: override #2 is now CONDITIONAL. A
    # sensitive path with a fan-out above two is still the unconditional override this cell
    # has always asserted; the small-edit case it used to cover is the SCOPED+ branch, and
    # its cells live in the §A3 block below.
    v2 = score(_loc(["src/auth/login.py", "src/auth/session.py", "src/auth/token.py"],
                    flags=["sensitive_path"], fan_out=3), taxonomy)
    expect("override #2: sensitive path (fan_out above the small-edit ceiling) -> FULL",
           v2["override_fired"] == 2 and v2["decision"] == DECISION_FULL)
    v2b = score(_loc(["src/auth/login.py"], flags=["sensitive_path"]), taxonomy)
    expect("override #2: a SMALL sensitive edit asks T3 first (§A3), it does not "
           "unconditionally override",
           v2b.get("needs_t3") is True and v2b.get("t3_reason") == "sensitive")

    # #3 also fires for a11y state + generated artifact.
    v3a = score(_loc(["x.css"], flags=["is_a11y_state"]), taxonomy)
    expect("override #3: a11y state -> FULL", v3a["override_fired"] == 3)
    v3b = score(_loc(["dist/app.js"], flags=["is_generated"]), taxonomy)
    expect("override #3: generated artifact -> FULL", v3b["override_fired"] == 3)

    # #4 semantic-vs-path disagreement: T1 low (.css) but T3 user-facing-major.
    v4 = score(_loc(["x.css"], flags=[]), taxonomy, t3_category="user-facing-major")
    expect("override #4: T1 low vs T3 major -> FULL", v4["override_fired"] == 4)
    # ...and the converse: T1 high (auth) — but that path is sensitive so #2 wins first;
    # use a migrations .css-free high path via **/migrations/** vs T3 plumbing instead.
    # migrations is sensitive too → override #2 precedes #4 (cheap override wins). Assert #2.
    # v3.4.1: with fan_out above the small-edit ceiling the sensitive path takes the
    # unconditional override, which is the ordering this cell is about.
    v4b = score(_loc(["db/migrations/003.ts", "db/migrations/004.ts",
                      "db/migrations/005.ts"], flags=[], fan_out=3), taxonomy,
                t3_category="plumbing")
    expect("cheap override precedes #4 (migrations sensitive -> #2)",
           v4b["override_fired"] == 2)

    # #5 churn-hot.
    v5 = score(_loc(["x.css"], flags=[]), taxonomy, churn_hot=True)
    expect("override #5: churn hot -> FULL", v5["override_fired"] == 5 and "churn" in
           v5["tiers_signalled"])

    # #7 advisor-hot (escalation-only, cloned from churn). advisor_hot=True escalates a change
    # that would otherwise be trivially FASTPATH_ELIGIBLE (low/low single literal path) -> FULL.
    v7 = score(_loc(["src/ui/button.css"], flags=[], fan_out=1), taxonomy,
               advisor_hot=True, request_text="tweak local button padding")
    expect("override #7: advisor hot -> FULL", v7["override_fired"] == 7
           and v7["decision"] == DECISION_FULL)
    expect("override #7: escalation-only -> high/high axes", v7["difficulty"]["band"] == "high"
           and v7["impact"]["band"] == "high")
    # advisor_hot=False (the default, and absence) must NOT escalate: the same trivial change
    # stays FASTPATH_ELIGIBLE. Escalation-only can only push UP, never down.
    v7cold = score(_loc(["src/ui/button.css"], flags=[], fan_out=1), taxonomy,
                   advisor_hot=False, request_text="tweak local button padding")
    expect("advisor_hot=False does NOT escalate (stays FASTPATH)",
           v7cold["decision"] == DECISION_FASTPATH and v7cold["override_fired"] is None)
    v7absent = score(_loc(["src/ui/button.css"], flags=[], fan_out=1), taxonomy,
                     request_text="tweak local button padding")
    expect("advisor_hot default (absence) does NOT escalate",
           v7absent["decision"] == DECISION_FASTPATH and v7absent["override_fired"] is None)
    # churn precedes advisor when BOTH are hot (cheap override #5 wins; both -> identical FULL).
    v7both = score(_loc(["x.css"], flags=[]), taxonomy, churn_hot=True, advisor_hot=True)
    expect("churn (#5) precedes advisor (#7) when both hot", v7both["override_fired"] == 5)

    # #6 any axis unknown (unclassified path + T3 unknown).
    v6 = score(_loc(["weird/thing.xyz"], flags=[]), taxonomy, t3_category="unknown")
    expect("override #6: unknown axis -> FULL", v6["override_fired"] == 6)
    expect("override #6: both axes unknown", v6["difficulty"]["band"] == "unknown"
           and v6["impact"]["band"] == "unknown")

    # ================= Layer-B positive gate + band composition ===================== #

    # Trivial CSS fix that is NOT a shared token → low/low, fan_out 1, single literal → ELIGIBLE.
    ve = score(_loc(["src/ui/button.css"], flags=[], fan_out=1), taxonomy,
               request_text="tweak the local button padding")
    expect("Layer-B: trivial single-path low/low -> FASTPATH_ELIGIBLE",
           ve["decision"] == DECISION_FASTPATH and ve["override_fired"] is None)
    expect("Layer-B eligible: display labels derived post-decision",
           ve["difficulty"]["display"] == 2 and ve["impact"]["display"] == 2)

    # fan_out over threshold blocks the DIRECT predicates. v3.0: the bands are still low/low,
    # so this demotes ONE tier to SCOPED, not all the way to FULL (spec §A1 — the matrix owns
    # the tier; the Layer-B predicates only gate the DIRECT cell). Pre-3.0 this asserted FULL.
    vfan = score(_loc(["src/ui/button.css"], flags=[], fan_out=3), taxonomy)
    expect("Layer-B: fan_out>threshold -> SCOPED (low/low bands, no override)",
           vfan["decision"] == DECISION_SCOPED and vfan["override_fired"] is None)

    # Two literal paths → not a single-path partition → not DIRECT, but still low/low → SCOPED.
    vtwo = score(_loc(["a.css", "b.css"], flags=[], fan_out=2), taxonomy)
    expect("Layer-B: two paths -> SCOPED", vtwo["decision"] == DECISION_SCOPED)

    # A content:feature_flag hit raises impact → not low → FULL (AC-8, no override).
    vff = score(_loc(["src/config.css"], flags=["content:feature_flag"], fan_out=1),
                taxonomy)
    expect("Layer-B: content:feature_flag raises impact -> FULL",
           vff["decision"] == DECISION_FULL and vff["impact"]["band"] == "high")

    # regex_timeout is fail-closed content evidence → impact high → FULL.
    vrt = score(_loc(["src/ui/button.css"], flags=["regex_timeout"], fan_out=1), taxonomy)
    expect("fail-closed regex_timeout -> FULL", vrt["decision"] == DECISION_FULL)

    # medium-band path (.tsx) → medium/medium. v3.0: that is the matrix's centre cell, SCOPED.
    # Pre-3.0 this collapsed to FULL — one of the 8 of 9 cells spec §A1 exists to un-collapse.
    vmed = score(_loc(["src/ui/Widget.tsx"], flags=[], fan_out=1), taxonomy)
    expect("Layer-B: medium/medium path -> SCOPED", vmed["decision"] == DECISION_SCOPED
           and vmed["impact"]["band"] == "medium")

    # ============ v3.0 spec §A1 — the 3x3 matrix, ALL NINE CELLS, inside the engine ==== #
    # Every fixture is identical but for the path, and every path differs only in the band
    # pair its taxonomy row declares — so a failing cell can only mean the matrix is wrong.
    # Each carries a single literal path and fan_out=1, i.e. the DIRECT predicates HOLD, so
    # the only thing under test in each cell is the band→tier mapping itself.
    mtx = tax.load_taxonomy(text=_MATRIX_TAXONOMY_TEXT)
    _cell_names = {DECISION_FASTPATH: "DIRECT", DECISION_SCOPED: "SCOPED",
                   DECISION_FULL: "FULL"}
    for (_d, _i), _want in sorted(_SPEC_A1_MATRIX.items()):
        _path = "m/d%s-i%s/f.txt" % (_d, _i)
        _v = score(_loc([_path], flags=[], fan_out=1), mtx,
                   request_text="matrix cell %s/%s" % (_d, _i))
        expect("matrix cell difficulty=%s impact=%s -> %s" % (_d, _i, _cell_names[_want]),
               _v["decision"] == _want and _v["override_fired"] is None
               and _v["difficulty"]["band"] == _d and _v["impact"]["band"] == _i)

    # The matrix is FAIL-CLOSED BY CONSTRUCTION, not only by override #6 arriving first:
    # ask the pure lookup directly for every pair the table does not contain.
    for _bad in (("unknown", "low"), ("low", "unknown"), ("unknown", "unknown"),
                 (None, "low"), ("low", None), (None, None), ("critical", "low")):
        expect("matrix fail-closed: %r -> FULL" % (_bad,),
               _matrix_decision(*_bad) == DECISION_FULL)
    expect("matrix covers exactly the 9 spec §A1 cells and nothing else",
           set(_TIER_MATRIX) == set(_SPEC_A1_MATRIX)
           and all(_TIER_MATRIX[k] == v for k, v in _SPEC_A1_MATRIX.items()))

    # ===== ANY FIRED OVERRIDE FORCES FULL — the single most load-bearing line in A1 ===== #
    # Override #4 is the one that makes the hazard real: it records the GENUINE low/low
    # bands beside override_fired=4. Assert BOTH halves — that the bands really are low/low
    # (so this is not a vacuous test), and that a post-hoc reader of exactly those bands
    # WOULD have said DIRECT — while the engine says FULL.
    vov = score(_loc(["x.css"], flags=[]), taxonomy, t3_category="user-facing-major")
    expect("override #4 records genuine low/low bands",
           vov["difficulty"]["band"] == "low" and vov["impact"]["band"] == "low")
    expect("override #4: a post-hoc read of those bands WOULD have granted DIRECT",
           _matrix_decision(vov["difficulty"]["band"], vov["impact"]["band"])
           == DECISION_FASTPATH)
    expect("override #4: the ENGINE says FULL_PIPELINE despite low/low",
           vov["decision"] == DECISION_FULL and vov["override_fired"] == 4)

    # And the structural backstop itself: `_verdict` is the single construction point, so a
    # proportionate decision handed in beside ANY override id comes back out as FULL.
    for _row in (1, 2, 3, 4, 5, 6, 7):
        for _proportionate in (DECISION_FASTPATH, DECISION_SCOPED):
            _forced = _verdict(_proportionate, override=_row, diff="low", imp="low",
                               tiers=["T1"], min_sample="insufficient")
            expect("_verdict forces FULL: override #%d beside %s" % (_row, _proportionate),
                   _forced["decision"] == DECISION_FULL
                   and _forced["override_fired"] == _row)
    # ...and that it does NOT touch a clean verdict (the backstop must not be a blanket).
    _clean = _verdict(DECISION_SCOPED, override=None, diff="medium", imp="medium",
                      tiers=["T1"], min_sample="insufficient")
    expect("_verdict leaves an override-free SCOPED verdict alone",
           _clean["decision"] == DECISION_SCOPED)

    # The tier vocabulary downstream reads (tasks 2/3/4 consume this as an interface).
    expect("DECISION_TO_TIER maps all three decisions to the manifest triage tokens",
           DECISION_TO_TIER == {DECISION_FASTPATH: "DIRECT", DECISION_SCOPED: "SCOPED",
                                DECISION_FULL: "FULL"})

    # ================= T3 total truth table (enum → both axes) ====================== #
    # An unclassified path (no path_pattern) + T2 insufficient → T3 fallback.
    # plumbing → low/low + single literal + fan1 → ELIGIBLE (taxonomy loaded = safety cover).
    vt_plumb = score(_loc(["tools/gen.py"], flags=[], fan_out=1), taxonomy,
                     t3_category="plumbing")
    expect("T3 plumbing (loaded taxonomy) -> low/low -> ELIGIBLE",
           vt_plumb["decision"] == DECISION_FASTPATH and "T3" in vt_plumb["tiers_signalled"])
    vt_minor = score(_loc(["tools/gen.py"], flags=[], fan_out=1), taxonomy,
                     t3_category="user-facing-minor")
    expect("T3 user-facing-minor -> medium/medium -> SCOPED",
           vt_minor["decision"] == DECISION_SCOPED and vt_minor["impact"]["band"] == "medium")
    vt_major = score(_loc(["tools/gen.py"], flags=[], fan_out=1), taxonomy,
                     t3_category="user-facing-major")
    expect("T3 user-facing-major -> high/high -> FULL",
           vt_major["decision"] == DECISION_FULL and vt_major["difficulty"]["band"] == "high")

    # T3 impact may only RAISE, never lower below T1: unclassified path won't lower a
    # would-be-high content flag (covered above); here confirm T3 major raises None→high.
    expect("T3 impact raises when T1 unclassified", vt_major["impact"]["band"] == "high")

    # needs_t3: unclassified path, T2 insufficient, no category → parent-Task handoff.
    vneed = score(_loc(["tools/gen.py"], flags=[], fan_out=1), taxonomy,
                  request_text="do the thing", token_cap=20000)
    expect("needs_t3 when T1 unclassified + no category", vneed.get("needs_t3") is True)
    expect("needs_t3 carries a ready prompt naming the enums",
           isinstance(vneed.get("t3_prompt"), str)
           and all(c in vneed["t3_prompt"] for c in T3_CATEGORIES))

    # token-cap overrun at the T3 boundary → abort → FULL (never calls a model).
    vcap = score(_loc(["tools/gen.py"], flags=[], fan_out=1), taxonomy,
                 request_text="x" * 5000, token_cap=10)
    expect("token-cap overrun -> abort -> FULL (no needs_t3)",
           vcap.get("needs_t3") is False and vcap["decision"] == DECISION_FULL)

    # ===== v3.4.1 §A2/§A3/§A4/§A5 — the size of a code change reaches the tier ======= #
    # The 3.4 probe's finding: any change under `scripts/**` was FULL by taxonomy glob
    # regardless of size, because a BROAD glob's bands were treated as if a specific row
    # had named the file. These cells pin the four decisions that fix it.
    btax = tax.load_taxonomy(text=_BREADTH_TAXONOMY_TEXT)

    # --- §A2 the T3 demotion: broad glob + plumbing -> SCOPED, no flavor, no override -- #
    d_plumb = score(_loc(["scripts/x.py"], flags=[], fan_out=1), btax,
                    t3_category="plumbing", request_text="fix a typo in a log line")
    expect("demotion: broad high/high glob + plumbing -> SCOPED",
           d_plumb["decision"] == DECISION_SCOPED and d_plumb["override_fired"] is None)
    expect("demotion: a plain SCOPED carries NO flavor", d_plumb.get("flavor") is None)
    expect("demotion: the record keeps the taxonomy's bands as t3_demotion.from",
           d_plumb["t3_demotion"]["from"] == {"difficulty": "high", "impact": "high"}
           and d_plumb["t3_demotion"]["category"] == "plumbing"
           and d_plumb["t3_demotion"]["applied"] is True)
    expect("demotion: bands become medium/medium (DIRECT for code stays unreachable)",
           d_plumb["difficulty"]["band"] == "medium"
           and d_plumb["impact"]["band"] == "medium")
    expect("demotion: T3 is recorded in tiers_signalled",
           "T3" in d_plumb["tiers_signalled"] and "T1" in d_plumb["tiers_signalled"])

    # user-facing-major on the same broad path: unchanged bands -> FULL, and the record
    # still says a demotion was CONSIDERED and refused. Override #4 is NOT evaluated here
    # (the whole point is that T1 said high from a broad glob and T3 disagreed).
    d_major = score(_loc(["scripts/x.py"], flags=[], fan_out=1), btax,
                    t3_category="user-facing-major")
    expect("demotion: user-facing-major -> FULL with t3_demotion.applied false",
           d_major["decision"] == DECISION_FULL
           and d_major["t3_demotion"]["applied"] is False
           and d_major["override_fired"] is None)
    d_unknown = score(_loc(["scripts/x.py"], flags=[], fan_out=1), btax,
                      t3_category="unknown")
    expect("demotion: unknown -> FULL, bands unchanged, applied false",
           d_unknown["decision"] == DECISION_FULL
           and d_unknown["t3_demotion"]["applied"] is False)

    # needs_t3 on the demotion path, with the reason that tells the caller's log apart
    # from the pre-existing unbanded handoff.
    d_need = score(_loc(["scripts/x.py"], flags=[], fan_out=1), btax,
                   request_text="fix a typo in a log line")
    expect("demotion: no category -> needs_t3 with t3_reason 'demotion'",
           d_need.get("needs_t3") is True and d_need.get("t3_reason") == "demotion")
    d_unbanded = score(_loc(["tools/gen.py"], flags=[], fan_out=1), btax,
                       request_text="do the thing")
    expect("the pre-existing unbanded handoff reports t3_reason 'unbanded'",
           d_unbanded.get("needs_t3") is True
           and d_unbanded.get("t3_reason") == "unbanded")

    # fan_out 3 is out of the demotion's reach: no T3 is asked for at all and the broad
    # glob's own high/high bands stand.
    d_fan = score(_loc(["scripts/a.py", "scripts/b.py", "scripts/c.py"], flags=[],
                       fan_out=3), btax, request_text="rework three scripts")
    expect("demotion: fan_out 3 -> FULL and NO needs_t3 (never a model call)",
           d_fan.get("needs_t3") is False and d_fan["decision"] == DECISION_FULL
           and "t3_demotion" not in d_fan)

    # A path a SPECIFIC row names is never demoted, even beside a broad row.
    d_named = score(_loc(["src/specific/one.py"], flags=[], fan_out=1), btax,
                    request_text="one line in a named file")
    expect("demotion: a specifically-named row is not broad -> FULL, no needs_t3",
           d_named.get("needs_t3") is False and d_named["decision"] == DECISION_FULL)

    # A content flag blocks the demotion outright (fail-closed on impact).
    d_content = score(_loc(["scripts/x.py"], flags=["content:legal_copy"], fan_out=1),
                      btax, request_text="edit the notice")
    expect("demotion: a content flag blocks it -> FULL, no needs_t3",
           d_content.get("needs_t3") is False
           and d_content["decision"] == DECISION_FULL)

    # §WS-B amendment: an incomplete content scan raises impact rather than degrading
    # localization — an exact-by-name literal path whose file was too large to read.
    d_incomplete = score(_loc(["docs/notes.md"], flags=["content_scan_incomplete"],
                              fan_out=1), btax, request_text="edit a large doc")
    expect("content_scan_incomplete raises impact -> never DIRECT",
           d_incomplete["decision"] != DECISION_FASTPATH
           and d_incomplete["impact"]["band"] == "high")
    expect("content_scan_incomplete is an impact-raising flag",
           _content_raises_impact(["content_scan_incomplete"]) is True)

    # --- §A3 SCOPED+ : a small edit on a sensitive path ------------------------------ #
    sp = score(_loc(["hooks/lane-guard.sh"], flags=["sensitive_path"], fan_out=1), btax,
               t3_category="plumbing", request_text="fix a log line in the guard")
    expect("scoped_plus: sensitive + exact + fan_out 1 + plumbing -> SCOPED",
           sp["decision"] == DECISION_SCOPED)
    expect("scoped_plus: the verdict carries flavor 'scoped_plus'",
           sp["flavor"] == FLAVOR_SCOPED_PLUS)
    expect("scoped_plus: no override fired (it is override-free evidence)",
           sp["override_fired"] is None)
    expect("scoped_plus: t3_demotion records sensitive true",
           sp["t3_demotion"]["sensitive"] is True
           and sp["t3_demotion"]["applied"] is True)
    expect("scoped_plus: bands medium/medium — never DIRECT",
           sp["difficulty"]["band"] == "medium" and sp["impact"]["band"] == "medium")
    sp_need = score(_loc(["hooks/lane-guard.sh"], flags=["sensitive_path"], fan_out=1),
                    btax, request_text="fix a log line in the guard")
    expect("scoped_plus: no category -> needs_t3 with t3_reason 'sensitive'",
           sp_need.get("needs_t3") is True
           and sp_need.get("t3_reason") == "sensitive")
    sp_unknown = score(_loc(["hooks/lane-guard.sh"], flags=["sensitive_path"], fan_out=1),
                       btax, t3_category="unknown")
    expect("scoped_plus: T3 unknown on a sensitive path -> override #2 -> FULL",
           sp_unknown["decision"] == DECISION_FULL
           and sp_unknown["override_fired"] == 2)
    sp_major = score(_loc(["hooks/lane-guard.sh"], flags=["sensitive_path"], fan_out=1),
                     btax, t3_category="user-facing-major")
    expect("scoped_plus: T3 user-facing-major on a sensitive path -> override #2",
           sp_major["override_fired"] == 2)
    sp_fan = score(_loc(["hooks/a.sh", "hooks/b.sh", "hooks/c.sh"],
                        flags=["sensitive_path"], fan_out=3), btax,
                   t3_category="plumbing")
    expect("scoped_plus: fan_out 3 on a sensitive path -> override #2",
           sp_fan["override_fired"] == 2)
    sp_amb = score(_loc(["hooks/lane-guard.sh"], flags=["sensitive_path"], fan_out=1,
                        confidence="ambiguous"), btax, t3_category="plumbing")
    expect("scoped_plus: needs EXACT localization (ambiguous -> override #1)",
           sp_amb["override_fired"] == 1)

    # NEVER_DEMOTE_GLOBS — secrets and CI are not "small edits", whatever T3 says.
    for _nd in ("config/app.env", "deploy/server.pem", "deploy/id.key",
                ".github/workflows/ci.yml"):
        _v_nd = score(_loc([_nd], flags=["sensitive_path"], fan_out=1), btax,
                      t3_category="plumbing")
        expect("NEVER_DEMOTE: %s stays override #2 -> FULL" % _nd,
               _v_nd["decision"] == DECISION_FULL and _v_nd["override_fired"] == 2)
    expect("NEVER_DEMOTE_GLOBS names secrets and CI, and nothing else",
           NEVER_DEMOTE_GLOBS == ("**/*.pem", "**/*.key", "**/*.env", ".github/**"))

    # --- §A4 `new_file` is localized, but never DIRECT ------------------------------- #
    nf = score(_loc(["docs/new-note.md"], flags=[], fan_out=1, confidence="new_file"),
               btax, request_text="add a new note")
    expect("new_file: counted as localized",
           "localization" in nf["tiers_signalled"] and nf["override_fired"] is None)
    expect("new_file: low/low + one literal path is SCOPED, never DIRECT "
           "(the DIRECT predicate tests confidence == 'exact' by name)",
           nf["decision"] == DECISION_SCOPED
           and _matrix_decision(nf["difficulty"]["band"], nf["impact"]["band"])
           == DECISION_FASTPATH)
    nf_exact = score(_loc(["docs/new-note.md"], flags=[], fan_out=1), btax)
    expect("...while the SAME bands with confidence 'exact' still reach DIRECT",
           nf_exact["decision"] == DECISION_FASTPATH)

    # --- §A5 the README finding, end to end ------------------------------------------ #
    # The taxonomy's legal-copy pattern would match this prose; `content_scan_exclude`
    # stops the scan, so the flag never reaches the scorer and the typo stays DIRECT.
    md_flags = tax.classify(btax, path="README.md",
                            content="you consent to the privacy policy")["flags"]
    expect("content_scan_exclude: markdown produces no content flag", md_flags == [])
    md = score(_loc(["README.md"], flags=md_flags, fan_out=1), btax,
               request_text="fix a typo in the README")
    expect("a README typo is DIRECT (low/low, exact, one literal path)",
           md["decision"] == DECISION_FASTPATH and md["override_fired"] is None)
    md_scanned = score(_loc(["README.md"], flags=["content:legal_copy"], fan_out=1), btax)
    expect("...and WOULD have been FULL had the scan not been excluded",
           md_scanned["decision"] == DECISION_FULL)
    expect("an already-proportionate broad glob is never sent to T3 for a demotion",
           md.get("needs_t3") is False and "t3_demotion" not in md)

    # --- the flavor invariant lives at the single construction point ------------------ #
    for _row in (1, 2, 4, 6):
        _f = _verdict(DECISION_SCOPED, override=_row, diff="medium", imp="medium",
                      tiers=["T1"], min_sample="insufficient",
                      flavor=FLAVOR_SCOPED_PLUS)
        expect("_verdict drops flavor when override #%d forces FULL" % _row,
               _f["decision"] == DECISION_FULL and _f["flavor"] is None)
    _ff = _verdict(DECISION_FASTPATH, override=None, diff="low", imp="low",
                   tiers=["T1"], min_sample="insufficient", flavor=FLAVOR_SCOPED_PLUS)
    expect("_verdict refuses a flavor on any decision but SCOPED_PIPELINE",
           _ff["flavor"] is None)
    _fb = _verdict(DECISION_SCOPED, override=None, diff="medium", imp="medium",
                   tiers=["T1"], min_sample="insufficient", flavor="made-up")
    expect("_verdict refuses an unknown flavor", _fb["flavor"] is None)
    expect("every verdict reports flavor, null when there is none",
           "flavor" in d_plumb and "flavor" in md and md["flavor"] is None)

    # ================= Missing-data + safety-coverage table ========================= #
    # Absent taxonomy (None) → unconditional FULL, both axes unknown, no override id.
    vabs = score(_loc(["src/ui/button.css"], flags=[], fan_out=1), None,
                 t3_category="plumbing")
    expect("absent taxonomy -> unconditional FULL", vabs["decision"] == DECISION_FULL)
    expect("absent taxonomy -> override_fired None (missing-data, not Layer-A)",
           vabs["override_fired"] is None)
    expect("absent taxonomy -> both axes unknown",
           vabs["difficulty"]["band"] == "unknown" and vabs["impact"]["band"] == "unknown")
    # A taxonomy with NO sensitive_path_list = no safety coverage → T3 low cannot manufacture
    # eligibility (round-3 fix at the coverage boundary).
    no_cover = tax.load_taxonomy(text="version: 1\npath_patterns: []\n"
                                       "content_patterns: []\nsensitive_path_list: []\n")
    vnc = score(_loc(["tools/gen.py"], flags=[], fan_out=1), no_cover,
                t3_category="plumbing")
    expect("no-safety-coverage taxonomy -> FULL (T3 low never manufactures eligibility)",
           vnc["decision"] == DECISION_FULL)

    # ================= Tier-2 corroboration + counterfactual guard ================== #
    vt2_healthy = score(_loc(["src/ui/button.css"], flags=[], fan_out=1), taxonomy,
                        tier2={"health": "healthy", "n": 9})
    expect("T2 healthy corroborates low -> still ELIGIBLE + calibrated",
           vt2_healthy["decision"] == DECISION_FASTPATH
           and vt2_healthy["min_sample_status"] == "calibrated"
           and "T2" in vt2_healthy["tiers_signalled"])
    vt2_unhealthy = score(_loc(["src/ui/button.css"], flags=[], fan_out=1), taxonomy,
                          tier2={"health": "unhealthy", "n": 9})
    # T2 `unhealthy` raises difficulty low→medium. v3.0: with impact still low that is the
    # matrix's (medium, low) cell, SCOPED — the RAISE is what is under test here, and it
    # still holds: the change has definitively left the DIRECT auto-route class.
    expect("T2 unhealthy RAISES difficulty -> out of DIRECT, into SCOPED",
           vt2_unhealthy["decision"] == DECISION_SCOPED
           and vt2_unhealthy["decision"] != DECISION_FASTPATH
           and vt2_unhealthy["difficulty"]["band"] != "low")
    vt2_insuff = score(_loc(["src/ui/button.css"], flags=[], fan_out=1), taxonomy,
                       tier2={"status": "insufficient", "n": 0})
    expect("T2 insufficient -> min_sample_status insufficient (escalation-only)",
           vt2_insuff["min_sample_status"] == "insufficient")

    # ================= END-TO-END Phase-P runs (fake localize, no model, no git) ===== #
    def fake_localize_factory(result):
        return lambda request, repo, taxonomy_dict: dict(result)

    # Prepare a repo tree with a real taxonomy file so the snapshot content-addresses it.
    with tempfile.TemporaryDirectory() as repo:
        tax_dir = os.path.join(repo, ".claude")
        os.makedirs(tax_dir)
        tax_file = os.path.join(tax_dir, "compound-v-impact-taxonomy.yaml")
        with open(tax_file, "w", encoding="utf-8") as fh:
            fh.write(_EXAMPLE_TAXONOMY_TEXT)
        stream = os.path.join(repo, "docs", "superpowers", "memory",
                              "triage-outcomes.jsonl")

        # (a) AC-1 end-to-end: shared-token 'make button red' → FULL via override #3.
        fk = fake_localize_factory(_loc(["src/ui/button.css", "src/ui/card.css"],
                                        flags=["shared_token"], fan_out=2))
        res = run_preeval("make button X red", repo=repo, _localize=fk,
                          ts="2026-07-12T10:15:00Z", stream_path=stream)
        expect("E2E AC-1: decision FULL via override #3",
               res["decision"] == DECISION_FULL and res["record"]["override_fired"] == 3)
        expect("E2E AC-1: record written write-once",
               os.path.isfile(os.path.join(repo, res["record_ref"])))
        expect("E2E AC-1: intent + snapshot written",
               os.path.isfile(os.path.join(repo, res["intent_ref"]))
               and res["taxonomy_ref"] is not None
               and os.path.isfile(os.path.join(repo, res["taxonomy_ref"])))
        expect("E2E AC-1: taxonomy_digest content-addresses the snapshot bytes",
               res["taxonomy_digest"] == tax.taxonomy_digest_bytes(
                   open(os.path.join(repo, res["taxonomy_ref"]), "rb").read()))
        expect("E2E AC-1: predicted event appended (decision matches)",
               res["predicted_event"]["decision"] == DECISION_FULL
               and res["predicted_event"]["event"] == "predicted")
        # write-once: a second run with the SAME request reuses the pre_eval_id and rejects
        # the record overwrite (write-once record).
        # Re-running the SAME request is supported (run_preeval rediscovers the id),
        # so a byte-identical second run is an idempotent no-op — and must NOT append
        # a second predicted event to the stream the breaker reads. A run whose
        # content DIFFERS under a reused id is still refused: that is a real conflict.
        before = io.open(stream, encoding="utf-8").read().count('"event": "predicted"') \
            if os.path.isfile(stream) else 0
        again = run_preeval("make button X red", repo=repo, _localize=fk,
                            ts="2026-07-12T10:15:00Z", pre_eval_id=res["pre_eval_id"],
                            stream_path=stream)
        after = io.open(stream, encoding="utf-8").read().count('"event": "predicted"') \
            if os.path.isfile(stream) else 0
        expect("E2E: an identical re-run is an idempotent no-op", again["pre_eval_id"] == res["pre_eval_id"])
        expect("E2E: an identical re-run appends NO second predicted event", after == before)
        rec_path = os.path.join(repo, record_path(repo, res["pre_eval_id"]))
        rec = json.loads(io.open(rec_path, encoding="utf-8").read())
        rec["decision"] = "SCOPED_PIPELINE"
        conflicted = _rejects(lambda: write_record(repo, res["pre_eval_id"], rec), ValueError)
        expect("E2E: a DIFFERING record under a reused id is refused", conflicted)

        # (b) The record validates against pre-eval-record.schema.json (if jsonschema present).
        _schema_check(expect, res["record"], must_validate=True)

    with tempfile.TemporaryDirectory() as repo:
        tax_dir = os.path.join(repo, ".claude")
        os.makedirs(tax_dir)
        with open(os.path.join(tax_dir, "compound-v-impact-taxonomy.yaml"), "w",
                  encoding="utf-8") as fh:
            fh.write(_EXAMPLE_TAXONOMY_TEXT)
        stream = os.path.join(repo, "docs", "superpowers", "memory",
                              "triage-outcomes.jsonl")

        # (c) FASTPATH_ELIGIBLE end-to-end: trivial local CSS → eligible record validates,
        # and carries a non-null taxonomy_ref/digest (the schema if/then requirement).
        fk_ok = fake_localize_factory(_loc(["src/ui/button.css"], flags=[], fan_out=1))
        rese = run_preeval("tweak local button padding", repo=repo, _localize=fk_ok,
                           ts="2026-07-12T10:16:00Z", stream_path=stream)
        expect("E2E eligible: decision FASTPATH_ELIGIBLE",
               rese["decision"] == DECISION_FASTPATH)
        expect("E2E eligible: record has non-null taxonomy_ref + digest",
               rese["record"]["taxonomy_ref"] and rese["record"]["taxonomy_digest"])
        _schema_check(expect, rese["record"], must_validate=True)

        # (c2) SCOPED end-to-end (v3.0). A medium/medium path is the matrix's centre cell.
        # The record must be WRITABLE and must VALIDATE: the schema's `decision` enum held
        # only two values before this change, so every SCOPED record would have failed here
        # — which is why the enum and the engine had to move in the same commit.
        fk_scoped = fake_localize_factory(_loc(["src/ui/Widget.tsx"], flags=[], fan_out=1))
        ress = run_preeval("adjust the widget label spacing", repo=repo, _localize=fk_scoped,
                           ts="2026-07-12T10:16:30Z", stream_path=stream)
        expect("E2E scoped: decision SCOPED_PIPELINE",
               ress["decision"] == DECISION_SCOPED and ress["override_fired"] is None)
        expect("E2E scoped: bands recorded medium/medium",
               ress["record"]["difficulty"]["band"] == "medium"
               and ress["record"]["impact"]["band"] == "medium")
        expect("E2E scoped: predicted event carries the new decision verbatim",
               ress["predicted_event"]["decision"] == DECISION_SCOPED)
        _schema_check(expect, ress["record"], must_validate=True,
                      label="SCOPED record validates against pre-eval-record.schema.json")

        # (c3) The schema itself must REFUSE the pairing the engine refuses to produce:
        # a fired override beside a proportionate decision. Hand-forge that record (the
        # engine cannot emit one) and assert the schema rejects it — so the invariant
        # survives even a future producer that regresses.
        _forged = dict(ress["record"], override_fired=4)
        _schema_check(expect, _forged, must_validate=False,
                      label="schema REJECTS override_fired beside SCOPED_PIPELINE")
        _forged_fp = dict(rese["record"], override_fired=4)
        _schema_check(expect, _forged_fp, must_validate=False,
                      label="schema REJECTS override_fired beside FASTPATH_ELIGIBLE")
        _schema_check(expect, dict(ress["record"], override_fired=None), must_validate=True,
                      label="schema ACCEPTS override_fired null beside SCOPED_PIPELINE")

        # (c4) The taxonomy conditional is keyed `decision != FULL_PIPELINE`, NOT
        # `== FASTPATH_ELIGIBLE`. Keyed the old way it stopped applying the moment a third
        # tier existed and a SCOPED record with a null taxonomy validated — the fail-open
        # the check exists to prevent. The engine cannot produce that record (an absent
        # taxonomy is an unconditional FULL), so forge it and prove the SCHEMA refuses it.
        _null_tax_scoped = dict(ress["record"], taxonomy_ref=None, taxonomy_digest=None,
                                taxonomy_version=None)
        _schema_check(expect, _null_tax_scoped, must_validate=False,
                      label="schema REJECTS a null-taxonomy SCOPED_PIPELINE record")
        _null_tax_fp = dict(rese["record"], taxonomy_ref=None, taxonomy_digest=None,
                            taxonomy_version=None)
        _schema_check(expect, _null_tax_fp, must_validate=False,
                      label="schema REJECTS a null-taxonomy FASTPATH_ELIGIBLE record")
        # ...while a null-taxonomy FULL_PIPELINE record stays valid: that is the real
        # absent-taxonomy case the engine emits, and the negative keying must not break it.
        _null_tax_full = dict(ress["record"], decision=DECISION_FULL, taxonomy_ref=None,
                              taxonomy_digest=None, taxonomy_version=None)
        _schema_check(expect, _null_tax_full, must_validate=True,
                      label="schema ACCEPTS a null-taxonomy FULL_PIPELINE record")

        # ===== (c4b) v3.4.1 §A7 — flavor / t3_demotion / t3_reason / new_file ======== #
        # `flavor` is a PROMISE the manifest validator enforces (a deep review job + a
        # cross-model second opinion). Pinning it to SCOPED_PIPELINE in the schema is what
        # stops a record from making that promise where it cannot be kept.
        _sp_rec = dict(ress["record"], flavor=FLAVOR_SCOPED_PLUS,
                       t3_reason="sensitive",
                       t3_demotion={"from": {"difficulty": "high", "impact": "high"},
                                    "category": "plumbing", "applied": True,
                                    "sensitive": True})
        _schema_check(expect, _sp_rec, must_validate=True,
                      label="schema ACCEPTS a SCOPED+ record (flavor + t3_demotion + reason)")
        _schema_check(expect, dict(_sp_rec, decision=DECISION_FULL, flavor="scoped_plus"),
                      must_validate=False,
                      label="schema REJECTS flavor scoped_plus on a FULL_PIPELINE record")
        _schema_check(expect, dict(rese["record"], flavor=FLAVOR_SCOPED_PLUS),
                      must_validate=False,
                      label="schema REJECTS flavor scoped_plus on a FASTPATH record")
        _schema_check(expect, dict(_sp_rec, flavor="deluxe"), must_validate=False,
                      label="schema REJECTS an unknown flavor")
        _schema_check(expect, dict(ress["record"], t3_reason="because"),
                      must_validate=False,
                      label="schema REJECTS a t3_reason outside the three-value enum")
        _schema_check(expect, dict(ress["record"],
                                   t3_demotion={"from": {"difficulty": "high"},
                                                "category": "plumbing", "applied": True}),
                      must_validate=False,
                      label="schema REJECTS a t3_demotion missing an axis")
        # A demotion that was REFUSED is as representable as one that was applied — the
        # record keeps the question, not only the answer.
        _schema_check(expect, dict(ress["record"], decision=DECISION_FULL, t3_reason="demotion",
                                   t3_demotion={"from": {"difficulty": "high",
                                                         "impact": "high"},
                                                "category": "user-facing-major",
                                                "applied": False}),
                      must_validate=True,
                      label="schema ACCEPTS a refused demotion (applied false) on FULL")
        # §A4 — `new_file` is a fourth localization confidence, and a record carrying it is
        # never FASTPATH_ELIGIBLE (the engine's Layer-B predicate, restated as evidence).
        _nf_rec = dict(ress["record"],
                       localization=dict(ress["record"]["localization"],
                                         confidence="new_file",
                                         flags=["new_file"]))
        _schema_check(expect, _nf_rec, must_validate=True,
                      label="schema ACCEPTS localization confidence new_file on SCOPED")
        _schema_check(expect, dict(ress["record"],
                                   localization=dict(ress["record"]["localization"],
                                                     confidence="invented")),
                      must_validate=False,
                      label="schema REJECTS an unknown localization confidence")

        # ===== (c5) The three fields Feature C's triage gate reads (spec §C) ========= #
        # `hooks/epic-goal-stop.sh` decides whether a record COVERS the current diff by
        # reading session_id, declared_paths and (for display) base_commit. The schema is
        # additionalProperties:false, so until these exist NO record can carry them and NO
        # record can ever cover a diff — the gate would ship inert. The engine does not
        # produce them (it never sees a session); /v:triage does. What is tested here is
        # that they are EXPRESSIBLE and CONSTRAINED, not that this module emits them.
        _bound = dict(ress["record"],
                      session_id="sess-abc123",
                      base_commit="a1b2c3d4e5f60718293a4b5c6d7e8f9012345678",
                      declared_paths=["scripts/app.py", "scripts/", "docs/**"],
                      tier="SCOPED")
        _schema_check(expect, _bound, must_validate=True,
                      label="schema ACCEPTS session_id + base_commit + declared_paths + tier")

        # `tier` is what the gate PREFERS over `decision`, so a disagreement would exempt a
        # record as a tier its own decision refuses. Pinned for all three decisions.
        for _dec, _good, _bad in ((DECISION_FASTPATH, "DIRECT", "FULL"),
                                  (DECISION_SCOPED, "SCOPED", "DIRECT"),
                                  (DECISION_FULL, "FULL", "DIRECT")):
            _rec = dict(_bound, decision=_dec, tier=_good)
            _schema_check(expect, _rec, must_validate=True,
                          label="schema ACCEPTS tier %s beside %s" % (_good, _dec))
            _schema_check(expect, dict(_rec, tier=_bad), must_validate=False,
                          label="schema REJECTS tier %s beside %s" % (_bad, _dec))
        # ...and `tier` stays optional: the gate falls back to mapping `decision`.
        _no_tier = dict(_bound)
        _no_tier.pop("tier")
        _schema_check(expect, _no_tier, must_validate=True,
                      label="schema ACCEPTS a record with no tier (gate maps decision)")

        # session_id: null and absent both mean "binds no session", which the gate can only
        # read as covering nothing. The EMPTY STRING is rejected — it looks like a binding
        # and can never match, which is the one shape that misleads a reader.
        _schema_check(expect, dict(_bound, session_id=None), must_validate=True,
                      label="schema ACCEPTS session_id null (binds no session)")
        _schema_check(expect, dict(_bound, session_id=""), must_validate=False,
                      label="schema REJECTS an empty session_id")

        # base_commit is recorded, not decisive — but it still has to be a commit.
        _schema_check(expect, dict(_bound, base_commit=None), must_validate=True,
                      label="schema ACCEPTS base_commit null")
        _schema_check(expect, dict(_bound, base_commit="a1b2c3d"), must_validate=True,
                      label="schema ACCEPTS a short base_commit sha")
        for _badsha in ("HEAD", "A1B2C3D", "a1b2c3", "z" * 40, "a1b2c3d4 "):
            _schema_check(expect, dict(_bound, base_commit=_badsha), must_validate=False,
                          label="schema REJECTS base_commit %r" % (_badsha,))

        # declared_paths: exactly the three forms the gate's `_path_covered` understands.
        _schema_check(expect, dict(_bound, declared_paths=[]), must_validate=True,
                      label="schema ACCEPTS an empty declared_paths (covers nothing)")
        for _good_path in ("a.py", "scripts/app.py", "scripts/", "docs/**", "src/*.css"):
            _schema_check(expect, dict(_bound, declared_paths=[_good_path]),
                          must_validate=True,
                          label="schema ACCEPTS declared path %r" % (_good_path,))
        # The gate DROPS an entry carrying its own separator or a line break, which silently
        # narrows the set. Rejecting here is where the producer still finds out.
        for _bad_path in (chr(31) + "x", "a" + chr(31) + "b", "a\nb", "a\rb", chr(0) + "a",
                          "", "/abs/path", "../escape", "a/../b", "..",
                          "/", "\ttab"):
            _schema_check(expect, dict(_bound, declared_paths=[_bad_path]),
                          must_validate=False,
                          label="schema REJECTS declared path %r" % (_bad_path,))
        _schema_check(expect, dict(_bound, declared_paths=["a.py", "a.py"]),
                      must_validate=False,
                      label="schema REJECTS duplicate declared paths")
        _schema_check(expect, dict(_bound, declared_paths="scripts/"), must_validate=False,
                      label="schema REJECTS a bare-string declared_paths")

        # ===== (c6) build_record's optional binding — the digest stays correct ======== #
        # The producer is /v:triage, not this engine, but the PRIMITIVE lives here because
        # `digest` covers the whole record: a producer that attached the binding AFTER
        # calling build_record would ship a record whose self-integrity digest silently no
        # longer verifies. Passing it through keeps that impossible.
        _tax_mod = _tax()
        _bv = score(_loc(["src/ui/Widget.tsx"], flags=[], fan_out=1), taxonomy)
        _unbound = build_record("2026-07-12T101600Z-b-a1b2", "bind me", _bv,
                                _loc(["src/ui/Widget.tsx"], flags=[], fan_out=1),
                                1, "tax.yaml", "sha256:" + "0" * 64,
                                ts="2026-07-12T10:16:00Z")
        expect("build_record without a binding is unchanged (no binding keys)",
               not any(k in _unbound for k in
                       ("session_id", "base_commit", "declared_paths", "tier")))
        _boundrec = build_record("2026-07-12T101600Z-b-a1b2", "bind me", _bv,
                                 _loc(["src/ui/Widget.tsx"], flags=[], fan_out=1),
                                 1, "tax.yaml", "sha256:" + "0" * 64,
                                 ts="2026-07-12T10:16:00Z",
                                 binding={"session_id": "sess-abc123",
                                          "base_commit": "a1b2c3d4e5f6",
                                          "declared_paths": ["src/ui/Widget.tsx"]})
        expect("build_record carries the binding through",
               _boundrec["session_id"] == "sess-abc123"
               and _boundrec["base_commit"] == "a1b2c3d4e5f6"
               and _boundrec["declared_paths"] == ["src/ui/Widget.tsx"])
        expect("build_record DERIVES tier from the decision (never taken from the caller)",
               _boundrec["tier"] == DECISION_TO_TIER[_bv["decision"]])
        expect("the bound record's digest covers the binding and still verifies",
               _boundrec["digest"] == _tax_mod.record_digest(_boundrec,
                                                             exclude_field="digest")
               and _boundrec["digest"] != _unbound["digest"])
        _schema_check(expect, _boundrec, must_validate=True,
                      label="a build_record-produced bound record validates")
        # The footgun this prevents, demonstrated: bolt the fields on afterwards and the
        # digest no longer verifies.
        _bolted = dict(_unbound, session_id="sess-abc123")
        expect("bolting a binding on AFTER build_record breaks the digest (why the kwarg)",
               _bolted["digest"] != _tax_mod.record_digest(_bolted, exclude_field="digest"))

        # (d) needs_t3 end-to-end: NO record + NO predicted are written; artifacts durable.
        fk_need = fake_localize_factory(_loc(["tools/gen.py"], flags=[], fan_out=1))
        resn = run_preeval("do the mysterious thing", repo=repo, _localize=fk_need,
                           ts="2026-07-12T10:17:00Z", stream_path=stream)
        expect("E2E needs_t3: returns needs_t3 with a prompt",
               resn.get("needs_t3") is True and "t3_prompt" in resn)
        expect("E2E needs_t3: NO record written yet",
               not os.path.isfile(record_path(repo, resn["pre_eval_id"])))
        # re-entry with the resolved category completes, reusing the SAME pre_eval_id.
        resr = run_preeval("do the mysterious thing", repo=repo, _localize=fk_need,
                           t3_category="plumbing", ts="2026-07-12T10:18:00Z",
                           stream_path=stream)
        expect("E2E needs_t3 re-entry: same pre_eval_id (intent fingerprint resume)",
               resr["pre_eval_id"] == resn["pre_eval_id"])
        expect("E2E needs_t3 re-entry: now decided (plumbing -> eligible)",
               resr.get("needs_t3") is False and resr["decision"] == DECISION_FASTPATH)
        _schema_check(expect, resr["record"], must_validate=True)

    # (e) Absent-taxonomy end-to-end: no taxonomy file → FULL, null taxonomy fields, valid.
    with tempfile.TemporaryDirectory() as repo:
        stream = os.path.join(repo, "docs", "superpowers", "memory",
                              "triage-outcomes.jsonl")
        fk_any = fake_localize_factory(_loc(["src/ui/button.css"], flags=[], fan_out=1))
        resa = run_preeval("make button red", repo=repo, _localize=fk_any,
                           t3_category="plumbing", ts="2026-07-12T10:19:00Z",
                           stream_path=stream)
        expect("E2E absent-taxonomy: decision FULL", resa["decision"] == DECISION_FULL)
        expect("E2E absent-taxonomy: taxonomy_ref/digest null",
               resa["record"]["taxonomy_ref"] is None
               and resa["record"]["taxonomy_digest"] is None
               and resa["record"]["taxonomy_version"] is None)
        _schema_check(expect, resa["record"], must_validate=True)
        # A FASTPATH_ELIGIBLE record with null taxonomy MUST be impossible / rejected by schema.
        bad = dict(resa["record"])
        bad["decision"] = DECISION_FASTPATH
        _schema_check(expect, bad, must_validate=False,
                      label="null-taxonomy FASTPATH record is schema-REJECTED")

    # ============ HIGH-3: a MALFORMED (validator-rejected) taxonomy fails CLOSED ===== #
    # A taxonomy that PARSES and even carries a non-empty sensitive_path_list (so the coverage
    # check _has_safety_coverage alone would PASS) but is REJECTED by the shared validator
    # (here: missing the required `churn` block) is treated as ABSENT → unconditional
    # FULL_PIPELINE, never FASTPATH_ELIGIBLE. Proves the fix is the shared validator, not just
    # the non-empty-sensitive-list coverage heuristic.
    malformed_tax_text = (
        "version: 1\n"
        "path_patterns:\n"
        "  - glob: \"**/*.css\"\n"
        "    difficulty_band: low\n"
        "    impact_band: low\n"
        "content_patterns: []\n"
        "sensitive_path_list:\n"
        "  - \"src/auth/**\"\n"
    )  # no `churn:` block → compound-v-validate-taxonomy rejects it.
    expect("HIGH-3: shared validator rejects the malformed taxonomy",
           bool(_validate_taxonomy_mod().validate_text(malformed_tax_text)))
    with tempfile.TemporaryDirectory() as repo:
        tax_dir = os.path.join(repo, ".claude")
        os.makedirs(tax_dir)
        tax_file = os.path.join(tax_dir, "compound-v-impact-taxonomy.yaml")
        with open(tax_file, "w", encoding="utf-8") as fh:
            fh.write(malformed_tax_text)
        d, b, v = _load_taxonomy(repo, None)
        expect("HIGH-3: _load_taxonomy returns None for a malformed taxonomy",
               d is None and b is None and v is None)
        # Guard against over-rejection: a VALID taxonomy at the same path still loads.
        with open(tax_file, "w", encoding="utf-8") as fh:
            fh.write(_EXAMPLE_TAXONOMY_TEXT)
        d2, b2, v2 = _load_taxonomy(repo, None)
        expect("HIGH-3: a valid taxonomy still loads (no over-rejection)",
               d2 is not None and b2 is not None and v2 == 1)

    with tempfile.TemporaryDirectory() as repo:
        tax_dir = os.path.join(repo, ".claude")
        os.makedirs(tax_dir)
        with open(os.path.join(tax_dir, "compound-v-impact-taxonomy.yaml"), "w",
                  encoding="utf-8") as fh:
            fh.write(malformed_tax_text)
        stream = os.path.join(repo, "docs", "superpowers", "memory",
                              "triage-outcomes.jsonl")
        fk = fake_localize_factory(_loc(["src/ui/button.css"], flags=[], fan_out=1))
        resm = run_preeval("tweak local button padding", repo=repo, _localize=fk,
                           t3_category="plumbing", ts="2026-07-12T10:20:00Z",
                           stream_path=stream)
        expect("HIGH-3 E2E: malformed taxonomy -> FULL_PIPELINE (never FASTPATH)",
               resm["decision"] == DECISION_FULL and resm["decision"] != DECISION_FASTPATH)
        expect("HIGH-3 E2E: malformed taxonomy treated as absent (null ref/digest)",
               resm["record"]["taxonomy_ref"] is None
               and resm["record"]["taxonomy_digest"] is None)

    # ============ HIGH-4: the engine honors enabled / fast_path:off / Tier-2 ========= #
    def _cfg(**kw):
        return dict({"enabled": True, "fast_path": "ask", "min_sample_count": 5,
                     "fan_out_threshold": 1, "token_cap": None}, **kw)

    def _seed_taxonomy(repo):
        tax_dir = os.path.join(repo, ".claude")
        os.makedirs(tax_dir)
        with open(os.path.join(tax_dir, "compound-v-impact-taxonomy.yaml"), "w",
                  encoding="utf-8") as fh:
            fh.write(_EXAMPLE_TAXONOMY_TEXT)
        return os.path.join(repo, "docs", "superpowers", "memory", "triage-outcomes.jsonl")

    # (a) enabled:false → the whole stage is a no-op → FULL_PIPELINE, NO artifacts written.
    with tempfile.TemporaryDirectory() as repo:
        _seed_taxonomy(repo)
        fk = fake_localize_factory(_loc(["src/ui/button.css"], flags=[], fan_out=1))
        resd = run_preeval("tweak local button padding", repo=repo, _localize=fk,
                           config_values=_cfg(enabled=False), ts="2026-07-12T10:21:00Z")
        expect("HIGH-4(a): enabled:false -> FULL_PIPELINE (no-op)",
               resd["decision"] == DECISION_FULL and resd.get("pre_eval_disabled") is True)
        expect("HIGH-4(a): enabled:false writes NO pre-eval artifacts",
               (not os.path.isdir(pre_eval_dir(repo))) or not os.listdir(pre_eval_dir(repo)))

    # (b) fast_path:"off" → a trivial CSS change that WOULD be FASTPATH is forced FULL; the
    # score is still computed (low/low bands recorded), decision forced FULL_PIPELINE.
    with tempfile.TemporaryDirectory() as repo:
        stream = _seed_taxonomy(repo)
        fk = fake_localize_factory(_loc(["src/ui/button.css"], flags=[], fan_out=1))
        reso = run_preeval("tweak local button padding", repo=repo, _localize=fk,
                           config_values=_cfg(fast_path="off"), ts="2026-07-12T10:22:00Z",
                           stream_path=stream)
        expect("HIGH-4(b): fast_path off -> FULL_PIPELINE (never FASTPATH)",
               reso["decision"] == DECISION_FULL)
        expect("HIGH-4(b): fast_path off still COMPUTES the score (low/low bands recorded)",
               reso["record"]["difficulty"]["band"] == "low"
               and reso["record"]["impact"]["band"] == "low")
        # off ALSO short-circuits a would-be T3 call: an unclassified path never returns needs_t3.
        fk2 = fake_localize_factory(_loc(["tools/gen.py"], flags=[], fan_out=1))
        reso2 = run_preeval("do the mysterious thing", repo=repo, _localize=fk2,
                            config_values=_cfg(fast_path="off"), ts="2026-07-12T10:23:00Z",
                            stream_path=stream)
        expect("HIGH-4(b): fast_path off -> no needs_t3 model call, decides FULL",
               reso2.get("needs_t3") is False and reso2["decision"] == DECISION_FULL)

    # (c) an UNHEALTHY Tier-2 cohort (resolved BY run_preeval itself, min_sample_count=1)
    # RAISES a trivial CSS change away from the fast-path → FULL_PIPELINE, T2 signalled.
    with tempfile.TemporaryDirectory() as repo:
        stream = _seed_taxonomy(repo)
        tm = _triage_mod()
        prior = "2026-07-12T090000Z-prior-fastpath-aaaa"
        tm.append_predicted(prior, decision=DECISION_FASTPATH, stream_path=stream)
        tm.bind_run(prior, "run-prior", stream_path=stream)
        tm.append_actual(prior, "run-prior", escalated=True, review_result="fail",
                         stream_path=stream)  # terminal, ESCALATED fast-path outcome → unhealthy
        # v2.9 triage counts a terminal actual only when it is git-verified against the run's
        # COMMITTED state.json (an uncommitted/working-tree one is precision-ignored). An ESCALATED
        # fast-path parent needs a committed state.json {phase:ESCALATION_REQUIRED, escalated_to} and
        # a committed stream. So git-init the temp repo and commit both.
        _rundir = os.path.join(repo, "docs", "superpowers", "execution", "run-prior")
        os.makedirs(_rundir, exist_ok=True)
        with open(os.path.join(_rundir, "state.json"), "w", encoding="utf-8") as _sf:
            json.dump({"phase": "ESCALATION_REQUIRED", "escalated_to": "run-prior-esc-child"}, _sf)
        _env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e",
                    GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e")
        for _c in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "seed"]):
            subprocess.run(["git", "-C", repo] + _c, env=_env, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        fk = fake_localize_factory(_loc(["src/ui/button.css"], flags=[], fan_out=1))
        resu = run_preeval("tweak local button padding once more", repo=repo, _localize=fk,
                           config_values=_cfg(min_sample_count=1), ts="2026-07-12T10:24:00Z",
                           stream_path=stream)
        # (medium, low) after the raise → SCOPED under the v3.0 matrix; the property being
        # asserted is unchanged — the cohort signal took the change OUT of the DIRECT class.
        expect("HIGH-4(c): unhealthy Tier-2 cohort resolved by run_preeval RAISES out of DIRECT",
               resu["decision"] == DECISION_SCOPED
               and resu["decision"] != DECISION_FASTPATH
               and resu["record"]["difficulty"]["band"] != "low"
               and "T2" in resu["record"]["tiers_signalled"])

    # ============ B3: `_advisor_hot_for` reader — post-run, fail-open ================ #
    def _write_result(results_dir, name, obj):
        os.makedirs(results_dir, exist_ok=True)
        with open(os.path.join(results_dir, name), "w", encoding="utf-8") as fh:
            json.dump(obj, fh)

    # Missing run_dir / missing results dir → False (absence NEVER escalates).
    expect("advisor reader: run_dir=None -> False", _advisor_hot_for(".", None) is False)
    with tempfile.TemporaryDirectory() as repo:
        expect("advisor reader: absent results dir fail-opens to False",
               _advisor_hot_for(repo, "docs/superpowers/execution/run-x") is False)

    # advisor_calls OVER the threshold in any completed result → hot (True).
    with tempfile.TemporaryDirectory() as repo:
        rd = os.path.join("docs", "superpowers", "execution", "run-hot")
        results = os.path.join(repo, rd, "results")
        _write_result(results, "job1.json",
                      {"status": "success", "usage": {"advisor_calls": 1}})
        _write_result(results, "job2.json",
                      {"status": "success",
                       "usage": {"advisor_calls": ADVISOR_HOT_THRESHOLD + 1}})
        expect("advisor reader: a job over threshold -> hot (True)",
               _advisor_hot_for(repo, rd) is True)

    # AT-threshold (not over) and null/absent/non-int → NOT hot (strictly-greater gate + fail-open).
    with tempfile.TemporaryDirectory() as repo:
        rd = os.path.join("docs", "superpowers", "execution", "run-cold")
        results = os.path.join(repo, rd, "results")
        _write_result(results, "at.json",
                      {"status": "success", "usage": {"advisor_calls": ADVISOR_HOT_THRESHOLD}})
        _write_result(results, "null.json",
                      {"status": "success", "usage": {"advisor_calls": None}})
        _write_result(results, "nousage.json", {"status": "success", "summary": "no usage block"})
        _write_result(results, "bool.json",
                      {"status": "success", "usage": {"advisor_calls": True}})
        # A FAILED job that consulted the advisor OVER threshold must NOT escalate (round-2):
        _write_result(results, "failed.json",
                      {"status": "error", "usage": {"advisor_calls": ADVISOR_HOT_THRESHOLD + 9}})
        _write_result(results, "blocked.json",
                      {"status": "blocked", "usage": {"advisor_calls": ADVISOR_HOT_THRESHOLD + 9}})
        _write_result(results, "bad.json", {})
        with open(os.path.join(repo, rd, "results", "corrupt.json"), "w",
                  encoding="utf-8") as fh:
            fh.write("{ not json")
        expect("advisor reader: at-threshold/null/absent/bool/corrupt/non-success -> NOT hot",
               _advisor_hot_for(repo, rd) is False)

    # Absolute run_dir also works (dispatcher may hand an absolute path).
    with tempfile.TemporaryDirectory() as repo:
        abs_rd = os.path.join(repo, "run-abs")
        _write_result(os.path.join(abs_rd, "results"), "j.json",
                      {"status": "success",
                       "usage": {"advisor_calls": ADVISOR_HOT_THRESHOLD + 5}})
        expect("advisor reader: absolute run_dir -> hot", _advisor_hot_for(repo, abs_rd) is True)

    # ==== FIX 8: --run-dir is actually threaded into run_preeval so the POST-RUN advisor
    #      sensor FIRES (it was dead before — no CLI/kwarg path reached _advisor_hot_for). ==
    with tempfile.TemporaryDirectory() as repo:
        tax_dir = os.path.join(repo, ".claude")
        os.makedirs(tax_dir, exist_ok=True)
        with open(os.path.join(tax_dir, "compound-v-impact-taxonomy.yaml"), "w",
                  encoding="utf-8") as fh:
            fh.write(_EXAMPLE_TAXONOMY_TEXT)
        stream = os.path.join(repo, "docs", "superpowers", "memory",
                              "triage-outcomes.jsonl")
        fk_fp = fake_localize_factory(_loc(["src/ui/button.css"], flags=[], fan_out=1))

        # (a) No run_dir => advisor sensor OFF (fail-open) => trivial change stays FASTPATH
        #     (unchanged normal pre-dispatch behavior).
        res_norund = run_preeval("tweak local padding no rundir", repo=repo,
                                 _localize=fk_fp, ts="2026-07-12T11:00:00Z",
                                 stream_path=stream)
        expect("FIX8: no run_dir => advisor sensor off => FASTPATH, no override",
               res_norund["decision"] == DECISION_FASTPATH
               and res_norund["override_fired"] is None)

        # (b) A run_dir whose results record advisor_calls OVER threshold => _advisor_hot_for
        #     is consulted on the reclassification path => override #7 fires => the SAME
        #     otherwise-trivial change reclassifies to FULL_PIPELINE.
        rd = os.path.join("docs", "superpowers", "execution", "run-adv")
        _res_dir = os.path.join(repo, rd, "results")
        os.makedirs(_res_dir, exist_ok=True)
        with open(os.path.join(_res_dir, "j.json"), "w", encoding="utf-8") as fh:
            json.dump({"status": "success",
                       "usage": {"advisor_calls": ADVISOR_HOT_THRESHOLD + 1}}, fh)
        res_rund = run_preeval("tweak local padding with rundir", repo=repo,
                               _localize=fk_fp, run_dir=rd,
                               ts="2026-07-12T11:01:00Z", stream_path=stream)
        expect("FIX8: --run-dir over threshold => advisor_hot override #7 => FULL",
               res_rund["decision"] == DECISION_FULL
               and res_rund["override_fired"] == 7)

    # (c) --run-dir path containment: inside is allowed; None fail-opens; a `..` escape and
    #     an outside-repo absolute path are rejected (validated before the sensor reads).
    with tempfile.TemporaryDirectory() as repo:
        expect("FIX8: run_dir=None is contained (fail-open, nothing to validate)",
               _run_dir_contained(repo, None) is True)
        expect("FIX8: repo-relative run_dir is contained",
               _run_dir_contained(repo, "docs/superpowers/execution/run-x") is True)
        expect("FIX8: '..' escaping run_dir is rejected",
               _run_dir_contained(repo, "../evil-run") is False)
        _outside = os.path.join(os.path.dirname(os.path.realpath(repo)), "outside-run")
        expect("FIX8: outside-repo absolute run_dir is rejected",
               _run_dir_contained(repo, _outside) is False)

    # ----------------------------------------------------------------------- #
    # Phase T — `triage_request`, the ONE implementation both callers sit on.
    #
    # It used to live inside a markdown heredoc in commands/v-triage.md, where
    # nothing could reach it: the binding, the declared-path vocabulary and the six
    # predicates were all untested, and the only way to add the hook as a second
    # caller was to copy them. These cases are what makes the move real.
    # ----------------------------------------------------------------------- #
    with tempfile.TemporaryDirectory() as repo:
        os.makedirs(os.path.join(repo, ".claude"))
        with open(os.path.join(repo, ".claude", "compound-v-impact-taxonomy.yaml"),
                  "w", encoding="utf-8") as fh:
            fh.write(_EXAMPLE_TAXONOMY_TEXT
                     + "\nauto_route_allow:\n  - \"src/ui/**/*.css\"\n"
                     + "auto_route_max_lines: 20\n")
        stream = os.path.join(repo, "docs", "superpowers", "memory",
                              "triage-outcomes.jsonl")

        fk_t = fake_localize_factory(_loc(["src/ui/button.css"], flags=[], fan_out=1))
        t = triage_request("tweak local button padding", repo=repo,
                           session_id="sess-1", base_commit="cafe1234",
                           ts="2026-09-02T10:00:00Z",
                           _localize=fk_t, stream_path=stream)
        expect("TRIAGE: reports every key both callers read",
               all(k in t for k in ("pre_eval_id", "tier", "decision", "needs_t3",
                                    "record_ref", "predicates", "declared_paths")))
        expect("TRIAGE: tier is DERIVED from the decision, never re-spelled",
               t["tier"] == DECISION_TO_TIER[t["decision"]] == "DIRECT")
        expect("TRIAGE: reports the six pre-edit predicates and no more",
               [p["n"] for p in t["predicates"]] == [1, 2, 3, 4, 5, 6])
        expect("TRIAGE: an eligible CSS path is a member of the auto-route class",
               t["member"] is True)
        expect("TRIAGE: declared_paths carries the resolved path",
               t["declared_paths"] == ["src/ui/button.css"])

        # THE BINDING IS INSIDE THE DIGEST. A producer that attached session_id after
        # build_record would ship a record whose own integrity digest silently no
        # longer verifies, so assert the digest over the WRITTEN record.
        with open(os.path.join(repo, t["record_ref"]), "r", encoding="utf-8") as fh:
            written = json.load(fh)
        expect("TRIAGE: the record is bound to the session id it was given",
               written.get("session_id") == "sess-1"
               and written.get("base_commit") == "cafe1234"
               and written.get("tier") == "DIRECT")
        expect("TRIAGE: the bound record's own digest still verifies",
               _tax().record_digest(written, exclude_field="digest")
               == written["digest"])
        # A DIFFERENT request text on purpose: the same one would resume the intent
        # record above and hit write-once with different bindings, which is a real
        # conflict rather than the thing under test.
        expect("TRIAGE: an empty session id binds NULL, never an invented value",
               triage_request("nudge the button padding again", repo=repo,
                              session_id="  ", ts="2026-09-02T10:00:30Z",
                              _localize=fk_t, stream_path=stream)["session_id"] is None)

        # A sensitive path is refused by predicate 5 even though it bands FULL anyway —
        # the predicates are reported independently of the tier, which is what lets a
        # caller explain WHY something is not in the class.
        fk_auth = fake_localize_factory(_loc(
            ["src/auth/login.py", "src/auth/session.py", "src/auth/token.py"],
            flags=[], fan_out=3))
        ta = triage_request("rework the login handler", repo=repo, session_id="sess-2",
                            ts="2026-09-02T10:01:00Z", _localize=fk_auth,
                            stream_path=stream)
        expect("TRIAGE: a sensitive path is FULL and not a member",
               ta["tier"] == "FULL" and ta["member"] is False)
        expect("TRIAGE: every decided result reports a flavor, null when there is none",
               "flavor" in ta and ta["flavor"] is None)

        # v3.4.1 §A3: the SMALL sensitive edit is the SCOPED+ candidate, so triage hands
        # the caller a T3 question instead of a tier — and says which question it is.
        fk_auth1 = fake_localize_factory(_loc(["src/auth/login.py"], flags=[], fan_out=1))
        ta1 = triage_request("touch one line in the login handler", repo=repo,
                             session_id="sess-2b", ts="2026-09-02T10:01:15Z",
                             _localize=fk_auth1, stream_path=stream)
        expect("TRIAGE: a small sensitive edit asks T3, reporting reason 'sensitive'",
               ta1["needs_t3"] is True and ta1["tier"] is None
               and ta1.get("t3_reason") == "sensitive")
        ta1p = triage_request("touch one line in the login handler", repo=repo,
                              session_id="sess-2b", ts="2026-09-02T10:01:30Z",
                              t3_category="plumbing", _localize=fk_auth1,
                              stream_path=stream)
        expect("TRIAGE: re-entering with `plumbing` yields SCOPED+ end to end",
               ta1p["tier"] == "SCOPED" and ta1p["flavor"] == FLAVOR_SCOPED_PLUS
               and ta1p["override_fired"] is None)

        # AMENDMENT 2: the binding is a REAL parameter on `run_preeval`, threaded to
        # `build_record` — never a `globals()["build_record"]` patch. It is asserted two
        # ways because the patch form passed every behavioural case above: the parameter
        # must be DECLARED, and driving `run_preeval` directly with it must actually bind.
        _argnames = run_preeval.__code__.co_varnames[:run_preeval.__code__.co_argcount]
        expect("TRIAGE: run_preeval declares `binding` as a real parameter",
               "binding" in _argnames)
        fk_b = fake_localize_factory(_loc(["src/ui/panel.css"], flags=[], fan_out=1))
        rp = run_preeval("restyle the side panel", repo=repo,
                         ts="2026-09-02T10:02:00Z", _localize=fk_b, stream_path=stream,
                         binding={"session_id": "sess-4", "base_commit": "beef5678"})
        expect("TRIAGE: run_preeval(binding=…) binds the record and leaves the "
               "module global alone",
               rp["record"].get("session_id") == "sess-4"
               and rp["record"].get("base_commit") == "beef5678"
               and rp["record"].get("declared_paths") == ["src/ui/panel.css"]
               and build_record.__name__ == "build_record")

    # `pre_eval.enabled: false` — the stage is a no-op, so there is NO record, no
    # predicate, and the change is FULL by the operator's own configuration. The hook
    # reads exactly this to decide to stay silent.
    with tempfile.TemporaryDirectory() as repo:
        os.makedirs(os.path.join(repo, ".claude"))
        with open(os.path.join(repo, ".claude", "compound-v.json"), "w",
                  encoding="utf-8") as fh:
            fh.write('{"pre_eval": {"enabled": false}}\n')
        td = triage_request("anything at all", repo=repo, session_id="sess-3")
        expect("TRIAGE: pre_eval.enabled=false is a no-op that writes NO record",
               td["disabled"] is True and td["record_ref"] is None
               and td["tier"] == "FULL"
               and not os.path.isdir(os.path.join(repo, PRE_EVAL_DIR_REL)))

    expect("TRIAGE: declare_paths refuses what the Stop gate would silently drop",
           declare_paths(["ok/a.md", "/abs.md", "../up.md", "ok/a.md"])
           == (["ok/a.md"], ["/abs.md", "../up.md"]))
    expect("TRIAGE: is_test_path catches the shapes predicate 6 removes",
           all(is_test_path(p) for p in ("tests/x.py", "a/test_x.py", "a/x_test.go",
                                         "a/x.spec.ts", "a/conftest.py"))
           and not is_test_path("src/ui/button.css"))

    if failures:
        print("\nSELFTEST FAILED: %d case(s)" % len(failures))
        return 1
    print("\nSELFTEST PASSED")
    return 0


def _rejects(fn, exc):
    try:
        fn()
        return False
    except exc:
        return True
    except Exception:  # noqa: BLE001
        return False


def _schema_check(expect, record, must_validate, label=None):
    """Validate a record against pre-eval-record.schema.json when jsonschema is available."""
    try:
        import jsonschema
    except ImportError:
        expect("schema check skipped (jsonschema not installed)", True)
        return
    schema_path = os.path.join(os.path.dirname(_here()), "schemas",
                               "pre-eval-record.schema.json")
    with open(schema_path, "r", encoding="utf-8") as fh:
        schema = json.load(fh)
    name = label or ("record validates against pre-eval-record.schema.json"
                     if must_validate else "record is schema-REJECTED")
    try:
        jsonschema.validate(record, schema)
        ok = must_validate
    except jsonschema.ValidationError:
        ok = not must_validate
    expect(name, ok)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
