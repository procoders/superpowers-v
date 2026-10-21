"""Fast-path validation: the review receipt and the fast_path block."""

import json
import os

from .globs import glob_match, _seg_is_literal
from .rules import _is_reviewer
from .fastpath_support import (
    FASTPATH_MODES, _EXEC_DIR, _RECEIPT_SUBPATH, _sibling, _read_json_file,
    _is_digest_shaped, _containment_problems, _review_resolution, _read_run_baseline,
    _recompute_diff_digest, verify_sealed_receipt)


def _validate_receipt(receipt_full, receipt_rel, manifest, fp, expected_model,
                      repo_root, manifest_bytes, sole_job_id, diff_root=None,
                      expected_attempt=None):
    """post-review: require + FULLY verify the dispatcher-written invocation
    receipt. Per CR5-6 the receipt MUST bind to and be verified against: run_id,
    pre_eval_id, the manifest digest, the immutable pre-launch baseline SHA, the
    FINAL diff digest, the reviewer backend/model (⇒ Claude Opus), attempt id,
    timestamp, and a normalized verdict of 'approved'. A stale receipt (wrong
    manifest / baseline / diff) or a non-approved-or-absent verdict fails
    closed. Every binding value is recomputed here — never trusted from the
    receipt itself.

    HIGH-1(b): when ``expected_attempt`` is supplied (the caller reads the CURRENT
    review attempt from the run's state.json), the receipt's ``attempt_id`` MUST equal
    it — a sealed attempt-1 receipt replayed when the expected next attempt is 2 fails
    closed. The check lives HERE, in the post-review caller, NOT in the shared
    ``verify_sealed_receipt`` (whose signature stays stable for triage). When
    ``expected_attempt`` is None the attempt check is skipped (back-compat), but the
    authoritative dispatcher flow ALWAYS passes it."""
    if not os.path.isfile(receipt_full):
        return ["fast_path --mode post-review requires a review receipt at '%s', "
                "none found (fail-closed)" % receipt_rel]
    try:
        with open(receipt_full, "r", encoding="utf-8") as fh:
            receipt = json.load(fh)
    except Exception as e:  # noqa: BLE001
        return ["fast_path review receipt '%s' is unreadable or not JSON (%s)"
                % (receipt_rel, e)]
    problems = []
    # --- sealed-receipt checks (schema shape + self-digest + verdict + id binding +
    #     reviewer-opus) via the SHARED entrypoint that triage also imports, so the
    #     two paths can never diverge. Repo-context bindings (expected_model,
    #     manifest digest, baseline, final diff, worktree) are added below. ---
    ok, reason = verify_sealed_receipt(
        receipt, fp.get("pre_eval_id"), manifest.get("run_id"))
    if not ok:
        problems.append(reason)
    if not isinstance(receipt, dict):
        return problems
    tax = _sibling("compound-v-taxonomy.py")
    rmodel = receipt.get("reviewer_model")
    if (expected_model is not None and rmodel is not None
            and str(rmodel) != str(expected_model)):
        problems.append("review receipt reviewer_model '%s' does not name the "
                        "resolved review model '%s'" % (rmodel, expected_model))

    # (verdict + reviewer-opus + self-digest are verified in verify_sealed_receipt.)

    # --- HIGH-1(b): attempt binding. The authoritative flow passes the CURRENT review
    #     attempt (from state.json); the receipt's attempt_id must equal it so a stale
    #     prior-attempt receipt cannot be replayed against a newer attempt. Compared as
    #     strings because the schema permits attempt_id to be string OR integer. ---
    if expected_attempt is not None:
        r_att = receipt.get("attempt_id")
        if str(r_att) != str(expected_attempt):
            problems.append("review receipt attempt_id %r != the expected review "
                            "attempt %r (from state.json) — a stale prior-attempt "
                            "receipt cannot be replayed against a newer attempt "
                            "(fail-closed, HIGH-1)" % (r_att, expected_attempt))

    # --- manifest_digest: REQUIRED + recomputed over the manifest under review ---
    r_mdig = receipt.get("manifest_digest")
    if not isinstance(r_mdig, str) or not r_mdig:
        problems.append("review receipt is missing manifest_digest — cannot bind "
                        "the receipt to the reviewed contract (fail-closed, CR5-6)")
    elif tax is None or manifest_bytes is None:
        problems.append("review receipt manifest_digest cannot be verified "
                        "(manifest bytes or digest primitive unavailable) — "
                        "fail-closed")
    else:
        want_mdig = tax.taxonomy_digest_bytes(manifest_bytes)
        if r_mdig != want_mdig:
            problems.append("review receipt manifest_digest '%s' != the manifest "
                            "under validation '%s' — stale or wrong-manifest "
                            "receipt (fail-closed, CR5-6)" % (r_mdig, want_mdig))

    # --- baseline_sha + final_diff_digest: bound to the run's IMMUTABLE
    #     baseline (state.json), and the diff recomputed against it ---
    baseline, berr = _read_run_baseline(
        repo_root, manifest.get("run_id"), sole_job_id)
    r_base = receipt.get("baseline_sha")
    if not isinstance(r_base, str) or not r_base:
        problems.append("review receipt is missing baseline_sha (fail-closed, "
                        "CR5-6)")
    if baseline is None:
        problems.append("cannot read the run's immutable pre-launch baseline to "
                        "verify the receipt (%s) — fail-closed" % berr)
    elif isinstance(r_base, str) and r_base and str(r_base) != str(baseline):
        problems.append("review receipt baseline_sha '%s' != the run's immutable "
                        "baseline '%s' — receipt bound to a different baseline "
                        "(fail-closed, CR5-6)" % (r_base, baseline))

    # --- MED-6: the receipt's OWN worktree binding MUST name the SAME checkout the
    #     validator recomputes the final diff in (``diff_root``, falling back to
    #     ``repo_root``). The prior code recomputed in that root but never checked
    #     the receipt's declared ``worktree`` against it, so a receipt sealed against
    #     a DIFFERENT checkout — whose diff hashes differently — was never caught by
    #     this binding. Compared as normalized realpaths (symlinks/`.`/`..` resolved);
    #     a relative worktree is anchored to ``repo_root``. The recompute below still
    #     runs against the trusted CLI root regardless, so a mismatch is an ADDED
    #     violation, never a way to skip the diff check. ---
    eff_diff_root = diff_root or repo_root
    r_wt = receipt.get("worktree")
    if not isinstance(r_wt, str) or not r_wt.strip():
        problems.append("review receipt is missing its 'worktree' binding — the "
                        "diff-root the producer hashed final_diff_digest against is "
                        "unrecorded, so the receipt cannot be tied to the checkout "
                        "under verification (fail-closed, MED-6)")
    elif eff_diff_root is None:
        problems.append("review receipt 'worktree' binding cannot be verified — no "
                        "diff-root is available to compare it against (fail-closed, "
                        "MED-6)")
    else:
        wt_abs = r_wt if os.path.isabs(r_wt) else os.path.join(repo_root, r_wt)
        if os.path.realpath(wt_abs) != os.path.realpath(eff_diff_root):
            problems.append("review receipt 'worktree' '%s' does not resolve to the "
                            "diff-root the final diff is recomputed in ('%s') — the "
                            "receipt was sealed against a different checkout "
                            "(fail-closed, MED-6)" % (r_wt, eff_diff_root))

    r_ddig = receipt.get("final_diff_digest")
    if not isinstance(r_ddig, str) or not r_ddig:
        problems.append("review receipt is missing final_diff_digest (fail-closed, "
                        "CR5-6)")
    elif baseline is not None:
        # CRIT-1: recompute in the SAME checkout the producer hashed (the worker's
        # linked worktree), falling back to repo_root only when no diff_root was
        # supplied. An unavailable worktree makes the git diff fail → fail-closed.
        cur_ddig, derr = _recompute_diff_digest(
            eff_diff_root, str(baseline), tax)
        if cur_ddig is None:
            problems.append("cannot recompute the final diff against baseline '%s' "
                            "(%s) — fail-closed" % (baseline, derr))
        elif cur_ddig != r_ddig:
            problems.append("review receipt final_diff_digest '%s' != the current "
                            "diff '%s' — stale-receipt replay against a changed "
                            "diff (fail-closed, CR5-6)" % (r_ddig, cur_ddig))

    return problems


def _validate_fast_path(manifest, fp, mode, repo_root, config_path, receipt_path,
                        manifest_bytes=None, diff_root=None, expected_attempt=None):
    """All v2.9 conditional fast-path invariants (gated on fast_path.eligible).
    Returns a list of violation strings."""
    problems = []
    if repo_root is None:
        repo_root = os.getcwd()
    if not isinstance(fp, dict):
        return ["fast_path block must be a mapping"]
    if fp.get("eligible") is not True:
        problems.append("fast_path.eligible must be true (a fast_path block with "
                        "eligible not-true is rejected)")

    # Mode is mandatory + fail-closed for a fast_path manifest.
    if mode is None:
        problems.append("fast_path manifest requires an explicit --mode "
                        "(pre-dispatch|post-review); no-mode is fail-closed")
    elif mode not in FASTPATH_MODES:
        problems.append("fast_path --mode '%s' invalid (expected one of %s)"
                        % (mode, ", ".join(FASTPATH_MODES)))

    # Exactly ONE implementer job; the review is a dispatcher PHASE, not a job.
    jobs = manifest.get("jobs") if isinstance(manifest.get("jobs"), list) else []
    if len(jobs) != 1:
        problems.append(
            "fast_path manifest must have exactly ONE implementer job (found %d); "
            "the combined SPEC+QUALITY review is a dispatcher phase "
            "(fast_path.review), not a jobs entry" % len(jobs))
    job0 = jobs[0] if jobs and isinstance(jobs[0], dict) else None
    if job0 is not None and _is_reviewer(job0):
        problems.append("fast_path manifest's sole job '%s' is a reviewer — the "
                        "review must be the fast_path.review phase, not a jobs "
                        "entry" % job0.get("id"))

    # Sole write_allowed literal.
    write_literal = None
    if job0 is not None:
        wa = job0.get("write_allowed")
        if not isinstance(wa, list) or len(wa) != 1:
            problems.append("fast_path job '%s' write_allowed must be exactly ONE "
                            "literal path" % job0.get("id"))
        else:
            cand = str(wa[0])
            if not _seg_is_literal(cand):
                problems.append("fast_path write_allowed '%s' must be a single "
                                "LITERAL normalized path (no glob metachar *?[)"
                                % cand)
            else:
                write_literal = cand
                if os.path.normpath(cand) != cand:
                    problems.append("fast_path write_allowed '%s' is not "
                                    "normalized (expected '%s')"
                                    % (cand, os.path.normpath(cand)))

    # Sentinel audits: block-YAML skip-records only (flow-{} rejected).
    audits = manifest.get("audits")
    if isinstance(audits, dict):
        for k, v in audits.items():
            if isinstance(v, str) and v.strip().startswith("{"):
                problems.append("fast_path audit '%s' is a flow-style mapping — "
                                "use a block YAML skip-record (the stdlib fallback "
                                "parser mis-parses flow {})" % k)
            elif not isinstance(v, dict):
                problems.append("fast_path audit '%s' must be a block YAML "
                                "skip-record {skipped, reason, localization, "
                                "taxonomy_version}" % k)
            elif not v:
                problems.append("fast_path audit '%s' is an empty mapping — use a "
                                "block YAML skip-record {skipped, reason, "
                                "localization, taxonomy_version}" % k)
            else:
                if v.get("skipped") is not True:
                    problems.append("fast_path audit '%s' skip-record must set "
                                    "skipped: true" % k)
                for f in ("reason", "localization", "taxonomy_version"):
                    if v.get(f) in (None, ""):
                        problems.append("fast_path audit '%s' skip-record missing "
                                        "'%s'" % (k, f))

    # Containment (CR4-6): the write literal + every *_ref.
    pre_ref = fp.get("pre_eval_ref")
    loc_ref = fp.get("localization_ref")
    tax_ref = fp.get("taxonomy_ref")
    if write_literal is not None:
        problems.extend(_containment_problems(
            "fast_path write target", write_literal, repo_root, must_exist=True))
    for label, ref in (("fast_path.pre_eval_ref", pre_ref),
                       ("fast_path.localization_ref", loc_ref),
                       ("fast_path.taxonomy_ref", tax_ref)):
        if ref in (None, ""):
            problems.append("%s is required on a fast_path manifest" % label)
        else:
            problems.extend(_containment_problems(
                label, str(ref), repo_root, must_exist=True,
                require_committed=True))

    # Cross-artifact binding (AC-13 / CR2-3).
    tax = _sibling("compound-v-taxonomy.py")
    rec = art = None
    if pre_ref:
        rec, err = _read_json_file(repo_root, str(pre_ref))
        if rec is None:
            problems.append("fast_path pinned pre-eval record '%s' unreadable "
                            "(%s) — fail-closed" % (pre_ref, err))
    if loc_ref:
        art, err = _read_json_file(repo_root, str(loc_ref))
        if art is None:
            problems.append("fast_path localization artifact '%s' unreadable "
                            "(%s) — fail-closed" % (loc_ref, err))

    def _rp0(obj):
        if isinstance(obj, dict):
            rp = obj.get("resolved_paths")
            if isinstance(rp, list) and rp:
                return str(rp[0])
        return None

    art_rp0 = _rp0(art)
    rec_loc = rec.get("localization") if isinstance(rec, dict) else None
    rec_rp0 = _rp0(rec_loc)
    if write_literal is not None and art_rp0 is not None and write_literal != art_rp0:
        problems.append("fast_path binding: sole write_allowed '%s' != "
                        "localization.resolved_paths[0] '%s' (AC-13)"
                        % (write_literal, art_rp0))
    if art_rp0 is not None and rec_rp0 is not None and art_rp0 != rec_rp0:
        problems.append("fast_path binding: localization resolved_paths[0] differs "
                        "between artifact '%s' and record '%s'"
                        % (art_rp0, rec_rp0))
    if isinstance(rec, dict) and str(fp.get("pre_eval_id")) != str(rec.get("pre_eval_id")):
        problems.append("fast_path binding: manifest pre_eval_id '%s' != record "
                        "pre_eval_id '%s' (AC-13)"
                        % (fp.get("pre_eval_id"), rec.get("pre_eval_id")))
    if isinstance(rec, dict) and str(rec.get("decision")) != "FASTPATH_ELIGIBLE":
        problems.append("fast_path binding: pinned record decision '%s' is not "
                        "FASTPATH_ELIGIBLE (AC-13)" % rec.get("decision"))

    # CRIT-2: the pinned pre-eval record must (a) carry a VALID self-digest and
    # (b) fully satisfy the FASTPATH_ELIGIBLE contract — a null Layer-A override
    # and BOTH axes at band 'low' (not merely "not high"). A tampered record (any
    # digest mismatch, a fired override, or a non-low band) MUST fail closed, so a
    # FULL_PIPELINE record with `decision` flipped to FASTPATH_ELIGIBLE and a
    # medium band cannot be replayed as fast-path eligible (CR5-6/CR5-7).
    if isinstance(rec, dict):
        # (a) self-digest — REQUIRED + verified with the SHARED primitive the
        #     producer used (compound-v-taxonomy.record_digest).
        rec_dig = rec.get("digest")
        if not isinstance(rec_dig, str) or not rec_dig:
            problems.append("fast_path binding: pinned pre-eval record '%s' is "
                            "missing its self-digest — cannot verify integrity "
                            "(fail-closed, CR5-6)" % pre_ref)
        elif tax is None:
            problems.append("fast_path binding: shared taxonomy digest primitive "
                            "unavailable — cannot verify pre-eval record "
                            "self-digest (fail-closed)")
        else:
            try:
                if tax.record_digest(rec, exclude_field="digest") != rec_dig:
                    problems.append("fast_path binding: pinned pre-eval record "
                                    "'%s' self-digest mismatch — the record was "
                                    "tampered (fail-closed, CR5-6)" % pre_ref)
            except Exception as e:  # noqa: BLE001
                problems.append("fast_path binding: cannot recompute pre-eval "
                                "record self-digest (%s) — fail-closed" % e)
        # (b) FASTPATH_ELIGIBLE contract: a fired override forces FULL_PIPELINE.
        if rec.get("override_fired") is not None:
            problems.append("fast_path binding: pinned record override_fired=%r is "
                            "set — a fired Layer-A override forces FULL_PIPELINE, "
                            "not fast-path (fail-closed, CR5-6)"
                            % rec.get("override_fired"))
        # (b) BOTH difficulty + impact must be band 'low' (Iron-Invariant #2).
        for axis in ("difficulty", "impact"):
            ax = rec.get(axis)
            band = ax.get("band") if isinstance(ax, dict) else None
            if band != "low":
                problems.append("fast_path binding: pinned record %s.band '%s' is "
                                "not 'low' — only a low/low request is fast-path "
                                "eligible (fail-closed, CR5-6)" % (axis, band))

    m_taxd = fp.get("taxonomy_digest")
    if isinstance(rec, dict) and str(m_taxd) != str(rec.get("taxonomy_digest")):
        problems.append("fast_path binding: manifest taxonomy_digest '%s' != "
                        "record taxonomy_digest '%s' (AC-13)"
                        % (m_taxd, rec.get("taxonomy_digest")))
    if tax is not None and isinstance(rec_loc, dict) and isinstance(art, dict):
        try:
            d_rec = tax.record_digest(rec_loc, exclude_field="digest")
            d_art = tax.record_digest(art, exclude_field="digest")
            if d_rec != d_art:
                problems.append("fast_path binding: localization content-digest "
                                "differs between record and artifact (AC-13)")
            # MED-8: the localization content-digest (the artifact's self-digest)
            # MUST be present AND well-shaped before it can be compared — a missing
            # or non-'sha256:<hex>' digest previously slipped through silently.
            art_dig = art.get("digest")
            if not _is_digest_shaped(art_dig):
                problems.append("fast_path binding: localization artifact "
                                "content-digest is missing or malformed "
                                "(expected 'sha256:<64-hex>') — absence/wrong-shape "
                                "fails closed (AC-13)")
            elif art_dig != d_art:
                problems.append("fast_path binding: localization artifact "
                                "self-digest mismatch")
        except Exception as e:  # noqa: BLE001
            problems.append("fast_path binding: cannot compute localization "
                            "content-digest (%s) — fail-closed" % e)

    # Taxonomy classification denylist against the PINNED snapshot.
    if tax is not None and tax_ref:
        tax_full = os.path.join(repo_root, str(tax_ref))
        try:
            snap_digest = tax.taxonomy_digest_file(tax_full)
            if m_taxd is not None and str(m_taxd) != str(snap_digest):
                problems.append("fast_path binding: manifest taxonomy_digest '%s' "
                                "!= snapshot content-address '%s' (AC-13)"
                                % (m_taxd, snap_digest))
        except Exception:  # noqa: BLE001 - containment already reports absence
            pass
        loaded = None
        try:
            loaded = tax.load_taxonomy(path=tax_full)
        except Exception as e:  # noqa: BLE001
            problems.append("fast_path taxonomy snapshot '%s' unreadable/malformed "
                            "(%s) — fail-closed" % (tax_ref, e))
        if loaded is not None and write_literal is not None and _seg_is_literal(write_literal):
            cls = tax.classify(loaded, path=write_literal)
            if cls.get("sensitive"):
                problems.append("fast_path write target '%s' is a sensitive path "
                                "per the pinned taxonomy — not fast-path eligible"
                                % write_literal)
            if str(cls.get("impact_band")) == "high":
                problems.append("fast_path write target '%s' classifies as "
                                "high-impact per the pinned taxonomy — not "
                                "fast-path eligible" % write_literal)
            churn = loaded.get("churn") or {}
            for g in churn.get("exclude_paths", []):
                if glob_match(write_literal, str(g)):
                    problems.append("fast_path write target '%s' is a "
                                    "generated/vendored path (churn exclude '%s') "
                                    "— not fast-path eligible" % (write_literal, g))
                    break

    # Mode-specific: review declaration + receipt handling.
    stance = manifest.get("routing_stance") or "balanced"
    run_id = manifest.get("run_id")
    receipt_full = receipt_path or os.path.join(
        repo_root, _EXEC_DIR, str(run_id), _RECEIPT_SUBPATH)
    if receipt_path is None:
        try:
            receipt_rel = os.path.relpath(receipt_full, repo_root)
        except Exception:  # noqa: BLE001
            receipt_rel = receipt_full
    else:
        receipt_rel = receipt_path

    if mode == "pre-dispatch":
        decl_problems, _ = _review_resolution(fp.get("review"), stance, repo_root, config_path)
        problems.extend(decl_problems)
        if os.path.lexists(receipt_full):
            problems.append("fast_path --mode pre-dispatch forbids a review "
                            "receipt, but one exists at '%s' (it cannot exist "
                            "before review)" % receipt_rel)
    elif mode == "post-review":
        decl_problems, resolved_model = _review_resolution(
            fp.get("review"), stance, repo_root, config_path)
        problems.extend(decl_problems)
        sole_job_id = job0.get("id") if isinstance(job0, dict) else None
        problems.extend(_validate_receipt(
            receipt_full, receipt_rel, manifest, fp, resolved_model,
            repo_root, manifest_bytes, sole_job_id, diff_root=diff_root,
            expected_attempt=expected_attempt))

    return problems
