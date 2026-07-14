#!/usr/bin/env python3
"""
Compound V — the CORE pre-evaluation scoring engine (v2.9 Task A3).

The pre-eval stage runs FIRST, before Trigger 0 recon (spec §1). It scores a change
request on two SEPARATE axes (difficulty, impact) from tiered deterministic evidence and
— only when a change is *provably* trivial + low-impact — writes a `FASTPATH_ELIGIBLE`
verdict the harness may OFFER as a proportionate fast-path. Everything else is
`FULL_PIPELINE`. The request-level score never auto-routes (Iron-Invariant #4); it only
ever OFFERS.

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
DECISION_FULL = "FULL_PIPELINE"

# spec §2 — T3 total truth table (deterministic; every enum → BOTH axes, no low/med
# ambiguity, round-3 fix). The T3 `light`-tier classify emits exactly one of these.
T3_TABLE = {
    "plumbing": ("low", "low"),
    "user-facing-minor": ("medium", "medium"),
    "user-facing-major": ("high", "high"),
    "unknown": ("unknown", "unknown"),
}
T3_CATEGORIES = tuple(T3_TABLE.keys())

# Derived 1-10 DISPLAY (spec §2 — post-decision label, NEVER the gate). Band-midpoint.
_BAND_DISPLAY = {"low": 2, "medium": 5, "high": 8}  # unknown/None → null

# Localization flags (from A1's `_map_classify_flags`) that trigger Layer-A overrides.
_OVERRIDE3_FLAGS = frozenset(("shared_token", "is_a11y_state", "is_generated"))
# Any of these means the change semantically IS a high-blast surface → raises impact and
# so blocks Layer B (AC-8: impact is what a change IS, not only where it lives). regex_timeout
# is a FAIL-CLOSED content signal (a content pattern could not be evaluated → treat as a hit).
_IMPACT_RAISING_FLAGS = frozenset(("shared_token", "is_a11y_state", "regex_timeout"))

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
      {"needs_t3": True, "t3_prompt": str}                              # parent runs the Task
      {"decision", "override_fired", "difficulty", "impact",            # a completed verdict
       "tiers_signalled", "min_sample_status"}
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

    tiers = ["localization"] if confidence == "exact" else []
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
    sensitive = ("sensitive_path" in flags) or any(
        tax.match_path(taxonomy, p)["sensitive"] for p in resolved)
    if sensitive:
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
    t1_diff = tax.max_band(
        tax.match_path(taxonomy, p)["difficulty_band"] for p in resolved)
    t1_impact = tax.max_band(
        tax.match_path(taxonomy, p)["impact_band"] for p in resolved)
    if t1_diff is not None or t1_impact is not None:
        if "T1" not in tiers:
            tiers.append("T1")

    # Content-pattern impact (localize already ran content patterns → surfaced as flags).
    content_impact_high = _content_raises_impact(flags)
    impact_band = tax.max_band(
        [t1_impact] + (["high"] if content_impact_high else []))
    difficulty_band = t1_diff

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
            return {"needs_t3": True, "t3_prompt": prompt,
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
                        min_sample=min_sample_status)

    # ============================ Layer B — positive gate ======================== #
    # FASTPATH_ELIGIBLE ⟺ difficulty==low ∧ impact==low ∧ fan_out≤threshold ∧ exactly one
    # literal normalized path (not shared/generated/config/migration — all already caught
    # by overrides #2/#3 and content-flag impact, so at Layer B `flags` is clean).
    eligible = (
        difficulty_band == "low"
        and impact_band == "low"
        and fan_out <= int(fan_out_threshold)
        and _is_single_literal_path(resolved)
    )
    decision = DECISION_FASTPATH if eligible else DECISION_FULL
    return _verdict(decision, override=None, diff=difficulty_band, imp=impact_band,
                    tiers=tiers, min_sample=min_sample_status)


def _bands_conflict(a, b):
    """Two classified bands conflict if both are real and differ by ≥2 ranks (low↔high)."""
    tax = _tax()
    ra, rb = tax.band_rank(a), tax.band_rank(b)
    return ra > 0 and rb > 0 and abs(ra - rb) >= 2


def _verdict(decision, override, diff, imp, tiers, min_sample):
    # De-dup tiers preserving order; keep only the schema enum.
    allowed = ("T1", "T2", "T3", "churn", "localization")
    seen, ordered = set(), []
    for t in tiers:
        if t in allowed and t not in seen:
            seen.add(t)
            ordered.append(t)
    return {
        "needs_t3": False,
        "decision": decision,
        "override_fired": override,
        "difficulty": _axis(diff),
        "impact": _axis(imp),
        "tiers_signalled": ordered,
        "min_sample_status": min_sample,
    }


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
                 taxonomy_ref, taxonomy_digest, ts=None):
    """Assemble the write-once pre-eval RECORD (conforms to pre-eval-record.schema.json).
    `status: PRE_EVAL_DONE` is a RECORD field, not a state.json phase (AC-7/CR2-8)."""
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
    rec["digest"] = tax.record_digest(rec, exclude_field="digest")
    return rec


def _evidence_confidence(verdict, localization):
    """An evidence-only confidence STRING (never a gating number): signalled tiers +
    localization confidence. Anti-ruflo: no cost/token figure."""
    tiers = ",".join(verdict.get("tiers_signalled", [])) or "none"
    return "localization:%s; tiers:%s" % (localization.get("confidence"), tiers)


def write_record(repo, pre_eval_id, record):
    """Write the write-once RECORD (O_EXCL — reject overwrite, CR1-9). Returns rel path."""
    full = record_path(repo, pre_eval_id)
    _write_once_text(full, json.dumps(record, indent=2, sort_keys=True,
                                      ensure_ascii=False) + "\n")
    return _rel(repo, full)


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
                write_localization=True, stream_path=None, append_predicted=True):
    """End-to-end Phase-P run. Writes intent → (localization) → taxonomy snapshot → record,
    then appends the `predicted` triage event. NEVER runs git (the orchestrator commits).

    `_localize` is injectable for tests (a callable `(request, repo, taxonomy) -> loc dict`);
    defaults to A1's real `localize()`. On `needs_t3`, returns the payload WITHOUT writing
    the record or appending `predicted` — the parent runs the light Task and re-invokes with
    `--t3-category`. Resume: an existing intent record for the same request fingerprint reuses
    its pre_eval_id and continues from the first missing artifact.

    Config honored (fail-closed, HIGH-4): `pre_eval.enabled==false` → the whole stage is a
    no-op (no artifacts) → FULL_PIPELINE; `pre_eval.fast_path=="off"` → hard kill-switch, the
    score is still computed but the decision is forced FULL_PIPELINE (never FASTPATH_ELIGIBLE);
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

    # HIGH-4(b): fast_path == "off" is a HARD kill-switch — no fast-path offer is EVER made.
    # The bands stay computed (for the record + learning), but the DECISION is forced
    # FULL_PIPELINE. When the score would need a T3 model call, we skip it entirely: a
    # fast-path that can never be offered is not worth a model spend (spec §3, near-free).
    if fast_path_off:
        if verdict.get("needs_t3"):
            verdict = _verdict(DECISION_FULL, override=None, diff="unknown", imp="unknown",
                               tiers=verdict.get("tiers_signalled", []),
                               min_sample=verdict.get("min_sample_status", "insufficient"))
        elif verdict.get("decision") == DECISION_FASTPATH:
            verdict = dict(verdict, decision=DECISION_FULL)

    if verdict.get("needs_t3"):
        # Pause: parent runs the light Task and re-invokes. Artifacts already durable.
        return {
            "needs_t3": True,
            "pre_eval_id": pre_eval_id,
            "t3_prompt": verdict["t3_prompt"],
            "intent_ref": intent_rel,
            "localization_ref": localization_ref,
            "taxonomy_ref": taxonomy_ref,
        }

    # Phase-P step 4 (write) + 5 (append): write-once record, then predicted event.
    record = build_record(pre_eval_id, request, verdict, localization,
                          taxonomy_version, taxonomy_ref, taxonomy_digest, ts=ts)
    record_rel = write_record(repo, pre_eval_id, record)

    predicted_event = None
    if append_predicted:
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
        "override_fired": verdict["override_fired"],
        "record": record,
        "record_ref": record_rel,
        "intent_ref": intent_rel,
        "localization_ref": localization_ref,
        "taxonomy_ref": taxonomy_ref,
        "taxonomy_digest": taxonomy_digest,
        "predicted_event": predicted_event,
    }


# --------------------------------------------------------------------------- #
# CLI.
# --------------------------------------------------------------------------- #
def main(argv):
    if "--selftest" in argv[1:]:
        return _selftest()

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
    ap.add_argument("--score-only", action="store_true",
                    help="pure scoring from --localization-json, no writes")
    ap.add_argument("--localization-json", dest="localization_json",
                    help="a localization dict (for --score-only)")
    ap.add_argument("--fan-out-threshold", type=int, default=1)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv[1:])

    if args.score_only:
        if not args.localization_json:
            ap.error("--score-only requires --localization-json")
        try:
            localization = json.loads(args.localization_json)
        except ValueError as e:
            ap.error("invalid --localization-json: %s" % e)
        taxonomy, _bytes, _v = _load_taxonomy(args.repo, args.taxonomy)
        verdict = score(localization, taxonomy, t3_category=args.t3_category,
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

    # #2 sensitive path.
    v2 = score(_loc(["src/auth/login.py"], flags=["sensitive_path"]), taxonomy)
    expect("override #2: sensitive path -> FULL", v2["override_fired"] == 2)

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
    v4b = score(_loc(["db/migrations/003.ts"], flags=[]), taxonomy,
                t3_category="plumbing")
    # migrations is sensitive too → override #2 precedes #4 (cheap override wins). Assert #2.
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

    # fan_out over threshold blocks Layer B (no override — just not eligible).
    vfan = score(_loc(["src/ui/button.css"], flags=[], fan_out=3), taxonomy)
    expect("Layer-B: fan_out>threshold -> FULL (no override)",
           vfan["decision"] == DECISION_FULL and vfan["override_fired"] is None)

    # Two literal paths → not a single-path partition → FULL.
    vtwo = score(_loc(["a.css", "b.css"], flags=[], fan_out=2), taxonomy)
    expect("Layer-B: two paths -> FULL", vtwo["decision"] == DECISION_FULL)

    # A content:feature_flag hit raises impact → not low → FULL (AC-8, no override).
    vff = score(_loc(["src/config.css"], flags=["content:feature_flag"], fan_out=1),
                taxonomy)
    expect("Layer-B: content:feature_flag raises impact -> FULL",
           vff["decision"] == DECISION_FULL and vff["impact"]["band"] == "high")

    # regex_timeout is fail-closed content evidence → impact high → FULL.
    vrt = score(_loc(["src/ui/button.css"], flags=["regex_timeout"], fan_out=1), taxonomy)
    expect("fail-closed regex_timeout -> FULL", vrt["decision"] == DECISION_FULL)

    # medium-band path (.tsx) → impact medium → FULL.
    vmed = score(_loc(["src/ui/Widget.tsx"], flags=[], fan_out=1), taxonomy)
    expect("Layer-B: medium path -> FULL", vmed["decision"] == DECISION_FULL
           and vmed["impact"]["band"] == "medium")

    # ================= T3 total truth table (enum → both axes) ====================== #
    # An unclassified path (no path_pattern) + T2 insufficient → T3 fallback.
    # plumbing → low/low + single literal + fan1 → ELIGIBLE (taxonomy loaded = safety cover).
    vt_plumb = score(_loc(["tools/gen.py"], flags=[], fan_out=1), taxonomy,
                     t3_category="plumbing")
    expect("T3 plumbing (loaded taxonomy) -> low/low -> ELIGIBLE",
           vt_plumb["decision"] == DECISION_FASTPATH and "T3" in vt_plumb["tiers_signalled"])
    vt_minor = score(_loc(["tools/gen.py"], flags=[], fan_out=1), taxonomy,
                     t3_category="user-facing-minor")
    expect("T3 user-facing-minor -> medium/medium -> FULL",
           vt_minor["decision"] == DECISION_FULL and vt_minor["impact"]["band"] == "medium")
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
    expect("T2 unhealthy RAISES difficulty -> FULL",
           vt2_unhealthy["decision"] == DECISION_FULL
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
        rejected = _rejects(lambda: run_preeval(
            "make button X red", repo=repo, _localize=fk, ts="2026-07-12T10:15:00Z",
            pre_eval_id=res["pre_eval_id"], stream_path=stream), FileExistsError)
        expect("E2E: write-once record rejects overwrite", rejected)

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
        expect("HIGH-4(c): unhealthy Tier-2 cohort resolved by run_preeval RAISES -> FULL",
               resu["decision"] == DECISION_FULL
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
