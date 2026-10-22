from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402

from cvcore import scope  # noqa: E402


class ScopeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = helpers.make_repo(Path(self._tmp.name), {
            "src/a.js": "a\n", "README.md": "hello\n", ".gitignore": "node_modules/\n"})
        self.base = helpers.sh(self.repo, "rev-parse", "HEAD").decode().strip()

    def tearDown(self):
        self._tmp.cleanup()

    def test_scope_pass_and_block(self):
        helpers.write(self.repo, {"src/a.js": "a2\n"})
        r = scope.check(self.repo, self.base, ["src/**"])
        self.assertEqual(("pass", ["src/a.js"]), (r["verdict"], r["changed"]))
        helpers.write(self.repo, {"README.md": "bye\n"})
        r = scope.check(self.repo, self.base, ["src/**"])
        self.assertEqual("blocked", r["verdict"])
        self.assertEqual(["README.md"], r["violations"])

    def test_scope_untracked_counted_ignored_not(self):
        helpers.write(self.repo, {"x.txt": "x\n", "node_modules/a.js": "m\n"})
        r = scope.check(self.repo, self.base, ["src/**"])
        self.assertEqual(["x.txt"], r["violations"])

    def test_scope_symlink_escape(self):
        os.symlink("/etc/hosts", self.repo / "src/l")
        os.symlink("a.js", self.repo / "src/inside")
        r = scope.check(self.repo, self.base, ["src/**"])
        self.assertEqual(["src/l"], r["violations"])

    def test_scope_unicode_paths(self):
        helpers.write(self.repo, {"docs/বুকিং নোট.md": "নোট\n"})
        r = scope.check(self.repo, self.base, ["docs/**"])
        self.assertEqual("pass", r["verdict"])
        self.assertEqual(["docs/বুকিং নোট.md"], r["changed"])

    def test_scope_evidence_exempt(self):
        rec = "docs/compound-v/runs/20261022-101500-x.json"
        helpers.write(self.repo, {rec: "{}", "docs/compound-v/plans/p.md": "plan\n"})
        helpers.commit_all(self.repo)
        helpers.write(self.repo, {rec: "{\"x\": 1}", "docs/compound-v/specs/s.md": "spec\n",
                                  "docs/compound-v/runs/runtime.py": "v = 0\n"})
        self.assertEqual(["docs/compound-v/runs/runtime.py"],
                         scope.check(self.repo, self.base, ["src/**"])["violations"])

    def test_scope_rename_and_delete_both_sides(self):
        (self.repo / "lib").mkdir()
        helpers.sh(self.repo, "mv", "src/a.js", "lib/a.js")
        (self.repo / "README.md").unlink()
        r = scope.check(self.repo, self.base, ["src/**"])
        self.assertEqual(["README.md", "lib/a.js"], r["violations"])
        self.assertIn("src/a.js", r["changed"])

    def test_cli_scope_uses_run_change_set(self):
        from cvcore import run
        run.start(self.repo, tier="light", request="x", change_set=["src/**"])
        helpers.write(self.repo, {"src/a.js": "a2\n"})
        r = helpers.cli(self.repo, "scope")
        self.assertEqual(0, r.returncode, r.stderr)
        helpers.write(self.repo, {"README.md": "bye\n"})
        r = helpers.cli(self.repo, "scope")
        self.assertEqual(1, r.returncode)
        self.assertIn("README.md", r.stdout)

    def test_matches(self):
        m = scope.matches
        self.assertTrue(m("a/b/c.tsx", ["**/*.{tsx,jsx}"]))
        self.assertTrue(m("c.jsx", ["**/*.{tsx,jsx}"]))
        self.assertFalse(m("src/a/b.js", ["src/*.js"]))
        self.assertTrue(m("src/a/b.js", ["src/**"]))
        self.assertFalse(m("srcx/a.js", ["src/**"]))
        self.assertFalse(m("src/a\nb.js", ["src/**", "**"]))
        self.assertTrue(m("README.md", ["README.md"]))


if __name__ == "__main__":
    unittest.main()
