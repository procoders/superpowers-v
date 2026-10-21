"""The triage block (--require-triage) and the SCOPED+ cross-model receipt."""

import json
import os

from .rules import (
    VALID_TRIAGE_TIERS, TRIAGE_REQUIRED_KEYS, VALID_TRIAGE_FLAVORS, TRIAGE_ALLOWED_KEYS,
    TRIAGE_DISABLED_FLAG, PRE_EVAL_DIR_REL, DEFAULT_TAXONOMY_REL)
from .fastpath_support import (
    _CROSS_MODEL_SCHEMA, _PLAN_REVIEW_SCHEMA, _CROSS_MODEL_EXPECTED, _sibling,
    _read_json_file, _is_digest_shaped, _load_bundled_schema, _schema_lite)


# --------------------------------------------------------------------------- #
# v3.0 (Feature A2) — `triage` block validation, engaged only by --require-triage.
# --------------------------------------------------------------------------- #
def _iso8601_ok(value):
    """True iff ``value`` parses as an ISO-8601 timestamp on the Python 3.9 floor.

    3.9's ``datetime.fromisoformat`` rejects the trailing ``Z`` every producer
    writes (3.11 accepts it), so the Zulu suffix is stripped before parsing —
    otherwise the same record would validate locally and fail in CI."""
    if not isinstance(value, str) or not value.strip():
        return False
    import datetime

    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1]
    try:
        datetime.datetime.fromisoformat(text)
        return True
    except ValueError:
        return False


def _validate_triage(manifest, repo_root, taxonomy_path):
    """Return violations for the top-level ``triage`` block. Called ONLY when
    ``--require-triage`` is passed: absence, malformation, an out-of-enum tier and
    a taxonomy_digest that disagrees with the taxonomy on disk are all failures."""
    problems = []
    tri = manifest.get("triage")
    if tri in (None, "", [], {}):
        problems.append(
            "manifest missing required top-level 'triage' block (--require-triage): "
            "expected {tier, pre_eval_id, taxonomy_digest, decided_at} — run "
            "/v:triage to produce and commit the record"
        )
        return problems
    if not isinstance(tri, dict):
        problems.append("manifest 'triage' must be a mapping (got %r)" % (tri,))
        return problems

    disabled = "disabled_by_config" in tri
    for key in TRIAGE_REQUIRED_KEYS:
        if tri.get(key) in (None, "", [], {}):
            if key == "taxonomy_digest":
                if not disabled:
                    problems.append(_null_digest_message(repo_root, taxonomy_path))
                continue
            problems.append("manifest triage missing required field '%s'" % key)

    tier = tri.get("tier")
    if tier not in (None, "") and str(tier) not in VALID_TRIAGE_TIERS:
        problems.append(
            "manifest triage.tier '%s' invalid (expected one of %s — the tier is "
            "compared verbatim downstream, so case matters)"
            % (tier, ", ".join(VALID_TRIAGE_TIERS))
        )

    # `pre_eval_id` becomes a path segment (docs/superpowers/pre-eval/<id>.json).
    # It is NOT run through _ID_RE: real ids carry an ISO timestamp with colons.
    pid = tri.get("pre_eval_id")
    if pid not in (None, ""):
        pid_s = str(pid)
        if "/" in pid_s or "\\" in pid_s or pid_s in (".", ".."):
            problems.append(
                "manifest triage.pre_eval_id '%s' is not a safe path segment "
                "(no '/' or '\\', not . or ..) — the id names the committed "
                "pre-eval record" % pid_s
            )

    decided_at = tri.get("decided_at")
    if decided_at not in (None, "") and not _iso8601_ok(decided_at):
        problems.append(
            "manifest triage.decided_at '%s' is not an ISO-8601 timestamp "
            "(e.g. 2026-09-01T10:15:00Z)" % decided_at
        )

    for key in tri:
        if key not in TRIAGE_ALLOWED_KEYS:
            problems.append(
                "manifest triage has unknown key '%s' (allowed: %s)"
                % (key, ", ".join(TRIAGE_ALLOWED_KEYS))
            )

    problems.extend(_validate_triage_flavor(tri, manifest))

    if disabled:
        problems.extend(_triage_disabled_problems(tri, repo_root))
        return problems

    digest = tri.get("taxonomy_digest")
    if digest not in (None, ""):
        if not _is_digest_shaped(digest):
            problems.append(
                "manifest triage.taxonomy_digest '%s' is malformed (expected "
                "'sha256:<64-hex>')" % digest
            )
        else:
            problems.extend(
                _triage_digest_problems(digest, repo_root, taxonomy_path))
    problems.extend(_triage_record_problems(tri, repo_root))
    return problems


_DECISION_TO_TIER = {"FASTPATH_ELIGIBLE": "DIRECT", "SCOPED_PIPELINE": "SCOPED",
                     "FULL_PIPELINE": "FULL"}


def _triage_record_problems(tri, repo_root):
    """A bound record that is on disk must carry the manifest's taxonomy digest, and no
    re-triage may have superseded it — otherwise a manifest bound before a re-triage
    would dispatch on a stale size decision. An absent record is not checked here."""
    pid = str(tri.get("pre_eval_id") or "")
    if not pid or "/" in pid or "\\" in pid or pid in (".", ".."):
        return []
    root = repo_root or "."
    rel = os.path.join(PRE_EVAL_DIR_REL, pid + ".json")
    rec, _err = _read_json_file(root, rel)
    retriage = ("re-run /v:triage <the same request> and /v:orchestrate so the manifest "
                "binds the new record (compound-v-preeval.py record-status shows which)")
    problems = []
    if isinstance(rec, dict):
        want_tier = _DECISION_TO_TIER.get(rec.get("decision"))
        if want_tier and str(tri.get("tier") or "") != want_tier:
            problems.append("manifest triage.tier %r does not match the record %s (decision "
                            "%s is %s) — the tier is copied from the record, never chosen"
                            % (tri.get("tier"), rel, rec.get("decision"), want_tier))
        if rec.get("flavor") not in (None, "") and tri.get("flavor") != rec.get("flavor"):
            problems.append("manifest triage.flavor %r does not match the record %s (flavor "
                            "%r) — a SCOPED+ record's mandatory deep review and cross-model "
                            "second opinion cannot be dropped by omitting the flavor"
                            % (tri.get("flavor"), rel, rec.get("flavor")))
    if isinstance(rec, dict) and rec.get("taxonomy_digest") != tri.get("taxonomy_digest"):
        problems.append("manifest triage.taxonomy_digest does not match the record %s "
                        "(%r) — %s" % (rel, rec.get("taxonomy_digest"), retriage))
    d = os.path.join(root, PRE_EVAL_DIR_REL)
    try:
        names = sorted(os.listdir(d))
    except OSError:
        names = []
    for name in names:
        if not name.endswith(".intent.json"):
            continue
        obj, _e = _read_json_file(root, os.path.join(PRE_EVAL_DIR_REL, name))
        if isinstance(obj, dict) and obj.get("supersedes") == pid:
            problems.append("manifest triage.pre_eval_id %s was superseded by %s — %s"
                            % (pid, obj.get("pre_eval_id"), retriage))
            break
    return problems


def _is_deep_claude_review_job(job):
    """True iff ``job`` is the deep in-harness review a SCOPED+ run owes.

    Read literally, and NOT through ``_is_reviewer``: that helper answers a laxer
    question ("must this job resolve to deep/opus?") and falls back to scanning the
    id and title of a job with no ``type`` at all. A SCOPED+ manifest has to carry a
    reviewer it DECLARED, so all three fields are tested by name — a job merely
    *titled* "review the seams" does not satisfy the rule."""
    if not isinstance(job, dict):
        return False
    return (str(job.get("type", "")).strip().lower() == "review"
            and str(job.get("tier", "")).strip().lower() == "deep"
            and str(job.get("backend", "")).strip().lower() == "claude")


def _validate_triage_flavor(tri, manifest):
    """Return violations for the optional ``triage.flavor`` (v3.4.1).

    Two checks, and only under ``--require-triage`` (this is reached from
    ``_validate_triage``): the value is in the enum, and ``scoped_plus`` — the band
    that says *small edit, sensitive path* — carries the deep Claude review job that
    is the whole reason the flavor exists. The cross-model half of that promise is
    NOT checked here: it cannot be, before dispatch, because the receipt does not
    exist yet. ``--require-cross-model-receipt`` checks it afterwards."""
    problems = []
    flavor = tri.get("flavor")
    if flavor in (None, ""):
        return problems
    if str(flavor) not in VALID_TRIAGE_FLAVORS:
        problems.append(
            "manifest triage.flavor '%s' invalid (expected one of %s) — flavor is "
            "a band, not free text" % (flavor, ", ".join(VALID_TRIAGE_FLAVORS)))
        return problems

    jobs = manifest.get("jobs")
    jobs = jobs if isinstance(jobs, list) else []
    if not any(_is_deep_claude_review_job(j) for j in jobs):
        problems.append(
            "manifest triage.flavor 'scoped_plus' requires a review job with "
            "type: review, tier: deep and backend: claude — a SCOPED+ band is a "
            "small edit on a sensitive path, and it buys back the deep review the "
            "SCOPED band would otherwise skip (the cross-model second opinion is "
            "the other half, checked after the fact by "
            "--require-cross-model-receipt)")
    return problems


def _null_digest_message(repo_root, taxonomy_path=None):
    """The null/absent `taxonomy_digest` violation, worded for the two ways it happens."""
    path = taxonomy_path or os.path.join(repo_root or ".", DEFAULT_TAXONOMY_REL)
    head = ("manifest triage missing required field 'taxonomy_digest': the triage record "
            "was scored without the impact taxonomy %s, so it pins no rules and "
            "cannot be dispatched" % DEFAULT_TAXONOMY_REL)
    if os.path.isfile(path):
        why = ("; the taxonomy exists now, so the record predates it")
    else:
        why = ("; the taxonomy is missing — /v:init drafts it (or /v:onboard builds it "
               "with its draft-taxonomy step)")
    return (head + why + "; then re-run /v:triage <the same request> and copy the NEW "
            "record's pre_eval_id and taxonomy_digest into this block "
            "(`compound-v-preeval.py record-status --pre-eval-id <id>` checks a record)")


def _triage_disabled_problems(tri, repo_root):
    """Violations for a `disabled_by_config` triage block. Every condition must hold; any
    unreadable input fails closed. FULL is the most conservative tier, so accepting this
    record never widens what can be dispatched."""
    problems = []
    root = repo_root or "."
    if tri.get("disabled_by_config") is not True:
        return ["manifest triage.disabled_by_config must be true when present (got %r)"
                % (tri.get("disabled_by_config"),)]
    if str(tri.get("tier")) != "FULL":
        problems.append("manifest triage.disabled_by_config requires tier FULL (got %r) — "
                        "a stage that scored nothing cannot grant a smaller tier"
                        % (tri.get("tier"),))
    if tri.get("taxonomy_digest") not in (None, ""):
        problems.append("manifest triage.disabled_by_config requires a null "
                        "taxonomy_digest — the config-disabled record pins no taxonomy")

    cfg_mod = _sibling("compound-v-project-config.py")
    enabled_false = False
    if cfg_mod is None:
        problems.append("manifest triage.disabled_by_config is unverifiable: "
                        "compound-v-project-config.py failed to load — fail-closed")
    else:
        try:
            values, _w = cfg_mod.resolve_pre_eval(cfg_mod.load_project_config(root))
            enabled_false = values.get("enabled") is False
        except Exception as e:  # noqa: BLE001 - unreadable config fails closed
            problems.append("manifest triage.disabled_by_config is unverifiable: the "
                            "project config could not be read (%s) — fail-closed" % e)
        else:
            if not enabled_false:
                problems.append(
                    "manifest triage.disabled_by_config, but pre_eval.enabled is not false "
                    "in .claude/compound-v.json any more — the stage is on, so re-run "
                    "/v:triage <the same request> and bind the scored record")

    pid = str(tri.get("pre_eval_id") or "")
    if not pid or "/" in pid or "\\" in pid or pid in (".", ".."):
        return problems  # already reported by the caller
    rel = os.path.join(PRE_EVAL_DIR_REL, pid + ".json")
    rec, err = _read_json_file(root, rel)
    if err is not None or not isinstance(rec, dict):
        problems.append("manifest triage.disabled_by_config: the record %s could not be "
                        "read (%s) — commit the record /v:triage --record-disabled wrote"
                        % (rel, err or "not a JSON object"))
        return problems
    loc = rec.get("localization")
    flags = loc.get("flags") if isinstance(loc, dict) else None
    if not (rec.get("decision") == "FULL_PIPELINE" and rec.get("taxonomy_digest") is None
            and isinstance(flags, list) and TRIAGE_DISABLED_FLAG in flags):
        problems.append("manifest triage.disabled_by_config: %s is not a config-disabled "
                        "FULL record (decision FULL_PIPELINE, null taxonomy_digest, "
                        "localization flag %r)" % (rel, TRIAGE_DISABLED_FLAG))
    if rec.get("digest") not in (None, ""):
        tax = _sibling("compound-v-taxonomy.py")
        try:
            ok = tax is not None and tax.record_digest(rec, exclude_field="digest") \
                == rec.get("digest")
        except Exception:  # noqa: BLE001
            ok = False
        if not ok:
            problems.append("manifest triage.disabled_by_config: %s fails its own digest "
                            "— the record was edited after it was written" % rel)
    return problems


def _triage_digest_problems(digest, repo_root, taxonomy_path):
    """Compare the record's ``taxonomy_digest`` against the taxonomy bytes on disk,
    through the SHARED compound-v-taxonomy primitive so producer and consumer can
    never diverge. An unreadable or absent taxonomy FAILS CLOSED — a record whose
    rules cannot be found is exactly the case this check exists for."""
    tax = _sibling("compound-v-taxonomy.py")
    path = taxonomy_path or os.path.join(repo_root or ".", DEFAULT_TAXONOMY_REL)
    if tax is None:
        return ["manifest triage.taxonomy_digest is unverifiable: the shared "
                "taxonomy digest primitive (compound-v-taxonomy.py) failed to "
                "load — fail-closed"]
    try:
        on_disk = tax.taxonomy_digest_file(path)
    except FileNotFoundError as e:
        # ABSENCE is the common case, not the exotic one: a repo that has never
        # run /v:onboard has no `.claude/compound-v-impact-taxonomy.yaml` at
        # all, so every --require-triage dispatch fails closed here and every
        # triage bands `unknown`. That refusal is correct — a record whose
        # rules cannot be found must not verify — but naming the real producer
        # (the `draft-taxonomy` step inside /v:onboard's default pipeline, see
        # skills/compound-v/onboarding.md and scripts/compound-v-onboard.py's
        # `draft-taxonomy` subcommand) turns "a required field is missing"
        # into something actionable. This is diagnosis only: the verdict
        # (fail-closed) is identical to the generic "unreadable" case below,
        # and a taxonomy that disagrees with an on-disk digest — a different,
        # more serious case — is handled separately, further down, and never
        # gets this hint.
        return ["manifest triage.taxonomy_digest is unverifiable: taxonomy '%s' "
                "is unreadable because it does not exist (%s) — a triage record "
                "must not outlive the rules that produced it (fail-closed); /v:init "
                "drafts %s, or run /v:onboard (its draft-taxonomy step drafts and, on "
                "approval, writes it)" % (path, e, DEFAULT_TAXONOMY_REL)]
    except Exception as e:  # noqa: BLE001 - present-but-unreadable fails closed too
        return ["manifest triage.taxonomy_digest is unverifiable: taxonomy '%s' "
                "is unreadable (%s) — a triage record must not outlive the rules "
                "that produced it (fail-closed)" % (path, e)]
    if str(digest) != str(on_disk):
        return ["manifest triage.taxonomy_digest '%s' does not match the taxonomy "
                "on disk ('%s' at %s) — the record outlived the rules that "
                "produced it; re-run /v:triage" % (digest, on_disk, path)]
    return []


# --------------------------------------------------------------------------- #
# v3.4.1 — the SCOPED+ cross-model receipt, engaged only by
# --require-cross-model-receipt PATH.
#
# A SCOPED+ run owes two reviews the plain SCOPED band skips: a deep in-harness
# Claude review (checked BEFORE dispatch, by the flavor rule above, because the job
# is declared in the manifest) and an independent cross-model second opinion
# (checkable only AFTER it has run, because its evidence is a file that does not
# exist yet). This is the second gate. It refuses the receipt rather than trusting
# the dispatcher's word that the review happened.
# --------------------------------------------------------------------------- #
def _validate_cross_model_receipt(manifest, receipt_path, expected_diff_digest=None):
    """Return violations for the SCOPED+ cross-model receipt at ``receipt_path``.

    Verifies, in order: the file reads as JSON at all; the envelope is valid against
    ``schemas/cross-model-receipt.schema.json``; the nested ``review`` is valid
    against ``schemas/plan-review.schema.json``; ``run_id`` and ``pre_eval_id`` equal
    the manifest's; ``diff_digest`` is well-formed and, when the caller supplies
    ``expected_diff_digest``, equal to it; and the self-integrity ``digest``
    re-derives from the receipt's own canonical bytes.

    What it deliberately does NOT do is read the review's verdict. The cross-model
    opinion is advisory — the orchestrator arbitrates, exactly as for `/v:review-plan`
    — so `concerns` is not a violation. What is not advisory is that a real reviewer
    of a DIFFERENT family ran, on THIS run, over THIS diff, and the bindings are what
    make that unfalsifiable rather than asserted."""
    problems = []
    if receipt_path in (None, ""):
        return problems
    try:
        with open(receipt_path, "r", encoding="utf-8") as fh:
            receipt = json.load(fh)
    except Exception as e:  # noqa: BLE001 - absent/unreadable/malformed fail closed
        return ["cross-model receipt '%s' could not be read (%s) — a scoped_plus run "
                "does not merge on the promise that the second opinion happened "
                "(fail-closed)" % (receipt_path, e)]

    schema, sch_err = _load_bundled_schema(_CROSS_MODEL_SCHEMA, "cross-model receipt")
    if sch_err is not None:
        problems.append(sch_err)
    elif schema is not None:
        problems.extend(_schema_lite(receipt, schema, "cross-model receipt"))
    if not isinstance(receipt, dict):
        return problems

    # --- reviewer_backend / cross_model must agree (v3.6) ---
    # `claude-advisor` (v2.12's on-demand read-only advisor) is a legitimate
    # receipt producer beside `codex`, but it is the SAME model family as the
    # implementer — so the receipt's own `cross_model` boolean must say so
    # honestly. A mismatch either overstates a same-family opinion as
    # independent (claude-advisor + true) or understates a genuine second
    # opinion (codex + false); both are fail-closed violations, never a WARN.
    rb = receipt.get("reviewer_backend")
    cm = receipt.get("cross_model")
    if rb in _CROSS_MODEL_EXPECTED and isinstance(cm, bool):
        expected_cm = _CROSS_MODEL_EXPECTED[rb]
        if cm != expected_cm:
            problems.append(
                "cross-model receipt cross_model=%r disagrees with "
                "reviewer_backend '%s' (expected %r) — a mismatched flag "
                "misrepresents whether an independent model family actually "
                "reviewed this diff" % (cm, rb, expected_cm)
            )

    review = receipt.get("review")
    if isinstance(review, dict):
        pr_schema, pr_err = _load_bundled_schema(_PLAN_REVIEW_SCHEMA, "plan-review")
        if pr_err is not None:
            problems.append(pr_err)
        elif pr_schema is not None:
            problems.extend(
                _schema_lite(review, pr_schema, "cross-model receipt.review"))

    # --- identity binding: the manifest's run_id and triage.pre_eval_id ---
    run_id = manifest.get("run_id") if isinstance(manifest, dict) else None
    tri = manifest.get("triage") if isinstance(manifest, dict) else None
    pre_eval_id = tri.get("pre_eval_id") if isinstance(tri, dict) else None
    if str(receipt.get("run_id")) != str(run_id):
        problems.append("cross-model receipt run_id '%s' != manifest run_id '%s'"
                        % (receipt.get("run_id"), run_id))
    if pre_eval_id in (None, ""):
        problems.append("cross-model receipt cannot be bound: the manifest has no "
                        "triage.pre_eval_id to bind it to")
    elif str(receipt.get("pre_eval_id")) != str(pre_eval_id):
        problems.append("cross-model receipt pre_eval_id '%s' != manifest "
                        "triage.pre_eval_id '%s'"
                        % (receipt.get("pre_eval_id"), pre_eval_id))

    # --- the reviewed diff ---
    diff_digest = receipt.get("diff_digest")
    if not _is_digest_shaped(diff_digest):
        problems.append("cross-model receipt diff_digest '%s' is malformed "
                        "(expected 'sha256:<64-hex>')" % (diff_digest,))
    elif expected_diff_digest not in (None, ""):
        if str(diff_digest) != str(expected_diff_digest):
            problems.append(
                "cross-model receipt diff_digest '%s' != the sealed patch the "
                "caller reviewed ('%s') — the receipt is from a different diff "
                "(stale-replay, fail-closed)" % (diff_digest, expected_diff_digest))

    # --- self-digest, via the SHARED primitive the producer seals with ---
    tax = _sibling("compound-v-taxonomy.py")
    rdig = receipt.get("digest")
    if not isinstance(rdig, str) or not rdig:
        problems.append("cross-model receipt is missing its self-digest — cannot "
                        "verify integrity (fail-closed)")
    elif tax is None:
        problems.append("cross-model receipt self-digest cannot be verified — the "
                        "shared taxonomy digest primitive is unavailable "
                        "(fail-closed)")
    else:
        try:
            if tax.record_digest(receipt, exclude_field="digest") != rdig:
                problems.append("cross-model receipt self-digest mismatch — the "
                                "receipt was edited after it was sealed "
                                "(fail-closed)")
        except Exception as e:  # noqa: BLE001
            problems.append("cross-model receipt self-digest cannot be recomputed "
                            "(%s) — fail-closed" % e)
    return problems
