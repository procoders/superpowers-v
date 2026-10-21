"""The command-line entry: argument parsing, verdict output and exit codes."""

import json
import os
import sys

from .fastpath_support import FASTPATH_MODES
from .core import validate_text
from .advisories import cross_model_receipt_advisories, advisories_text
from .selftest import _selftest


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
