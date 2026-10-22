from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402

from cvcore import escalate  # noqa: E402


class EscalateTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = helpers.make_repo(Path(self._tmp.name), {
            "README.md": "Welcome to the salon app\n",
            "public/index.html": "<h1>Hello there</h1>\n",
            "docs/compound-v/specs/s.md": "login and payments\n"})
        self.base = helpers.sh(self.repo, "rev-parse", "HEAD").decode().strip()

    def tearDown(self):
        self._tmp.cleanup()

    def classify(self):
        return escalate.classify_diff(self.repo, self.base)

    def test_escalate_auth_in_innocent_file(self):
        helpers.write(self.repo, {"utils/helpers.js": "res.cookie('sid', token)\n"})
        r = self.classify()
        self.assertEqual("full", r["tier"])
        self.assertIn("auth", r["reasons"])

    def test_escalate_copy_change_light(self):
        helpers.write(self.repo, {"README.md": "Welcome to the salon site\n",
                                  "docs/compound-v/specs/s.md": "more login words\n"})
        r = self.classify()
        self.assertEqual(("light", False), (r["tier"], r["touches_ui"]))

    def test_escalate_ui_flag(self):
        helpers.write(self.repo, {"public/index.html": "<h1>Hello friend</h1>\n"})
        r = self.classify()
        self.assertEqual(("light", True), (r["tier"], r["touches_ui"]))

    def test_escalate_binary_full(self):
        helpers.write(self.repo, {"logo.png": b"\x89PNG\r\n\x1a\n\x00\x00\x00"})
        helpers.commit_all(self.repo)
        self.base = helpers.sh(self.repo, "rev-parse", "HEAD").decode().strip()
        helpers.write(self.repo, {"logo.png": b"\x89PNG\r\n\x1a\n\x00\x01\x00"})
        r = self.classify()
        self.assertEqual("full", r["tier"])
        self.assertIn("unclassifiable", r["reasons"])

    def test_escalate_untracked_binary_and_size(self):
        helpers.write(self.repo, {"blob.bin": b"\x00\xff\x00"})
        self.assertIn("unclassifiable", self.classify()["reasons"])
        (self.repo / "blob.bin").unlink()
        helpers.write(self.repo, {"notes.txt": "line\n" * 301})
        r = self.classify()
        self.assertEqual("full", r["tier"])
        self.assertTrue(any(x.startswith("large") for x in r["reasons"]))

    def test_classify_request(self):
        c = escalate.classify_request
        self.assertEqual("light", c("fix typo in README"))
        self.assertEqual("full", c("add login"))
        self.assertIsNone(c("hmm"))
        self.assertEqual("light", c("исправь опечатку в README"))
        self.assertEqual("full", c("fix the typo in the login form"))
        self.assertEqual("full", c("добавь страницу записи"))

    def test_cli_escalate_and_classify_request(self):
        helpers.write(self.repo, {"utils/h.js": "jwt.sign(x)\n"})
        r = helpers.cli(self.repo, "escalate", "--base", self.base)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn('"full"', r.stdout)
        r = helpers.cli(self.repo, "classify-request", stdin="fix typo in README")
        self.assertIn('"light"', r.stdout)


if __name__ == "__main__":
    unittest.main()
