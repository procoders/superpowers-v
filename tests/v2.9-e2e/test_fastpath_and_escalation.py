#!/usr/bin/env python3
"""
Compound V v2.9 — Pre-Evaluation & proportionate fast-path END-TO-END acceptance suite
(Task Z1). Drives the REAL merged scripts (subprocess CLI + import-by-path), never a live
model, deterministically, locale-safe (LANG=C forced on every subprocess). Every git fixture
is built in a tempdir OUTSIDE the worktree and torn down.

What it proves (mapped to the spec §0 acceptance criteria):

  * AC-1  — "make button X red" that localizes onto a shared design token → the pre-eval
            engine returns FULL_PIPELINE via hard override #3 (shared_token / a11y / generated),
            with ZERO model calls. Driven through `compound-v-preeval.py --score-only` against
            the SHIPPED `.example.yaml` taxonomy, with a synthetic localization (permitted).
  * AC-11 — a `css-only`-remembered request STILL escalates when the resolved change hits a
            shared-token / a11y surface. remember-my-choice is a harness OFFER-skip only; it can
            never reach the fail-closed overrides. Proven two ways: (a) even when the T3
            classification says `plumbing` (low/low — the exact signal a remembered "css-only"
            choice would carry), an a11y / shared-token localization flag fires override #3 →
            FULL; (b) structurally, `score()` has no `remember` parameter, so the engine is
            physically un-tellable about a remembered choice.
  * AC-3 / AC-7 — a fast-path ACCEPTED run: `compound-v-preeval.py` → FASTPATH_ELIGIBLE record →
            `compound-v-fastpath-materialize.py` materializes a run whose `manifest.yaml` PASSES
            `compound-v-validate-manifest.py --mode pre-dispatch`; then a CLEAN tiny diff on the
            single localized file → `compound-v-postdiff-reclassify.py` does NOT escalate. And a
            diff that touches a sensitive path → `postdiff-reclassify` DOES escalate (the
            ESCALATION_REQUIRED path). Telemetry stays three-event append-only (no back-fill).
  * AC-10 / AC-12 — no fabricated metric: `compound-v-triage-outcomes.py precision` on an empty
            OR below-floor stream reports `status: insufficient` and NEVER a precision number;
            only a genuinely calibrated stream yields a git-derived precision float.

Python 3.9-safe, stdlib only (`unittest` + `subprocess` + `importlib`). Run:

    LANG=C python3 tests/v2.9-e2e/test_fastpath_and_escalation.py            # unittest main
    LANG=C python3 -m unittest tests.v2.9-e2e.test_fastpath_and_escalation   # (dir has a dot)

The suite adapts to each real script's ACTUAL argparse interface (probed from the merged
scripts), not a guessed shape.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


# --------------------------------------------------------------------------- #
# Locate the repo + the merged scripts (this file lives at tests/v2.9-e2e/…).
# --------------------------------------------------------------------------- #
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(REPO_ROOT, "scripts")
EXAMPLE_TAXONOMY = os.path.join(
    REPO_ROOT, ".claude", "compound-v-impact-taxonomy.example.yaml")
PY = sys.executable or "python3"

FASTPATH = "FASTPATH_ELIGIBLE"
FULL = "FULL_PIPELINE"


# --------------------------------------------------------------------------- #
# Subprocess + import helpers. Every subprocess forces LANG=C / LC_ALL=C so the
# suite is locale-invariant regardless of the caller's environment.
# --------------------------------------------------------------------------- #
def _c_env(extra=None):
    env = dict(os.environ)
    env["LANG"] = "C"
    env["LC_ALL"] = "C"
    if extra:
        env.update(extra)
    return env


def run_script(name, *args, cwd=None):
    """Run scripts/<name> with the given args under LANG=C. Returns (rc, stdout, stderr)."""
    proc = subprocess.run(
        [PY, os.path.join(SCRIPTS, name)] + [str(a) for a in args],
        cwd=cwd, env=_c_env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        universal_newlines=True)
    return proc.returncode, proc.stdout, proc.stderr


def run_json(name, *args, cwd=None):
    """Run a script and parse its stdout as JSON (fails the assertion path if not JSON)."""
    rc, out, err = run_script(name, *args, cwd=cwd)
    try:
        data = json.loads(out)
    except ValueError:
        data = None
    return rc, data, out, err


_MOD_CACHE = {}


def import_script(basename, modname):
    """Import a hyphenated script BY PATH (the same importlib pattern the scripts use to reuse
    each other). Lets us inject a deterministic fake localization — no live grep, no model."""
    if basename in _MOD_CACHE:
        return _MOD_CACHE[basename]
    path = os.path.join(SCRIPTS, basename)
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _MOD_CACHE[basename] = mod
    return mod


# --------------------------------------------------------------------------- #
# Git fixture helpers — throwaway repos in $TMPDIR, OUTSIDE this worktree.
# --------------------------------------------------------------------------- #
def git(repo, *args, check=True):
    proc = subprocess.run(["git", "-C", repo] + list(args), env=_c_env(),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True)
    if check and proc.returncode != 0:
        raise AssertionError("git %s failed: %s" % (" ".join(args), proc.stderr.strip()))
    return proc.stdout


def git_init(repo):
    os.makedirs(repo, exist_ok=True)
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "v-e2e@example.com")
    git(repo, "config", "user.name", "V E2E")
    git(repo, "config", "commit.gpgsign", "false")
    return repo


def git_head(repo):
    return git(repo, "rev-parse", "HEAD").strip()


def write_file(repo, rel, content, binary=False):
    p = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    mode = "wb" if binary else "w"
    kw = {} if binary else {"encoding": "utf-8"}
    with open(p, mode, **kw) as fh:
        fh.write(content)
    return p


class _RepoCase(unittest.TestCase):
    """Base case that allocates + cleans a tempdir tree for git fixtures."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="cv29-e2e-")
        # Guard: never let a fixture repo alias this checkout.
        self.assertFalse(os.path.abspath(self._tmp).startswith(os.path.abspath(REPO_ROOT)),
                         "fixture tempdir must live OUTSIDE the worktree")

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def new_repo(self, name="repo"):
        return git_init(os.path.join(self._tmp, name))


# =========================================================================== #
# AC-1 — shared-token "make button red" resolves to FULL via override #3.
# =========================================================================== #
class TestAC1SharedTokenForcesFullPipeline(_RepoCase):

    def test_make_button_red_shared_token_override3(self):
        # Synthetic localization (permitted): "make button X red" resolved onto shared design
        # tokens (fan-out > 1, shared_token flag). Driven through the REAL preeval CLI against
        # the SHIPPED example taxonomy — which carries a sensitive_path_list (safety coverage),
        # so the missing-data short-circuit does NOT pre-empt the override.
        loc = json.dumps({
            "resolved_paths": ["src/ui/button.css", "src/ui/card.css"],
            "fan_out": 2, "flags": ["shared_token"], "confidence": "exact"})
        rc, v, out, err = run_json(
            "compound-v-preeval.py", "--score-only", "--localization-json", loc,
            "--taxonomy", EXAMPLE_TAXONOMY, "--request", "make button X red")
        self.assertEqual(rc, 0, "preeval exited non-zero: %s" % err)
        self.assertIsNotNone(v, "preeval did not emit JSON: %s" % out)
        self.assertEqual(v["decision"], FULL, "shared-token change must be FULL_PIPELINE")
        self.assertEqual(v["override_fired"], 3, "must fire hard override #3 (shared_token/a11y)")
        # AC-3 spirit: a fired Layer-A override needs ZERO model calls.
        self.assertIs(v["needs_t3"], False, "override #3 must not require a T3 model call")


# =========================================================================== #
# AC-11 — remember-my-choice (css-only) never bypasses the fail-closed overrides.
# =========================================================================== #
class TestAC11RememberNeverBypassesOverrides(_RepoCase):

    def _score(self, flags, t3=None):
        loc = json.dumps({"resolved_paths": ["src/ui/button.css"], "fan_out": 1,
                          "flags": flags, "confidence": "exact"})
        argv = ["compound-v-preeval.py", "--score-only", "--localization-json", loc,
                "--taxonomy", EXAMPLE_TAXONOMY, "--request", "make it css-only"]
        if t3:
            argv += ["--t3-category", t3]
        rc, v, out, err = run_json(*argv)
        self.assertEqual(rc, 0, err)
        self.assertIsNotNone(v, out)
        return v

    def test_a11y_surface_escalates_despite_remembered_css_only(self):
        # A user "remembered" this request as css-only → the remembered signal is a low/low
        # (plumbing) classification. But localization reveals it touches an a11y surface.
        # Override #3 STILL fires → FULL. The low T3 classification cannot lower it.
        v = self._score(["is_a11y_state"], t3="plumbing")
        self.assertEqual(v["decision"], FULL)
        self.assertEqual(v["override_fired"], 3,
                         "a11y surface must fail closed even with a remembered low classification")

    def test_shared_token_surface_escalates_despite_remembered_css_only(self):
        v = self._score(["shared_token"], t3="plumbing")
        self.assertEqual(v["decision"], FULL)
        self.assertEqual(v["override_fired"], 3)

    def test_engine_has_no_remember_parameter(self):
        # Structural invariant: the deterministic scorer is physically un-tellable about a
        # remembered choice. remember-my-choice lives entirely in the harness OFFER layer.
        import inspect
        pe = import_script("compound-v-preeval.py", "cv_preeval_ac11")
        params = set(inspect.signature(pe.score).parameters)
        self.assertNotIn("remember", params)
        self.assertFalse(any("remember" in p for p in params),
                         "score() must not accept any remember/skip signal: %s" % params)


# =========================================================================== #
# AC-3 / AC-7 — fast-path accept → valid manifest + clean-diff-no-escalation;
#               sensitive-diff → escalation.
# =========================================================================== #
class TestAC3And7FastPathLifecycle(_RepoCase):

    def _make_eligible(self, repo, request="tweak local button padding",
                       target="src/ui/button.css", ts="2026-07-12T10:16:00Z"):
        """Build a genuine committed FASTPATH_ELIGIBLE pre-eval on a real git repo, using a
        deterministic injected localization (no live grep, no model). Returns the run result."""
        pe = import_script("compound-v-preeval.py", "cv_preeval_ac3")
        # Seed: the shipped taxonomy's minimal twin (carries safety coverage) + the target file.
        write_file(repo, os.path.join(".claude", "compound-v-impact-taxonomy.yaml"),
                   pe._EXAMPLE_TAXONOMY_TEXT)
        write_file(repo, target, ".btn { padding: 4px; }\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "seed: taxonomy + target")

        stream = os.path.join(repo, "docs", "superpowers", "memory", "triage-outcomes.jsonl")
        fake = lambda req, r, taxonomy: {"resolved_paths": [target], "fan_out": 1,
                                         "flags": [], "confidence": "exact"}
        res = pe.run_preeval(request, repo=repo, _localize=fake, ts=ts, stream_path=stream)
        git(repo, "add", "docs/superpowers/pre-eval",
            "docs/superpowers/memory/triage-outcomes.jsonl")
        git(repo, "commit", "-qm", "pre-eval %s" % res["pre_eval_id"])
        return res

    def test_accepted_fastpath_materializes_manifest_that_passes_pre_dispatch(self):
        repo = self.new_repo()
        res = self._make_eligible(repo)
        self.assertEqual(res["decision"], FASTPATH,
                         "trivial single-file CSS change must be FASTPATH_ELIGIBLE")

        mat = import_script("compound-v-fastpath-materialize.py", "cv_mat_ac3")
        out = mat.run_materialize(repo, res["pre_eval_id"],
                                  prompt_text="APPLY: make the button padding 8px.\n")
        self.assertEqual(out["status"], "materialized")

        manifest_full = os.path.join(repo, out["manifest_ref"])
        self.assertTrue(os.path.isfile(manifest_full), "manifest.yaml must be materialized")

        # THE gate — the REAL validator CLI, pre-dispatch mode, must accept it.
        rc, verdict, cli_out, err = run_json(
            "compound-v-validate-manifest.py", "--mode", "pre-dispatch",
            "--repo-root", repo, manifest_full)
        self.assertEqual(rc, 0, "validate --mode pre-dispatch must PASS: %s%s" % (cli_out, err))
        self.assertIsNotNone(verdict, cli_out)
        self.assertEqual(verdict["verdict"], "valid")
        self.assertEqual(verdict["violations"], [])

    def test_clean_fastpath_diff_does_not_escalate(self):
        repo = self.new_repo()
        res = self._make_eligible(repo)
        mat = import_script("compound-v-fastpath-materialize.py", "cv_mat_clean")
        out = mat.run_materialize(repo, res["pre_eval_id"], prompt_text="apply\n")
        self.assertEqual(out["status"], "materialized")

        baseline = git_head(repo)
        # Simulate the fast-path implementer: a clean, tiny edit to the SINGLE localized file.
        write_file(repo, out["write_allowed"], ".btn { padding: 8px; }\n")

        taxonomy = os.path.join(repo, ".claude", "compound-v-impact-taxonomy.yaml")
        rc, result, cli_out, err = run_json(
            "compound-v-postdiff-reclassify.py", "--worktree", repo,
            "--baseline", baseline, "--taxonomy", taxonomy)
        self.assertIsNotNone(result, "%s%s" % (cli_out, err))
        self.assertIs(result["escalate"], False,
                      "a clean tiny CSS diff must NOT escalate: %s" % result.get("reasons"))
        self.assertEqual(result["reasons"], [])
        self.assertEqual(rc, 0, "clean fast-path diff must exit 0 (fast-path holds)")

    def test_sensitive_path_diff_escalates(self):
        repo = self.new_repo()
        # Use the shipped example taxonomy (its sensitive_path_list includes src/auth/**).
        write_file(repo, "src/auth/login.ts", "// base\n")
        write_file(repo, "README.md", "hi\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "base")
        baseline = git_head(repo)
        # A change that touches the sensitive surface.
        write_file(repo, "src/auth/login.ts", "// base\nconst x = 1;\n")

        rc, result, cli_out, err = run_json(
            "compound-v-postdiff-reclassify.py", "--worktree", repo,
            "--baseline", baseline, "--taxonomy", EXAMPLE_TAXONOMY)
        self.assertIsNotNone(result, "%s%s" % (cli_out, err))
        self.assertIs(result["escalate"], True,
                      "a sensitive-path touch must ESCALATE (ESCALATION_REQUIRED path)")
        self.assertTrue(any("sensitive" in r for r in result["reasons"]),
                        "escalation reason must name the sensitive path: %s" % result["reasons"])
        self.assertEqual(rc, 1, "escalation must exit 1")

    def test_shared_token_content_diff_escalates(self):
        # AC-8 flavor via F2: a cosmetically-tiny CSS diff that INTRODUCES a shared token is a
        # high-blast content change → escalate, even though the path pattern alone reads low.
        repo = self.new_repo()
        write_file(repo, "styles/app.css", ".a { color: red; }\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "base")
        baseline = git_head(repo)
        write_file(repo, "styles/app.css", ".a { color: var(--color-primary); }\n")

        rc, result, cli_out, err = run_json(
            "compound-v-postdiff-reclassify.py", "--worktree", repo,
            "--baseline", baseline, "--taxonomy", EXAMPLE_TAXONOMY)
        self.assertIsNotNone(result, "%s%s" % (cli_out, err))
        self.assertIs(result["escalate"], True,
                      "a shared-token content hit must escalate: %s" % result.get("reasons"))


# =========================================================================== #
# AC-10 / AC-12 — no fabricated metric; precision is git-derived or "insufficient".
# =========================================================================== #
class TestAC10And12NoFabricatedMetric(_RepoCase):

    def _stream(self):
        # The triage stream MUST be named triage-outcomes.jsonl (append-only basename guard).
        d = os.path.join(self._tmp, "memory")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, "triage-outcomes.jsonl")

    def _tri(self, *args):
        return run_json("compound-v-triage-outcomes.py", *args)

    def _seed_verified_fastpath_success(self, stream, pid, rid):
        """Write the git-derived evidence the triage counter now requires (round-2 CRIT-2): the run
        state.json (MERGED + a REAL merge-commit SHA) and an approved receipt bound to (pid, rid),
        ALL COMMITTED at HEAD (triage reads committed blobs, not the working tree, and verifies the
        merge SHA is a real commit object). exec_dir is …/execution (two levels up from the stream)."""
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e")

        def _git(*a):
            subprocess.run(["git", "-C", self._tmp] + list(a), env=env, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not os.path.isdir(os.path.join(self._tmp, ".git")):
            _git("init", "-q")
        # An empty base commit gives a REAL merge-commit SHA to reference from state.json.
        _git("commit", "-q", "--allow-empty", "-m", "base")
        merge_sha = subprocess.run(["git", "-C", self._tmp, "rev-parse", "HEAD"],
                                   env=env, capture_output=True, text=True, check=True).stdout.strip()
        exec_dir = os.path.join(os.path.dirname(os.path.dirname(stream)), "execution")
        run = os.path.join(exec_dir, rid)
        os.makedirs(os.path.join(run, "review"), exist_ok=True)
        with open(os.path.join(run, "state.json"), "w", encoding="utf-8") as fh:
            json.dump({"phase": "MERGED", "merge_sha": merge_sha}, fh)
        with open(os.path.join(run, "review", "receipt.json"), "w", encoding="utf-8") as fh:
            json.dump({"verdict": "approved", "run_id": rid, "pre_eval_id": pid}, fh)
        # Commit the state.json + receipt + the (already-appended) stream so all are blobs at HEAD.
        _git("add", "-A")
        _git("commit", "-q", "-m", "evidence")

    def _assert_insufficient_no_number(self, result, raw):
        self.assertEqual(result.get("status"), "insufficient")
        self.assertNotIn("precision", result,
                         "an insufficient stream must NEVER carry a precision number")
        self.assertNotIn("escalation_rate", result)
        # Belt-and-suspenders on the raw text: no fabricated ratio leaks into stdout.
        self.assertNotIn("\"precision\"", raw)

    def test_precision_empty_stream_is_insufficient(self):
        stream = self._stream()
        open(stream, "w").close()  # empty, existing
        rc, result, out, err = self._tri("precision", "--stream", stream)
        self.assertEqual(rc, 0, err)
        self.assertIsNotNone(result, out)
        self._assert_insufficient_no_number(result, out)
        self.assertEqual(result["n"], 0)

    def test_precision_missing_stream_is_insufficient(self):
        # A stream file that does not exist yet must degrade to insufficient, not crash / fabricate.
        stream = self._stream()  # not created
        rc, result, out, err = self._tri("precision", "--stream", stream)
        self.assertEqual(rc, 0, err)
        self.assertIsNotNone(result, out)
        self._assert_insufficient_no_number(result, out)

    def test_precision_below_floor_is_insufficient(self):
        stream = self._stream()
        pid = "2026-07-12T101600Z-x-ab12"
        rid = "fastpath-" + pid
        # Three append-only events joined on pre_eval_id (predicted → bind → actual) — NO back-fill.
        self._tri("predicted", "--pre-eval-id", pid, "--decision", FASTPATH,
                  "--difficulty-band", "low", "--impact-band", "low", "--stream", stream)
        self._tri("bind", "--pre-eval-id", pid, "--run-id", rid, "--stream", stream)
        self._tri("actual", "--pre-eval-id", pid, "--run-id", rid,
                  "--review-result", "approved", "--test-result", "pass", "--stream", stream)
        self._seed_verified_fastpath_success(stream, pid, rid)  # git-derived evidence (HIGH-9)
        # One sample, floor of five → still below the floor → insufficient, no number.
        rc, result, out, err = self._tri("precision", "--stream", stream, "--min-sample", "5")
        self.assertEqual(rc, 0, err)
        self._assert_insufficient_no_number(result, out)
        self.assertEqual(result["n"], 1)
        self.assertEqual(result["min_sample_count"], 5)

    def test_precision_calibrated_stream_reports_git_derived_number(self):
        # Once the floor is met, the metric is a REAL git-derived precision — not fabricated,
        # not a band-midpoint display. This is the counterpart proving "insufficient" is a floor,
        # not a refusal to ever compute.
        stream = self._stream()
        pid = "2026-07-12T101600Z-x-ab12"
        rid = "fastpath-" + pid
        self._tri("predicted", "--pre-eval-id", pid, "--decision", FASTPATH,
                  "--difficulty-band", "low", "--impact-band", "low", "--stream", stream)
        self._tri("bind", "--pre-eval-id", pid, "--run-id", rid, "--stream", stream)
        self._tri("actual", "--pre-eval-id", pid, "--run-id", rid,
                  "--review-result", "approved", "--test-result", "pass", "--stream", stream)
        self._seed_verified_fastpath_success(stream, pid, rid)  # git-derived evidence (HIGH-9)
        rc, result, out, err = self._tri("precision", "--stream", stream, "--min-sample", "1")
        self.assertEqual(rc, 0, err)
        self.assertIsNotNone(result, out)
        self.assertNotIn("status", result, "a calibrated stream must NOT be insufficient")
        self.assertIn("precision", result)
        self.assertIsInstance(result["precision"], (int, float))
        self.assertEqual(result["n"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
