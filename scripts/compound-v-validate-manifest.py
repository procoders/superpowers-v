#!/usr/bin/env python3
"""
Compound V manifest validator — the DETERMINISTIC invariant gate.

Backs the ``partition-reviewer`` agent with a script that either passes or
fails with specifics. No LLM judgment, no network, no fabricated metrics.

Invariants enforced (from PRD §5.1/§5.5 + plan §5/§6)
----------------------------------------------------
1. **Disjoint write scope.** No file can be owned by two jobs. Because
   ``write_allowed`` entries are globs, we detect overlap deterministically:
   two globs conflict if a canonical witness path generated from one is
   matched by the other (checked both directions), or if they are identical.
2. **Codex ⇒ worktree.** Any job with ``backend: codex`` must have
   ``isolation: worktree``.
3. **Reviewers ⇒ deep/opus.** Any job whose ``type`` or ``id`` marks it a
   reviewer (spec/quality/integration/partition review) must resolve to the
   strongest reasoning: either ``tier: deep`` or ``model: opus``.
4. **Shared foundation serial.** Files declared shared/contract (via the
   ``shared_resources`` top-level list, if present) must each be written by a
   ``shared_foundation`` job whose ``run`` is ``serial``. Independently, any
   job typed ``shared_foundation`` must run ``serial``.
5. **Intent routing.** Jobs route by intent, not hardcoded model strings.
   Every job MUST carry ``model`` OR ``tier`` (model is now an optional
   override; existing explicit-model jobs stay valid — backward compatible).
   If present, ``tier`` ∈ {frontier, deep, standard, light} and ``effort`` ∈
   {low, medium, high, xhigh}. ``effort: xhigh`` is valid iff
   ``backend: codex`` (codex's kernel model_reasoning_effort accepts it —
   verified 2026-07-11 on codex-cli 0.144.1, re-verified 2026-09-24 on 0.156.1);
   any other backend with
   xhigh is a violation naming the rule.

Required-field + enum validation (before invariant checks)
-----------------------------------------------------------
All required fields per ``execution-manifest.md`` are checked first. Top-level:
``run_id``, ``jobs``, ``feature``, ``spec_path``, ``plan_path``, ``audits``,
``acceptance_criteria``, ``routing_stance``, ``max_parallel``. Per-job: ``id``,
``title``, ``type``, ``backend``, ``isolation``, ``run``, ``write_allowed``,
``read_allowed``, ``acceptance``, plus (``model`` OR ``tier``). Enums: ``backend``
∈ {claude, codex, antigravity, cursor, opencode} (``none`` is the routing
"return to planning" sentinel, NOT a dispatched job backend; ``opencode``
is a lower-trust, opt-in, WORKER-ONLY backend — see adapter-opencode.md);
``isolation`` ∈ {direct, worktree};
``run`` ∈ {serial, parallel};
``routing_stance`` ∈ {balanced, conservative, cost-aware, claude-only};
``tier`` ∈ {frontier, deep, standard, light}; ``effort`` ∈ {low, medium, high, xhigh}
(``xhigh`` valid iff ``backend: codex``).

Job ``id`` (and top-level ``run_id``) MUST match ``^[A-Za-z0-9._-]+$`` and not be
``.`` / ``..`` — ids become path segments, so a ``../x`` id is a path-traversal
vector and is rejected before dispatch.

**Parallel ⇒ worktree.** A ``run: parallel`` job MUST be ``isolation: worktree``
(per-job scope attribution needs isolation); ``isolation: direct`` is only valid
with ``run: serial``.

Structural sanity is also checked (jobs is a non-empty list; each job has an
``id``; ids unique; ``backend`` present; ``write_allowed`` is a list).

Structural TYPE checks: ``jobs`` non-empty list, ``acceptance_criteria`` list,
``audits`` mapping, ``max_parallel`` int, ``run_id``/``feature``/``spec_path``/
``plan_path`` strings, and per-job ``write_allowed``/``read_allowed``/``acceptance``
lists. A wrong-typed field is its own specific violation.

never-Haiku (execution layer): any job whose explicit ``model`` contains
``haiku`` (case-insensitive — ``haiku``, ``claude-haiku-...``) is rejected. The
frontmatter linter only sees agent/skill frontmatter; this closes the
execution-layer override path.

``depends_on``: every referenced id must exist among the manifest job ids (a
dangling ref is a violation) and the dependency graph must be acyclic (a cycle is
a violation naming the jobs on it).

v2.9 — conditional fast-path (only when a top-level ``fast_path`` block is present)
-----------------------------------------------------------------------------------
A ``fast_path`` manifest adds: single-literal-path partition, block-YAML audit
skip-records, cross-artifact binding (AC-13/CR2-3: the sole ``write_allowed``
literal == ``localization.resolved_paths[0]``; ``pre_eval_id`` / ``FASTPATH_ELIGIBLE``
decision / ``taxonomy_digest`` / localization content-digest equal across the
manifest + pinned pre-eval record + localization artifact), CR4-6 path containment
(normalized, repo-relative, realpath-under-root, committed regular file), a pinned-
snapshot taxonomy denylist, and TWO validation modes (CR4-1) — a ``fast_path``
manifest with **no** ``--mode`` is rejected (fail-closed):
  * ``--mode pre-dispatch`` validates the ``fast_path.review`` DECLARATION
    (``backend:claude`` + ``tier:deep`` OR ``model:opus``, resolved through
    compound-v-resolve-model.py to a concrete Claude Opus; CR4-8/CR5-5) and FORBIDS
    a receipt (it cannot exist yet).
  * ``--mode post-review`` REQUIRES + verifies the dispatcher-written invocation
    receipt (``schemas/fastpath-review-receipt.schema.json``) naming the resolved
    model before REVIEWED/MERGED.
A legacy (non-fast_path) manifest ignores ``--mode`` entirely — backward compatible.

v3.0 — `triage` (Feature A2) and `test_contract` (Feature B2)
--------------------------------------------------------------
Two OPTIONAL top-level blocks, both absent-valid so every manifest committed before
3.0 keeps validating unchanged.

``triage: {tier, pre_eval_id, taxonomy_digest, decided_at}`` becomes MANDATORY under
``--require-triage``, which ships **default OFF in every mode**: a mode-scoped default
is circular, since the block is emitted by the fast-path materializer and would red
that task's own e2e suite. The closure is behavioural — ``/v:dispatch`` passes the flag
on every live dispatch, while the CI historical sweep stays mode-less, which is what
keeps the committed run manifests valid WITHOUT a back-filled record. Under the flag a
missing block, a malformed one, a ``tier`` outside {DIRECT, SCOPED, FULL}, and a
``taxonomy_digest`` that disagrees with the taxonomy on disk (``--taxonomy FILE``,
default ``.claude/compound-v-impact-taxonomy.yaml``) are each a failure; an absent or
unreadable taxonomy fails CLOSED rather than skipping the comparison.

v3.4.1 adds ONE optional key, ``triage.flavor``, whose ONLY value is ``scoped_plus``
— a small edit on a sensitive path, banded SCOPED but reviewed like a FULL. Under
``--require-triage`` a ``scoped_plus`` manifest must carry a ``type: review`` job with
``tier: deep`` and ``backend: claude``; unknown triage keys stay rejected. The other
half of the SCOPED+ promise — an independent cross-model second opinion — cannot be
checked before dispatch, because its evidence does not exist yet, so it is checked
after the fact by ``--require-cross-model-receipt FILE`` (schema, ``run_id``,
``triage.pre_eval_id``, and a ``diff_digest`` that is well-formed, sealed under the
receipt's self-digest and equal to ``--expected-diff-digest`` when the caller passes
the bytes it sealed).

``test_contract: {floor_command, full_command, impacted_map[{when, run}]}`` plus per-job
``test_scope ∈ {full, impacted, floor_only}`` (absent ⇒ ``full``). Both halves of an
``impacted_map`` entry are mandatory, and a scope may never resolve to running NOTHING:
``floor_only`` requires a non-empty ``floor_command``, and ``impacted`` requires a
non-empty ``full_command`` because an unmapped path resolves to the full suite.

Usage
-----
    compound-v-validate-manifest.py <manifest.yaml>
    compound-v-validate-manifest.py --mode pre-dispatch|post-review \\
        [--repo-root DIR] [--config FILE] [--receipt FILE] <manifest.yaml>
    compound-v-validate-manifest.py [--require-triage] [--taxonomy FILE] <manifest.yaml>
    compound-v-validate-manifest.py --require-cross-model-receipt FILE \\
        [--expected-diff-digest sha256:...] <manifest.yaml>
    compound-v-validate-manifest.py --selftest

Exit codes: 0 = all invariants hold, 1 = one or more violations (printed),
2 = usage / parse error.

Python 3.9-safe, stdlib only. PyYAML used if importable; otherwise a tiny
embedded YAML-subset parser handles the manifest shape we emit.
"""

import sys


# --------------------------------------------------------------------------- #
# sys.path hardening — BEFORE the first import that can be shadowed
# (eighth review pass, item C2, 2026-09-03).
#
# THE ATTACK: this file runs with its OWN DIRECTORY first on `sys.path`, and it
# imports `yaml` to read the document that DEFINES every job's `write_allowed`.
# A `yaml.py` planted beside it — or in the CWD, which is on `sys.path` whenever
# this module is loaded by `python3 -c`, exactly how `hooks/lane-guard.sh` loads
# it from inside a worker's own worktree — is imported instead of PyYAML, and its
# `safe_load` then returns whatever lane it likes to the guard that is about to
# enforce it. Same shape for `json` and `re`.
#
# `python3 -P` / `PYTHONSAFEPATH` does this properly, and arrived in 3.11; this
# file targets stock-macOS 3.9.6, so it is done by hand. Two passes, because the
# first cannot use `os` — importing `os` is one of the things being made safe:
# strings first, then an exact realpath comparison once `os` is in hand.
def _harden_sys_path():
    here = __file__
    cut = here.rfind("/")
    unsafe = {"", ".", (here[:cut] if cut > 0 else ".")}
    sys.path[:] = [p for p in sys.path if p not in unsafe]

    import os  # noqa: E402 - after the string pass above, on purpose

    drop = set()
    try:
        drop.add(os.path.realpath(os.path.dirname(os.path.abspath(__file__))))
    except (OSError, ValueError):
        pass
    try:
        drop.add(os.path.realpath(os.getcwd()))
    except (OSError, ValueError):
        pass
    keep = []
    for p in sys.path:
        try:
            resolved = os.path.realpath(p)
        except (OSError, ValueError):
            keep.append(p)
            continue
        if resolved in drop:
            continue
        keep.append(p)
    sys.path[:] = keep


_harden_sys_path()

import json  # noqa: E402 - deliberately after _harden_sys_path()
import os  # noqa: E402
import re  # noqa: E402
import importlib.machinery
import importlib.util


class _SourceOnlyLoader(importlib.machinery.SourceFileLoader):
    def get_code(self, fullname):
        path = self.get_filename(fullname)
        return self.source_to_code(self.get_data(path), path)


_PACKAGE = "cv_validate"
_PACKAGE_MODULES = (
    "yamlload", "globs", "rules", "fastpath_support", "fastpath", "triage", "blocks",
    "core", "advisories", "selftest_fixtures", "selftest_fastpath")


def _load_package():
    pkg_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), _PACKAGE)
    for name in [n for n in sys.modules if n == _PACKAGE or n.startswith(_PACKAGE + ".")]:
        del sys.modules[name]
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        pkg = None
        for sub in ("__init__",) + _PACKAGE_MODULES:
            is_pkg = sub == "__init__"
            name = _PACKAGE if is_pkg else _PACKAGE + "." + sub
            path = os.path.join(pkg_dir, sub + ".py")
            spec = importlib.util.spec_from_file_location(
                name, path, loader=_SourceOnlyLoader(name, path),
                submodule_search_locations=[pkg_dir] if is_pkg else None)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
            if is_pkg:
                pkg = mod
            else:
                setattr(pkg, sub, mod)
    finally:
        sys.dont_write_bytecode = saved


_load_package()

from cv_validate.yamlload import (
    ManifestParseError, load_yaml, _strip_comment, _scalar, _inline_list, _split_commas,
    _open_quote, _value_part, _is_continuation, _BLOCK_SCALAR_RE, _fold_plain_scalars,
    _TOP_LEVEL_JOBS_RE, _assert_jobs_survived, _mini_yaml, _looks_scalar, _colon_index)
from cv_validate.globs import (
    glob_to_regex, glob_match, witness, _seg_is_literal, _literal_prefix,
    _literal_suffix, _seg_disjoint, _provably_disjoint, globs_overlap)
from cv_validate.rules import (
    REVIEWER_TOKENS, VALID_TIERS, VALID_EFFORTS, VALID_BACKENDS, VALID_ISOLATIONS,
    VALID_RUNS, VALID_STANCES, TIMEOUT_SEC_MIN, TIMEOUT_SEC_MAX, VALID_TRIAGE_TIERS,
    TRIAGE_REQUIRED_KEYS, VALID_TRIAGE_FLAVORS, TRIAGE_OPTIONAL_KEYS,
    TRIAGE_ALLOWED_KEYS, TRIAGE_DISABLED_FLAG, PRE_EVAL_DIR_REL, DEFAULT_TAXONOMY_REL,
    VALID_TEST_SCOPES, DEFAULT_TEST_SCOPE, TEST_CONTRACT_ALLOWED_KEYS,
    IMPACTED_MAP_REQUIRED_KEYS, RETRY_ALLOWED_KEYS, INTERFACES_ALLOWED_KEYS,
    TOPLEVEL_REQUIRED, JOB_REQUIRED, _ID_RE, _id_is_safe, _is_reviewer)
from cv_validate.fastpath_support import (
    FASTPATH_MODES, _EXEC_DIR, _RECEIPT_SUBPATH, _RECEIPT_SCHEMA, _CROSS_MODEL_SCHEMA,
    _PLAN_REVIEW_SCHEMA, _CROSS_MODEL_EXPECTED, _MAX_DIFF_BYTES, _GIT_DIFF_TIMEOUT_S,
    _GIT_PROBE_TIMEOUT_S, _GIT_UNAVAILABLE, _SIBLING_CACHE, _load_sibling, _sibling,
    _read_json_file, _is_claude_opus, _DIGEST_RE, _is_digest_shaped, _is_git_tracked,
    _git_via_supervisor, _is_committed_at_head, _containment_problems,
    _review_resolution, _load_bundled_schema, _load_receipt_schema, _json_type_ok,
    _schema_lite_value, _schema_lite, _read_run_baseline, _recompute_diff_digest,
    _sealed_receipt_problems, verify_sealed_receipt)
from cv_validate.fastpath import _validate_receipt, _validate_fast_path
from cv_validate.triage import (
    _iso8601_ok, _validate_triage, _DECISION_TO_TIER, _triage_record_problems,
    _is_deep_claude_review_job, _validate_triage_flavor, _null_digest_message,
    _triage_disabled_problems, _triage_digest_problems, _validate_cross_model_receipt)
from cv_validate.blocks import (
    _validate_test_contract, _validate_retry, _validate_provision,
    _string_list_problems, _CATCH_ALL_TOOLCHAIN_GLOBS, _validate_toolchain_artifacts,
    _validate_global_constraints, _validate_interfaces)
from cv_validate.core import validate, validate_text
from cv_validate.advisories import (
    AGENT_MEMORY_ROOTS, is_agent_memory_glob, unnamespaced_agent_memory_name,
    RUNTIME_CONCURRENCY_DEFAULT, TRANSPORT_AGENT_HEADROOM, _emit_workflow_module,
    _EMIT_WORKFLOW_MODULE, wave_concurrency_advisories, advisories,
    cross_model_receipt_advisories, advisories_text)
from cv_validate.selftest_fixtures import (
    GOOD_MANIFEST, FOLDED_FEATURE, FOLDED_CRITERION, FOLDED_MANIFEST, BAD_MANIFEST,
    PARALLEL_DIRECT_MANIFEST, BAD_ID_MANIFEST, HAIKU_MODEL_MANIFEST,
    DANGLING_DEP_MANIFEST, CYCLE_DEP_MANIFEST, WRONG_TYPE_MANIFEST,
    XHIGH_CODEX_MANIFEST, XHIGH_CLAUDE_MANIFEST, _timeout_manifest, _v3_manifest,
    _triage_block, ANTIGRAVITY_DIRECT_MANIFEST, OPENCODE_DIRECT_MANIFEST,
    OPENCODE_WORKTREE_MANIFEST, OPENCODE_REVIEWER_MANIFEST,
    OPENCODE_BARE_MODEL_MANIFEST, OPENCODE_MALFORMED_MODEL_MANIFEST,
    OPENCODE_INT_MODEL_MANIFEST, OPENCODE_LIST_MODEL_MANIFEST,
    OPENCODE_DICT_MODEL_MANIFEST)
from cv_validate.selftest_fastpath import (
    _fp_taxonomy_bytes, _fp_write, _fp_build, _fp_receipt, _FP_RUN_ID, _FP_JOB_ID,
    _FP_WRITE_PATH, _fp_git_and_state, _fp_git_worktree_and_state, _fp_write_receipt,
    _selftest_fastpath)


def _find_repo_root(start):
    """Walk up from ``start`` to the nearest dir containing ``.git`` (a dir OR a
    worktree ``.git`` file); fall back to the CWD when none is found."""
    d = os.path.abspath(start)
    while True:
        if os.path.exists(os.path.join(d, ".git")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return os.getcwd()
        d = parent


def _get_opt(args, name):
    """Pop ``--name VALUE`` from a mutable args list; return VALUE or None."""
    if name in args:
        i = args.index(name)
        if i + 1 < len(args):
            val = args[i + 1]
            del args[i:i + 2]
            return val
        del args[i:i + 1]
    return None


def main(argv):
    args = list(argv[1:])
    if "--selftest" in args:
        return _selftest()
    # v3.0 (Feature A2): a BOOLEAN flag, default OFF in every mode. /v:dispatch
    # passes it on every live dispatch; the CI historical sweep does not.
    require_triage = "--require-triage" in args
    while "--require-triage" in args:
        args.remove("--require-triage")
    mode = _get_opt(args, "--mode")
    repo_root = _get_opt(args, "--repo-root")
    config_path = _get_opt(args, "--config")
    receipt_path = _get_opt(args, "--receipt")
    # Where triage.taxonomy_digest is checked against; absent ⇒
    # <repo-root>/.claude/compound-v-impact-taxonomy.yaml.
    taxonomy_path = _get_opt(args, "--taxonomy")
    # v3.4.1: the SCOPED+ cross-model receipt (/v:dispatch step 8 passes it for a
    # `triage.flavor: scoped_plus` run, and only after the review has run).
    # `--expected-diff-digest` is optional and re-asserts the sealed patch bytes the
    # caller handed the reviewer against the digest the receipt claims.
    cross_model_receipt = _get_opt(args, "--require-cross-model-receipt")
    expected_diff_digest = _get_opt(args, "--expected-diff-digest")
    # CRIT-1: the worker's linked worktree — the checkout the producer hashed the
    # final diff in. The post-review recompute runs there; absent ⇒ repo_root.
    diff_root = _get_opt(args, "--worktree")
    # HIGH-1(b): the CURRENT review attempt (the caller reads it from the run's
    # state.json). When supplied, the post-review receipt's attempt_id MUST equal it —
    # a stale prior-attempt receipt cannot be replayed against a newer attempt.
    expected_attempt = _get_opt(args, "--expected-attempt")
    if expected_attempt is not None:
        try:
            expected_attempt = int(expected_attempt)
        except (TypeError, ValueError):
            print("error: --expected-attempt must be an integer", file=sys.stderr)
            return 2
    # Drop any remaining flags; the first non-flag token is the manifest path.
    positional = [a for a in args if not a.startswith("--")]
    if not positional:
        print("usage: compound-v-validate-manifest.py [--mode pre-dispatch|"
              "post-review] [--repo-root DIR] [--worktree DIR] [--config FILE] "
              "[--receipt FILE] [--expected-attempt N] [--require-triage] "
              "[--taxonomy FILE] [--require-cross-model-receipt FILE] "
              "[--expected-diff-digest sha256:...] <manifest.yaml>",
              file=sys.stderr)
        return 2
    if mode is not None and mode not in FASTPATH_MODES:
        print("error: --mode '%s' invalid (expected one of %s)"
              % (mode, ", ".join(FASTPATH_MODES)), file=sys.stderr)
        return 2
    path = positional[0]
    if not os.path.isfile(path):
        print("error: not a file: %s" % path, file=sys.stderr)
        return 2
    if repo_root is None:
        repo_root = _find_repo_root(os.path.dirname(os.path.abspath(path)))
    # Read the RAW bytes so the manifest_digest binding (CR5-6) content-addresses
    # to exactly what the producer digested; decode for YAML parsing separately.
    with open(path, "rb") as fh:
        raw = fh.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        print(json.dumps({"verdict": "error", "error": "manifest is not UTF-8 "
                          "(%s)" % e}), file=sys.stderr)
        return 2
    try:
        problems = validate_text(text, mode=mode, repo_root=repo_root,
                                 config_path=config_path,
                                 receipt_path=receipt_path,
                                 manifest_bytes=raw, diff_root=diff_root,
                                 expected_attempt=expected_attempt,
                                 require_triage=require_triage,
                                 taxonomy_path=taxonomy_path,
                                 cross_model_receipt=cross_model_receipt,
                                 expected_diff_digest=expected_diff_digest)
    except Exception as e:  # noqa: BLE001 - report parse failure cleanly
        print(json.dumps({"verdict": "error", "error": str(e)}), file=sys.stderr)
        return 2

    # ADVISORY channel (v3.5.0). Computed on BOTH paths and printed on both, so a
    # reader never has to make a manifest valid before they can see the advice. It
    # cannot change `problems`, the verdict, or the exit code — that separation is
    # the whole contract, and `agents/partition-reviewer.md` restates it.
    warnings = advisories_text(text)
    # The cross-model receipt is a separate file the manifest text alone can't see;
    # read it independently, same fail-soft rule as everything in this channel — an
    # unreadable/absent receipt contributes no advisory (the hard checks above
    # already fail-closed on that; this channel never duplicates a violation).
    if cross_model_receipt not in (None, ""):
        try:
            with open(cross_model_receipt, "r", encoding="utf-8") as _cm_fh:
                _cm_receipt = json.load(_cm_fh)
        except Exception:  # noqa: BLE001 - advisory channel is fail-soft
            _cm_receipt = None
        warnings.extend(cross_model_receipt_advisories(_cm_receipt))
    for w in warnings:
        print("ADVISORY: %s" % w, file=sys.stderr)

    if problems:
        print("MANIFEST INVALID: %d violation(s)" % len(problems), file=sys.stderr)
        for p in problems:
            print("  - %s" % p, file=sys.stderr)
        print(json.dumps({"verdict": "invalid", "violations": problems,
                          "warnings": warnings}, indent=2))
        return 1
    print(json.dumps({"verdict": "valid", "violations": [],
                      "warnings": warnings}, indent=2))
    return 0


def _selftest():
    failures = []

    def expect(name, cond):
        if cond:
            print("  ok   - %s" % name)
        else:
            print("  FAIL - %s" % name)
            failures.append(name)

    # Glob overlap units.
    expect("overlap: identical globs", globs_overlap("a/**", "a/**"))
    expect(
        "overlap: src/features/** vs src/features/api/**",
        globs_overlap("src/features/**", "src/features/api/**"),
    )
    expect(
        "disjoint: src/a/** vs src/b/**",
        not globs_overlap("src/a/**", "src/b/**"),
    )
    expect(
        "disjoint: src/types/x.ts vs src/db/y.ts",
        not globs_overlap("src/types/x.ts", "src/db/y.ts"),
    )
    expect(
        "overlap: dir/* vs dir/file.ts",
        globs_overlap("dir/*", "dir/file.ts"),
    )

    # GOOD manifest -> zero violations.
    good = validate_text(GOOD_MANIFEST)
    expect("good manifest: zero violations (%r)" % good, good == [])

    # BAD manifest -> catches each planted defect.
    bad = validate_text(BAD_MANIFEST)
    joined = " || ".join(bad)
    expect("bad manifest: has violations", len(bad) > 0)
    expect(
        "bad: codex-without-worktree caught",
        "backend codex" in joined and "isolation" in joined,
    )
    expect(
        "bad: reviewer-not-opus caught",
        "reviewer job" in joined and "opus" in joined,
    )
    expect("bad: write overlap caught", "overlap" in joined)
    expect(
        "bad: shared_foundation non-serial caught",
        "must run serial" in joined,
    )
    expect(
        "bad: orphan shared resource caught",
        "orphan.ts" in joined or "not written by any" in joined,
    )
    expect(
        "bad: missing model-or-tier caught",
        "must have 'model' or 'tier'" in joined,
    )
    expect(
        "bad: invalid tier caught",
        "tier 'turbo' invalid" in joined,
    )
    expect(
        "bad: invalid effort caught",
        "effort 'extreme' invalid" in joined,
    )

    # effort xhigh: valid iff backend codex — selftested BOTH ways.
    xh_ok = validate_text(XHIGH_CODEX_MANIFEST)
    expect("codex+xhigh manifest valid (%r)" % xh_ok, xh_ok == [])
    xh_bad = validate_text(XHIGH_CLAUDE_MANIFEST)
    expect(
        "claude+xhigh caught (xhigh is codex-only)",
        any("xhigh is codex-only (kernel: model_reasoning_effort); use high" in p
            for p in xh_bad),
    )
    expect(
        "bad: parallel+direct caught",
        "run: parallel with isolation: direct" in joined,
    )

    # timeout_sec: optional, integer seconds, bounded [60, 21600]. ABSENT is valid
    # and leaves the worker script's DEFAULT_TIMEOUT_SEC=900 in force.
    ts_absent = validate_text(_timeout_manifest(""))
    expect("timeout_sec absent: manifest valid (%r)" % ts_absent, ts_absent == [])
    ts_ok = validate_text(_timeout_manifest("1800"))
    expect("timeout_sec 1800: manifest valid (%r)" % ts_ok, ts_ok == [])
    for _edge in (TIMEOUT_SEC_MIN, TIMEOUT_SEC_MAX):
        _e = validate_text(_timeout_manifest(str(_edge)))
        expect("timeout_sec %d (inclusive bound) valid (%r)" % (_edge, _e), _e == [])
    ts_small = validate_text(_timeout_manifest(str(TIMEOUT_SEC_MIN - 1)))
    expect(
        "timeout_sec too small caught",
        any("timeout_sec 59 out of range" in p and "60" in p and "21600" in p
            for p in ts_small),
    )
    ts_large = validate_text(_timeout_manifest(str(TIMEOUT_SEC_MAX + 1)))
    expect(
        "timeout_sec too large caught",
        any("timeout_sec 21601 out of range" in p and "60" in p and "21600" in p
            for p in ts_large),
    )
    ts_bool = validate_text(_timeout_manifest("true"))
    expect(
        "timeout_sec bool caught (bool is an int subclass)",
        any("timeout_sec must be an integer number of seconds" in p
            for p in ts_bool),
    )
    ts_str = validate_text(_timeout_manifest('"900"'))
    expect(
        "timeout_sec string caught",
        any("timeout_sec must be an integer number of seconds" in p
            for p in ts_str),
    )
    expect(
        "no unknown-key rejection introduced (good manifest still clean)",
        not any("unknown" in p.lower() for p in good),
    )

    # never-Haiku policy: a model: haiku execution-layer override is INVALID.
    haiku = validate_text(HAIKU_MODEL_MANIFEST)
    expect(
        "model:haiku override caught (never-Haiku policy)",
        any("never-Haiku policy" in p for p in haiku),
    )

    # depends_on: dangling ref INVALID, cycle INVALID, valid DAG OK.
    dangling = validate_text(DANGLING_DEP_MANIFEST)
    expect(
        "dangling depends_on ref caught",
        any("references unknown job id 'task-0-missing'" in p for p in dangling),
    )
    cyc = validate_text(CYCLE_DEP_MANIFEST)
    expect(
        "depends_on cycle caught",
        any("cycle detected" in p for p in cyc),
    )
    expect(
        "valid DAG (good manifest) has no depends_on violation",
        not any("depends_on" in p or "cycle detected" in p for p in good),
    )

    # Structural type check: wrong-typed required field is a specific violation.
    wt_bad = validate_text(WRONG_TYPE_MANIFEST)
    expect(
        "wrong-typed acceptance_criteria caught",
        any("'acceptance_criteria' must be a list" in p for p in wt_bad),
    )

    # parallel ⇒ worktree, and a bad job id, each caught.
    pd_bad = validate_text(PARALLEL_DIRECT_MANIFEST)
    expect(
        "parallel+direct manifest invalid",
        any("run: parallel with isolation: direct" in p for p in pd_bad),
    )
    badid = validate_text(BAD_ID_MANIFEST)
    expect(
        "bad job id '../x' caught",
        any("invalid characters" in p for p in badid),
    )

    # antigravity ⇒ worktree: an external no-kernel-sandbox worker with
    # isolation: direct is INVALID (mirrors the codex⇒worktree invariant).
    agy_bad = validate_text(ANTIGRAVITY_DIRECT_MANIFEST)
    expect(
        "antigravity+direct caught (antigravity requires worktree)",
        any("backend antigravity but isolation" in p
            and "antigravity requires worktree" in p for p in agy_bad),
    )

    # opencode ⇒ worktree: same invariant, new backend (v1: worker-only, lower-trust).
    opencode_bad = validate_text(OPENCODE_DIRECT_MANIFEST)
    expect(
        "opencode+direct caught (opencode requires worktree)",
        any("backend opencode but isolation" in p
            and "opencode requires worktree" in p for p in opencode_bad),
    )
    opencode_ok = validate_text(OPENCODE_WORKTREE_MANIFEST)
    expect("opencode+worktree manifest is valid (provider/model string accepted)",
           opencode_ok == [])

    # WORKER-ONLY: a reviewer job MUST NEVER resolve to backend opencode,
    # even when tier: deep + isolation: worktree are otherwise satisfied.
    opencode_reviewer_bad = validate_text(OPENCODE_REVIEWER_MANIFEST)
    expect(
        "opencode reviewer job REJECTED (WORKER-ONLY)",
        any("reviewer job 'task-1-quality-review'" in p
            and "backend 'opencode'" in p
            and "WORKER-ONLY" in p for p in opencode_reviewer_bad),
    )

    # opencode provider/model shape: a bare (slash-less) or malformed (empty-side)
    # explicit model override is REJECTED before dispatch.
    opencode_bare_bad = validate_text(OPENCODE_BARE_MODEL_MANIFEST)
    expect(
        "bare opencode model 'gpt-6' REJECTED (not provider/model)",
        any("not a valid 'provider/model' string" in p for p in opencode_bare_bad),
    )
    opencode_malformed_bad = validate_text(OPENCODE_MALFORMED_MODEL_MANIFEST)
    expect(
        "malformed opencode model 'anthropic/' REJECTED (empty right side)",
        any("not a valid 'provider/model' string" in p
            for p in opencode_malformed_bad),
    )
    # NON-STRING opencode model (int / list / dict) must ALSO be rejected — it can
    # never be a provider/model string and must not skip the shape check.
    opencode_int_bad = validate_text(OPENCODE_INT_MODEL_MANIFEST)
    expect(
        "non-string opencode model (int 42) REJECTED",
        any("not a valid 'provider/model' string" in p
            for p in opencode_int_bad),
    )
    opencode_list_bad = validate_text(OPENCODE_LIST_MODEL_MANIFEST)
    expect(
        "non-string opencode model (list) REJECTED",
        any("not a valid 'provider/model' string" in p
            for p in opencode_list_bad),
    )
    opencode_dict_bad = validate_text(OPENCODE_DICT_MODEL_MANIFEST)
    expect(
        "non-string opencode model (dict) REJECTED",
        any("not a valid 'provider/model' string" in p
            for p in opencode_dict_bad),
    )

    # Reviewer satisfied by tier: deep (no model) — GOOD manifest task-3 uses
    # tier: deep and must not trip the reviewer invariant.
    expect(
        "reviewer via tier:deep accepted (no model)",
        not any("reviewer job 'task-3-spec-review'" in p for p in good),
    )
    # Finding 119: a reviewer lifted to the frontier tier (Fable) is STRONGER than
    # deep and must pass; a light-tier reviewer must still fail. The GOOD manifest
    # re-parsed, mutated, re-dumped — validate_text is the same entry the case
    # above used, so the two verdicts differ only in the reviewer's tier.
    import yaml as _yaml_f119
    _fr = _yaml_f119.safe_load(GOOD_MANIFEST)
    for _j in _fr.get("jobs", []):
        if _j.get("id") == "task-3-spec-review":
            _j["tier"] = "frontier"; _j.pop("model", None)
    _fr_probs = validate_text(_yaml_f119.safe_dump(_fr, sort_keys=False))
    expect("reviewer via tier:frontier accepted — stronger passes (finding 119)",
           not any("reviewer job 'task-3-spec-review'" in p for p in _fr_probs))
    for _j in _fr.get("jobs", []):
        if _j.get("id") == "task-3-spec-review":
            _j["tier"] = "light"
    _fr_probs2 = validate_text(_yaml_f119.safe_dump(_fr, sort_keys=False))
    expect("reviewer via tier:light still refused (finding 119 never weakens)",
           any("reviewer job 'task-3-spec-review'" in p for p in _fr_probs2))

    # Empty / malformed.
    expect("no jobs -> violation", validate_text("run_id: x") != [])
    expect("not a mapping -> violation", validate({}) != [])
    try:
        import yaml as _yaml_probe  # noqa: F401
        _have_pyyaml = True
    except ImportError:
        _have_pyyaml = False
    if _have_pyyaml:
        # finding 53: an inner ": " in an unquoted scalar is refused by PyYAML;
        # the validator must report it, never consult the subset parser instead.
        _fifty_three = validate_text("run_id: x\njobs:\n- id: a\n  title: Task A: the scorer\n"
                                     "  write_allowed: [a.py]\n")
        expect("PyYAML-rejected manifest is a VIOLATION, not a subset-parser pass (%r)"
               % _fifty_three, len(_fifty_three) == 1 and "PyYAML rejected" in _fifty_three[0])

    # Fallback parser parity: force the embedded parser on the good manifest.
    parsed = _mini_yaml(GOOD_MANIFEST)
    fb = validate(parsed)
    expect("fallback parser: good manifest clean (%r)" % fb, fb == [])
    fb_bad = validate(_mini_yaml(BAD_MANIFEST))
    expect("fallback parser: bad manifest flagged", len(fb_bad) > 0)

    # ------------------------------------------------------------------ #
    # FIFTH REVIEW PASS (2026-09-02) — the fallback parser could not read
    # what safe_dump writes.
    #
    # Every manifest in this repo is `yaml.safe_dump` output, and safe_dump
    # produces two shapes the shipped subset parser had no rule for: a scalar
    # FOLDED across lines at `width`, and a block SEQUENCE at its parent key's
    # own indentation. Each one made `parse_map` break early, so everything
    # after it — `jobs:` included — was silently dropped. `hooks/lane-guard.sh`
    # loads a manifest through this very function on an interpreter without
    # PyYAML; it read "no jobs", resolved no lane, and allowed every out-of-lane
    # write. FOLDED_MANIFEST below is literal safe_dump(width=100) output.
    folded = _mini_yaml(FOLDED_MANIFEST)
    expect("fallback parser: a folded plain scalar is joined, not truncated",
           folded.get("feature") == FOLDED_FEATURE)
    expect("fallback parser: a folded list item is joined too",
           folded.get("acceptance_criteria") == [FOLDED_CRITERION])
    expect("fallback parser: the document SURVIVES the fold (jobs present)",
           [j.get("id") for j in (folded.get("jobs") or [])] == ["guard-honest"])
    expect("fallback parser: the folded job's write_allowed lane is exact — "
           "this is the value the lane guard enforces on",
           folded["jobs"][0].get("write_allowed")
           == ["hooks/lane-guard.sh", "tests/test-lane-guard.sh"])

    # A TRUNCATED PARSE IS NOT A MANIFEST WITH NO JOBS. Multi-line flow
    # sequences are outside this parser's subset, so it recovers no jobs from
    # this document — and it must SAY SO rather than hand back a jobless
    # mapping that every caller reads as "nothing to enforce".
    _flow_jobs = "run_id: x\njobs: [\n  {id: a}\n]\n"
    try:
        _mini_yaml(_flow_jobs)
        _truncation_raised = ""
    except ValueError as _exc:
        _truncation_raised = str(_exc)
    expect("fallback parser: a top-level `jobs:` that yields no jobs RAISES",
           "TRUNCATED, not empty" in _truncation_raised)
    expect("...and the error says what to do about it (PyYAML)",
           "PyYAML" in _truncation_raised)
    expect("an explicitly empty `jobs: []` is parsed faithfully, not rejected",
           _mini_yaml("run_id: x\njobs: []\n") == {"run_id": "x", "jobs": []})
    expect("a document with no top-level `jobs:` at all is untouched by the check",
           _mini_yaml("run_id: x\n") == {"run_id": "x"})

    # The fixture is only evidence if it really is what safe_dump writes. When
    # PyYAML is importable, re-dump it and compare byte for byte; the CI floor
    # job installs PyYAML, so this runs there.
    try:
        import yaml as _y
    except ImportError:  # pragma: no cover - exercised on a PyYAML-less box
        expect("safe_dump cross-check SKIPPED — no PyYAML on this interpreter",
               True)
    else:
        _redump = _y.safe_dump(_y.safe_load(FOLDED_MANIFEST), width=100,
                               sort_keys=False, allow_unicode=True,
                               default_flow_style=False)
        expect("the folded fixture IS safe_dump(width=100) output, byte for byte",
               _redump == FOLDED_MANIFEST)
        expect("the fallback parser agrees with PyYAML on the folded manifest",
               _y.safe_load(FOLDED_MANIFEST) == folded)

    # --- v3.0 Feature A2: the `triage` block, behind --require-triage ---
    # The flag ships DEFAULT OFF in EVERY mode. A mode-scoped default was tried and
    # removed as circular: the block is emitted by the fast-path materializer, so
    # defaulting it on for --mode pre-dispatch would red the e2e suite inside the very
    # task that adds the emitter. `/v:dispatch` passes the flag explicitly on every
    # dispatch; the CI historical sweep does not.
    import glob as _glob3
    import tempfile as _tf3

    _tax_mod3 = _sibling("compound-v-taxonomy.py")
    _tri_root = _tf3.mkdtemp(prefix="cv-v3-triage-")
    os.makedirs(os.path.join(_tri_root, ".claude"), exist_ok=True)
    _tri_tax = os.path.join(_tri_root, DEFAULT_TAXONOMY_REL)
    # SYNTHESIZED taxonomy bytes: `.claude/compound-v-impact-taxonomy.yaml` does not
    # exist in this repo yet (it is generated by /v:onboard draft-taxonomy), so the
    # digest check is proven against bytes we write here, never against a file whose
    # absence would make the test vacuous.
    with open(_tri_tax, "wb") as _fh3:
        _fh3.write(b"version: 1\npath_patterns:\n  - glob: 'scripts/**'\n"
                   b"    impact_band: high\n    difficulty_band: medium\n")
    _tri_digest = (_tax_mod3.taxonomy_digest_file(_tri_tax)
                   if _tax_mod3 is not None else "sha256:" + "0" * 64)

    # WITHOUT the flag: a manifest with NO triage block is valid (the bootstrap
    # exemption 3.0 legitimately takes once), and so is a malformed one.
    _t_absent = validate_text(_v3_manifest(), repo_root=_tri_root)
    expect("triage: absent block valid without --require-triage (%r)" % _t_absent,
           _t_absent == [])
    _t_bad_off = validate_text(_v3_manifest(_triage_block(_tri_digest, tier="MAYBE")),
                               repo_root=_tri_root)
    expect("triage: malformed block ignored without the flag (historical sweep stays green)",
           _t_bad_off == [])

    # WITH the flag: absent block FAILS.
    _t_missing = validate_text(_v3_manifest(), repo_root=_tri_root, require_triage=True)
    expect("triage: absent block caught under --require-triage",
           any("missing required top-level 'triage' block" in p for p in _t_missing))

    # WITH the flag: a well-formed, digest-matched block is VALID.
    _t_good = validate_text(_v3_manifest(_triage_block(_tri_digest)),
                            repo_root=_tri_root, require_triage=True)
    expect("triage: well-formed digest-matched block valid (%r)" % _t_good, _t_good == [])

    # Each tier in the enum is accepted; anything else is not.
    for _tier in VALID_TRIAGE_TIERS:
        _r = validate_text(_v3_manifest(_triage_block(_tri_digest, tier=_tier)),
                           repo_root=_tri_root, require_triage=True)
        expect("triage: tier %s accepted (%r)" % (_tier, _r), _r == [])
    _t_tier = validate_text(_v3_manifest(_triage_block(_tri_digest, tier="direct")),
                            repo_root=_tri_root, require_triage=True)
    expect("triage: out-of-enum tier caught (case-sensitive — 'direct' is not DIRECT)",
           any("triage.tier 'direct' invalid" in p for p in _t_tier))

    # Malformed shapes: a missing key, a non-mapping block, an unknown key.
    for _key in TRIAGE_REQUIRED_KEYS:
        _r = validate_text(_v3_manifest(_triage_block(_tri_digest, drop=_key)),
                           repo_root=_tri_root, require_triage=True)
        expect("triage: missing '%s' caught" % _key,
               any("triage missing required field '%s'" % _key in p for p in _r))
    _t_scalar = validate_text(_v3_manifest("triage: SCOPED\n"),
                              repo_root=_tri_root, require_triage=True)
    expect("triage: non-mapping block caught",
           any("'triage' must be a mapping" in p for p in _t_scalar))
    _t_unknown = validate_text(
        _v3_manifest(_triage_block(_tri_digest, extra="  taxonomy-digest: oops\n")),
        repo_root=_tri_root, require_triage=True)
    expect("triage: unknown key caught (a 'taxonomy-digest' typo must not pass silently)",
           any("triage has unknown key 'taxonomy-digest'" in p for p in _t_unknown))

    # pre_eval_id becomes a path segment (docs/superpowers/pre-eval/<id>.json).
    _t_trav = validate_text(_v3_manifest(_triage_block(_tri_digest,
                                                       pre_eval_id="../../etc/passwd")),
                            repo_root=_tri_root, require_triage=True)
    expect("triage: path-traversal pre_eval_id caught",
           any("triage.pre_eval_id" in p and "path segment" in p for p in _t_trav))

    # decided_at: ISO-8601. Python 3.9's fromisoformat rejects a trailing 'Z', which
    # every producer writes — the Zulu suffix is stripped, so the CI floor and a newer
    # local interpreter agree.
    _t_zulu = validate_text(
        _v3_manifest(_triage_block(_tri_digest, decided_at="2026-09-01T10:15:00Z")),
        repo_root=_tri_root, require_triage=True)
    expect("triage: Zulu-suffixed decided_at parses on the 3.9 floor (%r)" % _t_zulu,
           _t_zulu == [])
    _t_when = validate_text(
        _v3_manifest(_triage_block(_tri_digest, decided_at="last tuesday")),
        repo_root=_tri_root, require_triage=True)
    expect("triage: unparseable decided_at caught",
           any("triage.decided_at" in p and "ISO-8601" in p for p in _t_when))

    # taxonomy_digest: shape, mismatch, and an unreadable taxonomy all fail closed.
    _t_shape = validate_text(_v3_manifest(_triage_block(_tri_digest, )).replace(
        _tri_digest, "not-a-digest"), repo_root=_tri_root, require_triage=True)
    expect("triage: malformed taxonomy_digest shape caught",
           any("triage.taxonomy_digest" in p and "sha256:<64-hex>" in p
               for p in _t_shape))
    _t_mismatch = validate_text(
        _v3_manifest(_triage_block("sha256:" + "b" * 64)),
        repo_root=_tri_root, require_triage=True)
    expect("triage: taxonomy_digest mismatch caught (synthesized taxonomy bytes)",
           any("triage.taxonomy_digest" in p and "does not match the taxonomy on disk" in p
               for p in _t_mismatch))
    _t_notax = validate_text(_v3_manifest(_triage_block(_tri_digest)),
                             repo_root=os.path.join(_tri_root, "no-such-root"),
                             require_triage=True)
    expect("triage: absent taxonomy on disk fails closed (never a silent skip)",
           any("triage.taxonomy_digest" in p and "unreadable" in p for p in _t_notax))
    # This task: an ABSENT taxonomy (the common "never ran /v:onboard" case)
    # names the real producer so the failure is actionable, not just diagnosed.
    expect("triage: absent taxonomy names /v:onboard draft-taxonomy as the fix",
           any("triage.taxonomy_digest" in p and "does not exist" in p
               and "/v:onboard" in p and "draft-taxonomy" in p for p in _t_notax))
    # The verdict must not blur with the DIGEST-MISMATCH case (taxonomy exists,
    # disagrees) — that is a different, more serious situation (the record
    # outlived the rules) and must never suggest re-running /v:onboard, only
    # /v:triage against the taxonomy that is already there.
    expect("triage: mismatch case (file exists) is never given the /v:onboard hint",
           not any("/v:onboard" in p for p in _t_mismatch))
    expect("triage: mismatch case still points at /v:triage, unchanged",
           any("re-run /v:triage" in p for p in _t_mismatch))
    # A taxonomy that exists but is unreadable for a DIFFERENT reason (here: the
    # configured path is a directory, not a file) must fall through to the
    # generic "unreadable" message, unchanged — the /v:onboard hint is specific
    # to genuine absence, not a stand-in for every unreadable-taxonomy case.
    _tri_taxdir = os.path.join(_tri_root, "a-directory-not-a-file")
    os.makedirs(_tri_taxdir, exist_ok=True)
    _t_taxisdir = validate_text(_v3_manifest(_triage_block(_tri_digest)),
                                repo_root=_tri_root, require_triage=True,
                                taxonomy_path=_tri_taxdir)
    expect("triage: taxonomy path that is a directory fails closed, generically",
           any("triage.taxonomy_digest" in p and "is unreadable" in p
               and "does not exist" not in p and "/v:onboard" not in p
               for p in _t_taxisdir))
    # --taxonomy overrides the default location.
    _t_over = validate_text(_v3_manifest(_triage_block(_tri_digest)),
                            repo_root=os.path.join(_tri_root, "no-such-root"),
                            require_triage=True, taxonomy_path=_tri_tax)
    expect("triage: --taxonomy override verifies against the named file (%r)" % _t_over,
           _t_over == [])

    # Fallback-parser parity: the same defects are caught without PyYAML.
    expect("triage: fallback parser flags a mismatched digest",
           any("does not match the taxonomy on disk" in p
               for p in validate(_mini_yaml(_v3_manifest(
                   _triage_block("sha256:" + "c" * 64))),
                   repo_root=_tri_root, require_triage=True)))

    # --- v3.9.0: a null taxonomy_digest says what to do; config-disabled FULL is the
    # one record a null digest is accepted for. ---
    def _null_block(pid, tier="FULL", extra=""):
        return ("triage:\n  tier: %s\n  pre_eval_id: %s\n  taxonomy_digest: null\n"
                '  decided_at: "2026-10-21T09:00:00Z"\n%s' % (tier, pid, extra))

    _nd_root = _tf3.mkdtemp(prefix="cv-v386-nulldigest-")
    _t_nd = validate_text(_v3_manifest(_null_block("2026-10-21T090000Z-x-a1b2")),
                          repo_root=_nd_root, require_triage=True)
    expect("triage: null digest without a taxonomy names the file, /v:init, /v:onboard "
           "and the re-triage (%r)" % _t_nd,
           any("missing required field 'taxonomy_digest'" in p and DEFAULT_TAXONOMY_REL in p
               and "/v:init" in p and "/v:onboard" in p and "re-run /v:triage" in p
               for p in _t_nd))
    _t_nd2 = validate_text(_v3_manifest(_null_block("2026-10-21T090000Z-x-a1b2")),
                           repo_root=_tri_root, require_triage=True)
    expect("triage: null digest once the taxonomy exists says the record predates it",
           any("missing required field 'taxonomy_digest'" in p and "predates" in p
               and "re-run /v:triage" in p for p in _t_nd2))

    _pe = _sibling("compound-v-preeval.py")
    expect("triage: the disabled-record flag is spelled as the producer spells it",
           _pe is not None and _pe.DISABLED_BY_CONFIG_FLAG == TRIAGE_DISABLED_FLAG)
    _dis_root = _tf3.mkdtemp(prefix="cv-v386-disabled-")
    os.makedirs(os.path.join(_dis_root, ".claude"), exist_ok=True)
    _dis_cfg = os.path.join(_dis_root, ".claude", "compound-v.json")
    with open(_dis_cfg, "w") as _fh:
        _fh.write('{"pre_eval": {"enabled": false}}\n')
    _dres = _pe.triage_request("add a booking page", repo=_dis_root, session_id="s",
                               record_disabled=True) if _pe is not None else {}
    _dpid = _dres.get("pre_eval_id") or "2026-10-21T090000Z-missing-a1b2"
    _dis_ok = "  disabled_by_config: true\n"
    _t_dis = validate_text(_v3_manifest(_null_block(_dpid, extra=_dis_ok)),
                           repo_root=_dis_root, require_triage=True)
    expect("triage: a config-disabled FULL record is accepted while disabled (%r)" % _t_dis,
           _t_dis == [])
    expect("triage: fallback parser agrees on the config-disabled block",
           validate(_mini_yaml(_v3_manifest(_null_block(_dpid, extra=_dis_ok))),
                    repo_root=_dis_root, require_triage=True) == [])
    _t_dis_tier = validate_text(_v3_manifest(_null_block(_dpid, tier="SCOPED",
                                                         extra=_dis_ok)),
                                repo_root=_dis_root, require_triage=True)
    expect("triage: config-disabled with a tier other than FULL is refused",
           any("requires tier FULL" in p for p in _t_dis_tier))
    _t_dis_dig = validate_text(_v3_manifest(_triage_block(_tri_digest, tier="FULL",
                                                          pre_eval_id=_dpid,
                                                          extra=_dis_ok)),
                               repo_root=_dis_root, require_triage=True)
    expect("triage: config-disabled with a non-null digest is refused",
           any("requires a null taxonomy_digest" in p for p in _t_dis_dig))
    _t_dis_norec = validate_text(_v3_manifest(_null_block("2026-10-21T090000Z-none-a1b2",
                                                          extra=_dis_ok)),
                                 repo_root=_dis_root, require_triage=True)
    expect("triage: config-disabled without the committed record is refused",
           any("could not be read" in p for p in _t_dis_norec))
    _t_dis_bad = validate_text(_v3_manifest(_null_block(_dpid, extra=(
        "  disabled_by_config: \"yes\"\n"))), repo_root=_dis_root, require_triage=True)
    expect("triage: disabled_by_config must be literally true",
           any("must be true when present" in p for p in _t_dis_bad))
    _drec_path = os.path.join(_dis_root, PRE_EVAL_DIR_REL, _dpid + ".json")
    _drec_bytes = open(_drec_path, "rb").read() if os.path.isfile(_drec_path) else b"{}"
    _drec = json.loads(_drec_bytes.decode("utf-8"))
    with open(_drec_path, "w") as _fh:
        json.dump(dict(_drec, localization=dict(_drec.get("localization") or {}, flags=[])),
                  _fh)
    _t_dis_plain = validate_text(_v3_manifest(_null_block(_dpid, extra=_dis_ok)),
                                 repo_root=_dis_root, require_triage=True)
    expect("triage: an ordinary null-digest FULL record cannot claim config-disabled",
           any("is not a config-disabled FULL record" in p for p in _t_dis_plain)
           and any("fails its own digest" in p for p in _t_dis_plain))
    with open(_drec_path, "wb") as _fh:
        _fh.write(_drec_bytes)
    with open(_dis_cfg, "w") as _fh:
        _fh.write('{"pre_eval": {"enabled": true}}\n')
    _t_dis_on = validate_text(_v3_manifest(_null_block(_dpid, extra=_dis_ok)),
                              repo_root=_dis_root, require_triage=True)
    expect("triage: the config-disabled record is refused once pre_eval is enabled again",
           any("pre_eval.enabled is not false" in p for p in _t_dis_on))
    os.remove(_dis_cfg)
    _t_dis_nocfg = validate_text(_v3_manifest(_null_block(_dpid, extra=_dis_ok)),
                                 repo_root=_dis_root, require_triage=True)
    expect("triage: no project config means the stage is on — refused",
           any("pre_eval.enabled is not false" in p for p in _t_dis_nocfg))
    import shutil as _shutil_386
    _shutil_386.rmtree(_nd_root, ignore_errors=True)
    _shutil_386.rmtree(_dis_root, ignore_errors=True)

    # --- v3.4.1: triage.flavor scoped_plus + the cross-model receipt ---
    # SCOPED+ is the band that says "small edit, sensitive path". It buys back the
    # two reviews plain SCOPED skips, and the validator refuses to take either on
    # trust: the deep in-harness reviewer is DECLARED in the manifest, so it is
    # checked before dispatch; the cross-model second opinion is EVIDENCE that does
    # not exist yet at that point, so it is checked afterwards, from its receipt.
    _DEEP_REVIEW_JOB = """  - id: review-v3
    title: "Review Gate"
    type: review
    backend: claude
    tier: deep
    effort: high
    isolation: direct
    run: serial
    depends_on: [task-1-v3]
    write_allowed: [docs/superpowers/dogfood/**]
    read_allowed: ["**"]
    acceptance: ["verdict written"]
"""
    _SP = "  flavor: scoped_plus\n"

    # 1. scoped_plus WITHOUT the deep Claude review job → violation naming the rule.
    _f_bare = validate_text(_v3_manifest(_triage_block(_tri_digest, extra=_SP)),
                            repo_root=_tri_root, require_triage=True)
    expect("triage.flavor: scoped_plus without a deep Claude review job is refused",
           any("scoped_plus' requires a review job" in p for p in _f_bare))

    # 2. WITH it → valid. The job is type/tier/backend-declared, never guessed from
    #    prose: a standard-tier one does not satisfy the rule.
    _f_ok = validate_text(
        _v3_manifest(_triage_block(_tri_digest, extra=_SP)) + _DEEP_REVIEW_JOB,
        repo_root=_tri_root, require_triage=True)
    expect("triage.flavor: scoped_plus with a deep Claude review job is valid (%r)"
           % _f_ok, _f_ok == [])
    _f_shallow = validate_text(
        _v3_manifest(_triage_block(_tri_digest, extra=_SP))
        + _DEEP_REVIEW_JOB.replace("tier: deep", "tier: standard"),
        repo_root=_tri_root, require_triage=True)
    expect("triage.flavor: a standard-tier review job does not satisfy the rule",
           any("scoped_plus' requires a review job" in p for p in _f_shallow))

    # 3. An out-of-enum flavor is a violation — flavor is a band, not free text.
    _f_bad = validate_text(
        _v3_manifest(_triage_block(_tri_digest, extra="  flavor: spicy\n")),
        repo_root=_tri_root, require_triage=True)
    expect("triage.flavor: unknown value caught",
           any("triage.flavor 'spicy' invalid" in p for p in _f_bad))
    # ...and `flavor` is ALLOWED rather than merely tolerated: an absent flavor stays
    # valid, and a near-miss key still fails the unknown-key walk.
    expect("triage: absent flavor stays valid (the key is optional)",
           validate_text(_v3_manifest(_triage_block(_tri_digest)),
                         repo_root=_tri_root, require_triage=True) == [])
    expect("triage: 'flavour' is still an unknown key (the walk reads ALLOWED_KEYS)",
           any("unknown key 'flavour'" in p for p in validate_text(
               _v3_manifest(_triage_block(_tri_digest,
                                          extra="  flavour: scoped_plus\n")),
               repo_root=_tri_root, require_triage=True)))

    # 4/5. --require-cross-model-receipt: the SCOPED+ second opinion, verified from
    # the file rather than believed. The receipt is sealed with the SAME shared
    # primitive the producer seals it with, so an edit after sealing is detectable.
    _cm_manifest = (_v3_manifest(_triage_block(_tri_digest, extra=_SP))
                    + _DEEP_REVIEW_JOB)
    _cm_dir = _tf3.mkdtemp(prefix="cv-cross-model-")

    def _cm_write(name, **over):
        body = {
            "run_id": "2026-09-01-v3",
            "pre_eval_id": "2026-09-01T101500Z-v3-a1b2",
            "diff_digest": "sha256:" + "a" * 64,
            "reviewer_backend": "codex",
            "reviewer_model": "gpt-5.6-sol",
            "cross_model": True,
            "produced_at": "2026-09-03T04:00:00Z",
            "review": {
                "verdict": "concerns",
                "summary": "One real objection, one blind spot checked.",
                "findings": [],
                "blind_spots_checked": ["partition disjointness"],
            },
        }
        body.update(over)
        if _tax_mod3 is not None:
            body["digest"] = _tax_mod3.record_digest(body, exclude_field="digest")
        full = os.path.join(_cm_dir, name)
        with open(full, "w", encoding="utf-8") as _fh:
            json.dump(body, _fh)
        return full

    _cm_good = _cm_write("good.json")
    _r_good = validate_text(_cm_manifest, repo_root=_tri_root, require_triage=True,
                            cross_model_receipt=_cm_good)
    expect("cross-model-receipt: a sealed, bound receipt validates (%r)" % _r_good,
           _r_good == [])
    # An advisory 'concerns' verdict is NOT a violation — the orchestrator arbitrates.
    expect("cross-model-receipt: a 'concerns' verdict is advisory, not a violation",
           not any("verdict" in p for p in _r_good))

    _r_absent = validate_text(_cm_manifest, repo_root=_tri_root, require_triage=True,
                              cross_model_receipt=os.path.join(_cm_dir, "nope.json"))
    expect("cross-model-receipt: a MISSING receipt fails closed",
           any("could not be read" in p for p in _r_absent))

    # Tampered after sealing: the bytes changed, the self-digest did not.
    _cm_tampered = os.path.join(_cm_dir, "tampered.json")
    with open(_cm_good, "r", encoding="utf-8") as _fh:
        _t_obj = json.load(_fh)
    _t_obj["diff_digest"] = "sha256:" + "b" * 64
    with open(_cm_tampered, "w", encoding="utf-8") as _fh:
        json.dump(_t_obj, _fh)
    _r_tamper = validate_text(_cm_manifest, repo_root=_tri_root, require_triage=True,
                              cross_model_receipt=_cm_tampered)
    expect("cross-model-receipt: self-digest mismatch caught (edited after sealing)",
           any("self-digest mismatch" in p for p in _r_tamper))

    # A sealed receipt over a DIFFERENT diff than the one the caller handed the
    # reviewer — the stale-replay case --expected-diff-digest exists for.
    _r_stale = validate_text(_cm_manifest, repo_root=_tri_root, require_triage=True,
                             cross_model_receipt=_cm_good,
                             expected_diff_digest="sha256:" + "c" * 64)
    expect("cross-model-receipt: diff_digest != the sealed patch caught (stale replay)",
           any("stale-replay" in p for p in _r_stale))

    # The three binding fields, each independently.
    _r_run = validate_text(_cm_manifest, repo_root=_tri_root, require_triage=True,
                           cross_model_receipt=_cm_write("wrongrun.json",
                                                         run_id="2026-01-01-other"))
    expect("cross-model-receipt: run_id binding enforced",
           any("run_id '2026-01-01-other' != manifest run_id" in p for p in _r_run))
    _r_pid = validate_text(_cm_manifest, repo_root=_tri_root, require_triage=True,
                           cross_model_receipt=_cm_write("wrongpid.json",
                                                         pre_eval_id="someone-elses"))
    expect("cross-model-receipt: pre_eval_id binding enforced",
           any("pre_eval_id 'someone-elses' !=" in p for p in _r_pid))
    _r_dd = validate_text(_cm_manifest, repo_root=_tri_root, require_triage=True,
                          cross_model_receipt=_cm_write("baddigest.json",
                                                        diff_digest="deadbeef"))
    expect("cross-model-receipt: malformed diff_digest caught",
           any("diff_digest 'deadbeef' is malformed" in p for p in _r_dd))

    # Schema shape: an unrecognised reviewer_backend is refused (enum), and an
    # unknown envelope field is a violation (additionalProperties: false).
    _r_fam = validate_text(_cm_manifest, repo_root=_tri_root, require_triage=True,
                           cross_model_receipt=_cm_write("claudereview.json",
                                                         reviewer_backend="claude"))
    expect("cross-model-receipt: an unrecognised reviewer_backend is refused",
           any("reviewer_backend must be one of" in p for p in _r_fam))

    # v3.6: reviewer_backend 'claude-advisor' beside 'codex', gated by `cross_model`.
    _r_advisor_ok = validate_text(
        _cm_manifest, repo_root=_tri_root, require_triage=True,
        cross_model_receipt=_cm_write("advisor-ok.json",
                                      reviewer_backend="claude-advisor",
                                      reviewer_model="claude-opus-4-5",
                                      cross_model=False))
    expect("cross-model-receipt: claude-advisor + cross_model:false is ACCEPTED "
           "(%r)" % _r_advisor_ok, _r_advisor_ok == [])
    expect("cross-model-receipt: claude-advisor + cross_model:false WARNs "
           "SECOND_OPINION_SAME_FAMILY",
           any("same-family" in w
               for w in cross_model_receipt_advisories(
                   {"reviewer_backend": "claude-advisor", "cross_model": False})))
    expect("cross-model-receipt: codex + cross_model:true never warns "
           "SECOND_OPINION_SAME_FAMILY",
           cross_model_receipt_advisories(
               {"reviewer_backend": "codex", "cross_model": True}) == [])

    _r_advisor_lie = validate_text(
        _cm_manifest, repo_root=_tri_root, require_triage=True,
        cross_model_receipt=_cm_write("advisor-lie.json",
                                      reviewer_backend="claude-advisor",
                                      reviewer_model="claude-opus-4-5",
                                      cross_model=True))
    expect("cross-model-receipt: claude-advisor + cross_model:true is REFUSED "
           "(disagreement)",
           any("disagrees with reviewer_backend" in p for p in _r_advisor_lie))

    _r_codex_lie = validate_text(
        _cm_manifest, repo_root=_tri_root, require_triage=True,
        cross_model_receipt=_cm_write("codex-lie.json", cross_model=False))
    expect("cross-model-receipt: codex + cross_model:false is REFUSED "
           "(disagreement)",
           any("disagrees with reviewer_backend" in p for p in _r_codex_lie))

    _r_unknown_backend = validate_text(
        _cm_manifest, repo_root=_tri_root, require_triage=True,
        cross_model_receipt=_cm_write("unknown-backend.json",
                                      reviewer_backend="gemini",
                                      cross_model=True))
    expect("cross-model-receipt: an unknown backend ('gemini') is refused",
           any("reviewer_backend must be one of" in p for p in _r_unknown_backend))
    _r_extra = validate_text(_cm_manifest, repo_root=_tri_root, require_triage=True,
                             cross_model_receipt=_cm_write("extra.json", note="hi"))
    expect("cross-model-receipt: unknown envelope field caught",
           any("unknown field 'note'" in p for p in _r_extra))
    # The NESTED review is checked against schemas/plan-review.schema.json.
    _r_review = validate_text(
        _cm_manifest, repo_root=_tri_root, require_triage=True,
        cross_model_receipt=_cm_write("badreview.json",
                                      review={"verdict": "lgtm", "summary": "s",
                                              "findings": [],
                                              "blind_spots_checked": []}))
    expect("cross-model-receipt: the nested review is validated against plan-review",
           any("receipt.review.verdict" in p for p in _r_review))

    # --- v3.0 Feature B2: test_contract + per-job test_scope ---
    # Both are OPTIONAL and unflagged: absent ⇒ `test_scope: full`, which is what every
    # manifest committed before 3.0 relies on.
    _CONTRACT_OK = ('test_contract:\n'
                    '  floor_command: "bash tests/test-epic-goal-stop.sh"\n'
                    '  full_command: "bash scripts/run-all-tests.sh"\n'
                    '  impacted_map:\n'
                    '    - when: "scripts/compound-v-*.py"\n'
                    '      run: "python3 {path} --selftest"\n')
    expect("test_contract: absent block + absent test_scope stays valid",
           validate_text(_v3_manifest()) == [])
    _c_ok = validate_text(_v3_manifest(contract_block=_CONTRACT_OK,
                                       job_line="    test_scope: impacted\n"))
    expect("test_contract: well-formed contract + test_scope: impacted valid (%r)" % _c_ok,
           _c_ok == [])
    for _sc in VALID_TEST_SCOPES:
        _r = validate_text(_v3_manifest(contract_block=_CONTRACT_OK,
                                        job_line="    test_scope: %s\n" % _sc))
        expect("test_contract: test_scope %s accepted (%r)" % (_sc, _r), _r == [])
    _c_enum = validate_text(_v3_manifest(contract_block=_CONTRACT_OK,
                                         job_line="    test_scope: some\n"))
    expect("test_contract: out-of-enum test_scope caught",
           any("test_scope 'some' invalid" in p for p in _c_enum))

    # impacted_map entries: `when` and `run` are both mandatory.
    _c_nowhen = validate_text(_v3_manifest(contract_block=(
        'test_contract:\n  floor_command: "f"\n  full_command: "F"\n'
        '  impacted_map:\n    - run: "python3 {path} --selftest"\n')))
    expect("test_contract: impacted_map entry without 'when' caught",
           any("impacted_map[0] missing required field 'when'" in p for p in _c_nowhen))
    _c_norun = validate_text(_v3_manifest(contract_block=(
        'test_contract:\n  floor_command: "f"\n  full_command: "F"\n'
        '  impacted_map:\n    - when: "scripts/*.py"\n')))
    expect("test_contract: impacted_map entry without 'run' caught",
           any("impacted_map[0] missing required field 'run'" in p for p in _c_norun))
    _c_scalar = validate_text(_v3_manifest(contract_block=(
        'test_contract:\n  floor_command: "f"\n  full_command: "F"\n'
        '  impacted_map:\n    - "scripts/*.py"\n')))
    expect("test_contract: non-mapping impacted_map entry caught",
           any("impacted_map[0] must be a mapping" in p for p in _c_scalar))
    _c_mapkeys = validate_text(_v3_manifest(contract_block=(
        'test_contract:\n  floor_command: "f"\n  full_command: "F"\n'
        '  impacted_map:\n    - when: "scripts/*.py"\n      run: "x"\n      why: "y"\n')))
    expect("test_contract: unknown impacted_map key caught",
           any("impacted_map[0] has unknown key 'why'" in p for p in _c_mapkeys))
    _c_maplist = validate_text(_v3_manifest(contract_block=(
        'test_contract:\n  floor_command: "f"\n  full_command: "F"\n'
        '  impacted_map: "scripts/*.py"\n')))
    expect("test_contract: non-list impacted_map caught",
           any("test_contract.impacted_map must be a list" in p for p in _c_maplist))
    _c_notmap = validate_text(_v3_manifest(contract_block='test_contract: "pytest"\n'))
    expect("test_contract: non-mapping test_contract caught",
           any("'test_contract' must be a mapping" in p for p in _c_notmap))
    _c_unknown = validate_text(_v3_manifest(contract_block=(
        'test_contract:\n  floor_command: "f"\n  full_command: "F"\n  floor_cmd: "f"\n')))
    expect("test_contract: unknown test_contract key caught",
           any("test_contract has unknown key 'floor_cmd'" in p for p in _c_unknown))

    # timeout_s: an optional bound on how long test_contract commands may run.
    _c_timeout_ok = validate_text(_v3_manifest(contract_block=(
        'test_contract:\n  floor_command: "f"\n  full_command: "F"\n'
        '  timeout_s: 480\n')))
    expect("test_contract: timeout_s 480 accepted (%r)" % _c_timeout_ok,
           _c_timeout_ok == [])
    for _bad_timeout in (0, -1, 541, "true", "480"):
        _tval_yaml = ('"%s"' % _bad_timeout if isinstance(_bad_timeout, str)
                      else str(_bad_timeout))
        _c_timeout_bad = validate_text(_v3_manifest(contract_block=(
            'test_contract:\n  floor_command: "f"\n  full_command: "F"\n'
            '  timeout_s: %s\n' % _tval_yaml)))
        expect("test_contract: timeout_s %r refused (%r)"
               % (_bad_timeout, _c_timeout_bad),
               any("test_contract.timeout_s must be an integer" in p
                   for p in _c_timeout_bad))
    _c_timeout_true = validate_text(_v3_manifest(contract_block=(
        'test_contract:\n  floor_command: "f"\n  full_command: "F"\n'
        '  timeout_s: true\n')))
    expect("test_contract: timeout_s true (bool) refused (%r)" % _c_timeout_true,
           any("test_contract.timeout_s must be an integer" in p
               for p in _c_timeout_true))

    # floor_only must never resolve to running NOTHING — the whole point of a floor.
    _c_floor_empty = validate_text(_v3_manifest(
        contract_block='test_contract:\n  floor_command: ""\n  full_command: "F"\n',
        job_line="    test_scope: floor_only\n"))
    expect("test_contract: floor_only with an EMPTY floor_command caught",
           any("floor_only" in p and "floor_command" in p for p in _c_floor_empty))
    _c_floor_absent = validate_text(_v3_manifest(
        job_line="    test_scope: floor_only\n"))
    expect("test_contract: floor_only with NO test_contract at all caught",
           any("floor_only" in p and "floor_command" in p for p in _c_floor_absent))
    _c_floor_ok = validate_text(_v3_manifest(
        contract_block='test_contract:\n  floor_command: "bash tests/x.sh"\n'
                       '  full_command: "F"\n',
        job_line="    test_scope: floor_only\n"))
    expect("test_contract: floor_only with a real floor_command valid (%r)" % _c_floor_ok,
           _c_floor_ok == [])
    # An unmapped path resolves to full_command, so `impacted` needs one to exist.
    _c_imp_nofull = validate_text(_v3_manifest(
        contract_block='test_contract:\n  floor_command: "f"\n',
        job_line="    test_scope: impacted\n"))
    expect("test_contract: impacted without a full_command caught (unmapped ⇒ full)",
           any("impacted" in p and "full_command" in p for p in _c_imp_nofull))

    # Fallback-parser parity for the contract half.
    expect("test_contract: fallback parser flags a floor_only with no floor_command",
           any("floor_only" in p for p in validate(_mini_yaml(_v3_manifest(
               job_line="    test_scope: floor_only\n")))))

    # --- v3.4.8 Task B: top-level `retry` block ---
    _r_absent = validate_text(_v3_manifest())
    expect("retry: absent block stays valid (%r)" % _r_absent, _r_absent == [])

    _r_ok = validate_text(_v3_manifest(
        retry_block="retry:\n  max_attempts: 2\n  escalate_reviewer: true\n"))
    expect("retry: well-formed block valid (%r)" % _r_ok, _r_ok == [])

    for _ma in (1, 2, 3):
        _r_ma_ok = validate_text(_v3_manifest(
            retry_block="retry:\n  max_attempts: %d\n" % _ma))
        expect("retry: max_attempts %d accepted (%r)" % (_ma, _r_ma_ok),
               _r_ma_ok == [])

    for _bad_ma in (0, 4, "3", -1):
        _ma_yaml = '"%s"' % _bad_ma if isinstance(_bad_ma, str) else str(_bad_ma)
        _r_ma_bad = validate_text(_v3_manifest(
            retry_block="retry:\n  max_attempts: %s\n" % _ma_yaml))
        expect("retry: max_attempts %r refused (%r)" % (_bad_ma, _r_ma_bad),
               any("retry.max_attempts must be an integer between 1 and 3" in p
                   for p in _r_ma_bad))

    _r_ma_bool = validate_text(_v3_manifest(
        retry_block="retry:\n  max_attempts: true\n"))
    expect("retry: max_attempts true (bool) refused (%r)" % _r_ma_bool,
           any("retry.max_attempts must be an integer between 1 and 3" in p
               for p in _r_ma_bool))

    for _er_bad in (1, "true", "yes"):
        _er_yaml = '"%s"' % _er_bad if isinstance(_er_bad, str) else str(_er_bad)
        _r_er_bad = validate_text(_v3_manifest(
            retry_block="retry:\n  escalate_reviewer: %s\n" % _er_yaml))
        expect("retry: escalate_reviewer %r refused (%r)" % (_er_bad, _r_er_bad),
               any("retry.escalate_reviewer must be a boolean" in p
                   for p in _r_er_bad))

    _r_er_ok = validate_text(_v3_manifest(
        retry_block="retry:\n  escalate_reviewer: false\n"))
    expect("retry: escalate_reviewer false accepted (%r)" % _r_er_ok, _r_er_ok == [])

    _r_unknown = validate_text(_v3_manifest(
        retry_block="retry:\n  max_attempts: 1\n  giveup: true\n"))
    expect("retry: unknown key caught (%r)" % _r_unknown,
           any("retry has unknown key 'giveup'" in p for p in _r_unknown))

    _r_notmap = validate_text(_v3_manifest(retry_block='retry: "twice"\n'))
    expect("retry: non-mapping retry caught (%r)" % _r_notmap,
           any("'retry' must be a mapping" in p for p in _r_notmap))

    # Fallback-parser parity for retry.
    _r_fallback = validate(_mini_yaml(_v3_manifest(
        retry_block="retry:\n  max_attempts: 5\n")))
    expect("retry: fallback parser flags an out-of-range max_attempts",
           any("retry.max_attempts must be an integer between 1 and 3" in p
               for p in _r_fallback))

    # --- v3.4.17: `global_constraints` + per-job `interfaces` ---------------- #
    # The two fields Superpowers 6.2.0's writing-plans added for isolated
    # implementers. ABSENT-VALID is the first row and the load-bearing one: every
    # manifest materialized from a pre-6.2.0 plan carries neither key.
    _gc_absent = validate_text(_v3_manifest())
    expect("6.2.0 fields: both absent stays valid (%r)" % _gc_absent,
           _gc_absent == [])

    _GC_OK = ('global_constraints:\n'
              '  - "Python 3.9-safe, stdlib only"\n'
              '  - "No new runtime dependency"\n')
    _IFACE_OK = ('    interfaces:\n'
                 '      consumes:\n'
                 '        - "load_yaml(text) -> dict"\n'
                 '      produces:\n'
                 '        - "validate(manifest) -> list[str]"\n')

    _gc_ok = validate_text(_v3_manifest(constraints_block=_GC_OK,
                                        job_line=_IFACE_OK))
    expect("6.2.0 fields: both present and well-formed valid (%r)" % _gc_ok,
           _gc_ok == [])

    _gc_only = validate_text(_v3_manifest(constraints_block=_GC_OK))
    expect("global_constraints: alone (no interfaces) valid (%r)" % _gc_only,
           _gc_only == [])

    _if_only = validate_text(_v3_manifest(job_line=_IFACE_OK))
    expect("interfaces: alone (no global_constraints) valid (%r)" % _if_only,
           _if_only == [])

    # Either interfaces key may be absent: a first task consumes nothing, a last
    # task produces nothing anyone else reads.
    for _half, _yaml_half in (
            ("consumes only",
             '    interfaces:\n      consumes:\n        - "f(x) -> y"\n'),
            ("produces only",
             '    interfaces:\n      produces:\n        - "g(x) -> y"\n'),
            ("empty mapping", '    interfaces: {}\n')):
        _if_half = validate_text(_v3_manifest(job_line=_yaml_half))
        expect("interfaces: %s accepted (%r)" % (_half, _if_half),
               _if_half == [])

    # An empty list is the absent case written longhand — not a violation.
    _gc_empty = validate_text(_v3_manifest(
        constraints_block="global_constraints: []\n"))
    expect("global_constraints: empty list accepted (%r)" % _gc_empty,
           _gc_empty == [])

    # A NULL VALUE IS NOT ABSENT (cross-model review r1, finding 6). A bare
    # `global_constraints:` / `interfaces:` / `consumes:` line parses to None in
    # BOTH parsers (verified), and reading that as "absent" let a materializer
    # write the key, fail to fill it, and validate clean — with every implementer
    # prompt silently losing the field. Only a MISSING key is absent.
    _gc_null = validate_text(_v3_manifest(
        constraints_block="global_constraints:\n"))
    expect("global_constraints: explicit null REFUSED, not read as absent (%r)"
           % _gc_null,
           any("'global_constraints' must be a list of strings" in p
               for p in _gc_null))

    _if_null = validate_text(_v3_manifest(job_line="    interfaces:\n"))
    expect("interfaces: explicit null REFUSED, not read as absent (%r)" % _if_null,
           any("interfaces must be a mapping with keys consumes/produces" in p
               for p in _if_null))

    for _nk in ("consumes", "produces"):
        _if_knull = validate_text(_v3_manifest(
            job_line="    interfaces:\n      %s:\n" % _nk))
        expect("interfaces.%s: explicit null REFUSED (%r)" % (_nk, _if_knull),
               any("interfaces.%s must be a list of strings" % _nk in p
                   for p in _if_knull))

    # Fallback-parser parity for the null case: the subset parser yields None for
    # a bare key too, so the machine WITHOUT PyYAML must refuse it identically.
    _gc_null_fb = validate(_mini_yaml(_v3_manifest(
        constraints_block="global_constraints:\n",
        job_line="    interfaces:\n      consumes:\n")))
    expect("null values: fallback parser refuses both, same messages",
           any("'global_constraints' must be a list of strings" in p
               for p in _gc_null_fb)
           and any("interfaces.consumes must be a list of strings" in p
                   for p in _gc_null_fb))

    # Wrong SHAPES, each with its own message.
    _gc_scalar = validate_text(_v3_manifest(
        constraints_block='global_constraints: "stdlib only"\n'))
    expect("global_constraints: scalar refused (%r)" % _gc_scalar,
           any("'global_constraints' must be a list of strings" in p
               for p in _gc_scalar))

    _gc_map = validate_text(_v3_manifest(
        constraints_block="global_constraints:\n  python: \"3.9\"\n"))
    expect("global_constraints: mapping refused (%r)" % _gc_map,
           any("'global_constraints' must be a list of strings" in p
               for p in _gc_map))

    for _bad_item, _bad_yaml in (("empty string", '  - ""\n'),
                                 ("boolean", "  - true\n"),
                                 ("integer", "  - 39\n")):
        _gc_bad = validate_text(_v3_manifest(
            constraints_block="global_constraints:\n" + _bad_yaml))
        expect("global_constraints: %s entry refused (%r)" % (_bad_item, _gc_bad),
               any("'global_constraints'[0] must be a non-empty string" in p
                   for p in _gc_bad))

    _if_scalar = validate_text(_v3_manifest(
        job_line='    interfaces: "consumes load_yaml"\n'))
    expect("interfaces: scalar refused (%r)" % _if_scalar,
           any("interfaces must be a mapping with keys consumes/produces" in p
               for p in _if_scalar))

    _if_list = validate_text(_v3_manifest(
        job_line='    interfaces:\n      - "load_yaml(text)"\n'))
    expect("interfaces: list refused (%r)" % _if_list,
           any("interfaces must be a mapping with keys consumes/produces" in p
               for p in _if_list))

    _if_unknown = validate_text(_v3_manifest(
        job_line='    interfaces:\n      requires:\n        - "load_yaml"\n'))
    expect("interfaces: unknown key caught (%r)" % _if_unknown,
           any("interfaces has unknown key 'requires'" in p
               for p in _if_unknown))

    _if_str = validate_text(_v3_manifest(
        job_line='    interfaces:\n      consumes: "load_yaml(text)"\n'))
    expect("interfaces: string-valued consumes refused (%r)" % _if_str,
           any("interfaces.consumes must be a list of strings" in p
               for p in _if_str))

    _if_blank = validate_text(_v3_manifest(
        job_line='    interfaces:\n      produces:\n        - ""\n'))
    expect("interfaces: blank produces entry refused (%r)" % _if_blank,
           any("interfaces.produces[0] must be a non-empty string" in p
               for p in _if_blank))

    # Fallback-parser parity for both fields (the machine WITHOUT PyYAML).
    _gc_fb = validate(_mini_yaml(_v3_manifest(constraints_block=_GC_OK,
                                              job_line=_IFACE_OK)))
    expect("6.2.0 fields: fallback parser accepts both (%r)" % _gc_fb,
           _gc_fb == [])
    _gc_fb_bad = validate(_mini_yaml(_v3_manifest(
        job_line='    interfaces:\n      requires:\n        - "x"\n')))
    expect("6.2.0 fields: fallback parser flags an unknown interfaces key",
           any("interfaces has unknown key 'requires'" in p
               for p in _gc_fb_bad))

    # The committed audit trail: every run manifest + the shipped example must still
    # validate WITHOUT the flag. This is the bootstrap exemption, and it is only honest
    # because /v:dispatch passes --require-triage on every live dispatch.
    _repo3 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _hist = sorted(_glob3.glob(os.path.join(_repo3, "docs", "superpowers", "execution",
                                          "*", "manifest.yaml")))
    _hist.append(os.path.join(_repo3, "examples", "manifest.example.yaml"))
    for _hm in _hist:
        if not os.path.isfile(_hm):
            continue
        with open(_hm, "r", encoding="utf-8") as _fh:
            _hp = validate_text(_fh.read(), repo_root=_repo3)
        expect("committed manifest validates without --require-triage: %s (%r)"
               % (os.path.basename(os.path.dirname(_hm)), _hp), _hp == [])

    # --- ADVISORIES: the memory-only lane (v3.5.0, Codex round-1 #8) -----------
    # A job whose whole lane is agent memory is refused as `no_work` the moment the
    # agent has nothing durable to save, which pressures it to invent an entry. The
    # advisory says so; it must NEVER become a violation, because pairing the glob
    # with a real output lane is the author's call, not the validator's.
    def _lane(*globs):
        return _v3_manifest().replace(
            "write_allowed: [src/features/**]",
            "write_allowed: [%s]" % ", ".join(globs))

    # Namespaced form (`superpowers-v-<agent>`) is the recommended shape, so it is
    # the "clean" baseline used below for cases that assert NO advisory fires for
    # a reason unrelated to namespacing.
    _mem_only = _lane('".claude/agent-memory/superpowers-v-spec-reviewer/**"')
    _mem_msgs = advisories_text(_mem_only)
    expect("advisory: a memory-only lane warns", len(_mem_msgs) == 1)
    # Bound-checked on purpose: a regressed detector must FAIL this row, not raise
    # an IndexError that ends the whole selftest before the later rows ever run.
    expect("advisory: the warning names the job and the remedy",
           bool(_mem_msgs) and all(s in _mem_msgs[0] for s in
                                   ("task-1-v3", "memory-only lane", "no_work",
                                    "pair the memory glob", "write_allowed: []")))
    # THE contract: advisory ≠ violation. Same manifest, still valid.
    expect("advisory: a memory-only lane does NOT change the verdict",
           validate_text(_mem_only) == [])
    expect("advisory: memory glob + a real output lane does NOT warn",
           advisories_text(_lane('".claude/agent-memory/superpowers-v-spec-reviewer/**"',
                                 '"docs/superpowers/dogfood/r-1.md"')) == [])
    expect("advisory: an empty write_allowed does NOT warn",
           advisories_text(_lane()) == [])
    expect("advisory: an ordinary code lane does NOT warn",
           advisories_text(_lane('"src/**"')) == [])
    # `in any form`: a detector that knows one spelling detects nothing.
    for _form in ('"./.claude/agent-memory/superpowers-v-spec-reviewer/**"',
                  '".claude/agent-memory/superpowers-v-spec-reviewer"',
                  '".claude/agent-memory-local/spec-reviewer/**"',
                  '"/.claude/agent-memory/superpowers-v-spec-reviewer/MEMORY.md"'):
        expect("advisory: memory-only lane detected as %s" % _form,
               len(advisories_text(_lane(_form))) == 1)
    expect("advisory: a look-alike path outside the memory roots does NOT warn",
           advisories_text(_lane('".claude/agent-memoryX/spec-reviewer/**"')) == [])
    expect("advisory: an unparseable manifest yields no advisory, only violations",
           advisories_text("\tnot: [valid") == [])

    # --- ADVISORIES: MEMORY_LANE_UNNAMESPACED (v3.6) --------------------------
    # A bare (non-namespaced) project-scope memory lane collides with another
    # plugin's memory-bearing agent of the same name; the namespaced form does
    # not. Independent of whether the lane is paired with a real output lane.
    for _bare in ('"./.claude/agent-memory/spec-reviewer/**"',
                  '".claude/agent-memory/spec-reviewer"',
                  '"/.claude/agent-memory/spec-reviewer/MEMORY.md"'):
        _u_msgs = advisories_text(
            _lane(_bare, '"docs/superpowers/dogfood/r-1.md"'))
        expect("advisory: bare memory lane %s raises MEMORY_LANE_UNNAMESPACED"
               % _bare,
               any("not namespaced" in w and "superpowers-v-spec-reviewer" in w
                   for w in _u_msgs))
    expect("advisory: the namespaced lane does NOT raise MEMORY_LANE_UNNAMESPACED",
           not any("not namespaced" in w for w in advisories_text(
               _lane('".claude/agent-memory/superpowers-v-spec-reviewer/**"',
                     '"docs/superpowers/dogfood/r-1.md"'))))
    expect("advisory: the gitignored -local scope never raises "
           "MEMORY_LANE_UNNAMESPACED",
           not any("not namespaced" in w for w in advisories_text(
               _lane('".claude/agent-memory-local/spec-reviewer/**"',
                     '"docs/superpowers/dogfood/r-1.md"'))))
    expect("advisory: MEMORY_LANE_UNNAMESPACED does NOT change the verdict",
           validate_text(_lane('".claude/agent-memory/spec-reviewer/**"',
                               '"docs/superpowers/dogfood/r-1.md"')) == [])
    expect("unnamespaced_agent_memory_name: bare form -> agent name",
           unnamespaced_agent_memory_name(".claude/agent-memory/spec-reviewer/**")
           == "spec-reviewer")
    expect("unnamespaced_agent_memory_name: namespaced form -> None",
           unnamespaced_agent_memory_name(
               ".claude/agent-memory/superpowers-v-spec-reviewer/**") is None)

    # --- ADVISORIES: WAVE_EXCEEDS_RUNTIME_CONCURRENCY (v3.6.4) -----------------
    # The native Workflow runtime's default cap is 16 concurrent agents, and the
    # emitter's own peak-concurrency arithmetic (see the constant's docstring
    # above `wave_concurrency_advisories`) is 1 agent per job in flight at a
    # time — so a wave this wide queues rather than dispatching all at once.
    def _wave_manifest(n_jobs, max_parallel):
        jobs = "\n".join(
            "  - id: task-w%d\n"
            "    title: \"wave job %d\"\n"
            "    type: bounded_crud\n"
            "    backend: claude\n"
            "    tier: standard\n"
            "    effort: medium\n"
            "    isolation: worktree\n"
            "    run: parallel\n"
            "    write_allowed: [src/wave%d/**]\n"
            "    read_allowed: [src/**]\n"
            "    acceptance: [\"builds\"]"
            % (i, i, i)
            for i in range(n_jobs)
        )
        return """
run_id: 2026-09-21-wave
feature: "wave width"
spec_path: docs/superpowers/specs/2026-09-21-wave.md
plan_path: docs/superpowers/plans/2026-09-21-wave.md
audits:
  archaeology: docs/superpowers/archaeology/2026-09-21-wave.md
  domain: docs/superpowers/expert/2026-09-21-wave.md
  library: docs/superpowers/library-audit/2026-09-21-wave.md
routing_stance: balanced
max_parallel: %d
acceptance_criteria:
  - "ships"
jobs:
%s
""" % (max_parallel, jobs)

    _wide = _wave_manifest(17, 20)
    _wide_msgs = advisories_text(_wide)
    expect("advisory: a 17-job single wave raises WAVE_EXCEEDS_RUNTIME_CONCURRENCY",
           any("17 jobs exceeds" in w and "wave 1" in w for w in _wide_msgs))
    expect("advisory: the warning names the runtime default and the env var",
           bool(_wide_msgs) and any(
               "concurrency cap of 16" in w
               and "CLAUDE_CODE_WORKFLOW_MAX_CONCURRENT_AGENTS" in w
               for w in _wide_msgs))
    expect("advisory: WAVE_EXCEEDS_RUNTIME_CONCURRENCY does NOT change the verdict",
           validate_text(_wide) == [])

    _narrow = _wave_manifest(4, 4)
    expect("advisory: a 4-job wave does NOT raise WAVE_EXCEEDS_RUNTIME_CONCURRENCY",
           not any("exceeds" in w and "concurrency cap" in w
                   for w in advisories_text(_narrow)))
    expect("wave-width test manifest (4-job) is itself a clean PASS",
           validate_text(_narrow) == [])

    # exactly-at-the-limit (16) must NOT warn; one over (17) must.
    expect("advisory: exactly 16 jobs in one wave does NOT warn",
           not any("concurrency cap" in w
                   for w in advisories_text(_wave_manifest(16, 20))))

    # --- v3.6: provision_command / provision_timeout_s -------------------------
    def _prov(extra):
        return _v3_manifest() + extra

    expect("provision: a valid command + timeout pair is PASS",
           validate_text(_prov("provision_command: \"npm ci\"\n"
                               "provision_timeout_s: 600\n")) == [])
    expect("provision: absent is valid (no key at all)",
           validate_text(_v3_manifest()) == [])
    expect("provision: provision_command 3 (not a string) is FAIL",
           any("provision_command" in p for p in
               validate_text(_prov("provision_command: 3\n"))))
    expect("provision: provision_command \"\" (empty) is FAIL",
           any("provision_command" in p for p in
               validate_text(_prov('provision_command: ""\n'))))
    expect("provision: provision_timeout_s 0 is FAIL",
           any("provision_timeout_s" in p for p in
               validate_text(_prov("provision_command: \"npm ci\"\n"
                                   "provision_timeout_s: 0\n"))))
    expect("provision: provision_timeout_s 1801 is FAIL",
           any("provision_timeout_s" in p for p in
               validate_text(_prov("provision_command: \"npm ci\"\n"
                                   "provision_timeout_s: 1801\n"))))
    expect("provision: provision_command with a newline is FAIL",
           any("provision_command" in p for p in
               _validate_provision({"provision_command": "npm ci\nrm -rf /"})))

    # --- issue #22: top-level toolchain_artifacts ------------------------------
    expect("toolchain_artifacts: absent is valid (no key at all)",
           validate_text(_v3_manifest()) == [])
    expect("toolchain_artifacts: a valid list of specific globs is PASS",
           validate_text(_prov(
               'toolchain_artifacts: ["tsconfig.tsbuildinfo", '
               '"node_modules/.vite/**"]\n')) == [])
    expect("toolchain_artifacts: a bare string (not a list) is FAIL",
           any("toolchain_artifacts" in p for p in
               validate_text(_prov('toolchain_artifacts: "x"\n'))))
    expect("toolchain_artifacts: [\"**\"] (catch-all) is FAIL",
           any("toolchain_artifacts" in p and "catch-all" in p for p in
               validate_text(_prov('toolchain_artifacts: ["**"]\n'))))
    expect("toolchain_artifacts: [\"\"] (empty entry) is FAIL",
           any("toolchain_artifacts" in p for p in
               validate_text(_prov('toolchain_artifacts: [""]\n'))))
    expect("toolchain_artifacts: null (bare key) is valid (same absent-vs-null "
           "rule as global_constraints)",
           validate_text(_prov("toolchain_artifacts:\n")) == [])
    # Every other catch-all spelling is refused too, not just bare "**".
    for _glob in ("*", "**/*", "/**", "./**"):
        expect("toolchain_artifacts: %r is a catch-all and FAILS" % _glob,
               any("catch-all" in p for p in _validate_toolchain_artifacts(
                   {"toolchain_artifacts": [_glob]})))
    # A catch-all mixed in with legitimate globs still fails the whole list —
    # one bad entry is enough, the good ones don't dilute it.
    expect("toolchain_artifacts: a catch-all mixed with valid globs still FAILS",
           any("catch-all" in p for p in _validate_toolchain_artifacts(
               {"toolchain_artifacts": ["tsconfig.tsbuildinfo", "**"]})))
    # A newline inside one entry is refused, same single-line discipline as
    # provision_command.
    expect("toolchain_artifacts: an entry with a newline is FAIL",
           any("toolchain_artifacts" in p and "single-line" in p
               for p in _validate_toolchain_artifacts(
                   {"toolchain_artifacts": ["tsconfig.tsbuildinfo\nrm -rf /"]})))
    # A non-string entry (bool/int) is caught by the shared shape check, not the
    # catch-all check crashing on a non-string.
    expect("toolchain_artifacts: a non-string entry (True) is FAIL, not a crash",
           any("toolchain_artifacts" in p for p in _validate_toolchain_artifacts(
               {"toolchain_artifacts": [True]})))

    # The SHIPPED example must not trip the advisory it documents.
    _ex = os.path.join(_repo3, "examples", "manifest.example.yaml")
    if os.path.isfile(_ex):
        with open(_ex, "r", encoding="utf-8") as _fh:
            _ex_warn = advisories_text(_fh.read())
        expect("advisory: examples/manifest.example.yaml raises none (%r)" % _ex_warn,
               _ex_warn == [])

    # v2.9 conditional fast-path suite (on-disk fixtures).
    _selftest_fastpath(expect)

    # --- C2: a `yaml.py` planted beside this script is NOT the parser ---------
    # (eighth review pass, 2026-09-03.) See `_harden_sys_path` at the top of this
    # file. This module reads the document that DEFINES every job's
    # `write_allowed`, and `hooks/lane-guard.sh` loads it by path from a process
    # whose CWD is the worker's own worktree — so both shadowing routes (the
    # script's directory and the CWD) are exercised here at once, with the plant
    # sitting in the directory that is both.
    import shutil as _shutil_c2
    import subprocess as _sp_c2
    import tempfile as _tempfile_c2

    _c2_tmp = _tempfile_c2.mkdtemp(prefix="cv-vm-shadow-")
    try:
        _c2_copy = os.path.join(_c2_tmp, "compound-v-validate-manifest.py")
        _shutil_c2.copy(os.path.abspath(__file__), _c2_copy)
        _shutil_c2.copytree(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "cv_validate"),
                            os.path.join(_c2_tmp, "cv_validate"))
        _c2_mark = os.path.join(_c2_tmp, "hostile-yaml-imported")
        with open(os.path.join(_c2_tmp, "yaml.py"), "w") as _fh_c2:
            _fh_c2.write(
                "open(%r, 'w').write('imported')\n"
                "def safe_load(text):\n"
                "    return {'jobs': [{'id': 'pwned', 'write_allowed': ['**']}]}\n"
                % _c2_mark)

        # The plant is POTENT: an unhardened process in that directory imports it.
        _sp_c2.run([sys.executable, "-B", "-c", "import yaml"], cwd=_c2_tmp,
                   stdout=_sp_c2.DEVNULL, stderr=_sp_c2.DEVNULL)
        expect("shadow: the planted yaml.py IS imported by an unhardened process "
               "(the plant is real)", os.path.exists(_c2_mark))
        if os.path.exists(_c2_mark):
            os.remove(_c2_mark)

        _c2_probe = (
            "import importlib.util, json, sys\n"
            "spec = importlib.util.spec_from_file_location('_cv_vm', sys.argv[1])\n"
            "mod = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(mod)\n"
            "print(json.dumps(mod.load_yaml('jobs:\\n- id: real\\n')))\n"
        )
        _c2_proc = _sp_c2.run(
            [sys.executable, "-B", "-c", _c2_probe, _c2_copy], cwd=_c2_tmp,
            stdout=_sp_c2.PIPE, stderr=_sp_c2.PIPE, universal_newlines=True)
        try:
            _c2_parsed = json.loads(_c2_proc.stdout or "{}")
        except ValueError:
            _c2_parsed = {}
        _c2_jobs = (_c2_parsed or {}).get("jobs") or []
        expect("shadow: the parse is unaffected — the real document is read",
               len(_c2_jobs) == 1 and _c2_jobs[0].get("id") == "real")
        expect("shadow: the planted yaml.py was never imported",
               not os.path.exists(_c2_mark))
    finally:
        _shutil_c2.rmtree(_c2_tmp, ignore_errors=True)

    if failures:
        print("\nSELFTEST FAILED: %d case(s)" % len(failures))
        return 1
    # --- 3.3.0: `type` decides who is a reviewer ---------------------------
    # Dogfood 10: a job TITLED "Writes the thing the reviewer reviews" was refused
    # for not being deep-tier. `integration` and `quality` are in the token list,
    # so ordinary titles were forcing jobs onto Opus by accident.
    expect("a declared review type is a reviewer",
           _is_reviewer({"type": "review", "id": "x", "title": "x"}) is True)
    expect("a docs job whose TITLE mentions a reviewer is NOT one",
           _is_reviewer({"type": "docs", "id": "impl-slice",
                         "title": "Writes the thing the reviewer reviews"}) is False)
    expect("'Add integration tests' is not a reviewer",
           _is_reviewer({"type": "tests_new", "id": "t1",
                         "title": "Add integration tests"}) is False)
    expect("'Refactor the quality metrics' is not a reviewer",
           _is_reviewer({"type": "mechanical_refactor", "id": "q1",
                         "title": "Refactor the quality metrics module"}) is False)
    expect("with NO type, the id/title fallback still catches a reviewer",
           _is_reviewer({"id": "spec-review", "title": "gate"}) is True)
    expect("the fallback matches WORD boundaries, so 'preview' is not 'review'",
           _is_reviewer({"id": "preview-builder",
                         "title": "build the preview"}) is False)
    expect("the fallback does not fire on 'disintegration'",
           _is_reviewer({"id": "d1", "title": "model disintegration study"}) is False)

    print("\nSELFTEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
