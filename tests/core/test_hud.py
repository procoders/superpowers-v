from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402

from cvcore import hud, receipts, run  # noqa: E402


class HudTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._key = receipts.KEY_PATH
        self.repo = helpers.make_repo(self.tmp, {"c": "1\n"})
        receipts.KEY_PATH = helpers.key_path(self.repo)

    def tearDown(self):
        receipts.KEY_PATH = self._key
        self._tmp.cleanup()

    def test_band_empty_without_run(self):
        self.assertEqual({}, hud.band(self.repo))
        self.assertEqual("", hud.brief(self.repo))

    def test_brief_names_missing_steps(self):
        rec = run.start(self.repo, tier="full", request="add salon booking")
        rec["test_cmd"] = "true"
        run.set_stage(self.repo, rec, "verify")
        receipts.run_step(self.repo, run.load(self.repo, rec["id"]), "tests")
        text = hud.brief(self.repo, "s1")
        self.assertTrue(text.startswith(f"Compound V run {rec['id']}: stage verify (full); "),
                        text)
        self.assertIn("missing review, live, scope", text)
        self.assertTrue(text.endswith("next: /compound-v:verify"), text)
        b = hud.band(self.repo, "s1")
        self.assertEqual({"tests": "pass", "review": "missing", "live": "missing",
                          "scope": "missing"}, b["steps"])
        self.assertEqual(("verify", "full", "pending", None),
                         (b["stage"], b["tier"], b["outcome"], b["cost_usd"]))
        r = helpers.cli(self.repo, "hud", "--brief")
        self.assertEqual(text, r.stdout.strip())
        self.assertEqual(rec["id"], json.loads(helpers.cli(self.repo, "hud").stdout)["run"])

    def test_cochange_counts(self):
        for i in range(3):
            helpers.write(self.repo, {"a": f"{i}\n", "b": f"{i}\n"})
            helpers.commit_all(self.repo, f"ab {i}")
        helpers.write(self.repo, {"a": "x\n", "c": "x\n"})
        helpers.commit_all(self.repo, "ac")
        got = hud.cochange(self.repo, ["a"])
        self.assertEqual({"path": "b", "count": 3}, got[0])
        self.assertEqual({"path": "c", "count": 1}, got[1])
        r = helpers.cli(self.repo, "cochange", "--path", "a")
        self.assertEqual(got, json.loads(r.stdout))


if __name__ == "__main__":
    unittest.main()
