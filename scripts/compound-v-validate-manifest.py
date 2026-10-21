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
    "core", "advisories", "selftest_fixtures", "selftest_fastpath", "selftest_blocks",
    "selftest")


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
from cv_validate.selftest_blocks import _selftest_blocks
from cv_validate.selftest import _selftest


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



if __name__ == "__main__":
    sys.exit(main(sys.argv))
