"""The v2.9 fast-path selftest suite, on on-disk fixtures."""

import json
import os

from . import _SCRIPTS_DIR
from . import fastpath_support as _fastpath_support
from .yamlload import _mini_yaml
from .fastpath_support import (
    _RECEIPT_SCHEMA, _GIT_UNAVAILABLE, _sibling, _is_committed_at_head,
    _containment_problems)
from .core import validate_text


# --------------------------------------------------------------------------- #
# v2.9 fast-path self-test — builds on-disk fixtures in a temp repo root so the
# containment + cross-artifact-binding checks exercise real files. Digests are
# computed via the SHARED compound-v-taxonomy primitives (record_digest /
# taxonomy_digest_bytes) so a producer (M1) and this consumer can never diverge.
# --------------------------------------------------------------------------- #
def _fp_taxonomy_bytes():
    """The example taxonomy shipped with the plugin (a valid snapshot to test
    classification against)."""
    here = _SCRIPTS_DIR
    example = os.path.join(os.path.dirname(here),
                           ".claude", "compound-v-impact-taxonomy.example.yaml")
    with open(example, "rb") as fh:
        return fh.read()


def _fp_write(root, rel, data):
    full = os.path.join(root, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    mode = "wb" if isinstance(data, bytes) else "w"
    kw = {} if isinstance(data, bytes) else {"encoding": "utf-8"}
    with open(full, mode, **kw) as fh:
        fh.write(data)
    return full


def _fp_build(root, tax_mod, **opts):
    """Materialize a fast-path fixture under ``root``; return the manifest text.

    Knobs (all default to the VALID shape): write_path, resolved_path,
    record_decision, manifest_tax_digest, record_tax_digest, artifact_fan_out,
    manifest_pre_eval_id, review (dict), audits_flow, second_job, glob_write,
    symlink_write, loc_ref, tax_ref, pre_ref, make_receipt (dict|None),
    receipt_rel, artifact_drop_digest (MED-8), artifact_bad_shape_digest (MED-8).
    """
    pre_eval_id = "2026-07-12T101500Z-make-button-red-a1b2"
    run_id = pre_eval_id
    write_path = opts.get("write_path", "src/components/button.css")
    resolved_path = opts.get("resolved_path", write_path)

    pre_ref = opts.get("pre_ref",
                       "docs/superpowers/pre-eval/%s.json" % pre_eval_id)
    loc_ref = opts.get("loc_ref",
                       "docs/superpowers/pre-eval/%s.localization.json" % pre_eval_id)
    tax_ref = opts.get(
        "tax_ref",
        "docs/superpowers/execution/%s/taxonomy-snapshot.yaml" % run_id)

    # Immutable taxonomy snapshot + its content-address digest (RAW bytes).
    tax_bytes = _fp_taxonomy_bytes()
    _fp_write(root, tax_ref, tax_bytes)
    real_tax_digest = tax_mod.taxonomy_digest_bytes(tax_bytes)
    manifest_tax_digest = opts.get("manifest_tax_digest", real_tax_digest)
    record_tax_digest = opts.get("record_tax_digest", real_tax_digest)

    # Localization object (embedded in the record) + standalone artifact w/ digest.
    localization = {
        "resolved_paths": [resolved_path],
        "fan_out": 1,
        "flags": [],
        "confidence": "exact",
    }
    artifact = dict(localization)
    artifact["fan_out"] = opts.get("artifact_fan_out", 1)
    artifact["digest"] = tax_mod.record_digest(artifact)
    if opts.get("artifact_drop_digest"):
        artifact.pop("digest", None)              # MED-8: absent content-digest
    elif opts.get("artifact_bad_shape_digest"):
        artifact["digest"] = "not-a-valid-digest"  # MED-8: wrong-shape digest
    _fp_write(root, loc_ref, json.dumps(artifact))

    record = {
        "pre_eval_id": pre_eval_id,
        "request_slug": "make-button-red",
        "ts": "2026-07-12T10:15:00Z",
        "status": "PRE_EVAL_DONE",
        "taxonomy_version": 1,
        "taxonomy_ref": tax_ref,
        "taxonomy_digest": record_tax_digest,
        "difficulty": {"band": opts.get("record_difficulty_band", "low")},
        "impact": {"band": opts.get("record_impact_band", "low")},
        "tiers_signalled": ["localization"],
        "localization": localization,
        "override_fired": opts.get("record_override_fired", None),
        "decision": opts.get("record_decision", "FASTPATH_ELIGIBLE"),
        "min_sample_status": "insufficient",
    }
    # A genuine record carries its own canonical-JSON self-digest (the producer
    # sets it via record_digest); a fast-path consumer verifies it (CR5-6/CR5-7).
    record["digest"] = tax_mod.record_digest(record, exclude_field="digest")
    if opts.get("record_bad_digest"):
        record["digest"] = "sha256:" + ("0" * 64)  # tamper: valid shape, wrong value
    elif opts.get("record_drop_digest"):
        record.pop("digest", None)
    _fp_write(root, pre_ref, json.dumps(record))

    # The write target: a real committed-looking regular file (or an escaping
    # symlink for the containment tamper case).
    if opts.get("symlink_write"):
        outside = os.path.join(root, "..", "outside-secret.css")
        with open(os.path.join(root, "outside-secret.css"), "w") as fh:
            fh.write("body{}\n")  # a sibling target the symlink escapes to
        link_full = os.path.join(root, write_path)
        os.makedirs(os.path.dirname(link_full), exist_ok=True)
        os.symlink(os.path.abspath(os.path.join(root, "outside-secret.css")),
                   link_full)
    elif not opts.get("skip_write_file"):
        _fp_write(root, write_path, "body{}\n")

    if opts.get("make_receipt") is not None:
        receipt_rel = opts.get(
            "receipt_rel",
            "docs/superpowers/execution/%s/review/receipt.json" % run_id)
        _fp_write(root, receipt_rel, json.dumps(opts["make_receipt"]))

    manifest_pre_eval_id = opts.get("manifest_pre_eval_id", pre_eval_id)
    review = opts.get("review", {"backend": "claude", "tier": "deep"})
    review_lines = "\n".join(
        "    %s: %s" % (k, v) for k, v in review.items())

    if opts.get("audits_flow"):
        audits_block = (
            "audits:\n"
            "  archaeology: {}\n"
            "  domain: {}\n"
            "  library: {}\n"
        )
    else:
        skip = ("    skipped: true\n"
                "    reason: fastpath\n"
                "    localization: %s\n"
                "    taxonomy_version: 1\n") % loc_ref
        audits_block = (
            "audits:\n"
            "  archaeology:\n" + skip +
            "  domain:\n" + skip +
            "  library:\n" + skip
        )

    write_glob = "src/**" if opts.get("glob_write") else write_path
    second = ""
    if opts.get("second_job"):
        second = (
            "  - id: task-2-extra\n"
            "    title: \"extra\"\n"
            "    type: docs\n"
            "    backend: claude\n"
            "    tier: standard\n"
            "    isolation: direct\n"
            "    run: serial\n"
            "    write_allowed: [docs/extra.md]\n"
            "    read_allowed: [src/**]\n"
            "    acceptance: [\"x\"]\n"
        )

    text = (
        "run_id: %s\n"
        "feature: \"make button red\"\n"
        "spec_path: docs/superpowers/execution/%s/spec-stub.md\n"
        "plan_path: docs/superpowers/execution/%s/plan-stub.md\n"
        "%s"
        "routing_stance: balanced\n"
        "max_parallel: 1\n"
        "acceptance_criteria:\n"
        "  - \"button is red\"\n"
        "fast_path:\n"
        "  eligible: true\n"
        "  pre_eval_id: %s\n"
        "  pre_eval_ref: %s\n"
        "  localization_ref: %s\n"
        "  taxonomy_ref: %s\n"
        "  taxonomy_digest: \"%s\"\n"
        "  review:\n"
        "%s\n"
        "jobs:\n"
        "  - id: task-1-button\n"
        "    title: \"make button red\"\n"
        "    type: bounded_crud\n"
        "    backend: claude\n"
        "    tier: standard\n"
        "    isolation: direct\n"
        "    run: serial\n"
        "    write_allowed: [%s]\n"
        "    read_allowed: [src/**]\n"
        "    acceptance: [\"button red\"]\n"
        "%s"
    ) % (run_id, run_id, run_id, audits_block, manifest_pre_eval_id, pre_ref,
         loc_ref, tax_ref, manifest_tax_digest, review_lines, write_glob, second)
    return text


def _fp_receipt(**over):
    r = {
        "run_id": "2026-07-12T101500Z-make-button-red-a1b2",
        "pre_eval_id": "2026-07-12T101500Z-make-button-red-a1b2",
        "manifest_digest": "sha256:" + ("a" * 64),
        "baseline_sha": "a" * 40,
        "final_diff_digest": "sha256:" + ("b" * 64),
        "reviewer_backend": "claude",
        "reviewer_model": "opus",
        "attempt_id": 1,
        "ts": "2026-07-12T10:20:00Z",
        "verdict": "approved",
        "integration_rationale": "single-job fast-path: no cross-job seams",
    }
    r.update(over)
    return r


_FP_RUN_ID = "2026-07-12T101500Z-make-button-red-a1b2"
_FP_JOB_ID = "task-1-button"
_FP_WRITE_PATH = "src/components/button.css"


def _fp_git_and_state(d, tax_mod, manifest_text):
    """Turn the fixture dir into a real git repo with a committed pre-launch
    baseline + one worker change, and write the run's state.json baseline — so
    the post-review receipt binding (manifest_digest / baseline_sha /
    final_diff_digest, CR5-6) can be recomputed against real git state. Returns
    the correct binding values (or None when git is unavailable)."""
    import subprocess

    def g(*a):
        return subprocess.run(["git", "-C", d] + list(a),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if g("init", "-q").returncode != 0:
        return None
    g("config", "user.email", "selftest@example.com")
    g("config", "user.name", "cv-selftest")
    g("config", "commit.gpgsign", "false")
    g("config", "core.hooksPath", "/dev/null")  # ignore any global hooks in CI
    g("add", "-A")
    if g("commit", "-q", "--no-verify", "-m", "baseline").returncode != 0:
        return None
    rp = g("rev-parse", "HEAD")
    if rp.returncode != 0:
        return None
    baseline = rp.stdout.decode("utf-8", "replace").strip()

    # One worker change to the sole write target → a non-empty tracked diff.
    with open(os.path.join(d, _FP_WRITE_PATH), "a", encoding="utf-8") as fh:
        fh.write("/* changed by worker */\n")
    diff = g("diff", "--no-color", baseline)
    if diff.returncode != 0:
        return None
    diff_bytes = diff.stdout or b""

    state = {"run_id": _FP_RUN_ID,
             "jobs": {_FP_JOB_ID: {"status": "success", "baseline": baseline}}}
    _fp_write(d, "docs/superpowers/execution/%s/state.json" % _FP_RUN_ID,
              json.dumps(state))
    return {
        "run_id": _FP_RUN_ID,
        "manifest_digest": tax_mod.taxonomy_digest_bytes(
            manifest_text.encode("utf-8")),
        "baseline_sha": baseline,
        "final_diff_digest": tax_mod.taxonomy_digest_bytes(diff_bytes),
        "receipt_rel": "docs/superpowers/execution/%s/review/receipt.json"
                       % _FP_RUN_ID,
    }


def _fp_git_worktree_and_state(d, tax_mod, manifest_text):
    """CRIT-1 topology: a MAIN repo (``repo_root``) holding the committed artifacts
    + state.json, and a SEPARATE linked WORKTREE (``diff_root``) holding the
    worker's file change. The producer hashes the final diff in the worktree, so
    the validator must recompute there — NOT in the main checkout. Returns
    (info, worktree_path) or (None, None) when git/worktree is unavailable."""
    import subprocess

    def g(cwd, *a):
        return subprocess.run(["git", "-C", cwd] + list(a),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if g(d, "init", "-q").returncode != 0:
        return None, None
    g(d, "config", "user.email", "selftest@example.com")
    g(d, "config", "user.name", "cv-selftest")
    g(d, "config", "commit.gpgsign", "false")
    g(d, "config", "core.hooksPath", "/dev/null")
    g(d, "add", "-A")
    if g(d, "commit", "-q", "--no-verify", "-m", "baseline").returncode != 0:
        return None, None
    rp = g(d, "rev-parse", "HEAD")
    if rp.returncode != 0:
        return None, None
    baseline = rp.stdout.decode("utf-8", "replace").strip()

    wt = d + "-wt"
    if g(d, "worktree", "add", "-q", "--detach", wt, baseline).returncode != 0:
        return None, None
    # The worker change lives ONLY in the linked worktree (the main tree is clean).
    with open(os.path.join(wt, _FP_WRITE_PATH), "a", encoding="utf-8") as fh:
        fh.write("/* changed by the worker in the linked worktree */\n")
    diff = g(wt, "diff", "--no-color", baseline)
    if diff.returncode != 0:
        return None, None
    diff_bytes = diff.stdout or b""

    state = {"run_id": _FP_RUN_ID,
             "jobs": {_FP_JOB_ID: {"status": "success", "baseline": baseline}}}
    _fp_write(d, "docs/superpowers/execution/%s/state.json" % _FP_RUN_ID,
              json.dumps(state))
    return ({
        "run_id": _FP_RUN_ID,
        "manifest_digest": tax_mod.taxonomy_digest_bytes(
            manifest_text.encode("utf-8")),
        "baseline_sha": baseline,
        "final_diff_digest": tax_mod.taxonomy_digest_bytes(diff_bytes),
        "receipt_rel": "docs/superpowers/execution/%s/review/receipt.json"
                       % _FP_RUN_ID,
    }, wt)


def _fp_write_receipt(d, tax_mod, info, drop=None, bad_digest=False, **over):
    """Write a post-review receipt bound to the real git state in ``info``.
    ``over`` mutates a field (the self-digest is recomputed AFTER, so exactly the
    overridden binding fails); ``bad_digest`` breaks the self-digest; ``drop``
    removes fields entirely."""
    receipt = {
        "run_id": _FP_RUN_ID,
        "pre_eval_id": _FP_RUN_ID,
        "manifest_digest": info["manifest_digest"],
        "baseline_sha": info["baseline_sha"],
        "final_diff_digest": info["final_diff_digest"],
        "reviewer_backend": "claude",
        "reviewer_model": "opus",
        "reviewer_tier": "deep",  # schema-required (fastpath-run R3 MED-6)
        # MED-6: bind to the diff-root by default (the repo root ``d`` — the diff-root
        # when no separate worktree is passed). The CRIT-1 worktree topology overrides
        # this via ``worktree=<wt>`` so it matches the linked worktree diff_root.
        "worktree": d,
        "attempt_id": 1,
        "ts": "2026-07-12T10:20:00Z",
        "verdict": "approved",
        "integration_rationale": "single-job fast-path: no cross-job seams",
    }
    receipt.update(over)
    for k in (drop or []):
        receipt.pop(k, None)
    if "digest" in (drop or []):
        pass  # intentionally absent
    elif bad_digest:
        receipt["digest"] = "sha256:" + ("e" * 64)
    else:
        receipt["digest"] = tax_mod.record_digest(receipt, exclude_field="digest")
    _fp_write(d, info["receipt_rel"], json.dumps(receipt))


def _selftest_fastpath(expect):
    import tempfile

    tax_mod = _sibling("compound-v-taxonomy.py")
    if tax_mod is None:
        expect("fastpath: shared taxonomy module loads", False)
        return

    base = tempfile.mkdtemp(prefix="cv-c1-fp-")

    def case(name):
        d = os.path.join(base, name)
        os.makedirs(d, exist_ok=True)
        return d

    # (a) minimal fast_path manifest validates under pre-dispatch.
    d = case("valid_predispatch")
    txt = _fp_build(d, tax_mod)
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: valid manifest passes pre-dispatch (%r)" % res, res == [])

    # No-mode = fail-closed for a fast_path manifest.
    d = case("nomode")
    txt = _fp_build(d, tax_mod)
    res = validate_text(txt, mode=None, repo_root=d)
    expect("fastpath: no --mode is rejected (fail-closed)",
           any("mode" in p.lower() for p in res))

    # (b) a second jobs entry under fast_path fails.
    d = case("secondjob")
    txt = _fp_build(d, tax_mod, second_job=True)
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: second job rejected",
           any("exactly ONE" in p for p in res))

    # (c) glob write_allowed under fast_path rejected; one literal path passes.
    d = case("globwrite")
    txt = _fp_build(d, tax_mod, glob_write=True)
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: glob write_allowed rejected",
           any("LITERAL" in p for p in res))

    # (d) block-YAML skip-record validates; flow-{} rejected ("use block YAML").
    d = case("flowaudit")
    txt = _fp_build(d, tax_mod, audits_flow=True)
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: flow-{} audit rejected (use block YAML)",
           any("block YAML" in p for p in res))
    # _mini_yaml nested-mapping fixture: the skip-record parses as a real mapping.
    parsed = _mini_yaml(_fp_build(case("miniyaml"), tax_mod))
    expect("fastpath: _mini_yaml parses nested skip-record mapping",
           isinstance(parsed.get("audits", {}).get("archaeology"), dict)
           and parsed["audits"]["archaeology"].get("skipped") is True)

    # (e) taxonomy classification: a sensitive write target is rejected.
    d = case("sensitive")
    txt = _fp_build(d, tax_mod, write_path="src/auth/login.css",
                    resolved_path="src/auth/login.css")
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: sensitive-path write target rejected",
           any("sensitive" in p for p in res))
    # unreadable taxonomy snapshot -> fail-closed.
    d = case("badtax")
    txt = _fp_build(d, tax_mod)
    os.remove(os.path.join(
        d, "docs/superpowers/execution/2026-07-12T101500Z-make-button-red-a1b2/"
        "taxonomy-snapshot.yaml"))
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: unreadable taxonomy snapshot fails closed",
           any("taxonomy" in p.lower() and ("unreadable" in p or "does not exist"
               in p or "not a regular file" in p) for p in res))

    # (f) cross-artifact binding tampering — every mismatched field fails.
    d = case("tamper_path")
    _fp_write(d, "src/components/other.css", "body{}\n")
    txt = _fp_build(d, tax_mod, write_path="src/components/other.css",
                    resolved_path="src/components/button.css")
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: write literal != resolved_paths[0] rejected",
           any("resolved_paths[0]" in p for p in res))

    d = case("tamper_preid")
    txt = _fp_build(d, tax_mod, manifest_pre_eval_id="2026-07-12T101500Z-evil-9999")
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: pre_eval_id mismatch rejected",
           any("pre_eval_id" in p for p in res))

    d = case("tamper_decision")
    txt = _fp_build(d, tax_mod, record_decision="FULL_PIPELINE")
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: non-FASTPATH_ELIGIBLE record rejected",
           any("FASTPATH_ELIGIBLE" in p for p in res))

    # CRIT-2: pinned pre-eval record self-digest + FASTPATH_ELIGIBLE band gate.
    d = case("tamper_rec_selfdigest")
    txt = _fp_build(d, tax_mod, record_bad_digest=True)
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: pre-eval record self-digest mismatch rejected",
           any("record" in p and "self-digest" in p for p in res))

    d = case("tamper_rec_missing_digest")
    txt = _fp_build(d, tax_mod, record_drop_digest=True)
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: pre-eval record missing self-digest rejected",
           any("record" in p and "self-digest" in p for p in res))

    # A FULL_PIPELINE record whose decision is flipped to FASTPATH_ELIGIBLE with a
    # MEDIUM band (and a freshly-VALID self-digest) MUST still fail on the band gate.
    d = case("tamper_rec_medium_band")
    txt = _fp_build(d, tax_mod, record_impact_band="medium")
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: pinned record impact.band=medium rejected (not low)",
           any("impact.band" in p and "not 'low'" in p for p in res))

    d = case("tamper_rec_diff_band")
    txt = _fp_build(d, tax_mod, record_difficulty_band="high")
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: pinned record difficulty.band=high rejected (not low)",
           any("difficulty.band" in p and "not 'low'" in p for p in res))

    d = case("tamper_rec_override")
    txt = _fp_build(d, tax_mod, record_override_fired=3)
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: pinned record override_fired set rejected",
           any("override_fired" in p for p in res))

    d = case("tamper_taxdigest")
    txt = _fp_build(d, tax_mod, manifest_tax_digest="sha256:" + ("0" * 64))
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: taxonomy_digest mismatch rejected",
           any("taxonomy_digest" in p for p in res))

    d = case("tamper_locdigest")
    txt = _fp_build(d, tax_mod, artifact_fan_out=99)
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: localization content-digest mismatch rejected",
           any("localization" in p and "digest" in p for p in res))

    # MED-8: a MISSING localization-artifact content-digest previously slipped
    # through (only a present string was compared); absence must fail closed.
    d = case("med8_loc_missing_digest")
    txt = _fp_build(d, tax_mod, artifact_drop_digest=True)
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath MED-8: localization artifact missing content-digest "
           "rejected (absence fails closed)",
           any("localization artifact content-digest is missing" in p
               for p in res))

    # MED-8: a wrong-SHAPE localization-artifact digest also fails closed.
    d = case("med8_loc_badshape_digest")
    txt = _fp_build(d, tax_mod, artifact_bad_shape_digest=True)
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath MED-8: localization artifact malformed content-digest "
           "rejected (wrong shape fails closed)",
           any("missing or malformed" in p for p in res))

    # (g) two validation modes.
    d = case("declined_backend")
    txt = _fp_build(d, tax_mod, review={"backend": "codex", "tier": "deep"})
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: review backend != claude rejected",
           any("claude" in p and "review" in p.lower() for p in res))

    d = case("review_no_deep_no_opus")
    txt = _fp_build(d, tax_mod, review={"backend": "claude", "tier": "standard"})
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: review claude+standard (not deep/opus) rejected",
           any("deep" in p or "opus" in p for p in res))

    # pre-dispatch forbids a receipt.
    d = case("predispatch_receipt")
    txt = _fp_build(d, tax_mod, make_receipt=_fp_receipt())
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: pre-dispatch forbids an existing receipt",
           any("forbid" in p or "receipt" in p for p in res))

    # post-review requires + FULLY verifies the receipt (CR5-6). Real git repo so
    # manifest_digest / baseline_sha / final_diff_digest are recomputable; a stale
    # or mismatched binding, or a non-approved verdict, MUST fail closed.
    import shutil as _shutil
    if _shutil.which("git") is not None:
        def _postreview(name, drop=None, bad_digest=False, **over):
            d = case(name)
            txt = _fp_build(d, tax_mod)
            info = _fp_git_and_state(d, tax_mod, txt)
            if info is None:
                return None, d
            _fp_write_receipt(d, tax_mod, info, drop=drop,
                              bad_digest=bad_digest, **over)
            return validate_text(txt, mode="post-review", repo_root=d), d

        res, _ = _postreview("postreview_ok")
        expect("fastpath: post-review with a fully-bound receipt passes (%r)"
               % res, res == [])

        res, _ = _postreview("postreview_badbackend", reviewer_backend="codex")
        expect("fastpath: receipt reviewer_backend != claude rejected",
               res is not None and any("claude" in p for p in res))

        res, _ = _postreview("postreview_badmodel", reviewer_model="sonnet")
        expect("fastpath: receipt reviewer_model not Opus rejected",
               res is not None and any(
                   "opus" in p.lower() or "resolved" in p.lower() for p in res))

        res, _ = _postreview("postreview_verdict_issues", verdict="issues")
        expect("fastpath: receipt verdict 'issues' rejected",
               res is not None and any(
                   "verdict" in p.lower() and "approved" in p.lower()
                   for p in res))

        res, _ = _postreview("postreview_verdict_absent", drop=["verdict"])
        expect("fastpath: receipt with absent verdict rejected",
               res is not None and any("verdict" in p.lower() for p in res))

        res, _ = _postreview("postreview_bad_manifest_digest",
                             manifest_digest="sha256:" + ("0" * 64))
        expect("fastpath: receipt manifest_digest mismatch rejected "
               "(stale/wrong manifest)",
               res is not None and any("manifest_digest" in p for p in res))

        res, _ = _postreview("postreview_bad_baseline", baseline_sha="f" * 40)
        expect("fastpath: receipt baseline_sha mismatch rejected",
               res is not None and any(
                   "baseline" in p.lower() and "!=" in p for p in res))

        res, _ = _postreview("postreview_stale_diff",
                             final_diff_digest="sha256:" + ("0" * 64))
        expect("fastpath: receipt final_diff_digest mismatch rejected "
               "(stale-replay)",
               res is not None and any("final_diff_digest" in p for p in res))

        res, _ = _postreview("postreview_bad_selfdigest", bad_digest=True)
        expect("fastpath: receipt self-digest mismatch rejected",
               res is not None and any(
                   "receipt self-digest" in p.lower() for p in res))

        res, _ = _postreview("postreview_missing_selfdigest", drop=["digest"])
        expect("fastpath: receipt missing self-digest rejected",
               res is not None and any(
                   "missing its self-digest" in p.lower() for p in res))

        # A receipt that exists but the run has NO immutable baseline → fail-closed.
        d = case("postreview_nobaseline")
        txt = _fp_build(d, tax_mod)
        info = _fp_git_and_state(d, tax_mod, txt)
        if info is not None:
            _fp_write(d, "docs/superpowers/execution/%s/state.json" % _FP_RUN_ID,
                      json.dumps({"run_id": _FP_RUN_ID, "jobs": {}}))
            _fp_write_receipt(d, tax_mod, info)
            res = validate_text(txt, mode="post-review", repo_root=d)
            expect("fastpath: post-review with no run baseline fails closed",
                   any("baseline" in p.lower() for p in res))

        # CRIT-1: the final-diff recompute MUST run in the SAME checkout the
        # producer hashed — the worker's linked WORKTREE (diff_root) — not the
        # main repo the dispatcher passes as --repo-root.
        d = case("crit1_worktree_diff_root")
        txt = _fp_build(d, tax_mod)
        wt_info, wt = _fp_git_worktree_and_state(d, tax_mod, txt)
        if wt_info is not None:
            # MED-6: the receipt's worktree binding must name the linked worktree
            # (the diff-root the producer hashed) — not the main repo root.
            _fp_write_receipt(d, tax_mod, wt_info, worktree=wt)
            # (i) with --worktree the receipt's worktree-hashed diff recomputes to
            #     the same digest → PASS (the main tree is clean, so this only
            #     passes because the recompute honored diff_root).
            res = validate_text(txt, mode="post-review", repo_root=d,
                                diff_root=wt)
            expect("fastpath CRIT-1: post-review recomputes the diff in the "
                   "linked worktree -> passes (%r)" % res, res == [])
            # (ii) WITHOUT --worktree the recompute falls to the main repo, whose
            #      diff against baseline is empty → digest mismatch → fail-closed.
            #      Proves the recompute is NOT anchored to repo_root.
            res = validate_text(txt, mode="post-review", repo_root=d,
                                diff_root=None)
            expect("fastpath CRIT-1: recomputing in the main checkout (no "
                   "worktree change) fails closed on the diff digest",
                   any("final_diff_digest" in p for p in res))
            # (iii) an unavailable diff_root never silently passes — fail-closed.
            res = validate_text(txt, mode="post-review", repo_root=d,
                                diff_root=os.path.join(d, "no-such-worktree"))
            expect("fastpath CRIT-1: an unavailable diff-root fails closed",
                   any("recompute the final diff" in p for p in res))
        else:
            expect("fastpath CRIT-1: worktree diff-root suite (git worktree "
                   "unavailable - skipped)", True)

        # ---- ROUND-4 HIGH-1(b): post-review attempt binding (--expected-attempt) ----
        # A receipt sealed at attempt 1, validated when the run's CURRENT attempt is 2,
        # is a stale prior-attempt replay → REJECTED. A correctly-incremented receipt
        # passes. When --expected-attempt is absent, behavior is unchanged (back-compat).
        d = case("postreview_attempt_stale")
        txt = _fp_build(d, tax_mod)
        info = _fp_git_and_state(d, tax_mod, txt)
        if info is not None:
            _fp_write_receipt(d, tax_mod, info, attempt_id=1)
            expect("fastpath HIGH-1: attempt-1 receipt passes when NO expected "
                   "attempt is supplied (back-compat)",
                   validate_text(txt, mode="post-review", repo_root=d) == [])
            expect("fastpath HIGH-1: attempt-1 receipt passes --expected-attempt 1",
                   validate_text(txt, mode="post-review", repo_root=d,
                                 expected_attempt=1) == [])
            res_att = validate_text(txt, mode="post-review", repo_root=d,
                                    expected_attempt=2)
            expect("fastpath HIGH-1: attempt-1 receipt REJECTED under "
                   "--expected-attempt 2 (stale prior-attempt replay)",
                   any("attempt_id" in p and "expected review attempt" in p
                       for p in res_att))

        d = case("postreview_attempt_fresh")
        txt = _fp_build(d, tax_mod)
        info = _fp_git_and_state(d, tax_mod, txt)
        if info is not None:
            _fp_write_receipt(d, tax_mod, info, attempt_id=2)
            expect("fastpath HIGH-1: correctly-incremented attempt-2 receipt passes "
                   "--expected-attempt 2",
                   validate_text(txt, mode="post-review", repo_root=d,
                                 expected_attempt=2) == [])

        # ---- ROUND-4 MED-3: an unloadable receipt schema fails CLOSED (no shape skip) ----
        d = case("postreview_schema_unloadable")
        txt = _fp_build(d, tax_mod)
        info = _fp_git_and_state(d, tax_mod, txt)
        if info is not None:
            _fp_write_receipt(d, tax_mod, info)  # a fully-valid receipt
            expect("fastpath MED-3: baseline receipt passes with a loadable schema",
                   validate_text(txt, mode="post-review", repo_root=d) == [])
            # Stub the module's schema path at a MALFORMED file — the load must fail and
            # that failure must itself be a rejection (never a silent shape-check skip).
            _saved_schema = _RECEIPT_SCHEMA
            bad_schema = os.path.join(d, "bad-schema.json")
            with open(bad_schema, "w", encoding="utf-8") as fh:
                fh.write("{ this is not valid json")
            vars(_fastpath_support)["_RECEIPT_SCHEMA"] = bad_schema
            try:
                res_sch = validate_text(txt, mode="post-review", repo_root=d)
            finally:
                vars(_fastpath_support)["_RECEIPT_SCHEMA"] = _saved_schema
            expect("fastpath MED-3: malformed receipt schema REJECTS (fail-closed, "
                   "no shape-check skip)",
                   any("schema" in p.lower() and "fail-closed" in p.lower()
                       for p in res_sch))
            # A MISSING schema file also fails closed.
            vars(_fastpath_support)["_RECEIPT_SCHEMA"] = os.path.join(d, "does-not-exist.json")
            try:
                res_sch2 = validate_text(txt, mode="post-review", repo_root=d)
            finally:
                vars(_fastpath_support)["_RECEIPT_SCHEMA"] = _saved_schema
            expect("fastpath MED-3: missing receipt schema also REJECTS (fail-closed)",
                   any("schema" in p.lower() and "fail-closed" in p.lower()
                       for p in res_sch2))
    else:
        expect("fastpath: post-review git-binding suite (git unavailable — "
               "skipped)", True)

    # post-review still REQUIRES a receipt (independent of git availability).
    d = case("postreview_missing")
    txt = _fp_build(d, tax_mod)  # no receipt written
    res = validate_text(txt, mode="post-review", repo_root=d)
    expect("fastpath: post-review requires a receipt",
           any("receipt" in p for p in res))

    # (h) containment: traversal ref + escaping symlink write target.
    d = case("traversal_ref")
    txt = _fp_build(d, tax_mod, loc_ref="../evil.localization.json")
    res = validate_text(txt, mode="pre-dispatch", repo_root=d)
    expect("fastpath: '..' traversal ref rejected",
           any("traversal" in p or ".." in p for p in res))

    if hasattr(os, "symlink"):
        d = case("symlink_write")
        try:
            txt = _fp_build(d, tax_mod, symlink_write=True)
            res = validate_text(txt, mode="pre-dispatch", repo_root=d)
            expect("fastpath: escaping-symlink write target rejected",
                   any("symlink" in p or "outside the repo" in p
                       or "escape" in p for p in res))
        except OSError:
            expect("fastpath: escaping-symlink write target rejected "
                   "(symlink unsupported — skipped)", True)

    # MED-9: a fast_path *_ref that is TRACKED/STAGED but absent from any commit
    # must fail — `git ls-files` is not proof of a commit (execution-manifest.md
    # §218-220: referenced artifacts must live in a commit).
    if _shutil.which("git") is not None:
        import subprocess as _sp

        def _gitstage(root, commit):
            r = _sp.run(["git", "-C", root, "init", "-q"],
                        stdout=_sp.PIPE, stderr=_sp.PIPE)
            if r.returncode != 0:
                return False
            for kv in (("user.email", "s@e.com"), ("user.name", "cv"),
                       ("commit.gpgsign", "false"), ("core.hooksPath", "/dev/null")):
                _sp.run(["git", "-C", root, "config"] + list(kv),
                        stdout=_sp.PIPE, stderr=_sp.PIPE)
            _sp.run(["git", "-C", root, "add", "-A"],
                    stdout=_sp.PIPE, stderr=_sp.PIPE)
            if commit:
                r = _sp.run(["git", "-C", root, "commit", "-q", "--no-verify",
                             "-m", "b"], stdout=_sp.PIPE, stderr=_sp.PIPE)
                return r.returncode == 0
            return True  # staged only — deliberately no commit, so no HEAD

        # (i) staged-not-committed: refs are tracked by ls-files yet in NO commit
        #     → the HEAD-commit check must reject (the pre-MED-9 code PASSED here).
        d = case("med9_staged_not_committed")
        txt = _fp_build(d, tax_mod)
        if _gitstage(d, commit=False):
            res = validate_text(txt, mode="pre-dispatch", repo_root=d)
            expect("fastpath MED-9: staged-but-uncommitted ref rejected "
                   "(ls-files is not a commit)",
                   any("not present in a commit" in p for p in res))
        else:
            expect("fastpath MED-9: staged-not-committed suite (git init failed "
                   "- skipped)", True)

        # (ii) genuinely committed refs pass under pre-dispatch — the HEAD check
        #      does not over-reject a durable artifact.
        d = case("med9_committed_ok")
        txt = _fp_build(d, tax_mod)
        if _gitstage(d, commit=True):
            res = validate_text(txt, mode="pre-dispatch", repo_root=d)
            expect("fastpath MED-9: committed refs pass pre-dispatch (%r)" % res,
                   res == [])
        else:
            expect("fastpath MED-9: committed-ok suite (commit failed - "
                   "skipped)", True)
    else:
        expect("fastpath MED-9: commit-containment suite (git unavailable - "
               "skipped)", True)

    # ---------------------------------------------------------------------- #
    # MED-6: the receipt's own ``worktree`` binding MUST equal the diff-root the
    # validator recomputes the final diff in. A missing binding, or one that
    # resolves to a DIFFERENT checkout, fails closed. (The matching-worktree
    # PASS is already proven by the CRIT-1 (i) case above with worktree=wt.)
    # ---------------------------------------------------------------------- #
    if _shutil.which("git") is not None:
        # (a) a receipt with NO worktree binding is rejected.
        d = case("med6_missing_worktree")
        txt = _fp_build(d, tax_mod)
        info = _fp_git_and_state(d, tax_mod, txt)
        if info is not None:
            _fp_write_receipt(d, tax_mod, info, drop=["worktree"])
            res = validate_text(txt, mode="post-review", repo_root=d)
            expect("fastpath MED-6: receipt without a 'worktree' binding rejected",
                   any("worktree" in p.lower() and "MED-6" in p for p in res))
        else:
            expect("fastpath MED-6: missing-worktree suite (git init failed - "
                   "skipped)", True)

        # (b) a receipt whose worktree resolves to a DIFFERENT checkout than the
        #     diff-root is rejected (a receipt sealed against another checkout).
        d = case("med6_wrong_worktree")
        txt = _fp_build(d, tax_mod)
        info = _fp_git_and_state(d, tax_mod, txt)
        if info is not None:
            other = os.path.join(d, "some", "other", "checkout")
            _fp_write_receipt(d, tax_mod, info, worktree=other)
            res = validate_text(txt, mode="post-review", repo_root=d)
            expect("fastpath MED-6: receipt worktree bound to a different checkout "
                   "rejected",
                   any("different checkout" in p and "MED-6" in p for p in res))
        else:
            expect("fastpath MED-6: wrong-worktree suite (git init failed - "
                   "skipped)", True)

        # (c) the correct binding (worktree == repo-root diff-root) still PASSES —
        #     the new gate does not over-reject a genuine single-tree receipt.
        d = case("med6_correct_worktree")
        txt = _fp_build(d, tax_mod)
        info = _fp_git_and_state(d, tax_mod, txt)
        if info is not None:
            _fp_write_receipt(d, tax_mod, info, worktree=d)
            res = validate_text(txt, mode="post-review", repo_root=d)
            expect("fastpath MED-6: correctly-bound worktree receipt passes (%r)"
                   % res, res == [])
        else:
            expect("fastpath MED-6: correct-worktree suite (git init failed - "
                   "skipped)", True)

    # ---------------------------------------------------------------------- #
    # MED-8: HEAD-commit containment fails CLOSED on a git error while a `.git`
    # IS present (was a silent skip), but still DEGRADES when there is no `.git`
    # at all (the legitimate no-git pre-dispatch path). The git-error condition
    # is simulated deterministically by stubbing the module-level probe to its
    # sentinels; the real probe is also exercised end-to-end.
    # ---------------------------------------------------------------------- #
    if _shutil.which("git") is not None:
        import subprocess as _sp8
        med8 = case("med8_headcheck")
        _fp_write(med8, "docs/a.json", "{}")

        def _g8(*a):
            return _sp8.run(["git", "-C", med8] + list(a),
                            stdout=_sp8.PIPE, stderr=_sp8.PIPE)

        _ok8 = _g8("init", "-q").returncode == 0
        for _kv in (("user.email", "s@e.com"), ("user.name", "cv"),
                    ("commit.gpgsign", "false"), ("core.hooksPath", "/dev/null")):
            _g8("config", *_kv)
        _g8("add", "-A")
        _ok8 = _ok8 and _g8("commit", "-q", "--no-verify", "-m", "b").returncode == 0

        if _ok8:
            g = vars(_fastpath_support)
            saved = g["_is_committed_at_head"]
            # (a) git-error sentinel while a `.git` is present -> fail closed.
            g["_is_committed_at_head"] = lambda rr, rp: _GIT_UNAVAILABLE
            try:
                probs = _containment_problems(
                    "artifact", "docs/a.json", med8,
                    must_exist=True, require_committed=True)
            finally:
                g["_is_committed_at_head"] = saved
            expect("fastpath MED-8: HEAD containment fails closed on a git error "
                   "(not a silent skip)",
                   any("could not be verified" in p and "MED-8" in p
                       for p in probs))

            # (b) the no-`.git` degrade sentinel (None) still SKIPS — the
            #     legitimate no-git path must not be turned into a violation.
            g["_is_committed_at_head"] = lambda rr, rp: None
            try:
                probs = _containment_problems(
                    "artifact", "docs/a.json", med8,
                    must_exist=True, require_committed=True)
            finally:
                g["_is_committed_at_head"] = saved
            expect("fastpath MED-8: no-.git containment still degrades (skip, not "
                   "a fail)",
                   not any("could not be verified" in p
                           or "not present in a commit" in p for p in probs))

            # (c) the REAL probe (through the timeout supervisor) returns True for
            #     a genuinely committed file.
            expect("fastpath MED-8: real _is_committed_at_head True for a "
                   "committed file",
                   _is_committed_at_head(med8, "docs/a.json") is True)
        else:
            expect("fastpath MED-8: git-error containment suite (git init/commit "
                   "failed - skipped)", True)
    else:
        expect("fastpath MED-8: git-error containment suite (git unavailable - "
               "skipped)", True)

    # (d) the REAL probe returns None (degrade) when there is no `.git` at all —
    #     independent of git availability, since it never shells out.
    nogit = case("med8_nogit")
    _fp_write(nogit, "docs/a.json", "{}")
    expect("fastpath MED-8: real _is_committed_at_head None when no .git (legit "
           "degrade)", _is_committed_at_head(nogit, "docs/a.json") is None)
